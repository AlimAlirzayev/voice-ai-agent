import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.memory import InMemorySaver

from app.graph import build_graph, get_pending, resume_turn, run_turn
from app.prompts.divan import NARRATION_OPENING
from app.services import retry as retry_module


class EchoModel:
    """Declines the council (always YEKUN) and echoes the user's message back,
    so the net behaviour matches the pre-multi-agent graph for this test."""

    async def ainvoke(self, messages):
        system = messages[0].content if messages and isinstance(messages[0], SystemMessage) else ""
        if "Divanbəyi" in system:
            return AIMessage(content="YEKUN")
        human_messages = [message for message in messages if isinstance(message, HumanMessage)]
        return AIMessage(content=f"echo: {human_messages[-1].content}")


class RoutingModel:
    """Routes to Koroğlu once, then ends the council - so the run exercises
    the HITL approval gate that his bold/risky advice always triggers."""

    def __init__(self):
        self.supervisor_calls = 0

    async def ainvoke(self, messages):
        system = messages[0].content if messages and isinstance(messages[0], SystemMessage) else ""
        if "Divanbəyi" in system:
            self.supervisor_calls += 1
            return AIMessage(content="KOROGLU" if self.supervisor_calls == 1 else "YEKUN")
        if "Koroğlu" in system:
            return AIMessage(content="Qorxma, qərarını ver və irəli addımla.")
        human_messages = [message for message in messages if isinstance(message, HumanMessage)]
        return AIMessage(content=f"echo: {human_messages[-1].content}")


class RateLimitError(Exception):
    """Stand-in for `openai.RateLimitError`/`groq.RateLimitError`. The retry
    helper (`app.services.retry.is_transient_error`) classifies purely by
    exception class name, so a lookalike defined here is enough to exercise
    it without importing a real provider SDK."""


class FlakyThenOkModel:
    """Fails the first `fail_times` LLM calls of the run with a
    transient-looking error, then behaves like `EchoModel`. Every LLM call
    site in `app/graph/builder.py` goes through `ainvoke_with_retry`, so the
    very first call (the supervisor's routing decision) already gets retried
    - this proves that retry actually recovers the turn instead of it dying
    on the first blip."""

    def __init__(self, fail_times: int):
        self.fail_times = fail_times
        self.calls = 0

    async def ainvoke(self, messages):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RateLimitError("temporary rate limit")
        system = messages[0].content if messages and isinstance(messages[0], SystemMessage) else ""
        if "Divanbəyi" in system:
            return AIMessage(content="YEKUN")
        human_messages = [message for message in messages if isinstance(message, HumanMessage)]
        return AIMessage(content=f"echo: {human_messages[-1].content}")


class AlwaysFailingModel:
    """Fails every call with the same transient-looking error - used to prove
    that once retries are exhausted, the *original* error is what surfaces,
    not something swallowed or replaced."""

    def __init__(self):
        self.calls = 0

    async def ainvoke(self, messages):
        self.calls += 1
        raise RateLimitError("still rate limited")


class RecordingGraph:
    def __init__(self):
        self.config = None

    async def ainvoke(self, payload, config):
        self.config = config
        return {"messages": [HumanMessage(content="input"), AIMessage(content="reply")]}


@pytest.mark.asyncio
async def test_graph_keeps_thread_memory():
    graph = build_graph(InMemorySaver(), llm=EchoModel())

    first = await run_turn(graph, "Mənim adım Alimdir.", "t-1")
    second = await run_turn(graph, "Adım nədir?", "t-1")

    assert first.status == "ok"
    assert first.reply == "echo: Mənim adım Alimdir."
    assert second.reply == "echo: Adım nədir?"
    assert first.history_length == 2
    assert second.history_length == 4


@pytest.mark.asyncio
async def test_graph_recovers_from_transient_llm_failure(monkeypatch):
    """A transient failure (e.g. a rate limit) on the supervisor's very first
    routing call must not kill the turn: `ainvoke_with_retry` (shared by
    every LLM call site in `app/graph/builder.py`) should retry it and let
    the turn finish exactly as it would have without the blip."""
    monkeypatch.setattr(retry_module, "DEFAULT_BACKOFF", (0.0, 0.0))
    model = FlakyThenOkModel(fail_times=2)
    graph = build_graph(InMemorySaver(), llm=model)

    result = await run_turn(graph, "Salam", "flaky-1")

    assert result.status == "ok"
    assert result.reply == "echo: Salam"
    # 2 failed attempts + 1 successful supervisor call (the retry cycle this
    # test targets), plus one more successful call for the no-opinions
    # synthesis step that always follows an immediate YEKUN.
    assert model.calls == retry_module.DEFAULT_ATTEMPTS + 1


@pytest.mark.asyncio
async def test_graph_raises_original_error_once_llm_retries_are_exhausted(monkeypatch):
    """If the model never recovers, `run_turn` must propagate the *original*
    exception unchanged after exhausting retries - not a generic/mangled
    error, and not silently swallowed."""
    monkeypatch.setattr(retry_module, "DEFAULT_BACKOFF", (0.0, 0.0))
    model = AlwaysFailingModel()
    graph = build_graph(InMemorySaver(), llm=model)

    with pytest.raises(RateLimitError, match="still rate limited"):
        await run_turn(graph, "Salam", "flaky-2")

    assert model.calls == retry_module.DEFAULT_ATTEMPTS


