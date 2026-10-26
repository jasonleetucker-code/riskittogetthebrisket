"""``/api/health`` reports the DLF session the fetch timer actually uses.

Incident, 2026-10-26: health said ``dlf_session.json`` was 96.6 days old while
the timer had refreshed its jar that day.  Health read the bootstrap seed under
the app directory; the timer keeps the live jar in ``/var/lib/dlf-fetch``.

These tests drive the real endpoint with a STALE seed in the app directory and
a FRESH jar in the timer's work directory (``DLF_FETCH_WORK_DIR``), so a
regression to the app-dir path fails loudly instead of reading plausibly.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import server
from src.sources import dlf_session

DLF = "dlf_session.json"
DAY = 86400.0


def _write(path: Path, *, age_days: float) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}", encoding="utf-8")
    stamp = time.time() - age_days * DAY
    os.utime(path, (stamp, stamp))
    return path


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    """An isolated app dir (what health used to read) and timer work dir."""
    app = tmp_path / "app"
    work = tmp_path / "work"
    app.mkdir()
    work.mkdir()
    monkeypatch.setattr(server, "BASE_DIR", app)
    monkeypatch.setenv(dlf_session.DLF_FETCH_WORK_DIR_ENV, str(work))
    return app, work


def _session_cookies() -> dict:
    # 200 or 503 depending on scrape/contract state; the body is the same shape.
    return TestClient(server.app).get("/api/health").json()["session_cookies"]


def test_health_reads_the_timers_jar_not_the_stale_app_dir_seed(dirs):
    app, work = dirs
    _write(app / DLF, age_days=96.6)  # the bootstrap seed from the incident
    _write(work / DLF, age_days=0.1)  # the jar the timer refreshed today

    dlf = _session_cookies()[DLF]

    assert dlf["present"] is True
    assert dlf["autoRefresh"] is True
    assert dlf["ageDays"] < 1.0, f"health read the stale app-dir seed: {dlf}"
    assert dlf["daysRemaining"] > 13.0


def test_missing_timer_jar_reports_missing_even_when_the_seed_is_fresh(dirs):
    """No fallback to the app dir: a seed nothing maintains must not stand in
    for the jar.  Missing is missing -- never a 0-day-old file."""
    app, _work = dirs
    _write(app / DLF, age_days=0.0)

    dlf = _session_cookies()[DLF]

    assert dlf == {"present": False, "autoRefresh": True}
    assert "ageDays" not in dlf


def test_nonexistent_work_dir_reports_missing(tmp_path, monkeypatch):
    app = tmp_path / "app"
    app.mkdir()
    monkeypatch.setattr(server, "BASE_DIR", app)
    monkeypatch.setenv(dlf_session.DLF_FETCH_WORK_DIR_ENV, str(tmp_path / "no-such-dir"))

    assert _session_cookies()[DLF] == {"present": False, "autoRefresh": True}


def test_a_genuinely_stale_timer_jar_still_reports_stale(dirs):
    """The fix must not hide a real problem: an old jar in the work dir is
    still reported at its true age."""
    _app, work = dirs
    _write(work / DLF, age_days=40.0)

    dlf = _session_cookies()[DLF]

    assert dlf["present"] is True
    assert 39.9 <= dlf["ageDays"] <= 40.1
    assert dlf["daysRemaining"] == 0.0


def test_other_sessions_still_resolve_against_the_app_dir(dirs):
    """Scope pin: only DLF moved.  IDP Show / DraftSharks keep BASE_DIR."""
    app, work = dirs
    _write(app / "idpshow_session.json", age_days=5.0)
    _write(work / "draftsharks_session.json", age_days=1.0)  # wrong place: must be ignored

    sessions = _session_cookies()

    assert sessions["idpshow_session.json"]["present"] is True
    assert 4.9 <= sessions["idpshow_session.json"]["ageDays"] <= 5.1
    assert sessions["draftsharks_session.json"] == {"present": False, "autoRefresh": True}


def test_health_has_no_second_hardcoded_dlf_path():
    """The only place that knows the timer's directory is the resolver."""
    source = Path(server.__file__).read_text(encoding="utf-8")
    assert "var/lib/dlf-fetch" not in source
    assert "_dlf_session.health_session_path(" in source
