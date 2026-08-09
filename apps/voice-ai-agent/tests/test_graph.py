import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from app.graph import build_graph, run_turn


class EchoModel:
    async def ainvoke(self, messages):
        human_messages = [message for message in messages if isinstance(message, HumanMessage)]
        return AIMessage(content=f"echo: {human_messages[-1].content}")


class RecordingGraph:
    def __init__(self):
        self.config = None

    async def ainvoke(self, payload, config):
        self.config = config
        return {"messages": [HumanMessage(content="input"), AIMessage(content="reply")]}


@pytest.mark.asyncio
async def test_graph_keeps_thread_memory():
    graph = build_graph(InMemorySaver(), llm=EchoModel())

    first_reply, first_history_length = await run_turn(graph, "Mənim adım Alimdir.", "t-1")
    second_reply, second_history_length = await run_turn(graph, "Adım nədir?", "t-1")

    assert first_reply == "echo: Mənim adım Alimdir."
    assert second_reply == "echo: Adım nədir?"
    assert first_history_length == 2
    assert second_history_length == 4


@pytest.mark.asyncio
async def test_trace_metadata_is_safe_and_classifies_voice_turn(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("APP_VERSION", "abc123")
    graph = RecordingGraph()

    reply, history_length = await run_turn(
        graph,
        "Salam",
        "private-thread-id",
        channel="telegram",
        modality="voice",
    )

    metadata = graph.config["metadata"]
    assert reply == "reply"
    assert history_length == 2
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
