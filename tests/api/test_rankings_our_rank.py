"""Tests that the rankings page includes an 'Our Rank' column derived from
consensus rank aggregation, NOT from value sorting.

Static-analysis tests verifying the JS source code contains the correct
column definition, consensus rank computation, and data attribute for Our Rank.
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

    def test_header_our_rank_has_consensus_tooltip(self):
        """Our Rank header should have a title/tooltip mentioning consensus rank."""
        src = RANKINGS_JS.read_text()
        match = re.search(
            r'<th[^>]*title="[^"]*consensus[^"]*"[^>]*>Our Rank',
            src, re.IGNORECASE,
        )
        assert match is not None, (
            "Our Rank header should have a title attribute mentioning 'consensus'"
        )


class TestConsensusRankComputation:
    """Verify rank is computed from per-site rank aggregation, not value sorting."""

    def test_uses_site_weights(self):
        """Consensus rank computation should use per-site weights."""
        src = RANKINGS_JS.read_text()
        assert "_SITE_WEIGHTS" in src, (
            "Rankings should define site weights for consensus rank aggregation"
        )

    def test_uses_median_mean_blend(self):
        """Consensus rank should blend 70% median + 30% weighted mean."""
        src = RANKINGS_JS.read_text()
        assert "0.7 * median" in src, "Should use 70% median blend"
        assert "0.3 * wMean" in src, "Should use 30% weighted mean blend"

    def test_per_site_ranking(self):
        """Should rank players within each site before aggregating."""
        src = RANKINGS_JS.read_text()
        assert "_siteRanks" in src, "Should compute per-site rank maps"

    def test_rank_assigned_before_filters(self):
        """modelRankMap must be built before filtering inside buildFullRankings."""
        src = RANKINGS_JS.read_text()
        fn_start = src.find("function buildFullRankings()")
        assert fn_start > 0, "buildFullRankings not found"
        fn_body = src[fn_start:]
        rank_map_pos = fn_body.find("modelRankMap")
        filter_pos = fn_body.find("ranked = ranked.filter")
        assert rank_map_pos > 0, "modelRankMap not found in buildFullRankings"
        assert filter_pos > 0, "filter logic not found in buildFullRankings"
        assert rank_map_pos < filter_pos, (
            "modelRankMap must be computed before filtering is applied"
        )

    def test_rank_to_value_curve_present(self):
        """Should have the canonical rank-to-value curve function."""
        src = RANKINGS_JS.read_text()
        assert "_rankToValue" in src, "Should define _rankToValue function"
        assert "_CURVE_A" in src, "Should use canonical curve parameter A"

    def test_format_rank_shows_decimals(self):
        """Rank formatting should show decimal precision."""
        src = RANKINGS_JS.read_text()
        assert "_formatRank" in src, "Should define _formatRank function"
        assert "toFixed(1)" in src, "Should format decimals to 1 place"


class TestOurRankInRowData:
    """Verify rank is stored on each row and rendered in cells."""

    def test_row_has_overall_model_rank_field(self):
        """Each ranked row object should carry overallModelRank."""
        src = RANKINGS_JS.read_text()
        assert "overallModelRank:" in src, (
            "Row object must include overallModelRank field"
        )

    def test_row_has_rank_derived_value(self):
        """Each row should have a rankDerivedValue from the rank-to-value curve."""
        src = RANKINGS_JS.read_text()
        assert "rankDerivedValue:" in src, (
            "Row object must include rankDerivedValue field"
        )

    def test_cell_renders_formatted_rank(self):
        """The table cell should display formatted rank with decimals."""
        src = RANKINGS_JS.read_text()
        assert "_formatRank(r.overallModelRank)" in src, (
            "Cell rendering must use _formatRank for decimal display"
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
        assert "modelRankLabel" in src, (
            "Mobile cards should use modelRankLabel variable"
        )


class TestUniverseAwareFiltering:
    """Verify IDP-only and offense-only source filtering in consensus rank."""

    def test_idp_only_sites_set_defined(self):
        """Should define _IDP_ONLY_SITES set for universe filtering."""
        src = RANKINGS_JS.read_text()
        assert "_IDP_ONLY_SITES" in src, "Should define IDP-only site set"

    def test_off_only_sites_set_defined(self):
        """Should define _OFF_ONLY_SITES set for universe filtering."""
        src = RANKINGS_JS.read_text()
        assert "_OFF_ONLY_SITES" in src, "Should define offense-only site set"

    def test_draftSharksIdp_in_idp_only_sites(self):
        """draftSharksIdp must be in the IDP-only filter set."""
        src = RANKINGS_JS.read_text()
        # Find the _IDP_ONLY_SITES definition
        match = re.search(r"_IDP_ONLY_SITES\s*=\s*new Set\(\[([^\]]+)\]", src)
        assert match is not None, "_IDP_ONLY_SITES Set not found"
        assert "draftSharksIdp" in match.group(1), (
            "draftSharksIdp must be in _IDP_ONLY_SITES"
        )

    def test_consensus_rank_skips_idp_for_offense(self):
        """Consensus rank loop should skip IDP-only sites for non-IDP rows."""
        src = RANKINGS_JS.read_text()
        assert "_IDP_ONLY_SITES.has(site)" in src, (
            "Should check _IDP_ONLY_SITES during consensus rank aggregation"
        )

    def test_draftSharksIdp_weight_defined(self):
        """draftSharksIdp should have an explicit weight in _SITE_WEIGHTS."""
        src = RANKINGS_JS.read_text()
        assert "draftSharksIdp:" in src, (
            "draftSharksIdp should have an explicit weight"
        )


class TestValueLabels:
    """Verify value column labels use canonical wording."""

    def test_no_fully_adjusted_label(self):
        """Should not use 'Fully Adjusted' as a label."""
        src = RANKINGS_JS.read_text()
        assert "Fully Adjusted" not in src, (
            "Should not use legacy 'Fully Adjusted' label"
        )

    def test_default_value_label_is_our_value(self):
        """Default value column label should be 'Our Value'."""
        src = RANKINGS_JS.read_text()
        assert "'Our Value'" in src, "Should use 'Our Value' as the default label"


class TestScraperSourceClassification:
    """Verify the scraper has correct source-type classification."""

    SCRAPER_PATH = Path(__file__).resolve().parents[2] / "Dynasty Scraper.py"

    def test_draftSharksIdp_in_scraper_idp_only_sites(self):
        """draftSharksIdp must be in _IDP_ONLY_SITES in Dynasty Scraper."""
        src = self.SCRAPER_PATH.read_text()
        match = re.search(r"_IDP_ONLY_SITES\s*=\s*\{([^}]+)\}", src)
        assert match is not None, "_IDP_ONLY_SITES not found in scraper"
        assert "draftSharksIdp" in match.group(1), (
            "draftSharksIdp must be in _IDP_ONLY_SITES in the scraper"
        )

    def test_composite_loop_has_universe_filter(self):
        """Composite loop should filter IDP sources for offense players."""
        src = self.SCRAPER_PATH.read_text()
        # Find the composite loop area
        loop_start = src.find("for dash_key, raw_val in pdata.items():")
        assert loop_start > 0, "Composite loop not found"
        loop_body = src[loop_start:loop_start + 1000]
        assert "_IDP_ONLY_SITES" in loop_body, (
            "Composite loop should check _IDP_ONLY_SITES for universe filtering"
        )

    def test_draftSharksIdp_has_scraper_weight(self):
        """draftSharksIdp should have an explicit weight in SITE_WEIGHTS."""
        src = self.SCRAPER_PATH.read_text()
        match = re.search(r"SITE_WEIGHTS\s*=\s*\{([^}]+)\}", src)
        assert match is not None, "SITE_WEIGHTS not found in scraper"
        assert "draftSharksIdp" in match.group(1), (
            "draftSharksIdp should have an explicit weight in SITE_WEIGHTS"
        )

    def test_idp_anchor_locking_present(self):
        """Post-composite IDP anchor locking step should exist."""
        src = self.SCRAPER_PATH.read_text()
        assert "IDP Anchor Lock" in src or "IDP anchor lock" in src.lower(), (
            "Scraper should have post-composite IDP anchor locking"
        )

    def test_rookie_bridge_present(self):
        """Post-composite rookie bridge calibration should exist."""
        src = self.SCRAPER_PATH.read_text()
        assert "Rookie Bridge" in src or "rookie bridge" in src.lower(), (
            "Scraper should have post-composite rookie bridge calibration"
        )
