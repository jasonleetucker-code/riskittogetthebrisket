"""Roster capacity and forced drops.

Synthetic contracts throughout, so nothing here is a function of which
sources answered the last scrape.  The one live-board fact these tests
encode is the motivating measurement, and it is stated rather than
depended on: ``dynasty_main`` carries a 58-man cap and six of its twelve
rosters were AT the cap on 2026-08-18, so for half the league every
2-for-1 costs a release.
"""

from __future__ import annotations

import pytest

from src.trade.roster_capacity import (
    assess_roster_capacity,
    build_capacity_context,
    league_roster_limit,
    league_taxi_size,
    player_names_only,
)

# The test conftest deliberately points the league registry at a
# non-existent file so nothing here can reach a live league.  Roster
# settings are therefore stated explicitly, which is also how the real
# caller works: ``simulate_trade`` is already handed ``roster_settings``.
MAIN_SETTINGS = {
    "teamCount": 12,
    "rosterSize": 58,
    "taxiSize": 0,
    "starters": {
        "QB": 1,
        "RB": 2,
        "WR": 3,
        "TE": 2,
        "FLEX": 2,
        "SFLEX": 1,
        "K": 1,
        "DL": 3,
        "LB": 3,
        "DB": 3,
    },
}
NEW_SETTINGS = {
    "teamCount": 10,
    "rosterSize": 24,
    "taxiSize": 5,
    "starters": {"QB": 1, "RB": 2, "WR": 3, "TE": 1, "FLEX": 2, "SFLEX": 1},
}
NO_SETTINGS = None


def _row(name: str, value: float | None, position: str = "RB", player_id: str | None = None):
    row = {
        "playerId": player_id or name.lower().replace(" ", "_"),
        "displayName": name,
        "canonicalName": name,
        "position": position,
        "fantasyPositions": [position],
    }
    if value is not None:
        row["rankDerivedValue"] = value
    return row


def _contract(
    roster: list[tuple[str, float | None, str]],
    extra_rows=(),
    picks=(),
    opponent: list[str] = (),
):
    """A contract with our team, an opponent, and a free-agent pool.

    The opponent matters: waiver level is the best UNROSTERED player at a
    position, so a trade target sitting outside every roster would set his own
    replacement level and score an effective cut cost of zero.  Putting the
    incoming players on a real roster is what the live board does.
    """
    rows = [_row(n, v, p) for n, v, p in roster]
    rows.extend(extra_rows)
    team = {
        "name": "Test Team",
        "ownerId": "owner-1",
        "roster_id": 1,
        "players": [n for n, _v, _p in roster],
        "playerIds": [n.lower().replace(" ", "_") for n, _v, _p in roster],
        "picks": list(picks),
    }
    teams = [team]
    if opponent:
        teams.append(
            {
                "name": "Opponent",
                "ownerId": "owner-2",
                "roster_id": 2,
                "players": list(opponent),
                "playerIds": [n.lower().replace(" ", "_") for n in opponent],
                "picks": [],
            }
        )
    return {"playersArray": rows, "sleeper": {"teams": teams}}, team


#: Positions cycled so a roster of any size can actually fill a lineup.
#: This matters: ``build_cut_ladder`` validates every rung against the exact
#: lineup solver, so a roster of 58 running backs has almost nothing droppable
#: and the ladder is empty for reasons that have nothing to do with capacity.
_POSITION_CYCLE = ("RB", "WR", "TE", "QB", "LB", "DB", "DL", "WR", "RB", "K")


def _roster(n: int, *, base: float = 1000.0):
    """``n`` players with strictly descending values, spread across positions."""
    return [
        (f"Player {i:02d}", base + (n - i) * 10.0, _POSITION_CYCLE[i % len(_POSITION_CYCLE)])
        for i in range(n)
    ]


def _incoming(names, value: float = 4000.0, position: str = "WR"):
    """Board rows for players arriving in a trade.

    Without these the arrivals are unresolvable, and ``effective_cut_cost``
    scores an unranked player 0 by design (``src/draft/displacement.py``:
    "at or below waiver level by definition"), which would make the arrival
    the cheapest release and quietly change what a test is measuring.
    """
    return [_row(n, value, position) for n in names]


