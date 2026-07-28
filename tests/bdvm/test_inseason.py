"""In-season updating: realized weekly production → posterior µ/σ + ROS.

The contract under test:
1. Preseason no-op — ``actuals=(None, {})`` (or omitted) produces the
   EXACT preseason payload; before week 1 nothing may drift.
2. Posterior math — µ shrinks toward realized per-game production with
   weight n_prior/(n_prior + weeks_played) (blend_ros_mu, the §8.4
   posterior finally wired live); σ shrinks by √(that weight).
3. Players with no observed weeks keep the preseason consensus —
   absence of evidence is never evidence of zero.
4. ROS sums only REMAINING weeks once a current week exists.
5. The actuals feed itself scores rows under league rules via the one
   production scoring path, and returns (None, {}) with no rows.
"""

from __future__ import annotations

import unittest

from src.bdvm.actuals import weekly_points_from_rows
from src.bdvm.params import load_param_set
from src.bdvm.ros import ros_projection_weight
from src.bdvm.service import run_valuation

PARAMS = load_param_set("params_v1")

SCORING = {"rec": 1.0, "rec_yd": 0.1, "idp_tkl_solo": 1.5}
_norm = lambda s: s.lower()  # noqa: E731


def _contract():
    return {
        "generatedAt": "x",
        "currentDraftYear": 2026,
        "sleeper": {
            "scoringSettings": SCORING,
            "rosterPositions": ["QB", "WR", "WR", "LB", "BN", "BN"],
            "leagueSettings": {"num_teams": 12},
        },
        "playersArray": [
            {
                "playerId": "w1",
                "canonicalName": "steady wr",
                "displayName": "Steady WR",
                "position": "WR",
                "assetClass": "offense",
                "age": 25.0,
                "yearsExp": 3,
            },
            {
                "playerId": "w2",
                "canonicalName": "quiet wr",
                "displayName": "Quiet WR",
                "position": "WR",
                "assetClass": "offense",
                "age": 25.0,
                "yearsExp": 3,
            },
        ],
    }


def _records():
    from src.bdvm.projections import ProjectionRecord

    return [
        ProjectionRecord(
            source="a",
            player_key=key,
            position="WR",
            season=2026,
            as_of="2026-07-20",
            games=17.0,
            fpg=12.0,
            scoring_native=True,
        )
        for key in ("steady wr", "quiet wr")
    ]


def _run(actuals=None, schedule_weeks=None):
    return run_valuation(
        _contract(),
        league_key="dynasty_main",
        params=PARAMS,
        projection_records=_records(),
        snapshot_as_of="2026-07-27",
        season=2026,
        actuals=actuals,
        schedule_weeks=schedule_weeks,
    )


class TestPreseasonNoOp(unittest.TestCase):
    def test_omitted_and_empty_actuals_are_identical(self):
        base = _run(actuals=None)
        empty = _run(actuals=(None, {}))
        self.assertEqual(base["meta"]["inSeason"], {"active": False})
        self.assertEqual(empty["meta"]["inSeason"], {"active": False})
        for p_base, p_empty in zip(base["players"], empty["players"]):
            self.assertEqual(p_base["projection"]["fpg"], p_empty["projection"]["fpg"])
            self.assertEqual(p_base["tradeValue"], p_empty["tradeValue"])


