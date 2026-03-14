"""Unit tests for src/canonical/transform.py"""
from __future__ import annotations

import pytest

from src.canonical.transform import (
    CANONICAL_SCALE,
    blend_source_values,
    build_canonical_by_universe,
    clamp,
    detect_suspicious_value_jumps,
    flatten_canonical,
    per_source_scores_for_universe,
    percentile_from_rank,
    percentile_to_canonical,
    rank_to_canonical,
    rookie_universe_warnings,
    split_by_universe,
)
from src.data_models import CanonicalAssetValue, RawAssetRecord


def _make_record(
    name: str = "Player A",
    source: str = "dlf_sf",
    universe: str = "offense_vet",
    rank: float | None = 1.0,
    value: float | None = None,
) -> RawAssetRecord:
    return RawAssetRecord(
        source=source,
        snapshot_id="snap_001",
        asset_type="player",
        external_asset_id="",
        external_name=name,
        display_name=name,
        team_raw="",
        position_raw="QB",
        age_raw="",
        rookie_flag_raw="",
        rank_raw=rank,
        value_raw=value,
        tier_raw="",
        universe=universe,
        format_key="dynasty_sf",
        is_idp=False,
        is_offense=True,
        source_notes="test",
        name_normalized_guess=name.lower(),
        asset_key=f"player::{name.lower()}",
    )


# ── clamp ────────────────────────────────────────────────────────────

class TestClamp:
    def test_within_range(self):
        assert clamp(5.0, 0.0, 10.0) == 5.0

    def test_below_range(self):
        assert clamp(-1.0, 0.0, 10.0) == 0.0

    def test_above_range(self):
        assert clamp(15.0, 0.0, 10.0) == 10.0


# ── percentile_from_rank ─────────────────────────────────────────────

class TestPercentileFromRank:
    def test_rank_1_is_top(self):
        p = percentile_from_rank(1.0, 100)
        assert p == 1.0

    def test_last_rank(self):
        p = percentile_from_rank(100.0, 100)
        assert p == pytest.approx(0.01, abs=0.001)

    def test_middle_rank(self):
        p = percentile_from_rank(50.0, 100)
        assert 0.49 < p < 0.55

    def test_depth_one(self):
        assert percentile_from_rank(1.0, 1) == 1.0

    def test_clamped_to_depth(self):
        # Rank beyond depth should still be valid
        p = percentile_from_rank(200.0, 100)
        assert p >= 0.0


# ── percentile_to_canonical ──────────────────────────────────────────

class TestPercentileToCanonical:
    def test_perfect_percentile(self):
        assert percentile_to_canonical(1.0) == CANONICAL_SCALE

    def test_zero_percentile(self):
        assert percentile_to_canonical(0.0) == 0

    def test_mid_percentile(self):
        score = percentile_to_canonical(0.5)
        # With 0.65 exponent, 0.5^0.65 ≈ 0.637, so score ≈ 6365
        assert 6000 < score < 7000

    def test_custom_exponent(self):
        score_steep = percentile_to_canonical(0.5, exponent=1.0)
        score_flat = percentile_to_canonical(0.5, exponent=0.5)
        # Steeper exponent should give lower score for mid-range
        assert score_steep < score_flat


# ── rank_to_canonical ────────────────────────────────────────────────

class TestRankToCanonical:
    def test_rank_1_is_max(self):
        assert rank_to_canonical(1.0, 100) == CANONICAL_SCALE

    def test_last_rank_is_low(self):
        score = rank_to_canonical(100.0, 100)
        assert score < 600

    def test_consistency(self):
        # rank_to_canonical should equal the composed functions
        p = percentile_from_rank(25.0, 100)
        expected = percentile_to_canonical(p)
        assert rank_to_canonical(25.0, 100) == expected


# ── split_by_universe ────────────────────────────────────────────────

class TestSplitByUniverse:
    def test_groups_correctly(self):
        records = [
            _make_record(name="A", universe="offense_vet"),
            _make_record(name="B", universe="offense_rookie"),
            _make_record(name="C", universe="offense_vet"),
        ]
        grouped = split_by_universe(records)
        assert len(grouped["offense_vet"]) == 2
        assert len(grouped["offense_rookie"]) == 1

    def test_empty_universe_becomes_unknown(self):
        rec = _make_record(universe="")
        grouped = split_by_universe([rec])
        assert "unknown" in grouped


# ── per_source_scores_for_universe ───────────────────────────────────

class TestPerSourceScores:
    def test_single_source_scores(self):
        records = [
            _make_record(name="A", rank=1.0),
            _make_record(name="B", rank=2.0),
            _make_record(name="C", rank=3.0),
        ]
        scores = per_source_scores_for_universe(records)
        assert "dlf_sf" in scores
        dlf = scores["dlf_sf"]
        assert dlf["player::a"] > dlf["player::b"] > dlf["player::c"]

    def test_top_rank_gets_max(self):
        records = [_make_record(name="A", rank=1.0)]
        scores = per_source_scores_for_universe(records)
        assert scores["dlf_sf"]["player::a"] == CANONICAL_SCALE

    def test_multiple_sources_separated(self):
        records = [
            _make_record(name="A", source="dlf", rank=1.0),
            _make_record(name="A", source="ktc", rank=1.0),
        ]
        scores = per_source_scores_for_universe(records)
        assert "dlf" in scores
        assert "ktc" in scores


