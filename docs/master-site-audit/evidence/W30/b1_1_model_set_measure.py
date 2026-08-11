"""B1.1 — model-set evidence extension for the W30-F008 percentile repair.

READ-ONLY. Fits nothing into production, promotes nothing, applies
nothing, writes no constant. Every number here is measured in-process on
the pinned inputs `b1_denominator_measure.py` records.

B1 established that fit, holdout and serving now share one percentile
coordinate, and produced a challenger. It also produced a recommendation
of MORE EVIDENCE REQUIRED, on three grounds: GLOBAL and IDP have no
holdout at all, IDP extrapolates over a quarter of its served universe,
and one of the two IDP training sources observes only its top 29%.

This script answers the questions that verdict left open:

  Q4  IDP fit-vs-serve coordinate trace — is the IDP scope's coordinate
      CONSISTENT with serving, INTENTIONAL BUT DIFFERENT, or a DEFECT?
  Q5  Tail policy — what does the p=1.0 clamp actually do to the live
      board, measured rather than reasoned about?
  §18 Reference-universe candidates — refit under alternative universes
      and score each against the one real holdout.
  §30 Source-depth sensitivity — leave-one-source-out per scope, and the
  §31 effect of a source that observes only the top of the curve.
  §39 Coherent model sets — the board impact of promoting the VALIDATED
  §43 scope alone versus all three together.

Usage (from the repo root):

    RISKIT_FIT_SNAPSHOT="$PWD/data/dynasty_data_2026-08-10.json" \\
      .venv/bin/python docs/master-site-audit/evidence/W30/b1_1_model_set_measure.py

    ... --json     machine-readable, same numbers
"""

from __future__ import annotations

import argparse
import json
import sys
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
    rank_to_percentile,
)
from src.model_registry.holdout import FIT_TOP_N  # noqa: E402

CHAMPION = {
    "GLOBAL": (HILL_GLOBAL_PERCENTILE_C, HILL_GLOBAL_PERCENTILE_S),
    "OFFENSE": (HILL_PERCENTILE_C, HILL_PERCENTILE_S),
    "IDP": (IDP_HILL_PERCENTILE_C, IDP_HILL_PERCENTILE_S),
}

# From B1's refit on these same pinned inputs (B1_CHALLENGER_EVIDENCE.md §3).
CHALLENGER = {
    "GLOBAL": (0.0890, 0.720),
    "OFFENSE": (0.0770, 1.110),
    "IDP": (0.0380, 0.870),
}

SNAPSHOT = ROOT / "data" / "dynasty_data_2026-08-10.json"


# ── the fitter, imported rather than reimplemented ──────────────────


def _fitter():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "fit_hill_curve_percentile_b11", ROOT / "scripts/fit_hill_curve_percentile.py"
    )
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except SystemExit:
        pass
    return mod


def scope_sources(fit) -> dict[str, list[tuple[str, list[float]]]]:
    """``{scope: [(label, descending values)]}`` — the fit's real inputs.

    Derived from the fitter's own tables plus the two entries it builds
    in code (IDPTC's snapshot-filtered IDP slice, and GLOBAL's
    DraftSharks concatenation), so a source added upstream appears here
    without this file being edited.
    """
    out: dict[str, list[tuple[str, list[float]]]] = {"GLOBAL": [], "OFFENSE": [], "IDP": []}
    for label, (rel, col) in fit.OFFENSE_SOURCES.items():
        out["OFFENSE"].append((label, fit._load_values(ROOT / rel, col)))
    for label, (rel, col) in fit.GLOBAL_SOURCES.items():
        out["GLOBAL"].append((label, fit._load_values(ROOT / rel, col)))
    out["GLOBAL"].append(("DraftSharks-Combined", fit._load_draftsharks_combined_values()))
    for label, (rel, col) in fit.IDP_CSV_SOURCES.items():
        out["IDP"].append((label, fit._load_values(ROOT / rel, col)))
    out["IDP"].append(("IDPTradeCalc-IDP", fit._load_idptc_idp_values()))
    return out


