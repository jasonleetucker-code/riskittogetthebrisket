"""The 12-hour cooldown must survive a change of REASON — W12-F005.

``state_key`` was ``aliasSignalKey or signalKey``, and both embed the
firing rule's tag (``sid:<id>::<tag>``).  A different rule was therefore a
different state row with ``prev_signal = ''`` and ``prev_notified_at = 0``,
so the cooldown branch was skipped entirely and the alert fired at once —
and a flip is exactly when the tag changes, so the cooldown never engaged
on the case it exists for.  ``priorSignal`` came back None too, and
``format_alert_email`` printed "— → SELL": a reversal rendered as a
first-ever signal.

Reproduced verbatim from the finding: BUY/uptrend_controlled then
SELL/sustained_downtrend for one player, zero elapsed time.
"""

from __future__ import annotations

import pytest

from src.api import signal_alerts, user_kv


@pytest.fixture()
def kv_path(tmp_path):
    return tmp_path / "user_kv.sqlite"


@pytest.fixture(autouse=True)
def _reset_setup_cache():
    user_kv._SETUP_DONE.clear()
    yield
    user_kv._SETUP_DONE.clear()


def _sig(name, tag, signal, sid="", dismissed=False):
    return {
        "name": name,
        "pos": "QB",
        "signal": signal,
        "reason": f"{signal} reason",
        "tag": tag,
        "signalKey": f"{name}::{tag}",
        "aliasSignalKey": f"sid:{sid}::{tag}" if sid else "",
        "sleeperId": sid,
        "dismissed": dismissed,
    }


def test_flip_to_a_new_reason_is_held_by_the_cooldown(kv_path):
    first = signal_alerts.detect_signal_transitions(
        "alice", [_sig("Josh Allen", "uptrend_controlled", "BUY", sid="4984")], path=kv_path
    )
    second = signal_alerts.detect_signal_transitions(
        "alice", [_sig("Josh Allen", "sustained_downtrend", "SELL", sid="4984")], path=kv_path
    )
    assert len(first) == 1
    assert second == [], "a different rule tag must not bypass the 12h cooldown"


def test_risk_tags_do_not_bypass_each_other(kv_path):
    signal_alerts.detect_signal_transitions(
        "alice", [_sig("Josh Allen", "alert_with_drop", "RISK", sid="4984")], path=kv_path
    )
    second = signal_alerts.detect_signal_transitions(
        "alice", [_sig("Josh Allen", "high_vol_drop", "RISK", sid="4984")], path=kv_path
    )
    assert second == []


def test_prior_signal_is_truthful_across_a_tag_change(kv_path, monkeypatch):
    signal_alerts.detect_signal_transitions(
        "alice", [_sig("Josh Allen", "uptrend_controlled", "BUY", sid="4984")], path=kv_path
    )
    now = signal_alerts._utc_now_ms()
    monkeypatch.setattr(signal_alerts, "_utc_now_ms", lambda: now + 13 * 3600 * 1000)
    later = signal_alerts.detect_signal_transitions(
        "alice", [_sig("Josh Allen", "sustained_downtrend", "SELL", sid="4984")], path=kv_path
    )
    assert len(later) == 1
    assert later[0]["priorSignal"] == "BUY", "a reversal must not read as a first signal"
    body = signal_alerts.format_alert_email("Alice", later)["body"]
    assert "BUY → SELL" in body
    assert "— → SELL" not in body


def test_the_dismissal_key_still_carries_the_tag(kv_path):
    """Dismissal lifecycle keeps following the REASON — that part was right."""
    out = signal_alerts.detect_signal_transitions(
        "alice", [_sig("Josh Allen", "uptrend_controlled", "BUY", sid="4984")], path=kv_path
    )
    assert out[0]["signalKey"] == "sid:4984::uptrend_controlled"
    assert out[0]["cooldownKey"] == "sid:4984"


def test_one_player_two_rows_is_one_alert_and_one_count(kv_path):
    # A two-way player holds an offense row and an IDP row in the same
    # payload; the digest used to say "2 of your players had a signal
    # change" about one player.
    out = signal_alerts.detect_signal_transitions(
        "alice",
        [
            _sig("Travis Hunter", "uptrend_controlled", "BUY", sid="11563"),
            _sig("Travis Hunter", "pos_news_rising", "BUY", sid="11563"),
        ],
        path=kv_path,
    )
    assert len(out) == 1
    email = signal_alerts.format_alert_email("Alice", out)
    assert "1 of your players" in email["body"]
    assert "1 signal update" in email["subject"]


def test_a_stored_tag_keyed_cooldown_still_gates_after_the_key_change(kv_path):
    """Deploy must not drop every existing cooldown and flood the sweep."""
    user_kv.merge_user_state(
        "alice",
        {
            "signalAlertState": {
                "sid:4017::elite_stable": {
                    "signal": "SELL",
                    "notifiedAt": signal_alerts._utc_now_ms(),
                }
            }
        },
        path=kv_path,
    )
    out = signal_alerts.detect_signal_transitions(
        "alice", [_sig("Josh Allen", "sustained_downtrend", "SELL", sid="4017")], path=kv_path
    )
    assert out == []


def test_distinct_players_still_alert_independently(kv_path):
    out = signal_alerts.detect_signal_transitions(
        "alice",
        [
            _sig("Josh Allen", "uptrend_controlled", "BUY", sid="4984"),
            _sig("Ja'Marr Chase", "sustained_downtrend", "SELL", sid="7564"),
        ],
        path=kv_path,
    )
    assert len(out) == 2
