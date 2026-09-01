"""B8 — the public/private boundary on ``/api/public/league/*``.

The boundary is SEMANTIC, not a module boundary and not a field-name
denylist (CLAUDE.md §5).  Aggregate, league-wide, factual content is
public; the per-manager decomposition that lets one manager scout a
rival is private intelligence.

``ownerId`` alone is deliberately NOT the test.  It is the team
identifier already visible in public standings.  What makes a payload
private is the decomposition attached to it — a manager's bench depth
and positional holes, their bidding behaviour, or an actionable buy/sell
call on their roster.

Measured anonymously on production 2026-08-13, which is what set the
line below:

    rosTeamStrength  61,654 chars  per-owner benchDepthScore,
                                   positionalCoverageScore,
                                   healthAvailabilityScore, startingLineup
    faabAnalytics    87,967 chars  ownerId, teamAggression, recentWins,
                                   playerHistory  (its only consumer is
                                   the PRIVATE /waivers page)
    rosTradeDeadline 19,400 chars  per-owner buy/sell/rebuild + strategy text
    rosChampionship     178 chars  championshipOdds / seeds, no ownerId
    rosPlayoffOdds      251 chars  playoffOdds / seeds, no ownerId
    rosPower          5,580 chars  ranking + weights, no private markers
    playoffOdds       1,686 chars  owners + odds, no private markers

``rosTradeDeadline`` currently answers "Insufficient evidence" only
because the product is preseason.  An empty payload is not a safe
boundary — the route populates real per-manager calls at week 1, which
is why it is closed now rather than when the data arrives.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import server
from src.api import league_registry

#: Sections whose payload is per-manager decision intelligence.
PRIVATE_SECTIONS = ("rosTeamStrength", "faabAnalytics", "rosTradeDeadline", "teamAssignment")

#: Sections that are genuinely league-wide facts and must STAY public.
#: Listed explicitly so a future "make it all private" sweep has to
#: argue with a test rather than quietly shrinking the public product.
PUBLIC_SECTIONS = ("rosChampionship", "rosPlayoffOdds", "rosPower", "playoffOdds")

#: Field names that mark a payload as per-manager decomposition.
PRIVATE_MARKERS = (
    "benchDepthScore",
    "positionalCoverageScore",
    "healthAvailabilityScore",
    "teamAggression",
    "playerHistory",
    "recommendation",
)


@pytest.fixture
def anon_client(monkeypatch):
    """A client with no session — the anonymous public caller."""
    monkeypatch.setattr(server, "_is_authenticated", lambda request: False)
    monkeypatch.setattr(server, "_get_auth_session", lambda request: None)
    with TestClient(server.app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def authed_client(monkeypatch):
    monkeypatch.setattr(server, "_is_authenticated", lambda request: True)
    monkeypatch.setattr(server, "_get_auth_session", lambda request: {"username": "t"})
    with TestClient(server.app, raise_server_exceptions=False) as c:
        yield c


class TestPrivateSectionsAreClosedToAnonymousCallers:
    @pytest.mark.parametrize("section", PRIVATE_SECTIONS)
    def test_anonymous_cannot_read_a_private_section(self, anon_client, section):
        res = anon_client.get(f"/api/public/league/{section}")
        assert res.status_code in (401, 403, 404), (
            f"{section!r} answered {res.status_code} to an anonymous caller; it "
            "carries per-manager decision intelligence"
        )

    @pytest.mark.parametrize("section", PRIVATE_SECTIONS)
    def test_the_csv_variant_is_closed_too(self, anon_client, section):
        """An alternate representation is the same data."""
        res = anon_client.get(f"/api/public/league/{section}.csv")
        assert res.status_code in (401, 403, 404), (
            f"{section}.csv answered {res.status_code} anonymously — the CSV "
            "route is a second door to the same payload"
        )

    @pytest.mark.parametrize("section", PRIVATE_SECTIONS)
    def test_private_sections_are_declared_private(self, section):
        from src.public_league.public_contract import PRIVATE_INTELLIGENCE_SECTIONS

        assert section in PRIVATE_INTELLIGENCE_SECTIONS


class TestPublicSectionsStayPublic:
    """B8 must not shrink the public product to satisfy the invariant."""

    @pytest.mark.parametrize("section", PUBLIC_SECTIONS)
    def test_anonymous_is_not_denied_a_league_wide_section(self, anon_client, section):
        """The assertion is about the BOUNDARY, not about data being
        available.  A 503 means the snapshot could not be built in this
        environment, which is a different fact from "you may not have
        this" — conflating them would make the test pass for the wrong
        reason the day the gate over-closes."""
        res = anon_client.get(f"/api/public/league/{section}")
        if res.status_code == 503:
            pytest.skip(f"{section}: snapshot unavailable in this environment")
        assert res.status_code not in (401, 403), (
            f"{section!r} is league-wide factual content and was DENIED "
            f"({res.status_code}) — the privacy rule is semantic, not "
            '"make every ROS section private"'
        )

    @pytest.mark.parametrize("section", PUBLIC_SECTIONS)
    def test_public_sections_carry_no_per_manager_decomposition(self, anon_client, section):
        res = anon_client.get(f"/api/public/league/{section}")
        if res.status_code != 200:
            pytest.skip(f"{section} unavailable in this environment")
        body = json.dumps(res.json())
        present = [m for m in PRIVATE_MARKERS if m in body]
        assert not present, (
            f"{section!r} is served publicly but carries {present} — either the "
            "payload changed or the section is misclassified"
        )


class TestPrivateConsumersStillWork:
    """Closing the anonymous door must not break the private product."""

    @pytest.mark.parametrize("section", PRIVATE_SECTIONS)
    def test_authenticated_callers_are_not_denied(self, authed_client, section):
        res = authed_client.get(f"/api/public/league/{section}")
        if res.status_code == 503:
            pytest.skip(f"{section}: snapshot unavailable in this environment")
        assert res.status_code not in (401, 403, 404), (
            f"{section!r} returned {res.status_code} to an AUTHENTICATED caller; "
            "/waivers and the private ROS surfaces consume this"
        )


class TestSectionsAreScopedToTheRequestedLeague:
    """``/{section}`` took no ``leagueKey`` and resolved the default league.

    Measured on production: ``?leagueKey=dynasty_main`` and
    ``?leagueKey=dynasty_new`` returned BYTE-IDENTICAL payloads stamped
    with dynasty_main's ``rootLeagueId``, and the response carried no
    ``leagueKey`` at all — so a caller could not even detect it.
    ``frontend/components/waivers/ManualAddDrop.jsx`` sends that
    parameter.  This is the W18 family on a route B6 did not enumerate.
    """

    def test_an_unknown_league_does_not_silently_inherit_the_default(self, authed_client):
        res = authed_client.get("/api/public/league/overview?leagueKey=not_a_league")
        assert res.status_code == 400, (
            "an unknown leagueKey was accepted and silently served the default "
            f"league's payload (status {res.status_code})"
        )

    def test_the_response_names_the_league_it_answered_for(self, authed_client):
        res = authed_client.get("/api/public/league/overview")
        if res.status_code != 200:
            pytest.skip("overview unavailable in this environment")
        body = res.json()
        assert body.get("leagueKey"), (
            "the response does not say which league it is for, so a caller "
            "cannot detect being served another league's data"
        )

    def test_each_configured_league_resolves_to_its_own_id(self, tmp_path, monkeypatch):
        """The resolver, not the payload — so scoping is provable even
        where only one league has a public snapshot.

        Builds its OWN registry rather than iterating whatever
        ``active_leagues()`` happens to return: the first version of this
        test looped over that, got an empty list under pytest, and passed
        vacuously while the call it was meant to exercise raised
        ``TypeError`` outside pytest. A test that cannot fail is worse
        than no test.
        """
        registry = tmp_path / "registry.json"
        registry.write_text(
            json.dumps(
                {
                    "defaultLeagueKey": "alpha",
                    "leagues": [
                        {
                            "key": "alpha",
                            "displayName": "Alpha",
                            "sleeperLeagueId": "L-ALPHA",
                            "active": True,
                            "aliases": ["a"],
                            "rosterSettings": {},
                        },
                        {
                            "key": "beta",
                            "displayName": "Beta",
                            "sleeperLeagueId": "L-BETA",
                            "active": True,
                            "rosterSettings": {},
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("LEAGUE_REGISTRY_PATH", str(registry))
        league_registry.reload_registry()
        try:
            expected = {"alpha": "L-ALPHA", "beta": "L-BETA"}
            assert len(expected) == 2, "fixture must carry two leagues to be meaningful"
            for key, sleeper_id in expected.items():
                assert server._public_league_id(key) == sleeper_id, (
                    f"{key} resolved to {server._public_league_id(key)!r}, not its "
                    f"own {sleeper_id!r}"
                )
            # Alias-aware, like every other league-aware route.
            assert server._public_league_id("a") == "L-ALPHA"
            # Unknown keys resolve to nothing rather than the default.
            assert server._public_league_id("nope") == ""
            # No argument still means the default league.
            assert server._public_league_id() == "L-ALPHA"
        finally:
            league_registry.reload_registry()


class TestForceRefreshIsBounded:
    """``?refresh=`` was an unbounded anonymous rebuild trigger.

    ``force_refresh=bool(refresh)`` had two defects in one expression:
    any non-empty string was true, so ``?refresh=0`` — the spelling a
    caller uses to say NO — forced a rebuild; and nothing checked who
    was asking, so an anonymous caller could skip the cache on every
    request and drive unbounded full snapshot rebuilds (O(seasons x
    weeks) plus Sleeper round-trips each).  The only remaining bound was
    a rate limiter whose key is caller-controlled.
    """

    def test_a_falsy_flag_does_not_force_a_rebuild(self, authed_client, monkeypatch):
        seen: list[bool] = []
        monkeypatch.setattr(
            server,
            "_get_public_snapshot",
            lambda force_refresh=False: seen.append(bool(force_refresh)) or _Snapshotless(),
        )
        authed_client.get("/api/public/league/overview?refresh=0")
        assert seen and seen[0] is False, "?refresh=0 forced a rebuild"

    def test_anonymous_cannot_force_a_rebuild(self, anon_client, monkeypatch):
        seen: list[bool] = []
        monkeypatch.setattr(
            server,
            "_get_public_snapshot",
            lambda force_refresh=False: seen.append(bool(force_refresh)) or _Snapshotless(),
        )
        anon_client.get("/api/public/league/overview?refresh=1")
        assert seen and seen[0] is False, (
            "an anonymous ?refresh=1 forced a full snapshot rebuild — the abuse "
            "surface is still open"
        )

    def test_an_authorized_caller_still_can(self, authed_client, monkeypatch):
        """The future 'Sync Sleeper / Refresh League Data' action.

        The repair must not make the planned authenticated refresh
        impossible — it is precisely the caller this admits.
        """
        seen: list[bool] = []
        monkeypatch.setattr(
            server,
            "_get_public_snapshot",
            lambda force_refresh=False: seen.append(bool(force_refresh)) or _Snapshotless(),
        )
        authed_client.get("/api/public/league/overview?refresh=1")
        assert seen and seen[0] is True, (
            "an authenticated caller could not force a refresh — this would "
            "foreclose the future authorized Sync Sleeper action"
        )

    def test_the_flag_parser_rejects_bool_of_string(self):
        assert server._is_truthy_flag("1") is True
        assert server._is_truthy_flag("true") is True
        assert server._is_truthy_flag("on") is True
        # The bug: bool("0") is True.
        assert server._is_truthy_flag("0") is False
        assert server._is_truthy_flag("false") is False
        assert server._is_truthy_flag("") is False
        assert server._is_truthy_flag(None) is False


class _Snapshotless:
    """Minimal stand-in so the refresh tests assert on the FLAG, not on
    snapshot building.  Section builders raise on it, the route turns
    that into a 503, and the flag we care about was already recorded."""

    def __getattr__(self, name):  # noqa: D105
        raise AttributeError(name)
