"""Package Value Adjustment — Phase 2 research (owner directive 2026-10-19, Phase 2).

RESEARCH ONLY.  ``geom_q078_v1`` (q = 0.78) stays the production model; nothing
here changes a value, a verdict, a dispatch or a config.  Candidates, criteria
and the decision rule were frozen BEFORE any result in
``docs/valuation/evidence/package_model_phase2_2026-10-19/PREREGISTRATION.md``.

Builds on Phase 1 (``scripts/package_model_hybrid_research.py``) — its model
registry, canonical board builder, point-in-time own-league pricing and box
market-ledger scorer are imported, never re-implemented.

Sections:

* ``large_package``  — why deep packages favour the star: a controlled matrix that
  holds the raw total fixed while varying piece count (1v2 … 1v10) and value
  concentration, the break-even raw multiple each model needs, useful depth versus
  filler at equal count and equal total, the marginal value of the k-th piece, and
  asymmetric multi-piece shapes (2v3, 2v5, 3v6, 4v8);
* ``properties``     — Phase 1's property suite extended to EFD, plus a 1-point
  gain bound, a splitting scan and a concentration-continuity scan;
* ``real_examples``  — real canonical players: genuine starters vs filler, IDP,
  picks and mixed packages;
* ``calibration``    — the preregistered target: stud-oriented SIGNED residual by
  structure bin, relative to the 1v1 control, with bootstrap CIs and a
  chronological holdout, on own-league trades (and, with ``--market-ledger`` on the
  box, the Sharp/KTC ledger);
* ``finder``         — Trade Finder replay per model (``--finder``).

Usage:
    python scripts/package_model_phase2_research.py [--out DIR] [--finder] [--market-ledger]
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import random
import re
import statistics
import sys
from pathlib import Path

# ``RISKIT_APP_DIR``: run from a temp dir against the deployed checkout (box).
REPO = Path(os.environ.get("RISKIT_APP_DIR") or Path(__file__).resolve().parents[1]).resolve()
SCRIPT_DIR = Path(__file__).resolve().parent  # sibling research scripts travel together

if "--market-ledger-only" in sys.argv:
    # Box mode: enforce read-only BEFORE any application module is imported
    # (scripts/research_readonly_guard.py — an audit hook that cannot be removed).
    _gspec = importlib.util.spec_from_file_location(
        "research_readonly_guard", SCRIPT_DIR / "research_readonly_guard.py"
    )
    GUARD = importlib.util.module_from_spec(_gspec)
    sys.modules["research_readonly_guard"] = GUARD
    _gspec.loader.exec_module(GUARD)
    GUARD.install()
else:
    GUARD = None

sys.path.insert(0, str(REPO))

_spec = importlib.util.spec_from_file_location(
    "package_model_hybrid_research", SCRIPT_DIR / "package_model_hybrid_research.py"
)
P1 = importlib.util.module_from_spec(_spec)
sys.modules["package_model_hybrid_research"] = P1
_spec.loader.exec_module(P1)

# ── candidates (frozen in PREREGISTRATION.md §2) ──────────────────────────

Q = 0.78
EFD_P = 1.0 / math.log2(1.0 + Q)  # 1.20210: two equal pieces keep the incumbent's 1 + q


def efd(p: float):
    """Effective-depth p-norm ``(sum v^p)^(1/p)`` = ``T * N_p^(1/p - 1)``."""
    return P1.lp(p)


def effective_count(vals, p: float = EFD_P) -> float:
    """Renyi/Hill effective number of pieces of order p (1 piece -> 1.0)."""
    d = P1._desc(vals)
    t = sum(d)
    if t <= 0:
        return 0.0
    s = sum((v / t) ** p for v in d)
    return s ** (-1.0 / (p - 1.0))


MODELS = {
    m: P1.MODELS[m]
    for m in (
        "RAW",
        "GEOM_78",
        "KTC",
        "BLEND_G75_K25",
        "BLEND_G50_K50",
        "BLEND_G25_K75",
        "FGEOM_70_20",
        "HYBRID_50",
        "GEOM_85",
        "LP_150",
    )
}
for _name, _p, _role in (("EFD_78", EFD_P, "challenger"), ("EFD_115", 1.15, "sensitivity"),
                         ("EFD_130", 1.30, "sensitivity")):  # fmt: skip
    MODELS[_name] = {
        "gap": P1.utility_gap(efd(_p)),
        "family": "efd",
        "monotoneByConstruction": True,
        "note": f"effective-depth p-norm, p = {_p:.5f} ({_role})",
    }

# Utilities (for package-vs-star tables) — None for gap-only models.
UTILITY = {
    "RAW": lambda v: sum(P1._desc(v)),
    "GEOM_78": P1.owa(lambda i: Q**i),
    "FGEOM_70_20": P1.fgeom(0.70, 0.20),
    "HYBRID_50": lambda v: 0.5 * sum(P1._desc(v)) + 0.5 * P1.lp(1.5)(v),
    "GEOM_85": P1.owa(lambda i: 0.85**i),
    "LP_150": P1.lp(1.5),
    "EFD_78": efd(EFD_P),
    "EFD_115": efd(1.15),
    "EFD_130": efd(1.30),
}
CORE = ["GEOM_78", "KTC", "BLEND_G50_K50", "FGEOM_70_20", "HYBRID_50", "EFD_78"]


def adjusted(gf, A, B) -> tuple[float, float, float]:
    ra, rb = sum(A), sum(B)
    g = gf(A, B)
    return g, ra + max(0.0, g - (ra - rb)), rb + max(0.0, (ra - rb) - g)


def level(gf, A, B) -> str:
    g, a, b = adjusted(gf, A, B)
    return P1.level(g, a, b)


# ── 1. large-package investigation ────────────────────────────────────────


def profile(n: int, r: float) -> list[float]:
    """n piece weights summing to 1 with ratio r between consecutive pieces
    (r = 1 even depth; r small = one headliner plus filler)."""
    w = [r**i for i in range(n)]
    s = sum(w)
    return [x / s for x in w]


CONCENTRATION = [1.0, 0.85, 0.7, 0.5, 0.3, 0.15]


def break_even_table() -> dict:
    """Raw multiple of the star a package needs to EQUAL it, by model x n x r.

    Every candidate except KTC is positively homogeneous, so the multiple is
    ``1 / U(profile)`` and does not depend on the star's value."""
    out = {}
    for m, u in UTILITY.items():
        out[m] = {
            str(n): {f"{r:.2f}": round(1.0 / u(profile(n, r)), 3) for r in CONCENTRATION}
            for n in range(1, 11)
        }
    return out


