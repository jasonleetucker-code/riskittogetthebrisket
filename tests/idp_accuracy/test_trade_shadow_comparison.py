"""Lane H: the shadow trade comparison keeps three quantities apart, and changes nothing live.

Everything here runs offline on a synthetic two-team league (58-man rosters under
``dynasty_main``'s stated roster settings).  The tests that read the committed evidence file skip when it is absent.

What is pinned:

* Market Price is the live package model and fairness band, called the way the live engines call
  them, from each team's own perspective; an unpriced asset refuses it.
* League Utility is shadow, per asset; an asset the candidates cannot score is UNAVAILABLE and a
  net is withheld rather than computed with a zero.
* Team Transaction Impact solves the whole before/after roster with the exact solver, takes forced
  drops from the live capacity owner, and a package is not the sum of its single moves.
* The three are never blended: separate blocks, no combined score, no verdict.
* Example selection is seeded, outcome-free, market-fair and reproducible.
* The artifact carries no manager, team, owner, roster or league identifier.
* Nothing in ``src/`` imports the script, and the script writes only its evidence file and cache.
"""

from __future__ import annotations

import ast
import inspect
import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from scripts.idp_accuracy import trade_shadow_comparison as tsc
from src.trade import roster_capacity as rc
from src.valuation_math import fairness_bands, package_model

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "idp_accuracy" / "trade_shadow_comparison.py"
EVIDENCE = (
    REPO / "docs" / "valuation" / "idp_accuracy" / "evidence" / "h_trade_shadow_comparison.json"
)
DOC = REPO / "docs" / "valuation" / "idp_accuracy" / "H_RECOMMENDATIONS.md"

