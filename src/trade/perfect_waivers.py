"""Perfect Waivers — the jointly optimal add/drop COMBINATION (C7-WAIV-01).

What this answers
=================
*Given this team's roster, its open roster spots, its FAAB balance and the
free agents on the wire, which SET of adds and drops leaves the roster best
off?*  Not "who is the best free agent" — that question is
``/api/waiver/suggestions``.  This is the inventory's row 3.3/3.4: the best
combination for the whole roster, with a stop rule, and every add paired with
the release it actually displaces instead of every add being paired with the
same lowest-valued body.

It is advice.  Nothing here executes, submits or schedules a waiver claim.

Nothing here is a second owner
===============================
Every number this module combines is produced elsewhere and consumed as is:

* **value** — ``rankDerivedValue``, the canonical board, and nothing else.
  The release cost of a rostered player is his board value with scarcity
  inert, which is the ladder-model ``releaseCost`` Perfect Draft uses
  (``frontend/lib/perfect-draft.js``) evaluated with the C2-DROP-01 default
  (``src/roster_intel/droppability.py``: scarcity not supplied, multiplier
  1.0).  It is obtained from ``displacement.effective_cut_cost`` so the
  basis stamp (``board`` / ``assumedWaiver``) is the owner's.  Not the ECC:
  ECC is measured OVER waiver level, and an add here is the waiver player
  itself, so ECC on the cost side would take the waiver credit twice — the
  exact defect Perfect Draft's ladder amendment documents.
* **lineup legality** — ``src/ros/lineup.py::solve_optimal_assignment``,
  the exact solver, with the league's own slots and configured flex rule.
  The legality RULE is the cut ladder's (``build_cut_ladder``): a roster
  may not fill fewer starting slots than it does today.
* **FAAB bids** — ``src/trade/faab_engine.py`` through
  ``waiver.find_waiver_targets`` (the same market-aware path
  ``/api/waiver/suggestions`` runs).  No second formula, and no
  dollar-to-value exchange rate: dollars are a CONSTRAINT (sum of the
  engine's recommended bids <= the team's balance), value is the objective.
  The engine has already priced the option value of a dollar into the bid.
* **roster capacity / taxi** — ``src/trade/roster_capacity.py``.
* **protections** — ``src/trade/constraints.py`` (C3-CON-01/02): a player
  the user protects is never proposed as a drop.
* **the uncertainty band of the stop rule** —
  ``config/trade/perfect_waivers.json::stopBand``, a declared PRIOR of this
  feature's own (initialised 2026-10-08 from the confidence gate's
  ``AGREEMENT_VALUE_RATIO``, deliberately NOT read from it: that gate keeps
  its own entry so confidence and other surfaces can diverge on purpose).
  Missing or malformed config refuses — there is no code default.

The problem, exactly
====================
Let ``R`` be the roster, ``T`` one token per open roster spot, ``F`` the
free-agent candidates.  A plan is the set ``K`` the team ends up holding::

    maximize   sum V(a) for adds a in K∩F  -  sum c(d) for drops d in R\\K
    subject to |K| = |R| + open                   (roster capacity)
               slots K can fill >= slots R fills  (lineup legality)
               sum bid(a) over K∩F <= balance      (FAAB budget)
               protected / unpriced players in K   (never proposed as drops)

**Without the budget this is a matroid problem, solved exactly.**  Slot
eligibility makes the rostered players a transversal matroid ``M``.  The
sets of size ``|R| + open`` whose ``M``-rank reaches today's fill ``r`` are
the bases of a matroid — the elongation of ``M`` truncated at ``r`` — so the
best plan is a maximum-weight basis, and reverse-delete greedy (remove the
cheapest element whose removal keeps the set spanning) finds it exactly.
This is the same matroid argument ``displacement.py`` makes for its cut
ladder, extended to a ground set that contains the adds: adding a tight end
is what can make releasing your only tight end legal, which a cut ladder
built on today's roster can never see.  That interaction IS the matching
problem the inventory names, and it is why the Perfect Draft
k-decomposition (displacement cost a function of the count alone) does not
transfer directly: here the cost of the j-th drop depends on WHICH adds were
made.  When no add changes legality, the two coincide (pinned by test).

**The budget makes it a knapsack, handled by exhaustive branch-and-bound.**
Only paid claims (engine bid > 0) touch the budget.  Each node solves the
matroid relaxation with some paid claims forced in and some excluded; if the
relaxation's paid claims fit the balance the node is solved exactly,
otherwise it branches on the most expensive one.  A node's bound is the
smaller of that relaxation and the Lagrangian bound at the root multiplier
(the budget priced into each claim's weight) — both valid upper bounds for
the subtree, so pruning is exact.  The search is bounded by ``node_limit``;
if it is reached the result is labelled ``node_limit`` with the remaining
bound gap — **never** passed off as optimal, and there is no greedy fallback
anywhere.  Measured on the 2026-10-07 archive board (12 teams, 58-man
rosters, ~245 free agents): the engine prices every candidate at $0, so all
12 plans close at the root in 0.1-0.2 s.  Under a synthetic stress (every
candidate bid $0-$45, balances $10/$30/$100) every plan still proved optimal
within 222 nodes and 3.5 s.

Two exact reductions keep the ground set small (both proven in the code):

* at most ``open + #{droppable d : rho·c(d) <= max V}`` free agents can be
  in any optimal plan (every add is paired with a distinct open spot or
  release it out-values — see the pairing below), and
* within one lineup-eligibility class, a free agent with at least that many
  unpruned rivals that are worth as much and cost no more can never be
  needed.

The stop rule
=============
"Stop when the next marginal move's gain is <= 0 or within the uncertainty."
A move that releases ``d`` for ``a`` is MATERIAL when ``V(a) > c(d)`` and
their relative gap ``|V(a) − c(d)| / mean`` exceeds the agreement ratio
``t``.  Algebraically that is ``V(a) > rho·c(d)`` with
``rho = (2 + t) / (2 − t)``, so the optimizer scores a kept roster player at
``rho·c(d)`` instead of ``c(d)``.  Its optimum therefore stops exactly where
the next move stops being material:

* every (add, drop) pair it returns is material — by Brualdi's bijective
  basis exchange there is a pairing ``sigma`` with ``K − a + sigma(a)`` a
  legal, budget-feasible plan for every add, and optimality gives
  ``rho·c(sigma(a)) <= V(a)``; and
* no further single move is material, else it would raise the objective.

An add into an OPEN spot releases nothing, so it is material whenever the
player has value.  Reported totals use the raw values; ``rho`` only decides.

The pairing is the matching
===========================
Waiver claims succeed and fail independently, so a pair must be legal in
BOTH directions: if only this claim fails (``K − a + d``) and if only this
claim wins (``K0 − d + a``).  An edge ``(a, d)`` requires both, and the
assignment solve picks a perfect matching on those edges.  One always exists
here: the matroid is a gammoid (a transversal matroid, truncated and
elongated, plus loops), gammoids are strongly base orderable, and a strongly
base orderable matroid has a bijection valid for EVERY subset of exchanges —
in particular for "only this one fails" and "only this one wins".  The
tests verify existence by brute force; if the solve ever returned an edge
that fails either check, the pair is labelled ``standsAlone: false`` rather
than claimed.  Pairing every add with "my lowest-valued player" guarantees
neither direction.

Missing is never zero
=====================
* A rostered player the board did not price is never proposed as a drop
  (his value is unknown, not zero) and still occupies a spot and can still
  fill a slot.
* A free agent the board did not price is not a candidate; the census is
  reported.
* An unknown roster cap makes NO capacity claim: the plan is restricted to
  capacity-neutral swaps.  An unknown taxi occupancy plans against the
  fewest open spots and says the drops are an upper bound.
* An unknown FAAB balance makes NO budget claim: paid claims are withheld
  from the plan and listed as such.

Pure computation apart from the owners it calls.  No I/O, no clock.
"""

