"""Per-member corpus search — deterministic BM25, no embeddings, no API cost.

Why not the app's own retriever: `app/rag/retriever.py` embeds the query with
OpenAI on every call. The operator's instruction for this build is that the
test run costs nothing beyond the Claude subscription, so this tool scores
locally instead. The trade is stated plainly wherever a citation is produced:
BM25 matches WORDS, the embedding retriever matches MEANING. A question
phrased with none of the corpus's own vocabulary will find less here than it
would there. An uncited answer is honest; a citation from a weaker retrieval
presented as the stronger one is not.

Chunking is NOT reimplemented — `app.rag.ingest.collect_chunks()` is imported
and reused, so this tool reads exactly the passages the production index
reads, with the same provenance (work, ref, source) behind every citation.

Azerbaijani-specific: the language glues suffixes onto stems («vətən»,
«vətənim», «vətənimdən»), so exact token equality misses obvious matches.
Terms are therefore compared on a stem prefix, which is crude but honest and
costs nothing.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache

from az_text import tokens

PREFIX = 5          # suffix-tolerant stem length
K1 = 1.5            # BM25 term-frequency saturation
B = 0.75            # BM25 length normalisation
MIN_SCORE = 1.0     # below this, the member answers uncited
TOP_K = 2


def _stems(text: str) -> list[str]:
    return [t[:PREFIX] for t in tokens(text) if len(t) >= 3]


@dataclass(frozen=True)
class Passage:
    advisor: str
    work: str
    ref: str
    source: str
    text: str
    score: float


class CorpusIndex:
    """BM25 over the corpus chunks, partitioned by advisor."""

    def __init__(self, chunks: list[dict]):
        self.by_advisor: dict[str, list[dict]] = {}
        for chunk in chunks:
            prepared = dict(chunk)
            prepared["_stems"] = Counter(_stems(chunk["text"]))
            prepared["_len"] = sum(prepared["_stems"].values())
            self.by_advisor.setdefault(chunk["advisor"], []).append(prepared)

        self.stats: dict[str, dict] = {}
        for advisor, docs in self.by_advisor.items():
            lengths = [d["_len"] for d in docs] or [1]
            df: Counter = Counter()
            for doc in docs:
                df.update(doc["_stems"].keys())
            self.stats[advisor] = {
                "avg_len": sum(lengths) / len(lengths),
                "df": df,
                "n": len(docs),
            }

    def counts(self) -> dict[str, int]:
        return {advisor: len(docs) for advisor, docs in self.by_advisor.items()}

    def search(self, advisor: str, query: str, k: int = TOP_K) -> list[Passage]:
        docs = self.by_advisor.get(advisor)
        if not docs:
            return []
        stats = self.stats[advisor]
        q_stems = set(_stems(query))
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
            Passage(
                advisor=doc["advisor"],
                work=doc.get("work", ""),
                ref=doc.get("ref", ""),
                source=doc.get("source", ""),
                text=doc["text"],
                score=round(score, 3),
            )
            for score, doc in scored[:k]
            if score >= MIN_SCORE
        ]


@lru_cache(maxsize=1)
def get_index() -> CorpusIndex | None:
    """Build the index once per process. None means retrieval is unavailable —
    a turn must never fail because the corpus could not be read."""
    try:
        from app.rag.ingest import collect_chunks

        chunks = collect_chunks()
    except Exception:  # noqa: BLE001 - retrieval must never sink a turn
        return None
    return CorpusIndex(chunks) if chunks else None


def search(advisor: str, query: str, k: int = TOP_K) -> list[Passage]:
    index = get_index()
    if index is None:
        return []
    try:
        return index.search(advisor, query, k)
    except Exception:  # noqa: BLE001
        return []


def render(advisor: str, query: str) -> str:
    """What the agent receives: its own passages, or an explicit nothing."""
    hits = search(advisor, query)
    if not hits:
        return (
            "Bu sualla səsləşən parça öz mətnlərində tapılmadı — "
            "sitatsız, öz xarakterinlə cavab ver."
        )
    return "\n".join(
        f"[{i + 1}] «{h.text.strip()}» — {h.work}, {h.ref} (uyğunluq {h.score})"
        for i, h in enumerate(hits)
    )
