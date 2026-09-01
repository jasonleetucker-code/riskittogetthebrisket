"""#815 — a degraded snapshot must not render as a real empty result.

Observed in production: public ``/league`` ``teamAssignment`` returned
``{"assignments": []}`` with HTTP 200 during a degraded/seasonless
snapshot, and recovered later. Nothing in the payload distinguished
"we asked and the answer is none" from "we could not ask".

The 2026-09-01 NFL Team Affinity rewrite adds two MORE ways evidence
can be partial or absent (no canonical contract; no NFL starter
signal) on top of the original season/roster gate, and this suite
pins all of them apart. Deliberately separate from
``test_team_assignment.py``, which pins the FORMULA — mixing
availability semantics into that file would bury them.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.api import team_assignment
from src.public_league.identity import Manager, ManagerRegistry, TeamAlias
from src.public_league.snapshot import PublicLeagueSnapshot, SeasonSnapshot


# ── Helpers (kept local; see the module docstring) ─────────────────

_SLOTS = ["QB", "RB", "WR", "TE", "FLEX", "BN"]


def _season(rosters):
    return SeasonSnapshot(
        season="2026",
        league_id="L1",
        league={"settings": {}, "roster_positions": list(_SLOTS)},
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


def _row(canonical_name, position, team, value, *, player_id=None):
    return {
        "canonicalName": canonical_name,
        "displayName": canonical_name,
        "position": position,
        "team": team,
        "rankDerivedValue": value,
        "playerId": player_id,
        "assetClass": "offense",
    }


def _contract(rows, teams):
    positions = {r["canonicalName"]: r["position"] for r in rows}
    by_name = {r["canonicalName"]: r for r in rows}
    team_dicts = [
        {
            "ownerId": owner_id,
            "name": f"team-{owner_id}",
            "players": list(names),
            "playerIds": [by_name.get(n, {}).get("playerId") for n in names],
        }
        for owner_id, names in teams.items()
    ]
    return {
        "meta": {"leagueKey": "dynasty_main"},
        "playersArray": rows,
        "sleeper": {
            "teams": team_dicts,
            "rosterPositions": list(_SLOTS),
            "positions": positions,
            "fantasyPositions": {},
        },
    }


def _stub_config(monkeypatch, tmp_path: Path):
    p = tmp_path / "team_assignment.json"
    p.write_text(
        json.dumps(
            {
                "favorites": {"jason": {"abbr": "MIN", "display": "Minnesota Vikings"}},
                "displayNameAliases": {},
                "weights": {"nflStartingQbMultiplier": 2.0},
                "thresholds": {"rosterAssignmentMinShare": 0.10},
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
    "qbSignalAvailable",
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


# ── Total unavailability (season/roster gate, unchanged) ───────────


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
    section = team_assignment.build_section(snap, None)
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
    section = team_assignment.build_section(snap, None)
    _assert_shaped(section)
    assert section["available"] is False
    assert section["unavailableReason"] == team_assignment.UNAVAILABLE_NO_ROSTERS


# ── Contract-level degradation (new: canonical MeaningfulCore/value) ─


def test_missing_contract_is_degraded_not_a_zero_score(monkeypatch, tmp_path: Path):
    """No canonical contract at all -- roster-based scoring is
    unavailable, but the favorite is config-derived and real."""
    _stub_config(monkeypatch, tmp_path)
    mgrs = ManagerRegistry(by_owner_id={"oA": _manager("oA", "jason")})
    rosters = [{"roster_id": 1, "owner_id": "oA", "players": ["p1", "p2", "p3"]}]
    section = team_assignment.build_section(_snapshot(rosters, {}, mgrs), None)
    _assert_shaped(section)

    assert section["available"] is True
    assert section["rosterScoringAvailable"] is False
    assert team_assignment.DEGRADED_NO_CONTRACT in section["degradedReasons"]

    a = section["assignments"][0]
    assert a["rosterScored"] is False
    assert a["totalWeightedCoreValue"] is None
    # The favorite still surfaces; only the roster-derived half is absent.
    assert [t["abbr"] for t in a["nflTeams"]] == ["MIN"]


def test_league_wide_contract_available_but_one_team_unmatched(monkeypatch, tmp_path: Path):
    """The contract loads and scores fine for managers it can match;
    a manager missing from the contract's own team list is reported
    per-team, not silently folded into the global degraded state."""
    _stub_config(monkeypatch, tmp_path)
    mgrs = ManagerRegistry(
        by_owner_id={"oA": _manager("oA", "jason"), "oB": _manager("oB", "nofavorite")}
    )
    rosters = [
        {"roster_id": 1, "owner_id": "oA", "players": ["p1"]},
        {"roster_id": 2, "owner_id": "oB", "players": ["p2"]},
    ]
    rows = [_row("p1", "RB", "KC", 4000, player_id="p1")]
    contract = _contract(rows, {"oA": ["p1"]})  # oB absent
    section = team_assignment.build_section(_snapshot(rosters, {}, mgrs), contract)
    _assert_shaped(section)
    assert section["rosterScoringAvailable"] is True

    by_owner = {a["ownerId"]: a for a in section["assignments"]}
    assert by_owner["oA"]["rosterScored"] is True
    assert by_owner["oB"]["rosterScored"] is False
    assert by_owner["oB"]["rosterUnavailableReason"] == team_assignment.ROSTER_REASON_NOT_IN_CONTRACT


def test_qb_signal_unavailable_does_not_block_roster_scoring(monkeypatch, tmp_path: Path):
    """No Sleeper NFL player directory -- the QB multiplier fails
    closed to 1.0x, but roster-based affinity still computes from
    canonical values."""
    _stub_config(monkeypatch, tmp_path)
    mgrs = ManagerRegistry(by_owner_id={"oA": _manager("oA", "jason")})
    rosters = [{"roster_id": 1, "owner_id": "oA", "players": ["p1"]}]
    rows = [_row("p1", "RB", "KC", 4000, player_id="p1")]
    contract = _contract(rows, {"oA": ["p1"]})
    section = team_assignment.build_section(_snapshot(rosters, {}, mgrs), contract)
    _assert_shaped(section)
    assert section["qbSignalAvailable"] is False
    assert team_assignment.DEGRADED_NO_QB_SIGNAL in section["degradedReasons"]
    assert section["rosterScoringAvailable"] is True
    a = section["assignments"][0]
    assert a["rosterScored"] is True
    assert a["totalWeightedCoreValue"] == 4000.0


# ── The healthy path keeps its meaning ─────────────────────────────


def test_healthy_empty_result_is_still_expressible(monkeypatch, tmp_path: Path):
    """A real "nothing qualified" answer must remain available:True.

    An empty roster (present in the contract, zero players) is scored
    fine -- Meaningful Core is legitimately empty, not unreadable -- and
    must render as ``nflTeams: []`` rather than a degraded state."""
    _stub_config(monkeypatch, tmp_path)
    mgrs = ManagerRegistry(by_owner_id={"oB": _manager("oB", "nofavorite")})
    rosters = [{"roster_id": 1, "owner_id": "oB", "players": []}]
    contract = _contract([], {"oB": []})
    section = team_assignment.build_section(_snapshot(rosters, {}, mgrs), contract)
    _assert_shaped(section)
    assert section["available"] is True
    assert section["unavailableReason"] is None
    assert section["rosterScoringAvailable"] is True
    a = section["assignments"][0]
    assert a["rosterScored"] is True
    assert a["totalWeightedCoreValue"] == 0.0
    assert a["nflTeams"] == []


def test_reason_constants_are_distinct_and_stable():
    """The frontend keys messages off these strings; a silent rename
    would fall through to the generic text without failing anything."""
    reasons = {
        team_assignment.UNAVAILABLE_NO_CURRENT_SEASON,
        team_assignment.UNAVAILABLE_NO_ROSTERS,
        team_assignment.DEGRADED_NO_CONTRACT,
        team_assignment.DEGRADED_NO_QB_SIGNAL,
        team_assignment.ROSTER_REASON_NOT_IN_CONTRACT,
    }
    assert reasons == {
        "no_current_season",
        "no_rosters",
        "canonical_contract_unavailable",
        "qb_starter_signal_unavailable",
        "team_not_in_contract_pool",
    }
