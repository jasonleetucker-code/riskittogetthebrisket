"""W13-F003 research study: BDVM signal saturation (OFFLINE, NOT ACTIVATED).

What this is
============
An offline, deterministic study of why the BDVM market-signal layer reads
STRONG_SELL on 570 of 676 market-anchored rows of the audit's pinned run, and
how a set of candidate corrections behave on IDENTICAL inputs.  It writes a
JSON report (and optionally a per-player CSV).  It changes nothing: it does not
import ``src/bdvm`` (the code it evaluates), it writes no file a served path
reads, and it touches no flag, parameter or threshold.

Proposal document: ``docs/valuation/methodology_proposals/W13_F003_BDVM_SIGNAL_SATURATION.md``.

Inputs (all tracked in git, all point-in-time)
==============================================
* ``docs/master-site-audit/evidence/W13/engine-live-run.json`` -- the audit's
  recorded BDVM run (asOf 2026-08-04, contract generated 2026-08-04T20:12Z):
  per-player fundamental DV, served ``tradeValue``, recorded market anchor,
  liquidity and collapse probability.  ``data/bdvm/projections/`` is box-local
  and gitignored, so this frozen run is the only reproducible BDVM board.
* ``config/bdvm/params_v1.json`` -- thresholds and scale constants, read as
  plain JSON (never through the production loader).
* ``exports/archive/dynasty_export_*.zip`` -- the committed daily exports.
  Only their ``site_raw/ktcSfTep.csv`` and ``site_raw/idpTradeCalc.csv`` are
  read, and only for snapshots dated AFTER the signal date, as OUTCOMES.  No
  candidate is fitted on anything later than the signal date.

Candidates (all computed here, independently of the production functions)
=========================================================================
* ``C0`` incumbent -- ``alpha = round((TV_balanced - market) x liquidity, 1)``
  through the production ladder (+/-400 / +/-900, collapse escalation, the
  STRONG_BUY liquidity gate).  Re-derived here; the test proves it reproduces
  the production ``market_comparison`` + ``buy_hold_sell`` counts exactly.
* ``C1`` spec-calibrated stud exponent -- BDVM spec section 6.6 says of
  ``gamma``: "Calibrate so your model's top-30 spacing matches market
  spacing".  ``gamma*`` is the least-squares slope of log market spacing on
  log DV spacing over the rank-matched top 30; ``TV' = 9800 (DV/DVmax)^gamma*``
  is used for the gap only.
* ``C2`` pooled rank-quantile map -- ``TV'`` is the market value at TV's own
  mid-rank percentile within the market-anchored board (offense and IDP
  pooled), so the gap measures rank disagreement in market units.
* ``C3`` per-market rank-quantile map -- as C2, mapped separately within the
  KTC-anchored (offense) and IDPTC-anchored (IDP) populations.
* ``C4`` percentile thresholds -- the incumbent alpha with labels assigned by
  fixed shares (10 / 15 / 50 / 15 / 10).  A comparator: it forces a balanced
  distribution by construction, which the owner directive warns against.
* ``C5`` uncertainty band -- the C2 map extended to BDVM's own p20 / p85
  band (``range.floor_p20`` / ``range.ceiling_p85``): BUY when the market sits
  below the mapped floor, SELL when above the mapped ceiling, else HOLD.  The
  threshold is the model's own stated uncertainty instead of a fixed number of
  points.  Three states only (the band supports a direction, not a strength).

Evaluation (the T6 test of the BDVM spec, shortened)
====================================================
Outcome = relative market change after the signal date: ``log(end / start)``
minus the median of that quantity within the same market source, at 30, 60
and 90 days.  ``start`` is the recorded market value the signal saw; ``end``
comes from the first archive dated on or after the target date.  A player
absent from the end snapshot (it publishes a top-N only) is CENSORED: his end
value is set to that file's minimum (an upper bound) and flagged; a
complete-case variant is reported beside it.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import sys
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

# Name normalisation only (the canonical name owner) -- used to join the
# outcome archive by name.  Not part of anything this study evaluates.
from src.utils.name_clean import normalize_player_name  # noqa: E402

DEFAULT_EVIDENCE = REPO / "docs" / "master-site-audit" / "evidence" / "W13" / "engine-live-run.json"
DEFAULT_PARAMS = REPO / "config" / "bdvm" / "params_v1.json"
DEFAULT_ARCHIVE = REPO / "exports" / "archive"

SIGNAL_DATE = "20260804"  # asOf of the recorded run
HORIZONS: tuple[tuple[int, str], ...] = ((30, "20260903"), (60, "20261003"), (90, "20261102"))
MARKET_SOURCES = ("ktcSfTep", "idpTradeCalc")
LABELS = ("STRONG_BUY", "BUY", "HOLD", "SELL", "STRONG_SELL")
BUY_SIDE = frozenset({"STRONG_BUY", "BUY"})
SELL_SIDE = frozenset({"SELL", "STRONG_SELL"})
CANDIDATES = ("C0", "C1", "C2", "C3", "C4", "C5")
C4_SHARES = (0.10, 0.15, 0.50, 0.15, 0.10)  # STRONG_SELL, SELL, HOLD, BUY, STRONG_BUY
GAMMA_FIT_TOP_K = 30
THRESHOLD_MULTIPLIERS = (0.5, 1.0, 1.5, 2.0, 3.0)
GROUP_ORDER = ("QB", "RB", "WR", "TE", "DL", "LB", "DB")


# ---------------------------------------------------------------------------
# small numeric helpers (deterministic, numpy only)
# ---------------------------------------------------------------------------
def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def average_ranks(x: Sequence[float]) -> np.ndarray:
    """1-based average ranks (ties share the mean rank)."""
    a = np.asarray(x, dtype=float)
    n = len(a)
    order = np.argsort(a, kind="mergesort")
    sa = a[order]
    starts = np.flatnonzero(np.r_[True, sa[1:] != sa[:-1]])
    counts = np.diff(np.r_[starts, n])
    ranks = np.empty(n, dtype=float)
    ranks[order] = np.repeat(starts + (counts + 1) / 2.0, counts)
    return ranks


def spearman(x: Sequence[float], y: Sequence[float]) -> float:
    rx = average_ranks(x)
    ry = average_ranks(y)
    if rx.std() == 0 or ry.std() == 0:
        return float("nan")
    return float(np.corrcoef(rx, ry)[0, 1])


def partial_spearman(x: Sequence[float], y: Sequence[float], z: Sequence[float]) -> float:
    """Rank correlation of x and y after linearly removing rank(z) from both."""
    rx, ry, rz = average_ranks(x), average_ranks(y), average_ranks(z)
    design = np.column_stack([np.ones(len(rz)), rz])
    ex = rx - design @ np.linalg.lstsq(design, rx, rcond=None)[0]
    ey = ry - design @ np.linalg.lstsq(design, ry, rcond=None)[0]
    if ex.std() == 0 or ey.std() == 0:
        return float("nan")
    return float(np.corrcoef(ex, ey)[0, 1])


def quantile_map(values: Sequence[float], reference: Sequence[float]) -> np.ndarray:
    """Map each value to the reference distribution at the value's mid-rank percentile.

    ``p_i = (rank_i - 0.5) / n`` with average ranks; the reference order statistic
    ``r_(k)`` sits at ``(k + 0.5) / m``; linear interpolation between, clamped at
    the ends.  Monotone non-decreasing in ``values``; ties map to one value.
    """
    v = np.asarray(values, dtype=float)
    ref = np.sort(np.asarray(reference, dtype=float))
    p = (average_ranks(v) - 0.5) / len(v)
    pos = (np.arange(len(ref)) + 0.5) / len(ref)
    return np.interp(p, pos, ref)


def r(x: float | None, nd: int = 4) -> float | None:
    if x is None:
        return None
    if isinstance(x, float) and math.isnan(x):
        return None
    return round(float(x), nd)


def quantiles(x: Sequence[float], qs: Iterable[float] = (10, 25, 50, 75, 90)) -> dict[str, float]:
    arr = np.asarray(x, dtype=float)
    return {f"p{int(q)}": r(float(np.percentile(arr, q)), 1) for q in qs}


# ---------------------------------------------------------------------------
# inputs
# ---------------------------------------------------------------------------
def load_params(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    th = raw["market"]["signal_thresholds"]
    return {
        "strong_buy_alpha": float(th["strong_buy_alpha"]),
        "buy_alpha": float(th["buy_alpha"]),
        "sell_alpha": float(th["sell_alpha"]),
        "strong_sell_alpha": float(th["strong_sell_alpha"]),
        "strong_buy_min_liquidity": float(th["strong_buy_min_liquidity"]),
        "liquidity_clip_lo": float(raw["market"]["liquidity"]["clip_lo"]),
        "target_top_value": float(raw["scale"]["target_top_value"]),
        "stud_gamma": float(raw["scale"]["stud_gamma"]),
    }


def load_rows(evidence_path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Market-anchored player rows from the recorded run, plus run-level facts."""
    data = json.loads(evidence_path.read_text(encoding="utf-8"))
    players = data["players"]
    dv_max = max(float(p["fundamental"]["balanced"]) for p in players)
    rows: list[dict[str, Any]] = []
    no_market = 0
    for p in players:
        m = p.get("market") or {}
        if m.get("marketValue") is None:
            no_market += 1
            continue
        reasons = list((p.get("quality") or {}).get("reasons") or [])
        rows.append(
            {
                "playerId": str(p.get("playerId") or ""),
                "name": p["name"],
                "group": p["group"],
                "source": m["marketSource"],
                "dv": float(p["fundamental"]["balanced"]),
                "tv": float(p["tradeValue"]["balanced"]),
                "floorP20": float((p.get("range") or {}).get("floor_p20") or 0.0),
                "ceilingP85": float((p.get("range") or {}).get("ceiling_p85") or 0.0),
                "market": float(m["marketValue"]),
                "liquidity": None if m.get("liquidity") is None else float(m["liquidity"]),
                "pCollapse": (p.get("probs") or {}).get("p_value_collapse_1y"),
                "smallSample": "small_nfl_sample" in reasons,
                "anyProxy": bool((p.get("projection") or {}).get("anyProxy")),
                "recordedSignal": (p.get("signal") or {}).get("signal"),
            }
        )
    rows.sort(key=lambda row: (row["name"], row["playerId"]))
    meta = data.get("meta") or {}
    facts = {
        "asOf": meta.get("asOf"),
        "contractGeneratedAt": meta.get("contractGeneratedAt"),
        "paramSetId": meta.get("paramSetId"),
        "pricedPlayers": len(players),
        "noMarketRows": no_market,
        "marketAnchoredRows": len(rows),
        "dvMaxAllPriced": dv_max,
        "projectionSources": sorted(
            {s for p in players for s in ((p.get("projection") or {}).get("sources") or [])}
        ),
    }
    return rows, facts


