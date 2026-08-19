"""Roster & Trade Intelligence (WS-J).

Additive layer over the League Intelligence engine. Valuation, exact
scoring, the best-ball optimizer, replacement levels and the value
schema are consumed from ``src/league_intel/`` as-is — nothing here
re-derives them.

Two halves that meet at ``RosterProfile`` / ``CompetitiveWindow``:

* **Roster engine** — ``marginal``, ``profiles``, ``window``,
  ``roster_source``, ``engine``. Measures what a roster IS by
  re-solving the exact lineup: marginal contribution, absence
  fragility, tradeable surplus, urgent need, and the competitive
  window as a five-state distribution. ``engine.analyze_roster``
  composes them and consumes ``src/ros/playoff_sim`` rather than
  simulating a second time.
* **Trade engine** — ``partner``, ``targets``, ``packages``. Measures
  what to DO about it: which positions are worth attacking, which
  players are worth pursuing, how a counterparty is likely to receive
  an offer, and which concrete packages are worth sending. Consumes
  the roster engine's output; never re-derives it.

**Canonical roster-intelligence chain (C2, 2026-08-18).**  ``core``,
``strength``, ``weakness`` and ``age_portfolio`` are the single owners
of the meaningful roster core, Team Strength, Team Weakness/Need
Priority and the age-value portfolio.  They are re-exported below as
THE stable interface for other lanes — trade intelligence, UI, and any
future decision product.  Consume them; do not reimplement them, and do
not select a roster population with a private top-N rule.  The HTTP
surface over the same owners is ``GET /api/roster/intelligence``
(``src/api/roster_intelligence.py``), which computes nothing of its own,
so an importer and an HTTP caller get identical numbers by construction.

``exposure`` is the C2-EXP-01 owner: value-weighted NFL-franchise
exposure, before/after.  It is DESCRIPTIVE ONLY — it emits no flag, no
verdict and no penalty, and nothing in the trade or roster chain imports
it, so it has no edge along which it could influence a grade.

``simulation`` is the exact before→apply→re-solve→after primitive
(`C2-SIM-01`, lane ``roster``).  The trade lane's `C3-CAP-01` roster
capacity / forced-drop unit is built ON it and lives in
``src/trade/`` — see the lane doc §14 for why that split is the
manifest's and not a halving of one unit.

``droppability`` is the odd one out and deliberately so: it OWNS
nothing.  The cut-ladder owner is ``src/draft/displacement.py``, and
that module is an adapter onto it so the trade and waiver lanes can
reach droppability without going through the Perfect Draft board.  It
is proven byte-identical to that board's ladder on all 12 live teams.

Full methodology, the replacement-level boundary table and the known
limitations: ``docs/roster-intelligence/C2_CANONICAL_ROSTER_CHAIN.md``.
"""

from src.roster_intel.age_portfolio import (
    TeamAgePortfolio,
    YouthCurve,
    build_age_portfolio,
    build_youth_curve,
    rank_age_portfolios,
)
from src.roster_intel.core import (
    CoreMember,
    MeaningfulCore,
    ReserveDemand,
    build_meaningful_core,
    reserve_demand,
)
from src.roster_intel.droppability import (
    DROPPABILITY_CONTRACT_VERSION,
    SCARCITY_REORDER_RATIO,
    league_droppability,
    pool_cut_ladder,
    team_droppability,
)
from src.roster_intel.exposure import (
    ExposureChange,
    FranchiseExposure,
    NflExposure,
    build_nfl_exposure,
    exposure_change,
    exposure_from_core,
    simulation_exposure_change,
)
from src.roster_intel.simulation import (
    RosterSimulation,
    SlotMovement,
    simulate_roster_change,
)
from src.roster_intel.strength import (
    POSITION_GROUPS,
    PositionStrength,
    TeamStrength,
    build_team_strength,
    rank_team_strengths,
)
from src.roster_intel.weakness import (
    PositionNeed,
    PositionRanks,
    SlotRung,
    TeamWeakness,
    build_position_ranks,
    build_team_weakness,
)

__all__ = [
    "CoreMember",
    "DROPPABILITY_CONTRACT_VERSION",
    "ExposureChange",
    "FranchiseExposure",
    "MeaningfulCore",
    "NflExposure",
    "POSITION_GROUPS",
    "PositionNeed",
    "PositionRanks",
    "PositionStrength",
    "ReserveDemand",
    "RosterSimulation",
    "SCARCITY_REORDER_RATIO",
    "SlotMovement",
    "SlotRung",
    "TeamAgePortfolio",
    "TeamStrength",
    "TeamWeakness",
    "YouthCurve",
    "build_age_portfolio",
    "build_meaningful_core",
    "build_nfl_exposure",
    "build_position_ranks",
    "build_team_strength",
    "build_team_weakness",
    "build_youth_curve",
    "exposure_change",
    "exposure_from_core",
    "league_droppability",
    "pool_cut_ladder",
    "rank_age_portfolios",
    "rank_team_strengths",
    "reserve_demand",
    "simulate_roster_change",
    "simulation_exposure_change",
    "team_droppability",
]
