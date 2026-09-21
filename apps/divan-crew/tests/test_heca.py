"""KNOWN-ANSWER check for the metre tool — run before any count is trusted.

Every expectation below was counted BY HAND from published verse, and the
hand count is written next to the line so a reader can re-do it without
running anything. The fixtures are deliberately not all clean: two of them
pin honest negatives (a line with no canonical bölgü, an apostrophe the
vowel rule cannot resolve), because a tool that only passes on easy input
has not been checked.
"""

from __future__ import annotations

import unittest

import heca
from az_text import syllables

# Koroğlu dastanı — «Durna teli», Koroğlu's own qoşma. 8 heca.
# Nigar(2) xanım(2) sənə(2) deyim(2)            = 8, boundary 4 reachable -> 4+4
# Bu(1) gələn(2) Eyvaz(2) bu(1) gələn(2)        = 8; 4 NOT reachable, 5 and 3
#   both are -> 5+3 AND 3+5. The first hand count here claimed 5+3 only and
#   the tool disagreed; re-counting by hand proved the TOOL right («Bu gələn»
#   is 3), so the expectation was corrected, never the code.
# Dili(2) dodağıyı(4) yeyim(2)                  = 8, neither 3,4,5 reachable -> none
# Bu(1) gələn(2) Eyvaz(2) bu(1) gələn(2)        = 8 -> 5+3
KOROGLU_8 = """Nigar xanım, sənə deyim,
Bu gələn Eyvaz, bu gələn.
Dili dodağıyı yeyim,
Bu gələn Eyvaz, bu gələn."""

# Molla Pənah Vaqif — «Bayram oldu...». 11 heca.
# Bayram(2) oldu(2) heç(1) bilmirəm(3) neyləyim(3)        = 11 -> 4+4+3
# Bizim(2) evdə(2) dolu(2) çuval(2) da(1) yoxdur(2)       = 11 -> 6+5 and 4+4+3
# Dügü(2) ilə(2) yağ(1) hamısı(3) çoxdandır(3)            = 11 -> 4+4+3
# Ət(1) heç(1) ələ(2) düşməz(2) motal(2) da(1) yoxdur(2)  = 11 -> 6+5 and 4+4+3
VAQIF_11 = """Bayram oldu, heç bilmirəm neyləyim,
Bizim evdə dolu çuval da yoxdur.
Dügü ilə yağ hamısı çoxdandır,
Ət heç ələ düşməz, motal da yoxdur."""

# Classic bayatı. 7 heca.
# Əzizim(3) vətən(2) yaxşı(2)   = 7, 4 not reachable, 3 is -> 3+4
# Köynəyi(3) kətan(2) yaxşı(2)  = 7 -> 3+4
# Qürbət(2) cənnət(2) olsa(2) da(1) = 7 -> 4+3
# Yenə(2) də(1) vətən(2) yaxşı(2)   = 7 -> 3+4
BAYATI_7 = """Əzizim, vətən yaxşı,
Köynəyi kətan yaxşı.
Qürbət cənnət olsa da,
Yenə də vətən yaxşı."""


class SyllableRule(unittest.TestCase):
    def test_one_vowel_one_syllable(self):
        for word, expected in [
            ("Nigar", 2), ("dodağıyı", 4), ("neyləyim", 3), ("Eyvaz", 2),
            ("yoxdur", 2), ("Əzizim", 3), ("çoxdandır", 3), ("da", 1), ("heç", 1),
        ]:
            self.assertEqual(syllables(word), expected, word)

    def test_capital_dotted_i_folds(self):
        # "İ".casefold() keeps a combining dot; az_lower must map it to i.
        self.assertEqual(syllables("İlə"), 2)
        self.assertEqual(syllables("IŞIQ"), 2)

    def test_apostrophe_is_not_a_syllable(self):
        # mə'na = mə-na: the apostrophe lengthens, it does not add a syllable.
        self.assertEqual(syllables("mə'na"), 2)
        self.assertEqual(syllables("sən'ət"), 2)

    def test_known_limit_apostrophe_standing_for_a_vowel(self):
        # şe'r is read şe-ir (2 syllables) but carries one written vowel.
        # The rule gets this WRONG by design; the report must flag it rather
        # than report a confident 1.
        self.assertEqual(syllables("şe'r"), 1)
        report = heca.analyse("Bu şe'r qısadır")
        self.assertIn("apostrof", report.lines[0].flags)
        self.assertIn("apostrof", report.note)