def _free_agents(count: int = 12, *, base: float = 300.0):
    """Unrostered rows, so waiver level is a real number rather than zero."""
    return [
        _row(f"FA {i:02d}", base + i, _POSITION_CYCLE[i % len(_POSITION_CYCLE)])
        for i in range(count)
    ]


def _ctx(roster, settings=None, extra_rows=None, picks=(), opponent=()):
    contract, team = _contract(
        roster,
        extra_rows=_free_agents() if extra_rows is None else extra_rows,
        picks=picks,
        opponent=opponent,
    )
    return build_capacity_context(
        contract, None, team, roster_settings=MAIN_SETTINGS if settings is None else settings
    )


# ── The league caps, from the one resolver ───────────────────────────


def test_league_caps_read_the_settings_they_are_given():
    assert league_roster_limit(None, MAIN_SETTINGS) == 58
    assert league_taxi_size(None, MAIN_SETTINGS) == 0
    assert league_roster_limit(None, NEW_SETTINGS) == 24
    assert league_taxi_size(None, NEW_SETTINGS) == 5


def test_league_caps_fall_back_to_the_registry(monkeypatch):
    """One resolver, and it does read the registry when nobody hands it settings."""

    class _Cfg:
        roster_settings = {"rosterSize": 30, "taxiSize": 4}

    import src.trade.roster_capacity as rc

    monkeypatch.setattr(
        "src.api.league_registry.get_league_by_key", lambda key: _Cfg() if key == "x" else None
    )
    assert rc.league_roster_limit("x") == 30
    assert rc.league_taxi_size("x") == 4
    assert rc.league_roster_limit("nope") is None


@pytest.mark.parametrize(
    "bad", [{}, {"rosterSize": 0}, {"rosterSize": "many"}, {"rosterSize": None}]
)
def test_an_unusable_roster_size_reads_as_unknown(bad):
    assert league_roster_limit(None, bad) is None


def test_an_unknown_cap_is_unknown_and_never_unlimited():
    """The optimistic default is the failure mode; state it as a test.

    A league with no configured roster size must NOT read as a league
    with no roster limit, which would make every trade look free.
    """
    assert league_roster_limit(None, {}) is None

    capacity = assess_roster_capacity(
        _ctx(_roster(20), settings={"starters": MAIN_SETTINGS["starters"]}),
        incoming_players=["A", "B", "C"],
        outgoing_players=[],
    )
    assert capacity.roster_limit is None
    assert capacity.over_limit_after is None
    assert capacity.open_spots_after is None
    assert capacity.forced_drops == []
    # UNKNOWN, and it must say unknown rather than "no drops needed".
    assert capacity.requires_drops is None
    assert capacity.certainty == "partial"
    assert any("UNKNOWN, not unlimited" in n for n in capacity.notes)


# ── Counting ─────────────────────────────────────────────────────────


def test_open_spots_absorb_the_trade():
    capacity = assess_roster_capacity(
        _ctx(_roster(50)), incoming_players=["In 1", "In 2"], outgoing_players=["Player 00"]
    )
    assert (capacity.size_before, capacity.size_after) == (50, 51)
    assert capacity.open_spots_before == 8
    assert capacity.open_spots_after == 7
    assert capacity.over_limit_after == 0
    assert capacity.forced_drops == []
    assert capacity.forced_drop_value == 0.0


@pytest.mark.parametrize(
    ("incoming", "outgoing", "expected_after", "expected_over"),
    [
        (1, 1, 58, 0),  # 1-for-1 is capacity neutral
        (1, 2, 57, 0),  # 2-for-1 frees a spot
        (2, 3, 57, 0),  # 3-for-2 frees a spot
        (2, 1, 59, 1),  # 1-for-2 costs one
        (3, 1, 60, 2),  # 1-for-3 costs two
        (3, 2, 59, 1),  # 2-for-3 costs one
    ],
)
def test_package_shapes_on_a_full_roster(incoming, outgoing, expected_after, expected_over):
    roster = _roster(58)
    capacity = assess_roster_capacity(
        _ctx(roster),
        incoming_players=[f"In {i}" for i in range(incoming)],
        outgoing_players=[n for n, _v, _p in roster[:outgoing]],
    )
    assert capacity.size_before == 58
    assert capacity.size_after == expected_after
    assert capacity.over_limit_after == expected_over
    assert len(capacity.forced_drops) == expected_over


