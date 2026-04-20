"""Empirical backtest for the canonical blend parameters.

Sweeps each tunable in ``src/api/data_contract.py`` against the
operator's daily snapshot archive and reports how much each
parameter value affects rank stability across time.

Parameters under test:
    * ``_BLEND_MEAN_WEIGHT`` / ``_BLEND_ROBUST_WEIGHT`` — the convex
      combination of weighted-mean and robust-trimmed-median.
      Swept at {0.50, 0.55, 0.60, 0.65, 0.70} for the mean weight
      with robust = 1 - mean so the pair stays a convex combination.
    * ``_VOLATILITY_COMPRESSION_FLOOR`` — minimum compression factor
      applied to high-disagreement rows.  Swept at {0.88, 0.90,
      0.92, 0.94}.
    * ``_VOLATILITY_COMPRESSION_CEIL`` — maximum boost factor applied
      to unanimous rows.  Swept at {1.04, 1.06, 1.08, 1.10, 1.12}.
    * IDPTC weight in ``_RANKING_SOURCES`` — Swept at {1.0, 1.5, 2.0,
      2.5, 3.0}.  The registry entry is mutated in place for each
      trial and restored on teardown.

Each parameter is swept independently with the others held at their
live defaults.  This is cheaper than a full Cartesian grid
(500 combos × N snapshots) and still exposes whether any single
value is wildly mis-calibrated.  A follow-up grid can probe
interactions if a single-dim sweep reveals a promising corner.

Stability metric:
    For each consecutive snapshot pair (T, T+1), compute the mean
    absolute change in ``canonicalConsensusRank`` across the
    top-200 players present on both days.  Lower = more stable.

    Also reports the value-weighted variant where each player's
    rank change is weighted by their rank-derived value on day T,
    so moves among the top 12 matter more than moves at rank 180.

Usage:
    python3 scripts/backtest_blend_params.py
    python3 scripts/backtest_blend_params.py --snapshots 5
    python3 scripts/backtest_blend_params.py --out reports/backtest.md

Runtime: ~2 minutes on 10 snapshots × ~20 parameter variations.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import time
from pathlib import Path
from statistics import mean, median, stdev

# Allow running from the repo root without an install step.
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

# Isolate Sleeper calls during the backtest — derivation uses the
# fallback context so TEP lands at 1.0, identical across every trial
# snapshot.  (The live service uses the operator's league; the
# backtest purposely normalizes this out so we're measuring blend
# behavior, not TEP drift.)
os.environ.pop("SLEEPER_LEAGUE_ID", None)

from src.api import data_contract  # noqa: E402


def load_snapshots(limit: int | None) -> list[tuple[str, dict]]:
    """Load the N most recent dynasty_data_YYYY-MM-DD.json snapshots."""
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
    """Run the canonical pipeline and return {displayName: row} for the
    ranked board (rows that received a ``canonicalConsensusRank``).
    """
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
    """Mean absolute rank change across consecutive day-pairs.

    Returns both unweighted and value-weighted variants.  The
    value-weighted variant weights each player's rank change by the
    day-T rank-derived value so top-12 moves dominate rank-180
    noise.

    A lower metric = more stable board = probably better-calibrated
    blend.  Cross-snapshot changes that reflect REAL source updates
    still register; the metric only claims to rank parameter choices
    relative to each other, not to reveal "true" values.
    """
    if len(boards) < 2:
        return {"mean_abs_rank_change": 0.0, "value_weighted_rank_change": 0.0}

    unweighted_changes: list[float] = []
    weighted_numer: float = 0.0
    weighted_denom: float = 0.0
    for prev, curr in zip(boards, boards[1:]):
        # Restrict to top_n on the PRIOR day so rank-200→rank-201
        # boundary thrashing doesn't dominate.  Consider only players
        # present in both snapshots (new rookies / removed players
        # are rank-change artifacts, not parameter signal).
        prev_top = [
            (name, info)
            for name, info in prev.items()
            if info["rank"] <= top_n
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


def sweep_blend_ratio(
    snapshots: list[tuple[str, dict]],
) -> list[dict]:
    """Sweep ``_BLEND_MEAN_WEIGHT`` (robust = 1 - mean)."""
    grid = [0.50, 0.55, 0.60, 0.65, 0.70, 0.75]
    original_mean = data_contract._BLEND_MEAN_WEIGHT
    original_rob = data_contract._BLEND_ROBUST_WEIGHT
    results: list[dict] = []
    try:
        for mean_w in grid:
            data_contract._BLEND_MEAN_WEIGHT = mean_w
            data_contract._BLEND_ROBUST_WEIGHT = round(1.0 - mean_w, 4)
            boards = [build_board(raw) for _date, raw in snapshots]
            m = stability_metric(boards)
            results.append(
                {
                    "param": "_BLEND_MEAN_WEIGHT",
                    "value": mean_w,
                    "paired_with": (
                        f"_BLEND_ROBUST_WEIGHT={round(1.0 - mean_w, 4)}"
                    ),
                    **m,
                }
            )
    finally:
        data_contract._BLEND_MEAN_WEIGHT = original_mean
        data_contract._BLEND_ROBUST_WEIGHT = original_rob
    return results


def sweep_volatility_floor(
    snapshots: list[tuple[str, dict]],
) -> list[dict]:
    """Sweep ``_VOLATILITY_COMPRESSION_FLOOR`` (compression limit)."""
    grid = [0.86, 0.88, 0.90, 0.92, 0.94, 0.96]
    original = data_contract._VOLATILITY_COMPRESSION_FLOOR
    results: list[dict] = []
    try:
        for v in grid:
            data_contract._VOLATILITY_COMPRESSION_FLOOR = v
            boards = [build_board(raw) for _date, raw in snapshots]
            m = stability_metric(boards)
            results.append(
                {
                    "param": "_VOLATILITY_COMPRESSION_FLOOR",
                    "value": v,
                    **m,
                }
            )
    finally:
        data_contract._VOLATILITY_COMPRESSION_FLOOR = original
    return results


def sweep_volatility_ceil(
    snapshots: list[tuple[str, dict]],
) -> list[dict]:
    """Sweep ``_VOLATILITY_COMPRESSION_CEIL`` (boost limit)."""
    grid = [1.02, 1.04, 1.06, 1.08, 1.10, 1.12, 1.14]
    original = data_contract._VOLATILITY_COMPRESSION_CEIL
    results: list[dict] = []
    try:
        for v in grid:
            data_contract._VOLATILITY_COMPRESSION_CEIL = v
            boards = [build_board(raw) for _date, raw in snapshots]
            m = stability_metric(boards)
            results.append(
                {
                    "param": "_VOLATILITY_COMPRESSION_CEIL",
                    "value": v,
                    **m,
                }
            )
    finally:
        data_contract._VOLATILITY_COMPRESSION_CEIL = original
    return results


def sweep_idptc_weight(
    snapshots: list[tuple[str, dict]],
) -> list[dict]:
    """Sweep the IDP Trade Calculator declared weight."""
    grid = [1.0, 1.5, 2.0, 2.5, 3.0]
    # Mutate the registry entry in place and restore after.
    target_key = "idpTradeCalc"
    target = next(
        (s for s in data_contract._RANKING_SOURCES if s.get("key") == target_key),
        None,
    )
    if target is None:
        return []
    original_weight = target.get("weight")
    results: list[dict] = []
    try:
        for w in grid:
            target["weight"] = float(w)
            boards = [build_board(raw) for _date, raw in snapshots]
            m = stability_metric(boards)
            results.append(
                {
                    "param": f"RANKING_SOURCES[{target_key}].weight",
                    "value": w,
                    **m,
                }
            )
    finally:
        target["weight"] = original_weight
    return results


def format_report(
    all_results: list[list[dict]],
    *,
    snapshot_count: int,
    runtime_seconds: float,
) -> str:
    """Emit a Markdown summary with the best-/worst- parameter rows
    highlighted per sweep.

    Ranks the runs within each sweep by the value-weighted stability
    metric (the one the mission cares about — moves at the top of
    the board count more than moves in the bottom).
    """
    lines: list[str] = []
    lines.append("# Blend Parameter Backtest")
    lines.append("")
    lines.append(f"Snapshot count: **{snapshot_count}**")
    lines.append(f"Runtime: **{runtime_seconds:.1f}s**")
    lines.append("")
    lines.append(
        "Stability metric: mean absolute change in "
        "``canonicalConsensusRank`` across consecutive-day pairs for "
        "top-200 players present in both days.  Value-weighted "
        "variant weights each delta by the day-T rank-derived value."
    )
    lines.append("")
    lines.append(
        "Lower = more stable = probably better-calibrated.  The *relative* "
        "ordering across parameter values is the signal; absolute numbers "
        "depend on the specific date range and do not imply calibration error."
    )
    lines.append("")

    for sweep in all_results:
        if not sweep:
            continue
        param = sweep[0]["param"]
        lines.append(f"## {param}")
        lines.append("")
        lines.append(
            "| value | extra | mean abs rank change | value-weighted rank change |"
        )
        lines.append("|------:|:------|---------------------:|---------------------------:|")
        # Sort by value-weighted metric ascending (most stable first)
        # for the summary, but render the grid in natural value order
        # so readers can scan a monotonic curve.
        natural = sorted(sweep, key=lambda r: r["value"])
        best = min(sweep, key=lambda r: r["value_weighted_rank_change"])
        worst = max(sweep, key=lambda r: r["value_weighted_rank_change"])
        for r in natural:
            marker = ""
            if r is best:
                marker = " **← most stable**"
            elif r is worst:
                marker = " ← least stable"
            extra = r.get("paired_with", "")
            lines.append(
                f"| {r['value']} | {extra} | "
                f"{r['mean_abs_rank_change']:.3f} | "
                f"{r['value_weighted_rank_change']:.3f}{marker} |"
            )
        spread = worst["value_weighted_rank_change"] - best["value_weighted_rank_change"]
        lines.append("")
        lines.append(
            f"Spread (worst − best): **{spread:.3f}** "
            f"(relative: {100 * spread / max(best['value_weighted_rank_change'], 1e-6):.1f}%)"
        )
        lines.append("")

    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument(
        "--snapshots",
        type=int,
        default=10,
        help="How many most-recent snapshots to use (default: 10).",
    )
    parser.add_argument(
        "--out",
        type=str,
        default="reports/backtest_blend_params.md",
        help="Output path for the Markdown report (default: reports/backtest_blend_params.md).",
    )
    args = parser.parse_args()

    start = time.time()
    snapshots = load_snapshots(args.snapshots)
    if len(snapshots) < 2:
        print(
            f"ERROR: need at least 2 snapshots to measure stability; "
            f"found {len(snapshots)}.  Run the daily scrape a couple of "
            f"days first."
        )
        return 1

    print(
        f"Loaded {len(snapshots)} snapshots "
        f"({snapshots[0][0]} → {snapshots[-1][0]})"
    )
    print()

    all_results: list[list[dict]] = []

    print("Sweeping _BLEND_MEAN_WEIGHT...")
    all_results.append(sweep_blend_ratio(snapshots))

    print("Sweeping _VOLATILITY_COMPRESSION_FLOOR...")
    all_results.append(sweep_volatility_floor(snapshots))

    print("Sweeping _VOLATILITY_COMPRESSION_CEIL...")
    all_results.append(sweep_volatility_ceil(snapshots))

    print("Sweeping RANKING_SOURCES[idpTradeCalc].weight...")
    all_results.append(sweep_idptc_weight(snapshots))

    runtime = time.time() - start
    report = format_report(
        all_results, snapshot_count=len(snapshots), runtime_seconds=runtime
    )

    out_path = _REPO_ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")

    print()
    print(f"✓ Report written to {out_path.relative_to(_REPO_ROOT)}")
    print(f"  ({runtime:.1f}s total)")
    print()
    # Also echo to stdout for quick inspection.
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
