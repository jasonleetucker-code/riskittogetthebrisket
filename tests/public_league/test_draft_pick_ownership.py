"""Public Draft tab pick ownership — the 2026-10-17 P0 regression suite.

Production showed one manager holding eight 2027 first-round picks when the
league's current Sleeper ``/traded_picks`` state gave him four.  Root cause:
``draft._pick_ownership_map`` replayed the ``traded_picks`` of EVERY season in
the chain, newest first, so an older league's ownership STATE overwrote the
current one.  These tests pin the repaired behaviour:

* present ownership comes from the canonical fold
  (``src.identity.picks.build_pick_ownership``) over the CURRENT league only;
* an unreadable ``/traded_picks`` is unknown ownership, never default ownership;
* every season x round reconciles to one pick per originating roster;
* movement statistics count completed trades, never repeated state rows;
* every derived surface (leaderboard, franchise, overview, superlatives,
  awards) agrees with the one inventory.

Snapshots are built directly so each scenario is explicit; draft years are
pinned unless a test is about the year resolver itself.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from src.public_league import draft, franchise, overview, public_contract, snapshot_store
from src.public_league.identity import build_manager_registry, register_handed_off_owners
from src.public_league.snapshot import PublicLeagueSnapshot, SeasonSnapshot

YEARS = ["2027", "2028"]

# Real registry league ids, so canonical asset ids are stamped (and so the
# roster-11 hand-off recorded for dynasty_main applies).
MAIN = "1312006700437352448"
NEW = "1320092771247222784"
JOEL = "712035316776669184"
JOHN = "735693375101108224"


REPO = Path(__file__).resolve().parents[2]


@pytest.fixture()
def real_registry(monkeypatch):
    """The committed league registry (conftest points the suite elsewhere), so
    canonical asset ids carry the real league KEY."""
    from src.api import league_registry

    monkeypatch.setenv("LEAGUE_REGISTRY_PATH", str(REPO / "config" / "leagues" / "registry.json"))
    league_registry.reload_registry()
    yield
    monkeypatch.undo()
    league_registry.reload_registry()


def _owner(rid: int) -> str:
    return f"owner-{rid}"


def _season(
    league_id: str,
    season: str,
    owners: dict[int, str | None],
    traded: list[dict] | None = None,
    *,
    rounds: int = 2,
    state: str = "observed",
    reason: str | None = None,
    trades_by_week: dict[int, list[dict]] | None = None,
) -> SeasonSnapshot:
    return SeasonSnapshot(
        season=season,
        league_id=league_id,
        league={
            "league_id": league_id,
            "season": season,
            "status": "in_season",
            "total_rosters": len(owners),
            "settings": {"draft_rounds": rounds, "type": 2},
        },
        users=[
            {"user_id": oid, "display_name": f"Name {oid}", "metadata": {}}
            for oid in owners.values()
            if oid
        ],
        rosters=[{"roster_id": rid, "owner_id": oid, "players": []} for rid, oid in owners.items()],
        matchups_by_week={},
        transactions_by_week=trades_by_week or {},
        drafts=[],
        draft_picks_by_draft={},
        traded_picks=list(traded or []),
        winners_bracket=[],
        losers_bracket=[],
        traded_picks_state=state,
        traded_picks_reason=reason,
    )


def _snapshot(*seasons: SeasonSnapshot) -> PublicLeagueSnapshot:
    registry = build_manager_registry(
        [{"league": s.league, "users": s.users, "rosters": s.rosters} for s in seasons]
    )
    register_handed_off_owners(registry)
    return PublicLeagueSnapshot(
        root_league_id=seasons[0].league_id,
        generated_at="2026-10-17T00:00:00+00:00",
        seasons=list(seasons),
        managers=registry,
    )


def _tp(season, rnd, origin, owner) -> dict:
    return {"season": season, "round": rnd, "roster_id": origin, "owner_id": owner}


def _trade(tx_id: str, week: int, created: int, legs: list[dict]) -> dict:
    return {
        "transaction_id": tx_id,
        "type": "trade",
        "status": "complete",
        "created": created,
        "leg": week,
        "roster_ids": sorted(
            {leg["owner_id"] for leg in legs} | {leg["previous_owner_id"] for leg in legs}
        ),
        "adds": None,
        "drops": None,
        "draft_picks": legs,
    }


def _leg(season, rnd, origin, frm, to) -> dict:
    return {
        "season": season,
        "round": rnd,
        "roster_id": origin,
        "previous_owner_id": frm,
        "owner_id": to,
    }


# Tests about the draft-year resolver itself run against the real one.
_REAL_YEARS = {"test_inventory_seasons_are_the_canonical_league_draft_years"}


@pytest.fixture(autouse=True)
def _pinned_years(request):
    if request.node.name in _REAL_YEARS:
        yield
        return
    with mock.patch.object(draft, "_owned_pick_seasons", return_value=list(YEARS)):
        yield


def _holder(section: dict, season: str, rnd: int, origin_owner: str) -> list[str]:
    """Owner ids holding the (season, round) pick that originated with origin_owner."""
    return sorted(
        oid
        for oid, picks in section["pickOwnership"].items()
        for p in picks
        if p["season"] == season and p["round"] == rnd and p["originalOwnerId"] == origin_owner
    )


FOUR = {1: _owner(1), 2: _owner(2), 3: _owner(3), 4: _owner(4)}


# 1 + 2 ────────────────────────────────────────────────────────────────────
def test_current_state_wins_over_conflicting_older_snapshots():
    """The live P0 shape: roster 1 traded a pick away THIS season; the older
    league's state still lists roster 1 as its holder."""
    current = _season("L-cur", "2026", FOUR, [_tp("2027", 1, 2, 3)])
    prev = _season("L-prev", "2025", FOUR, [_tp("2027", 1, 2, 1)])
    oldest = _season("L-old", "2024", FOUR, [_tp("2027", 1, 2, 1)])
    section = draft.build_section(_snapshot(current, prev, oldest))
    assert _holder(section, "2027", 1, _owner(2)) == [_owner(3)]
    first_round_1 = [
        p for p in section["pickOwnership"][_owner(1)] if p["season"] == "2027" and p["round"] == 1
    ]
    assert [p["originalOwnerId"] for p in first_round_1] == [_owner(1)]


