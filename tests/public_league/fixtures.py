"""Fixtures for the public league pipeline tests.

Provides a fully-deterministic two-season league chain with:
    * A manager who renamed their team between seasons (alias test).
    * A roster that changed hands between seasons (orphan-handoff test).
    * Regular-season + playoff weeks (week 1 reg, week 2 reg, week 3
      playoff), so streak / playoff-records / standings-mover
      computations have real input.
    * Completed trades with players + picks.
    * Completed waivers with FAAB bids.
    * Rookie draft with metadata.
    * Traded picks so the Draft Center pick-ownership map has data.
    * NFL players dump stub so position-based superlatives work.
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


def _roster(rid: int, owner_id: str, players: list[str], wins: int = 0, losses: int = 0, ties: int = 0, pf: float = 0.0, pa: float = 0.0, rank: int | None = None) -> dict[str, Any]:
    pf_int = int(pf)
    pf_dec = int(round((pf - pf_int) * 100))
    pa_int = int(pa)
    pa_dec = int(round((pa - pa_int) * 100))
    settings = {
        "wins": wins,
        "losses": losses,
        "ties": ties,
        "fpts": pf_int,
        "fpts_decimal": pf_dec,
        "fpts_against": pa_int,
        "fpts_against_decimal": pa_dec,
    }
    if rank is not None:
        settings["rank"] = rank
    return {
        "roster_id": rid,
        "owner_id": owner_id,
        "players": list(players),
        "settings": settings,
    }


# Player ID catalogue for the NFL players stub.  ``years_exp`` is used
# by the rookie-superlative calculation; we make pid-rookie players
# have years_exp=0.
NFL_PLAYERS_STUB: dict[str, dict[str, Any]] = {
    "p-qb1":  {"first_name": "Ann",   "last_name": "QB-One",   "position": "QB", "years_exp": 5},
    "p-qb2":  {"first_name": "Bob",   "last_name": "QB-Two",   "position": "QB", "years_exp": 3},
    "p-rb1":  {"first_name": "Cam",   "last_name": "RB-One",   "position": "RB", "years_exp": 4},
    "p-rb2":  {"first_name": "Dan",   "last_name": "RB-Two",   "position": "RB", "years_exp": 0},
    "p-rb3":  {"first_name": "Eve",   "last_name": "RB-Three", "position": "RB", "years_exp": 2},
    "p-wr1":  {"first_name": "Flo",   "last_name": "WR-One",   "position": "WR", "years_exp": 6},
    "p-wr2":  {"first_name": "Gus",   "last_name": "WR-Two",   "position": "WR", "years_exp": 0},
    "p-wr3":  {"first_name": "Hal",   "last_name": "WR-Three", "position": "WR", "years_exp": 2},
    "p-te1":  {"first_name": "Iva",   "last_name": "TE-One",   "position": "TE", "years_exp": 7},
    "p-te2":  {"first_name": "Jax",   "last_name": "TE-Two",   "position": "TE", "years_exp": 1},
    "p-idp1": {"first_name": "Kim",   "last_name": "DL-One",   "position": "DL", "years_exp": 3},
    "p-idp2": {"first_name": "Leo",   "last_name": "LB-One",   "position": "LB", "years_exp": 0},
    "p-idp3": {"first_name": "Max",   "last_name": "DB-One",   "position": "DB", "years_exp": 2},
    "p-rookie-a": {"first_name": "Rudy", "last_name": "Rook", "position": "WR", "years_exp": 0},
    "p-rookie-b": {"first_name": "Sal",  "last_name": "Stud", "position": "RB", "years_exp": 0},
}


# Roster inventories.  Different positional tilts so superlatives
# produce deterministic winners.
ROSTER_A_PLAYERS = ["p-qb1", "p-qb2", "p-rb1", "p-wr1", "p-te1", "p-rookie-a"]   # QB-heavy, rookies=2 (p-rb2 added in wk3 waiver)
ROSTER_B_PLAYERS = ["p-rb3", "p-rb2", "p-wr1", "p-wr2", "p-te1", "p-rookie-b"]    # RB-heavy, rookies=2
ROSTER_C_PLAYERS = ["p-wr1", "p-wr2", "p-wr3", "p-rb1", "p-qb1", "p-idp3"]        # WR-heavy
ROSTER_D_PLAYERS = ["p-te1", "p-te2", "p-idp1", "p-idp2", "p-idp3", "p-qb2"]       # IDP/TE-heavy


USERS_2025 = [
    _user("owner-A", "AAron", "Brisket Bandits"),
    _user("owner-B", "Bea",   "Bea's Beast Mode"),
    _user("owner-C", "Cole",  "Cole Train"),
    _user("owner-D", "Dana",  "Dana's Dynasty"),
]
USERS_2024 = [
    _user("owner-A", "AAron", "AAron Classic"),
    _user("owner-B", "Bea",   "Bea's Beast Mode"),
    _user("owner-C", "Cole",  "Cole Train"),
    _user("owner-X", "Xavier", "Xavier XL"),
]

ROSTERS_2025 = [
    _roster(1, "owner-A", ROSTER_A_PLAYERS, wins=9,  losses=5, pf=1450.12, pa=1320.44, rank=2),
    _roster(2, "owner-B", ROSTER_B_PLAYERS, wins=11, losses=3, pf=1600.50, pa=1200.10, rank=1),
    _roster(3, "owner-C", ROSTER_C_PLAYERS, wins=5,  losses=9, pf=1250.00, pa=1520.80, rank=4),
    _roster(4, "owner-D", ROSTER_D_PLAYERS, wins=7,  losses=7, pf=1380.30, pa=1405.20, rank=3),
]
ROSTERS_2024 = [
    _roster(1, "owner-A", ROSTER_A_PLAYERS, wins=8,  losses=6, pf=1390.10, pa=1400.30, rank=2),
    _roster(2, "owner-B", ROSTER_B_PLAYERS, wins=12, losses=2, pf=1700.00, pa=1150.00, rank=1),
    _roster(3, "owner-C", ROSTER_C_PLAYERS, wins=6,  losses=8, pf=1295.50, pa=1480.90, rank=3),
    _roster(4, "owner-X", ["p-qb1", "p-rb1"], wins=3,  losses=11, pf=1100.00, pa=1580.10, rank=4),
]


# Matchups — weeks 1 & 2 regular season, week 15 playoffs.
MATCHUPS_2025 = {
    1: [
        {"matchup_id": 1, "roster_id": 1, "points": 120.5},
        {"matchup_id": 1, "roster_id": 2, "points": 135.2},   # B beats A by 14.7
        {"matchup_id": 2, "roster_id": 3, "points": 95.0},
        {"matchup_id": 2, "roster_id": 4, "points": 110.3},   # D beats C by 15.3
    ],
    2: [
        {"matchup_id": 1, "roster_id": 1, "points": 145.8},
        {"matchup_id": 1, "roster_id": 3, "points": 142.1},   # A beats C by 3.7 (close)
        {"matchup_id": 2, "roster_id": 2, "points": 165.0},
        {"matchup_id": 2, "roster_id": 4, "points": 95.6},    # B beats D by 69.4 (blowout)
    ],
    15: [
        # Playoff semifinals.
        {"matchup_id": 1, "roster_id": 2, "points": 155.5},
        {"matchup_id": 1, "roster_id": 4, "points": 130.0},   # B beats D by 25.5
        {"matchup_id": 2, "roster_id": 1, "points": 150.0},
        {"matchup_id": 2, "roster_id": 3, "points": 140.0},   # A beats C by 10.0
    ],
    16: [
        # Playoff championship: B vs A.
        {"matchup_id": 1, "roster_id": 2, "points": 145.0},
        {"matchup_id": 1, "roster_id": 1, "points": 120.0},   # B beats A by 25.0
    ],
}
MATCHUPS_2024 = {
    1: [
        {"matchup_id": 1, "roster_id": 1, "points": 115.0},
        {"matchup_id": 1, "roster_id": 4, "points": 80.5},
        {"matchup_id": 2, "roster_id": 2, "points": 150.0},
        {"matchup_id": 2, "roster_id": 3, "points": 105.2},
    ],
    2: [
        {"matchup_id": 1, "roster_id": 1, "points": 130.0},
        {"matchup_id": 1, "roster_id": 2, "points": 155.0},   # B beats A (2nd reg meeting)
        {"matchup_id": 2, "roster_id": 3, "points": 110.0},
        {"matchup_id": 2, "roster_id": 4, "points": 112.0},   # X (owner-X) beats C close
    ],
    3: [
        # Upsets across the board:
        #   A (1-1) beats B (2-0)
        #   C (0-2) beats X (1-1)
        {"matchup_id": 1, "roster_id": 1, "points": 125.0},
        {"matchup_id": 1, "roster_id": 2, "points": 120.0},
        {"matchup_id": 2, "roster_id": 3, "points": 130.0},
        {"matchup_id": 2, "roster_id": 4, "points": 110.0},
    ],
}


TRADE_2025_WK3 = {
    "transaction_id": "tx-2025-a",
    "type": "trade",
    "status": "complete",
    "created": 1_730_000_000_000,
    "leg": 3,
    "roster_ids": [1, 2],
    "adds": {"p-rb2": 1, "p-wr2": 2},
    "drops": {"p-rb2": 2, "p-wr2": 1},
    "draft_picks": [
        {"season": "2026", "round": 2, "roster_id": 1, "previous_owner_id": 1, "owner_id": 2},
        {"season": "2026", "round": 4, "roster_id": 2, "previous_owner_id": 2, "owner_id": 1},
    ],
}
TRADE_2024_WK5 = {
    "transaction_id": "tx-2024-a",
    "type": "trade",
    "status": "complete",
    "created": 1_700_000_000_000,
    "leg": 5,
    "roster_ids": [1, 3],
    "adds": {"p-wr3": 1},
    "drops": {"p-wr3": 3},
    "draft_picks": [],
}

WAIVER_2025_WK1 = {
    "transaction_id": "wv-2025-a",
    "type": "waiver",
    "status": "complete",
    "created": 1_728_000_000_000,
    "leg": 1,
    "roster_ids": [3],
    "adds": {"p-wr3": 3},
    "drops": {},
    "settings": {"waiver_bid": 42},
}
WAIVER_2024_WK4 = {
    "transaction_id": "wv-2024-a",
    "type": "waiver",
    "status": "complete",
    "created": 1_698_000_000_000,
    "leg": 4,
    "roster_ids": [2],
    "adds": {"p-rb3": 2},
    "drops": {},
    "settings": {"waiver_bid": 17},
}
FA_2024_WK3 = {
    "transaction_id": "fa-2024-a",
    "type": "free_agent",
    "status": "complete",
    "created": 1_697_000_000_000,
    "leg": 3,
    "roster_ids": [4],
    "adds": {"p-idp1": 4},
    "drops": {},
}


DRAFT_2025 = {
    "draft_id": "draft-2025",
    "type": "rookie",
    "status": "complete",
    "season": "2025",
    "start_time": 1_720_000_000_000,
    "settings": {"rounds": 4},
}

DRAFT_PICKS_2025 = [
    {"round": 1, "pick_no": 1, "roster_id": 3, "player_id": "p-rookie-a",
     "metadata": {"first_name": "Rudy", "last_name": "Rook", "position": "WR", "team": "LV"}},
    {"round": 1, "pick_no": 2, "roster_id": 4, "player_id": "p-rookie-b",
     "metadata": {"first_name": "Sal", "last_name": "Stud", "position": "RB", "team": "JAX"}},
]


LEAGUE_2025 = {
    "league_id": "L2025",
    "name": "Brisket Dynasty",
    "season": "2025",
    "season_type": "regular",
    "status": "complete",
    "total_rosters": 4,
    "previous_league_id": "L2024",
    "settings": {"playoff_week_start": 15, "draft_rounds": 4},
}
LEAGUE_2024 = {
    "league_id": "L2024",
    "name": "Brisket Dynasty",
    "season": "2024",
    "season_type": "regular",
    "status": "complete",
    "total_rosters": 4,
    "previous_league_id": None,
    "settings": {"playoff_week_start": 15, "draft_rounds": 4},
}

WINNERS_BRACKET_2025 = [
    {"r": 1, "t1": 2, "t2": 4, "w": 2, "l": 4},
    {"r": 1, "t1": 1, "t2": 3, "w": 1, "l": 3},
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
    """Return a dict of functions overriding sleeper_client entry points."""
    league_by_id = {"L2025": LEAGUE_2025, "L2024": LEAGUE_2024}
    users_by_id = {"L2025": USERS_2025, "L2024": USERS_2024}
    rosters_by_id = {"L2025": ROSTERS_2025, "L2024": ROSTERS_2024}
    matchups_by_id = {"L2025": MATCHUPS_2025, "L2024": MATCHUPS_2024}
    transactions_by_id = {
        "L2025": {3: [TRADE_2025_WK3], 1: [WAIVER_2025_WK1]},
        "L2024": {5: [TRADE_2024_WK5], 4: [WAIVER_2024_WK4], 3: [FA_2024_WK3]},
    }
    drafts_by_id = {"L2025": [DRAFT_2025], "L2024": []}
    draft_picks_by_id = {"draft-2025": DRAFT_PICKS_2025}
    traded_picks_by_id = {
        "L2025": [
            {"season": "2026", "round": 2, "roster_id": 1, "owner_id": 2},
            {"season": "2026", "round": 4, "roster_id": 2, "owner_id": 1},
            {"season": "2027", "round": 3, "roster_id": 3, "owner_id": 1},
        ],
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
        "fetch_nfl_players": lambda: NFL_PLAYERS_STUB,
    }


def install_stubs(stubs):
    from src.public_league import sleeper_client

    for name, fn in stubs.items():
        setattr(sleeper_client, name, fn)


def build_test_snapshot():
    """Convenience: build + return a fully-populated snapshot for tests."""
    from src.public_league import build_public_snapshot
    from src.public_league import sleeper_client

    install_stubs(build_stub_client())
    sleeper_client.reset_nfl_players_cache()
    snapshot = build_public_snapshot("L2025", max_seasons=2, include_nfl_players=True)
    # Replace NFL players with fixture stub directly (cache may return live).
    snapshot.nfl_players = NFL_PLAYERS_STUB
    return snapshot