def fit_master(
    fit,
    sources: list[tuple[str, list[float]]],
    *,
    top_n: int = FIT_TOP_N,
    reference_n: int = PERCENTILE_REFERENCE_N,
) -> tuple[float, float] | None:
    """Refit a scope master, with the truncation and universe as knobs.

    ``top_n`` selects WHICH observations train. ``reference_n`` is the
    universe they are measured against. B1's whole point is that those
    are different questions; this makes both settable so §18 can vary one
    without disturbing the other.
    """
    per_source: list[tuple[str, float, float]] = []
    for label, values in sources:
        vs = list(values[:top_n])
        if len(vs) < 2:
            continue
        top = vs[0]
        if top <= 0:
            continue
        ps = [rank_to_percentile(i + 1, reference_n=reference_n) for i in range(len(vs))]
        pairs = [(ps[i], vs[i] / top * 9999.0) for i in range(len(vs))]
        c, s, _ = fit._fit(pairs)
        per_source.append((label, c, s))
    if not per_source:
        return None
    got = fit._fit_scope_master("scope", per_source)
    return None if got is None else (got[0], got[1])


# ── Q4 / Q5 — coordinates and the tail ──────────────────────────────


def q4_coordinate_trace(sources: dict[str, list[tuple[str, list[float]]]]) -> dict:
    """What percentile range does each scope's fit OBSERVE, and what does
    serving ASK it for?

    Both sides use the identical mapping after B1, so any gap here is a
    coverage gap, not a coordinate mismatch — which is exactly the
    distinction Q4 exists to make.
    """
    per_scope = {}
    for scope, srcs in sources.items():
        rows = []
        deepest_p = 0.0
        for label, values in srcs:
            n_trained = min(len(values), FIT_TOP_N)
            p_max = rank_to_percentile(n_trained) if n_trained >= 2 else 0.0
            deepest_p = max(deepest_p, p_max)
            rows.append(
                {
                    "source": label,
                    "rowsAvailable": len(values),
                    "rowsTrained": n_trained,
                    "truncated": len(values) > FIT_TOP_N,
                    "pMaxObserved": round(p_max, 4),
                    "rankMaxObserved": n_trained,
                }
            )
        per_scope[scope] = {
            "sources": rows,
            "pMaxObservedByAnySource": round(deepest_p, 4),
            "pMaxServed": 1.0,
            "extrapolatedFractionOfUniverse": round(1.0 - deepest_p, 4),
            "firstExtrapolatedRank": int(deepest_p * (PERCENTILE_REFERENCE_N - 1)) + 2,
        }
    return per_scope


def q5_tail_clamp() -> dict:
    """How much of the LIVE board is served at the clamped percentile?

    ``rank_to_percentile`` clamps to 1.0, so every rank past
    ``PERCENTILE_REFERENCE_N`` receives an identical percentile and
    therefore an identical value from that source. This counts the real
    contract's ``sourceRanks``, not the CSVs — a row only serves if it
    survived the identity join.
    """
    from collections import Counter

    from src.api.data_contract import build_api_data_contract

    raw = json.loads(SNAPSHOT.read_text())
    contract = build_api_data_contract(raw)
    rows = contract.get("playersArray") or []

    total: Counter[str] = Counter()
    clamped: Counter[str] = Counter()
    clamped_rows: set[str] = set()
    for row in rows:
        name = str(row.get("displayName") or row.get("name") or "")
        for key, rank in (row.get("sourceRanks") or {}).items():
            try:
                r = float(rank)
            except (TypeError, ValueError):
                continue
            total[key] += 1
            if r > PERCENTILE_REFERENCE_N:
                clamped[key] += 1
                clamped_rows.add(name)

    per_source = [
        {
            "source": key,
            "observations": n,
            "clamped": clamped[key],
            "clampedPct": round(100.0 * clamped[key] / n, 1),
        }
        for key, n in sorted(total.items(), key=lambda kv: -kv[1])
    ]
    obs = sum(total.values())
    cl = sum(clamped.values())

    # What the clamp costs in value terms: the widest rank span that maps
    # to one percentile, per source, and the value the curve would have
    # produced at the far end if the universe extended that far.
    worst = max(per_source, key=lambda d: d["clampedPct"]) if per_source else None

    return {
        "referenceN": PERCENTILE_REFERENCE_N,
        "overallRankLimit": _overall_rank_limit(),
        "totalObservations": obs,
        "clampedObservations": cl,
        "clampedPct": round(100.0 * cl / obs, 1) if obs else 0.0,
        "distinctBoardRowsTouched": len(clamped_rows),
        "boardRows": len(rows),
        "perSource": per_source,
        "worstSource": worst,
    }


