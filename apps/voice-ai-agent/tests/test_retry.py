"""Unit tests for `app.services.retry.call_with_retry`.

Fast on purpose: every test passes an explicit tiny `backoff` so nothing here
actually sleeps for the real 0.5s/1.5s used in production.
"""

import httpx
import pytest

from app.services.retry import call_with_retry, is_transient_error

FAST_BACKOFF = (0.0, 0.0)


class RateLimitError(Exception):
    """Stand-in for `openai.RateLimitError` / `groq.RateLimitError` - only the
    class *name* is used for classification, so a lookalike is enough."""


class AuthenticationError(Exception):
    """Stand-in for a clear client error (bad API key) - must never retry."""

    def __init__(self, message: str, status_code: int = 401):
        super().__init__(message)
        self.status_code = status_code


class FlakyCall:
    """Fails with `error` for the first `fail_times` calls, then returns `result`."""

    def __init__(self, error: Exception, fail_times: int, result: str = "ok"):
        self.error = error
        self.fail_times = fail_times
        self.result = result
        self.calls = 0

    async def __call__(self) -> str:
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.error
        return self.result


@pytest.mark.asyncio
async def test_recovers_after_transient_failures_then_succeeds():
    """Two transient failures followed by a success should still return the
    successful result - proving the retry logic actually recovers a call
    that would otherwise have killed the whole turn."""
    flaky = FlakyCall(RateLimitError("rate limited"), fail_times=2, result="answer")

    result = await call_with_retry(flaky, attempts=3, backoff=FAST_BACKOFF, label="test")

    assert result == "answer"
    assert flaky.calls == 3


@pytest.mark.asyncio
async def test_raises_original_error_after_exhausting_retries():
    """A failure on every attempt must surface as the *original* exception
    (same type, same message) once retries are exhausted - not a RetryError
    or anything else that would mask what actually went wrong."""
    always_fails = FlakyCall(RateLimitError("still rate limited"), fail_times=99)

    with pytest.raises(RateLimitError, match="still rate limited"):
        await call_with_retry(always_fails, attempts=3, backoff=FAST_BACKOFF, label="test")

    assert always_fails.calls == 3


@pytest.mark.asyncio
async def test_non_transient_error_is_not_retried():
    """A clear client error (bad API key, 401) must fail on the very first
    attempt - retrying it would only delay a message the user should see
    immediately."""
    auth_failure = FlakyCall(AuthenticationError("bad key"), fail_times=99)

    with pytest.raises(AuthenticationError, match="bad key"):
        await call_with_retry(auth_failure, attempts=3, backoff=FAST_BACKOFF, label="test")

    assert auth_failure.calls == 1


@pytest.mark.asyncio
async def test_each_attempt_issues_a_fresh_call_not_a_reused_coroutine():
    """`call_with_retry` takes a zero-arg callable and calls it again on every
    retry - it must never try to re-await the same coroutine object twice."""
    calls = []

    async def flaky():
        calls.append(len(calls))
        if len(calls) < 2:
            raise RateLimitError("transient")
        return "done"

    result = await call_with_retry(flaky, attempts=3, backoff=FAST_BACKOFF, label="test")

    assert result == "done"
    assert calls == [0, 1]


class TestIsTransientError:
    def test_rate_limit_status_code_is_transient(self):
        exc = Exception("rate limited")
        exc.status_code = 429
        assert is_transient_error(exc) is True

    def test_server_error_status_code_is_transient(self):
        exc = Exception("boom")
        exc.status_code = 503
        assert is_transient_error(exc) is True

    def test_client_error_status_code_is_not_transient(self):
        exc = Exception("bad request")
        exc.status_code = 400
        assert is_transient_error(exc) is False

    def test_auth_error_status_code_is_not_transient(self):
        exc = Exception("unauthorized")
        exc.status_code = 401
        assert is_transient_error(exc) is False

    def test_httpx_timeout_is_transient(self):
        assert is_transient_error(httpx.ConnectTimeout("timed out")) is True

    def test_httpx_connect_error_is_transient(self):
        assert is_transient_error(httpx.ConnectError("connection refused")) is True

    def test_rate_limit_error_by_name_is_transient(self):
        assert is_transient_error(RateLimitError("x")) is True

    def test_unrecognised_error_is_not_transient(self):
        assert is_transient_error(ValueError("some app bug")) is False
