"""``POST /api/trade/title-odds`` — the async season-odds route (DYN10 #4).

Pinned here, on the real FastAPI app:

* flag OFF (the default, owner-held): 503 ``feature_disabled`` before the body
  is read or anything is simulated;
* signed out: 401 whatever the flag says (auth is checked first);
* flag ON: the lens payload for the trade the body names, plus the transport
  fields; refusals from the shared simulation path keep their status;
* the same trade on the same board is not re-simulated for the same user
  (cache), while a different trade, a new board generation, an unstamped board
  or a refusal is;
* the cache and the in-flight slot are per USER: another user asking the same
  trade gets a computation of their own (no ``source: "cache"`` and no timing
  that would reveal someone else's request), and a session with no provable
  owner is never shared;
* a computation past the deadline answers ``title_odds_timeout``
  (unavailable, never zero), keeps running, and the next identical request
  gets its result;
* a full admission bound answers ``title_odds_busy`` (unavailable, retryable)
  without starting anything;
* Asset-Only is answered without computing.

The lens computation is replaced by a canned payload (it is pinned in
``tests/trade/test_title_odds_lens.py``); the runtime's own rules are pinned in
``tests/api/test_trade_title_odds_runtime.py``.
"""

from __future__ import annotations

import threading
import time

import pytest

import server
from src.api import compute_admission as ca
from src.api import trade_title_odds_runtime as rt
from src.trade import title_odds_lens as tol
from tests.api.test_league_routing import two_league_registry  # noqa: F401 — fixture
from tests.api.test_trade_analyze_runtime import (  # noqa: F401 — fixtures
    _BODY,
    _app_client,
    _session_for,
    client,
)
from tests.api.test_trade_analyze_title_odds_route import _canned, flag  # noqa: F401
from tests.api.test_trade_nfl_exposure import _contract

ROUTE = "/api/trade/title-odds"


def _admission(max_concurrent=2, timeout=5.0):
    spec = ca.AdmissionSpec(max_concurrent=max_concurrent, timeout_seconds=timeout)
    return ca.ComputeAdmission(ca.ROUTE_TRADE_TITLE_ODDS, spec_provider=lambda: spec)


@pytest.fixture
def runtime(monkeypatch):
    """A fresh runtime per test (own admission), so no cached payload or slot
    crosses tests."""
    fresh = rt.TitleOddsRuntime(admission=_admission())
    monkeypatch.setattr(server, "_TRADE_TITLE_ODDS", fresh)
    return fresh


def _stamp_board(monkeypatch, generation="2026-11-22T12:00:00+00:00"):
    contract = _contract(league_key="main")
    contract["generatedAt"] = generation
    monkeypatch.setattr(server, "latest_contract_data", contract)
    return contract


def _counting(monkeypatch, payload=None):
    calls: list[tuple] = []

    def fake(result, league_key, contract):
        calls.append((result["team"]["ownerId"], league_key, contract))
        return payload() if callable(payload) else (payload or _canned())

    monkeypatch.setattr(server, "_trade_title_odds_two_team", fake)
    return calls


def _fail(*_a, **_k):
    pytest.fail("the flag-off route must not do any work")


# ── the gate ─────────────────────────────────────────────────────────────


def test_flag_off_refuses_before_any_work(client, flag, runtime, monkeypatch):  # noqa: F811
    flag(False)
    monkeypatch.setattr(server, "_build_trade_simulation", _fail)
    monkeypatch.setattr(server, "_trade_title_odds_two_team", _fail)
    for kwargs in ({"json": _BODY}, {"content": b"not json"}):
        res = client.post(ROUTE, **kwargs)
        assert res.status_code == 503, res.text
        assert res.json()["error"] == "feature_disabled"
        assert res.json()["flag"] == tol.FLAG
        assert res.headers["cache-control"] == "no-store"


def test_signed_out_is_refused_whatever_the_flag(client, flag, runtime, monkeypatch):  # noqa: F811
    """Both gates: the cookie gate (middleware) and the handler's own check,
    which comes before the flag, so a signed-out caller learns nothing."""
    monkeypatch.setattr(server, "_get_auth_session", lambda _r: None)
    monkeypatch.setattr(server, "_build_trade_simulation", _fail)
    monkeypatch.setattr(server, "_trade_title_odds_two_team", _fail)
    for on in (False, True):
        flag(on)
        res = client.post(ROUTE, json=_BODY)
        assert res.status_code == 401 and res.json()["error"] == "auth_required"
        monkeypatch.setattr(server, "_is_authenticated", lambda _r: False)
        gated = client.post(ROUTE, json=_BODY)
        assert gated.status_code == 401 and gated.json()["error"] == "auth_required"
        monkeypatch.setattr(server, "_is_authenticated", lambda _r: True)


# ── flag ON ──────────────────────────────────────────────────────────────


