#!/usr/bin/env python
"""
Lightweight validation for scoring-fit preprocessing outputs.

This is an export-based sanity check (not a new valuation engine).
It helps confirm that format-fit adjustments are bounded and reasonable.
"""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path
from statistics import mean


def _to_float(v, default=None):
    try:
        if v is None or str(v).strip() == "":
            return default
        return float(v)
    except Exception:
        return default


def _to_bool(v):
    return str(v).strip().lower() in {"1", "true", "yes", "y", "t"}


def load_csv_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def summarize(scoring_rows: list[dict], conf_rows: list[dict], arch_rows: list[dict], top_n: int = 25) -> str:
    conf_map = {str(r.get("player_name", "")).strip(): r for r in conf_rows}
    arch_map = {str(r.get("player_name", "")).strip(): r for r in arch_rows}

    enriched = []
    for r in scoring_rows:
        name = str(r.get("player_name", "")).strip()
        if not name:
            continue
        conf = conf_map.get(name, {})
        arch = arch_map.get(name, {})
        fit_delta = _to_float(r.get("fit_delta"), 0.0)
        fit_ratio = _to_float(r.get("fit_ratio"), 1.0)
        confidence = _to_float(r.get("confidence"), _to_float(conf.get("confidence"), 0.0) or 0.0)
        pos = str(r.get("position") or arch.get("position") or "UNK").upper()
        td_dep = _to_float(arch.get("td_dependency"), 0.0) or 0.0
        volatility = _to_bool(arch.get("volatility_flag"))
        enriched.append(
            {
                "name": name,
                "pos": pos,
                "fit_delta": fit_delta,
                "fit_ratio": fit_ratio,
                "confidence": confidence,
                "td_dep": td_dep,
                "volatility": volatility,
                "archetype": str(arch.get("archetype", "")).strip(),
                "quality": str(r.get("data_quality_flag", "")).strip(),
            }
        )

    if not enriched:
        return "No scoring-fit rows available."

    top_gainers = sorted(enriched, key=lambda x: x["fit_delta"], reverse=True)[:top_n]
    top_losers = sorted(enriched, key=lambda x: x["fit_delta"])[:top_n]

    by_pos: dict[str, list[dict]] = defaultdict(list)
    for e in enriched:
        by_pos[e["pos"]].append(e)

    lines: list[str] = []
    lines.append("SCORING FIT VALIDATION")
    lines.append(f"Players evaluated: {len(enriched)}")
    lines.append("")

    lines.append("Top Gainers")
    for e in top_gainers:
        lines.append(
            f"  {e['name']} ({e['pos']}): delta={e['fit_delta']:+.3f} ratio={e['fit_ratio']:.4f} conf={e['confidence']:.3f}"
        )
    lines.append("")

    lines.append("Top Losers")
    for e in top_losers:
        lines.append(
            f"  {e['name']} ({e['pos']}): delta={e['fit_delta']:+.3f} ratio={e['fit_ratio']:.4f} conf={e['confidence']:.3f}"
        )
    lines.append("")

    lines.append("Position Summary")
    for pos in sorted(by_pos.keys()):
        rows = by_pos[pos]
        ratios = [r["fit_ratio"] for r in rows]
        confs = [r["confidence"] for r in rows]
        high_conf = sum(1 for r in rows if r["confidence"] >= 0.75)
        low_conf = sum(1 for r in rows if r["confidence"] < 0.45)
        lines.append(
            f"  {pos}: n={len(rows)} avg_ratio={mean(ratios):.4f} avg_conf={mean(confs):.3f} high_conf={high_conf} low_conf={low_conf}"
        )
    lines.append("")

    weak_sample_over_adjust = [
        r for r in enriched
        if r["confidence"] < 0.45 and abs(r["fit_ratio"] - 1.0) > 0.08
    ]
    td_volatile_outliers = [
        r for r in enriched
        if r["volatility"] and r["td_dep"] >= 0.70 and abs(r["fit_ratio"] - 1.0) > 0.08
    ]

    lines.append("Risk Checks")
    lines.append(f"  Low-confidence over-adjustments (>8%): {len(weak_sample_over_adjust)}")
    lines.append(f"  TD-volatile large moves (>8%): {len(td_volatile_outliers)}")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate scoring-fit CSV outputs.")
    parser.add_argument("--data-dir", default=str(Path(__file__).resolve().parents[1] / "data"))
    parser.add_argument("--top", type=int, default=25)
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    scoring_path = data_dir / "player_scoring_fit.csv"
    conf_path = data_dir / "player_confidence.csv"
    arch_path = data_dir / "player_archetypes.csv"

    scoring_rows = load_csv_rows(scoring_path)
    conf_rows = load_csv_rows(conf_path)
    arch_rows = load_csv_rows(arch_path)

    report = summarize(scoring_rows, conf_rows, arch_rows, top_n=max(5, int(args.top)))
    print(report)

    out_path = Path(args.output) if args.output else (data_dir / "scoring_fit_validation.txt")
    out_path.write_text(report + "\n", encoding="utf-8")
    print(f"\nWrote validation report: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
