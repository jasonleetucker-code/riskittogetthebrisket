"""Waiver Advisor — one team's add/drop + FAAB read, composed from existing owners.

What this answers
=================
*For this team, who are the best available players, what are they worth, would
they start, what must go to make room, what is the opportunity cost, and what
should I bid?*  One page of evidence per candidate.  It is ADVICE: nothing here
submits, schedules or drafts a waiver claim.

Nothing here is a second owner
==============================
Every number is produced elsewhere and consumed as is.  This module joins,
labels and reports; it does not value, price, bid, rank or decide legality.

=====================================  ==========================================
question                               owner consumed
=====================================  ==========================================
the add pool + standalone FAAB bids    ``src/trade/waiver.py::find_waiver_targets``
                                       (the FAAB engine, ``src/trade/faab_engine.py``,
                                       is the ONLY dollar owner — reached through
                                       that path, never re-derived)
jointly optimal add/drop plan, the     ``src/trade/perfect_waivers.py``
release each add displaces, stop rule  (``build_perfect_waivers``)
canonical dynasty value                ``rankDerivedValue`` on the contract row
value confidence                       ``confidenceBucket`` / ``confidenceLabel``
                                       (``src/api/confidence.py``, stamped on the row)
market reference                       ``src/sources/ktc_market.py::ktc_market_for_row``
                                       (the non-voting KTC Market benchmark; IDP and
                                       uncovered players are UNAVAILABLE, never 0)
league market price                    the FAAB engine's clearing band (expected
                                       winning bid) — a MARKET estimate, never the
                                       team's maximum offer
starting lineup impact                 ``src/ros/lineup.py::solve_optimal_assignment``
                                       over ``data_contract.contract_roster_pools``
                                       (the same pool + objective the contract's
                                       ``optimalLineup`` stamp uses)
forced drop + its cost                 ``src/trade/roster_capacity.py``
                                       (``assess_roster_capacity`` / ``forced_drop_cost``)
replacement level                      ``src/roster_intel/droppability.py::team_droppability``
                                       (``waiverValues`` — the cut-ladder owner's level)
positional scarcity                    ``roster_capacity.league_scarcity`` +
                                       ``displacement.scarcity_multiplier``
contender / rebuilder context          ``src/api/gameplan.py::league_competitive_postures``
                                       (``roster_intel.window.competitive_posture``)
season option value of a FAAB dollar   ``faab_engine.season_option_value``
=====================================  ==========================================

Declared dependencies on unresolved methodology
===============================================
* **Forced-drop selection is owner-held OFF** (``forced_drop_cheapest_legal``,
  owner decision 2026-10-21, ``tests/api/test_forced_drop_hold_locked.py``).
  This module only READS the flag.  The forced-drop cost is always
  ``reported_not_applied``: it never re-orders, filters or prices a candidate.
* **Competitive posture is context only.**  The list bids come from
  ``find_waiver_targets``, which runs the engine at
  ``competitive_status="bubble"`` for every team; the posture is shown beside
  them and changes no number here.
* **The list bids are season-phase aware** (fixed 2026-10-29, IST-7):
  ``find_waiver_targets`` builds its ``LeagueContext`` with the current NFL
  week, in-season state and playoff start, the same context the per-pair bid
  desk (``/api/waiver/faab-recommend``) uses.  Until then every list bid ran
  with the OFFSEASON option value.  The payload still states which option value
  each number ran under.
* **No championship-probability premium.**  Sim calibration is unverified; no
  playoff or title probability enters anything here.
* **Lineup impact is on the canonical dynasty board** (``rankDerivedValue``),
  the objective the contract's ``optimalLineup`` stamp uses — not a weekly
  points projection.  Labelled on every candidate.

Missing is never zero
=====================
Every absent quantity is ``None`` with a ``state`` / ``reason`` beside it: an
unpriced player, an unknown cap, a ceiling-only bid (no rival model), an
uncovered market reference, an unbuilt posture bundle.

Gate
====
The feature flag is ``waiver_advisor`` (proposed; NOT registered by this
change — see the coordinator hook in the PR).  :func:`advisor_enabled` fails
CLOSED while the flag is unregistered, so the route hook cannot serve the
advisor by accident.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

__all__ = [
    "ADVISOR_VERSION",
    "DEFAULT_LIMIT",
    "FLAG",
    "MAX_LIMIT",
    "advisor_enabled",
    "assemble_waiver_advisor",
    "compute_waiver_advisor",
    "parse_advisor_request",
]

ADVISOR_VERSION = "waiver-advisor/2026-10-27.v1"
FLAG = "waiver_advisor"
DEFAULT_LIMIT = 25
MAX_LIMIT = 100

_POSITION_FILTERS = frozenset({"ALL", "QB", "RB", "WR", "TE", "DL", "LB", "DB"})
_FAMILY = {
    "DT": "DL",
    "DE": "DL",
    "EDGE": "DL",
    "NT": "DL",
    "ILB": "LB",
    "OLB": "LB",
    "MLB": "LB",
    "CB": "DB",
    "S": "DB",
    "FS": "DB",
    "SS": "DB",
}

#: Why the forced-drop cost is never applied, stamped on every candidate.
FORCED_DROP_APPLICATION = "reported_not_applied"
POSTURE_APPLICATION = "context_only_not_applied_to_bids_or_ranking"
LINEUP_OBJECTIVE = "rankDerivedValue (canonical dynasty board; not a weekly projection)"
#: The competitive status ``find_waiver_targets`` hands the engine for every team.
LIST_BID_COMPETITIVE_STATUS = "bubble"


def advisor_enabled() -> bool:
    """Is the advisor switched on?  Fails CLOSED if the flag cannot be read.

    The flag name is a LITERAL (not ``FLAG``) so the reachability scan in
    ``tests/api/test_feature_flag_reachability.py`` can see the gate."""
    from src.api import feature_flags  # noqa: PLC0415

    try:
        return bool(feature_flags.is_enabled("waiver_advisor"))
    except KeyError:
        return False


def parse_advisor_request(body: Mapping[str, Any] | None) -> dict[str, Any]:
    """Normalise the route body: ``{teamOwnerId, position, limit}``.

    Unknown or malformed values fall back to the documented defaults rather
    than raising; ``teamOwnerId`` stays ``None`` when absent (the route answers
    ``team_required`` — a team is never guessed).
    """
    body = body if isinstance(body, Mapping) else {}
    owner = str(body.get("teamOwnerId") or "").strip() or None
    position = str(body.get("position") or "ALL").strip().upper()
    if position not in _POSITION_FILTERS:
        position = "ALL"
    raw_limit = body.get("limit")
    try:
        limit = int(raw_limit) if raw_limit is not None and not isinstance(raw_limit, bool) else 0
    except (TypeError, ValueError):
        limit = 0
    if limit <= 0:
        limit = DEFAULT_LIMIT
    return {"teamOwnerId": owner, "position": position, "limit": min(limit, MAX_LIMIT)}


# ── small helpers ────────────────────────────────────────────────────


def _norm(s: Any) -> str:
    return str(s or "").strip().lower()


def _num(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v)


def _round(v: float | None, nd: int = 1) -> float | None:
    return None if v is None else round(float(v), nd)


def _family(position: str) -> str:
    pos = str(position or "").strip().upper()
    return _FAMILY.get(pos, pos)


def _board_rows_by_name(contract: Mapping[str, Any] | None) -> dict[str, list[Mapping[str, Any]]]:
    """Non-pick board rows keyed by every name field (Perfect Waivers' join)."""
    out: dict[str, list[Mapping[str, Any]]] = {}
    for row in (contract or {}).get("playersArray") or []:
        if not isinstance(row, Mapping) or str(row.get("assetClass") or "").lower() == "pick":
            continue
        for f in ("displayName", "canonicalName", "legacyRef"):
            key = _norm(row.get(f))
            if key:
                bucket = out.setdefault(key, [])
                if not any(b is row for b in bucket):
                    bucket.append(row)
    return out


def _join_board_row(
    cand: Mapping[str, Any], rows_by_name: Mapping[str, list[Mapping[str, Any]]]
) -> tuple[Mapping[str, Any] | None, str | None]:
    """The ONE board row for a waiver-pool name, or ``(None, reason)``.

    The waiver pool returns NAMES.  A name alone is not an identity, so the
    join needs name AND position to single out exactly one board player — the
    rule ``perfect_waivers.build_perfect_waivers`` applies to the same pool.
    Anything else is reported, never guessed.
    """
    named = rows_by_name.get(_norm(cand.get("name"))) or []
    if not named:
        return None, "not_on_board"
    pos = str(cand.get("position") or "").strip().upper()
    matches = [b for b in named if str(b.get("position") or "").strip().upper() == pos]
    identities = {str(b.get("playerId") or id(b)) for b in matches}
    if len(identities) != 1:
        return None, "identity_ambiguous"
    return matches[0], None


# ── FAAB block (engine numbers, labelled) ────────────────────────────


def _faab_block(cand: Mapping[str, Any], methodology: str | None) -> dict[str, Any]:
    """The engine's standalone bid numbers for one candidate, kept apart.

    ``expectedWinningBid`` is a MARKET estimate (the engine's modelled clearing
    band) and ``maxRationalBid`` is THIS team's ceiling — two different
    quantities.  In ceiling-only mode no rival model ran, so the market half is
    UNAVAILABLE rather than invented.
    """
    bid = cand.get("bid") if isinstance(cand.get("bid"), Mapping) else None
    recommended = _num(bid.get("reasonable")) if bid else None
    market_aware = methodology == "market_aware"
    if recommended is None:
        state = "unavailable"
        reason = "engine_returned_no_bid"
    elif market_aware:
        state, reason = "market_aware", None
    else:
        state = "ceiling_only"
        reason = "no_team_context_rival_model_not_run"
    low, mid, high = (_num(cand.get(k)) for k in ("clearingLow", "clearing", "clearingHigh"))
    if market_aware and mid is not None:
        expected = {
            "state": "estimated",
            "low": low,
            "median": mid,
            "high": high,
            "basis": "faab_engine_market_clearing_band",
            "meaning": "what the player is expected to cost in this league — a market "
            "estimate, NOT this team's maximum offer",
        }
    else:
        expected = {
            "state": "unavailable",
            "reason": "ceiling_only_no_rival_model" if not market_aware else "engine_no_clearing",
            "low": None,
            "median": None,
            "high": None,
        }
    max_rational = _num(cand.get("maxRational")) if market_aware else None
    return {
        "state": state,
        "reason": reason,
        "methodology": methodology,
        "basis": "faab_engine_standalone_no_drop_side",
        "recommendedBid": recommended,
        "conservativeBid": _num(bid.get("lowball")) if bid else None,
        "aggressiveBid": _num(bid.get("aggressive")) if bid else None,
        "expectedWinningBid": expected,
        "maxRationalBid": {
            "state": "available" if max_rational is not None else "unavailable",
            "value": max_rational,
            "meaning": "the most this team could rationally pay (bounded by its balance)",
        },
        "objectiveDollars": _num(cand.get("objectiveDollars")) if market_aware else None,
        "confidence": cand.get("confidence") if market_aware else None,
    }


# ── lineup (exact solver over the contract's own pool) ───────────────


class _LineupContext:
    """The team's lineup pool + slots, built once per request."""

    def __init__(self, contract: Mapping[str, Any], team: Mapping[str, Any]) -> None:
        from src.api.data_contract import (  # noqa: PLC0415
            contract_roster_pools,
            contract_slot_eligibility,
            roster_pool_key,
        )
        from src.ros.lineup import solve_optimal_assignment  # noqa: PLC0415

        self._solve = solve_optimal_assignment
        self.state = "evaluated"
        self.reason: str | None = None
        self.pool: list[Any] = []
        self.slots: list[str] = []
        self.eligibility: Any = None
        self.baseline_ids: set[str] = set()
        self.baseline_total = 0.0
        try:
            pools, slots, _source = contract_roster_pools(dict(contract))
        except Exception as exc:  # noqa: BLE001 — lineup is one field, never the page
            self.state, self.reason = "unavailable", f"roster_pools_failed:{type(exc).__name__}"
            return
        teams = (contract.get("sleeper") or {}).get("teams") or []
        key = None
        for index, t in enumerate(teams):
            if t is team or (
                isinstance(t, Mapping)
                and str(t.get("ownerId") or "") == str(team.get("ownerId") or "")
                and t.get("roster_id") == team.get("roster_id")
            ):
                key = roster_pool_key(teams, index, t)
                break
        if key is None or key not in pools:
            self.state, self.reason = "unavailable", "team_pool_not_found"
            return
        if not slots:
            self.state, self.reason = "unavailable", "starter_slots_unknown"
            return
        self.pool = list(pools[key])
        self.slots = list(slots)
        # The SAME eligibility source ``contract_roster_pools`` builds the roster
        # pool from (``sleeper.positions`` / ``sleeper.fantasyPositions``, keyed
        # by name), so a free agent is seated by the owner's rule, not a second one.
        sleeper = contract.get("sleeper") if isinstance(contract.get("sleeper"), Mapping) else {}
        pos_map = sleeper.get("positions")
        elig_map = sleeper.get("fantasyPositions")
        self.positions = pos_map if isinstance(pos_map, Mapping) else {}
        self.fantasy_positions = elig_map if isinstance(elig_map, Mapping) else {}
        self.eligibility = contract_slot_eligibility(dict(contract)) or None
        base = self._solve(self.pool, self.slots, slot_eligibility=self.eligibility)
        self.baseline_ids = {p.player_id for p in base.values()}
        self.baseline_total = sum(float(p.ros_value or 0.0) for p in base.values())
        self._by_id = {p.player_id: p for p in self.pool}

    def impact(self, row: Mapping[str, Any], name: str, value: float) -> dict[str, Any]:
        if self.state != "evaluated":
            return {"state": self.state, "reason": self.reason, "objective": LINEUP_OBJECTIVE}
        from src.ros.lineup import RosterPlayer, lineup_position  # noqa: PLC0415

        fa_id = f"fa:{name}"
        # The owner's rule, exactly (``contract_roster_pools``): position from
        # ``sleeper.positions``, eligibility from ``sleeper.fantasyPositions``,
        # both by name, and NO board-row fallback.  A name the position map
        # does not carry is an UNKNOWN position: this candidate's lineup
        # impact is unavailable, never seated by a second rule.  (Measured on
        # the 2026-10-25 board: 266 of 276 free agents are in the map; the 10
        # that are not are mostly unsigned / college rookies.)
        position = str(self.positions.get(name) or "").strip()
        if not position:
            return {
                "state": "unavailable",
                "reason": "candidate_position_unknown",
                "objective": LINEUP_OBJECTIVE,
            }
        fantasy = self.fantasy_positions.get(name)
        cand = RosterPlayer(
            player_id=fa_id,
            canonical_name=name,
            position=lineup_position(position),
            ros_value=float(value),
            fantasy_positions=tuple(
                lineup_position(str(fp))
                for fp in (fantasy if isinstance(fantasy, (list, tuple)) else ())
                if str(fp).strip()
            ),
        )
        after = self._solve([*self.pool, cand], self.slots, slot_eligibility=self.eligibility)
        slot_of = {p.player_id: self.slots[i] for i, p in after.items()}
        after_ids = set(slot_of)
        enters = fa_id in after_ids
        displaced = sorted(self.baseline_ids - after_ids)
        total_after = sum(float(p.ros_value or 0.0) for p in after.values())
        out_rows = []
        for pid in displaced:
            p = self._by_id.get(pid)
            out_rows.append(
                {
                    "name": p.canonical_name if p else pid,
                    "position": p.position if p else "",
                    "value": _round(p.ros_value if p else None),
                }
            )
        return {
            "state": "evaluated",
            "objective": LINEUP_OBJECTIVE,
            "entersOptimalLineup": enters,
            "slot": slot_of.get(fa_id),
            "leavesLineup": out_rows,
            "startingValueDelta": _round(total_after - self.baseline_total),
        }


# ── capacity (forced drop, reported not applied) ─────────────────────


def _capacity_block(cap_ctx: Any, name: str) -> dict[str, Any]:
    from src.trade.roster_capacity import (  # noqa: PLC0415
        assess_roster_capacity,
        forced_drop_cost,
    )

    if cap_ctx is None:
        return {
            "state": "unavailable",
            "reason": "capacity_context_unavailable",
            "application": FORCED_DROP_APPLICATION,
        }
    capacity = assess_roster_capacity(cap_ctx, incoming_players=[name])
    cost, basis = forced_drop_cost(capacity)
    requires = capacity.requires_drops
    return {
        "state": "unknown" if requires is None else capacity.certainty,
        "rosterLimit": capacity.roster_limit,
        "openSpotsBefore": capacity.open_spots_before,
        "requiresDrops": requires,
        "forcedDrops": [
            {
                "name": d.name,
                "position": d.position,
                "value": _round(d.value),
                "releaseCost": _round(d.release_cost),
                "valueBasis": d.value_basis,
                "rung": d.rung,
            }
            for d in capacity.forced_drops
        ],
        "forcedDropsAreUpperBound": capacity.certainty != "exact",
        "unpricedForcedDrops": capacity.unpriced_forced_drops,
        "ladderExhausted": capacity.ladder_exhausted,
        "forcedDropCost": _round(cost),
        "forcedDropCostBasis": basis,
        "application": FORCED_DROP_APPLICATION,
    }


# ── posture (context only) ────────────────────────────────────────────


def _posture_block(
    postures: Mapping[str, Any] | None,
    meta: Mapping[str, Any] | None,
    owner_id: str,
    unavailable_reason: str | None,
) -> dict[str, Any]:
    base = {"application": POSTURE_APPLICATION, "owner": "src/roster_intel/window.py"}
    if unavailable_reason is not None:
        return {**base, "state": "unavailable", "reason": unavailable_reason}
    posture = (postures or {}).get(str(owner_id))
    if posture is None:
        return {**base, "state": "unavailable", "reason": "team_not_in_posture_bundle"}
    d = posture.to_dict() if hasattr(posture, "to_dict") else dict(posture)
    return {
        **base,
        "state": "available",
        "label": d.get("label"),
        "evidence": d.get("evidence"),
        "confidence": d.get("confidence"),
        "probabilities": d.get("probabilities"),
        "paramsVersion": d.get("paramsVersion"),
        "parameterStatus": d.get("parameterStatus"),
        "bundleFreshness": (meta or {}).get("bundleFreshness"),
    }


# ── season option value (the engine's own function) ───────────────────


def _season_option(
    *,
    league_budget: int,
    team_count: int,
    starters_per_team: int,
    balance: int | None,
) -> dict[str, Any]:
    """The option value the LIST bids ran under, and the one the desk applies.

    Since IST-7 (2026-10-29) ``find_waiver_targets`` passes the current week, so
    both contexts are the same in-season context; they are still computed
    separately so a future divergence shows instead of hiding.
    """
    from src.trade import faab_engine as engine  # noqa: PLC0415

    team = engine.TeamContext(
        faab_remaining=max(0, int(balance or 0)),
        competitive_status=LIST_BID_COMPETITIVE_STATUS,
    )
    week, in_season = engine.current_nfl_week()
    list_league = engine.LeagueContext(
        original_budget=int(league_budget),
        team_count=int(team_count),
        starters_per_team=int(starters_per_team),
        current_week=week,
        in_season=bool(in_season),
    )
    list_factor, list_reason = engine.season_option_value(list_league, team)
    desk_league = engine.LeagueContext(
        original_budget=int(league_budget),
        team_count=int(team_count),
        starters_per_team=int(starters_per_team),
        current_week=week,
        in_season=bool(in_season),
    )
    desk_factor, desk_reason = engine.season_option_value(desk_league, team)
    return {
        "owner": "src/trade/faab_engine.py::season_option_value",
        "currentWeek": week,
        "inSeason": bool(in_season),
        "listBids": {
            "factor": round(list_factor, 3),
            "reason": list_reason,
            "note": "find_waiver_targets passes the current NFL week (fixed 2026-10-29), "
            "the same season phase the bid desk uses",
        },
        "bidDesk": {"factor": round(desk_factor, 3), "reason": desk_reason},
        "competitiveStatusUsed": LIST_BID_COMPETITIVE_STATUS,
    }


# ── market reference ───────────────────────────────────────────────────


def _market_reference(row: Mapping[str, Any]) -> dict[str, Any]:
    from src.sources.ktc_market import ktc_market_for_row  # noqa: PLC0415

    market = ktc_market_for_row(row)
    available = bool(market.get("available")) and _num(market.get("value")) is not None
    return {
        "source": "ktc_market_benchmark_non_voting",
        "state": "available" if available else "unavailable",
        "reason": None if available else (market.get("reason") or "no_ktc_coverage"),
        "value": _num(market.get("value")) if available else None,
        "normalizedValue": _num(market.get("normalizedValue")) if available else None,
        "rank": market.get("rank") if available else None,
    }


# ── assembly ───────────────────────────────────────────────────────────


def _plan_index(
    perfect: Mapping[str, Any] | None,
) -> tuple[dict[str, Mapping[str, Any]], Mapping[str, Any] | None]:
    plan = (perfect or {}).get("plan") or {}
    by_id: dict[str, Mapping[str, Any]] = {}
    for mv in plan.get("moves") or []:
        add = mv.get("add") or {}
        if add.get("playerId") is not None:
            by_id[str(add["playerId"])] = mv
    nxt = ((perfect or {}).get("stopRule") or {}).get("nextBestMove")
    return by_id, nxt


def _plan_block(
    player_id: str, moves: Mapping[str, Mapping[str, Any]], nxt: Mapping[str, Any] | None
) -> dict[str, Any]:
    mv = moves.get(player_id)
    if mv is not None:
        return {
            "status": "in_plan",
            "release": mv.get("release"),
            "gain": mv.get("gain"),
            "material": mv.get("material"),
            "standsAlone": mv.get("standsAlone"),
        }
    if nxt and str((nxt.get("add") or {}).get("playerId")) == player_id:
        return {
            "status": "next_best_move",
            "release": nxt.get("release"),
            "gain": nxt.get("gain"),
            "reason": nxt.get("reason"),
        }
    return {
        "status": "not_in_plan",
        "reason": "the jointly optimal plan stops before this add (perfect_waivers stop rule)",
    }


def assemble_waiver_advisor(
    contract: Mapping[str, Any],
    *,
    league_key: str | None,
    owner_id: str,
    waiver_targets: Mapping[str, Any] | None,
    perfect_waivers: Mapping[str, Any] | None,
    droppability: Mapping[str, Any] | None,
    capacity_context: Any,
    scarcity: Mapping[str, Any] | None,
    scarcity_reason: str | None,
    postures: Mapping[str, Any] | None,
    posture_meta: Mapping[str, Any] | None,
    posture_unavailable_reason: str | None,
    faab_inputs: Mapping[str, Any],
    forced_drop_selection_enabled: bool,
    position: str = "ALL",
    limit: int = DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Join the owners' outputs into one advisor payload.  No I/O, no clock
    beyond the engine's own season clock.

    ``contract`` must carry the roster snapshot every owner was run on (the
    route hands all of them the same ``plan_contract``).
    """
    from src.draft.context import contract_teams, match_team  # noqa: PLC0415
    from src.draft.displacement import scarcity_multiplier  # noqa: PLC0415

    teams = contract_teams(contract)
    if not teams:
        raise ValueError("no_rosters_loaded")
    team = match_team(teams, owner_id=owner_id, roster_id=None, team_name=None)
    if team is None:
        raise ValueError("unknown_team")

    notes: list[str] = []
    targets = waiver_targets if isinstance(waiver_targets, Mapping) else {}
    methodology = targets.get("bidMethodology")
    if methodology != "market_aware":
        notes.append(
            "FAAB bids are the ceiling-only estimate (no rival model ran) — expected "
            "winning bid and max rational bid are unavailable, not zero"
        )
    waiver_levels = (droppability or {}).get("waiverValues") or {}
    if not waiver_levels:
        notes.append("replacement (waiver) levels unavailable — no value-over-waiver is stated")
    if scarcity is None:
        notes.append(f"positional scarcity unavailable — {scarcity_reason or 'not supplied'}")

    rows_by_name = _board_rows_by_name(contract)
    moves, nxt = _plan_index(perfect_waivers)
    lineup = _LineupContext(contract, team)
    if lineup.state != "evaluated":
        notes.append(f"lineup impact unavailable ({lineup.reason})")

    excluded: dict[str, int] = {}
    seen: set[str] = set()
    joined: list[tuple[Mapping[str, Any], Mapping[str, Any]]] = []
    for items in (targets.get("by_position") or {}).values():
        for cand in items or []:
            if not isinstance(cand, Mapping):
                continue
            row, why = _join_board_row(cand, rows_by_name)
            if row is None:
                excluded[why or "unjoined"] = excluded.get(why or "unjoined", 0) + 1
                continue
            value = _num(row.get("rankDerivedValue"))
            if value is None or value <= 0:
                excluded["unpriced"] = excluded.get("unpriced", 0) + 1
                continue
            pid = str(row.get("playerId") or cand.get("name"))
            if pid in seen:
                continue
            seen.add(pid)
            joined.append((cand, row))

    joined.sort(key=lambda cr: (-float(cr[1]["rankDerivedValue"]), _norm(cr[1].get("displayName"))))
    eligible = [
        cr for cr in joined if position == "ALL" or _family(cr[1].get("position")) == position
    ]
    shown = eligible[: max(1, int(limit))]

    candidates: list[dict[str, Any]] = []
    for cand, row in shown:
        name = str(row.get("displayName") or cand.get("name") or "")
        pos = str(row.get("position") or cand.get("position") or "").upper()
        value = float(row["rankDerivedValue"])
        pid = str(row.get("playerId") or "") or None
        level = _num(waiver_levels.get(pos)) if isinstance(waiver_levels, Mapping) else None
        sc = (scarcity or {}).get(pos) if isinstance(scarcity, Mapping) else None
        candidates.append(
            {
                "playerId": pid,
                "name": name,
                "position": pos,
                "positionFamily": _family(pos),
                "age": _num(row.get("age")),
                "rank": row.get("canonicalConsensusRank"),
                "isRookie": bool(cand.get("isRookie")),
                "value": {
                    # the canonical dynasty value, READ from the contract row; named
                    # apart from the canonical field so this composer never constructs it
                    "canonicalValue": _round(value, 0),
                    "confidenceBucket": row.get("confidenceBucket"),
                    "confidenceLabel": row.get("confidenceLabel"),
                },
                "marketReference": _market_reference(row),
                "replacement": {
                    "state": "available" if level is not None else "unavailable",
                    "waiverLevel": _round(level, 0),
                    "valueOverWaiverLevel": _round(value - level, 0) if level is not None else None,
                    "scarcityMultiplier": (
                        round(scarcity_multiplier(sc), 3) if scarcity is not None else None
                    ),
                    "owner": "src/roster_intel/droppability.py::team_droppability.waiverValues",
                },
                "lineup": lineup.impact(row, name, value),
                "plan": _plan_block(str(row.get("playerId") or name), moves, nxt),
                "capacity": _capacity_block(capacity_context, name),
                "faab": _faab_block(cand, methodology),
            }
        )

    perfect = perfect_waivers if isinstance(perfect_waivers, Mapping) else {}
    budget = perfect.get("budget") or {}
    raw_balance = team.get("faabRemaining")
    balance = int(raw_balance) if isinstance(raw_balance, int) and raw_balance >= 0 else None
    league_budget = int(faab_inputs.get("league_budget") or 100)
    history_state = "available" if faab_inputs.get("market_priors") else "missing"

    return {
        "version": ADVISOR_VERSION,
        "flag": FLAG,
        "leagueKey": league_key,
        "advisoryOnly": True,
        "valueScale": "rankDerivedValue",
        "team": {
            "ownerId": str(team.get("ownerId") or ""),
            "name": str(team.get("name") or ""),
            "rosterId": team.get("roster_id"),
        },
        "filters": {"position": position, "limit": int(limit)},
        "candidates": candidates,
        "census": {
            "poolCandidates": len(joined),
            "matchingFilter": len(eligible),
            "shown": len(candidates),
            "excluded": dict(sorted(excluded.items())),
        },
        "faab": {
            "state": "known" if balance is not None else "unknown",
            "remaining": balance,
            "originalBudget": league_budget,
            "bidMethodology": methodology,
            "seasonOption": _season_option(
                league_budget=league_budget,
                team_count=int(faab_inputs.get("team_count") or 12),
                starters_per_team=int(faab_inputs.get("starters_per_team") or 20),
                balance=balance,
            ),
            "bidHistory": {
                "state": history_state,
                "source": f"data/faab/bid_history_{league_key}.json",
            },
            "crowdEvidence": {
                "state": "evaluated_per_pair_in_bid_desk",
                "owner": "/api/waiver/faab-recommend (crowdMarket)",
            },
            "planBudget": budget or None,
        },
        "posture": _posture_block(postures, posture_meta, owner_id, posture_unavailable_reason),
        "plan": {
            "owner": "src/trade/perfect_waivers.py",
            "available": bool(perfect),
            "summary": perfect.get("plan"),
            "solver": perfect.get("solver"),
            "stopRule": perfect.get("stopRule"),
            "capacity": perfect.get("capacity"),
            "requiredStartersToday": perfect.get("requiredStartersToday"),
            "unpriced": perfect.get("unpriced"),
        },
        "replacementLevels": {
            "state": "available" if waiver_levels else "unavailable",
            "byPosition": dict(waiver_levels) if waiver_levels else {},
            "scarcityState": "available" if scarcity is not None else "unavailable",
        },
        "forcedDropPolicy": {
            "selectionFlag": "forced_drop_cheapest_legal",
            "selectionEnabled": bool(forced_drop_selection_enabled),
            "application": FORCED_DROP_APPLICATION,
            "note": "forced-drop cost is shown for every add and never re-orders, filters "
            "or prices a candidate; selection activation is owner-held",
        },
        "methodologyDependencies": [
            {"id": "forced_drop_activation", "state": "owner_held_off"},
            {"id": "posture_in_faab_engine", "state": "not_wired_context_only"},
            {"id": "list_bid_season_phase", "state": "current_week_applied"},
            {"id": "championship_probability_premium", "state": "not_used_sim_uncalibrated"},
            {"id": "lineup_objective", "state": "dynasty_board_value_not_weekly_projection"},
        ],
        "notes": notes + list(perfect.get("notes") or []),
    }


def compute_waiver_advisor(
    plan_contract: Mapping[str, Any],
    *,
    league_key: str,
    owner_id: str,
    inputs: Mapping[str, Any],
    constraints: Any = None,
    position: str = "ALL",
    limit: int = DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Run every owner once on ONE roster snapshot and assemble the payload.

    ``inputs`` is ``server._waiver_engine_inputs(...)``'s dict — the SAME
    budget / rosters / bid history ``/api/waiver/suggestions`` and
    ``/api/waiver/perfect`` use, so the three cannot disagree about a bid.
    Raises ``ValueError("unknown_team")`` / ``ValueError("no_rosters_loaded")``.
    """
    from src.api.league_registry import get_scoring_profile  # noqa: PLC0415
    from src.draft.context import contract_teams, match_team  # noqa: PLC0415
    from src.roster_intel.droppability import TeamNotInLeague, team_droppability  # noqa: PLC0415
    from src.trade import forced_drop_selection  # noqa: PLC0415
    from src.trade import perfect_waivers as perfect  # noqa: PLC0415
    from src.trade import waiver as waiver_owner  # noqa: PLC0415
    from src.trade.roster_capacity import build_capacity_context, league_scarcity  # noqa: PLC0415

    teams = contract_teams(plan_contract)
    if not teams:
        raise ValueError("no_rosters_loaded")
    team = match_team(teams, owner_id=owner_id, roster_id=None, team_name=None)
    if team is None:
        raise ValueError("unknown_team")

    targets = waiver_owner.find_waiver_targets(
        dict(plan_contract),
        inputs.get("teams"),
        per_position_limit=1_000_000,
        league_budget=inputs.get("league_budget"),
        team_count=inputs.get("team_count"),
        starters_per_team=inputs.get("starters_per_team"),
        team_owner_id=owner_id,
        starters=inputs.get("starters"),
        roster_size=inputs.get("roster_size"),
        market_priors=inputs.get("market_priors"),
    )
    plan = perfect.build_perfect_waivers(
        plan_contract,
        league_key=league_key,
        owner_id=owner_id,
        waiver_targets=targets,
        constraints=constraints,
        roster_settings=inputs.get("roster_settings"),
    )
    try:
        dropp = team_droppability(plan_contract, owner_id=owner_id)
    except TeamNotInLeague as exc:
        raise ValueError("unknown_team") from exc

    scarcity, scarcity_reason = league_scarcity(league_key, plan_contract)
    cap_ctx = build_capacity_context(
        plan_contract,
        league_key,
        team,
        roster_settings=dict(inputs.get("roster_settings") or {}) or None,
        scarcity_reading=(scarcity, scarcity_reason),
    )

    postures: Mapping[str, Any] | None = None
    posture_meta: Mapping[str, Any] | None = None
    posture_reason: str | None = None
    try:
        from src.api.gameplan import league_competitive_postures  # noqa: PLC0415

        postures, posture_meta = league_competitive_postures(
            league_key, get_scoring_profile(league_key) or "", plan_contract
        )
    except Exception as exc:  # noqa: BLE001 — posture is context, never the page
        posture_reason = getattr(exc, "reason", None) or f"unavailable:{type(exc).__name__}"

    return assemble_waiver_advisor(
        plan_contract,
        league_key=league_key,
        owner_id=owner_id,
        waiver_targets=targets,
        perfect_waivers=plan,
        droppability=dropp,
        capacity_context=cap_ctx,
        scarcity=scarcity,
        scarcity_reason=scarcity_reason,
        postures=postures,
        posture_meta=posture_meta,
        posture_unavailable_reason=posture_reason,
        faab_inputs=inputs,
        forced_drop_selection_enabled=forced_drop_selection.enabled(),
        position=position,
        limit=limit,
    )
