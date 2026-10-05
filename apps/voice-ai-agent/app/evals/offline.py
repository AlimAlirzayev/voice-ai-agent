"""Offline retrieval, citation and abstention evaluation (no network, no LLM).

    python -m app.evals.offline [--json] [--no-gate] [--heldout]

Scores the council's BM25 grounding against `persona_golden.json`:

* hit@k / MRR      - does the advisor's own passage rank in the top k for a
                     question about it (gold = a verbatim span of the corpus)
* faithfulness     - every returned citation is a real chunk of that advisor's
                     corpus (same text, work, ref, source), the 160-character
                     quote the graph shows is a prefix of it, and no template
                     or wiki markup rides along
* abstention       - off-topic questions retrieve nothing, so no citation is
                     claimed; and the council-level scope gate sends them to the
                     host while borderline in-scope questions still reach it

Exit code 1 when a gate in `GATES` is missed, so CI can run it as a step.
`--heldout` scores `persona_golden_heldout.json` instead: cases written after the
thresholds and scope patterns were frozen, so they were never used to pick them.
That run is report-only (no gate), to keep it from becoming a second tuning set.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from app.graph.guardrails import is_out_of_scope
from app.rag import bm25
from app.rag.bm25 import BM25Index, az_lower
from app.rag.ingest import collect_chunks

GOLDEN = Path(__file__).with_name("persona_golden.json")
HELDOUT = Path(__file__).with_name("persona_golden_heldout.json")
K = bm25.TOP_K
QUOTE_LEN = 160  # app/graph/builder.py: citation["quote"] = text[:160]
GATES_MAX = {"markup_chunks": 0}
GATES = {"hit_at_k": 0.85, "mrr": 0.60, "faithfulness": 1.0, "abstention": 1.0,
         "scope_abstention": 1.0, "borderline_pass": 1.0}
_MARKUP = re.compile(r"\{\{|\}\}|^\s*\|\s*\w[^\n=]*=|^\s*thumb(nail)?\s*$|<[a-z/!]|\[\[|&\w+;",
                     re.IGNORECASE | re.MULTILINE)


def _norm(text: str) -> str:
    return " ".join(az_lower(text).split())


def evaluate(golden: dict, chunks: list[dict] | None = None, gate: bool = True) -> dict:
    chunks = chunks if chunks is not None else collect_chunks()
    index = BM25Index(chunks)
    real = {(c["advisor"], c["work"], c["ref"]): c for c in chunks}

    # Retrieval depth is measured without the abstention floor on purpose, so
    # MRR reflects ranking quality; hit@k and faithfulness use the live gate.
    hits, rr, rows = 0, 0.0, []
    faithful, cited = 0, 0
    for case in golden["retrieval"]:
        gold = _norm(case["gold"])
        assert any(gold in _norm(c["text"]) for c in chunks if c["advisor"] == case["advisor"]), \
            f"gold span not in corpus: {case['id']}"
        live = index.search(case["advisor"], case["query"], K) if gate else _ungated(index, case, K)
        rank = next((i + 1 for i, h in enumerate(live) if gold in _norm(h["text"])), None)
        deep = _unfloored(index, case, 50)
        deep_rank = next((i + 1 for i, h in enumerate(deep) if gold in _norm(h["text"])), None)
        hits += rank is not None
        rr += 1 / deep_rank if deep_rank else 0.0
        rows.append({"id": case["id"], "rank": rank, "deep_rank": deep_rank})
        for h in live:
            cited += 1
            src = real.get((h["advisor"], h["work"], h["ref"]))
            ok = (src is not None and src["text"] == h["text"] and src["source"] == h["source"]
                  and h["text"].startswith(h["text"][:QUOTE_LEN]) and not _MARKUP.search(h["text"]))
            faithful += ok
            if not ok:
                rows.append({"id": case["id"], "unfaithful": f"{h['work']} {h['ref']}"})

    abstain_rows, abstained = [], 0
    for case in golden["abstain"]:
        got = index.search(case["advisor"], case["query"], K) if gate else _ungated(index, case, K)
        abstained += not got
        abstain_rows.append({"id": case["id"], "cited": [f"{h['work']} {h['ref']} ({h['score']})" for h in got]})

    scope_total = scope_ok = border_total = border_ok = 0
    scope_fail = []
    for case in golden["council_scope"]:
        flagged = is_out_of_scope(case["query"]) if gate else False
        if case["out_of_scope"]:
            scope_total += 1
            scope_ok += flagged
        else:
            border_total += 1
            border_ok += not flagged
        if flagged != case["out_of_scope"]:
            scope_fail.append(case["id"])

    n = len(golden["retrieval"])
    return {
        "hit_at_k": hits / n, "k": K, "mrr": rr / n,
        "faithfulness": faithful / cited if cited else 1.0, "citations_checked": cited,
        "abstention": abstained / len(golden["abstain"]),
        "markup_chunks": sum(bool(_MARKUP.search(c["text"])) for c in chunks),
        "scope_abstention": scope_ok / scope_total, "borderline_pass": border_ok / border_total,
        "counts": {"retrieval": n, "abstain": len(golden["abstain"]),
                   "scope_off_topic": scope_total, "borderline": border_total},
        "retrieval_rows": rows, "abstain_rows": abstain_rows, "scope_fail": scope_fail,
    }


def _ungated(index: BM25Index, case: dict, k: int) -> list[dict]:
    """The behaviour before the coverage gate: the score floor alone."""
    return index.search(case["advisor"], case["query"], k, min_matched=1)


def _unfloored(index: BM25Index, case: dict, k: int) -> list[dict]:
    """Ranking only, no abstention at all - the basis of MRR."""
    return index.search(case["advisor"], case["query"], k, min_matched=1, min_score=0.0)


def main(argv: list[str]) -> int:
    heldout = "--heldout" in argv
    golden = json.loads((HELDOUT if heldout else GOLDEN).read_text(encoding="utf-8"))
    result = evaluate(golden, gate="--no-gate" not in argv)
    if "--json" in argv:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for key in ("hit_at_k", "mrr", "faithfulness", "abstention", "scope_abstention", "borderline_pass"):
            print(f"{key:18s} {result[key]:.3f}" + (f"  (k={result['k']})" if key == "hit_at_k" else ""))
        print(f"{'markup_chunks':18s} {result['markup_chunks']}")
        print(result["counts"])
        for row in result["abstain_rows"]:
            if row["cited"]:
                print("  cited off-topic:", row["id"], row["cited"])
        for rid in result["scope_fail"]:
            print("  scope miss:", rid)
        for row in result["retrieval_rows"]:
            if row.get("rank") is None and "unfaithful" not in row:
                print("  not in top-k:", row["id"], "(deep rank", row["deep_rank"], ")")
    missed = [g for g, floor in GATES.items() if result[g] < floor]
    missed += [g for g, ceiling in GATES_MAX.items() if result[g] > ceiling]
    if missed and "--no-gate" not in argv and not heldout:
        print("GATE MISSED:", ", ".join(missed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