def test_flag_on_serves_the_lens_payload(client, flag, runtime, monkeypatch):  # noqa: F811
    flag(True)
    calls = _counting(monkeypatch)
    res = client.post(ROUTE, json=_BODY)
    assert res.status_code == 200, res.text
    assert res.headers["cache-control"] == "no-store"
    body = res.json()
    assert [(owner, league) for owner, league, _c in calls] == [("o1", "main")]
    assert body["state"] == "ok" and body["role"] == "context_not_vote"
    assert body["teams"] == _canned()["teams"]
    assert body["disclosure"]["text"] == tol.ODDS_DISCLOSURE
    assert body["leagueKey"] == "main"
    assert body["perspectiveOwnerId"] == "o1"
    assert body["computation"]["source"] == rt.SOURCE_COMPUTED
    assert isinstance(body["computation"]["ms"], float)
    # Context only: the route serves the lens, never a decision.
    assert "analysis" not in body and "decision" not in body


def test_refusals_from_the_shared_path_keep_their_status(client, flag, runtime, monkeypatch):  # noqa: F811
    flag(True)
    monkeypatch.setattr(server, "_trade_title_odds_two_team", _fail)
    res = client.post(ROUTE, json={**_BODY, "team": "nobody", "teamName": "Nobody"})
    assert res.status_code == 404 and res.json()["error"] == "team_not_found"
    bad = client.post(ROUTE, content=b"[1, 2]")
    assert bad.status_code == 400 and bad.json() == {"error": "invalid_body"}


def test_asset_only_is_answered_without_computing(client, flag, runtime, monkeypatch):  # noqa: F811
    flag(True)
    monkeypatch.setattr(server, "_trade_title_odds_two_team", _fail)
    res = client.post(ROUTE, json={**_BODY, "useTeamContext": False})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["state"] == "unavailable" and body["reason"] == tol.REASON_ASSET_ONLY
    assert body["teams"] == []
    assert body["computation"]["source"] == "not_computed"


# ── the cache ────────────────────────────────────────────────────────────


def test_the_same_trade_on_the_same_board_is_not_resimulated(client, flag, runtime, monkeypatch):  # noqa: F811
    flag(True)
    calls = _counting(monkeypatch)
    _stamp_board(monkeypatch)
    first = client.post(ROUTE, json=_BODY).json()
    second = client.post(ROUTE, json={**_BODY, "teamGoal": "WIN_NOW"}).json()
    assert len(calls) == 1
    assert first["computation"]["source"] == rt.SOURCE_COMPUTED
    assert second["computation"]["source"] == rt.SOURCE_CACHE
    assert second["teams"] == first["teams"]
    # A different trade is a different question.
    client.post(ROUTE, json={**_BODY, "playersOut": ["WR Phi"]})
    assert len(calls) == 2
    # A new board generation is a different board.
    _stamp_board(monkeypatch, generation="2026-11-22T14:00:00+00:00")
    again = client.post(ROUTE, json=_BODY).json()
    assert len(calls) == 3 and again["computation"]["source"] == rt.SOURCE_COMPUTED


def test_an_unstamped_board_and_a_refusal_are_never_cached(client, flag, runtime, monkeypatch):  # noqa: F811
    flag(True)
    calls = _counting(monkeypatch)
    # The fixture board carries no generation stamp: nothing proves it is the
    # same board next time.
    client.post(ROUTE, json=_BODY)
    client.post(ROUTE, json=_BODY)
    assert len(calls) == 2
    _stamp_board(monkeypatch)
    calls = _counting(monkeypatch, payload=lambda: tol.unavailable(tol.REASON_NO_SCHEDULE))
    for _ in range(2):
        body = client.post(ROUTE, json=_BODY).json()
        assert body["state"] == "unavailable" and body["reason"] == tol.REASON_NO_SCHEDULE
        assert body["computation"]["source"] == rt.SOURCE_COMPUTED
    assert len(calls) == 2


# ── the bound ────────────────────────────────────────────────────────────


def test_a_slow_computation_times_out_and_finishes_in_the_background(client, flag, monkeypatch):  # noqa: F811
    flag(True)
    _stamp_board(monkeypatch)
    slow = rt.TitleOddsRuntime(admission=_admission(timeout=0.05))
    monkeypatch.setattr(server, "_TRADE_TITLE_ODDS", slow)
    release = threading.Event()

    def blocked():
        assert release.wait(5), "the test never released the computation"
        return _canned()

    calls = _counting(monkeypatch, payload=blocked)
    timed_out = client.post(ROUTE, json=_BODY)
    assert timed_out.status_code == 200, timed_out.text
    body = timed_out.json()
    assert body["state"] == "unavailable" and body["reason"] == tol.REASON_TIMEOUT
    assert body["teams"] == []
    assert body["computation"]["source"] == rt.SOURCE_TIMEOUT
    release.set()
    deadline = time.monotonic() + 5
    while not slow._cache and time.monotonic() < deadline:
        time.sleep(0.01)
    after = client.post(ROUTE, json=_BODY).json()
    assert after["state"] == "ok" and after["computation"]["source"] == rt.SOURCE_CACHE
    assert len(calls) == 1


