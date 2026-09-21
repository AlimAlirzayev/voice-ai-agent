"""Heca vəzni (syllabic metre) analysis — deterministic, LLM-free.

What a real metre check is, and what a vowel counter is not
-----------------------------------------------------------
Counting vowels tells you a line has eleven syllables. It does NOT tell you
the line is a qoşma. Syllabic Azerbaijani verse is defined by the count AND
the bölgü — the caesura that must fall on a word boundary:

    11 heca : 6+5, 4+4+3      (qoşma, təcnis)
     8 heca : 4+4, 5+3, 3+5   (gəraylı, the qoşma of the dastans)
     7 heca : 4+3, 3+4        (bayatı)

A split falling inside a word is not a bölgü, so the check is decidable:
can the line be cut at word boundaries on exactly those syllable offsets?
That is what separates this from a vowel counter.

MEASURED ON REAL VERSE, not assumed: the secondary patterns above are in the
table because the fixtures demanded them. Koroğlu's own «Bu gələn Eyvaz, bu
gələn» is 5+3, not 4+4, and «Dili dodağıyı yeyim» (2+4+2 syllables per word)
honours NO canonical bölgü at all — in real folk verse some lines simply do
not, so the report gives a ratio per stanza instead of a binary verdict. A
tool that called that line broken would be wrong about the poem, not about
the line.

KNOWN LIMIT, flagged rather than hidden: the apostrophe of Arabic/Persian
loans usually marks a lengthened vowel inside one syllable (`mə'na` = 2) but
sometimes stands in for a dropped vowel (`şe'r` = şeir = 2 syllables, one
written vowel). Vowel counting gets the first right and the second wrong, so
any line containing an apostrophe is flagged `apostrof` and its count is
reported as needing a human eye. Silence there would be a wrong number
delivered confidently.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from az_text import VOWELS, az_lower, strip_apostrophes, syllables, words

BOLGU_PATTERNS: dict[int, tuple[tuple[int, ...], ...]] = {
    7: ((4, 3), (3, 4)),
    8: ((4, 4), (5, 3), (3, 5)),
    11: ((6, 5), (4, 4, 3)),
}

FORM_NAMES: dict[int, str] = {
    7: "bayatı (7 heca)",
    8: "gəraylı / dastan qoşması (8 heca)",
    11: "qoşma (11 heca)",
}

_APOSTROPHE_CHARS = "'’ʼ´`"


def _boundaries(pattern: tuple[int, ...]) -> set[int]:
    """Cumulative syllable offsets the pattern requires a word to end on."""
    out, running = set(), 0
    for part in pattern[:-1]:
        running += part
        out.add(running)
    return out


def bolgu_for(line: str) -> list[str]:
    """Every canonical bölgü this line actually honours, as 'a+b' strings."""
    parts = [syllables(w) for w in words(line)]
    total = sum(parts)
    reachable, running = set(), 0
    for count in parts:
        running += count
        reachable.add(running)
    return [
        "+".join(str(p) for p in pattern)
        for pattern in BOLGU_PATTERNS.get(total, ())
        if _boundaries(pattern) <= reachable
    ]


def rhyme_key(line: str) -> str:
    """The rhyme unit: the line's last vowel and everything after it.

    Deliberately shallow and stated as such — it captures the -ən of «gələn»
    and the -ur of «yoxdur», which is what a syllabic scheme is read on. A
    deeper key starts matching words that merely end alike.
    """
    line_words = words(line)
    if not line_words:
        return ""
    last = az_lower(strip_apostrophes(line_words[-1]))
    for i in range(len(last) - 1, -1, -1):
        if last[i] in VOWELS:
            return last[i:]
    return last


def rhyme_scheme(lines: list[str]) -> str:
    """Letter scheme: a bayatı reads 'aaba', a qoşma stanza 'abcb'."""
    seen: dict[str, str] = {}
    out: list[str] = []
    for line in lines:
        key = rhyme_key(line)
        if key not in seen:
            seen[key] = chr(ord("a") + len(seen))
        out.append(seen[key])
    return "".join(out)


@dataclass
class LineReport:
    text: str
    heca: int
    bolgu: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)


@dataclass
class HecaReport:
    """The verdict. `form` is named only when every line carries the same
    count — naming a form over ragged lines would be the tool lying. The
    bölgü result is a RATIO, because real folk stanzas contain lines that
    honour no canonical caesura."""

    lines: list[LineReport]
    metre: int | None
    consistent: bool
    form: str | None
    bolgu_lines: int
    bolgu_ratio: float
    rhyme: str
    stanzas: list[str]
    flagged: int = 0
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def analyse(text: str) -> HecaReport:
    raw_lines = text.splitlines()
    verse = [ln.strip() for ln in raw_lines if ln.strip()]
    if not verse:
        return HecaReport([], None, False, None, 0, 0.0, "", [], 0, "boş mətn")

    reports: list[LineReport] = []
    for line in verse:
        flags = ["apostrof"] if any(c in line for c in _APOSTROPHE_CHARS) else []
        reports.append(
            LineReport(line, sum(syllables(w) for w in words(line)), bolgu_for(line), flags)
        )

    counts = {r.heca for r in reports}
    consistent = len(counts) == 1
    metre = reports[0].heca if consistent else None
    form = FORM_NAMES.get(metre) if metre is not None else None
    with_bolgu = sum(1 for r in reports if r.bolgu)
    flagged = sum(1 for r in reports if r.flags)

    stanzas: list[str] = []
    current: list[str] = []
    for line in raw_lines:
        if line.strip():
            current.append(line.strip())
        elif current:
            stanzas.append(rhyme_scheme(current))
            current = []
    if current:
        stanzas.append(rhyme_scheme(current))

    notes: list[str] = []
    if not consistent:
        notes.append("hecalar bərabər deyil — vəzn adlandırılmır")
    if with_bolgu < len(reports):
        notes.append(f"{len(reports) - with_bolgu} misrada kanonik bölgü yoxdur")
    if flagged:
        notes.append(f"{flagged} misrada apostrof var — heca sayı insan gözü istəyir")

    return HecaReport(
        lines=reports,
        metre=metre,
        consistent=consistent,
        form=form,
        bolgu_lines=with_bolgu,
        bolgu_ratio=round(with_bolgu / len(reports), 3),
        rhyme=rhyme_scheme(verse),
        stanzas=stanzas,
        flagged=flagged,
        note="; ".join(notes),
    )


def render(text: str) -> str:
    """Human-readable verdict — what an agent receives back from the tool."""
    report = analyse(text)
    if not report.lines:
        return "Boş mətn — ölçüləcək misra yoxdur."
    head = (
        f"Vəzn: {report.form}"
        if report.form
        else f"Vəzn adlandırılmır (hecalar: {'/'.join(str(r.heca) for r in report.lines)})"
    )
    body = "\n".join(
        f"  {r.heca:>2} heca · bölgü {'/'.join(r.bolgu) if r.bolgu else 'yoxdur'}"
        f"{' · ⚠ apostrof' if r.flags else ''} · {r.text}"
        for r in report.lines
    )
    tail = f"Bölgü: {report.bolgu_lines}/{len(report.lines)} misrada · Qafiyə: {report.rhyme}"
    if report.stanzas:
        tail += f" (bəndlər: {', '.join(report.stanzas)})"
    if report.note:
        tail += f"\nQeyd: {report.note}"
    return f"{head}\n{body}\n{tail}"
