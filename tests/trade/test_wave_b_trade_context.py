"""Wave B — trade topology, Use Team Context, final legal roster, posture picks.

Owner directive 2026-10-03 ("Wave B"), binding records:
``docs/trade/TRADE_CONTEXT_AND_TOPOLOGY_SUPERSESSION_2026-08-14.md`` (C3-TOPO-01 /
C3-CTX-01), ``docs/trade/ROSTER_CAPACITY_FORCED_DROP_TRADE_ANALYSIS_ADDENDUM_2026-08-14.md``
(C3-CAP-01) and ``docs/trade/TRADE_FINDER_POSTURE_AWARE_PICKS_ADDENDUM_2026-08-14.md``
(C7-PICKGEN-01).  Posture itself is pinned in ``tests/roster_intel/test_posture.py``
and its use by Analyze Trade in ``test_analyze_posture_weighting.py``.
"""

from __future__ import annotations

import itertools

import pytest

from src.packages import PackageAsset, topology_is_allowed
from src.trade import team_context as TC
from src.trade.finder import find_trades
from src.trade.finder_context import pick_direction
from src.trade.roster_capacity import (
    assess_roster_capacity,
    requires_cleanup,
)
from tests.trade.test_roster_capacity import (
    MAIN_SETTINGS,
    _ctx,
    _incoming,
    _roster,
)

# ── C3-CTX-01: one mode contract ─────────────────────────────────────────


class TestTeamContextContract:
    @pytest.mark.parametrize("raw", [None, "false", 0, "off", [], {}, "0"])
    def test_only_a_boolean_false_turns_it_off(self, raw):
        assert TC.parse_use_team_context(raw) is True

    def test_false_is_asset_only(self):
        assert TC.parse_use_team_context(False) is False
        block = TC.mode_block(False, consulted=["rosterCapacity"])
        assert block["mode"] == "asset_only"
        assert block["label"] == "Asset-Only Analysis"
        (dim,) = block["dimensions"]
        assert dim["state"] == "excluded_by_mode"
        assert dim["includedInVerdict"] is False
        assert dim["note"] == "not included in this verdict"

    def test_unavailable_never_flips_the_mode(self):
        block = TC.mode_block(True, dimensions={"rosterCapacity": ("unavailable", "no_cap")})
        assert block["applied"] is True and block["mode"] == "team"
        assert block["dimensions"][0]["state"] == "unavailable"

    def test_off_cannot_claim_an_included_team_dimension(self):
        with pytest.raises(ValueError):
            TC.mode_block(False, dimensions={"rosterCapacity": "included"})

    def test_label_excluded_marks_without_hiding(self):
        out = TC.label_excluded({"requiresDrops": True})
        assert out["requiresDrops"] is True
        assert out["includedInVerdict"] is False
        assert out["contextNote"] == "not included in this verdict"
        assert TC.label_excluded(None) is None


def test_every_trade_route_uses_the_one_parser():
    """No route keeps a private ``useTeamContext`` rule (two did, four did not)."""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[2] / "server.py").read_text(encoding="utf-8")
    assert src.count('parse_use_team_context(body.get("useTeamContext"))') >= 5
    assert 'raw_use_team_context = body.get("useTeamContext")' not in src
    assert 'raw_context = body.get("useTeamContext")' not in src


# ── C3-TOPO-01 in the generators ─────────────────────────────────────────


def _asset(name, *, pick=False):
    return PackageAsset(asset_id="", name=name, position="PICK" if pick else "WR", value=1.0)


@pytest.mark.parametrize(
    ("give", "recv", "ok"),
    [
        (1, 1, True),
        (2, 1, True),
        (1, 2, True),
        (3, 2, True),
        (2, 3, True),
        (3, 1, False),
        (1, 3, False),
        (4, 2, False),
        (2, 4, False),
    ],
)
def test_topology_table_with_and_without_picks(give, recv, ok):
    g = [_asset(f"g{i}") for i in range(give)]
    r = [_asset(f"r{i}") for i in range(recv)]
    assert topology_is_allowed(g, r) is ok
    # Picks do not count as players, on either side.
    assert topology_is_allowed([*g, _asset("p", pick=True)], r) is ok
    assert topology_is_allowed(g, [*r, _asset("p", pick=True), _asset("q", pick=True)]) is ok


