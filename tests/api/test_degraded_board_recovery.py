"""Regression tests for the 2026-09-09 degraded-board production incident."""

from __future__ import annotations

import ast
from pathlib import Path

from scripts import verify_live_source_coverage as live_cov
from src.sources.ktc_value_sources import KTC_SOURCE_FILE_KEYS


ROOT = Path(__file__).resolve().parents[2]


def _server_scraper_owned_mirror_files() -> set[str]:
    tree = ast.parse((ROOT / "server.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "scraper_owned_site_raw"
            for target in node.targets
        ):
            continue
        assert isinstance(node.value, (ast.Tuple, ast.List))
        return {
            value.value
            for value in node.value.elts
            if isinstance(value, ast.Constant) and isinstance(value.value, str)
        }
    raise AssertionError("server.py has no scraper_owned_site_raw mirror declaration")


def test_post_scrape_mirror_includes_complete_ktc_three_source_family() -> None:
    mirrored = _server_scraper_owned_mirror_files()
    expected = {
        "ktc.csv",
        "ktcSfTep.csv",
        "idpTradeCalc.csv",
        *(f"{file_key}.csv" for file_key in KTC_SOURCE_FILE_KEYS.values()),
    }
    assert expected <= mirrored


def test_active_reprime_waits_for_healthy_coverage(monkeypatch) -> None:
    statuses = iter(
        [
            {"running": True, "stalled": False, "hung": False, "phase": "degraded"},
            {"running": False, "stalled": False, "hung": False, "phase": "healthy"},
        ]
    )
    calls = []

    def fake_fetch(_base_url: str):
        status = next(statuses)
        calls.append(status["phase"])
        return status

    def fake_coverage(status: dict):
        if status["phase"] == "degraded":
            return [("dlfSf", 0)], [], []
        return [], ["dlfSf"], []

    monkeypatch.setattr(live_cov, "_fetch_status", fake_fetch)
    monkeypatch.setattr(live_cov, "_coverage_result", fake_coverage)
    monkeypatch.setattr(live_cov.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(live_cov, "_COVERAGE_WAIT_ATTEMPTS", 3)
    monkeypatch.setattr(live_cov, "_COVERAGE_WAIT_SLEEP_SECONDS", 0)
    monkeypatch.setattr(live_cov.sys, "argv", ["verify_live_source_coverage.py", "http://localhost"])

    assert live_cov.main() == 0
    assert calls == ["degraded", "healthy"]


def test_idle_degraded_board_fails_without_wait_loop(monkeypatch) -> None:
    calls = []

    def fake_fetch(_base_url: str):
        calls.append("fetch")
        return {"running": False, "stalled": False, "hung": False}

    monkeypatch.setattr(live_cov, "_fetch_status", fake_fetch)
    monkeypatch.setattr(
        live_cov,
        "_coverage_result",
        lambda _status: ([("dlfSf", 0)], [], []),
    )
    monkeypatch.setattr(live_cov.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(live_cov, "_COVERAGE_WAIT_ATTEMPTS", 3)
    monkeypatch.setattr(live_cov.sys, "argv", ["verify_live_source_coverage.py", "http://localhost"])

    assert live_cov.main() == 1
    assert calls == ["fetch"]


def test_stalled_scrape_does_not_mask_degraded_board(monkeypatch) -> None:
    calls = []

    def fake_fetch(_base_url: str):
        calls.append("fetch")
        return {"running": True, "stalled": True, "hung": True}

    monkeypatch.setattr(live_cov, "_fetch_status", fake_fetch)
    monkeypatch.setattr(
        live_cov,
        "_coverage_result",
        lambda _status: ([("dlfSf", 0)], [], []),
    )
    monkeypatch.setattr(live_cov.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(live_cov, "_COVERAGE_WAIT_ATTEMPTS", 3)
    monkeypatch.setattr(live_cov.sys, "argv", ["verify_live_source_coverage.py", "http://localhost"])

    assert live_cov.main() == 1
    assert calls == ["fetch"]
