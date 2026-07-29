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

from src.adapters.ktc_crowd_faab import build_crowd_bid_map
from src.trade.faab_recommender import compute_confidence, recommend_faab


# ── Baseline (fewest inputs) ────────────────────────────────────


def test_minimal_inputs_returns_full_shape():
    out = recommend_faab(add_player_value=4000)
    # All four bid pills present, plus confidence + breakdown.
    assert set(out.keys()) >= {
        "conservative",
        "standard",
        "aggressive",
        "max",
        "confidence",
        "factors",
        "warnings",
        "explanation",
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
        add_player_value=4000,
        drop_player_value=2000,
    )
    even_swap = recommend_faab(
        add_player_value=4000,
        drop_player_value=4000,
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
        add_player_value=3000,
        drop_player_value=3000,
        team_faab_remaining=100,
        league_budget=100,
    )
    # Marginal — capped to roughly 50% of the baseline reasonable.
    # Without a drop side the bid would be ~$13; with the marginal
    # cap it should be much lower.
    assert out["standard"] <= 10
    assert any("marginal" in w.lower() for w in out["warnings"])


# ── Trending kicker ─────────────────────────────────────────────


def test_trending_count_high_bumps_standard():
    base = recommend_faab(
        add_player_value=4000,
        drop_player_value=1000,
        league_budget=100,
    )
    hot = recommend_faab(
        add_player_value=4000,
        drop_player_value=1000,
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
        add_player_value=2000,
        drop_player_value=500,
        add_player_position="WR",
        league_faab_summary=summary,
        league_budget=100,
    )
    # The 4-figure player would normally bid ~$15 — calibration
    # towards $30 should pull it up.
    assert out["standard"] > 15
    factor = next(
        (f for f in out["factors"] if f["label"].lower().startswith("league historical")),
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
        (f for f in out["factors"] if f["label"].lower().startswith("league historical")),
        None,
    )
    assert factor is not None
    assert factor["missing"] is True


def test_league_summary_missing_marks_factor():
    out = recommend_faab(add_player_value=2000)
    factor = next(
        (f for f in out["factors"] if "league" in f["label"].lower()),
        None,
    )
    assert factor is not None
    assert factor["missing"] is True


# ── KTC crowd blend ─────────────────────────────────────────────
#
# These tests feed a map built by the REAL producer
# (``ktc_crowd_faab.build_crowd_bid_map``) rather than a hand-written
# literal.  A literal in the wrong key shape is exactly what masked
# the 2026-07-29 defect: the producer keyed the map with the compact
# alphanumeric key ("tjwatt") while the recommender looked it up with
# ``strip().lower()`` ("t.j. watt"), so the factor never fired for any
# name containing a space — i.e. every real player.


def _crowd_map(name: str, pct_of_budget: float, *, budget: int = 100) -> dict[str, float]:
    """Build a crowd map through the production bridge so the key shape
    is pinned by the producer, not by this file."""
    bid = pct_of_budget / 100.0 * budget
    return build_crowd_bid_map(
        {
            "waivers": [
                {"added": name, "bid": bid, "settings": {"waiver_budget": budget}},
                {"added": name, "bid": bid, "settings": {"waiver_budget": budget}},
            ]
        }
    )


def test_ktc_crowd_blend_pulls_towards_crowd_bid():
    """KTC crowd reports 35% of budget for player → blend pulls
    standard towards $35 in a 100-budget league."""
    crowd = _crowd_map("Test Player", 35.0)
    out = recommend_faab(
        add_player_value=2000,
        drop_player_value=500,
        add_player_position="WR",
        add_player_name="Test Player",
        league_budget=100,
        ktc_crowd_bids=crowd,
    )
    # Without crowd: ~$15; with 70/30 blend toward $35 → up.
    assert out["standard"] > 15
    factor = next(
        (f for f in out["factors"] if f["label"].lower().startswith("ktc crowd")),
        None,
    )
    assert factor is not None


def test_ktc_crowd_blend_fires_for_a_punctuated_spaced_name():
    """Regression for the producer/consumer key mismatch.

    ``T.J. Watt`` exercises both properties the old bare
    ``strip().lower()`` lookup could not survive — a space and a
    period.  The server passes the raw display name straight through
    (``server.py`` FAAB endpoint → ``add_player_name``), so if this
    ever regresses the crowd factor silently disappears in production
    while every hand-keyed unit test keeps passing.
    """
    crowd = _crowd_map("T.J. Watt", 40.0)
    assert list(crowd) == ["tjwatt"], "producer key shape changed"
    out = recommend_faab(
        add_player_value=2000,
        drop_player_value=500,
        add_player_position="DL",
        add_player_name="T.J. Watt",
        league_budget=100,
        ktc_crowd_bids=crowd,
    )
    factor = next(
        (f for f in out["factors"] if f["label"].lower().startswith("ktc crowd")),
        None,
    )
    assert factor is not None, "crowd factor did not fire for a spaced, punctuated name"