def _finder_league(n_mine=12, n_theirs=12):
    """Two rosters whose board and market disagree enough to make arbitrage."""
    players, rows, teams = {}, [], []
    for owner, n, base in (("Me", n_mine, 6000), ("Them", n_theirs, 5800)):
        names = []
        for i in range(n):
            name = f"{owner} P{i:02d}"
            board = base - i * 220
            market = int(board * (0.8 if (i + (owner == "Them")) % 2 else 1.05))
            players[name] = {
                "_finalAdjusted": board,
                "_sites": 6,
                "_canonicalSiteValues": {"ktcCrowdTradesSfTep": market},
            }
            rows.append(
                {
                    "canonicalName": name,
                    "displayName": name,
                    "legacyRef": name,
                    "position": "WR",
                    "rankDerivedValue": board,
                }
            )
            names.append(name)
        teams.append({"name": owner, "ownerId": owner.lower(), "players": names})
    return players, {"playersArray": rows, "sleeper": {"teams": teams}}, teams


def test_finder_reaches_three_for_two_and_never_three_for_one():
    players, contract, teams = _finder_league()
    res = find_trades(players, "Me", ["Them"], teams, contract=contract, use_team_context=False)
    enum = res["metadata"]["packageEnumeration"]["Them"]
    assert {"oneForOne", "asymmetric", "twoForTwo", "threeForTwo"} <= set(enum)
    assert enum["threeForTwo"]["shapes"] == ["3-for-2", "2-for-3"]
    for t in res["trades"]:
        counts = t["playerCounts"]
        assert abs(counts["give"] - counts["receive"]) <= 1
    assert res["metadata"]["topology"]["owner"].endswith("topology_is_allowed")


def test_arbitrage_equal_count_request_is_still_honoured_for_api_callers():
    players, contract, teams = _finder_league()
    ctl = ["Them", {"__arbitrageControl": {"equalCountOnly": True}}]
    res = find_trades(players, "Me", ctl, teams, contract=contract, use_team_context=False)
    assert all(t["playerCounts"]["give"] == t["playerCounts"]["receive"] for t in res["trades"])


def test_angle_sizes_the_counter_side_from_the_offers_players_not_its_assets():
    from src.trade.angle import _topology_ok, _topology_sizes

    offer = [
        {"canonicalName": "A", "position": "WR"},
        {"canonicalName": "B", "position": "RB"},
        {"canonicalName": "2027 Round 1", "position": "PICK", "assetClass": "pick"},
    ]
    assert _topology_sizes(offer) == [1, 2, 3]  # 2 players ±1, the pick does not count
    four = [{"name": f"X{i}", "position": "WR"} for i in range(4)]
    assert not _topology_ok(offer, four)  # 2-for-4 even though the offer has 3 assets
    assert _topology_ok(offer, four[:3])
    one_plus_pick = [offer[0], offer[2]]
    assert _topology_sizes(one_plus_pick) == [1, 2]
    assert not _topology_ok(one_plus_pick, four[:3])  # 1-for-3 with a pick riding along


# ── C3-CAP-01: the addendum's eleven fixtures ────────────────────────────


def _cap(roster_n, incoming, outgoing_n, *, settings=None):
    from tests.trade.test_roster_capacity import _free_agents

    roster = _roster(roster_n)
    names_in = [f"In {i}" for i in range(incoming)]
    ctx = _ctx(roster, settings=settings, extra_rows=_free_agents() + _incoming(names_in))
    out = [n for n, _v, _p in roster[:outgoing_n]]
    return assess_roster_capacity(ctx, incoming_players=names_in, outgoing_players=out), ctx