def test_forced_drops_carry_their_value():
    """An asymmetric package cannot present released value as free."""
    roster = _roster(58)
    capacity = assess_roster_capacity(
        _ctx(
            roster,
            extra_rows=[*_free_agents(), *_incoming(["In 1", "In 2"])],
            opponent=["In 1", "In 2"],
        ),
        incoming_players=["In 1", "In 2"],
        outgoing_players=["Player 00"],
    )
    assert capacity.over_limit_after == 1
    (drop,) = capacity.forced_drops
    assert drop.value is not None and drop.value > 0
    assert drop.rung == 1
    assert capacity.forced_drop_value == drop.value
    assert capacity.unpriced_forced_drops == 0


def test_the_cheapest_release_goes_first_and_cheapest_means_over_replacement():
    """Ordering is by EFFECTIVE CUT COST, not raw board value.

    ``effective_cut_cost`` is ``max(0, value - waiver level at his position)``
    scaled by positional scarcity, because releasing a player you can replace
    off the wire costs you the difference, not his sticker price.  Asserting
    raw value here would pin the wrong quantity and would pass today only by
    accident.
    """
    roster = _roster(58)
    capacity = assess_roster_capacity(
        _ctx(
            roster,
            extra_rows=[*_free_agents(), *_incoming(["In 1", "In 2", "In 3"])],
            opponent=["In 1", "In 2", "In 3"],
        ),
        incoming_players=["In 1", "In 2", "In 3"],
        outgoing_players=["Player 00"],
    )
    costs = [d.effective_cut_cost for d in capacity.forced_drops]
    assert costs == sorted(costs)
    assert len(capacity.forced_drops) == capacity.over_limit_after


def test_multi_drop_is_ordered_and_summed():
    roster = _roster(58)
    capacity = assess_roster_capacity(
        _ctx(
            roster,
            extra_rows=[*_free_agents(), *_incoming(["In 1", "In 2", "In 3", "In 4"])],
            opponent=["In 1", "In 2", "In 3", "In 4"],
        ),
        incoming_players=["In 1", "In 2", "In 3", "In 4"],
        outgoing_players=["Player 00"],
    )
    assert capacity.over_limit_after == 3
    assert [d.rung for d in capacity.forced_drops] == [1, 2, 3]
    costs = [d.effective_cut_cost for d in capacity.forced_drops]
    assert costs == sorted(costs)  # cheapest release first
    values = [d.value for d in capacity.forced_drops if d.value is not None]
    assert capacity.forced_drop_value == pytest.approx(sum(values))


# ── Already illegal ──────────────────────────────────────────────────


def test_an_already_over_limit_roster_models_the_path_back():
    """A roster can be illegal before the trade; that must not be assumed away."""
    roster = _roster(61)
    capacity = assess_roster_capacity(
        _ctx(roster), incoming_players=["In 1"], outgoing_players=["Player 00"]
    )
    assert capacity.size_before == 61
    assert capacity.over_limit_before == 3
    assert capacity.size_after == 61
    assert capacity.over_limit_after == 3
    assert len(capacity.forced_drops) == 3
    assert any("ALREADY 3 over" in n for n in capacity.notes)


def test_over_limit_before_does_not_hide_the_trade_s_own_cost():
    over = assess_roster_capacity(
        _ctx(_roster(60)), incoming_players=["In 1", "In 2"], outgoing_players=[]
    )
    assert over.over_limit_before == 2
    assert over.over_limit_after == 4


# ── Picks ────────────────────────────────────────────────────────────


