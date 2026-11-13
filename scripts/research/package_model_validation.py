#!/usr/bin/env python3
"""Package model q and fairness bands: out-of-sample validation (Priority 16, research only).

Preregistered plan, committed before this script:
``docs/valuation/evidence/package_model_validation_2026-11-13/PREREGISTRATION.md``.
Result record: ``docs/valuation/PACKAGE_MODEL_VALIDATION_2026-11-13.md``.

Nothing here changes ``geom_q078_v1`` (q = 0.78), ``fairness_bands_v2``,
``config/trade/``, a flag or served code.  Utilities come from the package-model
owner (``package_model.geom_utility``) and every band label from the band owner
(``fairness_bands.fairness_base`` + ``fairness_bands.classify``); trade
eligibility, topology and point-in-time values from the market-trade ledger
owners (``market_trade_eval``).  No legacy research module is loaded.

Data sources (the preregistration's labels):

    --box                 D-BOX: the canonical ledger on this host, under the
                          read-only guard; aggregates to stdout, nothing written
    --ledger PATH         D-EXPORT: an exported byte copy of
                          ``data/market_trades/underlying_trades.sqlite``,
                          opened read-only
    --rows PATH           priced rows (JSONL, schema below), e.g. written by
                          ``--write-rows`` on an earlier run
    --own-league [PATH]   D-OWN: the tracked ``dynasty_main`` snapshot
                          (``data/sleeper_last_good.json``); one league, not decisive
    --power               D-SYN: synthetic power analysis (never market evidence)

Priced-row schema (one JSON object per line)::

    {"date": "2026-09-01", "cluster": "<opaque league key or null>",
     "sides": [[{"v": 5625.0, "kind": "pick", "pos": null}, ...], [...]],
     "targetPriceAuthority": 1, "source": "ktc_trade_database"}

``cluster`` is a salted hash of the host league id, never the id itself.

Missing is never zero: a trade with any asset the point-in-time board cannot
price is excluded and counted.  Output is aggregate-only and is checked for
identifiers before it is printed or written.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import re
import sqlite3
import subprocess
import sys
import zipfile
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

REPO = Path(os.environ.get("RISKIT_APP_DIR") or Path(__file__).resolve().parents[2]).resolve()
SCRIPT_DIR = Path(__file__).resolve().parent

# numpy is third-party (no application code) and is imported before the guard:
# CPython's ctypes import performs a dlopen the guard refuses.
import numpy as np  # noqa: E402

GUARD = None
if "--box" in sys.argv:
    sys.dont_write_bytecode = True
    for _cand in (
        SCRIPT_DIR / "research_readonly_guard.py",
        SCRIPT_DIR.parent / "research_readonly_guard.py",
    ):
        if _cand.exists():
            _gspec = importlib.util.spec_from_file_location("research_readonly_guard", _cand)
            GUARD = importlib.util.module_from_spec(_gspec)
            sys.modules["research_readonly_guard"] = GUARD
            _gspec.loader.exec_module(GUARD)
            GUARD.install()
            break
    else:  # pragma: no cover - box wiring
        raise SystemExit("--box needs research_readonly_guard.py beside this script")

if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.valuation_math import fairness_bands, package_model  # noqa: E402

# ── Frozen protocol constants (PREREGISTRATION.md) ─────────────────────────

PREREGISTRATION = "docs/valuation/evidence/package_model_validation_2026-11-13/PREREGISTRATION.md"
Q_INCUMBENT = float(package_model.PACKAGE_MODELS[package_model.GEOM_Q078_V1]["q"])
Q_GRID: tuple[float, ...] = tuple(round(0.30 + 0.01 * i, 2) for i in range(71))  # 0.30 .. 1.00
LEVEL_C = 2000.0  # Phase 3's fixed per-piece level, a diagnostic only (never refit here)
K_BLOCKS = 5
MAX_LAG_DAYS = 7
SINCE_DATE = "2026-07-01"
BOOT_REPS = 1000
QHAT_BOOT_REPS = 300
SEED = 20261113
R0_MIN_UNEQUAL = 2000
R0_MIN_LEAGUES = 200
R0_MIN_FOLD_UNEQUAL = 200
R2_SHAPE_ONLY_BELOW = 0.70
R2_LEVEL_RANGE = (0.70, 0.90)
R3_EXCESS_PP = 10.0
TARGET_AUTHORITY_MIN_UNEQUAL = 500
CLUSTER_SALT = "pkg-validation-2026-11-13"

SHAPES = ("1v1", "1v2", "2v1", "2v2", "3+")
P3_BINS = ("1vN_small", "ordinary", "deep", "equal")
CLASSES = ("offense_players_only", "includes_idp", "includes_picks_no_idp")
TIER_EDGES = (2000.0, 4000.0, 6000.0, 8000.0)
TIERS = ("<2000", "2000-3999", "4000-5999", "6000-7999", "8000+")
IDP_POSITIONS = frozenset(
    {"DL", "LB", "DB", "DE", "DT", "EDGE", "CB", "S", "SS", "FS", "ILB", "OLB", "IDP"}
)
MODELS = ("M078", "MFIT", "M100", "MMOM")
LEVELS = fairness_bands.LEVELS
NOT_FAIR = ("slight", "unfair", "lopsided")


# ── Pure quantities ─────────────────────────────────────────────────────────


def utility(values: Sequence[float], q: float) -> float:
    """``U_q(v) = sum q**(i-1) v_i`` (values best first) -- the package-model owner."""
    return package_model.geom_utility(values, q)


def residual(u_a: float, u_b: float, raw_a: float, raw_b: float) -> float:
    """The Phase 2/3 residual: the utility gap over the mean of the two
    positive-only adjusted totals.  ``rawA + rawB + |(rawA - rawB) - g|`` is the
    sum of the adjusted totals, because the side that discarded less depth is
    credited the difference (``package_model`` docstring)."""
    g = u_a - u_b
    return g / ((raw_a + raw_b + abs((raw_a - raw_b) - g)) / 2.0)


def shape_label(n_stud: int, n_other: int) -> str:
    """Shape with the stud side (the side holding the single most valuable asset) first."""
    if max(n_stud, n_other) >= 3:
        return "3+"
    return f"{n_stud}v{n_other}"


def phase3_bin(n_fewer: int, n_more: int) -> str:
    """Phase 2/3 structure bin (same definition, so results stay comparable)."""
    if n_fewer == n_more:
        return "equal"
    if n_more >= 5:
        return "deep"
    if n_fewer == 1 and n_more in (2, 3):
        return "1vN_small"
    return "ordinary"


def value_tier(level: float) -> str:
    for edge, label in zip(TIER_EDGES, TIERS):
        if level < edge:
            return label
    return TIERS[-1]


def asset_class(pieces: Iterable[Mapping[str, Any]]) -> str:
    pieces = list(pieces)
    if any(
        p.get("kind") == "player" and str(p.get("pos") or "").upper() in IDP_POSITIONS
        for p in pieces
    ):
        return "includes_idp"
    if any(p.get("kind") == "pick" for p in pieces):
        return "includes_picks_no_idp"
    return "offense_players_only"


def build_record(row: Mapping[str, Any]) -> dict[str, Any]:
    """One priced row -> one oriented analysis record (A = fewer pieces)."""
    sides = [sorted(side, key=lambda p: -float(p["v"])) for side in row["sides"]]
    if len(sides) != 2 or not sides[0] or not sides[1]:
        raise ValueError("a record needs two non-empty sides")
    a, b = (sides[0], sides[1]) if len(sides[0]) <= len(sides[1]) else (sides[1], sides[0])
    va = [float(p["v"]) for p in a]
    vb = [float(p["v"]) for p in b]
    stud, other = (va, vb) if va[0] >= vb[0] else (vb, va)
    level = (va[0] + vb[0]) / 2.0
    return {
        "date": str(row["date"])[:10],
        "cluster": row.get("cluster"),
        "vA": va,
        "vB": vb,
        "unequal": len(va) != len(vb),
        "shape": shape_label(len(stud), len(other)),
        "p3bin": phase3_bin(len(va), len(vb)),
        "assetClass": asset_class(a + b),
        "tier": value_tier(level),
        "targetPriceAuthority": row.get("targetPriceAuthority"),
        "source": row.get("source") or "unknown",
    }


def value_matrix(vectors: Sequence[Sequence[float]]) -> np.ndarray:
    width = max(len(v) for v in vectors)
    out = np.zeros((len(vectors), width))
    for i, v in enumerate(vectors):
        out[i, : len(v)] = v
    return out


def utility_grid(values: np.ndarray, qs: Sequence[float], *, level_c: float = 0.0) -> np.ndarray:
    """``(n, len(qs))`` utilities; rows of ``values`` are sorted best first and
    zero-padded.  ``level_c > 0`` is the non-homogeneous level diagnostic
    ``sum q**(i-1) max(0, v_i - c)`` (never a package formula)."""
    v = np.maximum(values - level_c, 0.0) if level_c else values
    powers = np.array([[q**i for q in qs] for i in range(values.shape[1])])
    return v @ powers


def residual_grid(
    recs: Sequence[Mapping[str, Any]], qs: Sequence[float], *, level_c: float = 0.0
) -> np.ndarray:
    va = value_matrix([r["vA"] for r in recs])
    vb = value_matrix([r["vB"] for r in recs])
    ua = utility_grid(va, qs, level_c=level_c)
    ub = utility_grid(vb, qs, level_c=level_c)
    ra = va.sum(axis=1, keepdims=True)
    rb = vb.sum(axis=1, keepdims=True)
    g = ua - ub
    return g / ((ra + rb + np.abs((ra - rb) - g)) / 2.0)


def parity_check(recs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """At q = 0.78 the vectorized utilities must equal the owner's, and the gap
    the owner's adjusted gap within its integer rounding.  A failure aborts."""
    va = value_matrix([r["vA"] for r in recs])
    vb = value_matrix([r["vB"] for r in recs])
    ua = utility_grid(va, [Q_INCUMBENT])[:, 0]
    ub = utility_grid(vb, [Q_INCUMBENT])[:, 0]
    max_u = 0.0
    max_gap = 0.0
    for i, r in enumerate(recs):
        oa, ob = utility(r["vA"], Q_INCUMBENT), utility(r["vB"], Q_INCUMBENT)
        max_u = max(max_u, abs(oa - ua[i]), abs(ob - ub[i]))
        adj_a, adj_b, _, _ = package_model.adjusted_pair_totals(
            r["vA"], r["vB"], model_id=package_model.GEOM_Q078_V1
        )
        max_gap = max(max_gap, abs((adj_a - adj_b) - (ua[i] - ub[i])))
    ok = bool(max_u < 1e-6 and max_gap <= 1.0)
    max_u, max_gap = float(max_u), float(max_gap)
    out = {
        "rows": len(recs),
        "maxUtilityDiff": max_u,
        "maxAdjustedGapDiff": round(max_gap, 4),
        "ok": ok,
    }
    if not ok:
        raise RuntimeError(f"parity check failed: {out}")
    return out


