"""Offline evaluation of the council: retrieval, grounding, persona rubric, contracts.

    python -m app.evals.offline [--json out.json] [--judge]

No network, no keys. Four stages, each reported with the numbers behind it:

  retrieval   BM25 over the real corpus: does the advisor's own passage come
              back (hit@2), and does an off-topic question come back empty.
  grounding   the real graph, scripted model, real retriever: every citation in
              the reply is a verbatim passage of THAT advisor's corpus, with a
              source URL. Plus corpus hygiene (markup debris in chunks).
  rubric      language / persona / grounding scorers (`persona.py`) against
              labelled fixtures - the scorers are tested, not assumed.
  contracts   the real graph: routing resolution, HITL pause, crisis bypass.

`--judge` adds the LLM judge (needs the Claude CLI) on the good fixtures; it is
off by default and its absence is stated, never scored as zero.

Exit code 1 when a gate in `persona_golden.json` is missed. Cases marked
`known_gap` are measured and printed but never fail the run; they print XPASS
once fixed so the mark can be removed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver

from app.evals.fakes import ScriptedCouncilModel
from app.evals.persona import score_reply
from app.graph import build_graph, run_turn
from app.rag import retriever as retriever_module
from app.rag.bm25 import BM25Retriever
from app.rag.ingest import collect_chunks

GOLDEN = Path(__file__).with_name("persona_golden.json")
MARKUP = re.compile(r"\{\{|\}\}|thumbnail|<[a-z/]|\[\[|\|")
ROUTE_FOR = {"nesreddin": "NESREDDIN", "koroglu": "KOROGLU", "simurg": "SIMURG",
             "nesimi": "NESIMI", "dedeqorqud": "DEDEQORQUD", "nizami": "NIZAMI"}


def _ratio(ok: int, n: int) -> float:
    return round(ok / n, 3) if n else 1.0


def _settled(case: dict, passed: bool) -> str:
    """PASS / FAIL, or XFAIL / XPASS for a case marked known_gap."""
    if case.get("status") == "known_gap":
        return "XPASS" if passed else "XFAIL"
    return "PASS" if passed else "FAIL"


# ---------------------------------------------------------------- retrieval
def run_retrieval(cases: list[dict], chunks: list[dict]) -> dict:
    retriever = BM25Retriever(chunks)
    rows = []
    for case in cases:
        hits = retriever.index.search(case["advisor"], case["query"], 2)
        if case["kind"] == "abstain":
            passed = not hits
            rank = None
        else:
            rank = next((i + 1 for i, h in enumerate(hits) if case["expect_work"].lower() in h["work"].lower()), None)
            passed = rank is not None
        rows.append({"id": case["id"], "kind": case["kind"], "state": _settled(case, passed), "rank": rank,
                     "got": [(h["work"], h["ref"], h["score"]) for h in hits], "counted": case.get("status") != "known_gap"})

    def rate(kind: str) -> float:
        # Known gaps stay in the abstain rate (it is the measurement of the
        # gap); the gated hit rates only count cases that are expected to pass.
        counted = [r for r in rows if r["kind"] == kind and (r["counted"] or kind == "abstain")]
        return _ratio(sum(r["state"] == "PASS" for r in counted), len(counted))

    gated = [r for r in rows if r["kind"] != "abstain" and r["counted"]]
    mrr = round(sum(1 / r["rank"] for r in gated if r["rank"]) / len(gated), 3) if gated else 1.0
    return {"rows": rows, "metrics": {"lexical_hit_at_2": rate("lexical"), "natural_hit_at_2": rate("natural"),
                                      "abstain_rate": rate("abstain"), "mrr": mrr}}


# ---------------------------------------------------------------- grounding
def _verbatim(citation: dict, chunks: list[dict]) -> bool:
    quote = " ".join(citation["quote"].split())
    return any(
        c["advisor"] == citation["advisor"] and c["work"] == citation["work"] and quote in " ".join(c["text"].split())
        for c in chunks
    ) and citation.get("source", "").startswith("http")


async def run_grounding(cases: list[dict], chunks: list[dict]) -> dict:
    """Real graph + real BM25 + scripted advisor: every citation must be a
    verbatim passage of the consulted advisor's own corpus."""
    previous = retriever_module.get_retriever
    retriever_module.get_retriever = lambda: BM25Retriever(chunks)  # type: ignore[assignment]
    try:
        total = faithful = 0
        rows = []
        for case in [c for c in cases if c["kind"] != "abstain"]:
            model = ScriptedCouncilModel(route=ROUTE_FOR[case["advisor"]])
            graph = build_graph(InMemorySaver(), model)
            result = await run_turn(graph, case["query"], f"ground-{case['id']}")
            cites = result.citations or []
            ok = sum(_verbatim(c, chunks) and c["advisor"] == case["advisor"] for c in cites)
            total += len(cites)
            faithful += ok
            rows.append({"id": case["id"], "citations": len(cites), "faithful": ok})
    finally:
        retriever_module.get_retriever = previous  # type: ignore[assignment]
    markup = [c for c in chunks if MARKUP.search(c["text"])]
    return {"rows": rows,
            "metrics": {"citation_faithfulness": _ratio(faithful, total), "citations_checked": total,
                        "corpus_chunks": len(chunks), "corpus_markup_chunks": len(markup)},
            "markup": [(c["advisor"], c["work"], c["ref"]) for c in markup]}


