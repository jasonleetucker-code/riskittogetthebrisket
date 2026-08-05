"""``GET /api/player/{sleeper_id}/realized`` — the identity join.

The route read ``sleeper.players`` / ``sleeper.playerDict``.  The
producer writes ``sleeper.idToPlayer`` + ``sleeper.positions``.  No
writer has ever produced the key the reader asked for, so
``resolve_player`` indexed ``None`` and the route answered
``unmapped_player`` for **937 of 937** id-carrying board rows — every
player, every league, with the stats fetch succeeding first (audit
W06-F003).

``tests/api/test_realized_points_endpoint.py`` re-implements the row
filter and therefore could not see this: it never reaches the route.
These tests drive the real handler.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import server

_GSIS = "00-0035676"

_CONTRACT = {
    "sleeper": {
        "leagueId": "1",
        "idToPlayer": {"5859": "A.J. Brown", "4984": "Josh Allen"},
        "positions": {"A.J. Brown": "WR", "Josh Allen": "QB"},
        "scoringSettings": {"rec": 1.0, "rec_yd": 0.1, "rec_td": 6.0},
    }
}


def _weekly_rows() -> list[dict]:
    return [
        {
            "player_id": _GSIS,
            "player_display_name": "A.J. Brown",
            "position": "WR",
            "season": 2025,
            "week": week,
            "receptions": 5,
            "receiving_yards": 60,
            "receiving_tds": 1,
        }
        for week in (1, 2, 3)
    ] + [
        {
            "player_id": "00-0034857",
            "player_display_name": "Josh Allen",
            "position": "QB",
            "season": 2025,
            "week": 1,
            "passing_yards": 300,
            "passing_tds": 3,
        }
    ]


class _League:
    key = "dynasty_main"


@pytest.fixture
def authed(monkeypatch):
    monkeypatch.setattr(server, "_is_authenticated", lambda r: True)
    monkeypatch.setattr(server, "_get_auth_session", lambda r: {"username": "jasonleetucker"})
    monkeypatch.setattr(server, "latest_contract_data", _CONTRACT)
    # The test env ships no league registry; league resolution is not
    # what these tests are about.
    monkeypatch.setattr(server, "_resolve_league_for_request", lambda r: _League())
    from src.api import feature_flags
    from src.nfl_data import ingest as _ing

    monkeypatch.setenv("RISKIT_FEATURE_REALIZED_POINTS_API", "1")
    feature_flags.reload()
    monkeypatch.setattr(_ing, "fetch_weekly_stats", lambda years, **kw: _weekly_rows())
    yield
    feature_flags.reload()


def _get(sleeper_id: str) -> dict:
    # Deliberately NOT a `with` block: the startup lifespan reloads
    # ``latest_contract_data`` from disk and would silently replace the
    # fixture's contract with whatever the container last scraped.
    client = TestClient(server.app, raise_server_exceptions=True)
    res = client.get(f"/api/player/{sleeper_id}/realized")
    assert res.status_code == 200, res.text
    return res.json()


def test_a_rostered_player_resolves_to_real_weeks(authed):
    """THE defect: this returned reason=unmapped_player with weeks=[]
    for every player on every board."""
    body = _get("5859")
    assert body.get("reason") != "unmapped_player", body
    assert body["gsisId"] == _GSIS
    assert body["weekCount"] == 3
    assert body["totalPoints"] > 0


def test_only_that_players_weeks_are_returned(authed):
    """The control — a directory that resolved everyone to one id would
    pass the test above."""
    body = _get("4984")
    assert body["gsisId"] == "00-0034857"
    assert body["weekCount"] == 1


def test_the_response_stamps_where_the_identity_came_from(authed):
    body = _get("5859")
    assert body["identity"]["source"].startswith("contract_sleeper_block")
    assert body["identity"]["gsisResolved"] == 2
    assert body["identity"]["matchMethod"] == "sleeper_id"


def test_an_unresolvable_id_says_which_way_it_failed(authed):
    """Absence stays representable: still ``unmapped_player``, but the
    count of what the join could not reach rides out with it."""
    body = _get("123456789")
    assert body["reason"] == "unmapped_player"
    assert body["identity"]["detail"] == "unknown_sleeper_id"
    assert body["identity"]["entries"] == 2