# ── Folds and fitting ───────────────────────────────────────────────────────


def date_blocks(dates: Sequence[str], k: int = K_BLOCKS) -> np.ndarray:
    """Contiguous blocks of about equal trade count; a date is never split."""
    n = len(dates)
    counts = Counter(dates)
    block_of: dict[str, int] = {}
    before = 0
    for d in sorted(counts):
        block_of[d] = min(k - 1, int((before + counts[d] / 2.0) * k / n))
        before += counts[d]
    return np.array([block_of[d] for d in dates], dtype=int)


def fit_index(res: np.ndarray, mask: np.ndarray, *, moment: bool = False) -> int | None:
    """Grid index minimising the mean ``r**2`` (or ``|mean r|``) over ``mask``."""
    if not mask.any():
        return None
    sub = res[mask]
    loss = np.abs(sub.mean(axis=0)) if moment else (sub**2).mean(axis=0)
    return int(np.argmin(loss))


# ── Two-way cluster bootstrap ───────────────────────────────────────────────


class TwoWayBoot:
    """Pigeonhole bootstrap (Owen 2007): leagues and dates are drawn with
    replacement independently; a row's weight is the product of its league's and
    its date's draw counts.  ``by_date=False`` is the league-only bootstrap.  A
    row with no league is its own league cluster."""

    def __init__(
        self,
        clusters: Sequence[Any],
        dates: Sequence[str],
        *,
        reps: int,
        seed: int,
        by_date: bool = True,
    ):
        codes: dict[Any, int] = {}
        self.li = np.array(
            [
                codes.setdefault(c if c is not None else ("_solo", i), len(codes))
                for i, c in enumerate(clusters)
            ]
        )
        dcodes: dict[str, int] = {}
        self.di = np.array([dcodes.setdefault(d, len(dcodes)) for d in dates])
        self.n_leagues, self.n_dates, self.reps = len(codes), len(dcodes), reps
        rng = np.random.default_rng(seed)
        self.ml = rng.multinomial(
            self.n_leagues, np.full(self.n_leagues, 1.0 / self.n_leagues), size=reps
        ).astype(float)
        if by_date:
            self.md = rng.multinomial(
                self.n_dates, np.full(self.n_dates, 1.0 / self.n_dates), size=reps
            ).astype(float)
        else:
            self.md = np.ones((reps, self.n_dates))

    def _chunks(self, size: int = 100):
        for s in range(0, self.reps, size):
            e = min(self.reps, s + size)
            yield s, e, self.ml[s:e][:, self.li] * self.md[s:e][:, self.di]

    def means(self, cols: Sequence[tuple[np.ndarray, np.ndarray]]) -> np.ndarray:
        """Replicate means ``(reps, len(cols))`` of each ``x`` over its ``mask``."""
        num_m = np.column_stack([np.where(m, x, 0.0) for x, m in cols])
        den_m = np.column_stack([m.astype(float) for _, m in cols])
        num = np.zeros((self.reps, len(cols)))
        den = np.zeros((self.reps, len(cols)))
        for s, e, w in self._chunks():
            num[s:e] = w @ num_m
            den[s:e] = w @ den_m
        with np.errstate(invalid="ignore", divide="ignore"):
            return num / den

    def argmin(self, res: np.ndarray, mask: np.ndarray, *, moment: bool = False) -> np.ndarray:
        """Replicate grid index minimising the weighted mean ``r**2`` over ``mask``
        (``moment=True``: the weighted ``|mean r|``)."""
        x = np.where(mask[:, None], res if moment else res**2, 0.0)
        cnt = mask.astype(float)
        out = np.zeros(self.reps, dtype=int)
        for s, e, w in self._chunks():
            with np.errstate(invalid="ignore", divide="ignore"):
                loss = (w @ x) / (w @ cnt)[:, None]
            loss = np.abs(loss) if moment else loss
            out[s:e] = np.nanargmin(np.where(np.isfinite(loss), loss, np.inf), axis=1)
        return out

    def argmin_mse(self, res: np.ndarray, mask: np.ndarray) -> np.ndarray:
        return self.argmin(res, mask)


