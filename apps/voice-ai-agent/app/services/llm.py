"""The single place where the chat model is constructed."""

from functools import lru_cache
from typing import Any

from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI

from app.core.config import settings
from app.services.retry import call_with_retry


class LLMError(RuntimeError):
    """Raised when the chat model cannot be used."""


async def ainvoke_with_retry(model: Any, messages: list, *, label: str = "llm-call") -> Any:
    """Call `model.ainvoke(messages)`, retrying transient failures.

    Shared by every LLM call site in `app/graph/builder.py` (supervisor
    routing, each advisor, synthesis) so a single dropped connection or rate
    limit doesn't kill a whole turn that may otherwise need several calls.
    `model` is duck-typed on purpose - both the real `ChatOpenAI`/`ChatGroq`
    and the fake models used in tests only need an async `ainvoke`.
    """
    return await call_with_retry(lambda: model.ainvoke(messages), label=label)


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
