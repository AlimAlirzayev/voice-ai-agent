"""Unit tests for `app.services.moderation.is_disallowed_content`, plus a
couple of integration checks that the `/chat` router wires it in correctly
without disturbing the existing, tested self-harm crisis path.

The real OpenAI moderation client is never used here - `moderation._client`
is monkeypatched to a small fake so these tests make no network calls and
run everywhere, key or no key.
"""

import pytest
from fastapi.testclient import TestClient

import app.api.chat as chat_module
from app.core.config import settings
from app.main import app
from app.services import moderation


class FakeCategories:
    def __init__(self, **flags):
        self._flags = flags

    def __getattr__(self, name):
        return self._flags.get(name, False)


class _FakeResult:
    def __init__(self, categories):
        self.categories = categories


class _FakeResponse:
    def __init__(self, categories):
        self.results = [_FakeResult(categories)]


class FakeModerations:
    def __init__(self, categories=None, error=None):
        self._categories = categories if categories is not None else FakeCategories()
        self._error = error

    async def create(self, model, input):  # noqa: A002 - matches the SDK's own signature
        if self._error:
            raise self._error
        return _FakeResponse(self._categories)


class FakeClient:
    def __init__(self, categories=None, error=None):
        self.moderations = FakeModerations(categories, error)


@pytest.fixture(autouse=True)
def _moderation_enabled(monkeypatch):
    monkeypatch.setattr(settings, "MODERATION_ENABLED", True)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "test-key")


@pytest.mark.asyncio
async def test_disabled_by_settings_never_calls_the_client(monkeypatch):
    monkeypatch.setattr(settings, "MODERATION_ENABLED", False)
    monkeypatch.setattr(
        moderation, "_client", lambda: FakeClient(FakeCategories(hate_threatening=True))
    )
    assert await moderation.is_disallowed_content("anything") is False


@pytest.mark.asyncio
async def test_returns_false_without_an_api_key(monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "")
    assert await moderation.is_disallowed_content("anything") is False


@pytest.mark.asyncio
async def test_returns_false_for_empty_or_blank_text():
    assert await moderation.is_disallowed_content("") is False
    assert await moderation.is_disallowed_content("   ") is False
    assert await moderation.is_disallowed_content(None) is False


@pytest.mark.asyncio
async def test_flags_a_blocking_category(monkeypatch):
    monkeypatch.setattr(moderation, "_client", lambda: FakeClient(FakeCategories(illicit=True)))
    assert await moderation.is_disallowed_content("some illegal request") is True


@pytest.mark.asyncio
async def test_does_not_flag_low_severity_categories(monkeypatch):
    """Plain (non-threatening, non-graphic) hate/harassment/violence/sexual
    are deliberately excluded - a legendary folk-hero advisor like Koroğlu
    can plausibly be asked about blunt or violent topics without it being a
    real safety issue; only the categories a public product must never
    engage with under any persona are blocking (see module docstring)."""
    monkeypatch.setattr(
        moderation,
        "_client",
        lambda: FakeClient(FakeCategories(hate=True, violence=True, sexual=True, harassment=True)),
    )
    assert await moderation.is_disallowed_content("something blunt") is False


def test_self_harm_categories_are_not_part_of_the_moderation_gate():
    """Self-harm stays exclusively the deterministic keyword check's job;
    the moderation gate must never compete with (or shadow) that response."""
    assert "self_harm" not in moderation._BLOCKING_CATEGORIES
    assert "self_harm_intent" not in moderation._BLOCKING_CATEGORIES
    assert "self_harm_instructions" not in moderation._BLOCKING_CATEGORIES


@pytest.mark.asyncio
async def test_fails_open_when_the_api_call_raises(monkeypatch):
    monkeypatch.setattr(
        moderation, "_client", lambda: FakeClient(error=RuntimeError("network blip"))
    )
    assert await moderation.is_disallowed_content("some message") is False


@pytest.mark.asyncio
async def test_does_not_flag_an_ordinary_koroglu_roleplay_request(monkeypatch):
    """The product's intentional design - roleplaying legendary historical
    figures - must never be treated as disallowed content."""
    monkeypatch.setattr(moderation, "_client", lambda: FakeClient(FakeCategories()))
    assert (
        await moderation.is_disallowed_content("Koroğlu, mənə cəsarətli məsləhət ver.") is False
    )


def _configure_chat(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "SQLITE_PATH", str(tmp_path / "checkpoints.sqlite"))
    monkeypatch.setattr(settings, "FEEDBACK_PATH", str(tmp_path / "feedback.sqlite"))


def test_chat_endpoint_returns_fallback_text_when_moderation_flags_the_message(
    monkeypatch, tmp_path
):
    _configure_chat(monkeypatch, tmp_path)

    async def _always_flagged(text):
        return True

    monkeypatch.setattr(chat_module, "is_disallowed_content", _always_flagged)

    with TestClient(app) as client:
        response = client.post("/chat", json={"thread_id": "mod-1", "message": "anything"})

    assert response.status_code == 200
    body = response.json()
    assert body["reply"] == chat_module.MODERATION_FALLBACK_TEXT
    assert body["consulted"] == []


def test_chat_endpoint_never_calls_moderation_for_a_self_harm_message(monkeypatch, tmp_path):
    """Ordering guarantee: the existing, tested crisis path must win outright
    - the moderation check must not even run for a self-harm message, let
    alone override its response."""
    _configure_chat(monkeypatch, tmp_path)

    async def _explode(text):
        raise AssertionError("moderation must not be called for a self-harm message")

    monkeypatch.setattr(chat_module, "is_disallowed_content", _explode)

    with TestClient(app) as client:
        response = client.post(
            "/chat",
            json={
                "thread_id": "mod-2",
                "message": "Artıq yaşamaq istəmirəm, intihar etmək istəyirəm.",
            },
        )

    assert response.status_code == 200
    assert "kömək" in response.json()["reply"].lower()