def _overall_rank_limit() -> int:
    from src.api.data_contract import OVERALL_RANK_LIMIT

    return int(OVERALL_RANK_LIMIT)


# ── §18 — reference-universe candidates ─────────────────────────────


def evaluate_offense_master(c: float, s: float):
    from src.model_registry.holdout import evaluate_offense_master as _ev

    return _ev(c, s)


def holdout_score(c: float, s: float) -> dict:
    """Score an OFFENSE curve on the four held-out retail boards."""
    res = evaluate_offense_master(c, s)
    return {
        "criterion": round(res.criterion, 2),
        "perBoard": {k: round(v, 2) for k, v in res.per_source.items()},
        "skipped": dict(res.skipped),
    }


def s18_reference_universe(fit, sources) -> dict:
    """Refit every scope under candidate reference universes.

    The universe is the one modelling choice B1 did NOT make: it unified
    fit and serve onto 500 because 500 is what serving already used, not
    because 500 was shown to be right. These are the defensible
    candidates, each scored where a score exists.
    """
    candidates = {
        "500 (current — serving's fixed reference pool)": PERCENTILE_REFERENCE_N,
        "400 (FIT_TOP_N — the deepest row any fit trains on)": FIT_TOP_N,
        "800 (OVERALL_RANK_LIMIT — the deepest rank the board publishes)": _overall_rank_limit(),
    }
    out = {}
    for label, ref_n in candidates.items():
        scopes = {}
        for scope, srcs in sources.items():
            got = fit_master(fit, srcs, reference_n=ref_n)
            if got is None:
                continue
            c, s = got
            entry = {"c": round(c, 4), "s": round(s, 4)}
            if scope == "OFFENSE":
                # The holdout scores in the CANONICAL coordinate, so a
                # curve fit against a different universe must be scored
                # in the universe it will actually be served in. Scoring
                # it in its own coordinate would grade every candidate on
                # its own private scale and make them incomparable —
                # which is the original W30-F008 defect wearing a hat.
                entry["holdoutInServingCoordinate"] = holdout_score(c, s)
            scopes[scope] = entry
        out[label] = scopes
    out["_note"] = (
        "Only OFFENSE has a holdout. GLOBAL and IDP constants are reported "
        "for completeness and are NOT validated by anything here."
    )
    return out


def s18_unanimity_sweep(
    *, s: float = HILL_PERCENTILE_S, lo: float = 0.024, hi: float = 0.120, step: float = 0.004
) -> dict:
    """Sweep ``c`` and separate "lower mean" from "better on every board".

    Two guards live here, and §18's conclusion depends on both.

    The DEGENERATE check answers the obvious objection to a criterion
    that improves as values fall: if it were monotone, a curve returning
    ~0 would win it, and the whole comparison would be measuring nothing.
    It is not monotone — there is an interior optimum — and this records
    that rather than asserting it.

    The UNANIMITY check separates "the mean improved" from "every held-out
    board improved". They diverge, and the divergence is the promotion
    decision: three of the four boards keep improving well past the point
    where PFKDynasty turns around. ADR-008 narrowed a claim over exactly
    this and the narrowing is prose in a note, not a gate in
    ``promotion.py``.
    """
    champion = evaluate_offense_master(HILL_PERCENTILE_C, HILL_PERCENTILE_S)
    base = dict(champion.per_source)

    rows = []
    c = lo
    while c <= hi + 1e-9:
        res = evaluate_offense_master(c, s)
        deltas = {k: res.per_source[k] - base[k] for k in base}
        rows.append(
            {
                "c": round(c, 4),
                "criterion": round(res.criterion, 2),
                "unanimous": all(v < 0 for v in deltas.values()),
                "deltaVsChampion": {k: round(v, 1) for k, v in sorted(deltas.items())},
            }
        )
        c += step

    degenerate = [
        {"c": dc, "criterion": round(evaluate_offense_master(dc, s).criterion, 2)}
        for dc in (0.0200, 0.0100, 0.0020, 0.0005)
    ]

    unan = [r for r in rows if r["unanimous"]]
    best_mean = min(rows, key=lambda r: r["criterion"])
    best_unan = min(unan, key=lambda r: r["criterion"]) if unan else None
    return {
        "slopeHeld": s,
        "championCriterion": round(champion.criterion, 2),
        "championPerBoard": {k: round(v, 2) for k, v in sorted(base.items())},
        "sweep": rows,
        "unanimousRange": (
            {"lo": min(r["c"] for r in unan), "hi": max(r["c"] for r in unan)} if unan else None
        ),
        "bestUnanimous": best_unan,
        "bestMean": best_mean,
        "degenerateCheck": degenerate,
        "_note": (
            "degenerateCheck exists so 'lower is better' cannot be trusted "
            "blindly: if the criterion were monotone in falling values, a "
            "curve returning ~0 would win it. It does not — these score far "
            "worse than the champion — so the interior optimum is real."
        ),
    }


