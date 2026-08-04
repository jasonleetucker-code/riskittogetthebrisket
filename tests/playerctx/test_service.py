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

    def test_per_source_retention_guard(self, tmp_path, fixture_bundle, players_dir, small_floors):
        # Regression (Codex round 1, finding 3 on PR #539): if ONE
        # source collapses semantically (contracts matching almost
        # nothing after a naming-convention change) while the union of
        # player keys stays healthy, the union-only guard would publish
        # a snapshot silently missing every contract block.  Each
        # source's matched count must hold the retention ratio on its
        # own.
        target = tmp_path / "snapshot.json"
        # Last-good: same 3 players (union check passes: 3 >= 3*0.75)
        # but contracts historically matched 50 rows.
        prev_players = {
            f"00-{i:07d}": {"gsisId": f"00-{i:07d}", "sleeperId": str(i), "name": f"P{i}"}
            for i in range(3)
        }
        store.write_snapshot(
            prev_players,
            counts={
                "contracts": {"parsed": 60, "matched": 50},
                "snapCounts": {"parsed": 3, "matched": 3},
                "depthCharts": {"parsed": 3, "matched": 3},
            },
            path=target,
        )
        before = target.read_text(encoding="utf-8")
        # New run only matches 2 contracts (fixture_bundle) — far under
        # 75% of 50 — while depth+snaps keep the union at 3 players.
        with pytest.raises(SchemaRegressionError, match="contracts: matched 2"):
            service.refresh_playerctx(
                fetcher=_fetcher(fixture_bundle),
                players_dir=players_dir,
                snapshot_path=target,
            )
        assert target.read_text(encoding="utf-8") == before  # last-good untouched

    def test_per_source_guard_skips_snapshots_without_counts(
        self, tmp_path, fixture_bundle, players_dir, small_floors
    ):
        # Older snapshots (or hand-rolled ones) without per-source
        # counts must not trip the guard.
        target = tmp_path / "snapshot.json"
        prev_players = {
            f"00-{i:07d}": {"gsisId": f"00-{i:07d}", "sleeperId": str(i), "name": f"P{i}"}
            for i in range(3)
        }
        store.write_snapshot(prev_players, counts={}, path=target)
        summary = service.refresh_playerctx(
            fetcher=_fetcher(fixture_bundle),
            players_dir=players_dir,
            snapshot_path=target,
        )
        assert summary["counts"]["players"] == 3


