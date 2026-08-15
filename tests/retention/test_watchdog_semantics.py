"""The scheduled retention watchdog must actually be able to fail.

The intended invariant, stated once:

    scheduled watchdog + unhealthy required artifact = FAILED CHECK

not a green informational report.

This is the defect owner review caught.  The first version of
``.github/workflows/retention-health.yml`` resolved ``REQUIRE`` from
``inputs.require``, which is **empty on a ``schedule`` event**, so the
nightly run silently fell into report-only mode and would have stayed
green with all eight retention streams dead.  A watchdog that cannot
fail is the same ships-then-stops-then-stays-quiet silence the C1-RET
tranche exists to repair, wearing a green tick.

These tests execute the probe script end-to-end against a temporary data
directory, so the rule is pinned by BEHAVIOUR rather than by a regex
over YAML.  The structural checks at the bottom exist only to stop a
future refactor moving the decision back into an expression where these
tests could not see it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PROBE = REPO / "deploy" / "diagnostics" / "retention_health_probe.sh"
WORKFLOW = REPO / ".github" / "workflows" / "retention-health.yml"

EXIT_OK = 0
EXIT_CANNOT_RUN = 1
EXIT_UNHEALTHY = 2


def _run(data_dir: Path, *, event_name: str = "", require: str = "") -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.update(
        {
            "APP_DIR": str(REPO),
            "PYTHON_BIN": sys.executable,
            "DATA_DIR": str(data_dir),
            "EVENT_NAME": event_name,
            "REQUIRE": require,
        }
    )
    return subprocess.run(
        ["bash", str(PROBE)],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


@pytest.fixture
def empty_data(tmp_path):
    """A host where nothing has been retained — all eight streams missing."""
    d = tmp_path / "data"
    d.mkdir()
    return d


@pytest.fixture
def one_healthy_stream(tmp_path):
    """A host where exactly C1-RET-01 is healthy and the rest are not."""
    d = tmp_path / "data"
    (d / "faab").mkdir(parents=True)
    fresh = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    (d / "faab" / "crowd_history_dynasty_main.json").write_text(
        json.dumps({"updatedAt": fresh, "rows": [{"id": "1"}]}), encoding="utf-8"
    )
    return d


# ── the invariant ────────────────────────────────────────────────────


def test_a_scheduled_run_fails_when_streams_are_unhealthy(empty_data):
    """THE test.  Before the fix this returned 0."""
    result = _run(empty_data, event_name="schedule")

    assert result.returncode == EXIT_UNHEALTHY, (
        "the scheduled watchdog reported success with every retention "
        f"stream missing\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "requiring every retention stream" in result.stdout


def test_a_scheduled_run_requires_everything_even_with_an_empty_require(empty_data):
    """``inputs.require`` is empty on a schedule event — that is exactly
    how the defect arose, so it is pinned explicitly."""
    result = _run(empty_data, event_name="schedule", require="")

    assert result.returncode == EXIT_UNHEALTHY


def test_a_scheduled_run_cannot_be_narrowed_to_one_stream(empty_data, one_healthy_stream):
    """A narrowing REQUIRE must not survive into a scheduled run, or the
    watchdog could be quietly scoped down to a stream that is fine."""
    result = _run(one_healthy_stream, event_name="schedule", require="C1-RET-01")

    assert result.returncode == EXIT_UNHEALTHY
    assert "ignoring REQUIRE" in result.stdout


def test_the_watchdog_turns_green_when_everything_is_healthy(one_healthy_stream, monkeypatch):
    """The signal has to be reachable, or a permanently red job is a job
    nobody reads.  Proven on the one stream a temp dir can make healthy:
    a required stream that IS healthy passes."""
    result = _run(one_healthy_stream, event_name="workflow_dispatch", require="C1-RET-01")

    assert result.returncode == EXIT_OK, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"


# ── manual dispatch keeps its three modes ────────────────────────────


def test_manual_report_only_does_not_fail(empty_data):
    result = _run(empty_data, event_name="workflow_dispatch", require="")

    assert result.returncode == EXIT_OK
    assert "report only" in result.stdout


def test_manual_all_requires_every_stream(empty_data):
    result = _run(empty_data, event_name="workflow_dispatch", require="ALL")

    assert result.returncode == EXIT_UNHEALTHY


def test_manual_selected_streams_are_honoured(one_healthy_stream):
    healthy = _run(one_healthy_stream, event_name="workflow_dispatch", require="C1-RET-01")
    unhealthy = _run(one_healthy_stream, event_name="workflow_dispatch", require="C1-RET-04")

    assert healthy.returncode == EXIT_OK
    assert unhealthy.returncode == EXIT_UNHEALTHY


def test_an_unknown_event_defaults_to_the_manual_semantics(empty_data):
    """Only ``schedule`` forces ALL.  A push or a rerun of a dispatch
    must not silently become a hard gate."""
    result = _run(empty_data, event_name="push", require="")

    assert result.returncode == EXIT_OK


# ── the probe cannot pass by failing to run ──────────────────────────


def test_a_missing_checker_is_an_error_not_a_pass(tmp_path, empty_data):
    """ "The check is not there yet" and "the check passed" must never
    look the same — that is the whole failure class."""
    bare = tmp_path / "deployed"
    bare.mkdir()
    env = dict(os.environ)
    env.update(
        {
            "APP_DIR": str(bare),
            "PYTHON_BIN": sys.executable,
            "DATA_DIR": str(empty_data),
            "EVENT_NAME": "schedule",
            "REQUIRE": "",
        }
    )
    result = subprocess.run(
        ["bash", str(PROBE)], env=env, capture_output=True, text=True, timeout=60
    )

    assert result.returncode == EXIT_CANNOT_RUN
    assert "absent on the deployed revision" in result.stdout


def test_a_missing_app_dir_is_an_error_not_a_pass(empty_data):
    env = dict(os.environ)
    env.update(
        {
            "APP_DIR": "/nonexistent/app/dir",
            "PYTHON_BIN": sys.executable,
            "DATA_DIR": str(empty_data),
            "EVENT_NAME": "schedule",
        }
    )
    result = subprocess.run(
        ["bash", str(PROBE)], env=env, capture_output=True, text=True, timeout=60
    )

    assert result.returncode == EXIT_CANNOT_RUN


# ── structural: the decision must stay where the tests can see it ────


def test_the_workflow_forwards_the_event_and_decides_nothing():
    """A future refactor that moves the schedule rule back into a YAML
    expression would put it beyond every test above.  This is the guard
    against that, and it is the ONLY structural assertion here."""
    text = WORKFLOW.read_text(encoding="utf-8")

    assert (
        "EVENT_NAME: ${{ github.event_name }}" in text
    ), "the workflow must forward the triggering event to the probe"
    assert "EVENT_NAME=$(printf %q" in text, "EVENT_NAME must reach the remote shell"
    # The workflow must not resolve the schedule case itself.
    assert (
        "github.event_name == 'schedule'" not in text
    ), "the schedule rule belongs in the probe script, where it is testable"


def test_the_probe_owns_the_schedule_rule():
    text = PROBE.read_text(encoding="utf-8")

    assert '"${EVENT_NAME}" == "schedule"' in text
    assert 'REQUIRE="ALL"' in text


def test_the_workflow_does_not_mask_the_remote_exit_status():
    # Comments stripped: the header explains WHY there is no ``|| true``,
    # and the guard is about the executable half.
    code = "\n".join(
        line
        for line in WORKFLOW.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    )

    assert "|| true" not in code, "a masked exit status makes the watchdog unable to fail"
    assert "continue-on-error" not in code
