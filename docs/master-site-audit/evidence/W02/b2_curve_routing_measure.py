"""B2 / W02-F001 — does curve routing follow the effective rank's pool?

READ-ONLY. Changes no production behaviour, fits nothing, promotes nothing.
Rebuilds the board in-process under a counterfactual routing to measure the
defect's size; every patch is restored in a ``finally``.

The claim under test
--------------------
An IDP-only ranking source starts in within-IDP rank space.
``needs_shared_market_translation`` moves that rank onto the shared/combined
ladder, so its ``effectiveRank`` is now a COMBINED-POOL ordinal. Percentile
conversion uses that combined-pool ordinal — but ``_curve_for_source``
routes on the source's ``scope``, which is still ``overall_idp``. The result
is an IDP-slice curve applied to a percentile whose ordinal meaning belongs
to the combined pool.

Confirmed structurally before any measurement: ``_curve_for_source`` reads
only ``is_cross_market`` and ``scope``. It never consults
``needs_shared_market_translation`` or ``needs_rookie_translation``, so the
routing decision is blind to the very translation that changed what the rank
means.

Two comparisons, kept separate on purpose
-----------------------------------------
1. **Routing counterfactual** — ``hill(p, IDP)`` vs ``hill(p, GLOBAL)`` at
   the SAME percentile. This isolates the curve choice and nothing else, and
   it is the question W02-F001 actually asks.
2. **Anchor ratio** — translated source contribution vs the anchor's
   contribution at the same effective rank. Reported because the historical
   finding used it, but it is NOT a clean measure of the routing defect: the
   anchor (``idpTradeCalc``) is a value-based source and takes the
   value-direct path (``raw / site_max × 9999``), so that ratio mixes
   "which curve" with "curve vs published value". Conflating them is how a
   routing defect could be mistaken for a calibration one.

Usage (from the repo root):

    .venv/bin/python docs/master-site-audit/evidence/W02/b2_curve_routing_measure.py
    ... --json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import subprocess
import sys
from collections import defaultdict
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
)

#: The B2 board. Deliberately the CURRENT one — B2 is a new repair phase and
#: §2 allows current data — but pinned and hashed here so the before/after is
#: its own experiment rather than a continuation of B1's.
BOARD = ROOT / "exports" / "latest" / "dynasty_data_2026-08-11.json"

CURVES = {
    "GLOBAL": (HILL_GLOBAL_PERCENTILE_C, HILL_GLOBAL_PERCENTILE_S),
    "OFFENSE": (HILL_PERCENTILE_C, HILL_PERCENTILE_S),
    "IDP": (IDP_HILL_PERCENTILE_C, IDP_HILL_PERCENTILE_S),
}

REPRESENTATIVE_RANKS = (1, 5, 10, 25, 50, 100, 150, 200, 300, 400, 500)


def hill(p: float, c: float, s: float) -> float:
    p = max(0.0, min(1.0, float(p)))
    if p == 0.0:
        return 9999.0
    return 9999.0 / (1.0 + (p / c) ** s)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16] if path.exists() else "ABSENT"


def _git(*args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
    except subprocess.CalledProcessError:
        return "UNKNOWN"


def pin_baseline() -> dict:
    """§2 — B2 gets its own measurement boundary, not B1's."""
    csvs = sorted((ROOT / "CSVs" / "site_raw").glob("*.csv"))
    return {
        "codeSha": _git("rev-parse", "HEAD"),
        "codeShaShort": _git("rev-parse", "--short", "HEAD"),
        "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "treeDirtyFiles": len([x for x in _git("status", "--porcelain").splitlines() if x.strip()]),
        "boardSnapshot": str(BOARD.relative_to(ROOT)),
        "boardSha256_16": _sha(BOARD),
        "boardBytes": BOARD.stat().st_size if BOARD.exists() else None,
        "sourceCsvSha256_16": {p.name: _sha(p) for p in csvs},
        "championConstants": {k: list(v) for k, v in CURVES.items()},
        "measuredAt": _git("log", "-1", "--format=%cI"),
        "_note": (
            "B1/B1.1/B1.2 numbers are tied to THEIR pins and are not "
            "reproducible against this board. Any before/after here is "
            "internal to this baseline."
        ),
    }


# ── the registry, read from production rather than restated ─────────


def source_registry() -> dict[str, dict]:
    from src.api.data_contract import _RANKING_SOURCES as RANKING_SOURCES

    out = {}
    for src in RANKING_SOURCES:
        out[src["key"]] = {
            "scope": str(src.get("scope") or ""),
            "sharedMarketTranslated": bool(src.get("needs_shared_market_translation")),
            "rookieTranslated": bool(src.get("needs_rookie_translation")),
            "crossMarket": bool(src.get("is_cross_market")),
        }
    return out


