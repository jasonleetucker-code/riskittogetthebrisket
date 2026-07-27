"""Tests for the usage-based signal engine.

These pin the gating rules: flag-off = no output, freshness guard
blocks mid-week data, z-score thresholds fire in the right
direction, and SELL requires active-starter status."""

from __future__ import annotations

from zoneinfo import ZoneInfo

import pytest

from src.api import feature_flags
from src.news import usage_signals
from src.nfl_data.usage_windows import UsageWindow

NFL_TZ = ZoneInfo("America/New_York")


@pytest.fixture(autouse=True)
def _flags():
    feature_flags.reload()
    yield
    feature_flags.reload()


def _mk_window(**overrides):
    base = {
        "player_id": "A",
        "season": 2024,
        "week": 17,
        "snap_pct_mean": 0.50,
        "snap_pct_sd": 0.05,
        "target_share_mean": 0.15,
        "target_share_sd": 0.02,
        "carry_share_mean": 0.10,
        "carry_share_sd": 0.02,
        "snap_pct_z": None,
        "target_share_z": None,
        "carry_share_z": None,
    }
    base.update(overrides)
    return UsageWindow(**base)


def test_flag_off_returns_empty(monkeypatch):
    monkeypatch.setenv("RISKIT_FEATURE_USAGE_SIGNALS", "0")
    feature_flags.reload()
    out = usage_signals.detect_usage_transitions([_mk_window(snap_pct_z=3.0)])
    assert out == []


def test_snap_spike_fires_buy(monkeypatch):
    monkeypatch.setenv("RISKIT_FEATURE_USAGE_SIGNALS", "1")
    feature_flags.reload()
    # Stat from 2024, "now" treated as after that season → historical, fresh.
    out = usage_signals.detect_usage_transitions(
        [_mk_window(season=2024, week=17, snap_pct_z=2.5)],
        season_year=2026,
    )
    assert len(out) == 1
    assert out[0].signal == "BUY"
    assert "snap" in out[0].tag.lower()


def test_target_spike_fires_buy(monkeypatch):
    monkeypatch.setenv("RISKIT_FEATURE_USAGE_SIGNALS", "1")
    feature_flags.reload()
    out = usage_signals.detect_usage_transitions(
        [_mk_window(season=2024, target_share_z=2.5)],
        season_year=2026,
    )
    assert len(out) == 1
    assert out[0].tag == "usage_spike_target"


def test_sell_requires_active_starter(monkeypatch):
    monkeypatch.setenv("RISKIT_FEATURE_USAGE_SIGNALS", "1")
    feature_flags.reload()
    # Backup player (20% snaps) — SHOULD NOT fire SELL even with a big drop.
    backup = _mk_window(snap_pct_mean=0.20, snap_pct_z=-3.0)
    out = usage_signals.detect_usage_transitions([backup], season_year=2026)
    assert out == []
    # Active starter (60% snaps) — big drop fires SELL.
    starter = _mk_window(snap_pct_mean=0.60, snap_pct_z=-3.0)
    out2 = usage_signals.detect_usage_transitions([starter], season_year=2026)
    assert len(out2) == 1
    assert out2[0].signal == "SELL"


def _pin_weekday(monkeypatch, weekday: int):
    """Freeze ``freshness``'s clock to a known weekday.

    ``detect_usage_transitions`` does not thread a ``now`` through to
    ``is_fresh_for_alerts``, so the only way to make the week-in-flight
    branch deterministic without stubbing the guard itself is to pin the
    clock it reads.  The real predicate still runs.
    """
    import datetime as _dt

    from src.nfl_data import freshness as _freshness

    # 2025-11-03 is a Monday, so +weekday lands on the day we want.
    pinned = _dt.datetime(2025, 11, 3, 12, 0, tzinfo=_dt.timezone.utc) + _dt.timedelta(days=weekday)
    assert pinned.weekday() == weekday, "fixture date arithmetic is wrong"
    monkeypatch.setattr(_freshness, "_nfl_now", lambda now=None: pinned)


def test_freshness_guard_blocks_current_week_before_thursday(monkeypatch):
    """Stat week == current week, and it is Monday → blocked.

    This assertion used to read ``out == [] or out[0].signal == "BUY"``,
    which accepts both outcomes — so a test named "blocks" passed
    whether or not it blocked.  The comment above it said as much: the
    guard reads TODAY's weekday, so the result changed depending on the
    day the suite ran, and the author disabled the assertion rather than
    pin the clock.

    Pinning it is the fix.  Both branches are now asserted, here and
    below, and either direction of regression fails.
    """
    monkeypatch.setenv("RISKIT_FEATURE_USAGE_SIGNALS", "1")
    feature_flags.reload()
    _pin_weekday(monkeypatch, 0)  # Monday

    w = _mk_window(season=2025, week=6, snap_pct_z=3.0, snap_pct_mean=0.60)
    out = usage_signals.detect_usage_transitions([w], season_year=2025, season_current_week=6)
    assert out == [], "a week still in flight on a Monday must not fire"


def test_freshness_guard_allows_current_week_from_thursday(monkeypatch):
    """The other half, and what makes the test above non-vacuous.

    Without this, a detector that fired on nothing at all would satisfy
    the Monday case perfectly.  Same window, same season context, one
    day later than the safe weekday.
    """
    monkeypatch.setenv("RISKIT_FEATURE_USAGE_SIGNALS", "1")
    feature_flags.reload()
    _pin_weekday(monkeypatch, 3)  # Thursday — _SAFE_WEEKDAY

    w = _mk_window(season=2025, week=6, snap_pct_z=3.0, snap_pct_mean=0.60)
    out = usage_signals.detect_usage_transitions([w], season_year=2025, season_current_week=6)
    assert [s.signal for s in out] == ["BUY"]


def test_signal_dict_format_matches_expected_shape():
    s = usage_signals.UsageSignal(
        player_id="A",
        signal="BUY",
        reason="test",
        tag="usage_spike_snap",
        snap_pct_z=2.5,
        target_share_z=None,
        carry_share_z=None,
    )
    d = s.to_signal_dict(name="Josh Allen", position="QB", sleeper_id="4017")
    assert d["name"] == "Josh Allen"
    assert d["signal"] == "BUY"
    assert d["signalKey"] == "Josh Allen::usage_spike_snap"
    assert d["aliasSignalKey"] == "sid:4017::usage_spike_snap"
    assert d["dismissed"] is False


def test_buy_priority_snap_over_target(monkeypatch):
    """When multiple z-scores cross the threshold, snap wins (most
    reliable signal)."""
    monkeypatch.setenv("RISKIT_FEATURE_USAGE_SIGNALS", "1")
    feature_flags.reload()
    w = _mk_window(season=2024, snap_pct_z=3.0, target_share_z=3.0, carry_share_z=3.0)
    out = usage_signals.detect_usage_transitions([w], season_year=2026)
    assert out[0].tag == "usage_spike_snap"
