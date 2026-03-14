"""Unit tests for src/identity/matcher.py"""
from __future__ import annotations

import pytest

from src.data_models import RawAssetRecord
from src.identity.matcher import (
    MATCH_QUARANTINE_THRESHOLD,
    _confidence_for_record,
    build_identity_resolution,
    build_master_players,
)


def _make_record(
    name: str = "Josh Allen",
    source: str = "dlf_sf",
    position: str = "QB",
    team: str = "BUF",
    external_id: str = "",
    asset_type: str = "player",
    universe: str = "offense_vet",
    rank: float | None = 1.0,
) -> RawAssetRecord:
    """Factory for test records with sensible defaults."""
    return RawAssetRecord(
        source=source,
        snapshot_id="snap_001",
        asset_type=asset_type,
        external_asset_id=external_id,
        external_name=name,
        display_name=name,
        team_raw=team,
        position_raw=position,
        age_raw="",
        rookie_flag_raw="",
        rank_raw=rank,
        value_raw=None,
        tier_raw="",
        universe=universe,
        format_key="dynasty_sf",
        is_idp=False,
        is_offense=True,
        source_notes="test",
        name_normalized_guess=name.lower().replace("'", ""),
        team_normalized_guess=team.upper(),
        position_normalized_guess=position.upper(),
        asset_key=f"player::{name.lower().replace(chr(39), '')}",
    )


# ── Confidence ladder tests ──────────────────────────────────────────

class TestConfidenceLadder:
    def test_exact_id_gives_1_00(self):
        rec = _make_record(external_id="sleeper_123")
        conf, method = _confidence_for_record(rec)
        assert conf == 1.00
        assert method == "exact_id"

    def test_name_team_position_gives_0_98(self):
        rec = _make_record()
        conf, method = _confidence_for_record(rec)
        assert conf == 0.98
        assert method == "exact_name_team_position"

    def test_name_position_only_gives_0_93(self):
        rec = _make_record(team="")
        conf, method = _confidence_for_record(rec)
        assert conf == 0.93
        assert method == "exact_name_position"

    def test_name_only_gives_0_85(self):
        rec = _make_record(team="", position="")
        rec.position_normalized_guess = ""
        rec.team_normalized_guess = ""
        conf, method = _confidence_for_record(rec)
        assert conf == 0.85
        assert method == "exact_name_only"


# ── Master player building ───────────────────────────────────────────

class TestBuildMasterPlayers:
    def test_single_record_creates_one_player(self):
        records = [_make_record()]
        players, conflicts = build_master_players(records)
        assert len(players) == 1
        assert not conflicts

    def test_same_player_multiple_sources_merges(self):
        rec1 = _make_record(source="dlf_sf")
        rec2 = _make_record(source="ktc")
        players, conflicts = build_master_players([rec1, rec2])
        assert len(players) == 1
        pid = list(players.keys())[0]
        assert len(players[pid].metadata["sources"]) == 2

    def test_different_players_stay_separate(self):
        rec1 = _make_record(name="Josh Allen", position="QB")
        rec2 = _make_record(name="Patrick Mahomes", position="QB")
        rec2.name_normalized_guess = "patrick mahomes"
        rec2.asset_key = "player::patrick mahomes"
        players, _ = build_master_players([rec1, rec2])
        assert len(players) == 2

    def test_position_conflict_detected(self):
        rec1 = _make_record(name="Josh Allen", position="QB")
        rec2 = _make_record(name="Josh Allen", position="LB", source="ktc")
        players, conflicts = build_master_players([rec1, rec2])
        assert len(players) == 1
        assert len(conflicts) == 1
        assert "multiple position families" in conflicts[0]

    def test_picks_ignored(self):
        rec = _make_record(asset_type="pick")
        players, _ = build_master_players([rec])
        assert len(players) == 0


# ── Full identity resolution ─────────────────────────────────────────

class TestBuildIdentityResolution:
    def test_basic_resolution(self):
        records = [
            _make_record(name="Josh Allen"),
            _make_record(name="Patrick Mahomes"),
        ]
        records[1].name_normalized_guess = "patrick mahomes"
        records[1].asset_key = "player::patrick mahomes"

        report = build_identity_resolution(records)
        assert report["master_player_count"] == 2
        assert report["player_alias_count"] == 2
        assert report["unresolved_count"] == 0

    def test_low_confidence_flagged(self):
        rec = _make_record(team="", position="")
        rec.position_normalized_guess = ""
        rec.team_normalized_guess = ""
        report = build_identity_resolution([rec])
        assert report["low_confidence_count"] == 1
        assert report["low_confidence_matches"][0]["match_confidence"] == 0.85

    def test_quarantine_threshold_customizable(self):
        rec = _make_record(team="", position="")
        rec.position_normalized_guess = ""
        rec.team_normalized_guess = ""
        # With a lower threshold, 0.85 should pass
        report = build_identity_resolution([rec], quarantine_threshold=0.80)
        assert report["low_confidence_count"] == 0

    def test_duplicate_aliases_detected(self):
        rec1 = _make_record(name="Josh Allen", external_id="ext_001")
        rec2 = _make_record(name="Joshua Allen", external_id="ext_001")
        rec2.name_normalized_guess = "joshua allen"
        rec2.asset_key = "player::joshua allen"
        report = build_identity_resolution([rec1, rec2])
        assert report["duplicate_alias_count"] == 1

    def test_pick_records_processed(self):
        rec = _make_record(
            name="2026 Early 1st",
            asset_type="pick",
            position="",
            team="",
        )
        rec.name_normalized_guess = "2026 early 1st"
        rec.position_normalized_guess = ""
        rec.team_normalized_guess = ""
        rec.asset_key = "pick::2026::1::EARLY"
        rec.pick_year_guess = 2026
        rec.pick_round_guess = 1
        rec.pick_slot_guess = "EARLY"
        report = build_identity_resolution([rec])
        assert report["pick_count"] == 1

    def test_empty_name_goes_to_unresolved(self):
        rec = _make_record(name="")
        rec.name_normalized_guess = ""
        report = build_identity_resolution([rec])
        assert report["unresolved_count"] == 1

    def test_single_vs_multi_source_tracking(self):
        rec1 = _make_record(name="Josh Allen", source="dlf_sf")
        rec2 = _make_record(name="Josh Allen", source="ktc")
        rec3 = _make_record(name="Patrick Mahomes", source="dlf_sf")
        rec3.name_normalized_guess = "patrick mahomes"
        rec3.asset_key = "player::patrick mahomes"
        report = build_identity_resolution([rec1, rec2, rec3])
        assert report["multi_source_count"] == 1
        assert report["single_source_count"] == 1
