"""Section: Weekly Recap Newsletter.

Auto-generates a narrative-grade recap for every completed scored week
in the snapshot:

    * Headline — single sentence capturing the week's dominant story.
    * Summary — 2-3 sentences with standings implication, star of the
      week, and the biggest surprise.
    * Superlatives — blowout / nailbiter / MVP / bust / bad beat.
    * Per-matchup one-liners with winner, margin, highlight.
    * Trades that were completed during the week's transaction leg.

The recap is pre-computed in one pass per snapshot so the dynamic
``/league/week/[season]/[week]`` route can fetch the public contract
and pick its record out by key in O(1).

Output shape
────────────
``seasonsCovered``  — passthrough.
``weeks``           — list of per-week recap dicts, ordered newest first.
``byKey``           — flat ``{"<season>:<week>": recap}`` map for
                      O(1) lookup from the dynamic route.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from . import metrics
from .snapshot import PublicLeagueSnapshot, SeasonSnapshot


def _side_entry(snapshot: PublicLeagueSnapshot, season: SeasonSnapshot, entry: dict[str, Any]) -> dict[str, Any]:
    rid = metrics.roster_id_of(entry)
    owner_id = metrics.resolve_owner(snapshot.managers, season.league_id, rid)
    return {
        "ownerId": owner_id,
        "rosterId": rid,
        "displayName": metrics.display_name_for(snapshot, owner_id) if owner_id else "",
        "teamName": metrics.team_name(snapshot, season.league_id, rid),
        "points": round(metrics.matchup_points(entry), 2),
    }


def _season_sort_key(season: str) -> int:
    try:
        return int(season)
    except (TypeError, ValueError):
        return 0


def _weekly_trades_for(
    season: SeasonSnapshot,
    snapshot: PublicLeagueSnapshot,
    week: int,
) -> list[dict[str, Any]]:
    """Return completed trades whose transaction ``leg`` matches ``week``.

    We deliberately expose only rosterIds and counts, not asset details
    — the ``activity`` section already carries the full trade payload
    with grades.  The recap is a pointer into that surface.
    """
    out: list[dict[str, Any]] = []
    for tx in season.trades():
        try:
            leg = int(tx.get("_leg") or tx.get("leg") or 0)
        except (TypeError, ValueError):
            leg = 0
        if leg != week:
            continue
        roster_ids = tx.get("roster_ids") or []
        parties = []
        for rid in roster_ids:
            oid = metrics.resolve_owner(snapshot.managers, season.league_id, rid)
            if oid:
                parties.append({
                    "ownerId": oid,
                    "displayName": metrics.display_name_for(snapshot, oid),
                })
        adds = tx.get("adds")
        assets_moved = len(adds) if isinstance(adds, dict) else 0
        picks_moved = len(tx.get("draft_picks") or [])
        out.append({
            "transactionId": tx.get("transaction_id"),
            "parties": parties,
            "assetsMoved": assets_moved,
            "picksMoved": picks_moved,
        })
    return out


def _matchup_oneliner(home: dict, away: dict, margin: float) -> str:
    if home["points"] == away["points"]:
        return f"{home['displayName']} and {away['displayName']} finished deadlocked at {home['points']:.1f}."
    winner, loser = (home, away) if home["points"] > away["points"] else (away, home)
    if margin < 3:
        return f"{winner['displayName']} edged {loser['displayName']} by {margin:.1f} in a nailbiter."
    if margin >= 50:
        return f"{winner['displayName']} obliterated {loser['displayName']} by {margin:.1f}."
    if margin >= 25:
        return f"{winner['displayName']} rolled {loser['displayName']} by {margin:.1f}."
    return f"{winner['displayName']} beat {loser['displayName']} by {margin:.1f}."


def _headline(recap: dict[str, Any]) -> str:
    # Prefer the blowout if it's meaningful; else the MVP; else nailbiter.
    blowout = recap.get("blowout")
    nailbiter = recap.get("nailBiter")
    mvp = recap.get("mvp")
    if blowout and blowout["margin"] >= 40:
        return (
            f"{blowout['winner']['displayName']} steamrolled "
            f"{blowout['loser']['displayName']} by {blowout['margin']:.1f}"
        )
    if mvp and blowout and mvp["ownerId"] == blowout["winner"]["ownerId"]:
        return (
            f"{mvp['displayName']} dropped {mvp['points']:.1f} in a "
            f"{blowout['margin']:.1f}-point win"
        )
    if nailbiter and nailbiter["margin"] < 2:
        return (
            f"{nailbiter['winner']['displayName']} survived "
            f"{nailbiter['loser']['displayName']} by {nailbiter['margin']:.2f}"
        )
    if mvp:
        return f"{mvp['displayName']} led the week with {mvp['points']:.1f}"
    return "Week in review"


def _summary(recap: dict[str, Any]) -> str:
    parts: list[str] = []
    mvp = recap.get("mvp")
    bust = recap.get("bust")
    badBeat = recap.get("badBeat")
    blowout = recap.get("blowout")
    nailbiter = recap.get("nailBiter")
    trades_count = len(recap.get("trades") or [])

    if mvp:
        parts.append(
            f"{mvp['displayName']} led the league with {mvp['points']:.1f} points."
        )
    if nailbiter and (not blowout or nailbiter["margin"] < blowout["margin"] / 10):
        parts.append(
            f"The closest game was {nailbiter['winner']['displayName']} over "
            f"{nailbiter['loser']['displayName']} by just {nailbiter['margin']:.2f}."
        )
    elif blowout:
        parts.append(
            f"Biggest margin: {blowout['winner']['displayName']} over "
            f"{blowout['loser']['displayName']} by {blowout['margin']:.1f}."
        )
    if badBeat and badBeat["points"] > (mvp["points"] if mvp else 0) - 5:
        parts.append(
            f"{badBeat['displayName']} took a bad beat — {badBeat['points']:.1f} "
            f"points and still lost by {badBeat['marginOfLoss']:.1f}."
        )
    elif bust:
        parts.append(
            f"{bust['displayName']} bottomed out at {bust['points']:.1f}."
        )
    if trades_count:
        parts.append(
            f"{trades_count} trade{'s' if trades_count != 1 else ''} cleared on the wire."
        )
    return " ".join(parts) or "Recap unavailable."


def _build_week_recap(
    snapshot: PublicLeagueSnapshot,
    season: SeasonSnapshot,
    week: int,
) -> dict[str, Any] | None:
    entries = season.matchups_by_week.get(week) or []
    pairs = metrics.matchup_pairs(entries)
    if not pairs:
        return None
    # Require at least one scored pair (skip fully unscored future weeks).
    scored_pairs = [
        (a, b) for a, b in pairs
        if metrics.is_scored(a) or metrics.is_scored(b)
    ]
    if not scored_pairs:
        return None

    is_playoff = week >= season.playoff_week_start
    matchup_rows: list[dict[str, Any]] = []
    highest: dict[str, Any] | None = None
    lowest: dict[str, Any] | None = None
    biggest: dict[str, Any] | None = None
    closest: dict[str, Any] | None = None
    bad_beat: dict[str, Any] | None = None

    for a, b in scored_pairs:
        home = _side_entry(snapshot, season, a)
        away = _side_entry(snapshot, season, b)
        if home["points"] == 0 and away["points"] == 0:
            continue
        margin = round(abs(home["points"] - away["points"]), 2)
        if home["points"] > away["points"]:
            winner, loser = home, away
        elif away["points"] > home["points"]:
            winner, loser = away, home
        else:
            winner = None
            loser = None

        row = {
            "matchupId": a.get("matchup_id"),
            "home": home,
            "away": away,
            "margin": margin,
            "winner": winner,
            "loser": loser,
            "oneliner": _matchup_oneliner(home, away, margin),
        }
        matchup_rows.append(row)

        for side in (home, away):
            if highest is None or side["points"] > highest["points"]:
                highest = side
            if lowest is None or side["points"] < lowest["points"]:
                lowest = side
        if winner and (biggest is None or margin > biggest["margin"]):
            biggest = {
                "winner": winner,
                "loser": loser,
                "margin": margin,
                "oneliner": row["oneliner"],
            }
        if winner and (closest is None or margin < closest["margin"]):
            closest = {
                "winner": winner,
                "loser": loser,
                "margin": margin,
                "oneliner": row["oneliner"],
            }
        # Bad beat: highest-scoring loser.
        if loser:
            candidate = {
                "ownerId": loser["ownerId"],
                "displayName": loser["displayName"],
                "teamName": loser["teamName"],
                "points": loser["points"],
                "marginOfLoss": margin,
                "winnerOwnerId": winner["ownerId"],
                "winnerDisplayName": winner["displayName"],
            }
            if bad_beat is None or candidate["points"] > bad_beat["points"]:
                bad_beat = candidate

    if not matchup_rows:
        return None

    trades = _weekly_trades_for(season, snapshot, week)

    recap: dict[str, Any] = {
        "season": season.season,
        "leagueId": season.league_id,
        "week": week,
        "isPlayoff": is_playoff,
        "matchups": matchup_rows,
        "blowout": biggest,
        "nailBiter": closest,
        "mvp": highest,
        "bust": lowest,
        "badBeat": bad_beat,
        "trades": trades,
    }
    recap["headline"] = _headline(recap)
    recap["summary"] = _summary(recap)
    return recap


def build_section(snapshot: PublicLeagueSnapshot) -> dict[str, Any]:
    seasons_sorted = sorted(
        snapshot.seasons, key=lambda s: _season_sort_key(s.season)
    )

    weeks_out: list[dict[str, Any]] = []
    by_key: dict[str, dict[str, Any]] = {}

    for season in seasons_sorted:
        for wk in sorted(season.matchups_by_week.keys()):
            recap = _build_week_recap(snapshot, season, wk)
            if not recap:
                continue
            weeks_out.append(recap)
            by_key[f"{season.season}:{wk}"] = recap

    # Newest first for the list view.
    weeks_out.sort(
        key=lambda r: (_season_sort_key(r["season"]), r["week"]),
        reverse=True,
    )

    return {
        "seasonsCovered": [s.season for s in snapshot.seasons],
        "weeks": weeks_out,
        "byKey": by_key,
        "latest": weeks_out[0] if weeks_out else None,
    }