def test_draft_picks_do_not_occupy_roster_spots():
    """Verified on the live contract, not assumed.

    ``rosterSize`` is 58, the largest live roster holds exactly 58
    PLAYERS, and those same teams hold 10-23 picks besides.  So a
    pick-for-player trade is NOT capacity-neutral, and this is the test
    that would fail if someone started counting picks.
    """
    roster = _roster(58)
    context = _ctx(roster, picks=["2027 Early 1st", "2027 Mid 2nd"])
    assert context.roster_player_names == tuple(n for n, _v, _p in roster)

    # Give a player, receive a pick → a spot opens.
    capacity = assess_roster_capacity(context, incoming_players=[], outgoing_players=["Player 00"])
    assert capacity.size_after == 57
    assert capacity.over_limit_after == 0


def test_player_names_only_drops_pick_rows():
    side = [
        {"name": "Josh Allen", "pos": "QB"},
        {"name": "2027 Early 1st", "pos": "PICK"},
        {"name": "Micah Parsons", "position": "LB"},
    ]
    assert player_names_only(side) == ["Josh Allen", "Micah Parsons"]


# ── Missing is never zero ────────────────────────────────────────────


def test_an_unresolved_player_still_occupies_a_spot():
    """Counting from what resolved would understate roster pressure."""
    contract, team = _contract(_roster(57), extra_rows=_free_agents())
    team["players"].append("Ghost Who Never Joined")
    team["playerIds"].append("ghost")
    context = build_capacity_context(contract, None, team, roster_settings=MAIN_SETTINGS)
    assert len(context.roster_player_names) == 58

    capacity = assess_roster_capacity(
        context, incoming_players=["In 1", "In 2"], outgoing_players=["Player 00"]
    )
    assert capacity.size_before == 58
    assert capacity.over_limit_after == 1
    assert any("did not join to the board" in n for n in context.notes)


def test_two_roster_entries_that_collide_on_identity_are_still_two_spots():
    """Counts come from the ROSTER, not from a keyed index of it.

    ``build_roster_assets`` keys by player id falling back to name, so two
    entries that normalize to the same key collapse to one asset.  A roster
    spot is not an identity — it is a slot — so collapsing them would report a
    58-man roster as 57 and hide a forced drop.  Sleeper ids are unique in
    practice; this pins the rule rather than the current luck.
    """
    roster = _roster(57)
    contract, team = _contract(roster, extra_rows=_free_agents())
    # Same name twice, no distinguishing id — the collision case.
    team["players"].append("Player 00")
    team["playerIds"].append("player_00")
    context = build_capacity_context(contract, None, team, roster_settings=MAIN_SETTINGS)

    assert len(context.roster_player_names) == 58
    capacity = assess_roster_capacity(context, incoming_players=["In 1"], outgoing_players=[])
    assert capacity.size_before == 58
    assert capacity.size_after == 59
    assert capacity.over_limit_after == 1


def test_removing_one_of_a_colliding_pair_removes_exactly_one_spot():
    """By multiplicity, not by set membership.

    The same rule ``simulate_trade`` had to learn for picks (C1-U6
    follow-up 10): trading one of two identical-keyed assets must not
    remove both.
    """
    roster = _roster(57)
    contract, team = _contract(roster, extra_rows=_free_agents())
    team["players"].append("Player 00")
    team["playerIds"].append("player_00")
    context = build_capacity_context(contract, None, team, roster_settings=MAIN_SETTINGS)

    capacity = assess_roster_capacity(context, incoming_players=[], outgoing_players=["Player 00"])
    assert capacity.size_after == 57  # one gone, one kept


def test_an_outgoing_player_the_roster_does_not_hold_frees_no_spot():
    """A name that was never there cannot free a spot.

    ``size_after`` used to subtract ``len(outgoing)`` flat, while
    ``_surviving_keys`` and the roster rebuild removed only what was actually
    present — two definitions of the post-trade roster in one function,
    disagreeing in the direction that HIDES pressure.  Reachable from
    ``/api/angle/find``, which lets a user select any player on the BOARD.
    """
    roster = _roster(58)
    contract, team = _contract(roster, extra_rows=_free_agents())
    context = build_capacity_context(contract, None, team, roster_settings=MAIN_SETTINGS)

    capacity = assess_roster_capacity(
        context,
        incoming_players=["Free Agent 00"],
        outgoing_players=["Somebody Else Entirely"],
    )
    assert capacity.size_before == 58
    assert capacity.outgoing == 1  # what was ASKED
    assert capacity.outgoing_not_on_roster == 1  # what could not happen
    assert capacity.size_after == 59  # not 58
    assert capacity.over_limit_after == 1
    assert len(capacity.forced_drops) == 1
    assert any("free no spot" in n for n in capacity.notes)


