"""The single place where the chat model is constructed."""

from functools import lru_cache

from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI

from app.core.config import settings


class LLMError(RuntimeError):
    """Raised when the chat model cannot be used."""


@lru_cache(maxsize=1)
def build_llm() -> ChatOpenAI | ChatGroq:
    if settings.chat_provider == "groq":
        if not settings.GROQ_API_KEY:
            raise LLMError("GROQ_API_KEY is not set - add it to .env")

        return ChatGroq(
            model=settings.GROQ_MODEL,
            api_key=settings.GROQ_API_KEY,
            temperature=0.7,
        )

    if not settings.OPENAI_API_KEY:
        raise LLMError("OPENAI_API_KEY is not set - add it to .env")

    return ChatOpenAI(
        model=settings.OPENAI_MODEL,
        api_key=settings.OPENAI_API_KEY,
        temperature=0.7,
    )
