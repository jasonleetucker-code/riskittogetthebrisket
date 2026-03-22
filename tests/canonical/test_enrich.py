"""Tests for position enrichment from legacy player data."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.canonical.enrich import (
    build_legacy_position_lookup,
    enrich_positions,
    _normalize_name,
    _is_pick_asset,
    _nickname_variants,
    _is_idp_asset,
    LEGACY_POS_MAP,
)


LEGACY_PATH = REPO / "data" / "legacy_data_2026-03-10.json"


class TestNormalizeName:
    def test_basic(self):
        assert _normalize_name("Patrick Mahomes") == "patrick mahomes"

    def test_strips_jr(self):
        assert _normalize_name("Marvin Harrison Jr.") == "marvin harrison"

    def test_strips_dots_and_apostrophes(self):
        assert _normalize_name("A.J. Brown") == "aj brown"
        assert _normalize_name("Ja'Marr Chase") == "jamarr chase"

    def test_strips_suffix_ii(self):
        assert _normalize_name("Mark Andrews II") == "mark andrews"


class TestIsPickAsset:
    def test_picks(self):
        assert _is_pick_asset("2026 Pick 1.01") is True
        assert _is_pick_asset("2026 Early 1st") is True
        assert _is_pick_asset("Early 1st") is True
        assert _is_pick_asset("2027 Mid 2nd") is True
        assert _is_pick_asset("2026 1st") is True

    def test_players(self):
        assert _is_pick_asset("Patrick Mahomes") is False
        assert _is_pick_asset("T.J. Watt") is False
        assert _is_pick_asset("Bijan Robinson") is False


class TestNicknameVariants:
    def test_cam_to_cameron(self):
        variants = _nickname_variants("cam skattebo")
        assert "cameron skattebo" in variants

    def test_tj_expansion(self):
        variants = _nickname_variants("tj watt")
        assert "t j watt" in variants

    def test_formal_to_nickname(self):
        variants = _nickname_variants("cameron ward")
        assert "cam ward" in variants

    def test_dr_suffix_removal(self):
        variants = _nickname_variants("gervon dexter dr")
        assert "gervon dexter" in variants

    def test_short_name_no_variants(self):
        assert _nickname_variants("mahomes") == []


class TestIsIdpAsset:
    def test_idp_universe(self):
        assert _is_idp_asset({"universe": "idp_vet", "source_values": {}}) is True
        assert _is_idp_asset({"universe": "idp_rookie", "source_values": {}}) is True

    def test_idp_only_sources(self):
        assert _is_idp_asset({"universe": "offense_vet", "source_values": {"IDPTRADECALC": 100}}) is True
        assert _is_idp_asset({"universe": "offense_vet", "source_values": {"PFF_IDP": 50}}) is True

    def test_not_idp(self):
        assert _is_idp_asset({"universe": "offense_vet", "source_values": {"KTC": 100}}) is False


class TestBuildLegacyLookup:
    @pytest.fixture
    def lookup(self):
        if not LEGACY_PATH.exists():
            pytest.skip("No legacy data file")
        return build_legacy_position_lookup(LEGACY_PATH)

    def test_has_entries(self, lookup):
        assert len(lookup) > 500

    def test_known_players(self, lookup):
        assert lookup.get("patrick mahomes") == "QB"
        assert lookup.get("bijan robinson") == "RB"

    def test_no_picks(self, lookup):
        for name, pos in lookup.items():
            assert pos != "PICK", f"Found PICK for {name}"


class TestEnrichPositions:
    def test_enriches_missing_positions(self):
        lookup = {"patrick mahomes": "QB", "tj watt": "DL"}
        assets = [
            {"display_name": "Patrick Mahomes", "metadata": {}, "blended_value": 9000},
            {"display_name": "T.J. Watt", "metadata": {}, "blended_value": 8000},
        ]
        result, summary = enrich_positions(assets, lookup)
        assert result[0]["metadata"]["position"] == "QB"
        assert result[0]["metadata"]["position_source"] == "legacy_enrichment"
        assert summary["enriched_from_legacy"] == 2

    def test_preserves_existing_position(self):
        lookup = {"patrick mahomes": "QB"}
        assets = [
            {"display_name": "Patrick Mahomes", "metadata": {"position": "QB"}, "blended_value": 9000},
        ]
        result, summary = enrich_positions(assets, lookup)
        assert result[0]["metadata"]["position_source"] == "adapter"
        assert summary["already_had_position"] == 1

    def test_skips_picks(self):
        lookup = {}
        assets = [
            {"display_name": "2026 Pick 1.01", "metadata": {}, "blended_value": 5000},
            {"display_name": "Early 1st", "metadata": {}, "blended_value": 4000},
            {"display_name": "2026 1st", "metadata": {}, "blended_value": 3000},
        ]
        result, summary = enrich_positions(assets, lookup)
        assert summary["skipped_picks"] == 3

    def test_nickname_matching(self):
        lookup = {"cameron skattebo": "RB"}
        assets = [
            {"display_name": "Cam Skattebo", "metadata": {}, "blended_value": 7000},
        ]
        result, summary = enrich_positions(assets, lookup)
        assert result[0]["metadata"]["position"] == "RB"
        assert result[0]["metadata"]["position_source"] == "nickname_match"
        assert summary["enriched_from_nickname"] == 1

    def test_idp_universe_inference(self):
        lookup = {}
        assets = [
            {"display_name": "Unknown IDP Player", "metadata": {},
             "universe": "idp_vet", "source_values": {"IDPTRADECALC": 100},
             "blended_value": 5000},
        ]
        result, summary = enrich_positions(assets, lookup, infer_idp=True)
        assert result[0]["metadata"]["position"] == "LB"
        assert result[0]["metadata"]["position_source"] == "universe_inferred"
        assert summary["enriched_from_universe_infer"] == 1

    def test_idp_inference_disabled(self):
        lookup = {}
        assets = [
            {"display_name": "Unknown IDP Player", "metadata": {},
             "universe": "idp_vet", "source_values": {"IDPTRADECALC": 100},
             "blended_value": 5000},
        ]
        result, summary = enrich_positions(assets, lookup, infer_idp=False)
        assert result[0]["metadata"].get("position") is None
        assert summary["unmatched"] == 1

    def test_coverage_pct(self):
        lookup = {"a": "QB"}
        assets = [
            {"display_name": "A", "metadata": {}, "blended_value": 9000},
            {"display_name": "B", "metadata": {}, "blended_value": 8000},
        ]
        _, summary = enrich_positions(assets, lookup)
        assert summary["position_coverage_pct"] == 50.0


class TestEnrichWithRealData:
    def test_real_enrichment(self):
        if not LEGACY_PATH.exists():
            pytest.skip("No legacy data file")
        snap_dir = REPO / "data" / "canonical"
        snaps = sorted(snap_dir.glob("canonical_snapshot_*.json"), reverse=True)
        if not snaps:
            pytest.skip("No canonical snapshot")

        lookup = build_legacy_position_lookup(LEGACY_PATH)
        snap = json.loads(snaps[0].read_text())
        assets = snap.get("assets", [])

        # Strip existing enriched position data to simulate un-enriched state
        for a in assets:
            meta = a.get("metadata", {})
            if meta.get("position_source") in ("legacy_enrichment", "nickname_match", "universe_inferred"):
                meta.pop("position", None)
                meta.pop("position_source", None)

        _, summary = enrich_positions(assets, lookup, infer_idp=True)

        # Should meaningfully improve coverage
        assert summary["enriched_from_legacy"] > 200
        assert summary["position_coverage_pct"] > 75
