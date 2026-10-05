"""Citation gate: off-topic questions get no citation, markup and refs, public surface."""
import inspect
import json
import math
import re
import warnings

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from app.evals import gate_sweep
from app.evals.fakes import ScriptedCouncilModel
from app.graph import build_graph, run_turn
from app.rag import bm25, ingest
from app.rag.bm25 import DEFAULT_GATE, GENERIC_STEMS, STRONG_SCORE, BM25Index, BM25Retriever, Gate, az_lower, stems
from app.rag.ingest import collect_chunks, parse_source, strip_markup

CASES = json.loads((gate_sweep.HERE / "grounding_cases.json").read_text(encoding="utf-8"))
ALL_RETRIEVAL = CASES["tuning"]["retrieval"] + CASES["heldout"]["retrieval"]
ALL_OFF_TOPIC = CASES["tuning"]["abstain"] + CASES["heldout"]["abstain"]
# measured leaks of the shipped gate: one strong single stem each (see the report). Pinned so an improvement or a
# regression is a deliberate edit, not a silent drift.
KNOWN_LEAKS = {"off-pizza", "ho-off-dag"}
KNOWN_MISSES = {"sim-divle"}  # gold passage at rank 3, same before and after the gate
ROUTE = {"nesreddin": "NESREDDIN", "koroglu": "KOROGLU", "simurg": "SIMURG", "nesimi": "NESIMI",
         "dedeqorqud": "DEDEQORQUD", "nizami": "NIZAMI"}


@pytest.fixture(scope="module")
def index():
    return BM25Index(collect_chunks())


def _norm(text):
    return " ".join(az_lower(text).split())


# ------------------------------------------------------------------ the gate itself

def test_gate_rules():
    assert Gate().passes([3.0, 3.0, 3.0], 9.0, 4)
    assert not Gate().passes([3.0, 3.0], 9.0, 4)           # a four-stem question needs three
    assert Gate().passes([3.0, 3.0], 6.0, 2)                # a two-stem question needs both
    assert not Gate().passes([3.0], 3.0, 1)                 # never fewer than two
    assert Gate(strong_score=5.5).passes([3.0], 3.0, 4, score=5.5)   # strength is an alternative
    assert not Gate(strong_score=5.5).passes([3.0], 3.0, 4, score=5.4)
    assert not Gate(min_matched=2, min_idf_sum=8).passes([3.0, 3.0], 6.0, 2)
    assert not Gate(min_matched=1, min_best_idf=4).passes([3.0], 3.0, 1)
    assert not Gate(min_matched=2, min_coverage=0.5).passes([3.0, 3.0], 20.0, 6)
    assert DEFAULT_GATE == Gate(strong_score=STRONG_SCORE, drop_generic=True)
    # the stems the audit review flagged as accidental are all generic
    assert {s for w in ("mənim", "istəmirəm", "çıxar", "qabağında", "kimi") for s in stems(w)} <= GENERIC_STEMS


def test_off_topic_questions_retrieve_nothing_except_the_pinned_leaks(index):
    leaks = {c["id"] for c in ALL_OFF_TOPIC if index.search(c["advisor"], c["query"], 2)}
    assert leaks == KNOWN_LEAKS
    old = {c["id"] for c in ALL_OFF_TOPIC if index.search(c["advisor"], c["query"], 2, min_matched=1)}
    assert len(old) >= 20  # before the gate nearly every off-topic question got a citation


def test_in_scope_questions_still_find_their_passage(index):
    missed = {c["id"] for c in ALL_RETRIEVAL
              if not any(_norm(c["gold"]) in _norm(h["text"]) for h in index.search(c["advisor"], c["query"], 2))}
    assert missed == KNOWN_MISSES
    for c in ALL_RETRIEVAL:  # the gold span exists, so a miss is the gate's, not the case's
        assert any(_norm(c["gold"]) in _norm(x["text"]) for x in collect_chunks() if x["advisor"] == c["advisor"])


