"""Master-site-audit W12-F006 regression (CW-40 P1 re-adjudication, 2026-11-06) -- OPEN.

Claim: the terminal-signal detector and the BDVM detector (both run back to back in the
SAME daily sweep, ``server.py`` ``/api/signal-alerts/run``) deliver independently to the
same address with separate cooldown namespaces, so one player can produce two emails
in one sweep.  ``custom_alerts`` is a third, separate route.

Reproduction (offline, real detector + delivery code, a tmp user_kv, a stub transport):
seed the BDVM baseline, then show one player to both detectors in one pass.

Nothing in ``src/api/signal_alerts.py`` / ``bdvm_signal_alerts.py`` / the sweep in
``server.py`` knows the other exists, so today two messages go out.  The strict xfail
states the correct behavior (at most one message per user per player per sweep); it
flips when a cross-detector gate lands.  Which of the two messages should win, or
whether they merge, is an owner product call (vocabularies are disjoint and can
disagree: RISK/SELL/BUY/MONITOR vs STRONG_BUY..STRONG_SELL).
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


def _sweep_one_user(kv_path):
    """The two calls ``server.py`` makes per (user, league) in one sweep, same ``email``."""
    sent: list[tuple[str, str, str]] = []

    def delivery(to, subject, body):
        sent.append((to, subject, body))
        return True

    # BDVM baseline seeding happens on an earlier sweep (flag-on day).
    seeded = bdvm_signal_alerts.process_user_bdvm_alerts(
        "alice",
        entries=[{"playerId": "other", "name": "Someone Else", "signal": "HOLD"}],
        email=EMAIL,
        delivery=delivery,
        path=kv_path,
        league_key=LEAGUE,
    )
    assert seeded["reason"] == "baseline_seeded"
    terminal_signal = {
        "name": "Josh Allen",
        "pos": "QB",
        "signal": "SELL",
        "reason": "rank-history spike",
        "tag": "elite_stable",
        "signalKey": "Josh Allen::elite_stable",
        "aliasSignalKey": "sid:4017::elite_stable",
        "sleeperId": "4017",
        "dismissed": False,
    }
    bdvm_entry = {
        "playerId": "4017",
        "name": "Josh Allen",
        "pos": "QB",
        "signal": "STRONG_BUY",
        "reason": "fundamental above market",
        "gap": 900.0,
        "fundamental": 8200.0,
        "marketValue": 7300.0,
    }
    r1 = signal_alerts.process_user_alerts(
        "alice",
        signals=[terminal_signal],
        display_name="alice",
        email=EMAIL,
        delivery=delivery,
        path=kv_path,
        league_key=LEAGUE,
    )
    r2 = bdvm_signal_alerts.process_user_bdvm_alerts(
        "alice",
        entries=[bdvm_entry],
        display_name="alice",
        email=EMAIL,
        delivery=delivery,
        path=kv_path,
        league_key=LEAGUE,
    )
    return sent, r1, r2


def test_each_detector_delivers_on_its_own_today(kv_path):
    sent, r1, r2 = _sweep_one_user(kv_path)
    assert r1["delivered"] is True and r2["delivered"] is True
    assert len(sent) == 2  # the measured defect: two emails, same address, same player
    assert {m[0] for m in sent} == {EMAIL}
    assert all("Josh Allen" in m[2] for m in sent)
    # opposite-capable vocabularies, nothing cross-references the other detector
    assert "SELL" in sent[0][2] and "STRONG_BUY" in sent[1][2]


@pytest.mark.xfail(
    strict=True,
    reason="W12-F006 OPEN: no cross-detector gate; one player in one sweep emails twice",
)
def test_one_player_one_sweep_one_message(kv_path):
    sent, _r1, _r2 = _sweep_one_user(kv_path)
    assert len([m for m in sent if "Josh Allen" in m[2]]) <= 1
