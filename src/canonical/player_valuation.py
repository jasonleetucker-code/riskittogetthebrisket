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
#
# RECONSTRUCTION-ONLY.  Nothing on the live valuation path evaluates
# these; the board is built by the percentile-form scope masters below.
# The only consumers answer "what would the board have said for this
# rank?" when a real value is missing — see ``rank_to_value_for_scope``.
#
# RE-TUNED 2026-07-30.  Previously 48.44 / 1.149, being the mean of
# per-source Hill fits from ``scripts/fit_hill_curve_from_market.py``
# (four value-emitting market sources, each normalised so its top player
# = 9999).  That is the wrong target for a reconstruction curve: fitting
# individual retail SOURCE boards answers "what shape does KTC publish",
# while these constants have to answer "what does OUR board pay at rank
# r" — the output of the whole pipeline, after blending, TE basis
# conversion, shrinkage, the single-source haircut, the corridor clamp
# and pick tethering.  Measured against the live board the old pair
# scored RMSE 821.8 on offense rows; the values below score 89.8.
#
# Fit by ``scripts/backtest_legacy_rank_curve.py``, per scope, against
# ``rankDerivedValue`` on the served board.  The fit is structurally
# stable — 16 archived snapshots spanning 2026-07-16 → 07-30 returned
# offense midpoint 65.4 (once 65.6) / slope 0.910 and IDP 64.4-64.6 /
# 0.900 — because the board's rank→value relation IS a Hill curve, so
# market churn only permutes which player sits at which rank.
#
# What DOES move them is a percentile-master promotion: the pre-promotion
# board of 2026-07-29 fit at 68.8 / 0.929, the post-promotion board at
# 65.2 / 0.905.  That is what ``scripts/check_rank_form_drift.py`` and
# ``.github/workflows/audit-rank-form-drift.yml`` watch for.
HILL_MIDPOINT: float = 65.4  # rank at which value decay inflects
HILL_SLOPE: float = 0.910  # controls steepness of decay

# IDP-specific rank-form curve.  Kept as a separate pair because
# ``rank_history.py`` routes by scope and the IDP sub-population does fit
# marginally better on its own numbers (RMSE 76.2 vs 76.4 for one shared
# curve).  Note how SMALL that gap is, and why: ``canonicalConsensusRank``
# is a single GLOBAL ordinal over the whole board, so offense, IDP and
# pick rows all lie on one rank→value relation by construction.  The
# pre-2026-07-30 rationale here — that "dynasty IDP markets price
# differently from offense", fit against IDPTradeCalc's raw IDP slice —
# describes a real property of retail IDP BOARDS, but it is not what this
# constant measures.  Against our own board the two scopes want
# effectively the same curve, and the old IDP pair (69.50 / 0.945) scored
# well on IDP rows largely by coincidence: it sat near the global optimum
# while the offense pair did not.
#
# Do not read the offense/IDP split here as evidence of two economies.
# If a future change makes ranks scope-local rather than global, re-fit
# and revisit.
IDP_HILL_MIDPOINT: float = 64.6
IDP_HILL_SLOPE: float = 0.900

# ── The canonical percentile-coordinate contract ──────────────────────
#
# ONE owner for the rank → percentile half of the pipeline. Fitting,
# holdout evaluation and serving all consume this; none of them may
# reconstruct the equation locally.
#
# The contract, stated once:
#
#   rank base            1-based ordinal rank (rank 1 is the best asset)
#   reference population PERCENTILE_REFERENCE_N — a FIXED universe, not
#                        the length of whatever list a caller happens to
#                        hold
#   coordinate           p = (rank − 1) / (REFERENCE_N − 1), clamped [0,1]
#   truncation semantics FIT_TOP_N and friends select WHICH observations
#                        participate. They do NOT redefine the universe.
#
# That last line is the whole of audit finding W30-F008. The fit
# truncated each source to its top 400 and then divided by the length of
# the truncated list, so a training row's percentile depended on how many
# rows the fit happened to keep: /399 for OFFENSE and GLOBAL, /369 for
# the 370-row IDP slice, against /499 at serve time. The same ordinal
# rank therefore meant three different coordinates, and because
# V(p) falls in p, every scope served ABOVE anything the fit was scored
# against — OFFENSE +8.0%..+25.4%, GLOBAL +6.2%..+14.2%, IDP
# +14.0%..+33.9% across ranks 25..400 (measured 2026-08-11 on pinned
# inputs, docs/master-site-audit/evidence/W30/b1_denominator_measure.py).
#
# The spread is the defect, not the offset. A uniform inflation would
# cancel out of every comparison that matters; a per-scope one stretches
# the IDP ladder differently from the offense ladder, so IDP and offense
# rows on the same board stop being comparable.
#
# Note what is deliberately NOT done: serving is not moved to /399 and
# /369 to match the fits. That would make each scope internally
# consistent and leave them mutually incompatible — the same defect
# wearing a tidier coat.
#
# A short population is the case that makes the contract concrete. The
# IDP slice holds 370 rows against a 500-row universe. Its last observed
# player sits at (370 − 1) / 499 = 0.7395, NOT at 1.0. Stretching a
# 370-row source across the full range would assert that its worst
# observed player is the worst player in the universe, which is a claim
# the data does not make.
PERCENTILE_REFERENCE_N: int = 500


