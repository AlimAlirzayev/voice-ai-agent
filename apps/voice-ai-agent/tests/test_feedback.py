import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.memory.feedback import FeedbackStore
from app.services.llm import build_llm


@pytest.mark.asyncio
async def test_feedback_store_records_and_counts(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "FEEDBACK_PATH", str(tmp_path / "feedback.sqlite"))
    store = FeedbackStore()
    await store.open()
    try:
        await store.add(turn_id="t1", thread_id="demo", kind="up")
        await store.add(turn_id="t2", thread_id="demo", kind="down")
        await store.add(turn_id="t3", thread_id="demo", kind="correction", text="Düzgünü belə idi.")

        stats = await store.stats()
        assert stats == {"up": 1, "down": 1, "correction": 1, "total": 3}
    finally:
        await store.close()


def test_feedback_endpoint_stores_and_rejects_empty_correction(monkeypatch, tmp_path):
    build_llm.cache_clear()
    monkeypatch.setattr(settings, "SQLITE_PATH", str(tmp_path / "checkpoints.sqlite"))
    monkeypatch.setattr(settings, "FEEDBACK_PATH", str(tmp_path / "feedback.sqlite"))

    with TestClient(app) as client:
        up = client.post(
            "/feedback", json={"turn_id": "abc123", "thread_id": "demo", "kind": "up"}
        )
        assert up.status_code == 200
        assert up.json()["stored"] is True

        missing_text = client.post(
            "/feedback", json={"turn_id": "abc123", "thread_id": "demo", "kind": "correction"}
        )
        assert missing_text.status_code == 422

        correction = client.post(
            "/feedback",
            json={
                "turn_id": "abc123",
                "thread_id": "demo",
                "kind": "correction",
                "text": "Düzgün cavab bu idi.",
            },
        )
        assert correction.status_code == 200

        stats = client.get("/feedback/stats")
        assert stats.status_code == 200
        assert stats.json()["up"] == 1
        assert stats.json()["correction"] == 1