# ── §30 / §31 — source-depth sensitivity ────────────────────────────


def s30_leave_one_source_out(fit, sources) -> dict:
    """Per scope: refit without each source, and score where possible.

    Two different questions share this machinery.

    (1) For OFFENSE, dropping a TRAINING source and scoring the result on
        the untouched holdout is a real generalisation test.
    (2) For GLOBAL and IDP there is no holdout, so the only honest
        measure is how far the master MOVES when a source leaves — a
        sensitivity number, not a quality number. A master that swings
        wildly on one source's absence is resting on that source.
    """
    out = {}
    for scope, srcs in sources.items():
        full = fit_master(fit, srcs)
        if full is None:
            continue
        fc, fs = full
        entry = {
            "full": {"c": round(fc, 4), "s": round(fs, 4)},
            "sourceCount": len(srcs),
            "dropped": [],
        }
        if scope == "OFFENSE":
            entry["full"]["holdout"] = holdout_score(fc, fs)
        for i, (label, _values) in enumerate(srcs):
            reduced = srcs[:i] + srcs[i + 1 :]
            got = fit_master(fit, reduced)
            if got is None:
                continue
            c, s = got
            depth = min(len(_values), FIT_TOP_N)
            rec = {
                "without": label,
                "sourceDepth": depth,
                "pMaxObserved": round(rank_to_percentile(depth), 4),
                "c": round(c, 4),
                "s": round(s, 4),
                # How far the curve moves, in the only units that matter:
                # served value at representative ranks.
                "valueShiftPct": {
                    str(r): round(100.0 * (_hill_at(r, c, s) / _hill_at(r, fc, fs) - 1.0), 1)
                    for r in (25, 100, 400)
                },
            }
            if scope == "OFFENSE":
                rec["holdout"] = holdout_score(c, s)
            entry["dropped"].append(rec)
        out[scope] = entry
    return out


def _hill_at(rank: int, c: float, s: float) -> float:
    p = rank_to_percentile(rank)
    if p <= 0.0:
        return 9999.0
    return 9999.0 / (1.0 + (p / c) ** s)


# ── §39–§43 — coherent model sets ───────────────────────────────────


def s39_coherent_model_sets() -> dict:
    """Board impact of the two defensible promotion sets.

    B1 measured ALL THREE scopes moving together. The other coherent
    option is promoting only the scope that has out-of-sample evidence
    (OFFENSE) and leaving GLOBAL and IDP on the champion. That is not a
    compromise for its own sake — it is the set whose every member is
    validated. Its cost is that it changes the cross-scope BALANCE, which
    is a real objection and is measured here rather than asserted.
    """
    sets = {
        "OFFENSE-only (every member validated)": {
            "GLOBAL": CHAMPION["GLOBAL"],
            "OFFENSE": CHALLENGER["OFFENSE"],
            "IDP": CHAMPION["IDP"],
        },
        "all three (B1's full challenger)": CHALLENGER,
    }
    out = {}
    for label, curves in sets.items():
        out[label] = _board_impact(curves)
    out["_commonRowSetControl"] = _common_row_set_control(sets)
    return out


