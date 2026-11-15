"""Data contracts of the hierarchical decision engine (v3, shadow challenger).

Pure dataclasses.  The engine emits verdict CODES only; the four user-facing
headline strings stay with the served owner ``src/trade/trade_decision.py``
(``tests/trade/test_trade_decision_owner.py``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping

ENGINE_VERSION = "decision_engine_v3_shadow"

#: Every layer carries one of these.  ONLY ``available`` may vote; ``partial``
#: and ``stale`` are report-only, and nothing missing ever contributes 0.
EVIDENCE_STATES = ("available", "partial", "stale", "unavailable")
VOTING_STATES = ("available",)
VERDICT_CODES = ("YES", "NO", "INSUFFICIENT_EVIDENCE")
SHAPES = ("good_for_both", "good_for_one", "bad_for_both", "insufficient")
STRATEGIES = ("WIN_NOW", "BALANCED", "LONG_TERM")
CONFIDENCE_LEVELS = ("low", "medium", "high")  # weakest first

#: Term -> the lineage member it reads (``src.evidence_lineage.registry``).
TERM_LINEAGE_MEMBER = {
    "A": "rank_derived_value",
    "C": "bestball_lineup_delta",
    "D1": "playoff_presim",
    "D2": "bestball_horizon",
}

#: Batch 1: no outcome-layer family has passed a preregistered, owner-approved
#: gate.  The batch-2 adapter reads ``model_registry.family_gates``; until then
#: this constant is the default and is pinned empty by test.
PROMOTED_LAYER_FAMILIES: frozenset[str] = frozenset()

Direction = Literal["favours", "opposes", "neutral"]
MagnitudeClass = Literal["modest", "large"]


@dataclass(frozen=True)
class TermResult:
    """One term of one team's decision, in the term's OWN units."""

    term: Literal["A", "C", "D1", "D2"]
    lineage_member: str
    state: str
    direction: Direction | None
    magnitude_class: MagnitudeClass | None
    value: float | None
    unit: str
    band: float | None
    mc_standard_error: float | None
    predictive_sd: float | None
    predictive_basis: str
    precision_ok: bool | None
    counted_as_vote: bool
    reason: str | None


@dataclass(frozen=True)
class TeamLayers:
    """Everything the engine reads for ONE team.  Read, never recomputed.

    ``asset`` (Layer A): ``sendValues`` / ``recvValues`` (priced canonical
    values), ``sendRaw`` / ``recvRaw``, ``sendAdjusted`` / ``recvAdjusted``,
    ``vaGap`` (recvAdjusted - sendAdjusted), ``sendVa`` / ``recvVa``,
    ``packageModel`` ({id, configState}), ``gateCodes`` (read from the analyze
    packet), ``forcedDropCost`` + ``forcedDropCostBasis`` (from
    ``roster_capacity.forced_drop_cost``), ``state`` / ``reason``.
    ``lineup`` is TeamLineupDelta-shaped, ``title`` CompetitiveOutcome-shaped,
    ``horizon`` TeamHorizonExpectation-shaped (camelCase ``to_dict`` keys; snake
    case accepted).  ``roster_known`` / ``roster_limit_known``: ``None`` is
    UNKNOWN, never true.
    """

    team_id: str
    strategy: str | None
    strategy_source: Literal["user", "posture", "none"]
    posture_label: str | None
    posture_probabilities: Mapping[str, float] | None
    asset: Mapping[str, Any]
    lineup: Mapping[str, Any]
    title: Mapping[str, Any]
    horizon: Mapping[str, Any]
    roster_known: bool | None
    roster_limit_known: bool | None
    freshness: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Reason:
    code: str
    family: str
    stance: Literal["for", "against", "context"]
    magnitude: float | None
    text_key: str
    evidence: Mapping[str, Any]


@dataclass(frozen=True)
class TeamDecision:
    team_id: str
    verdict: Literal["YES", "NO", "INSUFFICIENT_EVIDENCE"]
    neutral_tag: bool
    strategy: str
    strategy_source: str
    terms: tuple[TermResult, ...]
    policy_row: str
    predictive_probability: None
    confidence: Literal["high", "medium", "low"]
    confidence_bottleneck: str
    confidence_axes: Mapping[str, str]
    reasons: tuple[Reason, ...]
    key_numbers: Mapping[str, Any]
    what_would_change: tuple[Mapping[str, Any], ...]
    missing_evidence: tuple[Mapping[str, Any], ...]
    double_count_guard: Mapping[str, Any]
    receipt: Mapping[str, Any]


@dataclass(frozen=True)
class TwoSidedDecision:
    engine_version: str
    param_set_id: str
    teams: tuple[TeamDecision, TeamDecision]
    shape: Literal["good_for_both", "good_for_one", "bad_for_both", "insufficient"]
    recommendation_only: bool = True
    executes: bool = False

    def __post_init__(self) -> None:
        # A recommendation is never an action (CLAUDE.md: recommendations and
        # execution are separate).
        if self.executes is not False or self.recommendation_only is not True:
            raise ValueError("a decision-engine output is a recommendation only")
