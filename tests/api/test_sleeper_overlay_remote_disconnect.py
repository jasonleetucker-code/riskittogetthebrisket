"""Regression coverage for transient Sleeper transport disconnects."""

import http.client

from src.api import sleeper_overlay


def test_http_get_json_remote_disconnect_returns_none(monkeypatch):
    called = {"urlopen": 0}

    def remote_disconnect(*args, **kwargs):
        called["urlopen"] += 1
        raise http.client.RemoteDisconnected("remote closed")

    monkeypatch.setattr(sleeper_overlay.urllib.request, "urlopen", remote_disconnect)
    monkeypatch.setattr(
        "src.utils.circuit_breaker.get_or_create",
        lambda *args, **kwargs: None,
    )

    result = sleeper_overlay._http_get_json("https://api.sleeper.app/v1/test")

    assert called["urlopen"] == 1
    assert result is None
