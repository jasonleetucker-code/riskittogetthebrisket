"""`GET /api/player/{sleeper_id}/realized` — the row filter.

The endpoint filtered weekly stats on `player_id_gsis`, which is the
field name on the `WeeklyStatRow` DATACLASS. The raw nflverse rows that
`fetch_weekly_stats` actually returns use `player_id`. So the filter
matched zero rows for every player and the endpoint answered a
well-formed 200 with an empty `weeks` list — for everyone, always.

Measured on the real 2025 file, 2026-07-27: the old expression matched
**0** rows for a GSIS id the correct one matched **17**.

What kept it invisible was NOT the flag. `realized_points_api` defaults
**ON**; the endpoint's own docstring said "default OFF" and was wrong,
which made a live defect read as dormant. What hid it was the absence of
a caller — nothing in the frontend requests this endpoint.

So these tests exercise the filter directly. An endpoint nobody calls is
still an endpoint that answers wrongly the moment somebody does.
"""

from __future__ import annotations

import pytest


def _rows_for(gsis: str, weeks: int, *, key: str = "player_id") -> list[dict]:
    return [
        {
            key: gsis,
            "player_name": "Test Player",
            "position": "WR",
            "season": 2025,
            "week": w,
            "receptions": 5,
            "receiving_yards": 60,
            "receiving_tds": 1,
        }
        for w in range(1, weeks + 1)
    ]


def _filter(weekly: list[dict], gsis: str) -> list[dict]:
    """The endpoint's filter expression, kept in one place so this test
    and server.py cannot drift apart silently."""
    target = str(gsis or "").strip()
    return [
        r
        for r in weekly
        if target and str(r.get("player_id") or r.get("player_id_gsis") or "").strip() == target
    ]


def test_the_filter_matches_raw_nflverse_rows():
    """The bug. Raw rows key on `player_id`; the old filter read
    `player_id_gsis` and matched nothing."""
    rows = _rows_for("00-0036322", 17)
    assert len(_filter(rows, "00-0036322")) == 17


def test_the_filter_still_matches_dataclass_shaped_rows():
    """A caller passing normalized `WeeklyStatRow`-shaped dicts must keep
    working — the fix widens the filter rather than swapping one wrong
    key for another."""
    rows = _rows_for("00-0036322", 5, key="player_id_gsis")
    assert len(_filter(rows, "00-0036322")) == 5


def test_a_different_player_is_not_matched():
    """The control. Without it a filter that returned everything would
    pass both tests above."""
    rows = _rows_for("00-0036322", 17) + _rows_for("00-0000001", 4)
    assert len(_filter(rows, "00-0036322")) == 17
    assert len(_filter(rows, "00-0000001")) == 4


def test_rows_with_neither_key_are_not_matched_by_an_empty_gsis():
    """An unmapped player resolves to no GSIS. Matching '' against rows
    that also lack the key would return the entire league's stat lines
    under one player's name."""
    rows = [{"season": 2025, "week": 1, "receptions": 3}]
    assert _filter(rows, "") == []


def test_the_endpoint_is_live_by_default():
    """Pinned because the endpoint's docstring claimed the opposite.

    `realized_points_api` defaults ON, so this route answers real
    requests today. Believing it was off is what made a live defect look
    dormant, and a test is a harder thing to get wrong than prose.
    """
    from src.api import feature_flags

    feature_flags.reload()
    assert feature_flags.is_enabled("realized_points_api") is True


@pytest.mark.livedata
def test_the_filter_finds_real_weeks_on_the_live_file():
    """End to end against real nflverse data — the assertion that would
    have caught this originally. Marked livedata because it fetches."""
    from src.nfl_data.ingest import fetch_weekly_stats

    rows = fetch_weekly_stats([2025])
    if not rows:
        pytest.skip("no weekly stats available")
    gsis = str(rows[0].get("player_id") or "")
    assert gsis, "raw nflverse rows must carry player_id"
    assert (
        len(_filter(rows, gsis)) > 0
    ), "the filter matched no weeks for a GSIS id taken from the data itself"


