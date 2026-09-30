"""Deterministic DFS lineup construction — the projection baseline.

Objective in this module is exactly one thing: maximize the SUM OF PROJECTED
FANTASY POINTS of a legal lineup.  It is NOT contest-aware: no field, no
ownership, no payout curve, no duplication.  Every result says so
(``capabilityLevel: "projection_only"``) and carries no ROI/EV figure.

Solver: HiGHS through ``scipy.optimize.milp`` (MIT/BSD; ADR in
``docs/dfs/DECISIONS.md``).  With ``mip_rel_gap = 0`` a HiGHS ``status 0``
certifies the optimum of THIS deterministic objective under THESE constraints;
it certifies nothing about winning.  Statuses (closed vocabulary):

``optimal`` · ``timed_out_with_feasible_result`` · ``infeasible`` ·
``timed_out`` · ``unavailable``

Every solver answer is re-checked by :func:`validate_lineup`, a pure-Python
validator that shares no code with the model builder, before it is returned.

Multiple lineups are SEQUENTIAL: lineup *k* is the highest-projected lineup
that satisfies the uniqueness rule against lineups 1..k-1 and the exposure
caps.  That is a documented construction method, not a jointly optimized
portfolio.  A request for N that cannot be met returns the lineups actually
built plus an explicit shortfall — constraints are never relaxed to reach N.

Hard constraints are never relaxed.  When a request is infeasible, a deletion
filter over the OWNER's constraints isolates a minimal conflicting subset
(official rules are background, never candidates for removal).
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any

from src.dfs.imports import SlateAthlete
from src.dfs.rules import RuleSet

MAX_LINEUPS = 150
DEFAULT_TIME_BUDGET_S = 30.0
MAX_TIME_BUDGET_S = 60.0
MAX_ISOLATION_ITEMS = 40
ISOLATION_BUDGET_S = 10.0


class ConstraintError(ValueError):
    def __init__(self, code: str, message: str, detail: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail or {}


@dataclass
class Group:
    label: str
    players: list[str]
    min: int | None = None
    max: int | None = None


@dataclass
class Conditional:
    """If ANY of ``when`` is rostered, the count from ``then`` must lie in [then_min, then_max].

    "If A then B" = then [B] min 1; "if A then not B" = then [B] max 0;
    "if A then at least 2 of group G" = then G min 2.
    """

    label: str
    when: list[str]
    then: list[str]
    then_min: int | None = None
    then_max: int | None = None


@dataclass
class Stack:
    label: str
    primary: list[str]
    secondary: list[str]
    min_secondary: int = 1
    bring_back: int = 0


@dataclass
class Constraints:
    locks: list[str] = field(default_factory=list)
    excludes: list[str] = field(default_factory=list)
    salary_min: int | None = None
    salary_max: int | None = None
    max_per_team: int | None = None
    groups: list[Group] = field(default_factory=list)
    stacks: list[Stack] = field(default_factory=list)
    conditionals: list[Conditional] = field(default_factory=list)
    # Owner FORECAST edits for this build (points).  Replace the source
    # projection in the objective AND in the reported totals; recorded as the
    # owner's, never written back to the slate.
    projection_overrides: dict[str, float] = field(default_factory=dict)
    # Owner SELECTION preferences (fraction, e.g. 0.10 = +10%).  Tilt the
    # objective only; reported projections stay the unboosted forecast.
    boosts: dict[str, float] = field(default_factory=dict)
    lineups: int = 1
    min_unique: int = 1
    max_exposure: float | None = None
    player_max_exposure: dict[str, float] = field(default_factory=dict)
    time_budget_s: float = DEFAULT_TIME_BUDGET_S


def _int(raw: Any, name: str, lo: int, hi: int, allow_none: bool = True) -> int | None:
    if raw is None or raw == "":
        if allow_none:
            return None
        raise ConstraintError("INVALID_CONSTRAINT", f"{name} is required.")
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ConstraintError("INVALID_CONSTRAINT", f"{name} must be a whole number.")
    if isinstance(raw, float) and (not math.isfinite(raw) or not raw.is_integer()):
        raise ConstraintError("INVALID_CONSTRAINT", f"{name} must be a whole number.")
    v = int(raw)
    if v < lo or v > hi:
        raise ConstraintError("INVALID_CONSTRAINT", f"{name} must be between {lo} and {hi}.")
    return v


def _pct(raw: Any, name: str) -> float:
    # Compare before any float() so an arbitrarily large JSON integer cannot overflow.
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not 0 <= raw <= 1:
        raise ConstraintError("INVALID_CONSTRAINT", f"{name} must be a fraction between 0 and 1.")
    return float(raw)


def parse_constraints(
    raw: dict[str, Any] | None, ruleset: RuleSet, pool: list[SlateAthlete]
) -> Constraints:
    """Validate the owner's constraint payload against the rule set and pool."""
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ConstraintError("INVALID_CONSTRAINT", "constraints must be an object.")
    ids = {a.player_id for a in pool}
    size = len(ruleset.slots)

    def id_list(key: str) -> list[str]:
        vals = raw.get(key) or []
        if not isinstance(vals, list) or not all(isinstance(v, str) for v in vals):
            raise ConstraintError("INVALID_CONSTRAINT", f"{key} must be a list of player IDs.")
        unknown = [v for v in vals if v not in ids]
        if unknown:
            raise ConstraintError(
                "INVALID_CONSTRAINT",
                f"{key} names players not on this slate.",
                {"unknown": unknown[:20]},
            )
        return list(dict.fromkeys(vals))

    c = Constraints(locks=id_list("locks"), excludes=id_list("excludes"))
    both = sorted(set(c.locks) & set(c.excludes))
    if both:
        raise ConstraintError(
            "INVALID_CONSTRAINT", "A player cannot be both locked and excluded.", {"players": both}
        )
    c.salary_min = _int(raw.get("salaryMin"), "salaryMin", 0, ruleset.salary_cap)
    c.salary_max = _int(raw.get("salaryMax"), "salaryMax", 0, ruleset.salary_cap)
    c.max_per_team = _int(raw.get("maxPerTeam"), "maxPerTeam", 1, size)
    c.lineups = _int(raw.get("lineups", 1), "lineups", 1, MAX_LINEUPS, allow_none=False) or 1
    c.min_unique = _int(raw.get("minUnique", 1), "minUnique", 1, size, allow_none=False) or 1
    if raw.get("maxExposure") is not None:
        c.max_exposure = _pct(raw["maxExposure"], "maxExposure")
    pme = raw.get("playerMaxExposure") or {}
    if not isinstance(pme, dict):
        raise ConstraintError(
            "INVALID_CONSTRAINT", "playerMaxExposure must map player ID → fraction."
        )
    for pid, v in pme.items():
        if pid not in ids:
            raise ConstraintError(
                "INVALID_CONSTRAINT",
                "playerMaxExposure names a player not on this slate.",
                {"unknown": [pid]},
            )
        c.player_max_exposure[pid] = _pct(v, f"playerMaxExposure[{pid}]")
    budget = raw.get("timeBudgetSeconds")
    if budget is not None:
        if (
            isinstance(budget, bool)
            or not isinstance(budget, (int, float))
            or not 1 <= budget <= MAX_TIME_BUDGET_S
        ):
            raise ConstraintError(
                "INVALID_CONSTRAINT",
                f"timeBudgetSeconds must be between 1 and {MAX_TIME_BUDGET_S:g}.",
            )
        c.time_budget_s = float(budget)
    for i, g in enumerate(raw.get("groups") or []):
        if not isinstance(g, dict):
            raise ConstraintError("INVALID_CONSTRAINT", "groups entries must be objects.")
        players = g.get("players") or []
        if (
            not isinstance(players, list)
            or not players
            or not all(isinstance(p, str) and p in ids for p in players)
        ):
            raise ConstraintError(
                "INVALID_CONSTRAINT", f"group {i + 1} must list players on this slate."
            )
        gmin = _int(g.get("min"), f"group {i + 1} min", 0, size)
        gmax = _int(g.get("max"), f"group {i + 1} max", 0, size)
        if gmin is None and gmax is None:
            raise ConstraintError("INVALID_CONSTRAINT", f"group {i + 1} needs a min or a max.")
        if gmin is not None and gmax is not None and gmin > gmax:
            raise ConstraintError("INVALID_CONSTRAINT", f"group {i + 1} min exceeds max.")
        c.groups.append(
            Group(
                str(g.get("label") or f"Group {i + 1}")[:60],
                list(dict.fromkeys(players)),
                gmin,
                gmax,
            )
        )
    for key, target, lo, hi, what in (
        ("projectionOverrides", c.projection_overrides, -50.0, 500.0, "points"),
        ("boosts", c.boosts, -0.5, 0.5, "a fraction between -0.5 and 0.5"),
    ):
        m = raw.get(key) or {}
        if not isinstance(m, dict):
            raise ConstraintError("INVALID_CONSTRAINT", f"{key} must map player ID to a number.")
        for pid, v in m.items():
            if pid not in ids:
                raise ConstraintError(
                    "INVALID_CONSTRAINT",
                    f"{key} names a player not on this slate.",
                    {"unknown": [pid]},
                )
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi:
                raise ConstraintError("INVALID_CONSTRAINT", f"{key}[{pid}] must be {what}.")
            target[pid] = float(v)
    for i, r in enumerate(raw.get("conditionals") or []):
        if not isinstance(r, dict):
            raise ConstraintError("INVALID_CONSTRAINT", "conditionals entries must be objects.")
        when, then = r.get("when") or [], r.get("then") or []
        for name, lst in (("when", when), ("then", then)):
            if (
                not isinstance(lst, list)
                or not lst
                or not all(isinstance(p, str) and p in ids for p in lst)
            ):
                raise ConstraintError(
                    "INVALID_CONSTRAINT", f"rule {i + 1} '{name}' must list players on this slate."
                )
        if set(when) & set(then):
            raise ConstraintError(
                "INVALID_CONSTRAINT", f"rule {i + 1}: a player cannot be in both 'when' and 'then'."
            )
        tmin = _int(r.get("thenMin"), f"rule {i + 1} thenMin", 0, size)
        tmax = _int(r.get("thenMax"), f"rule {i + 1} thenMax", 0, size)
        if tmin is None and tmax is None:
            raise ConstraintError("INVALID_CONSTRAINT", f"rule {i + 1} needs thenMin or thenMax.")
        if tmin is not None and tmax is not None and tmin > tmax:
            raise ConstraintError("INVALID_CONSTRAINT", f"rule {i + 1}: thenMin exceeds thenMax.")
        c.conditionals.append(
            Conditional(
                label=str(r.get("label") or f"Rule {i + 1}")[:60],
                when=list(dict.fromkeys(when)),
                then=list(dict.fromkeys(then)),
                then_min=tmin,
                then_max=tmax,
            )
        )
    for i, s in enumerate(raw.get("stacks") or []):
        if not isinstance(s, dict):
            raise ConstraintError("INVALID_CONSTRAINT", "stacks entries must be objects.")
        prim = [str(p).upper() for p in s.get("primary") or []]
        sec = [str(p).upper() for p in s.get("secondary") or []]
        if not prim or not sec or not set(prim + sec) <= ruleset.positions:
            raise ConstraintError(
                "INVALID_CONSTRAINT",
                f"stack {i + 1} needs primary and secondary positions from this rule set.",
                {"positions": sorted(ruleset.positions)},
            )
        c.stacks.append(
            Stack(
                label=str(s.get("label") or f"Stack {i + 1}")[:60],
                primary=prim,
                secondary=sec,
                min_secondary=_int(
                    s.get("minSecondary", 1), "minSecondary", 0, size, allow_none=False
                )
                or 0,
                bring_back=_int(s.get("bringBack", 0), "bringBack", 0, size, allow_none=False) or 0,
            )
        )
    return c