def ci95(samples: np.ndarray) -> list[float] | None:
    s = samples[np.isfinite(samples)]
    if len(s) < 20:
        return None
    return [round(float(np.percentile(s, 2.5)), 4), round(float(np.percentile(s, 97.5)), 4)]


def _r4(x: float | None) -> float | None:
    return None if x is None or not math.isfinite(x) else round(float(x), 4)


# ── Evaluation ──────────────────────────────────────────────────────────────


def _strata(recs: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, np.ndarray]]:
    out: dict[str, dict[str, np.ndarray]] = {"all": {"all": np.ones(len(recs), dtype=bool)}}
    for key, labels in (
        ("shape", SHAPES),
        ("p3bin", P3_BINS),
        ("assetClass", CLASSES),
        ("tier", TIERS),
    ):
        vals = np.array([r[key] for r in recs])
        out[key] = {lab: vals == lab for lab in labels}
    return out


def residual_tables(
    recs, sel, model_res: Mapping[str, np.ndarray], boot: TwoWayBoot
) -> dict[str, Any]:
    """Mean signed residual (unequal rows, consolidator orientation), mean absolute
    residual (all rows) and MSE (unequal rows) per stratum and model, with
    two-way clustered intervals."""
    unequal = np.array([r["unequal"] for r in recs])
    strata = _strata(recs)
    cols: list[tuple[np.ndarray, np.ndarray]] = []
    index: list[tuple[str, str, str, str]] = []
    for skey, groups in strata.items():
        for lab, m in groups.items():
            for model, res in model_res.items():
                for stat, x, mask in (
                    ("meanSigned", res, sel & m & unequal),
                    ("meanAbs", np.abs(res), sel & m),
                    ("mse", res**2, sel & m & unequal),
                ):
                    cols.append((x, mask))
                    index.append((skey, lab, model, stat))
    reps = boot.means(cols)
    out: dict[str, Any] = {}
    for j, (skey, lab, model, stat) in enumerate(index):
        x, mask = cols[j]
        cell = out.setdefault(skey, {}).setdefault(lab, {}).setdefault(model, {})
        n = int(mask.sum())
        cell[stat] = {
            "n": n,
            "value": _r4(float(x[mask].mean())) if n else None,
            "ci95": ci95(reps[:, j]) if n else None,
        }
    return out


def _side_of(ci: Sequence[float] | None, x: float) -> str:
    if not ci:
        return "no_interval"
    return "interval_below" if ci[1] < x else ("interval_above" if ci[0] > x else "interval_covers")


