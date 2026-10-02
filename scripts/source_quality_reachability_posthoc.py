#!/usr/bin/env python3
"""POST-HOC reachability diagnostic for a recorded source-quality evaluation.

Evidence about the GATES, not a new evaluation: it changes no gate, metric,
target, candidate, disposition or recorded result.  It rebuilds the recorded
run's panel (``--data-through`` the recorded window end; the panel digest must
match the recorded pin or the script refuses), reproduces the recorded harness
cells and the recorded walk-forward Δ from the recorded fold weights, and then
reports:

1. the in-sample ORACLE Δ MALE within the challengers' constraints (family
   weights in [0.75, 1.25], family averaging), pooled and per universe, global
   and per fold -- an upper bound on any out-of-sample learner of that form --
   against the recorded G1 materiality bar (champion MALE SE);
2. whether the picks requirement (no market-priced pick row changes) is
   attainable, by rebuilding the recorded impact payload through the override
   path under single-family weight changes.

    python scripts/source_quality_reachability_posthoc.py \\
        --results docs/valuation/evidence/source-quality-2026-10-01/results_2026-09-30.json \\
        --out docs/valuation/evidence/source-quality-2026-10-01/reachability_posthoc.json

Exit codes: 0 written; 1 refused (panel or payload does not match the pins).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from src.source_quality import evaluate as ev  # noqa: E402
from src.source_quality import panel as pn  # noqa: E402
from src.source_quality import reachability as rc  # noqa: E402

CAP_LO, CAP_HI = 0.75, 1.25
PICK_MARKET_FAMILIES = ("idpTradeCalc", "ktcCrowd", "ktcTrades")


def _log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


def rescore_recorded(cells: rc.Cells, folds: list[dict], candidate: str) -> float:
    """Δ MALE of the recorded fold weights on the rebuilt cells (reproduction check)."""
    F = len(cells.families)
    W = np.ones((len(cells.y), F))
    for k, fold in enumerate(folds):
        sel = cells.fold == k
        per_u = fold.get("c2PerUniverse") if candidate == "C2_asset_class_reliability" else None
        for ui, u in enumerate(rc.UNIVERSES):
            w = (per_u or {}).get(u) or fold["weights"][candidate]
            vec = np.array([float(w.get(f, 1.0)) for f in cells.families])
            W[sel & (cells.universe == ui)] = vec
    return rc.delta(cells, W)


def picks_reachability(
    payload: Path, final_overrides: dict[str, dict[str, float]], families: list[str]
) -> dict:
    """Which weight changes move MARKET-PRICED pick rows on the recorded board."""
    from src.api import value_replay as vr

    raw = json.loads(payload.read_text(encoding="utf-8"))
    fam_of = ev.registry_families()
    members: dict[str, list[str]] = {}
    for k, f in fam_of.items():
        members.setdefault(f, []).append(k)
    champion = vr.build(raw)

    def market_picks(overrides: dict[str, float]) -> dict:
        board = vr.build(raw, {"weights": overrides})
        sub = ev._subset_changes(
            champion,
            board,
            lambda r: r.get("assetClass") == "pick" and ev._pick_class(r) in ev.PICK_MARKET_CLASSES,
        )
        by_class: dict[str, int] = {}
        after = {r["displayName"]: r for r in board.get("playersArray") or []}
        for r in champion.get("playersArray") or []:
            if r.get("assetClass") != "pick" or ev._pick_class(r) not in ev.PICK_MARKET_CLASSES:
                continue
            b = (after.get(r["displayName"]) or {}).get("rankDerivedValue")
            if isinstance(b, (int, float)) and b != r.get("rankDerivedValue"):
                by_class[ev._pick_class(r)] = by_class.get(ev._pick_class(r), 0) + 1
        return {**sub, "changedByProvenance": dict(sorted(by_class.items()))}

    out: dict = {"singleFamily": {}, "candidatesWithoutPickMarketFamilies": {}}
    for f in families:
        for w in (CAP_LO, CAP_HI):
            _log(f"picks: {f} x{w}")
            out["singleFamily"][f"{f}@{w}"] = market_picks({k: w for k in members[f]})
    for c, ov in final_overrides.items():
        _log(f"picks: {c} with pick-market families at 1.0")
        held = {k: (1.0 if fam_of.get(k) in PICK_MARKET_FAMILIES else v) for k, v in ov.items()}
        out["candidatesWithoutPickMarketFamilies"][c] = market_picks(held)
    movers = sorted({k.split("@")[0] for k, v in out["singleFamily"].items() if v["changed"]})
    out["familiesWhoseWeightMovesMarketPricedPicks"] = movers
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--results", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument(
        "--census", type=Path, default=REPO / "docs/sources/census/CENSUS_2026-10-01.json"
    )
    ap.add_argument("--skip-picks", action="store_true")
    args = ap.parse_args(argv)

    from src.api import data_contract as dc

    res = json.loads(args.results.read_text(encoding="utf-8"))
    through = date.fromisoformat(res["dataWindow"][1])
    census = pn.load_census(args.census)
    if ev.sha256_file(args.census) != res["pins"]["census"]["sha256"]:
        _log("refusing: census does not match the recorded pin")
        return 1
    specs, _excluded = pn.eligible_specs(census, dc._RANKING_SOURCES, dc._SOURCE_CSV_PATHS)
    _log("reading point-in-time history")
    panel = pn.ObservationPanel(specs, pn.versions_from_git(REPO, specs)).truncated(
        pn.day_end(through)
    )
    digest = ev.panel_digest(panel)
    if digest != res["pins"]["panelDigest"]:
        _log(f"refusing: panel digest {digest[:16]} != recorded {res['pins']['panelDigest'][:16]}")
        return 1
    span = panel.span()
    m = pn.build_matrix(panel, pn.daily_grid(span[0], span[1]))
    X = m.family_matrix()
    plan = ev.Plan()
    cells = rc.harness_cells(m, X, plan)
    agg = res["gates"]["C1_conservative_reliability"]["strata"]["ALL"]
    gate = agg["championMALE"]["se"]
    e0 = rc.errors(cells, np.ones(len(cells.families)))
    repro = {
        "cells": {"rebuilt": int(len(cells.y)), "recorded": agg["cells"]},
        "championMALE": {
            "rebuilt": round(float(e0.mean()), 5),
            "recorded": agg["championMALE"]["point"],
        },
        "candidateDeltaMALE": {
            c: {
                "rebuiltFromRecordedFoldWeights": round(
                    rescore_recorded(cells, res["walkForward"]["folds"], c), 5
                ),
                "recorded": res["gates"][c]["strata"]["ALL"]["deltaMALE"]["point"],
            }
            for c in ev.CANDIDATES
        },
    }
    _log(f"reproduction: {json.dumps(repro)}")

    box = {"lo": CAP_LO, "hi": CAP_HI}
    variants: dict[str, dict] = {}
    specs_ = {
        "pooled_global": dict(**box),
        "perUniverse_global": dict(**box, per_universe=True),
        "pooled_global_pickMarketFamiliesFixed": dict(**box, fixed=PICK_MARKET_FAMILIES),
        "perUniverse_global_pickMarketFamiliesFixed": dict(
            **box, per_universe=True, fixed=PICK_MARKET_FAMILIES
        ),
        "pooled_global_uncapped_context": dict(lo=0.05, hi=20.0),
    }
    for name, kw in specs_.items():
        _log(f"oracle {name}")
        variants[name] = rc.oracle(cells, **kw)
    for name, kw in {
        "pooled_perFold": dict(**box),
        "perUniverse_perFold": dict(**box, per_universe=True),
    }.items():
        _log(f"oracle {name}")
        variants[name] = rc.per_fold_oracle(cells, **kw)
    for v in variants.values():
        v["deltaMALE"] = round(v["deltaMALE"], 6)
        v["attainsG1Materiality"] = v["deltaMALE"] >= gate
        v["shareOfMateriality"] = round(v["deltaMALE"] / gate, 3)
        if isinstance(v.get("weights"), dict):
            v["weights"] = json.loads(
                json.dumps(v["weights"]), parse_float=lambda s: round(float(s), 4)
            )
        for f in v.get("folds") or []:
            f["deltaMALE"] = round(f["deltaMALE"], 6)

    # Where the challengers' own mapping lands on the same cells: their FINAL
    # weights (learned on all data) scored in sample, and whether each moved
    # family in the same direction as the box oracle.
    oracle_w = variants["pooled_global"]["weights"]
    mapping: dict[str, dict] = {}
    for c in ev.CANDIDATES:
        fw = res["finalWeights"].get(c)
        if not fw:
            continue
        if c == "C2_asset_class_reliability":
            W = np.ones((len(cells.y), len(cells.families)))
            for ui, u in enumerate(rc.UNIVERSES):
                w = fw["perUniverse"].get(u) or fw["pooled"]
                W[cells.universe == ui] = [float(w.get(f, 1.0)) for f in cells.families]
            d = rc.delta(cells, W)
            pooled_w = fw["pooled"]
        else:
            d = rc.delta(cells, np.array([float(fw.get(f, 1.0)) for f in cells.families]))
            pooled_w = fw
        moved = [f for f, v in pooled_w.items() if abs(v - 1.0) > 1e-9]
        same = [f for f in moved if np.sign(pooled_w[f] - 1.0) == np.sign(oracle_w[f] - 1.0)]
        mapping[c] = {
            "finalWeightsInSampleDeltaMALE": round(d, 6),
            "shareOfMateriality": round(d / gate, 3),
            "maxAbsWeightMove": round(
                max((abs(v - 1.0) for v in pooled_w.values()), default=0.0), 4
            ),
            "familiesMoved": len(moved),
            "sameDirectionAsPooledOracle": sorted(same),
            "oppositeDirectionToPooledOracle": sorted(set(moved) - set(same)),
        }

    out = {
        "challengerMappingInSample": mapping,
        "kind": "POST-HOC reachability diagnostic (not preregistered; changes no gate, metric, "
        "target, candidate, disposition or recorded result)",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "results": args.results.resolve().relative_to(REPO).as_posix(),
        "resultsSha256": ev.sha256_file(args.results),
        "panelDigest": digest,
        "dataThrough": through.isoformat(),
        "method": (
            "harness cells rebuilt exactly as walk_forward (ALL stratum, allTargets, primary "
            "horizon); weights chosen IN SAMPLE on those same test cells to maximise delta MALE "
            "(multi-start L-BFGS-B; numerical optimum, not certified global). An oracle: an upper "
            "bound for any learner restricted to the same weight box (per fold: for fold-varying "
            "weights). The challenger mapping w = 1 + clip(0.10*B*z, +-0.25) can only reach a "
            "subset of the box."
        ),
        "g1MaterialityBar": gate,
        "reproduction": repro,
        "oracle": variants,
    }
    if not args.skip_picks:
        payload = REPO / res["pins"]["impactPayload"]["path"]
        if ev.sha256_file(payload) != res["pins"]["impactPayload"]["sha256"]:
            _log("refusing: impact payload does not match the recorded pin")
            return 1
        overrides = {
            c: r["overrides"] for c, r in (res["boardImpact"] or {}).get("candidates", {}).items()
        }
        learned = sorted(res["finalWeights"]["C1_conservative_reliability"])
        out["picks"] = picks_reachability(payload, overrides, learned)
    args.out.write_text(json.dumps(out, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    _log(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
