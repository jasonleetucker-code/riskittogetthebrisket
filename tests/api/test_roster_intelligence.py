"""``GET /api/roster/intelligence`` assembly.

The shell over the canonical roster-intelligence chain. What matters
here is that it composes the owners rather than recomputing anything,
that the league-relative half is computed league-wide (a rank invented
for one team in isolation is not a rank), and that the two known
limitations are STAMPED rather than implied.

Builds a synthetic ``LeagueBundle`` rather than reading a live snapshot:
``data/ros/team_strength/`` is a gitignored production artifact, so a
test that needed it would be a `livedata` test and would give the hard
gate no coverage at all.
"""

from __future__ import annotations

import pytest

from src.api import gameplan as _gameplan
from src.api import roster_intelligence as ri
from src.roster_intel.core import build_meaningful_core
from src.roster_intel.strength import build_team_strength

_SLOTS = ("QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "SUPER_FLEX")


def _row(pid, pos, value):
    return {
        "playerId": pid,
        "canonicalName": pid,
        "position": pos,
        "rosValue": value,
        "confidence": 1.0,
    }


def _team(owner_id, *, scale=1.0, depth=4):
    rows = []
    for pos in ("QB", "RB", "WR", "TE"):
        for i in range(depth):
            rows.append(_row(f"{owner_id}_{pos}{i}", pos, round((900 - i * 90) * scale, 2)))
    return _gameplan.TeamInput(
        owner_id=owner_id,
        team_name=f"Team {owner_id}",
        rows=tuple(rows),
        pool=tuple(_gameplan.to_roster_players(rows)),
    )


def _bundle(n_teams=4, ages=True):
    teams = tuple(_team(f"o{i}", scale=1.0 + i * 0.1) for i in range(n_teams))
    player_meta = {}
    if ages:
        for t in teams:
            for j, row in enumerate(t.rows):
                player_meta[row["playerId"]] = {"age": 22.0 + (j % 8)}
    inputs = _gameplan.LeagueInputs(
        league_key="test_league",
        scoring_profile="test_profile",
        slots=_SLOTS,
        teams=teams,
        player_meta=player_meta,
        site_values={},
        playoff_odds=None,
        source_stamp="stamp",
        notes=("a note from the loader",),
    )
    return _gameplan.LeagueBundle(
        inputs=inputs,
        replacement={},
        scarcity={},
        lineup_scores={},
        intel={},
        signals={},
        compute_ms=0.0,
    )


def _contract(bundle):
    return {
        "meta": {"leagueKey": "test_league"},
        "playersArray": [
            {
                "playerId": row["playerId"],
                "position": row["position"],
                "rankDerivedValue": row["rosValue"],
                "age": (bundle.inputs.player_meta.get(row["playerId"]) or {}).get("age"),
            }
            for t in bundle.inputs.teams
            for row in t.rows
        ]
        # A pick row, which must never reach a positional rank.
        + [{"playerId": "mp1", "position": "PICK", "assetClass": "pick", "rankDerivedValue": 5000}],
    }


def _league(**kw):
    b = _bundle(**kw)
    return b, ri.build_league_roster_intelligence(b, _contract(b), team_count=12)


# ══ It composes the owners; it recomputes nothing ══════════════════


def test_every_team_carries_all_four_outputs():
    _, out = _league()
    assert len(out["teams"]) == 4
    for team in out["teams"].values():
        assert set(team) == {"ownerId", "teamName", "core", "strength", "weakness", "agePortfolio"}


def test_the_payload_matches_the_owners_called_directly():
    """If this drifts, the endpoint and a direct `src.roster_intel`
    consumer are giving two answers to one question — the failure the
    whole lane exists to remove."""
    bundle, out = _league()
    team = bundle.inputs.teams[0]
    core = build_meaningful_core(list(team.pool), list(_SLOTS))
    assert out["teams"][team.owner_id]["core"]["members"] == core.to_dict()["members"]
    assert (
        out["teams"][team.owner_id]["strength"]["total"]
        == build_team_strength(core).to_dict()["total"]
    )


def test_league_relative_fields_are_computed_across_the_whole_league():
    """A rank invented for one team in isolation is not a rank."""
    _, out = _league()
    ranks = sorted(t["strength"]["leagueRank"] for t in out["teams"].values())
    assert ranks == [1, 2, 3, 4]
    indices = [t["agePortfolio"]["youngCoreIndex"] for t in out["teams"].values()]
    assert all(i is not None for i in indices)


# ══ Limitations are stamped, not implied ═══════════════════════════


def test_unpriced_visibility_is_stamped():
    """`unpricedIds` is empty by construction on this path because the
    snapshot writer drops unpriced rows. A reader must not mistake that
    for a fully priced roster."""
    _, out = _league()
    assert out["rosterSource"] == "ros_team_strength_snapshot"
    assert "ros/team_strength.py" in out["unpricedVisibility"]
    assert "NOT evidence" in out["unpricedVisibility"]


def test_rank_population_is_stamped():
    _, out = _league()
    assert out["rankPopulation"] == "contract_board_priced_players"
    for team in out["teams"].values():
        assert team["weakness"]["rankPopulation"] == "contract_board_priced_players"


def test_loader_notes_are_carried_through():
    """The bundle's own notes describe real incomparabilities; dropping
    them here would hide them."""
    _, out = _league()
    assert "a note from the loader" in out["notes"]


# ══ Thresholds use the DECLARED league size ════════════════════════


def test_declared_team_count_wins_over_the_roster_count():
    """A snapshot missing one roster must not shrink every weakness
    threshold — the bug would look like the whole league improving."""
    bundle = _bundle(n_teams=4)
    out = ri.build_league_roster_intelligence(bundle, _contract(bundle), team_count=12)
    rungs = out["teams"]["o0"]["weakness"]["needs"]
    qb = next(n for n in rungs if n["position"] == "QB")
    assert [r["thresholdRank"] for r in qb["rungs"]] == [12, 24]


def test_roster_count_is_the_fallback_not_a_constant():
    bundle = _bundle(n_teams=4)
    out = ri.build_league_roster_intelligence(bundle, _contract(bundle))
    assert out["teamCount"] == 4
    qb = next(n for n in out["teams"]["o0"]["weakness"]["needs"] if n["position"] == "QB")
    assert [r["thresholdRank"] for r in qb["rungs"]] == [4, 8]


# ══ Board population ═══════════════════════════════════════════════


def test_picks_never_enter_the_positional_rank_population():
    bundle = _bundle()
    rows = ri._board_players(_contract(bundle))
    assert all(pos != "PICK" for _, pos, _ in rows)


def test_an_unpriced_board_row_is_carried_as_none_not_dropped_silently():
    """`build_position_ranks` owns the decision to exclude it, and does
    so for a stated reason. Filtering here would move that decision
    somewhere it is not explained."""
    contract = {"playersArray": [{"playerId": "x", "position": "QB", "rankDerivedValue": None}]}
    assert ri._board_players(contract) == [("x", "QB", None)]


def test_no_contract_yields_an_empty_board_rather_than_raising():
    assert ri._board_players(None) == []


# ══ Team view ══════════════════════════════════════════════════════


def test_team_view_returns_the_team_plus_league_context(monkeypatch):
    bundle = _bundle()
    monkeypatch.setattr(_gameplan, "get_league_bundle", lambda *a, **k: (bundle, True))
    out = ri.get_team_roster_intelligence(
        "test_league", "test_profile", _contract(bundle), "o0", team_count=12
    )
    assert out["team"]["ownerId"] == "o0"
    # Context carries every team, ordered by strength rank, but not the
    # full per-team payload — one team's request should not ship four
    # rosters' worth of detail.
    assert [c["ownerId"] for c in out["leagueContext"]] == ["o3", "o2", "o1", "o0"]
    assert "teams" not in out
    assert set(out["leagueContext"][0]) == {
        "ownerId",
        "teamName",
        "strengthTotal",
        "strengthRank",
        "youngCoreIndex",
        "valueWeightedCoreAge",
    }


def test_an_unknown_team_raises_rather_than_returning_an_empty_team(monkeypatch):
    """ "This owner is not in the league" and "this owner has nothing"
    are different answers."""
    bundle = _bundle()
    monkeypatch.setattr(_gameplan, "get_league_bundle", lambda *a, **k: (bundle, True))
    with pytest.raises(ri.TeamNotInLeague):
        ri.get_team_roster_intelligence("test_league", "test_profile", _contract(bundle), "nobody")


def test_contract_version_is_stamped():
    _, out = _league()
    assert out["contractVersion"] == ri.ROSTER_INTELLIGENCE_CONTRACT_VERSION


# ══ Degradation ════════════════════════════════════════════════════


def test_no_ages_degrades_honestly_rather_than_reporting_zero():
    _, out = _league(ages=False)
    for team in out["teams"].values():
        assert team["agePortfolio"]["valueWeightedCoreAge"] is None
        assert team["agePortfolio"]["youngCoreIndex"] is None
        # Strength is age-independent and must survive intact.
        assert team["strength"]["total"] > 0


def test_no_contract_still_produces_core_and_strength():
    """Rosters come from the snapshot, not the contract. Losing the
    board costs ranks and ages — it must not cost the lineup solve."""
    bundle = _bundle()
    out = ri.build_league_roster_intelligence(bundle, None, team_count=12)
    team = out["teams"]["o0"]
    assert team["core"]["starterCount"] > 0
    assert team["strength"]["total"] > 0
    # Every weakness rung is UNKNOWN — unmeasured, not failed.
    for need in team["weakness"]["needs"]:
        assert need["unmetRungs"] == 0
        assert need["unknownRungs"] + need["unfilledRungs"] == len(need["rungs"])