# ── The route itself (W18-F004 / B7) ──────────────────────────────────
#
# Everything above exercises a COPY of the endpoint's filter. The
# docstring says that copy is "kept in one place so this test and
# server.py cannot drift apart silently" — but a copy is precisely the
# thing that can drift, and while it sat here two other defects lived in
# the real handler untested:
#
#   * ``players_dir`` read ``sleeper_block["players"]`` / ``["playerDict"]``.
#     The contract's sleeper block has neither key, so the directory was
#     always ``None`` and EVERY request returned ``unmapped_player`` — a
#     well-formed 200 answering nothing, for every player, always.
#   * ``scoring_settings`` came from the LOADED contract rather than the
#     REQUESTED league, so a player in a second league was scored under
#     the first league's rules and stamped with the requested leagueKey.
#
# These call the real route.


@pytest.fixture
def realized_client(tmp_path, monkeypatch):
    """A two-league app with per-league scoring snapshots installed."""
    import json as _json

    from fastapi.testclient import TestClient

    import server
    from src.api import league_registry
    from tests.api.scoring_fixture import (
        OTHER_SCORING_CARD,
        SCORING_CARD,
        install_scoring_snapshots,
    )

    path = tmp_path / "registry.json"
    path.write_text(
        _json.dumps(
            {
                "defaultLeagueKey": "main",
                "leagues": [
                    {
                        "key": "main",
                        "displayName": "Main",
                        "sleeperLeagueId": "L-MAIN",
                        "active": True,
                        "rosterSettings": {"teamCount": 12},
                    },
                    {
                        "key": "side",
                        "displayName": "Side",
                        "sleeperLeagueId": "L-SIDE",
                        "active": True,
                        "rosterSettings": {"teamCount": 10},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("LEAGUE_REGISTRY_PATH", str(path))
    league_registry.reload_registry()
    # The two leagues score DIFFERENTLY — that is the point.
    install_scoring_snapshots(
        tmp_path, monkeypatch, {"L-MAIN": SCORING_CARD, "L-SIDE": OTHER_SCORING_CARD}
    )
    monkeypatch.setattr(server, "_is_authenticated", lambda request: True)
    monkeypatch.setattr(server, "_get_auth_session", lambda request: {"username": "t"})

    # One player, one week, one reception — enough to tell the two cards
    # apart (rec 1.0 vs 0.08).
    monkeypatch.setattr(
        "src.nfl_data.ingest.fetch_weekly_stats",
        lambda years: [
            {
                "player_id": "00-0000001",
                "season": 2025,
                "week": 1,
                "position": "WR",
                "receptions": 10,
            }
        ],
    )
    monkeypatch.setattr(
        "src.public_league.sleeper_client.fetch_nfl_players",
        lambda: {
            "999": {
                "player_id": "999",
                "gsis_id": "00-0000001",
                "full_name": "Test Player",
                "position": "WR",
                "team": "BUF",
            }
        },
    )
    with TestClient(server.app, raise_server_exceptions=True) as c:
        yield c
    league_registry.reload_registry()


def test_the_route_resolves_a_player_instead_of_answering_unmapped(realized_client):
    body = realized_client.get("/api/player/999/realized?leagueKey=main").json()
    assert body.get("reason") != "unmapped_player", (
        "the route still cannot resolve a player — players_dir is not the "
        "master Sleeper directory"
    )
    assert body.get("gsisId") == "00-0000001"
    assert body.get("weekCount"), "resolved the player but matched no weeks"


def test_each_league_is_scored_under_its_own_card(realized_client):
    """The requested league's rules, not the loaded contract's."""
    main = realized_client.get("/api/player/999/realized?leagueKey=main").json()
    side = realized_client.get("/api/player/999/realized?leagueKey=side").json()

    assert main["leagueKey"] == "main"
    assert side["leagueKey"] == "side"
    # 10 receptions at rec 1.0 vs rec 0.08 — 10.0 against 0.8.
    assert main["totalPoints"] == pytest.approx(10.0, abs=1e-6)
    assert side["totalPoints"] == pytest.approx(0.8, abs=1e-6)
    assert main["totalPoints"] != side["totalPoints"], (
        "both leagues scored identically — the route is using one league's "
        "card for the other, which is the W18-F002 shape on this route"
    )
