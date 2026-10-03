"""Voice endpoint: audio in -> transcript -> agent reply -> audio out.

The council is *heard*, not just read: each advisor who actually spoke gets
their own synthesized segment in their own voice (see `app/services/voice.py`
and `Settings.elevenlabs_voice_for`), so the reply comes back as one clip per
speaker in the order they spoke, plus the Divan's own synthesis/question.
"""

import asyncio
import base64
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from app.core.rate_limit import enforce_turn_rate_limit
from app.api.sse import event, sse_response
from app.graph import TurnResult, get_pending, resume_turn, run_turn, stream_turn
from app.core.config import settings
from app.graph.builder import NoPendingApproval, closing_of
from app.graph.guardrails import is_self_harm_risk
from app.models.schemas import THREAD_ID_PATTERN, VoiceResponse, VoiceSegment
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


def _segment_specs(result: TurnResult) -> list[tuple[str, str, str]]:
    """(text, advisor key, display name) for every clip of a reply, in playing
    order: the Divanbəyi's narration (if any) opens the sequence, so a listener
    hears "here's what's happening" before the advisor(s), matching the
    text-side `narration` field; then one clip per member who spoke, each in
    their own voice."""
    opinions = result.opinions or []
    specs: list[tuple[str, str, str]] = []

    if result.narration:
        specs.append((" ".join(result.narration), "", "Divanbəyi"))

    if result.status == "pending_approval":
        approval = result.approval or {}
        if approval.get("draft"):
            specs.append(
                (approval["draft"], approval.get("advisor_key", ""), approval.get("advisor", "Divan"))
            )
        specs.append((result.reply, "", "Divan"))
        return specs

    if not opinions:
        specs.append((result.reply, "", "Divan"))
        return specs

    for opinion in opinions:
        specs.append((opinion["text"], opinion["advisor"], opinion["name"]))
    if len(opinions) > 1:
        # The composed reply already holds every member's words (spoken above,
        # each in their own voice); only the Divanbəyi's closing line is new.
        closing = closing_of(result.reply)
        if closing:
            specs.append((closing, "", "Divanbəyi"))
    return specs


class Speaker:
    """Synthesizes the clips of ONE reply concurrently (at most
    `TTS_CONCURRENCY` in flight) and returns them in the order asked. A clip
    started early - `start()` while the next advisor is still generating - is
    reused by `collect()`, never synthesized twice."""

    def __init__(self) -> None:
        self._gate = asyncio.Semaphore(max(1, settings.TTS_CONCURRENCY))
        self._tasks: dict[tuple[str, str, str], asyncio.Task[VoiceSegment]] = {}

    async def _one(self, text: str, advisor: str, name: str) -> VoiceSegment:
        async with self._gate:
            return await _speak(text, advisor=advisor, name=name)

    def start(self, spec: tuple[str, str, str]) -> asyncio.Task[VoiceSegment]:
        if spec not in self._tasks:
            self._tasks[spec] = asyncio.ensure_future(self._one(*spec))
        return self._tasks[spec]

    def finished(self) -> list[tuple[str, str, str]]:
        """Specs whose clip is ready now (no waiting)."""
        return [spec for spec, task in self._tasks.items() if task.done() and not task.exception()]

    async def collect(self, specs: list[tuple[str, str, str]]) -> list[VoiceSegment]:
        tasks = [self.start(spec) for spec in specs]
        try:
            return list(await asyncio.gather(*tasks))
        except BaseException:
            await self.cancel()
            raise

    async def cancel(self) -> None:
        pending = list(self._tasks.values())
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)


async def _speak_segments(result: TurnResult, speaker: Speaker | None = None) -> list[VoiceSegment]:
    """One segment per clip of the reply, in speaking order (see
    `_segment_specs`), synthesized in parallel."""
    return await (speaker or Speaker()).collect(_segment_specs(result))


async def _read_transcript(file: UploadFile) -> str:
    """Upload -> text, with the size/STT/length checks shared by `/voice` and
    `/voice/stream` (all raise `HTTPException` before any audio is produced)."""
    limit = settings.MAX_UPLOAD_BYTES
    audio = await file.read(limit + 1 if limit else -1)
    if limit and len(audio) > limit:
        raise HTTPException(status_code=413, detail=f"Audio larger than {limit} bytes")

    try:
        transcript = await transcribe(audio, file.filename or "audio.ogg")
    except VoiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not transcript:
        raise HTTPException(status_code=422, detail="No speech detected in the audio")
    if settings.MAX_MESSAGE_CHARS and len(transcript) > settings.MAX_MESSAGE_CHARS:
        raise HTTPException(status_code=413, detail="The recording is too long - send a shorter one")
    return transcript


