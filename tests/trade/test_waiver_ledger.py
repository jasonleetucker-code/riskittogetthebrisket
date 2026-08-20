"""C4-WAIV-01 — the waiver ledger, projected from the canonical acquisition
ledger (C1-ACQ-01). Every test is an invariant over synthetic transactions,
never a count over live data, so this belongs in the deterministic gate.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.acquisition import store as store_mod
from src.acquisition.events import events_from_transaction
from src.trade.waiver_ledger import waiver_claims, waiver_ledger_summary

LEAGUE = "dynasty_main"
T1 = 1_760_000_000_000


@pytest.fixture
def db(tmp_path):
    store_mod._reset_setup_cache_for_tests()
    path = tmp_path / "retention" / "acquisition.sqlite"
    yield path
    store_mod._reset_setup_cache_for_tests()


def _waiver_tx(
    tx_id: str,
    *,
    bid: int | None = 15,
    ts: int | None = T1,
    added: tuple[str, ...] = ("4034",),
    dropped: tuple[str, ...] = (),
    rid: int = 1,
) -> dict[str, Any]:
    return {
        "transaction_id": tx_id,
        "type": "waiver",
        "status": "complete",
        "leg": 3,
        "status_updated": ts,
        "settings": {"waiver_bid": bid} if bid is not None else {},
        "adds": {pid: rid for pid in added},
        "drops": {pid: rid for pid in dropped},
        "draft_picks": [],
    }


def _fa_tx(
    tx_id: str, *, ts: int | None = T1, added: tuple[str, ...] = ("5555",), rid: int = 2
) -> dict[str, Any]:
    return {
        "transaction_id": tx_id,
        "type": "free_agent",
        "status": "complete",
        "leg": 3,
        "status_updated": ts,
        "adds": {pid: rid for pid in added},
        "drops": {},
        "draft_picks": [],
    }


def _ingest(db, txs, league_key: str = LEAGUE) -> None:
    events = []
    for tx in txs:
        events.extend(events_from_transaction(tx, league_key=league_key))
    store_mod.write_events(events, path=db)


def test_a_waiver_claim_groups_add_and_drop_under_one_row(db):
    _ingest(db, [_waiver_tx("t1", bid=23, added=("4034",), dropped=("1111",))])
    claims = waiver_claims(LEAGUE, path=db)

    assert len(claims) == 1
    c = claims[0]
    assert c["sourceRef"] == "tx:t1"
    assert c["transactionType"] == "WAIVER"
    assert c["faabBid"] == 23
    assert [a["assetId"] for a in c["added"]] == ["player:4034"]
    assert [d["assetId"] for d in c["dropped"]] == ["player:1111"]


def test_a_zero_dollar_waiver_is_a_real_claim_not_a_missing_bid(db):
    _ingest(db, [_waiver_tx("t2", bid=0)])
    claims = waiver_claims(LEAGUE, path=db)

    assert claims[0]["faabBid"] == 0

    summary = waiver_ledger_summary(LEAGUE, path=db)
    assert summary["zeroBidClaims"] == 1
    assert summary["faabSpent"] == 0
    assert summary["waiverClaimsMissingBid"] == 0


def test_free_agent_and_waiver_claims_stay_distinct(db):
    _ingest(db, [_waiver_tx("t3", bid=10), _fa_tx("t4")])
    summary = waiver_ledger_summary(LEAGUE, path=db)

    assert summary["waiverClaims"] == 1
    assert summary["freeAgentClaims"] == 1
    assert summary["totalClaims"] == 2

    fa_claim = next(c for c in waiver_claims(LEAGUE, path=db) if c["sourceRef"] == "tx:t4")
    assert fa_claim["transactionType"] == "FREE_AGENT"
    assert fa_claim["faabBid"] is None


def test_a_multi_add_claim_stays_one_row(db):
    _ingest(db, [_waiver_tx("t5", bid=5, added=("4034", "5000"))])
    claims = waiver_claims(LEAGUE, path=db)

    assert len(claims) == 1
    assert {a["assetId"] for a in claims[0]["added"]} == {"player:4034", "player:5000"}


def test_a_drop_only_transaction_is_not_a_claim(db):
    tx = {
        "transaction_id": "t6",
        "type": "waiver",
        "status": "complete",
        "leg": 3,
        "status_updated": T1,
        "settings": {"waiver_bid": 0},
        "adds": {},
        "drops": {"9999": 1},
        "draft_picks": [],
    }
    _ingest(db, [tx])

    assert waiver_claims(LEAGUE, path=db) == []


def test_an_undated_claim_is_never_dated_zero(db):
    _ingest(db, [_waiver_tx("t7", bid=1, ts=None)])
    claims = waiver_claims(LEAGUE, path=db)

    assert claims[0]["occurredAtMs"] is None
    assert claims[0]["timeFidelity"] == "undated"

    summary = waiver_ledger_summary(LEAGUE, path=db)
    assert summary["undatedClaims"] == 1
    assert summary["oldestOccurredAtMs"] is None
    assert summary["newestOccurredAtMs"] is None


def test_a_missing_bid_is_never_coerced_to_zero(db):
    _ingest(db, [_waiver_tx("t8", bid=None)])
    claims = waiver_claims(LEAGUE, path=db)

    assert claims[0]["faabBid"] is None

    summary = waiver_ledger_summary(LEAGUE, path=db)
    assert summary["waiverClaimsMissingBid"] == 1
    assert summary["faabSpent"] == 0


def test_league_isolation(db):
    _ingest(db, [_waiver_tx("t9", bid=1)], league_key=LEAGUE)
    _ingest(db, [_waiver_tx("t10", bid=1)], league_key="dynasty_new")

    assert len(waiver_claims(LEAGUE, path=db)) == 1
    assert len(waiver_claims("dynasty_new", path=db)) == 1


def test_claims_sort_oldest_first_with_undated_leading(db):
    _ingest(
        db,
        [
            _waiver_tx("t11", bid=1, ts=T1 + 1000),
            _waiver_tx("t12", bid=1, ts=None),
            _waiver_tx("t13", bid=1, ts=T1),
        ],
    )
    claims = waiver_claims(LEAGUE, path=db)

    assert [c["sourceRef"] for c in claims] == ["tx:t12", "tx:t13", "tx:t11"]


def test_empty_league_reports_empty_not_an_error(db):
    assert waiver_claims("dynasty_main", path=db) == []
    summary = waiver_ledger_summary("dynasty_main", path=db)
    assert summary["totalClaims"] == 0
    assert summary["faabSpent"] == 0
    assert summary["oldestOccurredAtMs"] is None
