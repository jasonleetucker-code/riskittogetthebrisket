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
        rows.append(
            {
                "playerId": str(pid),
                "playerName": name,
                "position": pos,
                "points": round(points, 2),
            }
        )
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
        rows.append(
            {
                "playerId": pid,
                "playerName": snapshot.player_display(pid),
                "position": snapshot.player_position(pid),
                "points": round(points, 2),
            }
        )
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

    # An unresolved owner USED TO return None here, which killed the whole
    # recap — `build_matchup_recap` bails when either side is None, so
    # `server.py` 404s.  That silently broke 28 of 158 public recap links
    # (measured against live Sleeper 2026-08-05; all 2024, roster_ids 9 and
    # 10), because `identity.py` deliberately does not register rosters
    # whose owner is orphaned or retired.
    #
    # The index never applied the same rule: `list_matchups` admits a pair
    # on "two entries and either side scored", with no owner check.  So the
    # archive advertised 28 links that could not be built — the asymmetry
    # is the defect, not the retirement list.  `identity.py`'s own comment
    # says such data "falls through to the same '' attribution path ... and
    # filtered out"; nothing filtered it.
    #
    # Resolved by making the DETAIL tolerant rather than making the index
    # hide games: a real 2024 matchup between real teams stays reachable,
    # attributed to the roster instead of to a person.  The retirement list
    # keeps doing its actual job — retired managers stay out of dropdowns
    # and franchise pages — because that filtering lives in identity.py,
    # not here.
    #
    # The synthetic id is unique per roster ON PURPOSE.  The frontend marks
    # the winner with `winnerOwnerId === side.ownerId`, so two retired
    # owners facing each other would both compare equal on "" and both
    # render as the winner.  It also cannot collide with a Sleeper user id,
    # which is numeric.  `ownerResolved: false` is what the UI gates on —
    # it must not link to /league/franchise/<synthetic>, which does not
    # exist.
    owner_resolved = bool(owner_id)
    if not owner_resolved:
        owner_id = f"retired:{season.league_id}:{rid}"

    starters = _starter_scores(entry, snapshot)
    bench = _bench_scores(entry, snapshot)
    top_scorer = max(starters, key=lambda r: r["points"], default=None) if starters else None
    biggest_miss = max(bench, key=lambda r: r["points"], default=None) if bench else None
    pre = pre_standings_lookup.get(owner_id) or {}
    return {
        "ownerId": owner_id,
        "ownerResolved": owner_resolved,
        "rosterId": rid,
        # display_name_for() returns the id itself when no manager matches,
        # which for the synthetic id would print "retired:12345:9" on the
        # card.  team_name() already degrades correctly to "Team <rid>".
        "displayName": (
            metrics.display_name_for(snapshot, owner_id) if owner_resolved else "Former manager"
        ),
        "teamName": metrics.team_name(snapshot, season.league_id, rid),
        "points": round(metrics.matchup_points(entry), 2),
        "starters": starters,
        "bench": bench,
        "topScorer": top_scorer,
        "biggestBenchMiss": biggest_miss
        if (biggest_miss and top_scorer and biggest_miss["points"] > top_scorer["points"])
        else None,
        "preWeekRecord": {
            "wins": pre.get("wins", 0),
            "losses": pre.get("losses", 0),
            "ties": pre.get("ties", 0),
            "winPct": pre.get("winPct", 0.0),
            "standing": pre.get("standing"),
            "pointsFor": pre.get("pointsFor", 0.0),
        }
        if pre
        else None,
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
                out.append(
                    {
                        "season": season.season,
                        "leagueId": season.league_id,
                        "week": week,
                        "isPlayoff": is_playoff,
                        "matchupId": mid,
                    }
                )
    return out
