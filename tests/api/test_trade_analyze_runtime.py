"""``/api/trade/analyze`` request runtime — timing, progress, in-flight sharing.

Trade War Room speed (owner directive 2026-10-19, part 4).  Everything here is
transport: the analysis itself is unchanged, which the equivalence test below
pins (the same request with and without the runtime's additions produces the
same analysis).  Uses the synthetic league of ``tests/api/test_trade_nfl_exposure``.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import threading
import time
import types

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
            "boardStamp": rt.contract_generation(server.latest_contract_data),
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


def test_progress_registry_is_bounded_and_expires(monkeypatch):
    # A clock that strictly advances on every read.  Windows' monotonic clock
    # ticks every ~15.6 ms, so begin() and the next read can land in the same
    # tick (zero elapsed) and a TTL of 0 has not expired yet; Linux's always
    # advances.  Only this module's ``time`` is replaced.
    ticks = itertools.count(1)
    monkeypatch.setattr(
        rt,
        "time",
        types.SimpleNamespace(monotonic=lambda: float(next(ticks)), perf_counter=time.perf_counter),
    )
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


def test_async_single_flight_survives_owner_cancel_and_releases_keys():
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
    # Guests: state and phase only — no elapsed time, no stage list (polled,
    # either would rebuild the per-stage times the redaction withholds).
    assert snap == {"requestId": rid, "state": "complete", "phase": "complete"}
    assert "by stage" not in timing["note"]


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


# ── round-3 review ───────────────────────────────────────────────────────


def test_async_failed_leader_costs_exactly_one_shared_retry():
    async def scenario(retry_fails: bool):
        flight = rt.AsyncSingleFlight()
        started = asyncio.Event()
        release = asyncio.Event()
        runs: list[str] = []

        async def leader():
            runs.append("leader")
            started.set()
            await release.wait()
            raise RuntimeError("down")

        async def attempt():
            runs.append("retry")
            await asyncio.sleep(0.01)
            if retry_fails:
                raise RuntimeError("still down")
            return "ok"

        lead = asyncio.ensure_future(flight.run("k", leader))
        await started.wait()
        joiners = [asyncio.ensure_future(flight.run("k", attempt)) for _ in range(11)]
        await asyncio.sleep(0)
        release.set()
        with pytest.raises(RuntimeError):
            await lead
        results = await asyncio.gather(*joiners, return_exceptions=True)
        assert runs.count("leader") == 1 and runs.count("retry") == 1  # 2 builds, not 12
        if retry_fails:
            assert all(isinstance(r, RuntimeError) for r in results)
        else:
            assert sorted(r[1] for r in results) == [False] + [True] * 10
            assert all(r[0] == "ok" for r in results)

    asyncio.run(scenario(False))
    asyncio.run(scenario(True))


def test_a_joiner_cancelled_in_the_same_tick_as_its_leader_stays_cancelled():
    async def scenario():
        flight = rt.AsyncSingleFlight()
        started = asyncio.Event()
        retried: list[int] = []

        async def leader():
            started.set()
            await asyncio.sleep(10)

        async def joiner_factory():
            retried.append(1)
            return "should not run"

        lead = asyncio.ensure_future(flight.run("k", leader))
        await started.wait()
        join = asyncio.ensure_future(flight.run("k", joiner_factory))
        await asyncio.sleep(0)
        shared = next(iter(flight._pending.values())).task
        shared.cancel()  # the leader's computation is cancelled ...
        join.cancel()  # ... and so is the joiner, in the same tick
        with pytest.raises(asyncio.CancelledError):
            await join
        assert retried == []  # its own cancellation was not swallowed into a retry
        lead.cancel()
        with pytest.raises(asyncio.CancelledError):
            await lead

    asyncio.run(scenario())


def test_a_finished_progress_entry_is_final_and_its_elapsed_time_frozen():
    import time as _time

    reg = rt.ProgressRegistry()
    handle = reg.begin("alice", "final-0001")
    handle.stage_done("resolve", 1.0)
    handle.finish(rt.CANCELLED)
    first = reg.snapshot("alice", "final-0001")
    # The shielded computation keeps going after the client left ...
    handle.phase("simulation")
    handle.stage_done("simulation", 5.0)
    handle.finish("complete")
    _time.sleep(0.05)
    later = reg.snapshot("alice", "final-0001")
    assert later == first  # ... and moves nothing, elapsedMs included
    assert later["state"] == "cancelled" and later["phase"] == "failed"


def test_only_request_scoped_refusals_are_shareable():
    from fastapi.responses import JSONResponse

    def outcome(status):
        return (None, None, JSONResponse(status_code=status, content={}), [])

    assert server._analysis_outcome_shareable(({}, "main", None, [])) is True
    assert server._analysis_outcome_shareable(outcome(400)) is True
    assert server._analysis_outcome_shareable(outcome(404)) is True
    for status in (401, 403, 500, 502, 503):
        assert server._analysis_outcome_shareable(outcome(status)) is False


# ── round-4 review ───────────────────────────────────────────────────────


def test_a_retrys_personal_refusal_is_never_handed_to_a_joiner():
    """The shared retry's outcome reaches every retry joiner — 5xx included —
    except a refusal about the retry leader's OWN session (401 / 403)."""

    async def scenario(retry_status: int):
        flight = rt.AsyncSingleFlight()
        started = asyncio.Event()
        release = asyncio.Event()
        runs: list[str] = []

        async def leader():
            runs.append("leader")
            started.set()
            await release.wait()
            return 503

        def make(name, status):
            async def attempt():
                runs.append(name)
                await asyncio.sleep(0.01)
                return status

            return attempt

        lead = asyncio.ensure_future(
            flight.run(
                "k", leader, share_if=lambda r: r < 400, personal_if=lambda r: r in (401, 403)
            )
        )
        await started.wait()
        joiners = [
            asyncio.ensure_future(
                flight.run(
                    "k",
                    make(f"j{i}", retry_status if i == 0 else 200),
                    share_if=lambda r: r < 400,
                    personal_if=lambda r: r in (401, 403),
                )
            )
            for i in range(4)
        ]
        await asyncio.sleep(0)
        release.set()
        await lead
        return [await j for j in joiners], runs

    # A 401 from the retry leader's session: each other joiner computes itself.
    results, runs = asyncio.run(scenario(401))
    assert results[0] == (401, False)
    assert results[1:] == [(200, False)] * 3
    assert runs == ["leader", "j0", "j1", "j2", "j3"]
    # A 503 from the retry is shared with every joiner (bounded: 2 attempts).
    results, runs = asyncio.run(scenario(503))
    assert results == [(503, False)] + [(503, True)] * 3
    assert runs == ["leader", "j0"]


