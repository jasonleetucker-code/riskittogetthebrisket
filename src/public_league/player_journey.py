"""Public player-journey view — follow a single player through every
trade, waiver, and weekly starter slot across the 2-season window.

For a given ``player_id`` we emit:
    * identity — name, position, NFL team, years_exp
    * ownership timeline — which manager rostered them each week
    * transactions — every trade / waiver / FA add / drop involving
      that player, with date, manager, and pick compensation
    * scoring summary — per-manager points scored while rostered,
      broken down by ``started`` vs ``benched`` vs ``not-rostered``
    * fantasy highlights — best single week, worst single week
    * roster arc — the sequence of managers who held the player

Everything is derived from the public snapshot.  No private
internals.  This lets us render a "journey" page nobody else in dynasty
tooling has.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from . import metrics
from .snapshot import PublicLeagueSnapshot, SeasonSnapshot


def _player_identity(snapshot: PublicLeagueSnapshot, player_id: str) -> dict[str, Any]:
    p = snapshot.nfl_players.get(str(player_id)) or {}
    return {
        "playerId": str(player_id),
        "playerName": snapshot.player_display(player_id),
        "position": snapshot.player_position(player_id) or (p.get("position") if isinstance(p, dict) else "") or "",
        "nflTeam": (p.get("team") if isinstance(p, dict) else "") or "",
        "yearsExp": (p.get("years_exp") if isinstance(p, dict) else None),
    }


def _owner_display(snapshot: PublicLeagueSnapshot, owner_id: str) -> dict[str, Any]:
    return {
        "ownerId": owner_id,
        "displayName": metrics.display_name_for(snapshot, owner_id),
    }


def _transactions_for(
    snapshot: PublicLeagueSnapshot,
    season: SeasonSnapshot,
    player_id: str,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []

    def _resolve(rid: Any) -> str:
        return metrics.resolve_owner(snapshot.managers, season.league_id, rid)

    for week in sorted(season.transactions_by_week.keys()):
        for tx in season.transactions_by_week[week]:
            status = str(tx.get("status") or "").lower()
            if status != "complete":
                continue
            ttype = str(tx.get("type") or "").lower()
            adds = tx.get("adds") or {}
            drops = tx.get("drops") or {}

            if str(player_id) in adds:
                added_to_rid = adds[str(player_id)]
                to_owner = _resolve(added_to_rid)
                events.append({
                    "kind": "add",
                    "txType": ttype,
                    "season": season.season,
                    "week": week,
                    "createdAt": tx.get("created") or tx.get("status_updated"),
                    "transactionId": str(tx.get("transaction_id") or ""),
                    "toOwnerId": to_owner,
                    "toDisplayName": metrics.display_name_for(snapshot, to_owner) if to_owner else "",
                    "faabBid": (tx.get("settings") or {}).get("waiver_bid"),
                })
            if str(player_id) in drops:
                dropped_from_rid = drops[str(player_id)]
                from_owner = _resolve(dropped_from_rid)
                events.append({
                    "kind": "drop",
                    "txType": ttype,
                    "season": season.season,
                    "week": week,
                    "createdAt": tx.get("created") or tx.get("status_updated"),
                    "transactionId": str(tx.get("transaction_id") or ""),
                    "fromOwnerId": from_owner,
                    "fromDisplayName": metrics.display_name_for(snapshot, from_owner) if from_owner else "",
                })
    events.sort(key=lambda e: (int(e.get("createdAt") or 0), e.get("kind") or ""))
    return events


def _scoring_summary(
    snapshot: PublicLeagueSnapshot,
    season: SeasonSnapshot,
    player_id: str,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]], dict[str, Any] | None, dict[str, Any] | None]:
    """Per-owner points scored while this player was rostered, plus
    a sparse per-week log ``[{owner, week, points, started}]`` and
    best/worst single-week entries.
    """
    per_owner: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "pointsStarted": 0.0,
        "pointsBenched": 0.0,
        "weeksStarted": 0,
        "weeksRostered": 0,
    })
    weekly_log: list[dict[str, Any]] = []
    best: dict[str, Any] | None = None
    worst: dict[str, Any] | None = None
    pid = str(player_id)

    for week in sorted(season.matchups_by_week.keys()):
        for entry in season.matchups_by_week[week]:
            roster = {str(x) for x in (entry.get("players") or []) if x}
            starters = {str(x) for x in (entry.get("starters") or []) if x}
            pp_keys = {str(k) for k in (entry.get("players_points") or {}).keys()}
            # Player is "rostered this week" if they appear in any of
            # players / starters / players_points.  Sleeper fills all
            # three in production, but older seasons + our unit-test
            # fixtures sometimes only populate the starters + points
            # pair — treat any presence as evidence.
            if pid not in roster and pid not in starters and pid not in pp_keys:
                continue
            rid = metrics.roster_id_of(entry)
            if rid is None:
                continue
            owner_id = metrics.resolve_owner(snapshot.managers, season.league_id, rid)
            if not owner_id:
                continue
            pp = entry.get("players_points") or {}
            try:
                pts = float(pp.get(pid) or 0.0)
            except (TypeError, ValueError):
                pts = 0.0
            started = pid in starters
            rec = per_owner[owner_id]
            rec["weeksRostered"] += 1
            if started:
                rec["pointsStarted"] += pts
                rec["weeksStarted"] += 1
            else:
                rec["pointsBenched"] += pts

            weekly_log.append({
                "season": season.season,
                "week": week,
                "ownerId": owner_id,
                "displayName": metrics.display_name_for(snapshot, owner_id),
                "started": started,
                "points": round(pts, 2),
            })

            if started and pts > 0:
                entry_blob = {
                    "season": season.season,
                    "week": week,
                    "ownerId": owner_id,
                    "displayName": metrics.display_name_for(snapshot, owner_id),
                    "points": round(pts, 2),
                }
                if best is None or pts > best["points"]:
                    best = entry_blob
                if worst is None or pts < worst["points"]:
                    worst = entry_blob

    for owner_id, rec in per_owner.items():
        rec["pointsStarted"] = round(rec["pointsStarted"], 2)
        rec["pointsBenched"] = round(rec["pointsBenched"], 2)
        rec["pointsTotal"] = round(rec["pointsStarted"] + rec["pointsBenched"], 2)

    return dict(per_owner), weekly_log, best, worst


def _draft_origin(snapshot: PublicLeagueSnapshot, player_id: str) -> dict[str, Any] | None:
    """If the player was taken in a rookie draft in the window, return
    the draft slot + drafted-by-owner."""
    pid = str(player_id)
    for season in snapshot.seasons:
        for draft_id, picks in season.draft_picks_by_draft.items():
            for p in picks:
                if str(p.get("player_id") or "") != pid:
                    continue
                rid = metrics.roster_id_of(p)
                owner_id = (
                    metrics.resolve_owner(snapshot.managers, season.league_id, rid)
                    if rid is not None else ""
                )
                return {
                    "season": season.season,
                    "leagueId": season.league_id,
                    "draftId": draft_id,
                    "round": int(p.get("round") or 0) or None,
                    "pickNo": int(p.get("pick_no") or 0) or None,
                    "ownerId": owner_id,
                    "displayName": metrics.display_name_for(snapshot, owner_id) if owner_id else "",
                }
    return None


def build_player_journey(
    snapshot: PublicLeagueSnapshot,
    player_id: str,
) -> dict[str, Any] | None:
    """Full public journey for ``player_id``.  ``None`` if the player is
    unknown AND no activity references them (defensive; missing player
    dump shouldn't 404 a known transaction subject)."""
    pid = str(player_id or "").strip()
    if not pid:
        return None

    identity = _player_identity(snapshot, pid)
    draft_origin = _draft_origin(snapshot, pid)

    per_season: list[dict[str, Any]] = []
    per_owner_totals: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "pointsStarted": 0.0,
        "pointsBenched": 0.0,
        "pointsTotal": 0.0,
        "weeksStarted": 0,
        "weeksRostered": 0,
    })
    all_weekly: list[dict[str, Any]] = []
    best_overall: dict[str, Any] | None = None
    worst_overall: dict[str, Any] | None = None
    all_events: list[dict[str, Any]] = []

    for season in snapshot.seasons:
        txs = _transactions_for(snapshot, season, pid)
        scoring, weekly, best, worst = _scoring_summary(snapshot, season, pid)
        all_events.extend(txs)
        all_weekly.extend(weekly)

        for owner_id, rec in scoring.items():
            agg = per_owner_totals[owner_id]
            agg["pointsStarted"] += rec["pointsStarted"]
            agg["pointsBenched"] += rec["pointsBenched"]
            agg["pointsTotal"] += rec["pointsTotal"]
            agg["weeksStarted"] += rec["weeksStarted"]
            agg["weeksRostered"] += rec["weeksRostered"]

        if best and (best_overall is None or best["points"] > best_overall["points"]):
            best_overall = best
        if worst and (worst_overall is None or worst["points"] < worst_overall["points"]):
            worst_overall = worst

        per_season.append({
            "season": season.season,
            "leagueId": season.league_id,
            "transactions": txs,
            "byOwner": [
                {"ownerId": owner, **stats}
                for owner, stats in sorted(
                    scoring.items(),
                    key=lambda kv: -kv[1]["pointsTotal"],
                )
            ],
            "weeklyLog": weekly,
            "bestWeek": best,
            "worstWeek": worst,
        })

    has_activity = (
        bool(all_events)
        or bool(all_weekly)
        or draft_origin is not None
    )
    if not has_activity:
        return None

    # Build ordered arc of managers (dedupe by owner_id preserving
    # insertion order) based on transaction events + weekly log.
    arc_seen: set[str] = set()
    arc: list[dict[str, Any]] = []
    arc_events = sorted(
        all_weekly,
        key=lambda e: (int(e.get("season") or 0), e["week"]),
    )
    for e in arc_events:
        owner_id = e["ownerId"]
        if owner_id in arc_seen:
            continue
        arc_seen.add(owner_id)
        arc.append(_owner_display(snapshot, owner_id))

    # Finalize per-owner totals.
    totals = [
        {
            "ownerId": owner,
            "displayName": metrics.display_name_for(snapshot, owner),
            "pointsStarted": round(t["pointsStarted"], 2),
            "pointsBenched": round(t["pointsBenched"], 2),
            "pointsTotal": round(t["pointsTotal"], 2),
            "weeksStarted": t["weeksStarted"],
            "weeksRostered": t["weeksRostered"],
        }
        for owner, t in per_owner_totals.items()
    ]
    totals.sort(key=lambda r: -r["pointsTotal"])

    return {
        "identity": identity,
        "draftOrigin": draft_origin,
        "ownershipArc": arc,
        "totalsByOwner": totals,
        "bestWeek": best_overall,
        "worstWeek": worst_overall,
        "events": sorted(all_events, key=lambda e: int(e.get("createdAt") or 0)),
        "bySeason": per_season,
        "seasonsCovered": [s.season for s in snapshot.seasons],
    }


def list_players_with_activity(snapshot: PublicLeagueSnapshot) -> list[dict[str, Any]]:
    """Return every player_id that appears in the snapshot's transactions
    or on a roster — the set of valid ``/league/player/[playerId]`` routes.
    """
    seen: set[str] = set()
    for season in snapshot.seasons:
        for roster in season.rosters:
            for pid in (roster.get("players") or []):
                if pid:
                    seen.add(str(pid))
        for week_txs in season.transactions_by_week.values():
            for tx in week_txs:
                for pid in (tx.get("adds") or {}):
                    if pid:
                        seen.add(str(pid))
                for pid in (tx.get("drops") or {}):
                    if pid:
                        seen.add(str(pid))
    out = []
    for pid in sorted(seen):
        out.append({
            "playerId": pid,
            "playerName": snapshot.player_display(pid),
            "position": snapshot.player_position(pid),
        })
    return out
