"""Unified Manager of the Year (owner decision 2026-09-28).

Synthetic adversarial cases for every regression the directive (§14) names,
each on a league small enough to check by hand.  Methodology:
``docs/awards/MANAGER_OF_THE_YEAR_METHODOLOGY.md``.  Surplus arithmetic:
every WR's replacement level is 10.0, so a WR scoring 25 in a week carries
15 surplus.
"""

from __future__ import annotations

import copy
import math
import unittest
from unittest import mock

from src.public_league import awards
from src.public_league import manager_of_the_year as moty
from tests.public_league.fixtures import build_test_snapshot
from tests.public_league.moty_fixtures import LEVELS, League, owner


class _Case(unittest.TestCase):
    """Published numbers carry ``moty.PUBLISHED_DECIMALS`` (4) decimals."""

    def assertAlmostEqual(self, first, second, places=None, msg=None, delta=None):  # noqa: N802
        if places is None and delta is None:
            places = 3
        super().assertAlmostEqual(first, second, places=places, msg=msg, delta=delta)


def evaluate(league: League, *, valuation_factory=None) -> dict:
    snapshot, season = league.build()
    return moty.build_season(snapshot, season, LEVELS, valuation_factory=valuation_factory)


def row(evaluation: dict, rid: int) -> dict:
    return next(r for r in evaluation["rows"] if r["ownerId"] == owner(rid))


def raw(evaluation: dict, rid: int, channel: str) -> dict:
    return row(evaluation, rid)["components"][channel]["raw"]


def score(evaluation: dict, rid: int, channel: str):
    return row(evaluation, rid)["components"][channel]["score"]


def tprod(evaluation: dict, rid: int):
    """T's PRODUCTION half: the ledger measurement the §14 trade regressions
    pin.  (T itself is scored only when its future-value half is complete.)"""
    return row(evaluation, rid)["components"]["T"]["productionScore"]


def flat_valuation(value: float = 1000.0):
    """A valuation source that prices every asset at the same value, so the
    trade future-value channel is COMPLETE and neutral (FV = 50)."""

    def factory(requests):
        list(requests)
        return lambda asset, instant: value

    return factory


class NormalizationTests(_Case):
    def test_zero_net_value_is_exactly_the_midpoint(self):
        self.assertEqual(moty.normalize_management(0.0, 13, 50.0), 50.0)
        self.assertEqual(moty.normalize_future_value_pct(0.0), 50.0)

    def test_bounded_monotonic_and_symmetric(self):
        xs = [-1e6, -500.0, -10.0, -0.01, 0.0, 0.01, 10.0, 500.0, 1e6]
        ys = [moty.normalize_management(x, 13, 50.0) for x in xs]
        self.assertEqual(ys, sorted(ys))
        self.assertTrue(all(0.0 <= y <= 100.0 for y in ys))
        for x in (3.0, 250.0):
            self.assertAlmostEqual(
                moty.normalize_management(x, 13, 50.0) + moty.normalize_management(-x, 13, 50.0),
                100.0,
            )

    def test_predeclared_scale_not_the_field(self):
        # +KAPPA*sigma per week maps to 50 + 50*tanh(1) whatever anyone else did.
        self.assertAlmostEqual(
            moty.normalize_management(0.5 * 40.0 * 10, 10, 40.0), 50 + 50 * math.tanh(1)
        )

    def test_unscalable_is_none_not_fifty(self):
        self.assertIsNone(moty.normalize_management(10.0, 0, 50.0))
        self.assertIsNone(moty.normalize_management(10.0, 13, 0.0))


