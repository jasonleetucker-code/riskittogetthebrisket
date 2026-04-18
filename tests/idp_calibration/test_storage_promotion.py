from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.idp_calibration import engine, promotion, production, season_chain, storage
from src.idp_calibration.stats_adapter import HistoricalStatsAdapter, PlayerSeason


class _StubAdapter(HistoricalStatsAdapter):
    name = "stub"

    def fetch(self, season):
        rows = []
        for i in range(60):
            pos = "DL" if i % 3 == 0 else ("LB" if i % 3 == 1 else "DB")
            rows.append(
                PlayerSeason(
                    player_id=f"p{season}_{i}",
                    name=f"Player {i}",
                    position=pos,
                    games=16,
                    stats={
                        "idp_tkl_solo": 100 - i,
                        "idp_sack": max(0, 12 - i / 3),
                        "idp_int": 2,
                    },
                )
            )
        return rows


def _fake_chain(seasons):
    def _builder(league_id, max_hops):
        return [
            {
                "league_id": f"{league_id}_{s}",
                "season": s,
                "name": f"{league_id} {s}",
                "previous_league_id": f"{league_id}_{s - 1}" if i < len(seasons) - 1 else "",
                "scoring_settings": {"idp_tkl_solo": 1.0, "idp_sack": 4.0, "idp_int": 3.0},
                "roster_positions": [
                    "QB", "RB", "RB", "WR", "WR", "TE", "FLEX",
                    "DL", "DL", "LB", "LB", "LB", "DB", "DB",
                    "BN", "BN", "BN",
                ],
                "total_rosters": 12,
            }
            for i, s in enumerate(seasons)
        ]

    return _builder


@pytest.fixture
def tmp_base(tmp_path, monkeypatch):
    # Keep engine's default chain fetcher deterministic.
    monkeypatch.setattr(
        season_chain,
        "fetch_league_chain",
        _fake_chain([2025, 2024, 2023, 2022]),
    )
    production.reset_cache()
    yield tmp_path
    production.reset_cache()


def test_save_and_load_run_round_trip(tmp_base):
    settings = engine.AnalysisSettings()
    artifact = engine.run_analysis(
        "A", "B", settings, stats_adapter_factory=lambda s: _StubAdapter()
    )
    run_id = storage.save_run(artifact, base=tmp_base)
    assert run_id == artifact["run_id"]
    loaded = storage.load_run(run_id, base=tmp_base)
    assert loaded is not None
    assert loaded["run_id"] == run_id
    # list_runs must surface it.
    summaries = storage.list_runs(base=tmp_base)
    assert any(s["run_id"] == run_id for s in summaries)
    latest = storage.get_latest(base=tmp_base)
    assert latest["run_id"] == run_id


def test_promote_writes_config_and_backs_up_prior(tmp_base):
    settings = engine.AnalysisSettings()
    art1 = engine.run_analysis(
        "A", "B", settings, stats_adapter_factory=lambda s: _StubAdapter()
    )
    storage.save_run(art1, base=tmp_base)
    result1 = promotion.promote_run(
        art1["run_id"], active_mode="blended", promoted_by="tester", base=tmp_base
    )
    assert result1["ok"] is True
    cfg_path = promotion.production_config_path(tmp_base)
    cfg = json.loads(cfg_path.read_text())
    assert cfg["source_run_id"] == art1["run_id"]
    assert cfg["active_mode"] == "blended"
    assert result1["backup_path"] is None

    # Second promote should move the prior config into backups dir.
    art2 = engine.run_analysis(
        "X", "Y", settings, stats_adapter_factory=lambda s: _StubAdapter()
    )
    storage.save_run(art2, base=tmp_base)
    result2 = promotion.promote_run(
        art2["run_id"], active_mode="intrinsic_only", base=tmp_base
    )
    assert result2["backup_path"] is not None
    assert Path(result2["backup_path"]).exists()
    refreshed = json.loads(cfg_path.read_text())
    assert refreshed["active_mode"] == "intrinsic_only"
    assert refreshed["source_run_id"] == art2["run_id"]


