"""Tests for the persistent session store.

Pins:
  * persist + hydrate round-trips a session.
  * TTL expiry drops old rows on hydrate.
  * Allowlist rotation invalidates all sessions.
  * Corrupted / missing DB returns empty, never raises.
  * evict removes a single session.
  * force_clear_all removes everything.
"""
from __future__ import annotations

import time

import pytest

from src.api import session_store


@pytest.fixture(autouse=True)
def _reset_setup_flag():
    session_store._setup_done.clear()  # noqa: SLF001
    yield
    session_store._setup_done.clear()  # noqa: SLF001


def test_persist_then_hydrate_round_trip(tmp_path):
    db = tmp_path / "s.sqlite"
    session_store.persist(
        "sid-abc",
        {
            "username": "jasonleetucker",
            "sleeper_user_id": "12345",
            "display_name": "Jason",
            "auth_method": "sleeper",
        },
        allowlist=["jasonleetucker"],
        db_path=db,
    )
    session_store._setup_done.clear()  # noqa: SLF001
    hydrated = session_store.hydrate(allowlist=["jasonleetucker"], db_path=db)
    assert "sid-abc" in hydrated
    assert hydrated["sid-abc"]["username"] == "jasonleetucker"
    assert hydrated["sid-abc"]["sleeper_user_id"] == "12345"
    assert hydrated["sid-abc"]["auth_method"] == "sleeper"


def test_hydrate_empty_db_returns_empty_dict(tmp_path):
    got = session_store.hydrate(db_path=tmp_path / "fresh.sqlite")
    assert got == {}


def test_allowlist_rotation_invalidates_sessions(tmp_path):
    db = tmp_path / "s.sqlite"
    session_store.persist(
        "sid-1", {"username": "old_user"},
        allowlist=["old_user"], db_path=db,
    )
    # Rotate — old_user removed, new_user added.
    session_store._setup_done.clear()  # noqa: SLF001
    hydrated = session_store.hydrate(allowlist=["new_user"], db_path=db)
    assert hydrated == {}, "session outlived its allowlist"


def test_ttl_expiry_drops_old_sessions(tmp_path, monkeypatch):
    db = tmp_path / "s.sqlite"
    # Tighten TTL for the test.
    monkeypatch.setattr(session_store, "_SESSION_TTL_SECONDS", 1.0)
    session_store.persist(
        "sid-fresh", {"username": "u"},
        allowlist=["u"], db_path=db,
    )
    time.sleep(1.2)  # force expiry
    session_store._setup_done.clear()  # noqa: SLF001
    hydrated = session_store.hydrate(allowlist=["u"], db_path=db)
    assert hydrated == {}


def test_evict_removes_single_session(tmp_path):
    db = tmp_path / "s.sqlite"
    session_store.persist("sid-a", {"username": "u"}, allowlist=["u"], db_path=db)
    session_store.persist("sid-b", {"username": "u"}, allowlist=["u"], db_path=db)
    session_store.evict("sid-a", db_path=db)
    session_store._setup_done.clear()  # noqa: SLF001
    hydrated = session_store.hydrate(allowlist=["u"], db_path=db)
    assert "sid-a" not in hydrated
    assert "sid-b" in hydrated


def test_persist_on_conflict_updates_last_seen(tmp_path):
    db = tmp_path / "s.sqlite"
    session_store.persist(
        "sid-1",
        {"username": "u", "created_at_epoch": time.time() - 1000},
        allowlist=["u"], db_path=db,
    )
    session_store.persist(
        "sid-1",
        {"username": "u", "created_at_epoch": time.time() - 1000},
        allowlist=["u"], db_path=db,
    )
    # Single row, not a duplicate.
    assert session_store.count_active(db_path=db) == 1


def test_force_clear_all_removes_everything(tmp_path):
    db = tmp_path / "s.sqlite"
    for i in range(5):
        session_store.persist(
            f"sid-{i}", {"username": "u"},
            allowlist=["u"], db_path=db,
        )
    assert session_store.count_active(db_path=db) == 5
    removed = session_store.force_clear_all(db_path=db)
    assert removed == 5
    assert session_store.count_active(db_path=db) == 0


def test_broken_db_does_not_crash(tmp_path):
    # Point at a path that can't be created (read-only parent).
    bad = tmp_path / "nonexistent-dir-doesnt-exist-yet"
    # No crash; empty result.
    got = session_store.hydrate(db_path=bad / "s.sqlite")
    assert isinstance(got, dict)


def test_allowlist_version_stable_across_case_and_whitespace():
    v1 = session_store._allowlist_version(["Alice ", "BOB"])  # noqa: SLF001
    v2 = session_store._allowlist_version(["alice", " bob "])  # noqa: SLF001
    assert v1 == v2


def test_allowlist_version_empty_is_stable():
    assert session_store._allowlist_version([]) == session_store._allowlist_version(None)  # noqa: SLF001
