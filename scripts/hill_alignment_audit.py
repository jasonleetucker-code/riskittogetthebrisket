#!/usr/bin/env python3
"""Hill / native-source alignment audit (read-only; V2-5 of the valuation map).

Separates three questions the 2026-09-30 replay's ``board.nativeVsHill`` metric
mixed together:

1. **price-scale mismatch** -- a value-direct source's native value against the
   live Hill master at the source's rank counted in the SAME population the
   master assumes;
2. **rank-population mismatch** -- how much of the replay's ratio comes from the
   population a live rank is counted in (board picks interleaved with players,
   board coverage vs the vendor's own list, combined offense+IDP+picks pools);
3. **genuine source disagreement** -- the source's ORDER against a
   leave-that-source-out board (scale-free, rank space), never against a
   consensus containing it.

Then evaluates at most three predeclared candidates (incumbent; c1 KTC re-scaled
by a monotone map from KTC's own rank->value curve onto the Hill scale; c2 KTC
through rank->Hill) with full rebuilds through the production pipeline, under
diagnostic patches that are restored after each build. Nothing here writes a
production constant, the model registry, or ``data_contract``.

Usage (repo root):
    python scripts/hill_alignment_audit.py \\
        --json docs/valuation/evidence/hill-alignment-2026-10-01/audit.json \\
        --markdown docs/valuation/evidence/hill-alignment-2026-10-01/audit.md

Exit codes: 0 ok; 2 a declared invariant failed (reported in the output, never
silently passed).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import statistics
import sys
import tempfile
import time
import zipfile
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import fit_hill_curve_percentile as fitter  # noqa: E402
from scripts import hill_board_guard as guard  # noqa: E402
from src.api import data_contract as dc  # noqa: E402
from src.api import value_replay as vr  # noqa: E402
from src.canonical import player_valuation as pv  # noqa: E402
from src.canonical.rank_coordinates import curve_for_pool  # noqa: E402
from src.canonical.tail_policy import clamp_percentile  # noqa: E402

AUDIT_SCHEMA = "hill-alignment-audit/v1"
KTC_KEYS = ("ktcCrowdSfTep", "ktcTradesSfTep")
IDPTC = "idpTradeCalc"
VALUE_SOURCES = (*KTC_KEYS, IDPTC)
CSV_DIR = REPO_ROOT / "CSVs" / "site_raw"
POLICY_PATH = REPO_ROOT / "config" / "model_registry" / "hill_autopilot_policy.json"
REGISTRY_PATH = REPO_ROOT / "config" / "model_registry" / "hill_scope_masters.json"
RANK_BANDS: tuple[tuple[int, int | None], ...] = (
    (1, 50),
    (51, 100),
    (101, 200),
    (201, 300),
    (301, 400),
    (401, None),
)
#: Bands the scale verdict is taken over (the V2-5 measurement's range).
VERDICT_BANDS = ("51-100", "101-200", "201-300", "301-400")
HAMPEL_VARIANTS: dict[str, dict[str, float]] = {
    "floor_750": {"min_threshold": 750.0},
    "floor_1000_incumbent": {"min_threshold": 1000.0},
    "floor_1250": {"min_threshold": 1250.0},
    "floor_1500": {"min_threshold": 1500.0},
    "mad_only_no_floor": {"min_threshold": 0.0},
    "mad_scaled_1p4826_no_floor": {"min_threshold": 0.0, "mad_scale": 1.4826},
}
_PICK_NAME = re.compile(r"^\s*20\d\d\s+(early|mid|late|round|pick|\d)", re.IGNORECASE)

# ── Declared BEFORE any candidate is computed (also README §1; git order) ───────
DECLARATION: dict[str, Any] = {
    "questions": [
        "scale: native normalized value / Hill(rank in the population the curve assumes)",
        "population: Hill(population-correct rank) / Hill(live rank) -- why the replay's "
        "nativeVsHill differs from the scale term",
        "disagreement: log2(source players-only rank / leave-that-source-out board "
        "players-only rank) -- scale-free; KTC is compared with BOTH KTC families removed",
    ],
    "populations": {
        "ktc_live": "board rows the source covers, offense players AND picks interleaved "
        "(Phase 1 offense scope admits PICK) -> OFFENSE master",
        "ktc_players": "board offense players the source covers -> OFFENSE master "
        "(the population every OFFENSE rank voter and holdout is ranked in)",
        "ktc_vendor": "players in the vendor CSV, picks removed -> OFFENSE master "
        "(board-coverage effect isolated)",
        "idptc_live": "board offense+IDP+picks pool -> GLOBAL master",
        "idptc_offense": "IDPTC's board offense players -> OFFENSE master",
        "idptc_idp": "IDPTC's board IDP players -> IDP master (CIRCULAR: the IDP master "
        "is fit on IDPTC's own IDP slice; reported, never used for a verdict)",
        "picks": "NON-COMPARABLE: no Hill master prices pick ranks for these sources; "
        "picks take the anchor path",
    },
    "breakdowns": [
        "position",
        "assetClass",
        "rank band on the population-correct rank (1-50, 51-100, 101-200, 201-300, "
        "301-400, 401+)",
        "row weight state (NORMAL / DEGRADED / SEVERELY_DEGRADED) + source subset freshness",
        "independent source count (<=2, 3-4, 5-8, 9+)",
    ],
    "verdicts": {
        "scale_mismatch_confirmed": "population-correct median scale ratio outside "
        "[0.90, 1.10] in >= 3 of the bands 51-100..301-400",
        "population_share": "mean log2(population factor) / mean log2(live ratio) over "
        "ranks 51-400; >= 0.5 means the replay metric was mostly population",
        "stable": "across >= 5 archive dates, max - min of the daily median vendor-"
        "population scale ratio per band <= 0.10",
    },
    "hampel_variants": sorted(HAMPEL_VARIANTS),
    "hampel_reported": [
        "observations excluded",
        "rows with any exclusion",
        "KTC Crowd / KTC Trades / both / IDPTC exclusions",
        "rows changed and top-200 membership changes vs the incumbent",
    ],
    "candidates": {
        "incumbent": "production as built",
        "c1_ktc_scale_map": "each KTC board's values pass a monotone map V' = H_off("
        "F_ktc^-1(v)), F_ktc = that board's own Hill fit (fitter grid, players-only top "
        "400, canonical /499 coordinate) on the CURRENT snapshot only; H_off = live "
        "OFFENSE master. Keeps KTC's local spacing around its own curve; applied to "
        "every KTC row incl. picks. Circularity: the target master trains on 6 boards, "
        "one of them KTC base (same crowd) -- not a consensus containing KTC Crowd as a "
        "vote, but not KTC-free either",
        "c2_ktc_rank_hill": "KTC Crowd + Trades leave _VALUE_BASED_SOURCES (corrected "
        "native_values_as_ranks; IDPTC stays value-direct)",
    },
    "candidate_metrics": [
        "rows changed; median / p90 / max |delta %| (Hill board guard definitions)",
        "top-25 / top-50 / top-100 / top-200 membership vs incumbent",
        "KTC and total outlier exclusions (diagnostic, NOT an objective)",
        "KTC family leverage: |V - V(no KTC)| / V(no KTC) on rows KTC covers",
        "sparse rows (<= 2 independent families): changed, median |delta %|",
        "contract structural errors",
        "build seconds",
        "Coker + data-chosen contrast set (regression examples only)",
    ],
    "candidate_gates": {
        "board_impact": "every Hill board guard rail from config/model_registry/"
        "hill_autopilot_policy.json::boardImpact",
        "no_new_structural_errors": "structural validation errors not above incumbent",
        "leverage": "KTC family leverage p90 <= 1.25x incumbent (a candidate may not "
        "buy alignment by handing KTC more control)",
        "cost": "build seconds <= 1.5x incumbent median",
    },
    "never": [
        "select or tune toward KTC Market parity (reported as context only)",
        "treat fewer outlier exclusions as success",
        "promote: any numeric calibration is a challenger for the Hill Autopilot / model "
        "registry, which this audit does not touch",
    ],
    "holdout": "point-in-time only where the archive genuinely carries the inputs: "
    "exports/archive zips carry the KTC Crowd / KTC Trades / IDPTC CSVs, not every "
    "voter, so a full point-in-time BOARD rebuild is out of reach here; the scale "
    "ratio and the c1 map are tested forward in time (fit on day d, scored on d+7)",
}


# ── Small pure helpers (tested) ─────────────────────────────────────────────────


def band_of(rank: int | None) -> str | None:
    if not rank or rank < 1:
        return None
    for lo, hi in RANK_BANDS:
        if hi is None or rank <= hi:
            return f"{lo}-{hi}" if hi is not None else f"{lo}+"
    return None


def coverage_band(n: int | None) -> str:
    if n is None:
        return "unknown"
    if n <= 2:
        return "<=2"
    if n <= 4:
        return "3-4"
    if n <= 8:
        return "5-8"
    return "9+"


def dense_ranks(items: Iterable[tuple[str, float, str]]) -> dict[str, int]:
    """``{key: dense rank}`` ordered exactly like Phase 1: value desc, name asc."""
    ordered = sorted(items, key=lambda t: (-t[1], t[2].lower()))
    out: dict[str, int] = {}
    prev: float | None = None
    rank = 0
    for idx, (key, value, _name) in enumerate(ordered):
        if prev is None or value != prev:
            rank = idx + 1
            prev = value
        out[key] = rank
    return out


def hill_value(rank: float, curve: tuple[float, float]) -> int:
    """Production rank -> value (canonical coordinate + production rounding)."""
    c, s = curve
    return pv.percentile_to_value(pv.rank_to_percentile(float(rank)), midpoint=c, slope=s)


def is_pick_name(name: str) -> bool:
    return bool(_PICK_NAME.match(str(name or "")))


def q(values: list[float], p: float) -> float | None:
    if not values:
        return None
    xs = sorted(values)
    pos = p * (len(xs) - 1)
    lo, hi = math.floor(pos), math.ceil(pos)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def summarize(values: list[float]) -> dict[str, Any]:
    """Median / IQR of ratios plus the mean of log2 (the additive scale)."""
    vals = [v for v in values if isinstance(v, (int, float)) and v > 0]
    if not vals:
        return {"n": 0}
    logs = [math.log2(v) for v in vals]
    return {
        "n": len(vals),
        "median": round(statistics.median(vals), 3),
        "p25": round(q(vals, 0.25), 3),
        "p75": round(q(vals, 0.75), 3),
        "meanLog2": round(statistics.fmean(logs), 4),
    }


def grouped(obs: list[dict], by: str, metric: str) -> dict[str, Any]:
    groups: dict[str, list[float]] = defaultdict(list)
    for o in obs:
        key = o.get(by)
        if key is None:
            continue
        groups[str(key)].append(o.get(metric))
    order = [b for b in (band_of(lo) for lo, _ in RANK_BANDS) if b]
    keys = sorted(groups, key=lambda k: (order.index(k) if k in order else 99, k))
    return {k: summarize(groups[k]) for k in keys}


# ── Curve fitting (the fitter's exact objective, vectorized) ────────────────────


def fit_hill(pairs: list[tuple[float, float]]) -> tuple[float, float, float]:
    """``fitter._fit`` computed with numpy: same grids, refinement and tie order.

    Parity with the fitter is pinned by a test; if numpy is unavailable the
    fitter's own pure-Python ``_fit`` is used.
    """
    try:
        import numpy as np
    except ImportError:  # pragma: no cover - numpy ships with the repo's deps
        return fitter._fit(pairs)
    ps = np.array(
        [clamp_percentile(p, reference_n=pv.PERCENTILE_REFERENCE_N) for p, _ in pairs], dtype=float
    )
    vs = np.array([v for _, v in pairs], dtype=float)

    def errs(cs: np.ndarray, ss: np.ndarray) -> np.ndarray:
        with np.errstate(divide="ignore", over="ignore", invalid="ignore"):
            ratio = ps[None, :] / cs[:, None]
            pred = 9999.0 / (1.0 + ratio[:, None, :] ** ss[None, :, None])
        pred = np.where(ps[None, None, :] == 0.0, 9999.0, pred)
        return ((vs[None, None, :] - pred) ** 2).sum(axis=2)

    c_grid = np.array([0.005 + 0.005 * i for i in range(100)])
    s_grid = np.array([0.4 + 0.02 * i for i in range(106)])
    grid_err = errs(c_grid, s_grid)
    ci, si = np.unravel_index(int(np.argmin(grid_err)), grid_err.shape)
    best = (float(grid_err[ci, si]), float(c_grid[ci]), float(s_grid[si]))
    _e0, c0, s0 = best
    for d_c in (-0.002, -0.001, 0.0, 0.001, 0.002):
        for d_s in (-0.01, -0.005, 0.0, 0.005, 0.01):
            c, s = c0 + d_c, s0 + d_s
            if c <= 0 or s <= 0:
                continue
            err = float(errs(np.array([c]), np.array([s]))[0, 0])
            if err < best[0]:
                best = (err, c, s)
    return best[1], best[2], best[0] / len(pairs)


def read_board_csv(path: Path, col: str | None = None) -> list[tuple[str, float]]:
    """``[(name, value)]`` with a positive numeric value, CSV order kept.

    Same filter as ``fitter._load_values`` (value > 0) but with an explicit UTF-8
    decode, which the fitter leaves to the platform default."""
    out: list[tuple[str, float]] = []
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        cols = reader.fieldnames or []
        if col is None:
            col = (
                "value" if "value" in cols else next((c for c in cols if "val" in c.lower()), None)
            )
        for row in reader:
            try:
                v = float(row.get(col) or 0)
            except (TypeError, ValueError):
                continue
            if v > 0:
                out.append((str(row.get("name") or row.get("Name") or ""), v))
    return out


def curve_fit_for_board(values: list[float], top_n: int = 400) -> dict[str, Any]:
    vals = sorted(values, reverse=True)[:top_n]
    pairs = fitter._percentile_pairs(vals)
    c, s, mse = fit_hill(pairs)
    return {"n": len(pairs), "c": round(c, 4), "s": round(s, 4), "rmse": round(mse**0.5, 1)}


def scale_map(c_src: float, s_src: float, master: tuple[float, float]) -> Callable[[float], float]:
    """c1: native normalized value -> its own curve's percentile -> master value."""
    c_m, s_m = master

    def apply(v_norm: float) -> float:
        if v_norm >= 9999.0:
            return 9999.0
        if v_norm <= 0:
            return 0.0
        p = c_src * ((9999.0 / v_norm) - 1.0) ** (1.0 / s_src)
        p = clamp_percentile(p, reference_n=pv.PERCENTILE_REFERENCE_N)
        return 9999.0 if p == 0.0 else 9999.0 / (1.0 + (p / c_m) ** s_m)

    return apply


