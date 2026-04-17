"""Section: Franchise Pages.

Per-manager franchise summaries — team-name lineage, cumulative
record, per-season results, trade counts, and draft counts.
Attribution is by owner_id.

The section emits both:
    * ``index`` — compact rows for the franchise list
    * ``detail`` — keyed-by-owner-id detailed pages

The public contract will normally include both; consumers may request
``?section=franchise&owner=<owner_id>`` to get just one detail page.
"""
from __future__ import annotations

from typing import Any

from .history import _final_standing_from_bracket, _regular_season_records
from .snapshot import PublicLeagueSnapshot


def _franchise_base(snapshot: PublicLeagueSnapshot) -> dict[str, dict[str, Any]]:
    """Initialize per-owner franchise skeletons."""
    franchises: dict[str, dict[str, Any]] = {}
    for owner_id, manager in snapshot.managers.by_owner_id.items():
        franchises[owner_id] = {
            **manager.to_public_dict(),
            "cumulative": {
                "wins": 0,
                "losses": 0,
                "ties": 0,
                "pointsFor": 0.0,
                "pointsAgainst": 0.0,
                "seasonsPlayed": 0,
                "championships": 0,
                "runnerUps": 0,
                "playoffAppearances": 0,
            },
            "seasonResults": [],
            "tradeCount": 0,
            "draftPickCount": 0,
        }
    return franchises


def build_section(snapshot: PublicLeagueSnapshot) -> dict[str, Any]:
    franchises = _franchise_base(snapshot)

    for season in snapshot.seasons:
        regular = _regular_season_records(season)
        placement = _final_standing_from_bracket(season.winners_bracket)
        for rid, rec in regular.items():
            owner_id = snapshot.managers.owner_for_roster(season.league_id, rid)
            if not owner_id or owner_id not in franchises:
                continue
            cum = franchises[owner_id]["cumulative"]
            cum["wins"] += rec["wins"]
            cum["losses"] += rec["losses"]
            cum["ties"] += rec["ties"]
            cum["pointsFor"] += rec["pointsFor"]
            cum["pointsAgainst"] += rec["pointsAgainst"]
            cum["seasonsPlayed"] += 1
            final_place = placement.get(rid)
            if final_place:
                cum["playoffAppearances"] += 1
                if final_place == 1:
                    cum["championships"] += 1
                elif final_place == 2:
                    cum["runnerUps"] += 1
            franchises[owner_id]["seasonResults"].append({
                "season": season.season,
                "leagueId": season.league_id,
                "wins": rec["wins"],
                "losses": rec["losses"],
                "ties": rec["ties"],
                "pointsFor": rec["pointsFor"],
                "pointsAgainst": rec["pointsAgainst"],
                "finalPlace": final_place,
            })

    # Trade counts per owner_id.  A transaction with type "trade"
    # credits every roster_id in its ``roster_ids`` list.
    for season in snapshot.seasons:
        for week_tx in season.transactions_by_week.values():
            for tx in week_tx:
                if str(tx.get("type") or "").lower() != "trade":
                    continue
                if str(tx.get("status") or "").lower() != "complete":
                    continue
                for rid in tx.get("roster_ids") or []:
                    owner_id = snapshot.managers.owner_for_roster(season.league_id, rid)
                    if owner_id and owner_id in franchises:
                        franchises[owner_id]["tradeCount"] += 1

    # Draft pick counts per owner_id.
    for season in snapshot.seasons:
        for picks in season.draft_picks_by_draft.values():
            for pick in picks:
                try:
                    rid = int(pick.get("roster_id"))
                except (TypeError, ValueError):
                    continue
                owner_id = snapshot.managers.owner_for_roster(season.league_id, rid)
                if owner_id and owner_id in franchises:
                    franchises[owner_id]["draftPickCount"] += 1

    # Finalize numeric rounding + build index.
    detail: dict[str, dict[str, Any]] = {}
    index: list[dict[str, Any]] = []
    for owner_id, fr in franchises.items():
        cum = fr["cumulative"]
        cum["pointsFor"] = round(cum["pointsFor"], 2)
        cum["pointsAgainst"] = round(cum["pointsAgainst"], 2)
        detail[owner_id] = fr
        index.append({
            "ownerId": owner_id,
            "displayName": fr["displayName"],
            "currentTeamName": fr["currentTeamName"],
            "avatar": fr.get("avatar") or "",
            "seasonsPlayed": cum["seasonsPlayed"],
            "wins": cum["wins"],
            "losses": cum["losses"],
            "championships": cum["championships"],
        })
    index.sort(key=lambda r: (-r["championships"], -r["wins"], r["displayName"].lower()))
    return {"index": index, "detail": detail}


def build_franchise_detail(snapshot: PublicLeagueSnapshot, owner_id: str) -> dict[str, Any] | None:
    """Return a single franchise detail page, or ``None`` if unknown."""
    section = build_section(snapshot)
    detail = section.get("detail") or {}
    return detail.get(str(owner_id or "")) or None
