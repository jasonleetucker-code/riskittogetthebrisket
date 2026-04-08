"""Cross-check that ranking formula, limits, and eligibility rules agree
between the three implementations:

  1. Python backend: src/api/data_contract.py (_compute_unified_rankings)
  2. Next.js frontend: frontend/lib/dynasty-data.js (computeUnifiedRanks, rankToValue)
  3. Static frontend: Static/js/runtime/10-rankings-and-picks.js (buildFullRankings, _rankToValue)

These tests ensure formula constants, eligibility guards, and rank limits
stay in sync across all three implementations.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

STATIC_JS = REPO / "Static" / "js" / "runtime" / "10-rankings-and-picks.js"
NEXT_JS = REPO / "frontend" / "lib" / "dynasty-data.js"


def _src(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ── Rank limit ────────────────────────────────────────────────────────────────

class TestRankLimit:
    """Both implementations must define an overall rank limit."""

    def test_static_overall_limit(self):
        src = _src(STATIC_JS)
        assert "OVERALL_LIMIT" in src, \
            "Static JS must define OVERALL_LIMIT"

    def test_next_overall_rank_limit(self):
        src = _src(NEXT_JS)
        assert "OVERALL_RANK_LIMIT" in src, \
            "Next.js lib must define OVERALL_RANK_LIMIT"


# ── Eligibility guards ───────────────────────────────────────────────────────

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
        assert "isPick" in src or '"PICK"' in src or "'PICK'" in src, \
            "Static JS must exclude pick assets from player rankings"

    def test_next_excludes_pick_assets(self):
        src = _src(NEXT_JS)
        assert '"PICK"' in src or "'PICK'" in src, \
            "Next.js lib must exclude PICK positions from rankings"

    def test_static_checks_source_values(self):
        src = _src(STATIC_JS)
        assert "sourceVals" in src or "SOURCE_KEYS" in src, \
            "Static JS must check for positive source values for ranking eligibility"

    def test_next_checks_source_values(self):
        src = _src(NEXT_JS)
        assert "canonicalSites" in src, \
            "Next.js lib must check canonicalSites for ranking eligibility"


# ── Hill-curve formula agreement ──────────────────────────────────────────────

class TestFormulaAgreement:
    """The rank-to-value formula must be identical across implementations."""

    _HILL_PATTERNS = {
        "scale_numerator": re.compile(r"9998\s*[/÷]"),
        "midpoint": re.compile(r"[\(/ ]45[.,)\s]"),
        "slope": re.compile(r"1\.10|1\.1[^0-9]"),
    }

    def _extract_hill_params(self, src: str) -> dict[str, str | None]:
        out = {}
        for name, pat in self._HILL_PATTERNS.items():
            m = pat.search(src)
            out[name] = m.group() if m else None
        return out

    def test_python_formula_matches_js(self):
        from src.canonical.player_valuation import rank_to_value
        assert rank_to_value(1) == 9999, "Rank 1 must produce 9999"
        assert rank_to_value(0) == 0, "Rank 0 must produce 0"
        mid = rank_to_value(45)
        assert 4900 <= mid <= 5100, f"Rank 45 (midpoint) produced {mid}, expected ~5000"

    def test_static_has_hill_params(self):
        params = self._extract_hill_params(_src(STATIC_JS))
        assert params["scale_numerator"] is not None, \
            "Could not find 9998/ in Static JS formula"

    def test_next_has_hill_params(self):
        params = self._extract_hill_params(_src(NEXT_JS))
        assert params["scale_numerator"] is not None, \
            "Could not find 9998/ in Next.js lib formula"

    def test_formula_constants_match(self):
        static_params = self._extract_hill_params(_src(STATIC_JS))
        next_params = self._extract_hill_params(_src(NEXT_JS))
        assert static_params["scale_numerator"] is not None
        assert next_params["scale_numerator"] is not None
        assert static_params["scale_numerator"] == next_params["scale_numerator"]

    def test_rank_limit_matches(self):
        static_match = re.search(r"OVERALL_LIMIT\s*=\s*(\d+)", _src(STATIC_JS))
        next_match = re.search(r"OVERALL_RANK_LIMIT\s*=\s*(\d+)", _src(NEXT_JS))
        assert static_match is not None, "Could not find OVERALL_LIMIT in Static JS"
        assert next_match is not None, "Could not find OVERALL_RANK_LIMIT in Next.js lib"
        assert static_match.group(1) == next_match.group(1), (
            f"Rank limit mismatch: "
            f"Static OVERALL_LIMIT={static_match.group(1)} "
            f"Next OVERALL_RANK_LIMIT={next_match.group(1)}"
        )

    def _extract_formula_body(self, src: str, fn_name: str) -> str:
        pat = re.compile(
            r"function\s+" + re.escape(fn_name) + r"\s*\([^)]*\)\s*\{([^}]+)\}",
            re.DOTALL,
        )
        m = pat.search(src)
        assert m is not None, f"Could not find function {fn_name} in source"
        return re.sub(r"\s+", " ", m.group(1).strip())

    def test_fallback_formula_bodies_are_identical(self):
        static_body = self._extract_formula_body(_src(STATIC_JS), "_rankToValue")
        next_body = self._extract_formula_body(_src(NEXT_JS), "rankToValue")
        assert static_body == next_body, (
            "Fallback formula bodies diverged between Static JS and Next.js lib.\n"
            f"  Static (_rankToValue): {static_body}\n"
            f"  Next   (rankToValue):  {next_body}\n"
        )


# ── Backend pre-computed rank preference ─────────────────────────────────────

class TestBackendPreComputedRanks:
    """Both JS frontends must prefer backend-computed canonicalConsensusRank
    and rankDerivedValue over client-side computation."""

    def test_static_reads_backend_rank(self):
        src = _src(STATIC_JS)
        assert "_canonicalConsensusRank" in src, (
            "Static JS must read backend-computed _canonicalConsensusRank"
        )

    def test_static_reads_backend_rank_derived_value(self):
        src = _src(STATIC_JS)
        assert "rankDerivedValue" in src, (
            "Static JS must read backend-computed rankDerivedValue"
        )

    def test_next_reads_backend_rank(self):
        src = _src(NEXT_JS)
        assert "canonicalConsensusRank" in src, (
            "Next.js lib must read backend-computed canonicalConsensusRank"
        )

    def test_next_reads_backend_rank_derived_value(self):
        src = _src(NEXT_JS)
        assert "rankDerivedValue" in src, (
            "Next.js lib must read backend-computed rankDerivedValue"
        )

    def test_static_has_backend_first_fallback_pattern(self):
        src = _src(STATIC_JS)
        assert "_rankToValue" in src, "Static JS must retain _rankToValue as fallback"

    def test_next_has_backend_first_fallback_pattern(self):
        src = _src(NEXT_JS)
        assert "rankToValue" in src, "Next.js lib must retain rankToValue as fallback"

    def test_backend_constant_matches_js_limit(self):
        from src.api.data_contract import OVERALL_RANK_LIMIT
        static_match = re.search(r"OVERALL_LIMIT\s*=\s*(\d+)", _src(STATIC_JS))
        next_match = re.search(r"OVERALL_RANK_LIMIT\s*=\s*(\d+)", _src(NEXT_JS))
        assert static_match is not None, "Could not find OVERALL_LIMIT in Static JS"
        assert next_match is not None, "Could not find OVERALL_RANK_LIMIT in Next.js lib"
        assert int(static_match.group(1)) == OVERALL_RANK_LIMIT
        assert int(next_match.group(1)) == OVERALL_RANK_LIMIT


# ── Unified rank precedence ──────────────────────────────────────────────────

class TestResolvedRankPrecedence:
    """Both renderers must use the same rank resolution precedence:
    canonicalConsensusRank (backend) >> computedConsensusRank (sort-order).
    """

    def test_static_uses_canonical_first(self):
        src = _src(STATIC_JS)
        assert "canonicalConsensusRank" in src

    def test_next_uses_canonical_first(self):
        src = _src(NEXT_JS)
        assert "canonicalConsensusRank" in src

    def test_next_resolved_rank_function_exists(self):
        src = _src(NEXT_JS)
        assert "resolvedRank" in src

    def test_static_resolved_rank_exists(self):
        src = _src(STATIC_JS)
        assert "resolvedRank" in src or "_resolvedRank" in src
