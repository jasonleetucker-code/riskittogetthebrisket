"""Pick Projector — future-pick → projected-draft-slot mapping.

Dynasty rookie-draft order is reverse final standings: the weakest
team picks 1.01.  This module projects that order for FUTURE seasons
from the ROS team-strength composite (``teamRosStrength`` in
``data/ros/team_strength/<league>.json``) and maps every owned future
pick (the overlay's ``pickDetails``) onto its projected slot — the
feature gap PFK's Pick Projector covers, built on our own playoff-sim
inputs.

Strictly a PROJECTION/CONTEXT layer: blended pick values (rookie-pool
tethering + the multiplicative future-year discount in the live
pipeline) are untouched.  Consumers render the projected slot next to
a pick, they do not re-value it.

League-scoped per CLAUDE.md: rosters/picks and team strength both
follow ``leagueKey`` — never collapse across leagues.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

# Confidence bands for a projected slot, derived from how isolated a
# team's strength score is from its immediate neighbors relative to
# the league's average inter-team gap.  A team wedged in a cluster
# can plausibly finish several slots away; a team far adrift of the
# pack is locked into its neighborhood.
_CONFIDENCE_HIGH_RATIO = 1.0
_CONFIDENCE_MEDIUM_RATIO = 0.4

_CONFIDENCE_ORDER = ("low", "medium", "high")

#: Ceiling on a pick's confidence by how many seasons out it is.
#:
#: WHY THIS EXISTS.  ``project_draft_order`` derives confidence purely
#: from how isolated a team's strength score is from its neighbours
#: **today**.  That is a sound answer to "how firmly is this team
#: ranked right now" and no answer at all to "where will its pick land
#: in three years", which is what a row labelled ``2029 1.01`` claims.
#:
#: Measured 2026-07-27 before this cap existed: a 2029 pick carried the
#: identical confidence distribution to a 2027 pick — {high 2, medium 6,
#: low 4} for all three seasons, and the same team read ``medium`` in
#: every one.  A field named ``confidence`` that cannot vary with the
#: horizon it is expressing confidence about is the name/predicate gap
#: this codebase keeps paying for.
#:
#: WHAT THIS IS NOT.  These ceilings are a STATED ASSUMPTION, not a
#: measurement.  Backtesting them needs multi-season team-strength
#: snapshots joined to realized final standings, and
#: ``data/ros/team_strength/`` holds only the current snapshot per
#: league — there is no history to fit against.  They are deliberately
#: conservative so the error is "we under-claimed" rather than "we
#: presented a three-year-out guess as high confidence".  Replace them
#: with a fitted curve once two seasons of snapshots exist.
_CONFIDENCE_CEILING_BY_HORIZON: dict[int, str] = {
    1: "high",  # next season — current strength is genuinely informative
    2: "medium",
}
_CONFIDENCE_CEILING_BEYOND = "low"


def _cap_confidence(confidence: str, seasons_out: int) -> str:
    """Lower ``confidence`` to the ceiling for ``seasons_out``.

    Never raises a confidence — a team in a tight cluster stays ``low``
    next season too.  The cap is a ceiling, not an assignment.
    """
    ceiling = _CONFIDENCE_CEILING_BY_HORIZON.get(seasons_out, _CONFIDENCE_CEILING_BEYOND)
    try:
        return min(confidence, ceiling, key=_CONFIDENCE_ORDER.index)
    except ValueError:  # unknown label — do not silently promote it
        return ceiling


def _to_float(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None  # NaN guard


def project_draft_order(strength_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Project the rookie-draft order from team-strength rows.

    Returns one row per team, sorted weakest-first (slot 1 = weakest
    projected team), each carrying::

        {rosterId, ownerId, teamName, teamRosStrength,
         projectedSlot, confidence}

    Teams missing a usable ``teamRosStrength`` are excluded (a slot
    built on an unknown score would be noise, not signal); callers
    can detect the shortfall by comparing lengths.  Ties break on
    rosterId for determinism.
    """
    usable: list[tuple[float, int, dict[str, Any]]] = []
    for row in strength_rows or []:
        if not isinstance(row, dict):
            continue
        strength = _to_float(row.get("teamRosStrength"))
        if strength is None:
            continue
        try:
            rid = int(row.get("rosterId") or 0)
        except (TypeError, ValueError):
            rid = 0
        usable.append((strength, rid, row))
    usable.sort(key=lambda t: (t[0], t[1]))

    strengths = [s for s, _rid, _row in usable]
    n = len(strengths)
    # Average inter-team gap — the yardstick for slot confidence.
    avg_gap = (
        (strengths[-1] - strengths[0]) / (n - 1) if n >= 2 and strengths[-1] > strengths[0] else 0.0
    )

    order: list[dict[str, Any]] = []
    for idx, (strength, rid, row) in enumerate(usable):
        if avg_gap <= 0:
            confidence = "low"
        else:
            gaps = []
            if idx > 0:
                gaps.append(strength - strengths[idx - 1])
            if idx < n - 1:
                gaps.append(strengths[idx + 1] - strength)
            min_gap = min(gaps) if gaps else 0.0
            ratio = min_gap / avg_gap
            if ratio >= _CONFIDENCE_HIGH_RATIO:
                confidence = "high"
            elif ratio >= _CONFIDENCE_MEDIUM_RATIO:
                confidence = "medium"
            else:
                confidence = "low"
        order.append(
            {
                "rosterId": rid,
                "ownerId": row.get("ownerId"),
                "teamName": row.get("teamName"),
                "teamRosStrength": strength,
                "projectedSlot": idx + 1,
                "confidence": confidence,
            }
        )
    return order


