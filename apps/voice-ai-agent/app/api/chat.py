"""Text chat endpoint."""

import uuid

from fastapi import APIRouter, Depends, Request
from fastapi import HTTPException

from app.core.rate_limit import enforce_turn_rate_limit
from app.graph import TurnResult, get_pending, resume_turn, run_turn
from app.graph.guardrails import is_self_harm_risk
from app.models.schemas import ChatRequest, ChatResponse, ResumeRequest
from app.services.llm import LLMError
from app.services.moderation import MODERATION_FALLBACK_TEXT, is_disallowed_content

router = APIRouter(tags=["chat"])


def _channel(request: Request) -> str:
    value = request.headers.get("x-agent-channel", "api").lower()
    return value if value in {"api", "telegram", "n8n"} else "api"


def _moderation_blocked_result() -> TurnResult:
    return TurnResult(
        status="ok",
        reply=MODERATION_FALLBACK_TEXT,
        history_length=0,
        consulted=[],
        opinions=[],
        turn_id=uuid.uuid4().hex[:12],
    )


@router.post("/chat", response_model=ChatResponse, dependencies=[Depends(enforce_turn_rate_limit)])
async def chat(payload: ChatRequest, request: Request) -> ChatResponse:
    """One conversation turn.

    Send the same `thread_id` twice and the agent remembers the first turn -
    that is the checkpointer doing its job. If the council's answer needs a
    human sign-off, this returns `status: "pending_approval"` instead of a
    finished reply - resolve it with `POST /chat/resume`.
    """
    try:
        result = await get_pending(request.app.state.graph, payload.thread_id)
        if result is None:
            # Self-harm risk always takes the existing, tested crisis path
            # inside `run_turn` first - the secondary moderation check below
            # never runs for (and can never override) that response.
            if not is_self_harm_risk(payload.message) and await is_disallowed_content(
                payload.message
            ):
                result = _moderation_blocked_result()
            else:
                result = await run_turn(
                    request.app.state.graph,
                    payload.message,
                    payload.thread_id,
                    channel=_channel(request),
                )
    except LLMError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return ChatResponse(
        thread_id=payload.thread_id,
        reply=result.reply,
        history_length=result.history_length,
        status=result.status,
        approval=result.approval,
        consulted=result.consulted or [],
        turn_id=result.turn_id,
        narration=result.narration or [],
    )


@router.post("/chat/resume", response_model=ChatResponse)
async def chat_resume(payload: ResumeRequest, request: Request) -> ChatResponse:
    """Resolve a `pending_approval` turn with a human decision."""
    decision = {"decision": payload.decision, "text": payload.text}

    try:
        result = await resume_turn(request.app.state.graph, payload.thread_id, decision)
    except LLMError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return ChatResponse(
        thread_id=payload.thread_id,
        reply=result.reply,
        history_length=result.history_length,
        status=result.status,
        approval=result.approval,
        consulted=result.consulted or [],
        turn_id=result.turn_id,
        narration=result.narration or [],
    )
