"""The scheduled refresh's browser fetchers must run on an image Playwright supports.

On 2026-10-25 the floating ``ubuntu-latest`` label moved to ubuntu-26.04
between the 11:59Z run (ubuntu-24.04, browser fetchers fine) and the 16:49Z run.
The locked Playwright answered ``does not support chromium on ubuntu26.04-x64``,
the old ``python -m playwright install chromium 2>/dev/null || true`` swallowed
it, every browser fetch (KTC, IDP Trade Calculator, DraftSharks) then failed, the
orchestrator restored last-good CSVs and declined to stamp them (correctly), and
the run still finished green.  The browser-driven boards stopped advancing and
nothing said why.

Two properties are pinned here, and the second is why a green run could hide it:

1. the refresh job runs on a PINNED image the locked Playwright can install on;
2. a failed browser install is still non-fatal (the HTTP-only fetchers must run)
   but is no longer silent: stderr is kept and a ``::warning`` annotation names it.

Moving the image is a deliberate act, together with a Playwright bump verified on
that image.  Update ``_PLAYWRIGHT_SUPPORTED_IMAGES`` in the same change.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
WORKFLOW = REPO / ".github" / "workflows" / "scheduled-refresh.yml"
_JOB = "refresh"
_INSTALL_STEP = "Install dependencies"

# Images the locked Playwright (requirements.lock.txt) can install Chromium on.
# ubuntu-26.04 is deliberately absent: the locked 1.58.0 reports it unsupported.
_PLAYWRIGHT_SUPPORTED_IMAGES = frozenset({"ubuntu-22.04", "ubuntu-24.04"})

_INSTALL_BLOCK = re.compile(
    r"if ! python -m playwright install chromium; then\n.*?\n\s*fi\b",
    re.DOTALL,
)

_STUB_PYTHON = """#!/usr/bin/env bash
: > stub_python_was_called
echo "stub playwright: $*" >&2
exit "${STUB_EXIT:-0}"
"""


def _job() -> dict:
    workflow = yaml.safe_load(WORKFLOW.read_text("utf-8"))
    return workflow["jobs"][_JOB]


def _install_script() -> str:
    for step in _job()["steps"]:
        if step.get("name") == _INSTALL_STEP:
            return step["run"]
    raise AssertionError(f"step {_INSTALL_STEP!r} not found")


def _code_lines(script: str) -> list[str]:
    return [ln for ln in script.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]


def _bash() -> str:
    found = shutil.which("bash")
    if not found:
        pytest.skip("bash is not available")
    return found


def test_refresh_job_runs_on_a_pinned_playwright_supported_image():
    runs_on = _job()["runs-on"]
    assert isinstance(runs_on, str)
    assert runs_on != "ubuntu-latest", (
        "ubuntu-latest floats; it moved to 26.04 and stopped every browser fetcher "
        "behind a green run (2026-10-25)"
    )
    assert runs_on in _PLAYWRIGHT_SUPPORTED_IMAGES, (
        f"{runs_on!r} is not an image the locked Playwright is known to support; "
        "bump Playwright and verify it on that image, then update this allowlist"
    )


def test_browser_install_failure_is_not_swallowed():
    code = "\n".join(_code_lines(_install_script()))
    assert "playwright install chromium" in code
    assert "2>/dev/null" not in code, "stderr is the only record of WHY the install failed"
    assert "|| true" not in code, "a masked exit status hides a dead browser path"
    assert _INSTALL_BLOCK.search(_install_script()), "install must be guarded by `if ! ...`"
    assert "::warning title=Playwright chromium install failed::" in code


def _run_install_block(tmp_path: Path, *, exit_code: int) -> subprocess.CompletedProcess:
    match = _INSTALL_BLOCK.search(_install_script())
    assert match, "install block not found"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "python"
    stub.write_text(_STUB_PYTHON, encoding="utf-8", newline="\n")
    stub.chmod(0o755)
    # $PWD, not the native path: a Windows "C:/..." entry would split on ":".
    script = 'export PATH="$PWD/bin:$PATH"\nset -Eeuo pipefail\n' + match.group(0) + "\n"
    return subprocess.run(
        [_bash(), "-c", script],
        cwd=tmp_path,
        env={**os.environ, "STUB_EXIT": str(exit_code)},
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_a_failed_browser_install_is_non_fatal_but_loud(tmp_path):
    proc = _run_install_block(tmp_path, exit_code=1)
    assert (tmp_path / "stub_python_was_called").exists(), proc.stdout + proc.stderr
    # Non-fatal: the HTTP-only fetchers still have to run.
    assert proc.returncode == 0, proc.stdout + proc.stderr
    # Loud: an annotation, and the installer's own stderr is not discarded.
    assert "::warning title=Playwright chromium install failed::" in proc.stdout
    assert "stub playwright: -m playwright install chromium" in proc.stderr


def test_a_successful_browser_install_raises_no_warning(tmp_path):
    proc = _run_install_block(tmp_path, exit_code=0)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "::warning" not in proc.stdout
