"""Hybrid package Value Adjustment research (owner directive 2026-10-19).

RESEARCH ONLY.  Nothing here changes a value, a verdict or the active model:
``geom_q078_v1`` (q = 0.78) stays the authoritative package model and
``ktc_2026_04`` the read-only comparator / rollback.  The owner asked whether
averaging our geometric adjustment with KTC's — or any other hybrid — would be
a better Value Adjustment.  This script answers that on evidence:

1. **Same canonical values for every model.**  The board is the canonical
   Chase Upside board (``rankDerivedValue``) built by the live pipeline
   (``build_api_data_contract``) from the committed raw payload in
   ``exports/latest/``.  KTC's *formula* is applied to those values; KTC's own
   player values are never used.
2. **Candidates.**  RAW (no adjustment); the incumbent geometric model and
   q alternatives; KTC; the owner's weighted blends of the geometric and KTC
   SIGNED GAPS (``w * geomGap + (1 - w) * ktcGap`` — one gap, shown as one
   positive-only adjustment, never two stacked bonuses); the previously studied
   HYBRID_50 (``0.5 * RAW + 0.5 * L1.5 norm`` — NOT a KTC/geometric average);
   and two monotone families that keep a depth floor: the floored geometric
   ``FGEOM(q, f)`` (piece weights ``f + (1 - f) * q**(i-1)``, i.e. a convex
   mix of RAW and GEOM_q utilities) and power weights ``ZIPF(a)`` (``i**-a``).
3. **Mathematical properties** (owner's §4) over a seeded stress suite drawn
   from the canonical board: add / raise monotonicity, side swap, permutation,
   positive scaling, 1-for-1 = raw, and the size of the jump caused by adding a
   1-point asset (continuity).
4. **Shape x scenario bias matrix** — the owner's 17 shapes over superstar,
   starter, bench, IDP-only, full-roster mixed, pick-heavy, low-value-padding
   and similar-value populations, near-balanced, near-tie and large-gap windows.
5. **Own-league completed trades**, each priced on the canonical board
   RECONSTRUCTED from the raw payload archived strictly before the trade (at
   most ``--max-lag-days`` earlier).  The inputs are point-in-time observations;
   the pipeline is today's code, so values are labelled ``reconstructed``, not
   observed.  Residuals with a chronological holdout for every fitted
   parameter, plus a paired bootstrap against the incumbent.

Usage:
    python scripts/package_model_hybrid_research.py [--out DIR] [--quick]
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import math
import os
import random
import re
import statistics
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

# ``RISKIT_APP_DIR`` lets the box run this file from a temp dir against the
# DEPLOYED checkout (scripts/package_model_market_ledger_onbox.sh).
REPO = Path(os.environ.get("RISKIT_APP_DIR") or Path(__file__).resolve().parents[1]).resolve()
sys.path.insert(0, str(REPO))

from src.api.data_contract import build_api_data_contract  # noqa: E402
from src.utils.name_clean import normalize_player_name  # noqa: E402
from src.valuation_math import fairness_bands, package_model  # noqa: E402

LATEST = REPO / "exports" / "latest"
ARCHIVE = REPO / "exports" / "archive"
TRADES = REPO / "data" / "sleeper_last_good.json"

# ── models ────────────────────────────────────────────────────────────────
# Every model is a SIGNED-GAP function: adjusted A minus adjusted B.  The
# positive-only display (one side receives |gap - rawGap|) is derived from it
# by ``as_adjustment`` — the one representation the production interface has.

Gap = Callable[[list[float], list[float]], float]


def _desc(vals) -> list[float]:
    return sorted((float(v) for v in vals if v is not None and float(v) > 0), reverse=True)


def owa(weights: Callable[[int], float]) -> Callable[[list[float]], float]:
    """Ordered-weighted utility ``sum w(i) * v_(i)`` (values descending, i from 0).

    Monotone in adding / raising an asset whenever ``w`` is non-negative and
    non-increasing; positively homogeneous; permutation invariant; 1-for-1 is
    raw iff ``w(0) == 1``.
    """

    def u(vals):
        return sum(weights(i) * v for i, v in enumerate(_desc(vals)))

    return u


def lp(p: float):
    def u(vals):
        d = _desc(vals)
        return sum(v**p for v in d) ** (1 / p) if d else 0.0

    return u


def utility_gap(u) -> Gap:
    return lambda a, b: u(a) - u(b)


def dispatch_gap(model_id: str) -> Gap:
    """The PRODUCTION dispatch (``package_model.adjust_pair``) as a signed gap."""

    def g(a, b):
        sa, sb = _desc(a), _desc(b)
        value, side, displayed = package_model.adjust_pair(sa, sb, model_id=model_id)
        va = value if displayed else 0
        return (sum(sa) + (va if side == 1 else 0)) - (sum(sb) + (va if side == 2 else 0))

    return g


GEOM78_DISPATCH = dispatch_gap(package_model.GEOM_Q078_V1)
KTC_DISPATCH = dispatch_gap(package_model.KTC_2026_04)


def blend(w_geom: float) -> Gap:
    """Owner's averaging idea: ONE blended signed gap over identical raw values."""
    return lambda a, b: w_geom * GEOM78_DISPATCH(a, b) + (1 - w_geom) * KTC_DISPATCH(a, b)


def as_adjustment(a, b, gap: Gap) -> tuple[float, int]:
    """Positive-only form of a signed gap: ``(value, side)`` (side 1 = A)."""
    d = gap(a, b) - (sum(_desc(a)) - sum(_desc(b)))
    if abs(d) < 1e-9:
        return 0.0, 0
    return abs(d), (1 if d > 0 else 2)


def fgeom(q: float, f: float):
    return owa(lambda i: f + (1 - f) * q**i)


MODELS: dict[str, dict] = {}


def _reg(name, gap, family, monotone_by_construction, note=""):
    MODELS[name] = {
        "gap": gap,
        "family": family,
        "monotoneByConstruction": monotone_by_construction,
        "note": note,
    }


_reg("RAW", lambda a, b: sum(_desc(a)) - sum(_desc(b)), "raw", True, "no package adjustment")
_reg("GEOM_78", GEOM78_DISPATCH, "geom", True, "INCUMBENT geom_q078_v1 via production dispatch")
_reg("KTC", KTC_DISPATCH, "ktc", False, "ktc_2026_04 via production dispatch, on canonical values")
for w in (0.75, 0.60, 0.50, 0.40, 0.25):
    _reg(
        f"BLEND_G{int(w * 100)}_K{int(round((1 - w) * 100))}",
        blend(w),
        "blend",
        False,
        f"{w:.0%} geometric gap + {1 - w:.0%} KTC gap (owner averaging idea)",
    )
