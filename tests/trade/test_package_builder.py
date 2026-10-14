"""C7-PKGB-01 — Package Builder (owner spec §2.2, inventory 2.6).

Every user constraint must be applied DURING generation; each test has a case
a post-filter or a convenience shortcut would get wrong.
"""

from __future__ import annotations

from pathlib import Path

from src.league_intel.cross_market import MARKET_IDPTC, MARKET_KTC
from src.packages.construction import PackageShape, enumerate_packages
from src.packages.construction import UNCONSTRAINED_OUTGOING
from src.trade import package_builder as pb
from src.trade.constraints import resolve_constraints


def _league(mine, theirs, *, third=()):
    """rows: ``(name, pos, board, ktc|None, idptc|None, nfl_team)``."""
    players, rows = {}, []
    for name, pos, board, ktc, idptc, team in (*mine, *theirs, *third):
        sites = {k: v for k, v in ((MARKET_KTC, ktc), (MARKET_IDPTC, idptc)) if v is not None}
        players[name] = {
            "_canonicalSiteValues": dict(sites),
            "position": pos,
            "team": team,
            "_sites": 8,
        }
        rows.append(
            {
                "displayName": name,
                "canonicalName": name,
                "position": pos,
                "team": team,
                "rankDerivedValue": board,
                "canonicalSiteValues": dict(sites),
                "assetClass": "player",
            }
        )
    teams = [
        {"name": "Us", "ownerId": "1", "players": [m[0] for m in mine]},
        {"name": "Them", "ownerId": "2", "players": [t[0] for t in theirs]},
    ]
    if third:
        teams.append({"name": "Third", "ownerId": "3", "players": [t[0] for t in third]})
    return players, teams, {"playersArray": rows}


def _build(mine, theirs, third=(), **kw):
    players, teams, contract = _league(mine, theirs, third=third)
    kw.setdefault("use_team_context", False)
    return pb.build_packages(players, "Us", teams, contract=contract, **kw)


MINE = [
    ("Our WR", "WR", 4200, 4600, 4600, "CIN"),
    ("Our RB", "RB", 3000, 3300, 3300, "MIN"),
    ("Our LB", "LB", 2500, None, 2900, "DAL"),
]
THEIRS = [
    ("Their WR", "WR", 4100, 4000, 4000, "BUF"),
    ("Their QB", "QB", 4400, 4300, 4300, "KC"),
    ("Their DB", "DB", 2200, None, 2100, "SEA"),
]


def _received(out):
    return [{a["name"] for a in p["receive"]} for p in out["packages"]]


def _sent(out):
    return [{a["name"] for a in p["send"]} for p in out["packages"]]


def test_return_positions_shape_the_pool_before_enumeration():
    out = _build(MINE, THEIRS, return_positions=frozenset({"QB"}))
    assert out["packages"], out
    assert all(r <= {"Their QB"} for r in _received(out))
    # The report proves the filter ran before enumeration: the opponent pool
    # the substrate saw holds only the QB.
    pool_sizes = {
        k: v["oneForOne"]["theirPoolSize"] for k, v in out["diagnostics"]["enumeration"].items()
    }
    assert pool_sizes == {"Them": 1}


def test_multi_selected_positions_are_all_honoured():
    out = _build(MINE, THEIRS, return_positions=frozenset({"QB", "DB"}))
    names = set().union(*_received(out))
    assert names <= {"Their QB", "Their DB"}


def test_desired_target_rides_every_receive_side_and_implies_the_opponent():
    out = _build(MINE, THEIRS, target="Their QB")
    assert out["request"]["opponent"] == "Them"
    assert out["packages"] and all("Their QB" in r for r in _received(out))


def test_target_owned_missing_or_pick_with_picks_off_are_explained():
    assert _build(MINE, THEIRS, target="Our WR")["noResultReason"] == "target_on_your_roster"
    assert _build(MINE, THEIRS, target="Nobody")["noResultReason"] == "target_not_found"


def test_outgoing_selection_limits_what_can_be_sent():
    out = _build(MINE, THEIRS, outgoing=["Our WR"], target="Their QB")
    assert all(s <= {"Our WR"} for s in _sent(out))
    out2 = _build(MINE, THEIRS, outgoing=["Our WR", "Ghost"], target="Their QB")
    assert out2["outgoingNotOnRoster"] == ["Ghost"]


def test_max_package_size_limits_the_shapes_generated_not_the_results():
    out = _build(MINE, THEIRS, max_assets_per_side=1)
    assert out["packages"]
    assert all(len(p["send"]) == 1 and len(p["receive"]) == 1 for p in out["packages"])
    # Applied before enumeration: only the 1-for-1 shape group ran at all.
    for report in out["diagnostics"]["enumeration"].values():
        assert report["asymmetric"]["emitted"] == 0
        assert report["multiPlayer"]["emitted"] == 0


def test_a_canonical_loss_is_never_returned():
    out = _build(MINE, THEIRS)
    assert all(p["canonical"]["direction"] != "opposes" for p in out["packages"])


def test_external_evidence_requires_a_whole_package_qualifying_calculator():
    out = _build(MINE, THEIRS, evidence="external")
    assert all(p["externalQualifies"] for p in out["packages"])
    loose = _build(MINE, THEIRS, evidence="any")
    assert len(loose["packages"]) >= len(out["packages"])


