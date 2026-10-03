"""A failed ``/traded_picks`` fetch is UNKNOWN ownership, never "no trades".

Both producers of league pick ownership used to treat a failed Sleeper
``/league/{id}/traded_picks`` fetch as an empty diff, fold DEFAULT
original-owner ownership, and publish it as fact in
``sleeper.teams[].picks`` / ``pickDetails``:

* ``src/api/sleeper_overlay.py::_build_pick_ownership`` passed
  ``traded if isinstance(traded, list) else []`` to the fold;
* ``Dynasty Scraper.py::fetch_sleeper_rosters`` set ``traded_picks = []``
  on a non-200, an exception, or a non-list body.

"Fetched, no trades" (a 200 list, possibly empty) and "fetch failed" are
different statements.  On failure each team's ``picks`` / ``pickDetails``
are ``None`` (``[]`` would claim the team owns no picks) and the team
carries ``pickOwnershipState: "unavailable"`` +
``pickOwnershipReason: "traded_picks_fetch_failed"``.  One vocabulary,
owned by ``src/identity/picks.py``.

Also pins every downstream consumer's unknown handling: Pick Projector,
BDVM ``pickCount``, the trade simulator, and the Pick Forecast capture.
"""

from __future__ import annotations

import ast
import datetime
import functools
import re
import types
from pathlib import Path
from typing import Any

import pytest

from src.api import sleeper_overlay
from src.identity import picks as pick_identity

_SCRAPER = Path(__file__).resolve().parents[2] / "Dynasty Scraper.py"

LEAGUE_ID = "LTEST_FAIL_CLOSED"
_UNREGISTERED = "unregistered-league"


# ── Overlay producer ─────────────────────────────────────────────────


def _overlay_responses(traded: Any) -> dict[str, Any]:
    return {
        f"/league/{LEAGUE_ID}": {"name": "T", "settings": {"waiver_budget": 100}},
        f"/league/{LEAGUE_ID}/rosters": [
            {"roster_id": 1, "owner_id": "oA", "players": ["P-1"], "settings": {}},
            {"roster_id": 2, "owner_id": "oB", "players": ["P-2"], "settings": {}},
        ],
        f"/league/{LEAGUE_ID}/users": [
            {"user_id": "oA", "display_name": "Team A"},
            {"user_id": "oB", "display_name": "Team B"},
        ],
        f"/league/{LEAGUE_ID}/traded_picks": traded,
    }


def _getter(responses: dict[str, Any]):
    def get(url: str) -> Any:
        for suffix in sorted(responses, key=len, reverse=True):
            if url.endswith(suffix):
                return responses[suffix]
        return None

    return get


def _overlay_teams(traded: Any) -> list[dict[str, Any]]:
    teams = sleeper_overlay._build_teams_block(
        LEAGUE_ID, {"P-1": "P One", "P-2": "P Two"}, getter=_getter(_overlay_responses(traded))
    )
    assert teams is not None
    return teams


def test_overlay_failed_traded_picks_fetch_publishes_unknown_not_defaults():
    # ``_http_get_json`` returns None on ANY failure (HTTP error, breaker
    # open, bad JSON) — that is the failed-fetch signal.
    teams = _overlay_teams(None)
    for t in teams:
        assert t["picks"] is None, "unknown ownership must not read as a list"
        assert t["pickDetails"] is None
        assert t["pickOwnershipState"] == "unavailable"
        assert t["pickOwnershipReason"] == "traded_picks_fetch_failed"


@pytest.mark.parametrize("body", [{"error": "nope"}, "oops", 0])
def test_overlay_non_list_body_is_unknown(body):
    for t in _overlay_teams(body):
        assert t["picks"] is None
        assert t["pickDetails"] is None
        assert t["pickOwnershipState"] == "unavailable"


def test_overlay_build_pick_ownership_returns_none_on_failure():
    assert sleeper_overlay._build_pick_ownership(LEAGUE_ID, [1, 2], getter=lambda u: None) is None


def test_overlay_empty_successful_list_still_folds_defaults():
    teams = _overlay_teams([])
    for t in teams:
        assert t["pickOwnershipState"] == "observed"
        assert t["pickOwnershipReason"] is None
        assert t["picks"], "a 200 empty list is 'no trades' — every team owns its own picks"
        assert all(d["original_roster_id"] == t["roster_id"] for d in t["pickDetails"])


