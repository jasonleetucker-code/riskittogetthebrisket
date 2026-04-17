"""Section: Home / Overview.

Derived, headline-level summary that front-loads the public /league
page with the most interesting facts so visitors immediately see
something worth clicking.  Every value here is derived from the
existing sections — this module never walks the raw snapshot.

Populated blocks:
    * currentChampion — defending champion of the most recent COMPLETE
      season (or null if no completed season exists).
    * featuredRivalry — rivalries section's #1 pair (the rivalry index
      winner, ties broken by total meetings).
    * topRecordCallouts — a small rotation of banner records:
      highest weekly score, biggest margin, most points in a season,
      longest win streak.
    * hottestRace — the current-season award race most worth
      highlighting (award engine chose this; we surface it here for
      the home card).
    * recentTrades — up to 5 most recent trades, slimmed for the card.
    * draftCapitalLeader — top weighted stockpile.
    * latestWeeklyRecap — most recent scored week across the 2-season
      window, plus one-line highlights (Game of the Week, Blowout,
      High Scorer).
    * mostDecoratedFranchise — #1 hall of fame row.
    * hottestTrade — biggest blockbuster (or null).
    * seasonRange — friendly label like "2024 – 2025".
    * leagueVitals — small badge summary (games played, total trades,
      total waivers).
"""
from __future__ import annotations

from typing import Any

from . import metrics
from .snapshot import PublicLeagueSnapshot


def _season_range_label(snapshot: PublicLeagueSnapshot) -> str:
    ids = [s.season for s in snapshot.seasons if s.season]
    if not ids:
        return ""
    if len(ids) == 1:
        return ids[0]
    try:
        years = sorted(int(x) for x in ids)
        if len(years) >= 2:
            return f"{years[0]}\u2013{years[-1]}"
    except ValueError:
        pass
    return f"{ids[-1]}\u2013{ids[0]}"


def _current_champion(history_section: dict[str, Any]) -> dict[str, Any] | None:
    champs = history_section.get("championsBySeason") or []
    if not champs:
        return None
    # Champions are emitted season-by-season in snapshot order (current
    # → previous).  Pick the most recent champion we actually have.
    return dict(champs[0])


def _featured_rivalry(rivalries_section: dict[str, Any]) -> dict[str, Any] | None:
    rivalries = rivalries_section.get("rivalries") or []
    if not rivalries:
        return None
    head = rivalries[0]
    return {
        "ownerIds": head["ownerIds"],
        "displayNames": head.get("displayNames") or [],
        "rivalryIndex": head["rivalryIndex"],
        "totalMeetings": head["totalMeetings"],
        "playoffMeetings": head["playoffMeetings"],
        "winsA": head["winsA"],
        "winsB": head["winsB"],
        "ties": head["ties"],
        "lastMeeting": head.get("lastMeeting"),
    }


def _top_record_callouts(records_section: dict[str, Any]) -> list[dict[str, Any]]:
    callouts: list[dict[str, Any]] = []

    def _push(kind: str, label: str, rows: list[dict[str, Any]], value_key: str, units: str = ""):
        if not rows:
            return
        row = rows[0]
        value = row.get(value_key)
        if isinstance(value, float):
            formatted = f"{value:g}"
        else:
            formatted = str(value or "")
        callouts.append({
            "kind": kind,
            "label": label,
            "value": value,
            "formattedValue": formatted + (f" {units}" if units else ""),
            "ownerId": row.get("ownerId"),
            "displayName": row.get("teamName") or row.get("displayName"),
            "season": row.get("season"),
            "week": row.get("week"),
        })

    _push("highest_single_week", "Highest week", records_section.get("singleWeekHighest") or [], "points", "pts")
    _push("biggest_margin", "Biggest blowout", records_section.get("biggestMargin") or [], "margin", "pts")
    _push("most_points_in_season", "Most season points", records_section.get("mostPointsInSeason") or [], "totalPoints", "pts")
    if records_section.get("longestWinStreaks"):
        head = records_section["longestWinStreaks"][0]
        callouts.append({
            "kind": "longest_win_streak",
            "label": "Longest win streak",
            "value": head["length"],
            "formattedValue": f"{head['length']} straight",
            "ownerId": head.get("ownerId"),
            "displayName": head.get("displayName"),
            "season": None,
            "week": None,
        })
    return callouts


def _recent_trades(activity_section: dict[str, Any], n: int = 5) -> list[dict[str, Any]]:
    feed = activity_section.get("feed") or []
    return [
        {
            "transactionId": t["transactionId"],
            "season": t["season"],
            "week": t.get("week"),
            "totalAssets": t["totalAssets"],
            "sides": [
                {
                    "ownerId": s["ownerId"],
                    "displayName": s.get("displayName") or s.get("teamName"),
                    "receivedPlayerCount": s.get("receivedPlayerCount", 0),
                    "receivedPickCount": s.get("receivedPickCount", 0),
                }
                for s in t.get("sides", [])
            ],
        }
        for t in feed[:n]
    ]


