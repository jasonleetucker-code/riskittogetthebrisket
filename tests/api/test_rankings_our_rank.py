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
        """Rank map must be built before filtering inside buildFullRankings."""
        src = RANKINGS_JS.read_text()
        # Find the buildFullRankings function
        fn_start = src.find("function buildFullRankings()")
        assert fn_start > 0, "buildFullRankings not found"
        fn_body = src[fn_start:]
        # positionRankMap is the fallback; canonical ranks come from row data
        rank_map_pos = fn_body.find("positionRankMap")
        # Filter application: ranked = ranked.filter(...)
        filter_pos = fn_body.find("ranked = ranked.filter")
        assert rank_map_pos > 0, "positionRankMap not found in buildFullRankings"
        assert filter_pos > 0, "filter logic not found in buildFullRankings"
        assert rank_map_pos < filter_pos, (
            "positionRankMap must be computed before filtering is applied"
        )

    def test_fallback_rank_is_one_based(self):
        """Fallback rank assignment should use i + 1 (1-based)."""
        src = RANKINGS_JS.read_text()
        assert "positionRankMap.set(r.name, i + 1)" in src, (
            "Fallback rank should be 1-based (i + 1)"
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


class TestCanonicalRankSupport:
    """Verify canonical consensus_rank (decimal) flows through to the UI."""

    def test_row_carries_canonical_consensus_rank(self):
        """Each row object should carry canonicalConsensusRank from player data."""
        src = RANKINGS_JS.read_text()
        assert "canonicalConsensusRank:" in src, (
            "Row object must include canonicalConsensusRank field"
        )

    def test_row_carries_canonical_tier_id(self):
        """Each row object should carry canonicalTierId from player data."""
        src = RANKINGS_JS.read_text()
        assert "canonicalTierId:" in src, (
            "Row object must include canonicalTierId field"
        )

    def test_canonical_rank_preferred_over_integer_fallback(self):
        """When canonical ranks are available, they should be used over integer fallback."""
        src = RANKINGS_JS.read_text()
        assert "hasCanonicalRanks" in src, (
            "Code should check for canonical rank availability"
        )
        assert "canonicalConsensusRank" in src, (
            "Code should reference canonicalConsensusRank for the model rank"
        )

    def test_decimal_rank_formatting(self):
        """Our Rank cell should format decimal values with toFixed(1)."""
        src = RANKINGS_JS.read_text()
        assert "toFixed(1)" in src, (
            "Decimal rank should be formatted with 1 decimal place"
        )


class TestLegacyLabelsRemoved:
    """Verify legacy terminology is replaced with canonical terminology."""

    def test_no_fully_adjusted_in_rankings_dropdown(self):
        """Rankings sort dropdown should not say 'Fully Adjusted'."""
        src = RANKINGS_JS.read_text()
        # Check only in the rankings-related areas (not unrelated code)
        # The RANKINGS_DATA_MODE_LABELS constant area and buildFullRankings area
        assert "Fully Adjusted" not in src, (
            "Rankings JS still contains 'Fully Adjusted' — should be 'Our Value'"
        )

    def test_no_final_value_column_header(self):
        """Detail column should not say 'Final Value' — should say 'Our Value'."""
        src = RANKINGS_JS.read_text()
        assert ">Final Value<" not in src, (
            "Column header still says 'Final Value' — should be 'Our Value'"
        )

    def test_value_full_label_is_our_value(self):
        """The default sort mode label should be 'Our Value' not 'Value (Full)'."""
        src = RANKINGS_JS.read_text()
        # In the valueColLabel determination
        assert "'Our Value'" in src, (
            "Default value column label should be 'Our Value'"
        )

    def test_rankings_html_dropdown_says_our_value(self):
        """The HTML sort dropdown for rankings should say 'Our Value'."""
        html_path = Path(__file__).resolve().parents[2] / "Static" / "index.html"
        src = html_path.read_text()
        # Find the rankingsSortBasis select
        import re
        match = re.search(r'id="rankingsSortBasis".*?</select>', src, re.DOTALL)
        assert match is not None, "rankingsSortBasis select not found"
        select_html = match.group(0)
        assert "Our Value" in select_html, (
            "Rankings sort dropdown should have 'Our Value' option"
        )
        assert "Fully Adjusted" not in select_html, (
            "Rankings sort dropdown should not have 'Fully Adjusted' option"
        )


class TestServerCanonicalOverlay:
    """Verify server pushes canonical rank and tier to player data."""

    def test_server_pushes_consensus_rank(self):
        """server.py overlay should set _canonicalConsensusRank on player data."""
        server_path = Path(__file__).resolve().parents[2] / "server.py"
        src = server_path.read_text()
        assert "_canonicalConsensusRank" in src, (
            "Server overlay must push _canonicalConsensusRank to player data"
        )

    def test_server_pushes_tier_id(self):
        """server.py overlay should set _canonicalTierId on player data."""
        server_path = Path(__file__).resolve().parents[2] / "server.py"
        src = server_path.read_text()
        assert "_canonicalTierId" in src, (
            "Server overlay must push _canonicalTierId to player data"
        )
