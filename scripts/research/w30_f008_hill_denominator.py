#!/usr/bin/env python3
"""W30-F008 -- Hill fit vs serve percentile denominator.  RESEARCH ONLY, NOT ACTIVATED.

Offline evidence instrument for
``docs/valuation/methodology_proposals/W30_F008_HILL_DENOMINATOR.md``.

It changes nothing that is served.  It never writes ``src/``, ``config/``, the
model registry or the live Hill constants; candidate curves are installed only
inside this process (and restored) to rebuild a pinned archived board.

What it measures
----------------
1. **Oracle.**  An independent exact re-derivation (``fractions`` + 60-digit
   ``decimal``) of the canonical coordinate ``p = (r - 1) / (N - 1)`` with the
   tail ceiling, and of ``V(p) = 9999 / (1 + (p / c)^s)``, compared with the
   production ``rank_to_percentile`` + ``percentile_to_value`` at the edge ranks
   (1, fractional, the 500 boundary, 501..904, the saturation boundary, past it).
2. **Reproduction of the live champion.**  Registry v2 (the constants served
   today) was fitted at commit ``3df9cc4`` by the pre-repair fitter, whose
   percentile was ``i / (n - 1)`` over each source's OWN truncated length.  An
   independent re-implementation of that procedure, fed the exact input blobs of
   that commit, must reproduce v2's constants.  Re-running it with ONLY the
   coordinate changed to the canonical one gives candidate **C0** -- the curve v2
   would have been had the coordinate been right.  No new data, no new method.
3. **Served skew** of the incumbent against C0 (and the audit's closed-form
   scalar re-expression **T**) at fixed ranks, per scope.
4. **Board impact** on a pinned archived scrape, rebuilt in-process under each
   candidate: values, ranks, positions, picks, confidence, Autopilot board-impact
   policy bounds.
5. **Holdout** -- cross-sectional on the committed holdout CSVs, and a FORWARD
   time split over their committed git history after 2026-07-28 (the incumbent
   and C0 are both fixed by information available on 2026-07-28, so every later
   board is out of time for both).

Inputs are pinned: git blobs by revision, one tracked ``exports/archive`` bundle
by name + sha256, the committed CSV history.  Never the network, never
``exports/latest`` or gitignored ``data/``.

Usage::

    python scripts/research/w30_f008_hill_denominator.py \
        --json-out docs/valuation/methodology_proposals/evidence/w30_f008_hill_denominator.json
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import hashlib
import io
import json
import math
import statistics
import subprocess
import sys
import tempfile
import zipfile
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from fractions import Fraction
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

#: Commit whose fitter produced registry v2 (``producer`` field of v2).  Its
#: own child, ``ebc47fd8ed``, recorded v2 as a challenger 30 minutes later.
V2_PRODUCER_REV = "3df9cc4"
#: Registry v2 params, as recorded in ``config/model_registry/hill_scope_masters.json``.
V2_PARAMS: dict[str, tuple[float, float]] = {
    "OFFENSE": (0.1100, 1.110),
    "GLOBAL": (0.1120, 0.725),
    "IDP": (0.0830, 1.110),
}
#: Pinned archived scrape for the board-impact rebuild.
DEFAULT_ARCHIVE = "dynasty_export_20261107_063955.zip"
#: The canonical coordinate unit and tail, restated from the docs so the
#: oracle can assert the production constants equal them instead of reading them.
CANON_N = 500
CANON_TAIL_RANK = 904
#: Date from which the incumbent and C0 are both out of time.
FORWARD_START = date(2026, 7, 29)

SCOPES: tuple[str, ...] = ("OFFENSE", "GLOBAL", "IDP")
POOL_BY_SCOPE = {"OFFENSE": "offense", "GLOBAL": "shared_market", "IDP": "idp"}
CONST_BY_SCOPE = {
    "OFFENSE": ("HILL_PERCENTILE_C", "HILL_PERCENTILE_S"),
    "GLOBAL": ("HILL_GLOBAL_PERCENTILE_C", "HILL_GLOBAL_PERCENTILE_S"),
    "IDP": ("IDP_HILL_PERCENTILE_C", "IDP_HILL_PERCENTILE_S"),
}
ORACLE_RANKS: tuple[float, ...] = (
    0.5,
    1,
    1.5,
    2,
    10,
    25,
    50,
    100,
    200,
    300,
    400,
    499,
    500,
    501,
    600,
    800,
    903,
    904,
    905,
    1000,
    2000,
)
SKEW_RANKS: tuple[int, ...] = (10, 25, 50, 100, 142, 200, 300, 400, 500, 700, 904)

# v2-era trainer tables (verbatim from ``git show 3df9cc4:scripts/fit_hill_curve_percentile.py``).
V2_OFFENSE_SOURCES: dict[str, tuple[str, str]] = {
    "KTC": ("CSVs/site_raw/ktc.csv", "value"),
    "DynastyDaddy": ("CSVs/site_raw/dynastyDaddySf.csv", "value"),
    "DynastyNerds": ("CSVs/site_raw/dynastyNerdsSfTep.csv", "Value"),
    "YahooBoone": ("CSVs/site_raw/yahooBoone.csv", "boone_value"),
    "Fitzmaurice": ("CSVs/site_raw/fantasyProsFitzmaurice.csv", "value"),
    "DraftSharks": ("CSVs/site_raw/draftSharksSf.csv", "3D Value +"),
}
V2_IDP_POSITIONS = frozenset(
    {"DL", "DE", "DT", "EDGE", "NT", "LB", "ILB", "OLB", "MLB", "DB", "CB", "S", "SS", "FS"}
)
#: The 400-row truncation both the v2 fitter and today's fitter apply.
TRUNCATE = 400


# ── git / pinned-input helpers ─────────────────────────────────────────────


def _git(*args: str) -> bytes:
    return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, check=True).stdout


def git_available(rev: str) -> bool:
    try:
        _git("cat-file", "-e", f"{rev}^{{commit}}")
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def blob_text(rev: str, path: str) -> str:
    return _git("show", f"{rev}:{path}").decode("utf-8")


def blob_id(rev: str, path: str) -> str:
    return _git("rev-parse", f"{rev}:{path}").decode("utf-8").strip()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ── 1. the independent oracle ──────────────────────────────────────────────


def oracle_percentile(rank: float, n: int = CANON_N, tail_rank: int = CANON_TAIL_RANK) -> Fraction:
    """Exact canonical coordinate, tail-clamped: ``clamp((r-1)/(N-1), 0, (T-1)/(N-1))``."""
    p = (Fraction(str(rank)) - 1) / (n - 1)
    p_max = Fraction(tail_rank - 1, n - 1)
    return max(Fraction(0), min(p_max, p))


def oracle_value(p: Fraction, c: float, s: float) -> Decimal:
    """``9999 / (1 + (p/c)^s)`` at 60 significant digits; ``p == 0`` is the 9999 anchor."""
    with localcontext() as ctx:
        ctx.prec = 60
        if p == 0:
            return Decimal(9999)
        ratio = (Decimal(p.numerator) / Decimal(p.denominator)) / Decimal(str(c))
        return Decimal(9999) / (1 + (Decimal(str(s)) * ratio.ln()).exp())


def oracle_rank_form(rank: float, c: float, s: float, n: int = CANON_N) -> Decimal:
    """Rank-form identity ``9999 / (1 + ((r-1)/M)^s)``, ``M = c (N-1)`` (B1.2), untruncated."""
    with localcontext() as ctx:
        ctx.prec = 60
        x = Decimal(str(rank)) - 1
        if x <= 0:
            return Decimal(9999)
        m = Decimal(str(c)) * (n - 1)
        return Decimal(9999) / (1 + (Decimal(str(s)) * (x / m).ln()).exp())


def oracle_int(v: Decimal) -> int:
    """Production rounds with Python ``round`` (half-even) then bounds to [1, 9999]."""
    return max(1, min(9999, int(v.to_integral_value(rounding=ROUND_HALF_EVEN))))


def oracle_section(candidates: Mapping[str, Mapping[str, tuple[float, float]]]) -> dict[str, Any]:
    from src.canonical import player_valuation as pv
    from src.canonical import tail_policy

    constants_ok = (
        pv.PERCENTILE_REFERENCE_N == CANON_N and tail_policy.TAIL_SATURATION_RANK == CANON_TAIL_RANK
    )
    rows: list[dict[str, Any]] = []
    max_p_diff = 0.0
    max_raw_diff = 0.0
    int_mismatch = 0
    identity_max = Decimal(0)
    for cand, scopes in candidates.items():
        for scope, (c, s) in scopes.items():
            for r in ORACLE_RANKS:
                p_exact = oracle_percentile(r)
                p_prod = pv.rank_to_percentile(float(r))
                max_p_diff = max(max_p_diff, abs(float(p_exact) - p_prod))
                v_exact = oracle_value(p_exact, c, s)
                v_prod_int = pv.percentile_to_value(p_prod, midpoint=c, slope=s)
                raw_prod = 9999.0 if p_prod == 0.0 else 9999.0 / (1.0 + (p_prod / c) ** s)
                max_raw_diff = max(max_raw_diff, abs(float(v_exact) - raw_prod))
                if oracle_int(v_exact) != v_prod_int:
                    int_mismatch += 1
                if 1 <= r <= CANON_TAIL_RANK:
                    identity_max = max(identity_max, abs(oracle_rank_form(r, c, s) - v_exact))
                if cand in ("incumbent", "C0"):
                    rows.append(
                        {
                            "candidate": cand,
                            "scope": scope,
                            "rank": r,
                            "pExact": str(p_exact),
                            "p": round(float(p_exact), 9),
                            "valueOracle": round(float(v_exact), 6),
                            "valueProductionInt": v_prod_int,
                        }
                    )

    edge: dict[str, Any] = {}
    for cand_name in ("incumbent", "C0"):
        for scope, (c, s) in candidates[cand_name].items():
            edge[f"{cand_name}:{scope}"] = _edge_cases(c, s)
    return {
        "productionConstantsEqualDocumented": constants_ok,
        "percentileReferenceN": pv.PERCENTILE_REFERENCE_N,
        "tailSaturationRank": tail_policy.TAIL_SATURATION_RANK,
        "pMax": str(oracle_percentile(10**6)),
        "maxAbsPercentileDiff": f"{max_p_diff:.3e}",
        "maxAbsRawValueDiff": f"{max_raw_diff:.3e}",
        "integerMismatches": int_mismatch,
        "rankFormIdentityMaxAbsDiff": f"{float(identity_max):.3e}",
        "edgeCases": edge,
        "table": rows,
    }


def _edge_cases(c: float, s: float) -> dict[str, Any]:
    """Boundary behaviour of the PRODUCTION functions for one curve."""
    from src.canonical import player_valuation as pv

    vals = [
        pv.percentile_to_value(pv.rank_to_percentile(float(r)), midpoint=c, slope=s)
        for r in range(1, 1201)
    ]
    raws = [
        9999.0 if r == 1 else 9999.0 / (1.0 + (pv.rank_to_percentile(float(r)) / c) ** s)
        for r in range(1, 1201)
    ]
    return {
        "rank1": vals[0],
        "rankHalf": pv.percentile_to_value(pv.rank_to_percentile(0.5), midpoint=c, slope=s),
        "rank500": vals[499],
        "rank501": vals[500],
        "rank500EqualsRank501": vals[499] == vals[500],
        "rank904": vals[903],
        "rank905": vals[904],
        "saturatesAt904": vals[903] == vals[904] == vals[1199],
        "rawStrictlyDecreasingTo904": all(raws[i] > raws[i + 1] for i in range(903)),
        "intNonIncreasing": all(vals[i] >= vals[i + 1] for i in range(len(vals) - 1)),
        "minServedValue": min(vals),
        "aboveDisplayFloor": min(vals) > pv.DISPLAY_SCALE_MIN,
    }


# ── 2. the v2 fit procedure, re-implemented independently ──────────────────


def _hill_array(p, c, s, p_max: float):
    import numpy as np

    pc = np.minimum(np.maximum(p, 0.0), p_max)
    with np.errstate(divide="ignore"):
        out = 9999.0 / (1.0 + (pc / c) ** s)
    return np.where(pc == 0.0, 9999.0, out)


def grid_fit(pairs: Sequence[tuple[float, float]], p_max: float) -> tuple[float, float, float]:
    """The fitter's grid search (c 0.005..0.5 step 0.005, s 0.4..2.5 step 0.02) + refine.

    Same grid, same refinement, same first-minimum tie rule as both the v2 fitter
    and ``scripts/fit_hill_curve_percentile._fit``; vectorised over ``s``.
    """
    import numpy as np

    p = np.array([a for a, _ in pairs], dtype=float)
    v = np.array([b for _, b in pairs], dtype=float)
    c_grid = [0.005 + 0.005 * i for i in range(100)]
    s_grid = np.array([0.4 + 0.02 * i for i in range(106)])
    best: tuple[float, float, float] | None = None
    for c in c_grid:
        err = ((v[None, :] - _hill_array(p[None, :], c, s_grid[:, None], p_max)) ** 2).sum(axis=1)
        j = int(np.argmin(err))
        if best is None or err[j] < best[0]:
            best = (float(err[j]), c, float(s_grid[j]))
    assert best is not None
    _e0, c0, s0 = best
    for dc in (-0.002, -0.001, 0.0, 0.001, 0.002):
        for ds in (-0.01, -0.005, 0.0, 0.005, 0.01):
            c, s = c0 + dc, s0 + ds
            if c <= 0 or s <= 0:
                continue
            err = float(((v - _hill_array(p, c, s, p_max)) ** 2).sum())
            if err < best[0]:
                best = (err, c, s)
    return best[1], best[2], best[0] / len(pairs)


MASTER_GRID: tuple[float, ...] = tuple(
    sorted(
        set(
            round(p, 6)
            for p in [i / 2000.0 for i in range(1, 50)] + [i / 200.0 for i in range(1, 200)]
        )
    )
)


def master_fit(
    fits: Sequence[tuple[str, float, float]], p_max: float
) -> tuple[float, float, float]:
    """Unweighted mean of per-source curves on the fitter's percentile grid, refit."""
    import numpy as np

    g = np.array(MASTER_GRID)
    mean = np.mean([_hill_array(g, c, s, p_max) for _, c, s in fits], axis=0)
    return grid_fit(list(zip(MASTER_GRID, mean.tolist())), p_max)


