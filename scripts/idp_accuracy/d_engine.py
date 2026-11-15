"""Lane D engine: an exact vectorized best-ball lineup solver and the marginal / volatility maths.

Research only; nothing in ``src/`` imports this and nothing here is served.

Why a second solver exists.  ``src.ros.lineup.solve_optimal_assignment`` is the exact owner and
is called once per simulated week by ``src.roster_intel.best_ball_utility``.  This study needs
tens of millions of week-solves (12 league rosters x ~400 players x several replacement
candidates x thousands of simulated weeks), which that scalar solver cannot do in useful time.
So the SAME problem is solved here for many weeks at once, and the result is pinned against
the owner by ``tests/idp_accuracy/test_bestball_archetypes.py`` on random weeks including
DL/LB and DB/LB hybrids.  The owner stays the source of truth for slot ELIGIBILITY too: this
module never keeps an eligibility table, it asks ``precompute_slot_eligibility``.

Algorithm.  Slot eligibility is a transversal matroid, so the greedy "take players in descending
score, keep one if the kept set is still assignable" is exactly optimal (the owner's own
docstring says the same).  Assignability of a set is Hall's condition, which for slots grouped by
name is: for every union ``S`` of eligibility signatures, the number of kept players whose
signature lies inside ``S`` is at most the slot count of ``S``.  Both the greedy and the Hall
test are vectorized across weeks.  Like the owner (``OBJECTIVE_REALIZED_POINTS``) it fills every
fillable slot, so a negative score is still counted when no better player can take the slot.
"""

from __future__ import annotations

import itertools
import math
from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np

from src.ros.lineup import RosterPlayer, normalize_slot, precompute_slot_eligibility

# ── eligibility signatures (from the owner) ──────────────────────────────────


def signature_for(
    player_id: str,
    position: str,
    fantasy_positions: Sequence[str],
    slots: Sequence[str],
    *,
    cache: dict | None = None,
) -> frozenset[str]:
    """The slot-family names this player may fill, as decided by ``src.ros.lineup``."""
    rp = RosterPlayer(
        player_id=player_id,
        canonical_name=player_id,
        position=position,
        ros_value=0.0,
        fantasy_positions=tuple(fantasy_positions),
    )
    elig = precompute_slot_eligibility([rp], list(slots))
    return frozenset(normalize_slot(slots[i]) for i in elig.get(player_id, ()))


# ── the vectorized exact solver ───────────────────────────────────────────────


class LineupSolver:
    """Exact best-ball lineup totals for many simulated weeks at once.

    ``slots`` is the starting-slot list (e.g. ``["QB","RB","RB",...,"DL","DL","DL"]``), already
    restricted to the slots of one sub-problem (offense or IDP).  ``signatures`` is the set of
    distinct eligibility signatures the pool contains.  A player is passed by *type id*, an index
    into ``self.types``.
    """

    def __init__(self, slots: Sequence[str], signatures: Iterable[frozenset[str]]):
        self.slot_caps = Counter(normalize_slot(s) for s in slots)
        self.n_slots = int(sum(self.slot_caps.values()))
        sigs = sorted({frozenset(s) for s in signatures if s}, key=lambda s: (len(s), sorted(s)))
        self.types: list[frozenset[str]] = sigs
        self.type_id = {s: i for i, s in enumerate(sigs)}
        # Hall sets: every distinct union of a non-empty sub-collection of signatures.
        unions: set[frozenset[str]] = set()
        for r in range(1, len(sigs) + 1):
            for combo in itertools.combinations(sigs, r):
                unions.add(frozenset().union(*combo))
        self.hall_sets = sorted(unions, key=lambda s: (len(s), sorted(s)))
        T = len(sigs)
        self.M = np.zeros((T, len(self.hall_sets)), dtype=np.int16)
        for j, S in enumerate(self.hall_sets):
            for t, sig in enumerate(sigs):
                if sig <= S:
                    self.M[t, j] = 1
        self.caps = np.array(
            [sum(self.slot_caps.get(g, 0) for g in S) for S in self.hall_sets], dtype=np.int16
        )

    def solve(self, X: np.ndarray, type_ids: np.ndarray) -> np.ndarray:
        """``X`` is (weeks, players) scores; ``type_ids`` (players,).  Returns (weeks,) totals."""
        D, N = X.shape
        if N == 0:
            return np.zeros(D)
        type_ids = np.asarray(type_ids, dtype=np.int64)
        order = np.argsort(-X, axis=1, kind="stable")
        rows = np.arange(D)
        cnt = np.zeros((D, len(self.types)), dtype=np.int16)
        total = np.zeros(D)
        filled = np.zeros(D, dtype=np.int16)
        for j in range(N):
            idx = order[:, j]
            t = type_ids[idx]
            cnt[rows, t] += 1
            ok = ((cnt @ self.M) <= self.caps).all(axis=1)
            bad = ~ok
            if bad.any():
                cnt[rows[bad], t[bad]] -= 1
            val = X[rows, idx]
            total += np.where(ok, val, 0.0)
            filled += ok
            if j + 1 >= self.n_slots and (filled >= self.n_slots).all():
                break
        return total