def test_ktc_crowd_missing_player_is_noop():
    """Crowd map present but doesn't have the specific player ⇒
    no crowd factor is added (silent passthrough)."""
    out = recommend_faab(
        add_player_value=2000,
        add_player_name="Other Player",
        ktc_crowd_bids=_crowd_map("Different Person", 25.0),
    )
    factor = next(
        (f for f in out["factors"] if f["label"].lower().startswith("ktc crowd")),
        None,
    )
    assert factor is None


# ── Team FAAB cap ───────────────────────────────────────────────


def test_team_faab_cap_clips_recommendation():
    """When a team has $5 FAAB left, we never recommend more than $5."""
    out = recommend_faab(
        add_player_value=8000,
        drop_player_value=1000,
        team_faab_remaining=5,
        league_budget=100,
    )
    assert out["standard"] <= 5
    assert out["max"] == 5
    assert any("cap" in w.lower() for w in out["warnings"])
    factor = next(
        (f for f in out["factors"] if f["label"].lower().startswith("team faab cap")),
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
        add_player_value=4000,
        drop_player_value=1000,
        add_player_position="WR",
        add_player_name="Hot Pickup",
        team_faab_remaining=80,
        league_faab_summary={
            "positionBids": {
                "WR": {"avg": 25.0, "count": 12, "min": 5, "max": 50},
            },
        },
        sleeper_trending={"count": 8000},
        # Built by the same producer the runtime uses.  A hand-written
        # literal here used to read ``{"hot pickup": 28.0}`` — the OLD
        # key shape — so after the 2026-07-29 compact-key fix the crowd
        # factor silently did NOT fire and this test still passed on the
        # loose ``in ("medium", "high")`` assertion, while its name
        # claimed every input was present.  That is the exact masking
        # pattern the key-registry comment in the producer warns about.
        ktc_crowd_bids=_crowd_map("Hot Pickup", 28.0),
        league_budget=100,
    )
    # Every factor must actually be present — assert the crowd factor
    # fired rather than inferring it from the confidence bucket, which
    # is what let the old wrong-key literal pass unnoticed.
    crowd_factor = next(
        (f for f in out["factors"] if f["label"].lower().startswith("ktc crowd")),
        None,
    )
    assert (
        crowd_factor is not None
    ), f"crowd factor did not fire; labels were {[f['label'] for f in out['factors']]}"
    assert out["confidence"] == "high"


def test_no_inputs_returns_low_confidence():
    out = recommend_faab(add_player_value=4000)
    assert out["confidence"] == "low"


def test_compute_confidence_accepts_serialized_dict_rows():
    """The endpoint appends dict-shaped factor rows AFTER the
    recommendation and recomputes the bucket — the helper must read
    both _Factor objects and the serialized dict shape."""
    assert (
        compute_confidence([{"weight": 0.9, "missing": False}, {"weight": 0.1, "missing": True}])
        == "high"
    )
    assert (
        compute_confidence([{"weight": 0.5, "missing": False}, {"weight": 0.5, "missing": True}])
        == "low"
    )
    # Recomputing over a real response's factors matches the stamp.
    out = recommend_faab(add_player_value=4000)
    assert compute_confidence(out["factors"]) == out["confidence"]


# ── Explanation copy ────────────────────────────────────────────


# ── FAAB v2: contention clearing ────────────────────────────────


def _baseline_v1(**overrides):
    """The pre-contention value bid for a 4000-value FA in a $100
    league (standard = $21 with these inputs)."""
    kwargs = dict(add_player_value=4000, league_budget=100)
    kwargs.update(overrides)
    return recommend_faab(**kwargs)


def test_contention_raises_to_clearing_price():
    base = _baseline_v1()
    out = _baseline_v1(
        contention={"clearing": base["standard"] + 4, "topRival": base["standard"] + 3},
        next_best_fa_value=0.0,  # irreplaceable — dropoff 100%
    )
    assert out["standard"] == base["standard"] + 4
    factor = next(
        (f for f in out["factors"] if f["label"] == "Rival contention"),
        None,
    )
    assert factor is not None
    assert "clear top rival" in factor["contribution"]


def test_contention_already_cleared_keeps_value_bid():
    base = _baseline_v1()
    out = _baseline_v1(
        contention={"clearing": base["standard"] - 5, "topRival": base["standard"] - 6},
        next_best_fa_value=0.0,
    )
    assert out["standard"] == base["standard"]
    factor = next(
        (f for f in out["factors"] if f["label"] == "Rival contention"),
        None,
    )
    assert factor is not None
    assert "already clears" in factor["contribution"]