def exposure_bounds(c: Constraints, pool: list[SlateAthlete]) -> dict[str, int]:
    """Integer max-appearance count per player for ``c.lineups`` lineups.

    ``floor(pct × N)`` — a cap is never rounded UP past what the owner asked for.
    Locked players are exempt from the global cap (a lock is an explicit
    instruction); an explicit per-player cap still applies to them.
    """
    n = c.lineups
    out: dict[str, int] = {}
    for a in pool:
        pct = c.player_max_exposure.get(a.player_id)
        if pct is None and c.max_exposure is not None and a.player_id not in c.locks:
            pct = c.max_exposure
        if pct is not None:
            out[a.player_id] = int(math.floor(pct * n + 1e-9))
    return out


# ── Independent validator ────────────────────────────────────────────────


def validate_lineup(
    assignment: list[tuple[str, str]],
    ruleset: RuleSet,
    pool_by_id: dict[str, SlateAthlete],
    c: Constraints | None = None,
) -> list[str]:
    """Return every rule the (slot name, player id) assignment breaks.  Empty = legal.

    Written without reference to the MILP so a modelling bug cannot hide itself.
    """
    errors: list[str] = []
    if len(assignment) != len(ruleset.slots):
        return [f"lineup has {len(assignment)} players, rule set needs {len(ruleset.slots)}"]
    ids = [pid for _, pid in assignment]
    if len(set(ids)) != len(ids):
        errors.append("a player appears twice")
    people = [pool_by_id[pid].identity for pid in ids if pid in pool_by_id]
    if len(set(people)) != len(people):
        errors.append("one athlete is rostered twice (e.g. as captain and in flex)")
    athletes = []
    for (slot_name, pid), slot in zip(assignment, ruleset.slots):
        a = pool_by_id.get(pid)
        if a is None:
            errors.append(f"{pid} is not on the slate")
            continue
        athletes.append(a)
        if slot_name != slot.name:
            errors.append(f"slot order mismatch at {slot.name}")
        if not ruleset.eligible(a, slot):
            errors.append(f"{a.name} ({'/'.join(a.positions)}) is not eligible for {slot.name}")
    if len(athletes) != len(assignment):
        return errors
    salary = sum(a.salary for a in athletes)
    if salary > ruleset.salary_cap:
        errors.append(f"salary {salary} exceeds cap {ruleset.salary_cap}")
    teams: dict[str, int] = {}
    for a in athletes:
        teams[a.team] = teams.get(a.team, 0) + 1
    if ruleset.max_players_per_team and max(teams.values()) > ruleset.max_players_per_team:
        errors.append(f"more than {ruleset.max_players_per_team} players from one team")
    if ruleset.min_teams and len(teams) < ruleset.min_teams:
        errors.append(f"players from fewer than {ruleset.min_teams} teams")
    if ruleset.min_games:
        games = {a.game for a in athletes}
        if None in games:
            errors.append("a player's game is unknown, so the minimum-games rule cannot be checked")
        elif len(games) < ruleset.min_games:
            errors.append(f"players from fewer than {ruleset.min_games} games")
    if c is not None:
        missing_locks = [p for p in c.locks if p not in ids]
        if missing_locks:
            errors.append(f"locked players missing: {missing_locks}")
        if set(c.excludes) & set(ids):
            errors.append("an excluded player is in the lineup")
        if c.salary_min is not None and salary < c.salary_min:
            errors.append(f"salary {salary} below owner minimum {c.salary_min}")
        if c.salary_max is not None and salary > c.salary_max:
            errors.append(f"salary {salary} above owner maximum {c.salary_max}")
        if c.max_per_team is not None and max(teams.values()) > c.max_per_team:
            errors.append(f"more than {c.max_per_team} players from one team (owner rule)")
        for g in c.groups:
            n = sum(1 for p in ids if p in g.players)
            if g.min is not None and n < g.min:
                errors.append(f"{g.label}: {n} < min {g.min}")
            if g.max is not None and n > g.max:
                errors.append(f"{g.label}: {n} > max {g.max}")
        for r in c.conditionals:
            if set(r.when) & set(ids):
                n = sum(1 for p in ids if p in r.then)
                if r.then_min is not None and n < r.then_min:
                    errors.append(f"{r.label}: {n} < {r.then_min} required")
                if r.then_max is not None and n > r.then_max:
                    errors.append(f"{r.label}: {n} > {r.then_max} allowed")
        for s in c.stacks:
            for a in athletes:
                if not set(a.positions) & set(s.primary):
                    continue
                mates = sum(
                    1
                    for b in athletes
                    if b is not a and b.team == a.team and set(b.positions) & set(s.secondary)
                )
                if mates < s.min_secondary:
                    errors.append(
                        f"{s.label}: {a.name} has {mates} same-team {'/'.join(s.secondary)}"
                    )
                if s.bring_back:
                    opp = sum(1 for b in athletes if a.opponent and b.team == a.opponent)
                    if opp < s.bring_back:
                        errors.append(f"{s.label}: {a.name} has {opp} bring-back players")
    return errors


