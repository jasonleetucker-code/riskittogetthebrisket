"""A team's rest-of-season strength must declare what its evidence was.

WHY THIS EXISTS SEPARATELY FROM THE PER-PLAYER STAMP
----------------------------------------------------
``aggregate`` now stamps ``evidenceBasis`` on every ROS row (V1-53 /
C5-ROS-01), because 18.1% of the live board is priced by nothing but
dynasty boards standing in for rest-of-season evidence.

A stamp nothing reads is the defect one layer up — the same shape as
``all_scoring_native`` written in one place and consumed in none. So the
first consumer is here, and it is the one that matters: ``team_strength``
is what ``power_v2`` weights at 0.41 (and, in preseason, at **100%** once
every historical component is dropped). If a team's strength is largely
dynasty-derived, the public /league Power tab is showing a dynasty
ranking labelled as a rest-of-season one.

WHAT IS MEASURED, PRECISELY
---------------------------
``dynastyProxyValueShare`` is the share of the roster's PRICED
rest-of-season value that rests on dynasty proxies:

    sum(rosValue * proxyShare) / sum(rosValue)

Weighted by value rather than by headcount, because a team whose
replacement-level 30th man is dynasty-priced is not in the same position
as one whose QB1 is. Unpriced players contribute to neither side — they
are already reported in ``unmappedPlayerCount`` and inventing a basis
for a player we could not price would be the original defect wearing a
new name.
"""

from __future__ import annotations

import pytest

from src.ros import team_strength as ts


def _agg(name, value, *, proxy_share):
    return {
        "canonicalName": name,
        "position": "WR",
        "rosValue": value,
        "confidence": 0.9,
        "dynastyProxyWeightShare": proxy_share,
        "evidenceBasis": (
            "rest_of_season"
            if proxy_share <= 0
            else ("dynasty_proxy_only" if proxy_share >= 1 else "mixed")
        ),
    }


def _team(players):
    return {
        "ownerId": "o1",
        "rosterId": 1,
        "teamName": "Test",
        "players": [
            {"playerId": f"p{i}", "canonicalName": n, "position": "WR"}
            for i, n in enumerate(players, start=1)
        ],
    }


def _build(aggs, players, **kw):
    return ts.compute_team_strength(
        [_team(players)],
        aggregated_players=aggs,
        starter_slots=["WR", "WR", "WR"],
        **kw,
    )


def test_a_roster_priced_entirely_by_dynasty_proxies_says_so():
    rows = _build(
        [_agg("alpha", 80.0, proxy_share=1.0), _agg("beta", 40.0, proxy_share=1.0)],
        ["alpha", "beta"],
    )
    assert rows[0]["dynastyProxyValueShare"] == 1.0
    assert rows[0]["evidenceBasis"] == "dynasty_proxy_only"


def test_a_roster_priced_entirely_by_ros_boards_says_so():
    rows = _build(
        [_agg("alpha", 80.0, proxy_share=0.0), _agg("beta", 40.0, proxy_share=0.0)],
        ["alpha", "beta"],
    )
    assert rows[0]["dynastyProxyValueShare"] == 0.0
    assert rows[0]["evidenceBasis"] == "rest_of_season"


def test_the_share_is_weighted_by_value_not_headcount():
    """A dynasty-priced QB1 and a dynasty-priced 30th man are not the
    same exposure, and a headcount would call them equal."""
    rows = _build(
        [_agg("star", 90.0, proxy_share=1.0), _agg("scrub", 10.0, proxy_share=0.0)],
        ["star", "scrub"],
    )
    share = rows[0]["dynastyProxyValueShare"]
    assert share == pytest.approx(0.9, abs=1e-6), share
    assert rows[0]["evidenceBasis"] == "mixed"

    flipped = _build(
        [_agg("star", 90.0, proxy_share=0.0), _agg("scrub", 10.0, proxy_share=1.0)],
        ["star", "scrub"],
    )
    assert flipped[0]["dynastyProxyValueShare"] == pytest.approx(0.1, abs=1e-6)


def test_unpriced_players_contribute_to_neither_side():
    """They are already reported in ``unmappedPlayerCount``. Inventing a
    basis for a player we could not price is the original defect under a
    new name."""
    rows = _build(
        [_agg("alpha", 80.0, proxy_share=1.0)],
        ["alpha", "ghost"],
    )
    assert rows[0]["unmappedPlayerCount"] == 1
    assert (
        rows[0]["dynastyProxyValueShare"] == 1.0
    ), "the unpriced player must not dilute the share toward 0.5"


def test_a_roster_with_nothing_priced_reports_null_not_zero():
    """0.0 means 'measured, and none of it is dynasty'. Nothing priced
    means we cannot say — and those must not read the same."""
    rows = _build([], ["ghost"])
    assert rows[0]["dynastyProxyValueShare"] is None
    assert rows[0]["evidenceBasis"] == "unpriced"


def test_the_composite_itself_is_unchanged():
    """NON-VACUITY / no-behaviour-change. The basis is a statement ABOUT
    the number, and must not move it."""
    aggs_a = [_agg("alpha", 80.0, proxy_share=1.0), _agg("beta", 40.0, proxy_share=1.0)]
    aggs_b = [_agg("alpha", 80.0, proxy_share=0.0), _agg("beta", 40.0, proxy_share=0.0)]
    a = _build(aggs_a, ["alpha", "beta"])[0]
    b = _build(aggs_b, ["alpha", "beta"])[0]
    assert a["teamRosStrength"] == b["teamRosStrength"]
    assert a["startingLineupScore"] == b["startingLineupScore"]
    assert a["teamRosStrength"] > 0, "fixture must actually score something"
