"""Integration tests: canonical pipeline → snapshot → shadow comparison.

These tests run the real canonical pipeline against DLF seed CSVs and
validate that the produced snapshot loads correctly into the shadow
comparison block used by server.py.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.adapters import DlfCsvAdapter
from src.api.data_contract import (
    build_api_data_contract,
    build_api_startup_payload,
    build_canonical_comparison_block,
    validate_api_data_contract,
)
from src.canonical.pipeline import write_canonical_snapshot
from src.canonical.transform import CANONICAL_SCALE
from src.data_models import RawAssetRecord

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _load_dlf_records() -> list[RawAssetRecord]:
    """Load real DLF seed CSV records using the production adapter."""
    sources = [
        ("DLF_SF", "offense_vet", "dlf_superflex.csv"),
        ("DLF_IDP", "idp_vet", "dlf_idp.csv"),
        ("DLF_RSF", "offense_rookie", "dlf_rookie_superflex.csv"),
        ("DLF_RIDP", "idp_rookie", "dlf_rookie_idp.csv"),
    ]
    records: list[RawAssetRecord] = []
    for source_id, universe, filename in sources:
        csv_path = REPO_ROOT / filename
        if not csv_path.exists():
            continue
        adapter = DlfCsvAdapter(source_id=source_id, source_bucket=universe)
        result = adapter.load(csv_path)
        for rec in result.records:
            rec.source = source_id
            rec.snapshot_id = "test_snap"
            records.append(rec)
    return records


@pytest.fixture(scope="module")
def dlf_records():
    records = _load_dlf_records()
    if not records:
        pytest.skip("DLF seed CSVs not available")
    return records


@pytest.fixture(scope="module")
def canonical_snapshot(dlf_records, tmp_path_factory):
    """Build a canonical snapshot from real DLF data."""
    tmp = tmp_path_factory.mktemp("canonical")
    out_path = tmp / "canonical_snapshot_test.json"
    weights = {"DLF_SF": 1.0, "DLF_IDP": 1.0, "DLF_RSF": 1.0, "DLF_RIDP": 1.0}
    payload = write_canonical_snapshot(
        out_path=out_path,
        run_id="integration-test-001",
        source_snapshot_id="test_snap",
        records=dlf_records,
        source_weights=weights,
    )
    return payload


class TestSnapshotProduction:
    def test_snapshot_has_assets(self, canonical_snapshot):
        assert canonical_snapshot["asset_count"] > 0

    def test_snapshot_has_required_keys(self, canonical_snapshot):
        required = {"run_id", "source_snapshot_id", "asset_count", "assets", "assets_by_universe"}
        assert required.issubset(set(canonical_snapshot.keys()))

    def test_snapshot_covers_all_universes(self, canonical_snapshot):
        universes = set(canonical_snapshot.get("asset_count_by_universe", {}).keys())
        assert "offense_vet" in universes
        assert "idp_vet" in universes

    def test_asset_format_matches_comparison_contract(self, canonical_snapshot):
        """Each asset must have the fields that build_canonical_comparison_block reads."""
        for asset in canonical_snapshot["assets"][:10]:
            assert "display_name" in asset
            assert "blended_value" in asset
            assert "universe" in asset
            assert "source_values" in asset
            assert isinstance(asset["source_values"], dict)

    def test_values_within_canonical_scale(self, canonical_snapshot):
        for asset in canonical_snapshot["assets"]:
            assert 0 <= asset["blended_value"] <= CANONICAL_SCALE

    def test_top_ranked_player_gets_max_score(self, canonical_snapshot):
        # Rank 1 in any universe should get CANONICAL_SCALE
        max_val = max(a["blended_value"] for a in canonical_snapshot["assets"])
        assert max_val == CANONICAL_SCALE


class TestSnapshotToComparisonBlock:
    def test_comparison_block_loads_from_snapshot(self, canonical_snapshot):
        block = build_canonical_comparison_block(canonical_snapshot)
        assert block["mode"] == "shadow"
        assert block["assetCount"] > 0
        assert block["snapshotRunId"] == "integration-test-001"

    def test_source_breakdown_present(self, canonical_snapshot):
        """Pipeline-produced snapshots have source_values → sourceBreakdown."""
        block = build_canonical_comparison_block(canonical_snapshot)
        # Find an asset with sourceBreakdown
        has_breakdown = [a for a in block["assets"].values() if "sourceBreakdown" in a]
        assert len(has_breakdown) > 0

    def test_delta_computation_with_mock_legacy(self, canonical_snapshot):
        """Delta computation works with the real snapshot format."""
        # Pick a real player from the snapshot
        first_asset = canonical_snapshot["assets"][0]
        player_name = first_asset["display_name"]
        canonical_val = first_asset["blended_value"]

        legacy_players = {player_name: {"_finalAdjusted": 5000}}
        block = build_canonical_comparison_block(
            canonical_snapshot,
            legacy_players=legacy_players,
        )
        entry = block["assets"].get(player_name, {})
        assert entry.get("legacyValue") == 5000
        assert entry.get("delta") == canonical_val - 5000

    def test_summary_statistics_populated(self, canonical_snapshot):
        legacy_players = {"Josh Allen": {"_finalAdjusted": 8500}}
        block = build_canonical_comparison_block(
            canonical_snapshot,
            legacy_players=legacy_players,
        )
        summary = block["summary"]
        assert summary["matchedToLegacy"] >= 1
        assert "avgAbsDelta" in summary

    def test_contract_validates_with_real_snapshot(self, canonical_snapshot):
        """The real snapshot produces a comparison block that passes contract validation."""
        payload = build_api_data_contract({
            "players": {"Josh Allen": {"_composite": 8500, "_rawComposite": 8500, "_finalAdjusted": 8500}},
            "sites": [{"key": "dlf"}],
            "maxValues": {"dlf": 9999},
            "sleeper": {"positions": {"Josh Allen": "QB"}},
        })
        payload["canonicalComparison"] = build_canonical_comparison_block(canonical_snapshot)
        report = validate_api_data_contract(payload)
        assert report["ok"], f"Errors: {report['errors']}"

    def test_startup_view_strips_comparison(self, canonical_snapshot):
        payload = build_api_data_contract({
            "players": {"Josh Allen": {"_composite": 8500, "_rawComposite": 8500, "_finalAdjusted": 8500}},
            "sites": [{"key": "dlf"}],
            "maxValues": {"dlf": 9999},
            "sleeper": {"positions": {"Josh Allen": "QB"}},
        })
        payload["canonicalComparison"] = build_canonical_comparison_block(canonical_snapshot)
        startup = build_api_startup_payload(payload)
        assert "canonicalComparison" not in startup


class TestServerSnapshotLoadingContract:
    """Tests that match server.py's _load_canonical_snapshot() expectations."""

    def test_snapshot_file_glob_pattern(self, canonical_snapshot, tmp_path):
        """server.py globs for 'canonical_snapshot_*.json' — verify our file matches."""
        out = tmp_path / "canonical_snapshot_test123.json"
        with out.open("w") as f:
            json.dump(canonical_snapshot, f)
        matches = list(tmp_path.glob("canonical_snapshot_*.json"))
        assert len(matches) == 1

    def test_snapshot_json_round_trips(self, canonical_snapshot, tmp_path):
        """Snapshot survives JSON serialization (server loads via json.load)."""
        out = tmp_path / "snap.json"
        with out.open("w") as f:
            json.dump(canonical_snapshot, f)
        with out.open("r") as f:
            reloaded = json.load(f)
        assert reloaded["asset_count"] == canonical_snapshot["asset_count"]
        assert len(reloaded["assets"]) == len(canonical_snapshot["assets"])
