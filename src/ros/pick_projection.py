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
NO_DRAFT_ORDER_RULE = "no_draft_order_rule_for_league"
NO_SEASON_SIMULATION = "no_fresh_season_simulation"
#: Prefix; the simulation's own refusal reason follows a colon
#: (``season_simulation_unsimulable:no_games_played_and_none_scheduled``) —
#: preseason and the rollover-to-draft window land here, NOT on "no rule".
SIMULATION_UNSIMULABLE = "season_simulation_unsimulable"
NO_SLOT_DISTRIBUTION = "simulation_published_no_slot_distribution"
SIMULATION_RULE_MISMATCH = "simulation_rule_differs_from_league_rule"
SIMULATED_SEASON_UNKNOWN = "simulated_season_unknown"
SIMULATION_JOIN_INCOMPLETE = "simulation_owner_join_incomplete"
BEYOND_SIMULATED_SEASON = "class_beyond_simulated_season"
BEFORE_SIMULATED_SEASON = "class_before_simulated_season"
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


def _forecast_weight(sim_payload: Mapping[str, Any]) -> tuple[float, str]:
    """How far to trust the simulation, from the ONE owner of that answer.

    ``pick_market.provisional_confidence`` already decides how much the
    pick-value layer trusts this same simulation at this point of the season;
    the projector's confidence label uses the same weight so the two never
    disagree about one input (a week-3 forecast is not "high").
    """
    from src.trade.pick_market import provisional_confidence  # noqa: PLC0415

    progress = sim_payload.get("regularSeasonProgress")
    progress = progress if isinstance(progress, Mapping) else {}
    return provisional_confidence(progress.get("weeksFinal"), progress.get("weeksTotal"))


def rule_slot_forecasts(
    sim_payload: Mapping[str, Any] | None,
    teams: list[dict[str, Any]],
    *,
    league_rule: str | None = None,
    rule_known: bool = False,
) -> tuple[list[dict[str, Any]], int | None, str | None, dict[str, Any]]:
    """``(projectedOrder, draftYear, reason, weight)`` from the season simulation.

    ``league_rule`` is the canonical owner's answer for this league
    (``draft_order.league_draft_order_rule``) when ``rule_known``; otherwise the
    simulation's own ``draftOrderRule`` stamp stands in for it.

    ``projectedOrder`` has one row per simulated team, ordered by EXPECTED
    rule slot (ties on rosterId); ``projectedSlot`` is that position, so every
    slot is used exactly once.  Each row carries the full ``slotDistribution``
    (index 0 = slot 1), ``expectedSlot`` and ``mostLikelySlot``.  The order is
    all-or-nothing: if any simulated team cannot be joined or carries a
    malformed distribution, nothing is forecast — a partial order would
    compress every later slot.  ``reason`` names why nothing was forecast.
    """
    if rule_known and league_rule is None:
        return [], None, NO_DRAFT_ORDER_RULE, {}
    if not isinstance(sim_payload, Mapping):
        return [], None, NO_SEASON_SIMULATION, {}
    unsimulable = sim_payload.get("unsimulable")
    if unsimulable:
        why = unsimulable.get("reason") if isinstance(unsimulable, Mapping) else None
        return [], None, f"{SIMULATION_UNSIMULABLE}:{why or 'unspecified'}", {}
    sim_rule = sim_payload.get("draftOrderRule")
    if not sim_rule:
        # A league with a known rule whose simulation published no slot
        # output is a simulation gap, not "no rule".
        return [], None, (NO_SLOT_DISTRIBUTION if rule_known else NO_DRAFT_ORDER_RULE), {}
    if rule_known and sim_rule != league_rule:
        return [], None, SIMULATION_RULE_MISMATCH, {}
    season = _int(sim_payload.get("season"))
    if season is None:
        return [], None, SIMULATED_SEASON_UNKNOWN, {}
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

    sim_rows = [r for r in sim_payload.get("playoffOdds") or [] if isinstance(r, Mapping)]
    if not sim_rows:
        return [], draft_year, NO_SLOT_DISTRIBUTION, {}
    league_size = len(sim_rows)
    rows: list[dict[str, Any]] = []
    for r in sim_rows:
        dist = r.get("draftSlotDistribution")
        if not isinstance(dist, list):
            return [], draft_year, NO_SLOT_DISTRIBUTION, {}
        probs = [_to_float(p) for p in dist]
        total = sum(p for p in probs if p is not None)
        if len(probs) != league_size or any(p is None or p < 0 for p in probs) or total <= 0:
            return [], draft_year, NO_SLOT_DISTRIBUTION, {}
        rid = rid_by_owner.get(str(r.get("ownerId") or ""))
        if rid is None:
            return [], draft_year, SIMULATION_JOIN_INCOMPLETE, {}
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
    if len({row["rosterId"] for row in rows}) != league_size:
        return [], draft_year, SIMULATION_JOIN_INCOMPLETE, {}

    weight, basis = _forecast_weight(sim_payload)
    uniform = 1.0 / league_size
    rows.sort(key=lambda row: (row["expectedSlot"], row["rosterId"]))
    for idx, row in enumerate(rows):
        slot = idx + 1
        dist = row["slotDistribution"]
        lo = max(1, slot - CONFIDENCE_WINDOW)
        hi = min(league_size, slot + CONFIDENCE_WINDOW)
        raw_mass = sum(dist[i - 1] for i in range(lo, hi + 1))
        # The label reads the forecast SHRUNK by the same weight the pick
        # market uses: c x P + (1 - c) x uniform.
        mass = weight * raw_mass + (1.0 - weight) * uniform * (hi - lo + 1)
        row["projectedSlot"] = slot
        row["slotWindowProbability"] = round(raw_mass, 4)
        row["weightedWindowProbability"] = round(mass, 4)
        # No weight means no trust in the forecast at all, whatever share of
        # the league a one-slot window happens to cover.
        row["confidence"] = _confidence_from_mass(mass) if weight > 0 else "low"
    return (
        rows,
        draft_year,
        None,
        {"forecastWeight": round(weight, 4), "forecastWeightBasis": basis},
    )