def ktc_break_even(star: float = 9000.0) -> dict:
    """KTC is not homogeneous: bisection on the raw multiple at a given star."""
    out = {}
    for n in range(2, 11):
        row = {}
        for r in CONCENTRATION:
            w = profile(n, r)
            lo, hi = 0.5, 6.0
            for _ in range(50):
                mid = (lo + hi) / 2
                g = P1.KTC_DISPATCH([star], [star * mid * x for x in w])
                lo, hi = (mid, hi) if g > 0 else (lo, mid)
            row[f"{r:.2f}"] = round((lo + hi) / 2, 3)
        out[str(n)] = row
    return out


def star_win_share(gap_cap: float = 0.30, steps: int = 61) -> dict:
    """For 1-for-n, the share of the near-balanced raw window (package raw
    between S/(1+cap) and S*(1+cap)... measured as the larger-side rule the
    benchmark used) in which the star side leads, by concentration."""
    out = {}
    for m in CORE + ["EFD_115", "EFD_130"]:
        gf = MODELS[m]["gap"]
        out[m] = {}
        for n in (2, 3, 4, 6, 8, 10):
            out[m][str(n)] = {}
            for r in CONCENTRATION:
                w = profile(n, r)
                wins = 0
                # raw gap <= cap of the larger side: multiples in [1-cap, 1/(1-cap)]
                lo, hi = 1 - gap_cap, 1 / (1 - gap_cap)
                for k in range(steps):
                    mult = lo + (hi - lo) * k / (steps - 1)
                    g, a, b = adjusted(gf, [9000.0], [9000.0 * mult * x for x in w])
                    wins += P1.leader(g, a, b) == 1
                out[m][str(n)][f"{r:.2f}"] = round(100.0 * wins / steps, 1)
    return out


def marginal_piece(star: float = 9000.0) -> dict:
    """What the k-th piece adds, useful vs negligible.

    Base package: k-1 pieces of value 0.3*star ("starters").  Add one more piece
    of value x.  Reports dU (utility change) and dU/x."""
    out = {}
    for m, u in UTILITY.items():
        rows = {}
        for k in (2, 3, 6, 7, 10):
            base = [0.3 * star] * (k - 1)
            rows[str(k)] = {}
            for label, x in (("1pt", 1.0), ("filler_2pct", 0.02 * star), ("bench_10pct", 0.1 * star),
                             ("starter_30pct", 0.3 * star)):  # fmt: skip
                du = u(base + [x]) - u(base)
                rows[str(k)][label] = {"dU": round(du, 1), "dUoverX": round(du / x, 3)}
        out[m] = rows
    return out


