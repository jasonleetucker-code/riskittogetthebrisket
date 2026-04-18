"""Section: Head-to-Head Matchup Preview.

For each matchup on the upcoming (or most recent) week, surface:
    * All-time head-to-head record between the two owners.
    * Last 5 meetings with dates / scores / winner.
    * Recent form — last 3 games per team (average points, W-L).

Current-week detection:
    1. Walk the current season's weeks in order.
    2. The current week is the first week whose matchup rows exist
       but have at least one unscored entry.
    3. If no such week exists (every scheduled matchup already has a
       score), fall back to the most recently scored week.  The UI can
       then render the section as "This week's results" instead of a
       preview — both modes use the same H2H context.

Output shape
────────────
``currentSeason``    — season id of the preview / recap week.
``currentWeek``      — int week number.
``mode``             — ``"preview"`` (unscored) or ``"recap"`` (scored).
``isPlayoff``        — passthrough for styling.
``matchups``         — list of ``{home, away, h2h, form, scores}``.
``generatedAt``      — iso timestamp for cache debugging.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from . import metrics
from .snapshot import PublicLeagueSnapshot, SeasonSnapshot


def _detect_current_week(season: SeasonSnapshot) -> tuple[int, str]:
    """Return (week, mode).  ``mode`` is ``"preview"`` if there are
    unscored matchups in the week, else ``"recap"``.
    """
    for wk in season.all_weeks:
        entries = season.matchups_by_week.get(wk) or []
        if not entries:
            continue
        has_scored = any(metrics.is_scored(e) for e in entries)
        has_unscored = any(not metrics.is_scored(e) for e in entries)
        # A "current" week is one where Sleeper has matchup rows but
        # not every team has posted a final score.  If every row is
        # unscored, it's a future week; we still preview it.
        if not has_scored:
            return wk, "preview"
        if has_unscored:
            return wk, "preview"
    # All weeks fully scored → recap the most recent one.
    last = 0
    for wk in season.all_weeks:
        entries = season.matchups_by_week.get(wk) or []
        if any(metrics.is_scored(e) for e in entries):
            last = wk
    return last, "recap"


def _pair_key(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a <= b else (b, a)


def _build_h2h_index(
    snapshot: PublicLeagueSnapshot,
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    """Walk every scored matchup pair and index meetings by the canonical
    owner-id tuple.  Meetings are ordered chronologically (oldest first).
    """
    idx: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for season, wk, a, b, is_playoff in metrics.walk_matchup_pairs(snapshot):
        oa = metrics.resolve_owner(snapshot.managers, season.league_id, a.get("roster_id"))
        ob = metrics.resolve_owner(snapshot.managers, season.league_id, b.get("roster_id"))
        if not oa or not ob or oa == ob:
            continue
        pa = metrics.matchup_points(a)
        pb = metrics.matchup_points(b)
        if pa <= 0 and pb <= 0:
            continue
        key = _pair_key(oa, ob)
        # Normalize so the key's first entry is always "sideA".
        sideA_oid, sideB_oid = key
        sideA_pts = pa if oa == sideA_oid else pb
        sideB_pts = pb if oa == sideA_oid else pa
        if sideA_pts > sideB_pts:
            winner = sideA_oid
        elif sideB_pts > sideA_pts:
            winner = sideB_oid
        else:
            winner = None
        idx[key].append({
            "season": season.season,
            "leagueId": season.league_id,
            "week": wk,
            "isPlayoff": is_playoff,
            "sideAOwnerId": sideA_oid,
            "sideBOwnerId": sideB_oid,
            "sideAPoints": round(sideA_pts, 2),
            "sideBPoints": round(sideB_pts, 2),
            "winnerOwnerId": winner,
            "margin": round(abs(sideA_pts - sideB_pts), 2),
        })
    for meetings in idx.values():
        meetings.sort(
            key=lambda m: (_season_sort(m["season"]), m["week"])
        )
    return idx


def _season_sort(season: str) -> int:
    try:
        return int(season)
    except (TypeError, ValueError):
        return 0


def _recent_form_for_owner(
    snapshot: PublicLeagueSnapshot,
    owner_id: str,
    before_season: str,
    before_week: int,
    n: int = 3,
) -> dict[str, Any]:
    """Return the owner's last ``n`` scored games STRICTLY before
    (season, week), oldest → newest.  Includes playoffs.
    """
    events: list[dict[str, Any]] = []
    for season, wk, a, b, is_playoff in metrics.walk_matchup_pairs(snapshot):
        # Strictly-before test.
        if _season_sort(season.season) > _season_sort(before_season):
            continue
        if (
            _season_sort(season.season) == _season_sort(before_season)
            and wk >= before_week
        ):
            continue
        for me, foe in ((a, b), (b, a)):
            rid = metrics.roster_id_of(me)
            if rid is None:
                continue
            oid = metrics.resolve_owner(snapshot.managers, season.league_id, rid)
            if oid != owner_id:
                continue
            my_pts = metrics.matchup_points(me)
            opp_pts = metrics.matchup_points(foe)
            if my_pts <= 0 and opp_pts <= 0:
                continue
            if my_pts > opp_pts:
                result = "W"
            elif my_pts < opp_pts:
                result = "L"
            else:
                result = "T"
            events.append({
                "season": season.season,
                "week": wk,
                "points": round(my_pts, 2),
                "opponentPoints": round(opp_pts, 2),
                "result": result,
            })
    events.sort(key=lambda e: (_season_sort(e["season"]), e["week"]))
    recent = events[-n:]
    wins = sum(1 for e in recent if e["result"] == "W")
    losses = sum(1 for e in recent if e["result"] == "L")
    ties = sum(1 for e in recent if e["result"] == "T")
    avg = round(sum(e["points"] for e in recent) / len(recent), 2) if recent else 0.0
    return {
        "games": recent,
        "record": f"{wins}-{losses}" + (f"-{ties}" if ties else ""),
        "avgPoints": avg,
    }


def _h2h_summary(meetings: list[dict[str, Any]], sideA_oid: str, sideB_oid: str) -> dict[str, Any]:
    """Summarize the full series between two owners."""
    wins_a = 0
    wins_b = 0
    ties = 0
    pts_a = 0.0
    pts_b = 0.0
    margins = []
    playoff_meetings = 0
    for m in meetings:
        aligned_a = m["sideAOwnerId"] == sideA_oid
        a_pts = m["sideAPoints"] if aligned_a else m["sideBPoints"]
        b_pts = m["sideBPoints"] if aligned_a else m["sideAPoints"]
        pts_a += a_pts
        pts_b += b_pts
        margins.append(a_pts - b_pts)
        if a_pts > b_pts:
            wins_a += 1
        elif b_pts > a_pts:
            wins_b += 1
        else:
            ties += 1
        if m.get("isPlayoff"):
            playoff_meetings += 1
    total = len(meetings)
    avg_margin = round(sum(abs(m) for m in margins) / total, 2) if total else 0.0
    biggest = max(margins, key=lambda m: abs(m)) if margins else 0.0
    return {
        "totalMeetings": total,
        "sideAWins": wins_a,
        "sideBWins": wins_b,
        "ties": ties,
        "sideAPointsTotal": round(pts_a, 2),
        "sideBPointsTotal": round(pts_b, 2),
        "avgMargin": avg_margin,
        "biggestMargin": round(abs(biggest), 2),
        "biggestMarginWinner": sideA_oid if biggest > 0 else (sideB_oid if biggest < 0 else None),
        "playoffMeetings": playoff_meetings,
    }


def _meetings_recent(meetings: list[dict[str, Any]], n: int = 5) -> list[dict[str, Any]]:
    return list(reversed(meetings[-n:])) if meetings else []


def _narrative(summary: dict[str, Any], sideA_name: str, sideB_name: str, last: dict[str, Any] | None) -> str:
    """Short 1-2 sentence summary."""
    total = summary["totalMeetings"]
    if total == 0:
        return f"First ever meeting between {sideA_name} and {sideB_name}."
    a, b = summary["sideAWins"], summary["sideBWins"]
    lead_bit = (
        f"{sideA_name} leads the series {a}-{b}"
        if a > b
        else f"{sideB_name} leads the series {b}-{a}"
        if b > a
        else f"series tied {a}-{a}"
    )
    last_bit = ""
    if last:
        if last["winnerOwnerId"] == summary.get("_sideA_oid"):
            winner_name = sideA_name
        elif last["winnerOwnerId"] == summary.get("_sideB_oid"):
            winner_name = sideB_name
        else:
            winner_name = None
        if winner_name:
            last_bit = f"; most recent: {winner_name} by {last['margin']:.1f} in {last['season']} wk {last['week']}"
    return f"{lead_bit}{last_bit}."


def build_section(snapshot: PublicLeagueSnapshot) -> dict[str, Any]:
    current = snapshot.current_season
    if current is None:
        return _empty_section()

    week, mode = _detect_current_week(current)
    if week == 0:
        return _empty_section()

    entries = current.matchups_by_week.get(week) or []
    pairs = metrics.matchup_pairs(entries)
    if not pairs:
        return _empty_section()

    h2h_index = _build_h2h_index(snapshot)

    out_matchups: list[dict[str, Any]] = []
    is_playoff = week >= current.playoff_week_start
    for a, b in pairs:
        oa = metrics.resolve_owner(snapshot.managers, current.league_id, a.get("roster_id"))
        ob = metrics.resolve_owner(snapshot.managers, current.league_id, b.get("roster_id"))
        if not oa or not ob:
            continue
        key = _pair_key(oa, ob)
        sideA_oid, sideB_oid = key
        meetings = h2h_index.get(key, [])
        summary = _h2h_summary(meetings, sideA_oid, sideB_oid)
        summary["_sideA_oid"] = sideA_oid
        summary["_sideB_oid"] = sideB_oid
        recent = _meetings_recent(meetings, n=5)
        form_a = _recent_form_for_owner(
            snapshot, sideA_oid, current.season, week, n=3
        )
        form_b = _recent_form_for_owner(
            snapshot, sideB_oid, current.season, week, n=3
        )

        home_rid = metrics.roster_id_of(a) if oa == sideA_oid else metrics.roster_id_of(b)
        away_rid = metrics.roster_id_of(b) if oa == sideA_oid else metrics.roster_id_of(a)

        home_entry = a if oa == sideA_oid else b
        away_entry = b if oa == sideA_oid else a

        out_matchups.append({
            "matchupId": a.get("matchup_id"),
            "home": {
                "ownerId": sideA_oid,
                "displayName": metrics.display_name_for(snapshot, sideA_oid),
                "teamName": metrics.team_name(snapshot, current.league_id, home_rid),
                "rosterId": home_rid,
                "points": round(metrics.matchup_points(home_entry), 2) if mode == "recap" else None,
            },
            "away": {
                "ownerId": sideB_oid,
                "displayName": metrics.display_name_for(snapshot, sideB_oid),
                "teamName": metrics.team_name(snapshot, current.league_id, away_rid),
                "rosterId": away_rid,
                "points": round(metrics.matchup_points(away_entry), 2) if mode == "recap" else None,
            },
            "h2h": {
                "totalMeetings": summary["totalMeetings"],
                "homeWins": summary["sideAWins"],
                "awayWins": summary["sideBWins"],
                "ties": summary["ties"],
                "avgMargin": summary["avgMargin"],
                "biggestMargin": summary["biggestMargin"],
                "biggestMarginWinnerOwnerId": summary["biggestMarginWinner"],
                "playoffMeetings": summary["playoffMeetings"],
                "last5": recent,
                "lastMeeting": recent[0] if recent else None,
                "narrative": _narrative(
                    summary,
                    metrics.display_name_for(snapshot, sideA_oid),
                    metrics.display_name_for(snapshot, sideB_oid),
                    recent[0] if recent else None,
                ),
            },
            "form": {
                "home": form_a,
                "away": form_b,
            },
        })

    return {
        "currentSeason": current.season,
        "currentWeek": week,
        "mode": mode,
        "isPlayoff": is_playoff,
        "matchups": out_matchups,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
    }


def _empty_section() -> dict[str, Any]:
    return {
        "currentSeason": None,
        "currentWeek": None,
        "mode": None,
        "isPlayoff": False,
        "matchups": [],
        "generatedAt": datetime.now(timezone.utc).isoformat(),
    }
