"""The routed trade LEDGER — the one owner of "which assets move where, and who
really holds them" for a team-attributed trade of any size (N-team engine, spec
``docs/trade/NTEAM_TRADE_ENGINE_SPEC.md`` §2.2-§2.4).

A ledger is a set of directed legs ``{assetId, from, to}`` between a set of
participating teams, validated against ONE captured contract (the snapshot).
This module:

* builds and memoises that snapshot (:func:`build_trade_snapshot`,
  :func:`snapshot_for`) — board rows by Sleeper id, the league's rosters, pick
  ownership, roster settings and roster freshness, all from one contract;
* parses asset refs (``p:<sleeperId>`` / the canonical league pick id of
  ``src/identity/picks.py``) — labels never identify an asset;
* validates a proposed ledger in the spec's fixed order (§2.3), raising
  :class:`LedgerError` with a stable reason code, and verifies every leg's
  origin against the snapshot's rosters — the verified owner cannot be
  overridden by anything in a request;
* projects one team's flows out of a validated ledger (:func:`team_flows`).

It computes no value, applies no package model and decides nothing: valuation
stays in ``trade_simulator`` / the pipeline, decisions in ``trade_decision``,
roster freshness in ``src/api/roster_freshness.py`` (the ONE reader of the
scraper's roster stamp — this module calls it and keeps no copy).  The N-team
composer is ``src/trade/analyze_service.analyze_trade_n``; both the private
``/api/trade/analyze-multi`` route and the public advisor obtain their snapshot
here, so the two read the same bytes.

Pure apart from the small snapshot memo.  Writes nothing.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping, Sequence

from src.identity.picks import (
    PICK_OWNER_ABSENT,
    PICK_OWNER_OWNED,
    PICK_OWNER_UNKNOWN,
    format_pick_label_overlay,
    league_pick_owner_index,
    lookup_league_pick_owner,
    parse_league_pick_id,
)

_LOG = logging.getLogger(__name__)

PLAYER_PREFIX = "p:"
LEDGER_VERSION = "trade_ledger_v1"

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "trade" / "multi_team.json"
#: Error echoes carry only request-supplied identifiers of this shape.  Anchored
#: with ``\Z``, not ``$``: in Python ``$`` also matches just BEFORE a trailing
#: newline, so an id ending in a newline would be echoed
#: (LANE-E-DEFECT-ECHO-NEWLINE).
_ECHO_RE = re.compile(r"^[A-Za-z0-9:_-]{1,64}\Z")

Participation = Literal["any_leg", "send_and_receive"]
RosterState = Literal["current", "stale", "unknown"]


# ── Policy ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class LedgerPolicy:
    """Structural bounds for one product.  ``max_teams`` is further capped at
    the snapshot league's team count."""

    min_teams: int = 2
    max_teams: int = 4
    max_legs: int = 128
    participation: Participation = "any_leg"


def _load_config() -> dict[str, Any]:
    raw = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("multi_team.json is not an object")
    for key in ("maxTeams", "maxLegs"):
        v = raw.get(key)
        if not isinstance(v, int) or isinstance(v, bool) or v < 2:
            raise ValueError(f"multi_team.json: {key} must be an int >= 2")
    if raw.get("participation") not in ("any_leg", "send_and_receive"):
        raise ValueError("multi_team.json: participation must be any_leg or send_and_receive")
    return raw


def private_policy() -> LedgerPolicy:
    """The private calculator's policy from ``config/trade/multi_team.json``.

    An unreadable or malformed file FAILS CLOSED to ``maxTeams`` 2 (the
    multi-team route then refuses N >= 3) and logs an error — never a silent
    larger default.
    """
    try:
        cfg = _load_config()
    except (OSError, ValueError) as exc:
        _LOG.error("multi_team.json unreadable (%s); private N-team capped at 2 teams", exc)
        return LedgerPolicy(max_teams=2)
    return LedgerPolicy(
        max_teams=int(cfg["maxTeams"]),
        max_legs=int(cfg["maxLegs"]),
        participation=cfg["participation"],
    )


