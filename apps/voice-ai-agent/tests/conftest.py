import pytest

from app.core.rate_limit import reset_rate_limits


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    """`TestClient` requests all share one fake client host ("testclient"),
    so the in-memory rate limiter's per-IP buckets would otherwise leak state
    between unrelated tests in the same process."""
    reset_rate_limits()
    yield
    reset_rate_limits()
