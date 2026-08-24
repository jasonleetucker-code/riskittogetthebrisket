"""Regression coverage for filename-dated playerctx freshness.

A discovery test used a fixed 2026-08-10 filename and eventually aged stale on
the real calendar.  These tests pin the clock explicitly so they prove both
sides of the real retention contract without depending on today's date.
"""

from datetime import datetime, timezone

from src.retention import health


def _playerctx_stream(report):
    return next(stream for stream in report["streams"] if stream["id"] == "C1-RET-08")


def _write_snapshot(data_dir):
    hist = data_dir / "playerctx" / "history"
    hist.mkdir(parents=True)
    (hist / "playerctx_2026-08-10.json").write_text("{}", encoding="utf-8")


def test_playerctx_fixed_filename_is_ok_inside_real_budget(data_dir, monkeypatch):
    _write_snapshot(data_dir)
    monkeypatch.setattr(
        health,
        "_now",
        lambda: datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc),
    )

    stream = _playerctx_stream(health.retention_health(data_dir=data_dir))

    assert stream["state"] == health.STATE_OK
    assert stream["stampSource"] == "filename"


def test_playerctx_fixed_filename_ages_out_past_real_budget(data_dir, monkeypatch):
    _write_snapshot(data_dir)
    monkeypatch.setattr(
        health,
        "_now",
        lambda: datetime(2026, 8, 20, 0, 0, 0, tzinfo=timezone.utc),
    )

    stream = _playerctx_stream(health.retention_health(data_dir=data_dir))

    assert stream["state"] == health.STATE_STALE
    assert stream["ageHours"] > stream["budgetHours"]
