"""Source-quality metrics on the point-in-time panel.  Each answers ONE question.

Notation: ``X[F]`` is the (assets x dates) ``-log(rank)`` score of family ``F``
(higher is better), ``C_S`` the mean over the families in ``S`` present for a
cell.  Every target excludes the evaluated family (leave-family-out), and every
statistic is assembled from per-origin additive sums so the date-block bootstrap
(:mod:`bootstrap`) resamples origins, never cells.

* :func:`lead_lag` -- MARKET LEAD/LAG.  Cross-fitted: the other families are
  split into halves A and B.  The evaluated family's disagreement with A at T
  (``g = X_F - C_A``) is regressed against B's later move
  (``C_B(T+h) - C_B(T)``), controlling for A-vs-B disagreement and for B's own
  recent move.  ``gap`` never contains B's measurement noise, so the
  regression-to-the-mean that makes ANY disagreement look prescient when the
  target and the baseline share noise cannot inflate it.  ``beta_gap`` is the
  fraction of F's disagreement that the independent market closes within h.
* :func:`stability` -- STABILITY/NOISE.  Self-reversal (fraction of a move the
  family itself undoes within h), move-confirmation (does the independent
  market later follow the family's own move, controlling for the market's own
  contemporaneous move), and the abandoned-move rate (a large move that the
  family reverses by half or more while the market does not follow).
* :func:`event_response` -- EVENT RESPONSIVENESS.  Events are defined from the
  OTHER families' consensus only (the evaluated family cannot define its own
  events); timing is the half-move crossing day relative to the market's.  It
  is reported beside the abandoned-move rate so responsiveness is never read
  without its noise.
* :func:`future_agreement` -- how close the family's board at T sits to the
  leave-family-out consensus at T+h, relative to its peers on the SAME cells.
  This is agreement with future independent evidence; it is never accuracy.
* :func:`fundamental_foresight` -- SECONDARY diagnostic against realized
  outcomes; never a definition of value.  Runs only when realized outcomes are
  supplied.
* :func:`transaction_fit` -- seam for the Unit I completed-trade ledger.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
import zlib

import numpy as np

from src.source_quality.bootstrap import block_ids, bootstrap
from src.source_quality.panel import IDP, OFFENSE, Matrix

FRESH_MIN_DAYS = 7.0  # preregistered: freshness-conditioning floor
FRESH_CADENCE_MULT = 2.0  # preregistered: and twice the source's cadence


@dataclass(frozen=True)
class Config:
    horizons: tuple[int, ...] = (7, 21, 42)
    lookback: int = 7
    splits: int = 8
    n_boot: int = 400
    seed: int = 20261001
    block_days: int = 14
    min_consensus_families: int = 2
    abandoned_move: float = float(np.log(1.25))
    event_quantile: float = 0.98
    event_window_days: int = 7
    event_follow_days: int = 14


def shifted(arr: np.ndarray, s: int) -> np.ndarray:
    """``out[:, j] = arr[:, j + s]``; NaN where ``j + s`` falls outside."""
    out = np.full_like(arr, np.nan)
    if s == 0:
        return arr.copy()
    if s > 0:
        out[:, :-s] = arr[:, s:]
    else:
        out[:, -s:] = arr[:, :s]
    return out


def consensus(X: Mapping[str, np.ndarray], fams: Iterable[str]) -> tuple[np.ndarray, np.ndarray]:
    fams = [f for f in fams if f in X]
    if not fams:
        any_arr = next(iter(X.values()))
        return np.full_like(any_arr, np.nan), np.zeros(any_arr.shape, dtype=np.int64)
    stack = np.stack([X[f] for f in fams])
    count = np.isfinite(stack).sum(axis=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = np.nansum(stack, axis=0) / np.where(count > 0, count, np.nan)
    return mean, count


def families_in(X: Mapping[str, np.ndarray], universe_mask: np.ndarray) -> list[str]:
    return sorted(f for f, arr in X.items() if np.isfinite(arr[universe_mask]).any())


def family_age(m: Matrix) -> dict[str, np.ndarray]:
    """Age (days) of the family's freshest member version at each date."""
    out = {}
    for fam, members in m.family_members().items():
        stack = np.stack([m.age_days[k] for k in members])
        with np.errstate(invalid="ignore"):
            out[fam] = np.where(
                np.isfinite(stack).any(axis=0),
                np.nanmin(np.where(np.isfinite(stack), stack, np.inf), axis=0),
                np.nan,
            )
    return out


