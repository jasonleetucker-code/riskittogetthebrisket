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

No second lineup engine: both states are solved by the canonical assignment
owner (`src/ros/lineup.py`, C2-U1) inside `_aggregate_state`, and
`lineup_displacement` reads those two solutions.
"""

from __future__ import annotations

import pytest

from src.trade.team_impact import compute, lineup_displacement

SETTINGS = {
    "teamCount": 12,
    "rosterSize": 40,
    "taxiSize": 0,
    "starters": {"QB": 1, "RB": 2, "WR": 2, "TE": 1},
}


def _asset(name: str, pos: str, value: int | None):
    return {
        "name": name,
        "sourceLabel": name,
        "pos": pos,
        "basePos": pos,
        "value": value,
        "assetClass": "player",
    }


def _starters(**by_position):
    return {pos: list(assets) for pos, assets in by_position.items()}


def test_the_four_categories_are_distinguished():
    before = _starters(
        QB=[_asset("Passer", "QB", 9000)],
        RB=[_asset("Keeper", "RB", 7000), _asset("Benched Later", "RB", 4000)],
    )
    after = _starters(
        QB=[_asset("Passer", "QB", 9000)],
        RB=[_asset("Keeper", "RB", 7000), _asset("New Star", "RB", 8000)],
    )
    out = lineup_displacement(
        before,
        after,
        incoming=[_asset("New Star", "RB", 8000)],
        outgoing=[_asset("Traded Away", "RB", 3000)],
    )
    assert [r["name"] for r in out["arrived"]] == ["New Star"]
    assert out["promoted"] == []
    assert out["departed"] == []
    # The player who lost his slot is DISPLACED — still rostered, benched.
    assert [r["name"] for r in out["displaced"]] == ["Benched Later"]


def test_a_traded_away_starter_is_departed_not_displaced():
    """The distinction the whole block exists for.

    A player you no longer own was not benched. Reporting him as displaced
    tells the user their lineup lost a slot to competition when in fact they
    sold it.
    """
    before = _starters(RB=[_asset("Sold", "RB", 6000), _asset("Kept", "RB", 5000)])
    after = _starters(RB=[_asset("Kept", "RB", 5000), _asset("Bench Guy", "RB", 3000)])

    out = lineup_displacement(before, after, incoming=[], outgoing=[_asset("Sold", "RB", 6000)])
    assert [r["name"] for r in out["departed"]] == ["Sold"]
    assert out["displaced"] == []
    # And the man who took the vacated slot was already here — a promotion,
    # not an arrival.
    assert [r["name"] for r in out["promoted"]] == ["Bench Guy"]
    assert out["arrived"] == []


def test_an_incoming_player_who_does_not_crack_the_lineup_appears_nowhere():
    """Acquiring depth is not a promotion, and the block must not invent one."""
    before = _starters(RB=[_asset("Star", "RB", 9000), _asset("Solid", "RB", 6000)])
    after = _starters(RB=[_asset("Star", "RB", 9000), _asset("Solid", "RB", 6000)])

    out = lineup_displacement(
        before, after, incoming=[_asset("Depth Piece", "RB", 900)], outgoing=[]
    )
    assert out == {
        "arrived": [],
        "promoted": [],
        "departed": [],
        "displaced": [],
        "startersBefore": 2,
        "startersAfter": 2,
        "isValueDelta": False,
    }


def test_it_publishes_no_value_delta():
    """`isValueDelta: False` is not decoration.

    Owner decision 26 says this is roster information. Every field names
    players and slots; nothing here subtracts one value from another.
    """
    before = _starters(RB=[_asset("A", "RB", 5000), _asset("B", "RB", 4000)])
    after = _starters(RB=[_asset("A", "RB", 5000), _asset("C", "RB", 8000)])
    out = lineup_displacement(before, after, incoming=[_asset("C", "RB", 8000)], outgoing=[])

    assert out["isValueDelta"] is False
    numeric = {k: v for k, v in out.items() if isinstance(v, int) and not isinstance(v, bool)}
    # The only bare numbers are counts of starters, not differences of value.
    assert set(numeric) == {"startersBefore", "startersAfter"}
    for bucket in ("arrived", "promoted", "departed", "displaced"):
        for row in out[bucket]:
            assert set(row) == {"name", "position", "value", "valueScale"}


def test_an_unpriced_starter_reports_a_null_value_not_zero():
    before = _starters(RB=[_asset("Priced", "RB", 5000)])
    after = _starters(RB=[_asset("Priced", "RB", 5000), _asset("Unknown", "RB", None)])
    out = lineup_displacement(before, after, incoming=[_asset("Unknown", "RB", None)], outgoing=[])
    assert out["arrived"][0]["value"] is None


def test_colliding_starter_identities_refuse_rather_than_merge():
    """A name key is sound for players and this says so out loud.

    Picks never reach here, which is what makes the key safe — a pick is the
    one asset class where two roster entries legitimately share a board row.
    If two starters ever collide anyway, merging them silently would drop a
    real player from the diff.
    """
    before = _starters(RB=[_asset("Same Name", "RB", 5000), _asset("Same Name", "RB", 4000)])
    with pytest.raises(ValueError, match="share the identity"):
        lineup_displacement(before, _starters(), incoming=[], outgoing=[])


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
