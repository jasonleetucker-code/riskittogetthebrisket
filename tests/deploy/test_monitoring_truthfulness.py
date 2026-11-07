"""A check that measured nothing must never read as verified (Workstream A4-lite).

Each test drives a real monitoring code path with an input it cannot measure
and asserts the result says NOT MEASURED / STALE rather than OK:

* ``health-check.yml`` backup step -- used to print "SQLite backup freshness
  OK." from the LEGACY backup keys alone while production's ``stateBackup``
  was ``unverifiable`` / ``permission_denied``;
* ``scripts/watchdog_freshness.py`` -- a CSV-mtime fallback (which a checkout
  resets) or a future-dated stamp read as a fresh fetch;
* ``scripts/temporal_ledger_status.py`` -- exited 0 for any ledger with rows,
  however old its newest date;
* ``scripts/refresh_injury_feed.py`` -- flag off logged at INFO, exit 0.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import textwrap
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO))


# -- health-check.yml backup step ------------------------------------------------
def _backup_step_script() -> str:
    workflow = (_REPO / ".github" / "workflows" / "health-check.yml").read_text(encoding="utf-8")
    step = workflow[workflow.index("Check /api/status (backup freshness)") :]
    body = step[step.index("python3 - <<'PY'") + len("python3 - <<'PY'") :]
    body = body[: body.index("\n          PY")]
    return textwrap.dedent(body)


def _run_backup_step(tmp_path: Path, state_backup: dict | None) -> subprocess.CompletedProcess:
    status = {
        "backup_health": {
            "newestBackupAgeHours": 6.9,
            "backupDirUsed": "fallback",
            "dbCount": 4,
            **({"stateBackup": state_backup} if state_backup is not None else {}),
        }
    }
    payload = tmp_path / "status_bkp.json"
    payload.write_text(json.dumps(status), encoding="utf-8")
    script = _backup_step_script().replace("/tmp/status_bkp.json", payload.as_posix())
    return subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=60
    )


def test_unverifiable_state_backup_is_not_measured_not_ok(tmp_path):
    """Production 2026-10-27: canonical root unreadable by the app user."""
    proc = _run_backup_step(
        tmp_path,
        {"state": "unverifiable", "reason": "permission_denied", "evidenceSource": None},
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "Legacy SQLite backup freshness OK." in proc.stdout
    assert (
        "::warning title=State backup NOT MEASURED (permission_denied, expected)::" in proc.stdout
    )
    # The bare, unqualified claim the step used to make is gone.
    assert "\nSQLite backup freshness OK." not in "\n" + proc.stdout


@pytest.mark.parametrize("reason", ["io_error", "probe_error", "generation_clock_skew"])
def test_other_unverifiable_reasons_are_named_not_expected(tmp_path, reason):
    proc = _run_backup_step(tmp_path, {"state": "unverifiable", "reason": reason})
    assert proc.returncode == 0
    assert "::warning title=State backup NOT MEASURED::" in proc.stdout
    assert reason in proc.stdout and "expected" not in proc.stdout


def test_absent_state_backup_block_is_not_measured(tmp_path):
    proc = _run_backup_step(tmp_path, None)
    assert proc.returncode == 0
    assert "State backup NOT MEASURED" in proc.stdout


def test_measured_healthy_state_backup_says_measured(tmp_path):
    proc = _run_backup_step(
        tmp_path,
        {
            "state": "healthy",
            "reason": "within_threshold",
            "ageHours": 6.0,
            "generationCount": 14,
            "directoryRole": "canonical",
            "evidenceSource": "directory_listing",
        },
    )
    assert proc.returncode == 0
    assert "State backup: healthy, measured" in proc.stdout
    assert "NOT MEASURED" not in proc.stdout


def test_healthy_without_evidence_is_not_a_measured_pass(tmp_path):
    proc = _run_backup_step(tmp_path, {"state": "healthy", "evidenceSource": None})
    assert "NOT MEASURED" in proc.stdout


@pytest.mark.parametrize("state", ["stale", "missing"])
def test_measured_stale_or_missing_state_backup_fails(tmp_path, state):
    proc = _run_backup_step(
        tmp_path, {"state": state, "reason": "x", "evidenceSource": "directory_listing"}
    )
    assert proc.returncode == 1
    assert f"::error title=State backup {state}::" in proc.stdout


# -- watchdog_freshness ------------------------------------------------------------
def test_watchdog_names_ages_it_did_not_measure():
    from scripts import watchdog_freshness as wf

    rows = {
        "a": {"ageHours": 1.0, "basis": "stamp"},
        "b": {"ageHours": 0.0, "basis": "csv_mtime"},
        "c": {"ageHours": 0.0, "basis": "stamp_clock_skew"},
        "d": {"ageHours": 2.0},
    }
    assert wf.unmeasured_age_sources(rows) == {"b": "csv_mtime", "c": "stamp_clock_skew"}


def test_watchdog_stamps_record_their_basis(tmp_path, monkeypatch):
    from scripts import watchdog_freshness as wf
    import src.api.data_contract as dc

    (tmp_path / "data" / "scrape_state").mkdir(parents=True)
    (tmp_path / "CSVs").mkdir()
    for name in ("stamped", "mtimeonly", "future"):
        (tmp_path / "CSVs" / f"{name}.csv").write_text("x\n", encoding="utf-8")
    now = datetime.now(timezone.utc).timestamp()
    (tmp_path / "data" / "scrape_state" / "stamped_last_success").write_text(
        str(now - 3600), encoding="utf-8"
    )
    (tmp_path / "data" / "scrape_state" / "future_last_success").write_text(
        str(now + 86400), encoding="utf-8"
    )
    monkeypatch.setattr(wf, "_REPO_ROOT", tmp_path)
    monkeypatch.setattr(wf, "unprovisioned_private_sources", lambda: [])
    monkeypatch.setattr(
        dc,
        "_SOURCE_CSV_PATHS",
        {n: f"CSVs/{n}.csv" for n in ("stamped", "mtimeonly", "future")},
    )
    rows = wf._read_freshness()
    assert rows["stamped"]["basis"] == "stamp"
    assert rows["mtimeonly"]["basis"] == "csv_mtime"
    assert rows["future"]["basis"] == "stamp_clock_skew"
    assert wf.unmeasured_age_sources(rows) == {
        "future": "stamp_clock_skew",
        "mtimeonly": "csv_mtime",
    }


# -- temporal_ledger_status ----------------------------------------------------------
def test_ledger_recency_is_measured_not_assumed():
    from scripts import temporal_ledger_status as tls

    today = date(2026, 10, 27)
    assert tls.ledger_staleness("2026-10-27", max_age_days=2, today=today) is None
    assert tls.ledger_staleness("2026-10-25", max_age_days=2, today=today) is None
    assert "4 days old" in tls.ledger_staleness("2026-10-23", max_age_days=2, today=today)
    # Unreadable recency is stale, never fresh.
    assert "unreadable" in tls.ledger_staleness(None, max_age_days=2, today=today)
    assert "unreadable" in tls.ledger_staleness("garbage", max_age_days=2, today=today)


def test_ledger_status_exits_3_when_stale(monkeypatch, capsys):
    from scripts import temporal_ledger_status as tls

    monkeypatch.setattr(
        tls.store, "coverage", lambda path: {"exists": True, "rows": 5, "lastDate": "2026-01-01"}
    )
    monkeypatch.setattr(
        tls.asof,
        "value_as_of",
        lambda *a, **k: {
            "fidelity": tls.asof.FIDELITY_UNAVAILABLE,
            "missingReason": tls.asof.REASON_BEFORE_BOUNDARY,
        },
    )
    assert tls.main([]) == 3
    assert "STALE" in capsys.readouterr().err


# -- injury feed -----------------------------------------------------------------------
def test_injury_feed_flag_off_says_not_measured(monkeypatch, caplog):
    from scripts import refresh_injury_feed as rif

    monkeypatch.setattr(rif.feature_flags, "is_enabled", lambda name: False)
    with caplog.at_level(logging.WARNING):
        assert rif.main([]) == 0
    assert any(
        r.levelno == logging.WARNING and "NOT MEASURED" in r.getMessage() for r in caplog.records
    )
