"""Azerbaijani text primitives shared by the deterministic tools.

No model, no network, no dependency beyond the standard library. Everything
here is checkable by hand, which is the point: the crew's tools must be
provable on a known answer before any of their numbers are reported.

Two traps are encoded here rather than rediscovered:

* Case folding. `"HİSSƏ".casefold()` keeps a combining dot, so a lowercase
  comparison silently fails on capitals. `az_lower()` maps İ→i and I→ı first.
* The apostrophe. Arabic/Persian loans are written with one (`mə'na`,
  `sən'ət`); it marks a lengthened vowel or a glottal stop, never a new
  syllable, so it is stripped before counting.
"""

from __future__ import annotations

import re

# Every Azerbaijani syllable carries exactly one vowel. That is what makes a
# syllable count deterministic rather than a guess.
VOWELS = frozenset("aeəiıoöuü")

_UPPER_MAP = str.maketrans({"İ": "i", "I": "ı"})
_APOSTROPHES = str.maketrans({c: "" for c in "'’ʼ´`"})

_WORD_RE = re.compile(r"[a-zəğışçöüA-ZƏĞIİŞÇÖÜ]+")


def az_lower(text: str) -> str:
    """Lowercase Azerbaijani correctly (İ→i, I→ı before the generic fold)."""
    return text.translate(_UPPER_MAP).lower()


def strip_apostrophes(text: str) -> str:
    return text.translate(_APOSTROPHES)


def syllables(word: str) -> int:
    """Syllable count of one word = its vowel count."""
    clean = az_lower(strip_apostrophes(word))
    return sum(1 for ch in clean if ch in VOWELS)


def words(line: str) -> list[str]:
    """Words of a line, punctuation dropped, apostrophes preserved inside."""
    return _WORD_RE.findall(strip_apostrophes(line))


def tokens(text: str) -> list[str]:
    """Lowercased word tokens for retrieval."""
    return [az_lower(w) for w in words(text)]
