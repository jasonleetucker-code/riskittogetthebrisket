"""Signals owner-session store, renewal and failure classes.

Every token here is SYNTHETIC: an unsigned ``header.payload.fake-signature``
string built by :func:`make_jwt`, or a literal ``synthetic-refresh-*`` value.
The refresh endpoint is a local stub HTTP server; no test touches the network
or Signals.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from src.sources import signals_auth as SA
from src.sources.acquisition_state import AUTH_REQUIRED, HEALTHY, UNAVAILABLE

REPO = Path(__file__).resolve().parents[2]
ISS = f"https://cognito-idp.{SA.EXPECTED_REGION}.amazonaws.com/{SA.EXPECTED_USER_POOL_ID}"


def _b64(obj: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")


def make_jwt(*, exp: float, token_use: str = "access", iss: str = ISS, tag: str = "") -> str:
    claims = {"exp": int(exp), "iat": int(exp) - 3600, "iss": iss, "token_use": token_use}
    if token_use == "access":
        claims["client_id"] = SA.EXPECTED_CLIENT_ID
    else:
        claims["aud"] = SA.EXPECTED_CLIENT_ID
    claims["jti"] = f"synthetic-{tag}-{time.monotonic_ns()}"
    return f"{_b64({'alg': 'none', 'typ': 'JWT'})}.{_b64(claims)}.fake-signature"


def capture(
    *, access_exp: float, refresh: str = "synthetic-refresh-0", device: bool = False
) -> dict:
    cap = {
        "clientId": SA.EXPECTED_CLIENT_ID,
        "username": "synthetic-user-uuid",
        "accessToken": make_jwt(exp=access_exp, tag="a0"),
        "idToken": make_jwt(exp=access_exp, token_use="id", tag="i0"),
        "refreshToken": refresh,
    }
    if device:
        cap.update(
            {
                "deviceKey": "us-east-2_synthetic-device",
                "deviceGroupKey": "synthetic-group",
                "randomPasswordKey": "synthetic-rpk",
            }
        )
    return cap


# ── stub Cognito ────────────────────────────────────────────────────────────


class StubCognito:
    """GetTokensFromRefreshToken / RevokeToken with optional strict rotation."""

    def __init__(self, *, valid: str = "synthetic-refresh-0", rotate: bool = True) -> None:
        self.valid = valid
        self.rotate = rotate
        self.calls: list[dict] = []
        self.failures: list[tuple[int, dict, dict]] = []  # queued (code, body, headers)
        self.lock = threading.Lock()
        self.generation = 0
        self.revoked = False
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):  # silence
                pass

            def do_POST(self):  # noqa: N802
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                target = self.headers.get("X-Amz-Target", "").rsplit(".", 1)[-1]
                code, payload, headers = stub.handle(target, body)
                raw = json.dumps(payload).encode()
                self.send_response(code)
                for k, v in headers.items():
                    self.send_header(k, v)
                self.send_header("Content-Type", "application/x-amz-json-1.1")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def handle(self, target: str, body: dict) -> tuple[int, dict, dict]:
        with self.lock:
            self.calls.append({"target": target, **body})
            if self.failures:
                return self.failures.pop(0)
            if target == "RevokeToken":
                self.revoked = True
                return 200, {}, {}
            if body.get("RefreshToken") != self.valid or self.revoked:
                return (
                    400,
                    {"__type": "NotAuthorizedException", "message": "Invalid Refresh Token"},
                    {},
                )
            self.generation += 1
            result = {
                "AccessToken": make_jwt(exp=time.time() + 3600, tag=f"a{self.generation}"),
                "IdToken": make_jwt(
                    exp=time.time() + 3600, token_use="id", tag=f"i{self.generation}"
                ),
                "ExpiresIn": 3600,
            }
            if self.rotate:
                self.valid = f"synthetic-refresh-{self.generation}"
                result["RefreshToken"] = self.valid
            return 200, {"AuthenticationResult": result}, {}

    def refresh_calls(self) -> int:
        return sum(1 for c in self.calls if c["target"] == "GetTokensFromRefreshToken")

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def stub():
    s = StubCognito()
    yield s
    s.close()


@pytest.fixture
def store(tmp_path) -> SA.SignalsStore:
    return SA.SignalsStore(SA.validate_store_dir(tmp_path / "signals-auth"))


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(SA, "_backoff_sleep", lambda s: None)


# ── store location ──────────────────────────────────────────────────────────


def test_store_refuses_the_repository(tmp_path):
    with pytest.raises(SA.StorePathError):
        SA.validate_store_dir(REPO / "data" / "signals-auth")
    with pytest.raises(SA.StorePathError):
        SA.validate_store_dir(REPO / "frontend" / "public" / "signals")


def test_store_refuses_any_git_checkout(tmp_path):
    checkout = tmp_path / "other-clone"
    (checkout / ".git").mkdir(parents=True)
    with pytest.raises(SA.StorePathError):
        SA.validate_store_dir(checkout / "nested" / "store")


def test_store_refuses_web_roots(tmp_path, monkeypatch):
    web = tmp_path / "www"
    monkeypatch.setattr(SA, "_WEB_ROOTS", (web,))
    with pytest.raises(SA.StorePathError):
        SA.validate_store_dir(web / "html" / "signals")


def test_default_store_is_outside_the_checkout(monkeypatch):
    monkeypatch.delenv(SA.AUTH_DIR_ENV, raising=False)
    resolved = SA.resolve_store_dir()
    assert not str(resolved).startswith(str(REPO.resolve()))


def test_env_override_is_validated(tmp_path, monkeypatch):
    monkeypatch.setenv(SA.AUTH_DIR_ENV, str(REPO / "signals"))
    with pytest.raises(SA.StorePathError):
        SA.resolve_store_dir()
    monkeypatch.setenv(SA.AUTH_DIR_ENV, str(tmp_path / "ok"))
    assert SA.resolve_store_dir() == (tmp_path / "ok").resolve()


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits")
def test_files_are_0600_and_dir_0700(store):
    SA.import_session(store, capture(access_exp=time.time() + 3600))
    assert (store.root.stat().st_mode & 0o777) == 0o700
    assert (store.session_path.stat().st_mode & 0o777) == 0o600
    assert (store.status_path.stat().st_mode & 0o777) == 0o600


def test_session_survives_a_process_restart(store, stub):
    SA.import_session(store, capture(access_exp=time.time() - 10))
    renewed = SA.renew(store, endpoint=stub.url)
    reopened = SA.SignalsStore(store.root)  # a new process opens the same dir
    assert reopened.read_session() == renewed
    assert SA.status(reopened)["state"] == SA.STATE_HEALTHY


def test_deploy_cleans_nothing_outside_app_dir():
    """deploy.sh resets the checkout; it must never reach the session store."""
    text = (REPO / "deploy" / "deploy.sh").read_text(encoding="utf-8")
    assert "git clean" not in text
    assert "signals-auth" not in text
    import re

    targets = set(re.findall(r'rm -rf "\$\{([a-z_]+)\}"', text))
    assert targets <= {"staging_dir", "old_dir"}, targets
    assert 'local staging_dir="${frontend_dir}/' in text
    assert 'local frontend_dir="${APP_DIR}/frontend"' in text


# ── capture validation ──────────────────────────────────────────────────────


def test_capture_requires_a_refresh_token(store):
    cap = capture(access_exp=time.time() + 3600)
    cap.pop("refreshToken")
    with pytest.raises(SA.SignalsAuthError) as exc:
        SA.import_session(store, cap)
    assert exc.value.reason == "capture_missing_refresh_token"
    assert store.read_session() is None


def test_capture_rejects_a_foreign_issuer(store):
    cap = capture(access_exp=time.time() + 3600)
    cap["accessToken"] = make_jwt(
        exp=time.time() + 3600, iss="https://evil.example.com/us-east-2_x"
    )
    with pytest.raises(SA.SignalsAuthError) as exc:
        SA.import_session(store, cap)
    assert exc.value.reason == "unrecognized_token_issuer"


def test_capture_rejects_client_mismatch_and_id_token_as_access(store):
    cap = capture(access_exp=time.time() + 3600)
    cap["clientId"] = "someotherclient"
    with pytest.raises(SA.SignalsAuthError):
        SA.import_session(store, cap)
    cap = capture(access_exp=time.time() + 3600)
    cap["accessToken"] = cap["idToken"]
    with pytest.raises(SA.SignalsAuthError):
        SA.import_session(store, cap)


# ── redaction ───────────────────────────────────────────────────────────────


def _secrets(session: dict) -> list[str]:
    toks = session["tokens"]
    return [
        v for v in (toks.get("accessToken"), toks.get("idToken"), toks.get("refreshToken")) if v
    ] + [v for v in (session.get("device") or {}).values() if v]


def test_status_never_contains_a_token(store, stub):
    SA.import_session(store, capture(access_exp=time.time() - 10, device=True))
    SA.renew(store, endpoint=stub.url)
    session = store.read_session()
    blob = json.dumps(SA.status(store))
    for secret in _secrets(session):
        assert secret not in blob
    blob_status_file = store.status_path.read_text(encoding="utf-8")
    for secret in _secrets(session):
        assert secret not in blob_status_file


def test_status_not_connected(store):
    st = SA.status(store)
    assert st["state"] == SA.STATE_NOT_CONNECTED


# ── renewal ─────────────────────────────────────────────────────────────────


def test_renewal_with_rotation(store, stub):
    SA.import_session(store, capture(access_exp=time.time() - 10))
    s = SA.renew(store, endpoint=stub.url)
    assert s["tokens"]["refreshToken"] == stub.valid == "synthetic-refresh-1"
    assert s["refreshTokenRotations"] == 1
    st = SA.status(store)
    assert st["state"] == SA.STATE_HEALTHY
    assert st["refreshTokenRotationEvidence"] == "rotating"
    # the rotated token keeps working
    s2 = SA.renew(store, force=True, endpoint=stub.url)
    assert s2["tokens"]["refreshToken"] == "synthetic-refresh-2"


def test_renewal_without_rotation_keeps_refresh_token(store):
    stub = StubCognito(rotate=False)
    try:
        SA.import_session(store, capture(access_exp=time.time() - 10))
        s = SA.renew(store, endpoint=stub.url)
        assert s["tokens"]["refreshToken"] == "synthetic-refresh-0"
        assert SA.status(store)["refreshTokenRotationEvidence"] == "not rotating"
    finally:
        stub.close()


def test_not_due_means_no_network(store, stub):
    SA.import_session(store, capture(access_exp=time.time() + 3600))
    SA.renew(store, endpoint=stub.url)
    assert stub.refresh_calls() == 0
    assert SA.get_access_token(store, endpoint=stub.url)
    assert stub.refresh_calls() == 0


def test_renews_before_expiry_within_skew(store, stub):
    SA.import_session(store, capture(access_exp=time.time() + 60))
    SA.get_access_token(store, endpoint=stub.url, skew_seconds=300)
    assert stub.refresh_calls() == 1


def test_device_key_is_sent(store, stub):
    SA.import_session(store, capture(access_exp=time.time() - 10, device=True))
    SA.renew(store, endpoint=stub.url)
    assert stub.calls[-1]["DeviceKey"] == "us-east-2_synthetic-device"
    assert stub.calls[-1]["ClientId"] == SA.EXPECTED_CLIENT_ID


def test_revoked_refresh_token_stops_without_looping(store, stub):
    SA.import_session(
        store, capture(access_exp=time.time() - 10, refresh="synthetic-refresh-stale")
    )
    stub.failures.append(
        (400, {"__type": "NotAuthorizedException", "message": "Refresh Token has been revoked"}, {})
    )
    with pytest.raises(SA.SignalsAuthError) as exc:
        SA.renew(store, endpoint=stub.url)
    assert exc.value.failure_class == SA.RECONNECT_REQUIRED
    assert exc.value.reason == "refresh_token_revoked"
    assert stub.refresh_calls() == 1  # not retried
    st = SA.status(store)
    assert st["state"] == SA.RECONNECT_REQUIRED
    assert st["acquisitionState"] == AUTH_REQUIRED
    episode = st["episode"]
    assert episode and episode["noticeDeliveredAt"] is None
    # Subsequent calls short-circuit: no network, same episode.
    for _ in range(3):
        with pytest.raises(SA.SignalsAuthError):
            SA.get_access_token(store, endpoint=stub.url)
    assert stub.refresh_calls() == 1
    # A deliberate forced attempt that fails again does not open a new episode.
    with pytest.raises(SA.SignalsAuthError):
        SA.renew(store, force=True, endpoint=stub.url)
    assert SA.status(store)["episode"]["id"] == episode["id"]


def test_expired_refresh_token_is_reconnect_required(store, stub):
    SA.import_session(store, capture(access_exp=time.time() - 10))
    stub.failures.append(
        (400, {"__type": "NotAuthorizedException", "message": "Refresh Token has expired"}, {})
    )
    with pytest.raises(SA.SignalsAuthError) as exc:
        SA.renew(store, endpoint=stub.url)
    assert (exc.value.failure_class, exc.value.reason) == (
        SA.RECONNECT_REQUIRED,
        "refresh_token_expired",
    )


def test_transient_is_bounded_and_opens_no_episode(store, stub):
    SA.import_session(store, capture(access_exp=time.time() - 10))
    for _ in range(SA.TRANSIENT_ATTEMPTS):
        stub.failures.append((503, {}, {}))
    with pytest.raises(SA.SignalsAuthError) as exc:
        SA.renew(store, endpoint=stub.url)
    assert exc.value.failure_class == SA.TRANSIENT
    assert stub.refresh_calls() == SA.TRANSIENT_ATTEMPTS
    st = SA.status(store)
    assert st["state"] == SA.STATE_TRANSIENT_FAILURE
    assert st["acquisitionState"] == UNAVAILABLE
    assert st["episode"] is None
    # no lock-out: the next attempt goes through and recovers
    SA.renew(store, endpoint=stub.url)
    assert SA.status(store)["state"] == SA.STATE_HEALTHY


def test_throttle_then_success(store, stub):
    SA.import_session(store, capture(access_exp=time.time() - 10))
    stub.failures.append((400, {"__type": "TooManyRequestsException"}, {"Retry-After": "2"}))
    SA.renew(store, endpoint=stub.url)
    assert stub.refresh_calls() == 2
    assert SA.status(store)["state"] == SA.STATE_HEALTHY


def test_transient_during_early_renewal_keeps_the_valid_token(store, stub):
    SA.import_session(store, capture(access_exp=time.time() + 120))
    for _ in range(SA.TRANSIENT_ATTEMPTS):
        stub.failures.append((500, {}, {}))
    token = SA.get_access_token(store, endpoint=stub.url, skew_seconds=300)
    assert token == store.read_session()["tokens"]["accessToken"]


def test_forbidden_is_refresh_refused_not_reconnect(store, stub):
    SA.import_session(store, capture(access_exp=time.time() - 10))
    stub.failures.append((403, {"__type": "ForbiddenException"}, {}))
    with pytest.raises(SA.SignalsAuthError) as exc:
        SA.renew(store, endpoint=stub.url)
    assert exc.value.failure_class == SA.REFRESH_REFUSED


def test_reconnect_closes_the_episode(store, stub):
    SA.import_session(store, capture(access_exp=time.time() - 10, refresh="synthetic-refresh-dead"))
    with pytest.raises(SA.SignalsAuthError):
        SA.renew(store, endpoint=stub.url)
    SA.import_session(
        store, capture(access_exp=time.time() + 3600, refresh="synthetic-refresh-new")
    )
    st = SA.status(store)
    assert st["state"] == SA.STATE_HEALTHY
    assert st["episode"] is None
    assert store.read_status()["lastResolvedEpisode"]["resolvedAt"]


def test_disconnect_and_remote_revoke(store, stub):
    SA.import_session(store, capture(access_exp=time.time() + 3600))
    assert SA.revoke_remote(store, endpoint=stub.url) is True
    assert stub.calls[-1]["target"] == "RevokeToken"
    assert SA.disconnect(store) is True
    assert SA.status(store)["state"] == SA.STATE_NOT_CONNECTED


# ── data-request classification ─────────────────────────────────────────────


def test_data_403_is_not_assumed_expiry():
    assert SA.classify_data_response(200, renewal_attempted=False) == SA.DATA_OK
    assert SA.classify_data_response(403, renewal_attempted=False) == SA.DATA_RENEW_AND_RETRY
    assert SA.classify_data_response(403, renewal_attempted=True) == SA.ACCESS_DENIED
    assert SA.classify_data_response(401, renewal_attempted=True) == SA.ACCESS_DENIED
    assert SA.classify_data_response(429, renewal_attempted=False) == SA.TRANSIENT
    assert SA.classify_data_response(502, renewal_attempted=True) == SA.TRANSIENT


def test_acquisition_vocabulary_is_reused():
    assert SA.acquisition_state_for(None) == HEALTHY
    assert SA.acquisition_state_for(SA.TRANSIENT) == UNAVAILABLE
    for cls in (SA.RECONNECT_REQUIRED, SA.ACCESS_DENIED, SA.REFRESH_REFUSED):
        assert SA.acquisition_state_for(cls) == AUTH_REQUIRED


# ── owner notice ────────────────────────────────────────────────────────────


def test_one_notice_per_episode_and_unconfigured_does_not_consume(store, stub):
    SA.import_session(store, capture(access_exp=time.time() - 10, refresh="synthetic-refresh-dead"))
    session = store.read_session()
    with pytest.raises(SA.SignalsAuthError):
        SA.renew(store, endpoint=stub.url)
    # unconfigured mailer: still pending
    r = SA.deliver_reconnect_notice(store=store, delivery=None, to_email=None)
    assert r["pending"] is True and r["delivered"] is False
    # failing mailer: still pending
    r = SA.deliver_reconnect_notice(
        store=store, delivery=lambda *a: False, to_email="ops@example.invalid"
    )
    assert r["pending"] is True
    sent: list[tuple[str, str, str]] = []
    r = SA.deliver_reconnect_notice(
        store=store, delivery=lambda *a: sent.append(a) or True, to_email="ops@example.invalid"
    )
    assert r["delivered"] is True and len(sent) == 1
    for secret in _secrets(session):
        assert secret not in sent[0][1] and secret not in sent[0][2]
    # deduplicated
    SA.deliver_reconnect_notice(
        store=store, delivery=lambda *a: sent.append(a) or True, to_email="x@example.invalid"
    )
    assert len(sent) == 1


def test_notice_with_no_store_or_no_episode(store):
    r = SA.deliver_reconnect_notice(
        store=store, delivery=lambda *a: True, to_email="x@example.invalid"
    )
    assert r["pending"] is False


# ── concurrency: one renewal owner, no lost rotation ────────────────────────

_WORKER = r"""
import json, sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from src.sources import signals_auth as SA
store = SA.SignalsStore(Path(sys.argv[2]))
endpoint, mode, go = sys.argv[3], sys.argv[4], Path(sys.argv[5])
while not go.exists():
    time.sleep(0.005)
