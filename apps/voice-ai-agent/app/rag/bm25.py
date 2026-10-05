"""BM25 retrieval over each advisor's own corpus - no embeddings, no network.

Why: the embedding index needs an OpenAI key at query time, and the council
must keep quoting its sources when that key is absent. BM25 in pure Python
over the same `ingest.collect_chunks()` output is deterministic (same question,
same passage), free, and honest about its strength: every hit is labelled
`retrieval: "bm25"` so a weaker match is never read as a stronger one.

Ported from apps/divan-crew/corpus.py (lesson #41), which measured the
parameters below on the Vikimənbə corpus; the crew keeps its own copy for now.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

K1 = 1.5
B = 0.75
PREFIX = 5          # suffix-tolerant stem length for an agglutinative language
MIN_SCORE = 1.0     # below this the advisor answers uncited
# A passage is only cited with real evidence, and there are two ways to have it:
#   * breadth - it shares MIN_MATCHED distinct stems with the question (a
#     two-stem question needs both, never fewer than two), or
#   * strength - its BM25 score reaches STRONG_SCORE (a rare word, repeated).
# Measured on the offline sets (python -m app.evals.gate_sweep): off-topic
# questions match one or two common words ("qiymət", "hava", "oyun") and score
# below ~5; genuine short or paraphrased questions either share several stems or
# hit a rare one above 5.5. Neither signal alone separates them: breadth alone
# lost 5 of the 25 existing retrieval cases, strength alone cited more
# off-topic questions.
MIN_MATCHED = 3
MIN_MATCHED_FLOOR = 2
STRONG_SCORE = 5.5
TOP_K = 2

_UPPER_MAP = str.maketrans({"İ": "i", "I": "ı"})
_APOSTROPHES = str.maketrans({c: "" for c in "'’ʼ´`"})
_WORD_RE = re.compile(r"[a-zəğışçöüA-ZƏĞIİŞÇÖÜ]+")


def az_lower(text: str) -> str:
    """Lowercase Azerbaijani correctly: İ→i and I→ı before the generic fold."""
    return text.translate(_UPPER_MAP).lower()


def tokens(text: str) -> list[str]:
    return [az_lower(w) for w in _WORD_RE.findall(text.translate(_APOSTROPHES))]


def stems(text: str) -> list[str]:
    return [t[:PREFIX] for t in tokens(text) if len(t) >= 3]


# Pronouns, conjunctions, quantifiers and light verbs that carry no topic. They
# are rare in this small literary corpus, so document frequency cannot find them
# ("mənim" appears in 2 chunks, "istəy" in 1) - but a question matching a passage
# only through them is matching by accident. Listed as words, stored as stems.
_GENERIC_WORDS = (
    "mən məni mənim sən səni sənin biz bizi siz onu onun bunu buna bunun nə necə niyə kim kimi "
    "hər heç çox daha amma ancaq lakin isə var yox bir iki üçün ilə və ola olur olan olub edir "
    "edib edən deyir deyən dedi istəyirəm istəmirəm istəyir istər lazım gəlir çıxar çıxıb çıxır "
    "qabağ vaxt"
)
GENERIC_STEMS = frozenset(w[:PREFIX] for w in _GENERIC_WORDS.split() if len(w) >= 3)


@dataclass(frozen=True)
class Gate:
    """When is a retrieved passage good enough to cite? Every field is a floor;
    zero disables it, except that `strong_score` is an alternative to the others
    rather than an addition. `min_matched` keeps the two-stem rule: a question with
    fewer stems than `min_matched` needs all of them, never fewer than `floor`.
    With `drop_generic`, GENERIC_STEMS count for nothing in the other measures."""
    min_matched: int = 3
    strong_score: float = 0.0    # a passage scoring at least this passes on strength alone
    floor: int = 2
    min_idf_sum: float = 0.0     # IDF-weighted overlap of the matched stems
    min_best_idf: float = 0.0    # the rarest matched stem
    min_coverage: float = 0.0    # share of the question's IDF mass the passage explains
    drop_generic: bool = False

    def passes(self, matched: list[float], total_idf: float, n_query_stems: int,
               score: float = 0.0) -> bool:
        if self.strong_score and score >= self.strong_score:
            return True
        required = max(1, self.min_matched) if self.min_matched < self.floor else max(
            self.floor, min(self.min_matched, n_query_stems))
        if len(matched) < required:
            return False
        if self.min_idf_sum and sum(matched) < self.min_idf_sum:
            return False
        if self.min_best_idf and max(matched, default=0.0) < self.min_best_idf:
            return False
        return not (self.min_coverage and total_idf and sum(matched) / total_idf < self.min_coverage)


class BM25Index:
    """BM25 partitioned by advisor: a member only ever searches its own texts."""

    def __init__(self, chunks: list[dict]):
        self.by_advisor: dict[str, list[dict]] = {}
        for chunk in chunks:
            prepared = dict(chunk)
            prepared["_stems"] = Counter(stems(chunk["text"]))
            prepared["_len"] = sum(prepared["_stems"].values())
            self.by_advisor.setdefault(chunk["advisor"], []).append(prepared)
        self.stats: dict[str, dict] = {}
        for advisor, docs in self.by_advisor.items():
            lengths = [d["_len"] for d in docs] or [1]
            df: Counter = Counter()
            for doc in docs:
                df.update(doc["_stems"].keys())
            self.stats[advisor] = {"avg_len": sum(lengths) / len(lengths), "df": df, "n": len(docs)}

    def counts(self) -> dict[str, int]:
        return {advisor: len(docs) for advisor, docs in self.by_advisor.items()}

    def search(self, advisor: str, query: str, k: int = TOP_K, *,
               min_score: float = MIN_SCORE, min_matched: int = MIN_MATCHED,
               gate: Gate | None = None) -> list[dict]:
        gate = gate if gate is not None else DEFAULT_GATE if min_matched == MIN_MATCHED else Gate(
            min_matched=min_matched)
        docs = self.by_advisor.get(advisor)
        if not docs:
            return []
        stats = self.stats[advisor]
        q_stems = set(stems(query))
        if not q_stems:
            return []
        idfs = {st: math.log(1 + (stats["n"] - stats["df"].get(st, 0) + 0.5)
                             / (stats["df"].get(st, 0) + 0.5)) for st in q_stems}
        counted = {st for st in q_stems if not (gate.drop_generic and st in GENERIC_STEMS)}
        total_idf = sum(idfs[st] for st in counted)
        scored: list[tuple[float, dict]] = []
        for doc in docs:
            score = 0.0
            matched: list[float] = []
            for stem in q_stems:
                tf = doc["_stems"].get(stem, 0)
                if not tf:
                    continue
                if stem in counted:
                    matched.append(idfs[stem])
                norm = 1 - B + B * doc["_len"] / stats["avg_len"]
                score += idfs[stem] * (tf * (K1 + 1)) / (tf + K1 * norm)
            if score > 0 and gate.passes(matched, total_idf, len(counted), score):
                scored.append((score, doc))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [
            {"advisor": doc["advisor"], "work": doc.get("work", ""), "ref": doc.get("ref", ""),
             "source": doc.get("source", ""), "text": doc["text"], "score": round(score, 3),
             "retrieval": "bm25"}
            for score, doc in scored[:k]
            if score >= min_score
        ]


DEFAULT_GATE = Gate(strong_score=STRONG_SCORE, drop_generic=True)


class BM25Retriever:
    """Same async surface as `retriever.Retriever`, so `evidence_for` needs no branch."""

    model = "bm25"

    def __init__(self, chunks: list[dict]):
        self.index = BM25Index(chunks)

    async def retrieve(self, advisor: str, query: str, k: int = TOP_K) -> list[dict]:
        return self.index.search(advisor, query, k)
