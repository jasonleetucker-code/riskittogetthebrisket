"""W22-F003 — the login endpoint's own failure throttle.

The finding: login had no throttle of its own, no lockout and no
failure backoff — 200 wrong-password attempts landed at 223 req/s with
zero 429.  The repair is a dedicated failure throttle in
``src/api/rate_limit.py`` (``login_*`` — one owner, beside the public
token buckets), wired into ``POST /api/auth/login``:

* failures are keyed by client IP AND by (client IP, username) —
  NEVER by username alone, so failures from elsewhere cannot lock the
  real owner out (the isolation test below pins the invariant);
* ``_LOGIN_FREE_ATTEMPTS`` failures per window are free, then the next
  attempt is delayed exponentially (1s → 2s → 4s ... capped), served
  as 429 + ``retryAfterSeconds``;
* the throttle is checked BEFORE credential comparison (a blocked
  caller learns nothing), and success clears the (ip, username) state.

Tests drive the clock through ``rate_limit._login_now`` — no sleeps.
Both ``X-Forwarded-For`` and ``X-Real-IP`` are set to the same single
IP so the tests hold under either resolution order of
``_client_ip_from_request`` (this branch reads XFF-first; #1112 moves
to X-Real-IP-first).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import server
from src.api import rate_limit


OWNER = "owneruser"
OWNER_PW = "correct-horse-not-a-real-secret"


def _hdrs(ip: str) -> dict[str, str]:
    return {"X-Forwarded-For": ip, "X-Real-IP": ip}


def _login(client, ip: str, username: str, password: str):
    return client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
        headers=_hdrs(ip),
    )


@pytest.fixture(autouse=True)
def _login_env(monkeypatch):
    monkeypatch.setattr(server, "JASON_LOGIN_USERNAME", OWNER)
    monkeypatch.setattr(server, "JASON_LOGIN_PASSWORD", OWNER_PW)
    # Keep wrong-password attempts away from the guest-pass SQLite —
    # only the throttle is under test here.
    monkeypatch.setattr(server._guest_passes, "validate", lambda pw: None)
    rate_limit.reset_for_tests()
    yield
    rate_limit.reset_for_tests()


@pytest.fixture
def clock(monkeypatch):
    """Deterministic clock for the login throttle only."""

    class _Clock:
        now = 1_000_000.0

        def advance(self, seconds: float) -> None:
            _Clock.now += seconds

    monkeypatch.setattr(rate_limit, "_login_now", lambda: _Clock.now)
    return _Clock()


# ── The invariant, pinned structurally ─────────────────────────────


def test_keys_never_contain_a_bare_username_component():
    """A lockout keyed on username alone would let an attacker lock the
    real owner out remotely.  The per-username key is always scoped
    within the client IP, and no usable IP means no keys at all."""
    assert rate_limit._login_keys("1.2.3.4", "Bob") == [
        "ip:1.2.3.4",
        "ipuser:1.2.3.4|bob",
    ]
    assert rate_limit._login_keys("", "bob") == []
    assert rate_limit._login_keys("   ", "bob") == []


def test_failures_from_one_ip_do_not_throttle_another_ip(clock):
    """The isolation half of the invariant, end to end: a burst from
    IP A neither throttles nor locks out the same username at IP B."""
    with TestClient(server.app, raise_server_exceptions=True) as c:
        for _ in range(6):
            _login(c, "10.0.0.1", OWNER, "wrong")
        # IP A is now backed off.
        res_a = _login(c, "10.0.0.1", OWNER, "wrong")
        assert res_a.status_code == 429
        # IP B, same username: a wrong attempt is a plain 401 ...
        res_b = _login(c, "10.0.0.2", OWNER, "wrong")
        assert res_b.status_code == 401, res_b.text
        # ... and the real owner still signs in.
        res_ok = _login(c, "10.0.0.2", OWNER, OWNER_PW)
        assert res_ok.status_code == 200, res_ok.text
        assert res_ok.json()["ok"] is True


# ── Backoff behavior ───────────────────────────────────────────────


def test_first_attempt_is_never_throttled(clock):
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = _login(c, "10.1.0.1", OWNER, "wrong")
    assert res.status_code == 401
    assert res.json() == {"ok": False, "error": "Invalid username or password."}


def test_burst_gets_429_with_growing_retry_after(clock):
    with TestClient(server.app, raise_server_exceptions=True) as c:
        # The free attempts are plain 401s.
        for i in range(rate_limit._LOGIN_FREE_ATTEMPTS):
            res = _login(c, "10.1.0.2", OWNER, "wrong")
            assert res.status_code == 401, f"attempt {i + 1} throttled early"
        # The next attempt is backed off.
        first = _login(c, "10.1.0.2", OWNER, "wrong")
        assert first.status_code == 429, first.text
        body = first.json()
        assert body["error"] == "too_many_attempts"
        retry_1 = body["retryAfterSeconds"]
        assert retry_1 >= 1
        assert first.headers["Retry-After"] == str(retry_1)
        # Wait out the delay: the attempt lands (401) and doubles the
        # backoff for the one after it.
        clock.advance(retry_1 + 0.1)
        res = _login(c, "10.1.0.2", OWNER, "wrong")
        assert res.status_code == 401
        second = _login(c, "10.1.0.2", OWNER, "wrong")
        assert second.status_code == 429
        retry_2 = second.json()["retryAfterSeconds"]
        assert retry_2 > retry_1, f"backoff did not grow: {retry_1} -> {retry_2}"


def test_backoff_caps_at_the_declared_ceiling(clock):
    ip, user = "10.1.0.6", "someone"
    for _ in range(60):
        rate_limit.login_record_failure(ip, user)
    blocked, retry_after = rate_limit.login_throttle_check(ip, user)
    assert blocked
    assert retry_after <= int(rate_limit._LOGIN_BACKOFF_CAP_SECONDS)


def test_correct_password_is_blocked_during_backoff_then_works_after(clock):
    """The check runs BEFORE credential comparison — a blocked caller
    learns nothing about validity — and expiry restores access."""
    with TestClient(server.app, raise_server_exceptions=True) as c:
        for _ in range(rate_limit._LOGIN_FREE_ATTEMPTS):
            _login(c, "10.1.0.3", OWNER, "wrong")
        res = _login(c, "10.1.0.3", OWNER, OWNER_PW)
        assert res.status_code == 429, "correct password must not bypass the backoff"
        clock.advance(2.0)
        res = _login(c, "10.1.0.3", OWNER, OWNER_PW)
        assert res.status_code == 200, res.text
        assert res.json()["ok"] is True


def test_success_resets_the_ip_username_state(clock):
    with TestClient(server.app, raise_server_exceptions=True) as c:
        for _ in range(rate_limit._LOGIN_FREE_ATTEMPTS):
            _login(c, "10.1.0.4", OWNER, "wrong")
        clock.advance(2.0)
        ok = _login(c, "10.1.0.4", OWNER, OWNER_PW)
        assert ok.status_code == 200
        # The (ip, username) failure state is gone ...
        with rate_limit._login_lock:
            assert f"ipuser:10.1.0.4|{OWNER}" not in rate_limit._login_failures
        # ... so the next mistake is a plain 401, not a 429.
        res = _login(c, "10.1.0.4", OWNER, "wrong")
        assert res.status_code == 401


def test_cooloff_window_forgets_old_failures(clock):
    with TestClient(server.app, raise_server_exceptions=True) as c:
        for _ in range(6):
            _login(c, "10.1.0.5", OWNER, "wrong")
        assert _login(c, "10.1.0.5", OWNER, "wrong").status_code == 429
        # A full cool-off later the window has reset: free attempts again.
        clock.advance(rate_limit._LOGIN_FAILURE_WINDOW_SECONDS + 1)
        res = _login(c, "10.1.0.5", OWNER, "wrong")
        assert res.status_code == 401
        res = _login(c, "10.1.0.5", OWNER, OWNER_PW)
        assert res.status_code == 200
