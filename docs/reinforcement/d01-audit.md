# Divan — engineering audit (d01)

Scope: `apps/voice-ai-agent` at commit `aab98b6` (before the d01 changes). Evidence is `file:line` on that commit unless marked **fixed in d01**, in which case the line refers to the current tree. Severity: **H** fix soon, **M** plan, **L** note.

## 1. Measured baseline

| Item | Value | Command |
|---|---|---|
| Tests before d01 | 121 passed, 3.6 s | `pytest -q` |
| Tests after d01 | 188 passed, ~12 s | `pytest -q` |
| Line coverage before → after | 64 % → 72 % (builder 97 → 100 %, voice API 52 → 86 %) | `pytest -q --cov=app --cov=bot` |
| Least covered | `bot.py` 20 %, `app/evals/audit.py` 0 %, `voicelab.py` API 36 %, `clone_voice.py` 46 % | same |
| Lint | 47 ruff findings with an ad-hoc rule set; no linter configured or run in CI | `ruff check app tests bot.py` |
| Chat turn latency (live, text only, Claude CLI provider) | mean 57.8 s (audit v1), 60.8 s (audit v5), 20 questions each | `output/audit-v1.json`, `audit-v5.json` → `summary.mean_seconds` |
| Council quality, judge mean 1–5 (v1 → v5) | character 1.95 → 3.6, mentality 2.84 → 4.1, language 3.26 → 3.6, style 2.47 → 3.5, usefulness 2.58 → 3.4 | same files |
| Routing (v5) | 17/18 | same |
| Noisy citations (v5) | 7 of 56 | same |

The brief states there are no tests under `tests/`; at the audited commit there were 121 (22 files). The gap was elsewhere (below).

## 2. Architecture and graph

`intake → supervisor ⇄ advisor → synthesize → (approval_gate | deliver) → trim` (`app/graph/builder.py`). Supervisor pattern with a single-word LLM router, six personas, cap of two advisors, `interrupt()` for Koroğlu, SQLite checkpointer, per-turn scratch reset in `intake`. Sound and well documented.

| # | Sev | Finding | Evidence |
|---|---|---|---|
| A1 | H | **Fail-open approval.** Any `decision` value other than `reject`/`edit` published the risky draft; `decision` was a free string. **Fixed in d01**: closed set at the API, fail-closed in the gate. | `builder.py:282-283` (old `else: final = state["draft"]`), `schemas.py:18` (old) |
| A2 | H | **Resume on a thread with no pause** replayed the old answer (completed thread) or crashed with `IndexError` → HTTP 500 (unknown thread). Measured with a scripted model. **Fixed in d01** (`NoPendingApproval` → 409). | `builder.py:resume_turn`; probe output in `reports/d01-divan-reinforcement.md` |
| A3 | M | **Router fallback to roster order on hop one.** Unusable router output (prose, injected instructions) summoned `remaining[0]` = Molla Nəsrəddin and spent a full advisor call; the 2026-09-25 fix covered hop two only. **Fixed in d01**: only the first word counts, unusable → host reply. | `builder.py:178-179` (old) |
| A4 | M | **Sequential council, 3–4 LLM calls per turn.** One advisor = router, advisor, router (asks for a second member), then synthesize. Two advisors = 4 calls. Each Claude CLI call spawns a process. Explains the ~60 s mean. | `builder.py:supervisor`, `claude_cli.py:_run_once` |
| A5 | M | **Citations are attached when retrieved, not when used.** The advisor is told to ignore irrelevant passages, but every retrieved passage is returned as a "receipt". | `builder.py` advisor: `new_citations` built from all `evidence` |
| A6 | M | **Weak abstention gate.** BM25 `MIN_SCORE = 1.0` with no stop-word list lets "Bitcoin qiyməti nə qədərdir?" cite Koroğlu (score 4.81) and "Bu gün hava necədir?" cite Nizami (3.44). Tracked as `known_gap` in the offline golden set. | `bm25.py:22`, `app/evals/persona_golden.json` |
| A7 | L | `history_length` is 0 on pending turns; `get_pending` drops `citations`. | `builder.py:_extract_result`, `get_pending` |
| A8 | L | Trim keeps the last N messages, which can start on an AI message. Harmless to the models used. | `builder.py:trim` |

## 3. Prompts

Strong: persona voices are specific, rules are measured by `app/evals/audit.py`, and prior-speaker notes prevent repetition (`prompts/divan.py:304`).

