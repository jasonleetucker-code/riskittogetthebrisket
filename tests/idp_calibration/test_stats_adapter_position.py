"""Regression test for the variable-shadowing bug in
SleeperStatsAdapter._fetch_impl that made every returned PlayerSeason
carry position="idp_tkl_5p" (the last stat-key iterated) instead of
the actual DL/LB/DB position — which caused build_universe to drop
every row silently.
"""
from __future__ import annotations

from src.idp_calibration.stats_adapter import SleeperStatsAdapter


def test_sleeper_adapter_preserves_canonical_position(monkeypatch):
    # Minimal fake payload: one DL, one LB, one DB player. Each row
    # also carries enough stat fields to exercise the inner stat-key
    # loop that used to shadow the position variable.
    fake_payload = {
        "1": {"idp_tkl_solo": 50, "idp_sack": 10, "gp": 16},
        "2": {"idp_tkl_solo": 120, "idp_int": 2, "gp": 17},
        "3": {"idp_tkl_solo": 75, "idp_pd": 18, "gp": 15},
    }
    fake_players = {
        "1": {"full_name": "Myles Garrett", "position": "DE"},
        "2": {"full_name": "Roquan Smith", "position": "LB"},
        "3": {"full_name": "Jaire Alexander", "position": "CB"},
    }

    class _FakeResp:
        status_code = 200

        def json(self):
            return fake_payload

    def _fake_get(url, timeout):
        return _FakeResp()

    # Patch both the HTTP call and the players map so the adapter has
    # zero external dependencies.
    import requests

    monkeypatch.setattr(requests, "get", _fake_get)
    adapter = SleeperStatsAdapter(players_map=fake_players)
    rows = adapter.fetch(2025)

    # All three rows must survive with their canonical defensive
    # position intact — not any stat-key name.
    assert len(rows) == 3
    positions = {r.position for r in rows}
    assert positions == {"DL", "LB", "DB"}
    # And the stats block has the expected canonical keys, proving the
    # stat-key loop ran and wrote into scored{} correctly.
    by_id = {r.player_id: r for r in rows}
    assert by_id["1"].position == "DL"
    assert by_id["1"].stats.get("idp_tkl_solo") == 50
    assert by_id["1"].stats.get("idp_sack") == 10
    assert by_id["2"].position == "LB"
    assert by_id["3"].position == "DB"
