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
    UNIVERSE_SCALES,
    CALIBRATION_EXPONENT,
    PICK_CEILING,
    DEFAULT_SCALE,
    _is_pick,
    _parse_pick_info,
    _pick_curve_value,
    LEGACY_PICK_ROUND_CURVE,
)


LEGACY_PATH = REPO / "data" / "legacy_data_2026-03-22.json"


def _make_assets(universe: str, values: list[int], names: list[str] | None = None) -> list[dict]:
    return [
        {"blended_value": v, "display_name": names[i] if names else f"Player_{i}",
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

    def test_top_player_gets_universe_max(self):
        off = _make_assets("offense_vet", [9999, 8000, 6000, 4000, 2000])
        idp = _make_assets("idp_vet", [9999, 8000, 6000, 4000, 2000])
        result = calibrate_canonical_values(off + idp)

        off_top = [a for a in result if a["universe"] == "offense_vet"][0]
        idp_top = [a for a in result if a["universe"] == "idp_vet"][0]
        assert off_top["calibrated_value"] == UNIVERSE_SCALES["offense_vet"]
        assert idp_top["calibrated_value"] == UNIVERSE_SCALES["idp_vet"]

    def test_idp_ceiling_lower_than_offense(self):
        off = _make_assets("offense_vet", [9999])
        idp = _make_assets("idp_vet", [9999])
        result = calibrate_canonical_values(off + idp)
        off_val = [a for a in result if a["universe"] == "offense_vet"][0]["calibrated_value"]
        idp_val = [a for a in result if a["universe"] == "idp_vet"][0]["calibrated_value"]
        assert idp_val < off_val

    def test_ordering_preserved(self):
        assets = _make_assets("offense_vet", [9000, 7000, 5000, 3000, 1000])
        result = calibrate_canonical_values(assets)
        cal_vals = [a["calibrated_value"] for a in result]
        assert cal_vals == sorted(cal_vals, reverse=True)


class TestPickDetection:
    def test_is_pick(self):
        assert _is_pick({"display_name": "2026 Pick 1.01"}) is True
        assert _is_pick({"display_name": "2026 Early 1st"}) is True
        assert _is_pick({"display_name": "Early 1st"}) is True
        assert _is_pick({"display_name": "2027 Mid 2nd"}) is True
        assert _is_pick({"display_name": "2026 1st"}) is True
        assert _is_pick({"display_name": "2027 2nd"}) is True
        assert _is_pick({"display_name": "Patrick Mahomes"}) is False
        assert _is_pick({"display_name": "T.J. Watt"}) is False


class TestPickParsing:
    def test_specific_pick(self):
        info = _parse_pick_info("2026 Pick 1.01")
        assert info["year"] == 2026
        assert info["round"] == 1
        assert info["slot"] == 1

    def test_tiered_pick(self):
        info = _parse_pick_info("2027 Early 1st")
        assert info["year"] == 2027
        assert info["round"] == 1
        assert info["tier"] == "early"

    def test_bare_year_round(self):
        info = _parse_pick_info("2026 1st")
        assert info["year"] == 2026
        assert info["round"] == 1

    def test_no_year(self):
        info = _parse_pick_info("Mid 2nd")
        assert info["year"] is None
        assert info["round"] == 2
        assert info["tier"] == "mid"


class TestPickCurveValue:
    def test_round_1_value(self):
        val = _pick_curve_value({"round": 1})
        assert 5000 < val < 8000

    def test_early_tier_boost(self):
        early = _pick_curve_value({"round": 1, "tier": "early"})
        mid = _pick_curve_value({"round": 1})
        assert early > mid

    def test_late_tier_discount(self):
        late = _pick_curve_value({"round": 1, "tier": "late"})
        mid = _pick_curve_value({"round": 1})
        assert late < mid

    def test_future_year_discount(self):
        current = _pick_curve_value({"year": 2026, "round": 1}, current_year=2026)
        future = _pick_curve_value({"year": 2028, "round": 1}, current_year=2026)
        assert future < current

    def test_current_year_not_discounted(self):
        """A pick in the current year should NOT receive a future-year discount."""
        import datetime
        this_year = datetime.date.today().year
        current_val = _pick_curve_value({"year": this_year, "round": 1})
        no_year_val = _pick_curve_value({"round": 1})
        # Current-year pick should equal a pick with no year (both undiscounted)
        assert current_val == no_year_val

    def test_default_year_uses_today(self):
        """Default current_year should derive from today, not a hard-coded constant."""
        import datetime
        this_year = datetime.date.today().year
        next_year = this_year + 1
        # A pick dated next year should be discounted when using the default
        default_val = _pick_curve_value({"year": next_year, "round": 1})
        explicit_val = _pick_curve_value({"year": next_year, "round": 1}, current_year=this_year)
        assert default_val == explicit_val

    def test_round_ordering(self):
        vals = [_pick_curve_value({"round": r}) for r in range(1, 7)]
        assert vals == sorted(vals, reverse=True)


class TestPickCalibrationWithLegacy:
    def test_direct_legacy_match(self):
        if not LEGACY_PATH.exists():
            pytest.skip("No legacy data")
        assets = [
            {"display_name": "2026 Pick 1.01", "blended_value": 9999,
             "universe": "offense_vet", "source_values": {"KTC": 9999}},
        ]
        result = calibrate_canonical_values(assets, legacy_path=LEGACY_PATH)
        pick = result[0]
        # Should match legacy value (6656 in 2026-03-22 snapshot)
        assert pick["calibrated_value"] == 6656
        assert pick["_pick_calibration_source"] == "legacy_direct"

    def test_round_curve_fallback(self):
        assets = [
            {"display_name": "2030 Early 1st", "blended_value": 5000,
             "universe": "offense_vet", "source_values": {"KTC": 5000}},
        ]
        result = calibrate_canonical_values(assets)
        pick = result[0]
        assert pick["_pick_calibration_source"] == "round_curve"
        # Future year should be discounted
        assert pick["calibrated_value"] < LEGACY_PICK_ROUND_CURVE[1]


class TestNonFantasyCeiling:
    def test_kickers_capped(self):
        from src.canonical.calibration import NON_FANTASY_CEILING
        assets = [
            {"blended_value": 9999, "display_name": "Star QB", "universe": "offense_vet",
             "metadata": {"position": "QB"}, "source_values": {"SRC": 9999}},
            {"blended_value": 8000, "display_name": "Brandon Aubrey", "universe": "offense_vet",
             "metadata": {"position": "K"}, "source_values": {"SRC": 8000}},
        ]
        result = calibrate_canonical_values(assets)
        kicker = [a for a in result if a["display_name"] == "Brandon Aubrey"][0]
        assert kicker["calibrated_value"] <= NON_FANTASY_CEILING


class TestCalibrationDistribution:
    def test_offense_not_top_heavy(self):
        values = list(range(9999, 5000, -12))
        assets = _make_assets("offense_vet", values)
        result = calibrate_canonical_values(assets)

        from collections import Counter
        def tier(v):
            if v >= 7000: return "elite"
            if v >= 5000: return "star"
            if v >= 3000: return "starter"
            if v >= 1500: return "bench"
            return "depth"

        tiers = Counter(tier(a["calibrated_value"]) for a in result)
        elite_pct = tiers["elite"] / len(result) * 100
        assert elite_pct < 20

    def test_idp_has_no_elite(self):
        values = list(range(9999, 5000, -50))
        assets = _make_assets("idp_vet", values)
        result = calibrate_canonical_values(assets)
        for a in result:
            assert a["calibrated_value"] <= UNIVERSE_SCALES["idp_vet"]


class TestCalibrationParams:
    def test_params_structure(self):
        params = get_calibration_params()
        assert "exponent" in params
        assert "universe_scales" in params
        assert "pick_calibration" in params
        assert "pick_round_curve" in params
        assert params["exponent"] == CALIBRATION_EXPONENT

    def test_custom_scales(self):
        assets = _make_assets("offense_vet", [9000, 7000, 5000])
        result = calibrate_canonical_values(
            assets, universe_scales={"offense_vet": 5000}
        )
        top = max(result, key=lambda a: a["calibrated_value"])
        assert top["calibrated_value"] == 5000