def test_overlay_success_ownership_is_byte_identical_to_the_direct_fold():
    """On success the published ownership is exactly the canonical fold —
    the fix only adds the state fields."""
    traded = [
        {"season": str(datetime.datetime.now().year + 1), "round": 1, "roster_id": 2, "owner_id": 1}
    ]
    own = sleeper_overlay._build_pick_ownership(LEAGUE_ID, [1, 2], getter=lambda u: traded)
    teams = {t["roster_id"]: t for t in _overlay_teams(traded)}
    for rid in (1, 2):
        assert teams[rid]["pickDetails"] == own[rid]
        assert teams[rid]["picks"] == [p["label"] for p in own[rid]]
    # the traded pick moved
    assert any(d["original_roster_id"] == 2 for d in teams[1]["pickDetails"])


# ── Scraper producer (Dynasty Scraper.py::fetch_sleeper_rosters) ─────


@functools.lru_cache(maxsize=1)
def _scraper_fetch_source() -> ast.Module:
    """Lift ``fetch_sleeper_rosters`` (and ``_env_int``) out of the scraper
    without executing the module — importing it runs minutes of real work.
    """
    tree = ast.parse(_SCRAPER.read_text(encoding="utf-8"))
    wanted = {"fetch_sleeper_rosters", "_env_int"}
    chunks = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in wanted]
    assert {n.name for n in chunks} == wanted, "scraper no longer defines the lifted functions"
    return ast.Module(body=chunks, type_ignores=[])


class _Resp:
    def __init__(self, status: int, body: Any = None, exc: Exception | None = None):
        self.status_code = status
        self._body = body
        self._exc = exc

    def json(self):
        if self._exc is not None:
            raise self._exc
        return self._body

    def raise_for_status(self):
        if self.status_code != 200:
            raise RuntimeError(f"HTTP {self.status_code}")


def _scraper_requests(traded: Any):
    """``traded``: a ``_Resp``, or an Exception to raise from ``get``."""
    year = datetime.date.today().year
    routes = {
        "/players/nfl": _Resp(
            200,
            {
                "P1": {"full_name": "Alpha One", "position": "QB"},
                "P2": {"full_name": "Beta Two", "position": "WR"},
            },
        ),
        f"/league/{LEAGUE_ID}/rosters": _Resp(
            200,
            [
                {"roster_id": 1, "owner_id": "oA", "players": ["P1"]},
                {"roster_id": 2, "owner_id": "oB", "players": ["P2"]},
            ],
        ),
        f"/league/{LEAGUE_ID}/users": _Resp(
            200,
            [
                {"user_id": "oA", "display_name": "Team A"},
                {"user_id": "oB", "display_name": "Team B"},
            ],
        ),
        f"/league/{LEAGUE_ID}": _Resp(
            200,
            {
                "name": "T",
                "season": str(year),
                "settings": {"num_teams": 2, "draft_rounds": 2},
                "scoring_settings": {"rec": 1.0},
                "roster_positions": ["QB", "WR"],
            },
        ),
        f"/league/{LEAGUE_ID}/drafts": _Resp(200, []),
    }

    def get(url: str, timeout: Any = None):
        if url.endswith("/traded_picks"):
            if isinstance(traded, Exception):
                raise traded
            return traded
        for suffix in sorted(routes, key=len, reverse=True):
            if url.endswith(suffix):
                return routes[suffix]
        return _Resp(404, None)

    return types.SimpleNamespace(get=get)


def _scraper_teams(traded: Any) -> dict[int, dict[str, Any]]:
    from src.identity.name_primitives import clean_name
    from src.utils.name_clean import resolve_idp_position
    from src.utils.owner_names import owner_label

    ns: dict[str, Any] = {
        "re": re,
        "datetime": datetime,
        "os": __import__("os"),
        "requests": _scraper_requests(traded),
        "clean_name": clean_name,
        "_owner_label": owner_label,
        "_resolve_idp_position": resolve_idp_position,
        "_pick_identity": pick_identity,
        "DEBUG": False,
    }
    exec(compile(_scraper_fetch_source(), "<scraper-slice>", "exec"), ns)
    _names, roster_data = ns["fetch_sleeper_rosters"](LEAGUE_ID)
    return {t["roster_id"]: t for t in roster_data["teams"]}


@pytest.mark.parametrize(
    "traded",
    [
        _Resp(503, None),
        _Resp(200, {"error": "not a list"}),
        _Resp(200, None, exc=ValueError("bad json")),
        ConnectionError("network down"),
    ],
    ids=["non_200", "non_list_body", "bad_json", "exception"],
)
def test_scraper_failed_traded_picks_fetch_publishes_unknown_not_defaults(traded):
    teams = _scraper_teams(traded)
    assert set(teams) == {1, 2}
    for t in teams.values():
        assert t["picks"] is None, "legacy labels must be unknown, not []"
        assert t["pickDetails"] is None
        assert t["pickOwnershipState"] == "unavailable"
        assert t["pickOwnershipReason"] == "traded_picks_fetch_failed"


