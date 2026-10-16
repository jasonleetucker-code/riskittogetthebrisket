"""The scheduled refresh's Draft Data sync must survive a curl transport failure.

The step runs under ``set -Eeuo pipefail`` and captured the status with a bare
``HTTP_CODE=$(curl ...)``.  When curl itself fails (DNS, connection reset,
timeout) the assignment carries curl's non-zero exit, ``set -e`` aborts the
step, and the refresh never reaches its own "keep existing workbook" warning.
This runs the real workflow step with a stub ``curl`` on PATH.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
_STEP = "Sync Draft Data from Google Sheet"

_STUB_CURL = """#!/usr/bin/env bash
: > stub_curl_was_called
out=""
while [ $# -gt 0 ]; do
  case "$1" in
    -o) out="$2"; shift 2 ;;
    *) shift ;;
  esac
done
if [ -n "$out" ] && [ -n "${STUB_BODY:-}" ]; then printf '%s' "$STUB_BODY" > "$out"; fi
printf '%s' "${STUB_CODE:-}"
exit "${STUB_EXIT:-0}"
"""


def _step_script() -> str:
    path = REPO / ".github" / "workflows" / "scheduled-refresh.yml"
    workflow = yaml.safe_load(path.read_text("utf-8"))
    for job in workflow["jobs"].values():
        for step in job.get("steps", []):
            if step.get("name") == _STEP:
                return step["run"]
    raise AssertionError(f"step {_STEP!r} not found")


def _bash() -> str:
    found = shutil.which("bash")
    if not found:
        pytest.skip("bash is not available")
    return found


def _run_step(
    tmp_path: Path, *, code: str, exit_code: int, body: str = ""
) -> subprocess.CompletedProcess:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "curl"
    stub.write_text(_STUB_CURL, encoding="utf-8", newline="\n")
    stub.chmod(0o755)
    (tmp_path / "CSVs").mkdir()
    (tmp_path / "CSVs" / "Draft Data.xlsx").write_text("EXISTING", encoding="utf-8")
    # $PWD, not the native path: a Windows "C:/..." entry would split on ":".
    script = 'export PATH="$PWD/bin:$PATH"\n' + _step_script()
    env = {**os.environ, "STUB_CODE": code, "STUB_EXIT": str(exit_code), "STUB_BODY": body}
    return subprocess.run(
        [_bash(), "-c", script],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def _assert_kept(tmp_path: Path, proc: subprocess.CompletedProcess) -> None:
    # The stub, never the network, answered.
    assert (tmp_path / "stub_curl_was_called").exists(), proc.stdout + proc.stderr
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "keeping existing workbook" in proc.stdout
    assert (tmp_path / "CSVs" / "Draft Data.xlsx").read_text("utf-8") == "EXISTING"
    assert not (tmp_path / "CSVs" / "Draft Data.xlsx.tmp").exists()


def test_a_curl_transport_failure_keeps_the_existing_workbook(tmp_path):
    # e.g. exit 6 "could not resolve host": curl writes "000" and fails.
    proc = _run_step(tmp_path, code="000", exit_code=6)
    _assert_kept(tmp_path, proc)
    assert "HTTP 000" in proc.stdout


def test_a_failure_after_a_200_header_is_not_treated_as_success(tmp_path):
    # e.g. exit 28 timeout mid-body: curl has already printed 200 and wrote a
    # partial file.  The status must be the fallback, not "200" or "200000".
    proc = _run_step(tmp_path, code="200", exit_code=28, body="partial")
    _assert_kept(tmp_path, proc)
    assert "HTTP 000" in proc.stdout


def test_a_non_200_status_still_keeps_the_existing_workbook(tmp_path):
    proc = _run_step(tmp_path, code="404", exit_code=0, body="not found")
    _assert_kept(tmp_path, proc)
    assert "HTTP 404" in proc.stdout


def test_a_suspiciously_small_200_still_keeps_the_existing_workbook(tmp_path):
    proc = _run_step(tmp_path, code="200", exit_code=0, body="tiny")
    _assert_kept(tmp_path, proc)
    assert "only 4 bytes" in proc.stdout
