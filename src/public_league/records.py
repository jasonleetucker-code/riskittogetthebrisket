"""Section: Records.

Full dynasty record book — single-game highs/lows, margin records,
most-points-in-a-loss / fewest-in-a-win, per-season scoring totals,
longest win/loss streaks, per-season trade/waiver counts, FAAB records,
playoff scoring records, and per-position player records.

Streak rules:
    * Chronological regular-season + playoff games only.
    * Ties end both win and loss streaks.
    * Byes (rows with points == 0 AND no paired matchup) are skipped,
      not counted as wins or losses.

Single-week records use individual-week side rows (no combined-finals
fusion) so the highest single-week always reflects exactly one NFL week
of scoring.
"""
from __future__ import annotations

from typing import Any

from . import metrics
from .snapshot import PublicLeagueSnapshot, SeasonSnapshot


# Positions we track player records for.  Order = display order in the UI.
_PLAYER_RECORD_POSITIONS = ("QB", "RB", "WR", "TE", "K", "DL", "LB", "DB")


def _weekly_side_rows(snapshot: PublicLeagueSnapshot) -> list[dict[str, Any]]:
    """Return every paired, scored roster-week with its opposing score.

    Combined-week finals (multi-week championships) are emitted as ONE
    row carrying both weeks' summed score — used for rivalry/meeting
    bookkeeping.  See ``_weekly_side_rows_individual`` for un-combined
    rows used by single-week records.
    """
    rows: list[dict[str, Any]] = []
    for season, week, a, b, is_playoff in metrics.walk_matchup_pairs(snapshot):
        # Multi-week finals collapse to one pair; stamp the spanned
        # weeks so record-book rows can label them correctly.
        combined_weeks = a.get("_combinedWeeks") or b.get("_combinedWeeks")
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
            row: dict[str, Any] = {
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
            }
            if combined_weeks and len(combined_weeks) > 1:
                row["combinedWeeks"] = list(combined_weeks)
            rows.append(row)
    return rows


def _weekly_side_rows_individual(snapshot: PublicLeagueSnapshot) -> list[dict[str, Any]]:
    """Per-individual-week side rows.  Never fuses multi-week finals.

    Used by single-week record categories (highest score, biggest
    margin, narrowest victory, etc.) so a 2-week championship is
    counted as TWO separate weeks of scoring rather than one combined
    300-point explosion.
    """
    rows: list[dict[str, Any]] = []
    for season in snapshot.seasons:
        for week in sorted(season.matchups_by_week.keys()):
            entries = season.matchups_by_week.get(week) or []
            is_playoff = week >= season.playoff_week_start
            for a, b in metrics.matchup_pairs(entries):
                for me, foe in ((a, b), (b, a)):
                    rid = metrics.roster_id_of(me)
                    if rid is None:
                        continue
                    my_pts = metrics.matchup_points(me)
                    opp_pts = metrics.matchup_points(foe)
                    if my_pts <= 0:
                        continue
                    owner_id = metrics.resolve_owner(
                        snapshot.managers, season.league_id, rid
                    )
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
                        "teamName": metrics.team_name(
                            snapshot, season.league_id, rid
                        ),
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


def _season_scoring_totals(
    snapshot: PublicLeagueSnapshot,
    *,
    regular_season_only: bool = True,
) -> list[dict[str, Any]]:
    """Per-owner-per-season total PF / PA / weeks.

    When ``regular_season_only`` is True (default), playoff weeks are
    excluded so the resulting "most points in a season" leaderboard
    reflects regular-season scoring only.
    """
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for season in snapshot.seasons:
        weeks = (
            season.regular_season_weeks
            if regular_season_only
            else season.all_weeks
        )
        for wk in weeks:
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


def _starter_set(entry: dict[str, Any]) -> list[str]:
    starters = entry.get("starters") or []
    return [str(s) for s in starters if s]


def _player_records(snapshot: PublicLeagueSnapshot) -> dict[str, list[dict[str, Any]]]:
    """Top single-week starter-only scorers grouped by position.

    Regular season only.  Only counts a player's points when they
    appeared in the starting lineup.  Returns ``{position: [top5...]}``
    ordered by points descending.
    """
    by_position: dict[str, list[dict[str, Any]]] = {pos: [] for pos in _PLAYER_RECORD_POSITIONS}

    for season in snapshot.seasons:
        for week in season.regular_season_weeks:
            entries = season.matchups_by_week.get(week) or []
            for entry in entries:
                rid = metrics.roster_id_of(entry)
                if rid is None:
                    continue
                owner_id = metrics.resolve_owner(
                    snapshot.managers, season.league_id, rid
                )
                if not owner_id:
                    continue
                pp = entry.get("players_points")
                if not isinstance(pp, dict):
                    continue
                starters = _starter_set(entry)
                if not starters:
                    continue
                for pid in starters:
                    raw = pp.get(pid)
                    try:
                        pts = float(raw or 0.0)
                    except (TypeError, ValueError):
                        continue
                    if pts <= 0:
                        continue
                    pos = snapshot.player_position(pid)
                    if not pos or pos not in by_position:
                        continue
                    by_position[pos].append({
                        "season": season.season,
                        "leagueId": season.league_id,
                        "week": week,
                        "ownerId": owner_id,
                        "rosterId": rid,
                        "teamName": metrics.team_name(snapshot, season.league_id, rid),
                        "displayName": metrics.display_name_for(snapshot, owner_id),
                        "playerId": pid,
                        "playerName": snapshot.player_display(pid),
                        "position": pos,
                        "points": round(pts, 2),
                    })

    out: dict[str, list[dict[str, Any]]] = {}
    for pos, rows in by_position.items():
        rows.sort(key=lambda r: -r["points"])
        # Top 5 single-week explosions per position.
        out[pos] = rows[:5]
    return out


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
    # Combined side rows preserve the multi-week-finals fusion for
    # rivalries / playoff bookkeeping.
    side_rows = _weekly_side_rows(snapshot)
    # Individual side rows are the truth for "single-week" record
    # categories — never fused, so each row is exactly one NFL week.
    individual_rows = _weekly_side_rows_individual(snapshot)
    win_streaks, loss_streaks = _streaks(snapshot)
    season_totals_regular = _season_scoring_totals(snapshot, regular_season_only=True)
    trade_waiver = _trade_waiver_counts(snapshot)

    # Single-game highs / lows from the un-combined per-week rows.
    highest = _top_n(individual_rows, "points", reverse=True, n=10)
    lowest = _top_n(individual_rows, "points", reverse=False, n=10)

    # Margin records (also single-week only).
    biggest_margin = _top_n(individual_rows, "margin", reverse=True, n=10)
    narrowest_margin = _top_n(
        [r for r in individual_rows if r["result"] == "W"],
        "margin",
        reverse=False,
        n=10,
    )
    most_points_in_loss = _top_n(
        [r for r in individual_rows if r["result"] == "L"],
        "points",
        reverse=True,
        n=5,
    )
    fewest_points_in_win = _top_n(
        [r for r in individual_rows if r["result"] == "W"],
        "points",
        reverse=False,
        n=5,
    )

    # Season-level top lists — regular season only per user request.
    most_points_season = sorted(season_totals_regular, key=lambda r: -r["totalPoints"])[:10]
    most_pa_season = sorted(season_totals_regular, key=lambda r: -r["totalPointsAgainst"])[:10]

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
        "playerRecords": _player_records(snapshot),
        "playerRecordPositions": list(_PLAYER_RECORD_POSITIONS),
    }
