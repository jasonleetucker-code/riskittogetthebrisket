"""Canonical Team Weakness / Need Priority (row 1.2).

The binding constraint is ``MASTER_PRODUCT_PLAN.md`` §4.1: *"Need
Priority must agree with the canonical lineup/assignment solve. An
`urgentNeed` flag that contradicts the actual roster solve is a defect,
not an alternate opinion."*  Most of this file is that invariant,
approached from several directions.
"""

from __future__ import annotations

import pytest

from src.ros.lineup import RosterPlayer
from src.roster_intel.core import build_meaningful_core
from src.roster_intel.weakness import (
    build_position_ranks,
    build_team_weakness,
)


def P(pid, pos, val, **kw):
    return RosterPlayer(player_id=pid, canonical_name=pid, position=pos, ros_value=val, **kw)


#: dynasty_main's offensive shape: QB 1 + SFLEX 1, RB 2, WR 3, TE 2, FLEX 2.
_SLOTS = ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "TE", "FLEX", "FLEX", "SUPER_FLEX"]


def _filler(per_pos=60):
    """A league-wide ranking population our team sits inside."""
    out = []
    for pos in ("QB", "RB", "WR", "TE", "DL", "LB", "DB"):
        for i in range(per_pos):
            out.append((f"{pos}_f{i}", pos, 8800 - i * 100))
    return out


def _ranks(mine, *, population="league_rostered"):
    rows = [(p.player_id, p.position, p.ros_value) for p in mine] + _filler()
    return build_position_ranks(rows, population=population)


def _weakness(mine, slots=None, team_count=12):
    core = build_meaningful_core(mine, slots or _SLOTS)
    return build_team_weakness(core, _ranks(mine), team_count=team_count)


def _strong_roster():
    """Every rung comfortably met."""
    return [
        P("QBa", "QB", 9000),
        P("QBb", "QB", 8900),
        P("RBa", "RB", 8850),
        P("RBb", "RB", 8840),
        P("WRa", "WR", 8830),
        P("WRb", "WR", 8820),
        P("WRc", "WR", 8810),
        P("TEa", "TE", 8805),
        P("TEb", "TE", 8802),
    ]


# ══ Thresholds are one rule, not a table ═══════════════════════════


def test_owner_thresholds_are_reproduced_at_twelve_teams():
    """QB1 12 / QB2 24, RB1 12 / RB2 24, WR1 12 / WR2 24 / WR3 36,
    TE1 12 / TE2 24 — the owner's listed numbers, derived rather than
    hard-coded."""
    w = _weakness(_strong_roster(), team_count=12)
    got = {p: [r.threshold_rank for r in n.rungs] for p, n in w.by_position.items()}
    assert got == {"QB": [12, 24], "RB": [12, 24], "WR": [12, 24, 36], "TE": [12, 24]}


def test_thresholds_scale_with_league_size():
    """A hard-coded top-12 is wrong in the 10-team league. `k × teamCount`
    is what the rule always meant."""
    w = _weakness(_strong_roster(), team_count=10)
    assert [r.threshold_rank for r in w.by_position["WR"].rungs] == [10, 20, 30]


def test_an_unknown_team_count_is_a_refusal():
    """Every threshold would collapse to rank 0 and the whole roster
    would read as critically weak."""
    core = build_meaningful_core(_strong_roster(), _SLOTS)
    w = build_team_weakness(core, _ranks(_strong_roster()), team_count=0)
    assert w.available is False
    assert w.unavailable_reason == "unknown_team_count"
    assert w.by_position == {}


# ══ Superflex is one QB demand, not two ════════════════════════════


def test_superflex_produces_two_qb_rungs_not_three():
    w = _weakness(_strong_roster())
    assert [r.rung for r in w.by_position["QB"].rungs] == [1, 2]


def test_removing_superflex_drops_qb_to_one_rung():
    """Proves the second QB rung comes from the SF slot rather than from
    a constant."""
    slots = [s for s in _SLOTS if s != "SUPER_FLEX"]
    w = _weakness(_strong_roster(), slots)
    assert [r.rung for r in w.by_position["QB"].rungs] == [1]


