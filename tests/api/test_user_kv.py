"""Tests for ``src.api.user_kv`` — durable per-user preference store."""
from __future__ import annotations

import json
import sqlite3
import threading
import time

import pytest

from src.api import user_kv


@pytest.fixture()
def kv_path(tmp_path):
    return tmp_path / "user_kv.sqlite"


@pytest.fixture(autouse=True)
def _reset_setup_cache():
    # Each test gets a fresh tmp path; clear the module-level "schema
    # already applied" cache so the SQLite pragmas + CREATE TABLE
    # actually run against the new path.
    user_kv._SETUP_DONE.clear()
    yield
    user_kv._SETUP_DONE.clear()


def test_empty_user_returns_empty_dict(kv_path):
    assert user_kv.get_user_state("nobody", path=kv_path) == {}


def test_set_and_get_field(kv_path):
    user_kv.set_user_field(
        "alice",
        "selectedTeam",
        {"ownerId": "abc", "name": "Alphas"},
        path=kv_path,
    )
    state = user_kv.get_user_state("alice", path=kv_path)
    assert state["selectedTeam"] == {"ownerId": "abc", "name": "Alphas"}
    assert "updatedAt" in state


def test_merge_preserves_unrelated_fields(kv_path):
    user_kv.set_user_field("a", "selectedTeam", {"ownerId": "o"}, path=kv_path)
    user_kv.merge_user_state("a", {"watchlist": ["Ja'Marr Chase"]}, path=kv_path)
    state = user_kv.get_user_state("a", path=kv_path)
    assert state["selectedTeam"] == {"ownerId": "o"}
    assert state["watchlist"] == ["Ja'Marr Chase"]


def test_merge_none_deletes_field(kv_path):
    user_kv.set_user_field("u", "watchlist", ["A", "B"], path=kv_path)
    user_kv.merge_user_state("u", {"watchlist": None}, path=kv_path)
    state = user_kv.get_user_state("u", path=kv_path)
    assert "watchlist" not in state


def test_dismissed_signals_merge_dict(kv_path):
    future_1 = int(time.time() * 1000) + 60_000
    future_2 = future_1 + 60_000
    user_kv.merge_user_state("u", {"dismissedSignals": {"k1": future_1}}, path=kv_path)
    user_kv.merge_user_state("u", {"dismissedSignals": {"k2": future_2}}, path=kv_path)
    state = user_kv.get_user_state("u", path=kv_path)
    assert state["dismissedSignals"] == {"k1": future_1, "k2": future_2}


def test_dismiss_signal_and_prune(kv_path):
    now_ms = int(time.time() * 1000)
    user_kv.dismiss_signal("u", "Mahomes::elite_stable", ttl_ms=60_000, path=kv_path)
    dis = user_kv.active_dismissals("u", path=kv_path)
    assert "Mahomes::elite_stable" in dis
    assert dis["Mahomes::elite_stable"] > now_ms

    # Expire manually by writing a past timestamp
    user_kv.merge_user_state(
        "u",
        {"dismissedSignals": {"already_expired": 1}},
        path=kv_path,
    )
    dis = user_kv.active_dismissals("u", path=kv_path)
    assert "already_expired" not in dis


def test_undismiss_signal(kv_path):
    user_kv.dismiss_signal("u", "foo", ttl_ms=60_000, path=kv_path)
    user_kv.undismiss_signal("u", "foo", path=kv_path)
    assert "foo" not in user_kv.active_dismissals("u", path=kv_path)


def test_dismissals_scoped_per_league(kv_path):
    """Dismissing a signal in league A must NOT hide the same
    signal in league B — both leagues get independent buckets."""
    user_kv.dismiss_signal(
        "u", "Josh Allen::elite_stable", ttl_ms=60_000,
        league_key="dynasty_main", path=kv_path,
    )
    # League A has it; league B does not.
    assert "Josh Allen::elite_stable" in user_kv.active_dismissals(
        "u", league_key="dynasty_main", path=kv_path,
    )
    assert user_kv.active_dismissals(
        "u", league_key="dynasty_new", path=kv_path,
    ) == {}


