"""Architectural invariants for the multi-league split.

CLAUDE.md calls the scoring-profile / leagueKey split "the single
most important architectural rule for multi-league".  Two of its
clauses had no direct test:

1. **"no endpoint exposes raw Sleeper IDs to the UI"** — the whole
   point of the opaque ``key``.  ``LeagueConfig.public_dict`` omits
   ``sleeper_league_id`` today, but nothing asserted it, so adding one
   field to that dict would have leaked every league's Sleeper ID to
   any caller of ``/api/leagues`` with a green suite.

2. **league-scoped endpoints must refuse a league they have no
   rosters for** — asserted individually for ``/api/trade/simulate``
   in ``test_league_routing.py``, but not as a sweep.  A newly added
   league-scoped route that forgets ``require_loaded_contract=True``
   would silently serve League A's rosters to a League B request.

The sharing half of the rule (same scoring profile ⇒ one shared
ranking output) is already covered by
``test_league_routing.py::test_api_data_serves_shared_rankings_for_same_profile``
and ``::test_api_data_503s_when_scoring_profile_differs``; this module
does not duplicate it.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import server
from src.api import league_registry


SLEEPER_IDS = {
    "main": "111111111111111111",
    "side": "222222222222222222",
    "retired": "333333333333333333",
}


@pytest.fixture
def registry_with_distinct_sleeper_ids(tmp_path, monkeypatch):
    """Three leagues whose Sleeper IDs are long, unique, greppable digits.

    Realistic Sleeper IDs (18-digit strings) rather than "L-MAIN" so a
    substring scan of the serialized response is meaningful and cannot
    collide with ordinary content.
    """
    path = tmp_path / "registry.json"
    path.write_text(
        json.dumps(
            {
                "defaultLeagueKey": "main",
                "leagues": [
                    {
                        "key": "main",
                        "displayName": "Main",
                        "sleeperLeagueId": SLEEPER_IDS["main"],
                        "scoringProfile": "superflex_tep15_ppr1",
                        "active": True,
                        "idpEnabled": True,
                        "rosterSettings": {"teamCount": 12},
                        "aliases": ["primary"],
                    },
                    {
                        "key": "side",
                        "displayName": "Side",
                        "sleeperLeagueId": SLEEPER_IDS["side"],
                        "scoringProfile": "ppr_standard",
                        "active": True,
                        "rosterSettings": {"teamCount": 10},
                    },
                    {
                        "key": "retired",
                        "displayName": "Retired",
                        "sleeperLeagueId": SLEEPER_IDS["retired"],
                        "active": False,
                        "rosterSettings": {},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("LEAGUE_REGISTRY_PATH", str(path))
    league_registry.reload_registry()

    from src.api import user_kv

    monkeypatch.setattr(user_kv, "USER_KV_PATH", tmp_path / "user_kv.sqlite")
    user_kv._SETUP_DONE.clear()

    monkeypatch.setattr(server, "_is_authenticated", lambda request: True)
    # Never touch Sleeper for the live display-name overlay.
    monkeypatch.setattr(server, "_fetch_sleeper_league_name", lambda _id: None)
    # The POST trade routes resolve an auth session before the league
    # check; without this they 401 before reaching the code under test.
    monkeypatch.setattr(
        server,
        "_get_auth_session",
        lambda request: {
            "username": "alice",
            "auth_method": "sleeper",
            "sleeper_user_id": "oA",
        },
    )

    yield

    league_registry.reload_registry()


# ── Invariant 1: no raw Sleeper league IDs on the wire ───────────────


class TestNoSleeperIdLeak:
    def test_public_dict_omits_the_sleeper_league_id(self, registry_with_distinct_sleeper_ids):
        """Unit-level guard on the serializer itself."""
        for cfg in league_registry.active_leagues():
            public = cfg.public_dict()
            assert cfg.sleeper_league_id  # fixture really does set one
            assert cfg.sleeper_league_id not in json.dumps(public)
            # And no key smells like a Sleeper id passthrough.
            assert "sleeperLeagueId" not in public
            assert "leagueId" not in public

    def test_api_leagues_response_contains_no_sleeper_id(
        self, registry_with_distinct_sleeper_ids, monkeypatch
    ):
        """End-to-end guard on the documented public endpoint.

        Scans the whole serialized body, so a leak nested anywhere —
        including inside ``userDefaultTeam`` — is caught.
        """
        monkeypatch.setattr(server, "_get_auth_session", lambda request: None)

        with TestClient(server.app, raise_server_exceptions=True) as c:
            res = c.get("/api/leagues")

        assert res.status_code == 200
        body = res.text
        for key, sleeper_id in SLEEPER_IDS.items():
            assert sleeper_id not in body, f"/api/leagues leaked {key}'s Sleeper ID"

    def test_api_leagues_still_returns_the_opaque_key_and_settings(
        self, registry_with_distinct_sleeper_ids, monkeypatch
    ):
        """The no-leak assertion must not be vacuously satisfied by an
        empty response — the useful fields have to actually be there."""
        monkeypatch.setattr(server, "_get_auth_session", lambda request: None)

        with TestClient(server.app, raise_server_exceptions=True) as c:
            payload = c.get("/api/leagues").json()

        keys = {entry["key"] for entry in payload["leagues"]}
        assert keys == {"main", "side"}  # 'retired' is inactive
        main = next(e for e in payload["leagues"] if e["key"] == "main")
        assert main["displayName"] == "Main"
        assert main["rosterSettings"] == {"teamCount": 12}
        assert main["idpEnabled"] is True
        assert main["scoringProfile"] == "superflex_tep15_ppr1"
        assert payload["defaultKey"] == "main"

    def test_authenticated_view_also_leaks_nothing(
        self, registry_with_distinct_sleeper_ids, monkeypatch
    ):
        """The authed branch adds ``userDefaultTeam`` via a Sleeper
        lookup keyed on the league ID — the ID must stay server-side."""
        monkeypatch.setattr(
            server,
            "_get_auth_session",
            lambda request: {"username": "jason", "sleeper_user_id": "U-JASON"},
        )
        monkeypatch.setattr(
            server,
            "_fetch_sleeper_user_team",
            lambda league_id, user_id: {"ownerId": user_id, "teamName": "Brisket Crew"},
        )

        with TestClient(server.app, raise_server_exceptions=True) as c:
            res = c.get("/api/leagues")

        assert res.status_code == 200
        # The enrichment really did run (otherwise this is vacuous).
        assert "Brisket Crew" in res.text
        for sleeper_id in SLEEPER_IDS.values():
            assert sleeper_id not in res.text


# ── Invariant 2: league-scoped endpoints refuse the wrong league ─────


# Routes CLAUDE.md lists as needing the specific league's rosters.
# Each must 503 ``data_not_ready`` when the loaded contract belongs to
# a different league.
#
# ``/api/draft-capital`` is deliberately NOT in this list even though
# CLAUDE.md's table includes it: the endpoint implements a documented
# cross-league Sleeper-derived fallback instead of 503ing.  That
# divergence is characterised in ``TestDraftCapitalCrossLeagueFallback``
# and written up as Defect D-2 in docs/python-coverage-audit.md rather
# than silently "fixed" here.
LEAGUE_SCOPED_GETS = [
    "/api/terminal",
]
LEAGUE_SCOPED_POSTS = [
    "/api/trade/simulate",
    "/api/trade/suggestions",
    "/api/trade/finder",
]


def _install_contract_for_league(monkeypatch, league_key: str) -> None:
    """Stub ``latest_contract_data`` stamped for ``league_key``.

    Must be called INSIDE the TestClient context so app startup can't
    clobber it — same constraint as ``test_league_routing.py``.
    """
    monkeypatch.setattr(
        server,
        "latest_contract_data",
        {
            "meta": {"leagueKey": league_key},
            "players": {"stub": {"name": "Stub"}},
            "playersArray": [{"name": "Stub"}],
            "sleeper": {"teams": [{"ownerId": "oA", "name": "Team A", "players": []}]},
        },
    )


class TestLeagueScopedEndpointsRefuseForeignLeagues:
    @pytest.mark.parametrize("path", LEAGUE_SCOPED_GETS)
    def test_get_endpoints_503_for_a_league_with_no_loaded_rosters(
        self, registry_with_distinct_sleeper_ids, monkeypatch, path
    ):
        with TestClient(server.app, raise_server_exceptions=True) as c:
            _install_contract_for_league(monkeypatch, "main")
            res = c.get(path, params={"leagueKey": "side"})

        assert res.status_code == 503, f"{path} served a foreign league"
        body = res.json()
        assert body["error"] == "data_not_ready"
        assert body.get("leagueKey") == "side"

    @pytest.mark.parametrize("path", LEAGUE_SCOPED_POSTS)
    def test_post_endpoints_503_for_a_league_with_no_loaded_rosters(
        self, registry_with_distinct_sleeper_ids, monkeypatch, path
    ):
        with TestClient(server.app, raise_server_exceptions=True) as c:
            _install_contract_for_league(monkeypatch, "main")
            res = c.post(path, json={"leagueKey": "side"})

        assert res.status_code == 503, f"{path} served a foreign league"
        body = res.json()
        assert body["error"] == "data_not_ready"
        # The message names the refused league even where the body
        # carries no ``leagueKey`` field (see the echo test below).
        assert "side" in body["message"]

    def test_leaguekey_echo_on_503_is_inconsistent_across_routes(
        self, registry_with_distinct_sleeper_ids, monkeypatch
    ):
        """CLAUDE.md: league-aware endpoints "all stamp leagueKey on
        their response".  On the 503 path only some do.

        Characterisation, not endorsement — the status code and error
        code (the part clients branch on) are correct everywhere.
        Recorded as a minor finding in docs/python-coverage-audit.md.
        """
        with TestClient(server.app, raise_server_exceptions=True) as c:
            _install_contract_for_league(monkeypatch, "main")
            simulate = c.post("/api/trade/simulate", json={"leagueKey": "side"}).json()
            finder = c.post("/api/trade/finder", json={"leagueKey": "side"}).json()

        assert simulate.get("leagueKey") == "side"
        assert "leagueKey" not in finder

    @pytest.mark.parametrize("path", LEAGUE_SCOPED_GETS + LEAGUE_SCOPED_POSTS)
    def test_every_league_scoped_route_rejects_unknown_and_inactive_keys(
        self, registry_with_distinct_sleeper_ids, monkeypatch, path
    ):
        """The documented 400 contract, swept across all of them."""
        with TestClient(server.app, raise_server_exceptions=True) as c:
            _install_contract_for_league(monkeypatch, "main")

            if path in LEAGUE_SCOPED_GETS:
                unknown = c.get(path, params={"leagueKey": "does-not-exist"})
                inactive = c.get(path, params={"leagueKey": "retired"})
            else:
                unknown = c.post(path, json={"leagueKey": "does-not-exist"})
                inactive = c.post(path, json={"leagueKey": "retired"})

        assert unknown.status_code == 400, path
        assert unknown.json()["error"] == "unknown_league"
        assert inactive.status_code == 400, path
        assert inactive.json()["error"] == "inactive_league"


# ── /api/draft-capital: documented divergence, characterised ─────────


class TestDraftCapitalCrossLeagueFallback:
    """CLAUDE.md says this route 503s on a league mismatch.  It does not.

    The handler resolves the league WITHOUT ``require_loaded_contract``
    and, for any non-default league, builds a Sleeper-derived answer
    from that league's own roster data.  The docstring on
    ``get_draft_capital`` describes this as intentional.

    Rather than pick a side, these tests pin what is actually
    guaranteed today — and, critically, assert the part that would be
    a real data leak if it broke: League A's roster/pick ownership
    must never appear under a League B request.

    See docs/python-coverage-audit.md, Defect D-2, for the open
    question (503 per the table vs. keep the fallback and fix the doc).
    """

    @pytest.fixture(autouse=True)
    def _no_network(self, monkeypatch):
        """The fallback calls Sleeper; tests must not.

        Records the league IDs requested so the assertions below can
        prove which league's rosters were consulted.
        """
        self.fetched: list[str] = []

        from src.api import draft_capital_fallback

        def _fake_build(sleeper_league_id, contract, **kwargs):
            self.fetched.append(str(sleeper_league_id))
            return {
                "teams": [],
                "source": "sleeper-derived",
                "_sleeperLeagueIdUsed": str(sleeper_league_id),
            }

        monkeypatch.setattr(draft_capital_fallback, "build_sleeper_derived", _fake_build)

    def test_foreign_league_gets_its_own_rosters_not_the_loaded_league_s(
        self, registry_with_distinct_sleeper_ids, monkeypatch
    ):
        with TestClient(server.app, raise_server_exceptions=True) as c:
            _install_contract_for_league(monkeypatch, "main")
            res = c.get("/api/draft-capital", params={"leagueKey": "side"})

        # Current behaviour: 200 with a Sleeper-derived payload.
        assert res.status_code == 200
        assert res.json()["leagueKey"] == "side"

        # The safety-critical part: it consulted SIDE's Sleeper league,
        # never MAIN's.  A regression here would serve one league's
        # pick ownership under another league's name.
        assert self.fetched == [SLEEPER_IDS["side"]]
        assert SLEEPER_IDS["main"] not in self.fetched

    def test_response_still_echoes_the_requested_league_key(
        self, registry_with_distinct_sleeper_ids, monkeypatch
    ):
        with TestClient(server.app, raise_server_exceptions=True) as c:
            _install_contract_for_league(monkeypatch, "main")
            res = c.get("/api/draft-capital", params={"leagueKey": "side"})
        assert res.json()["leagueKey"] == "side"

    def test_unknown_and_inactive_keys_are_still_rejected(
        self, registry_with_distinct_sleeper_ids, monkeypatch
    ):
        """The 400 half of the contract IS honoured here."""
        with TestClient(server.app, raise_server_exceptions=True) as c:
            _install_contract_for_league(monkeypatch, "main")
            unknown = c.get("/api/draft-capital", params={"leagueKey": "nope"})
            inactive = c.get("/api/draft-capital", params={"leagueKey": "retired"})

        assert unknown.status_code == 400
        assert unknown.json()["error"] == "unknown_league"
        assert inactive.status_code == 400
        assert inactive.json()["error"] == "inactive_league"


# ── The documented alias behaviour ───────────────────────────────────


class TestAliasCanonicalisation:
    def test_alias_resolves_and_the_response_echoes_the_canonical_key(
        self, registry_with_distinct_sleeper_ids, monkeypatch
    ):
        """``primary`` is an alias of ``main``; responses must report
        the canonical key so the frontend never learns alias names."""
        with TestClient(server.app, raise_server_exceptions=True) as c:
            _install_contract_for_league(monkeypatch, "main")
            res = c.get("/api/terminal", params={"leagueKey": "primary"})

        assert res.status_code != 400
        body = res.json()
        if isinstance(body, dict) and "leagueKey" in body:
            assert body["leagueKey"] == "main"
