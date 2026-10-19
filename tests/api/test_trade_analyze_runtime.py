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


def _concurrent_posts(client, requests_spec, monkeypatch, *, during=None):
    """Fire requests that are in flight together: the simulation blocks until
    every request has entered the route.

    ``requests_spec`` entries are ``(body, user)`` or ``(body, user, extra)``
    with ``extra`` holding ``headers`` / ``params`` / a ``session`` override.
    ``during`` runs inside the (first) held simulation, after the others had
    time to join it.
    """
    entered = threading.Barrier(len(requests_spec), timeout=10)
    calls: list[int] = []
    real = trade_simulator.simulate_trade
    sessions = {}

    def slow(*a, **k):
        calls.append(1)
        threading.Event().wait(0.5)  # hold the computation open
        if during is not None and len(calls) == 1:
            during()
        return real(*a, **k)

    monkeypatch.setattr(trade_simulator, "simulate_trade", slow)

    def session_by_header(request):
        return sessions[request.headers.get("x-test-user")]

    monkeypatch.setattr(server, "_get_auth_session", session_by_header)
    results: list = [None] * len(requests_spec)

    def go(i, spec):
        body, user = spec[0], spec[1]
        extra = spec[2] if len(spec) > 2 else {}
        sessions[user] = extra.get("session") or _session_for(user)(None)
        entered.wait()
        results[i] = client.post(
            "/api/trade/analyze",
            json=body,
            headers={"x-test-user": user, **extra.get("headers", {})},
            params=extra.get("params"),
        )

    threads = [threading.Thread(target=go, args=(i, spec)) for i, spec in enumerate(requests_spec)]
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
    # The joiner's view of the shared stages is frozen when the computation
    # ended: the creator's own receipt stage is never in it.
    joiner = a if a["analysisTiming"]["sharedComputation"] else b
    shared_names = [st["stage"] for st in joiner["analysisTiming"]["sharedStages"]]
    assert "receipt" not in shared_names and "simulation" in shared_names
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


def test_dedup_key_scopes_to_user_league_query_body_and_board():
    s = {"username": "Alice", "sleeper_user_id": "o1"}
    c1, c2 = {"meta": {"generatedAt": "t1"}}, {"meta": {"generatedAt": "t1"}}

    def key(owner="alice", body=None, contract=c1, league="main", query=()):
        return rt.dedup_key(
            owner,
            s,
            {"a": 1, "b": [1, 2]} if body is None else body,
            contract,
            league_key=league,
            query_items=query,
        )

    k = key()
    assert k == key(body={"b": [1, 2], "a": 1})  # key order is not identity
    assert k != key(owner="bob")
    assert k != key(body={"a": 2, "b": [1, 2]})
    assert k != key(contract=c2)  # a different board object
    assert k != key(league="side")  # resolved league (query / body / saved)
    assert k != key(query=[("valuationMode", "leagueAdjusted")])
    # A repeated parameter is read last-wins, so ORDER is identity.
    assert key(query=[("valuationMode", "market"), ("valuationMode", "leagueAdjusted")]) != key(
        query=[("valuationMode", "leagueAdjusted"), ("valuationMode", "market")]
    )
    assert key(owner=None) is None
    assert key(league=None) is None  # unresolvable: never shared
    assert key(body=["not", "a", "dict"]) is None


def test_guest_pass_sessions_are_never_pooled():
    guest = {"username": "guest", "auth_method": "guest_pass", "guest_pass_id": 7}
    a = rt.session_owner(guest, "session-aaaa")
    b = rt.session_owner(guest, "session-bbbb")
    assert a and b and a != b
    assert "session-aaaa" not in a  # the raw session id is a credential
    assert rt.session_owner(guest, None) is None  # unknown session: no bucket
    assert rt.session_owner({"username": "Alice"}) == "alice"


def test_progress_cap_is_per_owner():
    reg = rt.ProgressRegistry(ttl_seconds=60.0, max_entries=512, max_per_owner=3)
    reg.begin("victim", "victim-0001")
    for i in range(10):
        reg.begin("noisy", f"noisy-{i:04d}")
    assert reg.snapshot("victim", "victim-0001") is not None
    assert reg.snapshot("noisy", "noisy-0006") is None
    assert all(reg.snapshot("noisy", f"noisy-{i:04d}") for i in (7, 8, 9))


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


def test_concurrent_identical_refusals_each_get_the_refusal(client, monkeypatch):
    body = {**_BODY, "team": "nobody", "teamName": "Nobody"}
    results, _calls = _concurrent_posts(client, [(body, "alice"), (body, "alice")], monkeypatch)
    assert [r.status_code for r in results] == [404, 404]
    assert all(r.json() == {"error": "team_not_found", "leagueKey": "main"} for r in results)


