"""Offline tests for the RAG layer: corpus parsing, chunking, retrieval math
and the fail-safe paths. No network - embeddings are stubbed."""

import json

import pytest

from app.core.config import settings
from app.rag import ingest, retriever
from app.rag.ingest import chunk_poem, chunk_prose, collect_chunks, parse_source
from app.rag.retriever import Retriever, _cosine, evidence_for, get_retriever


@pytest.fixture(autouse=True)
def fresh_retriever_cache():
    get_retriever.cache_clear()
    yield
    get_retriever.cache_clear()


def test_parse_source_reads_header_and_body(tmp_path):
    f = tmp_path / "x.txt"
    f.write_text("# advisor: nesimi\n# work: Divan\n\nMisra bir\n", encoding="utf-8")
    meta, body = parse_source(f)
    assert meta == {"advisor": "nesimi", "work": "Divan"}
    assert body == "Misra bir"


def test_chunk_poem_merges_tiny_bends_and_keeps_refs():
    body = "a\nb\n\nc\nd\n\n" + ("uzun misra " * 20) + "\n\nson"
    chunks = chunk_poem(body)
    assert all(ref.startswith("bənd") for _, ref in chunks)
    # tiny leading couplets are merged, nothing is lost
    joined = "\n".join(text for text, _ in chunks)
    for piece in ("a", "c", "son"):
        assert piece in joined


def test_chunk_prose_packs_paragraphs():
    body = "\n\n".join(f"abzas {i} " + "söz " * 40 for i in range(6))
    chunks = chunk_prose(body)
    assert len(chunks) > 1
    assert all(len(text) <= ingest.MAX_PROSE_CHUNK + 250 for text, _ in chunks)


def test_repo_corpus_parses_into_chunks_for_three_advisors():
    chunks = collect_chunks()
    advisors = {c["advisor"] for c in chunks}
    assert {"nesimi", "dedeqorqud", "koroglu"} <= advisors
    assert all(c["work"] and c["ref"] and c["text"] for c in chunks)


def test_cosine_basics():
    assert _cosine([1, 0], [1, 0]) == pytest.approx(1.0)
    assert _cosine([1, 0], [0, 1]) == pytest.approx(0.0)
    assert _cosine([], []) == 0.0


@pytest.mark.anyio
async def test_retriever_ranks_by_similarity(monkeypatch):
    r = Retriever.__new__(Retriever)
    r.model = "stub"
    r.by_advisor = {
        "nesimi": [
            {"advisor": "nesimi", "work": "Divan", "ref": "bənd 1", "source": "s",
             "text": "iki cahan", "embedding": [1.0, 0.0]},
            {"advisor": "nesimi", "work": "Divan", "ref": "bənd 2", "source": "s",
             "text": "başqa mövzu", "embedding": [0.0, 1.0]},
        ]
    }

    class FakeEmbeddings:
        async def create(self, model, input):
            class R:
                data = [type("D", (), {"embedding": [1.0, 0.05]})()]
            return R()

    r._client = type("C", (), {"embeddings": FakeEmbeddings()})()

    hits = await r.retrieve("nesimi", "cahan sualı")
    assert hits and hits[0]["ref"] == "bənd 1"
    assert all(h["score"] >= retriever.MIN_SCORE for h in hits)
    assert await r.retrieve("koroglu", "x") == []


@pytest.mark.anyio
async def test_evidence_for_is_silent_without_index(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "SQLITE_PATH", str(tmp_path / "db.sqlite"))
    assert await evidence_for("nesimi", "salam") == []


def test_get_retriever_loads_index_file(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "SQLITE_PATH", str(tmp_path / "db.sqlite"))
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "test-key")
    index = settings.rag_index_file
    index.parent.mkdir(parents=True, exist_ok=True)
    index.write_text(json.dumps({"model": "m", "chunks": [
        {"advisor": "koroglu", "work": "Dastan", "ref": "hissə 1", "source": "s",
         "text": "t", "embedding": [1.0]},
    ]}), encoding="utf-8")

    r = get_retriever()
    assert r is not None and "koroglu" in r.by_advisor
