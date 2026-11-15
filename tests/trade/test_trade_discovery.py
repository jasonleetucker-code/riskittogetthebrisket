"""Trade Finder meaningful discovery — owner directive 2026-10-18.

Target Quality (canonical overall rank, incoming only, at least one incoming
PLAYER per package), Players to target (Offense / Defense / Both through the
canonical position owners), and the Most Impactful ordering — applied during
candidate generation in Golden Upgrades, Package Scan (the finder) and Best
Offers, never as a post-filter, and never relaxing an engine's own rules.

Adversarial where it matters: a pile of low-value pieces must not satisfy
Target Quality through combined value; a missing position must never read as
offense; a missing market value must never read as zero or as a vote.
"""

from __future__ import annotations

import pytest

from src import packages as substrate
from src.league_intel.cross_market import MARKET_IDPTC, MARKET_KTC
from src.trade import best_offers as bo
from src.trade import discovery as disc
from src.trade import finder
from src.trade import golden_upgrades as gu
from src.trade.constraints import resolve_constraints

KTC = MARKET_KTC
IDPTC = MARKET_IDPTC


def _league(mine, theirs, *, extra_teams=()):
    """rows: ``(name, pos, board, ktc|None, idptc|None, rank|None)``."""
    players, rows = {}, []
    for name, pos, board, ktc, idptc, rank in (
        *mine,
        *theirs,
        *(r for _t, rs in extra_teams for r in rs),
    ):
        sites = {k: v for k, v in ((KTC, ktc), (IDPTC, idptc)) if v is not None}
        players[name] = {"_canonicalSiteValues": dict(sites), "position": pos, "_sites": 8}
        row = {
            "displayName": name,
            "canonicalName": name,
            "position": pos,
            "rankDerivedValue": board,
            "canonicalSiteValues": dict(sites),
            "freshnessExcludedSources": [],
            "assetClass": "player",
            "confidenceBucket": "high",
        }
        if rank is not None:
            row["canonicalConsensusRank"] = rank
        rows.append(row)
    teams = [
        {"name": "Us", "ownerId": "1", "players": [m[0] for m in mine]},
        {"name": "Them", "ownerId": "2", "players": [t[0] for t in theirs]},
        *(
            {"name": tname, "ownerId": str(10 + i), "players": [r[0] for r in rs]}
            for i, (tname, rs) in enumerate(extra_teams)
        ),
    ]
    return players, teams, {"playersArray": rows}


def _filters(**kw):
    kw.setdefault("sort", "most_impactful")
    return disc.DiscoveryFilters(**kw)


# ── the vocabulary ────────────────────────────────────────────────────────


@pytest.mark.parametrize("pos", ["QB", "RB", "WR", "TE", "qb", " wr "])
def test_offense_positions(pos):
    assert disc.player_group(pos) == "offense"


@pytest.mark.parametrize(
    "pos",
    [
        "DL",
        "DE",
        "DT",
        "EDGE",
        "ED",
        "IDL",
        "NT",
        "LB",
        "ILB",
        "OLB",
        "MLB",
        "DB",
        "CB",
        "S",
        "SAF",
        "FS",
        "SS",
        "DL/LB",
    ],
)
def test_idp_positions_map_through_the_canonical_owner(pos):
    assert disc.player_group(pos) == "defense"


@pytest.mark.parametrize("pos", ["", None, "K", "T", "WR/DB", "LB/QB", "?"])
def test_missing_or_ambiguous_positions_are_never_offense(pos):
    assert disc.player_group(pos) == "unknown"


def test_picks_are_their_own_category():
    assert disc.player_group("PICK") == "pick"


def test_groups_come_from_the_lineup_owner_not_a_private_table():
    from src.ros.lineup import slot_eligible_positions

    assert disc.offense_positions() == slot_eligible_positions("SUPER_FLEX")
    assert disc.defense_positions() == slot_eligible_positions("IDP_FLEX")


def test_parse_filters_absent_is_legacy_and_present_defaults_to_the_page_defaults():
    assert disc.parse_discovery_filters({}) == (None, None)
    f, err = disc.parse_discovery_filters({"discovery": {}})
    assert err is None
    assert (f.quality, f.scope, f.sort, f.min_incoming_value) == (
        "top250",
        "both",
        "most_impactful",
        None,
    )


