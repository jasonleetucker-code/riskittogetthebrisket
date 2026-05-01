"""End-to-end tests for the /api/league/articles endpoints.

These hit the FastAPI app via TestClient with the article filesystem
pointed at a tmpdir. We don't exercise the Anthropic generator here —
that path is covered in tests/public_league/test_matchup_narrative.py
with a fake client. Here we verify:

    * GET /api/league/articles returns a slate-shaped index.
    * GET .../{season}/{week}/{matchupId}/{mode} returns the full
      article, 404 when missing.
    * POST /api/league/articles/generate gates on admin auth and
      returns 503 when ANTHROPIC_API_KEY is missing.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import server
from src.public_league import matchup_narrative as mn


@pytest.fixture
def article_tmpdir(monkeypatch):
    tmp = tempfile.TemporaryDirectory()
    monkeypatch.setenv("LEAGUE_NARRATIVES_DIR", tmp.name)
    yield Path(tmp.name)
    tmp.cleanup()


def _make_article(season="2025", week=17, matchup_id=1, mode="recap", title="Title"):
    return {
        "mode": mode,
        "season": season,
        "week": week,
        "matchupId": matchup_id,
        "title": title,
        "lede": "Lede.",
        "body": "Body paragraph 1.\n\nBody paragraph 2.",
        "kicker": "A kicker line.",
        "angleUsed": "championship-stakes",
        "persona": "analyst",
        "wordCount": 250,
        "model": "claude-opus-4-7",
        "generatedAt": "2026-01-07T14:00:00+00:00",
        "isChampionship": True,
        "roundLabel": "Championship",
        "home": {"ownerId": "owner-A", "displayName": "AAron", "teamName": "Brisket Bandits"},
        "away": {"ownerId": "owner-B", "displayName": "Bea", "teamName": "Beast Mode"},
        "usage": {"input_tokens": 100, "output_tokens": 200,
                  "cache_read_input_tokens": 0, "cache_creation_input_tokens": 100},
    }


def test_list_empty_returns_empty_array(article_tmpdir):
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.get("/api/league/articles?season=2025&week=17")
    assert res.status_code == 200
    body = res.json()
    assert body["articles"] == []
    assert body["total"] == 0
    assert body["season"] == "2025"
    assert body["week"] == 17


def test_list_returns_index_after_save(article_tmpdir):
    mn.save_article(_make_article(matchup_id=1, mode="preview", title="Preview"), base=article_tmpdir)
    mn.save_article(_make_article(matchup_id=1, mode="recap", title="Recap"), base=article_tmpdir)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.get("/api/league/articles?season=2025&week=17")
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 2
    titles = sorted(a["title"] for a in body["articles"])
    assert titles == ["Preview", "Recap"]
    # Index entries don't carry the body — only the lighter fields.
    for art in body["articles"]:
        assert "body" not in art
        assert "title" in art
        assert "kicker" in art
        assert "home" in art


def test_list_bad_week_returns_400(article_tmpdir):
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.get("/api/league/articles?week=not-an-int")
    assert res.status_code == 400


def test_get_single_article_round_trip(article_tmpdir):
    article = _make_article(matchup_id=1, mode="recap")
    mn.save_article(article, base=article_tmpdir)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.get("/api/league/articles/2025/17/1/recap")
    assert res.status_code == 200
    body = res.json()
    assert body["title"] == "Title"
    assert "body" in body
    assert body["isChampionship"] is True


def test_get_single_article_missing_returns_404(article_tmpdir):
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.get("/api/league/articles/2025/17/99/preview")
    assert res.status_code == 404
    assert res.json()["error"] == "not_found"


def test_get_single_article_bad_mode_returns_400(article_tmpdir):
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.get("/api/league/articles/2025/17/1/garbage")
    assert res.status_code == 400


def test_generate_requires_auth(article_tmpdir):
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.post("/api/league/articles/generate", json={"mode": "preview", "matchupId": 1})
    assert res.status_code == 401


def test_generate_requires_admin(article_tmpdir, monkeypatch):
    monkeypatch.setattr(server, "_is_authenticated", lambda r: True)
    monkeypatch.setattr(server, "_get_auth_session", lambda r: {"username": "randomuser"})
    monkeypatch.setattr(
        server, "PRIVATE_APP_ALLOWED_USERNAMES", frozenset({"jasonleetucker"}),
    )
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.post("/api/league/articles/generate", json={"mode": "preview", "matchupId": 1})
    assert res.status_code == 403


def test_generate_validates_mode(article_tmpdir, monkeypatch):
    monkeypatch.setattr(server, "_is_authenticated", lambda r: True)
    monkeypatch.setattr(server, "_get_auth_session", lambda r: {"username": "admin"})
    monkeypatch.setattr(
        server, "PRIVATE_APP_ALLOWED_USERNAMES", frozenset({"admin"}),
    )
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.post("/api/league/articles/generate", json={"mode": "nope", "matchupId": 1})
    assert res.status_code == 400


def test_generate_validates_matchup_id(article_tmpdir, monkeypatch):
    monkeypatch.setattr(server, "_is_authenticated", lambda r: True)
    monkeypatch.setattr(server, "_get_auth_session", lambda r: {"username": "admin"})
    monkeypatch.setattr(
        server, "PRIVATE_APP_ALLOWED_USERNAMES", frozenset({"admin"}),
    )
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.post("/api/league/articles/generate", json={"mode": "preview"})
    assert res.status_code == 400


def test_generate_returns_503_when_anthropic_unconfigured(article_tmpdir, monkeypatch):
    """With no API key + no SDK, the generator endpoint refuses to
    pretend it generated something.  Returns 503 so callers know the
    runtime isn't ready, not a misleading 200.

    The cache-hit short-circuit (existing article + force=false) is
    covered at the module level in
    tests/public_league/test_matchup_narrative.py — duplicating it
    here would require stubbing the league registry + snapshot
    builder, which would test the stubs more than the contract."""
    monkeypatch.setattr(server, "_is_authenticated", lambda r: True)
    monkeypatch.setattr(server, "_get_auth_session", lambda r: {"username": "admin"})
    monkeypatch.setattr(
        server, "PRIVATE_APP_ALLOWED_USERNAMES", frozenset({"admin"}),
    )
    # Provision a league via the env-var fallback so the resolver
    # finds something (anything — we never hit the snapshot path).
    monkeypatch.setenv("SLEEPER_LEAGUE_ID", "test-league-id")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    body = {"mode": "preview", "matchupId": 1, "season": "2025", "week": 17}
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.post("/api/league/articles/generate", json=body)
    # 503 because the SDK / API key isn't configured. The endpoint
    # checks this BEFORE building the snapshot to avoid wasting a
    # Sleeper round-trip.
    assert res.status_code == 503, res.text
    assert res.json()["error"] == "anthropic_unavailable"
