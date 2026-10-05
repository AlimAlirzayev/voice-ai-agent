"""Offline retrieval, citation and abstention evaluation (no network, no LLM credits).

    python -m app.evals.offline [--json] [--no-gate] [--heldout | --audit]

Scores the council's BM25 grounding against `persona_golden.json`:

* hit@k / MRR      - does the advisor's own passage rank in the top k for a question
                     about it (gold = a verbatim span of the corpus)
* faithfulness     - every returned citation is a real chunk of that advisor's corpus
                     (same text, work, ref, source) with no template or wiki markup
* abstention       - off-topic questions retrieve nothing, so no citation is claimed
* council level    - the same questions through the real LangGraph council with a stubbed
                     LLM, in two modes: a compliant router (YEKUN for off-topic questions) and
                     a worst-case router that sends every question to an advisor

`--heldout` scores `persona_golden_heldout.json` (written after the gate was frozen) and
`--audit` scores `audit_set.json`; both are report-only. `--no-gate` reproduces the behaviour
before the coverage gate (score floor only).

Exit code 1 when a gate in `GATES` / `GATES_MAX` is missed on the tuning set, so CI can run it.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

from langchain_core.messages import AIMessage, SystemMessage
from langgraph.checkpoint.memory import InMemorySaver

from app.core.config import settings
from app.graph import build_graph, run_turn
from app.prompts.divan import GREETING_PROMPT
from app.rag import bm25, retriever
from app.rag.bm25 import BM25Index, Gate, az_lower
from app.rag.ingest import collect_chunks

HERE = Path(__file__).parent
GOLDEN = HERE / "persona_golden.json"
HELDOUT = HERE / "persona_golden_heldout.json"
AUDIT = HERE / "audit_set.json"
AUDIT_VERDICTS = HERE / "audit_relevance.json"
K = bm25.TOP_K
QUOTE_LEN = 160  # app/graph/builder.py: citation["quote"] = text[:160]
GATES = {"hit_at_k": 0.85, "mrr": 0.60, "faithfulness": 1.0, "abstention": 1.0,
         "council_abstention": 1.0, "council_no_citation": 1.0,
         "council_in_scope_cited": 0.85, "council_faithfulness": 1.0}
GATES_MAX = {"markup_chunks": 0}
_MARKUP = re.compile(r"\{\{|\}\}|^\s*\|\s*\w[^\n=]*=|^\s*thumb(nail)?\s*$|<[a-z/!]|\[\[|&\w+;",
                     re.IGNORECASE | re.MULTILINE)
_LOOSE = Gate(min_matched=1)  # behaviour before the coverage gate
HOST, ADVISOR = "HOST-REPLY", "ADVISOR-ANSWER"


def _norm(text: str) -> str:
    return " ".join(az_lower(text).split())


def _search(index: BM25Index, case: dict, k: int, gate: bool, **kw) -> list[dict]:
    return index.search(case["advisor"], case["query"], k, **({} if gate else {"gate": _LOOSE}), **kw)


def _is_faithful(h: dict, real: dict) -> bool:
    src = real.get((h["advisor"], h["work"], h["ref"]))
    return (src is not None and src["text"] == h["text"] and src["source"] == h["source"]
            and not _MARKUP.search(h["text"]))


def evaluate(golden: dict, chunks: list[dict] | None = None, gate: bool = True) -> dict:
    chunks = chunks if chunks is not None else collect_chunks()
    index = BM25Index(chunks)
    real = {(c["advisor"], c["work"], c["ref"]): c for c in chunks}

    hits, rr, rows, faithful, cited = 0, 0.0, [], 0, 0
    for case in golden["retrieval"]:
        gold = _norm(case["gold"])
        assert any(gold in _norm(c["text"]) for c in chunks if c["advisor"] == case["advisor"]), \
            f"gold span not in corpus: {case['id']}"
        live = _search(index, case, K, gate)
        rank = next((i + 1 for i, h in enumerate(live) if gold in _norm(h["text"])), None)
        # MRR is measured on the unfloored ranking so it reflects ranking, not abstention.
        deep = index.search(case["advisor"], case["query"], 50, min_score=0.0, gate=_LOOSE)
        deep_rank = next((i + 1 for i, h in enumerate(deep) if gold in _norm(h["text"])), None)
        hits += rank is not None
        rr += 1 / deep_rank if deep_rank else 0.0
        rows.append({"id": case["id"], "rank": rank, "deep_rank": deep_rank})
        for h in live:
            cited += 1
            ok = _is_faithful(h, real)
            faithful += ok
            if not ok:
                rows.append({"id": case["id"], "unfaithful": f"{h['work']} {h['ref']}"})

    abstain_rows, abstained = [], 0
    for case in golden["abstain"]:
        got = _search(index, case, K, gate)
        abstained += not got
        abstain_rows.append({"id": case["id"], "cited": [f"{h['work']} {h['ref']} ({h['score']})" for h in got]})

    n = len(golden["retrieval"])
    result = {
        "hit_at_k": hits / n, "k": K, "mrr": rr / n,
        "faithfulness": faithful / cited if cited else 1.0, "citations_checked": cited,
        "abstention": abstained / len(golden["abstain"]),
        "false_abstention": sum(not _search(index, c, K, gate) for c in golden["retrieval"]) / n,
        "markup_chunks": sum(bool(_MARKUP.search(c["text"])) for c in chunks),
        "counts": {"retrieval": n, "off_topic": len(golden["abstain"])},
        "retrieval_rows": rows, "abstain_rows": abstain_rows,
    }
    result.update(evaluate_council(golden, chunks, gate))
    return result


# --------------------------------------------------------------------- council level

class _Council:
    """Stub LLM for the real graph. `route` is the advisor the router names first
    (None = YEKUN straight away). Host, advisor and router replies are fixed markers."""

    def __init__(self, route: str | None):
        self.route, self.supervisor_calls = route, 0

    async def ainvoke(self, messages):
        system = messages[0].content if messages and isinstance(messages[0], SystemMessage) else ""
        if "Yalnız bir söz ilə cavab ver" in system:  # the routing prompt
            self.supervisor_calls += 1
            return AIMessage(content=self.route.upper() if self.route and self.supervisor_calls == 1 else "YEKUN")
        if system.startswith(GREETING_PROMPT[:40]):
            return AIMessage(content=HOST)
        return AIMessage(content=ADVISOR)


async def _turn(question: str, route: str | None, tag: str):
    graph = build_graph(InMemorySaver(), llm=_Council(route))
    return await run_turn(graph, question, thread_id=f"offline-{tag}")


def evaluate_council(golden: dict, chunks: list[dict], gate: bool = True) -> dict:
    """The council path end to end with a stubbed LLM (graph, retrieval and citation
    plumbing are real). Off-topic questions run twice:

    * compliant router (YEKUN): must end in the host reply - no advisor, no citation
    * worst-case router (names an advisor anyway): must still claim no citation. The host
      reply is NOT expected here - nothing deterministic stops a misrouted advisor from
      answering - so `council_host_misrouted` is reported, never gated.

    In-scope questions are routed to their advisor and must come back cited, faithfully."""
    real = {(c["advisor"], c["work"], c["ref"]): c for c in chunks}
    saved = (settings.RAG_BACKEND, bm25.DEFAULT_GATE)
    settings.RAG_BACKEND = "bm25"
    if not gate:
        bm25.DEFAULT_GATE = _LOOSE
    retriever.get_retriever.cache_clear()

    async def run() -> dict:
        abstained = no_cite = host_mis = 0
        for case in golden["abstain"]:
            compliant = await _turn(case["query"], None, f"c-{case['id']}")
            abstained += (not compliant.consulted and not compliant.citations
                          and compliant.reply.strip() == HOST)
            mis = await _turn(case["query"], case["advisor"], f"m-{case['id']}")
            no_cite += not mis.citations
            host_mis += not mis.consulted
        cited = ok = quotes = 0
        for case in golden["retrieval"]:
            res = await _turn(case["query"], case["advisor"], f"i-{case['id']}")
            cited += bool(res.citations)
            for c in res.citations or []:
                quotes += 1
                src = next((x for k, x in real.items() if k[:3] == (c["advisor"], c["work"], c["ref"])), None)
                ok += bool(src and src["text"].startswith(c["quote"]) and src["source"] == c["source"]
                           and not _MARKUP.search(c["quote"]))
        n_off, n_in = len(golden["abstain"]), len(golden["retrieval"])
        return {"council_abstention": abstained / n_off, "council_no_citation": no_cite / n_off,
                "council_host_misrouted": host_mis / n_off, "council_in_scope_cited": cited / n_in,
                "council_faithfulness": ok / quotes if quotes else 1.0}

    try:
        return asyncio.run(run())
    finally:
        settings.RAG_BACKEND, bm25.DEFAULT_GATE = saved
        retriever.get_retriever.cache_clear()


# --------------------------------------------------------------------- audit set

def evaluate_audit(gate: bool = True) -> dict:
    """Citations over the 18 audit questions that name an advisor. There is no gold passage,
    so the numbers are coverage (any citation), junk (a citation the author judged a lexical
    accident, `audit_relevance.json`) and faithfulness - not accuracy."""
    chunks = collect_chunks()
    index = BM25Index(chunks)
    real = {(c["advisor"], c["work"], c["ref"]): c for c in chunks}
    verdict = json.loads(AUDIT_VERDICTS.read_text(encoding="utf-8"))
    audit = [c for c in json.loads(AUDIT.read_text(encoding="utf-8")) if c["expect"] in index.by_advisor]
    cited = junk = faithful = total = 0
    for c in audit:
        got = index.search(c["expect"], c["q"], K, **({} if gate else {"gate": _LOOSE}))
        cited += bool(got)
        junk += bool(got) and verdict.get(c["id"]) == "no"
        for h in got:
            total += 1
            faithful += _is_faithful(h, real)
    n = len(audit)
    return {"audit_questions": n, "audit_cited": cited, "audit_no_citation_rate": (n - cited) / n,
            "audit_junk_cited": junk, "audit_faithfulness": faithful / total if total else 1.0}


# --------------------------------------------------------------------- cli

def main(argv: list[str]) -> int:
    gate = "--no-gate" not in argv
    if "--audit" in argv:
        result = evaluate_audit(gate)
        print(json.dumps(result, ensure_ascii=False, indent=2) if "--json" in argv else
              "\n".join(f"{k:24s} {v:.3f}" if isinstance(v, float) else f"{k:24s} {v}"
                        for k, v in result.items()))
        return 0
    heldout = "--heldout" in argv
    result = evaluate(json.loads((HELDOUT if heldout else GOLDEN).read_text(encoding="utf-8")), gate=gate)
    if "--json" in argv:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for key in ("hit_at_k", "mrr", "faithfulness", "abstention", "false_abstention",
                    "council_abstention", "council_no_citation", "council_host_misrouted",
                    "council_in_scope_cited", "council_faithfulness"):
            print(f"{key:24s} {result[key]:.3f}" + (f"  (k={result['k']})" if key == "hit_at_k" else ""))
        print(f"{'markup_chunks':24s} {result['markup_chunks']}")
        print(result["counts"])
        for row in result["abstain_rows"]:
            if row["cited"]:
                print("  cited off-topic:", row["id"], row["cited"])
        for row in result["retrieval_rows"]:
            if row.get("rank") is None and "unfaithful" not in row:
                print("  not in top-k:", row["id"], "(deep rank", row["deep_rank"], ")")
    missed = [g for g, floor in GATES.items() if result[g] < floor]
    missed += [g for g, ceiling in GATES_MAX.items() if result[g] > ceiling]
    if missed and gate and not heldout:
        print("GATE MISSED:", ", ".join(missed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
