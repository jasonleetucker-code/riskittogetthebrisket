"""Persistence must actually persist, idempotently, without destroying history.

The audit found the previous implementation had no persistence at all —
no table, no writer, no INSERT — while the task list recorded the
snapshot store as complete. These tests exist so that claim is checkable
rather than asserted.
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from src.consensus_edge import snapshot


def _board(model="ce.test.v1", params="abc123", n=3, score=50.0):
    return {
        "status": "ok",
        "modelVersion": model,
        "paramSetId": params,
        "contractScrapedAt": "2026-08-04T00:00:00",
        "inputs": {"hoursStale": 6.0},
        "players": [
            {
                "playerKey": f"Player {i}",
                "displayName": f"Player {i}",
                "position": "WR" if i % 2 else "LB",
                "assetClass": "offense" if i % 2 else "idp",
                "score": score + i,
                "label": "Buy",
                "labelReason": None,
                "qualified": True,
                "confidence": 60.0,
                "components": {"mispricing": 0.5, "sharpFlow": None, "opportunity": None},
                "componentsAbsent": ["opportunity", "sharpFlow"],
                "confidenceFactors": {"coverage": 0.33, "reliability": 1.0, "freshness": 0.9},
                "mispricing": {"pctGap": 0.2},
                "fairValue": 1200.0,
                "marketValue": 1000.0,
                "anchorKey": "ktcSfTep",
                "unpricedReason": None,
                "conflict": {"conflicted": False},
            }
            for i in range(n)
        ],
    }


class _TempDB(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "ce.sqlite"

    def tearDown(self):
        self._tmp.cleanup()


class TestWriting(_TempDB):
    def test_a_board_is_written(self):
        result = snapshot.write_board(_board(n=5), as_of="2026-08-04", path=self.db)
        self.assertEqual(result["written"], 5)
        self.assertTrue(self.db.exists())

    def test_coverage_reports_what_was_stored(self):
        snapshot.write_board(_board(n=4), as_of="2026-08-04", path=self.db)
        cov = snapshot.coverage(self.db)
        self.assertTrue(cov["exists"])
        self.assertEqual(cov["rows"], 4)
        self.assertEqual(cov["distinctDates"], 1)
        self.assertEqual(cov["firstDate"], "2026-08-04")

    def test_coverage_on_a_missing_store_says_so(self):
        cov = snapshot.coverage(Path(self._tmp.name) / "nope.sqlite")
        self.assertFalse(cov["exists"])
        self.assertEqual(cov["snapshots"], 0)

    def test_a_board_that_did_not_build_is_not_written(self):
        result = snapshot.write_board({"status": "no_contract"}, path=self.db)
        self.assertTrue(result["skipped"])
        self.assertEqual(result["written"], 0)


class TestIdempotency(_TempDB):
    def test_rerunning_the_same_day_does_not_duplicate(self):
        snapshot.write_board(_board(n=3), as_of="2026-08-04", path=self.db)
        snapshot.write_board(_board(n=3), as_of="2026-08-04", path=self.db)
        self.assertEqual(snapshot.coverage(self.db)["rows"], 3)

    def test_rerunning_updates_the_values(self):
        snapshot.write_board(_board(n=1, score=10.0), as_of="2026-08-04", path=self.db)
        snapshot.write_board(_board(n=1, score=90.0), as_of="2026-08-04", path=self.db)
        rows = snapshot.history_for_player("Player 0", path=self.db)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["score"], 90.0)

    def test_separate_dates_accumulate(self):
        snapshot.write_board(_board(n=2), as_of="2026-08-03", path=self.db)
        snapshot.write_board(_board(n=2), as_of="2026-08-04", path=self.db)
        self.assertEqual(snapshot.coverage(self.db)["distinctDates"], 2)


class TestHistoryIsNotRewritten(_TempDB):
    """A different model's rows are that model's record, not ours.

    Overwriting them would destroy the only evidence of what the older
    model said — which is exactly what a promotion decision needs to
    compare against.
    """

    def test_a_new_model_version_does_not_overwrite_the_old_one(self):
        snapshot.write_board(_board(model="ce.v1", score=10.0), as_of="2026-08-04", path=self.db)
        snapshot.write_board(_board(model="ce.v2", score=90.0), as_of="2026-08-04", path=self.db)
        rows = snapshot.history_for_player("Player 0", path=self.db)
        versions = {r["model_version"] for r in rows}
        self.assertEqual(versions, {"ce.v1", "ce.v2"})

    def test_a_new_param_set_does_not_overwrite_the_old_one(self):
        snapshot.write_board(_board(params="p1"), as_of="2026-08-04", path=self.db)
        snapshot.write_board(_board(params="p2"), as_of="2026-08-04", path=self.db)
        rows = snapshot.history_for_player("Player 0", path=self.db)
        self.assertEqual({r["param_set_id"] for r in rows}, {"p1", "p2"})

    def test_both_versions_are_reported_in_coverage(self):
        snapshot.write_board(_board(model="ce.v1"), as_of="2026-08-04", path=self.db)
        snapshot.write_board(_board(model="ce.v2"), as_of="2026-08-04", path=self.db)
        self.assertEqual(snapshot.coverage(self.db)["modelVersions"], ["ce.v1", "ce.v2"])


def _prices(day_prices):
    """`{date: {player: {price, assetClass, position}}}` — what
    `outcomes.market_prices` returns and what `label_outcomes` now takes.

    It used to take a bare `{date: {player: price}}`, which is why the
    stored outcome was a RAW return: without a position and an origin
    price there is no cohort to be in excess of.

    Note that ORIGIN dates belong in here too, not just horizons: the
    cohort median is computed across the origin's whole population, so
    the map has to contain it. `snapshot.prices_by_date` supplies both
    by construction, which is what the production caller uses.
    """
    return {
        day: {
            name: {"price": price, "assetClass": "offense", "position": "WR"}
            for name, price in players.items()
        }
        for day, players in day_prices.items()
    }


class TestOutcomeLabelling(_TempDB):
    def test_outcomes_start_unlabelled(self):
        snapshot.write_board(_board(n=2), as_of="2026-08-04", path=self.db)
        self.assertEqual(snapshot.coverage(self.db)["rowsWithOutcomeLabels"], 0)

    def test_a_matured_horizon_gets_labelled(self):
        snapshot.write_board(_board(n=1), as_of="2026-08-01", path=self.db)
        # market 1000 -> 1100 over 14 days = +10%
        result = snapshot.label_outcomes(
            horizon_days=14,
            prices_by_date=_prices(
                {
                    "2026-08-01": {"Player 0": 1000.0},
                    "2026-08-15": {"Player 0": 1100.0},
                }
            ),
            path=self.db,
        )
        self.assertEqual(result["updated"], 1)
        rows = snapshot.history_for_player("Player 0", path=self.db)
        self.assertAlmostEqual(rows[0]["fwd_market_14d"], 0.1, places=6)

    def test_an_unmatured_horizon_is_left_alone(self):
        snapshot.write_board(_board(n=1), as_of="2026-08-01", path=self.db)
        result = snapshot.label_outcomes(horizon_days=14, prices_by_date={}, path=self.db)
        self.assertEqual(result["updated"], 0)
        self.assertEqual(snapshot.coverage(self.db)["rowsWithOutcomeLabels"], 0)

    def test_labelling_is_idempotent(self):
        snapshot.write_board(_board(n=1), as_of="2026-08-01", path=self.db)
        prices = _prices({"2026-08-01": {"Player 0": 1000.0}, "2026-08-15": {"Player 0": 1100.0}})
        snapshot.label_outcomes(horizon_days=14, prices_by_date=prices, path=self.db)
        again = snapshot.label_outcomes(horizon_days=14, prices_by_date=prices, path=self.db)
        self.assertEqual(again["updated"], 0, "an already-labelled row was relabelled")

    def test_an_unsupported_horizon_raises_rather_than_guessing(self):
        with self.assertRaises(ValueError):
            snapshot.label_outcomes(horizon_days=99, prices_by_date={}, path=self.db)

    def test_the_horizon_snaps_forward_when_the_exact_day_is_missing(self):
        # The panel has gaps. Requiring an exact origin+N hit silently
        # skipped every row whose horizon landed on a day nobody
        # snapshotted, which on a weekly-gap store is most of them.
        snapshot.write_board(_board(n=1), as_of="2026-08-01", path=self.db)
        result = snapshot.label_outcomes(
            horizon_days=14,
            prices_by_date=_prices(
                {
                    "2026-08-01": {"Player 0": 1000.0},
                    "2026-08-18": {"Player 0": 1100.0},
                }
            ),
            path=self.db,
        )
        self.assertEqual(result["updated"], 1)

    def test_it_never_snaps_backward(self):
        # A backward snap would shorten the holding period and bias every
        # return toward zero while looking like a successful labelling.
        snapshot.write_board(_board(n=1), as_of="2026-08-01", path=self.db)
        result = snapshot.label_outcomes(
            horizon_days=14,
            prices_by_date=_prices(
                {
                    "2026-08-01": {"Player 0": 1000.0},
                    "2026-08-10": {"Player 0": 1100.0},
                }
            ),
            path=self.db,
        )
        self.assertEqual(result["updated"], 0)
        self.assertEqual(result["noHorizonDate"], 1)

    def test_cohort_excess_is_stored_beside_the_raw_return(self):
        # Every other measurement in the package uses cohort-excess; a
        # store that keeps only the raw return records a player who rose
        # 3% in a market that rose 3% as a successful call.
        snapshot.write_board(_board(n=4), as_of="2026-08-01", path=self.db)
        prices = _prices(
            {
                "2026-08-01": {f"Player {i}": 1000.0 for i in range(4)},
                "2026-08-15": {
                    "Player 0": 1300.0,
                    "Player 1": 1100.0,
                    "Player 2": 1100.0,
                    "Player 3": 1100.0,
                },
            }
        )
        snapshot.label_outcomes(horizon_days=14, prices_by_date=prices, path=self.db)
        rows = snapshot.history_for_player("Player 0", path=self.db)
        self.assertAlmostEqual(rows[0]["fwd_market_14d"], 0.3, places=6)
        # Cohort median move was +10%, so the excess is +20 points.
        self.assertAlmostEqual(rows[0]["fwd_excess_14d"], 0.2, places=6)

    def test_a_rewrite_of_a_labelled_day_keeps_its_labels(self):
        """The defect this whole class was missing.

        `INSERT OR REPLACE` is DELETE-then-INSERT in SQLite, so the
        conflicting row is removed and every column the insert does not
        name comes back NULL — which is exactly the `fwd_*` columns the
        module docstring promises the write path never touches. The old
        tests never wrote after labelling, so nothing saw it.
        """
        snapshot.write_board(_board(n=1), as_of="2026-08-01", path=self.db)
        snapshot.label_outcomes(
            horizon_days=14,
            prices_by_date=_prices(
                {
                    "2026-08-01": {"Player 0": 1000.0},
                    "2026-08-15": {"Player 0": 1100.0},
                }
            ),
            path=self.db,
        )
        self.assertEqual(snapshot.coverage(self.db)["rowsWithOutcomeLabels"], 1)

        # Same date, same model, same params — the daily re-run.
        snapshot.write_board(_board(n=1, score=99.0), as_of="2026-08-01", path=self.db)
        rows = snapshot.history_for_player("Player 0", path=self.db)
        self.assertAlmostEqual(rows[0]["score"], 99.0, msg="the re-run did not update the score")
        self.assertIsNotNone(rows[0]["fwd_market_14d"], "the re-run destroyed the outcome label")

    def test_two_param_sets_on_one_date_are_labelled_independently(self):
        """The four-part key exists for this and was being ignored.

        SELECT and UPDATE keyed on `(as_of, player_key)`, so the first
        row's market value became the forward return for BOTH parameter
        sets — corrupting precisely the comparison a promotion decision
        would rest on. `updated` also under-counted, which is why the
        idempotency test passed vacuously.
        """
        cheap = _board(n=1, params="params-a")
        cheap["players"][0]["marketValue"] = 1000.0
        rich = _board(n=1, params="params-b")
        rich["players"][0]["marketValue"] = 2000.0
        snapshot.write_board(cheap, as_of="2026-08-01", path=self.db)
        snapshot.write_board(rich, as_of="2026-08-01", path=self.db)

        # The origin price map holds ONE price per (date, player) — the
        # market is not a property of the parameter set — so both rows
        # are judged against the same origin. What must differ is that
        # each row keeps its OWN stored market value, which is what the
        # two-column key protects.
        result = snapshot.label_outcomes(
            horizon_days=14,
            prices_by_date={
                "2026-08-01": {
                    "Player 0": {"price": 1000.0, "assetClass": "offense", "position": "WR"}
                },
                "2026-08-15": {
                    "Player 0": {"price": 1100.0, "assetClass": "offense", "position": "WR"}
                },
            },
            path=self.db,
        )
        self.assertEqual(result["updated"], 2, "one of the two parameter sets was skipped")

        conn = snapshot.connect(self.db)
        try:
            got = dict(
                conn.execute("SELECT param_set_id, fwd_market_14d FROM board_snapshots").fetchall()
            )
        finally:
            conn.close()
        # Both rows are updated — the point of the four-part key. The
        # old code selected two rows, keyed the UPDATE on two columns,
        # wrote the same value to both, and counted it once.
        self.assertAlmostEqual(got["params-a"], 0.1, places=6)
        self.assertAlmostEqual(got["params-b"], 0.1, places=6)


class TestTheStoreCanLabelItself(_TempDB):
    """`label_outcomes` had zero callers, and this is why it now has one.

    The obvious source of past prices is the git panel, which is
    expensive, needs an unshallow clone, and does not exist on the box
    running the timer. The store's own `market_value` column is the
    price the board was judged against on the day, written by the same
    code path that will write the horizon's.
    """

    def test_prices_by_date_reads_back_what_was_written(self):
        snapshot.write_board(_board(n=2), as_of="2026-08-01", path=self.db)
        snapshot.write_board(_board(n=2), as_of="2026-08-15", path=self.db)
        prices = snapshot.prices_by_date(self.db)
        self.assertEqual(sorted(prices), ["2026-08-01", "2026-08-15"])
        self.assertEqual(prices["2026-08-01"]["Player 0"]["price"], 1000.0)
        self.assertTrue(prices["2026-08-01"]["Player 0"]["position"])

    def test_a_round_trip_through_its_own_prices_labels_the_store(self):
        # n=6 so each of the two cohorts (_board alternates WR/offense
        # and LB/idp) has three members — the minimum for a cohort median
        # to exist at all.
        snapshot.write_board(_board(n=6), as_of="2026-08-01", path=self.db)
        later = _board(n=6)
        for i, row in enumerate(later["players"]):
            row["marketValue"] = 1300.0 if i == 0 else 1100.0
        snapshot.write_board(later, as_of="2026-08-15", path=self.db)

        result = snapshot.label_outcomes(
            horizon_days=14, prices_by_date=snapshot.prices_by_date(self.db), path=self.db
        )
        # Only the 2026-08-01 rows have a matured horizon; the
        # 2026-08-15 rows have no future date in the store yet.
        self.assertEqual(result["updated"], 6)
        self.assertEqual(snapshot.coverage(self.db)["rowsWithCohortExcess"], 6)

    def test_an_empty_store_yields_no_prices_rather_than_raising(self):
        self.assertEqual(snapshot.prices_by_date(self.db), {})


class TestMigration(unittest.TestCase):
    """`CREATE TABLE IF NOT EXISTS` is a no-op against an existing table.

    A database written by the v1 schema would keep its old columns
    forever, and every write naming a new one would fail — so the
    migration is the difference between shipping this change and
    breaking the only irreplaceable data the feature has.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "ce.sqlite"

    def tearDown(self):
        self._tmp.cleanup()

    def _make_v1(self):
        import sqlite3

        conn = sqlite3.connect(str(self.db))
        try:
            conn.execute(
                """
                CREATE TABLE board_snapshots (
                    as_of TEXT NOT NULL, player_key TEXT NOT NULL,
                    model_version TEXT NOT NULL, param_set_id TEXT NOT NULL,
                    display_name TEXT, position TEXT, asset_class TEXT,
                    score REAL, label TEXT, label_reason TEXT, qualified INTEGER,
                    confidence REAL,
                    component_mispricing REAL, component_sharp_flow REAL,
                    component_opportunity REAL, components_absent TEXT,
                    fair_value REAL, market_value REAL, anchor_key TEXT,
                    pct_gap REAL, unpriced_reason TEXT,
                    conflicted INTEGER, confidence_factors TEXT, hours_stale REAL,
                    contract_scraped_at TEXT, written_at TEXT NOT NULL,
                    fwd_market_7d REAL, fwd_market_14d REAL, fwd_market_30d REAL,
                    PRIMARY KEY (as_of, player_key, model_version, param_set_id)
                )
                """
            )
            conn.execute(
                "INSERT INTO board_snapshots (as_of, player_key, model_version, "
                "param_set_id, market_value, written_at, fwd_market_14d) "
                "VALUES ('2026-07-01', 'Old Player', 'ce.v0', 'old', 900.0, 'then', 0.05)"
            )
            conn.commit()
        finally:
            conn.close()
        snapshot._SETUP_DONE.pop(str(self.db), None)

    def test_a_v1_database_gains_the_new_columns(self):
        self._make_v1()
        snapshot.connect(self.db).close()
        conn = snapshot.connect(self.db)
        try:
            have = {r[1] for r in conn.execute("PRAGMA table_info(board_snapshots)").fetchall()}
        finally:
            conn.close()
        for name, _decl in snapshot._ADDED_COLUMNS:
            self.assertIn(name, have)

    def test_the_migration_keeps_the_rows_it_finds(self):
        self._make_v1()
        rows = snapshot.history_for_player("Old Player", path=self.db)
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0]["fwd_market_14d"], 0.05, places=6)

    def test_writing_after_migration_works(self):
        self._make_v1()
        result = snapshot.write_board(_board(n=1), as_of="2026-08-04", path=self.db)
        self.assertEqual(result["written"], 1)


