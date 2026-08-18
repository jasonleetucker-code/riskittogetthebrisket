"""Assembly for ``GET /api/roster/intelligence``.

The transport-facing composition of the canonical roster-intelligence
chain — meaningful core → Team Strength → Team Weakness → age/value
portfolio — for one league, with the requesting team broken out.

**This module computes nothing.**  Every number comes from
``src/roster_intel/{core,strength,weakness,age_portfolio}.py``; this is
the shell that loads inputs and shapes a response, the same relationship
``server.py::get_gameplan`` has with ``src/api/gameplan.py``.

The roster source is the CONTRACT, and that is load-bearing
===========================================================

Rosters come from ``data_contract.contract_roster_pools`` — the same
builder the ``optimalLineup`` stamp uses — not from the ROS
team-strength snapshot.  Two defects made the snapshot the wrong
source, and both are gone as a consequence rather than as a patch:

**It carried the wrong QUANTITY.**  Its ``rosValue`` is "a normalized
log-rank index on 0-100, not points, and not projection-aware"
(``src/ros/aggregate.py``) — a rest-of-season PRODUCTION measure.
``MASTER_PRODUCT_PLAN`` §4.1 says Team Strength "is not Power Ranking,
Playoff Odds, or ROS production" and must use canonical league values.
Team Strength was therefore summing the wrong number entirely; it now
sums ``rankDerivedValue`` on the canonical 1-9999 dynasty scale.

**It flattened unpriced players into real zeros before anyone could
see them.**  ``ros/team_strength.py`` appends every row it cannot match
with ``ros_value=0.0`` — its own comment calls that "a real
missing-is-zero coercion … left in place DELIBERATELY" — so
``unpriced_ids`` was structurally empty: not because every player was
priced, but because the unpriced ones arrived indistinguishable from
players genuinely worth nothing.  V1's MISSING IS NEVER ZERO rule
requires a consumer to tell those two apart, and a source that erases
the distinction makes that impossible downstream however correct the
consumer is.

*(Corrected 2026-08-19, integration review.  This said the writer
DROPPED those rows.  It does not.  The consequence for a consumer is
the same and the repair here is unchanged, but a coercion and a
deletion are fixed differently at the source — and §11 of the lane doc
hands the integration lane an instruction premised on the description,
so it had to be right.)*

Measured on the contract built from ``dynasty_export_20260818_191848.zip``
via ``build_api_data_contract``: **83 of 660 rostered players (12.6%)
carry no canonical value**, and every one is now reported in
``unpricedIds`` instead of reading as zero.

A third consequence, worth stating because it removes a real
operational fragility: the endpoint no longer needs the ROS refresh to
have run at all.  The contract is always loaded, so roster
intelligence cannot be dark because a different lane's timer failed.

**Positional ranks are measured against the contract board.**  "Top 12
QB" is a statement about a player's standing, not about who owns him,
so the population is every priced non-pick row on the canonical board —
and it is stamped, because a consumer comparing two teams must know
they were measured the same way.
"""

from __future__ import annotations

import math
import time
from typing import Any, Mapping

from src.api.data_contract import contract_roster_pools
from src.roster_intel.age_portfolio import (
    build_age_portfolio,
    build_youth_curve,
    rank_age_portfolios,
)
from src.roster_intel.core import build_meaningful_core
from src.roster_intel.droppability import league_droppability, team_droppability
from src.roster_intel.exposure import build_nfl_exposure, exposure_from_core
from src.roster_intel.strength import build_team_strength, rank_team_strengths
from src.roster_intel.weakness import build_position_ranks, build_team_weakness

__all__ = [
    "ROSTER_INTELLIGENCE_CONTRACT_VERSION",
    "TeamNotInLeague",
    "build_league_roster_intelligence",
    "get_team_roster_intelligence",
]

ROSTER_INTELLIGENCE_CONTRACT_VERSION = "roster-intelligence/2026-08-18.v1"

#: Where rosters and values come from.  Named in the payload because a
#: consumer comparing two responses must know they were built the same
#: way — and because this value CHANGED (it was the ROS snapshot, which
#: carried a production index and pre-deleted unpriced players).
_ROSTER_SOURCE = "canonical_contract"
_UNPRICED_VISIBILITY = (
    "rostered players the canonical board did not price are reported in "
    "unpricedIds and excluded from every value aggregate; they are never "
    "counted as zero"
)
_RANK_POPULATION = "contract_board_priced_players"


class TeamNotInLeague(Exception):
    """The requested owner has no roster in this league."""


