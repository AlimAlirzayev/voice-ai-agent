"""Strip print-edition apparatus from the advisors' corpus (idempotent).

The Dədə Qorqud texts came from a scanned edition via Vikimənbə and carry the
edition's own machinery inside the prose: Drezden line numbers ("... 5 bindin"),
page marks ("D67", "AV-3"), digits glued to words ("Bay4börə"), words broken at
a line end ("ye- rin"), footnote stars and editor's notes ("...Ensiklopediyada
“derlər” gedib. - Red."). None of it is the classic's words, and the council
reads quotes aloud, so it goes. Genuine OCR misreadings inside a word
("Baymdır" for "Bayındır") are left alone: fixing those needs a dictionary,
and a wrong guess would put words in a classic's mouth.

    python scripts/clean_corpus.py [--check]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

CORPUS = Path(__file__).resolve().parent.parent / "app" / "rag" / "corpus"
L = "A-Za-zƏəĞğİıÖöŞşÇçÜüÂâ"

RULES: list[tuple[str, str]] = [
    # editor's notes, always closed by "- Red."
    (r"\d*Bu rəqəm Drezden[^\n]*?- Red\.", ""),
    (r"Ensiklopediyada[^\n]*?- Red\.", ""),
    # OCR junk tokens carrying # (Aaf#l); a footnote star glued to a word
    # (göründü*.) loses only the star; "* * *" stanza dividers stay
    (r"\S*#\S*", ""),
    (r"\S*\*{2}\S*", ""),
    (r"(?<=\S)\*", ""),
    # page / folio marks: D67, AV-3, AV-3-
    (r"\b[A-Z]{1,3}-?\d+-?(?=\s|$|[" + L + "])", ""),
    # digits glued inside or onto a word: Bay4börə, dur6mışdı, 1çuxasıyla, oxunu29
    (r"(?<=[" + L + r"])\d+(?=[" + L + r"])", ""),
    (r"(?<!\S)\d+(?=[" + L + r"])", ""),
    (r"(?<=[" + L + r"])\d+(?=[\s.,;:!?…”\"]|$)", ""),
    # numbers wedged against punctuation: “7 Bunda, Qanlu8-qanlu, §8, (12)
    (r"§\d*", ""),
    (r"(?<=[“\"(«])\d+\s?", ""),
    (r"(?<=[" + L + r"])\d+(?=-)", ""),
    (r"\d+(?=[”»)])", ""),
    (r"(?<=-)\d+", ""),
    (r"(?<=[.,;:!?])\d+", ""),
    (r"(?<!\S)\d+(?=[.,;:!?])", ""),
    # free-standing line / page numbers
    (r"(?<!\S)\d+(?!\S)", ""),
    # last resort: the verse and prose of these classics hold no numerals at
    # all (measured: every digit left after the rules above was apparatus or
    # OCR garbage like "SşfSl3'"), so a token still carrying one goes whole
    (r"\S*\d\S*", ""),
    (r"[ \t]{2,}", " "),
]

BROKEN = re.compile(r"([" + L + r"]+)- ([" + L.replace("A-Z", "").replace("ƏĞİÖŞÇÜÂ", "") + r"a-z]+)")


def _vocab() -> set[str]:
    """Every word the corpus spells whole somewhere - the dictionary a broken
    word is checked against."""
    words: set[str] = set()
    for path in CORPUS.rglob("*.txt"):
        words.update(w.lower() for w in re.findall(r"(?<![-" + L + r"])[" + L + r"]+(?![-" + L + r"])",
                                                   path.read_text(encoding="utf-8")))
    return words


VOCAB: set[str] = set()


def _join(m: re.Match) -> str:
    left, right = m.group(1), m.group(2)
    if (left + right).lower() in VOCAB:          # gördü- gində -> gördügində
        return left + right
    if right.lower() in VOCAB and left.lower() in VOCAB:
        return f"{left}-{right}"                 # a real compound: ölməgə-yitməgə
    if len(left) <= 3 or len(right) <= 3:        # a syllable torn off: ye- rin
        return left + right
    return f"{left}-{right}"


def clean_body(text: str) -> str:
    """Apply the rules until nothing changes: removing a page mark can expose
    a second broken word, so one pass is not always a fixpoint."""
    while True:
        new = _clean_once(text)
        if new == text:
            return new
        text = new


def _clean_once(text: str) -> str:
    for pat, rep in RULES:
        text = re.sub(pat, rep, text)
    text = BROKEN.sub(_join, text)
    text = re.sub(r" +([.,;:!?])", r"\1", text)
    return re.sub(r"[ \t]+\n", "\n", text)


def clean_file(path: Path) -> tuple[str, str]:
    raw = path.read_text(encoding="utf-8")
    head, body = [], []
    lines = raw.splitlines(keepends=True)
    i = 0
    while i < len(lines) and (lines[i].startswith("#") or not lines[i].strip()):
        head.append(lines[i]); i += 1
    body = "".join(lines[i:])
    return raw, "".join(head) + clean_body(body)


def main() -> int:
    check = "--check" in sys.argv
    VOCAB.update(_vocab())
    dirty = 0
    for path in sorted(CORPUS.rglob("*.txt")):
        raw, new = clean_file(path)
        if raw != new:
            dirty += 1
            print(f"{'would clean' if check else 'cleaned'}: {path.relative_to(CORPUS)}")
            if not check:
                path.write_text(new, encoding="utf-8")
    return 1 if (check and dirty) else 0


if __name__ == "__main__":
    raise SystemExit(main())
