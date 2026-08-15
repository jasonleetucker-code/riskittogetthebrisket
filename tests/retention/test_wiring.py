"""The recorders are actually reachable from the live paths.

A store nothing writes to is not retention.  These are the tests that
would fail if a future refactor removed a call site — separately from
the store tests, which would all still pass.
"""

from __future__ import annotations

import json
import time

import pytest

from src.api import league_registry, sleeper_overlay
from src.retention import evidence_store, league_events


def _recent_ms() -> int:
    return int(time.time() * 1000) - 30 * 24 * 3600 * 1000


def _stub_http_responses(mapping):
    sorted_keys = sorted(mapping.keys(), key=len, reverse=True)

    def _resolve(url: str):
        for suffix in sorted_keys:
            if url.endswith(suffix):
                return mapping[suffix]
        return None

    return _resolve


@pytest.fixture(autouse=True)
def _isolated_stores(tmp_path, monkeypatch):
    evidence_store._reset_setup_cache_for_tests()
    league_events._reset_setup_cache_for_tests()
    monkeypatch.setattr(evidence_store, "DB_PATH", tmp_path / "evidence.sqlite")
    monkeypatch.setattr(league_events, "DB_PATH", tmp_path / "league_events.sqlite")
    sleeper_overlay.invalidate_overlay_cache()
    yield
    sleeper_overlay.invalidate_overlay_cache()
    evidence_store._reset_setup_cache_for_tests()
    league_events._reset_setup_cache_for_tests()


# ── C1-RET-04: write_scoring_snapshot records before it overwrites ───


def test_writing_a_scoring_snapshot_records_history(tmp_path, monkeypatch):
    monkeypatch.setattr(league_registry, "_DEFAULT_SCORING_SNAPSHOT_DIR", tmp_path / "leagues")

    league_registry.write_scoring_snapshot("999", {"rec": 1.0, "pass_td": 4})

    rows = evidence_store.scoring_card_history("999")
    assert len(rows) == 1


def test_the_overwritten_card_survives_in_history(tmp_path, monkeypatch):
    """THE row.  ``tmp.replace(path)`` still destroys the current-card
    file; what changed is that the previous card is no longer the only
    copy."""
    monkeypatch.setattr(league_registry, "_DEFAULT_SCORING_SNAPSHOT_DIR", tmp_path / "leagues")

    league_registry.write_scoring_snapshot("999", {"rec": 1.0})
    path = league_registry.write_scoring_snapshot("999", {"rec": 0.08})

    # The live gate still reads exactly one current card, unchanged.
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["scoringSettings"] == {"rec": 0.08}

    # And the destroyed one is recoverable.
    history = evidence_store.scoring_card_history("999")
    assert len(history) == 2
    first = evidence_store.scoring_card_at("999", history[0]["firstObservedAt"])
    assert first["scoringSettings"] == {"rec": 1.0}


def test_a_retention_failure_does_not_break_the_scoring_snapshot(tmp_path, monkeypatch):
    """The snapshot keeps the W18-F001 gate supplied; a retention store
    failure must not stop a league's card being refreshed."""
    monkeypatch.setattr(league_registry, "_DEFAULT_SCORING_SNAPSHOT_DIR", tmp_path / "leagues")

    def boom(*_a, **_k):
        raise RuntimeError("store unavailable")

    monkeypatch.setattr(evidence_store, "observe_scoring_card", boom)
    path = league_registry.write_scoring_snapshot("999", {"rec": 1.0})

    assert json.loads(path.read_text(encoding="utf-8"))["scoringSettings"] == {"rec": 1.0}


# ── C1-RET-06: trades carry an id, and the ledger outlives the window ─


