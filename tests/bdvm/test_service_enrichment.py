"""Service-level context, events, and ROS enrichment."""

from __future__ import annotations

import unittest

from src.bdvm import service as bdvm_service
from src.bdvm.context import PlayerContext
from src.bdvm.events import PlayerEvent
from src.bdvm.params import load_param_set
from src.bdvm.projections import ProjectionRecord
from src.bdvm.ros import RosWeek
from tests.bdvm.pool_depth import depth_records

PARAMS = load_param_set("params_v1")

SCORING = {"rec": 1.0, "rec_yd": 0.1, "rec_td": 6.0}
ROSTER_POSITIONS = [
    "QB",
    "RB",
    "RB",
    "WR",
    "WR",
    "WR",
    "TE",
    "FLEX",
    "SUPER_FLEX",
    "DL",
    "LB",
    "LB",
    "DB",
] + ["BN"] * 10


def contract(rows):
    return {
        "generatedAt": "2026-07-27T12:00:00Z",
        "currentDraftYear": 2026,
        "sleeper": {
            "scoringSettings": SCORING,
            "rosterPositions": ROSTER_POSITIONS,
            "leagueSettings": {"num_teams": 12, "taxi_slots": 0, "best_ball": False},
        },
        "playersArray": rows,
    }


def row(name, pos, age=None, years=3, team="KC", ktc=5000):
    return {
        "playerId": f"sid_{name}",
        "canonicalName": name,
        "displayName": name.title(),
        "position": pos,
        "assetClass": "idp" if pos in ("DL", "LB", "DB") else "offense",
        "age": age,
        "yearsExp": years,
        "rookie": years == 0,
        "team": team,
        "canonicalSiteValues": {"ktcSfTep": ktc}
        if pos not in ("DL", "LB", "DB")
        else {"idpTradeCalc": ktc},
    }


def proj(key, pos, fpg):
    return ProjectionRecord(
        source="s",
        player_key=key,
        position=pos,
        season=2026,
        as_of="2026-07-20",
        games=16.0,
        fpg=fpg,
        scoring_native=True,
    )


def run(rows, **kwargs):
    # Every fixture below projects one player; without bench depth no
    # group has a measurable replacement level and the engine (rightly)
    # returns everything unpriced.  See tests/bdvm/pool_depth.py.
    records = list(kwargs.pop("projection_records", None) or []) + depth_records()
    return bdvm_service.run_valuation(
        contract(rows),
        league_key="dynasty_main",
        params=PARAMS,
        snapshot_as_of="2026-07-27",
        season=2026,
        projection_records=records,
        **kwargs,
    )


class TestContextEnrichment(unittest.TestCase):
    def test_age_falls_back_to_nflverse_birth_date(self):
        rows = [row("ctx guy", "WR", age=None)]
        ctx = {
            "ctx guy": PlayerContext(
                player_key="ctx guy", birth_date="2000-03-15", rookie_season=2022
            )
        }
        payload = run(rows, projection_records=[proj("ctx guy", "WR", 12.0)], context=ctx)
        self.assertEqual(payload["meta"]["counts"]["priced"], 1)
        p = payload["players"][0]
        self.assertEqual(p["context"]["ageSource"], "nflverse_birth_date")
        self.assertAlmostEqual(p["raw"]["age"], 26.5, delta=0.2)
        # nfl_season from rookie_season: 2026-2022+1 = 5
        payload2 = run(rows, projection_records=[proj("ctx guy", "WR", 12.0)])
        self.assertEqual(payload2["meta"]["counts"]["unpricedByReason"].get("missing_age"), 1)

    def test_draft_capital_and_career_load_flow_in(self):
        rows = [row("young stud", "WR", age=23.0, years=1)]
        ctx = {
            "young stud": PlayerContext(
                player_key="young stud",
                draft_overall=5,
                draft_capital_score=1.0,
                rookie_season=2025,
                loads={"targets": 900.0},
            )
        }
        with_ctx = run(rows, projection_records=[proj("young stud", "WR", 12.0)], context=ctx)
        without_ctx = run(rows, projection_records=[proj("young stud", "WR", 12.0)])
        p_ctx = with_ctx["players"][0]
        p_no = without_ctx["players"][0]
        self.assertEqual(p_ctx["context"]["draftOverall"], 5)
        self.assertEqual(p_ctx["context"]["careerLoad"], 900.0)
        # draft capital raises ascension (kappa) → higher future value
        self.assertGreater(p_ctx["fundamental"]["rebuilder"], p_no["fundamental"]["rebuilder"])

    def test_ambiguous_idp_listing_bumps_designation_risk(self):
        rows = [row("tweener", "LB", age=25.0)]
        ctx = {
            "tweener": PlayerContext(
                player_key="tweener",
                true_position="LB",
                position_ambiguous=True,
                rookie_season=2022,
            )
        }
        with_ctx = run(rows, projection_records=[proj("tweener", "LB", 12.0)], context=ctx)
        without_ctx = run(rows, projection_records=[proj("tweener", "LB", 12.0)])
        # designation risk raises hazard → lower long-horizon value
        self.assertLess(
            with_ctx["players"][0]["fundamental"]["rebuilder"],
            without_ctx["players"][0]["fundamental"]["rebuilder"],
        )


