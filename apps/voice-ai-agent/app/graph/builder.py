"""The LangGraph agent: state, nodes, edges, checkpointing (Lesson 31).

    START -> agent -> (conditional) -> trim -> END
                   \\-> END

* state       - `ChatState.messages`, accumulated by the `add_messages` reducer.
* agent       - calls the LLM with the system prompt plus the whole history.
* trim        - drops the oldest messages once the history grows too long, using
                `RemoveMessage` so the reducer deletes them from the checkpoint.
* checkpoint  - supplied by the caller; keyed by `thread_id`, so every chat has
                its own memory that survives a restart.
"""

import hashlib
import os
from typing import Annotated, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AnyMessage,
    HumanMessage,
    RemoveMessage,
    SystemMessage,
)
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from app.core.config import settings
from app.prompts.system_prompt import SYSTEM_PROMPT
from app.services.llm import build_llm


class ChatState(TypedDict):
    """`add_messages` appends new messages instead of overwriting the list."""

    messages: Annotated[list[AnyMessage], add_messages]


def build_graph(checkpointer, llm: BaseChatModel | None = None):
    """Compile the agent. `llm` is injectable so tests can pass a fake model."""
    keep = settings.MAX_HISTORY_MESSAGES

    async def agent(state: ChatState) -> dict:
        model = llm if llm is not None else build_llm()
        reply = await model.ainvoke(
            [SystemMessage(content=SYSTEM_PROMPT), *state["messages"]]
        )
        return {"messages": [reply]}

    def needs_trim(state: ChatState) -> str:
        return "trim" if len(state["messages"]) > keep else END

    def trim(state: ChatState) -> dict:
        stale = state["messages"][:-keep]
        return {"messages": [RemoveMessage(id=m.id) for m in stale]}

    builder = StateGraph(ChatState)
    builder.add_node("agent", agent)
    builder.add_node("trim", trim)

    builder.add_edge(START, "agent")
    builder.add_conditional_edges("agent", needs_trim, ["trim", END])
    builder.add_edge("trim", END)

    return builder.compile(checkpointer=checkpointer)


def _trace_config(thread_id: str, *, channel: str, modality: str) -> dict:
    """Build safe LangSmith metadata without exposing raw conversation ids."""
    provider = settings.chat_provider
    model = settings.chat_model
    thread_hash = hashlib.sha256(thread_id.encode()).hexdigest()[:12]
    return {
        "configurable": {"thread_id": thread_id},
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


async def run_turn(
    graph,
    message: str,
    thread_id: str,
    *,
    channel: str = "api",
    modality: str = "text",
) -> tuple[str, int]:
    """Run one conversation turn and return (reply text, history length)."""
    result = await graph.ainvoke(
        {"messages": [HumanMessage(content=message)]},
        config=_trace_config(thread_id, channel=channel, modality=modality),
    )
    messages = result["messages"]
    reply = messages[-1].content if messages else ""
    return reply, len(messages)