class KoroghluQoshma(unittest.TestCase):
    def setUp(self):
        self.report = heca.analyse(KOROGLU_8)

    def test_every_line_is_eight(self):
        self.assertEqual([r.heca for r in self.report.lines], [8, 8, 8, 8])

    def test_form_named_only_because_it_is_consistent(self):
        self.assertTrue(self.report.consistent)
        self.assertEqual(self.report.form, "gəraylı / dastan qoşması (8 heca)")

    def test_bolgu_is_per_line_and_honest(self):
        self.assertEqual(self.report.lines[0].bolgu, ["4+4"])
        self.assertEqual(self.report.lines[1].bolgu, ["5+3", "3+5"])
        # Real folk verse: this line honours no canonical caesura.
        self.assertEqual(self.report.lines[2].bolgu, [])
        self.assertEqual(self.report.bolgu_lines, 3)
        self.assertEqual(self.report.bolgu_ratio, 0.75)
        self.assertIn("kanonik bölgü yoxdur", self.report.note)

    def test_rhyme_scheme(self):
        # deyim/gələn/yeyim/gələn -> a b a b
        self.assertEqual(self.report.rhyme, "abab")


class VaqifQoshma(unittest.TestCase):
    def setUp(self):
        self.report = heca.analyse(VAQIF_11)

    def test_eleven_syllables_throughout(self):
        self.assertEqual([r.heca for r in self.report.lines], [11, 11, 11, 11])
        self.assertEqual(self.report.form, "qoşma (11 heca)")

    def test_bolgu_patterns_found(self):
        self.assertEqual(self.report.lines[0].bolgu, ["4+4+3"])
        self.assertEqual(self.report.lines[1].bolgu, ["6+5", "4+4+3"])
        self.assertEqual(self.report.bolgu_ratio, 1.0)

    def test_first_stanza_rhymes_abcb(self):
        # neyləyim / yoxdur / çoxdandır / yoxdur
        self.assertEqual(self.report.rhyme, "abcb")


class Bayati(unittest.TestCase):
    def setUp(self):
        self.report = heca.analyse(BAYATI_7)

    def test_seven_syllables(self):
        self.assertEqual([r.heca for r in self.report.lines], [7, 7, 7, 7])
        self.assertEqual(self.report.form, "bayatı (7 heca)")

    def test_classic_aaba(self):
        self.assertEqual(self.report.rhyme, "aaba")

    def test_every_line_has_a_bolgu(self):
        self.assertEqual(self.report.bolgu_ratio, 1.0)
        self.assertEqual(self.report.lines[2].bolgu, ["4+3"])


class RefusesToName(unittest.TestCase):
    def test_ragged_lines_get_no_form(self):
        report = heca.analyse("Bir söz\nİki üç dörd beş altı yeddi səkkiz")
        self.assertFalse(report.consistent)
        self.assertIsNone(report.form)
        self.assertIn("vəzn adlandırılmır", report.note)

    def test_empty_text(self):
        report = heca.analyse("   \n  ")
        self.assertEqual(report.lines, [])
        self.assertIn("Boş mətn", heca.render("   "))

    def test_prose_is_not_forced_into_a_form(self):
        # 12 syllables is not a canonical syllabic metre: no form, no bölgü.
        report = heca.analyse("Bu sətir sadəcə adi nəsr cümləsidir bax")
        self.assertIsNone(report.form)
        self.assertEqual(report.bolgu_lines, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
