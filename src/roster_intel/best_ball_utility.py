"""Roster-conditional best-ball utility — #1173 (owner addendum 2026-08-29).

The question this module owns: **what does this asset do for THIS roster
under THIS league's best-ball lineup rules?**  It is deliberately separate
from what the asset is worth — canonical value (``rankDerivedValue``) is
never read, written or adjusted here.

Definition (``docs/OWNER_FEATURE_ADDENDUM_2026-08-29_BEST_BALL_ROSTER_UTILITY.md`` §2)::

    F(R) = E[ optimal legal weekly lineup score | roster R, exact league rules ]
    Best-Ball Lineup Impact (BBLI) = F(R_after) - F(R_before)

Estimated by simulation, and the order of operations is the point:

    scenario -> draw every player's week -> solve the legal lineup -> score -> average

never "average the projections, then choose a lineup once".  A best-ball
roster collects its best legal lineup EVERY week, so a deep bench is worth
something exactly when a draw lets it displace a starter — which only a
per-scenario solve can see.

Reused owners, nothing re-implemented:

* **lineup** — :func:`src.ros.lineup.solve_optimal_assignment` with
  ``OBJECTIVE_REALIZED_POINTS`` (the same exact, FLEX / SUPER_FLEX / IDP-flex
  aware global assignment Game Day uses).  No per-position approximation.
* **weekly variance** — :meth:`src.league_intel.sim_calibration.PointsModel.
  draw_from_mean`, the per-position CV measured under this league's scoring
  (the one variance model Game Day and the playoff sim share).
* **points** — the caller hands per-player means in POINTS in exact league
  scoring (the trade path supplies the league-scored ROS ensemble's per-game
  rate; see ``src.api.trade_simulator``).  This module never converts a rank
  or value index into points.

Pairing.  Every player's weekly draws are generated ONCE from a seed keyed by
(seed, player id) and shared by every roster evaluated, so the before / after
comparison differences out everything the trade did not touch.  The published
``standardError`` is the Monte-Carlo error of that paired mean — a precision
statement about this estimate, not a probability the trade "wins".

MISSING IS NEVER ZERO.  A player with no projection (``ppg is None``) is not
a candidate for any slot (the lineup owner's unpriced rule) and is REPORTED in
``coverage``; a projection of exactly 0.0 is a real, assignable zero.  When a
TRADED player is unprojected the utility is computed over the priced players
and ``coverage.state`` says ``partial`` — the decision layer must abstain on
it rather than read a partial number as complete.

Not modelled, and said so in ``assumptions`` rather than invented: injury /
availability probabilities, bye weeks, player-to-player correlation.  The
depth measure is therefore a deterministic single-starter-absence scenario,
not an injury forecast.
"""

from __future__ import annotations

import math
import random
import threading
import time
import zlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from src.league_intel.sim_calibration import PointsModel, load_points_model
from src.ros.lineup import (
    OBJECTIVE_REALIZED_POINTS,
    RosterPlayer,
    precompute_slot_eligibility,
    solve_optimal_assignment,
)

#: Scenarios per evaluation.  Pairing makes the DELTA precise at this size
#: (the published standard error says how precise); raising it costs latency
#: linearly on a request path.
DEFAULT_DRAWS = 400
DEFAULT_SEED = 1173

UNIT = "expected best-ball points per week (exact league scoring)"

#: A lineup-entry change smaller than this (percentage points) is not listed
#: as "materially affected" — a display threshold for which rows to show,
#: never an input to any number.
AFFECTED_LEP_PP = 5.0
MAX_AFFECTED = 8


@dataclass(frozen=True)
class UtilityPlayer:
    """One roster member as this module needs him.

    ``ppg`` is the per-week mean in POINTS under the league's exact scoring,
    or ``None`` when no projection exists (unknown — not zero).
    """

    player_id: str
    name: str
    position: str
    ppg: float | None
    fantasy_positions: tuple[str, ...] = ()


