"""POST-HOC reachability diagnostic for the harness-space G1 gate.

Not part of any preregistered evaluation, and it changes no gate, metric,
target, candidate or disposition.  It answers one question a reviewer asked of
the 2026-09-30 run: *were the gates attainable at all by a candidate of the
preregistered form?*  The answer separates two outcomes that read identically
as "DOES_NOT_MEET_PREREGISTERED_GATE":

* **no signal** -- even the best weights in the box cannot beat equal weights;
* **structurally unattainable** -- weights help, but no weight vector the
  challengers could express reaches the materiality bar.

Method: the harness cells are rebuilt exactly as :func:`evaluate.walk_forward`
builds them (every universe, every held-out family G, every test origin, the
primary horizon, all targets), then the weights are chosen IN SAMPLE -- on the
very test cells they are scored on -- to maximise Δ MALE.  That is an ORACLE:
an upper bound on what any learner restricted to the same weight box can reach
out of sample (per fold, the bound for fold-varying weights).  It is computed
by multi-start L-BFGS-B on an almost-everywhere smooth objective, so it is a
numerical optimum, not a certified global maximum.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from src.source_quality import metrics as mt
from src.source_quality import panel as pn


@dataclass(frozen=True)
class Cells:
    """Every harness cell: predictor families' scores, target, universe, fold."""

    families: list[str]
    x: np.ndarray  # (N, F) -log(rank) of each predictor family, NaN = not in predictor
    y: np.ndarray  # (N,) held-out family's board at T + h
    universe: np.ndarray  # (N,) index into UNIVERSES
    fold: np.ndarray  # (N,) fold index
    fold_starts: list[str]


UNIVERSES = (pn.OFFENSE, pn.IDP)


