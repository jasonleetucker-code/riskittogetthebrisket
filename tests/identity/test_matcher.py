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


# ── Confidence ladder edge cases ──────────────────────────────────────

class TestConfidenceLadderEdgeCases:
    def test_team_raw_fallback_when_no_normalized(self):
        """If team_normalized_guess is empty but team_raw has value, should still count."""
        rec = _make_record(team="BUF", position="QB")
        rec.team_normalized_guess = ""
        # team_raw = "BUF" should still give has_team=True
        conf, method = _confidence_for_record(rec)
        assert conf == 0.98
        assert method == "exact_name_team_position"

    def test_position_raw_fallback_when_no_normalized(self):
        rec = _make_record(team="", position="")
        rec.team_normalized_guess = ""
        rec.position_normalized_guess = ""
        rec.position_raw = "QB"
        conf, method = _confidence_for_record(rec)
        assert conf == 0.93
        assert method == "exact_name_position"

    def test_whitespace_only_external_id_not_exact(self):
        """Whitespace-only external_id should not count as exact_id."""
        rec = _make_record(external_id="   ")
        conf, method = _confidence_for_record(rec)
        # Whitespace strips to empty, so should NOT be exact_id
        # Current code: str(rec.external_asset_id).strip() → empty → False
        assert method != "exact_id"


# ── Master player building edge cases ─────────────────────────────────

class TestBuildMasterPlayersEdgeCases:
    def test_three_sources_merge_into_one_player(self):
        rec1 = _make_record(source="dlf")
        rec2 = _make_record(source="ktc")
        rec3 = _make_record(source="fantasycalc")
        players, _ = build_master_players([rec1, rec2, rec3])
        assert len(players) == 1
        pid = list(players.keys())[0]
        assert len(players[pid].metadata["sources"]) == 3

    def test_display_name_uses_first_seen(self):
        rec1 = _make_record(name="Josh Allen", source="dlf")
        rec2 = _make_record(name="Josh Allen", source="ktc")
        players, _ = build_master_players([rec1, rec2])
        pid = list(players.keys())[0]
        assert players[pid].display_name == "Josh Allen"

    def test_aliases_track_name_variants(self):
        rec1 = _make_record(name="Josh Allen", source="dlf")
        rec2 = _make_record(name="Joshua Allen", source="ktc")
        rec2.name_normalized_guess = "josh allen"  # Same normalized
        rec2.asset_key = "player::josh allen"
        players, _ = build_master_players([rec1, rec2])
        pid = list(players.keys())[0]
        assert "Josh Allen" in players[pid].aliases
        assert "Joshua Allen" in players[pid].aliases

    def test_empty_display_name_skipped(self):
        rec = _make_record(name="")
        rec.name_normalized_guess = ""
        players, _ = build_master_players([rec])
        assert len(players) == 0


# ── Pick processing edge cases ────────────────────────────────────────

class TestPickProcessingEdgeCases:
    def test_pick_with_numeric_slot(self):
        rec = _make_record(
            name="2026 Pick 1.03",
            asset_type="pick",
            position="",
            team="",
        )
        rec.name_normalized_guess = "2026 pick 1 03"
        rec.position_normalized_guess = ""
        rec.team_normalized_guess = ""
        rec.asset_key = "pick::2026::1::1.03"
        rec.pick_year_guess = 2026
        rec.pick_round_guess = 1
        rec.pick_slot_guess = "1.03"
        report = build_identity_resolution([rec])
        assert report["pick_count"] == 1
        picks = report["picks"]
        assert picks[0]["slot_known"] is True
        assert picks[0]["slot_number"] == 1

    def test_pick_with_tier_bucket_slot(self):
        rec = _make_record(
            name="2027 Mid 2nd",
            asset_type="pick",
            position="",
            team="",
        )
        rec.name_normalized_guess = "2027 mid 2nd"
        rec.position_normalized_guess = ""
        rec.team_normalized_guess = ""
        rec.asset_key = "pick::2027::2::MID"
        rec.pick_year_guess = 2027
        rec.pick_round_guess = 2
        rec.pick_slot_guess = "MID"
        report = build_identity_resolution([rec])
        assert report["pick_count"] == 1
        picks = report["picks"]
        assert picks[0]["slot_known"] is False
        assert picks[0]["bucket"] == "MID"

    def test_pick_without_year_uses_zero(self):
        rec = _make_record(
            name="Unknown Pick",
            asset_type="pick",
            position="",
            team="",
        )
        rec.name_normalized_guess = "unknown pick"
        rec.position_normalized_guess = ""
        rec.team_normalized_guess = ""
        rec.asset_key = "pick::0::0::UNKNOWN"
        rec.pick_year_guess = None
        rec.pick_round_guess = None
        rec.pick_slot_guess = ""
        report = build_identity_resolution([rec])
        assert report["pick_count"] == 1
        assert report["picks"][0]["season"] == 0


# ── Age parsing ───────────────────────────────────────────────────────

class TestAgeParsingInResolution:
    def test_valid_integer_age(self):
        rec = _make_record()
        rec.age_raw = "25"
        report = build_identity_resolution([rec])
        player = report["players"][0]
        assert player["age"] == 25.0

    def test_valid_float_age(self):
        rec = _make_record()
        rec.age_raw = "24.5"
        report = build_identity_resolution([rec])
        player = report["players"][0]
        assert player["age"] == 24.5

    def test_empty_age_is_none(self):
        rec = _make_record()
        rec.age_raw = ""
        report = build_identity_resolution([rec])
        player = report["players"][0]
        assert player["age"] is None

    def test_non_numeric_age_is_none(self):
        rec = _make_record()
        rec.age_raw = "N/A"
        report = build_identity_resolution([rec])
        player = report["players"][0]
        assert player["age"] is None


# ── build_identity_report backward compat ─────────────────────────────

class TestBuildIdentityReport:
    def test_is_alias_for_build_identity_resolution(self):
        from src.identity.matcher import build_identity_report
        records = [_make_record()]
        report = build_identity_report(records)
        assert report["master_player_count"] == 1
        assert "players" in report
