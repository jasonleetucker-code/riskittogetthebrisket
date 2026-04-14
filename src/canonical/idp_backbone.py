"""IDP rank translation backbone.

This module owns the single authoritative translation from a position-only
IDP source rank (e.g. "DL rank 5 in a top-20 DL list") to a synthetic
overall-IDP rank that can be fed into the shared Hill curve in
`src/canonical/player_valuation.py`.

Why this exists
───────────────
Historically every source was treated as if it produced an overall ordinal
rank over the full rankable population.  That assumption breaks when a
source only ranks a single position family.  A DL-only top-20 list would
otherwise be interpreted as "this player is one of the top 20 IDPs overall",
which dramatically overvalues shallow positional lists.

The fix is a two-step model:

  1. Build a backbone ladder from a trusted full-board IDP source.  The
     ladder records, for each position family, the *overall* IDP rank at
     which DLn (or LBn, DBn) sits in the backbone source.

     Example (toy numbers):
       DL ladder = [2, 4, 7, 11, 14, ...]
         → means DL1 sits at overall IDP rank 2, DL5 at overall IDP rank 14.

  2. Translate a position-only source's raw positional rank through that
     ladder to a synthetic overall-IDP rank.  Exact anchors map directly,
     fractional positions interpolate, and positions beyond the backbone
     extrapolate with a monotonic guardrail.

The synthetic overall-IDP rank is then passed through the standard Hill
curve, landing every IDP player in the same 1-9999 economy as offense.

Design notes
────────────
- This module is pure: no I/O, no contract-side bookkeeping, no stamping
  fields onto rows.  The ranking authority in
  `src/api/data_contract.py::_compute_unified_rankings` owns all of that.
- The frontend mirror in `frontend/lib/dynasty-data.js` must stay in sync
  with the math in this module.  The helpers here are small and easy to
  translate line-for-line.
- `SOURCE_SCOPE_OVERALL_IDP`, `SOURCE_SCOPE_OVERALL_OFFENSE`, and
  `SOURCE_SCOPE_POSITION_IDP` are the canonical scope tokens used across
  both backends.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

# ── Canonical scope tokens ─────────────────────────────────────────────
# Declared by each registered ranking source.  The scope decides which
# players are eligible to receive a rank from that source and how the
# resulting rank is translated into a Hill-curve input.
SOURCE_SCOPE_OVERALL_OFFENSE = "overall_offense"
SOURCE_SCOPE_OVERALL_IDP = "overall_idp"
SOURCE_SCOPE_POSITION_IDP = "position_idp"

VALID_SOURCE_SCOPES = frozenset(
    {
        SOURCE_SCOPE_OVERALL_OFFENSE,
        SOURCE_SCOPE_OVERALL_IDP,
        SOURCE_SCOPE_POSITION_IDP,
    }
)

# Position families that the ladder model understands.  These are the
# same tokens used by the rest of the pipeline for IDP normalization.
IDP_POSITION_GROUPS = ("DL", "LB", "DB")

# ── Translation result constants ────────────────────────────────────────
TRANSLATION_DIRECT = "direct"            # overall_idp / overall_offense
TRANSLATION_EXACT = "exact"              # position_idp matched an anchor
TRANSLATION_INTERPOLATED = "interpolated"  # fractional position between anchors
TRANSLATION_EXTRAPOLATED = "extrapolated"  # past the last known anchor
TRANSLATION_FALLBACK = "fallback"        # backbone absent; no-op passthrough


@dataclass(frozen=True)
class IdpBackbone:
    """Backbone ladders derived from a full-board IDP source.

    `ladders[pos]` is a list of overall-IDP ranks whose i-th entry is the
    overall rank of the (i+1)-th player at that position.  Ranks are
    integers starting at 1.

    `depth` is the total number of overall-IDP entries the backbone was
    built from.  It's retained for transparency (to label "ladderDepth"
    on translation metadata).

    ``shared_market_idp_ladder`` holds the combined offense+IDP ranks at
    which IDP entries appear in the backbone source's shared market.
    The i-th entry is the combined-pool rank of the (i+1)-th best IDP in
    the backbone source.  This ladder is only populated when the caller
    supplies ``offense_positions`` to ``build_backbone_from_rows``; it
    powers the crosswalk that keeps IDP-only expert boards (e.g. DLF)
    from pretending their rank 1 is the overall rank 1 of the shared
    market.

    ``shared_market_depth`` is the size of the combined offense+IDP pool
    used to build ``shared_market_idp_ladder``.  Zero when no shared
    market was supplied.
    """

    ladders: dict[str, list[int]] = field(default_factory=dict)
    depth: int = 0
    shared_market_idp_ladder: list[int] = field(default_factory=list)
    shared_market_depth: int = 0

    def ladder_for(self, position_group: str) -> list[int]:
        return self.ladders.get(str(position_group).upper(), [])

    def shared_idp_ladder(self) -> list[int]:
        """Return the combined offense+IDP ladder for IDP-only sources.

        Used by `translate_position_rank` to translate a non-backbone
        overall_idp source's raw rank into a synthetic combined-market
        rank.  Empty when no shared market was supplied at build time.
        """
        return list(self.shared_market_idp_ladder)

    def is_empty(self) -> bool:
        return self.depth == 0 or not any(self.ladders.values())


def build_backbone_from_ranked_entries(
    ranked_entries: Iterable[tuple[str, str]],
) -> IdpBackbone:
    """Build a backbone from a sequence of (position_group, name) tuples
    already sorted in descending overall-IDP order.

    Callers are expected to walk their full-board IDP source from best to
    worst and yield one tuple per IDP entry.  Non-IDP or unsupported
    positions should NOT be included — they'd pollute the ladder.

    The i-th tuple in the iterable is assigned overall IDP rank (i+1).
    """
    ladders: dict[str, list[int]] = {pos: [] for pos in IDP_POSITION_GROUPS}
    depth = 0
    for overall_idx, (pos, _name) in enumerate(ranked_entries, start=1):
        pos_up = str(pos or "").upper()
        if pos_up not in ladders:
            continue
        ladders[pos_up].append(overall_idx)
        depth = max(depth, overall_idx)
    return IdpBackbone(ladders=ladders, depth=depth)


def build_backbone_from_rows(
    rows: Iterable[dict],
    *,
    source_key: str,
    idp_positions: Iterable[str] = IDP_POSITION_GROUPS,
    offense_positions: Iterable[str] | None = None,
) -> IdpBackbone:
    """Convenience builder used by the contract pipeline.

    Walks `rows` (order doesn't matter), keeps only rows whose position
    is an IDP family, sorts them descending by the per-source value at
    `canonicalSiteValues[source_key]`, and constructs a backbone from the
    resulting order.

    When ``offense_positions`` is supplied, the builder also computes the
    *shared-market IDP ladder* — a list of combined offense+IDP ranks at
    which IDP players appear in the same-source value pool.  This ladder
    is the crosswalk backbone for non-backbone IDP-only expert boards
    (e.g. DLF): their raw IDP-only rank gets translated through it into
    a synthetic combined-pool rank, preventing DLF rank 1 from behaving
    like a shared-market rank 1.
    """
    idp_set = {p.upper() for p in idp_positions}
    offense_set = {p.upper() for p in (offense_positions or ())}

    eligible: list[tuple[float, str, str]] = []
    combined: list[tuple[float, str, str, bool]] = []  # (val, pos, name, is_idp)
    for row in rows:
        pos = str(row.get("position") or "").strip().upper()
        is_idp = pos in idp_set
        is_offense = pos in offense_set
        if not (is_idp or is_offense):
            continue
        sites = row.get("canonicalSiteValues") or {}
        raw = sites.get(source_key)
        try:
            val = float(raw) if raw is not None else None
        except (TypeError, ValueError):
            val = None
        if val is None or val <= 0:
            continue
        name = str(row.get("canonicalName") or row.get("displayName") or "")
        if is_idp:
            eligible.append((val, pos, name))
        if offense_set:
            combined.append((val, pos, name, is_idp))
    # Sort descending by value; secondary tiebreaker by name for stability.
    eligible.sort(key=lambda t: (-t[0], t[2].lower()))
    base = build_backbone_from_ranked_entries((pos, name) for _, pos, name in eligible)

    shared_market_idp_ladder: list[int] = []
    shared_market_depth = 0
    if combined:
        combined.sort(key=lambda t: (-t[0], t[2].lower()))
        shared_market_depth = len(combined)
        for combined_rank, (_, _pos, _name, is_idp) in enumerate(combined, start=1):
            if is_idp:
                shared_market_idp_ladder.append(combined_rank)

    return IdpBackbone(
        ladders=base.ladders,
        depth=base.depth,
        shared_market_idp_ladder=shared_market_idp_ladder,
        shared_market_depth=shared_market_depth,
    )


# ── Position-rank translation ────────────────────────────────────────────
def translate_position_rank(
    position_rank: float,
    ladder: list[int],
    *,
    min_synthetic_rank: int = 1,
) -> tuple[int, str]:
    """Translate a within-position rank to an overall-IDP synthetic rank.

    Args:
        position_rank: The raw 1-based rank inside the position family.
            Non-integer values interpolate between anchors (rarely used;
            most sources emit integers).
        ladder: The ladder for that position family.  Must be sorted
            ascending (built by ``build_backbone_from_*``).
        min_synthetic_rank: Lower bound clamp.  Defaults to 1 so the
            result is always a valid Hill-curve input.

    Returns:
        (synthetic_overall_rank, method) where ``method`` is one of the
        ``TRANSLATION_*`` constants.

    Rules:
        * Empty ladder → pass through the raw rank unchanged and mark it
          as TRANSLATION_FALLBACK so the caller can attach a caution flag.
        * ``position_rank <= 0`` → clamp to 1 (defensive).
        * Integer rank within the ladder → exact anchor.
        * Fractional rank strictly between two anchors → linear
          interpolation, rounded half-up.
        * Rank beyond the ladder → monotonic extrapolation using the
          average spacing of the last few anchors, guaranteeing the
          synthetic rank is strictly greater than the last anchor.
    """
    if not ladder:
        safe = max(min_synthetic_rank, int(round(max(1.0, float(position_rank or 1)))))
        return safe, TRANSLATION_FALLBACK

    try:
        pr = float(position_rank)
    except (TypeError, ValueError):
        pr = 1.0
    if pr < 1.0 or not _is_finite(pr):
        pr = 1.0

    n = len(ladder)
    # Exact or integer within ladder
    if pr == float(int(pr)) and 1 <= int(pr) <= n:
        return max(min_synthetic_rank, ladder[int(pr) - 1]), TRANSLATION_EXACT

    # Interpolation within the ladder
    if 1.0 <= pr <= float(n):
        low_idx = int(pr) - 1           # 0-based index of left anchor
        frac = pr - float(int(pr))
        low = ladder[low_idx]
        high = ladder[min(low_idx + 1, n - 1)]
        synthetic = low + (high - low) * frac
        return (
            max(min_synthetic_rank, int(round(synthetic))),
            TRANSLATION_INTERPOLATED,
        )

    # Extrapolation past the last anchor.  Use the average step of the
    # tail of the ladder (last min(5, n-1) steps) so a single wild spacing
    # can't blow up the projection.  Guarantee strict monotonicity.
    if n == 1:
        step = max(1.0, float(ladder[0]))
    else:
        tail = min(5, n - 1)
        diffs = [ladder[-i] - ladder[-i - 1] for i in range(1, tail + 1)]
        step = max(1.0, sum(diffs) / len(diffs))
    overshoot = pr - float(n)
    synthetic = ladder[-1] + step * overshoot
    synthetic_int = int(round(synthetic))
    if synthetic_int <= ladder[-1]:
        synthetic_int = ladder[-1] + 1
    return max(min_synthetic_rank, synthetic_int), TRANSLATION_EXTRAPOLATED


# ── Coverage-aware source weight ─────────────────────────────────────────
# Shallow positional lists (e.g. depth=20) should contribute less to the
# blend than a deep full-board source.  This helper computes the effective
# blend weight = declared_weight * coverage_factor.
#
# The coverage factor grows linearly from 0 up to ``MIN_FULL_DEPTH`` and
# caps at 1.0 beyond that.  60 was chosen as a sensible "fully covered"
# threshold given current top-20 / top-50 / top-150 list conventions; it
# can be tuned from the source registry without touching this module.
MIN_FULL_COVERAGE_DEPTH = 60


def coverage_weight(
    declared_weight: float,
    depth: int | None,
    *,
    min_full_depth: int = MIN_FULL_COVERAGE_DEPTH,
) -> float:
    """Return the effective blend weight for a source.

    Sources with no declared depth (overall lists) return `declared_weight`
    unchanged.  Sources with a declared depth shallower than
    ``min_full_depth`` are scaled linearly so a 20-deep list with declared
    weight 1.0 contributes only ``20 / min_full_depth``.
    """
    w = max(0.0, float(declared_weight or 0.0))
    if depth is None:
        return w
    try:
        d = float(depth)
    except (TypeError, ValueError):
        return w
    if d <= 0:
        return 0.0
    factor = min(1.0, d / max(1.0, float(min_full_depth)))
    return w * factor


# ── Internal helpers ─────────────────────────────────────────────────────
def _is_finite(x: float) -> bool:
    return x == x and x not in (float("inf"), float("-inf"))