# 3 ────────────────────────────────────────────────────────────────────────
def test_pick_traded_several_times_shows_its_final_holder():
    current = _season("L-cur", "2026", FOUR, [_tp("2028", 2, 1, 4)])
    prev = _season("L-prev", "2025", FOUR, [_tp("2028", 2, 1, 3)])
    oldest = _season("L-old", "2024", FOUR, [_tp("2028", 2, 1, 2)])
    section = draft.build_section(_snapshot(current, prev, oldest))
    assert _holder(section, "2028", 2, _owner(1)) == [_owner(4)]


# 4 ────────────────────────────────────────────────────────────────────────
def test_same_round_picks_from_different_origins_stay_distinct(real_registry):
    current = _season(MAIN, "2026", FOUR, [_tp("2027", 1, 2, 1), _tp("2027", 1, 3, 1)])
    section = draft.build_section(_snapshot(current))
    firsts = [p for p in section["pickOwnership"][_owner(1)] if p["label"] == "2027 R1"]
    assert len(firsts) == 3
    assert sorted(p["originRosterId"] for p in firsts) == [1, 2, 3]
    assert len({p["assetId"] for p in firsts}) == 3
    assert {p["assetId"] for p in firsts} == {
        "pick:dynasty_main:2027:r1:o1",
        "pick:dynasty_main:2027:r1:o2",
        "pick:dynasty_main:2027:r1:o3",
    }
    labels = sorted(p["originLabel"] for p in firsts)
    assert labels == ["From Name owner-2", "From Name owner-3", "Own"]


# 5 ────────────────────────────────────────────────────────────────────────
def test_numeric_and_string_seasons_name_one_asset():
    current = _season("L-cur", "2026", FOUR, [_tp(2027, 1, 2, 3), _tp("2028", 1, 4, 3)])
    inv = draft.pick_inventory(_snapshot(current))
    assert inv.integrity["ok"] is True
    held = {(p["season"], p["round"], p["originRosterId"]) for p in inv.by_owner[_owner(3)]}
    assert ("2027", 1, 2) in held and ("2028", 1, 4) in held


