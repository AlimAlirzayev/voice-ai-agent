"""FastAPI entry point.

The graph and its SQLite checkpointer are built once at startup and shared by
every request, so all conversations write into the same memory file.
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import chat, feedback, voice
from app.core.config import settings
from app.graph import build_graph
from app.memory.feedback import FeedbackStore
from app.memory.sqlite import Checkpointer

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    checkpointer = Checkpointer()
    feedback_store = FeedbackStore()
    app.state.graph = build_graph(await checkpointer.open())
    app.state.feedback = await feedback_store.open()
    try:
        yield
    finally:
        await checkpointer.close()
        await feedback_store.close()


app = FastAPI(
    title="Voice AI Agent",
    description="FastAPI + LangGraph + Whisper + ElevenLabs, traced by LangSmith.",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(chat.router)
app.include_router(voice.router)
app.include_router(feedback.router)

if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


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
        "feedback_store": str(settings.feedback_file.name),
        "telegram_bot": bool(settings.TELEGRAM_BOT_TOKEN),
        "demo": "/demo" if STATIC_DIR.is_dir() else None,
    }


@app.get("/demo", tags=["health"], include_in_schema=False)
async def demo() -> FileResponse:
    """The live Divan council demo page (chat + HITL approval, in the browser)."""
    return FileResponse(STATIC_DIR / "index.html")