# ---------------------------------------------------------------------------
# the incumbent ladder, re-derived (independent of src/bdvm/market.py)
# ---------------------------------------------------------------------------
def effective_liquidity(row: dict[str, Any], params: dict[str, Any]) -> float:
    liq = row["liquidity"]
    return float(liq) if liq is not None else params["liquidity_clip_lo"]


def ladder(alpha: float, row: dict[str, Any], params: dict[str, Any], scale: float = 1.0) -> str:
    """The production signal ladder, with thresholds optionally scaled by ``scale``."""
    liq = row["liquidity"]
    if alpha > params["buy_alpha"] * scale:
        if (
            alpha > params["strong_buy_alpha"] * scale
            and liq is not None
            and liq > params["strong_buy_min_liquidity"]
        ):
            return "STRONG_BUY"
        return "BUY"
    if alpha < params["sell_alpha"] * scale:
        if alpha < params["strong_sell_alpha"] * scale:
            return "STRONG_SELL"
        pc = row["pCollapse"]
        if pc is not None and pc > 0.5:
            return "STRONG_SELL"
        return "SELL"
    return "HOLD"


def alphas_for(tv_prime: Sequence[float], rows: list[dict[str, Any]], params: dict[str, Any]):
    return np.array(
        [
            round((float(t) - row["market"]) * effective_liquidity(row, params), 1)
            for t, row in zip(tv_prime, rows)
        ]
    )


