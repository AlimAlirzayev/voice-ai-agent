"""Safety guardrail in front of the Divan council.

Not a course-lesson topic - a baseline any real, publicly-reachable AI
product needs regardless: some inputs must never be routed to a roleplaying
historical persona, however well-intentioned that persona is, and must
instead get a direct, human, non-in-character response pointing to real
help. Koroğlu cheerfully saying "be brave" to someone expressing suicidal
intent would be actively harmful - so this check runs *before* the council
is ever consulted, and short-circuits it entirely.

Deterministic keyword matching, not an LLM call: zero cost, zero latency,
zero risk of the check itself being "talked out of" firing, and it is
multilingual because the product's users are (Azerbaijani/English/Russian/
Turkish, matching the system prompt's own language promise).
"""

import re

from app.core.config import settings

_SELF_HARM_PATTERNS = (
    r"\bintihar",
    r"\böz[uü]m[uü] öld[uü]r",
    r"\böz[uü]m[əe] qıy",
    r"\byaşamaq istəmirəm",
    r"\bhəyatıma son",
    r"\bart[ıi]q yaşamaq istəmirəm",
    r"\bsuicid",
    r"\bkill myself",
    r"\bend my life",
    r"\bwant to die\b",
    r"\bself[\s-]?harm",
    r"\bсамоубийств",
    r"\bпокончить с собой",
    r"\bне хочу жить",
    r"\bintihar etmek",
    r"\bkendimi öldür",
    r"\bcanıma kıy",
)
_PATTERN = re.compile("|".join(_SELF_HARM_PATTERNS), re.IGNORECASE | re.UNICODE)


def is_self_harm_risk(text: str) -> bool:
    """Deliberately high-recall, low-precision: a false positive costs one
    honest safety message; a false negative costs far more."""
    return bool(_PATTERN.search(text or ""))


def crisis_response() -> str:
    return settings.CRISIS_RESPONSE_TEXT
