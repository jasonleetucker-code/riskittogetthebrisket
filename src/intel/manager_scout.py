"""Manager Scout — per-manager tendency profiles (C6-MGR-01, CE-03).

WHAT THIS ANSWERS
─────────────────
"How does each manager in THIS league behave?" — descriptively, from what
they actually did: how often they trade and with whom, which positions and
asset classes they bring in versus send out, how much of their dealing is in
draft picks, whether they consolidate or spread out, how active they are on
the waiver wire, and how hard they bid FAAB against the price claims
actually clear at.

PRIVATE DECISION INTELLIGENCE
─────────────────────────────
``docs/OWNER_PRODUCT_BACKLOG_SPEC.md`` §7: "Analyze fantasy behavior only —
never real-world personal profiling … **Private only.**"  Manager tendencies
are named private in the B8 boundary
(``src/public_league/public_contract.py``) and in CLAUDE.md's public/private
split.  This module is reachable only through the session-gated
``/api/manager-scout`` route; no ``/api/public/*`` surface may import it, and
``_PRIVATE_FIELD_BLOCKLIST`` refuses its field names in any public payload.

ONE CONCEPT, ONE OWNER — THIS MODULE DERIVES NOTHING IT CAN CONSUME
──────────────────────────────────────────────────────────────────
Every input comes from an existing canonical owner, and nothing here
re-fetches Sleeper or re-parses a transaction:

=============================  =================================================
quantity                        owner consumed
=============================  =================================================
completed trades, both sides    ``src.trade.market_trade_ledger.market_trades``
                                (C4-MTL-01, projected from the C1-ACQ-01
                                acquisition ledger)
waiver / free-agent claims      ``src.trade.waiver_ledger.waiver_claims``
                                (C4-WAIV-01, same ledger)
FAAB bidding                    ``src.trade.faab_history`` — the resolved
                                bid-history summary and the bid predictor's
                                own per-manager factor (#1146)
player position                 ``src.identity.resolution.resolve_canonical_v2``
                                by Sleeper id (C1-ID-01)
pick season / round             ``src.identity.picks.parse_league_pick_id``
                                (C1-ID-02)
best-ball format                ``src.api.league_registry`` (stated fact only)
=============================  =================================================

**One value view, read — never computed.**  Each trade block carries
``valueAtToday``: the assets a manager received and sent, priced at TODAY's
canonical board (``rankDerivedValue`` for players; picks through
``identity.picks.market_resolution`` + ``api.pick_value_resolution`` — the
one MarketPickRef→value owner).  It is the Current-Grade view
``docs/TRADE_HISTORY_AGING_SPEC.md`` §1 names, as a RAW VALUE SUM: no Value
Adjustment, no package method, and never an at-the-time value.  An asset the
board declines to price is counted in ``unpricedAssets`` and excluded from the
sums — never added as 0.

IDENTITY ACROSS SEASONS
───────────────────────
Sleeper re-mints a dynasty league's id every season, and a roster id is only
stable inside one of them.  Every manager here is keyed by the Sleeper USER id
the ledgers recorded (``ownerUserId`` / bid-history ``ownerId``), so one human
is one profile across the whole chain, a renamed team does not split, and an
orphan takeover does not merge two people.  An event whose roster could not be
attributed to a user is counted as UNATTRIBUTED at league level and never
assigned to anyone.  No raw Sleeper league id appears in the output.

MISSING IS NEVER ZERO
─────────────────────
Every metric block carries ``state`` and ``sampleSize``:

* ``measured``            — at least one observation; the value is a real
                            measurement of that sample.
* ``insufficient_sample`` — the source is present but holds no observation
                            for this manager, so a share/ratio is undefined.
                            "No trades" is NOT "0% picks".
* ``unavailable``         — the source itself is absent on this host.
* ``not_applicable``      — the behaviour cannot exist (lineups in best ball).
* ``not_measured``        — the behaviour exists but no canonical owner
                            measures it.

Counts of observed events (``tradeCount``, ``claims``) are real counts when the
source is present — zero trades observed is a fact about the ledger.  Shares
and ratios are never published at a zero denominator.

NO LABELS WITHOUT AN OWNER-SETTLED THRESHOLD
────────────────────────────────────────────
Words like "aggressive", "pick hoarder" or "consolidator" need a cut-off no
owner has decided, so this module publishes the raw measured quantity and its
sample instead.  The one exception is structural, not a threshold: a trade in
which a manager sent more assets than they received is "consolidating" by
definition, and those counts are published as counts.
"""

