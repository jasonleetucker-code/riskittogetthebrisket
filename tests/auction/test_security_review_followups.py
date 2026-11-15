"""Follow-ups from the independent security review of the Phase 2 auction PR.

One test per finding, each written to fail if the corresponding fix is removed:

* reports are mock-only (filing AND reading) -- the commissioner reads every
  report and also bids as a seat;
* ``_retire_presented_session`` at the password-reset, invite-claim and
  site-owner call sites (the login call site is pinned in
  ``test_independent_security_audit``);
* idempotency: reset-link replay, ``idempotency_conflict`` on an admin route,
  claim release after a 5xx and after a response that cannot be serialised;
* ``code_sha()`` never shells out on a request path;
* an out-of-range ``client_revision`` is a 400, never a 500.
"""

from __future__ import annotations

import importlib
import time

from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from src.auction import accounts, api, feedback
from tests.auction.test_api_store import (  # noqa: F401 - fixture import
    ORIGIN,
    _owner_client,
    _ready_room,
    env,
    idem,
)
from tests.auction.test_independent_security_audit import (
    PW,
    _join,
    _live_ids,
    _official_room,
    _register,
    _reset_token,
)

# ---------------------------------------------------------------------------
# 1. Reports are mock-only
# ---------------------------------------------------------------------------


def _report_count(st) -> int:
    with st.read() as conn:
        return conn.execute("SELECT COUNT(*) FROM rehearsal_reports").fetchone()[0]


def test_reports_are_refused_to_file_or_read_in_a_non_mock_room(env):  # noqa: F811
    st, app = env
    owner = _owner_client(app)
    owner_uid = owner.get("/api/auction/auth/me").json()["user"]["id"]
    mock = _ready_room(owner)
    alice, alice_uid = _join(app, owner, mock, "S2", "alice")
    official = _official_room(st, owner_uid)
    with st.write() as conn:  # a seated bidder in the official room too
        accounts.add_member(
            st,
            conn,
            room_id=official,
            user_id=alice_uid,
            role="manager",
            seat_id="S2",
            now=time.time(),
        )
    url = f"/api/auction/rooms/{official}/reports"
    # The mock room works (the refusal is about the room type, not the route) ...
    ok = alice.post(
        f"/api/auction/rooms/{mock}/reports", json={"what_happened": "fine"}, headers=idem()
    )
    assert ok.status_code == 200, ok.text
    assert alice.get(f"/api/auction/rooms/{mock}/reports").status_code == 200
    # ... and a commissioner, a seated manager, and a replayed key are all refused
    # in the official one, on both the write and the read side.
    for who, c in (("owner", owner), ("alice", alice)):
        for key in ("official-key-0001", "official-key-0001"):
            r = c.post(
                url,
                json={"what_happened": "my bid was 87"},
                headers={**ORIGIN, "Idempotency-Key": key},
            )
            assert r.status_code == 409 and r.json()["error"] == "reports_mock_only", (who, r.text)
        r = c.get(url)
        assert r.status_code == 409 and r.json()["error"] == "reports_mock_only", (who, r.text)
    assert _report_count(st) == 1  # only the mock room's report exists
    # an unknown room is still a 404, not a mock-only refusal
    assert owner.get("/api/auction/rooms/r_nonesuch/reports").status_code == 404


# ---------------------------------------------------------------------------
# 6. client_revision range
# ---------------------------------------------------------------------------