def evaluate(
    recs: list[dict[str, Any]],
    *,
    boot_reps: int = BOOT_REPS,
    qhat_reps: int = QHAT_BOOT_REPS,
    seed: int = SEED,
) -> dict[str, Any]:
    """The preregistered evaluation over oriented records."""
    recs = sorted(recs, key=lambda r: r["date"])
    n = len(recs)
    out: dict[str, Any] = {"n": n}
    if n == 0:
        out["sufficiency"] = {"decisive": False, "reason": "no_eligible_trades"}
        return out
    dates = [r["date"] for r in recs]
    clusters = [r["cluster"] for r in recs]
    unequal = np.array([r["unequal"] for r in recs])
    multi = np.array([max(len(r["vA"]), len(r["vB"])) >= 2 for r in recs])
    out["parity"] = parity_check(recs)
    res = residual_grid(recs, Q_GRID)
    res_lvl = residual_grid(recs, Q_GRID, level_c=LEVEL_C)
    gi078 = Q_GRID.index(round(Q_INCUMBENT, 2))
    gi100 = Q_GRID.index(1.0)

    blocks = date_blocks(dates)
    out["population"] = {
        "trades": n,
        "unequal": int(unequal.sum()),
        "distinctLeagues": len({c for c in clusters if c is not None}),
        "rowsWithoutLeague": sum(1 for c in clusters if c is None),
        "distinctDates": len(set(dates)),
        "dateRange": [dates[0], dates[-1]],
        "byShape": dict(Counter(r["shape"] for r in recs)),
        "byAssetClass": dict(Counter(r["assetClass"] for r in recs)),
        "byTier": dict(Counter(r["tier"] for r in recs)),
        "bySource": dict(Counter(r["source"] for r in recs)),
    }

    # Forward chaining by date block.
    folds = []
    fit_col = np.full(n, -1, dtype=int)
    mom_col = np.full(n, -1, dtype=int)
    disjoint = np.zeros(n, dtype=bool)
    for k in range(1, K_BLOCKS):
        train, test = blocks < k, blocks == k
        tr_u = train & unequal
        gi = fit_index(res, tr_u)
        gm = fit_index(res, tr_u, moment=True)
        gl = fit_index(res_lvl, tr_u)
        fold = {
            "fold": k + 1,
            "trainDates": [
                min((d for d, b in zip(dates, blocks) if b < k), default=None),
                max((d for d, b in zip(dates, blocks) if b < k), default=None),
            ],
            "testDates": [
                min((d for d, b in zip(dates, blocks) if b == k), default=None),
                max((d for d, b in zip(dates, blocks) if b == k), default=None),
            ],
            "trainUnequal": int(tr_u.sum()),
            "testRows": int(test.sum()),
            "testUnequal": int((test & unequal).sum()),
            "qFit": None if gi is None else Q_GRID[gi],
            "qMoment": None if gm is None else Q_GRID[gm],
            "qLevelDiagnostic": None if gl is None else Q_GRID[gl],
        }
        if gi is None or not test.any():
            fold["scored"] = False
        else:
            fold["scored"] = True
            fit_col[test] = gi
            mom_col[test] = gm
            seen = {c for c, t in zip(clusters, train) if t and c is not None}
            disjoint |= test & np.array([c is None or c not in seen for c in clusters])
            tu = test & unequal
            if tu.any():
                fold["mse"] = {
                    "M078": _r4(float((res[tu, gi078] ** 2).mean())),
                    "MFIT": _r4(float((res[tu, gi] ** 2).mean())),
                    "M100": _r4(float((res[tu, gi100] ** 2).mean())),
                }
        folds.append(fold)
    out["folds"] = folds
    sel = fit_col >= 0
    rows = np.arange(n)
    model_res = {
        "M078": res[:, gi078],
        "MFIT": np.where(sel, res[rows, np.maximum(fit_col, 0)], np.nan),
        # Deviation D1 (results doc): the fold's moment-fitted q, scored the same way.
        "MMOM": np.where(sel, res[rows, np.maximum(mom_col, 0)], np.nan),
        "M100": res[:, gi100],
    }

    # Sufficiency (R0).
    scored = [f for f in folds if f.get("scored")]
    reasons = []
    if int(unequal.sum()) < R0_MIN_UNEQUAL:
        reasons.append(f"unequal_trades_below_{R0_MIN_UNEQUAL}")
    if out["population"]["distinctLeagues"] < R0_MIN_LEAGUES:
        reasons.append(f"distinct_leagues_below_{R0_MIN_LEAGUES}")
    if len(scored) < K_BLOCKS - 1 or any(f["testUnequal"] < R0_MIN_FOLD_UNEQUAL for f in scored):
        reasons.append(f"a_test_fold_below_{R0_MIN_FOLD_UNEQUAL}_unequal")
    out["sufficiency"] = {"decisive": not reasons, "reasons": reasons, "rule": "R0"}

    boot = TwoWayBoot(clusters, dates, reps=boot_reps, seed=seed)
    boot_l = TwoWayBoot(clusters, dates, reps=boot_reps, seed=seed + 1, by_date=False)
    out["bootstrap"] = {"method": "two-way pigeonhole (league x date)", "reps": boot_reps, "seed": seed,
                        "leagueClusters": boot.n_leagues, "dateClusters": boot.n_dates}  # fmt: skip

    # Headline: pooled OOS MSE and paired differences (unequal test rows).
    tu = sel & unequal
    head_cols = [
        ((model_res["M078"]) ** 2, tu),
        ((model_res["MFIT"]) ** 2, tu),
        ((model_res["M100"]) ** 2, tu),
        (model_res["M078"] ** 2 - np.nan_to_num(model_res["MFIT"]) ** 2, tu),
        (model_res["M078"] ** 2 - model_res["M100"] ** 2, tu),
    ]
    rep2 = boot.means(head_cols) if tu.any() else np.full((boot_reps, 5), np.nan)
    repl = boot_l.means(head_cols[3:]) if tu.any() else np.full((boot_reps, 2), np.nan)
    names = ("mseM078", "mseMFIT", "mseM100", "diffM078minusMFIT", "diffM078minusM100")
    head: dict[str, Any] = {"testUnequal": int(tu.sum())}
    for j, name in enumerate(names):
        x, m = head_cols[j]
        head[name] = {
            "value": _r4(float(x[m].mean())) if m.any() else None,
            "ci95": ci95(rep2[:, j]),
        }
        if j >= 3:
            head[name]["ci95LeagueOnly"] = ci95(repl[:, j - 3])
    # League-disjoint sensitivity.
    td = disjoint & unequal
    head["leagueDisjointTestUnequal"] = int(td.sum())
    if td.any():
        rep_d = boot.means([(head_cols[3][0], td), (head_cols[4][0], td)])
        head["leagueDisjoint"] = {
            "diffM078minusMFIT": {
                "value": _r4(float(head_cols[3][0][td].mean())),
                "ci95": ci95(rep_d[:, 0]),
            },
            "diffM078minusM100": {
                "value": _r4(float(head_cols[4][0][td].mean())),
                "ci95": ci95(rep_d[:, 1]),
            },
        }
    # J (Phase 3 calibration loss) on the pooled test set.
    p3 = np.array([r["p3bin"] for r in recs])
    head["J"] = {}
    for model, rv in model_res.items():
        means = [
            abs(float(rv[sel & (p3 == b)].mean()))
            for b in ("1vN_small", "ordinary", "deep")
            if (sel & (p3 == b)).any()
        ]
        head["J"][model] = _r4(max(means)) if means else None
    out["outOfSample"] = head
    out["residualTables"] = residual_tables(recs, sel, model_res, boot)

    # Full-sample q-hat with a refit bootstrap; secondary fits.
    full_u = unequal
    gi_full = fit_index(res, full_u)
    qfit: dict[str, Any] = {
        "grid": [Q_GRID[0], Q_GRID[-1], 0.01],
        "target": "mean r^2 over unequal-count trades",
    }
    if gi_full is not None:
        qb = TwoWayBoot(clusters, dates, reps=qhat_reps, seed=seed + 2)
        idx = qb.argmin_mse(res, full_u)
        qs = np.array([Q_GRID[i] for i in idx])
        qm = np.array([Q_GRID[i] for i in qb.argmin(res, full_u, moment=True)])
        loss = (res[full_u] ** 2).mean(axis=0)
        qfit.update({
            "qHat": Q_GRID[gi_full],
            "atGridBoundary": gi_full in (0, len(Q_GRID) - 1),
            "ci95": [round(float(np.percentile(qs, 2.5)), 2), round(float(np.percentile(qs, 97.5)), 2)],
            "bootReps": qhat_reps,
            "lossAt": {"0.78": _r4(float(loss[gi078])), "qHat": _r4(float(loss[gi_full])), "1.00": _r4(float(loss[gi100]))},
            "lossCurve": {f"{q:.2f}": _r4(float(loss[i])) for i, q in enumerate(Q_GRID) if i % 5 == 0 or i == gi_full},
            "qMoment": Q_GRID[fit_index(res, full_u, moment=True)],
            # Added after the synthetic check (results doc, deviation D1): the
            # moment estimator's interval, from the same resamples.
            "qMomentCi95": [round(float(np.percentile(qm, 2.5)), 2), round(float(np.percentile(qm, 97.5)), 2)],
            "qMomentAtGridBoundary": fit_index(res, full_u, moment=True) in (0, len(Q_GRID) - 1),
            "qAllMultiPiece": Q_GRID[fit_index(res, multi)] if multi.any() else None,
            "qLevelDiagnostic_c2000": Q_GRID[fit_index(res_lvl, full_u)],
        })  # fmt: skip
        r2 = (
            qfit["qHat"] < R2_SHAPE_ONLY_BELOW
            and R2_LEVEL_RANGE[0] <= qfit["qLevelDiagnostic_c2000"] <= R2_LEVEL_RANGE[1]
        )
        qfit["R2_levelEffectExplainsLowQ"] = bool(r2)
    out["qFit"] = qfit

    # R1 reading (only meaningful when R0 passes).
    def _verdict(ci):
        if ci is None:
            return "no_interval"
        return (
            "favours_alternative"
            if ci[0] > 0
            else ("favours_0.78" if ci[1] < 0 else "no_difference_detected")
        )

    out["rules"] = {
        "R0_decisive": out["sufficiency"]["decisive"],
        "R1_078_vs_fitted": _verdict(head["diffM078minusMFIT"]["ci95"]),
        "R1_078_vs_q1": _verdict(head["diffM078minusM100"]["ci95"]),
        "R2_levelEffectExplainsLowQ": qfit.get("R2_levelEffectExplainsLowQ"),
        # Deviation D1: R1 compares prediction loss and is not a test of q (the
        # synthetic check shows it favours a fitted q when the true q is 0.78);
        # the calibration reading is the moment fit's interval and J.
        "D1_R1_validity": "prediction_loss_only_not_a_test_of_q",
        "D1_momentQ_vs_078": _side_of(qfit.get("qMomentCi95"), Q_INCUMBENT),
        "D1_J_oos": head["J"],
    }

    # Format-comparability sensitivity (D-BOX only, when the ledger carries it).
    auth = np.array([r.get("targetPriceAuthority") == 1 for r in recs])
    if (auth & unequal).sum() >= TARGET_AUTHORITY_MIN_UNEQUAL:
        out["targetAuthoritySensitivity"] = residual_tables(recs, sel & auth, model_res, boot)[
            "p3bin"
        ]
    else:
        out["targetAuthoritySensitivity"] = {"reported": False, "unequalWithAuthority1": int((auth & unequal).sum()),
                                             "minimum": TARGET_AUTHORITY_MIN_UNEQUAL}  # fmt: skip

    q_hat = qfit.get("qHat")
    out["bands"] = band_evaluation(recs, boot, {"0.78": Q_INCUMBENT, "qHat": q_hat, "1.00": 1.0})
    return out