class TestCapacityFixtures:
    def test_1_full_roster_one_for_one_needs_no_cut(self):
        cap, _ = _cap(58, 1, 1)
        assert cap.requires_drops is False and cap.forced_drops == []

    def test_2_full_roster_one_for_two_needs_one_cleanup(self):
        cap, _ = _cap(58, 2, 1)
        assert cap.requires_drops is True and len(cap.forced_drops) == 1

    def test_3_one_open_spot_one_for_two_fits_cleanly(self):
        cap, _ = _cap(57, 2, 1)
        assert cap.requires_drops is False
        assert cap.forced_drop_release_cost in (None, 0.0) or cap.forced_drops == []

    def test_4_one_over_two_for_one_is_legal_after(self):
        cap, _ = _cap(59, 1, 2)
        assert cap.over_limit_before == 1 and cap.over_limit_after == 0

    def test_5_three_over_two_for_one_improves_to_two(self):
        cap, _ = _cap(61, 1, 2)
        assert (cap.over_limit_before, cap.over_limit_after) == (3, 2)

    def test_6_one_over_one_for_two_worsens_to_two(self):
        cap, _ = _cap(59, 2, 1)
        assert (cap.over_limit_before, cap.over_limit_after) == (1, 2)

    def test_7_taxi_relief_only_where_membership_is_known(self):
        settings = {**MAIN_SETTINGS, "taxiSize": 2}
        cap, _ = _cap(58, 2, 1, settings=settings)
        # Unknown taxi membership: a RANGE, never a guessed relief.
        assert cap.certainty == "partial"
        assert cap.over_limit_after is None
        assert cap.over_limit_after_min == 0 and cap.over_limit_after_max == 1

    def test_8_cut_chosen_by_the_canonical_ladder_not_lowest_raw_value(self):
        """The forced drop is the cut ladder's (lineup-validated, cheapest
        effective cut cost) — never ``package delta - lowest raw value``."""
        cap, _ = _cap(58, 2, 1)
        (drop,) = cap.forced_drops
        assert drop.release_cost > 0
        assert drop.rung == 1

    def test_9_picks_do_not_consume_capacity(self):
        roster = _roster(58)
        ctx = _ctx(roster)
        cap = assess_roster_capacity(
            ctx, incoming_players=["In 0"], outgoing_players=[roster[0][0]]
        )
        assert cap.requires_drops is False  # a 1-for-1 plus any number of picks

    def test_requires_cleanup_agrees_with_the_full_assessment(self):
        for n, inc, out in itertools.product((55, 57, 58, 60), (0, 1, 2, 3), (0, 1, 2, 3)):
            roster = _roster(n)
            ctx = _ctx(roster)
            names_in = [f"In {i}" for i in range(inc)]
            names_out = [x for x, _v, _p in roster[:out]]
            full = assess_roster_capacity(
                ctx, incoming_players=names_in, outgoing_players=names_out
            )
            quick = requires_cleanup(ctx, incoming_players=names_in, outgoing_players=names_out)
            assert quick is bool((full.over_limit_after_max or 0) > 0), (n, inc, out)


# Fixtures 10 (OFF excludes capacity from verdict/ranking) and 11 (ranking
# changes when one side cannot absorb the extra player) are pinned through the
# real finder in tests/trade/test_capacity_wiring.py and through Analyze Trade in
# tests/trade/test_analyze_posture_weighting.py / test_war_room_trade_path.py.


# ── Counterparty capacity through the simulator ──────────────────────────


def _two_team_contract():
    from tests.trade.test_roster_capacity import _free_agents, _row

    mine = _roster(58)
    theirs = [(f"Their {i:02d}", 2000.0 + i, "WR") for i in range(58)]
    rows = [_row(n, v, p) for n, v, p in (*mine, *theirs)] + _free_agents()
    teams = [
        {
            "name": "Us",
            "ownerId": "o1",
            "roster_id": 1,
            "players": [n for n, _v, _p in mine],
            "pickDetails": [],
        },
        {
            "name": "Them",
            "ownerId": "o2",
            "roster_id": 2,
            "players": [n for n, _v, _p in theirs],
            "pickDetails": [],
        },
    ]
    return {"playersArray": rows, "sleeper": {"teams": teams}}, mine, theirs


def test_simulator_evaluates_the_other_teams_final_legal_roster():
    from src.api import trade_simulator

    contract, mine, theirs = _two_team_contract()
    team = contract["sleeper"]["teams"][0]
    # We send TWO players for one of theirs: they must cut, we gain a spot.
    result = trade_simulator.simulate_trade(
        contract,
        resolved_team=team,
        players_in=[theirs[0][0]],
        players_out=[mine[0][0], mine[1][0]],
        roster_settings=MAIN_SETTINGS,
    )
    cp = result["counterparty"]
    assert cp["available"] is True
    assert cp["team"]["name"] == "Them"
    assert cp["rosterCapacity"]["requiresDrops"] is True
    assert len(cp["rosterCapacity"]["forcedDrops"]) == 1
    assert result["rosterCapacity"]["requiresDrops"] is False
    dims = {d["dimension"]: d for d in result["teamContext"]["dimensions"]}
    assert dims["counterpartyCapacity"]["state"] == "context"

    off = trade_simulator.simulate_trade(
        contract,
        resolved_team=team,
        players_in=[theirs[0][0]],
        players_out=[mine[0][0], mine[1][0]],
        roster_settings=MAIN_SETTINGS,
        use_team_context=False,
    )
    assert off["counterparty"]["includedInVerdict"] is False
    assert off["teamContext"]["mode"] == "asset_only"


