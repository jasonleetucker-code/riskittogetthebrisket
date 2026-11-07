"""W12-F006 (CW-40 P1) -- RESOLVED by owner decision 2026-11-07: Terminal takes precedence.

The terminal-signal detector and the BDVM detector run back to back in the SAME daily
sweep (``server.py`` ``/api/signal-alerts/run``).  They used to deliver independently, so
one player could produce two emails in one sweep.  Rule now: the user gets at most ONE
notification per (canonical Sleeper player id, user, sweep).  BDVM is suppressed for a
player only when a Terminal email that actually DELIVERED included that player; BDVM
detection and state recording are unchanged and the suppression is reported under
``suppressed`` (``suppressedBy: "terminal"``, both signals, ``directionConflict``).
``custom_alerts`` is a separate route and is not touched.

Offline, real detector + delivery code, a tmp user_kv, a stub transport.
"""

from __future__ import annotations

import pytest

from src.api import bdvm_signal_alerts, signal_alerts, user_kv

LEAGUE = "dynasty_main"
EMAIL = "manager@example.com"


@pytest.fixture()
def kv_path(tmp_path):
    user_kv._SETUP_DONE.clear()
    yield tmp_path / "user_kv.sqlite"
    user_kv._SETUP_DONE.clear()


def _terminal(name="Josh Allen", sid="4017", signal="SELL", tag="elite_stable"):
    return {
        "name": name,
        "pos": "QB",
        "signal": signal,
        "reason": "rank-history spike",
        "tag": tag,
        "signalKey": f"{name}::{tag}",
        "aliasSignalKey": f"sid:{sid}::{tag}" if sid else "",
        "sleeperId": sid,
        "dismissed": False,
    }


def _bdvm(name="Josh Allen", pid="4017", signal="STRONG_BUY"):
    return {
        "playerId": pid,
        "name": name,
        "pos": "QB",
        "signal": signal,
        "reason": "fundamental above market",
        "gap": 900.0,
        "fundamental": 8200.0,
        "marketValue": 7300.0,
    }


class _Transport:
    def __init__(self, fail_first=False):
        self.sent: list[tuple[str, str, str]] = []
        self._fail_first = fail_first

    def __call__(self, to, subject, body):
        if self._fail_first:
            self._fail_first = False
            return False
        self.sent.append((to, subject, body))
        return True


def _seed(kv_path, user="alice", delivery=None):
    seeded = bdvm_signal_alerts.process_user_bdvm_alerts(
        user,
        entries=[{"playerId": "other", "name": "Someone Else", "signal": "HOLD"}],
        email=EMAIL,
        delivery=delivery or _Transport(),
        path=kv_path,
        league_key=LEAGUE,
    )
    assert seeded["reason"] == "baseline_seeded"


def _run_pair(kv_path, terminal_signals, bdvm_entries, *, user="alice", delivery):
    """The two calls ``server.py`` makes per (user, league) in one sweep."""
    r1 = signal_alerts.process_user_alerts(
        user,
        signals=terminal_signals,
        display_name=user,
        email=EMAIL,
        delivery=delivery,
        path=kv_path,
        league_key=LEAGUE,
    )
    r2 = bdvm_signal_alerts.process_user_bdvm_alerts(
        user,
        entries=bdvm_entries,
        display_name=user,
        email=EMAIL,
        delivery=delivery,
        path=kv_path,
        league_key=LEAGUE,
        terminal_notified=r1.get("notifiedPlayerSignals"),
    )
    return r1, r2


def _sweep_one_user(kv_path):
    transport = _Transport()
    _seed(kv_path, delivery=transport)
    r1, r2 = _run_pair(kv_path, [_terminal()], [_bdvm()], delivery=transport)
    return transport.sent, r1, r2


def _bdvm_state(kv_path, user="alice"):
    state = user_kv.get_user_state(user, path=kv_path)
    return state[bdvm_signal_alerts._STATE_FIELD][LEAGUE]


def test_one_player_one_sweep_one_message(kv_path):
    sent, r1, r2 = _sweep_one_user(kv_path)
    assert len([m for m in sent if "Josh Allen" in m[2]]) == 1
    assert "SELL" in sent[0][2] and "STRONG_BUY" not in sent[0][2]  # Terminal wins
    assert r1["delivered"] is True and r2["delivered"] is False
    assert r2["reason"] == "suppressed_by_terminal"


def test_conflicting_directions_keep_evidence_terminal_email_only(kv_path):
    sent, _r1, r2 = _sweep_one_user(kv_path)  # Terminal SELL vs BDVM STRONG_BUY
    (item,) = r2["suppressed"]
    assert item == {
        "playerId": "4017",
        "name": "Josh Allen",
        "suppressedBy": "terminal",
        "terminalSignal": "SELL",
        "bdvmSignal": "STRONG_BUY",
        "directionConflict": True,
    }
    assert len(sent) == 1 and "SELL" in sent[0][2]


def test_same_direction_suppressed_without_conflict(kv_path):
    transport = _Transport()
    _seed(kv_path, delivery=transport)
    _r1, r2 = _run_pair(
        kv_path, [_terminal(signal="BUY")], [_bdvm(signal="BUY")], delivery=transport
    )
    assert len(transport.sent) == 1
    assert r2["suppressed"][0]["directionConflict"] is False


