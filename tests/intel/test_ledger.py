"""Ledger invariants: dedup, unit separation, and window arithmetic.

These are the tests that would have caught the defects this work
fixes.  Each class maps to a non-negotiable stated in the brief.
"""

from __future__ import annotations


import pytest

from src.intel import ledger

DAY_MS = 24 * 3600 * 1000
NOW = 1_800_000_000_000  # fixed clock — no wall-clock flake


@pytest.fixture()
def db(tmp_path):
    ledger.reset_setup_cache()
    path = tmp_path / "ledger.sqlite3"
    conn = ledger.connect(path)
    yield conn
    conn.close()
    ledger.reset_setup_cache()


def event(
    *,
    tx_id: str,
    owner: str,
    asset: str,
    action: str,
    ts: int,
    tx_type: str = "trade",
    league: str = "L1",
    asset_type: str = "player",
    discriminator: str = "",
) -> dict:
    """Mirrors the crawler's emitted shape, including its deterministic
    eventId, so these tests exercise the real ingestion contract."""
    event_id = f"{tx_id}:{owner}:{action}:{asset}"
    if discriminator:
        event_id = f"{event_id}:{discriminator}"
    return {
        "eventId": event_id,
        "txId": tx_id,
        "leagueId": league,
        "ownerId": owner,
        "assetId": asset,
        "assetType": asset_type,
        "action": action,
        "txType": tx_type,
        "ts": ts,
        "week": 1,
        "faabBid": None,
    }


def trade_1for1(tx_id, a_owner, b_owner, a_gets, b_gets, ts, league="L1"):
    """A 1-for-1 trade as the crawler emits it: paired add+drop per
    side.  ONE transaction, TWO asset movements, FOUR observations."""
    return [
        event(tx_id=tx_id, owner=a_owner, asset=a_gets, action="add", ts=ts, league=league),
        event(tx_id=tx_id, owner=b_owner, asset=a_gets, action="drop", ts=ts, league=league),
        event(tx_id=tx_id, owner=b_owner, asset=b_gets, action="add", ts=ts, league=league),
        event(tx_id=tx_id, owner=a_owner, asset=b_gets, action="drop", ts=ts, league=league),
    ]


class TestIdempotency:
    """Re-ingesting the same source data must not change any count."""

    def test_reingesting_identical_events_inserts_nothing(self, db):
        events = trade_1for1("tx1", "userA", "userB", "P1", "P2", NOW - DAY_MS)
        first = ledger.ingest_events(events, conn=db)
        assert first.movements_inserted == 4

        second = ledger.ingest_events(events, conn=db)
        assert second.movements_inserted == 0
        assert second.movements_skipped == 4

        c = ledger.counts(conn=db)
        assert c["tradeCount"] == 1
        assert c["assetMovementCount"] == 4

    def test_aggregates_stable_across_ten_reingests(self, db):
        events = trade_1for1("tx1", "userA", "userB", "P1", "P2", NOW - DAY_MS)
        ledger.ingest_events(events, conn=db)
        baseline = ledger.asset_signals(conn=db)
        for _ in range(10):
            ledger.ingest_events(events, conn=db)
        assert ledger.asset_signals(conn=db) == baseline

    def test_partial_overlap_refetch_adds_only_new(self, db):
        """The crawler refetches overlapping weeks; only genuinely new
        movements may land."""
        old = trade_1for1("tx1", "userA", "userB", "P1", "P2", NOW - 10 * DAY_MS)
        ledger.ingest_events(old, conn=db)
        refetch = old + trade_1for1("tx2", "userA", "userC", "P3", "P4", NOW - DAY_MS)
        result = ledger.ingest_events(refetch, conn=db)
        assert result.movements_inserted == 4  # only tx2's four
        assert ledger.counts(conn=db)["tradeCount"] == 2


