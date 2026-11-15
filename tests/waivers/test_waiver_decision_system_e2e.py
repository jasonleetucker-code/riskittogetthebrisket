"""Waiver Advisor, FAAB and IDP Streaming as ONE decision system, end to end.

Owner master directive 2026-11-08 section 14, Priority 9: the waiver surfaces
are decision systems, not pages.  One league, one team, one roster, one
balance, driven through the REAL route handlers (no composer is called
directly and nothing but external I/O is stubbed: Sleeper, the weekly
projection feed and the intel snapshot)::

    POST /api/waiver/advisor      POST /api/waiver/perfect
    POST /api/waiver/suggestions  POST /api/waiver/faab-recommend
    POST /api/waiver/streaming

Workflow covered, in order: user + league identification -> current roster ->
player availability -> league scoring / starter slots -> roster size -> team
needs -> remaining FAAB -> candidate value -> dynasty-loss constraint -> legal
drops -> streaming horizon -> expected weekly benefit -> opportunity cost ->
recommendation -> the NO ACTION alternative.

Every expectation is derived BY HAND from the fixture league (arithmetic is in
the comments); no assertion compares a function with its own output, except
the explicitly relational "surfaces agree" checks, whose oracle is the other
surfaces.

The fixture league
------------------
Starting slots ``QB TE DL LB LB DB`` + 2 bench = roster limit 8.  ``me`` holds
exactly 8 players (full).  FAAB balance 60 of a 100 original budget.

=========== == ========= ========= ===========================================
roster      pos board     week-9 pt note
=========== == ========= ========= ===========================================
Star QB     QB 8000      20
Weak TE     TE 900       6
Star DL     DL 3000      9
Star LB     LB 2500      10
Star DB     DB 2000      8
Bench LB    LB 700       3         weakest LB starter (the 2nd LB slot)
Bench WR    WR 3000      12        not startable: no WR / FLEX slot
Deep WR     WR 400       4         not startable
=========== == ========= ========= ===========================================

Free agents: Free TE (2600, 9 pts), Free WR (2500, 11), Free LB (1800, 12),
Free DL (1500, 5).  Hand-derived facts used below:

* no WR / RB / FLEX slot exists, so Free WR can never be started and is never
  offered (``position_not_started``);
* week-9 baseline lineup points = 20 + 6 + 9 + (10 + 3) + 8 = 56;
* adding Free LB and releasing Bench LB gains 12 - 3 = 9 points;
* releasing Bench LB costs 700 dynasty value: its full board value, because
  the drop assessment marks it ``conditional`` (age / draft recency / trend
  unknown), so it is not a free "churn" release;
* that plan's dynasty value change is 1800 - 700 = +1100.

``xfail(strict=True)`` tests are FINDINGS: invariants the owner directive
states that FAIL on current ``main``.  Each names the exact defect and flips
to a hard failure the moment the defect is fixed, which forces the marker's
removal.  No production code is changed here.
"""

from __future__ import annotations

import dataclasses
import functools
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import server
from src.api import feature_flags, league_registry, user_kv
from src.ros.weekly_league_projections import LeagueScoredWeeklyProjection, WeeklyProjectionSet
from src.waivers import streaming as streaming_module

ADVISOR = "/api/waiver/advisor"
PERFECT = "/api/waiver/perfect"
SUGGEST = "/api/waiver/suggestions"
DESK = "/api/waiver/faab-recommend"
STREAM = "/api/waiver/streaming"
AS = {"x-test-user": "alice"}
_OMIT = object()
IDP_POSITIONS = {"DL", "LB", "DB"}
SLOTS_IDP = ["QB", "TE", "DL", "LB", "LB", "DB", "BN", "BN"]
SLOTS_OFFENSE_ONLY = ["QB", "TE", "FLEX", "BN", "BN", "BN", "BN", "BN"]
ELIGIBLE_FREE_AGENTS = {"Free TE", "Free LB", "Free DL"}  # Free WR: no slot can start him


def _row(pid, name, pos, value):
    return {
        "playerId": pid,
        "displayName": name,
        "canonicalName": name,
        "legacyRef": name,
        "position": pos,
        "team": "XX",
        "rankDerivedValue": value,
        "sourceCount": 3,
        "assetClass": "idp" if pos in IDP_POSITIONS else "offense",
        "confidenceBucket": "medium",
        "confidenceLabel": "Medium",
    }


def _team(owner, rid, players, remaining, budget=100):
    team = {
        "ownerId": owner,
        "name": owner.title(),
        "roster_id": rid,
        "players": [n for _p, n in players],
        "playerIds": [p for p, _n in players],
        "faabBudget": budget,
    }
    if remaining is not _OMIT:
        team["faabRemaining"] = remaining
    return team


