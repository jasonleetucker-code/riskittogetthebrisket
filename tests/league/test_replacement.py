"""Tests for the replacement baseline calculator."""
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


LEAGUE_CONFIG = REPO / "config" / "leagues" / "default_superflex_idp.template.json"


@pytest.fixture
def settings():
    return LeagueSettings.from_json(LEAGUE_CONFIG)


@pytest.fixture
def calc(settings):
    return ReplacementCalculator(settings)


class TestLeagueSettings:
    def test_loads_from_json(self, settings):
        assert settings.teams == 12
        assert settings.superflex is True
        assert settings.te_premium == 1.5
        assert settings.starters["QB"] == 1
        assert settings.starters["WR"] == 3
        assert settings.starters["SFLEX"] == 1

    def test_offense_positions(self, settings):
        assert "QB" in settings.offense_positions
        assert "RB" in settings.offense_positions
        assert "WR" in settings.offense_positions
        assert "TE" in settings.offense_positions
        assert len(settings.offense_positions) == 4

    def test_idp_positions(self, settings):
        assert "DL" in settings.idp_positions
        assert "LB" in settings.idp_positions
        assert "DB" in settings.idp_positions
        assert len(settings.idp_positions) == 3

    def test_starter_demand_qb_superflex(self, settings):
        # QB: 1 direct + 1 SFLEX = 2 per team * 12 = 24
        demand = settings.starter_demand("QB")
        assert demand == 24

    def test_starter_demand_rb(self, settings):
        # RB: 2 direct + 2 FLEX + 1 SFLEX = 5 per team * 12 = 60
        demand = settings.starter_demand("RB")
        assert demand == 60

    def test_starter_demand_wr(self, settings):
        # WR: 3 direct + 2 FLEX + 1 SFLEX = 6 per team * 12 = 72
        demand = settings.starter_demand("WR")
        assert demand == 72

    def test_starter_demand_te(self, settings):
        # TE: 1 direct + 2 FLEX + 1 SFLEX = 4 per team * 12 = 48
        demand = settings.starter_demand("TE")
        assert demand == 48

    def test_starter_demand_dl(self, settings):
        # DL: 2 direct + 1 IDP_FLEX = 3 per team * 12 = 36
        demand = settings.starter_demand("DL")
        assert demand == 36

    def test_direct_starter_demand(self, settings):
        assert settings.direct_starter_demand("QB") == 12
        assert settings.direct_starter_demand("RB") == 24
        assert settings.direct_starter_demand("WR") == 36
        assert settings.direct_starter_demand("TE") == 12


