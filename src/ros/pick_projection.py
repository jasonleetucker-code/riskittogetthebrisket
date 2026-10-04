"""Pick Projector — future-pick → projected-draft-slot mapping.

WHICH TEAM PICKS WHERE is owned by the canonical draft-order rule
(``src/public_league/draft_order.py``; owner decision 2026-10-04: worst final
regular-season record first, ties by LOWER total Points For, recursively).
Predictive evidence may forecast a team's final record and Points For; only
that rule turns them into a slot.  So this module reads the league's SEASON
SIMULATION (``src/ros/playoff_sim.py``), which applies the rule in every
simulated season and publishes each team's ``draftSlotDistribution`` — it no
longer orders teams by Team Strength rank, which the rule names as a thing
that must not decide order.

What it publishes, per owned FUTURE pick (the overlay's ``pickDetails``):

* the class drafted after the SIMULATED season (``season + 1``): the slot
  distribution of the pick's ORIGINAL team, its expected slot, and a projected
  slot — the team's position when teams are ordered by expected rule slot;
* every LATER class: no slot forecast (``projectedSlot: None`` plus
  ``slotForecastUnavailableReason``).  No season beyond the simulated one is
  forecast, and Team Strength may not stand in for the rule;
* a league with no recorded rule, or no fresh simulation: no slot forecast for
  any class, with the reason named.

Strictly a PROJECTION/CONTEXT layer: blended pick values (rookie-pool
tethering + the future-year discount in the live pipeline) are untouched.

League-scoped per CLAUDE.md: rosters/picks and the simulation both follow
``leagueKey`` — never collapse across leagues.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from src.identity.picks import (
    PICK_OWNERSHIP_OBSERVED,
    PICK_OWNERSHIP_UNAVAILABLE,
    team_pick_ownership_unavailable_reason,
)

#: Version of the projector's method.  v2 (2026-10-04): slots come from the
#: season simulation under the canonical draft-order rule; v1 ordered teams by
#: Team Strength rank.
PROJECTOR_VERSION = "pick_projector_v2_draft_order_rule"

#: Where a projected slot comes from.
SLOT_SOURCE = "season_simulation"

#: Confidence of a projected slot = the simulated probability that the team
#: lands within ``CONFIDENCE_WINDOW`` slots of it.  The cut-offs are a STATED
#: PRIOR, not a fit: no realized draft order has been recorded against a
#: stored forecast yet (calibration is the pick-forecast capture follow-up in
#: docs/picks/DRAFT_ORDER_RULE.md).
CONFIDENCE_WINDOW = 1
CONFIDENCE_HIGH_MASS = 0.8
CONFIDENCE_MEDIUM_MASS = 0.5

_CONFIDENCE_ORDER = ("low", "medium", "high")

#: Ceiling on a pick's confidence by how many seasons out it is.  Only the
#: class right after the simulated season is ever forecast today, so the cap
#: binds only if that class is more than one season out; it is kept so a
#: confidence can never outrun its horizon if forecasting is extended.
#: A STATED ASSUMPTION, not a measurement (see the forecast-capture
#: follow-up).
_CONFIDENCE_CEILING_BY_HORIZON: dict[int, str] = {
    1: "high",  # next season — the simulation is genuinely informative
    2: "medium",
}
_CONFIDENCE_CEILING_BEYOND = "low"

#: Public names for the projector's parameters, so a consumer that must RECORD
#: the model identity (``src/ros/pick_forecast_snapshot.py``) reads them
#: without reaching into private constants.
CONFIDENCE_CEILING_BY_HORIZON = _CONFIDENCE_CEILING_BY_HORIZON
CONFIDENCE_CEILING_BEYOND = _CONFIDENCE_CEILING_BEYOND

#: Why a pick carries no slot forecast.  Named so "not forecast" and "unknown
#: input" never read the same, and never as slot 0.
NO_SEASON_SIMULATION = "no_fresh_season_simulation"
NO_DRAFT_ORDER_RULE = "no_draft_order_rule_for_league"
NO_SLOT_DISTRIBUTION = "simulation_published_no_slot_distribution"
SIMULATED_SEASON_UNKNOWN = "simulated_season_unknown"
BEYOND_SIMULATED_SEASON = "class_beyond_simulated_season"
ORIGIN_NOT_SIMULATED = "originating_team_not_in_simulation"


def _cap_confidence(confidence: str, seasons_out: int) -> str:
    """Lower ``confidence`` to the ceiling for ``seasons_out``.

    Never raises a confidence.  The cap is a ceiling, not an assignment.
    """
    ceiling = _CONFIDENCE_CEILING_BY_HORIZON.get(seasons_out, _CONFIDENCE_CEILING_BEYOND)
    try:
        return min(confidence, ceiling, key=_CONFIDENCE_ORDER.index)
    except ValueError:  # unknown label — do not silently promote it
        return ceiling


def _to_float(v: Any) -> float | None:
    if isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None  # NaN guard


def _int(v: Any) -> int | None:
    if isinstance(v, bool):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _confidence_from_mass(mass: float) -> str:
    if mass >= CONFIDENCE_HIGH_MASS:
        return "high"
    if mass >= CONFIDENCE_MEDIUM_MASS:
        return "medium"
    return "low"


def rule_slot_forecasts(
    sim_payload: Mapping[str, Any] | None,
    teams: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int | None, str | None]:
    """``(projectedOrder, draftYear, reason)`` from the season simulation.

    ``projectedOrder`` has one row per simulated team, ordered by EXPECTED
    rule slot (ties on rosterId); ``projectedSlot`` is that position, so every
    slot is used exactly once.  Each row carries the full
    ``slotDistribution`` (index 0 = slot 1), ``expectedSlot`` and
    ``mostLikelySlot``.  ``reason`` names why nothing could be forecast; the
    order is then empty and ``draftYear`` may be ``None``.
    """
    if not isinstance(sim_payload, Mapping):
        return [], None, NO_SEASON_SIMULATION
    if not sim_payload.get("draftOrderRule"):
        return [], None, NO_DRAFT_ORDER_RULE
    season = _int(sim_payload.get("season"))
    if season is None:
        return [], None, SIMULATED_SEASON_UNKNOWN
    draft_year = season + 1

    rid_by_owner: dict[str, int] = {}
    name_by_rid: dict[int, str] = {}
    for t in teams or []:
        if not isinstance(t, dict):
            continue
        rid = _int(t.get("roster_id"))
        if not rid:
            continue
        name_by_rid[rid] = str(t.get("name") or f"Team {rid}")
        owner = t.get("ownerId")
        if isinstance(owner, str) and owner:
            rid_by_owner[owner] = rid

    rows: list[dict[str, Any]] = []
    for r in sim_payload.get("playoffOdds") or []:
        if not isinstance(r, Mapping):
            continue
        dist = r.get("draftSlotDistribution")
        rid = rid_by_owner.get(str(r.get("ownerId") or ""))
        if rid is None or not isinstance(dist, list) or not dist:
            continue
        probs = [_to_float(p) for p in dist]
        if any(p is None or p < 0 for p in probs):
            continue
        total = sum(probs)  # type: ignore[arg-type]
        if total <= 0:
            continue
        probs = [p / total for p in probs]  # type: ignore[operator]
        expected = sum((i + 1) * p for i, p in enumerate(probs))
        most_likely = max(range(len(probs)), key=lambda i: (probs[i], -i)) + 1
        rows.append(
            {
                "rosterId": rid,
                "ownerId": r.get("ownerId"),
                "teamName": name_by_rid.get(rid),
                "expectedSlot": round(expected, 3),
                "mostLikelySlot": most_likely,
                "slotDistribution": [round(p, 4) for p in probs],
                "finalWins": r.get("finalWins"),
                "finalPointsFor": r.get("finalPointsFor"),
            }
        )
    if not rows:
        return [], draft_year, NO_SLOT_DISTRIBUTION

    rows.sort(key=lambda row: (row["expectedSlot"], row["rosterId"]))
    for idx, row in enumerate(rows):
        slot = idx + 1
        dist = row["slotDistribution"]
        lo = max(1, slot - CONFIDENCE_WINDOW)
        hi = min(len(dist), slot + CONFIDENCE_WINDOW)
        mass = sum(dist[i - 1] for i in range(lo, hi + 1))
        row["projectedSlot"] = slot
        row["slotWindowProbability"] = round(mass, 4)
        row["confidence"] = _confidence_from_mass(mass)
    return rows, draft_year, None


def build_pick_projections(
    teams: list[dict[str, Any]],
    sim_payload: Mapping[str, Any] | None,
    *,
    current_season: int | None = None,
) -> dict[str, Any]:
    """Project every owned FUTURE pick onto a draft slot under the league's rule.

    ``teams`` is the sleeper overlay's teams block (each carrying
    ``pickDetails`` — {season, round, original_roster_id, owner_roster_id,
    label}); ``sim_payload`` is the league's season simulation (or ``None``).
    Seasons at or before ``current_season`` are excluded (that draft's order
    is actual standings, not a projection).  ``current_season`` defaults to
    the SIMULATED season, else the calendar year.

    Returns ``{projectedOrder: [...], picks: [...], meta: {...}}``; a pick row
    is::

        {season, round, seasonsOut, projectedSlot, projectedPickNumber, label,
         confidence, slotConfidence, expectedSlot, slotDistribution,
         slotForecastUnavailableReason, ownerRosterId, ownerTeam,
         originalRosterId, originalTeam}

    with ``projectedSlot`` / ``projectedPickNumber`` / ``confidence``
    ``None`` whenever no slot forecast exists — never slot 0.

    Ownership UNKNOWN is refused, never projected as zero picks: when any
    team's pick ownership is unavailable, ``picks`` is ``None`` and ``meta``
    carries ``pickOwnershipState`` / ``pickOwnershipReason``.
    ``projectedOrder`` is still served: it does not depend on ownership.
    """
    order, draft_year, reason = rule_slot_forecasts(sim_payload, teams)
    if current_season is None:
        sim_season = _int(sim_payload.get("season")) if isinstance(sim_payload, Mapping) else None
        current_season = sim_season if sim_season is not None else datetime.now(timezone.utc).year
    slot_by_rid = {row["rosterId"]: row for row in order}
    team_count = len(order)

    meta: dict[str, Any] = {
        "source": SLOT_SOURCE,
        "projectorVersion": PROJECTOR_VERSION,
        "draftOrderRule": (
            sim_payload.get("draftOrderRule") if isinstance(sim_payload, Mapping) else None
        ),
        "simulatedSeason": (
            sim_payload.get("season") if isinstance(sim_payload, Mapping) else None
        ),
        "simulations": (
            sim_payload.get("n_simulations") if isinstance(sim_payload, Mapping) else None
        ),
        "regularSeasonProgress": (
            sim_payload.get("regularSeasonProgress") if isinstance(sim_payload, Mapping) else None
        ),
        "forecastDraftYear": draft_year if reason is None else None,
        "slotForecastUnavailableReason": reason,
        "teamCount": team_count,
        "currentSeason": current_season,
        "confidenceWindow": CONFIDENCE_WINDOW,
    }

    ownership_reasons = sorted(
        {r for t in teams or [] if (r := team_pick_ownership_unavailable_reason(t)) is not None}
    )
    if ownership_reasons:
        return {
            "projectedOrder": order,
            "picks": None,
            "meta": {
                **meta,
                "unprojectablePicks": None,
                "pickOwnershipState": PICK_OWNERSHIP_UNAVAILABLE,
                "pickOwnershipReason": ownership_reasons[0]
                if len(ownership_reasons) == 1
                else ",".join(ownership_reasons),
            },
        }

    name_by_rid: dict[int, str] = {}
    for t in teams or []:
        if not isinstance(t, dict):
            continue
        rid = _int(t.get("roster_id"))
        if rid:
            name_by_rid[rid] = str(t.get("name") or f"Team {rid}")

    picks: list[dict[str, Any]] = []
    unprojectable = 0
    for t in teams or []:
        if not isinstance(t, dict):
            continue
        for pd in t.get("pickDetails") or []:
            if not isinstance(pd, dict):
                continue
            season = _int(str(pd.get("season") or 0))
            rnd = _int(pd.get("round"))
            original = _int(pd.get("original_roster_id"))
            owner = _int(pd.get("owner_roster_id"))
            if season is None or rnd is None or season <= current_season or rnd < 1:
                continue
            if not original or not owner:
                continue
            seasons_out = season - current_season
            row: dict[str, Any] = {
                "season": season,
                "round": rnd,
                "seasonsOut": seasons_out,
                "projectedSlot": None,
                "projectedPickNumber": None,
                "label": f"{season} Round {rnd}",
                "confidence": None,
                "slotConfidence": None,
                "expectedSlot": None,
                "slotDistribution": None,
                "slotForecastUnavailableReason": None,
                "ownerRosterId": owner,
                "ownerTeam": name_by_rid.get(owner),
                "originalRosterId": original,
                "originalTeam": name_by_rid.get(original),
            }
            if reason is not None:
                row["slotForecastUnavailableReason"] = reason
            elif season != draft_year:
                row["slotForecastUnavailableReason"] = BEYOND_SIMULATED_SEASON
            elif original not in slot_by_rid:
                # The pick's slot follows the ORIGINAL team's final record.
                row["slotForecastUnavailableReason"] = ORIGIN_NOT_SIMULATED
                unprojectable += 1
            else:
                slot_row = slot_by_rid[original]
                slot = slot_row["projectedSlot"]
                row.update(
                    {
                        "projectedSlot": slot,
                        "projectedPickNumber": (rnd - 1) * team_count + slot,
                        "label": f"{season} {rnd}.{slot:02d}",
                        # Capped by horizon — see _CONFIDENCE_CEILING_BY_HORIZON.
                        # ``slotConfidence`` keeps the uncapped reading.
                        "confidence": _cap_confidence(slot_row["confidence"], seasons_out),
                        "slotConfidence": slot_row["confidence"],
                        "expectedSlot": slot_row["expectedSlot"],
                        "slotDistribution": slot_row["slotDistribution"],
                    }
                )
            picks.append(row)

    picks.sort(
        key=lambda p: (
            p["season"],
            p["round"],
            p["projectedSlot"] if p["projectedSlot"] is not None else 10**6,
            p["originalRosterId"],
        )
    )
    meta.update(
        {
            "unprojectablePicks": unprojectable,
            "pickOwnershipState": PICK_OWNERSHIP_OBSERVED,
            "pickOwnershipReason": None,
        }
    )
    return {"projectedOrder": order, "picks": picks, "meta": meta}