def band_levels(recs: Sequence[Mapping[str, Any]], q: float) -> tuple[list[str], np.ndarray]:
    """Owner band level per trade and whether it goes against the consolidating side."""
    levels, against = [], []
    for r in recs:
        ua, ub = utility(r["vA"], q), utility(r["vB"], q)
        levels.append(
            fairness_bands.classify(ua - ub, fairness_bands.fairness_base([ua, ub]))["level"]
        )
        against.append(r["unequal"] and ua < ub)
    return levels, np.array(against)


def band_evaluation(recs, boot: TwoWayBoot, qs: Mapping[str, float | None]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "bands": fairness_bands.receipt(),
        "assumption": "A1: an accepted trade is, on average, a fair exchange at canonical value (PREREGISTRATION.md 7.1)",
    }
    strata = _strata(recs)
    unequal = np.array([r["unequal"] for r in recs])
    per_q: dict[str, Any] = {}
    level_by_q: dict[str, np.ndarray] = {}
    for name, q in qs.items():
        if q is None:
            continue
        levels, against = band_levels(recs, q)
        lv = np.array(levels)
        level_by_q[name] = lv
        nf = np.isin(lv, NOT_FAIR).astype(float)
        lop = (lv == "lopsided").astype(float)
        cols, index = [], []
        for skey, groups in strata.items():
            for lab, m in groups.items():
                cols += [(nf, m), (lop, m)]
                index += [(skey, lab, "notFairShare"), (skey, lab, "lopsidedShare")]
        # Shape neutrality: shape minus 1v1, same replicates.
        reps = boot.means(cols)
        table: dict[str, Any] = {}
        for j, (skey, lab, stat) in enumerate(index):
            x, m = cols[j]
            cell = table.setdefault(skey, {}).setdefault(lab, {})
            cell["n"] = int(m.sum())
            cell[stat] = {
                "value": _r4(float(x[m].mean())) if m.any() else None,
                "ci95": ci95(reps[:, j]),
            }
            if stat == "notFairShare":
                cell["levels"] = dict(Counter(lv[m].tolist()))
                nfu = m & unequal & (nf > 0)
                cell["againstConsolidatorShareOfNotFair"] = (
                    _r4(float(against[nfu].mean())) if nfu.any() else None
                )
        ref = {
            stat: reps[:, index.index(("shape", "1v1", stat))]
            for stat in ("notFairShare", "lopsidedShare")
        }
        excess = {}
        for lab in SHAPES:
            if lab == "1v1":
                continue
            m = strata["shape"][lab]
            if not m.any() or not strata["shape"]["1v1"].any():
                continue
            e = {}
            for stat in ("notFairShare", "lopsidedShare"):
                j = index.index(("shape", lab, stat))
                diff = reps[:, j] - ref[stat]
                point = table["shape"][lab][stat]["value"] - table["shape"]["1v1"][stat]["value"]
                e[stat] = {
                    "pp": _r4(100 * point),
                    "ci95pp": None
                    if ci95(diff) is None
                    else [round(100 * c, 2) for c in ci95(diff)],
                }
            excess[lab] = e
        r3 = [
            lab for lab in ("1v2", "3+")
            if lab in excess and excess[lab]["notFairShare"]["pp"] is not None
            and excess[lab]["notFairShare"]["pp"] > R3_EXCESS_PP
            and excess[lab]["notFairShare"]["ci95pp"] is not None
            and excess[lab]["notFairShare"]["ci95pp"][0] > 0
        ]  # fmt: skip
        per_q[name] = {
            "q": q,
            "table": table,
            "excessOver1v1": excess,
            "R3_shapeBiased": r3 if name == "0.78" else None,
        }
    out["byQ"] = per_q
    # Stability: share of trades whose level changes from q = 0.78.
    stab: dict[str, Any] = {}
    base = level_by_q.get("0.78")
    for name, lv in level_by_q.items():
        if name == "0.78" or base is None:
            continue
        changed = lv != base
        stab[name] = {
            lab: _r4(float(changed[m].mean())) if m.any() else None
            for lab, m in strata["shape"].items()
        }
        stab[name]["all"] = _r4(float(changed.mean()))
    out["stabilityVs078"] = stab
    return out


# ── Data adapters ───────────────────────────────────────────────────────────

_ARCHIVE_RE = re.compile(r"dynasty_export_(\d{8})_(\d{6})\.zip$")
_INNER_RE = re.compile(r"dynasty_data_(\d{4}-\d{2}-\d{2})\.json$")


def archived_boards(archive_dir: Path) -> list[tuple[date, str, str]]:
    """``[(board_date, zip_path, inner_name)]`` oldest first; the board date is
    the date in the archived payload's own name."""
    out = []
    for p in archive_dir.glob("dynasty_export_*.zip"):
        if not _ARCHIVE_RE.search(p.name):
            continue
        with zipfile.ZipFile(p) as zf:
            inner = next((n for n in zf.namelist() if _INNER_RE.search(n)), None)
        if inner:
            out.append((date.fromisoformat(_INNER_RE.search(inner).group(1)), str(p), inner))
    return sorted(out)


def load_archived_board(path: str, inner: str):
    from src.api.data_contract import build_api_data_contract  # noqa: PLC0415
    from src.trade.market_trade_eval import BoardIndex  # noqa: PLC0415

    with zipfile.ZipFile(path) as zf:
        return BoardIndex(build_api_data_contract(json.loads(zf.read(inner))))


def cluster_key(league_id: Any) -> str | None:
    if league_id in (None, ""):
        return None
    return hashlib.sha256(f"{CLUSTER_SALT}|{league_id}".encode()).hexdigest()[:16]


