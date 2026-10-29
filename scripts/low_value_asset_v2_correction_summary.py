#!/usr/bin/env python3
"""Low-value-asset research — fairness_bands_v2 correction: compare shadow-replay runs.  RESEARCH ONLY.

Reads the committed ``shadow_replay.json`` (recorded under fairness_bands_v1) and any
number of re-runs produced by ``scripts/low_value_asset_shadow_replay.py`` (and,
optionally, the forced-drop diagnostic), and writes ONE aggregate-only comparison:

* ``reproduction`` — a leaf-by-leaf comparison of a ``--reproduction`` run (v1_legacy basis
  on the pinned board) against the committed file, so a reader can see how much of the
  recorded evidence is held before any v2 number is trusted;
* ``headline`` — the numbers the research memo quotes, per run.

It computes no fairness level and no band: every number is read from a run file.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EVIDENCE = REPO / "docs/valuation/evidence/low_value_assets_2026-10-20"
CLASSES = ("offense", "idp", "picks", "mixed")
TREATMENTS = (
    "A_curve_market",
    "A_curve_replacement",
    "B_currency_market",
    "B_currency_replacement",
)

#: parts of a run that are provenance / timing, never compared as results.
_SKIP = {"timingsSec", "bandBasis", "boardPin", "codeSha", "board", "generatedBy", "purpose"}


def _leaves(o, prefix=""):
    if isinstance(o, dict):
        for k, v in o.items():
            yield from _leaves(v, f"{prefix}/{k}")
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from _leaves(v, f"{prefix}[{i}]")
    else:
        yield prefix, o


def compare(a: dict, b: dict) -> dict:
    """Leaf comparison of two run files (provenance and timing excluded)."""
    la = dict(_leaves({k: v for k, v in a.items() if k not in _SKIP}))
    lb = dict(_leaves({k: v for k, v in b.items() if k not in _SKIP}))
    keys = sorted(set(la) | set(lb))
    differ = [k for k in keys if la.get(k, "<absent>") != lb.get(k, "<absent>")]
    by_section: dict[str, dict] = {}
    for k in keys:
        sec = k.split("/")[1]
        e = by_section.setdefault(sec, {"leaves": 0, "equal": 0})
        e["leaves"] += 1
        e["equal"] += k not in differ
    return {
        "leaves": len(keys),
        "equal": len(keys) - len(differ),
        "bySection": by_section,
        "differingPaths": differ[:200],
        "differingPathCount": len(differ),
    }


def headline(r: dict) -> dict:
    s3 = r["S3_fillerFlipStudy"]
    out: dict = {
        "fillerFlipStudy": {
            "bases": s3["design"]["bases"],
            "cases": s3["design"]["cases"],
            "byClass": {},
            "naiveDisclosure": s3["C_informationalDisclosure"],
        }
    }
    for cls in CLASSES:
        cell = s3["byClass"][cls]
        out["fillerFlipStudy"]["byClass"][cls] = {
            "incumbent": {c: cell[c]["GEOM_78"] for c in ("filler", "depth", "starter")},
            "criteria": s3["criteria"][cls],
            "starterOnlyBasesLevelChanged": {
                t: cell["F2_starterOnlyBases"][t]["share"] for t in TREATMENTS if cls != "picks"
            },
        }
    out["realExamples"] = [
        {
            "case": c["case"],
            "levels": {t: c["treatments"][t]["level"] for t in ("GEOM_78", *TREATMENTS)},
            "gapA": {t: c["treatments"][t]["gapA"] for t in ("GEOM_78", *TREATMENTS)},
            "disclosure": c["treatments"]["C_informational"]["disclosure"],
        }
        for c in r["S4_realExamples"]["cases"]
        if "treatments" in c
    ]
    s5a = r["S5a_calculatorFairnessSample"]
    out["calculatorSample"] = {
        "n": s5a["n"],
        "levelChanged": {t: v["levelChanged"] for t, v in s5a["byTreatment"].items()},
        "leaderFlipped": {t: v["leaderFlipped"] for t, v in s5a["byTreatment"].items()},
        "levelCountsIncumbent": s5a["byTreatment"]["GEOM_78"]["levelCounts"],
        "naiveDisclosureFires": s5a["C_informational"]["disclosureFires"],
    }
    s5b = r["S5b_tradeFinderReplay"]
    if s5b.get("run"):
        out["tradeFinderReplay"] = {
            t: {
                surf: {
                    k: v.get(k)
                    for k in (
                        "trades",
                        "kept",
                        "appear",
                        "disappear",
                        "meanTop10Overlap",
                        "lostSensibleDepthVsIncumbent",
                        "starForPile",
                        "levels",
                    )
                }
                for surf, v in surfs.items()
            }
            for t, surfs in s5b["comparisonVsIncumbent"].items()
        }
    s5c = r["S5c_tradeHistory"]
    out["tradeHistory"] = {
        "fullyPricedSides": s5c["fullyPricedSides"],
        "gradeBucketChangedFullyPriced": s5c["gradeBucketChangedVsGEOM_78_fullyPricedSides"],
    }
    s5d = r["S5d_warRoomTeamContext"]
    out["warRoom"] = {
        k: s5d[k]
        for k in (
            "samples",
            "sweetenedSteps",
            "fillerFlipsAssetOnly",
            "flipsNeutralisedByTeamContext",
            "flipsOverAbsorbed_verdictMovesAgainstReceiver",
            "flipsSurvivingTeamContext",
            "forcedDropBasis",
            "releaseCostPerForcedDropMedian",
            "fillerVaCreditMedian",
            "releaseChargedMedian",
            "releaseAsShareOfFillerCreditMedian",
        )
    }
    out["publicCategoryShadow"] = {
        t: {
            "evaluated": v["evaluated"],
            "categoryChangedVsGEOM_78": v["categoryChangedVsGEOM_78"],
        }
        for t, v in r["S5e_publicCategoryShadow"]["byTreatment"].items()
    }
    return out


def provenance(r: dict) -> dict:
    bb = r.get("bandBasis") or {}
    pin = r.get("boardPin") or {}
    return {
        "bandBasis": bb.get("basis", "v1_legacy (recorded before the switch existed)"),
        "ownerReceipt": bb.get("receiptOfOwnerInForce"),
        "codeSha": r.get("codeSha"),
        "archiveSha256": (r.get("board") or {}).get("sha256"),
        "builtBoardSha256": pin.get("builtBoardSha256"),
        "csvTreeRevision": (pin.get("csvTree") or {}).get("revisionSha"),
        "valueOverrides": pin.get("valueOverrides"),
        "pricedAssets": (r.get("board") or {}).get("pricedAssets"),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--committed", default=str(EVIDENCE / "shadow_replay.json"))
    ap.add_argument("--run", action="append", default=[], metavar="LABEL=PATH")
    ap.add_argument(
        "--reproduction",
        metavar="LABEL",
        help="the LABEL of the run (v1_legacy on the pinned board) compared leaf-by-leaf to the "
        "committed file",
    )
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    committed = json.loads(Path(args.committed).read_text(encoding="utf-8"))
    runs = {}
    for item in args.run:
        label, _, path = item.partition("=")
        runs[label] = json.loads(Path(path).read_text(encoding="utf-8"))
    out: dict = {
        "purpose": "RESEARCH ONLY.  Comparison of the recorded (fairness_bands_v1) shadow replay "
        "with re-runs on the pinned board; reads run files, computes no band.",
        "generatedBy": "scripts/low_value_asset_v2_correction_summary.py",
        "committed": {"provenance": provenance(committed), "headline": headline(committed)},
        "runs": {
            label: {"provenance": provenance(r), "headline": headline(r)}
            for label, r in runs.items()
        },
    }
    if args.reproduction:
        out["reproduction"] = {
            "run": args.reproduction,
            "versus": "committed shadow_replay.json",
            **compare(committed, runs[args.reproduction]),
        }
    dest = Path(args.out)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, indent=1, sort_keys=False) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(dest), "runs": list(runs)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
