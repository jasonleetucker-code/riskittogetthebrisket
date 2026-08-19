"""Canonical Meaningful Roster Core (C2-CORE-01).

Structured against the twelve acceptance criteria in §7 of
``docs/OWNER_FEATURE_ADDENDUM_2026-08-18_FLEX_STARTER_ASSIGNMENT.md``
(#899), each named so a failure says which criterion broke — plus the
pathological roster shapes the addendum does not enumerate but a real
league produces.

The fixtures are hand-computable on purpose.  Values are spaced far
enough apart that the intended ordering is obvious by reading, so a
failure is a statement about the ALGORITHM rather than about whether
two numbers happened to tie.
"""

from __future__ import annotations

import random

import pytest

from src.ros.lineup import RosterPlayer
from src.roster_intel.core import (
    build_meaningful_core,
    load_core_config,
    reserve_demand,
    reserve_slot_list,
)


def P(pid, pos, val, **kw):
    return RosterPlayer(
        player_id=pid,
        canonical_name=kw.pop("name", pid),
        position=pos,
        ros_value=val,
        **kw,
    )


#: The addendum's own §4 league.
_ADDENDUM_SLOTS = ["RB", "RB", "WR", "WR", "WR", "TE", "TE", "FLEX", "FLEX"]


def _addendum_pool():
    """§4's roster, with the ordering the example STATES.

    The two best remaining FLEX-eligible players after the dedicated
    slots must be RB3 then WR4 — so RB values are set to fall below WR4
    from RB5 down, making the example's outcome the only optimal one
    rather than an accident of spacing.
    """
    return [
        P("RB1", "RB", 900),
        P("RB2", "RB", 880),
        P("RB3", "RB", 700),  # best remaining → FLEX1
        P("RB4", "RB", 400),
        P("RB5", "RB", 300),
        P("WR1", "WR", 890),
        P("WR2", "WR", 870),
        P("WR3", "WR", 850),
        P("WR4", "WR", 690),  # second best remaining → FLEX2
        P("WR5", "WR", 380),
        P("WR6", "WR", 350),
        P("TE1", "TE", 860),
        P("TE2", "TE", 840),
        P("TE3", "TE", 200),
    ]


def _slots(core, pid):
    return next((m.slot, m.role) for m in core.members if m.player_id == pid)


# ══ §7.1 — FLEX starters are assigned before reserve selection ══════


def test_ac1_flex_starters_assigned_before_reserves():
    core = build_meaningful_core(_addendum_pool(), _ADDENDUM_SLOTS)
    assert _slots(core, "RB3") == ("FLEX", "starter")
    assert _slots(core, "WR4") == ("FLEX", "starter")


# ══ §7.2 — a FLEX-assigned player is not also native depth ═════════


def test_ac2_flex_starter_cannot_also_be_positional_depth():
    core = build_meaningful_core(_addendum_pool(), _ADDENDUM_SLOTS)
    for pid in ("RB3", "WR4"):
        roles = [m.role for m in core.members if m.player_id == pid]
        assert roles == ["starter"], f"{pid} appears {len(roles)}×: {roles}"


# ══ §7.3 — consuming RB3 at FLEX shifts the RB reserve pool ════════


def test_ac3_rb3_at_flex_makes_rb4_the_first_rb_reserve():
    """THE defect this addendum exists to prevent.

    A per-position list would offer RB3 as the first RB reserve while
    the lineup was already starting him.

    Asserted on reserve MEMBERSHIP, not on which slot label a member
    carries.  The reserve pass is a maximum-weight assignment, and with
    RB demand 1 + FLEX demand 1 both filled by running backs the two
    labellings (RB4→RB / RB5→FLEX and RB4→FLEX / RB5→RB) are equally
    optimal — `_canonicalize_slots` arbitrates deterministically, but
    the choice carries no meaning.  Nothing downstream reads it:
    `by_position` groups on NATIVE position precisely so a slot label
    cannot move a player between rooms.
    """
    core = build_meaningful_core(_addendum_pool(), _ADDENDUM_SLOTS)
    reserves = {m.player_id for m in core.reserves}
    assert "RB3" not in reserves, "RB3 starts at FLEX; he cannot also be depth"
    assert "RB4" in reserves, "the RB reserve pool must reach past the FLEX-consumed RB3"
    # The full reserve set: RB demand 1 + FLEX demand 1 both land on RBs
    # (RB4 = 400 and RB5 = 300 against WR5 = 380, once WR5/WR6 have taken
    # the two WR reserve slots), WR demand 2, TE demand 1.
    assert reserves == {"RB4", "RB5", "WR5", "WR6", "TE3"}