def test_a_failed_shared_retry_is_logged_without_user_data(caplog):
    async def scenario():
        flight = rt.AsyncSingleFlight()
        started = asyncio.Event()
        release = asyncio.Event()

        async def leader():
            started.set()
            await release.wait()
            raise RuntimeError("secret detail for alice in dynasty_main")

        async def retry():
            raise ValueError("secret detail for alice in dynasty_main")

        lead = asyncio.ensure_future(flight.run("k", leader, label="req-abc12345"))
        await started.wait()
        join = asyncio.ensure_future(flight.run("k", retry, label="req-def67890"))
        await asyncio.sleep(0)
        release.set()
        with pytest.raises(RuntimeError):
            await lead
        with pytest.raises(ValueError):
            await join
        await asyncio.sleep(0)

    with caplog.at_level("WARNING", logger="src.api.trade_analyze_runtime"):
        asyncio.run(scenario())
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "shared retry failed (request req-def67890): ValueError" in text
    assert "alice" not in text and "dynasty_main" not in text


def test_a_factory_raising_synchronously_is_the_retrys_outcome():
    async def scenario():
        flight = rt.AsyncSingleFlight()
        started = asyncio.Event()
        release = asyncio.Event()
        calls: list[str] = []

        async def leader():
            started.set()
            await release.wait()
            raise RuntimeError("down")

        def sync_boom():
            calls.append("sync")
            raise KeyError("raised before any coroutine existed")

        async def never():
            calls.append("never")
            return "x"

        lead = asyncio.ensure_future(flight.run("k", leader))
        await started.wait()
        first = asyncio.ensure_future(flight.run("k", sync_boom))
        second = asyncio.ensure_future(flight.run("k", never))
        await asyncio.sleep(0)
        release.set()
        with pytest.raises(RuntimeError):
            await lead
        for joiner in (first, second):
            with pytest.raises(KeyError):
                await joiner
        assert calls == ["sync"]  # one retry attempt, shared — not one per joiner

    asyncio.run(scenario())


