"""AMATH-S01 / CW-15: the AL-4a + AL-3b ledger is scheduled, final-only and idempotent."""

from __future__ import annotations

import json
from pathlib import Path

from scripts import run_forecast_calibration_ledger as ledger

_REPO = Path(__file__).resolve().parents[2]
_SYSTEMD = _REPO / "deploy" / "systemd"


def _state(week: int, kind: str = "regular", season: int = 2026) -> dict:
    return {"season": str(season), "season_type": kind, "week": week}


class _Calls:
    def __init__(self, code: int = 0) -> None:
        self.calls: list[list[str]] = []
        self.code = code

    def __call__(self, argv: list[str]) -> int:
        self.calls.append(argv)
        return self.code


def _run(tmp_path, state, a=None, b=None, **kw):
    a, b = a or _Calls(), b or _Calls()
    rc = ledger.run(
        state=state,
        marker_path=tmp_path / "m.json",
        al4a=a,
        al3b=b,
        leagues=["dynasty_main"],
        **kw,
    )
    return rc, a, b


def test_refuses_when_no_week_is_final(tmp_path):
    rc, a, b = _run(tmp_path, _state(1))  # week 1 in progress -> nothing final
    assert rc == 0 and not a.calls and not b.calls
    assert not (tmp_path / "m.json").exists()


def test_unreadable_state_is_not_final(tmp_path):
    rc, a, b = _run(tmp_path, None)
    assert rc == 1 and not a.calls and not b.calls


def test_runs_once_per_final_week_then_is_idempotent(tmp_path):
    rc, a, b = _run(tmp_path, _state(9))  # weeks 1..8 final
    assert rc == 0 and len(a.calls) == 1 and len(b.calls) == 1
    assert json.loads((tmp_path / "m.json").read_text(encoding="utf-8"))["lastFinalWeek"] == 8
    rc, a2, b2 = _run(tmp_path, _state(9))
    assert rc == 0 and not a2.calls and not b2.calls
    rc, a3, _ = _run(tmp_path, _state(10))  # next week finalizes -> runs again
    assert len(a3.calls) == 1


def test_failure_does_not_advance_marker(tmp_path):
    rc, _, _ = _run(tmp_path, _state(9), a=_Calls(1))
    assert rc == 1 and not (tmp_path / "m.json").exists()


def test_force_reruns_a_scored_week(tmp_path):
    _run(tmp_path, _state(9))
    _, a, _ = _run(tmp_path, _state(9), force=True)
    assert len(a.calls) == 1


def test_postseason_means_regular_season_complete(tmp_path):
    assert ledger.last_final_week(_state(1, "post")) == (2026, 18)


def test_timer_and_service_templates_exist_and_are_wired():
    svc = _SYSTEMD / "dynasty-forecast-calibration-ledger.service.template"
    tmr = _SYSTEMD / "dynasty-forecast-calibration-ledger.timer.template"
    assert svc.is_file() and tmr.is_file()
    assert "run_forecast_calibration_ledger.py" in svc.read_text(encoding="utf-8")
    assert "__SERVICE_NAME__-forecast-calibration-ledger.service" in tmr.read_text(encoding="utf-8")
    installer = (_REPO / "deploy" / "install-systemd-service.sh").read_text(encoding="utf-8")
    assert 'install_simple_timer "forecast-calibration-ledger"' in installer
