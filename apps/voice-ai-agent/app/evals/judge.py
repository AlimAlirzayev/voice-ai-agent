"""LLM-as-judge plumbing: parse a rubric verdict, aggregate, gate.

The judge itself is injected (`judge_fn(question, reply, consulted) -> dict`),
so this module is testable with no model. The live judge is
`app.evals.audit.judge` (a strict-philologist prompt over the Claude CLI);
`python -m app.evals.offline --judge` wires it in. Without a judge the offline
harness skips this stage and says so - it never invents a score.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from statistics import mean

DIMENSIONS = ("xarakter", "mentalitet", "dil", "bedii", "fayda")
JudgeFn = Callable[[str, str, list[str]], dict]


def parse_verdict(text: str) -> dict:
    """The first JSON object in the judge's text, validated: every dimension a
    number in 1..5. Anything else is `{"error": ...}` (never a guessed score)."""
    match = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not match:
        return {"error": "no JSON in judge output"}
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        return {"error": f"invalid JSON: {exc.msg}"}
    scores = {}
    for dim in DIMENSIONS:
        value = data.get(dim)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 1 <= value <= 5:
            return {"error": f"dimension {dim!r} missing or outside 1..5"}
        scores[dim] = float(value)
    return {**scores, "qusurlar": list(data.get("qusurlar") or []), "bir_cumle": str(data.get("bir_cumle", ""))}


def summarise(verdicts: list[dict], floors: dict[str, float] | None = None) -> dict:
    """Mean per dimension over the valid verdicts, plus which floors it breaks."""
    valid = [v for v in verdicts if "error" not in v]
    means = {d: round(mean(v[d] for v in valid), 2) for d in DIMENSIONS} if valid else {}
    breaches = {d: (means[d], floor) for d, floor in (floors or {}).items() if d in means and means[d] < floor}
    return {"judged": len(valid), "errors": len(verdicts) - len(valid), "means": means, "breaches": breaches}


def run_judge(cases: list[dict], judge_fn: JudgeFn, floors: dict[str, float] | None = None) -> dict:
    verdicts = []
    for case in cases:
        raw = judge_fn(case["question"], case["reply"], [case["advisor"]])
        verdicts.append(raw if "error" in raw else parse_verdict(json.dumps(raw)))
    return summarise(verdicts, floors)
