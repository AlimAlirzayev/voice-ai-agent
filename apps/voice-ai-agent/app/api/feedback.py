"""Feedback endpoint (Lesson 11.2): thumbs up/down and corrections.

React to any completed `/chat` or `/voice` reply by its `turn_id`. A
correction (`kind="correction"`) is the strongest signal - the user supplies
what the reply *should* have said - and is stored verbatim so it can later be
paired with the original reply into a `{prompt, chosen, rejected}` example.
"""

from fastapi import APIRouter, Depends, HTTPException, Request

from app.core.rate_limit import enforce_feedback_rate_limit
from app.models.schemas import FeedbackRequest, FeedbackResponse

router = APIRouter(tags=["feedback"])


def _channel(request: Request) -> str:
    value = request.headers.get("x-agent-channel", "api").lower()
    return value if value in {"api", "telegram", "n8n"} else "api"


@router.post(
    "/feedback", response_model=FeedbackResponse, dependencies=[Depends(enforce_feedback_rate_limit)]
)
async def feedback(payload: FeedbackRequest, request: Request) -> FeedbackResponse:
    if payload.kind == "correction" and not (payload.text or "").strip():
        raise HTTPException(status_code=422, detail="text is required when kind='correction'")

    row_id = await request.app.state.feedback.add(
        turn_id=payload.turn_id,
        thread_id=payload.thread_id,
        kind=payload.kind,
        advisor=payload.advisor,
        text=payload.text,
        channel=_channel(request),
    )
    return FeedbackResponse(id=row_id, stored=True)


@router.get("/feedback/stats", tags=["feedback"])
async def feedback_stats(request: Request) -> dict:
    return await request.app.state.feedback.stats()