def routing_table() -> dict:
    """Which sources have the W02-F001 shape, derived not listed."""
    reg = source_registry()
    rows = []
    for key, meta in sorted(reg.items()):
        # Mirrors `_curve_for_source`: cross-market wins, then scope.
        if meta["crossMarket"]:
            routed = "GLOBAL"
        elif meta["scope"] == "overall_idp":
            routed = "IDP"
        else:
            routed = "OFFENSE"
        translated = meta["sharedMarketTranslated"] or meta["rookieTranslated"]
        rows.append(
            {
                "source": key,
                **meta,
                "routedCurve": routed,
                # The defect: the rank was moved into a shared/combined
                # pool, but the curve is still the IDP-slice one.
                "defectShape": bool(meta["sharedMarketTranslated"]) and routed == "IDP",
                "rookieDefectShape": bool(meta["rookieTranslated"]) and routed == "IDP",
                "anyTranslation": translated,
            }
        )
    return {
        "sources": rows,
        "defectSources": [r["source"] for r in rows if r["defectShape"]],
        "rookieRiskSources": [r["source"] for r in rows if r["rookieDefectShape"]],
    }


# ── §11 — the measurement, across the whole board ───────────────────


def _board_rows():
    from src.api.data_contract import build_api_data_contract

    return build_api_data_contract(json.loads(BOARD.read_text())).get("playersArray") or []


def measure_contributions(rows) -> dict:
    """Per translated source: what it pays vs the anchor, and vs GLOBAL.

    Only rows where the source and the anchor landed on the SAME effective
    rank are compared — that is the condition the finding is about, and
    comparing different ranks would measure market disagreement instead.
    """
    reg = source_registry()
    translated = [k for k, m in reg.items() if m["sharedMarketTranslated"]]

    anchor_ratio: dict[str, list[float]] = defaultdict(list)
    curve_ratio: dict[str, list[float]] = defaultdict(list)
    samples: dict[str, list[dict]] = defaultdict(list)

    for row in rows:
        meta = row.get("sourceRankMeta") or {}
        anchor = meta.get("idpTradeCalc")
        a_rank = anchor.get("effectiveRank") if anchor else None
        a_val = (
            float(anchor["valueContribution"])
            if anchor and anchor.get("valueContribution")
            else None
        )
        for key in translated:
            m = meta.get(key)
            if not m or m.get("valueContribution") in (None, 0):
                continue
            v = float(m["valueContribution"])
            p = m.get("percentile")

            # The CLEAN routing measure needs only this source's own
            # percentile — comparing two curves at one coordinate. Collected
            # over every contributing row, because restricting it to rows
            # that happen to tie the anchor's exact ordinal is what made the
            # first pass report n=3 and n=4.
            if p is not None:
                g = hill(p, *CURVES["GLOBAL"])
                if g:
                    curve_ratio[key].append(hill(p, *CURVES["IDP"]) / g)

            # The anchor ratio is only meaningful where both landed on the
            # SAME effective rank; anywhere else it measures market
            # disagreement rather than routing. Small n is expected and is
            # reported rather than papered over.
            if a_val is None or m.get("effectiveRank") != a_rank:
                continue
            anchor_ratio[key].append(v / a_val)
            if len(samples[key]) < 4:
                samples[key].append(
                    {
                        "player": row.get("displayName") or row.get("name"),
                        "position": row.get("position"),
                        "rawRank": m.get("rawRank"),
                        "effectiveRank": m.get("effectiveRank"),
                        "percentile": p,
                        "contribution": v,
                        "anchorContribution": a_val,
                        "ratioToAnchor": round(v / a_val, 4),
                        "idpCurve": round(hill(p, *CURVES["IDP"]), 1) if p is not None else None,
                        "globalCurve": round(hill(p, *CURVES["GLOBAL"]), 1)
                        if p is not None
                        else None,
                    }
                )

    def stats(vals: list[float]) -> dict:
        if not vals:
            return {"n": 0}
        vs = sorted(vals)
        q = (
            statistics.quantiles(vs, n=4)
            if len(vs) >= 4
            else [vs[0], statistics.median(vs), vs[-1]]
        )
        return {
            "n": len(vs),
            "median": round(statistics.median(vs), 4),
            "p25": round(q[0], 4),
            "p75": round(q[2], 4),
            "min": round(vs[0], 4),
            "max": round(vs[-1], 4),
        }

    return {
        "perSource": {
            key: {
                "vsAnchor": stats(anchor_ratio[key]),
                "idpCurveVsGlobalCurve": stats(curve_ratio[key]),
                "samples": samples[key],
            }
            for key in sorted(translated)
        },
        "_note": (
            "vsAnchor mixes curve choice with value-direct-vs-Hill, because "
            "idpTradeCalc is a value-based source. idpCurveVsGlobalCurve is "
            "the clean routing measure: same percentile, two curves."
        ),
    }


