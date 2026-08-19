"""C5-ROS-01 — the seasonal lane must SAY when it is leaning on dynasty evidence.

THE BOUNDARY, AND WHICH HALF WAS MISSING
----------------------------------------
CLAUDE.md keeps two evidence domains apart. The dynasty direction is
already enforced hard: every entry in ``data_contract._RANKING_SOURCES``
must declare ``game_type: DYNASTY`` with evidence, the gate runs at
import, and ``tests/sources/test_game_type_gate_red.py`` pins it. A
redraft board cannot reach canonical dynasty value.

The seasonal direction had no equivalent, and the traffic runs the other
way. ``src/ros/parse.py`` grants a *"Dynasty proxy that's not ROS but
still relevant"* multiplier to any source with ``is_dynasty and not
is_ros``, so a long-horizon dynasty ranking answers a rest-of-season
question. Measured on the live board 2026-08-19:

* ``fantasyProsRosSf``  — ``is_ros=False, is_dynasty=True``, weight 0.85
* ``fantasyProsRosIdp`` — ``is_ros=False, is_dynasty=True``, weight 1.05

two of five sources, **and both are keyed ``...Ros...``**, which is the
trap: the name says rest-of-season and the flag says dynasty.

What that buys, on 1,041 live players:

| | |
|---|---|
| players with ANY dynasty-board contribution | 720 (69.2%) |
| players priced **only** by dynasty boards | 188 (18.1%) |
| share of contributing weight from dynasty boards | 31.4% |

``fantasyProsRosIdp`` is also the **only** ``is_idp`` source in the lane,
so every IDP player's ROS value rests on a dynasty board.

WHAT THIS FIXES, AND WHAT IT DELIBERATELY DOES NOT
--------------------------------------------------
It does **not** exclude the dynasty proxies. Doing so would leave 188
players unpriced and delete the lane's only IDP evidence — removing
working functionality to satisfy a rule, when the rule's actual
requirement is that the two domains stay *distinguishable*. Nor does it
change any ``rosValue``; the arithmetic is untouched and pinned below.

What it ends is the **silence**. A rest-of-season number resting wholly
on long-horizon dynasty rankings is a different claim from one resting
on rest-of-season evidence, and a consumer could not tell them apart.
Every row now carries ``evidenceBasis`` naming which it is.

Same posture as ``pickValueProvenance`` on pick rows and ``cardBasis`` on
season blocks: the value is published, and what it rests on travels with
it.
"""

from __future__ import annotations

from src.ros import sources as ros_sources
from src.ros.aggregate import RankedRow, SourceSnapshot, aggregate

LEAGUE = {"is_superflex": True, "is_te_premium": True, "is_2qb": False, "is_idp": True}

#: A fixed stamp, matching ``test_aggregate``'s convention. ``aggregate``
#: takes no ``now`` hook, so freshness decays against the wall clock —
#: every assertion below is a label or a relative comparison for exactly
#: that reason, never an absolute weight.
_SCRAPED_AT = "2026-04-28T11:00:00+00:00"


def _snap(key: str, *, is_ros: bool, is_dynasty: bool, names: list[str], weight: float = 1.0):
    return SourceSnapshot(
        source_key=key,
        base_weight=weight,
        is_ros=is_ros,
        is_dynasty=is_dynasty,
        is_te_premium=True,
        is_superflex=True,
        is_2qb=False,
        is_idp=False,
        status="ok",
        scraped_at=_SCRAPED_AT,
        player_count=len(names),
        has_valid_cache=True,
        rows=[
            RankedRow(canonical_name=n, position="WR", rank=i, total_ranked=len(names))
            for i, n in enumerate(names, start=1)
        ],
    )


def _by_name(rows):
    return {r["canonicalName"]: r for r in rows}


# ── 1. The registry fact this unit exists for ───────────────────────


def test_the_registry_really_does_admit_dynasty_boards():
    """Non-vacuity for everything below. If the lane stopped carrying
    dynasty proxies, these tests would pass by describing nothing."""
    breaching = [
        s["key"] for s in ros_sources.ROS_SOURCES if not s.get("is_ros") and s.get("is_dynasty")
    ]
    assert breaching, (
        "no dynasty-flagged source in the ROS lane any more — if that is "
        "deliberate, this suite and the parse.py proxy branch should go too"
    )
    # And the naming trap is real, so it is pinned rather than remembered.
    assert any("Ros" in k for k in breaching), breaching


# ── 2. The basis is stamped ─────────────────────────────────────────


def test_a_row_priced_only_by_dynasty_boards_says_so():
    rows = aggregate(
        [_snap("dynProxy", is_ros=False, is_dynasty=True, names=["alpha"])],
        league=LEAGUE,
    )
    row = _by_name(rows)["alpha"]
    assert row["evidenceBasis"] == "dynasty_proxy_only", row.get("evidenceBasis")


def test_a_row_priced_only_by_ros_boards_says_so():
    rows = aggregate(
        [_snap("realRos", is_ros=True, is_dynasty=False, names=["alpha"])],
        league=LEAGUE,
    )
    assert _by_name(rows)["alpha"]["evidenceBasis"] == "rest_of_season"