def config_version() -> str | None:
    try:
        return str(_load_config().get("version") or "") or None
    except (OSError, ValueError):
        return None


# ── Snapshot ───────────────────────────────────────────────────────────────


@dataclass(frozen=True, eq=False)
class TradeSnapshot:
    contract: Mapping[str, Any]
    league_key: str
    generation: str
    teams_by_roster_id: Mapping[int, Mapping[str, Any]]
    team_count: int
    player_owners: Mapping[str, tuple[int, ...]]
    known_player_ids: frozenset[str]
    pick_owner_index: Any
    pick_details_by_id: Mapping[str, Mapping[str, Any]]
    rows_by_player_id: Mapping[str, Mapping[str, Any] | None]
    roster_settings: Mapping[str, Any]
    rosters_state: RosterState
    rosters_as_of: str | None
    id_to_player: Mapping[str, str]


def _roster_id(team: Any) -> int | None:
    if not isinstance(team, Mapping):
        return None
    for key in ("roster_id", "rosterId"):
        try:
            rid = int(team.get(key))
        except (TypeError, ValueError):
            continue
        if rid >= 1:
            return rid
    return None


def _generation(contract: Mapping[str, Any]) -> str:
    """The ONE generation reader (``trade_analyze_runtime.contract_generation``);
    ``"unknown"`` when the board carries no stamp."""
    from src.api.trade_analyze_runtime import contract_generation  # noqa: PLC0415

    return contract_generation(contract) or "unknown"


def _registry_roster_settings(league_key: str) -> dict[str, Any]:
    try:
        from src.api.league_registry import get_league_by_key  # noqa: PLC0415

        cfg = get_league_by_key(league_key)
    except Exception:  # noqa: BLE001 — an unresolvable league has no settings
        return {}
    settings = getattr(cfg, "roster_settings", None) if cfg is not None else None
    return dict(settings) if isinstance(settings, Mapping) else {}


