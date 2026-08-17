"""C1-U8 — the whole chain, on one synthetic league's history.

The unit tests each pin one rule.  This one asks whether the rules
compose: raw Sleeper payloads → events → holdings → cost basis → pick
lineage → roster at a date, with a story that exercises every asset
origin (draft, waiver, free agent, trade) and every awkward case
(reacquisition, a multi-party trade, an undated event, an asset nobody
can explain).

It also pins the property that makes the backfill safe to re-run: doing
the whole thing twice changes nothing.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.acquisition import store as store_mod
from src.acquisition.basis import attach_basis
from src.acquisition.events import events_from_draft_picks, events_from_transaction
from src.acquisition.holdings import derive_holdings, derive_pick_lineage
from src.acquisition.roster import roster_at
from src.history import store as history_store

LEAGUE = "dynasty_main"
_D = datetime(2026, 8, 1, tzinfo=timezone.utc)


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


@pytest.fixture
def paths(tmp_path):
    store_mod._reset_setup_cache_for_tests()
    history_store._reset_setup_cache_for_tests()
    yield tmp_path / "acquisition.sqlite", tmp_path / "temporal_ledger.sqlite"
    store_mod._reset_setup_cache_for_tests()
    history_store._reset_setup_cache_for_tests()


def _observe(path, asset_key, when, value):
    history_store.write_observations(
        [
            {
                "asset_key": asset_key,
                "lane": history_store.LANE_CANONICAL,
                "source_key": "",
                "observed_date": when.date().isoformat(),
                "observed_at": when.isoformat(),
                "origin": "live",
                "asset_class": "offense",
                "value": value,
                "display_name": asset_key,
            }
        ],
        path=path,
    )


def _season_story():
    """One league's season, in the order it happened."""
    draft_day = _D
    return {
        "draft": (
            "d2026",
            [
                {
                    "pick_no": 1,
                    "player_id": "rookie",
                    "roster_id": 1,
                    "picked_at": _ms(draft_day),
                    "metadata": {"amount": "$88"},
                },
                {
                    "pick_no": 2,
                    "player_id": "snake",
                    "roster_id": 2,
                    "picked_at": _ms(draft_day),
                    "metadata": {},
                },
            ],
        ),
        "transactions": [
            {
                "transaction_id": "w1",
                "type": "waiver",
                "status": "complete",
                "status_updated": _ms(draft_day + timedelta(days=7)),
                "leg": 1,
                "adds": {"claimed": 3},
                "drops": {},
                "settings": {"waiver_bid": 14},
            },
            {
                "transaction_id": "fa1",
                "type": "free_agent",
                "status": "complete",
                "status_updated": _ms(draft_day + timedelta(days=8)),
                "leg": 1,
                "adds": {"streamer": 3},
                "drops": {},
            },
            {
                # Three-team trade: players AND a pick.
                "transaction_id": "t3",
                "type": "trade",
                "status": "complete",
                "status_updated": _ms(draft_day + timedelta(days=14)),
                "leg": 2,
                "roster_ids": [1, 2, 3],
                "adds": {"rookie": 2, "snake": 3},
                "drops": {"rookie": 1, "snake": 2},
                "draft_picks": [
                    {
                        "season": "2027",
                        "round": 1,
                        "roster_id": 9,
                        "owner_id": 1,
                        "previous_owner_id": 9,
                    }
                ],
            },
            {
                # The rookie comes home.
                "transaction_id": "t4",
                "type": "trade",
                "status": "complete",
                "status_updated": _ms(draft_day + timedelta(days=30)),
                "leg": 5,
                "roster_ids": [1, 2],
                "adds": {"rookie": 1},
                "drops": {"rookie": 2},
                "draft_picks": [
                    {
                        "season": "2027",
                        "round": 1,
                        "roster_id": 9,
                        "owner_id": 2,
                        "previous_owner_id": 1,
                    }
                ],
            },
            {
                # Sleeper gave us no stamp for this one.
                "transaction_id": "undated",
                "type": "waiver",
                "status": "complete",
                "adds": {"mystery": 4},
                "drops": {},
                "settings": {"waiver_bid": 3},
            },
        ],
    }


def _run(acq_path, hist_path, *, rosters=None):
    story = _season_story()
    draft_id, picks = story["draft"]

    events = events_from_draft_picks(
        picks, league_key=LEAGUE, draft_id=draft_id, sleeper_league_id="L1", season="2026"
    )
    for tx in story["transactions"]:
        events.extend(
            events_from_transaction(tx, league_key=LEAGUE, sleeper_league_id="L1", season="2026")
        )

    report = store_mod.write_events(events, path=acq_path)
    stored = store_mod.read_events(LEAGUE, path=acq_path)
    holdings = derive_holdings(LEAGUE, stored, current_rosters=rosters)
    attach_basis(holdings, path=hist_path)
    lineage = derive_pick_lineage(LEAGUE, stored)
    store_mod.replace_derivations(LEAGUE, holdings, lineage, path=acq_path)
    return report, holdings, lineage


