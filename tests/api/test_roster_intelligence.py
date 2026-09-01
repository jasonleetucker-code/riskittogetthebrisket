"""``GET /api/roster/intelligence`` assembly.

The shell over the canonical roster-intelligence chain. What matters
here is that it composes the owners rather than recomputing anything,
that the league-relative half is computed league-wide (a rank invented
for one team in isolation is not a rank), and that unpriced roster
membership SURVIVES to the consumer.

Fixtures are contracts, not ROS bundles, and that is the point of the
suite as much as its setup: rosters now come from
``data_contract.contract_roster_pools`` — canonical ``rankDerivedValue``
over full ``sleeper.teams[].players`` membership — rather than from the
ROS team-strength snapshot, which carried a 0-100 production index and
deleted every unpriced player before writing.
"""

from __future__ import annotations

import pytest

from src.api import roster_intelligence as ri
from src.roster_intel.core import build_meaningful_core
from src.roster_intel.exposure import nfl_team_by_player
from src.roster_intel.strength import build_team_strength

_SLOTS = ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "SUPER_FLEX"]


def _contract(n_teams=4, *, ages=True, depth=4, unpriced=0, teams_present=True):
    """A minimal but REAL-shaped contract: sleeper block + board."""
    positions, rows, teams = {}, [], []
    for ti in range(n_teams):
        owner, names = f"o{ti}", []
        for pos in ("QB", "RB", "WR", "TE"):
            for i in range(depth):
                name = f"{owner}_{pos}{i}"
                names.append(name)
                positions[name] = pos
                rows.append(
                    {
                        "playerId": f"id_{name}",
                        "canonicalName": name,
                        "displayName": name,
                        "position": pos,
                        "rankDerivedValue": round((900 - i * 90) * (1 + ti * 0.1), 2),
                        **({"age": 22.0 + (i % 8)} if ages else {}),
                    }
                )
        # Rostered players the board never priced: present on the roster,
        # absent from ``playersArray`` entirely.
        for u in range(unpriced):
            name = f"{owner}_GHOST{u}"
            names.append(name)
            positions[name] = "WR"
        teams.append({"ownerId": owner, "name": f"Team {owner}", "players": names})
    contract = {
        "meta": {"leagueKey": "test_league"},
        "playersArray": rows
        + [
            {
                "playerId": "mp1",
                "canonicalName": "2027 Pick 1.01",
                "position": "PICK",
                "assetClass": "pick",
                "rankDerivedValue": 5000,
            }
        ],
        "sleeper": {
            "rosterPositions": list(_SLOTS) + ["BN", "BN"],
            "positions": positions,
            "teams": teams if teams_present else [],
        },
    }
    return contract


def _league(**kw):
    c = _contract(**kw)
    return c, ri.build_league_roster_intelligence(c, team_count=12)


# ══ It composes the owners; it recomputes nothing ══════════════════


def test_every_team_carries_the_full_output_set():
    """Exact equality, not a subset: a new key appearing unannounced is
    how a payload grows a second answer to a question that already has
    one.  ``droppability`` is the deliberate exception and is opt-in."""
    _, out = _league()
    assert len(out["teams"]) == 4
    for team in out["teams"].values():
        assert {
            "ownerId",
            "teamName",
            "rosteredCount",
            "core",
            "strength",
            "weakness",
            "agePortfolio",
            "nflExposure",
        } == set(team)


def test_the_payload_matches_the_owners_called_directly():
    """If this drifts, the endpoint and a direct `src.roster_intel`
    consumer are giving two answers to one question — the failure the
    whole lane exists to remove."""
    from src.api.data_contract import contract_roster_pools

    c, out = _league()
    pools, slots, _ = contract_roster_pools(c)
    core = build_meaningful_core(pools["o0"], slots)
    assert out["teams"]["o0"]["core"]["members"] == core.to_dict()["members"]
    assert out["teams"]["o0"]["strength"]["total"] == build_team_strength(core).to_dict()["total"]


def test_league_relative_fields_are_computed_across_the_whole_league():
    """A rank invented for one team in isolation is not a rank."""
    _, out = _league()
    assert sorted(t["strength"]["leagueRank"] for t in out["teams"].values()) == [1, 2, 3, 4]
    assert all(t["agePortfolio"]["youngCoreIndex"] is not None for t in out["teams"].values())


# ══ Unpriced roster membership SURVIVES ════════════════════════════