# 6 ────────────────────────────────────────────────────────────────────────
def test_failed_traded_picks_fetch_is_unknown_ownership_everywhere():
    current = _season(
        "L-cur", "2026", FOUR, [], state="unavailable", reason="traded_picks_fetch_failed"
    )
    prev = _season("L-prev", "2025", FOUR, [_tp("2027", 1, 2, 1)])
    snap = _snapshot(current, prev)
    section = draft.build_section(snap)
    assert section["pickOwnershipState"] == "unavailable"
    assert section["pickOwnershipReason"] == "traded_picks_fetch_failed"
    # No fabricated inventory, counts or ranking — and no fallback to history.
    for key in ("pickOwnership", "stockpileLeaderboard", "mostPicksOwned", "fewestPicksOwned"):
        assert section[key] is None, key
    capital = franchise.build_section(snap)["detail"][_owner(1)]["draftCapital"]
    assert capital["totalPicks"] is None and capital["weightedScore"] is None
    assert capital["pickOwnershipState"] == "unavailable"
    assert overview._draft_capital_leader(section) is None


def test_failed_fetch_propagates_from_the_snapshot_builder():
    from tests.public_league import fixtures

    stubs = fixtures.build_stub_client(traded_picks_unreadable=frozenset({"L2025"}))
    fixtures.install_stubs(stubs)
    try:
        from src.public_league.snapshot import build_public_snapshot

        snap = build_public_snapshot("L2025", max_seasons=2, include_nfl_players=False)
    finally:
        fixtures.restore_stubs()
    assert snap.current_season.traded_picks_state == "unavailable"
    assert snap.current_season.traded_picks_reason == "traded_picks_fetch_failed"
    assert snap.seasons[1].traded_picks_state == "observed"
    assert draft.build_section(snap)["pickOwnership"] is None


# 7 ────────────────────────────────────────────────────────────────────────
def test_observed_empty_traded_picks_is_default_ownership():
    section = draft.build_section(_snapshot(_season("L-cur", "2026", FOUR, [])))
    assert section["pickOwnershipState"] == "observed"
    for rid in FOUR:
        picks = section["pickOwnership"][_owner(rid)]
        assert len(picks) == len(YEARS) * 2
        assert all(p["originRosterId"] == rid and not p["isTraded"] for p in picks)
        assert all(p["originLabel"] == "Own" for p in picks)


# 8 ────────────────────────────────────────────────────────────────────────
def test_unrecognized_rosters_never_erase_a_pick():
    traded = [_tp("2027", 1, 99, 2), _tp("2027", 2, 3, 99), "not-a-row"]
    owners = {**FOUR, 5: None}  # roster 5 is orphaned (no manager)
    current = _season("L-cur", "2026", owners, traded)
    inv = draft.pick_inventory(_snapshot(current))
    # The pick whose holder is unknown stays with its origin (canonical fold).
    assert _holder({"pickOwnership": inv.by_owner}, "2027", 2, _owner(3)) == [_owner(3)]
    # Orphan roster 5's own picks are kept and reported, not dropped.
    assert len(inv.unattributed) == len(YEARS) * 2
    assert {p["holderRosterId"] for p in inv.unattributed} == {5}
    integ = inv.integrity
    assert integ["assetCount"] == integ["expectedAssetCount"] == len(YEARS) * 2 * 5
    assert integ["ignoredTradedPickRows"] == 3
    assert integ["unattributedCount"] == len(YEARS) * 2
    assert integ["ok"] is False  # unattributed picks are a reported condition


# 9 ────────────────────────────────────────────────────────────────────────
def test_roster_handoff_credits_current_manager_and_keeps_history():
    """dynasty_main roster 11 passed from Joel to John in week 6
    (config/leagues/roster_ownership_changes.json)."""
    owners = {1: _owner(1), 11: JOHN}
    trades = {3: [_trade("tx-joel", 3, 3_000, [_leg("2027", 2, 11, 11, 1)])]}
    current = _season(MAIN, "2026", owners, [_tp("2027", 2, 11, 1)], trades_by_week=trades)
    section = draft.build_section(_snapshot(current))
    assert JOEL not in section["pickOwnership"]
    johns = section["pickOwnership"][JOHN]
    assert {p["originRosterId"] for p in johns} == {11}
    assert ("2027", 2) not in {(p["season"], p["round"]) for p in johns}
    # The week-3 trade was Joel's — history stays his.
    (leg,) = section["pickMovementTrail"]
    assert (leg["fromOwnerId"], leg["toOwnerId"]) == (JOEL, _owner(1))


