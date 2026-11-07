"""Tests for ``src/scoring/feature_engineering.py`` + the archetype
thresholds that read its output.

Every assertion here is a hand-computed number, because the whole
point of the module is that its features carry the units their names
and thresholds claim.  A test that recomputed the feature with the
production helper would have passed happily against the receptions-
per-YARD and TDs-per-YARD versions these pin against.
"""

from __future__ import annotations

import pytest

from src.scoring.archetype_model import infer_archetype
from src.scoring.feature_engineering import (
    RECEPTION_DEPENDENCY_TAG,
    compute_profile_features,
    infer_scoring_tags,
)


def _features(bucket: str, stats: dict[str, float], *, total_games: int = 16) -> dict[str, float]:
    return compute_profile_features(
        bucket,
        stats,
        total_games=total_games,
        recent_games=4,
        depth_factor=1.0,
        role_change=False,
    )


# ── td_dependency ───────────────────────────────────────────────


def test_td_dependency_is_a_production_share_not_tds_per_yard():
    """Goal-line back: 45 yd/g of offense and 0.9 TD/g.

    In yard-equivalents that is 0.9 × 60 = 54 from scores against 45
    from yardage → 54 / 99 = 0.545455 of production.

    The old formula was ``total_td / total_yd`` = 0.9 / 45 = 0.02 —
    touchdowns per YARD, thresholded at 0.06 (six scores per hundred
    yards).  No football player has ever cleared it, so the
    ``td_dependent`` tag could not fire for anyone.
    """
    f = _features(
        "RB",
        {
            "rush_yd": 35.0,
            "rush_td": 0.8,
            "rec": 1.5,
            "rec_yd": 10.0,
            "rec_td": 0.1,
            "rush_att": 9.0,
        },
    )
    assert abs(f["td_dependency"] - 0.545455) < 1e-6
    assert "td_dependent" in infer_scoring_tags("RB", f)


def test_td_dependency_does_not_fire_for_a_yardage_workhorse():
    """110 yd/g and 0.6 TD/g → 36 / 146 = 0.246575, below the cut."""
    f = _features(
        "RB",
        {"rush_yd": 90.0, "rush_td": 0.5, "rec": 3.0, "rec_yd": 20.0, "rec_td": 0.1},
    )
    assert abs(f["td_dependency"] - 0.246575) < 1e-6
    assert "td_dependent" not in infer_scoring_tags("RB", f)


def test_td_dependency_is_unknown_with_no_offensive_production():
    """No yardage/TD inputs observed -> unknown (omitted), not a 0.0 share."""
    f = _features("LB", {"idp_tkl_solo": 5.0, "idp_tkl_ast": 2.0})
    assert "td_dependency" not in f


def test_observed_zero_production_is_not_a_zero_share():
    f = _features("RB", {"rush_yd": 0.0, "rec_yd": 0.0, "rush_td": 0.0})
    assert "td_dependency" not in f


def test_missing_inputs_do_not_look_like_real_zero():
    from src.scoring.feature_engineering import scoring_tags_undecidable

    empty = _features("RB", {})
    assert "reception_dependency" not in empty
    assert "first_down_dependency" not in empty
    assert "turnover_sensitivity" not in empty
    assert "reception_sensitive" in scoring_tags_undecidable("RB", empty)
    real_zero = _features("RB", {"rush_yd": 80.0, "rec": 0.0, "rec_yd": 0.0, "rush_fd": 0.0})
    assert real_zero["reception_dependency"] == 0.0
    assert real_zero["first_down_dependency"] == 0.0
    assert "reception_sensitive" not in scoring_tags_undecidable("RB", real_zero)
    assert "scramble_floor_proxy" not in _features("QB", {"pass_yd": 250.0})
    assert _features("QB", {"pass_yd": 250.0, "rush_yd": 0.0})["scramble_floor_proxy"] == 0.0