def test_out_of_range_client_revision_is_a_400_not_a_500(env):  # noqa: F811
    st, app = env
    owner = _owner_client(app)
    room = _ready_room(owner)
    url = f"/api/auction/rooms/{room}/reports"
    bad = [
        b'{"what_happened":"x","client_revision":Infinity}',  # int(inf) -> OverflowError
        b'{"what_happened":"x","client_revision":-Infinity}',
        b'{"what_happened":"x","client_revision":1e400}',  # parses to inf
        b'{"what_happened":"x","client_revision":1000000000000000000000000000000}',  # > SQLite int
        b'{"what_happened":"x","client_revision":9223372036854775808}',  # 2**63
        b'{"what_happened":"x","client_revision":-1}',
    ]
    for n, raw in enumerate(bad):
        r = owner.post(
            url,
            content=raw,
            headers={
                **ORIGIN,
                "Idempotency-Key": f"bad-rev-key-{n:04d}",
                "Content-Type": "application/json",
            },
        )
        assert r.status_code == 400 and r.json()["error"] == "bad_client_revision", (raw, r.text)
    assert _report_count(st) == 0  # nothing was written
    # a sane value, a missing value and an unparseable one keep their old behaviour
    for n, body in enumerate(
        ({"client_revision": 7}, {}, {"client_revision": "not a number"}, {"client_revision": "9"})
    ):
        r = owner.post(
            url,
            json={"what_happened": "ok", **body},
            headers={**ORIGIN, "Idempotency-Key": f"good-rev-key-{n:04d}"},
        )
        assert r.status_code == 200, (body, r.text)
    revs = [x["clientRevision"] for x in owner.get(url).json()["reports"]][::-1]
    assert revs == [7, None, None, 9]


# ---------------------------------------------------------------------------
# 5. code_sha() is resolved at startup, never on a request path
# ---------------------------------------------------------------------------


def test_code_sha_is_resolved_once_at_import_and_never_shells_out_again(env, monkeypatch):  # noqa: F811
    import subprocess

    st, app = env
    calls: list = []

    class Done:
        returncode = 0
        stdout = "c" * 40 + "\n"

    def fake_run(*args, **kwargs):
        calls.append(args)
        return Done()

    monkeypatch.setattr(feedback, "_SHA", feedback._SHA)  # restored on teardown
    monkeypatch.delenv("RISKIT_CODE_SHA", raising=False)
    monkeypatch.setattr(subprocess, "run", fake_run)
    importlib.reload(feedback)  # == process start
    assert len(calls) == 1 and feedback.code_sha() == "c" * 40
    # request paths: the answer is already known, so nothing may shell out
    owner = _owner_client(app)
    room = _ready_room(owner)
    assert TestClient(app).get("/api/auction/meta").json()["codeSha"] == "c" * 40
    r = owner.post(
        f"/api/auction/rooms/{room}/reports", json={"what_happened": "x"}, headers=idem()
    )
    assert r.status_code == 200 and r.json()["codeSha"] == "c" * 40
    assert owner.get(f"/api/auction/rooms/{room}/preflight").json()["codeSha"] == "c" * 40
    for _ in range(3):
        feedback.code_sha()
    assert len(calls) == 1


def test_riskit_code_sha_wins_and_skips_git_entirely(env, monkeypatch):  # noqa: F811
    import subprocess

    calls: list = []
    monkeypatch.setattr(feedback, "_SHA", feedback._SHA)  # restored on teardown
    monkeypatch.setenv("RISKIT_CODE_SHA", "deploy-abc123")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append(a))
    importlib.reload(feedback)
    assert feedback.code_sha() == "deploy-abc123" and calls == []


# ---------------------------------------------------------------------------
# 2. Session retirement at the three remaining call sites
# ---------------------------------------------------------------------------


def _two_members(app, owner, room):
    alice, alice_uid = _join(app, owner, room, "S2", "alice")
    bob, bob_uid = _join(app, owner, room, "S3", "bob")
    return alice, alice_uid, bob, bob_uid


def _assert_retired(st, token, device_id, uid):
    """The presented account's session is dead AND its push device is silenced
    by sign-out (not merely stranded behind the dead session)."""
    assert accounts.session_user(st, token, time.time()) is None
    assert device_id not in _live_ids(st, uid)
    with st.read() as conn:
        row = conn.execute(
            "SELECT disabled_at, disabled_reason FROM notif_devices WHERE id=?", (device_id,)
        ).fetchone()
    assert row["disabled_at"] is not None and row["disabled_reason"] == "signed_out"


def _fresh_login(app, handle):
    return TestClient(app).post(
        "/api/auction/auth/login",
        json={"handle": handle, "password": PW[handle]},
        headers=idem(),
    )


