"""R2-5: per-route concurrency limit + compute timeout on BOTH N-team analyze
routes (``src/api/compute_admission.py``).

* the owner module: slots bound real computations, a full route refuses at
  once, the deadline answers the caller without abandoning (or double-
  starting) the computation, config parsing never yields "unlimited";
* ``POST /api/public/league/trade-advisor/analyze``: busy / timeout are a
  retryable 503 ``advisor_unavailable`` in the fixed, value-free copy;
* ``POST /api/trade/analyze-multi``: busy / timeout are a retryable 503
  ``analysis_busy`` / ``analysis_timeout``.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time

import pytest

from src.api import compute_admission as ca
from src.api import public_trade_advisor_api as api
from src.trade import public_advisor
from tests.api import trade_advisor_support as S
from tests.api.test_trade_analyze_multi_route import (  # noqa: F401 — pytest fixtures
    _body,
    _snap,
    _three_team,
    app,
    flag_on,
    real_registry,
)
from tests.api.trade_advisor_support import (  # noqa: F401 — pytest fixtures, used by name
    advisor_app_fixture,
    advisor_client_fixture,
)

# ── Owner module ────────────────────────────────────────────────────────────


def _adm(max_concurrent=1, timeout=1.0, route=ca.ROUTE_PUBLIC_ADVISOR):
    spec = ca.AdmissionSpec(max_concurrent=max_concurrent, timeout_seconds=timeout)
    return ca.ComputeAdmission(route, spec_provider=lambda: spec)


def test_committed_config_matches_the_declared_defaults_and_is_pending_owner():
    raw = json.loads(ca._CONFIG_PATH.read_text(encoding="utf-8"))
    assert raw["status"] == "PENDING_OWNER_CONFIRMATION"
    ca.reset_for_tests()
    for route, default in ca.DEFAULTS.items():
        assert ca.spec_for(route) == default
        assert default.max_concurrent >= 1 and default.timeout_seconds > 0


@pytest.mark.parametrize(
    "entry",
    [
        None,
        {},
        {"maxConcurrent": 0, "timeoutSeconds": 0},
        {"maxConcurrent": -1, "timeoutSeconds": -5},
        {"maxConcurrent": True, "timeoutSeconds": False},
        {"maxConcurrent": "4", "timeoutSeconds": "10"},
        {"maxConcurrent": 1.5, "timeoutSeconds": float("inf")},
        {"maxConcurrent": None, "timeoutSeconds": float("nan")},
    ],
)
def test_malformed_config_falls_back_never_unlimited(entry):
    default = ca.AdmissionSpec(max_concurrent=2, timeout_seconds=5.0)
    assert ca.parse_spec(entry, default) == default


def test_valid_config_is_read():
    default = ca.AdmissionSpec(max_concurrent=2, timeout_seconds=5.0)
    assert ca.parse_spec({"maxConcurrent": 3, "timeoutSeconds": 7}, default) == ca.AdmissionSpec(
        3, 7.0
    )


def test_unknown_route_is_refused():
    with pytest.raises(KeyError):
        ca.spec_for("nope")
    with pytest.raises(KeyError):
        ca.ComputeAdmission("nope")


def test_full_route_refuses_at_once_without_starting_the_work():
    adm = _adm(max_concurrent=1)
    started: list[str] = []

    async def scenario():
        gate = asyncio.Event()

        async def slow():
            started.append("first")
            await gate.wait()
            return "ok"

        async def never():
            started.append("second")
            return "should not run"

        first = asyncio.ensure_future(adm.admit(slow))
        await asyncio.sleep(0)
        assert adm.active == 1
        with pytest.raises(ca.AdmissionRejected) as exc:
            await adm.admit(never)
        assert exc.value.reason == "busy"
        assert exc.value.retry_after_seconds == ca.RETRY_AFTER_SECONDS
        gate.set()
        assert await first == "ok"
        assert adm.active == 0
        assert await adm.admit(lambda: asyncio.sleep(0, result="again")) == "again"

    asyncio.run(scenario())
    assert started == ["first"]


def test_slot_is_released_when_the_computation_raises():
    adm = _adm(max_concurrent=1)

    async def boom():
        raise RuntimeError("x")

    async def scenario():
        with pytest.raises(RuntimeError):
            await adm.admit(boom)
        assert adm.active == 0

    asyncio.run(scenario())


def test_deadline_answers_the_caller_but_keeps_the_slot_until_the_work_finishes():
    adm = _adm(max_concurrent=1, timeout=0.05)
    done = threading.Event()

    def blocking():
        time.sleep(0.3)
        done.set()
        return "late"

    async def scenario():
        loop = asyncio.get_running_loop()

        async def compute():
            return await loop.run_in_executor(None, blocking)

        t0 = time.monotonic()
        with pytest.raises(ca.AdmissionRejected) as exc:
            await adm.within_deadline(lambda: adm.admit(compute))
        assert exc.value.reason == "timeout"
        assert time.monotonic() - t0 < 0.25
        # The computation was NOT abandoned: it still holds its slot, so the
        # route stays bounded by real work, not by waiting callers.
        assert adm.active == 1 and not done.is_set()
        with pytest.raises(ca.AdmissionRejected) as busy:
            await adm.admit(compute)
        assert busy.value.reason == "busy"
        for _ in range(100):
            if adm.active == 0:
                break
            await asyncio.sleep(0.01)
        assert done.is_set() and adm.active == 0

    asyncio.run(scenario())


def test_deadline_passes_a_fast_result_through():
    adm = _adm(timeout=1.0)

    async def scenario():
        return await adm.within_deadline(lambda: adm.admit(lambda: asyncio.sleep(0, result=7)))

    assert asyncio.run(scenario()) == 7


def test_process_wide_instances_are_per_route():
    ca.reset_for_tests()
    a = ca.admission_for(ca.ROUTE_PUBLIC_ADVISOR)
    b = ca.admission_for(ca.ROUTE_ANALYZE_MULTI)
    assert a is ca.admission_for(ca.ROUTE_PUBLIC_ADVISOR)
    assert a is not b


# ── Public analyze route ────────────────────────────────────────────────────


def _set_specs(monkeypatch, *, max_concurrent=1, timeout=5.0):
    spec = ca.AdmissionSpec(max_concurrent=max_concurrent, timeout_seconds=timeout)
    monkeypatch.setattr(ca, "spec_for", lambda _route: spec)


def _wait_idle(adm, seconds=3.0):
    deadline = time.monotonic() + seconds
    while adm.active and time.monotonic() < deadline:
        time.sleep(0.01)
    return adm.active == 0


def _assert_public_refusal(res, reason):
    assert res.status_code == 503, res.text
    body = res.json()
    assert body["error"] == "advisor_unavailable"
    assert body["reason"] == reason
    assert body["message"] == public_advisor.ERROR_MESSAGES[("advisor_unavailable", reason)]
    assert body["retryAfterSeconds"] == ca.RETRY_AFTER_SECONDS
    assert res.headers["retry-after"] == str(ca.RETRY_AFTER_SECONDS)
    assert res.headers["cache-control"] == "no-store"
    public_advisor.assert_advisor_payload_value_free(body, kind="error")
    for sentinel in S.SENTINELS:
        assert str(sentinel) not in res.text


def test_public_route_refuses_when_every_slot_is_busy(advisor_client, monkeypatch):
    _set_specs(monkeypatch, max_concurrent=1, timeout=120.0)
    adm = ca.admission_for(ca.ROUTE_PUBLIC_ADVISOR)
    calls: list[int] = []
    real = public_advisor.evaluate
    monkeypatch.setattr(
        public_advisor, "evaluate", lambda *a, **k: calls.append(1) or real(*a, **k)
    )
    assert adm._try_acquire()  # another computation holds the only slot
    try:
        res = advisor_client.post(S.ANALYZE, json=S.trade_body(*S.NOT_FAIR_TWO))
        _assert_public_refusal(res, "busy")
        assert calls == []  # refused without computing
    finally:
        adm._release()
    ok = advisor_client.post(S.ANALYZE, json=S.trade_body(*S.NOT_FAIR_TWO))
    assert ok.status_code == 200, ok.text
    assert calls == [1] and adm.active == 0


def test_public_route_times_out_retryably_and_keeps_the_slot(advisor_client, monkeypatch):
    _set_specs(monkeypatch, max_concurrent=1, timeout=0.05)
    adm = ca.admission_for(ca.ROUTE_PUBLIC_ADVISOR)
    real = public_advisor.evaluate

    def slow(*a, **k):
        time.sleep(0.4)
        return real(*a, **k)

    monkeypatch.setattr(public_advisor, "evaluate", slow)
    res = advisor_client.post(S.ANALYZE, json=S.trade_body(*S.NOT_FAIR_TWO))
    _assert_public_refusal(res, "timeout")
    assert adm.active == 1  # still computing in its thread
    assert _wait_idle(adm)


def test_public_admission_refusal_is_held_to_the_response_floor(advisor_client, monkeypatch):
    """Like every outcome after the limiter charge, a refusal waits out the
    measured floor (its latency must not encode which path ran)."""
    _set_specs(monkeypatch, max_concurrent=1)
    cfg = {**api.advisor_config(), "responseFloorMs": 120}
    monkeypatch.setattr(api, "advisor_config", lambda: cfg)
    slept: list[float] = []

    async def fake_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(api, "_sleep", fake_sleep)
    adm = ca.admission_for(ca.ROUTE_PUBLIC_ADVISOR)
    assert adm._try_acquire()
    try:
        res = advisor_client.post(S.ANALYZE, json=S.trade_body(*S.NOT_FAIR_TWO))
    finally:
        adm._release()
    assert res.status_code == 503 and res.json()["reason"] == "busy"
    assert slept and 0 < slept[-1] <= 0.12


# ── Private analyze-multi route ─────────────────────────────────────────────


def test_private_route_refuses_when_every_slot_is_busy(app, flag_on, monkeypatch):  # noqa: F811
    client, contract = app
    # A generous deadline: the follow-up request really computes (Team
    # Context, real board) on a possibly loaded CI box.
    _set_specs(monkeypatch, max_concurrent=1, timeout=120.0)
    adm = ca.admission_for(ca.ROUTE_ANALYZE_MULTI)
    teams, legs = _three_team(_snap(contract))
    assert adm._try_acquire()
    try:
        res = client.post("/api/trade/analyze-multi", json=_body(teams, legs))
    finally:
        adm._release()
    assert res.status_code == 503, res.text
    body = res.json()
    assert body["error"] == "analysis_busy"
    assert body["retryable"] is True
    assert body["retryAfterSeconds"] == ca.RETRY_AFTER_SECONDS
    assert res.headers["retry-after"] == str(ca.RETRY_AFTER_SECONDS)
    assert res.headers["cache-control"] == "no-store"
    ok = client.post("/api/trade/analyze-multi", json=_body(teams, legs))
    assert ok.status_code == 200, ok.text
    assert adm.active == 0


def test_private_route_timeout_keeps_the_slot(app, flag_on, monkeypatch):  # noqa: F811
    from src.trade import analyze_service as svc

    client, contract = app
    _set_specs(monkeypatch, max_concurrent=1, timeout=0.05)
    adm = ca.admission_for(ca.ROUTE_ANALYZE_MULTI)
    real = svc.analyze_trade_n

    def slow(*a, **k):
        time.sleep(0.4)
        return real(*a, **k)

    monkeypatch.setattr(svc, "analyze_trade_n", slow)
    teams, legs = _three_team(_snap(contract))
    res = client.post("/api/trade/analyze-multi", json=_body(teams, legs))
    assert res.status_code == 503, res.text
    body = res.json()
    assert body["error"] == "analysis_timeout"
    assert body["retryable"] is True
    assert res.headers["retry-after"] == str(ca.RETRY_AFTER_SECONDS)
    assert adm.active == 1
    assert _wait_idle(adm)