def pairs_native(values: Sequence[float]) -> list[tuple[float, float]]:
    """The pre-repair coordinate: ``i / (n - 1)`` over the source's OWN truncated list."""
    n, top = len(values), values[0]
    return [(i / (n - 1), values[i] / top * 9999.0) for i in range(n)]


def pairs_canonical(values: Sequence[float]) -> list[tuple[float, float]]:
    """The canonical coordinate: ``i / (N - 1)`` whatever the list length."""
    top = values[0]
    return [(i / (CANON_N - 1), values[i] / top * 9999.0) for i in range(len(values))]


def _v2_load_values(text: str, col: str) -> list[float]:
    """The v2 loader verbatim: every positive cell (pick rows included), descending."""
    vs: list[float] = []
    for r in csv.DictReader(io.StringIO(text)):
        raw = r.get(col)
        try:
            v = float(raw) if raw else 0.0
        except (TypeError, ValueError):
            continue
        if v > 0:
            vs.append(v)
    vs.sort(reverse=True)
    return vs


def extract_v2_inputs(rev: str = V2_PRODUCER_REV) -> dict[str, Any]:
    """The exact trainer value vectors the v2 fitter saw at ``rev`` (from git blobs)."""
    blobs: dict[str, str] = {}
    out: dict[str, Any] = {"OFFENSE": {}, "GLOBAL": {}, "IDP": {}}
    for label, (path, col) in V2_OFFENSE_SOURCES.items():
        blobs[path] = blob_id(rev, path)
        out["OFFENSE"][label] = _v2_load_values(blob_text(rev, path), col)[:TRUNCATE]
    idptc = "CSVs/site_raw/idpTradeCalc.csv"
    blobs[idptc] = blob_id(rev, idptc)
    out["GLOBAL"]["IDPTradeCalc"] = _v2_load_values(blob_text(rev, idptc), "value")[:TRUNCATE]
    ds_sf, ds_idp = "CSVs/site_raw/draftSharksSf.csv", "CSVs/site_raw/draftSharksIdp.csv"
    blobs[ds_idp] = blob_id(rev, ds_idp)
    sf = _v2_load_values(blob_text(rev, ds_sf), "3D Value +")
    idp = _v2_load_values(blob_text(rev, ds_idp), "3D Value +")
    out["GLOBAL"]["DraftSharks-Combined"] = sorted(sf + idp, reverse=True)[:TRUNCATE]
    # IDP: IDPTC's IDP slice from the committed snapshot (the refit runner's
    # ``data/`` holds no tracked snapshot, so ``_latest_snapshot`` resolved to
    # ``exports/latest``), plus DraftSharks-IDP.
    snaps = [
        n
        for n in _git("ls-tree", "--name-only", rev, "exports/latest/").decode("utf-8").split()
        if n.startswith("exports/latest/dynasty_data_") and n.endswith(".json")
    ]
    snap_path = sorted(snaps)[-1]
    blobs[snap_path] = blob_id(rev, snap_path)
    snap = json.loads(blob_text(rev, snap_path))
    positions = (snap.get("sleeper") or {}).get("positions") or {}
    slice_vals: list[float] = []
    for name, p in (snap.get("players") or {}).items():
        if str(positions.get(name, "")).strip().upper() not in V2_IDP_POSITIONS:
            continue
        try:
            vf = float((p or {}).get("idpTradeCalc") or 0.0)
        except (TypeError, ValueError):
            continue
        if vf > 0:
            slice_vals.append(vf)
    slice_vals.sort(reverse=True)
    if slice_vals:
        out["IDP"]["IDPTradeCalc-IDP"] = slice_vals
    out["IDP"]["DraftSharks-IDP"] = idp[:TRUNCATE]
    # The VALUE-DIRECT voters of the v2 era (``_VALUE_BASED_SOURCES`` at that
    # commit: ``ktcSfTep`` + ``idpTradeCalc``) -- the scale a rank vote is
    # blended against.  Players only; IDPTC's offense slice via the snapshot.
    ktc_te = "CSVs/site_raw/ktcSfTep.csv"
    blobs[ktc_te] = blob_id(rev, ktc_te)
    off_slice: list[float] = []
    for name, p in (snap.get("players") or {}).items():
        if str(positions.get(name, "")).strip().upper() not in {"QB", "RB", "WR", "TE"}:
            continue
        try:
            vf = float((p or {}).get("idpTradeCalc") or 0.0)
        except (TypeError, ValueError):
            continue
        if vf > 0:
            off_slice.append(vf)
    off_slice.sort(reverse=True)
    out["VALUE_DIRECT"] = {
        "ktcSfTep": _board_values_from_text(blob_text(rev, ktc_te), "value")[:TRUNCATE],
        "IDPTradeCalc-Offense": off_slice[:TRUNCATE],
    }
    return {
        "rev": rev,
        "revFull": _git("rev-parse", rev).decode("utf-8").strip(),
        "blobs": blobs,
        "snapshot": snap_path,
        "idptcIdpSliceRows": len(slice_vals),
        "values": out,
    }


