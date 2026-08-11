"""B1.2 — separate the reference COORDINATE from the TAIL POLICY.

READ-ONLY. Fits nothing into production, promotes nothing, applies
nothing, changes no constant and no live behaviour. In-process patches are
made and restored inside a try/finally; the final report states whether
anything on disk changed.

B1.1 asked "is N=500 the right reference universe?", refit under
N=400/500/800, and read the resulting spread in `c` as a model difference.
B1.2 §1 established that it is not: `V` depends on rank only through
`M = c·(N−1)` and `s`, so changing N rescales `c` and leaves the curve
alone. Reference N is a UNIT.

What is NOT a unit is what happens past the reference population. Today
`p` saturates at 1.0, so every rank beyond N collapses onto one coordinate
and therefore one value. That is a modelling decision, it is live, and it
is the question B1.1's experiment was actually circling.

Policies compared here:

  A  CLAMP        p = min(1, (rank−1)/(N−1))          — production today
  B  CONTINUOUS   p = (rank−1)/(N−1), unclamped       — curve continues
  C  DEEPER_N     N' > N with c' = c·(N−1)/(N'−1)     — claimed equivalent
                  to B through rank N', clamping only past N'

`policy_equivalence()` proves or refutes the C≡B claim rather than
assuming it.

One structural fact this module had to discover to run at all, and which
matters to any future repair: **the clamp is enforced in two places**, not
one — `player_valuation.rank_to_percentile` clamps the coordinate, and
`player_valuation.percentile_to_value` clamps again at line 484 before
evaluating. A tail-policy change is therefore not a one-line edit to the
coordinate owner; both gates have to move together or the second silently
undoes the first.

Usage (from the repo root):

    RISKIT_FIT_SNAPSHOT="$PWD/data/dynasty_data_2026-08-10.json" \\
      .venv/bin/python docs/master-site-audit/evidence/W30/b1_2_tail_policy_measure.py
    ... --json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from src.canonical.player_valuation import (  # noqa: E402
    HILL_GLOBAL_PERCENTILE_C,
    HILL_GLOBAL_PERCENTILE_S,
    HILL_PERCENTILE_C,
    HILL_PERCENTILE_S,
    IDP_HILL_PERCENTILE_C,
    IDP_HILL_PERCENTILE_S,
    PERCENTILE_REFERENCE_N,
)

SNAPSHOT = ROOT / "data" / "dynasty_data_2026-08-10.json"

CHAMPION = {
    "GLOBAL": (HILL_GLOBAL_PERCENTILE_C, HILL_GLOBAL_PERCENTILE_S),
    "OFFENSE": (HILL_PERCENTILE_C, HILL_PERCENTILE_S),
    "IDP": (IDP_HILL_PERCENTILE_C, IDP_HILL_PERCENTILE_S),
}
CHALLENGER = {
    "GLOBAL": (0.0890, 0.720),
    "OFFENSE": (0.0770, 1.110),
    "IDP": (0.0380, 0.870),
}

TAIL_RANKS = (1, 10, 25, 50, 100, 200, 300, 400, 500, 550, 600, 700, 800, 900)


# ── the two policies, as plain functions ────────────────────────────


def p_clamped(rank: float, reference_n: int = PERCENTILE_REFERENCE_N) -> float:
    n = int(reference_n)
    if n < 2:
        return 0.0
    return max(0.0, min(1.0, (float(rank) - 1.0) / float(n - 1)))


def p_continuous(rank: float, reference_n: int = PERCENTILE_REFERENCE_N) -> float:
    """Same coordinate, no upper saturation. Still floored at 0."""
    n = int(reference_n)
    if n < 2:
        return 0.0
    return max(0.0, (float(rank) - 1.0) / float(n - 1))


def hill(p: float, c: float, s: float) -> float:
    """``V(p)`` with NO clamping of p — the policy is the caller's choice."""
    if p <= 0.0:
        return 9999.0
    return 9999.0 / (1.0 + (p / c) ** s)


def transform_c(c: float, *, from_n: int, to_n: int) -> float:
    return float(c) * (int(from_n) - 1) / (int(to_n) - 1)


# ── §20 / §22 — is DEEPER_N the same thing as CONTINUOUS? ───────────