def test_a_mixed_row_is_named_mixed_and_carries_the_share():
    rows = aggregate(
        [
            _snap("realRos", is_ros=True, is_dynasty=False, names=["alpha"]),
            _snap("dynProxy", is_ros=False, is_dynasty=True, names=["alpha"]),
        ],
        league=LEAGUE,
    )
    row = _by_name(rows)["alpha"]
    assert row["evidenceBasis"] == "mixed"
    share = row["dynastyProxyWeightShare"]
    assert 0.0 < share < 1.0, share


def test_the_share_is_zero_and_one_at_the_ends():
    """The share must be usable as a number, not only as a label."""
    only_ros = aggregate(
        [_snap("realRos", is_ros=True, is_dynasty=False, names=["alpha"])], league=LEAGUE
    )
    only_dyn = aggregate(
        [_snap("dynProxy", is_ros=False, is_dynasty=True, names=["alpha"])], league=LEAGUE
    )
    assert _by_name(only_ros)["alpha"]["dynastyProxyWeightShare"] == 0.0
    assert _by_name(only_dyn)["alpha"]["dynastyProxyWeightShare"] == 1.0


# ── 3. Nothing about the value moved ────────────────────────────────


def test_the_stamp_changes_no_value():
    """This unit is about what the number CLAIMS, not what it is.

    The dynasty proxy must still vote with exactly the weight it had.
    Asserted by making it DISAGREE and checking the disagreement lands,
    rather than against a remembered constant — a constant would also
    pass if the proxy were silently dropped and the remaining source
    happened to reproduce it.
    """
    ros = _snap("realRos", is_ros=True, is_dynasty=False, names=["alpha", "beta", "gamma"])
    # The proxy ranks gamma top and alpha last — the exact opposite end.
    proxy = _snap("dynProxy", is_ros=False, is_dynasty=True, names=["gamma", "beta", "alpha"])

    with_proxy = _by_name(aggregate([ros, proxy], league=LEAGUE))
    without = _by_name(aggregate([ros], league=LEAGUE))

    assert all(r["sourceCount"] == 2 for r in with_proxy.values()), "both sources must vote"
    # gamma is last on the ROS board and first on the proxy: if the proxy
    # is counted, gamma gains and alpha loses relative to ROS-only.
    assert with_proxy["gamma"]["rosValue"] > without["gamma"]["rosValue"]
    assert with_proxy["alpha"]["rosValue"] < without["alpha"]["rosValue"]
    # ...and every one of them is stamped mixed, not quietly excluded.
    assert {r["evidenceBasis"] for r in with_proxy.values()} == {"mixed"}


def test_a_source_that_is_neither_ros_nor_dynasty_is_not_a_dynasty_proxy():
    """The predicate is ``is_dynasty and not is_ros``, NOT ``not is_ros``.

    The lane carries a third kind: ``ffc2qbAdp`` is live with
    ``is_ros=False, is_dynasty=False`` — an ADP feed, which is neither a
    rest-of-season board nor a dynasty one. Calling it a dynasty proxy
    would be a different false claim from the one this unit fixes, and
    ``parse.effective_source_weight`` does not price it as one either.

    Added because the mutation that widens the predicate passed every
    other test in this file.
    """
    rows = aggregate(
        [_snap("adpFeed", is_ros=False, is_dynasty=False, names=["alpha"])],
        league=LEAGUE,
    )
    row = _by_name(rows)["alpha"]
    assert row["dynastyProxyWeightShare"] == 0.0
    assert row["evidenceBasis"] == "rest_of_season", (
        "an ADP feed is not a dynasty proxy; mislabelling it is a "
        "different false claim, not a safer one"
    )
    assert row["contributors"][0]["dynastyProxy"] is False


def test_the_live_registry_contains_all_three_kinds():
    """Non-vacuity for the test above: it only guards anything while a
    neither-flag source actually exists in the lane."""
    kinds = {(bool(s.get("is_ros")), bool(s.get("is_dynasty"))) for s in ros_sources.ROS_SOURCES}
    assert (True, False) in kinds, "no real ROS board in the lane"
    assert (False, True) in kinds, "no dynasty proxy in the lane"
    assert (False, False) in kinds, "no neither-kind source; the predicate test is moot"


def test_the_contributor_rows_name_which_source_was_the_proxy():
    """The share is a summary; a reader auditing one player needs to see
    WHICH source it came from without re-deriving it from the registry."""
    rows = aggregate(
        [
            _snap("realRos", is_ros=True, is_dynasty=False, names=["alpha"]),
            _snap("dynProxy", is_ros=False, is_dynasty=True, names=["alpha"]),
        ],
        league=LEAGUE,
    )
    contribs = {c["sourceKey"]: c["dynastyProxy"] for c in _by_name(rows)["alpha"]["contributors"]}
    assert contribs == {"realRos": False, "dynProxy": True}
