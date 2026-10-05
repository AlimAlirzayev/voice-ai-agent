# d02 — Divan latency report

Branch `cloudlab/d01-divan-reinforcement-d02-divan-latency`, based on `2bc9eeb` (d01). Migration notes: `docs/reinforcement/d02-latency.md`.

## Built

1. **B1, single-call routing.** One router call returns up to two members ("SIMURG KOROGLU"); they speak in turn, the router is not asked again. Rollback: `COUNCIL_ROUTING=iterative`.
2. **B2, parallel TTS.** The clips of a reply are synthesized concurrently, at most `TTS_CONCURRENCY` (default 4) at a time; order unchanged; one failed clip fails the reply with 502 and cancels the rest.
3. **B5, streaming.** New `POST /chat/stream` and `POST /voice/stream` (SSE): `narration`, `opinion`, `segment` (voice), then `done` with the exact body of the non-streaming route. TTS for member 1 starts while member 2 is written. Old routes untouched.
4. **Offline timing harness.** `python -m app.evals.latency` counts model calls and wall time with a delayed scripted model and TTS stub, before (`iterative`, serial TTS) against after.

## Measured

Fake model and TTS, 1.0 s per call and per clip. Command (from `apps/voice-ai-agent`): `python -m app.evals.latency --delay 1.0`.

| Case | Before | After |
|---|---|---|
| Model calls, greeting | 2 | 2 |
| Model calls, one member | 3 | 2 |
| Model calls, two members | 4 | 3 |
| Turn wall time, one member | 3.10 s | 2.01 s |
| Turn wall time, two members | 4.01 s | 3.01 s |
| TTS, 3 clips | 3.00 s serial | 1.00 s parallel |
| Stream, first event | — | 0.0 s of 3.01 s |
| Stream, first member's words | — | 2.01 s of 3.01 s |

| Check | Result | Command |
|---|---|---|
| Tests | 188 → 217 passed (29 new in `tests/test_latency.py`) | `python -m pytest -q` |
| Offline eval | output identical to the d01 baseline, gates OK, exit 0 | `python -m app.evals.offline` |
| Lint on touched files | no new findings; 6 older findings remain in `offline.py`, `voice_bench.py`, `test_corpus_clean.py`, `test_local_stack.py` | `ruff check app tests` |

Acceptance from the backlog: single-member turn makes exactly 2 model calls and two-member turn 3 (tested); 4 clips at 0.2 s finish in under 0.5 s with identical order (tested); first stream event under 25 % of the turn (tested); `done` bodies equal the `/chat` and `/voice` bodies apart from `turn_id` (tested).

## Not measured

- Live latency. The target "audit v6 mean ≤ 0.7 × 60.8 s" needs the Claude CLI and quota; not run. Structurally one model call fewer per non-greeting turn (−25 % to −33 % of calls); the live gain is that share of the per-call time, not more.
- Whether the real router answers two names in the new prompt as intended (only scripted answers were tried), and whether answer quality holds when both members are chosen up front. Needs audit v6 plus `--judge`.
- Real ElevenLabs/Azure behaviour at 4 concurrent requests (rate limits per plan).
- Browser or Telegram clients against the stream routes; none consume them yet.
- Advisors still run one after another (member 2 hears member 1); running them in parallel was not attempted.

## Open questions

- Is `TTS_CONCURRENCY=4` inside the ElevenLabs plan's concurrent-request limit? Lower it if 429s appear.
- Should the web UI and the Telegram bot move to the stream routes, and should `/chat/resume` get a stream variant?
- The session was told to develop on `claude/divan-latency-optimization-umdmk2`; the brief's footer requires this `cloudlab/` branch, which is the one pushed.

## Recommended next briefs

1. Live audit v6 (latency and judge scores) with `single_call` vs `iterative`.
2. Web and Telegram clients on `/chat/stream` and `/voice/stream`.
3. B3, abstention gate fix (still open in the backlog).
4. Parallel advisors for questions that clearly span two domains, if audit v6 shows the call count is still the bottleneck.