def test_a_partly_held_outgoing_multiset_frees_only_what_is_held():
    """Multiplicity on the miss side too: two asked, one held, one freed."""
    roster = _roster(58)
    contract, team = _contract(roster, extra_rows=_free_agents())
    context = build_capacity_context(contract, None, team, roster_settings=MAIN_SETTINGS)

    capacity = assess_roster_capacity(
        context,
        incoming_players=[],
        outgoing_players=["Player 00", "Player 00"],
    )
    assert capacity.outgoing == 2
    assert capacity.outgoing_not_on_roster == 1
    assert capacity.size_after == 57


def test_an_outgoing_name_the_roster_holds_is_unaffected():
    """The ordinary path must be byte-identical — this is not a new rule."""
    roster = _roster(58)
    contract, team = _contract(roster, extra_rows=_free_agents())
    context = build_capacity_context(contract, None, team, roster_settings=MAIN_SETTINGS)

    capacity = assess_roster_capacity(
        context,
        incoming_players=["Free Agent 00"],
        outgoing_players=["Player 00"],
    )
    assert capacity.outgoing_not_on_roster == 0
    assert capacity.size_after == 58
    assert capacity.over_limit_after == 0
    assert not any("free no spot" in n for n in capacity.notes)


def test_an_unpriced_forced_drop_is_reported_not_counted_as_zero():
    roster = _roster(57)
    contract, team = _contract(
        roster,
        extra_rows=[*_free_agents(), *_incoming(["In 1", "In 2"])],
        opponent=["In 1", "In 2"],
    )
    contract["playersArray"].append(_row("Unpriced Guy", None, "WR"))
    team["players"].append("Unpriced Guy")
    team["playerIds"].append("unpriced_guy")
    context = build_capacity_context(contract, None, team, roster_settings=MAIN_SETTINGS)

    capacity = assess_roster_capacity(
        context, incoming_players=["In 1", "In 2"], outgoing_players=["Player 00"]
    )
    assert capacity.over_limit_after == 1
    (drop,) = capacity.forced_drops
    # ``effective_cut_cost`` scores an unranked player 0 by design, so he is
    # the cheapest release.  That is the ladder owner's rule and this module
    # does not overrule it — what it must do is refuse to publish his value
    # as a number, because "we could not price him" and "he is worth nothing"
    # are different statements.
    assert drop.name == "Unpriced Guy"
    assert drop.value is None  # NOT 0.0
    assert drop.value_basis == "assumedWaiver"
    assert capacity.unpriced_forced_drops == 1
    # The total excludes him rather than silently absorbing a zero.
    assert capacity.forced_drop_value == 0.0
    # And the cut-cost total, which IS defined for him, is published separately.
    assert capacity.forced_drop_cut_cost == pytest.approx(drop.effective_cut_cost)


# ── Taxi ─────────────────────────────────────────────────────────────


def test_taxi_slots_make_the_conclusion_partial_not_silently_relieved():
    """Unknown taxi membership is a RANGE, never an assumption.

    Sleeper lists taxi players inside ``players``, so counting every listed
    player against the active cap **overstates** roster pressure — the opposite
    of what this module first claimed — and in a 5-slot league it can invent up
    to five forced drops that are not required.  Assuming full relief would
    hide real ones.  Neither guess is available, so the answer is bracketed.
    """
    # 28 rostered against a 24-man cap with 5 taxi slots: over by 4 if nobody
    # is on taxi, legal if four or more are.  Genuinely unknown.
    context = _ctx(_roster(28), settings=NEW_SETTINGS)
    assert context.taxi_membership_known is False
    assert any("partial" in n and "taxi" in n for n in context.notes)

    capacity = assess_roster_capacity(context, incoming_players=[], outgoing_players=[])
    assert capacity.taxi_size == 5
    assert capacity.certainty == "partial"
    assert capacity.over_limit_after is None  # no point estimate may be published
    assert capacity.over_limit_after_min == 0
    assert capacity.over_limit_after_max == 4
    assert capacity.taxi_occupied_min == 0
    assert capacity.taxi_occupied_max == 5
    assert capacity.requires_drops is None  # NOT False
    payload = capacity.to_dict()
    assert payload["requiresDrops"] is None
    assert payload["forcedDropsAreUpperBound"] is True