def fit_gamma(dv: np.ndarray, market: np.ndarray, top_k: int) -> float:
    """Least-squares exponent so rank-matched top-k DV spacing matches market spacing."""
    d = np.sort(dv)[::-1][:top_k]
    m = np.sort(market)[::-1][:top_k]
    d = d / d[0]
    m = m / m[0]
    keep = (d > 0) & (m > 0)
    ld = np.log(d[keep][1:])
    lm = np.log(m[keep][1:])
    return float((ld * lm).sum() / (ld * ld).sum())


def candidate_tv(rows: list[dict[str, Any]], params: dict[str, Any], dv_max: float) -> dict:
    tv = np.array([row["tv"] for row in rows])
    dv = np.array([row["dv"] for row in rows])
    market = np.array([row["market"] for row in rows])
    src = np.array([row["source"] for row in rows])
    gamma_star = fit_gamma(dv, market, GAMMA_FIT_TOP_K)
    c1 = params["target_top_value"] * (dv / dv_max) ** gamma_star
    c2 = quantile_map(tv, market)
    c3 = np.zeros(len(rows))
    for s in MARKET_SOURCES:
        mask = src == s
        if mask.any():
            c3[mask] = quantile_map(tv[mask], market[mask])
    return {"C0": tv, "C1": c1, "C2": c2, "C3": c3, "gammaStar": gamma_star}