def fit_procedure(
    values: Mapping[str, Mapping[str, Sequence[float]]], coordinate: str
) -> dict[str, Any]:
    """Per-source fits and scope masters under ``coordinate`` ('native' | 'canonical')."""
    if coordinate == "native":
        make, p_max = pairs_native, 1.0  # the v2 fitter clamped p to [0, 1]
    else:
        make, p_max = pairs_canonical, float(oracle_percentile(10**6))
    per_source: dict[str, dict[str, Any]] = {}
    masters: dict[str, dict[str, float]] = {}
    for scope in SCOPES:
        fits: list[tuple[str, float, float]] = []
        for label, vals in values[scope].items():
            if len(vals) < 2:
                continue
            c, s, mse = grid_fit(make(vals), p_max)
            fits.append((label, c, s))
            per_source[f"{scope}:{label}"] = {
                "rows": len(vals),
                "c": round(c, 4),
                "s": round(s, 3),
                "rmse": round(mse**0.5, 2),
                "deepestCanonicalP": round((len(vals) - 1) / (CANON_N - 1), 4),
            }
        c, s, mse = master_fit(fits, p_max)
        masters[scope] = {
            "c": round(c, 4),
            "s": round(s, 3),
            "masterRmse": round(mse**0.5, 2),
            "sources": len(fits),
        }
    return {"coordinate": coordinate, "perSource": per_source, "masters": masters}


def value_direct_fit(values: Mapping[str, Any]) -> dict[str, Any]:
    """Framing-B diagnostic: canonical-coordinate curves fitted to the value-direct voters.

    OFFENSE -> the two v2-era value-direct offense boards; GLOBAL -> IDPTC (the
    shared-market value-direct voter, the same per-source fit as GLOBAL's
    IDPTC trainer).  The IDP master is unused by the served board, so it is
    carried from the incumbent.
    """
    p_max = float(oracle_percentile(10**6))
    fits = []
    per: dict[str, Any] = {}
    for label, vals in values["VALUE_DIRECT"].items():
        if len(vals) < 2:
            continue
        c, s, mse = grid_fit(pairs_canonical(vals), p_max)
        fits.append((label, c, s))
        per[label] = {
            "rows": len(vals),
            "c": round(c, 4),
            "s": round(s, 3),
            "rmse": round(mse**0.5, 2),
        }
    oc, os_, _ = master_fit(fits, p_max)
    gc, gs, _ = grid_fit(pairs_canonical(values["GLOBAL"]["IDPTradeCalc"]), p_max)
    return {
        "perSource": per,
        "OFFENSE": [round(oc, 4), round(os_, 3)],
        "GLOBAL": [round(gc, 4), round(gs, 3)],
    }


def reproduction_section(inputs: Mapping[str, Any]) -> dict[str, Any]:
    native = fit_procedure(inputs["values"], "native")
    canonical = fit_procedure(inputs["values"], "canonical")
    reproduces = all(
        math.isclose(native["masters"][sc]["c"], V2_PARAMS[sc][0], abs_tol=5e-5)
        and math.isclose(native["masters"][sc]["s"], V2_PARAMS[sc][1], abs_tol=5e-4)
        for sc in SCOPES
    )
    # Per-source unit check: canonical c == native c * (n-1)/(N-1) up to the grid step.
    unit = {}
    for key, nat in native["perSource"].items():
        can = canonical["perSource"][key]
        predicted = nat["c"] * (nat["rows"] - 1) / (CANON_N - 1)
        unit[key] = {
            "nativeC": nat["c"],
            "canonicalC": can["c"],
            "predictedC": round(predicted, 4),
            "absErr": round(abs(predicted - can["c"]), 4),
            "sameS": abs(nat["s"] - can["s"]) <= 0.0101,
        }
    return {
        "native": native,
        "canonical": canonical,
        "reproducesRegistryV2": reproduces,
        "perSourceUnitTransform": unit,
        "valueDirectScale": value_direct_fit(inputs["values"]),
    }


# ── candidates ─────────────────────────────────────────────────────────────