# ── MILP ─────────────────────────────────────────────────────────────────


@dataclass
class _Model:
    pairs: list[tuple[int, int]]  # (athlete index, slot index)
    n_vars: int
    rows: list[tuple[dict[int, float], float, float, str]]  # coeffs, lb, ub, item tag


def _build(
    ruleset: RuleSet,
    pool: list[SlateAthlete],
    c: Constraints,
    previous: list[list[str]],
    exhausted: set[str],
    active_items: set[str] | None,
) -> _Model:
    """Build rows.  ``active_items`` None = all owner items; otherwise only those tags."""

    def on(tag: str) -> bool:
        return active_items is None or tag in active_items

    banned = set(exhausted) if on("exposure") else set()
    if on("excludes"):
        banned |= set(c.excludes)
    pairs: list[tuple[int, int]] = []
    for i, a in enumerate(pool):
        if a.player_id in banned:
            continue
        for s, slot in enumerate(ruleset.slots):
            if ruleset.eligible(a, slot):
                pairs.append((i, s))
    n = len(pairs)
    by_athlete: dict[int, list[int]] = {}
    by_slot: dict[int, list[int]] = {}
    for v, (i, s) in enumerate(pairs):
        by_athlete.setdefault(i, []).append(v)
        by_slot.setdefault(s, []).append(v)
    extra = n
    rows: list[tuple[dict[int, float], float, float, str]] = []

    def y(i: int) -> dict[int, float]:
        return {v: 1.0 for v in by_athlete.get(i, [])}

    def add_y(acc: dict[int, float], i: int, coef: float) -> None:
        for v in by_athlete.get(i, []):
            acc[v] = acc.get(v, 0.0) + coef

    for s in range(len(ruleset.slots)):
        rows.append(({v: 1.0 for v in by_slot.get(s, [])}, 1, 1, "rule"))
    for i in by_athlete:
        if len(by_athlete[i]) > 1:
            rows.append((y(i), 0, 1, "rule"))
    # Several rows of one athlete (Showdown CPT + FLEX): at most one of them.
    groups: dict[str, list[int]] = {}
    for i in by_athlete:
        groups.setdefault(pool[i].identity, []).append(i)
    for members in groups.values():
        if len(members) > 1:
            acc: dict[int, float] = {}
            for i in members:
                for v in by_athlete[i]:
                    acc[v] = 1.0
            rows.append((acc, 0, 1, "rule"))
    salary_row: dict[int, float] = {}
    for i in by_athlete:
        add_y(salary_row, i, float(pool[i].salary))
    lo = c.salary_min if (c.salary_min is not None and on("salary_min")) else -math.inf
    hi = float(ruleset.salary_cap)
    if c.salary_max is not None and on("salary_max"):
        hi = min(hi, float(c.salary_max))
    rows.append((salary_row, lo, hi, "rule"))

    teams: dict[str, list[int]] = {}
    games: dict[str, list[int]] = {}
    for i in by_athlete:
        teams.setdefault(pool[i].team, []).append(i)
        if pool[i].game:
            games.setdefault(pool[i].game, []).append(i)
    team_cap = ruleset.max_players_per_team
    if c.max_per_team is not None and on("max_per_team"):
        team_cap = min(team_cap or c.max_per_team, c.max_per_team)
    if team_cap:
        for members in teams.values():
            acc: dict[int, float] = {}
            for i in members:
                add_y(acc, i, 1.0)
            rows.append((acc, -math.inf, team_cap, "rule"))
    # Indicator z_k ≤ Σ y over members; Σ z ≥ minimum.
    for minimum, buckets in ((ruleset.min_teams, teams), (ruleset.min_games, games)):
        if not minimum:
            continue
        z_vars = []
        for members in buckets.values():
            z = extra
            extra += 1
            z_vars.append(z)
            acc = {z: 1.0}
            for i in members:
                add_y(acc, i, -1.0)
            rows.append((acc, -math.inf, 0, "rule"))
        rows.append(({z: 1.0 for z in z_vars}, minimum, math.inf, "rule"))

    index = {a.player_id: i for i, a in enumerate(pool)}
    for pid in c.locks:
        tag = f"lock:{pid}"
        if on(tag):
            rows.append((y(index[pid]), 1, 1, tag))
    for gi, g in enumerate(c.groups):
        tag = f"group:{gi}"
        if not on(tag):
            continue
        acc = {}
        for pid in g.players:
            if pid in index:  # an unprojected player cannot be selected
                add_y(acc, index[pid], 1.0)
        rows.append(
            (acc, -math.inf if g.min is None else g.min, math.inf if g.max is None else g.max, tag)
        )
    for ri, r in enumerate(c.conditionals):
        tag = f"cond:{ri}"
        if not on(tag):
            continue
        then_idx = [index[p] for p in r.then if p in index]
        for pid in r.when:
            if pid not in index:
                continue
            w = index[pid]
            if r.then_min is not None and r.then_min > 0:
                # Σ then − min·y_w ≥ 0  (binding only when w is rostered)
                acc = {}
                for j in then_idx:
                    add_y(acc, j, 1.0)
                add_y(acc, w, -float(r.then_min))
                rows.append((acc, 0, math.inf, tag))
            if r.then_max is not None:
                # Σ then + (|then| − max)·y_w ≤ |then|  (slack when w is not rostered)
                big = max(0, len(then_idx) - r.then_max)
                if big:
                    acc = {}
                    for j in then_idx:
                        add_y(acc, j, 1.0)
                    add_y(acc, w, float(big))
                    rows.append((acc, -math.inf, float(len(then_idx)), tag))
    for si, st in enumerate(c.stacks):
        tag = f"stack:{si}"
        if not on(tag):
            continue
        for i in by_athlete:
            a = pool[i]
            if not set(a.positions) & set(st.primary):
                continue
            if st.min_secondary:
                # Σ same-team secondary − k·y_primary ≥ 0
                acc = {}
                for j in teams.get(a.team, []):
                    if j != i and set(pool[j].positions) & set(st.secondary):
                        add_y(acc, j, 1.0)
                add_y(acc, i, -float(st.min_secondary))
                rows.append((acc, 0, math.inf, tag))
            if st.bring_back:
                acc = {}
                for j in teams.get(a.opponent or "", []):
                    add_y(acc, j, 1.0)
                add_y(acc, i, -float(st.bring_back))
                rows.append((acc, 0, math.inf, tag))
    if on("uniqueness"):
        size = len(ruleset.slots)
        for prev in previous:
            acc = {}
            for pid in prev:
                if pid in index:
                    add_y(acc, index[pid], 1.0)
            rows.append((acc, -math.inf, size - c.min_unique, "uniqueness"))
    return _Model(pairs=pairs, n_vars=extra, rows=rows)


