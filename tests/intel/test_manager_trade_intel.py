"""Manager Intelligence Batch B3 — draft capital and trade intelligence.

Deterministic: every Sleeper call is an injected fake (the B1/B2 harness from
``test_manager_activity``).  Pins the workstream's B3 "Tests" bullets
(``docs/intel/MANAGER_INTELLIGENCE_WORKSTREAM.md``): the ownership fold
(acquired picks, own picks traded away), a failed ``/traded_picks`` is
"unavailable" and never "owns no picks", a class whose rookie draft completed
is not held, generic-grade pick values with unpriced reasons, pick movement,
tendency counts with the insufficient-sample state, and coverage states.
"""

from __future__ import annotations

import pytest

from src.intel import manager_activity as ma
from src.intel import manager_trade_intel as mti
from src.public_league import sleeper_client as sc
from tests.intel.test_manager_activity import STATE, FakeSleeper, _league, _tx


@pytest.fixture(autouse=True)
def _reset():
    ma.reset_caches()
    yield
    ma.reset_caches()


ROOKIE_DRAFT_2026 = {
    "draft_id": "d26",
    "season": "2026",
    "status": "complete",
    "type": "linear",
    "settings": {"player_type": 1, "teams": 3, "rounds": 1},
    "start_time": 1_780_000_000_000,
    "last_picked": 1_780_000_500_000,
}


def _rookie_picks():
    return [
        {
            "pick_no": n,
            "round": 1,
            "roster_id": rid,
            "player_id": pid,
            "picked_by": owner,
            "metadata": {"years_exp": 0},
        }
        for n, rid, pid, owner in ((1, 1, "R", "1001"), (2, 2, "B", "2002"), (3, 3, "D", "3003"))
    ]


@pytest.fixture
def fake() -> FakeSleeper:
    f = FakeSleeper()
    lg = _league("11", "Alpha League")
    lg["settings"]["draft_rounds"] = 2
    f.leagues = [lg]
    f.rosters["11"] = [
        {"roster_id": 1, "owner_id": "1001", "players": ["A", "C", "R"]},
        {"roster_id": 2, "owner_id": "2002", "players": ["B"]},
        {"roster_id": 3, "owner_id": "3003", "players": ["D"]},
    ]
    f.users["11"] = [
        {"user_id": "1001", "display_name": "Dynasty Fan"},
        {"user_id": "2002", "display_name": "Rival Two"},
        {"user_id": "3003", "display_name": "Rival Three"},
    ]
    f.drafts["11"] = [ROOKIE_DRAFT_2026]
    f.picks["d26"] = _rookie_picks()
    f.traded["11"] = [
        # Acquired: roster 2's 2027 1st now held by the manager (roster 1).
        {"season": "2027", "round": 1, "roster_id": 2, "owner_id": 1, "previous_owner_id": 2},
        # Own pick traded away: the manager's 2027 2nd now held by roster 3.
        {"season": "2027", "round": 2, "roster_id": 1, "owner_id": 3, "previous_owner_id": 1},
    ]
    return f


def _capital(out):
    (entry,) = out["draftCapital"]["leagues"]
    return entry


# ── ownership fold ──────────────────────────────────────────────────────


def test_fold_lists_own_and_acquired_picks_and_own_picks_traded_away(fake):
    out = fake.build()
    dc = out["draftCapital"]
    assert dc["available"] is True
    entry = _capital(out)
    assert entry["pickOwnershipState"] == "observed"
    assert entry["pickOwnershipReason"] is None
    assert entry["coverage"] == "complete" and entry["rounds"] == 2
    assert entry["roundsSource"] == "league_settings"
    labels = [(p["label"], p["own"], p["originRosterId"]) for p in entry["picks"]]
    assert labels == [
        ("2027 Round 1", True, 1),
        ("2027 Round 1", False, 2),
        ("2028 Round 1", True, 1),
        ("2028 Round 2", True, 1),
        ("2029 Round 1", True, 1),
        ("2029 Round 2", True, 1),
    ]
    acquired = next(p for p in entry["picks"] if not p["own"])
    assert acquired["originOwnerName"] == "Rival Two"
    assert acquired["currentOwnerRosterId"] == 1
    assert acquired["pickId"] == "pick:sleeper-11:2027:r1:o2"
    (away,) = entry["ownPicksTradedAway"]
    assert away["label"] == "2027 Round 2" and away["currentOwnerName"] == "Rival Three"
    assert entry["counts"] == {"held": 6, "own": 5, "acquired": 1, "ownTradedAway": 1}
    assert entry["bySeason"]["2027"] == {"held": 2, "own": 1, "acquired": 1}
    assert dc["totals"]["picksHeld"] == 6 and dc["totals"]["ownTradedAway"] == 1
    assert out["coverage"]["leagues"][0]["tradedPicks"] == "complete"
    assert ("traded_picks", "11") in fake.calls


