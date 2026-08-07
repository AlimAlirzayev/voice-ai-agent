"""Text chat endpoint."""

from fastapi import APIRouter, Request

from app.graph import run_turn
from app.models.schemas import ChatRequest, ChatResponse

router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest, request: Request) -> ChatResponse:
    """One conversation turn.

    Send the same `thread_id` twice and the agent remembers the first turn -
    that is the checkpointer doing its job.
    """
    reply, history_length = await run_turn(
        request.app.state.graph,
        payload.message,
        payload.thread_id,
    )
    return ChatResponse(
        thread_id=payload.thread_id,
        reply=reply,
        history_length=history_length,
    )