# ---------------------------------------------------------------- rubric
def run_rubric(cases: list[dict]) -> dict:
    rows = []
    for case in cases:
        verdict = score_reply(case, case["reply"])
        passed = not verdict["fails"]
        agreed = passed == (case["expect"] == "pass")
        if agreed and "expect_fail" in case:
            agreed = any(case["expect_fail"] in f for f in verdict["fails"])
        if agreed and "expect_warn" in case:
            agreed = any(case["expect_warn"] in w for w in verdict["warns"])
        rows.append({"id": case["id"], "state": "PASS" if agreed else "FAIL", "fails": verdict["fails"],
                     "warns": verdict["warns"]})
    return {"rows": rows, "metrics": {"reply_rubric_agreement": _ratio(sum(r["state"] == "PASS" for r in rows), len(rows))}}


# ---------------------------------------------------------------- contracts
async def run_contracts(cases: list[dict]) -> dict:
    rows = []
    for case in cases:
        model = ScriptedCouncilModel(route=case["route"])
        graph = build_graph(InMemorySaver(), model)
        result = await run_turn(graph, case["message"], f"contract-{case['id']}")
        want = case["expect"]
        problems = []
        if result.status != want["status"]:
            problems.append(f"status {result.status!r} != {want['status']!r}")
        if (result.consulted or []) != want["consulted"]:
            problems.append(f"consulted {result.consulted!r} != {want['consulted']!r}")
        if "router_calls" in want and model.router_calls != want["router_calls"]:
            problems.append(f"router called {model.router_calls}x")
        rows.append({"id": case["id"], "state": "FAIL" if problems else "PASS", "problems": problems})
    return {"rows": rows, "metrics": {"contracts_pass": _ratio(sum(r["state"] == "PASS" for r in rows), len(rows))}}


# ---------------------------------------------------------------- driver
def check_gates(metrics: dict, gates: dict) -> list[str]:
    misses = []
    for name, floor in gates.items():
        if name.endswith("_max"):
            value = metrics.get(name[:-4])
            if value is not None and value > floor:
                misses.append(f"{name[:-4]} = {value} > {floor}")
        elif name in metrics and metrics[name] < floor:
            misses.append(f"{name} = {metrics[name]} < {floor}")
    return misses


async def evaluate(golden: dict, judge_fn=None) -> dict:
    chunks = collect_chunks()
    retrieval = run_retrieval(golden["retrieval"], chunks)
    grounding = await run_grounding(golden["retrieval"], chunks)
    rubric = run_rubric(golden["replies"])
    contracts = await run_contracts(golden["contracts"])
    metrics = {**retrieval["metrics"], **grounding["metrics"], **rubric["metrics"], **contracts["metrics"]}
    report = {"metrics": metrics, "retrieval": retrieval["rows"], "grounding": grounding["rows"],
              "markup_chunks": grounding["markup"], "rubric": rubric["rows"], "contracts": contracts["rows"],
              "judge": None}
    if judge_fn is not None:
        from app.evals.judge import run_judge

        good = [c for c in golden["replies"] if c["expect"] == "pass"]
        report["judge"] = run_judge(good, judge_fn, floors={"dil": 3.5, "xarakter": 3.5})
    report["gate_misses"] = check_gates(metrics, golden["gates"])
    return report


def print_report(report: dict) -> None:
    for section in ("retrieval", "rubric", "contracts"):
        print(f"\n[{section}]")
        for row in report[section]:
            extra = row.get("problems") or row.get("fails") if row["state"] == "FAIL" else ""
            if section == "retrieval":
                extra = f"rank={row['rank']}" if row["kind"] != "abstain" else f"got={len(row['got'])} passage(s)"
            print(f"  {row['state']:5} {row['id']}  {extra or ''}")
    print("\n[grounding]")
    for name, value in report["metrics"].items():
        if name.startswith(("citation", "corpus")):
            print(f"  {name} = {value}")
    for advisor, work, ref in report["markup_chunks"]:
        print(f"  markup debris: {advisor} / {work} / {ref}")
    print("\n[judge]", "not run (pass --judge; needs the Claude CLI)" if report["judge"] is None else report["judge"])
    print("\n[metrics]")
    for name, value in report["metrics"].items():
        print(f"  {name} = {value}")
    print("\n" + ("GATES OK" if not report["gate_misses"] else "GATES MISSED: " + "; ".join(report["gate_misses"])))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--json", default="", help="write the full report here")
    parser.add_argument("--judge", action="store_true", help="add the LLM judge (Claude CLI)")
    args = parser.parse_args(argv)
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    judge_fn = None
    if args.judge:
        from app.core.config import settings
        from app.evals.audit import judge as live_judge

        judge_fn = lambda q, r, c: live_judge(q, r, c, settings.CLAUDE_MODEL)
    report = asyncio.run(evaluate(golden, judge_fn))
    print_report(report)
    if args.json:
        Path(args.json).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return 1 if report["gate_misses"] else 0


if __name__ == "__main__":
    sys.exit(main())
