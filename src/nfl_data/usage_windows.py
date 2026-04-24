"""Rolling-window usage derivatives.

Takes raw per-week stat rows (from ``src.nfl_data.ingest``) and
produces the rolling-4-week windows that the signal engine and
the player-popup sparkline consume:

    snap_pct_4wk_mean, snap_pct_4wk_sd
    target_share_4wk_mean, target_share_4wk_sd
    carry_share_4wk_mean, carry_share_4wk_sd
    rz_touches_4wk_mean, rz_touches_4wk_sd

Plus a per-player transition flag (``usage_delta_z``) used by the
signal engine: the z-score of the current week's usage against
the 4-week history.

Pure-Python.  No pandas.

Callers pass normalized stat rows in any shape — this module
looks up keys by name and tolerates missing fields (returns 0).
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class UsageWindow:
    player_id: str  # GSIS or Sleeper — caller's choice, preserved verbatim
    season: int
    week: int
    snap_pct_mean: float
    snap_pct_sd: float
    target_share_mean: float
    target_share_sd: float
    carry_share_mean: float
    carry_share_sd: float
    snap_pct_z: float | None  # z-score of current week vs window
    target_share_z: float | None
    carry_share_z: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "playerId": self.player_id,
            "season": self.season,
            "week": self.week,
            "snapPctMean": round(self.snap_pct_mean, 3),
            "snapPctSd": round(self.snap_pct_sd, 3),
            "targetShareMean": round(self.target_share_mean, 3),
            "targetShareSd": round(self.target_share_sd, 3),
            "carryShareMean": round(self.carry_share_mean, 3),
            "carryShareSd": round(self.carry_share_sd, 3),
            "snapPctZ": round(self.snap_pct_z, 2) if self.snap_pct_z is not None else None,
            "targetShareZ": round(self.target_share_z, 2) if self.target_share_z is not None else None,
            "carryShareZ": round(self.carry_share_z, 2) if self.carry_share_z is not None else None,
        }


def _num(v, default=0.0):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return float(default)


def _compute_team_totals(
    stat_rows: list[dict[str, Any]],
) -> dict[tuple[int, int, str], dict[str, float]]:
    """Aggregate per-team-week totals so target/carry share can be
    computed.  Keyed by (season, week, team)."""
    totals: dict[tuple[int, int, str], dict[str, float]] = defaultdict(
        lambda: {"targets": 0.0, "carries": 0.0}
    )
    for row in stat_rows or []:
        if not isinstance(row, dict):
            continue
        season = int(_num(row.get("season")))
        week = int(_num(row.get("week")))
        team = str(row.get("recent_team") or row.get("team") or "").upper()
        if not team:
            continue
        t = totals[(season, week, team)]
        t["targets"] += _num(row.get("targets"))
        t["carries"] += _num(row.get("carries"))
    return totals


def _share(numerator: float, denom: float) -> float:
    if denom <= 0:
        return 0.0
    return numerator / denom


def _stdev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    var = sum((v - mean) ** 2 for v in values) / len(values)
    return math.sqrt(var)


def _zscore(current: float, mean: float, sd: float) -> float | None:
    if sd <= 0:
        return None
    return (current - mean) / sd


def build_rolling_windows(
    stat_rows: list[dict[str, Any]],
    *,
    window_size: int = 4,
    player_id_key: str = "player_id_gsis",
) -> list[UsageWindow]:
    """Walk each player's weekly rows in chronological order,
    emitting a ``UsageWindow`` per week that contains the mean/sd
    of the PRIOR ``window_size`` weeks and the z-score of the
    CURRENT week against that window.

    The current week's stats are intentionally excluded from the
    window — otherwise a big spike gets partially absorbed into
    the mean and under-flags the transition.
    """
    team_totals = _compute_team_totals(stat_rows)

    # Group by player, then sort by (season, week).
    by_player: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in stat_rows or []:
        if not isinstance(row, dict):
            continue
        pid = str(row.get(player_id_key) or "")
        if not pid:
            continue
        by_player[pid].append(row)

    windows: list[UsageWindow] = []
    for pid, rows in by_player.items():
        rows_sorted = sorted(rows, key=lambda r: (int(_num(r.get("season"))), int(_num(r.get("week")))))
        snap_pct_hist: list[float] = []
        target_share_hist: list[float] = []
        carry_share_hist: list[float] = []
        for row in rows_sorted:
            season = int(_num(row.get("season")))
            week = int(_num(row.get("week")))
            team = str(row.get("recent_team") or row.get("team") or "").upper()
            totals = team_totals.get((season, week, team), {"targets": 0.0, "carries": 0.0})
            curr_snap = _num(row.get("snap_pct"))
            curr_target = _share(_num(row.get("targets")), totals["targets"])
            curr_carry = _share(_num(row.get("carries")), totals["carries"])

            # Trailing window = last N weeks of history, excluding current.
            w_snap = snap_pct_hist[-window_size:]
            w_tgt = target_share_hist[-window_size:]
            w_car = carry_share_hist[-window_size:]

            w = UsageWindow(
                player_id=pid,
                season=season,
                week=week,
                snap_pct_mean=(sum(w_snap) / len(w_snap)) if w_snap else 0.0,
                snap_pct_sd=_stdev(w_snap),
                target_share_mean=(sum(w_tgt) / len(w_tgt)) if w_tgt else 0.0,
                target_share_sd=_stdev(w_tgt),
                carry_share_mean=(sum(w_car) / len(w_car)) if w_car else 0.0,
                carry_share_sd=_stdev(w_car),
                snap_pct_z=_zscore(curr_snap, sum(w_snap)/len(w_snap), _stdev(w_snap)) if len(w_snap) >= 2 else None,
                target_share_z=_zscore(curr_target, sum(w_tgt)/len(w_tgt), _stdev(w_tgt)) if len(w_tgt) >= 2 else None,
                carry_share_z=_zscore(curr_carry, sum(w_car)/len(w_car), _stdev(w_car)) if len(w_car) >= 2 else None,
            )
            windows.append(w)
            snap_pct_hist.append(curr_snap)
            target_share_hist.append(curr_target)
            carry_share_hist.append(curr_carry)
    return windows


def latest_window_per_player(
    windows: list[UsageWindow],
) -> dict[str, UsageWindow]:
    """Return the most recent ``UsageWindow`` per player."""
    out: dict[str, UsageWindow] = {}
    for w in windows:
        prev = out.get(w.player_id)
        if prev is None or (w.season, w.week) > (prev.season, prev.week):
            out[w.player_id] = w
    return out