try:
    if mode == "get":
        tok = SA.get_access_token(store, endpoint=endpoint)
        print(json.dumps({"ok": True, "fp": SA.fingerprint(tok)}))
    else:
        s = SA.renew(store, force=True, endpoint=endpoint)
        print(json.dumps({"ok": True, "fp": SA.fingerprint(s["tokens"]["refreshToken"])}))
except SA.SignalsAuthError as exc:
    print(json.dumps({"ok": False, "cls": exc.failure_class, "reason": exc.reason}))
"""


def _run_workers(
    store: SA.SignalsStore, stub: StubCognito, mode: str, n: int, tmp_path: Path
) -> list[dict]:
    go = tmp_path / f"go-{mode}"
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", _WORKER, str(REPO), str(store.root), stub.url, mode, str(go)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(n)
    ]
    time.sleep(1.0)  # let every interpreter start and block on the barrier
    go.write_text("go")
    out = []
    for p in procs:
        stdout, stderr = p.communicate(timeout=120)
        assert p.returncode == 0, stderr
        out.append(json.loads(stdout.strip().splitlines()[-1]))
    return out


def test_concurrent_workers_renew_exactly_once(store, stub, tmp_path):
    SA.import_session(store, capture(access_exp=time.time() - 10))
    results = _run_workers(store, stub, "get", 6, tmp_path)
    assert all(r["ok"] for r in results), results
    assert stub.refresh_calls() == 1  # one owner renewed; the rest reused its result
    assert len({r["fp"] for r in results}) == 1
    assert store.read_session()["tokens"]["refreshToken"] == stub.valid


def test_concurrent_forced_renewals_never_lose_a_rotated_token(store, stub, tmp_path):
    """Strict rotation: reusing ANY superseded refresh token fails.  Every
    worker succeeds only because each re-reads the newest token under the lock."""
    SA.import_session(store, capture(access_exp=time.time() - 10))
    n = 5
    results = _run_workers(store, stub, "force", n, tmp_path)
    assert all(r["ok"] for r in results), results
    assert stub.refresh_calls() == n
    assert store.read_session()["tokens"]["refreshToken"] == stub.valid == f"synthetic-refresh-{n}"
    assert store.read_session()["refreshTokenRotations"] == n


# ── CLI ─────────────────────────────────────────────────────────────────────


def _cli(
    *args: str, stdin: bytes | None = None, env: dict | None = None
) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(REPO / "scripts" / "signals_connect.py"), *args],
        input=stdin,
        capture_output=True,
        timeout=120,
        env={**os.environ, **(env or {})},
        cwd=str(REPO),
    )


def test_cli_status_on_empty_store(tmp_path):
    r = _cli("--store-dir", str(tmp_path / "s"), "status", "--data-root", str(tmp_path / "nodata"))
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["authentication"]["state"] == SA.STATE_NOT_CONNECTED
    assert out["sourceDataFreshness"]["state"] == "not_collected"


def test_cli_renew_without_session_is_a_noop(tmp_path):
    r = _cli("--store-dir", str(tmp_path / "s"), "renew")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["state"] == SA.STATE_NOT_CONNECTED


def test_cli_refuses_a_store_inside_the_repo():
    r = _cli("--store-dir", str(REPO / "signals-auth"), "status")
    assert r.returncode == 2
    assert b"Unsafe store location" in r.stdout


def test_cli_import_session_reads_stdin(tmp_path):
    cap = capture(access_exp=time.time() + 3600)
    r = _cli("--store-dir", str(tmp_path / "box"), "import-session", stdin=json.dumps(cap).encode())
    assert r.returncode == 0, r.stderr
    for secret in (cap["accessToken"], cap["refreshToken"], cap["idToken"]):
        assert secret.encode() not in r.stdout
    assert (
        SA.SignalsStore(tmp_path / "box").read_session()["tokens"]["refreshToken"]
        == cap["refreshToken"]
    )


def test_provision_sends_the_session_on_stdin_only(tmp_path, monkeypatch):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "signals_connect", REPO / "scripts" / "signals_connect.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    local = tmp_path / "local"
    SA.import_session(SA.SignalsStore(local), capture(access_exp=time.time() + 3600))
    secret = SA.SignalsStore(local).read_session()["tokens"]["refreshToken"]
    seen: dict = {}

    def fake_run(cmd, input=None, **kw):  # noqa: A002
        seen["cmd"], seen["input"] = cmd, input
        return subprocess.CompletedProcess(cmd, 0, stdout=b'{"imported": true}', stderr=b"")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    rc = mod.main(
        ["--store-dir", str(local), "provision", "--host", "chaseupside", "--sudo-user", "dynasty"]
    )
    assert rc == 0
    assert secret.encode() in seen["input"]
    assert all(secret not in part for part in seen["cmd"])
    assert seen["cmd"][:3] == ["ssh", "-o", "BatchMode=yes"] and seen["cmd"][3] == "chaseupside"
    assert "import-session" in seen["cmd"][4] and "sudo -n -u dynasty" in seen["cmd"][4]
    # the box becomes the one renewal owner: local copy removed, NOT revoked
    assert SA.SignalsStore(local).read_session() is None


def test_cli_connect_help():
    r = _cli("connect", "--help")
    assert r.returncode == 0
    assert b"--dry-run" in r.stdout
