"""A full start/terminal pair is required; private event text stays private."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

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
    assert result["checkout_sha"] == SHA
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
