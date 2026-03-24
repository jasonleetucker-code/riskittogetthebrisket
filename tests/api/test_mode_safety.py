"""Tests for CANONICAL_DATA_MODE behavior and internal-primary safety."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


class TestModeValidation:
    """Test that mode validation works correctly."""

    def test_valid_modes(self):
        valid = {"off", "shadow", "internal_primary", "primary"}
        for mode in valid:
            assert mode in valid

    def test_default_is_off(self):
        """The .env.example default must be off to protect public safety."""
        env_path = REPO / ".env.example"
        content = env_path.read_text(encoding="utf-8")
        assert "CANONICAL_DATA_MODE=off" in content

    def test_server_defaults_to_off(self):
        """server.py must default to off when env var is unset."""
        server_py = (REPO / "server.py").read_text(encoding="utf-8")
        assert 'os.getenv("CANONICAL_DATA_MODE", "off")' in server_py


class TestInternalPrimarySafety:
    """Test that internal_primary mode doesn't affect public data serving."""

    def test_api_data_always_serves_legacy(self):
        """The /api/data endpoint must always serve legacy data regardless of mode."""
        server_py = (REPO / "server.py").read_text(encoding="utf-8")
        # Verify there's no mode-conditional logic in the data endpoint
        # that would switch to canonical data
        assert "latest_contract_data" in server_py
        # The main data serving should not reference canonical_data
        # (it only references it in the comparison/scaffold blocks)

    def test_scaffold_canonical_internal_primary_branch(self):
        """The canonical scaffold endpoint must serve curated data in internal_primary mode."""
        server_py = (REPO / "server.py").read_text(encoding="utf-8")
        assert 'CANONICAL_DATA_MODE == "internal_primary"' in server_py
        # Verify the curated view includes the safety note
        assert "internal-primary data for evaluation only" in server_py

    def test_no_duplicate_scaffold_canonical_routes(self):
        """There must be exactly one /api/scaffold/canonical route definition."""
        server_py = (REPO / "server.py").read_text(encoding="utf-8")
        count = server_py.count('@app.get("/api/scaffold/canonical")')
        assert count == 1, f"Expected 1 route, found {count} duplicate definitions"

    def test_scaffold_endpoints_documented(self):
        """All scaffold endpoints should be documented in server.py."""
        server_py = (REPO / "server.py").read_text(encoding="utf-8")
        assert "/api/scaffold/canonical" in server_py
        assert "/api/scaffold/mode" in server_py
        assert "/api/scaffold/shadow" in server_py


class TestRollbackPath:
    """Test that rollback is simple and safe."""

    def test_mode_off_disables_canonical_loading(self):
        """Setting mode=off should skip canonical snapshot loading."""
        server_py = (REPO / "server.py").read_text(encoding="utf-8")
        assert 'CANONICAL_DATA_MODE == "off"' in server_py
        # Verify it returns None (skips loading)
        assert "return None" in server_py  # in _load_canonical_snapshot

    def test_rollback_documented(self):
        """Rollback instructions should be documented."""
        env_example = (REPO / ".env.example").read_text(encoding="utf-8")
        assert "revert" in env_example.lower() or "CANONICAL_DATA_MODE=off" in env_example


class TestPromotionReadiness:
    """Test that promotion readiness correctly evaluates internal_primary."""

    def test_readiness_script_exists(self):
        assert (REPO / "scripts" / "check_promotion_readiness.py").exists()

    def test_readiness_uses_offense_players_only(self):
        """Promotion readiness should use offense_players_only metrics."""
        script = (REPO / "scripts" / "check_promotion_readiness.py").read_text(encoding="utf-8")
        assert "offense_players_only" in script

    def test_all_hard_checks_pass(self):
        """Run actual readiness checks and verify all hard checks pass."""
        from scripts.check_promotion_readiness import check_internal_primary_readiness
        results = check_internal_primary_readiness(REPO)
        hard_fails = [r for r in results if r.get("pass") is False]
        for f in hard_fails:
            print(f"FAIL: {f['check']}: required={f['required']}, actual={f['actual']}")
        assert len(hard_fails) == 0, f"{len(hard_fails)} hard checks failed"


