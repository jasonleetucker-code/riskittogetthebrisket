"""Background jobs: bounded, owner-scoped, failures recorded, restarts honest."""

from __future__ import annotations

import pytest

from src.dfs import jobs


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DFS_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(jobs, "_recovered", True)
    yield
    jobs.wait_idle()


@jobs.register("test_ok")
def _ok(owner, params):
    return {"owner": owner, "echo": params["x"]}


@jobs.register("test_boom")
def _boom(owner, params):
    raise jobs.JobError("EXPECTED", "this job fails on purpose")


def test_a_job_runs_and_its_result_is_readable_only_by_its_owner():
    j = jobs.submit("o", "test_ok", {"x": 3})
    assert j["state"] in ("queued", "running", "done")
    jobs.wait_idle()
    done = jobs.get("o", j["jobId"])
    assert done["state"] == "done" and done["result"] == {"owner": "o", "echo": 3}
    assert jobs.get("someone_else", j["jobId"]) is None


def test_a_failing_job_is_recorded_not_raised():
    j = jobs.submit("o", "test_boom", {})
    jobs.wait_idle()
    got = jobs.get("o", j["jobId"])
    assert got["state"] == "failed" and got["error"].startswith("EXPECTED:")


def test_queue_is_bounded_and_unknown_kinds_refused(monkeypatch):
    with pytest.raises(jobs.JobError) as e:
        jobs.submit("o", "nope", {})
    assert e.value.code == "UNKNOWN_JOB_KIND"
    monkeypatch.setattr(jobs, "MAX_QUEUED", 0)
    with pytest.raises(jobs.JobError) as e:
        jobs.submit("o", "test_ok", {"x": 1})
    assert e.value.code == "QUEUE_FULL"


def test_jobs_left_running_by_a_previous_process_are_marked_interrupted(monkeypatch):
    with jobs._connect() as conn:
        conn.execute(
            "INSERT INTO dfs_jobs (id, owner, kind, state, created_at, params) VALUES (?,?,?,?,?,?)",
            ("job_old", "o", "test_ok", "running", "2026-09-30T00:00:00+00:00", "{}"),
        )
    monkeypatch.setattr(jobs, "_recovered", False)
    jobs._recover()
    old = jobs.get("o", "job_old")
    assert old["state"] == "interrupted" and "restarted" in old["error"]