def price_groups(
    groups: Iterable[Mapping[str, Any]],
    boards: Sequence[tuple[date, str, str]],
    *,
    load_board: Callable[[str, str], Any] = load_archived_board,
    max_lag_days: int = MAX_LAG_DAYS,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Price ledger groups on the board archived strictly before each trade (at
    most ``max_lag_days``) through the ledger owner's eligibility.  One board in
    memory at a time.  All-or-nothing: an unpriced asset excludes the trade."""
    from src.trade import market_trade_eval as ev  # noqa: PLC0415

    audit: dict[str, Any] = {
        "groups": 0,
        "excluded": Counter(),
        "topology": Counter(),
        "dedupeState": Counter(),
    }
    pending: dict[tuple[str, str], list] = {}
    for g in groups:
        audit["groups"] += 1
        topo = ev.classify_topology(g)
        audit["topology"][topo["topology"]] += 1
        audit["dedupeState"][str(g.get("dedupeState"))] += 1
        try:
            td = date.fromisoformat(str(g.get("occurredDate"))[:10])
        except ValueError:
            audit["excluded"]["undated"] += 1
            continue
        prior = [b for b in boards if b[0] < td and (td - b[0]).days <= max_lag_days]
        if not prior:
            audit["excluded"]["no_board_strictly_before_within_lag"] += 1
            continue
        bdate, path, inner = prior[-1]
        ok, why = ev.residual_eligible(g, topo, board_date=bdate, max_board_lag_days=max_lag_days)
        if not ok:
            audit["excluded"][str(why)] += 1
            continue
        pending.setdefault((path, inner), []).append((g, td))
    rows: list[dict[str, Any]] = []
    for (path, inner), items in sorted(pending.items()):
        board = load_board(path, inner)
        for g, td in items:
            sides = []
            for side in g["sides"]:
                priced = []
                for a in side:
                    v = board.values(a).get("canonical")
                    if v is None:
                        break
                    priced.append({"v": float(v), "kind": a.get("kind"), "pos": a.get("position")})
                else:
                    sides.append(priced)
                    continue
                break
            if len(sides) != 2:
                audit["excluded"]["asset_unpriced_on_point_in_time_board"] += 1
                continue
            rows.append({
                "date": td.isoformat(),
                "cluster": cluster_key(g.get("hostLeagueId")),
                "sides": sides,
                "targetPriceAuthority": g.get("targetPriceAuthority"),
                "source": "+".join(sorted(g.get("sourceFamilies") or [])) or "unknown",
            })  # fmt: skip
        del board
    audit["graded"] = len(rows)
    audit["boardsUsed"] = len(pending)
    for k in ("excluded", "topology", "dedupeState"):
        audit[k] = dict(audit[k])
    return rows, audit


def ledger_groups(
    conn: sqlite3.Connection, since: str = SINCE_DATE
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from src.trade import market_trade_report as report  # noqa: PLC0415

    meta = report.read_ledger_meta(conn)
    groups = [g for g, _fmt in report.read_ledger_window(conn, since_date=since)]
    return groups, {
        "ledgerBuiltAt": meta.get("builtAt") or meta.get("built_at"),
        "datedGroupsSince": since,
        "datedGroups": len(groups),
    }


def open_ledger_copy(path: Path) -> sqlite3.Connection:
    """An exported ledger copy, read-only (``mode=ro``)."""
    if not path.is_file():
        raise SystemExit(f"no ledger file at {path}")
    return sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)


_FAAB_RE = re.compile(r"faab|^\$\s*\d", re.IGNORECASE)


def own_league_asset(
    label: str, player_ids: Mapping[str, str], positions: Mapping[str, str]
) -> tuple[dict[str, Any], bool]:
    """One snapshot label -> a ledger-shaped asset; second value says a baked
    tier label was priced at the generic grade (the snapshot writes "Mid" for
    every future pick whose slot is unknown)."""
    from src.identity import picks  # noqa: PLC0415

    text = str(label or "").strip()
    parsed = picks.parse_pick_label(text)
    if parsed is not None:
        ref = picks.MarketPickRef(year=parsed.year, round_num=parsed.round_num, slot=parsed.slot)
        return {
            "kind": "pick",
            "canonicalId": ref.canonical_id,
            "pick": {"year": parsed.year, "round": parsed.round_num},
        }, parsed.tier is not None
    if _FAAB_RE.search(text):
        return {"kind": "faab", "canonicalId": None}, False
    pid = player_ids.get(text)
    if pid is None:
        return {"kind": "unresolved", "canonicalId": None}, False
    return {
        "kind": "player",
        "canonicalId": f"player:{pid}",
        "position": positions.get(text),
    }, False


def own_league_groups(snapshot: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The tracked snapshot's trades as ledger-shaped groups.  Format facts come
    from the snapshot itself: dynasty iff ``leagueSettings.type == 2``, superflex
    iff ``SUPER_FLEX`` is a roster slot.  A trade in another season's league is
    excluded (its format is not the snapshot's)."""
    data = json.loads(snapshot.read_text(encoding="utf-8"))["rosterData"]
    league_id = str(data.get("leagueId"))
    dynasty = (data.get("leagueSettings") or {}).get("type") == 2
    superflex = "SUPER_FLEX" in (data.get("rosterPositions") or [])
    fmt = {
        "general": {"dynastyState": "dynasty" if dynasty else "unknown"},
        "offense": {"superflex": True if superflex else None},
    }
    audit: dict[str, Any] = {"trades": 0, "excludedBeforePricing": Counter(), "tierLabelsPricedGeneric": 0,
                             "format": {"dynasty": dynasty, "superflex": superflex}}  # fmt: skip
    groups = []
    for t in data.get("trades") or []:
        audit["trades"] += 1
        sides = t.get("sides") or []
        if len(sides) != 2:
            audit["excludedBeforePricing"]["not_two_team"] += 1
            continue
        if str(t.get("leagueId")) != league_id:
            audit["excludedBeforePricing"]["other_season_league_format_not_the_snapshots"] += 1
            continue
        out_sides = []
        for s in sides:
            assets = []
            for label in s.get("got") or []:
                asset, downgraded = own_league_asset(
                    label, data.get("playerIds") or {}, data.get("positions") or {}
                )
                audit["tierLabelsPricedGeneric"] += int(downgraded)
                assets.append(asset)
            out_sides.append(assets)
        ts = int(t.get("timestamp") or 0)
        groups.append({
            "occurredDate": datetime.fromtimestamp(ts / 1000, tz=timezone.utc).date().isoformat(),
            "sides": out_sides,
            "dedupeState": "CONFIRMED_UNIQUE",
            "marketFormat": fmt,
            "hostLeagueId": league_id,
            "sourceFamilies": ["own_league_snapshot"],
            "targetPriceAuthority": 1,
        })  # fmt: skip
    audit["excludedBeforePricing"] = dict(audit["excludedBeforePricing"])
    return groups, audit


def read_rows(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            r = json.loads(line)
            vals = [p.get("v") for s in r["sides"] for p in s]
            if (
                len(r["sides"]) != 2
                or not all(r["sides"])
                or not all(isinstance(v, (int, float)) and math.isfinite(v) and v > 0 for v in vals)
            ):
                raise ValueError("a priced row needs two non-empty sides of finite positive values")
            rows.append(r)
    return rows


def write_rows(
    rows: Sequence[Mapping[str, Any]], path: Path, *, audit: Mapping[str, Any] | None = None
) -> None:
    """Priced rows carry per-trade values; they are refused inside the repository.
    The pricing audit (counts only) is written beside them as ``<path>.audit.json``."""
    target = path.resolve()
    if target == REPO or REPO in target.parents:
        raise SystemExit(
            "--write-rows refuses a path inside the repository (per-trade rows are never committed)"
        )
    with target.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, sort_keys=True) + "\n")
    if audit is not None:
        Path(str(target) + ".audit.json").write_text(
            json.dumps(audit, default=_json_default), encoding="utf-8"
        )


