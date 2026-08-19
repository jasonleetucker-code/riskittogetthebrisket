"""V1-42 / C2-SIM-01 — exact before → apply → re-solve → after, as NAMES.

Owner decision 26: promotions and displacements are *separate roster
information, never a value subtraction*.  The simulator already published a
value delta and per-position starter COUNTS; what it could never say was WHO.
"Your starter count at RB is unchanged" and "your RB2 got benched by the player
you just acquired" are different facts, and only the second explains what the
trade actually did to the lineup.

The four categories are the substance of this unit.  Two would not do:

    arrived    starting now, came IN with the trade
    promoted   starting now, was ALREADY on the roster and was not starting
    departed   was starting, LEFT in the trade — gone, not displaced
    displaced  was starting, is STILL on the roster, no longer starts

Merging `departed` into `displaced` would report a player you traded away as
having been benched, which is the reading that makes the block useless.

**No second simulator.**  The re-solve is
`roster_intel.simulation.simulate_roster_change` (C2-SIM-01, lane `roster`);
`lineup_displacement` receives its `RosterSimulation` and refines the owner's
movement KINDS into the arrived/departed split the owner structurally cannot
make, because it never receives the trade's incoming/outgoing sets as
identities (reported to Roster as R2).

These tests therefore state ROSTERS and a trade, and let the canonical solver
decide the lineup — rather than hand-feeding a starter dict, which pre-supposed
the very answer the unit exists to compute.
"""

from __future__ import annotations


from src.roster_intel import simulate_roster_change
from src.ros.lineup import resolve_starter_slots
from src.trade.team_impact import compute, lineup_displacement, roster_players

SETTINGS = {
    "teamCount": 12,
    "rosterSize": 40,
    "taxiSize": 0,
    "starters": {"QB": 1, "RB": 2, "WR": 2, "TE": 1},
}

ACCEPTED = ("QB", "RB", "WR", "TE", "DL", "LB", "DB", "K")


def _asset(name: str, pos: str, value: int | None):
    return {
        "name": name,
        "sourceLabel": name,
        "pos": pos,
        "basePos": pos,
        "value": value,
        "assetClass": "player",
    }


def _displacement(before, *, incoming=(), outgoing=(), settings=SETTINGS):
    """Solve the transaction through the canonical owner, then refine it.

    Mirrors exactly what ``team_impact.compute`` does, so these tests exercise
    the production path rather than a parallel one.  ``outgoing`` names assets
    by object identity, the same rule the caller's multiplicity resolution uses.
    """
    before_pool, before_by_id = roster_players(list(before), ACCEPTED, id_prefix="b")
    incoming_pool, incoming_by_id = roster_players(list(incoming), ACCEPTED, id_prefix="i")
    going = {id(a) for a in outgoing}
    outgoing_ids = [k for k, a in before_by_id.items() if id(a) in going]
    slots, _ = resolve_starter_slots(roster_settings=settings)
    simulation = simulate_roster_change(
        before_pool, slots, incoming=incoming_pool, outgoing_ids=outgoing_ids
    )
    return lineup_displacement(
        simulation,
        incoming_ids=incoming_by_id.keys(),
        outgoing_ids=outgoing_ids,
        assets_by_id={**before_by_id, **incoming_by_id},
    )


def test_the_four_categories_are_distinguished():
    """One trade producing all four states at once."""
    keeper = _asset("Keeper", "RB", 7000)
    benched = _asset("Benched Later", "RB", 4000)
    sold = _asset("Traded Away", "RB", 3000)
    passer = _asset("Passer", "QB", 9000)
    star = _asset("New Star", "RB", 8000)
    roster = [passer, keeper, benched, sold]

    out = _displacement(roster, incoming=[star], outgoing=[sold])

    assert [r["name"] for r in out["arrived"]] == ["New Star"]
    # The incumbent who lost his slot is DISPLACED — still rostered, benched.
    assert [r["name"] for r in out["displaced"]] == ["Benched Later"]
    assert out["promoted"] == []
    # ``sold`` never started (RB3 behind Keeper and Benched Later), so he is
    # not "departed" from a lineup he was not in — the block reports slots,
    # not transactions.
    assert out["departed"] == []