# ══ §7.4 — the same for WR ═════════════════════════════════════════


def test_ac4_wr4_at_flex_shifts_the_wr_reserve_pool():
    core = build_meaningful_core(_addendum_pool(), _ADDENDUM_SLOTS)
    # WR demand: ceil(1.5 × 3) − 3 = 2, drawn from WR5 down.
    wr_reserves = [m.player_id for m in core.reserves if m.slot == "WR"]
    assert wr_reserves == ["WR5", "WR6"]


# ══ §7.5 — 0 / 1 / 2 / 3+ FLEX all derive from league settings ═════


@pytest.mark.parametrize("n_flex", [0, 1, 2, 3, 4])
def test_ac5_flex_count_comes_from_config_not_a_constant(n_flex):
    slots = ["RB", "RB", "WR", "WR", "WR", "TE"] + ["FLEX"] * n_flex
    core = build_meaningful_core(_addendum_pool(), slots)
    seated_flex = [m for m in core.starters if m.slot == "FLEX"]
    assert len(seated_flex) == n_flex
    # ceil(1.5n) − n: 0→0, 1→1, 2→1, 3→2, 4→2.
    assert core.demand.by_slot.get("FLEX", 0) == ({0: 0, 1: 1, 2: 1, 3: 2, 4: 2}[n_flex])


# ══ §7.6 — Superflex does not double-count ═════════════════════════


def test_ac6_superflex_folds_into_qb_demand_once():
    """#839: 1 QB + 1 SF ⇒ 2 QB-demand starters ⇒ 3 meaningful QBs.

    The owner's own worked example, so it is pinned as arithmetic:
    basis 2, reserve demand ceil(1.5×2) − 2 = 1.
    """
    d = reserve_demand(["QB", "SUPER_FLEX", "RB", "RB", "WR", "WR", "WR", "TE"])
    assert d.starter_basis["QB"] == 2
    assert d.by_slot["QB"] == 1
    # SF must NOT also generate a reserve group of its own — that would
    # be the double count criterion 6 forbids.
    assert "SUPER_FLEX" not in d.by_slot


def test_ac6_superflex_starter_is_not_also_a_qb_reserve():
    pool = [P(f"QB{i}", "QB", 950 - i * 50) for i in range(1, 5)]
    pool += [P(f"WR{i}", "WR", 500 - i * 10) for i in range(1, 6)]
    pool += [P(f"RB{i}", "RB", 480 - i * 10) for i in range(1, 5)]
    core = build_meaningful_core(pool, ["QB", "SUPER_FLEX", "RB", "WR", "WR"])
    qbs = [(m.player_id, m.slot, m.role) for m in core.members if m.position == "QB"]
    assert [q[0] for q in qbs] == ["QB1", "QB2", "QB3"]  # exactly 3 meaningful QBs
    assert sorted(q[1] for q in qbs) == ["QB", "QB", "SUPER_FLEX"]
    assert [m.player_id for m in core.members].count("QB2") == 1


# ══ §7.7 — IDP FLEX follows the same architecture ══════════════════


def test_ac7_idp_flex_assigns_before_idp_reserves():
    pool = [P(f"LB{i}", "LB", 800 - i * 40) for i in range(1, 6)]
    pool += [P(f"DL{i}", "DL", 780 - i * 40) for i in range(1, 6)]
    pool += [P(f"DB{i}", "DB", 500 - i * 40) for i in range(1, 6)]
    core = build_meaningful_core(pool, ["LB", "LB", "DL", "DL", "DB", "IDP_FLEX"])
    flex = [m for m in core.starters if m.slot == "IDP_FLEX"]
    assert len(flex) == 1
    # The IDP_FLEX seat went to the best remaining defender, and that
    # player is not also in his own position's reserve list.
    seated = flex[0].player_id
    assert [m.player_id for m in core.members].count(seated) == 1
    assert core.demand.by_slot["IDP_FLEX"] == 1


