"""Section: Per-matchup game recap.

Given a (season, week, matchup_id) identifier, assemble a rich, public-
safe recap: starting lineups with per-player points, top scorer, bench
misses, pre-week standings for both sides, rivalry context if the pair
is a featured rivalry.

Output is composed entirely from the snapshot + the already-built
public sections.  No private data touches this path.
"""
from __future__ import annotations

from typing import Any

from . import metrics
from .snapshot import PublicLeagueSnapshot, SeasonSnapshot


def _week_matchup_pairs(entries: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    groups: dict[int, list[dict[str, Any]]] = {}
    for e in entries:
        mid = e.get("matchup_id")
        if mid is None:
            continue
        try:
            key = int(mid)
        except (TypeError, ValueError):
            continue
        groups.setdefault(key, []).append(e)
    return groups


def _starter_scores(entry: dict[str, Any], snapshot: PublicLeagueSnapshot) -> list[dict[str, Any]]:
    starters = entry.get("starters") or []
    pp = entry.get("players_points") or {}
    rows = []
    for pid in starters:
        if not pid or pid == "0":
            continue
        name = snapshot.player_display(pid)
        pos = snapshot.player_position(pid)
        try:
            points = float(pp.get(pid) or 0.0)
        except (TypeError, ValueError):
            points = 0.0
        rows.append({
            "playerId": str(pid),
            "playerName": name,
            "position": pos,
            "points": round(points, 2),
        })
    return rows


def _bench_scores(
    entry: dict[str, Any],
    snapshot: PublicLeagueSnapshot,
) -> list[dict[str, Any]]:
    starters = {str(s) for s in (entry.get("starters") or []) if s}
    roster = [str(p) for p in (entry.get("players") or []) if p]
    pp = entry.get("players_points") or {}
    rows = []
    for pid in roster:
        if pid in starters or pid == "0":
            continue
        try:
            points = float(pp.get(pid) or 0.0)
        except (TypeError, ValueError):
            points = 0.0
        rows.append({
            "playerId": pid,
            "playerName": snapshot.player_display(pid),
            "position": snapshot.player_position(pid),
            "points": round(points, 2),
        })
    rows.sort(key=lambda r: -r["points"])
    return rows


def _side_block(
    snapshot: PublicLeagueSnapshot,
    season: SeasonSnapshot,
    entry: dict[str, Any],
    pre_standings_lookup: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    rid = metrics.roster_id_of(entry)
    if rid is None:
        return None
    owner_id = metrics.resolve_owner(snapshot.managers, season.league_id, rid)
    if not owner_id:
        return None
    starters = _starter_scores(entry, snapshot)
    bench = _bench_scores(entry, snapshot)
    top_scorer = max(starters, key=lambda r: r["points"], default=None) if starters else None
    biggest_miss = max(bench, key=lambda r: r["points"], default=None) if bench else None
    pre = pre_standings_lookup.get(owner_id) or {}
    return {
        "ownerId": owner_id,
        "rosterId": rid,
        "displayName": metrics.display_name_for(snapshot, owner_id),
        "teamName": metrics.team_name(snapshot, season.league_id, rid),
        "points": round(metrics.matchup_points(entry), 2),
        "starters": starters,
        "bench": bench,
        "topScorer": top_scorer,
        "biggestBenchMiss": biggest_miss if (biggest_miss and top_scorer and biggest_miss["points"] > top_scorer["points"]) else None,
        "preWeekRecord": {
            "wins": pre.get("wins", 0),
            "losses": pre.get("losses", 0),
            "ties": pre.get("ties", 0),
            "winPct": pre.get("winPct", 0.0),
            "standing": pre.get("standing"),
            "pointsFor": pre.get("pointsFor", 0.0),
        } if pre else None,
    }


def build_matchup_recap(
    snapshot: PublicLeagueSnapshot,
    season_year: str,
    week: int,
    matchup_id: int,
) -> dict[str, Any] | None:
    """Assemble the public-safe recap block for a single matchup.

    Returns ``None`` if the season/week/matchup doesn't exist.
    """
    season = snapshot.season_by_year(season_year)
    if season is None:
        return None
    entries = season.matchups_by_week.get(week) or []
    if not entries:
        return None
    groups = _week_matchup_pairs(entries)
    pair = groups.get(int(matchup_id))
    if not pair or len(pair) != 2:
        return None

    is_playoff = week >= season.playoff_week_start
    pre_standings = metrics.pre_week_standings(season, snapshot.managers, week)
    pre_lookup = {r["ownerId"]: r for r in pre_standings}

    pair_sorted = sorted(pair, key=lambda e: int(e.get("roster_id") or 0))
    home = _side_block(snapshot, season, pair_sorted[0], pre_lookup)
    away = _side_block(snapshot, season, pair_sorted[1], pre_lookup)
    if home is None or away is None:
        return None

    margin = round(abs(home["points"] - away["points"]), 2)
    if home["points"] > away["points"]:
        winner = home
        loser = away
    elif away["points"] > home["points"]:
        winner = away
        loser = home
    else:
        winner = None
        loser = None

    # Narrative one-liner — human-friendly copy for Slack-share / OG cards.
    narrative = _build_narrative(snapshot, season, week, is_playoff, winner, loser, home, away)

    return {
        "season": season.season,
        "leagueId": season.league_id,
        "week": week,
        "isPlayoff": is_playoff,
        "matchupId": int(matchup_id),
        "home": home,
        "away": away,
        "margin": margin,
        "winnerOwnerId": winner["ownerId"] if winner else None,
        "loserOwnerId": loser["ownerId"] if loser else None,
        "narrative": narrative,
        "playoffWeekStart": season.playoff_week_start,
    }


def _build_narrative(
    snapshot: PublicLeagueSnapshot,
    season: SeasonSnapshot,
    week: int,
    is_playoff: bool,
    winner: dict[str, Any] | None,
    loser: dict[str, Any] | None,
    home: dict[str, Any],
    away: dict[str, Any],
) -> str:
    tag = "playoff" if is_playoff else "regular-season"
    if winner is None:
        return (
            f"{home['displayName']} and {away['displayName']} tied at "
            f"{home['points']} in the {season.season} Week {week} {tag} matchup."
        )
    top = winner.get("topScorer") or {}
    top_blurb = ""
    if top and top.get("playerName") and top.get("points", 0) > 0:
        top_blurb = f" Led by {top['playerName']}'s {top['points']} pts."
    return (
        f"{winner['displayName']} beat {loser['displayName']} "
        f"{winner['points']}–{loser['points']} (margin {round(abs(winner['points'] - loser['points']), 2)}) "
        f"in the {season.season} Week {week} {tag} matchup.{top_blurb}"
    )


def list_matchups(snapshot: PublicLeagueSnapshot) -> list[dict[str, Any]]:
    """Enumerate every (season, week, matchup_id) with a pair of scored
    entries.  Used to power the index page + for building sitemaps."""
    out: list[dict[str, Any]] = []
    for season in snapshot.seasons:
        for week in sorted(season.matchups_by_week.keys()):
            is_playoff = week >= season.playoff_week_start
            for mid, pair in _week_matchup_pairs(season.matchups_by_week[week]).items():
                if len(pair) != 2:
                    continue
                if not metrics.is_scored(pair[0]) and not metrics.is_scored(pair[1]):
                    continue
                out.append({
                    "season": season.season,
                    "leagueId": season.league_id,
                    "week": week,
                    "isPlayoff": is_playoff,
                    "matchupId": mid,
                })
    return out
