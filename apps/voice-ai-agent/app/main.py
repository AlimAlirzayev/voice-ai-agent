"""FastAPI entry point.

The graph and its SQLite checkpointer are built once at startup and shared by
every request, so all conversations write into the same memory file.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import chat, voice
from app.core.config import settings
from app.graph import build_graph
from app.memory.sqlite import Checkpointer


@asynccontextmanager
async def lifespan(app: FastAPI):
    checkpointer = Checkpointer()
    app.state.graph = build_graph(await checkpointer.open())
    try:
        yield
    finally:
        await checkpointer.close()


app = FastAPI(
    title="Voice AI Agent",
    description="FastAPI + LangGraph + Whisper + ElevenLabs, traced by LangSmith.",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(chat.router)
app.include_router(voice.router)


@app.get("/", tags=["health"])
async def root() -> dict:
    """Health check that also reports what is actually wired up."""
    return {
        "status": "ok",
        "llm": settings.chat_model if settings.llm_ready else "MISSING LLM API KEY",
        "llm_provider": settings.chat_provider,
        "stt": settings.OPENAI_STT_MODEL,
        "tts": settings.tts_provider,
        "langsmith_tracing": settings.tracing_enabled,
        "langsmith_project": settings.LANGSMITH_PROJECT if settings.tracing_enabled else None,
        "memory": str(settings.sqlite_file.name),
        "telegram_bot": bool(settings.TELEGRAM_BOT_TOKEN),
    }
