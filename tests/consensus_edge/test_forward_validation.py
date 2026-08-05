"""The forward-only component study, on a synthetic snapshot store.

This is the arm that measures Sharp Flow, and it is the only one that
can: a historical Sharp Flow backtest is unsound at any budget because
the movement corpus is survivorship-biased upstream (the crawler visits
only currently-qualified managers), so no as-of filter can fix it.
Forward-only sidesteps that entirely — the signal was written on the day
and the outcome weeks later.

The database is prod-only, so every test here builds its own.
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

from src.consensus_edge import snapshot as snap  # noqa: E402


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "validate_components_forward", REPO / "scripts" / "validate_components_forward.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


script = _load_script()


def _seed(path: Path, rows: list[tuple]) -> None:
    """`(as_of, player_key, sharp_flow, fwd_excess_14d)` straight in.

    Deliberately writes the columns directly rather than going through
    `write_board`: what is under test is the READ, and building a full
    board payload per row would couple this suite to the board's shape
    for no gain.
    """
    conn = snap.connect(path)
    try:
        conn.executemany(
            "INSERT INTO board_snapshots (as_of, player_key, model_version, "
            "param_set_id, component_sharp_flow, fwd_excess_14d, market_value, "
            "written_at) VALUES (?,?,?,?,?,?,?,?)",
            [(a, p, "test.v1", "pp", sf, fwd, 1000.0, a) for a, p, sf, fwd in rows],
        )
        conn.commit()
    finally:
        conn.close()


class TestMeasure(unittest.TestCase):
    def setUp(self):
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "ce.sqlite"

    def tearDown(self):
        self._tmp.cleanup()

    def _perfect_origin(self, as_of: str, n: int = 30, sign: int = 1):
        return [(as_of, f"p{i}", float(i), float(sign * i)) for i in range(n)]

    def test_a_perfectly_ordered_origin_scores_one(self):
        _seed(self.db, self._perfect_origin("2026-06-01"))
        run = script.measure("component_sharp_flow", horizon_days=14, path=self.db)
        self.assertAlmostEqual(run["origins"][0]["rho"], 1.0, places=6)

    def test_an_inverted_origin_scores_minus_one(self):
        _seed(self.db, self._perfect_origin("2026-06-01", sign=-1))
        run = script.measure("component_sharp_flow", horizon_days=14, path=self.db)
        self.assertAlmostEqual(run["origins"][0]["rho"], -1.0, places=6)

    def test_a_thin_origin_is_refused_rather_than_correlated(self):
        # Five pairs will produce a rho, and it will be noise wearing a
        # number. The floor matches the panel studies' so the two report
        # comparable things.
        _seed(self.db, self._perfect_origin("2026-06-01", n=5))
        run = script.measure("component_sharp_flow", horizon_days=14, path=self.db)
        self.assertIsNone(run["origins"][0]["rho"])
        self.assertEqual(run["origins"][0]["reason"], "too few pairs")
        self.assertEqual(run["originsUsable"], 0)

    def test_origins_are_correlated_separately_not_pooled(self):
        """Two origins that disagree must not cancel into one number.

        Pooling would also let a busy date dominate and would mix
        cohorts whose excess returns are centred on different days.
        """
        rows = self._perfect_origin("2026-06-01") + self._perfect_origin("2026-06-15", sign=-1)
        _seed(self.db, rows)
        run = script.measure("component_sharp_flow", horizon_days=14, path=self.db)
        self.assertEqual(run["originsUsable"], 2)
        self.assertAlmostEqual(run["meanSpearman"], 0.0, places=6)
        self.assertEqual({round(o["rho"]) for o in run["origins"]}, {1, -1})

    def test_unlabelled_rows_are_excluded_not_treated_as_zero(self):
        # A row whose horizon has not elapsed has NULL outcome. Reading
        # that as a zero return would dilute every correlation toward
        # nothing and look like a null result.
        _seed(self.db, self._perfect_origin("2026-06-01"))
        conn = snap.connect(self.db)
        conn.executemany(
            "INSERT INTO board_snapshots (as_of, player_key, model_version, "
            "param_set_id, component_sharp_flow, market_value, written_at) "
            "VALUES (?,?,?,?,?,?,?)",
            [("2026-06-01", f"unlabelled{i}", "test.v1", "pp", 5.0, 1.0, "x") for i in range(50)],
        )
        conn.commit()
        conn.close()
        run = script.measure("component_sharp_flow", horizon_days=14, path=self.db)
        self.assertEqual(run["labelledRows"], 30)
        self.assertAlmostEqual(run["origins"][0]["rho"], 1.0, places=6)

    def test_an_empty_component_column_reports_zero_rows_not_a_null_result(self):
        # This is the Sharp-Flow-without-a-ledger case, and it must not
        # read as "measured, no effect".
        _seed(self.db, self._perfect_origin("2026-06-01"))
        run = script.measure("component_opportunity", horizon_days=14, path=self.db)
        self.assertEqual(run["labelledRows"], 0)
        self.assertIsNone(run["meanSpearman"])
        self.assertIn("no origin has enough labelled rows", run["verdict"])


class TestVerdicts(unittest.TestCase):
    def _usable(self, *rhos):
        return [{"origin": f"d{i}", "n": 50, "rho": r} for i, r in enumerate(rhos)]

    def test_under_three_origins_is_underpowered_whatever_the_mean(self):
        v = script._verdict("x", self._usable(0.9, 0.9), 0.9, 2)
        self.assertIn("underpowered", v)
        self.assertIn("completeness only", v)

    def test_a_consistent_positive_is_called_positive(self):
        v = script._verdict("x", self._usable(0.2, 0.3, 0.25, 0.4), 0.29, 4)
        self.assertIn("positive and consistent", v)

    def test_a_mixed_sign_is_no_effect_even_with_a_positive_mean(self):
        v = script._verdict("x", self._usable(0.9, -0.4, 0.1, -0.2), 0.1, 2)
        self.assertIn("no effect detected", v)


class TestCli(unittest.TestCase):
    def setUp(self):
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "ce.sqlite"

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_missing_database_is_a_soft_failure_not_a_crash(self):
        rc = script.main(["--db", str(self.db), "--dry-run"])
        self.assertEqual(rc, 1)

    def test_a_database_with_no_labelled_rows_is_a_soft_failure(self):
        snap.connect(self.db).close()
        rc = script.main(["--db", str(self.db), "--dry-run"])
        self.assertEqual(rc, 1)

    def test_a_populated_database_produces_a_summary(self):
        _seed(self.db, [("2026-06-01", f"p{i}", float(i), float(i)) for i in range(30)])
        rc = script.main(["--db", str(self.db), "--dry-run"])
        self.assertEqual(rc, 0)

    def test_it_measures_every_series_not_only_sharp_flow(self):
        # The components have to be comparable to each other and to the
        # ranking key users actually see, or a Sharp Flow number has
        # nothing to be judged against.
        self.assertIn("conviction", script.SERIES)
        self.assertIn("component_mispricing", script.SERIES)
        self.assertIn("component_sharp_flow", script.SERIES)

    def test_every_series_names_a_real_stored_column(self):
        # A typo here would silently measure nothing and report a clean
        # null — the failure mode this whole package keeps finding.
        # Checked against the snapshot path's own column list, not a
        # second copy of it.
        self.assertTrue(
            set(script.SERIES) <= set(snap._OWNED_COLUMNS),
            f"not stored columns: {sorted(set(script.SERIES) - set(snap._OWNED_COLUMNS))}",
        )


if __name__ == "__main__":
    sys.exit(unittest.main())
