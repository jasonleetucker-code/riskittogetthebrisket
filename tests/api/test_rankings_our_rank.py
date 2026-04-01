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


class TestEliteCeilingExpansion:
    """Verify the elite ceiling expansion and ceiling-pull mechanisms."""

    SCRAPER_PATH = Path(__file__).resolve().parents[2] / "Dynasty Scraper.py"

    def test_elite_boost_max_at_least_8_percent(self):
        """ELITE_BOOST_MAX should be >= 0.08 for sufficient elite separation."""
        src = self.SCRAPER_PATH.read_text()
        match = re.search(r"ELITE_BOOST_MAX\s*=\s*([\d.]+)", src)
        assert match is not None, "ELITE_BOOST_MAX not found"
        assert float(match.group(1)) >= 0.08, (
            f"ELITE_BOOST_MAX should be >= 0.08, got {match.group(1)}"
        )

    def test_elite_norm_threshold_at_most_0_90(self):
        """ELITE_NORM_THRESHOLD should be <= 0.90 to capture broader elite tier."""
        src = self.SCRAPER_PATH.read_text()
        match = re.search(r"ELITE_NORM_THRESHOLD\s*=\s*([\d.]+)", src)
        assert match is not None, "ELITE_NORM_THRESHOLD not found"
        assert float(match.group(1)) <= 0.90, (
            f"ELITE_NORM_THRESHOLD should be <= 0.90, got {match.group(1)}"
        )

    def test_ceiling_pull_exists(self):
        """A ceiling-pull mechanism should exist for high-value offense players."""
        src = self.SCRAPER_PATH.read_text()
        assert "Ceiling pull" in src or "ceiling pull" in src.lower(), (
            "Scraper should have a ceiling-pull step for elite offense players"
        )

    def test_ceiling_pull_requires_multiple_sources(self):
        """Ceiling pull should require >= 4 sources to prevent single-source inflation."""
        src = self.SCRAPER_PATH.read_text()
        # Find the ceiling pull section
        cp_start = src.lower().find("ceiling pull")
        assert cp_start > 0, "Ceiling pull section not found"
        cp_block = src[cp_start:cp_start + 500]
        assert "len(wNorms) >= 4" in cp_block, (
            "Ceiling pull should require at least 4 sources"
        )

    def test_ceiling_pull_offense_only(self):
        """Ceiling pull should only apply to non-IDP players."""
        src = self.SCRAPER_PATH.read_text()
        cp_start = src.lower().find("ceiling pull")
        assert cp_start > 0
        cp_block = src[cp_start:cp_start + 500]
        assert "not _is_this_idp" in cp_block, (
            "Ceiling pull should be restricted to offense players"
        )


class TestSingleSourceDecay:
    """Verify single-source veteran suppression is aggressive enough."""

    SCRAPER_PATH = Path(__file__).resolve().parents[2] / "Dynasty Scraper.py"

    def test_steep_threshold_at_least_0_60(self):
        """SINGLE_SOURCE_STEEP_THRESHOLD should be >= 0.60 for broader coverage."""
        src = self.SCRAPER_PATH.read_text()
        match = re.search(r"SINGLE_SOURCE_STEEP_THRESHOLD\s*=\s*([\d.]+)", src)
        assert match is not None, "SINGLE_SOURCE_STEEP_THRESHOLD not found"
        assert float(match.group(1)) >= 0.60, (
            f"SINGLE_SOURCE_STEEP_THRESHOLD should be >= 0.60, got {match.group(1)}"
        )

    def test_steep_extra_at_least_0_20(self):
        """SINGLE_SOURCE_STEEP_EXTRA should be >= 0.20 for meaningful suppression."""
        src = self.SCRAPER_PATH.read_text()
        match = re.search(r"SINGLE_SOURCE_STEEP_EXTRA\s*=\s*([\d.]+)", src)
        assert match is not None, "SINGLE_SOURCE_STEEP_EXTRA not found"
        assert float(match.group(1)) >= 0.20, (
            f"SINGLE_SOURCE_STEEP_EXTRA should be >= 0.20, got {match.group(1)}"
        )

    def test_rank_only_source_extra_penalty(self):
        """Single-source rank-only players should get an additional penalty."""
        src = self.SCRAPER_PATH.read_text()
        steep_section = src[src.find("Single-source reliability floor"):]
        assert "is_rank_only" in steep_section or "rank_only" in steep_section.lower(), (
            "Single-source steep discount should check for rank-only sources"
        )

    def test_inline_discount_min_at_most_0_70(self):
        """SINGLE_SOURCE_DISCOUNT_MIN should be <= 0.70 (30% minimum haircut)."""
        src = self.SCRAPER_PATH.read_text()
        match = re.search(r"SINGLE_SOURCE_DISCOUNT_MIN\s*=\s*([\d.]+)", src)
        assert match is not None, "SINGLE_SOURCE_DISCOUNT_MIN not found"
        assert float(match.group(1)) <= 0.70, (
            f"SINGLE_SOURCE_DISCOUNT_MIN should be <= 0.70, got {match.group(1)}"
        )