# ── the admission bound ──────────────────────────────────────────────────


def test_a_full_route_answers_busy_without_computing(client, flag, monkeypatch):  # noqa: F811
    flag(True)
    _stamp_board(monkeypatch)
    adm = _admission(max_concurrent=1)
    full = rt.TitleOddsRuntime(admission=adm)
    monkeypatch.setattr(server, "_TRADE_TITLE_ODDS", full)
    monkeypatch.setattr(server, "_trade_title_odds_two_team", _fail)
    # Another trade's season simulation holds the only slot.
    assert adm._try_acquire()
    res = client.post(ROUTE, json=_BODY)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["state"] == "unavailable" and body["reason"] == tol.REASON_BUSY
    assert body["teams"] == []  # never a zero
    assert body["computation"]["source"] == rt.SOURCE_BUSY
    assert body["disclosure"]["text"] == tol.ODDS_DISCLOSURE
    # Not cached: with the slot free again the same request computes.
    adm._release()
    calls = _counting(monkeypatch)
    again = client.post(ROUTE, json=_BODY).json()
    assert again["state"] == "ok" and again["computation"]["source"] == rt.SOURCE_COMPUTED
    assert len(calls) == 1 and adm.active == 0


def test_the_route_uses_the_title_odds_admission_by_default():
    assert server._TRADE_TITLE_ODDS._admission is None  # resolved per call
    ca.reset_for_tests()
    assert server._TRADE_TITLE_ODDS.admission is ca.admission_for(ca.ROUTE_TRADE_TITLE_ODDS)


# ── per-user cache and in-flight slot ────────────────────────────────────


def test_another_user_never_gets_this_users_computation(client, flag, runtime, monkeypatch):  # noqa: F811
    flag(True)
    _stamp_board(monkeypatch)
    calls = _counting(monkeypatch)
    alice = client.post(ROUTE, json=_BODY).json()
    monkeypatch.setattr(server, "_get_auth_session", _session_for("bob", "o2"))
    bob = client.post(ROUTE, json=_BODY).json()
    # Same trade, same board, same team: two users, two computations.
    assert len(calls) == 2
    assert alice["computation"]["source"] == rt.SOURCE_COMPUTED
    assert bob["computation"]["source"] == rt.SOURCE_COMPUTED
    assert bob["perspectiveOwnerId"] == alice["perspectiveOwnerId"] == "o1"
    # Each user's own Retry is a cache hit.
    bob_retry = client.post(ROUTE, json=_BODY).json()
    monkeypatch.setattr(server, "_get_auth_session", _session_for("alice"))
    alice_retry = client.post(ROUTE, json=_BODY).json()
    assert bob_retry["computation"]["source"] == rt.SOURCE_CACHE
    assert alice_retry["computation"]["source"] == rt.SOURCE_CACHE
    assert len(calls) == 2


def test_guest_pass_sessions_are_scoped_to_their_own_session(client, flag, runtime, monkeypatch):  # noqa: F811
    flag(True)
    _stamp_board(monkeypatch)
    calls = _counting(monkeypatch)
    guest = {"username": "guest", "auth_method": "guest_pass", "guest_pass_id": 7}
    monkeypatch.setattr(server, "_get_auth_session", lambda _r: dict(guest))
    name = server.JASON_AUTH_COOKIE_NAME
    one = client.post(ROUTE, json=_BODY, headers={"cookie": f"{name}=sess-one"}).json()
    two = client.post(ROUTE, json=_BODY, headers={"cookie": f"{name}=sess-two"}).json()
    assert len(calls) == 2  # two holders of one pass: two people
    assert two["computation"]["source"] == rt.SOURCE_COMPUTED
    again = client.post(ROUTE, json=_BODY, headers={"cookie": f"{name}=sess-one"}).json()
    assert again["computation"]["source"] == rt.SOURCE_CACHE and len(calls) == 2
    assert one["teams"] == again["teams"]


def test_a_session_without_a_provable_owner_is_never_shared(client, flag, runtime, monkeypatch):  # noqa: F811
    """A guest-pass session whose id is unknown has no owner
    (``session_owner`` -> None): computed alone every time, never cached."""
    flag(True)
    _stamp_board(monkeypatch)
    calls = _counting(monkeypatch)
    guest = {"username": "guest", "auth_method": "guest_pass", "guest_pass_id": 7}
    monkeypatch.setattr(server, "_get_auth_session", lambda _r: dict(guest))
    for _ in range(2):
        body = client.post(ROUTE, json=_BODY).json()
        assert body["state"] == "ok"
        assert body["computation"]["source"] == rt.SOURCE_COMPUTED
    assert len(calls) == 2 and not runtime._cache
