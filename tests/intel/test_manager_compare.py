"""Manager Intelligence Batch E — comparisons (fixture-based, no network)."""

from __future__ import annotations

import copy
from typing import Any

from src.intel import manager_compare as mcmp
from src.public_league import sleeper_client

OK = sleeper_client.FETCH_OK


def _profile(uid: str, leagues: list[str]) -> dict[str, Any]:
    return {
        "status": "ok",
        "manager": {"userId": uid, "username": f"user{uid}", "displayName": f"User {uid}"},
        "season": "2026",
        "leaguesInScope": len(leagues),
        "leagues": [{"leagueId": lid} for lid in leagues],
        "summary": {"uniquePlayers": 40 + len(uid), "ageMean": 25.5, "ageKnownPlayers": 40},
    }


def _activity(uid: str) -> dict[str, Any]:
    return {
        "status": "ok",
        "tendencies": {"tradeCount": len(uid), "pieces": {"counts": {}}},
        "analytics": {"byMethod": {"WAIVER": 2}, "acquisitionCount": 2},
        "draftCapital": {"available": True, "totals": {"picksHeld": 9, "pricedValue": None}},
        "acquisitions": [],
        "coverage": {"leagues": []},
    }


def _career(uid: str, profile, activity) -> dict[str, Any]:
    return {
        "status": "ok",
        "totals": {"seasons": 3, "uid": uid},
        "archetypes": {"suggested": [], "items": [], "from": (profile, activity)},
    }


class Providers:
    def __init__(self, failing: dict[str, str] | None = None) -> None:
        self.failing = failing or {}
        self.profiles = {"alpha": _profile("1", ["L1", "L2"]), "beta": _profile("22", ["L2", "L3"])}
        self.activities = {"alpha": _activity("1"), "beta": _activity("22")}
        self.career_calls: list[dict[str, Any]] = []

    def profile(self, username, **kw):
        if username in self.failing:
            return {"status": self.failing[username], "query": username}
        return copy.deepcopy(self.profiles[username])

    def activity(self, username, **kw):
        assert kw["window"] == "season"
        return copy.deepcopy(self.activities[username])

    def career(self, username, **kw):
        self.career_calls.append({"username": username, **kw})
        uid = kw["profile_payload"]["manager"]["userId"]
        return _career(uid, kw["profile_payload"], kw["activity_payload"])

    def kwargs(self):
        return {
            "profile_provider": self.profile,
            "activity_provider": self.activity,
            "career_provider": self.career,
        }


def test_compare_serves_the_identical_single_manager_blocks():
    p = Providers()
    out = mcmp.build_manager_comparison("alpha", "beta", contract=None, **p.kwargs())
    assert out["status"] == "ok"
    for name, user in (("a", "alpha"), ("b", "beta")):
        side = out[name]
        assert side["portfolio"] == p.profiles[user]["summary"]
        assert side["tendencies"] == p.activities[user]["tendencies"]
        assert side["analytics"] == p.activities[user]["analytics"]
        assert side["draftCapital"] == p.activities[user]["draftCapital"]["totals"]
        assert side["manager"] == p.profiles[user]["manager"]
    assert out["a"]["career"] == {"seasons": 3, "uid": "1"}
    # The archetypes were evaluated over the very payloads shown beside them.
    call = next(c for c in p.career_calls if c["username"] == "alpha")
    assert call["profile_payload"] == p.profiles["alpha"]
    assert call["activity_payload"] == p.activities["alpha"]
    assert out["sharedLeagueIds"] == ["L2"]
    assert out["sameManager"] is False


def test_compare_same_manager_flag():
    p = Providers()
    out = mcmp.build_manager_comparison("alpha", "alpha", contract=None, **p.kwargs())
    assert out["sameManager"] is True


def test_compare_failed_side_is_named():
    p = Providers(failing={"beta": "not_found"})
    out = mcmp.build_manager_comparison("alpha", "beta", contract=None, **p.kwargs())
    assert out["status"] == "not_found" and out["failedSide"] == "b"


def test_compare_partial_source_is_partial_and_withholds_its_blocks():
    p = Providers()
    p.activities["beta"] = {"status": "rate_limited"}
    out = mcmp.build_manager_comparison("alpha", "beta", contract=None, **p.kwargs())
    assert out["status"] == "partial"
    assert out["b"]["tendencies"] is None and out["b"]["draftCapital"] is None
    assert out["b"]["sources"]["activity"] == "rate_limited"


def test_earlier_season_draft_capital_reason():
    p = Providers()
    p.activities["alpha"]["draftCapital"] = {"available": False, "reason": "earlier_season"}
    out = mcmp.build_manager_comparison("alpha", "beta", contract=None, **p.kwargs())
    assert out["a"]["draftCapital"] is None
    assert out["a"]["draftCapitalReason"] == "earlier_season"