class TestFrontendRankPrecedence:
    """Verify unified rank precedence across frontend files."""

    DYNASTY_DATA_JS = Path(__file__).resolve().parents[2] / "frontend" / "lib" / "dynasty-data.js"
    RANKINGS_PAGE = Path(__file__).resolve().parents[2] / "frontend" / "app" / "rankings" / "page.jsx"

    def test_resolved_rank_helper_exported(self):
        """dynasty-data.js should export a resolvedRank helper."""
        src = self.DYNASTY_DATA_JS.read_text()
        assert "export function resolvedRank" in src, (
            "dynasty-data.js should export resolvedRank()"
        )

    def test_resolved_rank_canonical_first(self):
        """resolvedRank should prefer canonicalConsensusRank over computed."""
        src = self.DYNASTY_DATA_JS.read_text()
        fn_start = src.find("export function resolvedRank")
        assert fn_start > 0
        fn_body = src[fn_start:fn_start + 200]
        # canonical should appear before computed in the ?? chain
        canonical_pos = fn_body.find("canonicalConsensusRank")
        computed_pos = fn_body.find("computedConsensusRank")
        assert canonical_pos > 0 and computed_pos > 0, (
            "resolvedRank should reference both rank fields"
        )
        assert canonical_pos < computed_pos, (
            "canonicalConsensusRank must come before computedConsensusRank"
        )

    def test_build_rows_uses_resolved_rank(self):
        """buildRows sort should use resolvedRank, not inline precedence."""
        src = self.DYNASTY_DATA_JS.read_text()
        # Find the sort calls in buildRows
        fn_start = src.find("export function buildRows")
        assert fn_start > 0
        fn_body = src[fn_start:]
        # Should NOT have inline "r.computedConsensusRank ?? r.canonicalConsensusRank"
        assert "computedConsensusRank ?? r.canonicalConsensusRank" not in fn_body, (
            "buildRows should not have inline rank precedence — use resolvedRank()"
        )
        assert "resolvedRank" in fn_body, (
            "buildRows should use resolvedRank() for sorting"
        )

    def test_rankings_page_imports_resolved_rank(self):
        """rankings/page.jsx should import resolvedRank from dynasty-data."""
        src = self.RANKINGS_PAGE.read_text()
        assert "resolvedRank" in src, (
            "rankings/page.jsx should import and use resolvedRank"
        )

    def test_rankings_page_no_inline_precedence(self):
        """rankings/page.jsx should not have its own inline rank precedence chain."""
        src = self.RANKINGS_PAGE.read_text()
        assert "r.canonicalConsensusRank ?? r.computedConsensusRank" not in src, (
            "modelRankMap should use resolvedRank(), not inline ??"
        )