class NoGateTests(_Case):
    """Every manager is ranked: no playoff, record or standings gate."""

    def _league(self):
        lg = League(weeks=4, teams=4)
        # Manager 4 dominates weekly scoring; manager 1 wins the title.
        for wk in range(1, 5):
            for rid, pts in ((1, 120.0), (2, 110.0), (3, 100.0), (4, 150.0)):
                lg.team_points[(wk, rid)] = pts
        lg.bracket = [{"r": 1, "t1": 1, "t2": 2, "w": 1, "l": 2, "p": 1}]
        return lg

    def test_non_playoff_manager_can_win(self):
        lg = self._league()
        # Manager 4 also wins a trade clearly; the bracket champion does not.
        lg.points = {"r3p0": 30.0, "r4p0": 11.0}
        lg.trade(1, 4, ["r4p0"], 3, ["r3p0"])
        ev = evaluate(lg, valuation_factory=flat_valuation())
        self.assertEqual(ev["status"], "final")
        self.assertEqual(ev["scoreBasis"], "full")
        top = ev["rows"][0]
        self.assertEqual(top["ownerId"], owner(4))
        self.assertEqual(top["components"]["P"]["score"], 0.0)
        self.assertFalse(top["components"]["P"]["madePlayoffs"])
        self.assertEqual(len([r for r in ev["rows"] if r["score"] is not None]), 4)

    def test_below_500_manager_is_not_excluded_by_record_and_can_win(self):
        # Manager 3 is the league's second-best scorer every week but always
        # meets manager 4, the best: a 0-4 head-to-head record.  No record
        # (or playoff) rule may exclude or discount them -- all-play and
        # management decide.
        lg = self._league()
        for wk in range(1, 5):
            for rid, pts in ((1, 120.0), (2, 110.0), (3, 145.0), (4, 150.0)):
                lg.team_points[(wk, rid)] = pts
        lg.pairings = {wk: [(3, 4), (1, 2)] for wk in range(1, 5)}
        lg.points = {"fa1": 40.0, "d1": 40.0, "r4p0": 30.0}
        lg.waiver(1, 3, add="fa1")  # a productive pickup
        lg.draft([(3, "d1", 21)])  # a strong pick against a band-3 expectation
        lg.free_agent(1, 4, drop="r4p0")  # manager 4 releases a producer...
        lg.free_agent(1, 1, add="r4p0")  # ...who is rostered elsewhere
        snapshot, season = lg.build()
        for wk in range(1, 5):  # manager 3's host record is 0-4
            by_rid = {e["roster_id"]: e for e in season.matchups_by_week[wk]}
            self.assertLess(by_rid[3]["points"], by_rid[4]["points"])
            self.assertEqual(by_rid[3]["matchup_id"], by_rid[4]["matchup_id"])
        for r in season.rosters:
            if r["roster_id"] == 3:
                r["settings"] = {"wins": 0, "losses": 4, "ties": 0}
        ev = moty.build_season(snapshot, season, LEVELS)
        top = ev["rows"][0]
        self.assertEqual(top["ownerId"], owner(3))
        self.assertEqual(top["rank"], 1)
        self.assertIsNotNone(top["score"])
        self.assertFalse(top["components"]["P"]["madePlayoffs"])
        self.assertEqual({r["rank"] is not None for r in ev["rows"]}, {True})

    def test_exceptional_champion_can_win(self):
        lg = self._league()
        for wk in range(1, 5):
            lg.team_points[(wk, 1)] = 200.0  # best every week AND champion
        ev = evaluate(lg)
        self.assertEqual(ev["rows"][0]["ownerId"], owner(1))
        self.assertEqual(ev["rows"][0]["components"]["P"]["score"], 100.0)

    def test_championship_is_valuable_not_automatic(self):
        ev = evaluate(self._league())
        champ = row(ev, 1)
        self.assertEqual(champ["contributions"]["P"], 10.0)  # at most 10 points
        self.assertNotEqual(ev["rows"][0]["ownerId"], owner(1))

    def test_no_row_carries_an_outside_the_race_label(self):
        ev = evaluate(self._league())
        for r in ev["rows"]:
            self.assertNotIn("eligible", r)
            self.assertNotIn("reason", r)


class AllPlayTests(_Case):
    def test_all_play_ignores_the_schedule(self):
        lg = League(weeks=3, teams=4)
        for wk in range(1, 4):
            for rid, pts in ((1, 90.0), (2, 120.0), (3, 60.0), (4, 100.0)):
                lg.team_points[(wk, rid)] = pts
        a = {r: score(evaluate(lg), r, "A") for r in range(1, 5)}
        lg.pairings = {wk: [(1, 3), (2, 4)] for wk in range(1, 4)}
        b = {r: score(evaluate(lg), r, "A") for r in range(1, 5)}
        self.assertEqual(a, b)
        self.assertAlmostEqual(a[2], 100.0)
        self.assertAlmostEqual(a[3], 0.0)

    def test_ties_zero_negative_and_missing(self):
        lg = League(weeks=2, teams=4)
        lg.team_points.update(
            {
                (1, 1): 100.0,
                (1, 2): 100.0,  # tie with 1
                (1, 3): 0.0,  # a real zero
                (1, 4): -5.0,  # a real negative
                (2, 1): 50.0,
                (2, 2): 40.0,
                (2, 3): 30.0,
            }
        )
        lg.missing_entries.add((2, 4))  # no score at all: missing, not zero
        ev = evaluate(lg)
        # wk1: 1 beats 3,4 and ties 2 -> 2.5/3; wk2: beats 2,3 -> 2/2.
        self.assertAlmostEqual(score(ev, 1, "A"), 100 * ((2.5 / 3) + 1.0) / 2)
        self.assertAlmostEqual(score(ev, 3, "A"), 100 * ((1 / 3) + 0.0) / 2)
        self.assertAlmostEqual(score(ev, 4, "A"), 0.0)
        a4 = row(ev, 4)["components"]["A"]
        self.assertEqual(a4["raw"]["weeksObserved"], 1)
        self.assertEqual(a4["coverage"], "partial")
        self.assertEqual(row(ev, 1)["components"]["A"]["coverage"], "complete")


