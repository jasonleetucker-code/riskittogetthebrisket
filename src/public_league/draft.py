"""Section: Draft Center.

Draft results by season, rookie-draft recap, current pick-ownership
map, weighted stockpile per manager, most-traded pick lineage.

Weighting (from prompt):
    1st round = 4, 2nd round = 3, 3rd round = 2, 4th+ = 1
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
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
    # A draft pick is made before the season's first week, so a roster that
    # changed hands mid-season made its picks under the OUTGOING owner.
    owner_id = (
        metrics.resolve_owner(snapshot.managers, season.league_id, rid, 0)
        if rid is not None
        else ""
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


@dataclass(frozen=True)
class PickInventory:
    """Current league pick ownership for the public draft surfaces.

    ``by_owner`` is ``None`` when ownership is UNKNOWN (the current league's
    ``/traded_picks`` was not observed) — never a seeded default inventory.
    Every current manager is a key, including managers who hold no picks.
    """

    state: str
    reason: str | None
    by_owner: dict[str, list[dict[str, Any]]] | None
    unattributed: list[dict[str, Any]]
    integrity: dict[str, Any] | None

    @property
    def available(self) -> bool:
        return self.by_owner is not None

    def state_fields(self) -> dict[str, Any]:
        from src.identity.picks import PICK_OWNERSHIP_REASON_FIELD, PICK_OWNERSHIP_STATE_FIELD

        return {PICK_OWNERSHIP_STATE_FIELD: self.state, PICK_OWNERSHIP_REASON_FIELD: self.reason}


def _registry_league_key(sleeper_league_id: str) -> str | None:
    try:
        from src.api.league_registry import league_key_for_sleeper_id

        return league_key_for_sleeper_id(sleeper_league_id)
    except Exception:  # noqa: BLE001 — an unreadable registry stamps no asset id
        return None


def _roster_ids(rosters: list[dict[str, Any]]) -> list[int]:
    out: list[int] = []
    for r in rosters or []:
        try:
            rid = int(r.get("roster_id"))
        except (TypeError, ValueError, AttributeError):
            continue
        if rid >= 1 and rid not in out:
            out.append(rid)
    return sorted(out)


def pick_inventory(snapshot: PublicLeagueSnapshot) -> PickInventory:
    """Current pick ownership, from the CANONICAL fold.

    Ownership is ``src.identity.picks.build_pick_ownership`` over the CURRENT
    league's rosters, draft rounds, canonical owned-pick seasons and its own
    ``/traded_picks`` — and nothing else.  Sleeper's ``traded_picks`` is an
    ownership STATE per league, not an event log: an older league in the
    chain describes who held a pick back then, so replaying it over the
    current state rewinds ownership (the 2026-10-17 P0: twelve picks shown on
    the manager who had since traded them away).  Older seasons' rows may
    still feed history features; they never redefine present ownership.

    Identity is ``leagueKey + season + round + origin roster``; the holder is
    state.  A pick whose holder roster has no resolvable manager is kept in
    ``unattributed`` (reported, never dropped).
    """
    from src.identity.picks import (
        PICK_OWNERSHIP_OBSERVED,
        PICK_OWNERSHIP_REASON_UNSTATED,
        PICK_OWNERSHIP_UNAVAILABLE,
        build_pick_ownership,
    )
    from src.identity.pick_lifecycle import league_draft_rounds

    current = snapshot.current_season
    if current is None:
        return PickInventory(
            state=PICK_OWNERSHIP_UNAVAILABLE,
            reason=PICK_OWNERSHIP_REASON_UNSTATED,
            by_owner=None,
            unattributed=[],
            integrity=None,
        )
    if current.traded_picks_state != PICK_OWNERSHIP_OBSERVED:
        return PickInventory(
            state=PICK_OWNERSHIP_UNAVAILABLE,
            reason=current.traded_picks_reason or PICK_OWNERSHIP_REASON_UNSTATED,
            by_owner=None,
            unattributed=[],
            integrity=None,
        )

    league_id = current.league_id
    league_key = _registry_league_key(league_id)
    roster_ids = _roster_ids(current.rosters)
    rounds = league_draft_rounds(current.league.get("settings") or {})
    seasons = [int(y) for y in _owned_pick_seasons(snapshot)]
    owned = build_pick_ownership(
        league_key or "unregistered-league",
        roster_ids,
        current.traded_picks,
        seasons=seasons,
        rounds=rounds,
    )

    def owner_of(rid: int) -> str:
        return metrics.resolve_owner(snapshot.managers, league_id, rid)

    by_owner: dict[str, list[dict[str, Any]]] = {}
    for rid in roster_ids:
        oid = owner_of(rid)
        if oid:
            by_owner.setdefault(oid, [])
    unattributed: list[dict[str, Any]] = []
    for entry in owned:
        ident = entry.identity
        origin = ident.origin_roster_id
        holder = entry.state.owner_roster_id
        original_owner_id = owner_of(origin)
        origin_name = (
            metrics.display_name_for(snapshot, original_owner_id) if original_owner_id else ""
        )
        is_traded = holder != origin
        season = str(ident.season)
        row = {
            "assetId": ident.canonical_id if league_key else None,
            "season": season,
            "round": ident.round_num,
            "originRosterId": origin,
            "originalOwnerId": original_owner_id,
            "originDisplayName": origin_name,
            "originLabel": (
                "Own"
                if not is_traded
                else (f"From {origin_name}" if origin_name else "From an unassigned roster")
            ),
            "isTraded": is_traded,
            "label": f"{season} R{ident.round_num}",
        }
        holder_owner = owner_of(holder) if holder is not None else ""
        if holder_owner:
            by_owner.setdefault(holder_owner, []).append(row)
        else:
            unattributed.append({**row, "holderRosterId": holder})
    for picks in by_owner.values():
        picks.sort(key=lambda p: (p["season"], p["round"], p["originRosterId"]))
    unattributed.sort(key=lambda p: (p["season"], p["round"], p["originRosterId"]))

    return PickInventory(
        state=PICK_OWNERSHIP_OBSERVED,
        reason=None,
        by_owner=by_owner,
        unattributed=unattributed,
        integrity=_inventory_integrity(
            by_owner,
            unattributed,
            roster_ids=roster_ids,
            seasons=seasons,
            rounds=rounds,
            traded_picks=current.traded_picks,
        ),
    )


def _inventory_integrity(
    by_owner: dict[str, list[dict[str, Any]]],
    unattributed: list[dict[str, Any]],
    *,
    roster_ids: list[int],
    seasons: list[int],
    rounds: int,
    traded_picks: list[dict[str, Any]],
) -> dict[str, Any]:
    """League-wide reconciliation, keyed on pick IDENTITY (never the label).

    Every season × round must hold exactly one pick per originating roster,
    each held by exactly one team.  ``ignoredTradedPickRows`` counts current
    ``/traded_picks`` rows inside the inventoried seasons/rounds that the
    canonical fold could not apply (an origin or holder that is not a current
    roster) — surfaced, so bad input is visible rather than absorbed.
    """
    rid_set = set(roster_ids)
    seen: dict[tuple[str, int, int], int] = defaultdict(int)
    for picks in list(by_owner.values()) + [unattributed]:
        for p in picks:
            seen[(p["season"], p["round"], p["originRosterId"])] += 1
    expected = {
        (str(y), r, rid) for y in seasons for r in range(1, rounds + 1) for rid in roster_ids
    }
    duplicates = sorted(k for k, n in seen.items() if n > 1)
    missing = sorted(expected - set(seen))
    extra = sorted(set(seen) - expected)
    mismatched = []
    for y in seasons:
        for r in range(1, rounds + 1):
            n = sum(c for (s, rr, _o), c in seen.items() if s == str(y) and rr == r)
            if n != len(roster_ids):
                mismatched.append({"season": str(y), "round": r, "count": n})
    season_set = {int(y) for y in seasons}
    ignored = 0
    for tp in traded_picks or []:
        try:
            yr, rnd = int(tp.get("season")), int(tp.get("round"))
            origin, owner = int(tp.get("roster_id")), int(tp.get("owner_id"))
        except (TypeError, ValueError, AttributeError):
            ignored += 1
            continue
        if (
            yr in season_set
            and 1 <= rnd <= rounds
            and (origin not in rid_set or owner not in rid_set)
        ):
            ignored += 1

    def fmt(keys):
        return [{"season": s, "round": r, "originRosterId": o} for s, r, o in keys]

    return {
        "ok": not (duplicates or missing or extra or mismatched or unattributed),
        "seasons": [str(y) for y in seasons],
        "rounds": rounds,
        "rosterCount": len(roster_ids),
        "expectedPerSeasonRound": len(roster_ids),
        "expectedAssetCount": len(expected),
        "assetCount": sum(seen.values()),
        "duplicateAssets": fmt(duplicates),
        "missingAssets": fmt(missing),
        "unexpectedAssets": fmt(extra),
        "mismatchedSeasonRounds": mismatched,
        "unattributedCount": len(unattributed),
        "ignoredTradedPickRows": ignored,
    }


def _pick_ownership_map(snapshot: PublicLeagueSnapshot) -> dict[str, list[dict[str, Any]]] | None:
    """Current picks per owner id, or ``None`` when ownership is unknown.

    Kept for existing consumers (awards, superlatives); it is now only a view
    of :func:`pick_inventory` — the canonical fold — never a second engine.
    """
    return pick_inventory(snapshot).by_owner


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


def weighted_stockpile_for_owner(
    snapshot: PublicLeagueSnapshot,
    owner_id: str,
    *,
    inventory: PickInventory | None = None,
) -> dict[str, Any]:
    """Public-safe weighted draft capital summary for one owner.

    Pass ``inventory`` when summarizing many owners from one snapshot so the
    canonical fold runs once.  When ownership is unknown every count is
    ``None`` (never ``0``) and the state fields say why.
    """
    inv = inventory if inventory is not None else pick_inventory(snapshot)
    if not inv.available:
        return {
            "totalPicks": None,
            "weightedScore": None,
            "byRound": None,
            "picks": None,
            **inv.state_fields(),
        }
    picks = inv.by_owner.get(owner_id, [])
    by_round: dict[int, int] = defaultdict(int)
    for p in picks:
        by_round[p["round"]] += 1
    return {
        "totalPicks": len(picks),
        "weightedScore": sum(pick_weight(p["round"]) for p in picks),
        "byRound": {str(r): n for r, n in sorted(by_round.items())},
        "picks": picks,
        **inv.state_fields(),
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
    rows.sort(key=lambda r: (-r["weightedScore"], -r["totalPicks"], r["displayName"], r["ownerId"]))
    return rows


def _trade_pick_legs(snapshot: PublicLeagueSnapshot) -> list[dict[str, Any]]:
    """Every draft pick moved by a COMPLETED trade, one row per (trade, pick).

    The evidence is the trade transactions themselves, de-duplicated by
    ``transaction_id`` across the whole league chain — never ``traded_picks``
    rows, which restate ownership once per league-season and so would count
    one move several times.  Origin roster ids are stable across Sleeper's
    ``previous_league_id`` chain, so ``(season, round, origin)`` names the
    same pick in every league of the chain.
    """
    seen: set[str] = set()
    legs: list[dict[str, Any]] = []
    for season in snapshot.seasons:
        for tx in season.trades():
            tx_id = str(tx.get("transaction_id") or "")
            if not tx_id or tx_id in seen:
                continue
            seen.add(tx_id)
            week = tx.get("_leg")
            for dp in tx.get("draft_picks") or []:
                if not isinstance(dp, dict):
                    continue
                try:
                    yr = int(dp.get("season"))
                    rnd = int(dp.get("round"))
                    origin = int(dp.get("roster_id"))
                except (TypeError, ValueError):
                    continue
                legs.append(
                    {
                        "season": str(yr),
                        "round": rnd,
                        "originRosterId": origin,
                        "fromRosterId": dp.get("previous_owner_id"),
                        "toRosterId": dp.get("owner_id"),
                        "leagueId": season.league_id,
                        "sourceSeason": season.season,
                        "week": week,
                        "created": int(tx.get("created") or tx.get("status_updated") or 0),
                    }
                )
    legs.sort(key=lambda leg: (leg["created"], leg["season"], leg["round"], leg["originRosterId"]))
    return legs


def _most_traded_pick(snapshot: PublicLeagueSnapshot) -> dict[str, Any] | None:
    """The pick moved by the most distinct completed trades, or ``None``.

    ``moveCount`` counts unique trade transactions (see
    :func:`_trade_pick_legs`); ``coverage`` is the history walk's state, so a
    truncated chain reads as a lower bound rather than a complete count.
    """
    moves: dict[tuple[str, int, int], int] = defaultdict(int)
    for leg in _trade_pick_legs(snapshot):
        moves[(leg["season"], leg["round"], leg["originRosterId"])] += 1
    if not moves:
        return None
    (yr, rnd, origin_rid), count = min(
        moves.items(), key=lambda kv: (-kv[1], kv[0][0], kv[0][1], kv[0][2])
    )
    current = snapshot.current_season
    league_id = current.league_id if current else ""
    original_owner_id = metrics.resolve_owner(snapshot.managers, league_id, origin_rid)
    return {
        "season": yr,
        "round": rnd,
        "originRosterId": origin_rid,
        "originalOwnerId": original_owner_id,
        "originDisplayName": (
            metrics.display_name_for(snapshot, original_owner_id) if original_owner_id else ""
        ),
        "label": f"{yr} R{rnd}",
        "moveCount": count,
        "evidence": "completed_trades",
        "coverage": (snapshot.history_coverage or {}).get("state"),
    }


def _pick_movement_trail(snapshot: PublicLeagueSnapshot) -> list[dict[str, Any]]:
    """Every completed trade leg that moved a pick, oldest first.

    Owners resolve in the league and week the trade happened, so a roster
    hand-off credits the manager who actually made the trade.
    """
    current = snapshot.current_season
    current_league_id = current.league_id if current else ""
    out: list[dict[str, Any]] = []
    for leg in _trade_pick_legs(snapshot):
        lid, week = leg["leagueId"], leg["week"]
        out.append(
            {
                "season": leg["season"],
                "round": leg["round"],
                "label": f"{leg['season']} R{leg['round']}",
                "originRosterId": leg["originRosterId"],
                "originalOwnerId": metrics.resolve_owner(
                    snapshot.managers, current_league_id, leg["originRosterId"]
                ),
                "fromOwnerId": metrics.resolve_owner(
                    snapshot.managers, lid, leg["fromRosterId"], week
                ),
                "toOwnerId": metrics.resolve_owner(snapshot.managers, lid, leg["toRosterId"], week),
                "sourceSeason": leg["sourceSeason"],
                "week": week,
            }
        )
    return out


def build_section(snapshot: PublicLeagueSnapshot) -> dict[str, Any]:
    drafts: list[dict[str, Any]] = []
    for season in snapshot.seasons:
        for draft in season.drafts:
            drafts.append(_draft_summary(snapshot, season, draft))
    drafts.sort(key=lambda d: (d["season"], d.get("startTime") or 0), reverse=True)

    inventory = pick_inventory(snapshot)
    if inventory.available:
        leaderboard = _stockpile_leaderboard(snapshot, inventory.by_owner)
        most_picks = leaderboard[0] if leaderboard else None
        fewest_picks = leaderboard[-1] if leaderboard else None
    else:
        # Unknown ownership publishes no inventory and no ranking — not an
        # empty board that reads as "nobody owns anything".
        leaderboard = most_picks = fewest_picks = None

    return {
        "drafts": drafts,
        **inventory.state_fields(),
        "pickOwnership": inventory.by_owner,
        "unattributedPicks": inventory.unattributed,
        "pickInventoryIntegrity": inventory.integrity,
        "stockpileLeaderboard": leaderboard,
        "mostPicksOwned": most_picks,
        "fewestPicksOwned": fewest_picks,
        "mostTradedPick": _most_traded_pick(snapshot),
        "pickMovementTrail": _pick_movement_trail(snapshot),
        "seasonsCovered": [s.season for s in snapshot.seasons],
    }
