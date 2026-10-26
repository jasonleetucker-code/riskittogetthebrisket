"""user_kv read-modify-write writers must not lose concurrent updates (#1704 D2).

Every writer rewrites one JSON blob per user.  Under sqlite3's default deferred
transactions the SELECT ran outside the write transaction, so two concurrent
writers both read the old blob and the second commit silently discarded the
first's change — the review measured 137/200 trials losing a league's trade
protections.  ``BEGIN IMMEDIATE`` before the read serialises them.
"""

from __future__ import annotations

import threading

import pytest

from src.api import user_kv

TRIALS = 40


@pytest.fixture()
def kv_path(tmp_path, monkeypatch):
    path = tmp_path / "user_kv.sqlite"
    monkeypatch.setattr(user_kv, "USER_KV_PATH", path)
    user_kv._SETUP_DONE.clear()
    return path


def _race(*writers):
    """Run every writer at once, released together by a barrier."""
    barrier = threading.Barrier(len(writers))
    errors: list[BaseException] = []

    def _run(fn):
        try:
            barrier.wait()
            fn()
        except BaseException as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=_run, args=(w,)) for w in writers]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors


def test_concurrent_writers_never_lose_each_others_fields(kv_path):
    lost = 0
    for i in range(TRIALS):
        user = f"u{i}"
        user_kv.set_user_field(user, "seed", 0, path=kv_path)
        _race(
            lambda: user_kv.set_league_scoped_entry(
                user, "tradeConstraintsByLeague", "a", {"nflTeams": ["MIN"]}, path=kv_path
            ),
            lambda: user_kv.set_league_scoped_entry(
                user, "tradeConstraintsByLeague", "b", {"nflTeams": ["BUF"]}, path=kv_path
            ),
            lambda: user_kv.merge_user_state(user, {"watchlist": ["X"]}, path=kv_path),
            lambda: user_kv.set_user_field(user, "notificationsEnabled", True, path=kv_path),
        )
        state = user_kv.get_user_state(user, path=kv_path)
        by_league = state.get("tradeConstraintsByLeague") or {}
        if (
            set(by_league) != {"a", "b"}
            or state.get("watchlist") != ["X"]
            or state.get("notificationsEnabled") is not True
        ):
            lost += 1
    assert lost == 0, f"{lost}/{TRIALS} trials lost a concurrent update"


def test_concurrent_league_dismissals_are_both_kept(kv_path):
    lost = 0
    for i in range(TRIALS):
        user = f"d{i}"
        user_kv.set_user_field(user, "seed", 0, path=kv_path)
        _race(
            lambda: user_kv.dismiss_signal(user, "sig1", league_key="a", path=kv_path),
            lambda: user_kv.dismiss_signal(user, "sig2", league_key="b", path=kv_path),
            lambda: user_kv.set_league_scoped_entry(
                user, "tradeConstraintsByLeague", "a", {"nflTeams": ["MIN"]}, path=kv_path
            ),
        )
        state = user_kv.get_user_state(user, path=kv_path)
        dismissed = state.get("dismissedSignalsByLeague") or {}
        if (
            "sig1" not in (dismissed.get("a") or {})
            or "sig2" not in (dismissed.get("b") or {})
            or "a" not in (state.get("tradeConstraintsByLeague") or {})
        ):
            lost += 1
    assert lost == 0, f"{lost}/{TRIALS} trials lost a concurrent update"


def test_a_failed_mutation_rolls_back_and_releases_the_lock(kv_path):
    user_kv.set_user_field("r", "keep", 1, path=kv_path)

    def _boom(entry):
        entry["keep"] = 2
        raise RuntimeError("mutation failed")

    with pytest.raises(RuntimeError):
        user_kv._mutate_user_state("r", _boom, path=kv_path)
    # Nothing persisted, and the next writer is not blocked by a held lock.
    user_kv.set_user_field("r", "other", True, path=kv_path)
    state = user_kv.get_user_state("r", path=kv_path)
    assert state["keep"] == 1 and state["other"] is True
