"""Empirical backtest for soft-fallback distance (framework step 9).

Sweeps ``_SOFT_FALLBACK_DISTANCE`` against the daily snapshot archive
and reports stability by distance, plus a "disabled" baseline for
direct comparison.

Soft fallback applies only to scope-eligible sources that did NOT
rank the player.  The fallback rank is
``pool_size + round(pool_size * distance)``, converted to a percentile
against ``_PERCENTILE_REFERENCE_N`` and fed through the same
percentile-Hill the covered path uses.

Distance 0.0 → fallback rank = pool + 1 (just past the list).
Distance 1.0 → fallback rank = 2 × pool (deep penalty).
Distance values > 1 are allowed but typically unhelpful.

Stability metric: mean absolute rank change across consecutive-day
pairs for top-200 players present in both snapshots.  Lower = more
stable.

Usage:
    python3 scripts/backtest_soft_fallback.py
    python3 scripts/backtest_soft_fallback.py --snapshots 10
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


DISTANCE_GRID: tuple[float, ...] = (
    0.0, 0.1, 0.2, 0.3, 0.5, 0.75, 1.0,
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


def stability_metric(boards, *, top_n: int = 200) -> dict[str, float]:
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


def sweep(snapshots: list[tuple[str, dict]]) -> list[dict]:
    orig_enabled = data_contract._SOFT_FALLBACK_ENABLED
    orig_distance = data_contract._SOFT_FALLBACK_DISTANCE
    results: list[dict] = []
    try:
        # Disabled baseline (behavior before PR 4).
        data_contract._SOFT_FALLBACK_ENABLED = False
        boards = [build_board(raw) for _, raw in snapshots]
        m = stability_metric(boards)
        results.append({"distance": None, "enabled": False, **m})

        # Sweep enabled distances.
        data_contract._SOFT_FALLBACK_ENABLED = True
        for d in DISTANCE_GRID:
            data_contract._SOFT_FALLBACK_DISTANCE = d
            boards = [build_board(raw) for _, raw in snapshots]
            m = stability_metric(boards)
            results.append({"distance": d, "enabled": True, **m})
    finally:
        data_contract._SOFT_FALLBACK_ENABLED = orig_enabled
        data_contract._SOFT_FALLBACK_DISTANCE = orig_distance
    return results


def render_report(snapshots, results) -> str:
    if not results:
        return "# Soft-Fallback Backtest\n\n(no data)\n"

    enabled_results = [r for r in results if r["enabled"]]
    by_weighted = sorted(
        enabled_results, key=lambda r: r["value_weighted_rank_change"]
    )
    by_unweighted = sorted(
        enabled_results, key=lambda r: r["mean_abs_rank_change"]
    )
    baseline = next(r for r in results if not r["enabled"])

    lines: list[str] = []
    lines.append("# Soft-Fallback Backtest")
    lines.append("")
    lines.append(f"- Snapshot count: **{len(snapshots)}**")
    if snapshots:
        lines.append(
            f"- Date range: **{snapshots[0][0]} → {snapshots[-1][0]}**"
        )
    lines.append(f"- Distance grid: {list(DISTANCE_GRID)}")
    lines.append(
        "- Chain under test: Framework step 9 soft fallback adds an "
        "imputed contribution from scope-eligible sources that didn't "
        "rank the player.  Fallback rank = pool + round(pool × distance)."
    )
    lines.append("")

    lines.append("## Stability")
    lines.append("")
    lines.append(
        "| setting | mean abs rank change | value-weighted rank change |"
    )
    lines.append("|:---|---:|---:|")
    lines.append(
        f"| disabled (pre-PR-4 behavior) | "
        f"{baseline['mean_abs_rank_change']:.3f} | "
        f"{baseline['value_weighted_rank_change']:.3f} |"
    )
    for r in enabled_results:
        un_marker = " ← best UW" if r is by_unweighted[0] else ""
        vw_marker = " ← best VW" if r is by_weighted[0] else ""
        lines.append(
            f"| distance={r['distance']:.2f} | "
            f"{r['mean_abs_rank_change']:.3f}{un_marker} | "
            f"{r['value_weighted_rank_change']:.3f}{vw_marker} |"
        )
    lines.append("")

    primary = by_weighted[0]
    primary_gain_vw = (
        100.0
        * (baseline["value_weighted_rank_change"] - primary["value_weighted_rank_change"])
        / baseline["value_weighted_rank_change"]
        if baseline["value_weighted_rank_change"] > 0
        else 0.0
    )
    lines.append("## Recommendation")
    lines.append("")
    if primary["value_weighted_rank_change"] >= baseline["value_weighted_rank_change"]:
        lines.append(
            "Soft fallback does not improve stability on this snapshot "
            "range.  Consider leaving it disabled, or pin it at a short "
            "distance (0.0-0.2) to keep the framework structure in place "
            "without degrading the board."
        )
    else:
        lines.append(
            f"Promote **distance = {primary['distance']:.2f}** "
            f"({primary_gain_vw:+.2f}% vs disabled, best on the "
            f"value-weighted metric).  Best on unweighted metric was "
            f"distance = {by_unweighted[0]['distance']:.2f}."
        )
    return "\n".join(lines) + "\n"


def write_csv(results: list[dict], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            ["setting", "mean_abs_rank_change", "value_weighted_rank_change"]
        )
        for r in results:
            label = (
                f"distance={r['distance']:.2f}"
                if r["enabled"]
                else "disabled"
            )
            w.writerow(
                [
                    label,
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
        default=_REPO_ROOT / "reports" / "soft_fallback_backtest_full.md",
    )
    ap.add_argument(
        "--csv",
        type=Path,
        default=_REPO_ROOT / "reports" / "soft_fallback_backtest.csv",
    )
    args = ap.parse_args()

    snapshots = load_snapshots(args.snapshots)
    if not snapshots:
        print(f"No snapshots in {_REPO_ROOT / 'data'}; aborting.")
        return 1
    print(f"Loaded {len(snapshots)} snapshots; sweeping soft-fallback …")
    results = sweep(snapshots)
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
