"""Section: League Superlatives.

Fun narrative labels derived strictly from Sleeper public data:
    * Biggest Comeback-of-the-Year (widest PA vs record gap)
    * Hard-Luck Manager (high PF, below-expected record)
    * Lucky Duck (low PF, above-expected record)
    * Most Improved (season-over-season wins delta)
    * Trade Machine (trade volume leader)
    * Couch Coach (lowest avg PF)

Every superlative attributes to an owner_id; no private data.
"""
from __future__ import annotations

from typing import Any

from .history import _regular_season_records
from .snapshot import PublicLeagueSnapshot


def _points_vs_record_diff(snapshot: PublicLeagueSnapshot, season) -> list[dict[str, Any]]:
    """Compute per-manager PF rank minus win rank for a season.

    Positive = higher PF than record would imply (hard-luck).
    Negative = higher record than PF would imply (lucky duck).
    """
    regular = _regular_season_records(season)
    if not regular:
        return []

    rids = list(regular.keys())
    pf_rank = sorted(rids, key=lambda r: -regular[r]["pointsFor"])
    win_rank = sorted(rids, key=lambda r: -(regular[r]["wins"] + regular[r]["ties"] * 0.5))

    pf_rank_map = {rid: i + 1 for i, rid in enumerate(pf_rank)}
    win_rank_map = {rid: i + 1 for i, rid in enumerate(win_rank)}

    out: list[dict[str, Any]] = []
    for rid in rids:
        owner_id = snapshot.managers.owner_for_roster(season.league_id, rid)
        if not owner_id:
            continue
        out.append({
            "ownerId": owner_id,
            "season": season.season,
            "pfRank": pf_rank_map[rid],
            "winRank": win_rank_map[rid],
            "delta": pf_rank_map[rid] - win_rank_map[rid],
            "pointsFor": regular[rid]["pointsFor"],
            "wins": regular[rid]["wins"],
            "losses": regular[rid]["losses"],
        })
    return out


def build_section(snapshot: PublicLeagueSnapshot) -> dict[str, Any]:
    per_season_diffs: list[dict[str, Any]] = []
    for season in snapshot.seasons:
        per_season_diffs.extend(_points_vs_record_diff(snapshot, season))

    hard_luck = sorted(per_season_diffs, key=lambda r: -r["delta"])[:5]
    lucky_duck = sorted(per_season_diffs, key=lambda r: r["delta"])[:5]

    # Trade volume by owner_id across chain.
    trade_counts: dict[str, int] = {}
    for season in snapshot.seasons:
        for week_tx in season.transactions_by_week.values():
            for tx in week_tx:
                if str(tx.get("type") or "").lower() != "trade":
                    continue
                if str(tx.get("status") or "").lower() != "complete":
                    continue
                for rid in tx.get("roster_ids") or []:
                    owner_id = snapshot.managers.owner_for_roster(season.league_id, rid)
                    if owner_id:
                        trade_counts[owner_id] = trade_counts.get(owner_id, 0) + 1
    trade_machine = sorted(
        ({"ownerId": oid, "trades": n} for oid, n in trade_counts.items()),
        key=lambda r: -r["trades"],
    )[:5]

    # Most improved season-over-season wins delta (need 2+ seasons).
    by_owner: dict[str, dict[str, dict[str, Any]]] = {}
    for season in snapshot.seasons:
        regular = _regular_season_records(season)
        for rid, rec in regular.items():
            owner_id = snapshot.managers.owner_for_roster(season.league_id, rid)
            if not owner_id:
                continue
            by_owner.setdefault(owner_id, {})[season.season] = rec

    most_improved: list[dict[str, Any]] = []
    if len(snapshot.seasons) >= 2:
        cur_season = snapshot.seasons[0].season
        prev_season = snapshot.seasons[1].season
        for owner_id, by_season in by_owner.items():
            cur = by_season.get(cur_season)
            prev = by_season.get(prev_season)
            if not cur or not prev:
                continue
            wins_delta = cur["wins"] - prev["wins"]
            most_improved.append({
                "ownerId": owner_id,
                "currentSeason": cur_season,
                "previousSeason": prev_season,
                "winsDelta": wins_delta,
                "currentRecord": f"{cur['wins']}-{cur['losses']}",
                "previousRecord": f"{prev['wins']}-{prev['losses']}",
            })
        most_improved.sort(key=lambda r: -r["winsDelta"])

    couch_coach: list[dict[str, Any]] = []
    weeks_by_owner: dict[str, list[float]] = {}
    for season in snapshot.seasons:
        for week, entries in season.matchups_by_week.items():
            for m in entries:
                try:
                    rid = int(m.get("roster_id"))
                except (TypeError, ValueError):
                    continue
                pts = float(m.get("points") or 0.0)
                if pts <= 0:
                    continue
                owner_id = snapshot.managers.owner_for_roster(season.league_id, rid)
                if owner_id:
                    weeks_by_owner.setdefault(owner_id, []).append(pts)
    for owner_id, ws in weeks_by_owner.items():
        if not ws:
            continue
        couch_coach.append({
            "ownerId": owner_id,
            "avgPoints": round(sum(ws) / len(ws), 2),
            "weeksPlayed": len(ws),
        })
    couch_coach.sort(key=lambda r: r["avgPoints"])

    return {
        "hardLuck": hard_luck,
        "luckyDuck": lucky_duck,
        "tradeMachine": trade_machine,
        "mostImproved": most_improved[:5],
        "couchCoach": couch_coach[:5],
    }