class TestProvenanceIsStored(_TempDB):
    def test_every_row_carries_model_and_param_versions(self):
        snapshot.write_board(_board(n=2), as_of="2026-08-04", path=self.db)
        for row in snapshot.history_for_player("Player 0", path=self.db):
            self.assertTrue(row["model_version"])
            self.assertTrue(row["param_set_id"])

    def test_input_staleness_is_recorded(self):
        # Without it a stored row cannot be reproduced: the same board on
        # the same day with staler data is a different claim.
        snapshot.write_board(_board(n=1), as_of="2026-08-04", path=self.db)
        conn = snapshot.connect(self.db)
        try:
            value = conn.execute("SELECT hours_stale FROM board_snapshots").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(value, 6.0)


class TestRealBoardRoundTrip(unittest.TestCase):
    """A real board, not a fixture, survives the round trip."""

    def test_a_real_board_can_be_written_and_read(self):
        import json
        import zipfile

        repo = Path(__file__).resolve().parents[2]
        zips = sorted((repo / "exports" / "archive").glob("dynasty_export_*.zip"))
        if not zips:
            self.skipTest("no archived payload")
        with zipfile.ZipFile(zips[-1]) as zf:
            names = [n for n in zf.namelist() if n.startswith("dynasty_data_")]
            raw = json.loads(zf.read(names[0]))

        from src.consensus_edge import service

        board = service.build_board(raw, hours_stale=service.resolve_hours_stale(raw))
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "ce.sqlite"
            result = snapshot.write_board(board, as_of=date(2026, 8, 4), path=db)
            self.assertGreater(result["written"], 100)
            cov = snapshot.coverage(db)
            self.assertEqual(cov["rows"], result["written"])


if __name__ == "__main__":
    unittest.main()