from __future__ import annotations

import heapq
import itertools
import json
import math
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.ros.lineup import RosterPlayer, precompute_slot_eligibility, solve_optimal_assignment

__all__ = [
    "DEFAULT_NODE_LIMIT",
    "PERFECT_WAIVERS_VERSION",
    "FreeAgentCandidate",
    "RosterCandidate",
    "SolveResult",
    "build_perfect_waivers",
    "PerfectWaiversConfigError",
    "STOP_BAND_SOURCE",
    "load_stop_band",
    "materiality_multiplier",
    "solve_perfect_waivers",
]

PERFECT_WAIVERS_VERSION = "perfect-waivers/2026-10-08.v1"

#: Branch-and-bound node budget.  A search that reaches it reports
#: ``status: "node_limit"`` with its bound gap rather than claiming an optimum.
DEFAULT_NODE_LIMIT = 2000

_EPS = 1e-9

#: How many of the best unplanned free agents ``_next_move`` examines.  It is
#: an EXPLANATION of the stop, not part of the optimization.
_NEXT_MOVE_CANDIDATES = 40

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "trade" / "perfect_waivers.json"
#: Where the stop band comes from, stamped on every payload.
STOP_BAND_SOURCE = "config/trade/perfect_waivers.json::stopBand"


class PerfectWaiversConfigError(RuntimeError):
    """The feature's declared parameters are missing or malformed.

    Raised rather than defaulted: a stop band nobody declared is a decision
    nobody made.
    """


def load_stop_band(path: Path | None = None) -> float:
    """``stopBand`` from ``config/trade/perfect_waivers.json`` — or refuse."""
    target = Path(path) if path is not None else _CONFIG_PATH
    try:
        doc = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PerfectWaiversConfigError(f"{target}: unreadable ({exc})") from exc
    if not isinstance(doc, dict):
        raise PerfectWaiversConfigError(f"{target}: not an object")
    band = doc.get("stopBand")
    if isinstance(band, bool) or not isinstance(band, (int, float)) or not 0.0 <= band < 2.0:
        raise PerfectWaiversConfigError(f"{target}: stopBand missing or out of range: {band!r}")
    if doc.get("stopBandClass") != "PRIOR":
        raise PerfectWaiversConfigError(f"{target}: stopBand must be declared stopBandClass PRIOR")
    return float(band)


#: Bisection steps for the root Lagrangian multiplier.  Any multiplier gives a
#: valid bound; more steps only tighten it.
_LAGRANGE_STEPS = 16

_KIND_FA = "fa"
_KIND_OPEN = "open"
_KIND_ROSTER = "roster"
# Removal order on equal weight: give up a free agent before an open spot,
# and an open spot before a rostered player — a tie never manufactures a move.
_KIND_RANK = {_KIND_FA: 0, _KIND_OPEN: 1, _KIND_ROSTER: 2}


# ── Inputs ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RosterCandidate:
    """One rostered player."""

    player_id: str
    name: str
    position: str
    #: ``rankDerivedValue``.  ``None`` when the board did not price him.
    value: float | None
    fantasy_positions: tuple[str, ...] = ()
    #: Why he may never be proposed as a drop (protection, unpriced, ...).
    locked_reason: str | None = None


@dataclass(frozen=True)
class FreeAgentCandidate:
    """One signable free agent, priced by the board and by the FAAB engine."""

    player_id: str
    name: str
    position: str
    #: ``rankDerivedValue`` (> 0 — unpriced players are not candidates).
    value: float
    #: The FAAB engine's recommended bid, whole dollars, >= 0.
    bid: int
    fantasy_positions: tuple[str, ...] = ()
    #: The engine's full bid block, passed through for display.
    bid_detail: Mapping[str, Any] = field(default_factory=dict)


def materiality_multiplier(ratio: float) -> float:
    """``rho`` such that ``V > rho·c``  <=>  ``V > c`` and relgap(V, c) > ratio.

    ``relgap(V, c) = (V − c) / ((V + c) / 2)`` — the board's symmetric-mean gap
    convention (``src/api/confidence.py::_relative_gap``).  Solving
    ``(V − c) / ((V + c) / 2) > t`` for ``V`` gives ``V (2 − t) > c (2 + t)``.
    """
    t = float(ratio)
    if not (0.0 <= t < 2.0):
        raise ValueError(f"materiality ratio must be in [0, 2), got {ratio!r}")
    return (2.0 + t) / (2.0 - t)


# ── The solver ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class _Element:
    key: str
    kind: str
    #: Objective weight: V for an add, rho·c for a kept roster player, 0 for
    #: an open spot.
    weight: float
    #: Raw quantity for reporting: V for an add, c for a release, 0 open.
    raw: float
    bid: int
    locked: bool
    #: ``None`` for an element that can fill no starting slot.
    lineup: RosterPlayer | None


@dataclass
class SolveResult:
    """The plan and how it was established."""

    status: str
    proven_optimal: bool
    nodes: int
    node_limit: int
    kept: frozenset[str]
    objective: float
    upper_bound: float | None
    baseline_fill: int
    final_fill: int
    adds: list[FreeAgentCandidate]
    drops: list[RosterCandidate]
    open_spots_used: int
    pairs: list[dict[str, Any]]
    next_move: dict[str, Any] | None
    pruned_free_agents: int
    add_bound: int
    notes: list[str]