def test_a_partial_conclusion_still_names_the_worst_case_drops():
    """Bracketed does not mean silent — the upper bound is still actionable."""
    capacity = assess_roster_capacity(
        _ctx(_roster(28), settings=NEW_SETTINGS), incoming_players=[], outgoing_players=[]
    )
    assert len(capacity.forced_drops) == capacity.over_limit_after_max
    assert capacity.to_dict()["forcedDropsAreUpperBound"] is True


def test_taxi_relief_cannot_rescue_a_roster_that_is_over_even_with_it():
    """When the bracket does not straddle, the answer is certain again."""
    # 30 rostered, 24 cap, 5 taxi: over by at least 1 however taxi is assigned.
    capacity = assess_roster_capacity(
        _ctx(_roster(30), settings=NEW_SETTINGS), incoming_players=[], outgoing_players=[]
    )
    assert capacity.over_limit_after_min == 1
    assert capacity.over_limit_after_max == 6
    assert capacity.requires_drops is True


def test_a_roster_legal_under_every_taxi_assignment_is_exact():
    """No bracket is published when it cannot change the answer."""
    capacity = assess_roster_capacity(
        _ctx(_roster(20), settings=NEW_SETTINGS), incoming_players=["In 1"], outgoing_players=[]
    )
    assert capacity.certainty == "exact"
    assert capacity.over_limit_after == 0
    assert capacity.requires_drops is False


def test_a_zero_taxi_league_is_never_bracketed():
    """``dynasty_main`` is unaffected by any of this."""
    capacity = assess_roster_capacity(
        _ctx(_roster(58)), incoming_players=["In 1", "In 2"], outgoing_players=["Player 00"]
    )
    assert capacity.taxi_size == 0
    assert capacity.certainty == "exact"
    assert capacity.over_limit_after == 1
    assert capacity.over_limit_after_min == capacity.over_limit_after_max == 1
    assert capacity.requires_drops is True
    assert capacity.to_dict()["forcedDropsAreUpperBound"] is False


def test_known_taxi_membership_is_used_and_makes_the_answer_exact():
    """The bracket exists because membership is invisible, not on principle.

    Hand it a roster that DOES carry ``taxi`` and the range collapses.  No
    contract-shaped caller supplies this today; the path exists so that adding
    ``taxi`` to the team block is a data change rather than a code change.
    """
    roster = _roster(28)
    contract, team = _contract(roster, extra_rows=_free_agents())
    on_taxi = [n for n, _v, _p in roster[:4]]
    team["taxi"] = on_taxi
    context = build_capacity_context(contract, None, team, roster_settings=NEW_SETTINGS)

    assert context.taxi_membership_known is True
    capacity = assess_roster_capacity(context, incoming_players=[], outgoing_players=[])
    assert capacity.certainty == "exact"
    assert capacity.taxi_occupied_min == capacity.taxi_occupied_max == 4
    # 28 rostered − 4 on taxi = 24 active, exactly the cap.
    assert capacity.over_limit_after == 0
    assert capacity.requires_drops is False


def test_a_traded_away_taxi_player_frees_his_taxi_slot_not_a_roster_spot():
    roster = _roster(28)
    contract, team = _contract(roster, extra_rows=_free_agents())
    team["taxi"] = [n for n, _v, _p in roster[:4]]
    context = build_capacity_context(contract, None, team, roster_settings=NEW_SETTINGS)

    capacity = assess_roster_capacity(context, incoming_players=[], outgoing_players=[roster[0][0]])
    # One taxi member left, so 27 rostered − 3 on taxi = 24 active.
    assert capacity.taxi_occupied_max == 3
    assert capacity.over_limit_after == 0


