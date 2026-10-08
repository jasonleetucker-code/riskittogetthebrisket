"""C6-MGR-01 — Manager Scout tendency computation over synthetic ledgers.

Every test builds its own acquisition ledger in ``tmp_path`` from synthetic
Sleeper transactions through the canonical normaliser
(``src.acquisition.events.events_from_transaction``), so nothing here counts
live data and the whole file belongs in the deterministic gate.  The league
key is absent from the registry on purpose.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from src.acquisition import store as store_mod
from src.acquisition.events import events_from_transaction
from src.intel import manager_scout as ms
from src.trade import faab_history

LEAGUE = "test_scout_league"
T_2025 = 1_730_000_000_000
T_2026 = 1_760_000_000_000

# Sleeper re-mints the league id every season, and roster ids are only
# stable inside one of them.  U1 holds roster 1 in 2025 and roster 3 in
# 2026; roster 2 changes hands from U2 to U4 (an orphan takeover).
CHAIN = {
    "2025": {"lid": "SLEEPER_LID_2025_XYZ", "owners": {1: "U1", 2: "U2", 3: "U3"}},
    "2026": {"lid": "SLEEPER_LID_2026_XYZ", "owners": {3: "U1", 2: "U4", 1: "U3"}},
}

POSITIONS = {"100": "QB", "200": "WR", "300": "RB", "400": "DL"}


def _positions(pid: str) -> str | None:
    return POSITIONS.get(pid)


@pytest.fixture
def db(tmp_path):
    store_mod._reset_setup_cache_for_tests()
    ms._reset_memo_for_tests()
    path = tmp_path / "retention" / "acquisition.sqlite"
    yield path
    store_mod._reset_setup_cache_for_tests()
    ms._reset_memo_for_tests()


def _trade(tx_id, *, ts, adds=None, drops=None, picks=None):
    return {
        "transaction_id": tx_id,
        "type": "trade",
        "status": "complete",
        "leg": 4,
        "status_updated": ts,
        "adds": adds or {},
        "drops": drops or {},
        "draft_picks": picks or [],
    }


def _waiver(tx_id, *, ts, rid, add, drop=None, bid=None, kind="waiver"):
    return {
        "transaction_id": tx_id,
        "type": kind,
        "status": "complete",
        "leg": 5,
        "status_updated": ts,
        "settings": {"waiver_bid": bid} if bid is not None else {},
        "adds": {add: rid},
        "drops": {drop: rid} if drop else {},
        "draft_picks": [],
    }


def _ingest(db, season: str, txs, *, owners=True):
    link = CHAIN[season]
    events = []
    for tx in txs:
        events.extend(
            events_from_transaction(
                tx,
                league_key=LEAGUE,
                sleeper_league_id=link["lid"],
                season=season,
                owner_by_roster=link["owners"] if owners else None,
            )
        )
    store_mod.write_events(events, path=db)


def _build(db, **kw):
    kw.setdefault("faab_payload", None)
    kw.setdefault("position_lookup", _positions)
    return ms.build_manager_scout(LEAGUE, acquisition_path=db, **kw)


def _by_owner(payload):
    return {m["ownerId"]: m for m in payload["managers"]}


# ── Trading ───────────────────────────────────────────────────────────────


def _seed_two_seasons(db):
    # 2025: U1 (rid 1) sends QB 100 + WR 200 to U2 (rid 2) for RB 300 and
    # U2's 2026 1st — two assets each way: an even package.
    _ingest(
        db,
        "2025",
        [
            _trade(
                "t25",
                ts=T_2025,
                adds={"100": 2, "200": 2, "300": 1},
                drops={"100": 1, "200": 1, "300": 2},
                picks=[
                    {
                        "season": "2026",
                        "round": 1,
                        "roster_id": 2,
                        "owner_id": 1,
                        "previous_owner_id": 2,
                    }
                ],
            )
        ],
    )
    # 2026: U1 now on rid 3 sends DL 400 + a 2028 2nd to U4 (rid 2) for
    # WR 200 — U1 sends 2 assets, receives 1: consolidating.
    _ingest(
        db,
        "2026",
        [
            _trade(
                "t26",
                ts=T_2026,
                adds={"400": 2, "200": 3},
                drops={"400": 3, "200": 2},
                picks=[
                    {
                        "season": "2028",
                        "round": 2,
                        "roster_id": 3,
                        "owner_id": 2,
                        "previous_owner_id": 3,
                    }
                ],
            )
        ],
    )


def test_one_human_is_one_profile_across_reminted_league_ids(db):
    _seed_two_seasons(db)
    managers = _by_owner(_build(db))
    u1 = managers["U1"]["tradeTendencies"]
    assert u1["state"] == "measured"
    assert u1["tradeCount"] == 2
    assert u1["tradesBySeason"] == {"2025": 1, "2026": 1}
    assert u1["window"]["seasons"] == ["2025", "2026"]


def test_an_orphan_takeover_does_not_merge_two_managers(db):
    _seed_two_seasons(db)
    managers = _by_owner(_build(db))
    assert managers["U2"]["tradeTendencies"]["tradeCount"] == 1
    assert managers["U4"]["tradeTendencies"]["tradeCount"] == 1
    assert managers["U2"]["tradeTendencies"]["tradesBySeason"] == {"2025": 1}
    assert managers["U4"]["tradeTendencies"]["tradesBySeason"] == {"2026": 1}


def test_positions_and_asset_classes_bought_versus_sold(db):
    _seed_two_seasons(db)
    u1 = _by_owner(_build(db))["U1"]["tradeTendencies"]
    assert u1["received"]["byPosition"] == {"RB": 1, "WR": 1}
    assert u1["sent"]["byPosition"] == {"DL": 1, "QB": 1, "WR": 1}
    assert u1["received"]["picks"] == 1 and u1["sent"]["picks"] == 1
    assert u1["netPicks"] == 0
    assert u1["netPlayers"] == 2 - 3
    assert u1["pickShareOfReceived"] == {
        "state": "measured",
        "value": round(1 / 3, 4),
        "sampleSize": 3,
    }


def test_future_pick_activity_is_measured_against_the_trade_season(db):
    _seed_two_seasons(db)
    u1 = _by_owner(_build(db))["U1"]["tradeTendencies"]
    # 2026 1st received in a 2025 trade = 1 season out; 2028 2nd sent in a
    # 2026 trade = 2 seasons out.
    assert u1["received"]["picksBySeasonOffset"] == {"1": 1}
    assert u1["received"]["picksByRound"] == {"1": 1}
    assert u1["sent"]["picksBySeasonOffset"] == {"2": 1}
    assert u1["sent"]["picksByRound"] == {"2": 1}


def test_package_shape_is_structural_counts(db):
    _seed_two_seasons(db)
    u1 = _by_owner(_build(db))["U1"]["tradeTendencies"]
    assert u1["packageShape"]["consolidating"] == 1  # 2026: sent 2, got 1
    assert u1["packageShape"]["even"] == 1  # 2025: sent 2, got 2
    assert u1["packageShape"]["consolidatingShare"]["value"] == 0.5


def test_partners_are_keyed_by_human_and_carry_current_names(db):
    _seed_two_seasons(db)
    teams = [{"ownerId": "U4", "name": "Team Four", "roster_id": 2}]
    u1 = _by_owner(_build(db, current_teams=teams))["U1"]["tradeTendencies"]
    assert {p["ownerId"]: p["trades"] for p in u1["partners"]} == {"U2": 1, "U4": 1}
    named = {p["ownerId"]: p["displayName"] for p in u1["partners"]}
    assert named == {"U2": None, "U4": "Team Four"}


def test_a_three_team_trade_stays_one_trade_with_two_partners(db):
    _ingest(
        db,
        "2026",
        [
            _trade(
                "t3",
                ts=T_2026,
                adds={"100": 2, "200": 1, "300": 3},
                drops={"100": 3, "200": 2, "300": 1},
            )
        ],
    )
    m = _by_owner(_build(db))
    u1 = m["U1"]["tradeTendencies"]  # rid 3 in 2026
    assert u1["tradeCount"] == 1
    assert u1["multiTeamTrades"] == 1
    assert sorted(p["ownerId"] for p in u1["partners"]) == ["U3", "U4"]


def test_an_unresolved_player_is_its_own_bucket_never_a_position(db):
    _ingest(db, "2026", [_trade("tu", ts=T_2026, adds={"999": 3}, drops={"999": 2})])
    u1 = _by_owner(_build(db))["U1"]["tradeTendencies"]
    assert u1["received"]["byPosition"] == {"UNRESOLVED": 1}


def test_no_identity_directory_means_every_player_is_unresolved(db):
    _seed_two_seasons(db)
    payload = _build(db, position_lookup=None)
    assert payload["sources"]["identity"]["state"] == "unavailable"
    u1 = _by_owner(payload)["U1"]["tradeTendencies"]
    assert set(u1["received"]["byPosition"]) == {"UNRESOLVED"}


# ── Missing is never zero ─────────────────────────────────────────────────


def test_a_member_with_no_trades_is_insufficient_not_zero_percent(db):
    _seed_two_seasons(db)
    teams = [{"ownerId": "U9", "name": "Quiet Team", "roster_id": 4}]
    u9 = _by_owner(_build(db, current_teams=teams))["U9"]
    t = u9["tradeTendencies"]
    assert t["state"] == "insufficient_sample"
    assert t["tradeCount"] == 0  # a real count over a present ledger
    assert t["pickShareOfReceived"] == {
        "state": "insufficient_sample",
        "value": None,
        "sampleSize": 0,
    }
    assert t["netPicks"] is None
    assert t["packageShape"]["consolidatingShare"]["value"] is None
    w = u9["waiverTendencies"]
    assert w["state"] == "insufficient_sample"
    assert w["waiverShareOfClaims"]["value"] is None


def test_a_missing_ledger_is_unavailable_and_is_not_created(db):
    assert not db.exists()
    teams = [{"ownerId": "U1", "name": "One", "roster_id": 3}]
    payload = _build(db, current_teams=teams)
    assert not db.exists(), "reading must not mint an empty ledger"
    u1 = _by_owner(payload)["U1"]
    assert u1["tradeTendencies"] == {
        "state": "unavailable",
        "reason": "acquisition_store_missing",
        "sampleSize": None,
    }
    assert u1["waiverTendencies"]["state"] == "unavailable"
    assert payload["sources"]["trades"]["state"] == "acquisition_store_missing"


def test_unattributed_sides_are_counted_never_assigned(db):
    _ingest(db, "2026", [_trade("tx", ts=T_2026, adds={"100": 3}, drops={"100": 2})], owners=False)
    payload = _build(db)
    assert payload["managers"] == []
    assert payload["sources"]["trades"]["unattributedSides"] == 2


# ── Waivers ───────────────────────────────────────────────────────────────


def test_waiver_activity_by_manager_and_position(db):
    _ingest(
        db,
        "2025",
        [
            _waiver("w1", ts=T_2025, rid=1, add="300", drop="100", bid=12),
            _waiver("w2", ts=T_2025 + 1, rid=1, add="200", kind="free_agent"),
        ],
    )
    _ingest(db, "2026", [_waiver("w3", ts=T_2026, rid=3, add="400", bid=0)])
    w = _by_owner(_build(db))["U1"]["waiverTendencies"]
    assert w["state"] == "measured"
    assert w["claims"] == 3
    assert w["waiverClaims"] == 2 and w["freeAgentClaims"] == 1
    assert w["claimsWithDrop"] == 1
    assert w["claimsBySeason"] == {"2025": 2, "2026": 1}
    assert w["addedByPosition"] == {"DL": 1, "RB": 1, "WR": 1}
    assert w["waiverShareOfClaims"]["value"] == round(2 / 3, 4)


# ── FAAB ──────────────────────────────────────────────────────────────────


def _faab(rows_by_season):
    return {
        "schemaVersion": 2,
        "seasons": [
            {"season": season, "budget": 100, "adds": rows}
            for season, rows in rows_by_season.items()
        ],
    }


def _bid(owner, pct, *, status="complete", tx_type="waiver"):
    return {
        "playerId": "1",
        "bid": int(pct),
        "bidPct": float(pct),
        "week": 3,
        "type": tx_type,
        "status": status,
        "won": status == "complete",
        "ownerId": owner,
    }


def test_faab_share_of_budget_and_bid_versus_clearing_price(db):
    payload = _build(
        db,
        faab_payload=_faab(
            {
                "2026": [
                    _bid("U1", 10.0),
                    _bid("U1", 0.0),
                    _bid("U1", 5.0, status="failed"),
                    _bid("U2", 20.0),
                ]
            }
        ),
    )
    f = _by_owner(payload)["U1"]["faabTendencies"]
    assert f["state"] == "measured"
    assert f["winningBids"]["sampleSize"] == 2
    assert f["winningBids"]["meanPctOfBudget"] == 5.0
    # league mean clearing = (10 + 0 + 20) / 3 = 10
    assert f["winningBids"]["ratioToLeagueMeanClearingPct"] == 0.5
    assert f["resolvedBids"]["sampleSize"] == 3
    assert f["resolvedBids"]["failedBids"] == 1
    assert f["resolvedBids"]["failedShare"]["value"] == round(1 / 3, 4)
    assert f["resolvedBids"]["meanPctOfBudget"] == 5.0
    # The predictor's own factor, as the FAAB engine applies it.
    priors = faab_history.summarize_bid_history(
        _faab(
            {
                "2026": [
                    _bid("U1", 10.0),
                    _bid("U1", 0.0),
                    _bid("U1", 5.0, status="failed"),
                    _bid("U2", 20.0),
                ]
            }
        )
    )
    factor, low = faab_history.owner_aggression_factor(priors, "U1")
    assert f["predictor"]["factor"] == round(factor, 4)
    assert f["predictor"]["lowSample"] is low is False
    assert payload["sources"]["faab"]["leagueMeanClearingPct"] == 10.0


def test_a_league_where_everything_cleared_free_has_no_ratio(db):
    payload = _build(db, faab_payload=_faab({"2026": [_bid("U1", 0.0), _bid("U2", 0.0)]}))
    f = _by_owner(payload)["U1"]["faabTendencies"]
    assert f["winningBids"]["meanPctOfBudget"] == 0.0  # a real $0 mean
    assert f["winningBids"]["ratioToLeagueMeanClearingPct"] is None  # undefined, not 1.0


def test_no_bids_from_a_member_is_insufficient_and_missing_history_unavailable(db):
    teams = [{"ownerId": "U9", "name": "Quiet", "roster_id": 4}]
    with_history = _build(db, current_teams=teams, faab_payload=_faab({"2026": [_bid("U1", 4.0)]}))
    f9 = _by_owner(with_history)["U9"]["faabTendencies"]
    assert f9["state"] == "insufficient_sample"
    assert f9["winningBids"]["meanPctOfBudget"] is None
    assert f9["resolvedBids"]["failedBids"] is None
    assert f9["predictor"]["lowSample"] is True

    without = _build(db, current_teams=teams, faab_payload=None)
    assert _by_owner(without)["U9"]["faabTendencies"]["state"] == "unavailable"
    assert without["sources"]["faab"]["state"] == "bid_history_missing"


# ── Lineups ───────────────────────────────────────────────────────────────


def _cfg(best_ball, stated=True):
    return SimpleNamespace(
        best_ball=best_ball, stated_fields=frozenset({"bestBall"}) if stated else frozenset()
    )


@pytest.mark.parametrize(
    "cfg, state, reason",
    [
        (_cfg(True), "not_applicable", "best_ball_league_lineups_are_set_automatically"),
        (_cfg(False), "not_measured", "no_canonical_lineup_decision_history"),
        (_cfg(False, stated=False), "not_measured", "league_format_unstated"),
    ],
)
def test_lineup_behaviour_states(db, cfg, state, reason):
    teams = [{"ownerId": "U1", "name": "One", "roster_id": 3}]
    m = _by_owner(_build(db, current_teams=teams, league_cfg=cfg))["U1"]
    assert m["lineupTendencies"]["state"] == state
    assert m["lineupTendencies"]["reason"] == reason


# ── Output hygiene ────────────────────────────────────────────────────────


def test_no_raw_sleeper_league_id_is_published(db):
    _seed_two_seasons(db)
    blob = json.dumps(_build(db))
    for link in CHAIN.values():
        assert link["lid"] not in blob


BOARD = {
    "meta": {"generatedAt": "2026-10-08T00:00:00+00:00"},
    "currentDraftYear": 2027,
    "playersArray": [
        {"playerId": "100", "assetClass": "player", "rankDerivedValue": 5000},
        {"playerId": "200", "assetClass": "player", "rankDerivedValue": 3000},
        {"playerId": "300", "assetClass": "player", "rankDerivedValue": 2000},
        # The board declines to price this one.
        {"playerId": "400", "assetClass": "player", "rankDerivedValue": None},
        {"canonicalName": "2028 Round 2", "assetClass": "pick", "rankDerivedValue": 1500},
    ],
}


def test_value_at_today_is_a_raw_canonical_sum_with_unpriced_disclosed(db):
    _seed_two_seasons(db)
    v = _by_owner(_build(db, contract=BOARD))["U1"]["tradeTendencies"]["valueAtToday"]
    assert v["state"] == "measured"
    assert v["basis"] == "todays_canonical_board_raw_sum_not_value_adjusted"
    assert v["boardAsOf"] == "2026-10-08T00:00:00+00:00"
    # Received: RB 300 (2000) + WR 200 (3000); the 2026 1st is a drafted
    # class no longer on the board -> unpriced, NOT 0.
    assert v["receivedTotal"] == 5000
    assert v["unpricedReceived"] == 1
    # Sent: QB 100 (5000) + WR 200 (3000) + 2028 2nd at its generic grade
    # (1500); DL 400 is unpriced.
    assert v["sentTotal"] == 9500
    assert v["unpricedSent"] == 1
    assert v["netTotal"] == -4500
    assert (v["receivedPerTrade"], v["sentPerTrade"], v["netPerTrade"]) == (2500, 4750, -2250)
    assert v["pricedAssets"] == 5 and v["unpricedAssets"] == 2
    assert v["picksAtGenericGrade"] == 1


def test_an_all_unpriced_side_has_no_total_not_zero(db):
    _ingest(db, "2026", [_trade("tu", ts=T_2026, adds={"400": 3}, drops={"400": 2})])
    m = _by_owner(_build(db, contract=BOARD))
    got = m["U1"]["tradeTendencies"]["valueAtToday"]
    assert got["receivedTotal"] is None  # one asset, unpriced
    assert got["sentTotal"] == 0  # sent nothing: a real zero
    assert got["netTotal"] is None


def test_no_board_means_value_unavailable_and_no_trades_insufficient(db):
    _seed_two_seasons(db)
    teams = [{"ownerId": "U9", "name": "Quiet", "roster_id": 4}]
    without = _by_owner(_build(db, current_teams=teams))
    assert without["U1"]["tradeTendencies"]["valueAtToday"] == {
        "state": "unavailable",
        "reason": "no_board_loaded",
        "sampleSize": None,
    }
    with_board = _by_owner(_build(db, current_teams=teams, contract=BOARD))
    quiet = with_board["U9"]["tradeTendencies"]["valueAtToday"]
    assert quiet["state"] == "insufficient_sample"
    assert "receivedTotal" not in quiet


def test_within_season_takeover_limitation_is_named(db):
    payload = _build(db)
    assert payload["limitations"]["withinSeasonTakeover"] == "attributed_to_owner_at_fetch_time"


def test_the_payload_is_deterministic(db):
    _seed_two_seasons(db)
    a = _build(db)
    b = _build(db)
    a.pop("generatedAt")
    b.pop("generatedAt")
    assert a == b
