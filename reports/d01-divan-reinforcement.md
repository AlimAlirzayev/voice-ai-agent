# d01 — Divan reinforcement report

Branch `cloudlab/d01-divan-reinforcement`. Deliverables: `docs/reinforcement/d01-audit.md`, `d01-benchmark.md`, `d01-backlog.md`, plus three code commits with tests.

## Built

1. **Hardening** (`d33bf5d`): bounds on message, upload, transcript, edit text, thread id and feedback fields; resume decision limited to approve/reject/edit and the approval gate fails closed; resume without a paused turn is 409 (was a stale replay or a 500); `TURN_TIMEOUT_SECONDS` bounds one run (503); control, zero-width and bidi characters stripped before the crisis check and the checkpoint; user lines indented in the Claude CLI transcript; router trusts only the first word and sends an unusable answer to the host instead of the first roster member. 43 tests.
2. **Offline eval harness** (`3a24084`): `python -m app.evals.offline` — BM25 retrieval over the real corpus, citation faithfulness through the real graph, a deterministic persona rubric tested against 15 labelled fixtures, six graph contracts, an injectable judge layer; gates in `persona_golden.json`; runs in CI.
3. **End-to-end tests** (`82c01a1`): scripted model, STT and TTS over HTTP; 11 tests (HITL over chat and voice, two-advisor flow, cap of two, memory across a restart, thread isolation, trimming, error mapping).

## Measured

| What | Result | Command (from `apps/voice-ai-agent`) |
|---|---|---|
| Tests | 121 → 188 passed | `pytest -q` |
| Coverage | 64 % → 72 %; builder 100 %; voice API 86 % | `pytest -q --cov=app --cov=bot` |
| Offline eval | lexical hit@2 1.00 (22), natural 1.00 (3), MRR 0.98, citation faithfulness 1.00 (49), rubric agreement 1.00 (15), contracts 6/6 | `python -m app.evals.offline` |
| Abstention on off-topic questions | 0/2 (known gap, reported, not gated) | same |
| Corpus markup debris | 2 chunks (Nəsimi rübailər, Zümrüd quşu) | same |
| Pre-fix defects reproduced | garbage decision published the draft; resume on a finished thread replayed it; resume on an unknown thread raised `IndexError` | scripted-model probe before the fix |
| Live latency | mean 57.8 s and 60.8 s per text turn | read from committed `output/audit-v1.json`, `audit-v5.json`; not re-run |

## Not measured

Cost per answer in currency (the CLI reports it; nothing stores it). Live behaviour of any change against the real provider, Telegram or n8n. Whether the rate limiter sees real client addresses behind Caddy. Judge calibration against a human. Backups of the memory volume. The `--judge` stage was not run (needs the Claude CLI and quota).

## Migration

No route, field or env var removed or renamed. New optional env vars, all in `.env.example`: `MAX_MESSAGE_CHARS` (4000), `MAX_UPLOAD_BYTES` (15 000 000), `MAX_EDIT_CHARS` (2000), `TURN_TIMEOUT_SECONDS` (300); 0 disables each. Behaviour changes a client can see:
- `/chat`, `/chat/resume`, `/voice`, `/voice/resume` return 422 for thread ids outside `[A-Za-z0-9_.:@-]{1,128}` (the web, Telegram and n8n clients mint ids inside it) and for a `decision` other than approve/reject/edit, or `edit` without text. The Telegram bot and the n8n flows only send approve/reject.
- Resume with no paused turn returns 409 instead of 200/500.
- Oversized message, upload or transcript returns 422/413.
- A router that answers in prose now yields the host's reply instead of Molla Nəsrəddin.
- An unrecognised decision reaching the graph now rejects instead of approving.

## Open questions for the owner

1. May the two corpus files with markup debris be cleaned (B4)? It edits quotable text.
2. Is 300 s the right turn budget given the Claude CLI worst case, or should the CLI timeout be lowered first?
3. Is the app reachable by more than one person? If yes, B6 (thread ownership) moves to the top.

## Recommended next briefs

1. **d02 latency**: B1 + B2 + B5 (fewer calls, parallel TTS, streaming); acceptance in the backlog.
2. **d03 grounding**: B3 + B4, then gate abstention in the offline eval.
3. **d04 eval calibration**: B8 + B9 with a native-speaker labelling session.
4. **d05 ops**: B7, B10, B11, B13.