# ── league percentile ───────────────────────────────────────────────────


def _row(rid: int, owner: str | None, value, events: int, picks: int | None) -> dict[str, Any]:
    return {
        "rosterId": rid,
        "ownerUserId": owner,
        "displayName": f"T{rid}",
        "record": {"wins": 1},
        "valueRank": None,
        "roster": {"pricedValue": value, "valueNote": None if value is not None else "x"},
        "draftCapital": {
            "pricedValue": None if picks is None else picks * 100,
            "counts": None if picks is None else {"held": picks},
        },
        "activity": {"trades": events // 2, "events": events, "playersAdded": events},
    }


def _scouting(rows) -> dict[str, Any]:
    return {
        "status": "ok",
        "league": {"leagueId": "9", "name": "Nine"},
        "season": "2026",
        "window": "season",
        "windowApplied": "season",
        "managers": rows,
        "coverage": {},
    }


def _fetch_user(name):
    return (OK, {"user_id": "me", "username": name}) if name != "ghost" else ("not_found", None)


def test_percentile_definition():
    assert mcmp.percentile(5, [1, 2, 5, 9]) == round((2 + 0.5) / 4, 4)
    assert mcmp.percentile(None, [1]) is None
    assert mcmp.percentile(3, []) is None


def test_league_percentile_over_batch_c_rows():
    rows = [
        _row(1, "me", 5000, 10, 6),
        _row(2, "a", 4000, 20, 6),
        _row(3, "b", 6000, 4, None),  # pick ownership unknown: not ranked on picks
        _row(4, "c", None, 6, 2),  # unpriced roster: not ranked on value
    ]
    out = mcmp.build_league_percentile(
        "someone",
        "9",
        contract=None,
        fetch_user=_fetch_user,
        league_provider=lambda lid, **kw: _scouting(rows),
    )
    m = {x["key"]: x for x in out["metrics"]}
    assert out["managerInLeague"] is True and out["team"]["rosterId"] == 1
    assert m["rosterValue"]["value"] == 5000
    assert m["rosterValue"]["teamsWithValue"] == 3
    assert m["rosterValue"]["percentile"] == 0.5  # above 4000, below 6000
    assert m["events"]["percentile"] == round(2 / 3, 4)
    # Picks: others with a value are rows 2 (6, tie) and 4 (2).
    assert m["picksHeld"]["percentile"] == round((1 + 0.5) / 2, 4)
    assert m["rosterValue"]["leagueMedian"] == 5000


def test_league_percentile_manager_missing_value_and_not_in_league():
    rows = [_row(1, "me", None, 3, None), _row(2, "a", 4000, 2, 4)]
    out = mcmp.build_league_percentile(
        "someone",
        "9",
        contract=None,
        fetch_user=_fetch_user,
        league_provider=lambda lid, **kw: _scouting(rows),
    )
    m = {x["key"]: x for x in out["metrics"]}
    assert m["rosterValue"]["value"] is None and m["rosterValue"]["percentile"] is None
    assert m["rosterValue"]["reason"] == "x"
    assert m["picksHeld"]["reason"] == "pick_ownership_unavailable"

    out = mcmp.build_league_percentile(
        "someone",
        "9",
        contract=None,
        fetch_user=_fetch_user,
        league_provider=lambda lid, **kw: _scouting([_row(2, "a", 1, 1, 1)]),
    )
    assert out["managerInLeague"] is False
    assert all(x["percentile"] is None for x in out["metrics"])
    assert {x["reason"] for x in out["metrics"]} == {"manager_not_in_league"}


def test_league_percentile_failures_name_the_side():
    out = mcmp.build_league_percentile(
        "ghost", "9", contract=None, fetch_user=_fetch_user, league_provider=lambda *a, **k: {}
    )
    assert out["status"] == "not_found" and out["failedSide"] == "a"
    out = mcmp.build_league_percentile(
        "x",
        "9",
        contract=None,
        fetch_user=_fetch_user,
        league_provider=lambda *a, **k: {"status": "not_found"},
    )
    assert out["status"] == "not_found" and out["failedSide"] == "league"


def test_observed_but_unpriced_picks_name_the_pricing_reason():
    row = _row(1, "me", 10, 3, 4)
    row["draftCapital"]["pricedValue"] = None
    row["draftCapital"]["unpricedReasons"] = {"board_unavailable": 4}
    out = mcmp.build_league_percentile(
        "someone",
        "9",
        contract=None,
        fetch_user=_fetch_user,
        league_provider=lambda lid, **kw: _scouting([row, _row(2, "a", 5, 1, 2)]),
    )
    m = {x["key"]: x for x in out["metrics"]}
    assert m["pickValue"]["reason"] == "board_unavailable"
    assert m["picksHeld"]["value"] == 4 and m["picksHeld"]["percentile"] == 1.0
