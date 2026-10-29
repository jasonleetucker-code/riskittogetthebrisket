"""Weekly streaming solver: the add/drop SET that most improves the optimal lineup.

What this answers
=================
*Given this roster, these free agents and their league-scored projected points
for one or more weeks, which adds and drops raise the optimal starting lineup
the most, subject to roster capacity, lineup legality, FAAB, the drop policy
and an explicit dynasty-loss budget, and is any of it better than doing
nothing?*

It is the weekly-points objective.  The DYNASTY objective (additive board value
of the held set) is Perfect Waivers' (``src/trade/perfect_waivers.py``) and is
not touched here.  Pure: no I/O, no contract reads, no clock.  The composer
(``src/waivers/streaming.py``) assembles the inputs from the canonical owners.

Nothing here is a second owner
==============================
* **Lineup value** is ``src/ros/lineup.py::solve_optimal_assignment`` (exact
  max-weight transversal-matroid assignment) with
  ``objective=OBJECTIVE_REALIZED_POINTS``: a player's weight is his projected
  points for the week, raw.  ``None`` (unprojected) is not assignable, never 0.
* **Legality** is the cut ladder's rule (``src/draft/displacement.py``): the
  final roster may not fill fewer starting slots than today's.  "Fill" is the
  same solver run with every weight 1.
* **Who may be dropped** is decided upstream by the drop assessment
  (``src/waivers/drop_assessment.py``): only its ``churn`` / ``conditional``
  players reach :attr:`SolverInput.droppable_ids`.  Protected, locked and
  unpriced players can never be released here.
* **Bids** are the FAAB engine's, supplied per free agent.  Dollars are a
  constraint, never traded against points.

The problem, exactly
====================
``L_w(S)`` is the optimal lineup's projected points from player set ``S`` in
week ``w``; ``V(S) = Σ_w weight_w · L_w(S)``.  For roster ``R``, open spots
``o``, free agents ``F``, droppable set ``E ⊆ R``::

    maximize   V(R ∪ A \\ D) − V(R)
    subject to A ⊆ F, D ⊆ E, |A| ≤ k, |A| − |D| ≤ o,
               Σ bid(A) ≤ FAAB balance,
               fill(R ∪ A \\ D) ≥ fill(R),
               Σ dyn(D) − Σ dyn(A) ≤ β            (β ≥ 0; unknown dyn(a) credits 0)
               every add starts: V(final) > V(final − a) for each a ∈ A

Ties: smaller net dynasty loss, then fewer moves, then id order.  A plan whose
gain is below ``materiality`` is not recommended: the answer is "no move".

Why it is exact (and when it says it is not)
============================================
Each ``L_w`` is a weighted matroid rank function, so ``V`` is monotone and
SUBMODULAR.  The search is a depth-first branch-and-bound over add sets, with
a second depth-first search for the drops of each add set.  Every cut below
is a proof that the cut branch cannot beat (or, on equal points, cannot tie
more cheaply than) the incumbent:

* **Components.**  The eligibility graph (players joined to the slots they may
  fill) splits into connected components and the lineup optimum is the sum of
  each component's (direct sum of matroids).  With no IDP flex, DL, LB and DB
  are separate and an IDP move never re-solves the offense.  Each component
  is still solved by ``solve_optimal_assignment``; only bookkeeping is split.
* **Solo-gain bound.**  ``V(R∪A\\D) − V(R) ≤ Σ_{a∈A} g(a)`` with
  ``g(a) = V(R+a) − V(R)`` (drops only remove value; submodularity).  Cheap,
  checked first.
* **Lagrangian bound** (:meth:`_Evaluator.plan_bound`).  The plan's side
  constraints — at most ``room`` more free agents, at most ``|E| + open`` of
  the droppable players and the adds left on the final roster, and the
  dynasty budget — are relaxed with multipliers.  For fixed multipliers the
  relaxation is one canonical lineup solve per component and week with
  per-player weights, so every multiplier triple is a valid upper bound (weak
  duality); subgradient steps tighten it.  For one week and one binding
  count it is the exact constrained optimum (a matroid intersected with one
  capacity constraint is integral).  Players with identical slot eligibility
  beyond the number of slots they share are left out of these solves
  (exchange argument: exact).
* **Independent adds.**  For a single week every add must start, so the adds
  must fit in one lineup together; a set that cannot fit has no feasible
  superset.  (Over several weeks two adds may start in different weeks, so
  this cut is not used there.)
* **Drops.**  Pass 1 finds the best points over the forced drop sets, ties
  cut; pass 2 finds the cheapest drop set reaching them.  At each node the
  players skipped are kept and ``r`` more must go, so the Lagrangian bound
  with that count dualised bounds every completion, and the cheapest ``r``
  remaining dynasty values bound the cost (and the budget).
* **Candidate filter (dominance, exact).**  A zero-gain free agent CAN matter:
  once a starter is released it may start, and its dynasty value may be what
  keeps the plan inside the budget (found by the oracle, not assumed).  So no
  candidate is dropped for a zero solo gain.  Instead a free agent is skipped
  only when at least ``k`` others with the same slot eligibility are at least
  as good on every week's points, on dynasty value and on bid (and strictly
  better on one, or equal with a smaller id): a plan uses at most ``k`` adds,
  so one dominator is always free to take its place without loss.

Exactness is checked against a brute-force oracle over every add and drop
subset (``tests/waivers/test_streaming_solver.py``, and 3,000 further random
instances, one and two weeks, budgeted and not, in development).

The search is bounded by ``node_limit`` (add-set nodes plus drop-search
nodes).  If it is reached the result is ``status="bounded"`` with
``boundGap``, the Lagrangian bound over every plan minus the plan found — a
proven ceiling on what was left unexplored.  It is never passed off as
optimal, and there is no greedy fallback.  The larger-budget comparison
(``bestUnbudgeted``) runs under its own share of the node limit and has its
own status, so it can never make the main answer "bounded".
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from src.ros.lineup import (
    OBJECTIVE_REALIZED_POINTS,
    RosterPlayer,
    precompute_slot_eligibility,
    solve_optimal_assignment,
)

__all__ = [
    "SOLVER_VERSION",
    "STATUS_BOUNDED",
    "STATUS_OPTIMAL",
    "SolverInput",
    "SolverResult",
    "StreamPlayer",
    "StreamPlan",
    "capacity_curve",
    "solve_streaming",
]

SOLVER_VERSION = "streaming-solver/2026-10-29.v1"
STATUS_OPTIMAL = "optimal"
STATUS_BOUNDED = "bounded"
DEFAULT_NODE_LIMIT = 200_000
_EPS = 1e-9
_BOUND_STEPS = 30
#: Share of ``node_limit`` the larger-budget comparison may use.
UNBUDGETED_NODE_SHARE = 0.25


@dataclass(frozen=True)
class StreamPlayer:
    """One player as the solver sees him.  Units are in the field names."""

    player_id: str
    name: str
    position: str
    #: Projected league-scored points per horizon week (same length as
    #: :attr:`SolverInput.week_weights`).  ``None`` = unknown that week.
    weekly_points: tuple[float | None, ...]
    #: Canonical dynasty value (``rankDerivedValue``); ``None`` = unpriced.
    dynasty_value: float | None = None
    fantasy_positions: tuple[str, ...] = ()
    #: Recommended FAAB bid (free agents only), whole dollars.
    bid: int = 0

    def eligible_signature(self) -> tuple[str, ...]:
        merged = {p.strip().upper() for p in self.fantasy_positions if p and p.strip()}
        if self.position:
            merged.add(self.position.strip().upper())
        return tuple(sorted(merged))


@dataclass(frozen=True)
class SolverInput:
    roster: tuple[StreamPlayer, ...]
    free_agents: tuple[StreamPlayer, ...]
    slots: tuple[str, ...]
    #: Roster ids the drop policy allows to be released (churn / conditional).
    droppable_ids: frozenset[str]
    open_spots: int
    max_adds: int
    faab_balance: int | None
    dynasty_budget: float = 0.0
    week_weights: tuple[float, ...] = (1.0,)
    materiality: float = 0.0
    slot_eligibility: Mapping[str, Collection[str]] | None = None
    node_limit: int = DEFAULT_NODE_LIMIT


@dataclass(frozen=True)
class StreamPlan:
    adds: tuple[str, ...]
    drops: tuple[str, ...]
    #: Σ_w weight_w · (L_w(final) − L_w(R)), projected points.
    weekly_gain: float
    #: Per horizon week, unweighted.
    gain_by_week: tuple[float, ...]
    #: Σ dyn(D) − Σ dyn(A) (unknown add value credits 0), dynasty value units.
    net_dynasty_loss: float
    faab_total: int

    def key(self) -> tuple:
        return (
            -round(self.weekly_gain, 6),
            round(self.net_dynasty_loss, 6),
            len(self.adds) + len(self.drops),
            self.adds,
            self.drops,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "adds": list(self.adds),
            "drops": list(self.drops),
            "weeklyGainPoints": round(self.weekly_gain, 3),
            "gainByWeekPoints": [round(g, 3) for g in self.gain_by_week],
            "netDynastyLoss": round(self.net_dynasty_loss, 1),
            "faabTotal": self.faab_total,
        }


@dataclass
class SolverResult:
    status: str
    baseline_points: tuple[float, ...]
    best: StreamPlan | None
    recommend_move: bool
    #: Best plan with the dynasty budget lifted (what a bigger β would buy).
    best_unbudgeted: StreamPlan | None
    alternatives: list[StreamPlan]
    excluded_free_agents: dict[str, str]
    bound_gap: float | None
    nodes: int
    notes: list[str] = field(default_factory=list)
    #: ``optimal`` / ``bounded`` for :attr:`best_unbudgeted`; ``None`` when
    #: it was not computed.  Separate from :attr:`status` (the budgeted answer).
    unbudgeted_status: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "solverVersion": SOLVER_VERSION,
            "status": self.status,
            "baselinePoints": [round(p, 3) for p in self.baseline_points],
            "recommendMove": self.recommend_move,
            "best": self.best.to_dict() if self.best else None,
            "bestUnbudgeted": self.best_unbudgeted.to_dict() if self.best_unbudgeted else None,
            "bestUnbudgetedStatus": self.unbudgeted_status,
            "alternatives": [p.to_dict() for p in self.alternatives],
            "excludedFreeAgents": dict(sorted(self.excluded_free_agents.items())),
            "boundGap": None if self.bound_gap is None else round(self.bound_gap, 3),
            "nodes": self.nodes,
            "notes": list(self.notes),
        }


class _Evaluator:
    """Lineup value of a player set, per week, memoised per lineup COMPONENT.

    The eligibility graph (players and slots, joined where a player may sit
    in a slot) splits into connected components; the transversal matroid is
    their direct sum, so the optimal lineup's points are the sum of each
    component's optimum.  In a league with no IDP flex, DL, LB and DB are
    three separate components and every offensive slot is untouched by an
    IDP move.  Each component is still solved by the canonical owner, on its
    own players and slots; only the bookkeeping is split.
    """

    def __init__(self, inp: SolverInput) -> None:
        self.inp = inp
        self.weeks = len(inp.week_weights)
        self.players: dict[str, StreamPlayer] = {}
        for p in (*inp.roster, *inp.free_agents):
            self.players.setdefault(p.player_id, p)
        slots = list(inp.slots)
        fill_players = {
            pid: RosterPlayer(
                player_id=pid,
                canonical_name=p.name,
                position=p.position,
                ros_value=1.0,
                fantasy_positions=p.fantasy_positions,
            )
            for pid, p in self.players.items()
        }
        elig = precompute_slot_eligibility(
            list(fill_players.values()), slots, slot_eligibility=inp.slot_eligibility
        )
        # Union-find over players ("p:<id>") and slot indices ("s:<i>").
        parent: dict[str, str] = {}

        def find(x: str) -> str:
            parent.setdefault(x, x)
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for pid in self.players:
            find(f"p:{pid}")
            for i in elig.get(pid, ()):
                a, b = find(f"p:{pid}"), find(f"s:{i}")
                if a != b:
                    parent[max(a, b)] = min(a, b)
        roots = sorted({find(f"p:{pid}") for pid in self.players})
        index = {r: n for n, r in enumerate(roots)}
        self.comp_of: dict[str, int] = {pid: index[find(f"p:{pid}")] for pid in self.players}
        self._comp_slots: list[list[str]] = [[] for _ in roots]
        for i, slot in enumerate(slots):
            root = find(f"s:{i}")
            if root in index:
                self._comp_slots[index[root]].append(slot)
        members: list[list[str]] = [[] for _ in roots]
        for pid in sorted(self.players):
            members[self.comp_of[pid]].append(pid)
        self._comp_elig = []
        for c, pids in enumerate(members):
            self._comp_elig.append(
                precompute_slot_eligibility(
                    [fill_players[i] for i in pids],
                    self._comp_slots[c],
                    slot_eligibility=inp.slot_eligibility,
                )
            )
        #: Eligible slot indices within the player's component.
        self._sig: dict[str, tuple[int, ...]] = {
            pid: tuple(self._comp_elig[self.comp_of[pid]].get(pid, ())) for pid in self.players
        }
        self._per_week: list[dict[str, RosterPlayer]] = [
            {
                pid: RosterPlayer(
                    player_id=pid,
                    canonical_name=p.name,
                    position=p.position,
                    ros_value=_week(p, w),
                    fantasy_positions=p.fantasy_positions,
                )
                for pid, p in self.players.items()
            }
            for w in range(self.weeks)
        ]
        self._fill_players = fill_players
        self._cache: dict[frozenset[str], tuple[float, ...]] = {}
        self._comp_cache: dict[tuple[int, int, frozenset[str]], float] = {}
        self._fill_cache: dict[tuple[int, frozenset[str]], int] = {}
        self.calls = 0

    def _solve(self, comp: int, pool: list[RosterPlayer]) -> dict[int, RosterPlayer]:
        return solve_optimal_assignment(
            pool,
            self._comp_slots[comp],
            slot_eligibility=self.inp.slot_eligibility,
            precomputed_eligibility=self._comp_elig[comp],
            objective=OBJECTIVE_REALIZED_POINTS,
        )

    def _split(self, ids: frozenset[str]) -> dict[int, frozenset[str]]:
        groups: dict[int, set[str]] = {}
        for i in ids:
            groups.setdefault(self.comp_of[i], set()).add(i)
        return {c: frozenset(g) for c, g in groups.items()}

    def _comp_points(self, comp: int, w: int, ids: frozenset[str]) -> float:
        key = (comp, w, ids)
        hit = self._comp_cache.get(key)
        if hit is not None:
            return hit
        self.calls += 1
        table = self._per_week[w]
        assignment = self._solve(comp, [table[i] for i in sorted(ids)])
        res = sum(float(p.ros_value or 0.0) for p in assignment.values())
        self._comp_cache[key] = res
        return res

    def points(self, ids: frozenset[str]) -> tuple[float, ...]:
        hit = self._cache.get(ids)
        if hit is not None:
            return hit
        groups = self._split(ids)
        res = tuple(
            sum(self._comp_points(c, w, g) for c, g in sorted(groups.items()))
            for w in range(self.weeks)
        )
        self._cache[ids] = res
        return res

    def value(self, ids: frozenset[str]) -> float:
        return sum(w * v for w, v in zip(self.inp.week_weights, self.points(ids), strict=True))

    def fill(self, ids: frozenset[str]) -> int:
        total = 0
        for c, g in self._split(ids).items():
            key = (c, g)
            hit = self._fill_cache.get(key)
            if hit is None:
                hit = len(self._solve(c, [self._fill_players[i] for i in sorted(g)]))
                self._fill_cache[key] = hit
            total += hit
        return total

    def plan_bound(
        self,
        *,
        fixed: frozenset[str],
        adds: frozenset[str],
        optional: frozenset[str],
        pool: Collection[str],
        cap: int,
        room: int,
        budget: float | None,
        target: float,
        start: tuple[float, float, float] | None = None,
    ) -> tuple[float, tuple[float, float, float]]:
        """Upper bound on ``V(final)`` over every plan reachable from here.

        ``final = fixed ∪ adds ∪ K``, ``K`` drawn from ``optional`` (the
        droppable roster players; the ones left out are the drops) and
        ``pool`` (free agents still available), with three side constraints:

        * at most ``cap`` players of ``adds ∪ K`` (the roster has that many
          places for them once the forced drops are made);
        * at most ``room`` from ``pool``;
        * the dynasty budget: ``dyn(optional) − dyn(adds ∪ K) <= budget``
          (``None`` = no budget).

        All three are relaxed into the objective with multipliers
        ``(ν, μ, λ) >= 0`` (Lagrangian duality).  For fixed multipliers a
        player's worth splits into a KEEP part (``ν·dyn − μ``, minus ``λ`` for
        a free agent), paid once whether or not he starts, and his points
        when he starts; a keep part below zero is charged to his starts, so
        what remains is one lineup solve per week by the canonical owner with
        per-player weights.  Every multiplier triple gives a valid upper
        bound (weak duality); they are improved by projected subgradient
        steps with Polyak step lengths toward ``target``, the smallest value
        found is returned, and the loop stops early once it is at or below
        ``target`` (the caller can prune).  ``start`` warm-starts the
        multipliers (a parent node's are close to its children's); the
        multipliers that gave the returned bound come back with it so the
        caller can pass them on.  Points are floored at 0 inside
        the bound and, over several weeks, a negative keep part is spread
        across weeks in proportion to their weights, both of which only
        loosen it.
        """
        cap = max(0, int(cap))
        room = max(0, int(room))
        pool_set = frozenset(pool) - fixed - adds - optional
        movable = optional | pool_set
        everyone = fixed | adds | movable
        weights = self.inp.week_weights
        total_weight = sum(weights)
        dyn = {i: _dyn(self.players[i]) for i in adds | movable}
        scale = max([1.0, *dyn.values()])
        dyn_opt = sum(dyn[i] for i in optional) / scale
        beta = None if budget is None else float(budget) / scale
        groups = self._split(everyone)
        touched = sorted({self.comp_of[i] for i in adds | movable})
        fixed_part = [
            sum(self._comp_points(c, w, g) for c, g in groups.items() if c not in touched)
            for w in range(self.weeks)
        ]
        floored = [
            {
                i: max(0.0, float(self._per_week[w][i].ros_value))
                for i in everyone
                if self._per_week[w][i].ros_value is not None
            }
            for w in range(self.weeks)
        ]

        def evaluate(nu: float, mu: float, lam: float) -> tuple[float, tuple[float, float, float]]:
            keep = {}
            for i in adds:
                keep[i] = nu * dyn[i] / scale - mu
            for i in movable:
                keep[i] = nu * dyn[i] / scale - mu - (lam if i in pool_set else 0.0)
            value = (
                (0.0 if beta is None else nu * (beta - dyn_opt))
                + mu * cap
                + lam * room
                + sum(keep[i] for i in adds)
                + sum(max(0.0, keep[i]) for i in movable)
            )
            started: set[str] = set()
            for w, weight in enumerate(weights):
                week_value = fixed_part[w]
                for c in touched:
                    # Players with identical slot eligibility can fill at most
                    # as many slots as they share, so only the best that many
                    # of each such group can start (exchange argument); the
                    # rest are left out of the solve, which is exact.
                    by_sig: dict[tuple[int, ...], list[tuple[float, str]]] = {}
                    for i in groups.get(c, frozenset()):
                        pts = floored[w].get(i)
                        if pts is None:
                            continue
                        if i in movable and keep[i] < 0 and total_weight > 0:
                            pts += keep[i] / total_weight
                        if pts > 0:
                            by_sig.setdefault(self._sig[i], []).append((-pts, i))
                    roster = []
                    for sig, members in by_sig.items():
                        members.sort()
                        for neg, i in members[: len(sig)]:
                            roster.append(_with_points(self._per_week[w][i], -neg))
                    assignment = self._solve(c, roster)
                    self.calls += 1
                    for p in assignment.values():
                        week_value += float(p.ros_value or 0.0)
                        started.add(p.player_id)
                value += weight * week_value
            kept = set(adds) | {i for i in movable if keep[i] > 0 or i in started}
            g_nu = 0.0 if beta is None else sum(dyn[i] for i in kept) / scale - dyn_opt + beta
            g_mu = cap - len(kept)
            g_lam = room - len(kept & pool_set)
            return value, (g_nu, float(g_mu), float(g_lam))

        nu, mu, lam = start if start is not None else (0.0, 0.0, 0.0)
        if beta is None:
            nu = 0.0
        best = float("inf")
        best_at = (nu, mu, lam)
        for _ in range(_BOUND_STEPS):
            value, (g_nu, g_mu, g_lam) = evaluate(nu, mu, lam)
            if value < best:
                best, best_at = value, (nu, mu, lam)
            if best <= target + _EPS:
                break
            # Subgradient of the dual at (ν, μ, λ); step toward smaller values.
            norm = g_nu * g_nu + g_mu * g_mu + g_lam * g_lam
            if norm <= 0:
                break  # the relaxed optimum is feasible and complementary: exact
            step = (value - target) / norm
            nu = max(0.0, nu - step * g_nu)
            mu = max(0.0, mu - step * g_mu)
            lam = max(0.0, lam - step * g_lam)
        return best, best_at


def _with_points(p: RosterPlayer, value: float) -> RosterPlayer:
    return RosterPlayer(
        player_id=p.player_id,
        canonical_name=p.canonical_name,
        position=p.position,
        ros_value=value,
        fantasy_positions=p.fantasy_positions,
    )


def _week(p: StreamPlayer, w: int) -> float | None:
    if w >= len(p.weekly_points):
        return None
    v = p.weekly_points[w]
    return None if v is None else float(v)


def _dyn(p: StreamPlayer) -> float:
    return float(p.dynasty_value) if p.dynasty_value is not None else 0.0


class _Search:
    """Depth-first branch-and-bound over add sets, with the best drop set for
    each, under one dynasty budget (``None`` = no budget)."""

    def __init__(
        self,
        inp: SolverInput,
        ev: _Evaluator,
        *,
        budget: float | None,
        start: StreamPlan | None = None,
        node_limit: int | None = None,
    ) -> None:
        self.inp = inp
        self.node_limit = int(inp.node_limit if node_limit is None else node_limit)
        self.ev = ev
        self.budget = budget
        self.roster_ids = frozenset(p.player_id for p in inp.roster)
        self.base_value = ev.value(self.roster_ids)
        self.base_fill = ev.fill(self.roster_ids)
        self.droppable = sorted(i for i in inp.droppable_ids if i in self.roster_ids)
        self.droppable_set = frozenset(self.droppable)
        self.fixed = self.roster_ids - self.droppable_set
        self.nodes = 0
        self.truncated = False
        self.best: StreamPlan | None = start
        self.plans: dict[tuple, StreamPlan] = {}
        self._warm: tuple[float, float, float] | None = None
        self._drop_warm: tuple[float, float, float] | None = None

    def _over_limit(self) -> bool:
        if self.nodes >= self.node_limit:
            self.truncated = True
            return True
        return False

    def _incumbent(self) -> float:
        return self.best.weekly_gain if self.best else 0.0

    def _within_budget(self, loss: float) -> bool:
        return self.budget is None or loss <= self.budget + _EPS

    def _consider(self, plan: StreamPlan) -> None:
        if not self._within_budget(plan.net_dynasty_loss):
            return
        self.plans[(plan.adds, plan.drops)] = plan
        if self.best is None or plan.key() < self.best.key():
            self.best = plan

    def _bound(self, adds: frozenset[str], pool: Sequence[str], room: int) -> float:
        """Upper bound on the gain of any plan holding ``adds`` plus at most
        ``room`` more from ``pool`` (forced drops and the budget included)."""
        # E ∪ adds keeps |E| + min(adds, open) places on the final roster:
        # every add beyond the open spots forces one drop.
        cap = len(self.droppable) + min(len(adds) + room, int(self.inp.open_spots))
        value, self._warm = self.ev.plan_bound(
            fixed=self.fixed,
            adds=adds,
            optional=self.droppable_set,
            pool=pool,
            cap=cap,
            room=room,
            budget=self.budget,
            target=self.base_value + self._incumbent(),
            start=self._warm,
        )
        return value - self.base_value

    def _forced(self, n_adds: int) -> int:
        return max(0, n_adds - int(self.inp.open_spots))

    def _plan(
        self, adds: tuple[str, ...], drops: tuple[str, ...], final: frozenset[str]
    ) -> StreamPlan:
        players = self.ev.players
        pts = self.ev.points(final)
        base = self.ev.points(self.roster_ids)
        gain_by_week = tuple(a - b for a, b in zip(pts, base, strict=True))
        gain = sum(w * g for w, g in zip(self.inp.week_weights, gain_by_week, strict=True))
        loss = sum(_dyn(players[d]) for d in drops) - sum(_dyn(players[a]) for a in adds)
        faab = sum(int(players[a].bid) for a in adds)
        return StreamPlan(
            adds=tuple(sorted(adds)),
            drops=tuple(sorted(drops)),
            weekly_gain=gain,
            gain_by_week=gain_by_week,
            net_dynasty_loss=loss,
            faab_total=faab,
        )

    def _every_add_starts(self, adds: Sequence[str], final: frozenset[str]) -> bool:
        v = self.ev.value(final)
        return all(v > self.ev.value(final - {a}) + _EPS for a in adds)

    def _try(
        self, adds: tuple[str, ...], drops: tuple[str, ...], t_ids: frozenset[str]
    ) -> StreamPlan | None:
        final = t_ids - set(drops)
        if drops and self.ev.fill(final) < self.base_fill:
            return None
        if not self._every_add_starts(adds, final):
            return None
        plan = self._plan(adds, drops, final)
        self._consider(plan)
        return plan

    def evaluate_adds(self, adds: tuple[str, ...]) -> None:
        """Best drop set for this add set, recorded as a plan.

        First the Lagrangian bound over every drop set at once
        (:meth:`_Evaluator.plan_bound`, budget included) can rule the add set
        out without looking at a single drop set, as can a tie on points that
        even the cheapest forced drops would make more expensive than the
        incumbent.  Otherwise two depth-first passes over the droppable
        players choose the ``m`` forced drops (see the module docstring):
        pass 1 the best points, pass 2 the cheapest set reaching them.
        """
        players = self.ev.players
        m = self._forced(len(adds))
        t_ids = frozenset(self.roster_ids | set(adds))
        if m == 0:
            self.nodes += 1
            self._try(adds, (), t_ids)
            return
        if len(self.droppable) < m:
            return
        upper = self._bound(frozenset(adds), (), 0)
        if upper < self._incumbent() - _EPS:
            return
        credit = sum(_dyn(players[a]) for a in adds)
        if self.best is not None and upper <= self.best.weekly_gain + _EPS:
            cheapest = sum(sorted(_dyn(players[e]) for e in self.droppable)[:m])
            if cheapest - credit > self.best.net_dynasty_loss + _EPS:
                return  # at best ties the incumbent's points at a higher dynasty cost
        t_value = self.ev.value(t_ids)
        loss = {e: t_value - self.ev.value(t_ids - {e}) for e in self.droppable}
        limit = None if self.budget is None else credit + self.budget
        best_here: list[tuple[float, float]] = []  # [(gain, drop dynasty value)]

        def search(order: list[str], seek_cost: bool) -> None:
            """Pass 1 (``seek_cost`` False): the best gain, ties pruned.
            Pass 2: the cheapest drop set reaching that gain."""
            dyn_of = [_dyn(players[e]) for e in order]
            cheapest_tail = [sorted(dyn_of[i:]) for i in range(len(order) + 1)]

            def rec(idx: int, dropped: tuple[str, ...], spent: float) -> None:
                if self.truncated or self._over_limit():
                    return
                self.nodes += 1
                r = m - len(dropped)
                if r == 0:
                    if limit is not None and spent > limit + _EPS:
                        return
                    plan = self._try(adds, dropped, t_ids)
                    if plan is not None and (
                        not best_here
                        or plan.weekly_gain > best_here[0][0] + _EPS
                        or (
                            plan.weekly_gain >= best_here[0][0] - _EPS
                            and spent < best_here[0][1] - _EPS
                        )
                    ):
                        best_here[:] = [(plan.weekly_gain, spent)]
                    return
                rest = order[idx:]
                if len(rest) < r:
                    return
                least = spent + sum(cheapest_tail[idx][:r])
                if limit is not None and least > limit + _EPS:
                    return
                if best_here and seek_cost and least > best_here[0][1] + _EPS:
                    return  # cannot reach the best gain more cheaply
                target = max(self._incumbent(), best_here[0][0] if best_here else -float("inf"))
                upper, self._drop_warm = self.ev.plan_bound(
                    fixed=t_ids - set(dropped) - set(rest),
                    adds=frozenset(),
                    optional=frozenset(rest),
                    pool=(),
                    cap=len(rest) - r,
                    room=0,
                    budget=None,
                    target=self.base_value + target,
                    start=self._drop_warm,
                )
                upper -= self.base_value
                if upper < self._incumbent() - _EPS:
                    return
                if (
                    self.best is not None
                    and upper <= self.best.weekly_gain + _EPS
                    and least - credit > self.best.net_dynasty_loss + _EPS
                ):
                    return  # at best a tie on points with the incumbent, at a higher dynasty cost
                if best_here:
                    gain = best_here[0][0]
                    if upper < gain - _EPS or (not seek_cost and upper <= gain + _EPS):
                        return
                for i in range(idx, len(order) - r + 1):
                    rec(i + 1, (*dropped, order[i]), spent + dyn_of[i])
                    if self.truncated:
                        return

            rec(0, (), 0.0)

        # Pass 1 visits high-value keeps first (smallest single-removal loss
        # dropped first); pass 2 visits cheap drops first.
        search(
            sorted(self.droppable, key=lambda e: (round(loss[e], 9), _dyn(players[e]), e)), False
        )
        if best_here:
            search(
                sorted(self.droppable, key=lambda e: (_dyn(players[e]), round(loss[e], 9), e)),
                True,
            )

    def run(self, candidates: list[tuple[str, float]], k: int) -> float | None:
        """Depth-first over add sets; returns the unexplored bound gap if truncated."""
        players = self.ev.players
        balance = self.inp.faab_balance
        single_week = len(self.inp.week_weights) == 1

        def dfs(start: int, adds: tuple[str, ...], spent: int) -> None:
            if self.truncated:
                return
            if adds:
                self.evaluate_adds(adds)
            if len(adds) >= k or self._over_limit():
                return
            held = frozenset(adds)
            current = self.ev.value(self.roster_ids | held) - self.base_value
            for i in range(start, len(candidates)):
                pid, _ = candidates[i]
                bid = int(players[pid].bid)
                if balance is not None and spent + bid > balance:
                    continue
                if balance is None and bid > 0:
                    continue
                if single_week and self.ev.fill(held | {pid}) <= len(adds):
                    # One week: every add must start, so the adds must fit in
                    # the lineup together, and no superset of a set that cannot
                    # fit can either.  (Over several weeks two adds may start in
                    # different weeks, so this does not apply.)
                    continue
                room = k - len(adds)
                incumbent = self._incumbent()
                upper = current + sum(g for _, g in candidates[i : i + room])
                if upper < incumbent - _EPS or upper <= _EPS:
                    break  # descending g: later starts are no better, and <= 0 is no move
                # The solo-gain sum ignores competition for slots, the forced
                # drops and the budget; the Lagrangian bound does not.  It is
                # computed over the pool from i on, so it also bounds every
                # later start.
                upper = self._bound(held, [c for c, _ in candidates[i:]], room)
                if upper < incumbent - _EPS or upper <= _EPS:
                    break
                if self._over_limit():
                    return
                self.nodes += 1
                dfs(i + 1, (*adds, pid), spent + bid)

        dfs(0, (), 0)
        if not self.truncated:
            return None
        # The bound over every plan at once is valid however far the search got.
        self.truncated = False  # let the bound run; restored below
        root = self._bound(frozenset(), [c for c, _ in candidates], k)
        self.truncated = True
        return max(0.0, root - self._incumbent())


def _candidates(inp: SolverInput, ev: _Evaluator) -> tuple[list[tuple[str, float]], dict[str, str]]:
    roster_ids = frozenset(p.player_id for p in inp.roster)
    base = ev.value(roster_ids)
    excluded: dict[str, str] = {}
    out: list[tuple[str, float]] = []
    for p in sorted(inp.free_agents, key=lambda x: x.player_id):
        if p.player_id in roster_ids:
            excluded[p.player_id] = "already_rostered"
            continue
        if all(_week(p, w) is None for w in range(len(inp.week_weights))):
            excluded[p.player_id] = "unprojected"
            continue
        if inp.faab_balance is None and int(p.bid) > 0:
            excluded[p.player_id] = "faab_balance_unknown_paid_claim"
            continue
        if inp.faab_balance is not None and int(p.bid) > inp.faab_balance:
            excluded[p.player_id] = "bid_exceeds_balance"
            continue
        g = ev.value(roster_ids | {p.player_id}) - base
        out.append((p.player_id, max(0.0, g)))
    out = _undominated(inp, ev, out, excluded)
    out.sort(key=lambda t: (-t[1], t[0]))
    return out, excluded


def _dominates(a: StreamPlayer, b: StreamPlayer, weeks: int) -> bool:
    """``a`` is at least as good as ``b`` everywhere, strictly or by id."""
    if a.eligible_signature() != b.eligible_signature():
        return False
    pa = [_week(a, w) for w in range(weeks)]
    pb = [_week(b, w) for w in range(weeks)]
    for x, y in zip(pa, pb, strict=True):
        if y is None:
            continue
        if x is None or x < y:
            return False
    if _dyn(a) < _dyn(b) or int(a.bid) > int(b.bid):
        return False
    strictly = (
        any((x is not None and (y is None or x > y)) for x, y in zip(pa, pb, strict=True))
        or _dyn(a) > _dyn(b)
        or int(a.bid) < int(b.bid)
    )
    return strictly or a.player_id < b.player_id


def _undominated(
    inp: SolverInput,
    ev: _Evaluator,
    cands: list[tuple[str, float]],
    excluded: dict[str, str],
) -> list[tuple[str, float]]:
    k = max(0, int(inp.max_adds))
    weeks = len(inp.week_weights)
    players = ev.players
    kept: list[tuple[str, float]] = []
    for pid, g in cands:
        me = players[pid]
        dominators = sum(
            1 for other, _ in cands if other != pid and _dominates(players[other], me, weeks)
        )
        if k > 0 and dominators >= k:
            excluded[pid] = "dominated"
            continue
        kept.append((pid, g))
    return kept


def solve_streaming(
    inp: SolverInput,
    *,
    alternatives: int = 5,
    unbudgeted: bool = True,
    start: StreamPlan | None = None,
) -> SolverResult:
    """The best weekly add/drop plan under every constraint, or "no move".

    ``status`` describes the budgeted answer only.  ``unbudgeted`` also runs
    the search with the dynasty budget lifted (what a larger budget would
    buy), under its own node limit (:data:`UNBUDGETED_NODE_SHARE` of
    ``node_limit``) and with its own status, so an expensive side question can
    never make the main answer "bounded".  ``start`` seeds the incumbent with
    a known feasible plan (the capacity curve passes the previous capacity's
    answer); it only speeds the search, the answer is the same.
    """
    if len(inp.week_weights) == 0:
        raise ValueError("week_weights must name at least one week")
    if inp.dynasty_budget < 0:
        raise ValueError("dynasty_budget must be >= 0 (a budget, not a target)")
    if any(w < 0 for w in inp.week_weights):
        raise ValueError("week_weights must be >= 0")
    ev = _Evaluator(inp)
    candidates, excluded = _candidates(inp, ev)
    k = max(0, int(inp.max_adds))

    budget = float(inp.dynasty_budget)
    seed = start if start is not None and start.net_dynasty_loss <= budget + _EPS else None
    search = _Search(inp, ev, budget=budget, start=seed)
    gap = search.run(candidates, k) if k > 0 else None
    best = search.best
    status = STATUS_BOUNDED if search.truncated else STATUS_OPTIMAL

    free_best: StreamPlan | None = None
    free_status: str | None = None
    free_nodes = 0
    if unbudgeted and k > 0:
        # Started from the budgeted answer, which is feasible there too.
        free = _Search(
            inp,
            ev,
            budget=None,
            start=best,
            node_limit=max(1, int(inp.node_limit * UNBUDGETED_NODE_SHARE)),
        )
        free.run(candidates, k)
        free_best = free.best
        free_status = STATUS_BOUNDED if free.truncated else STATUS_OPTIMAL
        free_nodes = free.nodes

    recommend = best is not None and best.weekly_gain >= max(inp.materiality, _EPS)
    alts = sorted(
        (p for p in search.plans.values() if best is None or p != best),
        key=StreamPlan.key,
    )[:alternatives]
    notes = []
    if status == STATUS_BOUNDED:
        notes.append(
            f"search stopped at node_limit={inp.node_limit}; the plan shown is the best found, "
            "not proven optimal"
        )
    if free_status == STATUS_BOUNDED:
        notes.append(
            "the larger-budget comparison stopped at its node limit: best found, not proven"
        )
    if best is not None and not recommend:
        notes.append(
            f"best plan gains {best.weekly_gain:.2f} projected points, below the materiality "
            f"threshold {inp.materiality:.2f}: no move"
        )
    unbudgeted_plan = free_best
    if unbudgeted_plan is not None and (
        unbudgeted_plan.weekly_gain <= _EPS
        or (best is not None and unbudgeted_plan.key() == best.key())
    ):
        unbudgeted_plan = None  # no gain at any budget, or the budget did not bind
    return SolverResult(
        status=status,
        baseline_points=ev.points(search.roster_ids),
        best=best if recommend else None,
        recommend_move=recommend,
        best_unbudgeted=unbudgeted_plan,
        alternatives=([best] if best is not None and not recommend else []) + alts,
        excluded_free_agents=excluded,
        bound_gap=gap,
        nodes=search.nodes + free_nodes,
        notes=notes,
        unbudgeted_status=free_status,
    )


def capacity_curve(inp: SolverInput, *, max_k: int = 7) -> list[dict[str, Any]]:
    """Best plan at each streaming capacity k = 0..max_k (diminishing returns).

    Each row is a full solve at that capacity, so a later k can only match or
    beat an earlier one; ``marginalGain`` is the step from k-1.  Nothing here
    adds future weeks' theoretical streams: a spot's value is its gain over
    the horizon the caller supplied, counted once.
    """
    rows: list[dict[str, Any]] = []
    prev = 0.0
    seed: StreamPlan | None = None
    for k in range(0, max_k + 1):
        res = solve_streaming(
            SolverInput(**{**inp.__dict__, "max_adds": k, "materiality": 0.0}),
            alternatives=0,
            unbudgeted=False,
            start=seed,
        )
        seed = res.best or seed
        gain = res.best.weekly_gain if res.best is not None else 0.0
        rows.append(
            {
                "capacity": k,
                "bestGainPoints": round(gain, 3),
                "marginalGainPoints": round(gain - prev, 3),
                "netDynastyLoss": (
                    round(res.best.net_dynasty_loss, 1) if res.best is not None else 0.0
                ),
                "adds": list(res.best.adds) if res.best is not None else [],
                "drops": list(res.best.drops) if res.best is not None else [],
                "status": res.status,
            }
        )
        prev = max(prev, gain)
    return rows


def recommended_capacity(rows: Sequence[Mapping[str, Any]], *, materiality: float) -> int:
    """Largest k whose every step up to it gained at least ``materiality``."""
    k = 0
    for row in rows[1:]:
        if float(row["marginalGainPoints"]) >= materiality and materiality >= 0:
            k = int(row["capacity"])
        else:
            break
    return k