# ── The acquired player as a cut candidate ───────────────────────────


def test_a_player_acquired_in_the_trade_can_be_the_forced_drop_and_is_flagged():
    """Not hidden.

    If the cheapest legal release is the piece the trade just brought in,
    that is the honest answer and it is a strong signal about the trade.
    Suppressing it would make the cheapest legal path invisible.
    """
    roster = _roster(58, base=5000.0)
    contract, team = _contract(roster, extra_rows=_free_agents())
    # A cheap piece at a position the roster is already deep in, so the lineup
    # guard has no reason to protect him.
    contract["playersArray"].append(_row("Cheap Arrival", 200.0, "WR"))
    context = build_capacity_context(contract, None, team, roster_settings=MAIN_SETTINGS)

    capacity = assess_roster_capacity(
        context, incoming_players=["Cheap Arrival", "Player 00"], outgoing_players=["Player 00"]
    )
    assert capacity.over_limit_after == 1
    (drop,) = capacity.forced_drops
    assert drop.name == "Cheap Arrival"
    assert drop.acquired_in_trade is True


# ── Agreement with the generator's legality rule ─────────────────────


@pytest.mark.parametrize(
    ("size", "incoming", "outgoing"),
    [(58, 2, 1), (58, 1, 1), (50, 3, 1), (58, 1, 3), (61, 1, 1)],
)
def test_agrees_with_check_legality_arithmetic(size, incoming, outgoing):
    """One counting rule, two consumers with different verdicts.

    ``roster_intel.packages._check_legality`` REFUSES an over-cap package;
    this module REPORTS it.  They must never disagree about whether the
    package is over the cap — only about what to do next.
    """
    from src.roster_intel.packages import _check_legality

    class _A:
        def __init__(self, i):
            self.asset_id = str(i)

    roster = _roster(size)
    capacity = assess_roster_capacity(
        _ctx(roster),
        incoming_players=[f"In {i}" for i in range(incoming)],
        outgoing_players=[n for n, _v, _p in roster[:outgoing]],
    )
    send = [_A(f"out{i}") for i in range(outgoing)]
    receive = [_A(f"in{i}") for i in range(incoming)]
    ok, _detail = _check_legality(send, receive, size, 40, 58)

    # ``_check_legality`` also guards the counterparty and empty packages;
    # our side's over-cap verdict is the part that must agree.
    over = bool(capacity.over_limit_after)
    if ok:
        assert not over
    else:
        assert over or size - outgoing + incoming < 1


# ── Degradation ──────────────────────────────────────────────────────


def test_no_board_still_answers_the_counts():
    """The counts are the load-bearing part; a missing board must not raise."""
    context = build_capacity_context(
        None, None, {"players": [f"P{i}" for i in range(58)]}, roster_settings=MAIN_SETTINGS
    )
    capacity = assess_roster_capacity(context, incoming_players=["A", "B"], outgoing_players=["P0"])
    assert capacity.size_before == 58
    assert capacity.over_limit_after == 1
    # Nothing can be priced, so the drops are unpriced rather than free.
    assert capacity.unpriced_forced_drops == len(capacity.forced_drops)


def test_no_team_is_an_empty_roster_not_a_crash():
    context = build_capacity_context(
        {"playersArray": []}, None, None, roster_settings=MAIN_SETTINGS
    )
    capacity = assess_roster_capacity(context, incoming_players=["A"], outgoing_players=[])
    assert capacity.size_before == 0
    assert capacity.size_after == 1
    assert capacity.over_limit_after == 0


def test_to_dict_is_json_shaped():
    import json

    capacity = assess_roster_capacity(
        _ctx(_roster(58)), incoming_players=["In 1", "In 2"], outgoing_players=["Player 00"]
    )
    payload = capacity.to_dict()
    json.dumps(payload)  # must not raise
    assert payload["valueScale"] == "rankDerivedValue"
    assert payload["forcedDrops"][0]["valueScale"] == "rankDerivedValue"


