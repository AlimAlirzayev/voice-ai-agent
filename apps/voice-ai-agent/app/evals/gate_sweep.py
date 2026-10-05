"""Sweep citation-gate settings and print one comparison table.

    python -m app.evals.gate_sweep

Deterministic, no network. Columns:
  main hit/abstain  persona_golden.json retrieval cases that must return the right work in the
                    top 2 (25 counted) / abstain cases that must return nothing (2 original)
  gold hit          grounding_cases.json in-scope questions whose gold passage is in the top 2 (29)
  off-topic         grounding_cases.json off-topic questions that retrieve nothing (22)
  audit cited/junk  audit_set.json questions (18 name an advisor) with any citation / with a
                    citation the author judged a lexical accident (audit_relevance.json)
"""

from __future__ import annotations

import json
from pathlib import Path

from app.rag.bm25 import DEFAULT_GATE, STRONG_SCORE, BM25Index, Gate, az_lower
from app.rag.ingest import collect_chunks

HERE = Path(__file__).parent
SETTINGS: list[tuple[str, Gate]] = [
    ("old: score floor 1.0 only", Gate(min_matched=1)),
    ("matched>=2", Gate(min_matched=2)),
    ("matched>=3", Gate()),
    ("matched>=3 no-generic", Gate(drop_generic=True)),
    ("matched>=3 | strong>=4.5", Gate(strong_score=4.5)),
    ("matched>=3 | strong>=5.0", Gate(strong_score=5.0)),
    (f"matched>=3 | strong>={STRONG_SCORE}", Gate(strong_score=STRONG_SCORE)),
    ("matched>=3 | strong>=6.0", Gate(strong_score=6.0)),
    ("matched>=3 | strong>=7.0", Gate(strong_score=7.0)),
    ("strong>=5.5 only (m>=1)", Gate(min_matched=1, strong_score=0.0)),  # needs min_score below
    ("no-generic m>=2 | strong>=5.5", Gate(min_matched=2, strong_score=5.5, drop_generic=True)),
    ("idf-sum>=4 (m>=2)", Gate(min_matched=2, min_idf_sum=4)),
    (f"no-generic m>=3 | strong>={STRONG_SCORE} (shipped)", DEFAULT_GATE),
]


def _norm(text: str) -> str:
    return " ".join(az_lower(text).split())


def run(settings=SETTINGS) -> list[dict]:
    index = BM25Index(collect_chunks())
    main = json.loads((HERE / "persona_golden.json").read_text(encoding="utf-8"))["retrieval"]
    main_hit = [c for c in main if c["kind"] != "abstain" and c.get("status") != "known_gap"]
    main_off = [c for c in main if c["kind"] == "abstain"]
    sets = json.loads((HERE / "grounding_cases.json").read_text(encoding="utf-8"))
    gold = sets["tuning"]["retrieval"] + sets["heldout"]["retrieval"]
    off = sets["tuning"]["abstain"] + sets["heldout"]["abstain"]
    verdict = json.loads((HERE / "audit_relevance.json").read_text(encoding="utf-8"))
    audit = [c for c in json.loads((HERE / "audit_set.json").read_text(encoding="utf-8"))
             if c["expect"] in index.by_advisor]
    rows = []
    for name, gate in settings:
        floor = 1.0 if "only (m>=1)" not in name else 5.5

        def got(case, q="query", adv="advisor", gate=gate, floor=floor):
            return index.search(case[adv], case[q], 2, gate=gate, min_score=floor)

        cited = [bool(index.search(c["expect"], c["q"], 2, gate=gate, min_score=floor)) for c in audit]
        rows.append({
            "setting": name,
            "main_hit": sum(any(c["expect_work"].lower() in h["work"].lower() for h in got(c)) for c in main_hit),
            "n_main_hit": len(main_hit),
            "main_off": sum(not got(c) for c in main_off), "n_main_off": len(main_off),
            "gold_hit": sum(any(_norm(c["gold"]) in _norm(h["text"]) for h in got(c)) for c in gold),
            "n_gold": len(gold),
            "off": sum(not got(c) for c in off), "n_off": len(off),
            "audit_cited": sum(cited), "n_audit": len(audit),
            "audit_junk": sum(ok and verdict.get(c["id"]) == "no" for ok, c in zip(cited, audit)),
        })
    return rows


def render(rows: list[dict]) -> str:
    head = (f"{'setting':38s} {'main hit':>8s} {'main abst':>9s} {'gold hit':>8s} {'off-topic':>9s} "
            f"{'audit cited':>11s} {'junk':>5s}")
    lines = [head, "-" * len(head)]
    for r in rows:
        lines.append(f"{r['setting']:38s} {r['main_hit']:>5d}/{r['n_main_hit']:<2d} {r['main_off']:>6d}/{r['n_main_off']:<2d} "
                     f"{r['gold_hit']:>5d}/{r['n_gold']:<2d} {r['off']:>6d}/{r['n_off']:<2d} "
                     f"{r['audit_cited']:>8d}/{r['n_audit']:<2d} {r['audit_junk']:>5d}")
    return "\n".join(lines)


if __name__ == "__main__":
    print(render(run()))