def build_trade_snapshot(
    contract: Mapping[str, Any],
    *,
    league_key: str,
    roster_settings: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> TradeSnapshot:
    """Index ONE captured contract for a whole request.

    ``roster_settings`` is resolved through the league registry, once, unless
    the caller passes the league's settings it already holds.  Roster
    freshness comes from ``src/api/roster_freshness.roster_freshness``.
    Raises ``LookupError`` when the contract carries no usable league rosters.
    """
    from src.api.roster_freshness import roster_freshness  # noqa: PLC0415
    from src.api.terminal import _players_array  # noqa: PLC0415
    from src.api.trade_simulator import rows_by_player_id  # noqa: PLC0415

    sleeper = contract.get("sleeper") if isinstance(contract, Mapping) else None
    teams = sleeper.get("teams") if isinstance(sleeper, Mapping) else None
    if not isinstance(teams, list) or not teams:
        raise LookupError("contract carries no league rosters")
    teams_by_rid: dict[int, Mapping[str, Any]] = {}
    for t in teams:
        rid = _roster_id(t)
        if rid is not None and rid not in teams_by_rid:
            teams_by_rid[rid] = t
    if len(teams_by_rid) < 2:
        raise LookupError("contract carries fewer than two rosters")

    player_owners: dict[str, list[int]] = {}
    pick_details: dict[str, Mapping[str, Any]] = {}
    for rid in sorted(teams_by_rid):
        t = teams_by_rid[rid]
        for pid in t.get("playerIds") or []:
            sid = str(pid or "").strip()
            if sid:
                player_owners.setdefault(sid, []).append(rid)
        details = t.get("pickDetails")
        if isinstance(details, list):
            for d in details:
                if isinstance(d, Mapping):
                    aid = str(d.get("assetId") or "").strip()
                    if aid and aid not in pick_details:
                        pick_details[aid] = d
    id_to_player = sleeper.get("idToPlayer") if isinstance(sleeper, Mapping) else None
    id_to_player = (
        {str(k): str(v) for k, v in id_to_player.items()}
        if isinstance(id_to_player, Mapping)
        else {}
    )
    rows = _players_array(dict(contract))
    fresh = roster_freshness(dict(contract), now=now)
    state = fresh.get("state")
    return TradeSnapshot(
        contract=contract,
        league_key=str(league_key),
        generation=_generation(contract),
        teams_by_roster_id=teams_by_rid,
        team_count=len(teams_by_rid),
        player_owners={k: tuple(v) for k, v in player_owners.items()},
        known_player_ids=frozenset(player_owners) | frozenset(id_to_player),
        pick_owner_index=league_pick_owner_index([teams_by_rid[r] for r in sorted(teams_by_rid)]),
        pick_details_by_id=pick_details,
        rows_by_player_id=rows_by_player_id(rows),
        roster_settings=(
            dict(roster_settings)
            if isinstance(roster_settings, Mapping)
            else _registry_roster_settings(str(league_key))
        ),
        rosters_state=state if state in ("current", "stale", "unknown") else "unknown",
        rosters_as_of=fresh.get("asOf"),
        id_to_player=id_to_player,
    )


_MEMO: "OrderedDict[tuple[Any, ...], TradeSnapshot]" = OrderedDict()
_MEMO_LOCK = threading.Lock()
_MEMO_SIZE = 2


def snapshot_for(
    contract: Mapping[str, Any],
    *,
    league_key: str,
    roster_settings: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> TradeSnapshot:
    """:func:`build_trade_snapshot`, memoised (LRU 2) on the contract object,
    its generation, the league, and the roster-freshness STATE right now — so
    a snapshot built while rosters were current is never reused once they have
    gone stale.  The memo holds the contract, so its ``id`` cannot be reused
    while the entry lives."""
    from src.api.roster_freshness import roster_freshness  # noqa: PLC0415

    state = roster_freshness(dict(contract), now=now).get("state")
    settings_key = (
        json.dumps(roster_settings, sort_keys=True, default=str)
        if isinstance(roster_settings, Mapping)
        else None
    )
    key = (id(contract), _generation(contract), str(league_key), state, settings_key)
    with _MEMO_LOCK:
        hit = _MEMO.get(key)
        if hit is not None and hit.contract is contract:
            _MEMO.move_to_end(key)
            return hit
    snap = build_trade_snapshot(
        contract, league_key=league_key, roster_settings=roster_settings, now=now
    )
    with _MEMO_LOCK:
        _MEMO[key] = snap
        _MEMO.move_to_end(key)
        while len(_MEMO) > _MEMO_SIZE:
            _MEMO.popitem(last=False)
    return snap


def clear_snapshot_memo() -> None:
    with _MEMO_LOCK:
        _MEMO.clear()


# ── Ledger types ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Leg:
    asset_id: str
    from_roster_id: int
    to_roster_id: int

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.asset_id, "from": self.from_roster_id, "to": self.to_roster_id}


@dataclass(frozen=True)
class ValidatedLedger:
    teams: tuple[int, ...]
    legs: tuple[Leg, ...]
    unverifiable_asset_ids: tuple[str, ...]
    generation: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "legs": [leg.to_dict() for leg in self.legs],
            "unverifiableAssetIds": list(self.unverifiable_asset_ids),
        }

    def canonical_key(self) -> str:
        """A stable string for single-flight keys and receipts (teams + legs)."""
        return json.dumps(
            {"teams": list(self.teams), "legs": [leg.to_dict() for leg in self.legs]},
            sort_keys=True,
            separators=(",", ":"),
        )