def test_different_players_both_send(kv_path):
    transport = _Transport()
    _seed(kv_path, delivery=transport)
    r1, r2 = _run_pair(
        kv_path,
        [_terminal()],
        [_bdvm(name="Other Guy", pid="9999")],
        delivery=transport,
    )
    assert r1["delivered"] and r2["delivered"] and "suppressed" not in r2
    assert len(transport.sent) == 2


def test_different_users_not_suppressed(kv_path):
    transport = _Transport()
    _seed(kv_path, user="alice", delivery=transport)
    _seed(kv_path, user="bob", delivery=transport)
    # Terminal fires for alice only; bob's BDVM alert for the same player must still send.
    signal_alerts.process_user_alerts(
        "alice",
        signals=[_terminal()],
        email=EMAIL,
        delivery=transport,
        path=kv_path,
        league_key=LEAGUE,
    )
    r_bob = bdvm_signal_alerts.process_user_bdvm_alerts(
        "bob",
        entries=[_bdvm()],
        email=EMAIL,
        delivery=transport,
        path=kv_path,
        league_key=LEAGUE,
        terminal_notified=None,  # bob's own Terminal run delivered nothing
    )
    assert r_bob["delivered"] is True and "suppressed" not in r_bob


def test_missing_canonical_id_does_not_merge(kv_path):
    transport = _Transport()
    _seed(kv_path, delivery=transport)
    r1, r2 = _run_pair(
        kv_path,
        [_terminal(sid="")],  # Terminal row without a Sleeper id
        [_bdvm()],
        delivery=transport,
    )
    assert r1["delivered"] and r1["notifiedPlayerSignals"] == {}
    assert r2["delivered"] is True and "suppressed" not in r2
    assert len(transport.sent) == 2  # fail open to both detectors' existing behaviour


def test_terminal_in_cooldown_bdvm_still_sends(kv_path):
    transport = _Transport()
    _seed(kv_path, delivery=transport)
    # First sweep consumes the Terminal transition (state recorded).
    signal_alerts.process_user_alerts(
        "alice",
        signals=[_terminal()],
        email=EMAIL,
        delivery=transport,
        path=kv_path,
        league_key=LEAGUE,
    )
    transport.sent.clear()
    # Next sweep: Terminal signal unchanged -> no Terminal email; BDVM newly fires.
    r1, r2 = _run_pair(kv_path, [_terminal()], [_bdvm()], delivery=transport)
    assert r1["reason"] == "no_transitions"
    assert r2["delivered"] is True and "suppressed" not in r2
    assert len(transport.sent) == 1 and "STRONG_BUY" in transport.sent[0][2]


def test_terminal_send_failure_does_not_swallow_bdvm(kv_path):
    _seed(kv_path)
    flaky = _Transport(fail_first=True)  # Terminal's send returns False
    r1, r2 = _run_pair(kv_path, [_terminal()], [_bdvm()], delivery=flaky)
    assert r1["delivered"] is False and "notifiedPlayerSignals" not in r1
    assert r2["delivered"] is True and "suppressed" not in r2
    assert len(flaky.sent) == 1 and "STRONG_BUY" in flaky.sent[0][2]


def test_bdvm_state_still_recorded_when_suppressed(kv_path):
    _sent, _r1, r2 = _sweep_one_user(kv_path)
    assert r2["suppressed"]
    st = _bdvm_state(kv_path)["bdvm:4017"]
    assert st["signal"] == "STRONG_BUY" and st["notifiedAt"] > 0
    # Cooldown semantics unchanged: same signal next sweep does not fire.
    again = bdvm_signal_alerts.process_user_bdvm_alerts(
        "alice",
        entries=[_bdvm()],
        email=EMAIL,
        delivery=_Transport(),
        path=kv_path,
        league_key=LEAGUE,
    )
    assert again["reason"] == "no_transitions"


def test_baseline_seeding_unchanged_with_terminal_mapping(kv_path):
    transport = _Transport()
    r = bdvm_signal_alerts.process_user_bdvm_alerts(
        "carol",
        entries=[_bdvm()],
        email=EMAIL,
        delivery=transport,
        path=kv_path,
        league_key=LEAGUE,
        terminal_notified={"4017": "SELL"},
    )
    assert r == {"transitions": 0, "delivered": False, "reason": "baseline_seeded"}
    assert _bdvm_state(kv_path, "carol")["bdvm:4017"] == {
        "signal": "STRONG_BUY",
        "notifiedAt": 0,
    }
    assert transport.sent == []


def test_partial_suppression_sends_remaining_players(kv_path):
    transport = _Transport()
    _seed(kv_path, delivery=transport)
    _r1, r2 = _run_pair(
        kv_path,
        [_terminal()],
        [_bdvm(), _bdvm(name="Other Guy", pid="9999", signal="SELL")],
        delivery=transport,
    )
    assert r2["delivered"] is True and r2["transitions"] == 1
    assert [x["playerId"] for x in r2["suppressed"]] == ["4017"]
    assert "Other Guy" in transport.sent[1][2] and "Josh Allen" not in transport.sent[1][2]
