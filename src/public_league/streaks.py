"""Section: Active Streaks & Records-in-Reach.

Distinct from ``records.py`` — that module returns the dynasty record
book (longest-ever streak holders, top-10 single-week highs, etc.).
This module surfaces **live, trailing streaks** and **records at risk
this season**, so the Home tab can render a "records are falling"
headline rail.

Output shape
────────────
``activeStreaks``    — per owner, their current trailing run of wins,
                       losses, 100+ point weeks, 120+ point weeks, etc.
                       Ordered so the longest streak leads, grouped by type.
``recordsInReach``   — per all-time record, the reigning holder and
                       the closest active chaser (if any).
``notableThisWeek``  — most recent scored week's entries that placed
                       in the all-time top-N for a category (e.g.
                       "3rd-highest score of all time").
``seasonsCovered``   — passthrough.
``currentSeason``    — passthrough.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from . import metrics
from .snapshot import PublicLeagueSnapshot, SeasonSnapshot


# Point thresholds we track "consecutive weeks above X" for.  Picked to
# be broad enough that most dynasty leagues hit them weekly.
_POINT_THRESHOLDS = (100.0, 120.0, 140.0)


# How many entries the "records in reach" list pulls for each category.
_RECORDS_IN_REACH_TOP_N = 5
# Only flag a record as "in reach" if the chaser is within this fraction
# of the record holder's value (streaks use raw count diff instead).
_NEAR_RECORD_POINTS_PCT = 0.95


def _chron_key(event: dict[str, Any]) -> tuple[int, int]:
    try:
        yr = int(event["season"])
    except (TypeError, ValueError):
        yr = 0
    return (yr, int(event.get("week") or 0))


def _all_events(snapshot: PublicLeagueSnapshot) -> list[dict[str, Any]]:
    """Flatten every scored paired roster-week into a chronological stream."""
    out: list[dict[str, Any]] = []
    for season, week, a, b, is_playoff in metrics.walk_matchup_pairs(snapshot):
        for me, foe in ((a, b), (b, a)):
            rid = metrics.roster_id_of(me)
            if rid is None:
                continue
            my_pts = metrics.matchup_points(me)
            opp_pts = metrics.matchup_points(foe)
            if my_pts <= 0 and opp_pts <= 0:
                continue
            owner_id = metrics.resolve_owner(
                snapshot.managers, season.league_id, rid
            )
            if not owner_id:
                continue
            if my_pts > opp_pts:
                result = "W"
            elif my_pts < opp_pts:
                result = "L"
            else:
                result = "T"
            out.append({
                "ownerId": owner_id,
                "season": season.season,
                "leagueId": season.league_id,
                "week": week,
                "isPlayoff": is_playoff,
                "points": round(my_pts, 2),
                "opponentPoints": round(opp_pts, 2),
                "margin": round(my_pts - opp_pts, 2),
                "result": result,
            })
    out.sort(key=_chron_key)
    return out


def _trailing_run(
    events_reversed: list[dict[str, Any]],
    predicate,
) -> tuple[int, dict[str, Any] | None, dict[str, Any] | None]:
    """Length of the trailing run where ``predicate(ev)`` is True, starting
    from the most recent event and walking backward.  Returns
    ``(length, start_event, end_event)`` where ``start_event`` is the
    chronologically earliest event in the run and ``end_event`` is the
    most recent.
    """
    length = 0
    end_ev = None
    start_ev = None
    for ev in events_reversed:
        if predicate(ev):
            if length == 0:
                end_ev = ev
            length += 1
            start_ev = ev
        else:
            break
    return length, start_ev, end_ev


def _active_streaks_for_owner(
    events: list[dict[str, Any]],
    owner_id: str,
    display_name: str,
) -> dict[str, dict[str, Any]]:
    """Compute trailing streaks for one owner from their chronological events."""
    if not events:
        return {}
    rev = list(reversed(events))

    # Most recent result determines which of {win, loss} streak we report.
    latest = rev[0]
    out: dict[str, dict[str, Any]] = {}

    if latest["result"] == "W":
        length, start, end = _trailing_run(rev, lambda e: e["result"] == "W")
        if length > 0:
            out["winStreak"] = {
                "type": "winStreak",
                "ownerId": owner_id,
                "displayName": display_name,
                "length": length,
                "start": start,
                "end": end,
            }
    elif latest["result"] == "L":
        length, start, end = _trailing_run(rev, lambda e: e["result"] == "L")
        if length > 0:
            out["lossStreak"] = {
                "type": "lossStreak",
                "ownerId": owner_id,
                "displayName": display_name,
                "length": length,
                "start": start,
                "end": end,
            }
    # A tie ends both streaks; no trailing run either way.

    # Point-threshold streaks are independent of W/L and track consecutive
    # games where the owner scored ≥ threshold.
    for t in _POINT_THRESHOLDS:
        length, start, end = _trailing_run(rev, lambda e, thr=t: e["points"] >= thr)
        if length > 0:
            key = f"plus{int(t)}Streak"
            out[key] = {
                "type": key,
                "threshold": t,
                "ownerId": owner_id,
                "displayName": display_name,
                "length": length,
                "start": start,
                "end": end,
            }
    return out


def _active_streaks_all(
    snapshot: PublicLeagueSnapshot,
    events: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Return {type: [streak, streak, ...]} across all owners.

    Streaks within each type are sorted by length descending.  Only
    owners with a non-zero length appear.
    """
    by_owner: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for ev in events:
        by_owner[ev["ownerId"]].append(ev)

    collected: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for owner_id, owner_events in by_owner.items():
        display = metrics.display_name_for(snapshot, owner_id)
        streaks = _active_streaks_for_owner(owner_events, owner_id, display)
        for stype, s in streaks.items():
            collected[stype].append(s)

    for stype in collected:
        collected[stype].sort(key=lambda s: -s["length"])
    return dict(collected)


