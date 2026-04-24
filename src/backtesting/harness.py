"""Light backtesting harness — evaluates trade-calculator outputs
against realized outcomes.

Purpose (Part 9 of the integration pass): give Jason one module
that answers "how good are my trade suggestions?" without
over-engineering.  Not an ML system.  Just a reducer that eats
historical trade records + value snapshots and produces an
accuracy table.

Inputs
------
Historical trade records::

    {
      "trade_id": "...",
      "date": "2025-10-15",
      "side_a_names": ["Josh Allen", "2026 1.04"],
      "side_b_names": ["Jalen Hurts", "2027 1.08"],
      "winProbA_at_time": 0.58,  # what the calc said
    }

Value snapshots::

    {("Josh Allen", "2025-10-15"): 9200, ("Josh Allen", "2026-04-15"): 9100, ...}

Output
------
    {
      "total": int,
      "correct": int,
      "accuracy": float,
      "buckets": {
        "0.5-0.55": {"total": N, "correct": N, "accuracy": f},
        ...
      }
    }

A trade is "correct" when sign(winProbA - 0.5) matches
sign(value_delta_after_horizon).  Horizon default 180 days.

Flag-gated on ``dynamic_source_weights`` implicitly — not
useful until the weight fitter is running.  Also simple
enough that it doesn't need a flag — the module just returns
empty summary when there's no historical data.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

_LOGGER = logging.getLogger(__name__)


@dataclass
class TradeRecord:
    trade_id: str
    date: str  # ISO YYYY-MM-DD
    side_a_names: list[str]
    side_b_names: list[str]
    win_prob_a: float  # what the calculator said at the time


@dataclass
class AccuracyBucket:
    total: int = 0
    correct: int = 0

    @property
    def accuracy(self) -> float:
        return (self.correct / self.total) if self.total else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "correct": self.correct,
            "accuracy": round(self.accuracy, 4),
        }


@dataclass
class BacktestSummary:
    total: int = 0
    correct: int = 0
    horizon_days: int = 180
    buckets: dict[str, AccuracyBucket] = field(default_factory=dict)
    skipped: int = 0
    skip_reasons: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "correct": self.correct,
            "accuracy": round(self.correct / self.total, 4) if self.total else 0.0,
            "horizonDays": self.horizon_days,
            "buckets": {k: v.to_dict() for k, v in self.buckets.items()},
            "skipped": self.skipped,
            "skipReasons": dict(self.skip_reasons),
        }


# Standard 10pp buckets from 0.5 to 1.0 — mirrors sports-quant's
# CONF_BINS.  A calibrated trade calc should have accuracy
# roughly equal to the bucket midpoint.
_BUCKETS = [
    (0.5, 0.55, "0.50-0.55"),
    (0.55, 0.60, "0.55-0.60"),
    (0.60, 0.65, "0.60-0.65"),
    (0.65, 0.70, "0.65-0.70"),
    (0.70, 0.75, "0.70-0.75"),
    (0.75, 0.80, "0.75-0.80"),
    (0.80, 0.85, "0.80-0.85"),
    (0.85, 0.90, "0.85-0.90"),
    (0.90, 0.95, "0.90-0.95"),
    (0.95, 1.01, "0.95-1.00"),
]


def _bucket_for(win_prob_a: float) -> str | None:
    """Treat <0.5 as inverse of >0.5; map to bucket above 0.5.
    e.g. winProbA=0.30 → bucket as "0.65-0.70" under the inverse."""
    p = abs(win_prob_a - 0.5) + 0.5  # 0.3 → 0.7, 0.5 → 0.5
    for lo, hi, label in _BUCKETS:
        if lo <= p < hi:
            return label
    return None


def _sum_value_at(
    names: list[str], on_date: str,
    value_snapshots: dict[tuple[str, str], float],
) -> float | None:
    """Sum the values of a list of player/pick names on a specific
    date.  Returns None if ANY name is missing a snapshot — we
    don't guess.  Caller skips such trades."""
    total = 0.0
    for name in names:
        v = value_snapshots.get((name, on_date))
        if v is None:
            return None
        total += float(v)
    return total


def _add_days(iso: str, days: int) -> str:
    dt = datetime.strptime(iso, "%Y-%m-%d")
    return (dt + timedelta(days=days)).strftime("%Y-%m-%d")


def run_backtest(
    records: list[TradeRecord],
    value_snapshots: dict[tuple[str, str], float],
    *,
    horizon_days: int = 180,
) -> BacktestSummary:
    """Run the backtest over the given records + snapshots.

    ``value_snapshots`` is keyed by (name, iso_date).  Caller is
    responsible for extracting these from their historical value
    exports.
    """
    summary = BacktestSummary(horizon_days=horizon_days)
    for b in _BUCKETS:
        summary.buckets[b[2]] = AccuracyBucket()

    def _skip(reason: str) -> None:
        summary.skipped += 1
        summary.skip_reasons[reason] = summary.skip_reasons.get(reason, 0) + 1

    for rec in records:
        if not rec.date or rec.win_prob_a is None:
            _skip("missing_date_or_winprob")
            continue
        try:
            future_date = _add_days(rec.date, horizon_days)
        except ValueError:
            _skip("bad_date_format")
            continue
        # Values at trade time + at horizon.
        a_now = _sum_value_at(rec.side_a_names, rec.date, value_snapshots)
        b_now = _sum_value_at(rec.side_b_names, rec.date, value_snapshots)
        a_future = _sum_value_at(rec.side_a_names, future_date, value_snapshots)
        b_future = _sum_value_at(rec.side_b_names, future_date, value_snapshots)
        if None in (a_now, b_now, a_future, b_future):
            _skip("missing_snapshots")
            continue
        # "Correct" = the side the calc favored ended up ahead at horizon.
        calc_favors_a = rec.win_prob_a > 0.5
        delta_future = a_future - b_future
        actually_a_ahead = delta_future > 0
        is_correct = calc_favors_a == actually_a_ahead
        summary.total += 1
        if is_correct:
            summary.correct += 1
        bucket = _bucket_for(rec.win_prob_a)
        if bucket and bucket in summary.buckets:
            summary.buckets[bucket].total += 1
            if is_correct:
                summary.buckets[bucket].correct += 1
    return summary


def format_report(summary: BacktestSummary) -> str:
    """Human-readable report for CLI output."""
    if summary.total == 0:
        return (
            f"No backtest trades evaluated. "
            f"skipped={summary.skipped} reasons={summary.skip_reasons}"
        )
    lines = []
    lines.append(f"Backtest summary (horizon={summary.horizon_days}d):")
    lines.append(
        f"  {summary.correct}/{summary.total} correct "
        f"({summary.correct/summary.total*100:.1f}%)"
    )
    if summary.skipped:
        lines.append(f"  skipped: {summary.skipped} (reasons: {summary.skip_reasons})")
    lines.append("")
    lines.append("Accuracy by confidence bucket:")
    lines.append("  bucket            total  correct  acc   calibration")
    for label, bucket in summary.buckets.items():
        mid = (float(label.split("-")[0]) + float(label.split("-")[1])) / 2
        deviation = bucket.accuracy - mid
        lines.append(
            f"  {label:<18} {bucket.total:>5}  {bucket.correct:>7}  "
            f"{bucket.accuracy:.3f}  Δ{deviation:+.3f}"
        )
    return "\n".join(lines)
