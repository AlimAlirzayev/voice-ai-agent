# d01-divan-reinforcement-d04-divan-eval-calibration

## Built
- `apps/voice-ai-agent/app/evals/calibration.py`: `pack` builds a blind labelling CSV (no judge output) plus a separate `key.json` with the judge's scores; `score` reports per rubric dimension (xarakter, mentalitet, dil, bedii, fayda): exact %, within-one %, Cohen's kappa, quadratic-weighted kappa, pass/fail kappa (score >= 4), and mean bias (judge minus human).
- `apps/voice-ai-agent/tests/test_calibration.py`: 11 tests on synthetic labels (perfect agreement, textbook kappa 0.4, weighted kappa ordering, undefined kappa, lenient-judge bias, blank cells, range validation, blind/deduplicated pack, seeded order, end-to-end CLI).
- `apps/voice-ai-agent/docs/calibration/INSTRUCTIONS.md`: rater sheet in Azerbaijani and English, plus organiser notes.
- `apps/voice-ai-agent/docs/calibration/pack/`: 20 items from the existing `output/audit-v5.json` (all 20 carry judge scores), shuffled with a fixed seed.

## Measured
- `cd apps/voice-ai-agent && uv run --extra dev pytest -q`: 131 passed (120 existing + 11 new).
- `uv run ruff check app/evals/calibration.py tests/test_calibration.py`: clean. Repo-wide ruff reports 24 errors that exist without these changes (not touched).
- `python -m app.evals.calibration pack ...` ran; `score` on the empty pack prints n/a for every dimension, as intended.

## Not measured
- No judge-vs-human agreement: no human labels exist yet (rater: native speaker, to be arranged by the owner).
- `--judge` stage not run; cost not recorded. The Claude CLI is present, but quota was not checked and no new judging was needed (v5 scores are reused).
- Judge scores in the pack come from a single run per item; judge run-to-run variance is unknown.

## Open questions
- `docs/reinforcement/d01-backlog.md` (items B8, B9) is not in this repo; scope was taken from the brief text. Please supply it if B8/B9 ask for more.
- Branch: the session was bound to `claude/divan-eval-calibration-tqafxe`, not `cloudlab/<BRIEF ID>`; work was pushed to the former.
- 20 items is small; kappa will be wide. Is a second rater or a larger pack (v1-v5 give about 85 distinct replies) wanted?
- Pass threshold (>= 4) is an assumption; confirm with the owner.

## Next briefs
1. Run the labelling session, then `score`; set a go/no-go agreement threshold per dimension.
2. Re-run the judge 3x on the same pack to measure its own repeatability (needs CLI quota; record cost).
3. If kappa is weak on a dimension, revise that rubric line in `JUDGE_SYSTEM` and re-score on a fresh pack.
