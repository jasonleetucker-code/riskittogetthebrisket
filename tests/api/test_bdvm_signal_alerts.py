"""BDVM market-signal transition alerts.

The cases that matter, in order:

1. Baseline seeding — the first sweep after the bdvm_engine flag turns
   on must NOT flood the user with an alert for every rostered player
   already sitting in BUY/SELL; it records state silently.
2. A genuine transition right after baseline fires immediately (the
   seeded notifiedAt is 0, not "now").
3. The same-signal / flicker-guard / per-league-isolation semantics
   mirror signal_alerts.py exactly — proven idioms, same tests.
4. Roster scoping: the board is league-wide; entries are the
   intersection with one roster's playerIds, and a non-ok board yields
   nothing (never fabricated).
"""

from __future__ import annotations

import pytest

from src.api import bdvm_signal_alerts as mod
from src.api import user_kv


@pytest.fixture()
def kv_path(tmp_path):
    user_kv._SETUP_DONE.clear()
    return tmp_path / "user_kv.sqlite"


def _entry(pid, signal, name="Elite Backer", **kw):
    return {
        "playerId": pid,
        "name": name,
        "pos": kw.get("pos", "LB"),
        "signal": signal,
        "reason": kw.get("reason", "gap above threshold"),
        "gap": kw.get("gap", 800.0),
        "fundamental": kw.get("fundamental", 7200.0),
        "marketValue": kw.get("marketValue", 6400.0),
    }


class TestBaselineSeeding:
    def test_first_sweep_seeds_without_firing(self, kv_path):
        entries = [_entry("p1", "BUY"), _entry("p2", "STRONG_SELL", name="Old Vet")]
        transitions, mode = mod.detect_bdvm_transitions(
            "u", entries, path=kv_path, league_key="dynasty_main"
        )
        assert mode == "baseline_seeded"
        assert transitions == []
        state = user_kv.get_user_state("u", path=kv_path)
        bucket = state["bdvmSignalAlertStateByLeague"]["dynasty_main"]
        assert bucket["bdvm:p1"] == {"signal": "BUY", "notifiedAt": 0}
        assert bucket["bdvm:p2"]["signal"] == "STRONG_SELL"

    def test_baseline_ignores_non_actionable(self, kv_path):
        entries = [_entry("p1", "HOLD"), _entry("p2", "NO_MARKET")]
        _t, mode = mod.detect_bdvm_transitions(
            "u", entries, path=kv_path, league_key="dynasty_main"
        )
        assert mode == "baseline_seeded"
        bucket = user_kv.get_user_state("u", path=kv_path)["bdvmSignalAlertStateByLeague"][
            "dynasty_main"
        ]
        assert bucket == {}

    def test_change_right_after_baseline_fires(self, kv_path):
        mod.detect_bdvm_transitions(
            "u", [_entry("p1", "BUY")], path=kv_path, league_key="dynasty_main"
        )
        transitions, mode = mod.detect_bdvm_transitions(
            "u", [_entry("p1", "STRONG_SELL")], path=kv_path, league_key="dynasty_main"
        )
        assert mode == "ok"
        assert len(transitions) == 1
        assert transitions[0]["priorSignal"] == "BUY"
        assert transitions[0]["signal"] == "STRONG_SELL"


