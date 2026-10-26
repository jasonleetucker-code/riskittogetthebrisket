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

Follow-up signals (same incident; SIGNAL ONLY, no failure semantics changed):

3. ``draftsharks-diagnostic.yml`` drives the same browser, so it is pinned the same
   way and its install failure is named; it stays FATAL there (that job exists to
   drive a real browser);
4. ``stamp_if_present`` no longer skips silently: a CSV that was not rewritten
   raises ``::warning title=Source not stamped::``, and the skip, the stamp and the
   exit status are exactly what they were;
5. a report step after the fetchers lists every browser-dependent CSV that was
   kept rather than rewritten and cannot fail the job.  The browser-source list
   is held in ONE place (``scripts/report_browser_source_status.py``), with a
   drift guard against a new Playwright fetcher being wired in without it.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from scripts import report_browser_source_status as rbs

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


def _run_install_block(
    tmp_path: Path, *, exit_code: int, block: str | None = None
) -> subprocess.CompletedProcess:
    if block is None:
        found = _INSTALL_BLOCK.search(_install_script())
        assert found, "install block not found"
        block = found.group(0)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "python"
    stub.write_text(_STUB_PYTHON, encoding="utf-8", newline="\n")
    stub.chmod(0o755)
    # $PWD, not the native path: a Windows "C:/..." entry would split on ":".
    script = 'export PATH="$PWD/bin:$PATH"\nset -Eeuo pipefail\n' + block + "\n"
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


# ── draftsharks-diagnostic.yml: same browser, same pin, failure named but still fatal ──

DIAGNOSTIC = REPO / ".github" / "workflows" / "draftsharks-diagnostic.yml"
_DIAG_INSTALL_BLOCK = re.compile(
    r"if ! python -m playwright install chromium; then\n.*?\n\s*fi\b",
    re.DOTALL,
)


def _diag_job() -> dict:
    return yaml.safe_load(DIAGNOSTIC.read_text("utf-8"))["jobs"]["probe"]


def _diag_install_script() -> str:
    for step in _diag_job()["steps"]:
        if step.get("name") == _INSTALL_STEP:
            return step["run"]
    raise AssertionError(f"step {_INSTALL_STEP!r} not found in the diagnostic")


def test_diagnostic_runs_on_a_pinned_playwright_supported_image():
    runs_on = _diag_job()["runs-on"]
    assert (
        runs_on != "ubuntu-latest"
    ), "ubuntu-latest floats; the diagnostic drives the same browser"
    assert (
        runs_on in _PLAYWRIGHT_SUPPORTED_IMAGES
    ), f"{runs_on!r} is not an image the locked Playwright is known to support"


def test_diagnostic_install_failure_is_named_and_does_not_mask_the_status():
    script = _diag_install_script()
    code = "\n".join(_code_lines(script))
    assert "2>/dev/null" not in code
    assert "|| true" not in code
    assert _DIAG_INSTALL_BLOCK.search(script), "install must be guarded by `if ! ...`"
    assert "::error title=Playwright chromium install failed::" in code


def test_diagnostic_install_failure_stays_fatal_and_loud(tmp_path):
    block = _DIAG_INSTALL_BLOCK.search(_diag_install_script()).group(0)
    proc = _run_install_block(tmp_path, exit_code=1, block=block)
    assert (tmp_path / "stub_python_was_called").exists(), proc.stdout + proc.stderr
    # Unlike the data pipeline, this job exists to drive a real browser.
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "::error title=Playwright chromium install failed::" in proc.stdout
    assert "stub playwright: -m playwright install chromium" in proc.stderr


def test_diagnostic_successful_install_is_silent(tmp_path):
    block = _DIAG_INSTALL_BLOCK.search(_diag_install_script()).group(0)
    proc = _run_install_block(tmp_path, exit_code=0, block=block)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "::error" not in proc.stdout and "::warning" not in proc.stdout


# ── stamp_if_present: the silent skip is now a named warning, nothing else changed ──

_SCRAPER_STEP = "Run scraper"
_NOT_STAMPED = "::warning title=Source not stamped::"
_BEFORE = 1_700_000_000
_MARKER = 1_700_000_100
_AFTER = 1_700_000_200


def _scraper_script() -> str:
    for step in _job()["steps"]:
        if step.get("name") == _SCRAPER_STEP:
            return step["run"]
    raise AssertionError(f"step {_SCRAPER_STEP!r} not found")


def _stamp_helpers() -> str:
    """``was_preserved`` + ``stamp_if_present`` exactly as the workflow defines them."""
    script = _scraper_script()
    start = script.index('MANIFEST="exports/latest/manifest.json"')
    end = script.index("\nstamp_if_present ktc ", start)
    return script[start:end]