class LedgerError(Exception):
    """A ledger the engine refuses, with a stable reason code.

    ``asset_ids`` / ``roster_ids`` are request-supplied identifiers only,
    sorted, filtered to the echo pattern and capped — never an actual owner.
    """

    def __init__(
        self,
        status: int,
        error: str,
        reason: str,
        *,
        asset_ids: Iterable[Any] = (),
        roster_ids: Iterable[Any] = (),
        cap: int = 128,
    ) -> None:
        super().__init__(f"{error}:{reason}")
        self.status = int(status)
        self.error = error
        self.reason = reason
        aids = sorted({str(a) for a in asset_ids if _ECHO_RE.match(str(a))})
        self.asset_ids: tuple[str, ...] = tuple(aids[: max(0, int(cap))])
        rids: set[int] = set()
        for r in roster_ids:
            if isinstance(r, int) and not isinstance(r, bool):
                rids.add(r)
        self.roster_ids: tuple[int, ...] = tuple(sorted(rids)[: max(0, int(cap))])

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"error": self.error, "reason": self.reason}
        if self.asset_ids:
            out["assetIds"] = list(self.asset_ids)
        if self.roster_ids:
            out["rosterIds"] = list(self.roster_ids)
        return out


@dataclass(frozen=True)
class TeamFlows:
    """One team's legs: what it sends (to any destination) and receives (from
    any sender), split into raw Sleeper player ids and canonical pick ids."""

    roster_id: int
    gives: tuple[Leg, ...]
    receives: tuple[Leg, ...]
    player_ids_out: tuple[str, ...]
    player_ids_in: tuple[str, ...]
    pick_ids_out: tuple[str, ...]
    pick_ids_in: tuple[str, ...]


# ── Parsing ────────────────────────────────────────────────────────────────


def parse_asset_id(asset_id: Any, *, league_key: str) -> tuple[str, Any] | None:
    """``("player", sleeperId)`` / ``("pick", LeaguePickIdentity)`` or ``None``.

    Only the two canonical forms are accepted; a pick of another league is
    ``None``.  Labels are never parsed.
    """
    if not isinstance(asset_id, str):
        return None
    if asset_id.startswith(PLAYER_PREFIX):
        pid = asset_id[len(PLAYER_PREFIX) :]
        if pid and pid.isalnum() and pid.isascii() and len(pid) <= 16:
            return ("player", pid)
        return None
    ident = parse_league_pick_id(asset_id)
    if ident is None or ident.league_key != league_key or ident.canonical_id != asset_id:
        return None
    return ("pick", ident)


def _leg_tuple(raw: Any) -> tuple[Any, Any, Any]:
    if isinstance(raw, Leg):
        return raw.asset_id, raw.from_roster_id, raw.to_roster_id
    if isinstance(raw, Mapping):
        return raw.get("id", raw.get("assetId")), raw.get("from"), raw.get("to")
    if isinstance(raw, (tuple, list)) and len(raw) == 3:
        return raw[0], raw[1], raw[2]
    return None, None, None


def _int_or_none(v: Any) -> int | None:
    if isinstance(v, bool) or not isinstance(v, int):
        return None
    return v


# ── Validation (spec §2.3; the first failing check decides) ───────────────