from __future__ import annotations

import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

METHOD_VERSION = "manager_scout_v1"
PRIVACY_CLASS = "private"

STATE_MEASURED = "measured"
STATE_INSUFFICIENT = "insufficient_sample"
STATE_UNAVAILABLE = "unavailable"
STATE_NOT_APPLICABLE = "not_applicable"
STATE_NOT_MEASURED = "not_measured"

#: Position bucket for a player the identity owner could not resolve.  Its
#: own bucket — never folded into a real position, never dropped.
UNRESOLVED_POSITION = "UNRESOLVED"

PositionLookup = Callable[[str], "str | None"]


# ── Small helpers ─────────────────────────────────────────────────────────


def _share(numerator: int, denominator: int) -> dict[str, Any]:
    """A share with its sample, or an explicit insufficient state at 0."""
    if denominator <= 0:
        return {"state": STATE_INSUFFICIENT, "value": None, "sampleSize": 0}
    return {
        "state": STATE_MEASURED,
        "value": round(numerator / denominator, 4),
        "sampleSize": denominator,
    }


def _window(times_ms: Iterable[int | None], seasons: Iterable[str | None]) -> dict[str, Any]:
    times = list(times_ms)
    dated = [t for t in times if t is not None]
    return {
        "seasons": sorted({str(s) for s in seasons if s}),
        "oldestOccurredAtMs": min(dated) if dated else None,
        "newestOccurredAtMs": max(dated) if dated else None,
        "undatedEvents": len(times) - len(dated),
    }


def _bump(d: dict[str, int], key: str, n: int = 1) -> None:
    d[key] = d.get(key, 0) + n


def _player_id(asset_id: str) -> str | None:
    if isinstance(asset_id, str) and asset_id.startswith("player:"):
        return asset_id.split(":", 1)[1] or None
    return None


# ── Default identity adapter (C1-ID-01) ───────────────────────────────────

_POSITION_CACHE_LOCK = threading.Lock()
_POSITION_CACHE: dict[str, Any] = {}


def default_position_lookup() -> tuple[PositionLookup | None, str]:
    """``(lookup, state)`` over the app's cached Sleeper player directory.

    Resolution goes through the canonical identity owner
    (``resolve_canonical_v2`` by Sleeper id), never a private position
    table.  Cached per directory file mtime.  ``(None, "unavailable")`` when
    no directory is on this host — every player then lands in
    ``UNRESOLVED`` rather than being guessed.
    """
    try:
        from src.public_league import snapshot_store  # noqa: PLC0415

        path = Path(snapshot_store.NFL_PLAYERS_PATH)
        mtime = path.stat().st_mtime_ns if path.exists() else None
    except Exception:  # noqa: BLE001 — absence is a state
        return None, STATE_UNAVAILABLE
    if mtime is None:
        return None, STATE_UNAVAILABLE

    with _POSITION_CACHE_LOCK:
        if _POSITION_CACHE.get("mtime") == mtime:
            return _POSITION_CACHE["lookup"], _POSITION_CACHE["state"]
        try:
            from src.consensus_edge.identity_join import load_player_directory  # noqa: PLC0415
            from src.identity.resolution import (  # noqa: PLC0415
                RESOLVED,
                build_sleeper_index,
                resolve_canonical_v2,
            )

            directory = load_player_directory()
            if not directory:
                return None, STATE_UNAVAILABLE
            index = build_sleeper_index(directory)
        except Exception:  # noqa: BLE001
            return None, STATE_UNAVAILABLE

        memo: dict[str, str | None] = {}

        def lookup(sleeper_id: str) -> str | None:
            if sleeper_id not in memo:
                res = resolve_canonical_v2(index, sleeper_id=str(sleeper_id))
                memo[sleeper_id] = (res.position or None) if res.status == RESOLVED else None
            return memo[sleeper_id]

        _POSITION_CACHE.update({"mtime": mtime, "lookup": lookup, "state": "available"})
        return lookup, "available"


# ── Per-manager accumulators ──────────────────────────────────────────────


def _empty_side() -> dict[str, Any]:
    return {
        "assets": 0,
        "players": 0,
        "picks": 0,
        "byPosition": {},
        "picksByRound": {},
        "picksBySeasonOffset": {},
        "pickSeasonOffsetUnknown": 0,
    }