def percentile_labels(alpha: np.ndarray) -> list[str]:
    cuts = np.cumsum(C4_SHARES)[:-1] * 100.0
    q = np.percentile(alpha, cuts)
    out = []
    for a in alpha:
        if a <= q[0]:
            out.append("STRONG_SELL")
        elif a <= q[1]:
            out.append("SELL")
        elif a < q[2]:
            out.append("HOLD")
        elif a < q[3]:
            out.append("BUY")
        else:
            out.append("STRONG_BUY")
    return out


def extend_map(tv: np.ndarray, mapped: np.ndarray):
    """The C2 map as a function of any TV-scale input (clamped at the board ends)."""
    order = np.argsort(tv, kind="mergesort")
    xs, idx = np.unique(tv[order], return_index=True)
    ys = mapped[order][idx]
    return lambda x: np.interp(np.asarray(x, dtype=float), xs, ys)


def band_labels(rows: list[dict[str, Any]], tv: np.ndarray, mapped: np.ndarray):
    """C5: market outside BDVM's own mapped p20/p85 band -> directional call."""
    to_market = extend_map(tv, mapped)
    lo = to_market([row["floorP20"] for row in rows])
    hi = to_market([row["ceilingP85"] for row in rows])
    market = np.array([row["market"] for row in rows])
    labels = []
    score = np.zeros(len(rows))
    for i, m in enumerate(market):
        if m < lo[i]:
            labels.append("BUY")
            score[i] = math.log(lo[i] / m)
        elif m > hi[i]:
            labels.append("SELL")
            score[i] = math.log(hi[i] / m) if hi[i] > 0 else -math.inf
        else:
            labels.append("HOLD")
    finite = np.isfinite(score)
    if not finite.all():
        score[~finite] = score[finite].min() - 1.0
    return labels, score, lo, hi


def run_candidates(rows: list[dict[str, Any]], params: dict[str, Any], dv_max: float) -> dict:
    tvs = candidate_tv(rows, params, dv_max)
    alphas: dict[str, np.ndarray] = {}
    labels: dict[str, list[str]] = {}
    for c in ("C0", "C1", "C2", "C3"):
        alphas[c] = alphas_for(tvs[c], rows, params)
        labels[c] = [ladder(a, row, params) for a, row in zip(alphas[c], rows)]
    alphas["C4"] = alphas["C0"]
    labels["C4"] = percentile_labels(alphas["C0"])
    labels["C5"], alphas["C5"], band_lo, band_hi = band_labels(rows, tvs["C0"], tvs["C2"])
    return {
        "tv": tvs,
        "alpha": alphas,
        "labels": labels,
        "gammaStar": tvs["gammaStar"],
        "bandLo": band_lo,
        "bandHi": band_hi,
    }


def label_counts(labels: Iterable[str]) -> dict[str, int]:
    c = Counter(labels)
    return {k: int(c.get(k, 0)) for k in LABELS}