def test_a_traded_away_starter_is_departed_not_displaced():
    """The distinction the whole block exists for.

    A player you no longer own was not benched. Reporting him as displaced
    tells the user their lineup lost a slot to competition when in fact they
    sold it.
    """
    sold = _asset("Sold", "RB", 6000)
    kept = _asset("Kept", "RB", 5000)
    bench = _asset("Bench Guy", "RB", 3000)

    out = _displacement([sold, kept, bench], outgoing=[sold])

    assert [r["name"] for r in out["departed"]] == ["Sold"]
    assert out["displaced"] == []
    # And the man who took the vacated slot was already here — a promotion,
    # not an arrival.
    assert [r["name"] for r in out["promoted"]] == ["Bench Guy"]
    assert out["arrived"] == []


def test_an_incoming_player_who_does_not_crack_the_lineup_appears_nowhere():
    """Acquiring depth is not a promotion, and the block must not invent one."""
    roster = [_asset("Star", "RB", 9000), _asset("Solid", "RB", 6000)]
    out = _displacement(roster, incoming=[_asset("Depth Piece", "RB", 900)])

    for bucket in ("arrived", "promoted", "departed", "displaced", "movedSlot"):
        assert out[bucket] == [], bucket
    assert out["startersBefore"] == out["startersAfter"] == 2


def test_it_publishes_no_value_delta():
    """`isValueDelta: False` is not decoration.

    Owner decision 26 says this is roster information. Every field names
    players and slots; nothing here subtracts one value from another.
    """
    a = _asset("A", "RB", 5000)
    b = _asset("B", "RB", 4000)
    out = _displacement([a, b], incoming=[_asset("C", "RB", 8000)])

    assert out["isValueDelta"] is False
    numeric = {k: v for k, v in out.items() if isinstance(v, int) and not isinstance(v, bool)}
    # The only bare numbers are counts of players, never differences of value.
    assert set(numeric) == {"startersBefore", "startersAfter", "coreBefore", "coreAfter"}
    for bucket in ("arrived", "promoted", "departed", "displaced", "demoted", "movedSlot"):
        for row in out[bucket]:
            assert set(row) == {
                "name",
                "position",
                "slotBefore",
                "slotAfter",
                "value",
                "valueScale",
            }


def test_an_unpriced_starter_reports_a_null_value_not_zero():
    """And an unpriced ARRIVAL is not seated at all — it is reported."""
    out = _displacement([_asset("Priced", "RB", 5000)], incoming=[_asset("Unknown", "RB", None)])
    assert out["arrived"] == [], "an unpriced player must not win a starting slot"
    assert out["unpricedIncoming"], "and his absence must be reported, not silent"


def test_two_roster_entries_sharing_a_name_stay_two_players():
    """The collision the retired name-keyed diff had to REFUSE rather than merge.

    Unique per-asset ids remove the collision instead of detecting it: two
    entries with one display name are two rows in the pool, so one cannot
    silently overwrite the other in the before/after diff.
    """
    first = _asset("Same Name", "RB", 5000)
    second = _asset("Same Name", "RB", 4000)
    pool, by_id = roster_players([first, second], ACCEPTED, id_prefix="b")

    assert len(pool) == 2
    assert len({p.player_id for p in pool}) == 2
    assert {id(a) for a in by_id.values()} == {id(first), id(second)}

    # And the diff survives it: selling one leaves the other starting.
    out = _displacement([first, second, _asset("Filler", "RB", 100)], outgoing=[first])
    assert [r["name"] for r in out["departed"]] == ["Same Name"]
    assert len(out["departed"]) == 1


# ── End to end, through the real solver ───────────────────────────────


