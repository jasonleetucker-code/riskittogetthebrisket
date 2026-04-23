"""Tests for ``src.api.injury_impact``."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest

from src.api import injury_impact


def _news(severity: str, hours_ago: float = 1.0, impact: str | None = "negative",
           headline: str = "Test injury headline") -> dict:
    ts = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    players = [{"name": "Test Player", "impact": impact}] if impact else []
    return {
        "severity": severity,
        "ts": ts.isoformat().replace("+00:00", "Z"),
        "headline": headline,
        "players": players,
    }


def _season_ms() -> int:
    """A timestamp squarely inside the NFL regular season (October)
    so the offseason suppressor doesn't fire."""
    return int(datetime(2026, 10, 15, tzinfo=timezone.utc).timestamp() * 1000)


def _offseason_ms() -> int:
    """A timestamp in the NFL offseason (May) so the suppressor
    fires."""
    return int(datetime(2026, 5, 15, tzinfo=timezone.utc).timestamp() * 1000)


def _season_news(severity: str, hours_ago: float = 1.0,
                  impact: str | None = "negative",
                  headline: str = "Test") -> dict:
    """A news item whose ``ts`` is just before the in-season now_ms
    used by tests — so decay math lines up even with the fixed
    October reference time."""
    season = datetime(2026, 10, 15, tzinfo=timezone.utc)
    ts = season - timedelta(hours=hours_ago)
    players = [{"name": "Test Player", "impact": impact}] if impact else []
    return {
        "severity": severity,
        "ts": ts.isoformat().replace("+00:00", "Z"),
        "headline": headline,
        "players": players,
    }


def test_no_news_returns_zero_discount():
    r = injury_impact.compute_injury_discount(
        pos="RB", age=24, is_rookie=False,
        news_for_player=[], now_ms=_season_ms(),
    )
    assert r["appliedDiscountPct"] == 0.0
    assert r["adjustedPct"] == 100.0
    assert r["severity"] is None


def test_alert_on_rb_mid_age_modest_discount():
    r = injury_impact.compute_injury_discount(
        pos="RB", age=27, is_rookie=False,
        news_for_player=[_season_news("alert", hours_ago=1)],
        now_ms=_season_ms(),
    )
    # base 4 × pos 1.20 × age 1.00 × decay ≈ 1.0 → ~4.8%
    # Capped at 5%.  Discount is modest — this is a dynasty horizon.
    assert 4.5 <= r["appliedDiscountPct"] <= 5.0
    assert r["severity"] == "alert"


def test_alert_on_qb_smaller_discount():
    r = injury_impact.compute_injury_discount(
        pos="QB", age=30, is_rookie=False,
        news_for_player=[_season_news("alert", hours_ago=1)],
        now_ms=_season_ms(),
    )
    # base 4 × pos 0.70 × age 1.20 × decay ≈ 1.0 → ~3.36%
    assert 3.0 <= r["appliedDiscountPct"] <= 3.6


def test_discount_capped_at_five_percent():
    # Aggressive multipliers — old vet RB with severe injury — should
    # cap at 5% for the dynasty context.
    r = injury_impact.compute_injury_discount(
        pos="RB", age=35, is_rookie=False,
        news_for_player=[_season_news("alert", hours_ago=1)],
        now_ms=_season_ms(),
    )
    assert r["appliedDiscountPct"] <= 5.0


def test_aging_rb_gets_heavier_discount():
    young = injury_impact.compute_injury_discount(
        pos="RB", age=22, is_rookie=False,
        news_for_player=[_season_news("alert", hours_ago=1)],
        now_ms=_season_ms(),
    )
    old = injury_impact.compute_injury_discount(
        pos="RB", age=33, is_rookie=False,
        news_for_player=[_season_news("alert", hours_ago=1)],
        now_ms=_season_ms(),
    )
    # Old RB should hit the 5% cap; young should be lower.
    assert old["appliedDiscountPct"] >= young["appliedDiscountPct"]


def test_decay_half_at_fifteen_days():
    now = _season_ms()
    r_fresh = injury_impact.compute_injury_discount(
        pos="RB", age=27, is_rookie=False,
        news_for_player=[_season_news("alert", hours_ago=1)],
        now_ms=now,
    )
    r_old = injury_impact.compute_injury_discount(
        pos="RB", age=27, is_rookie=False,
        news_for_player=[_season_news("alert", hours_ago=15 * 24)],
        now_ms=now,
    )
    # 15 days in = 50% decay = roughly half discount
    assert r_old["appliedDiscountPct"] < r_fresh["appliedDiscountPct"]
    assert abs(r_old["appliedDiscountPct"] - r_fresh["appliedDiscountPct"] / 2) <= 0.5