# ══ §7.8 — every meaningful-roster player is unique ════════════════


def test_ac8_every_core_member_is_unique():
    core = build_meaningful_core(_addendum_pool(), _ADDENDUM_SLOTS)
    ids = [m.player_id for m in core.members]
    assert len(ids) == len(set(ids))
    assert len(core.core_ids) == len(ids)


# ══ §7.9 — deterministic / permutation-invariant ═══════════════════


def test_ac9_selection_is_permutation_invariant():
    """A roster is a SET.  If shuffling the input changes the core, the
    core is an artifact of iteration order, not of the roster."""
    baseline = build_meaningful_core(_addendum_pool(), _ADDENDUM_SLOTS)
    expected = sorted((m.player_id, m.slot, m.role) for m in baseline.members)
    rng = random.Random(20260818)
    for _ in range(25):
        shuffled = _addendum_pool()
        rng.shuffle(shuffled)
        got = build_meaningful_core(shuffled, _ADDENDUM_SLOTS)
        assert sorted((m.player_id, m.slot, m.role) for m in got.members) == expected


# ══ §7.10 — unpriced stays explicit, never coerced to zero ═════════


def test_ac10_unpriced_players_are_reported_not_zeroed():
    pool = _addendum_pool() + [
        P("GHOST1", "RB", None),
        P("GHOST2", "WR", None),
    ]
    core = build_meaningful_core(pool, _ADDENDUM_SLOTS)
    assert core.unpriced_ids == frozenset({"GHOST1", "GHOST2"})
    # Third state: in neither starters nor reserves.
    assert "GHOST1" not in core.core_ids
    assert "GHOST2" not in core.core_ids
    # And they did not displace anyone — the priced core is unchanged.
    assert core.core_ids == build_meaningful_core(_addendum_pool(), _ADDENDUM_SLOTS).core_ids


def test_ac10_an_unpriced_player_never_wins_a_slot_from_a_priced_one():
    """The failure mode `or 0.0` produced: an unknown reads as a real
    0.0, which is assignable.  Here the only alternative to GHOST is a
    genuinely worthless player, and the worthless one must still start."""
    pool = [P("REAL", "RB", 0.0), P("GHOST", "RB", None)]
    core = build_meaningful_core(pool, ["RB"])
    assert [m.player_id for m in core.starters] == ["REAL"]
    assert core.unpriced_ids == frozenset({"GHOST"})


def test_ac10_a_short_roster_reports_unfilled_slots_rather_than_padding():
    core = build_meaningful_core([P("RB1", "RB", 900)], _ADDENDUM_SLOTS)
    assert len(core.starters) == 1
    assert sorted(core.unfilled_starter_slots) == [
        "FLEX",
        "FLEX",
        "RB",
        "TE",
        "TE",
        "WR",
        "WR",
        "WR",
    ]
    assert core.unfilled_reserve_slots  # demand exists; nobody to meet it


# ══ §7.11 — FLEX participation affects the core population ═════════


def test_ac11_flex_changes_the_meaningful_population():
    pool = _addendum_pool()
    without = build_meaningful_core(pool, [s for s in _ADDENDUM_SLOTS if s != "FLEX"])
    with_flex = build_meaningful_core(pool, _ADDENDUM_SLOTS)
    assert with_flex.core_ids != without.core_ids
    assert len(with_flex.core_ids) > len(without.core_ids)


# ══ §7.12 — FLEX is not a separate Team Strength position ══════════


def test_ac12_flex_starters_group_under_their_native_position():
    core = build_meaningful_core(_addendum_pool(), _ADDENDUM_SLOTS)
    groups = core.by_position()
    assert "FLEX" not in groups
    assert "RB3" in [m.player_id for m in groups["RB"]]  # FLEX-seated RB
    assert "WR4" in [m.player_id for m in groups["WR"]]


