"""Section: Franchise Pages.

Per-manager summaries within the 2-season window:
    * current display name + team-name history (aliases)
    * seasonsPlayed, cumulative wins/losses/ties, PF, PA
    * titles, finals appearances, playoff appearances
    * best / worst finish
    * top rival (highest rivalryIndex from rivalries section)
    * total trades, total waivers
    * current draft capital summary (owned picks + weighted stockpile)
    * award shelf placeholder (later prompt wires real awards)
"""
from __future__ import annotations

from typing import Any

from . import metrics
from .rivalries import build_section as build_rivalries
from .draft import weighted_stockpile_for_owner
from .snapshot import PublicLeagueSnapshot, SeasonSnapshot


def _roster_count_for(season: SeasonSnapshot, owner_id: str) -> dict[str, Any] | None:
    """Return {rosterId, teamName, settings} for the owner this season."""
    rid = None
    for r in season.rosters:
        if str(r.get("owner_id") or "") == owner_id:
            try:
                rid = int(r.get("roster_id"))
            except (TypeError, ValueError):
                rid = None
            break
    if rid is None:
        return None
    return {
        "rosterId": rid,
    }


def _top_rival_for(owner_id: str, rivalries_section: dict[str, Any]) -> dict[str, Any] | None:
    """Top rivalry for this owner, ranked by rivalryIndex."""
    best: dict[str, Any] | None = None
    for rec in rivalries_section.get("rivalries", []):
        if owner_id not in rec["ownerIds"]:
            continue
        if best is None or rec["rivalryIndex"] > best["rivalryIndex"]:
            best = rec
    if not best:
        return None
    other_idx = 1 if best["ownerIds"][0] == owner_id else 0
    return {
        "ownerId": best["ownerIds"][other_idx],
        "displayName": best["displayNames"][other_idx],
        "rivalryIndex": best["rivalryIndex"],
        "totalMeetings": best["totalMeetings"],
        "playoffMeetings": best["playoffMeetings"],
    }


def _trade_waiver_counts(snapshot: PublicLeagueSnapshot) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {}
    for season in snapshot.seasons:
        for tx in season.trades():
            for rid in tx.get("roster_ids") or []:
                owner_id = metrics.resolve_owner(snapshot.managers, season.league_id, rid)
                if not owner_id:
                    continue
                counts.setdefault(owner_id, {"trades": 0, "waivers": 0})
                counts[owner_id]["trades"] += 1
        for tx in season.waivers():
            for rid in tx.get("roster_ids") or []:
                owner_id = metrics.resolve_owner(snapshot.managers, season.league_id, rid)
                if not owner_id:
                    continue
                counts.setdefault(owner_id, {"trades": 0, "waivers": 0})
                counts[owner_id]["waivers"] += 1
    return counts


def _weekly_scoring_by_owner(
    snapshot: PublicLeagueSnapshot,
) -> dict[str, list[dict[str, Any]]]:
    """Flatten every scored roster-week into a per-owner trajectory.

    Returns ``{owner_id: [{season, week, isPlayoff, pointsFor}]}`` sorted
    chronologically.  Historical rosters aren't archived (see audit
    notes in PR), but every scored matchup already exposes a
    ``points`` field per roster-week, so per-week ``pointsFor`` is the
    fine-grained signal the franchise trajectory needs.  Weekly
    opponent ``pointsAgainst`` is available and stamped too for the
    frontend to do per-week margin rendering if it wants.
    """
    out: dict[str, list[dict[str, Any]]] = {}
    for season, wk, entry in metrics.walk_weekly_scores(snapshot, include_playoffs=True):
        roster_id = metrics.roster_id_of(entry)
        if roster_id is None:
            continue
        owner_id = metrics.resolve_owner(snapshot.managers, season.league_id, roster_id)
        if not owner_id:
            continue
        out.setdefault(owner_id, []).append(
            {
                "season": season.season,
                "week": int(wk),
                "isPlayoff": bool(wk >= season.playoff_week_start),
                "pointsFor": round(metrics.matchup_points(entry), 2),
            }
        )
    for rows in out.values():
        rows.sort(key=lambda r: (r["season"], r["week"]))
    return out