def write_mapped_csv(src: Path, dst: Path, fn: Callable[[float], float]) -> int:
    """Copy ``src`` with its value column passed through ``fn`` (on the 0-9999
    normalized scale). Returns rows rewritten. Order-preserving by construction."""
    with src.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        cols = list(reader.fieldnames or [])
        rows = list(reader)
    vals = [float(r["value"]) for r in rows if r.get("value") not in (None, "")]
    top = max(vals)
    n = 0
    for r in rows:
        raw = r.get("value")
        if raw in (None, ""):
            continue
        v = float(raw)
        if v > 0:
            r["value"] = f"{fn(v / top * 9999.0):.4f}"
            n += 1
    with dst.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    return n


# ── Part A: scale vs population ─────────────────────────────────────────────────


def _rows(contract: Mapping[str, Any]) -> list[dict]:
    return [r for r in contract.get("playersArray") or [] if r.get("displayName")]


def _site_max(rows: list[dict]) -> dict[str, float]:
    site_max, _suppressed, _diag = dc._partition_value_source_ranges(rows)
    return site_max


def scale_population_observations(
    contract: Mapping[str, Any],
    vendor_players: Mapping[str, list[float]],
    *,
    challenger_offense: tuple[float, float] | None = None,
) -> list[dict]:
    """One observation per (row, value source) that voted value-direct."""
    rows = _rows(contract)
    site_max = _site_max(rows)
    off_curve = curve_for_pool("offense")
    idp_curve = curve_for_pool("idp")
    out: list[dict] = []
    for key in VALUE_SOURCES:
        covered = []
        for r in rows:
            m = (r.get("sourceRankMeta") or {}).get(key)
            raw = (r.get("canonicalSiteValues") or {}).get(key)
            if not m or raw is None:
                continue
            try:
                raw_f = float(raw)
            except (TypeError, ValueError):
                continue
            if raw_f <= 0:
                continue
            covered.append((r, m, raw_f))
        name = lambda r: str(r.get("canonicalName") or r.get("displayName") or "")  # noqa: E731
        players_off = dense_ranks(
            (r["displayName"], v, name(r))
            for r, _m, v in covered
            if r.get("assetClass") == "offense"
        )
        players_idp = dense_ranks(
            (r["displayName"], v, name(r)) for r, _m, v in covered if r.get("assetClass") == "idp"
        )
        vendor = sorted(set(vendor_players.get(key) or []), reverse=True)
        for r, m, raw_f in covered:
            if m.get("valueContributionPath") != "value_direct" or not site_max.get(key):
                continue
            native = raw_f / site_max[key] * 9999.0
            live_rank = int(m["effectiveRank"])
            live_pool = str(m.get("rankCoordinatePool") or "")
            h_live = hill_value(live_rank, curve_for_pool(live_pool))
            ac = r.get("assetClass")
            obs: dict[str, Any] = {
                "source": key,
                "asset": r["displayName"],
                "assetClass": ac,
                "position": "PICK" if ac == "pick" else r.get("position"),
                "native": round(native, 2),
                "liveRank": live_rank,
                "livePool": live_pool,
                "hillLive": h_live,
                "ratioLive": native / h_live if h_live else None,
                "weightState": r.get("sourceWeightState"),
                "coverageBand": coverage_band(r.get("independentSourceCount")),
                "hampelDropped": bool(m.get("hampelDropped")),
                "comparable": ac in ("offense", "idp"),
            }
            if ac == "offense":
                pop_rank, curve, pop = players_off[r["displayName"]], off_curve, "offense_players"
            elif ac == "idp":
                pop_rank, curve, pop = players_idp[r["displayName"]], idp_curve, "idp_players"
            else:
                pop_rank, curve, pop = None, None, "non_comparable_pick"
            obs["population"] = pop
            obs["popRank"] = pop_rank
            obs["band"] = band_of(pop_rank) if pop_rank else None
            obs["circular"] = key == IDPTC and ac == "idp"
            if pop_rank:
                h_pop = hill_value(pop_rank, curve)
                obs["hillPop"] = h_pop
                obs["ratioPop"] = native / h_pop if h_pop else None
                obs["populationFactor"] = h_pop / h_live if h_live else None
                # Vendor population only where the vendor list is single-market
                # (IDPTC's CSV carries no positions, so its list mixes IDP in).
                if ac == "offense" and vendor and key in KTC_KEYS:
                    v_rank = 1 + sum(1 for x in vendor if x > raw_f)
                    h_v = hill_value(v_rank, off_curve)
                    obs["vendorRank"] = v_rank
                    obs["ratioVendor"] = native / h_v if h_v else None
                if challenger_offense and ac == "offense":
                    h_c = hill_value(pop_rank, challenger_offense)
                    obs["ratioPopChallenger"] = native / h_c if h_c else None
            out.append(obs)
    return out


