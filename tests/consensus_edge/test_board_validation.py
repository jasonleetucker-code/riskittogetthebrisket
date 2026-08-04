"""The shipping-readiness study, and the three ways it could lie.

`scripts/validate_consensus_edge_board.py` replays the full labelled
board over the committed panel and asks "if you had followed the top-20
buy list, would you have done better?". Everything here guards a way
that question could be answered wrongly while looking answered.

Three traps, each of which produces a plausible number rather than an
error:

1. **`csv_root`.** `build_board` did not thread it, so a replay enriched
   `canonicalSiteValues` from TODAY's CSVs. Measured on one panel day,
   **666 of 667 rows changed score**. The board still looked entirely
   valid.
2. **An active scoring fit.** `scoring_fit.measure` reaches nflverse on a
   cache miss, and an active fit is the exact configuration divergence
   `validation_scope` exists to flag — the published rho describes a
   board measured with the fit inert.
3. **The mean.** These are percentage returns on assets priced 152 to
   9999. On one real fold four players priced 152-306 returned +327%,
   +268%, +210% and +195%, pulling the top-20 mean to +59.44% while the
   median sat at +1.04%. Reporting the mean would have manufactured an
   edge out of four floor-priced rookies.
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

from src.consensus_edge import scoring_fit, validation_scope

REPO = Path(__file__).resolve().parents[2]


def _load_study():
    spec = importlib.util.spec_from_file_location(
        "_ce_validate", REPO / "scripts" / "validate_consensus_edge_board.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


STUDY = _load_study()


class TestTheInertFitBoardIsActuallyInert(unittest.TestCase):
    """A replay must not measure a fit — for correctness, not speed."""

    def setUp(self):
        self.board = scoring_fit.inert_board("test")

    def test_every_player_gets_exactly_one(self):
        for position in ("WR", "LB", "QB", None, "NOT_A_POSITION"):
            fit = self.board.for_player("Anyone", position)
            self.assertEqual(fit.multiplier, 1.0)
            self.assertTrue(fit.is_inert)

    def test_it_reports_itself_inactive(self):
        self.assertFalse(self.board.active)

    def test_it_matches_the_measured_configuration(self):
        # This is the point: a replay using it stays inside the
        # configuration the committed rho describes.
        scope = validation_scope.scope_for_board(self.board.to_meta())
        self.assertTrue(scope["matchesMeasured"])
        self.assertEqual(scope["differences"], [])

    def test_it_names_both_axes_as_absent(self):
        meta = self.board.to_meta()
        self.assertEqual(sorted(meta["absentAxes"]), ["idpPositionFit", "receptionDepthFit"])
        self.assertTrue(meta["reasons"]["summary"])

    def test_the_study_uses_it(self):
        source = (REPO / "scripts" / "validate_consensus_edge_board.py").read_text()
        self.assertIn("scoring_fit.inert_board(", source)
        self.assertIn("scoring_fit_board=self._inert", source)


class TestBuildBoardThreadsCsvRoot(unittest.TestCase):
    """The leak guard must be reachable from the function the study calls."""

    def test_build_board_accepts_csv_root(self):
        import inspect

        from src.consensus_edge import service

        params = inspect.signature(service.build_board).parameters
        self.assertIn("csv_root", params)
        self.assertIn("scoring_fit_board", params)

    def test_it_forwards_csv_root_rather_than_swallowing_it(self):
        import inspect

        from src.consensus_edge import service

        source = inspect.getsource(service.build_board)
        self.assertIn("csv_root=csv_root", source)

    def test_the_study_always_supplies_it(self):
        source = (REPO / "scripts" / "validate_consensus_edge_board.py").read_text()
        self.assertIn("csv_root=pd.csv_root", source)
        # Both the contract build and the board build need it; neither
        # alone is sufficient.
        self.assertEqual(source.count("csv_root=pd.csv_root"), 2)


class TestTheMedianIsTheHeadline(unittest.TestCase):
    """The statistic that decides must not be the outlier-driven one."""

    def _rows(self, n):
        return [{"playerKey": f"p{i}"} for i in range(n)]

    def test_one_huge_row_moves_the_mean_and_not_the_median(self):
        rows = self._rows(20)
        outcomes = {f"p{i}": 0.01 for i in range(20)}
        outcomes["p0"] = 3.275  # the real +327.5% row
        stats = STUDY._bucket_stats(rows, outcomes)
        self.assertGreater(stats["meanExcess"], 0.15)
        self.assertAlmostEqual(stats["medianExcess"], 0.01, places=9)

    def test_top_contributor_share_exposes_the_dependence(self):
        rows = self._rows(20)
        outcomes = {f"p{i}": 0.01 for i in range(20)}
        outcomes["p0"] = 3.275
        stats = STUDY._bucket_stats(rows, outcomes)
        self.assertGreater(
            stats["topContributorShare"],
            0.9,
            "a single row carrying >90% of the signal must be visible in the payload",
        )

    def test_a_balanced_bucket_has_a_low_contributor_share(self):
        rows = self._rows(20)
        outcomes = {f"p{i}": 0.01 for i in range(20)}
        stats = STUDY._bucket_stats(rows, outcomes)
        self.assertLess(stats["topContributorShare"], 0.1)

    def test_empty_bucket_reports_none_not_zero(self):
        stats = STUDY._bucket_stats(self._rows(3), {})
        self.assertEqual(stats["n"], 0)
        self.assertIsNone(stats["medianExcess"])
        self.assertIsNone(stats["meanExcess"])

    def test_pooling_carries_the_median_across_folds(self):
        folds = [
            {"topBuys": {"n": 20, "medianExcess": 0.02, "meanExcess": 0.6}},
            {"topBuys": {"n": 20, "medianExcess": 0.01, "meanExcess": 0.01}},
            {"topBuys": {"n": 20, "medianExcess": -0.01, "meanExcess": -0.01}},
        ]
        pooled = STUDY._pool(folds, ["topBuys"])
        self.assertEqual(pooled["folds"], 3)
        self.assertEqual(pooled["foldsPositive"], 2)
        # The pooled headline is the mean OF per-fold medians, so the
        # 0.6 mean in fold 1 cannot leak into it.
        self.assertAlmostEqual(pooled["medianExcess"], (0.02 + 0.01 - 0.01) / 3, places=9)


class TestLabelGroupsSplitTheDemoted(unittest.TestCase):
    """Every would-be Strong Buy lands in Buy; pooling them is a blend."""

    def test_a_demoted_buy_is_its_own_group(self):
        rows = [
            {"label": "Buy", "labelReason": None},
            {"label": "Buy", "labelReason": "score reaches Strong Buy but confidence 69 < 70"},
            {"label": "Neutral", "labelReason": None},
        ]
        groups = STUDY._label_groups(rows)
        self.assertEqual(len(groups["Buy"]), 1)
        self.assertEqual(len(groups["Buy (demoted from Strong)"]), 1)
        self.assertEqual(len(groups["Neutral"]), 1)

    def test_sells_split_the_same_way(self):
        rows = [
            {"label": "Sell", "labelReason": None},
            {"label": "Sell", "labelReason": "score reaches Strong Sell but confidence 69 < 70"},
        ]
        groups = STUDY._label_groups(rows)
        self.assertIn("Sell (demoted from Strong)", groups)


class TestEqualCountDeciles(unittest.TestCase):
    """Equal-count, not equal-width — the scores cluster near zero."""

    def test_buckets_are_equal_sized(self):
        rows = [{"playerKey": f"p{i}", "score": float(i)} for i in range(100)]
        outcomes = {f"p{i}": 0.0 for i in range(100)}
        deciles = STUDY._equal_count_deciles(rows, outcomes, bins=10)
        self.assertEqual(len(deciles), 10)
        self.assertEqual({d["n"] for d in deciles}, {10})

    def test_deciles_are_ordered_by_score(self):
        rows = [{"playerKey": f"p{i}", "score": float(i)} for i in range(100)]
        outcomes = {f"p{i}": 0.0 for i in range(100)}
        deciles = STUDY._equal_count_deciles(rows, outcomes, bins=10)
        means = [d["meanScore"] for d in deciles]
        self.assertEqual(means, sorted(means))

    def test_it_refuses_rather_than_making_n_equals_two_buckets(self):
        rows = [{"playerKey": f"p{i}", "score": float(i)} for i in range(12)]
        outcomes = {f"p{i}": 0.0 for i in range(12)}
        self.assertEqual(STUDY._equal_count_deciles(rows, outcomes, bins=10), [])


class TestTheDecisionBar(unittest.TestCase):
    """The bar was set before the numbers, and must stay set."""

    def _summary(self, *, median, beat, folds, classes):
        return {
            "pooled": {
                "topBuys": {"medianExcess": median, "meanExcess": median, "folds": folds},
                "byAssetClass": classes,
            },
            "topBuysBeatRandomInFolds": beat,
        }

    def test_a_positive_edge_beating_random_in_a_majority_ships(self):
        summary = self._summary(
            median=0.015,
            beat=6,
            folds=7,
            classes={
                "offense": {"folds": 7, "medianExcess": 0.01},
                "idp": {"folds": 7, "medianExcess": 0.02},
            },
        )
        self.assertIn("ship it", STUDY._decide(summary)["recommendation"])

    def test_zero_positive_asset_classes_does_NOT_ship(self):
        """The bug this test exists for.

        The veto was `len(positive) >= 2 or len(measured) <= 1`. With one
        measurable class the second clause was vacuously true, so a board
        on which NO asset class showed a positive edge shipped anyway —
        observed on a real 3-fold smoke run.
        """
        summary = self._summary(
            median=0.20,  # inflated by outliers
            beat=3,
            folds=3,
            classes={"idp": {"folds": 3, "medianExcess": -0.01}},
        )
        self.assertIn("do not ship", STUDY._decide(summary)["recommendation"])

    def test_a_negative_median_does_not_ship_however_good_the_mean(self):
        summary = self._summary(
            median=-0.01,
            beat=7,
            folds=7,
            classes={
                "offense": {"folds": 7, "medianExcess": 0.01},
                "idp": {"folds": 7, "medianExcess": 0.02},
            },
        )
        self.assertIn("do not ship", STUDY._decide(summary)["recommendation"])

    def test_beating_random_in_a_minority_does_not_ship(self):
        summary = self._summary(
            median=0.02,
            beat=3,
            folds=7,
            classes={
                "offense": {"folds": 7, "medianExcess": 0.01},
                "idp": {"folds": 7, "medianExcess": 0.02},
            },
        )
        self.assertIn("do not ship", STUDY._decide(summary)["recommendation"])

    def test_too_few_folds_is_inconclusive_not_a_pass(self):
        summary = self._summary(median=0.9, beat=2, folds=2, classes={})
        self.assertIn("inconclusive", STUDY._decide(summary)["recommendation"])


class TestTheLeakGuardDoesRealWork(unittest.TestCase):
    """`csv_root` must CHANGE the board, or it is guarding nothing.

    This is the strongest form of the test: not "the parameter exists"
    but "omitting it produces materially different numbers on a real
    historical date". Measured when the guard was added: 666 of 667
    common rows differed. If this ever stops failing without the
    redirect, the pipeline has stopped reading CSVs and every backtest
    in this feature needs re-examining.
    """

    @classmethod
    def setUpClass(cls):
        from src.consensus_edge import panel

        if panel.is_shallow():
            raise unittest.SkipTest("shallow clone: no panel to replay")
        try:
            dates = panel.available_dates()
        except Exception as exc:  # noqa: BLE001
            raise unittest.SkipTest(f"no panel available: {exc}") from exc
        if len(dates) < 50:
            raise unittest.SkipTest("panel too short to be meaningful")
        cls.when = dates[len(dates) // 2]

    def test_omitting_csv_root_changes_the_board(self):
        from src.api.data_contract import build_api_data_contract
        from src.consensus_edge import panel, service

        inert = scoring_fit.inert_board("test")
        with panel.panel_day(self.when) as day:
            contract = build_api_data_contract(day.payload, csv_root=day.csv_root)
            honest = service.build_board(
                contract, hours_stale=8.0, csv_root=day.csv_root, scoring_fit_board=inert
            )
            leaked = service.build_board(contract, hours_stale=8.0, scoring_fit_board=inert)

        a = {r["playerKey"]: r["score"] for r in honest["players"] if r["score"] is not None}
        b = {r["playerKey"]: r["score"] for r in leaked["players"] if r["score"] is not None}
        common = set(a) & set(b)
        self.assertGreater(len(common), 100, "too few common rows to conclude anything")
        differing = sum(1 for k in common if abs(a[k] - b[k]) > 1e-9)
        self.assertGreater(
            differing / len(common),
            0.5,
            "csv_root no longer changes the replayed board — the leak guard is "
            "guarding nothing, and every historical measurement needs re-checking",
        )

    def test_the_honest_board_matches_the_measured_configuration(self):
        from src.api.data_contract import build_api_data_contract
        from src.consensus_edge import panel, service

        with panel.panel_day(self.when) as day:
            contract = build_api_data_contract(day.payload, csv_root=day.csv_root)
            board = service.build_board(
                contract,
                hours_stale=8.0,
                csv_root=day.csv_root,
                scoring_fit_board=scoring_fit.inert_board("test"),
            )
        self.assertTrue(board["validationScope"]["matchesMeasured"])
        self.assertFalse(board["scoringFit"]["active"])

    def test_only_the_reachable_labels_appear(self):
        from src.api.data_contract import build_api_data_contract
        from src.consensus_edge import panel, service

        with panel.panel_day(self.when) as day:
            contract = build_api_data_contract(day.payload, csv_root=day.csv_root)
            board = service.build_board(
                contract,
                hours_stale=8.0,
                csv_root=day.csv_root,
                scoring_fit_board=scoring_fit.inert_board("test"),
            )
        labels = {r["label"] for r in board["players"]}
        for unreachable in ("Strong Buy", "Strong Sell", "Conflicted", "Withheld"):
            self.assertNotIn(
                unreachable,
                labels,
                f"{unreachable} appeared on a one-component board; the study's "
                "unreachableLabels block is now wrong",
            )


class TestCommittedMeasurementsAreHonest(unittest.TestCase):
    """The written artifact must carry its own limits."""

    def _measurements(self):
        return sorted(
            (REPO / "docs" / "measurements").glob("consensus-edge-board-validation-*.json")
        )

    def test_at_least_one_measurement_is_committed(self):
        self.assertTrue(self._measurements(), "the study has never been run and committed")

    def test_each_stamps_the_configuration_it_measured(self):
        import json

        for path in self._measurements():
            payload = json.loads(path.read_text())
            self.assertFalse(
                payload["configuration"]["scoringFitApplied"],
                f"{path.name} claims a scoring fit was applied; the replay holds it inert",
            )
            self.assertEqual(payload["hoursStalePinned"], 8.0)

    def test_each_names_the_labels_it_could_not_measure(self):
        import json

        for path in self._measurements():
            payload = json.loads(path.read_text())
            unreachable = payload["unreachableLabels"]
            for label in ("Strong Buy", "Strong Sell", "Conflicted", "Withheld"):
                self.assertIn(label, unreachable)

    def test_each_states_the_panel_is_offseason(self):
        import json

        for path in self._measurements():
            payload = json.loads(path.read_text())
            self.assertTrue(
                any("OFFSEASON" in c or "offseason" in c for c in payload["caveats"]),
                f"{path.name} does not state that its panel is entirely offseason",
            )


if __name__ == "__main__":
    unittest.main()