def test_scraper_empty_successful_list_still_folds_defaults():
    teams = _scraper_teams(_Resp(200, []))
    for rid, t in teams.items():
        assert t["pickOwnershipState"] == "observed"
        assert t["pickOwnershipReason"] is None
        assert t["picks"] and all("(own)" in label for label in t["picks"])
        assert all(d["fromRosterId"] == rid for d in t["pickDetails"])


def test_scraper_success_ownership_is_unchanged_by_the_state_fields():
    year = datetime.date.today().year
    traded = [{"season": str(year + 1), "round": 1, "roster_id": 2, "owner_id": 1}]
    teams = _scraper_teams(_Resp(200, traded))
    expected = pick_identity.build_pick_ownership(
        _UNREGISTERED,
        [1, 2],
        traded,
        seasons=[year, year + 1, year + 2, year + 3],
        rounds=2,
    )
    owned_by = {}
    for o in expected:
        owned_by.setdefault(o.state.owner_roster_id, set()).add(
            (o.identity.season, o.identity.round_num, o.identity.origin_roster_id)
        )
    for rid, t in teams.items():
        got = {(d["season"], d["round"], d["fromRosterId"]) for d in t["pickDetails"]}
        assert got == owned_by[rid]
        assert len(t["picks"]) == len(t["pickDetails"])
    assert any("(from Team B)" in label for label in teams[1]["picks"])


def test_both_producers_use_the_one_vocabulary():
    """Every producer imports the rule; none keeps a second copy."""
    from src.api import draft_capital_fallback

    src = _SCRAPER.read_text(encoding="utf-8")
    assert '"traded_picks_fetch_failed"' not in src
    assert '"unavailable"' not in src.split("def fetch_sleeper_rosters", 1)[1].split("\ndef ", 1)[0]
    for module in (sleeper_overlay, draft_capital_fallback):
        module_src = Path(module.__file__).read_text(encoding="utf-8")
        assert '"traded_picks_fetch_failed"' not in module_src, module.__name__
        assert "traded_picks_observation" in module_src, module.__name__


# ── The one vocabulary ───────────────────────────────────────────────


def test_traded_picks_observation_distinguishes_empty_from_missing():
    assert pick_identity.traded_picks_observation([]) == []
    assert pick_identity.traded_picks_observation([{"a": 1}]) == [{"a": 1}]
    for body in (None, {}, {"error": "x"}, "", 0):
        assert pick_identity.traded_picks_observation(body) is None


def test_team_reason_reader():
    reason = pick_identity.team_pick_ownership_unavailable_reason
    assert reason({"pickOwnershipState": "observed", "picks": []}) is None
    # legacy payload predating the state field, carrying lists
    assert reason({"picks": ["2027 1st"], "pickDetails": []}) is None
    assert reason(_unknown_team(1)) == "traded_picks_fetch_failed"
    assert reason({"name": "x"}) == "pick_ownership_unstated"


# ── Downstream consumers ─────────────────────────────────────────────


def _unknown_team(rid: int) -> dict[str, Any]:
    return {
        "name": f"Team {rid}",
        "ownerId": f"o{rid}",
        "roster_id": rid,
        "players": [],
        "playerIds": [],
        "picks": None,
        "pickDetails": None,
        **pick_identity.pick_ownership_fields(False),
    }


def _strength_rows() -> list[dict[str, Any]]:
    return [
        {"rosterId": 1, "ownerId": "o1", "teamName": "Team 1", "teamRosStrength": 80.0},
        {"rosterId": 2, "ownerId": "o2", "teamName": "Team 2", "teamRosStrength": 40.0},
    ]


def test_pick_projector_refuses_unknown_ownership_instead_of_zero_picks():
    from src.ros.pick_projection import build_pick_projections

    out = build_pick_projections(
        [_unknown_team(1), _unknown_team(2)], _strength_rows(), current_season=2026
    )
    assert out["picks"] is None
    assert out["meta"]["pickOwnershipState"] == "unavailable"
    assert out["meta"]["pickOwnershipReason"] == "traded_picks_fetch_failed"
    assert out["meta"]["unprojectablePicks"] is None
    # the order depends on strength, not ownership — still served
    assert [r["rosterId"] for r in out["projectedOrder"]] == [2, 1]


