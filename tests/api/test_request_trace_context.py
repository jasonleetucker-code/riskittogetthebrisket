"""W3C trace continuity and bounded, fail-open HTTP telemetry on the live route."""

import json
import logging

from fastapi.testclient import TestClient

import server
from src.api import league_registry
from src.utils import request_context

TRACE_ID = "a" * 32
PARENT_SPAN_ID = "b" * 16
TRACEPARENT = f"00-{TRACE_ID}-{PARENT_SPAN_ID}-01"


def test_traceparent_rejects_invalid_or_zero_ids():
    assert request_context.parse_traceparent(TRACEPARENT) == (TRACE_ID, PARENT_SPAN_ID, "01")
    for value in (
        None,
        "",
        "bogus",
        f"00-{'0' * 32}-{PARENT_SPAN_ID}-01",
        f"00-{TRACE_ID}-{'0' * 16}-01",
        TRACEPARENT + "\nsecret",
    ):
        assert request_context.parse_traceparent(value) is None


def test_client_request_id_cannot_put_private_text_into_trace_log(caplog):
    with caplog.at_level(logging.INFO, logger="calculator.trace"):
        response = TestClient(server.app).get(
            "/api/leagues", headers={"x-request-id": "private data"}
        )
    assert response.status_code == 200
    assert response.headers["x-request-id"] != "private data"
    span = json.loads(
        next(record.message for record in caplog.records if record.name == "calculator.trace")
    )
    assert span["request_id"] == response.headers["x-request-id"]
    assert "private data" not in json.dumps(span)


def test_live_leagues_keeps_trace_id_and_emits_private_free_span(tmp_path, monkeypatch, caplog):
    path = tmp_path / "registry.json"
    path.write_text(
        json.dumps(
            {
                "defaultLeagueKey": "main",
                "leagues": [
                    {
                        "key": "main",
                        "displayName": "Main",
                        "sleeperLeagueId": "PRIVATE-ID-123",
                        "defaultTeamMap": {
                            "alice": {"ownerId": "owner-secret", "teamName": "private"}
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("LEAGUE_REGISTRY_PATH", str(path))
    league_registry.reload_registry()
    monkeypatch.setattr(server, "_fetch_sleeper_league_name", lambda _: None)
    monkeypatch.setattr(server, "_get_auth_session", lambda _: {"username": "alice"})
    with caplog.at_level(logging.INFO, logger="calculator.trace"):
        response = TestClient(server.app).get(
            "/api/leagues", headers={"traceparent": TRACEPARENT, "cookie": "secret-cookie=abc"}
        )
    assert response.status_code == 200
    assert response.headers["x-trace-id"] == TRACE_ID
    assert response.headers["traceparent"].startswith(f"00-{TRACE_ID}-")
    assert PARENT_SPAN_ID not in response.headers["traceparent"]
    span = json.loads(
        next(record.message for record in caplog.records if record.name == "calculator.trace")
    )
    assert span["trace_id"] == TRACE_ID
    assert span["parent_span_id"] == PARENT_SPAN_ID
    assert span["span_id"] == response.headers["traceparent"].split("-")[2]
    assert span["request_id"] == response.headers["x-request-id"]
    assert span["http_route"] == "/api/leagues"
    assert span["http_status_code"] == 200
    assert span["duration_ms"] >= 0
    assert span["failure_class"] is None
    for secret in ("PRIVATE-ID-123", "owner-secret", "secret-cookie", "alice"):
        assert secret not in json.dumps(span)
    league_registry.reload_registry()


def test_separate_requests_get_distinct_traces_and_export_failure_is_harmless(monkeypatch):
    league_registry.reload_registry()
    monkeypatch.setattr(server, "_fetch_sleeper_league_name", lambda _: None)
    monkeypatch.setattr(server, "_get_auth_session", lambda _: None)
    client = TestClient(server.app)
    first = client.get("/api/leagues")
    second = client.get("/api/leagues")
    assert first.status_code == second.status_code == 200
    assert first.headers["x-trace-id"] != second.headers["x-trace-id"]

    def broken_exporter(**kwargs):
        raise RuntimeError("logging unavailable")

    monkeypatch.setattr(request_context, "emit_http_span", broken_exporter)
    response = client.get("/api/leagues")
    assert response.status_code == 200
    assert response.headers["x-trace-id"]


def test_failed_league_request_emits_failed_span(monkeypatch, caplog):
    monkeypatch.setattr(server, "_get_auth_session", lambda _: None)
    config = league_registry.LeagueConfig(
        key="main",
        display_name="Main",
        sleeper_league_id="PRIVATE-ID-123",
        scoring_profile="default",
        roster_settings={},
        idp_enabled=False,
    )
    monkeypatch.setattr(league_registry, "active_leagues", lambda: [config])
    monkeypatch.setattr(league_registry, "default_league_key", lambda: "main")

    def fail_source(_):
        raise RuntimeError("secret upstream detail")

    monkeypatch.setattr(server, "_fetch_sleeper_league_name", fail_source)
    with caplog.at_level(logging.INFO, logger="calculator.trace"):
        response = TestClient(server.app, raise_server_exceptions=False).get("/api/leagues")
    assert response.status_code == 500
    span = json.loads(
        next(record.message for record in caplog.records if record.name == "calculator.trace")
    )
    assert span["http_status_code"] == 500
    assert span["failure_class"] == "exception"
    assert "secret upstream detail" not in json.dumps(span)
