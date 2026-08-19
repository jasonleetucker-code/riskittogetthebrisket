"""Roster capacity reaches the surfaces that needed it — and filters nothing.

The counting lives in ``tests/trade/test_roster_capacity.py``.  This file is
about the WIRING, and specifically about the one way wiring a constraint into a
recommender goes wrong: the lists get shorter and nobody notices.

``roster_intel.packages._check_legality`` REFUSES an over-cap package, which is
right for a generator choosing what to put on a Pareto frontier.  On a full
58-man roster — six of the twelve live ``dynasty_main`` rosters were at the cap
on 2026-08-18 — the same rule applied here would silently empty the suggestion
and arbitrage lists.  So these surfaces REPORT, and the assertion that matters
is that the result count is byte-identical with the capacity read on and off.
"""

from __future__ import annotations

import pytest

from src.trade.roster_capacity import build_capacity_context
from src.trade.suggestions import PlayerAsset, generate_suggestions_from_pool

SETTINGS = {
    "teamCount": 12,
    "rosterSize": 34,
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
#: The response keys are camelCase — ``sell_high`` etc. are the INTERNAL
#: category names and reading them off the payload silently yields zero,
#: which reads exactly like "the engine found nothing".
_CATEGORIES = ("sellHigh", "buyLow", "consolidation", "positionalUpgrades")

#: Roster size is set to exactly the fixture roster length, so the team is AT
#: the cap.  That is the state the wiring exists for — six of the twelve live
#: ``dynasty_main`` rosters were at 58/58 on 2026-08-18 — and it is the state
#: in which a legality FILTER would empty these lists.
ROSTER_SIZE = 34


def _asset(name: str, value: int, position: str, *, rookie: bool = False) -> PlayerAsset:
    return PlayerAsset(
        name=name,
        position=position,
        display_value=value,
        calibrated_value=value,
        source_count=6,
        years_exp=4,
        rookie=rookie,
        board_rank=None,
    )


#: A positional shape that actually generates suggestions: deep at QB and RB,
#: thin at WR.  A uniform pool produces none at all, and a fixture that proves
#: nothing is worse than no fixture.
_SPREAD = {
    "QB": 10,
    "RB": 12,
    "WR": 12,
    "TE": 8,
    "LB": 8,
    "DB": 8,
    "DL": 8,
    "K": 3,
}


def _pool() -> list[PlayerAsset]:
    pool: list[PlayerAsset] = []
    for position, count in _SPREAD.items():
        for i in range(count):
            pool.append(_asset(f"{position} {i:02d}", 8000 - i * 400, position))
    for rank, asset in enumerate(sorted(pool, key=lambda a: -a.display_value), start=1):
        asset.board_rank = rank
    return pool


def _roster_names(pool: list[PlayerAsset], size: int) -> list[str]:
    """A roster deep at QB/RB and thin at WR, padded to ``size``."""
    by_position: dict[str, list[str]] = {}
    for asset in pool:
        by_position.setdefault(asset.position, []).append(asset.name)
    roster: list[str] = []
    roster += by_position["QB"][:6]  # surplus
    roster += by_position["RB"][:7]  # surplus
    roster += by_position["WR"][:1]  # need
    roster += by_position["TE"][:2]
    roster += by_position["LB"][:4]
    roster += by_position["DB"][:4]
    roster += by_position["DL"][:4]
    roster += by_position["K"][:1]
    # Pad with whatever is left so the roster sits exactly at the cap.
    for asset in pool:
        if len(roster) >= size:
            break
        if asset.name not in roster:
            roster.append(asset.name)
    assert len(roster) == size, f"fixture roster is {len(roster)}, wanted {size}"
    return roster


def _contract_for(pool: list[PlayerAsset], roster: list[str]) -> dict:
    rows = [
        {
            "playerId": a.name.lower().replace(" ", "_"),
            "displayName": a.name,
            "canonicalName": a.name,
            "position": a.position,
            "fantasyPositions": [a.position],
            "rankDerivedValue": a.display_value,
        }
        for a in pool
    ]
    team = {
        "name": "Us",
        "ownerId": "owner-1",
        "roster_id": 1,
        "players": list(roster),
        "playerIds": [n.lower().replace(" ", "_") for n in roster],
        "picks": [],
    }
    others = [a.name for a in pool if a.name not in set(roster)]
    opponent = {
        "name": "Them",
        "ownerId": "owner-2",
        "roster_id": 2,
        "players": others,
        "playerIds": [n.lower().replace(" ", "_") for n in others],
        "picks": [],
    }
    return {"playersArray": rows, "sleeper": {"teams": [team, opponent]}}


@pytest.fixture()
def full_roster_setup():
    pool = _pool()
    roster = _roster_names(pool, ROSTER_SIZE)
    contract = _contract_for(pool, roster)
    context = build_capacity_context(
        contract, None, contract["sleeper"]["teams"][0], roster_settings=SETTINGS
    )
    return pool, roster, context


def _counts(result: dict) -> dict[str, int]:
    return {k: len(result.get(k) or []) for k in _CATEGORIES}


# ── /api/trade/suggestions ───────────────────────────────────────────


def test_suggestions_are_not_filtered_by_capacity(full_roster_setup):
    """The lists must be the same length with the capacity read on and off.

    This is the whole point of "report, never filter", and it is the assertion
    that would catch someone later deciding an over-cap suggestion should be
    dropped "for cleanliness".
    """
    pool, roster, context = full_roster_setup
    without = generate_suggestions_from_pool(roster_names=roster, pool=pool)
    with_capacity = generate_suggestions_from_pool(
        roster_names=roster, pool=pool, capacity_context=context
    )
    assert _counts(without) == _counts(with_capacity)

    # And the same suggestions, in the same order — capacity must not
    # reorder them either, because it does not feed the ranking.
    for category in _CATEGORIES:
        a = [(s["give"][0]["name"], s["receive"][0]["name"]) for s in without.get(category) or []]
        b = [
            (s["give"][0]["name"], s["receive"][0]["name"])
            for s in with_capacity.get(category) or []
        ]
        assert a == b


def test_suggestions_carry_the_capacity_block_when_it_is_available(full_roster_setup):
    pool, roster, context = full_roster_setup
    result = generate_suggestions_from_pool(
        roster_names=roster, pool=pool, capacity_context=context
    )
    seen = 0
    for category in _CATEGORIES:
        for suggestion in result.get(category) or []:
            capacity = suggestion.get("rosterCapacity")
            assert capacity is not None, f"{category} suggestion has no capacity block"
            assert capacity["rosterLimit"] == ROSTER_SIZE
            assert capacity["sizeBefore"] == ROSTER_SIZE
            # give/receive counts must reconcile with the reported deltas
            assert capacity["outgoing"] == len(suggestion["give"])
            assert capacity["incoming"] == len(suggestion["receive"])
            assert (
                capacity["sizeAfter"] == ROSTER_SIZE - capacity["outgoing"] + capacity["incoming"]
            )
            seen += 1
    assert seen > 0, "fixture produced no suggestions — it cannot prove anything"


def test_a_one_for_two_on_a_full_roster_reports_its_forced_drop(full_roster_setup):
    pool, roster, context = full_roster_setup
    result = generate_suggestions_from_pool(
        roster_names=roster, pool=pool, capacity_context=context
    )
    asymmetric = [
        s
        for category in _CATEGORIES
        for s in result.get(category) or []
        if len(s["receive"]) > len(s["give"])
    ]
    for suggestion in asymmetric:
        capacity = suggestion["rosterCapacity"]
        assert capacity["overLimitAfter"] == len(s_receive := suggestion["receive"]) - len(
            suggestion["give"]
        )
        assert len(capacity["forcedDrops"]) == capacity["overLimitAfter"]
        assert s_receive  # keeps the walrus honest for linters


def test_no_suggestion_shape_can_currently_exceed_the_cap(full_roster_setup):
    """A property of today's generators, recorded so a change is visible.

    ``suggestions.py`` emits 1-for-1 (sell-high, buy-low, positional upgrade)
    and 2-for-1 (consolidation) — shapes that are capacity-neutral or that FREE
    a spot.  None of them can push a roster over the cap, so the forced-drop
    path is unreachable from this surface today and the capacity block reports
    the spot it frees.

    If someone adds a 1-for-2 generator this test fails, which is the point:
    the forced-drop path goes live at that moment and the guard below stops
    being theoretical.
    """
    pool, roster, context = full_roster_setup
    result = generate_suggestions_from_pool(
        roster_names=roster, pool=pool, capacity_context=context
    )
    for category in _CATEGORIES:
        for suggestion in result.get(category) or []:
            assert len(suggestion["receive"]) <= len(suggestion["give"])
            assert suggestion["rosterCapacity"]["overLimitAfter"] == 0


def test_an_already_over_limit_roster_does_not_lose_its_suggestions(full_roster_setup):
    """The guard that actually bites.

    On a roster that is ALREADY over the cap every suggestion reports forced
    drops, so a legality filter here would empty the lists outright.  The
    fixture above cannot catch that (its shapes never exceed the cap), and a
    guard that cannot fail is not a guard.
    """
    pool, roster, _context = full_roster_setup
    tight = dict(SETTINGS, rosterSize=ROSTER_SIZE - 3)
    contract = _contract_for(pool, roster)
    over_context = build_capacity_context(
        contract, None, contract["sleeper"]["teams"][0], roster_settings=tight
    )

    without = generate_suggestions_from_pool(roster_names=roster, pool=pool)
    with_capacity = generate_suggestions_from_pool(
        roster_names=roster, pool=pool, capacity_context=over_context
    )
    assert _counts(without) == _counts(with_capacity)
    assert sum(_counts(with_capacity).values()) > 0

    saw_drops = False
    for category in _CATEGORIES:
        for suggestion in with_capacity.get(category) or []:
            capacity = suggestion["rosterCapacity"]
            assert capacity["overLimitBefore"] == 3
            assert capacity["overLimitAfter"] > 0
            saw_drops = saw_drops or bool(capacity["forcedDrops"])
    assert saw_drops, "an over-cap roster must name the releases it needs"


def test_suggestions_without_a_context_say_so_rather_than_omitting_the_block(
    full_roster_setup,
):
    """Named, not silent — and still never a fabricated zero.

    A surface with no league context must not publish ``forcedDrops: []``,
    which reads as "this trade costs nothing" rather than "we did not check".
    This file used to pin the OTHER extreme: omit the key entirely.  That is
    equally unreadable, because ``server.py::_capacity_context_for`` returns
    ``None`` for two different things — no team block resolved, and building
    the context RAISED (logged server-side, invisible here) — so the client
    could not tell "we did not check" from "it fits".  The honest answer names
    itself: ``unavailable: no_capacity_context``.
    """
    pool, roster, _context = full_roster_setup
    result = generate_suggestions_from_pool(roster_names=roster, pool=pool)
    for category in _CATEGORIES:
        for suggestion in result.get(category) or []:
            assert suggestion["rosterCapacity"]["unavailable"] == "no_capacity_context"


# ── /api/trade/finder ────────────────────────────────────────────────


def _finder_inputs(pool: list[PlayerAsset], roster: list[str], contract: dict):
    """Raw players dict with a RETAIL market value that differs from the board.

    The finder measures the gap between our board and the market, so a fixture
    whose market equals the board has no arbitrage in it by construction and
    would return nothing — a skipping test that proves nothing.  Every other
    player is marked down 20% on the retail board so there is a real gap to
    find.
    """
    players = {}
    for i, asset in enumerate(pool):
        market = asset.display_value if i % 2 else int(asset.display_value * 0.8)
        players[asset.name] = {
            "_finalAdjusted": asset.display_value,
            "position": asset.position,
            "_sites": 6,
            "_canonicalSiteValues": {"ktcSfTep": market, "idpTradeCalc": market},
        }
    return players, contract["sleeper"]["teams"]


def test_finder_results_are_not_filtered_by_capacity():
    from src.trade.finder import find_trades

    pool = _pool()
    roster = _roster_names(pool, ROSTER_SIZE)
    contract = _contract_for(pool, roster)
    context = build_capacity_context(
        contract, None, contract["sleeper"]["teams"][0], roster_settings=SETTINGS
    )
    players, teams = _finder_inputs(pool, roster, contract)

    without = find_trades(players, "Us", ["Them"], teams, contract=contract)
    with_capacity = find_trades(
        players, "Us", ["Them"], teams, contract=contract, capacity_context=context
    )
    assert len(without["trades"]) == len(with_capacity["trades"])
    assert [t["give"] for t in without["trades"]] == [t["give"] for t in with_capacity["trades"]]

    assert with_capacity["trades"], "fixture produced no arbitrage trades — it proves nothing"
    for trade, plain in zip(with_capacity["trades"], without["trades"]):
        assert plain["rosterCapacity"]["unavailable"] == "no_capacity_context"
        capacity = trade["rosterCapacity"]
        assert capacity["rosterLimit"] == ROSTER_SIZE
        assert capacity["sizeAfter"] == ROSTER_SIZE - len(trade["give"]) + len(trade["receive"])
        assert len(capacity["forcedDrops"]) == capacity["overLimitAfter"]


# ── /api/angle/find + /api/angle/packages ────────────────────────────
#
# Angle is the surface where the forced-drop path is genuinely REACHABLE.
# ``suggestions.py`` emits nothing that exceeds a cap (the test above records
# that), and the finder needs its ``_generate_1for2`` shape.  Angle's offer mode
# sizes the counter-package at ``{N-1, N, N+1}`` — so N+1 sends one fewer player
# than it receives on EVERY size, on any roster, with no over-cap precondition.


def _angle_rows(pool: list[PlayerAsset]) -> list[dict]:
    """Angle's board rows: a my-value and a market value that differ.

    Every other player is marked down 20% on the retail board, same reasoning
    as ``_finder_inputs`` — with market == board there is no arbitrage in the
    fixture and the search returns nothing.
    """
    rows = []
    for i, asset in enumerate(pool):
        market = asset.display_value if i % 2 else int(asset.display_value * 0.8)
        rows.append(
            {
                "playerId": asset.name.lower().replace(" ", "_"),
                "canonicalName": asset.name,
                "displayName": asset.name,
                "position": asset.position,
                "rankDerivedValue": asset.display_value,
                "canonicalSiteValues": {"ktc": market, "idpTradeCalc": market},
            }
        )
    return rows


@pytest.fixture()
def angle_setup(full_roster_setup):
    pool, roster, context = full_roster_setup
    contract = _contract_for(pool, roster)
    return pool, roster, context, _angle_rows(pool), contract["sleeper"]["teams"]


def _cheapest_rostered(pool: list[PlayerAsset], roster: list[str]) -> str:
    """The roster's LOWEST-valued player.

    Angle only surfaces targets that beat the selected player on my-value, so
    selecting the roster's best asset returns an empty list and proves nothing.
    """
    held = {a.name: a.display_value for a in pool if a.name in set(roster)}
    return min(held, key=lambda n: held[n])


def test_angle_find_is_not_filtered_by_capacity(angle_setup):
    from src.trade.angle import find_angles

    pool, roster, context, rows, teams = angle_setup
    mine = _cheapest_rostered(pool, roster)

    kwargs = dict(min_my_gain_pct=1.0, max_market_gain_pct=100.0)
    without = find_angles(rows, mine, "owner-1", teams, **kwargs)
    with_capacity = find_angles(rows, mine, "owner-1", teams, capacity_context=context, **kwargs)
    assert without["candidates"], "fixture produced no angles — it proves nothing"
    assert [c["name"] for c in without["candidates"]] == [
        c["name"] for c in with_capacity["candidates"]
    ]

    for plain, annotated in zip(without["candidates"], with_capacity["candidates"]):
        assert plain["rosterCapacity"]["unavailable"] == "no_capacity_context"
        capacity = annotated["rosterCapacity"]
        assert capacity["rosterLimit"] == ROSTER_SIZE
        # 1-for-1 out of a roster that holds the selected player: size-neutral.
        assert capacity["outgoing"] == 1
        assert capacity["incoming"] == 1
        assert capacity["sizeAfter"] == ROSTER_SIZE
        assert capacity["overLimitAfter"] == 0
        assert capacity["forcedDrops"] == []


def test_angle_find_is_not_size_neutral_when_the_roster_lacks_the_player(angle_setup):
    """The reason the block is attached per candidate rather than once.

    Angle lets a user select any player on the BOARD, not only one they own, so
    "trade away a player you do not hold" is reachable from the endpoint.  It
    adds one and removes none.

    This is also what caught a real inconsistency in the owner: ``size_after``
    subtracted ``len(outgoing)`` flat while ``_surviving_keys`` and the roster
    rebuild removed only what was actually there, so the ladder was built on one
    roster and the drop count computed from another — in the direction that
    HIDES pressure, reporting a freed spot that never existed.
    """
    from src.trade.angle import find_angles

    pool, roster, _context, rows, teams = angle_setup
    mine = _cheapest_rostered(pool, roster)
    contract = _contract_for(pool, roster)
    # Same league, but our team block is one player short of the name we trade.
    team = dict(contract["sleeper"]["teams"][0])
    team["players"] = [n for n in roster if n != mine]
    context = build_capacity_context(contract, None, team, roster_settings=SETTINGS)

    result = find_angles(
        rows,
        mine,
        "owner-1",
        teams,
        min_my_gain_pct=1.0,
        max_market_gain_pct=100.0,
        capacity_context=context,
    )
    assert result["candidates"]
    for candidate in result["candidates"]:
        capacity = candidate["rosterCapacity"]
        # The REQUEST still asked to send one player away...
        assert capacity["outgoing"] == 1
        # ...but the roster does not hold him, so no spot is freed and the
        # discrepancy is published rather than corrected away.
        assert capacity["outgoingNotOnRoster"] == 1
        assert capacity["incoming"] == 1
        assert capacity["sizeAfter"] == ROSTER_SIZE  # 33 held + 1 incoming
        assert any("free no spot" in n for n in capacity["notes"])


def test_angle_packages_offer_mode_is_not_filtered_by_capacity(angle_setup):
    from src.trade.angle import find_angle_packages

    pool, roster, context, rows, teams = angle_setup
    offer = roster[:2]

    kwargs = dict(min_my_gain_pct=1.0, max_market_gain_pct=50.0, include_idp=True)
    without = find_angle_packages(rows, offer, "owner-1", teams, **kwargs)
    with_capacity = find_angle_packages(
        rows, offer, "owner-1", teams, capacity_context=context, **kwargs
    )
    assert without["candidates"], "fixture produced no counter-packages"
    assert len(without["candidates"]) == len(with_capacity["candidates"])
    assert [[p["name"] for p in c["players"]] for c in without["candidates"]] == [
        [p["name"] for p in c["players"]] for c in with_capacity["candidates"]
    ]

    for plain, annotated in zip(without["candidates"], with_capacity["candidates"]):
        assert plain["rosterCapacity"]["unavailable"] == "no_capacity_context"
        capacity = annotated["rosterCapacity"]
        assert capacity["outgoing"] == len(offer)
        assert capacity["incoming"] == len(annotated["players"])
        assert capacity["sizeAfter"] == ROSTER_SIZE - len(offer) + len(annotated["players"])


def test_angle_packages_n_plus_one_reports_its_forced_drop(angle_setup):
    """The reachable forced-drop shape, and the value it costs.

    A size-N+1 counter-package into a roster at the cap is over by exactly one,
    and the block must name the release rather than presenting the incoming
    player as free.
    """
    from src.trade.angle import find_angle_packages

    pool, roster, context, rows, teams = angle_setup
    offer = roster[:2]
    result = find_angle_packages(
        rows,
        offer,
        "owner-1",
        teams,
        min_my_gain_pct=1.0,
        max_market_gain_pct=50.0,
        include_idp=True,
        capacity_context=context,
    )
    over = [c for c in result["candidates"] if len(c["players"]) > len(offer)]
    assert over, "fixture produced no N+1 counter-packages — the forced-drop path is untested"
    for candidate in over:
        capacity = candidate["rosterCapacity"]
        excess = len(candidate["players"]) - len(offer)
        assert capacity["overLimitAfter"] == excess
        assert len(capacity["forcedDrops"]) == excess
        assert capacity["forcedDropValue"] is not None
        assert capacity["requiresDrops"] is True


def test_angle_packages_acquire_mode_is_not_filtered_by_capacity(angle_setup):
    from src.trade.angle import find_acquisition_packages

    pool, roster, context, rows, teams = angle_setup
    rostered = set(roster)
    desired = [a.name for a in pool if a.name not in rostered][:2]
    assert len(desired) == 2

    kwargs = dict(min_my_gain_pct=1.0, max_market_gain_pct=50.0, include_idp=True)
    without = find_acquisition_packages(rows, desired, "owner-1", teams, **kwargs)
    with_capacity = find_acquisition_packages(
        rows, desired, "owner-1", teams, capacity_context=context, **kwargs
    )
    assert without["candidates"], "fixture produced no acquisition packages"
    assert len(without["candidates"]) == len(with_capacity["candidates"])

    for plain, annotated in zip(without["candidates"], with_capacity["candidates"]):
        assert plain["rosterCapacity"]["unavailable"] == "no_capacity_context"
        capacity = annotated["rosterCapacity"]
        # Mirror image: the DESIRED side comes in, the candidate goes out.
        assert capacity["incoming"] == len(desired)
        assert capacity["outgoing"] == len(annotated["players"])
        assert capacity["sizeAfter"] == ROSTER_SIZE - len(annotated["players"]) + len(desired)


def test_angle_without_a_context_says_so_rather_than_omitting_the_block(angle_setup):
    """Named, not silent — same rule as suggestions, on all three angle modes."""
    from src.trade.angle import find_acquisition_packages, find_angle_packages, find_angles

    pool, roster, _context, rows, teams = angle_setup
    rostered = set(roster)
    desired = [a.name for a in pool if a.name not in rostered][:2]

    a = find_angles(
        rows,
        _cheapest_rostered(pool, roster),
        "owner-1",
        teams,
        min_my_gain_pct=1.0,
        max_market_gain_pct=100.0,
    )
    b = find_angle_packages(
        rows, roster[:2], "owner-1", teams, min_my_gain_pct=1.0, max_market_gain_pct=50.0
    )
    c = find_acquisition_packages(
        rows, desired, "owner-1", teams, min_my_gain_pct=1.0, max_market_gain_pct=50.0
    )
    for result in (a, b, c):
        for candidate in result["candidates"]:
            assert candidate["rosterCapacity"]["unavailable"] == "no_capacity_context"


def test_angle_picks_do_not_consume_a_roster_spot(angle_setup):
    """A pick in a counter-package must not count against the cap.

    Verified in the owner (``roster_capacity``) against the live league; pinned
    here because Angle's pool CAN contain pick rows and the filtering happens in
    the adapter this module hands the owner.
    """
    from src.trade.angle import _capacity_block

    _pool_unused, _roster, context, _rows, _teams = angle_setup
    block = _capacity_block(
        context,
        incoming=[
            {"name": "2027 Round 1", "position": "PICK"},
            {"name": "2027 Round 2", "position": "PICK"},
        ],
        outgoing=[],
    )
    assert block["incoming"] == 0
    assert block["sizeAfter"] == ROSTER_SIZE
    assert block["overLimitAfter"] == 0
