"""Fail-closed policy primitives for automatic Hill-master promotion.

This module deliberately owns NO I/O.  The workflow/script layer gathers
scores and history; these functions decide whether that evidence is strong
and stable enough to let OFFENSE replace the incumbent automatically.

Until GLOBAL and IDP have their own independent scorers, autopilot composes
an OFFENSE-only parameter set: the winning OFFENSE (c, s) plus the current
champion's other six constants.  That makes the existing per-scope promotion
gate an additional hard backstop rather than something autopilot overrides.

Owner methodology decision 1 (2026-10-01): the board-holdout gates are
NECESSARY, NOT SUFFICIENT. ``decide`` additionally requires the
``independent_validation`` gate -- at least one eligible, preregistered
independent validation target (``src/model_registry/independent_validation.py``)
that the winner passes. With none, the outcome is ``AUTO_PROMOTION_BLOCKED``
with reason exactly ``no_independent_validation_target``.

Reason precedence (most specific blocker first, each test-pinned):

1. no eligible standing challenger -> ``HOLD``, "no eligible standing challenger";
2. any board evidence gate fails -> ``HOLD``, "blocked by: <failed board gates>"
   (the independent-validation verdict is still recorded in ``gates`` and
   ``independent_validation_reason``);
3. every board gate passes but independent validation does not ->
   ``AUTO_PROMOTION_BLOCKED`` with ``reason`` = the independent-validation reason;
4. everything passes -> ``AUTO_PROMOTION_READY``.

Blocking changes only the outcome: winner selection, the stability cluster and
forward persistence are computed and returned exactly as before, so evidence
keeps accumulating while promotion is blocked.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from math import isfinite
from statistics import mean, median
from typing import Mapping, Sequence

from src.model_registry.independent_validation import (
    REASON_EVIDENCE_MISMATCH,
    REASON_NO_TARGET,
    IndependentValidationEvidence,
)

OUTCOME_READY = "AUTO_PROMOTION_READY"
#: A board evidence gate (or the winner) is not cleared; the champion stands.
OUTCOME_HOLD = "HOLD"
#: Every board gate cleared, but independent validation did not.
OUTCOME_BLOCKED = "AUTO_PROMOTION_BLOCKED"

#: The dependent-board evidence gates, in report order. ``independent_validation``
#: is deliberately not one of them: it is the additional, separate requirement.
BOARD_GATES: tuple[str, ...] = (
    "winner",
    "current_margin",
    "per_source",
    "leave_one_market_out",
    "cross_market_bootstrap",
    "row_health",
    "parameter_stability",
    "forward_persistence",
)
INDEPENDENT_GATE = "independent_validation"


@dataclass(frozen=True)
class AutopilotPolicy:
    min_current_improvement_points: float = 25.0
    min_current_improvement_fraction: float = 0.05
    min_improved_boards: int = 3
    max_board_worsening_fraction: float = 0.10
    min_rows_per_board: int = 300
    stable_candidates_required: int = 3
    stable_span_days: float = 5.0
    candidate_criterion_band_fraction: float = 0.05
    c_relative_tolerance: float = 0.08
    s_relative_tolerance: float = 0.06
    forward_days_required: int = 5
    forward_win_rate_required: float = 0.80
    forward_median_improvement_points: float = 25.0
    bootstrap_lower_quantile: float = 0.05
    min_bootstrap_lower_improvement_points: float = 25.0


@dataclass(frozen=True)
class CandidateScore:
    version: int
    c: float
    s: float
    criterion: float
    per_source: Mapping[str, float]
    per_source_rows: Mapping[str, int]
    fitted_at: str
    status: str
    training_inputs: Mapping[str, str]


@dataclass(frozen=True)
class ForwardScore:
    label: str
    champion_criterion: float
    candidate_criterion: float

    @property
    def improvement(self) -> float:
        return self.champion_criterion - self.candidate_criterion


@dataclass(frozen=True)
class AutopilotDecision:
    ready: bool
    winner_version: int | None
    gates: Mapping[str, bool]
    reason: str
    required_improvement: float
    current_improvement: float | None
    stable_versions: tuple[int, ...] = ()
    forward_days: int = 0
    forward_win_rate: float | None = None
    forward_median_improvement: float | None = None
    bootstrap_lower_improvement: float | None = None
    outcome: str = OUTCOME_HOLD
    #: ``None`` only when independent validation passed.
    independent_validation_reason: str | None = REASON_NO_TARGET


def independent_validation_reason(
    evidence: IndependentValidationEvidence | None, winner_version: int | None
) -> str | None:
    """The independent-validation verdict for ``winner_version`` (``None`` = passed).

    No evidence and an empty registry both mean no eligible target was
    established, so both read ``no_independent_validation_target``."""
    if evidence is None or evidence.registry_size == 0:
        return REASON_NO_TARGET
    if evidence.challenger_version != winner_version:
        return REASON_EVIDENCE_MISMATCH
    return evidence.reason


def _rel_close(a: float, b: float, tolerance: float) -> bool:
    scale = max(abs(a), abs(b), 1e-12)
    return abs(a - b) / scale <= tolerance


def required_improvement(champion_criterion: float, policy: AutopilotPolicy) -> float:
    return max(
        policy.min_current_improvement_points,
        champion_criterion * policy.min_current_improvement_fraction,
    )


def leave_one_out_passes(
    champion_per_source: Mapping[str, float],
    candidate_per_source: Mapping[str, float],
    policy: AutopilotPolicy,
) -> bool:
    """Require the win to survive deletion of any one scored market."""
    names = sorted(set(champion_per_source) & set(candidate_per_source))
    if len(names) < policy.min_improved_boards:
        return False
    for omitted in names:
        kept = [name for name in names if name != omitted]
        if len(kept) < 2:
            return False
        champion = mean(float(champion_per_source[name]) for name in kept)
        candidate = mean(float(candidate_per_source[name]) for name in kept)
        if champion - candidate < required_improvement(champion, policy):
            return False
    return True


def bootstrap_lower_improvement(
    champion_per_source: Mapping[str, float],
    candidate_per_source: Mapping[str, float],
    *,
    quantile: float,
) -> float:
    """Exact deterministic source bootstrap; no RNG and no flaky gate.

    With four holdout markets this enumerates all 4^4 resamples. It is a
    robustness diagnostic across markets, not a claim of ground-truth
    statistical independence.
    """
    names = sorted(set(champion_per_source) & set(candidate_per_source))
    if not names:
        return float("-inf")
    deltas = {
        name: float(champion_per_source[name]) - float(candidate_per_source[name]) for name in names
    }
    samples = sorted(
        mean(deltas[name] for name in draw) for draw in product(names, repeat=len(names))
    )
    idx = max(0, min(len(samples) - 1, int(quantile * (len(samples) - 1))))
    return float(samples[idx])


def choose_winner(candidates: Sequence[CandidateScore]) -> CandidateScore | None:
    eligible = [
        c
        for c in candidates
        if c.status == "challenger"
        and isfinite(c.criterion)
        and c.criterion >= 0
        and c.c > 0
        and c.s > 0
        and c.training_inputs
        and all(v != "missing" for v in c.training_inputs.values())
    ]
    return min(eligible, key=lambda c: (c.criterion, -c.version)) if eligible else None


def stable_cluster(
    winner: CandidateScore,
    candidates: Sequence[CandidateScore],
    *,
    policy: AutopilotPolicy,
    fitted_span_days: Mapping[int, float],
) -> tuple[CandidateScore, ...]:
    max_criterion = winner.criterion * (1.0 + policy.candidate_criterion_band_fraction)
    cluster = [
        c
        for c in candidates
        if c.status == "challenger"
        and c.criterion <= max_criterion
        and _rel_close(c.c, winner.c, policy.c_relative_tolerance)
        and _rel_close(c.s, winner.s, policy.s_relative_tolerance)
    ]
    cluster.sort(key=lambda c: (fitted_span_days.get(c.version, 0.0), c.version))
    if len(cluster) < policy.stable_candidates_required:
        return ()
    full_span = fitted_span_days.get(cluster[-1].version, 0.0) - fitted_span_days.get(
        cluster[0].version, 0.0
    )
    if full_span < policy.stable_span_days:
        return ()

    # Refits now run every ~2h. Taking the newest N candidates would make
    # a five-day persistence requirement mathematically impossible because
    # the newest three are usually only four hours apart. Select evidence
    # across the observed time span instead: oldest + evenly-spaced interior
    # points + newest.
    n = policy.stable_candidates_required
    if n == 1:
        return (cluster[-1],)
    indexes = [round(i * (len(cluster) - 1) / (n - 1)) for i in range(n)]
    chosen = tuple(cluster[i] for i in indexes)
    return chosen


def decide(
    *,
    champion_criterion: float,
    champion_per_source: Mapping[str, float],
    candidates: Sequence[CandidateScore],
    fitted_span_days: Mapping[int, float],
    forward_scores: Sequence[ForwardScore],
    policy: AutopilotPolicy,
    recent_row_health_ok: bool = True,
    independent_validation: IndependentValidationEvidence | None = None,
) -> AutopilotDecision:
    req = required_improvement(champion_criterion, policy)
    winner = choose_winner(candidates)
    if winner is None:
        return AutopilotDecision(
            ready=False,
            winner_version=None,
            gates={"winner": False},
            reason="no eligible standing challenger",
            required_improvement=req,
            current_improvement=None,
            outcome=OUTCOME_HOLD,
            independent_validation_reason=independent_validation_reason(
                independent_validation, None
            ),
        )

    improvement = champion_criterion - winner.criterion
    current_gate = improvement >= req

    source_names = set(champion_per_source) & set(winner.per_source)
    improved = 0
    no_large_regression = True
    for src in source_names:
        old = float(champion_per_source[src])
        new = float(winner.per_source[src])
        if new < old:
            improved += 1
        if old > 0 and (new - old) / old > policy.max_board_worsening_fraction:
            no_large_regression = False
    per_source_gate = (
        len(source_names) >= policy.min_improved_boards
        and improved >= policy.min_improved_boards
        and no_large_regression
    )
    leave_one_out_gate = leave_one_out_passes(
        champion_per_source,
        winner.per_source,
        policy,
    )
    bootstrap_lower = bootstrap_lower_improvement(
        champion_per_source,
        winner.per_source,
        quantile=policy.bootstrap_lower_quantile,
    )
    bootstrap_gate = bootstrap_lower >= policy.min_bootstrap_lower_improvement_points

    rows_gate = (
        bool(winner.per_source_rows)
        and all(int(n) >= policy.min_rows_per_board for n in winner.per_source_rows.values())
        and recent_row_health_ok
    )

    cluster = stable_cluster(
        winner,
        candidates,
        policy=policy,
        fitted_span_days=fitted_span_days,
    )
    stability_gate = len(cluster) >= policy.stable_candidates_required

    improvements = [x.improvement for x in forward_scores]
    forward_days = len(improvements)
    if improvements:
        wins = sum(
            1
            for score in forward_scores
            if score.improvement >= required_improvement(score.champion_criterion, policy)
        )
        win_rate = wins / len(improvements)
        med = float(median(improvements))
    else:
        win_rate = 0.0
        med = float("-inf")
    forward_gate = (
        forward_days >= policy.forward_days_required
        and win_rate >= policy.forward_win_rate_required
        and med >= policy.forward_median_improvement_points
    )

    gates = {
        "winner": True,
        "current_margin": current_gate,
        "per_source": per_source_gate,
        "leave_one_market_out": leave_one_out_gate,
        "cross_market_bootstrap": bootstrap_gate,
        "row_health": rows_gate,
        "parameter_stability": stability_gate,
        "forward_persistence": forward_gate,
    }
    iv_reason = independent_validation_reason(independent_validation, winner.version)
    gates[INDEPENDENT_GATE] = iv_reason is None

    board_failed = [name for name in BOARD_GATES if not gates[name]]
    ready = all(gates.values())
    if board_failed:
        outcome = OUTCOME_HOLD
        reason = "blocked by: " + ", ".join(board_failed)
    elif iv_reason is not None:
        outcome = OUTCOME_BLOCKED
        reason = iv_reason
    else:
        outcome = OUTCOME_READY
        reason = "all automatic-promotion evidence gates cleared"
    return AutopilotDecision(
        ready=ready,
        winner_version=winner.version,
        gates=gates,
        reason=reason,
        required_improvement=req,
        current_improvement=improvement,
        stable_versions=tuple(c.version for c in cluster),
        forward_days=forward_days,
        forward_win_rate=win_rate,
        forward_median_improvement=(med if improvements else None),
        bootstrap_lower_improvement=bootstrap_lower,
        outcome=outcome,
        independent_validation_reason=iv_reason,
    )


def compose_offense_only(
    champion_params: Mapping[str, float],
    winner: CandidateScore,
) -> dict[str, float]:
    """Return a promotion payload that changes OFFENSE and nothing else."""
    out = {str(k): float(v) for k, v in champion_params.items()}
    out["HILL_PERCENTILE_C"] = float(winner.c)
    out["HILL_PERCENTILE_S"] = float(winner.s)
    return out
