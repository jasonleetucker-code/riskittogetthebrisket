from __future__ import annotations

import pytest

from src.idp_calibration import api, engine, production, season_chain, storage
from src.idp_calibration.stats_adapter import HistoricalStatsAdapter, PlayerSeason


class _StubAdapter(HistoricalStatsAdapter):
    name = "stub"

    def fetch(self, season):
        rows = []
        for i in range(40):
            pos = "DL" if i % 3 == 0 else ("LB" if i % 3 == 1 else "DB")
            rows.append(
                PlayerSeason(
                    player_id=f"p{season}_{i}",
                    name=f"Player {i}",
                    position=pos,
                    games=16,
                    stats={"idp_tkl_solo": 40 - i, "idp_sack": max(0, 5 - i / 6)},
                )
            )
        return rows


def _fake_chain(seasons):
    def _builder(league_id, max_hops):
        return [
            {
                "league_id": f"{league_id}_{s}",
                "season": s,
                "previous_league_id": f"{league_id}_{s - 1}" if i < len(seasons) - 1 else "",
                "scoring_settings": {"idp_tkl_solo": 1.0, "idp_sack": 3.0},
                "roster_positions": ["QB", "RB", "WR", "DL", "LB", "LB", "DB", "BN"],
                "total_rosters": 10,
            }
            for i, s in enumerate(seasons)
        ]

    return _builder


@pytest.fixture
def tmp_base(tmp_path, monkeypatch):
    monkeypatch.setattr(
        season_chain, "fetch_league_chain", _fake_chain([2025, 2024, 2023, 2022])
    )
    # Force stats adapter to our stub so the API path doesn't touch the network.
    monkeypatch.setattr(
        engine, "get_stats_adapter", lambda season: (_StubAdapter(), ["stub:ok"])
    )
    production.reset_cache()
    yield tmp_path
    production.reset_cache()


def test_analyze_validates_league_ids(tmp_base):
    status, payload = api.analyze({"test_league_id": "", "my_league_id": ""}, base=tmp_base)
    assert status == 422
    assert payload["ok"] is False


def test_analyze_round_trip_and_run_detail(tmp_base):
    status, payload = api.analyze(
        {"test_league_id": "A", "my_league_id": "B"}, base=tmp_base
    )
    assert status == 200
    run_id = payload["run"]["run_id"]
    status, listing = api.runs_index(base=tmp_base)
    assert status == 200
    assert any(r["run_id"] == run_id for r in listing["runs"])
    status, detail = api.run_detail(run_id, base=tmp_base)
    assert status == 200
    assert detail["run"]["run_id"] == run_id


def test_run_detail_missing_returns_404(tmp_base):
    status, payload = api.run_detail("no-such-run", base=tmp_base)
    assert status == 404
    assert payload["ok"] is False


def test_promote_requires_run_id_and_mode(tmp_base):
    status, payload = api.promote({"run_id": ""}, base=tmp_base)
    assert status == 422
    status, payload = api.promote(
        {"run_id": "anything", "active_mode": "bogus"}, base=tmp_base
    )
    assert status == 422


def test_promote_and_production_flow(tmp_base):
    _, payload = api.analyze(
        {"test_league_id": "A", "my_league_id": "B"}, base=tmp_base
    )
    run_id = payload["run"]["run_id"]
    status, prod = api.production(base=tmp_base)
    assert status == 200 and prod["present"] is False
    status, result = api.promote(
        {"run_id": run_id, "active_mode": "blended"}, base=tmp_base
    )
    assert status == 200
    assert result["ok"] is True
    status, prod = api.production(base=tmp_base)
    assert prod["present"] is True
    assert prod["config"]["source_run_id"] == run_id


def test_status_reports_presence(tmp_base):
    status, payload = api.status(base=tmp_base)
    assert status == 200
    assert payload["production_present"] is False
    api.analyze({"test_league_id": "A", "my_league_id": "B"}, base=tmp_base)
    status, payload = api.status(base=tmp_base)
    assert payload["latest_run_id"] is not None
