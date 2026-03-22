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
)


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


class TestPickCeiling:
    def test_picks_capped(self):
        assets = _make_assets(
            "offense_vet", [9999, 9500, 9000],
            names=["2026 Pick 1.01", "2026 Early 1st", "Real Player"]
        )
        result = calibrate_canonical_values(assets)
        pick1 = [a for a in result if "Pick 1.01" in a["display_name"]][0]
        player = [a for a in result if "Real Player" in a["display_name"]][0]

        assert pick1["calibrated_value"] <= PICK_CEILING
        # The player should not be capped
        assert player["calibrated_value"] > 0

    def test_is_pick_detection(self):
        assert _is_pick({"display_name": "2026 Pick 1.01"}) is True
        assert _is_pick({"display_name": "2026 Early 1st"}) is True
        assert _is_pick({"display_name": "Early 1st"}) is True
        assert _is_pick({"display_name": "2027 Mid 2nd"}) is True
        assert _is_pick({"display_name": "2026 1st"}) is True
        assert _is_pick({"display_name": "2027 2nd"}) is True
        assert _is_pick({"display_name": "Patrick Mahomes"}) is False
        assert _is_pick({"display_name": "T.J. Watt"}) is False


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
        """IDP scale of 5000 means no one reaches elite tier (>=7000)."""
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
        assert "pick_ceiling" in params
        assert params["exponent"] == CALIBRATION_EXPONENT

    def test_custom_scales(self):
        assets = _make_assets("offense_vet", [9000, 7000, 5000])
        result = calibrate_canonical_values(
            assets, universe_scales={"offense_vet": 5000}
        )
        top = max(result, key=lambda a: a["calibrated_value"])
        assert top["calibrated_value"] == 5000
