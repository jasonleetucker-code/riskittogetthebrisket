"""PublicLeagueSnapshot.player_position must collapse Sleeper
multi-position players using DL > DB > LB, matching every other
IDP-position reader in the repo."""
from __future__ import annotations

from src.public_league.snapshot import PublicLeagueSnapshot


def _snap_with_players(players_map):
    snap = PublicLeagueSnapshot(
        root_league_id="x",
        generated_at="2026-04-18T00:00:00Z",
    )
    snap.nfl_players = players_map  # type: ignore[assignment]
    return snap


def test_player_position_uses_dl_over_lb():
    snap = _snap_with_players(
        {
            "a": {"position": "OLB", "fantasy_positions": ["DL", "LB"]},
        },
    )
    assert snap.player_position("a") == "DL"


def test_player_position_uses_db_over_lb():
    snap = _snap_with_players(
        {
            "a": {"position": "LB", "fantasy_positions": ["LB", "CB"]},
        },
    )
    assert snap.player_position("a") == "DB"


def test_player_position_exclusive_lb_stays_lb():
    snap = _snap_with_players(
        {
            "a": {"position": "LB", "fantasy_positions": ["LB"]},
        },
    )
    assert snap.player_position("a") == "LB"


def test_non_idp_falls_through_to_single_position():
    snap = _snap_with_players(
        {
            "qb": {"position": "QB", "fantasy_positions": ["QB"]},
        },
    )
    assert snap.player_position("qb") == "QB"


def test_missing_fantasy_positions_uses_single_position():
    snap = _snap_with_players(
        {
            "a": {"position": "DE"},  # no fantasy_positions
        },
    )
    assert snap.player_position("a") == "DL"