def _trade_fixture(league_id: str, tx_id: str, ts_ms: int):
    responses = {
        f"/league/{league_id}": {"name": "Main", "previous_league_id": None},
        f"/league/{league_id}/rosters": [
            {"roster_id": 1, "owner_id": "oA"},
            {"roster_id": 2, "owner_id": "oB"},
        ],
        f"/league/{league_id}/users": [
            {"user_id": "oA", "display_name": "A"},
            {"user_id": "oB", "display_name": "B"},
        ],
        f"/league/{league_id}/drafts": [],
    }
    for w in range(0, 19):
        responses[f"/league/{league_id}/transactions/{w}"] = []
    responses[f"/league/{league_id}/transactions/1"] = [
        {
            "transaction_id": tx_id,
            "type": "trade",
            "status": "complete",
            "status_updated": ts_ms,
            "roster_ids": [1, 2],
            "adds": {"4034": 1},
            "drops": {"4034": 2},
            "draft_picks": [],
        }
    ]
    return responses


def test_trades_carry_their_sleeper_transaction_id(monkeypatch):
    monkeypatch.setattr(
        sleeper_overlay,
        "_http_get_json",
        _stub_http_responses(_trade_fixture("L1", "tx-abc", _recent_ms())),
    )
    trades = sleeper_overlay._build_trades_block("L1", window_days=365)

    assert len(trades) == 1
    assert trades[0]["transactionId"] == "tx-abc"


def test_the_ledger_keeps_a_trade_the_window_drops(monkeypatch):
    """THE row.  ``window_days`` is OUR cutoff, not Sleeper's — the
    fetch still returned this trade and the filter is the only reason it
    is not displayed.  Recording happens ahead of that filter."""
    very_old_ms = 100_000_000  # 1973 — outside any window.
    monkeypatch.setattr(
        sleeper_overlay,
        "_http_get_json",
        _stub_http_responses(_trade_fixture("L1", "tx-ancient", very_old_ms)),
    )
    trades = sleeper_overlay._build_trades_block("L1", window_days=30)

    assert trades == [], "still filtered out of the display shape"
    assert league_events.transaction_coverage()["transactions"] == 1


def test_the_ledger_accumulates_across_refetches(monkeypatch):
    """The overlay refetches on every cold cache; the ledger must grow
    monotonically rather than mirror whatever the last fetch returned."""
    monkeypatch.setattr(
        sleeper_overlay,
        "_http_get_json",
        _stub_http_responses(_trade_fixture("L1", "tx-old", _recent_ms())),
    )
    sleeper_overlay._build_trades_block("L1", window_days=365)

    monkeypatch.setattr(
        sleeper_overlay,
        "_http_get_json",
        _stub_http_responses(_trade_fixture("L1", "tx-new", _recent_ms())),
    )
    sleeper_overlay._build_trades_block("L1", window_days=365)

    assert league_events.transaction_coverage()["transactions"] == 2


def test_a_ledger_failure_does_not_break_the_trades_block(monkeypatch):
    monkeypatch.setattr(
        sleeper_overlay,
        "_http_get_json",
        _stub_http_responses(_trade_fixture("L1", "tx-abc", _recent_ms())),
    )

    def boom(*_a, **_k):
        raise RuntimeError("ledger unavailable")

    monkeypatch.setattr(league_events, "record_transactions", boom)
    trades = sleeper_overlay._build_trades_block("L1", window_days=365)

    assert len(trades) == 1, "/trades must keep working when the ledger cannot be written"


# ── C1-RET-05: the trending snapshot shape the adapter emits ─────────


def test_the_adapter_snapshot_shape_is_what_the_recorder_consumes():
    """Pins the contract between ``sleeper_trending._fetch_snapshot`` and
    ``observe_trending_snapshot``.  They are wired together in
    server.py's post-scrape warm, where a shape drift would be silent."""
    from src.adapters import sleeper_trending

    snapshot = {
        "fetchedAt": "2026-01-01T00:00:00+00:00",
        "lookbackHours": sleeper_trending.DEFAULT_LOOKBACK_HOURS,
        "counts": {"4034": 900},
    }
    result = evidence_store.observe_trending_snapshot(snapshot)

    assert result["action"] == "recorded"
    assert evidence_store.trending_series("4034")[0]["count"] == 900