def build_pick_projections(
    teams: list[dict[str, Any]],
    sim_payload: Mapping[str, Any] | None,
    *,
    league_key: str | None = None,
    current_season: int | None = None,
) -> dict[str, Any]:
    """Project every owned FUTURE pick onto a draft slot under the league's rule.

    ``teams`` is the sleeper overlay's teams block (each carrying
    ``pickDetails`` — {season, round, original_roster_id, owner_roster_id,
    label}); ``sim_payload`` is the league's season simulation (or ``None``).
    With ``league_key`` the league's rule comes from its canonical owner
    (``draft_order.league_draft_order_rule``); without it the simulation's
    stamp stands in.  Seasons at or before ``current_season`` are excluded
    (that draft's order is actual standings, not a projection);
    ``current_season`` defaults to the SIMULATED season, else the calendar
    year.

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
    league_rule: str | None = None
    rule_known = league_key is not None
    if rule_known:
        from src.public_league.draft_order import league_draft_order_rule  # noqa: PLC0415

        league_rule = league_draft_order_rule(league_key)
    order, draft_year, reason, weight = rule_slot_forecasts(
        sim_payload, teams, league_rule=league_rule, rule_known=rule_known
    )
    sim = sim_payload if isinstance(sim_payload, Mapping) else {}
    if current_season is None:
        sim_season = _int(sim.get("season"))
        current_season = sim_season if sim_season is not None else datetime.now(timezone.utc).year
    slot_by_rid = {row["rosterId"]: row for row in order}
    team_count = len(order)

    meta: dict[str, Any] = {
        "source": SLOT_SOURCE,
        "projectorVersion": PROJECTOR_VERSION,
        "draftOrderRule": league_rule if rule_known else (sim.get("draftOrderRule") or None),
        "simulatedSeason": sim.get("season"),
        "simulations": sim.get("n_simulations"),
        "regularSeasonProgress": sim.get("regularSeasonProgress"),
        "forecastDraftYear": draft_year if reason is None else None,
        "slotForecastUnavailableReason": reason,
        "teamCount": team_count,
        "currentSeason": current_season,
        "confidenceWindow": CONFIDENCE_WINDOW,
        **weight,
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
            season = _int(pd.get("season"))
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
            elif draft_year is not None and season > draft_year:
                row["slotForecastUnavailableReason"] = BEYOND_SIMULATED_SEASON
            elif draft_year is not None and season < draft_year:
                row["slotForecastUnavailableReason"] = BEFORE_SIMULATED_SEASON
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
