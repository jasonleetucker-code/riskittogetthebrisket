"""The shared owner push path (``NOTIFY_WEBHOOK_URL``, same as the uptime probe)."""

from __future__ import annotations

import pytest

from src.utils import owner_notify as N


class Recorder:
    def __init__(self, status=200, exc=None):
        self.calls, self.status, self.exc = [], status, exc

    def __call__(self, url, title, body, timeout):
        self.calls.append((url, title, body, timeout))
        if self.exc:
            raise self.exc
        return self.status


def test_unset_means_nothing_is_contacted(monkeypatch):
    monkeypatch.delenv(N.WEBHOOK_ENV, raising=False)
    rec = Recorder()
    assert N.webhook_url() is None and N.channel(transport=rec) is None
    assert N.send("t", "b", transport=rec) is False
    assert rec.calls == []


def test_posts_plain_text_with_title_to_the_configured_topic(monkeypatch):
    monkeypatch.setenv(N.WEBHOOK_ENV, "https://ntfy.example/private-topic")
    rec = Recorder()
    assert N.channel(transport=rec)("Subject", "Body") is True
    url, title, body, timeout = rec.calls[0]
    assert url == "https://ntfy.example/private-topic" and title == "Subject"
    assert body == "Subject\n\nBody" and timeout <= N.DEFAULT_TIMEOUT_SECONDS


@pytest.mark.parametrize(
    "rec",
    [
        Recorder(status=500),
        Recorder(status=403),
        Recorder(exc=TimeoutError()),
        Recorder(exc=OSError()),
    ],
)
def test_an_unavailable_webhook_returns_false_and_never_raises(monkeypatch, rec):
    monkeypatch.setenv(N.WEBHOOK_ENV, "https://ntfy.example/t")
    assert N.send("t", "b", transport=rec) is False


@pytest.mark.parametrize(
    ("url", "ok"),
    [("http://ntfy.example/t", False), ("ftp://x/t", False), ("http://127.0.0.1:8080/t", True)],
)
def test_only_https_or_loopback(monkeypatch, url, ok):
    monkeypatch.setenv(N.WEBHOOK_ENV, url)
    assert (N.webhook_url() is not None) is ok


# ── ONE validator (2026-11-20) ────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "state"),
    [
        (None, "unset"),
        ("", "unset"),
        ("   ", "unset"),
        ("https://ntfy.sh/private-topic", "ok"),
        ("  https://ntfy.sh/private-topic\n", "ok"),  # surrounding whitespace is ignored
        ("https://ntfy.example:8443/t?auth=tok", "ok"),
        ("http://127.0.0.1:8080/t", "ok"),
        ("http://localhost/t", "ok"),
        ("https://ntfy.sh/a b", "rejected:whitespace"),
        ("https://ntfy.sh/a\tb", "rejected:whitespace"),
        ("https://u:p@ntfy.sh/x", "rejected:userinfo"),
        ("https://token@ntfy.sh/x", "rejected:userinfo"),
        ("HTTPS://ntfy.sh/x", "rejected:scheme"),  # the workflows' `== https://*` agrees
        ("Https://ntfy.sh/x", "rejected:scheme"),
        ("http://ntfy.sh/x", "rejected:scheme"),
        ('"https://ntfy.sh/x"', "rejected:scheme"),  # a quoted value is not a URL
        ("ftp://x/t", "rejected:scheme"),
        ("ntfy.sh/x", "rejected:scheme"),
        ("https:///x", "rejected:no_host"),
        ("https://", "rejected:no_host"),
        ("https://ntfy.sh:abc/x", "rejected:malformed"),
        ("https://[::1/x", "rejected:malformed"),
        ("https://ntfy.sh/café", "rejected:malformed"),
        ("https://ntfy.sh/\x00", "rejected:malformed"),
    ],
)
def test_validate_answers_a_state_and_a_reason_code(raw, state):
    assert N.validate(raw) == state
    if state.startswith(N.REJECTED_PREFIX):
        assert state[len(N.REJECTED_PREFIX) :] in N.REJECT_REASONS


def test_validate_never_echoes_the_value():
    for raw in ("https://u:secret-topic@ntfy.sh/x", "http://ntfy.sh/secret-topic", "x secret"):
        assert "secret" not in N.validate(raw)


def test_public_state_is_identifier_shaped():
    assert N.public_state("rejected:no_host") == "rejected_no_host"
    assert N.public_state("ok") == "ok" and N.public_state("unset") == "unset"


def test_every_sender_uses_the_validator(monkeypatch):
    """A rejected value is never contacted, whatever path asks."""
    rec = Recorder()
    monkeypatch.setenv(N.WEBHOOK_ENV, "https://u:p@ntfy.sh/t")
    assert N.webhook_url() is None and N.channel(transport=rec) is None
    assert N.send("t", "b", url="HTTPS://ntfy.sh/t", transport=rec) is False
    assert rec.calls == []


@pytest.mark.parametrize("status", ["200 OK", None, object()])
def test_a_non_integer_status_returns_false_and_never_raises(monkeypatch, status):
    monkeypatch.setenv(N.WEBHOOK_ENV, "https://ntfy.example/t")
    assert N.send("t", "b", transport=lambda *a: status) is False


def test_a_string_integer_status_still_counts():
    assert N.send("t", "b", url="https://ntfy.example/t", transport=lambda *a: "204") is True


# ── redirects are refused (the scheme check covers the only hop) ───────────


def test_a_redirect_is_not_followed():
    import http.server
    import threading

    hits: list[str] = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802 - http.server API
            hits.append(self.path)
            length = int(self.headers.get("Content-Length") or 0)
            self.rfile.read(length)
            if self.path == "/start":
                self.send_response(307)
                self.send_header("Location", "/elsewhere")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *_a):
            return None

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        assert N.send("t", "b", url=f"{base}/elsewhere") is True  # the server itself works
        hits.clear()
        assert N.send("t", "b", url=f"{base}/start") is False
        assert hits == ["/start"], "the redirect target must not be contacted"
    finally:
        server.shutdown()
        server.server_close()


# ── `python -m src.utils.owner_notify --check` ─────────────────────────────


@pytest.mark.parametrize(
    ("value", "code", "state"),
    [
        (None, 3, "unset"),
        ("https://ntfy.sh/private-topic-xyz", 0, "ok"),
        ("http://ntfy.sh/private-topic-xyz", 1, "rejected:scheme"),
    ],
)
def test_check_cli_exit_codes_and_no_echo(value, code, state):
    import os
    import subprocess
    import sys
    from pathlib import Path

    env = {k: v for k, v in os.environ.items() if k != N.WEBHOOK_ENV}
    if value is not None:
        env[N.WEBHOOK_ENV] = value
    proc = subprocess.run(
        [sys.executable, "-m", "src.utils.owner_notify", "--check"],
        cwd=Path(N.__file__).resolve().parents[2],
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == code, proc.stderr
    assert state in proc.stderr
    assert "private-topic" not in proc.stdout + proc.stderr
    assert N.check_exit_code(state) == code
