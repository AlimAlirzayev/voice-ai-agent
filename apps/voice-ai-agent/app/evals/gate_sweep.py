"""Sweep citation-gate settings and print one comparison table.

    python -m app.evals.gate_sweep

Columns (all deterministic, no network):
  audit cited      audit_set.json questions (18 name an advisor) that get any citation
  weak+ kept       of the 4 questions whose old top hit the author judged weak (none are `yes`),
                   how many still get that same passage (audit_relevance.json)
  junk cited       questions judged `no` that still get a citation (lexical accidents)
  hit@2 tune/held  in-scope questions with a known passage, passage in top 2 (21 / 8 cases)
  off-topic        off-topic questions that retrieve nothing (tuning 10 / held-out 12)
  false abst       in-scope questions (tuning + held-out, 29) that retrieve nothing at all
"""

from __future__ import annotations

import json
from pathlib import Path

from app.evals.offline import GOLDEN, HELDOUT, _norm
from app.rag.bm25 import BM25Index, Gate
from app.rag.ingest import collect_chunks

HERE = Path(__file__).parent
SETTINGS: list[tuple[str, Gate | None]] = [
    ("old: score floor only", Gate(min_matched=1)),
    ("matched>=2", Gate(min_matched=2)),
    ("matched>=3 (shipped)", Gate()),
    ("idf-sum>=4 (m>=2)", Gate(min_matched=2, min_idf_sum=4)),
    ("idf-sum>=6 (m>=2)", Gate(min_matched=2, min_idf_sum=6)),
    ("idf-sum>=8 (m>=2)", Gate(min_matched=2, min_idf_sum=8)),
    ("idf-sum>=10 (m>=2)", Gate(min_matched=2, min_idf_sum=10)),
    ("best-idf>=3.5 (m>=1)", Gate(min_matched=1, min_best_idf=3.5)),
    ("best-idf>=4.5 (m>=2)", Gate(min_matched=2, min_best_idf=4.5)),
    ("no-generic m>=2", Gate(min_matched=2, drop_generic=True)),
    ("no-generic m>=3", Gate(min_matched=3, drop_generic=True)),
    ("no-generic m>=2 idf-sum>=6", Gate(min_matched=2, min_idf_sum=6, drop_generic=True)),
    ("no-generic m>=2 idf-sum>=8", Gate(min_matched=2, min_idf_sum=8, drop_generic=True)),
    ("no-generic m>=2 cov>=0.35", Gate(min_matched=2, min_coverage=0.35, drop_generic=True)),
    ("no-generic m>=2 cov>=0.5", Gate(min_matched=2, min_coverage=0.5, drop_generic=True)),
]


def _hit(index, case, gate):
    gold = _norm(case["gold"])
    return any(gold in _norm(h["text"]) for h in index.search(case["advisor"], case["query"], 2, gate=gate))


def run(settings=SETTINGS, golden_files=(GOLDEN, HELDOUT)) -> list[dict]:
    chunks = collect_chunks()
    index = BM25Index(chunks)
    tune, held = (json.loads(f.read_text(encoding="utf-8")) for f in golden_files)
    audit = [c for c in json.loads((HERE / "audit_set.json").read_text(encoding="utf-8"))
             if c["expect"] in index.by_advisor]
    verdict = json.loads((HERE / "audit_relevance.json").read_text(encoding="utf-8"))
    old_top = {c["id"]: index.search(c["expect"], c["q"], 1, gate=Gate(min_matched=1)) for c in audit}
    rows = []
    for name, gate in settings:
        cited = weak_kept = junk = 0
        for c in audit:
            hits = index.search(c["expect"], c["q"], 2, gate=gate)
            cited += bool(hits)
            v = verdict.get(c["id"], "none")
            if v in ("weak", "yes") and hits and old_top[c["id"]] and hits[0]["ref"] == old_top[c["id"]][0]["ref"] \
                    and hits[0]["work"] == old_top[c["id"]][0]["work"]:
                weak_kept += 1
            junk += v == "no" and bool(hits)
        in_scope = tune["retrieval"] + held["retrieval"]
        silent = sum(not index.search(x["advisor"], x["query"], 2, gate=gate) for x in in_scope)
        rows.append({
            "setting": name, "audit_cited": cited, "audit_n": len(audit), "weak_kept": weak_kept,
            "junk": junk,
            "hit_tune": sum(_hit(index, x, gate) for x in tune["retrieval"]), "n_tune": len(tune["retrieval"]),
            "hit_held": sum(_hit(index, x, gate) for x in held["retrieval"]), "n_held": len(held["retrieval"]),
            "off_tune": sum(not index.search(x["advisor"], x["query"], 2, gate=gate) for x in tune["abstain"]),
            "off_held": sum(not index.search(x["advisor"], x["query"], 2, gate=gate) for x in held["abstain"]),
            "n_off_tune": len(tune["abstain"]), "n_off_held": len(held["abstain"]),
            "false_abst": silent, "n_in_scope": len(in_scope),
        })
    return rows


def render(rows: list[dict]) -> str:
    head = (f"{'setting':32s} {'audit cited':>11s} {'weak+ kept':>10s} {'junk':>5s} "
            f"{'hit@2 tune':>10s} {'hit@2 held':>10s} {'off tune':>8s} {'off held':>8s} {'false abst':>10s}")
    lines = [head, "-" * len(head)]
    for r in rows:
        lines.append(
            f"{r['setting']:32s} {r['audit_cited']:>8d}/{r['audit_n']:<2d} {r['weak_kept']:>8d}/4 {r['junk']:>5d} "
            f"{r['hit_tune']:>7d}/{r['n_tune']:<2d} {r['hit_held']:>7d}/{r['n_held']:<2d} "
            f"{r['off_tune']:>5d}/{r['n_off_tune']:<2d} {r['off_held']:>5d}/{r['n_off_held']:<2d} "
            f"{r['false_abst']:>7d}/{r['n_in_scope']}")
    return "\n".join(lines)


if __name__ == "__main__":
    print(render(run()))