def test_completed_rookie_draft_class_is_not_held(fake):
    entry = _capital(fake.build())
    years = entry["draftYears"]
    assert years["rule"] == "src/identity/pick_lifecycle.py::league_draft_years"
    assert years["evidence"] == "league_drafts_read"
    assert 2026 in years["retiredSeasons"]
    assert years["ownedPickSeasons"] == [2027, 2028, 2029]
    assert years["upcomingDraftYear"] == 2027
    assert all(p["season"] != 2026 for p in entry["picks"])


def test_startup_only_league_complete_draft_class_is_not_held(fake):
    # One completed NON-rookie (startup) draft for 2026: the canonical
    # lifecycle leaves 2026 "unknown", but that league's 2026 draft has run,
    # so no 2026 pick is held.
    fake.drafts["11"] = [{**ROOKIE_DRAFT_2026, "settings": {"player_type": 0, "teams": 3}}]
    fake.picks["d26"] = [{**p, "metadata": {"years_exp": 4}} for p in _rookie_picks()]
    entry = _capital(fake.build())
    years = entry["draftYears"]
    assert years["retiredSeasons"] == [] and 2026 in years["ownedPickSeasons"]
    assert years["draftCompleteSeasons"] == [2026]
    assert years["heldSeasons"] == [2027, 2028, 2029]
    assert all(p["season"] != 2026 for p in entry["picks"])


def test_upcoming_class_is_held_while_its_draft_has_not_run(fake):
    fake.drafts["11"] = [{**ROOKIE_DRAFT_2026, "status": "pre_draft"}]
    entry = _capital(fake.build())
    assert entry["draftYears"]["ownedPickSeasons"] == [2026, 2027, 2028, 2029]
    assert entry["draftYears"]["heldSeasons"] == [2026, 2027, 2028, 2029]
    assert any(p["season"] == 2026 for p in entry["picks"])


def test_unreadable_drafts_list_retires_nothing(fake):
    fake.drafts["11"] = sc.FETCH_ERROR
    entry = _capital(fake.build())
    assert entry["draftYears"]["evidence"] == "persisted_snapshot_or_none"
    assert entry["draftYears"]["retiredSeasons"] == []
    # The 2026 pick is held but its value is unknown (draft status unread).
    p26 = next(p for p in entry["picks"] if p["season"] == 2026)
    assert p26["value"] is None and p26["valueReason"] == "draft_status_unknown"


def test_default_rounds_when_league_does_not_state_them(fake):
    del fake.leagues[0]["settings"]["draft_rounds"]
    entry = _capital(fake.build())
    assert entry["rounds"] == 6 and entry["roundsSource"] == "default"


# ── unavailable is never empty ──────────────────────────────────────────


@pytest.mark.parametrize(
    ("kind", "coverage"),
    [(sc.FETCH_ERROR, "unavailable"), (sc.FETCH_RATE_LIMITED, "rate_limited")],
)
def test_failed_traded_picks_is_unavailable_not_empty(fake, kind, coverage):
    fake.traded["11"] = kind
    out = fake.build()
    entry = _capital(out)
    assert entry["picks"] is None and entry["ownPicksTradedAway"] is None
    assert entry["pickOwnershipState"] == "unavailable"
    assert entry["pickOwnershipReason"] == "traded_picks_fetch_failed"
    assert entry["coverage"] == coverage
    assert entry["pricedValue"] is None and entry["counts"] is None
    assert out["coverage"]["leagues"][0]["tradedPicks"] == coverage
    assert out["status"] == "partial"
    totals = out["draftCapital"]["totals"]
    assert totals["leaguesUnavailable"] == 1 and totals["leaguesObserved"] == 0


