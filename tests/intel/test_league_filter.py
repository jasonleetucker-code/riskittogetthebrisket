"""Dynasty-only league admission, and the migration into the ledger."""

from __future__ import annotations

import pytest

from src.intel import ingest, ledger, league_filter

DAY_MS = 24 * 3600 * 1000
NOW = 1_800_000_000_000


def league(league_id="L1", type_=None, best_ball=0, **extra):
    settings = dict(extra)
    if type_ is not None:
        settings["type"] = type_
    settings["best_ball"] = best_ball
    return {"league_id": league_id, "settings": settings}


class TestDynastyFilter:
    def test_dynasty_admitted(self):
        assert league_filter.is_eligible(league(type_=2)) is True

    def test_keeper_admitted(self):
        assert league_filter.is_eligible(league(type_=1)) is True

    def test_redraft_excluded(self):
        assert league_filter.is_eligible(league(type_=0)) is False

    def test_best_ball_excluded_regardless_of_type(self):
        assert league_filter.is_eligible(league(type_=2, best_ball=1)) is False

    def test_unknown_type_is_admitted_not_dropped(self):
        """A Sleeper response-shape change must degrade toward the old
        inclusive behaviour, never silently empty the pool."""
        assert league_filter.is_eligible({"league_id": "L1"}) is True
        assert league_filter.is_eligible(league(type_=None)) is True

    def test_unparseable_type_is_admitted(self):
        assert league_filter.is_eligible(league(type_="dynasty")) is True

    def test_partition_reports_what_it_dropped(self):
        eligible, excluded = league_filter.partition(
            [
                league("d1", type_=2),
                league("d2", type_=2),
                league("r1", type_=0),
                league("r2", type_=0),
                league("bb", type_=2, best_ball=1),
            ]
        )
        assert [lg["league_id"] for lg in eligible] == ["d1", "d2"]
        assert excluded == {"redraft": 2, "best_ball": 1}

    def test_partition_of_empty_is_empty(self):
        assert league_filter.partition([]) == ([], {})

    def test_type_labels(self):
        assert league_filter.type_label(league(type_=0)) == "redraft"
        assert league_filter.type_label(league(type_=1)) == "keeper"
        assert league_filter.type_label(league(type_=2)) == "dynasty"
        assert league_filter.type_label(league(type_=2, best_ball=1)) == "best_ball"
        assert league_filter.type_label({"league_id": "x"}) == "unknown"


@pytest.fixture()
def db_path(tmp_path):
    ledger.reset_setup_cache()
    yield tmp_path / "ledger.sqlite3"
    ledger.reset_setup_cache()


def _state():
    return {
        "memberNames": {"u1": "Alice", "u2": "Bob"},
        "leagues": {
            "L1": {
                "name": "Dynasty A",
                "season": "2026",
                "totalRosters": 12,
                "memberOwnerIds": ["u1", "u2"],
            },
        },
        "events": [
            {
                "eventId": "tx1:u1:add:P1",
                "txId": "tx1",
                "leagueId": "L1",
                "ownerId": "u1",
                "assetId": "P1",
                "assetType": "player",
                "action": "add",
                "txType": "trade",
                "ts": NOW - DAY_MS,
                "week": 1,
                "faabBid": None,
            },
            {
                "eventId": "tx1:u2:drop:P1",
                "txId": "tx1",
                "leagueId": "L1",
                "ownerId": "u2",
                "assetId": "P1",
                "assetType": "player",
                "action": "drop",
                "txType": "trade",
                "ts": NOW - DAY_MS,
                "week": 1,
                "faabBid": None,
            },
        ],
    }


class TestSnapshotMigration:
    def test_migration_imports_events_and_entities(self, db_path):
        result = ingest.ingest_state(_state(), league_key="default", path=db_path)
        assert result.movements_inserted == 2

        conn = ledger.connect(db_path)
        try:
            assert ledger.counts(conn=conn)["tradeCount"] == 1
            users = conn.execute("SELECT user_id FROM sleeper_users ORDER BY user_id").fetchall()
            assert [u["user_id"] for u in users] == ["u1", "u2"]
            leagues = conn.execute("SELECT league_id, name FROM leagues").fetchall()
            assert leagues[0]["name"] == "Dynasty A"
            members = conn.execute("SELECT COUNT(*) c FROM league_memberships").fetchone()
            assert members["c"] == 2
        finally:
            conn.close()

    def test_migration_is_idempotent(self, db_path):
        """Re-running the migration must not change a single count."""
        state = _state()
        ingest.ingest_state(state, path=db_path)
        conn = ledger.connect(db_path)
        try:
            before = ledger.asset_signals(conn=conn)
        finally:
            conn.close()

        for _ in range(3):
            again = ingest.ingest_state(state, path=db_path)
            assert again.movements_inserted == 0

        conn = ledger.connect(db_path)
        try:
            assert ledger.asset_signals(conn=conn) == before
        finally:
            conn.close()

    def test_migration_tolerates_empty_and_malformed_state(self, db_path):
        assert ingest.ingest_state({}, path=db_path).movements_inserted == 0
        assert ingest.ingest_state(None, path=db_path).movements_inserted == 0
        bad = {"events": [None, 42, {"eventId": "x"}], "leagues": {"L": "notadict"}}
        assert ingest.ingest_state(bad, path=db_path).movements_inserted == 0
