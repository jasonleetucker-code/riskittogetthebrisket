"""Tests for the ``?view=array`` desktop payload of ``GET /api/data``.

The full contract carries TWO parallel encodings of every player: the
legacy ``players`` dict and ``playersArray`` (~5.8MB + ~6.6MB of a
~12MB payload).  ``playersArray`` is strictly richer and is the branch
the frontend materializer (``buildRows``) prefers whenever present, so
desktop clients request ``view=array`` — the full contract minus the
legacy dict — and cut wire/parse cost roughly in half with zero field
loss.

Pinned here:
    1. ``view=array`` serves the precomputed array payload: no
       ``players`` dict, ``playersArray`` intact and identical to the
       full view's, ``X-Payload-View: array``.
    2. ``view=desktop`` is an accepted alias.
    3. The array payload is byte-stable with its own ETag (304 support
       comes from the shared fast path).
    4. Unknown views still fall back to the full payload.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import server
from src.api import league_registry


@pytest.fixture
def array_env(tmp_path, monkeypatch):
    path = tmp_path / "registry.json"
    path.write_text(
        json.dumps(
            {
                "defaultLeagueKey": "main",
                "leagues": [
                    {
                        "key": "main",
                        "displayName": "Main",
                        "sleeperLeagueId": "L-MAIN",
                        "active": True,
                        "rosterSettings": {"teamCount": 12},
                    }
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
    # Keep the live Sleeper overlay out of these tests.
    monkeypatch.setattr(server._sleeper_overlay, "fetch_sleeper_overlay", lambda **kwargs: None)

    yield

    league_registry.reload_registry()


def _install_views(monkeypatch):
    """Install a full payload + its derived array payload the way
    ``_prime_latest_payload`` does (dict copy minus ``players``)."""
    import gzip as _gzip
    import hashlib as _hashlib

    full_payload = {
        "meta": {"leagueKey": "main"},
        "players": {"Josh Allen": {"rankDerivedValue": 9200}},
        "playersArray": [{"displayName": "Josh Allen", "rankDerivedValue": 9200}],
        "sleeper": {"teams": []},
    }
    full_raw = json.dumps(full_payload, ensure_ascii=False, separators=(",", ":")).encode()

    array_payload = dict(full_payload)
    array_payload.pop("players", None)
    array_payload["payloadView"] = "array"
    array_raw = json.dumps(array_payload, ensure_ascii=False, separators=(",", ":")).encode()

    monkeypatch.setattr(server, "latest_data", {"players": {}})
    monkeypatch.setattr(server, "latest_contract_data", full_payload)
    monkeypatch.setattr(server, "latest_data_bytes", full_raw)
    monkeypatch.setattr(server, "latest_data_gzip_bytes", _gzip.compress(full_raw))
    monkeypatch.setattr(server, "latest_data_etag", _hashlib.sha1(full_raw).hexdigest())
    monkeypatch.setattr(server, "latest_array_data", array_payload)
    monkeypatch.setattr(server, "latest_array_data_bytes", array_raw)
    monkeypatch.setattr(server, "latest_array_data_gzip_bytes", _gzip.compress(array_raw))
    monkeypatch.setattr(server, "latest_array_data_etag", _hashlib.sha1(array_raw).hexdigest())
    return full_payload


def test_array_view_drops_only_the_legacy_dict(array_env, monkeypatch):
    with TestClient(server.app, raise_server_exceptions=True) as c:
        full_payload = _install_views(monkeypatch)
        res = c.get("/api/data?view=array")
    assert res.status_code == 200, res.text
    assert res.headers["X-Payload-View"] == "array"
    body = res.json()
    assert "players" not in body
    assert body["playersArray"] == full_payload["playersArray"]
    assert body["payloadView"] == "array"


def test_desktop_alias(array_env, monkeypatch):
    with TestClient(server.app, raise_server_exceptions=True) as c:
        _install_views(monkeypatch)
        res = c.get("/api/data?view=desktop")
    assert res.status_code == 200
    assert res.headers["X-Payload-View"] == "array"


def test_array_view_supports_304(array_env, monkeypatch):
    with TestClient(server.app, raise_server_exceptions=True) as c:
        _install_views(monkeypatch)
        first = c.get("/api/data?view=array")
        etag = first.headers.get("etag")
        assert etag
        second = c.get("/api/data?view=array", headers={"If-None-Match": etag})
    assert second.status_code == 304


def test_unknown_view_serves_full(array_env, monkeypatch):
    with TestClient(server.app, raise_server_exceptions=True) as c:
        _install_views(monkeypatch)
        res = c.get("/api/data?view=banana")
    assert res.status_code == 200
    assert res.headers["X-Payload-View"] == "full"
    assert "players" in res.json()


def test_prime_builds_array_variant_from_real_pipeline(array_env, monkeypatch, tmp_path):
    """End-to-end: run the real ``_prime_latest_payload`` on the small
    pipeline fixture and assert the array variant is the full payload
    minus ``players`` — nothing else may differ."""
    from tests.api.test_source_overrides import _fixture_raw_payload

    # Rank-history stamping writes under data/; isolate it.
    monkeypatch.setattr(server, "RANK_HISTORY_ENABLED", False, raising=False)
    server._prime_latest_payload(_fixture_raw_payload())
    try:
        full = server.latest_contract_data
        arr = server.latest_array_data
        assert full is not None and arr is not None
        assert "players" in full
        assert "players" not in arr
        expected = dict(full)
        expected.pop("players")
        expected["payloadView"] = "array"
        assert arr == expected
    finally:
        server._prime_latest_payload(None)