def test_password_reset_retires_the_other_account_session_on_this_browser(env):  # noqa: F811
    st, app = env
    owner = _owner_client(app)
    room = _ready_room(owner)
    alice, alice_uid, _bob, bob_uid = _two_members(app, owner, room)
    device = _register(alice)
    alice_token = alice.cookies.get(api.COOKIE_NAME)
    assert accounts.session_user(st, alice_token, time.time()).id == alice_uid
    # Alice's browser redeems BOB's reset link and becomes bob.
    reset = _reset_token(owner, room, bob_uid)
    r = alice.post(
        "/api/auction/auth/reset",
        json={"token": reset, "password": "bobs-fresh-pass-9"},
        headers=idem(),
    )
    assert r.status_code == 200 and r.json()["user"]["handle"] == "bob"
    _assert_retired(st, alice_token, device, alice_uid)
    assert _fresh_login(app, "alice").status_code == 200  # her ACCOUNT is untouched


def test_site_owner_bridge_retires_the_other_account_session_on_this_browser(env):  # noqa: F811
    st, app = env
    owner = _owner_client(app)
    room = _ready_room(owner)
    alice, alice_uid, _bob, _bob_uid = _two_members(app, owner, room)
    device = _register(alice)
    alice_token = alice.cookies.get(api.COOKIE_NAME)
    # The site owner signs in to Chase Upside on alice's browser and bridges in.
    alice.cookies.set("jason_session", "site-admin")
    r = alice.post("/api/auction/auth/site-owner", headers=idem())
    assert r.status_code == 200 and r.json()["user"]["isSiteAdmin"] is True, r.text
    _assert_retired(st, alice_token, device, alice_uid)
    assert _fresh_login(app, "alice").status_code == 200


def test_invite_claim_retires_a_presented_session_the_claim_did_not_see(env, monkeypatch):  # noqa: F811
    """``invite_claim`` only calls ``_retire_presented_session`` when its own
    lookup found NO signed-in user, so on a normal request the presented cookie
    is already dead and the call is defence in depth.  It is exercised here by
    making that first lookup miss while the cookie is still a live session --
    the case the call exists for (a claim that mints a NEW identity must never
    leave another account's session or push devices on this browser)."""
    st, app = env
    owner = _owner_client(app)
    room = _ready_room(owner)
    alice, alice_uid, _bob, _bob_uid = _two_members(app, owner, room)
    device = _register(alice)
    alice_token = alice.cookies.get(api.COOKIE_NAME)
    invite = (
        owner.post(f"/api/auction/rooms/{room}/invites", json={"seat": "S4"}, headers=idem())
        .json()["joinPath"]
        .split("token=")[1]
    )
    with monkeypatch.context() as m:
        m.setattr(api, "_user", lambda request: None)  # the claim sees no signed-in user
        r = alice.post(
            "/api/auction/invites/claim",
            json={"token": invite, "handle": "carol", "password": "carol-pass-12345"},
            headers=idem(),
        )
    assert r.status_code == 200 and r.json()["user"]["handle"] == "carol", r.text
    _assert_retired(st, alice_token, device, alice_uid)


# ---------------------------------------------------------------------------
# 3. Idempotency: reset-link replay, conflict on an admin route
# ---------------------------------------------------------------------------


def test_reset_link_replay_is_already_issued_and_never_reissues(env):  # noqa: F811
    st, app = env
    owner = _owner_client(app)
    room = _ready_room(owner)
    _alice, alice_uid = _join(app, owner, room, "S2", "alice")
    url = f"/api/auction/rooms/{room}/members/{alice_uid}/reset-link"
    headers = idem()
    first = owner.post(url, headers=headers)
    assert first.status_code == 200, first.text
    token = first.json()["resetPath"].split("token=")[1]
    again = owner.post(url, headers=headers)  # same key: a retry / double click
    assert again.status_code == 409 and again.json()["error"] == "already_issued"
    assert token not in again.text and "resetPath" not in again.json()
    # The replay minted nothing: the first link is still the live one.
    r = TestClient(app).post(
        "/api/auction/auth/reset",
        json={"token": token, "password": "after-replay-pass-1"},
        headers=idem(),
    )
    assert r.status_code == 200 and r.json()["user"]["handle"] == "alice"


