"""Public ``/api/public/league*`` responses never carry a raw Sleeper league id.

CLAUDE.md "League-aware routing": frontend callers use the stable
registry ``key`` from ``/api/leagues``; "no endpoint exposes raw Sleeper
IDs to the UI".  The public payloads did — measured on the fixture
contract before this change: the ``league`` header carried
``rootLeagueId`` / ``leagueIds`` / ``currentLeagueId`` (and
``historyCoverage.stoppedAtLeagueId``), every manager carried
``currentLeagueId`` and a per-alias ``leagueId``, ~20 section builders
stamped a per-row ``leagueId`` (300+ occurrences in records / streaks /
rivalries / weekly / …), drafts carried ``draftId``, the matchup and player
routes rebuilt the header with ``rootLeagueId``, ``/metrics`` answered
``leagueId``, and the CSV exports had ``leagueId`` / ``draftId`` columns.

The guard below WALKS EVERY PUBLIC ROUTE over a controlled snapshot (the
same fixture ``test_public_league_privacy_boundary.py`` builds — real
routes, stubbed Sleeper, its own registry) and fails if any key is a
league-id / draft-id field or any value contains a Sleeper id the snapshot
chain or the registry knows.  It also pins the ``leagueKey`` routing rules
on every public route: unknown → 400, inactive → 400, a non-public league
→ 404, never a silent default.
"""

from __future__ import annotations

import json
import re
from typing import Any

import pytest

import server
from src.api import league_registry
from src.public_league import public_contract
from tests.api.test_public_league_privacy_boundary import (  # noqa: F401 — pytest fixtures
    authed_client,
    controlled_snapshot,
)

#: Key names that are a raw Sleeper league / draft id, whatever the casing
#: or prefix (``leagueId``, ``rootLeagueId``, ``currentLeagueId``,
#: ``leagueIds``, ``stoppedAtLeagueId``, ``draftId`` …).
RAW_ID_KEY = re.compile(r"(?i)(leagueids?|draftid)$")

#: Every raw Sleeper id field the serving projection drops (pinned here so
#: shrinking ``public_contract.RAW_SLEEPER_ID_FIELDS`` has to argue with a test).
RAW_ID_FIELDS = (
    "currentLeagueId",
    "draftId",
    "failedLeagueId",
    "leagueId",
    "leagueIds",
    "previousLeagueId",
    "rootLeagueId",
    "stoppedAtLeagueId",
)

#: The fixture's Sleeper draft id (``tests/public_league/fixtures.py``).
FIXTURE_DRAFT_IDS = ("draft-2025",)

ARCHIVE_KINDS = ("trades", "waivers", "weeklyMatchups", "rookieDrafts", "seasonResults", "managers")


@pytest.fixture(autouse=True)
def _no_public_rate_limit(monkeypatch):
    """These tests make far more public requests per second than the
    anonymous scraper limit allows; the limiter is not under test here."""
    from src.api import rate_limit

    monkeypatch.setattr(rate_limit, "should_rate_limit", lambda ip: (False, 0))


def _forbidden_values(snapshot) -> set[str]:
    ids = {str(i) for i in snapshot.league_ids if i}
    ids.add(str(snapshot.root_league_id))
    for cfg in league_registry.all_leagues():
        if cfg.sleeper_league_id:
            ids.add(str(cfg.sleeper_league_id))
    ids.update(FIXTURE_DRAFT_IDS)
    return {i for i in ids if i}


