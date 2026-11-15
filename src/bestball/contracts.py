"""Published shapes for ``src/bestball`` — the best-ball marginal-utility lane.

Every cross-workstream dataclass here has a camelCase ``to_dict()`` and a
committed JSON fixture under ``tests/fixtures/bestball/`` that downstream
consumers (the decision engine's local Protocols) read in their batch-2 parity
tests.  Changing a field is therefore a contract change: update the fixture in
the same PR and say so.

Three rules are structural here rather than conventions:

* **Missing is never zero.**  Every numeric field is ``float | None``.  ``None``
  is UNKNOWN; a real ``0.0`` is a measured zero.  Every object carries
  ``state`` (one of :data:`EVIDENCE_STATES`) and a ``reason`` when it is not
  ``available``.
* **No probability from Monte-Carlo error.**  ``mc_standard_error`` is the
  precision of one estimate.  ``precision_ok`` says only whether that estimate
  is precise relative to the materiality band.  No object in this package
  carries a probability, a p-value or a "distinguishable" flag derived from it;
  :class:`MarginalBestBallUtility` deliberately has no such field (pinned by
  ``tests/bestball/test_contracts.py``).
* **A vacated roster spot is never silently empty.**  :class:`ReplacementChoice`
  names what filled it — a free waiver claim, internal promotion only, or an
  explicitly labelled ``none_available`` — and states the cost assumption.

Producers: :mod:`src.bestball.replacement` (``WaiverPool``),
:mod:`src.bestball.marginal` (``MarginalBestBallUtility``, ``RosterMarginals``),
:mod:`src.bestball.competitive` (``CompetitiveOutcome``).  ``TeamLineupDelta``
and the horizon shapes are published here as CONTRACTS ONLY so consumers can
code against them now; their producers (``trade_delta`` / ``horizon``) are
later PRs and nothing in this package emits them yet.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from src.roster_intel.best_ball_utility import UtilityPlayer

#: The four evidence states every layer of the decision model shares.  Only
#: ``available`` may vote downstream; ``partial`` and ``stale`` are report-only.
EVIDENCE_STATES: tuple[str, ...] = ("available", "partial", "stale", "unavailable")

REPLACEMENT_KINDS: tuple[str, ...] = (
    "waiver_free_agent",
    "internal_promotion_only",
    "none_available",
)

PREDICTIVE_BASES: tuple[str, ...] = (
    "unavailable",
    "prior_projection_error",
    "proxy_dispersion",
    "provider_calibrated",
)

#: The one cost assumption PR-1 makes about a waiver backfill, stated on every
#: replacement rather than implied: the claim is free and FAAB is not modelled.
FREE_WAIVER_COST_ASSUMPTION = "free_waiver_claim_unmodelled_faab"

UNIT_PPG = "expected best-ball points per week (exact league scoring)"


def _check_state(state: str) -> None:
    if state not in EVIDENCE_STATES:
        raise ValueError(f"state {state!r} is not one of {EVIDENCE_STATES}")


def _plain(value: Any) -> Any:
    """JSON-safe copy of a basis mapping (tuples -> lists, mappings -> dicts)."""
    if isinstance(value, Mapping):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def utility_player_to_dict(p: UtilityPlayer) -> dict[str, Any]:
    """camelCase view of the consumed :class:`UtilityPlayer` (no availability map)."""
    return {
        "playerId": p.player_id,
        "name": p.name,
        "position": p.position,
        "ppg": p.ppg,
        "fantasyPositions": list(p.fantasy_positions or ()),
    }


@dataclass(frozen=True)
class ReplacementChoice:
    """What fills the roster spot a removed player vacates."""

    kind: Literal["waiver_free_agent", "internal_promotion_only", "none_available"]
    player_id: str | None
    ppg: float | None
    contested: bool
    cost_assumption: str
    assumption: str

    def __post_init__(self) -> None:
        if self.kind not in REPLACEMENT_KINDS:
            raise ValueError(f"kind {self.kind!r} is not one of {REPLACEMENT_KINDS}")
        if not self.assumption:
            raise ValueError("a replacement must state its assumption")
        if self.kind == "waiver_free_agent" and self.player_id is None:
            raise ValueError("a waiver_free_agent replacement names its player")

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "playerId": self.player_id,
            "ppg": self.ppg,
            "contested": self.contested,
            "costAssumption": self.cost_assumption,
            "assumption": self.assumption,
        }


@dataclass(frozen=True)
class WaiverPool:
    """Priced free agents a team could claim, best first, plus what was left out.

    ``candidates`` holds only players with a league-scored projection, sorted by
    ``ppg`` descending (ties by player id).  An unprojected free agent is listed
    in ``unpriced_ids`` — never a candidate at 0.0.
    """

    candidates: tuple[UtilityPlayer, ...]
    unpriced_ids: tuple[str, ...]
    excluded_auction_lot_ids: tuple[str, ...]
    basis: Mapping[str, Any]
    state: str
    reason: str | None

    def __post_init__(self) -> None:
        _check_state(self.state)
        if any(p.ppg is None for p in self.candidates):
            raise ValueError("an unprojected player cannot be a waiver candidate")

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidates": [utility_player_to_dict(p) for p in self.candidates],
            "unpricedIds": list(self.unpriced_ids),
            "excludedAuctionLotIds": list(self.excluded_auction_lot_ids),
            "basis": _plain(self.basis),
            "state": self.state,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class MarginalBestBallUtility:
    """F(R) − F(R − {player} + {replacement}) for one rostered player.

    ``with_ppg`` / ``without_ppg`` are expected optimal best-ball lineup points
    per week; ``delta_ppg`` is their paired difference (positive = the roster is
    better WITH the player).  ``mc_standard_error`` is the Monte-Carlo precision
    of that paired estimate and nothing more; ``precision_ok`` is
    ``mc_standard_error <= band / 2``.  There is deliberately NO probability and
    NO "distinguishable" field.
    """

    player_id: str
    owner_id: str | None
    with_ppg: float | None
    without_ppg: float | None
    delta_ppg: float | None
    mc_standard_error: float | None
    precision_ok: bool | None
    predictive_sd: float | None
    predictive_basis: Literal[
        "unavailable", "prior_projection_error", "proxy_dispersion", "provider_calibrated"
    ]
    replacement: ReplacementChoice
    draws: int
    seed: int
    weeks: tuple[int, ...]
    param_set_id: str
    basis: Mapping[str, Any]
    state: str
    reason: str | None

    def __post_init__(self) -> None:
        _check_state(self.state)
        if self.predictive_basis not in PREDICTIVE_BASES:
            raise ValueError(f"predictive_basis {self.predictive_basis!r} unknown")
        if self.predictive_basis == "unavailable" and self.predictive_sd is not None:
            raise ValueError("predictive_sd requires a predictive basis")
        if self.state == "unavailable" and self.delta_ppg is not None:
            raise ValueError("an unavailable marginal carries no number")

    def to_dict(self) -> dict[str, Any]:
        return {
            "playerId": self.player_id,
            "ownerId": self.owner_id,
            "withPpg": self.with_ppg,
            "withoutPpg": self.without_ppg,
            "deltaPpg": self.delta_ppg,
            "mcStandardError": self.mc_standard_error,
            "precisionOk": self.precision_ok,
            "predictiveSd": self.predictive_sd,
            "predictiveBasis": self.predictive_basis,
            "replacement": self.replacement.to_dict(),
            "draws": self.draws,
            "seed": self.seed,
            "weeks": list(self.weeks),
            "paramSetId": self.param_set_id,
            "unit": UNIT_PPG,
            "basis": _plain(self.basis),
            "state": self.state,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class RosterMarginals:
    """Marginals for every (or the top ``max_players``) player on one roster."""

    owner_id: str | None
    entries: tuple[MarginalBestBallUtility, ...]
    elapsed_s: float
    runs: int
    basis: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ownerId": self.owner_id,
            "entries": [e.to_dict() for e in self.entries],
            "elapsedS": self.elapsed_s,
            "runs": self.runs,
            "basis": _plain(self.basis),
        }


@dataclass(frozen=True)
class CompetitiveOutcome:
    """Current-season title-probability change for one team."""

    owner_id: str
    title_prob_before: float | None
    title_prob_after: float | None
    delta: float | None
    ci_low: float | None
    ci_high: float | None
    horizon: Literal["current_season"]
    basis: str
    state: str
    reason: str | None

    def __post_init__(self) -> None:
        _check_state(self.state)
        if self.horizon != "current_season":
            raise ValueError("CompetitiveOutcome horizon is current_season only")
        if self.state == "unavailable" and any(
            v is not None
            for v in (
                self.title_prob_before,
                self.title_prob_after,
                self.delta,
                self.ci_low,
                self.ci_high,
            )
        ):
            raise ValueError("an unavailable competitive outcome carries no number")

    def to_dict(self) -> dict[str, Any]:
        return {
            "ownerId": self.owner_id,
            "titleProbBefore": self.title_prob_before,
            "titleProbAfter": self.title_prob_after,
            "delta": self.delta,
            "ciLow": self.ci_low,
            "ciHigh": self.ci_high,
            "horizon": self.horizon,
            "basis": self.basis,
            "state": self.state,
            "reason": self.reason,
        }


# ── Contracts published ahead of their producers (PR-2 / PR-3) ────────────


@dataclass(frozen=True)
class TeamLineupDelta:
    """One team's expected best-ball lineup change from a trade (PR-2 producer).

    ``state`` is narrowed to the four evidence states; ``coverage`` says whether
    every traded player was projected.  ``downside_q10`` stays ``None`` until a
    predictive (not Monte-Carlo) uncertainty exists.
    """

    owner_id: str
    before_ppg: float | None
    after_ppg: float | None
    delta_ppg: float | None
    mc_standard_error: float | None
    predictive_sd: float | None
    predictive_basis: str
    downside_q10: float | None
    depth_before: float | None
    depth_after: float | None
    coverage: Literal["full", "partial", "none"]
    vacated_spot_backfill: tuple[ReplacementChoice, ...]
    state: Literal["available", "partial", "stale", "unavailable"]
    reason: str | None

    def __post_init__(self) -> None:
        _check_state(self.state)
        if self.predictive_basis not in PREDICTIVE_BASES:
            raise ValueError(f"predictive_basis {self.predictive_basis!r} unknown")
        if self.coverage not in ("full", "partial", "none"):
            raise ValueError(f"coverage {self.coverage!r} unknown")

    def to_dict(self) -> dict[str, Any]:
        return {
            "ownerId": self.owner_id,
            "beforePpg": self.before_ppg,
            "afterPpg": self.after_ppg,
            "deltaPpg": self.delta_ppg,
            "mcStandardError": self.mc_standard_error,
            "predictiveSd": self.predictive_sd,
            "predictiveBasis": self.predictive_basis,
            "downsideQ10": self.downside_q10,
            "depthBefore": self.depth_before,
            "depthAfter": self.depth_after,
            "coverage": self.coverage,
            "vacatedSpotBackfill": [r.to_dict() for r in self.vacated_spot_backfill],
            "state": self.state,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class SeasonForecast:
    """One forward season for one player (PR-3 producer)."""

    season: int
    expected_ppg: float | None
    sd: float | None
    p_active: float | None
    basis: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "season": self.season,
            "expectedPpg": self.expected_ppg,
            "sd": self.sd,
            "pActive": self.p_active,
            "basis": self.basis,
        }


@dataclass(frozen=True)
class DynastyHorizonForecast:
    """A player's multi-season forecast (PR-3 producer)."""

    player_id: str
    seasons: tuple[SeasonForecast, ...]
    aging_curve_version: str
    state: str
    reason: str | None

    def __post_init__(self) -> None:
        _check_state(self.state)

    def to_dict(self) -> dict[str, Any]:
        return {
            "playerId": self.player_id,
            "seasons": [s.to_dict() for s in self.seasons],
            "agingCurveVersion": self.aging_curve_version,
            "state": self.state,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class TeamHorizonExpectation:
    """Deterministic lineup expectation per forward season (PR-3 producer)."""

    owner_id: str
    by_season: tuple[tuple[int, float | None, float | None], ...]
    method: Literal["deterministic_lineup_on_expected_ppg"]
    state: str
    reason: str | None

    def __post_init__(self) -> None:
        _check_state(self.state)
        if self.method != "deterministic_lineup_on_expected_ppg":
            raise ValueError(f"method {self.method!r} unknown")

    def to_dict(self) -> dict[str, Any]:
        return {
            "ownerId": self.owner_id,
            "bySeason": [
                {"season": s, "expectedLineupPpg": ppg, "sd": sd} for s, ppg, sd in self.by_season
            ],
            "method": self.method,
            "state": self.state,
            "reason": self.reason,
        }
