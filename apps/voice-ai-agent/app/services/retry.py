"""Shared retry-with-backoff for transient provider failures.

A single user turn can make 3-6 sequential LLM calls (supervisor routing,
up to two advisor opinions, synthesis - see `app/graph/builder.py`), plus a
Whisper transcription and a TTS call on the voice path (`app/services/
voice.py`). None of OpenAI/Groq/ElevenLabs are perfectly reliable moment to
moment: rate limits, timeouts, brief connection blips and 5xx responses all
happen and are usually gone on the next attempt. Today any one of them kills
the whole turn. This module gives every provider call site the same small,
consistent retry policy instead of re-deriving one per call site.

Deliberately narrow: only failures that *look* transient are retried (rate
limit / timeout / connection / 5xx). Clear client errors - bad API key,
malformed request, anything 4xx-that-isn't-429 - are never retried, since
retrying those only delays a clear error the user should see immediately.
`LLMError`/`VoiceError` (this app's own "not configured" errors) fall in
that second bucket too: they aren't network failures, so retrying them would
just waste time before delivering the same clear message.

Built on `tenacity`, already a transitive dependency of `langchain-core`
(and declared directly in `pyproject.toml` now that this module imports it).
"""

import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

import httpx
from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt, wait_chain, wait_fixed

log = logging.getLogger(__name__)

T = TypeVar("T")

DEFAULT_ATTEMPTS = 3
# Waited before the 2nd and 3rd attempts respectively; the last value repeats
# if `DEFAULT_ATTEMPTS` is ever raised past len(DEFAULT_BACKOFF) + 1.
DEFAULT_BACKOFF: tuple[float, ...] = (0.5, 1.5)

# Matched by exception *class name* only (see `is_transient_error`), so this
# needs no hard import of the openai/groq SDKs - voice.py and llm.py each
# only use a subset of them, and this helper is shared by both.
_TRANSIENT_EXCEPTION_NAMES = {
    "RateLimitError",
    "APITimeoutError",
    "APIConnectionError",
    "InternalServerError",
    "ServiceUnavailableError",
    "Timeout",
}


def is_transient_error(exc: BaseException) -> bool:
    """True for failures worth retrying: rate limits, timeouts, connection
    blips, 5xx. False for clear client errors (bad API key, bad request,
    anything else 4xx) and for anything unrecognised - a wrong guess there
    should surface immediately rather than silently eat a few seconds first.
    """
    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int):
        return status_code == 429 or status_code >= 500

    if isinstance(exc, (httpx.TimeoutException, httpx.TransportError)):
        return True

    return any(cls.__name__ in _TRANSIENT_EXCEPTION_NAMES for cls in type(exc).__mro__)


async def call_with_retry(
    func: Callable[[], Awaitable[T]],
    *,
    attempts: int | None = None,
    backoff: tuple[float, ...] | None = None,
    should_retry: Callable[[BaseException], bool] = is_transient_error,
    label: str = "call",
) -> T:
    """Await `func()`, retrying it a couple of times on transient failures.

    `func` must be a zero-arg async callable so every attempt issues a fresh
    call - never a re-awaited coroutine object (awaiting the same coroutine
    twice raises `RuntimeError`, which would turn a retry helper into a new
    bug). Re-raises the *original* exception, unwrapped, once attempts are
    exhausted or immediately when `should_retry` says the failure isn't
    transient - callers see the same exception type/message they always did,
    just after a couple of quick, invisible retries.

    `attempts`/`backoff` default to the module-level `DEFAULT_ATTEMPTS`/
    `DEFAULT_BACKOFF` looked up at call time (not bound at import time), so
    tests can monkeypatch those two constants to skip real sleeps.
    """
    attempts = DEFAULT_ATTEMPTS if attempts is None else attempts
    backoff = DEFAULT_BACKOFF if backoff is None else backoff

    def _before_sleep(retry_state) -> None:
        outcome = retry_state.outcome
        exc = outcome.exception() if outcome else None
        log.warning(
            "%s failed on attempt %d/%d (%s: %s), retrying",
            label,
            retry_state.attempt_number,
            attempts,
            type(exc).__name__ if exc else "?",
            exc,
        )

    retrying = AsyncRetrying(
        stop=stop_after_attempt(attempts),
        wait=wait_chain(*(wait_fixed(delay) for delay in backoff)),
        retry=retry_if_exception(should_retry),
        reraise=True,
        before_sleep=_before_sleep,
    )

    # tenacity decides whether to `await` its target by checking
    # `is_coroutine_callable(fn)` - true for an `async def`, but *false* for
    # a plain lambda that merely returns a coroutine when called (our
    # `func` is exactly that: `lambda: model.ainvoke(...)`). Passing `func`
    # straight to `retrying(...)` would make tenacity call it without
    # awaiting the result, silently handing back an unawaited coroutine
    # instead of the real value. Wrapping it in a real `async def` here
    # keeps `func`'s "zero-arg, fresh call every attempt" contract while
    # giving tenacity something it actually awaits.
    async def _call() -> T:
        return await func()

    return await retrying(_call)
