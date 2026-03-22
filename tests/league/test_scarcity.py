"""Tests for scarcity adjustment layer."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.league.settings import LeagueSettings
from src.league.replacement import ReplacementCalculator, PositionBaseline
from src.league.scarcity import compute_scarcity_adjusted_values, build_scarcity_summary

LEAGUE_CONFIG = REPO / "config" / "leagues" / "default_superflex_idp.template.json"


@pytest.fixture
def settings():
    return LeagueSettings.from_json(LEAGUE_CONFIG)


@pytest.fixture
def calc(settings):
    return ReplacementCalculator(settings)


def _make_assets(position: str, values: list[int]) -> list[dict]:
    return [
        {"blended_value": v, "display_name": f"Player_{position}_{i}",
         "metadata": {"position": position}, "universe": "offense_vet",
         "source_values": {"SRC": v}}
        for i, v in enumerate(values)
    ]


class TestScarcityAdjustment:
    def test_above_replacement_gets_positive_var(self, calc):
        assets = _make_assets("QB", [9000, 8000, 7000, 5000, 3000])
        baselines = calc.compute_baselines(assets)
        enriched = compute_scarcity_adjusted_values(assets, baselines)

        # Top QB should have positive VAR
        top = enriched[0]
        assert top["var_raw"] is not None
        assert top["var_raw"] > 0
        assert top["scarcity_adjusted_value"] > 0

    def test_below_replacement_gets_floor(self, calc):
        # Create a pool with many players so the replacement baseline is high
        values = list(range(9000, 3000, -100))  # 60 players
        assets = _make_assets("QB", values)
        baselines = calc.compute_baselines(assets)
        enriched = compute_scarcity_adjusted_values(assets, baselines)

        # Last player (value=3100) should be at or below replacement
        bottom = sorted(enriched, key=lambda a: a["blended_value"])[0]
        assert bottom["var_raw"] == 0 or bottom["scarcity_adjusted_value"] <= 100

    def test_ordering_preserved(self, calc):
        assets = _make_assets("QB", [9000, 7000, 5000, 3000])
        baselines = calc.compute_baselines(assets)
        enriched = compute_scarcity_adjusted_values(assets, baselines)

        adjusted_vals = [e["scarcity_adjusted_value"] for e in enriched]
        assert adjusted_vals == sorted(adjusted_vals, reverse=True)

    def test_no_position_uses_raw_value(self, calc):
        assets = [
            {"blended_value": 8000, "display_name": "Unknown Player",
             "metadata": {}, "universe": "offense_vet", "source_values": {"SRC": 8000}}
        ]
        baselines = calc.compute_baselines(assets)
        enriched = compute_scarcity_adjusted_values(assets, baselines)

        assert enriched[0]["scarcity_adjusted_value"] == 8000
        assert enriched[0]["var_raw"] is None

    def test_var_raw_is_value_minus_baseline(self, calc):
        assets = _make_assets("QB", [9000, 8000, 7000])
        baselines = calc.compute_baselines(assets)
        enriched = compute_scarcity_adjusted_values(assets, baselines)

        for e in enriched:
            if e["var_raw"] is not None and e["replacement_baseline"] is not None:
                expected_var = max(0, e["blended_value"] - e["replacement_baseline"])
                assert e["var_raw"] == expected_var

    def test_summary_structure(self, calc):
        assets = _make_assets("QB", [9000, 7000]) + _make_assets("WR", [8000, 6000])
        baselines = calc.compute_baselines(assets)
        enriched = compute_scarcity_adjusted_values(assets, baselines)
        summary = build_scarcity_summary(enriched, baselines)

        assert "total_assets" in summary
        assert "with_position" in summary
        assert "positions" in summary
        assert summary["total_assets"] == 4
        assert summary["with_position"] == 4


class TestScarcityWithRealData:
    def test_real_canonical_snapshot(self, calc):
        snap_dir = REPO / "data" / "canonical"
        snaps = sorted(snap_dir.glob("canonical_snapshot_*.json"), reverse=True)
        if not snaps:
            pytest.skip("No canonical snapshot")

        snap = json.loads(snaps[0].read_text())
        assets = snap.get("assets", [])
        baselines = calc.compute_baselines(assets)
        enriched = compute_scarcity_adjusted_values(assets, baselines)

        # Should have some adjusted values
        with_var = [e for e in enriched if e.get("var_raw") is not None]
        assert len(with_var) > 100

        # Adjusted values should span a reasonable range
        adjusted = [e["scarcity_adjusted_value"] for e in with_var]
        assert max(adjusted) == 9999 or max(adjusted) > 8000
        assert min(adjusted) < 500

        summary = build_scarcity_summary(enriched, baselines)
        assert summary["with_position"] > 0
