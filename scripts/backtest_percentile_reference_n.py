"""Empirical backtest for ``_PERCENTILE_REFERENCE_N``.

The framework's step 2 computes ``p = (r - 1) / (N - 1)`` where the
denominator is the source's pool size.  Under our current
implementation (which keeps the shared-market / rookie / position-IDP
ladder translations in place), we use a FIXED reference N instead of
the source's own pool size so every source contributes in the same
combined-pool coordinate system.

``_PERCENTILE_REFERENCE_N = 500`` was chosen as a design choice —
aligned with KTC's native pool size, the retail market's natural
scale — but it was never empirically validated.  This script sweeps
N across plausible values and reports stability.

Usage:
    python3 scripts/backtest_percentile_reference_n.py
    python3 scripts/backtest_percentile_reference_n.py --snapshots 10
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path
from statistics import mean

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

os.environ.pop("SLEEPER_LEAGUE_ID", None)

from src.api import data_contract  # noqa: E402


# Plausible reference pool sizes:
#  - 100: smallest sensible (roughly FP IDP's pool)
#  - 200-300: mid-depth expert boards
#  - 500: KTC's pool (current default)
#  - 700-900: closer to the full combined offense+IDP universe
#  - 1000: theoretical upper bound matching the full player pool
N_GRID: tuple[int, ...] = (100, 200, 300, 400, 500, 600, 700, 800, 900, 1000)


def load_snapshots(limit: int | None) -> list[tuple[str, dict]]:
    data_dir = _REPO_ROOT / "data"
    paths = sorted(data_dir.glob("dynasty_data_*.json"))
    if limit is not None and limit > 0:
        paths = paths[-limit:]
    loaded: list[tuple[str, dict]] = []
    for path in paths:
        with path.open() as fh:
            loaded.append((path.stem.replace("dynasty_data_", ""), json.load(fh)))
    return loaded


def build_board(raw: dict) -> dict[str, dict]:
    contract = data_contract.build_api_data_contract(raw, tep_multiplier=1.0)
    out: dict[str, dict] = {}
    for row in contract.get("playersArray") or []:
        rank = row.get("canonicalConsensusRank")
        name = str(row.get("displayName") or row.get("canonicalName") or "").strip()
        if not name or not rank:
            continue
        out[name] = {"rank": int(rank), "value": float(row.get("rankDerivedValue") or 0)}
    return out


def stability_metric(boards, *, top_n: int = 200) -> dict[str, float]:
    if len(boards) < 2:
        return {"mean_abs_rank_change": 0.0, "value_weighted_rank_change": 0.0}
    unweighted: list[float] = []
    w_num, w_den = 0.0, 0.0
    for prev, curr in zip(boards, boards[1:]):
        prev_top = [(name, info) for name, info in prev.items() if info["rank"] <= top_n]
        for name, prev_info in prev_top:
            curr_info = curr.get(name)
            if curr_info is None:
                continue
            delta = abs(curr_info["rank"] - prev_info["rank"])
            unweighted.append(delta)
            weight = prev_info["value"]
            w_num += delta * weight
            w_den += weight
    return {
        "mean_abs_rank_change": (mean(unweighted) if unweighted else 0.0),
        "value_weighted_rank_change": (w_num / w_den if w_den > 0 else 0.0),
    }


def sweep(snapshots) -> list[dict]:
    orig = data_contract._PERCENTILE_REFERENCE_N
    results: list[dict] = []
    try:
        for n in N_GRID:
            data_contract._PERCENTILE_REFERENCE_N = n
            boards = [build_board(raw) for _, raw in snapshots]
            m = stability_metric(boards)
            results.append({"N": n, **m})
    finally:
        data_contract._PERCENTILE_REFERENCE_N = orig
    return results


def render(snapshots, results) -> str:
    if not results:
        return "# Percentile Reference N Backtest\n\n(no data)\n"
    by_vw = sorted(results, key=lambda r: r["value_weighted_rank_change"])
    by_un = sorted(results, key=lambda r: r["mean_abs_rank_change"])
    best = by_vw[0]

    lines: list[str] = []
    lines.append("# Percentile Reference N Backtest")
    lines.append("")
    lines.append(f"- Snapshot count: **{len(snapshots)}**")
    if snapshots:
        lines.append(f"- Date range: **{snapshots[0][0]} → {snapshots[-1][0]}**")
    lines.append(f"- N grid: {list(N_GRID)}")
    lines.append(
        "- Chain under test: `p = (effective_rank − 1) / (N − 1)`, "
        "fed into the Hill curve with current (c, s) constants."
    )
    lines.append("")
    lines.append("## Stability by N")
    lines.append("")
    lines.append("| N | mean abs rank change | value-weighted rank change |")
    lines.append("|---:|---:|---:|")
    for r in results:
        un_marker = " ← best UW" if r is by_un[0] else ""
        vw_marker = " ← best VW" if r is by_vw[0] else ""
        lines.append(
            f"| {r['N']} | {r['mean_abs_rank_change']:.3f}{un_marker} | "
            f"{r['value_weighted_rank_change']:.3f}{vw_marker} |"
        )
    lines.append("")

    current_result = next(r for r in results if r["N"] == 500)
    improvement_pct = (
        100.0
        * (current_result["value_weighted_rank_change"] - best["value_weighted_rank_change"])
        / current_result["value_weighted_rank_change"]
        if current_result["value_weighted_rank_change"] > 0
        else 0.0
    )
    lines.append("## Recommendation")
    lines.append("")
    if best["N"] == 500:
        lines.append(
            "**Keep N=500.**  The current default is stability-optimal on "
            "this snapshot range.  The design-choice justification (KTC "
            "pool size, retail market scale) is empirically validated."
        )
    else:
        lines.append(
            f"**Promote N={best['N']}**  ({improvement_pct:+.2f}% vs "
            f"N=500 on the value-weighted metric).  Best on the "
            f"unweighted metric was N={by_un[0]['N']}."
        )
    return "\n".join(lines) + "\n"


def write_csv(results, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["N", "mean_abs_rank_change", "value_weighted_rank_change"])
        for r in results:
            w.writerow([r["N"], f"{r['mean_abs_rank_change']:.4f}", f"{r['value_weighted_rank_change']:.4f}"])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--snapshots", type=int, default=None)
    ap.add_argument(
        "--out",
        type=Path,
        default=_REPO_ROOT / "reports" / "percentile_reference_n_backtest_full.md",
    )
    ap.add_argument(
        "--csv",
        type=Path,
        default=_REPO_ROOT / "reports" / "percentile_reference_n_backtest.csv",
    )
    args = ap.parse_args()
    snapshots = load_snapshots(args.snapshots)
    if not snapshots:
        print("No snapshots"); return 1
    print(f"Loaded {len(snapshots)} snapshots; sweeping N …")
    results = sweep(snapshots)
    report = render(snapshots, results)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report)
    write_csv(results, args.csv)
    print(report)
    print(f"\nWrote report: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
