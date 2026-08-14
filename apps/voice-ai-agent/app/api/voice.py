"""Voice endpoint: audio in -> transcript -> agent reply -> audio out.

The council is *heard*, not just read: each advisor who actually spoke gets
their own synthesized segment in their own voice (see `app/services/voice.py`
and `Settings.elevenlabs_voice_for`), so the reply comes back as one clip per
speaker in the order they spoke, plus the Divan's own synthesis/question.
"""

import base64
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from app.core.rate_limit import enforce_turn_rate_limit
from app.graph import TurnResult, get_pending, resume_turn, run_turn
from app.graph.guardrails import is_self_harm_risk
from app.models.schemas import VoiceResponse, VoiceSegment
from app.services.llm import LLMError
from app.services.moderation import MODERATION_FALLBACK_TEXT, is_disallowed_content
from app.services.voice import VoiceError, synthesize, transcribe

router = APIRouter(tags=["voice"])


def _moderation_blocked_result() -> TurnResult:
    return TurnResult(
        status="ok",
        reply=MODERATION_FALLBACK_TEXT,
        history_length=0,
        consulted=[],
        opinions=[],
        turn_id=uuid.uuid4().hex[:12],
    )


def _channel(request: Request) -> str:
    value = request.headers.get("x-agent-channel", "api").lower()
    return value if value in {"api", "telegram", "n8n"} else "api"


def _build_voice_response(
    *, thread_id: str, transcript: str, result: TurnResult, segments: list[VoiceSegment]
) -> VoiceResponse:
    """The single place mapping a `TurnResult` to `VoiceResponse` - both
    `/voice` and `/voice/resume` go through this so `status`/`approval`
    can never silently drift out of sync between the two endpoints again."""
    last = segments[-1]
    return VoiceResponse(
        thread_id=thread_id,
        transcript=transcript,
        reply=result.reply,
        audio_base64=last.audio_base64,
        audio_mime=last.audio_mime,
        tts_provider=last.tts_provider,
        history_length=result.history_length,
        segments=segments,
        turn_id=result.turn_id,
        status=result.status,
        approval=result.approval,
        consulted=result.consulted or [],
        narration=result.narration or [],
    )


async def _speak(text: str, *, advisor: str = "", name: str = "Divan") -> VoiceSegment:
    spoken, mime, provider = await synthesize(text, advisor=advisor or None)
    return VoiceSegment(
        advisor=advisor,
        name=name,
        text=text,
        audio_base64=base64.b64encode(spoken).decode(),
        audio_mime=mime,
        tts_provider=provider,
    )


async def _speak_segments(result: TurnResult) -> list[VoiceSegment]:
    """One segment per council member who actually spoke, each in their own
    voice, in speaking order - the Divanbəyi's own narration (if any) opens
    the sequence, so a listener hears "here's what's happening" before the
    advisor(s), matching the text-side `narration` field."""
    opinions = result.opinions or []
    segments: list[VoiceSegment] = []

    if result.narration:
        segments.append(await _speak(" ".join(result.narration), name="Divanbəyi"))

    if result.status == "pending_approval":
        approval = result.approval or {}
        if approval.get("draft"):
            segments.append(
                await _speak(
                    approval["draft"],
                    advisor=approval.get("advisor_key", ""),
                    name=approval.get("advisor", "Divan"),
                )
            )
        segments.append(await _speak(result.reply))
        return segments

    if not opinions:
        segments.append(await _speak(result.reply))
        return segments

    for opinion in opinions:
        segments.append(
            await _speak(opinion["text"], advisor=opinion["advisor"], name=opinion["name"])
        )
    if len(opinions) > 1:
        # `result.reply` is the merged synthesis, distinct from any one
        # advisor's opinion - the Divan's own closing word.
        segments.append(await _speak(result.reply))
    return segments


@router.post(
    "/voice", response_model=VoiceResponse, dependencies=[Depends(enforce_turn_rate_limit)]
)
async def voice(
    request: Request,
    file: UploadFile = File(..., description="Voice note or audio file (ogg, m4a, mp3, wav)"),
    thread_id: str = Form("demo"),
) -> VoiceResponse:
    """The full voice round trip in one call.

    Whisper transcribes the upload, the Divan council answers using the memory
    of this `thread_id`, and the answer comes back as one base64 OGG/Opus clip
    per council member who spoke (see `segments`) - each in their own voice.
    """
    audio = await file.read()

    try:
        transcript = await transcribe(audio, file.filename or "audio.ogg")
    except VoiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not transcript:
        raise HTTPException(status_code=422, detail="No speech detected in the audio")

    try:
        result = await get_pending(request.app.state.graph, thread_id)
        if result is None:
            # Self-harm risk always takes the existing, tested crisis path
            # inside `run_turn` first - the secondary moderation check below
            # never runs for (and can never override) that response.
            if not is_self_harm_risk(transcript) and await is_disallowed_content(transcript):
                result = _moderation_blocked_result()
            else:
                result = await run_turn(
                    request.app.state.graph,
                    transcript,
                    thread_id,
                    channel=_channel(request),
                    modality="voice",
                )
    except LLMError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    try:
        segments = await _speak_segments(result)
    except VoiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return _build_voice_response(
        thread_id=thread_id, transcript=transcript, result=result, segments=segments
    )


@router.post("/voice/resume", response_model=VoiceResponse)
async def voice_resume(
    request: Request,
    thread_id: str = Form(...),
    decision: str = Form(..., description="approve | reject | edit"),
    text: str | None = Form(None, description="Replacement text when decision is 'edit'."),
) -> VoiceResponse:
    """Resolve a `pending_approval` voice turn - the reply comes back spoken
    in the advisor's own voice, same as `/voice`."""
    try:
        result = await resume_turn(
            request.app.state.graph,
            thread_id,
            {"decision": decision, "text": text},
        )
    except LLMError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    try:
        segments = await _speak_segments(result)
    except VoiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return _build_voice_response(
        thread_id=thread_id, transcript="", result=result, segments=segments
    )
