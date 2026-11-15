"""An anonymous ``?refresh=`` on ``/api/draft-capital`` is ignored.

It used to skip the result cache and run a full build (Sleeper round-trips,
dollar generation, ~3-4 s) per request for ANY caller -- ``?refresh=0``
included, since any non-empty string was truthy.  Same posture as
``_authorized_force_refresh`` on the public-league routes: ignored, not
refused, so the public tab keeps working and reads the cache.  Authenticated
callers keep the forced rebuild.
"""

from __future__ import annotations

import asyncio
import json
import time

import pytest

GOOD = {"season": 2027, "picks": [{"pick": "1.01", "dollarValue": 135}], "teamTotals": []}


class _League:
    key = "anon_refresh_league"


@pytest.fixture
def srv(monkeypatch):
    server = pytest.importorskip("server")
    league = _League()
    monkeypatch.setattr(server, "_DRAFT_CAPITAL_CACHE", {league.key: (time.time(), dict(GOOD))})
    monkeypatch.setattr(server, "_DRAFT_CAPITAL_LAST_VALID", {})
    monkeypatch.setattr(server, "_DRAFT_CAPITAL_LOCKS", {})
    monkeypatch.setattr(server, "_resolve_league_for_request", lambda r: league)
    monkeypatch.setattr(server._league_registry, "get_default_league", lambda: league)
    calls = {"n": 0}

    def _fetch(*_a, **_k):
        calls["n"] += 1
        return dict(GOOD, season=2099)

    monkeypatch.setattr(server, "_fetch_draft_capital", _fetch)
    return server, calls


def _call(server, refresh):
    resp = asyncio.run(server.get_draft_capital(object(), refresh=refresh))
    return resp.body


@pytest.mark.parametrize("refresh", ["1", "0", "true", "x"])
def test_anonymous_refresh_reads_the_cache(srv, monkeypatch, refresh):
    server, calls = srv
    monkeypatch.setattr(server, "_is_authenticated", lambda r: False)
    baseline = _call(server, "")
    forced = _call(server, refresh)
    assert calls["n"] == 0
    assert forced == baseline, "bytes are those of the plain cached request"
    assert json.loads(forced)["season"] == 2027


def test_authenticated_refresh_still_rebuilds(srv, monkeypatch):
    server, calls = srv
    monkeypatch.setattr(server, "_is_authenticated", lambda r: True)
    body = _call(server, "1")
    assert calls["n"] == 1
    assert json.loads(body)["season"] == 2099