def harness_cells(m: pn.Matrix, X: Mapping[str, np.ndarray], plan) -> Cells:
    """The ``ALL`` / ``allTargets`` cells of :func:`evaluate.walk_forward`."""
    cfg, h = plan.metrics, plan.primary_horizon
    D = len(m.dates)
    last_origin = D - 1 - h
    d0 = m.dates.index(plan.fold_start)
    test = np.arange(d0, last_origin + 1)
    fams_all = sorted(X)
    col = {f: i for i, f in enumerate(fams_all)}
    xs, ys, us, fs = [], [], [], []
    for ui, u in enumerate(UNIVERSES):
        umask = m.universe == u
        fams = mt.families_in(X, umask)
        Xu = {f: np.where(umask[:, None], X[f], np.nan)[:, test] for f in fams}
        for G in fams:
            others = [f for f in fams if f != G]
            stack = np.stack([Xu[f] for f in others])
            cnt = np.isfinite(stack).sum(axis=0)
            y = mt.shifted(np.where(umask[:, None], X[G], np.nan), h)[:, test]
            ok = (cnt >= cfg.min_consensus_families) & np.isfinite(y)
            a, j = np.nonzero(ok)
            block = np.full((a.size, len(fams_all)), np.nan)
            for f in others:
                block[:, col[f]] = Xu[f][a, j]
            xs.append(block)
            ys.append(y[a, j])
            us.append(np.full(a.size, ui))
            fs.append(j // plan.fold_days)
    fold_starts = [
        m.dates[d0 + k * plan.fold_days].isoformat() for k in range(int(max(map(np.max, fs))) + 1)
    ]
    return Cells(
        fams_all,
        np.concatenate(xs),
        np.concatenate(ys),
        np.concatenate(us),
        np.concatenate(fs),
        fold_starts,
    )


def subset(c: Cells, keep: np.ndarray) -> Cells:
    return Cells(c.families, c.x[keep], c.y[keep], c.universe[keep], c.fold[keep], c.fold_starts)


def _weights_matrix(c: Cells, p: np.ndarray, per_universe: bool) -> np.ndarray:
    F = len(c.families)
    return p.reshape(len(UNIVERSES), F)[c.universe] if per_universe else p[None, :]


def errors(c: Cells, w: np.ndarray) -> np.ndarray:
    """Absolute error of the weighted-mean blend; ``w`` is (F,) or (N, F)."""
    mask = np.isfinite(c.x)
    W = np.broadcast_to(w, c.x.shape)
    num = np.where(mask, c.x * W, 0.0).sum(axis=1)
    den = np.where(mask, W, 0.0).sum(axis=1)
    return np.abs(num / den - c.y)


def delta(c: Cells, w: np.ndarray) -> float:
    """Δ MALE = champion MALE − candidate MALE on the same cells (> 0 = better)."""
    return float((errors(c, np.ones(len(c.families))) - errors(c, w)).mean())


def _objective(p: np.ndarray, c: Cells, per_universe: bool) -> tuple[float, np.ndarray]:
    mask = np.isfinite(c.x)
    W = _weights_matrix(c, p, per_universe)
    xw = np.where(mask, c.x, 0.0)
    Wm = np.where(mask, np.broadcast_to(W, c.x.shape), 0.0)
    den = Wm.sum(axis=1)
    b = (xw * Wm).sum(axis=1) / den
    r = b - c.y
    n = len(c.y)
    g_cell = np.sign(r)[:, None] * np.where(mask, (c.x - b[:, None]) / den[:, None], 0.0) / n
    if per_universe:
        grad = np.zeros((len(UNIVERSES), len(c.families)))
        np.add.at(grad, c.universe, g_cell)
        grad = grad.ravel()
    else:
        grad = g_cell.sum(axis=0)
    return float(np.abs(r).mean()), grad


def oracle(
    c: Cells,
    *,
    lo: float,
    hi: float,
    per_universe: bool = False,
    fixed: Sequence[str] = (),
    starts: int = 4,
    seed: int = 20261001,
) -> dict:
    """In-sample best weights in ``[lo, hi]`` (``fixed`` families held at 1.0)."""
    from scipy.optimize import minimize

    F = len(c.families)
    nU = len(UNIVERSES) if per_universe else 1
    present = np.isfinite(c.x).any(axis=0)
    bounds = []
    for _u in range(nU):
        for i, f in enumerate(c.families):
            pin = f in fixed or not present[i]
            bounds.append((1.0, 1.0) if pin else (lo, hi))
    rng = np.random.default_rng(seed)
    inits = [np.ones(F * nU)] + [
        np.array([rng.uniform(a, b) for a, b in bounds]) for _ in range(max(0, starts - 1))
    ]
    best = None
    for x0 in inits:
        res = minimize(
            _objective, x0, args=(c, per_universe), jac=True, method="L-BFGS-B", bounds=bounds
        )
        if best is None or res.fun < best.fun:
            best = res
    w = best.x
    W = _weights_matrix(c, w, per_universe)
    d = delta(c, W if per_universe else w)
    shaped = w.reshape(nU, F)
    weights = (
        {u: dict(zip(c.families, map(float, shaped[k]))) for k, u in enumerate(UNIVERSES)}
        if per_universe
        else dict(zip(c.families, map(float, shaped[0])))
    )
    flat = (
        weights
        if not per_universe
        else {f"{u}:{f}": v for u, ww in weights.items() for f, v in ww.items()}
    )
    return {
        "deltaMALE": d,
        "cells": int(len(c.y)),
        "weights": weights,
        "atBound": sorted(
            k for k, v in flat.items() if min(abs(v - lo), abs(v - hi)) < 1e-6 and lo != hi
        ),
    }


def per_fold_oracle(c: Cells, **kw) -> dict:
    """Weights re-optimised in sample for EACH fold: the bound for fold-varying
    weights.  The aggregate is the cell-weighted sum, exactly how Δ aggregates."""
    folds = []
    total = 0.0
    for k in sorted(set(c.fold.tolist())):
        sub = subset(c, c.fold == k)
        r = oracle(sub, **kw)
        total += r["deltaMALE"] * r["cells"]
        folds.append(
            {"foldStart": c.fold_starts[k], "cells": r["cells"], "deltaMALE": r["deltaMALE"]}
        )
    return {"deltaMALE": total / len(c.y), "cells": int(len(c.y)), "folds": folds}
