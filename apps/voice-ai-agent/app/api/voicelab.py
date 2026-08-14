"""Voice Lab endpoints: the teach-the-voice loop (see services/voicelab.py).

`GET /voicelab/next` hands out the next practice sentence. `POST
/voicelab/sample` takes the trainer's recording of that sentence, stores it as
future cloning material, and answers with a side-by-side: what Whisper heard
in the trainer's reading vs. in the current clone's reading of the same text,
plus the clone's audio so a human can judge by ear. `POST
/voicelab/dictionary` teaches a respelling that all TTS immediately applies.
`POST /voicelab/retrain` pushes the accumulated samples back into the
ElevenLabs voice.
"""

import base64
import logging

import httpx
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.core.config import settings
from app.services import pronounce, voicelab
from app.services.voice import synthesize, transcribe

log = logging.getLogger(__name__)

router = APIRouter(tags=["voicelab"])


class PronounceEntry(BaseModel):
    word: str = Field(min_length=1, max_length=80)
    respelling: str = Field(min_length=1, max_length=120)


@router.get("/voicelab/next")
async def next_sentence() -> dict:
    return voicelab.next_sentence()


@router.post("/voicelab/sample")
async def sample(
    file: UploadFile = File(...),
    expected_text: str = Form(...),
    index: int | None = Form(default=None),
) -> dict:
    audio = await file.read()
    if not audio:
        raise HTTPException(status_code=422, detail="audio file is empty")

    extension = (file.filename or "sample.ogg").rsplit(".", 1)[-1].lower() or "ogg"
    stored = voicelab.save_sample(audio, expected_text, extension)

    trainer_transcript = await transcribe(audio, file.filename or "sample.ogg")

    clone_audio, mime, engine = await synthesize(expected_text, advisor=None)
    clone_transcript = await transcribe(clone_audio, "clone.ogg")

    if index is not None:
        voicelab.mark_done(index)

    return {
        "stored": stored.name,
        "trainer_transcript": trainer_transcript,
        "trainer_diffs": voicelab.word_diffs(expected_text, trainer_transcript),
        "clone_transcript": clone_transcript,
        "clone_diffs": voicelab.word_diffs(expected_text, clone_transcript),
        "clone_audio_base64": base64.b64encode(clone_audio).decode(),
        "clone_audio_mime": mime,
        "tts_provider": engine,
    }


@router.post("/voicelab/dictionary")
async def add_pronunciation(payload: PronounceEntry) -> dict:
    entries = pronounce.add(payload.word, payload.respelling)
    return {"stored": True, "entries": len(entries)}


@router.get("/voicelab/status")
async def status() -> dict:
    return {
        "samples": len(voicelab.sample_files()),
        "dictionary": pronounce.load(),
        "next": voicelab.next_sentence(),
        "narrator_voice_id": settings.ELEVENLABS_VOICE_ID,
    }


@router.post("/voicelab/retrain")
async def retrain() -> dict:
    """Push accumulated samples into the narrator's ElevenLabs voice (IVC edit)."""
    files = voicelab.sample_files()[-25:]  # ElevenLabs accepts up to 25 files
    if not files:
        raise HTTPException(status_code=422, detail="no samples collected yet")

    multipart = [
        ("files", (path.name, path.read_bytes(), "audio/mpeg"))
        for path in files
    ]
    async with httpx.AsyncClient(timeout=180) as client:
        response = await client.post(
            f"https://api.elevenlabs.io/v1/voices/{settings.ELEVENLABS_VOICE_ID}/edit",
            headers={"xi-api-key": settings.ELEVENLABS_API_KEY},
            data={"name": "Alim Native AZ v2"},
            files=multipart,
        )
    if response.status_code != 200:
        log.warning("voice edit failed: %s", response.text[:200])
        raise HTTPException(status_code=502, detail=f"ElevenLabs edit failed: {response.status_code}")
    return {"retrained": True, "samples_sent": len(files)}
