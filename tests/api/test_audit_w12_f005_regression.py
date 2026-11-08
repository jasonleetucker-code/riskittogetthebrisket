"""W12-F005: the 12-hour alert cooldown belongs to the PLAYER, not the rule tag.

A flip that arrives with a different firing rule used to be a brand-new state
row (no ``notifiedAt``, no prior signal), so the cooldown never engaged.  These
tests pin the repaired behaviour; PR #2111's W12-F005 strict xfails state the
same intent and must be flipped when both land.
"""

from __future__ import annotations

import pytest

from src.api import signal_alerts, user_kv


@pytest.fixture()
def kv_path(tmp_path):
    user_kv._SETUP_DONE.clear()
    yield tmp_path / "user_kv.sqlite"
    user_kv._SETUP_DONE.clear()


def _sig(name, tag, signal, sid):
    return {
        "name": name,
        "pos": "QB",
        "signal": signal,
        "reason": f"{signal} reason",
        "tag": tag,
        "signalKey": f"{name}::{tag}",
        "aliasSignalKey": f"sid:{sid}::{tag}" if sid else "",
        "sleeperId": sid,
        "dismissed": False,
    }


def _detect(kv_path, sig, user="alice", league="dynasty_main"):
    return signal_alerts.detect_signal_transitions(user, [sig], path=kv_path, league_key=league)


def _advance(monkeypatch, hours):
    now = signal_alerts._utc_now_ms()
    monkeypatch.setattr(signal_alerts, "_utc_now_ms", lambda: now + int(hours * 3600 * 1000))


def test_tag_change_within_cooldown_does_not_realert(kv_path):
    assert len(_detect(kv_path, _sig("Josh Allen", "uptrend_controlled", "BUY", "4017"))) == 1
    assert _detect(kv_path, _sig("Josh Allen", "sustained_downtrend", "SELL", "4017")) == []


def test_same_signal_new_tag_does_not_realert(kv_path):
    assert len(_detect(kv_path, _sig("Josh Allen", "rule_a", "SELL", "4017"))) == 1
    assert _detect(kv_path, _sig("Josh Allen", "rule_b", "SELL", "4017")) == []


def test_direction_flip_within_cooldown_is_held(kv_path):
    # The cooldown comment: it exists to stop a RISK -> SELL -> RISK flicker.
    assert len(_detect(kv_path, _sig("Josh Allen", "rule_a", "RISK", "4017"))) == 1
    assert _detect(kv_path, _sig("Josh Allen", "rule_b", "SELL", "4017")) == []


def test_after_expiry_flip_alerts_with_prior_signal(kv_path, monkeypatch):
    _detect(kv_path, _sig("Josh Allen", "uptrend_controlled", "BUY", "4017"))
    _advance(monkeypatch, 13)
    out = _detect(kv_path, _sig("Josh Allen", "sustained_downtrend", "SELL", "4017"))
    assert len(out) == 1
    assert out[0]["signal"] == "SELL"
    assert out[0]["priorSignal"] == "BUY"


def test_name_fallback_when_no_sleeper_id(kv_path):
    assert len(_detect(kv_path, _sig("Josh Allen", "rule_a", "BUY", ""))) == 1
    assert _detect(kv_path, _sig("Josh Allen", "rule_b", "SELL", "")) == []


def test_other_player_user_league_unaffected(kv_path):
    assert len(_detect(kv_path, _sig("Josh Allen", "rule_a", "BUY", "4017"))) == 1
    assert len(_detect(kv_path, _sig("Lamar Jackson", "rule_b", "SELL", "4881"))) == 1
    assert len(_detect(kv_path, _sig("Josh Allen", "rule_a", "BUY", "4017"), user="bob")) == 1
    other = _detect(kv_path, _sig("Josh Allen", "rule_b", "SELL", "4017"), league="dynasty_new")
    assert len(other) == 1


def test_failed_delivery_does_not_consume_cooldown(kv_path):
    sig = _sig("Josh Allen", "rule_a", "BUY", "4017")

    def boom(to, s, b):
        raise RuntimeError("smtp down")

    r = signal_alerts.process_user_alerts(
        "alice", signals=[sig], email="a@x.com", delivery=boom, path=kv_path, league_key="L"
    )
    assert r["delivered"] is False
    sent = []
    r2 = signal_alerts.process_user_alerts(
        "alice",
        signals=[_sig("Josh Allen", "rule_b", "BUY", "4017")],
        email="a@x.com",
        delivery=lambda to, s, b: sent.append(s) or True,
        path=kv_path,
        league_key="L",
    )
    assert r2["delivered"] is True and len(sent) == 1
    # And the successful send now holds the cooldown.
    assert _detect(kv_path, _sig("Josh Allen", "rule_c", "SELL", "4017"), league="L") == []


def test_false_return_also_restores_state(kv_path):
    sig = _sig("Josh Allen", "rule_a", "BUY", "4017")
    r = signal_alerts.process_user_alerts(
        "alice", signals=[sig], email="a@x.com", delivery=lambda *a: False, path=kv_path
    )
    assert r["reason"] == "delivery_returned_false"
    assert len(_detect(kv_path, sig, league="")) == 1
