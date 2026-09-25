"""The cloned voice speaks when its reference exists and falls back when it does not."""
import asyncio

from app.core.config import settings
from app.services import clone_voice, voice


def test_provider_clone_selected(monkeypatch):
    monkeypatch.setattr(settings, "TTS_PROVIDER", "clone")
    assert settings.tts_provider == "clone"


def test_falls_back_to_edge_without_reference(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "TTS_PROVIDER", "clone")
    monkeypatch.setattr(settings, "CLONE_REF_PATH", str(tmp_path / "missing.wav"))

    async def fake_edge(text, advisor, owner=False):
        if owner:
            raise clone_voice.CloneUnavailable("converter down")
        return b"edge-audio"

    monkeypatch.setattr(voice, "_edge_tts", fake_edge)
    audio, mime, engine = asyncio.run(voice.synthesize("Salam", "koroglu"))
    assert (audio, engine) == (b"edge-audio", "edge")


def test_converter_rung_when_omnivoice_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "VC_ENABLED", True)
    monkeypatch.setattr(settings, "TTS_PROVIDER", "clone")
    monkeypatch.setattr(settings, "CLONE_REF_PATH", str(tmp_path / "missing.wav"))

    async def fake_edge(text, advisor, owner=False):
        return b"owner-timbre" if owner else b"edge-audio"

    monkeypatch.setattr(voice, "_edge_tts", fake_edge)
    audio, mime, engine = asyncio.run(voice.synthesize("Salam", None))
    assert (audio, engine) == (b"owner-timbre", "owner-vc")


def test_clone_speaks_when_available(monkeypatch):
    monkeypatch.setattr(settings, "TTS_PROVIDER", "clone")

    async def fake_speak(text, advisor):
        return b"owner-voice"

    monkeypatch.setattr(clone_voice, "speak", fake_speak)
    audio, mime, engine = asyncio.run(voice.synthesize("Salam", "nizami"))
    assert (audio, engine) == (b"owner-voice", "clone")


def test_members_differ():
    styles = {clone_voice.style_for(a) for a in
              ["nesreddin", "koroglu", "simurg", "nesimi", "dedeqorqud", "nizami"]}
    assert len(styles) == 6


def test_quota_error_rests_the_space(monkeypatch):
    monkeypatch.setattr(clone_voice, "_resting_until", 0.0)
    monkeypatch.setattr(clone_voice, "available", lambda: True)

    def boom(text, speed):
        raise RuntimeError("You have exceeded your free ZeroGPU quota")

    monkeypatch.setattr(clone_voice, "_predict", boom)
    import pytest
    with pytest.raises(clone_voice.CloneUnavailable):
        asyncio.run(clone_voice.speak("Salam", None))
    calls = []
    monkeypatch.setattr(clone_voice, "_predict", lambda t, s: calls.append(1))
    with pytest.raises(clone_voice.CloneUnavailable, match="resting"):
        asyncio.run(clone_voice.speak("Salam", None))
    assert calls == []


def test_owner_model_is_first_when_present(monkeypatch):
    from app.services import owner_model
    monkeypatch.setattr(settings, "TTS_PROVIDER", "clone")

    async def fake(text, advisor):
        return b"his-own-model"

    monkeypatch.setattr(owner_model, "speak", fake)
    audio, mime, engine = asyncio.run(voice.synthesize("Salam", "nizami"))
    assert (audio, engine) == (b"his-own-model", "owner-model")


def test_model_path_resolves_under_app(monkeypatch):
    from app.services import owner_model
    assert str(owner_model.model_file()).endswith("voice-ai-agent/data/voices/owner.onnx")


def test_converter_off_by_default_falls_to_clear_voice(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "TTS_PROVIDER", "clone")
    monkeypatch.setattr(settings, "CLONE_REF_PATH", str(tmp_path / "missing.wav"))

    async def fake_edge(text, advisor, owner=False):
        assert not owner, "converter must not run while disabled"
        return b"edge-audio"

    monkeypatch.setattr(voice, "_edge_tts", fake_edge)
    assert asyncio.run(voice.synthesize("Salam", None))[2] == "edge"