def test_requests_differing_only_in_query_league_never_share(client, monkeypatch):
    """``?leagueKey`` outranks the body's.  Same user, same body, different
    query league: the second must get ITS league's answer, never the first's."""
    results, _calls = _concurrent_posts(
        client,
        [(_BODY, "alice"), (_BODY, "alice", {"params": {"leagueKey": "side"}})],
        monkeypatch,
    )
    main, side = results
    assert main.status_code == 200 and main.json()["leagueKey"] == "main"
    # "side" cannot be served from this board (no proven scoring identity /
    # overlay in the fixture): its OWN refusal, never main's analysis.
    assert side.status_code == 503 and side.json()["leagueKey"] == "side"


def test_requests_differing_only_in_saved_active_league_never_share(client, monkeypatch):
    """No leagueKey anywhere: the user's saved active league decides.  If it
    changes between two in-flight requests they answer for different leagues
    — each for the league it resolved, never the other's."""
    calls = {"n": 0}

    def saved_state(username):
        calls["n"] += 1
        return {"activeLeagueKey": "main" if calls["n"] == 1 else "side"}

    monkeypatch.setattr(server._user_kv, "get_user_state", saved_state)
    body = {k: v for k, v in _BODY.items() if k != "leagueKey"}
    results, _ = _concurrent_posts(client, [(body, "alice"), (body, "alice")], monkeypatch)
    # One request resolved main and was answered for main; the other resolved
    # side and got side's own answer (here: a refusal), not main's analysis.
    # (Before the fix both answered 200 for main: the second joined the first.)
    assert sorted((r.status_code, r.json().get("leagueKey")) for r in results) == [
        (200, "main"),
        (503, "side"),
    ]
    assert calls["n"] == 2  # each request resolved its league exactly once


def test_a_joining_request_reports_joined_while_the_shared_computation_runs(client, monkeypatch):
    snaps = {}

    def during():
        snaps["a"] = rt.PROGRESS.snapshot("alice", "join-test-aaaa")
        snaps["b"] = rt.PROGRESS.snapshot("alice", "join-test-bbbb")

    _concurrent_posts(
        client,
        [
            (_BODY, "alice", {"headers": {"X-Analysis-Request-Id": "join-test-aaaa"}}),
            (_BODY, "alice", {"headers": {"X-Analysis-Request-Id": "join-test-bbbb"}}),
        ],
        monkeypatch,
        during=during,
    )
    phases = sorted(s["phase"] for s in snaps.values())
    assert phases == ["joined_identical_request", "simulation"]


def test_no_progress_entry_for_a_request_that_fails_validation(client):
    rid = "invalid-req-0001"
    client.post(
        "/api/trade/analyze",
        json={**_BODY, "leagueKey": "nope"},
        headers={"X-Analysis-Request-Id": rid},
    )
    client.post("/api/trade/analyze", content=b"[]", headers={"X-Analysis-Request-Id": rid})
    assert client.get("/api/trade/analyze/status", params={"requestId": rid}).status_code == 404


def test_guest_sessions_share_only_within_their_own_session(client, monkeypatch):
    guest = {"username": "guest", "auth_method": "guest_pass", "guest_pass_id": 7}
    cookie = server.JASON_AUTH_COOKIE_NAME
    _, calls = _concurrent_posts(
        client,
        [
            (_BODY, "g1", {"session": guest, "headers": {"cookie": f"{cookie}=sess-one"}}),
            (_BODY, "g2", {"session": guest, "headers": {"cookie": f"{cookie}=sess-two"}}),
        ],
        monkeypatch,
    )
    assert len(calls) == 2  # two guest-pass holders: two computations


# ── round-2 review ───────────────────────────────────────────────────────


def test_repeated_query_parameters_in_two_orders_never_share(client, monkeypatch):
    q1 = [("valuationMode", "market"), ("valuationMode", "leagueAdjusted")]
    q2 = [("valuationMode", "leagueAdjusted"), ("valuationMode", "market")]
    _, calls = _concurrent_posts(
        client,
        [(_BODY, "alice", {"params": q1}), (_BODY, "alice", {"params": q2})],
        monkeypatch,
    )
    assert len(calls) == 2


def test_a_transient_5xx_is_not_handed_to_a_joiner(client, monkeypatch):
    """Overlay fetch fails once, then succeeds.  Alone: 503 then 200.  Two
    identical requests in flight together must not both get the 503."""
    import time as _time

    from src.api import sleeper_overlay

    fetches: list[int] = []
    loaded = server.latest_contract_data["sleeper"]

    def flaky_overlay(**_kw):
        fetches.append(1)
        if len(fetches) == 1:
            _time.sleep(0.6)  # the second request joins while this one is failing
            return None
        return {"teams": loaded["teams"], "leagueConfig": {}}

    monkeypatch.setattr(sleeper_overlay, "fetch_sleeper_overlay", flaky_overlay)
    monkeypatch.setattr(server._sleeper_overlay, "fetch_sleeper_overlay", flaky_overlay)
    monkeypatch.setattr(server, "_scoring_identity_error", lambda *_a, **_k: None)
    monkeypatch.setattr(
        server._sleeper_overlay,
        "merge_cross_league_sleeper_block",
        lambda **kw: (dict(kw["loaded_sleeper"]), None),
    )
    side = {**_BODY, "leagueKey": "side"}
    results, _ = _concurrent_posts(client, [(side, "alice"), (side, "alice")], monkeypatch)
    assert sorted(r.status_code for r in results) == [200, 503]
    assert len(fetches) == 2  # the joiner made its own attempt


