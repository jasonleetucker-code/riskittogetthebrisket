"""Manager Intelligence Batches B1 + B2 + the unified feed — deterministic.

Every Sleeper call is an injected fake; no network.  Pins the workstream's
"Tests" bullets (``docs/intel/MANAGER_INTELLIGENCE_WORKSTREAM.md``): two- and
three-team trades, picks + FAAB, pending excluded, co-owned rosters, hand-off
and creator attribution, unpriced = ``None`` (never 0), at-time unavailable,
rate-limited weeks, budget exhaustion, waiver add+drop as one event, draft
slot, still-rostered / slot, subsequently dropped, repeat targets, undated
stays undated, creator mismatch excluded, and feed dedupe + ordering.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.intel import manager_activity as ma
from src.public_league import sleeper_client as sc
from src.valuation_math import package_model

NOW_S = 1_792_000_000  # fixed clock (seconds)
DAY = 86_400
USER = {"user_id": "1001", "username": "dynastyfan", "display_name": "Dynasty Fan"}
STATE = {"season": "2026", "league_season": "2026", "season_type": "regular", "leg": 7}

# Our own registry league with a recorded hand-off (config/leagues/
# roster_ownership_changes.json): roster 11 passes from 712035316776669184 to
# 735693375101108224 at week 6.
HANDOFF_LEAGUE = "1312006700437352448"
HANDOFF_FROM = "712035316776669184"
HANDOFF_TO = "735693375101108224"

SF = ["QB", "RB", "WR", "TE", "SUPER_FLEX", "DL", "LB", "BN", "BN"]


def ms(days_ago: float) -> int:
    return int((NOW_S - days_ago * DAY) * 1000)


def _league(lid: str, name: str, *, type_: int = 2) -> dict[str, Any]:
    return {
        "league_id": lid,
        "name": name,
        "season": "2026",
        "status": "in_season",
        "total_rosters": 12,
        "roster_positions": SF,
        "settings": {"type": type_, "taxi_slots": 3},
        "scoring_settings": {"bonus_rec_te": 0.5},
    }


CONTRACT = {
    "playersArray": [
        {
            "playerId": "A",
            "displayName": "Alpha Back",
            "position": "RB",
            "team": "KC",
            "rankDerivedValue": 5000,
            "canonicalConsensusRank": 20,
        },
        {
            "playerId": "B",
            "displayName": "Bravo Receiver",
            "position": "WR",
            "team": "BUF",
            "rankDerivedValue": 4000,
            "canonicalConsensusRank": 30,
        },
        {
            "playerId": "C",
            "displayName": "Charlie End",
            "position": "TE",
            "team": "DET",
            "rankDerivedValue": 3000,
            "canonicalConsensusRank": 45,
        },
        {
            "playerId": "D",
            "displayName": "Delta Backer",
            "position": "LB",
            "team": "SF",
            "rankDerivedValue": 1500,
            "canonicalConsensusRank": 300,
        },
        {
            "playerId": "R",
            "displayName": "Rookie Runner",
            "position": "RB",
            "team": "NYJ",
            "rankDerivedValue": 2500,
            "canonicalConsensusRank": 80,
            "rookie": True,
        },
        {"assetClass": "pick", "canonicalName": "2027 Round 1", "rankDerivedValue": 3500},
        {"assetClass": "pick", "canonicalName": "2027 Round 2", "rankDerivedValue": 1200},
    ]
}
DIRECTORY = {"Z": {"full_name": "Zed Unranked", "position": "WR", "team": "MIA", "years_exp": 3}}


class FakeSleeper:
    """Per-endpoint fakes.  ``tx[(league, week)]`` is a list or a fetch kind."""

    def __init__(self) -> None:
        self.leagues: list[dict[str, Any]] = []
        self.rosters: dict[str, Any] = {}
        self.users: dict[str, Any] = {}
        self.drafts: dict[str, Any] = {}
        self.picks: dict[str, Any] = {}
        self.tx: dict[tuple[str, int], Any] = {}
        self.calls: list[tuple[str, Any]] = []

    @staticmethod
    def _answer(value: Any, default: Any) -> tuple[str, Any]:
        if isinstance(value, str):
            return value, None
        return sc.FETCH_OK, value if value is not None else default

    def fetch_user(self, username):
        self.calls.append(("user", username))
        return (
            (sc.FETCH_OK, USER) if username.lower() == "dynastyfan" else (sc.FETCH_NOT_FOUND, None)
        )

    def fetch_leagues(self, user_id, season):
        self.calls.append(("leagues", season))
        return sc.FETCH_OK, self.leagues

    def fetch_rosters(self, lid):
        self.calls.append(("rosters", lid))
        return self._answer(self.rosters.get(lid), [])

    def fetch_users(self, lid):
        self.calls.append(("users", lid))
        return self._answer(self.users.get(lid), [])

    def fetch_drafts(self, lid):
        self.calls.append(("drafts", lid))
        return self._answer(self.drafts.get(lid), [])

    def fetch_draft_picks(self, did):
        self.calls.append(("picks", did))
        return self._answer(self.picks.get(did), [])

    def fetch_transactions(self, lid, week):
        self.calls.append(("tx", (lid, week)))
        return self._answer(self.tx.get((lid, week)), [])

    def build(self, username="dynastyfan", **kwargs):
        params = {
            "contract": CONTRACT,
            "window": "season",
            "fetch_user": self.fetch_user,
            "fetch_leagues": self.fetch_leagues,
            "fetch_rosters": self.fetch_rosters,
            "fetch_users": self.fetch_users,
            "fetch_transactions": self.fetch_transactions,
            "fetch_drafts": self.fetch_drafts,
            "fetch_draft_picks": self.fetch_draft_picks,
            "fetch_state": lambda: STATE,
            "fetch_directory": lambda: DIRECTORY,
            "now": lambda: NOW_S,
        }
        params.update(kwargs)
        return ma.build_manager_activity(username, **params)


def _tx(tid: str, ttype: str = "trade", **kw: Any) -> dict[str, Any]:
    base = {
        "transaction_id": tid,
        "type": ttype,
        "status": "complete",
        "creator": "1001",
        "created": ms(kw.pop("days_ago", 5)),
        "leg": kw.pop("leg", 6),
        "roster_ids": [],
        "adds": None,
        "drops": None,
        "draft_picks": [],
        "waiver_budget": [],
        "settings": None,
    }
    base["status_updated"] = base["created"] + 1000
    base.update(kw)
    return base


@pytest.fixture(autouse=True)
def _reset():
    ma.reset_caches()
    yield
    ma.reset_caches()


@pytest.fixture
def fake() -> FakeSleeper:
    f = FakeSleeper()
    f.leagues = [_league("L1", "Alpha League")]
    f.rosters["L1"] = [
        {
            "roster_id": 1,
            "owner_id": "1001",
            "players": ["A", "C", "R"],
            "starters": ["A"],
            "taxi": ["R"],
        },
        {"roster_id": 2, "owner_id": "2002", "players": ["B"]},
        {"roster_id": 3, "owner_id": "3003", "players": ["D"]},
    ]
    f.users["L1"] = [
        {"user_id": "1001", "display_name": "Dynasty Fan"},
        {"user_id": "2002", "display_name": "Rival Two"},
        {"user_id": "3003", "display_name": "Rival Three"},
        {"user_id": "9009", "display_name": "The Commish", "is_owner": True},
    ]
    return f


# ── B1 — trades ─────────────────────────────────────────────────────────


def test_two_team_trade_sides_values_and_active_model(fake):
    fake.tx[("L1", 6)] = [
        _tx("t1", roster_ids=[1, 2], adds={"A": 1, "B": 2}, drops={"A": 2, "B": 1}, creator="2002")
    ]
    out = fake.build()
    assert out["status"] == "ok"
    assert out["packageModel"] == package_model.receipt()
    (trade,) = out["trades"]
    assert trade["id"] == "tx:t1" and trade["status"] == "complete" and trade["teamCount"] == 2
    assert trade["week"] == 6 and trade["leagueName"] == "Alpha League"
    assert trade["attribution"] == {"basis": "roster_owner", "uncertain": False, "reason": None}
    me = next(s for s in trade["sides"] if s["isManager"])
    other = next(s for s in trade["sides"] if not s["isManager"])
    assert [p["playerId"] for p in me["playersIn"]] == ["A"]
    assert [p["playerId"] for p in me["playersOut"]] == ["B"]
    assert me["incomingValue"] == 5000 and me["outgoingValue"] == 4000
    assert other["displayName"] == "Rival Two"
    assert me["faabIn"] is None and me["faabOut"] is None
    pc = trade["packageComparison"]
    assert pc["available"] and pc["model"] == package_model.active_model_id()
    assert pc["basis"] == "two_package"
    assert pc["manager"]["rawNet"] == 1000


def test_three_team_trade_stays_one_trade_and_names_its_basis(fake):
    fake.tx[("L1", 6)] = [
        _tx(
            "t3",
            roster_ids=[1, 2, 3],
            adds={"A": 1, "B": 2, "D": 3},
            drops={"A": 2, "B": 3, "D": 1},
            creator="3003",
        )
    ]
    out = fake.build()
    (trade,) = out["trades"]
    assert trade["teamCount"] == 3
    assert {s["rosterId"] for s in trade["sides"]} == {1, 2, 3}
    pc = trade["packageComparison"]
    assert pc["available"] and pc["basis"] == "per_side_received_vs_sent"
    assert "3-team" in pc["note"]
    assert len(pc["sides"]) == 3
    # Exactly one trade-shaped feed event, not three two-party fictions.
    assert [f["id"] for f in out["feed"]] == ["tx:t3"]


def test_trade_with_picks_and_faab(fake):
    fake.tx[("L1", 6)] = [
        _tx(
            "tp",
            roster_ids=[1, 2],
            adds={"B": 1},
            drops={"B": 2},
            draft_picks=[
                {
                    "season": "2027",
                    "round": 1,
                    "roster_id": 2,
                    "previous_owner_id": 2,
                    "owner_id": 1,
                }
            ],
            waiver_budget=[{"sender": 1, "receiver": 2, "amount": 10}],
        )
    ]
    (trade,) = fake.build()["trades"]
    me = next(s for s in trade["sides"] if s["isManager"])
    other = next(s for s in trade["sides"] if not s["isManager"])
    (pick,) = me["picksIn"]
    assert pick["label"] == "2027 Round 1" and pick["value"] == 3500
    assert pick["originRosterId"] == 2 and pick["boardRowName"] == "2027 Round 1"
    assert me["faabOut"] == 10 and me["faabIn"] is None
    assert other["faabIn"] == 10 and other["faabOut"] is None
    assert me["incomingValue"] == 4000 + 3500 and me["outgoingValue"] == 0


def test_pending_and_failed_transactions_are_excluded(fake):
    fake.tx[("L1", 6)] = [
        _tx("p1", status="pending", roster_ids=[1, 2], adds={"A": 1}, drops={"A": 2}),
        _tx("f1", "waiver", status="failed", roster_ids=[1], adds={"B": 1}),
    ]
    out = fake.build()
    assert out["trades"] == [] and out["feed"] == [] and out["acquisitions"] == []
    assert out["coverage"]["excluded"]["not_complete"] == 2


def test_co_owned_roster_is_the_managers(fake):
    fake.leagues.append(_league("L3", "Gamma"))
    fake.rosters["L3"] = [
        {"roster_id": 9, "owner_id": "3003", "co_owners": ["1001"], "players": ["A"]},
        {"roster_id": 4, "owner_id": "4004", "players": []},
    ]
    fake.users["L3"] = [{"user_id": "3003"}, {"user_id": "1001"}, {"user_id": "4004"}]
    fake.tx[("L3", 5)] = [
        _tx("co", roster_ids=[9, 4], adds={"A": 9}, drops={"A": 4}, creator="3003")
    ]
    out = fake.build()
    (trade,) = out["trades"]
    assert next(s for s in trade["sides"] if s["rosterId"] == 9)["isManager"] is True
    assert trade["attribution"]["basis"] == "roster_owner"


def test_unpriced_asset_is_null_with_reason_and_blocks_the_package_grade(fake):
    fake.tx[("L1", 6)] = [_tx("tu", roster_ids=[1, 2], adds={"Z": 1}, drops={"Z": 2})]
    (trade,) = fake.build()["trades"]
    me = next(s for s in trade["sides"] if s["isManager"])
    assert me["playersIn"][0]["value"] is None
    assert me["playersIn"][0]["valueReason"] == "not_on_board"
    assert me["playersIn"][0]["name"] == "Zed Unranked"
    assert me["incomingValue"] is None
    assert me["unpricedAssets"] == [
        {"kind": "player", "name": "Zed Unranked", "reason": "not_on_board"}
    ]
    assert trade["packageComparison"] == {
        "available": False,
        "reason": "unpriced_assets",
        "model": package_model.active_model_id(),
    }


def test_no_board_means_every_value_is_unavailable_never_zero(fake):
    fake.tx[("L1", 6)] = [_tx("tn", roster_ids=[1, 2], adds={"A": 1}, drops={"A": 2})]
    out = fake.build(contract=None)
    me = next(s for s in out["trades"][0]["sides"] if s["isManager"])
    assert out["hasBoard"] is False
    assert me["playersIn"][0]["value"] is None
    assert me["playersIn"][0]["valueReason"] == "board_unavailable"


def test_spent_pick_has_no_current_value(fake):
    fake.drafts["L1"] = [
        {
            "draft_id": "d26",
            "season": "2026",
            "status": "complete",
            "type": "linear",
            "settings": {"teams": 12},
        }
    ]
    fake.tx[("L1", 1)] = [
        _tx(
            "old",
            roster_ids=[1, 2],
            adds={"B": 1},
            drops={"B": 2},
            leg=1,
            days_ago=200,
            draft_picks=[
                {
                    "season": "2026",
                    "round": 1,
                    "roster_id": 1,
                    "previous_owner_id": 1,
                    "owner_id": 2,
                }
            ],
        )
    ]
    (trade,) = fake.build()["trades"]
    me = next(s for s in trade["sides"] if s["isManager"])
    assert me["picksOut"][0]["value"] is None
    assert me["picksOut"][0]["valueReason"] == "pick_already_used"
    assert trade["packageComparison"]["available"] is False


def test_at_time_unavailable_without_a_ledger_and_when_an_asset_is_unresolvable(fake):
    fake.tx[("L1", 6)] = [
        _tx("ta", roster_ids=[1, 2], adds={"A": 1, "B": 2}, drops={"A": 2, "B": 1})
    ]
    out = fake.build()
    (trade,) = out["trades"]
    assert all(not s["available"] for s in trade["atTime"]["sides"])
    assert trade["atTime"]["manager"]["reason"] == "history_ledger_missing"
    assert trade["aging"]["manager"] == {
        "rosterId": 1,
        "available": False,
        "reason": "at_time_unavailable",
    }

    def factory(requests):
        assert requests  # one batched ledger read
        return lambda asset, instant: 3000.0 if asset.get("playerId") == "A" else None

    (trade,) = fake.build(asof_factory=factory)["trades"]
    me = trade["atTime"]["manager"]
    assert me["available"] is False and me["reason"] == "no_historical_evidence"
    assert me["missingAssets"][0]["name"] == "Bravo Receiver"


def test_at_time_and_aging_when_every_asset_resolves(fake):
    fake.tx[("L1", 6)] = [
        _tx("tg", roster_ids=[1, 2], adds={"A": 1, "B": 2}, drops={"A": 2, "B": 1})
    ]

    def factory(requests):
        values = {"A": 4000.0, "B": 4000.0}
        return lambda asset, instant: values.get(asset.get("playerId"))

    (trade,) = fake.build(asof_factory=factory)["trades"]
    at = trade["atTime"]["manager"]
    assert at["available"] and at["rawNet"] == 0
    # Current: +1000 linear (5000 vs 4000, 1-for-1 carries no adjustment).
    assert trade["aging"]["manager"] == {"rosterId": 1, "available": True, "delta": 1000}


def test_creator_outside_every_party_flags_trade_uncertain(fake):
    fake.tx[("L1", 6)] = [
        _tx("tx9", roster_ids=[1, 2], adds={"A": 1}, drops={"A": 2}, creator="5555")
    ]
    (trade,) = fake.build()["trades"]
    assert trade["attribution"] == {
        "basis": "attribution_uncertain",
        "uncertain": True,
        "reason": "creator_not_a_current_party",
    }


def test_window_filters_by_completion_time(fake):
    fake.tx[("L1", 2)] = [
        _tx("w40", roster_ids=[1, 2], adds={"A": 1}, drops={"A": 2}, days_ago=40, leg=2)
    ]
    assert fake.build(window="30d")["trades"] == []
    ma.reset_caches()
    assert [t["id"] for t in fake.build(window="90d")["trades"]] == ["tx:w40"]


# ── coverage / budget ───────────────────────────────────────────────────


def test_rate_limited_week_makes_the_league_partial(fake):
    fake.tx[("L1", 3)] = sc.FETCH_RATE_LIMITED
    out = fake.build()
    (cov,) = out["coverage"]["leagues"]
    assert cov["transactions"] == "partial"
    assert cov["weeksFailed"] == 1 and cov["weeksFetched"] == 7
    assert out["status"] == "partial"


def test_every_week_rate_limited_is_rate_limited(fake):
    for week in range(0, 8):
        fake.tx[("L1", week)] = sc.FETCH_RATE_LIMITED
    (cov,) = fake.build()["coverage"]["leagues"]
    assert cov["transactions"] == "rate_limited"


def test_unreadable_rosters_make_the_league_unavailable(fake):
    fake.rosters["L1"] = sc.FETCH_ERROR
    out = fake.build()
    (cov,) = out["coverage"]["leagues"]
    assert cov["rosters"] == cov["transactions"] == "unavailable"
    assert out["status"] == "partial"
    assert not [c for c in fake.calls if c[0] == "tx"]


def test_budget_exhaustion_is_flagged(fake):
    out = fake.build(call_budget=5)  # rosters + users + drafts + 2 weeks
    cov = out["coverage"]
    assert cov["budgetExhausted"] is True and cov["callsSpent"] == 5
    assert cov["leagues"][0]["transactions"] == "partial"
    assert out["status"] == "partial"
    assert sum(1 for c in fake.calls if c[0] == "tx") == 2


def test_weeks_are_memoised_across_requests(fake):
    fake.build()
    first = sum(1 for c in fake.calls if c[0] == "tx")
    fake.build()
    assert sum(1 for c in fake.calls if c[0] == "tx") == first  # all from the memo


def test_offseason_reads_legs_zero_and_one(fake):
    out = fake.build(fetch_state=lambda: {"season": "2026", "season_type": "off", "leg": 0})
    assert out["coverage"]["legsRequested"] == [0, 1]


def test_earlier_season_reads_every_leg_and_applies_the_whole_season(fake):
    out = fake.build(season="2025", window="7d")
    assert out["coverage"]["legsRequested"] == list(range(0, 19))
    assert out["windowApplied"] == "season"


def test_not_found_and_rate_limited_users(fake):
    assert fake.build(username="ghost")["status"] == "not_found"
    out = fake.build(fetch_user=lambda u: (sc.FETCH_RATE_LIMITED, None))
    assert out["status"] == "rate_limited"


# ── B2 — acquisitions ───────────────────────────────────────────────────


def test_waiver_add_with_its_drop_is_one_event(fake):
    fake.tx[("L1", 4)] = [
        _tx(
            "wv",
            "waiver",
            roster_ids=[1],
            adds={"D": 1},
            drops={"C": 1},
            leg=4,
            settings={"waiver_bid": 7},
        )
    ]
    out = fake.build()
    (event,) = out["feed"]
    assert event["kind"] == "waiver" and event["faabBid"] == 7
    assert [p["playerId"] for p in event["added"]] == ["D"]
    assert [p["playerId"] for p in event["dropped"]] == ["C"]
    (acq,) = out["acquisitions"]
    assert acq["method"] == "WAIVER" and acq["faabBid"] == 7
    assert [p["playerId"] for p in acq["gaveUp"]] == ["C"]


def test_free_agent_add_has_no_faab_and_a_zero_dollar_waiver_keeps_zero(fake):
    fake.tx[("L1", 4)] = [
        _tx("fa", "free_agent", roster_ids=[1], adds={"D": 1}, leg=4, days_ago=6),
        _tx(
            "w0",
            "waiver",
            roster_ids=[1],
            adds={"Z": 1},
            leg=4,
            days_ago=7,
            settings={"waiver_bid": 0},
        ),
    ]
    by_method = {a["method"]: a for a in fake.build()["acquisitions"]}
    assert by_method["FREE_AGENT"]["faabBid"] is None
    assert by_method["WAIVER"]["faabBid"] == 0
    assert by_method["FREE_AGENT"]["gaveUp"] == []


def test_trade_acquisition_lists_what_was_given_up(fake):
    fake.tx[("L1", 6)] = [
        _tx("t1", roster_ids=[1, 2], adds={"A": 1, "B": 2}, drops={"A": 2, "B": 1})
    ]
    (acq,) = fake.build()["acquisitions"]
    assert acq["method"] == "TRADE"
    assert [p["playerId"] for p in acq["gaveUp"]] == ["B"]


def test_commissioner_move_is_method_other(fake):
    fake.tx[("L1", 4)] = [
        _tx("cm", "commissioner", roster_ids=[1], adds={"D": 1}, leg=4, creator="9009")
    ]
    out = fake.build()
    (acq,) = out["acquisitions"]
    assert acq["method"] == "OTHER"
    assert acq["attribution"]["basis"] == "commissioner"
    assert out["feed"][0]["kind"] == "commissioner"


def test_draft_pick_has_round_slot_and_stays_undated(fake):
    fake.drafts["L1"] = [
        {
            "draft_id": "d1",
            "season": "2026",
            "status": "complete",
            "type": "linear",
            "settings": {"teams": 12},
            "start_time": ms(150),
            "last_picked": ms(149),
        }
    ]
    fake.picks["d1"] = [
        {
            "pick_no": 18,
            "round": 2,
            "roster_id": 1,
            "player_id": "R",
            "picked_by": "1001",
            "draft_slot": 6,
            "metadata": {},
        }
    ]
    out = fake.build()
    (acq,) = out["acquisitions"]
    assert acq["method"] == "DRAFT" and acq["id"] == "draft:d1:18:player:R"
    assert acq["draft"]["round"] == 2 and acq["draft"]["slot"] == 6
    assert acq["draft"]["pickNo"] == 18 and acq["draft"]["kind"] == "linear"
    assert acq["occurredAt"] is None
    assert acq["occurredBound"] == {"notBefore": ms(150), "notAfter": ms(149)}
    assert acq["faabBid"] is None
    assert out["feed"][0]["id"] == "draft:d1:18"
    # The bound says it happened 149+ days ago: outside a 30-day window.
    ma.reset_caches()
    assert fake.build(window="30d")["acquisitions"] == []


def test_still_rostered_and_current_slot(fake):
    fake.tx[("L1", 4)] = [
        _tx("a1", "free_agent", roster_ids=[1], adds={"A": 1}, leg=4, days_ago=9),
        _tx("a2", "free_agent", roster_ids=[1], adds={"R": 1}, leg=4, days_ago=8),
        _tx("a3", "free_agent", roster_ids=[1], adds={"B": 1}, leg=4, days_ago=7),
    ]
    acq = {a["player"]["playerId"]: a for a in fake.build()["acquisitions"]}
    assert acq["A"]["stillRostered"] is True and acq["A"]["currentSlot"] == "starter"
    assert acq["R"]["currentSlot"] == "taxi"
    assert acq["A"]["subsequent"]["state"] == "still_rostered"
    assert acq["B"]["stillRostered"] is False
    assert acq["B"]["subsequent"]["state"] == "unknown"


def test_acquired_then_dropped_is_subsequently_dropped(fake):
    fake.tx[("L1", 2)] = [
        _tx("add", "free_agent", roster_ids=[1], adds={"B": 1}, leg=2, days_ago=20)
    ]
    fake.tx[("L1", 4)] = [
        _tx("drop", "free_agent", roster_ids=[1], drops={"B": 1}, leg=4, days_ago=6)
    ]
    out = fake.build()
    (acq,) = out["acquisitions"]
    assert acq["subsequent"] == {"state": "dropped", "at": ms(6) + 1000}
    assert out["analytics"]["subsequentlyTradedOrDropped"][0]["state"] == "dropped"
    kinds = {f["id"]: f["kind"] for f in out["feed"]}
    assert kinds == {"tx:add": "free_agent", "tx:drop": "drop"}


def test_repeat_target_across_leagues_and_analytics(fake):
    fake.leagues.append(_league("L2", "Beta"))
    fake.rosters["L2"] = [{"roster_id": 5, "owner_id": "1001", "players": ["R"]}]
    fake.users["L2"] = [{"user_id": "1001"}]
    fake.tx[("L1", 4)] = [_tx("x1", "free_agent", roster_ids=[1], adds={"R": 1}, leg=4, days_ago=6)]
    fake.tx[("L2", 5)] = [
        _tx(
            "x2",
            "waiver",
            roster_ids=[5],
            adds={"R": 5},
            leg=5,
            days_ago=3,
            settings={"waiver_bid": 4},
        ),
        _tx("x3", "free_agent", roster_ids=[5], adds={"D": 5}, leg=5, days_ago=2),
    ]
    out = fake.build()
    a = out["analytics"]
    assert a["repeatTargets"] == [
        {"playerId": "R", "name": "Rookie Runner", "timesAcquired": 2, "leagueCount": 2}
    ]
    assert a["byMethod"] == {"FREE_AGENT": 2, "WAIVER": 1}
    assert a["byPosition"] == {"LB": 1, "RB": 2}
    assert a["rookies"]["count"] == 2 and a["idp"]["count"] == 1
    assert a["mostValuable"][0]["name"] == "Rookie Runner"
    summary = {s["playerId"]: s for s in out["playerSummary"]}
    assert summary["R"]["leagues"] == ["L2", "L1"] or set(summary["R"]["leagues"]) == {"L1", "L2"}
    assert summary["R"]["methods"] == {"FREE_AGENT": 1, "WAIVER": 1}


def test_creator_mismatch_is_flagged_and_excluded_from_acquisitions(fake):
    fake.tx[("L1", 2)] = [
        _tx(
            "prev",
            "waiver",
            roster_ids=[1],
            adds={"D": 1},
            leg=2,
            creator="5555",
            settings={"waiver_bid": 3},
        )
    ]
    out = fake.build()
    assert out["acquisitions"] == []
    (event,) = out["feed"]
    assert event["attribution"]["basis"] == "previous_owner_possible"
    assert event["attribution"]["reason"] == "creator_not_owner_or_commissioner"
    assert out["coverage"]["excluded"]["previous_owner_possible"] == 1


def test_unknown_commissioners_fail_closed_for_a_foreign_creator(fake):
    fake.users["L1"] = sc.FETCH_ERROR
    fake.tx[("L1", 2)] = [
        _tx("u", "free_agent", roster_ids=[1], adds={"D": 1}, leg=2, creator="5555")
    ]
    out = fake.build()
    assert out["acquisitions"] == []
    assert out["feed"][0]["attribution"]["reason"] == "league_users_unavailable"


def test_recorded_handoff_decides_attribution_in_our_own_league():
    f = FakeSleeper()
    f.leagues = [_league(HANDOFF_LEAGUE, "Our Dynasty")]
    f.rosters[HANDOFF_LEAGUE] = [
        {"roster_id": 11, "owner_id": HANDOFF_TO, "players": ["A", "D"]},
        {"roster_id": 2, "owner_id": "2002", "players": []},
    ]
    f.users[HANDOFF_LEAGUE] = [{"user_id": HANDOFF_TO}, {"user_id": "2002"}]
    f.tx[(HANDOFF_LEAGUE, 3)] = [
        _tx(
            "before",
            "waiver",
            roster_ids=[11],
            adds={"A": 11},
            leg=3,
            days_ago=30,
            creator=HANDOFF_FROM,
        )
    ]
    f.tx[(HANDOFF_LEAGUE, 7)] = [
        # Created by the PREVIOUS owner's id, but week 7 belongs to the new one:
        # the recorded hand-off decides, not the creator heuristic.
        _tx(
            "after",
            "waiver",
            roster_ids=[11],
            adds={"D": 11},
            leg=7,
            days_ago=1,
            creator=HANDOFF_FROM,
        )
    ]
    user = {"user_id": HANDOFF_TO, "username": "newowner"}
    out = f.build(username="newowner", fetch_user=lambda u: (sc.FETCH_OK, user))
    assert [a["player"]["playerId"] for a in out["acquisitions"]] == ["D"]
    assert out["acquisitions"][0]["attribution"]["basis"] == "recorded_handoff"
    assert [e["id"] for e in out["feed"]] == ["tx:after"]
    assert out["coverage"]["excluded"]["recorded_previous_owner"] == 1


# ── unified feed ────────────────────────────────────────────────────────


def test_feed_dedupes_a_transaction_seen_in_two_weeks_and_orders_newest_first(fake):
    dup = _tx("dup", "free_agent", roster_ids=[1], adds={"D": 1}, leg=4, days_ago=4)
    fake.tx[("L1", 4)] = [dup]
    fake.tx[("L1", 5)] = [dict(dup)]
    fake.tx[("L1", 6)] = [_tx("t1", roster_ids=[1, 2], adds={"A": 1}, drops={"A": 2}, days_ago=1)]
    fake.drafts["L1"] = [
        {
            "draft_id": "d1",
            "season": "2026",
            "status": "complete",
            "type": "linear",
            "settings": {"teams": 12},
            "start_time": ms(150),
            "last_picked": ms(149),
        }
    ]
    fake.picks["d1"] = [
        {"pick_no": 1, "round": 1, "roster_id": 1, "player_id": "R", "picked_by": "1001"}
    ]
    out = fake.build()
    ids = [f["id"] for f in out["feed"]]
    assert ids == ["tx:t1", "tx:dup", "draft:d1:1"]
    assert len(ids) == len(set(ids))
    assert len([a for a in out["acquisitions"] if a["sourceId"] == "tx:dup"]) == 1
    assert out["feed"][0]["partners"] == ["Rival Two"]


def test_activity_payload_memo_keeps_only_ok_answers(fake):
    calls = {"n": 0}
    real = fake.fetch_transactions

    def counting(lid, week):
        calls["n"] += 1
        return real(lid, week)

    kwargs = {
        "fetch_user": fake.fetch_user,
        "fetch_leagues": fake.fetch_leagues,
        "fetch_rosters": fake.fetch_rosters,
        "fetch_users": fake.fetch_users,
        "fetch_transactions": counting,
        "fetch_drafts": fake.fetch_drafts,
        "fetch_draft_picks": fake.fetch_draft_picks,
        "fetch_state": lambda: STATE,
        "fetch_directory": lambda: DIRECTORY,
        "now": lambda: NOW_S,
    }
    first = ma.cached_manager_activity("DynastyFan", contract=CONTRACT, **kwargs)
    second = ma.cached_manager_activity("dynastyfan", contract=CONTRACT, **kwargs)
    assert first["cached"] is False and second["cached"] is True
    fake.tx[("L1", 2)] = sc.FETCH_RATE_LIMITED
    ma._memo.clear()  # the per-week memo would (correctly) still answer week 2
    third = ma.cached_manager_activity("dynastyfan", contract=CONTRACT, window="season", **kwargs)
    assert third["status"] == "partial" and third["cached"] is False
    fourth = ma.cached_manager_activity("dynastyfan", contract=CONTRACT, window="season", **kwargs)
    assert fourth["cached"] is False  # a partial answer was not memoised


def test_league_filter_reads_only_that_league(fake):
    fake.leagues.append(_league("L2", "Beta"))
    fake.rosters["L2"] = [{"roster_id": 5, "owner_id": "1001", "players": []}]
    out = fake.build(league_id="L2")
    assert [c["leagueId"] for c in out["coverage"]["leagues"]] == ["L2"]
    assert out["leagueFilterUnmatched"] is False
    ma.reset_caches()
    assert fake.build(league_id="nope")["leagueFilterUnmatched"] is True
