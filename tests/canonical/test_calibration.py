"""Tests for canonical value calibration layer."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.canonical.calibration import (
    calibrate_canonical_values,
    get_calibration_params,
    CALIBRATION_SCALE,
    CALIBRATION_EXPONENT,
)


def _make_assets(universe: str, values: list[int]) -> list[dict]:
    return [
        {"blended_value": v, "display_name": f"Player_{i}",
         "universe": universe, "source_values": {"SRC": v}}
        for i, v in enumerate(values)
    ]


class TestCalibration:
    def test_adds_calibrated_value(self):
        assets = _make_assets("offense_vet", [9000, 7000, 5000, 3000])
        result = calibrate_canonical_values(assets)
        for a in result:
            assert "calibrated_value" in a

    def test_preserves_blended_value(self):
        assets = _make_assets("offense_vet", [9000, 7000, 5000])
        result = calibrate_canonical_values(assets)
        assert result[0]["blended_value"] == 9000

    def test_top_player_gets_max(self):
        assets = _make_assets("offense_vet", [9999, 8000, 6000, 4000, 2000])
        result = calibrate_canonical_values(assets)
        top = max(result, key=lambda a: a["calibrated_value"])
        assert top["calibrated_value"] == CALIBRATION_SCALE

    def test_ordering_preserved(self):
        assets = _make_assets("offense_vet", [9000, 7000, 5000, 3000, 1000])
        result = calibrate_canonical_values(assets)
        cal_vals = [a["calibrated_value"] for a in result]
        assert cal_vals == sorted(cal_vals, reverse=True)

    def test_universes_calibrated_independently(self):
        off = _make_assets("offense_vet", [9000, 7000])
        idp = _make_assets("idp_vet", [8000, 6000])
        result = calibrate_canonical_values(off + idp)

        off_top = [a for a in result if a["universe"] == "offense_vet"][0]
        idp_top = [a for a in result if a["universe"] == "idp_vet"][0]
        # Both tops should get max calibrated value within their universe
        assert off_top["calibrated_value"] == CALIBRATION_SCALE
        assert idp_top["calibrated_value"] == CALIBRATION_SCALE

    def test_larger_pool_produces_more_spread(self):
        # With more players, bottom values should be lower
        small = _make_assets("offense_vet", [9000, 7000, 5000])
        large = _make_assets("offense_vet", list(range(9000, 1000, -100)))  # 80 players

        small_result = calibrate_canonical_values(small)
        large_result = calibrate_canonical_values(large)

        small_bottom = min(a["calibrated_value"] for a in small_result)
        large_bottom = min(a["calibrated_value"] for a in large_result)
        assert large_bottom < small_bottom

    def test_calibration_params(self):
        params = get_calibration_params()
        assert params["scale"] == CALIBRATION_SCALE
        assert params["exponent"] == CALIBRATION_EXPONENT
        assert "description" in params

    def test_custom_params(self):
        assets = _make_assets("offense_vet", [9000, 7000, 5000])
        result = calibrate_canonical_values(assets, scale=5000, exponent=1.0)
        top = max(result, key=lambda a: a["calibrated_value"])
        assert top["calibrated_value"] == 5000


class TestCalibrationDistribution:
    """Test that calibration produces a reasonable tier distribution."""

    def test_tier_distribution_matches_legacy_shape(self):
        # Simulate 400 players in offense_vet
        values = list(range(9999, 5000, -12))  # ~416 players
        assets = _make_assets("offense_vet", values)
        result = calibrate_canonical_values(assets)

        def tier(v):
            if v >= 7000: return "elite"
            if v >= 5000: return "star"
            if v >= 3000: return "starter"
            if v >= 1500: return "bench"
            return "depth"

        from collections import Counter
        tiers = Counter(tier(a["calibrated_value"]) for a in result)

        # With calibration, should NOT be top-heavy
        # Elite should be < 15% of pool (vs ~50% without calibration)
        elite_pct = tiers["elite"] / len(result) * 100
        assert elite_pct < 20, f"Elite is {elite_pct}% — still too top-heavy"

        # Should have meaningful depth
        assert tiers["depth"] > 0
        assert tiers["bench"] > 0