class TradeTests(_Case):
    def test_no_trade_is_exactly_neutral(self):
        ev = evaluate(League(weeks=4))
        for rid in range(1, 5):
            self.assertEqual(score(ev, rid, "T"), 50.0)
            self.assertEqual(raw(ev, rid, "T")["trades"], 0)

    def test_bad_trade_is_negative_and_mirrors_the_partner(self):
        lg = League(weeks=4, points={"r1p0": 25.0, "r2p0": 12.0})
        lg.trade(2, 1, ["r1p0"], 2, ["r2p0"])
        ev = evaluate(lg)
        # weeks 2-4: o1 gains 2/wk, loses 15/wk.
        self.assertAlmostEqual(raw(ev, 1, "T")["netSurplus"], 3 * (2 - 15))
        self.assertAlmostEqual(raw(ev, 2, "T")["netSurplus"], 3 * (15 - 2))
        self.assertLess(tprod(ev, 1), 50.0)
        self.assertAlmostEqual(tprod(ev, 1) + tprod(ev, 2), 100.0)
        # With a neutral, complete future-value channel the trade score is
        # the same verdict, halved toward the midpoint.
        full = evaluate(lg, valuation_factory=flat_valuation())
        self.assertLess(score(full, 1, "T"), 50.0)
        self.assertAlmostEqual(score(full, 1, "T") + score(full, 2, "T"), 100.0)

    def test_star_acquired_for_excessive_capital_is_not_automatically_good(self):
        lg = League(
            weeks=4,
            points={"r1p0": 20.0, "r1p1": 20.0, "r1p2": 20.0, "r2p0": 35.0},
        )
        lg.trade(1, 1, ["r1p0", "r1p1", "r1p2"], 2, ["r2p0"])
        ev = evaluate(lg)
        self.assertAlmostEqual(raw(ev, 1, "T")["netSurplus"], 4 * (25 - 30))
        self.assertLess(tprod(ev, 1), 50.0)

    def test_round_trip_cannot_manufacture_value(self):
        lg = League(weeks=6, points={"r1p0": 20.0, "r2p0": 20.0})
        for _ in range(3):
            lg.trade(2, 1, ["r1p0"], 2, ["r2p0"])
            lg.trade(3, 1, ["r2p0"], 2, ["r1p0"])
        ev = evaluate(lg)
        for rid in (1, 2):
            self.assertEqual(raw(ev, rid, "T")["netSurplus"], 0.0)
            self.assertEqual(tprod(ev, rid), 50.0)

    def test_reacquisition_credits_only_the_weeks_away(self):
        lg = League(weeks=5, points={"r1p0": 20.0, "r2p0": 30.0})
        lg.trade(2, 1, ["r1p0"], 2, ["r2p0"])
        lg.trade(4, 1, ["r2p0"], 2, ["r1p0"])
        ev = evaluate(lg)
        # o1 held r2p0 in weeks 2-3 (+20/wk) instead of r1p0 (-10/wk); back to
        # baseline from week 4 -- nothing more, in either direction.
        self.assertAlmostEqual(raw(ev, 1, "T")["netSurplus"], 2 * (20 - 10))
        self.assertAlmostEqual(raw(ev, 2, "T")["netSurplus"], -2 * (20 - 10))

    def test_trade_count_earns_nothing(self):
        lg = League(weeks=4)  # every player scores 0 -> no surplus anywhere
        for leg in (1, 2, 3):
            lg.trade(leg, 1, [f"r1p{leg - 1}"], 2, [f"r2p{leg - 1}"])
        ev = evaluate(lg)
        self.assertEqual(raw(ev, 1, "T")["trades"], 3)
        self.assertEqual(tprod(ev, 1), 50.0)
        full = evaluate(lg, valuation_factory=flat_valuation())
        self.assertEqual(score(full, 1, "T"), 50.0)


class WaiverTests(_Case):
    def test_drop_and_readd_cycling_is_neutral(self):
        lg = League(weeks=6, points={"r1p0": 30.0})
        for leg in (2, 4):
            lg.free_agent(leg, 1, drop="r1p0")
            lg.free_agent(leg + 1, 1, add="r1p0")
        ev = evaluate(lg)
        self.assertEqual(raw(ev, 1, "W")["netSurplus"], 0.0)
        # The two weeks he sat unrostered are UNKNOWN, not zero-cost.
        self.assertEqual(raw(ev, 1, "W")["unobservedWeeks"], 2)

    def test_no_value_pickups_earn_nothing(self):
        lg = League(weeks=4)
        for i in range(8):
            lg.free_agent(1 + i % 4, 1, add=f"fa{i}")
        ev = evaluate(lg)
        self.assertEqual(score(ev, 1, "W"), 50.0)

    def test_expensive_vs_cheap_equivalent_pickups(self):
        lg = League(weeks=4, points={"fa1": 20.0, "fa2": 20.0})
        lg.waiver(1, 1, add="fa1", bid=50)
        lg.waiver(1, 2, add="fa2", bid=1)
        ev = evaluate(lg)
        w1, w2 = raw(ev, 1, "W"), raw(ev, 2, "W")
        # Same production -> same score: FAAB is not converted to points
        # (its cost is already inside W -- methodology §5.7).
        self.assertEqual(score(ev, 1, "W"), score(ev, 2, "W"))
        self.assertEqual((w1["faabSpent"], w2["faabSpent"]), (50.0, 1.0))
        self.assertEqual((w1["faabSpentPct"], w2["faabSpentPct"]), (50.0, 1.0))
        self.assertFalse(w1["lowCost"])
        self.assertTrue(w2["lowCost"])
        self.assertIn("low-cost", row(ev, 2)["explanation"])
        self.assertNotIn("low-cost", row(ev, 1)["explanation"])

    def test_dropping_a_productive_baseline_player_is_charged(self):
        lg = League(weeks=4, points={"r1p0": 30.0, "fa1": 12.0})
        lg.waiver(2, 1, add="fa1", drop="r1p0")
        lg.free_agent(2, 3, add="r1p0")  # someone else rosters him: observable
        ev = evaluate(lg)
        self.assertAlmostEqual(raw(ev, 1, "W")["netSurplus"], 3 * (2 - 20))


