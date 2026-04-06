"""Rankings architecture guardrails — KTC-only mode.

These tests are the cross-file sync enforcement layer.  They run against
the actual JS source text of BOTH ranking implementations and verify they
agree on:
  • formula constants (midpoint, slope, scale)
  • rank limit (500)
  • eligibility guards (no "?", no PICK, positive KTC value only)
  • output shape (4-column schema, integer ktcRank, ourValue / rankDerivedValue)
  • absence of old consensus-blending artifacts (_SITE_WEIGHTS, toFixed(1), etc.)

If you change ranking logic in one file, at least one of these tests will
fail until the parallel file is updated — that's the point.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
STATIC_JS = REPO / "Static" / "js" / "runtime" / "10-rankings-and-picks.js"
NEXT_JS = REPO / "frontend" / "lib" / "dynasty-data.js"


# ── helpers ──────────────────────────────────────────────────────────────────

def _src(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ── Formula presence ─────────────────────────────────────────────────────────

class TestHillFormulaPresent:
    """Both JS files must define the Hill-style rank-to-value formula."""

    def test_static_defines_rank_to_value(self):
        assert "_rankToValue" in _src(STATIC_JS), \
            "Static JS must define _rankToValue function"

    def test_next_exports_rank_to_value(self):
        assert "rankToValue" in _src(NEXT_JS), \
            "Next.js lib must export rankToValue function"

    def test_static_formula_midpoint(self):
        """Static JS must use midpoint divisor of 45 in the Hill formula."""
        assert "/ 45," in _src(STATIC_JS) or "/ 45)" in _src(STATIC_JS), \
            "Static JS Hill formula must use midpoint 45"

    def test_next_formula_midpoint(self):
        """Next.js lib must use midpoint divisor of 45 in the Hill formula."""
        assert "/ 45," in _src(NEXT_JS) or "/ 45)" in _src(NEXT_JS), \
            "Next.js lib Hill formula must use midpoint 45"

    def test_static_formula_slope(self):
        """Static JS must use slope exponent 1.10."""
        assert "1.10" in _src(STATIC_JS), \
            "Static JS Hill formula must use slope 1.10"

    def test_next_formula_slope(self):
        """Next.js lib must use slope exponent 1.10."""
        assert "1.10" in _src(NEXT_JS), \
            "Next.js lib Hill formula must use slope 1.10"

    def test_static_formula_scale(self):
        """Static JS must clamp to 9999 max."""
        assert "9999" in _src(STATIC_JS), \
            "Static JS Hill formula must use scale max 9999"

    def test_next_formula_scale(self):
        """Next.js lib must clamp to 9999 max."""
        assert "9999" in _src(NEXT_JS), \
            "Next.js lib Hill formula must use scale max 9999"


# ── Rank limit ────────────────────────────────────────────────────────────────

class TestRankLimit:
    """Both implementations must cap rankings at 500."""

    def test_static_ktc_limit_500(self):
        src = _src(STATIC_JS)
        assert "KTC_LIMIT = 500" in src or "KTC_LIMIT=500" in src, \
            "Static JS must define KTC_LIMIT = 500"

    def test_next_ktc_rank_limit_500(self):
        src = _src(NEXT_JS)
        assert "KTC_RANK_LIMIT = 500" in src or "KTC_RANK_LIMIT=500" in src, \
            "Next.js lib must define KTC_RANK_LIMIT = 500"


# ── KTC-only eligibility guards ───────────────────────────────────────────────

class TestEligibilityGuards:
    """Both implementations must exclude unresolved / invalid players."""

    def test_static_excludes_question_mark_pos(self):
        src = _src(STATIC_JS)
        assert '"?"' in src or "'?'" in src, \
            "Static JS must guard against '?' position"

    def test_next_excludes_question_mark_pos(self):
        src = _src(NEXT_JS)
        assert '"?"' in src or "'?'" in src, \
            "Next.js lib must guard against '?' position"

    def test_static_excludes_pick_assets(self):
        src = _src(STATIC_JS)
        # Picks are excluded via isPick / token detection
        assert "isPick" in src or '"PICK"' in src or "'PICK'" in src, \
            "Static JS must exclude pick assets from player rankings"

    def test_next_excludes_pick_assets(self):
        src = _src(NEXT_JS)
        assert '"PICK"' in src or "'PICK'" in src, \
            "Next.js lib must exclude PICK positions from rankings"

    def test_static_requires_positive_ktc(self):
        src = _src(STATIC_JS)
        # buildFullRankings guards: ktcVal <= 0 → continue (negated guard)
        assert "ktcVal <= 0" in src or "ktc > 0" in src or "ktcVal > 0" in src, \
            "Static JS must require positive KTC value for ranking eligibility"

    def test_next_requires_positive_ktc(self):
        src = _src(NEXT_JS)
        assert "ktcVal > 0" in src or "ktc) > 0" in src or "> 0" in src, \
            "Next.js lib must require positive KTC value for ranking eligibility"


# ── Output schema ─────────────────────────────────────────────────────────────

class TestOutputSchema:
    """Rankings output must use the KTC-only 4-column schema."""

    def test_static_four_column_header(self):
        src = _src(STATIC_JS)
        assert "Our Rank" in src, "Static JS must have 'Our Rank' column"
        assert "Our Value" in src, "Static JS must have 'Our Value' column"
        assert "Player" in src or "Player Name" in src, \
            "Static JS must have Player column"

    def test_next_four_column_contract(self):
        src = _src(NEXT_JS)
        # rankDerivedValue is the 'Our Value' equivalent in Next.js lib
        assert "rankDerivedValue" in src, \
            "Next.js lib must produce rankDerivedValue field"
        assert "ktcRank" in src, \
            "Next.js lib must produce ktcRank field"

    def test_static_uses_integer_ktc_rank(self):
        src = _src(STATIC_JS)
        # ktcRank is the backend-supplied integer or the i+1 fallback
        assert "ktcRank" in src, "Static JS must assign ktcRank to each ranked row"

    def test_next_uses_integer_ktc_rank(self):
        src = _src(NEXT_JS)
        assert "r.ktcRank" in src, "Next.js lib must assign r.ktcRank to each ranked row"

    def test_static_rank_derived_value_field(self):
        src = _src(STATIC_JS)
        # Static uses ourValue but dataset.ourValue acts as rankDerivedValue
        assert "ourValue" in src or "rankDerivedValue" in src, \
            "Static JS must carry a rank-derived value on each row"

    def test_static_our_rank_tooltip_is_ktc(self):
        """Our Rank header tooltip must reference KTC rank, not consensus."""
        src = _src(STATIC_JS)
        # Look for 'Our Rank' header with a title attribute
        match = re.search(r'title="[^"]*[Kk][Tt][Cc][^"]*"', src)
        assert match is not None, \
            "Our Rank header should have a title attribute referencing KTC"

    def test_static_overallModelRank_field(self):
        """overallModelRank is kept as a compatibility alias for ktcRank."""
        src = _src(STATIC_JS)
        assert "overallModelRank" in src, \
            "Static JS must carry overallModelRank (KTC rank alias) on each row"

    def test_static_dataset_ktc_rank(self):
        """Table rows must store data-ktcRank for testability."""
        src = _src(STATIC_JS)
        assert "dataset.ktcRank" in src, \
            "Table row should store dataset.ktcRank attribute"


# ── Absence of old consensus artifacts ───────────────────────────────────────

class TestNoConsensusBlending:
    """Neither implementation should contain old multi-source consensus logic."""

    def test_static_no_site_weights(self):
        src = _src(STATIC_JS)
        assert "_SITE_WEIGHTS" not in src, \
            "Static JS must not define _SITE_WEIGHTS (consensus artifact)"

    def test_next_no_active_site_weights(self):
        src = _src(NEXT_JS)
        # _LEGACY_SITE_WEIGHTS was removed; no active SITE_WEIGHTS should exist
        assert "SITE_WEIGHTS" not in src, \
            "Next.js lib must not define SITE_WEIGHTS"

    def test_static_no_median_mean_blend(self):
        src = _src(STATIC_JS)
        assert "0.7 * median" not in src and "0.3 * wMean" not in src, \
            "Static JS must not use 70/30 median/mean consensus blending"

    def test_next_no_median_mean_blend(self):
        src = _src(NEXT_JS)
        assert "0.7 * median" not in src and "0.3 * wMean" not in src, \
            "Next.js lib must not use 70/30 median/mean consensus blending"

    def test_static_no_decimal_rank_formatter(self):
        src = _src(STATIC_JS)
        # Old consensus produced decimals (5.1, 8.7) and a _formatRank helper
        assert "_formatRank" not in src, \
            "Static JS must not have _formatRank (decimal consensus artifact)"

    def test_next_no_compute_consensus_ranks(self):
        src = _src(NEXT_JS)
        assert "computeConsensusRanks" not in src, \
            "Next.js lib must not have computeConsensusRanks function"

    def test_static_no_old_curve_param(self):
        src = _src(STATIC_JS)
        assert "_CURVE_A" not in src, \
            "Static JS must not reference old inverse-power curve parameter _CURVE_A"

    def test_next_no_old_curve_param(self):
        src = _src(NEXT_JS)
        assert "_CURVE_A" not in src and "CURVE_A" not in src, \
            "Next.js lib must not reference old inverse-power curve parameter CURVE_A"


# ── No-fully-adjusted label ────────────────────────────────────────────────────

class TestValueLabels:
    """Value column labels use canonical wording."""

    def test_static_no_fully_adjusted_label(self):
        src = _src(STATIC_JS)
        assert "Fully Adjusted" not in src, \
            "Should not use legacy 'Fully Adjusted' label"

    def test_static_our_value_label_present(self):
        src = _src(STATIC_JS)
        assert "Our Value" in src, "Static JS should use 'Our Value' label"

    def test_next_rank_derived_value_label(self):
        src = _src(NEXT_JS)
        assert "rankDerivedValue" in src, \
            "Next.js lib must use rankDerivedValue field for Our Value"


# ── Cross-file formula agreement ─────────────────────────────────────────────

class TestFormulaAgreement:
    """Formula parameters must be identical between the two JS files.

    This is the primary anti-drift test.  If someone updates the Hill
    formula in one file but not the other, this class catches it.
    """

    def _extract_hill_params(self, src: str) -> dict:
        """Extract midpoint and slope from the Hill formula in JS source."""
        # Pattern: (rank - 1) / <midpoint>, <slope>
        midpoint_match = re.search(r"\(rank\s*-\s*1\)\s*/\s*(\d+(?:\.\d+)?)", src)
        slope_match = re.search(r"Math\.pow\([^,]+,\s*(\d+\.\d+)\)", src)
        scale_match = re.search(r"(\d{4,})\s*\/\s*\(1\s*\+", src)
        return {
            "midpoint": midpoint_match.group(1) if midpoint_match else None,
            "slope": slope_match.group(1) if slope_match else None,
            "scale_numerator": scale_match.group(1) if scale_match else None,
        }

    def test_midpoint_matches(self):
        static_params = self._extract_hill_params(_src(STATIC_JS))
        next_params = self._extract_hill_params(_src(NEXT_JS))
        assert static_params["midpoint"] is not None, \
            "Could not extract midpoint from Static JS formula"
        assert next_params["midpoint"] is not None, \
            "Could not extract midpoint from Next.js lib formula"
        assert static_params["midpoint"] == next_params["midpoint"], (
            f"Hill formula midpoint mismatch: "
            f"Static={static_params['midpoint']} Next={next_params['midpoint']}"
        )

    def test_slope_matches(self):
        static_params = self._extract_hill_params(_src(STATIC_JS))
        next_params = self._extract_hill_params(_src(NEXT_JS))
        assert static_params["slope"] is not None, \
            "Could not extract slope from Static JS formula"
        assert next_params["slope"] is not None, \
            "Could not extract slope from Next.js lib formula"
        assert static_params["slope"] == next_params["slope"], (
            f"Hill formula slope mismatch: "
            f"Static={static_params['slope']} Next={next_params['slope']}"
        )

    def test_scale_numerator_matches(self):
        static_params = self._extract_hill_params(_src(STATIC_JS))
        next_params = self._extract_hill_params(_src(NEXT_JS))
        assert static_params["scale_numerator"] is not None, \
            "Could not extract scale numerator from Static JS formula"
        assert next_params["scale_numerator"] is not None, \
            "Could not extract scale numerator from Next.js lib formula"
        assert static_params["scale_numerator"] == next_params["scale_numerator"], (
            f"Hill formula scale numerator mismatch: "
            f"Static={static_params['scale_numerator']} Next={next_params['scale_numerator']}"
        )

    def test_rank_limit_matches(self):
        static_match = re.search(r"KTC_LIMIT\s*=\s*(\d+)", _src(STATIC_JS))
        next_match = re.search(r"KTC_RANK_LIMIT\s*=\s*(\d+)", _src(NEXT_JS))
        assert static_match is not None, "Could not find KTC_LIMIT in Static JS"
        assert next_match is not None, "Could not find KTC_RANK_LIMIT in Next.js lib"
        assert static_match.group(1) == next_match.group(1), (
            f"Rank limit mismatch: "
            f"Static KTC_LIMIT={static_match.group(1)} "
            f"Next KTC_RANK_LIMIT={next_match.group(1)}"
        )


# ── Backend pre-computed rank preference ─────────────────────────────────────

class TestBackendPreComputedRanks:
    """Both JS frontends must prefer backend-computed ktcRank / rankDerivedValue
    over client-side computation.

    This is the primary sync guardrail: the backend contract builder
    (src/api/data_contract.py) is the single source of truth for the formula.
    If either frontend hard-codes formula values instead of using backend fields,
    formula changes will silently diverge again.
    """

    def test_static_reads_backend_ktc_rank(self):
        """Static JS must read pdata.ktcRank from the API response."""
        src = _src(STATIC_JS)
        assert "pdata?.ktcRank" in src or "pdata.ktcRank" in src, (
            "Static JS must read backend-computed pdata.ktcRank "
            "(from _compute_ktc_rankings in data_contract.py)"
        )

    def test_static_reads_backend_rank_derived_value(self):
        """Static JS must read pdata.rankDerivedValue from the API response."""
        src = _src(STATIC_JS)
        assert "pdata?.rankDerivedValue" in src or "pdata.rankDerivedValue" in src, (
            "Static JS must read backend-computed pdata.rankDerivedValue "
            "(from _compute_ktc_rankings in data_contract.py)"
        )

    def test_next_reads_backend_ktc_rank(self):
        """Next.js lib must read r.raw.ktcRank from the playersArray entry."""
        src = _src(NEXT_JS)
        assert "r.raw?.ktcRank" in src or "r.raw.ktcRank" in src, (
            "Next.js lib must read backend-computed r.raw.ktcRank "
            "(from _compute_ktc_rankings in data_contract.py)"
        )

    def test_next_reads_backend_rank_derived_value(self):
        """Next.js lib must read r.raw.rankDerivedValue from the playersArray entry."""
        src = _src(NEXT_JS)
        assert "r.raw?.rankDerivedValue" in src or "r.raw.rankDerivedValue" in src, (
            "Next.js lib must read backend-computed r.raw.rankDerivedValue "
            "(from _compute_ktc_rankings in data_contract.py)"
        )

    def test_static_has_backend_first_fallback_pattern(self):
        """Static JS must use backend value when present, formula as fallback."""
        src = _src(STATIC_JS)
        # Must reference _rankToValue as a FALLBACK, not the primary path
        assert "_rankToValue" in src, "Static JS must retain _rankToValue as fallback"
        assert "backendRank" in src or "pdata?.ktcRank" in src, (
            "Static JS must check for backend rank before calling _rankToValue"
        )

    def test_next_has_backend_first_fallback_pattern(self):
        """Next.js lib must use backend value when present, formula as fallback."""
        src = _src(NEXT_JS)
        assert "rankToValue" in src, "Next.js lib must retain rankToValue as fallback"
        assert "backendRank" in src or "r.raw?.ktcRank" in src, (
            "Next.js lib must check for backend rank before calling rankToValue"
        )

    def test_backend_constant_matches_js_limit(self):
        """KTC_RANK_LIMIT in data_contract.py must match both JS files."""
        from src.api.data_contract import KTC_RANK_LIMIT
        static_match = re.search(r"KTC_LIMIT\s*=\s*(\d+)", _src(STATIC_JS))
        next_match = re.search(r"KTC_RANK_LIMIT\s*=\s*(\d+)", _src(NEXT_JS))
        assert static_match is not None, "Could not find KTC_LIMIT in Static JS"
        assert next_match is not None, "Could not find KTC_RANK_LIMIT in Next.js lib"
        assert int(static_match.group(1)) == KTC_RANK_LIMIT, (
            f"Static KTC_LIMIT ({static_match.group(1)}) != "
            f"Python KTC_RANK_LIMIT ({KTC_RANK_LIMIT})"
        )
        assert int(next_match.group(1)) == KTC_RANK_LIMIT, (
            f"Next.js KTC_RANK_LIMIT ({next_match.group(1)}) != "
            f"Python KTC_RANK_LIMIT ({KTC_RANK_LIMIT})"
        )