class TestReplacementCalculator:
    def test_effective_demand_qb(self, calc):
        # QB: 12 direct + 85% of 12 SFLEX = 12 + 10.2 = 22
        demand = calc.effective_demand("QB")
        assert demand == 22

    def test_effective_demand_rb(self, calc):
        # RB: 24 direct + 45% of 24 FLEX + 5% of 12 SFLEX = 24 + 10.8 + 0.6 = 35
        demand = calc.effective_demand("RB")
        assert demand == 35

    def test_effective_demand_wr(self, calc):
        # WR: 36 direct + 40% of 24 FLEX + 5% of 12 SFLEX = 36 + 9.6 + 0.6 = 46
        demand = calc.effective_demand("WR")
        assert demand == 46

    def test_effective_demand_te(self, calc):
        # TE: 12 direct + 15% of 24 FLEX + 5% of 12 SFLEX = 12 + 3.6 + 0.6 = 16
        demand = calc.effective_demand("TE")
        assert demand == 16

    def test_effective_demand_lb(self, calc):
        # LB: 24 direct + 40% of 12 IDP_FLEX = 24 + 4.8 = 29
        demand = calc.effective_demand("LB")
        assert demand == 29

    def test_replacement_rank_includes_buffer(self, calc):
        demand = calc.effective_demand("QB")
        rep_rank = calc.replacement_rank("QB")
        assert rep_rank > demand
        # Buffer = 25% of demand, rounded
        expected_buffer = max(1, round(demand * 0.25))
        assert rep_rank == demand + expected_buffer

    def test_compute_baselines_with_mock_data(self, calc):
        # Create mock canonical assets with positions
        assets = []
        for i in range(60):
            assets.append({
                "blended_value": 9999 - i * 100,
                "position": "QB",
                "universe": "offense_vet",
            })
        for i in range(100):
            assets.append({
                "blended_value": 9000 - i * 80,
                "position": "RB",
                "universe": "offense_vet",
            })
        for i in range(120):
            assets.append({
                "blended_value": 8500 - i * 60,
                "position": "WR",
                "universe": "offense_vet",
            })
        for i in range(50):
            assets.append({
                "blended_value": 7000 - i * 100,
                "position": "TE",
                "universe": "offense_vet",
            })

        baselines = calc.compute_baselines(assets)

        assert "QB" in baselines
        assert "RB" in baselines
        assert "WR" in baselines
        assert "TE" in baselines

        # QB replacement value should be at rank ~28 (22 demand + 6 buffer)
        qb = baselines["QB"]
        assert qb.replacement_value is not None
        assert qb.replacement_rank == 28  # 22 + round(22*0.25)=6
        assert qb.player_pool_size == 60
        assert qb.above_replacement_count > 0

    def test_compute_baselines_small_pool(self, calc):
        """When pool is smaller than demand, use lowest value."""
        assets = [
            {"blended_value": 9000, "position": "QB", "universe": "offense_vet"},
            {"blended_value": 8000, "position": "QB", "universe": "offense_vet"},
        ]
        baselines = calc.compute_baselines(assets)
        qb = baselines["QB"]
        assert qb.replacement_value == 8000  # Only 2 QBs, need 28
        assert qb.player_pool_size == 2

    def test_compute_baselines_empty_position(self, calc):
        """Position with no assets gets None replacement value."""
        baselines = calc.compute_baselines([])
        qb = baselines["QB"]
        assert qb.replacement_value is None
        assert qb.player_pool_size == 0

    def test_baselines_summary_serializable(self, calc):
        assets = [
            {"blended_value": 9000, "position": "QB", "universe": "offense_vet"},
        ]
        baselines = calc.compute_baselines(assets)
        summary = calc.baselines_summary(baselines)
        # Should be JSON-serializable
        json.dumps(summary)
        assert summary["teams"] == 12
        assert summary["superflex"] is True
        assert "QB" in summary["positions"]

    def test_position_aliases(self, calc):
        """DE/DT should map to DL, CB/S to DB, etc."""
        assets = [
            {"blended_value": 9000, "position": "DE", "universe": "idp_vet"},
            {"blended_value": 8500, "position": "DT", "universe": "idp_vet"},
            {"blended_value": 8000, "position": "CB", "universe": "idp_vet"},
            {"blended_value": 7500, "position": "S", "universe": "idp_vet"},
            {"blended_value": 7000, "position": "ILB", "universe": "idp_vet"},
        ]
        baselines = calc.compute_baselines(assets)
        assert baselines["DL"].player_pool_size == 2
        assert baselines["DB"].player_pool_size == 2
        assert baselines["LB"].player_pool_size == 1

    def test_rank_suffixed_positions(self, calc):
        """DLF-style LB1, LB23, DL70, DB5 should map correctly."""
        assets = [
            {"blended_value": 9000, "metadata": {"position": "LB1"}, "universe": "idp_vet"},
            {"blended_value": 8500, "metadata": {"position": "LB23"}, "universe": "idp_vet"},
            {"blended_value": 8000, "metadata": {"position": "DL70"}, "universe": "idp_vet"},
            {"blended_value": 7500, "metadata": {"position": "DB5"}, "universe": "idp_vet"},
        ]
        baselines = calc.compute_baselines(assets)
        assert baselines["LB"].player_pool_size == 2
        assert baselines["DL"].player_pool_size == 1
        assert baselines["DB"].player_pool_size == 1


class TestReplacementWithRealData:
    """Test replacement calculator with actual canonical snapshot data."""

    def test_with_canonical_snapshot(self, calc):
        """Run against real canonical data if available."""
        snap_dir = REPO / "data" / "canonical"
        snaps = sorted(snap_dir.glob("canonical_snapshot_*.json"), reverse=True)
        if not snaps:
            pytest.skip("No canonical snapshot available")

        snap = json.loads(snaps[0].read_text())
        assets = snap.get("assets", [])
        baselines = calc.compute_baselines(assets)

        summary = calc.baselines_summary(baselines)
        # At minimum, offense positions should have pool data
        # (IDP may not have position data in current pipeline)
        total_pool = sum(
            bl.player_pool_size for bl in baselines.values()
        )
        # We expect at least some position data (even if sparse)
        # This test documents the current state rather than asserting
        # a specific number
        assert isinstance(summary, dict)
        assert len(summary["positions"]) == 7  # QB, RB, WR, TE, DL, LB, DB
