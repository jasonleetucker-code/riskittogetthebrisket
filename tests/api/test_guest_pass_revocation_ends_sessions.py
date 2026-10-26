"""Revoking a guest pass ends every session it minted (security S3).

Before this, ``guest_passes.revoke`` only flipped ``validate``: no NEW login
could use the pass, but a session it had already minted kept authenticating
until the pass's own expiry.  The production verification workflow mints a
pass, logs in, and revokes it over SSH in a DIFFERENT process — so the
server's in-memory session never learned of the revoke, and a session cookie
that leaked (it did: Playwright traces of a failed run were uploaded as a
public artifact) stayed a valid guest session for the pass's whole window.

Worse, the persistent session store never recorded a session's expiry or
pass id, so after any restart a guest session rehydrated as an unbounded
30-day session.

Pinned here:

* revoke (direct module call, as the workflow does) → the existing session
  is 401 on a private route on its very next request;
* the same holds when the persisted-row deletion "loses the race" (the
  in-memory session is still cached) — the pass row is the authority;
* the admin revoke endpoint also drops this process's cached sessions;
* the persistent store round-trips ``expires_at_epoch`` / ``guest_pass_id``,
  and ``hydrate`` refuses a guest row without them and any expired row;
* ``revoke`` deletes the persisted sessions of that pass only.

And the complement — what must NOT end a guest session (V1 verification run
39221318435 lost its session mid-suite and with it the revoke proof):

* a backend restart: ``hydrate`` keeps a bounded guest row even under a
  non-empty allowlist that does not name ``guest`` (production's allowlist
  never does — guests are refused admin by NOT being on it), and revocation
  still ends the rehydrated session;
* an unreadable pass store: the request is refused (fail closed) but the
  session is kept, so the next request after the store recovers succeeds.
  A definitively inactive pass (revoked, expired, unknown id) still ends the
  session exactly as before.
"""

from __future__ import annotations

import sqlite3
import time

import pytest
from fastapi.testclient import TestClient

import server
from src.api import guest_passes, session_store

PRIVATE_ROUTE = "/api/user/state"


@pytest.fixture(autouse=True)
def _known_allowlist(monkeypatch):
    monkeypatch.setattr(server, "PRIVATE_APP_ALLOWED_USERNAMES", frozenset({"admin"}))
    monkeypatch.setattr(server, "JASON_LOGIN_USERNAME", "admin")
    monkeypatch.setattr(server, "JASON_LOGIN_PASSWORD", "admin-pwd")
    yield


@pytest.fixture(autouse=True)
def _isolated_stores(monkeypatch, tmp_path):
    pass_db = tmp_path / "guest_passes.sqlite"
    sess_db = tmp_path / "session_store.sqlite"
    monkeypatch.setattr(guest_passes, "_DEFAULT_DB_PATH", pass_db)
    monkeypatch.setattr(guest_passes, "_setup_done_paths", set())
    monkeypatch.setattr(session_store, "_DEFAULT_DB_PATH", sess_db)
    session_store._setup_done.clear()  # noqa: SLF001
    monkeypatch.setattr(server, "auth_sessions", {})
    from src.api import rate_limit  # noqa: PLC0415

    rate_limit.reset_for_tests()
    yield {"pass_db": pass_db, "sess_db": sess_db}
    rate_limit.reset_for_tests()
    session_store._setup_done.clear()  # noqa: SLF001


def _login(client: TestClient, token: str):
    res = client.post("/api/auth/login", json={"username": "", "password": token})
    assert res.status_code == 200, res.text
    assert res.json().get("guest") is True
    return res


def _guest_session_ids() -> list[str]:
    return [
        sid
        for sid, sess in server.auth_sessions.items()
        if isinstance(sess, dict) and sess.get("auth_method") == "guest_pass"
    ]


def test_revoke_ends_an_existing_session_on_its_next_request():
    pass_row, token = guest_passes.create(duration_hours=2.0)
    with TestClient(server.app, base_url="https://testserver") as c:
        _login(c, token)
        assert c.get(PRIVATE_ROUTE).status_code == 200
        # The workflow revokes in ANOTHER process: a direct module call,
        # never through this server's admin endpoint.
        assert guest_passes.revoke(pass_row.id) is True
        res = c.get(PRIVATE_ROUTE)
        assert res.status_code == 401, res.text
        assert c.get("/api/auth/status").json().get("authenticated") is False
    assert _guest_session_ids() == []