BOARD = [
    ("qb1", "Star QB", "QB", 8000),
    ("te1", "Weak TE", "TE", 900),
    ("dl1", "Star DL", "DL", 3000),
    ("lb1", "Star LB", "LB", 2500),
    ("db1", "Star DB", "DB", 2000),
    ("lbx", "Bench LB", "LB", 700),
    ("wr1", "Bench WR", "WR", 3000),
    ("wr2", "Deep WR", "WR", 400),
    ("rq", "Rival QB", "QB", 7000),
    ("fa1", "Free TE", "TE", 2600),
    ("fa2", "Free WR", "WR", 2500),
    ("fa3", "Free LB", "LB", 1800),
    ("fa4", "Free DL", "DL", 1500),
]
EXTRA_LBS = [(f"x{i}", f"Extra LB {i}", "LB", 1900 + 37 * i) for i in range(10)]
MINE = [(p, n) for p, n, _pos, _v in BOARD[:8]]
RIVAL = [("rq", "Rival QB")]
PTS = {
    "qb1": 20, "te1": 6, "dl1": 9, "lb1": 10, "db1": 8, "lbx": 3, "wr1": 12, "wr2": 4,
    "rq": 18, "fa1": 9, "fa2": 11, "fa3": 12, "fa4": 5,
}  # fmt: skip


def _contract(positions=SLOTS_IDP, balance=60, mine=MINE, values=None, extra=()):
    values = values or {}
    board = [*BOARD, *extra]
    return {
        "meta": {"leagueKey": "main"},
        "playersArray": [_row(p, n, pos, values.get(p, v)) for p, n, pos, v in board],
        "sleeper": {
            "rosterPositions": list(positions),
            "positions": {n: pos for _p, n, pos, _v in board},
            "teams": [_team("me", 1, mine, balance), _team("them", 2, RIVAL, 100)],
        },
    }


def _stub_projections(monkeypatch, pts=None, extra=()):
    """Offline weekly projection feed: hand-written points per player id."""
    pts = dict(PTS if pts is None else pts)
    board = [*BOARD, *extra]

    def load(league_key, season, week, current_week=None):
        rows = {
            pid: LeagueScoredWeeklyProjection(
                player_id=pid,
                name=name,
                position=pos,
                team="AAA",
                season=2026,
                week=week,
                weekly_points=pts.get(pid),
                state="projected" if pts.get(pid) is not None else "unprojected",
                reason="fixture",
            )
            for pid, name, pos, _v in board
        }
        return WeeklyProjectionSet(
            league_key=league_key,
            season=2026,
            week=week,
            as_of="2026-11-08T00:00:00+00:00",
            scoring_fingerprint="sf1:fixture",
            scoring_evidence_state="caller_supplied",
            refusal=None,
            source_states=(),
            players=rows,
            schedule_state="ok",
            bye_teams=(),
            current_week=week - 1,
            cache_key="fixture",
        )

    import src.ros.weekly_league_projections as feed

    monkeypatch.setattr(feed, "load_weekly_projections", load)