def test_empty_traded_picks_is_an_observation(fake):
    fake.traded["11"] = []
    entry = _capital(fake.build())
    assert entry["pickOwnershipState"] == "observed"
    assert entry["counts"]["acquired"] == 0 and entry["counts"]["ownTradedAway"] == 0
    assert entry["counts"]["held"] == 6


def test_non_list_traded_picks_body_proves_nothing(fake):
    fake.fetch_traded_picks = lambda lid: (sc.FETCH_OK, {"error": "nope"})
    entry = _capital(fake.build())
    assert entry["picks"] is None and entry["pickOwnershipState"] == "unavailable"


def test_budget_refused_traded_picks_is_not_read(fake):
    out = fake.build(call_budget=3)  # rosters + users + drafts
    entry = _capital(out)
    assert entry["picks"] is None and entry["coverage"] == "none"
    assert out["coverage"]["budgetExhausted"] is True


def test_unreadable_rosters_league_is_unavailable(fake):
    fake.rosters["11"] = sc.FETCH_RATE_LIMITED
    out = fake.build()
    entry = _capital(out)
    assert entry["picks"] is None and entry["coverage"] == "rate_limited"
    assert entry["pickOwnershipReason"] == "rosters_unavailable"
    assert not [c for c in fake.calls if c[0] == "traded_picks"]


def test_earlier_season_has_no_draft_capital_and_no_traded_picks_call(fake):
    out = fake.build(season="2025")
    assert out["draftCapital"]["available"] is False
    assert out["draftCapital"]["reason"] == "earlier_season"
    assert out["coverage"]["leagues"][0]["tradedPicks"] == "none"
    assert not [c for c in fake.calls if c[0] == "traded_picks"]


def test_traded_picks_is_memoised_across_requests(fake):
    fake.build()
    fake.build()
    assert sum(1 for c in fake.calls if c[0] == "traded_picks") == 1


# ── values ──────────────────────────────────────────────────────────────


def test_generic_grade_values_and_unpriced_reasons(fake):
    entry = _capital(fake.build())
    p27 = [p for p in entry["picks"] if p["season"] == 2027]
    assert all(p["value"] == 3500 for p in p27)
    assert all(p["valueBasis"] == "board_row" for p in p27)
    assert all(p["boardRowName"] == "2027 Round 1" for p in p27)
    later = [p for p in entry["picks"] if p["season"] in (2028, 2029)]
    assert all(p["value"] is None for p in later)
    assert all(p["valueReason"] == "no_board_row_for_ref" for p in later)
    assert entry["pricedValue"] == 7000
    assert entry["pricedPickCount"] == 2 and entry["unpricedPickCount"] == 4
    assert entry["unpricedReasons"] == {"no_board_row_for_ref": 4}


def test_no_board_makes_every_pick_unpriced_and_the_total_null(fake):
    entry = _capital(fake.build(contract=None))
    assert all(p["value"] is None for p in entry["picks"])
    assert entry["pricedValue"] is None and entry["pricedPickCount"] == 0


def test_no_picks_held_is_an_observed_zero_total(fake):
    # Every one of the manager's picks traded away.
    fake.traded["11"] = [
        {"season": str(s), "round": r, "roster_id": 1, "owner_id": 2}
        for s in (2027, 2028, 2029)
        for r in (1, 2)
    ]
    entry = _capital(fake.build())
    assert entry["picks"] == [] and entry["pricedValue"] == 0
    assert entry["counts"]["ownTradedAway"] == 6


# ── pick movement ───────────────────────────────────────────────────────