# ---------------------------------------------------------------------------
# diagnostics
# ---------------------------------------------------------------------------
def diagnostics(rows: list[dict[str, Any]], res: dict, params: dict[str, Any], dv_max: float):
    n = len(rows)
    tv = res["tv"]["C0"]
    market = np.array([row["market"] for row in rows])
    dv = np.array([row["dv"] for row in rows])
    gap = tv - market
    groups = np.array([row["group"] for row in rows])
    src = np.array([row["source"] for row in rows])
    liq = np.array([effective_liquidity(row, params) for row in rows])
    small = np.array([row["smallSample"] for row in rows])

    board = {
        "n": n,
        "tvMedian": r(float(np.median(tv)), 1),
        "marketMedian": r(float(np.median(market)), 1),
        "gapMedian": r(float(np.median(gap)), 1),
        "gapQuantiles": quantiles(gap),
        "tvQuantiles": quantiles(tv),
        "marketQuantiles": quantiles(market),
        "shareGapNegative": r(float(np.mean(gap < 0))),
        "spearmanTvMarket": r(spearman(tv, market)),
        "spearmanIncumbentAlphaMarket": r(spearman(res["alpha"]["C0"], market)),
        "rowsTvBelow100": int(np.sum(tv < 100)),
        "rowsDvZero": int(np.sum(dv <= 0)),
        "marketMin": r(float(market.min()), 1),
        "alphaMedianIncumbent": r(float(np.median(res["alpha"]["C0"])), 1),
    }

    per_group = {}
    for g in GROUP_ORDER:
        mask = groups == g
        if not mask.any():
            continue
        per_group[g] = {
            "n": int(mask.sum()),
            "market": "idpTradeCalc" if g in ("DL", "LB", "DB") else "ktcSfTep",
            "tvMedian": r(float(np.median(tv[mask])), 1),
            "marketMedian": r(float(np.median(market[mask])), 1),
            "gapMedian": r(float(np.median(gap[mask])), 1),
            "shareGapNegative": r(float(np.mean(gap[mask] < 0))),
            "spearmanTvMarket": r(spearman(tv[mask], market[mask])),
            "signals": {
                c: label_counts(np.array(res["labels"][c])[mask].tolist()) for c in CANDIDATES
            },
        }

    per_market = {}
    for s in MARKET_SOURCES:
        mask = src == s
        per_market[s] = {
            "n": int(mask.sum()),
            "spearmanTvMarket": r(spearman(tv[mask], market[mask])),
            "signals": {
                c: label_counts(np.array(res["labels"][c])[mask].tolist()) for c in CANDIDATES
            },
        }

    order = np.argsort(-market, kind="mergesort")
    deciles = []
    for k in range(10):
        idx = order[k * n // 10 : (k + 1) * n // 10]
        deciles.append(
            {
                "decile": k + 1,
                "marketMin": r(float(market[idx].min()), 1),
                "marketMax": r(float(market[idx].max()), 1),
                "tvMedian": r(float(np.median(tv[idx])), 1),
                "ratioTvToMarketMedian": r(float(np.median(tv[idx] / market[idx]))),
                "gapMedian": r(float(np.median(gap[idx])), 1),
                "incumbentStrongSellShare": r(
                    float(np.mean([res["labels"]["C0"][i] == "STRONG_SELL" for i in idx]))
                ),
                "c2StrongSellShare": r(
                    float(np.mean([res["labels"]["C2"][i] == "STRONG_SELL" for i in idx]))
                ),
            }
        )

    # gap = shape + rank: shape depends only on TV's own rank (a level/curve
    # artefact); rank is the disagreement in ordering, in market units.
    mapped = res["tv"]["C2"]
    shape = tv - mapped
    rank_part = mapped - market
    shape_alpha = np.array([round(s * lq, 1) for s, lq in zip(shape, liq)])
    decomposition = {
        "shapeMedian": r(float(np.median(shape)), 1),
        "rankMedian": r(float(np.median(rank_part)), 1),
        "shapeShareNegative": r(float(np.mean(shape < 0))),
        "varGap": r(float(np.var(gap)), 1),
        "varShape": r(float(np.var(shape)), 1),
        "varRank": r(float(np.var(rank_part)), 1),
        "covShapeRank": r(float(np.cov(shape, rank_part, bias=True)[0, 1]), 1),
        "signalsIfShapeOnly": label_counts(
            ladder(a, row, params) for a, row in zip(shape_alpha, rows)
        ),
    }

    sd = np.sort(dv)[::-1]
    sm = np.sort(market)[::-1]
    st = np.sort(tv)[::-1]
    spacing = {
        "dvRatioTop10": [r(float(x), 3) for x in sd[:10] / sd[0]],
        "marketRatioTop10": [r(float(x), 3) for x in sm[:10] / sm[0]],
        "servedTvRatioTop10": [r(float(x), 3) for x in st[:10] / st[0]],
        "gammaPrior": params["stud_gamma"],
        "gammaFitByTopK": {
            str(k): r(fit_gamma(dv, market, k)) for k in (GAMMA_FIT_TOP_K, 50, 100, n)
        },
    }

    no_liq = {
        c: label_counts(
            ladder(round((t - row["market"]) * 1.0, 1), row, params)
            for t, row in zip(res["tv"][c], rows)
        )
        for c in ("C0", "C2")
    }
    liquidity = {
        "quantiles": quantiles(liq, (0, 10, 50, 90, 100)),
        "unmeasuredRows": int(sum(row["liquidity"] is None for row in rows)),
        "signalsWithLiquidityForcedTo1": no_liq,
    }

    threshold_sensitivity = {}
    for c in ("C0", "C2"):
        threshold_sensitivity[c] = {
            str(mult): label_counts(
                ladder(a, row, params, scale=mult) for a, row in zip(res["alpha"][c], rows)
            )
            for mult in THRESHOLD_MULTIPLIERS
        }

    missing = {}
    for flag, mask in (("smallNflSample", small), ("adequateSample", ~small)):
        missing[flag] = {
            "n": int(mask.sum()),
            "signals": {
                c: label_counts(np.array(res["labels"][c])[mask].tolist())
                for c in ("C0", "C2", "C5")
            },
        }
    missing["proxyRows"] = int(sum(row["anyProxy"] for row in rows))

    return {
        "board": board,
        "perGroup": per_group,
        "perMarket": per_market,
        "marketDeciles": deciles,
        "decomposition": decomposition,
        "topSpacing": spacing,
        "liquidity": liquidity,
        "thresholdSensitivity": threshold_sensitivity,
        "missingDataSensitivity": missing,
    }


# ---------------------------------------------------------------------------
# outcomes (evaluation only)
# ---------------------------------------------------------------------------
def archive_on_or_after(archive_dir: Path, date: str) -> Path | None:
    for p in sorted(archive_dir.glob("dynasty_export_*.zip")):
        if p.name.split("_")[2] >= date:
            return p
    return None


def load_source_values(zip_path: Path, source: str) -> dict[str, float]:
    with zipfile.ZipFile(zip_path) as zf:
        text = zf.read(f"site_raw/{source}.csv").decode("utf-8")
    out: dict[str, float] = {}
    for rec in csv.DictReader(io.StringIO(text)):
        try:
            value = float(rec["value"])
        except (TypeError, ValueError, KeyError):
            continue
        key = normalize_player_name(rec.get("name") or "")
        if key:
            out[key] = value
    return out


def outcomes(rows: list[dict[str, Any]], zip_path: Path) -> tuple[np.ndarray, np.ndarray, dict]:
    boards = {s: load_source_values(zip_path, s) for s in MARKET_SOURCES}
    end = np.zeros(len(rows))
    censored = np.zeros(len(rows), dtype=bool)
    for i, row in enumerate(rows):
        board = boards[row["source"]]
        v = board.get(normalize_player_name(row["name"]))
        if v is None:
            v = min(board.values())
            censored[i] = True
        end[i] = v
    start = np.array([row["market"] for row in rows])
    raw = np.log(end / start)
    src = np.array([row["source"] for row in rows])
    y = raw.copy()
    drift = {}
    for s in MARKET_SOURCES:
        mask = src == s
        med = float(np.median(raw[mask]))
        drift[s] = r(med)
        y[mask] = raw[mask] - med
    return y, censored, {"drift": drift, "censored": int(censored.sum())}


def score_metrics(score, labels, y, market, src) -> dict[str, Any]:
    score = np.asarray(score, dtype=float)
    lab = np.asarray(labels)
    buy = np.isin(lab, list(BUY_SIDE))
    sell = np.isin(lab, list(SELL_SIDE))
    actionable = int(buy.sum() + sell.sum())
    hits = int(np.sum(y[buy] > 0) + np.sum(y[sell] < 0))
    off = src == "ktcSfTep"
    by_label = {}
    for k in LABELS:
        mask = lab == k
        by_label[k] = {
            "n": int(mask.sum()),
            "meanRelChange": r(float(y[mask].mean())) if mask.any() else None,
        }
    return {
        "spearman": r(spearman(score, y)),
        "partialSpearmanGivenMarketRank": r(partial_spearman(score, y, market)),
        "spearmanOffense": r(spearman(score[off], y[off])),
        "spearmanIdp": r(spearman(score[~off], y[~off])),
        "byLabel": by_label,
        "actionable": actionable,
        "hitRate": r(hits / actionable) if actionable else None,
        "longShortSpread": (
            r(float(y[buy].mean() - y[sell].mean())) if buy.any() and sell.any() else None
        ),
    }


BOOTSTRAP_CHALLENGERS = ("C2", "C5")


def bootstrap(scores: dict[str, np.ndarray], y, market, n_boot: int, seed: int) -> dict[str, Any]:
    """Paired bootstrap over players: each challenger against the incumbent C0.

    The same resample indices are used for every score, so the difference
    intervals are paired.
    """
    rng = np.random.default_rng(seed)
    n = len(y)
    names = ("C0", *BOOTSTRAP_CHALLENGERS)
    arrs = {c: np.asarray(scores[c], dtype=float) for c in names}
    rho: dict[str, list[float]] = {c: [] for c in names}
    par: dict[str, list[float]] = {c: [] for c in names}
    for _ in range(n_boot):
        idx = rng.integers(0, n, n)
        for c in names:
            rho[c].append(spearman(arrs[c][idx], y[idx]))
            par[c].append(partial_spearman(arrs[c][idx], y[idx], market[idx]))

    def ci(v) -> list[float | None]:
        arr = np.asarray(v, dtype=float)
        return [r(float(np.percentile(arr, 2.5))), r(float(np.percentile(arr, 97.5)))]

    out: dict[str, Any] = {"resamples": n_boot, "seed": seed}
    for c in names:
        out[f"spearman{c}CI95"] = ci(rho[c])
        out[f"partial{c}CI95"] = ci(par[c])
    for c in BOOTSTRAP_CHALLENGERS:
        out[f"spearmanDiff{c}MinusC0CI95"] = ci(np.subtract(rho[c], rho["C0"]))
        out[f"partialDiff{c}MinusC0CI95"] = ci(np.subtract(par[c], par["C0"]))
    return out


def evaluate(rows, res, archive_dir: Path, n_boot: int, seed: int) -> tuple[dict, dict]:
    market = np.array([row["market"] for row in rows])
    src = np.array([row["source"] for row in rows])
    tv = res["tv"]["C0"]
    out: dict[str, Any] = {}
    hashes: dict[str, str] = {}
    for days, target in HORIZONS:
        zp = archive_on_or_after(archive_dir, target)
        if zp is None:
            out[str(days)] = {"available": False, "reason": f"no archive on/after {target}"}
            continue
        hashes[zp.name] = sha256_file(zp)
        y, censored, facts = outcomes(rows, zp)
        horizon: dict[str, Any] = {
            "available": True,
            "archive": zp.name,
            **facts,
            "baselines": {
                "negMarketValue": r(spearman(-market, y)),
                "servedTvAlone": r(spearman(tv, y)),
            },
            "candidates": {},
            "completeCase": {},
        }
        for c in CANDIDATES:
            horizon["candidates"][c] = score_metrics(
                res["alpha"][c], res["labels"][c], y, market, src
            )
            keep = ~censored
            horizon["completeCase"][c] = {
                "n": int(keep.sum()),
                "spearman": r(spearman(np.asarray(res["alpha"][c])[keep], y[keep])),
                "partialSpearmanGivenMarketRank": r(
                    partial_spearman(np.asarray(res["alpha"][c])[keep], y[keep], market[keep])
                ),
            }
        if n_boot > 0:
            horizon["bootstrapVsIncumbent"] = bootstrap(
                res["alpha"], y, market, n_boot, seed + days
            )
        out[str(days)] = horizon
    return out, hashes


# ---------------------------------------------------------------------------
# per-player impacts
# ---------------------------------------------------------------------------
def player_table(rows, res) -> list[dict[str, Any]]:
    table = []
    for i, row in enumerate(rows):
        table.append(
            {
                "playerId": row["playerId"],
                "name": row["name"],
                "group": row["group"],
                "marketSource": row["source"],
                "market": r(row["market"], 1),
                "servedTvBalanced": r(row["tv"], 1),
                "tvC1": r(float(res["tv"]["C1"][i]), 1),
                "tvC2": r(float(res["tv"]["C2"][i]), 1),
                "tvC3": r(float(res["tv"]["C3"][i]), 1),
                "alphaC0": r(float(res["alpha"]["C0"][i]), 1),
                "alphaC1": r(float(res["alpha"]["C1"][i]), 1),
                "alphaC2": r(float(res["alpha"]["C2"][i]), 1),
                "alphaC3": r(float(res["alpha"]["C3"][i]), 1),
                "signalC0": res["labels"]["C0"][i],
                "signalC1": res["labels"]["C1"][i],
                "signalC2": res["labels"]["C2"][i],
                "signalC3": res["labels"]["C3"][i],
                "signalC4": res["labels"]["C4"][i],
                "bandLoC5": r(float(res["bandLo"][i]), 1),
                "bandHiC5": r(float(res["bandHi"][i]), 1),
                "signalC5": res["labels"]["C5"][i],
                "smallNflSample": row["smallSample"],
            }
        )
    return table


def transition_matrix(a: Sequence[str], b: Sequence[str]) -> dict[str, dict[str, int]]:
    m = {x: {y: 0 for y in LABELS} for x in LABELS}
    for x, y in zip(a, b):
        m[x][y] += 1
    return m


# ---------------------------------------------------------------------------
def build_report(
    evidence: Path, params_path: Path, archive_dir: Path, n_boot: int, seed: int
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    params = load_params(params_path)
    rows, facts = load_rows(evidence)
    res = run_candidates(rows, params, facts["dvMaxAllPriced"])
    recorded = label_counts(row["recordedSignal"] for row in rows)
    evaluation, archive_hashes = evaluate(rows, res, archive_dir, n_boot, seed)
    table = player_table(rows, res)
    report = {
        "study": "W13-F003 BDVM signal saturation",
        "activationStatus": "NOT ACTIVATED (research only)",
        "signalDate": SIGNAL_DATE,
        "inputs": {
            "evidence": {
                "path": evidence.relative_to(REPO).as_posix()
                if evidence.is_relative_to(REPO)
                else evidence.name,
                "sha256": sha256_file(evidence),
            },
            "params": {
                "path": params_path.relative_to(REPO).as_posix()
                if params_path.is_relative_to(REPO)
                else params_path.name,
                "sha256": sha256_file(params_path),
            },
            "outcomeArchives": archive_hashes,
        },
        "run": {**facts, "dvMaxAllPriced": r(facts["dvMaxAllPriced"])},
        "params": params,
        "recordedSignalCounts": recorded,
        "gammaStarTop30": r(res["gammaStar"]),
        "signalCounts": {c: label_counts(res["labels"][c]) for c in CANDIDATES},
        "strongSellShare": {
            c: r(label_counts(res["labels"][c])["STRONG_SELL"] / len(rows)) for c in CANDIDATES
        },
        "actionableShare": {
            c: r(sum(1 for x in res["labels"][c] if x in BUY_SIDE or x in SELL_SIDE) / len(rows))
            for c in CANDIDATES
        },
        "transitionIncumbentToC2": transition_matrix(res["labels"]["C0"], res["labels"]["C2"]),
        # Rows whose label would become a DIFFERENT actionable state at a
        # methodology switch: each is one transition alert under
        # src/api/bdvm_signal_alerts.py unless the alert state is re-seeded.
        "alertTransitionsAtSwitch": {
            c: sum(
                1
                for a, b in zip(res["labels"]["C0"], res["labels"][c])
                if b != a and (b in BUY_SIDE or b in SELL_SIDE)
            )
            for c in CANDIDATES
            if c != "C0"
        },
        "diagnostics": diagnostics(rows, res, params, facts["dvMaxAllPriced"]),
        "evaluation": evaluation,
    }
    return report, table


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    ap.add_argument("--params", type=Path, default=DEFAULT_PARAMS)
    ap.add_argument("--archive-dir", type=Path, default=DEFAULT_ARCHIVE)
    ap.add_argument("--out", type=Path, default=None, help="write the JSON report here")
    ap.add_argument("--players-csv", type=Path, default=None, help="write per-player impacts")
    ap.add_argument("--bootstrap", type=int, default=2000, help="paired resamples (0 = off)")
    ap.add_argument("--seed", type=int, default=20261107)
    args = ap.parse_args(argv)

    report, table = build_report(
        args.evidence, args.params, args.archive_dir, args.bootstrap, args.seed
    )
    text = json.dumps(report, indent=1, sort_keys=True, ensure_ascii=False) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    if args.players_csv:
        args.players_csv.parent.mkdir(parents=True, exist_ok=True)
        with args.players_csv.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(table[0].keys()), lineterminator="\n")
            writer.writeheader()
            writer.writerows(table)
    summary = report["signalCounts"]
    print(
        "signal counts: " + "; ".join(f"{c} {summary[c]}" for c in CANDIDATES),
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