def _solve(
    model: _Model, objective: list[float], time_limit: float
) -> tuple[str, list[float] | None]:
    import numpy as np
    from scipy.optimize import Bounds, LinearConstraint, milp
    from scipy.sparse import coo_array

    if model.n_vars == 0:
        return "infeasible", None
    r_idx, c_idx, vals, lbs, ubs = [], [], [], [], []
    for r, (coeffs, lb, ub, _tag) in enumerate(model.rows):
        for v, coef in coeffs.items():
            r_idx.append(r)
            c_idx.append(v)
            vals.append(coef)
        lbs.append(lb)
        ubs.append(ub)
    A = coo_array((vals, (r_idx, c_idx)), shape=(len(model.rows), model.n_vars)).tocsr()
    cost = np.zeros(model.n_vars)
    cost[: len(objective)] = -np.asarray(objective, dtype=float)
    res = milp(
        c=cost,
        constraints=[
            LinearConstraint(A, np.asarray(lbs, dtype=float), np.asarray(ubs, dtype=float))
        ],
        integrality=np.ones(model.n_vars),
        bounds=Bounds(0, 1),
        options={"time_limit": max(0.05, time_limit), "mip_rel_gap": 0.0, "presolve": True},
    )
    if res.status == 0 and res.x is not None:
        return "optimal", list(res.x)
    if res.status == 1:
        return (
            ("timed_out_with_feasible_result", list(res.x))
            if res.x is not None
            else ("timed_out", None)
        )
    if res.status == 2:
        return "infeasible", None
    return "unavailable", None


