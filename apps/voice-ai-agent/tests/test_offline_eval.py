"""The offline eval harness: its scorers, its gates and its own golden set."""

import json

import pytest

from app.evals import judge as judge_module
from app.evals import offline
from app.evals.persona import forbidden_address, score_reply, unsupported_quotes
from app.rag.ingest import collect_chunks


@pytest.fixture(scope="module")
def golden():
    return json.loads(offline.GOLDEN.read_text(encoding="utf-8"))


async def test_golden_set_meets_its_own_gates(golden):
    report = await offline.evaluate(golden)
    assert report["gate_misses"] == []
    assert report["metrics"]["citations_checked"] > 0


def test_main_exits_zero_on_the_committed_golden_set(capsys):
    assert offline.main([]) == 0
    assert "GATES OK" in capsys.readouterr().out


def test_gates_report_a_regression():
    assert offline.check_gates({"lexical_hit_at_2": 0.9}, {"lexical_hit_at_2": 1.0}) == [
        "lexical_hit_at_2 = 0.9 < 1.0"
    ]
    assert offline.check_gates({"corpus_markup_chunks": 3}, {"corpus_markup_chunks_max": 2})
    assert offline.check_gates({"corpus_markup_chunks": 2}, {"corpus_markup_chunks_max": 2}) == []


def test_known_gap_is_reported_but_never_counted_against_the_gate():
    chunks = collect_chunks()
    case = {"id": "x", "advisor": "koroglu", "kind": "abstain", "query": "Bitcoin qiyməti nə qədərdir?",
            "status": "known_gap"}
    out = offline.run_retrieval([case], chunks)
    assert out["rows"][0]["state"] in {"XFAIL", "XPASS"}
    lexical = {"id": "y", "advisor": "nesimi", "kind": "lexical", "query": "Məndə sığar iki cahan",
               "expect_work": "Sığmazam", "status": "known_gap"}
    assert offline.run_retrieval([lexical], chunks)["metrics"]["lexical_hit_at_2"] == 1.0


def test_wrong_expected_work_is_a_failed_retrieval_case():
    case = {"id": "x", "advisor": "nesimi", "kind": "lexical", "query": "Məndə sığar iki cahan",
            "expect_work": "Başqa əsər"}
    out = offline.run_retrieval([case], collect_chunks())
    assert out["rows"][0]["state"] == "FAIL"
    assert out["metrics"]["lexical_hit_at_2"] == 0.0


def test_citation_check_rejects_tampered_and_foreign_passages():
    chunks = collect_chunks()
    real = next(c for c in chunks if c["advisor"] == "nesimi")
    good = {"advisor": "nesimi", "work": real["work"], "quote": real["text"][:80], "source": "https://x.test"}
    assert offline._verbatim(good, chunks)
    assert not offline._verbatim({**good, "quote": good["quote"] + " uydurma"}, chunks)
    assert not offline._verbatim({**good, "advisor": "koroglu"}, chunks)  # another advisor's shelf
    assert not offline._verbatim({**good, "source": ""}, chunks)


# ---------------------------------------------------------------- scorers
def test_each_advisor_is_forbidden_the_others_forms_of_address_only():
    assert "oğul" in forbidden_address("nesimi")
    assert "ey can" not in forbidden_address("nesimi")
    assert "qardaş" not in forbidden_address("koroglu")  # shared with Nəsrəddin
    assert "qardaş" in forbidden_address("nizami")


def test_quotes_are_checked_against_corpus_evidence_and_verified_lines():
    assert unsupported_quotes("Dedi: «Hər kim ki ədaləti satar, tacı başında yanar»") != []
    assert unsupported_quotes("«Məndə sığar iki cahan, mən bu cahana sığmazam»") == []
    evidence = [{"text": "Qılınc qını bilər, igid yolunu bilər"}]
    assert unsupported_quotes("«qılınc qını bilər, igid yolunu»", evidence) == []
    assert unsupported_quotes("«Qaraqaşqabaqlı dünya»") == []  # two words is a phrase, not a quotation claim


def test_endings_do_not_hide_an_anachronism():
    verdict = score_reply({"advisor": "koroglu"}, "Hey igid, telefonla xəbər ver, maaşını da al.")
    assert any("anaxronizm" in f for f in verdict["fails"])


def test_clean_reply_has_no_failures():
    verdict = score_reply({"advisor": "koroglu"}, "Hey, igid! Qorxu hər kişinin qapısını döyər, qapını açmaq öz əlindədir.")
    assert verdict["fails"] == []


# ---------------------------------------------------------------- judge
GOOD = {"xarakter": 4, "mentalitet": 5, "dil": 4, "bedii": 3, "fayda": 4, "qusurlar": ["a"], "bir_cumle": "ok"}


def test_parse_verdict_accepts_wrapped_json_and_rejects_the_rest():
    parsed = judge_module.parse_verdict("Budur:\n" + json.dumps(GOOD) + "\nsağ ol")
    assert parsed["dil"] == 4.0 and parsed["qusurlar"] == ["a"]
    assert "error" in judge_module.parse_verdict("no json here")
    assert "error" in judge_module.parse_verdict(json.dumps({**GOOD, "dil": 9}))
    assert "error" in judge_module.parse_verdict(json.dumps({**GOOD, "dil": True}))
    assert "error" in judge_module.parse_verdict(json.dumps({k: v for k, v in GOOD.items() if k != "fayda"}))


def test_run_judge_averages_and_flags_floor_breaches():
    cases = [{"question": "q", "reply": "r", "advisor": "koroglu"}] * 2
    calls = iter([GOOD, {**GOOD, "dil": 2}])
    out = judge_module.run_judge(cases, lambda q, r, c: next(calls), floors={"dil": 3.5, "xarakter": 3.5})
    assert out["judged"] == 2 and out["means"]["dil"] == 3.0
    assert out["breaches"] == {"dil": (3.0, 3.5)}


def test_judge_errors_are_counted_not_scored():
    out = judge_module.run_judge(
        [{"question": "q", "reply": "r", "advisor": "koroglu"}], lambda q, r, c: {"error": "timeout"}
    )
    assert out == {"judged": 0, "errors": 1, "means": {}, "breaches": {}}
