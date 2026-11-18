"""Deploy pre-flight must refuse an .env the server would refuse (Task 13)."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

from src.api import startup_guards as sg

ROOT = Path(__file__).resolve().parents[2]


def _run(tmp_path, text, production=True):
    env = tmp_path / ".env"
    env.write_text(text, encoding="utf-8")
    cmd = [sys.executable, "-E", "-s", "-m", "src.api.startup_guards", "--check-env-file", str(env)]
    if production:
        cmd.append("--production")
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)


@pytest.mark.parametrize(
    "text",
    [
        "JASON_LOGIN_PASSWORD=changeme\n",
        'JASON_LOGIN_PASSWORD="changeme"\n',
        "# c\nexport JASON_LOGIN_PASSWORD='password'\n",
        "SOMETHING=1\n",  # absent password, no dev hatch
        "JASON_LOGIN_PASSWORD=\n",
        "JASON_LOGIN_PASSWORD=real-pw-9x\nJASON_LOGIN_PASSWORD=changeme\n",  # last wins
        "JASON_LOGIN_PASSWORD=real-pw-9x\nE2E_TEST_MODE=1\n",
        'JASON_LOGIN_PASSWORD=real-pw-9x\nALLOW_DEFAULT_LOGIN_DEV="true"\n',
    ],
)
def test_refused(tmp_path, text):
    proc = _run(tmp_path, text)
    assert proc.returncode == 1, proc.stderr
    assert "real-pw-9x" not in proc.stderr and "changeme" not in proc.stderr


@pytest.mark.parametrize(
    "text",
    [
        "JASON_LOGIN_PASSWORD=real-pw-9x\n",
        "JASON_LOGIN_PASSWORD=changeme\nJASON_LOGIN_PASSWORD='real-pw-9x'\n",  # last wins
        '; comment\n\nJASON_LOGIN_PASSWORD="real-pw-9x"\nE2E_TEST_MODE=0\n',
    ],
)
def test_accepted(tmp_path, text):
    proc = _run(tmp_path, text)
    assert proc.returncode == 0, proc.stderr


def test_non_production_dev_hatch_allows_placeholder(tmp_path):
    proc = _run(tmp_path, "JASON_LOGIN_PASSWORD=changeme\nALLOW_DEFAULT_LOGIN_DEV=1\n", False)
    assert proc.returncode == 0


def test_shared_rule_function():
    assert sg.startup_refusals({"JASON_LOGIN_PASSWORD": "real-pw-9x"}) == []
    assert sg.startup_refusals({"JASON_LOGIN_PASSWORD": "Changeme"})
    assert sg.startup_refusals({})
    assert sg.startup_refusals({"ALLOW_DEFAULT_LOGIN_DEV": "on"}) == []
    assert sg.startup_refusals(
        {"JASON_LOGIN_PASSWORD": "x-real-1", "RISKIT_ENV": "production", "E2E_TEST_MODE": "yes"}
    )
    assert sg.startup_refusals({"JASON_LOGIN_PASSWORD": "x-real-1", "E2E_TEST_MODE": "1"}) == []


def test_parse_env_file_semantics():
    got = sg.parse_env_file("A=1\n# x\n;y=2\nexport B='q'\nA=\"2\"\nC='mis\"\n")
    assert got == {"A": "2", "B": "q", "C": "'mis\""}


def test_server_uses_shared_rules_and_guard_precedes_swaps():
    assert "startup_refusals(os.environ)" in (ROOT / "server.py").read_text(encoding="utf-8")
    text = (ROOT / "deploy/deploy.sh").read_text(encoding="utf-8")
    body = text[text.index("\nmain() {") :]
    guard = body.index("check_box_env_guards")
    for later in (
        'git checkout --force "${TARGET_REV}"',
        "prepare_python_runtime",
        "deploy_frontend_atomic",
        "restart_service",
    ):
        assert guard < body.index(later), later
    assert len(re.findall(r"^\s*check_box_env_guards", body, re.M)) == 1


def test_script_runs_by_path_not_module(tmp_path):
    env = tmp_path / ".env"
    script = ROOT / "src/api/startup_guards.py"
    base = [sys.executable, "-E", "-s", str(script), "--check-env-file", str(env), "--production"]
    env.write_text("JASON_LOGIN_PASSWORD=changeme\n", encoding="utf-8")
    assert subprocess.run(base, cwd=tmp_path, capture_output=True).returncode == 1
    env.write_text("JASON_LOGIN_PASSWORD=real-pw-9x\n", encoding="utf-8")
    assert subprocess.run(base, cwd=tmp_path, capture_output=True).returncode == 0
