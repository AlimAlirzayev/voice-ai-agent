"""The LangGraph agent: the Divan council (Lesson 31 base + multi-agent supervisor + HITL).

Council roster: Molla Nəsrəddin (wit), Koroğlu (courage/action), Simurğ (wisdom).

    START -> intake -> supervisor -> {nesreddin,koroglu,simurg} -> supervisor (loop)
                                   \\-> synthesize -> approval_gate -> trim -> END
                                                    \\-> deliver ----/      \\-> END

* state       - `ChatState.messages`, accumulated by the `add_messages` reducer;
                per-turn routing scratch (`consulted`, `opinions`, `hops`,
                `draft`, `needs_approval`) is reset by `intake` so nothing
                leaks across turns.
* supervisor  - one cheap LLM call (temperature 0) naming the next advisor to
                consult, or YEKUN when the council is done; routes via `Command`.
* advisors    - each advisor gives a short, domain-only opinion, then returns
                control to the supervisor.
* synthesize  - merges the opinions (or uses the lone opinion verbatim) into a
                draft reply; flags `needs_approval` when Koroğlu (bold/risky
                action) spoke - his advice is the one worth a human pause.
* approval_gate - calls `interrupt()` to pause the run and surface the draft to
                a human. Resuming with `Command(resume={"decision": ...})`
                re-enters this node and turns the decision into the final
                message: approve -> the draft verbatim, edit -> the human's
                text, reject -> a short declined-to-advise line.
* deliver     - the no-approval-needed path: the draft becomes the final
                message directly.
* trim        - unchanged: drops the oldest messages once history grows too long,
                using `RemoveMessage` so the reducer deletes them from the checkpoint.
* checkpoint  - supplied by the caller; keyed by `thread_id`, so every chat has
                its own memory that survives a restart. A checkpointer is
                required for `interrupt()`/`Command(resume=...)` to work.
"""

import hashlib
import os
import uuid
from dataclasses import dataclass
from typing import Annotated, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    HumanMessage,
    RemoveMessage,
    SystemMessage,
)
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import Command, interrupt

from app.core.config import settings
from app.graph.guardrails import crisis_response, is_self_harm_risk
from app.prompts.divan import (
    NARRATION_HITL,
    NARRATION_OPENING,
    NARRATION_ROUTING,
    NARRATION_SYNTHESIS,
    ROSTER,
    SYNTHESIS_PROMPT,
    advisor_prompt,
    supervisor_prompt,
)
from app.services.llm import ainvoke_with_retry, build_llm

ADVISOR_KEYS = tuple(ROSTER.keys())
MAX_ADVISORS = 2
RECURSION_LIMIT = 10
APPROVAL_ADVISOR = "koroglu"  # bold/risky calls to action are what pause for a human


class ChatState(TypedDict):
    """`add_messages` appends new messages instead of overwriting the list.

    `consulted`/`opinions`/`hops`/`draft`/`needs_approval`/`narration` are
    per-turn routing scratch: `intake` resets them at the start of every turn
    so nothing leaks from the previous one. `narration` is the Divanbəyi's
    own brief, hand-written commentary on what the graph is doing as it does
    it (see `app/prompts/divan.py`) - surfaced to callers via
    `TurnResult.narration` for the frontend/bot to show or speak.
    """

    messages: Annotated[list[AnyMessage], add_messages]
    consulted: list[str]
    opinions: list[dict]
    hops: int
    draft: str
    needs_approval: bool
    narration: list[str]


@dataclass
class TurnResult:
    """What one graph run produced - either a normal reply, or a paused one
    waiting on `resume_turn()` with a human decision."""

    status: str  # "ok" | "pending_approval"
    reply: str
    history_length: int
    approval: dict | None = None
    consulted: list[str] | None = None
    opinions: list[dict] | None = None
    turn_id: str = ""
    narration: list[str] | None = None