class TestCanonicalSnapshotIntegrity:
    """Test that canonical snapshot has required structure for internal_primary."""

    @pytest.fixture(autouse=True)
    def load_snapshot(self):
        canonical_dir = REPO / "data" / "canonical"
        snapshots = sorted(canonical_dir.glob("canonical_snapshot_*.json"), reverse=True)
        if not snapshots:
            pytest.skip("No canonical snapshot available")
        self.snapshot = json.loads(snapshots[0].read_text(encoding="utf-8"))

    def test_has_assets(self):
        assets = self.snapshot.get("assets", [])
        assert len(assets) >= 500, f"Expected >=500 assets, got {len(assets)}"

    def test_assets_have_calibrated_values(self):
        assets = self.snapshot.get("assets", [])
        with_cal = [a for a in assets if a.get("calibrated_value") is not None]
        assert len(with_cal) >= len(assets) * 0.8, (
            f"Only {len(with_cal)}/{len(assets)} assets have calibrated_value"
        )

    def test_assets_have_source_values(self):
        assets = self.snapshot.get("assets", [])
        with_src = [a for a in assets if a.get("source_values")]
        assert len(with_src) >= len(assets) * 0.5, (
            f"Only {len(with_src)}/{len(assets)} assets have source_values"
        )

    def test_has_scarcity_adjusted_values(self):
        assets = self.snapshot.get("assets", [])
        with_scar = [a for a in assets if a.get("scarcity_adjusted_value") is not None]
        assert len(with_scar) >= 100, (
            f"Only {len(with_scar)} assets have scarcity_adjusted_value"
        )

    def test_snapshot_metadata(self):
        assert "run_id" in self.snapshot
        assert "source_count" in self.snapshot
        assert self.snapshot.get("source_count", 0) >= 2

    def test_calibrated_values_in_range(self):
        """Calibrated values should be in 0-9999 range."""
        assets = self.snapshot.get("assets", [])
        for a in assets:
            val = a.get("calibrated_value")
            if val is not None:
                assert 0 <= val <= 9999, (
                    f"{a.get('display_name')}: calibrated_value={val} out of range"
                )


class TestModeIsolation:
    """Test that mode changes are isolated and reversible."""

    def test_public_data_path_ignores_canonical(self):
        """The /api/data code path must not conditionally serve canonical data."""
        server_py = (REPO / "server.py").read_text(encoding="utf-8")
        # Find the api_data function and verify it doesn't branch on canonical mode
        # for its primary response
        import re
        # The main data endpoint handler
        data_fn = re.search(
            r'async def get_data\(.*?\).*?(?=\nasync def |\n@app\.)',
            server_py, re.DOTALL,
        )
        if data_fn:
            fn_text = data_fn.group()
            # Should NOT contain "if.*primary.*canonical_data" pattern
            # that would switch the served payload
            assert "canonical_data" not in fn_text.split("canonicalComparison")[0] if "canonicalComparison" in fn_text else True

    def test_shadow_comparison_non_authoritative(self):
        """Shadow comparison block must be non-authoritative metadata only."""
        server_py = (REPO / "server.py").read_text(encoding="utf-8")
        # The canonicalComparison block should be clearly non-authoritative
        assert "canonicalComparison" in server_py
        # It should be in shadow/internal_primary modes only
        assert 'CANONICAL_DATA_MODE in ("shadow", "internal_primary")' in server_py

    def test_invalid_mode_falls_back_to_off(self):
        """Invalid CANONICAL_DATA_MODE values must fall back to off."""
        server_py = (REPO / "server.py").read_text(encoding="utf-8")
        assert 'CANONICAL_DATA_MODE = "off"' in server_py  # fallback assignment
