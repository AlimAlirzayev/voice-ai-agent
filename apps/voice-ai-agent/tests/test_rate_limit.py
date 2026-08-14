"""Rate limiting: the pure counter logic in isolation, then the real
endpoints wired up behind it.

No OPENAI_API_KEY is needed for the endpoint tests: the rate limiter is a
FastAPI route dependency, so it runs (and can reject with 429) before the
handler body ever touches the LLM. An allowed-through request with no API
key configured still fails, just with a different, pre-existing status
(503/400) - that difference is exactly how these tests prove a request was
let past the limiter rather than blocked by it.
"""

import time

from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.rate_limit import (
    RATE_LIMIT_DETAIL,
    SlidingWindowRateLimiter,
    enforce_feedback_rate_limit,
    enforce_turn_rate_limit,
)
from app.main import app
from app.services.llm import build_llm


class TestSlidingWindowRateLimiter:
    def test_allows_up_to_the_limit_then_blocks(self):
        limiter = SlidingWindowRateLimiter()
        assert limiter.allow("ip-a", limit=3, window_seconds=60) is True
        assert limiter.allow("ip-a", limit=3, window_seconds=60) is True
        assert limiter.allow("ip-a", limit=3, window_seconds=60) is True
        assert limiter.allow("ip-a", limit=3, window_seconds=60) is False

    def test_keys_are_independent(self):
        limiter = SlidingWindowRateLimiter()
        for _ in range(3):
            assert limiter.allow("ip-a", limit=3, window_seconds=60) is True
        assert limiter.allow("ip-a", limit=3, window_seconds=60) is False
        # a different key has its own, untouched budget
        assert limiter.allow("ip-b", limit=3, window_seconds=60) is True

    def test_zero_limit_disables_the_limiter(self):
        limiter = SlidingWindowRateLimiter()
        for _ in range(50):
            assert limiter.allow("ip-a", limit=0, window_seconds=60) is True

    def test_allows_again_once_the_window_elapses(self, monkeypatch):
        limiter = SlidingWindowRateLimiter()
        fake_now = [1000.0]
        monkeypatch.setattr("app.core.rate_limit.time.monotonic", lambda: fake_now[0])

        assert limiter.allow("ip-a", limit=1, window_seconds=10) is True
        assert limiter.allow("ip-a", limit=1, window_seconds=10) is False

        fake_now[0] += 10.01  # past the window
        assert limiter.allow("ip-a", limit=1, window_seconds=10) is True

    def test_reset_clears_every_key(self):
        limiter = SlidingWindowRateLimiter()
        assert limiter.allow("ip-a", limit=1, window_seconds=60) is True
        assert limiter.allow("ip-a", limit=1, window_seconds=60) is False

        limiter.reset()

        assert limiter.allow("ip-a", limit=1, window_seconds=60) is True


def _configure(monkeypatch, tmp_path, **overrides):
    build_llm.cache_clear()
    monkeypatch.setattr(settings, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "")
    monkeypatch.setattr(settings, "GROQ_API_KEY", "")
    monkeypatch.setattr(settings, "MODERATION_ENABLED", False)
    monkeypatch.setattr(settings, "SQLITE_PATH", str(tmp_path / "checkpoints.sqlite"))
    monkeypatch.setattr(settings, "FEEDBACK_PATH", str(tmp_path / "feedback.sqlite"))
    monkeypatch.setattr(settings, "RATE_LIMIT_WINDOW_SECONDS", 0.3)
    monkeypatch.setattr(settings, "RATE_LIMIT_PER_MINUTE", 20)
    monkeypatch.setattr(settings, "RATE_LIMIT_FEEDBACK_PER_MINUTE", 60)
    for key, value in overrides.items():
        monkeypatch.setattr(settings, key, value)


def test_chat_allows_requests_under_the_limit_then_429s_over_it(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path, RATE_LIMIT_PER_MINUTE=3)

    with TestClient(app) as client:
        for _ in range(3):
            response = client.post("/chat", json={"thread_id": "t", "message": "Salam"})
            # No LLM key configured -> the *handler* fails with 503; that is
            # proof the request was let through the limiter, not blocked.
            assert response.status_code == 503

        blocked = client.post("/chat", json={"thread_id": "t", "message": "Salam"})
        assert blocked.status_code == 429
        assert blocked.json()["detail"] == RATE_LIMIT_DETAIL


