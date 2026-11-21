"""Box-side TEST push per alert class (STAB-2) -- booleans only, never the URL."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from scripts import send_owner_test_alert as T

TOPIC = "https://ntfy.sh/private-topic-for-tests"
TOKEN = "cron-token-for-tests-0123456789"
#: The real loopback POST, captured before the autouse stub replaces it.
_REAL_POST = T._urllib_post


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch):
    """No test reaches systemctl or a real backend unless it says so."""
    calls: list[tuple] = []

    def no_backend(url, token, timeout):
        calls.append((url, token, timeout))
        raise ConnectionRefusedError("no backend in tests")

    monkeypatch.setattr(T, "_urllib_post", no_backend)
    monkeypatch.setattr(T.H, "systemd_show", lambda unit, props: {})
    return calls


def _env(tmp_path, text):
    (tmp_path / ".env").write_text(text, encoding="utf-8")
    return tmp_path


def test_unconfigured_sends_nothing_and_exits_3(tmp_path):
    out, code = T.run(_env(tmp_path, "ALERT_ENABLED=false\n"), transport=lambda *a: 200)
    assert code == 3
    assert out["configured"] == {"ntfy": False}
    assert set(out["sent"]) == {k for k, _ in T.TEST_CLASSES}
    assert all(v is None for v in out["sent"].values())


def test_every_class_is_pushed_once_with_its_title(tmp_path):
    seen = []

    def transport(url, title, body, timeout):
        assert url == TOPIC
        seen.append(title)
        return 200

    out, code = T.run(_env(tmp_path, f"NOTIFY_WEBHOOK_URL={TOPIC}\n"), transport=transport)
    assert code == 0
    assert seen == [title for _, title in T.TEST_CLASSES]
    assert all(out["sent"].values())
    assert all(title.startswith("[TEST] ") for title in seen)


def test_a_failed_push_is_reported_and_exits_1(tmp_path):
    calls = {"n": 0}

    def transport(url, title, body, timeout):
        calls["n"] += 1
        return 500 if calls["n"] == 2 else 200

    out, code = T.run(_env(tmp_path, f"NOTIFY_WEBHOOK_URL={TOPIC}\n"), transport=transport)
    assert code == 1
    assert list(out["sent"].values()).count(False) == 1


def test_a_rejected_value_sends_nothing_and_says_why(tmp_path, capsys, monkeypatch):
    calls = []
    app = _env(tmp_path, "NOTIFY_WEBHOOK_URL=http://ntfy.sh/private-topic-for-tests\n")
    out, code = T.run(app, transport=lambda *a: calls.append(a) or 200)
    assert code == 3 and calls == []
    assert out["configured"] == {"ntfy": False}
    assert out["ntfyState"] == "rejected_scheme"
    monkeypatch.setattr(T.owner_notify, "_urllib_transport", lambda *a: 200)
    assert T.main(["--app-dir", str(app)]) == 3
    printed = capsys.readouterr().out
    assert json.loads(printed)["ntfyState"] == "rejected_scheme"
    assert "private-topic" not in printed


def test_missing_env_file_is_unreadable_not_configured(tmp_path):
    out, code = T.run(tmp_path / "nope", transport=lambda *a: 200)
    assert code == 3
    assert out["envFileReadable"] is False


def test_main_output_is_public_safe_and_never_names_the_topic(tmp_path, capsys, monkeypatch):
    app = _env(tmp_path, f"NOTIFY_WEBHOOK_URL={TOPIC}\n")
    monkeypatch.setattr(T.owner_notify, "_urllib_transport", lambda *a: 200)
    code = T.main(["--app-dir", str(app)])
    printed = capsys.readouterr().out
    assert code == 0
    assert "ntfy.sh" not in printed and "private-topic" not in printed
    assert json.loads(printed)["configured"] == {"ntfy": True}


def test_the_operator_run_never_writes_the_servers_delivery_record(tmp_path, monkeypatch):
    """This script runs out of process on the box; the delivery-health record
    in user_kv is the server's (``/api/status`` ``alertDelivery``)."""
    store = tmp_path / "user_kv.sqlite"
    monkeypatch.setattr(T.owner_alerts, "HEALTH_STORE_PATH", store)
    out, code = T.run(_env(tmp_path, f"NOTIFY_WEBHOOK_URL={TOPIC}\n"), transport=lambda *a: 500)
    assert code == 1 and not any(out["sent"].values())
    assert not store.exists()