class TestTransitions:
    def _seed(self, kv_path, league="dynasty_main"):
        mod.detect_bdvm_transitions("u", [_entry("p1", "BUY")], path=kv_path, league_key=league)

    def test_unchanged_signal_does_not_fire(self, kv_path):
        self._seed(kv_path)
        transitions, mode = mod.detect_bdvm_transitions(
            "u", [_entry("p1", "BUY")], path=kv_path, league_key="dynasty_main"
        )
        assert mode == "ok"
        assert transitions == []

    def test_new_player_flip_to_actionable_fires(self, kv_path):
        self._seed(kv_path)
        # p9 was HOLD (untracked) at baseline; now BUY
        transitions, _ = mod.detect_bdvm_transitions(
            "u", [_entry("p9", "BUY", name="Riser")], path=kv_path, league_key="dynasty_main"
        )
        assert [t["playerId"] for t in transitions] == ["p9"]
        assert transitions[0]["priorSignal"] is None

    def test_flicker_within_cooldown_is_suppressed(self, kv_path):
        self._seed(kv_path)
        # fire once (BUY → SELL) — notifiedAt stamps "now"
        first, _ = mod.detect_bdvm_transitions(
            "u", [_entry("p1", "SELL")], path=kv_path, league_key="dynasty_main"
        )
        assert len(first) == 1
        # immediate flip back — suppressed, but last-seen updated
        second, _ = mod.detect_bdvm_transitions(
            "u", [_entry("p1", "BUY")], path=kv_path, league_key="dynasty_main"
        )
        assert second == []
        bucket = user_kv.get_user_state("u", path=kv_path)["bdvmSignalAlertStateByLeague"][
            "dynasty_main"
        ]
        assert bucket["bdvm:p1"]["signal"] == "BUY"

    def test_fires_again_after_cooldown(self, kv_path, monkeypatch):
        self._seed(kv_path)
        mod.detect_bdvm_transitions(
            "u", [_entry("p1", "SELL")], path=kv_path, league_key="dynasty_main"
        )
        later = mod._utc_now_ms() + int(13 * 3600 * 1000)
        monkeypatch.setattr(mod, "_utc_now_ms", lambda: later)
        transitions, _ = mod.detect_bdvm_transitions(
            "u", [_entry("p1", "BUY")], path=kv_path, league_key="dynasty_main"
        )
        assert len(transitions) == 1
        assert transitions[0]["priorSignal"] == "SELL"

    def test_cooldown_is_scoped_per_league(self, kv_path):
        self._seed(kv_path, league="dynasty_main")
        self._seed(kv_path, league="second_league")
        a, _ = mod.detect_bdvm_transitions(
            "u", [_entry("p1", "SELL")], path=kv_path, league_key="dynasty_main"
        )
        b, _ = mod.detect_bdvm_transitions(
            "u", [_entry("p1", "SELL")], path=kv_path, league_key="second_league"
        )
        assert len(a) == 1 and len(b) == 1  # independent buckets

    def test_no_entries_leaves_state_untouched(self, kv_path):
        transitions, mode = mod.detect_bdvm_transitions(
            "u", [], path=kv_path, league_key="dynasty_main"
        )
        assert (transitions, mode) == ([], "no_entries")
        state = user_kv.get_user_state("u", path=kv_path)
        assert "bdvmSignalAlertStateByLeague" not in state


class TestRosterEntries:
    def _payload(self):
        return {
            "status": "ok",
            "players": [
                {
                    "playerId": "p1",
                    "name": "Elite Backer",
                    "position": "LB",
                    "signal": {"signal": "BUY", "reason": "gap"},
                    "market": {"gap": 800.0, "marketValue": 6400.0},
                    "tradeValue": {"balanced": 7200.0},
                },
                {
                    "playerId": "p2",
                    "name": "Other Team Guy",
                    "position": "WR",
                    "signal": {"signal": "SELL", "reason": "x"},
                    "market": {"gap": -500.0, "marketValue": 5000.0},
                    "tradeValue": {"balanced": 4500.0},
                },
            ],
        }

    def test_intersects_with_roster(self):
        entries = mod.roster_bdvm_entries(self._payload(), ["p1"])
        assert [e["playerId"] for e in entries] == ["p1"]
        assert entries[0]["signal"] == "BUY"
        assert entries[0]["fundamental"] == 7200.0

    def test_non_ok_board_yields_nothing(self):
        assert mod.roster_bdvm_entries({"status": "no_projection_snapshot"}, ["p1"]) == []
        assert mod.roster_bdvm_entries(None, ["p1"]) == []

    def test_empty_roster_yields_nothing(self):
        assert mod.roster_bdvm_entries(self._payload(), []) == []


