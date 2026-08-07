import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from app.graph import build_graph, run_turn


class EchoModel:
    async def ainvoke(self, messages):
        human_messages = [message for message in messages if isinstance(message, HumanMessage)]
        return AIMessage(content=f"echo: {human_messages[-1].content}")


@pytest.mark.asyncio
async def test_graph_keeps_thread_memory():
    graph = build_graph(InMemorySaver(), llm=EchoModel())

    first_reply, first_history_length = await run_turn(graph, "Mənim adım Alimdir.", "t-1")
    second_reply, second_history_length = await run_turn(graph, "Adım nədir?", "t-1")

    assert first_reply == "echo: Mənim adım Alimdir."
    assert second_reply == "echo: Adım nədir?"
    assert first_history_length == 2
    assert second_history_length == 4