def build_graph(checkpointer, llm: BaseChatModel | None = None):
    """Compile the agent. `llm` is injectable so tests can pass a fake model."""
    keep = settings.MAX_HISTORY_MESSAGES

    def get_model():
        return llm if llm is not None else build_llm()

    def intake(state: ChatState) -> dict:
        return {
            "consulted": [],
            "opinions": [],
            "hops": 0,
            "draft": "",
            "needs_approval": False,
            "narration": [],
        }

    async def supervisor(state: ChatState) -> Command:
        consulted = state.get("consulted", [])
        hops = state.get("hops", 0) + 1
        remaining = [key for key in ADVISOR_KEYS if key not in consulted]
        narration = state.get("narration", [])
        if hops == 1:
            narration = [*narration, NARRATION_OPENING]

        if not remaining or len(consulted) >= MAX_ADVISORS or hops > MAX_ADVISORS + 2:
            return Command(update={"hops": hops, "narration": narration}, goto="synthesize")

        decision = await ainvoke_with_retry(
            get_model(),
            [SystemMessage(content=supervisor_prompt()), *state["messages"]],
            label="llm-supervisor",
        )
        raw = (decision.content or "").strip().lower()
        token = raw.split()[0].strip(".,!?") if raw else ""

        if token in remaining:
            next_node = token
        elif token.startswith("yek"):
            next_node = "synthesize"
        else:
            next_node = remaining[0]

        if next_node in NARRATION_ROUTING:
            narration = [*narration, NARRATION_ROUTING[next_node]]

        return Command(update={"hops": hops, "narration": narration}, goto=next_node)

    def make_advisor(key: str):
        async def advisor(state: ChatState) -> Command:
            reply = await ainvoke_with_retry(
                get_model(),
                [SystemMessage(content=advisor_prompt(key)), *state["messages"]],
                label=f"llm-advisor-{key}",
            )
            opinion = {"advisor": key, "name": ROSTER[key]["name"], "text": reply.content}
            return Command(
                update={
                    "opinions": state.get("opinions", []) + [opinion],
                    "consulted": state.get("consulted", []) + [key],
                },
                goto="supervisor",
            )

        return advisor

    async def synthesize(state: ChatState) -> dict:
        opinions = state.get("opinions", [])
        narration = state.get("narration", [])

        if not opinions:
            reply = await ainvoke_with_retry(
                get_model(),
                [SystemMessage(content=SYNTHESIS_PROMPT), *state["messages"]],
                label="llm-synthesis",
            )
            text = reply.content
        elif len(opinions) == 1:
            text = opinions[0]["text"]
        else:
            narration = [*narration, NARRATION_SYNTHESIS]
            merged = "\n".join(f"{o['name']}: {o['text']}" for o in opinions)
            reply = await ainvoke_with_retry(
                get_model(),
                [
                    SystemMessage(content=SYNTHESIS_PROMPT),
                    *state["messages"],
                    HumanMessage(content=merged),
                ],
                label="llm-synthesis",
            )
            text = reply.content

        needs_approval = APPROVAL_ADVISOR in state.get("consulted", [])
        if needs_approval:
            narration = [*narration, NARRATION_HITL]
        return {"draft": text, "needs_approval": needs_approval, "narration": narration}

    def route_after_synthesis(state: ChatState) -> str:
        return "approval_gate" if state.get("needs_approval") else "deliver"

    def approval_gate(state: ChatState) -> dict:
        """Pauses the run and hands the draft to a human. `interrupt()` raises
        on the first pass (halting here); resuming with `Command(resume=...)`
        re-enters this same node from the top and returns the resume value."""
        decision = interrupt(
            {
                "kind": "hitl_approval",
                "advisor": ROSTER[APPROVAL_ADVISOR]["name"],
                "advisor_key": APPROVAL_ADVISOR,
                "question": "Bu, Koroğlunun cəsarətli tövsiyəsidir. Onu son cavab kimi təsdiqləyirsiniz?",
                "draft": state["draft"],
            }
        )
        action = decision.get("decision", "approve") if isinstance(decision, dict) else str(decision)

        if action == "reject":
            final = (
                "Onda bunu qəti tövsiyə kimi bildirmirəm — bu, sadəcə şuranın "
                "fikir mübadiləsi olaraq qaldı."
            )
        elif action == "edit" and isinstance(decision, dict) and decision.get("text"):
            final = decision["text"]
        else:
            final = state["draft"]

        return {"messages": [AIMessage(content=final)]}

    def deliver(state: ChatState) -> dict:
        return {"messages": [AIMessage(content=state["draft"])]}

    def needs_trim(state: ChatState) -> str:
        return "trim" if len(state["messages"]) > keep else END

    def trim(state: ChatState) -> dict:
        stale = state["messages"][:-keep]
        return {"messages": [RemoveMessage(id=m.id) for m in stale]}

    builder = StateGraph(ChatState)
    builder.add_node("intake", intake)
    builder.add_node("supervisor", supervisor)
    for key in ADVISOR_KEYS:
        builder.add_node(key, make_advisor(key))
    builder.add_node("synthesize", synthesize)
    builder.add_node("approval_gate", approval_gate)
    builder.add_node("deliver", deliver)
    builder.add_node("trim", trim)

    builder.add_edge(START, "intake")
    builder.add_edge("intake", "supervisor")
    builder.add_conditional_edges("synthesize", route_after_synthesis, ["approval_gate", "deliver"])
    builder.add_conditional_edges("approval_gate", needs_trim, ["trim", END])
    builder.add_conditional_edges("deliver", needs_trim, ["trim", END])
    builder.add_edge("trim", END)

    return builder.compile(checkpointer=checkpointer)