@pytest.mark.parametrize(
    "raw",
    [
        {"targetQuality": "top42"},
        {"playersToTarget": "kickers"},
        {"sort": "biggest"},
        {"minIncomingValue": "abc"},
        {"minIncomingValue": 20000},
        {"minIncomingValue": True},
        "top250",
    ],
)
def test_parse_filters_rejects_unknown_values_rather_than_falling_back(raw):
    f, err = disc.parse_discovery_filters({"discovery": raw})
    assert f is None and err["error"] == "invalid_discovery"


def test_broader_levels_for_one_click_expansion():
    assert disc.broader_quality_levels("top250") == ["top500", "all"]
    assert disc.broader_quality_levels("all") == []


# ── Target Quality is per asset, incoming only ────────────────────────────


def test_a_pile_of_low_value_pieces_never_satisfies_quality_through_combined_value():
    """Two rank-400 pieces sum past a top-100 player's value; neither is one."""
    _p, _t, contract = _league(
        [],
        [
            ("Deep A", "WR", 1800, 2000, None, 400),
            ("Deep B", "WR", 1800, 2000, None, 401),
            ("Star", "WR", 3000, 3000, None, 90),
        ],
    )
    index = disc.CanonicalIndex(contract)
    pool = finder.build_asset_pool(
        _p, market_top_n=0, board_values=finder.board_values_from_contract(contract)
    )
    by = {a.name: a for a in pool}
    anchor = disc.quality_anchor(_filters(quality="top100"), index)
    packages, report = substrate.enumerate_packages(
        [by["Star"]],  # our side is irrelevant to the anchor
        [by["Deep A"], by["Deep B"]],
        outgoing_policy=substrate.UNCONSTRAINED_OUTGOING,
        shapes=[substrate.PackageShape(1, 2)],
        receive_anchor=anchor,
    )
    assert list(packages) == []
    assert report.receive_anchor_rejected == 1
    assert report.to_dict()["receiveAnchorRejected"] == 1


def test_a_pick_never_meets_target_quality():
    pick = finder.Asset("2027 Round 1", "PICK", "", 6000, 6000, is_pick=True)
    ok, why = disc.incoming_quality(pick, _filters(quality="all"), disc.CanonicalIndex({}))
    assert (ok, why) == (False, "pick")


def test_minimum_incoming_value_is_a_second_per_asset_gate():
    _p, _t, contract = _league([], [("Mid", "WR", 2500, 2500, None, 120)])
    index = disc.CanonicalIndex(contract)
    a = finder.Asset("Mid", "WR", "", 2500, 2500)
    assert disc.incoming_quality(a, _filters(quality="top250"), index)[0] is True
    assert disc.incoming_quality(a, _filters(quality="top250", min_incoming_value=3000), index) == (
        False,
        "below_min_value",
    )


def test_an_unranked_player_is_outside_every_narrowed_level():
    a = finder.Asset("Off Cap", "WR", "", 1100, 1200)
    assert disc.incoming_quality(a, _filters(quality="top500"), disc.CanonicalIndex({})) == (
        False,
        "unranked",
    )
    assert disc.incoming_quality(a, _filters(quality="all"), disc.CanonicalIndex({}))[0] is True


# ── Golden Upgrades ───────────────────────────────────────────────────────


OWNED_LB = ("Our LB", "LB", 3000, None, 4000, 160)
TARGET_LB_120 = ("Their LB", "LB", 3600, None, 3500, 120)


def _golden(mine, theirs, **kw):
    players, teams, contract = _league(mine, theirs, extra_teams=kw.pop("extra_teams", ()))
    return gu.find_golden_upgrades(players, "Us", teams, contract=contract, **kw)


def test_top_n_changes_golden_eligibility():
    assert _golden([OWNED_LB], [TARGET_LB_120], discovery=_filters(quality="top250"))["upgrades"]
    out = _golden([OWNED_LB], [TARGET_LB_120], discovery=_filters(quality="top100"))
    assert out["upgrades"] == []
    # Applied BEFORE the scorer: the out-of-filter pair was never scored.
    assert out["diagnostics"]["pairs"] == 0
    assert out["discovery"]["report"]["packagesWithoutQualifyingPlayer"] == 1


def test_golden_filtered_empty_says_so_and_offers_broader_levels():
    out = _golden([OWNED_LB], [TARGET_LB_120], discovery=_filters(quality="top100"))
    assert out["noResultReason"] == "no_upgrade_within_target_quality"
    assert out["discovery"]["broaderAvailability"] == {"top250": 1, "top500": 1, "all": 1}
    assert "Top 100" in out["noResultDetail"]
    # The extra availability search does not leak into the published counts.
    assert out["diagnostics"]["pairs"] == 0


