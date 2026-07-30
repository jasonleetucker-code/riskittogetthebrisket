"""The /api/intel/* read path, served from the ledger.

Two things this pins that the cutover put at risk:

1. LEAGUE SCOPING.  The ledger is GLOBAL — one file spanning every
   crawled league, including everyone Sharp Tracker's discovery graph
   reaches.  The old snapshot was partitioned per league, so scoping was
   free; now every query must filter to the league's pool explicitly.
   :class:`TestLeagueScoping` is the regression barrier.

2. The defects the cutover exists to eliminate actually reaching the
   payload: no ``trendScore``, waiver adds absent from buy counts, and
   volume present beside net.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.intel import ledger, service, store

DAY_MS = 24 * 3600 * 1000


def _now_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def event(tx_id, owner, asset, action, ts, tx_type="trade", league="L1"):
    return {
        "eventId": f"{tx_id}:{owner}:{action}:{asset}",
        "txId": tx_id,
        "leagueId": league,
        "ownerId": owner,
        "assetId": asset,
        "assetType": "pick" if asset.startswith("pick:") else "player",
        "action": action,
        "txType": tx_type,
        "ts": ts,
        "week": 1,
        "faabBid": None,
    }


def snapshot(member_ids, *, holdings=None, league_key="default"):
    """Persist a crawl snapshot so the pool and holdings resolve."""
    state = store.default_state(season="2026")
    state["generatedAt"] = datetime.now(timezone.utc).isoformat()
    state["members"] = {oid: {"leagues": ["L1"], "truncated": False} for oid in member_ids}
    state["memberNames"] = {oid: f"Mgr {oid}" for oid in member_ids}
    state["leagues"] = {"L1": {"name": "Home", "season": "2026", "holdings": holdings or {}}}
    store.save_state(state, league_key)
    service.invalidate_cache()
    return state


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path / "intel")
    ledger.reset_setup_cache()
    service.invalidate_cache()
    yield
    ledger.reset_setup_cache()
    service.invalidate_cache()


class TestLeagueScoping:
    def test_board_excludes_managers_outside_the_pool(self, env):
        """A global ledger must not leak another league's activity.

        This is the failure the cutover made possible: the snapshot used
        to be partitioned per league, so an unfiltered read was safe.
        It no longer is.
        """
        now = _now_ms()
        snapshot(["mine1", "mine2"])
        ledger.ingest_events(
            [
                event("t1", "mine1", "MINE", "add", now - DAY_MS),
                # A manager from a totally unrelated league's pool —
                # present in the same ledger file, must not appear.
                event("t2", "stranger", "THEIRS", "add", now - DAY_MS, league="L999"),
            ]
        )
        payload = service.build_summary_payload("default")
        assets = {a["assetId"] for a in payload["assets"]}
        assert assets == {"MINE"}

    def test_empty_pool_yields_no_assets_rather_than_everything(self, env):
        """No pool must mean no rows — NOT an unfiltered query.

        An `IN ()` built from an empty list is the classic way this goes
        wrong: it either errors or silently matches all rows.
        """
        now = _now_ms()
        snapshot([])
        ledger.ingest_events([event("t1", "someone", "X", "add", now - DAY_MS)])
        assert service.build_summary_payload("default")["assets"] == []

    def test_shared_member_appears_in_both_leagues(self, env):
        """A manager in TWO of your leagues belongs on both boards.

        This is not a leak, and it is a real behaviour change from the
        snapshot era.  Insider Trading asks "what have my league-mates
        traded, anywhere" — so if the same person is a league-mate in two
        of your leagues, their activity is relevant to both.  The old
        per-league snapshot partition hid this, but that isolation was an
        artifact of which crawl recorded the event, not a semantic
        boundary.
        """
        now = _now_ms()
        snapshot(["shared"], league_key="league_a")
        snapshot(["shared"], league_key="league_b")
        ledger.ingest_events([event("t1", "shared", "P1", "add", now - DAY_MS)])

        for key in ("league_a", "league_b"):
            payload = service.build_summary_payload(key)
            assert {a["assetId"] for a in payload["assets"]} == {
                "P1"
            }, f"{key} should see its own member's activity"

    def test_distinct_pools_do_not_see_each_other(self, env):
        now = _now_ms()
        snapshot(["only_a"], league_key="league_a")
        snapshot(["only_b"], league_key="league_b")
        ledger.ingest_events(
            [
                event("t1", "only_a", "ASSET_A", "add", now - DAY_MS),
                event("t2", "only_b", "ASSET_B", "add", now - DAY_MS),
            ]
        )
        a = {x["assetId"] for x in service.build_summary_payload("league_a")["assets"]}
        b = {x["assetId"] for x in service.build_summary_payload("league_b")["assets"]}
        assert a == {"ASSET_A"}
        assert b == {"ASSET_B"}

    def test_member_payload_scopes_to_that_member(self, env):
        now = _now_ms()
        snapshot(["a", "b"])
        ledger.ingest_events(
            [
                event("t1", "a", "PA", "add", now - DAY_MS),
                event("t2", "b", "PB", "add", now - DAY_MS),
            ]
        )
        payload = service.build_member_payload("default", "a")
        assert {row["assetId"] for row in payload["assets"]} == {"PA"}

    def test_asset_payload_scopes_exposure_to_the_pool(self, env):
        now = _now_ms()
        snapshot(["mine"])
        ledger.ingest_events(
            [
                event("t1", "mine", "P1", "add", now - DAY_MS),
                event("t2", "stranger", "P1", "add", now - DAY_MS, league="L999"),
            ]
        )
        payload = service.build_player_payload("default", "P1")
        assert [m["ownerId"] for m in payload["memberExposure"]] == ["mine"]
        assert payload["windows"]["30d"]["buys"] == 1, "the stranger's buy must not be counted"


class TestDefectsAreGoneFromThePayload:
    def test_no_trend_score_anywhere(self, env):
        now = _now_ms()
        snapshot(["a"])
        ledger.ingest_events([event("t1", "a", "P1", "add", now - DAY_MS)])
        payload = service.build_summary_payload("default")
        row = payload["assets"][0]
        assert "trendScore" not in row
        for win in row["windows"].values():
            assert "trendScore" not in win

    def test_waiver_add_is_absent_from_the_board(self, env):
        """The defect that made the board mostly waiver noise."""
        now = _now_ms()
        snapshot(["a"])
        ledger.ingest_events([event("w1", "a", "WAIVED", "add", now - DAY_MS, tx_type="waiver")])
        payload = service.build_summary_payload("default")
        assert payload["assets"] == []
        assert payload["countedTxTypes"] == ["trade"]

    def test_waiver_activity_has_its_own_payload_with_its_own_words(self, env):
        now = _now_ms()
        snapshot(["a"])
        ledger.ingest_events([event("w1", "a", "WAIVED", "add", now - DAY_MS, tx_type="waiver")])
        payload = service.build_waiver_interest_payload("default")
        assert payload["activityType"] == "waiver_and_free_agent"
        row = payload["assets"][0]
        win = row["windows"]["30d"]
        # Named adds/drops, never buys/sells.
        assert win["adds"] == 1
        assert "buys" not in win and "sells" not in win
        assert "net" not in win, "net adds is not a meaningful waiver concept"

    def test_volume_accompanies_net(self, env):
        now = _now_ms()
        snapshot(["a", "b"])
        ledger.ingest_events(
            [
                event("t1", "a", "P1", "add", now - DAY_MS),
                event("t1", "b", "P1", "drop", now - DAY_MS),
            ]
        )
        row = service.build_summary_payload("default")["assets"][0]
        win = row["windows"]["30d"]
        assert win["net"] == 0
        assert win["volume"] == 2, "disagreement shows as volume, not as absence"
        assert win["uniqueManagers"] == 2
        assert row["confidence"] in ("insufficient", "low", "medium", "high")

    def test_held_and_traded_league_counts_stay_separate(self, env):
        """Unioning them made a widely-rostered player look traded."""
        now = _now_ms()
        snapshot(["a"], holdings={"a": ["HELDONLY"]})
        ledger.ingest_events([event("t1", "a", "TRADED", "add", now - DAY_MS)])
        payload = service.build_player_payload("default", "HELDONLY")
        assert payload["heldLeagueCount"] == 1
        assert (
            payload["windows"]["30d"]["uniqueLeagues"] == 0
        ), "held in a league is not traded in a league"


class TestWindowsAndAuditability:
    def test_windows_are_independent_not_summed(self, env):
        now = _now_ms()
        snapshot(["a"])
        ledger.ingest_events([event("t1", "a", "P1", "add", now - 15 * DAY_MS)])
        row = service.build_summary_payload("default")["assets"][0]
        assert row["windows"]["7d"]["buys"] == 0
        assert row["windows"]["30d"]["buys"] == 1
        assert row["windows"]["90d"]["buys"] == 1

    def test_active_window_is_stamped_on_the_payload(self, env):
        snapshot(["a"])
        payload = service.build_summary_payload("default")
        assert payload["window"] == "30d"
        assert "30d" in payload["windows"]

    def test_asset_payload_carries_the_underlying_movements(self, env):
        """Any count on screen must be auditable back to its trades."""
        now = _now_ms()
        snapshot(["a"])
        ledger.ingest_events([event("t1", "a", "P1", "add", now - DAY_MS)])
        payload = service.build_player_payload("default", "P1")
        assert len(payload["movements"]) == 1
        mv = payload["movements"][0]
        assert mv["txId"] == "t1" and mv["action"] == "add" and mv["txType"] == "trade"

    def test_unknown_asset_returns_none(self, env):
        snapshot(["a"])
        assert service.build_player_payload("default", "NOPE") is None

    def test_sort_by_volume_is_honoured(self, env):
        now = _now_ms()
        snapshot(["a", "b", "c"])
        ledger.ingest_events(
            [
                event("t1", "a", "THIN", "add", now - DAY_MS),
                *[
                    event(f"t{i}", oid, "BROAD", "add", now - DAY_MS)
                    for i, oid in enumerate(["a", "b", "c"], start=2)
                ],
            ]
        )
        rows = service.build_summary_payload("default", sort="volume")["assets"]
        assert rows[0]["assetId"] == "BROAD"
