"""Labelled SYNTHETIC fixtures for the Market Trade Ledger tests.

No captured vendor page, no real league id and no real trade is committed:
every row below is invented, shaped like the measured surfaces (KTC trade
database inline arrays; Sleeper league objects; intel-ledger movements).
"""

from __future__ import annotations

import json
from typing import Any

from src.trade.market_trade_normalize import IdentityContext

# A tiny Sleeper /players/nfl directory.  Two active "Sam Homonym" WRs make a
# genuinely ambiguous name.
DIRECTORY: dict[str, dict[str, Any]] = {
    "1001": {"full_name": "Alpha Receiver", "position": "WR", "team": "AAA", "active": True},
    "1002": {"full_name": "Bravo Runner", "position": "RB", "team": "BBB", "active": True},
    "1003": {"full_name": "Charlie Passer", "position": "QB", "team": "CCC", "active": True},
    "1004": {"full_name": "Delta Tight", "position": "TE", "team": "DDD", "active": True},
    "1005": {"full_name": "Sam Homonym", "position": "WR", "team": "EEE", "active": True},
    "1006": {"full_name": "Sam Homonym", "position": "WR", "team": "FFF", "active": True},
    "2001": {"full_name": "Echo Edge", "position": "DE", "team": "GGG", "active": True},
    "2002": {"full_name": "Foxtrot Backer", "position": "LB", "team": "HHH", "active": True},
}


def ctx() -> IdentityContext:
    return IdentityContext.from_directory(DIRECTORY, source="synthetic")


# KTC search-index rows: numeric ids for players and tier picks.
KTC_INDEX = [
    {"playerName": "Alpha Receiver", "playerID": 11, "position": "WR"},
    {"playerName": "Bravo Runner", "playerID": 12, "position": "RB"},
    {"playerName": "Charlie Passer", "playerID": 13, "position": "QB"},
    {"playerName": "Delta Tight", "playerID": 14, "position": "TE"},
    {"playerName": "Sam Homonym", "playerID": 15, "position": "WR"},
    {"playerName": "Nobody Known", "playerID": 16, "position": "WR"},
    {"playerName": "2027 Early 1st", "playerID": 901, "position": "RDP"},
    {"playerName": "2027 Mid 1st", "playerID": 902, "position": "RDP"},
]


def ktc_settings(
    league_id: str = "L-SYN-1",
    *,
    platform: str = "sleeper",
    qbs: int = 2,
    teams: int = 12,
    tep: int = 1,
    lineup: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    url = (
        f"https://sleeper.app/leagues/{league_id}"
        if platform == "sleeper"
        else f"https://myfantasyleague.com/2026/home/{league_id}"
    )
    return {
        "id": league_id,
        "dynastyPlatformType": 2 if platform == "sleeper" else 1,
        "teams": teams,
        "qBs": qbs,
        "ppr": 3,
        "tep": tep,
        "is2TE": False,
        "passTDPoints": 4.0,
        "leagueStartingLineup": {
            "position": lineup
            or [
                {"limit": "1-2" if qbs >= 2 else "1", "name": "QB"},
                {"limit": "2-5", "name": "RB"},
                {"limit": "3-6", "name": "WR"},
                {"limit": "1-4", "name": "TE"},
            ],
            "count": "10",
        },
        "rostersPerPlayer": 1,
        "leagueUrl": url,
        "leagueYear": 0,
    }


def ktc_row(
    trade_id: int,
    one: list[Any],
    two: list[Any],
    *,
    date: str = "2026-10-01T00:00:00",
    settings: dict[str, Any] | None = None,
    used_in_vft: bool = True,
) -> dict[str, Any]:
    return {
        "id": trade_id,
        "date": date,
        "teamOne": {"place": 1, "playerIds": [str(x) for x in one], "isVftFavored": True},
        "teamTwo": {"place": 2, "playerIds": [str(x) for x in two], "isVftFavored": False},
        "settings": settings or ktc_settings(),
        "isUsedInVft": used_in_vft,
    }


def ktc_page(rows: list[dict[str, Any]], index: list[dict[str, Any]] | None = None) -> str:
    return (
        "<html><head><title>Dynasty Trade Database</title></head><body><script>"
        f"var trades = {json.dumps(rows)};\n"
        f"var allPlayerSearchValues = {json.dumps(index if index is not None else KTC_INDEX)};\n"
        "var leagueType = 1;</script></body></html>"
    )


def sleeper_league(
    league_id: str = "L-SYN-1",
    *,
    roster_positions: list[str] | None = None,
    scoring: dict[str, float] | None = None,
    teams: int = 12,
    ltype: int = 2,
    best_ball: int = 1,
    taxi: int = 0,
) -> dict[str, Any]:
    return {
        "league_id": league_id,
        "season": "2026",
        "total_rosters": teams,
        "roster_positions": roster_positions if roster_positions is not None else TARGET_POSITIONS,
        "scoring_settings": dict(scoring if scoring is not None else TARGET_SCORING),
        "settings": {"type": ltype, "best_ball": best_ball, "num_teams": teams, "taxi_slots": taxi},
    }


#: A dynasty_main-shaped league: 12 teams, QB/2RB/3WR/2TE/2FLEX/SF/K, 3DL/3LB/3DB.
TARGET_POSITIONS = (
    ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "TE", "FLEX", "FLEX", "SUPER_FLEX", "K"]
    + ["DL", "DL", "DL", "LB", "LB", "LB", "DB", "DB", "DB"]
    + ["BN"] * 37
)
TARGET_SCORING: dict[str, float] = {
    "rec": 0.1,
    "bonus_rec_wr": 0.02,
    "bonus_fd_te": 1.0,
    "pass_td": 6.0,
    "pass_int": -4.0,
    "rush_yd": 0.1,
    "rec_yd": 0.1,
    "idp_tkl_solo": 1.33,
    "idp_tkl_ast": 0.8,
    "idp_sack": 2.92,
    "idp_pass_def": 5.3,
    "idp_int": 5.3,
}
