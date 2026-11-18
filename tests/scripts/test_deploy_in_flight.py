"""``scripts/deploy_in_flight.py`` — the on-box workflows' deploy guard.

The measured case (2026-11-18): two ``deploy.yml`` runs GitHub created but never
started (2026-08-19 and 2026-11-11) blocked every on-box Signals run.
"""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts import deploy_in_flight as guard

NOW = datetime(2026, 11, 18, 10, 13, tzinfo=timezone.utc)
REPO = Path(__file__).resolve().parents[2]


def _run(run_id: int, status: str, created: str | None) -> dict:
    return {
        "id": run_id,
        "status": status,
        "created_at": created,
        "event": "push",
        "head_sha": "a" * 40,
    }


def test_the_two_measured_orphans_no_longer_block() -> None:
    runs = [
        _run(43096180672, "queued", "2026-11-11T20:27:38Z"),
        _run(32212914036, "queued", "2026-08-19T03:39:22Z"),
    ]
    busy, orphaned = guard.classify(runs, NOW)
    assert busy == []
    assert [r["id"] for r in orphaned] == [43096180672, 32212914036]


def test_an_in_progress_deploy_blocks_whatever_its_age() -> None:
    busy, orphaned = guard.classify([_run(1, "in_progress", "2026-08-01T00:00:00Z")], NOW)
    assert [r["id"] for r in busy] == [1]
    assert orphaned == []


@pytest.mark.parametrize("status", ["queued", "waiting", "pending", "requested"])
def test_a_freshly_queued_deploy_blocks(status: str) -> None:
    busy, _ = guard.classify([_run(2, status, "2026-11-18T10:12:00Z")], NOW)
    assert [r["id"] for r in busy] == [2]


def test_the_orphan_boundary_is_inclusive_at_six_hours() -> None:
    just_under = _run(3, "queued", "2026-11-18T04:13:01Z")
    exactly = _run(4, "queued", "2026-11-18T04:13:00Z")
    busy, orphaned = guard.classify([just_under, exactly], NOW)
    assert [r["id"] for r in busy] == [3]
    assert [r["id"] for r in orphaned] == [4]


@pytest.mark.parametrize("created", [None, "", "not-a-date"])
def test_an_unreadable_age_fails_closed(created) -> None:
    busy, orphaned = guard.classify([_run(5, "queued", created)], NOW)
    assert [r["id"] for r in busy] == [5]
    assert orphaned == []


def test_completed_runs_and_duplicates_are_ignored() -> None:
    runs = [
        _run(6, "completed", "2026-11-18T10:00:00Z"),
        _run(7, "queued", "2026-11-18T10:00:00Z"),
        _run(7, "queued", "2026-11-18T10:00:00Z"),
    ]
    busy, _ = guard.classify(runs, NOW)
    assert [r["id"] for r in busy] == [7]


def test_an_unreadable_run_list_exits_2_never_clear(monkeypatch, capsys) -> None:
    def boom(*_a, **_k):
        raise subprocess.CalledProcessError(1, "gh")

    monkeypatch.setattr(guard.subprocess, "run", boom)
    assert guard.main(["--repo", "o/r"]) == 2
    assert "Deploy state unreadable" in capsys.readouterr().out


def test_exit_codes_for_clear_and_busy(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        guard,
        "_fetch_active_runs",
        lambda repo: [_run(8, "queued", "2026-08-19T03:39:22Z")],
    )
    assert guard.main(["--repo", "o/r"]) == 0
    out = capsys.readouterr().out
    assert "Orphaned deploy run" in out and "run 8" in out

    monkeypatch.setattr(
        guard, "_fetch_active_runs", lambda repo: [_run(9, "in_progress", "2026-11-18T10:00:00Z")]
    )
    assert guard.main(["--repo", "o/r"]) == 1
    assert "Production deploy in flight" in capsys.readouterr().out


@pytest.mark.parametrize("workflow", ["signals-health-probe.yml", "signals-onbox-verification.yml"])
def test_both_on_box_workflows_use_the_one_guard(workflow: str) -> None:
    text = (REPO / ".github" / "workflows" / workflow).read_text(encoding="utf-8")
    assert "scripts/deploy_in_flight.py" in text
    assert "for status in in_progress queued waiting pending requested" not in text
