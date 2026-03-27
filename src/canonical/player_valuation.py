"""Canonical player valuation system.

Produces market-realistic dynasty + IDP trade values from multi-source
ranking data using three core principles:

    1. Rankings determine ordering truth  (consensus rank)
    2. Gaps determine tier truth          (rank-gap tier detection)
    3. Curves determine value truth        (non-linear value mapping)

No league-specific adjustments, positional scarcity multipliers, or
external normalization factors are applied.  The output is a standalone
canonical value layer that can be consumed directly or optionally
modified downstream.

Pipeline:
    Step 1 – Consensus rank   (median/mean blend + volatility)
    Step 2 – Tier detection   (adjacent-gap analysis)
    Step 3 – Base value curve (inverse-power mapping)
    Step 4 – Tier cliff injection
    Step 5 – Volatility confidence adjustment
    Step 6 – Final output assembly
"""
from __future__ import annotations

import math
import statistics
from dataclasses import asdict, dataclass, field
from typing import Any, Sequence


# ══════════════════════════════════════════════════════════════════════
# HYPERPARAMETERS — all tunables collected here for easy iteration
# ══════════════════════════════════════════════════════════════════════

# Step 1: Consensus rank blending
W_MEDIAN: float = 0.70
W_MEAN: float = 0.30

# Step 2: Tier detection
TIER_GAP_WINDOW: int = 7           # rolling-median window (each side)
TIER_GAP_THRESHOLD: float = 2.0    # gap_score above this triggers a break
TIER_MIN_SIZE: int = 3             # minimum players in a tier before allowing split

# Step 3: Base value curve  —  base_value = A / (consensus_rank + B)^C
CURVE_A: float = 10_000.0          # scale (controls max value magnitude)
CURVE_B: float = 1.5               # shift (softens rank-1 singularity)
CURVE_C: float = 0.72              # decay (steepness of drop-off)

# Step 4: Tier cliff injection
CLIFF_BASE_POINTS: float = 120.0   # base cliff size in value units
CLIFF_RANK_DECAY: float = 0.006    # cliff decays with rank (deeper = smaller cliff)

# Step 5: Volatility adjustment
VOL_COMPRESSION_STRENGTH: float = 0.03   # max compression fraction per unit of z-scored volatility
VOL_FLOOR: float = 0.92                  # worst-case: retain at least 92% of value

# Step 6: Display scale
DISPLAY_SCALE_MAX: int = 9999
DISPLAY_SCALE_MIN: int = 1


# ══════════════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ══════════════════════════════════════════════════════════════════════

@dataclass
class PlayerValuation:
    """Full diagnostic output for a single player."""
    player_id: str
    display_name: str

    # Step 1 outputs
    source_ranks: list[float]
    median_rank: float
    mean_rank: float
    consensus_rank: float
    rank_volatility: float        # std-dev of source ranks

    # Step 2 outputs
    tier_id: int
    is_tier_start: bool           # True if this player is the first player in a new tier (a break exists directly above)
    gap_to_next: float | None     # raw gap to next-ranked player
    gap_score: float | None       # normalized gap score

    # Step 3–5 outputs
    base_value: float             # from curve only
    tier_adjustment: float        # cliff injection amount
    volatility_adjustment: float  # compression amount (negative)
    final_value: float            # base + tier_adj + vol_adj

    # Monotonicity enforcement
    monotonic_clamp_applied: bool  # True if this player's value was clamped down to preserve strict ordering

    # Display
    display_value: int            # mapped to 1–9999

    # Pass-through metadata
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TierBoundary:
    """Record of a detected tier break."""
    tier_id_above: int
    tier_id_below: int
    player_above: str        # last player in upper tier (player_id)
    player_below: str        # first player in lower tier (player_id)
    raw_gap: float
    gap_score: float
    rank_position: float     # consensus rank where the break occurs


@dataclass
class ValuationResult:
    """Complete output of the valuation pipeline."""
    players: list[PlayerValuation]
    tier_boundaries: list[TierBoundary]
    tier_count: int
    monotonic_clamp_count: int        # number of players whose values were clamped to preserve strict ordering
    hyperparameters: dict[str, Any]


# ══════════════════════════════════════════════════════════════════════
# STEP 1 — CONSENSUS RANK
# ══════════════════════════════════════════════════════════════════════

def compute_consensus_rank(
    source_ranks: Sequence[float],
    w_median: float = W_MEDIAN,
    w_mean: float = W_MEAN,
) -> tuple[float, float, float, float]:
    """Compute consensus rank from multiple source rankings.

    Returns:
        (consensus_rank, median_rank, mean_rank, rank_volatility)
    """
    if not source_ranks:
        raise ValueError("source_ranks must be non-empty")

    ranks = list(source_ranks)
    med = statistics.median(ranks)
    avg = statistics.mean(ranks)

    consensus = w_median * med + w_mean * avg

    vol = statistics.stdev(ranks) if len(ranks) >= 2 else 0.0

    return consensus, med, avg, vol