def _board_players(contract: Mapping[str, Any] | None) -> list[tuple[str, str, float | None]]:
    """``(playerKey, position, value)`` for every non-pick board row.

    ``playerKey`` is the CANONICAL NAME, not the Sleeper id, because
    that is what ``contract_roster_pools`` keys a ``RosterPlayer`` by —
    and every consumer of this list looks its rows up by
    ``CoreMember.player_id``.

    That is not a stylistic choice; keying it by ``playerId`` is a
    silent-failure bug, and this function had it. Positional ranks then
    matched nothing, so every weakness rung reported UNKNOWN, and the
    youth curve was empty, so every Young Core Index came back ``None``.
    Nothing raised — the payload was fully shaped and entirely
    unpopulated, which is precisely the failure mode the missing-vs-zero
    discipline exists to make visible. It was caught by running the real
    12-team board and seeing twelve ``None`` indices, not by a test.

    Picks are excluded because they are not players and cannot hold a
    positional rank; unpriced rows are carried through with ``None`` so
    ``build_position_ranks`` excludes them for its own stated reason
    rather than never seeing them.
    """
    rows: list[tuple[str, str, float | None]] = []
    if not isinstance(contract, Mapping):
        return rows
    for row in contract.get("playersArray") or []:
        if not isinstance(row, Mapping) or row.get("assetClass") == "pick":
            continue
        position = str(row.get("position") or "").strip()
        if not position:
            continue
        value = row.get("rankDerivedValue")
        priced = float(value) if isinstance(value, (int, float)) else None
        for key in (row.get("canonicalName"), row.get("displayName")):
            if key:
                rows.append((str(key), position, priced))
                break
    return rows


def _ages(contract: Mapping[str, Any] | None) -> dict[str, float | None]:
    """``{playerName: age}`` from the canonical board.

    Keyed by the SAME name ``contract_roster_pools`` keys players by, so
    an age lookup cannot silently miss every player because two halves
    of this module disagreed about the join key.  A non-positive age is
    dropped rather than carried: Sleeper writes ``0`` for an unresolved
    record, and ``0`` is exactly the value that would make a roster look
    historically young.
    """
    out: dict[str, float | None] = {}
    if not isinstance(contract, Mapping):
        return out
    for row in contract.get("playersArray") or []:
        if not isinstance(row, Mapping) or row.get("assetClass") == "pick":
            continue
        age = row.get("age")
        if not isinstance(age, (int, float)) or age <= 0:
            continue
        for key in (row.get("canonicalName"), row.get("displayName")):
            if key:
                out.setdefault(str(key), float(age))
    return out


def _nfl_teams(contract: Mapping[str, Any] | None) -> dict[str, str]:
    """``{playerName: nflTeam}`` from the canonical board.

    Keyed the same way ``contract_roster_pools`` keys players, for the reason
    ``_board_players`` documents at length: a join key that disagrees with the
    pools fails silently and completely.

    An empty ``team`` is left OUT rather than stored as ``""`` — the exposure
    owner reads absence as UNKNOWN and reports the player, and an empty string
    would instead create a bucket that holds a share.  Measured on the live
    board, 0 of 660 rostered players lack one, but 25 carry ``FA``, which is a
    real answer (unsigned) and not a missing one.
    """
    out: dict[str, str] = {}
    if not isinstance(contract, Mapping):
        return out
    for row in contract.get("playersArray") or []:
        if not isinstance(row, Mapping) or row.get("assetClass") == "pick":
            continue
        team = str(row.get("team") or "").strip()
        if not team:
            continue
        for key in (row.get("canonicalName"), row.get("displayName")):
            if key:
                out.setdefault(str(key), team)
    return out