# ── players / entities ────────────────────────────────────────────────────────


@dataclass
class Entity:
    pid: str
    name: str
    lpos: str  # lineup position group: QB RB WR TE K DL LB DB
    sub: str  # "off" | "idp"
    sig: frozenset[str]
    arch: str
    fine: str
    team: str | None
    bye_week: int | None
    played: np.ndarray  # points in weeks the player appeared
    n_games: int  # non-bye weeks with known status (played + dnp)
    played_weeks: tuple[int, ...] = ()
    snap_share_early: float | None = None
    snap_share_late: float | None = None
    #: (n_played, K) weekly counts of the priced defensive events, aligned with ``played``
    ev_counts: np.ndarray | None = None

    @property
    def n_played(self) -> int:
        return int(self.played.size)

    @property
    def p_active(self) -> float:
        return self.n_played / self.n_games if self.n_games else 0.0

    @property
    def mu_cond(self) -> float:
        return float(self.played.mean()) if self.n_played else 0.0

    @property
    def mu_unc(self) -> float:
        return self.p_active * self.mu_cond

    @property
    def sd_cond(self) -> float:
        return float(self.played.std(ddof=1)) if self.n_played > 1 else float("nan")

    @property
    def cv_cond(self) -> float:
        m = self.mu_cond
        s = self.sd_cond
        return s / m if m > 0 and np.isfinite(s) else float("nan")


OFFENSE_GROUPS = ("QB", "RB", "WR", "TE", "K")
IDP_GROUPS = ("DL", "LB", "DB")
OFFENSE_SLOT_NAMES = frozenset({"QB", "RB", "WR", "TE", "FLEX", "SUPER_FLEX", "K"})
IDP_SLOT_NAMES = frozenset({"DL", "LB", "DB"})


def split_slots(slots: Sequence[str]) -> tuple[list[str], list[str]]:
    off = [s for s in slots if normalize_slot(s) in OFFENSE_SLOT_NAMES]
    idp = [s for s in slots if normalize_slot(s) in IDP_SLOT_NAMES]
    return off, idp


def subproblem_of(sig: frozenset[str]) -> str | None:
    """ "off" / "idp", or None for a signature spanning both (a two-way player) or neither."""
    if not sig:
        return None
    if sig <= OFFENSE_SLOT_NAMES:
        return "off"
    if sig <= IDP_SLOT_NAMES:
        return "idp"
    return None


# ── weekly draws ──────────────────────────────────────────────────────────────

MODELS = ("E", "Ec", "S", "Su", "P", "Q")


@dataclass(frozen=True)
class Scenario:
    """One fully specified simulation.  Frozen so it can key results and cross processes."""

    model: str = (
        "E"  # E empirical | S archetype-shape (2025) | P gamma, archetype CV | Q Poisson events
    )
    avail: str = "observed"  # observed | always
    byes: str = "schedule"  # schedule | none
    window: str = "all"  # all | early (wk 1-3) | late (wk 4-6)
    cand_ranks: tuple[int, ...] = (1, 2, 3, 4, 5)  # FA rank(s) tried per opened family
    #: how the candidates become ONE replacement: "median" = the candidate whose roster scores the
    #: median of the set (robust to one free agent's small-sample luck), "best" = the roster that
    #: scores highest on these same weeks (the library's rule; selects the luckiest of K)
    repl_mode: str = "median"
    draws: int = 1500
    seed: int = 20261026
    boot: int | None = None  # None = the observed data; k = k-th week bootstrap replicate
    remaining_weeks: tuple[int, ...] = tuple(range(7, 18))
    deltas: tuple[float, ...] = (-1.0, 0.5)  # mean-preserving SD scaling (-1 = strip all variance)


