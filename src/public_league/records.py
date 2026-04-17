"""Section: Records.

Full dynasty record book — single-game highs/lows, margin records,
most-points-in-a-loss / fewest-in-a-win, per-season scoring totals,
longest win/loss streaks, per-season trade/waiver counts, FAAB records,
and playoff scoring records.

Streak rules:
    * Chronological regular-season + playoff games only.
    * Ties end both win and loss streaks.
    * Byes (rows with points == 0 AND no paired matchup) are skipped,
      not counted as wins or losses.
"""
from __future__ import annotations

from typing import Any

from . import metrics
from .snapshot import PublicLeagueSnapshot, SeasonSnapshot


def _weekly_side_rows(snapshot: PublicLeagueSnapshot) -> list[dict[str, Any]]:
    """Return every paired, scored roster-week with its opposing score."""
    rows: list[dict[str, Any]] = []
    for season, week, a, b, is_playoff in metrics.walk_matchup_pairs(snapshot):
        for me, foe in ((a, b), (b, a)):
            rid = metrics.roster_id_of(me)
            if rid is None:
                continue
            my_pts = metrics.matchup_points(me)
            opp_pts = metrics.matchup_points(foe)
            if my_pts <= 0:
                continue
            owner_id = metrics.resolve_owner(snapshot.managers, season.league_id, rid)
            if not owner_id:
                continue
            margin = my_pts - opp_pts
            result = "W" if margin > 0 else ("L" if margin < 0 else "T")
            rows.append({
                "season": season.season,
                "leagueId": season.league_id,
                "week": week,
                "isPlayoff": is_playoff,
                "ownerId": owner_id,
                "rosterId": rid,
                "teamName": metrics.team_name(snapshot, season.league_id, rid),
                "points": round(my_pts, 2),
                "opponentPoints": round(opp_pts, 2),
                "margin": round(margin, 2),
                "result": result,
            })
    return rows


def _top_n(rows: list[dict[str, Any]], key: str, reverse: bool = True, n: int = 10) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda r: r[key], reverse=reverse)[:n]


