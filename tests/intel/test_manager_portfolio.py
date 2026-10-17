"""C6-MGR-02 Batch A — Manager Intelligence portfolio aggregation.

Every Sleeper call is an injected fake; no network.  Pins the invariants the
page relies on: one row per player, counts that agree with the league detail,
scopes that never mix, co-owned rosters, the per-position exposure
denominator, unpriced = ``None`` (never 0), and honest partial / not-found /
rate-limited answers.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.intel import manager_portfolio as mp
from src.public_league import sleeper_client as sc

USER = {"user_id": "1001", "username": "dynastyfan", "display_name": "Dynasty Fan"}

SF_IDP = ["QB", "RB", "WR", "TE", "SUPER_FLEX", "DL", "LB", "DB", "BN", "BN"]
ONE_QB = ["QB", "RB", "WR", "TE", "FLEX", "K", "BN", "BN"]


def _league(lid: str, name: str, *, type_: int = 2, positions=SF_IDP) -> dict[str, Any]:
    return {
        "league_id": lid,
        "name": name,
        "season": "2026",
        "status": "in_season",
        "total_rosters": 12,
        "roster_positions": positions,
        "settings": {"type": type_, "taxi_slots": 3},
        "scoring_settings": {"bonus_rec_te": 0.5},
    }


LEAGUES = [
    _league("L1", "Alpha"),
    _league("L2", "Beta", positions=ONE_QB),
    _league("L3", "Gamma"),  # held as co-owner
    _league("R1", "Redraft Fun", type_=0),
    _league("K1", "Keeper Club", type_=1),
]

ROSTERS = {
    "L1": [
        {
            "roster_id": 1,
            "owner_id": "1001",
            "players": ["4046", "9999", "7777"],
            "starters": ["4046"],
            "taxi": ["7777"],
            "settings": {"wins": 4, "losses": 2, "ties": 0, "fpts": 900, "fpts_decimal": 50},
        },
        {"roster_id": 2, "owner_id": "2002", "players": ["5555"]},
    ],
    "L2": [{"roster_id": 4, "owner_id": "1001", "players": ["4046", "8888"], "starters": []}],
    "L3": [
        {"roster_id": 9, "owner_id": "3003", "co_owners": ["1001"], "players": ["4046"]},
    ],
    "R1": [{"roster_id": 1, "owner_id": "1001", "players": ["6666"]}],
    "K1": [{"roster_id": 1, "owner_id": "1001", "players": ["6666"]}],
}

CONTRACT = {
    "playersArray": [
        {
            "playerId": "4046",
            "displayName": "Justin Jefferson",
            "position": "WR",
            "team": "MIN",
            "rankDerivedValue": 9500,
            "canonicalConsensusRank": 2,
            "age": 27,
        },
        {
            "playerId": "9999",
            "displayName": "Some Linebacker",
            "position": "LB",
            "team": "NYJ",
            "rankDerivedValue": 1200,
            "canonicalConsensusRank": 400,
        },
        # 7777 is deliberately absent from the board: unpriced.
    ]
}

DIRECTORY = {
    "7777": {"full_name": "Deep Rookie", "position": "RB", "team": "KC", "years_exp": 0},
    "8888": {"first_name": "Kick", "last_name": "Er", "position": "K", "team": "BUF"},
}


def _fetchers(*, rosters=ROSTERS, leagues=LEAGUES, user=USER, failing: set[str] = frozenset()):
    calls: list[str] = []

    def fetch_user(name):
        calls.append(f"user:{name}")
        if user is None:
            return sc.FETCH_NOT_FOUND, None
        return sc.FETCH_OK, user

    def fetch_leagues(user_id, season):
        calls.append(f"leagues:{user_id}:{season}")
        return sc.FETCH_OK, leagues

    def fetch_rosters(league_id):
        calls.append(f"rosters:{league_id}")
        if league_id in failing:
            return sc.FETCH_ERROR, None
        return sc.FETCH_OK, rosters.get(league_id, [])

    return calls, {
        "fetch_user": fetch_user,
        "fetch_leagues": fetch_leagues,
        "fetch_rosters": fetch_rosters,
        "fetch_state": lambda: {"league_season": "2026"},
        "fetch_directory": lambda: DIRECTORY,
        "now": lambda: 1_800_000_000.0,
        "workers": 1,
    }


def _profile(**kw) -> dict[str, Any]:
    scope = kw.pop("scope", mp.SCOPE_DYNASTY)
    contract = kw.pop("contract", CONTRACT)
    max_leagues = kw.pop("max_leagues", mp.DEFAULT_MAX_LEAGUES)
    _calls, fetchers = _fetchers(**kw)
    return mp.build_manager_profile(
        "dynastyfan", contract=contract, scope=scope, max_leagues=max_leagues, **fetchers
    )


def _player(profile, pid):
    return next(p for p in profile["players"] if p["playerId"] == pid)


def test_one_row_per_player_and_counts_agree_with_league_detail():
    profile = _profile()
    assert profile["status"] == "ok"
    ids = [p["playerId"] for p in profile["players"]]
    assert len(ids) == len(set(ids))
    for p in profile["players"]:
        assert p["leaguesOwned"] == len(p["leagues"]) == p["exposure"]["owned"]
    jj = _player(profile, "4046")
    assert sorted(lg["leagueId"] for lg in jj["leagues"]) == ["L1", "L2", "L3"]
    summary = profile["summary"]
    assert summary["ownedInstances"] == sum(p["leaguesOwned"] for p in profile["players"])
    assert summary["uniquePlayers"] == len(profile["players"])


def test_scopes_never_mix():
    dynasty = _profile()
    assert dynasty["leagueCounts"] == {"dynasty": 3, "keeper": 1, "redraft": 1, "unknown": 0}
    assert {lg["leagueId"] for lg in dynasty["leagues"]} == {"L1", "L2", "L3"}
    assert "6666" not in {p["playerId"] for p in dynasty["players"]}
    redraft = _profile(scope=mp.SCOPE_REDRAFT)
    assert [lg["leagueId"] for lg in redraft["leagues"]] == ["R1"]
    assert [p["playerId"] for p in redraft["players"]] == ["6666"]


def test_co_owned_roster_counts_and_is_labelled():
    profile = _profile()
    gamma = next(lg for lg in profile["leagues"] if lg["leagueId"] == "L3")
    assert gamma["state"] == "ok" and gamma["coOwned"] is True
    alpha = next(lg for lg in profile["leagues"] if lg["leagueId"] == "L1")
    assert alpha["coOwned"] is False
    assert alpha["record"] == {"wins": 4, "losses": 2, "ties": 0, "pointsFor": 900.5}


def test_slots_label_starter_bench_and_taxi_without_double_counting():
    profile = _profile()
    slots = {
        (lg["leagueId"], p["playerId"]): lg["slot"]
        for p in profile["players"]
        for lg in p["leagues"]
    }
    assert slots[("L1", "4046")] == "starter"
    assert slots[("L1", "7777")] == "taxi"
    assert slots[("L1", "9999")] == "bench"
    assert _player(profile, "7777")["leaguesOwned"] == 1


def test_exposure_denominator_is_per_position():
    profile = _profile()
    # L1 and L3 have IDP slots, L2 does not: a linebacker is measured against 2.
    lb = _player(profile, "9999")["exposure"]
    assert (lb["owned"], lb["eligibleLeagues"]) == (1, 2)
    # Offense is eligible everywhere.
    assert _player(profile, "4046")["exposure"]["eligibleLeagues"] == 3
    # Only L2 has a K slot.
    k = _player(profile, "8888")["exposure"]
    assert (k["owned"], k["eligibleLeagues"], k["share"]) == (1, 1, 1.0)


def test_unpriced_players_are_none_never_zero():
    profile = _profile()
    rookie = _player(profile, "7777")
    assert rookie["value"] is None and rookie["overallRank"] is None
    assert rookie["name"] == "Deep Rookie" and rookie["isRookie"] is True
    assert _player(profile, "8888")["name"] == "Kick Er"
    assert profile["summary"]["unpricedPlayers"] == 2
    no_board = _profile(contract=None)
    assert all(p["value"] is None for p in no_board["players"])


def test_value_totals_only_over_superflex_leagues():
    by_format = _profile()["summary"]["byFormat"]
    sf = by_format["superflex"]
    # L1: 9500 + 1200 (7777 unpriced); L3: 9500.
    assert sf["leagues"] == 2 and sf["instances"] == 4 and sf["pricedInstances"] == 3
    assert sf["boardValue"] == 9500 + 1200 + 9500
    one_qb = by_format["1qb"]
    assert one_qb["boardValue"] is None
    assert one_qb["valueNote"] == "canonical_board_is_superflex"


def test_unreadable_league_makes_the_answer_partial_not_silent():
    profile = _profile(failing={"L2"})
    assert profile["status"] == "partial"
    assert profile["leaguesUnreadable"] == 1
    beta = next(lg for lg in profile["leagues"] if lg["leagueId"] == "L2")
    assert beta["state"] == "unavailable"
    assert all(lg["leagueId"] != "L2" for p in profile["players"] for lg in p["leagues"])


def test_league_without_a_roster_for_the_user_is_reported():
    rosters = {**ROSTERS, "L3": [{"roster_id": 9, "owner_id": "3003", "players": []}]}
    profile = _profile(rosters=rosters)
    gamma = next(lg for lg in profile["leagues"] if lg["leagueId"] == "L3")
    assert gamma["state"] == "no_roster"
    assert profile["status"] == "ok"


def test_truncation_is_explicit():
    profile = _profile(max_leagues=2)
    assert profile["truncated"] is True
    assert profile["leaguesInScope"] == 2
    assert [lg["name"] for lg in profile["leagues"]] == ["Alpha", "Beta"]


def test_unknown_user_is_not_found():
    assert _profile(user=None)["status"] == "not_found"


@pytest.mark.parametrize(
    ("kind", "expected"),
    [(sc.FETCH_RATE_LIMITED, "rate_limited"), (sc.FETCH_ERROR, "upstream_unavailable")],
)
def test_league_list_failures_are_classified(kind, expected):
    _calls, fetchers = _fetchers()
    fetchers["fetch_leagues"] = lambda user_id, season: (kind, None)
    profile = mp.build_manager_profile("dynastyfan", contract=CONTRACT, **fetchers)
    assert profile["status"] == expected
    assert profile["manager"]["userId"] == "1001"
    assert "players" not in profile


def test_memo_caches_only_ok_answers():
    mp.reset_cache()
    try:
        calls, fetchers = _fetchers(failing={"L2"})
        first = mp.cached_manager_profile("DynastyFan", contract=CONTRACT, **fetchers)
        second = mp.cached_manager_profile("dynastyfan", contract=CONTRACT, **fetchers)
        assert first["status"] == second["status"] == "partial"
        assert calls.count("user:dynastyfan") == 1 and calls.count("user:DynastyFan") == 1

        calls, fetchers = _fetchers()
        mp.cached_manager_profile("dynastyfan", contract=CONTRACT, **fetchers)
        cached = mp.cached_manager_profile("DYNASTYFAN", contract=CONTRACT, **fetchers)
        assert cached["cached"] is True
        assert calls.count("user:dynastyfan") == 1
    finally:
        mp.reset_cache()


# ── Sleeper client fetchers (request layer stubbed) ──────────────────────


def _stub_request(monkeypatch, answers: dict[str, tuple[str, Any]]):
    seen: list[str] = []

    def fake(url, timeout=None):
        seen.append(url)
        return answers.get(url, (sc.FETCH_ERROR, None))

    monkeypatch.setattr(sc, "request_json_classified", fake)
    return seen


def test_fetch_user_quotes_the_handle_and_treats_null_as_not_found(monkeypatch):
    base = sc.SLEEPER_BASE
    seen = _stub_request(
        monkeypatch,
        {
            f"{base}/user/dynastyfan": (sc.FETCH_OK, {"user_id": "1001"}),
            f"{base}/user/ghost": (sc.FETCH_OK, None),
        },
    )
    assert sc.fetch_user_classified(" dynastyfan ") == (sc.FETCH_OK, {"user_id": "1001"})
    assert sc.fetch_user_classified("ghost") == (sc.FETCH_NOT_FOUND, None)
    assert sc.fetch_user_classified("") == (sc.FETCH_NOT_FOUND, None)
    sc.fetch_user_classified("a/b?c")
    assert seen[-1] == f"{base}/user/a%2Fb%3Fc"


def test_fetch_user_leagues_distinguishes_none_from_failure(monkeypatch):
    base = sc.SLEEPER_BASE
    _stub_request(
        monkeypatch,
        {
            f"{base}/user/1/leagues/nfl/2026": (sc.FETCH_NOT_FOUND, None),
            f"{base}/user/2/leagues/nfl/2026": (sc.FETCH_OK, {"not": "a list"}),
            f"{base}/user/3/leagues/nfl/2026": (sc.FETCH_RATE_LIMITED, None),
        },
    )
    assert sc.fetch_user_leagues_classified("1", 2026) == (sc.FETCH_OK, [])
    assert sc.fetch_user_leagues_classified("2", "2026") == (sc.FETCH_ERROR, None)
    assert sc.fetch_user_leagues_classified("3", "2026") == (sc.FETCH_RATE_LIMITED, None)
    rosters_url = f"{base}/league/L9/rosters"
    _stub_request(monkeypatch, {rosters_url: (sc.FETCH_OK, "garbage")})
    assert sc.fetch_rosters_classified("L9") == (sc.FETCH_ERROR, None)