def _new_trade_acc() -> dict[str, Any]:
    return {
        "trades": set(),
        "times": [],
        "seasons": [],
        "bySeason": {},
        "multiTeam": 0,
        "partners": {},
        "unattributedPartners": 0,
        "received": _empty_side(),
        "sent": _empty_side(),
        "consolidating": 0,
        "expanding": 0,
        "even": 0,
        "value": _empty_value(),
    }


def _empty_value() -> dict[str, Any]:
    return {
        "receivedTotal": 0,
        "sentTotal": 0,
        "pricedReceived": 0,
        "pricedSent": 0,
        "unpricedReceived": 0,
        "unpricedSent": 0,
        "picksAtGenericGrade": 0,
    }


ValueLookup = Callable[[str, str], "tuple[int | None, bool]"]


def contract_value_lookup(contract: Mapping[str, Any] | None) -> ValueLookup | None:
    """``(asset_id, asset_kind) -> (value | None, priced_at_generic_grade)``
    over the loaded canonical board, or ``None`` when no board is loaded.

    Players: the row whose ``playerId`` (Sleeper id) matches, its positive
    finite ``rankDerivedValue``.  Picks: the league pick's market reference
    via ``identity.picks.market_resolution`` — slot unknown here, so the
    GENERIC grade, exactly as that owner answers — priced by
    ``api.pick_value_resolution.resolve_pick_value``.  A drafted class no
    longer on the board, an unpriced row, or an unparseable id is ``None``.
    """
    if not isinstance(contract, Mapping) or not contract.get("playersArray"):
        return None
    import math  # noqa: PLC0415

    from src.api.pick_value_resolution import resolve_pick_value  # noqa: PLC0415
    from src.identity.picks import market_resolution, parse_league_pick_id  # noqa: PLC0415

    def _positive(v: Any) -> int | None:
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return None
        return int(v) if math.isfinite(float(v)) and v > 0 else None

    players: dict[str, int | None] = {}
    for row in contract.get("playersArray") or []:
        if not isinstance(row, Mapping) or row.get("assetClass") == "pick":
            continue
        pid = str(row.get("playerId") or "").strip()
        if pid and pid not in players:
            players[pid] = _positive(row.get("rankDerivedValue"))
    try:
        draft_year: int | None = int(contract.get("currentDraftYear"))
    except (TypeError, ValueError):
        draft_year = None
    pick_memo: dict[str, int | None] = {}
    board = dict(contract)

    def lookup(asset_id: str, asset_kind: str) -> tuple[int | None, bool]:
        if asset_kind != "pick":
            pid = _player_id(asset_id)
            return (players.get(pid) if pid else None), False
        ident = parse_league_pick_id(asset_id)
        if ident is None or draft_year is None:
            return None, False
        ref = market_resolution(
            year=ident.season,
            round_num=ident.round_num,
            slot=None,
            current_draft_year=draft_year,
        ).ref
        key = ref.board_row_name() or ""
        if key not in pick_memo:
            pick_memo[key] = resolve_pick_value(board, ref).value if key else None
        return pick_memo[key], True

    return lookup


def _record_value(
    acc_value: dict[str, Any],
    assets: list[Mapping[str, Any]],
    direction: str,
    value_of: ValueLookup | None,
) -> None:
    if value_of is None:
        return
    for a in assets:
        v, generic = value_of(str(a.get("assetId") or ""), str(a.get("assetKind") or ""))
        if v is None:
            acc_value[f"unpriced{direction}"] += 1
            continue
        acc_value[f"{direction.lower()}Total"] += v
        acc_value[f"priced{direction}"] += 1
        if generic:
            acc_value["picksAtGenericGrade"] += 1


def _new_waiver_acc() -> dict[str, Any]:
    return {
        "claims": 0,
        "waiver": 0,
        "freeAgent": 0,
        "withDrop": 0,
        "bySeason": {},
        "addedByPosition": {},
        "times": [],
        "seasons": [],
    }


def _record_assets(
    side: dict[str, Any],
    assets: list[Mapping[str, Any]],
    *,
    trade_season: int | None,
    position_of: PositionLookup | None,
) -> None:
    from src.identity.picks import parse_league_pick_id  # noqa: PLC0415

    for a in assets:
        side["assets"] += 1
        kind = a.get("assetKind")
        aid = str(a.get("assetId") or "")
        if kind == "pick":
            side["picks"] += 1
            ident = parse_league_pick_id(aid)
            if ident is None:
                _bump(side["picksByRound"], "unknown")
                side["pickSeasonOffsetUnknown"] += 1
                continue
            _bump(side["picksByRound"], str(ident.round_num))
            if trade_season is None:
                side["pickSeasonOffsetUnknown"] += 1
            else:
                _bump(side["picksBySeasonOffset"], str(ident.season - trade_season))
        else:
            side["players"] += 1
            pid = _player_id(aid)
            pos = position_of(pid) if (position_of and pid) else None
            _bump(side["byPosition"], pos or UNRESOLVED_POSITION)