for q in (0.60, 0.65, 0.70, 0.75, 0.80, 0.82, 0.85, 0.88, 0.90):
    _reg(f"GEOM_{int(round(q * 100))}", utility_gap(owa(lambda i, q=q: q**i)), "geom", True)
_reg("HYBRID_50", utility_gap(lambda v: 0.5 * sum(_desc(v)) + 0.5 * lp(1.5)(v)), "lp", True)
_reg("LP_150", utility_gap(lp(1.5)), "lp", True)
FGEOM_GRID = [
    (q, f) for q in (0.60, 0.65, 0.70, 0.75, 0.78) for f in (0.10, 0.15, 0.20, 0.25, 0.30)
]
for q, f in FGEOM_GRID:
    _reg(
        f"FGEOM_{int(round(q * 100))}_{int(round(f * 100))}",
        utility_gap(fgeom(q, f)),
        "fgeom",
        True,
        f"piece weights {f} + {1 - f} * {q}^(i-1)",
    )
for a_ in (0.50, 0.75, 1.00):
    _reg(f"ZIPF_{int(a_ * 100)}", utility_gap(owa(lambda i, a_=a_: (i + 1) ** -a_)), "zipf", True)

# Models every report table shows; the full grid is in the JSON.
HEADLINE = [
    "RAW",
    "GEOM_78",
    "KTC",
    "BLEND_G75_K25",
    "BLEND_G60_K40",
    "BLEND_G50_K50",
    "BLEND_G40_K60",
    "BLEND_G25_K75",
    "GEOM_85",
    "HYBRID_50",
    "FGEOM_70_20",
    "FGEOM_75_15",
    "ZIPF_75",
]

# ── canonical board ───────────────────────────────────────────────────────


def _git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()
    except Exception:  # noqa: BLE001
        return "UNKNOWN"


def build_board(raw: dict) -> dict:
    contract = build_api_data_contract(raw)
    rows = {}
    for r in contract.get("playersArray") or []:
        v = r.get("rankDerivedValue")
        if isinstance(v, (int, float)) and v > 0:
            rows[r["displayName"]] = {
                "value": float(v),
                "cls": r.get("assetClass"),
                "rank": r.get("canonicalConsensusRank"),
            }
    return {"rows": rows, "aliases": contract.get("pickAliases") or {}}


def latest_board() -> tuple[dict, dict]:
    path = sorted(LATEST.glob("dynasty_data_*.json"))[-1]
    blob = path.read_bytes()
    board = build_board(json.loads(blob))
    prov = {
        "rawPayload": str(path.relative_to(REPO)),
        "rawPayloadSha256": hashlib.sha256(blob).hexdigest(),
        "codeSha": _git_sha(),
        "pricedAssets": len(board["rows"]),
        "byClass": {
            c: sum(1 for r in board["rows"].values() if r["cls"] == c)
            for c in ("offense", "idp", "pick")
        },
    }
    return board, prov


# ── populations / scenario sampling ───────────────────────────────────────


def pools(board: dict) -> dict[str, list[float]]:
    rows = board["rows"].values()
    off = sorted((r["value"] for r in rows if r["cls"] == "offense"), reverse=True)
    idp = sorted((r["value"] for r in rows if r["cls"] == "idp"), reverse=True)
    pk = sorted((r["value"] for r in rows if r["cls"] == "pick"), reverse=True)
    allv = sorted((r["value"] for r in rows), reverse=True)
    return {
        "offense": off,
        "star": off[:24],
        "starter": off[24:150],
        "bench": off[150:],
        "idp": idp,
        "pick": pk,
        "all": allv,
        "low": [v for v in allv if v < 1000],
    }


SHAPES = [
    (1, 1), (1, 2), (1, 3), (1, 4), (1, 6), (1, 10),
    (2, 2), (2, 3), (2, 4), (2, 6), (2, 10),
    (3, 3), (3, 4), (3, 6),
    (4, 4), (4, 6), (5, 10),
]  # fmt: skip


