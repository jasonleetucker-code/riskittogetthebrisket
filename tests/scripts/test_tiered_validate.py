"""scripts/tiered_validate.sh must never exit early and read as green.

Regression for 2026-09-24: L1 listed the changed paths, then died silently.
``add_dir`` ended in ``[[ -d ... ]] && ...``, which returns 1 for a changed
file directly under ``tests/`` (``tests/archive_fixtures.py``), and ``set -e``
killed the run with no message.  Separately, on Windows every path arrived
with a trailing ``\\r``, so exact ``case`` patterns (``src/api/data_contract.py``)
never matched, and a crash in change detection inside ``< <(...)`` could not
abort the run at all.

The script is driven through a ``python`` shim: change detection and pytest
are faked, everything the script decides about them is real.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "tiered_validate.sh"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="bash unavailable")

_SHIM = r"""#!/usr/bin/env bash
if [[ "$1" == "scripts/ci_change_scope.py" ]]; then
  [[ -n "${SHIM_SCOPE_FAIL:-}" ]] && { echo "boom" >&2; exit 3; }
  if [[ " $* " == *" --paths-only "* ]]; then
    printf 'tests/archive_fixtures.py\r\nsrc/api/data_contract.py\r\n'
  else
    printf 'python=True frontend=False high_risk=True\r\n'
  fi
  exit 0
fi
if [[ "$1" == "-m" && "$2" == "pytest" ]]; then
  echo "PYTEST_ARGS: ${*:3}"
  [[ -n "${SHIM_PYTEST_FAIL:-}" ]] && exit 1
  exit 0
fi
exec "$REAL_PYTHON" "$@"
"""


def _run(tmp_path: Path, **env_extra: str) -> subprocess.CompletedProcess[str]:
    shim_dir = tmp_path / "shim"
    shim_dir.mkdir(exist_ok=True)
    shim = shim_dir / "python"
    shim.write_text(_SHIM, encoding="utf-8", newline="\n")
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC)
    env = {
        **os.environ,
        "PATH": f"{shim_dir}{os.pathsep}{os.environ.get('PATH', '')}",
        "REAL_PYTHON": sys.executable,
        **env_extra,
    }
    return subprocess.run(
        ["bash", str(SCRIPT), "l1"],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_crlf_paths_and_top_level_test_helpers_reach_their_suites(tmp_path):
    res = _run(tmp_path)
    assert res.returncode == 0, res.stdout + res.stderr
    args = next(line for line in res.stdout.splitlines() if line.startswith("PYTEST_ARGS:"))
    # data_contract.py's named mapping survives the CRLF.
    assert "tests/canonical" in args and "tests/api" in args
    # A shared helper under tests/ widens to its importers instead of aborting.
    assert "tests/archive_fixtures.py" not in args
    assert "L1: GREEN" in res.stdout


def test_failing_pytest_fails_the_run_loudly(tmp_path):
    res = _run(tmp_path, SHIM_PYTEST_FAIL="1")
    assert res.returncode != 0
    assert "L1: GREEN" not in res.stdout
    assert "tiered_validate: FAILED" in res.stderr


def test_change_detection_failure_cannot_read_as_no_changes(tmp_path):
    res = _run(tmp_path, SHIM_SCOPE_FAIL="1")
    assert res.returncode != 0
    assert "L1: GREEN" not in res.stdout
    assert "tiered_validate: FAILED" in res.stderr