def test_undismiss_scoped_per_league(kv_path):
    """Un-dismissing in league A leaves league B's dismissal alone."""
    user_kv.dismiss_signal(
        "u", "Josh Allen::elite_stable", league_key="dynasty_main", path=kv_path,
    )
    user_kv.dismiss_signal(
        "u", "Josh Allen::elite_stable", league_key="dynasty_new", path=kv_path,
    )
    user_kv.undismiss_signal(
        "u", "Josh Allen::elite_stable", league_key="dynasty_main", path=kv_path,
    )
    # A gone, B intact.
    assert user_kv.active_dismissals(
        "u", league_key="dynasty_main", path=kv_path,
    ) == {}
    assert "Josh Allen::elite_stable" in user_kv.active_dismissals(
        "u", league_key="dynasty_new", path=kv_path,
    )


def test_legacy_flat_dismissals_unchanged(kv_path):
    """Legacy callers (no ``league_key``) continue to write the flat
    ``dismissedSignals`` field + read from it, keeping pre-migration
    state intact."""
    user_kv.dismiss_signal("u", "legacy::x", ttl_ms=60_000, path=kv_path)
    flat = user_kv.active_dismissals("u", path=kv_path)  # no league_key
    assert "legacy::x" in flat
    # Per-league reader on a league with no bucket returns empty —
    # it does NOT surface the flat field (we'd be showing default-
    # league dismissals under league B's name).
    assert user_kv.active_dismissals(
        "u", league_key="dynasty_new", path=kv_path,
    ) == {}


def test_corrupt_file_starts_fresh(kv_path):
    kv_path.write_text("not json", encoding="utf-8")
    # Should not raise
    state = user_kv.get_user_state("u", path=kv_path)
    assert state == {}
    # Subsequent write should succeed and overwrite the corrupt file.
    user_kv.set_user_field("u", "watchlist", ["x"], path=kv_path)
    assert user_kv.get_user_state("u", path=kv_path)["watchlist"] == ["x"]


def test_empty_username_is_noop(kv_path):
    assert user_kv.set_user_field("", "watchlist", ["x"], path=kv_path) == {}
    assert user_kv.get_user_state("", path=kv_path) == {}


def test_multiple_users_isolated(kv_path):
    user_kv.set_user_field("alice", "watchlist", ["A"], path=kv_path)
    user_kv.set_user_field("bob", "watchlist", ["B"], path=kv_path)
    assert user_kv.get_user_state("alice", path=kv_path)["watchlist"] == ["A"]
    assert user_kv.get_user_state("bob", path=kv_path)["watchlist"] == ["B"]


def test_dismissed_expires_pruned_on_read(kv_path):
    user_kv.set_user_field(
        "u",
        "dismissedSignals",
        {"expired": 100, "future": int(time.time() * 1000) + 60_000},
        path=kv_path,
    )
    state = user_kv.get_user_state("u", path=kv_path)
    assert "expired" not in state["dismissedSignals"]
    assert "future" in state["dismissedSignals"]


# ── SQLite-specific behaviours ──────────────────────────────────────


def test_file_is_sqlite_database(kv_path):
    user_kv.set_user_field("alice", "watchlist", ["a"], path=kv_path)
    assert kv_path.exists()
    # sqlite3 magic header
    with kv_path.open("rb") as f:
        assert f.read(16).startswith(b"SQLite format 3")


def test_wal_journal_mode_enabled(kv_path):
    user_kv.set_user_field("alice", "watchlist", ["a"], path=kv_path)
    conn = sqlite3.connect(str(kv_path))
    try:
        mode = conn.execute("PRAGMA journal_mode;").fetchone()[0].lower()
        assert mode == "wal"
    finally:
        conn.close()


