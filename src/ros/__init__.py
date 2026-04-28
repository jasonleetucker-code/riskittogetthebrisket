"""Rest-of-Season (ROS) rankings engine.

A separate short-term contender layer for power rankings, playoff odds,
championship odds, and buyer/seller recommendations.  HARD-isolated from
dynasty rankings and trade-calculator math — ROS values must never re-rank
dynasty players, change trade values, or modify market values.

Architecture (PR 1):

    sources/             — adapter registry + per-source scrapers
    scrape.py            — orchestrator (writes data/ros/sources/*.csv +
                           data/ros/runs/*.json)
    parse.py             — rank-to-value formula, freshness multipliers
    mapping.py           — name → canonical player resolver
    aggregate.py         — weighted average across sources
    lineup.py            — best projected lineup optimizer
    team_strength.py     — per-team ROS strength composite
    api.py               — FastAPI router (mounted at /api/ros/*)

Storage convention:

    data/ros/sources/<source_key>.csv          — latest scrape per source
    data/ros/runs/<source_key>__<iso_ts>.json  — per-run metadata
    data/ros/runs/index.json                   — most-recent-run pointer
    data/ros/aggregate/latest.json             — current aggregated values
    data/ros/aggregate/history/<iso_ts>.json   — rolling 30-day archive
    data/ros/team_strength/latest.json         — per-team snapshot
    data/ros/sims/playoff_<iso_ts>.json        — Monte Carlo outputs (PR 3)

Isolation invariant: this package MUST NOT mutate any module under
``src.api.data_contract``, ``frontend/lib/trade-logic.js``, or the dynasty
ranking source registry.  ``tests/ros/test_isolation.py`` snapshots the
dynasty contract output before+after importing this package and asserts
byte-identical results.
"""
from __future__ import annotations

__all__ = ["ROS_DATA_DIR"]

from pathlib import Path

# Single source of truth for the ROS file-storage root.  Resolved
# relative to repo root so tests + scripts + the API router all agree.
ROS_DATA_DIR: Path = Path(__file__).resolve().parents[2] / "data" / "ros"