def _json_default(o: Any) -> Any:
    if isinstance(o, np.generic):
        return o.item()
    raise TypeError(f"not JSON serializable: {type(o).__name__}")


# ── Synthetic (D-SYN): tests and power analysis only ───────────────────────

SYN_SHAPES = ((1, 1, 0.25), (1, 2, 0.25), (1, 3, 0.10), (2, 2, 0.15), (2, 3, 0.15), (3, 4, 0.10))


def synthetic_rows(
    n: int,
    *,
    true_q: float,
    sigma: float,
    seed: int,
    leagues: int = 400,
    days: int = 120,
    noise: str = "symmetric",
) -> list[dict[str, Any]]:
    """Accepted trades that clear EXACTLY under ``true_q`` up to multiplicative
    noise ``eps ~ N(0, sigma)``.  Side B is first scaled so ``U_q(B) = U_q(A)``;
    then ``noise="symmetric"`` multiplies A by ``e^(eps/2)`` and B by ``e^(-eps/2)``,
    and ``noise="b_side"`` multiplies B alone by ``e^eps``.  Values are lognormal,
    clipped to [300, 9999] before scaling.  Never evidence about the market."""
    if noise not in ("symmetric", "b_side"):
        raise ValueError(f"unknown noise placement {noise!r}")
    rng = np.random.default_rng(seed)
    probs = np.array([s[2] for s in SYN_SHAPES])
    start = date(2026, 7, 1)
    rows = []
    for _ in range(n):
        ka, kb, _p = SYN_SHAPES[rng.choice(len(SYN_SHAPES), p=probs / probs.sum())]
        va = sorted(
            np.clip(rng.lognormal(math.log(3000), 0.6, ka), 300, 9999).tolist(), reverse=True
        )
        vb = sorted(
            np.clip(rng.lognormal(math.log(3000), 0.6, kb), 300, 9999).tolist(), reverse=True
        )
        eps = rng.normal(0.0, sigma) if sigma > 0 else 0.0
        clear = utility(va, true_q) / utility(vb, true_q)
        if noise == "symmetric":
            va = [v * math.exp(eps / 2.0) for v in va]
            vb = [v * clear * math.exp(-eps / 2.0) for v in vb]
        else:
            vb = [v * clear * math.exp(eps) for v in vb]
        kinds = rng.choice(["player", "pick"], size=ka + kb, p=[0.7, 0.3])
        pos = rng.choice(["WR", "RB", "QB", "TE", "LB"], size=ka + kb)
        pieces = [
            {"v": float(v), "kind": str(k), "pos": str(p) if k == "player" else None}
            for v, k, p in zip(va + vb, kinds, pos)
        ]
        rows.append({
            "date": (start + timedelta(days=int(rng.integers(0, days)))).isoformat(),
            "cluster": f"syn{int(rng.integers(0, leagues))}",
            "sides": [pieces[:ka], pieces[ka:]],
            "source": "synthetic",
        })  # fmt: skip
    return rows


def power_analysis(
    *,
    true_qs=(0.70, 0.78, 0.85),
    sizes=(250, 1000, 5000),
    noises=("symmetric", "b_side"),
    sigma: float = 0.25,
    reps: int = 200,
    seed: int = SEED,
) -> dict[str, Any]:
    """Recovery and interval width of both preregistered estimators (MSE, the
    primary; moment, the secondary) on synthetic trades with a KNOWN q.  The
    trades are iid (no league or date dependence), so the widths are a LOWER
    bound on what clustered real trades give."""
    out: dict[str, Any] = {"label": "SYNTHETIC: estimator check and power only, never market evidence",
                           "sigma": sigma, "sigmaBasis": "Phase 3 production 1-for-1 mean |r| 0.1998 ~ 0.8 sigma",
                           "bootstrapReps": reps, "cells": []}  # fmt: skip
    for ni, noise in enumerate(noises):
        for qi, tq in enumerate(true_qs):
            for si, n in enumerate(sizes):
                rows = synthetic_rows(
                    n, true_q=tq, sigma=sigma, seed=seed + 1000 * ni + 100 * qi + si, noise=noise
                )
                recs = [build_record(r) for r in rows]
                res = residual_grid(recs, Q_GRID)
                unequal = np.array([r["unequal"] for r in recs])
                boot = TwoWayBoot(
                    [None] * len(recs), ["d"] * len(recs), reps=reps, seed=seed + 7, by_date=False
                )
                cell: dict[str, Any] = {"noise": noise, "trueQ": tq, "trades": n,
                                        "unequal": int(unequal.sum())}  # fmt: skip
                for name, moment in (("mse", False), ("moment", True)):
                    qs = np.array([Q_GRID[i] for i in boot.argmin(res, unequal, moment=moment)])
                    lo, hi = float(np.percentile(qs, 2.5)), float(np.percentile(qs, 97.5))
                    cell[name] = {
                        "qHat": Q_GRID[fit_index(res, unequal, moment=moment)],
                        "ci95": [round(lo, 2), round(hi, 2)],
                        "ciWidth": round(hi - lo, 2),
                        "coversTrueQ": bool(lo - 1e-9 <= tq <= hi + 1e-9),
                    }
                out["cells"].append(cell)
    return out


def r1_false_positive_check(
    *, n: int = 5000, sigma: float = 0.25, reps: int = 200, seed: int = SEED
) -> dict[str, Any]:
    """Run the full preregistered evaluation on synthetic trades whose true q IS
    0.78.  If R1 then 'favours' a fitted q, R1 cannot be read as evidence that
    the market's q differs from 0.78."""
    out: dict[str, Any] = {"label": "SYNTHETIC: true q = 0.78; tests the decision rule, not the market",
                           "trades": n, "sigma": sigma, "byNoise": {}}  # fmt: skip
    for i, noise in enumerate(("symmetric", "b_side")):
        rows = synthetic_rows(
            n, true_q=Q_INCUMBENT, sigma=sigma, seed=seed + 50 + i, noise=noise, leagues=400
        )
        ev = evaluate([build_record(r) for r in rows], boot_reps=reps, qhat_reps=100, seed=seed)
        oos = ev["outOfSample"]
        out["byNoise"][noise] = {
            "qHatMse": ev["qFit"].get("qHat"),
            "qHatMseCi95": ev["qFit"].get("ci95"),
            "qHatMoment": ev["qFit"].get("qMoment"),
            "qHatMomentCi95": ev["qFit"].get("qMomentCi95"),
            "D1_momentQ_vs_078": ev["rules"]["D1_momentQ_vs_078"],
            "foldQFit": [f.get("qFit") for f in ev["folds"]],
            "foldQMoment": [f.get("qMoment") for f in ev["folds"]],
            "diffM078minusMFIT": oos["diffM078minusMFIT"],
            "R1_078_vs_fitted": ev["rules"]["R1_078_vs_fitted"],
            "R1_078_vs_q1": ev["rules"]["R1_078_vs_q1"],
            "J": oos["J"],
        }
    return out


