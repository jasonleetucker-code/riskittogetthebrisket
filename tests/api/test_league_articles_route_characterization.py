"""Characterization pins for the three league narrative-article routes.

Written BEFORE the routes were moved out of ``server.py`` into
``src/public_league/articles_api.py`` (CLEANUP-4), and run green against
the unmodified code first, so the extraction is held to the exact
behaviour that shipped rather than to whatever the moved code happens to
do.  What is pinned:

* the OpenAPI operation for each route — operationId, summary,
  description, parameters, request body and responses — compared as a
  whole against a literal captured from the pre-extraction app, plus the
  routes' contiguous order in the document;
* each (path, method) is registered exactly once;
* no other registered route can match an article URL, so registration
  order relative to every other route (and the ``/static`` mount) cannot
  change which handler answers;
* status code, JSON body and ``Cache-Control`` / ``Content-Type`` for a
  request matrix covering the public reads, the 404/400/405/422 edges,
  and every admin-gate outcome of the generate trigger;
* late binding: the generate handler's collaborators are looked up on the
  ``server`` module at REQUEST time, so ``monkeypatch.setattr(server, ...)``
  keeps reaching them (``_require_admin_session``, ``_is_authenticated``,
  ``_get_auth_session``, ``PRIVATE_APP_ALLOWED_USERNAMES``,
  ``_resolve_league_for_request``, ``anthropic``, ``run_in_threadpool``,
  ``log``).

Uses ``app.openapi()`` rather than ``app.routes`` for the registration
checks: ``app.routes`` is version-dependent (FastAPI 0.141 keeps
``include_router`` routers as one opaque entry).
"""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path

import pytest
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

import server
from src.public_league import matchup_narrative as mn

LIST_PATH = "/api/league/articles"
SINGLE_PATH = "/api/league/articles/{season}/{week}/{matchup_id}/{mode}"
GENERATE_PATH = "/api/league/articles/generate"

ARTICLE_OPERATIONS = [(LIST_PATH, "get"), (SINGLE_PATH, "get"), (GENERATE_PATH, "post")]

_VALIDATION_ERROR_RESPONSE = {
    "description": "Validation Error",
    "content": {
        "application/json": {"schema": {"$ref": "#/components/schemas/HTTPValidationError"}}
    },
}

#: Captured from ``server.app.openapi()`` on main ``96da962fa`` before the
#: routes moved.  A difference here is a public-contract change.
EXPECTED_OPENAPI = {
    LIST_PATH: {
        "get": {
            "summary": "Get League Articles",
            "description": (
                "List narrative articles, optionally filtered by season/week.\n\n"
                "Query params:\n"
                "  * ``season`` (optional) — restrict to one season label.\n"
                "  * ``week`` (optional) — restrict to one week within season.\n\n"
                "Returns a flat array of {season, week, mode, matchupId, title,\n"
                "generatedAt, home, away, kicker} so the frontend list page can\n"
                "render a slate without N follow-up requests.  Heavy fields\n"
                "(body, lede) are omitted from the index response — clients fetch\n"
                "them via the single-article endpoint."
            ),
            "operationId": "get_league_articles_api_league_articles_get",
            "responses": {
                "200": {
                    "description": "Successful Response",
                    "content": {"application/json": {"schema": {}}},
                }
            },
        }
    },
    SINGLE_PATH: {
        "get": {
            "summary": "Get League Article",
            "description": "Single article — full body, ready to render.",
            "operationId": (
                "get_league_article_api_league_articles__season___week___matchup_id___mode__get"
            ),
            "parameters": [
                {
                    "name": "season",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string", "title": "Season"},
                },
                {
                    "name": "week",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "integer", "title": "Week"},
                },
                {
                    "name": "matchup_id",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "integer", "title": "Matchup Id"},
                },
                {
                    "name": "mode",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string", "title": "Mode"},
                },
            ],
            "responses": {
                "200": {
                    "description": "Successful Response",
                    "content": {"application/json": {"schema": {}}},
                },
                "422": _VALIDATION_ERROR_RESPONSE,
            },
        }
    },
    GENERATE_PATH: {
        "post": {
            "summary": "Post Generate League Article",
            "description": (
                "Admin trigger: generate a single article on demand.\n\n"
                "Body shape:\n"
                "    {\n"
                '      "season": "2025",         // optional, defaults to current season\n'
                '      "week": 17,                // optional, detector picks live week\n'
                '      "matchupId": 1,            // required for single-article runs\n'
                '      "mode": "preview" | "recap",\n'
                '      "force": true|false        // optional, default false\n'
                "    }\n\n"
                "Returns the generated article on success, 404 if the matchup\n"
                "can't be found in the snapshot, 503 if the Anthropic SDK isn't\n"
                "configured.\n\n"
                "NOTE: this is the synchronous, single-matchup path — full slate\n"
                "generation is the cron's job.  Hold a session at the wheel; this\n"
                "will block for 10-30 seconds while Claude generates."
            ),
            "operationId": "post_generate_league_article_api_league_articles_generate_post",
            "responses": {
                "200": {
                    "description": "Successful Response",
                    "content": {"application/json": {"schema": {}}},
                }
            },
        }
    },
}