@pytest.fixture()
def env(tmp_path: Path, monkeypatch):
    registry = tmp_path / "registry.json"

    def write_registry(*, drop_roster_size=False, **roster_settings):
        settings = {"teamCount": 2, "rosterSize": 8, **roster_settings}
        if drop_roster_size:
            del settings["rosterSize"]
        registry.write_text(
            json.dumps(
                {
                    "defaultLeagueKey": "main",
                    "leagues": [
                        {
                            "key": "main",
                            "displayName": "Main",
                            "sleeperLeagueId": "111",
                            "active": True,
                            "rosterSettings": settings,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        league_registry.reload_registry()

    monkeypatch.setenv("LEAGUE_REGISTRY_PATH", str(registry))
    write_registry()
    monkeypatch.setattr(user_kv, "USER_KV_PATH", tmp_path / "user_kv.sqlite")
    user_kv._SETUP_DONE.clear()

    def session(request):
        user = (getattr(request, "headers", None) or {}).get("x-test-user")
        return {"username": user, "auth_method": "password"} if user else None

    monkeypatch.setattr(server, "_get_auth_session", session)
    monkeypatch.setattr(server._sleeper_overlay, "fetch_sleeper_teams_overlay", lambda **_kw: None)
    real_is_enabled = feature_flags.is_enabled
    monkeypatch.setattr(
        feature_flags,
        "is_enabled",
        lambda name, *a, **k: (
            True if name in ("waiver_advisor", "idp_streaming") else real_is_enabled(name, *a, **k)
        ),
    )
    _stub_projections(monkeypatch)
    # No ``with``: the lifespan would load the real board over these fixtures.
    client = TestClient(server.app, raise_server_exceptions=True)

    def load(contract):
        monkeypatch.setattr(server, "latest_contract_data", contract)
        server._PERFECT_WAIVERS_CACHE.clear()
        return contract

    def post(url, expect=200, **body):
        res = client.post(url, json={"leagueKey": "main", "teamOwnerId": "me", **body}, headers=AS)
        assert res.status_code == expect, res.text
        return res.json()

    def stream(expect=200, **body):
        body.setdefault("week", 9)  # explicit: never depend on today's NFL week
        body.setdefault("horizonWeeks", 1)
        return post(STREAM, expect=expect, **body)

    yield SimpleNamespace(
        client=client,
        load=load,
        post=post,
        stream=stream,
        monkeypatch=monkeypatch,
        write_registry=write_registry,
    )
    league_registry.reload_registry()


def _advisor_by_name(payload):
    return {c["name"]: c for c in payload["candidates"]}


def _suggestion_names(payload):
    return {c["name"] for items in payload["by_position"].values() for c in items}


def _every_streaming_plan(stream):
    plans = [stream["plan"], stream["largerBudget"]["plan"], *stream["alternatives"]]
    return [p for p in plans if p]


# =====================================================================
# 1. The complete workflow, every surface on one context
# =====================================================================


def test_workflow_identification_roster_availability_scoring_capacity(env):
    env.load(_contract())
    adv = env.post(ADVISOR)
    perfect = env.post(PERFECT)
    sug = env.post(SUGGEST)
    stream = env.stream()

    # user + league identification: the team is the NAMED owner, the league the
    # one asked for; every private surface stamps both.
    assert adv["team"]["ownerId"] == "me" and adv["team"]["rosterId"] == 1
    assert perfect["team"]["ownerId"] == "me" and stream["team"]["ownerId"] == "me"
    assert adv["leagueKey"] == perfect["leagueKey"] == sug["leagueKey"] == "main"
    assert stream["leagueKey"] == "main"

    # current roster + roster size: 8 of 8, so a claim must name a drop.
    assert perfect["capacity"]["rosterCount"] == 8 and perfect["capacity"]["rosterLimit"] == 8
    assert perfect["capacity"]["openSpotsPlanned"] == 0 and stream["openSpots"] == 0
    assert all(c["capacity"]["rosterLimit"] == 8 for c in adv["candidates"])
    assert all(c["capacity"]["openSpotsBefore"] == 0 for c in adv["candidates"])

    # league scoring / starter positions: the live host's slot list, bench removed.
    assert stream["lineup"]["slots"] == ["QB", "TE", "DL", "LB", "LB", "DB"]
    assert stream["lineup"]["source"] == "sleeper_roster_positions"
    assert sug["positionEligibility"]["state"] == "league_slots"

    # player availability: exactly the hand-derived set (not rostered by anyone,
    # startable by some slot) on every surface that lists the wire.
    assert set(_advisor_by_name(adv)) == ELIGIBLE_FREE_AGENTS
    assert _suggestion_names(sug) == ELIGIBLE_FREE_AGENTS
    assert {m["add"]["name"] for m in perfect["plan"]["moves"]} <= ELIGIBLE_FREE_AGENTS
    assert {b["name"] for b in stream["streamingBoard"]} <= {"Free LB", "Free DL"}  # IDP only
    rostered = {n for _p, n in MINE} | {n for _p, n in RIVAL}
    assert not set(_advisor_by_name(adv)) & rostered
    assert not _suggestion_names(sug) & rostered


def test_workflow_candidate_value_replacement_and_team_needs(env):
    env.load(_contract())
    adv = _advisor_by_name(env.post(ADVISOR))
    # candidate value is the canonical board value, read as is.
    assert {n: c["value"]["canonicalValue"] for n, c in adv.items()} == {
        "Free TE": 2600.0,
        "Free LB": 1800.0,
        "Free DL": 1500.0,
    }
    # team needs: Free TE (2600) beats the only TE on the roster (Weak TE 900),
    # so he would enter the optimal lineup (delta 2600 - 900); Free DL (1500)
    # does not beat Star DL (3000), so he would not.
    assert adv["Free TE"]["lineup"]["entersOptimalLineup"] is True
    assert adv["Free TE"]["lineup"]["startingValueDelta"] == 2600.0 - 900.0
    assert adv["Free DL"]["lineup"]["entersOptimalLineup"] is False
    assert "not a weekly projection" in adv["Free TE"]["lineup"]["objective"]


@pytest.mark.parametrize("balance", [60, 20, 3])
def test_workflow_bids_never_exceed_the_balance_and_surfaces_agree(env, balance):
    """Same context, five surfaces, one canonical bid, never above the balance."""
    env.load(_contract(balance=balance))
    adv = _advisor_by_name(env.post(ADVISOR))
    sug = {c["name"]: c for items in env.post(SUGGEST)["by_position"].values() for c in items}
    stream = {b["name"]: b for b in env.stream()["streamingBoard"]}
    perfect_adds = {
        m["add"]["name"]: m["add"]["bid"]["recommended"] for m in env.post(PERFECT)["plan"]["moves"]
    }
    assert perfect_adds, "non-vacuity: the plan adds someone"
    for name in ELIGIBLE_FREE_AGENTS:
        desk = env.post(DESK, addPlayerName=name)["bids"]["recommended"]
        assert 0 <= desk <= balance, (name, balance)
        assert adv[name]["faab"]["recommendedBid"] == desk, (name, balance, "advisor vs desk")
        assert sug[name]["bid"]["reasonable"] == desk, (name, balance, "suggestions vs desk")
        if name in stream:
            assert stream[name]["bid"] == desk, (name, balance, "streaming vs desk")
        if name in perfect_adds:
            assert perfect_adds[name] == desk, (name, balance, "perfect vs desk")
    assert adv["Free TE"]["faab"]["maxRationalBid"]["value"] <= balance


def test_workflow_dynasty_loss_budget_streaming_horizon_and_recommendation(env):
    env.load(_contract())
    default = env.stream()
    # default dynasty-loss budget is ZERO: the request did not authorize any.
    assert default["request"]["dynastyBudget"] == 0.0
    # Opportunity cost: the only gaining plan costs 700 dynasty value, so the
    # zero budget refuses it, says why, and shows what a larger budget buys.
    assert default["recommendMove"] is False and default["plan"] is None
    assert default["noMoveReason"] == "dynasty_budget_binds"
    larger = default["largerBudget"]["plan"]
    assert larger["adds"] == ["fa3"] and larger["drops"] == ["lbx"]
    assert larger["weeklyGainPoints"] == 12 - 3  # expected weekly benefit
    assert larger["netDynastyLoss"] == 700.0  # Bench LB's full board value
    assert larger["dynastyValueChange"]["value"] == 1800.0 - 700.0
    assert default["baselinePoints"] == [20 + 6 + 9 + 10 + 3 + 8]
    # The boundary is the hand-derived cost: 699 refuses, 700 recommends.
    assert env.stream(dynastyBudget=699)["recommendMove"] is False
    chosen = env.stream(dynastyBudget=700)
    assert chosen["recommendMove"] is True
    assert chosen["plan"]["adds"] == ["fa3"] and chosen["plan"]["drops"] == ["lbx"]
    assert chosen["plan"]["weeklyGainPoints"] == 9.0


def test_workflow_horizon_weights_the_expected_benefit(env):
    env.load(_contract())
    # Two-week horizon, declared PRIOR weights [1.0, 0.85]: a 9-point weekly gain
    # totals 9 * 1.0 + 9 * 0.85 = 16.65 over the horizon.
    two = env.stream(dynastyBudget=700, horizonWeeks=2)
    assert two["weeks"] == [9, 10] and two["weekWeights"] == [1.0, 0.85]
    assert two["plan"]["gainByWeekPoints"] == [9.0, 9.0]
    assert two["plan"]["weeklyGainPoints"] == pytest.approx(9.0 * 1.0 + 9.0 * 0.85)


def test_workflow_streaming_keeps_three_quantities_separate(env):
    env.load(_contract())
    plan = env.stream(dynastyBudget=700)["plan"]
    # Expected weekly benefit (points), dynasty effect (board value) and FAAB
    # (dollars) are three differently-named fields, never one number.
    assert plan["weeklyGainPoints"] == 9.0
    assert plan["netDynastyLoss"] == 700.0
    assert plan["dynastyValueChange"]["value"] == 1100.0
    assert plan["faabTotal"] == 55
    assert len({plan["weeklyGainPoints"], plan["netDynastyLoss"], plan["faabTotal"]}) == 3
    # The dynasty-value surfaces never present a points figure and name their scale.
    perfect = env.post(PERFECT)
    assert perfect["valueScale"] == "rankDerivedValue"
    assert not any("point" in key.lower() for key in perfect["plan"])
    adv = env.post(ADVISOR)
    assert adv["valueScale"] == "rankDerivedValue"
    states = {d["id"]: d["state"] for d in adv["methodologyDependencies"]}
    assert states["lineup_objective"] == "dynasty_board_value_not_weekly_projection"


def test_workflow_no_action_alternative_is_available_and_valued(env):
    """Standing pat: every free agent is worse than what the roster has."""
    contract = _contract(values={"wr2": 800})  # nothing rostered is below any free agent
    for row in contract["playersArray"]:
        if row["playerId"] in ("fa1", "fa2", "fa3", "fa4"):
            row["rankDerivedValue"] = 600  # priced (still offered) but worse
    env.load(contract)
    _stub_projections(env.monkeypatch, dict(PTS, fa1=1, fa2=1, fa3=1, fa4=1))
    perfect = env.post(PERFECT)
    assert perfect["plan"]["moves"] == []
    assert perfect["plan"]["netValueGain"] == 0  # NO ACTION is worth exactly 0
    assert perfect["plan"]["totalRecommendedBid"] == 0
    assert perfect["budget"]["remainingAfter"] == perfect["budget"]["balance"] == 60
    assert perfect["solver"]["provenOptimal"] is True
    adv = env.post(ADVISOR)
    assert adv["candidates"], "non-vacuity: the wire is still shown"
    assert all(c["plan"]["status"] != "in_plan" for c in adv["candidates"])
    assert adv["plan"]["summary"]["moves"] == []
    stream = env.stream(dynastyBudget=100_000)
    assert stream["recommendMove"] is False and stream["plan"] is None
    assert stream["noMoveReason"] == "no_move_improves_the_lineup"
    assert stream["baselinePoints"] == [56.0]  # the do-nothing lineup, valued


# =====================================================================
# 2. Identification
# =====================================================================


@pytest.mark.parametrize("url", [ADVISOR, PERFECT, STREAM])
def test_unknown_or_missing_team_is_a_400_never_another_teams_plan(env, url):
    env.load(_contract())
    body = {"week": 9} if url == STREAM else {}
    assert env.post(url, expect=400, teamOwnerId="nobody", **body)["error"] == "unknown_team"
    res = env.client.post(url, json={"leagueKey": "main", **body}, headers=AS)
    assert res.status_code == 400 and res.json()["error"] == "team_required"


def test_anonymous_callers_are_refused_on_every_private_surface(env):
    env.load(_contract())
    for url in (ADVISOR, PERFECT, STREAM, DESK):
        res = env.client.post(url, json={"leagueKey": "main", "teamOwnerId": "me"})
        assert res.status_code == 401, url


def test_unknown_league_is_never_answered_with_this_leagues_roster(env):
    env.load(_contract())
    res = env.client.post(ADVISOR, json={"leagueKey": "elsewhere", "teamOwnerId": "me"}, headers=AS)
    assert res.status_code == 400 and res.json()["error"] == "unknown_league"


# =====================================================================
# 3. FAAB: unknown vs zero vs the balance
# =====================================================================


def test_known_zero_balance_is_zero_on_every_surface(env):
    env.load(_contract(balance=0))
    adv = env.post(ADVISOR)
    assert adv["faab"]["state"] == "known" and adv["faab"]["remaining"] == 0
    assert all(c["faab"]["recommendedBid"] == 0 for c in adv["candidates"])
    assert all(c["faab"]["maxRationalBid"]["value"] == 0 for c in adv["candidates"])
    sug = env.post(SUGGEST)
    assert sug["faabBudget"]["state"] == "known" and sug["faabBudget"]["balance"] == 0
    assert all(c["bid"]["aggressive"] == 0 for items in sug["by_position"].values() for c in items)
    desk = env.post(DESK, addPlayerName="Free LB")
    assert desk["faabBudget"]["state"] == "known" and desk["bids"]["recommended"] == 0
    perfect = env.post(PERFECT)
    assert perfect["budget"]["state"] == "known" and perfect["budget"]["balance"] == 0
    assert perfect["plan"]["totalRecommendedBid"] == 0
    stream = env.stream(dynastyBudget=700)
    assert stream["faab"]["state"] == "known" and stream["faab"]["remaining"] == 0
    # A $0 claim is a real, legal claim: the plan still exists and costs nothing.
    assert stream["recommendMove"] is True and stream["plan"]["faabTotal"] == 0


def test_unknown_balance_is_unknown_never_zero_and_never_the_budget(env):
    env.load(_contract(balance=_OMIT))
    perfect = env.post(PERFECT)
    assert perfect["budget"]["state"] == "unknown" and perfect["budget"]["balance"] is None
    assert perfect["budget"]["remainingAfter"] is None
    assert perfect["plan"]["totalRecommendedBid"] == 0  # no paid claim without a balance
    sug = env.post(SUGGEST)
    assert sug["faabBudget"]["state"] == "unknown" and sug["faabBudget"]["balance"] is None
    assert all(c["bid"] is None for items in sug["by_position"].values() for c in items)
    desk = env.post(DESK, addPlayerName="Free LB")
    assert desk["faabBudget"]["state"] == "unknown" and desk["faabBudget"]["balance"] is None
    assert desk["bids"]["recommended"] is None and desk["faabBudget"]["bidsWithheld"] is True
    adv = env.post(ADVISOR)
    assert adv["faab"]["state"] == "unknown" and adv["faab"]["remaining"] is None
    stream = env.stream(dynastyBudget=100_000)
    assert stream["faab"]["remaining"] is None
    assert stream["faab"]["state"] == "unknown_zero_claims_only"
    assert stream["plan"] is None or stream["plan"]["faabTotal"] == 0  # nothing paid


# W-1: was a strict-xfail finding; fixed by #2160 (unknown/overspent balance contract).
def test_finding_advisor_withholds_bids_when_the_balance_is_unknown(env):
    env.load(_contract(balance=_OMIT))
    adv = env.post(ADVISOR)
    assert adv["faab"]["state"] == "unknown" and adv["candidates"]
    for cand in adv["candidates"]:
        assert cand["faab"]["recommendedBid"] is None
        assert cand["faab"]["maxRationalBid"]["value"] is None


# W-2: was a strict-xfail finding; fixed by #2160 (unknown/overspent balance contract).
def test_finding_streaming_board_withholds_bids_when_the_balance_is_unknown(env):
    env.load(_contract(balance=_OMIT))
    board = env.stream(dynastyBudget=100_000)["streamingBoard"]
    assert board, "non-vacuity: free defenders are still listed"
    assert all(row["bid"] is None for row in board)


# W-3: was a strict-xfail finding; fixed by #2160 (unknown/overspent balance contract).
def test_finding_overspent_balance_is_classified_the_same_on_every_surface(env):
    env.load(_contract(balance=-7))
    assert env.post(PERFECT)["budget"]["state"] == "known"
    assert env.post(DESK, addPlayerName="Free LB")["faabBudget"]["state"] == "known"
    adv = env.post(ADVISOR)
    assert adv["faab"]["state"] == "known" and adv["faab"]["remaining"] == 0
    assert env.stream(dynastyBudget=700)["faab"]["state"] == "known"


# =====================================================================
# 4. Missing value is never a free drop
# =====================================================================


def test_unpriced_roster_player_is_never_a_free_drop_on_any_surface(env):
    # Bench LB loses its board value.  Everything that would have released him
    # for free (he is the weakest starter) must refuse, not treat him as 0.
    env.load(_contract(values={"lbx": None}))
    stream = env.stream(dynastyBudget=0)
    assert stream["recommendMove"] is False and stream["plan"] is None
    assert "lbx" not in {d for plan in _every_streaming_plan(stream) for d in plan["drops"]}
    perfect = env.post(PERFECT)
    assert "Bench LB" not in {m["release"].get("name") for m in perfect["plan"]["moves"]}
    adv = env.post(ADVISOR)
    assert "Bench LB" not in {
        (c["plan"].get("release") or {}).get("name") for c in adv["candidates"]
    }
    # The desk refuses a drop it cannot price (422), rather than charging 0.
    refused = env.post(DESK, expect=422, addPlayerName="Free LB", dropPlayerName="Bench LB")
    assert refused["error"] == "drop_player_unpriced" and refused["dropValueState"] == "unpriced"


def test_priced_control_for_the_unpriced_drop_test_is_actually_droppable(env):
    """Non-vacuity: with a value, the same player IS the drop under a big budget."""
    env.load(_contract())
    assert env.stream(dynastyBudget=700)["plan"]["drops"] == ["lbx"]
    assert (
        env.post(DESK, addPlayerName="Free LB", dropPlayerName="Bench LB")["resolvedDropValue"]
        == 700
    )


def test_unpriced_free_agent_is_never_offered_as_a_priced_claim(env):
    env.load(_contract(values={"fa3": None}))  # Free LB loses his value
    assert "Free LB" not in _advisor_by_name(env.post(ADVISOR))
    assert "Free LB" not in _suggestion_names(env.post(SUGGEST))
    assert "Free LB" not in {m["add"]["name"] for m in env.post(PERFECT)["plan"]["moves"]}
    env.post(DESK, expect=422, addPlayerName="Free LB")


# =====================================================================
# 5. Ineligible positions are never targets
# =====================================================================


def test_offense_only_league_is_never_offered_a_defender(env):
    env.load(_contract(positions=SLOTS_OFFENSE_ONLY))
    assert _suggestion_names(env.post(SUGGEST)) == {"Free TE", "Free WR"}
    assert set(_advisor_by_name(env.post(ADVISOR))) == {"Free TE", "Free WR"}
    perfect = env.post(PERFECT)
    assert {m["add"]["position"] for m in perfect["plan"]["moves"]} <= {"QB", "RB", "WR", "TE"}
    assert perfect["freeAgentExclusions"]["waiverPool"]["position_not_started"] == 2
    stream = env.stream(dynastyBudget=100_000)
    assert stream["recommendMove"] is False and stream["plan"] is None
    assert stream["lineup"]["slots"] == ["QB", "TE", "FLEX"]


# W-4: was a strict-xfail finding; fixed (streaming board filters on started slots).
def test_finding_streaming_board_offers_no_defender_in_an_offense_only_league(env):
    env.load(_contract(positions=SLOTS_OFFENSE_ONLY))
    board = env.stream(dynastyBudget=100_000)["streamingBoard"]
    assert [row["name"] for row in board if not row["excluded"]] == []


def test_a_position_the_lineup_cannot_start_is_not_offered_even_if_priced(env):
    env.load(_contract())  # QB TE DL LB LB DB: no WR / RB / FLEX
    assert "Free WR" not in _advisor_by_name(env.post(ADVISOR))
    assert "Free WR" not in _suggestion_names(env.post(SUGGEST))
    assert "Free WR" not in {m["add"]["name"] for m in env.post(PERFECT)["plan"]["moves"]}
    assert "Free WR" not in {b["name"] for b in env.stream(dynastyBudget=100_000)["streamingBoard"]}


# =====================================================================
# 6. Illegal roster moves are never recommended
# =====================================================================


def test_full_roster_every_surface_names_the_drop(env):
    env.load(_contract())  # 8 of 8
    perfect = env.post(PERFECT)
    assert perfect["plan"]["moves"], "non-vacuity: the plan moves"
    assert all(m["release"]["kind"] == "drop" for m in perfect["plan"]["moves"])
    assert 8 + perfect["plan"]["addCount"] - perfect["plan"]["dropCount"] <= 8
    plan = env.stream(dynastyBudget=700, capacity=3)["plan"]
    assert len(plan["adds"]) <= len(plan["drops"])  # zero open spots
    assert all(c["capacity"]["requiresDrops"] is True for c in env.post(ADVISOR)["candidates"])


def test_open_spots_bound_the_adds_without_a_drop(env):
    env.load(_contract(mine=MINE[:6]))  # 6 of 8: two open spots
    stream = env.stream(dynastyBudget=0, capacity=3)
    assert stream["openSpots"] == 2
    # Free LB fits an open spot: no release, so no dynasty cost, so the ZERO
    # budget allows it (a zero budget is not "never move").
    assert stream["recommendMove"] is True
    assert stream["plan"]["adds"] == ["fa3"] and stream["plan"]["drops"] == []
    assert stream["plan"]["netDynastyLoss"] == 0.0
    plan = env.stream(dynastyBudget=0, capacity=7)["plan"]
    assert len(plan["adds"]) - len(plan["drops"]) <= 2


def test_unknown_roster_limit_never_plans_an_add_without_a_drop(env):
    env.write_registry(drop_roster_size=True)
    env.load(_contract(mine=MINE[:6]))  # would be 2 open spots if the cap were 8
    perfect = env.post(PERFECT)
    assert perfect["capacity"]["rosterLimit"] is None and perfect["capacity"]["state"] == "unknown"
    assert all(m["release"]["kind"] == "drop" for m in perfect["plan"]["moves"])
    stream = env.stream(dynastyBudget=100_000)
    assert stream["openSpots"] is None
    for plan in _every_streaming_plan(stream):
        assert len(plan["drops"]) >= len(plan["adds"])


def test_taxi_occupancy_is_bracketed_and_never_assumed_free(env):
    env.write_registry(taxiSize=2)
    env.load(_contract())  # 8 of 8; two taxi slots whose membership is invisible
    perfect = env.post(PERFECT)
    cap = perfect["capacity"]
    assert cap["state"] == "partial" and cap["taxiSize"] == 2
    assert (cap["taxiOccupiedMin"], cap["taxiOccupiedMax"]) == (0, 2)
    assert all(m["release"]["kind"] == "drop" for m in perfect["plan"]["moves"])
    stream = env.stream(dynastyBudget=700)
    assert stream["openSpots"] == 0  # taxi relief is never assumed
    assert len(stream["plan"]["drops"]) >= len(stream["plan"]["adds"])


def test_protected_player_is_never_a_streaming_or_waiver_drop(env):
    env.load(_contract())
    put = env.client.put(
        "/api/user/trade-protections",
        json={"leagueKey": "main", "untouchables": ["Bench LB"], "nflTeams": []},
        headers=AS,
    )
    assert put.status_code == 200, put.text
    stream = env.stream(dynastyBudget=100_000)
    assert "lbx" not in {d for plan in _every_streaming_plan(stream) for d in plan["drops"]}
    perfect = env.post(PERFECT)
    assert "Bench LB" not in {m["release"].get("name") for m in perfect["plan"]["moves"]}


# =====================================================================
# 7. Dynasty-loss budget defaults to zero unless authorized
# =====================================================================


def test_default_dynasty_budget_is_zero_and_only_an_explicit_request_raises_it(env):
    env.load(_contract())
    cfg = streaming_module.load_streaming_config()
    assert (
        streaming_module.parse_streaming_request({"teamOwnerId": "me"}, cfg)["dynastyBudget"] == 0
    )
    assert env.stream()["request"]["dynastyBudget"] == 0.0
    assert env.stream()["recommendMove"] is False
    assert env.stream(dynastyBudget=700)["request"]["dynastyBudget"] == 700.0
    # A negative budget is a stable 400, never silently clamped.
    assert env.stream(expect=400, dynastyBudget=-1)["error"] == "bad_dynastyBudget"


# =====================================================================
# 8. A bounded search never claims global optimality
# =====================================================================


def test_perfect_waivers_node_limit_is_labelled_not_optimal(env):
    from src.trade import perfect_waivers as pw

    contract = _contract(
        positions=["QB", "TE", "DL", "LB", "LB", "DB", "FLEX", "BN"],
        balance=45,
        mine=MINE[:3],
        extra=EXTRA_LBS,
    )
    env.load(contract)
    env.monkeypatch.setattr(
        pw, "build_perfect_waivers", functools.partial(pw.build_perfect_waivers, node_limit=1)
    )
    solver = env.post(PERFECT)["solver"]
    assert solver["status"] == "node_limit"
    assert solver["provenOptimal"] is False
    assert solver["nodeLimit"] == 1
    # The advisor republishes the same claim; it never upgrades it.
    adv_solver = env.post(ADVISOR)["plan"]["solver"]
    assert adv_solver["provenOptimal"] is False and adv_solver["status"] == "node_limit"


def test_perfect_waivers_complete_search_is_labelled_proven(env):
    env.load(_contract())
    solver = env.post(PERFECT)["solver"]
    assert solver["status"] == "optimal" and solver["provenOptimal"] is True
    assert solver["nodes"] <= solver["nodeLimit"]


def test_streaming_bounded_search_never_claims_a_proof(env):
    env.load(_contract(extra=EXTRA_LBS))
    _stub_projections(
        env.monkeypatch,
        dict(PTS, **{pid: 6 + i for i, (pid, *_rest) in enumerate(EXTRA_LBS)}),
        extra=EXTRA_LBS,
    )
    cfg = streaming_module.load_streaming_config()
    tiny = dataclasses.replace(
        cfg,
        node_limit_single_week=1,
        node_limit_multiweek=1,
        node_limit_curve_row=1,
        request_work_budget=3000,
        min_solve_work=1,
    )
    env.monkeypatch.setattr(streaming_module, "load_streaming_config", lambda *a, **k: tiny)
    stream = env.stream(dynastyBudget=100_000, capacity=3)
    assert stream["solver"]["status"] == "bounded"
    assert stream["solver"]["nodeLimit"] == 1
    assert any("not proven optimal" in n for n in stream["solver"]["notes"])
    # No capacity row that was cut short is called optimal, and the no-move
    # reason says the search stopped rather than asserting nothing helps.
    assert all(r["status"] == "bounded" for r in stream["capacityCurve"] if r["capacity"] >= 1)
    assert stream["noMoveReason"] == "search_incomplete"


def test_streaming_complete_search_is_labelled_optimal(env):
    env.load(_contract())
    assert env.stream()["solver"]["status"] == "optimal"


# =====================================================================
# 9. Surfaces are advice, never execution
# =====================================================================


@pytest.mark.parametrize("url", [ADVISOR, PERFECT, STREAM])
def test_every_decision_surface_is_stamped_advisory(env, url):
    env.load(_contract())
    body = env.stream() if url == STREAM else env.post(url)
    assert body["advisoryOnly"] is True
