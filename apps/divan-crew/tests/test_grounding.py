"""The anti-fabrication rule, pinned by the failure that produced it.

The first live council run returned this citation:

    work   "Divan"
    ref    "qəzəl, mətlə beyti"
    source "Nəsimi, Seçilmiş əsərləri"

The quoted line is real. The provenance is not: our corpus holds that ghazal
as «Sığmazam (qəzəl)» sourced from az.wikisource.org, and the run had made
ZERO tool calls, so nothing had been retrieved at all. A model asked for
`citations` will happily supply plausible ones.

So the rule is: citations come from the retrieval ledger, never from the
model, and a run that never called the corpus tool is reported ungrounded.
"""

from __future__ import annotations

import unittest

import crew
from schemas import DivanVerdict


class ToolLedger(unittest.TestCase):
    def setUp(self):
        crew.reset_ledger()

    def test_ledger_starts_empty(self):
        self.assertEqual(crew._CITATION_LEDGER, [])
        self.assertEqual(crew._TOOL_CALLS["corpus"], 0)

    def test_a_real_search_writes_real_provenance(self):
        out = crew.corpus_tool.run(advisor="nesimi", query="iki cahan sığmazam")
        self.assertIn("Sığmazam", out)
        self.assertEqual(crew._TOOL_CALLS["corpus"], 1)
        self.assertTrue(crew._CITATION_LEDGER)
        entry = crew._CITATION_LEDGER[0]
        # The exact provenance the fabricated citation got wrong.
        self.assertIn("Sığmazam", entry["work"])
        self.assertTrue(entry["source"].startswith("https://az.wikisource.org"))
        self.assertEqual(entry["retrieval"], "bm25")

    def test_a_miss_is_counted_but_cites_nothing(self):
        out = crew.corpus_tool.run(advisor="nesimi", query="kubernetes konteyner")
        self.assertIn("tapılmadı", out)
        self.assertEqual(crew._TOOL_CALLS["corpus"], 1)
        self.assertEqual(crew._CITATION_LEDGER, [])

    def test_metre_tool_is_counted(self):
        crew.metre_tool.run(text="Əzizim, vətən yaxşı,\nKöynəyi kətan yaxşı.")
        self.assertEqual(crew._TOOL_CALLS["metre"], 1)


class ModelCitationsAreDropped(unittest.TestCase):
    """The replacement itself: whatever the model wrote is discarded and the
    ledger is substituted, so a run with no tool calls ends with no citations
    rather than with convincing ones."""

    def setUp(self):
        crew.reset_ledger()
        self.verdict = DivanVerdict(
            question="Qorxuram.",
            consulted=["nesimi"],
            opinions=[{"advisor": "nesimi", "name": "Nəsimi", "text": "Qorxma."}],
            verdict="Öz dəyərini tanı.",
            citations=[{
                "advisor": "nesimi",
                "work": "Divan",                       # the fabricated one
                "ref": "qəzəl, mətlə beyti",
                "quote": "Məndə sığar iki cahan...",
                "source": "Nəsimi, Seçilmiş əsərləri",  # a source we do not have
            }],
        )

    def _apply_ledger(self, verdict):
        from schemas import Citation

        verdict.citations = [Citation(**c) for c in crew._CITATION_LEDGER]
        return verdict

    def test_no_tool_call_means_no_citation(self):
        result = self._apply_ledger(self.verdict)
        self.assertEqual(result.citations, [])

    def test_a_real_call_replaces_the_invented_one(self):
        crew.corpus_tool.run(advisor="nesimi", query="iki cahan sığmazam")
        result = self._apply_ledger(self.verdict)
        self.assertTrue(result.citations)
        works = {c.work for c in result.citations}
        self.assertNotIn("Divan", works)
        sources = {c.source for c in result.citations}
        self.assertNotIn("Nəsimi, Seçilmiş əsərləri", sources)



class VoiceGuard(unittest.TestCase):
    """The second live run leaked retrieval vocabulary into what a 15th-century
    poet says out loud: «uyğunluq balı 6.415», «retrieval: BM25», «hissə 1».
    The prompt asks; this guard measures."""

    def test_machine_vocabulary_is_caught(self):
        leaked = (
            "Öz divanımda tapıldı — bənd 1, retrieval: BM25 "
            "(uyğunluq balı 7.262)."
        )
        found = crew.voice_leaks(leaked)
        self.assertIn("bm25", found)
        self.assertIn("retrieval", found)
        self.assertIn("uyğunluq bal", found)

    def test_a_clean_human_answer_passes(self):
        clean = (
            "Qorxun təbiidir, amma oturmaq da bir seçimdir. "
            "Bu gün kiçik bir addım at."
        )
        self.assertEqual(crew.voice_leaks(clean), [])

    def test_a_url_never_belongs_in_speech(self):
        self.assertIn("http", crew.voice_leaks("Bax https://az.wikisource.org/..."))

    def test_the_tool_no_longer_shows_a_score_to_the_agent(self):
        crew.reset_ledger()
        out = crew.corpus_tool.run(advisor="nesimi", query="iki cahan sığmazam")
        self.assertNotIn("uyğunluq", out)
        # but the provenance still reaches the LEDGER, which is where it belongs
        self.assertTrue(crew._CITATION_LEDGER[0]["source"].startswith("https://"))


class HollowCouncil(unittest.TestCase):
    """The check that caught the first live run, pinned so it cannot return.

    The two telemetry blocks below are VERBATIM from the recorded runs: the
    first council answered in one model call having consulted nobody, the
    third delegated to two members and opened their texts. A refactor of the
    manager that quietly restores the first shape fails here.
    """

    RUN1_HOLLOW = {"brain": {"claude_calls": 1, "fallback_calls": 0},
                   "tool_calls": {"corpus": 0, "metre": 0, "corpus_hits": 0}}
    RUN3_REAL = {"brain": {"claude_calls": 8, "fallback_calls": 0},
                 "tool_calls": {"corpus": 2, "metre": 0, "corpus_hits": 4}}

    def test_one_call_for_two_members_is_hollow(self):
        reason = crew.is_hollow(self.RUN1_HOLLOW, ["koroglu", "nesimi"])
        self.assertIsNotNone(reason)
        self.assertIn("model çağırışı", reason)

    def test_a_real_delegated_run_passes(self):
        self.assertIsNone(crew.is_hollow(self.RUN3_REAL, ["dedeqorqud", "nesimi"]))

    def test_no_tool_call_is_hollow_even_with_many_model_calls(self):
        telemetry = {"brain": {"claude_calls": 9, "fallback_calls": 0},
                     "tool_calls": {"corpus": 0}}
        reason = crew.is_hollow(telemetry, ["nesimi", "nizami"])
        self.assertIn("öz mətninə baxmayıb", reason)

    def test_an_empty_roster_is_hollow(self):
        self.assertIsNotNone(crew.is_hollow(self.RUN3_REAL, []))

if __name__ == "__main__":
    unittest.main(verbosity=2)
