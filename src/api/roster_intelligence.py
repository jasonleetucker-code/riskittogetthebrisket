"""Assembly for ``GET /api/roster/intelligence``.

The transport-facing composition of the canonical roster-intelligence
chain — meaningful core → Team Strength → Team Weakness → age/value
portfolio — for one league, with the requesting team broken out.

**This module computes nothing.**  Every number comes from
``src/roster_intel/{core,strength,weakness,age_portfolio}.py``; this is
the shell that loads inputs and shapes a response, the same relationship
``server.py::get_gameplan`` has with ``src/api/gameplan.py``.

Inputs are reused, not reloaded
===============================

``gameplan.get_league_bundle`` already loads every input this needs —
rosters, the league's starter slots, ages, replacement levels — and
caches the expensive solve on a source stamp.  Building a second loader
here would give the two surfaces two views of the same league, which is
the failure mode the whole lane exists to remove.

Two limitations, named rather than implied
==========================================

**The roster source drops unpriced players.**
``ros/team_strength.py`` skips rows with ``rosValue <= 0`` before
writing the snapshot ``load_league_inputs`` reads.  So ``unpricedIds``
is empty **by construction** on this path — not because every player
was priced, but because the ones that were not never arrived.  Stamped
as ``rosterSource`` + ``unpricedVisibility`` so a reader cannot mistake
an empty list for a complete roster.

**Positional ranks are measured against the contract board.**  "Top 12
QB" is a statement about a player's standing, not about who owns him,
so the population is every priced non-pick row on the canonical board —
and it is stamped, because a consumer comparing two teams must know
they were measured the same way.
"""

from __future__ import annotations

import time
from typing import Any, Mapping

from src.api import gameplan as _gameplan
from src.roster_intel.age_portfolio import (
    build_age_portfolio,
    build_youth_curve,
    rank_age_portfolios,
)
from src.roster_intel.core import build_meaningful_core
from src.roster_intel.strength import build_team_strength, rank_team_strengths
from src.roster_intel.weakness import build_position_ranks, build_team_weakness

__all__ = [
    "ROSTER_INTELLIGENCE_CONTRACT_VERSION",
    "TeamNotInLeague",
    "build_league_roster_intelligence",
    "get_team_roster_intelligence",
]

ROSTER_INTELLIGENCE_CONTRACT_VERSION = "roster-intelligence/2026-08-18.v1"

#: What ``load_league_inputs`` reads, and what it silently excludes.
_ROSTER_SOURCE = "ros_team_strength_snapshot"
_UNPRICED_VISIBILITY = (
    "unpriced players are excluded by the roster snapshot writer "
    "(ros/team_strength.py drops rosValue <= 0), so unpricedIds is empty "
    "by construction on this path and is NOT evidence that every player "
    "was priced"
)
_RANK_POPULATION = "contract_board_priced_players"


class TeamNotInLeague(Exception):
    """The requested owner has no roster in this league."""


def _board_players(contract: Mapping[str, Any] | None) -> list[tuple[str, str, float | None]]:
    """``(playerId, position, value)`` for every priced non-pick row.

    Picks are excluded because they are not players and cannot hold a
    positional rank; unpriced rows are carried through with ``None`` so
    ``build_position_ranks`` can exclude them for its own stated reason
    rather than never seeing them.
    """
    rows: list[tuple[str, str, float | None]] = []
    if not isinstance(contract, Mapping):
        return rows
    for row in contract.get("playersArray") or []:
        if not isinstance(row, Mapping) or row.get("assetClass") == "pick":
            continue
        pid = str(row.get("playerId") or "").strip()
        position = str(row.get("position") or "").strip()
        if not pid or not position:
            continue
        value = row.get("rankDerivedValue")
        rows.append((pid, position, float(value) if isinstance(value, (int, float)) else None))
    return rows


def _ages(bundle: _gameplan.LeagueBundle) -> dict[str, float | None]:
    """``{playerId: age}`` from the bundle's contract-derived meta."""
    return {
        pid: float(meta["age"])
        for pid, meta in bundle.inputs.player_meta.items()
        if isinstance(meta, Mapping) and meta.get("age") is not None
    }