def depth_vs_filler(star: float = 9000.0) -> list[dict]:
    """Equal count and/or equal raw total, different distribution of useful
    and negligible value."""
    S = star
    cases = [
        ("six starters, raw 1.8x", [0.30 * S] * 6),
        ("six starters, raw 1.2x", [0.20 * S] * 6),
        ("six filler, raw 0.3x", [0.05 * S] * 6),
        (
            "2 starters + 4 filler, raw 1.2x",
            [0.5 * S, 0.5 * S, 0.05 * S, 0.05 * S, 0.05 * S, 0.05 * S],
        ),
        ("1 near-star + 5 filler, raw 1.2x", [0.95 * S] + [0.05 * S] * 5),
        ("six even, raw 1.2x (same total as row 2)", [0.20 * S] * 6),
        ("ten starters, raw 2.5x", [0.25 * S] * 10),
        ("ten filler, raw 0.5x", [0.05 * S] * 10),
        ("three good starters, raw 1.3x", [0.5 * S, 0.45 * S, 0.35 * S]),
        ("four starters, raw 1.4x", [0.4 * S, 0.35 * S, 0.35 * S, 0.3 * S]),
    ]
    out = []
    for label, pkg in cases:
        row = {"case": label, "package": [round(v) for v in pkg], "raw": round(sum(pkg)),
               "effectiveCount": round(effective_count(pkg), 2)}  # fmt: skip
        for m in CORE + ["EFD_115", "EFD_130", "GEOM_85", "LP_150"]:
            g, a, b = adjusted(MODELS[m]["gap"], [S], pkg)
            row[m] = {"starLead": round(g), "level": P1.level(g, a, b)}
        out.append(row)
    return out


def asymmetric(star: float = 9000.0) -> list[dict]:
    S = star
    shapes = {
        "2v3": ([S, 0.4 * S], [0.55 * S, 0.5 * S, 0.45 * S]),
        "2v5 useful": ([S, 0.4 * S], [0.35 * S] * 5),
        "2v5 filler-heavy": ([S, 0.4 * S], [0.7 * S, 0.5 * S, 0.1 * S, 0.1 * S, 0.1 * S]),
        "3v6 useful": ([S, 0.6 * S, 0.4 * S], [0.4 * S] * 6),
        "3v6 filler-heavy": (
            [S, 0.6 * S, 0.4 * S],
            [0.9 * S, 0.7 * S, 0.2 * S, 0.2 * S, 0.2 * S, 0.2 * S],
        ),
        "4v8 useful": ([S, 0.7 * S, 0.5 * S, 0.3 * S], [0.4 * S] * 8),
        "4v8 filler-heavy": ([S, 0.7 * S, 0.5 * S, 0.3 * S], [0.9 * S, 0.8 * S] + [0.15 * S] * 6),
    }
    out = []
    for label, (A, B) in shapes.items():
        row = {"shape": label, "A": [round(v) for v in A], "B": [round(v) for v in B],
               "rawA": round(sum(A)), "rawB": round(sum(B))}  # fmt: skip
        for m in CORE + ["GEOM_85"]:
            g, a, b = adjusted(MODELS[m]["gap"], A, B)
            row[m] = {"gapA": round(g), "level": P1.level(g, a, b)}
        out.append(row)
    return out


# ── 2. properties (Phase 1 suite + Phase 2 additions) ─────────────────────


def phase2_properties(seed: int = 20261019, cases: int = 4000) -> dict:
    rng = random.Random(seed)
    out = {}
    for m in MODELS:
        gf = MODELS[m]["gap"]
        eps = 1.0 if MODELS[m]["family"] in ("ktc", "blend") or m == "GEOM_78" else 1e-6
        f = {"onePointGainAboveOne": 0, "addGainAboveAddedValue": 0, "splitHelpsTheSplitter": 0,
             "concentrationJump": 0}  # fmt: skip
        for _ in range(cases):
            A = [float(rng.randint(100, 9999)) for _ in range(rng.randint(1, 8))]
            B = [float(rng.randint(100, 9999)) for _ in range(rng.randint(1, 8))]
            g = gf(A, B)
            if gf(A + [1.0], B) - g > 1.0 + eps:
                f["onePointGainAboveOne"] += 1
            x = float(rng.randint(1, 9999))
            if gf(A + [x], B) - g > x + eps:
                f["addGainAboveAddedValue"] += 1
            # Splitting one of A's assets into two halves must not raise A
            # (that would let a manager manufacture value by unbundling).
            i = rng.randrange(len(A))
            split = A[:i] + A[i + 1 :] + [A[i] / 2, A[i] / 2]
            if gf(split, B) > g + eps:
                f["splitHelpsTheSplitter"] += 1
            # Continuity in concentration: a 0.1% move of value between two of
            # A's pieces moves the gap by at most ~0.1% of the larger side * 2.
            if len(A) >= 2:
                d = 0.001 * min(A[0], A[1])
                moved = [A[0] + d, A[1] - d] + A[2:]
                if abs(gf(moved, B) - g) > 2 * d + eps:
                    f["concentrationJump"] += 1
        out[m] = f
    return {"cases": cases, "seed": seed, "failures": out}


# ── 3. real players ───────────────────────────────────────────────────────


