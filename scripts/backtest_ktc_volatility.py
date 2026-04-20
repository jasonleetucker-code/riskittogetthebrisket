"""Empirical backtest for KTC day-to-day volatility.

Quantifies how much KTC's curve drifts in the rank positions our
reconciliation test (``tests/canonical/test_ktc_reconciliation.py``)
pins.  The output decides whether the current ±5pp tolerance band
is defensible, too loose, or too tight — and feeds directly into
any future decision to re-fit the Hill curve (audit item R-H1).

For each daily snapshot in ``data/dynasty_data_*.json`` this script:

  1. Sorts players by raw ``ktc`` value descending (picks filtered).
  2. Records KTC value at each pinned reconciliation rank.
  3. Compares to ``rank_to_value(rank)`` (our deterministic Hill
     curve) and records the percentage divergence.

Across the full history it computes, per rank:

  * observed min / max / mean / stdev of KTC value
  * observed min / max / mean / stdev of pct_diff
  * max and 95th-percentile day-over-day change in pct_diff
    (consecutive-day jump, the signal that actually breaks CI)

Usage:
    python3 scripts/backtest_ktc_volatility.py
    python3 scripts/backtest_ktc_volatility.py --out reports/ktc_volatility.md

No production behavior is modified.  The output is a markdown report.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
import sys
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.canonical.player_valuation import (  # noqa: E402
    HILL_MIDPOINT,
    HILL_SLOPE,
    rank_to_value,
)


_PICK_PATTERN = re.compile(r"^\d{4}\s+(Early|Mid|Late)\s+\d", re.IGNORECASE)

# Ranks pinned in tests/canonical/test_ktc_reconciliation.py.  Any
# change here should mirror in the test (and vice versa) so the
# report and the regression test measure the same thing.
PINNED_RANKS: list[int] = [1, 5, 12, 24, 50, 100, 150, 200, 300, 400]

DATA_DIR = REPO / "data"


def _iter_ktc_values(payload: dict[str, Any]) -> list[tuple[str, int]]:
    """Return (player_name, ktc_value) for every non-pick player
    with a positive KTC value.  Mirrors the filtering in
    ``tests/canonical/test_ktc_reconciliation.py::_load_ktc_players_sorted``.
    """
    players = payload.get("players") or {}
    rows: list[tuple[str, int]] = []
    for name, pdata in players.items():
        if _PICK_PATTERN.match(str(name)):
            continue
        v = (pdata or {}).get("ktc") if isinstance(pdata, dict) else None
        if not v:
            continue
        try:
            rows.append((str(name), int(v)))
        except (TypeError, ValueError):
            continue
    rows.sort(key=lambda r: -r[1])
    return rows


def _rank_values(ktc_rows: list[tuple[str, int]]) -> dict[int, tuple[str, int]]:
    """Return {rank: (player_name, ktc_value)} for every pinned rank
    that falls within the available pool.
    """
    out: dict[int, tuple[str, int]] = {}
    for r in PINNED_RANKS:
        if r - 1 < len(ktc_rows):
            out[r] = ktc_rows[r - 1]
    return out


def _snapshot_date(path: Path) -> str:
    """Return the ISO date component of a dynasty_data_YYYY-MM-DD.json file."""
    stem = path.stem  # dynasty_data_2026-04-15
    return stem.rsplit("_", 1)[-1]


def collect_daily_series(data_dir: Path) -> dict[int, list[dict[str, Any]]]:
    """Build per-rank daily time series.

    Returns: {rank -> [{"date": YYYY-MM-DD, "ktc": int, "player": str,
                        "ours": int, "pct_diff": float}, ...]}
    """
    per_rank: dict[int, list[dict[str, Any]]] = {r: [] for r in PINNED_RANKS}
    files = sorted(data_dir.glob("dynasty_data_*.json"))
    if not files:
        raise SystemExit(f"No snapshots found in {data_dir}")

    for path in files:
        date = _snapshot_date(path)
        with path.open() as f:
            payload = json.load(f)
        rows = _iter_ktc_values(payload)
        for rank, (player, ktc_val) in _rank_values(rows).items():
            ours = rank_to_value(rank)
            pct_diff = 100.0 * (ours - ktc_val) / ktc_val if ktc_val else 0.0
            per_rank[rank].append(
                {
                    "date": date,
                    "ktc": ktc_val,
                    "player": player,
                    "ours": ours,
                    "pct_diff": pct_diff,
                }
            )
    return per_rank


def _summary_stats(values: list[float]) -> dict[str, float]:
    if not values:
        return {"min": 0.0, "max": 0.0, "mean": 0.0, "stdev": 0.0}
    return {
        "min": min(values),
        "max": max(values),
        "mean": statistics.mean(values),
        "stdev": statistics.stdev(values) if len(values) >= 2 else 0.0,
    }


def _percentile(sorted_vals: list[float], p: float) -> float:
    """Linear-interpolated percentile (p in [0, 1]) on a sorted list."""
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    k = (len(sorted_vals) - 1) * p
    lo = int(k)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = k - lo
    return sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac


def _day_over_day(series: list[float]) -> dict[str, float]:
    """Compute {max_abs_delta, p95_abs_delta} for consecutive-day deltas."""
    if len(series) < 2:
        return {"max_abs_delta": 0.0, "p95_abs_delta": 0.0}
    deltas = [abs(series[i] - series[i - 1]) for i in range(1, len(series))]
    deltas.sort()
    return {
        "max_abs_delta": max(deltas),
        "p95_abs_delta": _percentile(deltas, 0.95),
    }


def render_report(per_rank: dict[int, list[dict[str, Any]]]) -> str:
    lines: list[str] = []
    sample_sizes = {r: len(v) for r, v in per_rank.items()}
    n_snapshots = max(sample_sizes.values()) if sample_sizes else 0
    first_date = per_rank[PINNED_RANKS[0]][0]["date"] if per_rank[PINNED_RANKS[0]] else "?"
    last_date = per_rank[PINNED_RANKS[0]][-1]["date"] if per_rank[PINNED_RANKS[0]] else "?"

    lines.append("# KTC Volatility Backtest")
    lines.append("")
    lines.append(f"- Snapshot count: **{n_snapshots}**")
    lines.append(f"- Date range: **{first_date} → {last_date}**")
    lines.append(f"- Hill constants: midpoint={HILL_MIDPOINT}, slope={HILL_SLOPE}")
    lines.append(f"- Pinned ranks: {PINNED_RANKS}")
    lines.append("")
    lines.append(
        "Measures how much KTC's curve drifts day-to-day at the ranks "
        "pinned in `tests/canonical/test_ktc_reconciliation.py`. The "
        "`pct_diff` column is `(ours − ktc) / ktc × 100`; `ours` is "
        "deterministic, so all observed spread comes from KTC scrape "
        "drift.  **The `max dod` column is the statistic the ±tolerance "
        "band must absorb** — it's the largest consecutive-day jump in "
        "pct_diff observed across the history."
    )
    lines.append("")

    lines.append("## Per-rank drift summary")
    lines.append("")
    header = (
        "| rank | n | ktc min | ktc max | ktc stdev | pct_diff min | "
        "pct_diff max | pct_diff stdev | max dod | p95 dod |"
    )
    sep = "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"
    lines.append(header)
    lines.append(sep)
    for rank in PINNED_RANKS:
        series = per_rank[rank]
        if not series:
            lines.append(f"| {rank} | 0 | — | — | — | — | — | — | — | — |")
            continue
        ktc_stats = _summary_stats([s["ktc"] for s in series])
        pct_stats = _summary_stats([s["pct_diff"] for s in series])
        dod = _day_over_day([s["pct_diff"] for s in series])
        lines.append(
            f"| {rank} | {len(series)} | "
            f"{int(ktc_stats['min'])} | {int(ktc_stats['max'])} | "
            f"{ktc_stats['stdev']:.1f} | "
            f"{pct_stats['min']:+.2f}% | {pct_stats['max']:+.2f}% | "
            f"{pct_stats['stdev']:.2f}pp | "
            f"{dod['max_abs_delta']:.2f}pp | {dod['p95_abs_delta']:.2f}pp |"
        )
    lines.append("")

    # Overall max day-over-day across any pinned rank
    all_dod: list[float] = []
    for rank in PINNED_RANKS:
        series = per_rank[rank]
        if len(series) >= 2:
            pct_series = [s["pct_diff"] for s in series]
            for i in range(1, len(pct_series)):
                all_dod.append(abs(pct_series[i] - pct_series[i - 1]))
    all_dod.sort()
    lines.append("## Aggregate drift across all pinned ranks")
    lines.append("")
    if all_dod:
        lines.append(f"- Observations (day-over-day pct_diff deltas): **{len(all_dod)}**")
        lines.append(f"- Max observed: **{all_dod[-1]:.2f}pp**")
        lines.append(f"- 99th percentile: **{_percentile(all_dod, 0.99):.2f}pp**")
        lines.append(f"- 95th percentile: **{_percentile(all_dod, 0.95):.2f}pp**")
        lines.append(f"- 90th percentile: **{_percentile(all_dod, 0.90):.2f}pp**")
        lines.append(f"- Median: **{_percentile(all_dod, 0.50):.2f}pp**")
    else:
        lines.append("- (not enough data)")
    lines.append("")

    lines.append("## Tolerance-band sizing guidance")
    lines.append("")
    if all_dod:
        p99 = _percentile(all_dod, 0.99)
        p95 = _percentile(all_dod, 0.95)
        max_dod = all_dod[-1]
        lines.append(
            "The `pct_diff` band in "
            "`PINNED_DELTAS` is a static center + ±DELTA_TOLERANCE_PP. The "
            "tolerance must be ≥ the max day-over-day jump observed in this "
            "history or a data refresh will break CI.  Safe sizing rules:"
        )
        lines.append("")
        lines.append(f"- **Strict (catches regressions earliest):** ceil(max_dod) + 1pp = {int(max_dod) + 1}pp")
        lines.append(f"- **Balanced (absorbs 99% of drift):** ceil(p99) + 1pp = {int(p99) + 1}pp")
        lines.append(f"- **Lax (absorbs 95% of drift, tolerates rare CI break):** ceil(p95) + 1pp = {int(p95) + 1}pp")
        lines.append("")
        current_tol = 5.0
        if current_tol >= max_dod:
            lines.append(
                f"Current tolerance **±{current_tol:.1f}pp** is SAFE "
                f"(covers max observed dod = {max_dod:.2f}pp)."
            )
        elif current_tol >= p99:
            lines.append(
                f"Current tolerance **±{current_tol:.1f}pp** covers the "
                f"p99 drift ({p99:.2f}pp) but NOT the max observed "
                f"({max_dod:.2f}pp).  Expect ~1% of daily refreshes to "
                f"break CI unless widened to **±{int(max_dod) + 1}pp**."
            )
        else:
            lines.append(
                f"Current tolerance **±{current_tol:.1f}pp** is TOO TIGHT — "
                f"p99 drift = {p99:.2f}pp, max = {max_dod:.2f}pp.  Widen "
                f"to at least **±{int(p99) + 1}pp** to survive ordinary "
                f"KTC drift."
            )
    lines.append("")

    lines.append("## Per-rank day-over-day trace")
    lines.append("")
    lines.append(
        "Top few largest day-over-day pct_diff jumps, per rank.  Useful "
        "for spotting the specific dates KTC methodology appears to have "
        "shifted."
    )
    lines.append("")
    for rank in PINNED_RANKS:
        series = per_rank[rank]
        if len(series) < 2:
            continue
        jumps: list[tuple[float, str, str, float, float]] = []
        for i in range(1, len(series)):
            prior = series[i - 1]
            curr = series[i]
            jump = curr["pct_diff"] - prior["pct_diff"]
            jumps.append((jump, prior["date"], curr["date"], prior["pct_diff"], curr["pct_diff"]))
        jumps.sort(key=lambda t: -abs(t[0]))
        lines.append(f"### rank {rank}")
        lines.append("")
        lines.append("| prev date | curr date | prev pct | curr pct | Δ |")
        lines.append("|---|---|---:|---:|---:|")
        for j, prev_d, curr_d, prev_p, curr_p in jumps[:3]:
            lines.append(
                f"| {prev_d} | {curr_d} | {prev_p:+.2f}% | {curr_p:+.2f}% | {j:+.2f}pp |"
            )
        lines.append("")

    return "\n".join(lines)


def write_csv(per_rank: dict[int, list[dict[str, Any]]], out_path: Path) -> None:
    """Dump the full daily series as CSV for downstream analysis."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "rank", "player", "ktc", "ours", "pct_diff"])
        for rank in PINNED_RANKS:
            for s in per_rank[rank]:
                w.writerow([s["date"], rank, s["player"], s["ktc"], s["ours"], f"{s['pct_diff']:+.4f}"])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--data-dir",
        type=Path,
        default=DATA_DIR,
        help="Directory containing dynasty_data_*.json snapshots",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=REPO / "reports" / "ktc_volatility_backtest.md",
        help="Markdown report output path",
    )
    ap.add_argument(
        "--csv",
        type=Path,
        default=REPO / "reports" / "ktc_volatility_backtest.csv",
        help="CSV daily-series output path",
    )
    args = ap.parse_args()

    per_rank = collect_daily_series(args.data_dir)
    report = render_report(per_rank)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report)
    write_csv(per_rank, args.csv)

    # Also print the summary so a runner without a file viewer sees it.
    print(report)
    print(f"\nWrote report: {args.out}")
    print(f"Wrote CSV:    {args.csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
