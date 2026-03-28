"""Tests that the rankings page includes an 'Our Rank' column derived from our model.

Static-analysis tests verifying the JS source code contains the correct
column definition, rank computation, and data attribute for Our Rank.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

STATIC_DIR = Path(__file__).resolve().parents[2] / "Static"
RANKINGS_JS = STATIC_DIR / "js" / "runtime" / "10-rankings-and-picks.js"


class TestOurRankColumnExists:
    """Verify the 'Our Rank' column is present in the rankings table."""

    def test_header_contains_our_rank(self):
        """Table header must include an 'Our Rank' column."""
        src = RANKINGS_JS.read_text()
        assert "Our Rank" in src, "Rankings JS does not contain 'Our Rank' header"

    def test_header_our_rank_has_tooltip(self):
        """Our Rank header should have a title/tooltip explaining it."""
        src = RANKINGS_JS.read_text()
        # Look for the th element with Our Rank and a title attribute
        match = re.search(r'<th[^>]*title="[^"]*model[^"]*"[^>]*>Our Rank', src, re.IGNORECASE)
        assert match is not None, (
            "Our Rank header should have a title attribute mentioning 'model'"
        )


class TestOurRankComputation:
    """Verify rank is computed from our model value, not arbitrary index."""

    def test_rank_computed_from_adjusted_composite(self):
        """overallModelRank must be derived by sorting on adjustedComposite."""
        src = RANKINGS_JS.read_text()
        # The sort that computes model rank should reference adjustedComposite
        assert "b.adjustedComposite - a.adjustedComposite" in src, (
            "Model rank sort should compare adjustedComposite (our final model value)"
        )

    def test_rank_assigned_before_filters_in_build_function(self):
        """modelRankMap must be built before filtering inside buildFullRankings."""
        src = RANKINGS_JS.read_text()
        # Find the buildFullRankings function
        fn_start = src.find("function buildFullRankings()")
        assert fn_start > 0, "buildFullRankings not found"
        fn_body = src[fn_start:]
        rank_map_pos = fn_body.find("modelRankMap")
        # Filter application: ranked = ranked.filter(...)
        filter_pos = fn_body.find("ranked = ranked.filter")
        assert rank_map_pos > 0, "modelRankMap not found in buildFullRankings"
        assert filter_pos > 0, "filter logic not found in buildFullRankings"
        assert rank_map_pos < filter_pos, (
            "modelRankMap must be computed before filtering is applied"
        )

    def test_rank_is_one_based(self):
        """Rank assignment should use i + 1 (1-based)."""
        src = RANKINGS_JS.read_text()
        # The forEach that assigns rank should add 1
        assert "modelRankMap.set(r.name, i + 1)" in src, (
            "Model rank should be 1-based (i + 1)"
        )


class TestOurRankInRowData:
    """Verify rank is stored on each row and rendered in cells."""

    def test_row_has_overall_model_rank_field(self):
        """Each ranked row object should carry overallModelRank."""
        src = RANKINGS_JS.read_text()
        assert "overallModelRank:" in src, (
            "Row object must include overallModelRank field"
        )

    def test_cell_renders_overall_model_rank(self):
        """The table cell should display r.overallModelRank."""
        src = RANKINGS_JS.read_text()
        assert "r.overallModelRank" in src, (
            "Cell rendering must reference r.overallModelRank"
        )

    def test_data_attribute_stored_on_tr(self):
        """Each <tr> should store data-overallModelRank for testability."""
        src = RANKINGS_JS.read_text()
        assert "dataset.overallModelRank" in src, (
            "Table row should store data-overallModelRank attribute"
        )


class TestOurRankOnMobile:
    """Verify mobile cards include the model rank."""

    def test_mobile_card_shows_our_rank(self):
        """Mobile card subtitle should include 'Our Rank' label."""
        src = RANKINGS_JS.read_text()
        assert "Our Rank" in src, "Mobile rendering should mention Our Rank"
        # Specifically in the mobile card template
        assert "modelRankLabel" in src, (
            "Mobile cards should use modelRankLabel variable"
        )