class DraftTests(_Case):
    def test_top_pick_is_not_automatically_the_best_draft(self):
        lg = League(weeks=4, points={"d1": 14.0, "d21": 13.0})
        lg.draft([(1, "d1", 1), (2, "d21", 21)])
        ev = evaluate(lg)
        e1, e3 = moty.ANNUAL_BAND_EXPECTATION[0], moty.ANNUAL_BAND_EXPECTATION[2]
        self.assertAlmostEqual(raw(ev, 1, "D")["netSurplusVsExpectation"], 4 * (4 - e1))
        self.assertAlmostEqual(raw(ev, 2, "D")["netSurplusVsExpectation"], 4 * (3 - e3))
        self.assertLess(score(ev, 1, "D"), 50.0)
        self.assertGreater(score(ev, 2, "D"), 50.0)

    def test_no_picks_is_neutral_not_a_failure(self):
        lg = League(weeks=4, points={"d1": 14.0})
        lg.draft([(1, "d1", 1)])
        ev = evaluate(lg)
        self.assertEqual(raw(ev, 3, "D")["selections"], 0)
        self.assertEqual(score(ev, 3, "D"), 50.0)

    def test_a_traded_pick_is_not_credited_twice(self):
        lg = League(weeks=4, points={"d2": 20.0})
        lg._tx(
            "trade",
            1,
            None,
            None,
            roster_ids=[1, 2],
            draft_picks=[
                {
                    "season": "2025",
                    "round": 1,
                    "roster_id": 2,
                    "owner_id": 1,
                    "previous_owner_id": 2,
                }
            ],
        )
        lg.draft([(1, "d2", 2)])
        ev = evaluate(lg)
        e = moty.ANNUAL_BAND_EXPECTATION[0]
        t1, t2 = raw(ev, 1, "T"), raw(ev, 2, "T")
        d1 = raw(ev, 1, "D")
        self.assertAlmostEqual(t1["draftPickExpectationNet"], 4 * e)
        self.assertAlmostEqual(t2["draftPickExpectationNet"], -4 * e)
        # Trade (obtaining the pick) + draft (using it) = the player's surplus, once.
        self.assertAlmostEqual(t1["netSurplus"] + d1["netSurplusVsExpectation"], 4 * 10.0)

    def test_drafted_player_traded_away_keeps_selection_value_in_d(self):
        lg = League(weeks=4, points={"d1": 30.0, "r2p0": 10.0})
        lg.draft([(1, "d1", 1)])
        lg.trade(3, 1, ["d1"], 2, ["r2p0"])
        ev = evaluate(lg)
        e = moty.ANNUAL_BAND_EXPECTATION[0]
        self.assertAlmostEqual(raw(ev, 1, "D")["netSurplusVsExpectation"], 4 * (20 - e))
        # ...and the trade is charged for the weeks he was gone.
        self.assertAlmostEqual(raw(ev, 1, "T")["netSurplus"], 2 * (0 - 20))
        self.assertAlmostEqual(raw(ev, 2, "T")["netSurplus"], 2 * (20 - 0))

    def test_auction_bands_by_price_rank(self):
        lg = League(weeks=2, points={"a": 20.0, "b": 20.0})
        lg.draft([(1, "a", 1), (2, "b", 2)], kind="auction", amounts=[5, 60])
        snapshot, season = lg.build()
        sels, _, _ = moty._window_selections(snapshot, season)
        by = {s.pid: s for s in sels}
        self.assertEqual((by["b"].pick_no, by["a"].pick_no), (1, 2))
        self.assertEqual((by["b"].amount, by["a"].amount), (60, 5))


class AccountingIdentityTests(_Case):
    def test_channels_telescope_to_the_roster_difference(self):
        lg = League(
            weeks=5,
            points={"r1p0": 22.0, "r2p0": 17.0, "fa1": 15.0, "r1p1": 13.0, "d9": 19.0},
        )
        lg.draft([(1, "d9", 9)])
        lg.trade(2, 1, ["r1p0"], 2, ["r2p0"])
        lg.waiver(3, 1, add="fa1", drop="r1p1")
        lg.free_agent(3, 4, add="r1p1")
        snapshot, season = lg.build()
        led = moty.management_ledger(snapshot, season, LEVELS)
        facts = led["facts"]
        u = moty._Surplus(snapshot, facts, LEVELS)
        base = {"r1p0", "r1p1", "r1p2"}
        held_total = sum((u(p, wk) or 0.0) for wk in facts.weeks for p in facts.holdings[wk][1])
        base_total = sum((u(p, wk) or 0.0) for wk in facts.weeks for p in base)
        t = led["tally"][1]
        total = sum(t[c].credit - t[c].charge for c in ("T", "W", "D"))
        e = moty.ANNUAL_BAND_EXPECTATION[0]
        self.assertAlmostEqual(total, held_total - base_total - e * 5)