def test_cancelled_request_is_finished_not_left_running(two_league_registry, monkeypatch):  # noqa: F811
    from starlette.requests import Request

    rt.PROGRESS.clear()
    monkeypatch.setattr(server, "latest_contract_data", _contract(league_key="main"))
    monkeypatch.setattr(server, "_get_auth_session", _session_for("alice"))

    async def cancelled(*_a, **_k):
        raise asyncio.CancelledError

    monkeypatch.setattr(server, "_compute_trade_analysis", cancelled)
    body = json.dumps(_BODY).encode()

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/trade/analyze",
        "headers": [(b"x-analysis-request-id", b"cancel-req-0001")],
        "query_string": b"",
    }

    async def go():
        with pytest.raises(asyncio.CancelledError):
            await server.post_trade_analyze(Request(scope, receive))

    asyncio.run(go())
    snap = rt.PROGRESS.snapshot("alice", "cancel-req-0001")
    assert snap["state"] == "cancelled" and snap["phase"] == "failed"
    rt.PROGRESS.clear()


def test_one_guest_pass_cannot_evict_other_users_progress():
    reg = rt.ProgressRegistry(ttl_seconds=60.0, max_entries=512, max_per_owner=4)
    reg.begin("alice", "alice-0001")
    for i in range(40):  # one pass, forty minted sessions
        reg.begin(f"guest_pass:7:session{i:02d}", f"guest-{i:04d}")
    assert reg.snapshot("alice", "alice-0001") is not None
    alive = [i for i in range(40) if reg.snapshot(f"guest_pass:7:session{i:02d}", f"guest-{i:04d}")]
    assert alive == [36, 37, 38, 39]  # the pass's own oldest entries went first


def test_guests_get_total_time_only(client, monkeypatch):
    guest = {"username": "guest", "auth_method": "guest_pass", "guest_pass_id": 7}
    monkeypatch.setattr(server, "_get_auth_session", lambda _r: guest)
    cookie = server.JASON_AUTH_COOKIE_NAME
    rid = "guest-req-0001"
    res = client.post(
        "/api/trade/analyze",
        json=_BODY,
        headers={"cookie": f"{cookie}=sess-guest", "X-Analysis-Request-Id": rid},
    )
    assert res.status_code == 200, res.text
    timing = res.json()["analysisTiming"]
    assert "stages" not in timing and "sharedStages" not in timing
    assert timing["detail"] == "total_only" and timing["totalMs"] >= 0
    assert res.headers["server-timing"].startswith("total;dur=")
    assert "," not in res.headers["server-timing"]
    snap = client.get(
        "/api/trade/analyze/status",
        params={"requestId": rid},
        headers={"cookie": f"{cookie}=sess-guest"},
    ).json()
    assert snap["state"] == "complete"
    assert all(set(st) == {"stage"} for st in snap["completedStages"])


def test_resolve_covers_the_league_resolution(client, monkeypatch):
    import time as _time

    real = server._resolve_league_for_request

    def slow(*a, **k):
        _time.sleep(0.25)
        return real(*a, **k)

    monkeypatch.setattr(server, "_resolve_league_for_request", slow)
    timing = client.post("/api/trade/analyze", json=_BODY).json()["analysisTiming"]
    stages = {st["stage"]: st["ms"] for st in timing["stages"]}
    assert list(stages)[0] == "resolve" and stages["resolve"] >= 250


def test_async_single_flight_hands_a_failed_leader_to_no_one():
    async def scenario():
        flight = rt.AsyncSingleFlight()
        started = asyncio.Event()
        release = asyncio.Event()
        runs = []

        async def leader_fails():
            runs.append("leader")
            started.set()
            await release.wait()
            raise RuntimeError("transient")

        async def joiner_ok():
            runs.append("joiner")
            return "ok"

        lead = asyncio.ensure_future(flight.run("k", leader_fails))
        await started.wait()
        join = asyncio.ensure_future(flight.run("k", joiner_ok))
        await asyncio.sleep(0)
        release.set()
        with pytest.raises(RuntimeError):
            await lead
        assert await join == ("ok", False)
        assert runs == ["leader", "joiner"]

        # A result share_if rejects (a 5xx) is not shared either.
        started.clear()
        release.clear()

        async def leader_5xx():
            started.set()
            await release.wait()
            return 503

        async def joiner_200():
            return 200

        lead = asyncio.ensure_future(flight.run("k2", leader_5xx, share_if=lambda r: r < 500))
        await started.wait()
        join = asyncio.ensure_future(flight.run("k2", joiner_200, share_if=lambda r: r < 500))
        await asyncio.sleep(0)
        release.set()
        assert await lead == (503, False)
        assert await join == (200, False)

    asyncio.run(scenario())
