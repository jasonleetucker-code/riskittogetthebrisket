"""Sleeper HTTP helpers for the IDP calibration lab.

Wraps the existing public-pipeline client at
``src/public_league/sleeper_client.py`` so we reuse its pooled session,
graceful-degradation behaviour, and cached NFL player map. The
calibration lab needs a deeper history than the public snapshot (4
seasons vs 3), so ``fetch_league_chain`` exposes a configurable cap.
"""
from __future__ import annotations

from typing import Any

from src.public_league.sleeper_client import (
    fetch_league,
    fetch_nfl_players,
    fetch_rosters,
    fetch_users,
)

__all__ = [
    "fetch_league",
    "fetch_nfl_players",
    "fetch_rosters",
    "fetch_users",
    "fetch_league_chain",
]


def fetch_league_chain(
    start_league_id: str, max_seasons: int = 8
) -> list[dict[str, Any]]:
    """Walk ``previous_league_id`` links starting from ``start_league_id``.

    Unlike ``src.public_league.sleeper_client.walk_league_chain`` this
    variant allows a deeper horizon so the calibration lab can reach
    the 2022 season even when the public-pipeline horizon is shorter.
    Returns league objects ordered newest -> oldest. Stops on the
    first missing league (no silent year substitution). Safe against
    circular ``previous_league_id`` references.
    """
    if max_seasons <= 0:
        return []
    chain: list[dict[str, Any]] = []
    seen: set[str] = set()
    cur = str(start_league_id or "").strip()
    while cur and cur not in seen and len(chain) < max_seasons:
        seen.add(cur)
        league = fetch_league(cur)
        if not league:
            break
        chain.append(league)
        nxt = league.get("previous_league_id") or league.get("previous_league") or ""
        cur = str(nxt or "").strip()
    return chain