@dataclass
class ShapeReference:
    """Archetype shape from the PRIOR season (rescored under the 2026 card): SHAPE ONLY.

    ``event_points`` is the league card's points per counted defensive event, in the order of
    ``d_data.EVENT_KEYS``; the event model (Q) multiplies Poisson counts by it.
    """

    ratios: dict[str, np.ndarray]  # archetype -> pooled score / own-season conditional mean
    cv: dict[str, float]
    n_players: dict[str, int]
    event_points: np.ndarray | None = None
    #: the same reference WITHOUT the roster-relevance filter (model "Su"): fringe players included
    alt: "ShapeReference | None" = None

    def pool_for(self, arch: str, lpos: str) -> np.ndarray:
        r = self.ratios.get(arch)
        if r is not None and r.size >= 200:
            return r
        return self.ratios[f"POS_{lpos}"]


def _bootstrap_entity(e: Entity, rng: np.random.Generator) -> Entity:
    """Resample the player's non-bye weeks with replacement (a week is played or DNP).

    The same week indices carry the weekly event counts, so the score and its events stay one
    observation.
    """
    if e.n_games == 0:
        return e
    # Reconstruct the week list: n_played observed scores + (n_games - n_played) DNP weeks.
    miss = e.n_games - e.n_played
    kinds = np.concatenate([np.ones(e.n_played, dtype=bool), np.zeros(miss, dtype=bool)])
    scores = np.concatenate([e.played, np.zeros(miss)])
    pick = rng.integers(0, e.n_games, size=e.n_games)
    k = kinds[pick]
    ev = None
    if e.ev_counts is not None:
        ev_all = np.vstack([e.ev_counts, np.zeros((miss, e.ev_counts.shape[1]))])
        ev = ev_all[pick][k]
    return Entity(
        pid=e.pid,
        name=e.name,
        lpos=e.lpos,
        sub=e.sub,
        sig=e.sig,
        arch=e.arch,
        fine=e.fine,
        team=e.team,
        bye_week=e.bye_week,
        played=scores[pick][k].astype(float),
        n_games=e.n_games,
        ev_counts=ev,
    )