@pytest.fixture(scope="module")
def openapi_doc() -> dict:
    return server.app.openapi()


@pytest.fixture
def article_tmpdir(monkeypatch):
    tmp = tempfile.TemporaryDirectory()
    monkeypatch.setenv("LEAGUE_NARRATIVES_DIR", tmp.name)
    yield Path(tmp.name)
    tmp.cleanup()


def _article(season="2025", week=17, matchup_id=1, mode="recap", title="Title"):
    return {
        "mode": mode,
        "season": season,
        "week": week,
        "matchupId": matchup_id,
        "title": title,
        "lede": "Lede.",
        "body": "Body.",
        "kicker": "Kicker.",
        "angleUsed": "championship-stakes",
        "persona": "analyst",
        "wordCount": 250,
        "model": "test-model",
        "generatedAt": "2026-01-07T14:00:00+00:00",
        "isChampionship": True,
        "roundLabel": "Championship",
        "home": {"ownerId": "owner-A", "displayName": "A", "teamName": "Alpha"},
        "away": {"ownerId": "owner-B", "displayName": "B", "teamName": "Beta"},
    }


def _admin(monkeypatch, username="admin", allow=("admin",)):
    monkeypatch.setattr(server, "_is_authenticated", lambda r: True)
    monkeypatch.setattr(server, "_get_auth_session", lambda r: {"username": username})
    monkeypatch.setattr(server, "PRIVATE_APP_ALLOWED_USERNAMES", frozenset(allow))


def _observe(res) -> tuple[int, object, str | None, str | None]:
    try:
        body: object = res.json()
    except ValueError:
        body = res.text
    return (
        res.status_code,
        body,
        res.headers.get("cache-control"),
        res.headers.get("content-type"),
    )


# ── OpenAPI contract ────────────────────────────────────────────────────


def test_openapi_operations_are_pinned_exactly(openapi_doc):
    actual = {path: openapi_doc["paths"][path] for path in EXPECTED_OPENAPI}
    assert json.dumps(actual, sort_keys=True) == json.dumps(EXPECTED_OPENAPI, sort_keys=True)


def test_article_paths_keep_their_contiguous_order(openapi_doc):
    keys = list(openapi_doc["paths"])
    start = keys.index(LIST_PATH)
    assert keys[start : start + 3] == [LIST_PATH, SINGLE_PATH, GENERATE_PATH]


def test_each_operation_registered_exactly_once(openapi_doc):
    op_ids = [
        op["operationId"]
        for methods in openapi_doc["paths"].values()
        for op in methods.values()
        if isinstance(op, dict) and "operationId" in op
    ]
    for path, method in ARTICLE_OPERATIONS:
        op_id = openapi_doc["paths"][path][method]["operationId"]
        assert op_ids.count(op_id) == 1, op_id
    # Only the pinned methods exist on these paths.
    assert set(openapi_doc["paths"][LIST_PATH]) == {"get"}
    assert set(openapi_doc["paths"][SINGLE_PATH]) == {"get"}
    assert set(openapi_doc["paths"][GENERATE_PATH]) == {"post"}


def _template_regex(template: str) -> re.Pattern[str]:
    parts = re.split(r"(\{[^}]+\})", template)
    pattern = "".join(
        ("(?:.+)" if p.endswith(":path}") else "[^/]+") if p.startswith("{") else re.escape(p)
        for p in parts
    )
    return re.compile(f"^{pattern}$")


