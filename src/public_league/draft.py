"""Section: Draft Center.

Per-season rookie / startup draft results + remaining draft capital
per franchise.  Attribution is by owner_id at the time of the draft
(pick ownership) using the Sleeper picks payload.

No private valuation / rank signal leaks into this section.
"""
from __future__ import annotations

from typing import Any

from .history import _team_name_for
from .snapshot import PublicLeagueSnapshot, SeasonSnapshot


def _normalize_pick(snapshot: PublicLeagueSnapshot, season: SeasonSnapshot, pick: dict[str, Any]) -> dict[str, Any]:
    try:
        roster_id = int(pick.get("roster_id"))
    except (TypeError, ValueError):
        roster_id = None
    try:
        round_ = int(pick.get("round") or 0)
    except (TypeError, ValueError):
        round_ = 0
    try:
        pick_no = int(pick.get("pick_no") or 0)
    except (TypeError, ValueError):
        pick_no = 0
    owner_id = snapshot.managers.owner_for_roster(season.league_id, roster_id) if roster_id is not None else ""
    metadata = pick.get("metadata") or {}
    return {
        "round": round_,
        "pickNo": pick_no,
        "rosterId": roster_id,
        "ownerId": owner_id,
        "teamName": _team_name_for(snapshot, season.league_id, roster_id) if roster_id is not None else "",
        "playerId": str(pick.get("player_id") or ""),
        "playerName": (
            str(metadata.get("first_name") or "").strip() + " " + str(metadata.get("last_name") or "").strip()
        ).strip() or None,
        "position": metadata.get("position") or None,
        "nflTeam": metadata.get("team") or None,
    }


def _draft_summary(snapshot: PublicLeagueSnapshot, season: SeasonSnapshot, draft: dict[str, Any]) -> dict[str, Any]:
    draft_id = str(draft.get("draft_id") or "")
    picks = season.draft_picks_by_draft.get(draft_id, [])
    normalized = [_normalize_pick(snapshot, season, p) for p in picks]
    normalized.sort(key=lambda r: (r["round"] or 99, r["pickNo"] or 999))
    return {
        "draftId": draft_id,
        "season": season.season,
        "leagueId": season.league_id,
        "type": draft.get("type") or "",
        "status": draft.get("status") or "",
        "startTime": draft.get("start_time") or None,
        "rounds": int(draft.get("settings", {}).get("rounds") or 0) if isinstance(draft.get("settings"), dict) else 0,
        "picks": normalized,
    }


def _remaining_capital(snapshot: PublicLeagueSnapshot) -> list[dict[str, Any]]:
    """Aggregate ``traded_picks`` ownership across all seasons to a slim
    view of each manager's outstanding future-pick capital.
    """
    # Sleeper traded_picks lists picks that have been traded from their
    # original roster to a new owner.  For a public view we only show
    # the NET outcome per manager: how many picks they currently own
    # that were originally someone else's, and how many of their own
    # picks they've dealt away.
    owner_net: dict[str, dict[str, Any]] = {}

    def _ensure(owner_id: str) -> dict[str, Any]:
        if owner_id not in owner_net:
            owner_net[owner_id] = {
                "ownerId": owner_id,
                "acquiredPicks": 0,
                "tradedAwayPicks": 0,
                "netPicks": 0,
                "details": [],
            }
        return owner_net[owner_id]

    for season in snapshot.seasons:
        for pick in season.traded_picks:
            season_year = pick.get("season")
            round_ = pick.get("round")
            try:
                origin_rid = int(pick.get("roster_id"))
                current_owner_rid = int(pick.get("owner_id"))
            except (TypeError, ValueError):
                continue
            original_owner_id = snapshot.managers.owner_for_roster(season.league_id, origin_rid)
            current_owner_id = snapshot.managers.owner_for_roster(season.league_id, current_owner_rid)
            if not original_owner_id or not current_owner_id:
                continue
            if original_owner_id == current_owner_id:
                # Round-tripped back to the original owner — skip.
                continue
            _ensure(current_owner_id)["acquiredPicks"] += 1
            _ensure(original_owner_id)["tradedAwayPicks"] += 1
            _ensure(current_owner_id)["details"].append({
                "season": season_year,
                "round": round_,
                "originalOwnerId": original_owner_id,
            })

    for rec in owner_net.values():
        rec["netPicks"] = rec["acquiredPicks"] - rec["tradedAwayPicks"]
    return sorted(owner_net.values(), key=lambda r: -r["netPicks"])


def build_section(snapshot: PublicLeagueSnapshot) -> dict[str, Any]:
    drafts: list[dict[str, Any]] = []
    for season in snapshot.seasons:
        for draft in season.drafts:
            drafts.append(_draft_summary(snapshot, season, draft))
    drafts.sort(key=lambda d: (d["season"], d.get("startTime") or 0), reverse=True)
    return {
        "drafts": drafts,
        "remainingCapital": _remaining_capital(snapshot),
        "seasonsCovered": [s.season for s in snapshot.seasons],
    }