def test_revoked_pass_is_refused_even_if_session_deletion_races(monkeypatch):
    """The persisted-row deletion is belt-and-braces; the pass row decides."""
    pass_row, token = guest_passes.create(duration_hours=2.0)
    monkeypatch.setattr(session_store, "evict_guest_pass", lambda *a, **k: 0)
    with TestClient(server.app, base_url="https://testserver") as c:
        _login(c, token)
        assert c.get(PRIVATE_ROUTE).status_code == 200
        guest_passes.revoke(pass_row.id)
        assert _guest_session_ids(), "precondition: the session is still cached"
        assert c.get(PRIVATE_ROUTE).status_code == 401


def test_admin_revoke_endpoint_drops_cached_sessions(monkeypatch):
    pass_row, token = guest_passes.create(duration_hours=2.0)
    with TestClient(server.app, base_url="https://testserver") as guest:
        _login(guest, token)
        assert len(_guest_session_ids()) == 1
        # An admin caller for this one request only: the private-API gate
        # and the admin check are stubbed, then restored before the guest's
        # own request is judged by the real gate.
        real_is_auth = server._is_authenticated
        monkeypatch.setattr(server, "_require_admin_session", lambda r: {"username": "admin"})
        monkeypatch.setattr(server, "_is_authenticated", lambda r: True)
        with TestClient(server.app, base_url="https://testserver") as admin:
            res = admin.post(f"/api/admin/guest-pass/{pass_row.id}/revoke")
        monkeypatch.setattr(server, "_is_authenticated", real_is_auth)
        assert res.status_code == 200 and res.json()["ok"] is True
        assert _guest_session_ids() == []
        assert guest.get(PRIVATE_ROUTE).status_code == 401


def test_other_passes_sessions_survive_a_revoke():
    p1, t1 = guest_passes.create(duration_hours=2.0)
    _p2, t2 = guest_passes.create(duration_hours=2.0)
    with (
        TestClient(server.app, base_url="https://testserver") as a,
        TestClient(server.app, base_url="https://testserver") as b,
    ):
        _login(a, t1)
        _login(b, t2)
        guest_passes.revoke(p1.id)
        assert a.get(PRIVATE_ROUTE).status_code == 401
        assert b.get(PRIVATE_ROUTE).status_code == 200


def test_guest_session_without_a_pass_id_is_refused():
    """Fail closed: a guest session that cannot name its pass cannot be
    revoked, so it does not authenticate (legacy rehydrated rows)."""
    _p, token = guest_passes.create(duration_hours=2.0)
    with TestClient(server.app, base_url="https://testserver") as c:
        _login(c, token)
        (sid,) = _guest_session_ids()
        server.auth_sessions[sid].pop("guest_pass_id")
        assert c.get(PRIVATE_ROUTE).status_code == 401


def test_session_store_round_trips_expiry_and_pass_id(_isolated_stores):
    db = _isolated_stores["sess_db"]
    exp = time.time() + 3600
    session_store.persist(
        "sid-g",
        {
            "username": "guest",
            "auth_method": "guest_pass",
            "expires_at_epoch": exp,
            "guest_pass_id": 42,
        },
        db_path=db,
    )
    session_store._setup_done.clear()  # noqa: SLF001
    got = session_store.hydrate(db_path=db)
    assert got["sid-g"]["expires_at_epoch"] == pytest.approx(exp)
    assert got["sid-g"]["guest_pass_id"] == 42


def test_hydrate_drops_expired_and_unbounded_guest_rows(_isolated_stores):
    db = _isolated_stores["sess_db"]
    session_store.persist(
        "sid-expired",
        {
            "username": "guest",
            "auth_method": "guest_pass",
            "expires_at_epoch": time.time() - 5,
            "guest_pass_id": 1,
        },
        db_path=db,
    )
    session_store.persist(
        "sid-legacy", {"username": "guest", "auth_method": "guest_pass"}, db_path=db
    )
    session_store.persist("sid-owner", {"username": "admin", "auth_method": "password"}, db_path=db)
    session_store._setup_done.clear()  # noqa: SLF001
    got = session_store.hydrate(db_path=db)
    assert set(got) == {"sid-owner"}
    # ...and the refused rows are deleted, not merely skipped.
    session_store._setup_done.clear()  # noqa: SLF001
    assert session_store.count_active(db_path=db) == 1