def validate_ledger(
    snap: TradeSnapshot,
    *,
    teams: Sequence[Any],
    legs: Sequence[Any],
    policy: LedgerPolicy,
) -> ValidatedLedger:
    """Validate a proposed ledger against ``snap``; raises :class:`LedgerError`.

    Teams are canonicalised to ascending ``rosterId`` and legs to ascending
    asset id, so request order can never change a result.  Ownership is
    checked (check 14) only when the snapshot's rosters are ``current``; when
    they are ``stale`` or ``unknown`` every asset is recorded as
    UNVERIFIABLE instead (rosters that are not current prove ownership in
    neither direction).
    """
    cap = int(policy.max_legs)
    team_list = list(teams or [])
    int_teams = [_int_or_none(t) for t in team_list]
    if any(t is None for t in int_teams):
        raise LedgerError(400, "invalid_trade", "team_not_in_league", cap=cap)
    ints = [int(t) for t in int_teams if t is not None]
    distinct = sorted(set(ints))
    # 1-2: count distinct ids first, then duplicates (so [3,3,3,3,3] is
    # duplicate_team, never too_many_teams).
    if len(distinct) < policy.min_teams:
        raise LedgerError(400, "invalid_trade", "too_few_teams", roster_ids=distinct, cap=cap)
    dups = sorted({t for t in ints if ints.count(t) > 1})
    if dups:
        raise LedgerError(400, "invalid_trade", "duplicate_team", roster_ids=dups, cap=cap)
    # 3. too many for the policy or the league.
    if len(distinct) > min(int(policy.max_teams), int(snap.team_count)):
        raise LedgerError(400, "invalid_trade", "too_many_teams", roster_ids=distinct, cap=cap)
    # 4. a team outside the snapshot league.
    foreign = [t for t in distinct if t not in snap.teams_by_roster_id]
    if foreign:
        raise LedgerError(400, "invalid_trade", "team_not_in_league", roster_ids=foreign, cap=cap)
    # 5-6. empty / too many legs (before any per-leg identity work).
    raw_legs = list(legs or [])
    if not raw_legs:
        raise LedgerError(400, "invalid_trade", "empty_trade", cap=cap)
    if len(raw_legs) > cap:
        raise LedgerError(400, "invalid_trade", "too_many_assets", cap=cap)

    parsed: list[tuple[str, Any, Any, tuple[str, Any]]] = []
    unknown: list[Any] = []
    for raw in raw_legs:
        aid, frm, to = _leg_tuple(raw)
        p = parse_asset_id(aid, league_key=snap.league_key)
        if p is None:
            unknown.append(aid)
            continue
        kind, ref = p
        if kind == "player":
            if ref not in snap.known_player_ids:
                unknown.append(aid)
                continue
        else:
            own = lookup_league_pick_owner(
                (), aid, index=snap.pick_owner_index
            )  # index carries the teams
            if own.state == PICK_OWNER_ABSENT:
                unknown.append(aid)
                continue
        parsed.append((aid, frm, to, p))
    # 7. nonexistent asset.
    if unknown:
        raise LedgerError(400, "invalid_trade", "unknown_asset", asset_ids=unknown, cap=cap)
    # 8. duplicate transfer.
    ids = [a for a, _f, _t, _p in parsed]
    dup_ids = sorted({a for a in ids if ids.count(a) > 1})
    if dup_ids:
        raise LedgerError(400, "invalid_trade", "duplicate_asset", asset_ids=dup_ids, cap=cap)
    team_set = set(distinct)
    # 9-11. origin / destination.
    bad_origin = [a for a, f, _t, _p in parsed if _int_or_none(f) not in team_set]
    if bad_origin:
        raise LedgerError(400, "invalid_trade", "invalid_origin", asset_ids=bad_origin, cap=cap)
    bad_dest = [a for a, _f, t, _p in parsed if _int_or_none(t) not in team_set]
    if bad_dest:
        raise LedgerError(400, "invalid_trade", "invalid_destination", asset_ids=bad_dest, cap=cap)
    self_dest = [a for a, f, t, _p in parsed if f == t]
    if self_dest:
        raise LedgerError(
            400, "invalid_trade", "destination_is_origin", asset_ids=self_dest, cap=cap
        )
    senders = {int(f) for _a, f, _t, _p in parsed}
    receivers = {int(t) for _a, _f, t, _p in parsed}
    # 12. a listed team with no leg at all.
    idle = [t for t in distinct if t not in senders and t not in receivers]
    if idle:
        raise LedgerError(400, "invalid_trade", "idle_team", roster_ids=idle, cap=cap)
    # 13. product rule: every team both sends and receives.
    if policy.participation == "send_and_receive":
        lopsided = [t for t in distinct if t not in senders or t not in receivers]
        if lopsided:
            raise LedgerError(400, "invalid_trade", "one_sided_trade", roster_ids=lopsided, cap=cap)

    # 14. ownership — only current rosters prove it.
    unverifiable: list[str] = []
    not_owned: list[str] = []
    if snap.rosters_state != "current":
        unverifiable = [a for a, _f, _t, _p in parsed]
    else:
        for aid, frm, _to, (kind, _ref) in parsed:
            frm_i = int(frm)
            if kind == "player":
                holders = set(snap.player_owners.get(_ref) or ())
                if len(holders) == 1:
                    if holders != {frm_i}:
                        not_owned.append(aid)
                elif not holders:
                    not_owned.append(aid)
                elif frm_i in holders:
                    unverifiable.append(aid)
                else:
                    not_owned.append(aid)
            else:
                own = lookup_league_pick_owner((), aid, index=snap.pick_owner_index)
                if own.state == PICK_OWNER_OWNED:
                    if own.owner_roster_id != frm_i:
                        not_owned.append(aid)
                elif own.state == PICK_OWNER_UNKNOWN:
                    unverifiable.append(aid)
                else:  # absent is check 7; defensive
                    not_owned.append(aid)
    if not_owned:
        raise LedgerError(409, "stale_assets", "asset_not_owned", asset_ids=not_owned, cap=cap)

    canonical = sorted(
        (Leg(str(a), int(f), int(t)) for a, f, t, _p in parsed), key=lambda leg: leg.asset_id
    )
    return ValidatedLedger(
        teams=tuple(distinct),
        legs=tuple(canonical),
        unverifiable_asset_ids=tuple(sorted(set(unverifiable))),
        generation=snap.generation,
    )


