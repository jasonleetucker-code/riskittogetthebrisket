"""Security incident 2026-10-08 — the production acceptance instruments.

Pins the two new pieces of ``v1-authenticated-verification.yml``:

* the post-revocation probe (``verify_v1_authenticated.py security-probe``):
  the SAME session, accepted before the on-box revoke, must be rejected
  after it — and the probe never lets the cookie reach stdout, stderr or
  its output file;
* the on-box census (``session_store.guest_session_census``): count-only,
  read-only, and every MUST-be-0 count must be OBSERVED as 0 (an absent or
  unreadable store is unknown, never a pass).

No network, no box: temp SQLite stores and a urlopen test double.
"""

from __future__ import annotations

import io
import json
import sqlite3
import time
import urllib.error
from pathlib import Path

import pytest
import yaml

import scripts.verify_v1_authenticated as auth
from src.api import guest_passes, session_store

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "v1-authenticated-verification.yml"

COOKIE = "SENTINEL-cookie-value-9f3b2c71d0"


@pytest.fixture(autouse=True)
def _reset_checks():
    auth.CHECKS.clear()
    yield
    auth.CHECKS.clear()


# ── temp stores ──


@pytest.fixture
def stores(tmp_path):
    sess = tmp_path / "session_store.sqlite"
    passes = tmp_path / "guest_passes.sqlite"
    session_store._setup(sess)
    guest_passes._setup(passes)
    return sess, passes


