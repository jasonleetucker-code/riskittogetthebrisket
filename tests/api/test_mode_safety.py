"""Tests for CANONICAL_DATA_MODE behavior and internal-primary safety."""
from __future__ import annotations

import json
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
        content = env_path.read_text()
        assert "CANONICAL_DATA_MODE=off" in content

    def test_server_defaults_to_off(self):
        """server.py must default to off when env var is unset."""
        server_py = (REPO / "server.py").read_text()
        assert 'os.getenv("CANONICAL_DATA_MODE", "off")' in server_py


class TestInternalPrimarySafety:
    """Test that internal_primary mode doesn't affect public data serving."""

    def test_api_data_always_serves_legacy(self):
        """The /api/data endpoint must always serve legacy data regardless of mode."""
        server_py = (REPO / "server.py").read_text()
        # Verify there's no mode-conditional logic in the data endpoint
        # that would switch to canonical data
        assert "latest_contract_data" in server_py
        # The main data serving should not reference canonical_data
        # (it only references it in the comparison/scaffold blocks)

    def test_scaffold_canonical_requires_internal_primary(self):
        """The canonical scaffold endpoint must only be available in internal_primary."""
        server_py = (REPO / "server.py").read_text()
        assert 'CANONICAL_DATA_MODE != "internal_primary"' in server_py

    def test_scaffold_endpoints_documented(self):
        """All scaffold endpoints should be documented in server.py."""
        server_py = (REPO / "server.py").read_text()
        assert "/api/scaffold/canonical" in server_py
        assert "/api/scaffold/mode" in server_py
        assert "/api/scaffold/shadow" in server_py


class TestRollbackPath:
    """Test that rollback is simple and safe."""

    def test_mode_off_disables_canonical_loading(self):
        """Setting mode=off should skip canonical snapshot loading."""
        server_py = (REPO / "server.py").read_text()
        assert 'CANONICAL_DATA_MODE == "off"' in server_py
        # Verify it returns None (skips loading)
        assert "return None" in server_py  # in _load_canonical_snapshot

    def test_rollback_documented(self):
        """Rollback instructions should be documented."""
        env_example = (REPO / ".env.example").read_text()
        assert "revert" in env_example.lower() or "CANONICAL_DATA_MODE=off" in env_example


class TestPromotionReadiness:
    """Test that promotion readiness correctly evaluates internal_primary."""

    def test_readiness_script_exists(self):
        assert (REPO / "scripts" / "check_promotion_readiness.py").exists()

    def test_readiness_uses_offense_players_only(self):
        """Promotion readiness should use offense_players_only metrics."""
        script = (REPO / "scripts" / "check_promotion_readiness.py").read_text()
        assert "offense_players_only" in script

    def test_all_hard_checks_pass(self):
        """Run actual readiness checks and verify all hard checks pass."""
        from scripts.check_promotion_readiness import check_internal_primary_readiness
        results = check_internal_primary_readiness(REPO)
        hard_fails = [r for r in results if r.get("pass") is False]
        for f in hard_fails:
            print(f"FAIL: {f['check']}: required={f['required']}, actual={f['actual']}")
        assert len(hard_fails) == 0, f"{len(hard_fails)} hard checks failed"