def _extract(
    model: _Model, x: list[float], ruleset: RuleSet, pool: list[SlateAthlete]
) -> list[tuple[str, str]]:
    chosen = {}
    for v, (i, s) in enumerate(model.pairs):
        if x[v] > 0.5:
            chosen[s] = pool[i].player_id
    return [(slot.name, chosen.get(s, "")) for s, slot in enumerate(ruleset.slots)]


def solver_version() -> str:
    try:
        import scipy

        return f"HiGHS via scipy.optimize.milp (scipy {scipy.__version__})"
    except Exception:  # noqa: BLE001
        return "unavailable"


def _owner_items(c: Constraints, previous: list[list[str]], exhausted: set[str]) -> list[str]:
    items = [f"lock:{p}" for p in c.locks]
    if c.excludes:
        items.append("excludes")
    if c.salary_min is not None:
        items.append("salary_min")
    if c.salary_max is not None:
        items.append("salary_max")
    if c.max_per_team is not None:
        items.append("max_per_team")
    items += [f"group:{i}" for i in range(len(c.groups))]
    items += [f"stack:{i}" for i in range(len(c.stacks))]
    items += [f"cond:{i}" for i in range(len(c.conditionals))]
    if previous:
        items.append("uniqueness")
    if exhausted:
        items.append("exposure")
    return items


