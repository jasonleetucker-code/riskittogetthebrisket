"""Section: Draft Center.

Draft results by season, rookie-draft recap, current pick-ownership
map, weighted stockpile per manager, most-traded pick lineage.

Weighting (from prompt):
    1st round = 4, 2nd round = 3, 3rd round = 2, 4th+ = 1
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from . import metrics
from .snapshot import PublicLeagueSnapshot, SeasonSnapshot


ROUND_WEIGHT = {1: 4, 2: 3, 3: 2}


def pick_weight(round_: int | None) -> int:
    if round_ is None:
        return 0
    return ROUND_WEIGHT.get(int(round_), 1)


def _normalize_pick(snapshot: PublicLeagueSnapshot, season: SeasonSnapshot, pick: dict[str, Any]) -> dict[str, Any]:
    rid = metrics.roster_id_of(pick)
    try:
        round_ = int(pick.get("round") or 0)
    except (TypeError, ValueError):
        round_ = 0
    try:
        pick_no = int(pick.get("pick_no") or 0)
    except (TypeError, ValueError):
        pick_no = 0
    owner_id = (
        metrics.resolve_owner(snapshot.managers, season.league_id, rid) if rid is not None else ""
    )
    metadata = pick.get("metadata") or {}
    first = str(metadata.get("first_name") or "").strip()
    last = str(metadata.get("last_name") or "").strip()
    player_name = f"{first} {last}".strip() or None
    player_id = str(pick.get("player_id") or "")
    if not player_name and player_id:
        player_name = snapshot.player_display(player_id) or None
    return {
        "round": round_,
        "pickNo": pick_no,
        "rosterId": rid,
        "ownerId": owner_id,
        "teamName": metrics.team_name(snapshot, season.league_id, rid) if rid is not None else "",
        "playerId": player_id,
        "playerName": player_name,
        "position": metadata.get("position") or snapshot.player_position(player_id) or None,
        "nflTeam": metadata.get("team") or None,
    }


def _draft_summary(snapshot: PublicLeagueSnapshot, season: SeasonSnapshot, draft: dict[str, Any]) -> dict[str, Any]:
    draft_id = str(draft.get("draft_id") or "")
    picks = season.draft_picks_by_draft.get(draft_id, [])
    normalized = [_normalize_pick(snapshot, season, p) for p in picks]
    normalized.sort(key=lambda r: (r["round"] or 99, r["pickNo"] or 999))
    first_round = [p for p in normalized if p["round"] == 1]
    return {
        "draftId": draft_id,
        "season": season.season,
        "leagueId": season.league_id,
        "type": draft.get("type") or "",
        "status": draft.get("status") or "",
        "startTime": draft.get("start_time") or None,
        "rounds": int((draft.get("settings") or {}).get("rounds") or 0) if isinstance(draft.get("settings"), dict) else 0,
        "picks": normalized,
        "firstRoundRecap": first_round,
    }


def _pick_ownership_map(snapshot: PublicLeagueSnapshot) -> dict[str, list[dict[str, Any]]]:
    """Current pick ownership per owner_id, organized by future season.

    Sleeper's ``traded_picks`` lists only picks that have changed
    hands.  We reconstruct the full future pick inventory per roster
    using the current rosters + draft_rounds from league settings,
    then apply the traded_picks diff to derive present ownership.
    """
    current = snapshot.current_season
    if current is None:
        return {}

    num_teams = current.num_teams or max(1, len(current.rosters))
    settings = current.league.get("settings") or {}
    try:
        draft_rounds = int(settings.get("draft_rounds") or 0)
    except (TypeError, ValueError):
        draft_rounds = 0
    if draft_rounds <= 0:
        draft_rounds = 4

    future_years = _future_seasons(current, count=2)
    original_by_rid: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for r in current.rosters:
        try:
            rid = int(r.get("roster_id"))
        except (TypeError, ValueError):
            continue
        for yr in future_years:
            for rnd in range(1, draft_rounds + 1):
                original_by_rid[rid].append({
                    "season": yr,
                    "round": rnd,
                    "fromRosterId": rid,
                    "ownerRosterId": rid,
                })

    # Apply traded picks (chronological across all seasons so the most
    # recent ownership wins).
    for season in snapshot.seasons:
        for tp in season.traded_picks:
            try:
                yr = str(tp.get("season") or "")
                rnd = int(tp.get("round"))
                origin_rid = int(tp.get("roster_id"))
                current_owner_rid = int(tp.get("owner_id"))
            except (TypeError, ValueError):
                continue
            if yr not in future_years:
                continue
            for bucket in original_by_rid.values():
                for pick in bucket:
                    if (
                        pick["season"] == yr
                        and pick["round"] == rnd
                        and pick["fromRosterId"] == origin_rid
                    ):
                        pick["ownerRosterId"] = current_owner_rid

    by_owner: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for bucket in original_by_rid.values():
        for pick in bucket:
            owner_id = metrics.resolve_owner(
                snapshot.managers, current.league_id, pick["ownerRosterId"]
            )
            original_owner_id = metrics.resolve_owner(
                snapshot.managers, current.league_id, pick["fromRosterId"]
            )
            if not owner_id:
                continue
            by_owner[owner_id].append({
                "season": pick["season"],
                "round": pick["round"],
                "originalOwnerId": original_owner_id,
                "isTraded": owner_id != original_owner_id,
                "label": f"{pick['season']} R{pick['round']}",
            })
    for owner_id, lst in by_owner.items():
        lst.sort(key=lambda p: (p["season"], p["round"]))
    return dict(by_owner)


def _future_seasons(current: SeasonSnapshot, count: int = 2) -> list[str]:
    try:
        yr = int(current.season)
    except (TypeError, ValueError):
        return []
    # Future picks start the year AFTER the current league season.
    return [str(yr + i + 1) for i in range(count)]


def weighted_stockpile_for_owner(snapshot: PublicLeagueSnapshot, owner_id: str) -> dict[str, Any]:
    """Public-safe weighted draft capital summary for one owner."""
    ownership = _pick_ownership_map(snapshot)
    picks = ownership.get(owner_id, [])
    weight = sum(pick_weight(p["round"]) for p in picks)
    by_round: dict[int, int] = defaultdict(int)
    for p in picks:
        by_round[p["round"]] += 1
    return {
        "totalPicks": len(picks),
        "weightedScore": weight,
        "byRound": {str(r): n for r, n in sorted(by_round.items())},
        "picks": picks,
    }


def _stockpile_leaderboard(snapshot: PublicLeagueSnapshot, ownership: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    rows = []
    for owner_id, picks in ownership.items():
        rows.append({
            "ownerId": owner_id,
            "displayName": metrics.display_name_for(snapshot, owner_id),
            "totalPicks": len(picks),
            "weightedScore": sum(pick_weight(p["round"]) for p in picks),
        })
    rows.sort(key=lambda r: (-r["weightedScore"], -r["totalPicks"]))
    return rows


def _most_traded_pick(snapshot: PublicLeagueSnapshot) -> dict[str, Any] | None:
    """Pick whose ownership has moved the most times across the chain."""
    moves: dict[tuple[str, int, int], int] = defaultdict(int)
    for season in snapshot.seasons:
        for tp in season.traded_picks:
            try:
                yr = str(tp.get("season") or "")
                rnd = int(tp.get("round"))
                origin_rid = int(tp.get("roster_id"))
            except (TypeError, ValueError):
                continue
            moves[(yr, rnd, origin_rid)] += 1
    if not moves:
        return None
    (yr, rnd, origin_rid), count = max(moves.items(), key=lambda kv: kv[1])
    current = snapshot.current_season
    league_id = current.league_id if current else ""
    original_owner_id = metrics.resolve_owner(snapshot.managers, league_id, origin_rid)
    return {
        "season": yr,
        "round": rnd,
        "originalOwnerId": original_owner_id,
        "label": f"{yr} R{rnd}",
        "moveCount": count,
    }


def _pick_movement_trail(snapshot: PublicLeagueSnapshot) -> list[dict[str, Any]]:
    """Every traded pick with original vs current owner."""
    current = snapshot.current_season
    league_id = current.league_id if current else ""
    out: list[dict[str, Any]] = []
    for season in snapshot.seasons:
        for tp in season.traded_picks:
            try:
                yr = str(tp.get("season") or "")
                rnd = int(tp.get("round"))
                origin_rid = int(tp.get("roster_id"))
                current_owner_rid = int(tp.get("owner_id"))
            except (TypeError, ValueError):
                continue
            original_owner_id = metrics.resolve_owner(snapshot.managers, league_id, origin_rid)
            current_owner_id = metrics.resolve_owner(snapshot.managers, league_id, current_owner_rid)
            out.append({
                "season": yr,
                "round": rnd,
                "label": f"{yr} R{rnd}",
                "originalOwnerId": original_owner_id,
                "currentOwnerId": current_owner_id,
                "sourceSeason": season.season,
            })
    return out


def build_section(snapshot: PublicLeagueSnapshot) -> dict[str, Any]:
    drafts: list[dict[str, Any]] = []
    for season in snapshot.seasons:
        for draft in season.drafts:
            drafts.append(_draft_summary(snapshot, season, draft))
    drafts.sort(key=lambda d: (d["season"], d.get("startTime") or 0), reverse=True)

    ownership = _pick_ownership_map(snapshot)
    leaderboard = _stockpile_leaderboard(snapshot, ownership)
    most_picks = leaderboard[0] if leaderboard else None
    fewest_picks = leaderboard[-1] if leaderboard else None

    return {
        "drafts": drafts,
        "pickOwnership": ownership,
        "stockpileLeaderboard": leaderboard,
        "mostPicksOwned": most_picks,
        "fewestPicksOwned": fewest_picks,
        "mostTradedPick": _most_traded_pick(snapshot),
        "pickMovementTrail": _pick_movement_trail(snapshot),
        "seasonsCovered": [s.season for s in snapshot.seasons],
    }