def test_legacy_table_is_migrated_in_place(_isolated_stores):
    """A production store created before the new columns keeps its rows."""
    import sqlite3

    db = _isolated_stores["sess_db"]
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE auth_sessions (session_id TEXT PRIMARY KEY, username TEXT NOT NULL, "
        "sleeper_user_id TEXT NOT NULL DEFAULT '', display_name TEXT NOT NULL DEFAULT '', "
        "avatar TEXT NOT NULL DEFAULT '', auth_method TEXT NOT NULL DEFAULT 'password', "
        "allowlist_version TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL, "
        "last_seen_at REAL NOT NULL)"
    )
    now = time.time()
    conn.execute(
        "INSERT INTO auth_sessions VALUES ('sid-owner','admin','','','','password','',?,?)",
        (now, now),
    )
    conn.execute(
        "INSERT INTO auth_sessions VALUES ('sid-guest','guest','','','','guest_pass','',?,?)",
        (now, now),
    )
    conn.commit()
    conn.close()
    got = session_store.hydrate(db_path=db)
    assert set(got) == {"sid-owner"}, "a legacy guest row is unbounded and must not rehydrate"


def test_revoke_deletes_only_that_pass_persisted_sessions(_isolated_stores):
    db = _isolated_stores["sess_db"]
    exp = time.time() + 3600
    p1, _ = guest_passes.create(duration_hours=2.0)
    p2, _ = guest_passes.create(duration_hours=2.0)
    for sid, pid in (("a", p1.id), ("b", p1.id), ("c", p2.id)):
        session_store.persist(
            sid,
            {
                "username": "guest",
                "auth_method": "guest_pass",
                "expires_at_epoch": exp,
                "guest_pass_id": pid,
            },
            db_path=db,
        )
    guest_passes.revoke(p1.id, session_db_path=db)
    session_store._setup_done.clear()  # noqa: SLF001
    assert set(session_store.hydrate(db_path=db)) == {"c"}


@pytest.mark.parametrize("bad", [None, 0, -1, "3", True, 3.0])
def test_session_authority_fails_closed_on_bad_ids(bad):
    assert guest_passes.session_authority(bad) is False


def test_session_authority_tracks_the_pass():
    p, _ = guest_passes.create(duration_hours=2.0)
    assert guest_passes.session_authority(p.id) is True
    guest_passes.revoke(p.id)
    assert guest_passes.session_authority(p.id) is False
    assert guest_passes.session_authority(p.id + 999) is False


# ── What must NOT end a guest session ───────────────────────────────────


def _persisted_guest_rows(db) -> int:
    conn = sqlite3.connect(db)
    try:
        return int(
            conn.execute(
                "SELECT COUNT(*) FROM auth_sessions WHERE auth_method = 'guest_pass'"
            ).fetchone()[0]
        )
    finally:
        conn.close()


def _cookie(client: TestClient) -> str:
    value = client.cookies.get(server.JASON_AUTH_COOKIE_NAME)
    assert value, "precondition: login set the session cookie"
    return value


def _restart_process_memory() -> None:
    """What a backend restart does to sessions: the in-memory cache is gone
    and startup rebuilds it from disk with the production allowlist."""
    server.auth_sessions.clear()
    session_store._setup_done.clear()  # noqa: SLF001
    server.auth_sessions.update(
        session_store.hydrate(allowlist=server.PRIVATE_APP_ALLOWED_USERNAMES)
    )


def test_hydrate_keeps_a_bounded_guest_row_under_a_non_empty_allowlist(_isolated_stores):
    db = _isolated_stores["sess_db"]
    exp = time.time() + 3600
    session_store.persist(
        "sid-guest",
        {
            "username": "guest",
            "auth_method": "guest_pass",
            "expires_at_epoch": exp,
            "guest_pass_id": 7,
        },
        db_path=db,
    )
    session_store.persist("sid-owner", {"username": "admin", "auth_method": "password"}, db_path=db)
    session_store.persist(
        "sid-gone", {"username": "removed", "auth_method": "password"}, db_path=db
    )
    session_store._setup_done.clear()  # noqa: SLF001
    got = session_store.hydrate(allowlist=["admin"], db_path=db)
    # The allowlist still signs out a non-guest user who left it ...
    assert set(got) == {"sid-guest", "sid-owner"}
    # ... and the guest row keeps the identity its authority check needs.
    assert got["sid-guest"]["guest_pass_id"] == 7
    assert got["sid-guest"]["expires_at_epoch"] == pytest.approx(exp)


