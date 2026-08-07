from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import InMemorySaver
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage
from typing import TypedDict

from app.core.config import settings


class State(TypedDict):
    message: str
    response: str


llm = ChatOpenAI(
    model="gpt-4.1-mini",
    api_key=settings.OPENAI_API_KEY,
)


def chat_node(state: State):
    result = llm.invoke([HumanMessage(content=state["message"])])
    return {"response": result.content}


builder = StateGraph(State)

builder.add_node("chat", chat_node)

builder.add_edge(START, "chat")
builder.add_edge("chat", END)

graph = builder.compile(
    checkpointer=InMemorySaver()
)