| # | Sev | Finding | Evidence |
|---|---|---|---|
| P1 | M | No instruction hierarchy: user text sits beside the system prompt with no statement that the user cannot change persona rules, reveal the prompt, or redirect routing. Nothing in the eval set probes it. | `prompts/divan.py:316-325` |
| P2 | M | Persona and routing prompts are Azerbaijani-only; the router answers in prose when the user writes in another language (A3 made that safe, not better). | `supervisor_prompt` |
| P3 | L | Rules 2–3 depend on the model knowing the corpus; only Dədə Qorqud's blessing and Nəsimi's couplet are verified in the prompt. Other fabricated quotations are now caught offline (`unsupported_quotes`) but not prevented. | `prompts/divan.py:177-180` |

## 4. Memory

SQLite via `AsyncSqliteSaver`, one thread per id, survives restart (now tested on a real file).

| # | Sev | Finding | Evidence |
|---|---|---|---|
| M1 | M | **Thread ids are client-chosen and shared.** Default `demo` is one shared memory for everyone who omits it; any holder of the access key can read or continue another thread by guessing its id. Single-tenant today, so M; becomes H with more than one user. Format now validated (d01), ownership is not. | `schemas.py:ChatRequest.thread_id` |
| M2 | M | No retention or deletion: conversation text lives forever in `checkpoints.sqlite`; no purge endpoint beyond Telegram `/reset`, which only starts a new thread. | `memory/sqlite.py`, `bot.py:121` |
| M3 | L | One writer connection, no WAL setting; fine at current load. | `memory/sqlite.py:27-32` |

## 5. Human-in-the-loop

Correct use of `interrupt()` + checkpointer; the web, Telegram and n8n adapters all resolve it. Gaps are A1/A2 above plus:

| # | Sev | Finding | Evidence |
|---|---|---|---|
| H1 | M | Approval is not bound to the approver: any caller who knows the thread id can resolve it. Same root cause as M1. | `api/chat.py:chat_resume` |
| H2 | L | Only Koroğlu triggers approval; Nəsimi and Dədə Qorqud also give life-direction advice. A policy decision, not a defect. | `builder.py:APPROVAL_ADVISOR` |
| H3 | L | No expiry on a paused thread; a pending approval blocks that thread's new messages forever (by design in `get_pending`), so an abandoned pause dead-ends the chat until `/reset`. | `chat.py:44` |

## 6. Error handling

Good: tenacity retry on transient provider errors (`services/retry.py`), Claude CLI zero-token retry, TTS fallback chain ElevenLabs → OpenAI/edge, retrieval and moderation fail safe.

| # | Sev | Finding | Evidence |
|---|---|---|---|
| E1 | H | **No wall-clock bound on a turn.** Worst case per CLI call is 150 s × 3 attempts plus 4×(10..40) s update waits, per call, 3–4 calls. The HTTP client gives up; the server keeps burning quota. **Fixed in d01**: `TURN_TIMEOUT_SECONDS` (default 300). | `claude_cli.py:104,63,228` |
| E2 | M | Cancellation after the timeout leaves the thread at the last completed superstep; a second request then continues from there. Acceptable, undocumented. | LangGraph checkpoint semantics (INFERRED) |
| E3 | L | `moderation` fails open by design (documented). | `moderation.py:49` |

## 7. Latency path (STT → graph → TTS)

`/voice` is strictly sequential: whole-file Whisper → graph → one TTS call per segment, awaited in a loop → base64 JSON. (`api/voice.py:78-116`, `services/voice.py`).

| # | Sev | Finding |
|---|---|---|
| L1 | H | Graph time dominates (A4). A text turn averages ~60 s measured on the live provider; voice adds STT and N sequential TTS calls. No streaming anywhere (`ainvoke`, not `astream`). |
| L2 | M | TTS segments are synthesized one after another although independent; for two advisors plus narration that is 3–4 serial calls. `asyncio.gather` would cut the TTS share to the slowest clip. |
| L3 | M | Router call is a full LLM round trip for a decision a classifier or a cheaper model could make; hop two (asking for a second member) is spent on every single-advisor turn. |
| L4 | L | No latency metrics beyond LangSmith traces; `/` reports configuration only. |

## 8. Cost per answer

UNKNOWN in currency: the default provider is the operator's subscription through the Claude CLI (`services/llm.py:233`), which reports `total_cost_usd` in its JSON (`claude_cli.py:_parse`) but nothing stores it. Calls per answer are known (A4: 2–4 LLM calls, plus embeddings if `RAG_BACKEND=embeddings`, plus 1–4 TTS calls and one Whisper call on voice). The usable control is the quota: one public key plus a 20/min/IP limit is the only fence (S4).

