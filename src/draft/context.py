"""Per-team roster context for the Perfect Draft optimizer.

Everything in here is **static for the duration of a draft**: rosters, board
values, waiver levels and the cut ladder do not change when a rookie is sold.
That is precisely why the split exists.  The fast-moving state — budgets,
recorded picks, live prices — lives in the browser's ``localStorage`` and never
reaches the server, so the optimizer itself runs on the client against this
payload (see ``frontend/lib/perfect-draft.js``).  Shipping the whole draft
workspace to the server on every recorded pick, mid-auction, to recompute a
knapsack that takes single-digit milliseconds would be the wrong trade.

What the client cannot compute for itself, and this module supplies:

* each team's roster joined to canonical ``rankDerivedValue`` (the contract is
  ~4 MB — sending it to the browser is exactly what the repo's performance
  rules forbid),
* the waiver level at each position, which needs the league-wide rostered set,
* the Effective Cut Cost ladder, which needs the lineup solver and the league's
  scarcity signals.

The client recomputes no values.  It consumes these stamps exactly as
``draft-logic.js`` already consumes ``rookieKtcValue``, so the repo's "no
frontend ranking engine" rule holds.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from src.draft.displacement import (
    RosterAsset,
    build_cut_ladder,
    count_free_agents,
    free_agent_ladder,
    waiver_values_by_position,
)
from src.draft.rookie_pool import auction_rookie_keys

__all__ = [
    "CONTEXT_VERSION",
    "build_roster_context",
    "list_draft_teams",
]

#: Bumped when the payload shape changes in a way the client must notice.
#:
#: v2 (2026-08-04) adds ``waiverLadder`` — the declining free-agent ladder
#: behind W(k) — and excludes rookies in the live auction from every
#: free-agent measurement, which moves ``waiverValues`` too.
#: v3 (2026-08-04) adds ``rosterByPosition`` / ``startersByPosition`` so the
#: client can say whether a plan leaves a starting slot unfilled.
CONTEXT_VERSION = "2026-08-04.v3"


def _norm(s: Any) -> str:
    return str(s or "").strip().lower()


def _sleeper_block(contract: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if not isinstance(contract, Mapping):
        return {}
    block = contract.get("sleeper")
    return block if isinstance(block, Mapping) else {}


def _teams(contract: Mapping[str, Any] | None) -> list[Mapping[str, Any]]:
    teams = _sleeper_block(contract).get("teams")
    if not isinstance(teams, list):
        return []
    return [t for t in teams if isinstance(t, Mapping)]


def _index_contract_rows(
    contract: Mapping[str, Any] | None,
) -> tuple[dict[str, Mapping[str, Any]], dict[str, Mapping[str, Any]]]:
    """``(by_player_id, by_name)`` over ``playersArray``.

    Name keys cover all three fields the contract carries, mirroring
    ``src/trade/finder.py::board_values_from_contract``.  First write wins, so a
    later duplicate cannot displace an earlier canonical row.
    """
    by_id: dict[str, Mapping[str, Any]] = {}
    by_name: dict[str, Mapping[str, Any]] = {}
    rows = (contract or {}).get("playersArray") if isinstance(contract, Mapping) else None
    if not isinstance(rows, list):
        return by_id, by_name
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        pid = _norm(row.get("playerId"))
        if pid:
            by_id.setdefault(pid, row)
        for field_name in ("legacyRef", "canonicalName", "displayName"):
            key = _norm(row.get(field_name))
            if key:
                by_name.setdefault(key, row)
    return by_id, by_name


def _roster_size_for(league_key: str | None) -> int | None:
    try:
        from src.api.league_registry import (  # noqa: PLC0415
            get_default_league,
            get_league_by_key,
        )

        cfg = get_league_by_key(league_key) if league_key else get_default_league()
        if cfg is None or not cfg.roster_settings:
            return None
        raw = cfg.roster_settings.get("rosterSize")
        return int(raw) if raw is not None else None
    except Exception:  # noqa: BLE001 — registry problems must not break the endpoint
        return None


def _taxi_size_for(league_key: str | None) -> int:
    try:
        from src.api.league_registry import (  # noqa: PLC0415
            get_default_league,
            get_league_by_key,
        )

        cfg = get_league_by_key(league_key) if league_key else get_default_league()
        if cfg is None or not cfg.roster_settings:
            return 0
        return int(cfg.roster_settings.get("taxiSize") or 0)
    except Exception:  # noqa: BLE001
        return 0


def _league_scarcity(
    league_key: str | None,
    contract: Mapping[str, Any] | None,
) -> tuple[Mapping[str, Any] | None, str | None]:
    """League scarcity signals, or ``(None, reason)``.

    Routes through ``src.api.gameplan.get_league_bundle`` so the ~1.35 s solve
    is shared with every other consumer rather than duplicated behind a second
    cache.  Degrades rather than raises: the multiplier goes inert (1.0) and the
    reason is surfaced, because a missing ROS snapshot must not take down a
    working draft board.
    """
    if not league_key:
        return None, "no league key — positional scarcity inert"
    try:
        from src.api.gameplan import get_league_bundle  # noqa: PLC0415
        from src.api.league_registry import get_scoring_profile  # noqa: PLC0415

        profile = get_scoring_profile(league_key) or ""
        bundle, _hit = get_league_bundle(league_key, profile, contract)
        return bundle.scarcity, None
    except Exception as exc:  # noqa: BLE001 — optional signal
        return None, f"positional scarcity unavailable ({type(exc).__name__}) — multiplier inert"


def list_draft_teams(contract: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """Teams the draft board can optimize for.

    No raw Sleeper league id is exposed; ``ownerId``/``rosterId`` are the
    league-internal handles the draft workspace already joins on.
    """
    out: list[dict[str, Any]] = []
    for team in _teams(contract):
        players = team.get("players")
        out.append(
            {
                "name": str(team.get("name") or ""),
                "ownerId": str(team.get("ownerId") or ""),
                "rosterId": team.get("roster_id"),
                "rosterCount": len(players) if isinstance(players, list) else 0,
            }
        )
    out.sort(key=lambda t: t["name"].lower())
    return out


def _match_team(
    teams: Sequence[Mapping[str, Any]],
    *,
    owner_id: str | None,
    roster_id: Any,
    team_name: str | None,
) -> Mapping[str, Any] | None:
    """Resolve a team by ownerId, then rosterId, then display name.

    Owner id first because it is the only handle stable across a team rename —
    the draft workspace joins on lowercased display name, which drifts.
    """
    if owner_id:
        for t in teams:
            if _norm(t.get("ownerId")) == _norm(owner_id):
                return t
    if roster_id not in (None, ""):
        for t in teams:
            if str(t.get("roster_id")) == str(roster_id):
                return t
    if team_name:
        for t in teams:
            if _norm(t.get("name")) == _norm(team_name):
                return t
    return None


def build_roster_assets(
    team: Mapping[str, Any],
    by_name: Mapping[str, Mapping[str, Any]],
    by_id: Mapping[str, Mapping[str, Any]],
) -> tuple[list[RosterAsset], list[str]]:
    """Join one team's roster to the board.

    Returns ``(assets, unmatched_names)``.  Extracted from
    :func:`build_roster_context` so analysis tooling can get at the roster
    itself — the context payload carries only per-position *counts*, and
    anything asking "what would this lineup actually be?" needs the players.
    Duplicating the join in a script would be a second definition of who is on
    a roster, which is exactly the kind of parallel system this repo avoids.
    """
    names = [str(n) for n in (team.get("players") or []) if str(n or "").strip()]
    ids = [str(i) for i in (team.get("playerIds") or []) if str(i or "").strip()]
    assets: list[RosterAsset] = []
    unmatched: list[str] = []
    for idx, name in enumerate(names):
        row = by_name.get(_norm(name))
        if row is None and idx < len(ids):
            row = by_id.get(_norm(ids[idx]))
        if row is None:
            unmatched.append(name)
            # Still occupies a roster spot, and is a legitimate cut candidate —
            # dropping him from the model would understate roster pressure.
            assets.append(
                RosterAsset(
                    player_id=ids[idx] if idx < len(ids) else name,
                    name=name,
                    position="",
                    board_value=None,
                )
            )
            continue
        value = row.get("rankDerivedValue")
        fantasy = row.get("fantasyPositions")
        assets.append(
            RosterAsset(
                player_id=str(row.get("playerId") or name),
                name=str(row.get("displayName") or row.get("canonicalName") or name),
                position=str(row.get("position") or "").strip().upper(),
                board_value=float(value) if isinstance(value, (int, float)) and value > 0 else None,
                ros_value=float(row.get("rosValue") or 0.0),
                fantasy_positions=tuple(fantasy) if isinstance(fantasy, (list, tuple)) else (),
                injured=bool(row.get("injured")),
            )
        )
    return assets, unmatched


def build_roster_context(
    contract: Mapping[str, Any] | None,
    league_key: str | None,
    *,
    owner_id: str | None = None,
    roster_id: Any = None,
    team_name: str | None = None,
) -> dict[str, Any]:
    """Assemble one team's Perfect Draft roster context.

    Raises :class:`ValueError` when the team cannot be resolved — the caller
    turns that into a clean 400 rather than silently optimizing for whichever
    team happened to sort first, which would be the worst possible failure mode
    for a tool whose entire output is team-specific.
    """
    teams = _teams(contract)
    if not teams:
        raise ValueError("no_rosters_loaded")

    team = _match_team(teams, owner_id=owner_id, roster_id=roster_id, team_name=team_name)
    if team is None:
        raise ValueError("unknown_team")

    by_id, by_name = _index_contract_rows(contract)
    notes: list[str] = []

    # League-wide rostered set — a player on ANY roster is not a waiver option.
    rostered_keys: set[str] = set()
    for t in teams:
        for pid in t.get("playerIds") or []:
            if _norm(pid):
                rostered_keys.add(_norm(pid))
        for nm in t.get("players") or []:
            if _norm(nm):
                rostered_keys.add(_norm(nm))

    # Rookies in this auction are NOT free alternatives to buying rookies in
    # this auction.  Without this exclusion the board's best "free agent" tight
    # end was lot number one (see src/draft/rookie_pool.py), which suppressed
    # every rookie TE's surplus by comparing him against himself.
    auction_keys = auction_rookie_keys(contract)
    # The size of the defect this exclusion fixes, measured rather than
    # asserted: the difference between the free-agent universe with the auction
    # in it and without.  Counted this way and not by "auction rookies nobody
    # rosters", which overstates it — a rookie with no position never reached
    # the free-agent pool to begin with.
    free_agents_total = count_free_agents(contract, rostered_keys, auction_keys)
    auction_rookies_excluded = count_free_agents(contract, rostered_keys) - free_agents_total
    waiver_values = waiver_values_by_position(contract, rostered_keys, auction_keys)
    if not waiver_values:
        notes.append("no waiver-level values available — cut costs fall back to raw board value")

    # The declining ladder behind W(k): taking k roster spots forgoes the top-k
    # free agents, not the single best one k times over.  The cap is generous
    # relative to any plan the optimizer will produce (open spots plus at most
    # MAX_LADDER_RUNGS cuts) so the client never runs off the end of it.
    waiver_ladder = free_agent_ladder(contract, rostered_keys, auction_keys, limit=90)
    if not waiver_ladder:
        notes.append(
            "no free agents available — replacement level is unmeasurable and "
            "rookie surplus is therefore the raw board value"
        )

    assets, unmatched = build_roster_assets(team, by_name, by_id)

    if unmatched:
        notes.append(
            f"{len(unmatched)} rostered player(s) did not join to the board and are "
            "treated as unpriced — verify before releasing"
        )

    from src.ros.lineup import load_league_starter_slots  # noqa: PLC0415

    starter_slots = load_league_starter_slots(league_key)
    scarcity, scarcity_note = _league_scarcity(league_key, contract)
    if scarcity_note:
        notes.append(scarcity_note)

    ladder = build_cut_ladder(assets, starter_slots, waiver_values, scarcity)
    notes.extend(ladder.notes)

    roster_size = _roster_size_for(league_key)
    roster_count = len(assets)
    open_spots = max(0, roster_size - roster_count) if roster_size else 0
    taxi_size = _taxi_size_for(league_key)
    if taxi_size:
        notes.append(
            f"league carries {taxi_size} taxi slot(s), but Sleeper's per-player taxi "
            "assignment is not ingested anywhere in this codebase — taxi relief is "
            "NOT modelled and open spots may be understated"
        )

    assumed_waiver = sum(1 for r in ladder.rungs if r.value_basis == "assumedWaiver")

    # Positional shape, so the client can say whether a plan leaves a hole.
    # Counted from the joined assets rather than from the cut ladder: the
    # ladder truncates at MAX_LADDER_RUNGS and excludes the undroppable, so its
    # positions are a sample of the roster, not the roster.
    roster_by_position: dict[str, int] = {}
    for asset in assets:
        pos = (asset.position or "").strip().upper()
        if pos:
            roster_by_position[pos] = roster_by_position.get(pos, 0) + 1
    starters_by_position: dict[str, int] = {}
    for slot in starter_slots:
        key = str(slot or "").strip().upper()
        if key:
            starters_by_position[key] = starters_by_position.get(key, 0) + 1

    return {
        "contextVersion": CONTEXT_VERSION,
        "leagueKey": league_key,
        "valueScale": "rankDerivedValue",
        "team": {
            "name": str(team.get("name") or ""),
            "ownerId": str(team.get("ownerId") or ""),
            "rosterId": team.get("roster_id"),
        },
        "rosterSize": roster_size,
        "rosterCount": roster_count,
        "openRosterSpots": open_spots,
        "taxiSize": taxi_size,
        "taxiSlotsAvailable": 0,
        "waiverValues": {k: round(v, 1) for k, v in sorted(waiver_values.items())},
        # Descending free-agent values — the W(k) ladder.  ``waiverValues``
        # above stays for the cut side (a released player IS replaced at his
        # own position) and for display; this is the addition side, where the
        # spots are fungible and the same free agent cannot fill two of them.
        "waiverLadder": [round(v, 1) for v in waiver_ladder],
        # Positional shape.  ``rosterByPosition`` is this team's joined roster;
        # ``startersByPosition`` is the league's own lineup requirement from the
        # registry (FLEX / SUPER_FLEX / IDP_FLEX appear as their own keys — they
        # are slots, not positions, and the client must not treat them as one).
        "rosterByPosition": dict(sorted(roster_by_position.items())),
        "startersByPosition": dict(sorted(starters_by_position.items())),
        "cutLadder": ladder.to_dict(),
        "counts": {
            "rosterPlayers": roster_count,
            "unmatchedRosterPlayers": len(unmatched),
            "cutRungs": len(ladder.rungs),
            "undroppable": len(ladder.undroppable),
            "assumedWaiverRungs": assumed_waiver,
            "freeAgents": free_agents_total,
            "auctionRookiesExcludedFromWaivers": auction_rookies_excluded,
        },
        "unmatchedRosterPlayers": unmatched[:25],
        "notes": notes,
    }