class LineupIndependenceTests(_Case):
    def test_best_ball_start_sit_earns_nothing(self):
        lg = League(weeks=4, points={"r1p0": 25.0, "r2p0": 12.0})
        lg.trade(2, 1, ["r1p0"], 2, ["r2p0"])
        a = evaluate(lg)
        snapshot, season = lg.build()
        for entries in season.matchups_by_week.values():
            for e in entries:
                e["starters"] = list(reversed(e["players"]))[:1]
        b = moty.build_season(snapshot, season, LEVELS)
        for rid in range(1, 5):
            for ch in ("T", "W", "D"):
                self.assertEqual(score(a, rid, ch), score(b, rid, ch))


class WindowTests(_Case):
    def test_no_postseason_management_weeks(self):
        lg = League(weeks=4, points={"fa1": 40.0})
        base = evaluate(lg)
        lg.waiver(5, 1, add="fa1")  # leg 5 = first playoff week
        after = evaluate(lg)
        self.assertEqual(after["coverage"]["counts"]["waiverMoves"], 0)
        self.assertEqual(score(after, 1, "W"), score(base, 1, "W"))

    def test_missing_transaction_history_is_not_no_trades(self):
        lg = League(weeks=4, points={"r1p0": 25.0})
        snapshot, season = lg.build()
        snapshot.seasons = [season]  # the previous league is not in the snapshot
        ev = moty.build_season(snapshot, season, LEVELS)
        self.assertEqual(ev["coverage"]["baseline"], "unavailable")
        self.assertIn("window_baseline_unavailable", ev["coverage"]["reasons"])
        for r in ev["rows"]:
            self.assertIsNone(r["components"]["T"]["score"])
            self.assertIsNone(r["score"])
            self.assertIsNone(r["rank"])

    def test_inaugural_season_starts_from_empty_rosters(self):
        lg = League(weeks=3, inaugural=True, base={1: [], 2: [], 3: [], 4: []})
        lg.draft([(1, "s1", 1), (2, "s2", 2)])
        snapshot, season = lg.build()
        ev = moty.build_season(snapshot, season, LEVELS)
        self.assertEqual(ev["coverage"]["baseline"], "inaugural")

    def test_stat_correction_changes_the_result(self):
        lg = League(weeks=4, points={"r1p0": 25.0, "r2p0": 12.0})
        lg.trade(2, 1, ["r1p0"], 2, ["r2p0"])
        snapshot, season = lg.build()
        before = moty.build_season(snapshot, season, LEVELS)
        for e in season.matchups_by_week[3]:
            if "r2p0" in e["players_points"]:
                e["players_points"]["r2p0"] = 32.0  # corrected upward
        after = moty.build_season(snapshot, season, LEVELS)
        self.assertAlmostEqual(
            raw(after, 1, "T")["netSurplus"] - raw(before, 1, "T")["netSurplus"], 20.0
        )
        self.assertEqual(raw(after, 3, "T"), raw(before, 3, "T"))


class PostseasonTests(_Case):
    def _bracket_league(self, final_winner=1):
        lg = League(weeks=2, teams=6)
        lg.bracket = [
            {"r": 1, "t1": 3, "t2": 6, "w": 3, "l": 6},
            {"r": 1, "t1": 4, "t2": 5, "w": 4, "l": 5},
            {"r": 2, "t1": 1, "t2": 4, "w": 1, "l": 4},
            {"r": 2, "t1": 2, "t2": 3, "w": 3, "l": 2},
            {
                "r": 3,
                "t1": 1,
                "t2": 3,
                "w": final_winner,
                "l": 3 if final_winner == 1 else 1,
                "p": 1,
            },
            {"r": 3, "t1": 4, "t2": 2, "w": 4, "l": 2, "p": 3},  # placement game: ignored
        ]
        return lg

    def test_actual_bracket_same_stage_ties_and_no_bye_wins(self):
        ev = evaluate(self._bracket_league())
        p = {rid: row(ev, rid)["components"]["P"]["score"] for rid in range(1, 7)}
        self.assertAlmostEqual(p[1], 100.0)
        self.assertAlmostEqual(p[3], 100 * (7 - 2) / 6)
        # Bye team 2 and round-1 winner 4 both lost in round 2: tied at 3.5,
        # whatever the third-place game said.
        self.assertAlmostEqual(p[2], 100 * (7 - 3.5) / 6)
        self.assertAlmostEqual(p[4], p[2])
        self.assertAlmostEqual(p[5], 100 * (7 - 5.5) / 6)
        self.assertAlmostEqual(p[6], p[5])

    def test_unresolved_bracket_is_pending_and_provisional(self):
        lg = self._bracket_league(final_winner=None)
        lg.status = "in_season"
        ev = evaluate(lg)
        self.assertEqual(ev["status"], "provisional")
        for r in ev["rows"]:
            self.assertIsNone(r["components"]["P"]["score"])
            self.assertEqual(r["components"]["P"]["status"], "pending")
            self.assertIsNone(r["contributions"]["P"])
            self.assertAlmostEqual(r["score"], r["earnedOf90"] / 0.9)

    def test_final_uses_the_full_formula(self):
        ev = evaluate(self._bracket_league())
        for r in ev["rows"]:
            c = r["components"]
            expect = sum(moty.WEIGHTS[k] * c[k]["score"] for k in ("A", "T", "W", "D", "P"))
            self.assertAlmostEqual(r["score"], expect)


