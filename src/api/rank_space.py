"""Compare ranks that came from boards of different depths.

WHY THIS EXISTS
---------------
Every cross-source rank comparison on this site was arithmetic on raw
ordinals, and the sources are not the same size.  Measured on the live
board (2026-08-05), the registered sources publish between 278 and 900
rows — a 3.2x spread — so "rank 143" means something different on every
one of them:

    draftSharks  rank 143 of 683  =  0.209 of the way down its board
    ktcSfTep     rank 121 of 469  =  0.258 of the way down its board

Ordinally KTC looks higher on that player.  In the only space where the
two boards are comparable, it is *lower*.  Normalizing flipped the sign
of the retail-vs-consensus gap on 42% of offense rows and 35 of 36 picks.

RANK SPACE is that common space: a rank divided by the depth of the
board it came from, so every source contributes a number in [0, 1] where
0 is the top of that board and 1 is the bottom.

WHAT THIS MODULE DELIBERATELY DOES NOT DO
-----------------------------------------
It does not know what a market gap is, what a retail source is, or what
the contract looks like.  It converts ranks and averages them.  The
policy — which sources sit on which side, what the sign means, when to
abstain — belongs to the caller (``data_contract._compute_market_gap``),
so this stays reusable for the next cross-source comparison rather than
becoming a second place where market-gap rules live.
"""

from __future__ import annotations

import statistics
from collections.abc import Iterable, Mapping
from typing import Any

__all__ = [
    "pool_depths",
    "to_rank_space",
    "mean_rank_space",
    "position_basis",
    "PER_MILLE",
    "RANK_SPACE_UNIT",
]

# Rank-space differences are tiny decimals (a big gap is ~0.15), which
# read badly in a UI and compare badly against integer thresholds.  The
# published magnitude is scaled by this and rounded, so 0.121 -> 121.
PER_MILLE = 1000

# Stamped on every payload carrying a rank-space magnitude.  The unit
# CHANGED in this batch (it used to be ordinal ranks), and a consumer
# still gating on the old unit would silently mis-threshold rather than
# fail — so the unit travels with the number.
RANK_SPACE_UNIT = "rankSpacePerMille"


def pool_depths(rank_maps: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    """Observed depth of each source's board, as the deepest rank it used.

    OBSERVED rather than declared.  The registry carries a ``depth``
    field, but it is ``None`` for most sources and describes the
    publisher's intent rather than what actually arrived — a source that
    failed halfway through a scrape still declares its full depth.  The
    deepest rank actually present is what the data supports, and it
    self-corrects when coverage changes.

    Sources absent from every map simply do not appear in the result;
    callers must treat a missing depth as "cannot normalize", never as
    zero.
    """
    depths: dict[str, int] = {}
    for ranks in rank_maps:
        if not isinstance(ranks, Mapping):
            continue
        for key, rank in ranks.items():
            if isinstance(rank, bool) or not isinstance(rank, (int, float)):
                continue
            value = int(rank)
            if value <= 0:
                continue
            if value > depths.get(str(key), 0):
                depths[str(key)] = value
    return depths


def to_rank_space(rank: Any, depth: Any) -> float | None:
    """Place one rank on the 0..1 scale of its own board.

    Returns ``None`` — never 0.0 — when the rank or the depth is
    unusable.  0.0 is the TOP of the board, the most valuable position
    there is, so coercing an unknown into it would be the exact
    substitution the C3 batch exists to remove.
    """
    if isinstance(rank, bool) or not isinstance(rank, (int, float)):
        return None
    if isinstance(depth, bool) or not isinstance(depth, (int, float)):
        return None
    if rank <= 0 or depth <= 0:
        return None
    return float(rank) / float(depth)


def mean_rank_space(
    ranks: Mapping[str, Any],
    depths: Mapping[str, Any],
    keys: Iterable[str] | None = None,
) -> tuple[float | None, int]:
    """Mean rank-space position over ``keys``, and how many it excluded.

    The exclusion count is returned rather than swallowed for the same
    reason ``utils.unknown.aggregate`` returns it: "the mean of the four
    sources we could place" is a different claim from "the mean of six",
    and a caller that cannot tell them apart will make the second claim.
    """
    wanted = set(keys) if keys is not None else set(ranks)
    placed: list[float] = []
    excluded = 0
    for key in wanted:
        if key not in ranks:
            continue
        value = to_rank_space(ranks.get(key), depths.get(key))
        if value is None:
            excluded += 1
            continue
        placed.append(value)
    if not placed:
        return None, excluded
    return statistics.fmean(placed), excluded


def position_basis(
    gaps_by_position: Mapping[str, list[float]],
    *,
    min_sample: int,
) -> dict[str, float]:
    """The part of a position's gap that is definitional, not tradeable.

    A retail board and an expert board can disagree about a whole
    POSITION for reasons that have nothing to do with any individual
    player.  Measured 2026-08-05, the median rank-space gap by position
    was TE +0.121 and PICK -0.109 against WR +0.020 / RB +0.016 /
    QB -0.007: the retail anchor is a TE-premium board and the board
    this pipeline publishes is anchored on it (ADR-015), so "retail
    ranks this tight end higher" is a restatement of the basis, not a
    mispricing.  Left in, it made 94% of tight ends and 97% of picks
    read SELL.

    The median — not the mean — because a handful of genuinely
    mispriced players should not move the constant that is supposed to
    describe everyone else.

    Positions with fewer than ``min_sample`` observations get NO entry.
    De-meaning off three players invents a basis out of the very noise
    it is meant to remove, and the caller is expected to abstain rather
    than guess.
    """
    out: dict[str, float] = {}
    for position, gaps in gaps_by_position.items():
        usable = [g for g in gaps if isinstance(g, (int, float)) and not isinstance(g, bool)]
        if len(usable) < min_sample:
            continue
        out[str(position)] = float(statistics.median(usable))
    return out
