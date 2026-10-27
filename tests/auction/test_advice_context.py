"""Perfect Draft advice context: caller's own seat only, never a chimera."""

from __future__ import annotations

import sys

import pytest

from src.api import draft_optimizer_api
from tests.auction.test_api_store import ORIGIN, _make_room, _owner_client, env  # noqa: F401 - fixture import


def _with_league(key):
    sys.modules["server"].latest_contract_data["meta"] = {
        "leagueKey": key,
        "generatedAt": "2026-09-29T00:00:00Z",
    }


def test_advice_context_uses_the_callers_own_seat(env, monkeypatch):  # noqa: F811
    st, app = env
    _with_league("dynasty_main")
    calls = []

    def fake(contract, league_key, *, owner_id=None, roster_id=None, team_name=None):
        calls.append((league_key, owner_id, roster_id, team_name))
        return {"openRosterSpots": 4, "cutLadder": {"rungs": []}, "waiverValues": {}}

    monkeypatch.setattr(draft_optimizer_api, "get_roster_context", fake)
    c = _owner_client(app)
    room = _make_room(c, budgetSource="equal", equalAmount=100)["roomId"]
    out = c.get(f"/api/auction/rooms/{room}/advice-context?ownerId=u7&teamName=Team%207").json()
    assert out["status"] == "ok" and out["context"]["openRosterSpots"] == 4
    # the seat comes from membership (S1 → u1); query parameters are ignored
    assert calls == [("dynasty_main", "u1", None, None)]
    assert out["boardValues"]["991"] > 0 and "1" not in out["boardValues"]  # pool only, no veteran


def test_advice_refuses_a_board_for_another_league(env, monkeypatch):  # noqa: F811
    st, app = env
    _with_league("dynasty_main")
    c = _owner_client(app)
    room = _make_room(c, budgetSource="equal", equalAmount=100)["roomId"]
    _with_league("dynasty_new")
    monkeypatch.setattr(
        draft_optimizer_api,
        "get_roster_context",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not be called")),
    )
    out = c.get(f"/api/auction/rooms/{room}/advice-context").json()
    # Neither the other league's rosters NOR its board values (LATENT-06 /
    # LI1842-DEFECT-13): the values used to be returned before this check.
    assert (
        out["status"] == "unavailable"
        and out["reason"] == "board_is_for_another_league"
        and out["context"] is None
        and out["boardValues"] == {}
        and out["valuesAsOf"] is None
    )


def test_advice_failure_is_reported_not_raised(env, monkeypatch):  # noqa: F811
    st, app = env
    _with_league("dynasty_main")
    c = _owner_client(app)
    room = _make_room(c, budgetSource="equal", equalAmount=100)["roomId"]

    def boom(*a, **k):
        raise ValueError("unknown_team")

    monkeypatch.setattr(draft_optimizer_api, "get_roster_context", boom)
    r = c.get(f"/api/auction/rooms/{room}/advice-context")
    assert r.status_code == 200 and r.json()["reason"] == "unknown_team"


def test_advice_requires_membership(env):  # noqa: F811
    from fastapi.testclient import TestClient

    st, app = env
    c = _owner_client(app)
    room = _make_room(c, budgetSource="equal", equalAmount=100)["roomId"]
    assert TestClient(app).get(f"/api/auction/rooms/{room}/advice-context").status_code == 401


def test_unstamped_board_is_treated_as_the_servers_own_league(env, monkeypatch):  # noqa: F811
    """Same rule as /api/draft/roster-context: only a board that DECLARES a
    different league is refused."""
    st, app = env
    sys.modules["server"].latest_contract_data.pop("meta", None)
    import types

    from src.api import league_registry

    monkeypatch.setattr(
        league_registry, "get_default_league", lambda: types.SimpleNamespace(key="dynasty_main")
    )
    seen = []
    monkeypatch.setattr(
        draft_optimizer_api,
        "get_roster_context",
        lambda contract, key, **kw: seen.append((key, kw.get("owner_id")))
        or {"openRosterSpots": 2},
    )
    c = _owner_client(app)
    room = _make_room(c, budgetSource="equal", equalAmount=100)["roomId"]
    out = c.get(f"/api/auction/rooms/{room}/advice-context").json()
    assert out["status"] == "ok", out
    assert seen and seen[0][1] == "u1"


def test_room_budgets_are_requested_for_the_seats_league(env):  # noqa: F811
    """LI1842-DEFECT-13: budgets are asked for the SEATS' league explicitly,
    and the room's provenance names whose dollars they are."""
    st, app = env
    _with_league("dynasty_main")
    seen = []
    srv = sys.modules["server"]
    original = srv.get_draft_capital

    async def spy(request):
        seen.append(request.query_params.get("leagueKey"))
        return await original(request)

    srv.get_draft_capital = spy
    c = _owner_client(app)
    out = _make_room(c)
    assert seen == ["dynasty_main"]
    prov = out["budgetProvenance"]
    assert prov["leagueKey"] == "dynasty_main" and prov["seatLeagueKey"] == "dynasty_main"
    assert prov["leagueMismatch"] is None


