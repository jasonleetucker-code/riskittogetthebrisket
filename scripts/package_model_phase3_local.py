#!/usr/bin/env python3
"""Package Value Adjustment research, Phase 3 — LOCAL decision study.  RESEARCH ONLY.

``geom_q078_v1`` (q = 0.78) stays the production model.  Nothing here is wired
into a served path; every candidate is scored in this process only and the
Trade Finder replay restores the production dispatch after every model
(``package_model_finder_replay.installed``).

Question (owner, 2026-10-20): the production market-ledger study found every
package model under-credits the side receiving FEWER pieces, and a homogeneous
power norm ``LP_p`` fits the pooled market better as ``p`` grows.  Is ``LP_150``
(or a nearby stronger-consolidation homogeneous model) a genuinely better
package formula, or only a more aggressive one?  This script answers the parts
that need no ledger, on the current canonical board:

A. mathematical properties on seeded random trades (the Phase 1/2 suite plus
   homogeneity, 1-for-1 identity and continuity);
B. the implied consolidation premium — break-even raw multiple of an even
   n-piece package against one star, and the marginal weight of a 2nd piece;
C. concrete trades built from REAL players on the newest archived board;
D. the Phase 2 Trade Finder replay (same enumeration, scoring swap only,
   context-free) plus fairness-level changes on a fixed random trade sample.

Candidates: the incumbent ``GEOM_78`` (production dispatch), ``KTC`` (production
rollback dispatch), ``LP_125 .. LP_250`` and ``GP_078_150`` / ``GP_090_175``
(Phase 3 families).  ``VG_078_1500`` / ``VG_078_2000`` (geometric shape on value
above a replacement level) are NON-HOMOGENEOUS DIAGNOSTICS, never candidates.

Output: ``docs/valuation/evidence/package_model_phase3_2026-10-20/local.json``
— aggregates, derived numbers and real player NAMES only (no league, user,
roster or team identifiers; checked with ``assert_aggregate_only``).
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import multiprocessing
import random
import re
import shutil
import sys
import tempfile
import time
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
OUT_DEFAULT = "docs/valuation/evidence/package_model_phase3_2026-10-20/local.json"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPT_DIR / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# Phase 3 module (never with --box: this is the local, no-ledger study).  It
# loads Phase 2 (P2) which loads Phase 1 (P1); reuse those, do not reload.
P3 = _load("package_model_phase3_research")
P2 = P3.P2
P1 = P2.P1
FR = _load("package_model_finder_replay")

from src.valuation_math import package_model as pm  # noqa: E402

INCUMBENT = "GEOM_78"
CANDIDATES = [
    "GEOM_78",
    "KTC",
    "LP_125",
    "LP_150",
    "LP_175",
    "LP_200",
    "LP_250",
    "GP_078_150",
    "GP_090_175",
]
DIAGNOSTICS = ["VG_078_1500", "VG_078_2000"]
ALL_MODELS = CANDIDATES + DIAGNOSTICS
DISPATCH = {"GEOM_78", "KTC"}  # production dispatch: integer-rounded adjustments
SEED = 20261020

# ── models ────────────────────────────────────────────────────────────────


def _utility(name: str):
    """The Phase 3 utility for ``name`` (FAMILY / DECOMP name where it exists,
    else built from the same constructor)."""
    for reg in (P3.FAMILY, P3.DECOMP, P3.DIAGNOSTIC):
        if name in reg:
            return reg[name]["u"], "phase3_registry"
    m = re.fullmatch(r"LP_(\d{3})", name)
    if m:
        return P3.lp_u(int(m.group(1)) / 100.0), "built_with_lp_u"
    m = re.fullmatch(r"GP_(\d{3})_(\d{3})", name)
    if m:
        return P3.gp_u(int(m.group(1)) / 100.0, int(m.group(2)) / 100.0), "built_with_gp_u"
    m = re.fullmatch(r"VG_(\d{3})_(\d+)", name)
    if m:
        return P3.vor_u(float(m.group(2)), int(m.group(1)) / 100.0), "built_with_vor_u"
    raise KeyError(name)


def _gap_from_u(u):
    return lambda a, b: u(P1._desc(a)) - u(P1._desc(b))


def build_models() -> dict[str, dict]:
    models: dict[str, dict] = {}
    for m in ALL_MODELS:
        if m in DISPATCH:
            models[m] = {
                "gap": P2.MODELS[m]["gap"],
                "source": "production dispatch (package_model.adjust_pair)",
                "role": "incumbent" if m == INCUMBENT else "candidate (rollback model)",
                "homogeneousByConstruction": m != "KTC",
            }
            continue
        u, src = _utility(m)
        P1.BAND_UTILITY[m] = lambda v, u=u: u(P1._desc(v))  # own-utility v2 base
        diag = m in DIAGNOSTICS
        models[m] = {
            "gap": _gap_from_u(u),
            "source": src,
            "role": "diagnostic_non_homogeneous (never a candidate)" if diag else "candidate",
            "homogeneousByConstruction": not diag,
        }
    return models


def _public(models: dict) -> dict:
    return {m: {k: v for k, v in s.items() if k != "gap"} for m, s in models.items()}


# ── A. mathematical properties ────────────────────────────────────────────

PROPS = (
    "addAssetNeverHurts",
    "raiseValueNeverHurts",
    "orderInvariance",
    "swapNegatesGap",
    "homogeneity",
    "oneForOneIsRawGap",
    "onePointAssetMovesGapAtMostOne",
    "continuityEpsilon",
    "unbundlingNeverHelps",
)


def _trial_plan(rng: random.Random, cases: int) -> list[dict]:
    """Identical random trials for every model."""
    plan = []
    for _ in range(cases):
        A = [float(rng.randint(100, 9999)) for _ in range(rng.randint(1, 8))]
        B = [float(rng.randint(100, 9999)) for _ in range(rng.randint(1, 8))]
        pa, pb = A[:], B[:]
        rng.shuffle(pa)
        rng.shuffle(pb)
        plan.append(
            {
                "A": A,
                "B": B,
                "x": float(rng.randint(1, 9999)),
                "i": rng.randrange(len(A)),
                "d": float(rng.randint(1, 2000)),
                "k": rng.uniform(0.25, 3.0),
                "permA": pa,
                "permB": pb,
                "one": (float(rng.randint(1, 9999)), float(rng.randint(1, 9999))),
            }
        )
    return plan


def properties(models: dict, cases: int = 4000, seed: int = SEED) -> dict:
    plan = _trial_plan(random.Random(seed), cases)
    eps_cont = 0.01
    out = {}
    for m, spec in models.items():
        gf = spec["gap"]
        tol = 1.0 if m in DISPATCH else 1e-6
        fails = dict.fromkeys(PROPS, 0)
        worst = dict.fromkeys(PROPS, 0.0)

        def bad(prop, excess, _f=fails, _w=worst):
            if excess > 0:
                _f[prop] += 1
                _w[prop] = max(_w[prop], excess)

        max_cont = {"1": 0.0, "0.1": 0.0, "0.01": 0.0}
        for t in plan:
            A, B = t["A"], t["B"]
            g = gf(A, B)
            bad("addAssetNeverHurts", (g - gf(A + [t["x"]], B)) - tol)
            bad("addAssetNeverHurts", (gf(A, B + [t["x"]]) - g) - tol)
            raised = A[:]
            raised[t["i"]] += t["d"]
            bad("raiseValueNeverHurts", (g - gf(raised, B)) - tol)
            bad("orderInvariance", abs(gf(t["permA"], t["permB"]) - g) - tol)
            bad("swapNegatesGap", abs(gf(B, A) + g) - tol)
            k = t["k"]
            hk = gf([k * v for v in A], [k * v for v in B])
            bad("homogeneity", abs(hk - k * g) - max(tol * (1 + k), 1e-9 * abs(k * g)))
            a1, b1 = t["one"]
            bad("oneForOneIsRawGap", abs(gf([a1], [b1]) - (a1 - b1)) - tol)
            bad("onePointAssetMovesGapAtMostOne", abs(gf(A + [1.0], B) - g) - (1.0 + tol))
            for e in (1.0, 0.1, eps_cont):
                dlt = abs(gf(A + [e], B) - g)
                key = "1" if e == 1.0 else ("0.1" if e == 0.1 else "0.01")
                max_cont[key] = max(max_cont[key], dlt)
            bad("continuityEpsilon", abs(gf(A + [eps_cont], B) - g) - (eps_cont + tol))
            i = t["i"]
            split = A[:i] + A[i + 1 :] + [A[i] / 2, A[i] / 2]
            bad("unbundlingNeverHelps", (gf(split, B) - g) - tol)
        mand = gf([7200.0], [6000.0, 1.0])
        base = gf([7200.0], [6000.0])
        out[m] = {
            "role": spec["role"],
            "tolerance": tol,
            "failures": fails,
            "passes": {p: cases - fails[p] for p in PROPS},
            "worstExcessOverTolerance": {p: round(v, 4) for p, v in worst.items()},
            "maxGapChangeWhenAddingEpsilon": {k: round(v, 4) for k, v in max_cont.items()},
            "mandatoryCase_7200_vs_6000_plus_1": {
                "gap_7200_vs_6000": round(base, 3),
                "gap_7200_vs_6000_and_1": round(mand, 3),
                "pass": (base - 1.0 - tol) <= mand <= base + tol,
            },
            "totalFailures": sum(fails.values()),
        }
    return {
        "cases": cases,
        "seed": seed,
        "valueRange": [100, 9999],
        "piecesPerSide": [1, 8],
        "toleranceNote": "1.0 for the integer-rounded production dispatch (GEOM_78, KTC), "
        "1e-6 otherwise; homogeneity tolerance scales with k",
        "byModel": out,
    }


# ── B. implied consolidation premium ──────────────────────────────────────


def _break_even(gf, star: float, n: int, lo: float = 0.2, hi: float = 40.0) -> float | None:
    """Raw multiple ``m`` such that n equal pieces of ``star*m/n`` equal the star."""

    def f(m):
        return gf([star], [star * m / n] * n)

    if f(lo) <= 0 or f(hi) > 0:
        return None
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if f(mid) > 0 else (lo, mid)
    return round((lo + hi) / 2, 3)


def consolidation_premium(models: dict) -> dict:
    ns = (2, 3, 4, 6, 8, 10)
    rel = (0.1, 0.3, 0.5, 0.8, 1.0)
    out = {}
    for m, spec in models.items():
        gf = spec["gap"]
        be = {str(int(s)): {str(n): _break_even(gf, s, n) for n in ns} for s in (9000.0, 6000.0)}
        mw = {}
        for s in (9000.0, 6000.0):
            base = gf([s], [s])
            mw[str(int(s))] = {
                f"{r:.1f}": round((gf([s, r * s], [s]) - base) / (r * s), 4) for r in rel
            }
        out[m] = {"breakEvenRawMultiple": be, "secondPieceMarginalWeight": mw}
    return {
        "definition": {
            "breakEvenRawMultiple": "raw total (as a multiple of the star) an even package of n "
            "equal pieces needs for its adjusted value to equal the star's; 1.0 = no premium",
            "secondPieceMarginalWeight": "(gap([S, r*S], [S]) - gap([S], [S])) / (r*S): the "
            "share of a 2nd piece of relative size r that is credited",
        },
        "byModel": out,
    }


# ── C. concrete examples on the current canonical board ──────────────────


def newest_archive() -> tuple[Path, str]:
    zips = sorted((REPO / "exports" / "archive").glob("dynasty_export_*.zip"))
    path = zips[-1]
    with zipfile.ZipFile(path) as zf:
        member = next(n for n in zf.namelist() if re.match(r"dynasty_data_.*\.json$", n))
    return path, member


def load_board(raw: dict) -> dict:
    """``P1.build_board``'s rows (``rankDerivedValue > 0``, keyed by display
    name) plus position / rookie, from ONE contract build."""
    from src.api.data_contract import build_api_data_contract  # noqa: PLC0415

    contract = build_api_data_contract(raw)
    rows = {}
    for r in contract.get("playersArray") or []:
        v = r.get("rankDerivedValue")
        if isinstance(v, (int, float)) and v > 0:
            rows[r["displayName"]] = {
                "value": float(v),
                "cls": r.get("assetClass"),
                "pos": r.get("position"),
                "rookie": bool(r.get("rookie")),
            }
    return rows


def _fmt(side) -> list[str]:
    return [f"{n} ({p}, {v:.0f})" for n, v, p in side]


def _evaluate(models, A, B) -> dict:
    a, b = [v for _, v, _ in A], [v for _, v, _ in B]
    out = {}
    for m, spec in models.items():
        g, x, y = P2.adjusted(spec["gap"], a, b)
        lead = P1.leader(g, x, y)
        out[m] = {
            "gapA": round(g),
            "adjA": round(x),
            "adjB": round(y),
            "level": P1.band_level(m, g, a, b),
            "favours": "A" if lead == 1 else ("B" if lead == -1 else "even"),
        }
    return out


def real_examples(models: dict, rows: dict) -> dict:
    def pool(pred):
        return sorted(
            ((n, r["value"], r["pos"]) for n, r in rows.items() if pred(n, r)),
            key=lambda x: -x[1],
        )

    off = pool(lambda n, r: r["cls"] == "offense")
    idp = pool(lambda n, r: r["cls"] == "idp")
    picks = pool(lambda n, r: r["cls"] == "pick" and "Round" not in n)
    rookies = pool(lambda n, r: r["cls"] == "offense" and r["rookie"])
    filler = [x for x in off if 700 <= x[1] < 1500]

    def near(lst, target, k, used):
        got = []
        for _ in range(k):
            x = min((x for x in lst if x[0] not in used), key=lambda x: abs(x[1] - target))
            used.add(x[0])
            got.append(x)
        return got

    cases = []

    def add(label, kind, A, B, extra=None, without_filler=None):
        """``without_filler``: B minus its filler, to test whether filler alone
        tips the verdict."""
        ev = _evaluate(models, A, B)
        ev0 = _evaluate(models, A, without_filler) if without_filler else None
        ra, rb = sum(v for _, v, _ in A), sum(v for _, v, _ in B)
        near_even = abs(ra - rb) <= 0.10 * max(ra, rb)
        for m, r in ev.items():
            flags = []
            # A decisive verdict on raw-even filler IS correct, so filler cases are exempt.
            if near_even and kind != "star_vs_filler" and r["level"] in ("unfair", "lopsided"):
                flags.append("decisive_verdict_on_raw_near_even_trade")
            if kind == "star_vs_starters" and rb >= ra and r["favours"] == "A":
                if r["level"] in ("unfair", "lopsided"):
                    flags.append("superstar_beats_legit_starters_by_large_margin")
            if kind == "star_vs_filler" and (
                r["favours"] != "A" or r["level"] in ("fair", "slight")
            ):
                flags.append("filler_manufactures_fairness")
            if ev0 is not None:
                r0 = ev0[m]
                r["withoutFiller"] = {k: r0[k] for k in ("gapA", "level", "favours")}
                tipped = r0["favours"] == "A" and r["favours"] != "A"
                if tipped or (r0["level"] != "fair" and r["level"] == "fair"):
                    flags.append("filler_manufactures_fairness")
            r["flags"] = flags
        cases.append(
            {
                "case": label,
                "kind": kind,
                "A": _fmt(A),
                "B": _fmt(B),
                "rawA": round(ra),
                "rawB": round(rb),
                "rawRatioBoverA": round(rb / ra, 3),
                **(extra or {}),
                "models": ev,
            }
        )

    # Near-even consolidation trades (A = fewer pieces).
    u: set = set()
    a = near(off, 6500, 1, u)
    add("1-for-2 near-even", "near_even", a, near(off, 0.54 * a[0][1], 2, u))
    u = set()
    a = near(off, 7500, 1, u)
    add("1-for-3 near-even", "near_even", a, near(off, 0.37 * a[0][1], 3, u))
    u = set()
    a = near(off, 8000, 1, u) + near(off, 3000, 1, u)
    add("2-for-3 near-even", "near_even", a, near(off, 4500, 1, u) + near(off, 3800, 1, u)
        + near(off, 3000, 1, u))  # fmt: skip
    u = set()
    a = near(off, 8500, 1, u) + near(off, 4000, 1, u)
    add("2-for-4 near-even", "near_even", a, near(off, 3300, 4, u))

    # Elite star vs genuine starters / filler.
    star = off[2]
    S = star[1]
    for n, share in ((2, 0.55), (3, 0.40), (4, 0.33), (6, 0.30), (8, 0.25), (10, 0.22)):
        u = {star[0]}
        add(f"elite star vs {n} starters (~{share:.0%} each)", "star_vs_starters", [star],
            near(off, share * S, n, u))  # fmt: skip
    for n in (6, 8, 10):
        u = {star[0]}
        add(f"elite star vs {n} filler (< 1500 each)", "star_vs_filler", [star],
            near(filler, 1000, n, u))  # fmt: skip
    u = {star[0]}
    two = near(off, 0.5 * S, 2, u)
    add("elite star vs 2 starters + 4 filler", "star_vs_starters_plus_filler", [star],
        two + near(filler, 1000, 4, u), without_filler=two)  # fmt: skip

    # Filler sweetener ladder: B is short, then adds 1..4 filler pieces.
    u = set()
    a = near(off, 6000, 1, u)
    b0 = near(off, 5200, 1, u)
    fill = near(filler, 900, 4, u)
    ladder = []
    for k in range(5):
        B = b0 + fill[:k]
        ev = _evaluate(models, a, B)
        ladder.append({"fillerAdded": k, "B": _fmt(B), "rawB": round(sum(v for _, v, _ in B)),
                       "models": ev})  # fmt: skip
    k0 = ladder[0]["models"]
    for m in models:
        f_raw = sum(v for _, v, _ in fill)
        credited = k0[m]["gapA"] - ladder[4]["models"][m]["gapA"]
        first = next((s["fillerAdded"] for s in ladder if s["models"][m]["level"] == "fair"), None)
        for s in ladder:
            s["models"][m]["fillerCreditShare"] = (
                None
                if s["fillerAdded"] == 0
                else round(
                    (k0[m]["gapA"] - s["models"][m]["gapA"])
                    / sum(v for _, v, _ in fill[: s["fillerAdded"]]),
                    3,
                )
            )
        ladder[0]["models"][m]["summary"] = {
            "fillerRawTotal": round(f_raw),
            "creditedOfFourFiller": round(credited),
            "firstFillerCountRatedFair": first,
            "flag_filler_manufactures_fairness": first is not None
            and k0[m]["level"] in ("unfair", "lopsided"),
        }
    filler_ladder = {"A": _fmt(a), "rawA": round(a[0][1]), "steps": ladder}

    # IDP.
    istar = idp[0]
    for n, share in ((2, 0.55), (3, 0.40)):
        u = {istar[0]}
        add(f"IDP star vs {n} IDP starters (~{share:.0%} each)", "star_vs_starters", [istar],
            near(idp, share * istar[1], n, u))  # fmt: skip
    # Rookie / future picks.
    rk = rookies[0]
    u = {rk[0]}
    add("top rookie vs 2 future firsts", "rookie_pick", [rk], near(picks, 0.57 * rk[1], 2, u))
    u = {star[0]}
    add("elite star vs 3 firsts", "star_vs_starters", [star], near(picks, 0.40 * S, 3, u))
    u = {rk[0]}
    add("top rookie vs 1 first + 2 rookies", "rookie_pick", [rk],
        near(picks, 0.45 * rk[1], 1, u) + near(rookies, 0.33 * rk[1], 2, u))  # fmt: skip

    flag_counts = {
        m: {
            f: sum(1 for c in cases if f in c["models"][m]["flags"])
            for f in (
                "decisive_verdict_on_raw_near_even_trade",
                "superstar_beats_legit_starters_by_large_margin",
                "filler_manufactures_fairness",
            )
        }
        for m in models
    }
    return {
        "convention": "A = side giving fewer pieces; gapA = adjusted A minus adjusted B "
        + (
            "(positive favours A); level = fairness_bands_v1 on adjusted totals"
            if P1.current_band_basis() == "v1_legacy"
            else "(positive favours A); level = fairness_bands_v2 (each model on its own "
            "package utilities; KTC on its adjusted totals, the owner's rule)"
        ),
        "cases": cases,
        "fillerSweetenerLadder": filler_ladder,
        "flagCounts": flag_counts,
    }


# ── D. decision replay + fairness reclassification ────────────────────────


def fairness_sample(models: dict, rows: dict, n: int = 2000, seed: int = SEED + 1) -> dict:
    """A fixed random sample of plausible trades (assets drawn from the top 500
    board assets, raw gap <= 25% of the larger side), classified by every model."""
    rng = random.Random(seed)
    vals = sorted((r["value"] for r in rows.values()), reverse=True)[:500]
    trades = []
    while len(trades) < n:
        na = rng.randint(1, 3)
        nb = rng.randint(na, min(na + 4, 7))
        A = rng.sample(vals, na)
        B = rng.sample(vals, nb)
        ra, rb = sum(A), sum(B)
        if abs(ra - rb) <= 0.25 * max(ra, rb):
            trades.append((A, B))
    lv, gaps = {}, {}
    for m, spec in models.items():
        lv[m], gaps[m] = [], []
        for A, B in trades:
            g, x, y = P2.adjusted(spec["gap"], A, B)
            lv[m].append((P1.band_level(m, g, A, B), P1.leader(g, x, y)))
            gaps[m].append(g)
    bins = [P2.structure_bin(*P2.orient(A, B)) for A, B in trades]
    base = lv[INCUMBENT]
    out = {}
    for m in models:
        trans: dict = {}
        changed = flips = 0
        by_bin: dict = {}
        consol = {"towardFewer": 0, "towardMore": 0}
        for i, ((lb, db), (lm, dm)) in enumerate(zip(base, lv[m])):
            trans[f"{lb}->{lm}"] = trans.get(f"{lb}->{lm}", 0) + 1
            ch = lb != lm
            fl = db != 0 and dm != 0 and db != dm
            changed += ch
            flips += fl
            b = by_bin.setdefault(bins[i], {"n": 0, "levelChanged": 0, "leaderFlipped": 0})
            b["n"] += 1
            b["levelChanged"] += ch
            b["leaderFlipped"] += fl
        for (A, B), gi, gm in zip(trades, gaps[INCUMBENT], gaps[m]):
            fa, fb = P2.orient(A, B)
            if len(fa) == len(fb):
                continue
            # Positive = the candidate moves the verdict toward the fewer-pieces side.
            d = (gm - gi) if fa is A else (gi - gm)
            if d > 1:
                consol["towardFewer"] += 1
            elif d < -1:
                consol["towardMore"] += 1
        out[m] = {
            "levelChanged": changed,
            "leaderFlipped": flips,
            "transitions": dict(sorted(trans.items())),
            "levelCounts": {
                k: sum(1 for x, _ in lv[m] if x == k)
                for k in ("fair", "slight", "unfair", "lopsided")
            },
            "byStructureBin": by_bin,
            "unequalCountGapShiftVsIncumbent": consol,
        }
    return {
        "n": n,
        "seed": seed,
        "population": "assets drawn uniformly from the top 500 board values; 1-3 v 1-7 pieces "
        "(more-pieces side >= fewer); raw gap <= 25% of the larger raw side",
        "binCounts": {b: bins.count(b) for b in sorted(set(bins))},
        "byModel": out,
    }


def _replay_chunk(job):
    raw_path, chunk = job
    models = build_models()
    return FR.run(board_raw_path=Path(raw_path), models=models, model_ids=chunk, level=P2.level)


def _merge(parts: list[dict], order: list[str]) -> dict:
    first = parts[0]
    raw, timings = {}, {}
    for p in parts:
        assert p["teams"] == first["teams"] and p["surfaces"] == first["surfaces"]
        raw.update(p["raw"])
        timings.update(p["timingsSec"])
    return {"surfaces": first["surfaces"], "teams": first["teams"], "models": order,
            "timingsSec": timings, "starTargets": first["starTargets"], "raw": raw}  # fmt: skip


def _strip_examples(ex: dict, keep: set[str], per: int = 5) -> dict:
    out = {}
    for mid, by_s in ex.items():
        if mid not in keep:
            continue
        out[mid] = {}
        for s, d in by_s.items():
            out[mid][s] = {
                k: [{kk: vv for kk, vv in t.items() if kk != "team"} for t in v[:per]]
                for k, v in d.items()
            }
    return out


def chunks(models: list[str], workers: int) -> list[list[str]]:
    out: list[list[str]] = [[] for _ in range(workers)]
    for i, m in enumerate(models):
        out[i % workers].append(m)
    return [c for c in out if c]


# ── main ──────────────────────────────────────────────────────────────────


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default=OUT_DEFAULT)
    ap.add_argument("--cases", type=int, default=4000, help="section A random trades")
    ap.add_argument("--sample", type=int, default=2000, help="section D fairness sample")
    ap.add_argument("--workers", type=int, default=4, help="parallel finder-replay processes")
    ap.add_argument("--skip-replay", action="store_true", help="skip the Trade Finder replay")
    args = ap.parse_args()
    assert pm.active_model_id() == pm.GEOM_Q078_V1, "the incumbent must be the active model"
    t0 = time.time()

    zpath, member = newest_archive()
    with zipfile.ZipFile(zpath) as zf:
        blob = zf.read(member)
    raw = json.loads(blob)
    scratch = Path(tempfile.mkdtemp(prefix="pkg_phase3_local_"))
    raw_path = scratch / member
    raw_path.write_bytes(blob)

    models = build_models()
    pool = None
    pending = None
    if not args.skip_replay:
        order = [INCUMBENT] + [m for m in ALL_MODELS if m != INCUMBENT]
        jobs = [(str(raw_path), c) for c in chunks(order, args.workers)]
        pool = multiprocessing.get_context("fork").Pool(len(jobs))
        pending = pool.map_async(_replay_chunk, jobs)

    timings = {}
    t = time.time()
    rows = load_board(raw)
    timings["board"] = round(time.time() - t, 1)
    t = time.time()
    sec_a = properties(models, cases=args.cases)
    timings["A"] = round(time.time() - t, 1)
    t = time.time()
    sec_b = consolidation_premium(models)
    timings["B"] = round(time.time() - t, 1)
    t = time.time()
    sec_c = real_examples(models, rows)
    timings["C"] = round(time.time() - t, 1)
    t = time.time()
    sample = fairness_sample(models, rows, n=args.sample)
    timings["D_sample"] = round(time.time() - t, 1)

    replay_out: dict = {"run": False, "reason": "--skip-replay"}
    if pending is not None:
        parts = pending.get()
        pool.close()
        pool.join()
        replay = _merge(parts, order)
        replay_out = {
            "run": True,
            "context": "context-free only (use_team_context=False): roster capacity / posture "
            "are box-local, so forced-drop and posture effects are excluded by design",
            "harness": "scripts/package_model_finder_replay.py (Phase 2), candidate installed "
            "in-process behind package_model._geom_pair and always restored",
            "surfaces": replay["surfaces"],
            "teamCount": len(replay["teams"]),
            "starTargets": sorted(v for v in replay["starTargets"].values() if v),
            "timingsSec": replay["timingsSec"],
            "comparisonVsIncumbent": FR.compare(replay),
            "examples": _strip_examples(
                FR.examples(replay), {"LP_150", "LP_175", "LP_250", "GP_078_150", "VG_078_2000"}
            ),
        }
    shutil.rmtree(scratch, ignore_errors=True)

    result = {
        "purpose": "RESEARCH ONLY (Phase 3, local). geom_q078_v1 (q = 0.78) stays active; "
        "nothing is promoted.",
        "generatedBy": "scripts/package_model_phase3_local.py",
        "activeModelAtRun": pm.active_model_id(),
        "board": {
            "archive": str(zpath.relative_to(REPO)),
            "member": member,
            "sha256": hashlib.sha256(blob).hexdigest(),
            "pricedAssets": len(rows),
            "byClass": {
                c: sum(1 for r in rows.values() if r["cls"] == c)
                for c in ("offense", "idp", "pick")
            },
        },
        "codeSha": P1._git_sha(),
        "models": _public(models),
        "A_properties": sec_a,
        "B_consolidationPremium": sec_b,
        "C_realExamples": sec_c,
        "D_decisions": {"fairnessSample": sample, "finderReplay": replay_out},
        "timingsSec": {**timings, "total": round(time.time() - t0, 1)},
    }
    # Provenance hashes are public hex digests; everything else must look aggregate.
    P2.assert_aggregate_only({k: v for k, v in result.items() if k not in ("board", "codeSha")})
    P2.assert_aggregate_only({k: v for k, v in result["board"].items() if k != "sha256"})
    out = REPO / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1, default=str) + "\n")
    print(json.dumps({"out": str(out), "timingsSec": result["timingsSec"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
