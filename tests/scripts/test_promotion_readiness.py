"""Tests for check_promotion_readiness threshold loading."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.check_promotion_readiness import _load_thresholds


class TestLoadThresholds:
    """Verify that _load_thresholds reads from config and falls back correctly."""

    def test_loads_internal_primary_from_config(self):
        thresholds = _load_thresholds(REPO, "internal_primary")
        assert thresholds.get("source_count_min") == 2
        assert thresholds.get("top50_overlap_min_pct") == 66
        assert thresholds.get("avg_abs_delta_max") == 1500

    def test_loads_public_primary_from_config(self):
        thresholds = _load_thresholds(REPO, "public_primary")
        assert thresholds.get("source_count_min") == 2
        assert thresholds.get("top50_overlap_min_pct") == 80
        assert thresholds.get("avg_abs_delta_max") == 800

    def test_loads_shadow_from_config(self):
        thresholds = _load_thresholds(REPO, "shadow")
        assert thresholds.get("canonical_asset_count_min") == 300
        assert thresholds.get("source_count_min") == 2

    def test_public_stricter_than_internal(self):
        internal = _load_thresholds(REPO, "internal_primary")
        public = _load_thresholds(REPO, "public_primary")
        # Both modes require 2 sources in the 2-source model
        assert public["source_count_min"] == internal["source_count_min"]
        assert public["top50_overlap_min_pct"] > internal["top50_overlap_min_pct"]
        assert public["avg_abs_delta_max"] < internal["avg_abs_delta_max"]

    def test_fallback_when_config_missing(self, tmp_path):
        """Returns hard-coded fallbacks when config dir doesn't exist."""
        thresholds = _load_thresholds(tmp_path, "internal_primary")
        assert thresholds.get("source_count_min") == 2
        assert thresholds.get("top50_overlap_min_pct") == 66

    def test_fallback_when_config_malformed(self, tmp_path):
        """Returns hard-coded fallbacks when config is not valid JSON."""
        cfg_dir = tmp_path / "config" / "promotion"
        cfg_dir.mkdir(parents=True)
        (cfg_dir / "promotion_thresholds.json").write_text("not json")
        thresholds = _load_thresholds(tmp_path, "internal_primary")
        assert thresholds.get("source_count_min") == 2

    def test_unknown_mode_returns_empty(self):
        thresholds = _load_thresholds(REPO, "nonexistent_mode")
        assert thresholds == {}