def real_examples(board: dict) -> list[dict]:
    rows = board["rows"]

    def by_cls(cls):
        return sorted(
            ((n, r["value"]) for n, r in rows.items() if r["cls"] == cls), key=lambda x: -x[1]
        )

    off, idp, pk = by_cls("offense"), by_cls("idp"), by_cls("pick")
    used: set[str] = set()

    def near(lst, target, k=1):
        got = []
        for _ in range(k):
            x = min((x for x in lst if x[0] not in used), key=lambda x: abs(x[1] - target))
            used.add(x[0])
            got.append(x)
        return got

    star = off[2]
    used.add(star[0])
    S = star[1]
    cases = [
        ("1-for-6 genuine starters (each ~30% of the star)", [star], near(off, 0.30 * S, 6)),
        ("1-for-6 bench (each ~18%)", [star], near(off, 0.18 * S, 6)),
        ("1-for-6 filler (each ~5%)", [star], near(off, 0.05 * S, 6)),
        ("1-for-3 three starters (~40% each)", [star], near(off, 0.40 * S, 3)),
        ("1-for-4 four starters (~33% each)", [star], near(off, 0.33 * S, 4)),
        ("1-for-10 starters (~22% each)", [star], near(off, 0.22 * S, 10)),
        ("1-for-6: 2 starters + 4 filler", [star], near(off, 0.5 * S, 2) + near(off, 0.05 * S, 4)),
    ]
    istar = idp[0]
    used.add(istar[0])
    cases.append(("IDP 1-for-4 starters", [istar], near(idp, 0.33 * istar[1], 4)))
    cases.append(("IDP 1-for-6 filler", [istar], near(idp, 0.06 * istar[1], 6)))
    cases.append(("star for 3 firsts", [star], near(pk, 0.40 * S, 3)))
    cases.append(
        ("star for 2 firsts + 2 starters", [star], near(pk, 0.35 * S, 2) + near(off, 0.3 * S, 2))
    )
    cases.append(
        (
            "mixed: star for IDP + offense depth (5)",
            [star],
            near(idp, 0.3 * S, 2) + near(off, 0.3 * S, 3),
        )
    )
    out = []
    for label, A, B in cases:
        a, b = [v for _, v in A], [v for _, v in B]
        row = {"case": label, "A": [f"{n} ({v:.0f})" for n, v in A], "B": [f"{n} ({v:.0f})" for n, v in B],
               "rawA": round(sum(a)), "rawB": round(sum(b)), "effectiveCountB": round(effective_count(b), 2)}  # fmt: skip
        for m in CORE + ["GEOM_85"]:
            g, x, y = adjusted(MODELS[m]["gap"], a, b)
            row[m] = {"gapA": round(g), "level": P1.level(g, x, y)}
        out.append(row)
    return out


# ── 4. calibration (preregistered target) ─────────────────────────────────


def structure_bin(A, B) -> str:
    """A = the side receiving FEWER pieces (PREREGISTRATION.md Amendment 1)."""
    nf, nm = len(A), len(B)
    if nf == nm:
        return "equal"
    if nm >= 5:
        return "deep"
    if nf == 1 and nm in (2, 3):
        return "1vN_small"
    return "ordinary"


def orient(A, B):
    """Fewer pieces first: piece count carries no value noise (no winner's curse)."""
    return (A, B) if len(A) <= len(B) else (B, A)


def signed_residual(gf, A, B) -> float:
    g, a, b = adjusted(gf, A, B)
    return g / ((a + b) / 2.0)


def _boot_ci(xs: list[float], rng, n=2000):
    if len(xs) < 2:
        return None
    ms = sorted(statistics.fmean(xs[rng.randrange(len(xs))] for _ in xs) for _ in range(n))
    return [round(ms[int(0.025 * n)], 4), round(ms[int(0.975 * n)], 4)]


BINS = ("1vN_small", "ordinary", "deep", "equal")


def calibration(rows: list[dict], seed: int = 3, models: list[str] | None = None) -> dict:
    """Mean SIGNED residual, consolidating (fewer-pieces) side positive, per
    structure bin, with bootstrap CIs, overall and on an earlier 60% / later 40%
    chronological split.  ``mean = 0`` is the calibration point; negative = the
    model gives consolidation too little, positive = too much.  Equal-count
    trades carry no count signal and are reported for coverage only."""
    rng = random.Random(seed)
    trades = []
    for r in rows:
        A, B = orient(r["A"], r["B"])
        trades.append({**r, "A": A, "B": B, "bin": structure_bin(A, B)})
    trades.sort(key=lambda t: t["ts"])
    cut = int(0.6 * len(trades))
    periods = {"all": trades, "earlier60": trades[:cut], "later40": trades[cut:]}
    out: dict = {"binCounts": {p: {b: sum(1 for t in ts if t["bin"] == b) for b in BINS}
                               for p, ts in periods.items()}, "byModel": {}}  # fmt: skip
    for m in models or list(MODELS):
        gf = MODELS[m]["gap"]
        res = {}
        for pname, ts in periods.items():
            bins = {}
            for b in BINS:
                xs = [signed_residual(gf, t["A"], t["B"]) for t in ts if t["bin"] == b]
                bins[b] = ({"n": 0} if not xs else
                           {"n": len(xs), "meanSigned": round(statistics.fmean(xs), 4),
                            "medianSigned": round(statistics.median(xs), 4),
                            "ci95": None if b == "equal" else _boot_ci(xs, rng)})  # fmt: skip
            res[pname] = bins
        out["byModel"][m] = res
    return out