def test_golden_eligibility_definition_is_unchanged_by_the_filters():
    """All Players + Both is exactly the legacy candidate set."""
    mine = [OWNED_LB, ("Our WR", "WR", 3000, 4000, None, 150)]
    theirs = [
        TARGET_LB_120,
        ("Their WR", "WR", 3500, 3700, None, 130),
        ("Their S", "DB", 3600, None, 3500, 125),
    ]
    legacy = _golden(mine, theirs)
    filtered = _golden(mine, theirs, discovery=_filters(quality="all"))
    pairs = lambda r: sorted((u["owned"]["name"], u["target"]["name"]) for u in r["upgrades"])  # noqa: E731
    assert pairs(legacy) == pairs(filtered)
    assert legacy["diagnostics"]["golden"] == filtered["diagnostics"]["golden"]


def test_golden_players_to_target():
    mine = [OWNED_LB, ("Our WR", "WR", 3000, 4000, None, 150)]
    theirs = [TARGET_LB_120, ("Their WR", "WR", 3500, 3700, None, 130)]
    off = _golden(mine, theirs, discovery=_filters(quality="all", scope="offense"))
    assert [u["target"]["name"] for u in off["upgrades"]] == ["Their WR"]
    dfn = _golden(mine, theirs, discovery=_filters(quality="all", scope="defense"))
    assert [u["target"]["name"] for u in dfn["upgrades"]] == ["Their LB"]
    both = _golden(mine, theirs, discovery=_filters(quality="all", scope="both"))
    assert sorted(u["target"]["name"] for u in both["upgrades"]) == ["Their LB", "Their WR"]


def test_golden_unknown_position_is_counted_and_never_offense():
    theirs = [("Mystery", "", 3600, 3500, None, 120), ("Their WR", "WR", 3500, 3700, None, 130)]
    mine = [("Our WR", "WR", 3000, 4000, None, 150)]
    out = _golden(mine, theirs, discovery=_filters(quality="all", scope="offense"))
    report = out["discovery"]["report"]
    assert report["unknownPosition"] == 1 and "Mystery" in report["unknownPositionNames"]
    assert all(u["target"]["name"] != "Mystery" for u in out["upgrades"])


def test_golden_shows_ranks_gain_and_why_it_matters():
    [u] = _golden([OWNED_LB], [TARGET_LB_120], discovery=_filters(quality="top250"))["upgrades"]
    assert (u["owned"]["rank"], u["target"]["rank"]) == (160, 120)
    assert u["absoluteGain"] == 600
    assert u["discovery"]["gain"] == 600 and u["discovery"]["gainPct"] == 20.0
    assert u["discovery"]["bestIncoming"]["name"] == "Their LB"
    assert "Their LB" in u["whyItMatters"] and "#120" in u["whyItMatters"]


def test_golden_lock_outside_players_to_target_is_reported_not_overridden():
    mine = [OWNED_LB, ("Our WR", "WR", 3000, 4000, None, 150)]
    theirs = [TARGET_LB_120, ("Their WR", "WR", 3500, 3700, None, 130)]
    cons = resolve_constraints(refinement={"lock": ["Our LB"], "exclude": []})
    out = _golden(
        mine, theirs, constraints=cons, discovery=_filters(quality="all", scope="offense")
    )
    assert out["upgrades"] == []
    assert out["noResultReason"] == "locked_player_outside_players_to_target"
    assert "Our LB" in out["noResultDetail"]


def test_golden_most_impactful_prefers_the_meaningful_target():
    """A deep, high-percentage bench swap must not outrank a real starter."""
    mine = [
        ("Bench LB", "LB", 900, None, 1300, 600),
        ("Starter LB", "LB", 3000, None, 4000, 160),
    ]
    theirs = [
        ("Deep LB", "LB", 1400, None, 1200, 520),  # +55% board, tiny value
        ("Good LB", "LB", 3600, None, 3500, 120),  # +20% board, a top-120 player
    ]
    out = _golden(mine, theirs, discovery=_filters(quality="all"))
    assert out["upgrades"][0]["target"]["name"] == "Good LB"
    pct = _golden(mine, theirs, discovery=_filters(quality="all", sort="percentage_edge"))
    assert pct["upgrades"][0]["target"]["name"] == "Deep LB"  # explicit opt-in still works


def test_golden_is_deterministic():
    mine = [OWNED_LB, ("Our LB2", "LB", 3000, None, 3900, 161)]
    theirs = [TARGET_LB_120, ("Other LB", "LB", 3600, None, 3500, 121)]
    a = _golden(mine, theirs, discovery=_filters(quality="all"))
    b = _golden(mine, theirs, discovery=_filters(quality="all"))
    assert a["upgrades"] == b["upgrades"]