def test_protections_block_outgoing_only_minnesota_example():
    """A Minnesota player is protected outgoing — and stays a valid target."""
    c = resolve_constraints(persistent={"nflTeams": ["MIN"]})
    out = _build(MINE, THEIRS, constraints=c)
    assert out["packages"], out  # never vacuous
    assert all("Our RB" not in s for s in _sent(out))
    theirs = [*THEIRS, ("Their MIN WR", "WR", 4300, 4200, 4200, "MIN")]
    out2 = _build(MINE, theirs, constraints=c, target="Their MIN WR")
    assert out2["packages"] and all("Their MIN WR" in r for r in _received(out2))


def test_lock_appears_in_every_package_and_a_protected_lock_is_refused():
    c = resolve_constraints(refinement={"lock": ["Our LB"]})
    out = _build(MINE, THEIRS, constraints=c)
    assert out["packages"] and all("Our LB" in s for s in _sent(out))
    bad = resolve_constraints(
        persistent={"untouchables": ["Our LB"]}, refinement={"lock": ["Our LB"]}
    )
    assert _build(MINE, THEIRS, constraints=bad)["noResultReason"] == (
        "lock_conflicts_with_protection"
    )


def test_no_return_assets_in_the_selected_positions_is_explained():
    out = _build(MINE, THEIRS, return_positions=frozenset({"TE"}))
    assert out["noResultReason"] == "no_return_assets_in_selected_positions"


def test_return_position_vocabulary_normalises_and_rejects_unknowns():
    fams, unknown = pb.normalize_return_positions(["edge", "S", "picks", "wr"])
    assert fams == frozenset({"DL", "DB", "PICKS", "WR"}) and unknown == []
    assert pb.normalize_return_positions(["K"])[1] == ["K"]
    assert pb.normalize_return_positions(None) == (None, [])


def test_required_receive_is_on_every_receive_side_and_skips_too_small_shapes():
    class A:
        def __init__(self, n, v):
            self.name = self.key = n
            self.asset_id, self.value, self.model_value = n, v, v
            self.position, self.is_pick = "WR", False

    ours = [A("o1", 5000), A("o2", 4000)]
    theirs = [A("t1", 4500), A("t2", 3000)]
    target = A("T", 6000)
    pairs, report = enumerate_packages(
        ours,
        theirs,
        outgoing_policy=UNCONSTRAINED_OUTGOING,
        shapes=[PackageShape(1, 1), PackageShape(1, 2), PackageShape(2, 2)],
        required_receive=[target],
    )
    seen = [tuple(a.name for a in p.receive) for p in pairs]
    assert seen and all("T" in r for r in seen)
    assert report.to_dict()["requiredReceive"] == 1


def test_the_consumer_never_enumerates_packages_itself():
    src = Path(pb.__file__).read_text(encoding="utf-8")
    assert "combinations(" not in src and "itertools" not in src


def test_an_unknown_nfl_team_fails_closed_under_a_team_protection():
    """No NFL team on the asset: a team rule cannot clear it, so it is not sent."""
    players, teams, contract = _league(MINE, THEIRS)
    for p in players.values():
        p.pop("team")
    out = pb.build_packages(
        players,
        "Us",
        teams,
        contract=contract,
        use_team_context=False,
        constraints=resolve_constraints(persistent={"nflTeams": ["MIN"]}),
    )
    assert out["noResultReason"] == "all_outgoing_assets_constrained"


def test_a_target_held_by_another_team_than_the_chosen_one_says_so():
    third = [("Third QB", "QB", 4500, 4300, 4300, "LV")]
    out = _build(MINE, THEIRS, third=third, target="Third QB", opponent="Them")
    assert out["noResultReason"] == "target_not_on_opponent"
    assert out["targetHolders"] == ["Third"]


def test_an_ambiguous_target_is_refused_with_its_holders():
    third = [("Their QB", "QB", 4500, 4300, 4300, "LV")]
    out = _build(MINE, THEIRS, third=third, target="Their QB")
    assert out["noResultReason"] == "target_ambiguous"
    assert out["targetHolders"] == ["Them", "Third"]
    # Naming the team resolves it.
    assert _build(MINE, THEIRS, third=third, target="Their QB", opponent="Third")["packages"]


def test_a_rostered_but_unpriced_target_is_not_reported_missing():
    players, teams, contract = _league(MINE, THEIRS)
    teams[1]["players"].append("Unpriced Rookie")
    out = pb.build_packages(
        players, "Us", teams, contract=contract, use_team_context=False, target="Unpriced Rookie"
    )
    assert out["noResultReason"] == "target_unpriced"
    assert out["targetHolders"] == ["Them"]


def test_owning_the_target_outside_the_outgoing_selection_is_still_yours():
    out = _build(MINE, THEIRS, target="Our RB", outgoing=["Our WR"])
    assert out["noResultReason"] == "target_on_your_roster"


def test_unknown_roster_costs_rank_as_the_merged_heads_worst_known():
    """Review: stand-ins came per opponent, so a lone candidate with an
    unknown release cost ranked as free against charged opponents."""
    third = [("Third WR", "WR", 4150, 4050, 4050, "LV")]

    def capacity_for(opp, give, receive):
        return (None, None) if opp == "Third" else (object(), 400.0)

    out = _build(
        MINE,
        THEIRS,
        third=third,
        use_team_context=True,
        capacity_for=capacity_for,
        max_assets_per_side=1,
    )
    third_pkgs = [p for p in out["packages"] if p["opponent"] == "Third"]
    assert third_pkgs
    for p in third_pkgs:
        assert p["rankingFactors"]["forcedDropCost"] is None
        assert p["rankingImputations"]["forcedDropCost"] > 0


def test_the_search_budget_is_reported_never_silent(monkeypatch):
    monkeypatch.setattr(pb, "SEARCH_BUDGET_PER_SHAPE_GROUP", 1)
    out = _build(MINE, THEIRS)
    assert out["searchTruncated"] is True
