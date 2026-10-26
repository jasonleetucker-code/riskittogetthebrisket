"""``server._live_player_meta`` carries each board row's ``playerId`` for the
as-known news archive WITHOUT changing the position/team it has always served to
mention enrichment, and never attributes a display name two ids share."""

from __future__ import annotations

import server


def _meta(monkeypatch, rows):
    monkeypatch.setattr(server, "latest_contract_data", {"playersArray": rows})
    monkeypatch.setattr(server, "latest_data_etag", None)  # bypass the memo
    return server._live_player_meta()


def test_player_id_rides_along(monkeypatch):
    meta = _meta(
        monkeypatch, [{"displayName": "Alpha", "position": "WR", "team": "buf", "playerId": "100"}]
    )
    assert meta["Alpha"] == {"position": "WR", "team": "BUF", "playerId": "100"}


def test_same_name_same_identity_different_ids_keeps_position_team_drops_id(monkeypatch):
    meta = _meta(
        monkeypatch,
        [
            {"displayName": "Twin", "position": "WR", "team": "BUF", "playerId": "1"},
            {"displayName": "Twin", "position": "WR", "team": "BUF", "playerId": "2"},
        ],
    )
    # position/team exactly as before this change; the id is withheld.
    assert meta["Twin"]["position"] == "WR" and meta["Twin"]["team"] == "BUF"
    assert meta["Twin"]["playerId"] is None
    assert meta["Twin"]["playerIdNullReason"] == "display_name_shared_by_multiple_player_ids"


def test_identity_collision_unchanged(monkeypatch):
    meta = _meta(
        monkeypatch,
        [
            {"displayName": "CJ", "position": "LB", "team": "TEN", "playerId": "1"},
            {"displayName": "CJ", "position": "WR", "team": "ATL", "playerId": "2"},
        ],
    )
    assert meta["CJ"]["position"] is None and meta["CJ"]["team"] is None
    assert meta["CJ"]["playerId"] is None


def test_row_without_id_is_null_with_reason(monkeypatch):
    meta = _meta(monkeypatch, [{"displayName": "NoId", "position": "RB"}])
    assert meta["NoId"]["playerId"] is None
    assert meta["NoId"]["playerIdNullReason"] == "board_row_has_no_player_id"