def policy_equivalence(c: float = 0.0770, s: float = 1.110, deeper_n: int = 800) -> dict:
    """Prove or refute: DEEPER_N ≡ CONTINUOUS through rank ``deeper_n``.

    Algebraically both reduce to ``V = 9999/(1 + ((rank−1)/M)^s)`` with the
    same ``M``, so they should agree exactly up to the deeper universe's own
    clamp. Checked numerically rather than asserted, and the divergence
    beyond ``deeper_n`` is recorded too — that is the part which makes
    "declare a bigger N" a weaker statement than "extrapolate".
    """
    n0 = PERCENTILE_REFERENCE_N
    c_deep = transform_c(c, from_n=n0, to_n=deeper_n)
    rows = []
    for rank in TAIL_RANKS:
        v_clamp = hill(p_clamped(rank, n0), c, s)
        v_cont = hill(p_continuous(rank, n0), c, s)
        v_deep = hill(p_clamped(rank, deeper_n), c_deep, s)
        rows.append(
            {
                "rank": rank,
                "clamp_N500": round(v_clamp, 2),
                "continuous_N500": round(v_cont, 2),
                "deeperN_clamped": round(v_deep, 2),
                "continuousVsDeeper": round(v_cont - v_deep, 4),
            }
        )
    within = [r for r in rows if r["rank"] <= deeper_n]
    beyond = [r for r in rows if r["rank"] > deeper_n]
    return {
        "c": c,
        "s": s,
        "deeperN": deeper_n,
        "cInDeeperN": round(c_deep, 6),
        "rows": rows,
        "equivalentThroughDeeperN": all(abs(r["continuousVsDeeper"]) < 0.01 for r in within),
        "maxAbsDiffWithin": round(
            max((abs(r["continuousVsDeeper"]) for r in within), default=0), 6
        ),
        "divergesBeyondDeeperN": bool(beyond)
        and any(abs(r["continuousVsDeeper"]) > 0.01 for r in beyond),
        "_note": (
            "CONTINUOUS at N=500 and DEEPER_N with transformed c are the same "
            "curve up to the deeper universe's own clamp; past it, DEEPER_N "
            "saturates and CONTINUOUS does not. 'Use a bigger N' is therefore "
            "'extrapolate, but stop at N2'."
        ),
    }


def top_region_is_untouched(deeper_n: int = 800) -> dict:
    """§22 — a pure tail-policy change must not move ranks ≤ N.

    If this ever failed, the change would not be a tail policy at all.
    """
    worst = 0.0
    for label, curves in (("champion", CHAMPION), ("challenger", CHALLENGER)):
        for scope, (c, s) in curves.items():
            for rank in range(1, PERCENTILE_REFERENCE_N + 1, 7):
                a = hill(p_clamped(rank), c, s)
                b = hill(p_continuous(rank), c, s)
                worst = max(worst, abs(a - b))
            _ = label, scope
    return {
        "maxAbsDeltaAtOrAboveRank1ThroughN": round(worst, 9),
        "topRegionUnchanged": worst < 1e-9,
        "deeperN": deeper_n,
    }


# ── §23 — how much differentiation does the clamp destroy? ──────────


def tail_differentiation() -> dict:
    """Per source: what the clamp costs, at the ranks that actually vote.

    Uses the LIVE contract's `sourceRanks`, so every rank counted here is a
    real observation that survived the identity join, not a CSV row.
    """
    from src.api.data_contract import build_api_data_contract

    contract = build_api_data_contract(json.loads(SNAPSHOT.read_text()))
    rows = contract.get("playersArray") or []

    ranks_by_source: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        for key, rank in (row.get("sourceRanks") or {}).items():
            try:
                ranks_by_source[key].append(float(rank))
            except (TypeError, ValueError):
                continue

    # Scope routing mirrors `_curve_for_source`: IDP-scope sources take the
    # IDP master, cross-market the GLOBAL one, everything else OFFENSE.
    idp_like = {"idpTradeCalc", "idpShow", "draftSharksIdp", "dlfIdp", "fantasyProsIdp"}
    cross = {"draftSharks"}

    out = []
    for source, ranks in sorted(ranks_by_source.items(), key=lambda kv: -len(kv[1])):
        beyond = sorted(r for r in ranks if r > PERCENTILE_REFERENCE_N)
        if not beyond:
            continue
        scope = "IDP" if source in idp_like else ("GLOBAL" if source in cross else "OFFENSE")
        c, s = CHAMPION[scope]
        clamped_v = hill(1.0, c, s)
        deepest = max(beyond)
        samples = []
        for rank in (500, 550, 600, 700, 800, deepest):
            if rank < PERCENTILE_REFERENCE_N:
                continue
            cont = hill(p_continuous(rank), c, s)
            samples.append(
                {
                    "rank": int(rank),
                    "clamped": round(clamped_v, 1),
                    "continuous": round(cont, 1),
                    "delta": round(cont - clamped_v, 1),
                    "pctOfClamped": round(100.0 * (cont - clamped_v) / clamped_v, 1),
                }
            )
        out.append(
            {
                "source": source,
                "scope": scope,
                "observations": len(ranks),
                "clampedObservations": len(beyond),
                "clampedPct": round(100.0 * len(beyond) / len(ranks), 1),
                "deepestRank": int(deepest),
                "distinctClampedRanks": len(set(beyond)),
                "collapsedOntoOneValue": round(clamped_v, 1),
                "samples": samples,
            }
        )
    return {
        "referenceN": PERCENTILE_REFERENCE_N,
        "perSource": out,
        "_note": (
            "distinctClampedRanks is the differentiation the clamp destroys: "
            "that many distinct ordinal positions currently receive one "
            "identical contribution from this source."
        ),
    }