class _Problem:
    def __init__(
        self,
        roster: Sequence[RosterCandidate],
        free_agents: Sequence[FreeAgentCandidate],
        *,
        slots: Sequence[str],
        slot_eligibility: Mapping[str, Collection[str]] | None,
        open_spots: int,
        rho: float,
    ) -> None:
        self.slots = [str(s) for s in slots if s]
        self.slot_eligibility = slot_eligibility or None
        self.rho = rho
        self.elements: dict[str, _Element] = {}
        self.roster_by_key: dict[str, RosterCandidate] = {}
        self.fa_by_key: dict[str, FreeAgentCandidate] = {}

        lineup_players: list[RosterPlayer] = []
        for i, rc in enumerate(roster):
            key = f"r:{i}:{rc.player_id}"
            priced = isinstance(rc.value, (int, float)) and rc.value > 0
            cost = float(rc.value) if priced else 0.0
            # Assignment weight steers WHICH maximum matching the solver
            # returns (heavy players preferred, so a cheap element is rarely
            # matched and its removal needs no re-solve); it cannot change
            # HOW MANY slots are filled.  An unpriced body still fills a slot
            # legally — the displacement owner's FEASIBILITY_OBJECTIVE point.
            weight = rho * cost
            lp = RosterPlayer(
                player_id=key,
                canonical_name=rc.name,
                position=rc.position or "",
                ros_value=weight,
                fantasy_positions=tuple(rc.fantasy_positions or ()),
            )
            lineup_players.append(lp)
            self.roster_by_key[key] = rc
            self.elements[key] = _Element(
                key=key,
                kind=_KIND_ROSTER,
                weight=weight,
                raw=cost,
                bid=0,
                locked=bool(rc.locked_reason) or not priced,
                lineup=lp,
            )
        for i in range(max(0, int(open_spots))):
            key = f"open:{i}"
            self.elements[key] = _Element(
                key=key, kind=_KIND_OPEN, weight=0.0, raw=0.0, bid=0, locked=False, lineup=None
            )
        for i, fa in enumerate(free_agents):
            key = f"f:{i}:{fa.player_id}"
            lp = RosterPlayer(
                player_id=key,
                canonical_name=fa.name,
                position=fa.position or "",
                ros_value=float(fa.value),
                fantasy_positions=tuple(fa.fantasy_positions or ()),
            )
            lineup_players.append(lp)
            self.fa_by_key[key] = fa
            self.elements[key] = _Element(
                key=key,
                kind=_KIND_FA,
                weight=float(fa.value),
                raw=float(fa.value),
                bid=max(0, int(fa.bid)),
                locked=False,
                lineup=lp,
            )

        self.eligibility = (
            precompute_slot_eligibility(
                lineup_players, self.slots, slot_eligibility=self.slot_eligibility
            )
            if self.slots
            else {}
        )
        # Elements eligible for no starting slot are loops of the transversal
        # matroid: they never enter a matching.
        self.lineup_keys = {k for k, idx in self.eligibility.items() if idx}
        self.k0 = frozenset(k for k, e in self.elements.items() if e.kind != _KIND_FA)
        self.capacity = len(self.k0)
        self.solves = 0
        self.baseline_fill = self.fill(self.k0)[0] if self.slots else 0

    # -- the transversal matroid, through the canonical solver -----------

    def fill(self, keys: Iterable[str]) -> tuple[int, frozenset[str]]:
        """``(slots filled, keys of the players filling them)`` for a set."""
        if not self.slots:
            return 0, frozenset()
        players = [
            self.elements[k].lineup
            for k in keys
            if k in self.lineup_keys and self.elements[k].lineup is not None
        ]
        self.solves += 1
        assignment = solve_optimal_assignment(
            players,
            self.slots,
            slot_eligibility=self.slot_eligibility,
            precomputed_eligibility=self.eligibility,
        )
        return len(assignment), frozenset(p.player_id for p in assignment.values())

    def weight(self, keys: Iterable[str], lam: float = 0.0) -> float:
        return sum(self._w(k, lam) for k in keys)

    def _w(self, key: str, lam: float = 0.0) -> float:
        el = self.elements[key]
        return el.weight - lam * el.bid if lam else el.weight

    def spend(self, keys: Iterable[str]) -> int:
        return sum(self.elements[k].bid for k in keys if self.elements[k].kind == _KIND_FA)

    def _order(self, keys: Iterable[str], lam: float = 0.0) -> list[str]:
        return sorted(
            keys,
            key=lambda k: (self._w(k, lam), _KIND_RANK[self.elements[k].kind], k),
        )

    def relax(
        self, excluded: frozenset[str], forced: frozenset[str], lam: float = 0.0
    ) -> tuple[frozenset[str], float] | None:
        """Maximum-weight basis with ``excluded`` removed and ``forced`` kept.

        Reverse-delete greedy on the elongated truncation: walk elements
        cheapest first and remove one whenever the remainder still fills
        ``baseline_fill`` slots, until the set is at capacity.  An element
        that cannot be removed now can never be removed later (a subset of a
        non-spanning set is non-spanning), so one pass is exact.  ``None``
        when no basis keeps every forced and locked element.

        ``lam`` prices each claim's bid into its weight (``V - lam*bid``) for
        the Lagrangian bound; the returned weight is under that pricing.
        """
        current = {k for k in self.elements if k not in excluded}
        pinned = {k for k in current if self.elements[k].locked} | set(forced)
        if len(pinned) > self.capacity:
            return None
        if len(current) > self.capacity:
            filled, matched = self.fill(current)
            if filled < self.baseline_fill:
                return None
            for key in self._order(current, lam):
                if len(current) <= self.capacity:
                    break
                if key in pinned:
                    continue
                if key not in matched:
                    current.discard(key)
                    continue
                trial = current - {key}
                f2, m2 = self.fill(trial)
                if f2 >= self.baseline_fill:
                    current = trial
                    matched = m2
            if len(current) > self.capacity:
                return None
        kept = frozenset(current)
        return kept, self.weight(kept, lam)

    def legal(self, keys: Iterable[str]) -> bool:
        return self.fill(keys)[0] >= self.baseline_fill


