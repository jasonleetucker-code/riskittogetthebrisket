"""Aggregate ROS rankings across multiple sources into per-player values.

Inputs:
    - One ``SourceSnapshot`` per enabled ROS source.  Each snapshot has
      a list of ``RankedRow`` (canonical_name, position, rank, score)
      plus the metadata needed to compute the source's effective weight
      (status, scraped_at, player_count, has_valid_cache).
    - The league context dict (is_superflex, is_te_premium, idp_enabled).

Outputs:
    A list of ``AggregatedPlayer`` dicts ready for serialization to
    ``data/ros/aggregate/latest.json``.  Each entry carries:

        canonicalName        — canonical identity
        position             — best-known position from highest-confidence source
        rosValue             — weighted average normalized score (0-100)
        rosRankOverall       — rank within all aggregated players
        rosRankPosition      — rank within the player's position
        sourceCount          — number of sources that ranked this player
        sourceMinRank        — best rank seen
        sourceMaxRank        — worst rank seen
        sourceMedianRank     — median across sources
        sourceStddev         — score stddev across sources
        confidence           — composite [0, 1]: source_count + agreement + freshness
        tier                 — quintile (1 best, 5 worst)
        contributors         — per-source breakdown for explainability
        staleFlag            — true if every contributor is stale
        volatilityFlag       — true if stddev > VOLATILITY_THRESHOLD

The aggregator is pure — no I/O, no globals.  Storage / scheduling lives
in ``src/ros/scrape.py`` and ``src/ros/api.py``.
"""

from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass, field
from typing import Any, Iterable

from src.ros.parse import (
    effective_source_weight,
    rank_to_score,
)


LOG = logging.getLogger("ros.aggregate")

VOLATILITY_THRESHOLD = 18.0  # 0-100 scale; stddev above this flags volatile
DEFAULT_TIER_QUINTILES = 5


@dataclass(frozen=True)
class RankedRow:
    """One source's view of one player."""

    canonical_name: str
    position: str | None
    rank: int
    total_ranked: int
    # Optional projection signal from the source.  CARRIED BUT NOT
    # CONSUMED — ``aggregate()`` rank-scores every row, this one
    # included.  The field is populated (``scrape.py``) from a real
    # parsed projection (``sources/draftsharks_ros.py``), and DraftSharks
    # is the highest-weighted ROS source, so this is a live signal being
    # dropped rather than an unused hook.
    #
    # Consuming it is a change to every ROS value and to the meaning of
    # the 0-100 scale — projections are points, rank scores are not, and
    # blending the two needs a validated conversion that does not exist.
    # Pinned by ``tests/ros/test_projection_value_is_not_consumed.py``;
    # that suite fails if this comment starts claiming an override again.
    projection_value: float | None = None
    confidence: float = 1.0


@dataclass(frozen=True)
class SourceSnapshot:
    """All inputs needed to score one source's contribution."""

    source_key: str
    base_weight: float
    is_ros: bool
    is_dynasty: bool
    is_te_premium: bool
    is_superflex: bool
    is_2qb: bool
    is_idp: bool
    status: str  # "ok" | "partial" | "failed"
    scraped_at: str | None
    player_count: int
    has_valid_cache: bool
    rows: list[RankedRow] = field(default_factory=list)


@dataclass
class _PlayerAcc:
    """Per-player accumulator while we walk every source."""

    canonical_name: str
    position: str | None
    weighted_score_sum: float = 0.0
    weight_sum: float = 0.0
    ranks: list[int] = field(default_factory=list)
    raw_scores: list[float] = field(default_factory=list)
    contributors: list[dict[str, Any]] = field(default_factory=list)
    stale_count: int = 0
    total_count: int = 0


