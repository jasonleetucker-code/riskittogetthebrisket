"""``/api/trade/analyze`` request runtime — timing, progress, in-flight sharing.

Trade War Room speed (owner directive 2026-10-19, part 4).  Everything here is
transport: the analysis itself is unchanged, which the equivalence test below
pins (the same request with and without the runtime's additions produces the
same analysis).  Uses the synthetic league of ``tests/api/test_trade_nfl_exposure``.
"""

from __future__ import annotations

import asyncio
import json
import threading

import pytest
from fastapi.testclient import TestClient

import server
from src.api import trade_analyze_runtime as rt
from src.api import trade_simulator
from tests.api.test_league_routing import two_league_registry  # noqa: F401 — fixture
from tests.api.test_trade_nfl_exposure import _contract

_BODY = {"leagueKey": "main", "team": "o1", "playersIn": ["WR Buf Star"], "playersOut": ["WR Kc"]}
STAGES = ["resolve", "posture", "simulation", "exposure", "comparables", "decision", "receipt"]


def _session_for(username, sleeper_id="o1"):
    return lambda _request: {
        "username": username,
        "auth_method": "sleeper",
        "sleeper_user_id": sleeper_id,
    }


@pytest.fixture(scope="module")
def _app_client():
    # One lifespan for the module (each costs a full contract prime).
    with TestClient(server.app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture
def client(_app_client, two_league_registry, monkeypatch):  # noqa: F811
    from src.trade import comparable_trades as ct

    monkeypatch.setattr(
        ct, "comparable_trades", lambda *_a, **_k: {"state": "unavailable", "reason": "test"}
    )
    rt.PROGRESS.clear()
    monkeypatch.setattr(server, "latest_contract_data", _contract(league_key="main"))
    monkeypatch.setattr(server, "_get_auth_session", _session_for("alice"))
    yield _app_client
    rt.PROGRESS.clear()


def _strip(body):
    body = json.loads(json.dumps(body))
    body.pop("analysisTiming", None)
    body["analysis"].pop("decisionRunId", None)
    return body


# ── timing ───────────────────────────────────────────────────────────────


def test_analysis_timing_names_every_stage_and_server_timing_matches(client):
    res = client.post("/api/trade/analyze", json=_BODY)
    assert res.status_code == 200, res.text
    timing = res.json()["analysisTiming"]
    assert [s["stage"] for s in timing["stages"]] == STAGES
    assert all(isinstance(s["ms"], float) and s["ms"] >= 0 for s in timing["stages"])
    assert timing["totalMs"] >= max(s["ms"] for s in timing["stages"])
    assert timing["sharedComputation"] is False
    header = res.headers["server-timing"]
    for stage in STAGES + ["total"]:
        assert f"{stage};dur=" in header
    assert res.headers["cache-control"] == "no-store"


def test_runtime_additions_do_not_change_the_analysis(client, monkeypatch):
    """The served analysis equals one recomputed from the same simulation."""
    from src.trade.analyze_trade import analyze_trade

    body = client.post("/api/trade/analyze", json=_BODY).json()
    sim = {k: v for k, v in body.items() if k not in ("analysis", "analysisTiming")}
    meta = server.latest_contract_data.get("meta") or {}
    recomputed = analyze_trade(
        sim,
        comparables={"state": "unavailable", "reason": "test"},
        provenance={
            "boardStamp": meta.get("generatedAt"),
            "scoringFingerprint": meta.get("scoringFingerprint"),
        },
    )
    served = {k: v for k, v in body["analysis"].items() if k != "decisionRunId"}
    assert json.dumps(served, sort_keys=True) == json.dumps(recomputed, sort_keys=True)


def test_errors_keep_their_status_and_body(client, monkeypatch):
    res = client.post("/api/trade/analyze", json={**_BODY, "team": "nobody", "teamName": "Nobody"})
    assert res.status_code == 404
    assert res.json() == {"error": "team_not_found", "leagueKey": "main"}
    bad = client.post("/api/trade/analyze", content=b"[1, 2]")
    assert bad.status_code == 400 and bad.json() == {"error": "invalid_body"}
    monkeypatch.setattr(server, "_get_auth_session", lambda _r: None)
    assert client.post("/api/trade/analyze", json=_BODY).status_code == 401


# ── progress ─────────────────────────────────────────────────────────────


def test_progress_is_readable_by_the_same_user_only(client, monkeypatch):
    rid = "war-room-req-0001"
    res = client.post("/api/trade/analyze", json=_BODY, headers={"X-Analysis-Request-Id": rid})
    assert res.status_code == 200
    status = client.get("/api/trade/analyze/status", params={"requestId": rid})
    assert status.status_code == 200
    snap = status.json()
    assert snap["state"] == "complete" and snap["phase"] == "complete"
    assert [s["stage"] for s in snap["completedStages"]] == STAGES
    assert snap["phases"] == list(rt.PHASES)
    # Another signed-in user cannot read it, even with the id.
    monkeypatch.setattr(server, "_get_auth_session", _session_for("mallory", "o2"))
    other = client.get("/api/trade/analyze/status", params={"requestId": rid})
    assert other.status_code == 404 and other.json()["state"] == "unknown"
    # Signed out: refused.
    monkeypatch.setattr(server, "_get_auth_session", lambda _r: None)
    assert client.get("/api/trade/analyze/status", params={"requestId": rid}).status_code == 401


def test_progress_reports_the_stage_actually_running(client, monkeypatch):
    rid = "war-room-req-0002"
    seen: dict = {}
    real = trade_simulator.simulate_trade

    def spy(*a, **k):
        seen["mid"] = rt.PROGRESS.snapshot("alice", rid)
        return real(*a, **k)

    monkeypatch.setattr(trade_simulator, "simulate_trade", spy)
    client.post("/api/trade/analyze", json=_BODY, headers={"X-Analysis-Request-Id": rid})
    assert seen["mid"]["state"] == "running"
    assert seen["mid"]["phase"] == "simulation"
    assert [s["stage"] for s in seen["mid"]["completedStages"]] == ["resolve", "posture"]


def test_failed_request_is_reported_failed_and_bad_ids_are_ignored(client, monkeypatch):
    rid = "war-room-req-0003"
    client.post(
        "/api/trade/analyze",
        json={**_BODY, "team": "nobody", "teamName": "Nobody"},
        headers={"X-Analysis-Request-Id": rid},
    )
    assert client.get("/api/trade/analyze/status", params={"requestId": rid}).json()["state"] == (
        "failed"
    )
    # An invalid id is not recorded, and the status route refuses it.
    client.post("/api/trade/analyze", json=_BODY, headers={"X-Analysis-Request-Id": "x y"})
    assert client.get("/api/trade/analyze/status", params={"requestId": "x y"}).status_code == 400


def test_progress_registry_is_bounded_and_expires():
    reg = rt.ProgressRegistry(ttl_seconds=0.0, max_entries=2)
    reg.begin("u", "aaaaaaaa1")
    assert reg.snapshot("u", "aaaaaaaa1") is None  # TTL 0: gone on the next read
    reg = rt.ProgressRegistry(ttl_seconds=60.0, max_entries=2)
    for i in range(4):
        reg.begin("u", f"aaaaaaaa{i}")
    assert reg.snapshot("u", "aaaaaaaa0") is None
    assert reg.snapshot("u", "aaaaaaaa3") is not None


# ── in-flight sharing ────────────────────────────────────────────────────


def _concurrent_posts(client, bodies_and_sessions, monkeypatch):
    """Fire requests that are in flight together: the simulation blocks until
    every request has entered the route."""
    entered = threading.Barrier(len(bodies_and_sessions), timeout=10)
    calls: list[int] = []
    real = trade_simulator.simulate_trade
    sessions = {}

    def slow(*a, **k):
        calls.append(1)
        threading.Event().wait(0.5)  # hold the computation open
        return real(*a, **k)

    monkeypatch.setattr(trade_simulator, "simulate_trade", slow)

    def session_by_header(request):
        return sessions[request.headers.get("x-test-user")]

    monkeypatch.setattr(server, "_get_auth_session", session_by_header)
    results: list = [None] * len(bodies_and_sessions)

    def go(i, body, user):
        sessions[user] = _session_for(user)(None)
        entered.wait()
        results[i] = client.post("/api/trade/analyze", json=body, headers={"x-test-user": user})

    threads = [
        threading.Thread(target=go, args=(i, b, u)) for i, (b, u) in enumerate(bodies_and_sessions)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    return results, calls


def test_identical_concurrent_requests_share_one_computation(client, monkeypatch):
    results, calls = _concurrent_posts(client, [(_BODY, "alice"), (_BODY, "alice")], monkeypatch)
    assert all(r.status_code == 200 for r in results)
    assert len(calls) == 1
    a, b = (r.json() for r in results)
    assert _strip(a) == _strip(b)
    # Each request still gets its own decision receipt.
    assert a["analysis"]["decisionRunId"] != b["analysis"]["decisionRunId"]
    assert sorted(
        [a["analysisTiming"]["sharedComputation"], b["analysisTiming"]["sharedComputation"]]
    ) == [
        False,
        True,
    ]


def test_two_users_or_two_trades_never_share(client, monkeypatch):
    other_trade = {**_BODY, "playersOut": ["WR Phi"]}
    results, calls = _concurrent_posts(
        client, [(_BODY, "alice"), (_BODY, "bob"), (other_trade, "alice")], monkeypatch
    )
    assert all(r.status_code == 200 for r in results)
    assert len(calls) == 3
    assert not any(r.json()["analysisTiming"]["sharedComputation"] for r in results)


def test_dedup_key_scopes_to_user_body_and_board():
    s = {"username": "Alice", "sleeper_user_id": "o1"}
    c1, c2 = {"meta": {"generatedAt": "t1"}}, {"meta": {"generatedAt": "t1"}}
    k = rt.dedup_key(s, {"a": 1, "b": [1, 2]}, c1)
    assert k == rt.dedup_key(s, {"b": [1, 2], "a": 1}, c1)  # key order is not identity
    assert k != rt.dedup_key({**s, "username": "bob"}, {"a": 1, "b": [1, 2]}, c1)
    assert k != rt.dedup_key(s, {"a": 2, "b": [1, 2]}, c1)
    assert k != rt.dedup_key(s, {"a": 1, "b": [1, 2]}, c2)  # a different board object
    assert rt.dedup_key(None, {"a": 1}, c1) is None
    assert rt.dedup_key(s, ["not", "a", "dict"], c1) is None


def test_async_single_flight_shares_failure_and_survives_owner_cancel():
    async def scenario():
        flight = rt.AsyncSingleFlight()
        started = asyncio.Event()
        release = asyncio.Event()
        runs = []

        async def work():
            runs.append(1)
            started.set()
            await release.wait()
            return {"v": 1}

        owner = asyncio.ensure_future(flight.run("k", work))
        await started.wait()
        waiter = asyncio.ensure_future(flight.run("k", work))
        await asyncio.sleep(0)
        owner.cancel()  # the client that started it goes away
        release.set()
        value, shared = await waiter
        assert (value, shared, len(runs)) == ({"v": 1}, True, 1)
        assert flight.in_flight() == 0

        async def boom():
            raise RuntimeError("x")

        with pytest.raises(RuntimeError):
            await flight.run("k2", boom)
        assert flight.in_flight() == 0

    asyncio.run(scenario())