def test_unpriced_rostered_players_reach_the_consumer():
    """THE repair. The ROS snapshot dropped `rosValue <= 0` before
    writing, so `unpricedIds` was structurally empty — not because every
    player was priced, but because the unpriced ones never arrived.

    V1's missing-is-never-zero rule requires the consumer to tell an
    unpriced asset from a valued-zero one, and a source that deletes the
    evidence makes that impossible however correct the consumer is.
    """
    _, out = _league(unpriced=3)
    for team in out["teams"].values():
        unpriced = team["core"]["unpricedIds"]
        assert len(unpriced) == 3, unpriced
        assert all(u.endswith(("GHOST0", "GHOST1", "GHOST2")) for u in unpriced)


def test_an_unpriced_player_is_neither_in_the_core_nor_valued_at_zero():
    _, out = _league(unpriced=2)
    team = out["teams"]["o0"]
    core_ids = {m["playerId"] for m in team["core"]["members"]}
    assert not (core_ids & set(team["core"]["unpricedIds"]))
    # And they did not drag the aggregate down by counting as 0.
    _, clean = _league(unpriced=0)
    assert team["strength"]["total"] == clean["teams"]["o0"]["strength"]["total"]


def test_roster_count_includes_unpriced_players():
    """`rosteredCount` is roster MEMBERSHIP, so it must count players the
    board could not price — otherwise the payload silently agrees with
    the source that deleted them."""
    _, out = _league(unpriced=3)
    _, clean = _league(unpriced=0)
    assert out["teams"]["o0"]["rosteredCount"] == clean["teams"]["o0"]["rosteredCount"] + 3


def test_unpriced_visibility_is_stamped_and_names_the_real_source():
    _, out = _league()
    assert out["rosterSource"] == "canonical_contract"
    assert "never counted as zero" in out["unpricedVisibility"]


def test_rank_population_is_stamped():
    _, out = _league()
    assert out["rankPopulation"] == "contract_board_priced_players"
    for team in out["teams"].values():
        assert team["weakness"]["rankPopulation"] == "contract_board_priced_players"


# ══ The board join key ═════════════════════════════════════════════


def test_board_rows_are_keyed_by_the_name_the_pools_use():
    """Keying the board by `playerId` while pools key by name is a
    SILENT failure: ranks match nothing, so every weakness rung reports
    UNKNOWN and every Young Core Index comes back None — with a fully
    shaped payload and no exception. It shipped that way briefly and was
    caught by running a real board, not by a test. This is the test."""
    c, out = _league()
    rows = ri._board_players(c)
    keys = {k for k, _, _ in rows}
    assert "o0_QB0" in keys
    assert not any(k.startswith("id_") for k in keys)
    # And the downstream consequence is asserted, not just the shape.
    for team in out["teams"].values():
        assert team["agePortfolio"]["youngCoreIndex"] is not None
        assert any(
            r["status"] != "unknown" for need in team["weakness"]["needs"] for r in need["rungs"]
        )


def test_picks_never_enter_the_positional_rank_population():
    c = _contract()
    assert all(pos != "PICK" for _, pos, _ in ri._board_players(c))


def test_an_unpriced_board_row_is_carried_as_none_not_dropped_silently():
    """`build_position_ranks` owns the decision to exclude it, and does
    so for a stated reason. Filtering here would move that decision
    somewhere it is not explained."""
    contract = {
        "playersArray": [{"canonicalName": "x", "position": "QB", "rankDerivedValue": None}]
    }
    assert ri._board_players(contract) == [("x", "QB", None)]


def test_no_contract_yields_an_empty_board_rather_than_raising():
    assert ri._board_players(None) == []


# ══ Thresholds use the DECLARED league size ════════════════════════


def test_declared_team_count_wins_over_the_roster_count():
    """A contract missing one roster must not shrink every weakness
    threshold — the bug would look like the whole league improving."""
    _, out = _league(n_teams=4)
    qb = next(n for n in out["teams"]["o0"]["weakness"]["needs"] if n["position"] == "QB")
    assert [r["thresholdRank"] for r in qb["rungs"]] == [12, 24]


def test_roster_count_is_the_fallback_not_a_constant():
    c = _contract(n_teams=4)
    out = ri.build_league_roster_intelligence(c)
    assert out["teamCount"] == 4
    qb = next(n for n in out["teams"]["o0"]["weakness"]["needs"] if n["position"] == "QB")
    assert [r["thresholdRank"] for r in qb["rungs"]] == [4, 8]


# ══ Team view ══════════════════════════════════════════════════════


