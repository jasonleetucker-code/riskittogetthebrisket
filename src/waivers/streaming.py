"""Weekly IDP streaming — the composer (IST-6 / IST-8, owner directive 2026-10-29).

One question, answered for one roster: *which defenders should this team add
and drop for the coming week(s), and is that better than doing nothing?*

Everything here is assembly.  Each number comes from its canonical owner:

==========================================  ==================================================
concern                                     owner consumed
==========================================  ==================================================
league-scored weekly projections            :mod:`src.ros.weekly_league_projections`
lineup slots (live host → registry)         :func:`src.ros.lineup.resolve_starter_slots`
the add/drop search and the lineup value    :mod:`src.waivers.streaming_solver`
                                            (``solve_optimal_assignment`` underneath)
who may be dropped, and at what dynasty     :mod:`src.waivers.drop_assessment`
cost
free agents, board identity, FAAB bids      :func:`src.trade.perfect_waivers.free_agent_candidates`
                                            over :func:`src.trade.waiver.find_waiver_targets`
who is rostered anywhere in the league      :func:`src.draft.context.league_rostered_keys`
free-agent dynasty ladder (replacement)     :func:`src.draft.waiver_population.base_free_agent_rows`
open roster spots                           :mod:`src.trade.roster_capacity`
competitive posture (context only)          :func:`src.api.gameplan.league_competitive_postures`
==========================================  ==================================================

Units never mix.  Every plan reports three separate quantities: projected
lineup points gained (the objective), the dynasty value change exactly as the
directive defines it (``Σ V(adds) − Σ V(drops)``, reported, never optimised),
and FAAB dollars.

The dynasty budget
------------------
The optimiser's dynasty constraint is on what a release actually costs:
``max(0, V(drop) − replacement)``, the value that could not be signed back off
the wire (the drop assessment's ``dynastyCost``).  Several releases at one
position are charged against successively deeper free agents — the ``j``-th
release at a position against the ``j``-th best free agent there (charged at
the deepest rung any plan could need, so the charge is never too low) —
because one free agent cannot replace two players.  An added free agent
credits nothing: he IS the replacement, and crediting him would count the same
value twice.  The default budget is 0: no release may cost dynasty value that
the wire cannot give back.  A positive budget is the manager's explicit choice.

Missing is never zero
---------------------
* A player with no projection for a week is unassignable that week, never a
  0-point starter (``unprojected``); a proven bye is a real 0.
* A rostered player with no projection is listed, so a baseline that cannot
  count him is visible.
* A free agent off the dynasty board has an UNKNOWN dynasty value (credits
  nothing, shown as unknown) and no FAAB engine price; he is offered only as
  a $0 claim and labelled so.
* An unknown FAAB balance allows $0 claims only (the solver's rule).
* An unknown roster limit is treated as no open spot (every add forces a
  drop), and said.

Recommendation and execution are separate: nothing here submits a claim.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from src.waivers import streaming_solver as solver

__all__ = [
    "FLAG",
    "StreamingConfig",
    "StreamingConfigError",
    "assemble_streaming",
    "compute_streaming",
    "load_streaming_config",
    "parse_streaming_request",
]

FLAG = "idp_streaming"
CONTRACT_VERSION = "idp-streaming/2026-10-29.v1"
CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "waivers" / "streaming.json"
MAX_HORIZON_WEEKS = 4
POSITION_FILTERS = ("ALL", "DL", "LB", "DB")
_BOARD_LIMIT = 60


class StreamingConfigError(ValueError):
    """The streaming config is missing or malformed: the feature refuses."""


@dataclass(frozen=True)
class StreamingConfig:
    version: str
    materiality_points: float
    max_capacity: int
    default_capacity: int
    horizon_week_weights: tuple[float, ...]
    node_limit_single_week: int
    node_limit_multiweek: int
    node_limit_curve_row: int
    idp_families: tuple[str, ...]
    config_hash: str


def load_streaming_config(path: Path | str | None = None) -> StreamingConfig:
    """Read ``config/waivers/streaming.json``; refuse rather than default."""
    p = Path(path) if path is not None else CONFIG_PATH
    try:
        raw_text = p.read_text(encoding="utf-8")
        raw = json.loads(raw_text)
    except (OSError, ValueError) as exc:
        raise StreamingConfigError(f"streaming config unreadable: {p}") from exc

    def entry(name: str) -> Any:
        node = raw.get(name) if isinstance(raw, Mapping) else None
        if not isinstance(node, Mapping) or node.get("class") != "PRIOR" or "value" not in node:
            raise StreamingConfigError(f"streaming config entry missing or not a PRIOR: {name}")
        return node["value"]

    try:
        materiality = float(entry("materialityPoints"))
        max_cap = int(entry("maxCapacity"))
        default_cap = int(entry("defaultCapacity"))
        weights = tuple(float(w) for w in entry("horizonWeekWeights"))
        limits = entry("nodeLimits")
        families = tuple(str(f).upper() for f in entry("idpFamilies"))
        single = int(limits["singleWeek"])
        multi = int(limits["multiweek"])
        row = int(limits["capacityCurvePerRow"])
    except (TypeError, ValueError, KeyError) as exc:
        raise StreamingConfigError("streaming config entry has the wrong shape") from exc
    if (
        materiality < 0
        or not 0 <= default_cap <= max_cap <= 10
        or not weights
        or len(weights) > MAX_HORIZON_WEEKS
        or any(w < 0 for w in weights)
        or min(single, multi, row) < 1
        or not families
    ):
        raise StreamingConfigError("streaming config value out of range")
    return StreamingConfig(
        version=str(raw.get("version") or ""),
        materiality_points=materiality,
        max_capacity=max_cap,
        default_capacity=default_cap,
        horizon_week_weights=weights,
        node_limit_single_week=single,
        node_limit_multiweek=multi,
        node_limit_curve_row=row,
        idp_families=families,
        config_hash=hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
    )


def parse_streaming_request(body: Mapping[str, Any] | None, cfg: StreamingConfig) -> dict[str, Any]:
    """Validate the request body.  Raises ``ValueError(code)`` on a bad field."""
    body = body if isinstance(body, Mapping) else {}
    owner = str(body.get("teamOwnerId") or "").strip() or None

    def _int(name: str, lo: int, hi: int, default: int | None) -> int | None:
        v = body.get(name)
        if v is None or v == "":
            return default
        if isinstance(v, bool):
            raise ValueError(f"bad_{name}")
        try:
            out = int(v)
        except (TypeError, ValueError):
            raise ValueError(f"bad_{name}") from None
        if not lo <= out <= hi or float(v) != out:
            raise ValueError(f"bad_{name}")
        return out

    position = str(body.get("position") or "ALL").strip().upper()
    if position not in POSITION_FILTERS:
        raise ValueError("bad_position")
    budget_raw = body.get("dynastyBudget", 0)
    try:
        budget = float(budget_raw if budget_raw not in (None, "") else 0)
    except (TypeError, ValueError):
        raise ValueError("bad_dynastyBudget") from None
    if isinstance(budget_raw, bool) or not 0 <= budget <= 100_000:
        raise ValueError("bad_dynastyBudget")
    curve = body.get("capacityCurve", True)
    if not isinstance(curve, bool):
        raise ValueError("bad_capacityCurve")
    return {
        "teamOwnerId": owner,
        "week": _int("week", 1, 18, None),
        "horizonWeeks": _int("horizonWeeks", 1, len(cfg.horizon_week_weights), 1),
        "position": position,
        "capacity": _int("capacity", 0, cfg.max_capacity, cfg.default_capacity),
        "dynastyBudget": budget,
        "capacityCurve": curve,
    }


# ── helpers ─────────────────────────────────────────────────────────────


def _family(position: Any) -> str:
    from src.ros.lineup import lineup_position  # noqa: PLC0415

    return lineup_position(str(position or "").strip().upper())


def _norm(v: Any) -> str:
    return str(v or "").strip().lower()


def _round(v: float | None, n: int = 2) -> float | None:
    return None if v is None else round(float(v), n)


def _week_points(proj_sets: Sequence[Any], pid: str) -> tuple[tuple[float | None, ...], list[dict]]:
    pts: list[float | None] = []
    detail: list[dict] = []
    for ps in proj_sets:
        row = ps.players.get(pid) if ps is not None else None
        if row is None:
            pts.append(None)
            detail.append(
                {"week": ps.week, "state": "unprojected", "reason": "not_in_projection_set"}
            )
            continue
        pts.append(row.weekly_points)
        detail.append(
            {
                "week": ps.week,
                "points": _round(row.weekly_points),
                "state": row.state,
                "reason": row.reason,
                "opponent": row.opponent,
                "sources": [s.source_key for s in row.sources],
                "combineMethod": row.combine_method,
                "familyCount": row.family_count,
                "coverageShare": (
                    _round(row.coverage.coverage_share, 3) if row.coverage is not None else None
                ),
                "uncoveredKeys": list(row.coverage.uncovered_keys) if row.coverage else [],
                "injuryStatus": row.injury_status,
            }
        )
    return tuple(pts), detail


def _ladders(contract: Mapping[str, Any], rostered: set[str]) -> dict[str, list[float]]:
    """Free-agent dynasty values per position family, best first."""
    from src.draft.waiver_population import base_free_agent_rows  # noqa: PLC0415

    out: dict[str, list[float]] = {}
    for row in base_free_agent_rows(contract, rostered, ()):
        out.setdefault(_family(row.get("position")), []).append(float(row["rankDerivedValue"]))
    for vals in out.values():
        vals.sort(reverse=True)
    return out


def _drop_cost(
    assessment: Any, rung: int, ladder: Sequence[float]
) -> tuple[float | None, float | None]:
    """``(cost, replacement used)``: the larger of the drop assessment's own
    cost and the cost against the ``rung``-th best free agent at his position."""
    value = assessment.dynasty_value
    if value is None or assessment.dynasty_cost is None:
        return None, None
    replacement = ladder[rung - 1] if 0 < rung <= len(ladder) else 0.0
    deep = max(0.0, float(value) - replacement)
    return max(float(assessment.dynasty_cost), deep), replacement


# ── assembly (pure) ─────────────────────────────────────────────────────


def assemble_streaming(
    *,
    league_key: str,
    team: Mapping[str, Any],
    owner_id: str,
    season: int,
    weeks: Sequence[int],
    current_week: int | None,
    projection_sets: Sequence[Any],
    slots: Sequence[str],
    slots_source: str | None,
    board_rows_by_id: Mapping[str, Mapping[str, Any]],
    rostered_keys: set[str],
    drop_assessment: Any,
    fa_bids: Mapping[str, Any],
    fa_bid_methodology: Any,
    ladders: Mapping[str, Sequence[float]],
    faab_remaining: int | None,
    open_spots: int | None,
    open_spots_note: str | None,
    request: Mapping[str, Any],
    cfg: StreamingConfig,
    posture: Mapping[str, Any] | None = None,
    posture_reason: str | None = None,
) -> dict[str, Any]:
    """Join the owners' outputs and run the solver.  No I/O, no clock."""
    families = set(cfg.idp_families)
    if request["position"] != "ALL":
        families = {request["position"]}
    weights = tuple(cfg.horizon_week_weights[: len(projection_sets)])
    notes: list[str] = []

    # ── roster ────────────────────────────────────────────────────────
    roster_ids = [str(i) for i in (team.get("playerIds") or []) if str(i or "").strip()]
    assessments = drop_assessment.by_player_id()
    roster: list[solver.StreamPlayer] = []
    unprojected_roster: list[dict[str, Any]] = []
    roster_meta: dict[str, dict[str, Any]] = {}
    for pid in roster_ids:
        row = board_rows_by_id.get(_norm(pid)) or {}
        proj = next((ps.players.get(pid) for ps in projection_sets if ps.players.get(pid)), None)
        position = (proj.position if proj is not None else None) or row.get("position") or ""
        name = (
            (proj.name if proj is not None else None)
            or row.get("displayName")
            or (assessments[pid].name if pid in assessments else pid)
        )
        pts, detail = _week_points(projection_sets, pid)
        fp = row.get("fantasyPositions")
        roster.append(
            solver.StreamPlayer(
                player_id=pid,
                name=str(name),
                position=str(position).upper(),
                weekly_points=pts,
                fantasy_positions=tuple(fp) if isinstance(fp, (list, tuple)) else (),
            )
        )
        roster_meta[pid] = {"name": str(name), "position": str(position).upper(), "weeks": detail}
        if all(p is None for p in pts) and _family(position) in set(cfg.idp_families):
            unprojected_roster.append({"playerId": pid, "name": str(name), "weeks": detail})

    # ── who may go, and at what cost ─────────────────────────────────
    k = int(request["capacity"])
    droppable: dict[str, dict[str, Any]] = {}
    by_family: dict[str, list[Any]] = {}
    for pid in roster_ids:
        a = assessments.get(pid)
        if a is None or a.drop_class not in ("churn", "conditional"):
            continue
        fam = _family(a.position)
        if fam not in families:
            continue
        by_family.setdefault(fam, []).append(a)
    for fam, members in by_family.items():
        rung = max(1, min(k, len(members)))
        for a in members:
            cost, repl = _drop_cost(a, rung, ladders.get(fam, ()))
            if cost is None:
                continue
            droppable[a.player_id] = {
                "cost": cost,
                "replacementUsed": repl,
                "replacementRung": rung,
                "assessment": a,
            }
    # Roster players carry their release cost as the solver's dynasty value.
    roster = [
        solver.StreamPlayer(
            **{
                **p.__dict__,
                "dynasty_value": droppable[p.player_id]["cost"]
                if p.player_id in droppable
                else None,
            }
        )
        for p in roster
    ]

    # ── free agents ──────────────────────────────────────────────────
    free_agents: list[solver.StreamPlayer] = []
    fa_meta: dict[str, dict[str, Any]] = {}
    seen: set[str] = set()
    for ps in projection_sets:
        for row in ps.players.values():
            pid = str(row.player_id)
            if pid in seen or _norm(pid) in rostered_keys:
                continue
            if _family(row.position) not in families:
                continue
            seen.add(pid)
    for pid in sorted(seen):
        pts, detail = _week_points(projection_sets, pid)
        proj = next((ps.players.get(pid) for ps in projection_sets if ps.players.get(pid)), None)
        board = board_rows_by_id.get(_norm(pid))
        bid_c = fa_bids.get(pid)
        value = board.get("rankDerivedValue") if board else None
        value = float(value) if isinstance(value, (int, float)) and value > 0 else None
        if bid_c is not None:
            bid, bid_basis = int(bid_c.bid), "faab_engine"
        elif value is None:
            bid, bid_basis = 0, "off_board_zero_claim_only"
        else:
            # On the board but not in the priced waiver pool (the pool's own
            # rules excluded him): no engine price, so no paid claim.
            bid, bid_basis = 0, "unpriced_by_engine_zero_claim_only"
        fp = board.get("fantasyPositions") if board else None
        free_agents.append(
            solver.StreamPlayer(
                player_id=pid,
                name=str(
                    proj.name if proj and proj.name else (board or {}).get("displayName") or pid
                ),
                position=str(
                    (proj.position if proj else None) or (board or {}).get("position") or ""
                ).upper(),
                weekly_points=pts,
                dynasty_value=None,  # an add credits nothing against the budget (module docstring)
                fantasy_positions=tuple(fp) if isinstance(fp, (list, tuple)) else (),
                bid=bid,
            )
        )
        fa_meta[pid] = {
            "name": free_agents[-1].name,
            "position": free_agents[-1].position,
            "team": proj.team if proj else None,
            "dynastyValue": _round(value, 0),
            "dynastyValueState": "priced" if value is not None else "unknown_off_board",
            "bid": bid,
            "bidBasis": bid_basis,
            "bidDetail": dict(bid_c.bid_detail) if bid_c is not None else None,
            "weeks": detail,
        }

    multiweek = len(projection_sets) > 1
    node_limit = cfg.node_limit_multiweek if multiweek else cfg.node_limit_single_week
    if open_spots is None:
        notes.append(
            open_spots_note or "roster limit unknown: every add is treated as forcing a drop"
        )
    base_input = solver.SolverInput(
        roster=tuple(roster),
        free_agents=tuple(free_agents),
        slots=tuple(slots),
        droppable_ids=frozenset(droppable),
        open_spots=max(0, int(open_spots or 0)),
        max_adds=k,
        faab_balance=faab_remaining,
        dynasty_budget=float(request["dynastyBudget"]),
        week_weights=weights,
        materiality=cfg.materiality_points,
        node_limit=node_limit,
    )
    result = solver.solve_streaming(base_input)

    curve = None
    recommended_k = None
    if request["capacityCurve"]:
        curve = solver.capacity_curve(
            solver.SolverInput(**{**base_input.__dict__, "node_limit": cfg.node_limit_curve_row}),
            max_k=cfg.max_capacity,
        )
        recommended_k = solver.recommended_capacity(curve, materiality=cfg.materiality_points)

    def explain_plan(plan: solver.StreamPlan | None) -> dict[str, Any] | None:
        if plan is None:
            return None
        add_rows = []
        raw_add = 0.0
        unknown_add = 0
        for a in plan.adds:
            m = fa_meta[a]
            if m["dynastyValue"] is None:
                unknown_add += 1
            else:
                raw_add += float(m["dynastyValue"])
            add_rows.append({"playerId": a, **m})
        drop_rows = []
        raw_drop = 0.0
        for d in plan.drops:
            info = droppable[d]
            a = info["assessment"]
            raw_drop += float(a.dynasty_value or 0.0)
            drop_rows.append(
                {
                    "playerId": d,
                    "name": a.name,
                    "position": a.position,
                    "dropClass": a.drop_class,
                    "dynastyValue": _round(a.dynasty_value, 0),
                    "releaseCost": _round(info["cost"], 0),
                    "replacementValue": _round(info["replacementUsed"], 0),
                    "replacementRung": info["replacementRung"],
                    "reasons": [r.to_dict() for r in a.reasons][:3],
                    "weeks": roster_meta.get(d, {}).get("weeks", []),
                }
            )
        return {
            **plan.to_dict(),
            "addDetails": add_rows,
            "dropDetails": drop_rows,
            # The directive's quantity, reported only: Σ V(adds) − Σ V(drops).
            "dynastyValueChange": {
                "value": round(raw_add - raw_drop, 1),
                "state": "complete" if unknown_add == 0 else "partial_unknown_add_values",
                "unknownAddValues": unknown_add,
            },
            "releaseCost": round(plan.net_dynasty_loss, 1),
        }

    best = explain_plan(result.best)
    no_move_reason = None
    if not result.recommend_move:
        if not droppable and k > 0 and int(open_spots or 0) == 0:
            no_move_reason = "no_droppable_player"
        elif not free_agents:
            no_move_reason = "no_projected_free_agent"
        elif result.alternatives:
            no_move_reason = "below_materiality"
        else:
            no_move_reason = "no_move_improves_the_lineup"

    board = _streaming_board(base_input, fa_meta, result)
    return {
        "contractVersion": CONTRACT_VERSION,
        "leagueKey": league_key,
        "team": {"ownerId": owner_id, "name": team.get("name") or team.get("sleeperTeamName")},
        "season": season,
        "weeks": list(weeks),
        "weekWeights": list(weights),
        "currentWeek": current_week,
        "request": dict(request),
        "config": {
            "version": cfg.version,
            "hash": cfg.config_hash,
            "materialityPoints": cfg.materiality_points,
        },
        "lineup": {"slots": list(slots), "source": slots_source},
        "solver": {
            "version": solver.SOLVER_VERSION,
            "status": result.status,
            "boundGap": _round(result.bound_gap, 3),
            "nodes": result.nodes,
            "nodeLimit": node_limit,
            "notes": list(result.notes),
        },
        "baselinePoints": [_round(p) for p in result.baseline_points],
        "recommendMove": result.recommend_move,
        "noMoveReason": no_move_reason,
        "plan": best,
        "alternatives": [explain_plan(p) for p in result.alternatives],
        "largerBudget": {
            "plan": explain_plan(result.best_unbudgeted),
            "status": result.unbudgeted_status,
            "meaning": "the best plan with the dynasty budget lifted: what a larger budget would buy",
        },
        "capacityCurve": curve,
        "recommendedCapacity": recommended_k,
        "streamingBoard": board,
        "safeToDrop": _drop_board(drop_assessment, droppable, families, roster_meta),
        "faab": {
            "remaining": faab_remaining,
            "state": "known" if faab_remaining is not None else "unknown_zero_claims_only",
            "bidMethodology": fa_bid_methodology,
        },
        "openSpots": open_spots,
        "posture": {
            "context": dict(posture) if posture else None,
            "unavailableReason": posture_reason,
            "use": "displayed for context only; it never raises the dynasty budget",
        },
        "unprojectedRosterPlayers": unprojected_roster,
        "excludedFreeAgents": dict(sorted(result.excluded_free_agents.items())),
        "sources": [ps.to_dict(include_players=False) for ps in projection_sets],
        "notes": notes,
    }