@pytest.mark.asyncio
async def test_bold_advice_pauses_for_approval_then_resumes():
    graph = build_graph(InMemorySaver(), llm=RoutingModel())

    paused = await run_turn(graph, "Bu riskli addımı atmalıyammı?", "hitl-1")
    assert paused.status == "pending_approval"
    assert paused.approval["advisor"] == "Koroğlu"
    assert "irəli addımla" in paused.approval["draft"]

    approved = await resume_turn(graph, "hitl-1", {"decision": "approve"})
    assert approved.status == "ok"
    assert approved.reply == paused.approval["draft"]
    assert approved.history_length == 2


@pytest.mark.asyncio
async def test_bold_advice_rejected_by_human_is_not_delivered():
    graph = build_graph(InMemorySaver(), llm=RoutingModel())

    paused = await run_turn(graph, "Bu riskli addımı atmalıyammı?", "hitl-2")
    assert paused.status == "pending_approval"

    rejected = await resume_turn(graph, "hitl-2", {"decision": "reject"})
    assert rejected.status == "ok"
    assert rejected.reply != paused.approval["draft"]
    assert "qəti tövsiyə" in rejected.reply


@pytest.mark.asyncio
async def test_narration_explains_routing_and_hitl_in_order():
    """The Divanbəyi's own commentary: opening line, then which advisor got
    the floor and why, then the HITL warning - in that order, before the
    council's own answer even needs a human decision."""
    graph = build_graph(InMemorySaver(), llm=RoutingModel())

    paused = await run_turn(graph, "Bu riskli addımı atmalıyammı?", "narration-1")

    assert paused.narration is not None
    assert len(paused.narration) == 3
    assert "marşrutlaşdırma" in paused.narration[0]
    assert "Koroğluya verirəm" in paused.narration[1]
    assert "Human-in-the-Loop" in paused.narration[2]


@pytest.mark.asyncio
async def test_narration_resets_between_turns_and_threads():
    """`intake` must clear `narration` at the start of every turn - a thread
    that never talks to Koroğlu should never see his HITL line, even after
    a *different* thread on the same graph triggered it."""
    graph = build_graph(InMemorySaver(), llm=RoutingModel())
    await run_turn(graph, "Bu riskli addımı atmalıyammı?", "narration-a")  # 3-line HITL turn

    quiet = await run_turn(graph, "Salam", "narration-b")  # unrelated thread, same graph/model

    assert quiet.narration == [NARRATION_OPENING]


@pytest.mark.asyncio
async def test_get_pending_blocks_new_input_until_resolved():
    """A second message sent while a turn is paused must not restart the
    graph - it should just re-surface the same pending approval."""
    graph = build_graph(InMemorySaver(), llm=RoutingModel())

    paused = await run_turn(graph, "Bu riskli addımı atmalıyammı?", "hitl-3")
    assert paused.status == "pending_approval"

    assert await get_pending(graph, "no-pending-thread") is None

    still_pending = await get_pending(graph, "hitl-3")
    assert still_pending is not None
    assert still_pending.status == "pending_approval"
    assert still_pending.approval == paused.approval

    resolved = await resume_turn(graph, "hitl-3", {"decision": "approve"})
    assert resolved.status == "ok"
    assert await get_pending(graph, "hitl-3") is None


@pytest.mark.asyncio
async def test_self_harm_message_bypasses_the_council_entirely():
    """No persona should role-play a reply to this - it must never even
    reach the model, let alone a specific advisor."""

    class ExplodingModel:
        async def ainvoke(self, messages):
            raise AssertionError("the council must not be consulted for a self-harm message")

    graph = build_graph(InMemorySaver(), llm=ExplodingModel())

    result = await run_turn(graph, "Artıq yaşamaq istəmirəm, intihar etmək istəyirəm.", "crisis-1")

    assert result.status == "ok"
    assert result.consulted == []
    assert "kömək" in result.reply.lower()


@pytest.mark.asyncio
async def test_trace_metadata_is_safe_and_classifies_voice_turn(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("APP_VERSION", "abc123")
    graph = RecordingGraph()

    result = await run_turn(
        graph,
        "Salam",
        "private-thread-id",
        channel="telegram",
        modality="voice",
    )

    metadata = graph.config["metadata"]
    assert result.reply == "reply"
    assert result.history_length == 2
    assert graph.config["run_name"] == "voice-ai-agent-turn"
    assert graph.config["tags"] == ["voice-ai-agent", "telegram", "voice", "openai"]
    assert metadata == {
        "channel": "telegram",
        "modality": "voice",
        "llm_provider": "openai",
        "llm_model": "gpt-4.1-mini",
        "environment": "test",
        "app_version": "abc123",
        "thread_id_hash": metadata["thread_id_hash"],
    }
    assert metadata["thread_id_hash"] != "private-thread-id"
    assert len(metadata["thread_id_hash"]) == 12
