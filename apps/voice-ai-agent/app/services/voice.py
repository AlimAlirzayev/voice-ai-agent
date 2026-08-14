"""Voice flow: Whisper speech-to-text, ElevenLabs text-to-speech (Lesson 26).

Both engines are hosted, so nothing has to be compiled locally - no torch, no
ffmpeg, no model download before a presentation.

Both TTS paths return OGG/Opus, which is exactly what Telegram wants for a voice
note, so the caller never has to care which engine spoke.
"""

import logging
from functools import lru_cache

from elevenlabs.client import AsyncElevenLabs
from openai import AsyncOpenAI

from app.core.config import settings
from app.services.retry import call_with_retry

log = logging.getLogger(__name__)

OGG = "audio/ogg"


class VoiceError(RuntimeError):
    """Raised when a voice engine cannot be used at all."""


@lru_cache(maxsize=1)
def _openai() -> AsyncOpenAI:
    if not settings.OPENAI_API_KEY:
        raise VoiceError("OPENAI_API_KEY is not set - add it to .env")
    return AsyncOpenAI(api_key=settings.OPENAI_API_KEY)


@lru_cache(maxsize=1)
def _elevenlabs() -> AsyncElevenLabs:
    return AsyncElevenLabs(api_key=settings.ELEVENLABS_API_KEY)


async def transcribe(audio: bytes, filename: str = "audio.ogg") -> str:
    """Speech to text with Whisper."""
    if not audio:
        raise VoiceError("The uploaded audio file is empty")

    response = await call_with_retry(
        lambda: _openai().audio.transcriptions.create(
            model=settings.OPENAI_STT_MODEL,
            file=(filename, audio),
        ),
        label="whisper-transcribe",
    )
    return (response.text or "").strip()


async def synthesize(text: str, advisor: str | None = None) -> tuple[bytes, str, str]:
    """Text to speech. Returns (audio bytes, mime type, engine that spoke).

    `advisor` picks which Divan council member's voice speaks (nesreddin /
    koroglu / simurg); omit it for the default narrator voice. ElevenLabs is
    preferred; if its key is missing or the call fails, OpenAI TTS takes over
    with its own per-advisor voice so a live session never ends in silence.
    """
    if settings.ELEVENLABS_API_KEY:
        try:
            return await _elevenlabs_tts(text, advisor), OGG, "elevenlabs"
        except Exception as exc:  # noqa: BLE001 - stage safety net
            log.warning("ElevenLabs TTS failed, falling back to OpenAI: %s", exc)

    return await _openai_tts(text, advisor), OGG, "openai"


async def _elevenlabs_tts(text: str, advisor: str | None) -> bytes:
    async def _once() -> bytes:
        stream = _elevenlabs().text_to_speech.convert(
            voice_id=settings.elevenlabs_voice_for(advisor),
            text=text,
            model_id=settings.ELEVENLABS_MODEL,
            output_format="opus_48000_64",
        )
        chunks = [chunk async for chunk in stream]
        audio = b"".join(chunks)
        if not audio:
            raise VoiceError("ElevenLabs returned no audio")
        return audio

    # A fresh stream is opened on every attempt - a half-consumed stream from
    # a failed attempt is never reused. A couple of quick retries here before
    # giving up on ElevenLabs entirely, since the caller (`synthesize`) then
    # falls through to OpenAI TTS - worth trying to avoid that switch first.
    return await call_with_retry(_once, label="elevenlabs-tts")


async def _openai_tts(text: str, advisor: str | None) -> bytes:
    async def _once() -> bytes:
        response = await _openai().audio.speech.create(
            model=settings.OPENAI_TTS_MODEL,
            voice=settings.openai_voice_for(advisor),
            input=text,
            response_format="opus",
        )
        return response.content

    return await call_with_retry(_once, label="openai-tts")
