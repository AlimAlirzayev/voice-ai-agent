"""The single place where the chat model is constructed."""

from langchain_openai import ChatOpenAI

from app.core.config import settings


def build_llm() -> ChatOpenAI:
    return ChatOpenAI(
        model=settings.OPENAI_MODEL,
        api_key=settings.OPENAI_API_KEY,
        temperature=0.7,
    )
