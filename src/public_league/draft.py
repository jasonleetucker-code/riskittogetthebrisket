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


def _normalize_pick(
    snapshot: PublicLeagueSnapshot, season: SeasonSnapshot, pick: dict[str, Any]
) -> dict[str, Any]:
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
    # What an auction pick actually SOLD for.  Sleeper puts it on the pick's
    # metadata for auction drafts and omits it for snake drafts, so ``None``
    # means "not an auction" rather than "free" — the two must not read alike.
    #
    # This is the only place in the codebase where realized rookie prices from
    # a COMPLETED auction can enter, and it was discarding them.  The raw picks
    # are already fetched for every season the snapshot covers
    # (``src/public_league/snapshot.py``), so carrying one field through turns
    # an existing fetch into the realized-price corpus that
    # ``PRICE_DISPERSION_PRIOR`` and any Perfect Draft backtest need.  See
    # ``docs/perfect-draft.md`` §10 for what is still missing after this.
    raw_amount = metadata.get("amount")
    try:
        amount = int(raw_amount) if raw_amount not in (None, "") else None
    except (TypeError, ValueError):
        amount = None

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
        "amount": amount,
    }


def _draft_summary(
    snapshot: PublicLeagueSnapshot, season: SeasonSnapshot, draft: dict[str, Any]
) -> dict[str, Any]:
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
        "rounds": int((draft.get("settings") or {}).get("rounds") or 0)
        if isinstance(draft.get("settings"), dict)
        else 0,
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

    from src.identity.pick_lifecycle import league_draft_rounds

    draft_rounds = league_draft_rounds(current.league.get("settings") or {})

    future_years = _owned_pick_seasons(snapshot)
    original_by_rid: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for r in current.rosters:
        try:
            rid = int(r.get("roster_id"))
        except (TypeError, ValueError):
            continue
        for yr in future_years:
            for rnd in range(1, draft_rounds + 1):
                original_by_rid[rid].append(
                    {
                        "season": yr,
                        "round": rnd,
                        "fromRosterId": rid,
                        "ownerRosterId": rid,
                    }
                )

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
            by_owner[owner_id].append(
                {
                    "season": pick["season"],
                    "round": pick["round"],
                    "originalOwnerId": original_owner_id,
                    "isTraded": owner_id != original_owner_id,
                    "label": f"{pick['season']} R{pick['round']}",
                }
            )
    for owner_id, lst in by_owner.items():
        lst.sort(key=lambda p: (p["season"], p["round"]))
    return dict(by_owner)


def _owned_pick_seasons(snapshot: PublicLeagueSnapshot) -> list[str]:
    """The seasons this league's picks are inventoried for — the league-scoped
    canonical answer (``pick_lifecycle.league_draft_years``, Wave A).

    This used to be ``league season + 1, + 2``: it dropped the current class
    even before its draft had happened and the third future class always, so
    the public stockpile disagreed with every other surface's inventory.  The
    evidence comes from the snapshot itself (drafts, their picks, current
    rosters) — no file read and no fetch.
    """
    current = snapshot.current_season
    if current is None:
        return []
    from src.api.draft_class_evidence import league_draft_years_for
    from src.identity.pick_lifecycle import evidence_from_sleeper

    drafts: list[dict[str, Any]] = []
    picks_by_draft: dict[str, Any] = {}
    for season in snapshot.seasons:
        for d in season.drafts or []:
            if isinstance(d, dict):
                drafts.append(d)
        for did, plist in (season.draft_picks_by_draft or {}).items():
            picks_by_draft[str(did)] = plist
    rostered = [
        str(pid)
        for r in current.rosters or []
        if isinstance(r, dict)
        for pid in (r.get("players") or [])
        if pid
    ]
    evidence = evidence_from_sleeper(
        league_key=None,
        sleeper_league_id=current.league_id,
        drafts=drafts,
        picks_by_draft_id=picks_by_draft,
        rostered_player_ids=rostered if current.rosters else None,
        observed_at=None,
    )
    years = league_draft_years_for(
        current.league_id, league_season=current.season, evidence=evidence
    )
    return [str(y) for y in years.owned_pick_seasons]


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


def _stockpile_leaderboard(
    snapshot: PublicLeagueSnapshot, ownership: dict[str, list[dict[str, Any]]]
) -> list[dict[str, Any]]:
    rows = []
    for owner_id, picks in ownership.items():
        rows.append(
            {
                "ownerId": owner_id,
                "displayName": metrics.display_name_for(snapshot, owner_id),
                "totalPicks": len(picks),
                "weightedScore": sum(pick_weight(p["round"]) for p in picks),
            }
        )
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
            current_owner_id = metrics.resolve_owner(
                snapshot.managers, league_id, current_owner_rid
            )
            out.append(
                {
                    "season": yr,
                    "round": rnd,
                    "label": f"{yr} R{rnd}",
                    "originalOwnerId": original_owner_id,
                    "currentOwnerId": current_owner_id,
                    "sourceSeason": season.season,
                }
            )
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