def fresh_dates(m: Matrix, fam: str) -> np.ndarray:
    """Dates on which the family's evidence is fresh enough to judge its BASE
    quality.  Staleness is the freshness factor's job, so judging base quality
    on stale observations would let 'fresh' and 'historically accurate'
    collapse into one number."""
    ages = family_age(m)[fam]
    cad = [m.specs[k].cadence_hours for k in m.family_members()[fam] if m.specs[k].cadence_hours]
    bound = max(FRESH_MIN_DAYS, FRESH_CADENCE_MULT * (max(cad) / 24.0 if cad else 0.0))
    return np.isfinite(ages) & (ages <= bound)


def _origins(n_dates: int, lookback: int, horizon: int) -> np.ndarray:
    return np.arange(lookback, n_dates - horizon) if n_dates - horizon > lookback else np.arange(0)


def _solve_first(stats: np.ndarray, k: int) -> float | None:
    """stats = flattened [XtX (k*k), Xty (k), n]; returns beta[0]."""
    xtx = stats[: k * k].reshape(k, k)
    xty = stats[k * k : k * k + k]
    if stats[-1] < k + 5:
        return None
    try:
        beta = np.linalg.solve(xtx, xty)
    except np.linalg.LinAlgError:
        return None
    return float(beta[0])


def _ols_date_stats(
    y: np.ndarray, Xs: list[np.ndarray], valid: np.ndarray, origins: np.ndarray
) -> np.ndarray:
    """Per-origin within-date-demeaned OLS sufficient statistics."""
    k = len(Xs)
    out = np.zeros((len(origins), k * k + k + 1))
    for i, j in enumerate(origins):
        v = valid[:, j]
        n = int(v.sum())
        if n < 3:
            continue
        Z = np.stack([x[v, j] for x in Xs], axis=1)
        yy = y[v, j]
        Z = Z - Z.mean(axis=0)
        yy = yy - yy.mean()
        out[i, : k * k] = (Z.T @ Z).ravel()
        out[i, k * k : k * k + k] = Z.T @ yy
        out[i, -1] = n
    return out


def lead_lag(
    m: Matrix,
    X: Mapping[str, np.ndarray],
    fam: str,
    universe: str,
    horizon: int,
    cfg: Config,
    *,
    exclude_targets: frozenset[str] = frozenset(),
    fresh_only: bool = True,
    origins_mask: np.ndarray | None = None,
) -> dict:
    umask = m.universe == universe
    others = [f for f in families_in(X, umask) if f != fam and f not in exclude_targets]
    if fam not in X or len(others) < 2:
        return {
            "status": "insufficient",
            "reason": f"needs >=2 independent families, have {len(others)}",
        }
    D = len(m.dates)
    origins = _origins(D, cfg.lookback, horizon)
    if origins_mask is not None:
        origins = origins[origins_mask[origins]]
    if fresh_only:
        origins = origins[fresh_dates(m, fam)[origins]]
    if len(origins) == 0:
        return {"status": "insufficient", "reason": "no evaluable origins"}
    rng = np.random.default_rng(cfg.seed + zlib.crc32(fam.encode()) % 10_000)
    xf = np.where(umask[:, None], X[fam], np.nan)
    stats = np.zeros((len(origins), 3 * 3 + 3 + 1))
    for _ in range(cfg.splits):
        perm = list(rng.permutation(others))
        half = (len(perm) + 1) // 2
        ca, _ = consensus(X, perm[:half])
        cb, _ = consensus(X, perm[half:])
        y = shifted(cb, horizon) - cb
        g = xf - ca
        a = ca - cb
        c = cb - shifted(cb, -cfg.lookback)
        valid = np.isfinite(y) & np.isfinite(g) & np.isfinite(a) & np.isfinite(c)
        stats += _ols_date_stats(y, [g, a, c], valid, origins)
    keep = stats[:, -1] > 0
    stats, origins = stats[keep], origins[keep]
    if len(origins) == 0:
        return {"status": "insufficient", "reason": "no evaluable cells"}
    dates = [m.dates[j] for j in origins]
    est = bootstrap(
        stats,
        lambda s: _solve_first(s, 3),
        block_ids(dates, cfg.block_days),
        n_boot=cfg.n_boot,
        seed=cfg.seed,
    )
    return {
        "status": "ok" if est.point is not None else "insufficient",
        "betaGap": est.as_dict(),
        "cells": int(stats[:, -1].sum() / cfg.splits),
        "origins": len(origins),
        "targetFamilies": others,
    }


