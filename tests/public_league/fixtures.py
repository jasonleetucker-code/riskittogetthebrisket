"""Fixtures for the public league pipeline tests.

Provides a fully-deterministic two-season league chain with:
    * A manager who renamed their team between seasons (alias test).
    * A roster that changed hands between seasons (orphan-handoff test)
      so we can assert history correctly attributes each season to the
      owner_id who actually held the roster at the time.
"""
from __future__ import annotations

from typing import Any


def _user(uid: str, display_name: str, team_name: str) -> dict[str, Any]:
    return {
        "user_id": uid,
        "display_name": display_name,
        "metadata": {"team_name": team_name},
        "avatar": f"avatar_{uid}",
    }


def _roster(rid: int, owner_id: str, wins: int = 0, losses: int = 0, ties: int = 0, pf: float = 0.0, pa: float = 0.0) -> dict[str, Any]:
    pf_int = int(pf)
    pf_dec = int(round((pf - pf_int) * 100))
    pa_int = int(pa)
    pa_dec = int(round((pa - pa_int) * 100))
    return {
        "roster_id": rid,
        "owner_id": owner_id,
        "players": [],
        "settings": {
            "wins": wins,
            "losses": losses,
            "ties": ties,
            "fpts": pf_int,
            "fpts_decimal": pf_dec,
            "fpts_against": pa_int,
            "fpts_against_decimal": pa_dec,
        },
    }


# Four managers.  owner-A renamed their team between seasons.
# owner-D only appears in 2024 (took over roster 4 from owner-X mid-chain).
USERS_2025 = [
    _user("owner-A", "AAron", "Brisket Bandits"),   # renamed from "AAron Classic"
    _user("owner-B", "Bea",   "Bea's Beast Mode"),
    _user("owner-C", "Cole",  "Cole Train"),
    _user("owner-D", "Dana",  "Dana's Dynasty"),    # took over roster_id 4
]
USERS_2024 = [
    _user("owner-A", "AAron", "AAron Classic"),     # OLD team name
    _user("owner-B", "Bea",   "Bea's Beast Mode"),
    _user("owner-C", "Cole",  "Cole Train"),
    _user("owner-X", "Xavier", "Xavier XL"),        # previous owner of roster 4
]

ROSTERS_2025 = [
    _roster(1, "owner-A", wins=9, losses=5, pf=1450.12, pa=1320.44),
    _roster(2, "owner-B", wins=11, losses=3, pf=1600.50, pa=1200.10),
    _roster(3, "owner-C", wins=5, losses=9, pf=1250.00, pa=1520.80),
    _roster(4, "owner-D", wins=7, losses=7, pf=1380.30, pa=1405.20),
]
ROSTERS_2024 = [
    _roster(1, "owner-A", wins=8, losses=6, pf=1390.10, pa=1400.30),
    _roster(2, "owner-B", wins=12, losses=2, pf=1700.00, pa=1150.00),
    _roster(3, "owner-C", wins=6, losses=8, pf=1295.50, pa=1480.90),
    _roster(4, "owner-X", wins=3, losses=11, pf=1100.00, pa=1580.10),
]


MATCHUPS_2025 = {
    1: [
        {"matchup_id": 1, "roster_id": 1, "points": 120.5},
        {"matchup_id": 1, "roster_id": 2, "points": 135.2},
        {"matchup_id": 2, "roster_id": 3, "points": 95.0},
        {"matchup_id": 2, "roster_id": 4, "points": 110.3},
    ],
    2: [
        {"matchup_id": 1, "roster_id": 1, "points": 145.8},
        {"matchup_id": 1, "roster_id": 3, "points": 142.1},
        {"matchup_id": 2, "roster_id": 2, "points": 165.0},
        {"matchup_id": 2, "roster_id": 4, "points": 95.6},
    ],
}
MATCHUPS_2024 = {
    1: [
        {"matchup_id": 1, "roster_id": 1, "points": 115.0},
        {"matchup_id": 1, "roster_id": 4, "points": 80.5},  # owner-X was here
        {"matchup_id": 2, "roster_id": 2, "points": 150.0},
        {"matchup_id": 2, "roster_id": 3, "points": 105.2},
    ],
}


TRADE_2025_WK3 = {
    "transaction_id": "tx-2025-a",
    "type": "trade",
    "status": "complete",
    "created": 1_730_000_000_000,
    "leg": 3,
    "roster_ids": [1, 2],
    "adds": {"p1": 2, "p2": 1},
    "drops": {"p1": 1, "p2": 2},
    "draft_picks": [
        {"season": "2026", "round": 2, "roster_id": 1, "previous_owner_id": 1, "owner_id": 2},
    ],
}