def split_calibration(rows: list[dict], key: str, seed: int = 5, min_n: int = 30) -> dict:
    """Calibration per value of ``rows[i][key]`` (format / source), core models only,
    where the group has at least ``min_n`` unequal-count trades."""
    groups: dict = {}
    for r in rows:
        groups.setdefault(str(r.get(key)), []).append(r)
    out = {}
    for g, rs in sorted(groups.items()):
        unequal = sum(1 for r in rs if len(r["A"]) != len(r["B"]))
        out[g] = (calibration(rs, seed=seed, models=CORE + ["RAW"]) if unequal >= min_n
                  else {"n": len(rs), "unequal": unequal, "reported": False,
                        "reason": f"fewer than {min_n} unequal-count trades"})  # fmt: skip
    return out


# ── main ──────────────────────────────────────────────────────────────────


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default="docs/valuation/evidence/package_model_phase2_2026-10-19")
    ap.add_argument("--finder", action="store_true", help="replay Trade Finder per model")
    ap.add_argument("--market-ledger", action="store_true", help="box only: Sharp/KTC ledger")
    ap.add_argument("--max-lag-days", type=float, default=7.0)
    ap.add_argument(
        "--local-ktc-archive",
        type=Path,
        default=None,
        help="KTC trade-db archive collected locally",
    )
    ap.add_argument(
        "--local-intel-ledger", type=Path, default=None, help="intel ledger crawled locally"
    )
    ap.add_argument("--player-directory", type=Path, default=None, help="Sleeper /players/nfl dump")
    ap.add_argument(
        "--market-ledger-only",
        action="store_true",
        help="box: grade ONLY the canonical market-trade ledger and print aggregates to stdout "
        "(writes nothing; the repository is public, so output is checked to be aggregate-only)",
    )
    args = ap.parse_args()

    if args.market_ledger_only:
        return market_ledger_only(args.max_lag_days)

    board, prov = P1.latest_board()
    rows, census = P1.trade_rows(args.max_lag_days)
    result = {
        "purpose": "RESEARCH ONLY (Phase 2). geom_q078_v1 stays active; nothing is promoted.",
        "preregistration": "docs/valuation/evidence/package_model_phase2_2026-10-19/PREREGISTRATION.md",
        "generatedBy": "scripts/package_model_phase2_research.py",
        "board": prov,
        "efdP": EFD_P,
        "models": {m: {k: v for k, v in s.items() if k != "gap"} for m, s in MODELS.items()},
        "largePackage": {
            "breakEvenRawMultiple": break_even_table(),
            "breakEvenRawMultipleKtcAtStar9000": ktc_break_even(),
            "starLeadShareNearBalanced": star_win_share(),
            "marginalPiece": marginal_piece(),
            "depthVsFiller": depth_vs_filler(),
            "asymmetric": asymmetric(),
        },
        "properties": phase2_properties(),
        "realExamples": real_examples(board),
        "ownLeagueCalibration": {"census": census, **calibration(rows)},
    }
    if args.market_ledger:
        groups = box_market_groups()
        result["marketLedgerCalibration"] = (
            {"available": False, "reason": "no_market_trade_ledger_on_this_host"}
            if groups is None
            else {
                "origin": "box canonical ledger (read-only)",
                **market_evidence(groups, args.max_lag_days),
            }
        )
    else:
        result["marketLedgerCalibration"] = {
            "available": False,
            "reason": "not_requested (box only: --market-ledger)",
        }
    if args.local_ktc_archive or args.local_intel_ledger:
        groups, lanes = local_market_groups(
            args.local_ktc_archive, args.local_intel_ledger, args.player_directory
        )
        result["publicMarketSample"] = {
            "origin": "collected in this research container from public endpoints (KTC trade database window; "
            "Sleeper public API from the committed Sharp discovery seeds); not the production archive",
            "lanes": lanes,
            **market_evidence(groups, args.max_lag_days),
        }
    if args.finder:
        sys.path.insert(0, str(SCRIPT_DIR))
        import package_model_finder_replay as fr  # noqa: PLC0415

        replay = fr.run(board_raw_path=Path(prov["rawPayload"]), models=MODELS, level=level)
        result["finder"] = {
            "method": fr.__doc__,
            "teams": replay["teams"],
            "timingsSec": replay["timingsSec"],
            "starTargets": replay["starTargets"],
            "comparison": fr.compare(replay),
            "examples": fr.examples(replay),
        }
    out = REPO / args.out
    out.mkdir(parents=True, exist_ok=True)
    (out / "phase2.json").write_text(json.dumps(result, indent=1, default=str) + "\n")
    print(json.dumps({"out": str(out), "ownLeague": census}, indent=1))
    return 0


