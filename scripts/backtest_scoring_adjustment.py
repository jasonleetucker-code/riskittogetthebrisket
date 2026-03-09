#!/usr/bin/env python
"""Lightweight validation for scoring-adjustment outputs.

Usage:
  python scripts/backtest_scoring_adjustment.py
  python scripts/backtest_scoring_adjustment.py --input dynasty_data_2026-03-09.json
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCRIPT_DIR)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.scoring.backtest import run_scoring_backtest


def resolve_latest_json() -> str | None:
    candidates = glob.glob(os.path.join(ROOT, "dynasty_data_*.json"))
    if not candidates:
        return None
    candidates.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return candidates[0]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="", help="Path to dynasty_data_*.json")
    ap.add_argument("--output", default=os.path.join(ROOT, "data", "scoring_backtest_report.json"))
    args = ap.parse_args()

    path = args.input.strip() or (resolve_latest_json() or "")
    if not path or not os.path.exists(path):
        print(f"[backtest] Could not find input json: {path}")
        return 1

    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    players = payload.get("players", {}) if isinstance(payload, dict) else {}
    fits = {}
    comparator_rows = []
    for name, pdata in (players or {}).items():
        if not isinstance(pdata, dict):
            continue
        sid = str(pdata.get("_sleeperId") or pdata.get("_id") or name).strip()
        fit = {
            "name": name,
            "bucket": str(pdata.get("_lamBucket") or ""),
            "ppgTest": float(pdata.get("_formatFitPPGTest") or 0.0),
            "ppgCustom": float(pdata.get("_formatFitPPGCustom") or 0.0),
            "fitFinal": float(pdata.get("_formatFitFinal") or 1.0),
            "productionMultiplier": float(pdata.get("_formatFitProductionMultiplier") or pdata.get("_effectiveMultiplier") or 1.0),
            "confidence": float(pdata.get("_formatFitConfidence") or 0.0),
        }
        fits[sid] = fit
        ppg_test = fit["ppgTest"]
        ppg_custom = fit["ppgCustom"]
        if ppg_test > 0 or ppg_custom > 0:
            target_ratio = ppg_custom / max(ppg_test, 1.0)
            new_mult = float(pdata.get("_formatFitProductionMultiplier") or fit["multiplier"] or 1.0)
            legacy_mult = float(pdata.get("_effectiveMultiplier") or 1.0)
            naive_mult = max(0.70, min(1.40, target_ratio))
            comparator_rows.append(
                {
                    "target_ratio": target_ratio,
                    "new_mult": new_mult,
                    "legacy_mult": legacy_mult,
                    "naive_mult": naive_mult,
                }
            )

    report = run_scoring_backtest(fits)
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    if comparator_rows:
        def _mae(key: str) -> float:
            vals = [abs(float(r[key]) - float(r["target_ratio"])) for r in comparator_rows]
            return (sum(vals) / len(vals)) if vals else 0.0
        report["modelComparisons"] = {
            "n": len(comparator_rows),
            "mae_new_multiplier_vs_raw_ratio": round(_mae("new_mult"), 6),
            "mae_legacy_multiplier_vs_raw_ratio": round(_mae("legacy_mult"), 6),
            "mae_naive_rescore_vs_raw_ratio": round(_mae("naive_mult"), 6),
        }

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, sort_keys=True)
    print(f"[backtest] Wrote {args.output}")
    print(f"[backtest] Sample size: {report.get('sampleSize', 0)}")
    print(f"[backtest] Overall: {report.get('overall', {})}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