# ── Package Scan (the finder) ─────────────────────────────────────────────


def _scan(players, teams, contract, **kw):
    kw.setdefault("use_team_context", False)
    return finder.find_trades(
        players,
        "Us",
        [t["name"] for t in teams if t["name"] != "Us"]
        + [{"__arbitrageControl": {"equalCountOnly": True}}],
        teams,
        contract=contract,
        **kw,
    )


def _scan_league():
    mine = [
        ("Our WR1", "WR", 4000, 4600, None, 100),
        ("Our WR2", "WR", 2400, 2900, None, 260),
        ("Our LB", "LB", 2500, None, 3000, 240),
    ]
    theirs = [
        ("Their RB", "RB", 4600, 4300, None, 80),
        ("Their WR", "WR", 2900, 2600, None, 300),
        ("Their LB", "LB", 3200, None, 2800, 180),
    ]
    return _league(mine, theirs)


def test_scan_receive_side_always_holds_a_qualifying_player(monkeypatch):
    players, teams, contract = _scan_league()
    seen: list[list[str]] = []
    real = finder._score_trade

    def spy(give, receive):
        seen.append([a.name for a in receive])
        return real(give, receive)

    monkeypatch.setattr(finder, "_score_trade", spy)
    out = _scan(players, teams, contract, discovery=_filters(quality="top250"))
    # The scorer never saw a receive side without a top-250 player.
    assert seen and all(any(n in ("Their RB", "Their LB") for n in recv) for recv in seen)
    for t in out["trades"]:
        assert t["discovery"]["meetsTargetQuality"] is True
    assert out["metadata"]["discovery"]["report"]["packagesWithoutQualifyingPlayer"] > 0


def test_scan_players_to_target_narrows_before_enumeration(monkeypatch):
    players, teams, contract = _scan_league()
    seen: list[str] = []
    real = finder._score_trade

    def spy(give, receive):
        seen.extend(a.position for a in receive)
        return real(give, receive)

    monkeypatch.setattr(finder, "_score_trade", spy)
    _scan(players, teams, contract, discovery=_filters(quality="all", scope="defense"))
    assert seen and set(seen) == {"LB"}


def test_scan_legacy_request_is_unchanged():
    players, teams, contract = _scan_league()
    legacy = _scan(players, teams, contract)
    assert "discovery" not in legacy["metadata"]
    assert all("discovery" not in t for t in legacy["trades"])


def test_scan_all_players_keeps_the_same_qualified_set():
    players, teams, contract = _scan_league()
    key = lambda r: sorted(  # noqa: E731
        (
            tuple(sorted(a["name"] for a in t["give"])),
            tuple(sorted(a["name"] for a in t["receive"])),
        )
        for t in r["trades"]
    )
    legacy = _scan(players, teams, contract)
    allp = _scan(players, teams, contract, discovery=_filters(quality="all"))
    assert key(legacy) == key(allp)


def test_scan_sorts_and_determinism():
    players, teams, contract = _scan_league()
    a = _scan(players, teams, contract, discovery=_filters(quality="all"))
    b = _scan(players, teams, contract, discovery=_filters(quality="all"))
    assert a["trades"] == b["trades"]
    impacts = [t["discovery"]["impact"] for t in a["trades"]]
    assert impacts == sorted(impacts, reverse=True)
    gains = [
        t["discovery"]["gain"]
        for t in _scan(
            players, teams, contract, discovery=_filters(quality="all", sort="absolute_gain")
        )["trades"]
    ]
    assert gains == sorted(gains, reverse=True)
    ranks = [
        t["discovery"]["bestIncoming"]["rank"]
        for t in _scan(
            players, teams, contract, discovery=_filters(quality="all", sort="incoming_rank")
        )["trades"]
    ]
    assert ranks == sorted(ranks)


def test_scan_empty_result_names_the_constraint():
    players, teams, contract = _scan_league()
    out = _scan(
        players, teams, contract, discovery=_filters(quality="top100", min_incoming_value=9000)
    )
    assert out["trades"] == []
    assert out["metadata"]["discovery"]["emptyReason"] == "no_target_meets_quality"
    assert out["metadata"]["discovery"]["broaderQualityLevels"] == ["top250", "top500", "all"]


