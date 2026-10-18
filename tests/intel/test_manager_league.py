"""Manager Intelligence Batch C — league-wide opponent scouting, deterministic.

Every Sleeper call is an injected fake; no network.  Pins the workstream's
Batch C tests (``docs/intel/MANAGER_INTELLIGENCE_WORKSTREAM.md``): the league
fan-out stays inside its call budget (one league / rosters / users / drafts /
traded_picks fetch, legs through the shared memo), partial and rate-limited
coverage states, former members never leak, a registry league attaches the
existing Manager Scout profile instead of re-deriving tendencies, and an
unpriced player is never a zero.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from src.intel import manager_activity as ma
from src.intel import manager_league as ml
from src.public_league import sleeper_client as sc

NOW_S = 1_792_000_000
DAY = 86_400
STATE = {"season": "2026", "league_season": "2026", "season_type": "regular", "leg": 7}

LEAGUE_ID = "555000111"
# Our own registry league with a recorded hand-off (config/leagues/
# roster_ownership_changes.json): roster 11 passes from HANDOFF_FROM to
# HANDOFF_TO at week 6.
HANDOFF_LEAGUE = "1312006700437352448"
HANDOFF_FROM = "712035316776669184"
HANDOFF_TO = "735693375101108224"

SF = ["QB", "RB", "WR", "TE", "SUPER_FLEX", "DL", "LB", "BN", "BN"]
ONE_QB = ["QB", "RB", "WR", "TE", "FLEX", "BN", "BN"]

CONTRACT = {
    "playersArray": [
        {"playerId": "A", "displayName": "Alpha Back", "position": "RB", "team": "KC",
         "rankDerivedValue": 5000, "canonicalConsensusRank": 20},
        {"playerId": "B", "displayName": "Bravo Receiver", "position": "WR", "team": "BUF",
         "rankDerivedValue": 4000, "canonicalConsensusRank": 30},
        {"playerId": "C", "displayName": "Charlie End", "position": "TE", "team": "DET",
         "rankDerivedValue": 3000, "canonicalConsensusRank": 45},
        {"playerId": "Q", "displayName": "Quinn Passer", "position": "QB", "team": "CIN",
         "rankDerivedValue": 6000, "canonicalConsensusRank": 10},
        {"playerId": "D", "displayName": "Delta Backer", "position": "LB", "team": "SF",
         "rankDerivedValue": 1500, "canonicalConsensusRank": 300},
        {"assetClass": "pick", "canonicalName": "2027 Round 1", "rankDerivedValue": 3500},
        {"assetClass": "pick", "canonicalName": "2027 Round 2", "rankDerivedValue": 1200},
    ]
}  # fmt: skip
DIRECTORY = {
    "Z": {"full_name": "Zed Unranked", "position": "WR", "team": "MIA", "years_exp": 3},
    "Y": {"full_name": "Yan Unranked", "position": "RB", "team": "NYG", "years_exp": 1},
}


def ms(days_ago: float) -> int:
    return int((NOW_S - days_ago * DAY) * 1000)


def _league(lid: str = LEAGUE_ID, *, positions=SF, season: str = "2026") -> dict[str, Any]:
    return {
        "league_id": lid,
        "name": "Championship Test",
        "season": season,
        "status": "in_season",
        "total_rosters": 3,
        "roster_positions": positions,
        "settings": {"type": 2, "taxi_slots": 3, "draft_rounds": 2},
        "scoring_settings": {"bonus_rec_te": 0.5},
    }


def _tx(tid: str, ttype: str = "trade", **kw: Any) -> dict[str, Any]:
    base = {
        "transaction_id": tid,
        "type": ttype,
        "status": "complete",
        "creator": kw.pop("creator", "u1"),
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


class Fake:
    def __init__(self, league: dict[str, Any] | str | None = None) -> None:
        self.league = league if league is not None else _league()
        self.rosters: Any = [
            {"roster_id": 1, "owner_id": "u1", "players": ["A", "Q", "Z"], "starters": ["A", "Q"],
             "taxi": ["Z"], "settings": {"wins": 4, "losses": 2}},
            {"roster_id": 2, "owner_id": "u2", "co_owners": ["u2b"], "players": ["B", "C", "D"],
             "starters": ["B", "C"], "reserve": ["D"]},
            {"roster_id": 3, "owner_id": None, "players": ["Y"], "starters": []},
        ]  # fmt: skip
        self.users: Any = [
            {"user_id": "u1", "display_name": "Ann", "is_owner": True,
             "metadata": {"team_name": "Ann's Team"}},
            {"user_id": "u2", "display_name": "Bob"},
            {"user_id": "u2b", "display_name": "Bob Co"},
        ]  # fmt: skip
        self.drafts: Any = []
        self.draft_picks: dict[str, Any] = {}
        self.tx: dict[int, Any] = {}
        self.traded: Any = []
        self.calls: list[tuple[str, Any]] = []

    @staticmethod
    def _answer(value: Any, default: Any) -> tuple[str, Any]:
        if isinstance(value, str):
            return value, None
        return sc.FETCH_OK, value if value is not None else default

    def fetch_league(self, lid):
        self.calls.append(("league", lid))
        return self._answer(self.league, None)

    def fetch_rosters(self, lid):
        self.calls.append(("rosters", lid))
        return self._answer(self.rosters, [])

    def fetch_users(self, lid):
        self.calls.append(("users", lid))
        return self._answer(self.users, [])

    def fetch_drafts(self, lid):
        self.calls.append(("drafts", lid))
        return self._answer(self.drafts, [])

    def fetch_draft_picks(self, did):
        self.calls.append(("picks", did))
        return self._answer(self.draft_picks.get(did), [])

    def fetch_transactions(self, lid, week):
        self.calls.append(("tx", week))
        return self._answer(self.tx.get(week), [])

    def fetch_traded_picks(self, lid):
        self.calls.append(("traded_picks", lid))
        return self._answer(self.traded, [])

    def build(self, league_id: str = LEAGUE_ID, **kwargs: Any) -> dict[str, Any]:
        params: dict[str, Any] = {
            "contract": CONTRACT,
            "window": "season",
            "fetch_league": self.fetch_league,
            "fetch_rosters": self.fetch_rosters,
            "fetch_users": self.fetch_users,
            "fetch_transactions": self.fetch_transactions,
            "fetch_drafts": self.fetch_drafts,
            "fetch_draft_picks": self.fetch_draft_picks,
            "fetch_traded_picks": self.fetch_traded_picks,
            "fetch_state": lambda: STATE,
            "fetch_directory": lambda: DIRECTORY,
            "registry_config": lambda lid: None,
            "now": lambda: NOW_S,
        }
        params.update(kwargs)
        return ml.build_league_scouting(league_id, **params)

    def kinds(self) -> list[str]:
        return [c[0] for c in self.calls]


@pytest.fixture(autouse=True)
def _reset():
    ma.reset_caches()
    ml.reset_cache()
    yield


def _row(out: dict[str, Any], rid: int) -> dict[str, Any]:
    return next(r for r in out["managers"] if r["rosterId"] == rid)


# ── fan-out, budget, memo ───────────────────────────────────────────────


def test_one_league_fan_out_stays_inside_the_budget():
    f = Fake()
    f.drafts = [{"draft_id": "d1", "season": "2026", "status": "complete", "type": "snake",
                 "settings": {"teams": 3}}]  # fmt: skip
    out = f.build()
    assert out["status"] == "ok"
    kinds = f.kinds()
    # One league, rosters, users, drafts and traded_picks fetch — never per roster.
    for k in ("league", "rosters", "users", "drafts", "traded_picks"):
        assert kinds.count(k) == 1, k
    assert kinds.count("tx") == 8  # legs 0..7 (current leg 7)
    assert kinds.count("picks") == 1
    cov = out["coverage"]
    assert cov["callsSpent"] == len(f.calls) <= cov["callBudget"] == ml.LEAGUE_CALL_BUDGET
    assert cov["budgetExhausted"] is False
    assert cov["transactions"] == "complete" and cov["tradedPicks"] == "complete"
    assert out["managerCount"] == 3


def test_completed_weeks_come_from_the_shared_memo_on_a_second_read():
    f = Fake()
    f.build()
    f.calls.clear()
    out = f.build()
    # Completed legs (0..6) are memoised for hours; the current leg (7) and the
    # league / traded picks for minutes — so only rosters + users are re-read.
    assert f.kinds().count("tx") == 0
    assert out["coverage"]["callsSpent"] == 2


def test_budget_exhaustion_is_partial_and_flagged():
    f = Fake()
    out = f.build(call_budget=8)
    assert out["status"] == "partial"
    cov = out["coverage"]
    assert cov["budgetExhausted"] is True
    assert cov["transactions"] == "partial"
    assert cov["weeksFailed"] > 0


def test_rate_limited_week_makes_the_league_partial():
    f = Fake()
    f.tx[3] = sc.FETCH_RATE_LIMITED
    out = f.build()
    assert out["status"] == "partial"
    assert out["coverage"]["transactions"] == "partial"
    assert out["coverage"]["weeksFailed"] == 1


def test_league_level_failures_map_to_statuses():
    assert Fake(league=sc.FETCH_NOT_FOUND).build()["status"] == "not_found"
    assert Fake(league=sc.FETCH_RATE_LIMITED).build()["status"] == "rate_limited"
    assert Fake(league=sc.FETCH_ERROR).build()["status"] == "upstream_unavailable"
    f = Fake()
    f.rosters = sc.FETCH_RATE_LIMITED
    out = f.build()
    assert out["status"] == "rate_limited" and "managers" not in out
    f = Fake()
    f.rosters = sc.FETCH_ERROR
    assert f.build()["status"] == "upstream_unavailable"


def test_unread_users_is_partial_and_names_stay_missing():
    f = Fake()
    f.users = sc.FETCH_ERROR
    out = f.build()
    assert out["status"] == "partial"
    assert out["coverage"]["leagueUsers"] == "unavailable"
    assert all(r["displayName"] is None for r in out["managers"])


# ── roster summary, values, ranks ───────────────────────────────────────


def test_roster_summary_slots_values_and_unpriced_never_zero():
    out = Fake().build()
    ann = _row(out, 1)
    roster = ann["roster"]
    assert (roster["starters"], roster["bench"], roster["taxi"], roster["reserve"]) == (2, 0, 1, 0)
    assert roster["pricedValue"] == 11000  # A + Q; Z unpriced is not added
    assert roster["unpricedCount"] == 1 and roster["unpricedReasons"] == {"not_on_board": 1}
    z = next(p for p in roster["players"] if p["playerId"] == "Z")
    assert z["value"] is None and z["valueReason"] == "not_on_board"
    assert roster["players"][-1]["playerId"] == "Z"  # unpriced sorts last
    assert roster["byPosition"]["WR"] == {
        "count": 1, "pricedCount": 0, "unpricedCount": 1, "pricedValue": None, "rank": None,
    }  # fmt: skip
    bob = _row(out, 2)
    assert bob["roster"]["reserve"] == 1
    # Orphan roster holding only an unpriced player: no total, no rank.
    orphan = _row(out, 3)
    assert orphan["orphan"] is True and orphan["ownerUserId"] is None
    assert orphan["roster"]["pricedValue"] is None and orphan["valueRank"] is None
    # Ranks: Ann 11000, Bob 8500 (B + C + D).
    assert ann["valueRank"] == 1 and bob["valueRank"] == 2
    assert out["ranking"]["rankedRosters"] == 2
    assert ann["roster"]["byPosition"]["QB"]["rank"] == 1
    # Bob holds no QB: observed 0, ranked behind Ann (the orphan holds no
    # roster value at all and is unranked, never last-as-zero).
    assert "QB" not in bob["roster"]["byPosition"]
    assert [r["rosterId"] for r in out["managers"]] == [1, 2, 3]
    assert out["managers"][0]["teamName"] == "Ann's Team"
    assert bob["coOwnerCount"] == 1


def test_ties_share_a_rank():
    assert ml._competition_ranks({1: 10, 2: 10, 3: 5, 4: None}) == {1: 1, 2: 1, 3: 3, 4: None}


def test_non_superflex_league_withholds_totals_and_ranks():
    out = Fake(league=_league(positions=ONE_QB)).build()
    ann = _row(out, 1)
    assert ann["roster"]["pricedValue"] is None
    assert ann["roster"]["valueNote"] == "canonical_board_is_superflex"
    assert ann["valueRank"] is None
    assert all(g["pricedValue"] is None for g in ann["roster"]["byPosition"].values())
    # Per-player canonical values are still shown.
    assert next(p for p in ann["roster"]["players"] if p["playerId"] == "A")["value"] == 5000
    assert out["ranking"]["withheld"] == "canonical_board_is_superflex"


def test_no_board_withholds_every_value():
    out = Fake().build(contract=None)
    ann = _row(out, 1)
    assert out["hasBoard"] is False and ann["valueRank"] is None
    assert all(p["value"] is None for p in ann["roster"]["players"])
    assert ann["roster"]["valueNote"] == "board_unavailable"


# ── activity counts and tendencies ──────────────────────────────────────


def test_activity_counts_and_trade_stream_tendencies_per_roster():
    f = Fake()
    f.tx[6] = [
        _tx("t1", roster_ids=[1, 2], adds={"B": 1, "A": 2}, drops={"A": 1, "B": 2}),
        _tx("w1", "waiver", creator="u2", roster_ids=[2], adds={"Z": 2}, drops={"D": 2},
            settings={"waiver_bid": 7}),
        _tx("f1", "free_agent", creator="u1", roster_ids=[1], adds={"Y": 1}),
        _tx("p1", "trade", status="pending", roster_ids=[1, 2], adds={"C": 1}, drops={"C": 2}),
    ]  # fmt: skip
    out = f.build()
    ann, bob = _row(out, 1)["activity"], _row(out, 2)["activity"]
    assert ann["trades"] == 1 and ann["freeAgentAdds"] == 1 and ann["waiverClaims"] == 0
    assert bob["trades"] == 1 and bob["waiverClaims"] == 1 and bob["playersDropped"] == 1
    assert bob["faabSpent"] == 7 and bob["faabClaims"] == 1
    assert ann["playersAddedByMethod"] == {"FREE_AGENT": 1, "TRADE": 1}
    assert ann["lastActivityAt"] is not None
    tend = _row(out, 1)["tendencies"]
    assert _row(out, 1)["tendenciesSource"] == "trade_stream"
    assert tend["tradeCount"] == 1
    assert tend["pickPlayer"]["sufficientSample"] is False  # n=1 < PRIOR minimum
    assert _row(out, 3)["activity"]["events"] == 0


def test_window_filters_counts():
    f = Fake()
    f.tx[2] = [_tx("old", "free_agent", creator="u1", roster_ids=[1], adds={"Y": 1},
                   days_ago=60, leg=2)]  # fmt: skip
    assert _row(f.build(window="30d"), 1)["activity"]["freeAgentAdds"] == 0
    ma.reset_caches()
    assert _row(f.build(window="90d"), 1)["activity"]["freeAgentAdds"] == 1


def test_creator_mismatch_is_counted_apart_not_credited():
    f = Fake()
    f.tx[6] = [_tx("x1", "free_agent", creator="stranger", roster_ids=[2], adds={"Y": 2})]
    bob = _row(f.build(), 2)
    assert bob["activity"]["freeAgentAdds"] == 0
    assert bob["activity"]["uncertainAttribution"] == 1
    assert bob["activity"]["playersAdded"] == 0


# ── draft capital ───────────────────────────────────────────────────────


def test_draft_capital_per_roster_from_one_traded_picks_read():
    f = Fake()
    f.traded = [{"season": "2027", "round": 1, "roster_id": 2, "owner_id": 1,
                 "previous_owner_id": 2}]  # fmt: skip
    out = f.build()
    ann, bob = _row(out, 1)["draftCapital"], _row(out, 2)["draftCapital"]
    assert f.kinds().count("traded_picks") == 1
    ann_2027 = [p for p in ann["picks"] if p["season"] == 2027 and p["round"] == 1]
    assert {p["originRosterId"] for p in ann_2027} == {1, 2}
    assert all(p["value"] == 3500 for p in ann_2027)
    assert bob["counts"]["ownTradedAway"] == 1
    assert ann["managerRosterIds"] == [1]


def test_traded_picks_failure_is_unavailable_never_no_picks():
    f = Fake()
    f.traded = sc.FETCH_RATE_LIMITED
    out = f.build()
    assert out["status"] == "partial"
    cap = _row(out, 1)["draftCapital"]
    assert cap["picks"] is None and cap["pickOwnershipState"] == "unavailable"
    assert out["draftCapital"]["coverage"] == "rate_limited"


def test_earlier_season_league_reads_every_leg_and_no_traded_picks():
    f = Fake(league=_league(season="2025"))
    out = f.build(window="30d")
    assert out["windowApplied"] == "season"
    assert "traded_picks" not in f.kinds()
    assert f.kinds().count("tx") == ma.MAX_LEG + 1
    assert _row(out, 1)["draftCapital"]["reason"] == "earlier_season"
    assert out["draftCapital"]["available"] is False


# ── registry league: Manager Scout, former-member privacy ───────────────


def _registry_fake() -> Fake:
    f = Fake(league=_league(HANDOFF_LEAGUE))
    f.rosters = [
        {"roster_id": 11, "owner_id": HANDOFF_TO, "players": ["A", "Q"]},
        {"roster_id": 2, "owner_id": "u2", "players": ["B", "C"]},
    ]
    f.users = [
        {"user_id": HANDOFF_TO, "display_name": "New Owner"},
        {"user_id": "u2", "display_name": "Bob"},
    ]
    f.tx[3] = [
        # Week 3 belongs to the FORMER owner of roster 11 (recorded hand-off).
        _tx("pre", roster_ids=[11, 2], adds={"B": 11, "A": 2}, drops={"A": 11, "B": 2},
            creator=HANDOFF_FROM, leg=3),
        _tx("pre_fa", "free_agent", roster_ids=[11], adds={"Z": 11}, creator=HANDOFF_FROM, leg=3),
    ]  # fmt: skip
    f.tx[7] = [
        _tx("post", "free_agent", roster_ids=[11], adds={"Y": 11}, creator=HANDOFF_TO, leg=7),
    ]
    return f


SCOUT_PAYLOAD = {
    "leagueKey": "dynasty_main",
    "methodVersion": "manager_scout_v1",
    "generatedAt": "2026-10-17T00:00:00+00:00",
    "sources": {"trades": {"state": "available"}, "lineup": {"state": "not_measured"}},
    "managers": [
        {"managerKey": "k-new", "ownerId": HANDOFF_TO, "currentMember": True,
         "displayName": "New Owner",
         "tradeTendencies": {"state": "measured", "sampleSize": 4,
                             "partners": [{"managerKey": "k-old", "ownerId": None,
                                           "displayName": None, "trades": 2}]},
         "waiverTendencies": {"state": "insufficient_sample", "sampleSize": 0},
         "faabTendencies": {"state": "unavailable"}},
        {"managerKey": "k-old", "ownerId": None, "currentMember": False, "displayName": None,
         "tradeTendencies": {"state": "measured", "sampleSize": 9}},
    ],
}  # fmt: skip


def test_registry_league_attaches_manager_scout_and_never_rederives():
    f = _registry_fake()
    seen: list[Any] = []

    def provider(cfg, teams, contract):
        seen.append((cfg.key, teams))
        return SCOUT_PAYLOAD

    cfg = SimpleNamespace(key="dynasty_main")
    out = f.build(HANDOFF_LEAGUE, registry_config=lambda lid: cfg, scout_provider=provider)
    assert len(seen) == 1 and seen[0][0] == "dynasty_main"
    assert {t["ownerId"] for t in seen[0][1]} == {HANDOFF_TO, "u2"}
    new = _row(out, 11)
    assert new["tendencies"] is None and new["tendenciesSource"] == "manager_scout"
    assert new["scout"]["managerKey"] == "k-new"
    assert new["scout"]["tradeTendencies"]["sampleSize"] == 4
    assert _row(out, 2)["scout"] is None  # no profile for this member
    assert out["scout"]["formerMembersWithHistory"] == 1
    assert out["league"]["registryLeague"] is True
    assert out["league"]["registryKey"] == "dynasty_main"


def test_former_member_is_never_published_and_pre_handoff_moves_are_not_credited():
    f = _registry_fake()
    cfg = SimpleNamespace(key="dynasty_main")
    out = f.build(
        HANDOFF_LEAGUE, registry_config=lambda lid: cfg, scout_provider=lambda *a: SCOUT_PAYLOAD
    )
    blob = json.dumps(out)
    assert HANDOFF_FROM not in blob
    new = _row(out, 11)
    # Only the week-7 free-agent add is the current owner's.
    assert new["activity"]["freeAgentAdds"] == 1 and new["activity"]["trades"] == 0
    assert new["excluded"].get("recorded_previous_owner") == 2


def test_external_league_former_creator_id_is_not_published():
    f = Fake()
    f.tx[6] = [_tx("t9", roster_ids=[1, 2], adds={"B": 1, "A": 2}, drops={"A": 1, "B": 2},
                   creator="ghost-former-999")]  # fmt: skip
    out = f.build()
    assert "ghost-former-999" not in json.dumps(out)


def test_scout_failure_is_an_unavailable_state():
    f = _registry_fake()
    cfg = SimpleNamespace(key="dynasty_main")

    def boom(*a):
        raise RuntimeError("store exploded")

    out = f.build(HANDOFF_LEAGUE, registry_config=lambda lid: cfg, scout_provider=boom)
    assert out["scout"]["state"] == "unavailable"
    assert all(r["scout"] is None for r in out["managers"])


def test_default_scout_provider_calls_the_owner_and_gates_the_board(monkeypatch):
    from src.intel import manager_scout

    captured: dict[str, Any] = {}

    def fake_cached(key, **kwargs):
        captured.update({"key": key, **kwargs})
        return SCOUT_PAYLOAD

    monkeypatch.setattr(manager_scout, "cached_manager_scout", fake_cached)
    cfg = SimpleNamespace(key="dynasty_main")
    teams = [{"ownerId": "u2", "name": "Bob", "roster_id": 2}]
    foreign = {"meta": {"leagueKey": "dynasty_new"}, "sleeper": {"teams": [{"ownerId": "x"}]}}
    ml._default_scout_provider(cfg, teams, foreign)
    assert captured["key"] == "dynasty_main" and captured["league_cfg"] is cfg
    assert captured["current_teams"] == teams
    assert captured["contract"] is None  # another league's board is never borrowed
    own = {"meta": {"leagueKey": "dynasty_main"}, "sleeper": {"teams": [{"ownerId": "u2"}]}}
    ml._default_scout_provider(cfg, teams, own)
    assert captured["contract"] is own


def test_registry_lookup_uses_the_league_registry(monkeypatch):
    from src.api import league_registry

    cfg = SimpleNamespace(key="dynasty_main", sleeper_league_id=HANDOFF_LEAGUE)
    monkeypatch.setattr(
        league_registry,
        "league_key_for_sleeper_id",
        lambda sid: "dynasty_main" if sid == HANDOFF_LEAGUE else None,
    )
    monkeypatch.setattr(
        league_registry, "get_league_by_key", lambda key: cfg if key == "dynasty_main" else None
    )
    assert ml._registry_config(HANDOFF_LEAGUE) is cfg
    # An unknown id is external (None), never guessed.
    assert ml._registry_config("999999999999") is None

    def broken(sid):
        raise RuntimeError("registry unreadable")

    monkeypatch.setattr(league_registry, "league_key_for_sleeper_id", broken)
    assert ml._registry_config(HANDOFF_LEAGUE) is None


# ── payload memo ────────────────────────────────────────────────────────


def test_only_ok_payloads_are_memoised():
    f = Fake()
    kwargs = {k: v for k, v in {
        "fetch_league": f.fetch_league, "fetch_rosters": f.fetch_rosters,
        "fetch_users": f.fetch_users, "fetch_transactions": f.fetch_transactions,
        "fetch_drafts": f.fetch_drafts, "fetch_draft_picks": f.fetch_draft_picks,
        "fetch_traded_picks": f.fetch_traded_picks, "fetch_state": lambda: STATE,
        "fetch_directory": lambda: DIRECTORY, "registry_config": lambda lid: None,
        "now": lambda: NOW_S}.items()}  # fmt: skip
    first = ml.cached_league_scouting(LEAGUE_ID, contract=CONTRACT, window="season", **kwargs)
    assert first["cached"] is False
    second = ml.cached_league_scouting(LEAGUE_ID, contract=CONTRACT, window="season", **kwargs)
    assert second["cached"] is True
    ml.reset_cache()
    f.traded = sc.FETCH_ERROR
    ma.reset_caches()
    p1 = ml.cached_league_scouting(LEAGUE_ID, contract=CONTRACT, window="season", **kwargs)
    p2 = ml.cached_league_scouting(LEAGUE_ID, contract=CONTRACT, window="season", **kwargs)
    assert p1["status"] == "partial" and p2["cached"] is False
