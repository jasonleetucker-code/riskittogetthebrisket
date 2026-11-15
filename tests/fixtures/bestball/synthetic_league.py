"""A deterministic synthetic league shaped like dynasty_main.

12 teams, 58-man rosters, the 21 starting slots dynasty_main starts
(QB1 RB2 WR3 TE2 FLEX2 SUPER_FLEX1 K1 DL3 LB3 DB3), plus a free-agent pool, a
live rookie auction (rookie rows nobody rosters) and a few unprojected free
agents.  Every number is SYNTHETIC — generated from a fixed seed, never read
from the live board — so tests and the offline report are reproducible and
carry no private league data.

Used by ``tests/bestball/*`` and ``scripts/bestball_marginal_report.py``.
"""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from typing import Any

from src.roster_intel.best_ball_utility import UtilityPlayer

#: dynasty_main's 21 starters, spelled with the lineup owner's canonical names.
DYNASTY_MAIN_SLOTS: tuple[str, ...] = (
    "QB",
    "RB",
    "RB",
    "WR",
    "WR",
    "WR",
    "TE",
    "TE",
    "FLEX",
    "FLEX",
    "SUPER_FLEX",
    "K",
    "DL",
    "DL",
    "DL",
    "LB",
    "LB",
    "LB",
    "DB",
    "DB",
    "DB",
)

TEAMS = 12
ROSTER_SIZE = 58
#: Per-roster position counts (sum 58).
ROSTER_SHAPE: Mapping[str, int] = {
    "QB": 5,
    "RB": 9,
    "WR": 12,
    "TE": 6,
    "K": 2,
    "DL": 8,
    "LB": 8,
    "DB": 8,
}
#: (top-of-position ppg, per-rank decay) — synthetic, roughly league-scored shape.
_POSITION_CURVE: Mapping[str, tuple[float, float]] = {
    "QB": (26.0, 0.25),
    "RB": (20.0, 0.13),
    "WR": (20.0, 0.11),
    "TE": (16.0, 0.16),
    "K": (10.0, 0.04),
    "DL": (14.0, 0.07),
    "LB": (17.0, 0.08),
    "DB": (13.0, 0.06),
}
FREE_AGENTS_PER_POSITION = 12
AUCTION_ROOKIES = 6
UNPROJECTED_FREE_AGENTS = 4
SEASON = 2026


def _ppg(pos: str, rank: int, rng: random.Random) -> float:
    top, decay = _POSITION_CURVE[pos]
    return round(max(0.5, top - decay * rank + rng.uniform(-0.6, 0.6)), 2)


def build_league(seed: int = 20261019) -> dict[str, Any]:
    """``{"contract", "ppg", "slots", "unprojected"}`` for the synthetic league."""
    rng = random.Random(seed)
    rows: list[dict[str, Any]] = []
    ppg: dict[str, float] = {}
    teams: list[dict[str, Any]] = [
        {"rosterId": t + 1, "ownerId": f"owner{t + 1:02d}", "playerIds": [], "players": []}
        for t in range(TEAMS)
    ]
    for pos, per_team in ROSTER_SHAPE.items():
        total = per_team * TEAMS
        for rank in range(total + FREE_AGENTS_PER_POSITION):
            pid = f"{pos.lower()}{rank + 1:03d}"
            name = f"Synthetic {pos} {rank + 1}"
            rows.append(
                {
                    "playerId": pid,
                    "canonicalName": name,
                    "displayName": name,
                    "position": pos,
                    "assetClass": "player",
                    "rankDerivedValue": max(1, 9000 - 25 * rank),
                }
            )
            ppg[pid] = _ppg(pos, rank, rng)
            if rank < total:
                # Snake-ish distribution so every team gets a spread of ranks.
                rnd, slot = divmod(rank, TEAMS)
                team = teams[slot if rnd % 2 == 0 else TEAMS - 1 - slot]
                team["playerIds"].append(pid)
                team["players"].append(name)
    # The live rookie auction: unrostered rookies with a board value.  Strong
    # on purpose — they must never be offered as free replacements.
    for i in range(AUCTION_ROOKIES):
        pos = ("WR", "RB", "TE", "QB", "WR", "RB")[i]
        pid = f"rookie{i + 1:02d}"
        rows.append(
            {
                "playerId": pid,
                "canonicalName": f"Synthetic Rookie {i + 1}",
                "position": pos,
                "assetClass": "player",
                "rookie": True,
                "rankDerivedValue": 8000 - 100 * i,
            }
        )
        ppg[pid] = 18.0 - i
    # Free agents with no projection: listed unpriced, never priced at 0.
    unprojected: list[str] = []
    for i in range(UNPROJECTED_FREE_AGENTS):
        pid = f"noproj{i + 1:02d}"
        rows.append(
            {
                "playerId": pid,
                "canonicalName": f"Synthetic Unprojected {i + 1}",
                "position": ("WR", "TE", "LB", "DB")[i],
                "assetClass": "player",
                "rankDerivedValue": 500,
            }
        )
        unprojected.append(pid)
    # Picks are never waiver replacements.
    rows.append({"canonicalName": "2027 Round 1", "position": "PICK", "assetClass": "pick"})
    contract = {"playersArray": rows, "sleeper": {"teams": teams}}
    return {
        "contract": contract,
        "ppg": ppg,
        "slots": list(DYNASTY_MAIN_SLOTS),
        "unprojected": unprojected,
    }


def ppg_lookup_for(ppg: Mapping[str, float]):
    """A ``league_scored_ppg_by_id``-shaped lookup over the synthetic projections."""

    def _lookup(
        player_ids: Sequence[str], *, season: int, scoring_settings: Mapping[str, Any]
    ) -> tuple[dict[str, float], dict[str, Any]]:
        del scoring_settings
        out = {pid: ppg[pid] for pid in player_ids if pid in ppg}
        return out, {
            "state": "available",
            "reason": None,
            "source": "synthetic_fixture",
            "season": season,
        }

    return _lookup


def roster_for(league: Mapping[str, Any], team_index: int = 0) -> list[UtilityPlayer]:
    """One synthetic team's 58 players as :class:`UtilityPlayer` rows."""
    contract = league["contract"]
    by_id = {r["playerId"]: r for r in contract["playersArray"] if r.get("playerId")}
    team = contract["sleeper"]["teams"][team_index]
    return [
        UtilityPlayer(
            player_id=pid,
            name=by_id[pid]["canonicalName"],
            position=by_id[pid]["position"],
            ppg=league["ppg"].get(pid),
        )
        for pid in team["playerIds"]
    ]


def rostered_ids(league: Mapping[str, Any]) -> list[str]:
    return [pid for t in league["contract"]["sleeper"]["teams"] for pid in t["playerIds"]]