def _prune_free_agents(
    roster: Sequence[RosterCandidate],
    free_agents: Sequence[FreeAgentCandidate],
    *,
    open_spots: int,
    rho: float,
    eligibility_class: Mapping[int, tuple[int, ...]],
) -> tuple[set[int], int]:
    """Exact reduction of the free-agent pool.  ``(kept indices, add_bound)``.

    **The add bound.**  In any optimal plan every add ``a`` is paired with a
    distinct open spot or released player ``d`` with ``rho·c(d) <= V(a)``
    (module docstring, "The stop rule").  So no optimal plan holds more than
    ``open + #{droppable d : rho·c(d) <= max V}`` free agents.

    **Dominance.**  Within one eligibility class (identical slot sets, so
    interchangeable for lineup legality), order players by
    ``(bid asc, value desc, index)``.  A player with at least ``add_bound``
    UNPRUNED earlier players worth at least as much is never needed: an
    optimal plan holding him cannot also hold all of those (it would exceed
    the add bound), so one of them can take his place at no greater cost and
    no smaller value, with the lineup unchanged.
    """
    droppable = [
        float(r.value)
        for r in roster
        if not r.locked_reason and isinstance(r.value, (int, float)) and r.value > 0
    ]
    if not free_agents:
        return set(), max(0, int(open_spots))
    v_max = max(float(fa.value) for fa in free_agents)
    add_bound = max(0, int(open_spots)) + sum(1 for c in droppable if rho * c <= v_max + _EPS)

    by_class: dict[tuple[int, ...], list[int]] = {}
    for i in range(len(free_agents)):
        by_class.setdefault(tuple(eligibility_class.get(i, ())), []).append(i)

    keep: set[int] = set()
    for members in by_class.values():
        ordered = sorted(
            members, key=lambda i: (int(free_agents[i].bid), -float(free_agents[i].value), i)
        )
        unpruned: list[int] = []
        for i in ordered:
            fa = free_agents[i]
            dominators = sum(
                1 for j in unpruned if float(free_agents[j].value) >= float(fa.value) - _EPS
            )
            if dominators >= add_bound:
                continue
            unpruned.append(i)
            keep.add(i)
    return keep, add_bound


def _relative_gap(a: float, b: float) -> float | None:
    scale = (a + b) / 2.0
    if scale <= 0:
        return None
    return abs(a - b) / scale


def solve_perfect_waivers(
    roster: Sequence[RosterCandidate],
    free_agents: Sequence[FreeAgentCandidate],
    *,
    starter_slots: Sequence[str],
    slot_eligibility: Mapping[str, Collection[str]] | None = None,
    open_spots: int,
    budget: int | None,
    materiality_ratio: float,
    node_limit: int = DEFAULT_NODE_LIMIT,
) -> SolveResult:
    """Solve one team's Perfect Waivers plan.  See the module docstring.

    ``budget=None`` means the balance is UNKNOWN: paid claims are withheld
    (a budget claim we cannot check is not made), $0 claims still plan.
    """
    rho = materiality_multiplier(materiality_ratio)
    notes: list[str] = []
    slots = [str(s) for s in (starter_slots or []) if s]
    if not slots:
        notes.append(
            "no starter slots resolved — the plan cannot be lineup-guarded, so no "
            "drop is proposed (adds into open spots only)"
        )

    # Eligibility classes for the dominance reduction, from the lineup owner.
    probe = [
        RosterPlayer(
            player_id=str(i),
            canonical_name=fa.name,
            position=fa.position or "",
            ros_value=float(fa.value),
            fantasy_positions=tuple(fa.fantasy_positions or ()),
        )
        for i, fa in enumerate(free_agents)
    ]
    classes = (
        {
            int(k): tuple(v)
            for k, v in precompute_slot_eligibility(
                probe, slots, slot_eligibility=slot_eligibility or None
            ).items()
        }
        if slots
        else {}
    )
    if not slots:
        roster = [
            r
            if r.locked_reason
            else RosterCandidate(
                player_id=r.player_id,
                name=r.name,
                position=r.position,
                value=r.value,
                fantasy_positions=r.fantasy_positions,
                locked_reason="no_lineup_guard",
            )
            for r in roster
        ]
    keep, add_bound = _prune_free_agents(
        roster, free_agents, open_spots=open_spots, rho=rho, eligibility_class=classes
    )
    pruned = len(free_agents) - len(keep)

    # Every free agent stays an element, so the stop explanation can still
    # name a pruned one; the pruned are excluded from every optimization.
    problem = _Problem(
        roster,
        free_agents,
        slots=slots,
        slot_eligibility=slot_eligibility,
        open_spots=open_spots,
        rho=rho,
    )

    if slots and problem.baseline_fill < len(slots):
        notes.append(
            f"your roster fills {problem.baseline_fill} of {len(slots)} starting slots today; "
            f"the plan keeps at least {problem.baseline_fill} filled — not necessarily the same "
            "slots (the cut ladder's legality rule counts filled slots)"
        )
    pruned_keys = frozenset(
        f"f:{i}:{fa.player_id}" for i, fa in enumerate(free_agents) if i not in keep
    )
    paid = frozenset(
        k
        for k, e in problem.elements.items()
        if e.kind == _KIND_FA and e.bid > 0 and k not in pruned_keys
    )
    base_excluded: frozenset[str] = pruned_keys
    if budget is None:
        base_excluded = pruned_keys | paid
        if paid:
            notes.append(
                f"FAAB balance unknown — {len(paid)} paid claim(s) withheld from the plan "
                "rather than planned against a balance we cannot check"
            )
    cap = int(budget) if budget is not None else 0

    # ── Branch and bound over paid claims ──────────────────────────────
    best, nodes, status, upper = _branch_and_bound(
        problem, paid=paid, base_excluded=base_excluded, cap=cap, node_limit=node_limit
    )
    if status == "node_limit":
        notes.append(
            f"branch-and-bound stopped at its {node_limit}-node limit — the plan is the best "
            f"found, NOT proven optimal (objective {best[1]:.0f}, bound {upper:.0f})"
        )

    kept = best[0]
    # (−value, key): never frozenset iteration order, which follows
    # PYTHONHASHSEED and made the pairing differ between processes.
    adds = sorted(
        (k for k in kept if problem.elements[k].kind == _KIND_FA),
        key=lambda k: (-problem.elements[k].raw, k),
    )
    released = sorted(
        (k for k in problem.k0 if k not in kept),
        key=lambda k: (-problem.elements[k].raw, k),
    )
    drops = [k for k in released if problem.elements[k].kind == _KIND_ROSTER]
    opens = [k for k in released if problem.elements[k].kind == _KIND_OPEN]

    pairs = _pair_moves(problem, kept, adds, released) if adds else []
    next_move = (
        _next_move(problem, kept, budget=cap if budget is not None else None)
        if status == "optimal"
        else None
    )
    final_fill = problem.fill(kept)[0] if slots else 0

    return SolveResult(
        status=status,
        proven_optimal=status == "optimal",
        nodes=nodes,
        node_limit=node_limit,
        kept=kept,
        objective=best[1],
        upper_bound=upper,
        baseline_fill=problem.baseline_fill,
        final_fill=final_fill,
        adds=[problem.fa_by_key[k] for k in adds],
        drops=[problem.roster_by_key[k] for k in drops],
        open_spots_used=len(opens),
        pairs=pairs,
        next_move=next_move,
        pruned_free_agents=pruned,
        add_bound=add_bound,
        notes=notes,
    )


