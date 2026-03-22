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

    def test_players(self):
        assert _is_pick_asset("Patrick Mahomes") is False
        assert _is_pick_asset("T.J. Watt") is False
        assert _is_pick_asset("Bijan Robinson") is False


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
        assert result[1]["metadata"]["position"] == "DL"
        assert summary["enriched_from_legacy"] == 2

    def test_preserves_existing_position(self):
        lookup = {"patrick mahomes": "QB"}
        assets = [
            {"display_name": "Patrick Mahomes", "metadata": {"position": "QB"}, "blended_value": 9000},
        ]
        result, summary = enrich_positions(assets, lookup)
        assert result[0]["metadata"]["position_source"] == "adapter"
        assert summary["already_had_position"] == 1
        assert summary["enriched_from_legacy"] == 0

    def test_skips_picks(self):
        lookup = {}
        assets = [
            {"display_name": "2026 Pick 1.01", "metadata": {}, "blended_value": 5000},
            {"display_name": "Early 1st", "metadata": {}, "blended_value": 4000},
        ]
        result, summary = enrich_positions(assets, lookup)
        assert summary["skipped_picks"] == 2
        assert result[0]["metadata"].get("position") is None

    def test_unmatched_tracked(self):
        lookup = {}
        assets = [
            {"display_name": "Unknown Player", "metadata": {}, "blended_value": 1000},
        ]
        result, summary = enrich_positions(assets, lookup)
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

        # Strip existing position data to simulate un-enriched state
        for a in assets:
            meta = a.get("metadata", {})
            if meta.get("position_source") == "legacy_enrichment":
                meta.pop("position", None)
                meta.pop("position_source", None)

        _, summary = enrich_positions(assets, lookup)

        # Should meaningfully improve coverage
        assert summary["enriched_from_legacy"] > 200
        assert summary["position_coverage_pct"] > 60
