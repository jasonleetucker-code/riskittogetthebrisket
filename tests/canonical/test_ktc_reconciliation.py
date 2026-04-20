"""KTC reconciliation regression tests.

Pins the divergence between our canonical Hill-curve rank-to-value
mapping and KeepTradeCut's live value curve, so that any drift in
either direction surfaces as a test failure instead of silently shifting
production rankings.

The curves DO NOT match identically by design — KTC's proprietary curve
is just one of several blended market sources in our consensus rank
(see ``HILL_MIDPOINT`` / ``HILL_SLOPE`` in ``player_valuation.py``,
fit as the mean across KTC, IDPTradeCalc, DynastyNerds, DynastyDaddy).
What this test pins is the *size* of the divergence at key ranks, using
invariant tolerance bands rather than exact pins so normal daily KTC
scrape drift does not break CI — the same philosophy as PR #154 applied
to anchor player values.

When the pinned pct_diff band fails, either:
  1. KTC drifted beyond band (rare — their curve is notoriously stable), or
  2. We re-fit the Hill curve (via scripts/fit_hill_curve_from_market.py)
     and need to re-baseline the pinned values below.

The KTC fixture is the live offense-vet snapshot at
``CSVs/site_raw/ktc.csv``.  Picks (rows like "2026 Early 1st") are
filtered out so the rank index reflects player ordering only.
"""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.canonical.player_valuation import rank_to_value


KTC_CSV = REPO / "CSVs" / "site_raw" / "ktc.csv"
_PICK_PATTERN = re.compile(r"^\d{4}\s+(Early|Mid|Late)\s+\d", re.IGNORECASE)


def _load_ktc_players_sorted() -> list[tuple[str, int]]:
    """Return KTC player rows sorted by value descending.

    Filters draft picks out so that rank 1 = top player by KTC value.
    """
    rows: list[tuple[str, int]] = []
    with KTC_CSV.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = (row.get("name") or "").strip()
            raw_value = (row.get("value") or "").strip()
            if not name or not raw_value:
                continue
            if _PICK_PATTERN.match(name):
                continue
            try:
                value = int(raw_value)
            except ValueError:
                continue
            rows.append((name, value))
    rows.sort(key=lambda r: -r[1])
    return rows


# ──────────────────────────────────────────────────────────────────────
# Pinned deltas — our Hill curve vs KTC at key ranks.
#
# Each entry: (rank, ours_expected, pct_diff_band_center).
# Baselined 2026-04-20 against CSVs/site_raw/ktc.csv.
#
# ``ours_expected`` is the exact integer ``rank_to_value(rank)`` output.
# Because ``rank_to_value`` is pure and deterministic in the Hill
# constants, changing it is a deliberate act and must re-baseline here.
#
# ``pct_diff_band_center`` is the expected (ours − ktc) / ktc × 100
# at that rank.  Tolerance ``DELTA_TOLERANCE_PP`` is applied symmetrically
# around the band center — wide enough (±5pp) to absorb ordinary daily
# KTC scrape drift, narrow enough to catch a real curve shape change.
# ──────────────────────────────────────────────────────────────────────
PINNED_DELTAS: list[tuple[int, int, float]] = [
    # rank, ours (exact), pct_diff band center
    (1,   9999,   0.0),
    (5,   9460,  -1.8),
    (12,  8459,   8.4),
    (24,  7017,   3.8),
    (50,  4967,  -3.6),
    (100, 3055, -15.4),
    (150, 2157, -24.0),
    (200, 1648, -31.9),
    (300, 1100, -32.5),
    (400,  815, -19.2),
]

# Tolerance band around pinned pct_diff, in absolute percentage points.
# ±5pp is wide enough to absorb normal daily KTC scrape drift (their
# daily changes typically sit well under ±2pp at most ranks) while
# still tight enough to catch a real curve-shape regression.
DELTA_TOLERANCE_PP = 5.0


@pytest.fixture(scope="module")
def ktc_players() -> list[tuple[str, int]]:
    if not KTC_CSV.exists():
        pytest.skip(f"KTC fixture missing at {KTC_CSV}")
    players = _load_ktc_players_sorted()
    if len(players) < 400:
        pytest.skip(f"KTC fixture too small ({len(players)} players, need >= 400)")
    return players


