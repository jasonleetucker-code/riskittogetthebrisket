"""C1-U8 — the acquisition ledger's invariants.

Every test here is an invariant ("re-ingest cannot duplicate"), never a
count over live data, so this belongs in the deterministic gate.

The ones that would be easy to get wrong, and are therefore the point:

* a conflicting re-ingest is SURFACED, not applied — a ledger whose past
  changes when a collector re-runs is not a ledger;
* a three-team trade stays ONE transaction;
* reacquisition opens a NEW holding period rather than editing the old;
* pick lineage survives transfer AND slot realization, because owner and
  slot are STATE and identity is not;
* ``amount is None`` (not an auction) never collapses into ``0``;
* an undated event never becomes an event dated zero.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.acquisition import events as ev_mod
from src.acquisition import store as store_mod
from src.acquisition.events import events_from_draft_picks, events_from_transaction
from src.acquisition.holdings import (
    ORDER_FIDELITY_ORDERED,
    ORDER_FIDELITY_UNDATED_PRESENT,
    derive_holdings,
    derive_pick_lineage,
)

LEAGUE = "dynasty_main"
T1 = 1_760_000_000_000
T2 = T1 + 86_400_000
T3 = T2 + 86_400_000


@pytest.fixture
def db(tmp_path):
    store_mod._reset_setup_cache_for_tests()
    path = tmp_path / "retention" / "acquisition.sqlite"
    yield path
    store_mod._reset_setup_cache_for_tests()


def _trade(tx_id: str, ts: int | None = T1, **over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "transaction_id": tx_id,
        "type": "trade",
        "status": "complete",
        "leg": 4,
        "status_updated": ts,
        "roster_ids": [1, 2],
        "adds": {"4034": 1},
        "drops": {"4034": 2},
        "draft_picks": [],
    }
    base.update(over)
    return base


def _norm(tx: dict[str, Any], **kw: Any):
    return events_from_transaction(tx, league_key=LEAGUE, **kw)


def _rows(events):
    """Events as replay-order dicts, without a database round trip."""
    return sorted(
        (
            {
                "asset_id": e.asset_id,
                "asset_kind": e.asset_kind,
                "event_type": e.event_type,
                "after_owner_rid": e.after_owner_rid,
                "before_owner_rid": e.before_owner_rid,
                "occurred_at_ms": e.occurred_at_ms,
                "source_ref": e.source_ref,
            }
            for e in events
        ),
        key=lambda r: (
            r["occurred_at_ms"] is None,
            r["occurred_at_ms"] or 0,
            r["source_ref"],
            r["asset_id"],
        ),
    )


# ── ingest idempotence ──────────────────────────────────────────────


class TestIngestIsIdempotent:
    def test_exact_reingest_inserts_nothing_new(self, db):
        events = _norm(_trade("t1"))
        first = store_mod.write_events(events, path=db)
        second = store_mod.write_events(events, path=db)
        assert first["inserted"] == len(events) > 0
        assert second["inserted"] == 0
        assert second["unchanged"] == len(events)
        assert second["conflicts"] == []

    def test_a_conflicting_reingest_is_surfaced_and_not_applied(self, db):
        store_mod.write_events(_norm(_trade("t1")), path=db)
        # Same key, different facts (the trade "moved" to another roster).
        mutated = _norm(_trade("t1", adds={"4034": 3}, drops={"4034": 2}))
        report = store_mod.write_events(mutated, path=db)

        assert report["inserted"] == 0
        assert report["conflicts"], "a changed fact under an existing key must be reported"

        stored = store_mod.read_events(LEAGUE, path=db)
        by_asset = {r["asset_id"]: r for r in stored}
        assert by_asset["player:4034"]["after_owner_rid"] == 1, (
            "the stored event was overwritten — re-running a collector must not be able "
            "to rewrite history"
        )

    def test_ingestion_order_does_not_change_the_result(self, db, tmp_path):
        forward = _norm(_trade("a", ts=T1)) + _norm(_trade("b", ts=T2, adds={"99": 2}))
        store_mod.write_events(forward, path=db)
        a_rows = store_mod.read_events(LEAGUE, path=db)

        store_mod._reset_setup_cache_for_tests()
        other = tmp_path / "retention" / "reverse.sqlite"
        store_mod.write_events(list(reversed(forward)), path=other)
        b_rows = store_mod.read_events(LEAGUE, path=other)

        assert a_rows == b_rows

    def test_same_timestamp_events_still_converge(self, db, tmp_path):
        same = _norm(_trade("a", ts=T1)) + _norm(_trade("b", ts=T1, adds={"99": 2}))
        store_mod.write_events(same, path=db)
        first = store_mod.read_events(LEAGUE, path=db)

        store_mod._reset_setup_cache_for_tests()
        other = tmp_path / "retention" / "shuffled.sqlite"
        store_mod.write_events(list(reversed(same)), path=other)
        assert store_mod.read_events(LEAGUE, path=other) == first

    def test_an_empty_transaction_list_is_not_an_error(self, db):
        assert store_mod.write_events([], path=db)["inserted"] == 0


# ── what normalisation preserves ────────────────────────────────────


class TestNormalisationPreservesTheFacts:
    def test_a_three_team_trade_stays_one_transaction(self):
        tx = _trade(
            "three",
            roster_ids=[1, 2, 3],
            adds={"A": 1, "B": 2, "C": 3},
            drops={"A": 2, "B": 3, "C": 1},
        )
        events = _norm(tx)
        assert len({e.source_ref for e in events}) == 1, "the multi-party shape was split"
        assert len(events) == 3, "one row per asset moved"
        moves = {(e.asset_id, e.before_owner_rid, e.after_owner_rid) for e in events}
        assert moves == {
            ("player:A", 2, 1),
            ("player:B", 3, 2),
            ("player:C", 1, 3),
        }

    def test_players_and_picks_in_one_trade(self):
        tx = _trade(
            "mixed",
            draft_picks=[
                {
                    "season": "2027",
                    "round": 1,
                    "roster_id": 5,
                    "owner_id": 1,
                    "previous_owner_id": 2,
                }
            ],
        )
        events = _norm(tx)
        kinds = {e.asset_kind for e in events}
        assert kinds == {"player", "pick"}
        pick = next(e for e in events if e.asset_kind == "pick")
        assert pick.asset_id == f"pick:{LEAGUE}:2027:r1:o5", (
            "pick identity must come from the C1-U3 owner and be keyed on ORIGIN, which is "
            "what makes it survive every transfer"
        )

    def test_a_pure_pick_trade_is_still_a_trade(self):
        tx = _trade(
            "picks_only",
            adds={},
            drops={},
            draft_picks=[
                {
                    "season": "2028",
                    "round": 2,
                    "roster_id": 7,
                    "owner_id": 3,
                    "previous_owner_id": 7,
                }
            ],
        )
        events = _norm(tx)
        assert [e.asset_kind for e in events] == ["pick"]

    def test_a_waiver_records_its_bid_and_a_free_agent_records_none(self):
        waiver = _norm(
            {
                "transaction_id": "w",
                "type": "waiver",
                "status": "complete",
                "status_updated": T1,
                "adds": {"9": 4},
                "drops": {},
                "settings": {"waiver_bid": 0},
            }
        )
        assert waiver[0].faab_bid == 0, "a waiver that cost nothing is not a waiver with no bid"

        fa = _norm(
            {
                "transaction_id": "f",
                "type": "free_agent",
                "status": "complete",
                "status_updated": T1,
                "adds": {"9": 4},
                "drops": {},
            }
        )
        assert fa[0].faab_bid is None, "a free-agent add has no bid at all"
        assert fa[0].event_type == "FREE_AGENT"

    def test_an_add_drop_produces_two_assets(self):
        events = _norm(
            {
                "transaction_id": "ad",
                "type": "waiver",
                "status": "complete",
                "status_updated": T1,
                "adds": {"in": 4},
                "drops": {"out": 4},
                "settings": {"waiver_bid": 12},
            }
        )
        by_asset = {e.asset_id: e for e in events}
        assert by_asset["player:in"].event_type == "WAIVER"
        assert by_asset["player:out"].event_type == "DROP"
        assert by_asset["player:out"].after_owner_rid is None

    def test_an_undated_event_stays_undated(self, db):
        events = _norm(_trade("undated", ts=None, created=None))
        assert events[0].occurred_at_ms is None
        assert events[0].time_fidelity == "undated"

        store_mod.write_events(events, path=db)
        stored = store_mod.read_events(LEAGUE, path=db)[0]
        assert stored["occurred_at_ms"] is None, "an undated event became an event dated zero"
        assert stored["time_fidelity"] == "undated"

    def test_an_incomplete_transaction_is_refused(self):
        assert _norm(_trade("pending", status="pending")) == []

    def test_a_transaction_without_an_id_is_refused(self):
        assert _norm(_trade("", ts=T1)) == []


class TestDraftSelections:
    def test_an_auction_price_is_recorded(self):
        events = events_from_draft_picks(
            [
                {
                    "pick_no": 3,
                    "player_id": "77",
                    "roster_id": 2,
                    "picked_at": T1,
                    "metadata": {"amount": "$42"},
                }
            ],
            league_key=LEAGUE,
            draft_id="d1",
        )
        assert events[0].auction_amount == 42
        assert events[0].event_type == "DRAFT"
        assert events[0].source_ref == "draft:d1:3"

    def test_a_snake_pick_has_no_amount_rather_than_a_zero_one(self):
        events = events_from_draft_picks(
            [{"pick_no": 1, "player_id": "77", "roster_id": 2, "metadata": {}}],
            league_key=LEAGUE,
            draft_id="d1",
        )
        assert events[0].auction_amount is None, (
            "None means 'not an auction' and 0 means 'went for nothing' — collapsing them "
            "is the defect src/public_league/draft.py already names"
        )

    def test_a_zero_dollar_auction_lot_records_zero(self):
        events = events_from_draft_picks(
            [
                {
                    "pick_no": 9,
                    "player_id": "77",
                    "roster_id": 2,
                    "metadata": {"amount": "0"},
                }
            ],
            league_key=LEAGUE,
            draft_id="d1",
        )
        assert events[0].auction_amount == 0


# ── replay derivations ──────────────────────────────────────────────


class TestHoldingPeriods:
    def test_a_trade_closes_the_giver_and_opens_the_receiver(self):
        holdings = derive_holdings(LEAGUE, _rows(_norm(_trade("t"))))
        by_owner = {h["owner_rid"]: h for h in holdings}
        assert by_owner[2]["disposed_method"] == "TRADE_AWAY"
        assert by_owner[2]["disposed_at_ms"] == T1
        assert by_owner[1]["acquired_method"] == "TRADE"
        assert by_owner[1]["disposed_at_ms"] is None

    def test_reacquisition_opens_a_new_period_without_mutating_the_first(self):
        events = _rows(
            _norm(_trade("away", ts=T1, adds={"P": 2}, drops={"P": 1}))
            + _norm(_trade("back", ts=T2, adds={"P": 1}, drops={"P": 2}))
        )
        holdings = derive_holdings(LEAGUE, events)
        one = sorted((h for h in holdings if h["owner_rid"] == 1), key=lambda h: h["sequence_num"])
        assert [h["sequence_num"] for h in one] == [
            1,
            2,
        ], "owning a player, trading him away and trading him back is three facts"
        assert one[0]["disposed_at_ms"] == T1, "the first period was rewritten"
        assert one[1]["acquired_at_ms"] == T2
        assert one[1]["disposed_at_ms"] is None

    def test_multiple_reacquisition_cycles(self):
        events = _rows(
            _norm(_trade("a1", ts=T1, adds={"P": 2}, drops={"P": 1}))
            + _norm(_trade("b1", ts=T2, adds={"P": 1}, drops={"P": 2}))
            + _norm(_trade("a2", ts=T3, adds={"P": 2}, drops={"P": 1}))
        )
        holdings = derive_holdings(LEAGUE, events)
        seqs = sorted(
            (h["owner_rid"], h["sequence_num"]) for h in holdings if h["asset_id"] == "player:P"
        )
        assert seqs == [(1, 1), (1, 2), (2, 1), (2, 2)]

    def test_replaying_twice_is_identical(self):
        events = _rows(_norm(_trade("t")))
        assert derive_holdings(LEAGUE, events) == derive_holdings(LEAGUE, events)

    def test_an_idempotent_restatement_does_not_open_a_second_period(self):
        """The same acquisition seen twice under different transaction
        ids must not read as owning the asset twice in a row."""
        events = _rows(
            _norm(_trade("t1", ts=T1, adds={"P": 1}, drops={}))
            + _norm(_trade("t2", ts=T2, adds={"P": 1}, drops={}))
        )
        holdings = [h for h in derive_holdings(LEAGUE, events) if h["owner_rid"] == 1]
        assert len(holdings) == 1, holdings

    def test_an_undated_event_degrades_order_fidelity_rather_than_hiding(self):
        dated = derive_holdings(LEAGUE, _rows(_norm(_trade("t", ts=T1))))
        assert {h["order_fidelity"] for h in dated} == {ORDER_FIDELITY_ORDERED}

        mixed = derive_holdings(
            LEAGUE,
            _rows(_norm(_trade("t", ts=T1)) + _norm(_trade("u", ts=None, created=None))),
        )
        assert {h["order_fidelity"] for h in mixed} == {
            ORDER_FIDELITY_UNDATED_PRESENT
        }, "a partially-unorderable history must not be reported as fully ordered"


class TestImportUnknownIsFailClosed:
    def test_an_unexplained_roster_asset_is_import_unknown(self):
        holdings = derive_holdings(LEAGUE, [], current_rosters={"player:Z": 6})
        assert len(holdings) == 1
        assert holdings[0]["acquired_method"] == "IMPORT_UNKNOWN"
        assert holdings[0]["acquired_at_ms"] is None
        assert holdings[0]["basis_missing_reason"] == "no_explaining_event"

    def test_it_is_never_defaulted_to_free_agent(self):
        holdings = derive_holdings(LEAGUE, [], current_rosters={"player:Z": 6})
        assert holdings[0]["acquired_method"] != "FREE_AGENT", (
            "defaulting an unexplained holding to FREE_AGENT because most of them were is "
            "'missing is zero' wearing a label — it reports a $0 basis nobody observed"
        )

    def test_an_explained_asset_is_not_relabelled(self):
        events = _rows(_norm(_trade("t", ts=T1, adds={"P": 1}, drops={})))
        holdings = derive_holdings(LEAGUE, events, current_rosters={"player:P": 1})
        assert len(holdings) == 1
        assert holdings[0]["acquired_method"] == "TRADE"


class TestPickLineage:
    def _pick_tx(self, tx_id: str, ts: int, frm: int | None, to: int) -> dict[str, Any]:
        return _trade(
            tx_id,
            ts=ts,
            adds={},
            drops={},
            draft_picks=[
                {
                    "season": "2028",
                    "round": 1,
                    "roster_id": 9,  # ORIGIN — constant across every hop
                    "owner_id": to,
                    "previous_owner_id": frm,
                }
            ],
        )

    def test_a_pick_traded_twice_is_one_chain_of_two_hops(self):
        events = _rows(_norm(self._pick_tx("h1", T1, 9, 2)) + _norm(self._pick_tx("h2", T2, 2, 5)))
        chain = derive_pick_lineage(LEAGUE, events)
        assert len({h["pick_id"] for h in chain}) == 1, "the chain fragmented into two assets"
        assert [(h["hop_num"], h["from_rid"], h["to_rid"]) for h in chain] == [
            (1, 9, 2),
            (2, 2, 5),
        ]

    def test_two_same_round_picks_do_not_collapse(self):
        """Two 2028 1sts from different origins are different assets.
        The intel ledger's generic ``pick:<season>:<round>`` key cannot
        express this, which is why identity is origin-keyed."""
        tx = _trade(
            "two",
            adds={},
            drops={},
            draft_picks=[
                {"season": "2028", "round": 1, "roster_id": 3, "owner_id": 1},
                {"season": "2028", "round": 1, "roster_id": 8, "owner_id": 1},
            ],
        )
        chain = derive_pick_lineage(LEAGUE, _rows(_norm(tx)))
        assert len({h["pick_id"] for h in chain}) == 2, chain

    def test_identity_survives_slot_realization(self):
        """Slot is STATE.  A pick that lands at 1.04 is the same asset it
        was when nobody knew the order."""
        from src.identity.picks import LeaguePickIdentity, LeaguePickState, OwnedLeaguePick

        identity = LeaguePickIdentity(
            league_key=LEAGUE, season=2028, round_num=1, origin_roster_id=9
        )
        unknown = OwnedLeaguePick(identity=identity, state=LeaguePickState(owner_roster_id=2))
        realized = OwnedLeaguePick(
            identity=identity, state=LeaguePickState(owner_roster_id=2, slot=4)
        )
        assert unknown.identity.canonical_id == realized.identity.canonical_id

        events = _rows(_norm(self._pick_tx("h1", T1, 9, 2)))
        assert derive_pick_lineage(LEAGUE, events)[0]["pick_id"] == identity.canonical_id

    def test_replay_after_realization_does_not_duplicate_the_chain(self):
        events = _rows(_norm(self._pick_tx("h1", T1, 9, 2)))
        assert derive_pick_lineage(LEAGUE, events) == derive_pick_lineage(LEAGUE, events)


class TestDerivedTablesAreRebuiltWholesale:
    def test_rebuilding_replaces_rather_than_accumulates(self, db):
        events = _rows(_norm(_trade("t")))
        holdings = derive_holdings(LEAGUE, events)
        lineage = derive_pick_lineage(LEAGUE, events)

        store_mod.replace_derivations(LEAGUE, holdings, lineage, path=db)
        store_mod.replace_derivations(LEAGUE, holdings, lineage, path=db)

        conn = store_mod.connect(db)
        try:
            count = conn.execute("SELECT COUNT(*) FROM holdings").fetchone()[0]
        finally:
            conn.close()
        assert count == len(holdings)

    def test_rebuilding_one_league_leaves_another_alone(self, db):
        mine = derive_holdings(LEAGUE, _rows(_norm(_trade("t"))))
        theirs = derive_holdings(
            "dynasty_new",
            _rows(events_from_transaction(_trade("o"), league_key="dynasty_new")),
        )
        store_mod.replace_derivations(LEAGUE, mine, [], path=db)
        store_mod.replace_derivations("dynasty_new", theirs, [], path=db)
        store_mod.replace_derivations(LEAGUE, mine, [], path=db)

        conn = store_mod.connect(db)
        try:
            other = conn.execute(
                "SELECT COUNT(*) FROM holdings WHERE league_key = 'dynasty_new'"
            ).fetchone()[0]
        finally:
            conn.close()
        assert other == len(theirs)


class TestCoverageIsCountsOnly:
    def test_no_asset_identifiers_leak_into_the_health_surface(self, db):
        store_mod.write_events(_norm(_trade("t")), path=db)
        cov = store_mod.coverage(path=db)
        assert cov["present"] is True
        assert cov["events"] > 0
        assert cov["privacyClass"] == "private"
        blob = repr(cov)
        assert "player:" not in blob and "4034" not in blob, (
            "a health probe that echoes private acquisition contents moves the privacy "
            "boundary every time someone checks whether the collector is alive"
        )

    def test_an_absent_database_reports_absent_rather_than_empty(self, tmp_path):
        cov = store_mod.coverage(path=tmp_path / "nope.sqlite")
        assert cov["present"] is False
        assert "events" not in cov, "'no database' and 'a database with no rows' are different"


class TestDirectionComesFromTheOwnerFieldNotTheName:
    """``COMMISSIONER`` is in BOTH vocabularies, on purpose — a
    commissioner can hand an asset to a roster or take one off.  So the
    replay must decide direction from ``after_owner_rid``.  Branching on
    the method name drops every commissioner add, and the failure is
    silent: the asset simply is not on anyone's roster afterwards."""

    def test_a_commissioner_add_opens_a_holding(self):
        events = _rows(
            _norm(
                {
                    "transaction_id": "c1",
                    "type": "commissioner",
                    "status": "complete",
                    "status_updated": T1,
                    "adds": {"P": 3},
                    "drops": {},
                }
            )
        )
        holdings = derive_holdings(LEAGUE, events)
        assert [(h["owner_rid"], h["acquired_method"]) for h in holdings] == [(3, "COMMISSIONER")]

    def test_a_commissioner_removal_closes_one(self):
        events = _rows(
            _norm(_trade("t", ts=T1, adds={"P": 1}, drops={}))
            + _norm(
                {
                    "transaction_id": "c2",
                    "type": "commissioner",
                    "status": "complete",
                    "status_updated": T2,
                    "adds": {},
                    "drops": {"P": 1},
                }
            )
        )
        holdings = derive_holdings(LEAGUE, events)
        assert len(holdings) == 1
        assert holdings[0]["disposed_at_ms"] == T2
        assert holdings[0]["disposed_method"] == "DROP"


def test_the_method_vocabularies_overlap_only_where_direction_is_genuinely_ambiguous():
    assert "IMPORT_UNKNOWN" in ev_mod.ACQUISITION_METHODS
    both = set(ev_mod.ACQUISITION_METHODS) & set(ev_mod.DISPOSAL_METHODS)
    assert both == {"COMMISSIONER"}, (
        "a method in both vocabularies is one whose direction the replay must read from "
        f"after_owner_rid rather than the name; unexpected members: {both}"
    )
