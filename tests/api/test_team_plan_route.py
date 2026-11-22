"""``GET /api/team/plan`` — flag, auth, league routing, privacy, warm-only reads.

The composer's own rules are pinned in ``tests/api/test_team_plan.py``; this
suite pins the route: the owner-held flag, the private API gate, the
``leagueKey`` rules (scope, mismatch 503), that the requester's protections
bind only their own team and never leak, and that every cache read is
warm-only — nothing is written to a shared cache and ``latest_contract_data``
is never mutated.
"""

from __future__ import annotations

import json
import time
from collections import OrderedDict

import pytest
from fastapi.testclient import TestClient

import server
from src.api import feature_flags, gameplan, league_registry, user_kv
from src.trade.constraints import resolve_constraints

URL = "/api/team/plan"
# Captured before any fixture patches them.
_REAL_IS_ENABLED = feature_flags.is_enabled
_REAL_SUGGESTIONS = server._trade_suggestions_from_contract
OWNER = {"x-test-user": "alice", "x-test-sleeper": "o0"}
OTHER = {"x-test-user": "bob", "x-test-sleeper": "o1"}
_SLOTS = {"QB": 1, "RB": 2, "WR": 3, "TE": 1, "FLEX": 1, "SFLEX": 1}


def _contract(*, league_key: str = "dynasty_main", roster_source: str = "live") -> dict:
    """A small real-shaped contract: four teams, a board with ages."""
    rows, teams, positions = [], [], {}
    for ti in range(4):
        owner, names = f"o{ti}", []
        for pos in ("QB", "RB", "WR", "TE"):
            for i in range(4):
                name = f"{owner}_{pos}{i}"
                names.append(name)
                positions[name] = pos
                rows.append(
                    {
                        "playerId": f"id_{name}",
                        "canonicalName": name,
                        "displayName": name,
                        "position": pos,
                        "team": "MIN" if pos == "QB" else "DET",
                        "rankDerivedValue": round((900 - i * 90) * (1 + ti * 0.1), 2),
                        # o0 is the oldest roster, so its rooms read old.
                        "age": 30.0 + i if ti == 0 else 22.0 + i,
                    }
                )
        teams.append(
            {
                "ownerId": owner,
                "name": f"Team {owner}",
                "roster_id": ti + 1,
                "players": names,
                "playerIds": [f"id_{n}" for n in names],
                "pickOwnershipState": "observed",
                "pickOwnershipReason": None,
            }
        )
    fetched = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
    return {
        "meta": {"leagueKey": league_key},
        "generatedAt": "gen-1",
        "scrapeTimestamp": "scrape-1",
        "playersArray": rows,
        "sleeper": {
            "rosterPositions": ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "SUPER_FLEX"],
            "positions": positions,
            "teams": teams,
            "rosterSource": roster_source,
            "rosterFetchedAt": fetched,
        },
    }


class _Posture:
    def __init__(self, label: str):
        self.label = label

    def to_dict(self) -> dict:
        return {"label": self.label, "isVerdict": False, "parameterStatus": "PRIOR"}


def _suggestions_payload() -> dict:
    return {
        "sellHigh": [
            {
                "type": "sell_high",
                "give": [{"name": "o0_RB3"}],
                "receive": [{"name": "o1_WR1"}],
                "gap": 10,
                "fairness": "even",
                "rationale": "sell surplus",
                "confidence": "medium",
            }
        ],
        "buyLow": [],
        "consolidation": [],
        "positionalUpgrades": [],
        "metadata": {"assetPoolSize": 64, "boardTopNFilter": 150},
        "warnings": [],
    }


def _perfect_payload() -> dict:
    return {
        "advisoryOnly": True,
        "plan": {
            "moves": [
                {
                    "add": {"playerId": "fa1", "name": "FA One", "position": "WR", "bid": {}},
                    "release": {"kind": "openSpot"},
                    "gain": 120.0,
                    "relativeGap": 0.2,
                    "material": True,
                    "standsAlone": True,
                }
            ]
        },
        "solver": {"status": "optimal", "provenOptimal": True},
        "stopRule": {"stopBandClass": "PRIOR"},
        "budget": {"state": "known"},
        "rosterSource": "contract",
        "rostersAsOf": None,
    }


def _draft_capital_payload() -> dict:
    return {
        "teamTotals": [
            {"team": f"Team o{i}", "auctionDollars": 300, "rosterId": i + 1, "ownerId": f"o{i}"}
            for i in range(4)
        ],
        "allYearsTeamTotals": [],
        "teamTotalsState": "available",
        "upcomingDraftYear": 2027,
    }