# ══ Refusal semantics ══════════════════════════════════════════════


def test_no_starter_slots_is_a_refusal_not_an_empty_lineup():
    """`resolve_starter_slots` returns [] as a REFUSAL.  Treating it as
    "this league starts nobody" is the missing-is-zero error one layer
    up, and it is what silently undercounted an IDP league by twelve
    slots before C2-U1."""
    core = build_meaningful_core(_addendum_pool(), [])
    assert core.available is False
    assert core.unavailable_reason == "no_starter_slots"
    assert core.members == ()


def test_empty_roster_is_available_but_empty():
    """Distinct from a refusal: we know the lineup, there is nobody in
    it.  Both produce zero members, and they must not read the same."""
    core = build_meaningful_core([], _ADDENDUM_SLOTS)
    assert core.available is True
    assert core.members == ()
    assert len(core.unfilled_starter_slots) == len(_ADDENDUM_SLOTS)


# ══ Pathological rosters ═══════════════════════════════════════════


def test_oversized_roster_selects_only_the_meaningful_core():
    """A 58-man roster must not put 58 players in the core — that is the
    raw-sum failure (W20-F003) the core exists to replace."""
    pool = [P(f"WR{i}", "WR", 1000 - i) for i in range(1, 40)]
    pool += [P(f"RB{i}", "RB", 960 - i) for i in range(1, 20)]
    pool += [P(f"TE{i}", "TE", 500 - i) for i in range(1, 12)]
    assert len(pool) == 69  # deeper than any real roster
    core = build_meaningful_core(pool, _ADDENDUM_SLOTS)
    # Every slot fillable ⇒ core size is exactly demand, not roster size.
    assert len(core.members) == len(_ADDENDUM_SLOTS) + core.demand.total() == 14
    assert not core.unfilled_starter_slots and not core.unfilled_reserve_slots


def test_all_unpriced_roster_yields_an_empty_core_and_says_why():
    pool = [P(f"X{i}", "WR", None) for i in range(6)]
    core = build_meaningful_core(pool, _ADDENDUM_SLOTS)
    assert core.members == ()
    assert len(core.unpriced_ids) == 6
    assert core.available is True  # we could ask; the roster is unpriceable


def test_duplicate_roster_ids_are_reported_and_seated_once():
    dup = P("RB1", "RB", 900)
    core = build_meaningful_core([dup, dup, P("RB2", "RB", 880)], ["RB", "RB"])
    assert core.duplicate_ids == frozenset({"RB1"})
    assert sorted(m.player_id for m in core.starters) == ["RB1", "RB2"]


def test_multi_position_eligibility_is_honoured_in_both_passes():
    """A DL/LB hybrid is legal in either room.  Sleeper evaluates
    eligibility on `fantasy_positions`, and both solves must too —
    otherwise the reserve pass benches a player the starter pass would
    have allowed."""
    hybrid = P("HYB", "DL", 500, fantasy_positions=("DL", "LB"))
    pool = [P("DL1", "DL", 900), P("LB1", "LB", 890), hybrid]
    core = build_meaningful_core(pool, ["DL", "LB"])
    assert core.demand.by_slot == {"DL": 1, "LB": 1}
    # HYB is seated as a reserve in exactly one of the two rooms.
    hyb = [m for m in core.members if m.player_id == "HYB"]
    assert len(hyb) == 1
    assert hyb[0].role == "reserve"
    assert hyb[0].slot in {"DL", "LB"}


def test_kickers_start_but_generate_no_reserve_demand():
    """A backup kicker is not portfolio value.  Counting one would put a
    K into the population Team Strength sums."""
    d = reserve_demand(["QB", "RB", "RB", "WR", "WR", "WR", "TE", "K"])
    assert "K" not in d.by_slot
    assert "K" not in d.starter_basis


def test_configured_flex_eligibility_reaches_both_solves():
    """A league can CONFIGURE what its flex accepts.  If the override
    only reached the starter pass, the reserve pass would apply the
    declared table and admit an illegal player."""
    pool = [P("RB1", "RB", 900), P("RB2", "RB", 880), P("TE1", "TE", 870), P("TE2", "TE", 500)]
    # This league's FLEX excludes TE.
    core = build_meaningful_core(pool, ["FLEX", "FLEX"], slot_eligibility={"FLEX": ["RB", "WR"]})
    seated = {m.player_id for m in core.members}
    assert "TE1" not in seated and "TE2" not in seated
    assert seated == {"RB1", "RB2"}