def aggregate(
    snapshots: Iterable[SourceSnapshot],
    *,
    league: dict[str, Any],
    now_iso: str | None = None,
) -> list[dict[str, Any]]:
    """Combine source snapshots into a sorted list of aggregated players.

    The returned list is sorted by ``rosValue`` descending so callers
    can directly write it as ``data/ros/aggregate/latest.json``.
    """
    snaps = list(snapshots)
    if not snaps:
        return []

    accs: dict[str, _PlayerAcc] = {}

    for snap in snaps:
        if not snap.rows:
            continue
        is_stale_source = snap.status not in ("ok", "partial") and snap.has_valid_cache
        # Weight is computed once per (source, player_position) bucket.
        # For PR1 we treat IDP-vs-offense as the only position split
        # that affects the format-match multiplier; sub-position
        # adjustments come in PR2/PR4.
        sample_position = next((r.position for r in snap.rows if r.position), None)
        weight = effective_source_weight(
            {
                "base_weight": snap.base_weight,
                "is_superflex": snap.is_superflex,
                "is_2qb": snap.is_2qb,
                "is_te_premium": snap.is_te_premium,
                "is_idp": snap.is_idp,
                "is_ros": snap.is_ros,
                "is_dynasty": snap.is_dynasty,
            },
            league=league,
            scraped_at=snap.scraped_at,
            player_count=snap.player_count,
            status=snap.status,
            has_valid_cache=snap.has_valid_cache,
            position=sample_position,
        )
        if weight <= 0:
            continue
        # One vote per (source, player).  ``weight`` above is computed once
        # for the SOURCE, then added below once per ROW — so a source that
        # lists the same player twice silently doubles that vendor's say.
        # That is not hypothetical: the DraftSharks ROS adapter
        # concatenated two of the vendor's own boards over an identical
        # 978-player universe, taking 67.4% of the blend against an
        # intended 50.8% and inflating ``sourceCount``/``confidence`` on
        # 939 of 1084 players for a year (audit 2026-07-30).  The adapter
        # is fixed; this guard is here so the next one cannot reintroduce
        # it.  First row wins — adapters put their primary board first.
        seen_in_source: set[str] = set()
        for row in snap.rows:
            if not row.canonical_name:
                continue
            # EVERY row is rank-scored, including rows that carry a real
            # projection.  ``rosValue`` is therefore a normalized log-rank
            # index on 0-100 — not points, and not projection-aware.
            #
            # This used to be an ``if row.projection_value ... else`` whose
            # two branches were byte-identical, described as a "PR1 stub"
            # awaiting projection-aware scaling.  The branch made the
            # discard look like a decision the code was already making;
            # collapsing it makes the discard visible.  See
            # ``RankedRow.projection_value`` for what is being dropped and
            # what wiring it up would cost.
            score = rank_to_score(row.rank, row.total_ranked)
            if score <= 0:
                continue
            # Checked here rather than at the top of the loop so a row that
            # scores 0 (and contributes nothing) cannot claim the slot and
            # shut out a scoreable duplicate behind it.
            if row.canonical_name in seen_in_source:
                LOG.warning(
                    "[ros] %s emitted %r more than once — keeping the first "
                    "scoring row; a source gets one vote per player.",
                    snap.source_key,
                    row.canonical_name,
                )
                continue
            seen_in_source.add(row.canonical_name)
            acc = accs.get(row.canonical_name)
            if acc is None:
                acc = _PlayerAcc(
                    canonical_name=row.canonical_name,
                    position=row.position,
                )
                accs[row.canonical_name] = acc
            row_weight = weight * (row.confidence or 1.0)
            acc.weighted_score_sum += score * row_weight
            acc.weight_sum += row_weight
            acc.ranks.append(int(row.rank))
            acc.raw_scores.append(score)
            acc.contributors.append(
                {
                    "sourceKey": snap.source_key,
                    "rank": int(row.rank),
                    "score": round(score, 2),
                    "weight": round(row_weight, 4),
                    "stale": is_stale_source,
                }
            )
            acc.total_count += 1
            if is_stale_source:
                acc.stale_count += 1
            # Carry the first non-empty position seen as the canonical
            # display position.  Position conflicts surface in the
            # contributors list for debugging.
            if row.position and not acc.position:
                acc.position = row.position

    aggregated: list[dict[str, Any]] = []
    for acc in accs.values():
        if acc.weight_sum <= 0:
            continue
        ros_value = acc.weighted_score_sum / acc.weight_sum
        stddev = statistics.pstdev(acc.raw_scores) if len(acc.raw_scores) > 1 else 0.0
        median_rank = statistics.median(acc.ranks) if acc.ranks else None
        # DISTINCT sources, not rows.  ``sourceCount`` is the number the UI
        # shows as "N sources agree" and the number ``ros-index.js`` breaks
        # duplicate-row ties on, so counting rows lets one vendor's second
        # board read as independent corroboration.  The per-source dedup
        # above makes these equal today; this keeps them equal by
        # construction rather than by the loop above staying correct.
        source_count = len({c["sourceKey"] for c in acc.contributors})
        # Confidence: combines source count (saturates at 4),
        # agreement (1 - stddev/SD_REFERENCE), and freshness
        # (% of contributors not stale).
        source_count_factor = min(1.0, source_count / 4.0)
        agreement_factor = max(0.0, 1.0 - stddev / 30.0)
        freshness_factor = 1.0 - (acc.stale_count / acc.total_count) if acc.total_count else 0.0
        confidence = round(
            0.45 * source_count_factor + 0.35 * agreement_factor + 0.20 * freshness_factor,
            3,
        )
        aggregated.append(
            {
                "canonicalName": acc.canonical_name,
                "position": acc.position,
                "rosValue": round(ros_value, 2),
                "sourceCount": source_count,
                "sourceMinRank": min(acc.ranks),
                "sourceMaxRank": max(acc.ranks),
                "sourceMedianRank": float(median_rank) if median_rank is not None else None,
                "sourceStddev": round(stddev, 3),
                "confidence": confidence,
                "staleFlag": acc.stale_count == acc.total_count and acc.total_count > 0,
                "volatilityFlag": stddev > VOLATILITY_THRESHOLD,
                "contributors": acc.contributors,
            }
        )

    # Overall + position ranks + tiers.
    aggregated.sort(key=lambda p: -p["rosValue"])
    for i, player in enumerate(aggregated, start=1):
        player["rosRankOverall"] = i
        player["tier"] = _tier_for_index(i, len(aggregated))

    by_pos: dict[str, int] = {}
    for player in aggregated:
        pos = (player.get("position") or "").upper()
        by_pos[pos] = by_pos.get(pos, 0) + 1
        player["rosRankPosition"] = by_pos[pos]

    if now_iso:
        for player in aggregated:
            player["aggregatedAt"] = now_iso

    return aggregated


def _tier_for_index(index_1based: int, total: int) -> int:
    """Map a 1-based rank to a quintile tier (1 best ... 5 worst)."""
    if total <= 0:
        return DEFAULT_TIER_QUINTILES
    bucket = max(1, total // DEFAULT_TIER_QUINTILES)
    return min(DEFAULT_TIER_QUINTILES, ((index_1based - 1) // bucket) + 1)