# ══ FLEX gets no rung ladder ═══════════════════════════════════════


def test_flex_is_not_a_need_category():
    w = _weakness(_strong_roster())
    assert "FLEX" not in w.by_position
    assert "SUPER_FLEX" not in w.by_position
    assert set(w.by_position) == {"QB", "RB", "WR", "TE"}


def test_a_flex_seated_player_is_judged_once_on_his_own_ladder():
    """RB3 starting at FLEX is still a running back. He must not create
    a FLEX need AND an RB need for the same body."""
    mine = _strong_roster() + [P("RBc", "RB", 8700)]
    core = build_meaningful_core(mine, _SLOTS)
    assert any(m.player_id == "RBc" and m.slot == "FLEX" for m in core.starters)
    w = build_team_weakness(core, _ranks(mine), team_count=12)
    holders = [r.player_id for n in w.by_position.values() for r in n.rungs]
    assert holders.count("RBc") <= 1


# ══ It agrees with the solve ═══════════════════════════════════════


def test_no_position_is_urgent_when_the_solve_filled_it_well():
    """The §4.1 invariant, stated directly."""
    w = _weakness(_strong_roster())
    assert w.urgent_positions == ()
    assert all(n.level == "none" for n in w.by_position.values())


def test_a_position_the_solve_could_not_fill_is_critical():
    roster = [p for p in _strong_roster() if not p.player_id.startswith("TE")]
    w = _weakness(roster)
    assert w.by_position["TE"].level == "critical"
    assert w.by_position["TE"].unfilled_rungs == 2
    assert "TE" in w.urgent_positions


def test_rung_holders_are_the_teams_own_best_at_that_position():
    """Rungs are filled best-first, so rung k is always the k-th best —
    which is what makes the ladder agree with the assignment."""
    mine = [
        P("QBa", "QB", 9000),
        P("QBb", "QB", 100),
        P("RBa", "RB", 8850),
        P("RBb", "RB", 8840),
        P("WRa", "WR", 8830),
        P("WRb", "WR", 8820),
        P("WRc", "WR", 8810),
        P("TEa", "TE", 8805),
        P("TEb", "TE", 8802),
    ]
    w = _weakness(mine)
    qb = w.by_position["QB"]
    assert [r.player_id for r in qb.rungs] == ["QBa", "QBb"]
    assert qb.rungs[0].status == "met"
    assert qb.rungs[1].status == "unmet"


# ══ Missing is never weak ══════════════════════════════════════════


def test_an_unranked_holder_is_unknown_not_a_need():
    """A player we cannot rank is not a player who ranks badly. Scoring
    him would manufacture a trade target out of a join miss."""
    mine = _strong_roster()
    core = build_meaningful_core(mine, _SLOTS)
    # Rank population that simply does not contain our tight ends.
    partial = build_position_ranks(
        [(p.player_id, p.position, p.ros_value) for p in mine if p.position != "TE"] + _filler(),
        population="partial",
    )
    w = build_team_weakness(core, partial, team_count=12)
    te = w.by_position["TE"]
    assert te.unknown_rungs == 2
    assert te.unmet_rungs == 0
    assert te.priority == 0.0
    assert te.level == "none"
    assert "NOT measured" in te.reasons[0]


def test_unpriced_players_are_excluded_from_ranks_not_ranked_last():
    """Ranking an unpriced player last would make him look like the
    worst QB alive, and a rung holding him would read as critical."""
    rows = [("GHOST", "QB", None), ("REAL", "QB", 500)]
    ranks = build_position_ranks(rows, population="test")
    assert ranks.rank_of("GHOST") is None
    assert ranks.rank_of("REAL") == 1


def test_unfilled_and_unknown_are_distinct_states():
    """Nobody is there vs. somebody is there and we cannot rank them."""
    mine = [p for p in _strong_roster() if p.player_id != "TEb"]
    core = build_meaningful_core(mine, _SLOTS)
    partial = build_position_ranks(
        [(p.player_id, p.position, p.ros_value) for p in mine if p.player_id != "TEa"] + _filler(),
        population="partial",
    )
    te = build_team_weakness(core, partial, team_count=12).by_position["TE"]
    assert [r.status for r in te.rungs] == ["unknown", "unfilled"]