def _lagrange_multiplier(
    problem: _Problem, base_excluded: frozenset[str], cap: int, paid: frozenset[str]
) -> tuple[float, list[tuple[frozenset[str], float]]]:
    """The bid price ``lam`` minimizing the Lagrangian bound at the root.

    ``L(lam) = max_K [w(K) - lam*(spend(K) - cap)]`` is an upper bound on the
    budget-constrained optimum for EVERY ``lam >= 0`` (weak duality), and it
    is convex in ``lam``; bisection on its subgradient ``cap - spend`` finds
    the tightest one.  Any multiplier is valid — this only buys pruning — so
    a coarse search is safe.  Also returns the budget-feasible plans met on
    the way, as incumbents.
    """
    feasible: list[tuple[frozenset[str], float]] = []
    ratios = [
        problem.elements[k].weight / problem.elements[k].bid
        for k in paid
        if k not in base_excluded and problem.elements[k].bid > 0
    ]
    if not ratios:
        return 0.0, feasible
    lo, hi = 0.0, max(ratios) + 1.0
    best_lam, best_bound = 0.0, math.inf
    for _ in range(_LAGRANGE_STEPS):
        lam = (lo + hi) / 2.0
        sub = problem.relax(base_excluded, frozenset(), lam)
        if sub is None:
            break
        kept, wl = sub
        bound = wl + lam * cap
        if bound < best_bound:
            best_lam, best_bound = lam, bound
        if problem.spend(kept) <= cap:
            feasible.append((kept, problem.weight(kept)))
            hi = lam
        else:
            lo = lam
    return best_lam, feasible


def _branch_and_bound(
    problem: _Problem,
    *,
    paid: frozenset[str],
    base_excluded: frozenset[str],
    cap: int,
    node_limit: int,
) -> tuple[tuple[frozenset[str], float], int, str, float]:
    """Exact search over which paid claims to make.

    A node fixes some paid claims in (``forced``) and some out (``excluded``).
    Its bound is the smaller of two valid relaxations: the matroid optimum
    ignoring the budget, and the Lagrangian bound at the root multiplier.  A
    node whose budget-ignoring optimum already fits the balance is solved
    exactly; otherwise it branches on that optimum's most expensive undecided
    claim.  Best-first, so the first ``node_limit`` nodes go where the bound
    is highest; reaching the limit is reported, never hidden.
    """
    # The free-claims-only plan is always feasible: the starting incumbent.
    seed = problem.relax(base_excluded | paid, frozenset())
    best = seed if seed is not None else (problem.k0, problem.weight(problem.k0))
    lam, met = _lagrange_multiplier(problem, base_excluded, cap, paid)
    for kept, w in met:
        if w > best[1] + _EPS:
            best = (kept, w)

    def evaluate(ex: frozenset[str], fo: frozenset[str]):
        plain = problem.relax(ex, fo)
        if plain is None:
            return None
        kept, w = plain
        if problem.spend(kept) <= cap:
            return w, kept, (kept, w)
        bound = w
        incumbent = None
        if lam > 0:
            lag = problem.relax(ex, fo, lam)
            if lag is not None:
                lag_kept, wl = lag
                bound = min(bound, wl + lam * cap)
                if problem.spend(lag_kept) <= cap:
                    incumbent = (lag_kept, problem.weight(lag_kept))
        return bound, kept, incumbent

    counter = itertools.count()
    heap: list[tuple[float, int, frozenset[str], frozenset[str], frozenset[str], bool]] = []

    def push(ex: frozenset[str], fo: frozenset[str]) -> None:
        nonlocal best
        out = evaluate(ex, fo)
        if out is None:
            return
        bound, kept, incumbent = out
        if incumbent is not None and incumbent[1] > best[1] + _EPS:
            best = incumbent
        exact = incumbent is not None and incumbent[0] == kept
        if bound > best[1] + _EPS and not exact:
            heapq.heappush(heap, (-bound, next(counter), ex, fo, kept, exact))

    push(base_excluded, frozenset())
    nodes = 0
    status = "optimal"
    while heap:
        neg_bound, _, excluded, forced, kept, exact = heapq.heappop(heap)
        if -neg_bound <= best[1] + _EPS:
            continue
        nodes += 1
        if nodes > node_limit:
            heapq.heappush(heap, (neg_bound, next(counter), excluded, forced, kept, exact))
            status = "node_limit"
            break
        undecided = [k for k in kept if k in paid and k not in forced]
        branch = max(undecided, key=lambda k: (problem.elements[k].bid, k))
        with_it = forced | {branch}
        if problem.spend(with_it) <= cap:
            push(excluded, with_it)
        push(excluded | {branch}, forced)

    upper = max([best[1]] + [-h[0] for h in heap]) if status == "node_limit" else best[1]
    return best, nodes, status, upper


def _pair_moves(
    problem: _Problem,
    kept: frozenset[str],
    adds: Sequence[str],
    released: Sequence[str],
) -> list[dict[str, Any]]:
    """Pair each add with the release it displaces, legal in both directions.

    Edge ``(a, d)``: ``kept − a + d`` is legal (this claim alone fails) AND
    ``K0 − d + a`` is legal (this claim alone wins).  See the module
    docstring for why a perfect matching on those edges always exists.  The
    assignment prefers same-position pairs so the list reads naturally; ties
    resolve by the caller's deterministic order.
    """
    from scipy.optimize import linear_sum_assignment  # noqa: PLC0415

    adds = list(adds)
    released = list(released)
    n = len(adds)
    if n == 0:
        return []
    fails_alone = [[True] * len(released) for _ in range(n)]
    wins_alone = [[True] * len(released) for _ in range(n)]
    if problem.slots:
        for i, a in enumerate(adds):
            without = kept - {a}
            if problem.legal(without):
                continue
            for j, d in enumerate(released):
                fails_alone[i][j] = problem.legal(without | {d})
        for j, d in enumerate(released):
            reduced = problem.k0 - {d}
            if problem.legal(reduced):
                continue
            for i, a in enumerate(adds):
                wins_alone[i][j] = problem.legal(reduced | {a})

    big = 1_000_000.0
    cost = []
    for i, a in enumerate(adds):
        a_pos = (problem.fa_by_key[a].position or "").upper()
        row = []
        for j, d in enumerate(released):
            el = problem.elements[d]
            same = (
                el.kind == _KIND_ROSTER
                and (problem.roster_by_key[d].position or "").upper() == a_pos
            )
            ok = fails_alone[i][j] and wins_alone[i][j]
            row.append((0.0 if ok else big) + (0.0 if same else 1.0))
        cost.append(row)
    rows, cols = linear_sum_assignment(cost)

    pairs: list[dict[str, Any]] = []
    for i, j in zip(rows, cols):
        a, d = adds[i], released[j]
        fa = problem.fa_by_key[a]
        el = problem.elements[d]
        drop_value = el.raw if el.kind == _KIND_ROSTER else 0.0
        gain = float(fa.value) - drop_value
        pair: dict[str, Any] = {
            "add": a,
            "release": d,
            "releaseKind": "openSpot" if el.kind == _KIND_OPEN else "drop",
            "gain": gain,
            "relativeGap": (
                _relative_gap(float(fa.value), drop_value) if el.kind == _KIND_ROSTER else None
            ),
            "material": float(fa.value) > problem.rho * drop_value + _EPS
            if el.kind == _KIND_ROSTER
            else float(fa.value) > 0,
            "failsAloneLegal": bool(fails_alone[i][j]),
            "winsAloneLegal": bool(wins_alone[i][j]),
            "standsAlone": bool(fails_alone[i][j] and wins_alone[i][j]),
        }
        pairs.append(pair)
    pairs.sort(key=lambda p: (-p["gain"], p["add"]))
    return pairs


