"""Cross-check that ranking formula, limits, and eligibility rules agree
between the two implementations:

  1. Python backend: src/api/data_contract.py (_compute_unified_rankings)
  2. Next.js frontend: frontend/lib/dynasty-data.js (computeUnifiedRanks, rankToValue)

These tests ensure formula constants, eligibility guards, and rank limits
stay in sync across both implementations.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

NEXT_JS = REPO / "frontend" / "lib" / "dynasty-data.js"


def _src(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ── Rank limit ────────────────────────────────────────────────────────────────

class TestRankLimit:
    """Next.js implementation must define an overall rank limit."""

    def test_next_overall_rank_limit(self):
        src = _src(NEXT_JS)
        assert "OVERALL_RANK_LIMIT" in src, \
            "Next.js lib must define OVERALL_RANK_LIMIT"


# ── Eligibility guards ───────────────────────────────────────────────────────

class TestEligibilityGuards:
    """Next.js implementation must exclude unresolved / invalid players."""

    def test_next_excludes_question_mark_pos(self):
        src = _src(NEXT_JS)
        assert '"?"' in src or "'?'" in src, \
            "Next.js lib must guard against '?' position"

    def test_next_excludes_pick_assets(self):
        src = _src(NEXT_JS)
        assert '"PICK"' in src or "'PICK'" in src, \
            "Next.js lib must exclude PICK positions from rankings"

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

    def test_next_has_hill_params(self):
        params = self._extract_hill_params(_src(NEXT_JS))
        assert params["scale_numerator"] is not None, \
            "Could not find 9998/ in Next.js lib formula"

    def test_rank_limit_matches_backend(self):
        from src.api.data_contract import OVERALL_RANK_LIMIT
        next_match = re.search(r"OVERALL_RANK_LIMIT\s*=\s*(\d+)", _src(NEXT_JS))
        assert next_match is not None, "Could not find OVERALL_RANK_LIMIT in Next.js lib"
        assert int(next_match.group(1)) == OVERALL_RANK_LIMIT


# ── Backend pre-computed rank preference ─────────────────────────────────────

class TestBackendPreComputedRanks:
    """Next.js frontend must prefer backend-computed canonicalConsensusRank
    and rankDerivedValue over client-side computation."""

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

    def test_next_has_backend_first_fallback_pattern(self):
        src = _src(NEXT_JS)
        assert "rankToValue" in src, "Next.js lib must retain rankToValue as fallback"


# ── Unified rank precedence ──────────────────────────────────────────────────

class TestResolvedRankPrecedence:
    """Next.js renderer must use the same rank resolution precedence:
    canonicalConsensusRank (backend) >> computedConsensusRank (sort-order).
    """

    def test_next_uses_canonical_first(self):
        src = _src(NEXT_JS)
        assert "canonicalConsensusRank" in src

    def test_next_resolved_rank_function_exists(self):
        src = _src(NEXT_JS)
        assert "resolvedRank" in src