def _streaming_board(
    inp: solver.SolverInput, fa_meta: Mapping[str, Mapping[str, Any]], result: Any
) -> list[dict[str, Any]]:
    """Available defenders ranked by what ONE of them adds to this lineup
    (no drop), not by dynasty value or raw points."""
    ev = solver._Evaluator(inp)
    roster_ids = frozenset(p.player_id for p in inp.roster)
    base = ev.value(roster_ids)
    rows = []
    for p in inp.free_agents:
        if all(v is None for v in p.weekly_points):
            continue
        gain = ev.value(roster_ids | {p.player_id}) - base
        rows.append((gain, p))
    rows.sort(key=lambda t: (-t[0], t[1].player_id))
    out = []
    for gain, p in rows[:_BOARD_LIMIT]:
        m = fa_meta[p.player_id]
        out.append(
            {
                "playerId": p.player_id,
                "name": m["name"],
                "position": m["position"],
                "team": m["team"],
                "soloLineupGainPoints": round(gain, 2),
                "weeks": m["weeks"],
                "dynastyValue": m["dynastyValue"],
                "dynastyValueState": m["dynastyValueState"],
                "bid": m["bid"],
                "bidBasis": m["bidBasis"],
                "excluded": result.excluded_free_agents.get(p.player_id),
            }
        )
    return out