# ══════════════════════════════════════════════════════════════════════
# STEP 2 — TIER DETECTION
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
        boundaries.append(TierBoundary(
            tier_id_above=tier_ids[bi],
            tier_id_below=tier_ids[bi] + 1 if bi + 1 < n else tier_ids[bi],
            player_above=player_ids[bi],
            player_below=player_ids[bi + 1] if bi + 1 < n else player_ids[bi],
            raw_gap=raw_gaps[bi],
            gap_score=gap_scores[bi],
            rank_position=consensus_ranks[bi],
        ))

    # Pad gaps/scores to length n (last player has no gap)
    raw_gaps_padded: list[float | None] = [*raw_gaps, None]
    gap_scores_padded: list[float | None] = [*gap_scores, None]

    return tier_ids, raw_gaps_padded, gap_scores_padded, boundaries


# ══════════════════════════════════════════════════════════════════════
# STEP 3 — BASE VALUE CURVE
# ══════════════════════════════════════════════════════════════════════

def base_value_curve(
    consensus_rank: float,
    *,
    A: float = CURVE_A,
    B: float = CURVE_B,
    C: float = CURVE_C,
) -> float:
    """Map consensus rank to a base value using an inverse-power curve.

    Formula:  base = A / (consensus_rank + B)^C

    Properties:
        - Monotonically decreasing
        - Very steep near rank 1 (elite premium)
        - Moderate slope through mid-ranks (starter range)
        - Flattened tail (replacement-level compression)
    """
    return A / ((consensus_rank + B) ** C)


# ══════════════════════════════════════════════════════════════════════
# STEP 4 — TIER CLIFF INJECTION
# ══════════════════════════════════════════════════════════════════════

def compute_tier_adjustments(
    consensus_ranks: list[float],
    tier_ids: list[int],
    boundaries: list[TierBoundary],
    *,
    cliff_base: float = CLIFF_BASE_POINTS,
    cliff_decay: float = CLIFF_RANK_DECAY,
) -> list[float]:
    """Add cumulative tier-cliff bonuses.

    Players in higher tiers (lower tier_id) accumulate the value of all
    cliffs between their tier and the bottom tier.  This makes the cliff
    visible as a discrete jump at each tier boundary.

    The cliff size decays with rank so that early-tier cliffs (where values
    are large) are proportionally meaningful, while late-tier cliffs do not
    create unrealistic gaps among low-value players.

    Returns:
        List of tier adjustment values (same length as inputs).
    """
    n = len(consensus_ranks)
    if n == 0:
        return []

    # Map each tier boundary to a cliff size that decays with rank.
    # tier_id_below is the tier you drop INTO; the cliff bonus accrues
    # to every tier above it.
    cliff_at_boundary: dict[int, float] = {}
    for b in boundaries:
        cliff_at_boundary[b.tier_id_below] = cliff_base * math.exp(
            -cliff_decay * b.rank_position
        )

    # Walk tiers top-down.  Tier 1 accumulates all cliffs; each subsequent
    # tier loses the cliff that sits above it.
    max_tier = max(tier_ids) if tier_ids else 1
    accumulated = sum(cliff_at_boundary.values())
    tier_bonus: dict[int, float] = {}
    for t in range(1, max_tier + 1):
        tier_bonus[t] = accumulated
        if t + 1 in cliff_at_boundary:
            accumulated -= cliff_at_boundary[t + 1]

    return [tier_bonus.get(tier_ids[i], 0.0) for i in range(n)]


# ══════════════════════════════════════════════════════════════════════
# STEP 5 — VOLATILITY CONFIDENCE ADJUSTMENT
# ══════════════════════════════════════════════════════════════════════

def compute_volatility_adjustments(
    base_plus_tier: list[float],
    volatilities: list[float],
    *,
    strength: float = VOL_COMPRESSION_STRENGTH,
    floor: float = VOL_FLOOR,
) -> list[float]:
    """Apply a mild value compression for high-volatility players.

    High cross-source disagreement → slightly compress value toward zero
    to reflect reduced conviction.

    The adjustment is z-score-based relative to the population volatility
    distribution, so the penalty is relative, not absolute.

    Returns:
        List of adjustment amounts (negative or zero).
    """
    n = len(base_plus_tier)
    if n == 0:
        return []

    # If all volatilities are zero (e.g. single source), no adjustment
    if all(v == 0.0 for v in volatilities):
        return [0.0] * n

    vol_mean = statistics.mean(volatilities)
    vol_std = statistics.stdev(volatilities) if n >= 2 else 1.0
    if vol_std < 1e-9:
        return [0.0] * n

    adjustments: list[float] = []
    for i in range(n):
        z = (volatilities[i] - vol_mean) / vol_std
        # Only compress when z > 0 (above-average volatility)
        if z <= 0:
            adjustments.append(0.0)
        else:
            compression_frac = min(z * strength, 1.0 - floor)
            adj = -compression_frac * base_plus_tier[i]
            adjustments.append(adj)

    return adjustments