def build_league_roster_intelligence(
    contract: Mapping[str, Any] | None,
    *,
    team_count: int | None = None,
    include_droppability: bool = False,
) -> dict[str, Any]:
    """Core / strength / weakness / age for EVERY team in one league.

    League-wide because three of the four outputs are league-RELATIVE:
    Team Strength rank, the Young Core Index and each room's percentile
    are all undefined for a single team.  Computing one team in
    isolation and then inventing its rank is the failure this shape
    prevents.
    """
    t0 = time.perf_counter()
    pools, slots, slot_source = contract_roster_pools(dict(contract or {}))
    team_names = _team_names(contract)
    ages = _ages(contract)

    board = _board_players(contract)
    ranks = build_position_ranks(board, population=_RANK_POPULATION)
    youth = build_youth_curve([(position, ages.get(pid)) for pid, position, _ in board])

    # The league's OWN size, with the registry's declared count preferred
    # when supplied: a contract missing one roster must not shrink every
    # weakness threshold.
    n_teams = int(team_count) if team_count else len(pools)

    cores = {oid: build_meaningful_core(pool, slots) for oid, pool in pools.items()}
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
                full_roster=[
                    (pl.player_id, float(pl.ros_value))
                    for pl in pools[oid]
                    if pl.ros_value is not None
                ],
            )
            for oid, core in cores.items()
        }
    )

    drops = league_droppability(contract) if include_droppability else {}
    nfl_teams = _nfl_teams(contract)
    roster_values = {pl.player_id: pl.ros_value for pool in pools.values() for pl in pool}

    teams = {
        oid: {
            "ownerId": oid,
            "teamName": team_names.get(oid, ""),
            "rosteredCount": len(pools[oid]),
            "core": cores[oid].to_dict(),
            "strength": strengths[oid].to_dict(),
            "weakness": weaknesses[oid].to_dict(),
            "agePortfolio": portfolios[oid].to_dict(),
            # Descriptive only (C2-EXP-01).  Two scopes, named separately,
            # because "how concentrated is what plays" and "how concentrated
            # is the capital" are different questions with different answers.
            "nflExposure": {
                "core": exposure_from_core(cores[oid], teams=nfl_teams).to_dict(),
                "fullRoster": build_nfl_exposure(
                    [pl.player_id for pl in pools[oid]],
                    teams=nfl_teams,
                    values=roster_values,
                    positions={pl.player_id: pl.position for pl in pools[oid]},
                    scope="full_roster",
                ).to_dict(),
            },
            **({"droppability": drops[oid]} if oid in drops else {}),
        }
        for oid in pools
    }

    return {
        "contractVersion": ROSTER_INTELLIGENCE_CONTRACT_VERSION,
        "leagueKey": (contract or {}).get("meta", {}).get("leagueKey"),
        "teamCount": n_teams,
        "starterSlots": slots,
        "slotSource": slot_source,
        "rosterSource": _ROSTER_SOURCE,
        "unpricedVisibility": _UNPRICED_VISIBILITY,
        "rankPopulation": _RANK_POPULATION,
        # Stamped whether or not it was asked for: "you did not request
        # droppability" and "this team has nothing droppable" must not
        # read the same, and an absent key alone cannot tell them apart.
        "droppabilityIncluded": bool(include_droppability),
        "teams": teams,
        "timing": {"computeMs": round((time.perf_counter() - t0) * 1000.0, 1)},
    }


def _team_names(contract: Mapping[str, Any] | None) -> dict[str, str]:
    """``{ownerId: teamName}`` from the contract's sleeper block."""
    out: dict[str, str] = {}
    sleeper = (contract or {}).get("sleeper")
    if not isinstance(sleeper, Mapping):
        return out
    for team in sleeper.get("teams") or []:
        if isinstance(team, Mapping):
            oid = str(team.get("ownerId") or "")
            if oid:
                out[oid] = str(team.get("name") or team.get("sleeperTeamName") or "")
    return out


def _league_context_order(item: tuple[str, Mapping[str, Any]]) -> tuple[bool, float, str]:
    """Sort key for the league context: ranked teams first, best first.

    An unranked team sorts to the END on an explicit ``inf``, never on a
    coerced ``0``. The coercion is what the decision-coercion gate flags
    and it is right to: ``rank or 0`` reads an ABSENT rank as the best
    possible one, so the leading ``is None`` element is the only thing
    keeping such a team out of first place. Two guards where one should
    do it, and the fragile one is invisible.

    ``inf`` needs no companion guard — it is last on its own — so the
    ``is None`` element survives only to keep every unranked team
    grouped, and ``owner_id`` makes ties deterministic.
    """
    owner_id, team = item
    rank = team["strength"]["leagueRank"]
    return (rank is None, math.inf if rank is None else float(rank), owner_id)


def get_team_roster_intelligence(
    contract: Mapping[str, Any] | None,
    owner_id: str,
    *,
    team_count: int | None = None,
    include_droppability: bool = False,
) -> dict[str, Any]:
    """One team's roster intelligence, plus the league context it is
    ranked against.

    Raises :class:`TeamNotInLeague` when the owner has no roster in this
    contract — distinct from "this team has nothing", which is a real
    answer with a real payload.

    ``league_key`` / ``scoring_profile`` were parameters while this read
    the ROS snapshot through ``gameplan.get_league_bundle``; the
    contract carries its own league identity, so they are gone rather
    than left accepted-and-ignored.
    """
    league = build_league_roster_intelligence(contract, team_count=team_count)
    team = league["teams"].get(str(owner_id))
    if team is None:
        raise TeamNotInLeague(str(owner_id))

    if include_droppability:
        # ONE team's ladder, not the league's — the league loop costs 13x
        # this and the other eleven ladders are not part of this answer.
        team = dict(team)
        team["droppability"] = team_droppability(contract, owner_id=str(owner_id))

    payload = dict(league)
    payload["droppabilityIncluded"] = bool(include_droppability)
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
        for oid, t in sorted(league["teams"].items(), key=_league_context_order)
    ]
    payload.pop("teams", None)
    return payload