def test_contention_stops_at_value_ceiling_with_warning():
    """Projected clearing far above the value ceiling ⇒ stop at the
    ceiling + 'likely outbid' warning — never chase past value."""
    base = _baseline_v1()
    # Ceiling for a fully-irreplaceable player: aggressive(=1.4×std)
    # × 1.25 ⇒ std 21 → ceiling 36.  Clearing $80 blows past it.
    out = _baseline_v1(
        contention={"clearing": 80, "topRival": 79},
        next_best_fa_value=0.0,
    )
    expected_ceiling = round(round(base["standard"] * 1.40) * 1.25)
    assert out["standard"] == expected_ceiling
    assert out["standard"] < 80
    assert any("Likely outbid" in w for w in out["warnings"])


def test_dropoff_gate_blocks_clearing_chase_for_replaceable_player():
    """Next-best same-position FA within 15% ⇒ value bid only —
    the clearing price is NOT chased."""
    base = _baseline_v1()
    out = _baseline_v1(
        contention={"clearing": base["standard"] + 10, "topRival": base["standard"] + 9},
        next_best_fa_value=3800.0,  # dropoff 5% < 15% gate
    )
    assert out["standard"] == base["standard"]
    factor = next(
        (f for f in out["factors"] if f["label"] == "Replaceable at position"),
        None,
    )
    assert factor is not None
    assert "value bid only" in factor["contribution"]


def test_no_contention_input_is_pure_backward_compat():
    """Omitting the new kwargs reproduces v1 output exactly."""
    v1 = _baseline_v1()
    v2 = _baseline_v1(contention=None, next_best_fa_value=None)
    assert v1 == v2


# ── FAAB v2: budget-environment scaling ─────────────────────────


def test_env_scale_applies_in_hot_league_without_position_data():
    """Median winning bid 16% of budget (2× the 8% target) in a
    league with enough analyzed bids and NO per-position history ⇒
    scale up (clamped at 1.6)."""
    cold = recommend_faab(add_player_value=4000, league_budget=100)
    hot = recommend_faab(
        add_player_value=4000,
        add_player_position="WR",
        league_budget=100,
        league_faab_summary={
            "leagueMedianWinningBid": 16.0,
            "totalBidsAnalyzed": 20,
            "positionBids": {},
        },
    )
    assert hot["standard"] == round(cold["standard"] * 1.6)
    factor = next(
        (f for f in hot["factors"] if f["label"] == "Budget environment"),
        None,
    )
    assert factor is not None


def test_env_scale_requires_ten_analyzed_bids():
    out = recommend_faab(
        add_player_value=4000,
        add_player_position="WR",
        league_budget=100,
        league_faab_summary={
            "leagueMedianWinningBid": 16.0,
            "totalBidsAnalyzed": 9,  # below the floor
            "positionBids": {},
        },
    )
    assert not any(f["label"] == "Budget environment" for f in out["factors"])


def test_env_scale_skipped_when_position_calibration_applied():
    """REGRESSION (review-caught double-count bug): when
    positionBids[pos].count ≥ 3 the position calibration already
    anchors the bid to league prices — env scaling must NOT stack
    on top."""
    out = recommend_faab(
        add_player_value=4000,
        add_player_position="WR",
        league_budget=100,
        league_faab_summary={
            "leagueMedianWinningBid": 16.0,
            "totalBidsAnalyzed": 20,
            "positionBids": {
                "WR": {"avg": 30.0, "count": 10, "min": 5, "max": 60},
            },
        },
    )
    assert not any(f["label"] == "Budget environment" for f in out["factors"])
    # The position calibration DID fire instead.
    assert any(
        f["label"].lower().startswith("league historical") and not f["missing"]
        for f in out["factors"]
    )


def test_env_scale_clamps_cold_league_at_floor():
    out = recommend_faab(
        add_player_value=4000,
        add_player_position="WR",
        league_budget=100,
        league_faab_summary={
            "leagueMedianWinningBid": 1.0,  # 1% of budget → ratio 0.125 → clamp 0.6
            "totalBidsAnalyzed": 20,
            "positionBids": {},
        },
    )
    cold = recommend_faab(add_player_value=4000, league_budget=100)
    assert out["standard"] == round(cold["standard"] * 0.6)


# ── FAAB v2: pacing warning ─────────────────────────────────────


def test_pacing_warning_when_bid_exceeds_forty_pct_of_budget():
    out = recommend_faab(
        add_player_value=8000,
        drop_player_value=1000,
        team_faab_remaining=50,
        league_budget=100,
    )
    assert out["standard"] > 0.40 * 50  # precondition for the assert below
    assert any(w.startswith("Pacing:") for w in out["warnings"])


def test_no_pacing_warning_for_small_bids():
    out = recommend_faab(
        add_player_value=1000,
        team_faab_remaining=100,
        league_budget=100,
    )
    assert out["standard"] <= 0.40 * 100
    assert not any(w.startswith("Pacing:") for w in out["warnings"])


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
            add_player_value=4000,
            drop_player_value=1000,
            team_faab_remaining=80,
            league_budget=100,
        ),
        # No drop → "free-agent target" copy.
        recommend_faab(add_player_value=4000),
    ]
    for out in cases:
        assert isinstance(out["explanation"], str)
        assert len(out["explanation"]) > 10  # at least a sentence