# 10 + 11 ──────────────────────────────────────────────────────────────────
def test_every_season_and_round_reconciles_league_wide():
    owners = {rid: _owner(rid) for rid in range(1, 13)}
    # Roster 12 sends every pick away; roster 1 collects a pile of them.
    traded = [_tp(y, r, 12, 1) for y in YEARS for r in (1, 2)]
    traded += [_tp("2027", 1, rid, 7) for rid in (2, 6, 8)] + [_tp("2028", 2, 5, 9)]
    snap = _snapshot(
        _season("L-cur", "2026", owners, traded),
        _season("L-prev", "2025", owners, [_tp("2027", 1, rid, 1) for rid in (2, 6, 7, 8)]),
    )
    inv = draft.pick_inventory(snap)
    integ = inv.integrity
    assert integ["ok"] is True
    assert integ["expectedPerSeasonRound"] == 12
    assert integ["assetCount"] == 12 * len(YEARS) * 2
    assert not integ["duplicateAssets"] and not integ["missingAssets"]
    assert not integ["mismatchedSeasonRounds"]
    seen = [
        (p["season"], p["round"], p["originRosterId"])
        for picks in inv.by_owner.values()
        for p in picks
    ]
    assert len(seen) == len(set(seen)) == 48
    # Zero-pick manager is still represented, on the inventory and the board.
    assert inv.by_owner[_owner(12)] == []
    board = draft.build_section(snap)["stockpileLeaderboard"]
    assert {r["ownerId"] for r in board} == set(owners.values())
    assert board[-1]["ownerId"] == _owner(12) and board[-1]["totalPicks"] == 0
    # The stale older state did not leak: roster 7 holds the three it received now.
    sevens = [p for p in inv.by_owner[_owner(7)] if (p["season"], p["round"]) == ("2027", 1)]
    assert sorted(p["originRosterId"] for p in sevens) == [2, 6, 7, 8]


# 12 ───────────────────────────────────────────────────────────────────────
def test_leagues_are_isolated(real_registry):
    a = draft.pick_inventory(_snapshot(_season(MAIN, "2026", FOUR, [_tp("2027", 1, 2, 1)])))
    b = draft.pick_inventory(_snapshot(_season(NEW, "2026", FOUR, [])))
    assert all(
        p["assetId"].startswith("pick:dynasty_main:") for ps in a.by_owner.values() for p in ps
    )
    assert all(
        p["assetId"].startswith("pick:dynasty_new:") for ps in b.by_owner.values() for p in ps
    )
    assert len(b.by_owner[_owner(1)]) == len(YEARS) * 2  # A's trade never reaches B


# 13 ───────────────────────────────────────────────────────────────────────
def test_weighted_stockpile_equals_its_inventory():
    traded = [_tp("2027", 1, 2, 1), _tp("2027", 2, 3, 1), _tp("2028", 1, 4, 2)]
    snap = _snapshot(_season("L-cur", "2026", FOUR, traded, rounds=4))
    section = draft.build_section(snap)
    weight = {1: 4, 2: 3, 3: 2, 4: 1}
    for row in section["stockpileLeaderboard"]:
        picks = section["pickOwnership"][row["ownerId"]]
        assert row["totalPicks"] == len(picks)
        assert row["weightedScore"] == sum(weight[p["round"]] for p in picks)


# 14 ───────────────────────────────────────────────────────────────────────
def test_inventory_seasons_are_the_canonical_league_draft_years():
    snap = _snapshot(_season("L-cur", "2026", FOUR, []))
    inv = draft.pick_inventory(snap)
    assert inv.integrity["seasons"] == draft._owned_pick_seasons(snap)
    assert {p["season"] for ps in inv.by_owner.values() for p in ps} == set(
        draft._owned_pick_seasons(snap)
    )


# 15 ───────────────────────────────────────────────────────────────────────
def test_state_rows_are_never_counted_as_trades():
    """Three league-seasons restate one pick's ownership; one trade moved it."""
    trade = _trade("tx-1", 1, 1_000, [_leg("2027", 1, 3, 3, 1)])
    current = _season("L-cur", "2026", FOUR, [_tp("2027", 1, 3, 1)])
    prev = _season("L-prev", "2025", FOUR, [_tp("2027", 1, 3, 1)], trades_by_week={1: [trade]})
    oldest = _season("L-old", "2024", FOUR, [_tp("2027", 1, 3, 1)])
    section = draft.build_section(_snapshot(current, prev, oldest))
    most = section["mostTradedPick"]
    assert most["moveCount"] == 1
    assert most["evidence"] == "completed_trades"
    assert len(section["pickMovementTrail"]) == 1