def test_counterparty_is_never_guessed():
    from src.api.trade_simulator import infer_counterparty

    contract, mine, theirs = _two_team_contract()
    teams = contract["sleeper"]["teams"]
    team, reason = infer_counterparty(teams, players_in=["Nobody"], exclude_rid=1)
    assert team is None and reason == "incoming_assets_not_held_by_another_team"
    teams.append({"name": "Third", "roster_id": 3, "players": ["Third 00"]})
    team, reason = infer_counterparty(teams, players_in=[theirs[0][0], "Third 00"], exclude_rid=1)
    assert team is None and reason == "incoming_assets_span_multiple_teams"


# ── C7-PICKGEN-01 ────────────────────────────────────────────────────────


def _postures(mine, theirs, conf="HIGH"):
    return {
        "teams": {
            "me": {"teamName": "Me", "posture": mine, "confidence": conf},
            "them": {"teamName": "Them", "posture": theirs, "confidence": conf},
        }
    }


class TestPickDirection:
    def test_push_sends_to_rebuild_and_retool(self):
        for t in ("REBUILD", "RETOOL"):
            d, _ = pick_direction(
                {"posture": "PUSH", "confidence": "HIGH"}, {"posture": t, "confidence": "MEDIUM"}
            )
            assert d == "send"

    def test_rebuild_receives_from_push(self):
        d, _ = pick_direction(
            {"posture": "REBUILD", "confidence": "HIGH"}, {"posture": "PUSH", "confidence": "HIGH"}
        )
        assert d == "receive"

    @pytest.mark.parametrize(
        ("m", "t"),
        [("HOLD", "REBUILD"), ("PUSH", "PUSH"), ("REBUILD", "REBUILD"), ("HOLD", "HOLD")],
    )
    def test_no_strategic_mismatch_no_picks(self, m, t):
        d, why = pick_direction(
            {"posture": m, "confidence": "HIGH"}, {"posture": t, "confidence": "HIGH"}
        )
        assert d is None and why

    def test_low_confidence_or_missing_posture_moves_no_pick(self):
        assert (
            pick_direction(
                {"posture": "PUSH", "confidence": "LOW"},
                {"posture": "REBUILD", "confidence": "HIGH"},
            )[0]
            is None
        )
        assert pick_direction(None, {"posture": "REBUILD", "confidence": "HIGH"})[0] is None


def _pick_league():
    """``_finder_league`` plus owned picks and the board's pick rows."""
    players, contract, teams = _finder_league()
    tiers = {"Early": 6400, "Mid": 5400, "Late": 4600}
    for tier, v in tiers.items():
        name = f"2027 {tier} 1st"
        players[name] = {"_finalAdjusted": v, "_canonicalSiteValues": {"ktcCrowdTradesSfTep": v}}
        contract["playersArray"].append(
            {
                "canonicalName": name,
                "position": "PICK",
                "assetClass": "pick",
                "rankDerivedValue": v,
                "pickValueProvenance": {"class": "direct_market_blend"},
            }
        )
    contract["playersArray"].append(
        {
            "canonicalName": "2027 Round 1",
            "position": "PICK",
            "assetClass": "pick",
            "rankDerivedValue": 5466,
            "pickValueProvenance": {
                "class": "derived_uniform_tier_ev",
                "basis": ["2027 Early 1st", "2027 Mid 1st", "2027 Late 1st"],
            },
        }
    )
    for t, rid in zip(teams, (1, 2)):
        t["roster_id"] = rid
        t["pickDetails"] = [
            {
                "season": 2027,
                "round": 1,
                "fromRosterId": rid,
                "ownerRosterId": rid,
                "slot": None,
                "label": "2027 Mid 1st (own)",
                "assetId": f"pick:L:2027:r1:o{rid}",
            }
        ]
    return players, contract, teams


