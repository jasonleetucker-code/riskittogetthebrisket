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
from datetime import date, datetime, timezone
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
MAX_DYNASTY_BUDGET = 100_000
#: The one recommended-capacity rule this composer implements; the config
#: declares it (a PRIOR) and a config naming another rule is refused.
RECOMMENDED_CAPACITY_RULE = "fewest_within_one_materiality_step"
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
    request_work_budget: int
    min_solve_work: int
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
        work = int(limits["requestWorkBudget"])
        min_solve = int(limits["minSolveWork"])
        rec_rule = str(entry("recommendedCapacityRule"))
    except (TypeError, ValueError, KeyError) as exc:
        raise StreamingConfigError("streaming config entry has the wrong shape") from exc
    if (
        materiality < 0
        or not 0 <= default_cap <= max_cap <= 10
        or not weights
        or len(weights) > MAX_HORIZON_WEEKS
        or any(w < 0 for w in weights)
        or min(single, multi, row, work, min_solve) < 1
        or rec_rule != RECOMMENDED_CAPACITY_RULE
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
        request_work_budget=work,
        min_solve_work=min_solve,
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
    if isinstance(budget_raw, bool) or not 0 <= budget <= MAX_DYNASTY_BUDGET:
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
        row = ps.players.get(pid)
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


def _release_cost(assessment: Any, rung: int, ladder: Sequence[float]) -> dict[str, Any]:
    """What releasing this player costs against the dynasty budget, and why.

    * ``churn`` (the drop assessment found a free agent of equal dynasty value
      and no signal against a release): the value the wire cannot give back,
      ``max(dynastyCost, V − ladder[rung−1])`` — the ``rung``-th best free
      agent at his position, so several releases at one position are never all
      charged against one free agent.
    * ``conditional`` (droppable "only within the user's explicit dynasty-loss
      budget": an unknown or rising signal, a low-confidence value, or no locks
      supplied): his FULL dynasty value.  No replacement credit, because the
      assessment's own reason is that a free release is unsafe.  At the default
      budget of 0 a conditional player is therefore never released.
    """
    value = float(assessment.dynasty_value)
    if assessment.drop_class == "conditional":
        return {
            "cost": value,
            "basis": "conditional_full_value",
            "ladderReplacementValue": None,
            "replacementRung": None,
            "assessment": assessment,
        }
    replacement = ladder[rung - 1] if 0 < rung <= len(ladder) else 0.0
    deep = max(0.0, value - replacement)
    return {
        "cost": max(float(assessment.dynasty_cost), deep),
        "basis": "churn_value_above_replacement",
        "ladderReplacementValue": replacement,
        "replacementRung": rung,
        "assessment": assessment,
    }


def _recost(plan: solver.StreamPlan | None, table: Mapping[str, Mapping[str, Any]]):
    """A plan found under one cost table, re-priced under another (or None)."""
    if plan is None or any(d not in table for d in plan.drops):
        return None
    return solver.StreamPlan(
        adds=plan.adds,
        drops=plan.drops,
        weekly_gain=plan.weekly_gain,
        gain_by_week=plan.gain_by_week,
        net_dynasty_loss=sum(float(table[d]["cost"]) for d in plan.drops),
        faab_total=plan.faab_total,
    )


def _raw_best(res: Any) -> solver.StreamPlan | None:
    """The best plan a solve found, recommended or not."""
    if res.best is not None:
        return res.best
    return res.alternatives[0] if res.alternatives else None


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
        if any(p is None for p in pts) and _family(position) in set(cfg.idp_families):
            unprojected_roster.append(
                {
                    "playerId": pid,
                    "name": str(name),
                    "missingWeeks": [d["week"] for d, p in zip(detail, pts) if p is None],
                    "weeks": detail,
                }
            )

    # ── who may go, and at what cost ─────────────────────────────────
    k = int(request["capacity"])
    budget = float(request["dynastyBudget"])
    by_family: dict[str, list[Any]] = {}
    for pid in roster_ids:
        a = assessments.get(pid)
        if a is None or a.drop_class not in ("churn", "conditional"):
            continue
        if a.dynasty_value is None or a.dynasty_cost is None:
            continue  # unpriced: never released (the assessment protects them too)
        fam = _family(a.position)
        if fam in families:
            by_family.setdefault(fam, []).append(a)

    def cost_table(kk: int) -> dict[str, dict[str, Any]]:
        # A plan with at most kk adds releases at most kk players, so charging
        # every release at rung min(kk, n) never under-charges that plan.
        table: dict[str, dict[str, Any]] = {}
        for fam, members in by_family.items():
            rung = max(1, min(kk, len(members)))
            for a in members:
                table[a.player_id] = _release_cost(a, rung, ladders.get(fam, ()))
        return table

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
    main_limit = cfg.node_limit_multiweek if multiweek else cfg.node_limit_single_week
    if open_spots is None:
        notes.append(
            open_spots_note or "roster limit unknown: every add is treated as forcing a drop"
        )
    elif open_spots_note:
        notes.append(open_spots_note)

    def solver_input(
        kk: int, table: Mapping[str, Any], limit: int, work: int | None = None
    ) -> solver.SolverInput:
        return solver.SolverInput(
            roster=tuple(
                solver.StreamPlayer(
                    **{
                        **p.__dict__,
                        "dynasty_value": table[p.player_id]["cost"]
                        if p.player_id in table
                        else None,
                    }
                )
                for p in roster
            ),
            free_agents=tuple(free_agents),
            slots=tuple(slots),
            droppable_ids=frozenset(table),
            open_spots=max(0, int(open_spots or 0)),
            max_adds=kk,
            faab_balance=faab_remaining,
            dynasty_budget=budget,
            week_weights=weights,
            materiality=cfg.materiality_points,
            node_limit=limit,
            work_limit=work,
        )

    # One solve per capacity kk = 1..top, each with its own rung-correct cost
    # table and seeded with the previous capacity's plan (re-priced).  The
    # answer at capacity k is the best plan over every kk <= k, so a larger
    # capacity can never return a worse plan, and the curve and the answer
    # come from the same solves.
    #
    # Work is budgeted per REQUEST in canonical lineup solves, the measured
    # cost driver (a search node can cost one solve or, through the
    # Lagrangian bound, hundreds; more horizon weeks cost proportionally
    # more solves).  Deterministic: the same inputs make the same solves.
    # Capacities up to the request are solved first and always get at least
    # ``minSolveWork``; curve rows above it take what is left, and a row the
    # budget cannot reach is reported as not searched, never as optimal.
    top = max(k, cfg.max_capacity) if request["capacityCurve"] else k
    work_left = cfg.request_work_budget
    rows: list[dict[str, Any]] = []
    unsearched: list[int] = []
    seed: solver.StreamPlan | None = None
    for kk in range(1, top + 1):
        table = cost_table(kk)
        cap_limit = main_limit if kk <= k else cfg.node_limit_curve_row
        if kk > k and work_left < cfg.min_solve_work:
            unsearched.append(kk)
            continue
        inp = solver_input(kk, table, cap_limit, max(cfg.min_solve_work, work_left))
        res = solver.solve_streaming(
            inp,
            alternatives=5 if kk <= k else 0,
            unbudgeted=kk == k,
            start=_recost(seed, table),
        )
        work_left -= res.work
        plan = _raw_best(res)
        rows.append({"k": kk, "table": table, "input": inp, "result": res, "plan": plan})
        if plan is not None:
            seed = plan

    def best_upto(limit: int) -> dict[str, Any] | None:
        chosen = None
        for row in rows:
            if row["k"] > limit or row["plan"] is None:
                continue
            if chosen is None or row["plan"].key() < chosen["plan"].key():
                chosen = row
        return chosen

    main_rows = [r for r in rows if r["k"] <= k]
    chosen = best_upto(k)
    best_plan = chosen["plan"] if chosen else None
    best_table = chosen["table"] if chosen else cost_table(max(1, k))
    recommend = best_plan is not None and best_plan.weekly_gain >= max(cfg.materiality_points, 1e-9)
    bounded = [r for r in main_rows if r["result"].status != solver.STATUS_OPTIMAL]
    status = solver.STATUS_BOUNDED if bounded else solver.STATUS_OPTIMAL
    gaps = [r["result"].bound_gap for r in bounded if r["result"].bound_gap is not None]
    solver_notes: list[str] = []
    for r in main_rows:
        for n in r["result"].notes:
            if n not in solver_notes:
                solver_notes.append(n)
    cap_row = rows[k - 1] if k >= 1 else None
    alt_plans = []
    if chosen is not None:
        alt_plans = [p for p in chosen["result"].alternatives if p is not None and p != best_plan][
            :5
        ]

    curve = None
    recommended_k = None
    if request["capacityCurve"]:
        curve = [
            {
                "capacity": 0,
                "bestGainPoints": 0.0,
                "marginalGainPoints": 0.0,
                "netDynastyLoss": 0.0,
                "adds": [],
                "drops": [],
                "status": solver.STATUS_OPTIMAL,
                "searched": True,
            }
        ]
        prev = 0.0
        raw_gains: dict[int, float] = {0: 0.0}
        for kk in range(1, top + 1):
            got = best_upto(kk)
            gain = got["plan"].weekly_gain if got else 0.0
            gain = max(gain, prev)
            curve.append(
                {
                    "capacity": kk,
                    "bestGainPoints": round(gain, 3),
                    "marginalGainPoints": round(gain - prev, 3),
                    "netDynastyLoss": round(got["plan"].net_dynasty_loss, 1) if got else 0.0,
                    "adds": list(got["plan"].adds) if got else [],
                    "drops": list(got["plan"].drops) if got else [],
                    # Proven only if every solve up to this capacity was.
                    "status": (
                        solver.STATUS_OPTIMAL
                        if kk not in unsearched
                        and all(
                            r["result"].status == solver.STATUS_OPTIMAL
                            for r in rows
                            if r["k"] <= kk
                        )
                        else solver.STATUS_BOUNDED
                    ),
                    # False when the request's work budget ran out before
                    # this capacity: its gain carries the smaller
                    # capacities' best, a lower bound.
                    "searched": kk not in unsearched,
                }
            )
            raw_gains[kk] = gain
            prev = gain
        g_max = prev
        if g_max < cfg.materiality_points:
            recommended_k = 0
        else:
            # The fewest spots whose gain is itself material and captures all
            # but less than one material step of the best gain any capacity
            # up to the maximum reaches.
            floor = max(cfg.materiality_points, g_max - cfg.materiality_points)
            # Compared on the unrounded gains (the curve shows them rounded):
            # g_max itself always clears the floor, so this always finds one.
            recommended_k = min(kk for kk, g in raw_gains.items() if g >= floor - 1e-12)

    def explain_plan(
        plan: solver.StreamPlan | None, table: Mapping[str, Any]
    ) -> dict[str, Any] | None:
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
            info = table[d]
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
                    "releaseCostBasis": info["basis"],
                    "ladderReplacementValue": _round(info["ladderReplacementValue"], 0),
                    "assessmentReplacementValue": _round(a.replacement_value, 0),
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
            # With an unknown add value the total is unknown, never a sum
            # that counts him as 0; the known part is given separately.
            "dynastyValueChange": {
                "value": round(raw_add - raw_drop, 1) if unknown_add == 0 else None,
                "knownValue": round(raw_add - raw_drop, 1),
                "state": "complete" if unknown_add == 0 else "partial_unknown_add_values",
                "unknownAddValues": unknown_add,
            },
            "releaseCost": round(plan.net_dynasty_loss, 1),
        }

    best = explain_plan(best_plan if recommend else None, best_table)
    no_move_reason = None
    if not recommend:
        if not by_family and k > 0 and int(open_spots or 0) == 0:
            no_move_reason = "no_droppable_player"
        elif not free_agents:
            no_move_reason = "no_projected_free_agent"
        elif k == 0:
            no_move_reason = "capacity_zero"
        elif _budget_binds(cap_row, cfg.materiality_points):
            no_move_reason = "dynasty_budget_binds"
        elif (best_plan is not None and best_plan.weekly_gain > 1e-9) or (
            cap_row is not None
            and cap_row["result"].best_unbudgeted is not None
            and cap_row["result"].best_unbudgeted.weekly_gain > 1e-9
        ):
            # Some move gains points (within the budget, or only beyond it),
            # but less than the materiality threshold.
            no_move_reason = "below_materiality"
        elif bounded:
            # The search stopped before proving there is no improving move.
            no_move_reason = "search_incomplete"
        else:
            no_move_reason = "no_move_improves_the_lineup"

    if rows:
        baseline_points = rows[0]["result"].baseline_points
    else:
        baseline_points = solver.solve_streaming(
            solver_input(0, {}, 1), alternatives=0, unbudgeted=False
        ).baseline_points
    if unsearched:
        solver_notes.append(
            f"capacity curve rows {unsearched[0]}..{unsearched[-1]} were not searched: the "
            "request's work budget was spent; they show the best plan of a smaller capacity, "
            "a lower bound"
        )
    board_input = (
        chosen["input"] if chosen else (cap_row["input"] if cap_row else solver_input(0, {}, 1))
    )
    excluded = dict(cap_row["result"].excluded_free_agents) if cap_row else {}
    board = _streaming_board(board_input, fa_meta, excluded, weights)
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
            "maxCapacity": cfg.max_capacity,
            "defaultCapacity": cfg.default_capacity,
            "maxHorizonWeeks": len(cfg.horizon_week_weights),
            "maxDynastyBudget": MAX_DYNASTY_BUDGET,
        },
        "lineup": {"slots": list(slots), "source": slots_source},
        "solver": {
            "version": solver.SOLVER_VERSION,
            "status": status,
            "boundGap": _round(max(gaps), 3) if gaps else None,
            "nodes": sum(r["result"].nodes for r in rows),
            "nodeLimit": main_limit,
            "requestWorkBudget": cfg.request_work_budget,
            "workUsed": cfg.request_work_budget - work_left,
            "unsearchedCapacities": unsearched,
            "solvedCapacities": [r["k"] for r in rows],
            "notes": solver_notes,
        },
        "baselinePoints": [_round(p) for p in baseline_points],
        "recommendMove": recommend,
        "noMoveReason": no_move_reason,
        "plan": best,
        "alternatives": (
            (
                [explain_plan(best_plan, best_table)]
                if best_plan is not None and not recommend
                else []
            )
            + [explain_plan(p, best_table) for p in alt_plans]
        ),
        "largerBudget": {
            "plan": explain_plan(cap_row["result"].best_unbudgeted, cap_row["table"])
            if cap_row
            else None,
            "status": cap_row["result"].unbudgeted_status if cap_row else None,
            "meaning": "the best plan at this capacity with the dynasty budget lifted: what a "
            "larger budget would buy",
        },
        "capacityCurve": curve,
        "recommendedCapacity": recommended_k,
        "streamingBoard": board,
        "safeToDrop": _drop_board(drop_assessment, cost_table(max(1, k)), families, roster_meta),
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
        "excludedFreeAgents": dict(sorted(excluded.items())),
        "sources": [ps.to_dict(include_players=False) for ps in projection_sets],
        "notes": notes,
    }