class TestEventEnrichment(unittest.TestCase):
    def test_event_moves_value_and_audits(self):
        rows = [row("event guy", "WR", age=25.0)]
        evt = PlayerEvent(
            event_id="e1",
            player_key="event guy",
            event_type="DEPTH_CHART_DEMOTION",
            effective_date="2026-07-25",
            confidence=0.9,
        )
        with_ev = run(rows, projection_records=[proj("event guy", "WR", 12.0)], events=[evt])
        without_ev = run(rows, projection_records=[proj("event guy", "WR", 12.0)], events=[])
        self.assertEqual(with_ev["meta"]["counts"]["eventsApplied"], 1)
        # Compare the PRE-SCALE value, like the context tests above: this
        # fixture has one contract player, so he is the calibration anchor
        # and his trade value is pinned at target_top_value either way.
        self.assertLess(
            with_ev["players"][0]["fundamental"]["balanced"],
            without_ev["players"][0]["fundamental"]["balanced"],
        )
        audit = with_ev["players"][0]["events"]
        self.assertEqual(audit[0]["type"], "DEPTH_CHART_DEMOTION")
        self.assertTrue(audit[0]["applied"])

    def test_reflected_event_is_inert(self):
        rows = [row("noop guy", "WR", age=25.0)]
        evt = PlayerEvent(
            event_id="e2",
            player_key="noop guy",
            event_type="DEPTH_CHART_DEMOTION",
            effective_date="2026-07-25",
            confidence=0.9,
            already_in_projection=True,
        )
        with_ev = run(rows, projection_records=[proj("noop guy", "WR", 12.0)], events=[evt])
        without_ev = run(rows, projection_records=[proj("noop guy", "WR", 12.0)], events=[])
        self.assertEqual(with_ev["meta"]["counts"]["eventsApplied"], 0)
        self.assertEqual(
            with_ev["players"][0]["tradeValue"]["balanced"],
            without_ev["players"][0]["tradeValue"]["balanced"],
        )


class TestRosEnrichment(unittest.TestCase):
    def _weeks(self, bye=9):
        return [
            RosWeek(week=w, is_bye=(w == bye), p_active=1.0, is_league_playoff=w in (15, 16, 17))
            for w in range(1, 19)
        ]

    def test_ros_present_with_schedule(self):
        rows = [row("ros guy", "WR", age=25.0, team="KC")]
        payload = run(
            rows,
            projection_records=[proj("ros guy", "WR", 12.0)],
            schedule_weeks={"KC": self._weeks()},
        )
        ros = payload["players"][0]["ros"]
        self.assertIsNotNone(ros)
        self.assertEqual(ros["weeks"], 18)
        self.assertGreater(ros["contender"], ros["rebuilder"])  # playoff weighting
        self.assertGreater(ros["balanced"], 0)

    def test_ros_absent_without_schedule_and_flagged_for_fa(self):
        rows = [row("fa guy", "WR", age=25.0, team="FA")]
        payload = run(
            rows,
            projection_records=[proj("fa guy", "WR", 12.0)],
            schedule_weeks={"KC": self._weeks()},
        )
        ros = payload["players"][0]["ros"]
        self.assertIsNone(ros["value"])
        self.assertIn("no_schedule_for_team", ros["reason"])
        payload2 = run(rows, projection_records=[proj("fa guy", "WR", 12.0)])
        self.assertIsNone(payload2["players"][0]["ros"])


if __name__ == "__main__":
    unittest.main()