def test_infer_scoring_tags_tolerates_none_and_nan_feature_values():
    feats = {"reception_dependency": None, "td_dependency": float("nan")}
    assert infer_scoring_tags("RB", feats) == []


# ── reception_dependency ────────────────────────────────────────


def test_wr_reception_dependency_is_commensurable_with_the_rb_threshold():
    """6 catches and 75 receiving yards → 60 yard-equivalents from the
    catches against 75 from yardage → 60 / 135 = 0.444444.

    The old WR formula was ``rec / rec_yd`` = 0.08 — receptions per
    YARD — checked against the same 0.22 the RB's genuine touch
    fraction used, so ``reception_sensitive`` could only ever fire for
    running backs.
    """
    f = _features("WR", {"rec": 6.0, "rec_yd": 75.0, "rec_td": 0.5})
    assert abs(f["reception_dependency"] - 0.444444) < 1e-6
    assert "reception_sensitive" in infer_scoring_tags("WR", f)


def test_te_carries_reception_dependency_at_all():
    """The TE branch never emitted ``reception_dependency``, so the
    {RB, WR, TE} tag read a missing key as 0.0 and never fired.

    5 catches, 55 yards → 50 / 105 = 0.476190.
    """
    f = _features("TE", {"rec": 5.0, "rec_yd": 55.0})
    assert abs(f["reception_dependency"] - 0.476190) < 1e-6
    assert "reception_sensitive" in infer_scoring_tags("TE", f)


def test_rb_reception_dependency_still_splits_backfield_roles():
    """The unified definition must keep doing the RB job the touch
    fraction did: a two-down back stays under the cut, a pass-catching
    back stays over it.

    Two-down: 2 rec → 20, 75 rush + 12 rec = 87 yd → 20 / 107 = 0.186916
    Receiving: 6 rec → 60, 35 rush + 50 rec = 85 yd → 60 / 145 = 0.413793
    """
    two_down = _features("RB", {"rec": 2.0, "rec_yd": 12.0, "rush_yd": 75.0, "rush_att": 16.0})
    receiving = _features("RB", {"rec": 6.0, "rec_yd": 50.0, "rush_yd": 35.0, "rush_att": 8.0})
    assert abs(two_down["reception_dependency"] - 0.186916) < 1e-6
    assert abs(receiving["reception_dependency"] - 0.413793) < 1e-6
    assert "reception_sensitive" not in infer_scoring_tags("RB", two_down)
    assert "reception_sensitive" in infer_scoring_tags("RB", receiving)


# ── te_premium_dependency ───────────────────────────────────────


def test_te_premium_cut_survives_the_change_of_units():
    """``te_premium_sensitive`` cut at 0.12 receptions-per-yard, i.e.
    a TE averaging at most 8.33 yards per catch.  Restated as a
    reception share that same cut is 10×0.12 / (10×0.12 + 1) = 0.5455
    — a change of variables, so the tag fires for exactly the stat
    lines it always did.

    8.0 y/r (5 rec, 40 yd) → 50 / 90 = 0.555556 → fires, as before.
    11.0 y/r (5 rec, 55 yd) → 50 / 105 = 0.476190 → doesn't, as before.
    """
    short_area = _features("TE", {"rec": 5.0, "rec_yd": 40.0})
    seam = _features("TE", {"rec": 5.0, "rec_yd": 55.0})
    assert abs(short_area["te_premium_dependency"] - 0.555556) < 1e-6
    assert abs(seam["te_premium_dependency"] - 0.476190) < 1e-6
    assert "te_premium_sensitive" in infer_scoring_tags("TE", short_area)
    assert "te_premium_sensitive" not in infer_scoring_tags("TE", seam)


# ── scramble_floor_proxy ────────────────────────────────────────


