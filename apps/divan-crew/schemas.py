"""The structured verdict the Divan crew must produce (`output_pydantic`).

This is the lesson's structured-output requirement, and it also closes a real
defect in the running product. `app/graph/builder.py` picks the next advisor
with `raw.split()[0]` and, when that token is not a roster key, falls back to
`remaining[0]` — so a model that answers «Bilmirəm» or emits an empty string
routes the question to whichever advisor happens to be first in the dict, and
nothing anywhere says that happened. A silent wrong route is worse than a
loud failure, because it produces a confident answer from the wrong member.

`parse_advisor_token` is the strict replacement: it accepts a roster key or
the closing token, and RAISES on anything else.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator

try:  # the roster is the single source of truth, imported never copied
    from app.prompts.divan import ROSTER

    ADVISOR_KEYS = tuple(ROSTER.keys())
except Exception:  # noqa: BLE001 - keeps the schema importable in isolation
    ADVISOR_KEYS = ("nesreddin", "koroglu", "simurg", "nesimi", "dedeqorqud", "nizami")

CLOSING_TOKEN = "YEKUN"
MAX_CONSULTED = 2
APPROVAL_ADVISOR = "koroglu"


class RoutingError(ValueError):
    """The supervisor said something that is not a routing decision."""


def parse_advisor_token(raw: str) -> str:
    """Return a roster key or 'YEKUN'. Raise on anything else.

    The whole point is the absence of a fallback: there is no 'pick the first
    remaining advisor' branch here, because that branch is how a routing
    failure turns into a plausible answer from the wrong member.
    """
    if raw is None:
        raise RoutingError("supervisor returned nothing")
    token = re.sub(r"[^\w]", "", str(raw).strip().split()[0] if str(raw).strip() else "")
    lowered = token.lower()
    if lowered in ADVISOR_KEYS:
        return lowered
    if lowered.startswith("yek"):
        return CLOSING_TOKEN
    raise RoutingError(f"not a routing decision: {raw!r}")


class Citation(BaseModel):
    """A passage a member actually leaned on. `retrieval` names HOW it was
    found, so a BM25 hit is never read as an embedding hit."""

    advisor: str
    work: str
    ref: str
    quote: str
    source: str = ""
    retrieval: str = Field("bm25", description="bm25 | embedding")


class Opinion(BaseModel):
    advisor: str
    name: str
    text: str

    @field_validator("advisor")
    @classmethod
    def known_advisor(cls, value: str) -> str:
        if value not in ADVISOR_KEYS:
            raise ValueError(f"unknown advisor key: {value!r}")
        return value


class MetreCheck(BaseModel):
    """Only present when a member produced verse and the metre tool ran."""

    metre: int | None = None
    form: str | None = None
    bolgu_ratio: float = 0.0
    rhyme: str = ""
    note: str = ""


class DivanVerdict(BaseModel):
    """What one council run returns. Deliberately strict: an unknown advisor
    key, an over-long roster or a missing verdict fails here rather than
    downstream."""

    question: str
    consulted: list[str] = Field(default_factory=list, max_length=MAX_CONSULTED)
    opinions: list[Opinion] = Field(default_factory=list)
    verdict: str = Field(..., min_length=1)
    needs_approval: bool = False
    citations: list[Citation] = Field(default_factory=list)
    metre: MetreCheck | None = None

    @field_validator("consulted")
    @classmethod
    def known_and_unique(cls, value: list[str]) -> list[str]:
        for key in value:
            if key not in ADVISOR_KEYS:
                raise ValueError(f"unknown advisor key: {key!r}")
        if len(set(value)) != len(value):
            raise ValueError("the same advisor was consulted twice")
        return value

    def with_approval_rule(self) -> "DivanVerdict":
        """Koroğlu's bold advice is the one that pauses for a human — the same
        rule the LangGraph HITL gate applies, kept identical on purpose."""
        self.needs_approval = APPROVAL_ADVISOR in self.consulted
        return self