# ══════════════════════════════════════════════════════════════════════
# STEP 6 — FULL PIPELINE
# ══════════════════════════════════════════════════════════════════════

def compute_display_anchor(
    *,
    curve_a: float = CURVE_A,
    curve_b: float = CURVE_B,
    curve_c: float = CURVE_C,
    cliff_base: float = CLIFF_BASE_POINTS,
) -> float:
    """Compute a stable display-scale anchor from curve hyperparameters.

    The anchor is the theoretical maximum raw value: the base-curve value
    at rank 1 plus one full cliff bonus.  Because it depends only on
    hyperparameters (not on player data), it is stable across daily data
    refreshes and only changes when the model is deliberately retuned.

    This prevents the display scale from drifting when the top player's
    consensus rank or tier structure shifts between runs.
    """
    return base_value_curve(1.0, A=curve_a, B=curve_b, C=curve_c) + cliff_base


def _to_display(value: float, anchor: float) -> int:
    """Map a raw final value onto the 1–9999 display scale.

    Args:
        value: Raw final value from the pipeline.
        anchor: Stable display anchor (from compute_display_anchor).
                Values above the anchor are clamped to DISPLAY_SCALE_MAX.
    """
    if anchor <= 0:
        return DISPLAY_SCALE_MIN
    scaled = value / anchor * DISPLAY_SCALE_MAX
    return max(DISPLAY_SCALE_MIN, min(DISPLAY_SCALE_MAX, round(scaled)))


@dataclass
class PlayerInput:
    """Minimal input for the valuation pipeline."""
    player_id: str
    display_name: str
    source_ranks: list[float]
    metadata: dict[str, Any] = field(default_factory=dict)


def run_valuation(
    players: list[PlayerInput],
    *,
    # Step 1
    w_median: float = W_MEDIAN,
    w_mean: float = W_MEAN,
    # Step 2
    gap_window: int = TIER_GAP_WINDOW,
    gap_threshold: float = TIER_GAP_THRESHOLD,
    min_tier_size: int = TIER_MIN_SIZE,
    # Step 3
    curve_a: float = CURVE_A,
    curve_b: float = CURVE_B,
    curve_c: float = CURVE_C,
    # Step 4
    cliff_base: float = CLIFF_BASE_POINTS,
    cliff_decay: float = CLIFF_RANK_DECAY,
    # Step 5
    vol_strength: float = VOL_COMPRESSION_STRENGTH,
    vol_floor: float = VOL_FLOOR,
) -> ValuationResult:
    """Execute the full canonical valuation pipeline.

    Args:
        players: List of PlayerInput with source ranks.
        Remaining kwargs override default hyperparameters.

    Returns:
        ValuationResult with per-player diagnostics and tier info.
    """
    if not players:
        return ValuationResult(
            players=[],
            tier_boundaries=[],
            tier_count=0,
            monotonic_clamp_count=0,
            hyperparameters=_collect_hyperparams(locals()),
        )

    # ── Step 1: Consensus rank ──
    consensus_data: list[tuple[PlayerInput, float, float, float, float]] = []
    for p in players:
        cr, med, avg, vol = compute_consensus_rank(
            p.source_ranks, w_median=w_median, w_mean=w_mean,
        )
        consensus_data.append((p, cr, med, avg, vol))

    # Sort by consensus rank ascending (best = lowest rank)
    consensus_data.sort(key=lambda x: x[1])

    sorted_ranks = [x[1] for x in consensus_data]
    sorted_ids = [x[0].player_id for x in consensus_data]

    # ── Step 2: Tier detection ──
    tier_ids, raw_gaps, gap_scores, boundaries = detect_tiers(
        sorted_ranks, sorted_ids,
        gap_window=gap_window,
        gap_threshold=gap_threshold,
        min_tier_size=min_tier_size,
    )

    # Build set of players that start a new tier (first player below a break)
    tier_start_players = {b.player_below for b in boundaries}

    # ── Step 3: Base value curve ──
    base_values = [
        base_value_curve(cr, A=curve_a, B=curve_b, C=curve_c)
        for cr in sorted_ranks
    ]

    # ── Step 4: Tier cliff injection ──
    tier_adjustments = compute_tier_adjustments(
        sorted_ranks, tier_ids, boundaries,
        cliff_base=cliff_base, cliff_decay=cliff_decay,
    )

    base_plus_tier = [bv + ta for bv, ta in zip(base_values, tier_adjustments)]

    # ── Step 5: Volatility adjustment ──
    volatilities = [x[4] for x in consensus_data]
    vol_adjustments = compute_volatility_adjustments(
        base_plus_tier, volatilities,
        strength=vol_strength, floor=vol_floor,
    )

    # ── Assemble raw final values ──
    raw_finals = [
        bpt + va for bpt, va in zip(base_plus_tier, vol_adjustments)
    ]

    # ── Enforce strict monotonic decrease ──
    # Small rounding or volatility adjustments could theoretically create
    # a non-monotonic blip.  Walk forward and clamp.
    clamped_indices: set[int] = set()
    for i in range(1, len(raw_finals)):
        if raw_finals[i] >= raw_finals[i - 1]:
            raw_finals[i] = raw_finals[i - 1] - 0.01
            clamped_indices.add(i)

    # ── Step 6: Display scale mapping ──
    display_anchor = compute_display_anchor(
        curve_a=curve_a, curve_b=curve_b, curve_c=curve_c,
        cliff_base=cliff_base,
    )

    results: list[PlayerValuation] = []
    for i, (p, cr, med, avg, vol) in enumerate(consensus_data):
        pv = PlayerValuation(
            player_id=p.player_id,
            display_name=p.display_name,
            source_ranks=list(p.source_ranks),
            median_rank=med,
            mean_rank=avg,
            consensus_rank=cr,
            rank_volatility=vol,
            tier_id=tier_ids[i],
            is_tier_start=p.player_id in tier_start_players,
            gap_to_next=raw_gaps[i],
            gap_score=gap_scores[i],
            base_value=base_values[i],
            tier_adjustment=tier_adjustments[i],
            volatility_adjustment=vol_adjustments[i],
            final_value=raw_finals[i],
            monotonic_clamp_applied=i in clamped_indices,
            display_value=_to_display(raw_finals[i], display_anchor),
            metadata=dict(p.metadata),
        )
        results.append(pv)

    return ValuationResult(
        players=results,
        tier_boundaries=boundaries,
        tier_count=max(tier_ids) if tier_ids else 0,
        monotonic_clamp_count=len(clamped_indices),
        hyperparameters=_collect_hyperparams({
            "w_median": w_median, "w_mean": w_mean,
            "gap_window": gap_window, "gap_threshold": gap_threshold,
            "min_tier_size": min_tier_size,
            "curve_a": curve_a, "curve_b": curve_b, "curve_c": curve_c,
            "cliff_base": cliff_base, "cliff_decay": cliff_decay,
            "vol_strength": vol_strength, "vol_floor": vol_floor,
        }),
    )


