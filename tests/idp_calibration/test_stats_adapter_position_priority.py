"""SleeperStatsAdapter and LocalCSVStatsAdapter must collapse
multi-position players using DL > DB > LB. A DL+LB player becomes DL;
an LB+DB player becomes DB; an exclusive LB stays LB. This pins the
end-to-end integration since the stats adapter is the earliest point
in the pipeline where Sleeper raw data touches our position layer.
"""
from __future__ import annotations

from src.idp_calibration.stats_adapter import (
    LocalCSVStatsAdapter,
    SleeperStatsAdapter,
)


def test_sleeper_adapter_prefers_fantasy_positions_under_dl_priority(monkeypatch, tmp_path):
    # A DL+LB player with single-position "OLB" in `position` but
    # `fantasy_positions=["DL","LB"]` must resolve to DL.
    fake_payload = {
        "multi_dl_lb": {"idp_tkl_solo": 80, "gp": 17},
        "multi_lb_db": {"idp_tkl_solo": 70, "gp": 17},
        "pure_lb": {"idp_tkl_solo": 120, "gp": 17},
    }
    fake_players_map = {
        "multi_dl_lb": {
            "full_name": "DL/LB Hybrid",
            "position": "OLB",
            "fantasy_positions": ["DL", "LB"],
        },
        "multi_lb_db": {
            "full_name": "LB/DB Hybrid",
            "position": "LB",
            "fantasy_positions": ["LB", "S"],
        },
        "pure_lb": {
            "full_name": "Pure LB",
            "position": "LB",
            "fantasy_positions": ["LB"],
        },
    }

    class _FakeResp:
        status_code = 200

        def json(self):
            return fake_payload

    import requests

    monkeypatch.setattr(requests, "get", lambda url, timeout: _FakeResp())
    adapter = SleeperStatsAdapter(players_map=fake_players_map)
    rows = {r.player_id: r for r in adapter.fetch(2025)}

    assert rows["multi_dl_lb"].position == "DL"      # DL > LB
    assert rows["multi_lb_db"].position == "DB"      # DB > LB (S → DB)
    assert rows["pure_lb"].position == "LB"          # exclusive LB


def test_sleeper_adapter_falls_back_to_single_position_when_no_list(monkeypatch):
    # Older snapshots may omit fantasy_positions entirely. We must
    # still resolve using the single position field.
    fake_payload = {"p": {"idp_tkl_solo": 10, "gp": 16}}
    fake_players_map = {"p": {"full_name": "X", "position": "DE"}}  # no fantasy_positions

    class _FakeResp:
        status_code = 200

        def json(self):
            return fake_payload

    import requests

    monkeypatch.setattr(requests, "get", lambda url, timeout: _FakeResp())
    adapter = SleeperStatsAdapter(players_map=fake_players_map)
    rows = adapter.fetch(2025)
    assert len(rows) == 1
    assert rows[0].position == "DL"                  # DE → DL


def test_local_csv_adapter_respects_priority(tmp_path):
    csv_path = tmp_path / "2025.csv"
    csv_path.write_text(
        "player_id,name,position,fantasy_positions,idp_tkl_solo\n"
        "a,Multi DL/LB,OLB,\"DL,LB\",50\n"
        "b,Multi LB/DB,LB,\"LB,CB\",70\n"
        "c,Pure LB,LB,LB,100\n",
    )
    adapter = LocalCSVStatsAdapter(base_dir=tmp_path)
    rows = {r.player_id: r for r in adapter.fetch(2025)}
    assert rows["a"].position == "DL"
    assert rows["b"].position == "DB"
    assert rows["c"].position == "LB"
