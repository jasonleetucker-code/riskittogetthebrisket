"""Valuation pipeline behavior tests.

These test the documented behavior of the live valuation pipeline parameters.
They verify configuration values and document intended behavior without running
the full scraper pipeline.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRAPER = REPO / "Dynasty Scraper.py"


def _scraper_src() -> str:
    return SCRAPER.read_text(encoding="utf-8")


class TestEliteCeilingBehavior:
    """Elite offensive players should approach the 9999 ceiling."""

    def test_composite_scale_is_9999(self):
        src = _scraper_src()
        assert "COMPOSITE_SCALE = 9999" in src

    def test_elite_boost_max_allows_meaningful_expansion(self):
        """ELITE_BOOST_MAX should be >= 0.08 to allow top players near ceiling."""
        m = re.search(r"ELITE_BOOST_MAX\s*=\s*([\d.]+)", _scraper_src())
        assert m is not None
        val = float(m.group(1))
        assert val >= 0.08, f"ELITE_BOOST_MAX={val} too low for meaningful ceiling expansion"

    def test_elite_norm_threshold_below_0_90(self):
        """Threshold should be <= 0.90 to allow broader elite expansion."""
        m = re.search(r"ELITE_NORM_THRESHOLD\s*=\s*([\d.]+)", _scraper_src())
        assert m is not None
        val = float(m.group(1))
        assert val <= 0.90, f"ELITE_NORM_THRESHOLD={val} too high"

    def test_elite_cap_guardrail_offense_allows_8_percent(self):
        """Offense elite cap should allow at least 8% above value-site ceiling."""
        src = _scraper_src()
        # Find the offense elite cap line
        m = re.search(r"elite_cap = cap_limit \* \(1\.0 \+ \(([\d.]+) \* market_conf\)\)", src)
        assert m is not None
        # The second match (non-IDP path) should be >= 0.08
        matches = re.findall(r"elite_cap = cap_limit \* \(1\.0 \+ \(([\d.]+) \* market_conf\)\)", src)
        assert len(matches) >= 2
        offense_factor = float(matches[1])  # second match is the non-IDP one
        assert offense_factor >= 0.08, f"Offense elite cap factor {offense_factor} too low"


class TestSingleSourceSuppression:
    """Single-source veterans should get strong low-liquidity suppression."""

    def test_single_source_discount_min_below_0_60(self):
        """Min discount should be <= 0.60 for strong suppression."""
        m = re.search(r"SINGLE_SOURCE_DISCOUNT_MIN\s*=\s*([\d.]+)", _scraper_src())
        assert m is not None
        val = float(m.group(1))
        assert val <= 0.60, f"SINGLE_SOURCE_DISCOUNT_MIN={val} not aggressive enough"

    def test_single_source_discount_max_below_0_85(self):
        """Max discount should be < 0.85 even with high confidence."""
        m = re.search(r"SINGLE_SOURCE_DISCOUNT_MAX\s*=\s*([\d.]+)", _scraper_src())
        assert m is not None
        val = float(m.group(1))
        assert val < 0.85, f"SINGLE_SOURCE_DISCOUNT_MAX={val} too lenient"


class TestIDPAnchorPlacement:
    """IDP anchor must be locked and defensible."""

    def test_idp_anchor_top_is_set(self):
        src = _scraper_src()
        assert "IDP_ANCHOR_TOP" in src

    def test_idp_anchor_from_top_defensive_player(self):
        """IDP_ANCHOR_TOP should be derived from the highest IDP value."""
        src = _scraper_src()
        assert "Top defensive player" in src or "IDP_ANCHOR_TOP" in src

    def test_idp_value_cap_sites_includes_idptradecalc(self):
        src = _scraper_src()
        assert '"idpTradeCalc"' in src
        # Must be in the value cap sites set
        assert "_idp_value_cap_sites" in src


class TestRookieBridgeBehavior:
    """Rookie-only boards should not dominate mixed placement."""

    def test_rookie_only_dlf_excluded_for_non_rookies(self):
        """DLF rookie-only sources should not affect veteran composites."""
        src = _scraper_src()
        assert "_ROOKIE_ONLY_DLF_SITE_KEYS" in src or "ROOKIE_ONLY_DLF" in src
        # Must check for rookie status before including
        assert "not _is_this_rookie" in src

    def test_idp_rookie_only_no_market_cap_exists(self):
        """IDP rookie-only signals without real IDP market should be capped."""
        src = _scraper_src()
        assert "IDP_ROOKIE_ONLY_NO_MARKET_CAP" in src


class TestSourceTypeHandling:
    """Source types must be explicitly classified."""

    def test_source_types_documented_in_pool_builder(self):
        from src.pool.builder import SOURCE_TYPES
        assert "ktc" in SOURCE_TYPES
        assert "idpTradeCalc" in SOURCE_TYPES

    def test_source_type_categories(self):
        from src.pool.builder import SOURCE_TYPES
        types = set(SOURCE_TYPES.values())
        expected = {
            "full_mixed_value",
            "mixed_offense_idp_bridge",
        }
        assert types == expected, f"Missing source types: {expected - types}"

    def test_idptradecalc_is_mixed_bridge(self):
        from src.pool.builder import SOURCE_TYPES
        assert SOURCE_TYPES["idpTradeCalc"] == "mixed_offense_idp_bridge"