class TestTheWholeChain:
    def test_every_acquisition_method_appears(self, paths):
        acq, hist = paths
        _report, holdings, _lineage = _run(acq, hist)
        methods = {h["acquired_method"] for h in holdings}
        assert {"DRAFT", "WAIVER", "FREE_AGENT", "TRADE"} <= methods, methods

    def test_the_auction_price_and_the_snake_pick_stay_distinguishable(self, paths):
        acq, hist = paths
        _run(acq, hist)
        conn = store_mod.connect(acq)
        try:
            amounts = dict(
                conn.execute(
                    "SELECT asset_id, auction_amount FROM acquisition_events "
                    "WHERE event_type = 'DRAFT'"
                ).fetchall()
            )
        finally:
            conn.close()
        assert amounts["player:rookie"] == 88
        assert amounts["player:snake"] is None, "a snake pick is not a $0 auction lot"

    def test_the_reacquired_rookie_has_two_periods_on_roster_one(self, paths):
        acq, hist = paths
        _report, holdings, _lineage = _run(acq, hist)
        rookie_one = sorted(
            (h for h in holdings if h["asset_id"] == "player:rookie" and h["owner_rid"] == 1),
            key=lambda h: h["sequence_num"],
        )
        assert [h["acquired_method"] for h in rookie_one] == ["DRAFT", "TRADE"]
        assert rookie_one[0]["disposed_method"] == "TRADE_AWAY"
        assert rookie_one[1]["disposed_at_ms"] is None

    def test_the_pick_chain_is_two_hops_on_one_asset(self, paths):
        acq, hist = paths
        _report, _holdings, lineage = _run(acq, hist)
        assert len({h["pick_id"] for h in lineage}) == 1
        assert [(h["hop_num"], h["from_rid"], h["to_rid"]) for h in lineage] == [
            (1, 9, 1),
            (2, 1, 2),
        ]

    def test_the_undated_claim_degrades_order_fidelity_for_the_league(self, paths):
        acq, hist = paths
        _report, holdings, _lineage = _run(acq, hist)
        assert {h["order_fidelity"] for h in holdings} == {"undated_event_present"}

    def test_cost_basis_is_stamped_where_the_ledger_can_answer(self, paths):
        acq, hist = paths
        _observe(hist, "player:rookie", _D + timedelta(days=13), 4200.0)
        _report, holdings, _lineage = _run(acq, hist)

        traded_in = next(
            h
            for h in holdings
            if h["asset_id"] == "player:rookie"
            and h["owner_rid"] == 2
            and h["acquired_method"] == "TRADE"
        )
        assert traded_in["basis_value"] == 4200.0

        drafted = next(
            h for h in holdings if h["asset_id"] == "player:rookie" and h["owner_rid"] == 1
        )
        assert drafted["basis_value"] is None, "nothing was observed before the draft"
        assert drafted["basis_missing_reason"]

    def test_an_unexplained_roster_asset_becomes_import_unknown(self, paths):
        acq, hist = paths
        _report, holdings, _lineage = _run(
            acq, hist, rosters={"player:rookie": 1, "player:ghost": 7}
        )
        ghost = next(h for h in holdings if h["asset_id"] == "player:ghost")
        assert ghost["acquired_method"] == "IMPORT_UNKNOWN"
        assert ghost["basis_missing_reason"] == "no_explaining_event"

        rookie = [h for h in holdings if h["asset_id"] == "player:rookie"]
        assert "IMPORT_UNKNOWN" not in {
            h["acquired_method"] for h in rookie
        }, "an asset whose arrival IS explained must not be relabelled by the roster pass"


class TestRunningItTwiceChangesNothing:
    def test_events_holdings_and_lineage_are_all_stable(self, paths):
        acq, hist = paths
        first_report, first_holdings, first_lineage = _run(acq, hist)
        second_report, second_holdings, second_lineage = _run(acq, hist)

        assert first_report["inserted"] > 0
        assert second_report["inserted"] == 0
        assert second_report["conflicts"] == []
        assert second_holdings == first_holdings
        assert second_lineage == first_lineage

        conn = store_mod.connect(acq)
        try:
            counts = (
                conn.execute("SELECT COUNT(*) FROM acquisition_events").fetchone()[0],
                conn.execute("SELECT COUNT(*) FROM holdings").fetchone()[0],
                conn.execute("SELECT COUNT(*) FROM pick_lineage").fetchone()[0],
            )
        finally:
            conn.close()
        assert counts == (
            first_report["offered"],
            len(first_holdings),
            len(first_lineage),
        )


class TestRosterReconstructionOverTheStory:
    def test_the_roster_changes_across_the_trade(self, paths):
        acq, hist = paths
        _run(acq, hist)

        before = roster_at(LEAGUE, _D + timedelta(days=10), owner_rid=1, path=acq)
        after = roster_at(LEAGUE, _D + timedelta(days=20), owner_rid=1, path=acq)

        assert "player:rookie" in {a["assetId"] for a in before["assets"]}
        assert "player:rookie" not in {
            a["assetId"] for a in after["assets"]
        }, "the rookie was traded away on day 14"

    def test_it_reports_partial_because_of_the_undated_claim(self, paths):
        acq, hist = paths
        _run(acq, hist)
        result = roster_at(LEAGUE, _D + timedelta(days=20), path=acq)
        assert result["fidelity"] == "partial"
        assert result["inferredMemberships"] >= 1

    def test_before_the_draft_there_is_nothing_to_reconstruct_from(self, paths):
        acq, hist = paths
        _run(acq, hist)
        result = roster_at(LEAGUE, _D - timedelta(days=1), path=acq)
        assert result["fidelity"] == "unavailable"
        assert result["assets"] == []
