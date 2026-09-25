import pytest

from app.core import config as config_module
from app.core.config import settings
from app.core.rate_limit import reset_rate_limits
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
