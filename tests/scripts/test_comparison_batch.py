"""Tests for the comparison batch runner."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure repo root on path
REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.run_comparison_batch import (
    _normalize_name,
    match_players,
    compute_stats,
    generate_markdown,
)


class TestNormalizeName:
    def test_basic(self):
        assert _normalize_name("Josh Allen") == "josh allen"

    def test_suffix_stripping(self):
        assert _normalize_name("Marvin Harrison Jr.") == "marvin harrison"

    def test_period_stripping(self):
        assert _normalize_name("A.J. Brown") == "aj brown"

    def test_apostrophe(self):
        assert _normalize_name("Ja'Marr Chase") == "jamarr chase"


class TestMatchPlayers:
    def test_exact_match(self):
        canonical = {"Josh Allen": {"value": 9000, "universe": "offense_vet", "source_count": 2, "source_values": {}}}
        legacy = {"Josh Allen": {"value": 8500, "pos": "QB", "name": "Josh Allen"}}
        matched, c_only, l_only = match_players(canonical, legacy)
        assert len(matched) == 1
        assert matched[0]["delta"] == 500
        assert len(c_only) == 0
        assert len(l_only) == 0

    def test_normalized_match(self):
        canonical = {"A.J. Brown": {"value": 7000, "universe": "offense_vet", "source_count": 1, "source_values": {}}}
        legacy = {"AJ Brown": {"value": 5000, "pos": "WR", "name": "AJ Brown"}}
        matched, c_only, l_only = match_players(canonical, legacy)
        assert len(matched) == 1

    def test_unmatched(self):
        canonical = {"Player A": {"value": 5000, "universe": "offense_vet", "source_count": 1, "source_values": {}}}
        legacy = {"Player B": {"value": 4000, "pos": "RB", "name": "Player B"}}
        matched, c_only, l_only = match_players(canonical, legacy)
        assert len(matched) == 0
        assert len(c_only) == 1
        assert len(l_only) == 1


class TestComputeStats:
    def test_basic_stats(self):
        matched = [
            {"name": "A", "canonical_value": 9000, "legacy_value": 8500, "delta": 500, "abs_delta": 500, "pct_delta": 5.9, "universe": "offense_vet", "source_count": 2, "legacy_pos": "QB"},
            {"name": "B", "canonical_value": 7000, "legacy_value": 5000, "delta": 2000, "abs_delta": 2000, "pct_delta": 40.0, "universe": "offense_vet", "source_count": 1, "legacy_pos": "WR"},
        ]
        stats = compute_stats(matched)
        assert stats["count"] == 2
        assert stats["avg_abs_delta"] == 1250
        assert stats["max_abs_delta"] == 2000
        assert "delta_distribution" in stats

    def test_empty(self):
        stats = compute_stats([])
        assert stats["count"] == 0


class TestGenerateMarkdown:
    def test_produces_markdown(self):
        matched = [
            {"name": "A", "canonical_value": 9000, "legacy_value": 8500, "delta": 500, "abs_delta": 500, "pct_delta": 5.9, "universe": "offense_vet", "source_count": 2, "legacy_pos": "QB"},
        ]
        stats = compute_stats(matched)
        md = generate_markdown(stats, matched, ["C"], ["D"], "snap.json", "legacy.json")
        assert "Comparison Report" in md
        assert "snap.json" in md
        assert "legacy.json" in md