@pytest.mark.parametrize(
    "url, owner",
    [
        ("/api/league/articles", LIST_PATH),
        ("/api/league/articles/2025/17/1/recap", SINGLE_PATH),
        ("/api/league/articles/generate", GENERATE_PATH),
    ],
)
def test_no_other_route_can_match_an_article_url(openapi_doc, url, owner):
    """Registration order is irrelevant only if nothing else competes.

    Every OpenAPI path template, plus the ``/static`` mount prefix, is
    tested against each concrete article URL; only the owning route may
    match.  (The SPA catch-all was removed from server.py in #555.)
    """
    matching = [t for t in openapi_doc["paths"] if _template_regex(t).match(url)]
    assert matching == [owner]
    assert not url.startswith("/static/")


# ── HTTP behaviour matrix ───────────────────────────────────────────────

_JSON = "application/json"


@pytest.mark.parametrize(
    "method, url, expected",
    [
        (
            "GET",
            "/api/league/articles?season=2025&week=17",
            (
                200,
                {"articles": [], "total": 0, "season": "2025", "week": 17},
                "public, max-age=120",
                _JSON,
            ),
        ),
        (
            "GET",
            "/api/league/articles",
            (
                200,
                {"articles": [], "total": 0, "season": None, "week": None},
                "public, max-age=120",
                _JSON,
            ),
        ),
        (
            "GET",
            "/api/league/articles?week=not-an-int",
            (
                400,
                {"error": "bad_request", "message": "week must be an integer"},
                None,
                _JSON,
            ),
        ),
        (
            "GET",
            "/api/league/articles/2025/17/99/preview",
            (
                404,
                {
                    "error": "not_found",
                    "message": "No preview article on disk for 2025 W17 matchup 99",
                },
                None,
                _JSON,
            ),
        ),
        (
            "GET",
            "/api/league/articles/2025/17/1/garbage",
            (
                400,
                {"error": "bad_request", "message": "mode must be preview|recap"},
                None,
                _JSON,
            ),
        ),
        (
            "GET",
            "/api/league/articles/generate",
            (405, {"detail": "Method Not Allowed"}, None, _JSON),
        ),
        (
            "POST",
            "/api/league/articles",
            (405, {"detail": "Method Not Allowed"}, None, _JSON),
        ),
        (
            "DELETE",
            "/api/league/articles/2025/17/1/recap",
            (405, {"detail": "Method Not Allowed"}, None, _JSON),
        ),
        (
            "POST",
            "/api/league/articles/generate",
            (401, {"error": "auth_required"}, None, _JSON),
        ),
    ],
)
def test_unauthenticated_matrix(article_tmpdir, method, url, expected):
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.request(method, url, json={"mode": "preview", "matchupId": 1})
    assert _observe(res) == expected


def test_single_article_round_trip_headers(article_tmpdir):
    article = _article()
    mn.save_article(article, base=article_tmpdir)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.get("/api/league/articles/2025/17/1/recap")
    status, body, cache, ctype = _observe(res)
    assert (status, cache, ctype) == (200, "public, max-age=300", _JSON)
    assert body == json.loads(json.dumps(mn.load_article("2025", 17, 1, "recap")))


def test_list_hydrates_index_entries(article_tmpdir):
    mn.save_article(_article(mode="preview", title="P"), base=article_tmpdir)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.get("/api/league/articles?season=2025&week=17")
    assert _observe(res) == (
        200,
        {
            "articles": [
                {
                    "season": "2025",
                    "week": 17,
                    "mode": "preview",
                    "matchupId": 1,
                    "title": "P",
                    "kicker": "Kicker.",
                    "angleUsed": "championship-stakes",
                    "isChampionship": True,
                    "roundLabel": "Championship",
                    "home": {"ownerId": "owner-A", "displayName": "A", "teamName": "Alpha"},
                    "away": {"ownerId": "owner-B", "displayName": "B", "teamName": "Beta"},
                    "generatedAt": "2026-01-07T14:00:00+00:00",
                    "wordCount": 250,
                }
            ],
            "total": 1,
            "season": "2025",
            "week": 17,
        },
        "public, max-age=120",
        _JSON,
    )


def test_path_type_validation_is_fastapi_422(article_tmpdir):
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.get("/api/league/articles/2025/notaweek/1/recap")
    status, body, _cache, ctype = _observe(res)
    assert (status, ctype) == (422, _JSON)
    assert [(e["loc"], e["type"]) for e in body["detail"]] == [(["path", "week"], "int_parsing")]