def _archived_boards() -> list:
    """``[(board_date, path)]`` for every archived raw payload, oldest first."""
    import re  # noqa: PLC0415
    import zipfile  # noqa: PLC0415
    from datetime import datetime  # noqa: PLC0415

    out = []
    for _ts, path in P1._archives():
        with zipfile.ZipFile(path) as zf:
            name = next(n for n in zf.namelist() if re.match(r"dynasty_data_.*\.json$", n))
        d = datetime.strptime(name[len("dynasty_data_") : -len(".json")], "%Y-%m-%d").date()
        out.append((d, path, name))
    return sorted(out)


def market_rows_from_groups(
    groups, *, max_lag_days: float = 7.0, value_key: str = "canonical"
) -> tuple[list[dict], dict]:
    """Single-value-key form of :func:`price_market_groups`."""
    return price_market_groups(groups, max_lag_days=max_lag_days, value_keys=(value_key,))[
        value_key
    ]


def price_market_groups(
    groups, *, max_lag_days: float = 7.0, value_keys=("canonical",), row_extras=None
) -> dict[str, tuple[list[dict], dict]]:
    """Price ledger groups on the canonical board archived STRICTLY before each
    trade (<= ``max_lag_days``), through the eligibility owner
    (``market_trade_eval.residual_eligible``: proven-unique, dynasty, superflex,
    two teams, no unresolved / FAAB / startup pick, no look-ahead).  Coverage is
    all-or-nothing: an asset the board cannot price excludes the trade.

    Memory-bounded for the production host: trades are first assigned to their
    board, then each board is built ONCE, used for every value key, and released
    before the next is built — never more than one board in memory.

    Returns ``{value_key: (rows, audit)}``; rows are aggregate-safe (values, date,
    format tags, source, league) and never leave the process except as aggregates.
    ``row_extras(trade, board)``, when given, adds fields to every row (Phase 3
    asset metadata); without it the rows are exactly the Phase 2 rows."""
    import gc  # noqa: PLC0415
    import zipfile  # noqa: PLC0415
    from collections import Counter  # noqa: PLC0415
    from datetime import datetime, timezone  # noqa: PLC0415

    from src.api.data_contract import build_api_data_contract  # noqa: PLC0415
    from src.trade import market_trade_eval as ev  # noqa: PLC0415

    boards = _archived_boards()

    def new_audit():
        return {
            "groups": len(groups),
            "dedupeState": Counter(),
            "teamCount": Counter(),
            "topology": Counter(),
            "excluded": Counter(),
            "superflex": Counter(),
            "sourceFamilies": Counter(),
            "assetKinds": Counter(),
        }

    audits = {k: new_audit() for k in value_keys}
    pending: dict = {}  # board path -> [(trade, date, board_date, name)]
    for t in groups:
        topo = ev.classify_topology(t)
        for audit in audits.values():
            audit["dedupeState"][t.get("dedupeState")] += 1
            audit["teamCount"][len(t.get("sides") or [])] += 1
            audit["topology"][topo["topology"]] += 1
            audit["superflex"][
                str(((t.get("marketFormat") or {}).get("offense") or {}).get("superflex"))
            ] += 1
            audit["sourceFamilies"]["+".join(sorted(t.get("sourceFamilies") or []))] += 1
            for side in t.get("sides") or []:
                for asset in side:
                    audit["assetKinds"][asset.get("kind")] += 1
        try:
            td = datetime.fromisoformat(str(t.get("occurredDate"))[:10]).date()
        except ValueError:
            for audit in audits.values():
                audit["excluded"]["undated"] += 1
            continue
        prior = [b for b in boards if b[0] < td and (td - b[0]).days <= max_lag_days]
        if not prior:
            for audit in audits.values():
                audit["excluded"]["no_board_strictly_before_within_lag"] += 1
            continue
        d, path, name = prior[-1]
        ok, why = ev.residual_eligible(t, topo, board_date=d, max_board_lag_days=int(max_lag_days))
        if not ok:
            for audit in audits.values():
                audit["excluded"][why] += 1
            continue
        pending.setdefault(path, []).append((t, td, d, name))

    rows_by_key: dict = {k: [] for k in value_keys}
    boards_used = 0
    for path in sorted(pending, key=str):
        items = pending[path]
        with zipfile.ZipFile(path) as zf:
            board = ev.BoardIndex(build_api_data_contract(json.loads(zf.read(items[0][3]))))
        boards_used += 1
        for t, td, _d, _name in items:
            fmt = t.get("marketFormat") or {}
            vendor = fmt.get("vendor") or {}
            te = fmt.get("te") or {}
            for key in value_keys:
                sides = [[board.values(x).get(key) for x in side] for side in t["sides"]]
                if any(v is None for side in sides for v in side) or not all(sides):
                    audits[key]["excluded"]["asset_unpriced_on_point_in_time_board"] += 1
                    continue
                rows_by_key[key].append({
                    "ts": int(datetime.combine(td, datetime.min.time(), timezone.utc).timestamp() * 1000),
                    "date": td.isoformat(),
                    "A": sides[0],
                    "B": sides[1],
                    "source": "+".join(sorted(t.get("sourceFamilies") or [])),
                    "league": t.get("hostLeagueId"),
                    "tep": vendor.get("tepLevel") if vendor.get("tepLevel") is not None else te.get("scoringEdge"),
                    "idp": bool((fmt.get("idp") or {}).get("enabled")),
                    "vft": (t.get("vendorFlags") or {}).get("isUsedInVft"),
                    "hasPick": any(a.get("kind") == "pick" for side in t["sides"] for a in side),
                    "rosterSize": (fmt.get("general") or {}).get("rosterSize"),
                    "teams": (fmt.get("general") or {}).get("teams"),
                    "boardLagDays": (td - _d).days,
                    **(row_extras(t, board) if row_extras else {}),
                })  # fmt: skip
        del board
        gc.collect()

    out = {}
    for key in value_keys:
        rows, audit = rows_by_key[key], audits[key]
        leagues = Counter(r["league"] for r in rows if r["league"])
        audit["graded"] = len(rows)
        audit["boardsUsed"] = boards_used
        audit["dateRange"] = [
            min((r["date"] for r in rows), default=None),
            max((r["date"] for r in rows), default=None),
        ]
        audit["byDate"] = dict(sorted(Counter(r["date"] for r in rows).items()))
        audit["distinctLeagues"] = len(leagues)
        audit["largestLeagueShare"] = (
            round(max(leagues.values()) / len(rows), 3) if rows and leagues else None
        )
        audit["top5LeagueShare"] = (
            round(sum(c for _, c in leagues.most_common(5)) / len(rows), 3)
            if rows and leagues
            else None
        )
        audit["vftConsumed"] = Counter(str(r["vft"]) for r in rows)
        for k in (
            "dedupeState",
            "teamCount",
            "topology",
            "excluded",
            "superflex",
            "sourceFamilies",
            "assetKinds",
        ):
            audit[k] = dict(audit[k])
        out[key] = (rows, audit)
    return out