def stability(
    m: Matrix,
    X: Mapping[str, np.ndarray],
    fam: str,
    universe: str,
    horizon: int,
    cfg: Config,
    *,
    exclude_targets: frozenset[str] = frozenset(),
) -> dict:
    umask = m.universe == universe
    if fam not in X:
        return {"status": "insufficient", "reason": "no data"}
    others = [f for f in families_in(X, umask) if f != fam and f not in exclude_targets]
    D = len(m.dates)
    origins = _origins(D, cfg.lookback, horizon)
    xf = np.where(umask[:, None], X[fam], np.nan)
    d1 = xf - shifted(xf, -cfg.lookback)
    d2 = shifted(xf, horizon) - xf
    moved = np.isfinite(d1) & np.isfinite(d2) & (np.abs(d1) > 1e-9)
    rev = np.zeros((len(origins), 2))
    for i, j in enumerate(origins):
        v = moved[:, j]
        rev[i] = [float((d1[v, j] * d2[v, j]).sum()), float((d1[v, j] ** 2).sum())]
    dates = [m.dates[j] for j in origins]
    blocks = block_ids(dates, cfg.block_days)
    self_rev = bootstrap(
        rev,
        lambda s: (-s[0] / s[1]) if s[1] > 0 else None,
        blocks,
        n_boot=cfg.n_boot,
        seed=cfg.seed,
    )
    out: dict = {
        "status": "ok",
        "selfReversal": self_rev.as_dict(),
        "originsWithAnyMove": int(sum(1 for j in origins if moved[:, j].any())),
        "origins": len(origins),
        "medianAbsMove": round(float(np.median(np.abs(d1[moved]))), 4) if moved.any() else None,
    }
    if len(others) >= 1:
        co, _ = consensus(X, others)
        y = shifted(co, horizon) - co
        cpast = co - shifted(co, -cfg.lookback)
        valid = moved & np.isfinite(y) & np.isfinite(cpast)
        st = _ols_date_stats(y, [d1, cpast], valid, origins)
        out["moveConfirmation"] = bootstrap(
            st, lambda s: _solve_first(s, 2), blocks, n_boot=cfg.n_boot, seed=cfg.seed
        ).as_dict()
        big = valid & (np.abs(d1) >= cfg.abandoned_move)
        sgn = np.sign(d1)
        abandoned = big & (sgn * d2 <= -0.5 * np.abs(d1)) & (sgn * y < 0.5 * np.abs(d1))
        ab = np.array([[abandoned[:, j].sum(), big[:, j].sum()] for j in origins], dtype=float)
        out["abandonedMoveRate"] = bootstrap(
            ab,
            lambda s: (s[0] / s[1]) if s[1] > 0 else None,
            blocks,
            n_boot=cfg.n_boot,
            seed=cfg.seed,
        ).as_dict()
        out["largeMoves"] = int(ab[:, 1].sum())
    return out