def test_the_heldout_set_is_disjoint_from_the_tuning_set():
    q = lambda part: {c["query"] for k in ("retrieval", "abstain") for c in CASES[part][k]}  # noqa: E731
    assert not q("tuning") & q("heldout")
    assert len(CASES["heldout"]["abstain"]) >= 12 and len(CASES["heldout"]["retrieval"]) >= 8


def test_shipped_gate_meets_the_sweep_criteria():
    rows = {r["setting"]: r for r in gate_sweep.run()}
    shipped = next(r for name, r in rows.items() if name.endswith("(shipped)"))
    # criteria fixed before choosing: keep every existing retrieval case, abstain on every existing abstain case
    assert shipped["main_hit"] == shipped["n_main_hit"] and shipped["main_off"] == shipped["n_main_off"]
    assert shipped["gold_hit"] >= rows["old: score floor 1.0 only"]["gold_hit"]
    assert shipped["off"] >= 20 and rows["old: score floor 1.0 only"]["off"] <= 1
    # among settings that meet both, none cites fewer lexical accidents on the audit set
    for r in rows.values():
        if r["main_hit"] == r["n_main_hit"] and r["main_off"] == r["n_main_off"] and r["off"] >= shipped["off"]:
            assert r["audit_junk"] >= shipped["audit_junk"], r["setting"]


# ------------------------------------------------------------------ backward compatibility

def _reference_search(index, advisor, query, k, min_score):
    """The scoring loop exactly as it was before the gate existed."""
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


def test_public_surface_is_unchanged_for_callers_that_pass_nothing_new(index):
    sig = inspect.signature(BM25Retriever.retrieve)
    assert list(sig.parameters) == ["self", "advisor", "query", "k"]
    assert sig.parameters["k"].default == bm25.TOP_K and BM25Retriever.model == "bm25"
    assert inspect.iscoroutinefunction(BM25Retriever.retrieve)
    params = inspect.signature(BM25Index.search).parameters
    assert list(params)[:4] == ["self", "advisor", "query", "k"]
    for name in ("min_score", "min_matched", "gate"):
        assert params[name].kind is inspect.Parameter.KEYWORD_ONLY
    assert params["min_score"].default == bm25.MIN_SCORE and params["min_matched"].default == bm25.MIN_MATCHED

    q = "Məlikməmməd divlə qırx gün qırx gecə güləşdi"
    plain = index.search("simurg", q)
    assert plain == index.search("simurg", q, bm25.TOP_K, min_score=bm25.MIN_SCORE,
                                 min_matched=bm25.MIN_MATCHED)
    assert plain and set(plain[0]) == {"advisor", "work", "ref", "source", "text", "score", "retrieval"}
    assert index.search("yoxdur", q) == [] and index.search("simurg", "") == []

    # the old behaviour is reachable, and identical to a frozen copy of the pre-gate scoring loop
    for case in ALL_RETRIEVAL + ALL_OFF_TOPIC:
        old = [(h["ref"], h["score"]) for h in index.search(case["advisor"], case["query"], 2, min_matched=1)]
        assert old == _reference_search(index, case["advisor"], case["query"], 2, bm25.MIN_SCORE)
        gated = {h["ref"] for h in index.search(case["advisor"], case["query"], 50)}
        assert gated <= {h["ref"] for h in index.search(case["advisor"], case["query"], 50, min_matched=1)}


@pytest.mark.asyncio
async def test_retriever_default_call_still_returns_cited_passages():
    r = BM25Retriever(collect_chunks())
    hits = await r.retrieve("nesimi", "Məndə sığar iki cahan, mən bu cahana sığmazam")
    assert hits and hits[0]["retrieval"] == "bm25" and all(h["advisor"] == "nesimi" for h in hits)
    assert await r.retrieve("koroglu", "Bitcoin qiyməti nə qədərdir?") == []


# ------------------------------------------------------------------ corpus markup and stable refs

def test_strip_markup_removes_templates_and_image_options():
    raw = "{{Başlıq\n| müəllif = X\n| il =\n}}\n\nFəzli həqdir\nFəzli həq memarımız.\n"
    assert strip_markup(raw) == "Fəzli həqdir\nFəzli həq memarımız."
    assert strip_markup("thumbnail\nBiri varmış") == "Biri varmış"
    assert strip_markup("a {{x {{y}} z}} b") == "a  b"
    assert strip_markup("[[Fayl:a.jpg|thumb|x]]\nsöz") == "söz"
    assert strip_markup("Thumbnail görüntüsü yoxdur") == "Thumbnail görüntüsü yoxdur"


