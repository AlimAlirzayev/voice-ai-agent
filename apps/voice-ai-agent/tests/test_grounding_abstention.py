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
