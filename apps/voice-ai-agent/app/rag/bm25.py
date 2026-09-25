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

K1 = 1.5
B = 0.75
PREFIX = 5          # suffix-tolerant stem length for an agglutinative language
MIN_SCORE = 1.0     # below this the advisor answers uncited
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

    def search(self, advisor: str, query: str, k: int = TOP_K) -> list[dict]:
        docs = self.by_advisor.get(advisor)
        if not docs:
            return []
        stats = self.stats[advisor]
        q_stems = set(stems(query))
        if not q_stems:
            return []
        scored: list[tuple[float, dict]] = []
        for doc in docs:
            score = 0.0
            for stem in q_stems:
                tf = doc["_stems"].get(stem, 0)
                if not tf:
                    continue
                df = stats["df"].get(stem, 0)
                idf = math.log(1 + (stats["n"] - df + 0.5) / (df + 0.5))
                norm = 1 - B + B * doc["_len"] / stats["avg_len"]
                score += idf * (tf * (K1 + 1)) / (tf + K1 * norm)
            if score > 0:
                scored.append((score, doc))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [
            {"advisor": doc["advisor"], "work": doc.get("work", ""), "ref": doc.get("ref", ""),
             "source": doc.get("source", ""), "text": doc["text"], "score": round(score, 3),
             "retrieval": "bm25"}
            for score, doc in scored[:k]
            if score >= MIN_SCORE
        ]


class BM25Retriever:
    """Same async surface as `retriever.Retriever`, so `evidence_for` needs no branch."""

    model = "bm25"

    def __init__(self, chunks: list[dict]):
        self.index = BM25Index(chunks)

    async def retrieve(self, advisor: str, query: str, k: int = TOP_K) -> list[dict]:
        return self.index.search(advisor, query, k)
