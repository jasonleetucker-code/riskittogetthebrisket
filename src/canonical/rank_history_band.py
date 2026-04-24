"""Rolling ``rankHistory`` band for the source-consensus CI
(upgrade item #10).

Takes the per-day ``valueBand`` snapshots (from Phase 4) and
surfaces the p10/p50/p90 band's behavior over time.  Answers
"has this player's consensus range shrunk (sources agreeing more)
or widened (sources diverging)?"

Data model
----------
Input::
    [
      {"date": "2026-04-01", "valueBand": {"p10": 6000, "p50": 6500, "p90": 7000}},
      ...
    ]

Output::
    {
      "dates": ["2026-04-01", "2026-04-02", ...],
      "p10": [6000, 5950, ...],
      "p50": [6500, 6480, ...],
      "p90": [7000, 7100, ...],
      "spread": [1000, 1150, ...],         # p90 - p10 per day
      "spreadChange30d": -200,              # last - 30d-ago
      "spreadChangePct30d": -0.15,          # -15% tighter consensus
      "trend": "converging" | "diverging" | "stable",
    }

Pure-Python.  Used by the player popup mini-chart when the
``value_confidence_intervals`` flag is on.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RankHistoryBand:
    dates: list[str]
    p10: list[float]
    p50: list[float]
    p90: list[float]
    spread: list[float]
    spread_change_30d: float | None
    spread_change_pct_30d: float | None
    trend: str  # "converging" | "diverging" | "stable"

    def to_dict(self) -> dict[str, Any]:
        return {
            "dates": list(self.dates),
            "p10": [round(v, 1) for v in self.p10],
            "p50": [round(v, 1) for v in self.p50],
            "p90": [round(v, 1) for v in self.p90],
            "spread": [round(v, 1) for v in self.spread],
            "spreadChange30d": (
                round(self.spread_change_30d, 1)
                if self.spread_change_30d is not None else None
            ),
            "spreadChangePct30d": (
                round(self.spread_change_pct_30d, 3)
                if self.spread_change_pct_30d is not None else None
            ),
            "trend": self.trend,
        }


def build_band_history(
    snapshots: list[dict[str, Any]],
    *,
    window_days: int = 30,
    converging_pct_threshold: float = -0.10,
    diverging_pct_threshold: float = 0.10,
) -> RankHistoryBand | None:
    """Build the history from a chronologically-ordered snapshot list.

    ``snapshots`` entries: ``{"date": "YYYY-MM-DD", "valueBand": {"p10", "p50", "p90"}}``.

    Returns None if no usable snapshots.  One-snapshot input returns
    the single point with trend="stable".
    """
    if not snapshots:
        return None
    # Filter + sort chronologically.
    cleaned: list[tuple[str, float, float, float]] = []
    for s in snapshots:
        if not isinstance(s, dict):
            continue
        date = str(s.get("date") or "")
        band = s.get("valueBand") or s.get("band") or {}
        if not isinstance(band, dict):
            continue
        try:
            p10 = float(band.get("p10"))
            p50 = float(band.get("p50"))
            p90 = float(band.get("p90"))
        except (TypeError, ValueError):
            continue
        if not date:
            continue
        cleaned.append((date, p10, p50, p90))
    if not cleaned:
        return None
    cleaned.sort(key=lambda r: r[0])

    dates = [r[0] for r in cleaned]
    p10s = [r[1] for r in cleaned]
    p50s = [r[2] for r in cleaned]
    p90s = [r[3] for r in cleaned]
    spreads = [p90 - p10 for (p10, p90) in zip(p10s, p90s)]

    # Compute 30-day change.
    spread_change: float | None = None
    spread_change_pct: float | None = None
    trend = "stable"
    if len(spreads) >= 2:
        # Look back min(window_days, len-1) positions.
        lookback = min(window_days, len(spreads) - 1)
        older = spreads[-lookback - 1]
        newer = spreads[-1]
        spread_change = newer - older
        if older > 0:
            spread_change_pct = spread_change / older
            if spread_change_pct <= converging_pct_threshold:
                trend = "converging"
            elif spread_change_pct >= diverging_pct_threshold:
                trend = "diverging"
            else:
                trend = "stable"

    return RankHistoryBand(
        dates=dates,
        p10=p10s, p50=p50s, p90=p90s,
        spread=spreads,
        spread_change_30d=spread_change,
        spread_change_pct_30d=spread_change_pct,
        trend=trend,
    )
