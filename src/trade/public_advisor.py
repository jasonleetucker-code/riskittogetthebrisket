"""Brisket Trade Advisor — the public, restricted interface to the trade engine.

Owner directive 2026-10-19 ("GIVE LEAGUE MEMBERS THE INTELLIGENCE, NOT THE
DATA"); design: the advisor implementation design §2.10 / §3 / §6.

This module is the pure half (no FastAPI).  It does four things and computes
no value of its own:

1. **Snapshot** — :func:`build_snapshot` indexes ONE captured contract
   (``latest_contract_data``) so every list and every evaluation in a request
   reads one coherent generation of rows, rosters and pick ownership.
2. **Lists** — :func:`list_teams` / :func:`list_team_assets` return team and
   asset IDENTITIES (ids, labels, positions, booleans).  Players are ordered by
   the canonical board value on the server; the value never leaves.  Picks sit
   in their own segment ordered by (season, round, origin), never by value.
3. **Validation** — :func:`validate_trade` enforces the trade structure and
   asset ownership against the snapshot, independently of any client.
4. **Evaluation** — :func:`evaluate_trade` runs the SAME shared analysis path
   the private War Room runs (``trade_simulator.simulate_trade`` →
   ``analyze_trade.analyze_trade`` → ``trade_decision.decide``) and maps the
   decision to one of five public categories with
   ``trade_decision.public_category_from_decision``.  It returns an
   :class:`AdvisorResult`, which holds public fields ONLY; the simulation and
   the decision object never leave this module except through
   :func:`_evaluate_trade_internal`, which exists for parity tests.

Engine access goes through ONE adapter block (``_engine_*`` below).  The
shared 2-team analysis service (``src/trade/analyze_service.py``, design B0-c)
is being built in parallel; until it merges, the adapter calls
``simulate_trade`` / ``analyze_trade`` exactly as ``server._build_trade_simulation``
+ ``post_trade_analyze`` do (Team Context on, posture built if missing, the
valuation lens withdrawn so the contract is used as-is).  **Switch the adapter
to ``analyze_service.simulate_for_team`` / ``analyze_for_team`` once B0-c
merges** — no decision logic lives here, so the switch is a call-site change.

Deliberate, named divergences from the private War Room (design §2.10, OD-8):

* ``one_sided_trade`` — with two teams each team must send at least one asset
  (mirrors the War Room's own ``ready`` rule, ``TradeWarRoom.jsx``);
* ``idle_team`` — with three or four teams every team must send or receive;
* a 128-leg payload-safety bound (not a per-team quantity cap);
* player ownership is checked against the roster's ``playerIds`` (409
  ``stale_assets``), and conflicting or unpublished ownership returns
  UNAVAILABLE ``ownership_unverifiable`` instead of being evaluated;
* a player is identified by Sleeper id: an id with no board row, or whose
  board row name resolves to a DIFFERENT player in the engine's name index
  (a name collision), is UNAVAILABLE ``asset_not_evaluable`` rather than
  priced as somebody else (until B0-b makes the engine itself id-keyed).

3–4-team recommendations are built-but-OFF by owner default OD-1: the
Python multi-side twin (design B1) is not on ``main``, so any trade with more
than two teams is validated in full and then answered UNAVAILABLE
``multi_team_unsupported``.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from src.identity.picks import (
    PICK_OWNER_OWNED,
    PICK_OWNER_UNKNOWN,
    league_pick_owner_index,
    lookup_league_pick_owner,
    parse_league_pick_id,
    round_suffix,
    team_pick_ownership_unavailable_reason,
)
from src.trade import trade_decision
from src.utils.name_clean import normalize_position
from src.valuation_math import package_model

_LOG = logging.getLogger(__name__)

ADVISOR_VERSION = "brisket_trade_advisor_v1"
SORTS = ("value_desc", "value_asc", "alpha")
OFFENSE = frozenset({"QB", "RB", "WR", "TE", "K"})
DEFENSE = frozenset({"DL", "LB", "DB"})
MIN_TEAMS = 2
MAX_TEAMS = 4
MAX_LEGS = 128
#: The JavaScript calculator's active package model (``trade-logic.js``
#: ``ACTIVE_PACKAGE_MODEL_ID``).  Python must agree before the advisor answers.
_REQUIRED_PACKAGE_MODEL = package_model.GEOM_Q078_V1
#: Roster freshness budget — the repo's existing scrape-cadence rule
#: (``SCORING_SNAPSHOT_MAX_AGE_HOURS``), not a new number.
_ROSTER_MAX_AGE_HOURS = 6.0
PLAYER_ID_PREFIX = "p:"


class AdvisorError(Exception):
    """A request the advisor refuses, with its public error shape.

    ``extras`` carries only identifiers the caller supplied or the snapshot
    owns (asset ids, roster ids) — never a value or an engine message.
    """

    def __init__(self, status: int, error: str, reason: str | None = None, **extras: Any) -> None:
        super().__init__(error if reason is None else f"{error}:{reason}")
        self.status = int(status)
        self.error = error
        self.reason = reason
        self.extras = extras


# ── Data shapes ────────────────────────────────────────────────────────────


@dataclass(frozen=True, eq=False)
class AdvisorSnapshot:
    contract: Mapping[str, Any]
    league_key: str
    generation: str
    team_order: tuple[int, ...]
    teams_by_rid: Mapping[int, Mapping[str, Any]]
    rows: tuple[Mapping[str, Any], ...]
    row_index: Mapping[str, Mapping[str, Any]]
    rows_by_player_id: Mapping[str, Mapping[str, Any]]
    player_owners: Mapping[str, tuple[int, ...]]
    pick_owner_index: tuple[dict[str, list[int]], bool]
    pick_details_by_id: Mapping[str, Mapping[str, Any]]
    roster_settings: Mapping[str, Any]
    rosters_state: str
    rosters_as_of: str | None
    id_to_player: Mapping[str, str] = field(default_factory=dict)
    positions_by_name: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class PublicTeam:
    roster_id: int
    display_name: str
    team_name: str | None


@dataclass(frozen=True)
class PublicAsset:
    id: str
    kind: str  # "player" | "pick"
    label: str
    side: str  # "offense" | "defense" | "other" | "pick"
    position: str | None = None
    nfl_team: str | None = None
    season: int | None = None
    round: int | None = None
    origin_roster_id: int | None = None
    projection: str | None = None
    evaluable: bool = False


@dataclass(frozen=True)
class TradeLeg:
    id: str
    from_rid: int
    to_rid: int


@dataclass(frozen=True)
class ValidatedTrade:
    perspective: int
    teams: tuple[int, ...]
    legs: tuple[TradeLeg, ...]
    #: Assets whose ownership could not be verified (conflicting or
    #: unpublished records); evaluation answers UNAVAILABLE for them.
    unverifiable_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class AdvisorResult:
    """The ONLY evaluation type the router may serialize: public fields only."""

    category: str
    reason_code: str | None
    unavailable_asset_ids: tuple[str, ...]
    legs: tuple[TradeLeg, ...]
    team_count: int
    perspective: int


# ── Engine adapter (switch to src.trade.analyze_service once B0-c merges) ──
#
# Every call into the private engine is in this block, so the B0-c switch is
# a change here and nowhere else.  These are the engine's OWN resolution
# functions, not copies: the board value an asset list is sorted by is the
# value the engine would analyze with.


def _engine_rows(contract: Mapping[str, Any]) -> list[dict[str, Any]]:
    from src.api.terminal import _players_array

    return _players_array(dict(contract))


def _engine_row_index(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    from src.api.terminal import _build_row_index

    return _build_row_index(rows)


def _engine_row_name(row: Mapping[str, Any]) -> str:
    from src.api.terminal import _row_name

    return _row_name(dict(row))


def _engine_resolve(label: str, row_index: Mapping[str, Any]) -> dict[str, Any] | None:
    """The engine's per-asset resolution (``trade_simulator._resolve_asset``)."""
    from src.api.trade_simulator import _resolve_asset

    return _resolve_asset(label, row_index=row_index)


