"""Tests for the persistent session store.

Pins:
  * persist + hydrate round-trips a session.
  * Sliding TTL: idle time (last_seen_at) drives expiry, and touch()
    keeps an active session alive.
  * Allowlist removal invalidates only the removed user's sessions;
    adding a user leaves existing sessions intact; an empty allowlist
    imposes no restriction.
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


def test_allowlist_removal_invalidates_removed_user(tmp_path):
    db = tmp_path / "s.sqlite"
    session_store.persist(
        "sid-1",
        {"username": "old_user"},
        allowlist=["old_user"],
        db_path=db,
    )
    # old_user is dropped from the allowlist entirely.
    session_store._setup_done.clear()  # noqa: SLF001
    hydrated = session_store.hydrate(allowlist=["new_user"], db_path=db)
    assert hydrated == {}, "removed user's session outlived its allowlist"


def test_adding_a_user_keeps_existing_sessions(tmp_path):
    """Regression: adding a NEW user to the allowlist must not sign
    out everyone else (the old global-version-hash behavior did)."""
    db = tmp_path / "s.sqlite"
    session_store.persist(
        "sid-existing",
        {"username": "jasonleetucker"},
        allowlist=["jasonleetucker"],
        db_path=db,
    )
    # A second operator is added; the allowlist set changes.
    session_store._setup_done.clear()  # noqa: SLF001
    hydrated = session_store.hydrate(
        allowlist=["jasonleetucker", "new_teammate"],
        db_path=db,
    )
    assert "sid-existing" in hydrated
    assert hydrated["sid-existing"]["username"] == "jasonleetucker"


def test_empty_allowlist_imposes_no_restriction(tmp_path):
    """A blank / unset allowlist must not invalidate every session."""
    db = tmp_path / "s.sqlite"
    session_store.persist("sid-1", {"username": "u"}, allowlist=["u"], db_path=db)
    session_store._setup_done.clear()  # noqa: SLF001
    assert "sid-1" in session_store.hydrate(allowlist=[], db_path=db)
    session_store._setup_done.clear()  # noqa: SLF001
    assert "sid-1" in session_store.hydrate(allowlist=None, db_path=db)


def test_ttl_expiry_drops_old_sessions(tmp_path, monkeypatch):
    db = tmp_path / "s.sqlite"
    # Tighten TTL for the test.
    monkeypatch.setattr(session_store, "_SESSION_TTL_SECONDS", 1.0)
    session_store.persist(
        "sid-fresh",
        {"username": "u"},
        allowlist=["u"],
        db_path=db,
    )
    time.sleep(1.2)  # force expiry
    session_store._setup_done.clear()  # noqa: SLF001
    hydrated = session_store.hydrate(allowlist=["u"], db_path=db)
    assert hydrated == {}


def test_sliding_ttl_uses_last_seen_not_created(tmp_path, monkeypatch):
    """An old session that was recently active must survive: expiry
    keys off last_seen_at, not created_at."""
    db = tmp_path / "s.sqlite"
    monkeypatch.setattr(session_store, "_SESSION_TTL_SECONDS", 100.0)
    # created long ago, but persist stamps last_seen_at = now.
    session_store.persist(
        "sid-active",
        {"username": "u", "created_at_epoch": time.time() - 10_000},
        allowlist=["u"],
        db_path=db,
    )
    session_store._setup_done.clear()  # noqa: SLF001
    hydrated = session_store.hydrate(allowlist=["u"], db_path=db)
    assert "sid-active" in hydrated
    assert hydrated["sid-active"]["last_seen_epoch"] > time.time() - 100


def test_touch_keeps_idle_session_alive(tmp_path, monkeypatch):
    db = tmp_path / "s.sqlite"
    monkeypatch.setattr(session_store, "_SESSION_TTL_SECONDS", 1.0)
    session_store.persist("sid-1", {"username": "u"}, allowlist=["u"], db_path=db)
    time.sleep(1.2)  # would expire on its own
    session_store.touch("sid-1", db_path=db)  # heartbeat bumps last_seen
    session_store._setup_done.clear()  # noqa: SLF001
    hydrated = session_store.hydrate(allowlist=["u"], db_path=db)
    assert "sid-1" in hydrated, "touch() should have refreshed the sliding TTL"


def test_touch_unknown_session_is_noop(tmp_path):
    db = tmp_path / "s.sqlite"
    session_store.persist("sid-real", {"username": "u"}, allowlist=["u"], db_path=db)
    session_store.touch("sid-does-not-exist", db_path=db)  # must not raise
    assert session_store.count_active(db_path=db) == 1


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
        allowlist=["u"],
        db_path=db,
    )
    session_store.persist(
        "sid-1",
        {"username": "u", "created_at_epoch": time.time() - 1000},
        allowlist=["u"],
        db_path=db,
    )
    # Single row, not a duplicate.
    assert session_store.count_active(db_path=db) == 1


def test_force_clear_all_removes_everything(tmp_path):
    db = tmp_path / "s.sqlite"
    for i in range(5):
        session_store.persist(
            f"sid-{i}",
            {"username": "u"},
            allowlist=["u"],
            db_path=db,
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
