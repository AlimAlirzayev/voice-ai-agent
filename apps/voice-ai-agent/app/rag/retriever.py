"""Per-advisor retrieval over the ingested corpus index.

Degenerate-graceful by design: no index file, no OpenAI key, or a provider
hiccup all mean "no evidence" - a turn must never fail because retrieval did.
The relevance gate (`MIN_SCORE`) is the light version of the agentic-RAG
grading step: below it, the advisor answers from character alone and no
citation is claimed - an uncited answer is honest, a bad citation is not.
"""

import json
import logging
import math
from functools import lru_cache

from openai import AsyncOpenAI

from app.core.config import settings

log = logging.getLogger(__name__)

MIN_SCORE = 0.30
TOP_K = 2


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class Retriever:
    def __init__(self, model: str, chunks: list[dict]):
        self.model = model
        self.by_advisor: dict[str, list[dict]] = {}
        for chunk in chunks:
            self.by_advisor.setdefault(chunk["advisor"], []).append(chunk)
        self._client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    async def retrieve(self, advisor: str, query: str, k: int = TOP_K) -> list[dict]:
        candidates = self.by_advisor.get(advisor)
        if not candidates:
            return []
        response = await self._client.embeddings.create(model=self.model, input=[query])
        q = response.data[0].embedding
        scored = sorted(
            ({**c, "score": _cosine(q, c["embedding"])} for c in candidates),
            key=lambda c: c["score"],
            reverse=True,
        )
        hits = [c for c in scored[:k] if c["score"] >= MIN_SCORE]
        return [
            {"advisor": c["advisor"], "work": c["work"], "ref": c["ref"],
             "source": c["source"], "text": c["text"], "score": round(c["score"], 3)}
            for c in hits
        ]


@lru_cache(maxsize=1)
def get_retriever() -> Retriever | None:
    """Load the index once per process; None disables retrieval entirely."""
    index_file = settings.rag_index_file
    if not settings.OPENAI_API_KEY or not index_file.exists():
        return None
    try:
        data = json.loads(index_file.read_text(encoding="utf-8"))
        return Retriever(data["model"], data["chunks"])
    except (OSError, json.JSONDecodeError, KeyError) as exc:
        log.warning("rag index unreadable, retrieval disabled: %s", exc)
        return None


async def evidence_for(advisor: str, query: str) -> list[dict]:
    """Safe entry point for graph nodes: empty list on any failure."""
    retriever = get_retriever()
    if retriever is None:
        return []
    try:
        return await retriever.retrieve(advisor, query)
    except Exception as exc:  # noqa: BLE001 - retrieval must never sink a turn
        log.warning("retrieval failed for %s: %s", advisor, exc)
        return []
