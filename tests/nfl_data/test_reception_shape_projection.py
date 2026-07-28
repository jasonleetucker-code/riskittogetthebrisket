"""Projecting a reception-band shape forward.

Historical banded scoring is exact — play-by-play carries every catch.
Projections are the open half, because no source publishes banded
receptions. The decomposition that makes it tractable::

    projected banded points
        = projected receptions      (ordinary projection sources)
        x expected points per catch (this module)

and the second factor is a player TRAIT rather than a forecast. Measured
year-over-year r = 0.767 (2023->2024) and 0.718 (2024->2025), which is
high for a fantasy metric — most sit between 0.3 and 0.5.

The tests that matter most are the ones pinning what the shrinkage
REFUSES to do. r=0.72 is not 1.0, and a 20-catch shape estimated across
six bands has empty cells by chance. Taking it at face value would hand
the largest adjustments to the players whose shapes are least known —
the exact failure the IDP per-player attempt was refused for.
"""

from __future__ import annotations

import pytest

from src.nfl_data.reception_depth import BAND_KEYS
from src.nfl_data.reception_shape_projection import (
    MIN_RECEPTIONS_FOR_SHAPE,
    SHRINK_K,
    expected_points_per_catch,
    fit_shrinkage_constant,
    position_shapes,
    project_band_shape,
)

_CARD = {
    "rec": 0.08,
    "rec_0_4": 0.17,
    "rec_5_9": 0.42,
    "rec_10_19": 0.67,
    "rec_20_29": 0.92,
    "rec_30_39": 1.17,
    "rec_40p": 1.92,
}

_DEEP = {"rec_40p": 40}
_SHORT = {"rec_0_4": 40}
_POS_MID = {b: (1.0 if b == "rec_10_19" else 0.0) for b in BAND_KEYS}


def test_a_large_sample_keeps_most_of_the_players_own_shape():
    shape = project_band_shape({"rec_40p": 200}, _POS_MID)
    w = 200 / (200 + SHRINK_K)
    assert shape["rec_40p"] == pytest.approx(w)
    assert w > 0.8, "a 200-catch season should be mostly the player's own shape"


def test_a_small_sample_is_pulled_hard_toward_the_position():
    """THE GUARD. A thin shape must not produce a large adjustment.

    At n=10 the player keeps only 20% of his own shape, so an extreme
    observed distribution cannot express itself as an extreme value.
    """
    shape = project_band_shape({"rec_40p": 10}, _POS_MID)
    w = 10 / (10 + SHRINK_K)
    assert shape["rec_40p"] == pytest.approx(w)
    assert w < 0.25, "a 10-catch sample is being trusted far too much"


def test_shrinkage_compresses_value_more_than_it_compresses_shape():
    """The property that makes this safe in points terms."""
    thin = expected_points_per_catch(project_band_shape({"rec_40p": 10}, _POS_MID), _CARD)
    thick = expected_points_per_catch(project_band_shape({"rec_40p": 200}, _POS_MID), _CARD)
    mid = expected_points_per_catch(_POS_MID, _CARD)
    assert mid < thin < thick, "shrinkage should order thin between position and thick"
    assert (thin - mid) < 0.35 * (thick - mid)


def test_below_the_floor_the_player_shape_is_ignored_entirely():
    shape = project_band_shape({"rec_40p": MIN_RECEPTIONS_FOR_SHAPE - 1}, _POS_MID)
    assert shape == pytest.approx(_POS_MID)


def test_an_unknown_player_returns_none_rather_than_a_flat_guess():
    """Unknown and league-average must not be the same value.

    Returning a uniform or position shape for a player with no data at
    all would price him as average while looking like a measurement —
    the failure mode this codebase keeps paying for.
    """
    assert project_band_shape(None, None) is None
    assert project_band_shape({}, None) is None
    assert expected_points_per_catch(None, _CARD) is None


def test_position_shapes_are_catch_weighted_not_player_weighted():
    """A 9-catch specialist must not count as much as a workhorse."""
    payload = {
        "players": {
            "a": {"bands": {"rec_40p": 100}},
            "b": {"bands": {"rec_0_4": 10}},
        }
    }
    shapes = position_shapes(payload, {"a": "WR", "b": "WR"})
    assert shapes["WR"]["rec_40p"] == pytest.approx(100 / 110)


def test_positions_do_not_contaminate_each_other():
    """An RB's catch distribution is a different distribution, not a
    noisy draw from the WR one. Shrinking toward a pooled league mean
    would drag every back toward a shape no back has."""
    payload = {
        "players": {
            "wr": {"bands": {"rec_40p": 50}},
            "rb": {"bands": {"rec_0_4": 50}},
        }
    }
    shapes = position_shapes(payload, {"wr": "WR", "rb": "RB"})
    assert shapes["WR"]["rec_40p"] == pytest.approx(1.0)
    assert shapes["RB"]["rec_0_4"] == pytest.approx(1.0)