def test_room_refuses_budgets_from_another_league(env):  # noqa: F811
    """A draft-capital answer for a different league than the seats is refused
    (409), never joined -- not substituted, not silently mixed."""
    st, app = env
    _with_league("dynasty_main")
    from tests.auction.test_api_store import _draft_capital

    async def other_league(request):
        return {**_draft_capital(), "leagueKey": "dynasty_new"}

    sys.modules["server"].get_draft_capital = other_league
    c = _owner_client(app)
    from tests.auction.test_api_store import idem

    r = c.post(
        "/api/auction/rooms",
        json={"preset": "fast", "seatSource": "league", "budgetSource": "draft_capital"},
        headers=idem(),
    )
    assert r.status_code == 409, r.text
    assert "budget_league_mismatch" in r.text


def test_room_refuses_budgets_that_do_not_name_their_league(env):  # noqa: F811
    st, app = env
    _with_league("dynasty_main")
    from tests.auction.test_api_store import _draft_capital, idem

    async def unstamped(request):
        return _draft_capital()  # no leagueKey

    sys.modules["server"].get_draft_capital = unstamped
    c = _owner_client(app)
    r = c.post(
        "/api/auction/rooms",
        json={"preset": "fast", "seatSource": "league", "budgetSource": "draft_capital"},
        headers=idem(),
    )
    assert r.status_code == 409 and "budget_league_unstated" in r.text


def test_generic_seats_still_report_whose_budgets_they_read(env):  # noqa: F811
    st, app = env
    _with_league("dynasty_main")
    c = _owner_client(app)
    prov = _make_room(c, seatSource="generic")["budgetProvenance"]
    assert prov["seatLeagueKey"] is None and prov["leagueMismatch"] is None
    assert prov["leagueKey"] == "dynasty_main"


@pytest.fixture()
def main_registry(tmp_path):
    """A registry whose default league is the real ``dynasty_main`` entry (the
    suite points the registry at a nonexistent file).  Restored, then
    reloaded, on teardown -- in that order."""
    import json
    import os
    from pathlib import Path

    from src.api import league_registry

    repo = Path(__file__).resolve().parents[2]
    registry = json.loads((repo / "config/leagues/registry.json").read_text(encoding="utf-8"))
    main = next(lg for lg in registry["leagues"] if lg["key"] == "dynasty_main")
    path = tmp_path / "registry-main.json"
    path.write_text(
        json.dumps({"schemaVersion": 1, "defaultLeagueKey": "dynasty_main", "leagues": [main]}),
        encoding="utf-8",
    )
    previous = os.environ.get("LEAGUE_REGISTRY_PATH")
    os.environ["LEAGUE_REGISTRY_PATH"] = str(path)
    league_registry.reload_registry()
    try:
        yield "dynasty_main"
    finally:
        if previous is None:
            os.environ.pop("LEAGUE_REGISTRY_PATH", None)
        else:
            os.environ["LEAGUE_REGISTRY_PATH"] = previous
        league_registry.reload_registry()


@pytest.fixture()
def real_server(monkeypatch, main_registry):
    """The REAL ``server`` module, imported before ``env`` installs its fake.

    Only the workbook builder is stubbed (it parses ``CSVs/Draft Data.xlsx``
    and calls Sleeper); the handler itself -- league resolution, the cache,
    and the ``leagueKey`` stamp it puts on every 200 -- runs for real.
    """
    import server as real  # noqa: PLC0415

    monkeypatch.setattr(real, "_DRAFT_CAPITAL_CACHE", {})
    monkeypatch.setattr(real, "_DRAFT_CAPITAL_LAST_VALID", {})
    monkeypatch.setattr(real, "_DRAFT_CAPITAL_LOCKS", {})
    monkeypatch.setattr(real, "_is_authenticated", lambda request: True)
    return real


def test_room_creation_succeeds_against_the_real_draft_capital_handler(
    real_server,
    env,  # noqa: F811
    monkeypatch,
):
    """The same-league path through the REAL ``get_draft_capital``: the
    handler stamps the league it resolved, so the room opens -- no false
    ``budget_league_unstated`` / ``budget_league_mismatch``."""
    from tests.auction.test_api_store import _draft_capital

    st, app = env
    default_key = "dynasty_main"
    _with_league(default_key)
    built = []

    def fake_workbook(league_key=None, *a, **k):
        built.append(league_key)
        return _draft_capital()  # deliberately unstamped: the handler must stamp it

    monkeypatch.setattr(real_server, "_fetch_draft_capital", fake_workbook)
    sys.modules["server"].get_draft_capital = real_server.get_draft_capital
    c = _owner_client(app)
    out = _make_room(c)
    assert built == [default_key]
    prov = out["budgetProvenance"]
    assert prov["leagueKey"] == default_key and prov["seatLeagueKey"] == default_key
    assert prov["leagueMismatch"] is None