class TestProcessAndEmail:
    def test_process_reports_baseline(self, kv_path):
        out = mod.process_user_bdvm_alerts(
            "u",
            entries=[_entry("p1", "BUY")],
            email="a@b.c",
            delivery=lambda *a: True,
            path=kv_path,
            league_key="dynasty_main",
        )
        assert out == {"transitions": 0, "delivered": False, "reason": "baseline_seeded"}

    def test_process_delivers_transition(self, kv_path):
        sent = []

        def stub(to, subject, body):
            sent.append((to, subject, body))
            return True

        mod.process_user_bdvm_alerts(
            "u",
            entries=[_entry("p1", "BUY")],
            email="a@b.c",
            delivery=stub,
            path=kv_path,
            league_key="dynasty_main",
        )
        out = mod.process_user_bdvm_alerts(
            "u",
            entries=[_entry("p1", "STRONG_SELL")],
            display_name="Jason",
            email="a@b.c",
            delivery=stub,
            path=kv_path,
            league_key="dynasty_main",
        )
        assert out["delivered"] is True and out["reason"] == "ok"
        to, subject, body = sent[0]
        assert to == "a@b.c"
        assert "1 BDVM market signal change" in subject
        assert "BUY → STRONG_SELL" in body
        assert "fundamental 7,200 vs market 6,400 (gap +800)" in body
        assert "/bdvm" in body

    def test_no_email_reason(self, kv_path):
        mod.detect_bdvm_transitions(
            "u", [_entry("p1", "BUY")], path=kv_path, league_key="dynasty_main"
        )
        out = mod.process_user_bdvm_alerts(
            "u",
            entries=[_entry("p1", "SELL")],
            email="",
            path=kv_path,
            league_key="dynasty_main",
        )
        assert out["reason"] == "no_email"

    def test_delivery_error_reason(self, kv_path):
        mod.detect_bdvm_transitions(
            "u", [_entry("p1", "BUY")], path=kv_path, league_key="dynasty_main"
        )

        def boom(*_a):
            raise RuntimeError("smtp down")

        out = mod.process_user_bdvm_alerts(
            "u",
            entries=[_entry("p1", "SELL")],
            email="a@b.c",
            delivery=boom,
            path=kv_path,
            league_key="dynasty_main",
        )
        assert out["reason"] == "delivery_error:RuntimeError"
        assert out["delivered"] is False

    def test_email_formats_prior_none_and_negative_gap(self):
        formatted = mod.format_bdvm_alert_email(
            "Jason",
            [
                {
                    "name": "Faller",
                    "pos": "WR",
                    "signal": "SELL",
                    "priorSignal": None,
                    "reason": "",
                    "gap": -350.0,
                    "fundamental": 4000.0,
                    "marketValue": 4350.0,
                }
            ],
        )
        assert "— → SELL" in formatted["body"]
        assert "(gap -350)" in formatted["body"]


def _sweep(c, monkeypatch, server):
    monkeypatch.setattr(server, "latest_contract_data", {"players": {}})
    monkeypatch.setattr(server, "SIGNAL_ALERT_CRON_TOKEN", "test-token-abc123")
    monkeypatch.setattr(server._user_kv, "all_user_states", lambda: {})
    return c.post(
        "/api/signal-alerts/run",
        headers={"Authorization": "Bearer test-token-abc123"},
    )


def test_sweep_reports_flag_state_and_stays_green_when_off(monkeypatch):
    """The OFF path is the documented rollback, so it stays tested —
    now via the env override, since bdvm_engine ships ON as of
    2026-07-28.  The detector must add zero risk to the existing digest
    when the feature is dormant."""
    from fastapi.testclient import TestClient

    import server
    from src.api import feature_flags

    monkeypatch.setenv("RISKIT_FEATURE_BDVM_ENGINE", "0")
    feature_flags.reload()
    try:
        with TestClient(server.app, raise_server_exceptions=True) as c:
            # Patch AFTER lifespan so startup can't clobber the stubs
            # (see test_signal_alerts.py for the rationale).
            res = _sweep(c, monkeypatch, server)
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["bdvmEnabled"] is False
        assert body["results"] == []
    finally:
        monkeypatch.delenv("RISKIT_FEATURE_BDVM_ENGINE", raising=False)
        feature_flags.reload()


def test_sweep_stays_green_with_the_flag_on(monkeypatch):
    """The path that is now the DEFAULT.

    Flag-on day runs this sweep against every user.  It must stay green
    and stamp bdvmEnabled=true — a BDVM-leg failure degrades to an error
    stamped on the league summary, never a failed digest for everyone.
    """
    from fastapi.testclient import TestClient

    import server
    from src.api import feature_flags

    feature_flags.reload()
    assert feature_flags.is_enabled("bdvm_engine"), "default should be ON here"
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = _sweep(c, monkeypatch, server)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["bdvmEnabled"] is True
    assert body["results"] == []