def _season_int(season: Any) -> int | None:
    try:
        return int(str(season))
    except (TypeError, ValueError):
        return None


# ── Builders per source ───────────────────────────────────────────────────


def _fold_trades(
    trades: list[Mapping[str, Any]],
    *,
    position_of: PositionLookup | None,
    value_of: ValueLookup | None = None,
) -> tuple[dict[str, dict[str, Any]], dict[str, int]]:
    accs: dict[str, dict[str, Any]] = {}
    league = {"trades": len(trades), "unattributedSides": 0}
    for t in trades:
        ref = str(t.get("sourceRef") or "")
        season = t.get("season")
        season_i = _season_int(season)
        teams = t.get("teams") or {}
        owners = [side.get("ownerUserId") for side in teams.values()]
        multi = len(teams) > 2
        seen_users: set[str] = set()
        for side in teams.values():
            uid = side.get("ownerUserId")
            if not uid:
                league["unattributedSides"] += 1
                continue
            uid = str(uid)
            acc = accs.setdefault(uid, _new_trade_acc())
            received = list(side.get("received") or [])
            sent = list(side.get("sent") or [])
            _record_assets(
                acc["received"], received, trade_season=season_i, position_of=position_of
            )
            _record_assets(acc["sent"], sent, trade_season=season_i, position_of=position_of)
            _record_value(acc["value"], received, "Received", value_of)
            _record_value(acc["value"], sent, "Sent", value_of)
            if uid in seen_users:
                # Two sides of one trade attributed to the same human: the
                # assets count, the trade does not count twice.
                continue
            seen_users.add(uid)
            acc["trades"].add(ref)
            acc["times"].append(t.get("occurredAtMs"))
            acc["seasons"].append(season)
            _bump(acc["bySeason"], str(season) if season else "unknown")
            if multi:
                acc["multiTeam"] += 1
            if len(sent) > len(received):
                acc["consolidating"] += 1
            elif len(sent) < len(received):
                acc["expanding"] += 1
            else:
                acc["even"] += 1
            for other in owners:
                if other is None:
                    acc["unattributedPartners"] += 1
                elif str(other) != uid:
                    _bump(acc["partners"], str(other))
    return accs, league


def _fold_waivers(
    claims: list[Mapping[str, Any]],
    *,
    position_of: PositionLookup | None,
) -> tuple[dict[str, dict[str, Any]], dict[str, int]]:
    accs: dict[str, dict[str, Any]] = {}
    league = {"claims": len(claims), "unattributedClaims": 0}
    for c in claims:
        uid = c.get("ownerUserId")
        if not uid:
            league["unattributedClaims"] += 1
            continue
        acc = accs.setdefault(str(uid), _new_waiver_acc())
        acc["claims"] += 1
        if c.get("transactionType") == "WAIVER":
            acc["waiver"] += 1
        else:
            acc["freeAgent"] += 1
        if c.get("dropped"):
            acc["withDrop"] += 1
        season = c.get("season")
        _bump(acc["bySeason"], str(season) if season else "unknown")
        acc["times"].append(c.get("occurredAtMs"))
        acc["seasons"].append(season)
        for a in c.get("added") or []:
            if a.get("assetKind") != "player":
                continue
            pid = _player_id(str(a.get("assetId") or ""))
            pos = position_of(pid) if (position_of and pid) else None
            _bump(acc["addedByPosition"], pos or UNRESOLVED_POSITION)
    return accs, league


def _side_block(side: dict[str, Any]) -> dict[str, Any]:
    return {
        "assets": side["assets"],
        "players": side["players"],
        "picks": side["picks"],
        "byPosition": dict(sorted(side["byPosition"].items())),
        "picksByRound": dict(sorted(side["picksByRound"].items())),
        "picksBySeasonOffset": dict(
            sorted(side["picksBySeasonOffset"].items(), key=lambda kv: int(kv[0]))
        ),
        "pickSeasonOffsetUnknown": side["pickSeasonOffsetUnknown"],
    }


#: What ``valueAtToday`` is — and is not.  Travels with every number.
VALUE_BASIS = "todays_canonical_board_raw_sum_not_value_adjusted"