def test_the_shape_always_sums_to_one():
    for bands in ({"rec_40p": 40}, {"rec_0_4": 12, "rec_20_29": 30}, {"rec_5_9": 9}):
        shape = project_band_shape(bands, _POS_MID)
        assert sum(shape.values()) == pytest.approx(1.0)


def test_negative_counts_cannot_create_negative_probability():
    """A corrupt row must degrade, not invert."""
    shape = project_band_shape({"rec_40p": 40, "rec_0_4": -100}, _POS_MID)
    assert all(v >= 0.0 for v in shape.values())
    assert sum(shape.values()) == pytest.approx(1.0)


def test_deep_and_short_shapes_price_in_the_right_order():
    deep = expected_points_per_catch(project_band_shape(_DEEP, _POS_MID), _CARD)
    short = expected_points_per_catch(project_band_shape(_SHORT, _POS_MID), _CARD)
    assert short < deep


def test_the_fitter_prefers_shrinkage_to_either_extreme():
    """The result that justifies the method, on synthetic data with the
    same structure as the real fit.

    Players have a true shape plus sampling noise. Trusting the noisy
    observation (K=0) overfits; ignoring it (K=inf) discards real
    signal. If the fitter did not beat both, shrinkage would be doing no
    work and the constant would be decoration.
    """
    import random

    rng = random.Random(11)
    positions = {}
    prior = {"players": {}}
    later = {"players": {}}
    for i in range(120):
        gid = f"p{i:03d}"
        positions[gid] = "WR"
        deep_rate = rng.uniform(0.05, 0.45)  # the player's TRUE tendency

        def draw(n):
            bands = {b: 0 for b in BAND_KEYS}
            for _ in range(n):
                bands["rec_40p" if rng.random() < deep_rate else "rec_5_9"] += 1
            return bands

        prior["players"][gid] = {"bands": draw(rng.randint(25, 60))}
        later["players"][gid] = {"bands": draw(40)}

    res = fit_shrinkage_constant(prior, later, positions, _CARD)
    assert res["fitted"] is not None
    assert res["mseAtBest"] < res["mseTrustPlayer"], "shrinkage must beat trusting the sample"
    assert res["mseAtBest"] < res["mseIgnorePlayer"], "shrinkage must beat the position mean"
    assert 0.0 < res["fitted"] < 1e9, "an endpoint won; shrinkage is doing nothing"


def test_the_shipped_constant_sits_in_the_fitted_range():
    """``SHRINK_K`` is fitted on real seasons, and its optimum is flat
    between roughly 30 and 60. This pins that the shipped value stays in
    that basin rather than drifting to an endpoint."""
    assert 30.0 <= SHRINK_K <= 60.0


# ── In-season blending ───────────────────────────────────────────────


def test_blending_weights_counts_not_shapes():
    """Sample size must carry through the blend.

    A 3-catch current season must not get an equal vote with a 90-catch
    prior. Weighting shapes rather than counts would do exactly that,
    and would hand the loudest voice to the least evidence — in week 2,
    every week.
    """
    from src.nfl_data.reception_shape_projection import blend_seasons

    blended = blend_seasons({2025: {"rec_0_4": 90}, 2026: {"rec_40p": 3}})
    assert blended["rec_40p"] == pytest.approx(3.0)
    assert blended["rec_0_4"] == pytest.approx(45.0)  # 90 at half weight
    assert blended["rec_0_4"] > blended["rec_40p"], "3 catches outvoted 90"


def test_the_current_season_is_weighted_highest():
    from src.nfl_data.reception_shape_projection import blend_seasons

    blended = blend_seasons(
        {2024: {"rec_0_4": 100}, 2025: {"rec_0_4": 100}, 2026: {"rec_0_4": 100}}
    )
    # 100 + 50 + 25 across three seasons at a one-season half-life.
    assert blended["rec_0_4"] == pytest.approx(175.0)


def test_a_changed_role_pulls_the_blend_as_the_season_accumulates():
    """The property that makes in-season data worth ingesting at all.

    A player who was a checkdown back and is now running deep routes
    should move — slowly at first, then decisively — rather than being
    pinned to his history forever.
    """
    from src.nfl_data.reception_shape_projection import blend_seasons

    prior = {"rec_0_4": 80}
    early = blend_seasons({2025: prior, 2026: {"rec_40p": 5}})
    late = blend_seasons({2025: prior, 2026: {"rec_40p": 60}})
    share_early = early["rec_40p"] / sum(early.values())
    share_late = late["rec_40p"] / sum(late.values())
    assert share_early < 0.2, "5 catches should barely move him"
    assert share_late > 0.5, "60 catches should dominate an old shape"
    assert share_late > share_early


def test_blending_a_single_season_is_a_no_op():
    from src.nfl_data.reception_shape_projection import blend_seasons

    assert blend_seasons({2025: {"rec_10_19": 40}})["rec_10_19"] == pytest.approx(40.0)


def test_blending_nothing_is_empty_not_uniform():
    from src.nfl_data.reception_shape_projection import blend_seasons

    blended = blend_seasons({})
    assert sum(blended.values()) == 0.0
    assert project_band_shape(blended, None) is None, "empty must stay unknown"
