"""Bench depth for BDVM service fixtures.

A 12-team league's replacement RANK sits (startable slots + waiver
buffer) deep — up to the 72nd WR in the fixtures that use this helper.
A fixture that projects three players therefore has no measurable
replacement level for any group, and since audit H7 the engine says so
(``unpriced`` / ``no_replacement_level``) rather than silently pricing
surplus over a fabricated R = 0.

These filler projections give each lineup group a pool that actually
reaches its replacement rank.  They are never on the contract, so they
shape the pools (and the per-group production z-scores) and nothing
else — no fixture's priced-player count changes because of them.
"""

from __future__ import annotations

import math

from src.bdvm.projections import ProjectionRecord

# True positions, one per lineup group: QB/RB/WR/TE plus EDGE→DL,
# LB→LB, CB→DB under DEFAULT_POS_GROUPS.
DEPTH_POSITIONS = ("QB", "RB", "WR", "TE", "EDGE", "LB", "CB")
DEPTH_PER_GROUP = 80  # deepest replacement rank in these fixtures is 72

_TOP_FPG = {
    "QB": 22.0,
    "RB": 18.0,
    "WR": 17.0,
    "TE": 14.0,
    "EDGE": 15.0,
    "LB": 18.0,
    "CB": 13.0,
}
_DECAY = 0.02  # gentle exponential, same shape as the reference pools


def depth_records(
    *,
    season: int = 2026,
    as_of: str = "2026-07-20",
    positions: tuple[str, ...] = DEPTH_POSITIONS,
    n: int = DEPTH_PER_GROUP,
    source: str = "depth",
) -> list[ProjectionRecord]:
    """Filler projections, ``n`` per position, monotonically decaying."""
    out: list[ProjectionRecord] = []
    for pos in positions:
        top = _TOP_FPG.get(pos, 14.0)
        for i in range(n):
            out.append(
                ProjectionRecord(
                    source=source,
                    player_key=f"depth {pos.lower()} {i}",
                    position=pos,
                    season=season,
                    as_of=as_of,
                    games=17.0,
                    fpg=round(top * math.exp(-_DECAY * i), 3),
                    scoring_native=True,
                )
            )
    return out
