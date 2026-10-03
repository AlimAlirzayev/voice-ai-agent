# Divan — reinforcement backlog (d01)

Ranked by impact ÷ effort. Impact: how much it moves latency, safety, or answer quality for the live product. Effort: S ≤ half a day, M ≈ 1–2 days, L > 2 days. Every item has an acceptance test that can be run without a person in the loop unless stated.

## Done in d01

| ID | Item | Acceptance test (now passing) |
|---|---|---|
| D1 | Input bounds, closed decision set, fail-closed approval, 409 on resume without pause, turn timeout, invisible-character stripping, transcript role-forging fix, first-word routing | `pytest tests/test_hardening.py` (43 tests) |
| D2 | Offline persona / grounding eval with golden set, wired into CI | `python -m app.evals.offline` exits 0; `pytest tests/test_offline_eval.py` |
| D3 | End-to-end council tests with scripted model, STT, TTS | `pytest tests/test_council_e2e.py` (11 tests) |
| D4 | B1 single-call routing, B2 parallel TTS, B5 streaming routes (d02) | `pytest tests/test_latency.py`; `python -m app.evals.latency` |

## Open, ranked

| Rank | ID | Item | Impact | Effort | Acceptance test |
|---|---|---|---|---|---|
| 3 | B3 | **Fix the abstention gate.** Add an Azerbaijani stop-word list and a relative-score floor to BM25; return no passages when the query has no content words. Only attach citations the advisor actually used (ask the advisor to return the passage numbers it leaned on, or drop passages below a higher floor). | H (a bad receipt is worse than none) | M | `abstain-bitcoin` and `abstain-hava` flip to XPASS in `python -m app.evals.offline`; lexical and natural hit@2 stay 1.00; then remove `known_gap` and gate `abstain_rate = 1.0`. |
| 4 | B4 | **Corpus hygiene.** Strip Wikisource template markup from `nesimi/rubailer.txt` and the `thumbnail` token from the Zümrüd quşu file; extend `is_usable` to reject `{{`, `thumbnail`, `[[` anywhere; refresh the chunk counts in `corpus/README.md`. | M (a debris chunk can be read aloud as Nəsimi) | S | `corpus_markup_chunks = 0`; lower the gate `corpus_markup_chunks_max` to 0. Needs the owner's OK: it edits the quotable corpus. |
| 6 | B6 | **Thread ownership.** Server issues an unguessable thread id bound to the access key or Telegram chat; reject resume and reads from other bindings. Keep `demo`/client ids working behind a flag for the n8n adapter. | M now, H with a second user | M | Test: caller B cannot resume or read caller A's thread (403); n8n flow with the flag on still passes. |
| 7 | B7 | **Trust the proxy correctly.** Run uvicorn with `--proxy-headers --forwarded-allow-ips=<caddy>` and key the limiter on the forwarded client; add a per-key daily budget. | M | S | Test with `X-Forwarded-For` from a trusted peer: two clients get separate buckets; from an untrusted peer the header is ignored. Verify live that the limiter sees client addresses (UNKNOWN today). |
| 8 | B8 | **Injection probes and instruction hierarchy.** Add 10 injection cases (ignore-rules, persona swap, prompt reveal, route forcing) to the golden set; add one hierarchy sentence to `DIVAN_QAYDALARI`. | M | S | New cases pass offline (router/HITL/crisis contracts) and in the live audit (persona holds); offline rubric gate unchanged. |
| 9 | B9 | **Calibrate the judge.** 30–50 replies labelled by a native speaker on separate binary rubrics (character, language, grounding); report agreement (Cohen's kappa) between judge and human. Needs a person. | M | M | kappa ≥ 0.6 per rubric, or the judge is demoted to trend-only in the docs. |
| 10 | B10 | **Observability.** Record per-turn seconds, call count, route taken, `total_cost_usd` from the CLI JSON, and error class; expose `/metrics` or log JSON lines; alert on 5xx rate and the capped-window message. | M | M | Test: a turn emits one metrics record with the five fields; capped-window path increments its counter. |
| 11 | B11 | **Deploy gate.** Make the deploy workflow depend on CI for the same commit; add a rollback to the previous image tag. | M | S | A commit with a failing test does not deploy (verified on a throwaway branch). |
| 12 | B12 | **Lint and types in CI.** Add a `ruff` config with a small rule set and fix or waive the 47 current findings; add `mypy` on `app/graph` and `app/models`. | L | M | `ruff check` and `mypy` exit 0 in CI. |
| 13 | B13 | **Voicelab and info leaks.** Require `VOICELAB_TOKEN` when `DIVAN_ACCESS_KEY` is set (including `/voicelab/next?skip=`); trim `/` to `{"status":"ok"}`; strip newlines in `/client-log`. | L–M | S | Tests: 403 without token; `/` has no model or key hints; log line has no raw newlines. |
| 14 | B14 | **Retention and deletion.** `DELETE /threads/{id}` (owner-gated) and a configurable purge of threads idle for N days; expiry for paused approvals. | M | M | Test: purge removes checkpoints older than N days and leaves newer ones; an expired pause lets the thread accept a new message. |
| 15 | B15 | **Cover `bot.py`.** Handler tests with a fake Telegram `Update` and `httpx.MockTransport` for text, voice, approval, feedback and the owner gate. | M | M | `bot.py` coverage ≥ 70 %. |