class TestPosterior(unittest.TestCase):
    def test_mu_shrinks_toward_actuals_with_prior_weight(self):
        # 4 weeks at 20.0 FPG against a 12.0 preseason µ (offense
        # n_prior = 6): posterior = w·12 + (1−w)·20, w = 6/(6+4).
        samples = [(1, 20.0), (2, 20.0), (3, 20.0), (4, 20.0)]
        payload = _run(actuals=(5, {"steady wr": samples}))
        w = ros_projection_weight(4.0, is_idp=False, params=PARAMS)
        expected_mu = w * 12.0 + (1 - w) * 20.0
        steady = next(p for p in payload["players"] if p["name"] == "Steady WR")
        self.assertAlmostEqual(steady["projection"]["fpg"], round(expected_mu, 3), places=3)
        self.assertEqual(payload["meta"]["inSeason"]["currentWeek"], 5)
        self.assertEqual(payload["meta"]["inSeason"]["playersUpdated"], 1)

    def test_unobserved_player_keeps_preseason_mu(self):
        payload = _run(actuals=(5, {"steady wr": [(1, 20.0)]}))
        quiet = next(p for p in payload["players"] if p["name"] == "Quiet WR")
        self.assertAlmostEqual(quiet["projection"]["fpg"], 12.0, places=3)

    def test_sigma_shrinks_with_evidence(self):
        base = _run()
        updated = _run(actuals=(9, {"steady wr": [(w, 12.0) for w in range(1, 9)]}))
        s_base = next(p for p in base["players"] if p["name"] == "Steady WR")
        s_upd = next(p for p in updated["players"] if p["name"] == "Steady WR")
        # identical production → µ unchanged, σ_source strictly smaller
        self.assertAlmostEqual(s_upd["projection"]["fpg"], s_base["projection"]["fpg"], places=3)
        self.assertLess(
            s_upd["projection"]["sigmaSource"], s_base["projection"]["sigmaSource"] + 1e-9
        )


class TestRosRemainingWeeks(unittest.TestCase):
    def _weeks(self):
        from src.bdvm.ros import RosWeek

        return {"KC": [RosWeek(week=w, is_bye=(w == 6), p_active=1.0) for w in range(1, 19)]}

    def _contract_with_team(self):
        c = _contract()
        for row in c["playersArray"]:
            row["team"] = "KC"
        return c

    def test_ros_counts_only_remaining_weeks(self):
        pre = run_valuation(
            self._contract_with_team(),
            league_key="dynasty_main",
            params=PARAMS,
            projection_records=_records(),
            snapshot_as_of="2026-07-27",
            season=2026,
            schedule_weeks=self._weeks(),
        )
        mid = run_valuation(
            self._contract_with_team(),
            league_key="dynasty_main",
            params=PARAMS,
            projection_records=_records(),
            snapshot_as_of="2026-07-27",
            season=2026,
            schedule_weeks=self._weeks(),
            actuals=(10, {"steady wr": [(w, 12.0) for w in range(1, 10)]}),
        )
        pre_ros = next(p for p in pre["players"] if p["name"] == "Steady WR")["ros"]
        mid_ros = next(p for p in mid["players"] if p["name"] == "Steady WR")["ros"]
        self.assertEqual(pre_ros["weeks"], 18)
        self.assertEqual(mid_ros["weeks"], 9)  # weeks 10..18
        self.assertLess(mid_ros["balanced"], pre_ros["balanced"])


class TestActualsFeed(unittest.TestCase):
    def test_rows_score_under_league_rules_week_granular(self):
        rows = [
            {
                "player_display_name": "Steady WR",
                "position": "WR",
                "season": 2026,
                "week": 1,
                "season_type": "REG",
                "receptions": 5,
                "receiving_yards": 70,
            },
            {  # playoffs excluded
                "player_display_name": "Steady WR",
                "position": "WR",
                "season": 2026,
                "week": 19,
                "season_type": "POST",
                "receptions": 9,
                "receiving_yards": 150,
            },
            {  # other season excluded
                "player_display_name": "Steady WR",
                "position": "WR",
                "season": 2025,
                "week": 2,
                "season_type": "REG",
                "receptions": 9,
                "receiving_yards": 150,
            },
        ]
        week, by_key = weekly_points_from_rows(rows, SCORING, season=2026, name_normalizer=_norm)
        self.assertEqual(week, 2)
        self.assertEqual(by_key["steady wr"], [(1, 12.0)])  # 5 rec + 7.0 yds

    def test_no_rows_is_preseason(self):
        week, by_key = weekly_points_from_rows([], SCORING, season=2026, name_normalizer=_norm)
        self.assertIsNone(week)
        self.assertEqual(by_key, {})


if __name__ == "__main__":
    unittest.main()