DRAFT_2025 = {
    "draft_id": "draft-2025",
    "type": "rookie",
    "status": "complete",
    "season": "2025",
    "start_time": 1_720_000_000_000,
    "settings": {"rounds": 5},
}

DRAFT_PICKS_2025 = [
    {"round": 1, "pick_no": 1, "roster_id": 3, "player_id": "pid-101",
     "metadata": {"first_name": "Ashton", "last_name": "Jeanty", "position": "RB", "team": "LV"}},
    {"round": 1, "pick_no": 2, "roster_id": 4, "player_id": "pid-102",
     "metadata": {"first_name": "Travis", "last_name": "Hunter", "position": "WR", "team": "JAX"}},
]


LEAGUE_2025 = {
    "league_id": "L2025",
    "name": "Brisket Dynasty",
    "season": "2025",
    "season_type": "regular",
    "status": "complete",
    "total_rosters": 4,
    "previous_league_id": "L2024",
}
LEAGUE_2024 = {
    "league_id": "L2024",
    "name": "Brisket Dynasty",
    "season": "2024",
    "season_type": "regular",
    "status": "complete",
    "total_rosters": 4,
    "previous_league_id": None,
}

WINNERS_BRACKET_2025 = [
    # Round 1 semifinals
    {"r": 1, "t1": 2, "t2": 4, "w": 2, "l": 4},
    {"r": 1, "t1": 1, "t2": 3, "w": 1, "l": 3},
    # Championship + 3rd place
    {"r": 2, "t1": 2, "t2": 1, "w": 2, "l": 1, "p": 1},
    {"r": 2, "t1": 4, "t2": 3, "w": 4, "l": 3, "p": 3},
]
WINNERS_BRACKET_2024 = [
    {"r": 1, "t1": 2, "t2": 3, "w": 2, "l": 3},
    {"r": 1, "t1": 1, "t2": 4, "w": 1, "l": 4},
    {"r": 2, "t1": 2, "t2": 1, "w": 2, "l": 1, "p": 1},
    {"r": 2, "t1": 3, "t2": 4, "w": 3, "l": 4, "p": 3},
]


def build_stub_client():
    """Return a dict-of-functions overriding every sleeper_client entry
    point used by build_public_snapshot.  Install with
    ``monkeypatch.setattr('src.public_league.sleeper_client.<name>', stub[name])``.
    """
    league_by_id = {"L2025": LEAGUE_2025, "L2024": LEAGUE_2024}
    users_by_id = {"L2025": USERS_2025, "L2024": USERS_2024}
    rosters_by_id = {"L2025": ROSTERS_2025, "L2024": ROSTERS_2024}
    matchups_by_id = {"L2025": MATCHUPS_2025, "L2024": MATCHUPS_2024}
    transactions_by_id = {
        "L2025": {3: [TRADE_2025_WK3]},
        "L2024": {},
    }
    drafts_by_id = {"L2025": [DRAFT_2025], "L2024": []}
    draft_picks_by_id = {"draft-2025": DRAFT_PICKS_2025}
    traded_picks_by_id = {
        "L2025": [{"season": "2026", "round": 3, "roster_id": 3, "owner_id": 1}],
        "L2024": [],
    }
    winners_by_id = {"L2025": WINNERS_BRACKET_2025, "L2024": WINNERS_BRACKET_2024}

    return {
        "fetch_league": lambda lid: league_by_id.get(lid),
        "fetch_users": lambda lid: users_by_id.get(lid, []),
        "fetch_rosters": lambda lid: rosters_by_id.get(lid, []),
        "fetch_matchups": lambda lid, wk: matchups_by_id.get(lid, {}).get(wk, []),
        "fetch_transactions": lambda lid, wk: transactions_by_id.get(lid, {}).get(wk, []),
        "fetch_drafts": lambda lid: drafts_by_id.get(lid, []),
        "fetch_draft_picks": lambda did: draft_picks_by_id.get(did, []),
        "fetch_traded_picks": lambda lid: traded_picks_by_id.get(lid, []),
        "fetch_winners_bracket": lambda lid: winners_by_id.get(lid, []),
        "fetch_losers_bracket": lambda lid: [],
        "fetch_draft_detail": lambda did: None,
    }


def install_stubs(stubs):
    """Overwrite sleeper_client module attributes with stubs dict entries."""
    from src.public_league import sleeper_client

    for name, fn in stubs.items():
        setattr(sleeper_client, name, fn)
