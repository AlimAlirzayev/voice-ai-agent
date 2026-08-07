"""Voice endpoint: audio in -> transcript -> agent reply -> audio out."""

import base64

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from app.graph import run_turn
from app.models.schemas import VoiceResponse
from app.services.voice import VoiceError, synthesize, transcribe

router = APIRouter(tags=["voice"])


@router.post("/voice", response_model=VoiceResponse)
async def voice(
    request: Request,
    file: UploadFile = File(..., description="Voice note or audio file (ogg, m4a, mp3, wav)"),
    thread_id: str = Form("demo"),
) -> VoiceResponse:
    """The full voice round trip in one call.

    Whisper transcribes the upload, the LangGraph agent answers using the memory
    of this `thread_id`, and the answer comes back as base64 OGG/Opus audio.
    """
    audio = await file.read()

    try:
        transcript = await transcribe(audio, file.filename or "audio.ogg")
    except VoiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not transcript:
        raise HTTPException(status_code=422, detail="No speech detected in the audio")

    reply, history_length = await run_turn(request.app.state.graph, transcript, thread_id)

    try:
        spoken, mime, provider = await synthesize(reply)
    except VoiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return VoiceResponse(
        thread_id=thread_id,
        transcript=transcript,
        reply=reply,
        audio_base64=base64.b64encode(spoken).decode(),
        audio_mime=mime,
        tts_provider=provider,
        history_length=history_length,
    )