class DrawSet:
    """Simulated weekly scores for a fixed entity list under one scenario.

    ``S`` conditional-on-active scores, ``AB`` the active-and-not-bye indicator, ``X = AB * S``.
    All three are (weeks, entities).  The uniform matrices come from the scenario seed ONLY, so
    two scenarios over the same entities share their random numbers (paired comparisons), and a
    bootstrap replicate differs from the base run only through the resampled weeks.
    """

    def __init__(self, entities: Sequence[Entity], shape: ShapeReference, sc: Scenario):
        self.sc = sc
        self.entities = list(entities)
        N = len(self.entities)
        D = sc.draws
        rng = np.random.default_rng(sc.seed)
        u_score = rng.random((D, N))
        u_avail = rng.random((D, N))
        week = rng.choice(np.array(sc.remaining_weeks), size=D)
        ents = self.entities
        if sc.boot is not None:
            brng = np.random.default_rng([sc.seed, 7919, sc.boot])
            ents = [_bootstrap_entity(e, brng) for e in ents]
        self.eff = ents  # entities as simulated (resampled when bootstrapping)
        S = np.zeros((D, N))
        p = np.zeros(N)
        mu = np.zeros(N)
        for i, e in enumerate(ents):
            if e.n_played == 0:
                continue
            mu[i] = e.mu_cond
            p[i] = 1.0 if sc.avail == "always" else e.p_active
            if sc.model == "E":
                S[:, i] = e.played[
                    np.minimum((u_score[:, i] * e.n_played).astype(int), e.n_played - 1)
                ]
            elif sc.model == "Ec":
                # E with the n/(n-1) variance correction: an n-point empirical distribution has
                # (n-1)/n of the sample variance, so deviations are scaled back up.
                kk = math.sqrt(e.n_played / (e.n_played - 1)) if e.n_played > 1 else 1.0
                x = e.played[np.minimum((u_score[:, i] * e.n_played).astype(int), e.n_played - 1)]
                S[:, i] = e.mu_cond + kk * (x - e.mu_cond)
            elif sc.model in ("S", "Su"):
                ref = shape.alt if (sc.model == "Su" and shape.alt is not None) else shape
                pool = ref.pool_for(e.arch, e.lpos)
                S[:, i] = (
                    e.mu_cond
                    * pool[np.minimum((u_score[:, i] * pool.size).astype(int), pool.size - 1)]
                )
            elif sc.model == "P":
                from scipy.stats import gamma as _gamma

                cv = shape.cv.get(e.arch) or shape.cv[f"POS_{e.lpos}"]
                if e.mu_cond > 0 and cv > 0:
                    a = 1.0 / (cv * cv)
                    S[:, i] = _gamma.ppf(u_score[:, i], a, scale=e.mu_cond / a)
                else:
                    S[:, i] = e.mu_cond
            elif sc.model == "Q":
                # Verified event RATES (the player's own counts per appearance) with a PROVISIONAL
                # variance assumption (independent Poisson counts).  Offense has no event model
                # and falls back to its own empirical weeks, so a Q run changes IDP only.
                if e.ev_counts is None or shape.event_points is None:
                    S[:, i] = e.played[
                        np.minimum((u_score[:, i] * e.n_played).astype(int), e.n_played - 1)
                    ]
                else:
                    from scipy.stats import poisson as _poisson

                    lam = e.ev_counts.mean(axis=0)
                    resid = e.mu_cond - float(lam @ shape.event_points)
                    # one uniform block per entity, seeded by (scenario seed, entity index), so
                    # replicates and models share their random numbers without a (D, N, K) array
                    ev_u = np.random.default_rng([sc.seed, 4242, i]).random((D, lam.size))
                    cnt = _poisson.ppf(ev_u, np.maximum(lam, 1e-12)[None, :])
                    S[:, i] = cnt @ shape.event_points + resid
            else:
                raise ValueError(sc.model)
        avail = u_avail < p[None, :]
        if sc.byes == "schedule":
            bye_wk = np.array([(-1 if e.bye_week is None else e.bye_week) for e in ents])
            bye = week[:, None] == bye_wk[None, :]
        else:
            bye = np.zeros((D, N), dtype=bool)
        self.S = S
        self.mu_cond = mu
        self.AB = (avail & ~bye).astype(float)
        self.index = {e.pid: i for i, e in enumerate(ents)}

    @classmethod
    def from_matrix(cls, entities: Sequence[Entity], X: np.ndarray, sc: Scenario) -> "DrawSet":
        """A DrawSet whose weekly scores are GIVEN (e.g. the six realized weeks), not simulated."""
        self = cls.__new__(cls)
        self.sc = sc
        self.entities = list(entities)
        self.eff = self.entities
        self.S = np.asarray(X, float)
        self.AB = np.ones_like(self.S)
        self.mu_cond = np.array([e.mu_cond for e in self.entities])
        self.index = {e.pid: i for i, e in enumerate(self.entities)}
        return self

    def column(self, i: int, delta: float | None = None) -> np.ndarray:
        """Weekly points of entity ``i``; ``delta`` scales the deviation about the conditional mean."""
        s = self.S[:, i]
        if delta is not None and delta != 0.0:
            m = self.mu_cond[i]
            s = m + (1.0 + delta) * (s - m)
        return self.AB[:, i] * s


# ── candidate replacements and marginals ─────────────────────────────────────


@dataclass
class Pools:
    """Who is on which roster, who is a free agent, per sub-problem."""

    roster_idx: list[dict[str, list[int]]]  # team -> {"off": [entity idx], "idp": [...]}
    fa_by_group: dict[str, list[int]]  # slot group -> entity idx, best unconditional mean first
    solvers: dict[str, LineupSolver]
    type_of: np.ndarray  # entity idx -> type id within its sub-problem
    sub_of: list[str]


def build_pools(
    entities: Sequence[Entity],
    teams: Sequence[Sequence[str]],
    fa_pids: set[str],
    slots: Sequence[str],
    excluded: set[str],
) -> Pools:
    off_slots, idp_slots = split_slots(slots)
    by_pid = {e.pid: i for i, e in enumerate(entities)}
    sigs = {"off": set(), "idp": set()}
    for e in entities:
        if e.pid in excluded:
            continue
        sigs[e.sub].add(e.sig)
    solvers = {
        "off": LineupSolver(off_slots, sigs["off"]),
        "idp": LineupSolver(idp_slots, sigs["idp"]),
    }
    type_of = np.zeros(len(entities), dtype=np.int64)
    for i, e in enumerate(entities):
        if e.pid in excluded:
            continue
        type_of[i] = solvers[e.sub].type_id[e.sig]
    roster_idx = []
    for team in teams:
        d = {"off": [], "idp": []}
        for pid in team:
            i = by_pid.get(pid)
            if i is None or pid in excluded:
                continue
            d[entities[i].sub].append(i)
        roster_idx.append(d)
    fa_by_group: dict[str, list[int]] = {}
    fa_all = [by_pid[p] for p in fa_pids if p in by_pid and p not in excluded]
    fa_all.sort(key=lambda i: (-entities[i].mu_unc, entities[i].pid))
    for i in fa_all:
        for g in entities[i].sig:
            fa_by_group.setdefault(g, []).append(i)
    return Pools(roster_idx, fa_by_group, solvers, type_of, [e.sub for e in entities])


