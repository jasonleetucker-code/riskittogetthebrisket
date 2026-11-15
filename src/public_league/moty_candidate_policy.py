"""Owner Decision 12 — interim rules for the unified Manager of the Year CANDIDATE.

The OFFICIAL Manager of the Year is ``awards._manager_of_the_year_scores``
(30% final finish, 25% win%, 15% points for, 15% trade, 15% waiver) and it alone
decides the award card and the race.  Decision 12 (2026-10-18) keeps it that
way for 2024, 2025 and 2026 and keeps the owner's unified method
(``0.40·A + 0.25·T + 0.15·W + 0.10·D + 0.10·P``, owner decision 2026-09-28) a
**validation-only candidate**.  The candidate's implementation lives on the
unmerged PR #1513, not on ``main``; this module is the ``main``-side owner of the
rules any candidate presentation must obey, so the candidate cannot reach a
surface without them:

* label ``validation-only candidate``, promotion ``not_promoted``;
* the approved weights, unchanged and never rescaled;
* a component without its required evidence is ``UNAVAILABLE`` (or ``PARTIAL``
  when materially incomplete), never a zero, and its weight is NOT redistributed;
* no definitive 100-point score unless every component is ``COMPLETE``; instead
  measured points out of the measurable maximum plus the explicit range of
  totals the unmeasured weight could still produce, and the managers that range
  leaves able to finish first;
* a trade component is complete only when every trade is valued at decision
  time (both halves); a trade moving FAAB is unvalued (no defensible conversion);
  a season with no trades is complete by construction (never penalized);
* only point-in-time-knowable values and prior-period / out-of-sample draft
  expectations are admissible; unknown dropped-player production stays unknown;
* the earliest season that could become official is 2027, and only through the
  normal promotion gates — this module never promotes anything.

Nothing in the official award path imports this module
(``tests/public_league/test_moty_d12_interim_rules.py`` pins that).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Mapping

CANDIDATE_LABEL = "validation-only candidate"
PROMOTION_STATE = "not_promoted"
EARLIEST_ELIGIBLE_OFFICIAL_SEASON = 2027

#: Owner decision 2026-09-28, unchanged by Decision 12.  Award policy, not fitted.
APPROVED_WEIGHTS: Mapping[str, float] = {"A": 0.40, "T": 0.25, "W": 0.15, "D": 0.10, "P": 0.10}

COMPLETE = "COMPLETE"
PARTIAL = "PARTIAL"
UNAVAILABLE = "UNAVAILABLE"
_STATES = (COMPLETE, PARTIAL, UNAVAILABLE)


@dataclass(frozen=True)
class ComponentEvidence:
    """One candidate component.  ``score`` is 0–100 and present only when measured."""

    key: str
    state: str
    score: float | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.key not in APPROVED_WEIGHTS:
            raise ValueError(f"unknown MOTY component {self.key!r}")
        if self.state not in _STATES:
            raise ValueError(f"unknown component state {self.state!r}")
        if self.state == UNAVAILABLE and self.score is not None:
            raise ValueError(f"{self.key}: an UNAVAILABLE component carries no score")
        if self.state == COMPLETE and self.score is None:
            raise ValueError(f"{self.key}: a COMPLETE component needs its score")
        if self.state != COMPLETE and not self.reason:
            raise ValueError(f"{self.key}: a {self.state} component names its reason")
        if self.score is not None and not 0.0 <= float(self.score) <= 100.0:
            raise ValueError(f"{self.key}: score outside 0–100")


def trade_component_state(
    *, trades: int, valued_at_decision_time: int, faab_trades: int = 0
) -> tuple[str, str | None]:
    """``(state, reason)`` for T.  No trades is complete; any unvalued trade is not."""
    if trades < 0 or valued_at_decision_time < 0 or faab_trades < 0:
        raise ValueError("counts are non-negative")
    if trades == 0:
        return COMPLETE, None
    if faab_trades > 0:
        return UNAVAILABLE, "faab_transfer_unpriced"
    if valued_at_decision_time < trades:
        return UNAVAILABLE, "trade_decision_time_value_incomplete"
    return COMPLETE, None


def waiver_component_state(
    *, faab_spent_unpriced: bool, dropped_players_unknown: int
) -> tuple[str, str | None]:
    """``(state, reason)`` for W: unpriced FAAB or unknown dropped production is partial."""
    if dropped_players_unknown > 0:
        return PARTIAL, "dropped_player_production_unknown"
    if faab_spent_unpriced:
        return PARTIAL, "faab_unpriced"
    return COMPLETE, None


def value_is_point_in_time(observed_at: datetime, decision_at: datetime) -> bool:
    """A historical value is admissible only if it was knowable at the decision."""
    return observed_at <= decision_at


def draft_expectation_is_out_of_sample(fit_seasons: Iterable[int], evaluated_season: int) -> bool:
    """A draft expectation must be fitted on prior periods only."""
    seasons = list(fit_seasons)
    return bool(seasons) and all(int(s) < int(evaluated_season) for s in seasons)


def candidate_presentation(season: int, components: Iterable[ComponentEvidence]) -> dict[str, Any]:
    """How a candidate may be shown for one manager-season.

    A missing component is ``UNAVAILABLE``.  ``definitiveScore`` exists only when
    every component is ``COMPLETE``; otherwise ``measuredPoints`` (complete
    components, frozen weights) out of ``measurablePoints``, and ``possibleRange``
    — the totals the unmeasured weight could still produce (0 to 100 per point of
    weight; a PARTIAL component's observed score is evidence, not a bound).
    """
    by_key = {c.key: c for c in components}
    rows = []
    measured = measurable = open_weight = 0.0
    for key, weight in APPROVED_WEIGHTS.items():
        comp = by_key.get(key) or ComponentEvidence(key, UNAVAILABLE, reason="not_measured")
        if comp.state == COMPLETE:
            measured += weight * float(comp.score)
            measurable += 100.0 * weight
        else:
            open_weight += 100.0 * weight
        rows.append(
            {
                "key": key,
                "weight": weight,
                "state": comp.state,
                "score": comp.score,
                "reason": comp.reason,
            }
        )
    complete = open_weight == 0.0
    return {
        "label": CANDIDATE_LABEL,
        "promotion": PROMOTION_STATE,
        "official": False,
        "season": int(season),
        "seasonCouldBeOfficial": int(season) >= EARLIEST_ELIGIBLE_OFFICIAL_SEASON and complete,
        "weights": dict(APPROVED_WEIGHTS),
        "components": rows,
        "complete": complete,
        "definitiveScore": round(measured, 4) if complete else None,
        "measuredPoints": round(measured, 4),
        "measurablePoints": round(measurable, 4),
        "possibleRange": {"low": round(measured, 4), "high": round(measured + open_weight, 4)},
    }


def could_finish_first(presentations: Mapping[str, Mapping[str, Any]]) -> list[str]:
    """Managers whose possible range still reaches the best guaranteed total.

    With complete evidence this is the leader (and anyone tied); with incomplete
    evidence it is everyone the unmeasured weight could put first — the explicit
    alternative to naming an apparent winner incomplete evidence could overturn.
    """
    if not presentations:
        return []
    floor = max(float(p["possibleRange"]["low"]) for p in presentations.values())
    return sorted(m for m, p in presentations.items() if float(p["possibleRange"]["high"]) >= floor)