# ══ Demand arithmetic ══════════════════════════════════════════════


def test_reserve_demand_matches_the_addendum_worked_example():
    d = reserve_demand(_ADDENDUM_SLOTS)
    assert d.by_slot == {"RB": 1, "WR": 2, "TE": 1, "FLEX": 1}


def test_multiplier_ships_labelled_as_a_prior():
    """The multiplier is a V1 champion under validation, not frozen
    methodology.  An unlabelled constant is how a prior silently becomes
    canonical."""
    d = reserve_demand(_ADDENDUM_SLOTS)
    assert d.multiplier == 1.5
    assert d.multiplier_status == "PRIOR"
    assert d.multiplier_provenance == "owner_addendum_839_amended_899"
    assert load_core_config()["reserveMultiplierStatus"] == "PRIOR"


def test_reserve_slot_list_is_deterministic():
    d = reserve_demand(_ADDENDUM_SLOTS)
    assert reserve_slot_list(d) == reserve_slot_list(d)
    assert sorted(reserve_slot_list(d)) == reserve_slot_list(d)


def test_slot_aliases_are_resolved_before_counting():
    """`SFLEX` is the registry's spelling; `SUPER_FLEX` is canonical.
    Counting them as two different slots would give a superflex league
    two separate demands."""
    assert reserve_demand(["QB", "SFLEX"]).starter_basis["QB"] == 2
    assert reserve_demand(["QB", "SUPERFLEX"]).starter_basis["QB"] == 2


# ══ Both live leagues ══════════════════════════════════════════════


def test_live_league_dynasty_main_shape():
    """QB1 RB2 WR3 TE2 FLEX2 SFLEX1 K1 DL3 LB3 DB3 — the real registry
    lineup.  Hand-checked: QB basis 2 (SF folded) → 1; RB 2 → 1;
    WR 3 → 2; TE 2 → 1; FLEX 2 → 1; DL/LB/DB 3 → 2 each."""
    slots = (
        ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "TE", "FLEX", "FLEX", "SFLEX", "K"]
        + ["DL"] * 3
        + ["LB"] * 3
        + ["DB"] * 3
    )
    d = reserve_demand(slots)
    assert d.by_slot == {
        "QB": 1,
        "RB": 1,
        "WR": 2,
        "TE": 1,
        "FLEX": 1,
        "DL": 2,
        "LB": 2,
        "DB": 2,
    }
    assert d.total() == 12


def test_live_league_dynasty_new_has_no_idp_demand():
    """QB1 RB2 WR3 TE1 FLEX2 SFLEX1, 10 teams, IDP off.  No defensive
    demand may appear from a constant."""
    d = reserve_demand(["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "FLEX", "SFLEX"])
    assert d.by_slot == {"QB": 1, "RB": 1, "WR": 2, "TE": 1, "FLEX": 1}
    assert not {"DL", "LB", "DB", "IDP_FLEX"} & set(d.by_slot)


def test_core_member_position_is_always_a_family_token():
    """`CoreMember.position` goes through `lineup_position`, so DE/DT/
    EDGE arrive as DL and CB/S/FS/SS as DB.

    Load-bearing: `strength` and `age_portfolio` group on this field
    with no re-normalisation and no group-merge step. If a raw position
    ever reached them, DE and DT would land in two groups that both
    claim to be the DL room.
    """
    pool = [
        P("E1", "DE", 700),
        P("T1", "DT", 650),
        P("X1", "EDGE", 600),
        P("C1", "CB", 500),
        P("S1", "FS", 450),
    ]
    core = build_meaningful_core(pool, ["DL", "DL", "DL", "DB", "DB"])
    assert {m.position for m in core.members} == {"DL", "DB"}
    assert set(core.by_position()) == {"DL", "DB"}
    assert len(core.by_position()["DL"]) == 3
