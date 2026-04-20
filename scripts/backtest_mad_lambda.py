"""Empirical backtest for the MAD volatility-penalty weight (λ).

Sweeps ``_MAD_PENALTY_LAMBDA`` (Final Framework step 6) against the
daily snapshot archive and reports how much the choice of λ affects
board stability across consecutive days.

Formula under test:
    final = (trimmed_mean + trimmed_median) / 2  −  λ · MAD
where MAD is the mean absolute deviation of the trimmed per-source
Hill-curve values around the trimmed mean.

Stability metric:
    Mean absolute change in ``canonicalConsensusRank`` for the top-200
    players present in both snapshots of each consecutive day-pair.
    Lower = more stable.  Also a value-weighted variant that weights
    each move by the day-T rank-derived value so top-12 moves dominate
    rank-180 noise.

The relative ordering of λ values is the signal; absolute numbers
are a function of the specific snapshot range and do not imply
calibration error.

Usage:
    python3 scripts/backtest_mad_lambda.py
    python3 scripts/backtest_mad_lambda.py --snapshots 10
    python3 scripts/backtest_mad_lambda.py --out reports/mad_lambda.md

No production behavior is modified.  The output is a markdown report
+ CSV of the per-λ stability metric.
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

# Pin the TEP derivation to the default path to avoid Sleeper-based
# variance across snapshots.
os.environ.pop("SLEEPER_LEAGUE_ID", None)

from src.api import data_contract  # noqa: E402


LAMBDA_GRID: tuple[float, ...] = (
    0.0, 0.05, 0.1, 0.2, 0.3, 0.5, 0.7, 1.0, 1.5, 2.0,
)


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
    ranked board.
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
    """Mean absolute rank change across consecutive day-pairs."""
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


def sweep_lambda(
    snapshots: list[tuple[str, dict]],
) -> list[dict]:
    """Sweep λ across ``LAMBDA_GRID`` and return per-λ stability."""
    original = data_contract._MAD_PENALTY_LAMBDA
    results: list[dict] = []
    try:
        for lam in LAMBDA_GRID:
            data_contract._MAD_PENALTY_LAMBDA = lam
            boards = [build_board(raw) for _d, raw in snapshots]
            m = stability_metric(boards)
            results.append({"lambda": lam, **m})
    finally:
        data_contract._MAD_PENALTY_LAMBDA = original
    return results


def render_report(
    snapshots: list[tuple[str, dict]],
    results: list[dict],
) -> str:
    if not results:
        return "# MAD λ Backtest\n\n(no data)\n"

    by_weighted = sorted(results, key=lambda r: r["value_weighted_rank_change"])
    by_unweighted = sorted(results, key=lambda r: r["mean_abs_rank_change"])
    baseline = next(r for r in results if r["lambda"] == 0.0)

    lines: list[str] = []
    lines.append("# MAD λ Backtest")
    lines.append("")
    lines.append(f"- Snapshot count: **{len(snapshots)}**")
    if snapshots:
        lines.append(
            f"- Date range: **{snapshots[0][0]} → {snapshots[-1][0]}**"
        )
    lines.append(f"- λ grid: {list(LAMBDA_GRID)}")
    lines.append(
        "- Chain under test: "
        "`center = (trimmed_mean + trimmed_median)/2`, "
        "`final = center − λ·MAD`, "
        "where MAD is the trimmed-mean absolute deviation of per-source "
        "Hill-curve values."
    )
    lines.append("")

    lines.append("## Stability by λ")
    lines.append("")
    lines.append("| λ | mean abs rank change | Δ vs λ=0 | value-weighted rank change | Δ vs λ=0 |")
    lines.append("|---:|---:|---:|---:|---:|")
    for r in results:
        lam = r["lambda"]
        un = r["mean_abs_rank_change"]
        vw = r["value_weighted_rank_change"]
        d_un = un - baseline["mean_abs_rank_change"]
        d_vw = vw - baseline["value_weighted_rank_change"]
        un_marker = ""
        vw_marker = ""
        if r is by_unweighted[0]:
            un_marker = " ← best"
        if r is by_weighted[0]:
            vw_marker = " ← best"
        lines.append(
            f"| {lam:.2f} | {un:.3f}{un_marker} | {d_un:+.3f} | "
            f"{vw:.3f}{vw_marker} | {d_vw:+.3f} |"
        )
    lines.append("")

    lines.append("## Recommendation")
    lines.append("")
    best_w = by_weighted[0]
    best_u = by_unweighted[0]
    if best_w["lambda"] == 0.0 and best_u["lambda"] == 0.0:
        lines.append(
            "**Keep λ = 0.0.**  MAD penalty does not improve stability on "
            "this snapshot range — the Final Framework step 6 is an "
            "identity no-op and can be removed.  Consider whether a "
            "different optimization target (e.g. KTC alignment) would "
            "favour a non-zero λ before committing to remove the feature."
        )
    else:
        primary = best_w
        gain_pct_vw = (
            100.0
            * (baseline["value_weighted_rank_change"] - primary["value_weighted_rank_change"])
            / baseline["value_weighted_rank_change"]
            if baseline["value_weighted_rank_change"] > 0
            else 0.0
        )
        gain_pct_un = (
            100.0
            * (baseline["mean_abs_rank_change"] - best_u["mean_abs_rank_change"])
            / baseline["mean_abs_rank_change"]
            if baseline["mean_abs_rank_change"] > 0
            else 0.0
        )
        lines.append(
            f"**Promote λ = {primary['lambda']:.2f}** "
            f"(best on value-weighted metric, "
            f"{gain_pct_vw:+.2f}% vs λ=0).  Best on unweighted metric was "
            f"λ = {best_u['lambda']:.2f} ({gain_pct_un:+.2f}%).  If the "
            f"two agree, the choice is obvious; if they disagree, prefer "
            f"the value-weighted optimum because top-of-board stability "
            f"matters more than long-tail rank jitter."
        )
    lines.append("")
    return "\n".join(lines)


def write_csv(results: list[dict], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            ["lambda", "mean_abs_rank_change", "value_weighted_rank_change"]
        )
        for r in results:
            w.writerow(
                [
                    r["lambda"],
                    f"{r['mean_abs_rank_change']:.4f}",
                    f"{r['value_weighted_rank_change']:.4f}",
                ]
            )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--snapshots",
        type=int,
        default=None,
        help="Use only the most recent N snapshots (default: all in data/)",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=_REPO_ROOT / "reports" / "mad_lambda_backtest_full.md",
    )
    ap.add_argument(
        "--csv",
        type=Path,
        default=_REPO_ROOT / "reports" / "mad_lambda_backtest.csv",
    )
    args = ap.parse_args()

    snapshots = load_snapshots(args.snapshots)
    if not snapshots:
        print(f"No snapshots in {_REPO_ROOT / 'data'}; aborting.")
        return 1

    print(f"Loaded {len(snapshots)} snapshots; sweeping λ …")
    results = sweep_lambda(snapshots)
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
