"""Aggregation: window edges, trade add+drop pairing, ranking metric,
league counting, member exposure."""

from __future__ import annotations

from src.intel import aggregate, crawler, signals
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
        assert summary["signalStrength"] == 0.0

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


class TestNoNestedWindowRanking:
    """The regression barrier for the retired ``trendScore``.

    ``3·net48h + 2·net7d + 1·net30d`` summed NESTED windows, so a
    movement an hour old sat inside all three terms and contributed
    3+2+1 = 6 to the board's sort key.  Everything here pins that one
    event now enters the ranking exactly once.
    """

    def test_trend_score_is_gone(self):
        """The retired formula must not come back under any name."""
        assert not hasattr(aggregate, "trend_score")
        summary = aggregate.build_asset_summary([_event("p1", "add", NOW_MS - HOUR_MS)], NOW_MS)
        assert "trendScore" not in summary["p1"]

    def test_one_fresh_event_is_counted_once_not_once_per_nested_window(self):
        """A single 1-hour-old buy lands in 48h, 7d, 14d AND 30d.  Its
        ranking number must be the value of ONE window, not the sum.

        Hand-computed from the published formula (docs/intel/METRICS.md)
        over the 30d primary window — net 1, volume 1, 1 manager::

            normalized_net  = 1/1                = 1.0
            sample_conf(1)  = 1/(1+5)            = 0.166666…
            breadth(1)      = 1/(1+3)            = 0.25
            strength        = 1.0*0.16666*0.25*100 = 4.1666… → 4.17
        """
        events = [_event("p1", "add", NOW_MS - HOUR_MS)]
        summary = aggregate.build_asset_summary(events, NOW_MS)["p1"]
        # The event really is inside every window — that is the setup,
        # not the bug.  The bug was adding those views together.
        assert [summary["windows"][w]["net"] for w in ("48h", "7d", "14d", "30d")] == [1, 1, 1, 1]
        assert summary["signalStrength"] == 4.17
        # The retired formula would have said 3*1 + 2*1 + 1*1 = 6.
        assert summary["signalStrength"] != 6

    def test_broad_sustained_activity_outranks_thin_and_fresh(self):
        """The exact inversion the old sort key produced.

        One buy an hour ago scored 6 (3+2+1 through the nested
        windows); five buys by five managers ten days ago scored 5 —
        so the thin-and-fresh asset ranked ABOVE the broad one.

        Hand-computed for the broad asset — net 5, volume 5, 5
        managers over the 30d window::

            normalized_net  = 5/5       = 1.0
            sample_conf(5)  = 5/(5+5)   = 0.5
            breadth(5)      = 5/(5+3)   = 0.625
            strength        = 1.0*0.5*0.625*100 = 31.25
        """
        events = [_event("fresh", "add", NOW_MS - HOUR_MS, owner="A", league="L0")]
        events += [
            _event("broad", "add", NOW_MS - 10 * DAY_MS, owner=oid, league=f"L{i}")
            for i, oid in enumerate("BCDEF")
        ]
        summaries = aggregate.build_asset_summary(events, NOW_MS)
        fresh, broad = summaries["fresh"], summaries["broad"]

        # Old formula, recomputed here by hand so the inversion is
        # visible rather than asserted in the abstract.
        old_fresh = 3 * 1 + 2 * 1 + 1 * 1
        old_broad = 3 * 0 + 2 * 0 + 1 * 5
        assert old_fresh > old_broad, "the retired sort key ranked fresh above broad"

        assert fresh["signalStrength"] == 4.17
        assert broad["signalStrength"] == 31.25
        assert broad["signalStrength"] > fresh["signalStrength"]

    def test_thin_signal_is_never_labelled_confident(self):
        events = [_event("p1", "add", NOW_MS - HOUR_MS)]
        summary = aggregate.build_asset_summary(events, NOW_MS)["p1"]
        assert summary["confidence"] == "low"

    def test_velocity_is_a_ratio_of_rates_not_a_sum(self):
        """2 buys in 48h against 4 in 30d: (2/2d) ÷ (4/30d) = 7.5.
        The two 48h buys appear in BOTH terms and cancel, which is why
        a ratio cannot double-count the way the sum did."""
        events = [
            _event("p1", "add", NOW_MS - HOUR_MS, owner="A", event_id="e1"),
            _event("p1", "add", NOW_MS - 2 * HOUR_MS, owner="B", event_id="e2"),
            _event("p1", "add", NOW_MS - 10 * DAY_MS, owner="C", event_id="e3"),
            _event("p1", "add", NOW_MS - 20 * DAY_MS, owner="D", event_id="e4"),
        ]
        summary = aggregate.build_asset_summary(events, NOW_MS)["p1"]
        assert summary["velocity"] == 7.5

    def test_window_spans_come_from_the_one_shared_registry(self):
        """Two registries could drift a span in one module and not the
        other.  There is now one definition; this module reports a
        subset of it (snapshot retention is 45d, so a 90d window read
        off the snapshot would be a 45-day answer under a 90d label)."""
        assert set(aggregate.WINDOWS_MS) <= set(signals.WINDOWS_MS)
        for name, span in aggregate.WINDOWS_MS.items():
            assert span == signals.WINDOWS_MS[name]
        assert aggregate.PRIMARY_WINDOW in aggregate.WINDOWS_MS


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