# ── Output safety ───────────────────────────────────────────────────────────

_ID_LIKE = re.compile(r"\d{9,}")
_FORBIDDEN = ("player:", "pick:", "utrade:", "@")
_SHA_KEYS = {"codeSha", "deployedCodeSha"}
_SHA_RE = re.compile(r"^(?:[0-9a-f]{40}|UNKNOWN)$")


def assert_aggregate_only(obj: Any, path: str = "$") -> None:
    """Refuse any output carrying an id-like run or an asset / trade identifier."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            assert_aggregate_only(str(k), f"{path}.<key>")
            if k in _SHA_KEYS and isinstance(v, str):
                if not _SHA_RE.match(v):
                    raise ValueError(f"{path}.{k}: not a commit sha")
                continue
            assert_aggregate_only(v, f"{path}.{k}")
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            assert_aggregate_only(v, f"{path}[{i}]")
    elif isinstance(obj, str):
        if _ID_LIKE.search(obj) or any(f in obj for f in _FORBIDDEN):
            raise ValueError(f"{path}: identifier-like string refused")


def _code_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        sha = out.stdout.strip()
        return sha if _SHA_RE.match(sha) else "UNKNOWN"
    except (OSError, subprocess.SubprocessError):
        return "UNKNOWN"


def _deployed_sha() -> str:
    """Box: the deployed sha from the app dir's git metadata, read as files (no subprocess)."""
    try:
        head = (REPO / ".git" / "HEAD").read_text(encoding="utf-8").strip()
        if head.startswith("ref: "):
            head = (REPO / ".git" / head[5:]).read_text(encoding="utf-8").strip()
        return head if _SHA_RE.match(head) else "UNKNOWN"
    except OSError:
        return "UNKNOWN"


# ── Main ────────────────────────────────────────────────────────────────────


def run(
    rows: list[dict[str, Any]],
    *,
    label: str,
    audit: Mapping[str, Any],
    boot_reps: int,
    qhat_reps: int,
) -> dict[str, Any]:
    recs = [build_record(r) for r in rows]
    return {
        "purpose": "RESEARCH ONLY (Priority 16). geom_q078_v1 and fairness_bands_v2 unchanged.",
        "preregistration": PREREGISTRATION,
        "data": label,
        "packageModel": package_model.receipt(package_model.GEOM_Q078_V1),
        "audit": audit,
        "evaluation": evaluate(recs, boot_reps=boot_reps, qhat_reps=qhat_reps),
    }


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    src = ap.add_mutually_exclusive_group()
    src.add_argument(
        "--box", action="store_true", help="the canonical ledger on this host, read-only guard"
    )
    src.add_argument("--ledger", type=Path, help="exported copy of underlying_trades.sqlite")
    src.add_argument("--rows", type=Path, help="priced rows JSONL")
    src.add_argument(
        "--own-league", nargs="?", const=REPO / "data" / "sleeper_last_good.json", type=Path
    )
    ap.add_argument("--power", action="store_true", help="add the synthetic power analysis")
    ap.add_argument("--archive-dir", type=Path, default=REPO / "exports" / "archive")
    ap.add_argument("--since", default=SINCE_DATE)
    ap.add_argument("--write-rows", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=None, help="results JSON path (refused with --box)")
    ap.add_argument("--boot-reps", type=int, default=BOOT_REPS)
    ap.add_argument("--qhat-boot-reps", type=int, default=QHAT_BOOT_REPS)
    args = ap.parse_args(argv)
    if args.box and (args.out or args.write_rows):
        ap.error("--box writes nothing: aggregates go to stdout")

    result: dict[str, Any] = {
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds")
    }
    rows: list[dict[str, Any]] | None = None
    if args.box or args.ledger:
        from src.trade import market_trade_report as report  # noqa: PLC0415

        conn = report.open_canonical_ledger() if args.box else open_ledger_copy(args.ledger)
        if conn is None:
            result["available"] = False
            result["reason"] = "no_market_trade_ledger_on_this_host"
        else:
            try:
                groups, meta = ledger_groups(conn, args.since)
            finally:
                conn.close()
            rows, audit = price_groups(groups, archived_boards(args.archive_dir))
            audit = {**meta, **audit}
            if args.write_rows:
                write_rows(rows, args.write_rows, audit=audit)
            label = (
                "D-BOX (canonical ledger, read-only)"
                if args.box
                else "D-EXPORT (exported ledger copy, read-only)"
            )
            result.update(
                run(
                    rows,
                    label=label,
                    audit=audit,
                    boot_reps=args.boot_reps,
                    qhat_reps=args.qhat_boot_reps,
                )
            )
    elif args.rows:
        rows = read_rows(args.rows)
        sidecar = Path(str(args.rows) + ".audit.json")
        audit = json.loads(sidecar.read_text(encoding="utf-8")) if sidecar.is_file() else {}
        result.update(
            run(
                rows,
                label=audit.pop("dataLabel", "priced rows file"),
                audit={"rows": len(rows), **audit},
                boot_reps=args.boot_reps,
                qhat_reps=args.qhat_boot_reps,
            )
        )
    elif args.own_league:
        groups, oaudit = own_league_groups(args.own_league)
        rows, paudit = price_groups(groups, archived_boards(args.archive_dir))
        label = "D-OWN (tracked dynasty_main snapshot; one league; not decisive)"
        audit = {**oaudit, **paudit}
        if args.write_rows:
            write_rows(rows, args.write_rows, audit={**audit, "dataLabel": label})
        result.update(
            run(
                rows,
                label=label,
                audit=audit,
                boot_reps=args.boot_reps,
                qhat_reps=args.qhat_boot_reps,
            )
        )
    if args.power:
        result["powerAnalysis"] = power_analysis()
        result["r1FalsePositiveCheck"] = r1_false_positive_check()
    if args.box:
        result["deployedCodeSha"] = _deployed_sha()
        denied = GUARD.denied() if GUARD else []
        net = [d for d in denied if d["event"].startswith("socket.")]
        fatal = [d for d in denied if not d["event"].startswith("socket.")]
        result["readOnlyGuard"] = {
            "installed": bool(GUARD and GUARD.installed()),
            "refusedWriteOrProcessAttempts": len(fatal),
            "refusedWriteOrProcessEvents": sorted({d["event"] for d in fatal}),
            "refusedNetworkAttempts": len(net),
        }
    else:
        result["codeSha"] = _code_sha()
    assert_aggregate_only(result)
    text = json.dumps(result, indent=1, sort_keys=False, default=_json_default)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    if result.get("available") is False:
        return 2
    # Box: a refused write or process start fails the run (exit 3), as in Phase 3.
    return 3 if args.box and result["readOnlyGuard"]["refusedWriteOrProcessAttempts"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