def rank_to_percentile(rank: float, *, reference_n: int = PERCENTILE_REFERENCE_N) -> float:
    """Canonical 1-based ordinal rank → percentile coordinate.

    ``p = (rank − 1) / (reference_n − 1)``, clamped to ``[0, 1]``.

    Ranks past the reference population clamp to 1.0 and share the
    curve's tail — deliberate top-N-board behavior, not an accident.

    Args:
        rank: 1-based ordinal rank. Rank 1 maps to 0.0.
        reference_n: the declared reference universe. Callers should
            almost never pass this; it exists so a genuinely different
            universe can be declared explicitly rather than implied by a
            list length.
    """
    n = int(reference_n)
    if n < 2:
        return 0.0
    p = (float(rank) - 1.0) / float(n - 1)
    return max(0.0, min(1.0, p))


def training_percentiles(count: int, *, reference_n: int = PERCENTILE_REFERENCE_N) -> list[float]:
    """Canonical coordinates for ``count`` consecutively-ranked rows.

    The helper fit and holdout share so neither divides by its own list
    length. Row ``i`` (0-based) is ordinal rank ``i + 1``, whatever
    truncation was applied before the call.
    """
    return [rank_to_percentile(i + 1, reference_n=reference_n) for i in range(int(count))]


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
HILL_GLOBAL_PERCENTILE_C: float = 0.1120
HILL_GLOBAL_PERCENTILE_S: float = 0.725
#
# OFFENSE master — fit from offense-only value sources (KTC,
# DynastyDaddy, DynastyNerds).  Used for every offense-scope source's
# contributions (KTC, DLF SF, Dynasty Nerds, FantasyPros SF, Dynasty
# Daddy, Flock Fantasy, FootballGuys SF, Yahoo/Boone, DraftSharks,
# DLF Rookie SF).
HILL_PERCENTILE_C: float = 0.1100
HILL_PERCENTILE_S: float = 1.110
#
# IDP master — fit from IDPTradeCalc's IDP slice (the only value-
# based IDP source).  Used for every IDP-scope source's contributions
# (DLF IDP, FantasyPros IDP, FootballGuys IDP, DLF Rookie IDP,
# DraftSharks IDP).
IDP_HILL_PERCENTILE_C: float = 0.0830
IDP_HILL_PERCENTILE_S: float = 1.110
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
HILL_ROOKIE_PERCENTILE_C: float = 0.1530
HILL_ROOKIE_PERCENTILE_S: float = 0.885

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

    CALIBRATION (re-measured 2026-07-30 after the constants were re-tuned,
    ``scripts/backtest_legacy_rank_curve.py``, 740 ranked rows of the live
    board, results in ``docs/measurements/``):

        candidate                overall RMSE   idp    offense   pick
        legacy_scope   (this)         83.8      76.2     89.8     64.7
        best-fit per scope            83.4      76.2     89.8     47.6
        best-fit single curve         84.0      76.4     90.1     61.9
        percentile_global            410.1     459.0    380.6    276.5
        percentile_scope             691.8     835.0    575.5    639.0

    For contrast, the SAME table on the same board before the re-tune:

        legacy_scope (old 48.44/1.149 + 69.50/0.945)
                                     644.9      89.5    821.8    882.9

    Two conclusions worth keeping:

    * The re-tuned pair now sits ON the achievable floor (83.8 vs 83.4),
      so there is no headroom left in this curve family.  The remaining
      ~84 RMSE is irreducible scatter — the board is not a pure function
      of rank, because post-blend stages (pick tethering, the two-way
      boost, the corridor clamp) move individual rows off the curve.
    * The percentile masters are NOT a drop-in replacement, and the
      2026-07-29 note that they had "inverted error profiles" is
      superseded: on the current board they are 5-8x worse everywhere.
      They are an INPUT stage to the blend, not a model of its output,
      so translating them into rank space does not answer this question.
      Retiring the rank-form family in their favour is off the table
      until something better than a refit exists.
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