# -- the RUNNING backend's producers (E2E-TEST) ---------------------------------------
_ALL_DELIVERED = {
    "mode": "producers",
    "ntfyState": "ok",
    "producers": {
        name: {"delivered": True, "reason": "delivered"}
        for name in ("opsAlerts", "sourceHealthAlerts", "sendAlert", "signalsReconnectNotice")
    },
}


def _with_token(tmp_path, extra=""):
    return _env(tmp_path, f"NOTIFY_WEBHOOK_URL={TOPIC}\nSIGNAL_ALERT_CRON_TOKEN={TOKEN}\n{extra}")


def test_no_token_says_so_and_fails_nothing(tmp_path, _hermetic):
    out, code = T.run(_env(tmp_path, f"NOTIFY_WEBHOOK_URL={TOPIC}\n"), transport=lambda *a: 200)
    assert code == 0
    assert out["backend"]["tokenConfigured"] is False
    assert out["backend"]["state"] == "token_absent"
    assert _hermetic == [], "no token: the backend is never called"


def test_a_delivering_backend_passes_and_is_called_with_the_bearer(tmp_path):
    seen = []

    def post(url, token, timeout):
        seen.append((url, token))
        return 200, _ALL_DELIVERED

    out, code = T.run(_with_token(tmp_path), transport=lambda *a: 200, post=post)
    assert code == 0, out
    assert seen == [(T.LOCAL_PRODUCER_TEST_URL, TOKEN)]
    assert T.LOCAL_PRODUCER_TEST_URL.startswith("http://127.0.0.1:")
    assert out["backend"]["state"] == "ok" and out["backend"]["httpStatus"] == 200
    assert out["backend"]["producers"] == _ALL_DELIVERED["producers"]


@pytest.mark.parametrize(
    "status,body,state",
    [
        (
            502,
            {"producers": {"sendAlert": {"delivered": False, "reason": "all_channels_failed"}}},
            "failed",
        ),
        # The RUNNING process has no channel although .env does: not restarted.
        (
            400,
            {"producers": {"sendAlert": {"delivered": None, "reason": "not_configured"}}},
            "not_configured",
        ),
        # A backend on another token, or one that predates the bearer.
        (401, {"error": "auth_required"}, "refused"),
        (200, {"producers": {"opsAlerts": {"delivered": False, "reason": "producer_error"}}}, "ok"),
        (200, {"error": "nonsense"}, "unexpected_response"),
        (500, None, "unexpected_status"),
        # The shared test-alert budget is spent: healthy backend, nothing sent.
        (429, {"error": "rate_limited", "retryAfterSeconds": 120}, "rate_limited"),
    ],
)
def test_a_backend_that_did_not_deliver_everywhere_fails_the_run(tmp_path, status, body, state):
    out, code = T.run(
        _with_token(tmp_path), transport=lambda *a: 200, post=lambda *a: (status, body)
    )
    assert code == 1, out
    assert out["backend"]["state"] == state
    assert out["backend"]["httpStatus"] == status


@pytest.mark.parametrize(
    "body,expected",
    [
        ({"error": "rate_limited", "retryAfterSeconds": 120}, 120),
        ({"error": "rate_limited", "retryAfterSeconds": "120; https://x"}, None),
        ({"error": "rate_limited", "retryAfterSeconds": True}, None),
        (None, None),
    ],
)
def test_a_rate_limited_backend_reports_only_an_integer_retry_hint(body, expected):
    report, passed = T.backend_producer_check(
        {"SIGNAL_ALERT_CRON_TOKEN": TOKEN}, post=lambda *a: (429, body)
    )
    assert passed is False and report["state"] == "rate_limited"
    assert report["retryAfterSeconds"] == expected


def test_an_unreachable_backend_reports_the_error_class_only(tmp_path, _hermetic):
    out, code = T.run(_with_token(tmp_path), transport=lambda *a: 200)
    assert code == 1
    assert out["backend"]["state"] == "unreachable"
    assert out["backend"]["errorClass"] == "ConnectionRefusedError"
    assert len(_hermetic) == 1


def test_an_env_without_push_still_tests_the_backend_and_keeps_exit_3(tmp_path):
    app = _env(tmp_path, f"SIGNAL_ALERT_CRON_TOKEN={TOKEN}\n")
    out, code = T.run(app, transport=lambda *a: 200, post=lambda *a: (200, _ALL_DELIVERED))
    assert code == 3
    assert out["backend"]["state"] == "ok"


