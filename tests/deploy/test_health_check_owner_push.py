"""The GitHub-side production alerts also reach the owner's phone (STAB-2).

`health-check.yml` files and closes rolling issues; GitHub's own notification
e-mail was the only way the owner heard of them.  The tracker steps now also
POST to the owner's ntfy topic (repo secret ``NOTIFY_WEBHOOK_URL``) on a NEW
incident, a CHANGED condition set and a RECOVERY -- never on every run -- and
never print the URL.  Unset secret -> no-op.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WF = ROOT / ".github" / "workflows" / "health-check.yml"
STEPS = (
    "Open or update the tracking issue on failure",
    "Close the tracking issue on a green run",
    "Sync the rolling SLO tracking issue",
)


def _steps() -> dict[str, dict]:
    doc = yaml.safe_load(WF.read_text(encoding="utf-8"))
    out = {}
    for job in doc["jobs"].values():
        for step in job.get("steps", []):
            if step.get("name") in STEPS:
                out[step["name"]] = step
    return out


def test_each_tracker_step_receives_the_secret():
    steps = _steps()
    assert set(steps) == set(STEPS)
    for name, step in steps.items():
        assert step["env"].get("NOTIFY_WEBHOOK_URL") == "${{ secrets.NOTIFY_WEBHOOK_URL }}", name


def test_pushes_only_at_lifecycle_points():
    text = WF.read_text(encoding="utf-8")
    calls = re.findall(r'notify_owner "([^"]+)"', text)
    assert sorted(calls) == sorted(
        [
            "Risk It: production health check failing",
            "Risk It: production health recovered",
            "Risk It: production SLO alert",
            "Risk It: production SLOs recovered",
            "Risk It: production SLO conditions changed",
        ]
    )


def test_the_url_value_is_never_echoed():
    # Naming the secret in a message is fine; EXPANDING it in output is not.
    expansion = re.compile(r"\$\{?NOTIFY_WEBHOOK_URL")
    for line in WF.read_text(encoding="utf-8").splitlines():
        if re.search(r"\b(echo|printf)\b", line):
            assert not expansion.search(line), line


def _function_source() -> str:
    run = _steps()["Sync the rolling SLO tracking issue"]["run"]
    m = re.search(r"notify_owner\(\) \{.*?\n\s*\}\n", run, re.S)
    assert m, "notify_owner function not found"
    return m.group(0)


def _run(tmp_path, url: str | None, curl_exit: int) -> subprocess.CompletedProcess:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    log = tmp_path / "curl.log"
    (bindir / "curl").write_text(
        f'#!/usr/bin/env bash\necho "$@" >> {log}\nexit {curl_exit}\n', encoding="utf-8"
    )
    (bindir / "curl").chmod(0o755)
    env = {"PATH": f"{bindir}:{os.environ['PATH']}"}
    if url is not None:
        env["NOTIFY_WEBHOOK_URL"] = url
    script = (
        "set -Eeuo pipefail\n" + _function_source() + 'notify_owner "Title X" "Body Y"\necho done\n'
    )
    return subprocess.run(
        ["bash", "-c", script], env=env, capture_output=True, text=True, timeout=30
    )


def test_unset_secret_is_a_silent_no_op(tmp_path):
    cp = _run(tmp_path, None, 0)
    assert cp.returncode == 0 and cp.stdout.strip() == "done"
    assert not (tmp_path / "curl.log").exists()


def test_a_push_never_prints_the_url_and_a_failure_is_only_a_warning(tmp_path):
    url = "https://ntfy.sh/private-topic-for-tests"
    ok = _run(tmp_path, url, 0)
    assert ok.returncode == 0 and "owner push sent: Title X" in ok.stdout
    assert "private-topic" not in ok.stdout + ok.stderr
    second = tmp_path / "second"
    second.mkdir()
    fail = _run(second, url, 22)
    assert fail.returncode == 0
    assert "::warning title=Owner push failed::" in fail.stdout
    assert "private-topic" not in fail.stdout + fail.stderr


def test_a_non_https_url_is_ignored(tmp_path):
    cp = _run(tmp_path, "http://ntfy.sh/topic", 0)
    assert cp.returncode == 0
    assert not (tmp_path / "curl.log").exists()