def test_one_trade_listed_in_two_league_seasons_counts_once():
    trade = _trade("tx-dup", 1, 1_000, [_leg("2027", 1, 3, 3, 1)])
    later = _trade("tx-2", 2, 2_000, [_leg("2027", 1, 3, 1, 2)])
    current = _season("L-cur", "2026", FOUR, [], trades_by_week={1: [trade], 2: [later]})
    prev = _season("L-prev", "2025", FOUR, [], trades_by_week={1: [trade]})
    section = draft.build_section(_snapshot(current, prev))
    assert section["mostTradedPick"]["moveCount"] == 2
    assert [(t["fromOwnerId"], t["toOwnerId"]) for t in section["pickMovementTrail"]] == [
        (_owner(3), _owner(1)),
        (_owner(1), _owner(2)),
    ]


def test_no_completed_trades_withholds_most_traded_pick():
    current = _season("L-cur", "2026", FOUR, [_tp("2027", 1, 3, 1)])
    section = draft.build_section(_snapshot(current))
    assert section["mostTradedPick"] is None
    assert section["pickMovementTrail"] == []


# 16 ───────────────────────────────────────────────────────────────────────
def test_public_payload_is_safe_and_carries_no_raw_league_id(real_registry):
    trade = _trade("tx-1", 1, 1_000, [_leg("2027", 1, 3, 3, 1)])
    current = _season(MAIN, "2026", FOUR, [_tp("2027", 1, 3, 1)], trades_by_week={1: [trade]})
    section = draft.build_section(_snapshot(current))
    public_contract.assert_public_payload_safe(section)
    served = public_contract.public_payload(section)
    ownership_parts = {
        k: served[k]
        for k in (
            "pickOwnership",
            "stockpileLeaderboard",
            "pickInventoryIntegrity",
            "unattributedPicks",
            "mostTradedPick",
            "pickMovementTrail",
        )
    }
    assert MAIN not in json.dumps(ownership_parts)
    assert "tx-1" not in json.dumps(ownership_parts)


# 17 ───────────────────────────────────────────────────────────────────────
def test_franchise_overview_and_draft_tab_agree():
    traded = [_tp("2027", 1, 2, 1), _tp("2027", 1, 3, 1), _tp("2028", 2, 4, 2)]
    snap = _snapshot(
        _season("L-cur", "2026", FOUR, traded),
        _season("L-prev", "2025", FOUR, [_tp("2027", 1, 2, 4)]),
    )
    section = draft.build_section(snap)
    detail = franchise.build_section(snap)["detail"]
    for row in section["stockpileLeaderboard"]:
        capital = detail[row["ownerId"]]["draftCapital"]
        assert capital["totalPicks"] == row["totalPicks"]
        assert capital["weightedScore"] == row["weightedScore"]
        assert capital["picks"] == section["pickOwnership"][row["ownerId"]]
    leader = overview._draft_capital_leader(section)
    assert leader["ownerId"] == section["stockpileLeaderboard"][0]["ownerId"] == _owner(1)


def test_superlatives_and_awards_withhold_pick_terms_when_unknown():
    from src.public_league import awards, superlatives

    current = _season(
        "L-cur", "2026", FOUR, [], state="unavailable", reason="traded_picks_fetch_failed"
    )
    snap = _snapshot(current)
    sup = superlatives.build_section(snap)
    assert sup["mostPickHeavy"] == {"winner": None, "ranking": []}
    assert sup["mostFutureFocused"] == {"winner": None, "ranking": []}
    assert awards._pick_hoarder_scores(snap) is None


# persistence ──────────────────────────────────────────────────────────────
def test_traded_picks_state_round_trips_and_legacy_loads_as_unstated():
    unavailable = _season(
        "L-cur", "2026", FOUR, [], state="unavailable", reason="traded_picks_fetch_failed"
    )
    back = snapshot_store._season_from_dict(snapshot_store._season_to_dict(unavailable))
    assert (back.traded_picks_state, back.traded_picks_reason) == (
        "unavailable",
        "traded_picks_fetch_failed",
    )

    observed = _season("L-cur", "2026", FOUR, [_tp("2027", 1, 2, 1)])
    back = snapshot_store._season_from_dict(snapshot_store._season_to_dict(observed))
    assert (back.traded_picks_state, back.traded_picks_reason) == ("observed", None)
    assert back.traded_picks == observed.traded_picks

    legacy = snapshot_store._season_to_dict(observed)
    legacy.pop("tradedPicksState")
    legacy.pop("tradedPicksReason")
    back = snapshot_store._season_from_dict(legacy)
    assert (back.traded_picks_state, back.traded_picks_reason) == (
        "unavailable",
        "pick_ownership_unstated",
    )
