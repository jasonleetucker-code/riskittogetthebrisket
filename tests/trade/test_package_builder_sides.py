"""Package Builder Sending / Receiving — owner directive 2026-10-18 (Batch 2).

Each side is independently Offense / Defense (IDP) / Both, applied to the two
pools BEFORE enumeration in every mode; all nine combinations must work.
Conflicts (a locked or selected player outside Sending, a requested target
outside Receiving or Target Quality, return positions outside Receiving) are
REPORTED — never silently dropped and never overridden.  Picks are never
offense or defense.
"""

from __future__ import annotations

import itertools

import pytest

from src.league_intel.cross_market import MARKET_IDPTC, MARKET_KTC
from src.trade import discovery as disc
from src.trade import finder
from src.trade import package_builder as pb
from src.trade.constraints import resolve_constraints


def _league(mine, theirs):
    """rows: ``(name, pos, board, ktc|None, idptc|None, rank)``."""
    players, rows = {}, []
    for name, pos, board, ktc, idptc, rank in (*mine, *theirs):
        sites = {k: v for k, v in ((MARKET_KTC, ktc), (MARKET_IDPTC, idptc)) if v is not None}
        players[name] = {"_canonicalSiteValues": dict(sites), "position": pos, "_sites": 8}
        rows.append(
            {
                "displayName": name,
                "canonicalName": name,
                "position": pos,
                "rankDerivedValue": board,
                "canonicalSiteValues": dict(sites),
                "assetClass": "player",
                "canonicalConsensusRank": rank,
                "confidenceBucket": "medium",
            }
        )
    teams = [
        {"name": "Us", "ownerId": "1", "players": [m[0] for m in mine]},
        {"name": "Them", "ownerId": "2", "players": [t[0] for t in theirs]},
    ]
    return players, teams, {"playersArray": rows}


MINE = [
    ("Our WR", "WR", 4200, 4600, 4600, 95),
    ("Our RB", "RB", 3000, 3300, 3300, 160),
    ("Our LB", "LB", 3300, None, 3500, 140),
    ("Our DB", "DB", 2600, None, 2800, 230),
]
THEIRS = [
    ("Their WR", "WR", 4600, 4300, 4300, 70),
    ("Their QB", "QB", 4400, 4300, 4300, 80),
    ("Their LB", "LB", 3900, None, 3600, 110),
    ("Their DB", "DB", 2900, None, 2700, 205),
    ("Deep WR", "WR", 1500, 1400, 1400, 420),
]


def _build(mine=MINE, theirs=THEIRS, **kw):
    players, teams, contract = _league(mine, theirs)
    kw.setdefault("use_team_context", False)
    return pb.build_packages(players, "Us", teams, contract=contract, **kw)


def _groups(assets):
    return {disc.player_group(a["position"]) for a in assets if not a.get("isPick")}


@pytest.mark.parametrize(("send", "recv"), list(itertools.product(disc.SCOPES, disc.SCOPES)))
def test_all_nine_sending_receiving_combinations(send, recv):
    out = _build(send_scope=send, receive_scope=recv, max_assets_per_side=2)
    assert out["sides"] == {**out["sides"], "sending": send, "receiving": recv}
    for p in out["packages"]:
        if send != "both":
            assert _groups(p["send"]) <= {send}
        if recv != "both":
            assert _groups(p["receive"]) <= {recv}
    if not out["packages"]:
        assert out.get("noResultReason"), out


def test_filters_shape_both_pools_before_enumeration():
    out = _build(send_scope="defense", receive_scope="offense", max_assets_per_side=1)
    enum = out["diagnostics"]["enumeration"]["Them"]["oneForOne"]
    # The substrate saw only our two defenders and their three offensive players.
    assert enum["ourPoolSize"] == 2
    assert enum["theirPoolSize"] == 3


def test_owner_example_defense_for_offense_top_100_up_to_3():
    """Sending Defense, Receiving Offense, Top 100, up to 3."""
    out = _build(
        send_scope="defense",
        receive_scope="offense",
        max_assets_per_side=3,
        discovery=disc.DiscoveryFilters(quality="top100", sort="most_impactful"),
    )
    assert out["packages"], out
    for p in out["packages"]:
        assert _groups(p["send"]) == {"defense"}
        assert _groups(p["receive"]) == {"offense"}
        assert all(not a["isPick"] for a in p["send"])  # picks only when enabled
        assert p["discovery"]["meetsTargetQuality"] is True
        assert any(a["name"] in ("Their WR", "Their QB") for a in p["receive"])


def test_picks_stay_a_separate_category():
    out = _build(send_scope="defense", receive_scope="offense", allow_picks=True)
    for p in out["packages"]:
        for a in p["send"]:
            assert a["isPick"] or disc.player_group(a["position"]) == "defense"


