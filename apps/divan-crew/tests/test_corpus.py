"""KNOWN-ANSWER check for the corpus tool, against the REAL corpus.

The known answers here are facts about the shipped corpus that a human can
verify by opening the files: Nəsimi's «Sığmazam» contains the line about two
worlds fitting inside one person; Koroğlu's texts are about Çənlibel and his
dəlilər; Nizami's are Leyli və Məcnun and Sirlər Xəzinəsi. So a question in
each member's own vocabulary must return that member's own work, and a
question about none of it must return nothing rather than a weak best guess.

If the corpus is not importable (no course app on this machine) the whole
case class is skipped loudly — never silently passed.
"""

from __future__ import annotations

import unittest

import corpus

INDEX = corpus.get_index()


@unittest.skipIf(INDEX is None, "course corpus not importable on this machine")
class RealCorpus(unittest.TestCase):
    def test_every_member_has_text(self):
        counts = INDEX.counts()
        for key in ("nesreddin", "koroglu", "simurg", "nesimi", "dedeqorqud", "nizami"):
            self.assertIn(key, counts, key)
            self.assertGreater(counts[key], 0, key)

    def test_nesimi_finds_his_own_famous_line(self):
        hits = corpus.search("nesimi", "iki cahan mənə sığmaz")
        self.assertTrue(hits, "no passage for Nəsimi's best-known ghazal")
        self.assertIn("sığmazam", " ".join(h.text.lower() for h in hits))

    def test_koroglu_finds_chenlibel(self):
        hits = corpus.search("koroglu", "Çənlibel dəlilər igidlik")
        self.assertTrue(hits)
        self.assertEqual(hits[0].advisor, "koroglu")

    def test_a_member_never_returns_another_members_text(self):
        for key in ("nesimi", "koroglu", "nizami", "dedeqorqud"):
            for hit in corpus.search(key, "eşq, ədalət, igidlik, nəsihət"):
                self.assertEqual(hit.advisor, key)

    def test_citation_carries_provenance(self):
        hits = corpus.search("nizami", "Leyli Məcnun eşq")
        self.assertTrue(hits)
        self.assertTrue(hits[0].work)
        self.assertTrue(hits[0].ref)
        self.assertTrue(hits[0].source.startswith("http"))

    def test_off_corpus_question_returns_nothing(self):
        # Nothing in a 15th-century divan is about this. A retriever that
        # answers anyway is the one that invents citations.
        hits = corpus.search("nesimi", "kubernetes konteyner orkestrasiyası")
        self.assertEqual(hits, [])
        self.assertIn("tapılmadı", corpus.render("nesimi", "kubernetes konteyner"))

    def test_scores_are_ordered(self):
        hits = corpus.search("dedeqorqud", "ata oğul nəsihət", k=2)
        if len(hits) == 2:
            self.assertGreaterEqual(hits[0].score, hits[1].score)


class DegradesSafely(unittest.TestCase):
    def test_unknown_advisor_is_empty_not_an_error(self):
        self.assertEqual(corpus.search("shakespeare", "to be or not to be"), [])

    def test_empty_query_is_empty(self):
        self.assertEqual(corpus.search("nesimi", ""), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
