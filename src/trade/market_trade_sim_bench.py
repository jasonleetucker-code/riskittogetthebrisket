"""Estimator test bench + power study for chaseTradeMarket (P6a / G12s).

Runs candidate trade-implied valuation models against synthetic worlds from
:mod:`src.trade.market_trade_sim`, where the true values are known, and
answers the directive's question honestly: how many completed trades, from how
many independent leagues, does each model need before its per-tier ordering
is accurate to a stated level?  The answer is reported as a REQUIRED count;
the shortfall is ``required - observed`` only once a real observed count is
supplied (missing is never zero, so an unknown observed count yields a null
shortfall, never "0 short").

SCOPE — read before reusing anything here.  The estimators in this module are
BENCH PROTOTYPES for the power study.  They are not the production estimator
(that is P6's ``src/trade/market_trade_price_model.py``, G12) and nothing on
the valuation path may import this module (pinned by test).  P6 plugs its
estimator into :func:`evaluate_fit` / :func:`run_scenario` through the
:class:`FitResult` shape rather than re-implementing the metrics, so the bench
remains the one owner of the synthetic metrics.

Candidate models (plan §4.2), all estimated on log values ``theta``:

* ``prior_only`` — the consensus-free prior alone (position mean + a
  covariate standing in for age / draft capital).  What you know with zero
  trades.
* ``naive_sum_l2`` — "add up both sides, they should be equal": raw summed
  package totals (``q = 1``), squared-error loss, every trade weighted 1.  The
  approach the directive warns against; kept as a baseline.
* ``bt_consolidation`` — graph / Bradley–Terry baseline: a 1-for-k trade says
  the single asset beats each of the k; a 1-for-1 says the two are tied.
* ``geom_huber`` (E2 primary) — sorted geometric package utility
  (``q = 0.78``, the active Value Adjustment model, used as a DECLARED
  benchmark aggregator, not assumed true), Huber robust loss, recency weights
  ``0.5 ** (age / H)`` with age from the evidence cutoff, per-league and
  per-manager-pair caps, format covariates post-stratified to the reference
  format, ridge shrinkage toward the consensus-free prior.
* ablations — ``geom_huber_pooled`` (format ignored), ``geom_huber_unweighted``
  (no recency, no caps), ``geom_huber_mgr`` (+ penalised manager effect).

Metrics are compression-invariant (plan §5): pairwise ordering accuracy and
Kendall tau within true tiers (any monotone transform of an estimate leaves
them unchanged; a constant estimate scores 0.5 / 0), decoy accuracy on held-out
trades (does the actual counter-package fit better than size-matched decoys;
a constant estimate ties at 0.5), and interval coverage of contrasts with
cluster-robust (manager-lineage component) standard errors.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Any, Mapping, Sequence

import numpy as np
from scipy import optimize, sparse, stats
from scipy.sparse import linalg as splinalg

from src.trade.market_trade_sim import (
    DOMAINS,
    MAX_PACKAGE,
    POSITIONS,
    STRATA,
    SimConfig,
    SimWorld,
    TradeSet,
    chronological_split,
    derive_seed,
    format_effect_design,
    generate_world,
    maturity_cohort,
    reserved_components,
)

STATUS_SUPPORTED = "SUPPORTED"
STATUS_PRIOR_DOMINATED = "PRIOR_DOMINATED"
STATUS_INSUFFICIENT = "INSUFFICIENT"

# True-rank tier edges per domain (inclusive upper rank); picks tier by round.
TIER_EDGES: Mapping[str, tuple[tuple[str, int], ...]] = {
    "offense": (("T1", 24), ("T2", 60), ("T3", 120), ("T4", 10**9)),
    "idp": (("T1", 12), ("T2", 36), ("T3", 10**9)),
}
PICK_TIERS: tuple[tuple[str, tuple[int, ...]], ...] = (
    ("R1", (1,)),
    ("R2", (2,)),
    ("R3+", (3, 4, 5, 6)),
)


# --------------------------------------------------------------------------- #
# Specs and thresholds — every number below is a PLACEHOLDER to be fixed in
# the preregistration (docs/market_trades/CHASE_TRADE_MARKET_PREREGISTRATION.md)
# before any real holdout is examined.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class EstimatorSpec:
    name: str
    kind: str = "latent"  # latent | bt | prior
    q: float = 0.78
    loss: str = "huber"  # huber | l2
    half_life_days: float | None = 90.0
    league_cap: float | None = 25.0
    pair_cap: float | None = 4.0
    format_effects: bool = True
    manager_effect: bool = False
    tau: float = 2.0
    huber_k: float = 1.345
    manager_sd: float = 0.1


DEFAULT_ESTIMATORS: tuple[EstimatorSpec, ...] = (
    EstimatorSpec("prior_only", kind="prior"),
    EstimatorSpec(
        "naive_sum_l2",
        q=1.0,
        loss="l2",
        half_life_days=None,
        league_cap=None,
        pair_cap=None,
        format_effects=False,
    ),
    EstimatorSpec(
        "bt_consolidation", kind="bt", half_life_days=None, league_cap=None, pair_cap=None
    ),
    EstimatorSpec("geom_huber"),
)

ABLATION_ESTIMATORS: tuple[EstimatorSpec, ...] = (
    EstimatorSpec("geom_huber_pooled", format_effects=False),
    EstimatorSpec("geom_huber_unweighted", half_life_days=None, league_cap=None, pair_cap=None),
    EstimatorSpec("geom_huber_mgr", manager_effect=True),
)


@dataclass(frozen=True)
class SupportThresholds:
    """Plan §4.8 support PROCEDURE.  Values are placeholders."""

    min_info_appearances: float = 3.0
    min_components: int = 3
    max_component_share: float = 0.6
    max_prior_influence: float = 0.5
    max_contrast_se: float = 0.35
    require_core: bool = True


@dataclass
class FitResult:
    """What any estimator (bench prototype or P6's production estimator) hands
    the metrics.  ``theta`` is the reference-format log value per asset (NaN
    where no estimate exists); ``se_contrast`` is the standard error of
    ``theta_a - mean(theta over the domain core)`` or None."""

    spec: EstimatorSpec
    theta: np.ndarray
    se_contrast: np.ndarray | None
    status: np.ndarray
    reason: np.ndarray
    format_offset: np.ndarray  # (n_positions, n_strata) fitted log shifts
    q_eval: float
    core: np.ndarray  # bool per asset
    info: dict[str, np.ndarray]
    diagnostics: dict[str, Any]
    n_clusters: int
    internals: dict[str, Any] = field(default_factory=dict, repr=False)


# --------------------------------------------------------------------------- #
# Observation weights
# --------------------------------------------------------------------------- #


def observation_weights(
    trades: TradeSet,
    *,
    evidence_cutoff: float,
    half_life_days: float | None,
    league_cap: float | None,
    pair_cap: float | None,
) -> np.ndarray:
    """Recency x league cap x manager-pair cap.

    * recency ``0.5 ** (age / H)``, age = ``evidence_cutoff - trade date``
      (the newest observation the build could see — never the wall clock);
    * league cap ``min(1, C / W_league)`` where ``W_league`` is that league's
      recency-weighted volume, so one hyperactive league cannot dominate;
    * pair cap ``min(1, C_pair / W_pair)`` over the unordered manager pair, so
      two managers trading back and forth count as bounded evidence.
    """
    n = trades.n
    w = np.ones(n)
    if half_life_days:
        age = np.maximum(0.0, evidence_cutoff - trades.date)
        w = 0.5 ** (age / float(half_life_days))
    if league_cap:
        tot = np.bincount(
            trades.league, weights=w, minlength=int(trades.league.max(initial=-1)) + 1
        )
        w = w * np.minimum(1.0, league_cap / np.maximum(tot[trades.league], 1e-12))
    if pair_cap:
        lo = np.minimum(trades.mgr_a, trades.mgr_b)
        hi = np.maximum(trades.mgr_a, trades.mgr_b)
        _, inv = np.unique(np.stack([lo, hi], axis=1), axis=0, return_inverse=True)
        inv = np.asarray(inv).reshape(-1)
        tot = np.bincount(inv, weights=w)
        w = w * np.minimum(1.0, pair_cap / np.maximum(tot[inv], 1e-12))
    return w


def kish_effective_n(weights: np.ndarray) -> float:
    s = float(np.sum(weights))
    s2 = float(np.sum(np.square(weights)))
    return s * s / s2 if s2 > 0 else 0.0


# --------------------------------------------------------------------------- #
# Graph support: 2-edge-connected core and effective resistance
# --------------------------------------------------------------------------- #


def _co_occurrence_edges(trades: TradeSet) -> dict[tuple[int, int], int]:
    edges: dict[tuple[int, int], int] = {}
    both = np.concatenate([trades.side_a, trades.side_b], axis=1)
    for row in both:
        ids = sorted(set(int(a) for a in row if a >= 0))
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                key = (ids[i], ids[j])
                edges[key] = edges.get(key, 0) + 1
    return edges


def two_edge_connected_core(n_assets: int, trades: TradeSet, domain: np.ndarray) -> np.ndarray:
    """Per domain, the largest 2-edge-connected component of the asset
    co-occurrence graph (bridges removed; a pair seen in >=2 trades is never a
    bridge).  An asset hanging off the core by one trade cannot have its
    contrast to the core cross-checked, so plan §4.8 refuses it support."""
    edges = _co_occurrence_edges(trades)
    adj: list[list[tuple[int, int]]] = [[] for _ in range(n_assets)]
    keys = list(edges)
    for eid, (a, b) in enumerate(keys):
        adj[a].append((b, eid))
        adj[b].append((a, eid))
    bridges: set[int] = set()
    disc = [-1] * n_assets
    low = [0] * n_assets
    timer = 0
    for root in range(n_assets):
        if disc[root] != -1 or not adj[root]:
            continue
        disc[root] = low[root] = timer
        timer += 1
        stack: list[tuple[int, int, int]] = [(root, -1, 0)]
        while stack:
            node, parent_edge, idx = stack[-1]
            if idx < len(adj[node]):
                stack[-1] = (node, parent_edge, idx + 1)
                nxt, eid = adj[node][idx]
                if eid == parent_edge:
                    continue
                if disc[nxt] == -1:
                    disc[nxt] = low[nxt] = timer
                    timer += 1
                    stack.append((nxt, eid, 0))
                else:
                    low[node] = min(low[node], disc[nxt])
            else:
                stack.pop()
                if stack:
                    par = stack[-1][0]
                    low[par] = min(low[par], low[node])
                    if low[node] > disc[par] and edges[keys[parent_edge]] < 2:
                        bridges.add(parent_edge)
    # Components after removing bridges.
    comp = [-1] * n_assets
    c = 0
    for start in range(n_assets):
        if comp[start] != -1 or not adj[start]:
            continue
        comp[start] = c
        todo = [start]
        while todo:
            node = todo.pop()
            for nxt, eid in adj[node]:
                if eid in bridges or comp[nxt] != -1:
                    continue
                comp[nxt] = c
                todo.append(nxt)
        c += 1
    comp_arr = np.asarray(comp)
    core = np.zeros(n_assets, dtype=bool)
    for d in range(len(DOMAINS)):
        m = (domain == d) & (comp_arr >= 0)
        if not m.any():
            continue
        labels, counts = np.unique(comp_arr[m], return_counts=True)
        best = labels[np.argmax(counts)]
        core |= (domain == d) & (comp_arr == best)
    return core


def effective_resistance_to_core(n_assets: int, trades: TradeSet, core: np.ndarray) -> np.ndarray:
    """Diagnostic: resistance distance from each core asset to the core
    centroid in the multiplicity-weighted co-occurrence graph (``L^+``
    quadratic form).  NaN outside the core."""
    out = np.full(n_assets, np.nan)
    idx = np.flatnonzero(core)
    if idx.size < 2:
        return out
    pos = {int(a): i for i, a in enumerate(idx)}
    lap = np.zeros((idx.size, idx.size))
    for (a, b), m in _co_occurrence_edges(trades).items():
        if a in pos and b in pos:
            i, j = pos[a], pos[b]
            lap[i, j] -= m
            lap[j, i] -= m
            lap[i, i] += m
            lap[j, j] += m
    lp = np.linalg.pinv(lap)
    centre = lp.mean(axis=1)
    out[idx] = np.diag(lp) - 2 * centre + lp.mean()
    return out


# --------------------------------------------------------------------------- #
# Latent model: objective, gradient, Jacobian
# --------------------------------------------------------------------------- #


@dataclass
class _Design:
    n_assets: int
    n_fx: int
    n_mgr: int
    n_groups: int
    n_dom: int
    side_a: np.ndarray
    side_b: np.ndarray
    combo_a: np.ndarray
    combo_b: np.ndarray
    mgr_a: np.ndarray
    mgr_b: np.ndarray
    fx_map: np.ndarray  # (n_combo, n_fx)
    pen: sparse.csr_matrix  # rows e_a = theta_a - m_g - beta_d x_a
    ridge: np.ndarray  # diagonal ridge per parameter

    @property
    def n_params(self) -> int:
        return self.n_assets + self.n_fx + self.n_mgr + self.n_groups + self.n_dom


def _build_design(world: SimWorld, trades: TradeSet, spec: EstimatorSpec) -> _Design:
    assets = world.assets
    n_a = assets.n
    effects = world.config.format_effects if spec.format_effects else ()
    fx_map = format_effect_design(effects)
    n_fx = fx_map.shape[1]
    n_mgr = len(world.manager_ids) if spec.manager_effect else 0
    n_groups = len(POSITIONS)
    n_dom = len(DOMAINS)
    n_strata = len(STRATA)

    def _combo(side: np.ndarray) -> np.ndarray:
        pos = np.where(side >= 0, assets.position[np.maximum(side, 0)], 0)
        return pos * n_strata + trades.stratum[:, None]

    off_m = n_a + n_fx + n_mgr
    off_b = off_m + n_groups
    rows = np.repeat(np.arange(n_a), 3)
    cols = np.stack(
        [np.arange(n_a), off_m + assets.position, off_b + assets.domain], axis=1
    ).reshape(-1)
    vals = np.stack([np.ones(n_a), -np.ones(n_a), -assets.prior_feature], axis=1).reshape(-1)
    pen = sparse.csr_matrix(
        (vals, (rows, cols)), shape=(n_a, n_a + n_fx + n_mgr + n_groups + n_dom)
    )
    ridge = np.zeros(pen.shape[1])
    ridge[n_a : n_a + n_fx] = 1.0  # format shifts: weakly toward 0 (1 log-unit sd)
    ridge[n_a + n_fx : off_m] = 1.0 / spec.manager_sd**2
    ridge[off_m:off_b] = 1e-4  # location: barely identified, data identify contrasts only
    ridge[off_b:] = 1e-2
    return _Design(
        n_assets=n_a,
        n_fx=n_fx,
        n_mgr=n_mgr,
        n_groups=n_groups,
        n_dom=n_dom,
        side_a=trades.side_a,
        side_b=trades.side_b,
        combo_a=_combo(trades.side_a),
        combo_b=_combo(trades.side_b),
        mgr_a=trades.mgr_a,
        mgr_b=trades.mgr_b,
        fx_map=fx_map,
        pen=pen,
        ridge=ridge,
    )


def _side_terms(
    theta: np.ndarray, combo_off: np.ndarray, side: np.ndarray, combo: np.ndarray, q: float
) -> tuple[np.ndarray, np.ndarray]:
    """``(logU, dlogU/dz)`` per trade side.  ``z`` is slot log value incl. the
    format offset; padded slots contribute nothing."""
    mask = side >= 0
    z = theta[np.maximum(side, 0)] + combo_off[combo]
    v = np.where(mask, np.exp(np.minimum(z, 50.0)), 0.0)
    order = np.argsort(-v, axis=1, kind="stable")
    rank = np.argsort(order, axis=1, kind="stable")
    qpow = q**rank
    u = np.sum(qpow * v, axis=1)
    u = np.maximum(u, 1e-300)
    return np.log(u), np.where(mask, qpow * v / u[:, None], 0.0)


def _residuals(params: np.ndarray, d: _Design, q: float):
    theta = params[: d.n_assets]
    gamma = params[d.n_assets : d.n_assets + d.n_fx]
    combo_off = d.fx_map @ gamma if d.n_fx else np.zeros(d.fx_map.shape[0])
    la, ga = _side_terms(theta, combo_off, d.side_a, d.combo_a, q)
    lb, gb = _side_terms(theta, combo_off, d.side_b, d.combo_b, q)
    r = la - lb
    if d.n_mgr:
        u = params[d.n_assets + d.n_fx : d.n_assets + d.n_fx + d.n_mgr]
        r = r - (u[d.mgr_a] - u[d.mgr_b])
    return r, ga, gb


def _psi(r: np.ndarray, loss: str, delta: float) -> tuple[np.ndarray, np.ndarray]:
    if loss == "l2":
        return 0.5 * r * r, r
    a = np.abs(r)
    rho = np.where(a <= delta, 0.5 * r * r, delta * (a - 0.5 * delta))
    return rho, np.clip(r, -delta, delta)


def _jacobian(d: _Design, ga: np.ndarray, gb: np.ndarray) -> sparse.csr_matrix:
    n = ga.shape[0]
    rows_l: list[np.ndarray] = []
    cols_l: list[np.ndarray] = []
    vals_l: list[np.ndarray] = []
    tr = np.repeat(np.arange(n)[:, None], MAX_PACKAGE, axis=1)
    for side, combo, g, sign in ((d.side_a, d.combo_a, ga, 1.0), (d.side_b, d.combo_b, gb, -1.0)):
        m = side >= 0
        rows_l.append(tr[m])
        cols_l.append(side[m])
        vals_l.append(sign * g[m])
        if d.n_fx:
            fx_rows = d.fx_map[combo[m]]  # (n_slots, n_fx)
            for k in range(d.n_fx):
                nz = fx_rows[:, k] != 0
                rows_l.append(tr[m][nz])
                cols_l.append(np.full(int(nz.sum()), d.n_assets + k))
                vals_l.append(sign * g[m][nz] * fx_rows[nz, k])
    if d.n_mgr:
        base = d.n_assets + d.n_fx
        rows_l += [np.arange(n), np.arange(n)]
        cols_l += [base + d.mgr_a, base + d.mgr_b]
        vals_l += [-np.ones(n), np.ones(n)]
    return sparse.csr_matrix(
        (np.concatenate(vals_l), (np.concatenate(rows_l), np.concatenate(cols_l))),
        shape=(n, d.n_params),
    )


def _objective(params, d: _Design, q, w, loss, delta, inv_tau2):
    r, ga, gb = _residuals(params, d, q)
    rho, psi = _psi(r, loss, delta)
    e = d.pen @ params
    f = float(np.sum(w * rho) + 0.5 * inv_tau2 * e @ e + 0.5 * np.sum(d.ridge * params * params))
    jac = _jacobian(d, ga, gb)
    g = jac.T @ (w * psi) + inv_tau2 * (d.pen.T @ e) + d.ridge * params
    return f, np.asarray(g).reshape(-1)


def _minimise(d, q, w, loss, delta, inv_tau2, x0):
    res = optimize.minimize(
        _objective,
        x0,
        args=(d, q, w, loss, delta, inv_tau2),
        jac=True,
        method="L-BFGS-B",
        options={"maxiter": 2000, "maxfun": 4000, "gtol": 1e-7},
    )
    return res


def _info_and_clusters(
    world: SimWorld, trades: TradeSet, w: np.ndarray, theta: np.ndarray, q: float
):
    """Per asset: information-weighted appearances (a slot at sorted rank k
    counts ``w * q**k`` — a 5th piece at q=0.78 counts ~0.37), distinct
    components, max single-component share and Kish n_eff over components."""
    n_a = world.assets.n
    comp = trades.component
    n_c = int(comp.max(initial=-1)) + 1
    per = np.zeros((n_a, max(n_c, 1)))
    raw = np.zeros(n_a)
    for side in (trades.side_a, trades.side_b):
        mask = side >= 0
        v = np.where(mask, np.exp(theta[np.maximum(side, 0)]), 0.0)
        rank = np.argsort(np.argsort(-v, axis=1, kind="stable"), axis=1, kind="stable")
        info = np.where(mask, w[:, None] * q**rank, 0.0)
        a_idx = side[mask]
        np.add.at(per, (a_idx, np.repeat(comp[:, None], MAX_PACKAGE, axis=1)[mask]), info[mask])
        np.add.at(raw, a_idx, 1.0)
    total = per.sum(axis=1)
    n_components = (per > 0).sum(axis=1)
    share = np.where(total > 0, per.max(axis=1) / np.maximum(total, 1e-300), np.nan)
    sq = np.square(per).sum(axis=1)
    n_eff = np.where(sq > 0, total * total / np.maximum(sq, 1e-300), 0.0)
    return {
        "appearances": raw,
        "info_appearances": total,
        "components": n_components.astype(int),
        "max_component_share": share,
        "n_eff_components": n_eff,
    }


def _classify(info, se, prior_infl, core, thr: SupportThresholds, has_se: bool):
    n = info["appearances"].shape[0]
    status = np.full(n, STATUS_PRIOR_DOMINATED, dtype=object)
    reason = np.full(n, "", dtype=object)
    for a in range(n):
        if info["appearances"][a] == 0:
            status[a], reason[a] = STATUS_INSUFFICIENT, "no_trade_evidence"
            continue
        if thr.require_core and not core[a]:
            status[a], reason[a] = STATUS_INSUFFICIENT, "outside_two_edge_connected_core"
            continue
        checks = (
            (info["info_appearances"][a] >= thr.min_info_appearances, "info_appearances_below_min"),
            (info["components"][a] >= thr.min_components, "too_few_components"),
            (info["max_component_share"][a] <= thr.max_component_share, "one_component_dominates"),
            (not has_se or prior_infl[a] <= thr.max_prior_influence, "prior_influence_above_max"),
            (not has_se or se[a] <= thr.max_contrast_se, "interval_too_wide"),
        )
        failed = [why for ok, why in checks if not ok]
        if failed:
            reason[a] = failed[0]
        else:
            status[a] = STATUS_SUPPORTED
    return status, reason


def _contrast_matrix(core: np.ndarray, domain: np.ndarray) -> np.ndarray:
    """``C`` with ``C @ theta = theta_a - mean(theta over a's domain core)``."""
    n = core.shape[0]
    c = np.eye(n)
    for d in range(len(DOMAINS)):
        ref = np.flatnonzero(core & (domain == d))
        if ref.size == 0:
            ref = np.flatnonzero(domain == d)
        rows = np.flatnonzero(domain == d)
        if rows.size and ref.size:
            c[np.ix_(rows, ref)] -= 1.0 / ref.size
    return c


def fit_latent(
    world: SimWorld,
    trades: TradeSet,
    spec: EstimatorSpec,
    *,
    evidence_cutoff: float,
    thresholds: SupportThresholds = SupportThresholds(),
    n_starts: int = 1,
    seed: int = 0,
    compute_resistance: bool = False,
) -> FitResult:
    """Fit a sorted-geometric latent value model (bench prototype).

    Two stages: an L2 fit, then Huber with ``delta = k * 1.4826 * MAD`` of the
    stage-1 residuals, warm-started.  ``n_starts > 1`` adds seeded random
    starts and reports the largest contrast disagreement between them."""
    d = _build_design(world, trades, spec)
    w = observation_weights(
        trades,
        evidence_cutoff=evidence_cutoff,
        half_life_days=spec.half_life_days,
        league_cap=spec.league_cap,
        pair_cap=spec.pair_cap,
    )
    inv_tau2 = 1.0 / spec.tau**2
    rng = np.random.default_rng(seed)
    best = None
    start_thetas = []
    for s in range(max(1, n_starts)):
        x0 = np.zeros(d.n_params)
        if s:
            x0[: d.n_assets] = rng.normal(0.0, 0.5, d.n_assets)
        res = _minimise(d, spec.q, w, "l2", 1.0, inv_tau2, x0)
        delta = 1.0
        if spec.loss == "huber":
            r0, _, _ = _residuals(res.x, d, spec.q)
            scale = 1.4826 * float(np.median(np.abs(r0 - np.median(r0)))) if r0.size else 1.0
            delta = spec.huber_k * max(scale, 1e-3)
            res = _minimise(d, spec.q, w, "huber", delta, inv_tau2, res.x)
        start_thetas.append(res.x[: d.n_assets].copy())
        if best is None or res.fun < best[0].fun:
            best = (res, delta)
    res, delta = best
    params = res.x
    theta = params[: d.n_assets].copy()

    # Cluster-robust Laplace covariance (prior information kept in the meat so
    # an asset with no data reports the prior's width, never zero).
    r, ga, gb = _residuals(params, d, spec.q)
    _, psi = _psi(r, spec.loss, delta)
    dpsi = np.ones_like(r) if spec.loss == "l2" else (np.abs(r) <= delta).astype(float)
    jac = _jacobian(d, ga, gb)
    hpen = inv_tau2 * (d.pen.T @ d.pen) + sparse.diags(d.ridge)
    hess = (jac.T @ sparse.diags(w * dpsi) @ jac + hpen).tocsc()
    comp = trades.component
    uniq, comp_idx = np.unique(comp, return_inverse=True)
    n_clusters = int(uniq.size)
    scores = (
        jac.T
        @ sparse.csr_matrix(
            ((w * psi), (np.arange(trades.n), comp_idx)), shape=(trades.n, max(n_clusters, 1))
        )
    ).toarray()
    if n_clusters > 1:
        scores *= math.sqrt(n_clusters / (n_clusters - 1))
    e_assets = sparse.eye(d.n_params, d.n_assets, format="csc")
    try:
        lu = splinalg.splu(hess)
        x = lu.solve(e_assets.toarray())  # (p, n_assets) = H^-1 restricted
    except RuntimeError:
        x = np.linalg.lstsq(hess.toarray(), e_assets.toarray(), rcond=None)[0]
    xs = x.T @ scores  # (n_assets, G)
    v = xs @ xs.T + x.T @ (hpen @ x)

    world_trades_core = two_edge_connected_core(d.n_assets, trades, world.assets.domain)
    cmat = _contrast_matrix(world_trades_core, world.assets.domain)
    var_c = np.einsum("ij,jk,ik->i", cmat, v, cmat)
    # Plan §4.7 full-row prior influence, tau^-2 * sum_b |[H^-1]_ab|, taken in
    # CONTRAST space: the common location is identified only by a tiny ridge,
    # so a raw row sum would be dominated by a direction no trade can inform.
    # ~1 for an asset the trades say nothing about, -> 0 as evidence grows.
    hinv_c = cmat @ x[: d.n_assets, :] @ cmat.T
    prior_row = inv_tau2 * np.abs(hinv_c).sum(axis=1)
    # The full row is NOT bounded by 1 (neighbouring assets' posteriors are
    # positively correlated), so the gate uses the bounded diagonal share
    # tau^-2 [C H^-1 C']_aa in [0, ~1] and the row is reported beside it;
    # the preregistration fixes which one gates after X1 recovery runs.
    prior_infl = inv_tau2 * np.diag(hinv_c)
    se = np.sqrt(np.maximum(var_c, 0.0))
    info = _info_and_clusters(world, trades, w, theta, spec.q)
    info["prior_influence"] = prior_infl
    info["prior_influence_row"] = prior_row
    if compute_resistance:
        info["effective_resistance"] = effective_resistance_to_core(
            d.n_assets, trades, world_trades_core
        )
    status, reason = _classify(info, se, prior_infl, world_trades_core, thresholds, True)

    gamma = params[d.n_assets : d.n_assets + d.n_fx]
    offs = (d.fx_map @ gamma) if d.n_fx else np.zeros(d.fx_map.shape[0])
    theta_out = theta.copy()
    theta_out[status == STATUS_INSUFFICIENT] = np.nan
    spread = 0.0
    if len(start_thetas) > 1:
        cs = [cmat @ t for t in start_thetas]
        spread = float(max(np.max(np.abs(a - cs[0])) for a in cs[1:]))
    return FitResult(
        spec=spec,
        theta=theta_out,
        se_contrast=se,
        status=status,
        reason=reason,
        format_offset=offs.reshape(len(POSITIONS), len(STRATA)),
        q_eval=spec.q,
        core=world_trades_core,
        info=info,
        diagnostics={
            "converged": bool(res.success),
            "objective": float(res.fun),
            "huber_delta": float(delta),
            "n_params": int(d.n_params),
            "n_train_trades": int(trades.n),
            "kish_n_eff_trades": kish_effective_n(w),
            "start_spread_max_abs_contrast": spread,
            "fitted_format_effects": dict(
                zip(
                    [
                        f"{p}:{v}"
                        for p, v, _ in (world.config.format_effects if spec.format_effects else ())
                    ],
                    [float(g) for g in gamma],
                )
            ),
        },
        n_clusters=n_clusters,
        internals={
            "x": x,
            "jac": jac,
            "w": w,
            "psi": psi,
            "cmat": cmat,
            "trades": trades,
            "n_assets": d.n_assets,
        },
    )


def fit_bt(
    world: SimWorld,
    trades: TradeSet,
    spec: EstimatorSpec,
    *,
    evidence_cutoff: float,
    thresholds: SupportThresholds = SupportThresholds(),
) -> FitResult:
    """Bradley–Terry consolidation baseline: 1-for-k ⇒ the single asset beats
    each of the k; 1-for-1 ⇒ tie (y = 0.5).  Same consensus-free prior."""
    n_a = world.assets.n
    win, lose, ys, wt = [], [], [], []
    w_obs = observation_weights(
        trades,
        evidence_cutoff=evidence_cutoff,
        half_life_days=spec.half_life_days,
        league_cap=spec.league_cap,
        pair_cap=spec.pair_cap,
    )
    counts = trades.counts()
    for t in range(trades.n):
        ka, kb = counts[t]
        a = [int(x) for x in trades.side_a[t] if x >= 0]
        b = [int(x) for x in trades.side_b[t] if x >= 0]
        if ka == 1 and kb == 1:
            win.append(a[0])
            lose.append(b[0])
            ys.append(0.5)
            wt.append(w_obs[t])
        elif ka == 1 or kb == 1:
            single, many = (a[0], b) if ka == 1 else (b[0], a)
            for m in many:
                win.append(single)
                lose.append(m)
                ys.append(1.0)
                wt.append(w_obs[t] / len(many))
    win_a, lose_a = np.asarray(win, dtype=int), np.asarray(lose, dtype=int)
    y, wt_a = np.asarray(ys), np.asarray(wt)
    x_feat = world.assets.prior_feature
    pos, dom = world.assets.position, world.assets.domain
    n_g, n_d = len(POSITIONS), len(DOMAINS)
    inv_tau2 = 1.0 / spec.tau**2

    def f(p):
        th, m, b = p[:n_a], p[n_a : n_a + n_g], p[n_a + n_g :]
        diff = th[win_a] - th[lose_a]
        # log-loss of P(win beats lose) = sigmoid(diff)
        ll = np.logaddexp(0, -diff) * y + np.logaddexp(0, diff) * (1 - y)
        sig = 1.0 / (1.0 + np.exp(-diff))
        gdiff = wt_a * (sig - y)
        e = th - m[pos] - b[dom] * x_feat
        val = float(np.sum(wt_a * ll) + 0.5 * inv_tau2 * e @ e + 0.5e-4 * m @ m + 0.5e-2 * b @ b)
        g = np.zeros_like(p)
        np.add.at(g, win_a, gdiff)
        np.add.at(g, lose_a, -gdiff)
        g[:n_a] += inv_tau2 * e
        g[n_a : n_a + n_g] += -inv_tau2 * np.bincount(pos, weights=e, minlength=n_g) + 1e-4 * m
        g[n_a + n_g :] += -inv_tau2 * np.bincount(dom, weights=e * x_feat, minlength=n_d) + 1e-2 * b
        return val, g

    res = optimize.minimize(
        f, np.zeros(n_a + n_g + n_d), jac=True, method="L-BFGS-B", options={"maxiter": 2000}
    )
    theta = res.x[:n_a].copy()
    core = two_edge_connected_core(n_a, trades, dom)
    info = _info_and_clusters(world, trades, w_obs, theta, 0.78)
    info["prior_influence"] = np.full(n_a, np.nan)
    status, reason = _classify(info, None, None, core, thresholds, False)
    theta[status == STATUS_INSUFFICIENT] = np.nan
    return FitResult(
        spec=spec,
        theta=theta,
        se_contrast=None,
        status=status,
        reason=reason,
        format_offset=np.zeros((len(POSITIONS), len(STRATA))),
        q_eval=0.78,
        core=core,
        info=info,
        diagnostics={
            "converged": bool(res.success),
            "n_comparisons": int(y.size),
            "n_train_trades": int(trades.n),
        },
        n_clusters=int(np.unique(trades.component).size),
    )


def fit_prior_only(world: SimWorld, trades: TradeSet, spec: EstimatorSpec, **_: Any) -> FitResult:
    """The consensus-free covariate alone.  Every asset is PRIOR_DOMINATED by
    construction; cross-domain placement is undefined, so metrics stay within
    domain."""
    n = world.assets.n
    core = two_edge_connected_core(n, trades, world.assets.domain)
    info = _info_and_clusters(world, trades, np.ones(trades.n), world.assets.prior_feature, 0.78)
    return FitResult(
        spec=spec,
        theta=world.assets.prior_feature.astype(float).copy(),
        se_contrast=None,
        status=np.full(n, STATUS_PRIOR_DOMINATED, dtype=object),
        reason=np.full(n, "prior_only_estimator", dtype=object),
        format_offset=np.zeros((len(POSITIONS), len(STRATA))),
        q_eval=0.78,
        core=core,
        info=info,
        diagnostics={"n_train_trades": int(trades.n)},
        n_clusters=int(np.unique(trades.component).size),
    )


def fit_estimator(
    world, trades, spec, *, evidence_cutoff, thresholds=SupportThresholds(), **kw
) -> FitResult:
    if spec.kind == "prior":
        return fit_prior_only(world, trades, spec)
    if spec.kind == "bt":
        return fit_bt(world, trades, spec, evidence_cutoff=evidence_cutoff, thresholds=thresholds)
    return fit_latent(
        world, trades, spec, evidence_cutoff=evidence_cutoff, thresholds=thresholds, **kw
    )


# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #


def true_tiers(world: SimWorld, truth: np.ndarray) -> np.ndarray:
    """Tier label per asset from the TRUE value at the evidence cutoff."""
    assets = world.assets
    out = np.full(assets.n, "", dtype=object)
    for d, name in enumerate(DOMAINS):
        idx = np.flatnonzero(assets.domain == d)
        if name == "picks":
            for label, rounds in PICK_TIERS:
                out[idx[np.isin(assets.pick_round[idx], rounds)]] = f"{name}:{label}"
            continue
        order = idx[np.argsort(-truth[idx], kind="stable")]
        lo = 0
        for label, hi in TIER_EDGES[name]:
            out[order[lo : min(hi, order.size)]] = f"{name}:{label}"
            lo = hi
            if lo >= order.size:
                break
    return out


def pairwise_accuracy(
    true: np.ndarray, est: np.ndarray, *, min_log_gap: float
) -> tuple[float | None, int]:
    """Share of pairs (true log gap >= ``min_log_gap``) the estimate orders
    correctly; ties count half.  Invariant to any strictly monotone transform
    of ``est``; a constant estimate scores exactly 0.5."""
    t = np.asarray(true, float)
    e = np.asarray(est, float)
    ok = np.isfinite(t) & np.isfinite(e)
    t, e = t[ok], e[ok]
    if t.size < 2:
        return None, 0
    dt = t[:, None] - t[None, :]
    de = e[:, None] - e[None, :]
    iu = np.triu_indices(t.size, 1)
    dt, de = dt[iu], de[iu]
    keep = np.abs(dt) >= min_log_gap
    if not keep.any():
        return None, 0
    dt, de = dt[keep], de[keep]
    score = np.where(de == 0, 0.5, (np.sign(dt) == np.sign(de)).astype(float))
    return float(score.mean()), int(score.size)


def _offsets_for(
    fit: FitResult, assets_pos: np.ndarray, side: np.ndarray, stratum: np.ndarray
) -> np.ndarray:
    pos = np.where(side >= 0, assets_pos[np.maximum(side, 0)], 0)
    return fit.format_offset[pos, stratum[:, None]]


def side_log_utility(
    fit: FitResult, assets_pos: np.ndarray, side: np.ndarray, stratum: np.ndarray, q: float
) -> np.ndarray:
    """Fitted ``log U`` per side (u = 0, no manager effect — the published
    quantity, plan §5)."""
    mask = side >= 0
    z = fit.theta[np.maximum(side, 0)] + _offsets_for(fit, assets_pos, side, stratum)
    v = np.where(mask, np.exp(np.minimum(z, 50.0)), 0.0)
    vs = -np.sort(-v, axis=1)
    u = np.sum(vs * q ** np.arange(side.shape[1]), axis=1)
    with np.errstate(divide="ignore"):
        return np.log(u)


def decoy_accuracy(
    world: SimWorld,
    fit: FitResult,
    trades: TradeSet,
    *,
    q: float,
    n_decoys: int = 4,
    seed: int = 0,
) -> dict[str, Any]:
    """Held-out choice metric: does the actual counter-package fit side A
    better than (a) size-matched random decoys from the same held-out period's
    traded assets and (b) "hard" decoys that swap ONE asset of side B for a
    same-position traded asset?  Ties count half; a constant estimate scores
    0.5 on both.  Trades touching an asset without an estimate are skipped and
    counted, never imputed."""
    empty = {"easy": None, "hard": None, "evaluated": 0, "skipped_unpriced": 0}
    if trades.n == 0:
        return empty
    priced = np.isfinite(fit.theta) & (fit.status != STATUS_INSUFFICIENT)
    ok = np.ones(trades.n, dtype=bool)
    for side in (trades.side_a, trades.side_b):
        ok &= np.all((side < 0) | priced[np.maximum(side, 0)], axis=1)
    t = trades.subset(ok)
    if t.n == 0:
        return {**empty, "skipped_unpriced": int((~ok).sum())}
    rng = np.random.default_rng(seed)
    pos = world.assets.position
    pool = np.unique(np.concatenate([t.side_a[t.side_a >= 0], t.side_b[t.side_b >= 0]]))
    by_pos = {int(p): pool[pos[pool] == p] for p in np.unique(pos[pool])}
    kb_arr = (t.side_b >= 0).sum(axis=1)
    easy = np.full((t.n, n_decoys, MAX_PACKAGE), -1)
    hard = np.repeat(t.side_b[:, None, :], n_decoys, axis=1).copy()
    valid = np.zeros(t.n, dtype=bool)

    def _draw(cands: np.ndarray, avoid: set[int]) -> int | None:
        for _ in range(64):
            c = int(cands[int(rng.integers(cands.size))])
            if c not in avoid:
                return c
        rest = [int(c) for c in cands if int(c) not in avoid]
        return int(rng.choice(rest)) if rest else None

    for i in range(t.n):
        b = t.side_b[i]
        kb = int(kb_arr[i])
        used = {int(x) for x in t.side_a[i] if x >= 0} | {int(x) for x in b if x >= 0}
        if pool.size - len(used) < kb:
            continue
        valid[i] = True
        for j in range(n_decoys):
            chosen: set[int] = set()
            for k in range(kb):
                c = _draw(pool, used | chosen)
                chosen.add(c)
                easy[i, j, k] = c
            slot = int(rng.integers(0, kb))
            c = _draw(by_pos.get(int(pos[b[slot]]), pool), used)
            hard[i, j, slot] = c if c is not None else _draw(pool, used)
    if not valid.any():
        return {**empty, "skipped_unpriced": int((~ok).sum())}
    t = t.subset(valid)
    easy, hard = easy[valid], hard[valid]
    la = side_log_utility(fit, pos, t.side_a, t.stratum, q)
    lb = side_log_utility(fit, pos, t.side_b, t.stratum, q)
    actual = np.abs(la - lb)[:, None]
    strat = np.repeat(t.stratum, n_decoys)
    out = {}
    for name, arr in (("easy", easy), ("hard", hard)):
        ld = side_log_utility(fit, pos, arr.reshape(-1, MAX_PACKAGE), strat, q).reshape(
            t.n, n_decoys
        )
        dist = np.abs(la[:, None] - ld)
        out[name] = float(np.mean(np.where(dist == actual, 0.5, (actual < dist).astype(float))))
    return {**out, "evaluated": int(t.n), "skipped_unpriced": int((~ok).sum())}


def maturity_signal_test(
    world: SimWorld,
    fit: FitResult,
    trades: TradeSet,
    *,
    q: float,
    min_trades: int = 3,
    reading: str = "league_level",
) -> dict[str, Any]:
    """Does league age improve the signal?  Per league, mean |held-out
    residual| under the fit; one-sided Mann–Whitney: cohort A (>=3 completed
    seasons) less noisy than younger leagues.  Report-only.  ``reading`` is
    ``league_level`` (seasons as of the build) or ``point_in_time`` (seasons
    at each trade; a league's trades split into one group per cohort) —
    directive V2 / preregistration §9 report BOTH."""
    if reading not in ("league_level", "point_in_time"):
        raise ValueError(f"unknown maturity reading: {reading}")
    if trades.n == 0 or fit.spec.kind == "prior":
        return {"p_value": None, "n_A": 0, "n_younger": 0}
    pos = world.assets.position
    r = np.abs(
        side_log_utility(fit, pos, trades.side_a, trades.stratum, q)
        - side_log_utility(fit, pos, trades.side_b, trades.stratum, q)
    )
    ok = np.isfinite(r)
    if reading == "league_level":
        is_a = world.leagues.maturity[trades.league] >= 3
    else:
        is_a = trades.maturity_pit >= 3
    by_group: dict[tuple[int, bool], list[float]] = {}
    for lg, a, val in zip(trades.league[ok], is_a[ok], r[ok]):
        by_group.setdefault((int(lg), bool(a)), []).append(float(val))
    a_vals, y_vals = [], []
    for (_lg, a), vals in by_group.items():
        if len(vals) < min_trades:
            continue
        (a_vals if a else y_vals).append(float(np.mean(vals)))
    if len(a_vals) < 3 or len(y_vals) < 3:
        return {"p_value": None, "n_A": len(a_vals), "n_younger": len(y_vals)}
    p = float(stats.mannwhitneyu(a_vals, y_vals, alternative="less").pvalue)
    return {"p_value": p, "n_A": len(a_vals), "n_younger": len(y_vals)}


def evaluate_fit(
    world: SimWorld,
    fit: FitResult,
    *,
    truth: np.ndarray,
    test_sets: Mapping[str, TradeSet],
    min_log_gap: float = math.log(1.2),
    eval_qs: Sequence[float] = (0.70, 0.78, 0.85, 1.0),
    interval_level: float = 0.90,
    seed: int = 0,
) -> dict[str, Any]:
    """Every metric for one fit.  ``truth`` is the true reference-format log
    value at the evidence cutoff."""
    tiers = true_tiers(world, truth)
    appeared = fit.info["appearances"] > 0
    supported = fit.status == STATUS_SUPPORTED
    cmat = _contrast_matrix(fit.core, world.assets.domain)
    true_c = cmat @ truth
    est_c = cmat @ np.nan_to_num(fit.theta, nan=0.0)
    g = max(fit.n_clusters - 1, 1)
    tq = float(stats.t.ppf(0.5 + interval_level / 2, g))
    per_tier: dict[str, Any] = {}
    for tier in sorted(set(tiers) - {""}):
        in_tier = tiers == tier
        row: dict[str, Any] = {"n_assets": int(in_tier.sum())}
        for label, sel in (
            ("supported", in_tier & supported),
            ("appeared", in_tier & appeared & np.isfinite(fit.theta)),
        ):
            acc, npairs = pairwise_accuracy(truth[sel], fit.theta[sel], min_log_gap=min_log_gap)
            tau = None
            if sel.sum() >= 3:
                tau_v = stats.kendalltau(truth[sel], fit.theta[sel]).statistic
                tau = None if not np.isfinite(tau_v) else float(tau_v)
            row[label] = {
                "n": int(sel.sum()),
                "pairwise_accuracy": acc,
                "pairs": npairs,
                "kendall_tau": tau,
            }
        row["supported_coverage"] = float((in_tier & supported).sum() / max(in_tier.sum(), 1))
        if fit.se_contrast is not None and (in_tier & supported).any():
            sel = in_tier & supported
            hit = np.abs(est_c[sel] - true_c[sel]) <= tq * fit.se_contrast[sel]
            row["interval_coverage"] = float(hit.mean())
        else:
            row["interval_coverage"] = None
        per_tier[tier] = row
    held_out: dict[str, Any] = {}
    for name, ts in test_sets.items():
        by_q = {}
        for q in eval_qs:
            by_q[f"{q:.2f}"] = decoy_accuracy(world, fit, ts, q=q, seed=derive_seed(seed, name, q))
        best_q = max(by_q, key=lambda k: by_q[k]["hard"] if by_q[k]["hard"] is not None else -1)
        held_out[name] = {
            "at_fit_q": decoy_accuracy(
                world, fit, ts, q=fit.q_eval, seed=derive_seed(seed, name, "fit")
            ),
            "best_case_q": best_q,
            "best_case": by_q[best_q],
            "maturity_signal": maturity_signal_test(world, fit, ts, q=fit.q_eval),
            "maturity_signal_point_in_time": maturity_signal_test(
                world, fit, ts, q=fit.q_eval, reading="point_in_time"
            ),
        }
    status_counts = {
        s: int((fit.status == s).sum())
        for s in (STATUS_SUPPORTED, STATUS_PRIOR_DOMINATED, STATUS_INSUFFICIENT)
    }
    return {
        "estimator": fit.spec.name,
        "per_tier": per_tier,
        "held_out": held_out,
        "status_counts": status_counts,
        "n_clusters": fit.n_clusters,
        "diagnostics": fit.diagnostics,
    }


# --------------------------------------------------------------------------- #
# Worked examples: how each trade moved one estimate
# --------------------------------------------------------------------------- #


def trade_influence(fit: FitResult, asset: int) -> np.ndarray:
    """Approximate effect of each training trade on asset ``asset``'s contrast
    (``theta_a - core mean``): the one-step leave-one-out change
    ``-[C H^-1 g_t]_a`` with ``g_t = w_t psi(r_t) J_t``.  Positive means the
    trade pushed the estimate UP.  Latent fits only."""
    it = fit.internals
    if not it:
        raise ValueError("trade_influence needs a latent fit")
    x, jac, w, psi, cmat = it["x"], it["jac"], it["w"], it["psi"], it["cmat"]
    row = cmat[asset] @ x.T  # (p,) = d contrast_a / d (param gradient) direction
    g = jac.multiply((w * psi)[:, None]).tocsr()
    return -np.asarray(g @ row).reshape(-1)


def worked_examples(
    world: SimWorld, fit: FitResult, *, n_assets: int = 5, top_trades: int = 3
) -> list[dict[str, Any]]:
    """Synthetic worked examples: for the best-supported assets, the trades
    that moved the estimate most.  Same shape the real-data report uses for
    its five anonymized examples (directive V2 §10) — but every id here is
    synthetic."""
    trades: TradeSet = fit.internals["trades"]
    supported = np.flatnonzero(fit.status == STATUS_SUPPORTED)
    if supported.size == 0:
        return []
    order = supported[np.argsort(-fit.info["info_appearances"][supported], kind="stable")]
    picks: list[int] = []
    seen_dom: set[int] = set()
    for a in order:  # spread across domains first, then fill
        if world.assets.domain[a] not in seen_dom:
            picks.append(int(a))
            seen_dom.add(int(world.assets.domain[a]))
    for a in order:
        if len(picks) >= n_assets:
            break
        if int(a) not in picks:
            picks.append(int(a))
    out = []
    for a in picks[:n_assets]:
        infl = trade_influence(fit, a)
        top = np.argsort(-np.abs(infl), kind="stable")[:top_trades]
        rows = []
        for t in top:
            side = "A" if a in trades.side_a[t] else "B"
            rows.append(
                {
                    "trade": f"syn-trade-{int(t):05d}",
                    "shape": f"{int((trades.side_a[t] >= 0).sum())}-for-{int((trades.side_b[t] >= 0).sum())}",
                    "format": "/".join(STRATA[int(trades.stratum[t])]),
                    "asset_side": side,
                    "counterparts": [
                        world.assets.ids[int(b)]
                        for b in (trades.side_b[t] if side == "A" else trades.side_a[t])
                        if b >= 0
                    ],
                    "same_side": [
                        world.assets.ids[int(b)]
                        for b in (trades.side_a[t] if side == "A" else trades.side_b[t])
                        if b >= 0 and b != a
                    ],
                    "weight": round(float(fit.internals["w"][t]), 3),
                    "moved_estimate_pct": round(100.0 * (math.exp(float(infl[t])) - 1.0), 2),
                }
            )
        out.append(
            {
                "asset": world.assets.ids[a],
                "position": POSITIONS[int(world.assets.position[a])],
                "estimate_contrast_pct": round(
                    100.0
                    * (math.exp(float(fit.internals["cmat"][a] @ np.nan_to_num(fit.theta))) - 1.0),
                    1,
                ),
                "se_contrast_log": round(float(fit.se_contrast[a]), 3)
                if fit.se_contrast is not None
                else None,
                "info_appearances": round(float(fit.info["info_appearances"][a]), 2),
                "components": int(fit.info["components"][a]),
                "top_trades": rows,
            }
        )
    return out


# --------------------------------------------------------------------------- #
# Inner-CV configuration choice (training data only)
# --------------------------------------------------------------------------- #


def select_by_inner_cv(
    world: SimWorld,
    trades: TradeSet,
    base: EstimatorSpec,
    grid: Sequence[Mapping[str, Any]],
    *,
    validation_days: float = 28.0,
    seed: int = 0,
) -> dict[str, Any]:
    """Choose half-life / caps / tau from TRAINING data only (plan §4.5-4.7):
    fit on trades collected before ``evidence_cutoff - validation_days``,
    score hard-decoy accuracy on trades dated after it.  Decoy accuracy, not
    residual loss: on 1-for-1 trades a fully compressed board has residual 0,
    so residual loss would reward shrinking every value together.  The locked
    reserve never enters; ties keep the earlier (declared-prior) grid entry."""
    if trades.n == 0:
        return {"chosen": base, "scores": []}
    cutoff = float(trades.collected.max()) - validation_days
    inner_train = trades.collected <= cutoff
    inner_val = trades.date > cutoff
    if inner_train.sum() < 10 or inner_val.sum() < 10:
        return {"chosen": base, "scores": [], "note": "too_few_trades_for_inner_cv"}
    tr = trades.subset(inner_train)
    va = trades.subset(inner_val)
    ev = float(tr.collected.max())
    scores = []
    best: tuple[float, EstimatorSpec] | None = None
    for i, overrides in enumerate(grid):
        spec = replace(base, name=f"{base.name}|cv{i}", **dict(overrides))
        fit = fit_estimator(world, tr, spec, evidence_cutoff=ev)
        acc = decoy_accuracy(world, fit, va, q=spec.q, seed=derive_seed(seed, "inner", i))["hard"]
        scores.append({"overrides": dict(overrides), "hard_decoy_accuracy": acc})
        if acc is not None and (best is None or acc > best[0]):
            best = (acc, replace(base, **dict(overrides)))
    return {"chosen": best[1] if best else base, "scores": scores}


# --------------------------------------------------------------------------- #
# Scenario runner + power study
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SplitSpec:
    reserve_share: float = 0.2
    reserve_salt: str = "syn-salt-v1"
    holdout_days: float = 56.0
    purge_days: float = 7.0


def run_scenario(
    cfg: SimConfig,
    estimators: Sequence[EstimatorSpec] = DEFAULT_ESTIMATORS,
    *,
    split: SplitSpec = SplitSpec(),
    thresholds: SupportThresholds = SupportThresholds(),
    min_log_gap: float = math.log(1.2),
    eval_qs: Sequence[float] = (0.70, 0.78, 0.85, 1.0),
) -> dict[str, Any]:
    """Generate one world, split it, fit every estimator, evaluate."""
    world = generate_world(cfg)
    trades = world.trades
    reserve = reserved_components(
        world.component_ids, salt=split.reserve_salt, share=split.reserve_share
    )
    in_reserve = np.isin(trades.component, sorted(reserve))
    cutoff_day = cfg.span_days - split.holdout_days
    train_t, test_t, evidence_cutoff = chronological_split(
        trades, cutoff_day=cutoff_day, purge_days=split.purge_days
    )
    train = train_t & ~in_reserve
    if evidence_cutoff is None or not train.any():
        return {"error": "no_training_trades", "config": _cfg_summary(cfg, world)}
    evidence_cutoff = float(trades.collected[train].max())
    truth = world.assets.theta_at(evidence_cutoff)
    test_sets = {
        "chronological_future": trades.subset(test_t & ~in_reserve),
        "reserved_components": trades.subset(in_reserve & (trades.collected <= cfg.span_days + 7)),
    }
    tr = trades.subset(train)
    results = {}
    for spec in estimators:
        fit = fit_estimator(world, tr, spec, evidence_cutoff=evidence_cutoff, thresholds=thresholds)
        results[spec.name] = evaluate_fit(
            world,
            fit,
            truth=truth,
            test_sets=test_sets,
            min_log_gap=min_log_gap,
            eval_qs=eval_qs,
            seed=cfg.seed,
        )
    cohorts_now = maturity_cohort(tr.maturity_now)
    cohorts_pit = maturity_cohort(tr.maturity_pit)
    return {
        "config": _cfg_summary(cfg, world),
        "split": {
            "train_trades": int(train.sum()),
            "train_trades_by_domain": _trades_touching_domain(world, tr),
            "late_collected_excluded": int(
                ((trades.date <= cutoff_day) & (trades.collected > cutoff_day) & ~in_reserve).sum()
            ),
            "test_future_trades": test_sets["chronological_future"].n,
            "reserved_component_trades": test_sets["reserved_components"].n,
            "reserved_components": len(reserve),
            "evidence_cutoff_day": evidence_cutoff,
            "train_cohorts_league_level": {
                k: int((cohorts_now == k).sum()) for k in ("A", "B", "below_B")
            },
            "train_cohorts_point_in_time": {
                k: int((cohorts_pit == k).sum()) for k in ("A", "B", "below_B")
            },
        },
        "estimators": results,
    }


def _trades_touching_domain(world: SimWorld, trades: TradeSet) -> dict[str, int]:
    """Training trades with at least one asset of each domain — the unit a
    real-data count can be compared against (e.g. "trades containing an IDP
    player")."""
    both = np.concatenate([trades.side_a, trades.side_b], axis=1)
    dom = np.where(both >= 0, world.assets.domain[np.maximum(both, 0)], -1)
    return {name: int((dom == d).any(axis=1).sum()) for d, name in enumerate(DOMAINS)}


def _cfg_summary(cfg: SimConfig, world: SimWorld) -> dict[str, Any]:
    return {
        "seed": cfg.seed,
        "n_leagues": cfg.n_leagues,
        "trades_per_league": cfg.trades_per_league,
        "trades_generated": world.trades.n,
        "assets": world.assets.n,
        "managers": len(world.manager_ids),
        "components": len(world.component_ids),
        "largest_component_leagues": int(np.bincount(world.leagues.component).max())
        if world.leagues.n
        else 0,
        "q_true": cfg.q_true,
        "maturity_effect": cfg.maturity_effect,
        "manager_multi_league_prob": cfg.manager_multi_league_prob,
    }


def _metric(run: Mapping[str, Any], est: str, tier: str, metric: str) -> float | None:
    e = run.get("estimators", {}).get(est)
    if not e:
        return None
    if metric == "decoy_hard_future":
        return e["held_out"]["chronological_future"]["at_fit_q"]["hard"]
    if metric == "decoy_hard_reserved":
        return e["held_out"]["reserved_components"]["at_fit_q"]["hard"]
    row = e["per_tier"].get(tier)
    if row is None:
        return None
    if metric == "supported_coverage":
        return row["supported_coverage"]
    if metric == "interval_coverage":
        return row["interval_coverage"]
    if metric.startswith("appeared_"):
        return row["appeared"][metric[len("appeared_") :]]
    return row["supported"][metric]


def required_count(points: Sequence[tuple[float, float | None]], target: float) -> dict[str, Any]:
    """Smallest count at which the (count, metric) curve reaches ``target``
    AND stays there at every larger grid count; log-linear interpolation
    between the bracketing grid points.  ``beyond_grid`` when never reached —
    never an extrapolated guess."""
    pts = sorted((float(n), m) for n, m in points)
    if not pts:
        return {"state": "no_points", "required": None}
    ok = [m is not None and m >= target for _, m in pts]
    first = None
    for i in range(len(pts)):
        if all(ok[i:]):
            first = i
            break
    if first is None:
        return {"state": "beyond_grid", "required": None, "max_grid": pts[-1][0]}
    if first == 0:
        return {"state": "at_or_below_grid_min", "required": pts[0][0]}
    (n0, m0), (n1, m1) = pts[first - 1], pts[first]
    if m0 is None or m1 == m0:
        return {"state": "reached", "required": n1}
    frac = (target - m0) / (m1 - m0)
    req = math.exp(math.log(n0) + frac * (math.log(n1) - math.log(n0)))
    return {"state": "reached", "required": round(req, 1)}


def shortfall(required: Mapping[str, Any], observed: float | None) -> dict[str, Any]:
    """``required - observed``.  An unknown observed count is UNKNOWN, never
    zero; a requirement beyond the grid is reported as such."""
    if observed is None:
        return {"state": "unknown_observed_count", "shortfall": None}
    if required.get("required") is None:
        return {"state": required.get("state", "unknown"), "shortfall": None, "observed": observed}
    return {
        "state": "met" if observed >= required["required"] else "short",
        "shortfall": max(0.0, round(float(required["required"]) - float(observed), 1)),
        "observed": observed,
        "required": required["required"],
    }


def power_study(
    base: SimConfig,
    *,
    leagues_grid: Sequence[int],
    trades_per_league_grid: Sequence[float],
    replicates: int,
    estimators: Sequence[EstimatorSpec] = DEFAULT_ESTIMATORS,
    targets: Mapping[str, float] | None = None,
    metric: str = "pairwise_accuracy",
    split: SplitSpec = SplitSpec(),
    thresholds: SupportThresholds = SupportThresholds(),
    observed: Mapping[str, float | None] | None = None,
    min_log_gap: float = math.log(1.2),
    joint: Sequence[tuple[str, str]] = (("pairwise_accuracy", "supported_coverage"),),
) -> dict[str, Any]:
    """Grid over (leagues, trades per league) x replicates.  Returns per grid
    point the replicate mean / p10 of every tier metric, the required TOTAL
    trades to reach each target per tier and estimator (along the
    leagues-scale-with-volume diagonal of the grid at each trades-per-league),
    and the shortfall against an observed count when one is supplied.

    ``joint`` pairs (e.g. accuracy on the supported set AND supported
    coverage) report the larger of the two requirements: an accurate model
    that prices almost nobody has not met an accuracy target.  Required
    TRAINING trades are also grossed up by the measured train fraction (the
    locked reserve, the chronological holdout and late-collected rows are not
    training data) into total eligible trades."""
    targets = dict(targets or {"pairwise_accuracy": 0.80})
    observed = dict(observed or {})
    points: list[dict[str, Any]] = []
    for n_lg in leagues_grid:
        for tpl in trades_per_league_grid:
            runs = []
            for rep in range(replicates):
                cfg = replace(
                    base,
                    n_leagues=int(n_lg),
                    trades_per_league=float(tpl),
                    seed=derive_seed(base.seed, n_lg, tpl, rep),
                )
                runs.append(
                    run_scenario(
                        cfg,
                        estimators,
                        split=split,
                        thresholds=thresholds,
                        min_log_gap=min_log_gap,
                        eval_qs=(0.78,),
                    )
                )
            points.append(_summarise_point(n_lg, tpl, runs, estimators))
    tiers = sorted({t for p in points for est in p["metrics"].values() for t in est if ":" in t})
    requirements: dict[str, Any] = {}
    for est in [e.name for e in estimators]:
        for tier in tiers:
            for tname, tval in targets.items():
                for tpl in trades_per_league_grid:
                    curve = [
                        (
                            p["train_trades_mean"],
                            (p["metrics"][est].get(tier, {}).get(tname) or {}).get("mean"),
                        )
                        for p in points
                        if p["trades_per_league"] == tpl
                    ]
                    req = required_count(curve, tval)
                    key = f"{est}|{tier}|{tname}>={tval}|tpl={tpl:g}"
                    leagues_curve = [
                        (
                            p["n_leagues"],
                            (p["metrics"][est].get(tier, {}).get(tname) or {}).get("mean"),
                        )
                        for p in points
                        if p["trades_per_league"] == tpl
                    ]
                    dom_curve = [
                        (
                            p["train_trades_by_domain_mean"][tier.split(":")[0]],
                            (p["metrics"][est].get(tier, {}).get(tname) or {}).get("mean"),
                        )
                        for p in points
                        if p["trades_per_league"] == tpl
                    ]
                    requirements[key] = {
                        "required_train_trades": req,
                        "required_train_trades_touching_domain": required_count(dom_curve, tval),
                        "required_total_trades_incl_holdouts": _gross_up(req, points, tpl),
                        "required_leagues": required_count(leagues_curve, tval),
                        "shortfall_trades": shortfall(req, observed.get("train_trades")),
                    }
            for a_name, b_name in joint:
                if a_name not in targets or b_name not in targets:
                    continue
                for tpl in trades_per_league_grid:
                    ka = f"{est}|{tier}|{a_name}>={targets[a_name]}|tpl={tpl:g}"
                    kb = f"{est}|{tier}|{b_name}>={targets[b_name]}|tpl={tpl:g}"
                    ra, rb = requirements[ka], requirements[kb]
                    req = _joint(ra["required_train_trades"], rb["required_train_trades"])
                    requirements[f"{est}|{tier}|joint({a_name},{b_name})|tpl={tpl:g}"] = {
                        "required_train_trades": req,
                        "required_train_trades_touching_domain": _joint(
                            ra["required_train_trades_touching_domain"],
                            rb["required_train_trades_touching_domain"],
                        ),
                        "required_total_trades_incl_holdouts": _gross_up(req, points, tpl),
                        "required_leagues": _joint(ra["required_leagues"], rb["required_leagues"]),
                        "shortfall_trades": shortfall(req, observed.get("train_trades")),
                    }
    return {
        "base_config": {
            k: getattr(base, k)
            for k in base.__dataclass_fields__
            if k not in ("topology", "format_effects", "maturity_probs")
        },
        "grid": {
            "leagues": list(leagues_grid),
            "trades_per_league": list(trades_per_league_grid),
            "replicates": replicates,
        },
        "targets": targets,
        "observed": observed or None,
        "points": points,
        "requirements": requirements,
        "synthetic": True,
    }


def _joint(a: Mapping[str, Any], b: Mapping[str, Any]) -> dict[str, Any]:
    if a.get("required") is None or b.get("required") is None:
        bad = a if a.get("required") is None else b
        return {"state": bad.get("state", "unknown"), "required": None}
    return {"state": "reached", "required": max(a["required"], b["required"])}


def _gross_up(
    req: Mapping[str, Any], points: Sequence[Mapping[str, Any]], tpl: float
) -> dict[str, Any]:
    fr = [
        p["train_fraction_mean"]
        for p in points
        if p["trades_per_league"] == tpl and p["train_fraction_mean"]
    ]
    if req.get("required") is None or not fr:
        return {"state": req.get("state", "unknown"), "required": None}
    f = float(np.mean(fr))
    return {
        "state": req["state"],
        "required": round(req["required"] / f, 1),
        "train_fraction": round(f, 3),
    }


_TIER_METRICS = (
    "pairwise_accuracy",
    "kendall_tau",
    "supported_coverage",
    "interval_coverage",
    "appeared_pairwise_accuracy",
)


def _summarise_point(n_lg, tpl, runs, estimators) -> dict[str, Any]:
    good = [r for r in runs if "estimators" in r]
    out: dict[str, Any] = {
        "n_leagues": int(n_lg),
        "trades_per_league": float(tpl),
        "replicates_ok": len(good),
        "train_trades_mean": float(np.mean([r["split"]["train_trades"] for r in good]))
        if good
        else 0.0,
        "trades_generated_mean": float(np.mean([r["config"]["trades_generated"] for r in good]))
        if good
        else 0.0,
        "train_trades_by_domain_mean": {
            d: float(np.mean([r["split"]["train_trades_by_domain"][d] for r in good]))
            if good
            else 0.0
            for d in DOMAINS
        },
        "train_fraction_mean": (
            float(
                np.mean(
                    [
                        r["split"]["train_trades"] / max(r["config"]["trades_generated"], 1)
                        for r in good
                    ]
                )
            )
            if good
            else None
        ),
        "components_mean": float(np.mean([r["config"]["components"] for r in good]))
        if good
        else 0.0,
        "metrics": {},
    }
    for spec in estimators:
        est = spec.name
        tiers = sorted({t for r in good for t in r["estimators"][est]["per_tier"]})
        per: dict[str, Any] = {}
        for tier in tiers:
            row = {}
            for m in _TIER_METRICS:
                vals = [v for v in (_metric(r, est, tier, m) for r in good) if v is not None]
                row[m] = (
                    {
                        "mean": float(np.mean(vals)),
                        "p10": float(np.quantile(vals, 0.1)),
                        "n": len(vals),
                    }
                    if vals
                    else None
                )
            per[tier] = row
        for m in ("decoy_hard_future", "decoy_hard_reserved"):
            vals = [v for v in (_metric(r, est, "", m) for r in good) if v is not None]
            per[m] = {"mean": float(np.mean(vals)), "n": len(vals)} if vals else None
        for key, label in (
            ("maturity_signal", "maturity_signal_power_at_0.05"),
            ("maturity_signal_point_in_time", "maturity_signal_point_in_time_power_at_0.05"),
        ):
            fut = [r["estimators"][est]["held_out"]["chronological_future"] for r in good]
            pvals = [h[key]["p_value"] for h in fut if h[key]["p_value"] is not None]
            per[label] = (
                {"rate": float(np.mean([p < 0.05 for p in pvals])), "n": len(pvals)}
                if pvals
                else None
            )
        out["metrics"][est] = per
    return out
