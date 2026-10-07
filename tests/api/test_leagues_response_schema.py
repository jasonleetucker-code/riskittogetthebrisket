"""The live /api/leagues route enforces distinct public and signed-in schemas."""

import json

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import server
from src.api import league_registry
from src.api.schemas.leagues import AuthenticatedLeaguesResponse, PublicLeaguesResponse


@pytest.fixture
def league_route(tmp_path, monkeypatch):
    registry = tmp_path / "leagues.json"
    registry.write_text(
        json.dumps(
            {
                "defaultLeagueKey": "main",
                "leagues": [
                    {
                        "key": "main",
                        "displayName": "Main",
                        "sleeperLeagueId": "PRIVATE-SLEEPER-123",
                        "active": True,
                        "rosterSettings": {"teamCount": 12, "starters": {"QB": 1}},
                        "defaultTeamMap": {
                            "alice": {"ownerId": "alice-owner", "teamName": "Alice Team"}
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("LEAGUE_REGISTRY_PATH", str(registry))
    league_registry.reload_registry()
    monkeypatch.setattr(server, "_fetch_sleeper_league_name", lambda _: None)
    yield
    league_registry.reload_registry()


def test_anonymous_view_contains_only_public_fields(league_route, monkeypatch):
    monkeypatch.setattr(server, "_get_auth_session", lambda _: None)
    response = TestClient(server.app).get("/api/leagues")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert set(body) == {"leagues", "defaultKey"}
    assert body["defaultKey"] == "main"
    assert set(body["leagues"][0]) == {
        "key",
        "displayName",
        "scoringProfile",
        "idpEnabled",
        "bestBall",
        "rosterSettings",
        "active",
    }
    assert "PRIVATE-SLEEPER-123" not in response.text
    assert "alice-owner" not in response.text


def test_authenticated_view_adds_only_this_users_defaults(league_route, monkeypatch):
    monkeypatch.setattr(server, "_get_auth_session", lambda _: {"username": "alice"})
    response = TestClient(server.app).get("/api/leagues")
    assert response.status_code == 200
    body = response.json()
    assert body["userDefaultKey"] == "main"
    assert body["leagues"][0]["userDefaultTeam"] == {
        "ownerId": "alice-owner",
        "teamName": "Alice Team",
    }
    assert "PRIVATE-SLEEPER-123" not in response.text


def test_schema_refuses_private_or_unexpected_fields(league_route, monkeypatch):
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        PublicLeaguesResponse.model_validate(
            {
                "leagues": [
                    {
                        "key": "main",
                        "displayName": "Main",
                        "scoringProfile": "default",
                        "idpEnabled": False,
                        "bestBall": False,
                        "rosterSettings": {},
                        "active": True,
                        "sleeperLeagueId": "PRIVATE-SLEEPER-123",
                    }
                ],
                "defaultKey": "main",
            }
        )

    original = league_registry.LeagueConfig.public_dict

    def leaked_public_dict(cfg):
        return {**original(cfg), "userDefaultTeam": {"ownerId": "other-user"}}

    monkeypatch.setattr(league_registry.LeagueConfig, "public_dict", leaked_public_dict)
    monkeypatch.setattr(server, "_get_auth_session", lambda _: None)
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        TestClient(server.app).get("/api/leagues")


def test_openapi_documents_two_closed_views(league_route):
    document = server.app.openapi()
    response_schema = document["paths"]["/api/leagues"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    assert len(response_schema["anyOf"]) == 2
    components = document["components"]["schemas"]
    for name in (
        "PublicLeague",
        "AuthenticatedLeague",
        "PublicLeaguesResponse",
        "AuthenticatedLeaguesResponse",
        "UserDefaultTeam",
    ):
        assert components[name]["additionalProperties"] is False
    assert "sleeperLeagueId" not in str(response_schema)


def test_absent_default_league_is_explicitly_null():
    anonymous = PublicLeaguesResponse.model_validate({"leagues": [], "defaultKey": None})
    authenticated = AuthenticatedLeaguesResponse.model_validate(
        {"leagues": [], "defaultKey": None, "userDefaultKey": None}
    )
    assert anonymous.model_dump(by_alias=True)["defaultKey"] is None
    assert authenticated.model_dump(by_alias=True)["userDefaultKey"] is None