def _trace_config(thread_id: str, *, channel: str, modality: str) -> dict:
    """Build safe LangSmith metadata without exposing raw conversation ids."""
    provider = settings.chat_provider
    model = settings.chat_model
    thread_hash = hashlib.sha256(thread_id.encode()).hexdigest()[:12]
    return {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": RECURSION_LIMIT,
        "run_name": "voice-ai-agent-turn",
        "tags": ["voice-ai-agent", channel, modality, provider],
        "metadata": {
            "channel": channel,
            "modality": modality,
            "llm_provider": provider,
            "llm_model": model,
            "environment": os.getenv("APP_ENV", "local"),
            "app_version": os.getenv("APP_VERSION", "unversioned"),
            "thread_id_hash": thread_hash,
        },
    }


def _new_turn_id() -> str:
    """Short id a completed reply can be referenced by later - e.g. to attach
    feedback (see `app/api/feedback.py`). Not persisted in graph state; each
    finished turn simply gets a fresh one."""
    return uuid.uuid4().hex[:12]


def _extract_result(raw: dict) -> TurnResult:
    pending = raw.get("__interrupt__")
    if pending:
        payload = pending[0].value
        return TurnResult(
            status="pending_approval",
            reply=payload.get("question", ""),
            history_length=0,
            approval=payload,
            consulted=raw.get("consulted", []),
            opinions=raw.get("opinions", []),
            turn_id=_new_turn_id(),
            narration=raw.get("narration", []),
        )
    messages = raw.get("messages", [])
    reply = messages[-1].content if messages else ""
    return TurnResult(
        status="ok",
        reply=reply,
        history_length=len(messages),
        consulted=raw.get("consulted", []),
        opinions=raw.get("opinions", []),
        turn_id=_new_turn_id(),
        narration=raw.get("narration", []),
    )


async def get_pending(graph, thread_id: str) -> TurnResult | None:
    """Check whether this thread already has a paused turn awaiting a human
    decision, without running or restarting the graph.

    Feeding a *new* message into a thread whose previous turn is still parked
    at `approval_gate` would start a fresh run on top of the paused one and
    corrupt the pause - callers must check this first and, if it returns
    something, show that instead of invoking the graph again.
    """
    snapshot = await graph.aget_state(
        _trace_config(thread_id, channel="internal", modality="text")
    )
    if not snapshot.next or not snapshot.interrupts:
        return None

    payload = snapshot.interrupts[0].value
    values = snapshot.values or {}
    return TurnResult(
        status="pending_approval",
        reply=payload.get("question", ""),
        history_length=0,
        approval=payload,
        consulted=values.get("consulted", []),
        opinions=values.get("opinions", []),
        turn_id=_new_turn_id(),
        narration=values.get("narration", []),
    )


async def run_turn(
    graph,
    message: str,
    thread_id: str,
    *,
    channel: str = "api",
    modality: str = "text",
) -> TurnResult:
    """Run one conversation turn. May come back `pending_approval` if the
    council's answer needs a human sign-off - see `resume_turn`. Callers
    should check `get_pending` first; this function does not do it itself so
    that it stays a plain "run one turn" primitive `resume_turn` can share.

    A message flagged as a self-harm risk never reaches the council at all -
    no persona, however well-meaning, should role-play a reply to that. It
    gets a direct, human, out-of-character response instead."""
    if is_self_harm_risk(message):
        return TurnResult(
            status="ok",
            reply=crisis_response(),
            history_length=0,
            consulted=[],
            opinions=[],
            turn_id=_new_turn_id(),
        )

    raw = await graph.ainvoke(
        {"messages": [HumanMessage(content=message)]},
        config=_trace_config(thread_id, channel=channel, modality=modality),
    )
    return _extract_result(raw)


async def resume_turn(
    graph,
    thread_id: str,
    decision: dict,
    *,
    channel: str = "api",
    modality: str = "text",
) -> TurnResult:
    """Continue a `pending_approval` turn with a human decision, e.g.
    `{"decision": "approve"}`, `{"decision": "reject"}`, or
    `{"decision": "edit", "text": "..."}`."""
    raw = await graph.ainvoke(
        Command(resume=decision),
        config=_trace_config(thread_id, channel=channel, modality=modality),
    )
    return _extract_result(raw)
