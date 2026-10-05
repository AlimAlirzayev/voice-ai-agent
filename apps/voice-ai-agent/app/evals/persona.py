"""Rubric scorers for one council reply: language, persona fidelity, grounding.

Deterministic on purpose - they run in CI with no key and give the same verdict
every time. They encode the rules the prompts already promise
(`DIVAN_QAYDALARI` in `app/prompts/divan.py`): clean Azerbaijani, no modern
self-help calques, no anachronism, only your own form of address, and no
quotation that is not in the advisor's sources. What they cannot judge (is it
*alive*, is the advice good) is left to the LLM judge in `app/evals/judge.py`.

`fails` break the build; `warns` are reported and tracked.
"""

from __future__ import annotations

import re
from functools import lru_cache

from app.evals.audit import az_lower, deterministic_checks

# Rule 3: "your world has no telephone, salary, customer, business, paper-plan".
ANACHRONISMS = (
    "telefon", "maaş", "müştəri", "biznes", "internet", "kompüter", "mobil", "proqram",
    "email", "ofis", "menecer", "startap", "investisiya", "sosial şəbəkə",
)
# Rule 1: translation-smelling idioms the prompts name explicitly.
CALQUES = (
    "öz içinə qulaq as", "nəfəs al", "özünə tapşırıq ver", "kağıza yaz", "addım at",
    "konkret", "özünü sev", "komfort zonası", "sərhədlərini müəyyən et",
)
# The persona must never speak as a machine (the audit's whole-word list misses
# "modeliyəm"/"intellektəm": Azerbaijani hangs its endings on the stem).
MACHINE_STEMS = ("süni intellekt", "dil model", "llm", "chatbot", "neyron şəbək", "openai", "anthropic", "chatgpt")
# Rule 4: each member's own forms of address (from `_VOICE`).
ADDRESS = {
    "nesreddin": ("ay qardaş", "a kişi", "ay bala"),
    "koroglu": ("igid", "qardaş", "dəli"),
    "simurg": ("ey yolçu", "balam"),
    "nesimi": ("ey can", "ey dost", "ey könül"),
    "dedeqorqud": ("oğul", "xanım hey", "bəylər"),
    "nizami": ("ey dil", "ey yar", "əzizim"),
}
# Lines the prompts themselves bless as verified against the corpus.
VERIFIED_LINES = (
    "Məndə sığar iki cahan, mən bu cahana sığmazam",
    "Yerli qara dağların yıxılmasın, kölgəlicə qaba ağacın kəsilməsin, qamın axan görklü suyun qurumasın",
)
_QUOTE = re.compile(r"«([^»]{12,})»")
_NON_LETTER = re.compile(r"[^a-zəğışçöü]+")


def _norm(text: str) -> str:
    return _NON_LETTER.sub(" ", az_lower(text)).strip()


@lru_cache(maxsize=1)
def _corpus_norm() -> tuple[str, ...]:
    from app.rag.ingest import collect_chunks

    return tuple(_norm(c["text"]) for c in collect_chunks())


def _has_phrase(text: str, phrase: str, *, stem: bool = False) -> bool:
    """Whole-word phrase match; `stem=True` lets endings follow ("telefonla")."""
    tail = "" if stem else r"(?![a-zəğışçöü])"
    return re.search(rf"(?<![a-zəğışçöü]){re.escape(_norm(phrase))}{tail}", _norm(text)) is not None


def forbidden_address(advisor: str) -> tuple[str, ...]:
    """Forms of address that belong to the other members and not to this one."""
    own = set(ADDRESS.get(advisor, ()))
    return tuple(sorted({f for key, forms in ADDRESS.items() if key != advisor for f in forms} - own))


def unsupported_quotes(reply: str, evidence: list[dict] | None = None) -> list[str]:
    """«…» spans of three or more words that appear in no source: not in the
    corpus, not in the passages retrieved for this turn, not a verified line."""
    allowed = [_norm(line) for line in VERIFIED_LINES]
    allowed += [_norm(e.get("text", "")) for e in evidence or []]
    corpus = _corpus_norm()
    bad = []
    for span in _QUOTE.findall(reply):
        needle = _norm(span)
        if len(needle.split()) < 3:
            continue
        if any(needle in hay for hay in allowed) or any(needle in hay for hay in corpus):
            continue
        bad.append(span.strip())
    return bad


def score_reply(case: dict, reply: str, evidence: list[dict] | None = None) -> dict:
    """Score one reply. `case` needs `advisor`; may carry `lang` and `max_sentences`."""
    advisor = case["advisor"]
    base = deterministic_checks(
        {"expect": advisor, "lang": case.get("lang", "az"), "max_sentences": case.get("max_sentences", 3)},
        reply, [advisor], [],
    )
    fails, warns = list(base["fails"]), list(base["warns"])

    found = [w for w in ANACHRONISMS if _has_phrase(reply, w, stem=True)]
    if found:
        fails.append("anaxronizm: " + ", ".join(found))
    calques = [c for c in CALQUES if _has_phrase(reply, c, stem=True)]
    if calques:
        fails.append("tərcümə kalkası: " + ", ".join(calques))
    machine = [m for m in MACHINE_STEMS if _has_phrase(reply, m, stem=True)]
    if machine:
        fails.append("maşın kimi danışır: " + ", ".join(machine))
    quotes = unsupported_quotes(reply, evidence)
    if quotes:
        fails.append("mənbəsiz sitat: " + " | ".join(q[:60] for q in quotes))
    foreign = [f for f in forbidden_address(advisor) if _has_phrase(reply, f)]
    if foreign:
        warns.append("başqasının xitabı: " + ", ".join(foreign))
    return {"fails": fails, "warns": warns, "sentences": base["sentences"]}