def test_pick_movement_from_the_trade_stream(fake):
    fake.tx[("11", 6)] = [
        _tx(
            "pm",
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
                },
                {
                    "season": "2027",
                    "round": 2,
                    "roster_id": 1,
                    "previous_owner_id": 1,
                    "owner_id": 2,
                },
            ],
        )
    ]
    mv = fake.build()["draftCapital"]["movements"]
    assert mv["acquired"] == 1 and mv["sent"] == 1
    acq = next(r for r in mv["rows"] if r["direction"] == "acquired")
    sent = next(r for r in mv["rows"] if r["direction"] == "sent")
    assert acq["counterparty"]["displayName"] == "Rival Two"
    assert sent["counterparty"]["displayName"] == "Rival Two"
    assert acq["occurredAt"] is not None and acq["tradeId"] == "tx:pm"
    assert acq["stillHeld"] is True  # traded_picks says roster 1 holds it
    # traded_picks shows the 2027 2nd with roster 3 (moved on again).
    assert sent["stillHeld"] is False
    assert mv["byLeague"]["11"] == {"leagueName": "Alpha League", "acquired": 1, "sent": 1}


# ── tendencies ──────────────────────────────────────────────────────────


def _trade(tid, days, adds, drops, picks=()):
    return _tx(
        tid,
        roster_ids=[1, 2],
        adds=adds,
        drops=drops,
        days_ago=days,
        draft_picks=list(picks),
    )


def test_tendencies_insufficient_below_the_prior_minimum(fake):
    fake.tx[("11", 6)] = [_trade("t1", 3, {"A": 1}, {"A": 2})]
    tend = fake.build()["tendencies"]
    assert mti.TENDENCY_MIN_SAMPLE == 3
    assert tend["tradeCount"] == 1 and tend["minSampleBasis"] == "PRIOR"
    assert tend["pickPlayer"]["n"] == 1 and tend["pickPlayer"]["sufficientSample"] is False
    assert tend["positions"]["n"] == 1 and tend["positions"]["sufficientSample"] is False


def test_tendency_counts_values_ages_and_shapes(fake):
    pick_out = {"season": "2027", "round": 1, "roster_id": 1, "previous_owner_id": 1, "owner_id": 2}
    pick_in = {"season": "2027", "round": 2, "roster_id": 2, "previous_owner_id": 2, "owner_id": 1}
    fake.tx[("11", 6)] = [
        # picks for a player: the manager sends a 1st, receives A (RB).
        _trade("s1", 2, {"A": 1}, {"A": 2}, [pick_out]),
        # players for picks: the manager sends B (WR), receives a 2nd.
        _trade("s2", 3, {"B": 2}, {"B": 1}, [pick_in]),
        # 2-for-1 consolidation: sends C + D, receives R.
        _trade("s3", 4, {"R": 1, "C": 2, "D": 2}, {"R": 2, "C": 1, "D": 1}),
    ]
    directory = {"A": {"age": 25}, "B": {"age": 31}, "C": {"age": 28}, "R": {"age": 21}}
    tend = fake.build(fetch_directory=lambda: directory)["tendencies"]
    assert tend["tradeCount"] == 3
    assert tend["pickPlayer"]["sufficientSample"] is True
    shapes = tend["pickPlayer"]["counts"]
    assert shapes["picks_for_players"] == 1 and shapes["players_for_picks"] == 1
    assert shapes["players_for_players"] == 1
    pieces = tend["pieces"]["counts"]
    assert pieces == {"consolidation": 1, "depth": 0, "even": 2}
    assert tend["pieces"]["shapes"] == {"1-for-1": 2, "1-for-2": 1}
    pos = {r["key"]: r for r in tend["positions"]["rows"]}
    assert tend["positions"]["n"] == 5  # A, R in; B, C, D out
    assert pos["RB"]["acquired"]["count"] == 2 and pos["RB"]["acquired"]["pricedValue"] == 7500
    assert pos["WR"]["sent"] == {
        "count": 1,
        "pricedValue": 4000,
        "pricedCount": 1,
        "unpricedCount": 0,
    }
    assert pos["RB"]["sent"]["count"] == 0 and pos["RB"]["sent"]["pricedValue"] is None
    ages = {r["key"]: r for r in tend["ages"]["rows"]}
    assert ages["≤23"]["acquired"]["count"] == 1  # R, 21
    assert ages["24-26"]["acquired"]["count"] == 1  # A, 25
    assert ages["30+"]["sent"]["count"] == 1  # B, 31
    assert ages["27-29"]["sent"]["count"] == 1  # C, 28
    assert ages["unknown"]["sent"]["count"] == 1  # D: no age anywhere
    assert "current age" in tend["ages"]["basis"]


