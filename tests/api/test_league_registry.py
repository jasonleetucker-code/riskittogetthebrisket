"""Tests for ``src.api.league_registry``.

The registry is the single source of truth for every configured
league.  These tests pin down:

* JSON parsing (valid + malformed entries)
* Fallback to ``SLEEPER_LEAGUE_ID`` env var when no file exists
* Helper lookups (by key, by alias, default league, user default)
* Roster settings accessor
* ``LEAGUE_REGISTRY_PATH`` env override resolution
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.api import league_registry


@pytest.fixture(autouse=True)
def _reset_registry(monkeypatch):
    """Clear module-level cache and env overrides before each test.

    Without this, tests that load a fixture file would leak the
    cached state into the next test.  We also null out the env vars
    the registry consults so tests have a clean starting point —
    each test opts in explicitly.
    """
    monkeypatch.delenv("SLEEPER_LEAGUE_ID", raising=False)
    monkeypatch.delenv("SLEEPER_LEAGUE_NAME", raising=False)
    monkeypatch.delenv("SLEEPER_LEAGUE_IDP_ENABLED", raising=False)
    monkeypatch.delenv("LEAGUE_REGISTRY_PATH", raising=False)
    league_registry.reload_registry()
    yield
    league_registry.reload_registry()


def _write_registry(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


# ── Basic parsing + lookups ───────────────────────────────────────


def test_load_from_file_returns_configured_leagues(tmp_path, monkeypatch):
    path = _write_registry(
        tmp_path,
        {
            "schemaVersion": 1,
            "defaultLeagueKey": "main",
            "leagues": [
                {
                    "key": "main",
                    "displayName": "Main League",
                    "sleeperLeagueId": "12345",
                    "scoringProfile": "superflex_tep15",
                    "idpEnabled": True,
                    "active": True,
                    "rosterSettings": {"teamCount": 12},
                },
                {
                    "key": "secondary",
                    "displayName": "Secondary League",
                    "sleeperLeagueId": "67890",
                    "scoringProfile": "superflex_tep15",
                    "idpEnabled": False,
                    "active": True,
                    "rosterSettings": {"teamCount": 10},
                },
            ],
        },
    )
    monkeypatch.setenv("LEAGUE_REGISTRY_PATH", str(path))
    league_registry.reload_registry()

    leagues = league_registry.all_leagues()
    assert [c.key for c in leagues] == ["main", "secondary"]
    assert league_registry.get_default_league().key == "main"
    assert league_registry.get_sleeper_league_id() == "12345"
    assert league_registry.get_sleeper_league_id("secondary") == "67890"


def test_get_league_by_key_matches_alias(tmp_path, monkeypatch):
    path = _write_registry(
        tmp_path,
        {
            "leagues": [
                {
                    "key": "dynasty_main",
                    "displayName": "Main",
                    "sleeperLeagueId": "12345",
                    "aliases": ["main", "idp"],
                    "rosterSettings": {},
                },
            ],
        },
    )
    monkeypatch.setenv("LEAGUE_REGISTRY_PATH", str(path))
    league_registry.reload_registry()

    assert league_registry.get_league_by_key("dynasty_main").key == "dynasty_main"
    assert league_registry.get_league_by_key("main").key == "dynasty_main"
    assert league_registry.get_league_by_key("IDP").key == "dynasty_main"  # case-insensitive
    assert league_registry.get_league_by_key("unknown") is None
    assert league_registry.get_league_by_key(None) is None
    assert league_registry.get_league_by_key("") is None


def test_default_league_falls_back_to_first_active(tmp_path, monkeypatch):
    """When defaultLeagueKey is missing, the first *active* league wins
    — not just the first listed.  Inactive leagues are skipped."""
    path = _write_registry(
        tmp_path,
        {
            "leagues": [
                {
                    "key": "inactive_one",
                    "displayName": "Off",
                    "sleeperLeagueId": "1",
                    "active": False,
                    "rosterSettings": {},
                },
                {
                    "key": "active_one",
                    "displayName": "On",
                    "sleeperLeagueId": "2",
                    "active": True,
                    "rosterSettings": {},
                },
            ],
        },
    )
    monkeypatch.setenv("LEAGUE_REGISTRY_PATH", str(path))
    league_registry.reload_registry()

    assert league_registry.get_default_league().key == "active_one"


def test_active_leagues_excludes_inactive(tmp_path, monkeypatch):
    path = _write_registry(
        tmp_path,
        {
            "leagues": [
                {"key": "a", "displayName": "A", "sleeperLeagueId": "1", "active": True, "rosterSettings": {}},
                {"key": "b", "displayName": "B", "sleeperLeagueId": "2", "active": False, "rosterSettings": {}},
                {"key": "c", "displayName": "C", "sleeperLeagueId": "3", "active": True, "rosterSettings": {}},
            ],
        },
    )
    monkeypatch.setenv("LEAGUE_REGISTRY_PATH", str(path))
    league_registry.reload_registry()

    active = [c.key for c in league_registry.active_leagues()]
    assert active == ["a", "c"]
    # all_leagues still returns everything
    assert len(league_registry.all_leagues()) == 3


def test_get_user_default_league_uses_team_map(tmp_path, monkeypatch):
    """A user whose username appears in any active league's
    default_team_map lands on THAT league, not the global default."""
    path = _write_registry(
        tmp_path,
        {
            "defaultLeagueKey": "primary",
            "leagues": [
                {
                    "key": "primary",
                    "displayName": "Primary",
                    "sleeperLeagueId": "1",
                    "active": True,
                    "rosterSettings": {},
                    "defaultTeamMap": {},
                },
                {
                    "key": "secondary",
                    "displayName": "Secondary",
                    "sleeperLeagueId": "2",
                    "active": True,
                    "rosterSettings": {},
                    "defaultTeamMap": {
                        "alice": {"ownerId": "", "teamName": "Alice's Team"},
                    },
                },
            ],
        },
    )
    monkeypatch.setenv("LEAGUE_REGISTRY_PATH", str(path))
    league_registry.reload_registry()

    assert league_registry.get_user_default_league("alice").key == "secondary"
    assert league_registry.get_user_default_league("ALICE").key == "secondary"  # case-insensitive
    assert league_registry.get_user_default_league("bob").key == "primary"  # fallback
    assert league_registry.get_user_default_league(None).key == "primary"
    assert league_registry.get_user_default_league("").key == "primary"


def test_get_user_default_skips_inactive_team_map_match(tmp_path, monkeypatch):
    """If the only league that lists a user is inactive, we fall back
    to the default league rather than steering the user onto a
    disabled league."""
    path = _write_registry(
        tmp_path,
        {
            "defaultLeagueKey": "main",
            "leagues": [
                {"key": "main", "displayName": "Main", "sleeperLeagueId": "1", "active": True, "rosterSettings": {}},
                {
                    "key": "disabled",
                    "displayName": "Off",
                    "sleeperLeagueId": "2",
                    "active": False,
                    "rosterSettings": {},
                    "defaultTeamMap": {"alice": {"ownerId": "x", "teamName": "A"}},
                },
            ],
        },
    )
    monkeypatch.setenv("LEAGUE_REGISTRY_PATH", str(path))
    league_registry.reload_registry()

    assert league_registry.get_user_default_league("alice").key == "main"


def test_get_league_roster_settings_returns_copy(tmp_path, monkeypatch):
    """Caller mutations must not leak into the registry cache."""
    path = _write_registry(
        tmp_path,
        {
            "leagues": [
                {
                    "key": "main",
                    "displayName": "Main",
                    "sleeperLeagueId": "1",
                    "active": True,
                    "rosterSettings": {"teamCount": 12, "starters": {"QB": 1}},
                },
            ],
        },
    )
    monkeypatch.setenv("LEAGUE_REGISTRY_PATH", str(path))
    league_registry.reload_registry()

    settings = league_registry.get_league_roster_settings("main")
    assert settings["teamCount"] == 12
    settings["teamCount"] = 99  # mutate the copy
    fresh = league_registry.get_league_roster_settings("main")
    assert fresh["teamCount"] == 12, "registry should hand out fresh copies"


def test_get_league_roster_settings_unknown_key_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("SLEEPER_LEAGUE_ID", "12345")
    league_registry.reload_registry()
    assert league_registry.get_league_roster_settings("nonexistent") == {}


# ── Env-var fallback path ─────────────────────────────────────────


def test_falls_back_to_env_var_when_no_registry_file(monkeypatch, tmp_path):
    """Existing single-league deployments without a registry.json
    file must keep working via the SLEEPER_LEAGUE_ID env var."""
    nonexistent = tmp_path / "missing.json"
    monkeypatch.setenv("LEAGUE_REGISTRY_PATH", str(nonexistent))
    monkeypatch.setenv("SLEEPER_LEAGUE_ID", "99999")
    league_registry.reload_registry()

    default = league_registry.get_default_league()
    assert default is not None
    assert default.key == "default"
    assert default.sleeper_league_id == "99999"
    assert default.active is True
    # Should also match by the synthesized "main" alias.
    assert league_registry.get_league_by_key("main").sleeper_league_id == "99999"


def test_no_registry_and_no_env_var_returns_none(monkeypatch, tmp_path):
    """Fresh developer box with no config + no env: everything works
    but returns None/empty.  Callers must handle this gracefully."""
    nonexistent = tmp_path / "missing.json"
    monkeypatch.setenv("LEAGUE_REGISTRY_PATH", str(nonexistent))
    # SLEEPER_LEAGUE_ID already cleared by the fixture
    league_registry.reload_registry()

    assert league_registry.get_default_league() is None
    assert league_registry.all_leagues() == []
    assert league_registry.active_leagues() == []
    assert league_registry.get_sleeper_league_id() is None
    assert league_registry.default_league_key() is None


# ── Malformed input ───────────────────────────────────────────────


def test_skips_malformed_entries_keeps_good_ones(tmp_path, monkeypatch, caplog):
    path = _write_registry(
        tmp_path,
        {
            "leagues": [
                {"displayName": "Missing Key"},  # no key → skipped
                {"key": "missing_id", "displayName": "Missing ID"},  # no sleeperLeagueId
                {"key": "ok", "displayName": "OK", "sleeperLeagueId": "5", "rosterSettings": {}},
            ],
        },
    )
    monkeypatch.setenv("LEAGUE_REGISTRY_PATH", str(path))
    league_registry.reload_registry()

    keys = [c.key for c in league_registry.all_leagues()]
    assert keys == ["ok"], "bad entries should be skipped, good one kept"


def test_duplicate_keys_keep_first(tmp_path, monkeypatch):
    path = _write_registry(
        tmp_path,
        {
            "leagues": [
                {"key": "dup", "displayName": "First", "sleeperLeagueId": "1", "rosterSettings": {}},
                {"key": "dup", "displayName": "Second", "sleeperLeagueId": "2", "rosterSettings": {}},
            ],
        },
    )
    monkeypatch.setenv("LEAGUE_REGISTRY_PATH", str(path))
    league_registry.reload_registry()

    cfg = league_registry.get_league_by_key("dup")
    assert cfg.display_name == "First"
    assert cfg.sleeper_league_id == "1"
    # Only one entry total.
    assert len(league_registry.all_leagues()) == 1


def test_invalid_json_returns_empty_then_env_fallback(tmp_path, monkeypatch):
    """A corrupt registry file shouldn't brick the server — log the
    error and fall through to the env-var fallback."""
    path = tmp_path / "registry.json"
    path.write_text("{ not valid json", encoding="utf-8")
    monkeypatch.setenv("LEAGUE_REGISTRY_PATH", str(path))
    monkeypatch.setenv("SLEEPER_LEAGUE_ID", "77777")
    league_registry.reload_registry()

    # Falls back to env var; a single league synthesized from it.
    assert league_registry.get_default_league().sleeper_league_id == "77777"


# ── public_dict() API response shape ──────────────────────────────


def test_public_dict_omits_sleeper_id(tmp_path, monkeypatch):
    """The /api/leagues response must not include the Sleeper ID —
    the registry key is the public identifier."""
    path = _write_registry(
        tmp_path,
        {
            "leagues": [
                {
                    "key": "main",
                    "displayName": "Main",
                    "sleeperLeagueId": "SECRET-ID-123",
                    "scoringProfile": "ppr1",
                    "idpEnabled": True,
                    "active": True,
                    "rosterSettings": {"teamCount": 12},
                },
            ],
        },
    )
    monkeypatch.setenv("LEAGUE_REGISTRY_PATH", str(path))
    league_registry.reload_registry()

    payload = league_registry.get_league_by_key("main").public_dict()
    assert payload["key"] == "main"
    assert payload["displayName"] == "Main"
    assert payload["idpEnabled"] is True
    assert payload["scoringProfile"] == "ppr1"
    assert payload["rosterSettings"] == {"teamCount": 12}
    assert payload["active"] is True
    assert "sleeperLeagueId" not in payload
    assert "SECRET-ID-123" not in json.dumps(payload)


def test_api_leagues_endpoint_returns_active_leagues(tmp_path, monkeypatch):
    """GET /api/leagues returns the list of active leagues with no
    Sleeper IDs leaked.  Unauthenticated clients don't see
    userDefaultKey."""
    from fastapi.testclient import TestClient

    import server

    path = _write_registry(
        tmp_path,
        {
            "defaultLeagueKey": "main",
            "leagues": [
                {
                    "key": "main",
                    "displayName": "Main League",
                    "sleeperLeagueId": "SECRET-111",
                    "idpEnabled": True,
                    "active": True,
                    "rosterSettings": {"teamCount": 12},
                },
                {
                    "key": "off",
                    "displayName": "Off League",
                    "sleeperLeagueId": "SECRET-222",
                    "idpEnabled": False,
                    "active": False,
                    "rosterSettings": {},
                },
            ],
        },
    )
    monkeypatch.setenv("LEAGUE_REGISTRY_PATH", str(path))
    league_registry.reload_registry()

    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.get("/api/leagues")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["defaultKey"] == "main"
    # Only active leagues listed.
    assert [lg["key"] for lg in body["leagues"]] == ["main"]
    assert body["leagues"][0]["displayName"] == "Main League"
    # No Sleeper ID anywhere in the response.
    assert "SECRET-111" not in res.text
    assert "SECRET-222" not in res.text
    # Anonymous callers don't get userDefaultKey.
    assert "userDefaultKey" not in body


def test_default_team_map_lowercase_keys(tmp_path, monkeypatch):
    """Usernames are lower-cased on read so lookups are
    case-insensitive without touching the caller."""
    path = _write_registry(
        tmp_path,
        {
            "leagues": [
                {
                    "key": "main",
                    "displayName": "Main",
                    "sleeperLeagueId": "1",
                    "active": True,
                    "rosterSettings": {},
                    "defaultTeamMap": {
                        "JasonLeeTucker": {"ownerId": "abc", "teamName": "T1"},
                    },
                },
            ],
        },
    )
    monkeypatch.setenv("LEAGUE_REGISTRY_PATH", str(path))
    league_registry.reload_registry()

    cfg = league_registry.get_league_by_key("main")
    assert "jasonleetucker" in cfg.default_team_map
    assert cfg.default_team_map["jasonleetucker"] == {"ownerId": "abc", "teamName": "T1"}
