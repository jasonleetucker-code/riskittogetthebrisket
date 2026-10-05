"""A full start/terminal pair is required; private event text stays private."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from scripts import scrape_source_lifecycle_proof as lifecycle
from scripts.scrape_source_lifecycle_proof import ProofError, prove


NOW = datetime(2026, 10, 5, 22, 30, tzinfo=timezone.utc)
WORKER = "run-0123456789ab"
SHA = "a" * 40


def row(event, when, *, worker=WORKER, source="KTC", **extra):
    return json.dumps(
        {"event": event, "ts": when.isoformat(), "worker_id": worker, "source": source, **extra}
    )


def lines(*events):
    return [json.dumps({"type": "checkout_identity", "sha": SHA}), *events]


def test_correlates_real_source_lifecycle_without_exposing_private_fields():
    start = NOW - timedelta(seconds=19.125)
    result = prove(
        lines(
            row("source_start", start, message="private customer name"),
            row("source_complete", NOW, meta={"cookie": "secret"}),
        ),
        now=NOW,
    )
    assert result["duration_seconds"] == 19.125
    assert result["outcome"] == "source_complete"
    assert result["worker_id"] == WORKER
    assert result["checkout_sha_observed"] == SHA
    assert "private" not in json.dumps(result)
    assert "secret" not in json.dumps(result)


def test_rejects_mismatched_worker_and_incomplete_lifecycle():
    start = NOW - timedelta(seconds=5)
    with pytest.raises(ProofError, match="no correlated"):
        prove(
            lines(
                row("source_start", start),
                row("source_failed", NOW, worker="run-ffffffffffff"),
            ),
            now=NOW,
        )


def test_rejects_stale_complete_lifecycle():
    start = NOW - timedelta(days=3)
    with pytest.raises(ProofError, match="stale"):
        prove(
            lines(row("source_start", start), row("source_complete", start + timedelta(seconds=4))),
            now=NOW,
        )


def test_torn_rows_are_skipped_and_latest_complete_pair_wins():
    start = NOW - timedelta(seconds=10)
    result = prove(
        lines(
            "{torn",
            row("source_start", start, source="KTC"),
            row("source_complete", start + timedelta(seconds=2), source="KTC"),
            row("source_start", start + timedelta(seconds=5), source="IDPTradeCalc"),
            row("source_partial", NOW, source="IDPTradeCalc"),
        ),
        now=NOW,
    )
    assert result["source"] == "IDPTradeCalc"
    assert result["outcome"] == "source_partial"


def test_requires_checkout_identity_and_rejects_future_terminal():
    with pytest.raises(ProofError, match="checkout identity"):
        prove([row("source_start", NOW), row("source_complete", NOW)], now=NOW)
    with pytest.raises(ProofError, match="no correlated"):
        prove(
            lines(row("source_start", NOW), row("source_complete", NOW + timedelta(seconds=1))),
            now=NOW,
        )


def test_production_mode_reads_events_on_host_without_echoing_private_data(tmp_path, monkeypatch):
    events = tmp_path / "data" / "diagnostics" / "scrape_events.jsonl"
    events.parent.mkdir(parents=True)
    events.write_text(
        row("source_start", NOW - timedelta(seconds=4), message="private")
        + "\n"
        + row("source_complete", NOW, meta={"secret": "credential"})
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("APP_DIR", str(tmp_path))
    monkeypatch.setattr(lifecycle.subprocess, "check_output", lambda *args, **kwargs: SHA)
    result = prove(lifecycle._production_lines(), now=NOW)
    assert result["checkout_sha_observed"] == SHA
    assert result["duration_seconds"] == 4.0
    assert "private" not in json.dumps(result)
    assert "credential" not in json.dumps(result)


def test_streamed_script_runs_on_host_and_emits_only_allowlisted_summary(tmp_path):
    import os
    import subprocess
    import sys

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "fixture",
        ],
        check=True,
    )
    events = tmp_path / "data" / "diagnostics" / "scrape_events.jsonl"
    events.parent.mkdir(parents=True)
    now = datetime.now(timezone.utc)
    events.write_text(
        row("source_start", now - timedelta(seconds=2), message="private")
        + "\n"
        + row("source_complete", now, meta={"secret": "credential"})
        + "\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, "-", "--production"],
        input=open(lifecycle.__file__, encoding="utf-8").read(),
        text=True,
        capture_output=True,
        env={**os.environ, "APP_DIR": str(tmp_path)},
        check=True,
    )
    summary = json.loads(result.stdout)
    assert summary["schema"] == "scrape-source-lifecycle-proof/v1"
    assert summary["duration_seconds"] == 2.0
    assert "private" not in result.stdout
    assert "credential" not in result.stdout
