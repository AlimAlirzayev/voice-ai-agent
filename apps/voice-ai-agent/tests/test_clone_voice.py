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

    async def fake_edge(text, advisor):
        return b"edge-audio"

    monkeypatch.setattr(voice, "_edge_tts", fake_edge)
    audio, mime, engine = asyncio.run(voice.synthesize("Salam", "koroglu"))
    assert (audio, engine) == (b"edge-audio", "edge")


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