class TestUnitSeparation:
    """A transaction, an asset movement, and an observation are three
    different things and must never be conflated."""

    def test_four_player_trade_is_one_transaction(self, db):
        ts = NOW - DAY_MS
        events = []
        for asset in ("P1", "P2"):
            events += [
                event(tx_id="tx1", owner="userA", asset=asset, action="add", ts=ts),
                event(tx_id="tx1", owner="userB", asset=asset, action="drop", ts=ts),
            ]
        for asset in ("P3", "P4"):
            events += [
                event(tx_id="tx1", owner="userB", asset=asset, action="add", ts=ts),
                event(tx_id="tx1", owner="userA", asset=asset, action="drop", ts=ts),
            ]
        ledger.ingest_events(events, conn=db)

        c = ledger.counts(conn=db)
        assert c["tradeCount"] == 1, "a 4-player trade is ONE transaction"
        assert c["assetMovementCount"] == 8, "four assets, each observed from both sides"
        assert c["buyCount"] == 4
        assert c["sellCount"] == 4

    def test_one_player_moving_once_counts_once_per_side(self, db):
        ledger.ingest_events(
            [
                event(tx_id="tx1", owner="userA", asset="P1", action="add", ts=NOW - DAY_MS),
                event(tx_id="tx1", owner="userB", asset="P1", action="drop", ts=NOW - DAY_MS),
            ],
            conn=db,
        )
        rows = {r["assetId"]: r for r in ledger.asset_signals(conn=db)}
        assert rows["P1"]["buys"] == 1
        assert rows["P1"]["sells"] == 1
        assert rows["P1"]["movementCount"] == 2
        assert rows["P1"]["tradeCount"] == 1

    def test_two_tracked_managers_trading_preserves_both_opinions(self, db):
        """Both sides tracked: A's buy and B's sell are both real
        observations of conflicting opinion and must both survive."""
        ledger.ingest_events(
            trade_1for1("tx1", "userA", "userB", "P1", "P2", NOW - DAY_MS), conn=db
        )
        rows = {r["assetId"]: r for r in ledger.asset_signals(conn=db)}
        assert rows["P1"]["buys"] == 1 and rows["P1"]["sells"] == 1
        assert rows["P1"]["net"] == 0
        assert rows["P1"]["volume"] == 2, "disagreement must show as volume, not vanish"
        assert rows["P1"]["uniqueManagers"] == 2

    def test_multiple_picks_same_season_round_do_not_collapse(self, db):
        ts = NOW - DAY_MS
        ledger.ingest_events(
            [
                event(
                    tx_id="tx1",
                    owner="userA",
                    asset="pick:2027:1",
                    action="add",
                    ts=ts,
                    asset_type="pick",
                    discriminator="o3",
                ),
                event(
                    tx_id="tx1",
                    owner="userA",
                    asset="pick:2027:1",
                    action="add",
                    ts=ts,
                    asset_type="pick",
                    discriminator="o5",
                ),
            ],
            conn=db,
        )
        rows = {r["assetId"]: r for r in ledger.asset_signals(conn=db)}
        assert rows["pick:2027:1"]["buys"] == 2, "two distinct picks, not one deduped"


