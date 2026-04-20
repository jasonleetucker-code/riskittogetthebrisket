"""Empirical backtest for the α subgroup-shrinkage factor.

Sweeps ``_ALPHA_SHRINKAGE`` (Final Framework step 8) against the
daily snapshot archive and reports stability by α.

Formula under test:
    Final = Anchor + α · (SubgroupBlend − Anchor)

    α = 0.0 → pure anchor (IDPTC decides every value alone)
    α = 1.0 → pure subgroup blend (anchor ignored except as fallback)
    α intermediate → anchor-baseline with subgroup adjustment

Stability metric = mean absolute rank change across consecutive
day-pairs for the top-200 players present in both snapshots.  Lower
= more stable.  Value-weighted variant weights each rank move by
day-T value.

Usage:
    python3 scripts/backtest_alpha_shrinkage.py
    python3 scripts/backtest_alpha_shrinkage.py --snapshots 10

No production behavior is modified.  Output: markdown + CSV.
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


ALPHA_GRID: tuple[float, ...] = (
    0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0,
)


def load_snapshots(limit: int | None) -> list[tuple[str, dict]]:
    data_dir = _REPO_ROOT / "data"
    paths = sorted(data_dir.glob("dynasty_data_*.json"))
    if limit is not None and limit > 0:
        paths = paths[-limit:]
    loaded: list[tuple[str, dict]] = []
    for path in paths:
        date = path.stem.replace("dynasty_data_", "")
        with path.open() as fh:
            loaded.append((date, json.load(fh)))
    return loaded


def build_board(raw: dict) -> dict[str, dict]:
    contract = data_contract.build_api_data_contract(raw, tep_multiplier=1.0)
    out: dict[str, dict] = {}
    for row in contract.get("playersArray") or []:
        rank = row.get("canonicalConsensusRank")
        name = str(row.get("displayName") or row.get("canonicalName") or "").strip()
        if not name or not rank:
            continue
        out[name] = {
            "rank": int(rank),
            "value": float(row.get("rankDerivedValue") or 0),
        }
    return out


def stability_metric(
    boards: list[dict[str, dict]],
    *,
    top_n: int = 200,
) -> dict[str, float]:
    if len(boards) < 2:
        return {"mean_abs_rank_change": 0.0, "value_weighted_rank_change": 0.0}
    unweighted_changes: list[float] = []
    weighted_numer: float = 0.0
    weighted_denom: float = 0.0
    for prev, curr in zip(boards, boards[1:]):
        prev_top = [
            (name, info) for name, info in prev.items() if info["rank"] <= top_n
        ]
        for name, prev_info in prev_top:
            curr_info = curr.get(name)
            if curr_info is None:
                continue
            delta = abs(curr_info["rank"] - prev_info["rank"])
            unweighted_changes.append(delta)
            weight = prev_info["value"]
            weighted_numer += delta * weight
            weighted_denom += weight
    return {
        "mean_abs_rank_change": (
            mean(unweighted_changes) if unweighted_changes else 0.0
        ),
        "value_weighted_rank_change": (
            weighted_numer / weighted_denom if weighted_denom > 0 else 0.0
        ),
    }


def sweep_alpha(snapshots: list[tuple[str, dict]]) -> list[dict]:
    original = data_contract._ALPHA_SHRINKAGE
    results: list[dict] = []
    try:
        for alpha in ALPHA_GRID:
            data_contract._ALPHA_SHRINKAGE = alpha
            boards = [build_board(raw) for _d, raw in snapshots]
            m = stability_metric(boards)
            results.append({"alpha": alpha, **m})
    finally:
        data_contract._ALPHA_SHRINKAGE = original
    return results


def render_report(
    snapshots: list[tuple[str, dict]], results: list[dict]
) -> str:
    if not results:
        return "# α Shrinkage Backtest\n\n(no data)\n"
    by_weighted = sorted(results, key=lambda r: r["value_weighted_rank_change"])
    by_unweighted = sorted(results, key=lambda r: r["mean_abs_rank_change"])

    lines: list[str] = []
    lines.append("# α Shrinkage Backtest")
    lines.append("")
    lines.append(f"- Snapshot count: **{len(snapshots)}**")
    if snapshots:
        lines.append(
            f"- Date range: **{snapshots[0][0]} → {snapshots[-1][0]}**"
        )
    lines.append(f"- α grid: {list(ALPHA_GRID)}")
    lines.append(
        "- Chain under test: `Final = Anchor + α·(SubgroupBlend − Anchor)` "
        "where Anchor is IDPTC's percentile-Hill value and SubgroupBlend "
        "is the unweighted trimmed mean-median of the other sources' "
        "percentile-Hill values."
    )
    lines.append("")

    lines.append("## Stability by α")
    lines.append("")
    lines.append("| α | mean abs rank change | value-weighted rank change |")
    lines.append("|---:|---:|---:|")
    for r in results:
        un_marker = " ← best" if r is by_unweighted[0] else ""
        vw_marker = " ← best" if r is by_weighted[0] else ""
        lines.append(
            f"| {r['alpha']:.2f} | {r['mean_abs_rank_change']:.3f}{un_marker} | "
            f"{r['value_weighted_rank_change']:.3f}{vw_marker} |"
        )
    lines.append("")

    primary = by_weighted[0]
    lines.append("## Recommendation")
    lines.append("")
    lines.append(
        f"Promote **α = {primary['alpha']:.2f}**  "
        f"(best on value-weighted metric).  Best on unweighted metric was "
        f"α = {by_unweighted[0]['alpha']:.2f}.  If they agree, the choice is "
        f"obvious; if not, prefer the value-weighted optimum because "
        f"top-of-board stability matters more than long-tail rank jitter."
    )
    return "\n".join(lines) + "\n"


def write_csv(results: list[dict], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["alpha", "mean_abs_rank_change", "value_weighted_rank_change"])
        for r in results:
            w.writerow(
                [
                    r["alpha"],
                    f"{r['mean_abs_rank_change']:.4f}",
                    f"{r['value_weighted_rank_change']:.4f}",
                ]
            )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--snapshots", type=int, default=None)
    ap.add_argument(
        "--out",
        type=Path,
        default=_REPO_ROOT / "reports" / "alpha_shrinkage_backtest_full.md",
    )
    ap.add_argument(
        "--csv",
        type=Path,
        default=_REPO_ROOT / "reports" / "alpha_shrinkage_backtest.csv",
    )
    args = ap.parse_args()

    snapshots = load_snapshots(args.snapshots)
    if not snapshots:
        print(f"No snapshots in {_REPO_ROOT / 'data'}; aborting.")
        return 1
    print(f"Loaded {len(snapshots)} snapshots; sweeping α …")
    results = sweep_alpha(snapshots)
    report = render_report(snapshots, results)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report)
    write_csv(results, args.csv)
    print(report)
    print(f"\nWrote report: {args.out}")
    print(f"Wrote CSV:    {args.csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