class TestReconstructPlayerctx:
    """Replaying the snapshot as it would have read at a past week.

    The `snapTrend` axis was documented in four places as unmeasurable
    because the playerctx snapshot is overwritten weekly with no history.
    The history is upstream — nflverse publishes snap counts per game —
    so what was missing was an as-of read, not a retention policy.
    """

    def _bundle_with_four_weeks(self, tmp_path, fixture_bundle):
        fixture_bundle.snap_counts = write_csv(
            tmp_path / "snaps_multi.csv",
            SNAPS_HEADER,
            [
                f"2025_{w:02d}_SF_XX,x{w},2025,REG,{w},Christian McCaffrey,McCaCh01,"
                f"RB,SF,XX,{40 + w * 10},0.{40 + w * 10},0,0,0,0"
                for w in range(1, 5)
            ],
        )
        return fixture_bundle

    def test_the_replay_sees_only_games_up_to_the_cutoff(
        self, tmp_path, fixture_bundle, players_dir
    ):
        bundle = self._bundle_with_four_weeks(tmp_path, fixture_bundle)
        payload = service.reconstruct_playerctx(
            as_of=service.AsOf(season=2025, through_week=2),
            fetcher=_fetcher(bundle),
            players_dir=players_dir,
        )
        assert payload["players"]["00-0033280"]["snaps"]["games"] == 2

    def test_the_snap_trend_actually_differs_between_two_cutoffs(
        self, tmp_path, fixture_bundle, players_dir
    ):
        """The property the whole exercise exists to obtain.

        A replay whose derived signal is identical at every cutoff is
        worthless for a backtest — every fold would resample one
        observation, which is exactly what the all-offseason panel does
        to this axis today.
        """
        bundle = self._bundle_with_four_weeks(tmp_path, fixture_bundle)
        trends = {}
        for cutoff in (3, 4):
            payload = service.reconstruct_playerctx(
                as_of=service.AsOf(season=2025, through_week=cutoff),
                fetcher=_fetcher(bundle),
                players_dir=players_dir,
            )
            trends[cutoff] = payload["players"]["00-0033280"]["snaps"]["trend"]
        assert trends[3] != trends[4], f"snapTrend frozen across cutoffs: {trends}"

    def test_it_reports_survivorship_rather_than_assuming_it_away(
        self, tmp_path, fixture_bundle, players_dir
    ):
        # The join anchor is the LIVE Sleeper pool; a player out of the
        # league by now cannot join, so a replay is biased toward
        # survivors. That has to be quantifiable, not hidden.
        fixture_bundle.snap_counts = write_csv(
            tmp_path / "snaps_retired.csv",
            SNAPS_HEADER,
            [
                "2025_01_SF_XX,x1,2025,REG,1,Christian McCaffrey,McCaCh01,RB,SF,XX,60,0.85,0,0,0,0",
                "2025_02_SF_XX,x2,2025,REG,2,Christian McCaffrey,McCaCh01,RB,SF,XX,65,0.95,0,0,0,0",
                # Real in 2025, gone from the 2026 Sleeper pool.
                "2025_01_NYJ_XX,x3,2025,REG,1,Retired Veteran,RetiVe00,RB,NYJ,XX,50,0.70,0,0,0,0",
            ],
        )
        payload = service.reconstruct_playerctx(
            as_of=service.AsOf(season=2025),
            fetcher=_fetcher(fixture_bundle),
            players_dir=players_dir,
        )
        snaps = payload["survivorship"]["snapCounts"]
        assert snaps["parsed"] == 2  # two player aggregates
        assert snaps["matched"] == 1
        assert snaps["unjoined"] == 1
        assert snaps["joinRate"] == 0.5

    def test_it_does_not_write_anything(self, tmp_path, fixture_bundle, players_dir, monkeypatch):
        """A replay must be one default argument away from nothing.

        Threading `as_of` onto `refresh_playerctx` would have left a
        historical reconstruction able to overwrite the live snapshot
        production reads, which is why this is a separate entry point.
        """
        live = tmp_path / "live" / "snapshot.json"
        monkeypatch.setattr(store, "SNAPSHOT_PATH", live)
        service.reconstruct_playerctx(
            as_of=service.AsOf(season=2025, through_week=1),
            fetcher=_fetcher(fixture_bundle),
            players_dir=players_dir,
        )
        assert not live.exists()
        assert not live.parent.exists()

    def test_it_does_not_enforce_the_live_row_floors(self, tmp_path, fixture_bundle, players_dir):
        # A replay at week 1 legitimately has very few rows. Enforcing
        # the production floors would make early weeks unreachable.
        payload = service.reconstruct_playerctx(
            as_of=service.AsOf(season=2025, through_week=1),
            fetcher=_fetcher(fixture_bundle),
            players_dir=players_dir,
        )
        assert payload["parsedCounts"]["snapCounts"] < service._ROW_FLOORS["snapCounts"]
        assert payload["players"]

    def test_an_unbounded_replay_matches_the_live_refresh(
        self, tmp_path, fixture_bundle, players_dir, small_floors
    ):
        # The as-of machinery must be inert when nothing is bounded, or
        # adding it would have silently changed what production serves.
        target = tmp_path / "snapshot.json"
        service.refresh_playerctx(
            fetcher=_fetcher(fixture_bundle),
            players_dir=players_dir,
            snapshot_path=target,
        )
        live = store.load_snapshot(target)
        replay = service.reconstruct_playerctx(
            as_of=service.AsOf(),
            fetcher=_fetcher(fixture_bundle),
            players_dir=players_dir,
        )
        assert replay["players"] == live["players"]
        assert replay["sleeperIndex"] == live["sleeperIndex"]

    def test_the_asof_window_is_stamped_on_the_payload(self, fixture_bundle, players_dir):
        payload = service.reconstruct_playerctx(
            as_of=service.AsOf(season=2025, through_week=3, depth_as_of="2026-07-25"),
            fetcher=_fetcher(fixture_bundle),
            players_dir=players_dir,
        )
        assert payload["asOf"] == {
            "season": 2025,
            "throughWeek": 3,
            "depthAsOf": "2026-07-25",
        }


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