def curve_gap_by_rank() -> dict:
    """§17 — the routing gap as a function of rank, independent of data."""
    from src.canonical.player_valuation import rank_to_percentile

    out = []
    for rank in REPRESENTATIVE_RANKS:
        p = rank_to_percentile(rank)
        i = hill(p, *CURVES["IDP"])
        g = hill(p, *CURVES["GLOBAL"])
        out.append(
            {
                "rank": rank,
                "percentile": round(p, 6),
                "idpCurve": round(i, 1),
                "globalCurve": round(g, 1),
                "idpOverGlobal": round(i / g, 4),
                "deltaIfRouted": round(g - i, 1),
            }
        )
    return {"rows": out}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if not BOARD.exists():
        print(f"FATAL: B2 board snapshot missing: {BOARD}", file=sys.stderr)
        return 2

    rows = _board_rows()
    report = {
        "baseline": pin_baseline(),
        "routing": routing_table(),
        "curveGapByRank": curve_gap_by_rank(),
        "contributions": measure_contributions(rows),
        "boardRows": len(rows),
    }

    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    b = report["baseline"]
    print(f"code {b['codeShaShort']} on {b['branch']}, {b['treeDirtyFiles']} dirty")
    print(f"board {b['boardSnapshot']} sha {b['boardSha256_16']} ({b['boardBytes']} B)")
    print(f"rows {report['boardRows']}")

    print("\n=== routing table (derived from the live registry) ===")
    print(f"{'source':20s} {'scope':16s} {'sharedX':8s} {'rookieX':8s} {'cross':6s} {'curve':8s}")
    for r in report["routing"]["sources"]:
        if r["scope"] == "overall_idp" or r["anyTranslation"] or r["crossMarket"]:
            flag = (
                "  <-- DEFECT"
                if r["defectShape"]
                else ("  <-- rookie risk" if r["rookieDefectShape"] else "")
            )
            print(
                f"{r['source']:20s} {r['scope']:16s} {str(r['sharedMarketTranslated']):8s} "
                f"{str(r['rookieTranslated']):8s} {str(r['crossMarket']):6s} {r['routedCurve']:8s}{flag}"
            )
    print(f"\ndefect sources: {report['routing']['defectSources']}")
    print(f"rookie-risk sources: {report['routing']['rookieRiskSources']}")

    print("\n=== curve gap by rank (IDP vs GLOBAL at the same percentile) ===")
    print(f"{'rank':>5s} {'pctile':>9s} {'IDP':>8s} {'GLOBAL':>8s} {'IDP/GLB':>8s} {'delta':>9s}")
    for r in report["curveGapByRank"]["rows"]:
        print(
            f"{r['rank']:5d} {r['percentile']:9.6f} {r['idpCurve']:8.1f} {r['globalCurve']:8.1f} "
            f"{r['idpOverGlobal']:8.4f} {r['deltaIfRouted']:+9.1f}"
        )

    print("\n=== contributions at the SAME effective rank as the anchor ===")
    for key, d in report["contributions"]["perSource"].items():
        a, cc = d["vsAnchor"], d["idpCurveVsGlobalCurve"]
        if not a.get("n"):
            print(f"\n  {key}: no comparable rows")
            continue
        print(f"\n  {key}  (anchor-matched n={a['n']}, contributing rows n={cc.get('n', 0)})")
        print(
            f"    vs anchor        median {a['median']:.3f}  p25 {a['p25']:.3f}  "
            f"p75 {a['p75']:.3f}  min {a['min']:.3f}  max {a['max']:.3f}"
        )
        if cc.get("n"):
            print(
                f"    IDP/GLOBAL curve median {cc['median']:.3f}  p25 {cc['p25']:.3f}  "
                f"p75 {cc['p75']:.3f}  min {cc['min']:.3f}  max {cc['max']:.3f}"
            )
        for s in d["samples"][:2]:
            print(
                f"      {s['player']} ({s['position']}) raw {s['rawRank']} -> eff "
                f"{s['effectiveRank']}: contrib {s['contribution']:.0f}, anchor "
                f"{s['anchorContribution']:.0f}, IDP {s['idpCurve']}, GLOBAL {s['globalCurve']}"
            )
    print(f"\n  {report['contributions']['_note']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