def test_broad_intersect_specific_and_incompatible_is_explained():
    both = _build(receive_scope="offense", return_positions=frozenset({"WR", "LB"}))
    assert both["sides"]["returnPositionsOutsideReceiving"] == ["LB"]
    assert both["request"]["returnPositions"] == ["WR"]
    for p in both["packages"]:
        assert {a["position"] for a in p["receive"]} <= {"WR"}
    none = _build(receive_scope="offense", return_positions=frozenset({"LB", "DB"}))
    assert none["packages"] == []
    assert none["noResultReason"] == "return_positions_outside_receiving"
    assert "LB" in none["noResultDetail"]


def test_improve_mode_position_outside_receiving_is_explained():
    out = _build(receive_scope="defense", return_positions=frozenset({"QB"}), per_opponent=True)
    assert out["noResultReason"] == "return_positions_outside_receiving"


def test_a_locked_player_outside_sending_is_reported_not_overridden():
    cons = resolve_constraints(refinement={"lock": ["Our WR"], "exclude": []})
    out = _build(send_scope="defense", constraints=cons)
    assert out["packages"] == []
    assert out["noResultReason"] == "locked_player_outside_sending"
    assert "Our WR" in out["noResultDetail"]


def test_selected_outgoing_outside_sending_is_reported():
    out = _build(send_scope="defense", outgoing=["Our WR", "Our LB"])
    assert out["sides"]["selectedOutgoingOutsideSending"] == ["Our WR"]
    for p in out["packages"]:
        assert {a["name"] for a in p["send"]} <= {"Our LB"}
    sell = _build(send_scope="defense", outgoing=["Our WR"], per_opponent=True)
    assert sell["noResultReason"] == "selected_outgoing_outside_sending"


def test_exclude_and_protection_still_apply_inside_the_scope():
    cons = resolve_constraints(
        persistent={"untouchables": ["Our LB"]}, refinement={"lock": [], "exclude": ["Our DB"]}
    )
    out = _build(send_scope="defense", constraints=cons)
    assert out["packages"] == []
    assert out["noResultReason"] == "all_outgoing_assets_constrained"


def test_a_target_outside_receiving_gets_guidance():
    out = _build(target="Their LB", receive_scope="offense")
    assert out["noResultReason"] == "target_outside_receiving"
    assert "Their LB" in out["noResultDetail"]


def test_a_target_outside_target_quality_gets_guidance_never_a_silent_drop():
    out = _build(
        target="Deep WR", discovery=disc.DiscoveryFilters(quality="top250", sort="most_impactful")
    )
    assert out["packages"] == []
    assert out["noResultReason"] == "target_outside_target_quality"
    assert out["targetRank"] == 420 and out["suggestedTargetQuality"] == "top500"
    broadened = _build(
        target="Deep WR", discovery=disc.DiscoveryFilters(quality="top500", sort="most_impactful")
    )
    assert broadened.get("noResultReason") != "target_outside_target_quality"


def test_quality_never_satisfied_by_combined_low_value_pieces():
    out = _build(
        receive_scope="offense",
        max_assets_per_side=3,
        discovery=disc.DiscoveryFilters(quality="top100", sort="most_impactful"),
    )
    for p in out["packages"]:
        assert any(a["name"] in ("Their WR", "Their QB") for a in p["receive"])


def test_legacy_request_is_unchanged():
    a = _build()
    b = _build(send_scope="both", receive_scope="both")

    def strip(r):
        return [
            (p["opponent"], [x["name"] for x in p["send"]], [x["name"] for x in p["receive"]])
            for p in r["packages"]
        ]

    assert strip(a) == strip(b)
    assert "discovery" not in a


def test_deterministic_and_sorted():
    f = disc.DiscoveryFilters(quality="all", sort="most_impactful")
    a = _build(discovery=f, max_assets_per_side=2)
    b = _build(discovery=f, max_assets_per_side=2)
    assert a["packages"] == b["packages"]
    impacts = [p["discovery"]["impact"] for p in a["packages"]]
    assert impacts == sorted(impacts, reverse=True)


def test_unknown_position_is_never_sent_or_received_in_a_narrowed_mode():
    mine = [*MINE, ("Mystery", "", 3000, 3300, 3300, 150)]
    out = _build(mine=mine, send_scope="offense")
    for p in out["packages"]:
        assert all(a["name"] != "Mystery" for a in p["send"])


def test_invalid_scope_is_a_programming_error():
    with pytest.raises(ValueError):
        _build(send_scope="kickers")


def test_pick_target_waives_quality_and_says_so():
    # A pick target brings back no player; the waiver is stated, not hidden.
    pick = finder.Asset("2027 Round 1", "PICK", "", 3000, 3000, is_pick=True)
    assert (
        disc.incoming_quality(pick, disc.DiscoveryFilters(quality="all"), disc.CanonicalIndex({}))[
            0
        ]
        is False
    )
