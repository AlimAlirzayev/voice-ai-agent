"""Server-Sent Events plumbing shared by `/chat/stream` and `/voice/stream`."""

import json
from typing import Any

from fastapi.responses import StreamingResponse


def event(name: str, data: Any) -> str:
    """One SSE frame. `data` is JSON on a single line."""
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def sse_response(frames) -> StreamingResponse:
    return StreamingResponse(
        frames,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