def build_candidates(repro: Mapping[str, Any]) -> dict[str, dict[str, tuple[float, float]]]:
    """Incumbent, C0 and the audit's closed-form scalar re-expression T.

    T assumes ONE fit denominator per scope -- 399 for OFFENSE/GLOBAL and 369 for
    IDP (the audit's arithmetic and the player_valuation comment).  The
    reproduction shows OFFENSE mixed depths 294..400 and the v2 IDP master saw a
    142-row board, so T is reported as the naive correction, not the right one.
    """
    inc = {sc: V2_PARAMS[sc] for sc in SCOPES}
    c0 = {
        sc: (repro["canonical"]["masters"][sc]["c"], repro["canonical"]["masters"][sc]["s"])
        for sc in SCOPES
    }
    t = {
        "OFFENSE": (round(V2_PARAMS["OFFENSE"][0] * 399 / 499, 4), V2_PARAMS["OFFENSE"][1]),
        "GLOBAL": (round(V2_PARAMS["GLOBAL"][0] * 399 / 499, 4), V2_PARAMS["GLOBAL"][1]),
        "IDP": (round(V2_PARAMS["IDP"][0] * 369 / 499, 4), V2_PARAMS["IDP"][1]),
    }
    c0_og = {"OFFENSE": c0["OFFENSE"], "GLOBAL": c0["GLOBAL"], "IDP": inc["IDP"]}
    vd = repro["valueDirectScale"]
    c_vd = {"OFFENSE": tuple(vd["OFFENSE"]), "GLOBAL": tuple(vd["GLOBAL"]), "IDP": inc["IDP"]}
    return {"incumbent": inc, "C0": c0, "C0_offense_global": c0_og, "T": t, "C_vd": c_vd}  # type: ignore[dict-item]


def registry_reference_candidates() -> dict[str, dict[str, tuple[float, float]]]:
    """READ-ONLY: the newest recorded challenger (the routine refit's current answer)."""
    reg = json.loads(
        (REPO / "config/model_registry/hill_scope_masters.json").read_text(encoding="utf-8")
    )
    latest = max(reg["versions"], key=lambda v: v["version"])
    p = latest["params"]
    full = {sc: (float(p[CONST_BY_SCOPE[sc][0]]), float(p[CONST_BY_SCOPE[sc][1]])) for sc in SCOPES}
    composed = {"OFFENSE": full["OFFENSE"], "GLOBAL": V2_PARAMS["GLOBAL"], "IDP": V2_PARAMS["IDP"]}
    return {
        f"R{latest['version']}_offense_only": composed,
        f"R{latest['version']}_all": full,
        "_meta": {"version": latest["version"], "fittedAt": latest.get("fittedAt")},  # type: ignore[dict-item]
    }


def hill_float(rank: float, c: float, s: float) -> float:
    p = float(oracle_percentile(rank))
    return 9999.0 if p == 0 else 9999.0 / (1.0 + (p / c) ** s)


