"""Voice flow: Whisper speech-to-text, ElevenLabs text-to-speech (Lesson 26).

Both engines are hosted, so nothing has to be compiled locally - no torch, no
ffmpeg, no model download before a presentation.

Both TTS paths return OGG/Opus, which is exactly what Telegram wants for a voice
note, so the caller never has to care which engine spoke.
"""

import asyncio
import logging
from functools import lru_cache

from elevenlabs.client import AsyncElevenLabs
from openai import AsyncOpenAI

from app.core.config import settings
from app.services import pronounce
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
def _stt_client() -> AsyncOpenAI:
    """Whisper through any OpenAI-compatible endpoint (Groq's free tier, or OpenAI)."""
    if settings.STT_BASE_URL and settings.STT_API_KEY:
        return AsyncOpenAI(api_key=settings.STT_API_KEY, base_url=settings.STT_BASE_URL)
    return _openai()


@lru_cache(maxsize=1)
def _elevenlabs() -> AsyncElevenLabs:
    return AsyncElevenLabs(api_key=settings.ELEVENLABS_API_KEY)


async def transcribe(audio: bytes, filename: str = "audio.ogg") -> str:
    """Speech to text with Whisper.

    `language="az"` matters more than it looks: without it, Whisper
    autodetects and - measured 2026-08-15 via scripts/scan_pronunciation.py -
    drifts to Turkish (phonetically the closest language) on a large fraction
    of otherwise-correct Azerbaijani audio: "qovuşmaz" heard as "kovuşmaz",
    "hər" as "her", "cahan" as "cehennem" (Turkish for "hell"), one utterance
    came back transliterated into Persian script entirely. That was our own
    measurement instrument lying about the TTS, not a TTS problem - a "fix"
    based on those transcripts would have forced the voice to say the WRONG
    thing to satisfy a mis-set STT. Pinning the language stops the drift.
    """
    if not audio:
        raise VoiceError("The uploaded audio file is empty")

    response = await call_with_retry(
        lambda: _stt_client().audio.transcriptions.create(
            model=settings.stt_model,
            file=(filename, audio),
            language="az",
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
    text = pronounce.apply(text)
    provider = settings.tts_provider
    if provider == "clone":
        from app.services import clone_voice, owner_model

        try:
            return await owner_model.speak(text, advisor), OGG, "owner-model"
        except clone_voice.CloneUnavailable as exc:
            if owner_model.available():
                log.warning("owner model failed, trying the clone: %s", exc)
        try:
            return await clone_voice.speak(text, advisor), OGG, "clone"
        except clone_voice.CloneUnavailable as exc:
            log.warning("OmniVoice clone unavailable, converting the Microsoft voice: %s", exc)
        try:
            if not settings.VC_ENABLED:
                raise clone_voice.CloneUnavailable("timbre converter disabled (benchmark WER 0.42)")
            return await _edge_tts(text, advisor, owner=True), OGG, "owner-vc"
        except clone_voice.CloneUnavailable as exc:
            log.warning("owner timbre converter unavailable, Microsoft voice speaks: %s", exc)
            provider = "edge"

    if provider == "elevenlabs":
        try:
            return await _elevenlabs_tts(text, advisor), OGG, "elevenlabs"
        except Exception as exc:  # noqa: BLE001 - stage safety net
            log.warning("ElevenLabs TTS failed, falling back: %s", exc)
            provider = "openai" if settings.OPENAI_API_KEY else "edge"

    if provider == "edge":
        return await _edge_tts(text, advisor), OGG, "edge"

    return await _openai_tts(text, advisor), OGG, "openai"


async def _edge_tts(text: str, advisor: str | None, owner: bool = False) -> bytes:
    """Free Microsoft neural Azerbaijani voices (edge-tts), re-encoded to OGG/Opus.

    edge-tts only emits MP3; ffmpeg turns it into the same OGG/Opus the other
    engines return, so Telegram voice notes and the web player see one format.
    """
    import edge_tts

    voice, rate, pitch = settings.edge_voice_for(advisor)

    async def _once() -> bytes:
        communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
        mp3 = b"".join(
            [chunk["data"] async for chunk in communicate.stream() if chunk["type"] == "audio"]
        )
        if not mp3:
            raise VoiceError("edge-tts returned no audio")
        return mp3

    mp3 = await call_with_retry(_once, label="edge-tts")
    if owner:
        from app.services import clone_voice

        return await clone_voice.to_owner(mp3)
    return await _mp3_to_ogg(mp3)


async def _mp3_to_ogg(mp3: bytes) -> bytes:
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-loglevel", "error", "-i", "pipe:0", "-c:a", "libopus", "-b:a", "48k",
        "-f", "ogg", "pipe:1",
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate(mp3)
    if proc.returncode != 0 or not out:
        raise VoiceError(f"ffmpeg mp3→ogg failed: {err.decode('utf-8', 'replace')[:200]}")
    return out


async def _elevenlabs_tts(text: str, advisor: str | None) -> bytes:
    async def _once() -> bytes:
        stream = _elevenlabs().text_to_speech.convert(
            voice_id=settings.elevenlabs_voice_for(advisor),
            text=text,
            model_id=settings.ELEVENLABS_MODEL,
            output_format="opus_48000_64",
            voice_settings={"stability": settings.ELEVENLABS_STABILITY},
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