@pytest.mark.parametrize(
    "username, allow, body, expected",
    [
        (
            "randomuser",
            ("someone-else",),
            {"mode": "preview", "matchupId": 1},
            (403, {"error": "admin_required", "message": "Allowlisted users only."}),
        ),
        (
            "admin",
            ("admin",),
            {"mode": "nope", "matchupId": 1},
            (400, {"error": "bad_request", "message": "mode must be preview|recap"}),
        ),
        (
            "admin",
            ("admin",),
            {"mode": "preview"},
            (400, {"error": "bad_request", "message": "matchupId required"}),
        ),
        (
            "admin",
            ("admin",),
            {"mode": "recap", "matchupId": "x"},
            (400, {"error": "bad_request", "message": "matchupId must be an integer"}),
        ),
        (
            "admin",
            ("admin",),
            {"mode": "recap", "matchupId": 1, "week": "x"},
            (400, {"error": "bad_request", "message": "week must be an integer"}),
        ),
    ],
)
def test_generate_admin_gate_and_validation(
    article_tmpdir, monkeypatch, username, allow, body, expected
):
    _admin(monkeypatch, username=username, allow=allow)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.post("/api/league/articles/generate", json=body)
    assert _observe(res)[:2] == expected
    assert _observe(res)[2:] == (None, _JSON)


def test_generate_non_json_body_is_treated_as_empty(article_tmpdir, monkeypatch):
    _admin(monkeypatch)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.post(
            "/api/league/articles/generate",
            content=b"not json",
            headers={"content-type": "text/plain"},
        )
    assert _observe(res)[:2] == (
        400,
        {"error": "bad_request", "message": "mode must be preview|recap"},
    )


# ── Late binding to the server module ───────────────────────────────────


def test_require_admin_session_is_resolved_on_server_at_request_time(article_tmpdir, monkeypatch):
    monkeypatch.setattr(
        server,
        "_require_admin_session",
        lambda request: JSONResponse(status_code=418, content={"error": "patched"}),
    )
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.post("/api/league/articles/generate", json={"mode": "preview", "matchupId": 1})
    assert _observe(res)[:2] == (418, {"error": "patched"})


def test_league_resolution_error_is_resolved_on_server(article_tmpdir, monkeypatch):
    _admin(monkeypatch)

    def _refuse(request, body=None):
        raise server.LeagueResolutionError(400, "unknown_league", "patched resolver")

    monkeypatch.setattr(server, "_resolve_league_for_request", _refuse)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.post("/api/league/articles/generate", json={"mode": "preview", "matchupId": 1})
    status, body, _cache, _ctype = _observe(res)
    assert status == 400
    assert body["error"] == "unknown_league"


def test_anthropic_none_on_server_means_503(article_tmpdir, monkeypatch):
    _admin(monkeypatch)
    monkeypatch.setenv("SLEEPER_LEAGUE_ID", "test-league-id")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake")
    monkeypatch.setattr(server, "anthropic", None)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.post("/api/league/articles/generate", json={"mode": "preview", "matchupId": 1})
    assert _observe(res)[:2] == (
        503,
        {"error": "anthropic_unavailable", "message": "anthropic SDK not installed"},
    )


def test_missing_api_key_means_503(article_tmpdir, monkeypatch):
    _admin(monkeypatch)
    monkeypatch.setenv("SLEEPER_LEAGUE_ID", "test-league-id")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(server, "anthropic", object())
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.post("/api/league/articles/generate", json={"mode": "preview", "matchupId": 1})
    assert _observe(res)[:2] == (
        503,
        {"error": "anthropic_unavailable", "message": "ANTHROPIC_API_KEY not configured"},
    )


class _FakeAnthropic:
    def __init__(self):
        self.calls: list[dict] = []

    def AsyncAnthropic(self, **kwargs):  # noqa: N802 — mirrors the SDK attribute
        self.calls.append(kwargs)
        return object()


