"""Slow work in an ``async def`` route must not freeze every other request.

Measured on production 2026-11-12: ``GET /api/status`` took 14-18 s per call,
and an unrelated ``GET /api/leagues`` (0.45 s alone) waited 15.9 s while it
ran.  The handler was ``async def`` and computed every probe synchronously, so
one status poll (settings page, tools pages, uptime checks) stalled the whole
single-worker backend.  ``GET /api/sleeper/draft/picks`` had the same shape:
polled every 2-3 s during a live draft, with Sleeper round-trips on the loop.

These tests are deterministic, not timing-based.  The stubbed slow step blocks
on a thread event that only a CONCURRENT request can release.  If the slow
step runs on the event loop, the concurrent request can never run, the event
times out, and the stub records that it was not released.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading

import httpx
import pytest

import server
from src.api import session_store, user_kv

_RELEASE_TIMEOUT_S = 3.0


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(session_store, "_DEFAULT_DB_PATH", tmp_path / "sessions.sqlite")
    session_store._setup_done.clear()  # noqa: SLF001
    monkeypatch.setattr(user_kv, "USER_KV_PATH", tmp_path / "user_kv.sqlite")
    # Public routes are rate limited per client IP; this test's two requests
    # must never be the ones that trip it.
    from src.api import rate_limit

    monkeypatch.setattr(rate_limit, "should_rate_limit", lambda _ip: (False, 0))
    saved = dict(server.auth_sessions)
    yield
    server.auth_sessions.clear()
    server.auth_sessions.update(saved)
    session_store._setup_done.clear()  # noqa: SLF001


class _BlockingStep:
    """A slow step that finishes only once a concurrent request completed."""

    def __init__(self, result):
        self.entered = threading.Event()
        self.released = threading.Event()
        self.saw_release: list[bool] = []
        self._result = result

    def __call__(self, *_args, **_kwargs):
        self.entered.set()
        self.saw_release.append(self.released.wait(timeout=_RELEASE_TIMEOUT_S))
        return self._result


async def _concurrent(slow_path: str, headers: dict, step: _BlockingStep) -> tuple[int, int]:
    """(slow status code, quick status code); bodies attached on failure."""
    transport = httpx.ASGITransport(app=server.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://fixture") as client:
        slow = asyncio.create_task(client.get(slow_path, headers=headers))
        # Wait until the slow step is running.  On the event loop this loop
        # cannot advance until the step gives up, which is the failure mode.
        for _ in range(int(_RELEASE_TIMEOUT_S * 200)):
            if step.entered.is_set():
                break
            await asyncio.sleep(0.005)
        quick = await client.get("/api/leagues")
        step.released.set()
        slow_res = await slow
    assert slow_res.status_code == 200, slow_res.text[:400]
    assert quick.status_code == 200, quick.text[:400]
    return slow_res.status_code, quick.status_code


def test_status_probes_do_not_block_other_requests(monkeypatch):
    step = _BlockingStep(result={})
    monkeypatch.setattr(server, "_rank_history_coverage_safe", step)

    slow_code, quick_code = asyncio.run(_concurrent("/api/status", {}, step))

    assert quick_code == 200
    assert slow_code == 200
    assert step.saw_release == [True], (
        "/api/status ran its probes on the event loop: a concurrent request "
        "could not complete while it worked"
    )


def test_admin_diagnostics_probes_do_not_block_other_requests(monkeypatch):
    step = _BlockingStep(result={})
    monkeypatch.setattr(server, "_rank_history_coverage_safe", step)
    monkeypatch.setattr(server, "_require_admin_session", lambda _req: {"username": "admin"})
    sid = server._create_auth_session("admin")  # noqa: SLF001
    headers = {"Cookie": f"{server.JASON_AUTH_COOKIE_NAME}={sid}"}

    slow_code, quick_code = asyncio.run(_concurrent("/api/admin/diagnostics", headers, step))

    assert quick_code == 200
    assert slow_code == 200
    assert step.saw_release == [True]


@pytest.fixture
def one_league(tmp_path):
    """conftest points the registry at nothing; this route needs one league."""
    from src.api import league_registry

    path = tmp_path / "registry.json"
    path.write_text(
        json.dumps(
            {
                "defaultLeagueKey": "main",
                "leagues": [
                    {
                        "key": "main",
                        "displayName": "Main",
                        "sleeperLeagueId": "L-MAIN",
                        "active": True,
                        "rosterSettings": {"teamCount": 3},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    previous = os.environ.get("LEAGUE_REGISTRY_PATH")
    os.environ["LEAGUE_REGISTRY_PATH"] = str(path)
    league_registry.reload_registry()
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("LEAGUE_REGISTRY_PATH", None)
        else:
            os.environ["LEAGUE_REGISTRY_PATH"] = previous
        league_registry.reload_registry()


def test_live_draft_poll_does_not_block_other_requests(monkeypatch, one_league):
    snapshot = {
        "leagueKey": "main",
        "draftId": "d1",
        "status": "drafting",
        "latestPickNo": 0,
        "picks": [],
        "fetchedAt": "2026-11-12T00:00:00+00:00",
    }
    step = _BlockingStep(result=snapshot)
    monkeypatch.setattr(server._sleeper_overlay, "fetch_live_draft_picks", step)  # noqa: SLF001
    sid = server._create_auth_session("drafter")  # noqa: SLF001
    headers = {"Cookie": f"{server.JASON_AUTH_COOKIE_NAME}={sid}"}

    slow_code, quick_code = asyncio.run(_concurrent("/api/sleeper/draft/picks", headers, step))

    assert quick_code == 200
    assert slow_code == 200
    assert step.saw_release == [True], "/api/sleeper/draft/picks fetched Sleeper on the event loop"


def test_status_still_serves_the_scrape_state_it_takes_on_the_loop():
    """The split keeps the payload whole: scrape-state keys from the loop,
    probe keys from the threadpool, in one public projection."""
    res = asyncio.run(server.get_status())

    body = json.loads(res.body)
    for key in ("running", "stalled", "stall_threshold_sec", "rankHistoryCoverage", "build"):
        assert key in body, key
