"""Tests for ``src.api.user_kv`` — durable per-user preference store."""
from __future__ import annotations

import time

import pytest

from src.api import user_kv


@pytest.fixture()
def kv_path(tmp_path):
    return tmp_path / "user_kv.json"


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
