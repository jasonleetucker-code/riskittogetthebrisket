"""#815 — a degraded snapshot must not render as a real empty result.

Observed in production: public ``/league`` ``teamAssignment`` returned
``{"assignments": []}`` with HTTP 200 during a degraded/seasonless
snapshot, and recovered later.  Nothing in the payload distinguished
"we asked and the answer is none" from "we could not ask", and the
frontend printed a cause ("current season has no rosters yet") that it
had not measured.

This suite pins the three states apart.  It is deliberately separate
from ``test_team_assignment.py``, which pins the SCORING model — mixing
availability semantics into that file would bury them.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.api import team_assignment
from src.public_league.identity import Manager, ManagerRegistry, TeamAlias
from src.public_league.snapshot import PublicLeagueSnapshot, SeasonSnapshot


# ── Helpers (kept local; see the module docstring) ─────────────────


def _season(rosters):
    return SeasonSnapshot(
        season="2026",
        league_id="L1",
        league={"settings": {}, "roster_positions": ["QB", "RB", "WR", "TE", "FLEX", "BN"]},
        users=[],
        rosters=rosters,
        matchups_by_week={},
        transactions_by_week={},
        drafts=[],
        draft_picks_by_draft={},
        traded_picks=[],
        winners_bracket=[],
        losers_bracket=[],
    )


def _manager(owner_id, display_name):
    return Manager(
        owner_id=owner_id,
        display_name=display_name,
        current_team_name=display_name,
        current_roster_id=1,
        current_league_id="L1",
        aliases=[
            TeamAlias(
                season="2026",
                league_id="L1",
                team_name=display_name,
                display_name=display_name,
            ),
        ],
    )


def _snapshot(rosters, nfl_players, managers):
    return PublicLeagueSnapshot(
        root_league_id="L1",
        generated_at="2026-04-30T00:00:00Z",
        seasons=[_season(rosters)],
        managers=managers,
        nfl_players=nfl_players,
    )


def _stub_config(monkeypatch, tmp_path: Path):
    p = tmp_path / "team_assignment.json"
    p.write_text(
        json.dumps(
            {
                "favorites": {"jason": {"abbr": "MIN", "display": "Minnesota Vikings"}},
                "displayNameAliases": {},
                "thresholds": {"assignmentMinPoints": 10},
                "limits": {"maxTeamsPerOwner": 3},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(team_assignment, "_CONFIG_PATH", p)


# ── The shape every path must satisfy ──────────────────────────────

_REQUIRED_KEYS = {
    "available",
    "unavailableReason",
    "rosterScoringAvailable",
    "degradedReasons",
    "assignments",
    "config",
    "currentSeason",
    "asOf",
}


def _assert_shaped(section):
    """Every path emits the SAME keys.

    The frontend destructures and maps unconditionally, so a degraded
    payload that drops fields trades one defect for another.
    """
    assert _REQUIRED_KEYS <= set(section), sorted(_REQUIRED_KEYS - set(section))
    assert isinstance(section["assignments"], list)
    assert isinstance(section["degradedReasons"], list)


# ── Total unavailability ───────────────────────────────────────────


def test_no_current_season_is_unavailable_not_empty():
    """THE #815 regression.

    Before the repair this returned a bare ``assignments: []`` and the
    caller had no way to tell it apart from a healthy empty league.
    """
    snap = PublicLeagueSnapshot(
        root_league_id="L1",
        generated_at="2026-04-30T00:00:00Z",
        seasons=[],
    )
    section = team_assignment.build_section(snap)
    _assert_shaped(section)
    assert section["available"] is False
    assert section["unavailableReason"] == team_assignment.UNAVAILABLE_NO_CURRENT_SEASON
    assert section["assignments"] == []
    assert section["currentSeason"] is None


def test_season_present_but_no_rosters_is_its_own_reason():
    """Distinct from a missing season: the season resolved, it just
    carries nothing.  Collapsing the two would make the recovered vs.
    never-started cases indistinguishable."""
    snap = _snapshot([], {}, ManagerRegistry(by_owner_id={}))
    section = team_assignment.build_section(snap)
    _assert_shaped(section)
    assert section["available"] is False
    assert section["unavailableReason"] == team_assignment.UNAVAILABLE_NO_ROSTERS


# ── Partial degradation ────────────────────────────────────────────


def test_missing_player_directory_is_degraded_not_a_zero_score(monkeypatch, tmp_path: Path):
    """``snapshot.nfl_players`` empty scores every player 0.

    That is reachable in production: ``snapshot.build`` swallows the
    ~5 MB dump's fetch error and falls back to ``{}``.  Without the
    flag, a favorite-only card asserts "no roster team qualified" from
    evidence that was never read.
    """
    _stub_config(monkeypatch, tmp_path)
    mgrs = ManagerRegistry(by_owner_id={"oA": _manager("oA", "jason")})
    rosters = [{"roster_id": 1, "owner_id": "oA", "players": ["p1", "p2", "p3"]}]
    section = team_assignment.build_section(_snapshot(rosters, {}, mgrs))
    _assert_shaped(section)

    # The section IS available — the favorite is config-derived and real.
    assert section["available"] is True
    assert section["rosterScoringAvailable"] is False
    assert team_assignment.DEGRADED_NO_PLAYER_DIRECTORY in section["degradedReasons"]

    a = section["assignments"][0]
    assert a["rosterScored"] is False
    assert a["playersResolved"] == 0
    assert a["playersTotal"] == 3
    # The favorite still surfaces; only the roster-derived half is absent.
    assert [t["abbr"] for t in a["nflTeams"]] == ["MIN"]


def test_partial_directory_reports_how_much_it_could_resolve(monkeypatch, tmp_path: Path):
    """A directory that answers for SOME ids is not a failure, but the
    coverage must be visible — otherwise a half-read roster silently
    scores half as high as it should."""
    _stub_config(monkeypatch, tmp_path)
    mgrs = ManagerRegistry(by_owner_id={"oA": _manager("oA", "jason")})
    rosters = [{"roster_id": 1, "owner_id": "oA", "players": ["p1", "p2", "ghost"]}]
    nfl = {
        "p1": {"team": "KC", "position": "QB", "depth_chart_order": 1, "years_exp": 5},
        "p2": {"team": "KC", "position": "WR", "depth_chart_order": 1, "years_exp": 3},
    }
    section = team_assignment.build_section(_snapshot(rosters, nfl, mgrs))
    _assert_shaped(section)
    assert section["available"] is True
    assert section["rosterScoringAvailable"] is True
    assert section["degradedReasons"] == []

    a = section["assignments"][0]
    assert a["rosterScored"] is True
    assert a["playersResolved"] == 2
    assert a["playersTotal"] == 3


# ── The healthy path keeps its meaning ─────────────────────────────


def test_healthy_empty_result_is_still_expressible(monkeypatch, tmp_path: Path):
    """A real "nothing qualified" answer must remain available:True.

    Otherwise the repair overcorrects and every quiet league reads as
    broken.
    """
    _stub_config(monkeypatch, tmp_path)
    mgrs = ManagerRegistry(by_owner_id={"oB": _manager("oB", "nofavorite")})
    rosters = [{"roster_id": 1, "owner_id": "oB", "players": ["p1"]}]
    # One deep-bench body: resolves fine, scores 0, clears no threshold.
    nfl = {"p1": {"team": "KC", "position": "WR", "depth_chart_order": 7, "years_exp": 4}}
    section = team_assignment.build_section(_snapshot(rosters, nfl, mgrs))
    _assert_shaped(section)
    assert section["available"] is True
    assert section["unavailableReason"] is None
    assert section["rosterScoringAvailable"] is True
    a = section["assignments"][0]
    assert a["rosterScored"] is True
    assert a["nflTeams"] == []


def test_reason_constants_are_distinct_and_stable():
    """The frontend keys messages off these strings; a silent rename
    would fall through to the generic text without failing anything."""
    reasons = {
        team_assignment.UNAVAILABLE_NO_CURRENT_SEASON,
        team_assignment.UNAVAILABLE_NO_ROSTERS,
        team_assignment.DEGRADED_NO_PLAYER_DIRECTORY,
    }
    assert reasons == {"no_current_season", "no_rosters", "player_directory_unavailable"}