def event_response(
    m: Matrix,
    X: Mapping[str, np.ndarray],
    fam: str,
    universe: str,
    cfg: Config,
    *,
    exclude_targets: frozenset[str] = frozenset(),
) -> dict:
    umask = m.universe == universe
    others = [f for f in families_in(X, umask) if f != fam and f not in exclude_targets]
    if fam not in X or len(others) < 2:
        return {
            "status": "insufficient",
            "reason": f"needs >=2 independent families, have {len(others)}",
        }
    co, cnt = consensus(X, others)
    co = np.where(umask[:, None] & (cnt >= cfg.min_consensus_families), co, np.nan)
    w = cfg.event_window_days
    move = co - shifted(co, -w)
    finite = np.abs(move[np.isfinite(move)])
    if finite.size < 50:
        return {"status": "insufficient", "reason": "too few consensus moves"}
    thr = float(np.quantile(finite, cfg.event_quantile))
    D = len(m.dates)
    xf = X[fam]
    cand = np.argwhere(np.isfinite(move) & (np.abs(move) >= thr))
    # one event per asset per 2*follow window: strongest first
    order = sorted(cand.tolist(), key=lambda pj: -abs(move[pj[0], pj[1]]))
    taken: dict[int, list[int]] = {}
    events = []
    for p, j in order:
        if any(abs(j - t) <= cfg.event_follow_days for t in taken.get(p, [])):
            continue
        base = j - 2 * w
        end = j + cfg.event_follow_days
        if base < 0 or end >= D:
            continue
        taken.setdefault(p, []).append(j)
        events.append((p, j, base, end))
    per_date: dict[int, list[float]] = {}
    for p, j, base, end in events:
        if not np.isfinite(xf[p, base]):
            continue
        s = np.sign(move[p, j])
        mag = abs(move[p, j])
        rc = s * (co[p, base : end + 1] - co[p, base]) / mag
        rf = s * (xf[p, base : end + 1] - xf[p, base]) / mag
        tc = next((i for i, v in enumerate(rc) if np.isfinite(v) and v >= 0.5), None)
        if tc is None:
            continue
        tf = next((i for i, v in enumerate(rf) if np.isfinite(v) and v >= 0.5), None)
        row = per_date.setdefault(j, [0.0, 0.0, 0.0])
        row[0] += 1
        if tf is not None:
            row[1] += 1
            row[2] += tc - tf
    if not per_date:
        return {
            "status": "insufficient",
            "reason": "no evaluable events",
            "threshold": round(thr, 4),
        }
    js = sorted(per_date)
    arr = np.array([per_date[j] for j in js])
    blocks = block_ids([m.dates[j] for j in js], cfg.block_days)
    return {
        "status": "ok",
        "threshold": round(thr, 4),
        "events": int(arr[:, 0].sum()),
        "captureRate": bootstrap(
            arr,
            lambda s: s[1] / s[0] if s[0] > 0 else None,
            blocks,
            n_boot=cfg.n_boot,
            seed=cfg.seed,
        ).as_dict(),
        "meanLeadDaysWhenCaptured": bootstrap(
            arr,
            lambda s: s[2] / s[1] if s[1] > 0 else None,
            blocks,
            n_boot=cfg.n_boot,
            seed=cfg.seed,
        ).as_dict(2),
    }


def future_agreement_stats(
    m: Matrix,
    X: Mapping[str, np.ndarray],
    universe: str,
    horizon: int,
    cfg: Config,
    *,
    exclude_targets: frozenset[str] = frozenset(),
    origins: np.ndarray | None = None,
    fresh_only: bool = True,
) -> tuple[dict[str, np.ndarray], np.ndarray]:
    """Per-origin ``[sum relative error, cells]`` per family.

    Relative error on a cell = the family's |score - LFO consensus(T+h)| minus
    the mean of that quantity over every family observed on the same cell, so a
    family is compared with its peers on exactly the players it covers.
    """
    umask = m.universe == universe
    fams = [f for f in families_in(X, umask) if f not in exclude_targets]
    D = len(m.dates)
    if origins is None:
        origins = _origins(D, cfg.lookback, horizon)
    errs = {}
    for f in fams:
        tgt, cnt = consensus(X, [g for g in fams if g != f])
        tgt = np.where(cnt >= cfg.min_consensus_families, shifted(tgt, horizon), np.nan)
        e = np.abs(np.where(umask[:, None], X[f], np.nan) - tgt)
        if fresh_only:
            e = np.where(fresh_dates(m, f)[None, :], e, np.nan)
        errs[f] = e
    if not errs:
        return {}, origins
    stack = np.stack([errs[f] for f in fams])
    with np.errstate(invalid="ignore"):
        cnt = np.isfinite(stack).sum(axis=0)
        mean = np.nansum(stack, axis=0) / np.where(cnt >= 2, cnt, np.nan)
    out = {}
    for i, f in enumerate(fams):
        rel = stack[i] - mean
        ok = np.isfinite(rel)
        out[f] = np.array([[rel[ok[:, j], j].sum(), ok[:, j].sum()] for j in origins], dtype=float)
    return out, origins