def describe_item(tag: str, c: Constraints, pool_by_id: dict[str, SlateAthlete]) -> str:
    kind, _, ref = tag.partition(":")
    if kind == "lock":
        a = pool_by_id.get(ref)
        return f"Lock {a.name if a else ref}"
    if kind == "group":
        g = c.groups[int(ref)]
        return f"{g.label} (min {g.min}, max {g.max})"
    if kind == "cond":
        r = c.conditionals[int(ref)]
        names = lambda ps: ", ".join(pool_by_id[p].name if p in pool_by_id else p for p in ps[:4])  # noqa: E731
        bounds = " and ".join(
            x
            for x in (
                f"at least {r.then_min}" if r.then_min is not None else "",
                f"at most {r.then_max}" if r.then_max is not None else "",
            )
            if x
        )
        return f"{r.label}: if {names(r.when)} then {bounds} of {names(r.then)}"
    if kind == "stack":
        s = c.stacks[int(ref)]
        return (
            f"{s.label}: each {'/'.join(s.primary)} needs {s.min_secondary} same-team {'/'.join(s.secondary)}"
            + (f" and {s.bring_back} bring-back" if s.bring_back else "")
        )
    return {
        "excludes": f"Excluded players ({len(c.excludes)})",
        "salary_min": f"Minimum salary {c.salary_min}",
        "salary_max": f"Maximum salary {c.salary_max}",
        "max_per_team": f"At most {c.max_per_team} players per team",
        "uniqueness": f"At least {c.min_unique} unique player(s) versus every earlier lineup",
        "exposure": "Exposure caps (players already at their maximum)",
    }.get(tag, tag)