def build_pick_projections(
    teams: list[dict[str, Any]],
    strength_rows: list[dict[str, Any]],
    *,
    current_season: int | None = None,
) -> dict[str, Any]:
    """Project every owned FUTURE pick onto a draft slot.

    ``teams`` is the sleeper overlay's teams block (each carrying
    ``pickDetails`` — {season, round, original_roster_id,
    owner_roster_id, label}); ``strength_rows`` is the ROS
    team-strength snapshot.  Only seasons strictly AFTER
    ``current_season`` are projected — the current season's rookie
    draft order is actual standings, not a projection.

    Returns::

        {projectedOrder: [...], picks: [...], meta: {...}}

    where each pick row is::

        {season, round, projectedSlot, projectedPickNumber, label,
         confidence, ownerRosterId, ownerTeam,
         originalRosterId, originalTeam}
    """
    if current_season is None:
        current_season = datetime.now(timezone.utc).year

    order = project_draft_order(strength_rows)
    slot_by_rid = {row["rosterId"]: row for row in order}
    team_count = len(order)

    name_by_rid: dict[int, str] = {}
    for t in teams or []:
        if not isinstance(t, dict):
            continue
        try:
            rid = int(t.get("roster_id") or 0)
        except (TypeError, ValueError):
            continue
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
            try:
                season = int(str(pd.get("season") or 0))
                rnd = int(pd.get("round") or 0)
                original = int(pd.get("original_roster_id") or 0)
                owner = int(pd.get("owner_roster_id") or 0)
            except (TypeError, ValueError):
                continue
            if season <= current_season or rnd < 1 or not original or not owner:
                continue
            # The pick's slot follows the ORIGINAL team's projected
            # finish — that team's record sets where the pick lands.
            slot_row = slot_by_rid.get(original)
            if slot_row is None:
                unprojectable += 1
                continue
            slot = slot_row["projectedSlot"]
            seasons_out = season - current_season
            picks.append(
                {
                    "season": season,
                    "round": rnd,
                    "seasonsOut": seasons_out,
                    "projectedSlot": slot,
                    "projectedPickNumber": (rnd - 1) * team_count + slot,
                    "label": f"{season} {rnd}.{slot:02d}",
                    # Capped by horizon — see _CONFIDENCE_CEILING_BY_HORIZON.
                    # ``slotConfidence`` keeps the uncapped, today-only
                    # reading so a consumer can tell "this team is
                    # tightly ranked but the pick is far out" from "this
                    # team is in a scrum".
                    "confidence": _cap_confidence(slot_row["confidence"], seasons_out),
                    "slotConfidence": slot_row["confidence"],
                    "ownerRosterId": owner,
                    "ownerTeam": name_by_rid.get(owner),
                    "originalRosterId": original,
                    "originalTeam": name_by_rid.get(original),
                }
            )

    picks.sort(key=lambda p: (p["season"], p["round"], p["projectedSlot"]))
    return {
        "projectedOrder": order,
        "picks": picks,
        "meta": {
            "source": "teamRosStrength",
            "teamCount": team_count,
            "currentSeason": current_season,
            "unprojectablePicks": unprojectable,
        },
    }