class TestTradeVsWaiver:
    """Waiver adds are not buys.  Drops are not sells."""

    def test_waiver_add_is_not_a_trade_buy(self, db):
        ledger.ingest_events(
            [
                event(
                    tx_id="w1",
                    owner="userA",
                    asset="P1",
                    action="add",
                    ts=NOW - DAY_MS,
                    tx_type="waiver",
                )
            ],
            conn=db,
        )
        assert ledger.asset_signals(conn=db) == [], "waiver add must not appear in trade signals"

    def test_free_agent_add_is_not_a_trade_buy(self, db):
        ledger.ingest_events(
            [
                event(
                    tx_id="f1",
                    owner="userA",
                    asset="P1",
                    action="add",
                    ts=NOW - DAY_MS,
                    tx_type="free_agent",
                )
            ],
            conn=db,
        )
        assert ledger.asset_signals(conn=db) == []

    def test_waiver_drop_is_not_a_trade_sell(self, db):
        ledger.ingest_events(
            [
                event(
                    tx_id="w1",
                    owner="userA",
                    asset="P1",
                    action="drop",
                    ts=NOW - DAY_MS,
                    tx_type="waiver",
                )
            ],
            conn=db,
        )
        assert ledger.asset_signals(conn=db) == []

    def test_waiver_activity_still_queryable_when_explicitly_asked(self, db):
        ledger.ingest_events(
            [
                event(
                    tx_id="w1",
                    owner="userA",
                    asset="P1",
                    action="add",
                    ts=NOW - DAY_MS,
                    tx_type="waiver",
                )
            ],
            conn=db,
        )
        rows = ledger.asset_signals(tx_types=ledger.WAIVER_TX_TYPES, conn=db)
        assert len(rows) == 1 and rows[0]["buys"] == 1

    def test_mixed_feed_counts_only_the_trade(self, db):
        ts = NOW - DAY_MS
        ledger.ingest_events(
            [
                event(tx_id="t1", owner="userA", asset="P1", action="add", ts=ts),
                event(tx_id="w1", owner="userB", asset="P1", action="add", ts=ts, tx_type="waiver"),
                event(
                    tx_id="f1", owner="userC", asset="P1", action="add", ts=ts, tx_type="free_agent"
                ),
            ],
            conn=db,
        )
        rows = {r["assetId"]: r for r in ledger.asset_signals(conn=db)}
        assert rows["P1"]["buys"] == 1, "only the trade counts as a buy"
        assert ledger.counts(conn=db)["buyCount"] == 1
        # …and all three are still on record.
        assert ledger.coverage(conn=db)["movementCount"] == 3


class TestTimeWindows:
    """Windows are overlapping views.  Never additive."""

    def test_trade_15_days_ago(self, db):
        """The brief's exact table."""
        ledger.ingest_events(
            [event(tx_id="tx1", owner="userA", asset="P1", action="add", ts=NOW - 15 * DAY_MS)],
            conn=db,
        )

        def buys(window):
            since = None if window is None else NOW - window * DAY_MS
            rows = ledger.asset_signals(since_ms=since, until_ms=NOW, conn=db)
            return rows[0]["buys"] if rows else 0

        assert buys(7) == 0
        assert buys(30) == 1
        assert buys(90) == 1
        assert buys(None) == 1, "all-time is its own query, not 0+1+1"

    def test_trade_60_days_ago(self, db):
        ledger.ingest_events(
            [event(tx_id="tx1", owner="userA", asset="P1", action="add", ts=NOW - 60 * DAY_MS)],
            conn=db,
        )

        def buys(window):
            since = None if window is None else NOW - window * DAY_MS
            rows = ledger.asset_signals(since_ms=since, until_ms=NOW, conn=db)
            return rows[0]["buys"] if rows else 0

        assert buys(7) == 0
        assert buys(30) == 0
        assert buys(90) == 1
        assert buys(None) == 1

    def test_all_time_is_not_the_sum_of_windows(self, db):
        """The precise failure mode the brief names: one event that is
        a member of three windows is still ONE event."""
        ledger.ingest_events(
            [event(tx_id="tx1", owner="userA", asset="P1", action="add", ts=NOW - 15 * DAY_MS)],
            conn=db,
        )
        w30 = ledger.asset_signals(since_ms=NOW - 30 * DAY_MS, until_ms=NOW, conn=db)[0]["buys"]
        w90 = ledger.asset_signals(since_ms=NOW - 90 * DAY_MS, until_ms=NOW, conn=db)[0]["buys"]
        all_time = ledger.asset_signals(until_ms=NOW, conn=db)[0]["buys"]

        assert w30 == 1 and w90 == 1
        assert all_time == 1
        assert all_time != w30 + w90, "summing nested windows would give 2"

    def test_window_edge_is_inclusive(self, db):
        ledger.ingest_events(
            [event(tx_id="tx1", owner="userA", asset="P1", action="add", ts=NOW - 30 * DAY_MS)],
            conn=db,
        )
        rows = ledger.asset_signals(since_ms=NOW - 30 * DAY_MS, until_ms=NOW, conn=db)
        assert rows[0]["buys"] == 1, "an event exactly at the edge still counts"