def test_scramble_floor_proxy_is_not_divided_by_games_twice():
    """``rush_yd`` arrives from ``stats_per_game`` already per game;
    dividing by ``total_games`` again made a 30 yd/g rusher read as
    1.875 over a 16-game season."""
    f = _features("QB", {"pass_yd": 250.0, "pass_td": 2.0, "rush_yd": 30.0}, total_games=16)
    assert f["scramble_floor_proxy"] == 30.0
    # And it must not move when the sample length does.
    short = _features("QB", {"pass_yd": 250.0, "pass_td": 2.0, "rush_yd": 30.0}, total_games=4)
    assert short["scramble_floor_proxy"] == f["scramble_floor_proxy"]


# ── threshold reconciliation ────────────────────────────────────


def test_archetype_and_tag_read_one_reception_threshold():
    """``infer_archetype`` cut ``receiving_rb`` at 0.18 while
    ``infer_scoring_tags`` cut ``reception_sensitive`` at 0.22 on the
    SAME feature, so a back could be a receiving_rb that the tag said
    wasn't reception-sensitive.  One constant now feeds both."""
    assert RECEPTION_DEPENDENCY_TAG == 0.22
    between = {"reception_dependency": 0.20, "goal_line_proxy": 0.0}
    archetype, _style = infer_archetype("RB", between)
    assert archetype == "early_down_rb"
    assert "reception_sensitive" not in infer_scoring_tags("RB", between)

    above = {"reception_dependency": 0.25, "goal_line_proxy": 0.0}
    assert infer_archetype("RB", above)[0] == "receiving_rb"
    assert "reception_sensitive" in infer_scoring_tags("RB", above)


# ── AMATH-S38: missing feature is UNKNOWN, never 0 ─────────────────
_BRANCH_CASES = [
    # bucket, feature, cut, hi label, lo label
    ("QB", "qb_rush_contribution", 0.22, "dual_threat_qb", "pocket_qb"),
    ("WR", "field_stretcher_proxy", 13.5, "field_stretcher_wr", "possession_wr"),
    ("TE", "red_zone_proxy", 0.45, "td_te", "volume_te"),
    ("DL", "splash_dependency", 1.2, "sack_dl", "tackle_dl"),
    ("LB", "tackle_dependency", 6.5, "tackle_lb", "splash_lb"),
    ("DB", "splash_dependency", 0.85, "ballhawk_db", "tackle_db"),
]


@pytest.mark.parametrize("bucket,key,cut,hi,lo", _BRANCH_CASES)
def test_missing_feature_is_unknown_not_default_label(bucket, key, cut, hi, lo):
    assert infer_archetype(bucket, {}) == ("unknown", "unknown")
    assert infer_archetype(bucket, {key: None}) == ("unknown", "unknown")
    assert infer_archetype(bucket, {key: float("nan")}) == ("unknown", "unknown")
    assert infer_archetype(bucket, {key: float("inf")}) == ("unknown", "unknown")
    assert infer_archetype(bucket, None) == ("unknown", "unknown")
    # Observed values (including an observed 0) still classify as before.
    assert infer_archetype(bucket, {key: 0.0})[0] == lo
    assert infer_archetype(bucket, {key: cut})[0] == hi


def test_rb_missing_features_unknown_observed_zero_unchanged():
    assert infer_archetype("RB", {})[0] == "unknown"
    assert infer_archetype("RB", {"goal_line_proxy": 0.9})[0] == "unknown"  # reception unobserved
    assert (
        infer_archetype("RB", {"reception_dependency": 0.1})[0] == "unknown"
    )  # goal line unobserved
    assert infer_archetype("RB", {"reception_dependency": 0.0, "goal_line_proxy": 0.0})[0] == (
        "early_down_rb"
    )
    assert infer_archetype("RB", {"reception_dependency": 0.5})[0] == "receiving_rb"
    assert infer_archetype("RB", {"reception_dependency": 0.1, "goal_line_proxy": 0.5})[0] == (
        "goal_line_rb"
    )