class TieTests(_Case):
    @staticmethod
    def _row(oid, score, management, a):
        return {
            "ownerId": oid,
            "score": score,
            "management": management,
            "components": {"A": {"score": a}},
        }

    def test_exact_ties_break_on_management_then_all_play_then_share(self):
        rows = [
            self._row("z", 60.0, 20.0, 50.0),
            self._row("a", 60.0, 25.0, 40.0),  # more management -> ahead
            self._row("m", 60.0, 20.0, 55.0),  # same management, more A
            self._row("b", 60.0, 20.0, 50.0),  # identical to "z": shared rank
        ]
        scored, _ = moty.rank_rows(rows)
        ranks = {r["ownerId"]: (r["rank"], r.get("tied", False)) for r in scored}
        self.assertEqual(ranks["a"], (1, False))
        self.assertEqual(ranks["m"], (2, False))
        self.assertEqual(ranks["z"], (3, True))
        self.assertEqual(ranks["b"], (3, True))

    def test_input_order_and_names_never_decide(self):
        rows = [self._row("b", 60.0, 20.0, 50.0), self._row("a", 60.0, 20.0, 50.0)]
        scored, _ = moty.rank_rows(copy.deepcopy(rows))
        scored_rev, _ = moty.rank_rows(copy.deepcopy(rows[::-1]))
        self.assertEqual({r["rank"] for r in scored}, {1})
        self.assertEqual({r["rank"] for r in scored_rev}, {1})


class FutureValueTests(_Case):
    """T's future-value channel: acquisition-time value at the trade's instant."""

    VALUES = {"r1p0": 5000.0, ("2026", 1): 6500.0, "r2p0": 300.0}

    def _factory(self, missing=()):
        seen = []

        def factory(requests):
            reqs = list(requests)
            seen.extend(reqs)

            def resolve(asset, instant):
                key = (
                    asset.get("playerId")
                    if asset.get("kind") == "player"
                    else (
                        str(asset.get("season")),
                        int(asset.get("round")),
                    )
                )
                if key in missing:
                    return None
                return self.VALUES.get(key)

            return resolve

        return factory, seen

    def _rebuild_league(self):
        lg = League(weeks=4, points={"r1p0": 30.0, "r2p0": 10.0})
        lg.trade(
            2,
            1,
            ["r1p0"],
            2,
            ["r2p0"],
            draft_picks=[
                {
                    "season": "2026",
                    "round": 1,
                    "roster_id": 2,
                    "owner_id": 1,
                    "previous_owner_id": 2,
                }
            ],
        )
        return lg

    def test_valuable_future_picks_are_not_zero_benefit(self):
        factory, seen = self._factory()
        ev = evaluate(self._rebuild_league(), valuation_factory=factory)
        t = row(ev, 1)["components"]["T"]
        self.assertEqual(ev["coverage"]["tradeFutureValue"]["status"], "complete")
        self.assertLess(t["productionScore"], 50.0)  # lost a producer this season
        self.assertGreater(t["futureValueScore"], 50.0)  # got more value back
        self.assertAlmostEqual(t["score"], 0.5 * t["productionScore"] + 0.5 * t["futureValueScore"])
        self.assertEqual(t["coverage"], "complete")
        # Both sides valued at the SAME instant: the trade's own.
        instants = {inst for _asset, inst in seen}
        self.assertEqual(len(instants), 1)

    def test_missing_valuation_means_no_fake_precision(self):
        factory, _ = self._factory(missing={("2026", 1)})
        ev = evaluate(self._rebuild_league(), valuation_factory=factory)
        t = row(ev, 1)["components"]["T"]
        self.assertIn(ev["coverage"]["tradeFutureValue"]["status"], ("partial", "unavailable"))
        self.assertIsNone(t["futureValueScore"])
        # The production half is NOT the trade score (v1.1, OD-MOTY-7).
        self.assertIsNone(t["score"])
        self.assertEqual(t["coverage"], "unavailable")
        self.assertIsNotNone(t["productionScore"])
        self.assertTrue(t["unscoredReason"].startswith("trade_future_value_"))
        self.assertTrue(any(r.startswith("trade_future_value_") for r in ev["coverage"]["reasons"]))
        self.assertIn("trade_component_unscored", ev["coverage"]["reasons"])

    def test_no_valuation_source_is_reported_unavailable(self):
        ev = evaluate(self._rebuild_league())
        self.assertEqual(ev["coverage"]["tradeFutureValue"]["status"], "unavailable")
        self.assertEqual(ev["coverage"]["status"], "partial")