def test_a_refused_core_propagates_refusal():
    core = build_meaningful_core(_strong_roster(), [])
    w = build_team_weakness(core, _ranks(_strong_roster()), team_count=12)
    assert w.available is False
    assert w.unavailable_reason == "no_starter_slots"


# ══ Severity ═══════════════════════════════════════════════════════


@pytest.mark.parametrize(
    "qb2_value,expected",
    [
        # Filler QBs run 8800 down to 2900 in steps of 100, so rank r
        # holds value 8800 − (r−1)·100.  The QB2 bar is top 24.
        (8790, "none"),  # rank 2
        (5850, "moderate"),  # rank 31 → shortfall 7, ratio 0.29
        (100, "high"),  # below every filler → rank 61, ratio 1.54
    ],
)
def test_severity_escalates_with_the_shortfall(qb2_value, expected):
    mine = [p for p in _strong_roster() if p.player_id != "QBb"]
    mine.append(P("QBb", "QB", qb2_value))
    assert _weakness(mine).by_position["QB"].level == expected


def test_a_position_takes_the_level_of_its_worst_rung():
    """Averaging would let an elite QB1 hide a missing QB2 — and the
    missing QB2 is the whole reason to look."""
    mine = [p for p in _strong_roster() if p.player_id != "QBb"]
    mine.append(P("QBb", "QB", 1))
    qb = _weakness(mine).by_position["QB"]
    assert qb.rungs[0].status == "met"
    assert qb.level == "high"


def test_two_failing_rungs_outrank_one_at_the_same_severity():
    one = [p for p in _strong_roster() if p.player_id != "WRc"] + [P("WRc", "WR", 1)]
    two = [p for p in _strong_roster() if p.player_id not in ("WRb", "WRc")] + [
        P("WRb", "WR", 2),
        P("WRc", "WR", 1),
    ]
    assert _weakness(two).by_position["WR"].priority > _weakness(one).by_position["WR"].priority


def test_shortfall_is_none_unless_the_rung_is_genuinely_unmet():
    """Reporting 0 on an unfilled rung would read as "just missed"."""
    roster = [p for p in _strong_roster() if not p.player_id.startswith("TE")]
    for rung in _weakness(roster).by_position["TE"].rungs:
        assert rung.status == "unfilled"
        assert rung.shortfall is None


# ══ Output contract ════════════════════════════════════════════════


def test_needs_are_ordered_worst_first_and_deterministically():
    mine = [p for p in _strong_roster() if not p.player_id.startswith("TE")]
    mine += [P("RBc", "RB", 1)]
    w = _weakness(mine)
    ordered = [n.position for n in w.ordered_needs]
    assert ordered[0] == "TE"  # critical outranks everything
    assert ordered == [n.position for n in _weakness(mine).ordered_needs]


def test_rank_population_is_stamped_on_the_output():
    """ "Top 12 QB" is only meaningful once you say top 12 of what."""
    core = build_meaningful_core(_strong_roster(), _SLOTS)
    ranks = _ranks(_strong_roster(), population="board_all_priced")
    w = build_team_weakness(core, ranks, team_count=12)
    assert w.to_dict()["rankPopulation"] == "board_all_priced"


def test_threshold_rule_and_status_are_published():
    """The rule ships labelled: an unlabelled constant is how a prior
    silently becomes canonical."""
    d = _weakness(_strong_roster()).to_dict()
    assert d["thresholdRule"] == "rung_index_times_team_count"
    assert d["thresholdStatus"] == "PRIOR"


def test_idp_rungs_derive_from_required_slots_times_league_size():
    """The owner states the IDP rule explicitly; it is the same rule."""
    mine = [P(f"LB{i}", "LB", 8800 - i) for i in range(1, 4)]
    w = _weakness(mine, ["LB", "LB", "LB"], team_count=12)
    assert [r.threshold_rank for r in w.by_position["LB"].rungs] == [12, 24, 36]