def test_backend_answers_are_allowlisted_never_echoed(tmp_path, capsys, monkeypatch):
    hostile = {
        "ntfyState": "https://evil.example/x",
        "producers": {
            "opsAlerts": {"delivered": "yes", "reason": "see https://x", "errorClass": "a/b"},
            "bad name": {"delivered": True, "reason": "delivered"},
        },
    }
    app = _with_token(tmp_path)
    monkeypatch.setattr(T, "_urllib_post", lambda *a: (502, hostile))
    monkeypatch.setattr(T.owner_notify, "_urllib_transport", lambda *a: 200)
    assert T.main(["--app-dir", str(app)]) == 1
    printed = capsys.readouterr().out
    report = json.loads(printed)["backend"]
    assert report["producers"] == {
        "opsAlerts": {"delivered": None, "reason": "unrecognized", "errorClass": "withheld"}
    }
    assert report["ntfyState"] is None
    for secret in ("evil.example", "https://", TOKEN, "private-topic"):
        assert secret not in printed


def test_reasons_match_the_server():
    import server

    assert T.PRODUCER_REASONS == server.OWNER_ALERT_PRODUCER_REASONS


def test_the_real_post_sends_the_bearer_to_loopback_and_reads_error_bodies():
    """``_urllib_post`` against a real loopback HTTP server: POST, bearer header,
    JSON body read back for a 2xx and for an HTTP error alike."""
    seen: list[tuple[str, str, str | None]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802 - http.server API
            seen.append((self.command, self.path, self.headers.get("Authorization")))
            ok = self.headers.get("Authorization") == f"Bearer {TOKEN}"
            payload = json.dumps(_ALL_DELIVERED if ok else {"error": "auth_required"}).encode()
            self.send_response(200 if ok else 401)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_a):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{httpd.server_port}/api/test-alert?producers=1"
        assert _REAL_POST(url, TOKEN, 5.0) == (200, _ALL_DELIVERED)
        assert _REAL_POST(url, "wrong", 5.0) == (401, {"error": "auth_required"})
    finally:
        httpd.shutdown()
        thread.join(timeout=5)
    assert seen == [
        ("POST", "/api/test-alert?producers=1", f"Bearer {TOKEN}"),
        ("POST", "/api/test-alert?producers=1", "Bearer wrong"),
    ]


# -- the push-capable drop-in units --------------------------------------------------
def test_dropin_units_are_reported_by_name_from_the_probe_mapping(tmp_path, monkeypatch):
    units = list(T.H.PUSH_DROPIN_UNITS.values())
    assert units, "the mapping is the source of truth; it must not be empty"
    configured, unloaded = units[0], units[1:]

    def show(unit, props):
        if unit == configured:
            return {"LoadState": "loaded", "Environment": f"NOTIFY_WEBHOOK_URL={TOPIC}"}
        return {"LoadState": "not-found"}

    monkeypatch.setattr(T.H, "systemd_show", show)
    out, _ = T.run(_env(tmp_path, f"NOTIFY_WEBHOOK_URL={TOPIC}\n"), transport=lambda *a: 200)
    expected = {T._unit_identifier(configured): True}
    expected.update({T._unit_identifier(u): None for u in unloaded})
    assert out["dropinUnits"] == expected
    # A name, spelled as a public-safe identifier.
    assert T._unit_identifier("riskit-uptime.service") == "riskit_uptime_service"


def test_a_loaded_unit_without_a_webhook_is_false_and_output_is_public_safe(
    tmp_path, capsys, monkeypatch
):
    monkeypatch.setattr(
        T.H, "systemd_show", lambda unit, props: {"LoadState": "loaded", "Environment": "A=b"}
    )
    monkeypatch.setattr(T.owner_notify, "_urllib_transport", lambda *a: 200)
    assert T.main(["--app-dir", str(_env(tmp_path, f"NOTIFY_WEBHOOK_URL={TOPIC}\n"))]) == 0
    report = json.loads(capsys.readouterr().out)
    assert set(report["dropinUnits"]) == {
        T._unit_identifier(u) for u in T.H.PUSH_DROPIN_UNITS.values()
    }
    assert all(v is False for v in report["dropinUnits"].values())
