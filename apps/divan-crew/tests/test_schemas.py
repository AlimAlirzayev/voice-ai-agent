"""The structured verdict and the strict routing parse.

The routing cases are the point: the product today answers a garbage
supervisor token by quietly consulting whichever advisor is first in the
roster. These tests pin the replacement — garbage raises.
"""

from __future__ import annotations

import unittest

from pydantic import ValidationError

from schemas import (
    CLOSING_TOKEN,
    DivanVerdict,
    Opinion,
    RoutingError,
    parse_advisor_token,
)


class Routing(unittest.TestCase):
    def test_accepts_a_roster_key(self):
        self.assertEqual(parse_advisor_token("KOROGLU"), "koroglu")
        self.assertEqual(parse_advisor_token("nizami\n"), "nizami")
        self.assertEqual(parse_advisor_token("Simurg."), "simurg")

    def test_accepts_the_closing_token(self):
        self.assertEqual(parse_advisor_token("YEKUN"), CLOSING_TOKEN)
        self.assertEqual(parse_advisor_token("yekun, bəsdir"), CLOSING_TOKEN)

    def test_garbage_fails_loudly_instead_of_picking_someone(self):
        # Each of these silently routes to ROSTER's first key today.
        for garbage in ["Bilmirəm", "", "   ", "```json", "I am not sure", "42"]:
            with self.assertRaises(RoutingError, msg=garbage):
                parse_advisor_token(garbage)

    def test_none_fails(self):
        with self.assertRaises(RoutingError):
            parse_advisor_token(None)


class Verdict(unittest.TestCase):
    def _verdict(self, **overrides):
        payload = {
            "question": "Qorxuram qərar verməyə.",
            "consulted": ["koroglu"],
            "opinions": [{"advisor": "koroglu", "name": "Koroğlu", "text": "Qorxma."}],
            "verdict": "Qorxunu tanı, sonra addım at.",
        }
        payload.update(overrides)
        return DivanVerdict(**payload)

    def test_valid_verdict(self):
        verdict = self._verdict()
        self.assertEqual(verdict.consulted, ["koroglu"])
        self.assertFalse(verdict.needs_approval)

    def test_koroglu_triggers_the_human_gate(self):
        self.assertTrue(self._verdict().with_approval_rule().needs_approval)

    def test_a_calm_member_does_not(self):
        verdict = self._verdict(
            consulted=["nizami"],
            opinions=[{"advisor": "nizami", "name": "Nizami Gəncəvi", "text": "Səbr."}],
        ).with_approval_rule()
        self.assertFalse(verdict.needs_approval)

    def test_unknown_advisor_key_is_rejected(self):
        with self.assertRaises(ValidationError):
            self._verdict(consulted=["shakespeare"])
        with self.assertRaises(ValidationError):
            Opinion(advisor="shakespeare", name="X", text="y")

    def test_roster_cap_is_enforced(self):
        with self.assertRaises(ValidationError):
            self._verdict(consulted=["koroglu", "nizami", "simurg"])

    def test_same_advisor_twice_is_rejected(self):
        with self.assertRaises(ValidationError):
            self._verdict(consulted=["koroglu", "koroglu"])

    def test_empty_verdict_is_rejected(self):
        with self.assertRaises(ValidationError):
            self._verdict(verdict="")

    def test_citation_records_how_it_was_retrieved(self):
        verdict = self._verdict(citations=[{
            "advisor": "koroglu", "work": "Koroğlu dastanı", "ref": "hissə 3",
            "quote": "...", "source": "https://az.wikisource.org/",
        }])
        # Default must be the weaker method actually used, never 'embedding'.
        self.assertEqual(verdict.citations[0].retrieval, "bm25")


if __name__ == "__main__":
    unittest.main(verbosity=2)