def test_decay_zero_at_thirty_days():
    now = _season_ms()
    r = injury_impact.compute_injury_discount(
        pos="RB", age=27, is_rookie=False,
        news_for_player=[_season_news("alert", hours_ago=31 * 24)],
        now_ms=now,
    )
    # 31-day-old news → fully decayed → no discount
    assert r["appliedDiscountPct"] == 0.0


def test_positive_impact_news_does_not_fire():
    r = injury_impact.compute_injury_discount(
        pos="RB", age=27, is_rookie=False,
        news_for_player=[_season_news("alert", hours_ago=1, impact="positive")],
        now_ms=_season_ms(),
    )
    # Positive impact even at alert severity → ignored.
    assert r["appliedDiscountPct"] == 0.0


def test_worst_case_across_multiple_items():
    items = [
        _season_news("info", hours_ago=5, headline="Day-to-day"),
        _season_news("alert", hours_ago=1, headline="ACL"),
        _season_news("watch", hours_ago=2, headline="Hamstring"),
    ]
    r = injury_impact.compute_injury_discount(
        pos="RB", age=27, is_rookie=False,
        news_for_player=items,
        now_ms=_season_ms(),
    )
    assert r["severity"] == "alert"
    assert r["headline"] == "ACL"


def test_apply_injury_impact_produces_adjusted_value():
    row = {
        "pos": "RB",
        "age": 27,
        "rookie": False,
        "rankDerivedValue": 5000,
    }
    r = injury_impact.apply_injury_impact(
        row=row,
        news_for_player=[_season_news("alert", hours_ago=1)],
        now_ms=_season_ms(),
    )
    assert r["adjustedValue"] is not None
    # Should be less than the original but not catastrophically so —
    # at most 5% off = 4750 floor.
    assert r["adjustedValue"] < 5000
    assert r["adjustedValue"] >= 4700


def test_apply_injury_impact_no_news_leaves_value_untouched():
    row = {"pos": "RB", "age": 27, "rookie": False, "rankDerivedValue": 5000}
    r = injury_impact.apply_injury_impact(
        row=row, news_for_player=[], now_ms=_season_ms(),
    )
    assert r["appliedDiscountPct"] == 0.0
    assert r["adjustedValue"] == 5000


# ── Offseason suppressor ────────────────────────────────────────────────


def test_offseason_alert_produces_zero_discount():
    r = injury_impact.compute_injury_discount(
        pos="RB", age=27, is_rookie=False,
        news_for_player=[_news("alert", hours_ago=1)],
        now_ms=_offseason_ms(),  # May → offseason
    )
    assert r["appliedDiscountPct"] == 0.0
    assert r["offseasonSuppressed"] is True
    # Headline + severity still echoed so UI can render "Injury
    # news (suppressed — offseason)" with context.
    assert r["severity"] == "alert"
    assert r["headline"] == "Test injury headline"


@pytest.mark.parametrize("month,expected", [
    (1, False),   # January — playoffs, in-season
    (2, True),    # February — offseason starts
    (3, True),
    (4, True),    # Draft
    (5, True),    # OTAs
    (6, True),
    (7, True),    # Training camp open
    (8, True),    # Preseason — still classified offseason
    (9, False),   # Week 1
    (10, False),
    (11, False),
    (12, False),
])
def test_offseason_boundary_by_month(month, expected):
    ts = int(datetime(2026, month, 15, tzinfo=timezone.utc).timestamp() * 1000)
    assert injury_impact._is_nfl_offseason(ts) is expected


def test_offseason_apply_injury_impact_leaves_value_intact():
    row = {"pos": "RB", "age": 27, "rookie": False, "rankDerivedValue": 5000}
    r = injury_impact.apply_injury_impact(
        row=row,
        news_for_player=[_news("alert", hours_ago=1)],
        now_ms=_offseason_ms(),
    )
    assert r["adjustedValue"] == 5000
    assert r["appliedDiscountPct"] == 0.0
    assert r["offseasonSuppressed"] is True