def market_evidence(groups, max_lag_days: float) -> dict:
    priced = price_market_groups(
        groups, max_lag_days=max_lag_days, value_keys=("canonical", "ktcMarket")
    )
    rows, audit = priced["canonical"]
    out = {"available": True, "valueBasis": "canonical rankDerivedValue", "audit": audit,
           "calibration": calibration(rows)}  # fmt: skip
    # Value-curve control: the SAME trades priced on KTC Market (KTC's published
    # crowd + trades value, offense + picks only).  If the consolidation deficit
    # shrinks on the market's own scale, it belongs to the canonical value curve,
    # not to the package model — and must not be "fixed" inside the package model.
    krows, kaudit = priced["ktcMarket"]
    out["ktcMarketBasisControl"] = {"graded": kaudit["graded"], "excluded": kaudit["excluded"],
                                    "calibration": calibration(krows, models=CORE + ["RAW", "GEOM_85", "LP_150"])}  # fmt: skip
    for key in ("source", "tep", "idp", "hasPick", "vft"):
        out[f"by_{key}"] = split_calibration(rows, key)
    # League-balanced view: at most 3 trades per league, so no single league dominates.
    capped, seen = [], {}
    for r in rows:
        k = r["league"] or f"anon:{len(seen)}"
        if seen.get(k, 0) < 3:
            capped.append(r)
            seen[k] = seen.get(k, 0) + 1
    out["leagueCapped3"] = {"n": len(capped), **calibration(capped, models=CORE + ["RAW"])}
    return out


def local_market_groups(
    ktc_archive: Path | None, intel_ledger: Path | None, player_directory: Path
) -> tuple:
    """Rebuild ledger groups from stores collected IN THIS CONTAINER from public
    endpoints (never production): the KTC trade-database window and the
    Sharp-discovery Sleeper lane, deduplicated together by the ledger owner."""
    from src.trade import market_trade_report as report  # noqa: PLC0415
    from src.trade.market_trade_normalize import IdentityContext  # noqa: PLC0415

    ctx = IdentityContext.from_directory(
        json.loads(player_directory.read_text(encoding="utf-8")),
        source=f"file:{player_directory.name}",
    )
    lanes = []
    if ktc_archive:
        lanes.append("ktc_trade_database")
    if intel_ledger:
        lanes.append("sleeper_sharp_discovery")
    res = report.build_ledger(archive_path=ktc_archive, intel_ledger_path=intel_ledger, lanes=lanes, ctx=ctx,
                              allow_stale_target_scoring=True)  # fmt: skip
    return res["grouping"].groups, {k: v for k, v in (res.get("lanes") or {}).items()}


def box_market_groups() -> list | None:
    """Box only: every dated group in the persisted canonical ledger (read-only)."""
    from src.trade import market_trade_report as report  # noqa: PLC0415

    conn = report.open_canonical_ledger()
    if conn is None:
        return None
    try:
        return [g for g, _fmt in report.read_ledger_window(conn, since_date="2026-07-01")]
    finally:
        conn.close()


