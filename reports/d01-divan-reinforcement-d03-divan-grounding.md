# d01-divan-reinforcement-d03-divan-grounding

## Premise caveats (read first)
- The files the brief points at do not exist on `main` or on this branch: `docs/reinforcement/d01-backlog.md`
  (B3/B4), `app/evals/offline.py`, `persona_golden.json`, and parent commit `2bc9eeb62c15`.
- **The "0/2 off-topic" baseline is unverified.** I never saw those two cases or how they were scored.
- **The golden sets are self-authored** (tuning set: me, with the gate; held-out set: me, after the gate was frozen).
  Every before/after number below is therefore a **regression gate only**, not a reproduction of the d01 baseline
  and not evidence of live quality.
- Branches: the session pinned `claude/divan-grounding-abstention-gpj2h9`; the brief footer asks for
  `cloudlab/d01-divan-reinforcement-d03-divan-grounding`. Both carry the same commits.

## What changed
- `app/rag/bm25.py`: a passage is cited only if it shares at least 3 distinct stems with the question
  (all of them for a two-stem question, never fewer than 2). `search()` gains keyword-only `min_score` and
  `min_matched`; positional signature, hit shape and `BM25Retriever.retrieve(advisor, query, k)` are unchanged.
  The default result set is intentionally stricter than before; passing `min_matched=1` reproduces the old results exactly.
- `app/rag/ingest.py`: `strip_markup()` removes the `{{Başlıq…}}` template and the lone `thumbnail` line.
  It runs **per chunk after refs are assigned**, so no ref moves (see below). Corpus files are untouched:
  no owner approval to edit quotable text is on record.
- `app/graph/guardrails.py` + `builder.py`: `is_out_of_scope()` routes plain task requests straight to the host reply.
  **Its held-out recall is 0/12** (below); it is a narrow stopgap, not a topic classifier.
- `app/evals/offline.py`, `persona_golden.json` (tuning), `persona_golden_heldout.json` (held-out), CI step
  `python -m app.evals.offline`, `tests/test_grounding_abstention.py` (13 tests).

## 1. Held-out check
Cases written after the thresholds and patterns were frozen (commit `52dde5f`); never used to choose them.
Command: `python -m app.evals.offline --heldout` (report-only, `--no-gate` = before). 8 in-scope questions with a
known passage, 12 off-topic, 10 borderline in-scope.

| metric | tuning set before | tuning set after | held-out before | held-out after |
|---|---|---|---|---|
| hit@2 | 0.952 | 0.952 | 1.000 | 1.000 |
| MRR | 0.944 | 0.944 | 1.000 | 1.000 |
| citation faithfulness | 1.000 | 1.000 | 1.000 | 1.000 |
| retrieval abstention (off-topic gets no citation) | 0/10 | 10/10 | 1/12 | **12/12** |
| scope-gate abstention (off-topic reaches the host) | 0/10 (no gate) | 10/10 | 0/12 | **0/12** |
| borderline answered (not turned away) | 8/8 | 8/8 | 10/10 | 10/10 |

- The coverage gate generalised: 12/12 off-topic held-out questions get no citation, and all 8 in-scope held-out
  passages are still found.
- The scope-pattern gate did **not** generalise: it fires on none of the 12 held-out off-topic questions. Its tuning-set
  10/10 is in-sample and should not be read as capability. Its borderline 10/10 is nearly trivial, because it almost never fires.
- Per the instruction, I did not add patterns for the held-out cases. Loosening a keyword list would only trade
  recall for false abstentions on advice questions, so I left it as is and flagged it. Real council-level abstention needs a router-level or
  classifier-level fix and a live eval (not run).

## 2. Recall loss on the audit set
The audit set has 20 questions; 18 name an advisor (the other 2 are small talk). Questions with at least one citation:
17/18 before, 8/18 after. The 9 that lost it (relevance is my reading of the old top hit; please second-check the two marked weak):