def candidate_fas(e: Entity, pools: Pools, ranks: Sequence[int], banned: set[int]) -> list[int]:
    """FA entity indices to try as the replacement: the rank-r FA per opened family, for each r."""
    out: list[int] = []
    for g in sorted(e.sig):
        pool = [i for i in pools.fa_by_group.get(g, []) if i not in banned]
        for r in ranks:
            if 0 < r <= len(pool) and pool[r - 1] not in out:
                out.append(pool[r - 1])
    return out


@dataclass
class MarginalResult:
    pid: str
    deltas: dict[
        float, np.ndarray
    ]  # delta -> per-draw (F_with(delta) - F_without), averaged over contexts
    base_with: np.ndarray  # per-draw F_with - F_without at delta 0 (averaged over contexts)
    own_with: float | None  # own-context marginal (mean over draws)
    contexts: int
    repl_pids: list[str]
    no_candidate_contexts: int


def _pick_replacement(vals: list[tuple[str, np.ndarray]], mode: str) -> tuple[str, np.ndarray]:
    """One replacement from the candidate rosters' per-week totals."""
    ranked = sorted(vals, key=lambda t: (-float(t[1].mean()), t[0]))
    if mode == "best":
        return ranked[0]
    if mode == "median":
        return ranked[len(ranked) // 2]
    raise ValueError(mode)


def evaluate_marginals(
    ds: DrawSet,
    pools: Pools,
    eval_idx: Sequence[int],
    owner_of: dict[int, int],
    *,
    context_teams: Sequence[int] | None = None,
) -> dict[int, MarginalResult]:
    """Marginal of each evaluated entity in every context (roster) vs a free-agent claim.

    ``M_k(p) = F(R_k - {p} + {p}) - F(R_k - {p} + {c})`` per simulated week, ``c`` the replacement
    chosen by ``sc.repl_mode`` among the candidate free agents.  For a context that is not p's own
    team ``R_k - {p}`` is just ``R_k``, so the replacement rosters are shared by every player and
    cached.  Everything is per-week arrays, so paired differences are exact.
    """
    ents = ds.entities
    D = ds.sc.draws
    n_teams = len(pools.roster_idx)
    teams = list(range(n_teams)) if context_teams is None else list(context_teams)
    X = ds.AB * ds.S  # (D, N)
    deltas = ds.sc.deltas
    mode = ds.sc.repl_mode
    cache_cand: dict[tuple[int, int], np.ndarray] = {}
    cache_base: dict[tuple[int, str], np.ndarray] = {}

    def f_roster(sub: str, cols: list[int], extra: int | None = None) -> np.ndarray:
        solver = pools.solvers[sub]
        if extra is None:
            return solver.solve(X[:, cols], pools.type_of[cols]) if cols else np.zeros(D)
        if cols:
            return solver.solve(
                np.column_stack([X[:, cols], X[:, extra]]),
                np.append(pools.type_of[cols], pools.type_of[extra]),
            )
        return solver.solve(X[:, [extra]], np.array([pools.type_of[extra]]))

    results: dict[int, MarginalResult] = {}
    for i in eval_idx:
        e = ents[i]
        sub = e.sub
        tid_p = int(pools.type_of[i])
        solver = pools.solvers[sub]
        acc_with = {d: np.zeros(D) for d in (0.0, *deltas)}
        acc_without = np.zeros(D)
        own = None
        used = 0
        repl_pids: list[str] = []
        none_cands = 0
        owner = owner_of.get(i)
        for k in teams:
            roster = pools.roster_idx[k][sub]
            own_ctx = i in roster
            base_cols = [c for c in roster if c != i]
            banned = set(roster) | {i}
            cands = candidate_fas(e, pools, ds.sc.cand_ranks, banned)
            tids = pools.type_of[base_cols]
            with_d: dict[float, np.ndarray] = {}
            for d in (0.0, *deltas):
                if d == 0.0 and own_ctx:
                    key = (k, sub)
                    if key not in cache_base:
                        cache_base[key] = f_roster(sub, roster)
                    with_d[d] = cache_base[key]
                    continue
                col = ds.column(i, d)
                if base_cols:
                    with_d[d] = solver.solve(
                        np.column_stack([X[:, base_cols], col]), np.append(tids, tid_p)
                    )
                else:
                    with_d[d] = solver.solve(col[:, None], np.array([tid_p]))
            vals: list[tuple[str, np.ndarray]] = []
            for c in cands:
                if own_ctx:
                    vals.append((ents[c].pid, f_roster(sub, base_cols, c)))
                else:
                    key = (k, c)
                    if key not in cache_cand:
                        cache_cand[key] = f_roster(sub, base_cols, c)
                    vals.append((ents[c].pid, cache_cand[key]))
            if vals:
                pid_c, without = _pick_replacement(vals, mode)
                repl_pids.append(pid_c)
            else:  # no priced free agent can fill any slot p opens
                none_cands += 1
                without = f_roster(sub, base_cols)
            for d in with_d:
                acc_with[d] += with_d[d]
            acc_without += without
            used += 1
            if owner is not None and k == owner:
                own = float((with_d[0.0] - without).mean())
        results[i] = MarginalResult(
            pid=e.pid,
            deltas={d: (acc_with[d] - acc_without) / used for d in deltas},
            base_with=(acc_with[0.0] - acc_without) / used,
            own_with=own,
            contexts=used,
            repl_pids=repl_pids,
            no_candidate_contexts=none_cands,
        )
    return results


def deterministic_marginals(
    ents: Sequence[Entity],
    pools: Pools,
    eval_idx: Sequence[int],
    owner_of: dict[int, int],
    cand_ranks: Sequence[int] = (1, 2, 3, 4, 5),
    mode: str = "median",
) -> dict[int, tuple[float, float | None]]:
    """The same marginal in a world where every player scores exactly his expected ppg each week.

    This is the "season-long ppg lineup" valuation: expected points per week, no variance, no
    byes.  Returns (context-average marginal, own-context marginal) per entity.
    """
    mu = np.array([e.mu_unc for e in ents])[None, :]
    out: dict[int, tuple[float, float | None]] = {}
    n_teams = len(pools.roster_idx)
    for i in eval_idx:
        e = ents[i]
        sub = e.sub
        solver = pools.solvers[sub]
        owner = owner_of.get(i)
        tot = 0.0
        own = None
        for k in range(n_teams):
            roster = pools.roster_idx[k][sub]
            base_cols = [c for c in roster if c != i]
            banned = set(roster) | {i}
            with_v = float(solver.solve(mu[:, base_cols + [i]], pools.type_of[base_cols + [i]])[0])
            vals = [
                (
                    ents[c].pid,
                    np.array(
                        [
                            float(
                                solver.solve(
                                    mu[:, base_cols + [c]], pools.type_of[base_cols + [c]]
                                )[0]
                            )
                        ]
                    ),
                )
                for c in candidate_fas(e, pools, cand_ranks, banned)
            ]
            if vals:
                best = float(_pick_replacement(vals, mode)[1][0])
            else:
                best = (
                    float(solver.solve(mu[:, base_cols], pools.type_of[base_cols])[0])
                    if base_cols
                    else 0.0
                )
            tot += with_v - best
            if owner is not None and k == owner:
                own = with_v - best
        out[i] = (tot / n_teams, own)
    return out


# ── statistics helpers ────────────────────────────────────────────────────────


def spearman(a: Sequence[float], b: Sequence[float]) -> float:
    from scipy.stats import spearmanr

    a = np.asarray(a, float)
    b = np.asarray(b, float)
    if a.size < 3 or np.ptp(a) == 0 or np.ptp(b) == 0:
        return float("nan")
    return float(spearmanr(a, b).statistic)


def percentile_ci(xs: Sequence[float], lo: float = 2.5, hi: float = 97.5) -> tuple[float, float]:
    arr = np.asarray([x for x in xs if np.isfinite(x)], float)
    if arr.size == 0:
        return float("nan"), float("nan")
    return float(np.percentile(arr, lo)), float(np.percentile(arr, hi))