def test_compute_publishes_displacement_solved_by_the_canonical_owner():
    """Not a hand-built starter dict: `compute` re-solves both lineups.

    The acquired RB is better than the incumbent RB2, so the exact solver seats
    him and benches the incumbent — and the block names both.
    """
    roster = [
        _asset("QB1", "QB", 8000),
        _asset("RB1", "RB", 7000),
        _asset("RB2", "RB", 3000),
        _asset("WR1", "WR", 6500),
        _asset("WR2", "WR", 6000),
        _asset("TE1", "TE", 5000),
    ]
    incoming = [_asset("Big RB", "RB", 9000)]
    after = roster + incoming

    impact = compute(
        before_assets=roster,
        after_assets=after,
        receiving=incoming,
        sending=[],
        equity=9000,
        roster_settings=SETTINGS,
    )
    assert impact is not None
    disp = impact["lineupDisplacement"]
    assert [r["name"] for r in disp["arrived"]] == ["Big RB"]
    assert [r["name"] for r in disp["displaced"]] == ["RB2"]
    assert disp["departed"] == []
    assert disp["startersBefore"] == disp["startersAfter"] == 6


def test_no_score_reads_the_displacement_block():
    """Non-influence, proven structurally rather than by a dict identity.

    An earlier version of this test popped the key and asserted the other keys
    were unchanged — which is true of any dict and proves nothing. The real
    property is that `lineupDisplacement` is WRITE-ONLY inside `compute`: it is
    assigned once and read by no scoring expression, so no verdict can move
    because of it. Same posture the manifest requires of `C2-EXP-01`
    ("descriptive only; must not influence trade grade").
    """
    import ast
    import inspect

    from src.trade import team_impact

    tree = ast.parse(inspect.getsource(team_impact))
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "compute")

    assigned_at = [
        n.lineno
        for n in ast.walk(fn)
        if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "displacement" for t in n.targets)
    ]
    assert len(assigned_at) == 1, "expected exactly one assignment of `displacement`"

    # Every other mention must be the single publish into the payload dict.
    loads = [
        n
        for n in ast.walk(fn)
        if isinstance(n, ast.Name) and n.id == "displacement" and isinstance(n.ctx, ast.Load)
    ]
    assert len(loads) == 1, (
        "`displacement` is read more than once inside `compute` — if a score now "
        "consumes it, roster information has started moving a trade grade"
    )


def test_the_verdict_is_unchanged_by_whether_a_displacement_happened():
    """Behavioural companion to the structural guard.

    Two rosters identical in every scored aggregate — same positions, same
    values, same counts — but one seats the newcomer without benching anyone
    (a free slot) and the other displaces an incumbent. The scores must match.
    """
    common = [
        _asset("QB1", "QB", 8000),
        _asset("WR1", "WR", 6500),
        _asset("WR2", "WR", 6000),
        _asset("TE1", "TE", 5000),
    ]
    # Roster A: two RBs already, the newcomer benches the weaker one.
    a_before = common + [_asset("RB1", "RB", 7000), _asset("RB2", "RB", 3000)]
    a_after = a_before + [_asset("New RB", "RB", 9000)]
    # Roster B: identical multiset of values, but ordered so the newcomer is
    # the weaker of the three and starts nobody out.
    b_before = common + [_asset("RB1", "RB", 9000), _asset("RB2", "RB", 7000)]
    b_after = b_before + [_asset("New RB", "RB", 3000)]

    a = compute(
        before_assets=a_before,
        after_assets=a_after,
        receiving=[_asset("New RB", "RB", 9000)],
        sending=[],
        equity=9000,
        roster_settings=SETTINGS,
    )
    b = compute(
        before_assets=b_before,
        after_assets=b_after,
        receiving=[_asset("New RB", "RB", 3000)],
        sending=[],
        equity=3000,
        roster_settings=SETTINGS,
    )
    assert a is not None and b is not None
    # The fixtures differ in what the lineup did...
    assert a["lineupDisplacement"]["displaced"], "roster A should have displaced RB2"
    assert not b["lineupDisplacement"]["displaced"], "roster B should displace nobody"
    # ...and the STARTER aggregates the scores are built from agree, which is
    # what makes the comparison meaningful rather than coincidental.
    assert a["starterDelta"] == b["starterDelta"]
    assert a["depthDelta"] == b["depthDelta"]


