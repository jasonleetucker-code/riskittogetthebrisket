"""The bridge owner's per-family shared-market ladders (Signals IDP, 2026-10-04).

A source that ranks only WITHIN a family ("LB3") is translated by asking where
the third LB sits on the shared market — never by ordering families against
each other.  The family slice must therefore be exactly the overall ladder
sliced by family: same ordering, same rescale, same blend.
"""

from __future__ import annotations

from src.bridges import CARDINAL, QUALIFIED, BridgeDescriptor, assess_bridges
from src.bridges.ladder import build_bridge_ladder

OFFENSE = frozenset({"QB", "RB", "WR", "TE"})
IDP = frozenset({"DL", "LB", "DB"})


def _row(name: str, position: str, **values: float) -> dict:
    return {"displayName": name, "position": position, "canonicalSiteValues": dict(values)}


def _descriptor(key: str, family: str) -> BridgeDescriptor:
    return BridgeDescriptor(
        bridge_key=key,
        display_name=key,
        family=family,
        kind=CARDINAL,
        offense_keys=(f"{key}Off",),
        idp_keys=(f"{key}Idp",),
        comparability=QUALIFIED,
        comparability_evidence="measured shared scale",
    )


def _board() -> list[dict]:
    # Combined order on "a": QB(100) LB1(90) RB(80) DL1(70) DB1(60) WR(50) LB2(40) DL2(30)
    return [
        _row("Q", "QB", aOff=100.0, bOff=100.0),
        _row("R", "RB", aOff=80.0, bOff=90.0),
        _row("W", "WR", aOff=50.0, bOff=40.0),
        _row("LB one", "LB", aIdp=90.0, bIdp=70.0),
        _row("DL one", "DL", aIdp=70.0, bIdp=95.0),
        _row("DB one", "DB", aIdp=60.0, bIdp=60.0),
        _row("LB two", "LB", aIdp=40.0, bIdp=30.0),
        _row("DL two", "DL", aIdp=30.0, bIdp=20.0),
    ]


def _ladder(descriptors, limit=None):
    assessments = assess_bridges(
        descriptors, _board(), offense_positions=OFFENSE, idp_positions=IDP
    )
    return build_bridge_ladder(
        assessments, _board(), offense_positions=OFFENSE, idp_positions=IDP, limit=limit
    )


def test_a_family_ladder_is_the_combined_rank_of_that_familys_players():
    lad = _ladder([_descriptor("a", "fa")])
    assert lad.ladder == (2, 4, 5, 7, 8)
    assert lad.family_ladder("LB") == (2, 7)
    assert lad.family_ladder("DL") == (4, 8)
    assert lad.family_ladder("DB") == (5,)


def test_the_family_slices_partition_the_overall_ladder_with_one_bridge():
    lad = _ladder([_descriptor("a", "fa")])
    merged = sorted(r for fam in ("DL", "LB", "DB") for r in lad.family_ladder(fam))
    assert tuple(merged) == lad.ladder


def test_an_unpriced_family_is_absent_not_rank_one():
    board = [r for r in _board() if r["position"] != "DB"]
    assessments = assess_bridges(
        [_descriptor("a", "fa")], board, offense_positions=OFFENSE, idp_positions=IDP
    )
    lad = build_bridge_ladder(assessments, board, offense_positions=OFFENSE, idp_positions=IDP)
    assert lad.family_ladder("DB") == ()
    assert "DB" not in lad.position_ladders


def test_no_usable_bridge_means_no_family_ladder():
    lad = build_bridge_ladder([], _board(), offense_positions=OFFENSE, idp_positions=IDP)
    assert lad.position_ladders == {} and lad.family_ladder("LB") == ()


def test_two_bridges_blend_each_family_like_the_overall_ladder():
    one = _ladder([_descriptor("a", "fa")], limit=1)
    two = _ladder([_descriptor("a", "fa"), _descriptor("b", "fb")])
    # Bridge "b" ranks DL one first among IDPs; the blended family slice
    # moves with it while staying monotone within the family.
    assert two.family_ladder("DL")[0] <= one.family_ladder("DL")[0]
    for fam in ("DL", "LB", "DB"):
        ranks = two.family_ladder(fam)
        assert list(ranks) == sorted(ranks) and len(set(ranks)) == len(ranks)
    assert two.to_dict()["familyDepths"] == {"DB": 1, "DL": 2, "LB": 2}
