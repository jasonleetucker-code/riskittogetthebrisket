"""``/api/scaffold/identity`` serves a report with no age on it.

Measured 2026-08-04: ``generated_at`` 2026-04-20T19:48:28Z — **106
days** older than the live contract — served as current, with no field
on the 2.5 MB response indicating that (audit W06-F010).  The producer
(``scripts/identity_resolve.py``) is referenced by no workflow, timer or
service, so the file only moves when a human runs it.

Repairing the report's CONTENT is a different piece of work (its
``sleeper_id`` is hardcoded empty in ``src/identity/matcher.py``, and
its pick table is empty because the bridge adapter types every record
``player``).  What this pins is that the surface stops implying
freshness it does not have.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

import server


def _write_report(tmp_path, generated_at: str):
    d = tmp_path / "identity"
    d.mkdir(parents=True, exist_ok=True)
    path = d / "identity_report_test.json"
    path.write_text(
        json.dumps({"generated_at": generated_at, "master_player_count": 3}),
        encoding="utf-8",
    )
    return path


def _get(monkeypatch, tmp_path, generated_at):
    _write_report(tmp_path, generated_at)
    monkeypatch.setattr(server, "DATA_DIR", tmp_path)
    monkeypatch.setattr(server, "_is_authenticated", lambda r: True)
    monkeypatch.setattr(server, "_get_auth_session", lambda r: {"username": "jasonleetucker"})
    client = TestClient(server.app, raise_server_exceptions=True)
    res = client.get("/api/scaffold/identity")
    assert res.status_code == 200, res.text
    return res.json()


def test_the_response_stamps_how_old_the_report_is(monkeypatch, tmp_path):
    old = (datetime.now(timezone.utc) - timedelta(days=106)).isoformat()
    body = _get(monkeypatch, tmp_path, old)
    assert body["_meta"]["generatedAt"] == old
    assert body["_meta"]["ageDays"] >= 105
    assert body["_meta"]["stale"] is True


def test_a_fresh_report_is_not_marked_stale(monkeypatch, tmp_path):
    fresh = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    body = _get(monkeypatch, tmp_path, fresh)
    assert body["_meta"]["ageDays"] == 0
    assert body["_meta"]["stale"] is False


def test_an_unparseable_timestamp_is_reported_as_unknown_not_as_fresh(monkeypatch, tmp_path):
    body = _get(monkeypatch, tmp_path, "not a date")
    assert body["_meta"]["ageDays"] is None
    assert body["_meta"]["stale"] is None


def test_the_report_body_is_served_unchanged(monkeypatch, tmp_path):
    body = _get(monkeypatch, tmp_path, datetime.now(timezone.utc).isoformat())
    assert body["master_player_count"] == 3
