"""Script-level regression tests for the intel-refresh workflow's
embedded decision logic.

The workflow can't run in CI, but its two decision points are plain
Python heredocs — so we extract them from the YAML and execute them
against fixture payloads.  Pins the round-3 fix: a 409 from a
SINGLE-league run must not be adopted as the all-league run, and the
poll must never accept a completed non-all result.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

WORKFLOW_PATH = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "intel-refresh.yml"


def _steps() -> dict[str, str]:
    doc = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    return {
        step.get("name"): step.get("run", "")
        for step in doc["jobs"]["refresh"]["steps"]
        if isinstance(step, dict)
    }


def _extract_heredocs(run_text: str) -> list[str]:
    """Python sources embedded as ``<<'PY'`` heredocs, in order."""
    lines = run_text.split("\n")
    blocks: list[str] = []
    i = 0
    while i < len(lines):
        if "<<'PY'" in lines[i]:
            j = i + 1
            block: list[str] = []
            while j < len(lines) and lines[j].strip() != "PY":
                block.append(lines[j])
                j += 1
            blocks.append("\n".join(block))
            i = j
        i += 1
    return blocks


def _run_snippet(source: str, payload: dict, tmp_path: Path) -> subprocess.CompletedProcess:
    body = tmp_path / "body.json"
    body.write_text(json.dumps(payload), encoding="utf-8")
    return subprocess.run(
        [sys.executable, "-", str(body)],
        input=source,
        capture_output=True,
        text=True,
        timeout=30,
    )


@pytest.fixture(scope="module")
def poll_script() -> str:
    blocks = _extract_heredocs(_steps()["Poll refresh status"])
    assert len(blocks) == 1, "poll step should embed exactly one python heredoc"
    return blocks[0]


@pytest.fixture(scope="module")
def trigger_script() -> str:
    blocks = _extract_heredocs(_steps()["Trigger intel refresh"])
    assert len(blocks) == 1, "trigger step should embed exactly one python heredoc"
    return blocks[0]


def _all_result(errors: list | None = None) -> dict:
    return {
        "isRunning": False,
        "lastError": ("boom" if errors else None),
        "lastResult": {
            "mode": "all",
            "leagues": [
                {"leagueKey": "dynasty_main", "callsUsed": 10},
                {"leagueKey": "dynasty_new", "callsUsed": 12},
            ],
            "errors": errors or [],
        },
    }


class TestPollDecision:
    def test_running_keeps_polling(self, poll_script, tmp_path):
        proc = _run_snippet(poll_script, {"isRunning": True, "startedAt": "x"}, tmp_path)
        assert proc.returncode == 2

    def test_error_hard_fails(self, poll_script, tmp_path):
        proc = _run_snippet(
            poll_script,
            {"isRunning": False, "lastError": "dynasty_new: exploded", "lastResult": {}},
            tmp_path,
        )
        assert proc.returncode == 1

    def test_completed_single_league_run_is_not_accepted(self, poll_script, tmp_path):
        # THE round-3 regression: a session-triggered single-league
        # refresh finishing must not satisfy the all-league cron.
        proc = _run_snippet(
            poll_script,
            {
                "isRunning": False,
                "lastError": None,
                "lastResult": {"leagueKey": "dynasty_main", "callsUsed": 10},
            },
            tmp_path,
        )
        assert proc.returncode == 2  # keep polling, not success

    def test_completed_all_run_succeeds(self, poll_script, tmp_path):
        proc = _run_snippet(poll_script, _all_result(), tmp_path)
        assert proc.returncode == 0
        assert "dynasty_main" in proc.stdout
        assert "dynasty_new" in proc.stdout

    def test_all_run_with_per_league_errors_fails(self, poll_script, tmp_path):
        payload = _all_result(errors=[{"leagueKey": "dynasty_new", "error": "seed failed"}])
        payload["lastError"] = None  # errors surfaced via the result block alone
        proc = _run_snippet(poll_script, payload, tmp_path)
        assert proc.returncode == 1

    def test_no_result_keeps_polling(self, poll_script, tmp_path):
        proc = _run_snippet(
            poll_script, {"isRunning": False, "lastError": None, "lastResult": None}, tmp_path
        )
        assert proc.returncode == 2


class TestTriggerDecision:
    def test_prints_active_run_league_key(self, trigger_script, tmp_path):
        proc = _run_snippet(trigger_script, {"status": {"leagueKey": "all"}}, tmp_path)
        assert proc.returncode == 0
        assert proc.stdout.strip() == "all"

        proc = _run_snippet(trigger_script, {"status": {"leagueKey": "dynasty_main"}}, tmp_path)
        assert proc.stdout.strip() == "dynasty_main"

    def test_tolerates_garbage_body(self, trigger_script, tmp_path):
        body = tmp_path / "garbage.json"
        body.write_text("not json", encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, "-", str(body)],
            input=trigger_script,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert proc.returncode == 0
        assert proc.stdout.strip() == ""

    def test_trigger_step_only_adopts_all_league_runs(self):
        run_text = _steps()["Trigger intel refresh"]
        # The 409 branch must gate adoption on the active run being
        # all-league, and retry (bounded) otherwise.
        assert '"${active}" == "all"' in run_text
        assert "seq 1 10" in run_text
        assert "sleep 30" in run_text
        # The old unconditional 409-accept must be gone.
        assert '"${code}" != "202" && "${code}" != "409"' not in run_text
