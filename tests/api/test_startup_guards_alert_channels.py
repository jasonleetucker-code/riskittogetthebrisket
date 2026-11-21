"""Owner-alert settings that will not deliver are WARNED about at startup (2026-11-20).

A ``NOTIFY_WEBHOOK_URL`` like ``http://ntfy.sh/x`` used to be dropped without a
word: ``send_alert`` returned silently, the sweeps reported ``deliveryConfigured:
false`` and ``/api/test-alert`` said "not configured" for a variable that WAS
set.  ``startup_guards.alert_channel_warnings`` names the variable and a reason
code -- never the value -- and the server logs it once, as a warning, never a
refusal (alerts are optional).  The deploy pre-flight prints the same lines.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.api import startup_guards as sg

ROOT = Path(__file__).resolve().parents[2]
TOPIC = "https://ntfy.sh/private-topic-for-tests"
EMAIL = {
    "ALERT_ENABLED": "true",
    "ALERT_TO": "owner@example.invalid",
    "ALERT_FROM": "box@example.invalid",
    "ALERT_PASSWORD": "not-a-real-password",
}


def _no_value_leaks(lines):
    text = "\n".join(lines)
    for secret in ("private-topic", "ntfy.sh/", "owner@example", "not-a-real-password"):
        assert secret not in text, secret


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        ("http://ntfy.sh/private-topic-for-tests", "scheme"),
        ("https://u:p@ntfy.sh/private-topic-for-tests", "userinfo"),
        ("https://ntfy.sh/private topic", "whitespace"),
        ("HTTPS://ntfy.sh/private-topic-for-tests", "scheme"),
    ],
)
def test_a_rejected_webhook_is_named_with_its_reason(raw, reason):
    lines = sg.alert_channel_warnings({"NOTIFY_WEBHOOK_URL": raw})
    assert len(lines) == 1
    assert lines[0].startswith("NOTIFY_WEBHOOK_URL is set but rejected")
    assert f"({reason})" in lines[0]
    _no_value_leaks(lines)


def test_a_valid_or_absent_webhook_outside_production_says_nothing():
    assert sg.alert_channel_warnings({"NOTIFY_WEBHOOK_URL": TOPIC}) == []
    assert sg.alert_channel_warnings({}) == []


def test_half_configured_email_names_what_is_missing():
    env = {k: v for k, v in EMAIL.items() if k not in ("ALERT_TO", "ALERT_PASSWORD")}
    lines = sg.alert_channel_warnings(env)
    assert lines == [
        "ALERT_ENABLED is on but ALERT_TO, ALERT_PASSWORD unset; e-mail alerts are off"
    ]
    assert sg.alert_channel_warnings(EMAIL) == []
    assert sg.alert_channel_warnings({**EMAIL, "ALERT_ENABLED": "false", "ALERT_TO": ""}) == []
    alias = {k: v for k, v in EMAIL.items() if k != "ALERT_PASSWORD"}
    alias["GMAIL_APP_PASSWORD"] = "not-a-real-password"
    assert sg.alert_channel_warnings(alias) == []


def test_production_with_no_channel_at_all_is_said_once():
    prod = {"RISKIT_ENV": "production"}
    lines = sg.alert_channel_warnings(prod)
    assert len(lines) == 1 and lines[0].startswith("no owner alert channel is configured")
    assert sg.alert_channel_warnings({**prod, "NOTIFY_WEBHOOK_URL": TOPIC}) == []
    assert sg.alert_channel_warnings({**prod, **EMAIL}) == []
    rejected = sg.alert_channel_warnings({**prod, "NOTIFY_WEBHOOK_URL": "http://ntfy.sh/x"})
    assert len(rejected) == 2  # why the webhook is off, and that nothing is left


def test_warnings_never_become_refusals():
    env = {"JASON_LOGIN_PASSWORD": "real-pw-9x", "NOTIFY_WEBHOOK_URL": "http://ntfy.sh/x"}
    assert sg.startup_refusals(env) == []
    assert sg.alert_channel_warnings(env)


def _preflight(script: Path, env_file: Path, cwd: Path):
    cmd = [sys.executable, "-E", "-s", str(script), "--check-env-file", str(env_file)]
    return subprocess.run([*cmd, "--production"], cwd=cwd, capture_output=True, text=True)


def test_the_preflight_prints_the_warning_and_keeps_its_exit_code(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "JASON_LOGIN_PASSWORD=real-pw-9x\nNOTIFY_WEBHOOK_URL=http://ntfy.sh/private-topic-x\n",
        encoding="utf-8",
    )
    proc = _preflight(ROOT / "src/api/startup_guards.py", env, tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert "startup guard warning: NOTIFY_WEBHOOK_URL is set but rejected (scheme)" in proc.stderr
    assert "private-topic" not in proc.stderr + proc.stdout


def test_single_file_preflight_still_runs_without_the_validator(tmp_path):
    """``deploy/deploy.sh`` copies ONLY this file out of the target revision: the
    lazy import must not crash it (a crash would refuse every deploy)."""
    lone = tmp_path / "lone"
    lone.mkdir()
    shutil.copy(ROOT / "src/api/startup_guards.py", lone / "startup_guards.py")
    env = tmp_path / ".env"
    env.write_text(
        "JASON_LOGIN_PASSWORD=real-pw-9x\nNOTIFY_WEBHOOK_URL=http://ntfy.sh/x\n",
        encoding="utf-8",
    )
    # deploy.sh's copy lives in ``mktemp -d``; a module planted at the shared
    # parent (``/tmp/utils/owner_notify.py``) must never be executed.
    planted = tmp_path / "utils"
    planted.mkdir()
    marker = tmp_path / "planted-ran"
    (planted / "owner_notify.py").write_text(
        f"open({str(marker)!r}, 'w', encoding='utf-8').close()\n", encoding="utf-8"
    )
    proc = _preflight(lone / "startup_guards.py", env, tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert "rejected" not in proc.stderr  # not judged, never guessed
    assert not marker.exists(), "a module outside the private copy dir was executed"
    # A copy of the validator beside it is used when present.
    shutil.copy(ROOT / "src/utils/owner_notify.py", lone / "owner_notify.py")
    proc = _preflight(lone / "startup_guards.py", env, tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert "NOTIFY_WEBHOOK_URL is set but rejected (scheme)" in proc.stderr


def test_the_server_logs_the_warnings_and_does_not_refuse():
    text = (ROOT / "server.py").read_text(encoding="utf-8")
    assert "_startup_guards.alert_channel_warnings(os.environ)" in text
    block = text[text.index("_startup_guards.alert_channel_warnings(os.environ)") :][:200]
    assert "log.warning" in block and "raise" not in block


def test_deploy_sh_copies_the_validator_into_the_same_private_dir():
    """The pre-flight stages startup_guards.py in a ``mktemp -d``; the validator
    must sit beside it (the only place the lone copy loads it from), and both
    are removed again by name, never recursively."""
    text = (ROOT / "deploy/deploy.sh").read_text(encoding="utf-8")
    body = text[text.index("check_box_env_guards() {") :]
    body = body[: body.index("\n}\n")]
    assert 'git show "${TARGET_REV}:src/utils/owner_notify.py" > "${tmp}/owner_notify.py"' in body
    assert body.index("owner_notify.py") < body.index("--check-env-file")
    assert 'rm -f -- "${tmp}/startup_guards.py" "${tmp}/owner_notify.py"' in body
    code = "\n".join(ln for ln in body.splitlines() if not ln.strip().startswith("#"))
    assert "rm -rf" not in code


def test_the_staged_pair_judges_the_webhook_end_to_end(tmp_path):
    """Exactly what deploy.sh stages: the two files, alone, in a private dir."""
    staged = tmp_path / "staged"
    staged.mkdir()
    shutil.copy(ROOT / "src/api/startup_guards.py", staged / "startup_guards.py")
    shutil.copy(ROOT / "src/utils/owner_notify.py", staged / "owner_notify.py")
    env = tmp_path / ".env"
    env.write_text(
        "JASON_LOGIN_PASSWORD=real-pw-9x\nNOTIFY_WEBHOOK_URL=https://u:p@ntfy.sh/private-topic-x\n",
        encoding="utf-8",
    )
    proc = _preflight(staged / "startup_guards.py", env, tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert "rejected (userinfo)" in proc.stderr
    assert "private-topic" not in proc.stderr + proc.stdout
