"""Tests for canonical value calibration layer."""

from __future__ import annotations

import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.canonical.calibration import (  # noqa: E402 — must follow the sys.path bootstrap above
    calibrate_canonical_values,
    get_calibration_params,
    UNIVERSE_SCALES,
    CALIBRATION_EXPONENT,
    _is_pick,
)


LEGACY_PATH = REPO / "data" / "legacy_data_2026-03-22.json"


def _make_assets(universe: str, values: list[int], names: list[str] | None = None) -> list[dict]:
    return [
        {
            "blended_value": v,
            "display_name": names[i] if names else f"Player_{i}",
            "universe": universe,
            "source_values": {"SRC": v},
        }
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


class TestRetiredPickPricerRefuses:
    """C1-U6: this layer's own pick pricer (round curve + 0.70**years
    discount + tier adjustment + slot interpolation) is DELETED — it was
    a complete second future-pick valuation owner.  A pick asset passed
    through calibration now comes back explicitly UNPRICED (None with a
    labelled source), never a curve value and never zero."""

    def test_pick_assets_are_refused_not_priced(self):
        assets = [
            {
                "display_name": "2030 Early 1st",
                "blended_value": 5000,
                "universe": "offense_vet",
                "source_values": {"KTC": 5000},
            },
            {
                "display_name": "2026 Pick 1.01",
                "blended_value": 9999,
                "universe": "offense_vet",
                "source_values": {"KTC": 9999},
            },
        ]
        result = calibrate_canonical_values(assets)
        for pick in result:
            assert pick["calibrated_value"] is None
            assert pick["_pick_calibration_source"] == "retired_second_owner_c1u6"

    def test_no_pick_curve_machinery_survives(self):
        import src.canonical.calibration as cal

        for gone in (
            "_pick_curve_value",
            "_parse_pick_info",
            "LEGACY_PICK_ROUND_CURVE",
            "PICK_YEAR_DISCOUNT",
        ):
            assert not hasattr(cal, gone), f"retired pick pricer resurrected: {gone}"


class TestNonFantasyCeiling:
    def test_kickers_capped(self):
        from src.canonical.calibration import NON_FANTASY_CEILING

        assets = [
            {
                "blended_value": 9999,
                "display_name": "Star QB",
                "universe": "offense_vet",
                "metadata": {"position": "QB"},
                "source_values": {"SRC": 9999},
            },
            {
                "blended_value": 8000,
                "display_name": "Brandon Aubrey",
                "universe": "offense_vet",
                "metadata": {"position": "K"},
                "source_values": {"SRC": 8000},
            },
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
            if v >= 7000:
                return "elite"
            if v >= 5000:
                return "star"
            if v >= 3000:
                return "starter"
            if v >= 1500:
                return "bench"
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
        # The retired second owner's curve must not reappear in params.
        assert "pick_round_curve" not in params
        assert "pick_year_discount" not in params
        assert params["exponent"] == CALIBRATION_EXPONENT

    def test_custom_scales(self):
        assets = _make_assets("offense_vet", [9000, 7000, 5000])
        result = calibrate_canonical_values(assets, universe_scales={"offense_vet": 5000})
        top = max(result, key=lambda a: a["calibrated_value"])
        assert top["calibrated_value"] == 5000