def _longest_ever_win_loss(
    events: list[dict[str, Any]],
    snapshot: PublicLeagueSnapshot,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """All-time longest win and loss streaks (chronological, ties break)."""
    by_owner: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for ev in events:
        by_owner[ev["ownerId"]].append(ev)

    best_win = None
    best_loss = None
    for owner_id, owner_events in by_owner.items():
        cur_w = 0
        cur_l = 0
        w_start = None
        l_start = None
        for ev in owner_events:
            if ev["result"] == "W":
                cur_l = 0
                l_start = None
                cur_w += 1
                if cur_w == 1:
                    w_start = ev
                if best_win is None or cur_w > best_win["length"]:
                    best_win = {
                        "ownerId": owner_id,
                        "displayName": metrics.display_name_for(snapshot, owner_id),
                        "length": cur_w,
                        "start": w_start,
                        "end": ev,
                    }
            elif ev["result"] == "L":
                cur_w = 0
                w_start = None
                cur_l += 1
                if cur_l == 1:
                    l_start = ev
                if best_loss is None or cur_l > best_loss["length"]:
                    best_loss = {
                        "ownerId": owner_id,
                        "displayName": metrics.display_name_for(snapshot, owner_id),
                        "length": cur_l,
                        "start": l_start,
                        "end": ev,
                    }
            else:
                cur_w = 0
                cur_l = 0
                w_start = None
                l_start = None

    return best_win, best_loss


def _top_score_events(
    events: list[dict[str, Any]],
    highest: bool,
    n: int = _RECORDS_IN_REACH_TOP_N,
) -> list[dict[str, Any]]:
    filtered = [e for e in events if e["points"] > 0]
    filtered.sort(key=lambda e: e["points"], reverse=highest)
    out = []
    for e in filtered[:n]:
        out.append({
            "rank": len(out) + 1,
            **e,
            "displayName": None,  # filled in by caller
        })
    return out


def _latest_scored_week(
    snapshot: PublicLeagueSnapshot,
) -> tuple[str, int] | None:
    """Return the (season, week) of the most recently scored game."""
    latest: tuple[int, int, str, int] | None = None  # (year, week, season, week)
    for season, week, a, b, _is_playoff in metrics.walk_matchup_pairs(snapshot):
        try:
            yr = int(season.season)
        except (TypeError, ValueError):
            yr = 0
        key = (yr, week)
        if latest is None or key > latest[:2]:
            latest = (yr, week, season.season, week)
    if latest is None:
        return None
    return latest[2], latest[3]


def _notable_this_week(
    snapshot: PublicLeagueSnapshot,
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Entries from the most recent scored week that crack the all-time
    top-10 in any point-total, margin, or bad-beat category.
    """
    latest = _latest_scored_week(snapshot)
    if latest is None:
        return []
    latest_season, latest_week = latest

    # All-time sorted stacks.
    by_points_hi = sorted(events, key=lambda e: -e["points"])
    by_points_lo = sorted([e for e in events if e["points"] > 0], key=lambda e: e["points"])
    by_margin_hi = sorted(events, key=lambda e: -e["margin"])
    # Bad beats: high points in a loss (margin < 0, points high).
    losses = [e for e in events if e["result"] == "L"]
    by_bad_beat = sorted(losses, key=lambda e: -e["points"])

    def _rank_of(target: dict[str, Any], ordered: list[dict[str, Any]]) -> int | None:
        for i, e in enumerate(ordered):
            if (
                e["ownerId"] == target["ownerId"]
                and e["season"] == target["season"]
                and e["week"] == target["week"]
                and e["points"] == target["points"]
            ):
                return i + 1
        return None

    notables: list[dict[str, Any]] = []
    this_week_events = [
        e for e in events
        if e["season"] == latest_season and e["week"] == latest_week
    ]
    for ev in this_week_events:
        display = metrics.display_name_for(snapshot, ev["ownerId"])
        hi_rank = _rank_of(ev, by_points_hi)
        if hi_rank and hi_rank <= _RECORDS_IN_REACH_TOP_N:
            notables.append({
                "category": "highestSingleWeek",
                "rank": hi_rank,
                "label": _ordinal_label(hi_rank, "highest single-week score"),
                "ownerId": ev["ownerId"],
                "displayName": display,
                "season": ev["season"],
                "week": ev["week"],
                "value": ev["points"],
                "valueLabel": f"{ev['points']:.1f} pts",
            })
        lo_rank = _rank_of(ev, by_points_lo)
        if lo_rank and lo_rank <= _RECORDS_IN_REACH_TOP_N:
            notables.append({
                "category": "lowestSingleWeek",
                "rank": lo_rank,
                "label": _ordinal_label(lo_rank, "lowest single-week score"),
                "ownerId": ev["ownerId"],
                "displayName": display,
                "season": ev["season"],
                "week": ev["week"],
                "value": ev["points"],
                "valueLabel": f"{ev['points']:.1f} pts",
            })
        if ev["margin"] > 0:
            m_rank = _rank_of(ev, by_margin_hi)
            if m_rank and m_rank <= _RECORDS_IN_REACH_TOP_N:
                notables.append({
                    "category": "biggestBlowout",
                    "rank": m_rank,
                    "label": _ordinal_label(m_rank, "biggest single-week margin"),
                    "ownerId": ev["ownerId"],
                    "displayName": display,
                    "season": ev["season"],
                    "week": ev["week"],
                    "value": ev["margin"],
                    "valueLabel": f"+{ev['margin']:.1f}",
                })
        if ev["result"] == "L":
            bb_rank = _rank_of(ev, by_bad_beat)
            if bb_rank and bb_rank <= _RECORDS_IN_REACH_TOP_N:
                notables.append({
                    "category": "badBeat",
                    "rank": bb_rank,
                    "label": _ordinal_label(bb_rank, "highest score in a loss"),
                    "ownerId": ev["ownerId"],
                    "displayName": display,
                    "season": ev["season"],
                    "week": ev["week"],
                    "value": ev["points"],
                    "valueLabel": f"{ev['points']:.1f} pts in L",
                })
    notables.sort(key=lambda n: (n["rank"], n["category"]))
    return notables


def _ordinal_label(rank: int, thing: str) -> str:
    suffixes = {1: "st", 2: "nd", 3: "rd"}
    suffix = "th" if 10 <= rank % 100 <= 20 else suffixes.get(rank % 10, "th")
    return f"{rank}{suffix}-{thing} all-time"


def _records_in_reach(
    snapshot: PublicLeagueSnapshot,
    events: list[dict[str, Any]],
    active_streaks: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """For each all-time record, return the holder + the closest chaser."""
    records: list[dict[str, Any]] = []

    # Highest single-week score.
    scored = [e for e in events if e["points"] > 0]
    if scored:
        holder_ev = max(scored, key=lambda e: e["points"])
        records.append({
            "category": "highestSingleWeek",
            "label": "Highest single-week score",
            "holder": {
                "ownerId": holder_ev["ownerId"],
                "displayName": metrics.display_name_for(snapshot, holder_ev["ownerId"]),
                "value": holder_ev["points"],
                "valueLabel": f"{holder_ev['points']:.1f} pts",
                "season": holder_ev["season"],
                "week": holder_ev["week"],
            },
        })
        # Current season candidates.
        current_year = snapshot.current_season.season if snapshot.current_season else None
        current = [e for e in scored if e["season"] == current_year]
        if current:
            chaser = max(current, key=lambda e: e["points"])
            if chaser["ownerId"] != holder_ev["ownerId"] or chaser["week"] != holder_ev["week"]:
                records[-1]["chaser"] = {
                    "ownerId": chaser["ownerId"],
                    "displayName": metrics.display_name_for(snapshot, chaser["ownerId"]),
                    "value": chaser["points"],
                    "valueLabel": f"{chaser['points']:.1f} pts",
                    "season": chaser["season"],
                    "week": chaser["week"],
                    "gap": round(holder_ev["points"] - chaser["points"], 2),
                    "withinReach": chaser["points"] >= holder_ev["points"] * _NEAR_RECORD_POINTS_PCT,
                }

    # Longest win streak.
    best_win, best_loss = _longest_ever_win_loss(events, snapshot)
    if best_win:
        rec = {
            "category": "longestWinStreak",
            "label": "Longest win streak",
            "holder": {
                "ownerId": best_win["ownerId"],
                "displayName": best_win["displayName"],
                "value": best_win["length"],
                "valueLabel": f"{best_win['length']} straight",
                "season": best_win["end"]["season"] if best_win["end"] else None,
                "week": best_win["end"]["week"] if best_win["end"] else None,
            },
        }
        # Active win streak chaser.
        active_wins = active_streaks.get("winStreak") or []
        if active_wins:
            top = active_wins[0]
            if top["length"] > 0:
                rec["chaser"] = {
                    "ownerId": top["ownerId"],
                    "displayName": top["displayName"],
                    "value": top["length"],
                    "valueLabel": f"{top['length']} active",
                    "gap": best_win["length"] - top["length"],
                    "withinReach": top["length"] >= best_win["length"] - 1,
                }
        records.append(rec)
    if best_loss:
        rec = {
            "category": "longestLossStreak",
            "label": "Longest losing streak",
            "holder": {
                "ownerId": best_loss["ownerId"],
                "displayName": best_loss["displayName"],
                "value": best_loss["length"],
                "valueLabel": f"{best_loss['length']} straight",
                "season": best_loss["end"]["season"] if best_loss["end"] else None,
                "week": best_loss["end"]["week"] if best_loss["end"] else None,
            },
        }
        active_losses = active_streaks.get("lossStreak") or []
        if active_losses:
            top = active_losses[0]
            if top["length"] > 0:
                rec["chaser"] = {
                    "ownerId": top["ownerId"],
                    "displayName": top["displayName"],
                    "value": top["length"],
                    "valueLabel": f"{top['length']} active",
                    "gap": best_loss["length"] - top["length"],
                    "withinReach": top["length"] >= best_loss["length"] - 1,
                }
        records.append(rec)

    return records


# ── Public builder ───────────────────────────────────────────────────────
def build_section(snapshot: PublicLeagueSnapshot) -> dict[str, Any]:
    events = _all_events(snapshot)
    active = _active_streaks_all(snapshot, events)
    records = _records_in_reach(snapshot, events, active)
    notable = _notable_this_week(snapshot, events)
    latest = _latest_scored_week(snapshot)

    # Flatten active streaks into a single sorted list for rendering
    # convenience, keeping each owner's longest only.
    active_flat: list[dict[str, Any]] = []
    for stype, rows in active.items():
        for r in rows:
            active_flat.append({**r, "type": stype})
    # Sort longest first within type priority: win > loss > plus140 > plus120 > plus100
    type_priority = {
        "winStreak": 0,
        "lossStreak": 1,
        "plus140Streak": 2,
        "plus120Streak": 3,
        "plus100Streak": 4,
    }
    active_flat.sort(key=lambda s: (type_priority.get(s["type"], 99), -s["length"]))

    return {
        "seasonsCovered": [s.season for s in snapshot.seasons],
        "currentSeason": snapshot.current_season.season if snapshot.current_season else None,
        "latestWeek": (
            {"season": latest[0], "week": latest[1]} if latest else None
        ),
        "activeStreaks": active_flat,
        "activeStreaksByType": active,
        "recordsInReach": records,
        "notableThisWeek": notable,
        "thresholds": {
            "points": list(_POINT_THRESHOLDS),
        },
    }
