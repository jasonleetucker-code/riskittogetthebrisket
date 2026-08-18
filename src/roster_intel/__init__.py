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
    "POSITION_GROUPS",
    "CoreMember",
    "MeaningfulCore",
    "PositionNeed",
    "PositionRanks",
    "PositionStrength",
    "ReserveDemand",
    "RosterSimulation",
    "SlotMovement",
    "SlotRung",
    "TeamAgePortfolio",
    "TeamStrength",
    "TeamWeakness",
    "YouthCurve",
    "build_age_portfolio",
    "build_meaningful_core",
    "build_position_ranks",
    "build_team_strength",
    "build_team_weakness",
    "build_youth_curve",
    "rank_age_portfolios",
    "rank_team_strengths",
    "reserve_demand",
    "simulate_roster_change",
]