def default_posture_resolver(
    contract: Mapping[str, Any], league_key: str, team: Mapping[str, Any]
) -> dict[str, Any]:
    """The War Room's posture rule for Analyze Trade with Team Context on:
    ``competitive_posture_for(..., build_if_missing=True)``."""
    from src.api.trade_simulator import competitive_posture_for

    return competitive_posture_for(dict(contract), league_key, dict(team), build_if_missing=True)


def _engine_analyze(
    snap: AdvisorSnapshot,
    team: Mapping[str, Any],
    *,
    players_in: list[str],
    players_out: list[str],
    picks_in: list[str],
    picks_out: list[str],
    pick_ids_in: list[str | None],
    pick_ids_out: list[str | None],
    posture_resolver: Callable[..., Mapping[str, Any] | None],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """``(simulation, analysis)`` exactly as ``/api/trade/analyze`` builds them
    with Team Context on — minus what the public path must not do: no
    comparables lens (context only, never votes), no decision log write, and
    no counterfactual search (``counterfactuals=False``; it runs after the
    headline, leaning and confidence are fixed, so it cannot change a category).
    """
    from src.api.trade_simulator import simulate_trade
    from src.trade.analyze_trade import analyze_trade

    contract = dict(snap.contract)
    posture = posture_resolver(contract, snap.league_key, team)
    simulation = simulate_trade(
        contract,
        resolved_team=dict(team),
        players_in=players_in,
        players_out=players_out,
        picks_in=picks_in,
        picks_out=picks_out,
        pick_asset_ids_in=pick_ids_in,
        pick_asset_ids_out=pick_ids_out,
        roster_settings=dict(snap.roster_settings or {}),
        league_key=snap.league_key,
        include_roster_utility=True,
        competitive_posture=dict(posture) if isinstance(posture, Mapping) else posture,
    )
    simulation["teamContext"] = {"applied": True, "mode": "team"}
    meta = contract.get("meta") if isinstance(contract.get("meta"), dict) else {}
    analysis = analyze_trade(
        simulation,
        comparables=None,
        team_goal=None,
        provenance={
            "boardStamp": meta.get("generatedAt") or contract.get("generatedAt"),
            "scoringFingerprint": meta.get("scoringFingerprint"),
        },
        counterfactuals=False,
    )
    return simulation, analysis


def package_model_ready() -> bool:
    """The advisor answers only when Python's active package model is the one
    the JavaScript calculator uses.  ``package_model._config`` falls back to
    the KTC model on an unreadable or unknown config, so a broken config shows
    up here as a mismatch and the advisor refuses (generic UNAVAILABLE) rather
    than answering on a model ``/trade`` is not using."""
    state = getattr(package_model, "config_state", None)  # B0-e, when merged
    if callable(state):
        try:
            if state() != "ok":
                return False
        except Exception:  # noqa: BLE001
            return False
    try:
        return package_model.active_model_id() == _REQUIRED_PACKAGE_MODEL
    except Exception:  # noqa: BLE001
        return False


# ── Snapshot ───────────────────────────────────────────────────────────────


def generation_for(contract: Mapping[str, Any]) -> str:
    meta = contract.get("meta") if isinstance(contract.get("meta"), dict) else {}
    stamp = (
        contract.get("generatedAt")
        or meta.get("generatedAt")
        or contract.get("scrapeTimestamp")
        or "unknown"
    )
    return hashlib.sha256(f"brisket-advisor-v1|{stamp}".encode()).hexdigest()[:16]


def _rid(team: Any) -> int | None:
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


def _row_player_id(row: Mapping[str, Any]) -> str:
    return str(row.get("playerId") or row.get("_sleeperId") or "").strip()


def roster_freshness(contract: Mapping[str, Any]) -> tuple[str, str | None]:
    """``(state, asOf)`` for the snapshot's rosters (design §2.6 rule).

    ``current`` when the contract states its rosters are LIVE and at most
    six hours old; ``stale`` when it states they were restored from the last
    good snapshot or are older; ``unknown`` when nothing in the contract
    proves either — unprovable freshness is not freshness.  Reads the
    ``sleeper.rosterSource`` / ``rosterSnapshotAgeHours`` evidence (design
    B0-f); a contract built before that evidence exists answers ``unknown``.
    Only the date is exposed.
    """
    sleeper = contract.get("sleeper") if isinstance(contract.get("sleeper"), Mapping) else {}
    source = sleeper.get("rosterSource")
    age = sleeper.get("rosterSnapshotAgeHours")
    stamp = str(contract.get("scrapeTimestamp") or contract.get("generatedAt") or "")
    as_of = stamp[:10] if len(stamp) >= 10 and stamp[4] == "-" else None
    if source == "live":
        if isinstance(age, (int, float)) and not isinstance(age, bool):
            return ("current" if age <= _ROSTER_MAX_AGE_HOURS else "stale"), as_of
        return "current", as_of
    if source == "last_good":
        return "stale", as_of
    return "unknown", None


def build_snapshot(
    contract: Mapping[str, Any],
    *,
    league_key: str,
    roster_settings: Mapping[str, Any] | None,
    freshness: tuple[str, str | None] | None = None,
) -> AdvisorSnapshot:
    """Index one captured contract.  Raises ``AdvisorError(503, not_ready)``
    when it carries no usable league rosters."""
    sleeper = contract.get("sleeper") if isinstance(contract, Mapping) else None
    teams = sleeper.get("teams") if isinstance(sleeper, Mapping) else None
    if not isinstance(teams, list) or not teams:
        raise AdvisorError(503, "advisor_unavailable", "not_ready")
    teams_by_rid: dict[int, Mapping[str, Any]] = {}
    order: list[int] = []
    for t in teams:
        rid = _rid(t)
        if rid is None or rid in teams_by_rid:
            continue
        teams_by_rid[rid] = t
        order.append(rid)
    if len(teams_by_rid) < MIN_TEAMS:
        raise AdvisorError(503, "advisor_unavailable", "not_ready")

    rows = _engine_rows(contract)
    row_index = _engine_row_index(rows)
    rows_by_player_id: dict[str, Mapping[str, Any]] = {}
    for r in rows:
        pid = _row_player_id(r)
        if pid and r.get("assetClass") != "pick" and pid not in rows_by_player_id:
            rows_by_player_id[pid] = r

    player_owners: dict[str, list[int]] = {}
    pick_details: dict[str, Mapping[str, Any]] = {}
    for rid in order:
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

    state, as_of = freshness if freshness is not None else roster_freshness(contract)
    return AdvisorSnapshot(
        contract=contract,
        league_key=str(league_key),
        generation=generation_for(contract),
        team_order=tuple(order),
        teams_by_rid=teams_by_rid,
        rows=tuple(rows),
        row_index=row_index,
        rows_by_player_id=rows_by_player_id,
        player_owners={k: tuple(v) for k, v in player_owners.items()},
        pick_owner_index=league_pick_owner_index(list(teams_by_rid.values())),
        pick_details_by_id=pick_details,
        roster_settings=dict(roster_settings or {}),
        rosters_state=state if state in ("current", "stale", "unknown") else "unknown",
        rosters_as_of=as_of,
        id_to_player=dict(sleeper.get("idToPlayer") or {})
        if isinstance(sleeper.get("idToPlayer"), Mapping)
        else {},
        positions_by_name=dict(sleeper.get("positions") or {})
        if isinstance(sleeper.get("positions"), Mapping)
        else {},
    )


# ── Lists ──────────────────────────────────────────────────────────────────


def _team_display_name(team: Mapping[str, Any], rid: int) -> str:
    name = str(team.get("name") or "").strip()
    return name or f"Team {rid}"


def list_teams(snap: AdvisorSnapshot) -> list[PublicTeam]:
    out: list[PublicTeam] = []
    for rid in snap.team_order:
        t = snap.teams_by_rid[rid]
        team_name = str(t.get("sleeperTeamName") or "").strip() or None
        out.append(PublicTeam(rid, _team_display_name(t, rid), team_name))
    out.sort(key=lambda pt: (pt.display_name.casefold(), pt.roster_id))
    return out


def _player_row_for(snap: AdvisorSnapshot, player_id: str) -> Mapping[str, Any] | None:
    """The canonical row for a Sleeper id, only when the engine's name index
    resolves that row's name back to the SAME player (fail closed on a
    collision rather than price somebody else)."""
    row = snap.rows_by_player_id.get(player_id)
    if row is None:
        return None
    name = _engine_row_name(row).strip().lower()
    hit = snap.row_index.get(name) if name else None
    if hit is None or _row_player_id(hit) != player_id:
        return None
    return row


def _player_resolution(snap: AdvisorSnapshot, player_id: str) -> dict[str, Any] | None:
    row = _player_row_for(snap, player_id)
    if row is None:
        return None
    return _engine_resolve(_engine_row_name(row), snap.row_index)


def _pick_label(snap: AdvisorSnapshot, d: Mapping[str, Any], ident: Any) -> str:
    season = int(ident.season)
    rnd = int(ident.round_num)
    origin = int(ident.origin_roster_id)
    owner = _rid({"roster_id": d.get("ownerRosterId")})
    if owner is not None and owner == origin:
        tail = "Own"
    else:
        origin_team = snap.teams_by_rid.get(origin)
        name = (
            _team_display_name(origin_team, origin)
            if origin_team is not None
            else (str(d.get("fromTeam") or "").strip() or f"Team {origin}")
        )
        tail = f"Originally {name}"
    return f"{season} {round_suffix(rnd)} — {tail}"


def _player_asset(snap: AdvisorSnapshot, pid: str) -> tuple[PublicAsset, float | None]:
    row = _player_row_for(snap, pid)
    raw_row = snap.rows_by_player_id.get(pid)
    label = (
        _engine_row_name(raw_row).strip()
        if raw_row is not None
        else str(snap.id_to_player.get(pid) or "").strip()
    ) or f"Player {pid}"
    pos_raw = None
    if raw_row is not None:
        pos_raw = raw_row.get("position") or raw_row.get("pos")
    if not pos_raw:
        pos_raw = snap.positions_by_name.get(label)
    pos = normalize_position(pos_raw) or None
    side = "offense" if pos in OFFENSE else "defense" if pos in DEFENSE else "other"
    hit = _engine_resolve(_engine_row_name(row), snap.row_index) if row is not None else None
    value = float(hit["value"]) if hit is not None and hit.get("value") else None
    evaluable = value is not None and value > 0
    nfl_team = None
    if raw_row is not None:
        nfl_team = str(raw_row.get("team") or "").strip() or None
    return (
        PublicAsset(
            id=f"{PLAYER_ID_PREFIX}{pid}",
            kind="player",
            label=label,
            side=side,
            position=pos,
            nfl_team=nfl_team,
            evaluable=evaluable,
        ),
        value if evaluable else None,
    )


def list_team_assets(
    snap: AdvisorSnapshot, roster_id: int, *, sort: str
) -> tuple[list[PublicAsset], str]:
    """``(assets, pickOwnership)`` for one team, ordered on the server.

    * ``value_desc`` — priced players by (value desc, label, id), then
      unpriced players by (label, id), then the pick segment;
    * ``value_asc`` — the EXACT reverse of the priced-player segment (ties
      included), then unpriced players, then picks;
    * ``alpha`` — every asset by (label, id).

    Picks are always ordered by (season, round, origin label, id), never by
    value.  When the team's pick ownership is unavailable no pick is listed.
    """
    if sort not in SORTS:
        raise AdvisorError(400, "invalid_request", "unsupported_sort", field="sort")
    team = snap.teams_by_rid.get(int(roster_id))
    if team is None:
        raise AdvisorError(404, "unknown_team")

    priced: list[tuple[float, PublicAsset]] = []
    unpriced: list[PublicAsset] = []
    seen: set[str] = set()
    for raw in team.get("playerIds") or []:
        pid = str(raw or "").strip()
        if not pid or pid in seen:
            continue
        seen.add(pid)
        asset, value = _player_asset(snap, pid)
        if value is None:
            unpriced.append(asset)
        else:
            priced.append((value, asset))

    picks: list[PublicAsset] = []
    pick_state = "observed"
    if team_pick_ownership_unavailable_reason(team) is not None:
        pick_state = "unavailable"
    else:
        for d in team.get("pickDetails") or []:
            if not isinstance(d, Mapping):
                continue
            aid = str(d.get("assetId") or "").strip()
            ident = parse_league_pick_id(aid)
            if ident is None or ident.league_key != snap.league_key or aid in seen:
                continue
            seen.add(aid)
            hit = _engine_resolve(str(d.get("label") or ""), snap.row_index)
            picks.append(
                PublicAsset(
                    id=aid,
                    kind="pick",
                    label=_pick_label(snap, d, ident),
                    side="pick",
                    season=int(ident.season),
                    round=int(ident.round_num),
                    origin_roster_id=int(ident.origin_roster_id),
                    projection=None,  # OD-2: projected labels OFF
                    evaluable=bool(hit is not None and hit.get("value")),
                )
            )
    # Every pick asset above is built with an int season and round.
    picks.sort(key=lambda a: (a.season, a.round, a.label.casefold(), a.id))

    def _label_key(a: PublicAsset) -> tuple[str, str]:
        return (a.label.casefold(), a.id)

    priced_desc = [
        a for _v, a in sorted(priced, key=lambda va: (-va[0], va[1].label.casefold(), va[1].id))
    ]
    unpriced.sort(key=_label_key)
    if sort == "value_desc":
        ordered = [*priced_desc, *unpriced, *picks]
    elif sort == "value_asc":
        ordered = [*reversed(priced_desc), *unpriced, *picks]
    else:
        ordered = sorted([*priced_desc, *unpriced, *picks], key=_label_key)
    return ordered, pick_state


# ── Validation ─────────────────────────────────────────────────────────────


def _parse_asset_id(snap: AdvisorSnapshot, asset_id: str) -> tuple[str, Any] | None:
    """``("player", sleeperId)`` / ``("pick", identity)`` or ``None``."""
    if asset_id.startswith(PLAYER_ID_PREFIX):
        pid = asset_id[len(PLAYER_ID_PREFIX) :]
        if pid and pid.isalnum() and len(pid) <= 16:
            return ("player", pid)
        return None
    ident = parse_league_pick_id(asset_id)
    if ident is None or ident.league_key != snap.league_key:
        return None
    return ("pick", ident)


def validate_trade(
    snap: AdvisorSnapshot,
    *,
    perspective: int,
    teams: list[int] | tuple[int, ...],
    legs: list[tuple[str, int, int]],
) -> ValidatedTrade:
    """Validate a proposed trade against the snapshot (design §2.10 order).

    Raises :class:`AdvisorError` — 400 ``invalid_trade`` for a malformed
    structure, 409 ``stale_assets`` for an asset the origin team does not hold
    in this snapshot.  Ownership that cannot be verified (conflicting claims,
    an unpublished pick inventory) is returned in ``unverifiable_ids``.
    """
    team_list = [int(t) for t in teams]
    if int(perspective) not in team_list:
        raise AdvisorError(
            400, "invalid_trade", "perspective_not_in_trade", rosterIds=[int(perspective)]
        )
    dups = sorted({t for t in team_list if team_list.count(t) > 1})
    if dups:
        raise AdvisorError(400, "invalid_trade", "duplicate_team", rosterIds=dups)
    unknown_teams = [t for t in team_list if t not in snap.teams_by_rid]
    if unknown_teams:
        raise AdvisorError(400, "invalid_trade", "unknown_team", rosterIds=unknown_teams)

    parsed: list[tuple[str, int, int, tuple[str, Any]]] = []
    bad_ids = []
    for asset_id, frm, to in legs:
        p = _parse_asset_id(snap, asset_id)
        if p is None:
            bad_ids.append(asset_id)
        else:
            parsed.append((asset_id, int(frm), int(to), p))
    if bad_ids:
        raise AdvisorError(400, "invalid_trade", "unknown_asset", assetIds=bad_ids)
    ids = [a for a, _f, _t, _p in parsed]
    dup_ids = sorted({a for a in ids if ids.count(a) > 1})
    if dup_ids:
        raise AdvisorError(400, "invalid_trade", "duplicate_asset", assetIds=dup_ids)
    team_set = set(team_list)
    bad_origin = [a for a, f, _t, _p in parsed if f not in team_set]
    if bad_origin:
        raise AdvisorError(400, "invalid_trade", "invalid_origin", assetIds=bad_origin)
    bad_dest = [a for a, _f, t, _p in parsed if t not in team_set]
    if bad_dest:
        raise AdvisorError(400, "invalid_trade", "invalid_destination", assetIds=bad_dest)
    self_dest = [a for a, f, t, _p in parsed if f == t]
    if self_dest:
        raise AdvisorError(400, "invalid_trade", "destination_is_origin", assetIds=self_dest)
    if len(parsed) > MAX_LEGS:
        raise AdvisorError(400, "invalid_trade", "too_many_assets")
    senders = {f for _a, f, _t, _p in parsed}
    receivers = {t for _a, _f, t, _p in parsed}
    if len(team_list) == 2:
        idle = [t for t in team_list if t not in senders]
        if idle:
            raise AdvisorError(400, "invalid_trade", "one_sided_trade", rosterIds=idle)
    else:
        idle = [t for t in team_list if t not in senders and t not in receivers]
        if idle:
            raise AdvisorError(400, "invalid_trade", "idle_team", rosterIds=idle)

    not_owned: list[str] = []
    unverifiable: list[str] = []
    teams_seq = list(snap.teams_by_rid.values())
    for asset_id, frm, _to, (kind, ref) in parsed:
        if kind == "player":
            owners = snap.player_owners.get(ref) or ()
            if len(set(owners)) > 1:
                unverifiable.append(asset_id)
            elif tuple(set(owners)) != (frm,):
                not_owned.append(asset_id)
        else:
            own = lookup_league_pick_owner(teams_seq, asset_id, index=snap.pick_owner_index)
            if own.state == PICK_OWNER_OWNED:
                if own.owner_roster_id != frm:
                    not_owned.append(asset_id)
            elif own.state == PICK_OWNER_UNKNOWN:
                unverifiable.append(asset_id)
            else:
                not_owned.append(asset_id)
    if not_owned:
        raise AdvisorError(409, "stale_assets", "asset_not_owned", assetIds=not_owned)
    return ValidatedTrade(
        perspective=int(perspective),
        teams=tuple(team_list),
        legs=tuple(TradeLeg(a, f, t) for a, f, t, _p in parsed),
        unverifiable_ids=tuple(unverifiable),
    )


# ── Evaluation ─────────────────────────────────────────────────────────────


def _unavailable(
    trade: ValidatedTrade, reason: str | None, ids: tuple[str, ...] = ()
) -> AdvisorResult:
    return AdvisorResult(
        category="UNAVAILABLE",
        reason_code=reason,
        unavailable_asset_ids=ids,
        legs=trade.legs,
        team_count=len(trade.teams),
        perspective=trade.perspective,
    )


def _evaluate_trade_internal(
    snap: AdvisorSnapshot,
    trade: ValidatedTrade,
    *,
    posture_resolver: Callable[..., Mapping[str, Any] | None] | None = None,
    multi_team_enabled: bool = False,
) -> tuple[AdvisorResult, dict[str, Any]]:
    """``(AdvisorResult, internals)`` — internals are for tests only and must
    never reach a response."""
    internals: dict[str, Any] = {}
    if len(trade.teams) != 2:
        # OD-1: built-but-OFF.  The multi-side twin is not on main, so even a
        # switched-on config cannot produce a 3–4-team category here.
        internals["multiTeamEnabled"] = bool(multi_team_enabled)
        return _unavailable(trade, "multi_team_unsupported"), internals
    if trade.unverifiable_ids:
        return _unavailable(trade, "ownership_unverifiable"), internals
    if not package_model_ready():
        _LOG.error("public advisor: package model is not the active JS model; refusing")
        return _unavailable(trade, None), internals

    perspective = trade.perspective
    team = snap.teams_by_rid[perspective]
    players_in: list[str] = []
    players_out: list[str] = []
    picks_in: list[str] = []
    picks_out: list[str] = []
    ids_in: list[str | None] = []
    ids_out: list[str | None] = []
    engine_label_to_id: dict[str, str] = {}
    not_evaluable: list[str] = []
    for leg in trade.legs:
        incoming = leg.to_rid == perspective
        if leg.id.startswith(PLAYER_ID_PREFIX):
            row = _player_row_for(snap, leg.id[len(PLAYER_ID_PREFIX) :])
            if row is None:
                not_evaluable.append(leg.id)
                continue
            name = _engine_row_name(row)
            engine_label_to_id[name] = leg.id
            (players_in if incoming else players_out).append(name)
        else:
            d = snap.pick_details_by_id.get(leg.id) or {}
            label = str(d.get("label") or "").strip()
            if not label:
                not_evaluable.append(leg.id)
                continue
            engine_label_to_id[label] = leg.id
            if incoming:
                picks_in.append(label)
                ids_in.append(leg.id)
            else:
                picks_out.append(label)
                ids_out.append(leg.id)
    if not_evaluable:
        return _unavailable(trade, "asset_not_evaluable", tuple(not_evaluable)), internals

    simulation, analysis = _engine_analyze(
        snap,
        team,
        players_in=players_in,
        players_out=players_out,
        picks_in=picks_in,
        picks_out=picks_out,
        pick_ids_in=ids_in,
        pick_ids_out=ids_out,
        posture_resolver=posture_resolver or default_posture_resolver,
    )
    internals["simulation"] = simulation
    internals["analysis"] = analysis
    decision = analysis.get("decision") if isinstance(analysis, dict) else None
    category = trade_decision.public_category_from_decision(decision)
    reason = trade_decision.public_reason_code(decision)
    if category not in trade_decision.PUBLIC_CATEGORIES:
        category, reason = "UNAVAILABLE", None
    if category == "UNAVAILABLE" and reason == "roster_limit":
        reason = None
    if category != "UNAVAILABLE" and reason not in (None, "roster_limit"):
        reason = None
    ids: tuple[str, ...] = ()
    if category == "UNAVAILABLE" and reason == "asset_not_evaluable":
        mapped = []
        for label in trade_decision.public_asset_gap_labels(decision):
            aid = engine_label_to_id.get(label)
            if aid is None:
                # The engine names a resolved asset by its board row; map by
                # case-insensitive match before giving up.
                aid = next(
                    (v for k, v in engine_label_to_id.items() if k.lower() == label.lower()),
                    None,
                )
            if aid is not None and aid not in mapped:
                mapped.append(aid)
        ids = tuple(mapped)
    return (
        AdvisorResult(
            category=category,
            reason_code=reason,
            unavailable_asset_ids=ids,
            legs=trade.legs,
            team_count=2,
            perspective=perspective,
        ),
        internals,
    )


def evaluate_trade(
    snap: AdvisorSnapshot,
    trade: ValidatedTrade,
    *,
    posture_resolver: Callable[..., Mapping[str, Any] | None] | None = None,
    multi_team_enabled: bool = False,
) -> AdvisorResult:
    """The public evaluation: an :class:`AdvisorResult` and nothing else."""
    result, _internals = _evaluate_trade_internal(
        snap,
        trade,
        posture_resolver=posture_resolver,
        multi_team_enabled=multi_team_enabled,
    )
    return result


def result_text(result: AdvisorResult) -> dict[str, str | None]:
    """The fixed copy for a result: recommendation / headline / message plus
    the reason text (``None`` unless the reason is one of the public codes)."""
    text = trade_decision.public_text(result.category, result.reason_code)
    reason_text = (
        trade_decision.PUBLIC_REASON_TEXT.get(result.reason_code) if result.reason_code else None
    )
    return {**text, "reasonText": reason_text}