class TradeUnavailableTests(_Case):
    """While T's future-value half cannot be measured, T is UNAVAILABLE --
    never its production half standing in -- and there is no MOTY score:
    only the measured points and a validation rank (methodology §11.5)."""

    def _rebuilder(self, *, trade: bool, final: bool = True):
        # Fixed team scores: A cannot move, so any difference is T's doing.
        lg = League(weeks=4, points={"r1p0": 30.0, "r2p0": 10.0})
        for wk in range(1, 5):
            for rid in range(1, 5):
                lg.team_points[(wk, rid)] = 100.0 + 10 * rid
        if final:
            lg.bracket = [{"r": 1, "t1": 3, "t2": 4, "w": 4, "l": 3, "p": 1}]
        else:
            lg.status = "in_season"
        if trade:
            # Manager 1 sells a producer for a future first: a rebuild.
            lg.trade(
                2,
                1,
                ["r1p0"],
                2,
                ["r2p0"],
                draft_picks=[
                    {
                        "season": "2026",
                        "round": 1,
                        "roster_id": 2,
                        "owner_id": 1,
                        "previous_owner_id": 2,
                    }
                ],
            )
        return lg

    def test_production_only_trade_is_never_the_trade_score(self):
        ev = evaluate(self._rebuilder(trade=True))
        self.assertEqual(ev["coverage"]["tradeFutureValue"]["status"], "unavailable")
        self.assertEqual(ev["scoreBasis"], "incomplete")
        self.assertEqual(ev["promotion"], "not_promoted")
        self.assertFalse(ev["official"])
        for r in ev["rows"]:
            t = r["components"]["T"]
            self.assertIsNone(t["score"])
            self.assertEqual(t["coverage"], "unavailable")
            self.assertIsNone(r["score"])  # no MOTY score without T
            self.assertIsNone(r["contributions"]["T"])
            self.assertIsNotNone(r["rank"])  # a validation rank on measured points
        seller = row(ev, 1)
        self.assertLess(seller["components"]["T"]["productionScore"], 50.0)  # context only
        inc = seller["incomplete"]
        c = seller["components"]
        self.assertAlmostEqual(
            inc["measuredPoints"],
            0.40 * c["A"]["score"]
            + 0.15 * c["W"]["score"]
            + 0.10 * c["D"]["score"]
            + 0.10 * c["P"]["score"],
        )
        self.assertAlmostEqual(inc["measurablePoints"], 75.0)
        self.assertEqual(inc["unscoredComponents"], ["T"])
        self.assertIn("not scored", seller["explanation"])
        # Whoever the unscored T (up to 25 pts) could put first is named.
        rng = ev["unscoredTradeRange"]
        self.assertEqual(rng["tMaxPoints"], 25.0)
        top = ev["rows"][0]["incomplete"]["measuredPoints"]
        expect = [
            r["ownerId"] for r in ev["rows"] if top - r["incomplete"]["measuredPoints"] < 25.0
        ]
        self.assertEqual(rng["couldLeadUnderSomeT"], expect)
        self.assertEqual(rng["leaderDetermined"], len(expect) == 1)

    def test_provisional_incomplete_is_out_of_the_65_measurable_points(self):
        ev = evaluate(self._rebuilder(trade=True, final=False))
        self.assertEqual(ev["status"], "provisional")
        inc = row(ev, 1)["incomplete"]
        self.assertAlmostEqual(inc["measurablePoints"], 65.0)
        self.assertEqual(inc["unscoredComponents"], ["T", "P"])
        self.assertIsNone(row(ev, 1)["earnedOf90"])

    def test_rebuilding_trade_is_not_penalized_by_its_unmeasurable_side(self):
        with_trade = evaluate(self._rebuilder(trade=True))
        without = evaluate(self._rebuilder(trade=False))
        self.assertEqual(without["scoreBasis"], "full")  # no trades -> T measurable
        self.assertIsNone(without["unscoredTradeRange"])
        seller = row(with_trade, 1)
        # Same A, W, D, P: the one-sided production loss moves nothing.
        base = row(without, 1)["contributions"]
        expect = sum(base[k] for k in ("A", "W", "D", "P"))
        self.assertAlmostEqual(seller["incomplete"]["measuredPoints"], expect)

    def test_no_trades_needs_no_valuation_source(self):
        ev = evaluate(League(weeks=4))
        self.assertEqual(ev["coverage"]["tradeFutureValue"]["status"], "complete")
        self.assertEqual(ev["scoreBasis"], "full")
        for rid in range(1, 5):
            self.assertEqual(score(ev, rid, "T"), 50.0)

    def test_incomplete_ties_break_on_measured_management_then_all_play(self):
        rows = [
            {
                "ownerId": oid,
                "score": None,
                "incomplete": {"measuredPoints": 50.0},
                "management": mgmt,
                "components": {"A": {"score": a}},
            }
            for oid, mgmt, a in (("z", 10.0, 40.0), ("a", 12.0, 30.0), ("m", 10.0, 45.0))
        ]
        scored, _ = moty.rank_rows(rows)
        self.assertEqual([r["ownerId"] for r in scored], ["a", "m", "z"])