def _value_block(
    acc: dict[str, Any], n: int, *, board_as_of: str | None, board_state: str
) -> dict[str, Any]:
    """Today's-board raw value of what a manager received and sent."""
    if board_state != "available":
        return {"state": STATE_UNAVAILABLE, "reason": board_state, "sampleSize": None}
    v = acc["value"]
    if not n:
        return {"state": STATE_INSUFFICIENT, "sampleSize": 0, "basis": VALUE_BASIS}

    def _total(direction: str) -> int | None:
        # A side whose every asset is unpriced has no measured total; a side
        # that received nothing at all genuinely totals 0.
        priced, unpriced = v[f"priced{direction}"], v[f"unpriced{direction}"]
        return v[f"{direction.lower()}Total"] if (priced or not unpriced) else None

    got, gave = _total("Received"), _total("Sent")
    net = (got - gave) if (got is not None and gave is not None) else None
    return {
        "state": STATE_MEASURED,
        "sampleSize": n,
        "basis": VALUE_BASIS,
        "boardAsOf": board_as_of,
        "receivedTotal": got,
        "sentTotal": gave,
        "netTotal": net,
        "receivedPerTrade": round(got / n) if got is not None else None,
        "sentPerTrade": round(gave / n) if gave is not None else None,
        "netPerTrade": round(net / n) if net is not None else None,
        "pricedAssets": v["pricedReceived"] + v["pricedSent"],
        "unpricedAssets": v["unpricedReceived"] + v["unpricedSent"],
        "unpricedReceived": v["unpricedReceived"],
        "unpricedSent": v["unpricedSent"],
        "picksAtGenericGrade": v["picksAtGenericGrade"],
    }


def _trading_block(
    acc: dict[str, Any] | None,
    *,
    source_state: str,
    names: Mapping[str, str | None],
    board_as_of: str | None = None,
    board_state: str = "no_board_loaded",
) -> dict[str, Any]:
    if source_state != "available":
        return {"state": STATE_UNAVAILABLE, "reason": source_state, "sampleSize": None}
    acc = acc or _new_trade_acc()
    n = len(acc["trades"])
    recv, sent = acc["received"], acc["sent"]
    partners = sorted(acc["partners"].items(), key=lambda kv: (-kv[1], kv[0]))
    return {
        "state": STATE_MEASURED if n else STATE_INSUFFICIENT,
        "sampleSize": n,
        "window": _window(acc["times"], acc["seasons"]),
        "tradeCount": n,
        "tradesBySeason": dict(sorted(acc["bySeason"].items())),
        "multiTeamTrades": acc["multiTeam"],
        "partners": [
            {"ownerId": uid, "displayName": names.get(uid), "trades": k} for uid, k in partners
        ],
        "unattributedPartnerSides": acc["unattributedPartners"],
        "received": _side_block(recv),
        "sent": _side_block(sent),
        # Raw counts, no label: "how much of what they deal is picks".
        "pickShareOfReceived": _share(recv["picks"], recv["assets"]),
        "pickShareOfSent": _share(sent["picks"], sent["assets"]),
        "netPicks": (recv["picks"] - sent["picks"]) if n else None,
        "netPlayers": (recv["players"] - sent["players"]) if n else None,
        # Structural, not a threshold: sent more pieces than received.
        "packageShape": {
            "consolidating": acc["consolidating"],
            "expanding": acc["expanding"],
            "even": acc["even"],
            "consolidatingShare": _share(acc["consolidating"], n),
        },
        "valueAtToday": _value_block(acc, n, board_as_of=board_as_of, board_state=board_state),
    }


def _waiver_block(acc: dict[str, Any] | None, *, source_state: str) -> dict[str, Any]:
    if source_state != "available":
        return {"state": STATE_UNAVAILABLE, "reason": source_state, "sampleSize": None}
    acc = acc or _new_waiver_acc()
    n = acc["claims"]
    return {
        "state": STATE_MEASURED if n else STATE_INSUFFICIENT,
        "sampleSize": n,
        "window": _window(acc["times"], acc["seasons"]),
        "claims": n,
        "waiverClaims": acc["waiver"],
        "freeAgentClaims": acc["freeAgent"],
        "claimsWithDrop": acc["withDrop"],
        "claimsBySeason": dict(sorted(acc["bySeason"].items())),
        "addedByPosition": dict(sorted(acc["addedByPosition"].items())),
        "waiverShareOfClaims": _share(acc["waiver"], n),
    }