def test_a_reused_request_id_cannot_be_moved_by_the_old_handle():
    reg = rt.ProgressRegistry()
    old = reg.begin("alice", "reused-0001")
    old.finish("complete")
    new = reg.begin("alice", "reused-0001")  # the client reuses the id
    old.finish(rt.FAILED)
    old.phase("simulation")
    old.stage_done("simulation", 99.0)
    snap = reg.snapshot("alice", "reused-0001")
    assert snap["state"] == "running" and snap["phase"] == "received"
    assert snap["completedStages"] == []
    new.finish("complete")
    assert reg.snapshot("alice", "reused-0001")["state"] == "complete"


def test_personal_refusals_are_classified():
    from fastapi.responses import JSONResponse

    def outcome(status):
        return (None, None, JSONResponse(status_code=status, content={}), [])

    assert server._analysis_outcome_personal(({}, "main", None, [])) is False
    for status in (401, 403):
        assert server._analysis_outcome_personal(outcome(status)) is True
    for status in (400, 404, 500, 503):
        assert server._analysis_outcome_personal(outcome(status)) is False


# ── board generation (five-point review, 2026-10-20) ─────────────────────
#
# The served contract stamps its generation at the TOP level
# (``generatedAt``, beside ``dataFreshness``); ``meta`` carries only
# ``leagueKey`` / ``packageModel`` / ``scoringFingerprint`` /
# ``scoringProfile``.  Reading ``meta.generatedAt`` therefore always answered
# "" / ``None`` on a real board: the in-flight key's generation component was
# dead (only ``id(contract)`` separated two boards) and every decision receipt
# carried ``boardStamp: null``.  The fixtures above put ``generatedAt`` under
# ``meta``, which is why nothing caught it.


def test_contract_generation_reads_the_top_level_stamp_the_served_board_carries():
    assert rt.contract_generation({"generatedAt": "2026-10-20T01:10:59Z", "meta": {}}) == (
        "2026-10-20T01:10:59Z"
    )
    # A board carrying it only under ``meta`` (older shape) still answers.
    assert rt.contract_generation({"meta": {"generatedAt": "t-meta"}}) == "t-meta"
    # Unknown is ``None``, never a fabricated stamp.
    assert rt.contract_generation({"meta": {}}) is None
    assert rt.contract_generation(None) is None


def test_dedup_key_separates_two_generations_of_one_board_object():
    s = {"username": "alice", "sleeper_user_id": "o1"}
    board = {"generatedAt": "gen-1", "meta": {"leagueKey": "main"}}
    k1 = rt.dedup_key("alice", s, {"a": 1}, board, league_key="main")
    board["generatedAt"] = "gen-2"  # a new generation (same object address)
    k2 = rt.dedup_key("alice", s, {"a": 1}, board, league_key="main")
    assert k1 != k2


def test_decision_receipt_names_the_board_generation(client, monkeypatch):
    contract = _contract(league_key="main")
    contract.pop("generatedAt", None)
    (contract.get("meta") or {}).pop("generatedAt", None)
    contract["generatedAt"] = "2026-10-20T01:10:59.009881+00:00"  # the served shape
    monkeypatch.setattr(server, "latest_contract_data", contract)
    res = client.post("/api/trade/analyze", json=_BODY)
    assert res.status_code == 200, res.text
    receipt = res.json()["analysis"]["decision"]["receipt"]
    assert receipt["boardStamp"] == "2026-10-20T01:10:59.009881+00:00"