class OtherAwardsUnchangedTests(_Case):
    """The unified MOTY must not move a single byte of any other award."""

    @staticmethod
    def _strip(section):
        section = copy.deepcopy(section)
        section.pop("motyMethodVersion", None)
        for s in section["bySeason"]:
            s.pop("managerOfTheYear", None)
            s["awards"] = [a for a in s["awards"] if a["key"] != "manager_of_the_year"]
            (s.get("finalists") or {}).pop("manager_of_the_year", None)
        section["awardRaces"] = [
            r for r in section["awardRaces"] if r["key"] != "manager_of_the_year"
        ]
        return section

    def test_every_other_award_is_byte_identical(self):
        snapshot = build_test_snapshot()
        with_unified = awards.build_section(snapshot)

        def _inert(snap, season, levels, valuation_factory=None):
            return None

        with mock.patch.object(moty, "build_season", side_effect=_inert):
            without = awards.build_section(snapshot)
        self.assertEqual(self._strip(with_unified), self._strip(without))
        # League MVP (and its team-success gate) is part of that equality;
        # assert it explicitly so a regression names the award.
        for a, b in zip(with_unified["bySeason"], without["bySeason"]):
            mvp_a = [x for x in a["awards"] if x["key"] == "league_mvp"]
            mvp_b = [x for x in b["awards"] if x["key"] == "league_mvp"]
            self.assertEqual(mvp_a, mvp_b)

    def test_unpromoted_method_never_decides_the_card_or_race(self):
        """Validation track (owner direction 2026-09-29): in EVERY season --
        the live one included -- the card and race keep the existing method
        and the unified result rides beside it, labelled not promoted."""
        snapshot = build_test_snapshot()
        section = awards.build_section(snapshot)
        seen = 0
        for season_row in section["bySeason"]:
            ev = season_row.get("managerOfTheYear")
            if not ev:
                continue
            self.assertFalse(ev["official"])
            self.assertEqual(ev["promotion"], "not_promoted")
            award = next(
                (a for a in season_row["awards"] if a["key"] == "manager_of_the_year"), None
            )
            if award is None:
                continue
            seen += 1
            self.assertIn("compositeScore", award["value"])
            self.assertNotIn("score", award["value"])
            self.assertNotIn("provisional", award)
            if "unifiedCandidate" in award:
                self.assertFalse(award["unifiedCandidate"]["official"])
                self.assertEqual(award["unifiedCandidate"]["promotion"], "not_promoted")
        self.assertGreater(seen, 0)
        for race in section["awardRaces"]:
            if race["key"] != "manager_of_the_year":
                continue
            self.assertNotIn("methodVersion", race)
            for leader in race.get("leaders") or []:
                self.assertIn("compositeScore", leader["value"])

    def test_live_provisional_season_is_not_presented_as_official(self):
        """Even a FULLY scored live season (no trades -> T measurable) keeps
        the existing method's card and race until promotion."""
        lg = League(weeks=4, status="in_season")
        snapshot, season = lg.build()
        ev = moty.build_season(snapshot, season, LEVELS)
        self.assertEqual((ev["status"], ev["scoreBasis"]), ("provisional", "full"))
        self.assertFalse(awards._moty_is_live(ev))
        rows = {
            "moty": awards._manager_of_the_year_scores(snapshot, season, [], []),
            "moty_unified": ev,
        }
        award = awards._manager_of_the_year_award(snapshot, season, rows)
        self.assertIn("compositeScore", award["value"])
        self.assertNotIn("provisional", award)
        self.assertEqual(award["unifiedCandidate"]["promotion"], "not_promoted")
        self.assertFalse(award["unifiedCandidate"]["official"])
        race = awards._manager_of_the_year_race(snapshot, season, rows)
        self.assertNotIn("methodVersion", race)
        # Promotion is the ONE switch: an official evaluation decides the card.
        promoted = dict(ev, official=True, promotion="promoted")
        self.assertTrue(awards._moty_is_live(promoted))

    def test_completed_season_keeps_its_official_legacy_winner(self):
        snapshot = build_test_snapshot()
        section = awards.build_section(snapshot)
        for season_row, season in zip(section["bySeason"], snapshot.seasons):
            ev = season_row.get("managerOfTheYear")
            if not ev or ev["status"] != "final":
                continue
            award = next(a for a in season_row["awards"] if a["key"] == "manager_of_the_year")
            legacy = awards._manager_of_the_year_scores(
                snapshot,
                season,
                awards._trader_of_the_year_scores(snapshot, season)[0],
                awards._waiver_king_scores(snapshot, season),
            )
            self.assertEqual(award["ownerId"], legacy[0]["ownerId"])
            self.assertIn("compositeScore", award["value"])
            self.assertIn("unifiedCandidate", award)
            self.assertFalse(award["unifiedCandidate"]["official"])


if __name__ == "__main__":
    unittest.main()
