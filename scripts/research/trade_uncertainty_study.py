#!/usr/bin/env python3
"""Trade Monte Carlo value-uncertainty study (MD-107, research only).

Preregistered plan: docs/valuation/TRADE_UNCERTAINTY_STUDY_PREREG_2026-11-08.md.
This module changes no served behaviour: it imports ``monte_carlo._triangular_draw``
only to realize the incumbent band exactly as the simulator does.

Two stages, so the expensive replay is resumable:

    collect  rebuild the board for each past date (panel replay) -> one gz per date
    analyze  walk-forward evaluation of the candidate uncertainty models

The metric and model functions are pure and importable (see
tests/research/test_trade_uncertainty_metrics.py).  Missing is never zero: an
asset absent at the target date is attrition, a null dispersion makes the
dispersion models UNAVAILABLE for that row.
"""

from __future__ import annotations

import argparse
import gzip
import json
import logging
import math
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Sequence

import numpy as np

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

TAUS = np.round(np.arange(0.05, 0.9501, 0.05), 2)  # 19 levels
HORIZONS = (7, 14, 28)
E_START = date(2026, 6, 15)
LAST_DATE = date(2026, 11, 8)
REFIT_EVERY_DAYS = 14
MIN_TRAIN_DATES = 30
N_FLOOR = 300
N_FLOOR_DATES = 8
STRATUM_MIN_N = 1000
STRATUM_MIN_DATES = 10
DECIDABLE_BLOCKS = 8
INSEASON_START = date(2026, 9, 10)
TIER_EDGES = (1000.0, 2500.0, 5000.0, 7500.0)
BOOT_REPS = 2000
BOOT_SEED = 20261108
MODELS = ("M0", "M1", "M2", "M3", "M4")
IDP_POS = {"DL", "LB", "DB", "CB", "S"}


# --------------------------------------------------------------------------
# Pure metric functions
# --------------------------------------------------------------------------


def pinball_per_row(y: np.ndarray, q: np.ndarray, taus: Sequence[float]) -> np.ndarray:
    """Mean pinball loss over the quantile levels, one value per row.

    ``q`` has shape (n, K) with ``q[:, k]`` the tau_k quantile.
    """
    t = np.asarray(taus, dtype=float)[None, :]
    d = np.asarray(y, dtype=float)[:, None] - np.asarray(q, dtype=float)
    return np.maximum(t * d, (t - 1.0) * d).mean(axis=1)


def _tau_index(taus: Sequence[float], tau: float) -> int:
    arr = np.asarray(taus, dtype=float)
    i = int(np.argmin(np.abs(arr - tau)))
    if not math.isclose(float(arr[i]), tau, abs_tol=1e-9):
        raise ValueError(f"tau {tau} not on the grid")
    return i


def interval_bounds(
    q: np.ndarray, taus: Sequence[float], level: float
) -> tuple[np.ndarray, np.ndarray]:
    """Central ``level`` interval from quantile columns (0.5 -/+ level/2)."""
    lo = _tau_index(taus, round(0.5 - level / 2.0, 10))
    hi = _tau_index(taus, round(0.5 + level / 2.0, 10))
    return q[:, lo], q[:, hi]