class TestStaticRankingsUnresolvedPositionGuard:
    """Verify the static rankings pipeline rejects unresolved-position players."""

    RANKINGS_JS = Path(__file__).resolve().parents[2] / "Static" / "js" / "runtime" / "10-rankings-and-picks.js"

    def test_valid_player_pos_set_defined(self):
        """_VALID_PLAYER_POS set must be defined for position validation."""
        src = self.RANKINGS_JS.read_text()
        assert "_VALID_PLAYER_POS" in src, (
            "Should define _VALID_PLAYER_POS set for position validation"
        )

    def test_valid_pos_includes_all_offense(self):
        """_VALID_PLAYER_POS must include QB, RB, WR, TE."""
        src = self.RANKINGS_JS.read_text()
        match = re.search(r"_VALID_PLAYER_POS\s*=\s*new Set\(\[([^\]]+)\]", src)
        assert match is not None, "_VALID_PLAYER_POS Set not found"
        content = match.group(1)
        for pos in ["QB", "RB", "WR", "TE"]:
            assert f"'{pos}'" in content, f"{pos} missing from _VALID_PLAYER_POS"

    def test_valid_pos_includes_all_idp(self):
        """_VALID_PLAYER_POS must include DL, DE, DT, LB, DB, CB, S, EDGE."""
        src = self.RANKINGS_JS.read_text()
        match = re.search(r"_VALID_PLAYER_POS\s*=\s*new Set\(\[([^\]]+)\]", src)
        assert match is not None
        content = match.group(1)
        for pos in ["DL", "DE", "DT", "LB", "DB", "CB", "S", "EDGE"]:
            assert f"'{pos}'" in content, f"{pos} missing from _VALID_PLAYER_POS"

    def test_valid_pos_excludes_pick(self):
        """_VALID_PLAYER_POS must NOT include PICK (picks have their own path)."""
        src = self.RANKINGS_JS.read_text()
        match = re.search(r"_VALID_PLAYER_POS\s*=\s*new Set\(\[([^\]]+)\]", src)
        assert match is not None
        assert "'PICK'" not in match.group(1), "PICK must not be in _VALID_PLAYER_POS"

    def test_base_rows_filter_unresolved_pos(self):
        """getOrBuildRankingsBaseRows must reject rows with unresolved positions."""
        src = self.RANKINGS_JS.read_text()
        fn_start = src.find("function getOrBuildRankingsBaseRows")
        assert fn_start > 0
        fn_body = src[fn_start:fn_start + 2000]
        assert "_VALID_PLAYER_POS.has(pos)" in fn_body, (
            "getOrBuildRankingsBaseRows must check _VALID_PLAYER_POS"
        )

    def test_no_value_sort_fallback_rank(self):
        """modelRankMap must NOT assign fallback ranks from value sort."""
        src = self.RANKINGS_JS.read_text()
        fn_start = src.find("function buildFullRankings")
        assert fn_start > 0
        fn_body = src[fn_start:fn_start + 5000]
        # The old bug: _valSorted.forEach((r, i) => { if (!modelRankMap.has(r.name)) modelRankMap.set(r.name, i + 1); });
        assert "if (!modelRankMap.has(r.name)) modelRankMap.set(r.name, i + 1)" not in fn_body, (
            "Must not assign fallback ranks from value sort — "
            "this lets unranked rows displace properly ranked players"
        )

    def test_unranked_rows_get_infinity(self):
        """Rows without consensus rank must get overallModelRank = Infinity."""
        src = self.RANKINGS_JS.read_text()
        fn_start = src.find("function buildFullRankings")
        assert fn_start > 0
        fn_body = src[fn_start:fn_start + 10000]
        assert "Infinity" in fn_body, (
            "Unranked rows should get overallModelRank = Infinity"
        )
        assert "_hasValidRank" in fn_body, (
            "Rows should carry _hasValidRank flag for sort logic"
        )

    def test_rank_first_sort_for_default_basis(self):
        """Default sort (sortBasis === 'full') must sort by rank, not value."""
        src = self.RANKINGS_JS.read_text()
        fn_start = src.find("function buildFullRankings")
        assert fn_start > 0
        fn_body = src[fn_start:fn_start + 10000]
        assert "sortBasis === 'full'" in fn_body, (
            "Default sort should check for 'full' basis to enable rank-first sort"
        )
        assert "a.overallModelRank - b.overallModelRank" in fn_body, (
            "Rank-first sort should compare overallModelRank directly"
        )

    def test_unranked_sort_to_bottom(self):
        """Unranked rows must sort after all ranked rows."""
        src = self.RANKINGS_JS.read_text()
        fn_start = src.find("function buildFullRankings")
        assert fn_start > 0
        fn_body = src[fn_start:fn_start + 10000]
        # The sort comparator must check _hasValidRank to push unranked down
        assert "a._hasValidRank && !b._hasValidRank" in fn_body, (
            "Sort must push unranked rows (no _hasValidRank) below ranked rows"
        )