def build_league_roster_intelligence(
    bundle: _gameplan.LeagueBundle,
    contract: Mapping[str, Any] | None,
    *,
    team_count: int | None = None,
) -> dict[str, Any]:
    """Core / strength / weakness / age for EVERY team in one league.

    League-wide because three of the four outputs are league-RELATIVE:
    Team Strength rank, the Young Core Index and each room's percentile
    are all undefined for a single team.  Computing one team in
    isolation and then inventing its rank is the failure this shape
    prevents.
    """
    t0 = time.perf_counter()
    slots = list(bundle.inputs.slots)
    ages = _ages(bundle)

    board = _board_players(contract)
    ranks = build_position_ranks(board, population=_RANK_POPULATION)
    youth = build_youth_curve([(position, ages.get(pid)) for pid, position, _ in board])

    # The league's OWN size, measured from the rosters we loaded, with
    # the registry's declared count preferred when supplied: a snapshot
    # missing one roster must not shrink every weakness threshold.
    n_teams = int(team_count) if team_count else len(bundle.inputs.teams)

    cores = {
        team.owner_id: build_meaningful_core(list(team.pool), slots) for team in bundle.inputs.teams
    }
    strengths = rank_team_strengths({oid: build_team_strength(core) for oid, core in cores.items()})
    weaknesses = {
        oid: build_team_weakness(core, ranks, team_count=n_teams) for oid, core in cores.items()
    }
    portfolios = rank_age_portfolios(
        {
            oid: build_age_portfolio(
                core,
                ages,
                youth=youth,
                full_roster=_full_roster_values(bundle, oid),
            )
            for oid, core in cores.items()
        }
    )

    teams = {
        team.owner_id: {
            "ownerId": team.owner_id,
            "teamName": team.team_name,
            "core": cores[team.owner_id].to_dict(),
            "strength": strengths[team.owner_id].to_dict(),
            "weakness": weaknesses[team.owner_id].to_dict(),
            "agePortfolio": portfolios[team.owner_id].to_dict(),
        }
        for team in bundle.inputs.teams
    }

    return {
        "contractVersion": ROSTER_INTELLIGENCE_CONTRACT_VERSION,
        "leagueKey": bundle.inputs.league_key,
        "teamCount": n_teams,
        "starterSlots": slots,
        "rosterSource": _ROSTER_SOURCE,
        "unpricedVisibility": _UNPRICED_VISIBILITY,
        "rankPopulation": _RANK_POPULATION,
        "teams": teams,
        "notes": list(bundle.inputs.notes),
        "timing": {"computeMs": round((time.perf_counter() - t0) * 1000.0, 1)},
    }


def _full_roster_values(bundle: _gameplan.LeagueBundle, owner_id: str) -> list[tuple[str, float]]:
    """``(playerId, value)`` over the WHOLE roster, for the addendum's
    secondary full-roster age.

    Rows carrying no ``rosValue`` are SKIPPED rather than valued at 0:
    a zero-weight row would contribute nothing to a value-weighted mean
    anyway, but writing the coercion invites the next reader to copy it
    somewhere it does matter.
    """
    team = bundle.team(owner_id)
    out: list[tuple[str, float]] = []
    for row in team.rows if team else ():
        pid = str(row.get("playerId") or "")
        value = row.get("rosValue")
        if pid and isinstance(value, (int, float)):
            out.append((pid, float(value)))
    return out


def get_team_roster_intelligence(
    league_key: str,
    scoring_profile: str,
    contract: Mapping[str, Any] | None,
    owner_id: str,
    *,
    team_count: int | None = None,
) -> dict[str, Any]:
    """One team's roster intelligence, plus the league context it is
    ranked against.

    Raises :class:`TeamNotInLeague` when the owner has no roster, and
    ``gameplan.GameplanUnavailable`` when the inputs are not loadable —
    both distinct from "this team has nothing", which is a real answer.
    """
    bundle, cache_hit = _gameplan.get_league_bundle(league_key, scoring_profile, contract)
    league = build_league_roster_intelligence(bundle, contract, team_count=team_count)
    team = league["teams"].get(str(owner_id))
    if team is None:
        raise TeamNotInLeague(str(owner_id))

    payload = dict(league)
    payload["team"] = team
    # League-relative context without shipping every roster twice: the
    # ranks a consumer needs to place this team, and nothing more.
    payload["leagueContext"] = [
        {
            "ownerId": oid,
            "teamName": t["teamName"],
            "strengthTotal": t["strength"]["total"],
            "strengthRank": t["strength"]["leagueRank"],
            "youngCoreIndex": t["agePortfolio"]["youngCoreIndex"],
            "valueWeightedCoreAge": t["agePortfolio"]["valueWeightedCoreAge"],
        }
        for oid, t in sorted(
            league["teams"].items(),
            key=lambda kv: (
                kv[1]["strength"]["leagueRank"] is None,
                kv[1]["strength"]["leagueRank"] or 0,
                kv[0],
            ),
        )
    ]
    payload.pop("teams", None)
    payload["timing"] = {**league["timing"], "bundleCacheHit": cache_hit}
    return payload