# ── Projections ────────────────────────────────────────────────────────────


def team_flows(ledger: ValidatedLedger, roster_id: int) -> TeamFlows:
    """Team ``roster_id``'s gives (every leg it sends, to any destination) and
    receives (every leg routed to it, from any sender), each sorted by id."""
    rid = int(roster_id)
    gives = tuple(leg for leg in ledger.legs if leg.from_roster_id == rid)
    receives = tuple(leg for leg in ledger.legs if leg.to_roster_id == rid)

    def _players(xs: Sequence[Leg]) -> tuple[str, ...]:
        return tuple(
            sorted(
                leg.asset_id[len(PLAYER_PREFIX) :]
                for leg in xs
                if leg.asset_id.startswith(PLAYER_PREFIX)
            )
        )

    def _picks(xs: Sequence[Leg]) -> tuple[str, ...]:
        return tuple(
            sorted(leg.asset_id for leg in xs if not leg.asset_id.startswith(PLAYER_PREFIX))
        )

    return TeamFlows(
        roster_id=rid,
        gives=gives,
        receives=receives,
        player_ids_out=_players(gives),
        player_ids_in=_players(receives),
        pick_ids_out=_picks(gives),
        pick_ids_in=_picks(receives),
    )


def player_label(snap: TradeSnapshot, player_id: str) -> str:
    """Display label for a player id: the board row's name, else Sleeper's
    name, else the id.  PRESENTATION ONLY — identity resolves by id."""
    from src.api.trade_simulator import row_name  # noqa: PLC0415

    row = snap.rows_by_player_id.get(player_id)
    if row:
        name = row_name(row).strip()
        if name:
            return name
    return str(snap.id_to_player.get(player_id) or "").strip() or f"{PLAYER_PREFIX}{player_id}"


def pick_label(snap: TradeSnapshot, asset_id: str) -> str:
    """Display label for a canonical pick id: the holder's own ``pickDetails``
    label when published, else the owner's unslotted overlay label
    (``picks.format_pick_label_overlay``) — never a guessed slot."""
    d = snap.pick_details_by_id.get(asset_id) or {}
    label = str(d.get("label") or "").strip()
    if label:
        return label
    ident = parse_league_pick_id(asset_id)
    if ident is None:
        return asset_id
    return format_pick_label_overlay(ident.season, ident.round_num, None)


def team_display_name(snap: TradeSnapshot, roster_id: int) -> str:
    team = snap.teams_by_roster_id.get(int(roster_id)) or {}
    return str(team.get("name") or "").strip() or f"Team {int(roster_id)}"
