"""Cross-check that the Next.js frontend materializes backend-authored
ranking fields without running its own ranking engine.

  1. Python backend: src/api/data_contract.py (_compute_unified_rankings)
  2. Next.js frontend: frontend/lib/dynasty-data.js (buildRows — materializer only)

Historically both implementations ran the same Hill-curve blend in
parallel so drift between the two was a real risk; these tests
originally pinned the formula constants, rank limits, and fallback
path.  As of the 2026-04-15 fallback removal, the frontend is a pure
materializer — there is no ``rankToValue``, no ``computeUnifiedRanks``,
and no ``OVERALL_RANK_LIMIT`` in the JS bundle anymore.  The only
ranking symbol the frontend exposes is ``canonicalConsensusRank``
(which it reads from the backend contract) and ``resolvedRank`` (a
pure accessor).

The tests below now pin the INVERSE invariant: the frontend lib must
NOT carry any of the removed symbols.  If someone reintroduces a
client-side ranking engine these assertions fail loudly.
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


def _strip_comments(src: str) -> str:
    """Remove // line comments and /* ... */ block comments from a JS source.

    Used by the fallback-removal assertions below so a mention of a
    removed identifier inside an explanatory comment is not treated
    as a regression.  We only care about active code references.
    """
    # Block comments first (non-greedy).
    src = re.sub(r"/\*[\s\S]*?\*/", "", src)
    # Then line comments (up to end of line).
    src = re.sub(r"//[^\n]*", "", src)
    return src


# ── Fallback removal guarantee ────────────────────────────────────────────────

class TestFallbackRemoved:
    """The frontend ranking fallback was removed; verify the symbols are gone.

    These assertions strip comments before checking so an explanatory
    mention of a removed identifier in a doc comment is NOT treated as
    a regression — only active code references fail.
    """

    def test_rank_to_value_is_not_exported(self):
        src = _strip_comments(_src(NEXT_JS))
        assert "export function rankToValue" not in src
        assert "rankToValue(" not in src, (
            "frontend/lib/dynasty-data.js must not invoke rankToValue — "
            "the backend is the sole ranking engine"
        )

    def test_compute_unified_ranks_is_removed(self):
        src = _strip_comments(_src(NEXT_JS))
        assert "computeUnifiedRanks" not in src, (
            "frontend/lib/dynasty-data.js must not define computeUnifiedRanks — "
            "the fallback was removed"
        )

    def test_non_canonical_fallback_symbol_is_removed(self):
        src = _strip_comments(_src(NEXT_JS))
        assert "NON_CANONICAL_FALLBACK" not in src, (
            "NON_CANONICAL_FALLBACK marker must not be present"
        )

    def test_overall_rank_limit_constant_is_removed(self):
        src = _strip_comments(_src(NEXT_JS))
        # The cap lives exclusively in the backend now; the frontend
        # trusts the backend's enforcement and never imports it.
        assert "OVERALL_RANK_LIMIT" not in src


# ── Backend-authoritative row materialization ────────────────────────────────

class TestBackendAuthoritative:
    """The frontend must read backend-stamped rank/value fields verbatim."""

    def test_reads_backend_canonical_consensus_rank(self):
        src = _src(NEXT_JS)
        assert "canonicalConsensusRank" in src, (
            "Next.js lib must read backend-computed canonicalConsensusRank"
        )

    def test_reads_backend_rank_derived_value(self):
        src = _src(NEXT_JS)
        assert "rankDerivedValue" in src, (
            "Next.js lib must read backend-computed rankDerivedValue"
        )

    def test_build_rows_is_pure_materializer(self):
        src = _src(NEXT_JS)
        # ``buildRows`` must be defined and exported.
        assert "export function buildRows" in src


# ── Python Hill-curve spot check (backend-only) ──────────────────────────────

class TestBackendFormulaIntact:
    """The backend rank-to-value curve is the single source of truth."""

    def test_python_hill_curve_anchors(self):
        from src.canonical.player_valuation import rank_to_value
        assert rank_to_value(1) == 9999, "Rank 1 must produce 9999"
        assert rank_to_value(0) == 0, "Rank 0 must produce 0"
        mid = rank_to_value(45)
        assert 4900 <= mid <= 5100, f"Rank 45 (midpoint) produced {mid}, expected ~5000"


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