def test_same_key_with_a_different_body_on_an_admin_route_is_a_conflict(env):  # noqa: F811
    st, app = env
    owner = _owner_client(app)
    room = _ready_room(owner)
    url = f"/api/auction/rooms/{room}/clock"
    before = float(st.room_row(room)["clock_offset"])
    headers = {**ORIGIN, "Idempotency-Key": "admin-key-000001"}
    assert owner.post(url, json={"advanceSeconds": 60}, headers=headers).status_code == 200
    r = owner.post(url, json={"advanceSeconds": 7200}, headers=headers)
    assert r.status_code == 409 and r.json()["error"] == "idempotency_conflict", r.text
    assert float(st.room_row(room)["clock_offset"]) - before == 60  # the second body never ran
    # the same key AND body is a plain replay
    same = owner.post(url, json={"advanceSeconds": 60}, headers=headers)
    assert same.status_code == 200 and same.headers.get("Idempotent-Replay") == "true"
    assert float(st.room_row(room)["clock_offset"]) - before == 60


# ---------------------------------------------------------------------------
# 3/4. The idempotency claim is released when the route fails
# ---------------------------------------------------------------------------


def _client_without_server_errors(app, owner):
    c = TestClient(app, raise_server_exceptions=False)
    c.cookies.set(api.COOKIE_NAME, owner.cookies.get(api.COOKIE_NAME))
    return c


def _receipt_rows(st, key):
    with st.read() as conn:
        return conn.execute("SELECT status FROM route_receipts WHERE key=?", (key,)).fetchall()


def test_a_5xx_releases_the_claim_so_the_same_key_can_retry(env):  # noqa: F811
    st, app = env
    owner = _owner_client(app)
    calls = {"n": 0}

    async def flaky(request: Request):
        calls["n"] += 1
        if calls["n"] == 1:
            return JSONResponse(status_code=503, content={"error": "store_hiccup"})
        return {"ok": True, "attempt": calls["n"]}

    app.add_api_route("/api/auction/_test/flaky", api._idempotent_route(flaky), methods=["POST"])
    headers = {**ORIGIN, "Idempotency-Key": "flaky-key-000001"}
    first = owner.post("/api/auction/_test/flaky", json={"a": 1}, headers=headers)
    assert first.status_code == 503
    assert _receipt_rows(st, "flaky-key-000001") == []  # released, not parked in_progress
    retry = owner.post("/api/auction/_test/flaky", json={"a": 1}, headers=headers)
    assert retry.status_code == 200 and retry.json() == {"ok": True, "attempt": 2}
    # the success IS now stored: a further retry replays it without running again
    replay = owner.post("/api/auction/_test/flaky", json={"a": 1}, headers=headers)
    assert replay.json() == {"ok": True, "attempt": 2}
    assert replay.headers.get("Idempotent-Replay") == "true" and calls["n"] == 2


def test_a_response_that_cannot_be_built_releases_the_claim(env):  # noqa: F811
    """``JSONResponse(resp)`` runs after the route returns; when it raises (a
    body that is not JSON-serialisable) the claim must be released like any
    other failure, not left ``in_progress`` so every retry is a 409."""
    st, app = env
    owner = _owner_client(app)
    client = _client_without_server_errors(app, owner)
    calls = {"n": 0}

    async def unserialisable(request: Request):
        calls["n"] += 1
        return {"bad": object()}

    app.add_api_route(
        "/api/auction/_test/unserialisable",
        api._idempotent_route(unserialisable),
        methods=["POST"],
    )
    headers = {**ORIGIN, "Idempotency-Key": "unserial-key-0001"}
    first = client.post("/api/auction/_test/unserialisable", json={}, headers=headers)
    assert first.status_code == 500
    assert _receipt_rows(st, "unserial-key-0001") == []
    again = client.post("/api/auction/_test/unserialisable", json={}, headers=headers)
    # the retry RUNS again (500 again), it is not refused as still in progress
    assert again.status_code == 500 and calls["n"] == 2