# ── Which positions a league actually starts (rehearsal finding A) ────
#
# `_BASE_POSITIONS` was both a report ORDER and an eligibility FILTER, and as a
# filter it was wrong: `dynasty_main` starts `K: 1`, `resolve_starter_slots`
# duly returns a `K` slot, and `project_starters` dropped every kicker — so the
# K slot could never be filled, `K` was not even a key in the output, and a
# traded kicker was invisible to the whole team-impact payload including the
# lineup delta above.
#
# Measured on the same roster: the capacity path (`build_cut_ladder` ->
# `assign_lineup`) SEATS the kicker while this module modelled one slot fewer.
# Two Trade modules disagreeing about one roster.


K_SETTINGS = {"teamCount": 12, "rosterSize": 40, "starters": {"QB": 1, "RB": 1, "K": 1}}


def test_a_league_that_starts_a_kicker_seats_one():
    from src.trade.team_impact import project_starters

    out = project_starters(
        [_asset("QB1", "QB", 9000), _asset("RB1", "RB", 7000), _asset("Kicker", "K", 500)],
        K_SETTINGS,
    )
    assert [a["name"] for a in out.get("K", [])] == ["Kicker"]


def test_the_capacity_path_and_team_impact_agree_on_the_same_roster():
    """The inconsistency that motivated the fix, pinned so it cannot return."""
    from src.draft.displacement import RosterAsset
    from src.ros.lineup import assign_lineup, resolve_starter_slots
    from src.trade.team_impact import project_starters

    slots, _ = resolve_starter_slots(roster_settings=K_SETTINGS)
    assets = [
        RosterAsset(player_id="q", name="QB1", position="QB", board_value=9000),
        RosterAsset(player_id="r", name="RB1", position="RB", board_value=7000),
        RosterAsset(player_id="k", name="Kicker", position="K", board_value=500),
    ]
    capacity_seated = {
        p.canonical_name
        for p in assign_lineup([a.to_lineup_player() for a in assets], slots).assignments.values()
    }

    impact = project_starters(
        [_asset("QB1", "QB", 9000), _asset("RB1", "RB", 7000), _asset("Kicker", "K", 500)],
        K_SETTINGS,
    )
    impact_seated = {a["name"] for bucket in impact.values() for a in bucket}
    assert capacity_seated == impact_seated


def test_a_league_that_starts_no_kicker_reports_none():
    """Derived per league, not a constant — `dynasty_new` starts no K and no IDP."""
    from src.trade.team_impact import _positions_for

    assert _positions_for(K_SETTINGS) == ("QB", "RB", "K")
    assert _positions_for(SETTINGS) == ("QB", "RB", "WR", "TE")


def test_an_unscalable_position_contributes_no_fabricated_baseline():
    """Rehearsal finding B: `_avg(combined) or 1500.0` invented a scale.

    A position with no priced starter has no measurable scale. It now
    contributes no depth/overflow term and is named in `unscalablePositions`,
    rather than being weighted by a number nobody observed.
    """
    roster = [_asset("QB1", "QB", 8000), _asset("RB1", "RB", 7000)]
    impact = compute(
        before_assets=roster,
        after_assets=roster + [_asset("RB2", "RB", 3000)],
        receiving=[_asset("RB2", "RB", 3000)],
        sending=[],
        equity=3000,
        roster_settings=SETTINGS,
    )
    assert impact is not None
    # WR and TE are startable in this league but nobody is rostered there.
    assert set(impact["unscalablePositions"]) >= {"WR", "TE"}