def test_uncertain_attribution_trades_are_left_out_of_tendencies(fake):
    fake.tx[("11", 6)] = [
        _tx("u1", roster_ids=[1, 2], adds={"A": 1}, drops={"A": 2}, creator="7777")
    ]
    tend = fake.build()["tendencies"]
    assert tend["tradeCount"] == 0 and tend["excludedUncertain"] == 1


def test_age_buckets_are_declared_and_total():
    assert [b[0] for b in mti.AGE_BUCKETS] == ["≤23", "24-26", "27-29", "30+"]
    assert mti.age_bucket(None) == "unknown"
    assert mti.age_bucket(True) == "unknown"
    assert mti.age_bucket(23) == "≤23" and mti.age_bucket(30) == "30+"
    assert mti.age_bucket(23.5) == "24-26"


def test_state_unchanged_by_b3_for_the_feed(fake):
    # B3 adds blocks; the existing views are untouched.
    out = fake.build()
    assert set(out) >= {"trades", "acquisitions", "feed", "draftCapital", "tendencies"}
    assert STATE["league_season"] == out["currentSeason"]


# ── API: the real builder behind the route ──────────────────────────────


@pytest.fixture
def route(monkeypatch, fake):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.api import feature_flags, rate_limit
    from src.intel import manager_intel_api as api
    from tests.intel.test_manager_activity import CONTRACT, DIRECTORY, NOW_S

    rate_limit.reset_for_tests()
    feature_flags.reload()
    real = ma.cached_manager_activity

    def wired(username, **kwargs):
        kwargs.pop("asof_factory", None)
        return real(
            username,
            fetch_user=fake.fetch_user,
            fetch_leagues=fake.fetch_leagues,
            fetch_rosters=fake.fetch_rosters,
            fetch_users=fake.fetch_users,
            fetch_transactions=fake.fetch_transactions,
            fetch_drafts=fake.fetch_drafts,
            fetch_draft_picks=fake.fetch_draft_picks,
            fetch_traded_picks=fake.fetch_traded_picks,
            fetch_state=lambda: STATE,
            fetch_directory=lambda: DIRECTORY,
            now=lambda: NOW_S,
            **kwargs,
        )

    monkeypatch.setattr(ma, "cached_manager_activity", wired)
    api.configure(
        session_provider=lambda request: {"username": "owner", "auth_method": "password"},
        contract_provider=lambda: CONTRACT,
    )
    app = FastAPI()
    app.include_router(api.router)
    yield TestClient(app)
    api.configure(session_provider=None, contract_provider=None)
    rate_limit.reset_for_tests()
    feature_flags.reload()


def test_route_serves_draft_capital_and_tendencies(route):
    r = route.get("/api/manager-intel/activity", params={"username": "dynastyfan"})
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    body = r.json()
    assert body["draftCapital"]["available"] is True
    assert body["draftCapital"]["leagues"][0]["pickOwnershipState"] == "observed"
    assert body["tendencies"]["minSample"] == mti.TENDENCY_MIN_SAMPLE
    assert body["coverage"]["leagues"][0]["tradedPicks"] == "complete"


def test_route_rate_limited_traded_picks_is_a_partial_200(route, fake):
    fake.traded["11"] = sc.FETCH_RATE_LIMITED
    r = route.get("/api/manager-intel/activity", params={"username": "dynastyfan"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "partial"
    assert body["coverage"]["leagues"][0]["tradedPicks"] == "rate_limited"
    entry = body["draftCapital"]["leagues"][0]
    assert entry["picks"] is None and entry["pickOwnershipState"] == "unavailable"


def test_route_sleeper_429_on_the_user_is_429(route, fake):
    fake.fetch_user = lambda username: (sc.FETCH_RATE_LIMITED, None)
    r = route.get("/api/manager-intel/activity", params={"username": "dynastyfan"})
    assert r.status_code == 429 and r.json()["error"] == "upstream_rate_limited"