def _next_move(
    problem: _Problem, kept: frozenset[str], *, budget: int | None
) -> dict[str, Any] | None:
    """The best single move the plan did NOT make, and why it stopped.

    For each affordable free agent not in the plan, the cheapest legal
    release among the plan's remaining open spots and droppable roster.  By
    optimality none of these is material; this names the closest one so the
    stop is explained rather than asserted.
    """
    spent = problem.spend(kept)
    remaining = None if budget is None else budget - spent
    releasable = [
        k
        for k in problem._order(kept)
        if problem.elements[k].kind in (_KIND_OPEN, _KIND_ROSTER) and not problem.elements[k].locked
    ]
    best: dict[str, Any] | None = None
    candidates = sorted(
        (
            k
            for k, e in problem.elements.items()
            if e.kind == _KIND_FA
            and k not in kept
            and (e.bid == 0 or (remaining is not None and e.bid <= remaining))
        ),
        key=lambda k: (-problem.elements[k].raw, k),
    )[:_NEXT_MOVE_CANDIDATES]
    for a in candidates:
        grown = kept | {a}
        _filled, matched = problem.fill(grown)
        for d in releasable:
            if d in matched and not problem.legal(grown - {d}):
                continue
            gain = problem.elements[a].raw - problem.elements[d].raw
            if best is None or gain > best["gain"]:
                best = {"add": a, "release": d, "gain": gain}
            break
    if best is None:
        return None
    a_val = problem.elements[best["add"]].raw
    d_el = problem.elements[best["release"]]
    gap = _relative_gap(a_val, d_el.raw) if d_el.kind == _KIND_ROSTER else None
    if best["gain"] <= _EPS:
        reason = "no_positive_move"
    else:
        reason = "within_uncertainty"
    best.update({"relativeGap": gap, "reason": reason})
    return best


# ── Payload assembly ────────────────────────────────────────────────


def _norm(s: Any) -> str:
    return str(s or "").strip().lower()


def _round(v: float | None) -> float | None:
    return None if v is None else round(float(v), 1)