def isolate_conflict(
    ruleset: RuleSet,
    pool: list[SlateAthlete],
    c: Constraints,
    previous: list[list[str]],
    exhausted: set[str],
    deadline: float,
) -> dict[str, Any]:
    """Deletion filter: a minimal set of owner items that is infeasible with the official rules."""
    items = _owner_items(c, previous, exhausted)

    def feasible(active: set[str]) -> bool | None:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        m = _build(ruleset, pool, c, previous, exhausted, active)
        status, _ = _solve(m, [0.0] * len(m.pairs), min(remaining, 5.0))
        if status in ("optimal", "timed_out_with_feasible_result"):
            return True
        if status == "infeasible":
            return False
        return None

    base = feasible(set())
    if base is None:
        return {"state": "undetermined", "reason": "time budget exhausted before isolation"}
    if not base:
        return {
            "state": "rules_or_pool",
            "items": [],
            "message": "The player pool cannot fill a legal lineup under the rule set alone "
            "(check that every slot has eligible, projected players and the cap is reachable).",
        }
    if len(items) > MAX_ISOLATION_ITEMS:
        return {
            "state": "undetermined",
            "reason": f"more than {MAX_ISOLATION_ITEMS} owner constraints",
        }
    core = list(items)
    for tag in list(items):
        trial = set(core) - {tag}
        ok = feasible(trial)
        if ok is None:
            return {
                "state": "undetermined",
                "reason": "time budget exhausted during isolation",
                "items": core,
            }
        if not ok:
            core.remove(tag)
    return {"state": "isolated", "items": core}


def _lineup_payload(
    assignment: list[tuple[str, str]],
    pool_by_id: dict[str, SlateAthlete],
    ruleset: RuleSet,
    c: Constraints | None = None,
) -> dict[str, Any]:
    players = []
    for slot_name, pid in assignment:
        a = pool_by_id[pid]
        mult = ruleset.points_multiplier(slot_name)
        override = c.projection_overrides.get(pid) if c else None
        used = override if override is not None else a.projection
        players.append(
            {
                "slot": slot_name,
                "playerId": pid,
                "name": a.name,
                "positions": a.positions,
                "team": a.team,
                "opponent": a.opponent,
                "game": a.game,
                "salary": a.salary,
                "projection": a.projection,
                # The stored projection is never changed; the slot's multiplier
                # (captain 1.5x) is applied here, visibly, exactly once.
                "ownerOverride": override,
                "preferenceBoost": (c.boosts.get(pid) if c else None),
                "slotMultiplier": mult,
                # Forecast actually used (owner override if any) × slot multiplier.
                # Boosts are NOT in here: they tilted selection, not the forecast.
                "slotProjection": round(used * mult, 2) if used is not None else None,
                "projectionSource": a.projection_source,
                "pointsPerK": round(used / (a.salary / 1000), 3)
                if a.salary and used is not None
                else None,
            }
        )
    salary = sum(p["salary"] for p in players)
    teams: dict[str, int] = {}
    for p in players:
        teams[p["team"]] = teams.get(p["team"], 0) + 1
    return {
        "players": players,
        "salary": salary,
        "salaryRemaining": ruleset.salary_cap - salary,
        "projection": round(sum(p["slotProjection"] for p in players), 2),
        # Same players in different flex slots score identically: that is ONE
        # scoring identity.  The slot map is kept separately because late-swap
        # flexibility can still differ between assignments.
        "scoringIdentity": "|".join(sorted(p["playerId"] for p in players)),
        "assignmentIdentity": "|".join(f"{p['slot']}={p['playerId']}" for p in players),
        "teamCounts": dict(sorted(teams.items(), key=lambda kv: (-kv[1], kv[0]))),
    }


