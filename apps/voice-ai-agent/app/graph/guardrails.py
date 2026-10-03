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


# Out-of-scope gate: the council advises on life, courage, wit and wisdom out
# of a literary heritage. These are tasks it has no standing to answer at all.
# High precision, low recall on purpose - a missed one still reaches the
# supervisor prompt, which also sends non-council questions to the host, but a
# false hit would turn away someone who came for advice. Hence only unambiguous
# task phrasings, never bare topic words ("futbol", "hava", "pul" stay in scope:
# "komandam dağılır", "içimdə kədər" are council questions).
_OUT_OF_SCOPE_PATTERNS = (
    r"\b(python|javascript|typescript|java|c\+\+|sql|html|css|excel|docker|linux)\b[\w\s,.-]*\b(kod|funksiya|sıral|birləşdir|yaz|necə)",
    r"\b(kod|proqram|skript|funksiya)\w*\s+(yaz|hazırla|düzəlt)",
    r"\b(bitcoin|ethereum|kripto\w*)\b.*\b(qiymət|kurs|neçəyədir|nə qədər)",
    r"\b(dollar|avro|manat|valyuta)\w*\s+kurs",
    r"\bhava\w*\s+(necə\s+olacaq|proqnoz)|\bhava\s+proqnoz",
    r"\b(iphone|samsung|xiaomi|noutbuk|telefon)\w*\b.*\b(müqayisə|hansı\s+daha\s+yax[sş]ı)",
    r"\bvergi\s+bəyannamə",
    r"\b(resept|reseptini|bişir\w*|pizza)\b",
    r"\b(oyunda|matçda|matçın|liqada)\b.*\b(xal|hesab|nəticə|qol)",
    r"\bingilis\s+dilinə\s+tərcümə|\btərcümə\s+et\b",
    r"\btənliy\w*\s+həll|\bhəll\s+et\b.*\btənlik",
)
_OUT_OF_SCOPE = re.compile("|".join(_OUT_OF_SCOPE_PATTERNS), re.IGNORECASE | re.UNICODE)


def is_out_of_scope(text: str) -> bool:
    """True for a plain task request the council cannot ground in its sources
    (code, quotes, weather, recipes, scores, translation, tax forms)."""
    return bool(_OUT_OF_SCOPE.search(text or ""))


def crisis_response() -> str:
    return settings.CRISIS_RESPONSE_TEXT