def _drop_board(
    drop_assessment: Any,
    droppable: Mapping[str, Mapping[str, Any]],
    families: set[str],
    roster_meta: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    rows = []
    for a in drop_assessment.assessments:
        if _family(a.position) not in families:
            continue
        d = a.to_dict()
        info = droppable.get(a.player_id)
        d["releaseCost"] = _round(info["cost"], 0) if info else None
        d["weeks"] = roster_meta.get(a.player_id, {}).get("weeks", [])
        rows.append(d)
    order = {"churn": 0, "conditional": 1, "protected": 2}
    rows.sort(key=lambda r: (order.get(r.get("dropClass"), 3), r.get("dynastyValue") or 0))
    return {"players": rows, "summary": drop_assessment.to_dict().get("summary")}


# ── orchestration (I/O through the owners) ──────────────────────────────


def compute_streaming(
    plan_contract: Mapping[str, Any],
    *,
    league_key: str,
    owner_id: str,
    inputs: Mapping[str, Any],
    constraints: Any,
    request: Mapping[str, Any],
    cfg: StreamingConfig | None = None,
    today: date | None = None,
    load_projections: Any = None,
    assess_drops: Any = None,
) -> dict[str, Any]:
    """Run every owner once on one roster snapshot and assemble the payload.

    Raises ``ValueError`` codes: ``no_rosters_loaded``, ``unknown_team``,
    ``starter_slots_unknown``, ``not_in_season``, ``projections_refused``.
    """
    from src.bdvm.actuals import nfl_projection_season  # noqa: PLC0415
    from src.draft.context import contract_teams, index_contract_rows, league_rostered_keys  # noqa: PLC0415
    from src.draft.context import match_team  # noqa: PLC0415
    from src.ros.lineup import resolve_starter_slots  # noqa: PLC0415
    from src.trade import faab_engine  # noqa: PLC0415
    from src.trade import perfect_waivers  # noqa: PLC0415
    from src.trade import waiver as waiver_owner  # noqa: PLC0415
    from src.trade.roster_capacity import assess_roster_capacity, build_capacity_context  # noqa: PLC0415

    cfg = cfg or load_streaming_config()
    teams = contract_teams(plan_contract)
    if not teams:
        raise ValueError("no_rosters_loaded")
    team = match_team(teams, owner_id=owner_id, roster_id=None, team_name=None)
    if team is None:
        raise ValueError("unknown_team")

    sleeper = (
        plan_contract.get("sleeper") if isinstance(plan_contract.get("sleeper"), Mapping) else {}
    )
    slots, slots_source = resolve_starter_slots(
        roster_positions=sleeper.get("rosterPositions"),
        roster_settings=dict(inputs.get("roster_settings") or {}) or None,
    )
    if not slots:
        raise ValueError("starter_slots_unknown")

    current_week, in_season = faab_engine.current_nfl_week(today)
    week = request.get("week") or current_week
    if week is None:
        raise ValueError("not_in_season")
    season = nfl_projection_season(today)
    weeks = [w for w in range(int(week), int(week) + int(request["horizonWeeks"])) if w <= 18]

    if load_projections is None:
        from src.ros.weekly_league_projections import load_weekly_projections  # noqa: PLC0415

        def load_projections(w: int) -> Any:
            return load_weekly_projections(league_key, season, w, current_week=current_week)

    projection_sets = [load_projections(w) for w in weeks]
    if any(getattr(ps, "refusal", None) for ps in projection_sets):
        raise ValueError("projections_refused")

    if assess_drops is None:
        from src.waivers.drop_assessment import assess_team_drops  # noqa: PLC0415

        def assess_drops() -> Any:
            return assess_team_drops(
                plan_contract, league_key=league_key, owner_id=owner_id, constraints=constraints
            )

    drops = assess_drops()

    targets = waiver_owner.find_waiver_targets(
        dict(plan_contract),
        inputs.get("teams"),
        min_value=1,
        per_position_limit=1_000_000,
        league_budget=inputs.get("league_budget"),
        team_count=inputs.get("team_count"),
        starters_per_team=inputs.get("starters_per_team"),
        team_owner_id=owner_id,
        starters=inputs.get("starters"),
        roster_size=inputs.get("roster_size"),
        market_priors=inputs.get("market_priors"),
        today=today,
    )
    rostered = league_rostered_keys(plan_contract)
    candidates, _excluded, _ambiguous = perfect_waivers.free_agent_candidates(
        plan_contract, targets, rostered=rostered
    )
    fa_bids = {c.player_id: c for c in candidates}
    by_id, _by_name = index_contract_rows(plan_contract)

    raw_balance = team.get("faabRemaining")
    faab_remaining = int(raw_balance) if isinstance(raw_balance, int) and raw_balance >= 0 else None

    cap_ctx = build_capacity_context(
        plan_contract,
        league_key,
        team,
        roster_settings=dict(inputs.get("roster_settings") or {}) or None,
        scarcity_reading=(None, "streaming: scarcity not used"),
    )
    capacity = assess_roster_capacity(cap_ctx)
    open_spots = capacity.open_spots_before
    open_note = None
    if open_spots is None:
        open_note = "roster limit unknown: every add is treated as forcing a drop"
    elif capacity.certainty != "exact":
        open_note = f"open roster spots are {capacity.certainty}: {open_spots} used"

    posture = None
    posture_reason = None
    try:
        from src.api.gameplan import league_competitive_postures  # noqa: PLC0415
        from src.api.league_registry import get_scoring_profile  # noqa: PLC0415

        postures, _meta = league_competitive_postures(
            league_key, get_scoring_profile(league_key) or "", plan_contract, build_if_missing=False
        )
        posture = (postures or {}).get(owner_id)
        if posture is not None and hasattr(posture, "to_dict"):
            posture = posture.to_dict()
        if posture is None:
            posture_reason = "team_not_in_posture_bundle"
    except Exception as exc:  # noqa: BLE001 — posture is context, never the answer
        posture_reason = getattr(exc, "reason", None) or f"unavailable:{type(exc).__name__}"

    return assemble_streaming(
        league_key=league_key,
        team=team,
        owner_id=owner_id,
        season=season,
        weeks=weeks,
        current_week=current_week if in_season else None,
        projection_sets=projection_sets,
        slots=slots,
        slots_source=slots_source,
        board_rows_by_id=by_id,
        rostered_keys=rostered,
        drop_assessment=drops,
        fa_bids=fa_bids,
        fa_bid_methodology=targets.get("bidMethodology"),
        ladders=_ladders(plan_contract, rostered),
        faab_remaining=faab_remaining,
        open_spots=open_spots,
        open_spots_note=open_note,
        request=request,
        cfg=cfg,
        posture=posture,
        posture_reason=posture_reason,
    )
