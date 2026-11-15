"""``GET /api/player/{id}/realized`` and ``POST /api/custom-alerts/run`` must
not block the event loop.

Same defect and technique as ``test_slow_handlers_off_event_loop.py``: the
stubbed slow step blocks on a thread event that only a CONCURRENT request can
release.  If the slow step runs on the event loop, the concurrent request can
never run, the wait times out and the stub records ``False``.

* realized: ``fetch_weekly_stats`` is an nflverse download + parse (8.5 s cold).
* custom alerts: ``_deliver_email_smtp`` is smtplib with 15 s timeouts, once
  per hit, per user.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
from types import SimpleNamespace

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
    from src.api import rate_limit

    monkeypatch.setattr(rate_limit, "should_rate_limit", lambda _ip: (False, 0))
    saved = dict(server.auth_sessions)
    yield
    server.auth_sessions.clear()
    server.auth_sessions.update(saved)
    session_store._setup_done.clear()  # noqa: SLF001


@pytest.fixture
def one_league(tmp_path):
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


async def _concurrent(method: str, path: str, headers: dict, step: _BlockingStep):
    """Run the slow request, fire GET /api/leagues while it is in flight."""
    transport = httpx.ASGITransport(app=server.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://fixture") as client:
        slow = asyncio.create_task(client.request(method, path, headers=headers))
        for _ in range(int(_RELEASE_TIMEOUT_S * 200)):
            if step.entered.is_set():
                break
            await asyncio.sleep(0.005)
        quick = await client.get("/api/leagues")
        step.released.set()
        slow_res = await slow
    assert quick.status_code == 200, quick.text[:400]
    return slow_res


def _session_headers(username: str = "tester") -> dict:
    sid = server._create_auth_session(username)  # noqa: SLF001
    return {"Cookie": f"{server.JASON_AUTH_COOKIE_NAME}={sid}"}


# --------------------------------------------------------------- realized


def _realized_setup(monkeypatch, weekly):
    from src.nfl_data import ingest

    step = _BlockingStep(result=weekly)
    monkeypatch.setattr(ingest, "fetch_weekly_stats", step)
    monkeypatch.setattr(
        server._league_registry,  # noqa: SLF001
        "scoring_settings_for_league",
        lambda _cfg: {"pass_td": 4.0},
    )
    return step


def test_realized_fetch_does_not_block_other_requests(monkeypatch, one_league):
    step = _realized_setup(monkeypatch, [])
    res = asyncio.run(_concurrent("GET", "/api/player/4046/realized", _session_headers(), step))

    assert res.status_code == 200, res.text[:400]
    assert step.saw_release == [True], "realized fetched nflverse stats on the event loop"


def test_realized_no_stats_body_unchanged(monkeypatch, one_league):
    step = _realized_setup(monkeypatch, [])
    step.released.set()
    res = asyncio.run(_concurrent("GET", "/api/player/4046/realized", _session_headers(), step))

    assert res.json() == {
        "sleeperId": "4046",
        "leagueKey": "main",
        "reason": "no_stats_available",
        "weeks": [],
        "totalPoints": 0.0,
        "weekCount": 0,
    }


def test_realized_unmapped_player_body_unchanged(monkeypatch, one_league):
    step = _realized_setup(monkeypatch, [{"player_id": "00-1", "week": 1}])
    step.released.set()
    from src.public_league import sleeper_client

    monkeypatch.setattr(sleeper_client, "fetch_nfl_players", lambda: {})
    res = asyncio.run(_concurrent("GET", "/api/player/4046/realized", _session_headers(), step))

    assert res.json() == {
        "sleeperId": "4046",
        "leagueKey": "main",
        "reason": "unmapped_player",
        "weeks": [],
    }


# ----------------------------------------------------------- custom alerts


def _alerts_setup(monkeypatch):
    hit = SimpleNamespace(
        channels=("email",),
        title="T",
        body="B",
        kind="k",
        rule_id="r1",
    )
    step = _BlockingStep(result=True)
    monkeypatch.setattr(server, "SIGNAL_ALERT_CRON_TOKEN", "tok")
    monkeypatch.setattr(server, "latest_contract_data", {"playersArray": [{"name": "x"}]})
    monkeypatch.setattr(
        server._user_kv,  # noqa: SLF001
        "all_user_states",
        lambda: {"u1": {"customAlerts": [{"id": "r1"}], "notificationsEmail": "a@b.c"}},
    )
    monkeypatch.setattr(server._custom_alerts, "evaluate_alerts", lambda *a, **k: [hit])  # noqa: SLF001
    monkeypatch.setattr(server._custom_alerts, "mark_fired", lambda st, h: dict(st, fired=1))  # noqa: SLF001
    monkeypatch.setattr(server, "_deliver_email_smtp", step)
    writes: list[str] = []
    monkeypatch.setattr(
        server._user_kv,  # noqa: SLF001
        "mutate_user_state",
        lambda username, fn: writes.append(username),
    )
    return step, writes


def test_custom_alerts_delivery_does_not_block_other_requests(monkeypatch):
    step, writes = _alerts_setup(monkeypatch)
    headers = {"Authorization": "Bearer tok"}
    res = asyncio.run(_concurrent("POST", "/api/custom-alerts/run", headers, step))

    assert res.status_code == 200, res.text[:400]
    assert step.saw_release == [True], "custom-alerts delivered email on the event loop"


def test_custom_alerts_response_and_side_effects_unchanged(monkeypatch):
    step, writes = _alerts_setup(monkeypatch)
    step.released.set()
    headers = {"Authorization": "Bearer tok"}
    res = asyncio.run(_concurrent("POST", "/api/custom-alerts/run", headers, step))

    assert res.json() == {"ok": True, "users": {"u1": {"hits": 1, "email": 1, "push": 0}}}
    assert res.headers["cache-control"] == "no-store"
    assert writes == ["u1"]


def test_custom_alerts_still_requires_auth(monkeypatch):
    _alerts_setup(monkeypatch)

    async def go():
        transport = httpx.ASGITransport(app=server.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://fixture") as c:
            return await c.post("/api/custom-alerts/run")

    res = asyncio.run(go())
    assert res.status_code == 401