def test_flagged_sources_keep_their_debris_on_disk_but_chunks_are_clean():
    """Corpus edits need the owner's approval (backlog B4); the loader keeps the debris out of citations."""
    for rel in ("nesimi/rubailer.txt", "simurg/melikmemmed-zumrud-qusu.txt"):
        _, body = parse_source(ingest.CORPUS_DIR / rel)
        assert strip_markup(body) != body, rel
    marker = re.compile(r"\{\{|\}\}|thumbnail|<[a-z/]|\[\[|\|")
    assert not [c for c in collect_chunks() if marker.search(c["text"])]


def test_legacy_refs_still_resolve_to_the_same_text():
    """Chunk every file the pre-cleaning way and require each old ref that carried text to resolve to the same text
    minus the debris; Rübailər "bənd 2" is still "bənd 2" (its "bənd 1" was only the template)."""
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
                assert key not in new, key
    assert checked > 300
    rub = {ref: t for (a, w, ref), t in new.items() if w == "Rübailər"}
    assert "bənd 1" not in rub and rub["bənd 2"].startswith("Fəzli həqdir vaqifi əsrarımız")


def test_cyrillic_lookalikes_in_the_corpus_are_reported_not_edited():
    """Detector only (backlog B4: corpus edits need the owner). Cyrillic letters that look like Latin ones
    ("кimi", "о saat") sit in the transcribed text, break BM25 tokens ("кimi" -> "imi") and would be quoted as written.
    When the owner approves a fix, update KNOWN."""
    KNOWN = {"nizami/xosrov-sirin-esq.txt": 83, "simurg/melikmemmed-zumrud-qusu.txt": 35}
    cyrillic = re.compile(r"[Ѐ-ӿ]")
    found = {}
    for path in sorted(ingest.CORPUS_DIR.rglob("*.txt")):
        _, body = parse_source(path)
        n = sum(bool(cyrillic.search(tok)) for tok in body.split())
        if n:
            found[path.relative_to(ingest.CORPUS_DIR).as_posix()] = n
    if found:
        warnings.warn(f"Cyrillic lookalike tokens in corpus: {found}", stacklevel=1)
    assert found == KNOWN


# ------------------------------------------------------------------ council path (real graph, scripted model)

async def _turn(question, route, tag):
    model = ScriptedCouncilModel(route=route, reply="Sözümü dedim.", host="HOST")
    return await run_turn(build_graph(InMemorySaver(), model), question, f"ground-{tag}"), model


async def test_council_abstains_when_the_router_declines():
    for case in ALL_OFF_TOPIC:
        res, model = await _turn(case["query"], "YEKUN", case["id"])
        assert res.reply.strip() == "HOST" and not res.consulted and not res.citations, case["id"]
        assert not model.advisor_systems


async def test_no_citation_survives_for_off_topic_even_if_the_router_names_an_advisor():
    for case in ALL_OFF_TOPIC:
        if case["id"] in KNOWN_LEAKS:
            continue
        res, _ = await _turn(case["query"], ROUTE[case["advisor"]], case["id"])
        assert not res.citations, (case["id"], res.citations)


async def test_known_limit_a_misrouted_off_topic_question_still_gets_an_advisor_answer():
    """Not a guarantee we want: nothing deterministic stops a router that names an advisor from getting an
    (uncited) advisor answer. Pinned so a future scope classifier flips it on purpose."""
    res, _ = await _turn("Dollar bu gün neçə manatdır?", "NIZAMI", "limit")
    assert res.consulted == ["nizami"] and not res.citations


async def test_council_still_cites_in_scope_questions():
    case = ALL_RETRIEVAL[0]
    res, _ = await _turn(case["query"], ROUTE[case["advisor"]], "in-scope")
    assert res.citations and all(c["advisor"] == case["advisor"] for c in res.citations)