def scale_population_summary(obs: list[dict]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in VALUE_SOURCES:
        mine = [o for o in obs if o["source"] == key]
        comparable = [o for o in mine if o["comparable"]]
        offense = [o for o in comparable if o["assetClass"] == "offense"]
        entry: dict[str, Any] = {
            "observations": len(mine),
            "nonComparablePicks": sum(1 for o in mine if not o["comparable"]),
            "byBand": {
                metric: grouped(offense, "band", metric)
                for metric in (
                    "ratioLive",
                    "ratioPop",
                    "populationFactor",
                    "ratioVendor",
                    "ratioPopChallenger",
                )
            },
            "byPosition": grouped(comparable, "position", "ratioPop"),
            "byAssetClass": grouped(comparable, "assetClass", "ratioPop"),
            "byWeightState": grouped(offense, "weightState", "ratioPop"),
            "byCoverage": grouped(offense, "coverageBand", "ratioPop"),
        }
        if key == IDPTC:
            idp = [o for o in comparable if o["assetClass"] == "idp"]
            entry["idpByBandCircular"] = grouped(idp, "band", "ratioPop")
            entry["liveByBandAllClasses"] = grouped(
                [dict(o, liveBand=band_of(o["liveRank"])) for o in mine], "liveBand", "ratioLive"
            )
        mid = [o for o in offense if o["band"] in VERDICT_BANDS]
        live_logs = [math.log2(o["ratioLive"]) for o in mid if o.get("ratioLive")]
        pop_logs = [math.log2(o["populationFactor"]) for o in mid if o.get("populationFactor")]
        band_medians = {
            b: entry["byBand"]["ratioPop"].get(b, {}).get("median") for b in VERDICT_BANDS
        }
        outside = [b for b, m in band_medians.items() if m is not None and not 0.9 <= m <= 1.1]
        mean_live = statistics.fmean(live_logs) if live_logs else None
        entry["verdict"] = {
            "bandsOutsideTolerance": outside,
            "scaleMismatchConfirmed": len(outside) >= 3,
            "meanLog2Live": round(mean_live, 4) if mean_live is not None else None,
            "meanLog2PopulationFactor": round(statistics.fmean(pop_logs), 4) if pop_logs else None,
            "populationShare": round(statistics.fmean(pop_logs) / mean_live, 3)
            if pop_logs and mean_live
            else None,
        }
        out[key] = entry
    return out


def vendor_player_values(csv_dir: Path = CSV_DIR) -> dict[str, list[float]]:
    out: dict[str, list[float]] = {}
    for key in VALUE_SOURCES:
        path = csv_dir / f"{key}.csv"
        if path.exists():
            out[key] = [v for n, v in read_board_csv(path) if not is_pick_name(n)]
    return out


def population_composition(contract: Mapping[str, Any]) -> dict[str, Any]:
    """How many picks sit inside each value source's live rank pool, and above
    which players -- the mechanism behind the population factor."""
    rows = _rows(contract)
    out = {}
    for key in VALUE_SOURCES:
        live = [
            (r.get("assetClass"), (r.get("sourceRankMeta") or {}).get(key, {}).get("effectiveRank"))
            for r in rows
            if key in (r.get("sourceRankMeta") or {})
        ]
        out[key] = {
            "rowsInPool": len(live),
            "byClass": {
                ac: sum(1 for a, _r in live if a == ac) for ac in sorted({a for a, _ in live if a})
            },
            "picksInTop400": sum(1 for a, rk in live if a == "pick" and rk and rk <= 400),
            "idpInTop400": sum(1 for a, rk in live if a == "idp" and rk and rk <= 400),
        }
    return out


def native_curve_shapes(csv_dir: Path = CSV_DIR) -> dict[str, Any]:
    """Every native-value board's own Hill fit, players only, canonical coordinate.

    Answers whether KTC's spacing is an outlier AMONG VALUE MARKETS (genuine
    spacing disagreement) or only against the rank-voter consensus."""
    boards = {
        "ktcCrowdSfTep": ("live value voter", "ktcCrowdSfTep.csv"),
        "ktcTradesSfTep": ("live value voter", "ktcTradesSfTep.csv"),
        "ktc (base)": ("OFFENSE trainer; non-voting", "ktc.csv"),
        "dynastyDaddySf": ("OFFENSE trainer; rank voter", "dynastyDaddySf.csv"),
        "dynastyNerdsSfTep": ("OFFENSE trainer; rank voter", "dynastyNerdsSfTep.csv"),
        "yahooBoone": ("OFFENSE trainer; rank voter", "yahooBoone.csv"),
        "fantasyProsFitzmaurice": ("OFFENSE trainer; rank voter", "fantasyProsFitzmaurice.csv"),
        "draftSharksSf": ("OFFENSE trainer; rank voter", "draftSharksSf.csv"),
        "fantasyCalc": ("OFFENSE holdout; rank voter", "fantasyCalc.csv"),
        "otcffbSf": ("OFFENSE holdout; rank voter", "otcffbSf.csv"),
        "pfkDynasty": ("OFFENSE holdout; rank voter", "pfkDynasty.csv"),
        "fantasyNavigatorSf": (
            "OFFENSE holdout; rank voter (ktcCrowd family)",
            "fantasyNavigatorSf.csv",
        ),
        "dlfValuesSfTep": ("non-voting; measurement gate pending", "dlfValuesSfTep.csv"),
    }
    cols = {
        "dynastyNerdsSfTep.csv": "Value",
        "yahooBoone.csv": "boone_value",
        "draftSharksSf.csv": "3D Value +",
    }
    out: dict[str, Any] = {}
    for label, (role, fname) in boards.items():
        path = csv_dir / fname
        if not path.exists():
            out[label] = {"role": role, "status": "csv_missing"}
            continue
        named = read_board_csv(path, cols.get(fname))
        players = [v for n, v in named if not is_pick_name(n)]
        vals_all = [v for _n, v in named]
        top = sorted(named, key=lambda t: -t[1])[:400]
        picks_in_top = sum(1 for n, _v in top if is_pick_name(n))
        entry = {"role": role, "playersOnly": curve_fit_for_board(players)}
        if picks_in_top:
            entry["withPicksAsTheFitterReads"] = curve_fit_for_board(vals_all)
            entry["picksInTop400"] = picks_in_top
        out[label] = entry
    c, s = curve_for_pool("offense")
    out["_liveOffenseMaster"] = {"c": c, "s": s}
    return out


def curve_values(
    c: float, s: float, grid: Iterable[float] = (0.02, 0.05, 0.1, 0.2, 0.3, 0.5, 0.7)
) -> dict:
    return {str(p): round(9999.0 / (1.0 + (p / c) ** s)) for p in grid}


# ── Part B: disagreement against leave-that-source-out boards ───────────────────


def loo_disagreement(
    base: Mapping[str, Any],
    loo: Mapping[str, Any],
    source_key: str,
    scale_obs: list[dict] | None = None,
) -> dict[str, Any]:
    """The source's own players-only rank against the LOO board's players-only rank.

    Rank space is scale-free, so this is order disagreement only. For value-direct
    sources the value-space split is also reported: log2(native / LOO) =
    log2(native / Hill(pop rank)) [scale] + log2(Hill(pop rank) / LOO) [order on the
    Hill scale]. The LOO board is itself on the Hill scale (rank voters vote through
    it), so the second term cannot judge the curve -- only the first can."""
    loo_rows = {r["displayName"]: r for r in _rows(loo)}
    by_obs = {o["asset"]: o for o in scale_obs or [] if o["source"] == source_key}
    src_def = next((s for s in dc._RANKING_SOURCES if s.get("key") == source_key), {})
    if src_def.get("needs_rookie_translation"):
        # A rookie-only list orders one draft class; its translated rank is a
        # ladder position, not an opinion about every veteran. Not comparable.
        return {"rows": 0, "status": "non_comparable_rookie_only_list"}
    src_items = [
        (r, (r.get("sourceRankMeta") or {})[source_key])
        for r in _rows(base)
        if r.get("assetClass") == "offense" and source_key in (r.get("sourceRankMeta") or {})
    ]
    priced = [
        (r, m)
        for r, m in src_items
        if isinstance((loo_rows.get(r["displayName"]) or {}).get("rankDerivedValue"), (int, float))
        and loo_rows[r["displayName"]]["rankDerivedValue"] > 0
    ]
    loo_unpriced = len(src_items) - len(priced)
    # Both ranks are counted over the SAME rows -- the offense players this source
    # covers and the LOO board prices -- so a shallow list is not penalised for
    # the players it never ranked.
    own_rank = dense_ranks(
        (r["displayName"], -float(m["effectiveRank"]), r["displayName"]) for r, m in priced
    )
    loo_rank = dense_ranks(
        (
            r["displayName"],
            float(loo_rows[r["displayName"]]["rankDerivedValue"]),
            str(r.get("canonicalName") or r["displayName"]),
        )
        for r, _m in priced
    )
    obs = []
    for r, m in priced:
        name = r["displayName"]
        lv = loo_rows[name]["rankDerivedValue"]
        o = {
            "asset": name,
            "band": band_of(own_rank[name]),
            "rankRatio": own_rank[name] / loo_rank[name],
            "contributionOverLoo": (m.get("valueContribution") or 0) / lv,
            "hampelDropped": bool(m.get("hampelDropped")),
        }
        so = by_obs.get(name)
        if so and so.get("hillPop"):
            o["scaleTerm"] = so["native"] / so["hillPop"]
            o["orderTermOnHill"] = so["hillPop"] / lv
            o["nativeOverLoo"] = so["native"] / lv
        obs.append(o)
    dropped = [o for o in obs if o["hampelDropped"]]
    out = {
        "rows": len(obs),
        "looUnpriced": loo_unpriced,
        "outlierDroppedRows": {
            "n": len(dropped),
            "rankRatio": summarize([o["rankRatio"] for o in dropped]),
            "scaleTerm": summarize([o["scaleTerm"] for o in dropped if "scaleTerm" in o]),
            "orderTermOnHill": summarize(
                [o["orderTermOnHill"] for o in dropped if "orderTermOnHill" in o]
            ),
        },
        "rankRatioByBand": grouped(obs, "band", "rankRatio"),
        "shareRankOffByMoreThan41pct": round(
            sum(1 for o in obs if abs(math.log2(o["rankRatio"])) > 0.5) / len(obs), 3
        )
        if obs
        else None,
        "contributionOverLooByBand": grouped(obs, "band", "contributionOverLoo"),
        "hampelDropRate": round(sum(o["hampelDropped"] for o in obs) / len(obs), 3)
        if obs
        else None,
    }
    if any("scaleTerm" in o for o in obs):
        out["valueSplitByBand"] = {
            metric: grouped([o for o in obs if metric in o], "band", metric)
            for metric in ("nativeOverLoo", "scaleTerm", "orderTermOnHill")
        }
    return out


# ── Part C/D: outlier census and candidate evaluation ──────────────────────────


def hampel_census(contract: Mapping[str, Any]) -> dict[str, Any]:
    per_source: dict[str, int] = defaultdict(int)
    ktc_bands: dict[str, int] = defaultdict(int)
    rows_any = 0
    both_ktc = 0
    for r in _rows(contract):
        meta = r.get("sourceRankMeta") or {}
        dropped = [k for k, m in meta.items() if m.get("hampelDropped")]
        if dropped:
            rows_any += 1
        for k in dropped:
            per_source[k] += 1
            if k in KTC_KEYS:
                ktc_bands[band_of(meta[k].get("effectiveRank")) or "?"] += 1
        if set(KTC_KEYS) <= set(dropped):
            both_ktc += 1
    return {
        "ktcDropsByLiveRankBand": dict(ktc_bands),
        "observationsExcluded": sum(per_source.values()),
        "rowsWithAnyExclusion": rows_any,
        "ktcCrowd": per_source.get("ktcCrowdSfTep", 0),
        "ktcTrades": per_source.get("ktcTradesSfTep", 0),
        "bothKtc": both_ktc,
        "idpTradeCalc": per_source.get(IDPTC, 0),
        "bySource": dict(sorted(per_source.items(), key=lambda kv: -kv[1])),
    }


def board_impact(
    before: Mapping[str, Any], after: Mapping[str, Any], policy: Mapping[str, Any]
) -> dict:
    """The Hill board guard's metrics and gates (``scripts/hill_board_guard.py``),
    computed on two in-memory contracts; parity with the guard is test-pinned."""
    rb = {r["displayName"]: r for r in _rows(before)}
    ra = {r["displayName"]: r for r in _rows(after)}
    common = sorted(set(rb) & set(ra))
    value_pct, rank_shift = [], []
    newly_unpriced = before_priced = 0
    for key in common:
        old_v, new_v = rb[key].get("rankDerivedValue"), ra[key].get("rankDerivedValue")
        if isinstance(old_v, (int, float)):
            before_priced += 1
            if not isinstance(new_v, (int, float)):
                newly_unpriced += 1
            elif old_v:
                value_pct.append(abs(float(new_v) - float(old_v)) / abs(float(old_v)))
        old_r, new_r = rb[key].get("canonicalConsensusRank"), ra[key].get("canonicalConsensusRank")
        if isinstance(old_r, (int, float)) and isinstance(new_r, (int, float)):
            rank_shift.append(abs(float(new_r) - float(old_r)))
    metrics = {
        "rows": len(common),
        "unpricedFraction": newly_unpriced / max(1, before_priced),
        "medianAbsPctValueChange": float(statistics.median(value_pct)) if value_pct else 0.0,
        "p90AbsPctValueChange": guard._q(value_pct, 0.90),
        "maxAbsPctValueChange": max(value_pct, default=0.0),
        "medianAbsRankShift": float(statistics.median(rank_shift)) if rank_shift else 0.0,
        "p90AbsRankShift": guard._q(rank_shift, 0.90),
        "top25Overlap": len(guard._top(rb, 25) & guard._top(ra, 25)),
        "top100Overlap": len(guard._top(rb, 100) & guard._top(ra, 100)),
    }
    gates = {
        "same_row_set": set(rb) == set(ra),
        "unpriced": metrics["unpricedFraction"] <= float(policy["maxUnpricedFraction"]),
        "median_value_change": metrics["medianAbsPctValueChange"]
        <= float(policy["maxMedianAbsPctValueChange"]),
        "p90_value_change": metrics["p90AbsPctValueChange"]
        <= float(policy["maxP90AbsPctValueChange"]),
        "max_value_change": metrics["maxAbsPctValueChange"]
        <= float(policy["maxSingleAbsPctValueChange"]),
        "top25_overlap": metrics["top25Overlap"] >= int(policy["minTop25Overlap"]),
        "top100_overlap": metrics["top100Overlap"] >= int(policy["minTop100Overlap"]),
        "median_rank_shift": metrics["medianAbsRankShift"]
        <= float(policy["maxMedianAbsRankShift"]),
        "p90_rank_shift": metrics["p90AbsRankShift"] <= float(policy["maxP90AbsRankShift"]),
    }
    return {"pass": all(gates.values()), "gates": gates, "metrics": metrics}


def _without_picks(contract: Mapping[str, Any]) -> dict[str, Any]:
    """The same board with pick rows removed (a reporting cut, not a rebuild)."""
    return {"playersArray": [r for r in _rows(contract) if r.get("assetClass") != "pick"]}


def subset_freshness(contract: Mapping[str, Any]) -> dict[str, Any]:
    sources = ((contract.get("sourceWeighting") or {}).get("sources")) or {}
    out = {}
    for key in VALUE_SOURCES:
        subsets = (sources.get(key) or {}).get("subsets") or {}
        out[key] = {
            name: {
                k: sub.get(k) for k in ("freshness", "ageHours", "expectedCadenceHours", "state")
            }
            for name, sub in subsets.items()
        }
    return out


def _top_set(contract: Mapping[str, Any], n: int) -> set[str]:
    return {
        r["displayName"]
        for r in _rows(contract)
        if isinstance(r.get("canonicalConsensusRank"), int) and r["canonicalConsensusRank"] <= n
    }


def ktc_leverage(contract: Mapping[str, Any], no_ktc: Mapping[str, Any]) -> dict[str, Any]:
    """|V - V(no KTC)| / V(no KTC) on offense rows KTC voted on."""
    alt = {r["displayName"]: r.get("rankDerivedValue") for r in _rows(no_ktc)}
    lev = []
    for r in _rows(contract):
        meta = r.get("sourceRankMeta") or {}
        if r.get("assetClass") != "offense" or not any(k in meta for k in KTC_KEYS):
            continue
        v, w = r.get("rankDerivedValue"), alt.get(r["displayName"])
        if isinstance(v, (int, float)) and isinstance(w, (int, float)) and w > 0:
            lev.append(abs(v - w) / w)
    return {
        "rows": len(lev),
        "median": round(statistics.median(lev), 4) if lev else None,
        "p90": round(guard._q(lev, 0.90), 4) if lev else None,
        "max": round(max(lev), 4) if lev else None,
    }


def sparse_rows_effect(base: Mapping[str, Any], other: Mapping[str, Any]) -> dict[str, Any]:
    alt = {r["displayName"]: r.get("rankDerivedValue") for r in _rows(other)}
    pct = []
    n = 0
    for r in _rows(base):
        if (r.get("independentSourceCount") or 0) > 2 or r.get("assetClass") == "pick":
            continue
        v, w = r.get("rankDerivedValue"), alt.get(r["displayName"])
        if not isinstance(v, (int, float)) or v <= 0:
            continue
        n += 1
        if isinstance(w, (int, float)) and w != v:
            pct.append(abs(w - v) / v)
    return {
        "sparseRows": n,
        "changed": len(pct),
        "medianAbsPctChanged": round(statistics.median(pct), 4) if pct else 0.0,
        "maxAbsPctChanged": round(max(pct), 4) if pct else 0.0,
    }


def structural_errors(contract: Mapping[str, Any]) -> int | None:
    health = dc.validate_api_data_contract(contract)
    errs = health.get("structuralErrors")
    return len(errs) if isinstance(errs, list) else None


def asset_values(contract: Mapping[str, Any], names: Iterable[str]) -> dict[str, Any]:
    rows = {r["displayName"]: r for r in _rows(contract)}
    return {
        n: {
            "value": (rows.get(n) or {}).get("rankDerivedValue"),
            "rank": (rows.get(n) or {}).get("canonicalConsensusRank"),
            "ktcDropped": [
                k
                for k in KTC_KEYS
                if ((rows.get(n) or {}).get("sourceRankMeta") or {}).get(k, {}).get("hampelDropped")
            ],
        }
        for n in names
    }


# ── Part E: point-in-time holdout of the scale ratio and the c1 map ────────────


def _archive_days(archive: Path) -> list[tuple[str, Path]]:
    by_day: dict[str, Path] = {}
    for z in sorted(archive.glob("dynasty_export_*.zip")):
        try:
            names = zipfile.ZipFile(z).namelist()
        except zipfile.BadZipFile:
            continue
        if all(f"site_raw/{k}.csv" in names for k in KTC_KEYS):
            by_day[z.name.split("_")[2]] = z  # newest bundle of each day wins
    return sorted(by_day.items())


def _zip_board(z: Path, key: str) -> list[tuple[str, float]]:
    with zipfile.ZipFile(z) as zf, tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / f"{key}.csv"
        target.write_bytes(zf.read(f"site_raw/{key}.csv"))
        return read_board_csv(target)


def _vendor_ratio_by_band(values: list[float], curve: tuple[float, float]) -> dict[str, float]:
    vals = sorted(values, reverse=True)
    top = vals[0]
    ranks = dense_ranks((str(i), v, f"{i:06d}") for i, v in enumerate(vals))
    groups: dict[str, list[float]] = defaultdict(list)
    for i, v in enumerate(vals):
        rk = ranks[str(i)]
        b = band_of(rk)
        if b in VERDICT_BANDS:
            groups[b].append((v / top * 9999.0) / hill_value(rk, curve))
    return {b: round(statistics.median(groups[b]), 3) for b in VERDICT_BANDS if groups.get(b)}


def _map_error_by_band(
    values: list[float], fn: Callable[[float], float], curve
) -> dict[str, float]:
    vals = sorted(values, reverse=True)
    top = vals[0]
    ranks = dense_ranks((str(i), v, f"{i:06d}") for i, v in enumerate(vals))
    groups: dict[str, list[float]] = defaultdict(list)
    for i, v in enumerate(vals):
        rk = ranks[str(i)]
        b = band_of(rk)
        mapped = fn(v / top * 9999.0)
        h = hill_value(rk, curve)
        if b in VERDICT_BANDS and mapped > 0 and h > 0:
            groups[b].append(abs(math.log2(mapped / h)))
    return {b: round(statistics.median(groups[b]), 4) for b in VERDICT_BANDS if groups.get(b)}


def archive_holdout(archive: Path, *, horizon_days: int = 7) -> dict[str, Any]:
    days = _archive_days(archive)
    curve = curve_for_pool("offense")
    out: dict[str, Any] = {"dates": [d for d, _ in days], "sources": {}}
    for key in KTC_KEYS:
        daily = {}
        fits = {}
        players_by_day = {}
        for day, z in days:
            players = [v for n, v in _zip_board(z, key) if not is_pick_name(n)]
            if len(players) < 50:
                continue
            players_by_day[day] = players
            daily[day] = _vendor_ratio_by_band(players, curve)
            fits[day] = curve_fit_for_board(players)
        spread = {}
        for b in VERDICT_BANDS:
            series = [daily[d][b] for d in daily if b in daily[d]]
            if series:
                spread[b] = {
                    "days": len(series),
                    "min": min(series),
                    "max": max(series),
                    "range": round(max(series) - min(series), 3),
                }
        stable = bool(spread) and all(
            s["days"] >= 5 and s["range"] <= 0.10 for s in spread.values()
        )
        forward = []
        dates = sorted(players_by_day)
        for i, d in enumerate(dates):
            later = [x for x in dates[i + 1 :] if _days_between(d, x) >= horizon_days]
            if not later:
                continue
            d2 = later[0]
            f = fits[d]
            fn_d = scale_map(f["c"], f["s"], curve)
            f2 = fits[d2]
            fn_same = scale_map(f2["c"], f2["s"], curve)
            forward.append(
                {
                    "fitOn": d,
                    "scoredOn": d2,
                    "outOfSampleMedianAbsLog2ByBand": _map_error_by_band(
                        players_by_day[d2], fn_d, curve
                    ),
                    "inSampleMedianAbsLog2ByBand": _map_error_by_band(
                        players_by_day[d2], fn_same, curve
                    ),
                }
            )
        out["sources"][key] = {
            "days": len(daily),
            "dailyMedianScaleRatioByBand": daily,
            "rangeByBand": spread,
            "stable": stable,
            "ownCurveFitByDay": fits,
            "forwardMapCheck": forward,
        }
    return out


def _days_between(a: str, b: str) -> int:
    from datetime import date

    da = date(int(a[:4]), int(a[4:6]), int(a[6:8]))
    db = date(int(b[:4]), int(b[4:6]), int(b[6:8]))
    return (db - da).days


# ── Orchestration ──────────────────────────────────────────────────────────────


def _timed_build(
    raw: Mapping[str, Any], spec: Mapping[str, Any] | None = None, *, warm: bool = False
):
    """One build and its wall time. ``warm`` builds twice and times the second, so
    a candidate reading new CSV paths is not charged for a cold parse cache."""
    if warm:
        vr.build(raw, spec)
    t0 = time.perf_counter()
    contract = vr.build(raw, spec)
    return contract, time.perf_counter() - t0


def _pending_challenger() -> dict[str, Any] | None:
    """The newest standing OFFENSE challenger in the registry (read-only context)."""
    try:
        blob = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    champion = str(blob.get("championVersion"))
    cands = [
        v
        for v in blob.get("versions") or []
        if v.get("status") in ("challenger", "rejected")
        and "HILL_PERCENTILE_C" in (v.get("params") or {})
        and str(v.get("version")) != champion
    ]
    if not cands:
        return None
    last = cands[-1]
    return {
        "version": last.get("version"),
        "status": last.get("status"),
        "notes": last.get("notes"),
        "c": last["params"]["HILL_PERCENTILE_C"],
        "s": last["params"]["HILL_PERCENTILE_S"],
    }


def run(
    payload_path: Path,
    *,
    archive: Path | None = REPO_ROOT / "exports" / "archive",
    contrast: list[str] | None = None,
    loo_rank_sources: bool = True,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    say = progress or (lambda _m: None)
    raw = json.loads(payload_path.read_text(encoding="utf-8"))
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))["boardImpact"]
    invariants: dict[str, Any] = {}

    live_ctx: list = []
    with vr._recording_league_context(live_ctx):
        base, t_base = _timed_build(raw)
    base_again, t_base2 = _timed_build(raw)
    invariants["rebuild_is_identical"] = vr.board_hash(base) == vr.board_hash(base_again)
    pins = {**vr.pins(payload_path), "liveLeagueContext": live_ctx}
    result: dict[str, Any] = {
        "schema": AUDIT_SCHEMA,
        "declaration": DECLARATION,
        "declarationSha256": hashlib.sha256(
            json.dumps(DECLARATION, sort_keys=True).encode("utf-8")
        ).hexdigest(),
        "pins": pins,
        "boardRows": len(_rows(base)),
        "outputs": {"incumbentBoardSha256": vr.board_hash(base)},
    }

    # Part A ------------------------------------------------------------------
    say("scale vs population")
    challenger = _pending_challenger()
    vendor = vendor_player_values()
    obs = scale_population_observations(
        base,
        vendor,
        challenger_offense=(challenger["c"], challenger["s"]) if challenger else None,
    )
    result["scaleVsPopulation"] = {
        "summary": scale_population_summary(obs),
        "poolComposition": population_composition(base),
        "nativeCurveShapes": native_curve_shapes(),
        "pendingOffenseChallenger": challenger,
        "sourceSubsetFreshness": subset_freshness(base),
        "liveMasters": {
            pool: dict(zip(("c", "s"), curve_for_pool(pool)))
            for pool in ("offense", "shared_market", "idp")
        },
    }
    # Corrected as-ranks rebuild: the direct Hill(live rank) must equal what the
    # pipeline itself stamps when KTC votes through its rank.
    say("c2 / corrected as-ranks rebuild")
    c2, t_c2 = _timed_build(raw, vr.native_values_as_ranks_spec(), warm=True)
    c2_rows = {r["displayName"]: r for r in _rows(c2)}
    agree = disagree = 0
    for o in obs:
        if o["source"] not in KTC_KEYS:
            continue
        m = ((c2_rows.get(o["asset"]) or {}).get("sourceRankMeta") or {}).get(o["source"]) or {}
        if m.get("valueContributionPath") != "rank_hill" or o["position"] == "TE":
            continue
        if abs((m.get("valueContribution") or 0) - o["hillLive"]) <= 1:
            agree += 1
        else:
            disagree += 1
    invariants["direct_hill_matches_pipeline_rank_hill"] = {"agree": agree, "disagree": disagree}
    result["scaleVsPopulation"]["correctedReplayMetric"] = vr.native_vs_hill(base, c2)
    contaminated = vr.build(raw, {"patch": ("_VALUE_BASED_SOURCES", frozenset())})
    idptc_ranks = [
        ((r.get("sourceRankMeta") or {}).get(IDPTC) or {}).get("effectiveRank")
        for r in _rows(contaminated)
        if IDPTC in (r.get("sourceRankMeta") or {})
    ]
    result["scaleVsPopulation"]["replayCounterfactualErratum"] = {
        "what": "the 2026-09-30 native_values_as_ranks emptied _VALUE_BASED_SOURCES; "
        "IDPTC then entered Phase 1c and its native value was decoded as a rank",
        "idptcEffectiveRankMinMax": [min(idptc_ranks), max(idptc_ranks)] if idptc_ranks else None,
        "replayMetricUnderOldPatch": vr.native_vs_hill(base, contaminated).get(IDPTC),
        "boardDiffOldPatch": vr.board_diff(base, contaminated, top=5),
        "boardDiffCorrectedPatch": vr.board_diff(base, c2, top=5),
    }

    # Part B ------------------------------------------------------------------
    say("leave-one-out boards")
    no_ktc, _ = _timed_build(raw, {"disable": list(KTC_KEYS)})
    loo_idptc, _ = _timed_build(raw, {"disable": [IDPTC]})
    disagreement = {key: loo_disagreement(base, no_ktc, key, obs) for key in KTC_KEYS}
    disagreement[IDPTC] = loo_disagreement(base, loo_idptc, IDPTC, obs)
    if loo_rank_sources:
        keys = sorted(
            {
                k
                for r in _rows(base)
                if r.get("assetClass") == "offense"
                for k in (r.get("sourceRankMeta") or {})
            }
            - set(VALUE_SOURCES)
        )
        for key in keys:
            say(f"loo {key}")
            loo, _ = _timed_build(raw, {"disable": [key]})
            d = loo_disagreement(base, loo, key)
            disagreement[key] = {
                k: d[k]
                for k in (
                    "status",
                    "rows",
                    "looUnpriced",
                    "rankRatioByBand",
                    "shareRankOffByMoreThan41pct",
                    "contributionOverLooByBand",
                    "hampelDropRate",
                    "outlierDroppedRows",
                )
                if k in d
            }
    result["disagreement"] = {
        "note": "KTC Crowd and KTC Trades are each compared with a board built WITHOUT "
        "BOTH KTC families (same provider, correlated); IDPTC without IDPTC; every rank "
        "voter without itself.",
        "bySource": disagreement,
    }

    # Part C ------------------------------------------------------------------
    say("outlier filter sensitivity")
    hampel: dict[str, Any] = {"incumbent": hampel_census(base)}
    for name, kw in HAMPEL_VARIANTS.items():
        variant, _ = _timed_build(raw, vr.hampel_threshold_spec(**kw))
        diff = vr.board_diff(base, variant, top=5)
        hampel[name] = {
            **hampel_census(variant),
            "rowsChanged": diff["rowsChanged"],
            "top200MembershipChanges": diff["top200MembershipChanges"],
        }
    off, _ = _timed_build(raw, vr.counterfactual_specs({}, [])["hampel_off"])
    diff = vr.board_diff(base, off, top=5)
    hampel["off"] = {
        **hampel_census(off),
        "rowsChanged": diff["rowsChanged"],
        "top200MembershipChanges": diff["top200MembershipChanges"],
    }
    invariants["hampel_1000_variant_equals_incumbent"] = (
        hampel["floor_1000_incumbent"]["rowsChanged"] == 0
    )
    result["outlierSensitivity"] = hampel

    # Part D ------------------------------------------------------------------
    say("c1 scale map")
    master = curve_for_pool("offense")
    c1_fits: dict[str, Any] = {}
    with tempfile.TemporaryDirectory() as tmp:
        identity_paths, mapped_paths = {}, {}
        for key in KTC_KEYS:
            src = CSV_DIR / f"{key}.csv"
            fit = curve_fit_for_board(vendor[key])
            c1_fits[key] = fit
            ident = Path(tmp) / f"{key}.identity.csv"
            write_mapped_csv(src, ident, lambda v: v)
            identity_paths[key] = ident
            mapped = Path(tmp) / f"{key}.c1.csv"
            write_mapped_csv(src, mapped, scale_map(fit["c"], fit["s"], master))
            mapped_paths[key] = mapped
        ident_board, _ = _timed_build(raw, vr.csv_override_spec(identity_paths))
        invariants["csv_patch_identity_rows_changed"] = vr.board_diff(base, ident_board)[
            "rowsChanged"
        ]
        c1, t_c1 = _timed_build(raw, vr.csv_override_spec(mapped_paths), warm=True)
    names = ["Jalen Coker", *(contrast or [])]
    no_ktc_lev = ktc_leverage(base, no_ktc)
    base_errors = structural_errors(base)
    candidates: dict[str, Any] = {}
    for name, contract, secs in (
        ("incumbent", base, statistics.median([t_base, t_base2])),
        ("c1_ktc_scale_map", c1, t_c1),
        ("c2_ktc_rank_hill", c2, t_c2),
    ):
        impact = board_impact(base, contract, policy)
        lev = ktc_leverage(contract, no_ktc)
        errs = structural_errors(contract)
        entry = {
            "boardSha256": vr.board_hash(contract),
            "boardImpact": impact,
            "boardImpactPlayersOnly": board_impact(
                _without_picks(base), _without_picks(contract), policy
            )["metrics"],
            "boardDiff": vr.board_diff(base, contract, top=10),
            "topOverlap": {
                str(n): len(_top_set(base, n) & _top_set(contract, n)) for n in (25, 50, 100, 200)
            },
            "outliers": hampel_census(contract),
            "ktcLeverage": lev,
            "sparseRows": sparse_rows_effect(base, contract),
            "structuralErrors": errs,
            "buildSeconds": round(secs, 3),
            "assets": asset_values(contract, names),
        }
        if name != "incumbent":
            entry["gates"] = {
                "board_impact": impact["pass"],
                "no_new_structural_errors": errs is not None
                and base_errors is not None
                and errs <= base_errors,
                "leverage": lev["p90"] is not None
                and no_ktc_lev["p90"] is not None
                and lev["p90"] <= 1.25 * no_ktc_lev["p90"],
                "cost": secs <= 1.5 * statistics.median([t_base, t_base2]),
            }
            entry["eligible"] = all(entry["gates"].values())
        candidates[name] = entry
    result["candidates"] = {"c1OwnCurveFits": c1_fits, "results": candidates}

    # Part E ------------------------------------------------------------------
    if archive is not None and archive.is_dir():
        say("archive holdout")
        result["holdout"] = archive_holdout(archive)
    else:
        result["holdout"] = {"status": "insufficient_coverage", "reason": "no archive"}

    result["invariants"] = invariants
    result["invariantsOk"] = (
        invariants["rebuild_is_identical"]
        and invariants["hampel_1000_variant_equals_incumbent"]
        and invariants["csv_patch_identity_rows_changed"] == 0
        and invariants["direct_hill_matches_pipeline_rank_hill"]["disagree"] == 0
    )
    return result