@router.post(
    "/voice", response_model=VoiceResponse, dependencies=[Depends(enforce_turn_rate_limit)]
)
async def voice(
    request: Request,
    file: UploadFile = File(..., description="Voice note or audio file (ogg, m4a, mp3, wav)"),
    thread_id: str = Form("demo", pattern=THREAD_ID_PATTERN),
) -> VoiceResponse:
    """The full voice round trip in one call.

    Whisper transcribes the upload, the Divan council answers using the memory
    of this `thread_id`, and the answer comes back as one base64 OGG/Opus clip
    per council member who spoke (see `segments`) - each in their own voice.
    """
    transcript = await _read_transcript(file)

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
    thread_id: str = Form(..., pattern=THREAD_ID_PATTERN),
    decision: Literal["approve", "reject", "edit"] = Form(..., description="approve | reject | edit"),
    text: str | None = Form(
        None,
        max_length=settings.MAX_EDIT_CHARS or None,
        description="Replacement text when decision is 'edit'.",
    ),
) -> VoiceResponse:
    """Resolve a `pending_approval` voice turn - the reply comes back spoken
    in the advisor's own voice, same as `/voice`."""
    if decision == "edit" and not (text or "").strip():
        raise HTTPException(status_code=422, detail="text is required when decision is 'edit'")

    try:
        result = await resume_turn(
            request.app.state.graph,
            thread_id,
            {"decision": decision, "text": text},
        )
    except NoPendingApproval as exc:
        raise HTTPException(status_code=409, detail="Bu söhbətdə təsdiq gözləyən cavab yoxdur.") from exc
    except LLMError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    try:
        segments = await _speak_segments(result)
    except VoiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return _build_voice_response(
        thread_id=thread_id, transcript="", result=result, segments=segments
    )


@router.post("/voice/stream", dependencies=[Depends(enforce_turn_rate_limit)])
async def voice_stream(
    request: Request,
    file: UploadFile = File(..., description="Voice note or audio file (ogg, m4a, mp3, wav)"),
    thread_id: str = Form("demo", pattern=THREAD_ID_PATTERN),
):
    """`POST /voice`, delivered as Server-Sent Events.

    Upload, size and speech-to-text errors are ordinary HTTP errors (same codes
    as `/voice`) because they happen before the stream opens. Then: `transcript`
    (string), `narration`, `opinion` (text, as in `/chat/stream`), `segment`
    (a `VoiceSegment`, as soon as that member's clip is synthesized - TTS for
    one member runs while the next one is still being written), and finally
    `done` with the exact `VoiceResponse` body `POST /voice` would return.
    A client that played the `segment` events may ignore `done.segments`.
    A failure after the stream opened arrives as `error`."""
    transcript = await _read_transcript(file)
    graph = request.app.state.graph

    async def frames():
        speaker = Speaker()
        sent: set = set()
        yield event("transcript", transcript)
        try:
            result = await get_pending(graph, thread_id)
            if result is None:
                if not is_self_harm_risk(transcript) and await is_disallowed_content(transcript):
                    result = _moderation_blocked_result()
                else:
                    async for kind, value in stream_turn(
                        graph, transcript, thread_id, channel=_channel(request), modality="voice"
                    ):
                        if kind == "result":
                            result = value
                            continue
                        yield event(kind, value)
                        if kind == "opinion":
                            speaker.start((value["text"], value["advisor"], value["name"]))
                        for spec in speaker.finished():
                            if spec not in sent:
                                sent.add(spec)
                                yield event("segment", (await speaker.start(spec)).model_dump(mode="json"))
            segments = await _speak_segments(result, speaker)
            for segment in segments:
                spec = (segment.text, segment.advisor, segment.name)
                if spec in sent:
                    continue
                sent.add(spec)
                yield event("segment", segment.model_dump(mode="json"))
            yield event(
                "done",
                _build_voice_response(
                    thread_id=thread_id, transcript=transcript, result=result, segments=segments
                ).model_dump(mode="json"),
            )
        except LLMError as exc:
            await speaker.cancel()
            yield event("error", {"status": 503, "detail": str(exc)})
        except VoiceError as exc:
            await speaker.cancel()
            yield event("error", {"status": 502, "detail": str(exc)})
        except BaseException:
            await speaker.cancel()
            raise

    return sse_response(frames())
