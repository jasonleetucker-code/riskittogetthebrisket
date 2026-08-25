"""C2-U1 / V1-27 §10 item 3 — a starter-neutral trade moves no starter.

WHY THIS FILE EXISTS
────────────────────
``docs/lineup/C2_U1_CANONICAL_LINEUP.md`` §10 item 3 reads:

    ``/api/trade/simulate`` returns a ``teamImpact`` block whose
    ``starterDelta`` is unchanged for trades that change no starter.

§10a recorded it **BLOCKED-EXTERNAL** — "401 without a session". That is
true of the HTTP probe and only of the HTTP probe. The *property* it
was probing is pure Python: ``team_impact.compute`` derives
``starterCount`` from ``project_starters``, which calls the canonical
owner ``src/ros/lineup.py::assign_lineup``. Nothing about that needs a
deployed server, and a census at `131abf9f9` found the property pinned
**nowhere** — the existing ``starterDelta`` assertions all check that it
*moves* (``< 0``, position absent), never that it *stays put*.

So the transport half stays L3 and belongs to Claude 5's production run.
The invariant half is closed here, deterministically, at L1.

WHAT "STARTER-NEUTRAL" MEANS, PRECISELY
───────────────────────────────────────
Not "a trade that changes nothing" — that would be vacuous, and an
empty trade already has its own test. The interesting case is a trade
that **moves real value** while leaving the starting lineup's shape
untouched: swap a deep-bench player for a different deep-bench player
at the same position, where neither can crack the lineup. Value moves;
starters do not.

That case is what separates starter accounting from value accounting.
A regression that made ``starterCount`` track *value* rather than
*seats* would still pass every existing test in the repo and would fail
the first assertion below.
"""

from __future__ import annotations

from src.trade.team_impact import compute

#: A saturated lineup: every starting slot has a clearly better player
#: than the bench pieces the trade moves, so the solve cannot prefer a
#: traded asset. No flex — flex is exercised by ``test_canonical_lineup``
#: and would only add a second reason for a seat to move.
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
    }


def _saturated_roster() -> list[dict]:
    """Starters comfortably above anything the trades below move."""
    return [
        _asset("QB Starter", "QB", 9000),
        _asset("RB Starter A", "RB", 8800),
        _asset("RB Starter B", "RB", 8600),
        _asset("WR Starter A", "WR", 8400),
        _asset("WR Starter B", "WR", 8200),
        _asset("TE Starter", "TE", 8000),
        # Deep bench — none of these can displace a starter above.
        _asset("WR Bench Out", "WR", 300),
        _asset("RB Bench Filler", "RB", 250),
    ]


def _starter_delta(*, incoming: list[dict], outgoing: list[dict]) -> dict[str, int]:
    before = _saturated_roster()
    out_names = {a["name"] for a in outgoing}
    after = [a for a in before if a["name"] not in out_names] + incoming
    # Real equity, not a placeholder: these tests assert that a NONZERO
    # value swing still moves no seat, so handing the engine a fake 0
    # would quietly remove the thing being tested.
    equity = sum(a["value"] for a in incoming) - sum(a["value"] for a in outgoing)
    impact = compute(
        before_assets=before,
        after_assets=after,
        receiving=incoming,
        sending=outgoing,
        equity=equity,
        roster_settings=SETTINGS,
    )
    assert impact is not None, "roster_settings must yield starter slots"
    return impact["starterDelta"]


def test_bench_for_bench_swap_moves_no_starter():
    """The headline property: value moves, seats do not.

    ``WR Bench Out`` (300) leaves, ``WR Bench In`` (900) arrives — a 3x
    value swing at the same position, both far below the WR starters.
    Every ``starterDelta`` entry must be exactly 0.
    """
    delta = _starter_delta(
        incoming=[_asset("WR Bench In", "WR", 900)],
        outgoing=[_asset("WR Bench Out", "WR", 300)],
    )
    assert delta, "starterDelta must be populated, not empty — 0-of-0 is not a pass"
    assert all(v == 0 for v in delta.values()), f"a bench-for-bench swap moved a starter: {delta}"


def test_cross_position_bench_swap_moves_no_starter():
    """Same property across positions.

    ``WR Bench Out`` leaves and an RB arrives. Both rosters still seat
    2 WR and 2 RB from their own starters, so no position's seat count
    may move — even though the roster's positional *composition* did.
    """
    delta = _starter_delta(
        incoming=[_asset("RB Bench In", "RB", 700)],
        outgoing=[_asset("WR Bench Out", "WR", 300)],
    )
    assert delta, "starterDelta must be populated, not empty"
    assert all(
        v == 0 for v in delta.values()
    ), f"a cross-position bench swap moved a starter: {delta}"


def test_same_position_starter_swap_moves_no_seat_though_value_moves():
    """The discriminating case, and the reason this file is not just the
    two tests above.

    Swapping the QB starter for a *different, cheaper* QB changes who
    occupies the seat and moves real value **through the starting
    lineup** — but the league still starts exactly one QB, so the seat
    count is unchanged and every ``starterDelta`` entry must be 0.

    This case is what a value-tracking regression cannot survive. The
    two bench swaps above cannot catch that class on their own: a
    bench-for-bench trade moves no starter *value* either, so an
    implementation that wrongly reported value would still print 0 and
    look correct. Established by mutation, not by argument — see the
    file's own record in the V1-27 handoff.
    """
    delta = _starter_delta(
        incoming=[_asset("QB Replacement", "QB", 8500)],
        outgoing=[_asset("QB Starter", "QB", 9000)],
    )
    assert delta, "starterDelta must be populated, not empty"
    assert all(v == 0 for v in delta.values()), (
        "a same-position starter swap changed a SEAT count; starterDelta is "
        f"counting something other than seats: {delta}"
    )


def test_the_fixture_can_actually_move_a_starter():
    """Positive control — without this the tests above are vacuous.

    If the fixture were built so that NO trade could ever move a
    starter, both assertions above would pass for the wrong reason.
    Trading a real starter out for a deep-bench player must move the
    count, proving the fixture is sensitive to the thing being measured.
    """
    delta = _starter_delta(
        incoming=[_asset("WR Scrub In", "WR", 100)],
        outgoing=[_asset("QB Starter", "QB", 9000)],
    )
    assert (
        delta.get("QB") == -1
    ), f"trading the only QB starter away must drop QB starters by 1, got {delta}"