@pytest.mark.parametrize("bad_pass_id", [0, -3])
def test_hydrate_still_drops_a_guest_row_without_a_usable_pass_id(_isolated_stores, bad_pass_id):
    db = _isolated_stores["sess_db"]
    session_store.persist(
        "sid-guest",
        {"username": "guest", "auth_method": "guest_pass", "expires_at_epoch": time.time() + 3600},
        db_path=db,
    )
    conn = sqlite3.connect(db)
    conn.execute(
        "UPDATE auth_sessions SET guest_pass_id = ? WHERE session_id = 'sid-guest'", (bad_pass_id,)
    )
    conn.commit()
    conn.close()
    session_store._setup_done.clear()  # noqa: SLF001
    assert session_store.hydrate(allowlist=["admin"], db_path=db) == {}
    assert _persisted_guest_rows(db) == 0


def test_a_live_guest_session_survives_a_restart_and_revocation_still_ends_it(_isolated_stores):
    pass_row, token = guest_passes.create(duration_hours=2.0)
    with TestClient(server.app, base_url="https://testserver") as c:
        _login(c, token)
        assert c.get(PRIVATE_ROUTE).status_code == 200
        cookie = _cookie(c)
    _restart_process_memory()
    assert _guest_session_ids(), "the restart must rehydrate the live guest session"
    with TestClient(server.app, base_url="https://testserver") as after:
        after.cookies.set(server.JASON_AUTH_COOKIE_NAME, cookie)
        assert after.get(PRIVATE_ROUTE).status_code == 200
        assert after.get("/api/auth/status").json().get("authenticated") is True
        # The rehydrated session answers to its pass exactly as before.
        guest_passes.revoke(pass_row.id)
        assert after.get(PRIVATE_ROUTE).status_code == 401
    assert _guest_session_ids() == []
    assert _persisted_guest_rows(_isolated_stores["sess_db"]) == 0


def test_a_stale_row_of_a_revoked_pass_cannot_authenticate_after_a_restart(
    monkeypatch, _isolated_stores
):
    """Revoke's row deletion "lost" (it is belt-and-braces): the row comes
    back on restart, and the per-request pass check still ends it."""
    pass_row, token = guest_passes.create(duration_hours=2.0)
    monkeypatch.setattr(session_store, "evict_guest_pass", lambda *a, **k: 0)
    with TestClient(server.app, base_url="https://testserver") as c:
        _login(c, token)
        cookie = _cookie(c)
    guest_passes.revoke(pass_row.id)
    _restart_process_memory()
    assert _guest_session_ids(), "precondition: the stale row rehydrated"
    with TestClient(server.app, base_url="https://testserver") as after:
        after.cookies.set(server.JASON_AUTH_COOKIE_NAME, cookie)
        assert after.get(PRIVATE_ROUTE).status_code == 401
    assert _guest_session_ids() == []
    assert _persisted_guest_rows(_isolated_stores["sess_db"]) == 0


def _locked(*_a, **_k):
    raise sqlite3.OperationalError("database is locked")


@pytest.mark.parametrize("failure", ["read_raises", "setup_fails"])
def test_unreadable_pass_store_refuses_the_request_but_keeps_the_session(
    monkeypatch, _isolated_stores, failure
):
    _p, token = guest_passes.create(duration_hours=2.0)
    db = _isolated_stores["sess_db"]
    with TestClient(server.app, base_url="https://testserver") as c:
        _login(c, token)
        assert c.get(PRIVATE_ROUTE).status_code == 200
        with monkeypatch.context() as m:
            if failure == "read_raises":
                m.setattr(guest_passes, "get", _locked)
            else:
                m.setattr(guest_passes, "_ensure_setup", lambda _path: False)
            # Fail closed: no access while the authority cannot be read ...
            assert c.get(PRIVATE_ROUTE).status_code == 401
            assert c.get("/api/auth/status").json().get("authenticated") is False
            # ... but the session is neither evicted nor deleted.
            assert len(_guest_session_ids()) == 1
            assert _persisted_guest_rows(db) == 1
        # The store answers again: the same session works on its next request.
        assert c.get(PRIVATE_ROUTE).status_code == 200