def build_section(snapshot: PublicLeagueSnapshot) -> dict[str, Any]:
    rivalries_section = build_rivalries(snapshot)
    trade_counts = _trade_waiver_counts(snapshot)

    # Per-owner weekly scoring trajectory — finer-grained than the
    # season-aggregate ``seasonResults`` below and the proper signal
    # for the franchise-trajectory chart.  Roster dollar value by
    # week isn't available (no historical roster archive), but weekly
    # pointsFor is a real historical signal that tracks how strong a
    # roster was every week, not just in aggregate.
    weekly_by_owner = _weekly_scoring_by_owner(snapshot)

    # Season-by-season per-owner aggregates.
    per_owner_season: dict[str, list[dict[str, Any]]] = {}
    cumulative: dict[str, dict[str, Any]] = {}

    for season in snapshot.seasons:
        standings = metrics.season_standings(season, snapshot.managers)
        placement = metrics.playoff_placement(season.winners_bracket)
        playoff_rids = set(metrics.playoff_teams(season.winners_bracket))

        for row in standings:
            owner_id = row["ownerId"]
            final_place = placement.get(row["rosterId"])
            made_playoffs = row["rosterId"] in playoff_rids
            per_owner_season.setdefault(owner_id, []).append({
                "season": season.season,
                "leagueId": season.league_id,
                "rosterId": row["rosterId"],
                "teamName": metrics.team_name(snapshot, season.league_id, row["rosterId"]),
                "wins": row["wins"],
                "losses": row["losses"],
                "ties": row["ties"],
                "pointsFor": row["pointsFor"],
                "pointsAgainst": row["pointsAgainst"],
                "standing": row["standing"],
                "finalPlace": final_place,
                "madePlayoffs": made_playoffs,
            })

            cum = cumulative.setdefault(owner_id, {
                "wins": 0,
                "losses": 0,
                "ties": 0,
                "pointsFor": 0.0,
                "pointsAgainst": 0.0,
                "seasonsPlayed": 0,
                "championships": 0,
                "finalsAppearances": 0,
                "playoffAppearances": 0,
                "regularSeasonFirstPlace": 0,
                "bestFinish": None,
                "worstFinish": None,
            })
            cum["wins"] += row["wins"]
            cum["losses"] += row["losses"]
            cum["ties"] += row["ties"]
            cum["pointsFor"] += row["pointsFor"]
            cum["pointsAgainst"] += row["pointsAgainst"]
            cum["seasonsPlayed"] += 1
            if made_playoffs:
                cum["playoffAppearances"] += 1
            if final_place == 1:
                cum["championships"] += 1
            if final_place in (1, 2):
                cum["finalsAppearances"] += 1
            if row["standing"] == 1:
                cum["regularSeasonFirstPlace"] += 1
            effective = final_place or row["standing"]
            if cum["bestFinish"] is None or effective < cum["bestFinish"]:
                cum["bestFinish"] = effective
            if cum["worstFinish"] is None or effective > cum["worstFinish"]:
                cum["worstFinish"] = effective

    detail: dict[str, dict[str, Any]] = {}
    index: list[dict[str, Any]] = []

    for owner_id, manager in snapshot.managers.by_owner_id.items():
        cum = cumulative.get(owner_id, {})
        capital = weighted_stockpile_for_owner(snapshot, owner_id)
        fr = {
            **manager.to_public_dict(),
            "cumulative": {
                "wins": cum.get("wins", 0),
                "losses": cum.get("losses", 0),
                "ties": cum.get("ties", 0),
                "pointsFor": round(cum.get("pointsFor", 0.0), 2),
                "pointsAgainst": round(cum.get("pointsAgainst", 0.0), 2),
                "seasonsPlayed": cum.get("seasonsPlayed", 0),
                "championships": cum.get("championships", 0),
                "finalsAppearances": cum.get("finalsAppearances", 0),
                "playoffAppearances": cum.get("playoffAppearances", 0),
                "regularSeasonFirstPlace": cum.get("regularSeasonFirstPlace", 0),
                "bestFinish": cum.get("bestFinish"),
                "worstFinish": cum.get("worstFinish"),
            },
            "seasonResults": sorted(
                per_owner_season.get(owner_id, []),
                key=lambda r: (r["season"], r["rosterId"]),
            ),
            "weeklyScoring": weekly_by_owner.get(owner_id, []),
            "topRival": _top_rival_for(owner_id, rivalries_section),
            "tradeCount": trade_counts.get(owner_id, {}).get("trades", 0),
            "waiverCount": trade_counts.get(owner_id, {}).get("waivers", 0),
            "draftCapital": capital,
            "awardShelf": [],
        }
        detail[owner_id] = fr
        index.append({
            "ownerId": owner_id,
            "displayName": fr["displayName"],
            "currentTeamName": fr["currentTeamName"],
            "avatar": fr.get("avatar") or "",
            "seasonsPlayed": fr["cumulative"]["seasonsPlayed"],
            "wins": fr["cumulative"]["wins"],
            "losses": fr["cumulative"]["losses"],
            "championships": fr["cumulative"]["championships"],
            "bestFinish": fr["cumulative"]["bestFinish"],
        })

    index.sort(
        key=lambda r: (
            -(r["championships"] or 0),
            r["bestFinish"] or 999,
            -(r["wins"] or 0),
            r["displayName"].lower(),
        )
    )
    return {"index": index, "detail": detail}


def build_franchise_detail(snapshot: PublicLeagueSnapshot, owner_id: str) -> dict[str, Any] | None:
    section = build_section(snapshot)
    return (section.get("detail") or {}).get(str(owner_id or "")) or None