| question id | old citation | relevant? |
|---|---|---|
| nesreddin-qonsu | Molla/Teymur dungeon scene (matched "mənim", "istəm") | no |
| nesreddin-reis | Molla before the qazı (matched "çıxar", "qabağ") | no |
| koroglu-haqq | Giziroğlu verse (matched "dostu", "başım") | no |
| simurg-mena | dragon at the spring (matched "var", "qırx") | no |
| simurg-telesmek | birds' qəsidə, "uşaqlar kimi" (matched one stem) | no |
| nesimi-deyer | Sığmazam bənd 4 (matched only "mən") | weak: thematically near, lexically accidental |
| nesimi-fikir | Zühur eylədi, "Nəsimi kimi" (matched only "kimi") | no: "kimi" is a function word |
| dedeqorqud-toy | Baybörə, "Ata dururkən oğul əlinmi öpərlər" | weak: father/son, different point |
| dedeqorqud-ana | Dirsə xan lament (matched "isə", "istəy") | no |

No clearly relevant Nəsimi citation was lost. Threshold sweep (same 21 retrieval, 10 abstain, 18 audit cases):

| rule | hit@2 | off-topic abstained | audit questions cited |
|---|---|---|---|
| score floor only (old) | 20/21 | 0/10 | 17/18 |
| min_matched 2 | 20/21 | 7/10 | 15/18 |
| **min_matched 3 (kept; two-stem questions need both)** | 20/21 | 10/10 | 8/18 |
| rare-stem variant: 2 stems incl. one with corpus df ≤ 1, else ≥3 | not run | 9/10 | 11/18 |

I tried the rare-stem rule you suggested. It brings back citations, but the ones it readmits are rare-because-
accidental stems ("kimi", "uşaql", "istəy") and it lets one off-topic question through. Since the lost Nəsimi hits
were not clearly relevant, I did not adopt it. MRR is unaffected by any of these rules (it is computed on the
unfloored ranking). The single hit@2 miss (`sim-divle`, gold at rank 3) is the same under every rule.

## 3. Rübailər refs
Refs are now assigned on the transcribed file and markup is stripped per chunk afterwards. Old "bənd 2" is still
"bənd 2" with the same text. Old "bənd 1" was only the `{{Başlıq}}` template, so it no longer exists as a citable chunk
(there is nothing to cite there). Zümrüd quşu "hissə 1" keeps its ref and loses only the word "thumbnail".
`test_legacy_refs_still_resolve_to_the_same_text` chunks every file the old way and checks all 300+ old refs.

## 4. Backward compatibility
`test_public_surface_is_unchanged_for_callers_that_pass_nothing_new` pins the signatures and defaults of
`BM25Retriever.retrieve`, `BM25Index.search` (additions are keyword-only), `evidence_for`, the hit dict keys,
and equivalence of no-argument and explicit-default calls. It also checks that `min_matched=1` is identical to a frozen copy of the
pre-gate scoring loop on all golden queries. `test_default_gate_only_ever_removes_hits` checks the gate never adds a hit.
What does change for callers that pass nothing: the default result set is stricter.

## Measured
`cd apps/voice-ai-agent && python -m app.evals.offline [--heldout] [--no-gate]`; `python -m pytest -q`: 131 passed;
`python -m app.evals.run`: 8/8. Markup-carrying chunks: 2 before (measured on the original loader), 0 after.

## Not measured
- Live router and end-to-end council answers (needs provider credits); only deterministic paths ran.
- The embeddings backend (`RAG_BACKEND=embeddings`): untouched.
- Whether the old audit citations were relevant beyond my reading of the top hit.
- Held-out sets by someone other than the author of the gate; only one held-out set of 30 cases exists.
- Cyrillic "О" in the Zümrüd quşu text ("О saat") is visible and was left alone.

## Open questions
- Is editing the two flagged corpus files approved? If yes, remove the debris at source and the loader cleaner becomes a safety net.
- Where are d01 B3/B4 and the original 0/2 cases? Needed to replace this self-authored baseline.
- Keep, narrow or remove the keyword scope gate given 0/12 held-out recall?

## Recommended next briefs
1. Router-level abstention eval with live credits, with and without the scope gate; decide the gate's fate.
2. Embeddings-based or classifier scope check, scored on a held-out set written by someone else.
3. Same coverage gate for the embeddings backend, compared with BM25 on one set.
