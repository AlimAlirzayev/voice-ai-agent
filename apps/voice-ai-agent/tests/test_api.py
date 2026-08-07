from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.services.llm import build_llm


def test_health_works_without_openai_key(monkeypatch, tmp_path):
    build_llm.cache_clear()
    monkeypatch.setattr(settings, "LLM_PROVIDER", "auto")
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "")
    monkeypatch.setattr(settings, "GROQ_API_KEY", "")
    monkeypatch.setattr(settings, "SQLITE_PATH", str(tmp_path / "checkpoints.sqlite"))

    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["llm"] == "MISSING LLM API KEY"


def test_chat_returns_clear_error_without_openai_key(monkeypatch, tmp_path):
    build_llm.cache_clear()
    monkeypatch.setattr(settings, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "")
    monkeypatch.setattr(settings, "GROQ_API_KEY", "")
    monkeypatch.setattr(settings, "SQLITE_PATH", str(tmp_path / "checkpoints.sqlite"))

    with TestClient(app) as client:
        response = client.post(
            "/chat",
            json={"thread_id": "test", "message": "Salam"},
        )

    assert response.status_code == 503
    assert response.json()["detail"] == "OPENAI_API_KEY is not set - add it to .env"