def _collect_hyperparams(params: dict[str, Any]) -> dict[str, Any]:
    """Extract only numeric/string hyperparams from a dict."""
    skip = {"players", "self"}
    return {
        k: v for k, v in params.items()
        if k not in skip and isinstance(v, (int, float, str, bool))
    }


# ══════════════════════════════════════════════════════════════════════
# INTEGRATION HELPER — bridge from existing RawAssetRecord pipeline
# ══════════════════════════════════════════════════════════════════════

def build_player_inputs_from_raw_records(
    records: list[dict[str, Any]],
    excluded_sources: set[str] | None = None,
) -> list[PlayerInput]:
    """Convert raw adapter records (grouped by asset_key) into PlayerInput.

    Each unique asset_key becomes one PlayerInput.  Source ranks are
    extracted from rank_raw fields.

    This helper performs source *filtering*, not source *weighting*.
    Every included source contributes one rank with equal influence.
    If weighted source contribution is needed, it should be implemented
    in the consensus-rank step, not here.

    Args:
        records: List of dicts with at least asset_key, display_name,
                 source, rank_raw fields.
        excluded_sources: Optional set of source names to skip entirely.

    Returns:
        List of PlayerInput ready for run_valuation().
    """
    skip = excluded_sources or set()
    by_key: dict[str, dict[str, Any]] = {}

    for rec in records:
        key = rec.get("asset_key", "")
        if not key:
            continue
        source = rec.get("source", "")
        if source in skip:
            continue
        rank = rec.get("rank_raw")
        if rank is None:
            continue

        if key not in by_key:
            by_key[key] = {
                "player_id": key,
                "display_name": rec.get("display_name", key),
                "source_ranks": [],
                "metadata": {},
            }
            pos = rec.get("position_normalized_guess") or rec.get("position_raw", "")
            team = rec.get("team_normalized_guess") or rec.get("team_raw", "")
            if pos:
                by_key[key]["metadata"]["position"] = pos
            if team:
                by_key[key]["metadata"]["team"] = team

        by_key[key]["source_ranks"].append(float(rank))

    return [
        PlayerInput(**data)
        for data in by_key.values()
        if data["source_ranks"]  # must have at least one rank
    ]