@pytest.fixture()
def env(tmp_path, monkeypatch):
    registry = tmp_path / "registry.json"
    registry.write_text(
        json.dumps(
            {
                "defaultLeagueKey": "dynasty_main",
                "leagues": [
                    {
                        "key": "dynasty_main",
                        "displayName": "Main",
                        "sleeperLeagueId": "TPMAIN",
                        "scoringProfile": "prof_a",
                        "active": True,
                        "rosterSettings": {"teamCount": 4, "rosterSize": 20, "starters": _SLOTS},
                    },
                    {
                        "key": "dynasty_new",
                        "displayName": "New",
                        "sleeperLeagueId": "TPNEW",
                        "scoringProfile": "prof_a",
                        "active": True,
                        "rosterSettings": {"teamCount": 4, "starters": _SLOTS},
                    },
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
        headers = getattr(request, "headers", None) or {}
        user = headers.get("x-test-user")
        if not user:
            return None
        return {"username": user, "sleeper_user_id": headers.get("x-test-sleeper") or ""}

    monkeypatch.setattr(server, "_get_auth_session", _session)
    contract = _contract()
    monkeypatch.setattr(server, "latest_contract_data", contract)

    # Shared caches: fresh objects per test (monkeypatch restores the originals).
    monkeypatch.setattr(gameplan, "_BUNDLE_CACHE", {})
    monkeypatch.setattr(gameplan, "_TEAM_CACHE", OrderedDict())
    monkeypatch.setattr(server, "_PERFECT_WAIVERS_CACHE", {})
    monkeypatch.setattr(server, "_DRAFT_CAPITAL_CACHE", {})
    monkeypatch.setattr(server._sleeper_overlay, "peek_sleeper_teams_overlay", lambda lid: None)

    posture_state = {"postures": None}

    def _postures(league_key, scoring_profile, contract, *, build_if_missing=True, **_kw):
        assert build_if_missing is False, "the plan must never build the league bundle"
        if posture_state["postures"] is None:
            raise gameplan.GameplanUnavailable("league_bundle_not_warm", "cold")
        return posture_state["postures"], {"bundleFreshness": "last_computed", "notes": []}

    monkeypatch.setattr(gameplan, "league_competitive_postures", _postures)

    calls: dict[str, list] = {"suggestions": [], "constraints": []}
    protected = resolve_constraints(persistent={"untouchables": ["o0_QB0"], "nflTeams": ["MIN"]})

    def _constraints(request, contract, league_cfg, *, surface, refinement=None):
        calls["constraints"].append(surface)
        return protected

    def _suggestions(contract, league_cfg, roster, **kwargs):
        calls["suggestions"].append({"roster": list(roster), **kwargs})
        return _suggestions_payload()

    monkeypatch.setattr(server, "_constraints_for_request", _constraints)
    monkeypatch.setattr(server, "_trade_suggestions_from_contract", _suggestions)

    real = feature_flags.is_enabled
    flag = {"on": True}
    monkeypatch.setattr(
        feature_flags,
        "is_enabled",
        lambda name, *a, **k: flag["on"] if name == "team_advisor_plan" else real(name, *a, **k),
    )
    client = TestClient(server.app, raise_server_exceptions=True)
    yield type(
        "E",
        (),
        {
            "client": client,
            "flag": flag,
            "contract": contract,
            "calls": calls,
            "protected": protected,
            "posture": posture_state,
            "monkeypatch": monkeypatch,
        },
    )
    league_registry.reload_registry()


def _seed_warm(env, *, owner: str = "o0", waiver_constraints=None):
    """Warm every cache the plan reads, the way the owning routes would."""
    env.posture["postures"] = {f"o{i}": _Posture("PUSH") for i in range(4)}
    gameplan._BUNDLE_CACHE["dynasty_main"] = ("stamp-1", object())
    gameplan._TEAM_CACHE["\x00".join(["dynasty_main", "stamp-1", owner, "", ""])] = (
        "stamp-1",
        {
            "targetPlayers": [
                {
                    "playerId": "id_o2_WR0",
                    "name": "o2_WR0",
                    "position": "WR",
                    "recommended": True,
                    "reason": "corroborated by lineup_fit",
                    "confidence": 0.5,
                },
                {"playerId": "x", "name": "x", "position": "TE", "recommended": False},
            ],
            "coverage": {},
            "limitations": {},
            "timing": {"sourceStamp": "stamp-1"},
        },
    )
    keyed = waiver_constraints if waiver_constraints is not None else env.protected
    key = server._perfect_waivers_cache_key(
        "dynasty_main", owner, env.contract, env.contract["sleeper"]["teams"], keyed
    )
    server._PERFECT_WAIVERS_CACHE[key] = (time.time(), _perfect_payload())
    server._DRAFT_CAPITAL_CACHE["dynasty_main"] = (time.time(), _draft_capital_payload())


# ── Flag and auth ────────────────────────────────────────────────────


def test_not_a_public_api_path():
    assert not server._is_public_api_path(URL)


def test_flag_off_is_503_feature_disabled(env):
    env.flag["on"] = False
    res = env.client.get(URL, headers=OWNER)
    assert res.status_code == 503
    assert res.json() == {"error": "feature_disabled", "flag": "team_advisor_plan"}
    assert res.headers["cache-control"] == "private, no-store"
    assert env.calls["suggestions"] == []


def test_flag_off_by_default_without_any_override(env, monkeypatch):
    """The registry default alone answers 503: nothing in the test env turns it on."""
    monkeypatch.setattr(feature_flags, "is_enabled", _REAL_IS_ENABLED)
    monkeypatch.delenv("RISKIT_FEATURE_TEAM_ADVISOR_PLAN", raising=False)
    feature_flags.reload()
    res = env.client.get(URL, headers=OWNER)
    assert res.status_code == 503
    assert res.json() == {"error": "feature_disabled", "flag": "team_advisor_plan"}


@pytest.mark.parametrize("flag_on", [True, False])
def test_anonymous_is_401(env, flag_on):
    env.flag["on"] = flag_on
    res = env.client.get(URL)
    assert res.status_code == 401
    assert res.json()["error"] == "auth_required"


# ── League routing ───────────────────────────────────────────────────


def test_out_of_scope_league_is_an_explicit_unavailable(env):
    res = env.client.get(URL, params={"leagueKey": "dynasty_new"}, headers=OWNER)
    assert res.status_code == 200
    body = res.json()
    assert body["available"] is False and body["unavailableReason"] == "league_not_in_scope"
    assert env.calls["suggestions"] == []


def test_unknown_league_is_400(env):
    res = env.client.get(URL, params={"leagueKey": "nope"}, headers=OWNER)
    assert res.status_code == 400
    assert res.json()["error"] == "unknown_league"


def test_loaded_contract_for_another_league_is_503(env, monkeypatch):
    monkeypatch.setattr(server, "latest_contract_data", _contract(league_key="dynasty_new"))
    res = env.client.get(URL, params={"leagueKey": "dynasty_main"}, headers=OWNER)
    assert res.status_code == 503
    body = res.json()
    assert body["error"] == "data_not_ready" and body["leagueKey"] == "dynasty_main"


def test_no_contract_is_503(env, monkeypatch):
    monkeypatch.setattr(server, "latest_contract_data", None)
    res = env.client.get(URL, headers=OWNER)
    assert res.status_code == 503 and res.json()["error"] == "data_not_ready"


def test_unknown_team_is_404_and_no_team_is_400(env):
    res = env.client.get(URL, params={"team": "ghost"}, headers=OWNER)
    assert res.status_code == 404 and res.json()["error"] == "team_not_found"
    res = env.client.get(URL, headers={"x-test-user": "carol"})
    assert res.status_code == 400 and res.json()["error"] == "team_required"


# ── The composed plan ────────────────────────────────────────────────


def test_composed_plan_from_warm_owners(env):
    _seed_warm(env)
    res = env.client.get(URL, headers=OWNER)
    assert res.status_code == 200
    assert res.headers["cache-control"] == "private, no-store"
    body = res.json()
    assert body["leagueKey"] == "dynasty_main" and body["team"]["ownerId"] == "o0"
    assert body["requesterOwnsTeam"] is True
    assert body["posture"]["available"] is True
    assert body["posture"]["posture"]["label"] == "PUSH"
    assert body["teamStrength"]["available"] is True
    assert body["teamWeakness"]["owner"] == "src/roster_intel/weakness.py"
    sections = body["sections"]
    for key in ("buyTargets", "sellHigh", "waivers", "agingAssets"):
        assert sections[key]["available"] is True, key
    assert body["draftCapital"]["upcomingClass"]["ownerId"] == "o0"
    assert body["draftCapital"]["freshness"] == "current"
    kinds = [a["kind"] for a in body["actions"]]
    assert kinds[:3] == ["buy_target", "sell_high", "waiver_move"]
    assert "aging_asset_risk" in kinds  # o0 is the old roster
    assert body["planState"] == "actions"
    assert body["rosterFreshness"]["state"] == "current"
    assert body["valuationMode"] == "market"
    assert set(body["timing"]) >= {"computeMs", "warmReadsMs", "suggestionsMs"}
    # The suggestion engine ran on THIS team's exact roster, with its protections.
    call = env.calls["suggestions"][0]
    assert call["roster"] == env.contract["sleeper"]["teams"][0]["players"]
    assert call["constraints"] is env.protected
    assert body["protections"]["applied"] is True and body["protections"]["active"] is True


def test_cold_owners_are_explicit_never_empty(env):
    res = env.client.get(URL, headers=OWNER)
    assert res.status_code == 200
    body = res.json()
    assert body["posture"]["unavailableReason"] == "league_bundle_not_warm"
    assert body["sections"]["buyTargets"]["unavailableReason"] == "gameplan_targets_not_warm"
    assert body["sections"]["waivers"]["unavailableReason"] == "perfect_waivers_not_warm"
    assert body["draftCapital"]["unavailableReason"] == "draft_capital_not_warm"
    assert body["completeness"]["complete"] is False
    assert body["planState"] != "do_nothing"


def test_stale_rosters_are_surfaced(env, monkeypatch):
    stale = _contract(roster_source="last_good")
    monkeypatch.setattr(server, "latest_contract_data", stale)
    body = env.client.get(URL, headers=OWNER).json()
    assert body["rosterFreshness"]["state"] == "stale"
    assert any("rosters are stale" in w for w in body["warnings"])


# ── Privacy ──────────────────────────────────────────────────────────


def test_non_owner_gets_no_protections_and_never_the_owners_plan(env):
    """bob (o1) reads o0's plan: bob's protections are not applied to o0's
    team, nobody's protections are revealed, and a Perfect Waivers entry
    shaped by o0's owner's protections cannot be served to him."""
    _seed_warm(env)  # waiver entry keyed by the OWNER's protections
    res = env.client.get(URL, params={"team": "o0"}, headers=OTHER)
    assert res.status_code == 200
    body = res.json()
    assert body["requesterOwnsTeam"] is False
    assert body["protections"] == {
        "applied": False,
        "reason": "requester_does_not_own_team",
        "owner": "src/trade/constraints.py",
    }
    assert env.calls["constraints"] == []
    assert env.calls["suggestions"][0]["constraints"] is None
    assert body["sections"]["waivers"]["unavailableReason"] == "perfect_waivers_not_warm"
    text = json.dumps(body["protections"])
    assert "o0_QB0" not in text and "MIN" not in text


def test_non_owner_reads_the_unprotected_waiver_plan_only(env):
    _seed_warm(env, waiver_constraints=resolve_constraints())
    body = env.client.get(URL, params={"team": "o0"}, headers=OTHER).json()
    assert body["sections"]["waivers"]["available"] is True
    owner_body = env.client.get(URL, headers=OWNER).json()
    # The owner's protections are different, so the unprotected entry is not theirs.
    assert owner_body["sections"]["waivers"]["unavailableReason"] == "perfect_waivers_not_warm"


# ── Warm-only: nothing written, nothing mutated ──────────────────────


def _cache_state():
    return json.dumps(
        {
            "bundle": sorted(gameplan._BUNDLE_CACHE),
            "team": list(gameplan._TEAM_CACHE),
            "pw": [(k, v[0]) for k, v in server._PERFECT_WAIVERS_CACHE.items()],
            "dc": [(k, v[0]) for k, v in server._DRAFT_CAPITAL_CACHE.items()],
        },
        default=str,
    )


def test_nothing_writes_shared_caches_or_mutates_the_contract(env):
    _seed_warm(env)
    # An expired Perfect Waivers entry stays put (a peek never evicts).
    server._PERFECT_WAIVERS_CACHE["expired"] = (0.0, {"plan": {"moves": []}})
    contract_before = json.dumps(env.contract, sort_keys=True, default=str)
    caches_before = _cache_state()
    for headers in (OWNER, OTHER):
        assert env.client.get(URL, params={"team": "o0"}, headers=headers).status_code == 200
    assert _cache_state() == caches_before
    assert json.dumps(server.latest_contract_data, sort_keys=True, default=str) == (contract_before)
    assert server.latest_contract_data is env.contract


def test_cached_team_gameplan_is_warm_only_and_order_preserving(env):
    assert gameplan.cached_team_gameplan("dynasty_main", "o0") is None
    _seed_warm(env)
    gameplan._TEAM_CACHE["dynasty_main\x00stamp-1\x00o1\x00\x00"] = ("stamp-1", {"x": 1})
    order = list(gameplan._TEAM_CACHE)
    assert gameplan.cached_team_gameplan("dynasty_main", "o0")["targetPlayers"]
    assert list(gameplan._TEAM_CACHE) == order
    # A team payload from a superseded bundle stamp is not served.
    gameplan._BUNDLE_CACHE["dynasty_main"] = ("stamp-2", object())
    assert gameplan.cached_team_gameplan("dynasty_main", "o0") is None


def test_perfect_waivers_peek_neither_reorders_nor_evicts(env):
    server._PERFECT_WAIVERS_CACHE["a"] = (time.time(), {"a": 1})
    server._PERFECT_WAIVERS_CACHE["b"] = (time.time(), {"b": 1})
    server._PERFECT_WAIVERS_CACHE["old"] = (0.0, {"old": 1})
    assert server._perfect_waivers_cache_peek("a") == {"a": 1}
    assert server._perfect_waivers_cache_peek("old") is None
    assert server._perfect_waivers_cache_peek("") is None
    assert list(server._PERFECT_WAIVERS_CACHE) == ["a", "b", "old"]


def test_draft_capital_read_follows_the_routes_cache_rules(env):
    read = server._team_plan_draft_capital_read("dynasty_main")
    assert read.reason == "draft_capital_not_warm"
    server._DRAFT_CAPITAL_CACHE["dynasty_main"] = (time.time(), _draft_capital_payload())
    assert server._team_plan_draft_capital_read("dynasty_main").freshness == "current"
    swr = time.time() - server._DRAFT_CAPITAL_TTL_SEC - 1.0
    server._DRAFT_CAPITAL_CACHE["dynasty_main"] = (swr, _draft_capital_payload())
    assert server._team_plan_draft_capital_read("dynasty_main").freshness == (
        "stale_while_revalidate"
    )
    server._DRAFT_CAPITAL_CACHE["dynasty_main"] = (0.0, _draft_capital_payload())
    assert server._team_plan_draft_capital_read("dynasty_main").reason == "draft_capital_not_warm"


def test_overlay_peek_never_fetches_or_writes(monkeypatch):
    from src.api import sleeper_overlay as so

    def _no_network(*a, **k):
        raise AssertionError("peek must never fetch")

    monkeypatch.setattr(so, "_build_teams_block", _no_network)
    monkeypatch.setattr(so, "_CACHE", {})
    monkeypatch.setattr(so, "_TEAMS_CACHE", {})
    assert so.peek_sleeper_teams_overlay("L1") is None
    so._TEAMS_CACHE["L1"] = {"payload": {"teams": [{"ownerId": "o0"}]}, "_cached_at": time.time()}
    assert so.peek_sleeper_teams_overlay("L1")["teams"] == [{"ownerId": "o0"}]
    so._TEAMS_CACHE["L1"]["_cached_at"] = 0.0
    assert so.peek_sleeper_teams_overlay("L1") is None
    assert list(so._CACHE) == [] and list(so._TEAMS_CACHE) == ["L1"]


def test_real_suggestion_engine_path_answers_or_says_why(env, monkeypatch):
    """Unstubbed: the plan runs the real suggestion engine on this team's
    roster, and the section is either the owner's answer or an explicit
    refusal with its reason — never a silent empty list."""
    monkeypatch.setattr(server, "_trade_suggestions_from_contract", _REAL_SUGGESTIONS)
    body = env.client.get(URL, headers=OWNER).json()
    sec = body["sections"]["sellHigh"]
    assert sec["owner"] == "src/trade/suggestions.py::generate_suggestions_from_pool"
    assert sec["unavailableReason"] != "suggestions_error"  # the engine did not raise
    if sec["available"]:
        assert isinstance(sec["actions"], list)
        assert sec["boardTopNFilter"] is not None
    else:
        assert sec["unavailableReason"]


def test_the_suggestions_route_and_the_plan_share_one_helper(env, monkeypatch):
    """Both answer through ``_trade_suggestions_from_contract`` — no second copy."""
    seen: list[str] = []

    def _spy(contract, league_cfg, roster, **kwargs):
        seen.append(kwargs["surface"])
        return _suggestions_payload()

    monkeypatch.setattr(server, "_trade_suggestions_from_contract", _spy)
    roster = env.contract["sleeper"]["teams"][0]["players"]
    res = env.client.post(
        "/api/trade/suggestions",
        json={"roster": roster, "leagueKey": "dynasty_main"},
        headers=OWNER,
    )
    assert res.status_code == 200
    env.client.get(URL, headers=OWNER)
    assert seen == ["/api/trade/suggestions", "/api/team/plan"]