# ── Release cost vs Effective Cut Cost ────────────────────────────────
#
# `effective_cut_cost` is `max(0, base - waiver) x scarcity`, so it is **0 for
# every player at or below waiver level** — which, on a roster that is full, is
# exactly the tail the cut ladder selects. Measured on the 2026-08-18 board:
# every one of the twelve `dynasty_main` rosters produces forced drops with
# ECC 0.0, so `forcedDropCutCost` summed to 0.0 while `forcedDropValue` on the
# same trade was 3,964.
#
# ECC is not WRONG, it answers a different question — "what do I lose against
# the wire", and Bobby Wagner (1,312) really is below the LB waiver level
# (1,740). It is the wrong question HERE: the vacated spot is consumed by the
# incoming player, so there is no wire pickup to net against, and charging
# value-over-replacement credits a replacement that cannot be signed.
#
# Perfect Draft hit this first; CLAUDE.md records its answer and this consumes
# the same rule rather than inventing a third notion of what a cut costs.


def test_release_cost_is_not_zero_when_the_cut_ladder_is_below_waiver_level():
    roster = _roster(58)
    contract, team = _contract(roster, extra_rows=_free_agents())
    context = build_capacity_context(contract, None, team, roster_settings=MAIN_SETTINGS)
    capacity = assess_roster_capacity(context, incoming_players=["Free Agent 00"])

    assert capacity.forced_drops, "fixture forced no drops — it proves nothing"
    drop = capacity.forced_drops[0]
    # The whole point: a real cost where ECC reports none.
    assert drop.release_cost > 0
    assert capacity.forced_drop_release_cost == pytest.approx(
        sum(d.release_cost for d in capacity.forced_drops)
    )


def test_release_cost_consumes_the_ladder_rather_than_re_deriving_scarcity():
    """`base x scarcity`, with both read off the rung.

    Re-deriving the multiplier here would be a fourth copy of a rule
    `src/draft/displacement.py` already owns (its docstring names the third).
    """
    roster = _roster(58)
    contract, team = _contract(roster, extra_rows=_free_agents())
    context = build_capacity_context(contract, None, team, roster_settings=MAIN_SETTINGS)
    capacity = assess_roster_capacity(context, incoming_players=["Free Agent 00"])

    for drop in capacity.forced_drops:
        base = drop.value if drop.value is not None else drop.waiver_value
        assert drop.release_cost == pytest.approx(base * drop.scarcity_multiplier)


def test_both_costs_are_published_so_they_can_be_reconciled():
    """Neither number is removed.

    `effectiveCutCost` keeps its meaning for the consumers that want value over
    replacement; `releaseCost` answers the roster question. Publishing only one
    would either hide the real cost or silently change what an existing field
    means.
    """
    roster = _roster(58)
    contract, team = _contract(roster, extra_rows=_free_agents())
    context = build_capacity_context(contract, None, team, roster_settings=MAIN_SETTINGS)
    payload = assess_roster_capacity(context, incoming_players=["Free Agent 00"]).to_dict()

    assert {"forcedDropCutCost", "forcedDropReleaseCost"} <= set(payload)
    row = payload["forcedDrops"][0]
    assert {"effectiveCutCost", "releaseCost", "waiverValue", "scarcityMultiplier"} <= set(row)


def test_an_above_replacement_drop_still_reports_both_costs():
    """Where ECC is non-zero the two numbers differ but neither is zero.

    Guards against "just alias releaseCost to ECC" — they are different
    quantities, and a fixture where ECC happens to be 0 could not show that.
    """
    roster = _roster(58)
    contract, team = _contract(roster, extra_rows=_free_agents())
    context = build_capacity_context(contract, None, team, roster_settings=MAIN_SETTINGS)
    capacity = assess_roster_capacity(context, incoming_players=["Free Agent 00"])

    for drop in capacity.forced_drops:
        if drop.effective_cut_cost > 0:
            assert drop.release_cost > drop.effective_cut_cost, (
                "release cost must exceed value-over-replacement — it does not "
                "net out the waiver level"
            )
            break
