"""``/api/draft-capital``: bounded stale-while-revalidate and the post-publish rebuild.

Production 2026-11-15: the first request after the 300 s TTL took 4.29 s and
3.29 s (two samples), the next ones 0.40-0.64 s.  The contract here:

* a fresh entry answers with no build (unchanged);
* an expired SUCCESSFUL entry inside TTL + ``_DRAFT_CAPITAL_SWR_SEC`` answers at
  once, unchanged, while exactly ONE background build replaces it;
* past that bound, an ``error`` entry (a refusal), or an authorized
  ``?refresh=1``, the request blocks on a build exactly as before;
* the background build files its result through the same rules as the request
  path (last valid board, refusal cached for the TTL, dollars-generation
  failure answered by the labelled last valid board for the short window);
* an anonymous caller gets the redacted copy and the cached board is untouched;
* after a publish clears the cache, the default league's board is rebuilt off
  the request path, and a failure there never raises.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import threading
import time

import pytest

from tests.public_league.fixtures import wait_for_public_memo_refreshes


class _League:
    key = "swr_draft_league"


GOOD_OLD = {"season": 2027, "picks": [{"pick": "1.01", "dollarValue": 135}], "teamTotals": []}
GOOD_NEW = {"season": 2027, "picks": [{"pick": "1.01", "dollarValue": 140}], "teamTotals": []}
REFUSAL = {"error": "pick_ownership_unavailable", "message": "x", "draftYear": 2027}


@pytest.fixture
def srv(monkeypatch):
    server = pytest.importorskip("server")
    wait_for_public_memo_refreshes(server)
    for name in (
        "_DRAFT_CAPITAL_CACHE",
        "_DRAFT_CAPITAL_LAST_VALID",
        "_DRAFT_CAPITAL_LOCKS",
        "_DRAFT_CAPITAL_FILED_STARTED",
    ):
        monkeypatch.setattr(server, name, {})
    serving = threading.Event()
    serving.set()
    monkeypatch.setattr(server, "_SERVING_STARTED", serving)
    monkeypatch.setattr(server, "_public_memo_refresh_inflight", {})
    monkeypatch.setattr(server, "_public_memo_refresh_failed_at", {})
    monkeypatch.setattr(server, "_public_memo_refresh_abandoned", {})
    league = _League()
    monkeypatch.setattr(server, "_resolve_league_for_request", lambda r: league)
    monkeypatch.setattr(server._league_registry, "get_default_league", lambda: league)
    monkeypatch.setattr(server, "_is_authenticated", lambda r: True)
    yield server
    wait_for_public_memo_refreshes(server)


def _builder(server, monkeypatch, result, *, gate: threading.Event | None = None):
    builds: list[int] = []

    def build(*_a, **_k):
        builds.append(1)
        if gate is not None:
            gate.wait(10)
        return json.loads(json.dumps(result))

    monkeypatch.setattr(server, "_fetch_draft_capital", build)
    return builds


def _get(server, refresh: str = ""):
    resp = asyncio.run(server.get_draft_capital(object(), refresh=refresh))
    return json.loads(resp.body)


def _seed(server, body, age: float) -> None:
    stamped = {**body, "leagueKey": _League.key}
    server._DRAFT_CAPITAL_CACHE[_League.key] = (time.time() - age, stamped)


def test_window_constants():
    server = pytest.importorskip("server")
    assert server._DRAFT_CAPITAL_TTL_SEC == 300
    # TTL + window = the Sleeper overlay's 15-minute fresh window.
    assert server._DRAFT_CAPITAL_TTL_SEC + server._DRAFT_CAPITAL_SWR_SEC == 900


def test_fresh_entry_answers_without_a_build(srv, monkeypatch):
    builds = _builder(srv, monkeypatch, GOOD_NEW)
    _seed(srv, GOOD_OLD, age=10)
    assert _get(srv)["picks"] == GOOD_OLD["picks"]
    wait_for_public_memo_refreshes(srv)
    assert builds == []


def test_expired_success_answers_at_once_and_one_build_replaces_it(srv, monkeypatch):
    gate = threading.Event()
    builds = _builder(srv, monkeypatch, GOOD_NEW, gate=gate)
    _seed(srv, GOOD_OLD, age=srv._DRAFT_CAPITAL_TTL_SEC + 5)
    # Three requests while the build is held: all answered from the stale
    # board, one background build.
    for _ in range(3):
        out = _get(srv)
        assert out["picks"] == GOOD_OLD["picks"]
        assert "staleWhileRevalidate" not in out
    gate.set()
    wait_for_public_memo_refreshes(srv)
    assert builds == [1]
    stamp, cached = srv._DRAFT_CAPITAL_CACHE[_League.key]
    assert cached["picks"] == GOOD_NEW["picks"] and cached["leagueKey"] == _League.key
    assert time.time() - stamp < 5
    assert srv._DRAFT_CAPITAL_LAST_VALID[_League.key][1]["picks"] == GOOD_NEW["picks"]
    # The next request reads the rebuilt board with no further build.
    assert _get(srv)["picks"] == GOOD_NEW["picks"]
    wait_for_public_memo_refreshes(srv)
    assert builds == [1]


def test_past_the_bound_the_request_blocks_as_before(srv, monkeypatch):
    builds = _builder(srv, monkeypatch, GOOD_NEW)
    _seed(srv, GOOD_OLD, age=srv._DRAFT_CAPITAL_TTL_SEC + srv._DRAFT_CAPITAL_SWR_SEC + 1)
    assert _get(srv)["picks"] == GOOD_NEW["picks"]
    assert builds == [1]


def test_an_expired_refusal_is_never_served_stale(srv, monkeypatch):
    builds = _builder(srv, monkeypatch, GOOD_NEW)
    _seed(srv, REFUSAL, age=srv._DRAFT_CAPITAL_TTL_SEC + 5)
    out = _get(srv)
    assert "error" not in out and out["picks"] == GOOD_NEW["picks"]
    assert builds == [1]


def test_authorized_refresh_blocks_even_with_a_stale_entry(srv, monkeypatch):
    builds = _builder(srv, monkeypatch, GOOD_NEW)
    _seed(srv, GOOD_OLD, age=srv._DRAFT_CAPITAL_TTL_SEC + 5)
    assert _get(srv, refresh="1")["picks"] == GOOD_NEW["picks"]
    assert builds == [1]


def test_anonymous_stale_answer_is_redacted_and_the_cache_untouched(srv, monkeypatch):
    gate = threading.Event()
    _builder(srv, monkeypatch, GOOD_NEW, gate=gate)
    board = {
        "season": 2027,
        "picks": [
            {"pick": "1.01", "dollarValue": 135, "rookieName": "Private", "rookieBoardValue": 9}
        ],
        "teamTotals": [],
    }
    _seed(srv, board, age=srv._DRAFT_CAPITAL_TTL_SEC + 5)
    monkeypatch.setattr(srv, "_is_authenticated", lambda r: False)
    out = _get(srv)
    assert "rookieName" not in out["picks"][0] and "rookieBoardValue" not in out["picks"][0]
    cached = srv._DRAFT_CAPITAL_CACHE[_League.key][1]
    assert cached["picks"][0]["rookieName"] == "Private"
    gate.set()


def test_background_refusal_is_filed_like_the_request_path(srv, monkeypatch):
    _builder(srv, monkeypatch, REFUSAL)
    _seed(srv, GOOD_OLD, age=srv._DRAFT_CAPITAL_TTL_SEC + 5)
    assert _get(srv)["picks"] == GOOD_OLD["picks"]
    wait_for_public_memo_refreshes(srv)
    stamp, cached = srv._DRAFT_CAPITAL_CACHE[_League.key]
    assert cached == {**REFUSAL, "leagueKey": _League.key}
    assert time.time() - stamp < 5  # held for the full TTL, as the request path does
    assert _get(srv) == {**REFUSAL, "leagueKey": _League.key}


def test_background_generation_failure_serves_the_labelled_last_valid_board(srv, monkeypatch):
    srv._DRAFT_CAPITAL_LAST_VALID[_League.key] = (
        time.time() - 30,
        {**GOOD_OLD, "leagueKey": _League.key},
    )
    failed = {
        "error": "draft_dollars_unavailable",
        "unavailableReason": "no_verified_allocation",
        "draftYear": 2027,
        "draftValuationGeneration": {"targetDraftYear": 2027, "generationHash": None},
    }
    _builder(srv, monkeypatch, failed)
    _seed(srv, GOOD_OLD, age=srv._DRAFT_CAPITAL_TTL_SEC + 5)
    _get(srv)
    wait_for_public_memo_refreshes(srv)
    stamp, cached = srv._DRAFT_CAPITAL_CACHE[_League.key]
    assert cached["staleWhileRevalidate"]["state"] == "serving_last_valid_board"
    remaining = srv._DRAFT_CAPITAL_TTL_SEC - (time.time() - stamp)
    assert remaining <= srv._DRAFT_CAPITAL_STALE_RETRY_SEC + 1


def test_publish_rebuild_fills_the_default_board(srv, monkeypatch):
    builds = _builder(srv, monkeypatch, GOOD_NEW)
    monkeypatch.setattr(srv, "_DRAFT_CAPITAL_WARM_ENABLED", True)
    assert srv._kick_draft_capital_publish_rebuild() is True
    wait_for_public_memo_refreshes(srv)
    assert builds == [1]
    assert srv._DRAFT_CAPITAL_CACHE[_League.key][1]["picks"] == GOOD_NEW["picks"]
    # The first visitor of the new generation builds nothing.
    assert _get(srv)["picks"] == GOOD_NEW["picks"]
    wait_for_public_memo_refreshes(srv)
    assert builds == [1]


def test_publish_rebuild_disabled_or_failing_never_raises(srv, monkeypatch):
    builds = _builder(srv, monkeypatch, GOOD_NEW)
    monkeypatch.setattr(srv, "_DRAFT_CAPITAL_WARM_ENABLED", False)
    assert srv._kick_draft_capital_publish_rebuild() is False
    monkeypatch.setattr(srv, "_DRAFT_CAPITAL_WARM_ENABLED", True)

    def boom():
        raise RuntimeError("registry down")

    monkeypatch.setattr(srv._league_registry, "get_default_league", boom)
    assert srv._kick_draft_capital_publish_rebuild() is False
    wait_for_public_memo_refreshes(srv)
    assert builds == []


def test_publish_clears_then_rebuilds():
    """The generation clear in the publish path is followed by the rebuild."""
    server = pytest.importorskip("server")
    src = inspect.getsource(server)
    clear_then_kick = "_DRAFT_CAPITAL_CACHE.clear()\n    _kick_draft_capital_publish_rebuild()"
    assert clear_then_kick in src.replace("\r\n", "\n")


def test_labelled_last_valid_board_keeps_its_short_retry_rule(srv, monkeypatch):
    builds = _builder(srv, monkeypatch, GOOD_NEW)
    labelled = {**GOOD_OLD, "staleWhileRevalidate": {"state": "serving_last_valid_board"}}
    _seed(srv, labelled, age=srv._DRAFT_CAPITAL_TTL_SEC + 5)
    out = _get(srv)
    assert "staleWhileRevalidate" not in out and out["picks"] == GOOD_NEW["picks"]
    assert builds == [1]


def test_background_build_superseded_by_a_publish_is_not_filed_and_reruns(srv, monkeypatch):
    monkeypatch.setattr(srv, "latest_data_etag", "gen-1")
    calls: list[str] = []

    def build(*_a, **_k):
        calls.append(srv.latest_data_etag)
        if len(calls) == 1:
            # A publish lands while the first build runs.
            srv.latest_data_etag = "gen-2"
            return json.loads(json.dumps(GOOD_OLD))
        return json.loads(json.dumps(GOOD_NEW))

    monkeypatch.setattr(srv, "_fetch_draft_capital", build)
    _seed(srv, GOOD_OLD, age=srv._DRAFT_CAPITAL_TTL_SEC + 5)
    _get(srv)
    wait_for_public_memo_refreshes(srv)
    assert calls == ["gen-1", "gen-2"]
    cached = srv._DRAFT_CAPITAL_CACHE[_League.key][1]
    assert cached["picks"] == GOOD_NEW["picks"]
    assert srv._DRAFT_CAPITAL_LAST_VALID[_League.key][1]["picks"] == GOOD_NEW["picks"]


def test_request_build_superseded_by_a_publish_is_served_but_not_filed(srv, monkeypatch):
    monkeypatch.setattr(srv, "latest_data_etag", "gen-1")

    def build(*_a, **_k):
        srv.latest_data_etag = "gen-2"
        return json.loads(json.dumps(GOOD_OLD))

    monkeypatch.setattr(srv, "_fetch_draft_capital", build)
    out = _get(srv, refresh="1")
    assert out["picks"] == GOOD_OLD["picks"]
    assert _League.key not in srv._DRAFT_CAPITAL_CACHE
    assert _League.key not in srv._DRAFT_CAPITAL_LAST_VALID


def test_an_older_background_build_never_overwrites_a_newer_refresh(srv, monkeypatch):
    gate = threading.Event()
    calls: list[int] = []

    def build(*_a, **_k):
        calls.append(1)
        if len(calls) == 1:
            gate.wait(10)  # the background build started first and finishes last
            return json.loads(json.dumps(GOOD_OLD))
        return json.loads(json.dumps(GOOD_NEW))

    monkeypatch.setattr(srv, "_fetch_draft_capital", build)
    _seed(srv, GOOD_OLD, age=srv._DRAFT_CAPITAL_TTL_SEC + 5)
    _get(srv)  # stale answer; background build 1 starts and blocks
    deadline = time.time() + 5
    while not calls and time.time() < deadline:
        time.sleep(0.01)
    assert calls == [1]
    assert _get(srv, refresh="1")["picks"] == GOOD_NEW["picks"]  # build 2 files
    gate.set()
    wait_for_public_memo_refreshes(srv)
    assert len(calls) == 2
    assert srv._DRAFT_CAPITAL_CACHE[_League.key][1]["picks"] == GOOD_NEW["picks"]


def test_boot_publish_rebuild_waits_for_serving(srv, monkeypatch):
    builds = _builder(srv, monkeypatch, GOOD_NEW)
    monkeypatch.setattr(srv, "_DRAFT_CAPITAL_WARM_ENABLED", True)
    not_yet = threading.Event()
    monkeypatch.setattr(srv, "_SERVING_STARTED", not_yet)
    assert srv._kick_draft_capital_publish_rebuild() is True
    time.sleep(0.2)
    assert builds == [] and _League.key not in srv._DRAFT_CAPITAL_CACHE
    not_yet.set()
    deadline = time.time() + 10
    while _League.key not in srv._DRAFT_CAPITAL_CACHE and time.time() < deadline:
        time.sleep(0.02)
    wait_for_public_memo_refreshes(srv)
    assert builds == [1]
    assert srv._DRAFT_CAPITAL_CACHE[_League.key][1]["picks"] == GOOD_NEW["picks"]
