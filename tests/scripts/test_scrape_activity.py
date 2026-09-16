"""The one definition of "a scrape is blocking the box right now".

WHY THIS EXISTS
---------------
``server.py`` launches a scrape three seconds after every boot, and its
browser-launch phase blocks the process — so every deploy creates a window in
which the box is alive and answers nothing. Measured on Deploy Production run
35092313919: ``/api/public/league`` returned 200 to the smoke test's warm loop
at 12:22:01 and then timed out at 12:22:38, with ``/api/health`` reporting
``scrape_running: true, current_step: "browser"`` throughout.

The danger in fixing that is fixing it too generously. These tests pin the
boundary: what a scrape may excuse, and what it may never excuse.
"""

from __future__ import annotations

import importlib

import pytest

_mod = importlib.import_module("scripts.scrape_activity")


# ── what a scrape may excuse ────────────────────────────────────────────────


@pytest.mark.parametrize("code", ["000", "000000", "502", "503", "504"])
def test_transport_failures_are_attributable_to_a_scrape(code):
    """curl's 000 and nginx's gateway codes mean the app never answered."""
    assert _mod.is_unreachable_code(code)


@pytest.mark.parametrize("code", ["200", "201", "301", "400", "401", "403", "404", "418", "500"])
def test_an_answer_is_never_excused_by_a_scrape(code):
    """A wrong status code is a correctness statement, not unreachability.

    This is the load-bearing half. If ``/api/data`` ever answered 200 to an
    unauthenticated probe, the auth gate would be broken and private data
    exposed — and no amount of scrape activity may turn that into a wait.
    500 is included deliberately: the app answered, it just answered badly.
    """
    assert not _mod.is_unreachable_code(code)


def test_codes_are_compared_without_surrounding_whitespace():
    assert _mod.is_unreachable_code(" 502 ")
    assert _mod.is_unreachable_code(502)


# ── which scrapes count as recovering ───────────────────────────────────────


def test_an_active_scrape_is_recovering():
    assert _mod.recovering_scrape({"running": True, "stalled": False, "hung": False})


def test_a_stalled_or_hung_scrape_is_not_recovering():
    """These are the states a deploy should fail on, not wait out."""
    assert not _mod.recovering_scrape({"running": True, "stalled": True, "hung": False})
    assert not _mod.recovering_scrape({"running": True, "stalled": False, "hung": True})


def test_no_scrape_is_not_recovering():
    assert not _mod.recovering_scrape({"running": False, "stalled": False, "hung": False})
    assert not _mod.recovering_scrape({})


# ── the CLI contract the deploy workflow depends on ─────────────────────────


def test_check_code_exit_codes(capsys):
    assert _mod.main.__module__  # sanity: module imported
    import sys

    def run(argv):
        old = sys.argv
        sys.argv = ["scrape_activity.py", *argv]
        try:
            return _mod.main()
        finally:
            sys.argv = old

    assert run(["--check-code", "000"]) == 0
    assert run(["--check-code", "502"]) == 0
    assert run(["--check-code", "401"]) == 1
    assert run(["--check-code", "200"]) == 1


def test_unreadable_status_is_cannot_tell_not_no(monkeypatch):
    """Exit 2 is its own answer.

    The blocking window swallows ``/api/status`` as well, so "cannot tell" is
    the COMMON case mid-scrape — verified live against production while a
    scrape held the box. It must be distinguishable from a server that
    answered and said no scrape is running (exit 1), because the deploy smoke
    test ends its wait on the latter and keeps waiting on the former.
    """
    monkeypatch.setattr(_mod, "fetch_status", lambda *a, **k: None)
    import sys

    old = sys.argv
    sys.argv = ["scrape_activity.py", "https://example.invalid"]
    try:
        assert _mod.main() == 2
    finally:
        sys.argv = old


def test_active_and_idle_scrapes_have_distinct_exit_codes(monkeypatch):
    import sys

    def run(status):
        monkeypatch.setattr(_mod, "fetch_status", lambda *a, **k: status)
        old = sys.argv
        sys.argv = ["scrape_activity.py", "https://example.invalid"]
        try:
            return _mod.main()
        finally:
            sys.argv = old

    assert run({"running": True, "stalled": False, "hung": False}) == 0
    assert run({"running": False}) == 1
    assert run({"running": True, "stalled": True}) == 1


def test_fetch_status_returns_none_on_a_non_dict_payload(monkeypatch):
    """A JSON list is parseable but is not a status; it must not read as one."""

    class _Resp:
        status = 200

        def read(self):
            return b"[]"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(_mod.urllib.request, "urlopen", lambda *a, **k: _Resp())
    assert _mod.fetch_status("https://example.invalid") is None


# ── one owner, not two ──────────────────────────────────────────────────────


def test_the_coverage_gate_consumes_this_predicate_rather_than_redefining_it():
    """``verify_live_source_coverage.py`` had its own copy; now it imports.

    Two definitions of "is a scrape running" can drift, and the one in the
    deploy workflow would be the one nobody notices drifting.
    """
    verify = importlib.import_module("scripts.verify_live_source_coverage")
    assert verify._recovering_scrape is _mod.recovering_scrape