def test_pick_projector_observed_state_still_projects():
    from src.ros.pick_projection import build_pick_projections

    teams = _overlay_teams([])
    out = build_pick_projections(teams, _strength_rows(), current_season=2026)
    assert out["picks"], "observed ownership projects future picks"
    assert out["meta"]["pickOwnershipState"] == "observed"


def test_ros_route_marks_unknown_ownership(monkeypatch):
    import asyncio
    import json

    from src.ros import api as ros_api

    monkeypatch.setattr(ros_api, "load_or_compute_team_strength", lambda _k: _strength_rows())
    monkeypatch.setattr(
        "src.api.league_registry.get_league_by_key",
        lambda _k: types.SimpleNamespace(key="lk", sleeper_league_id=LEAGUE_ID),
    )
    monkeypatch.setattr(
        "src.api.sleeper_overlay.fetch_sleeper_teams_overlay",
        lambda sleeper_league_id: {"teams": [_unknown_team(1), _unknown_team(2)]},
    )
    resp = asyncio.run(ros_api.get_pick_projections(None, leagueKey="lk"))
    body = json.loads(resp.body)
    assert body["picks"] is None
    assert body["error"] == "pick_ownership_unavailable"
    assert body["meta"]["pickOwnershipReason"] == "traded_picks_fetch_failed"


def test_bdvm_rosters_carry_unknown_picks_not_empty():
    from src.bdvm.roster import rosters_from_contract

    rosters = rosters_from_contract({"sleeper": {"teams": [_unknown_team(1)]}})
    assert rosters[0]["picks"] is None
    assert rosters[0]["pickOwnershipReason"] == "traded_picks_fetch_failed"
    observed = rosters_from_contract({"sleeper": {"teams": _overlay_teams([])}})
    assert observed[0]["picks"] and observed[0]["pickOwnershipReason"] is None


def test_bdvm_pick_count_is_none_not_zero_when_ownership_unknown():
    from src.bdvm.params import load_param_set
    from src.bdvm.roster import analyze_rosters

    out = analyze_rosters(
        {"players": [], "replacement": {}},
        {"sleeper": {"teams": [_unknown_team(1)]}},
        load_param_set("params_v1"),
    )
    row = out["rosters"][0]
    assert row["pickCount"] is None
    assert row["pickCountUnavailableReason"] == "traded_picks_fetch_failed"


def test_trade_simulator_flags_unknown_pick_ownership():
    from src.api import trade_simulator

    team = _unknown_team(1)
    contract = {"playersArray": [], "sleeper": {"teams": [team]}}
    result = trade_simulator.simulate_trade(contract, resolved_team=team)
    assert result["pickOwnership"]["state"] == "unavailable"
    assert result["pickOwnership"]["reason"] == "traded_picks_fetch_failed"
    observed = {**team, "picks": [], "pickDetails": [], **pick_identity.pick_ownership_fields(True)}
    result = trade_simulator.simulate_trade(contract, resolved_team=observed)
    assert "pickOwnership" not in result


def test_forecast_capture_reads_the_stated_ownership(monkeypatch):
    """The capture fails closed on the overlay's own statement, not on
    watching the URL: a teams block stamped ``unavailable`` is unproven
    even though the capture's getter never saw /traded_picks."""
    from src.ros import pick_forecast_snapshot as snap

    def _no_snapshot(*_a, **_k):
        raise RuntimeError("offline")

    monkeypatch.setattr(
        sleeper_overlay,
        "_build_teams_block",
        lambda lid, id_map, getter=None: [_unknown_team(1), _unknown_team(2)],
    )
    monkeypatch.setattr(
        "src.ros.team_strength.load_or_compute_team_strength",
        lambda *_a, **_k: _strength_rows(),
    )
    monkeypatch.setattr("src.ros.team_strength.persisted_fast_path_rows", lambda _key: None)
    monkeypatch.setattr("src.public_league.snapshot.build_public_snapshot", _no_snapshot)
    cfg = types.SimpleNamespace(key="lk", sleeper_league_id=LEAGUE_ID)
    inputs = snap.gather_inputs(
        cfg,
        {"season": "2026", "season_type": "regular", "week": 5, "display_week": 5},
        contract=None,
        contract_reason="contract_build_skipped",
        http_get=lambda url: None,
    )
    assert inputs.overlay_teams is None
    assert inputs.overlay_reason == "traded_picks_fetch_failed_ownership_unproven"
    assert inputs.forecast is None