def _insert_session(path: Path, sid: str, *, auth_method: str, expires=None, pass_id=None):
    now = time.time()
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(
            "INSERT INTO auth_sessions (session_id, username, auth_method, created_at, "
            "last_seen_at, expires_at_epoch, guest_pass_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                sid,
                "guest" if auth_method == "guest_pass" else "owner",
                auth_method,
                now,
                now,
                expires,
                pass_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _mint(passes: Path, hours: float = 2.0) -> int:
    gp, _token = guest_passes.create(duration_hours=hours, db_path=passes)
    return gp.id


def _set_pass(passes: Path, pass_id: int, *, revoked=None, expires=None) -> None:
    conn = sqlite3.connect(str(passes))
    try:
        if revoked is not None:
            conn.execute(
                "UPDATE guest_passes SET revoked_at_epoch = ? WHERE id = ?", (revoked, pass_id)
            )
        if expires is not None:
            conn.execute(
                "UPDATE guest_passes SET expires_at_epoch = ? WHERE id = ?", (expires, pass_id)
            )
        conn.commit()
    finally:
        conn.close()


def _census(stores):
    sess, passes = stores
    return session_store.guest_session_census(db_path=sess, guest_pass_db_path=passes)


def _statuses(checks):
    return {c.check_id: c.status for c in checks}


# ── census ──


def test_clean_store_passes(stores):
    sess, passes = stores
    pid = _mint(passes)
    _insert_session(sess, "s-owner", auth_method="password")
    _insert_session(
        sess, "s-guest", auth_method="guest_pass", expires=time.time() + 3600, pass_id=pid
    )
    census = _census(stores)
    assert census["schemaHasGuestColumns"] is True
    assert census["totalSessions"] == 2
    assert census["guestSessions"] == 1
    assert census["guestSessionsMissingPassIdentity"] == 0
    assert census["guestSessionsPassRevoked"] == 0
    assert census["guestSessionsLiveWithInactivePass"] == 0
    assert set(_statuses(auth.check_session_census(census)).values()) == {"pass"}


@pytest.mark.parametrize("expires,pass_id", [(None, None), (None, 7), (time.time() + 60, None)])
def test_legacy_guest_row_without_pass_identity_fails(stores, expires, pass_id):
    sess, _ = stores
    _insert_session(sess, "s-legacy", auth_method="guest_pass", expires=expires, pass_id=pass_id)
    census = _census(stores)
    assert census["guestSessionsMissingPassIdentity"] == 1
    assert _statuses(auth.check_session_census(census))["SEC-LEGACY"] == "fail"


def test_pre_migration_schema_fails_and_is_not_migrated_by_the_census(tmp_path):
    sess = tmp_path / "legacy.sqlite"
    conn = sqlite3.connect(str(sess))
    conn.execute(
        "CREATE TABLE auth_sessions (session_id TEXT PRIMARY KEY, username TEXT NOT NULL, "
        "sleeper_user_id TEXT NOT NULL DEFAULT '', display_name TEXT NOT NULL DEFAULT '', "
        "avatar TEXT NOT NULL DEFAULT '', auth_method TEXT NOT NULL DEFAULT 'password', "
        "allowlist_version TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL, "
        "last_seen_at REAL NOT NULL)"
    )
    conn.execute(
        "INSERT INTO auth_sessions (session_id, username, auth_method, created_at, last_seen_at) "
        "VALUES ('s-old', 'guest', 'guest_pass', 1, 1)"
    )
    conn.commit()
    conn.close()

    census = session_store.guest_session_census(
        db_path=sess, guest_pass_db_path=tmp_path / "absent.sqlite"
    )
    assert census["schemaHasGuestColumns"] is False
    assert census["guestSessionsMissingPassIdentity"] == 1
    statuses = _statuses(auth.check_session_census(census))
    assert statuses["SEC-SCHEMA"] == "fail" and statuses["SEC-LEGACY"] == "fail"

    # Read-only: a census that migrated would make the schema check pass by
    # construction and prove nothing.
    conn = sqlite3.connect(str(sess))
    cols = {r[1] for r in conn.execute("PRAGMA table_info(auth_sessions)")}
    conn.close()
    assert "guest_pass_id" not in cols and "expires_at_epoch" not in cols


def test_revoked_pass_session_present_fails(stores):
    sess, passes = stores
    pid = _mint(passes)
    _insert_session(sess, "s-g", auth_method="guest_pass", expires=time.time() + 3600, pass_id=pid)
    _set_pass(passes, pid, revoked=time.time())
    census = _census(stores)
    assert census["guestSessionsPassRevoked"] == 1
    assert _statuses(auth.check_session_census(census))["SEC-INACTIVE-PASS"] == "fail"


def test_revoke_cleans_the_row_so_the_census_passes(stores):
    """The canonical revoke (PR #1718) is what makes the MUST-0 hold."""
    sess, passes = stores
    pid = _mint(passes)
    _insert_session(sess, "s-g", auth_method="guest_pass", expires=time.time() + 3600, pass_id=pid)
    assert guest_passes.revoke(pid, db_path=passes, session_db_path=sess) is True
    census = _census(stores)
    assert census["guestSessions"] == 0
    assert census["guestSessionsPassRevoked"] == 0


def test_live_row_with_expired_or_purged_pass_fails(stores):
    sess, passes = stores
    pid = _mint(passes)
    _set_pass(passes, pid, expires=time.time() - 10)
    _insert_session(sess, "s-a", auth_method="guest_pass", expires=time.time() + 600, pass_id=pid)
    _insert_session(sess, "s-b", auth_method="guest_pass", expires=time.time() + 600, pass_id=999)
    census = _census(stores)
    assert census["guestSessionsLiveWithInactivePass"] == 2
    assert _statuses(auth.check_session_census(census))["SEC-INACTIVE-PASS"] == "fail"


def test_self_expired_row_is_reported_not_failed(stores):
    """A row past its OWN expiry is refused by hydrate and per-request; it is
    reported as awaiting cleanup rather than failing the run."""
    sess, passes = stores
    pid = _mint(passes)
    _set_pass(passes, pid, expires=time.time() - 10)
    _insert_session(sess, "s-x", auth_method="guest_pass", expires=time.time() - 10, pass_id=pid)
    census = _census(stores)
    assert census["guestSessionsExpiredAwaitingCleanup"] == 1
    assert census["guestSessionsLiveWithInactivePass"] == 0
    assert set(_statuses(auth.check_session_census(census)).values()) == {"pass"}


def test_absent_store_is_unknown_and_fails(tmp_path):
    census = session_store.guest_session_census(
        db_path=tmp_path / "nope.sqlite", guest_pass_db_path=tmp_path / "nope2.sqlite"
    )
    assert census["storePresent"] is False
    assert census["guestSessionsMissingPassIdentity"] is None
    assert not (tmp_path / "nope.sqlite").exists()  # never created
    assert set(_statuses(auth.check_session_census(census)).values()) == {"fail"}


def test_unreadable_pass_store_is_unknown_not_zero(stores, tmp_path):
    sess, _ = stores
    _insert_session(sess, "s-g", auth_method="guest_pass", expires=time.time() + 600, pass_id=3)
    census = session_store.guest_session_census(
        db_path=sess, guest_pass_db_path=tmp_path / "missing_passes.sqlite"
    )
    assert census["passStoreReadable"] is False
    assert census["guestSessionsPassRevoked"] is None
    assert _statuses(auth.check_session_census(census))["SEC-INACTIVE-PASS"] == "fail"


def test_census_carries_no_identifiers(stores):
    sess, passes = stores
    pid = _mint(passes)
    _insert_session(
        sess, "SID-zz-1234", auth_method="guest_pass", expires=time.time() + 60, pass_id=pid
    )
    census = _census(stores)
    assert all(v is None or isinstance(v, (bool, int)) for v in census.values())
    blob = json.dumps(census)
    assert "SID-zz-1234" not in blob
    assert set(census) == set(auth._CENSUS_KEYS)  # fixed keys; values are counts/booleans


# ── post-revocation probe ──

_ACCEPTED = {
    "authStatusHttp": 200,
    "authenticated": True,
    "privateRouteHttp": 200,
    "probeError": False,
}
_REJECTED = {
    "authStatusHttp": 200,
    "authenticated": False,
    "privateRouteHttp": 401,
    "probeError": False,
}


def test_revocation_pass_requires_control_then_rejection():
    assert set(_statuses(auth.check_revocation(True, _ACCEPTED, _REJECTED)).values()) == {"pass"}


@pytest.mark.parametrize(
    "revoke_ok,pre,post,failing",
    [
        (True, _ACCEPTED, _ACCEPTED, "SEC-POST-REVOKE"),  # still authenticates
        (True, _ACCEPTED, {**_REJECTED, "privateRouteHttp": 200}, "SEC-POST-REVOKE"),
        (True, _REJECTED, _REJECTED, "SEC-POST-REVOKE"),  # control never accepted
        (True, None, _REJECTED, "SEC-POST-REVOKE"),
        (True, _ACCEPTED, None, "SEC-POST-REVOKE"),
        (False, _ACCEPTED, _REJECTED, "SEC-REVOKE"),  # revoke failed → run fails
        (None, _ACCEPTED, _REJECTED, "SEC-REVOKE"),
    ],
)
def test_revocation_failures(revoke_ok, pre, post, failing):
    assert _statuses(auth.check_revocation(revoke_ok, pre, post))[failing] == "fail"


class _Resp:
    def __init__(self, status: int, body: dict):
        self.status = status
        self._raw = json.dumps(body).encode()

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _urlopen_double(*, revoked: bool, seen: list):
    """Adversarial double: every body echoes the cookie it was sent."""

    def fake(req, timeout=None):
        cookie = req.get_header("Cookie")
        seen.append(cookie)
        path = req.full_url.split("://", 1)[1].split("/", 1)[1]
        if path == "api/auth/status":
            body = {"authenticated": not revoked, "echo": cookie}
            return _Resp(200, body)
        if revoked:
            raise urllib.error.HTTPError(
                req.full_url,
                401,
                "Unauthorized",
                {},
                io.BytesIO(json.dumps({"error": "auth_required", "echo": cookie}).encode()),
            )
        return _Resp(200, {"username": "guest", "echo": cookie})

    return fake


@pytest.mark.parametrize("revoked", [False, True])
def test_probe_never_prints_or_writes_the_cookie(tmp_path, monkeypatch, capsys, revoked):
    cookie_file = tmp_path / "session_cookie"
    cookie_file.write_text(COOKIE, encoding="utf-8")
    out = tmp_path / "probe.json"
    seen: list = []
    monkeypatch.setattr(auth.urllib.request, "urlopen", _urlopen_double(revoked=revoked, seen=seen))

    rc = auth.main(
        [
            "security-probe",
            "--origin",
            "https://example.test",
            "--cookie-file",
            str(cookie_file),
            "--out",
            str(out),
        ]
    )

    assert rc == 0
    assert seen and all(c == f"jason_session={COOKIE}" for c in seen)  # it really used it
    captured = capsys.readouterr()
    written = out.read_text(encoding="utf-8")
    for text in (captured.out, captured.err, written):
        assert COOKIE not in text
    result = json.loads(written)
    assert result == (_REJECTED if revoked else _ACCEPTED)


def test_probe_error_never_leaks_the_exception_text(tmp_path, monkeypatch, capsys):
    cookie_file = tmp_path / "session_cookie"
    cookie_file.write_text(COOKIE, encoding="utf-8")
    out = tmp_path / "probe.json"

    def boom(req, timeout=None):
        raise urllib.error.URLError(f"refused while sending {req.get_header('Cookie')}")

    monkeypatch.setattr(auth.urllib.request, "urlopen", boom)
    auth.main(
        [
            "security-probe",
            "--origin",
            "https://example.test",
            "--cookie-file",
            str(cookie_file),
            "--out",
            str(out),
        ]
    )
    captured = capsys.readouterr()
    written = out.read_text(encoding="utf-8")
    for text in (captured.out, captured.err, written):
        assert COOKIE not in text
    assert json.loads(written)["probeError"] is True


# ── summary (the public artifact) ──


def _write(tmp_path, name, obj):
    p = tmp_path / name
    p.write_text(json.dumps(obj), encoding="utf-8")
    return str(p)


def _clean_census():
    return {
        "storePresent": True,
        "schemaHasGuestColumns": True,
        "totalSessions": 4,
        "guestSessions": 0,
        "guestSessionsMissingPassIdentity": 0,
        "guestSessionsPassRevoked": 0,
        "guestSessionsLiveWithInactivePass": 0,
        "guestSessionsExpiredAwaitingCleanup": 0,
        "passStoreReadable": None,
    }


def test_summary_passes_and_writes_job_summary(tmp_path, capsys):
    out = tmp_path / "security-acceptance.json"
    step = tmp_path / "step_summary.md"
    rc = auth.main(
        [
            "security-summary",
            "--pre",
            _write(tmp_path, "pre.json", _ACCEPTED),
            "--post",
            _write(tmp_path, "post.json", _REJECTED),
            "--census",
            _write(tmp_path, "census.json", _clean_census()),
            "--revoke-ok",
            "true",
            "--out",
            str(out),
            "--step-summary",
            str(step),
        ]
    )
    assert rc == 0
    summary = json.loads(out.read_text(encoding="utf-8"))
    assert summary["verdict"] == "pass"
    assert "PASS" in step.read_text(encoding="utf-8")


def test_summary_allowlists_and_fails_on_missing_evidence(tmp_path, capsys):
    hostile = {**_clean_census(), "sessionId": COOKIE, "guestSessionsPassRevoked": COOKIE}
    out = tmp_path / "security-acceptance.json"
    rc = auth.main(
        [
            "security-summary",
            "--pre",
            _write(tmp_path, "pre.json", {**_ACCEPTED, "cookie": COOKIE}),
            "--post",
            str(tmp_path / "never-written.json"),
            "--census",
            _write(tmp_path, "census.json", hostile),
            "--revoke-ok",
            "true",
            "--out",
            str(out),
        ]
    )
    assert rc == 2
    text = out.read_text(encoding="utf-8")
    assert COOKIE not in text and COOKIE not in capsys.readouterr().out
    summary = json.loads(text)
    assert summary["verdict"] == "fail"
    assert "sessionId" not in summary["sessionStoreCensus"]
    assert summary["sessionStoreCensus"]["guestSessionsPassRevoked"] is None
    assert summary["postRevocationProbe"] is None


# ── workflow wiring ──


def _steps():
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["v1-authenticated"]["steps"]


def test_workflow_orders_control_revoke_probe_census_summary():
    names = [s.get("name") for s in _steps()]
    order = [
        "Log in through the real auth path",
        "Security probe before revocation (control)",
        "Revoke the pass (always)",
        "Security probe after revocation (same session)",
        "On-box guest-session census (count-only, read-only)",
        "Security acceptance summary (incident 2026-10-08)",
        "Fail the job on API/lane4/browser verdicts",
        "Upload the reports",
    ]
    idx = [names.index(n) for n in order]
    assert idx == sorted(idx)


def test_workflow_keeps_the_cookie_until_the_post_probe_then_deletes_it():
    steps = {s.get("name"): s for s in _steps()}
    revoke = steps["Revoke the pass (always)"]["run"]
    post = steps["Security probe after revocation (same session)"]
    census = steps["On-box guest-session census (count-only, read-only)"]
    summary = steps["Security acceptance summary (incident 2026-10-08)"]
    trap = [ln for ln in revoke.splitlines() if ln.strip().startswith("trap ")]
    assert trap and "session_cookie" not in trap[0]
    assert "revoke_ok=false" in revoke and "exit 1" in revoke
    assert "session_cookie" in post["run"].split("python3", 1)[0]  # trap deletes it
    assert "security-probe" in post["run"]
    assert "guest_session_census()" in census["run"]
    for step in (post, census, summary):
        assert step["if"] == "${{ always() && steps.mint.outputs.pass_id != '' }}"
    upload = steps["Upload the reports"]["with"]["path"]
    assert "security-acceptance.json" in upload
    assert "RUNNER_TEMP" not in upload and "census" not in upload
