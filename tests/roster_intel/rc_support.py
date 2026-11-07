"""Deterministic synthetic leagues for the Roster Construction V1 tests.

Builds a real :class:`PublicLeagueSnapshot` (Sleeper-shaped matchups with
``players`` / ``players_points`` / ``starters`` / ``points``) so the tests run
through the same snapshot → player_impact → construction path as production.
The host's best-ball ``starters`` are produced by the canonical solver,
exactly as Sleeper awards a best-ball lineup.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Mapping
from typing import Any

from src.public_league.identity import ManagerRegistry
from src.public_league.snapshot import PublicLeagueSnapshot, SeasonSnapshot
from src.ros.lineup import (
    OBJECTIVE_REALIZED_POINTS,
    RosterPlayer,
    solve_optimal_assignment,
)

#: dynasty_main's configured starters (config/leagues/registry.json).
DYNASTY_MAIN_SLOTS = [
    "QB", "RB", "RB", "WR", "WR", "WR", "TE", "TE", "FLEX", "FLEX", "SUPER_FLEX",
    "K", "DL", "DL", "DL", "LB", "LB", "LB", "DB", "DB", "DB",
]  # fmt: skip

_BASE = {"QB": 20.0, "RB": 12.0, "WR": 12.0, "TE": 8.0, "K": 8.0, "DL": 8.0, "LB": 9.0, "DB": 7.0}
_COUNTS = {"QB": 3, "RB": 5, "WR": 6, "TE": 3, "K": 1, "DL": 4, "LB": 4, "DB": 4}

WEEKS = list(range(1, 9))


def wobble(week: int, idx: int) -> float:
    return 1.0 + 0.1 * (((week * 7) + (idx * 3)) % 5 - 2)


def standard_roster(tag: str, scale: float = 1.0) -> dict[str, tuple[str, Callable[[int], float]]]:
    """``{pid: (position, week -> points)}`` — a full 30-man team."""
    out: dict[str, tuple[str, Callable[[int], float]]] = {}
    for pos, n in _COUNTS.items():
        for i in range(n):
            depth = 1.0 - 0.15 * i
            base = _BASE[pos] * scale * depth

            def fn(w: int, base=base, i=i, pos=pos) -> float:
                return round(base * wobble(w, i + len(pos)), 2)

            out[f"{tag}-{pos.lower()}{i + 1}"] = (pos, fn)
    return out


def _starters(roster: Mapping[str, float], positions: Mapping[str, str], slots: list[str]):
    pool = [
        RosterPlayer(player_id=p, canonical_name=p, position=positions[p], ros_value=v)
        for p, v in roster.items()
        if v is not None
    ]
    a = solve_optimal_assignment(pool, slots, objective=OBJECTIVE_REALIZED_POINTS)
    starters = [a[i].player_id if i in a else "0" for i in range(len(slots))]
    return starters, round(sum(float(p.ros_value) for p in a.values()), 2)


def build_snapshot(
    teams: Mapping[int, Mapping[str, tuple[str, Callable[[int], float | None]]]],
    *,
    weeks: list[int] = WEEKS,
    slots: list[str] | None = None,
    best_ball: Any = 1,
    ownership: Mapping[str, Mapping[int, int]] | None = None,
    missing_points: set[tuple[str, int]] | None = None,
    playoff_week_start: int = 15,
    status: str = "complete",
    managed_starters: Callable[[int, int, list[str]], list[str]] | None = None,
    season: str = "2025",
    league_id: str = "RC2025",
) -> PublicLeagueSnapshot:
    """``ownership[pid] = {week: rosterId}`` overrides which team holds a player.

    ``missing_points`` drops ``(pid, week)`` from ``players_points`` (a host gap).
    ``managed_starters(rid, week, roster_ids)`` returns submitted starters for a
    managed league (``best_ball=0``).
    """
    slots = list(slots or DYNASTY_MAIN_SLOTS)
    positions = {pid: spec[0] for t in teams.values() for pid, spec in t.items()}
    fns = {pid: spec[1] for t in teams.values() for pid, spec in t.items()}
    home = {pid: rid for rid, t in teams.items() for pid in t}
    ownership = ownership or {}
    missing_points = missing_points or set()
    matchups: dict[int, list[dict[str, Any]]] = {}
    rids = sorted(teams)
    for wk in weeks:
        entries = []
        for rid in rids:
            roster = sorted(
                pid for pid in positions if ownership.get(pid, {}).get(wk, home[pid]) == rid
            )
            pts = {}
            for pid in roster:
                if (pid, wk) in missing_points:
                    continue
                v = fns[pid](wk)
                if v is not None:
                    pts[pid] = v
            if managed_starters is None:
                starters, score = _starters(pts, positions, slots)
            else:
                starters = managed_starters(rid, wk, roster) if managed_starters else []
                score = round(sum(pts.get(p, 0.0) for p in starters if p != "0"), 2)
            entries.append(
                {
                    "roster_id": rid,
                    "matchup_id": (rids.index(rid) // 2) + 1,
                    "points": score,
                    "players": roster,
                    "players_points": pts,
                    "starters": starters,
                }
            )
        matchups[wk] = entries
    league = {
        "league_id": league_id,
        "season": season,
        "status": status,
        "total_rosters": len(rids),
        "roster_positions": slots + ["BN"] * 10,
        "settings": {"best_ball": best_ball, "playoff_week_start": playoff_week_start},
        "scoring_settings": {},
    }
    s = SeasonSnapshot(
        season=season,
        league_id=league_id,
        league=league,
        users=[],
        rosters=[{"roster_id": rid, "owner_id": "", "players": []} for rid in rids],
        matchups_by_week=matchups,
        transactions_by_week={},
        drafts=[],
        draft_picks_by_draft={},
        traded_picks=[],
        winners_bracket=[],
        losers_bracket=[],
    )
    nfl = {
        pid: {"position": pos, "fantasy_positions": [pos], "full_name": pid}
        for pid, pos in positions.items()
    }
    return PublicLeagueSnapshot(
        root_league_id=league_id,
        generated_at="2026-10-30T00:00:00+00:00",
        seasons=[s],
        managers=ManagerRegistry(),
        nfl_players=nfl,
    )


def make_contract(
    league_key: str,
    rosters: Mapping[int, list[str]],
    values: Mapping[str, float | None],
    positions: Mapping[str, str],
    ages: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    ages = ages or {}
    rows = [
        {
            "playerId": pid,
            "displayName": pid,
            "canonicalName": pid,
            "position": positions[pid],
            "rankDerivedValue": v,
            "age": ages.get(pid),
            "assetClass": "player",
        }
        for pid, v in values.items()
    ]
    return {
        "generatedAt": "2026-10-30T00:00:00+00:00",
        "meta": {"leagueKey": league_key},
        "playersArray": rows,
        "sleeper": {
            "teams": [
                {"roster_id": rid, "ownerId": f"o{rid}", "players": list(p), "playerIds": list(p)}
                for rid, p in rosters.items()
            ]
        },
    }


def league_of(n: int = 4, scales: Mapping[int, float] | None = None) -> dict[int, dict]:
    scales = scales or {}
    return {
        rid: standard_roster(f"t{rid}", scales.get(rid, 1.0 - 0.05 * rid))
        for rid in range(1, n + 1)
    }


def clone(x):
    return copy.deepcopy(x)


def positions_of(teams: Mapping[int, Mapping[str, tuple[str, Any]]]) -> dict[str, str]:
    return {pid: spec[0] for t in teams.values() for pid, spec in t.items()}


def compute(
    snapshot: PublicLeagueSnapshot,
    *,
    contract: Mapping[str, Any] | None = None,
    league_key: str = "k",
    roster_id: int | None = 1,
    include_playoffs: bool = False,
    roster_limit: int | None = None,
    posture: Mapping[str, Any] | None = None,
    with_impact: bool = True,
):
    """The production path: snapshot -> player_impact -> construction payload."""
    from src.api import roster_construction_api as api
    from src.public_league import player_impact as pi
    from src.roster_intel import construction as rc

    season = snapshot.seasons[0]
    impact = pi.compute_season(snapshot, season) if with_impact else None
    si = api.season_input_from_snapshot(
        snapshot,
        season,
        include_playoffs=include_playoffs,
        impact=impact,
        roster_limit=roster_limit,
    )
    ls = rc.compute_league_season(si, api.load_priors())
    value = api.value_input_from_contract(contract, league_key, snapshot)
    payload = api.build_payload(
        ls, league_key=league_key, roster_id=roster_id, value=value, posture=posture
    )
    return payload, ls


def flat(team: Mapping[str, tuple[str, Any]], pos: str, pts: float) -> None:
    """Helper: give every ``pos`` player on ``team`` a flat weekly score."""
    for pid, (p, _fn) in list(team.items()):
        if p == pos:
            team[pid] = (p, lambda _w, v=pts: v)
