"""Scripted chat model for offline evals and tests: no network, no keys.

It answers the three prompts the council sends - routing, host, advisor - from
a script, so an eval can exercise the *real* graph (routing resolution, HITL,
retrieval, citations, memory) with the model's behaviour held constant.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.prompts.divan import ROSTER

ROUTING_MARK = "Yalnız bir söz ilə cavab ver"
HOST_MARK = "Divanbəyisisən"


class ScriptedCouncilModel:
    """`route` is what the router says on its first call (then YEKUN); `reply`
    is what every advisor says; `host` is the host's greeting."""

    def __init__(self, route: str = "YEKUN", reply: str = "Sözümü dedim.", host: str = "Xoş gəlmisiniz."):
        self.route = route
        self.reply = reply
        self.host = host
        self.router_calls = 0
        self.advisor_systems: list[str] = []

    async def ainvoke(self, messages):
        system = messages[0].content if messages and isinstance(messages[0], SystemMessage) else ""
        if ROUTING_MARK in system:
            self.router_calls += 1
            return AIMessage(content=self.route if self.router_calls == 1 else "YEKUN")
        if HOST_MARK in system:
            return AIMessage(content=self.host)
        self.advisor_systems.append(system)
        user = [m for m in messages if isinstance(m, HumanMessage)]
        return AIMessage(content=self.reply if user else "")


def advisor_names() -> dict[str, str]:
    return {key: info["name"] for key, info in ROSTER.items()}
