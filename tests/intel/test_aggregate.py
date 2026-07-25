"""Aggregation: window edges, trade add+drop pairing, trendScore math,
league counting, member exposure."""

from __future__ import annotations

from src.intel import aggregate, crawler
from tests.intel.conftest import DAY_MS, HOUR_MS, NOW_MS, make_trade_tx


def _event(
    asset_id: str,
    action: str,
    ts: int,
    owner: str = "A",
    league: str = "L1",
    event_id: str | None = None,
) -> dict:
    return {
        "eventId": event_id or f"tx-{asset_id}-{action}-{ts}-{owner}",
        "txId": "tx",
        "leagueId": league,
        "ownerId": owner,
        "assetId": asset_id,
        "assetType": "pick" if asset_id.startswith("pick:") else "player",
        "action": action,
        "txType": "trade",
        "ts": ts,
        "week": 1,
        "faabBid": None,
    }


class TestWindowEdges:
    def test_event_exactly_at_48h_edge_is_included(self):
        events = [_event("p1", "add", NOW_MS - 48 * HOUR_MS)]
        summary = aggregate.build_asset_summary(events, NOW_MS)["p1"]
        assert summary["windows"]["48h"] == {"buys": 1, "sells": 0, "net": 1}

    def test_event_just_past_48h_falls_to_7d_window(self):
        events = [_event("p1", "add", NOW_MS - 48 * HOUR_MS - 1)]
        summary = aggregate.build_asset_summary(events, NOW_MS)["p1"]
        assert summary["windows"]["48h"] == {"buys": 0, "sells": 0, "net": 0}
        assert summary["windows"]["7d"] == {"buys": 1, "sells": 0, "net": 1}

    def test_event_older_than_30d_counts_nowhere(self):
        events = [_event("p1", "add", NOW_MS - 31 * DAY_MS)]
        summary = aggregate.build_asset_summary(events, NOW_MS)["p1"]
        assert all(w == {"buys": 0, "sells": 0, "net": 0} for w in summary["windows"].values())
        assert summary["trendScore"] == 0

    def test_future_events_ignored(self):
        events = [_event("p1", "add", NOW_MS + HOUR_MS)]
        assert aggregate.build_asset_summary(events, NOW_MS) == {}


class TestTradePairing:
    def test_trade_produces_paired_add_and_drop_events(self):
        tx = make_trade_tx(
            "t1",
            NOW_MS - HOUR_MS,
            adds={"p42": 2},
            drops={"p42": 1},
            draft_picks=[
                {
                    "season": "2027",
                    "round": 2,
                    "roster_id": 2,
                    "owner_id": 1,
                    "previous_owner_id": 2,
                }
            ],
        )
        rid_to_owner = {"1": "A", "2": "B"}
        events = crawler._events_from_tx(tx, "L1", 1, rid_to_owner, {"A", "B"}, set())

        # Player p42: B adds, A drops.  Pick 2027-2: A adds, B drops.
        by_key = {(e["ownerId"], e["action"], e["assetId"]) for e in events}
        assert by_key == {
            ("B", "add", "p42"),
            ("A", "drop", "p42"),
            ("A", "add", "pick:2027:2"),
            ("B", "drop", "pick:2027:2"),
        }

        summary = aggregate.build_asset_summary(events, NOW_MS)
        # Pool-internal trade: one buy + one sell → net 0 for both assets.
        assert summary["p42"]["windows"]["48h"] == {"buys": 1, "sells": 1, "net": 0}
        assert summary["pick:2027:2"]["windows"]["48h"] == {"buys": 1, "sells": 1, "net": 0}
        assert summary["pick:2027:2"]["assetType"] == "pick"

    def test_incomplete_trade_produces_no_events(self):
        tx = make_trade_tx("t1", NOW_MS - HOUR_MS, adds={"p1": 1}, status="proposed")
        assert crawler._events_from_tx(tx, "L1", 1, {"1": "A"}, {"A"}, set()) == []


class TestTrendScore:
    def test_trend_score_formula(self):
        assert aggregate.trend_score(2, 3, 5) == 3 * 2 + 2 * 3 + 1 * 5 == 17
        assert aggregate.trend_score(-1, 0, 4) == 1

    def test_trend_score_uses_48h_7d_30d_nets(self):
        events = [
            _event("p1", "add", NOW_MS - HOUR_MS),  # in all windows
            _event("p1", "add", NOW_MS - 3 * DAY_MS),  # 7d/14d/30d
            _event("p1", "drop", NOW_MS - 20 * DAY_MS),  # 30d only
        ]
        summary = aggregate.build_asset_summary(events, NOW_MS)["p1"]
        net48, net7, net30 = 1, 2, 1
        assert summary["windows"]["48h"]["net"] == net48
        assert summary["windows"]["7d"]["net"] == net7
        assert summary["windows"]["30d"]["net"] == net30
        assert summary["trendScore"] == 3 * net48 + 2 * net7 + 1 * net30 == 8


class TestLeagueCount:
    def test_league_count_spans_held_and_traded_leagues(self):
        events = [
            _event("p1", "add", NOW_MS - HOUR_MS, league="L1"),
            _event("p1", "drop", NOW_MS - 2 * HOUR_MS, league="L2", owner="B"),
        ]
        holdings = {
            "L2": {"B": ["p1"]},  # overlaps a traded league
            "L3": {"A": ["p1"]},
            "L4": {"A": ["other"]},
        }
        summary = aggregate.build_asset_summary(events, NOW_MS, holdings=holdings)["p1"]
        assert summary["leagueCount"] == 3  # L1 (traded), L2, L3 (held)
        assert summary["heldLeagueCount"] == 2


class TestMemberExposure:
    def test_member_exposure_holds_and_trades(self):
        events = [
            _event("p1", "add", NOW_MS - HOUR_MS, owner="A", league="L1"),
            _event("p1", "add", NOW_MS - DAY_MS, owner="A", league="L2"),
            _event("p1", "drop", NOW_MS - DAY_MS, owner="B", league="L3"),
            _event("p2", "add", NOW_MS - HOUR_MS, owner="A", league="L1"),  # other asset
        ]
        holdings = {
            "L1": {"A": ["p1"]},
            "L2": {"A": ["p1"]},
            "L9": {"C": ["p1"]},
        }
        exposure = aggregate.build_member_exposure(events, holdings, "p1", NOW_MS)
        by_owner = {m["ownerId"]: m for m in exposure}
        assert by_owner["A"]["heldLeagueCount"] == 2
        assert by_owner["A"]["buys30d"] == 2
        assert by_owner["A"]["net30d"] == 2
        assert by_owner["B"]["heldLeagueCount"] == 0
        assert by_owner["B"]["sells30d"] == 1
        assert by_owner["C"]["heldLeagueCount"] == 1
        # Sorted by held-league count desc.
        assert exposure[0]["ownerId"] == "A"