def _draw(rng, pool, n, cap=None):
    cand = (
        pool if cap is None else [v for v in pool if v <= cap] or pool[-max(1, len(pool) // 10) :]
    )
    return [cand[rng.randrange(len(cand))] for _ in range(n)]


def scenario_sampler(p: dict[str, list[float]], name: str):
    """Return ``sample(rng, nf, nm) -> (fewer_side, more_side)``.

    The more-piece side is drawn at or below ``2 x`` the per-piece value that
    would balance the fewer side (and never above its best piece), so deep
    shapes can be near-balanced at all.  Equal shapes draw freely.
    """

    def depth_cap(fewer, nm):
        return min(max(fewer), 2.0 * sum(fewer) / nm)

    def mk(fpool, mpool, extra=None):
        def s(rng, nf, nm):
            fewer = _draw(rng, fpool, nf)
            cap = None if nf == nm else depth_cap(fewer, nm)
            more = _draw(rng, mpool, nm, cap)
            if extra:
                fewer, more = extra(rng, fewer, more)
            return fewer, more

        return s

    if name == "superstar":
        return mk(p["star"], p["starter"] + p["bench"])
    if name == "midtier":
        return mk(p["starter"], p["starter"] + p["bench"])
    if name == "bench_depth":
        return mk(p["bench"], p["bench"])
    if name == "idp_only":
        return mk(p["idp"], p["idp"])
    if name == "mixed_full_roster":
        return mk(p["all"], p["all"])
    if name == "picks":

        def mix(rng, fewer, more):
            # Half the pieces on each side become picks of similar value.
            def swap(side):
                out = []
                for v in side:
                    if rng.random() < 0.5:
                        near = [x for x in p["pick"] if abs(x - v) <= 0.15 * v]
                        out.append(near[rng.randrange(len(near))] if near else v)
                    else:
                        out.append(v)
                return out

            return swap(fewer), swap(more)

        return mk(p["offense"], p["offense"], mix)
    if name == "low_value_padding":

        def pad(rng, fewer, more):
            # The deeper side carries 1-3 low-value pieces (< 1,000) in place of
            # its weakest pieces.
            k = min(len(more) - 1, 1 + rng.randrange(3)) if len(more) > 1 else 0
            more = sorted(more, reverse=True)
            for j in range(k):
                more[-1 - j] = p["low"][rng.randrange(len(p["low"]))]
            return fewer, more

        return mk(p["offense"], p["offense"], pad)
    if name == "similar_values":

        def s(rng, nf, nm):
            c = p["offense"][rng.randrange(len(p["offense"]) // 2)]
            # Pieces within +-10% of a common centre on each side, scaled so the
            # sides can balance: the deeper side's centre is c * nf / nm.
            cm = c * nf / nm
            return (
                [c * (0.9 + 0.2 * rng.random()) for _ in range(nf)],
                [cm * (0.9 + 0.2 * rng.random()) for _ in range(nm)],
            )

        return s
    if name == "random_offense":
        return mk(p["offense"], p["offense"])
    raise ValueError(name)


SCENARIOS = [
    "random_offense",
    "superstar",
    "midtier",
    "bench_depth",
    "idp_only",
    "mixed_full_roster",
    "picks",
    "low_value_padding",
    "similar_values",
]
GAP_WINDOWS = {
    "balanced_le30": (0.0, 0.30),
    "near_tie_le5": (0.0, 0.05),
    "large_30_60": (0.30, 0.60),
}


def leader(gap: float, a: float, b: float) -> int:
    """+1 A ahead, -1 B ahead, 0 within 1% of the larger side (benchmark rule)."""
    return 0 if abs(gap) <= 0.01 * max(a, b) else (1 if gap > 0 else -1)


#: This module (and every historical script that loads it) classifies on the
#: RETIRED fairness_bands_v1 denominator (the larger ADJUSTED side).  Current
#: research obtains levels from the fairness-band owner (``classify_packages`` /
#: ``fairness_base`` + ``classify``); ``tests/scripts/test_research_band_basis_guard.py``
#: allow-lists the historical scripts that intentionally keep this basis.
FAIRNESS_BAND_BASIS = "v1_legacy"


def level_v1_legacy(gap: float, adj_a: float, adj_b: float) -> str:
    """LEGACY (fairness_bands_v1): the band on the larger ADJUSTED side.

    Retained ONLY to reproduce evidence recorded under v1.  The owner's base is
    the larger PACKAGE UTILITY (``fairness_bands.larger_package_utility``); this
    helper passes the owner's ``classify`` the retired base, so its answer is
    not the approved methodology's.  Do not use it in new research.
    """
    return fairness_bands.classify(gap, max(adj_a, adj_b))["level"]


#: Historical name, kept so the frozen Phase 1-3 scripts keep running unchanged.
level = level_v1_legacy

# ── band basis for the level-dependent sections (2026-10-21 re-measurement) ──
# ``docs/valuation/PACKAGE_MODEL_PHASES_1_3_V2_REMEASURE_2026-10-21.md``.  The
# Phase 1-3 call sites classify through :func:`band_level`, which knows the two
# PACKAGES as well as the gap, so it can answer either basis:
#
# * ``v1_legacy`` -- :func:`level_v1_legacy` on the adjusted totals, exactly the
#   recorded evidence.  The MODULE DEFAULT, so the frozen scripts' own ``main``
#   still classify on the recorded basis (their boards are rebuilt by
#   today's pipeline; see the addendum for the exact reproduction).
# * ``current`` -- fairness_bands_v2 from the owner: the incumbent through
#   ``classify_packages``; KTC through ``larger_package_utility(model_id=ktc)``
#   (the owner's own rule for a model with no package utility: its adjusted
#   totals stand in); any other model on ITS OWN package utilities
#   (``fairness_base((U_A, U_B))``, the #1898 rule for a comparator).  A model
#   with no package utility (the BLENDs: a weighted signed gap) takes the owner's
#   utility-less rule, the adjusted totals, so it is v1 == v2 by construction.
#
# Select the basis with :func:`band_basis`; ``scripts/package_model_v2_remeasure.py``
# is the driver that runs both.

BAND_BASES = ("current", "v1_legacy")
_BAND_BASIS = ["v1_legacy"]

#: Per-model package utility ``U(values)`` (any order), for the ``current`` basis.
#: Registered by ``_reg`` below and by the Phase 2 / Phase 3 modules for their
#: own candidates; a model absent here has no package utility.
BAND_UTILITY: dict[str, Callable[[list[float]], float]] = {}


@contextlib.contextmanager
def band_basis(basis: str):
    """Scope the basis :func:`band_level` answers on (in-process, always restored)."""
    if basis not in BAND_BASES:
        raise ValueError(f"unknown band basis {basis!r}; expected one of {BAND_BASES}")
    saved = _BAND_BASIS[0]
    _BAND_BASIS[0] = basis
    try:
        yield
    finally:
        _BAND_BASIS[0] = saved


def current_band_basis() -> str:
    return _BAND_BASIS[0]


def band_level(model: str, gap: float, A, B, *, basis: str | None = None) -> str:
    """The fairness level of ``gap`` (adjusted A minus adjusted B under ``model``)
    for the packages ``A`` / ``B``, on the selected basis (see the block above)."""
    basis = basis or _BAND_BASIS[0]
    a, b = _desc(A), _desc(B)
    if basis == "v1_legacy":
        ra, rb = sum(a), sum(b)
        return level_v1_legacy(gap, ra + max(0.0, gap - (ra - rb)), rb + max(0.0, (ra - rb) - gap))
    if basis != "current":
        raise ValueError(f"unknown band basis {basis!r}; expected one of {BAND_BASES}")
    if model == "GEOM_78":
        return fairness_bands.classify_packages(gap, a, b, model_id=package_model.GEOM_Q078_V1)[
            "level"
        ]
    if model == "KTC":
        base = fairness_bands.larger_package_utility(a, b, model_id=package_model.KTC_2026_04)
        return fairness_bands.classify(gap, base)["level"]
    u = BAND_UTILITY.get(model)
    if u is not None:
        return fairness_bands.classify(gap, fairness_bands.fairness_base((u(a), u(b))))["level"]
    # No package utility (a blend of signed gaps): the owner's utility-less rule.
    ra, rb = sum(a), sum(b)
    stand_in = (ra + max(0.0, gap - (ra - rb)), rb + max(0.0, (ra - rb) - gap))
    return fairness_bands.classify(gap, fairness_bands.fairness_base(stand_in))["level"]


# The same constructors the registry above uses (its gaps are ``U(A) - U(B)``).
BAND_UTILITY["RAW"] = lambda v: sum(_desc(v))
for _q in (0.60, 0.65, 0.70, 0.75, 0.80, 0.82, 0.85, 0.88, 0.90):
    BAND_UTILITY[f"GEOM_{int(round(_q * 100))}"] = owa(lambda i, q=_q: q**i)
BAND_UTILITY["HYBRID_50"] = lambda v: 0.5 * sum(_desc(v)) + 0.5 * lp(1.5)(v)
BAND_UTILITY["LP_150"] = lp(1.5)
for _q, _f in FGEOM_GRID:
    BAND_UTILITY[f"FGEOM_{int(round(_q * 100))}_{int(round(_f * 100))}"] = fgeom(_q, _f)
for _a in (0.50, 0.75, 1.00):
    BAND_UTILITY[f"ZIPF_{int(_a * 100)}"] = owa(lambda i, a_=_a: (i + 1) ** -a_)
assert set(BAND_UTILITY) | {"GEOM_78", "KTC"} | {
    m for m in MODELS if m.startswith("BLEND_")
} == set(MODELS), "every Phase 1 model has a band rule"


@contextlib.contextmanager
def legacy_v1_denominator():
    """LEGACY (fairness_bands_v1) reproduction of a PRODUCTION code path.

    Inside the block ``fairness_bands.larger_package_utility`` answers the retired
    v1 base (``max`` of the two ADJUSTED totals, ``package_model.adjusted_pair_totals``)
    for every caller that reads it through the module (the analyze lenses, the
    decision engine, the Trade Finder), so a measurement that runs the real
    engine reproduces a v1-era number.  In-process only and always restored;
    nothing is written anywhere.  Never wrap a current-methodology measurement in it.

    Process-global (not thread-safe); correct for single-threaded use and for forked
    workers that are created inside the block.  A caller that did ``from ...fairness_bands
    import larger_package_utility`` would not see the rebind: every production caller reads
    it through the module.
    """
    original = fairness_bands.larger_package_utility

    def v1_base(a, b, *, model_id=None):
        a_adj, b_adj, _, _ = package_model.adjusted_pair_totals(
            fairness_bands._require_pieces(a, "side_a_values"),
            fairness_bands._require_pieces(b, "side_b_values"),
            model_id=model_id,
        )
        return fairness_bands.fairness_base((a_adj, b_adj))

    fairness_bands.larger_package_utility = v1_base
    try:
        yield
    finally:
        fairness_bands.larger_package_utility = original


def run_matrix(p, per_cell: int, seed: int) -> dict:
    rng = random.Random(seed)
    names = list(MODELS)
    out: dict = {}
    for win_name, (lo, hi) in GAP_WINDOWS.items():
        for scen in SCENARIOS:
            sampler = scenario_sampler(p, scen)
            for nf, nm in SHAPES:
                if win_name != "balanced_le30" and (nf, nm) == (1, 1):
                    continue
                cases = []
                tries = 0
                while len(cases) < per_cell and tries < per_cell * 400:
                    tries += 1
                    fewer, more = sampler(rng, nf, nm)
                    rf, rm = sum(fewer), sum(more)
                    g = abs(rf - rm) / max(rf, rm)
                    if lo <= g <= hi:
                        # Randomise which side is A so position cannot matter.
                        cases.append((fewer, more) if rng.random() < 0.5 else (more, fewer))
                key = f"{win_name}|{scen}|{nf}v{nm}"
                if len(cases) < per_cell // 4:
                    out[key] = {"cases": len(cases), "unattainable": True}
                    continue
                cell = {"cases": len(cases)}
                for m in names:
                    gf = MODELS[m]["gap"]
                    st = dict(fewer=0, more=0, tie=0, top=0, topk=0, flip=0, rawLead=0,
                              shift=[], lvl={}, sameLvlG78=0, sameLeadG78=0)  # fmt: skip
                    for A, B in cases:
                        ra, rb = sum(A), sum(B)
                        g = gf(A, B)
                        adj_a, adj_b = ra + max(0.0, g - (ra - rb)), rb + max(0.0, (ra - rb) - g)
                        ld = leader(g, adj_a, adj_b)
                        rl = leader(ra - rb, ra, rb)
                        g78 = GEOM78_DISPATCH(A, B)
                        a78, b78 = ra + max(0.0, g78 - (ra - rb)), rb + max(0.0, (ra - rb) - g78)
                        if nf != nm:
                            fewer_is_a = len(A) < len(B)
                            con = 1 if fewer_is_a else -1
                            st["fewer"] += ld == con
                            st["more"] += ld == -con
                            st["tie"] += ld == 0
                        if max(A) != max(B):
                            st["topk"] += 1
                            st["top"] += ld == (1 if max(A) > max(B) else -1)
                        if rl != 0:
                            st["rawLead"] += 1
                            st["flip"] += ld == -rl
                        st["shift"].append(abs(g - (ra - rb)) / max(ra, rb))
                        lv = band_level(m, g, A, B)
                        st["lvl"][lv] = st["lvl"].get(lv, 0) + 1
                        st["sameLvlG78"] += lv == band_level("GEOM_78", g78, A, B)
                        st["sameLeadG78"] += ld == leader(g78, a78, b78)
                    n = len(cases)
                    sh = sorted(st["shift"])
                    cell[m] = {
                        "fewerWins": _pct(st["fewer"], n if nf != nm else 0),
                        "moreWins": _pct(st["more"], n if nf != nm else 0),
                        "even": _pct(st["tie"], n if nf != nm else 0),
                        "topAssetSideWins": _pct(st["top"], st["topk"]),
                        "rawLeaderReversed": _pct(st["flip"], st["rawLead"]),
                        "medianShiftPctOfLarger": round(100 * sh[n // 2], 2),
                        "p95ShiftPctOfLarger": round(100 * sh[min(n - 1, int(0.95 * n))], 2),
                        "levels": st["lvl"],
                        "sameLevelAsIncumbent": _pct(st["sameLvlG78"], n),
                        "sameLeaderAsIncumbent": _pct(st["sameLeadG78"], n),
                    }
                out[key] = cell
    return out


def _pct(n, d):
    return None if not d else round(100.0 * n / d, 2)


# ── mathematical property suite ───────────────────────────────────────────


def run_properties(p, cases: int, seed: int) -> dict:
    rng = random.Random(seed)
    allv = p["all"]
    fails = {
        m: {
            "addToA_worsensA": 0,
            "addToB_worsensB": 0,
            "raiseA_worsensA": 0,
            "raiseB_worsensB": 0,
            "sideSwap": 0,
            "permutation": 0,
            "scale": 0,
            "oneForOneNotRaw": 0,
            "maxJumpFromOnePointAsset": 0.0,
        }
        for m in MODELS
    }
    examples: dict[str, list] = {m: [] for m in MODELS}
    for c in range(cases):
        A = [allv[rng.randrange(len(allv))] for _ in range(1 + rng.randrange(6))]
        B = [allv[rng.randrange(len(allv))] for _ in range(1 + rng.randrange(6))]
        if c % 3 == 0:  # also exercise the uniform range the 2026-10-17 memo used
            A = [float(rng.randint(500, 9999)) for _ in A]
            B = [float(rng.randint(500, 9999)) for _ in B]
        add = allv[rng.randrange(len(allv))]
        raise_by = 1 + rng.randrange(2000)
        ia, ib = rng.randrange(len(A)), rng.randrange(len(B))
        Ar = [v + raise_by if i == ia else v for i, v in enumerate(A)]
        Br = [v + raise_by if i == ib else v for i, v in enumerate(B)]
        k = (0.5, 2.0, 1.37)[c % 3]
        for m, spec in MODELS.items():
            gf = spec["gap"]
            # Integer-rounded production outputs get 1 point of slack per model
            # component; utilities are exact up to float.
            eps = 1.0 if spec["family"] in ("ktc", "blend") or m == "GEOM_78" else 1e-6
            g = gf(A, B)
            f = fails[m]
            if gf(A + [add], B) < g - eps:
                f["addToA_worsensA"] += 1
                if len(examples[m]) < 3:
                    examples[m].append({"A": A, "B": B, "addToA": add})
            if gf(A, B + [add]) > g + eps:
                f["addToB_worsensB"] += 1
            if gf(Ar, B) < g - eps:
                f["raiseA_worsensA"] += 1
            if gf(A, Br) > g + eps:
                f["raiseB_worsensB"] += 1
            if abs(gf(B, A) + g) > eps:
                f["sideSwap"] += 1
            if abs(gf(list(reversed(A)), list(reversed(B))) - g) > eps:
                f["permutation"] += 1
            gs = gf([v * k for v in A], [v * k for v in B])
            if abs(gs - k * g) > (1 + k) * 2 * eps + 1e-6 * abs(g):
                f["scale"] += 1
            if len(A) == 1 and len(B) == 1 and abs(g - (A[0] - B[0])) > eps:
                f["oneForOneNotRaw"] += 1
            jump = max(abs(gf(A + [1.0], B) - g), abs(gf(A, B + [1.0]) - g))
            f["maxJumpFromOnePointAsset"] = max(f["maxJumpFromOnePointAsset"], round(jump, 1))
    return {"cases": cases, "seed": seed, "failures": fails, "addToAExamples": examples}


NAMED = [
    ([7200], [6000]),
    ([7200], [6000, 1]),
    ([7200], [6000, 500]),
    ([9000], [8500, 1]),
    ([8200], [5500, 4900]),
    ([9000], [2000] * 12),
    ([9000], [2500] * 12),
]


def named_cases() -> list[dict]:
    out = []
    for A, B in NAMED:
        row = {
            "A": A if len(A) < 5 else f"{len(A)}x{A[0]}",
            "B": B if len(B) < 5 else f"{len(B)}x{B[0]}",
            "rawGap": sum(A) - sum(B),
        }
        for m in HEADLINE:
            row[m] = round(MODELS[m]["gap"](A, B), 1)
        out.append(row)
    return out


# ── own-league completed trades on a reconstructed canonical board ───────

_ARCHIVE_RE = re.compile(r"dynasty_export_(\d{8})_(\d{6})\.zip$")
_FROM_RE = re.compile(r"\s*\(from [^)]*\)\s*$", re.IGNORECASE)
_SLOT_RE = re.compile(r"^(\d{4}) (\d\.\d\d)$")


def _archives():
    out = []
    for p in ARCHIVE.glob("dynasty_export_*.zip"):
        m = _ARCHIVE_RE.search(p.name)
        if m:
            dt = datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
            out.append((int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000), p))
    return sorted(out)


_BOARDS: dict[Path, dict | None] = {}


def _archived_board(path: Path) -> dict | None:
    if path in _BOARDS:
        return _BOARDS[path]
    board = None
    try:
        with zipfile.ZipFile(path) as zf:
            name = next(n for n in zf.namelist() if re.match(r"dynasty_data_.*\.json$", n))
            board = build_board(json.loads(zf.read(name)))
            board["index"] = {}
            for disp, r in board["rows"].items():
                board["index"][normalize_player_name(disp)] = r["value"]
    except Exception as exc:  # noqa: BLE001 — counted, never priced
        board = {"error": f"{type(exc).__name__}: {exc}"[:200]}
    _BOARDS[path] = board
    return board


def _price(board: dict, label: str) -> float | None:
    name = _FROM_RE.sub("", str(label or "")).strip()
    m = _SLOT_RE.match(name)
    if m:
        name = f"{m.group(1)} Pick {m.group(2)}"
    for cand in (name, board["aliases"].get(name)):
        if cand and cand in board["rows"]:
            return board["rows"][cand]["value"]
    if re.match(r"^\d{4}\s", name):
        return None
    return board["index"].get(normalize_player_name(name))


def trade_rows(max_lag_days: float) -> tuple[list[dict], dict]:
    trades = json.loads(TRADES.read_text())["rosterData"].get("trades") or []
    archives = _archives()
    census = {"trades": len(trades), "notTwoTeam": 0, "noArchiveBefore": 0, "boardTooOld": 0,
              "boardBuildFailed": 0, "unpricedAsset": 0, "graded": 0}  # fmt: skip
    rows = []
    for t in trades:
        sides = t.get("sides") or []
        if len(sides) != 2:
            census["notTwoTeam"] += 1
            continue
        ts = int(t.get("timestamp") or 0)
        prior = [a for a in archives if a[0] < ts]
        if not prior:
            census["noArchiveBefore"] += 1
            continue
        a_ts, a_path = prior[-1]
        if (ts - a_ts) / 86_400_000 > max_lag_days:
            census["boardTooOld"] += 1
            continue
        board = _archived_board(a_path)
        if not board or "error" in board:
            census["boardBuildFailed"] += 1
            continue
        A = [_price(board, x) for x in sides[0].get("got") or []]
        B = [_price(board, x) for x in sides[1].get("got") or []]
        if not A or not B or any(v is None for v in A + B):
            # MISSING IS NEVER ZERO: the trade is excluded and counted.
            census["unpricedAsset"] += 1
            continue
        census["graded"] += 1
        rows.append({"ts": ts, "board": a_path.name, "A": A, "B": B,
                     "assetsA": [_FROM_RE.sub("", x) for x in sides[0]["got"]],
                     "assetsB": [_FROM_RE.sub("", x) for x in sides[1]["got"]],
                     "shape": f"{min(len(A), len(B))}v{max(len(A), len(B))}"})  # fmt: skip
    rows.sort(key=lambda r: r["ts"])
    return rows, census


def residual(gf: Gap, A, B) -> float:
    ra, rb = sum(A), sum(B)
    g = gf(A, B)
    adj_a, adj_b = ra + max(0.0, g - (ra - rb)), rb + max(0.0, (ra - rb) - g)
    return g / ((adj_a + adj_b) / 2.0)


def _summ(xs):
    if not xs:
        return {"n": 0}
    a = sorted(abs(x) for x in xs)
    return {"n": len(a), "meanAbs": round(statistics.fmean(a), 4),
            "medianAbs": round(statistics.median(a), 4),
            "rms": round(math.sqrt(statistics.fmean(x * x for x in a)), 4)}  # fmt: skip


def trade_evidence(rows: list[dict], seed: int, *, detail: bool = True) -> dict:
    multi = [r for r in rows if r["shape"] != "1v1"]
    unequal = [r for r in rows if r["shape"].split("v")[0] != r["shape"].split("v")[1]]
    per_model = {}
    for m, spec in MODELS.items():
        gf = spec["gap"]
        per_model[m] = {
            "all": _summ([residual(gf, r["A"], r["B"]) for r in rows]),
            "multiPiece": _summ([residual(gf, r["A"], r["B"]) for r in multi]),
            "unequalShapes": _summ([residual(gf, r["A"], r["B"]) for r in unequal]),
        }
    # Chronological holdout: each parametric family picks its best member on the
    # EARLIER 60% of multi-piece trades and is scored on the LATER 40%.
    cut = int(0.6 * len(multi))
    fit, test = multi[:cut], multi[cut:]
    families: dict[str, list[str]] = {}
    for m, spec in MODELS.items():
        families.setdefault(spec["family"], []).append(m)
    holdout = {}
    for fam, members in families.items():
        if not fit or not test:
            break
        best = min(
            members,
            key=lambda m: statistics.fmean(
                abs(residual(MODELS[m]["gap"], r["A"], r["B"])) for r in fit
            ),
        )
        holdout[fam] = {
            "chosenOnFit": best,
            "fitMeanAbs": round(statistics.fmean(abs(residual(MODELS[best]["gap"], r["A"], r["B"])) for r in fit), 4),
            "testMeanAbs": round(statistics.fmean(abs(residual(MODELS[best]["gap"], r["A"], r["B"])) for r in test), 4),
        }  # fmt: skip
    if test:
        holdout["incumbent_GEOM_78"] = {
            "testMeanAbs": round(statistics.fmean(abs(residual(GEOM78_DISPATCH, r["A"], r["B"])) for r in test), 4)
        }  # fmt: skip
    # Paired bootstrap: mean|r(model)| - mean|r(GEOM_78)| on multi-piece trades.
    rng = random.Random(seed)
    base = [abs(residual(GEOM78_DISPATCH, r["A"], r["B"])) for r in multi]
    boot = {}
    for m in HEADLINE + [
        "GEOM_70",
        "LP_150",
        "ZIPF_100",
        "FGEOM_65_20",
        "FGEOM_70_15",
        "FGEOM_78_10",
        "ZIPF_50",
    ]:
        if m == "GEOM_78" or not multi:
            continue
        d = [abs(residual(MODELS[m]["gap"], r["A"], r["B"])) - b for r, b in zip(multi, base)]
        samples = sorted(statistics.fmean(d[rng.randrange(len(d))] for _ in d) for _ in range(2000))
        boot[m] = {"meanDiff": round(statistics.fmean(d), 4),
                   "ci95": [round(samples[50], 4), round(samples[1949], 4)],
                   "better": sum(1 for x in d if x < -1e-9), "worse": sum(1 for x in d if x > 1e-9)}  # fmt: skip
    # Trade-history classification impact: level under each model vs incumbent.
    cls = {}
    for m in HEADLINE:
        changed = []
        for r in rows:
            lv = {}
            for name, mid in (("m", m), ("g", "GEOM_78")):
                g = MODELS[mid]["gap"](r["A"], r["B"])
                lv[name] = band_level(mid, g, r["A"], r["B"])
            if lv["m"] != lv["g"]:
                changed.append(f"{r['shape']}: {lv['g']} -> {lv['m']}")
        cls[m] = {"changed": len(changed), "of": len(rows), "examples": changed[:6]}
    return {
        "shapes": {s: sum(1 for r in rows if r["shape"] == s) for s in sorted({r["shape"] for r in rows})},
        "residuals": per_model,
        "chronologicalHoldout": {"fitTrades": len(fit), "testTrades": len(test), "byFamily": holdout},
        "pairedBootstrapVsIncumbent": boot,
        "tradeHistoryLevelChangesVsIncumbent": cls,
        "multiPieceTrades": None if not detail else [
            {"date": datetime.fromtimestamp(r["ts"] / 1000, timezone.utc).date().isoformat(),
             "board": r["board"], "shape": r["shape"],
             "A": [f"{n} ({v:.0f})" for n, v in zip(r["assetsA"], r["A"])],
             "B": [f"{n} ({v:.0f})" for n, v in zip(r["assetsB"], r["B"])],
             "residual": {m: round(residual(MODELS[m]["gap"], r["A"], r["B"]), 3)
                          for m in ("RAW", "GEOM_78", "KTC", "BLEND_G50_K50", "GEOM_70", "FGEOM_70_20", "HYBRID_50")}}
            for r in multi
        ],
        # The residual has no interior optimum in q: it keeps falling as the
        # package collapses toward "only each side's best asset counts", and
        # 1-for-1 trades (which no package model touches) set the noise floor.
        "residualByQExtended": {
            f"{q:.1f}": round(
                statistics.fmean(
                    abs(residual(utility_gap(owa(lambda i, q=q: q**i)), r["A"], r["B"])) for r in multi
                ),
                4,
            )
            for q in (0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)
        }
        if multi
        else {},
        "oneForOneNoiseFloor": _summ(
            [residual(MODELS["RAW"]["gap"], r["A"], r["B"]) for r in rows if r["shape"] == "1v1"]
        ),
        "residualByQ": {m: per_model[m]["multiPiece"].get("meanAbs") for m in MODELS if MODELS[m]["family"] == "geom"},
    }  # fmt: skip


# ── box-only: the Sharp / KTC market-trade ledger ────────────────────────
#
# The decisive independent evidence lives in ``data/market_trades/`` on the
# production box, not in this repository.  ``--market-ledger`` grades every
# candidate on that ledger with the SAME eligibility owner
# (``market_trade_eval.residual_eligible``: proven-unique, dynasty, superflex,
# no look-ahead) and the SAME canonical values (``BoardIndex``), each trade
# priced on the latest archived board dated strictly before it.  It publishes
# AGGREGATES only — never another league's trade contents.


def score_market_trades(graded: list[tuple[dict, object, object]]) -> tuple[list[dict], dict]:
    """``graded``: ``(trade_group, BoardIndex, board_date)`` triples.  Returns
    residual rows (no contents) and an exclusion census.  The incumbent's
    residual is cross-checked against ``market_trade_eval.trade_residual``."""
    from src.trade import market_trade_eval as ev  # noqa: PLC0415

    rows, census = [], {"considered": 0, "graded": 0, "notFullyPriced": 0, "ownerMismatch": 0}
    for t, board, board_date in graded:
        census["considered"] += 1
        ok, why = ev.residual_eligible(t, ev.classify_topology(t), board_date=board_date)
        if not ok:
            census[why] = census.get(why, 0) + 1
            continue
        a, b = ev._orient(t["sides"], board)
        A = [board.values(x).get("canonical") for x in a]
        B = [board.values(x).get("canonical") for x in b]
        if not A or not B or any(v is None for v in A + B):
            census["notFullyPriced"] += 1
            continue
        owner = ev.trade_residual(t, board, "canonical", model_id=package_model.GEOM_Q078_V1)
        if owner is None or abs(owner["relativeResidual"] - residual(GEOM78_DISPATCH, A, B)) > 1e-6:
            census["ownerMismatch"] += 1
        census["graded"] += 1
        ts = datetime.fromisoformat(str(t["occurredDate"])[:10]).replace(tzinfo=timezone.utc)
        rows.append({"ts": int(ts.timestamp() * 1000), "A": A, "B": B,
                     "shape": f"{min(len(A), len(B))}v{max(len(A), len(B))}"})  # fmt: skip
    rows.sort(key=lambda r: r["ts"])
    return rows, census


def market_ledger_evidence(max_lag_days: float) -> dict:
    from src.trade import market_trade_eval as ev  # noqa: PLC0415
    from src.trade import market_trade_report as report  # noqa: PLC0415

    conn = report.open_canonical_ledger()
    if conn is None:
        return {"available": False, "reason": "no_market_trade_ledger_on_this_host"}
    boards = []
    for _ts, path in _archives():
        with zipfile.ZipFile(path) as zf:
            name = next(n for n in zf.namelist() if re.match(r"dynasty_data_.*\.json$", n))
            d = datetime.strptime(name[len("dynasty_data_") : -len(".json")], "%Y-%m-%d").date()
        boards.append((d, path))
    if not boards:
        return {"available": False, "reason": "no_archived_boards"}
    trades = [g for g, _fmt in report.read_ledger_window(conn, since_date=boards[0][0].isoformat())]
    conn.close()
    built: dict[Path, object] = {}
    graded = []
    for t in trades:
        try:
            td = datetime.fromisoformat(str(t.get("occurredDate"))[:10]).date()
        except ValueError:
            continue
        prior = [bd for bd in boards if bd[0] < td and (td - bd[0]).days <= max_lag_days]
        if not prior:
            continue
        d, path = prior[-1]
        if path not in built:
            with zipfile.ZipFile(path) as zf:
                name = next(n for n in zf.namelist() if re.match(r"dynasty_data_.*\.json$", n))
                built[path] = ev.BoardIndex(build_api_data_contract(json.loads(zf.read(name))))
        graded.append((t, built[path], d))
    rows, census = score_market_trades(graded)
    return {
        "available": True,
        "census": census,
        "boardsUsed": len(built),
        "inSampleWarning": "the canonical board votes KTC Trades, which consumes these trades",
        **trade_evidence(rows, seed=11, detail=False),
    }


# ── worked examples on real canonical players ─────────────────────────────


def worked_examples(board: dict) -> list[dict]:
    rows = board["rows"]
    off = sorted(
        ((n, r["value"]) for n, r in rows.items() if r["cls"] == "offense"), key=lambda x: -x[1]
    )
    idp = sorted(
        ((n, r["value"]) for n, r in rows.items() if r["cls"] == "idp"), key=lambda x: -x[1]
    )

    def near(lst, target, skip=()):
        return min((x for x in lst if x[0] not in skip), key=lambda x: abs(x[1] - target))

    out = []

    def add(label, A, B):
        a, b = [v for _, v in A], [v for _, v in B]
        row = {"label": label, "A": [f"{n} ({v:.0f})" for n, v in A], "B": [f"{n} ({v:.0f})" for n, v in B],
               "rawA": round(sum(a)), "rawB": round(sum(b))}  # fmt: skip
        for m in HEADLINE:
            g = MODELS[m]["gap"](a, b)
            row[m] = {"gap": round(g), "level": band_level(m, g, a, b)}
        out.append(row)

    star = off[2]
    used = {star[0]}
    # 1-for-3 / 1-for-2 / 2-for-3 near raw balance
    p1 = near(off, star[1] * 0.42, used)
    used.add(p1[0])
    p2 = near(off, star[1] * 0.36, used)
    used.add(p2[0])
    p3 = near(off, star[1] * 0.30, used)
    used.add(p3[0])
    add("1-for-3: one star for three starters (raw about even)", [star], [p1, p2, p3])
    q1 = near(off, star[1] * 0.55, used)
    used.add(q1[0])
    q2 = near(off, star[1] * 0.5, used)
    used.add(q2[0])
    add("1-for-2: one star for two good starters", [star], [q1, q2])
    s2 = near(off, star[1] * 0.65, used)
    used.add(s2[0])
    r1 = near(off, (star[1] + s2[1]) * 0.36, used)
    used.add(r1[0])
    r2 = near(off, (star[1] + s2[1]) * 0.33, used)
    used.add(r2[0])
    r3 = near(off, (star[1] + s2[1]) * 0.30, used)
    used.add(r3[0])
    add("2-for-3: star + starter for three starters", [star, s2], [r1, r2, r3])
    deep = []
    for k in range(10):
        x = near(off, star[1] * 0.11, used)
        used.add(x[0])
        deep.append(x)
    add("1-for-10: star for ten depth pieces (raw ~10% more depth)", [star], deep)
    d6 = []
    for k in range(6):
        x = near(off, star[1] * 0.18, used)
        used.add(x[0])
        d6.append(x)
    add("1-for-6: star for six depth pieces", [star], d6)
    i1 = idp[0]
    ib = [
        near(idp, i1[1] * 0.36, {i1[0]}),
        near(idp, i1[1] * 0.33, {i1[0]}),
        near(idp, i1[1] * 0.31, {i1[0]}),
    ]
    ib = list(dict.fromkeys(ib))
    add("IDP 1-for-3", [i1], ib)
    return out


# ── matrix aggregation (the committed evidence is aggregates + one CSV) ───

ORDINARY = ["1v2", "1v3", "1v4", "2v3", "2v4", "3v4"]
DEEP = ["1v6", "1v10", "2v6", "2v10", "3v6", "4v6", "5v10"]
EQUAL = ["2v2", "3v3", "4v4"]
REPORT_MODELS = HEADLINE + ["GEOM_60", "GEOM_70", "GEOM_75", "LP_150", "ZIPF_100", "FGEOM_65_20"]
METRICS = [
    "fewerWins",
    "moreWins",
    "topAssetSideWins",
    "rawLeaderReversed",
    "medianShiftPctOfLarger",
    "p95ShiftPctOfLarger",
    "sameLevelAsIncumbent",
    "sameLeaderAsIncumbent",
]


def aggregate_matrix(cells: dict) -> dict:
    """Unweighted mean over attainable cells, per window x shape group (and per
    shape / scenario for the balanced window), for every model."""

    def mean(win, metric, model, shapes=None, scen=None):
        xs = []
        for key, cell in cells.items():
            w, s, sh = key.split("|")
            if w != win or cell.get("unattainable"):
                continue
            if (shapes and sh not in shapes) or (scen and s != scen):
                continue
            v = cell[model][metric]
            if v is not None:
                xs.append(v)
        return round(statistics.fmean(xs), 1) if xs else None

    out: dict = {}
    for win in GAP_WINDOWS:
        out[win] = {
            group: {m: {k: mean(win, k, m, shapes) for k in METRICS} for m in MODELS}
            for group, shapes in (("ordinary", ORDINARY), ("deep", DEEP), ("equal", EQUAL))
        }
    out["balanced_le30_byShape"] = {
        f"{a}v{b}": {m: {k: mean("balanced_le30", k, m, [f"{a}v{b}"]) for k in METRICS[:5]}
                     for m in REPORT_MODELS}
        for a, b in SHAPES
    }  # fmt: skip
    out["balanced_le30_byScenario"] = {
        s: {grp: {m: mean("balanced_le30", "fewerWins", m, shapes, s) for m in REPORT_MODELS}
            for grp, shapes in (("ordinary", ORDINARY), ("deep", DEEP))}
        for s in SCENARIOS
    }  # fmt: skip
    out["unattainableCells"] = sorted(k for k, c in cells.items() if c.get("unattainable"))
    return out


def matrix_csv(cells: dict) -> str:
    lines = ["window,scenario,shape,cases,model," + ",".join(METRICS)]
    for key, cell in cells.items():
        if cell.get("unattainable"):
            continue
        w, s, sh = key.split("|")
        for m in REPORT_MODELS:
            vals = ["" if cell[m][k] is None else str(cell[m][k]) for k in METRICS]
            lines.append(",".join([w, s, sh, str(cell["cases"]), m, *vals]))
    return "\n".join(lines) + "\n"


# ── main ─────────────────────────────────────────────────────────────────


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default="docs/valuation/evidence/package_model_hybrid_2026-10-19")
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--max-lag-days", type=float, default=7.0)
    ap.add_argument(
        "--market-ledger",
        action="store_true",
        help="box only: also grade the Sharp/KTC market-trade ledger (aggregates only)",
    )
    args = ap.parse_args()

    board, prov = latest_board()
    p = pools(board)
    per_cell = 60 if args.quick else 400
    matrix = run_matrix(p, per_cell, seed=20261019)
    props = run_properties(p, 1500 if args.quick else 20000, seed=98232)
    rows, census = trade_rows(args.max_lag_days)
    evidence = trade_evidence(rows, seed=7)

    result = {
        "purpose": "RESEARCH ONLY. No model is promoted; geom_q078_v1 stays active.",
        "generatedBy": "scripts/package_model_hybrid_research.py",
        "board": prov,
        "models": {m: {k: v for k, v in s.items() if k != "gap"} for m, s in MODELS.items()},
        "headline": HEADLINE,
        "properties": props,
        "namedCases": named_cases(),
        "workedExamples": worked_examples(board),
        "matrix": {
            "perCell": per_cell,
            "shapes": [f"{a}v{b}" for a, b in SHAPES],
            "scenarios": SCENARIOS,
            "windows": GAP_WINDOWS,
            "perCellCsv": "matrix_cells.csv (report models only)",
            "aggregates": aggregate_matrix(matrix),
        },  # fmt: skip
        "trades": {
            "census": census,
            "maxLagDays": args.max_lag_days,
            "valueBasis": "reconstructed: today's pipeline over the raw payload archived before the trade",
            **evidence,
        },  # fmt: skip
        "marketTradeLedger": (
            market_ledger_evidence(args.max_lag_days)
            if args.market_ledger
            else {"available": False, "reason": "not_requested (box only: --market-ledger)"}
        ),
    }
    out = REPO / args.out
    out.mkdir(parents=True, exist_ok=True)
    suffix = "_quick" if args.quick else ""
    (out / f"research{suffix}.json").write_text(json.dumps(result, indent=1, default=str) + "\n")
    (out / f"matrix_cells{suffix}.csv").write_text(matrix_csv(matrix))
    print(json.dumps({"out": str(out), "trades": census}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