def test_team_view_returns_the_team_plus_league_context():
    c = _contract()
    out = ri.get_team_roster_intelligence(c, "o0", team_count=12)
    assert out["team"]["ownerId"] == "o0"
    assert [x["ownerId"] for x in out["leagueContext"]] == ["o3", "o2", "o1", "o0"]
    assert "teams" not in out
    assert set(out["leagueContext"][0]) == {
        "ownerId",
        "teamName",
        "strengthTotal",
        "strengthRank",
        "youngCoreIndex",
        "valueWeightedCoreAge",
    }


def test_an_unknown_team_raises_rather_than_returning_an_empty_team():
    """ "This owner is not in the league" and "this owner has nothing"
    are different answers."""
    with pytest.raises(ri.TeamNotInLeague):
        ri.get_team_roster_intelligence(_contract(), "nobody")


def test_contract_version_and_slot_source_are_stamped():
    _, out = _league()
    assert out["contractVersion"] == ri.ROSTER_INTELLIGENCE_CONTRACT_VERSION
    assert out["slotSource"] == "sleeper_roster_positions"


# ══ Degradation ════════════════════════════════════════════════════


def test_no_ages_degrades_honestly_rather_than_reporting_zero():
    _, out = _league(ages=False)
    for team in out["teams"].values():
        assert team["agePortfolio"]["valueWeightedCoreAge"] is None
        assert team["agePortfolio"]["youngCoreIndex"] is None
        # Strength is age-independent and must survive intact.
        assert team["strength"]["total"] > 0


def test_a_contract_with_no_teams_yields_no_teams_rather_than_raising():
    out = ri.build_league_roster_intelligence(_contract(teams_present=False))
    assert out["teams"] == {}
    assert out["starterSlots"] == []


def test_no_contract_at_all_is_shaped_and_empty():
    out = ri.build_league_roster_intelligence(None)
    assert out["teams"] == {}
    assert out["contractVersion"] == ri.ROSTER_INTELLIGENCE_CONTRACT_VERSION


# ══ Droppability is composed, opt-in, and stamped ══════════════════


def test_droppability_is_absent_by_default_and_the_absence_is_stamped():
    """OFF by default is a measured choice: the four core outputs cost
    69 ms on the live 12-team board and the cut ladder a further 710 ms.

    The stamp is what keeps that honest — "you did not ask for it" and
    "this team has nothing droppable" are different answers, and an
    absent key alone cannot tell them apart."""
    _, out = _league()
    assert out["droppabilityIncluded"] is False
    assert all("droppability" not in team for team in out["teams"].values())


def test_droppability_when_requested_matches_the_owner_called_directly():
    """Composition, not recomputation — the same rule the four core
    outputs follow."""
    from src.roster_intel.droppability import team_droppability

    c = _contract()
    out = ri.build_league_roster_intelligence(c, team_count=12, include_droppability=True)
    assert out["droppabilityIncluded"] is True
    for oid, team in out["teams"].items():
        assert team["droppability"] == team_droppability(c, owner_id=oid)


def test_the_team_view_computes_one_ladder_not_twelve():
    """The other eleven ladders are not part of this answer, and the
    league loop costs 13x this one."""
    from src.roster_intel.droppability import team_droppability

    c = _contract()
    out = ri.get_team_roster_intelligence(c, "o0", team_count=12, include_droppability=True)
    assert out["droppabilityIncluded"] is True
    assert out["team"]["droppability"] == team_droppability(c, owner_id="o0")
    # League context carries ranks, never other teams' cut ladders.
    assert all("droppability" not in row for row in out["leagueContext"])


def test_requesting_droppability_does_not_disturb_the_four_core_outputs():
    c = _contract()
    plain = ri.build_league_roster_intelligence(c, team_count=12)
    with_drops = ri.build_league_roster_intelligence(c, team_count=12, include_droppability=True)
    for oid, team in plain["teams"].items():
        other = dict(with_drops["teams"][oid])
        other.pop("droppability", None)
        assert other == team


# ══ NFL exposure is descriptive, and present for every team ════════


def test_every_team_carries_both_exposure_scopes():
    _, out = _league()
    for team in out["teams"].values():
        exposure = team["nflExposure"]
        assert exposure["core"]["scope"] == "meaningful_core"
        assert exposure["fullRoster"]["scope"] == "full_roster"


def test_exposure_matches_the_owner_called_directly():
    from src.api.data_contract import contract_roster_pools
    from src.roster_intel.exposure import exposure_from_core

    c, out = _league()
    pools, slots, _ = contract_roster_pools(c)
    core = build_meaningful_core(pools["o0"], slots)
    direct = exposure_from_core(core, teams=nfl_team_by_player(c))
    assert out["teams"]["o0"]["nflExposure"]["core"] == direct.to_dict()