class TestIdentity:
    """Stable Sleeper user id, never username."""

    def test_username_change_preserves_identity_and_history(self, db):
        ledger.upsert_users([{"user_id": "u1", "username": "oldname"}], conn=db)
        ledger.upsert_users([{"user_id": "u1", "username": "newname"}], conn=db)
        row = db.execute(
            "SELECT current_username, username_history FROM sleeper_users WHERE user_id='u1'"
        ).fetchone()
        assert row["current_username"] == "newname"
        assert "oldname" in row["username_history"]
        assert db.execute("SELECT COUNT(*) c FROM sleeper_users").fetchone()["c"] == 1

    def test_counts_follow_user_id_across_a_rename(self, db):
        ledger.upsert_users([{"user_id": "u1", "username": "before"}], conn=db)
        ledger.ingest_events(
            [event(tx_id="tx1", owner="u1", asset="P1", action="add", ts=NOW - 2 * DAY_MS)],
            conn=db,
        )
        ledger.upsert_users([{"user_id": "u1", "username": "after"}], conn=db)
        ledger.ingest_events(
            [event(tx_id="tx2", owner="u1", asset="P2", action="add", ts=NOW - DAY_MS)],
            conn=db,
        )
        rows = ledger.manager_asset_activity(user_ids=["u1"], conn=db)
        assert sum(r["buys"] for r in rows) == 2
        assert ledger.counts(conn=db)["uniqueManagerCount"] == 1


class TestManagerActivity:
    def test_excludes_the_league_being_asked_about(self, db):
        """ "Bought elsewhere" must not count the current league."""
        ts = NOW - DAY_MS
        ledger.ingest_events(
            [
                event(tx_id="t1", owner="u1", asset="P1", action="add", ts=ts, league="HOME"),
                event(tx_id="t2", owner="u1", asset="P1", action="add", ts=ts, league="OTHER"),
            ],
            conn=db,
        )
        rows = ledger.manager_asset_activity(
            user_ids=["u1"], asset_id="P1", exclude_league_ids=["HOME"], conn=db
        )
        assert len(rows) == 1
        assert rows[0]["buys"] == 1
        assert rows[0]["uniqueLeagues"] == 1


class TestDataDirIsolation:
    def test_ledger_path_follows_store_data_dir(self, tmp_path, monkeypatch):
        """The ledger must resolve its path at CALL time from
        ``store.DATA_DIR``.  A path captured at import time sails past
        the test suite's redirection and writes real rows into the
        production ``data/intel/`` — which is exactly what happened
        before ``default_path()`` was made dynamic."""
        from src.intel import store

        monkeypatch.setattr(store, "DATA_DIR", tmp_path / "elsewhere")
        assert ledger.default_path().parent == tmp_path / "elsewhere"

    def test_refresh_writes_only_inside_the_redirected_dir(self, tmp_path, monkeypatch):
        from src.intel import store

        target = tmp_path / "redirected"
        monkeypatch.setattr(store, "DATA_DIR", target)
        ledger.reset_setup_cache()
        ledger.ingest_events(
            [event(tx_id="tx1", owner="u1", asset="P1", action="add", ts=NOW - DAY_MS)]
        )
        assert (target / ledger.LEDGER_FILENAME).exists()


class TestPruning:
    def test_prune_drops_only_beyond_retention(self, db):
        ledger.ingest_events(
            [
                event(tx_id="old", owner="u1", asset="P1", action="add", ts=NOW - 500 * DAY_MS),
                event(tx_id="new", owner="u1", asset="P2", action="add", ts=NOW - DAY_MS),
            ],
            conn=db,
        )
        removed = ledger.prune(now_ms=NOW, conn=db)
        assert removed == 1
        assert {r["assetId"] for r in ledger.asset_signals(conn=db)} == {"P2"}

    def test_retention_horizon_supports_90d(self, db):
        assert (
            ledger.MOVEMENT_RETENTION_DAYS >= 90
        ), "a 90-day window is unanswerable if retention is shorter than it"