def test_chat_rate_limit_allows_again_after_the_window_elapses(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path, RATE_LIMIT_PER_MINUTE=1)

    with TestClient(app) as client:
        first = client.post("/chat", json={"thread_id": "t", "message": "Salam"})
        assert first.status_code == 503

        blocked = client.post("/chat", json={"thread_id": "t", "message": "Salam"})
        assert blocked.status_code == 429

        time.sleep(0.35)  # RATE_LIMIT_WINDOW_SECONDS is shrunk to 0.3s above

        recovered = client.post("/chat", json={"thread_id": "t", "message": "Salam"})
        assert recovered.status_code == 503  # allowed through again, not 429


def test_voice_endpoint_is_rate_limited(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path, RATE_LIMIT_PER_MINUTE=1)

    with TestClient(app) as client:
        files = {"file": ("note.ogg", b"not-real-audio-bytes", "audio/ogg")}
        first = client.post("/voice", files=files, data={"thread_id": "v"})
        # No OPENAI_API_KEY -> transcription fails with a 400 VoiceError;
        # again, proof the request reached the handler, past the limiter.
        assert first.status_code == 400

        blocked = client.post("/voice", files=files, data={"thread_id": "v"})
        assert blocked.status_code == 429
        assert blocked.json()["detail"] == RATE_LIMIT_DETAIL


def test_chat_and_voice_share_one_turn_budget_per_ip(monkeypatch, tmp_path):
    """Both endpoints trigger the same costly council/TTS pipeline, so they
    are designed to draw down the same per-IP budget."""
    _configure(monkeypatch, tmp_path, RATE_LIMIT_PER_MINUTE=1)

    with TestClient(app) as client:
        chat_response = client.post("/chat", json={"thread_id": "t", "message": "Salam"})
        assert chat_response.status_code == 503  # allowed - burns the shared budget

        files = {"file": ("note.ogg", b"not-real-audio-bytes", "audio/ogg")}
        voice_response = client.post("/voice", files=files, data={"thread_id": "t"})
        assert voice_response.status_code == 429


def test_feedback_endpoint_has_its_own_independent_budget(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path, RATE_LIMIT_PER_MINUTE=1, RATE_LIMIT_FEEDBACK_PER_MINUTE=2)

    with TestClient(app) as client:
        # Burn the /chat (+/voice) budget completely - /feedback must be unaffected.
        client.post("/chat", json={"thread_id": "t", "message": "Salam"})
        assert client.post("/chat", json={"thread_id": "t", "message": "Salam"}).status_code == 429

        first = client.post("/feedback", json={"turn_id": "a", "thread_id": "t", "kind": "up"})
        assert first.status_code == 200
        second = client.post("/feedback", json={"turn_id": "b", "thread_id": "t", "kind": "up"})
        assert second.status_code == 200
        third = client.post("/feedback", json={"turn_id": "c", "thread_id": "t", "kind": "up"})
        assert third.status_code == 429
        assert third.json()["detail"] == RATE_LIMIT_DETAIL


def _all_routes():
    """Flatten `app.routes`: FastAPI represents `include_router()` results as
    a wrapper (`_IncludedRouter`) around the original `APIRouter` rather than
    inlining its routes directly, so those need one extra hop to reach the
    actual `APIRoute` objects (and their `dependant.dependencies`)."""
    for route in app.routes:
        nested = getattr(route, "original_router", None)
        if nested is not None:
            yield from nested.routes
        else:
            yield route


def _dependency_callables(path: str, method: str = "POST"):
    for route in _all_routes():
        if getattr(route, "path", None) == path and method in getattr(route, "methods", set()):
            return {dep.call for dep in route.dependant.dependencies}
    raise AssertionError(f"route not found: {method} {path}")


def test_resume_endpoints_are_not_rate_limited_by_the_turn_limiter():
    """Resuming an already-in-flight human approval isn't spamming *new*
    turns, so it must not carry the same-turn rate limit dependency."""
    assert enforce_turn_rate_limit not in _dependency_callables("/chat/resume")
    assert enforce_turn_rate_limit not in _dependency_callables("/voice/resume")


def test_health_check_is_not_rate_limited():
    assert enforce_turn_rate_limit not in _dependency_callables("/", method="GET")


def test_new_turn_and_feedback_endpoints_carry_the_expected_limiter():
    assert enforce_turn_rate_limit in _dependency_callables("/chat")
    assert enforce_turn_rate_limit in _dependency_callables("/voice")
    assert enforce_feedback_rate_limit in _dependency_callables("/feedback")