def optimize(ruleset: RuleSet, athletes: list[SlateAthlete], c: Constraints) -> dict[str, Any]:
    """Build up to ``c.lineups`` lineups.  Never raises for infeasibility — it reports."""
    started = time.monotonic()
    deadline = started + c.time_budget_s
    by_id = {a.player_id: a for a in athletes}
    unprojected_locks = [
        p for p in c.locks if by_id[p].projection is None and p not in c.projection_overrides
    ]
    if unprojected_locks:
        raise ConstraintError(
            "LOCKED_PLAYER_UNPROJECTED",
            "A locked player has no projection. Add a projection for them or remove the lock — missing is never scored as zero.",
            {"players": [{"playerId": p, "name": by_id[p].name} for p in unprojected_locks]},
        )
    excluded = set(c.excludes)
    if ruleset.min_games and any(
        a.game is None for a in athletes if a.projection is not None and a.player_id not in excluded
    ):
        raise ConstraintError(
            "GAME_UNKNOWN",
            "Some players have no game, so the rule set's minimum-games rule cannot be enforced. Re-import the full platform file.",
        )
    # An owner override supplies a forecast, so an overridden athlete is
    # projected even if the source had none (missing stays missing otherwise).
    forecast = {
        a.player_id: c.projection_overrides.get(a.player_id, a.projection) for a in athletes
    }
    pool = [a for a in athletes if forecast[a.player_id] is not None]
    excluded_unprojected = [a.player_id for a in athletes if forecast[a.player_id] is None]
    # Unrounded: the solver optimizes exactly the forecasts it was given, tilted
    # by any owner selection boost (which never enters a reported total).
    objective = [
        float(forecast[a.player_id]) * (1.0 + c.boosts.get(a.player_id, 0.0)) for a in pool
    ]  # type: ignore[arg-type]
    pool_by_id = {a.player_id: a for a in pool}
    caps = exposure_bounds(c, pool)
    counts: dict[str, int] = {}
    lineups: list[dict[str, Any]] = []
    previous: list[list[str]] = []
    statuses: list[str] = []
    stop: dict[str, Any] | None = None
    for k in range(c.lineups):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            stop = {"reason": "time_budget_exhausted"}
            break
        exhausted = {pid for pid, cap in caps.items() if counts.get(pid, 0) >= cap}
        locked_exhausted = sorted(set(c.locks) & exhausted)
        if locked_exhausted:
            statuses.append("infeasible")  # proven without a solve, not a timeout
            stop = {
                "reason": "infeasible",
                "conflict": {
                    "state": "isolated",
                    "items": [f"lock:{p}" for p in locked_exhausted] + ["exposure"],
                },
            }
            break
        model = _build(ruleset, pool, c, previous, exhausted, None)
        # The objective indexes (athlete, slot) pairs, not athletes.
        # Slot multipliers (Showdown captain) apply here, once, at the slot.
        status, x = _solve(
            model,
            [
                objective[i] * ruleset.points_multiplier(ruleset.slots[s].name)
                for i, s in model.pairs
            ],
            remaining,
        )
        statuses.append(status)
        if x is None:
            if status == "infeasible":
                stop = {
                    "reason": "infeasible",
                    # Isolation gets its own bounded budget (ISOLATION_BUDGET_S)
                    # beyond the build budget; it only ever runs after a proven
                    # infeasibility, and the response reports its elapsed time.
                    "conflict": isolate_conflict(
                        ruleset,
                        pool,
                        c,
                        previous,
                        exhausted,
                        max(deadline, time.monotonic()) + ISOLATION_BUDGET_S,
                    ),
                }
            else:
                stop = {"reason": status}
            break
        assignment = _extract(model, x, ruleset, pool)
        errors = validate_lineup(assignment, ruleset, pool_by_id, c)
        if not errors and previous:
            ids = {pid for _, pid in assignment}
            for prev in previous:
                if len(ids - set(prev)) < c.min_unique:
                    errors.append("uniqueness rule violated")
                    break
        if errors:
            stop = {"reason": "solver_result_invalid", "errors": errors}
            statuses[-1] = "unavailable"
            break
        payload = _lineup_payload(assignment, pool_by_id, ruleset, c)
        payload["index"] = k + 1
        payload["status"] = status
        lineups.append(payload)
        ids_now = [pid for _, pid in assignment]
        previous.append(ids_now)
        for pid in ids_now:
            counts[pid] = counts.get(pid, 0) + 1
    if stop and stop.get("conflict", {}).get("items"):
        stop["conflict"]["described"] = [
            describe_item(t, c, by_id) for t in stop["conflict"]["items"]
        ]
    if not lineups:
        overall = statuses[-1] if statuses else "timed_out"
        if stop and stop.get("reason") == "time_budget_exhausted":
            overall = "timed_out"
    elif any(s == "timed_out_with_feasible_result" for s in statuses):
        overall = "timed_out_with_feasible_result"
    else:
        overall = "optimal" if len(lineups) == c.lineups else "partial"
    exposure = []
    n_built = len(lineups)
    for pid, cnt in sorted(counts.items(), key=lambda kv: (-kv[1], pool_by_id[kv[0]].name)):
        exposure.append(
            {
                "playerId": pid,
                "name": pool_by_id[pid].name,
                "count": cnt,
                "share": round(cnt / n_built, 4) if n_built else None,
                "cap": caps.get(pid),
            }
        )
    return {
        "status": overall,
        "requested": c.lineups,
        "built": n_built,
        "shortfall": (
            None if n_built == c.lineups else {"missing": c.lineups - n_built, **(stop or {})}
        ),
        "lineups": lineups,
        "exposure": exposure,
        "exposureCaps": {pid: cap for pid, cap in caps.items()},
        "excludedUnprojected": excluded_unprojected,
        "elapsedMs": int((time.monotonic() - started) * 1000),
    }