class _Draws:
    """Per-player weekly draws, generated once and shared across rosters."""

    def __init__(self, model: PointsModel, draws: int, seed: int) -> None:
        self._model = model
        self._n = draws
        self._seed = seed
        self._cache: dict[str, list[float]] = {}

    def of(self, player: UtilityPlayer) -> list[float]:
        pid = player.player_id
        hit = self._cache.get(pid)
        if hit is None:
            # zlib.crc32, not hash(): Python salts str hashes per process,
            # which would make every run's numbers differ.
            rng = random.Random(zlib.crc32(f"{self._seed}:{pid}".encode()))
            mean = float(player.ppg)  # caller guarantees ppg is not None
            hit = [self._model.draw_from_mean(mean, player.position, rng) for _ in range(self._n)]
            self._cache[pid] = hit
        return hit


@dataclass
class _RosterRun:
    mean: float
    per_draw: list[float]
    lep: dict[str, float]  # player id -> share of draws in the lineup (0-1)
    usable: dict[str, float]  # player id -> E[points x in lineup]
    raw_ppg: float
    priced: int
    unpriced_ids: tuple[str, ...]


def _roster_player(p: UtilityPlayer, value: float) -> RosterPlayer:
    return RosterPlayer(
        player_id=p.player_id,
        canonical_name=p.name,
        position=p.position,
        ros_value=value,
        fantasy_positions=p.fantasy_positions,
    )


def _run(
    roster: Sequence[UtilityPlayer],
    slots: Sequence[str],
    slot_eligibility: Mapping[str, Any] | None,
    draws: _Draws,
    n: int,
) -> _RosterRun:
    priced = [p for p in roster if p.ppg is not None]
    unpriced = tuple(sorted(p.player_id for p in roster if p.ppg is None))
    if not priced:
        return _RosterRun(0.0, [0.0] * n, {}, {}, 0.0, 0, unpriced)
    series = {p.player_id: draws.of(p) for p in priced}
    template = [_roster_player(p, 0.0) for p in priced]
    eligibility = precompute_slot_eligibility(
        template, list(slots), slot_eligibility=slot_eligibility
    )
    in_count: dict[str, int] = {p.player_id: 0 for p in priced}
    usable_sum: dict[str, float] = {p.player_id: 0.0 for p in priced}
    per_draw: list[float] = []
    for d in range(n):
        pool = [_roster_player(p, series[p.player_id][d]) for p in priced]
        assignment = solve_optimal_assignment(
            pool,
            list(slots),
            precomputed_eligibility=eligibility,
            objective=OBJECTIVE_REALIZED_POINTS,
        )
        score = 0.0
        for pl in assignment.values():
            v = float(pl.ros_value)
            score += v
            in_count[pl.player_id] += 1
            usable_sum[pl.player_id] += v
        per_draw.append(score)
    return _RosterRun(
        mean=sum(per_draw) / n,
        per_draw=per_draw,
        lep={pid: c / n for pid, c in in_count.items()},
        usable={pid: s / n for pid, s in usable_sum.items()},
        raw_ppg=sum(float(p.ppg) for p in priced),
        priced=len(priced),
        unpriced_ids=unpriced,
    )


def _expected_lineup_score(
    roster: Sequence[UtilityPlayer],
    slots: Sequence[str],
    slot_eligibility: Mapping[str, Any] | None,
) -> tuple[float, list[str]]:
    """One solve on the MEANS — used only by the absence scenario, which asks a
    deterministic what-if and says so."""
    pool = [_roster_player(p, float(p.ppg)) for p in roster if p.ppg is not None]
    if not pool:
        return 0.0, []
    assignment = solve_optimal_assignment(
        pool,
        list(slots),
        slot_eligibility=slot_eligibility,
        objective=OBJECTIVE_REALIZED_POINTS,
    )
    return (
        sum(float(pl.ros_value) for pl in assignment.values()),
        [pl.player_id for pl in assignment.values()],
    )


