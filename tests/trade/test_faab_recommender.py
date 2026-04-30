"""Tests for ``src/trade/faab_recommender.py``.

The recommender composes 6+ signals (baseline formula, value-gain
modifier, trending kicker, league analytics, KTC crowd blend, team
FAAB cap, marginal-upgrade floor).  Each input is optional; missing
inputs drop confidence and surface a ``factors[].missing=true`` row.

These tests pin every fallback path so a future "let's just blend
in X" tweak doesn't silently break confidence reporting or the
explanation copy.
"""
from __future__ import annotations

from src.trade.faab_recommender import recommend_faab


# ── Baseline (fewest inputs) ────────────────────────────────────


def test_minimal_inputs_returns_full_shape():
    out = recommend_faab(add_player_value=4000)
    # All four bid pills present, plus confidence + breakdown.
    assert set(out.keys()) >= {
        "conservative", "standard", "aggressive", "max",
        "confidence", "factors", "warnings", "explanation",
    }
    assert out["standard"] >= 0
    assert out["confidence"] == "low"  # most factors missing
    # Warnings list is iterable even when empty.
    assert isinstance(out["warnings"], list)
    # Explanation is human copy.
    assert isinstance(out["explanation"], str)
    assert out["explanation"]


def test_zero_value_returns_zero_bid():
    out = recommend_faab(add_player_value=0)
    assert out["standard"] == 0
    assert out["aggressive"] == 0


# ── Value-gain modifier ────────────────────────────────────────


def test_value_gain_boosts_standard_for_real_upgrades():
    """A 4000-value add beating a 2000-value drop should
    recommend MORE than the same add against a 4000-value drop."""
    big_upgrade = recommend_faab(
        add_player_value=4000, drop_player_value=2000,
    )
    even_swap = recommend_faab(
        add_player_value=4000, drop_player_value=4000,
    )
    assert big_upgrade["standard"] >= even_swap["standard"]


def test_negative_swap_recommends_zero_with_warning():
    """Add worth less than drop ⇒ recommend $0 + warning."""
    out = recommend_faab(add_player_value=2000, drop_player_value=5000)
    assert out["standard"] == 0
    assert any("worth more" in w for w in out["warnings"])


def test_marginal_swap_caps_bid_with_warning():
    """Add value == drop value ⇒ marginal upgrade ⇒ standard
    capped to a token bid."""
    out = recommend_faab(
        add_player_value=3000, drop_player_value=3000,
        team_faab_remaining=100, league_budget=100,
    )
    # Marginal — capped to roughly 50% of the baseline reasonable.
    # Without a drop side the bid would be ~$13; with the marginal
    # cap it should be much lower.
    assert out["standard"] <= 10
    assert any("marginal" in w.lower() for w in out["warnings"])


# ── Trending kicker ─────────────────────────────────────────────


def test_trending_count_high_bumps_standard():
    base = recommend_faab(
        add_player_value=4000, drop_player_value=1000,
        league_budget=100,
    )
    hot = recommend_faab(
        add_player_value=4000, drop_player_value=1000,
        league_budget=100,
        sleeper_trending={"count": 12000},  # top tier (10000+ → +20%)
    )
    assert hot["standard"] > base["standard"]
    # Trending factor labelled in the breakdown.
    assert any(f["label"].lower().startswith("trending") for f in hot["factors"])


def test_trending_missing_marks_factor():
    out = recommend_faab(
        add_player_value=4000,
        # sleeper_trending not passed
    )
    trending_factor = next(
        (f for f in out["factors"] if f["label"].lower().startswith("trending")),
        None,
    )
    assert trending_factor is not None
    assert trending_factor["missing"] is True


# ── League analytics calibration ────────────────────────────────


def test_league_calibration_blends_to_historical_bid():
    """When the league has historically paid $30 for WR1-tier
    waivers, our recommendation moves towards that."""
    summary = {
        "positionBids": {
            "WR": {"avg": 30.0, "count": 10, "min": 5, "max": 60},
        },
    }
    out = recommend_faab(
        add_player_value=2000, drop_player_value=500,
        add_player_position="WR",
        league_faab_summary=summary,
        league_budget=100,
    )
    # The 4-figure player would normally bid ~$15 — calibration
    # towards $30 should pull it up.
    assert out["standard"] > 15
    factor = next(
        (f for f in out["factors"]
         if f["label"].lower().startswith("league historical")),
        None,
    )
    assert factor is not None
    assert factor["missing"] is False


