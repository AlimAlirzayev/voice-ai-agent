"""Per-client rate limiting for the abuse-prone endpoints (not a course
lesson - baseline for any publicly-reachable AI product).

Before this module existed, nothing stood between the public internet and
`/chat`/`/voice`/`/feedback`: anyone who could reach the deployed URL could
call `/chat` unlimited times (each turn can trigger 3-6 LLM calls plus TTS -
a real cost, not just a nuisance) or spam `/feedback` with junk.

Deliberately simple and dependency-free: this app is a single container with
no horizontal scaling (see `docker-compose.yml` at the repo root), so an
in-memory sliding-window counter is a pragmatic, appropriately-sized fit.
Reaching for Redis or another shared store here would be solving a scaling
problem this deployment doesn't have yet. If this app is ever run as more
than one replica, this needs to move to a shared store instead - an
in-memory limiter only sees the requests that land on its own process.

Keyed by client IP (`request.client.host`) - a pragmatic default, not a
perfect one. Behind a reverse proxy without trustworthy `X-Forwarded-For`
handling, many real clients can appear to share one IP (under-blocking them
as a group) and a malicious client can potentially spoof headers if such
handling is later added carelessly. There is no such proxy in this repo
today, so this is not engineered further than that; revisit once one exists.
"""

import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

from app.core.config import settings

RATE_LIMIT_DETAIL = "Çox tez-tez sorğu göndərirsiniz, bir az gözləyin."


class SlidingWindowRateLimiter:
    """Fixed-capacity sliding-window counter, one deque of hit timestamps per
    key. `limit`/`window_seconds` are passed in on every call (not baked in
    at construction) so operators - and tests - can change them via
    `Settings` without rebuilding the limiter."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str, limit: int, window_seconds: float) -> bool:
        """True if `key` is still under `limit` hits within the trailing
        `window_seconds`, and records this call as a hit. `limit <= 0`
        disables the limiter entirely (treated as "unlimited")."""
        if limit <= 0:
            return True

        now = time.monotonic()
        hits = self._hits[key]
        cutoff = now - window_seconds
        while hits and hits[0] < cutoff:
            hits.popleft()

        if len(hits) >= limit:
            return False

        hits.append(now)
        return True

    def reset(self) -> None:
        """Test hook: forget every recorded hit."""
        self._hits.clear()


# One shared bucket for both "new turn" endpoints (`/chat`, `/voice`) - they
# both trigger the same costly council + TTS pipeline, so it makes sense for
# one IP hammering either (or both) to draw down the same budget. `/feedback`
# is cheap to serve but still worth capping against spam, so it gets its own,
# independent, more generous bucket.
_turn_limiter = SlidingWindowRateLimiter()
_feedback_limiter = SlidingWindowRateLimiter()


def _client_key(request: Request) -> str:
    client = request.client
    return client.host if client else "unknown"


def enforce_turn_rate_limit(request: Request) -> None:
    """FastAPI dependency for `/chat` and `/voice` (new-turn endpoints only -
    NOT `/chat/resume` or `/voice/resume`: resuming an already-in-flight
    human approval isn't spamming new turns and shouldn't be blocked by a
    limit meant to control that)."""
    key = _client_key(request)
    if not _turn_limiter.allow(key, settings.RATE_LIMIT_PER_MINUTE, settings.RATE_LIMIT_WINDOW_SECONDS):
        raise HTTPException(status_code=429, detail=RATE_LIMIT_DETAIL)


def enforce_feedback_rate_limit(request: Request) -> None:
    """FastAPI dependency for `POST /feedback`."""
    key = _client_key(request)
    if not _feedback_limiter.allow(
        key, settings.RATE_LIMIT_FEEDBACK_PER_MINUTE, settings.RATE_LIMIT_WINDOW_SECONDS
    ):
        raise HTTPException(status_code=429, detail=RATE_LIMIT_DETAIL)


def reset_rate_limits() -> None:
    """Test hook: clear both buckets so tests don't leak state into each
    other (every `TestClient` request shares the same fake client host)."""
    _turn_limiter.reset()
    _feedback_limiter.reset()