def _common_row_set_control(sets: dict[str, dict[str, tuple[float, float]]]) -> dict:
    """Re-measure both sets over ONE row set scored by all three boards.

    Each entry above is diffed against its own intersection with the
    champion board, and those intersections are not the same size (799
    vs 787), because the two candidates price slightly different rows.
    That is a real objection to comparing the two mean shifts, so this
    removes it: build all three boards, keep only rows every board
    priced, and rank within that fixed set.
    """
    boards = {label: _board_values(curves) for label, curves in sets.items()}
    champion_board = _board_values(CHAMPION)
    common = sorted(set(champion_board).intersection(*(set(b) for b in boards.values())))
    if not common:
        return {"commonRows": 0}

    def order(vals: dict[str, float]) -> dict[str, int]:
        return {n: i for i, n in enumerate(sorted(common, key=lambda k: -vals[k]), 1)}

    base_order = order(champion_board)
    out: dict = {"commonRows": len(common)}
    for label, vals in boards.items():
        alt_order = order(vals)
        shifts = [abs(alt_order[n] - base_order[n]) for n in common]
        out[label] = {
            "rowsReordered": sum(1 for v in shifts if v),
            "meanAbsRankShift": round(sum(shifts) / len(shifts), 2),
            "maxAbsRankShift": max(shifts),
            "rowsMovingOver10": sum(1 for v in shifts if v > 10),
        }
    return out


def _board_values(curves: dict[str, tuple[float, float]]) -> dict[str, float]:
    """Board under one curve set. Patches, builds, restores; writes nothing."""
    import src.canonical.player_valuation as pv
    from src.api import data_contract as dc

    names = {
        "GLOBAL": ("HILL_GLOBAL_PERCENTILE_C", "HILL_GLOBAL_PERCENTILE_S"),
        "OFFENSE": ("HILL_PERCENTILE_C", "HILL_PERCENTILE_S"),
        "IDP": ("IDP_HILL_PERCENTILE_C", "IDP_HILL_PERCENTILE_S"),
    }
    saved = {n: getattr(pv, n) for pair in names.values() for n in pair}
    try:
        for scope, (cn, sn) in names.items():
            c, s = curves[scope]
            setattr(pv, cn, float(c))
            setattr(pv, sn, float(s))
        contract = dc.build_api_data_contract(json.loads(SNAPSHOT.read_text()))
    finally:
        for n, v in saved.items():
            setattr(pv, n, v)
    vals: dict[str, float] = {}
    for row in contract.get("playersArray") or []:
        name = str(row.get("displayName") or row.get("name") or "")
        v = row.get("rankDerivedValue")
        if name and isinstance(v, (int, float)) and v > 0:
            vals[name] = float(v)
    return vals


