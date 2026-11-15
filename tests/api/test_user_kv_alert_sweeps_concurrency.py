"""Alert sweeps must not lose concurrent updates to the user_kv field they own.

Each sweep below used to read its state with ``get_user_state`` and later
rewrite the WHOLE field (``signalAlertStateByLeague``, ``bdvmSignalAlert...``,
``opsAlertState``, ``sourceHealthAlertState``) from that copy, so a write
landing in between was discarded: one league's cooldowns erased by another
league's sweep, or a delivered alert's cooldown lost so it fired again.  Since
#1704 ``user_kv`` serialises read-modify-write, but only for writers that read
INSIDE the lock (``mutate_user_state``).

Reads are widened deterministically (``_read_row`` sleeps after reading) so
the old interleaving loses an update on every run.
"""

from __future__ import annotations

import threading
import time

import pytest

from src.api import bdvm_signal_alerts as bdvm
from src.api import ops_alerts as oa
from src.api import signal_alerts as sa
from src.api import signal_state_migration as mig
from src.api import source_health_alerts as sha
from src.api import user_kv


@pytest.fixture()
def kv(tmp_path, monkeypatch):
    path = tmp_path / "kv.sqlite"
    user_kv._SETUP_DONE.clear()
    real = user_kv._read_row

    def _slow(conn, username):
        row = real(conn, username)
        time.sleep(0.15)
        return row

    monkeypatch.setattr(user_kv, "_read_row", _slow)
    yield path
    user_kv._SETUP_DONE.clear()


def _race(*calls):
    barrier = threading.Barrier(len(calls))
    errors: list[BaseException] = []

    def _run(fn):
        try:
            barrier.wait()
            fn()
        except BaseException as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=_run, args=(c,)) for c in calls]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors


def _sig(key: str, signal: str = "SELL") -> dict:
    return {"signalKey": key, "signal": signal, "name": key}


def test_terminal_signal_sweeps_for_two_leagues_keep_both_buckets(kv):
    _race(
        lambda: sa.detect_signal_transitions("u", [_sig("p1")], path=kv, league_key="a"),
        lambda: sa.detect_signal_transitions("u", [_sig("p2")], path=kv, league_key="b"),
    )
    by_league = user_kv.get_user_state("u", path=kv)["signalAlertStateByLeague"]
    assert set(by_league) == {"a", "b"}
    assert "p1" in by_league["a"] and "p2" in by_league["b"]


def test_terminal_signal_transitions_are_still_returned(kv):
    out = sa.detect_signal_transitions("u", [_sig("p1")], path=kv, league_key="a")
    assert [t["signalKey"] for t in out] == ["p1"]
    # Same signal again: no transition, last-seen kept.
    assert sa.detect_signal_transitions("u", [_sig("p1")], path=kv, league_key="a") == []


def test_signal_state_migration_keeps_a_concurrent_league_sweep(kv):
    user_kv.set_user_field(
        "u", "signalAlertState", {"old": {"signal": "SELL", "notifiedAt": 5}}, path=kv
    )
    _race(
        lambda: mig.migrate_user("u", default_league_key="main", path=kv),
        lambda: sa.detect_signal_transitions("u", [_sig("p2")], path=kv, league_key="b"),
    )
    state = user_kv.get_user_state("u", path=kv)
    by_league = state["signalAlertStateByLeague"]
    assert set(by_league) == {"main", "b"}
    assert "old" in by_league["main"]
    assert state["signalAlertState"] == {}


def _bdvm(pid: str, signal: str = "BUY") -> dict:
    return {"playerId": pid, "signal": signal, "name": pid}


def test_bdvm_sweeps_for_two_leagues_keep_both_buckets(kv):
    _race(
        lambda: bdvm.detect_bdvm_transitions("u", [_bdvm("p1")], path=kv, league_key="a"),
        lambda: bdvm.detect_bdvm_transitions("u", [_bdvm("p2")], path=kv, league_key="b"),
    )
    by_league = user_kv.get_user_state("u", path=kv)[bdvm._STATE_FIELD]
    assert set(by_league) == {"a", "b"}
    assert "bdvm:p1" in by_league["a"] and "bdvm:p2" in by_league["b"]


def test_bdvm_baseline_then_transition_modes_unchanged(kv):
    t, mode = bdvm.detect_bdvm_transitions("u", [_bdvm("p1")], path=kv, league_key="a")
    assert (t, mode) == ([], "baseline_seeded")
    t, mode = bdvm.detect_bdvm_transitions("u", [_bdvm("p1", "SELL")], path=kv, league_key="a")
    assert mode == "ok" and [x["signalKey"] for x in t] == ["bdvm:p1"]
    assert bdvm.detect_bdvm_transitions("u", [], path=kv, league_key="a") == ([], "no_entries")


def test_concurrent_ops_sweeps_keep_both_delivered_cooldowns(kv):
    def _send(to, subj, body):
        return True

    _race(
        lambda: oa.check_and_alert(
            status_payload={"scrape_success_rate_24h": 0.1},
            delivery=_send,
            to_email="a@b.com",
            kv_path=kv,
        ),
        lambda: oa.check_and_alert(
            data_age_hours=100.0, delivery=_send, to_email="a@b.com", kv_path=kv
        ),
    )
    state = user_kv.get_user_state(oa._OPS_STATE_USER, path=kv)["opsAlertState"]
    assert {"scrape_failure", "data_stale"} <= set(state), state
    assert all(state[c].get("deliveredAt") for c in ("scrape_failure", "data_stale"))


def test_concurrent_source_health_sweeps_alert_once(kv):
    """The cooldown decision is made on the CURRENT state: two overlapping
    sweeps over the same stale source deliver one alert, not two."""
    sends: list[str] = []
    lock = threading.Lock()

    def _send(to, subj, body):
        with lock:
            sends.append(subj)
        return True

    stale = {"ktc": {"lastFetched": "2020-01-01T00:00:00+00:00"}}
    _race(
        lambda: sha.check_and_alert(stale, delivery=_send, to_email="a@b.com", kv_path=kv),
        lambda: sha.check_and_alert(stale, delivery=_send, to_email="a@b.com", kv_path=kv),
    )
    assert len(sends) == 1
    state = user_kv.get_user_state("_system_source_health", path=kv)
    assert state["sourceHealthAlertState"]["ktc"]["currentlyStale"] is True
