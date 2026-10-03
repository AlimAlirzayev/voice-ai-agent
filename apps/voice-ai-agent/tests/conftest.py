import pytest
from fastapi.testclient import TestClient

import app.api.voice as voice_api
import app.graph.builder as builder
from app.core import config as config_module
from app.core.config import settings
from app.core.rate_limit import reset_rate_limits
from app.main import app
from app.rag import retriever as retriever_module
from app.services import llm as llm_module
from app.services import voice as voice_module


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    """`TestClient` requests all share one fake client host ("testclient"),
    so the in-memory rate limiter's per-IP buckets would otherwise leak state
    between unrelated tests in the same process."""
    reset_rate_limits()
    yield
    reset_rate_limits()


@pytest.fixture(autouse=True)
def _isolate_from_live_env(monkeypatch):
    """Tests must see the code's defaults, never the machine's `.env`.

    Measured 2026-09-25: with a live `.env` on the box, one test sent fake
    audio to the real Groq endpoint and another saw the live model name.
    Every provider-selecting field is pinned here, the cached clients are
    dropped, and the Claude CLI is treated as absent so "auto" resolves the
    way the original tests were written (OpenAI unless a key says otherwise).
    """
    for name, value in {
        "LLM_PROVIDER": "auto", "OPENAI_API_KEY": "", "GROQ_API_KEY": "",
        "ELEVENLABS_API_KEY": "", "STT_BASE_URL": "", "STT_API_KEY": "", "STT_MODEL": "",
        "TTS_PROVIDER": "auto", "RAG_BACKEND": "auto", "MODERATION_ENABLED": True,
    }.items():
        monkeypatch.setattr(settings, name, value)
    monkeypatch.setattr(config_module.shutil, "which", lambda _name: None)
    llm_module.build_llm.cache_clear()
    retriever_module.get_retriever.cache_clear()
    voice_module._openai.cache_clear()
    voice_module._stt_client.cache_clear()
    voice_module._elevenlabs.cache_clear()
    yield
    llm_module.build_llm.cache_clear()
    retriever_module.get_retriever.cache_clear()
    voice_module._stt_client.cache_clear()


@pytest.fixture(autouse=True)
def _no_access_key(monkeypatch):
    """The live .env carries DIVAN_ACCESS_KEY for the public link; tests talk
    to the app directly and must not need it (test_access_key sets its own)."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "DIVAN_ACCESS_KEY", "")


@pytest.fixture
def make_client(monkeypatch, tmp_path):
    """Factory: `make_client(model)` -> a TestClient whose council uses `model`."""
    stack = []

    def _make(model, **settings_overrides):
        monkeypatch.setattr(settings, "SQLITE_PATH", str(tmp_path / "c.sqlite"))
        monkeypatch.setattr(settings, "FEEDBACK_PATH", str(tmp_path / "f.sqlite"))
        for key, value in settings_overrides.items():
            monkeypatch.setattr(settings, key, value)
        monkeypatch.setattr(builder, "build_llm", lambda: model)
        client = TestClient(app)
        client.__enter__()
        stack.append(client)
        return client

    yield _make
    for client in stack:
        client.__exit__(None, None, None)


@pytest.fixture
def spoken(monkeypatch):
    """Replace STT/TTS; `spoken` records (text, advisor) for every synthesized clip."""
    clips: list[tuple[str, str | None]] = []

    async def fake_transcribe(audio, filename):
        return audio.decode()

    async def fake_synthesize(text, advisor=None):
        clips.append((text, advisor))
        return b"OGG", "audio/ogg", "fake"

    monkeypatch.setattr(voice_api, "transcribe", fake_transcribe)
    monkeypatch.setattr(voice_api, "synthesize", fake_synthesize)
    return clips