def _hottest_trade(activity_section: dict[str, Any]) -> dict[str, Any] | None:
    blockbusters = activity_section.get("biggestBlockbusters") or []
    if not blockbusters:
        return None
    head = blockbusters[0]
    return {
        "transactionId": head["transactionId"],
        "season": head["season"],
        "week": head.get("week"),
        "totalAssets": head["totalAssets"],
        "notableAssetCount": head.get("notableAssetCount", 0),
        "sides": [
            {
                "ownerId": s["ownerId"],
                "displayName": s.get("displayName") or s.get("teamName"),
                "receivedPlayerCount": s.get("receivedPlayerCount", 0),
                "receivedPickCount": s.get("receivedPickCount", 0),
            }
            for s in head.get("sides", [])
        ],
    }


def _draft_capital_leader(draft_section: dict[str, Any]) -> dict[str, Any] | None:
    board = draft_section.get("stockpileLeaderboard") or []
    if not board:
        return None
    head = board[0]
    return {
        "ownerId": head["ownerId"],
        "displayName": head["displayName"],
        "weightedScore": head["weightedScore"],
        "totalPicks": head["totalPicks"],
    }


def _latest_weekly_recap(weekly_section: dict[str, Any]) -> dict[str, Any] | None:
    weeks = weekly_section.get("weeks") or []
    if not weeks:
        return None
    # Already sorted descending by (season, week).
    head = weeks[0]
    highlights = head.get("highlights") or {}
    return {
        "season": head["season"],
        "week": head["week"],
        "isPlayoff": head.get("isPlayoff", False),
        "gameOfTheWeek": highlights.get("gameOfTheWeek"),
        "blowoutOfTheWeek": highlights.get("blowoutOfTheWeek"),
        "highestScorer": highlights.get("highestScorer"),
        "lowestScorer": highlights.get("lowestScorer"),
        "upsetOfTheWeek": highlights.get("upsetOfTheWeek"),
        "standingsMover": highlights.get("standingsMover"),
    }


def _most_decorated_franchise(history_section: dict[str, Any]) -> dict[str, Any] | None:
    hof = history_section.get("hallOfFame") or []
    if not hof:
        return None
    head = hof[0]
    return {
        "ownerId": head["ownerId"],
        "displayName": head["displayName"],
        "currentTeamName": head.get("currentTeamName"),
        "championships": head.get("championships", 0),
        "finalsAppearances": head.get("finalsAppearances", 0),
        "playoffAppearances": head.get("playoffAppearances", 0),
        "wins": head.get("wins", 0),
        "losses": head.get("losses", 0),
        "pointsFor": head.get("pointsFor", 0.0),
    }


def _most_chaotic_manager(awards_section: dict[str, Any]) -> dict[str, Any] | None:
    races = awards_section.get("awardRaces") or []
    for race in races:
        if race["key"] == "chaos_agent" and race.get("leaders"):
            leader = race["leaders"][0]
            return {
                "ownerId": leader["ownerId"],
                "displayName": leader["displayName"],
                "score": leader["value"].get("score"),
            }
    # Fallback to the most-recent season's historical chaos winner.
    for season_row in awards_section.get("bySeason") or []:
        for a in season_row.get("awards", []):
            if a["key"] == "chaos_agent":
                val = a.get("value") or {}
                return {
                    "ownerId": a["ownerId"],
                    "displayName": a["displayName"],
                    "score": val.get("score"),
                    "season": season_row["season"],
                }
    return None


def _league_vitals(snapshot: PublicLeagueSnapshot) -> dict[str, Any]:
    total_trades = 0
    total_waivers = 0
    total_scored_weeks = 0
    for season in snapshot.seasons:
        total_trades += len(season.trades())
        total_waivers += len(season.waivers())
        for wk in season.matchups_by_week:
            if any(metrics.is_scored(e) for e in season.matchups_by_week[wk]):
                total_scored_weeks += 1
    return {
        "seasonsCovered": len(snapshot.seasons),
        "managers": len(snapshot.managers.by_owner_id),
        "totalTrades": total_trades,
        "totalWaivers": total_waivers,
        "totalScoredWeeks": total_scored_weeks,
    }


def build_section(
    snapshot: PublicLeagueSnapshot,
    *,
    history_section: dict[str, Any],
    rivalries_section: dict[str, Any],
    records_section: dict[str, Any],
    awards_section: dict[str, Any],
    activity_section: dict[str, Any],
    draft_section: dict[str, Any],
    weekly_section: dict[str, Any],
) -> dict[str, Any]:
    """Build the overview section.  All inputs are already-built
    section payloads from the rest of the public contract so we can
    compose headline views from trusted derived data.
    """
    return {
        "seasonRangeLabel": _season_range_label(snapshot),
        "currentChampion": _current_champion(history_section),
        "featuredRivalry": _featured_rivalry(rivalries_section),
        "topRecordCallouts": _top_record_callouts(records_section),
        "recentTrades": _recent_trades(activity_section),
        "hottestTrade": _hottest_trade(activity_section),
        "draftCapitalLeader": _draft_capital_leader(draft_section),
        "latestWeeklyRecap": _latest_weekly_recap(weekly_section),
        "mostDecoratedFranchise": _most_decorated_franchise(history_section),
        "hottestRace": awards_section.get("hottestRace"),
        "mostChaoticManager": _most_chaotic_manager(awards_section),
        "leagueVitals": _league_vitals(snapshot),
    }