def _stub_generation_path(monkeypatch, *, snapshot_calls: list, log_calls: list):
    from src.public_league.snapshot import PublicLeagueSnapshot, SeasonSnapshot

    season = SeasonSnapshot(
        season="2025",
        league_id="test",
        league={},
        users=[],
        rosters=[],
        matchups_by_week={},
        transactions_by_week={},
        drafts=[],
        draft_picks_by_draft={},
        traded_picks=[],
        winners_bracket=[],
        losers_bracket=[],
    )
    snapshot = PublicLeagueSnapshot(
        root_league_id="test", generated_at="2025-01-01T00:00:00", seasons=[season]
    )

    async def _threadpool(fn, *args, **kwargs):
        snapshot_calls.append((getattr(fn, "__name__", repr(fn)), args))
        return snapshot

    monkeypatch.setattr(server, "run_in_threadpool", _threadpool)

    real_log = server.log

    class _Log:
        """Records ``warning`` calls; everything else goes to the real logger
        (app startup logs through ``server.log`` too)."""

        def warning(self, msg, *args, **kwargs):
            if str(msg).startswith("league_article"):
                log_calls.append((msg, kwargs.get("extra")))
            else:
                real_log.warning(msg, *args, **kwargs)

        def __getattr__(self, name):
            return getattr(real_log, name)

    monkeypatch.setattr(server, "log", _Log())
    monkeypatch.setattr(mn, "build_brief", lambda *a, **k: object())
    monkeypatch.setattr(mn, "collect_prior_articles", lambda *a, **k: [])


def test_generate_success_uses_server_collaborators(article_tmpdir, monkeypatch):
    _admin(monkeypatch)
    monkeypatch.setenv("SLEEPER_LEAGUE_ID", "test-league-id")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake")
    fake = _FakeAnthropic()
    monkeypatch.setattr(server, "anthropic", fake)
    snapshot_calls: list = []
    log_calls: list = []
    _stub_generation_path(monkeypatch, snapshot_calls=snapshot_calls, log_calls=log_calls)
    generated = _article(mode="preview", title="Fresh")

    async def _generate(**kwargs):
        return generated

    monkeypatch.setattr(mn, "generate_article", _generate)
    body = {"mode": "preview", "matchupId": 1, "season": "2025", "week": 17}
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.post("/api/league/articles/generate", json=body)
    assert _observe(res) == (200, {"article": generated, "regenerated": True}, None, _JSON)
    assert snapshot_calls == [("build_public_snapshot", ("test-league-id",))]
    assert fake.calls == [{"api_key": "fake"}]
    assert log_calls == []
    # Second call without force is a cache hit on the article just saved.
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.post("/api/league/articles/generate", json=body)
    status, payload, _cache, _ctype = _observe(res)
    assert status == 200 and payload["regenerated"] is False
    assert payload["article"]["title"] == "Fresh"


def test_generate_failure_logs_on_server_logger(article_tmpdir, monkeypatch):
    _admin(monkeypatch)
    monkeypatch.setenv("SLEEPER_LEAGUE_ID", "test-league-id")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake")
    monkeypatch.setattr(server, "anthropic", _FakeAnthropic())
    snapshot_calls: list = []
    log_calls: list = []
    _stub_generation_path(monkeypatch, snapshot_calls=snapshot_calls, log_calls=log_calls)

    async def _boom(**kwargs):
        raise ValueError("bad upstream")

    monkeypatch.setattr(mn, "generate_article", _boom)
    body = {"mode": "recap", "matchupId": 3, "season": "2025", "week": 17}
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.post("/api/league/articles/generate", json=body)
    assert _observe(res) == (
        502,
        {"error": "generation_failed", "errorType": "ValueError", "message": "bad upstream"},
        None,
        _JSON,
    )
    assert log_calls == [
        (
            "league_article_generation_failed",
            {
                "season": "2025",
                "week": 17,
                "matchupId": 3,
                "mode": "recap",
                "error_type": "ValueError",
            },
        )
    ]


def test_generate_unknown_matchup_is_404(article_tmpdir, monkeypatch):
    _admin(monkeypatch)
    monkeypatch.setenv("SLEEPER_LEAGUE_ID", "test-league-id")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake")
    monkeypatch.setattr(server, "anthropic", _FakeAnthropic())
    _stub_generation_path(monkeypatch, snapshot_calls=[], log_calls=[])
    monkeypatch.setattr(mn, "build_brief", lambda *a, **k: None)
    body = {"mode": "recap", "matchupId": 9, "season": "2025", "week": 17}
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.post("/api/league/articles/generate", json=body)
    assert _observe(res)[:2] == (
        404,
        {"error": "matchup_not_found", "message": "no matchup_id=9 in 2025 W17"},
    )
