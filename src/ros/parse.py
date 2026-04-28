"""Pure functions for ROS rank-to-value conversion + source-weight math.

Per the spec:

    rank_score = 100 * ((ln(N + 1) - ln(r)) / ln(N + 1))

    effective_source_weight =
        base_source_weight
        * format_match_multiplier
        * freshness_multiplier
        * completeness_multiplier
        * availability_multiplier

These helpers are stateless so the aggregator + tests + future debugging
tools all agree on a single canonical conversion.  No I/O here.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any


# ── Rank → 0-100 normalized score ────────────────────────────────────
def rank_to_score(rank: int | float, total_ranked: int) -> float:
    """Convert a 1-indexed rank to a 0-100 normalized ROS score.

    Logarithmic top-heavy curve so elite ranks separate cleanly from
    replacement-level players.  rank 1 → near 100; rank N → 0.

    Returns 0 for invalid input rather than raising — sources with
    sparse coverage or missing rank fields shouldn't crash the
    aggregator.
    """
    try:
        r = float(rank)
        n = float(total_ranked)
    except (TypeError, ValueError):
        return 0.0
    if not (r > 0) or not (n > 0) or r > n:
        return 0.0
    denom = math.log(n + 1)
    if denom <= 0:
        return 0.0
    return 100.0 * (denom - math.log(r)) / denom


# ── Format-match multiplier ──────────────────────────────────────────
# Per spec:
#   1.15 — exact Superflex/2QB + TE premium match
#   1.10 — Superflex/2QB match
#   1.05 — IDP source used for IDP player
#   0.95 — standard PPR but useful
#   0.85 — not ROS but still relevant (dynasty proxy)
def format_match_multiplier(
    src: dict[str, Any], league: dict[str, Any], position: str | None = None
) -> float:
    """Score how well a source's format matches the league + player.

    ``league`` is a thin dict carrying the relevant flags:

        {
            "is_superflex": bool,
            "is_2qb": bool,
            "is_te_premium": bool,
            "idp_enabled": bool,
        }

    ``position`` lets the multiplier favor IDP sources for IDP rows.
    """
    pos = (position or "").upper()
    is_idp_player = pos in {"DL", "DE", "DT", "EDGE", "LB", "DB", "S", "CB"}

    # IDP source matched to an IDP player — modest bonus.
    if src.get("is_idp") and is_idp_player:
        # Compounded with the SF/2QB bonus when applicable.
        base = 1.05
    else:
        base = 1.0

    sf_match = bool(src.get("is_superflex") or src.get("is_2qb")) and bool(
        league.get("is_superflex") or league.get("is_2qb")
    )
    tep_match = bool(src.get("is_te_premium")) and bool(league.get("is_te_premium"))

    if sf_match and tep_match:
        return base * 1.15
    if sf_match:
        return base * 1.10

    # Dynasty proxy that's not ROS but still relevant.
    if not src.get("is_ros") and src.get("is_dynasty"):
        return base * 0.85
    # Standard PPR with no SF/TEP match but useful.
    return base * 0.95


# ── Freshness multiplier ─────────────────────────────────────────────
# Per spec:
#   1.00 — scraped today
#   0.90 — 1 day old
#   0.75 — 2-3 days old
#   0.50 — 4-7 days old
#   0.25 — older than 7 days
def freshness_multiplier(scraped_at_iso: str | None, *, now: datetime | None = None) -> float:
    """Discount source weight by age of the most recent successful scrape.

    ``scraped_at_iso`` is the source's ``last_success_at`` from its run
    metadata.  ``now`` is injectable for deterministic tests.
    """
    if not scraped_at_iso:
        return 0.0
    try:
        when = datetime.fromisoformat(scraped_at_iso.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    ref = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    age_hours = (ref - when).total_seconds() / 3600
    if age_hours < 24:
        return 1.0
    if age_hours < 48:
        return 0.90
    if age_hours < 96:  # 2-3 days
        return 0.75
    if age_hours < 168:  # 4-7 days
        return 0.50
    return 0.25


# ── Completeness multiplier ──────────────────────────────────────────
# Per spec:
#   1.00 — broad rankings with good player count
#   0.85 — partial rankings
#   0.70 — position-only or missing key positions
def completeness_multiplier(player_count: int, *, expected_min: int = 200) -> float:
    """Discount weight for sparse coverage."""
    try:
        n = int(player_count)
    except (TypeError, ValueError):
        return 0.0
    if n <= 0:
        return 0.0
    if n >= expected_min:
        return 1.0
    if n >= expected_min // 2:
        return 0.85
    return 0.70


# ── Availability multiplier ──────────────────────────────────────────
# Per spec:
#   1.00 — full data parsed
#   0.50 — partially parsed
#   0.00 — failed AND no recent valid cache
def availability_multiplier(status: str, has_valid_cache: bool) -> float:
    s = (status or "").lower()
    if s == "ok":
        return 1.0
    if s == "partial":
        return 0.5
    if has_valid_cache:
        return 0.5
    return 0.0


# ── Effective per-source weight ──────────────────────────────────────
def effective_source_weight(
    src: dict[str, Any],
    *,
    league: dict[str, Any],
    scraped_at: str | None,
    player_count: int,
    status: str,
    has_valid_cache: bool,
    position: str | None = None,
    now: datetime | None = None,
) -> float:
    """Compose the four multipliers per the spec's weight formula."""
    base = float(src.get("base_weight") or 0.0)
    if base <= 0:
        return 0.0
    return (
        base
        * format_match_multiplier(src, league, position)
        * freshness_multiplier(scraped_at, now=now)
        * completeness_multiplier(player_count)
        * availability_multiplier(status, has_valid_cache)
    )
