"""Usage-based signal engine.

Converts ``UsageWindow`` rows (from ``src.nfl_data.usage_windows``)
into BUY / SELL transitions that feed the existing signal alerts
pipeline (``src.api.signal_alerts``).

Rules
-----
Emit BUY when: snap_pct_z >= 2.0 OR target_share_z >= 2.0 OR carry_share_z >= 2.0
Emit SELL when: snap_pct_z <= -2.0 AND the player was an active starter
              (snap_pct_mean >= 0.50) in the prior window.  The SELL
              guard avoids "backup player's random 10% → 5% drop"
              false alerts.

Additional safeguards
---------------------
* Freshness guard (``src.nfl_data.freshness``) MUST pass — we
  don't fire on mid-week, pre-republish data.
* Depth-chart cross-check (``src.nfl_data.depth_charts``) gates
  MONITOR signals — see Phase 8.
* Feature flag ``usage_signals`` must be on.

Output format matches what ``detect_signal_transitions`` expects,
so downstream delivery pipes work unchanged:

    {"name", "pos", "signal", "reason", "tag", "signalKey",
     "aliasSignalKey", "sleeperId", "dismissed": False}
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from src.api import feature_flags
from src.nfl_data import freshness as _fresh
from src.nfl_data.usage_windows import UsageWindow

_BUY_Z = 2.0
_SELL_Z = -2.0
_ACTIVE_STARTER_SNAP_PCT = 0.50


@dataclass(frozen=True)
class UsageSignal:
    player_id: str
    signal: str  # "BUY" | "SELL"
    reason: str
    tag: str  # e.g. "usage_spike::snap" or "usage_drop::target"
    snap_pct_z: float | None
    target_share_z: float | None
    carry_share_z: float | None

    def to_signal_dict(
        self, *, name: str, position: str, sleeper_id: str,
    ) -> dict[str, Any]:
        """Render to the shape the existing signal_alerts engine
        consumes."""
        return {
            "name": name,
            "pos": position,
            "signal": self.signal,
            "reason": self.reason,
            "tag": self.tag,
            "signalKey": f"{name}::{self.tag}",
            "aliasSignalKey": f"sid:{sleeper_id}::{self.tag}" if sleeper_id else "",
            "sleeperId": sleeper_id,
            "dismissed": False,
        }


def detect_usage_transitions(
    windows: Iterable[UsageWindow],
    *,
    season_year: int | None = None,
    season_current_week: int | None = None,
) -> list[UsageSignal]:
    """Emit BUY/SELL usage transitions from the latest window per
    player, applying the freshness guard.

    Returns empty list when the feature flag is off — safe default.
    """
    if not feature_flags.is_enabled("usage_signals"):
        return []

    out: list[UsageSignal] = []
    for w in windows:
        # Freshness: never fire on mid-week current-week data.
        if not _fresh.is_fresh_for_alerts(
            stat_week=w.week, stat_year=w.season,
            season_year=season_year, season_current_week=season_current_week,
        ):
            continue

        # BUY rules — any single z-score >= +2.
        buy_reason = _check_buy(w)
        if buy_reason:
            tag, detail = buy_reason
            out.append(UsageSignal(
                player_id=w.player_id,
                signal="BUY",
                reason=detail,
                tag=tag,
                snap_pct_z=w.snap_pct_z,
                target_share_z=w.target_share_z,
                carry_share_z=w.carry_share_z,
            ))
            continue  # don't double-fire buy+sell on same window

        # SELL rules — drop z <= -2 AND prior-window starter.
        sell_reason = _check_sell(w)
        if sell_reason:
            tag, detail = sell_reason
            out.append(UsageSignal(
                player_id=w.player_id,
                signal="SELL",
                reason=detail,
                tag=tag,
                snap_pct_z=w.snap_pct_z,
                target_share_z=w.target_share_z,
                carry_share_z=w.carry_share_z,
            ))
    return out


def _check_buy(w: UsageWindow) -> tuple[str, str] | None:
    # Check in priority order: snap > target > carry.
    if w.snap_pct_z is not None and w.snap_pct_z >= _BUY_Z:
        return (
            "usage_spike_snap",
            f"Snap share jumped {w.snap_pct_z:+.1f}σ above 4-week mean.",
        )
    if w.target_share_z is not None and w.target_share_z >= _BUY_Z:
        return (
            "usage_spike_target",
            f"Target share jumped {w.target_share_z:+.1f}σ above 4-week mean.",
        )
    if w.carry_share_z is not None and w.carry_share_z >= _BUY_Z:
        return (
            "usage_spike_carry",
            f"Carry share jumped {w.carry_share_z:+.1f}σ above 4-week mean.",
        )
    return None


def _check_sell(w: UsageWindow) -> tuple[str, str] | None:
    # SELL requires the player was an active starter — prevents
    # false alerts on backup-role noise.
    if w.snap_pct_mean < _ACTIVE_STARTER_SNAP_PCT:
        return None
    if w.snap_pct_z is not None and w.snap_pct_z <= _SELL_Z:
        return (
            "usage_drop_snap",
            f"Snap share fell {w.snap_pct_z:+.1f}σ below 4-week mean.",
        )
    return None
