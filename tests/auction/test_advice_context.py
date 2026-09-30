"""Perfect Draft advice context: caller's own seat only, never a chimera."""

from __future__ import annotations

import sys

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
    assert (
        out["status"] == "values_only"
        and out["reason"] == "board_is_for_another_league"
        and out["context"] is None
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
