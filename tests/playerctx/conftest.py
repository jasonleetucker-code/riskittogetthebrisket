"""Shared fixtures for the playerctx suite — small CSV builders that
mirror the live nflverse schemas (verified 2026-07-25).  No network."""

from __future__ import annotations

import gzip
from pathlib import Path

import pytest

CONTRACTS_HEADER = (
    "player,position,team,is_active,year_signed,years,value,apy,"
    "guaranteed,apy_cap_pct,player_page,otc_id,draft_year"
)

SNAPS_HEADER = (
    "game_id,pfr_game_id,season,game_type,week,player,pfr_player_id,"
    "position,team,opponent,offense_snaps,offense_pct,defense_snaps,"
    "defense_pct,st_snaps,st_pct"
)

DEPTH_HEADER = (
    "dt,team,player_name,espn_id,gsis_id,pos_grp_id,pos_grp,pos_id,"
    "pos_name,pos_abb,pos_slot,pos_rank"
)


def write_csv(path: Path, header: str, rows: list[str]) -> Path:
    text = header + "\n" + "\n".join(rows) + "\n"
    if path.name.endswith(".gz"):
        path.write_bytes(gzip.compress(text.encode("utf-8")))
    else:
        path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def players_dir() -> dict[str, dict[str, str]]:
    """A Sleeper pool shaped like ``normalize.build_sleeper_pool`` output."""
    return {
        "4034": {
            "player_id": "4034",
            "full_name": "Christian McCaffrey",
            "position": "RB",
            "team": "SF",
            "gsis_id": "00-0033280",
            "espn_id": "3117251",
        },
        "6794": {
            "player_id": "6794",
            "full_name": "Justin Jefferson",
            "position": "WR",
            "team": "MIN",
            "gsis_id": "00-0036322",
            "espn_id": "4262921",
        },
        "9999": {
            "player_id": "9999",
            "full_name": "Micah Parsons",
            "position": "DL",
            "team": "DAL",
            "gsis_id": "00-0036933",
            "espn_id": "4361429",
        },
        # No gsis_id — joinable but unkeyable; must be dropped+counted.
        "7777": {
            "player_id": "7777",
            "full_name": "Ghost Nogsis",
            "position": "WR",
            "team": "CHI",
            "gsis_id": "",
            "espn_id": "1234567",
        },
    }
