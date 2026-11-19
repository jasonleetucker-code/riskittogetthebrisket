"""``scripts/check_login_status.py`` prints only a status line and never a secret."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

import check_login_status as cls  # noqa: E402

SECRET = "S3cret-Value-Never-Printed-0123"


def _run(capsys, status, expect, env_extra=None, argv_extra=()):
    seen = {}

    def fake_login(url, user, pw):
        seen.update(url=url, user=user, pw=pw)
        return status

    env = {"CHECK_LOGIN_PASSWORD": SECRET, "JASON_LOGIN_USERNAME": "owner"}
    env.update(env_extra or {})
    rc = cls.main(
        ["--url", "https://example.invalid", "--expect", expect, *argv_extra],
        env=env,
        login=fake_login,
    )
    out = capsys.readouterr()
    return rc, out.out + out.err, seen


def test_new_password_ok_and_old_password_refused_match_their_expectation(capsys):
    rc, text, seen = _run(capsys, 200, "ok", argv_extra=("--label", "new"))
    assert rc == 0 and text.strip() == "login HTTP 200 (new)"
    assert seen["user"] == "owner" and seen["pw"] == SECRET
    rc, text, _ = _run(capsys, 401, "refused", argv_extra=("--label", "old"))
    assert rc == 0 and text.strip() == "login HTTP 401 (old)"


def test_mismatch_and_throttle_are_failures_not_passes(capsys):
    assert _run(capsys, 401, "ok")[0] == 1
    assert _run(capsys, 200, "refused")[0] == 1
    assert _run(capsys, 429, "refused")[0] == 1  # throttled: no evidence either way
    assert _run(capsys, 503, "ok")[0] == 1


def test_secret_never_appears_in_output(capsys):
    for status, expect in ((200, "ok"), (401, "refused"), (401, "ok"), (429, "refused")):
        _, text, _ = _run(capsys, status, expect)
        assert SECRET not in text


def test_refuses_plain_http_and_missing_inputs(capsys):
    rc = cls.main(
        ["--url", "http://example.invalid", "--expect", "ok"],
        env={"CHECK_LOGIN_PASSWORD": SECRET, "JASON_LOGIN_USERNAME": "o"},
        login=lambda *a: 200,
    )
    assert rc == 2
    rc = cls.main(
        ["--url", "https://example.invalid", "--expect", "ok"],
        env={"CHECK_LOGIN_PASSWORD": SECRET},
        login=lambda *a: 200,
    )
    assert rc == 2
    rc = cls.main(
        ["--url", "https://example.invalid", "--expect", "ok", "--username", "o"],
        env={},
        prompt=lambda _p: "",
        login=lambda *a: 200,
    )
    assert rc == 2


def _guarded(url, monkeypatch):
    calls = []
    monkeypatch.setattr(cls.urllib.request, "urlopen", lambda *a, **k: calls.append(a))
    rc = cls.main(
        ["--url", url, "--expect", "ok"],
        env={"CHECK_LOGIN_PASSWORD": SECRET, "JASON_LOGIN_USERNAME": "owner"},
    )
    return rc, calls


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost.evil.com",
        "http://127.0.0.1.evil.com",
        "http://localhost@evil.com",
        "https://owner:pw@example.invalid",
        "http://user:pw@localhost:8000",
        "ftp://localhost",
    ],
)
def test_foreign_or_userinfo_urls_refused_and_nothing_sent(url, monkeypatch, capsys):
    rc, calls = _guarded(url, monkeypatch)
    out = capsys.readouterr()
    assert rc == 2 and calls == []
    assert SECRET not in out.out + out.err


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://[::1]:8000",
        "https://example.invalid",
    ],
)
def test_loopback_http_and_https_allowed(url):
    assert cls.url_is_safe(url)


def test_midflight_network_error_exits_2_without_leaking_secret(capsys):
    def boom(url, user, pw):
        raise cls.urllib.error.URLError(f"connection reset {pw}")

    rc = cls.main(
        ["--url", "https://example.invalid", "--expect", "ok"],
        env={"CHECK_LOGIN_PASSWORD": SECRET, "JASON_LOGIN_USERNAME": "owner"},
        login=boom,
    )
    out = capsys.readouterr()
    assert rc == 2
    assert SECRET not in out.out + out.err


def test_password_has_no_command_line_flag():
    src = (REPO / "scripts" / "check_login_status.py").read_text(encoding="utf-8")
    assert '"--password"' not in src
    assert '"--password-env"' in src