def _board_impact(curves: dict[str, tuple[float, float]]) -> dict:
    """Rebuild the board under a curve set and diff it against champion.

    In-process only — patches the module constants, builds, restores. No
    file is written and no constant survives the call.
    """
    import src.canonical.player_valuation as pv
    from src.api import data_contract as dc

    names = {
        "GLOBAL": ("HILL_GLOBAL_PERCENTILE_C", "HILL_GLOBAL_PERCENTILE_S"),
        "OFFENSE": ("HILL_PERCENTILE_C", "HILL_PERCENTILE_S"),
        "IDP": ("IDP_HILL_PERCENTILE_C", "IDP_HILL_PERCENTILE_S"),
    }
    raw = json.loads(SNAPSHOT.read_text())

    def build() -> dict[str, float]:
        contract = dc.build_api_data_contract(json.loads(json.dumps(raw)))
        vals: dict[str, float] = {}
        for row in contract.get("playersArray") or []:
            name = str(row.get("displayName") or row.get("name") or "")
            v = row.get("rankDerivedValue")
            if name and isinstance(v, (int, float)) and v > 0:
                vals[name] = float(v)
        return vals

    saved = {n: getattr(pv, n) for pair in names.values() for n in pair}
    try:
        base = build()
        for scope, (cn, sn) in names.items():
            c, s = curves[scope]
            setattr(pv, cn, float(c))
            setattr(pv, sn, float(s))
        alt = build()
    finally:
        for n, v in saved.items():
            setattr(pv, n, v)

    common = sorted(set(base) & set(alt))
    base_order = {n: i for i, n in enumerate(sorted(common, key=lambda k: -base[k]), 1)}
    alt_order = {n: i for i, n in enumerate(sorted(common, key=lambda k: -alt[k]), 1)}
    shifts = {n: alt_order[n] - base_order[n] for n in common}
    moved = [abs(v) for v in shifts.values()]
    biggest = sorted(common, key=lambda n: -abs(shifts[n]))[:5]
    return {
        "comparableRows": len(common),
        "rowsReordered": sum(1 for v in shifts.values() if v != 0),
        "meanAbsRankShift": round(sum(moved) / len(moved), 2) if moved else 0.0,
        "maxAbsRankShift": max(moved) if moved else 0,
        "rowsMovingOver10": sum(1 for v in moved if v > 10),
        "largestMovers": [
            {
                "player": n,
                "rank": f"{base_order[n]} -> {alt_order[n]}",
                "shift": -shifts[n],
                "value": f"{base[n]:.0f} -> {alt[n]:.0f}",
            }
            for n in biggest
        ],
    }


# ── report ──────────────────────────────────────────────────────────


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--skip-board", action="store_true", help="skip the two board rebuilds")
    args = ap.parse_args()

    if not SNAPSHOT.exists():
        print(f"FATAL: pinned snapshot missing: {SNAPSHOT}", file=sys.stderr)
        return 2

    fit = _fitter()
    sources = scope_sources(fit)

    report: dict = {
        "pinnedSnapshot": str(SNAPSHOT.relative_to(ROOT)),
        "referenceN": PERCENTILE_REFERENCE_N,
        "fitTopN": FIT_TOP_N,
        "champion": {k: list(v) for k, v in CHAMPION.items()},
        "challenger": {k: list(v) for k, v in CHALLENGER.items()},
        "Q4_coordinateTrace": q4_coordinate_trace(sources),
        "Q5_tailClamp": q5_tail_clamp(),
        "S18_referenceUniverse": s18_reference_universe(fit, sources),
        "S18_unanimitySweep": s18_unanimity_sweep(),
        "S30_leaveOneSourceOut": s30_leave_one_source_out(fit, sources),
    }
    if not args.skip_board:
        report["S39_coherentModelSets"] = s39_coherent_model_sets()

    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    _print_human(report)
    return 0


