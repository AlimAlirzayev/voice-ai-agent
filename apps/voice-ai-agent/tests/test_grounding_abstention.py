"""Grounding gate: off-topic questions get no citation, markup never reaches a quote,
and the offline golden gates hold."""
import json

from app.evals import offline
from app.graph.guardrails import is_out_of_scope
from app.rag.bm25 import BM25Index
from app.rag.ingest import collect_chunks, parse_source, strip_markup


def _golden():
    return json.loads(offline.GOLDEN.read_text(encoding="utf-8"))


def test_offline_gates_hold():
    result = offline.evaluate(_golden())
    for gate, floor in offline.GATES.items():
        assert result[gate] >= floor, (gate, result[gate])
    assert result["markup_chunks"] == 0


def test_gate_is_what_fixes_abstention():
    old = offline.evaluate(_golden(), gate=False)
    assert old["abstention"] == 0.0 and old["scope_abstention"] == 0.0


def test_min_matched_is_a_per_call_override():
    index = BM25Index(collect_chunks())
    q = "Bitcoin-in qiyməti bu gün nə qədərdir?"
    assert index.search("koroglu", q) == []
    assert index.search("koroglu", q, min_matched=1)  # the old behaviour is reachable


def test_scope_gate_keeps_borderline_questions():
    for case in _golden()["council_scope"]:
        assert is_out_of_scope(case["query"]) is case["out_of_scope"], case["id"]
    assert not is_out_of_scope("")


def test_strip_markup_removes_templates_and_image_options():
    raw = "{{Başlıq\n| müəllif = X\n| il =\n}}\n\nFəzli həqdir\nFəzli həq memarımız.\n"
    assert strip_markup(raw) == "Fəzli həqdir\nFəzli həq memarımız."
    assert strip_markup("thumbnail\nBiri varmış") == "Biri varmış"
    assert strip_markup("a {{x {{y}} z}} b") == "a  b"
    assert strip_markup("[[Fayl:a.jpg|thumb|x]]\nsöz") == "söz"
    assert strip_markup("Thumbnail görüntüsü yoxdur") == "Thumbnail görüntüsü yoxdur"


def test_known_flagged_sources_still_carry_debris_but_chunks_do_not():
    """The two flagged files are left as transcribed (editing quotable text needs
    the owner's sign-off); the loader is what keeps the debris out of citations."""
    root = offline.GOLDEN.parent.parent / "rag" / "corpus"
    for rel in ("nesimi/rubailer.txt", "simurg/melikmemmed-zumrud-qusu.txt"):
        _, body = parse_source(root / rel)
        assert strip_markup(body) != body, rel
    for chunk in collect_chunks():
        assert not offline._MARKUP.search(chunk["text"]), (chunk["work"], chunk["ref"])


def test_legacy_refs_still_resolve_to_the_same_text():
    """Cleaning markup must not renumber citations: chunk the files exactly as the
    pre-gate loader did (raw body, no stripping) and require every old ref that
    carried text to resolve to the same text, minus the debris."""
    from app.rag import ingest

    new = {(c["advisor"], c["work"], c["ref"]): c["text"] for c in collect_chunks()}
    checked = 0
    for path in sorted(ingest.CORPUS_DIR.rglob("*.txt")):
        meta, body = parse_source(path)
        if not body or "advisor" not in meta:
            continue
        chunker = ingest.chunk_poem if meta.get("type") == "poem" else ingest.chunk_prose
        for text, ref in chunker(body):
            key = (meta["advisor"], meta.get("work", path.stem), ref)
            expected = strip_markup(text)
            if expected:
                assert new[key] == expected, key
                checked += 1
            else:
                assert key not in new, key  # a pure-markup chunk simply stops existing
    assert checked > 300
    rub = {ref: text for (a, w, ref), text in new.items() if w == "Rübailər"}
    assert "bənd 1" not in rub and rub["bənd 2"].startswith("Fəzli həqdir vaqifi əsrarımız")
    assert new[next(k for k in new if k[1].startswith("Məlikməmməd") and k[2] == "hissə 1")].startswith("Biri varmış")


def _reference_search(index, advisor, query, k, min_score):
    """The scoring loop exactly as it was before the coverage gate existed."""
    import math

    from app.rag import bm25

    docs = index.by_advisor.get(advisor)
    if not docs:
        return []
    stats = index.stats[advisor]
    q_stems = set(bm25.stems(query))
    scored = []
    for doc in docs:
        score = 0.0
        for stem in q_stems:
            tf = doc["_stems"].get(stem, 0)
            if not tf:
                continue
            df = stats["df"].get(stem, 0)
            idf = math.log(1 + (stats["n"] - df + 0.5) / (df + 0.5))
            norm = 1 - bm25.B + bm25.B * doc["_len"] / stats["avg_len"]
            score += idf * (tf * (bm25.K1 + 1)) / (tf + bm25.K1 * norm)
        if score > 0:
            scored.append((score, doc))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [(d["ref"], round(s, 3)) for s, d in scored[:k] if s >= min_score]


def test_public_surface_is_unchanged_for_callers_that_pass_nothing_new():
    import inspect

    from app.rag import bm25, retriever

    # retrieve(): same parameters, same defaults, same hit shape
    sig = inspect.signature(bm25.BM25Retriever.retrieve)
    assert list(sig.parameters) == ["self", "advisor", "query", "k"]
    assert sig.parameters["k"].default == bm25.TOP_K == retriever.TOP_K
    assert bm25.BM25Retriever.model == "bm25"
    assert inspect.iscoroutinefunction(bm25.BM25Retriever.retrieve)
    assert inspect.iscoroutinefunction(retriever.evidence_for)
    assert list(inspect.signature(retriever.evidence_for).parameters) == ["advisor", "query"]

    # search(): the old positional signature is a prefix of the new one; additions are keyword-only
    params = inspect.signature(bm25.BM25Index.search).parameters
    assert list(params)[:4] == ["self", "advisor", "query", "k"]
    for name in ("min_score", "min_matched"):
        assert params[name].kind is inspect.Parameter.KEYWORD_ONLY
    assert params["min_score"].default == bm25.MIN_SCORE
    assert params["min_matched"].default == bm25.MIN_MATCHED

    # no-argument call == explicit defaults, and the hit dict has its original keys
    index = BM25Index(collect_chunks())
    q = "Məlikməmməd divlə qırx gün qırx gecə güləşdi"
    plain = index.search("simurg", q)
    assert plain == index.search("simurg", q, bm25.TOP_K, min_score=bm25.MIN_SCORE,
                                 min_matched=bm25.MIN_MATCHED)
    assert plain and set(plain[0]) == {"advisor", "work", "ref", "source", "text", "score", "retrieval"}
    assert index.search("yoxdur", q) == [] and index.search("simurg", "") == []

    # the old behaviour is reachable and byte-identical to the pre-gate scoring loop
    for case in _golden()["retrieval"] + _golden()["abstain"]:
        old = [(h["ref"], h["score"]) for h in
               index.search(case["advisor"], case["query"], 2, min_matched=1)]
        assert old == _reference_search(index, case["advisor"], case["query"], 2, bm25.MIN_SCORE)


def test_default_gate_only_ever_removes_hits():
    index = BM25Index(collect_chunks())
    for case in _golden()["retrieval"] + _golden()["abstain"]:
        gated = {h["ref"] for h in index.search(case["advisor"], case["query"], 50)}
        loose = {h["ref"] for h in index.search(case["advisor"], case["query"], 50, min_matched=1)}
        assert gated <= loose
