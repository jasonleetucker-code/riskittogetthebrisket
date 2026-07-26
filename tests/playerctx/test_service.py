"""Service orchestration with mocked fetch — end-to-end refresh into a
tmp snapshot, floor/retention regression paths, and the CLI exit-code
mapping.  No network."""

from __future__ import annotations

import pytest

from scripts import refresh_playerctx as cli
from src.playerctx import fetch as fetch_mod
from src.playerctx import service, store
from src.playerctx.normalize import SchemaRegressionError
from tests.playerctx.conftest import (
    CONTRACTS_HEADER,
    DEPTH_HEADER,
    SNAPS_HEADER,
    write_csv,
)


@pytest.fixture
def fixture_bundle(tmp_path):
    """A FetchBundle backed by tiny on-disk fixture files."""
    contracts = write_csv(
        tmp_path / "historical_contracts.csv.gz",
        CONTRACTS_HEADER,
        [
            "Christian McCaffrey,RB,49ers,TRUE,2024,2,38000000,19000000,24000000,"
            "0.07,https://example.invalid,1,2017",
            "Micah Parsons,DL,Cowboys,TRUE,2025,4,188000000,47000000,120000000,"
            "0.18,https://example.invalid,2,2021",
        ],
    )
    snaps = write_csv(
        tmp_path / "snap_counts_2025.csv",
        SNAPS_HEADER,
        [
            "2025_01_SF_XX,x1,2025,REG,1,Christian McCaffrey,McCaCh01,RB,SF,XX,60,0.85,0,0,0,0",
            "2025_02_SF_XX,x2,2025,REG,2,Christian McCaffrey,McCaCh01,RB,SF,XX,65,0.95,0,0,0,0",
            "2025_01_MIN_XX,x3,2025,REG,1,Justin Jefferson,JeffJu00,WR,MIN,XX,70,0.98,0,0,0,0",
        ],
    )
    depth = write_csv(
        tmp_path / "depth_charts_2026.csv",
        DEPTH_HEADER,
        [
            "2026-07-25T00:00:00Z,SF,Christian McCaffrey,3117251,00-0033280,20,3WR 1TE,1,RB,RB,1,1",
            "2026-07-25T00:00:00Z,MIN,Justin Jefferson,4262921,00-0036322,20,3WR 1TE,1,WR,WR,1,1",
            "2026-07-25T00:00:00Z,DAL,Micah Parsons,4361429,00-0036933,16,Base 4-3 D,11,RDE,RDE,1,1",
        ],
    )
    return fetch_mod.FetchBundle(
        contracts=contracts,
        snap_counts=snaps,
        snap_counts_season=2025,
        depth_charts=depth,
        depth_charts_season=2026,
        sleeper_players=None,
        warnings=["snap_counts 2026: missing 404"],
    )


@pytest.fixture
def small_floors(monkeypatch):
    monkeypatch.setattr(service, "_ROW_FLOORS", {"contracts": 1, "snapCounts": 1, "depthCharts": 1})
    monkeypatch.setattr(service, "_MIN_MATCHED_PLAYERS", 1)


def _fetcher(bundle):
    def fake_fetch(*, cache_dir=None, max_age_hours=None, force=False):
        return bundle

    return fake_fetch


class TestRefreshPlayerctx:
    def test_end_to_end_writes_snapshot(self, tmp_path, fixture_bundle, players_dir, small_floors):
        target = tmp_path / "out" / "snapshot.json"
        summary = service.refresh_playerctx(
            fetcher=_fetcher(fixture_bundle),
            players_dir=players_dir,
            snapshot_path=target,
        )
        assert summary["snapshotPath"] == str(target)
        assert summary["warnings"] == ["snap_counts 2026: missing 404"]
        payload = store.load_snapshot(target)
        assert payload is not None
        players = payload["players"]
        assert set(players) == {"00-0033280", "00-0036322", "00-0036933"}
        cmc = players["00-0033280"]
        assert cmc["contract"]["apy"] == 19_000_000
        assert cmc["snaps"]["pct"] == pytest.approx(90.0)
        assert cmc["depth"]["rank"] == 1
        assert payload["sources"]["snapCounts"]["season"] == 2025
        assert payload["sources"]["depthCharts"]["season"] == 2026

    def test_missing_dataset_is_soft_failure(self, fixture_bundle, players_dir, small_floors):
        fixture_bundle.contracts = None
        with pytest.raises(RuntimeError, match="contracts"):
            service.refresh_playerctx(fetcher=_fetcher(fixture_bundle), players_dir=players_dir)

    def test_row_floor_breach_is_schema_regression(
        self, tmp_path, fixture_bundle, players_dir, monkeypatch
    ):
        monkeypatch.setattr(
            service, "_ROW_FLOORS", {"contracts": 99, "snapCounts": 1, "depthCharts": 1}
        )
        monkeypatch.setattr(service, "_MIN_MATCHED_PLAYERS", 1)
        with pytest.raises(SchemaRegressionError, match="contracts"):
            service.refresh_playerctx(
                fetcher=_fetcher(fixture_bundle),
                players_dir=players_dir,
                snapshot_path=tmp_path / "snap.json",
            )

    def test_retention_guard_keeps_last_good(
        self, tmp_path, fixture_bundle, players_dir, small_floors
    ):
        target = tmp_path / "snapshot.json"
        # Last-good snapshot with far more players than the new run yields.
        many = {
            f"00-{i:07d}": {"gsisId": f"00-{i:07d}", "sleeperId": str(i), "name": f"P{i}"}
            for i in range(20)
        }
        store.write_snapshot(many, path=target)
        before = target.read_text(encoding="utf-8")
        with pytest.raises(SchemaRegressionError, match="retains only"):
            service.refresh_playerctx(
                fetcher=_fetcher(fixture_bundle),
                players_dir=players_dir,
                snapshot_path=target,
            )
        assert target.read_text(encoding="utf-8") == before  # untouched

    def test_missing_sleeper_dump_is_soft_failure(self, fixture_bundle, small_floors):
        with pytest.raises(RuntimeError, match="sleeper"):
            service.refresh_playerctx(fetcher=_fetcher(fixture_bundle))


class TestLoadPlayerctx:
    def test_defensive_load(self, tmp_path):
        assert service.load_playerctx(tmp_path / "missing.json") is None


class TestCliExitCodes:
    def test_success_is_zero(self, monkeypatch, capsys):
        monkeypatch.setattr(
            cli,
            "refresh_playerctx",
            lambda **kw: {
                "snapshotPath": "/x/snapshot.json",
                "counts": {"players": 3, "contracts": {"matched": 2}},
                "sources": {},
                "warnings": ["w1"],
            },
        )
        assert cli.main([]) == 0
        err = capsys.readouterr().err
        assert "w1" in err

    def test_schema_regression_is_two(self, monkeypatch):
        def boom(**kw):
            raise SchemaRegressionError("columns went missing")

        monkeypatch.setattr(cli, "refresh_playerctx", boom)
        assert cli.main([]) == 2

    def test_soft_failure_is_one(self, monkeypatch):
        def boom(**kw):
            raise RuntimeError("network sad")

        monkeypatch.setattr(cli, "refresh_playerctx", boom)
        assert cli.main([]) == 1
