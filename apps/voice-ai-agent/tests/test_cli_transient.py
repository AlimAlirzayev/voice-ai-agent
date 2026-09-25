"""A CLI child that spent zero tokens is retried; a real failure is not."""
import asyncio
import json

import pytest
from langchain_core.messages import HumanMessage

from app.services import claude_cli
from app.services.claude_cli import CAPPED_TEXT, ClaudeCLIChat, ClaudeCLIError

ZERO = json.dumps({"duration_api_ms": 0, "usage": {"input_tokens": 0, "output_tokens": 0}}).encode()
REAL = json.dumps({"result": "bad request", "usage": {"input_tokens": 12, "output_tokens": 0}}).encode()
OK = json.dumps({"result": "Salam", "usage": {"input_tokens": 5, "output_tokens": 2}}).encode()


def _model(monkeypatch, outcomes):
    monkeypatch.setattr(claude_cli, "TRANSIENT_BACKOFF", (0.0, 0.0))
    m = ClaudeCLIChat()
    seen = []

    async def fake(self, system, transcript):
        out, code = outcomes[len(seen)]
        seen.append(code)
        return self._parse(out, b"", code)

    monkeypatch.setattr(ClaudeCLIChat, "_run_once", fake)
    return m, seen


def test_zero_token_exit_is_retried_then_answers(monkeypatch):
    m, seen = _model(monkeypatch, [(ZERO, 1), (ZERO, 1), (OK, 0)])
    msg = asyncio.run(m.ainvoke([HumanMessage("salam")]))
    assert msg.content == "Salam" and len(seen) == 3


def test_zero_token_exit_gives_polite_text_after_last_try(monkeypatch):
    m, seen = _model(monkeypatch, [(ZERO, 1)] * 3)
    with pytest.raises(ClaudeCLIError) as e:
        asyncio.run(m.ainvoke([HumanMessage("salam")]))
    assert str(e.value) == CAPPED_TEXT and len(seen) == 3


def test_failure_that_spent_tokens_is_not_retried(monkeypatch):
    m, seen = _model(monkeypatch, [(REAL, 1)])
    with pytest.raises(ClaudeCLIError) as e:
        asyncio.run(m.ainvoke([HumanMessage("salam")]))
    assert not e.value.transient and len(seen) == 1
