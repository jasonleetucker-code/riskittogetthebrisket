"""CW-50 waiver workflow properties, asserted end to end through the real routes.

Owner directive 2026-11-07 Part 5.  Every property is checked against an
INDEPENDENT hand-computed expectation (the eligible set, the balance, the
roster capacity) built from small fixture leagues, through
``POST /api/waiver/perfect`` and ``POST /api/waiver/suggestions``:

(a) only eligible players are ever proposed (unrostered league-wide, not on
    the requesting team, an offered position, priced, corroborated);
(b) a bid never exceeds the team's AVAILABLE balance; $0 stays $0; an unknown
    balance is explicit unknown;
(c) a claim on a full roster names a drop (never an open spot it lacks);
(d) protected players / required starters are never proposed as drops;
(e) standing pat (no move) is available and chosen when nothing beats it;
(f) identical inputs give identical recommendations; display-only body
    fields and input ordering do not change the underlying plan.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import server
from src.api import league_registry, user_kv

PERFECT = "/api/waiver/perfect"
SUGGEST = "/api/waiver/suggestions"
AS = {"x-test-user": "alice"}

_OMIT = object()


def _row(pid, name, pos, value, sources=3):
    return {
        "playerId": pid,
        "displayName": name,
        "canonicalName": name,
        "legacyRef": name,
        "position": pos,
        "team": "XX",
        "rankDerivedValue": value,
        "sourceCount": sources,
        "assetClass": "offense",
    }


def _team(owner, rid, players, remaining, budget=100):
    """``players`` is a list of (playerId, name); ``remaining=_OMIT`` omits the balance."""
    t = {
        "ownerId": owner,
        "name": owner.title(),
        "roster_id": rid,
        "players": [n for _p, n in players],
        "playerIds": [p for p, _n in players],
        "faabBudget": budget,
    }
    if remaining is not _OMIT:
        t["faabRemaining"] = remaining
    return t


def _build_contract(my_players, my_remaining, rows, rival_players=()):
    return {
        "meta": {"leagueKey": "main"},
        "playersArray": rows,
        "sleeper": {
            "rosterPositions": ["QB", "TE", "BN", "BN", "BN"],
            "teams": [
                _team("me", 1, my_players, my_remaining),
                _team("them", 2, list(rival_players), 100),
            ],
        },
    }


# Hand-computed pool membership (value floor 500, >= 2 sources, offered
# positions only, unrostered anywhere in the league).
ELIGIBLE_FAS = {"Free TE", "Free WR", "Free RB"}
JUNK_FAS = {"Free Kicker", "Cheap WR", "Lone Source WR"}


def _board():
    return [
        _row("qb1", "Star QB", "QB", 8000),
        _row("te1", "Weak TE", "TE", 900),
        _row("wr1", "Bench WR", "WR", 3000),
        _row("wr2", "Deep WR", "WR", 400),
        _row("rq", "Rival QB", "QB", 7000),
        _row("rw", "Rival WR", "WR", 6500),
        _row("fa1", "Free TE", "TE", 2600),
        _row("fa2", "Free WR", "WR", 2500),
        _row("fa3", "Free RB", "RB", 2400),
        _row("k1", "Free Kicker", "K", 3000),
        _row("c1", "Cheap WR", "WR", 300),
        _row("s1", "Lone Source WR", "WR", 2000, sources=1),
    ]


MINE_FULL = [("qb1", "Star QB"), ("te1", "Weak TE"), ("wr1", "Bench WR"), ("wr2", "Deep WR")]
RIVAL = [("rq", "Rival QB"), ("rw", "Rival WR")]


@pytest.fixture()
def env(tmp_path: Path, monkeypatch):
    registry = tmp_path / "registry.json"
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
                        "rosterSettings": {"teamCount": 2, "rosterSize": 4},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("LEAGUE_REGISTRY_PATH", str(registry))
    league_registry.reload_registry()
    monkeypatch.setattr(user_kv, "USER_KV_PATH", tmp_path / "user_kv.sqlite")
    user_kv._SETUP_DONE.clear()

    def _session(request):
        user = (getattr(request, "headers", None) or {}).get("x-test-user")
        return {"username": user, "auth_method": "password"} if user else None

    monkeypatch.setattr(server, "_get_auth_session", _session)
    monkeypatch.setattr(server._sleeper_overlay, "fetch_sleeper_teams_overlay", lambda **_kw: None)
    # No ``with``: the lifespan would load the real board over these fixtures.
    client = TestClient(server.app, raise_server_exceptions=True)

    def load(contract):
        monkeypatch.setattr(server, "latest_contract_data", contract)
        server._PERFECT_WAIVERS_CACHE.clear()
        return contract

    def perfect(**extra):
        res = client.post(
            PERFECT, json={"leagueKey": "main", "teamOwnerId": "me", **extra}, headers=AS
        )
        assert res.status_code == 200, res.text
        return res.json()

    def suggest(**extra):
        res = client.post(
            SUGGEST, json={"leagueKey": "main", "teamOwnerId": "me", **extra}, headers=AS
        )
        assert res.status_code == 200, res.text
        return res.json()

    yield SimpleNamespace(client=client, load=load, perfect=perfect, suggest=suggest)
    league_registry.reload_registry()


def _pool_names(payload):
    return {c["name"] for items in payload["by_position"].values() for c in items}


def _pool_bids(payload):
    out = []
    for items in payload["by_position"].values():
        for c in items:
            out.extend(c["bid"][k] for k in ("aggressive", "reasonable", "lowball"))
    return out


def _moves(payload):
    return payload["plan"]["moves"]


def _protect(env, names):
    put = env.client.put(
        "/api/user/trade-protections",
        json={"leagueKey": "main", "untouchables": sorted(names), "nflTeams": []},
        headers=AS,
    )
    assert put.status_code == 200, put.text


# -- (a) eligibility ------------------------------------------------------


def test_a_suggestions_pool_is_exactly_the_hand_computed_eligible_set(env):
    env.load(_build_contract(MINE_FULL, 60, _board(), RIVAL))
    # Not "Bench WR"/"Star QB" (mine), not "Rival *" (rival's), no K, no
    # sub-floor value, no single-source row.
    assert _pool_names(env.suggest()) == ELIGIBLE_FAS


def test_a_perfect_plan_adds_only_eligible_players(env):
    env.load(_build_contract(MINE_FULL, 60, _board(), RIVAL))
    added = {m["add"]["name"] for m in _moves(env.perfect())}
    assert added, "fixture has clearly better free agents; the plan must move"
    assert added <= ELIGIBLE_FAS
    assert not added & ({n for _p, n in MINE_FULL} | {n for _p, n in RIVAL} | JUNK_FAS)


def test_a_rostered_by_id_only_never_proposed_by_perfect(env):
    contract = _build_contract(MINE_FULL, 60, _board(), RIVAL)
    contract["sleeper"]["teams"][1]["playerIds"].append("fa2")  # no name entry
    env.load(contract)
    assert "Free WR" not in {m["add"]["name"] for m in _moves(env.perfect())}


@pytest.mark.xfail(
    strict=True,
    reason=(
        "src/trade/waiver.py:236-252 rostered_name_set (used at find_waiver_targets) "
        "keys ownership on NAMES only; a player rostered by playerId only is offered "
        "by /api/waiver/suggestions as a free agent. /api/waiver/perfect re-checks "
        "ids in perfect_waivers.free_agent_candidates."
    ),
)
def test_a_suggestions_excludes_player_rostered_by_id_only(env):
    contract = _build_contract(MINE_FULL, 60, _board(), RIVAL)
    contract["sleeper"]["teams"][1]["playerIds"].append("fa2")
    env.load(contract)
    assert "Free WR" not in _pool_names(env.suggest())


def test_a_duplicate_player_ids_do_not_double_propose(env):
    rows = _board() + [_row("fa2", "Free WR", "WR", 2500)]  # exact duplicate row
    env.load(_build_contract(MINE_FULL, 60, rows, RIVAL))
    adds = [m["add"]["playerId"] for m in _moves(env.perfect())]
    assert len(adds) == len(set(adds))


# -- (b) balance ----------------------------------------------------------


@pytest.mark.parametrize("balance", [0, 1, 3, 60])
def test_b_no_bid_exceeds_available_balance(env, balance):
    env.load(_build_contract(MINE_FULL, balance, _board(), RIVAL))
    assert max(_pool_bids(env.suggest())) <= balance
    payload = env.perfect()
    assert payload["budget"]["state"] == "known"
    assert payload["budget"]["balance"] == balance
    for m in _moves(payload):
        assert 0 <= m["add"]["bid"]["recommended"] <= balance
    assert 0 <= payload["plan"]["totalRecommendedBid"] <= balance
    assert payload["budget"]["remainingAfter"] >= 0


def test_b_exhausted_budget_is_zero_never_negative(env):
    env.load(_build_contract(MINE_FULL, 0, _board(), RIVAL))
    assert set(_pool_bids(env.suggest())) == {0}
    assert env.perfect()["plan"]["totalRecommendedBid"] == 0


def test_b_overspent_negative_balance_never_bids(env):
    env.load(_build_contract(MINE_FULL, -7, _board(), RIVAL))
    assert set(_pool_bids(env.suggest())) == {0}
    payload = env.perfect()
    assert payload["plan"]["totalRecommendedBid"] == 0
    # A negative balance is not a known spendable budget either.
    assert payload["budget"]["state"] == "unknown"


def test_b_balance_below_engine_ceiling_is_the_cap(env):
    env.load(_build_contract(MINE_FULL, 2, _board(), RIVAL))
    bids = _pool_bids(env.suggest())
    assert bids and max(bids) <= 2 and all(isinstance(b, int) for b in bids)


def test_b_explicit_request_balance_caps_even_when_roster_says_more(env):
    env.load(_build_contract(MINE_FULL, 60, _board(), RIVAL))
    assert max(_pool_bids(env.suggest(faabRemaining=4))) <= 4


def test_b_unknown_balance_is_explicit_unknown_in_perfect_plan(env):
    env.load(_build_contract(MINE_FULL, _OMIT, _board(), RIVAL))
    payload = env.perfect()
    assert payload["budget"]["state"] == "unknown"
    assert payload["budget"]["balance"] is None
    assert payload["budget"]["remainingAfter"] is None


@pytest.mark.xfail(
    strict=True,
    reason=(
        "src/trade/waiver.py:494-499 — an UNKNOWN balance (own team row without "
        "faabRemaining) falls back to cap = league budget (default 100, also "
        "server.py _waiver_engine_inputs) and bids are emitted as if capped to a "
        "known $100; the suggestions response has no budget-state field."
    ),
)
def test_b_suggestions_unknown_balance_is_not_presented_as_a_known_budget(env):
    env.load(_build_contract(MINE_FULL, _OMIT, _board(), RIVAL))
    body = env.suggest()
    state = body.get("budgetState") or (body.get("budget") or {}).get("state")
    assert state == "unknown"


# -- (c) roster capacity --------------------------------------------------


def test_c_claim_on_full_roster_names_a_drop(env):
    env.load(_build_contract(MINE_FULL, 60, _board(), RIVAL))  # 4 of 4
    payload = env.perfect()
    assert payload["capacity"]["rosterCount"] == 4 and payload["capacity"]["rosterLimit"] == 4
    assert payload["capacity"]["openSpotsPlanned"] == 0
    moves = _moves(payload)
    assert moves
    assert all(m["release"]["kind"] == "drop" for m in moves)
    assert 4 + payload["plan"]["addCount"] - payload["plan"]["dropCount"] <= 4


def test_c_open_spots_bound_the_number_of_open_spot_claims(env):
    env.load(_build_contract(MINE_FULL[:2], 60, _board(), RIVAL))  # 2 of 4
    payload = env.perfect()
    assert payload["capacity"]["openSpotsPlanned"] == 2
    opens = [m for m in _moves(payload) if m["release"]["kind"] == "openSpot"]
    assert len(opens) <= 2
    assert 2 + payload["plan"]["addCount"] - payload["plan"]["dropCount"] <= 4


def test_c_full_roster_all_protected_is_refused_not_overfilled(env):
    env.load(_build_contract(MINE_FULL, 60, _board(), RIVAL))
    _protect(env, [n for _p, n in MINE_FULL])
    payload = env.perfect()
    assert _moves(payload) == []
    assert payload["plan"]["addCount"] == 0 and payload["plan"]["dropCount"] == 0
    assert payload["plan"]["totalRecommendedBid"] == 0


def test_c_unknown_roster_limit_never_plans_an_add_without_a_drop(env, monkeypatch):
    monkeypatch.setattr(
        server._league_registry, "get_league_roster_settings", lambda _key: {"teamCount": 2}
    )
    env.load(_build_contract(MINE_FULL[:2], 60, _board(), RIVAL))
    payload = env.perfect()
    assert payload["capacity"]["rosterLimit"] is None
    assert payload["capacity"]["state"] == "unknown"
    assert all(m["release"]["kind"] == "drop" for m in _moves(payload))


# -- (d) protected players are never drops --------------------------------


def test_d_saved_protection_never_proposed_as_drop(env):
    env.load(_build_contract(MINE_FULL, 60, _board(), RIVAL))
    protected = {"Weak TE", "Deep WR"}
    _protect(env, protected)
    payload = env.perfect()
    assert not {m["release"].get("name") for m in _moves(payload)} & protected
    assert {r["name"] for r in payload["constraints"]["protectedOnRoster"]} == protected


def test_d_sole_starter_is_never_dropped_without_a_replacement(env):
    mine = [("qb1", "Star QB"), ("wr2", "Deep WR")]  # the only QB; no QB on the wire
    env.load(_build_contract(mine, 60, _board(), RIVAL))
    released = {m["release"].get("name") for m in _moves(env.perfect())}
    assert "Star QB" not in released


def test_d_unpriced_rostered_player_is_never_dropped(env):
    rows = _board() + [_row("ghost", "Unpriced Guy", "WR", None)]
    mine = [("qb1", "Star QB"), ("te1", "Weak TE"), ("wr1", "Bench WR"), ("ghost", "Unpriced Guy")]
    env.load(_build_contract(mine, 60, rows, RIVAL))
    released = {m["release"].get("name") for m in _moves(env.perfect())}
    assert "Unpriced Guy" not in released


# -- (e) no-transaction alternative ---------------------------------------


def test_e_stand_pat_when_no_claim_beats_the_roster(env):
    rows = [
        _row("qb1", "Star QB", "QB", 9000),
        _row("te1", "Star TE", "TE", 8000),
        _row("wr1", "Star WR", "WR", 7500),
        _row("wr2", "Star WR2", "WR", 7400),
        _row("rq", "Rival QB", "QB", 7000),
        _row("fa1", "Free TE", "TE", 600),
        _row("fa2", "Free WR", "WR", 700),
    ]
    mine = [("qb1", "Star QB"), ("te1", "Star TE"), ("wr1", "Star WR"), ("wr2", "Star WR2")]
    env.load(_build_contract(mine, 60, rows, [("rq", "Rival QB")]))
    payload = env.perfect()
    assert _moves(payload) == []
    assert payload["plan"]["addCount"] == 0 and payload["plan"]["totalRecommendedBid"] == 0
    assert payload["plan"]["netValueGain"] == 0
    assert payload["solver"]["provenOptimal"] is True


def test_e_empty_wire_is_stand_pat(env):
    rows = [r for r in _board() if r["displayName"] not in ELIGIBLE_FAS | JUNK_FAS]
    env.load(_build_contract(MINE_FULL, 60, rows, RIVAL))
    payload = env.perfect()
    assert _moves(payload) == []
    assert payload["solver"]["freeAgentsConsidered"] == 0


def test_e_every_recommended_move_beats_standing_pat(env):
    env.load(_build_contract(MINE_FULL, 60, _board(), RIVAL))
    payload = env.perfect()
    assert payload["plan"]["netValueGain"] > 0
    assert all(m["gain"] > 0 and m["standsAlone"] for m in _moves(payload))


def test_e_zero_balance_plan_spends_nothing(env):
    env.load(_build_contract(MINE_FULL, 0, _board(), RIVAL))
    payload = env.perfect()
    assert payload["plan"]["totalRecommendedBid"] == 0
    assert payload["budget"]["remainingAfter"] == 0


# -- (f) determinism / display-only fields --------------------------------


def _strip(payload):
    p = copy.deepcopy(payload)
    p.pop("rostersAsOf", None)
    return p


def test_f_identical_inputs_identical_plan_without_the_cache(env):
    env.load(_build_contract(MINE_FULL, 60, _board(), RIVAL))
    first = _strip(env.perfect())
    server._PERFECT_WAIVERS_CACHE.clear()
    assert _strip(env.perfect()) == first


def test_f_display_only_body_fields_do_not_change_the_plan(env):
    env.load(_build_contract(MINE_FULL, 60, _board(), RIVAL))
    base = _strip(env.perfect())
    server._PERFECT_WAIVERS_CACHE.clear()
    noisy = _strip(
        env.perfect(position="WR", sortBy="value", search="free", limit=1, hideRookies=True)
    )
    assert noisy == base


def test_f_input_ordering_does_not_change_the_plan(env):
    contract = _build_contract(MINE_FULL, 60, _board(), RIVAL)
    env.load(contract)
    base = _strip(env.perfect())
    shuffled = copy.deepcopy(contract)
    shuffled["playersArray"].reverse()
    shuffled["sleeper"]["teams"].reverse()
    env.load(shuffled)
    other = _strip(env.perfect())
    for key in ("plan", "budget", "capacity", "constraints"):
        assert other[key] == base[key], key


def test_f_suggestions_display_fields_do_not_change_bids(env):
    env.load(_build_contract(MINE_FULL, 60, _board(), RIVAL))
    base = env.suggest()
    assert env.suggest(sortBy="value", search="x", limit=1, viewMode="compact") == base