def _faab_block(owner_id: str, priors: Any, *, source_state: str) -> dict[str, Any]:
    if source_state != "available" or priors is None:
        return {"state": STATE_UNAVAILABLE, "reason": source_state, "sampleSize": None}
    from src.trade.faab_history import owner_aggression_factor  # noqa: PLC0415

    win_n = int(priors.owner_sample.get(owner_id, 0))
    att_n = int(priors.owner_attempt_sample.get(owner_id, 0))
    failed = int(priors.owner_attempt_failed.get(owner_id, 0))
    clearing_mean = priors.mean_pct if priors.sample_size else None
    attempt_mean = priors.bid_attempt_mean_pct

    def _ratio(owner_mean: float | None, league_mean: float | None) -> float | None:
        # The owner's mean bid over the league's mean — but only where the
        # league mean is a positive number.  A league where every claim
        # cleared at $0 has no price to be "above"; dividing by it is
        # undefined, not 1.0.
        if owner_mean is None or not league_mean:
            return None
        return round(owner_mean / league_mean, 4)

    win_mean = priors.owner_win_mean_pct.get(owner_id) if win_n else None
    att_mean = priors.owner_attempt_mean_pct.get(owner_id) if att_n else None
    factor, low_sample = owner_aggression_factor(priors, owner_id)
    return {
        "state": STATE_MEASURED if (win_n or att_n) else STATE_INSUFFICIENT,
        "sampleSize": att_n or win_n,
        "window": {"seasons": list(priors.seasons)},
        "winningBids": {
            "state": STATE_MEASURED if win_n else STATE_INSUFFICIENT,
            "sampleSize": win_n,
            "meanPctOfBudget": round(win_mean, 3) if win_mean is not None else None,
            "ratioToLeagueMeanClearingPct": _ratio(win_mean, clearing_mean),
        },
        "resolvedBids": {
            "state": STATE_MEASURED if att_n else STATE_INSUFFICIENT,
            "sampleSize": att_n,
            "failedBids": failed if att_n else None,
            "failedShare": _share(failed, att_n),
            "meanPctOfBudget": round(att_mean, 3) if att_mean is not None else None,
            "ratioToLeagueMeanBidPct": _ratio(att_mean, attempt_mean),
        },
        # What the FAAB bid predictor (#1146) actually applies for this
        # manager — the validated owner's factor, not a second estimate.
        "predictor": {
            "owner": "src.trade.faab_history.owner_aggression_factor",
            "factor": round(float(factor), 4),
            "lowSample": bool(low_sample),
        },
    }


def _lineup_block(league_cfg: Any) -> dict[str, Any]:
    stated = getattr(league_cfg, "stated_fields", frozenset()) or frozenset()
    if league_cfg is None or "bestBall" not in stated:
        return {
            "state": STATE_NOT_MEASURED,
            "reason": "league_format_unstated",
            "sampleSize": None,
        }
    if getattr(league_cfg, "best_ball", False):
        return {
            "state": STATE_NOT_APPLICABLE,
            "reason": "best_ball_league_lineups_are_set_automatically",
            "sampleSize": None,
        }
    return {
        "state": STATE_NOT_MEASURED,
        # src/ros/lineup.py solves the OPTIMAL lineup; nothing canonical
        # records the lineup a manager actually set week by week, so there
        # is no history to compare against.
        "reason": "no_canonical_lineup_decision_history",
        "sampleSize": None,
    }


# ── Public entry point ────────────────────────────────────────────────────


