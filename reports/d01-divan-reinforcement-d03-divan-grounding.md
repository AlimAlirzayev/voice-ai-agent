# d01-divan-reinforcement-d03-divan-grounding

## Premise check (read first)
The brief points at files that do not exist on this branch or on `main`:
`docs/reinforcement/d01-backlog.md` (B3/B4), `app/evals/offline.py`,
`persona_golden.json`, and parent commit `2bc9eeb62c15`. The "0/2 off-topic" baseline
therefore could not be reproduced or read. I built the missing pieces (`app/evals/offline.py`,
`app/evals/persona_golden.json`) and measured my own before/after on them. The golden set is
authored by me, not inherited; treat its numbers as a regression gate, not as the d01 baseline.

Branch: the session pinned `claude/divan-grounding-abstention-gpj2h9`; the footer asks for
`cloudlab/d01-divan-reinforcement-d03-divan-grounding`. I pushed only to the pinned branch.

## What was built
- `app/rag/bm25.py`: a passage is cited only if it shares at least 3 distinct stems with the
  question (2 for a two-stem question, never fewer than 2). `search()` takes keyword-only
  `min_score` / `min_matched`; defaults and the `BM25Retriever` surface are unchanged.
- `app/graph/guardrails.py` + `builder.py`: `is_out_of_scope()`, a deterministic gate for plain
  task requests (code, crypto quotes, weather, recipes, scores, translation, tax forms). On the
  first supervisor hop it skips the router and goes to the host reply, so no advisor speaks.
  High precision, low recall by design; bare topic words ("futbol", "hava", "pul") stay in scope.
- `app/rag/ingest.py`: `strip_markup()` at load time removes the `{{Başlıq…}}` template and the
  lone `thumbnail` line. Corpus files were NOT edited: nothing in the repo or brief records the
  owner's approval to change quotable text. Consequence: Nəsimi *Rübailər* refs shift by one
  (old "bənd 2" is now "bənd 1"), because the template was chunk 1.
- `app/evals/offline.py` + `persona_golden.json` (21 retrieval, 10 abstain, 10 off-topic scope,
  8 borderline cases), CI step `python -m app.evals.offline`, `tests/test_grounding_abstention.py`.

## Measured
Command: `cd apps/voice-ai-agent && python -m app.evals.offline` (`--no-gate` reproduces before).

| metric | before | after |
|---|---|---|
| hit@2 | 0.952 | 0.952 |
| MRR | 0.944 | 0.944 |
| citation faithfulness | 1.000 (41 citations) | 1.000 |
| retrieval abstention, off-topic | 0/10 | 10/10 |
| council scope abstention, off-topic | 0/10 (no gate) | 10/10 |
| borderline answered | 8/8 | 8/8 |
| chunks carrying markup | 2 | 0 |

Test suite: 127 passed (121 before + 6 new). `python -m app.evals.run`: 8/8.

Side effect: on the 20 audit questions (`audit_set.json`), questions that receive any citation
fall from 17 to 8. The dropped ones I inspected were weak single-word matches (e.g. a
neighbour-parking question citing the Molla/Teymur dungeon scene), but two Nəsimi ones were
plausible. Fewer citations is the intended trade; the size of it is a decision for the owner.

## Not measured
- The live router LLM: whether it abstains on off-topic questions without the new gate.
- Council-level answers end to end (needs provider credits); only the deterministic path ran.
- The embeddings backend (`RAG_BACKEND=embeddings`): untouched, still gated by cosine `MIN_SCORE`.
- Generalisation: thresholds were chosen on the same small set they are scored on. No held-out set.
- Cyrillic "О" in the Zümrüd quşu text ("О saat") is visible but was left alone.

## Open questions
- Does the owner approve editing quotable corpus text (the two flagged files)? If yes, remove
  the two debris blocks at source and drop the loader cleaner's file-specific tests.
- Where are d01 B3/B4 and the original 0/2 cases? Please supply them to rerun against this gate.
- Accept ref renumbering for Rübailər?

## Recommended next briefs
1. Held-out abstention set (30+ off-topic and borderline questions, written by someone else).
2. Live router eval with credits: off-topic abstention with and without the scope gate.
3. Same coverage gate for the embeddings backend, then compare the two on one set.