# ── Markdown ───────────────────────────────────────────────────────────────────


def _fmt(x: Any) -> str:
    if x is None:
        return "—"
    if isinstance(x, float):
        return f"{x:.3f}"
    return str(x)


def _band_table(rows: dict[str, dict[str, dict]], metrics: list[str]) -> list[str]:
    bands = [b for b in (band_of(lo) for lo, _ in RANK_BANDS) if b]
    lines = ["| band | " + " | ".join(metrics) + " |", "|---|" + "---|" * len(metrics)]
    for b in bands:
        cells = []
        for m in metrics:
            s = (rows.get(m) or {}).get(b) or {}
            cells.append(f"{_fmt(s.get('median'))} (n {s.get('n', 0)})" if s.get("n") else "—")
        lines.append(f"| {b} | " + " | ".join(cells) + " |")
    return lines


def render_markdown(res: Mapping[str, Any]) -> str:
    p = res["pins"]
    out = [
        "# Hill / native-source alignment audit — tables",
        "",
        f"Schema `{res['schema']}`; declaration sha256 `{res['declarationSha256'][:16]}…`; "
        f"invariants ok: **{res['invariantsOk']}**.",
        "",
        "## Pins",
        "",
        f"- code revision `{p['codeRevision']}` (dirty: {p['workingTreeDirty']})",
        f"- payload `{p['payload']['path']}` sha256 `{p['payload']['sha256'][:16]}…`, "
        f"scrape {p['payload']['scrapeTimestamp']}",
        f"- source CSVs: {len(p['sourceCsvs'])} hashed; config files: {len(p['config'])}; "
        f"freshness state files: {len(p['freshnessState'])}",
        f"- local league snapshots: {len(p['localLeagueSnapshots']['files'])} file(s) "
        "(gitignored; none = tracked-input build, completed-draft picks kept)",
        f"- live league context: {json.dumps(p['liveLeagueContext'])[:300]}",
        f"- board rows {res['boardRows']}; incumbent board sha256 "
        f"`{res['outputs']['incumbentBoardSha256'][:16]}…`",
        f"- invariants: `{json.dumps(res['invariants'])}`",
        "",
        "## A. Scale vs population (offense rows, median ratio, n)",
        "",
    ]
    sp = res["scaleVsPopulation"]
    for key, entry in sp["summary"].items():
        out += [f"### {key}", "", f"verdict: `{json.dumps(entry['verdict'])}`", ""]
        out += _band_table(
            entry["byBand"],
            ["ratioLive", "populationFactor", "ratioPop", "ratioVendor", "ratioPopChallenger"],
        )
        out += ["", "by position (population-correct ratio):", ""]
        out += ["| group | median | p25 | p75 | n |", "|---|---|---|---|---|"]
        for g, s in entry["byPosition"].items():
            out.append(
                f"| {g} | {_fmt(s.get('median'))} | {_fmt(s.get('p25'))} | {_fmt(s.get('p75'))} | {s.get('n')} |"
            )
        for label, field in (
            ("row weight state", "byWeightState"),
            ("independent families", "byCoverage"),
        ):
            out += ["", f"by {label}:", ""]
            out += ["| group | median | n |", "|---|---|---|"]
            for g, s in entry[field].items():
                out.append(f"| {g} | {_fmt(s.get('median'))} | {s.get('n')} |")
        if "idpByBandCircular" in entry:
            out += ["", "IDP rows vs IDP master (CIRCULAR — master fit on this slice):", ""]
            out += _band_table({"ratioPop": entry["idpByBandCircular"]}, ["ratioPop"])
        out.append("")
    out += [
        "### Live rank pools",
        "",
        "```",
        json.dumps(sp["poolComposition"], indent=1),
        "```",
        "",
    ]
    out += [
        "### Source subset freshness (value sources)",
        "",
        "```",
        json.dumps(sp["sourceSubsetFreshness"], indent=1),
        "```",
        "",
    ]
    out += ["### Native curve shapes (players only, canonical coordinate, top 400)", ""]
    out += ["| board | role | c | s | rmse | n |", "|---|---|---|---|---|---|"]
    for label, e in sp["nativeCurveShapes"].items():
        if label.startswith("_"):
            continue
        po = e.get("playersOnly") or {}
        out.append(
            f"| {label} | {e['role']} | {po.get('c')} | {po.get('s')} | {po.get('rmse')} | {po.get('n')} |"
        )
        if e.get("withPicksAsTheFitterReads"):
            wp = e["withPicksAsTheFitterReads"]
            out.append(
                f"| {label} (as the fitter reads it, {e['picksInTop400']} picks in top 400) | "
                f"| {wp['c']} | {wp['s']} | {wp['rmse']} | {wp['n']} |"
            )
    out += [
        "",
        f"live OFFENSE master: `{sp['nativeCurveShapes']['_liveOffenseMaster']}`; pending "
        f"challenger: `{json.dumps(sp['pendingOffenseChallenger'])[:240]}`",
        "",
        "### Erratum for the 2026-09-30 replay counterfactual",
        "",
        "```",
        json.dumps(sp["replayCounterfactualErratum"], indent=1)[:3000],
        "```",
        "",
        "## B. Disagreement against leave-that-source-out boards",
        "",
        res["disagreement"]["note"],
        "",
        "| source | rows | rank ratio 1-50 | 51-100 | 101-200 | 201-300 | 301-400 | share >41% off | outlier drop rate |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for key, d in res["disagreement"]["bySource"].items():
        rr = d.get("rankRatioByBand") or {}
        cells = [_fmt((rr.get(b) or {}).get("median")) for b in ("1-50", *VERDICT_BANDS)]
        out.append(
            f"| {key} | {d['rows']} | "
            + " | ".join(cells)
            + f" | {_fmt(d.get('shareRankOffByMoreThan41pct'))} | {_fmt(d.get('hampelDropRate'))} |"
        )
    out += ["", "Outlier-dropped observations: are they order disagreements or scale gaps?", ""]
    out += [
        "| source | dropped | median rank ratio | median scale term | median order term |",
        "|---|---|---|---|---|",
    ]
    for key, d in res["disagreement"]["bySource"].items():
        od = d.get("outlierDroppedRows") or {}
        if od.get("n"):
            out.append(
                f"| {key} | {od['n']} | {_fmt(od['rankRatio'].get('median'))} | "
                f"{_fmt(od['scaleTerm'].get('median'))} | {_fmt(od['orderTermOnHill'].get('median'))} |"
            )
    for key in VALUE_SOURCES:
        d = res["disagreement"]["bySource"].get(key) or {}
        if d.get("valueSplitByBand"):
            out += [
                "",
                f"{key}: value split, log2(native/LOO) = scale + order-on-Hill (medians)",
                "",
            ]
            out += _band_table(
                d["valueSplitByBand"], ["nativeOverLoo", "scaleTerm", "orderTermOnHill"]
            )
    out += [
        "",
        "## C. Outlier-filter threshold sensitivity",
        "",
        "| variant | excluded | rows | KTC Crowd | KTC Trades | both KTC | IDPTC | rows changed | top-200 changes |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for name, h in res["outlierSensitivity"].items():
        out.append(
            f"| {name} | {h['observationsExcluded']} | {h['rowsWithAnyExclusion']} | {h['ktcCrowd']} | "
            f"{h['ktcTrades']} | {h['bothKtc']} | {h['idpTradeCalc']} | {h.get('rowsChanged', 0)} | "
            f"{h.get('top200MembershipChanges', 0)} |"
        )
    out += [
        "",
        f"incumbent KTC drops by live rank band: `{json.dumps(res['outlierSensitivity']['incumbent']['ktcDropsByLiveRankBand'])}`",
    ]
    out += [
        "",
        "## D. Candidates",
        "",
        f"c1 own-curve fits: `{json.dumps(res['candidates']['c1OwnCurveFits'])}`",
        "",
    ]
    out += [
        "| candidate | rows changed | median Δ% | p90 Δ% | max Δ% | top-25/50/100/200 kept | KTC excl. (crowd/trades) | KTC leverage p90 | sparse changed / median Δ% | struct. errors | build s | gates |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for name, c in res["candidates"]["results"].items():
        m = c["boardImpact"]["metrics"]
        to = c["topOverlap"]
        out.append(
            f"| {name} | {c['boardDiff']['rowsChanged']} | {m['medianAbsPctValueChange']:.3f} | "
            f"{m['p90AbsPctValueChange']:.3f} | {m['maxAbsPctValueChange']:.3f} | "
            f"{to['25']}/{to['50']}/{to['100']}/{to['200']} | {c['outliers']['ktcCrowd']}/{c['outliers']['ktcTrades']} | "
            f"{_fmt(c['ktcLeverage']['p90'])} | {c['sparseRows']['changed']} / {_fmt(c['sparseRows']['medianAbsPctChanged'])} | "
            f"{c['structuralErrors']} | {c['buildSeconds']} | "
            f"{'—' if 'gates' not in c else json.dumps(c['gates'])} |"
        )
    out += ["", "Players only (pick rows removed from both boards — a reporting cut):", ""]
    out += [
        "| candidate | median Δ% | p90 Δ% | max Δ% | top-25 | top-100 | median rank shift | p90 rank shift |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for name, c in res["candidates"]["results"].items():
        m = c["boardImpactPlayersOnly"]
        out.append(
            f"| {name} | {m['medianAbsPctValueChange']:.3f} | {m['p90AbsPctValueChange']:.3f} | "
            f"{m['maxAbsPctValueChange']:.3f} | {m['top25Overlap']} | {m['top100Overlap']} | "
            f"{m['medianAbsRankShift']} | {m['p90AbsRankShift']} |"
        )
    out += ["", "Regression examples (value / rank / KTC dropped):", ""]
    names = list(next(iter(res["candidates"]["results"].values()))["assets"])
    out += [
        "| asset | " + " | ".join(res["candidates"]["results"]) + " |",
        "|---|" + "---|" * len(res["candidates"]["results"]),
    ]
    for n in names:
        cells = []
        for c in res["candidates"]["results"].values():
            a = c["assets"][n]
            cells.append(f"{a['value']} / {a['rank']} / {','.join(a['ktcDropped']) or '-'}")
        out.append(f"| {n} | " + " | ".join(cells) + " |")
    h = res.get("holdout") or {}
    out += ["", "## E. Point-in-time holdout (archive)", ""]
    if "sources" in h:
        out.append(f"dates: {h['dates'][0]} … {h['dates'][-1]} ({len(h['dates'])} days)")
        for key, s in h["sources"].items():
            out += [
                "",
                f"### {key} — stable: **{s['stable']}**",
                "",
                "| band | days | min | max | range |",
                "|---|---|---|---|---|",
            ]
            for b, r in s["rangeByBand"].items():
                out.append(f"| {b} | {r['days']} | {r['min']} | {r['max']} | {r['range']} |")
            fw = s["forwardMapCheck"]
            if fw:
                oos = [
                    statistics.median(list(f["outOfSampleMedianAbsLog2ByBand"].values()))
                    for f in fw
                ]
                ins = [
                    statistics.median(list(f["inSampleMedianAbsLog2ByBand"].values())) for f in fw
                ]
                out.append(
                    f"\nc1 map forward check ({len(fw)} pairs, d -> d+7): median |log2 error| "
                    f"out-of-sample {statistics.median(oos):.4f} vs in-sample {statistics.median(ins):.4f}"
                )
    else:
        out.append(json.dumps(h))
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--payload", type=Path, default=None)
    ap.add_argument("--json", type=Path, required=True)
    ap.add_argument("--markdown", type=Path, required=True)
    ap.add_argument("--no-archive", action="store_true")
    ap.add_argument("--no-rank-loo", action="store_true", help="skip per-rank-voter LOO rebuilds")
    args = ap.parse_args(argv)
    payload = (
        args.payload or sorted((REPO_ROOT / "exports" / "latest").glob("dynasty_data_*.json"))[-1]
    )
    from scripts.value_replay import contrast_set

    base = vr.build(json.loads(payload.read_text(encoding="utf-8")))
    contrast = [n for n in contrast_set(base) if n != "Jalen Coker"]
    res = run(
        payload,
        archive=None if args.no_archive else REPO_ROOT / "exports" / "archive",
        contrast=contrast,
        loo_rank_sources=not args.no_rank_loo,
        progress=lambda m: print(f"[audit] {m}", file=sys.stderr),
    )
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(
        json.dumps(res, indent=1, sort_keys=False, default=str) + "\n", encoding="utf-8"
    )
    args.markdown.write_text(render_markdown(res), encoding="utf-8")
    print(
        f"wrote {args.json} and {args.markdown}; invariantsOk={res['invariantsOk']}",
        file=sys.stderr,
    )
    return 0 if res["invariantsOk"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
