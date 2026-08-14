"""FastAPI entry point.

The graph and its SQLite checkpointer are built once at startup and shared by
every request, so all conversations write into the same memory file.
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.api import chat, feedback, voice, voicelab
from app.core.config import settings
from app.graph import build_graph
from app.memory.feedback import FeedbackStore
from app.memory.sqlite import Checkpointer

STATIC_DIR = Path(__file__).parent / "static"

log = logging.getLogger("app.client")


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
app.include_router(voicelab.router)

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
async def demo() -> HTMLResponse:
    """The live Divan council demo page (chat + HITL approval, in the browser).

    Asset URLs carry a `?v=<mtime>` stamp so a redeploy always busts the
    browser cache - a stale cached app.js against fresh HTML once shipped a
    silently dead feature (the Voice Lab tab stuck on its loading text).
    """
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    version = str(int((STATIC_DIR / "js" / "app.js").stat().st_mtime))
    return HTMLResponse(html.replace("__V__", version))


@app.post("/client-log", include_in_schema=False)
async def client_log(request: Request) -> dict:
    """Browser-side errors land here (window.onerror / unhandledrejection),
    so a broken frontend is visible in `docker compose logs api` instead of
    dying silently in the user's console."""
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001 - malformed beacon must not 500
        payload = {"raw": (await request.body())[:300].decode(errors="replace")}
    log.warning("client-error: %s", str(payload)[:600])
    return {"ok": True}