def test_filler_cannot_raise_incoming_importance():
    index = disc.CanonicalIndex(
        _league([], [("Star", "WR", 5000, 5000, None, 40), ("Filler", "WR", 800, 900, None, 650)])[
            2
        ]
    )
    prior = disc.load_impact_prior()
    give = [finder.Asset("Ours", "WR", "", 4000, 4000)]
    star = finder.Asset("Star", "WR", "", 5000, 5000)
    filler = finder.Asset("Filler", "WR", "", 800, 900)
    alone = disc.candidate_metrics(give, [star], index=index, prior=prior)
    padded = disc.candidate_metrics(give, [star, filler], index=index, prior=prior)
    assert padded["factors"]["incomingImportance"] == alone["factors"]["incomingImportance"]
    assert padded["bestIncoming"]["name"] == "Star"
    # The gain is VA-adjusted (the calculator's own verdict), never a raw sum.
    assert padded["gain"] == padded["receivingAdjusted"] - padded["sendingAdjusted"] or padded[
        "gain"
    ] == round(padded["receivingAdjusted"] - padded["sendingAdjusted"])


def test_unknown_factors_are_never_free():
    prior = disc.load_impact_prior()
    known = {
        "factors": {
            "incomingImportance": 0.4,
            "edge": 0.5,
            "rosterFit": -0.5,
            "counterpartyPlausibility": 0.8,
            "forcedDropCost": 0.3,
        },
        "evidenceMultiplier": 1.0,
    }
    unknown = {
        "factors": {
            "incomingImportance": 0.4,
            "edge": 0.5,
            "rosterFit": None,
            "counterpartyPlausibility": 0.8,
            "forcedDropCost": None,
        },
        "evidenceMultiplier": 1.0,
    }
    disc.score_impact([known, unknown], prior)
    assert unknown["imputations"] == {"rosterFit": -0.5, "forcedDropCost": 0.3}
    assert unknown["impact"] == known["impact"]


def test_missing_confidence_is_not_high_evidence():
    prior = disc.load_impact_prior()
    give = [finder.Asset("Ours", "WR", "", 3000, 3000)]
    recv = [finder.Asset("Nobody", "WR", "", 3500, 3500)]
    m = disc.candidate_metrics(give, recv, index=disc.CanonicalIndex({}), prior=prior)
    assert m["evidenceMultiplier"] == prior["evidenceMultipliers"]["none"]


# ── Best Offers ───────────────────────────────────────────────────────────


def test_best_offers_quality_and_scope_and_explained_cards():
    mine = [("Our WR", "WR", 4000, 5000, 5100, 110)]
    theirs = [("Their RB", "RB", 5000, 4800, 4900, 70)]
    deep = [("Deep RB", "RB", 5000, 4800, 4900, 420)]
    players, teams, contract = _league(mine, theirs, extra_teams=[("Deep", deep)])
    out = bo.build_best_offers(
        players,
        "Us",
        teams,
        contract=contract,
        use_team_context=False,
        market_top_n=0,
        discovery=_filters(quality="top250"),
    )
    cards = {c["team"]: c for c in out["opponents"]}
    assert cards["Them"]["status"] == "qualified"
    assert cards["Them"]["offer"]["discovery"]["bestIncoming"]["rank"] == 70
    assert cards["Them"]["offer"]["whyItMatters"]
    assert cards["Deep"]["noResultReason"] == "no_target_meets_quality"
    assert out["discovery"]["filters"]["targetQuality"] == "top250"
    dfn = bo.build_best_offers(
        players,
        "Us",
        teams,
        contract=contract,
        use_team_context=False,
        market_top_n=0,
        discovery=_filters(quality="all", scope="defense"),
    )
    assert {c["noResultReason"] for c in dfn["opponents"]} == {"no_target_in_players_to_target"}


# ── cross-view consistency ────────────────────────────────────────────────


def test_the_same_swap_reads_the_same_in_golden_and_scan():
    mine = [OWNED_LB]
    theirs = [TARGET_LB_120]
    players, teams, contract = _league(mine, theirs)
    f = _filters(quality="top250")
    [g] = gu.find_golden_upgrades(players, "Us", teams, contract=contract, discovery=f)["upgrades"]
    scan = _scan(players, teams, contract, discovery=f)
    same = [
        t
        for t in scan["trades"]
        if [a["name"] for a in t["give"]] == ["Our LB"]
        and [a["name"] for a in t["receive"]] == ["Their LB"]
    ]
    if not same:
        pytest.skip("the finder's own gates did not admit this swap")
    for k in ("gain", "gainPct", "bestIncoming", "meetsTargetQuality"):
        assert same[0]["discovery"][k] == g["discovery"][k]