def _absence_depth(
    roster: Sequence[UtilityPlayer],
    slots: Sequence[str],
    slot_eligibility: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """Single-starter absence: remove each expected starter in turn, re-solve.

    ``meanLossPpg`` — how much the expected lineup loses, on average, when one
    starter is out.  Lower means deeper/more resilient.  A deterministic
    scenario over the means, NOT an injury probability (none is modelled).
    """
    base, starters = _expected_lineup_score(roster, slots, slot_eligibility)
    if not starters:
        return None
    losses: list[tuple[float, str]] = []
    for sid in starters:
        rest = [p for p in roster if p.player_id != sid]
        without, _ = _expected_lineup_score(rest, slots, slot_eligibility)
        losses.append((base - without, sid))
    worst = max(losses)
    return {
        "expectedLineupPpg": round(base, 2),
        "meanLossPpg": round(sum(loss for loss, _ in losses) / len(losses), 2),
        "worstLossPpg": round(worst[0], 2),
        "worstLossPlayerId": worst[1],
        "starters": len(starters),
    }


def _paired_stats(after: _RosterRun, before: _RosterRun) -> tuple[float, float | None]:
    diffs = [a - b for a, b in zip(after.per_draw, before.per_draw)]
    n = len(diffs)
    mean = sum(diffs) / n if n else 0.0
    if n < 2:
        return mean, None
    var = sum((d - mean) ** 2 for d in diffs) / (n - 1)
    return mean, math.sqrt(var / n)


def _roster_summary(run: _RosterRun, roster_size: int) -> dict[str, Any]:
    return {
        "expectedLineupPpg": round(run.mean, 2),
        "rawProjectedPpg": round(run.raw_ppg, 2),
        # Raw projected production that never reaches the legal lineup: the
        # redundancy the market value of those players does not see.
        "redundantPpg": round(max(0.0, run.raw_ppg - run.mean), 2),
        "rosteredPlayers": roster_size,
        "projectedPlayers": run.priced,
        "unprojectedPlayerIds": list(run.unpriced_ids),
    }


def evaluate_trade_utility(
    *,
    before: Sequence[UtilityPlayer],
    after: Sequence[UtilityPlayer],
    slots: Sequence[str],
    roles: Mapping[str, str],
    after_before_cleanup: Sequence[UtilityPlayer] | None = None,
    slot_eligibility: Mapping[str, Any] | None = None,
    points_model: PointsModel | None = None,
    draws: int = DEFAULT_DRAWS,
    seed: int = DEFAULT_SEED,
    basis: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """BBLI and its explanation for one trade from one team's side.

    ``after`` is the FINAL LEGAL roster (forced cleanup applied);
    ``after_before_cleanup`` is the roster the moment the trade lands, given
    only when a cleanup changed it, so "the apparent gain" and "the gain once
    the roster is legal" are both visible.  ``roles`` maps the player ids the
    trade touches to ``incoming`` / ``outgoing`` / ``forcedDrop``.
    """
    if not slots:
        return {
            "available": False,
            "unavailableReason": "starter_slots_unresolved",
            "unit": UNIT,
        }
    model = points_model or load_points_model()
    n = max(2, int(draws))
    shared = _Draws(model, n, seed)

    run_before = _run(before, slots, slot_eligibility, shared, n)
    run_after = _run(after, slots, slot_eligibility, shared, n)
    run_pre = (
        _run(after_before_cleanup, slots, slot_eligibility, shared, n)
        if after_before_cleanup is not None
        else None
    )

    impact, stderr = _paired_stats(run_after, run_before)
    pre_impact = _paired_stats(run_pre, run_before)[0] if run_pre is not None else None

    # Coverage: a traded player (either direction) without a projection makes
    # the utility PARTIAL — computed over the priced players, never zero-filled.
    by_id = {p.player_id: p for p in (*before, *after, *(after_before_cleanup or ()))}
    traded_unprojected = sorted(
        pid
        for pid, role in roles.items()
        if role in ("incoming", "outgoing")
        and by_id.get(pid) is not None
        and by_id[pid].ppg is None
    )
    coverage_state = "partial" if traded_unprojected else "full"

    players: list[dict[str, Any]] = []
    listed: set[str] = set()

    def _player_row(pid: str, role: str) -> dict[str, Any]:
        p = by_id.get(pid)
        lep_b = run_before.lep.get(pid)
        lep_a = run_after.lep.get(pid)
        return {
            "playerId": pid,
            "name": p.name if p else pid,
            "position": p.position if p else "",
            "role": role,
            "projectedPpg": None if p is None or p.ppg is None else round(float(p.ppg), 2),
            "lineupEntryPctBefore": None if lep_b is None else round(100 * lep_b, 1),
            "lineupEntryPctAfter": None if lep_a is None else round(100 * lep_a, 1),
            "usablePpgBefore": None
            if pid not in run_before.usable
            else round(run_before.usable[pid], 2),
            "usablePpgAfter": None
            if pid not in run_after.usable
            else round(run_after.usable[pid], 2),
        }

    for pid, role in sorted(roles.items(), key=lambda kv: (kv[1], kv[0])):
        players.append(_player_row(pid, role))
        listed.add(pid)

    # Players the trade never names whose lineup role it changes (a FLEX seat
    # vacated, a bench player promoted, a starter pushed out).
    common = set(run_before.lep) & set(run_after.lep)
    shifts = sorted(
        ((run_after.lep[pid] - run_before.lep[pid], pid) for pid in common if pid not in listed),
        key=lambda t: -abs(t[0]),
    )
    for shift, pid in shifts[:MAX_AFFECTED]:
        if abs(shift) * 100 < AFFECTED_LEP_PP:
            break
        players.append(_player_row(pid, "promoted" if shift > 0 else "displaced"))

    n_in = sum(1 for r in roles.values() if r == "incoming")
    n_out = sum(1 for r in roles.values() if r == "outgoing")
    shape = "consolidation" if n_out > n_in else "expansion" if n_in > n_out else "swap"

    depth_before = _absence_depth(before, slots, slot_eligibility)
    depth_after = _absence_depth(after, slots, slot_eligibility)
    depth_delta = (
        round(depth_after["meanLossPpg"] - depth_before["meanLossPpg"], 2)
        if depth_before and depth_after
        else None
    )

    return {
        "available": True,
        "unit": UNIT,
        "before": _roster_summary(run_before, len(before)),
        "after": _roster_summary(run_after, len(after)),
        "afterBeforeCleanup": (
            _roster_summary(run_pre, len(after_before_cleanup or ()))
            if run_pre is not None
            else None
        ),
        "impact": {
            "ppg": round(impact, 2),
            "standardError": None if stderr is None else round(stderr, 3),
            # Only when a forced cleanup changed the roster: the gain the
            # moment the trade lands, before the roster is made legal.
            "ppgBeforeCleanup": None if pre_impact is None else round(pre_impact, 2),
        },
        "players": players,
        "shape": {
            "label": shape,
            "playersIn": n_in,
            "playersOut": n_out,
            # The consequence of the shape is BBLI itself — there is no
            # universal consolidation premium to report here.
        },
        "depth": {
            "method": "single_starter_absence",
            "description": (
                "each expected starter removed in turn and the legal lineup re-solved; "
                "a deterministic what-if, not an injury probability"
            ),
            "before": depth_before,
            "after": depth_after,
            # Positive = a missing starter hurts MORE after the trade.
            "meanLossDeltaPpg": depth_delta,
        },
        "rosterSpot": {
            "openSpotsGained": max(0, n_out - n_in),
            "shadowValuePpg": None,
            "reason": "not_yet_measured: the waiver-pool projection join is pending",
        },
        "coverage": {
            "state": coverage_state,
            "tradedUnprojectedPlayerIds": traded_unprojected,
        },
        "basis": {
            **dict(basis or {}),
            "draws": n,
            "seed": seed,
            "pointsModel": model.to_dict(),
            "lineupSolver": "src.ros.lineup.solve_optimal_assignment (realized_points)",
        },
        "assumptions": [
            "each week is drawn around the player's per-game projection with the league's "
            "calibrated per-position variance; players are independent",
            "injury / availability probabilities are not modelled",
            "bye weeks are not modelled",
            "the lineup is re-solved exactly for every simulated week (best ball)",
        ],
    }


# ── Projection basis (trade path) ────────────────────────────────────────
#
# Per-player per-game points under the league's EXACT scoring, from the
# canonical league-scored ROS ensemble (``src.ros.projection_ensemble``) —
# the same resolution Game Day's preseason fallback uses.  It is a
# FULL-SEASON projection's per-game rate (horizon ``PRESEASON_FULL_SEASON``),
# and the basis block says so rather than implying a weekly projection.

_ENSEMBLE_TTL_SECONDS = 900.0
_ensemble_cache: dict[tuple[int, str], tuple[float, dict[str, float], dict[str, Any]]] = {}
_ensemble_lock = threading.Lock()


def _ensemble_index(
    season: int, scoring_settings: Mapping[str, Any]
) -> tuple[dict[str, float], dict[str, Any]]:
    """``(normalized name -> per-game points, basis)`` for one league scoring card."""
    from src.league_comparison.sleeper_scoring import scoring_fingerprint
    from src.ros.game_day_capture import estimate_index_from_ensemble
    from src.ros.projection_ensemble import build_ros_full_season_ensemble

    fingerprint = scoring_fingerprint(dict(scoring_settings or {}))
    if fingerprint is None:
        return {}, {"state": "unavailable", "reason": "scoring_card_missing"}
    key = (int(season), fingerprint)
    now = time.time()
    with _ensemble_lock:
        hit = _ensemble_cache.get(key)
    if hit is not None and now - hit[0] < _ENSEMBLE_TTL_SECONDS:
        return hit[1], hit[2]
    result = build_ros_full_season_ensemble(
        season=int(season), scoring_settings=dict(scoring_settings)
    )
    index = estimate_index_from_ensemble(result.ensemble)
    families = sorted(
        {fam for obs in result.ensemble for fam in (getattr(obs, "families", None) or ())}
    )
    basis = {
        "state": "available" if index else "unavailable",
        "reason": None if index else "no_projection_snapshot",
        "source": f"ros_ensemble:{result.horizon}:equal_family_mean",
        "horizon": result.horizon,
        "description": (
            "full-season projection per game, rescored through this league's exact "
            "scoring card; not a weekly projection"
        ),
        "season": int(season),
        "scoringFingerprint": fingerprint,
        "sourcesLoaded": list(result.sources_loaded),
        "sourcesUnavailable": list(result.sources_unavailable),
        "families": families,
        "playersProjected": len(index),
    }
    with _ensemble_lock:
        _ensemble_cache[key] = (now, index, basis)
    return index, basis


def league_scored_ppg_by_id(
    player_ids: Sequence[str],
    *,
    season: int,
    scoring_settings: Mapping[str, Any],
) -> tuple[dict[str, float], dict[str, Any]]:
    """Per-game league-scored points for Sleeper ``player_ids``.

    A player the ensemble does not price, or whose name two NFL players share
    (the Game Day join refuses those rather than guess), is simply absent from
    the result — UNKNOWN, never 0.0.
    """
    index, basis = _ensemble_index(season, scoring_settings)
    if not index:
        return {}, basis
    from src.api.matchup_intel import players_meta_for_rosters
    from src.ros.game_day_estimates import preseason_by_id

    ids = [str(p) for p in player_ids if p]
    meta = players_meta_for_rosters([{"players": ids}])
    by_id, ambiguous = preseason_by_id(ids, meta, index)
    return by_id, {**basis, "ambiguousNameIds": list(ambiguous)}