def coverage_flags(y: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> np.ndarray:
    return ((y >= lo) & (y <= hi)).astype(float)


def empirical_quantiles(x: np.ndarray, taus: Sequence[float] = TAUS) -> np.ndarray:
    return np.quantile(np.asarray(x, dtype=float), np.asarray(taus, dtype=float), method="linear")


def incumbent_quantiles(taus: Sequence[float] = TAUS, band: float = 0.15) -> np.ndarray:
    """Quantiles of the return the simulator's flat band actually draws.

    p10 = -band, p50 = 0, p90 = +band, with the module's own piecewise-linear
    mapping (including its extrapolated tails).
    """
    from src.trade.monte_carlo import _triangular_draw

    return np.array([_triangular_draw(-band, 0.0, band, float(u)) for u in taus])


def tier_of(v: np.ndarray) -> np.ndarray:
    return np.searchsorted(np.asarray(TIER_EDGES), np.asarray(v, dtype=float), side="right")


def age_bucket(age: float | None, rookie: bool, group: str) -> str:
    if group == "pick":
        return "pick"
    if rookie:
        return "rookie"
    if age is None or not isinstance(age, (int, float)) or not math.isfinite(age):
        return "unknown"
    if age <= 24:
        return "le24"
    if age <= 28:
        return "25_28"
    return "ge29"


def asset_group(position: str, asset_class: str) -> str:
    pos = (position or "").upper()
    if pos == "PICK" or asset_class == "pick":
        return "pick"
    return "idp" if pos in IDP_POS else "offense"


def select_cell(
    levels: Sequence[tuple[Any, ...]],
    table: dict[tuple[Any, ...], dict[str, Any]],
    n_floor: int = N_FLOOR,
    dates_floor: int = N_FLOOR_DATES,
) -> tuple[int, tuple[Any, ...] | None]:
    """First backoff level whose training cell meets BOTH floors.

    ``levels`` is ordered finest to coarsest.  Returns (level_index, cell key);
    (len(levels), None) when nothing qualifies (caller uses the pooled model).
    """
    for i, key in enumerate(levels):
        cell = table.get(key)
        if cell and cell["n"] >= n_floor and cell["dates"] >= dates_floor:
            return i, key
    return len(levels), None


def flag_break_dates(meta: dict[date, dict[str, Any]]) -> dict[date, list[str]]:
    """Mechanical, input-state break rules (plan section 5).

    Never looks at value movement.  ``meta[d]`` carries ``stems`` (sorted
    tuple), ``n_priced`` and ``payload_lag_days``.
    """
    out: dict[date, list[str]] = {}
    prev: dict[str, Any] | None = None
    for d in sorted(meta):
        m = meta[d]
        reasons: list[str] = []
        if prev is not None:
            if tuple(m["stems"]) != tuple(prev["stems"]):
                reasons.append("source_set_changed")
            if (
                prev["n_priced"] > 0
                and abs(m["n_priced"] - prev["n_priced"]) / prev["n_priced"] > 0.10
            ):
                reasons.append("priced_count_jump_gt_10pct")
        if m.get("payload_lag_days") is not None and m["payload_lag_days"] > 3:
            reasons.append("payload_stale_gt_3d")
        if reasons:
            out[d] = reasons
        prev = m
    return out


def pair_is_excluded(origin: date, horizon: int, breaks: set[date]) -> bool:
    """Excluded if origin, target, or any date in (t, t+h] is a break date."""
    return any((origin + timedelta(days=k)) in breaks for k in range(0, horizon + 1))


def block_bootstrap_indices(n: int, block: int, rng: np.random.Generator) -> np.ndarray:
    """Moving-block bootstrap index vector of length n (blocks of ``block``)."""
    block = max(1, min(block, n))
    nb = int(math.ceil(n / block))
    starts = rng.integers(0, n - block + 1, size=nb)
    idx = np.concatenate([np.arange(s, s + block) for s in starts])
    return idx[:n]


def bootstrap_ratio_ci(
    num: np.ndarray, den: np.ndarray, block: int, reps: int = BOOT_REPS, seed: int = BOOT_SEED
) -> tuple[float, float, float]:
    """Point estimate and 95% interval of sum(num)/sum(den) over date rows."""
    num = np.asarray(num, dtype=float)
    den = np.asarray(den, dtype=float)
    n = len(num)
    if n == 0 or den.sum() == 0:
        return float("nan"), float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    est = num.sum() / den.sum()
    vals = np.empty(reps)
    for r in range(reps):
        idx = block_bootstrap_indices(n, block, rng)
        d = den[idx].sum()
        vals[r] = num[idx].sum() / d if d else np.nan
    lo, hi = np.nanpercentile(vals, [2.5, 97.5])
    return float(est), float(lo), float(hi)


def bootstrap_diff_ci(
    num_a: np.ndarray,
    num_b: np.ndarray,
    den: np.ndarray,
    block: int,
    reps: int = BOOT_REPS,
    seed: int = BOOT_SEED,
) -> tuple[float, float, float]:
    """Paired date-block bootstrap of (sum(num_a)-sum(num_b))/sum(den)."""
    num_a, num_b, den = (np.asarray(x, dtype=float) for x in (num_a, num_b, den))
    n = len(den)
    if n == 0 or den.sum() == 0:
        return float("nan"), float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    est = (num_a.sum() - num_b.sum()) / den.sum()
    vals = np.empty(reps)
    for r in range(reps):
        idx = block_bootstrap_indices(n, block, rng)
        d = den[idx].sum()
        vals[r] = (num_a[idx].sum() - num_b[idx].sum()) / d if d else np.nan
    lo, hi = np.nanpercentile(vals, [2.5, 97.5])
    return float(est), float(lo), float(hi)


# --------------------------------------------------------------------------
# Model fitting / prediction (pure; numpy arrays in, quantile matrices out)
# --------------------------------------------------------------------------


def fit_pooled(r: np.ndarray) -> np.ndarray:
    return empirical_quantiles(r)


def fit_m1(r: np.ndarray, cv: np.ndarray) -> np.ndarray | None:
    ok = np.isfinite(cv) & (cv > 0)
    if ok.sum() < N_FLOOR:
        return None
    return empirical_quantiles(r[ok] / cv[ok])


def predict_m1(qz: np.ndarray, cv: np.ndarray) -> np.ndarray:
    return cv[:, None] * qz[None, :]


def fit_m3(r: np.ndarray, cv: np.ndarray, h: np.ndarray) -> tuple[float, float, np.ndarray] | None:
    """r^2 ~ a*cv^2 + b*h (non-negative), then empirical quantiles of r/sigma."""
    from scipy.optimize import nnls

    ok = np.isfinite(cv) & (cv > 0)
    if ok.sum() < N_FLOOR:
        return None
    X = np.column_stack([cv[ok] ** 2, h[ok].astype(float)])
    (a, b), _ = nnls(X, r[ok] ** 2)
    sig = np.sqrt(a * cv[ok] ** 2 + b * h[ok])
    if not np.all(sig > 0):
        return None
    return float(a), float(b), empirical_quantiles(r[ok] / sig)


def predict_m3(a: float, b: float, qz: np.ndarray, cv: np.ndarray, h: int) -> np.ndarray:
    sig = np.sqrt(a * cv**2 + b * h)
    return sig[:, None] * qz[None, :]


# --------------------------------------------------------------------------
# Collection (panel replay)
# --------------------------------------------------------------------------


def collect_day(d: date, cache_dir: Path) -> dict[str, Any]:
    out = cache_dir / f"{d.isoformat()}.json.gz"
    if out.exists():
        return {"date": d.isoformat(), "cached": True}
    from src.api.data_contract import build_api_data_contract
    from src.consensus_edge import panel

    with panel.panel_day(d) as day:
        contract = build_api_data_contract(day.payload, csv_root=day.csv_root)
        stems = list(day.csv_sources)
        payload_date = str(day.payload.get("date") or "")
    rows: list[list[Any]] = []
    for row in contract.get("playersArray") or []:
        v = row.get("rankDerivedValue")
        if not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0:
            continue
        pid = row.get("playerId")
        key = (
            str(pid)
            if pid
            else f"{row.get('canonicalName') or row.get('displayName')}::{row.get('assetClass')}"
        )
        cv = row.get("marketDispersionCV")
        cv = float(cv) if isinstance(cv, (int, float)) and math.isfinite(cv) else None
        age = row.get("age")
        age = float(age) if isinstance(age, (int, float)) else None
        rows.append(
            [
                key,
                round(float(v), 3),
                str(row.get("position") or ""),
                str(row.get("assetClass") or ""),
                age,
                bool(row.get("rookie")),
                cv,
                int(row.get("sourceCount") or 0),
            ]
        )
    lag = None
    try:
        lag = (d - datetime.strptime(payload_date, "%Y-%m-%d").date()).days
    except ValueError:
        pass
    blob = {
        "date": d.isoformat(),
        "stems": stems,
        "payloadDate": payload_date,
        "payloadLagDays": lag,
        "rows": rows,
    }
    with gzip.open(out, "wt", encoding="utf-8") as fh:
        json.dump(blob, fh, separators=(",", ":"))
    return {"date": d.isoformat(), "cached": False, "rows": len(rows)}


def cmd_collect(args: argparse.Namespace) -> int:
    logging.disable(logging.WARNING)
    from src.consensus_edge import panel

    panel._assert_deep()  # noqa: SLF001
    days = [d for d in panel.available_dates() if d <= LAST_DATE]
    cache = Path(args.cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    i, n = (int(x) for x in args.shard.split("/"))
    mine = [d for k, d in enumerate(days) if k % n == i]
    for d in mine:
        try:
            res = collect_day(d, cache)
        except Exception as exc:  # noqa: BLE001
            print(f"[collect] {d} FAILED: {exc}", file=sys.stderr)
            continue
        print(f"[collect] {res}", file=sys.stderr, flush=True)
    return 0


# --------------------------------------------------------------------------
# Loading and pair construction
# --------------------------------------------------------------------------


def load_cache(cache_dir: Path) -> tuple[dict[date, dict[str, Any]], dict[date, dict[str, Any]]]:
    """Return (meta, data) by date; data[d] has aligned numpy columns."""
    meta: dict[date, dict[str, Any]] = {}
    data: dict[date, dict[str, Any]] = {}
    for f in sorted(Path(cache_dir).glob("*.json.gz")):
        with gzip.open(f, "rt", encoding="utf-8") as fh:
            b = json.load(fh)
        d = date.fromisoformat(b["date"])
        rows = b["rows"]
        meta[d] = {
            "stems": tuple(sorted(b["stems"])),
            "n_priced": len(rows),
            "payload_lag_days": b.get("payloadLagDays"),
            "payload_date": b.get("payloadDate"),
        }
        data[d] = {
            "key": np.array([r[0] for r in rows]),
            "v": np.array([r[1] for r in rows], dtype=float),
            "pos": np.array([r[2] for r in rows]),
            "cls": np.array([r[3] for r in rows]),
            "age": np.array([np.nan if r[4] is None else r[4] for r in rows], dtype=float),
            "rookie": np.array([r[5] for r in rows], dtype=bool),
            "cv": np.array([np.nan if r[6] is None else r[6] for r in rows], dtype=float),
        }
    return meta, data


def build_pairs(
    data: dict[date, dict[str, Any]], origin: date, h: int
) -> dict[str, np.ndarray] | None:
    t1 = origin + timedelta(days=h)
    if origin not in data or t1 not in data:
        return None
    a, b = data[origin], data[t1]
    # keys are unique per date by construction of the contract; guard anyway
    _, ia = np.unique(a["key"], return_index=True)
    _, ib = np.unique(b["key"], return_index=True)
    ka, kb = a["key"][ia], b["key"][ib]
    common, ca, cb = np.intersect1d(ka, kb, return_indices=True)
    if len(common) == 0:
        return None
    sa, sb = ia[ca], ib[cb]
    v0, v1 = a["v"][sa], b["v"][sb]
    pos, cls = a["pos"][sa], a["cls"][sa]
    group = np.array([asset_group(p, c) for p, c in zip(pos, cls)])
    ab = np.array(
        [
            age_bucket(None if np.isnan(x) else x, bool(rk), g)
            for x, rk, g in zip(a["age"][sa], a["rookie"][sa], group)
        ]
    )
    return {
        "key": common,
        "v0": v0,
        "r": v1 / v0 - 1.0,
        "group": group,
        "pos": pos,
        "age_b": ab,
        "tier": tier_of(v0),
        "cv": a["cv"][sa],
        "n_origin": np.array([len(ka)]),
        "n_target": np.array([len(kb)]),
    }


def attrition_stats(
    data: dict[date, dict[str, Any]], origin: date, h: int
) -> dict[str, int] | None:
    t1 = origin + timedelta(days=h)
    if origin not in data or t1 not in data:
        return None
    ka, kb = set(data[origin]["key"].tolist()), set(data[t1]["key"].tolist())
    return {"origin": len(ka), "matched": len(ka & kb), "lostAtTarget": len(ka - kb)}


# --------------------------------------------------------------------------
# Walk-forward evaluation
# --------------------------------------------------------------------------


def _cell_levels(group: str, pos: str, tier: int, ageb: str) -> list[tuple[Any, ...]]:
    return [
        ("g", group, pos, tier, ageb),
        ("gpt", group, pos, tier),
        ("gt", group, tier),
        ("g", group),
    ]


class TrainStore:
    """Pairs accumulated by (origin date, horizon), queried by cutoff."""

    def __init__(self) -> None:
        self.items: list[tuple[date, int, dict[str, np.ndarray]]] = []

    def add(self, origin: date, h: int, p: dict[str, np.ndarray]) -> None:
        self.items.append((origin, h, p))

    def training(self, cutoff: date, h: int | None = None) -> dict[str, np.ndarray]:
        """Pairs whose TARGET date (o + h) is on or before ``cutoff``."""
        parts = [
            (o, hh, p)
            for (o, hh, p) in self.items
            if o + timedelta(days=hh) <= cutoff and (h is None or hh == h)
        ]
        if not parts:
            return {}
        cols = {
            k: np.concatenate([p[k] for (_, _, p) in parts])
            for k in ("r", "group", "pos", "age_b", "tier", "cv")
        }
        cols["h"] = np.concatenate([np.full(len(p["r"]), hh) for (_, hh, p) in parts])
        cols["odate"] = np.concatenate([np.full(len(p["r"]), o.toordinal()) for (o, _, p) in parts])
        cols["n_dates"] = np.array([len({o for (o, _, _) in parts})])
        return cols


def fit_models(train_h: dict[str, np.ndarray], train_all: dict[str, np.ndarray]) -> dict[str, Any]:
    models: dict[str, Any] = {"M0": incumbent_quantiles()}
    r = train_h["r"]
    models["M4"] = fit_pooled(r)
    models["M1"] = fit_m1(r, train_h["cv"])
    models["M3"] = fit_m3(train_all["r"], train_all["cv"], train_all["h"])
    # M2 cell table
    table: dict[tuple[Any, ...], dict[str, Any]] = {}
    keyset: dict[tuple[Any, ...], list[int]] = {}
    g, ps, tr, ab, od = (train_h[k] for k in ("group", "pos", "tier", "age_b", "odate"))
    for i in range(len(r)):
        for lv in _cell_levels(str(g[i]), str(ps[i]), int(tr[i]), str(ab[i])):
            keyset.setdefault(lv, []).append(i)
    for lv, idx in keyset.items():
        idx_a = np.asarray(idx)
        table[lv] = {"n": len(idx_a), "dates": len(np.unique(od[idx_a])), "idx": idx_a}
    models["M2_table"] = table
    models["M2_r"] = r
    models["M2_cache"] = {}
    return models


def predict_m2(models: dict[str, Any], p: dict[str, np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    """Per-row M2 quantiles with backoff; returns (Q, level_index)."""
    table, r, cache = models["M2_table"], models["M2_r"], models["M2_cache"]
    n = len(p["r"])
    Q = np.empty((n, len(TAUS)))
    lvl = np.empty(n, dtype=int)
    for i in range(n):
        levels = _cell_levels(
            str(p["group"][i]), str(p["pos"][i]), int(p["tier"][i]), str(p["age_b"][i])
        )
        li, key = select_cell(levels, table)
        lvl[i] = li
        if key is None:
            qv = models["M4"]
        else:
            if key not in cache:
                cache[key] = empirical_quantiles(r[table[key]["idx"]])
            qv = cache[key]
        Q[i] = qv
    return Q, lvl


def evaluate_origin(models: dict[str, Any], p: dict[str, np.ndarray], h: int) -> dict[str, Any]:
    """Quantile predictions for one origin/horizon pair set."""
    n = len(p["r"])
    cv = p["cv"]
    cv_ok = np.isfinite(cv) & (cv > 0)
    out: dict[str, Any] = {"cv_ok": cv_ok}
    out["M0"] = np.broadcast_to(models["M0"], (n, len(TAUS)))
    out["M4"] = np.broadcast_to(models["M4"], (n, len(TAUS)))
    out["M2"], out["M2_level"] = predict_m2(models, p)
    out["M1"] = None
    out["M3"] = None
    if models["M1"] is not None:
        q = np.full((n, len(TAUS)), np.nan)
        q[cv_ok] = predict_m1(models["M1"], cv[cv_ok])
        out["M1"] = q
    if models["M3"] is not None:
        a, b, qz = models["M3"]
        q = np.full((n, len(TAUS)), np.nan)
        q[cv_ok] = predict_m3(a, b, qz, cv[cv_ok], h)
        out["M3"] = q
    return out


def run_eval(
    data: dict[date, dict[str, Any]],
    meta: dict[date, dict[str, Any]],
    *,
    horizons: Sequence[int] = HORIZONS,
    exclude: bool = True,
    log: Any = None,
) -> dict[str, Any]:
    dates = sorted(data)
    breaks_info = flag_break_dates(meta)
    breaks = set(breaks_info) if exclude else set()

    store = TrainStore()
    pair_cache: dict[tuple[date, int], dict[str, np.ndarray] | None] = {}
    for d in dates:
        for h in horizons:
            p = build_pairs(data, d, h)
            pair_cache[(d, h)] = p
            if p is not None and not pair_is_excluded(d, h, breaks):
                store.add(d, h, p)

    # per (model, h, subset) accumulators: per-date rows of sums
    acc: dict[tuple[str, int, str], dict[date, np.ndarray]] = {}
    # strata accumulators (point): key -> [n, cov50, cov80, dates set]
    strata: dict[tuple[str, int, str, str], list[Any]] = {}
    phase: dict[tuple[str, int, str], list[float]] = {}
    m2_levels: dict[int, np.ndarray] = {}
    refit_log: list[dict[str, Any]] = []
    attr: dict[int, dict[str, int]] = {
        h: {"origin": 0, "matched": 0, "lostAtTarget": 0} for h in horizons
    }
    skipped_blocks = 0
    inc = incumbent_quantiles()
    i50 = (_tau_index(TAUS, 0.25), _tau_index(TAUS, 0.75))

    last_origin_for = {h: LAST_DATE - timedelta(days=h) for h in horizons}
    refit = E_START
    while refit <= LAST_DATE:
        block_end = refit + timedelta(days=REFIT_EVERY_DAYS)
        train_all = store.training(refit)
        ndates = int(train_all["n_dates"][0]) if train_all else 0
        if ndates < MIN_TRAIN_DATES:
            skipped_blocks += 1
            refit_log.append({"refit": refit.isoformat(), "skipped": True, "trainDates": ndates})
            refit = block_end
            continue
        for h in horizons:
            train_h = store.training(refit, h)
            if not train_h or len(train_h["r"]) < N_FLOOR:
                continue
            models = fit_models(train_h, train_all)
            m3 = models["M3"]
            refit_log.append(
                {
                    "refit": refit.isoformat(),
                    "h": h,
                    "trainPairs": int(len(train_h["r"])),
                    "trainDates": ndates,
                    "m3": None if m3 is None else {"a": round(m3[0], 5), "b": round(m3[1], 6)},
                    "m4Q10Q90": [
                        round(float(models["M4"][1]), 4),
                        round(float(models["M4"][-2]), 4),
                    ],
                }
            )
            d = refit
            while d < block_end and d <= last_origin_for[h]:
                p = pair_cache.get((d, h))
                if p is not None and not pair_is_excluded(d, h, breaks):
                    at = attrition_stats(data, d, h)
                    for k in attr[h]:
                        attr[h][k] += at[k]
                    ev = evaluate_origin(models, p, h)
                    y = p["r"]
                    m2_levels.setdefault(h, np.zeros(5, dtype=int))
                    m2_levels[h] += np.bincount(ev["M2_level"], minlength=5)[:5]
                    for m in MODELS:
                        q = ev[m]
                        if q is None:
                            continue
                        for subset, mask in (
                            ("cv", ev["cv_ok"]),
                            ("all", np.ones(len(y), dtype=bool)),
                        ):
                            if subset == "all" and m in ("M1", "M3"):
                                continue
                            if mask.sum() == 0:
                                continue
                            yy, qq = y[mask], q[mask]
                            lo50, hi50 = qq[:, i50[0]], qq[:, i50[1]]
                            lo80, hi80 = interval_bounds(qq, TAUS, 0.8)
                            c50, c80 = (
                                coverage_flags(yy, lo50, hi50),
                                coverage_flags(yy, lo80, hi80),
                            )
                            pb = pinball_per_row(yy, qq, TAUS)
                            vec = np.array(
                                [
                                    len(yy),
                                    c50.sum(),
                                    c80.sum(),
                                    (hi50 - lo50).sum(),
                                    (hi80 - lo80).sum(),
                                    pb.sum(),
                                ]
                            )
                            acc.setdefault((m, h, subset), {})[d] = vec
                            if subset == "cv" or m in ("M0", "M2", "M4"):
                                ph = "in" if d >= INSEASON_START else "pre"
                                pk = phase.setdefault((m, h, f"{subset}:{ph}"), [0.0, 0.0])
                                pk[0] += len(yy)
                                pk[1] += c80.sum()
                            if subset == "cv":
                                g, ps, tr = p["group"][mask], p["pos"][mask], p["tier"][mask]
                                for dim, col in (("group", g), ("position", ps), ("tier", tr)):
                                    for val in np.unique(col):
                                        sel = col == val
                                        rec = strata.setdefault(
                                            (m, h, dim, str(val)), [0, 0.0, 0.0, set()]
                                        )
                                        rec[0] += int(sel.sum())
                                        rec[1] += float(c50[sel].sum())
                                        rec[2] += float(c80[sel].sum())
                                        rec[3].add(d.toordinal())
                d += timedelta(days=1)
        refit = block_end
    return {
        "acc": acc,
        "strata": strata,
        "phase": phase,
        "m2_levels": m2_levels,
        "refit_log": refit_log,
        "attrition": attr,
        "skippedBlocks": skipped_blocks,
        "breaks": {k.isoformat(): v for k, v in sorted(breaks_info.items())},
        "excludeApplied": exclude,
        "incumbentQ": inc,
    }


def summarize(res: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"byHorizon": {}}
    acc = res["acc"]
    for h in HORIZONS:
        hs: dict[str, Any] = {"models": {}}
        # primary: 'cv' intersection
        dates0 = sorted(acc.get(("M0", h, "cv"), {}))
        if not dates0:
            out["byHorizon"][str(h)] = {"note": "no evaluation origins"}
            continue
        span_days = (dates0[-1] - dates0[0]).days + 1
        hs["evalOrigins"] = len(dates0)
        hs["evalSpan"] = [dates0[0].isoformat(), dates0[-1].isoformat()]
        hs["disjointBlocks"] = span_days // h
        hs["decidable"] = (span_days // h) >= DECIDABLE_BLOCKS
        for m in MODELS:
            for subset in ("cv", "all"):
                key = (m, h, subset)
                if key not in acc:
                    continue
                dd = sorted(acc[key])
                M = np.array([acc[key][d] for d in dd])
                n = M[:, 0]
                e80 = bootstrap_ratio_ci(M[:, 2], n, h)
                e50 = bootstrap_ratio_ci(M[:, 1], n, h)
                pb = bootstrap_ratio_ci(M[:, 5], n, h)
                ent: dict[str, Any] = {
                    "pairs": int(n.sum()),
                    "origins": len(dd),
                    "cov50": _r(e50),
                    "cov80": _r(e80),
                    "meanWidth50": round(float(M[:, 3].sum() / n.sum()), 5),
                    "meanWidth80": round(float(M[:, 4].sum() / n.sum()), 5),
                    "pinball": _r(pb),
                    "crpsApprox": round(2 * pb[0], 6),
                }
                # disjoint-origin sensitivity
                sel = [i for i, d in enumerate(dd) if (d - dd[0]).days % h == 0]
                if sel:
                    Ms = M[sel]
                    ent["disjointOrigins"] = {
                        "origins": len(sel),
                        "cov80": round(float(Ms[:, 2].sum() / Ms[:, 0].sum()), 4),
                        "pinball": round(float(Ms[:, 5].sum() / Ms[:, 0].sum()), 6),
                    }
                hs["models"].setdefault(m, {})[subset] = ent
        # paired pinball difference vs M0 and M4 on cv subset
        k0 = ("M0", h, "cv")
        for m in ("M1", "M2", "M3", "M4"):
            km = (m, h, "cv")
            if km not in acc:
                continue
            dd = sorted(set(acc[km]) & set(acc[k0]))
            A = np.array([acc[km][d] for d in dd])
            B = np.array([acc[k0][d] for d in dd])
            hs["models"][m]["pinballMinusM0"] = _r(bootstrap_diff_ci(A[:, 5], B[:, 5], A[:, 0], h))
            k4 = ("M4", h, "cv")
            if m != "M4" and k4 in acc:
                dd4 = sorted(set(acc[km]) & set(acc[k4]))
                A4 = np.array([acc[km][d] for d in dd4])
                C4 = np.array([acc[k4][d] for d in dd4])
                hs["models"][m]["pinballMinusM4"] = _r(
                    bootstrap_diff_ci(A4[:, 5], C4[:, 5], A4[:, 0], h)
                )
        # strata
        st: dict[str, Any] = {}
        for (m, hh, dim, val), (n, c50, c80, ds) in res["strata"].items():
            if hh != h:
                continue
            ok = n >= STRATUM_MIN_N and len(ds) >= STRATUM_MIN_DATES
            st.setdefault(m, {}).setdefault(dim, {})[val] = (
                {"n": n, "dates": len(ds), "cov50": round(c50 / n, 4), "cov80": round(c80 / n, 4)}
                if ok
                else {"n": n, "dates": len(ds), "status": "below_floor"}
            )
        hs["strata"] = st
        hs["phase"] = {
            f"{m}|{k.split(':', 1)[1]}": round(v[1] / v[0], 4)
            for (m, hh, k), v in res["phase"].items()
            if hh == h and k.startswith("cv:") and v[0] > 0
        }
        if h in res["m2_levels"]:
            tot = res["m2_levels"][h].sum()
            hs["m2BackoffShare"] = {
                n_: round(float(c) / float(tot), 4)
                for n_, c in zip(
                    ["g_pos_tier_age", "g_pos_tier", "g_tier", "g", "pooled"], res["m2_levels"][h]
                )
            }
        hs["attrition"] = res["attrition"][h]
        out["byHorizon"][str(h)] = hs
    return out


def _r(t: tuple[float, float, float]) -> dict[str, float]:
    return {"est": round(t[0], 5), "lo95": round(t[1], 5), "hi95": round(t[2], 5)}


def apply_decision_rule(summary: dict[str, Any]) -> dict[str, Any]:
    """Section 7 of the preregistration, mechanically."""
    verdict: dict[str, Any] = {"byHorizon": {}}
    decidable = []
    for hk, hs in summary["byHorizon"].items():
        if "models" not in hs:
            continue
        if hs["decidable"]:
            decidable.append(int(hk))
        res_h: dict[str, Any] = {"decidable": hs["decidable"], "models": {}}
        for m in ("M1", "M2", "M3", "M4"):
            ms = hs["models"].get(m, {}).get("cv")
            if not ms:
                continue
            c: dict[str, bool] = {}
            c["1_point_coverage"] = (
                0.75 <= ms["cov80"]["est"] <= 0.85 and 0.45 <= ms["cov50"]["est"] <= 0.55
            )
            c["2_ci_inside_70_90"] = ms["cov80"]["lo95"] >= 0.70 and ms["cov80"]["hi95"] <= 0.90
            d0 = hs["models"][m].get("pinballMinusM0")
            c["3_beats_m0"] = bool(d0 and d0["hi95"] < 0)
            d4 = hs["models"][m].get("pinballMinusM4")
            c["4_not_worse_than_m4"] = True if m == "M4" or d4 is None else bool(d4["lo95"] <= 0)
            bad = []
            for dim in ("position", "tier", "group"):
                for val, s in hs["strata"].get(m, {}).get(dim, {}).items():
                    if "cov80" in s and not (0.70 <= s["cov80"] <= 0.90):
                        bad.append(f"{dim}={val}:{s['cov80']}")
            c["5_strata_in_70_90"] = not bad
            c["6_phases_in_70_90"] = all(
                0.70 <= v <= 0.90 for k, v in hs["phase"].items() if k.startswith(m + "|")
            ) and any(k.startswith(m + "|") for k in hs["phase"])
            res_h["models"][m] = {"criteria": c, "passes": all(c.values()), "strataOutside": bad}
        verdict["byHorizon"][hk] = res_h
    passers = [
        m
        for m in ("M1", "M2", "M3")
        if decidable
        and all(verdict["byHorizon"][str(h)]["models"].get(m, {}).get("passes") for h in decidable)
    ]
    verdict["decidableHorizons"] = decidable
    verdict["modelsPassingAllDecidable"] = passers
    if len(decidable) < 2 or not {7, 14} <= set(decidable):
        verdict["verdict"] = "(c) inconclusive: fewer than the required decidable horizons"
    elif passers:
        verdict["verdict"] = "(a) credible candidate: " + ",".join(passers)
    else:
        verdict["verdict"] = "(b) none credible"
    return verdict


# --------------------------------------------------------------------------
# Q2: verdict persistence (descriptive)
# --------------------------------------------------------------------------

GAP_BINS = (0.02, 0.05, 0.10, 0.20)


def gap_bin(rel: np.ndarray) -> np.ndarray:
    return np.searchsorted(np.asarray(GAP_BINS), rel, side="right")


def sign_persists(gap0: np.ndarray, gap1: np.ndarray) -> np.ndarray:
    return (gap0 * gap1) > 0


def verdict_persistence(
    data: dict[date, dict[str, Any]], meta: dict[date, dict[str, Any]], seed: int = BOOT_SEED
) -> dict[str, Any]:
    breaks = set(flag_break_dates(meta))
    rng = np.random.default_rng(seed)
    out: dict[str, Any] = {}
    cand_per_origin, cap_per_bin = 40000, 1000
    for h in HORIZONS:
        per_date: list[np.ndarray] = []  # (date, shape, bin) -> [persist, total]
        for d in sorted(data):
            if not (E_START <= d <= LAST_DATE - timedelta(days=h)) or pair_is_excluded(
                d, h, breaks
            ):
                continue
            p = build_pairs(data, d, h)
            if p is None or len(p["r"]) < 50:
                continue
            v0 = p["v0"]
            v1 = v0 * (1.0 + p["r"])
            n = len(v0)
            mat = np.zeros((3, len(GAP_BINS) + 1, 2))
            for si, (na, nb) in enumerate(((1, 1), (2, 1), (2, 2))):
                need = na + nb
                if n < need:
                    continue
                idx = np.stack([rng.permutation(n)[:need] for _ in range(cand_per_origin // 8)])
                A = idx[:, :na]
                B = idx[:, na:]
                g0 = v0[A].sum(axis=1) - v0[B].sum(axis=1)
                g1 = v1[A].sum(axis=1) - v1[B].sum(axis=1)
                rel = np.abs(g0) / np.maximum(v0[A].sum(axis=1), v0[B].sum(axis=1))
                bn = gap_bin(rel)
                per = sign_persists(g0, g1)
                for b in range(len(GAP_BINS) + 1):
                    sel = np.where(bn == b)[0][:cap_per_bin]
                    mat[si, b, 0] = per[sel].sum()
                    mat[si, b, 1] = len(sel)
            per_date.append(mat)
        if not per_date:
            continue
        M = np.stack(per_date)
        res_h: dict[str, Any] = {"origins": len(per_date), "byShape": {}}
        for si, name in enumerate(("1v1", "2v1", "2v2")):
            bins = {}
            for b in range(len(GAP_BINS) + 1):
                lab = ["0-2%", "2-5%", "5-10%", "10-20%", "20%+"][b]
                est = bootstrap_ratio_ci(M[:, si, b, 0], M[:, si, b, 1], h, reps=500, seed=seed + b)
                bins[lab] = {"trades": int(M[:, si, b, 1].sum()), **_r(est)}
            res_h["byShape"][name] = bins
        out[str(h)] = res_h
    return out


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def cmd_analyze(args: argparse.Namespace) -> int:
    meta, data = load_cache(Path(args.cache_dir))
    dates = sorted(data)
    if not dates:
        print("empty cache", file=sys.stderr)
        return 2
    primary = run_eval(data, meta, exclude=True)
    summary = summarize(primary)
    verdict = apply_decision_rule(summary)
    sens = run_eval(data, meta, exclude=False)
    sens_summary = summarize(sens)
    q2 = verdict_persistence(data, meta)
    result = {
        "study": "trade-monte-carlo-value-uncertainty",
        "prereg": "docs/valuation/TRADE_UNCERTAINTY_STUDY_PREREG_2026-11-08.md",
        "dataDates": [dates[0].isoformat(), dates[-1].isoformat()],
        "dataDateCount": len(dates),
        "evalStart": E_START.isoformat(),
        "lastDate": LAST_DATE.isoformat(),
        "breakDates": primary["breaks"],
        "refitLog": primary["refit_log"],
        "skippedBlocks": primary["skippedBlocks"],
        "incumbentQuantiles": [round(float(x), 5) for x in primary["incumbentQ"]],
        "taus": [float(t) for t in TAUS],
        "primary": summary,
        "decisionRule": verdict,
        "sensitivityNoExclusions": sens_summary,
        # Added after the primary outcomes were seen (labelled DEVIATION in the report):
        # the same mechanical rule applied to the no-exclusion run, informational only.
        "sensitivityDecisionRule": apply_decision_rule(sens_summary),
        "verdictPersistence": q2,
        "caveats": [
            "replay_pipeline_is_current: movement is input-driven only; understates as-served movement",
            "replay runs without scrape_state: freshness/health weighting off, constant across dates",
            "measures board self-consistency, not common-mode error",
            "value uncertainty only: says nothing about fairness-verdict uncertainty beyond Q2 descriptive, and nothing about acceptance",
        ],
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1, default=str) + "\n", encoding="utf-8")
    print(f"wrote {out}\n{verdict['verdict']}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect")
    c.add_argument("--cache-dir", required=True)
    c.add_argument("--shard", default="0/1")
    c.set_defaults(fn=cmd_collect)
    a = sub.add_parser("analyze")
    a.add_argument("--cache-dir", required=True)
    a.add_argument("--out", required=True)
    a.set_defaults(fn=cmd_analyze)
    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
