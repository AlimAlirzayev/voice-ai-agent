"""Second, broader safety net in front of the Divan council - alongside, not
instead of, the deterministic self-harm keyword check in
`app/graph/guardrails.py`.

That check is narrow on purpose: it only catches self-harm language, by
design (see its own docstring for why that stays keyword-based and
deterministic). It says nothing about, say, a request for step-by-step help
committing a clearly illegal act, or content a public AI product should not
casually engage with under any persona - hate speech, graphic violence,
sexual content involving minors, and similar categories a real, purpose-built
classifier is more robust at catching than another hand-rolled keyword list
would be.

OpenAI's moderation endpoint (`omni-moderation-latest` by default - see
`Settings.MODERATION_MODEL`) is a good fit: it is free/cheap, fast, and
already backed by the same `openai` package this app uses for Whisper and
TTS (`app/services/voice.py`). This module only ever moderates the
*incoming user message*, before it is routed to the council - never the
council's own (in-character) reply - so it cannot fire because a legendary
persona like Koroğlu or Nəsimi is being roleplayed; that is this product's
intentional design and is not something the moderation model is even asked
to judge.

Deliberately excluded, on purpose, after investigation - NOT because it
doesn't matter, but because getting it right needs more than what fits
safely here:

* Impersonation of a real, specific, living person in a defamatory or
  harmful way. OpenAI's moderation categories (hate, harassment, violence,
  sexual, self-harm, illicit) have no "impersonation" category at all - this
  would need a separate, carefully-scoped classifier (likely an LLM call
  asking specifically "is this asking to impersonate a real living person",
  distinct from "is this the product's own historical/legendary persona
  roleplay"). Hand-rolling that distinction with the time available here
  risks either missing real impersonation requests or, worse, misfiring on
  the product's own Koroğlu/Nəsimi/Simurğ/etc. roleplay - which would break
  the product. Recommended as separate future work; see the task report.

Categories included below are deliberately a narrow subset of everything the
model can flag - only ones a public AI advisor product must never engage
with under any persona, regardless of severity. Plain (non-threatening,
non-graphic) `hate`/`harassment`/`violence`/`sexual` are *not* included: at
low severity those are exactly the kind of pointed, sometimes blunt language
a legendary folk-hero advisor (Koroğlu, in particular) can plausibly be
asked about without it being a real safety issue, and this module only ever
sees the user's own words - being trigger-happy there would start rejecting
ordinary questions.

Fails OPEN: any error moderating a message (missing key, network blip,
timeout, API error, retries exhausted) is logged and treated as "not
flagged". A moderation-service hiccup must never block a legitimate user
message as a side effect of an unrelated infrastructure problem. This is
intentionally different from `is_self_harm_risk`, which is local/
deterministic and needs no such fallback because it never talks to a
network at all.
"""

import logging

from openai import AsyncOpenAI

from app.core.config import settings
from app.services.retry import call_with_retry

log = logging.getLogger(__name__)

# Category attribute names from `openai.types.moderation.Categories` (see
# `_is_flagged`) - a message trips the gate if *any* of these are true.
_BLOCKING_CATEGORIES = (
    "sexual_minors",
    "illicit",
    "illicit_violent",
    "violence_graphic",
    "hate_threatening",
    "harassment_threatening",
)

MODERATION_FALLBACK_TEXT = (
    "Bu tələbi qarşılaya bilmirəm - fərqli bir sualla yenidən cəhd edin."
)


def _client() -> AsyncOpenAI | None:
    """Built fresh on every call rather than `lru_cache`d like
    `app/services/voice.py`'s equivalents: this module is on the safety-check
    path, so it must always reflect the *current* `OPENAI_API_KEY` (e.g. a
    test flipping it from empty to set, or an operator rotating it) rather
    than risk silently moderating with (or failing open because of) a stale
    cached client. Constructing an `AsyncOpenAI` instance does no network
    I/O, so this costs nothing per call."""
    if not settings.OPENAI_API_KEY:
        return None
    return AsyncOpenAI(api_key=settings.OPENAI_API_KEY)


def _is_flagged(categories) -> bool:
    return any(getattr(categories, name, False) for name in _BLOCKING_CATEGORIES)


async def is_disallowed_content(text: str) -> bool:
    """Best-effort secondary safety net using OpenAI's moderation model.

    Returns False (never blocks) when moderation is disabled
    (`Settings.MODERATION_ENABLED`), when there is no `OPENAI_API_KEY`
    configured, when the text is empty, or when the moderation call itself
    fails for any reason - see module docstring for why this fails open.
    """
    text = (text or "").strip()
    if not settings.MODERATION_ENABLED or not text:
        return False

    client = _client()
    if client is None:
        return False

    try:
        response = await call_with_retry(
            lambda: client.moderations.create(model=settings.MODERATION_MODEL, input=text),
            label="moderation",
        )
    except Exception as exc:  # noqa: BLE001 - must never block on infra hiccups
        log.warning("Moderation check failed, failing open: %s", exc)
        return False

    if not response.results:
        return False

    return _is_flagged(response.results[0].categories)
