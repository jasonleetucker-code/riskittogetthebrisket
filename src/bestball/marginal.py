"""Marginal best-ball utility: what one player adds to THIS roster.

Directive §7::

    Marginal Best Ball Utility = E[optimal team production WITH the player]
                               - E[optimal team production WITHOUT the player]

with "an appropriate replacement scenario when the player is removed — do not
assume an empty roster spot is always the correct alternative".

So the WITHOUT roster is ``R - {p} + {best free claim}``, never just ``R - {p}``
unless no priced free agent can fill any slot the player could — and then the
replacement is reported as an explicitly labelled ``none_available``.

Computation — nothing re-implemented, everything through the public API of the
existing owner :func:`src.roster_intel.best_ball_utility.evaluate_trade_utility`
(the exact best-ball lineup solve per simulated week, paired draws, the
availability calendar, the before-side reuse):

1. **Opened slot families.**  The removed player's eligible starting slots
   (:func:`src.ros.lineup.precompute_slot_eligibility`, honouring the league's
   own ``slot_eligibility``), collapsed to distinct slot names — e.g. a WR opens
   ``WR``, ``FLEX`` and ``SUPER_FLEX``.
2. **Candidates.**  For each opened family, the top ``candidatesPerSlotFamily``
   priced free agents eligible for it (the pool is already sorted by
   league-scored ppg).  Deduplicated.  The cap bounds cost only.
3. **Re-solve decides.**  Each candidate is simulated as the claim
   (``after = R - {p} + {c}``) against the same paired draws; the candidate
   whose roster scores best is the replacement.  If that candidate adds no
   usable points (``usablePpgAfter`` 0.00), the replacement is labelled
   ``internal_promotion_only`` — the roster's own depth absorbs the vacated
   contribution.
4. **Publish** ``delta_ppg``, its Monte-Carlo ``mc_standard_error`` and
   ``precision_ok = mc_standard_error <= band / 2``.

The band is ``materialityPpg`` (a declared PRIOR).  ``predictive_basis`` is
``unavailable`` in this PR: no predictive (projection-error) uncertainty exists
yet, so ``predictive_sd`` is ``None`` and the band is the materiality prior
alone.  Raising draws can only tighten precision; it never moves the band, so
it can never manufacture a "material" verdict.  No probability is derived from
the Monte-Carlo error anywhere in this package.

Selection note, stated rather than hidden: choosing the best of K simulated
candidates on the same draws is a max over K noisy estimates, which slightly
favours the replacement (biases ``delta_ppg`` down, the conservative
direction).  K is 1-3 per player at the default cap.

Scope: offline report objects only.  No production module imports this
package (pinned by ``tests/bestball/test_import_graph.py``); league slots are
always passed in explicitly, so no league is ever resolved implicitly.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from typing import Any

from src.bestball.contracts import (
    FREE_WAIVER_COST_ASSUMPTION,
    MarginalBestBallUtility,
    ReplacementChoice,
    RosterMarginals,
    WaiverPool,
)
from src.league_intel.sim_calibration import PointsModel
from src.roster_intel import best_ball_utility as _bbu
from src.roster_intel.best_ball_utility import UtilityPlayer, evaluate_trade_utility
from src.ros.lineup import RosterPlayer, normalize_slot, precompute_slot_eligibility

__all__ = [
    "materiality_band_ppg",
    "marginal_bestball_utility",
    "marginal_bestball_utility_for_roster",
    "opened_slot_families",
    "select_candidates",
]

MODEL_VERSION = "bestball_marginal_v1"


def materiality_band_ppg(params: Mapping[str, Any]) -> float:
    """The magnitude band for a marginal, in ppg.

    PR-1: the ``materialityPpg`` prior alone, because ``predictive_basis`` is
    ``unavailable``.  The band never depends on the draw count.
    """
    return float(params["materialityPpg"])


def _rp(p: UtilityPlayer) -> RosterPlayer:
    return RosterPlayer(
        player_id=p.player_id,
        canonical_name=p.name,
        position=p.position,
        ros_value=0.0,
        fantasy_positions=p.fantasy_positions,
    )


def opened_slot_families(
    player: UtilityPlayer,
    slots: Sequence[str],
    slot_eligibility: Mapping[str, Any] | None = None,
) -> tuple[str, ...]:
    """Distinct (normalized) starting-slot names ``player`` may fill, in slot order."""
    elig = precompute_slot_eligibility(
        [_rp(player)], list(slots), slot_eligibility=slot_eligibility
    )
    out: list[str] = []
    for i in elig.get(player.player_id, ()):
        fam = normalize_slot(slots[i])
        if fam not in out:
            out.append(fam)
    return tuple(out)


def select_candidates(
    families: Sequence[str],
    pool: Sequence[UtilityPlayer],
    *,
    cap: int,
    exclude_ids: Sequence[str] = (),
    slot_eligibility: Mapping[str, Any] | None = None,
) -> list[UtilityPlayer]:
    """Top ``cap`` pool players per opened family, deduplicated, pool order kept."""
    if not families or cap <= 0:
        return []
    skip = set(exclude_ids)
    eligible_pool = [c for c in pool if c.player_id not in skip and c.ppg is not None]
    elig = precompute_slot_eligibility(
        [_rp(c) for c in eligible_pool], list(families), slot_eligibility=slot_eligibility
    )
    chosen: list[UtilityPlayer] = []
    seen: set[str] = set()
    for j in range(len(families)):
        taken = 0
        for c in eligible_pool:
            if taken >= cap:
                break
            if j in elig.get(c.player_id, ()):
                taken += 1
                if c.player_id not in seen:
                    seen.add(c.player_id)
                    chosen.append(c)
    return chosen


def _not_evaluated(reason: str) -> ReplacementChoice:
    return ReplacementChoice(
        kind="none_available",
        player_id=None,
        ppg=None,
        contested=False,
        cost_assumption=FREE_WAIVER_COST_ASSUMPTION,
        assumption=f"not_evaluated: {reason}",
    )


def _unavailable(
    player_id: str,
    owner_id: str | None,
    params: Mapping[str, Any],
    weeks: Sequence[int] | None,
    reason: str,
    basis: Mapping[str, Any] | None = None,
) -> MarginalBestBallUtility:
    return MarginalBestBallUtility(
        player_id=player_id,
        owner_id=owner_id,
        with_ppg=None,
        without_ppg=None,
        delta_ppg=None,
        mc_standard_error=None,
        precision_ok=None,
        predictive_sd=None,
        predictive_basis="unavailable",
        replacement=_not_evaluated(reason),
        draws=int(params["draws"]),
        seed=int(params["seed"]),
        weeks=tuple(weeks or ()),
        param_set_id=str(params.get("paramSetId")),
        basis={"modelVersion": MODEL_VERSION, **dict(basis or {})},
        state="unavailable",
        reason=reason,
    )


def _row(result: Mapping[str, Any], pid: str) -> Mapping[str, Any] | None:
    for r in result.get("players") or ():
        if r.get("playerId") == pid:
            return r
    return None


def marginal_bestball_utility(
    roster: Sequence[UtilityPlayer],
    player_id: str,
    slots: Sequence[str],
    *,
    waiver_pool: WaiverPool,
    params: Mapping[str, Any],
    weeks: Sequence[int] | None = None,
    slot_eligibility: Mapping | None = None,
    points_model: PointsModel | None = None,
    owner_id: str | None = None,
    cache_scope: Sequence[str] | None = None,
    availability_basis: Mapping[str, Any] | None = None,
) -> MarginalBestBallUtility:
    """F(R) - F(R - {player} + {best free claim}) for one rostered player."""
    started = time.perf_counter()
    if not slots:
        return _unavailable(player_id, owner_id, params, weeks, "starter_slots_unresolved")
    if weeks is not None and not list(weeks):
        return _unavailable(player_id, owner_id, params, weeks, "no_remaining_fantasy_weeks")
    player = next((p for p in roster if p.player_id == player_id), None)
    if player is None:
        return _unavailable(player_id, owner_id, params, weeks, "player_not_on_roster")
    if player.ppg is None:
        # Removing an unprojected player changes nothing the simulation can
        # see; publishing that as a 0.0 marginal would be a fabricated zero.
        return _unavailable(player_id, owner_id, params, weeks, "player_unprojected")

    draws = int(params["draws"])
    seed = int(params["seed"])
    cap = int(params["candidatesPerSlotFamily"])
    band = materiality_band_ppg(params)
    roster_ids = [p.player_id for p in roster]
    families = opened_slot_families(player, slots, slot_eligibility)
    pool_ok = waiver_pool.state == "available"
    candidates = (
        select_candidates(
            families,
            waiver_pool.candidates,
            cap=cap,
            exclude_ids=roster_ids,
            slot_eligibility=slot_eligibility,
        )
        if pool_ok
        else []
    )
    without_player = [p for p in roster if p.player_id != player_id]
    before_stats = dict(_bbu.before_side_stats)

    def _evaluate(claim: UtilityPlayer | None) -> dict[str, Any]:
        roles = {player_id: "outgoing"}
        after = list(without_player)
        if claim is not None:
            roles[claim.player_id] = "incoming"
            after.append(claim)
        return evaluate_trade_utility(
            before=list(roster),
            after=after,
            slots=list(slots),
            roles=roles,
            slot_eligibility=slot_eligibility,
            points_model=points_model,
            draws=draws,
            seed=seed,
            weeks=None if weeks is None else list(weeks),
            availability_basis=availability_basis,
            cache_scope=cache_scope,
        )

    evaluated: list[tuple[UtilityPlayer | None, dict[str, Any]]] = []
    for claim in candidates or [None]:
        result = _evaluate(claim)
        if not result.get("available"):
            return _unavailable(
                player_id,
                owner_id,
                params,
                weeks,
                f"utility_unavailable:{result.get('unavailableReason')}",
            )
        evaluated.append((claim, result))

    # The re-solve decides: the claim whose roster scores best (ties by id).
    claim, best = min(
        evaluated,
        key=lambda cr: (-cr[1]["impact"]["ppg"], "" if cr[0] is None else cr[0].player_id),
    )
    impact = best["impact"]
    se = impact.get("standardError")
    delta = round(-float(impact["ppg"]), 2)
    after_runs = len(evaluated)
    stats_after = dict(_bbu.before_side_stats)

    if claim is None:
        if pool_ok:
            assumption = (
                "no priced free agent is eligible for any slot this player can fill "
                f"({', '.join(families) or 'none'}); the vacated spot stays empty"
            )
        else:
            assumption = (
                f"waiver pool {waiver_pool.state} ({waiver_pool.reason}); measured "
                "against an empty spot, so the delta is an upper bound"
            )
        replacement = ReplacementChoice(
            kind="none_available",
            player_id=None,
            ppg=None,
            contested=False,
            cost_assumption=FREE_WAIVER_COST_ASSUMPTION,
            assumption=assumption,
        )
    else:
        row = _row(best, claim.player_id) or {}
        # The claim's usable production (E[points x in lineup], published to
        # 2 dp) is zero: he only ever fills a slot on a tied zero week, so the
        # roster's own depth absorbs the vacated slot.  A missing row is not
        # zero, so it never takes this branch.
        contributes_nothing = row.get("usablePpgAfter") == 0.0
        if contributes_nothing:
            replacement = ReplacementChoice(
                kind="internal_promotion_only",
                player_id=None,
                ppg=None,
                contested=False,
                cost_assumption=FREE_WAIVER_COST_ASSUMPTION,
                assumption=(
                    f"the best eligible free agent ({claim.player_id}) adds no usable "
                    "points (under 0.005 ppg) in any simulated week; rostered depth "
                    "absorbs the vacated slot"
                ),
            )
        else:
            replacement = ReplacementChoice(
                kind="waiver_free_agent",
                player_id=claim.player_id,
                ppg=claim.ppg,
                contested=False,
                cost_assumption=FREE_WAIVER_COST_ASSUMPTION,
                assumption=(
                    "the vacated roster spot is filled by a free waiver claim of the "
                    "best simulated eligible free agent; FAAB cost and rival claims "
                    "are not modelled (one team in isolation)"
                ),
            )

    utility_basis = best.get("basis") or {}
    basis = {
        "modelVersion": MODEL_VERSION,
        "materialityBandPpg": band,
        "bandBasis": "materiality_prior_only",
        "precisionRule": "mcStandardError <= materialityBandPpg / 2",
        "openedSlotFamilies": list(families),
        "candidateCapPerFamily": cap,
        "candidatesEvaluated": [
            {
                "playerId": None if c is None else c.player_id,
                "position": None if c is None else c.position,
                "ppg": None if c is None else c.ppg,
                "impactPpg": r["impact"]["ppg"],
                "standardError": r["impact"].get("standardError"),
            }
            for c, r in evaluated
        ],
        # Rosters simulated for this player: the BEFORE roster plus one AFTER
        # roster per candidate.  The before side may be reused (cache_scope).
        "simulatedRosters": 1 + after_runs,
        "afterRuns": after_runs,
        "beforeSide": {
            "computed": stats_after.get("computed", 0) - before_stats.get("computed", 0),
            "reused": stats_after.get("reused", 0) - before_stats.get("reused", 0),
            "cacheScope": None if cache_scope is None else list(cache_scope),
        },
        "waiverPoolState": waiver_pool.state,
        "waiverPoolReason": waiver_pool.reason,
        "freeAgentsUnpriced": len(waiver_pool.unpriced_ids),
        "rosterUnprojectedIds": sorted(p.player_id for p in roster if p.ppg is None),
        "pointsModel": utility_basis.get("pointsModel"),
        "drawsPerWeek": utility_basis.get("drawsPerWeek"),
        "lineupSolver": utility_basis.get("lineupSolver"),
        "horizon": "current_season",
        "elapsedS": round(time.perf_counter() - started, 4),
    }
    return MarginalBestBallUtility(
        player_id=player_id,
        owner_id=owner_id,
        with_ppg=best["before"]["expectedLineupPpg"],
        without_ppg=best["after"]["expectedLineupPpg"],
        delta_ppg=delta,
        mc_standard_error=se,
        precision_ok=None if se is None else bool(se <= band / 2),
        predictive_sd=None,
        predictive_basis="unavailable",
        replacement=replacement,
        draws=int(utility_basis.get("draws", draws)),
        seed=seed,
        weeks=tuple(weeks or ()),
        param_set_id=str(params.get("paramSetId")),
        basis=basis,
        state="available" if pool_ok else "partial",
        reason=None if pool_ok else f"waiver_pool_unavailable:{waiver_pool.reason}",
    )


def marginal_bestball_utility_for_roster(
    roster: Sequence[UtilityPlayer],
    slots: Sequence[str],
    *,
    waiver_pool: WaiverPool,
    params: Mapping[str, Any],
    weeks: Sequence[int] | None = None,
    max_players: int | None = None,
    slot_eligibility: Mapping | None = None,
    points_model: PointsModel | None = None,
    owner_id: str | None = None,
    availability_basis: Mapping[str, Any] | None = None,
) -> RosterMarginals:
    """Marginals for a roster's projected players, highest ppg first.

    ``max_players`` caps how many projected players are simulated (cost).
    Unprojected players are listed as ``unavailable`` entries and cost no run.
    The before roster is shared across every player through the owner's
    content-addressed reuse (``cache_scope``), so the cost per player is one
    AFTER simulation per candidate.
    """
    started = time.perf_counter()
    projected = sorted(
        (p for p in roster if p.ppg is not None),
        key=lambda p: (-float(p.ppg), p.player_id),  # ppg filtered non-None
    )
    if max_players is not None:
        projected = projected[: max(0, int(max_players))]
    scope = ("bestball.marginal", str(owner_id))
    stats_before = dict(_bbu.before_side_stats)
    entries: list[MarginalBestBallUtility] = []
    runs = 0
    for p in projected:
        entry = marginal_bestball_utility(
            roster,
            p.player_id,
            slots,
            waiver_pool=waiver_pool,
            params=params,
            weeks=weeks,
            slot_eligibility=slot_eligibility,
            points_model=points_model,
            owner_id=owner_id,
            cache_scope=scope,
            availability_basis=availability_basis,
        )
        runs += int(entry.basis.get("afterRuns", 0))
        entries.append(entry)
    for p in sorted((p for p in roster if p.ppg is None), key=lambda p: p.player_id):
        entries.append(
            marginal_bestball_utility(
                roster,
                p.player_id,
                slots,
                waiver_pool=waiver_pool,
                params=params,
                weeks=weeks,
                owner_id=owner_id,
            )
        )
    stats_after = dict(_bbu.before_side_stats)
    return RosterMarginals(
        owner_id=owner_id,
        entries=tuple(entries),
        elapsed_s=round(time.perf_counter() - started, 4),
        runs=runs,
        basis={
            "modelVersion": MODEL_VERSION,
            "paramSetId": params.get("paramSetId"),
            "draws": int(params["draws"]),
            "seed": int(params["seed"]),
            "playersSimulated": len(projected),
            "playersUnprojected": sum(1 for p in roster if p.ppg is None),
            "afterRuns": runs,
            "beforeSide": {
                "computed": stats_after.get("computed", 0) - stats_before.get("computed", 0),
                "reused": stats_after.get("reused", 0) - stats_before.get("reused", 0),
            },
        },
    )