def build_manager_scout(
    league_key: str,
    *,
    league_cfg: Any = None,
    current_teams: Iterable[Mapping[str, Any]] | None = None,
    acquisition_path: Path | None = None,
    faab_payload: Mapping[str, Any] | None | bool = False,
    position_lookup: PositionLookup | None | bool = False,
    contract: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """The Manager Scout payload for one league.

    ``current_teams`` is the loaded contract's ``sleeper.teams`` for THIS
    league (display names and current roster ids only).  ``contract`` is that
    same loaded contract, read only for today's canonical values
    (``valueAtToday``); ``None`` makes that block ``unavailable``.  ``faab_payload`` /
    ``position_lookup`` default (``False``) to the canonical loaders; pass
    ``None`` to state the source is absent, or a value to inject one.
    """
    from src.trade import faab_history  # noqa: PLC0415
    from src.trade import market_trade_ledger, waiver_ledger  # noqa: PLC0415

    now = now or datetime.now(timezone.utc)

    # Identity adapter.
    if position_lookup is False:
        position_of, identity_state = default_position_lookup()
    else:
        position_of = position_lookup or None
        identity_state = "available" if position_of else STATE_UNAVAILABLE

    # Trades + waivers — one ledger, two owners.
    if market_trade_ledger.acquisition_store_present(acquisition_path):
        trades = market_trade_ledger.market_trades(league_key, path=acquisition_path)
        claims = waiver_ledger.waiver_claims(league_key, path=acquisition_path)
        ledger_state = "available"
    else:
        trades, claims = [], []
        ledger_state = "acquisition_store_missing"
    value_of = contract_value_lookup(contract)
    board_state = "available" if value_of is not None else "no_board_loaded"
    board_meta = (contract or {}).get("meta") if isinstance(contract, Mapping) else None
    board_as_of = None
    if isinstance(contract, Mapping):
        board_as_of = (
            (board_meta or {}).get("generatedAt") if isinstance(board_meta, Mapping) else None
        ) or contract.get("generatedAt")
    trade_accs, trade_league = _fold_trades(trades, position_of=position_of, value_of=value_of)
    waiver_accs, waiver_league = _fold_waivers(claims, position_of=position_of)

    # FAAB.
    if faab_payload is False:
        faab_payload = faab_history.load_bid_history(league_key)
    if isinstance(faab_payload, Mapping) and faab_payload.get("seasons"):
        priors = faab_history.summarize_bid_history(dict(faab_payload))
        faab_state = "available"
    else:
        priors = None
        faab_state = "bid_history_missing"

    # Who is in the profile set: every current member (so a member with no
    # history is shown as insufficient, not omitted) plus every human the
    # ledgers attribute something to (former members keep their history).
    names: dict[str, str | None] = {}
    current_rid: dict[str, int | None] = {}
    for team in current_teams or []:
        oid = str(team.get("ownerId") or "").strip()
        if not oid:
            continue
        names[oid] = str(team.get("name") or "") or None
        rid = team.get("roster_id", team.get("rosterId"))
        try:
            current_rid[oid] = int(rid) if rid is not None else None
        except (TypeError, ValueError):
            current_rid[oid] = None
    owner_ids = set(names) | set(trade_accs) | set(waiver_accs)
    if priors is not None:
        owner_ids |= {o for o in priors.owner_sample if o}
        owner_ids |= {o for o in priors.owner_attempt_sample if o}

    lineup = _lineup_block(league_cfg)
    managers = []
    for oid in sorted(owner_ids, key=lambda o: (o not in names, (names.get(o) or "").lower(), o)):
        managers.append(
            {
                "ownerId": oid,
                "displayName": names.get(oid),
                "currentMember": oid in names,
                "currentRosterId": current_rid.get(oid),
                "tradeTendencies": _trading_block(
                    trade_accs.get(oid),
                    source_state=ledger_state,
                    names=names,
                    board_as_of=board_as_of,
                    board_state=board_state,
                ),
                "waiverTendencies": _waiver_block(waiver_accs.get(oid), source_state=ledger_state),
                "faabTendencies": _faab_block(oid, priors, source_state=faab_state),
                "lineupTendencies": lineup,
            }
        )

    return {
        "leagueKey": league_key,
        "methodVersion": METHOD_VERSION,
        "privacyClass": PRIVACY_CLASS,
        "generatedAt": now.isoformat(),
        "sources": {
            "trades": {
                "owner": "src.trade.market_trade_ledger.market_trades",
                "state": ledger_state,
                "trades": trade_league["trades"],
                "unattributedSides": trade_league["unattributedSides"],
                "window": _window(
                    [t.get("occurredAtMs") for t in trades], [t.get("season") for t in trades]
                ),
            },
            "waivers": {
                "owner": "src.trade.waiver_ledger.waiver_claims",
                "state": ledger_state,
                "claims": waiver_league["claims"],
                "unattributedClaims": waiver_league["unattributedClaims"],
                "window": _window(
                    [c.get("occurredAtMs") for c in claims], [c.get("season") for c in claims]
                ),
            },
            "faab": {
                "owner": "src.trade.faab_history.summarize_bid_history",
                "state": faab_state,
                "seasons": list(priors.seasons) if priors is not None else [],
                "leagueMeanClearingPct": (
                    round(priors.mean_pct, 3) if priors is not None and priors.sample_size else None
                ),
                "leagueMedianClearingPct": (
                    round(priors.median_pct, 3)
                    if priors is not None and priors.sample_size
                    else None
                ),
                "leagueZeroBidShare": (
                    round(priors.zero_bid_share, 4)
                    if priors is not None and priors.sample_size
                    else None
                ),
                "leagueMeanBidPct": (
                    round(priors.bid_attempt_mean_pct, 3)
                    if priors is not None and priors.bid_attempt_mean_pct is not None
                    else None
                ),
            },
            "identity": {
                "owner": "src.identity.resolution.resolve_canonical_v2",
                "state": identity_state,
            },
            "lineup": lineup,
            "board": {
                "owner": "rankDerivedValue + src.api.pick_value_resolution",
                "state": board_state,
                "asOf": board_as_of,
                "basis": VALUE_BASIS,
            },
        },
        "notIncluded": {
            # Named so a reader does not mistake absence for "no behaviour".
            "otherLeagues": "insider_and_sharp_populations_kept_separate",
            "atTheTimeValues": "trade_history_aging_not_authorized",
            "valueAdjustment": "raw_value_sum_only_no_package_method",
            "ageProfile": "no_canonical_age_at_transaction_owner",
        },
        "limitations": {
            # Upstream attribution, not this module's: both the acquisition
            # collector (scripts/build_acquisition_ledger.py, _owner_by_roster)
            # and the FAAB history fetch (src/trade/faab_history.py, the
            # roster_to_owner map) attribute a season's transactions through
            # the roster->owner map as Sleeper reports it WHEN FETCHED.  A
            # mid-season takeover therefore credits the departed manager's
            # earlier moves in that season to the incoming one.  Across
            # seasons attribution is correct (each season's own map).
            "withinSeasonTakeover": "attributed_to_owner_at_fetch_time",
        },
        "managers": managers,
    }


# ── Per-process memo ──────────────────────────────────────────────────────

_MEMO_LOCK = threading.Lock()
_MEMO: dict[tuple, tuple[float, dict[str, Any]]] = {}
_MEMO_TTL_SECONDS = 300.0


def _stat_sig(path: Path | None) -> tuple[Any, ...]:
    if path is None:
        return (None,)
    try:
        st = os.stat(path)
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return (None,)


def cached_manager_scout(
    league_key: str,
    *,
    league_cfg: Any = None,
    current_teams: list[Mapping[str, Any]] | None = None,
    contract: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """``build_manager_scout`` memoised for 5 minutes per league + input
    file signatures (acquisition ledger incl. WAL, bid history, directory)
    + the loaded board's identity (a new scrape is a new board).
    """
    import time  # noqa: PLC0415

    from src.retention.evidence_store import RETENTION_DIR  # noqa: PLC0415
    from src.trade import faab_history  # noqa: PLC0415

    acq = Path(RETENTION_DIR) / "acquisition.sqlite"
    try:
        from src.public_league import snapshot_store  # noqa: PLC0415

        directory_path: Path | None = Path(snapshot_store.NFL_PLAYERS_PATH)
    except Exception:  # noqa: BLE001
        directory_path = None
    teams_sig = tuple(
        (
            str(t.get("ownerId") or ""),
            str(t.get("name") or ""),
            t.get("roster_id", t.get("rosterId")),
        )
        for t in (current_teams or [])
    )
    board_meta = (contract or {}).get("meta") if isinstance(contract, Mapping) else None
    board_sig = (
        id(contract),
        (board_meta or {}).get("generatedAt") if isinstance(board_meta, Mapping) else None,
    )
    key = (
        league_key,
        _stat_sig(acq),
        _stat_sig(Path(str(acq) + "-wal")),
        _stat_sig(faab_history.history_path(league_key)),
        _stat_sig(directory_path),
        teams_sig,
        board_sig,
    )
    now = time.monotonic()
    with _MEMO_LOCK:
        hit = _MEMO.get(key)
        if hit is not None and now - hit[0] < _MEMO_TTL_SECONDS:
            return hit[1]
    payload = build_manager_scout(
        league_key, league_cfg=league_cfg, current_teams=current_teams, contract=contract
    )
    with _MEMO_LOCK:
        for stale in [k for k in _MEMO if k[0] == league_key]:
            _MEMO.pop(stale, None)
        _MEMO[key] = (now, payload)
    return payload


def _reset_memo_for_tests() -> None:
    with _MEMO_LOCK:
        _MEMO.clear()
    with _POSITION_CACHE_LOCK:
        _POSITION_CACHE.clear()
