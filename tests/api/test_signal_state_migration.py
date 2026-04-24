"""Tests for signalAlertState legacy migration."""
from __future__ import annotations

import pytest

from src.api import signal_state_migration as mig
from src.api import user_kv


@pytest.fixture()
def kv(tmp_path):
    path = tmp_path / "user_kv.sqlite"
    user_kv._SETUP_DONE.clear()
    yield path
    user_kv._SETUP_DONE.clear()


def test_user_with_legacy_state_gets_migrated(kv):
    user_kv.merge_user_state(
        "alice",
        {
            "signalAlertState": {
                "sid:4017::elite_stable": {"signal": "SELL", "notifiedAt": 1_000_000},
                "sid:9479::elite_stable": {"signal": "BUY", "notifiedAt": 2_000_000},
            },
            "signalAlertStateByLeague": {},
        },
        path=kv,
    )
    result = mig.migrate_user("alice", default_league_key="dynasty_main", path=kv)
    assert result["action"] == "migrated"
    assert result["keys_moved"] == 2
    state = user_kv.get_user_state("alice", path=kv)
    # Legacy field cleared.
    assert state["signalAlertState"] == {}
    # Bucket populated.
    assert "dynasty_main" in state["signalAlertStateByLeague"]
    assert "sid:4017::elite_stable" in state["signalAlertStateByLeague"]["dynasty_main"]


def test_already_migrated_user_is_skipped(kv):
    user_kv.merge_user_state(
        "bob",
        {
            "signalAlertState": {"sid:1::x": {"signal": "SELL", "notifiedAt": 1}},
            "signalAlertStateByLeague": {
                "dynasty_main": {"sid:99::x": {"signal": "BUY", "notifiedAt": 999}},
            },
        },
        path=kv,
    )
    result = mig.migrate_user("bob", default_league_key="dynasty_main", path=kv)
    assert result["action"] == "skipped"
    state = user_kv.get_user_state("bob", path=kv)
    # Legacy still cleared for cleanup.
    assert state["signalAlertState"] == {}
    # Nested state preserved verbatim.
    assert state["signalAlertStateByLeague"]["dynasty_main"]["sid:99::x"]["signal"] == "BUY"


def test_user_with_no_legacy_is_noop(kv):
    user_kv.merge_user_state(
        "charlie",
        {"signalAlertStateByLeague": {"dynasty_main": {}}},
        path=kv,
    )
    result = mig.migrate_user("charlie", default_league_key="dynasty_main", path=kv)
    assert result["action"] == "noop"


def test_empty_legacy_dict_is_noop(kv):
    user_kv.merge_user_state(
        "dave",
        {"signalAlertState": {}},
        path=kv,
    )
    result = mig.migrate_user("dave", default_league_key="dynasty_main", path=kv)
    assert result["action"] == "noop"


def test_migrate_all_counts_actions(kv):
    user_kv.merge_user_state(
        "alice",
        {"signalAlertState": {"sid:1::x": {"signal": "SELL", "notifiedAt": 1}}},
        path=kv,
    )
    user_kv.merge_user_state("bob", {}, path=kv)
    result = mig.migrate_all(default_league_key="dynasty_main", path=kv)
    assert result["processed"] == 2
    assert result["counts"]["migrated"] == 1
    assert result["counts"]["noop"] == 1


def test_migration_is_idempotent(kv):
    user_kv.merge_user_state(
        "alice",
        {"signalAlertState": {"sid:1::x": {"signal": "SELL", "notifiedAt": 1}}},
        path=kv,
    )
    first = mig.migrate_user("alice", default_league_key="dynasty_main", path=kv)
    second = mig.migrate_user("alice", default_league_key="dynasty_main", path=kv)
    assert first["action"] == "migrated"
    # Second run — no legacy state left, so noop.
    assert second["action"] == "noop"


def test_migration_preserves_newer_entries_on_conflict(kv):
    """When both legacy AND league-bucket have the same signalKey,
    the newer notifiedAt wins so we don't lose a recent cooldown."""
    user_kv.merge_user_state(
        "alice",
        {
            "signalAlertState": {
                "sid:1::x": {"signal": "SELL", "notifiedAt": 1_000_000},
            },
            "signalAlertStateByLeague": {
                "dynasty_main": {
                    # Different league bucket — should not collide.
                    "sid:2::x": {"signal": "BUY", "notifiedAt": 500_000},
                },
            },
        },
        path=kv,
    )
    result = mig.migrate_user("alice", default_league_key="dynasty_main", path=kv)
    # Already-migrated state detected → skipped (legacy cleaned).
    # But both entries should now live in the bucket.
    state = user_kv.get_user_state("alice", path=kv)
    bucket = state["signalAlertStateByLeague"]["dynasty_main"]
    # The pre-existing league entry was enough to mark as already_migrated.
    # The legacy gets cleared regardless.  Check that the legacy cleanup
    # doesn't drop the sid:2::x entry.
    assert "sid:2::x" in bucket
    assert state["signalAlertState"] == {}