class TestKTCReconciliation:
    """Pin our Hill curve's divergence from KTC at key ranks."""

    @pytest.mark.parametrize("rank,pinned_ours,pinned_pct", PINNED_DELTAS)
    def test_rank_delta_within_tolerance(
        self,
        ktc_players: list[tuple[str, int]],
        rank: int,
        pinned_ours: int,
        pinned_pct: float,
    ) -> None:
        _, ktc_value = ktc_players[rank - 1]
        ours = rank_to_value(rank)

        # Our curve is deterministic — any change to HILL_MIDPOINT/
        # HILL_SLOPE is intentional and should require re-baselining
        # this test.  Pin exactly.
        assert ours == pinned_ours, (
            f"Our Hill curve at rank {rank} changed: {pinned_ours} -> {ours}. "
            f"Re-baseline PINNED_DELTAS if this was intentional "
            f"(e.g. re-fit via scripts/fit_hill_curve_from_market.py)."
        )

        # KTC's curve wiggles with their daily scrape.  Keep the
        # divergence within ±DELTA_TOLERANCE_PP of the pinned center.
        actual_pct = 100.0 * (ours - ktc_value) / ktc_value
        assert abs(actual_pct - pinned_pct) <= DELTA_TOLERANCE_PP, (
            f"Divergence from KTC at rank {rank} drifted: "
            f"pinned {pinned_pct:+.1f}% vs actual {actual_pct:+.1f}% "
            f"(KTC={ktc_value}, ours={ours}, band ±{DELTA_TOLERANCE_PP:.1f}pp). "
            f"Investigate whether KTC shifted or our curve needs re-fitting."
        )


class TestKTCCurveShapeInvariants:
    """Pin the qualitative shape of the KTC/ours divergence.

    These invariants describe *how* our curve differs from KTC and are
    independent of the specific pinned numbers above.  They should hold
    until the Hill curve is re-fit.
    """

    def test_rank_one_matches_by_construction(
        self, ktc_players: list[tuple[str, int]]
    ) -> None:
        # Both curves anchor at ~9999 at rank 1.
        _, ktc_top = ktc_players[0]
        ours_top = rank_to_value(1)
        assert abs(ours_top - ktc_top) <= 5

    def test_midrange_is_higher_than_ktc(
        self, ktc_players: list[tuple[str, int]]
    ) -> None:
        # Ranks 10-15 — our curve sits above KTC (their curve dips
        # faster through the early top-12).
        for rank in range(10, 16):
            _, ktc = ktc_players[rank - 1]
            ours = rank_to_value(rank)
            assert ours > ktc, (
                f"Expected our curve above KTC at rank {rank}, "
                f"got ours={ours}, ktc={ktc}"
            )

    def test_tail_is_compressed_vs_ktc(
        self, ktc_players: list[tuple[str, int]]
    ) -> None:
        # Past rank 100, our Hill curve compresses more aggressively
        # than KTC's — this is the primary known divergence and should
        # remain visible until the curve is re-fit.
        for rank in (100, 150, 200, 300):
            _, ktc = ktc_players[rank - 1]
            ours = rank_to_value(rank)
            assert ours < ktc, (
                f"Expected our curve below KTC at rank {rank}, "
                f"got ours={ours}, ktc={ktc}"
            )

    def test_aggregate_tail_gap_is_material(
        self, ktc_players: list[tuple[str, int]]
    ) -> None:
        # Sanity: the average tail divergence (ranks 100-300) should
        # be at least 15% below KTC.  If this collapses, either KTC
        # changed shape or we re-fit the curve — either way,
        # re-baseline the test.
        deltas: list[float] = []
        for rank in range(100, 301, 25):
            _, ktc = ktc_players[rank - 1]
            ours = rank_to_value(rank)
            deltas.append(100.0 * (ours - ktc) / ktc)
        avg = sum(deltas) / len(deltas)
        assert avg <= -15.0, (
            f"Tail divergence collapsed: avg pct diff = {avg:+.1f}% "
            f"(expected <= -15%). Re-baseline if curve was re-fit."
        )
