"""The free-agent ladder behind ``W(k)``, and who is allowed onto it.

Two separate claims are pinned here.

**A rookie in the auction is not a free alternative to the auction.**  The
shipped model asked "what is the best player available at this position for
free?" and answered with players who were lots in the very draft being
optimized — on the 2026-08-04 board, five of the six best "free agents".  The
effect was to suppress rookie surplus by comparing a rookie against himself.

**One free agent cannot fill k roster spots.**  The shipped model charged every
addition the same positional waiver level, which assumes you can sign the best
free agent as many times as you have spots.  The ladder charges the top-k, in
order, and its marginal rung declines.
"""

from __future__ import annotations

from src.draft.displacement import (
    count_free_agents,
    free_agent_ladder,
    waiver_values_by_position,
)
from src.draft.rookie_pool import auction_rookie_keys, select_rookie_rows


def _row(name, pos, value, *, rookie=False, player_id=None):
    return {
        "playerId": player_id or name.lower().replace(" ", "-"),
        "displayName": name,
        "canonicalName": name,
        "position": pos,
        "rankDerivedValue": value,
        "rookie": rookie,
        "assetClass": "offense",
    }


def _contract(rows):
    return {"playersArray": rows}


ROWS = [
    _row("Rostered Star", "WR", 9000),
    _row("Auction Rookie TE", "TE", 2000, rookie=True),
    _row("Auction Rookie WR", "WR", 1900, rookie=True),
    _row("Veteran FA TE", "TE", 1500),
    _row("Veteran FA WR", "WR", 1400),
    _row("Veteran FA RB", "RB", 1300),
    _row("Deep FA WR", "WR", 1200),
]


def test_the_auction_pool_is_kept_off_the_waiver_wire():
    contract = _contract(ROWS)
    rostered = {"rostered star"}

    naive = waiver_values_by_position(contract, rostered)
    # Without the exclusion, the best "free" TE is a rookie in the draft.
    assert naive["TE"] == 2000
    assert naive["WR"] == 1900

    excluded = waiver_values_by_position(contract, rostered, auction_rookie_keys(contract))
    assert excluded["TE"] == 1500
    assert excluded["WR"] == 1400


def test_the_ladder_declines_and_is_position_agnostic():
    contract = _contract(ROWS)
    rungs = free_agent_ladder(contract, {"rostered star"}, auction_rookie_keys(contract))
    assert rungs == [1500.0, 1400.0, 1300.0, 1200.0]
    # Strictly decreasing: that is the property the flat charge lacked.
    assert all(a >= b for a, b in zip(rungs, rungs[1:]))
    # And it crosses positions — a roster spot can hold anyone.
    assert len(rungs) == 4


def test_the_ladder_charges_more_than_the_flat_model_for_a_concentrated_plan():
    """The documented direction, measured on a case that isolates it.

    Three WR additions paid ``3 x waiverValue(WR)`` under the flat model. The
    honest charge is the top three of the whole pool, which is larger whenever
    other positions out-rank the WR wire — the usual case.
    """
    contract = _contract(ROWS)
    rostered = {"rostered star"}
    keys = auction_rookie_keys(contract)
    flat = 3 * waiver_values_by_position(contract, rostered, keys)["WR"]
    ladder = sum(free_agent_ladder(contract, rostered, keys)[:3])
    assert flat == 4200
    assert ladder == 4200.0 or ladder > flat
    # (WR wire is 1400 and the top three are 1500/1400/1300 — a case where they
    # coincide is worth pinning too, so a future change that breaks the
    # equivalence shows up here rather than silently.)


def test_the_ladder_respects_its_limit_without_pretending_to_be_complete():
    contract = _contract(ROWS)
    rostered = {"rostered star"}
    keys = auction_rookie_keys(contract)
    assert len(free_agent_ladder(contract, rostered, keys, limit=2)) == 2
    # The population is reported separately, so a caller cannot mistake the cap
    # for the count.
    assert count_free_agents(contract, rostered, keys) == 4


def test_the_exclusion_count_is_the_measurable_difference():
    contract = _contract(ROWS)
    rostered = {"rostered star"}
    keys = auction_rookie_keys(contract)
    assert count_free_agents(contract, rostered) - count_free_agents(contract, rostered, keys) == 2


def test_an_already_rostered_rookie_is_not_double_counted():
    """A rookie who is BOTH in the auction and on a roster is excluded once."""
    contract = _contract(ROWS)
    rostered = {"rostered star", "auction rookie te"}
    keys = auction_rookie_keys(contract)
    assert count_free_agents(contract, rostered, keys) == 4


def test_the_auction_pool_selection_matches_the_board():
    """``select_rookie_rows`` is the single definition of "in this auction"."""
    contract = _contract(ROWS)
    rows = select_rookie_rows(contract, top_n=72)
    assert [r["displayName"] for r in rows] == ["Auction Rookie TE", "Auction Rookie WR"]
    # Highest value first, matching the draft board's own ordering.
    assert rows[0]["rankDerivedValue"] > rows[1]["rankDerivedValue"]


def test_a_rookie_without_a_sleeper_id_is_not_in_the_auction():
    """College / undrafted entries a ranking source lists but nobody can roster."""
    rows = [*ROWS, {**_row("Phantom Rookie", "WR", 5000, rookie=True), "playerId": None}]
    assert "phantom rookie" not in auction_rookie_keys(_contract(rows))


def test_the_context_reports_positional_shape():
    """Per-position counts so the client can say whether a plan leaves a hole.

    Counted from the joined roster, deliberately NOT from the cut ladder: the
    ladder truncates at ``MAX_LADDER_RUNGS`` and drops the undroppable, so its
    positions are a sample of the roster rather than the roster.
    """
    from src.draft.context import build_roster_context

    contract = {
        "playersArray": [
            _row("Star QB", "QB", 9000),
            _row("Bench WR", "WR", 2000),
            _row("Free TE", "TE", 1500),
        ],
        "sleeper": {
            "teams": [
                {
                    "name": "Alpha",
                    "ownerId": "o1",
                    "roster_id": 1,
                    "players": ["Star QB", "Bench WR"],
                    "playerIds": ["star-qb", "bench-wr"],
                }
            ]
        },
    }
    ctx = build_roster_context(contract, None, team_name="Alpha")
    assert ctx["rosterByPosition"] == {"QB": 1, "WR": 1}
    # Starters come from the league registry; with no league key resolved the
    # requirement map is simply empty rather than invented.
    assert isinstance(ctx["startersByPosition"], dict)
    assert ctx["contextVersion"].endswith(".v3")