def test_push_team_can_send_its_owned_first_to_a_rebuilder():
    players, contract, teams = _pick_league()
    res = find_trades(
        players,
        "Me",
        ["Them"],
        teams,
        contract=contract,
        league_postures=_postures("PUSH", "REBUILD"),
    )
    gen = res["metadata"]["pickGeneration"]["Them"]
    assert gen["direction"] == "send"
    assert gen["picksOffered"] == ["2027 Mid 1st (own)"]
    assert res["postureDirectedPickPackages"], "the fixture must produce a pick package"
    for p in res["postureDirectedPickPackages"]:
        picks = [a for a in p["give"] if a.get("assetClass") == "pick"]
        assert [a["assetId"] for a in picks] == ["pick:L:2027:r1:o1"]  # OUR owned pick
        # Generic future grade, vendor tier mean, honestly incomplete.
        assert picks[0]["name"] == "2027 Round 1"
        assert picks[0]["marketBasis"] == "vendorTierMean"
        assert p["ktcCoverage"] == "partial"
        assert not any(a.get("assetClass") == "pick" for a in p["receive"])


def test_rebuilder_receives_the_push_teams_owned_pick():
    players, contract, teams = _pick_league()
    res = find_trades(
        players,
        "Me",
        ["Them"],
        teams,
        contract=contract,
        league_postures=_postures("REBUILD", "PUSH"),
    )
    assert res["metadata"]["pickGeneration"]["Them"]["direction"] == "receive"
    assert res["postureDirectedPickPackages"], "the fixture must produce a pick package"
    for p in res["postureDirectedPickPackages"]:
        picks = [a for a in p["receive"] if a.get("assetClass") == "pick"]
        assert [a["assetId"] for a in picks] == ["pick:L:2027:r1:o2"]  # THEIR owned pick


def test_no_picks_without_a_posture_mismatch_or_in_asset_only():
    players, contract, teams = _pick_league()
    same = find_trades(
        players, "Me", ["Them"], teams, contract=contract, league_postures=_postures("PUSH", "PUSH")
    )
    assert same["postureDirectedPickPackages"] == []
    assert all(t["picksIncluded"] == 0 for t in same["trades"])
    off = find_trades(
        players,
        "Me",
        ["Them"],
        teams,
        contract=contract,
        league_postures=_postures("PUSH", "REBUILD"),
        use_team_context=False,
    )
    assert off["postureDirectedPickPackages"] == []
    assert off["metadata"]["pickGeneration"] == {}
    assert all(t["picksIncluded"] == 0 for t in off["trades"])


def test_player_only_stays_preferred_and_picks_never_enter_the_main_list_unqualified():
    players, contract, teams = _pick_league()
    res = find_trades(
        players,
        "Me",
        ["Them"],
        teams,
        contract=contract,
        league_postures=_postures("PUSH", "REBUILD"),
    )
    full = [t for t in res["trades"] if t["ktcCoverage"] == "full"]
    picks_in_main = [t for t in res["trades"] if t["picksIncluded"]]
    if full and picks_in_main:
        first_pick = res["trades"].index(picks_in_main[0])
        assert all(res["trades"].index(t) < first_pick for t in full)


def test_a_pick_the_sender_does_not_hold_is_never_offered():
    players, contract, teams = _pick_league()
    teams[0]["pickDetails"] = []  # we traded our first away
    res = find_trades(
        players,
        "Me",
        ["Them"],
        teams,
        contract=contract,
        league_postures=_postures("PUSH", "REBUILD"),
    )
    gen = res["metadata"]["pickGeneration"]["Them"]
    assert gen["picksOffered"] == []
    assert res["postureDirectedPickPackages"] == []


def test_an_unpriced_pick_is_never_offered():
    players, contract, teams = _pick_league()
    for name in ("2027 Early 1st", "2027 Mid 1st", "2027 Late 1st"):
        players[name]["_canonicalSiteValues"] = {}
    res = find_trades(
        players,
        "Me",
        ["Them"],
        teams,
        contract=contract,
        league_postures=_postures("PUSH", "REBUILD"),
    )
    gen = res["metadata"]["pickGeneration"]["Them"]
    assert gen["picksOffered"] == []
    assert gen["inventory"]["noMarketPrice"] == 1