def _streaks(snapshot: PublicLeagueSnapshot) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Compute longest win and longest loss streaks per owner, chronologically."""
    # Build owner → chronological sequence of (season, week, result).
    by_owner: dict[str, list[tuple[str, int, str, dict[str, Any]]]] = {}
    for season, week, a, b, _is_playoff in metrics.walk_matchup_pairs(snapshot):
        for me, foe in ((a, b), (b, a)):
            rid = metrics.roster_id_of(me)
            if rid is None:
                continue
            my = metrics.matchup_points(me)
            opp = metrics.matchup_points(foe)
            if my <= 0 and opp <= 0:
                continue
            owner_id = metrics.resolve_owner(snapshot.managers, season.league_id, rid)
            if not owner_id:
                continue
            if my > opp:
                result = "W"
            elif my < opp:
                result = "L"
            else:
                result = "T"
            by_owner.setdefault(owner_id, []).append((
                season.season, week, result,
                {
                    "season": season.season,
                    "leagueId": season.league_id,
                    "week": week,
                    "result": result,
                    "rosterId": rid,
                    "teamName": metrics.team_name(snapshot, season.league_id, rid),
                },
            ))

    # Sort each owner's games chronologically.  We order by (season-year,
    # week) — seasons are snapshot order current → previous, so convert
    # season to int when possible so older games come first.
    def _chron_key(event: tuple[str, int, str, dict[str, Any]]) -> tuple[int, int]:
        try:
            yr = int(event[0])
        except (TypeError, ValueError):
            yr = 0
        return (yr, event[1])

    win_streaks: list[dict[str, Any]] = []
    loss_streaks: list[dict[str, Any]] = []

    for owner_id, events in by_owner.items():
        events.sort(key=_chron_key)
        best_win = {"length": 0, "start": None, "end": None}
        best_loss = {"length": 0, "start": None, "end": None}
        cur_win = {"length": 0, "start": None, "end": None}
        cur_loss = {"length": 0, "start": None, "end": None}

        for season_key, week, result, meta in events:
            if result == "W":
                cur_loss = {"length": 0, "start": None, "end": None}
                cur_win["length"] += 1
                if cur_win["start"] is None:
                    cur_win["start"] = meta
                cur_win["end"] = meta
                if cur_win["length"] > best_win["length"]:
                    best_win = dict(cur_win)
            elif result == "L":
                cur_win = {"length": 0, "start": None, "end": None}
                cur_loss["length"] += 1
                if cur_loss["start"] is None:
                    cur_loss["start"] = meta
                cur_loss["end"] = meta
                if cur_loss["length"] > best_loss["length"]:
                    best_loss = dict(cur_loss)
            else:
                cur_win = {"length": 0, "start": None, "end": None}
                cur_loss = {"length": 0, "start": None, "end": None}

        if best_win["length"] > 0:
            win_streaks.append({
                "ownerId": owner_id,
                "displayName": metrics.display_name_for(snapshot, owner_id),
                **best_win,
            })
        if best_loss["length"] > 0:
            loss_streaks.append({
                "ownerId": owner_id,
                "displayName": metrics.display_name_for(snapshot, owner_id),
                **best_loss,
            })

    win_streaks.sort(key=lambda r: -r["length"])
    loss_streaks.sort(key=lambda r: -r["length"])
    return win_streaks, loss_streaks


def _trade_waiver_counts(snapshot: PublicLeagueSnapshot) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for season in snapshot.seasons:
        trades = len(season.trades())
        waivers = 0
        max_faab = 0
        max_faab_row: dict[str, Any] | None = None
        for tx in season.waivers():
            waivers += 1
            settings = tx.get("settings") or {}
            bid = settings.get("waiver_bid")
            try:
                bid_n = int(bid) if bid is not None else 0
            except (TypeError, ValueError):
                bid_n = 0
            if bid_n > max_faab:
                max_faab = bid_n
                adds = tx.get("adds") or {}
                player_ids = list(adds.keys())
                player_id = player_ids[0] if player_ids else ""
                roster_ids = tx.get("roster_ids") or []
                rid = int(roster_ids[0]) if roster_ids else None
                owner_id = metrics.resolve_owner(snapshot.managers, season.league_id, rid) if rid is not None else ""
                max_faab_row = {
                    "season": season.season,
                    "leagueId": season.league_id,
                    "bid": bid_n,
                    "ownerId": owner_id,
                    "displayName": metrics.display_name_for(snapshot, owner_id) if owner_id else "",
                    "playerId": player_id,
                    "playerName": snapshot.player_display(player_id),
                }
        out.append({
            "season": season.season,
            "leagueId": season.league_id,
            "tradeCount": trades,
            "waiverCount": waivers,
            "maxFaab": max_faab_row,
        })
    return out


def _season_scoring_totals(snapshot: PublicLeagueSnapshot) -> list[dict[str, Any]]:
    """Per-owner-per-season total PF / PA / weeks."""
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for season in snapshot.seasons:
        for wk in season.all_weeks:
            for a, b in metrics.matchup_pairs(season.matchups_by_week.get(wk) or []):
                for me, foe in ((a, b), (b, a)):
                    if not metrics.is_scored(me) and not metrics.is_scored(foe):
                        continue
                    rid = metrics.roster_id_of(me)
                    if rid is None:
                        continue
                    owner_id = metrics.resolve_owner(snapshot.managers, season.league_id, rid)
                    if not owner_id:
                        continue
                    key = (owner_id, season.season)
                    rec = by_key.setdefault(key, {
                        "ownerId": owner_id,
                        "season": season.season,
                        "leagueId": season.league_id,
                        "weeksPlayed": 0,
                        "totalPoints": 0.0,
                        "totalPointsAgainst": 0.0,
                    })
                    rec["weeksPlayed"] += 1
                    rec["totalPoints"] += metrics.matchup_points(me)
                    rec["totalPointsAgainst"] += metrics.matchup_points(foe)

    rows = list(by_key.values())
    for r in rows:
        r["totalPoints"] = round(r["totalPoints"], 2)
        r["totalPointsAgainst"] = round(r["totalPointsAgainst"], 2)
        r["avgPoints"] = round(r["totalPoints"] / r["weeksPlayed"], 2) if r["weeksPlayed"] else 0.0
        r["displayName"] = metrics.display_name_for(snapshot, r["ownerId"])
    return rows


def _playoff_records(side_rows: list[dict[str, Any]], snapshot: PublicLeagueSnapshot) -> dict[str, Any]:
    playoff_rows = [r for r in side_rows if r["isPlayoff"]]
    most_points = _top_n(playoff_rows, "points", reverse=True, n=5)

    # Most playoff wins in a season.
    by_key: dict[tuple[str, str], int] = {}
    for r in playoff_rows:
        if r["result"] == "W":
            by_key[(r["ownerId"], r["season"])] = by_key.get((r["ownerId"], r["season"]), 0) + 1
    wins_rows = [
        {
            "ownerId": owner_id,
            "season": season,
            "displayName": metrics.display_name_for(snapshot, owner_id),
            "playoffWins": wins,
        }
        for (owner_id, season), wins in by_key.items()
    ]
    wins_rows.sort(key=lambda r: -r["playoffWins"])
    return {
        "mostPointsInPlayoffs": most_points,
        "mostPlayoffWinsInSeason": wins_rows[:5],
    }


def build_section(snapshot: PublicLeagueSnapshot) -> dict[str, Any]:
    side_rows = _weekly_side_rows(snapshot)
    win_streaks, loss_streaks = _streaks(snapshot)
    season_totals = _season_scoring_totals(snapshot)
    trade_waiver = _trade_waiver_counts(snapshot)

    # Single-game highs / lows (regular + playoffs).
    highest = _top_n(side_rows, "points", reverse=True, n=10)
    lowest = _top_n(side_rows, "points", reverse=False, n=10)

    # Margin records.
    biggest_margin = _top_n(side_rows, "margin", reverse=True, n=10)
    narrowest_margin = _top_n(
        [r for r in side_rows if r["result"] == "W"],
        "margin",
        reverse=False,
        n=10,
    )
    # Most points in a loss (biggest points among losers).
    most_points_in_loss = _top_n(
        [r for r in side_rows if r["result"] == "L"],
        "points",
        reverse=True,
        n=5,
    )
    # Fewest points in a win.
    fewest_points_in_win = _top_n(
        [r for r in side_rows if r["result"] == "W"],
        "points",
        reverse=False,
        n=5,
    )

    # Season-level top lists.
    most_points_season = sorted(season_totals, key=lambda r: -r["totalPoints"])[:10]
    most_pa_season = sorted(season_totals, key=lambda r: -r["totalPointsAgainst"])[:10]

    most_trades_season = sorted(trade_waiver, key=lambda r: -r["tradeCount"])[:3]
    most_waivers_season = sorted(trade_waiver, key=lambda r: -r["waiverCount"])[:3]
    largest_faab = [r for r in trade_waiver if r["maxFaab"]]
    largest_faab.sort(key=lambda r: -r["maxFaab"]["bid"])

    return {
        "seasonsCovered": [s.season for s in snapshot.seasons],
        "singleWeekHighest": highest,
        "singleWeekLowest": lowest,
        "biggestMargin": biggest_margin,
        "narrowestVictory": narrowest_margin,
        "mostPointsInLoss": most_points_in_loss,
        "fewestPointsInWin": fewest_points_in_win,
        "mostPointsInSeason": most_points_season,
        "mostPointsAgainstInSeason": most_pa_season,
        "longestWinStreaks": win_streaks[:10],
        "longestLossStreaks": loss_streaks[:10],
        "tradeCountsBySeason": trade_waiver,
        "mostTradesInSeason": most_trades_season,
        "mostWaiversInSeason": most_waivers_season,
        "largestFaabBid": [r["maxFaab"] for r in largest_faab[:3]],
        "playoffRecords": _playoff_records(side_rows, snapshot),
    }