def _budget_binds(cap_row: Mapping[str, Any] | None, materiality: float) -> bool:
    """True when the dynasty budget is what stops a material move: the
    budget-lifted search at the requested capacity found a plan gaining at
    least ``materiality``.  (A droppable set whose every release cost exceeds
    the budget is not enough on its own: the lineup may gain nothing from any
    add, and then the budget is not what stops the move.)"""
    if cap_row is None:
        return False
    lifted = cap_row["result"].best_unbudgeted
    return lifted is not None and lifted.weekly_gain >= max(materiality, 1e-9)


def _streaming_board(
    inp: solver.SolverInput,
    fa_meta: Mapping[str, Mapping[str, Any]],
    excluded: Mapping[str, str],
    weights: Sequence[float],
) -> list[dict[str, Any]]:
    """Available defenders ranked by what ONE of them adds to this lineup
    (no drop), then by weighted projected points — not by dynasty value."""
    gains = solver.solo_gains(inp)
    rows = []
    for p in inp.free_agents:
        if p.player_id not in gains:
            continue
        projected = sum(
            w * float(v) for w, v in zip(weights, p.weekly_points, strict=False) if v is not None
        )
        missing = sum(1 for v in p.weekly_points[: len(weights)] if v is None)
        rows.append((gains[p.player_id], projected, p, missing))
    # The projection tiebreak uses the known weeks only, which ranks a
    # player missing a week below an equal one who is not (the cautious way).
    rows.sort(key=lambda t: (-round(t[0], 6), -round(t[1], 6), t[2].player_id))
    out = []
    for gain, projected, p, missing in rows[:_BOARD_LIMIT]:
        m = fa_meta[p.player_id]
        out.append(
            {
                "playerId": p.player_id,
                "name": m["name"],
                "position": m["position"],
                "team": m["team"],
                "soloLineupGainPoints": round(gain, 2),
                # Unknown, never a sum counting the missing week as 0.
                "weightedProjectedPoints": round(projected, 2) if missing == 0 else None,
                "weightedProjectedPointsKnown": round(projected, 2),
                "missingProjectionWeeks": missing,
                "weeks": m["weeks"],
                "dynastyValue": m["dynastyValue"],
                "dynastyValueState": m["dynastyValueState"],
                "bid": m["bid"],
                "bidBasis": m["bidBasis"],
                "excluded": excluded.get(p.player_id),
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
        d["releaseCostBasis"] = info["basis"] if info else None
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

    Raises ``ValueError`` with a stable code: ``no_rosters_loaded``,
    ``unknown_team``, ``starter_slots_unknown``, ``not_in_season``,
    ``projections_refused``, ``drop_policy_unreadable``, ``league_mismatch``.
    ``StreamingConfigError`` when the streaming config is unreadable.

    The default week is the one whose games are still to be played: on
    Tuesday and Wednesday (the waiver days) ``current_nfl_week`` still names
    the week that just finished, so the default is the next one.
    ``assess_drops(plan_contract, league_key, owner_id, constraints)`` and
    ``load_projections(week, season, current_week)`` are injectable for tests.
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

    clock = today or datetime.now(timezone.utc).date()
    current_week, in_season = faab_engine.current_nfl_week(clock)
    week = request.get("week")
    week_rule = "requested"
    if week is None:
        if current_week is None:
            raise ValueError("not_in_season")
        # Tuesday = 1, Wednesday = 2: the week just played is still "current".
        if clock.weekday() in (1, 2) and current_week < 18:
            week, week_rule = current_week + 1, "next_week_on_waiver_days"
        else:
            week, week_rule = current_week, "current_week"
    season = nfl_projection_season(clock)
    weeks = [w for w in range(int(week), int(week) + int(request["horizonWeeks"])) if w <= 18]

    if load_projections is None:
        from src.ros.weekly_league_projections import load_weekly_projections  # noqa: PLC0415

        def load_projections(w: int, season: int, current_week: int | None) -> Any:
            return load_weekly_projections(league_key, season, w, current_week=current_week)

    projection_sets = [load_projections(w, season, current_week) for w in weeks]
    if any(getattr(ps, "refusal", None) for ps in projection_sets):
        raise ValueError("projections_refused")

    if assess_drops is None:
        from src.waivers.drop_assessment import assess_team_drops  # noqa: PLC0415

        def assess_drops(contract: Any, league_key: str, owner_id: str, constraints: Any) -> Any:
            return assess_team_drops(
                contract, league_key=league_key, owner_id=owner_id, constraints=constraints
            )

    from src.waivers.drop_assessment import (  # noqa: PLC0415
        DropAssessmentConfigError,
        TeamNotInLeague,
    )

    try:
        drops = assess_drops(plan_contract, league_key, owner_id, constraints)
    except TeamNotInLeague as exc:
        raise ValueError("unknown_team") from exc
    except DropAssessmentConfigError as exc:
        raise ValueError("drop_policy_unreadable") from exc
    except ValueError as exc:
        if str(exc).startswith("league_mismatch"):
            raise ValueError("league_mismatch") from exc
        raise

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
    if capacity.over_limit_before:
        open_note = (
            open_note + "; " if open_note else ""
        ) + "the roster is already over its limit: every add forces a drop"

    posture = None
    posture_reason = None
    try:
        from src.api.gameplan import league_competitive_postures  # noqa: PLC0415
        from src.api.league_registry import get_scoring_profile  # noqa: PLC0415

        postures, posture_meta = league_competitive_postures(
            league_key,
            get_scoring_profile(league_key) or "",
            plan_contract,
            week=current_week,
            in_season=bool(in_season),
            build_if_missing=False,
        )
        posture = (postures or {}).get(owner_id)
        if posture is not None and hasattr(posture, "to_dict"):
            posture = posture.to_dict()
        if posture is not None:
            posture = {
                **posture,
                "bundleFreshness": (posture_meta or {}).get("bundleFreshness"),
            }
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
        request={**request, "weekRule": week_rule},
        cfg=cfg,
        posture=posture,
        posture_reason=posture_reason,
    )