def _print_human(r: dict) -> None:
    print(f"pinned snapshot : {r['pinnedSnapshot']}")
    print(f"reference N     : {r['referenceN']}   FIT_TOP_N: {r['fitTopN']}")

    print("\n=== Q4 — fit-vs-serve coordinate trace ===")
    for scope, d in r["Q4_coordinateTrace"].items():
        print(f"\n{scope}: deepest observation p={d['pMaxObservedByAnySource']}, served to p=1.0")
        print(
            f"  extrapolated: {d['extrapolatedFractionOfUniverse']:.1%} of the universe "
            f"(from rank {d['firstExtrapolatedRank']})"
        )
        for s in d["sources"]:
            trunc = " (truncated)" if s["truncated"] else ""
            print(
                f"    {s['source']:24s} {s['rowsAvailable']:5d} rows -> trains "
                f"{s['rowsTrained']:4d}, p<={s['pMaxObserved']:.4f}{trunc}"
            )

    t = r["Q5_tailClamp"]
    print("\n=== Q5 — the p=1.0 tail clamp on the live board ===")
    print(
        f"  {t['clampedObservations']} of {t['totalObservations']} served observations "
        f"({t['clampedPct']}%) sit at the clamp"
    )
    print(
        f"  touching {t['distinctBoardRowsTouched']} of {t['boardRows']} board rows; "
        f"OVERALL_RANK_LIMIT={t['overallRankLimit']} vs referenceN={t['referenceN']}"
    )
    for s in t["perSource"]:
        if s["clamped"]:
            print(
                f"    {s['source']:24s} {s['clamped']:4d}/{s['observations']:4d}  {s['clampedPct']:5.1f}%"
            )

    print("\n=== §18 — reference-universe candidates ===")
    for label, scopes in r["S18_referenceUniverse"].items():
        if label.startswith("_"):
            continue
        print(f"\n  {label}")
        for scope, e in scopes.items():
            line = f"    {scope:8s} c={e['c']:.4f} s={e['s']:.4f}"
            h = e.get("holdoutInServingCoordinate")
            if h:
                line += f"   holdout criterion {h['criterion']}"
            print(line)
    print(f"\n  {r['S18_referenceUniverse']['_note']}")

    u = r["S18_unanimitySweep"]
    print("\n=== §18 — lower MEAN vs better on EVERY board (s held at %.3f) ===" % u["slopeHeld"])
    print(f"  champion criterion {u['championCriterion']}")
    for row in u["sweep"]:
        d = " ".join(f"{k[:4]}={v:+.0f}" for k, v in row["deltaVsChampion"].items())
        print(
            f"    c={row['c']:.4f}  crit {row['criterion']:8.2f}  "
            f"{'UNANIMOUS' if row['unanimous'] else '   split ':>10s}  {d}"
        )
    if u["bestUnanimous"]:
        rng = u["unanimousRange"]
        print(
            f"  best unanimous: c={u['bestUnanimous']['c']:.4f} "
            f"crit {u['bestUnanimous']['criterion']} (range {rng['lo']:.4f}..{rng['hi']:.4f})"
        )
    print(
        f"  best mean     : c={u['bestMean']['c']:.4f} crit {u['bestMean']['criterion']} "
        f"unanimous={u['bestMean']['unanimous']}"
    )
    print(
        "  degenerate check: "
        + ", ".join(f"c={g['c']}->{g['criterion']}" for g in u["degenerateCheck"])
    )

    print("\n=== §30/§31 — leave-one-source-out ===")
    for scope, e in r["S30_leaveOneSourceOut"].items():
        base_h = e["full"].get("holdout")
        extra = f"   holdout {base_h['criterion']}" if base_h else ""
        print(f"\n  {scope}: full c={e['full']['c']:.4f} s={e['full']['s']:.4f}{extra}")
        for d in e["dropped"]:
            vs = d["valueShiftPct"]
            line = (
                f"    without {d['without']:24s} (depth {d['sourceDepth']:3d}, "
                f"p<={d['pMaxObserved']:.3f})  c={d['c']:.4f} s={d['s']:.4f}  "
                f"value @25/100/400: {vs['25']:+.1f}%/{vs['100']:+.1f}%/{vs['400']:+.1f}%"
            )
            if d.get("holdout"):
                line += f"  holdout {d['holdout']['criterion']}"
            print(line)

    if "S39_coherentModelSets" in r:
        print("\n=== §39-§43 — coherent model sets, board impact vs champion ===")
        for label, d in r["S39_coherentModelSets"].items():
            if label == "_commonRowSetControl":
                print(f"\n  control — one common row set ({d['commonRows']} rows)")
                for k, v in d.items():
                    if k == "commonRows":
                        continue
                    print(
                        f"    {k}: {v['rowsReordered']} reorder, mean {v['meanAbsRankShift']}, "
                        f"max {v['maxAbsRankShift']}, >10 {v['rowsMovingOver10']}"
                    )
                continue
            print(f"\n  {label}")
            print(
                f"    {d['rowsReordered']}/{d['comparableRows']} rows reorder; "
                f"mean |shift| {d['meanAbsRankShift']}, max {d['maxAbsRankShift']}, "
                f"{d['rowsMovingOver10']} move >10"
            )
            for m in d["largestMovers"]:
                print(f"      {m['player']:22s} {m['rank']:>14s} ({m['shift']:+d})  {m['value']}")


if __name__ == "__main__":
    raise SystemExit(main())
