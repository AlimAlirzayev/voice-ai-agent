"""LangChain chat model over the Claude Code CLI (`claude -p`).

Why this exists: the council's members must speak literary Azerbaijani, and the
best writer we have measured for that is Claude, reached through the operator's
subscription rather than a metered API key. The IELTS examiner already runs on
this principle with an AutoGen client; this is the same idea for LangChain, so
`graph/builder.py` needs no change at all - it only ever calls `ainvoke`.

Each call is a fresh, stateless CLI child: no tools, no MCP servers, no
CLAUDE.md, no session file. The system prompt travels as `--system-prompt`,
the conversation as a plain transcript on stdin, and the answer comes back as
one JSON document (`--output-format json`).
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import time
from typing import Any, Sequence

from langchain_core.callbacks import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult


from app.services.llm import LLMError

# Shown to the person when the subscription window is exhausted (measured
# 2026-09-25 05:50: exit 1 with 0 input/output tokens). The API maps any
# LLMError to 503 and the demo page prints its text, so this sentence is
# what a user reads instead of "Internal Server Error".
CAPPED_TEXT = (
    "Divan hazırda dincəlir — şuranın bu saatlıq söz payı tükənib. "
    "Bir az sonra yenidən soruşun, məclis yenə sizi dinləyəcək."
)


class ClaudeCLIError(LLMError):
    """The CLI child failed, timed out or answered with something that is not JSON.

    An LLMError on purpose: the chat/voice endpoints already turn that into a
    clean 503 with a readable detail instead of a 500 traceback."""


# At most this many CLI children at once per process: the subscription is one
# account, and the council already serialises its members inside a turn.
_SEMAPHORE = asyncio.Semaphore(3)


def render_transcript(messages: Sequence[BaseMessage]) -> tuple[str, str]:
    """Split LangChain messages into (system prompt, transcript for stdin).

    System messages are joined into one system prompt. Everything else becomes
    a labelled transcript; the final instruction tells the model to answer as
    the assistant instead of continuing the transcript.
    """
    system_parts: list[str] = []
    lines: list[str] = []
    for m in messages:
        content = m.content if isinstance(m.content, str) else json.dumps(m.content, ensure_ascii=False)
        if isinstance(m, SystemMessage):
            system_parts.append(content)
        elif isinstance(m, HumanMessage):
            lines.append(f"User: {content}")
        elif isinstance(m, AIMessage):
            lines.append(f"Assistant: {content}")
        else:
            lines.append(f"{m.type}: {content}")
    transcript = "\n\n".join(lines) if lines else "(no messages)"
    transcript += "\n\nReply as the assistant. Do not repeat the transcript, do not add a label."
    return "\n\n".join(system_parts), transcript


class ClaudeCLIChat(BaseChatModel):
    """`BaseChatModel` whose every call is one `claude -p` subprocess."""

    model: str = "claude-fable-5-1"
    binary: str = "claude"
    timeout: float = 150.0
    effort: str = "medium"
    cwd: str = "/tmp"
    # The CLI exposes no temperature; kept so call sites that read it still work.
    temperature: float = 0.7
    # Telemetry, mutated in place (pydantic field, not a property, on purpose).
    calls: int = 0
    seconds: float = 0.0

    @property
    def _llm_type(self) -> str:
        return "claude-cli"

    @property
    def _identifying_params(self) -> dict[str, Any]:
        return {"model": self.model, "effort": self.effort}

    # ---------------------------------------------------------------- helpers
    def _command(self, system: str) -> list[str]:
        cmd = [self.binary, "-p", "--output-format", "json", "--model", self.model,
               "--tools", "", "--strict-mcp-config", "--no-session-persistence",
               "--setting-sources", "", "--permission-mode", "default"]
        if system:
            cmd += ["--system-prompt", system]
        return cmd

    def _env(self) -> dict[str, str]:
        env = dict(os.environ)
        env.setdefault("PYTHONIOENCODING", "utf-8")
        env.pop("CLAUDECODE", None)  # a nested CLI must not think it is inside a session
        if self.effort:
            env["CLAUDE_CODE_EFFORT_LEVEL"] = self.effort
        return env

    def _parse(self, out: bytes, err: bytes, returncode: int) -> tuple[str, dict]:
        if returncode != 0:
            raise ClaudeCLIError(self._failure_text(out, err, returncode))
        try:
            data = json.loads(out.decode("utf-8", "replace"))
        except json.JSONDecodeError as exc:
            raise ClaudeCLIError(f"claude -p returned non-JSON: {out[:200]!r}") from exc
        if data.get("is_error"):
            raise ClaudeCLIError(f"claude -p error: {str(data.get('result', ''))[:400]}")
        text = data.get("result") or ""
        if not isinstance(text, str):
            text = json.dumps(text, ensure_ascii=False)
        usage = data.get("usage") or {}
        return text.strip(), {"usage": usage, "model": self.model,
                              "duration_ms": data.get("duration_ms"), "cost_usd": data.get("total_cost_usd")}

    @staticmethod
    def _failure_text(out: bytes, err: bytes, returncode: int) -> str:
        """A readable reason: the CLI's own `result` text when it sent JSON,
        the capped-window sentence when it spent zero tokens."""
        try:
            data = json.loads(out.decode("utf-8", "replace"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            data = None
        if isinstance(data, dict):
            usage = data.get("usage") or {}
            if not usage.get("input_tokens") and not usage.get("output_tokens"):
                return CAPPED_TEXT
            reason = str(data.get("result") or "")[:300]
            if reason:
                return f"claude -p exit {returncode}: {reason}"
        return f"claude -p exit {returncode}: {(err or out).decode('utf-8', 'replace')[:300]}"

    def _result(self, text: str, meta: dict) -> ChatResult:
        message = AIMessage(content=text, response_metadata=meta)
        return ChatResult(generations=[ChatGeneration(message=message)])

    # ---------------------------------------------------------------- async
    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        system, transcript = render_transcript(messages)
        t0 = time.time()
        async with _SEMAPHORE:
            # The CLI auto-updates in place; for a few seconds the binary is
            # absent. Measured 2026-09-25 05:34 during audit v3: eight turns in
            # a row died on FileNotFoundError (500). Wait it out, don't fail.
            for attempt in range(4):
                try:
                    proc = await asyncio.create_subprocess_exec(
                        *self._command(system), stdin=asyncio.subprocess.PIPE,
                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                        cwd=self.cwd, env=self._env(),
                    )
                    break
                except FileNotFoundError:
                    if attempt == 3:
                        raise ClaudeCLIError(f"`{self.binary}` not found (CLI update in progress?)")
                    await asyncio.sleep(10 * (attempt + 1))
            try:
                out, err = await asyncio.wait_for(proc.communicate(transcript.encode("utf-8")), timeout=self.timeout)
            except asyncio.TimeoutError:
                proc.kill()
                raise ClaudeCLIError(f"claude -p timed out after {self.timeout:.0f}s")
        self.calls += 1
        self.seconds += time.time() - t0
        text, meta = self._parse(out, err, proc.returncode or 0)
        return self._result(text, meta)

    # ---------------------------------------------------------------- sync
    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        system, transcript = render_transcript(messages)
        t0 = time.time()
        try:
            proc = subprocess.run(
                self._command(system), input=transcript.encode("utf-8"), capture_output=True,
                cwd=self.cwd, env=self._env(), timeout=self.timeout, check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ClaudeCLIError(f"claude -p timed out after {self.timeout:.0f}s") from exc
        self.calls += 1
        self.seconds += time.time() - t0
        text, meta = self._parse(proc.stdout, proc.stderr, proc.returncode)
        return self._result(text, meta)
