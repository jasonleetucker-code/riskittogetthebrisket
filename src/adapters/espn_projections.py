"""ESPN season-projection adapter (Phase 2 scaffold).

The IDP scoring-fit pipeline currently uses trailing-3-yr realized
PPG as its production-quality estimate.  Phase 2 of the original
integration plan replaces that with forward-looking projections —
moving the lens from "what they did" to "what they're projected
to do under YOUR scoring."

Two projection sources, per the plan:

1. **ESPN league-aware projections** — at
   ``https://fantasy.espn.com/football/players/projections?leagueId=N``.
   League-scoring-aware fantasy points; rarely per-stat for IDPs.
   Behind Disney auth; requires a Playwright browser session with
   the user's ESPN cookies.

2. **Clay 2026 cheatsheet PDF** — static URL, structured tables,
   limited IDP coverage.  Static-PDF parser via ``pdfplumber``.

Status
------
Adapter scaffold + contract.  Full implementation deferred:

* ESPN: needs Disney-auth cookie capture + Playwright wiring
  (largely a copy of the existing scraper pattern in
  ``Dynasty Scraper.py``).
* Clay: needs static PDF parser, monthly refresh in
  ``scheduled-refresh.yml``.

The scaffold here exists so Phase 2 can be picked up cleanly:
data shape, adapter interface, and integration point are all
pinned.

Public contract
---------------
``fetch_espn_projections(season: int) -> list[ProjectedStatRow]``

``ProjectedStatRow``: same shape as ``WeeklyStatRow`` so the
existing ``compute_weekly_points`` pipeline can score it without
changes.  ``week=0`` is the convention for "season aggregate."

When activated, the scoring-fit orchestrator's
``build_realized_3yr_ppg`` will be renamed to
``build_dynasty_weighted_ppg`` and accept an optional
``projections`` parameter that overrides Y1 (current season) when
present.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProjectedStatRow:
    """Mirrors ``WeeklyStatRow`` for the projection corpus.

    ``week=0`` is the convention for "season aggregate" rather than
    a specific week — the scoring path treats it the same since the
    aggregator sums across weeks per player anyway.
    """
    player_id: str         # gsis_id
    player_name: str
    position: str
    team: str
    season: int
    week: int = 0          # 0 = season aggregate
    # Defensive projections — same column names as nflverse weekly
    # defensive stats so ``compute_weekly_points`` works unchanged.
    def_tackles_solo: float = 0.0
    def_tackle_assists: float = 0.0
    def_tackles: float = 0.0
    def_tackles_for_loss: float = 0.0
    def_sacks: float = 0.0
    def_sack_yards: float = 0.0
    def_qb_hits: float = 0.0
    def_pass_defended: float = 0.0
    def_interceptions: float = 0.0
    def_interception_yards: float = 0.0
    def_fumbles_forced: float = 0.0
    def_fumble_recovery_own: float = 0.0
    def_tds: float = 0.0


def fetch_espn_projections(season: int) -> list[ProjectedStatRow]:
    """Return season-projection rows from ESPN.

    **Not yet implemented.**  When activated:

    1. Launch Playwright with the operator's ESPN cookies (loaded
       from a secret blob).
    2. Navigate to fantasy.espn.com/football/players/projections,
       set the league dropdown to the operator's leagueId.
    3. Iterate every page of the projections table; parse the
       per-position columns.
    4. Cross-walk ESPN player ids → gsis via the existing id_map
       (which has ``espn_id`` columns).
    5. Emit ``ProjectedStatRow`` per player.

    Returns ``[]`` until Phase 2 is wired.  The orchestrator falls
    back to realized PPG when projections are empty, so this no-op
    is safe.
    """
    _LOGGER.info(
        "espn_projections=not_yet_implemented season=%d",
        season,
    )
    return []