def test_an_expired_pass_still_ends_the_session_for_good(_isolated_stores):
    """The pass expired early (row edited) while the session's own expiry is
    still ahead: inactive, not unreadable — evicted from memory and disk."""
    pass_row, token = guest_passes.create(duration_hours=2.0)
    with TestClient(server.app, base_url="https://testserver") as c:
        _login(c, token)
        conn = sqlite3.connect(_isolated_stores["pass_db"])
        conn.execute(
            "UPDATE guest_passes SET expires_at_epoch = ? WHERE id = ?",
            (time.time() - 1, pass_row.id),
        )
        conn.commit()
        conn.close()
        assert c.get(PRIVATE_ROUTE).status_code == 401
    assert _guest_session_ids() == []
    assert _persisted_guest_rows(_isolated_stores["sess_db"]) == 0


def test_an_unknown_pass_id_still_ends_the_session_for_good(_isolated_stores):
    _p, token = guest_passes.create(duration_hours=2.0)
    with TestClient(server.app, base_url="https://testserver") as c:
        _login(c, token)
        (sid,) = _guest_session_ids()
        server.auth_sessions[sid]["guest_pass_id"] = 987654
        assert c.get(PRIVATE_ROUTE).status_code == 401
    assert _guest_session_ids() == []
    assert _persisted_guest_rows(_isolated_stores["sess_db"]) == 0


def test_the_sessions_own_expiry_still_ends_it_for_good(_isolated_stores):
    _p, token = guest_passes.create(duration_hours=2.0)
    with TestClient(server.app, base_url="https://testserver") as c:
        _login(c, token)
        (sid,) = _guest_session_ids()
        server.auth_sessions[sid]["expires_at_epoch"] = time.time() - 1
        assert c.get(PRIVATE_ROUTE).status_code == 401
    assert _guest_session_ids() == []
    assert _persisted_guest_rows(_isolated_stores["sess_db"]) == 0


def test_session_authority_state_separates_unreadable_from_inactive(monkeypatch):
    p, _ = guest_passes.create(duration_hours=2.0)
    assert guest_passes.session_authority_state(p.id) == guest_passes.AUTHORITY_ACTIVE
    assert guest_passes.session_authority_state(p.id + 999) == guest_passes.AUTHORITY_INACTIVE
    for bad in (None, 0, -1, "3", True, 3.0):
        assert guest_passes.session_authority_state(bad) == guest_passes.AUTHORITY_INACTIVE
    with monkeypatch.context() as m:
        m.setattr(guest_passes, "get", _locked)
        assert guest_passes.session_authority_state(p.id) == guest_passes.AUTHORITY_UNKNOWN
        # The boolean form stays fail-closed: unknown is not authority.
        assert guest_passes.session_authority(p.id) is False
    with monkeypatch.context() as m:
        m.setattr(guest_passes, "_ensure_setup", lambda _path: False)
        assert guest_passes.session_authority_state(p.id) == guest_passes.AUTHORITY_UNKNOWN
    guest_passes.revoke(p.id)
    assert guest_passes.session_authority_state(p.id) == guest_passes.AUTHORITY_INACTIVE


def test_ending_a_session_logs_the_reason_and_pass_never_the_session_id(caplog):
    _p, token = guest_passes.create(duration_hours=2.0)
    with TestClient(server.app, base_url="https://testserver") as c:
        _login(c, token)
        (sid,) = _guest_session_ids()
        cookie = _cookie(c)
        guest_passes.revoke(_p.id)
        with caplog.at_level("INFO"):
            assert c.get(PRIVATE_ROUTE).status_code == 401
    ended = [r.getMessage() for r in caplog.records if "auth session ended" in r.getMessage()]
    assert ended == [
        f"auth session ended: reason=guest_pass_not_authoritative auth_method=guest_pass guest_pass_id={_p.id}"
    ]
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert sid not in text and cookie not in text