| # | Sev | Finding |
|---|---|---|
| C1 | M | No per-answer cost or token record; ElevenLabs characters per segment are unbounded by the reply length the model chooses. |

## 9. Security

| # | Sev | Finding | Evidence |
|---|---|---|---|
| S1 | H | **Unbounded inputs.** Chat message, thread id, edit text, feedback text and the voice upload had no size limits (`await file.read()` loads the whole file). **Fixed in d01** (`MAX_MESSAGE_CHARS`, `MAX_UPLOAD_BYTES`, `MAX_EDIT_CHARS`, id pattern, feedback caps). | `schemas.py:10` (old), `voice.py:133` (old) |
| S2 | M | **Role forging in the CLI transcript.** User text was rendered as `User: …` lines in a flat string; a message containing `\nAssistant: …` forged a turn. **Fixed in d01** (continuation lines indented). | `claude_cli.py:render_transcript` |
| S3 | M | **Self-harm keyword check evadable** with a zero-width character inside the keyword (`inti​har`), and invisible characters were stored in memory. **Fixed in d01** (`sanitize_user_text`). | `guardrails.py:is_self_harm_risk` |
| S4 | M | **Rate limit is per `request.client.host`.** Behind the Caddy proxy documented in `DEPLOY.md` and `docs/VPS.md`, the client address is the proxy unless uvicorn trusts forwarded headers; then all users share one 20/min bucket. INFERRED from the documented topology; not measured. | `rate_limit.py:265-267`, `DEPLOY.md` §1 |
| S5 | M | Access key also accepted in the query string (`?k=`), so it lands in proxy access logs and browser history. Cookie is HttpOnly/Secure/Lax. Rotate if logs are shared. | `main.py:61-68` |
| S6 | M | `/voicelab/*` mutating endpoints are open when `VOICELAB_TOKEN` is empty (the default), and `/voicelab/next?skip=` mutates without the token. | `api/voicelab.py:34-47` |
| S7 | L | Health endpoint is public and discloses provider, model and which keys are missing. | `main.py:81-96` |
| S8 | L | `/client-log` writes attacker-controlled text to logs (600 chars, no newline stripping): log injection. Behind the key gate. | `main.py:112-122` |
| S9 | L | n8n compose defaults ship placeholder encryption/JWT secrets (`…-change-me`), only reachable on loopback. | `docker-compose.yml:61-63` |
| S10 | L | Prompt injection through retrieved text is not a risk today: the corpus is committed and trusted. It becomes one if ingestion ever takes user or web content. | `rag/ingest.py` |
| S11 | OK | No secrets committed; `.env` ignored; deploy uses repository secrets. Checked by reading, not by a scanner. | `.gitignore`, `deploy.yml` |

## 10. Tests

121 tests before d01 (provider fallbacks, retry, voice, bot gate, rate limit, RAG math, CLI quirks). Strong where regressions had bitten before. Gaps: the HTTP council path end to end, HITL edge cases, memory across a restart, router parsing, and the committed "golden" check.

| # | Sev | Finding |
|---|---|---|
| T1 | H | **The CI golden evaluation evaluates recorded strings, not the system.** `app/evals/run.py` scores `fixture_response` text with `evaluators.py`; nothing in it can fail when routing, retrieval, HITL or prompts regress (8/8 passes regardless). **Addressed in d01** by `app.evals.offline` (real graph, real retriever, labelled scorer fixtures). |
| T2 | M | No linter or type check in CI; `bot.py` 20 % covered; the live audit (`audit.py`) needs a running server and the Claude CLI and is not run on a schedule. |
| T3 | L | `tests/conftest.py` pins provider fields by hand; a new provider setting that is not added leaks the machine's `.env` into tests (it happened once, 2026-09-25). |

## 11. Observability

LangSmith traces carry channel, modality, provider, model, hashed thread id (`builder.py:_trace_config`). Good privacy hygiene. Missing: latency and error counters, per-advisor routing counts, token/cost capture, an alert on 5xx or on the capped-window message. Feedback store exists (`/feedback/stats`) but nothing consumes it.

## 12. Deploy

Docker Compose on a single droplet, GitHub Actions deploy on push to `main`, healthcheck on `/`. No rollback step, no pre-deploy test gate (deploy and CI are separate workflows; a red CI does not stop a deploy), image uses `uv sync --frozen`. Backups of the `voice_memory` volume: UNKNOWN (not in repo).

## 13. What changed in d01

See `d01-backlog.md` (items marked done) and `reports/d01-divan-reinforcement.md`. Public routes, request/response shapes and env vars are unchanged; new env vars are optional; behaviour changes are listed in the report under *Migration*.