def test_delete_run_removes_file_and_updates_latest(tmp_base):
    settings = engine.AnalysisSettings()
    art1 = engine.run_analysis(
        "A", "B", settings, stats_adapter_factory=lambda s: _StubAdapter()
    )
    storage.save_run(art1, base=tmp_base)
    art2 = engine.run_analysis(
        "C", "D", settings, stats_adapter_factory=lambda s: _StubAdapter()
    )
    storage.save_run(art2, base=tmp_base)
    # latest should be art2 (the most recently saved).
    assert storage.get_latest(base=tmp_base)["run_id"] == art2["run_id"]

    # Deleting the latest must rewrite the pointer to the surviving run.
    assert storage.delete_run(art2["run_id"], base=tmp_base) is True
    assert storage.load_run(art2["run_id"], base=tmp_base) is None
    assert storage.get_latest(base=tmp_base)["run_id"] == art1["run_id"]

    # Deleting the last remaining run must clear the pointer.
    assert storage.delete_run(art1["run_id"], base=tmp_base) is True
    assert storage.get_latest(base=tmp_base) is None

    # Deleting an already-gone run is a no-op that returns False.
    assert storage.delete_run(art1["run_id"], base=tmp_base) is False


def test_delete_run_does_not_touch_promoted_config(tmp_base):
    settings = engine.AnalysisSettings()
    art = engine.run_analysis(
        "A", "B", settings, stats_adapter_factory=lambda s: _StubAdapter()
    )
    storage.save_run(art, base=tmp_base)
    promotion.promote_run(art["run_id"], active_mode="blended", base=tmp_base)
    assert promotion.production_config_path(tmp_base).exists()
    storage.delete_run(art["run_id"], base=tmp_base)
    # Production stays. Deleting a run never reverts prod automatically —
    # that's an explicit action (delete the file on disk).
    assert promotion.production_config_path(tmp_base).exists()


def test_promote_unknown_run_raises(tmp_base):
    with pytest.raises(FileNotFoundError):
        promotion.promote_run("does-not-exist", base=tmp_base)


def test_promote_refuses_run_with_no_bucket_data(tmp_base):
    # Build an artifact whose multipliers contain only zero-count buckets
    # (the exact shape produced by a run where every season failed to
    # resolve). Promoting would otherwise let the anchor floor (0.05)
    # reach production and cut every IDP value by ~95%.
    empty_artifact = {
        "run_id": "empty_run",
        "generated_at": "2026-04-18T00:00:00Z",
        "settings": {"blend": {"intrinsic": 0.75, "market": 0.25}},
        "resolved_seasons": [],
        "multipliers": {
            "DL": {"position": "DL", "buckets": [
                {"label": "1-6", "intrinsic": 1.0, "market": 1.0, "final": 1.0, "count": 0},
            ]},
            "LB": {"position": "LB", "buckets": []},
            "DB": {"position": "DB", "buckets": []},
        },
        "anchors": {},
    }
    storage.save_run(empty_artifact, base=tmp_base)
    with pytest.raises(promotion.EmptyCalibrationError):
        promotion.promote_run("empty_run", base=tmp_base)
    # No config file should have been written.
    assert not promotion.production_config_path(tmp_base).exists()


def test_production_lookup_returns_multiplier_when_promoted(tmp_base):
    settings = engine.AnalysisSettings()
    art = engine.run_analysis(
        "A", "B", settings, stats_adapter_factory=lambda s: _StubAdapter()
    )
    storage.save_run(art, base=tmp_base)
    promotion.promote_run(art["run_id"], active_mode="blended", base=tmp_base)
    production.reset_cache()
    val = production.get_idp_bucket_multiplier("DL", 1, base=tmp_base)
    # Top bucket must be 1.0 by construction.
    assert val == 1.0
    # A very late rank falls back to anchor floor (0.05 by default).
    assert production.get_idp_bucket_multiplier("DL", 500, base=tmp_base) >= 0.0