def test_an_unpriced_rostered_player_reaches_the_full_roster_exposure_unweighted():
    """Roster membership is real even when the value is not; the share
    denominator must exclude him without deleting the evidence that he
    is there."""
    _, out = _league(unpriced=3)
    full = out["teams"]["o0"]["nflExposure"]["fullRoster"]
    assert len(full["unpricedIds"]) == 3
    assert all(pid not in b["playerIds"] for pid in full["unpricedIds"] for b in full["buckets"])


def test_a_board_row_with_no_nfl_team_is_not_given_a_bucket():
    """The fixture carries no ``team`` field at all, so every player is
    unknown-team.  That must produce an empty bucket list and a full
    ``unknownTeamIds``, never a franchise called UNKNOWN holding 100%."""
    _, out = _league()
    core = out["teams"]["o0"]["nflExposure"]["core"]
    assert core["buckets"] == []
    assert core["topFranchiseShare"] is None
    assert len(core["unknownTeamIds"]) > 0


def test_nfl_teams_are_keyed_the_way_the_pools_are():
    """Same silent-failure class as ``_board_players``: a playerId key
    against name-keyed pools produces a fully shaped, entirely empty
    exposure with nothing raised."""
    c = _contract()
    for row in c["playersArray"]:
        row["team"] = "MIN"
    keys = set(nfl_team_by_player(c))
    assert "o0_QB0" in keys
    assert not any(k.startswith("id_") for k in keys)
    out = ri.build_league_roster_intelligence(c, team_count=12)
    core = out["teams"]["o0"]["nflExposure"]["core"]
    assert [b["team"] for b in core["buckets"]] == ["MIN"]
    assert core["unknownTeamIds"] == []


# ══ Hybrid slot eligibility survives the contract → pool join ══════


def test_a_hybrid_idp_keeps_every_slot_he_is_legally_eligible_for():
    """The defect ``src/roster_intel/roster_source.py`` was written to
    prevent, checked on the source this chain actually uses.

    ADR-007: Sleeper evaluates slot eligibility against
    ``fantasy_positions``, not ``position``. A pass-rushing linebacker
    ships as ``DL`` with ``["DL", "LB"]`` and is legal in either. LI-3
    measured the cost of losing that: hybrid IDPs locked out of half
    their legal slots, and 6 of 12 teams with a materially wrong
    starting lineup.

    ``roster_source`` exists because the ROS aggregate carries no
    ``fantasy_positions`` at all — a property of the source this lane
    moved OFF. The contract carries ``sleeper.fantasyPositions``, so the
    join keeps eligibility; measured on the live board, 660 of 660
    rostered players carry it and 43 are hybrids. This pins the
    behaviour rather than the count, so it holds whatever the board
    looks like on the day.
    """
    from src.api.data_contract import contract_roster_pools

    c = _contract(n_teams=1, depth=1)
    c["sleeper"]["teams"][0]["players"].append("o0_HYBRID")
    c["sleeper"]["positions"]["o0_HYBRID"] = "DL"
    c["sleeper"]["fantasyPositions"] = {"o0_HYBRID": ["DL", "LB"]}
    c["playersArray"].append(
        {
            "playerId": "id_hybrid",
            "canonicalName": "o0_HYBRID",
            "displayName": "o0_HYBRID",
            "position": "DL",
            "rankDerivedValue": 500.0,
        }
    )
    pools, _slots, _src = contract_roster_pools(c)
    hybrid = next(p for p in pools["o0"] if p.player_id == "o0_HYBRID")
    assert hybrid.position == "DL"
    assert set(hybrid.fantasy_positions) == {"DL", "LB"}

    # And the canonical solver actually seats him in the LB slot, which
    # is the whole point — carrying the field and ignoring it would look
    # identical in the payload.
    from src.ros.lineup import solve_optimal_assignment

    assigned = solve_optimal_assignment([hybrid], ["LB"])
    assert list(assigned.values()) == [hybrid]


def test_a_player_with_no_declared_eligibility_is_not_given_extra_slots():
    """Absent eligibility means "only his own position", never "every
    position" — the failure mode that would let a kicker start at LB."""
    from src.api.data_contract import contract_roster_pools
    from src.ros.lineup import solve_optimal_assignment

    c = _contract(n_teams=1, depth=1)
    pools, _slots, _src = contract_roster_pools(c)
    qb = next(p for p in pools["o0"] if p.position == "QB")
    assert qb.fantasy_positions == ()
    assert solve_optimal_assignment([qb], ["LB"]) == {}