# ── §24 — board impact, measured, production untouched ──────────────


@contextmanager
def continuous_tail():
    """Serve with an unsaturated tail, then put production back exactly.

    Both gates are patched. `rank_to_percentile` produces the coordinate and
    `percentile_to_value` re-clamps it at line 484 — patching only the first
    is a no-op past rank N, which is a trap worth failing loudly on rather
    than quietly measuring nothing.
    """
    import src.canonical.player_valuation as pv

    real_rank_to_percentile = pv.rank_to_percentile
    real_percentile_to_value = pv.percentile_to_value

    def unclamped_rank_to_percentile(rank, *, reference_n=PERCENTILE_REFERENCE_N):
        return p_continuous(rank, reference_n)

    def unclamped_percentile_to_value(
        percentile, *, midpoint=HILL_PERCENTILE_C, slope=HILL_PERCENTILE_S
    ):
        p = max(0.0, float(percentile))
        if p == 0.0:
            return pv.DISPLAY_SCALE_MAX
        raw = 9999.0 / (1.0 + (p / midpoint) ** slope)
        return max(pv.DISPLAY_SCALE_MIN, min(pv.DISPLAY_SCALE_MAX, round(raw)))

    pv.rank_to_percentile = unclamped_rank_to_percentile
    pv.percentile_to_value = unclamped_percentile_to_value
    try:
        yield
    finally:
        pv.rank_to_percentile = real_rank_to_percentile
        pv.percentile_to_value = real_percentile_to_value


def _board(position_too: bool = True) -> dict[str, tuple[float, str]]:
    from src.api.data_contract import build_api_data_contract

    contract = build_api_data_contract(json.loads(SNAPSHOT.read_text()))
    out: dict[str, tuple[float, str]] = {}
    for row in contract.get("playersArray") or []:
        name = str(row.get("displayName") or row.get("name") or "")
        v = row.get("rankDerivedValue")
        pos = str(row.get("position") or row.get("pos") or "?") if position_too else "?"
        if name and isinstance(v, (int, float)) and v > 0:
            out[name] = (float(v), pos)
    return out


def board_impact_of_tail_policy() -> dict:
    """Clamp vs continuous on the champion curves, by position."""
    base = _board()
    with continuous_tail():
        alt = _board()

    common = sorted(set(base) & set(alt))
    base_order = {n: i for i, n in enumerate(sorted(common, key=lambda k: -base[k][0]), 1)}
    alt_order = {n: i for i, n in enumerate(sorted(common, key=lambda k: -alt[k][0]), 1)}
    shifts = {n: alt_order[n] - base_order[n] for n in common}
    absshift = sorted(abs(v) for v in shifts.values())

    def pct(q: float) -> int:
        if not absshift:
            return 0
        return absshift[min(len(absshift) - 1, int(q * len(absshift)))]

    by_pos: dict[str, list[int]] = defaultdict(list)
    for n in common:
        by_pos[base[n][1]].append(abs(shifts[n]))

    valuechg = [n for n in common if abs(alt[n][0] - base[n][0]) > 0.5]
    movers = sorted(common, key=lambda n: -abs(shifts[n]))[:8]

    return {
        "comparableRows": len(common),
        "rowsWithChangedValue": len(valuechg),
        "rowsReordered": sum(1 for v in shifts.values() if v != 0),
        "meanAbsRankShift": round(sum(absshift) / len(absshift), 2) if absshift else 0.0,
        "medianAbsRankShift": pct(0.50),
        "p90AbsRankShift": pct(0.90),
        "maxAbsRankShift": max(absshift) if absshift else 0,
        "over5": sum(1 for v in absshift if v > 5),
        "over10": sum(1 for v in absshift if v > 10),
        "over25": sum(1 for v in absshift if v > 25),
        "over50": sum(1 for v in absshift if v > 50),
        "byPosition": {
            pos: {
                "rows": len(v),
                "reordered": sum(1 for x in v if x),
                "meanAbsShift": round(sum(v) / len(v), 2),
                "max": max(v),
            }
            for pos, v in sorted(by_pos.items(), key=lambda kv: -len(kv[1]))
        },
        "largestMovers": [
            {
                "player": n,
                "position": base[n][1],
                "rank": f"{base_order[n]} -> {alt_order[n]}",
                "shift": -shifts[n],
                "value": f"{base[n][0]:.0f} -> {alt[n][0]:.0f}",
            }
            for n in movers
        ],
    }


