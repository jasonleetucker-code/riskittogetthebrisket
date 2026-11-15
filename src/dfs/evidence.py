"""Structured evidence claims from podcasts, articles and news — the deterministic core.

Whatever extracts a claim (a person, a rule, a language model) must pass it
through :func:`validate_claim`; nothing downstream reads free text.  This module
decides what a claim IS ALLOWED TO DO, and that policy is code, not prose
(owner mandate §15, DFS-§15-01):

* **Conditional** evidence ("if A is out, B starts") is inactive until its
  condition is resolved true.
* **Analyst preference** ("I love B tonight") can never carry a numeric
  projection change — it is research-only.
* A **role interval** ("32–34 minutes") is an attributed range, never an
  official allocation; it may feed role modelling only through shadow mode.
* A **popularity** claim ("everyone is playing B") is qualitative: a claim that
  arrives with an invented ownership percentage is refused.
* **Retrospective** analysis and anything published after lock is never
  pre-lock evidence.
* **Promotion / sponsorship** is never performance evidence.
* The same underlying report heard twice (host repeating a beat reporter, a
  cross-posted clip) is ONE piece of evidence: independence is counted by
  ``underlying_primary_source``, not by clip.
* Corrections and retractions supersede; nothing is deleted.

Numbers from a claim NEVER enter a production projection directly: the most a
claim can do is ``shadow`` (logged next to the model, compared later).
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

CLAIM_TYPES = (
    "confirmed_fact",
    "attributed_report",
    "role_expectation",
    "numerical_projection",
    "market_observation",
    "ownership_expectation",
    "analyst_preference",
    "leverage_recommendation",
    "strategy_hypothesis",
    "promotion",
    "speculation",
    "retrospective",
)
#: What a claim may be used for, most permissive last.  "shadow" is the ceiling
#: for any model use until an evaluated, owner-approved feature policy exists.
USES = ("excluded", "research", "field_model_shadow", "shadow")
_ALLOWED_USE: dict[str, str] = {
    "confirmed_fact": "shadow",
    "attributed_report": "shadow",
    "role_expectation": "shadow",
    "numerical_projection": "shadow",
    "market_observation": "shadow",
    "ownership_expectation": "field_model_shadow",
    "analyst_preference": "research",
    "leverage_recommendation": "research",
    "strategy_hypothesis": "research",
    "speculation": "research",
    "promotion": "excluded",
    "retrospective": "excluded",
}
_NUMERIC_OK = {
    "role_expectation",
    "numerical_projection",
    "market_observation",
    "confirmed_fact",
    "attributed_report",
}
_SAFE_ID = re.compile(r"^[0-9A-Za-z][0-9A-Za-z_\-:.]{0,99}$")


class ClaimError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class Claim:
    claim_id: str
    episode_id: str
    segment_start: float
    segment_end: float
    speaker: str | None
    claim_type: str
    athlete_ids: list[str]
    sport: str
    statistic: str | None
    value_or_range: tuple[float, float] | None
    unit: str | None
    negation: bool
    condition: str | None
    condition_resolved: bool | None  # None = unresolved
    as_of: str
    valid_until: str | None
    underlying_primary_source: str
    source_family: str
    extraction_quality: str  # publisher_transcript | asr | manual
    superseded_by: str | None = None
    retracted: bool = False
    permitted_model_use: str = "research"
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _iso(raw: Any, name: str, required: bool = True) -> str | None:
    if raw in (None, ""):
        if required:
            raise ClaimError("INVALID_CLAIM", f"{name} is required.")
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ClaimError("INVALID_CLAIM", f"{name} must be an ISO timestamp.") from exc
    if dt.tzinfo is None:
        raise ClaimError("INVALID_CLAIM", f"{name} must carry a timezone.")
    return dt.isoformat()


def validate_claim(raw: dict[str, Any]) -> Claim:
    """Schema + policy.  Refuses what the policy forbids; never 'fixes' a claim."""
    if not isinstance(raw, dict):
        raise ClaimError("INVALID_CLAIM", "A claim must be an object.")
    ctype = raw.get("claimType")
    if ctype not in CLAIM_TYPES:
        raise ClaimError("INVALID_CLAIM", f"claimType must be one of {CLAIM_TYPES}.")
    for key in ("claimId", "episodeId", "underlyingPrimarySource", "sourceFamily"):
        if not isinstance(raw.get(key), str) or not _SAFE_ID.match(raw[key]):
            raise ClaimError("INVALID_CLAIM", f"{key} must be a safe identifier.")
    start, end = raw.get("segmentStart"), raw.get("segmentEnd")
    if (
        not all(
            isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0 for v in (start, end)
        )
        or end < start
    ):
        raise ClaimError(
            "INVALID_CLAIM", "segmentStart/segmentEnd must be seconds with end ≥ start."
        )
    quality = raw.get("extractionQuality")
    if quality not in ("publisher_transcript", "asr", "manual"):
        raise ClaimError(
            "INVALID_CLAIM", "extractionQuality must be publisher_transcript, asr or manual."
        )
    athletes = raw.get("athleteIds") or []
    if not isinstance(athletes, list) or not all(
        isinstance(a, str) and _SAFE_ID.match(a) for a in athletes
    ):
        raise ClaimError(
            "INVALID_CLAIM",
            "athleteIds must be resolved canonical IDs (ambiguous names are quarantined upstream).",
        )
    value = raw.get("valueOrRange")
    rng: tuple[float, float] | None = None
    if value is not None:
        if ctype not in _NUMERIC_OK:
            # "I love B tonight" may not arrive with "+4 points"; "everyone is
            # playing B" may not arrive with "35%".
            raise ClaimError(
                "NUMBER_NOT_PERMITTED",
                f"A {ctype.replace('_', ' ')} claim cannot carry a number — that would fabricate a quantity the speaker did not state.",
            )
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            rng = (float(value), float(value))
        elif (
            isinstance(value, list)
            and len(value) == 2
            and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in value)
            and value[0] <= value[1]
        ):
            rng = (float(value[0]), float(value[1]))
        else:
            raise ClaimError("INVALID_CLAIM", "valueOrRange must be a number or [low, high].")
        if not raw.get("statistic") or not raw.get("unit"):
            raise ClaimError("INVALID_CLAIM", "A numeric claim needs its statistic and unit.")
    condition = raw.get("condition")
    resolved = raw.get("conditionResolved")
    if resolved not in (True, False, None):
        raise ClaimError("INVALID_CLAIM", "conditionResolved must be true, false or null.")
    claim = Claim(
        claim_id=raw["claimId"],
        episode_id=raw["episodeId"],
        segment_start=float(start),
        segment_end=float(end),
        speaker=(str(raw["speaker"])[:80] if raw.get("speaker") else None),
        claim_type=ctype,
        athlete_ids=list(athletes),
        sport=str(raw.get("sport") or ""),
        statistic=(str(raw["statistic"])[:60] if raw.get("statistic") else None),
        value_or_range=rng,
        unit=(str(raw["unit"])[:30] if raw.get("unit") else None),
        negation=bool(raw.get("negation")),
        condition=(str(condition)[:200] if condition else None),
        condition_resolved=resolved if condition else None,
        as_of=_iso(raw.get("asOf"), "asOf"),
        valid_until=_iso(raw.get("validUntil"), "validUntil", required=False),
        underlying_primary_source=raw["underlyingPrimarySource"],
        source_family=raw["sourceFamily"],
        extraction_quality=quality,
        superseded_by=raw.get("supersededBy"),
        retracted=bool(raw.get("retracted")),
    )
    claim.permitted_model_use = _ALLOWED_USE[ctype]
    if (
        claim.extraction_quality == "asr"
        and claim.permitted_model_use == "shadow"
        and claim.negation is False
    ):
        claim.notes.append(
            "ASR text: negation and numbers need human confirmation before any model use."
        )
    return claim


def active_use(
    claim: Claim, *, decision_time: str, lock_time: str | None = None
) -> tuple[str, str]:
    """What this claim may do AT a decision time.  Returns (use, reason)."""
    t = datetime.fromisoformat(decision_time)
    as_of = datetime.fromisoformat(claim.as_of)
    if claim.retracted:
        return "excluded", "retracted"
    if claim.superseded_by:
        return "excluded", f"superseded by {claim.superseded_by}"
    if as_of > t:
        return "excluded", "not yet published at the decision time (no look-ahead)"
    if lock_time and as_of > datetime.fromisoformat(lock_time):
        return "excluded", "published after lock: not pre-lock evidence"
    if claim.valid_until and datetime.fromisoformat(claim.valid_until) < t:
        return "excluded", "expired"
    if claim.condition and claim.condition_resolved is not True:
        return "research", "conditional: inactive until its condition is resolved true"
    return claim.permitted_model_use, "policy"


def independent_support(claims: list[Claim]) -> dict[str, Any]:
    """How many INDEPENDENT reports back the same statement — counted by primary source, not clip."""
    live = [c for c in claims if not c.retracted and not c.superseded_by]
    primaries = sorted({c.underlying_primary_source for c in live})
    families = sorted({c.source_family for c in live})
    return {"clips": len(live), "independentReports": len(primaries), "sourceFamilies": families}