# ── blend_source_values ──────────────────────────────────────────────

class TestBlendSourceValues:
    def test_equal_weights(self):
        per_source = {
            "dlf": {"player::a": 8000},
            "ktc": {"player::a": 6000},
        }
        weights = {"dlf": 1.0, "ktc": 1.0}
        result = blend_source_values(per_source, weights, "offense_vet")
        assert len(result) == 1
        assert result[0].blended_value == 7000

    def test_weighted_blend(self):
        per_source = {
            "dlf": {"player::a": 9000},
            "ktc": {"player::a": 3000},
        }
        weights = {"dlf": 3.0, "ktc": 1.0}
        result = blend_source_values(per_source, weights, "offense_vet")
        # (9000*3 + 3000*1) / (3+1) = 30000/4 = 7500
        assert result[0].blended_value == 7500

    def test_zero_weight_excluded(self):
        per_source = {
            "dlf": {"player::a": 8000},
            "bad": {"player::a": 0},
        }
        weights = {"dlf": 1.0, "bad": 0.0}
        result = blend_source_values(per_source, weights, "offense_vet")
        assert result[0].blended_value == 8000

    def test_sorted_by_value_descending(self):
        per_source = {
            "dlf": {"player::a": 5000, "player::b": 8000},
        }
        result = blend_source_values(per_source, {"dlf": 1.0}, "test")
        assert result[0].asset_key == "player::b"
        assert result[1].asset_key == "player::a"


# ── detect_suspicious_value_jumps ────────────────────────────────────

class TestDetectJumps:
    def test_no_jump(self):
        current = [CanonicalAssetValue("a", "A", "off", {}, 5000)]
        previous = [CanonicalAssetValue("a", "A", "off", {}, 5100)]
        assert detect_suspicious_value_jumps(current, previous) == []

    def test_jump_detected(self):
        current = [CanonicalAssetValue("a", "A", "off", {}, 9000)]
        previous = [CanonicalAssetValue("a", "A", "off", {}, 5000)]
        warnings = detect_suspicious_value_jumps(current, previous, jump_threshold=1800)
        assert len(warnings) == 1
        assert warnings[0]["delta"] == 4000

    def test_new_asset_no_warning(self):
        current = [CanonicalAssetValue("new", "New", "off", {}, 9000)]
        previous = [CanonicalAssetValue("old", "Old", "off", {}, 5000)]
        assert detect_suspicious_value_jumps(current, previous) == []


# ── flatten_canonical ────────────────────────────────────────────────

class TestFlattenCanonical:
    def test_flattens_and_sorts(self):
        by_universe = {
            "offense_vet": [CanonicalAssetValue("a", "A", "off", {}, 5000)],
            "offense_rookie": [CanonicalAssetValue("b", "B", "rk", {}, 8000)],
        }
        flat = flatten_canonical(by_universe)
        assert len(flat) == 2
        assert flat[0].blended_value >= flat[1].blended_value


# ── rookie_universe_warnings ─────────────────────────────────────────

class TestRookieWarnings:
    def test_large_rookie_universe_warns(self):
        records = [_make_record(name=f"P{i}", universe="offense_rookie") for i in range(260)]
        warnings = rookie_universe_warnings(records)
        assert any(w["warning"] == "rookie_universe_count_unusually_large" for w in warnings)

    def test_small_non_rookie_warns(self):
        records = [_make_record(name=f"P{i}", universe="offense_vet") for i in range(50)]
        warnings = rookie_universe_warnings(records)
        assert any(w["warning"] == "non_rookie_universe_count_unusually_small" for w in warnings)

    def test_normal_counts_no_warnings(self):
        records = [_make_record(name=f"P{i}", universe="offense_vet") for i in range(100)]
        warnings = rookie_universe_warnings(records)
        assert len(warnings) == 0


# ── build_canonical_by_universe (integration) ────────────────────────

class TestBuildCanonicalByUniverse:
    def test_end_to_end(self):
        records = [
            _make_record(name="A", rank=1.0, universe="offense_vet"),
            _make_record(name="B", rank=2.0, universe="offense_vet"),
            _make_record(name="C", rank=1.0, universe="offense_rookie"),
        ]
        weights = {"dlf_sf": 1.0}
        result = build_canonical_by_universe(records, weights)
        assert "offense_vet" in result
        assert "offense_rookie" in result
        assert len(result["offense_vet"]) == 2
        assert len(result["offense_rookie"]) == 1
        # First player should have highest value
        assert result["offense_vet"][0].blended_value > result["offense_vet"][1].blended_value