# ── a synthetic league ────────────────────────────────────────────────────────────────────────
#: ``dynasty_main``'s roster settings, stated here because the test conftest blocks the registry
#: (the script threads the registry's own settings through the same argument).
MAIN_SETTINGS = {
    "teamCount": 12,
    "rosterSize": 58,
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
#: 58 players per team, the real roster limit of ``dynasty_main``.
SHAPE = (("QB", 3), ("RB", 8), ("WR", 12), ("TE", 5), ("K", 2), ("DL", 10), ("LB", 8), ("DB", 10))
BASE_PPG = {
    "QB": 20.0,
    "RB": 12.0,
    "WR": 11.0,
    "TE": 8.0,
    "K": 8.0,
    "DL": 9.0,
    "LB": 10.0,
    "DB": 9.0,
}
TEAM_NAMES = ("Alpha Private Team", "Bravo Private Team")
OWNER_IDS = ("owner-alpha-123456", "owner-bravo-654321")
WEEKS = (1, 2, 3)


def _row(sid: str, name: str, pos: str, value: float | None, rank: int | None) -> dict:
    return {
        "playerId": sid,
        "displayName": name,
        "canonicalName": name,
        "legacyRef": name,
        "position": pos,
        "assetClass": "offense" if pos in tsc.OFFENSE else "idp",
        "rankDerivedValue": value,
        "canonicalConsensusRank": rank,
        "confidenceBucket": "high",
        "quarantined": False,
        "fantasyPositions": None,
    }


def make_world(*, duplicate_name: bool = False) -> dict:
    rows: list[dict] = []
    teams: list[dict] = []
    id_to_name: dict[str, str] = {}
    positions: dict[str, str] = {}
    ppg: dict[str, float] = {}
    rank = 0
    for t in range(2):
        ids: list[str] = []
        names: list[str] = []
        k = 0
        for pos, n in SHAPE:
            for i in range(n):
                sid = str(1000 + t * 100 + k)
                name = f"{'AB'[t]}{pos}{i}"
                if duplicate_name and t == 1 and pos == "WR" and i == 0:
                    name = "AWR0"  # same display name as team 0's WR0, a different id
                p = BASE_PPG[pos] - 0.8 * i
                ppg[sid] = p
                rank += 1
                # one unpriced player per team: the board declined to price him
                value = None if (pos == "DL" and i == 9) else float(round(300 * p))
                rows.append(_row(sid, name, pos, value, None if value is None else rank))
                id_to_name[sid] = name
                positions[name] = pos
                ids.append(sid)
                names.append(name)
                k += 1
        teams.append(
            {
                "name": TEAM_NAMES[t],
                "sleeperTeamName": TEAM_NAMES[t],
                "roster_id": t + 1,
                "ownerId": OWNER_IDS[t],
                # deliberately NOT parallel to playerIds, as in the live contract
                "players": sorted(names),
                "playerIds": ids,
            }
        )
    for j, pos in enumerate(("QB", "RB", "WR", "TE", "DL", "LB", "DB")):
        sid = str(9000 + j)
        name = f"FA{pos}"
        rows.append(_row(sid, name, pos, 500.0 + j, 900 + j))
        id_to_name[sid] = name
        positions[name] = pos
    contract = {
        "playersArray": rows,
        "sleeper": {
            "leagueId": "999000111222333",
            "leagueName": "Synthetic Private League",
            "teams": teams,
            "idToPlayer": id_to_name,
            "positions": positions,
            "fantasyPositions": {},
            "scoringSettings": {},
            "rosterPositions": [],
        },
    }
    assets, rosters, census = tsc.load_assets(contract)
    weeks = {}
    for w in WEEKS:
        # a spiky week pattern so best-ball depth matters
        weeks[w] = {
            sid: max(0.0, p + (1.5 if (int(sid) + w) % 3 == 0 else -1.5)) for sid, p in ppg.items()
        }
    points = tsc.PointsTable(weeks, {w: frozenset(weeks[w]) for w in WEEKS})
    probe = rc.build_capacity_context(
        contract,
        tsc.LEAGUE_KEY,
        rosters[0].team,
        roster_settings=MAIN_SETTINGS,
        scarcity_reading=(None, tsc.SCARCITY_NOTE),
    )
    rules = tsc.LeagueRules(
        probe.starter_slots, probe.slot_eligibility, probe.roster_limit, MAIN_SETTINGS
    )
    return {
        "contract": contract,
        "assets": assets,
        "rosters": rosters,
        "points": points,
        "rules": rules,
        "census": census,
    }


@pytest.fixture(scope="module")
def world() -> dict:
    return make_world()


def asset(world: dict, name: str) -> tsc.Asset:
    return next(a for a in world["assets"].values() if a.name == name)


def utility_table(world: dict, *, skip: tuple[str, ...] = ()) -> dict[str, tsc.UtilityRow]:
    table = {}
    for a in world["assets"].values():
        if a.name in skip:
            table[a.sid] = tsc.UtilityRow(a.sid, None, None, None, "rookie_prior_only")
        else:
            d = (a.value or 0) / 1000.0
            table[a.sid] = tsc.UtilityRow(a.sid, d * 2, d, 0.1, None)
    return table


# ── the real league facts the synthetic league borrows ────────────────────────────────────────
def test_the_synthetic_league_uses_the_registry_rules(world):
    rules = world["rules"]
    assert rules.roster_limit == 58
    assert len(rules.slots) == 21
    assert rules.slots.count("DL") == rules.slots.count("LB") == rules.slots.count("DB") == 3
    assert all(len(r.assets) == 58 for r in world["rosters"])


def test_assets_join_by_id_and_flag_a_name_collision():
    clean = make_world()
    assert clean["census"]["nameJoinDisagrees"] == 0
    dup = make_world(duplicate_name=True)
    # two ids share one display name: the capacity owner joins by name, so the second is flagged
    assert dup["census"]["nameJoinDisagrees"] == 1
    flagged = [a for a in dup["assets"].values() if not a.name_join_safe]
    assert len(flagged) == 1 and flagged[0].name == "AWR0"
    # and a flagged player is never drawn into an example
    assert not tsc._eligible(flagged[0])


def test_unpriced_players_stay_unpriced_not_zero(world):
    unpriced = [a for a in world["assets"].values() if a.value is None]
    assert len(unpriced) == 2
    assert all(not tsc._eligible(a) for a in unpriced)


# ── quantity 1: Market Price ──────────────────────────────────────────────────────────────────
def test_market_price_is_the_live_package_model_from_each_teams_perspective(world):
    give = (asset(world, "AWR0"), asset(world, "AWR1"))
    recv = (asset(world, "BWR0"),)
    a = tsc.market_price(give, recv)
    b = tsc.market_price(recv, give)
    gv, rv = [x.value for x in give], [x.value for x in recv]
    send_adj, recv_adj, _, _ = package_model.adjusted_pair_totals(gv, rv)
    assert a["sendAdjusted"] == pytest.approx(send_adj, abs=0.05)
    assert a["receiveAdjusted"] == pytest.approx(recv_adj, abs=0.05)
    assert a["gap"] == pytest.approx(recv_adj - send_adj, abs=0.05)
    # the other team sees the same trade from the other side
    assert b["gap"] == pytest.approx(-a["gap"], abs=0.11)
    assert a["packageModel"] == package_model.receipt()["id"] == "geom_q078_v1"
    band = fairness_bands.classify_packages(recv_adj - send_adj, gv, rv)
    assert a["band"]["level"] == band["level"] and a["band"]["label"] == band["label"]


def test_a_one_for_one_carries_no_package_adjustment(world):
    reading = tsc.market_price((asset(world, "AWR0"),), (asset(world, "BRB0"),))
    assert reading["sendValueAdjustment"] == reading["receiveValueAdjustment"] == 0


def test_market_price_refuses_an_unpriced_asset(world):
    unpriced = next(a for a in world["assets"].values() if a.value is None)
    reading = tsc.market_price((unpriced,), (asset(world, "BRB0"),))
    assert reading["state"] == "unpriced_asset"
    assert unpriced.name in reading["unpricedAssets"]
    assert "gap" not in reading and "band" not in reading


# ── quantity 2: League Utility ────────────────────────────────────────────────────────────────
def test_league_utility_net_is_receive_minus_give_when_everything_is_scored(world):
    table = utility_table(world)
    give, recv = (asset(world, "AWR0"),), (asset(world, "BRB0"),)
    block = tsc.league_utility(give, recv, table)
    d_give = table[give[0].sid].d
    d_recv = table[recv[0].sid].d
    assert block["complete"] is True
    assert block["net"]["D"] == pytest.approx(d_recv - d_give, abs=0.01)
    assert block["net"]["additive"] is False
    assert block["net"]["countsDiffer"] is False and block["net"]["bias"] is None
    assert "SHADOW" in block["status"]


def test_an_unscored_asset_is_unavailable_and_withholds_the_net_never_zero(world):
    table = utility_table(world, skip=("BRB0",))
    block = tsc.league_utility((asset(world, "AWR0"),), (asset(world, "BRB0"),), table)
    assert block["complete"] is False
    assert block["net"]["D"] is None and block["net"]["C"] is None
    scored, missing = block["give"][0], block["receive"][0]
    assert scored["state"] == "scored" and missing["state"] == "unavailable"
    assert missing["D"] is None and missing["C"] is None
    assert missing["reason"] == "rookie_prior_only"


def test_a_player_outside_the_cutoff_universe_is_unavailable(world):
    row = tsc.utility_for("not-a-player", {})
    assert row.d is None and row.reason == "not_in_cutoff_universe"


def test_unequal_player_counts_carry_the_diminishing_returns_caveat(world):
    table = utility_table(world)
    block = tsc.league_utility(
        (asset(world, "AWR0"), asset(world, "AWR1")), (asset(world, "BRB0"),), table
    )
    assert block["net"]["countsDiffer"] is True
    assert "favours the side that receives more players" in block["net"]["bias"]


def test_parse_league_utility_reads_lane_g_vectors_and_reasons():
    blob = json.dumps(
        {
            "preregistration": "idp_accuracy_G_v1",
            "window": "W0",
            "promotes": False,
            "vectors": {
                "C": {"1": 1.5, "2": -0.5},
                "D": {"1": 2.0},
                "D_se": {"1": 0.3},
            },
            "vectorSha256": {"D": "abc"},
            "players": [
                {"id": "1", "projectionStatus": "projected"},
                {"id": "2", "projectionStatus": "projected"},
                {"id": "3", "projectionStatus": "rookie_prior_only"},
            ],
        }
    ).encode()
    table, src = tsc.parse_league_utility(blob, "test")
    assert table["1"].d == 2.0 and table["1"].c == 1.5 and table["1"].reason is None
    assert table["2"].d is None and table["2"].c == -0.5
    assert table["2"].reason == "D_undefined_no_team_schedule"
    assert table["3"].d is None and table["3"].reason == "rookie_prior_only"
    assert src["promotes"] is False and src["scoredD"] == 1 and len(src["sha256"]) == 64


def test_missing_scores_file_makes_every_asset_unavailable(tmp_path):
    table, src = tsc.load_league_utility(tmp_path / "nope.json", None)
    assert table == {} and src["state"] == "unavailable"


# ── quantity 3: Team Transaction Impact ───────────────────────────────────────────────────────
def test_lineup_solve_does_not_seat_an_unknown_player_but_does_seat_a_zero():
    slots = tsc.LeagueRules(("WR",), None, 58)
    a = tsc.Asset("1", "Unknown", "WR", (), 5.0, 1, "high", False, True)
    b = tsc.Asset("2", "Zero", "WR", (), 5.0, 2, "high", False, True)
    total, started = tsc.lineup_solve([a, b], {"1": None, "2": 0.0}, slots)
    assert started == ["2"] and total == 0.0  # a real zero is assignable; None is not


def test_a_package_is_not_the_sum_of_its_single_moves():
    """Two received WRs compete for one WR slot: each alone helps, together they do not add."""
    rules = tsc.LeagueRules(("WR",), None, 58)

    def wr(sid: str) -> tsc.Asset:
        return tsc.Asset(sid, f"WR{sid}", "WR", (), 1000.0, 1, "high", False, True)

    base, in1, in2 = wr("1"), wr("2"), wr("3")
    points = tsc.PointsTable(
        {1: {"1": 10.0, "2": 12.0, "3": 11.0}}, {1: frozenset({"1", "2", "3"})}
    )
    before_total = tsc.lineup_solve([base], points.by_week[1], rules)[0]
    singles = tsc.sum_of_single_moves([base], [], [in1, in2], points, rules, [before_total])
    whole = tsc.lineup_solve([base, in1, in2], points.by_week[1], rules)[0] - before_total
    assert singles == [pytest.approx(3.0)]  # +2 for the 12, +1 for the 11
    assert whole == pytest.approx(2.0)  # only the 12 starts
    assert whole != pytest.approx(singles[0])


def test_a_cut_is_costed_in_lineup_points_and_legality_is_slot_fill_only():
    """The ladder guards the COUNT of fillable slots, not the points; the census measures both."""
    rules = tsc.LeagueRules(("QB", "K"), None, 58)

    def a(sid: str, pos: str) -> tsc.Asset:
        return tsc.Asset(sid, f"P{sid}", pos, (), 1000.0, 1, "high", False, True)

    qb1, qb2, k1 = a("1", "QB"), a("2", "QB"), a("3", "K")
    weeks = {w: {"1": 20.0, "2": 5.0, "3": 8.0} for w in (1, 2)}
    points = tsc.PointsTable(weeks, {w: frozenset(weeks[w]) for w in weeks})
    roster = [qb1, qb2, k1]
    assert tsc.cut_cost_in_lineup_points(roster, qb2, points, rules) == (0.0, True)
    cost, legal = tsc.cut_cost_in_lineup_points(roster, qb1, points, rules)
    assert cost == pytest.approx(15.0) and legal  # qb2 backfills the slot
    cost, legal = tsc.cut_cost_in_lineup_points(roster, k1, points, rules)
    assert cost == pytest.approx(8.0) and not legal  # the only kicker: the K slot goes unfilled


def test_removal_is_by_multiplicity_not_by_name(world):
    roster = list(world["rosters"][0].assets)
    one = roster[0]
    assert len(tsc._without(roster + [one], [one])) == len(roster)


def test_a_two_for_three_at_the_roster_limit_forces_one_drop_and_replays_the_final_roster(world):
    give = (asset(world, "AWR0"), asset(world, "AWR1"))
    recv = (asset(world, "BWR0"), asset(world, "BWR1"), asset(world, "BTE0"))
    block = tsc.team_transaction_impact(
        world["contract"],
        world["rosters"][0],
        give,
        recv,
        world["assets"],
        world["points"],
        world["rules"],
    )
    cap = block["capacity"]
    assert (cap["rosterLimit"], cap["sizeBefore"], cap["sizeAfter"]) == (58, 58, 59)
    assert cap["requiresDrops"] is True and cap["overLimitAfter"] == 1
    assert len(cap["forcedDrops"]) == 1 and cap["forcedDropsMissingFromRoster"] == 0
    assert cap["owner"].startswith("src.trade.roster_capacity")
    replay = block["bestBallReplay"]
    # the forced drop is applied before the final lineup is replayed: 58 -> 59 landed -> 58 final
    assert replay["rosterSizes"] == {"before": 58, "landed": 59, "final": 58}
    assert replay["weeks"] == 3 and len(replay["weeklyDelta"]) == 3
    assert replay["delta"] == pytest.approx(replay["final"] - replay["before"], abs=0.011)
    assert replay["weeksImproved"] + replay["weeksWorsened"] <= replay["weeks"]
    assert block["isVerdict"] is False
    # received players can only start if they are in the final roster
    assert set(block["startedWeeks"]) >= {a.name for a in (*give, *recv)}


def test_a_trade_with_room_forces_nothing(world):
    # the other side of the same trade receives fewer players than it gives
    give = (asset(world, "BWR0"), asset(world, "BWR1"), asset(world, "BTE0"))
    recv = (asset(world, "AWR0"), asset(world, "AWR1"))
    block = tsc.team_transaction_impact(
        world["contract"],
        world["rosters"][1],
        give,
        recv,
        world["assets"],
        world["points"],
        world["rules"],
    )
    assert block["capacity"]["sizeAfter"] == 57
    assert block["capacity"]["forcedDrops"] == []
    assert block["capacity"]["requiresDrops"] is False


def test_the_replay_never_changes_the_before_roster(world):
    before_ids = [a.sid for a in world["rosters"][0].assets]
    tsc.team_transaction_impact(
        world["contract"],
        world["rosters"][0],
        (asset(world, "AWR0"),),
        (asset(world, "BWR0"),),
        world["assets"],
        world["points"],
        world["rules"],
    )
    assert [a.sid for a in world["rosters"][0].assets] == before_ids


# ── the three stay apart ──────────────────────────────────────────────────────────────────────
def _forbidden_blend_keys(obj, found=None):
    found = [] if found is None else found
    if isinstance(obj, Mapping):
        for k, v in obj.items():
            if str(k).lower() in {
                "combined",
                "blended",
                "blend",
                "score",
                "verdict",
                "recommendation",
            }:
                found.append(k)
            _forbidden_blend_keys(v, found)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _forbidden_blend_keys(v, found)
    return found


def test_an_example_carries_three_named_blocks_and_no_blended_number(world):
    spec = next(s for s in tsc.CATEGORIES if s.id == "starter_upgrade_2for1")
    trade = tsc.Trade(
        spec.id,
        0,
        1,
        (asset(world, "AWR1"), asset(world, "AWR2")),
        (asset(world, "BWR0"),),
    )
    ex = tsc.build_example(
        "T1",
        spec,
        trade,
        world["contract"],
        world["rosters"],
        world["assets"],
        world["points"],
        utility_table(world),
        world["rules"],
        {"category": spec.id},
    )
    for side in ("A", "B"):
        blocks = ex["sides"][side]
        assert [
            blocks[k]["quantity"] for k in ("marketPrice", "leagueUtility", "teamTransactionImpact")
        ] == [
            "Market Price",
            "League Utility",
            "Team Transaction Impact",
        ]
        assert "SHADOW" in blocks["leagueUtility"]["status"]
        assert "read-only" in blocks["marketPrice"]["status"]
    assert ex["isVerdict"] is False and ex["readout"]["note"].startswith("descriptive only")
    assert _forbidden_blend_keys(ex) == []
    # each readout is about one quantity; none references another quantity's number
    assert set(ex["readout"]) == {"marketPrice", "leagueUtilityD", "teamTransactionImpact", "note"}
    md = tsc.render_markdown({"examples": [ex]})
    assert (
        "Market Price" in md and "League Utility (SHADOW)" in md and "Team Transaction Impact" in md
    )


def test_the_readout_says_unavailable_when_league_utility_is_missing(world):
    spec = next(s for s in tsc.CATEGORIES if s.id == "offense_for_idp_rookie_1for1")
    trade = tsc.Trade(spec.id, 0, 1, (asset(world, "ATE0"),), (asset(world, "BDL0"),))
    ex = tsc.build_example(
        "T2",
        spec,
        trade,
        world["contract"],
        world["rosters"],
        world["assets"],
        world["points"],
        utility_table(world, skip=("BDL0",)),
        world["rules"],
        {},
    )
    assert ex["readout"]["leagueUtilityD"]["favours"] == "unavailable"
    assert ex["sides"]["A"]["leagueUtility"]["net"]["D"] is None
    assert "UNAVAILABLE" in tsc.render_markdown({"examples": [ex]})


# ── example selection ─────────────────────────────────────────────────────────────────────────
def _pick(world, spec_id, **kw):
    spec = next(s for s in tsc.CATEGORIES if s.id == spec_id)
    return spec, tsc.sample_trade(
        spec, world["rosters"], utility_table(world), world["rules"], max_draws=4000, **kw
    )


def test_selection_is_seeded_reproducible_and_market_fair(world):
    spec, (t1, s1) = _pick(world, "offense_for_idp_1for1")
    _, (t2, s2) = _pick(world, "offense_for_idp_1for1")
    assert t1 is not None and t1.key == t2.key and s1 == s2
    reading = tsc.market_price(t1.give, t1.recv)
    assert reading["band"]["level"] == "fair"
    assert t1.give[0].is_offense and t1.recv[0].is_idp and t1.a_index != t1.b_index
    assert tsc._topology_ok(t1.give, t1.recv)
    _, (t3, _) = _pick(world, "offense_for_idp_1for1", seed=tsc.SEED + 1)
    assert t3 is not None


def test_selection_keeps_only_market_fair_trades_across_seeds():
    """A tiny universe in which only one pairing is fair: every seed must land on it."""

    def wr(sid: str, value: float) -> tsc.Asset:
        return tsc.Asset(sid, f"WR{sid}", "WR", (), value, 1, "high", False, True)

    a_side = tsc.Roster(0, (wr("1", 1000.0), wr("2", 5000.0)), {})
    b_side = tsc.Roster(1, (wr("3", 1010.0), wr("4", 9000.0)), {})
    spec = tsc.CategorySpec("tiny", "tiny", 1, 1, lambda a, u: True, lambda a, u: True)
    rules = tsc.LeagueRules(("WR",), None, 58)
    for seed in range(20):
        trade, summary = tsc.sample_trade(
            spec, [a_side, b_side], {}, rules, seed=seed, max_draws=400, keep=16
        )
        assert trade is not None and summary["marketFairKept"] == 16
        values = {trade.give[0].value, trade.recv[0].value}
        assert values == {1000.0, 1010.0}, (seed, values)
        assert tsc.market_price(trade.give, trade.recv)["band"]["level"] == "fair"


def test_selection_reads_no_outcome():
    params = set(inspect.signature(tsc.sample_trade).parameters)
    assert not params & {"points", "weeks", "replay", "outcomes"}
    tree = ast.parse(inspect.getsource(tsc.sample_trade).lstrip())
    used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    used |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    outcome_readers = {"replay", "lineup_solve", "team_transaction_impact", "score_weeks", "points"}
    assert not used & outcome_readers, used & outcome_readers


def test_the_roster_limit_category_needs_a_full_side_a(world):
    spec = next(s for s in tsc.CATEGORIES if s.id == "cut_requiring_2for3")
    assert spec.needs_full_roster
    relaxed = tsc.LeagueRules(world["rules"].slots, world["rules"].slot_eligibility, 59)
    trade, summary = tsc.sample_trade(
        spec, world["rosters"], utility_table(world), relaxed, max_draws=500
    )
    assert trade is None and summary["marketFairKept"] == 0


def test_the_categories_cover_the_directive_kinds():
    ids = {s.id for s in tsc.CATEGORIES}
    assert any(i.startswith("offense_for_idp") for i in ids)
    assert "starter_upgrade_2for1" in ids
    assert "depth_package_1for2" in ids
    assert any(i.startswith("cut_requiring") for i in ids)
    assert 4 <= len(tsc.CATEGORIES) <= 6
    # every generated shape is one the live generators would propose
    for s in tsc.CATEGORIES:
        assert abs(s.n_give - s.n_recv) <= 1


# ── hygiene and isolation ─────────────────────────────────────────────────────────────────────
def test_public_safety_refuses_private_keys_and_values(world):
    forbidden = tsc.forbidden_values(world["contract"])
    assert "Alpha Private Team" in forbidden and "owner-alpha-123456" in forbidden
    tsc.assert_public_safe({"examples": [{"name": "Justin Jefferson"}]}, forbidden)
    with pytest.raises(ValueError):
        tsc.assert_public_safe({"ownerId": "x"}, forbidden)
    with pytest.raises(ValueError):
        tsc.assert_public_safe({"a": {"roster_id": 3}}, forbidden)
    with pytest.raises(ValueError):
        tsc.assert_public_safe({"note": "traded away by Alpha Private Team"}, forbidden)
    with pytest.raises(ValueError):
        tsc.assert_public_safe({"id": "999000111222333"}, forbidden + ["999000111222333"])


def test_an_example_built_from_the_world_is_public_safe(world):
    spec = next(s for s in tsc.CATEGORIES if s.id == "depth_package_1for2")
    trade = tsc.Trade(
        spec.id, 0, 1, (asset(world, "AWR0"),), (asset(world, "BWR3"), asset(world, "BTE1"))
    )
    ex = tsc.build_example(
        "T5",
        spec,
        trade,
        world["contract"],
        world["rosters"],
        world["assets"],
        world["points"],
        utility_table(world),
        world["rules"],
        {},
    )
    tsc.assert_public_safe(ex, tsc.forbidden_values(world["contract"]))


def test_nothing_in_src_imports_the_shadow_script():
    for path in (REPO / "src").rglob("*.py"):
        assert "trade_shadow_comparison" not in path.read_text(
            encoding="utf-8", errors="ignore"
        ), path


def test_the_script_writes_only_its_evidence_and_cache_and_sets_no_flag():
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    writers: set[str] = set()
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for node in ast.walk(fn):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in {"write_text", "write_bytes", "mkdir", "extractall"}:
                    writers.add(fn.name)
    # evidence file, the cache, the temporary pinned-tree build: nothing else touches disk
    assert writers <= {
        "write_evidence",
        "write_doc_block",
        "get",
        "__init__",
        "build_contract_at_tree",
    }, writers
    text = SCRIPT.read_text(encoding="utf-8")
    assert "RISKIT_FEATURE" not in text and "os.environ[" not in text
    assert "set_flag" not in text and "feature_flags" not in text


def test_the_script_uses_the_live_owners_and_defines_no_second_one():
    text = SCRIPT.read_text(encoding="utf-8")
    for owner in (
        "package_model.adjusted_pair_totals",
        "fairness_bands.classify_packages",
        "solve_optimal_assignment",
        "rc.assess_roster_capacity",
        "rc.build_capacity_context",
        "topology_is_allowed",
        "compute_weekly_points",
    ):
        assert owner in text, owner
    # no private flex table, no second package model
    assert "FLEX_ELIGIBLE" not in text and "def adjust_package" not in text


# ── the committed evidence ────────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def evidence() -> dict:
    if not EVIDENCE.exists():
        pytest.skip("evidence file not generated")
    return json.loads(EVIDENCE.read_text(encoding="utf-8"))


def test_evidence_is_pinned_to_lane_a_and_does_not_promote(evidence):
    assert evidence["promotes"] is False
    agree = evidence["inputs"]["laneAAgreement"]
    assert agree == {"archiveSha256": True, "servedBoardSha256": True, "scoringFingerprint": True}
    assert evidence["inputs"]["servedBoard"]["pinned"] is True
    assert evidence["inputs"]["league"]["slotsAgreeWithSleeperRosterPositions"] is True
    assert evidence["inputs"]["packageModel"]["id"] == "geom_q078_v1"
    assert evidence["inputs"]["leagueUtilitySource"]["promotes"] is False


def test_evidence_scorer_and_solver_reproduce_the_host(evidence):
    w = evidence["inputs"]["weeklyPoints"]
    chk = w["scorerCheckVsHostAwardedPoints"]
    assert chk["within0_01"] == chk["playerWeeksCompared"] > 3000
    assert chk["hostAwardedNonzeroWithoutALine"] == 0
    solver = w["solverCheckVsHostTeamTotals"]
    assert solver["within0_015"] == solver["teamWeeksQualifying"]


def test_evidence_is_aggregate_and_public_safe(evidence):
    tsc.assert_public_safe(evidence)
    text = json.dumps(evidence)
    assert "api.sleeper.app" not in text and "leagueId" not in text


def test_evidence_covers_the_directive_trade_kinds(evidence):
    cats = {e["category"] for e in evidence["examples"]}
    assert 4 <= len(evidence["examples"]) <= 6
    assert any(c.startswith("offense_for_idp") for c in cats)
    assert {"starter_upgrade_2for1", "depth_package_1for2", "cut_requiring_2for3"} <= cats


def test_evidence_market_numbers_recompute_from_the_stated_assets(evidence):
    for ex in evidence["examples"]:
        for side in ex["sides"].values():
            m = side["marketPrice"]
            if m["state"] != "priced":
                continue
            gv = [a["boardValue"] for a in side["gives"]]
            rv = [a["boardValue"] for a in side["receives"]]
            send_adj, recv_adj, _, _ = package_model.adjusted_pair_totals(gv, rv)
            assert m["sendAdjusted"] == pytest.approx(send_adj, abs=0.11)
            assert m["receiveAdjusted"] == pytest.approx(recv_adj, abs=0.11)
            assert m["band"]["level"] == "fair"  # the selection rule


def test_evidence_league_utility_never_scores_an_unavailable_asset_as_zero(evidence):
    saw_unavailable = False
    for ex in evidence["examples"]:
        for side in ex["sides"].values():
            lu = side["leagueUtility"]
            rows = [*lu["give"], *lu["receive"]]
            for r in rows:
                if r["state"] == "unavailable":
                    saw_unavailable = True
                    assert r["D"] is None and r["reason"]
            if not lu["complete"]:
                assert lu["net"]["D"] is None
            else:
                want = sum(r["D"] for r in lu["receive"]) - sum(r["D"] for r in lu["give"])
                assert lu["net"]["D"] == pytest.approx(want, abs=0.011)
    assert saw_unavailable, "the unscorable-rookie example must show UNAVAILABLE"


def test_evidence_team_impact_is_internally_consistent(evidence):
    for ex in evidence["examples"]:
        for side in ex["sides"].values():
            t = side["teamTransactionImpact"]
            r = t["bestBallReplay"]
            assert r["delta"] == pytest.approx(r["final"] - r["before"], abs=0.011)
            assert r["weeksImproved"] == sum(1 for x in r["weeklyDelta"] if x > tsc.NO_CHANGE_PTS)
            assert r["weeksWorsened"] == sum(1 for x in r["weeklyDelta"] if x < -tsc.NO_CHANGE_PTS)
            cap = t["capacity"]
            assert cap["sizeAfter"] - cap["sizeBefore"] == len(side["receives"]) - len(
                side["gives"]
            )
            assert len(cap["forcedDrops"]) == (cap["overLimitAfter"] or 0)
            assert cap["forcedDropsMissingFromRoster"] == 0
            if not cap["forcedDrops"]:
                assert r["delta"] == pytest.approx(r["deltaBeforeCleanup"], abs=0.011)
            assert t["isVerdict"] is False


def test_evidence_has_a_cut_requiring_example_with_a_real_forced_drop(evidence):
    ex = next(e for e in evidence["examples"] if e["category"] == "cut_requiring_2for3")
    assert len(ex["sides"]["A"]["teamTransactionImpact"]["capacity"]["forcedDrops"]) == 1


def test_evidence_tie_census_measures_the_incumbent_tie_break(evidence):
    c = evidence["cutLadderTieCensus"]
    assert c["rosters"] == 12 and c["rostersWithATiedFirstCut"] == 12
    assert "OFF" in c["rule"] and c["tiedSetSize"]["max"] >= c["tiedSetSize"]["median"] > 1
    assert c["firstCutIsAlphabeticallyFirstOfTheTiedSet"] >= 10
    lineup = c["replayedLineupPointsLostByTheChosenCut"]
    assert lineup["rostersMeasured"] == 12
    # the ladder guards slot COUNT, so its name-chosen cut often costs best-ball points
    # while every tied set also holds a legal cut that costs none
    assert lineup["rostersWhereTheChosenCutCostsPoints"] >= 1
    assert lineup["rostersWhoseTiedSetHoldsALegalCutThatCostsNothing"] == 12
    assert lineup["cheapestLegalCutInTheTiedSetMean"] == 0.0


def test_evidence_blocks_are_never_blended(evidence):
    assert _forbidden_blend_keys(evidence["examples"]) == []
    for ex in evidence["examples"]:
        assert ex["isVerdict"] is False


def test_the_doc_embeds_the_generated_results_block(evidence):
    if not DOC.exists():
        pytest.skip("recommendations doc not written")
    text = DOC.read_text(encoding="utf-8")
    start, end = "<!-- table:shadow -->", "<!-- /table:shadow -->"
    assert start in text and end in text
    body = text.split(start, 1)[1].split(end, 1)[0].strip("\n")
    assert body == tsc.render_markdown(evidence).strip("\n"), (
        "H_RECOMMENDATIONS.md drifted from the evidence; run "
        "`python scripts/idp_accuracy/trade_shadow_comparison.py --offline --write-doc`"
    )