def _raw_id_leaks(payload: Any, forbidden: set[str], path: str = "$") -> list[str]:
    found: list[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            if isinstance(key, str):
                if RAW_ID_KEY.search(key):
                    found.append(f"key {path}.{key}")
                if any(f in key for f in forbidden):
                    found.append(f"key-value {path}.{key}")
            found.extend(_raw_id_leaks(value, forbidden, f"{path}.{key}"))
    elif isinstance(payload, (list, tuple)):
        for i, item in enumerate(payload):
            found.extend(_raw_id_leaks(item, forbidden, f"{path}[{i}]"))
    elif isinstance(payload, str):
        if any(f in payload for f in forbidden):
            found.append(f"value {path}={payload!r}")
    return found


@pytest.fixture
def public_routes(authed_client, controlled_snapshot):  # noqa: F811
    """Every public JSON route, with the fixture's real ids filled in.

    Authenticated, so the four private-intelligence sections are walked too
    — they are served through the same route and the same projection."""
    client = authed_client
    snapshot = server._public_league_cache["snapshot"]
    matchups = client.get("/api/public/league/matchups").json()["matchups"]
    players = client.get("/api/public/league/players").json()["players"]
    assert matchups and players, "fixture must yield a matchup and a player to walk"
    m = matchups[0]
    required = [
        "/api/public/league",
        "/api/public/league/franchise?owner=owner-B",
        "/api/public/league/matchups",
        f"/api/public/league/matchup/{m['season']}/{m['week']}/{m['matchupId']}",
        "/api/public/league/players",
        f"/api/public/league/player/{players[0]['playerId']}",
        "/api/public/league/metrics",
    ] + [
        f"/api/public/league/{s}"
        for s in (public_contract.OVERVIEW_SECTION, *public_contract._SECTION_BUILDERS)
    ]
    # Lazy ROS / Monte-Carlo sections may answer 503 where their file-backed
    # artifacts do not exist; whatever they answer is still walked.
    optional = [
        f"/api/public/league/{s}"
        for s in public_contract._LAZY_SECTION_BUILDERS
        if f"/api/public/league/{s}" not in required
    ]
    return client, snapshot, required, optional


class TestNoPublicRouteServesARawSleeperId:
    def test_every_public_json_route_is_free_of_raw_sleeper_ids(self, public_routes):
        client, snapshot, required, optional = public_routes
        forbidden = _forbidden_values(snapshot)
        assert {"L2025", "L2024"} <= forbidden, "guard must know the fixture chain"
        leaks: dict[str, list[str]] = {}
        for path in required + optional:
            res = client.get(path)
            if path in required:
                assert res.status_code == 200, f"{path}: {res.status_code} {res.text[:300]}"
            found = _raw_id_leaks(res.json(), forbidden)
            if found:
                leaks[path] = found[:5] + ([f"... {len(found) - 5} more"] if len(found) > 5 else [])
        assert not leaks, "raw Sleeper ids served publicly:\n" + json.dumps(leaks, indent=1)

    def test_every_public_csv_is_free_of_raw_sleeper_ids(self, public_routes):
        client, snapshot, _required, _optional = public_routes
        forbidden = _forbidden_values(snapshot)
        from src.public_league import csv_export

        # Sections with a real exporter.  (``PUBLIC_CSV_EXPORTABLE_KEYS``
        # also advertises a few that have none and 503 — a pre-existing,
        # separate defect; nothing is served there to leak.)
        exportable = [
            s
            for s in public_contract.PUBLIC_CSV_EXPORTABLE_KEYS
            if s in csv_export.EXPORTERS or s in ("franchise", "archives")
        ]
        assert len(exportable) >= 8, exportable
        paths = [f"/api/public/league/{s}.csv" for s in exportable]
        paths += ["/api/public/league/hall_of_fame.csv"]
        paths += [f"/api/public/league/archives.csv?kind={k}" for k in ARCHIVE_KINDS]
        paths += ["/api/public/league/franchise.csv?owner=owner-B"]
        leaks = {}
        for path in paths:
            res = client.get(path)
            assert res.status_code == 200, f"{path}: {res.status_code} {res.text[:300]}"
            header_row = res.text.splitlines()[0] if res.text else ""
            bad_cols = [c for c in header_row.split(",") if RAW_ID_KEY.search(c.strip())]
            bad_vals = sorted(f for f in forbidden if f in res.text)
            if bad_cols or bad_vals:
                leaks[path] = {"columns": bad_cols, "values": bad_vals}
        assert not leaks, f"raw Sleeper ids in public CSVs: {leaks}"

    def test_csv_names_its_league_by_key(self, public_routes):
        client, _snapshot, _r, _o = public_routes
        for path in ("/api/public/league/history.csv", "/api/public/league/hall_of_fame.csv"):
            res = client.get(path)
            assert res.status_code == 200
            assert (
                res.headers.get("x-league-key") == "fixture_public_league"
            ), f"{path} does not name the league it describes"

    def test_header_names_the_current_season_by_label(self, public_routes):
        client, snapshot, _r, _o = public_routes
        league = client.get("/api/public/league/history").json()["league"]
        assert league["currentSeason"] == snapshot.current_season.season
        managers = league["managers"]
        assert managers and all("currentSeason" in m for m in managers)
        # A manager not in the current season has none (unknown, not "").
        seasons = {m["currentSeason"] for m in managers}
        assert snapshot.current_season.season in seasons
        assert seasons <= {snapshot.current_season.season, None}

    def test_metrics_names_the_league_by_key(self, public_routes):
        client, _snapshot, _r, _o = public_routes
        body = client.get("/api/public/league/metrics").json()
        assert body["leagueKey"] == "fixture_public_league"


class TestServingProjection:
    """``public_payload`` is the one serving boundary; the blocklist makes
    any payload that skipped it fail closed instead of leaking."""

    def test_projection_drops_raw_ids_without_mutating_the_builder_result(self):
        built = {
            "leagueId": "L1",
            "rows": [{"season": "2025", "leagueId": "L1", "draftId": "D1", "x": 1}],
            "league": {"rootLeagueId": "L1", "leagueIds": ["L1"], "currentLeagueId": "L1"},
        }
        before = json.loads(json.dumps(built))
        served = public_contract.public_payload(built)
        assert served == {"rows": [{"season": "2025", "x": 1}], "league": {}}
        assert built == before, "builders memoize results; the projection must copy"

    def test_the_projected_field_set_is_pinned(self):
        assert public_contract.RAW_SLEEPER_ID_FIELDS == frozenset(RAW_ID_FIELDS)

    @pytest.mark.parametrize("field", RAW_ID_FIELDS)
    def test_an_unprojected_payload_fails_closed(self, field):
        with pytest.raises(AssertionError, match="raw Sleeper id"):
            public_contract.assert_public_payload_safe({"data": [{field: "123"}]})


# ── leagueKey routing on every public route ─────────────────────────────

ROUTES = (
    "/api/public/league",
    "/api/public/league/overview",
    "/api/public/league/history.csv",
    "/api/public/league/hall_of_fame.csv",
    "/api/public/league/matchups",
    "/api/public/league/matchup/2025/1/1",
    "/api/public/league/players",
    "/api/public/league/player/p-idp1",
    "/api/public/league/metrics",
    "/api/league/articles",
    "/api/league/articles/2025/1/1/recap",
)

#: Article reads describe the public league but carry no JSON envelope of
#: their own (their bodies are pinned by
#: ``test_league_articles_route_characterization.py``), so "served" means
#: the key validation let the request through to the article store.
ARTICLE_ROUTES = ("/api/league/articles", "/api/league/articles/2025/1/1/recap")


@pytest.fixture
def routed_client(authed_client, controlled_snapshot, monkeypatch, tmp_path):  # noqa: F811
    """The controlled public league plus an inactive league and an active
    league with no public snapshot."""
    league_key, sleeper_id = controlled_snapshot
    registry = tmp_path / "routing_registry.json"
    registry.write_text(
        json.dumps(
            {
                "defaultLeagueKey": league_key,
                "leagues": [
                    {
                        "key": league_key,
                        "displayName": "Fixture",
                        "sleeperLeagueId": sleeper_id,
                        "active": True,
                        "aliases": ["fx"],
                        "rosterSettings": {},
                    },
                    {
                        "key": "retired_league",
                        "displayName": "Retired",
                        "sleeperLeagueId": "L-RETIRED",
                        "active": False,
                        "rosterSettings": {},
                    },
                    {
                        "key": "other_league",
                        "displayName": "Other",
                        "sleeperLeagueId": "L-OTHER",
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
    return authed_client, league_key


def _with_key(path: str, key: str) -> str:
    return f"{path}{'&' if '?' in path else '?'}leagueKey={key}"


class TestEveryPublicRouteHonoursLeagueKey:
    @pytest.mark.parametrize("path", ROUTES)
    def test_unknown_key_is_400(self, routed_client, path):
        client, _key = routed_client
        res = client.get(_with_key(path, "not_a_league"))
        assert res.status_code == 400, f"{path}: {res.status_code} {res.text[:200]}"
        assert res.json()["error"] == "unknown_league"

    @pytest.mark.parametrize("path", ROUTES)
    def test_inactive_key_is_400(self, routed_client, path):
        client, _key = routed_client
        res = client.get(_with_key(path, "retired_league"))
        assert res.status_code == 400, f"{path}: {res.status_code} {res.text[:200]}"
        assert res.json()["error"] == "inactive_league"

    @pytest.mark.parametrize("path", ROUTES)
    def test_another_league_is_refused_not_substituted(self, routed_client, path):
        client, _key = routed_client
        res = client.get(_with_key(path, "other_league"))
        assert res.status_code == 404, (
            f"{path} answered {res.status_code} for a league with no public snapshot "
            "— a named league must never be served the default league's payload"
        )
        assert res.json()["error"] == "league_not_public"

    @pytest.mark.parametrize("path", ROUTES)
    @pytest.mark.parametrize("spelling", ["fixture_public_league", "fx"])
    def test_the_public_league_is_served_by_key_or_alias(self, routed_client, path, spelling):
        client, league_key = routed_client
        res = client.get(_with_key(path, spelling))
        if path in ARTICLE_ROUTES:
            # Past validation: the list answers, a missing article is the
            # store's own 404, never a league refusal.
            assert res.status_code in (200, 404), f"{path}: {res.status_code}"
            assert res.json().get("error") not in {
                "unknown_league",
                "inactive_league",
                "league_not_public",
            }
            return
        assert res.status_code == 200, f"{path}: {res.status_code} {res.text[:200]}"
        if path.endswith(".csv"):
            assert res.headers.get("x-league-key") == league_key
        else:
            assert res.json()["leagueKey"] == league_key


# ── Failure paths are public payloads too ───────────────────────────────


@pytest.fixture
def failing_rebuild(authed_client, controlled_snapshot, monkeypatch):  # noqa: F811
    """A cold cache whose rebuild returns a HALF-FETCHED current season —
    the real ``current_season_integrity_error`` path (``sleeper_client``
    answers a failed ``/rosters`` GET with ``[]``).  The refusal text names
    the season as ``"2025 (L2025)"``; the routes used to echo it in their
    503 bodies."""
    from src.public_league import build_public_snapshot

    _league_key, sleeper_id = controlled_snapshot
    broken = build_public_snapshot(sleeper_id, max_seasons=2, include_nfl_players=False)
    broken.current_season.rosters = []
    monkeypatch.setattr(server, "build_public_snapshot", lambda *a, **k: broken)
    monkeypatch.setattr(server, "_PUBLIC_LEAGUE_PERSIST", False)
    for key, value in {
        "snapshot": None,
        "snapshot_league_id": None,
        "fetched_at": 0.0,
        "refreshing": False,
        "last_failure_at": 0.0,
        "last_failure_error": None,
    }.items():
        monkeypatch.setitem(server._public_league_cache, key, value)
    return authed_client, sleeper_id


class TestUnavailableResponsesNameNoSleeperId:
    def test_every_public_route_503_is_generic(self, failing_rebuild):
        client, sleeper_id = failing_rebuild
        forbidden = {sleeper_id, "L2024"}
        paths = [
            "/api/public/league",
            "/api/public/league/overview",
            "/api/public/league/history",
            "/api/public/league/activity",
            "/api/public/league/archives",
            "/api/public/league/rosPower",
            "/api/public/league/franchise?owner=owner-B",
            "/api/public/league/matchups",
            "/api/public/league/matchup/2025/1/1",
            "/api/public/league/players",
            "/api/public/league/player/p-idp1",
            "/api/public/league/history.csv",
            "/api/public/league/hall_of_fame.csv",
        ]
        seen_503 = 0
        leaks = {}
        for path in paths:
            res = client.get(path)
            seen_503 += res.status_code == 503
            body = res.text
            bad = sorted(f for f in forbidden if f in body)
            if bad or "integrity" in body or "rosters" in body:
                leaks[path] = (res.status_code, body[:200])
        assert seen_503 == len(paths), "every route must actually take the failure path"
        assert not leaks, f"failure detail served publicly: {leaks}"

    def test_the_detail_is_still_logged(self, failing_rebuild, caplog):
        client, sleeper_id = failing_rebuild
        with caplog.at_level("ERROR"):
            client.get("/api/public/league/history")
        assert any(
            sleeper_id in r.getMessage() for r in caplog.records
        ), "the operator log must keep the specific failure"


class TestPowerRefusalAndLensAreProjected:
    def test_a_membership_refusal_names_no_league_id(self, public_routes, monkeypatch):
        """``power_v2._refused_section`` used to publish the integrity text
        (``"2025 (L2025)"`` + owner ids) in ``missingInputs`` on the public
        ``rosPower`` route, canonical and lens paths alike."""
        client, snapshot, _r, _o = public_routes
        monkeypatch.setattr(snapshot.current_season, "rosters", [])
        forbidden = _forbidden_values(snapshot)
        for path in (
            "/api/public/league/rosPower",
            "/api/public/league/rosPower?lens=results_only",
        ):
            res = client.get(path)
            assert res.status_code == 200, f"{path}: {res.status_code} {res.text[:200]}"
            data = res.json()["data"]
            assert data["unrankable"]["reason"] == "current_league_membership_incomplete"
            assert not _raw_id_leaks(res.json(), forbidden), path

    def test_the_lens_recompute_goes_through_the_projection(self, public_routes, monkeypatch):
        """The ``?lens=`` branch replaced ``payload["data"]`` AFTER the
        section payload was projected; whatever it returns is projected too."""
        from src.ros import power_v2

        client, snapshot, _r, _o = public_routes
        real = power_v2.build_section

        def leaky(snap, *a, **k):
            section = real(snap, *a, **k)
            if k.get("lens"):
                section = {**section, "leagueId": snap.root_league_id}
            return section

        monkeypatch.setattr(power_v2, "build_section", leaky)
        res = client.get("/api/public/league/rosPower?lens=results_only")
        assert res.status_code == 200, f"{res.status_code} {res.text[:200]}"
        assert not _raw_id_leaks(res.json(), _forbidden_values(snapshot))