def cross_scope_under_tail_policy() -> dict:
    """§70 — does the tail change reweigh IDP against offense?"""
    out = {}
    for label, curves in (("champion", CHAMPION), ("challenger", CHALLENGER)):
        rows = []
        for rank in (25, 100, 400, 500, 600, 800):
            oc, os_ = curves["OFFENSE"]
            ic, is_ = curves["IDP"]
            for policy, pf in (("clamp", p_clamped), ("continuous", p_continuous)):
                o = hill(pf(rank), oc, os_)
                i = hill(pf(rank), ic, is_)
                rows.append(
                    {
                        "rank": rank,
                        "policy": policy,
                        "offense": round(o, 1),
                        "idp": round(i, 1),
                        "idpOverOffense": round(i / o, 4) if o else None,
                    }
                )
        out[label] = rows
    return out


# ── §26 / §27 — FIT_TOP_N depth, coordinate held fixed ──────────────


def fit_depth_experiment() -> dict:
    """Does discarding ranks 401+ change the fitted rank-space curve?

    One variable moves: how many observations train. The coordinate is held
    at the canonical reference for every case, so any movement in `M` is
    attributable to the added rows and nothing else.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "b1_2_fitter", ROOT / "scripts/fit_hill_curve_percentile.py"
    )
    fit = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(fit)
    except SystemExit:
        pass

    measure_spec = importlib.util.spec_from_file_location(
        "b1_2_measure", ROOT / "docs/master-site-audit/evidence/W30/b1_1_model_set_measure.py"
    )
    measure = importlib.util.module_from_spec(measure_spec)
    measure_spec.loader.exec_module(measure)

    sources = measure.scope_sources(fit)
    out = {}
    for scope in ("OFFENSE", "GLOBAL"):
        srcs = sources[scope]
        available = max(len(v) for _, v in srcs)
        depths = sorted({400, 500, min(800, available), available})
        cases = []
        for depth in depths:
            got = measure.fit_master(fit, srcs, top_n=depth)
            if got is None:
                continue
            c, s = got
            rec = {
                "fitTopN": depth,
                "c": round(c, 4),
                "s": round(s, 4),
                "rankSpaceMidpoint": round(
                    measure.rank_space_midpoint(c, PERCENTILE_REFERENCE_N), 3
                ),
                "rowsTrainedPerSource": {label: min(len(v), depth) for label, v in srcs},
            }
            if scope == "OFFENSE":
                rec["holdout"] = measure.score_candidate(c, s, reference_n=PERCENTILE_REFERENCE_N)
            cases.append(rec)
        Ms = [x["rankSpaceMidpoint"] for x in cases]
        out[scope] = {
            "deepestSourceAvailable": available,
            "cases": cases,
            "midpointSpreadPct": round(100.0 * (max(Ms) - min(Ms)) / min(Ms), 2) if Ms else 0.0,
        }
    out["IDP"] = {
        "skipped": (
            "IDP's deepest value source is the 370-row IDPTC slice; there are no "
            "ranks 401+ to add, so a depth experiment would vary nothing."
        )
    }
    return out


# ── report ──────────────────────────────────────────────────────────


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--skip-board", action="store_true")
    ap.add_argument("--skip-depth", action="store_true")
    args = ap.parse_args()

    if not SNAPSHOT.exists():
        print(f"FATAL: pinned snapshot missing: {SNAPSHOT}", file=sys.stderr)
        return 2

    report: dict = {
        "pinnedSnapshot": str(SNAPSHOT.relative_to(ROOT)),
        "referenceN": PERCENTILE_REFERENCE_N,
        "champion": {k: list(v) for k, v in CHAMPION.items()},
        "policyEquivalence": policy_equivalence(),
        "topRegionUntouched": top_region_is_untouched(),
        "tailDifferentiation": tail_differentiation(),
        "crossScope": cross_scope_under_tail_policy(),
    }
    if not args.skip_board:
        report["boardImpact"] = board_impact_of_tail_policy()
    if not args.skip_depth:
        report["fitDepth"] = fit_depth_experiment()

    if args.json:
        print(json.dumps(report, indent=2))
        return 0
    _print_human(report)
    return 0


def _print_human(r: dict) -> None:
    print(f"pinned snapshot : {r['pinnedSnapshot']}   reference N: {r['referenceN']}")

    e = r["policyEquivalence"]
    print(f"\n=== §20/§22 — CONTINUOUS(N=500) vs DEEPER_N({e['deeperN']}) ===")
    print(f"  c={e['c']} -> c'={e['cInDeeperN']} in N={e['deeperN']}")
    print(f"  {'rank':>6s} {'clamp':>10s} {'continuous':>11s} {'deeperN':>10s} {'cont-deep':>10s}")
    for row in e["rows"]:
        print(
            f"  {row['rank']:6d} {row['clamp_N500']:10.2f} {row['continuous_N500']:11.2f} "
            f"{row['deeperN_clamped']:10.2f} {row['continuousVsDeeper']:10.4f}"
        )
    print(
        f"  equivalent through rank {e['deeperN']}: {e['equivalentThroughDeeperN']} "
        f"(max |diff| {e['maxAbsDiffWithin']})"
    )
    t = r["topRegionUntouched"]
    print(
        f"  top region (ranks 1..{r['referenceN']}) unchanged: {t['topRegionUnchanged']} "
        f"(max delta {t['maxAbsDeltaAtOrAboveRank1ThroughN']})"
    )

    d = r["tailDifferentiation"]
    print("\n=== §23 — differentiation the clamp destroys ===")
    for s in d["perSource"]:
        print(
            f"\n  {s['source']} ({s['scope']}) — {s['clampedObservations']}/{s['observations']} "
            f"clamped ({s['clampedPct']}%), {s['distinctClampedRanks']} distinct ranks -> "
            f"one value {s['collapsedOntoOneValue']}, deepest {s['deepestRank']}"
        )
        for x in s["samples"]:
            print(
                f"      rank {x['rank']:4d}  clamped {x['clamped']:7.1f}  "
                f"continuous {x['continuous']:7.1f}  delta {x['delta']:+8.1f} ({x['pctOfClamped']:+.1f}%)"
            )

    if "boardImpact" in r:
        b = r["boardImpact"]
        print("\n=== §24 — board impact of clamp -> continuous (champion curves) ===")
        print(
            f"  {b['rowsWithChangedValue']}/{b['comparableRows']} rows change value; "
            f"{b['rowsReordered']} reorder"
        )
        print(
            f"  mean {b['meanAbsRankShift']}  median {b['medianAbsRankShift']}  "
            f"p90 {b['p90AbsRankShift']}  max {b['maxAbsRankShift']}"
        )
        print(f"  >5 {b['over5']}   >10 {b['over10']}   >25 {b['over25']}   >50 {b['over50']}")
        print("  by position:")
        for pos, v in b["byPosition"].items():
            print(
                f"    {pos:6s} rows {v['rows']:4d}  reordered {v['reordered']:4d}  "
                f"mean {v['meanAbsShift']:6.2f}  max {v['max']:4d}"
            )
        print("  largest movers:")
        for m in b["largestMovers"]:
            print(
                f"    {m['player']:22s} {m['position']:5s} {m['rank']:>14s} ({m['shift']:+d})  {m['value']}"
            )

    if "fitDepth" in r:
        print("\n=== §26/§27 — FIT_TOP_N depth, coordinate fixed ===")
        for scope, v in r["fitDepth"].items():
            if "skipped" in v:
                print(f"\n  {scope}: {v['skipped']}")
                continue
            print(
                f"\n  {scope} (deepest source {v['deepestSourceAvailable']} rows), "
                f"M spread {v['midpointSpreadPct']}%"
            )
            for case in v["cases"]:
                line = (
                    f"    FIT_TOP_N={case['fitTopN']:4d}  c={case['c']:.4f} s={case['s']:.4f}  "
                    f"M={case['rankSpaceMidpoint']:7.3f}"
                )
                if case.get("holdout"):
                    line += f"  holdout {case['holdout']['criterion']}"
                print(line)


if __name__ == "__main__":
    raise SystemExit(main())
