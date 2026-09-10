"""Unit tests for ``scripts/verify_live_source_coverage.py``'s bounded
recovery loop.

Regression target: the 2026-09-09 production incident.  PR #1321 added a
bounded (61 x 5s) recovery window so the deploy's served-source-coverage
gate tolerates a startup scrape that is still republishing sources.  The
loop worked correctly for ordinary "server responded, sources still
missing" rounds -- but the very next round, ``/api/status`` itself went
fully unreachable (a synchronous KTC scrape step blocking the process),
and ``main()`` did ``if status is None: return 1`` immediately, discarding
the remaining ~55 of 61 attempts and forcing an unnecessary rollback while
the scrape was still legitimately running.  These tests pin the fix: a
totally unreachable status round is treated as one more "still recovering"
round, not an instant abort, while a genuinely-exhausted bounded window
(status never comes back at all) still fails honestly.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "verify_live_source_coverage.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("verify_live_source_coverage", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


_mod = _load_module()


def _recovering_status(missing: dict[str, int]) -> dict:
    return {
        "served_source_coverage": missing,
        "running": True,
        "stalled": False,
        "hung": False,
        "current_step": "source_start",
        "current_source": "KTC",
    }


def _ok_status() -> dict:
    return {
        "served_source_coverage": {"dlfSf": 500, "dlfRookieSf": 120},
        "running": False,
        "stalled": False,
        "hung": False,
    }


def _run_main(monkeypatch, statuses, coverage_results):
    """Drive main() with a scripted sequence of _fetch_status() returns and
    matching _coverage_result() outcomes, with sleep() stubbed to a no-op so
    the test doesn't actually wait."""
    calls = {"n": 0}

    def fake_fetch_status(base_url):
        idx = calls["n"]
        calls["n"] += 1
        return statuses[min(idx, len(statuses) - 1)]

    def fake_coverage_result(status):
        idx = calls["n"] - 1
        return coverage_results[min(idx, len(coverage_results) - 1)]

    monkeypatch.setattr(_mod, "_fetch_status", fake_fetch_status)
    monkeypatch.setattr(_mod, "_coverage_result", fake_coverage_result)
    monkeypatch.setattr(_mod.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(sys, "argv", ["verify_live_source_coverage.py", "http://127.0.0.1:8000"])
    return _mod.main(), calls["n"]


def test_a_single_unreachable_round_does_not_abort_the_recovery_window(monkeypatch):
    """The exact 2026-09-09 shape: recovering, recovering, then ONE totally
    unreachable round, then recovering again and finally clean.  The old
    code returned 1 (and gave up) the instant the None round happened."""
    violations = [("dlfSf", 0), ("dlfRookieSf", 2)]
    statuses = [
        _recovering_status({"dlfSf": 0, "dlfRookieSf": 2}),
        _recovering_status({"dlfSf": 0, "dlfRookieSf": 2}),
        None,  # /api/status fully unreachable this round
        _recovering_status({"dlfSf": 0, "dlfRookieSf": 2}),
        _ok_status(),
    ]
    coverage_results = [
        (violations, [], []),
        (violations, [], []),
        None,  # unused when status is None
        (violations, [], []),
        ([], ["dlfSf", "dlfRookieSf"], []),
    ]
    code, attempts = _run_main(monkeypatch, statuses, coverage_results)
    assert code == 0
    assert attempts == 5


def test_bounded_window_still_fails_if_status_never_comes_back(monkeypatch):
    """If /api/status is unreachable for the ENTIRE bounded window, that is
    a real failure -- the loop must not wait forever, and must report the
    honest "never returned a parseable response" reason rather than
    reusing the "no recoverable scrape" wording that implies status we
    never actually had."""
    statuses = [None] * _mod._COVERAGE_WAIT_ATTEMPTS
    coverage_results = [None] * _mod._COVERAGE_WAIT_ATTEMPTS
    code, attempts = _run_main(monkeypatch, statuses, coverage_results)
    assert code == 1
    assert attempts == _mod._COVERAGE_WAIT_ATTEMPTS


def test_bounded_window_still_fails_fast_on_a_stalled_scrape(monkeypatch):
    """Existing behavior, preserved: a status that IS reachable but reports
    a stalled/non-running scrape must still fail immediately rather than
    burning the whole bounded window."""
    violations = [("dlfSf", 0)]
    stalled_status = {
        "served_source_coverage": {"dlfSf": 0},
        "running": False,
        "stalled": True,
        "hung": False,
        "current_step": "source_start",
        "current_source": "KTC",
    }
    statuses = [stalled_status]
    coverage_results = [(violations, [], [])]
    code, attempts = _run_main(monkeypatch, statuses, coverage_results)
    assert code == 1
    assert attempts == 1


def test_multiple_unreachable_rounds_are_each_tolerated_up_to_the_bound(monkeypatch):
    """Several transient total-unreachable rounds in a row, not just one,
    still recover cleanly as long as the server answers before the bound
    is exhausted."""
    statuses = [None, None, None, _ok_status()]
    coverage_results = [None, None, None, ([], ["dlfSf", "dlfRookieSf"], [])]
    code, attempts = _run_main(monkeypatch, statuses, coverage_results)
    assert code == 0
    assert attempts == 4


def test_recovering_scrape_helper_treats_stalled_and_hung_as_not_recovering():
    assert _mod._recovering_scrape({"running": True, "stalled": False, "hung": False})
    assert not _mod._recovering_scrape({"running": True, "stalled": True, "hung": False})
    assert not _mod._recovering_scrape({"running": True, "stalled": False, "hung": True})
    assert not _mod._recovering_scrape({"running": False, "stalled": False, "hung": False})
