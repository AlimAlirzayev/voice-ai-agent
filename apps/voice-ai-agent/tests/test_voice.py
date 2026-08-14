"""Tests for the retry behaviour added around the voice engines in
`app/services/voice.py`: Whisper transcription and both TTS provider paths
(ElevenLabs, OpenAI). Real provider clients are swapped for small fakes so
these run instantly and without any network access or API key.
"""

from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.services import retry as retry_module
from app.services import voice as voice_module
from app.services.voice import _elevenlabs_tts, _openai_tts, synthesize, transcribe


class RateLimitError(Exception):
    """Stand-in for a transient provider error - classified by name only,
    see `app.services.retry.is_transient_error`."""


@pytest.fixture(autouse=True)
def fast_backoff(monkeypatch):
    """No test here should actually sleep for the real 0.5s/1.5s backoff."""
    monkeypatch.setattr(retry_module, "DEFAULT_BACKOFF", (0.0, 0.0))


class FakeTranscriptions:
    def __init__(self, fail_times: int, text: str = "Salam"):
        self.fail_times = fail_times
        self.text = text
        self.calls = 0

    async def create(self, **kwargs):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RateLimitError("transient transcription failure")
        return SimpleNamespace(text=self.text)


class FakeSpeech:
    def __init__(self, fail_times: int, content: bytes = b"audio-bytes"):
        self.fail_times = fail_times
        self.content = content
        self.calls = 0

    async def create(self, **kwargs):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RateLimitError("transient speech failure")
        return SimpleNamespace(content=self.content)


class FakeOpenAIClient:
    def __init__(self, transcriptions: FakeTranscriptions | None = None, speech: FakeSpeech | None = None):
        self.audio = SimpleNamespace(transcriptions=transcriptions, speech=speech)


class FakeTextToSpeech:
    """Mirrors `AsyncElevenLabs().text_to_speech`: `.convert()` is a plain
    (non-async) call that returns an async-iterable stream of chunks."""

    def __init__(self, fail_times: int, chunks: tuple[bytes, ...] = (b"el-audio",)):
        self.fail_times = fail_times
        self.chunks = chunks
        self.calls = 0

    def convert(self, **kwargs):
        self.calls += 1
        call_index = self.calls

        async def _stream():
            if call_index <= self.fail_times:
                raise RateLimitError("transient tts failure")
            for chunk in self.chunks:
                yield chunk

        return _stream()


class FakeElevenLabsClient:
    def __init__(self, text_to_speech: FakeTextToSpeech):
        self.text_to_speech = text_to_speech


# --- transcribe() ------------------------------------------------------


@pytest.mark.asyncio
async def test_transcribe_recovers_after_transient_failures(monkeypatch):
    transcriptions = FakeTranscriptions(fail_times=2, text="Salam, necəsən?")
    monkeypatch.setattr(voice_module, "_openai", lambda: FakeOpenAIClient(transcriptions=transcriptions))

    text = await transcribe(b"some-audio-bytes")

    assert text == "Salam, necəsən?"
    assert transcriptions.calls == 3


@pytest.mark.asyncio
async def test_transcribe_raises_original_error_once_retries_exhausted(monkeypatch):
    transcriptions = FakeTranscriptions(fail_times=99)
    monkeypatch.setattr(voice_module, "_openai", lambda: FakeOpenAIClient(transcriptions=transcriptions))

    with pytest.raises(RateLimitError, match="transient transcription failure"):
        await transcribe(b"some-audio-bytes")

    assert transcriptions.calls == retry_module.DEFAULT_ATTEMPTS


# --- _elevenlabs_tts() ---------------------------------------------------


@pytest.mark.asyncio
async def test_elevenlabs_tts_recovers_after_transient_failures(monkeypatch):
    tts = FakeTextToSpeech(fail_times=2, chunks=(b"a", b"b", b"c"))
    monkeypatch.setattr(voice_module, "_elevenlabs", lambda: FakeElevenLabsClient(tts))

    audio = await _elevenlabs_tts("hello", advisor=None)

    assert audio == b"abc"
    assert tts.calls == 3


@pytest.mark.asyncio
async def test_elevenlabs_tts_raises_original_error_once_retries_exhausted(monkeypatch):
    tts = FakeTextToSpeech(fail_times=99)
    monkeypatch.setattr(voice_module, "_elevenlabs", lambda: FakeElevenLabsClient(tts))

    with pytest.raises(RateLimitError, match="transient tts failure"):
        await _elevenlabs_tts("hello", advisor=None)

    assert tts.calls == retry_module.DEFAULT_ATTEMPTS


# --- _openai_tts() --------------------------------------------------------


@pytest.mark.asyncio
async def test_openai_tts_recovers_after_transient_failures(monkeypatch):
    speech = FakeSpeech(fail_times=2, content=b"openai-audio")
    monkeypatch.setattr(voice_module, "_openai", lambda: FakeOpenAIClient(speech=speech))

    audio = await _openai_tts("hello", advisor=None)

    assert audio == b"openai-audio"
    assert speech.calls == 3


@pytest.mark.asyncio
async def test_openai_tts_raises_original_error_once_retries_exhausted(monkeypatch):
    speech = FakeSpeech(fail_times=99)
    monkeypatch.setattr(voice_module, "_openai", lambda: FakeOpenAIClient(speech=speech))

    with pytest.raises(RateLimitError, match="transient speech failure"):
        await _openai_tts("hello", advisor=None)

    assert speech.calls == retry_module.DEFAULT_ATTEMPTS


# --- synthesize() fallback still works alongside the new retries --------


@pytest.mark.asyncio
async def test_synthesize_still_falls_back_to_openai_once_elevenlabs_is_exhausted(monkeypatch):
    """The existing ElevenLabs -> OpenAI fallback-on-any-exception behaviour
    must survive the new retry logic unchanged: ElevenLabs gets its retries,
    and only once *those* are exhausted does OpenAI TTS take over."""
    monkeypatch.setattr(settings, "ELEVENLABS_API_KEY", "fake-elevenlabs-key")
    tts = FakeTextToSpeech(fail_times=99)
    speech = FakeSpeech(fail_times=0, content=b"openai-fallback-audio")
    monkeypatch.setattr(voice_module, "_elevenlabs", lambda: FakeElevenLabsClient(tts))
    monkeypatch.setattr(voice_module, "_openai", lambda: FakeOpenAIClient(speech=speech))

    audio, mime, provider = await synthesize("hello")

    assert provider == "openai"
    assert audio == b"openai-fallback-audio"
    assert mime == voice_module.OGG
    assert tts.calls == retry_module.DEFAULT_ATTEMPTS
    assert speech.calls == 1