def served_skew_section(cands: Mapping[str, Mapping[str, tuple[float, float]]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for scope in SCOPES:
        ci, si = cands["incumbent"][scope]
        rows = []
        for r in SKEW_RANKS:
            vi = hill_float(r, ci, si)
            row: dict[str, Any] = {"rank": r, "incumbent": round(vi, 1)}
            for name in ("C0", "T"):
                c, s = cands[name][scope]
                v = hill_float(r, c, s)
                row[name] = round(v, 1)
                row[f"incumbentOver{name}Pct"] = round(100.0 * (vi - v) / v, 2)
            rows.append(row)
        out[scope] = {
            "incumbentMidpointRank": round(ci * (CANON_N - 1), 3),
            "C0MidpointRank": round(cands["C0"][scope][0] * (CANON_N - 1), 3),
            "rows": rows,
        }
    return out


# ── 4. board impact on a pinned archive ───────────────────────────────────


@contextlib.contextmanager
def installed_curves(scopes: Mapping[str, tuple[float, float]]) -> Iterator[None]:
    """Install candidate (c, s) per scope IN THIS PROCESS ONLY, restoring on exit."""
    from src.canonical import player_valuation as pv
    from src.canonical import rank_coordinates as rc

    saved_pool = dict(rc._CURVE_BY_POOL)
    saved_pv = {n: getattr(pv, n) for sc in SCOPES for n in CONST_BY_SCOPE[sc]}
    try:
        for sc, (c, s) in scopes.items():
            rc._CURVE_BY_POOL[POOL_BY_SCOPE[sc]] = (float(c), float(s))
            cn, sn = CONST_BY_SCOPE[sc]
            setattr(pv, cn, float(c))
            setattr(pv, sn, float(s))
        yield
    finally:
        rc._CURVE_BY_POOL.clear()
        rc._CURVE_BY_POOL.update(saved_pool)
        for n, v in saved_pv.items():
            setattr(pv, n, v)


def load_archive_payload(name: str) -> tuple[dict[str, Any], str]:
    path = REPO / "exports" / "archive" / name
    with zipfile.ZipFile(path) as zf:
        inner = [n for n in zf.namelist() if n.startswith("dynasty_data_") and n.endswith(".json")]
        payload = json.loads(zf.read(inner[0]).decode("utf-8"))
    return payload, sha256_file(path)


def build_board(
    payload: Mapping[str, Any], scopes: Mapping[str, tuple[float, float]]
) -> dict[str, Any]:
    from src.api.data_contract import build_api_data_contract

    with installed_curves(scopes):
        return build_api_data_contract(json.loads(json.dumps(payload)))


def _pos(row: Mapping[str, Any]) -> str:
    if row.get("assetClass") == "pick":
        return "PICK"
    return str(row.get("position") or "?").upper()


def _paths(row: Mapping[str, Any]) -> set[str]:
    meta = row.get("sourceRankMeta") or {}
    return {str(m.get("valueContributionPath")) for m in meta.values() if isinstance(m, dict)}


#: Sources that vote value-direct on today's board (``_VALUE_BASED_SOURCES``).
VALUE_DIRECT_KEYS = frozenset({"ktcCrowdSfTep", "ktcTradesSfTep", "idpTradeCalc"})


def value_direct_drops(board: Mapping[str, Any]) -> dict[str, Any]:
    """How many value-direct market votes the outlier filter discarded, per asset class.

    A dropped vote is a real provider's opinion removed from the blend, so a curve
    whose level makes the value-direct markets look like outliers changes WHO
    votes, not only how much each vote is worth.
    """
    out: dict[str, Any] = {}
    for cls in ("offense", "idp", "pick"):
        per: dict[str, int] = {}
        rows = 0
        for r in board["playersArray"]:
            if r.get("assetClass") != cls or not r.get("rankDerivedValue"):
                continue
            hit = [
                s
                for s in (r.get("droppedSources") or [])
                if isinstance(s, str) and s in VALUE_DIRECT_KEYS
            ]
            rows += 1 if hit else 0
            for s in hit:
                per[s] = per.get(s, 0) + 1
        out[cls] = {"rowsWithDroppedValueDirectVote": rows, "bySource": dict(sorted(per.items()))}
    return out


def _q(vals: Sequence[float], q: float) -> float:
    if not vals:
        return float("nan")
    s = sorted(vals)
    k = (len(s) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def pick_term_structure(board: Mapping[str, Any]) -> dict[str, Any]:
    """Mean value per round: the slotted class (rookie-pool tethered) vs later tier classes.

    Current-year slot picks inherit rookie PLAYER values (rank-Hill heavy) while
    later classes are vendor-priced value-direct, so a curve level change moves
    one side of the term structure and not the other.
    """
    import re

    slot_re = re.compile(r"^(\d{4}) Pick (\d)\.(\d{2})$")
    tier_re = re.compile(r"^(\d{4}) (Early|Mid|Late) (\d)(?:st|nd|rd|th)$")
    slots: dict[tuple[int, int], list[float]] = {}
    tiers: dict[tuple[int, int], list[float]] = {}
    for r in board["playersArray"]:
        v = r.get("rankDerivedValue")
        if r.get("assetClass") != "pick" or not v:
            continue
        name = str(r.get("displayName"))
        m = slot_re.match(name)
        if m:
            slots.setdefault((int(m.group(1)), int(m.group(2))), []).append(float(v))
            continue
        m = tier_re.match(name)
        if m:
            tiers.setdefault((int(m.group(1)), int(m.group(3))), []).append(float(v))
    out: dict[str, Any] = {}
    for (yr, rnd), vals in sorted(slots.items()):
        if rnd > 2:
            continue
        nxt = tiers.get((yr + 1, rnd))
        out[f"{yr}R{rnd}"] = {
            "slotMean": round(statistics.fmean(vals), 1),
            f"tier{yr + 1}Mean": round(statistics.fmean(nxt), 1) if nxt else None,
            "slotOverNextYearTier": round(statistics.fmean(vals) / statistics.fmean(nxt), 4)
            if nxt
            else None,
        }
    return out


def market_shape_section(rev: str) -> dict[str, Any]:
    """Each committed OFFENSE board's own best-fit curve (canonical coordinate, at ``rev``).

    Context for how wide the 'market shape' spread is: the master averages these.
    """
    from src.model_registry.holdout import offense_holdout_sources, offense_training_sources

    p_max = float(oracle_percentile(10**6))
    out: dict[str, Any] = {}
    for role, table in (
        ("train", offense_training_sources()),
        ("holdout", offense_holdout_sources()),
    ):
        for label, (path, col) in sorted(table.items()):
            vals = _board_values_from_text(blob_text(rev, path), col)[:TRUNCATE]
            if len(vals) < 100:
                out[label] = {"role": role, "rows": len(vals), "skipped": True}
                continue
            c, s, mse = grid_fit(pairs_canonical(vals), p_max)
            out[label] = {
                "role": role,
                "rows": len(vals),
                "c": round(c, 4),
                "s": round(s, 3),
                "midpointRank": round(c * (CANON_N - 1), 2),
                "rmse": round(mse**0.5, 1),
            }
    return out


def board_diff(
    base: Mapping[str, Any], cand: Mapping[str, Any], policy: Mapping[str, Any]
) -> dict[str, Any]:
    b = {r["displayName"]: r for r in base["playersArray"]}
    c = {r["displayName"]: r for r in cand["playersArray"]}
    common = [
        n for n in b if n in c and b[n].get("rankDerivedValue") and c[n].get("rankDerivedValue")
    ]
    pct = {
        n: (c[n]["rankDerivedValue"] - b[n]["rankDerivedValue"]) / b[n]["rankDerivedValue"]
        for n in common
    }
    ranked = [
        n
        for n in common
        if b[n].get("canonicalConsensusRank") and c[n].get("canonicalConsensusRank")
    ]
    shift = {n: b[n]["canonicalConsensusRank"] - c[n]["canonicalConsensusRank"] for n in ranked}
    vd_only = [n for n in common if _paths(b[n]) == {"value_direct"}]
    vd_only_changed = [n for n in vd_only if b[n]["rankDerivedValue"] != c[n]["rankDerivedValue"]]

    def top(board: Mapping[str, Mapping[str, Any]], k: int) -> set[str]:
        return {
            n
            for n, r in board.items()
            if r.get("canonicalConsensusRank") and r["canonicalConsensusRank"] <= k
        }

    by_pos: dict[str, dict[str, Any]] = {}
    for n in common:
        by_pos.setdefault(_pos(b[n]), {"pct": [], "shift": []})["pct"].append(pct[n])
        if n in shift:
            by_pos[_pos(b[n])]["shift"].append(shift[n])
    pos_summary = {
        p: {
            "rows": len(d["pct"]),
            "medianPctValueChange": round(100 * statistics.median(d["pct"]), 2),
            "p10PctValueChange": round(100 * _q(d["pct"], 0.10), 2),
            "p90PctValueChange": round(100 * _q(d["pct"], 0.90), 2),
            "rowsRising": sum(1 for x in d["pct"] if x > 0),
            "medianRankShift": statistics.median(d["shift"]) if d["shift"] else None,
            "meanAbsRankShift": round(statistics.fmean(abs(x) for x in d["shift"]), 2)
            if d["shift"]
            else None,
        }
        for p, d in sorted(by_pos.items())
    }
    abs_pct = [abs(x) for x in pct.values()]
    abs_shift = [abs(x) for x in shift.values()]
    conf_moves: dict[str, int] = {}
    for n in common:
        k = f"{b[n].get('confidenceBucket')}->{c[n].get('confidenceBucket')}"
        if b[n].get("confidenceBucket") != c[n].get("confidenceBucket"):
            conf_moves[k] = conf_moves.get(k, 0) + 1
    bi = policy.get("boardImpact", {})
    metrics = {
        "medianAbsPctValueChange": statistics.median(abs_pct),
        "p90AbsPctValueChange": _q(abs_pct, 0.90),
        "maxAbsPctValueChange": max(abs_pct),
        "top25Overlap": len(top(b, 25) & top(c, 25)),
        "top100Overlap": len(top(b, 100) & top(c, 100)),
        "medianAbsRankShift": statistics.median(abs_shift),
        "p90AbsRankShift": _q(abs_shift, 0.90),
    }
    gates = {
        "maxMedianAbsPctValueChange": metrics["medianAbsPctValueChange"]
        <= bi.get("maxMedianAbsPctValueChange", 1),
        "maxP90AbsPctValueChange": metrics["p90AbsPctValueChange"]
        <= bi.get("maxP90AbsPctValueChange", 1),
        "maxSingleAbsPctValueChange": metrics["maxAbsPctValueChange"]
        <= bi.get("maxSingleAbsPctValueChange", 1),
        "minTop25Overlap": metrics["top25Overlap"] >= bi.get("minTop25Overlap", 0),
        "minTop100Overlap": metrics["top100Overlap"] >= bi.get("minTop100Overlap", 0),
        "maxMedianAbsRankShift": metrics["medianAbsRankShift"]
        <= bi.get("maxMedianAbsRankShift", 1e9),
        "maxP90AbsRankShift": metrics["p90AbsRankShift"] <= bi.get("maxP90AbsRankShift", 1e9),
    }
    movers = sorted(
        (n for n in ranked if b[n]["canonicalConsensusRank"] <= 300),
        key=lambda n: (-abs(pct[n]), n),
    )[:12]
    rank_movers = sorted(ranked, key=lambda n: (-abs(shift[n]), n))[:12]

    def mover(n: str) -> dict[str, Any]:
        return {
            "name": n,
            "pos": _pos(b[n]),
            "valueBefore": b[n]["rankDerivedValue"],
            "valueAfter": c[n]["rankDerivedValue"],
            "pct": round(100 * pct[n], 2),
            "rankBefore": b[n].get("canonicalConsensusRank"),
            "rankAfter": c[n].get("canonicalConsensusRank"),
        }

    viol_b = sum(1 for r in base["playersArray"] if r.get("blendIntegrityViolation"))
    viol_c = sum(1 for r in cand["playersArray"] if r.get("blendIntegrityViolation"))

    def buckets(board: Mapping[str, Mapping[str, Any]]) -> dict[str, int]:
        out: dict[str, int] = {}
        for n in common:
            k = str(board[n].get("confidenceBucket"))
            out[k] = out.get(k, 0) + 1
        return dict(sorted(out.items()))

    return {
        "comparableRows": len(common),
        "rowsValueChanged": sum(
            1 for n in common if b[n]["rankDerivedValue"] != c[n]["rankDerivedValue"]
        ),
        "rowsRising": sum(1 for x in pct.values() if x > 0),
        "rowsFalling": sum(1 for x in pct.values() if x < 0),
        "rankedRows": len(ranked),
        "rowsReordered": sum(1 for x in shift.values() if x != 0),
        "rowsMovingOver10": sum(1 for x in abs_shift if x > 10),
        "maxAbsRankShift": max(abs_shift) if abs_shift else 0,
        "valueDirectOnlyRows": len(vd_only),
        "valueDirectOnlyRowsChanged": len(vd_only_changed),
        "metrics": {k: round(v, 4) if isinstance(v, float) else v for k, v in metrics.items()},
        "autopilotBoardImpactGates": gates,
        "autopilotBoardImpactPass": all(gates.values()),
        "byPosition": pos_summary,
        "confidenceTransitions": dict(sorted(conf_moves.items())),
        "confidenceBuckets": {"incumbent": buckets(b), "candidate": buckets(c)},
        "pickTermStructure": {
            "incumbent": pick_term_structure(base),
            "candidate": pick_term_structure(cand),
        },
        "blendIntegrityViolations": {"incumbent": viol_b, "candidate": viol_c},
        "contractHealthOk": {
            "incumbent": (base.get("contractHealth") or {}).get("ok"),
            "candidate": (cand.get("contractHealth") or {}).get("ok"),
        },
        "largestValueMoversTop300": [mover(n) for n in movers],
        "largestRankMovers": [mover(n) for n in rank_movers],
    }


def vote_calibration(board: Mapping[str, Any]) -> dict[str, Any]:
    """Rank-Hill vote vs value-direct vote on the SAME row, by board-rank band.

    A calibration diagnostic, not out-of-sample evidence: KTC trains OFFENSE and
    IDPTC trains GLOBAL.  TE rows are excluded (the TE basis conversion scales
    rank-Hill and value-direct votes differently by construction).
    """
    bands = ((1, 50), (51, 100), (101, 200), (201, 400), (401, 800))
    out: dict[str, Any] = {}
    for group, positions, vd_keys in (
        ("offense_QB_RB_WR", {"QB", "RB", "WR"}, {"ktcCrowdSfTep", "ktcTradesSfTep"}),
        ("idp", {"DL", "LB", "DB", "DE", "DT", "EDGE", "CB", "S"}, {"idpTradeCalc"}),
    ):
        res: dict[str, Any] = {}
        for lo, hi in bands:
            ratios: list[float] = []
            for r in board["playersArray"]:
                rk = r.get("canonicalConsensusRank")
                if not rk or not (lo <= rk <= hi) or _pos(r) not in positions:
                    continue
                meta = r.get("sourceRankMeta") or {}
                vd = [
                    m["valueContribution"]
                    for k, m in meta.items()
                    if k in vd_keys
                    and m.get("valueContributionPath") == "value_direct"
                    and m.get("valueContribution")
                ]
                rh = [
                    m["valueContribution"]
                    for m in meta.values()
                    if m.get("valueContributionPath") == "rank_hill" and m.get("valueContribution")
                ]
                if vd and rh:
                    ratios.append(statistics.median(rh) / statistics.median(vd))
            res[f"{lo}-{hi}"] = {
                "rows": len(ratios),
                "medianRankHillOverValueDirect": round(statistics.median(ratios), 4)
                if ratios
                else None,
            }
        out[group] = res
    return out


def exchange_rate(board: Mapping[str, Any]) -> dict[str, Any]:
    """Board value over IDPTC's own value for the same row, offense vs IDP, by board rank.

    IDP Trade Calculator prices offense AND IDP on one native scale, so the ratio
    of the two medians is the board's offense/IDP exchange rate relative to that
    one full-roster market.  In-sample by construction (IDPTC votes value-direct
    on both populations and trains GLOBAL): a coherence diagnostic, not evidence
    of truth.
    """
    bands = ((1, 100), (101, 300), (301, 600))
    out: dict[str, Any] = {}
    for lo, hi in bands:
        grp: dict[str, list[float]] = {"offense": [], "idp": []}
        for r in board["playersArray"]:
            rk, v = r.get("canonicalConsensusRank"), r.get("rankDerivedValue")
            if not rk or not v or not (lo <= rk <= hi) or r.get("assetClass") not in grp:
                continue
            m = (r.get("sourceRankMeta") or {}).get("idpTradeCalc") or {}
            if m.get("valueContributionPath") == "value_direct" and m.get("valueContribution"):
                grp[str(r["assetClass"])].append(float(v) / float(m["valueContribution"]))
        off = statistics.median(grp["offense"]) if grp["offense"] else None
        idp = statistics.median(grp["idp"]) if grp["idp"] else None
        out[f"{lo}-{hi}"] = {
            "offenseRows": len(grp["offense"]),
            "idpRows": len(grp["idp"]),
            "offenseBoardOverIdptc": round(off, 4) if off else None,
            "idpBoardOverIdptc": round(idp, 4) if idp else None,
            "offenseOverIdpRatio": round(off / idp, 4) if off and idp else None,
        }
    return out


def board_section(
    archive: str, cands: Mapping[str, Mapping[str, tuple[float, float]]]
) -> dict[str, Any]:
    payload, sha = load_archive_payload(archive)
    policy = json.loads(
        (REPO / "config/model_registry/hill_autopilot_policy.json").read_text(encoding="utf-8")
    )
    base = build_board(payload, cands["incumbent"])
    # The incumbent rebuild must be the unpatched build: same constants, same board.
    from src.api.data_contract import build_api_data_contract

    plain = build_api_data_contract(json.loads(json.dumps(payload)))
    same = [r.get("rankDerivedValue") for r in plain["playersArray"]] == [
        r.get("rankDerivedValue") for r in base["playersArray"]
    ]
    pools: dict[str, int] = {}
    for r in base["playersArray"]:
        for m in (r.get("sourceRankMeta") or {}).values():
            if m.get("valueContributionPath") == "rank_hill":
                pool = str(m.get("rankCoordinatePool"))
                pools[pool] = pools.get(pool, 0) + 1
    rows_with_hill = sum(1 for r in base["playersArray"] if "rank_hill" in _paths(r))
    out: dict[str, Any] = {
        "archive": archive,
        "archiveSha256": sha,
        "incumbentRebuildEqualsPlainBuild": same,
        "rows": len(base["playersArray"]),
        "rowsWithRankHillVote": rows_with_hill,
        "rankHillVotesByPool": dict(sorted(pools.items())),
        "voteCalibration": {"incumbent": vote_calibration(base)},
        "exchangeRate": {"incumbent": exchange_rate(base)},
        "valueDirectDrops": {"incumbent": value_direct_drops(base)},
        "diffs": {},
    }
    for name, scopes in cands.items():
        if name == "incumbent" or name.startswith("_"):
            continue
        board = build_board(payload, scopes)
        out["diffs"][name] = board_diff(base, board, policy)
        out["voteCalibration"][name] = vote_calibration(board)
        out["exchangeRate"][name] = exchange_rate(board)
        out["valueDirectDrops"][name] = value_direct_drops(board)
    return out


# ── 4b. player-level forward ordering (later observations, no look-ahead) ──


def _spearman(xs: Sequence[float], ys: Sequence[float]) -> float:
    def ranks(v: Sequence[float]) -> list[float]:
        order = sorted(range(len(v)), key=lambda i: v[i])
        out = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                out[order[k]] = avg
            i = j + 1
        return out

    rx, ry = ranks(xs), ranks(ys)
    mx, my = statistics.fmean(rx), statistics.fmean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return num / den if den else float("nan")


FORWARD_ORDER_DATES: tuple[str, ...] = (
    "2026-08-01",
    "2026-08-15",
    "2026-09-01",
    "2026-09-15",
    "2026-10-01",
    "2026-10-10",
)
HORIZON_DAYS = 28


def forward_ordering_section(
    cands: Mapping[str, Mapping[str, tuple[float, float]]],
    rev: str,
    dates: Sequence[str] = FORWARD_ORDER_DATES,
    horizon: int = HORIZON_DAYS,
) -> dict[str, Any]:
    """Does the board at t order offense players like a later market at t + h?

    Both candidates are fixed by 2026-07-28 information and every t is later, so
    there is no look-ahead.  NO target is independent, and the two available
    kinds are contaminated in OPPOSITE directions -- reported together as a
    bracket, never one alone:

    * the three holdout markets also vote BY RANK in the board at t.  Deflating
      rank votes relative to value-direct votes (what C0 does) reduces their
      own influence, so this target is biased TOWARD THE INCUMBENT;
    * KTC Market (``ktcCrowdTradesSfTep``, benchmark-only, never a vote) is the
      published blend of KTC Crowd + KTC Trades, which vote value-direct.  C0
      raises their relative influence, so this target is biased TOWARD C0.
    """
    from src.utils.name_clean import normalize_player_name

    archives = sorted((REPO / "exports" / "archive").glob("dynasty_export_*.zip"))
    holdouts = dict(_holdouts())
    holdouts["KTCMarket"] = ("CSVs/site_raw/ktcCrowdTradesSfTep.csv", "value")
    hist = {label: _history(path, rev) for label, (path, _c) in holdouts.items()}
    rows: list[dict[str, Any]] = []
    for ds in dates:
        t = date.fromisoformat(ds)
        stamp = t.strftime("%Y%m%d")
        prior = [
            a
            for a in archives
            if a.name[len("dynasty_export_") : len("dynasty_export_") + 8] <= stamp
        ]
        if not prior:
            continue
        arch = prior[-1]
        payload, sha = load_archive_payload(arch.name)
        boards = {n: build_board(payload, cands[n]) for n in ("incumbent", "C0", "C_vd")}
        cutoff = datetime(t.year, t.month, t.day, 23, 59, 59, tzinfo=timezone.utc) + timedelta(
            days=horizon
        )
        per_board: dict[str, Any] = {}
        for label, (path, col) in sorted(holdouts.items()):
            shas = [s for ts, s in hist[label] if ts <= cutoff]
            if not shas:
                continue
            from src.model_registry.training_manifest import load_board_values

            with tempfile.TemporaryDirectory() as td:
                p = Path(td) / "b.csv"
                p.write_text(blob_text(shas[-1], path), encoding="utf-8")
                bv = load_board_values(p, col)
            target = {
                normalize_player_name(n): v
                for n, v in zip(bv.names[:TRUNCATE], bv.values[:TRUNCATE])
            }
            res: dict[str, Any] = {"targetBlob": blob_id(shas[-1], path)}
            for n, b in boards.items():
                xs, ys = [], []
                for r in b["playersArray"]:
                    if r.get("assetClass") != "offense" or not r.get("rankDerivedValue"):
                        continue
                    key = normalize_player_name(r.get("displayName"))
                    if key in target:
                        xs.append(float(r["rankDerivedValue"]))
                        ys.append(float(target[key]))
                res[n] = {"rows": len(xs), "spearman": round(_spearman(xs, ys), 5)}
            res["C0MinusIncumbent"] = round(res["C0"]["spearman"] - res["incumbent"]["spearman"], 5)
            res["C_vdMinusIncumbent"] = round(
                res["C_vd"]["spearman"] - res["incumbent"]["spearman"], 5
            )
            per_board[label] = res
        drops = {
            n: value_direct_drops(b)["offense"]["rowsWithDroppedValueDirectVote"]
            for n, b in boards.items()
        }
        rows.append(
            {
                "t": ds,
                "archive": arch.name,
                "archiveSha256": sha,
                "horizonDays": horizon,
                "offenseRowsWithDroppedValueDirectVote": drops,
                "boards": per_board,
            }
        )

    def summarise(labels: set[str]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for cand in ("C0", "C_vd"):
            deltas = [
                b[f"{cand}MinusIncumbent"]
                for r in rows
                for k, b in r["boards"].items()
                if k in labels
            ]
            out[cand] = {
                "pairs": len(deltas),
                "pairsBetterThanIncumbent": sum(1 for d in deltas if d > 0),
                "meanDelta": round(statistics.fmean(deltas), 5) if deltas else None,
                "minDelta": round(min(deltas), 5) if deltas else None,
                "maxDelta": round(max(deltas), 5) if deltas else None,
            }
        return out

    return {
        "dates": list(dates),
        "horizonDays": horizon,
        "rows": rows,
        "holdoutMarkets_biasedTowardIncumbent": summarise(set(_holdouts())),
        "ktcMarket_biasedTowardC0": summarise({"KTCMarket"}),
    }


# ── 5. holdout: cross-sectional and forward ───────────────────────────────


def _board_values_from_text(text: str, column: str) -> list[float]:
    from src.model_registry.training_manifest import MissingColumnError, load_board_values

    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "board.csv"
        p.write_text(text, encoding="utf-8")
        try:
            return list(load_board_values(p, column).values)
        except MissingColumnError:
            return []


def holdout_rmse(values: Sequence[float], c: float, s: float) -> float:
    """RMSE of the curve against one board, canonical coordinate, top-400, top = 9999."""
    vs = list(values[:TRUNCATE])
    top = vs[0]
    err = 0.0
    for i, v in enumerate(vs):
        err += (hill_float(i + 1, c, s) - v / top * 9999.0) ** 2
    return (err / len(vs)) ** 0.5


def holdout_rmse_native(values: Sequence[float], c: float, s: float) -> float:
    """The same RMSE in the pre-repair native coordinate (what v2's gate measured)."""
    vs = list(values[:TRUNCATE])
    n, top = len(vs), vs[0]
    err = 0.0
    for i, v in enumerate(vs):
        p = i / (n - 1)
        h = 9999.0 if p == 0 else 9999.0 / (1.0 + (p / c) ** s)
        err += (h - v / top * 9999.0) ** 2
    return (err / len(vs)) ** 0.5


def _holdouts() -> dict[str, tuple[str, str]]:
    from src.model_registry.holdout import offense_holdout_sources

    return offense_holdout_sources()


def cross_sectional_section(
    cands: Mapping[str, Mapping[str, tuple[float, float]]], rev: str
) -> dict[str, Any]:
    """Score every candidate's OFFENSE curve on the holdout CSVs committed at ``rev``.

    Cross-checked against the production evaluator, pointed at a temporary root
    holding exactly those blobs (it reads nothing else from disk for scoring).
    """
    from src.model_registry.holdout import evaluate_offense_master

    out: dict[str, Any] = {"rev": rev, "boards": {}}
    boards: dict[str, list[float]] = {}
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    for label, (path, col) in sorted(_holdouts().items()):
        text = blob_text(rev, path)
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(text, encoding="utf-8")
        boards[label] = _board_values_from_text(text, col)
        out["boards"][label] = {
            "path": path,
            "blob": blob_id(rev, path),
            "rows": min(len(boards[label]), TRUNCATE),
        }
    scores: dict[str, Any] = {}
    for name, scopes in cands.items():
        if name.startswith("_"):
            continue
        c, s = scopes["OFFENSE"]
        per = {k: round(holdout_rmse(v, c, s), 2) for k, v in boards.items() if len(v) >= 100}
        prod = evaluate_offense_master(c, s, repo_root=root)
        scores[name] = {
            "c": c,
            "s": s,
            "criterion": round(statistics.fmean(per.values()), 2),
            "perSource": per,
            "productionEvaluatorCriterion": round(prod.criterion, 2),
        }
    out["scores"] = scores
    inc = cands["incumbent"]["OFFENSE"]
    out["incumbentNativeCoordinateCriterion"] = round(
        statistics.fmean(holdout_rmse_native(v, *inc) for v in boards.values() if len(v) >= 100), 2
    )
    tmp.cleanup()
    return out


def _history(path: str, rev: str = "HEAD") -> list[tuple[datetime, str]]:
    raw = _git("log", "--format=%H%x09%cI", rev, "--", path).decode("utf-8")
    out = []
    for line in raw.splitlines():
        sha, ts = line.split("\t")
        out.append((datetime.fromisoformat(ts).astimezone(timezone.utc), sha))
    out.sort()
    return out


def forward_section(
    cands: Mapping[str, Mapping[str, tuple[float, float]]],
    start: date = FORWARD_START,
    end: date | None = None,
    rev: str = "HEAD",
) -> dict[str, Any]:
    """Score the July-28-fixed candidates on every later day's committed holdout boards."""
    holdouts = _holdouts()
    hist = {label: _history(path, rev) for label, (path, _c) in holdouts.items()}
    last = max(ts for h in hist.values() for ts, _ in h).date()
    end = end or last
    blob_cache: dict[str, list[float]] = {}
    days: list[dict[str, Any]] = []
    states: set[tuple[str, ...]] = set()
    names = [n for n in ("incumbent", "C0", "T", "C_vd") if n in cands]
    d = start
    while d <= end:
        cutoff = datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=timezone.utc)
        per: dict[str, dict[str, float]] = {n: {} for n in names}
        native_inc: dict[str, float] = {}
        state: list[str] = []
        for label, (path, col) in sorted(holdouts.items()):
            prior = [sha for ts, sha in hist[label] if ts <= cutoff]
            if not prior:
                continue
            bid = blob_id(prior[-1], path)
            if bid not in blob_cache:
                blob_cache[bid] = _board_values_from_text(blob_text(prior[-1], path), col)
            vals = blob_cache[bid]
            if len(vals) < 100:
                continue
            state.append(bid)
            for n in names:
                per[n][label] = holdout_rmse(vals, *cands[n]["OFFENSE"])
            native_inc[label] = holdout_rmse_native(vals, *cands["incumbent"]["OFFENSE"])
        if per["incumbent"]:
            states.add(tuple(state))
            row: dict[str, Any] = {"date": d.isoformat(), "boards": sorted(per["incumbent"])}
            for n in names:
                row[n] = round(statistics.fmean(per[n].values()), 2)
            row["incumbentNative"] = round(statistics.fmean(native_inc.values()), 2)
            row["C0BeatsIncumbentOnEveryBoard"] = all(
                per["C0"][k] < per["incumbent"][k] for k in per["incumbent"]
            )
            days.append(row)
        d += timedelta(days=1)

    def summary(name: str) -> dict[str, Any]:
        imp = [r["incumbent"] - r[name] for r in days]
        return {
            "days": len(imp),
            "winDays": sum(1 for x in imp if x > 0),
            "medianImprovement": round(statistics.median(imp), 2),
            "minImprovement": round(min(imp), 2),
            "maxImprovement": round(max(imp), 2),
        }

    by_month: dict[str, dict[str, float]] = {}
    for r in days:
        m = r["date"][:7]
        by_month.setdefault(m, {"n": 0.0, **{n: 0.0 for n in names}})
        by_month[m]["n"] += 1
        for n in names:
            by_month[m][n] += r[n]
    months = {
        m: {"days": int(v["n"]), **{n: round(v[n] / v["n"], 2) for n in names}}
        for m, v in sorted(by_month.items())
    }
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "holdouts": sorted(holdouts),
        "distinctBoardStates": len(states),
        "summary": {n: summary(n) for n in names if n != "incumbent"},
        "daysC0BeatsIncumbentOnEveryBoard": sum(
            1 for r in days if r["C0BeatsIncumbentOnEveryBoard"]
        ),
        "byMonth": months,
        "first": days[0] if days else None,
        "last": days[-1] if days else None,
        "series": days,
    }


# ── driver ─────────────────────────────────────────────────────────────────


def _round_floats(o: Any) -> Any:
    if isinstance(o, float):
        return round(o, 6)
    if isinstance(o, dict):
        return {k: _round_floats(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_round_floats(v) for v in o]
    return o


def load_inputs(rev: str, fixture: Path | None) -> dict[str, Any]:
    """v2 inputs from git when the revision is reachable, else from the evidence fixture."""
    if git_available(rev):
        return extract_v2_inputs(rev)
    if fixture is None or not fixture.is_file():
        raise SystemExit(f"revision {rev} is not reachable and no --inputs-fixture was given")
    return json.loads(fixture.read_text(encoding="utf-8"))["v2Inputs"]


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument(
        "--rev", default=V2_PRODUCER_REV, help="commit whose fitter produced the champion"
    )
    ap.add_argument(
        "--archive", default=DEFAULT_ARCHIVE, help="tracked exports/archive bundle to rebuild"
    )
    ap.add_argument(
        "--inputs-fixture", type=Path, default=None, help="evidence JSON carrying v2Inputs"
    )
    ap.add_argument("--json-out", type=Path, default=None)
    ap.add_argument("--skip-board", action="store_true")
    ap.add_argument("--skip-holdout", action="store_true")
    ap.add_argument(
        "--forward-end", default=None, help="last forward day (YYYY-MM-DD); default newest commit"
    )
    ap.add_argument(
        "--holdout-rev", default="HEAD", help="revision whose committed CSVs are scored"
    )
    args = ap.parse_args(argv)

    inputs = load_inputs(args.rev, args.inputs_fixture)
    repro = reproduction_section(inputs)
    cands = build_candidates(repro)
    ref = registry_reference_candidates()
    ref_meta = ref.pop("_meta")
    all_cands: dict[str, Any] = {**cands, **ref}

    result: dict[str, Any] = {
        "finding": "W30-F008",
        "activationStatus": "NOT ACTIVATED",
        "treeRevision": _git("rev-parse", "HEAD").decode("utf-8").strip(),
        "v2Inputs": inputs,
        "reproduction": repro,
        "candidates": {
            k: {sc: list(v) for sc, v in sc_map.items()} for k, sc_map in all_cands.items()
        },
        "registryReference": ref_meta,
        "oracle": oracle_section(all_cands),
        "servedSkew": served_skew_section(cands),
    }
    if not args.skip_board:
        result["board"] = board_section(args.archive, all_cands)
    if not args.skip_holdout:
        hrev = _git("rev-parse", args.holdout_rev).decode("utf-8").strip()
        result["marketShapes"] = market_shape_section(hrev)
        result["holdoutCrossSectional"] = cross_sectional_section(all_cands, hrev)
        end = date.fromisoformat(args.forward_end) if args.forward_end else None
        result["holdoutForward"] = forward_section(cands, end=end, rev=hrev)
        if not args.skip_board:
            result["forwardOrdering"] = forward_ordering_section(cands, hrev)

    text = json.dumps(_round_floats(result), indent=1, sort_keys=True) + "\n"
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(text, encoding="utf-8")
    m = repro
    print(f"reproduces registry v2: {m['reproducesRegistryV2']}")
    for sc in SCOPES:
        print(
            f"  {sc:8s} native {m['native']['masters'][sc]['c']:.4f}/{m['native']['masters'][sc]['s']:.3f}"
            f"  canonical(C0) {m['canonical']['masters'][sc]['c']:.4f}/{m['canonical']['masters'][sc]['s']:.3f}"
        )
    o = result["oracle"]
    print(
        f"oracle: integer mismatches {o['integerMismatches']}, max raw diff {o['maxAbsRawValueDiff']}"
    )
    if "board" in result:
        for name, dd in result["board"]["diffs"].items():
            print(
                f"board {name:22s} changed {dd['rowsValueChanged']:4d}/{dd['comparableRows']}"
                f"  median|%| {100 * dd['metrics']['medianAbsPctValueChange']:.2f}"
                f"  reordered {dd['rowsReordered']}  gates {dd['autopilotBoardImpactPass']}"
            )
    if "holdoutCrossSectional" in result:
        for name, sc in result["holdoutCrossSectional"]["scores"].items():
            print(
                f"holdout {name:22s} {sc['criterion']:.2f} (production evaluator {sc['productionEvaluatorCriterion']:.2f})"
            )
        fw = result["holdoutForward"]
        print(f"forward {fw['start']}..{fw['end']}: {json.dumps(fw['summary'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
