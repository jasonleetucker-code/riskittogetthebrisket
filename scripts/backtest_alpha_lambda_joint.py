"""2D joint backtest: α (subgroup shrinkage) × λ (MAD penalty).

Earlier single-parameter sweeps converged toward α=0 and λ=0 — the
stability-optimal degenerate solution is "anchor alone, no subgroup,
no MAD penalty" because IDPTC's own day-to-day stability dominates.
That's PRODUCT-BAD: it throws away 15 of 16 sources.

This 2D sweep shows the full landscape so we can pick a joint
operating point that preserves meaningful multi-source signal while
staying near the stability frontier.

No production behavior modified.  Output: markdown heatmap + CSV.
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


ALPHA_GRID: tuple[float, ...] = (0.0, 0.05, 0.1, 0.2, 0.3, 0.5)
LAMBDA_GRID: tuple[float, ...] = (0.0, 0.05, 0.1, 0.2, 0.3, 0.5)


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


def stability_vw(boards, *, top_n: int = 200) -> float:
    if len(boards) < 2:
        return 0.0
    n, d = 0.0, 0.0
    for prev, curr in zip(boards, boards[1:]):
        prev_top = [(name, info) for name, info in prev.items() if info["rank"] <= top_n]
        for name, prev_info in prev_top:
            curr_info = curr.get(name)
            if curr_info is None:
                continue
            delta = abs(curr_info["rank"] - prev_info["rank"])
            w = prev_info["value"]
            n += delta * w
            d += w
    return n / d if d > 0 else 0.0


def sweep_2d(snapshots) -> list[dict]:
    orig_a = data_contract._ALPHA_SHRINKAGE
    orig_l = data_contract._MAD_PENALTY_LAMBDA
    results: list[dict] = []
    try:
        for a in ALPHA_GRID:
            for l in LAMBDA_GRID:
                data_contract._ALPHA_SHRINKAGE = a
                data_contract._MAD_PENALTY_LAMBDA = l
                boards = [build_board(raw) for _, raw in snapshots]
                vw = stability_vw(boards)
                results.append({"alpha": a, "lambda": l, "vw": vw})
    finally:
        data_contract._ALPHA_SHRINKAGE = orig_a
        data_contract._MAD_PENALTY_LAMBDA = orig_l
    return results


def render(snapshots, results) -> str:
    if not results:
        return "# α × λ joint backtest\n\n(no data)\n"
    by_vw = sorted(results, key=lambda r: r["vw"])
    best = by_vw[0]

    lines: list[str] = []
    lines.append("# α × λ Joint Backtest")
    lines.append("")
    lines.append(f"- Snapshot count: **{len(snapshots)}**")
    if snapshots:
        lines.append(f"- Date range: **{snapshots[0][0]} → {snapshots[-1][0]}**")
    lines.append(f"- α grid: {list(ALPHA_GRID)}")
    lines.append(f"- λ grid: {list(LAMBDA_GRID)}")
    lines.append("- Metric: **value-weighted rank change** (lower = more stable)")
    lines.append("")
    lines.append(
        "**Caveat**: this metric rewards stability.  The stability "
        "optimum drifts toward α=0 and λ=0 — \"use the anchor source "
        "alone, ignore the 15 other sources.\"  That's product-bad "
        "because the blend is supposed to reflect multi-source "
        "consensus.  Pick a joint point that's **near** the stability "
        "frontier but still preserves meaningful subgroup signal (α ≥ "
        "~0.05) and some volatility damping (λ ≥ ~0.05)."
    )
    lines.append("")
    lines.append("## Heatmap (rows = α, cols = λ)")
    lines.append("")
    header = "| α \\ λ | " + " | ".join(f"{l:.2f}" for l in LAMBDA_GRID) + " |"
    sep = "|---:|" + "|".join(["---:" for _ in LAMBDA_GRID]) + "|"
    lines.append(header)
    lines.append(sep)
    for a in ALPHA_GRID:
        row_vals = []
        for l in LAMBDA_GRID:
            v = next(r["vw"] for r in results if r["alpha"] == a and r["lambda"] == l)
            marker = " ★" if (a, l) == (best["alpha"], best["lambda"]) else ""
            row_vals.append(f"{v:.3f}{marker}")
        lines.append(f"| **{a:.2f}** | " + " | ".join(row_vals) + " |")
    lines.append("")
    lines.append(f"Stability-optimal cell: α={best['alpha']}, λ={best['lambda']} (VW={best['vw']:.3f})")
    lines.append("")

    # Pareto-ish: cells within 20% of the optimum across non-degenerate α.
    threshold = best["vw"] * 1.20
    lines.append("## Near-optimal non-degenerate cells (within 20% of optimum)")
    lines.append("")
    lines.append("| α | λ | VW | % worse than optimum |")
    lines.append("|---:|---:|---:|---:|")
    for r in by_vw:
        if r["vw"] > threshold:
            continue
        if r["alpha"] < 0.05:
            # α=0 is the degenerate "anchor only" case — exclude so
            # the surviving set still reflects a real subgroup voice.
            continue
        pct = 100.0 * (r["vw"] - best["vw"]) / best["vw"] if best["vw"] > 0 else 0.0
        lines.append(f"| {r['alpha']:.2f} | {r['lambda']:.2f} | {r['vw']:.3f} | +{pct:.1f}% |")
    return "\n".join(lines) + "\n"


def write_csv(results, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["alpha", "lambda", "value_weighted_rank_change"])
        for r in results:
            w.writerow([r["alpha"], r["lambda"], f"{r['vw']:.4f}"])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--snapshots", type=int, default=None)
    ap.add_argument(
        "--out",
        type=Path,
        default=_REPO_ROOT / "reports" / "alpha_lambda_joint_backtest_full.md",
    )
    ap.add_argument(
        "--csv",
        type=Path,
        default=_REPO_ROOT / "reports" / "alpha_lambda_joint_backtest.csv",
    )
    args = ap.parse_args()

    snapshots = load_snapshots(args.snapshots)
    if not snapshots:
        print("No snapshots"); return 1
    print(f"Loaded {len(snapshots)} snapshots; running 2D α × λ sweep …")
    results = sweep_2d(snapshots)
    report = render(snapshots, results)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report)
    write_csv(results, args.csv)
    print(report)
    print(f"\nWrote report: {args.out}")
    print(f"Wrote CSV:    {args.csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
