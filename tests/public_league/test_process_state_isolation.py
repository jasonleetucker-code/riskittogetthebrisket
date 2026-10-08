"""The public-league test stubs do not outlive their module.

``install_stubs`` used to be a bare ``setattr`` on ``sleeper_client`` that
nothing undid, and the route tests also leaked ``SLEEPER_LEAGUE_ID`` and a
stub-built snapshot in ``server``'s public cache.  Every later module in the
process then ran against the fixture league, so
``tests/api/test_public_league_privacy_boundary.py`` passed in isolation and
failed after ``test_server_routes.py`` (measured 2026-10-07).

``tests/conftest.py::_public_league_process_state`` now restores all three at
the end of every module.  These tests pin the mechanism it relies on, in one
process, without depending on suite order: a "leaking module" is simulated
and the restore must return the process to exactly what it was.
"""

from __future__ import annotations

import os
import sys

import pytest

from src.public_league import sleeper_client
from tests.public_league import fixtures


@pytest.fixture
def isolated_env(monkeypatch):
    # Whatever the outer state, put it back after the test.
    monkeypatch.delenv("SLEEPER_LEAGUE_ID", raising=False)
    yield


def test_restore_undoes_install_stubs(isolated_env):
    names = list(fixtures.build_stub_client())
    before = {name: getattr(sleeper_client, name) for name in names}
    restore = fixtures.capture_public_league_process_state()

    fixtures.install_stubs(fixtures.build_stub_client())
    # A second install (another class in the same module) must not record
    # the first install's stub as the original.
    fixtures.install_stubs(fixtures.build_stub_client())
    assert sleeper_client.fetch_league("L2025") is not None  # stubbed

    restore()
    for name in names:
        assert getattr(sleeper_client, name) is before[name], name
    assert fixtures._STUBBED_ORIGINALS == {}


def test_restore_undoes_the_leaked_league_id(isolated_env):
    restore = fixtures.capture_public_league_process_state()
    os.environ["SLEEPER_LEAGUE_ID"] = "L2025"  # what the route tests do
    restore()
    assert "SLEEPER_LEAGUE_ID" not in os.environ

    os.environ["SLEEPER_LEAGUE_ID"] = "OUTER"
    restore = fixtures.capture_public_league_process_state()
    os.environ["SLEEPER_LEAGUE_ID"] = "L2025"
    restore()
    assert os.environ["SLEEPER_LEAGUE_ID"] == "OUTER"


def test_restore_returns_the_public_snapshot_cache_and_drops_derived_memos(isolated_env):
    import server

    assert sys.modules.get("server") is server
    cache = server._public_league_cache
    saved = dict(cache)
    try:
        restore = fixtures.capture_public_league_process_state()
        sentinel = object()
        cache.update({"snapshot": sentinel, "snapshot_league_id": "L2025", "fetched_at": 1.0})
        for name in fixtures.PUBLIC_SERVER_MEMOS:
            getattr(server, name)["leaked"] = sentinel

        restore()
        assert cache.get("snapshot") is saved.get("snapshot")
        assert cache.get("snapshot_league_id") == saved.get("snapshot_league_id")
        for name in fixtures.PUBLIC_SERVER_MEMOS:
            assert "leaked" not in getattr(server, name), name
    finally:
        cache.clear()
        cache.update(saved)