def _run_stamp(
    tmp_path: Path,
    *,
    csv_mtime: int | None,
    rows: int,
    min_lines: int = 100,
    manifest_preserved: list[str] | None = None,
) -> tuple[subprocess.CompletedProcess, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    shim = bin_dir / "python3"
    shim.write_text(
        f'#!/usr/bin/env bash\nexec "{Path(sys.executable).as_posix()}" "$@"\n',
        encoding="utf-8",
        newline="\n",
    )
    shim.chmod(0o755)

    marker = tmp_path / "marker"
    marker.write_text("", encoding="utf-8")
    os.utime(marker, (_MARKER, _MARKER))
    csv = tmp_path / "CSVs" / "site_raw" / "ktc.csv"
    if csv_mtime is not None:
        csv.parent.mkdir(parents=True)
        csv.write_text("name,value\n" * rows, encoding="utf-8", newline="\n")
        os.utime(csv, (csv_mtime, csv_mtime))
    if manifest_preserved is not None:
        manifest = tmp_path / "exports" / "latest" / "manifest.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(
            '{"siteRawPreserved": ' + str(manifest_preserved).replace("'", '"') + "}",
            encoding="utf-8",
        )
    script = (
        'export PATH="$PWD/bin:$PATH"\n'
        "set -Eeuo pipefail\n"
        "mkdir -p data/scrape_state\n"
        'SCRAPE_START_MARKER="$PWD/marker"\n'
        + _stamp_helpers()
        + f"\nstamp_if_present ktc CSVs/site_raw/ktc.csv {min_lines}\n"
    )
    proc = subprocess.run(
        [_bash(), "-c", script],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return proc, tmp_path / "data" / "scrape_state" / "ktc_last_success"


def test_a_rewritten_csv_is_stamped_without_any_warning(tmp_path):
    proc, stamp = _run_stamp(tmp_path, csv_mtime=_AFTER, rows=150)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert stamp.exists() and stamp.read_text().strip().isdigit()
    assert "::warning" not in proc.stdout


def test_a_csv_that_was_not_rewritten_is_named_and_not_stamped(tmp_path):
    proc, stamp = _run_stamp(tmp_path, csv_mtime=_BEFORE, rows=150)
    assert proc.returncode == 0, proc.stdout + proc.stderr  # exit status unchanged
    assert not stamp.exists()  # the skip itself is unchanged
    expected = f"{_NOT_STAMPED}ktc: CSV not rewritten this run (kept previous file)"
    assert expected in proc.stdout, proc.stdout


def test_a_rewritten_but_too_short_csv_is_named_and_not_stamped(tmp_path):
    proc, stamp = _run_stamp(tmp_path, csv_mtime=_AFTER, rows=7)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert not stamp.exists()
    assert f"{_NOT_STAMPED}ktc: CSV rewritten but only 7 lines (minimum 100)" in proc.stdout
    assert "kept previous file" not in proc.stdout, "that claim would be false here"


def test_a_missing_csv_is_named_and_not_stamped(tmp_path):
    proc, stamp = _run_stamp(tmp_path, csv_mtime=None, rows=0)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert not stamp.exists()
    assert f"{_NOT_STAMPED}ktc: CSV missing" in proc.stdout
    assert "kept previous file" not in proc.stdout


def test_a_scraper_restored_csv_keeps_its_existing_warning_and_gains_no_second_one(tmp_path):
    # Current mtime (the restore pass rewrites the file) - only the manifest knows.
    proc, stamp = _run_stamp(tmp_path, csv_mtime=_AFTER, rows=150, manifest_preserved=["ktc.csv"])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert not stamp.exists()
    assert (
        "::warning title=ktc not refreshed::Restored last-good board; NOT stamping" in proc.stdout
    )
    assert _NOT_STAMPED not in proc.stdout


# ── the report step: placed after the fetchers, can never fail the job ──


def _steps() -> list[dict]:
    return _job()["steps"]


def _report_step() -> dict:
    for step in _steps():
        if "report_browser_source_status.py" in step.get("run", ""):
            return step
    raise AssertionError("no step runs scripts/report_browser_source_status.py")


def test_report_step_follows_the_scraper_step_and_cannot_fail_the_job():
    names = [s.get("name") for s in _steps()]
    report = _report_step()
    assert names.index(report["name"]) == names.index(_SCRAPER_STEP) + 1
    assert report.get("continue-on-error") is True
    # Runs when the scraper step FAILED too (that is when it matters most) but not
    # when the scraper step was skipped on purpose or the run was cancelled.
    condition = report["if"]
    assert "!cancelled()" in condition
    assert "inputs.skip_scrape != true" in condition
    assert _steps()[names.index(_SCRAPER_STEP)]["if"] == "${{ inputs.skip_scrape != true }}"


def test_report_step_reads_the_marker_the_scraper_step_creates():
    assert 'SCRAPE_START_MARKER="$RUNNER_TEMP/scrape_start.marker"' in _scraper_script()
    assert '--marker "$RUNNER_TEMP/scrape_start.marker"' in _report_step()["run"]


def test_report_step_adds_no_failure_semantics():
    run = _report_step()["run"]
    assert "exit 1" not in run
    # The reporter itself exits 0 whatever happens (pinned in
    # tests/scripts/test_report_browser_source_status.py); nothing here may wrap it
    # into a gate.
    assert "set -e" not in run.replace("set +e", "")


def test_browser_source_list_is_complete_and_wired():
    """Drift guard: a Playwright fetcher added to the refresh must join the list."""
    script = _scraper_script()
    invoked = set(re.findall(r"\bpython (scripts/[\w.]+\.py)\b", script))
    assert 'python "Dynasty Scraper.py"' in script
    invoked.add("Dynasty Scraper.py")

    drives_browser = re.compile(r"^\s*(?:from|import)\s+playwright\b", re.MULTILINE)
    browser_entry_points = {
        rel for rel in invoked if drives_browser.search((REPO / rel).read_text("utf-8"))
    }
    declared = {source.fetcher for source in rbs.BROWSER_SOURCES}
    assert browser_entry_points == declared, (
        "the refresh invokes a Playwright-driven entry point that is not in "
        "scripts/report_browser_source_status.py::BROWSER_SOURCES (or the reverse); "
        "a browser source missing from the list is the silent failure this report exists for"
    )

    for source in rbs.BROWSER_SOURCES:
        assert (REPO / "CSVs" / "site_raw" / source.csv).is_file(), source.csv
        if source.scraper_owned:
            pattern = rf"^stamp_if_present {re.escape(source.name)}\s+CSVs/site_raw/{re.escape(source.csv)}\b"
            assert re.search(
                pattern, script, re.MULTILINE
            ), f"{source.name} is listed as scraper-owned but is not stamped by stamp_if_present"
