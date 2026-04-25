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

from src.canonical.player_valuation import (
    percentile_to_value,
    rank_to_value,  # kept for shape invariants
)
from src.api.data_contract import _PERCENTILE_REFERENCE_N


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
# Each entry: (rank, ours_expected, pct_diff_band_center, tolerance_pp).
# Baselined 2026-04-20 against CSVs/site_raw/ktc.csv after the Final
# Framework PR 3 transition to percentile-input Hill.
#
# ``ours_expected`` is the exact integer
# ``percentile_to_value(p)`` output where
# ``p = (rank − 1) / (_PERCENTILE_REFERENCE_N − 1)``.  Because
# ``percentile_to_value`` is deterministic in HILL_PERCENTILE_C/S,
# changing those constants is a deliberate act and must re-baseline
# the test.
#
# ``pct_diff_band_center`` is the expected (ours − ktc) / ktc × 100
# at that rank.  ``tolerance_pp`` is the symmetric band half-width.
#
# Tolerances are tiered per the KTC volatility backtest
# (``scripts/backtest_ktc_volatility.py``, see
# ``reports/ktc_volatility_backtest_full.md``) across 25 daily
# snapshots.  Day-over-day KTC drift (independent of our Hill):
#
#   ranks 1–50    max dod ≈ 0.64pp → ±3pp  (slightly wider than the
#                                           rank-Hill version because
#                                           the percentile fit tracks
#                                           mid-top differently)
#   ranks 100–150 max dod ≈ 1.04pp → ±3pp
#   ranks 200–400 max dod ≈ 8.36pp → ±10pp
#
# A structural KTC tail shift larger than these bands is a signal, not
# a regression — break CI, investigate, re-baseline the affected ranks.
# ──────────────────────────────────────────────────────────────────────
PINNED_DELTAS: list[tuple[int, int, float, float]] = [
    (  1, 9999,   0.0,  3.0),
    (  5, 9577,  -0.6,  3.0),
    ( 12, 8748,  12.3,  3.0),
    ( 24, 7474,  11.0,  3.0),
    ( 50, 5508,   6.6,  3.0),
    (100, 3508,  -3.0,  5.0),
    (150, 2513, -11.5,  5.0),
    (200, 1933, -20.4, 10.0),
    (300, 1298, -19.4, 10.0),
    (400,  963,  -3.7, 10.0),
]


def _ours(rank: int) -> int:
    """Return the expected live value at ``rank`` under the Final
    Framework percentile Hill, using the same reference pool size
    (``_PERCENTILE_REFERENCE_N``) as ``_compute_unified_rankings``.
    """
    if _PERCENTILE_REFERENCE_N < 2:
        return 9999
    p = (rank - 1) / (_PERCENTILE_REFERENCE_N - 1)
    return int(percentile_to_value(p))


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

    @pytest.mark.parametrize("rank,pinned_ours,pinned_pct,tolerance_pp", PINNED_DELTAS)
    def test_rank_delta_within_tolerance(
        self,
        ktc_players: list[tuple[str, int]],
        rank: int,
        pinned_ours: int,
        pinned_pct: float,
        tolerance_pp: float,
    ) -> None:
        _, ktc_value = ktc_players[rank - 1]
        ours = _ours(rank)

        # Our curve is deterministic — any change to HILL_PERCENTILE_C
        # / HILL_PERCENTILE_S is intentional and should require
        # re-baselining this test.  Pin exactly.
        assert ours == pinned_ours, (
            f"Our Hill curve at rank {rank} changed: {pinned_ours} -> {ours}. "
            f"Re-baseline PINNED_DELTAS if this was intentional "
            f"(e.g. re-fit via scripts/fit_hill_curve_percentile.py)."
        )

        # KTC's curve wiggles with their daily scrape.  Tier-specific
        # tolerance (see PINNED_DELTAS doc block) — tight at the stable
        # top of board, wide at the actively-drifting deep tail.
        actual_pct = 100.0 * (ours - ktc_value) / ktc_value
        assert abs(actual_pct - pinned_pct) <= tolerance_pp, (
            f"Divergence from KTC at rank {rank} drifted: "
            f"pinned {pinned_pct:+.1f}% vs actual {actual_pct:+.1f}% "
            f"(KTC={ktc_value}, ours={ours}, band ±{tolerance_pp:.1f}pp). "
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
        # Both curves anchor at ~9999 at rank 1.  Our Hill ceiling
        # is exactly 9999 by construction; KTC's actual top varies
        # depending on scrape timing — their #1 player occasionally
        # sits a few dozen points below 9999 when the market shifts
        # between updates.  Observed range is ~9970-9999 over 6
        # months of data, so ≤25 (=0.25% of the scale) gives normal
        # market drift breathing room without weakening the
        # invariant that rank-1 anchors at the top of the curve.
        _, ktc_top = ktc_players[0]
        ours_top = _ours(1)
        assert abs(ours_top - ktc_top) <= 25

    def test_midrange_is_higher_than_ktc(
        self, ktc_players: list[tuple[str, int]]
    ) -> None:
        # Ranks 10-15 — our percentile-Hill curve sits above KTC
        # (their curve dips faster through the early top-12 than
        # the fitted Hill shape).
        for rank in range(10, 16):
            _, ktc = ktc_players[rank - 1]
            ours = _ours(rank)
            assert ours > ktc, (
                f"Expected our curve above KTC at rank {rank}, "
                f"got ours={ours}, ktc={ktc}"
            )

    def test_tail_stays_bounded_vs_ktc(
        self, ktc_players: list[tuple[str, int]]
    ) -> None:
        # Past rank 100, the divergence from KTC stays within ±40pp.
        # Our offense master curve is the unweighted mean of KTC, DD,
        # and DN per-source fits; DD and DN have steeper tails than
        # KTC, so the master compresses the deep tail relative to KTC.
        # The bound permits this consensus divergence without flagging.
        for rank in (100, 150, 200, 300, 400):
            _, ktc = ktc_players[rank - 1]
            ours = _ours(rank)
            pct = abs(100.0 * (ours - ktc) / ktc)
            assert pct <= 40.0, (
                f"Divergence at rank {rank} too large: "
                f"ours={ours}, ktc={ktc}, |pct|={pct:.1f}%"
            )