def build_perfect_waivers(
    contract: Mapping[str, Any] | None,
    *,
    league_key: str | None,
    owner_id: str,
    waiver_targets: Mapping[str, Any] | None,
    constraints: Any = None,
    roster_settings: Mapping[str, Any] | None = None,
    node_limit: int = DEFAULT_NODE_LIMIT,
) -> dict[str, Any]:
    """Assemble one team's Perfect Waivers payload from the canonical owners.

    ``contract`` must carry the rosters the plan is for (the route hands it
    the live teams overlay when it has one).  ``waiver_targets`` is the
    output of ``waiver.find_waiver_targets`` for THIS team — the add pool and
    its FAAB bids.  Raises ``ValueError("unknown_team")`` /
    ``ValueError("no_rosters_loaded")`` rather than optimizing for some other
    team: every number in the payload is roster-specific.
    """
    from src.api.data_contract import contract_slot_eligibility  # noqa: PLC0415
    from src.draft.context import (  # noqa: PLC0415
        build_roster_assets,
        contract_teams,
        index_contract_rows,
        league_rostered_keys,
        match_team,
    )
    from src.draft.displacement import effective_cut_cost  # noqa: PLC0415
    from src.roster_intel.droppability import TeamNotInLeague, team_droppability  # noqa: PLC0415
    from src.trade.roster_capacity import (  # noqa: PLC0415
        assess_roster_capacity,
        build_capacity_context,
    )
    from src.trade.waiver import waiver_pool_exclusion_census  # noqa: PLC0415

    # Refuses (raises) before any work when the feature's band is undeclared.
    ratio = load_stop_band()

    teams = contract_teams(contract)
    if not teams:
        raise ValueError("no_rosters_loaded")
    team = match_team(teams, owner_id=owner_id, roster_id=None, team_name=None)
    if team is None:
        raise ValueError("unknown_team")

    notes: list[str] = []

    # ── Slots and droppability, from C2-DROP-01 ──────────────────────
    try:
        dropp = team_droppability(contract, owner_id=owner_id)
    except TeamNotInLeague as exc:
        raise ValueError("unknown_team") from exc
    starter_slots = list(dropp.get("starterSlots") or [])
    slot_eligibility = contract_slot_eligibility(contract) or None
    undroppable_alone = list((dropp.get("cutLadder") or {}).get("undroppable") or [])

    # ── Capacity, from the roster-capacity owner ─────────────────────
    cap_ctx = build_capacity_context(
        contract, league_key, team, roster_settings=dict(roster_settings or {}) or None
    )
    capacity = assess_roster_capacity(cap_ctx)
    roster_limit = capacity.roster_limit
    if roster_limit is None:
        capacity_state = "unknown"
        open_spots = 0
        notes.append(
            "roster size limit is unknown — no capacity claim is made, so only "
            "capacity-neutral swaps are planned (no add without a matching drop)"
        )
    elif capacity.over_limit_before is None or capacity.open_spots_before is None:
        # A known cap with an unanswered count is still no capacity claim.
        capacity_state = "unknown"
        open_spots = 0
        notes.append(
            "roster capacity could not be determined — only capacity-neutral swaps are planned"
        )
    else:
        over = capacity.over_limit_before
        open_spots = 0 if over > 0 else capacity.open_spots_before
        # The owner's no-trade answer is "exact" whenever the roster is legal
        # under every taxi assignment — true, but the OPEN-SPOT count is still
        # a range while taxi membership is unknown.  The bracket says so; an
        # unanswered bracket end is itself a reason for "partial".
        taxi_lo = capacity.taxi_occupied_min
        taxi_hi = capacity.taxi_occupied_max
        taxi_ranged = (
            taxi_lo is None or taxi_hi is None or taxi_hi > taxi_lo if capacity.taxi_size else False
        )
        capacity_state = "partial" if capacity.certainty != "exact" or taxi_ranged else "exact"
        if over > 0:
            notes.append(
                f"roster is already {over} over its {roster_limit}-man limit — the plan is "
                "capacity-neutral and does not clear the overage; see the cut ladder"
            )
        if capacity_state == "partial":
            notes.append(
                "taxi occupancy is unknown — the plan uses the FEWEST possible open spots, "
                "so its drops are an upper bound (taxi relief may need fewer)"
            )

    # ── Roster join + protections ───────────────────────────────────
    by_id, by_name = index_contract_rows(contract)
    assets, unmatched = build_roster_assets(team, by_name, by_id)
    if unmatched:
        notes.append(
            f"{len(unmatched)} rostered player(s) did not join to the board — unpriced, "
            "never proposed as drops, still occupying their spots"
        )
    resolution_failed = bool(getattr(constraints, "resolution_failed", False))
    if resolution_failed:
        notes.append(
            "your trade protections could not be read — no drop is proposed until they can be"
        )
    roster: list[RosterCandidate] = []
    protected_rows: list[dict[str, Any]] = []
    unpriced_rows: list[dict[str, Any]] = []
    for asset in assets:
        reason: str | None = None
        if constraints is not None:
            reason = constraints.block_reason(
                {"name": asset.name, "playerId": asset.player_id, "position": asset.position}
            )
            if reason is not None:
                protected_rows.append(
                    {"playerId": asset.player_id, "name": asset.name, "reason": reason}
                )
        # The displacement owner's cost basis, scarcity inert (C2-DROP-01).
        _ecc, base, basis, _waiver, _mult = effective_cut_cost(asset, {}, None)
        value = float(base) if basis == "board" else None
        if value is None:
            unpriced_rows.append(
                {"playerId": asset.player_id, "name": asset.name, "position": asset.position}
            )
            reason = reason or "unpriced_value_unknown"
        roster.append(
            RosterCandidate(
                player_id=asset.player_id,
                name=asset.name,
                position=asset.position,
                value=value,
                fantasy_positions=tuple(asset.fantasy_positions or ()),
                locked_reason=reason,
            )
        )

    # ── The add pool, from the FAAB-priced waiver targets ────────────
    # League-wide rostered set, ids AND names — the displacement owner's
    # definition.  No auction-rookie exclusion: ``rookie_pool`` exists for the
    # during-the-auction question, and undrafted rookies ARE free agents once
    # it ends; the pre-draft window is the waiver pool's own rookie gate.
    rostered = league_rostered_keys(contract)
    targets = waiver_targets if isinstance(waiver_targets, Mapping) else {}
    bid_methodology = targets.get("bidMethodology")
    free_agents: list[FreeAgentCandidate] = []
    fa_excluded: dict[str, int] = {}
    seen: set[str] = set()

    ambiguous_names: list[str] = []

    def _exclude(reason: str) -> None:
        fa_excluded[reason] = fa_excluded.get(reason, 0) + 1

    # The waiver pool hands back NAMES.  A name alone is not an identity: two
    # players can share one, and ``index_contract_rows`` keeps whichever row
    # came first.  So the join needs the name AND the position to single out
    # exactly one board player; anything else is reported, never guessed.
    rows_by_name: dict[str, list[Mapping[str, Any]]] = {}
    for brow in (contract or {}).get("playersArray") or []:
        if not isinstance(brow, Mapping) or str(brow.get("assetClass") or "").lower() == "pick":
            continue
        for f in ("displayName", "canonicalName", "legacyRef"):
            key = _norm(brow.get(f))
            if key:
                bucket = rows_by_name.setdefault(key, [])
                if not any(b is brow for b in bucket):
                    bucket.append(brow)

    for items in (targets.get("by_position") or {}).values():
        for cand in items or []:
            if not isinstance(cand, Mapping):
                continue
            named = rows_by_name.get(_norm(cand.get("name"))) or []
            if not named:
                _exclude("not_on_board")
                continue
            cand_pos = str(cand.get("position") or "").strip().upper()
            matches = [b for b in named if str(b.get("position") or "").strip().upper() == cand_pos]
            identities = {str(b.get("playerId") or id(b)) for b in matches}
            if len(identities) != 1:
                _exclude("identity_ambiguous")
                amb = str(cand.get("name") or "")
                if amb not in ambiguous_names and len(ambiguous_names) < 25:
                    ambiguous_names.append(amb)
                continue
            row = matches[0]
            keys = {
                _norm(row.get(f)) for f in ("playerId", "legacyRef", "canonicalName", "displayName")
            } - {""}
            if keys & rostered:
                _exclude("rostered")
                continue
            value = row.get("rankDerivedValue")
            if not isinstance(value, (int, float)) or value <= 0:
                _exclude("unpriced")
                continue
            bid_block = cand.get("bid") if isinstance(cand.get("bid"), Mapping) else None
            bid = bid_block.get("reasonable") if bid_block else None
            if not isinstance(bid, (int, float)) or bid < 0:
                _exclude("no_bid")
                continue
            pid = str(row.get("playerId") or cand.get("name"))
            if pid in seen:
                continue
            seen.add(pid)
            fantasy = row.get("fantasyPositions")
            free_agents.append(
                FreeAgentCandidate(
                    player_id=pid,
                    name=str(row.get("displayName") or cand.get("name")),
                    position=str(row.get("position") or cand.get("position") or "").upper(),
                    value=float(value),
                    bid=int(bid),
                    fantasy_positions=tuple(fantasy) if isinstance(fantasy, (list, tuple)) else (),
                    bid_detail={
                        "recommended": int(bid),
                        "aggressive": bid_block.get("aggressive") if bid_block else None,
                        "conservative": bid_block.get("lowball") if bid_block else None,
                        "clearing": cand.get("clearing"),
                        "maxRational": cand.get("maxRational"),
                        "confidence": cand.get("confidence"),
                    },
                )
            )

    # Who the waiver pool's own rules filtered before any of the above, by
    # reason, from the pool's own predicate (``waiver.waiver_candidate_exclusion``)
    # — so a player outside the pool is counted, not invisible.
    unrostered_rows = [
        dict(r)
        for r in (contract or {}).get("playersArray") or []
        if isinstance(r, Mapping)
        and str(r.get("assetClass") or "").lower() != "pick"
        and str(r.get("position") or "").strip().upper() not in {"", "PICK"}
        and not (
            {_norm(r.get(f)) for f in ("playerId", "legacyRef", "canonicalName", "displayName")}
            - {""}
        )
        & rostered
    ]
    pool_census = waiver_pool_exclusion_census(unrostered_rows)

    # Unpriced free agents: reported, never valued at zero.
    unpriced_fa = 0
    unpriced_fa_names: list[str] = []
    for row in (contract or {}).get("playersArray") or []:
        if not isinstance(row, Mapping) or str(row.get("assetClass") or "").lower() == "pick":
            continue
        pos = str(row.get("position") or "").strip().upper()
        if not pos or pos == "PICK":
            continue
        value = row.get("rankDerivedValue")
        if isinstance(value, (int, float)) and value > 0:
            continue
        keys = {
            _norm(row.get(f)) for f in ("playerId", "legacyRef", "canonicalName", "displayName")
        } - {""}
        if keys & rostered:
            continue
        unpriced_fa += 1
        if len(unpriced_fa_names) < 25:
            unpriced_fa_names.append(str(row.get("displayName") or row.get("canonicalName") or ""))

    # ── Budget ────────────────────────────────────────────────────
    raw_balance = team.get("faabRemaining")
    budget = int(raw_balance) if isinstance(raw_balance, int) and raw_balance >= 0 else None

    result = solve_perfect_waivers(
        roster,
        free_agents,
        starter_slots=starter_slots,
        slot_eligibility=slot_eligibility,
        open_spots=open_spots,
        budget=budget,
        materiality_ratio=ratio,
        node_limit=node_limit,
    )
    notes.extend(result.notes)

    # ── Render the pairs with names ─────────────────────────────────
    moves: list[dict[str, Any]] = []
    add_lookup = {fa.player_id: fa for fa in result.adds}
    drop_lookup = {rc.player_id: rc for rc in result.drops}
    for p in result.pairs:
        add_pid = p["add"].split(":", 2)[2]
        fa = add_lookup.get(add_pid)
        if fa is None:
            continue
        release: dict[str, Any]
        if p["releaseKind"] == "drop":
            drop_pid = p["release"].split(":", 2)[2]
            rc = drop_lookup.get(drop_pid)
            release = {
                "kind": "drop",
                "playerId": rc.player_id if rc else drop_pid,
                "name": rc.name if rc else drop_pid,
                "position": rc.position if rc else "",
                "value": _round(rc.value if rc else None),
            }
        else:
            release = {"kind": "openSpot"}
        moves.append(
            {
                "add": {
                    "playerId": fa.player_id,
                    "name": fa.name,
                    "position": fa.position,
                    "value": _round(fa.value),
                    "bid": dict(fa.bid_detail),
                },
                "release": release,
                "gain": _round(p["gain"]),
                "relativeGap": None if p["relativeGap"] is None else round(p["relativeGap"], 4),
                "material": bool(p["material"]),
                "standsAlone": bool(p["standsAlone"]),
            }
        )

    next_move = None
    if result.next_move is not None:
        nm = result.next_move
        nm_add = nm["add"].split(":", 2)[2]
        add_fa = next((fa for fa in free_agents if fa.player_id == nm_add), None)
        rel_key = nm["release"]
        if rel_key.startswith("open:"):
            rel = {"kind": "openSpot"}
        else:
            rel_pid = rel_key.split(":", 2)[2]
            rc = next((r for r in roster if r.player_id == rel_pid), None)
            rel = {
                "kind": "drop",
                "playerId": rel_pid,
                "name": rc.name if rc else rel_pid,
                "position": rc.position if rc else "",
                "value": _round(rc.value if rc else None),
            }
        next_move = {
            "add": {
                "playerId": nm_add,
                "name": add_fa.name if add_fa else nm_add,
                "position": add_fa.position if add_fa else "",
                "value": _round(add_fa.value if add_fa else None),
                "bid": add_fa.bid if add_fa else None,
            },
            "release": rel,
            "gain": _round(nm["gain"]),
            "relativeGap": None if nm["relativeGap"] is None else round(nm["relativeGap"], 4),
            "reason": nm["reason"],
        }

    total_bid = sum(fa.bid for fa in result.adds)
    # Every drop is priced: an unpriced roster player is locked and can never
    # be released, so ``rc.value`` is a number here by construction.
    net_gain = sum(fa.value for fa in result.adds) - sum(float(rc.value) for rc in result.drops)

    return {
        "version": PERFECT_WAIVERS_VERSION,
        "leagueKey": league_key,
        "valueScale": "rankDerivedValue",
        "advisoryOnly": True,
        "team": {
            "ownerId": str(team.get("ownerId") or ""),
            "name": str(team.get("name") or ""),
            "rosterId": team.get("roster_id"),
        },
        "plan": {
            "moves": moves,
            "addCount": len(result.adds),
            "dropCount": len(result.drops),
            "openSpotsUsed": result.open_spots_used,
            "netValueGain": _round(net_gain),
            "totalRecommendedBid": total_bid,
            "startersFilledBefore": result.baseline_fill,
            "startersFilledAfter": result.final_fill,
            "starterSlots": len(starter_slots),
        },
        "stopRule": {
            "rule": (
                "stop when the next move's gain is <= 0 or the add and the release it "
                "displaces are within the declared stop band"
            ),
            "agreementRatio": ratio,
            "stopBandClass": "PRIOR",
            "source": STOP_BAND_SOURCE,
            "swapMultiplier": round(materiality_multiplier(ratio), 6),
            "nextBestMove": next_move,
        },
        "solver": {
            "status": result.status,
            "provenOptimal": result.proven_optimal,
            "method": "matroid reverse-delete (exact) + branch-and-bound over paid claims",
            "nodes": result.nodes,
            "nodeLimit": result.node_limit,
            "objective": _round(result.objective),
            "upperBound": _round(result.upper_bound),
            "freeAgentsConsidered": len(free_agents),
            "freeAgentsPrunedExactly": result.pruned_free_agents,
            "addBound": result.add_bound,
        },
        "budget": {
            "state": "known" if budget is not None else "unknown",
            "balance": budget,
            "planned": total_bid,
            "remainingAfter": None if budget is None else budget - total_bid,
            "bidBasis": "faab_engine_recommended_standalone",
            "bidMethodology": bid_methodology,
        },
        "capacity": {
            "state": capacity_state,
            "rosterLimit": roster_limit,
            "rosterCount": capacity.size_before,
            "openSpotsPlanned": open_spots,
            "overLimitBefore": capacity.over_limit_before,
            "taxiSize": capacity.taxi_size,
            "taxiOccupiedMin": capacity.taxi_occupied_min,
            "taxiOccupiedMax": capacity.taxi_occupied_max,
        },
        "constraints": {
            "resolutionFailed": resolution_failed,
            "protectedOnRoster": protected_rows,
        },
        "requiredStartersToday": undroppable_alone,
        "unpriced": {
            "rosterPlayers": unpriced_rows,
            "freeAgents": unpriced_fa,
            "freeAgentSample": unpriced_fa_names,
        },
        "freeAgentExclusions": {
            "waiverPool": dict(sorted(pool_census.items())),
            "planJoin": dict(sorted(fa_excluded.items())),
            "identityAmbiguous": ambiguous_names,
        },
        "notes": notes,
    }
