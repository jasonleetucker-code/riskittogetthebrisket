"""End-to-end service test on a synthetic contract fixture.

Covers: the full contract→consensus→replacement→engine→market flow,
missing-data statuses, pick distributions, versioned meta, the market
isolation gate at the payload level, and valuation persistence.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.bdvm import service as bdvm_service
from src.bdvm.params import load_param_set
from src.bdvm.projections import ProjectionRecord
from tests.bdvm.pool_depth import depth_records

PARAMS = load_param_set("params_v1")

SCORING = {
    "rec": 1.0,
    "rec_yd": 0.1,
    "rec_td": 6.0,
    "pass_yd": 0.04,
    "pass_td": 4.0,
    "rush_yd": 0.1,
    "rush_td": 6.0,
    "idp_tkl_solo": 1.5,
    "idp_tkl_ast": 0.75,
    "idp_sack": 4.0,
    "bonus_rec_te": 0.5,
}

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
    "DL",
    "LB",
    "LB",
    "LB",
    "DB",
    "DB",
    "DB",
] + ["BN"] * 15


def player_row(name, pos, age=25.0, years=3, ktc=None, idptc=None, **extra):
    row = {
        "playerId": f"sid_{name.replace(' ', '_')}",
        "canonicalName": name,
        "displayName": name.title(),
        "position": pos,
        "assetClass": "idp" if pos in ("DL", "LB", "DB") else "offense",
        "age": age,
        "yearsExp": years,
        "rookie": years == 0,
        "canonicalSiteValues": {},
    }
    if ktc is not None:
        row["canonicalSiteValues"]["ktcSfTep"] = ktc
    if idptc is not None:
        row["canonicalSiteValues"]["idpTradeCalc"] = idptc
    row.update(extra)
    return row


def proj(key, pos, fpg, games=16.5, source="srcA"):
    return ProjectionRecord(
        source=source,
        player_key=key,
        position=pos,
        season=2026,
        as_of="2026-07-20",
        games=games,
        fpg=fpg,
        scoring_native=True,
    )


def build_contract():
    return {
        "generatedAt": "2026-07-27T12:00:00Z",
        "currentDraftYear": 2026,
        "sleeper": {
            "scoringSettings": SCORING,
            "rosterPositions": ROSTER_POSITIONS,
            "leagueSettings": {"num_teams": 12, "taxi_slots": 0, "best_ball": False},
        },
        "playersArray": [
            player_row("alpha qb", "QB", age=26.0, years=4, ktc=8000),
            player_row("beta rb", "RB", age=23.0, years=1, ktc=6000),
            player_row("gamma wr", "WR", age=27.0, years=5, ktc=5000),
            player_row("delta te", "TE", age=24.0, years=2, ktc=3000),
            player_row("epsilon lb", "LB", age=25.0, years=3, idptc=4000),
            player_row("zeta edge", "DL", age=26.0, years=4, idptc=3500),
            player_row("eta cb", "DB", age=24.0, years=2, idptc=2000),
            # no projection for this one:
            player_row("theta wr", "WR", age=29.0, years=7, ktc=2500),
            # projection exists but age missing:
            {**player_row("iota rb", "RB", years=2, ktc=2200), "age": None},
            # unsupported position:
            player_row("kappa k", "K", age=30.0, years=8),
            # quarantined row must be skipped entirely:
            {**player_row("lambda wr", "WR", age=25.0, years=3, ktc=4000), "quarantined": True},
            # picks:
            {
                "canonicalName": "2026 1.03",
                "displayName": "2026 1.03",
                "assetClass": "pick",
                "position": "PICK",
                "canonicalSiteValues": {"ktcSfTep": 5600},
            },
            {
                # The platform's canonical slot-pick displayName form —
                # the one every real /api/data pick row carries.
                "canonicalName": "2026 Pick 1.04",
                "displayName": "2026 Pick 1.04",
                "assetClass": "pick",
                "position": "PICK",
                "canonicalSiteValues": {"ktcSfTep": 5200},
            },
            {
                "canonicalName": "mystery pick",
                "displayName": "Mystery Pick",
                "assetClass": "pick",
                "position": "PICK",
                "canonicalSiteValues": {},
            },
        ],
    }


PROJECTIONS = [
    proj("alpha qb", "QB", 20.0),
    proj("alpha qb", "QB", 22.0, source="srcB"),
    proj("beta rb", "RB", 15.0),
    proj("beta rb", "RB", 14.0, source="srcB"),
    proj("gamma wr", "WR", 14.5),
    proj("delta te", "TE", 11.0),
    proj("epsilon lb", "LB", 16.0),
    proj("zeta edge", "EDGE", 13.0),  # true position from the projection source
    proj("eta cb", "CB", 9.0),
    proj("iota rb", "RB", 9.0),  # priced projection, but row has no age
    # projection for someone not on the contract at all — ignored:
    proj("ghost wr", "WR", 12.0),
]


def run(contract=None, **kwargs):
    # PROJECTIONS alone is nine players in a 12-team league, so no group's
    # replacement RANK lands inside a measured pool; depth_records supplies
    # the bench the replacement solve needs (tests/bdvm/pool_depth.py).
    return bdvm_service.run_valuation(
        contract or build_contract(),
        league_key="dynasty_main",
        params=PARAMS,
        projection_records=list(PROJECTIONS) + depth_records(),
        snapshot_as_of="2026-07-27",
        season=2026,
        **kwargs,
    )


class TestEndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = run()

    def test_status_and_versioned_meta(self):
        meta = self.payload["meta"]
        self.assertEqual(self.payload["status"], "ok")
        self.assertEqual(meta["modelVersion"], "1.0.0")
        self.assertTrue(meta["paramSetId"].startswith("params_v1:"))
        self.assertTrue(meta["configHash"])
        self.assertEqual(meta["configSource"], "sleeper_block")
        self.assertEqual(meta["leagueKey"], "dynasty_main")
        self.assertEqual(meta["surplusMode"], "option")
        self.assertTrue(meta["marketReadAfterFundamental"])
        self.assertEqual(meta["projectionSnapshot"]["asOf"], "2026-07-27")

    def test_counts_and_unpriced_reasons(self):
        counts = self.payload["meta"]["counts"]
        self.assertEqual(counts["priced"], 7)
        reasons = counts["unpricedByReason"]
        self.assertEqual(reasons.get("no_projection"), 1)  # theta wr
        self.assertEqual(reasons.get("missing_age"), 1)  # iota rb
        self.assertEqual(reasons.get("unsupported_position"), 1)  # kappa k
        # quarantined row is silently excluded, not "unpriced"
        names = {p["name"] for p in self.payload["players"]}
        self.assertNotIn("Lambda Wr", names)

    def test_unmeasurable_replacement_level_is_unpriced_not_priced_over_zero(self):
        """H7: the same contract WITHOUT bench depth prices nothing.

        Nine projections cannot answer a 12-team league's replacement
        ranks (36+ deep for WR).  R is the origin of the value scale, so
        an R that silently defaults to 0.0 hands every player his ENTIRE
        FPG as surplus in a payload that is indistinguishable from a real
        one.  Refusing is the §6.3 contract; the replacement block says
        which levels are missing rather than reporting a measured 0.0.
        """
        payload = bdvm_service.run_valuation(
            build_contract(),
            league_key="dynasty_main",
            params=PARAMS,
            projection_records=list(PROJECTIONS),  # deliberately no depth
            snapshot_as_of="2026-07-27",
            season=2026,
        )
        counts = payload["meta"]["counts"]
        self.assertEqual(counts["priced"], 0)
        self.assertEqual(counts["unpricedByReason"].get("no_replacement_level"), 7)
        self.assertEqual(payload["players"], [])
        for group, block in payload["replacement"].items():
            self.assertTrue(block["poolExhausted"], msg=group)
            self.assertIsNone(block["replacementFpg"], msg=group)

    def test_no_silent_zero_values(self):
        """Unpriced players never appear in the priced list with value 0."""
        for p in self.payload["players"]:
            self.assertGreater(p["tradeValue"]["balanced"], 0.0)

    def test_player_entry_shape(self):
        p = next(x for x in self.payload["players"] if x["name"] == "Alpha Qb")
        for key in (
            "fundamental",
            "tradeValue",
            "probs",
            "explain",
            "range",
            "quality",
            "projection",
            "replacement",
            "market",
            "signal",
            "path",
            "dynastyScore0to100",
        ):
            self.assertIn(key, p)
        for strategy in ("contender", "balanced", "rebuilder", "risk_neutral"):
            self.assertIn(strategy, p["tradeValue"])
        self.assertEqual(p["projection"]["sourceCount"], 2)
        self.assertEqual(p["replacement"]["method"], "dynamic_vorp")

    def test_market_gap_math_on_payload(self):
        p = next(x for x in self.payload["players"] if x["name"] == "Alpha Qb")
        m = p["market"]
        self.assertEqual(m["marketSource"], "ktcSfTep")
        self.assertAlmostEqual(m["gap"], p["tradeValue"]["balanced"] - m["marketValue"], places=0)
        idp = next(x for x in self.payload["players"] if x["name"] == "Epsilon Lb")
        self.assertEqual(idp["market"]["marketSource"], "idpTradeCalc")

    def test_true_position_flows_from_projection_source(self):
        edge = next(x for x in self.payload["players"] if x["name"] == "Zeta Edge")
        self.assertEqual(edge["position"], "EDGE")
        self.assertEqual(edge["group"], "DL")
        cb = next(x for x in self.payload["players"] if x["name"] == "Eta Cb")
        self.assertEqual(cb["position"], "CB")
        self.assertEqual(cb["group"], "DB")

    def test_pick_distribution(self):
        picks = {p["name"]: p for p in self.payload["picks"]}
        slot_pick = picks["2026 1.03"]
        self.assertEqual(slot_pick["overallSlot"], 3)
        self.assertEqual(slot_pick["yearsOut"], 0)
        dist = slot_pick["distribution"]["balanced"]
        self.assertLessEqual(abs(dist["ev"] - 3479.0), 1.0)  # Appendix C pick 3
        self.assertAlmostEqual(dist["p_hit"] + dist["p_mid"] + dist["p_miss"], 1.0)
        # The canonical "YYYY Pick R.SS" displayName — the form the live
        # contract and the trade page actually use — must parse too;
        # before the regex allowed the "Pick" token, all 72 real slot
        # picks were unpriced (review finding, 2026-07-28).
        canonical = picks["2026 Pick 1.04"]
        self.assertEqual(canonical["overallSlot"], 4)
        self.assertIsNotNone(canonical["distribution"])
        mystery = picks["Mystery Pick"]
        self.assertIsNone(mystery["distribution"])
        self.assertEqual(mystery["reason"], "unparseable_pick_name")

    def test_replacement_block_present(self):
        repl = self.payload["replacement"]
        for group in ("QB", "RB", "WR", "TE", "DL", "LB", "DB"):
            self.assertIn(group, repl)
            self.assertEqual(repl[group]["method"], "dynamic_vorp")


class TestIsolationAndModes(unittest.TestCase):
    def test_fundamentals_identical_without_market_data(self):
        """Phase-5 gate: strip every market value from the contract and
        the fundamental output must not move by a hair."""
        with_market = run()
        stripped = build_contract()
        for row in stripped["playersArray"]:
            row["canonicalSiteValues"] = {}
        without_market = run(contract=stripped)
        a = {p["name"]: p["fundamental"] for p in with_market["players"]}
        b = {p["name"]: p["fundamental"] for p in without_market["players"]}
        self.assertEqual(a, b)
        # and the market block honestly reports absence
        for p in without_market["players"]:
            self.assertIsNone(p["market"]["marketValue"])
            self.assertIsNone(p["market"]["gap"])
            self.assertEqual(p["signal"]["signal"], "NO_MARKET")

    def test_surplus_mode_ablation_plumbed(self):
        opt = run()
        plain = run(surplus_mode="plain")
        self.assertEqual(plain["meta"]["surplusMode"], "plain")
        # values must differ somewhere — the ablation is real
        a = [round(p["fundamental"]["balanced"], 6) for p in opt["players"]]
        b = [round(p["fundamental"]["balanced"], 6) for p in plain["players"]]
        self.assertNotEqual(a, b)

    def test_no_projection_snapshot_status(self):
        payload = bdvm_service.run_valuation(
            build_contract(),
            league_key="dynasty_main",
            params=PARAMS,
            season=1999,  # no snapshot dir for 1999
        )
        self.assertEqual(payload["status"], "no_projection_snapshot")
        self.assertEqual(payload["players"], [])
        self.assertIn("does not fabricate", payload["message"])


class TestPersistence(unittest.TestCase):
    def test_dated_files_are_immutable_and_latest_updates(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(bdvm_service, "VALUATION_DIR", Path(td)):
                p1 = bdvm_service._persist_valuation(
                    {"status": "ok", "n": 1},
                    league_key="dynasty_main",
                    as_of="2026-07-27T10:00:00+00:00",
                )
                p2 = bdvm_service._persist_valuation(
                    {"status": "ok", "n": 2},
                    league_key="dynasty_main",
                    as_of="2026-07-27T10:00:00+00:00",
                )
                self.assertNotEqual(p1, p2)  # same stamp → new file, no overwrite
                latest = json.loads((Path(td) / "dynasty_main" / "latest.json").read_text())
                self.assertEqual(latest["n"], 2)
                self.assertEqual(json.loads(p1.read_text())["n"], 1)


if __name__ == "__main__":
    unittest.main()