def test_corrupt_file_renamed_and_replaced(tmp_path):
    # Path to a non-database file; _ensure_schema should rename it
    # to .corrupt and rebuild.
    path = tmp_path / "user_kv.sqlite"
    path.write_text("definitely not a database", encoding="utf-8")
    user_kv._SETUP_DONE.clear()
    state = user_kv.get_user_state("u", path=path)
    assert state == {}
    # Write still works after the reset.
    user_kv.set_user_field("u", "watchlist", ["x"], path=path)
    assert user_kv.get_user_state("u", path=path)["watchlist"] == ["x"]
    # Corrupt file was preserved for inspection.
    assert (tmp_path / "user_kv.sqlite.corrupt").exists()


def test_concurrent_writes_do_not_lose_data(kv_path):
    # 10 writer threads each insert a distinct user; all 10 should
    # survive (SQLite's WAL-mode locks serialise the writes).
    user_kv.set_user_field("seed", "watchlist", [], path=kv_path)

    def _writer(idx: int) -> None:
        user_kv.set_user_field(
            f"user-{idx}",
            "watchlist",
            [f"p{idx}"],
            path=kv_path,
        )

    threads = [threading.Thread(target=_writer, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    conn = sqlite3.connect(str(kv_path))
    try:
        count = conn.execute("SELECT COUNT(*) FROM user_state").fetchone()[0]
    finally:
        conn.close()
    assert count == 11  # 10 writers + the seed user


def test_legacy_json_migration_runs_on_first_boot(tmp_path, monkeypatch):
    sqlite_path = tmp_path / "user_kv.sqlite"
    legacy_path = tmp_path / "user_kv.json"
    # Pretend we're running against the production path so the
    # migration path is exercised.
    monkeypatch.setattr(user_kv, "USER_KV_PATH", sqlite_path)
    monkeypatch.setattr(user_kv, "_LEGACY_JSON_PATH", legacy_path)

    legacy_path.write_text(
        json.dumps({
            "alice": {
                "watchlist": ["Ja'Marr Chase"],
                "selectedTeam": {"ownerId": "o", "name": "Alphas"},
                "updatedAt": "2026-04-22T10:00:00Z",
            },
            "bob": {"watchlist": ["Bijan Robinson"]},
        })
    )
    user_kv._SETUP_DONE.clear()
    # First call triggers migration.
    alice = user_kv.get_user_state("alice")
    assert alice["watchlist"] == ["Ja'Marr Chase"]
    assert user_kv.get_user_state("bob")["watchlist"] == ["Bijan Robinson"]
    # Legacy file renamed, not deleted.
    assert not legacy_path.exists()
    assert legacy_path.with_suffix(".json.migrated").exists()


def test_dismiss_signal_stores_alias_mapping(kv_path):
    user_kv.dismiss_signal(
        "u",
        "Ja'Marr Chase::alert_with_drop",
        ttl_ms=60_000,
        alias_sleeper_id="7564",
        alias_display_name="Ja'Marr Chase",
        path=kv_path,
    )
    state = user_kv.get_user_state("u", path=kv_path)
    aliases = state.get("dismissalAliases") or {}
    assert aliases.get("Ja'Marr Chase") == "7564"


def test_dismiss_signal_without_alias_keeps_existing_map(kv_path):
    # Set one alias, then dismiss another signal without providing
    # alias args — the first mapping must persist.
    user_kv.dismiss_signal(
        "u", "A::tag",
        ttl_ms=60_000,
        alias_sleeper_id="111",
        alias_display_name="A",
        path=kv_path,
    )
    user_kv.dismiss_signal(
        "u", "B::tag",
        ttl_ms=60_000,
        path=kv_path,
    )
    aliases = user_kv.dismissal_aliases("u", path=kv_path)
    assert aliases == {"A": "111"}


def test_get_user_state_does_not_read_other_users_blobs(kv_path):
    user_kv.set_user_field("alice", "watchlist", ["a"], path=kv_path)
    user_kv.set_user_field("bob", "watchlist", ["b"], path=kv_path)
    # Read Alice — bob should NOT appear in alice's state.
    alice = user_kv.get_user_state("alice", path=kv_path)
    assert alice.get("watchlist") == ["a"]
    assert "bob" not in alice
    assert user_kv.get_user_state("charlie", path=kv_path) == {}
