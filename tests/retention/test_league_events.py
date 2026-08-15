"""C1-RET-06 — the PRIVATE own-league transaction ledger.

Pins the three properties that make it a ledger rather than a cache:
re-running cannot duplicate, re-running cannot truncate, and the raw
payload survives so a question asked later is answerable.
"""

from __future__ import annotations

import json

import pytest

from src.retention import league_events


@pytest.fixture
def db(tmp_path):
    league_events._reset_setup_cache_for_tests()
    path = tmp_path / "retention" / "league_events.sqlite"
    yield path
    league_events._reset_setup_cache_for_tests()


def _tx(tx_id: str, **over):
    base = {
        "transaction_id": tx_id,
        "type": "trade",
        "status": "complete",
        "leg": 5,
        "status_updated": 1_760_000_000_000,
        "roster_ids": [1, 2],
        "adds": {"4034": 1},
        "drops": {"4034": 2},
        "draft_picks": [],
    }
    base.update(over)
    return base


def test_transactions_are_recorded(db):
    report = league_events.record_transactions(
        "999", [_tx("a"), _tx("b")], league_key="main", path=db
    )
    assert report["recorded"] == 2
    assert report["skipped"] == 0

    cov = league_events.transaction_coverage(path=db)
    assert cov["transactions"] == 2
    assert cov["trades"] == 2
    assert cov["leagues"] == 1


def test_rerunning_the_same_window_does_not_duplicate(db):
    """The overlay refetches a 365-day window on every cold cache, so
    the same trades WILL be offered repeatedly."""
    league_events.record_transactions("999", [_tx("a"), _tx("b")], path=db)
    report = league_events.record_transactions("999", [_tx("a"), _tx("b")], path=db)

    assert report["recorded"] == 0
    assert report["updated"] == 2
    assert league_events.transaction_coverage(path=db)["transactions"] == 2


def test_a_shrinking_window_cannot_truncate_the_ledger(db):
    """THE point of the row. A later fetch that no longer returns an old
    trade must not remove it — that is exactly the loss being prevented."""
    league_events.record_transactions("999", [_tx("old"), _tx("new")], path=db)
    league_events.record_transactions("999", [_tx("new")], path=db)

    assert league_events.transaction_coverage(path=db)["transactions"] == 2


def test_first_recorded_at_is_never_rewritten(db):
    """When we first SAW an event is our own evidence, and a different
    fact from when Sleeper says it happened."""
    league_events.record_transactions("999", [_tx("a")], path=db)
    conn = league_events.connect(db)
    try:
        first = conn.execute("SELECT first_recorded_at FROM league_transactions").fetchone()[0]
    finally:
        conn.close()

    league_events.record_transactions("999", [_tx("a")], path=db)
    conn = league_events.connect(db)
    try:
        again, last_seen = conn.execute(
            "SELECT first_recorded_at, last_seen_at FROM league_transactions"
        ).fetchone()
    finally:
        conn.close()

    assert again == first
    assert last_seen >= first


def test_pending_can_advance_to_complete(db):
    """A strict existing-wins rule would pin a trade at pending forever."""
    league_events.record_transactions("999", [_tx("a", status="pending")], path=db)
    league_events.record_transactions("999", [_tx("a", status="complete")], path=db)

    conn = league_events.connect(db)
    try:
        status = conn.execute("SELECT status FROM league_transactions").fetchone()[0]
    finally:
        conn.close()
    assert status == "complete"


def test_a_transaction_without_an_id_is_skipped_not_synthesised(db):
    """A fabricated key would defeat the dedup the ledger exists for."""
    report = league_events.record_transactions("999", [_tx("a"), {"type": "trade"}], path=db)
    assert report["recorded"] == 1
    assert report["skipped"] == 1


def test_the_raw_payload_survives(db):
    tx = _tx("a", some_field_nobody_reads_yet={"deep": 1})
    league_events.record_transactions("999", [tx], path=db)

    conn = league_events.connect(db)
    try:
        raw = conn.execute("SELECT payload_json FROM league_transactions").fetchone()[0]
    finally:
        conn.close()
    assert json.loads(raw)["some_field_nobody_reads_yet"] == {"deep": 1}


def test_chain_members_are_separate_leagues(db):
    """A depth-2 chain spans seasons under different Sleeper ids; the
    event stays attached to the season it happened in."""
    league_events.record_transactions("2025-id", [_tx("a")], path=db)
    league_events.record_transactions("2026-id", [_tx("a")], path=db)

    assert league_events.transaction_coverage(path=db)["transactions"] == 2


def test_seconds_and_millisecond_stamps_both_normalise(db):
    league_events.record_transactions("999", [_tx("s", status_updated=1_760_000_000)], path=db)
    league_events.record_transactions("999", [_tx("ms", status_updated=1_760_000_000_000)], path=db)

    conn = league_events.connect(db)
    try:
        stamps = [
            r[0]
            for r in conn.execute(
                "SELECT occurred_at_ms FROM league_transactions ORDER BY transaction_id"
            )
        ]
    finally:
        conn.close()
    assert stamps == [1_760_000_000_000, 1_760_000_000_000]


def test_an_undated_event_is_null_not_zero(db):
    league_events.record_transactions("999", [_tx("a", status_updated=None, created=None)], path=db)
    conn = league_events.connect(db)
    try:
        stamp = conn.execute("SELECT occurred_at_ms FROM league_transactions").fetchone()[0]
    finally:
        conn.close()
    assert stamp is None, "an undated event is not an event dated 1970"


def test_coverage_distinguishes_absent_from_empty(db):
    cov = league_events.transaction_coverage(path=db)
    assert cov["present"] is False
    assert cov["privacyClass"] == "private"

    league_events.record_transactions("999", [_tx("a")], path=db)
    assert league_events.transaction_coverage(path=db)["present"] is True


def test_coverage_never_echoes_a_payload(db):
    """A health surface that leaked private trade contents would move
    the privacy boundary every time someone checked liveness."""
    league_events.record_transactions("999", [_tx("a")], league_key="main", path=db)
    blob = json.dumps(league_events.transaction_coverage(path=db))

    assert "roster_ids" not in blob
    assert "adds" not in blob
    assert "4034" not in blob


def test_the_private_store_is_a_separate_file_from_the_internal_one():
    """So that 'back this up' and 'publish this' can never be the same
    gesture by accident."""
    from src.retention import evidence_store

    assert league_events.DB_PATH != evidence_store.DB_PATH
    assert league_events.PRIVACY_CLASS == "private"