_ID_LIKE = re.compile(
    r"\d{9,}|utrade:|player:|mpick:|hostLeagueId|leagueId|ownerId|userId|rosterId"
)
_SHA_KEYS = {"deployedCodeSha"}
_SHA_RE = re.compile(r"^(?:[0-9a-f]{40}|UNKNOWN)$")


def assert_aggregate_only(obj, path: str = "$") -> None:
    """Refuse to emit anything that looks like an identifier (league / user /
    roster / transaction ids, canonical asset ids).  The report is meant to be
    committed to a PUBLIC repository, so it must be counts and statistics only.
    The one exception is the deployed commit SHA, which is public anyway and is
    validated as exactly 40 hex characters."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if _ID_LIKE.search(str(k)):
                raise ValueError(f"identifier-like key at {path}")
            if k in _SHA_KEYS:
                if not (isinstance(v, str) and _SHA_RE.match(v)):
                    raise ValueError(f"unexpected value at {path}.{k}")
                continue
            assert_aggregate_only(v, f"{path}.{k}")
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            assert_aggregate_only(v, f"{path}[{i}]")
    elif isinstance(obj, str) and _ID_LIKE.search(obj):
        raise ValueError(f"identifier-like value at {path}")


def _peak_rss_mb() -> float | None:
    """Peak resident memory of this process (Linux reports KiB)."""
    try:
        import resource  # noqa: PLC0415

        return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0, 1)
    except Exception:  # noqa: BLE001
        return None


def _deployed_sha(app_dir: Path) -> str:
    """The deployed commit, read from ``.git`` files (no subprocess, read-only)."""
    try:
        git = app_dir / ".git"
        head = (git / "HEAD").read_text(encoding="utf-8").strip()
        if head.startswith("ref: "):
            ref = head[5:].strip()
            loose = git / ref
            if loose.exists():
                head = loose.read_text(encoding="utf-8").strip()
            else:
                packed = (git / "packed-refs").read_text(encoding="utf-8")
                head = next(
                    (ln.split()[0] for ln in packed.splitlines() if ln.endswith(" " + ref)), ""
                )
        return head if re.fullmatch(r"[0-9a-f]{40}", head or "") else "UNKNOWN"
    except (OSError, StopIteration):
        return "UNKNOWN"


def market_ledger_only(max_lag_days: float) -> int:
    """Box mode: read the persisted canonical ledger read-only, grade every
    candidate on point-in-time canonical boards, print aggregates only.

    Runs under ``research_readonly_guard`` (installed at import when
    ``--market-ledger-only`` is on the command line): no file write outside a
    private temp dir, read-only SQLite only, no network, no subprocess.  Exit
    3 if the guard refused anything, even if application code swallowed it."""
    from datetime import datetime, timezone  # noqa: PLC0415

    from src.trade import market_trade_report as report  # noqa: PLC0415

    conn = report.open_canonical_ledger()
    if conn is None:
        out = {"available": False, "reason": "no_market_trade_ledger_on_this_host"}
        print(json.dumps(out))
        return 2
    try:
        meta = report.read_ledger_meta(conn)
        groups = [g for g, _fmt in report.read_ledger_window(conn, since_date="2026-07-01")]
    finally:
        conn.close()
    evidence = market_evidence(groups, max_lag_days)
    denied = GUARD.denied() if GUARD is not None else []
    network = [d for d in denied if d["event"].startswith("socket.")]
    fatal = [d for d in denied if not d["event"].startswith("socket.")]
    out = {
        "purpose": "RESEARCH ONLY (Phase 2). geom_q078_v1 stays active; nothing is promoted.",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "deployedCodeSha": _deployed_sha(REPO),
        "researchScript": "scripts/package_model_phase2_research.py --market-ledger-only",
        "readOnlyGuard": {
            "installed": bool(GUARD is not None and GUARD.installed()),
            # Writes / read-write SQLite / subprocess: any one fails the run (exit 3).
            "refusedWriteOrProcessAttempts": len(fatal),
            "refusedWriteOrProcessEvents": sorted({d["event"] for d in fatal}),
            # Network: the board build's own league-context GET
            # (data_contract._resolve_league_context) falls back to defaults;
            # verified to leave canonical values identical (Phase 2 memo §A.1).
            "refusedNetworkAttempts": len(network),
            "refusedNetworkCallers": sorted({d["caller"] for d in network}),
        },
        "peakRssMb": _peak_rss_mb(),
        "ledgerBuiltAt": meta.get("builtAt") or meta.get("built_at"),
        "ledgerDatedGroupsSince20260701": len(groups),
        "marketLedgerCalibration": {"origin": "box canonical ledger (read-only)", **evidence},
    }
    out = json.loads(json.dumps(out, default=str))
    assert_aggregate_only(out)
    print(json.dumps(out, indent=1))
    return 3 if fatal else 0


if __name__ == "__main__":
    raise SystemExit(main())