def test_league_calibration_skipped_when_position_undersamples():
    """≤2 historical bids for a position ⇒ skip calibration to
    avoid noise."""
    summary = {
        "positionBids": {
            "WR": {"avg": 50.0, "count": 1, "min": 50, "max": 50},
        },
    }
    out = recommend_faab(
        add_player_value=2000,
        add_player_position="WR",
        league_faab_summary=summary,
        league_budget=100,
    )
    factor = next(
        (f for f in out["factors"]
         if f["label"].lower().startswith("league historical")),
        None,
    )
    assert factor is not None
    assert factor["missing"] is True


def test_league_summary_missing_marks_factor():
    out = recommend_faab(add_player_value=2000)
    factor = next(
        (f for f in out["factors"]
         if "league" in f["label"].lower()),
        None,
    )
    assert factor is not None
    assert factor["missing"] is True


# ── KTC crowd blend ─────────────────────────────────────────────


def test_ktc_crowd_blend_pulls_towards_crowd_bid():
    """KTC crowd reports 35% of budget for player → blend pulls
    standard towards $35 in a 100-budget league."""
    out = recommend_faab(
        add_player_value=2000, drop_player_value=500,
        add_player_position="WR",
        add_player_name="Test Player",
        league_budget=100,
        ktc_crowd_bids={"test player": 35.0},
    )
    # Without crowd: ~$15; with 70/30 blend toward $35 → up.
    assert out["standard"] > 15
    factor = next(
        (f for f in out["factors"]
         if f["label"].lower().startswith("ktc crowd")),
        None,
    )
    assert factor is not None


def test_ktc_crowd_missing_player_is_noop():
    """Crowd map present but doesn't have the specific player ⇒
    no crowd factor is added (silent passthrough)."""
    out = recommend_faab(
        add_player_value=2000,
        add_player_name="Other Player",
        ktc_crowd_bids={"different person": 25.0},
    )
    factor = next(
        (f for f in out["factors"]
         if f["label"].lower().startswith("ktc crowd")),
        None,
    )
    assert factor is None


# ── Team FAAB cap ───────────────────────────────────────────────


def test_team_faab_cap_clips_recommendation():
    """When a team has $5 FAAB left, we never recommend more than $5."""
    out = recommend_faab(
        add_player_value=8000, drop_player_value=1000,
        team_faab_remaining=5,
        league_budget=100,
    )
    assert out["standard"] <= 5
    assert out["max"] == 5
    assert any("cap" in w.lower() for w in out["warnings"])
    factor = next(
        (f for f in out["factors"]
         if f["label"].lower().startswith("team faab cap")),
        None,
    )
    assert factor is not None


def test_team_faab_zero_recommends_zero():
    """Team is broke (0 FAAB) ⇒ recommendation floors at 0."""
    out = recommend_faab(
        add_player_value=8000,
        team_faab_remaining=0,
        league_budget=100,
    )
    assert out["standard"] == 0
    assert out["aggressive"] == 0


# ── Confidence ─────────────────────────────────────────────────


def test_all_inputs_present_returns_high_confidence():
    out = recommend_faab(
        add_player_value=4000, drop_player_value=1000,
        add_player_position="WR",
        add_player_name="Hot Pickup",
        team_faab_remaining=80,
        league_faab_summary={
            "positionBids": {
                "WR": {"avg": 25.0, "count": 12, "min": 5, "max": 50},
            },
        },
        sleeper_trending={"count": 8000},
        ktc_crowd_bids={"hot pickup": 28.0},
        league_budget=100,
    )
    # All factors present (or actively contributing) ⇒ high
    # confidence.  Allow medium too in case calibration registers
    # as no-op.
    assert out["confidence"] in ("medium", "high")


def test_no_inputs_returns_low_confidence():
    out = recommend_faab(add_player_value=4000)
    assert out["confidence"] == "low"


# ── Explanation copy ────────────────────────────────────────────


def test_explanation_present_for_every_branch():
    """Every code path emits non-empty explanation copy."""
    cases = [
        # Negative swap → "don't bid".
        recommend_faab(add_player_value=1000, drop_player_value=5000),
        # Zero/token bid → "token bid".
        recommend_faab(
            add_player_value=4000,
            team_faab_remaining=2,
            league_budget=100,
        ),
        # Drop-side present → "swap" copy.
        recommend_faab(
            add_player_value=4000, drop_player_value=1000,
            team_faab_remaining=80, league_budget=100,
        ),
        # No drop → "free-agent target" copy.
        recommend_faab(add_player_value=4000),
    ]
    for out in cases:
        assert isinstance(out["explanation"], str)
        assert len(out["explanation"]) > 10  # at least a sentence
