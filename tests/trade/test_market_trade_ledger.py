"""C4-MTL-01 — the Market Trade Ledger's own-league lane.

Every test is an invariant over synthetic transactions, never a count over
live data, so this belongs in the deterministic gate. The league key used
throughout (``"test_league_xyz"``) is deliberately absent from
``config/leagues/registry.json`` so format metadata resolves to its
honest all-unknown default rather than coupling these tests to live
registry contents.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.acquisition import store as store_mod
from src.acquisition.events import events_from_transaction
from src.trade.market_trade_ledger import market_ledger_summary, market_trades

LEAGUE = "test_league_xyz"
T1 = 1_760_000_000_000


@pytest.fixture
def db(tmp_path):
    store_mod._reset_setup_cache_for_tests()
    path = tmp_path / "retention" / "acquisition.sqlite"
    yield path
    store_mod._reset_setup_cache_for_tests()


def _trade_tx(
    tx_id: str,
    *,
    ts: int | None = T1,
    adds: dict[str, int] | None = None,
    drops: dict[str, int] | None = None,
    picks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "transaction_id": tx_id,
        "type": "trade",
        "status": "complete",
        "leg": 3,
        "status_updated": ts,
        "adds": adds or {},
        "drops": drops or {},
        "draft_picks": picks or [],
    }


def _ingest(db, txs, league_key: str = LEAGUE) -> None:
    events = []
    for tx in txs:
        events.extend(events_from_transaction(tx, league_key=league_key))
    store_mod.write_events(events, path=db)


def test_a_two_team_trade_groups_both_sides_under_one_row(db):
    _ingest(
        db,
        [
            _trade_tx(
                "t1",
                adds={"4034": 1, "1111": 2},
                drops={"4034": 2, "1111": 1},
            )
        ],
    )
    trades = market_trades(LEAGUE, path=db)

    assert len(trades) == 1
    trade = trades[0]
    assert trade["sourceRef"] == "tx:t1"
    assert trade["teamCount"] == 2
    assert trade["assetCount"] == 2

    team1, team2 = trade["teams"]["1"], trade["teams"]["2"]
    assert [a["assetId"] for a in team1["received"]] == ["player:4034"]
    assert [a["assetId"] for a in team1["sent"]] == ["player:1111"]
    assert [a["assetId"] for a in team2["received"]] == ["player:1111"]
    assert [a["assetId"] for a in team2["sent"]] == ["player:4034"]


def test_a_three_team_trade_is_not_flattened_into_a_pair(db):
    _ingest(
        db,
        [
            _trade_tx(
                "t2",
                adds={"100": 1, "200": 2, "300": 3},
                drops={"100": 2, "200": 3, "300": 1},
            )
        ],
    )
    trades = market_trades(LEAGUE, path=db)

    assert len(trades) == 1
    assert trades[0]["teamCount"] == 3
    assert trades[0]["assetCount"] == 3
    assert set(trades[0]["teams"].keys()) == {"1", "2", "3"}


def test_picks_are_carried_as_pick_assets(db):
    pick = {"season": "2027", "round": 1, "roster_id": 1, "owner_id": 2, "previous_owner_id": 1}
    _ingest(db, [_trade_tx("t3", adds={"4034": 2}, drops={"4034": 1}, picks=[pick])])
    trades = market_trades(LEAGUE, path=db)

    assert trades[0]["assetCount"] == 2
    team1, team2 = trades[0]["teams"]["1"], trades[0]["teams"]["2"]
    pick_refs = [a for a in team1["sent"] if a["assetKind"] == "pick"]
    assert len(pick_refs) == 1
    assert pick_refs[0]["assetId"] in [a["assetId"] for a in team2["received"]]


def test_format_metadata_is_present_and_honest_when_unregistered(db):
    _ingest(db, [_trade_tx("t4", adds={"4034": 1}, drops={"4034": 2})])
    trade = market_trades(LEAGUE, path=db)[0]

    assert set(trade["format"].keys()) == {"teams", "superflex", "tep", "tepLevel", "is2Te", "idp"}
    # This league key is not in the registry, so every format field is an
    # honest unknown rather than a fabricated default.
    assert all(v is None for v in trade["format"].values())


def test_a_non_trade_transaction_never_appears(db):
    waiver_tx = {
        "transaction_id": "w1",
        "type": "waiver",
        "status": "complete",
        "leg": 3,
        "status_updated": T1,
        "settings": {"waiver_bid": 5},
        "adds": {"9999": 1},
        "drops": {},
        "draft_picks": [],
    }
    _ingest(db, [waiver_tx])
    assert market_trades(LEAGUE, path=db) == []


def test_an_undated_trade_is_never_dated_zero(db):
    _ingest(db, [_trade_tx("t5", ts=None, adds={"4034": 1}, drops={"4034": 2})])
    trade = market_trades(LEAGUE, path=db)[0]

    assert trade["occurredAtMs"] is None
    assert trade["timeFidelity"] == "undated"


def test_summary_separates_two_team_from_multi_team(db):
    _ingest(
        db,
        [
            _trade_tx("t6", adds={"1": 1}, drops={"1": 2}),
            _trade_tx(
                "t7",
                adds={"2": 1, "3": 2, "4": 3},
                drops={"2": 2, "3": 3, "4": 1},
            ),
        ],
    )
    summary = market_ledger_summary(LEAGUE, path=db)

    assert summary["totalTrades"] == 2
    assert summary["twoTeamTrades"] == 1
    assert summary["multiTeamTrades"] == 1
    assert summary["sourceFamilies"] == ["own_league_sleeper"]


def test_league_isolation(db):
    _ingest(db, [_trade_tx("t8", adds={"1": 1}, drops={"1": 2})], league_key=LEAGUE)
    _ingest(db, [_trade_tx("t9", adds={"1": 1}, drops={"1": 2})], league_key="other_league")

    assert len(market_trades(LEAGUE, path=db)) == 1
    assert len(market_trades("other_league", path=db)) == 1


def test_re_ingesting_the_same_trade_does_not_duplicate_the_row(db):
    tx = _trade_tx("t10", adds={"4034": 1}, drops={"4034": 2})
    _ingest(db, [tx])
    _ingest(db, [tx])
    assert len(market_trades(LEAGUE, path=db)) == 1


def test_empty_league_reports_empty_not_an_error(db):
    assert market_trades(LEAGUE, path=db) == []
    summary = market_ledger_summary(LEAGUE, path=db)
    assert summary["totalTrades"] == 0
    assert summary["oldestOccurredAtMs"] is None