def future_agreement(
    m: Matrix,
    X: Mapping[str, np.ndarray],
    universe: str,
    horizon: int,
    cfg: Config,
    **kw,
) -> dict[str, dict]:
    per, origins = future_agreement_stats(m, X, universe, horizon, cfg, **kw)
    out = {}
    for f, st in per.items():
        keep = st[:, 1] > 0
        st = st[keep]
        if not keep.any():
            out[f] = {
                "point": None,
                "se": None,
                "ci90": [None, None],
                "blocks": 0,
                "boot": 0,
                "cells": 0,
            }
            continue
        blocks = block_ids([m.dates[j] for j in origins[keep]], cfg.block_days)
        # score = -(mean relative error): higher = closer to future independent evidence
        est = bootstrap(
            st,
            lambda s: (-s[0] / s[1]) if s[1] > 0 else None,
            blocks,
            n_boot=cfg.n_boot,
            seed=cfg.seed,
        )
        out[f] = {**est.as_dict(), "cells": int(st[:, 1].sum())}
    return out


def fundamental_foresight(
    m: Matrix,
    X: Mapping[str, np.ndarray],
    realized: Mapping[str, float] | None,
    as_of: date,
) -> dict:
    """SECONDARY: Spearman of each family's as-of board with realized outcomes.

    ``realized`` maps asset keys (``name::UNIVERSE``) to an outcome measured
    strictly AFTER ``as_of``.  Not a definition of value.
    """
    if not realized:
        return {
            "status": "INSUFFICIENT_EVIDENCE",
            "missing": "no realized-outcome file supplied (2026 season: <= 4 completed weeks "
            "at evaluation time; nflverse weekly stats are not cached in this checkout)",
        }
    if as_of not in m.dates:
        return {"status": "insufficient", "reason": "as_of outside panel"}
    j = m.dates.index(as_of)
    idx = {a: i for i, a in enumerate(m.assets)}
    out = {}
    for f, arr in X.items():
        pairs = [
            (arr[idx[a], j], v)
            for a, v in realized.items()
            if a in idx and np.isfinite(arr[idx[a], j])
        ]
        if len(pairs) < 30:
            out[f] = {"status": "insufficient", "n": len(pairs)}
            continue
        a, b = np.array(pairs).T
        ra, rb = np.argsort(np.argsort(a)), np.argsort(np.argsort(b))
        out[f] = {
            "status": "ok",
            "n": len(pairs),
            "spearman": round(float(np.corrcoef(ra, rb)[0, 1]), 4),
        }
    return {"status": "ok", "asOf": as_of.isoformat(), "families": out}


def transaction_fit(trades: Sequence[Mapping] | None = None) -> dict:
    """Seam for TRANSACTION FIT (Batch 3 Unit I's completed-trade ledger).

    Not computable on this branch: the ledger (KTC Trade Database archive +
    Sleeper transactions -> canonical identities -> deduplicated underlying-trade
    groups) is being built by Unit I and its dedupe/topology are not validated.
    When it lands, a trade at time T scores each family by how well its as-of-T
    board orders the two sides; the evaluator must consume the ledger's
    deduplicated groups, never raw rows (one trade reported twice is one trade).
    """
    if not trades:
        return {
            "status": "INSUFFICIENT_EVIDENCE",
            "missing": "Unit I completed-trade ledger (deduplicated, topology-validated) not available",
        }
    raise NotImplementedError("transaction fit is wired when Unit I's ledger schema is fixed")


UNIVERSE_BANDS: dict[str, tuple[int, int]] = {OFFENSE: (36, 150), IDP: (24, 100)}
