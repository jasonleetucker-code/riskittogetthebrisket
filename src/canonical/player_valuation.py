"""Canonical rank/percentile → value curves and rank-gap tier detection.

SCOPE NOTE (2026-07-29).  This module used to also carry the engine for
the retired offline canonical-build path — a six-step pipeline
(``run_valuation``) with its own consensus-rank blend, tier-cliff
injection, volatility compression and ``PlayerInput`` /
``PlayerValuation`` / ``ValuationResult`` dataclasses, plus the adapter
bridges (``build_player_inputs_from_*``,
``valuation_result_to_asset_dicts``) that fed it.  That path was retired
alongside ``scripts/canonical_build.py``, ``src/canonical/transform.py``
and ``src/canonical/pipeline.py``; the engine outlived its callers and
was verified to have zero production importers (only its own tests and a
re-export in ``src/canonical/__init__.py``).  It was deleted on
2026-07-29 as part of the repository dead-code audit.

What remains — and what this module is now responsible for — is the
shared curve + tiering primitives that the LIVE pipeline calls:

* ``rank_to_value`` / ``rank_to_value_for_scope`` — the legacy rank-form
  Hill curve, used only on RECONSTRUCTION/FALLBACK paths
  (``src/api/rank_history.py``, ``src/api/terminal.py``).
* ``percentile_to_value`` + the scope-level percentile Hill constants —
  step 2→3 of the live "Final Framework" blend in
  ``src/api/data_contract.py::_compute_unified_rankings``.  The eight
  ``HILL_*_PERCENTILE_C/S`` constants are read and rewritten textually
  by ``src/model_registry/hill_masters.py``; keep their declarations on
  a single ``NAME: float = <number>`` line.
* ``detect_tiers`` (+ ``TierBoundary``, ``_rolling_median``) —
  rolling-median rank-gap tier detection, imported at runtime by
  ``data_contract.py``.

Live values are NOT produced here.  This module supplies curves; the
blend that decides a player's value lives in ``data_contract.py``.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Sequence


# ══════════════════════════════════════════════════════════════════════
# HYPERPARAMETERS — all tunables collected here for easy iteration
# ══════════════════════════════════════════════════════════════════════

# Tier detection
TIER_GAP_WINDOW: int = 7  # rolling-median window (each side)
TIER_GAP_THRESHOLD: float = 2.0  # gap_score above this triggers a break
TIER_MIN_SIZE: int = 3  # minimum players in a tier before allowing split

# Rank-form value curve — Hill-style, rank 1 always = 9999
# value = 1 + 9998 / (1 + ((rank - 1) / midpoint)^slope)
# Mirrors the JS rankToValue in frontend/lib/dynasty-data.js.
#
# Constants are the simple mean of per-source Hill-curve fits across
# the four value-emitting market sources — KTC, IDPTradeCalc,
# DynastyNerds (SF TEP), DynastyDaddy (SF) — each normalised so its
# top player = 9999 before fitting. Re-run
# ``scripts/fit_hill_curve_from_market.py`` when the community's
# dropoff shape drifts from ours and update the constants here.
HILL_MIDPOINT: float = 48.44  # rank at which value decay inflects
HILL_SLOPE: float = 1.149  # controls steepness of decay

# IDP-specific Hill curve.  Dynasty IDP markets price differently from
# offense: the #1 LB is nowhere near 2x the #2 the way the #1 QB is,
# and values decay more slowly through the long tail (mid-/deep-
# roster IDP players are more fungible than the equivalent offensive
# skill-position players).  Fit via
# ``scripts/fit_hill_curve_from_market.py --universe idp`` against
# IDPTradeCalc's raw IDP slice of its combined offense+IDP pool — the
# retail IDP authority whose per-rank values the blend should
# reproduce at the Hill step, BEFORE any per-position IDP calibration
# multiplier is applied.  Previous fit anchored on FantasyPros IDP
# ``normalizedValue`` which produced values ~600-1,000 below IDPTC
# across the top-250 IDP rows; the new fit is RMSE ~170 across 376
# IDP rows in the live snapshot.  Re-run the fit and update these
# constants when the IDPTC dropoff shape drifts.
IDP_HILL_MIDPOINT: float = 69.50
IDP_HILL_SLOPE: float = 0.945

# Final Framework step 2-3: percentile-input Hill curves, one per scope.
#
#     p = (r − 1) / (N − 1)
#     V(p) = 9999 / (1 + (p / c)^s)
#
# Updated framework (2026-04-20) uses SCOPE-LEVEL master curves built
# via per-source fits + trimmed mean-median combination, not a pooled
# fit across all value sources.  See ``scripts/fit_hill_curve_percentile.py``.
#
# GLOBAL master — fit from the anchor's combined offense+IDP pool
# (currently IDPTradeCalc only; the only source with dual-universe
# coverage).  Used for the anchor source's contributions to every
# player, regardless of position.
HILL_GLOBAL_PERCENTILE_C: float = 0.1130
HILL_GLOBAL_PERCENTILE_S: float = 0.870
#
# OFFENSE master — fit from offense-only value sources (KTC,
# DynastyDaddy, DynastyNerds).  Used for every offense-scope source's
# contributions (KTC, DLF SF, Dynasty Nerds, FantasyPros SF, Dynasty
# Daddy, Flock Fantasy, FootballGuys SF, Yahoo/Boone, DraftSharks,
# DLF Rookie SF).
HILL_PERCENTILE_C: float = 0.1180
HILL_PERCENTILE_S: float = 1.170
#
# IDP master — fit from IDPTradeCalc's IDP slice (the only value-
# based IDP source).  Used for every IDP-scope source's contributions
# (DLF IDP, FantasyPros IDP, FootballGuys IDP, DLF Rookie IDP,
# DraftSharks IDP).
IDP_HILL_PERCENTILE_C: float = 0.0930
IDP_HILL_PERCENTILE_S: float = 0.970
#
# ROOKIE master — fit from KTC + IDPTC rookie slices of the latest
# snapshot.
#
# NOT ROUTED.  This curve is refit weekly by
# ``.github/workflows/refit-hill-curves.yml`` but no live code path
# selects it: ``data_contract.py::_curve_for_source`` routes
# cross-market -> GLOBAL, overall_idp -> IDP, and everything else
# (offense AND picks) -> OFFENSE.  Rookie-only sources ladder-translate
# their rank into combined-pool space *before* reaching that function,
# so the OFFENSE/IDP master is the correct curve by the time they get
# there.  ``_build_hill_curves_block`` stamps ``routed: false`` on this
# entry accordingly, and CLAUDE.md describes it as refit tooling only.
#
# The previous version of this comment said the curve was "used for
# every rookie-only source's contributions (DLF Rookie SF, DLF Rookie
# IDP)" with their NATIVE pool size as the percentile denominator.
# That described the pre-2026-04-21 routing, which the ladder
# translation retired; it survived here as a stale comment and
# contradicted both the code and CLAUDE.md.  Corrected 2026-07-26.
# Keep the constants — the refit workflow maintains them, and routing
# the curve is a live option — but do not read this block as a
# description of current behaviour.
HILL_ROOKIE_PERCENTILE_C: float = 0.1280
HILL_ROOKIE_PERCENTILE_S: float = 0.865

# Display scale
DISPLAY_SCALE_MAX: int = 9999
DISPLAY_SCALE_MIN: int = 1


# ══════════════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ══════════════════════════════════════════════════════════════════════


@dataclass
class TierBoundary:
    """Record of a detected tier break."""

    tier_id_above: int
    tier_id_below: int
    player_above: str  # last player in upper tier (player_id)
    player_below: str  # first player in lower tier (player_id)
    raw_gap: float
    gap_score: float
    rank_position: float  # consensus rank where the break occurs


# ══════════════════════════════════════════════════════════════════════
# TIER DETECTION — adjacent rank-gap analysis
# ══════════════════════════════════════════════════════════════════════


def _rolling_median(values: Sequence[float], idx: int, window: int) -> float:
    """Compute rolling median of *values* centered on *idx*.

    Uses *window* elements on each side.  At boundaries the window is
    asymmetrically clipped (but always includes at least the value
    itself so the result is never undefined).
    """
    lo = max(0, idx - window)
    hi = min(len(values), idx + window + 1)
    subset = values[lo:hi]
    return statistics.median(subset) if subset else values[idx]


def detect_tiers(
    consensus_ranks: list[float],
    player_ids: list[str],
    *,
    gap_window: int = TIER_GAP_WINDOW,
    gap_threshold: float = TIER_GAP_THRESHOLD,
    min_tier_size: int = TIER_MIN_SIZE,
) -> tuple[list[int], list[float | None], list[float | None], list[TierBoundary]]:
    """Detect natural tiers from sorted consensus ranks.

    Args:
        consensus_ranks: Ascending-sorted consensus ranks.
        player_ids: Corresponding player IDs (same order).
        gap_window: Half-window for rolling median of gaps.
        gap_threshold: Normalized gap score above which a tier break fires.
        min_tier_size: Minimum players before a tier can be split.

    Returns:
        (tier_ids, raw_gaps, gap_scores, boundaries)
        All lists are aligned with the input order.
    """
    n = len(consensus_ranks)
    if n == 0:
        return [], [], [], []
    if n == 1:
        return [1], [None], [None], []

    # Compute adjacent gaps
    raw_gaps: list[float] = []
    for i in range(n - 1):
        raw_gaps.append(consensus_ranks[i + 1] - consensus_ranks[i])

    # Compute normalized gap scores
    gap_scores: list[float] = []
    for i, g in enumerate(raw_gaps):
        rm = _rolling_median(raw_gaps, i, gap_window)
        # Guard against zero-division when local gaps are all identical
        score = g / rm if rm > 1e-9 else (1.0 if g < 1e-9 else gap_threshold + 1.0)
        gap_scores.append(score)

    # Identify tier break indices
    break_indices: list[int] = []  # index i means break AFTER player i
    players_since_last_break = 0
    for i, score in enumerate(gap_scores):
        players_since_last_break += 1
        if score >= gap_threshold and players_since_last_break >= min_tier_size:
            break_indices.append(i)
            players_since_last_break = 0

    # Build tier IDs
    tier_ids = [1] * n
    current_tier = 1
    break_set = set(break_indices)
    for i in range(n):
        tier_ids[i] = current_tier
        if i in break_set:
            current_tier += 1

    # Build boundary records
    boundaries: list[TierBoundary] = []
    for bi in break_indices:
        boundaries.append(
            TierBoundary(
                tier_id_above=tier_ids[bi],
                tier_id_below=tier_ids[bi] + 1 if bi + 1 < n else tier_ids[bi],
                player_above=player_ids[bi],
                player_below=player_ids[bi + 1] if bi + 1 < n else player_ids[bi],
                raw_gap=raw_gaps[bi],
                gap_score=gap_scores[bi],
                rank_position=consensus_ranks[bi],
            )
        )

    # Pad gaps/scores to length n (last player has no gap)
    raw_gaps_padded: list[float | None] = [*raw_gaps, None]
    gap_scores_padded: list[float | None] = [*gap_scores, None]

    return tier_ids, raw_gaps_padded, gap_scores_padded, boundaries


# ══════════════════════════════════════════════════════════════════════
# VALUE CURVES — rank-form (fallback) and percentile-form (live)
# ══════════════════════════════════════════════════════════════════════


def rank_to_value(
    rank: float,
    *,
    midpoint: float = HILL_MIDPOINT,
    slope: float = HILL_SLOPE,
) -> int:
    """Convert a rank to a display value on the 1–9999 scale.

    Hill-style formula: value = 1 + 9998 / (1 + ((rank - 1) / midpoint)^slope)

    Properties:
        - Rank 1 always returns exactly 9999 (denominator = 1 when rank = 1)
        - Flatter at the elite top than the old inverse-power curve
        - Smoother decay through the mid-ranks
        - Long tail preserved at low end
        - No post-hoc anchor/scaling that could drift between runs
    """
    if rank is None or rank <= 0:
        return 0
    # Clamp to >= 1: consensus ranks below 1 map to 9999 (above "1st place").
    # Also prevents negative base in fractional-exponent computation.
    effective_rank = max(1.0, float(rank))
    raw = 1.0 + 9998.0 / (1.0 + ((effective_rank - 1.0) / midpoint) ** slope)
    return max(DISPLAY_SCALE_MIN, min(DISPLAY_SCALE_MAX, round(raw)))


def rank_to_value_for_scope(rank: float, scope: str) -> int:
    """Scope-aware rank → value, for RECONSTRUCTION/FALLBACK paths only.

    THE ONE implementation of "what would the board have said for this
    rank?".  Two callers reconstruct a value when a real one is missing:

      * ``src/api/rank_history.py`` — old log entries that persisted a
        rank but not a value (per-source values only began persisting
        2026-04-29).
      * ``src/api/terminal.py`` — a ranked row carrying neither
        ``rankDerivedValue`` nor ``values.full``.  Dormant on live data
        (0 of 740 ranked rows on the 2026-07-29 payload) but reachable.

    ``scope`` is ``"idp"`` for IDP rows, anything else for offense.
    Picks take the offense curve: they are reconstructed rarely and the
    board prices them by tethering, not by a rank curve, so no rank-form
    curve is right for them (see the backtest note below).

    NOT the live valuation path.  Live values come from
    ``data_contract.py::_compute_unified_rankings``; this is only for
    rows where that output is unavailable.

    CALIBRATION (measured 2026-07-29,
    ``scripts/backtest_legacy_rank_curve.py``, 740 ranked rows of the
    live board, results in ``docs/measurements/``):

        candidate                overall RMSE   idp    offense   pick
        legacy_offense (was)         840.4     826.5    845.9   887.8
        legacy_scope   (this)        670.3      78.7    845.9   887.8
        percentile_global            238.4     164.9    278.8   193.4
        best-fit rank-form            96.3      65.6    113.5    68.7

    Routing by scope is a strict improvement and costs nothing — it uses
    constants that already exist — so it is applied here.  Whether this
    whole legacy rank-form family should be REPLACED (by the
    registry-managed percentile masters, or by a refit) is an open
    modeling decision, deliberately not taken inside an audit fix: the
    candidates have inverted error profiles (percentile_global is far
    better past rank 120 but ~2x worse in the top 24), and switching
    changes user-visible history values.  See the audit report.
    """
    if str(scope).lower() == "idp":
        return int(rank_to_value(float(rank), midpoint=IDP_HILL_MIDPOINT, slope=IDP_HILL_SLOPE))
    return int(rank_to_value(float(rank), midpoint=HILL_MIDPOINT, slope=HILL_SLOPE))


def percentile_to_value(
    percentile: float,
    *,
    midpoint: float = HILL_PERCENTILE_C,
    slope: float = HILL_PERCENTILE_S,
) -> int:
    """Final Framework step 2→3: convert a percentile to a display value.

    Input:
        percentile = (rank − 1) / (N − 1), clamped to [0, 1].  In the
        LIVE pipeline N is the fixed 500-rank combined-pool reference
        (``data_contract._PERCENTILE_REFERENCE_N``) for every source —
        ranks past 500 clamp to p=1.0 and share the curve's tail
        value.  (The per-source-native-pool design this docstring
        previously described was retired with the 2026-04-21 ladder
        translations; offline fit tooling may still pass native-pool
        percentiles.)

    Formula:
        V(p) = 9999 / (1 + (p / midpoint)^slope)

    Properties:
        - percentile=0 (source's rank 1) always returns 9999.
        - percentile=1 (source's last-ranked) decays to the curve's
          long tail.  Exact floor depends on (midpoint, slope).
        - Source pool size is absorbed into the percentile — a 100-
          deep source and a 500-deep source both map their rank-1
          to p=0 → V=9999, and their rank-50 to different p values
          reflecting how "deep" 50 is within each source.

    Constants are fit via ``scripts/fit_hill_curve_percentile.py``;
    see the module-level constants (``HILL_PERCENTILE_C`` /
    ``HILL_PERCENTILE_S`` for offense, ``IDP_HILL_PERCENTILE_C`` /
    ``IDP_HILL_PERCENTILE_S`` for IDP).
    """
    p = max(0.0, min(1.0, float(percentile)))
    if p == 0.0:
        return DISPLAY_SCALE_MAX
    raw = 9999.0 / (1.0 + (p / midpoint) ** slope)
    return max(DISPLAY_SCALE_MIN, min(DISPLAY_SCALE_MAX, round(raw)))
