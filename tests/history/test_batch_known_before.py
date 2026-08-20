"""``asof.batch_known_before`` — the batched, instant-strict sibling of
``value_known_before`` added for historical trade replay (V1-97 /
C3-REPLAY-01).

Each request carries its OWN instant (unlike ``batch_as_of``, which shares
one date across every asset) because the same player recurs across many
trades at different timestamps.  These tests pin:

* per-request instant-strict selection is identical to calling
  ``value_known_before`` once per request (T0/T1/T2 semantics);
* never-future selection, exhaustively;
* the batching itself: one SQL round trip per DISTINCT asset key, not per
  request;
* positional-order preservation, including repeated keys;
* the naive-instant / pre-boundary / no-ledger degenerate paths behave
  exactly like the single-item function.
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from src.history import asof, store


class _LedgerCase(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.ledger = Path(self._td.name) / "ledger.sqlite"
        store._reset_setup_cache_for_tests()

    def _write(self, asset_key, observed_date, value, *, observed_at=None, origin="test"):
        result = store.write_observations(
            [
                {
                    "asset_key": asset_key,
                    "asset_class": "offense",
                    "lane": store.LANE_CANONICAL,
                    "source_key": "",
                    "observed_date": observed_date,
                    "observed_at": observed_at,
                    "value": value,
                    "origin": origin,
                }
            ],
            path=self.ledger,
        )
        assert result["written"] == 1, result
        return result


class TestCoreSelection(_LedgerCase):
    """T0/T1/T2: the direct bug reproduction, at the batch layer."""

    def test_t0_t1_t2_selects_the_prior_observation_not_the_latest(self):
        self._write("player:X", "2026-07-15", 4000.0, observed_at="2026-07-15T12:00:00+00:00")
        self._write("player:X", "2026-08-10", 8000.0, observed_at="2026-08-10T12:00:00+00:00")
        t1 = datetime(2026, 7, 20, 0, 0, tzinfo=timezone.utc)
        out = asof.batch_known_before([("player:X", t1)], path=self.ledger)
        r = out["results"][0]
        self.assertEqual(r["value"], 4000.0)
        self.assertEqual(r["fidelity"], asof.FIDELITY_NEAREST_PRIOR)

    def test_exact_instant_match(self):
        self._write("player:X", "2026-07-20", 5000.0, observed_at="2026-07-20T09:00:00+00:00")
        t1 = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)
        out = asof.batch_known_before([("player:X", t1)], path=self.ledger)
        r = out["results"][0]
        self.assertEqual(r["value"], 5000.0)
        self.assertEqual(r["fidelity"], asof.FIDELITY_EXACT)

    def test_only_future_observation_exists_is_unavailable(self):
        self._write("player:X", "2026-08-10", 8000.0, observed_at="2026-08-10T12:00:00+00:00")
        t0 = datetime(2026, 7, 20, 0, 0, tzinfo=timezone.utc)
        out = asof.batch_known_before([("player:X", t0)], path=self.ledger)
        r = out["results"][0]
        self.assertEqual(r["fidelity"], asof.FIDELITY_UNAVAILABLE)
        self.assertEqual(r["missingReason"], asof.REASON_NO_PRIOR)
        self.assertIsNone(r["value"])

    def test_no_observation_at_all_is_unavailable(self):
        t0 = datetime(2026, 7, 20, 0, 0, tzinfo=timezone.utc)
        out = asof.batch_known_before([("player:nowhere", t0)], path=self.ledger)
        r = out["results"][0]
        self.assertEqual(r["fidelity"], asof.FIDELITY_UNAVAILABLE)
        self.assertEqual(r["missingReason"], asof.REASON_NO_PRIOR)

    def test_ledger_does_not_exist_yet(self):
        missing = Path(self._td.name) / "never_written.sqlite"
        t0 = datetime(2026, 7, 20, 0, 0, tzinfo=timezone.utc)
        out = asof.batch_known_before([("player:X", t0)], path=missing)
        r = out["results"][0]
        self.assertEqual(r["fidelity"], asof.FIDELITY_UNAVAILABLE)
        self.assertFalse(missing.exists())

    def test_before_permanent_boundary_is_permanent_missing(self):
        t0 = datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc)
        out = asof.batch_known_before([("player:X", t0)], path=self.ledger)
        r = out["results"][0]
        self.assertEqual(r["fidelity"], asof.FIDELITY_UNAVAILABLE)
        self.assertEqual(r["missingReason"], asof.REASON_BEFORE_BOUNDARY)


class TestBoardMovingDoesNotChangeThePast(_LedgerCase):
    """T-BOARD-BUMP: the direct proof the hindsight leak is closed —
    appending a later observation must never change an earlier
    known-before answer."""

    def test_appending_a_post_trade_observation_does_not_move_the_past_answer(self):
        self._write("player:X", "2026-07-15", 4000.0, observed_at="2026-07-15T12:00:00+00:00")
        trade_instant = datetime(2026, 7, 20, 0, 0, tzinfo=timezone.utc)

        before = asof.batch_known_before([("player:X", trade_instant)], path=self.ledger)
        self.assertEqual(before["results"][0]["value"], 4000.0)

        # "The board moved" — a brand new, much larger observation lands
        # after the trade date.
        self._write("player:X", "2026-08-10", 9999.0, observed_at="2026-08-10T12:00:00+00:00")

        after = asof.batch_known_before([("player:X", trade_instant)], path=self.ledger)
        self.assertEqual(before["results"][0], after["results"][0])


class TestNeverFuture(_LedgerCase):
    def test_never_future_exhaustive(self):
        """Property, exhaustively over a date lattice: the batched
        selection never returns an observation dated after the
        requested instant's UTC date."""
        obs_dates = ["2026-07-20", "2026-07-28", "2026-08-05", "2026-08-13"]
        for i, d in enumerate(obs_dates):
            self._write("player:X", d, float(1000 * (i + 1)), observed_at=f"{d}T12:00:00+00:00")

        requests = []
        offsets = list(range(0, 40))
        start = datetime(2026, 7, 14, tzinfo=timezone.utc)
        for offset in offsets:
            requests.append(("player:X", start + timedelta(days=offset, hours=6)))

        out = asof.batch_known_before(requests, path=self.ledger)
        for (_, instant), r in zip(requests, out["results"]):
            if r["fidelity"] == asof.FIDELITY_UNAVAILABLE:
                self.assertEqual(r["missingReason"], asof.REASON_NO_PRIOR)
            else:
                self.assertLessEqual(r["observedDate"], instant.date().isoformat())


class TestInstantStrictSameDayExclusion(_LedgerCase):
    def test_unproven_same_day_instant_is_excluded(self):
        # Naive observed_at ⇒ normalized to NULL at the write path ⇒ an
        # unknown instant, never proven at-or-before a same-day query.
        self._write("player:X", "2026-08-16", 4947.0, observed_at="2026-08-16")
        early = datetime(2026, 8, 16, 6, 0, tzinfo=timezone.utc)
        out = asof.batch_known_before([("player:X", early)], path=self.ledger)
        self.assertEqual(out["results"][0]["fidelity"], asof.FIDELITY_UNAVAILABLE)

        self._write("player:X", "2026-08-15", 4000.0, observed_at="2026-08-15T12:00:00+00:00")
        out2 = asof.batch_known_before([("player:X", early)], path=self.ledger)
        self.assertEqual(out2["results"][0]["observedDate"], "2026-08-15")

    def test_negative_utc_offset_compares_correctly(self):
        self._write(
            "player:X",
            "2026-08-16",
            4947.0,
            # 18:00-07:00 == 2026-08-17T01:00Z — AFTER the earlier query
            # instant despite sorting before it as text.
            observed_at="2026-08-16T18:00:00-07:00",
        )
        q = datetime(2026, 8, 16, 23, 0, tzinfo=timezone.utc)
        out = asof.batch_known_before([("player:X", q)], path=self.ledger)
        self.assertEqual(out["results"][0]["fidelity"], asof.FIDELITY_UNAVAILABLE)

        q2 = datetime(2026, 8, 17, 2, 0, tzinfo=timezone.utc)
        out2 = asof.batch_known_before([("player:X", q2)], path=self.ledger)
        self.assertEqual(out2["results"][0]["observedDate"], "2026-08-16")


class TestMultipleObservationsSameDayDeterminism(_LedgerCase):
    def test_tie_resolution_matches_select_best(self):
        self._write(
            "player:X",
            "2026-08-16",
            100.0,
            observed_at="2026-08-16T09:00:00+00:00",
            origin="scraper",
        )
        self._write(
            "player:X",
            "2026-08-16",
            200.0,
            observed_at="2026-08-16T18:00:00+00:00",
            origin="scraper",
        )
        q = datetime(2026, 8, 16, 23, 0, tzinfo=timezone.utc)
        single = asof.value_known_before("player:X", q, path=self.ledger)
        out = asof.batch_known_before([("player:X", q)], path=self.ledger)
        self.assertEqual(out["results"][0]["value"], single["value"])
        self.assertEqual(out["results"][0]["value"], 200.0)


class TestNaiveInstantRefused(_LedgerCase):
    def test_naive_instant_raises_before_touching_the_ledger(self):
        # A naive instant anywhere in the batch must be refused before any
        # connection is opened — including when it is not the first item.
        aware = datetime(2026, 8, 16, 6, 0, tzinfo=timezone.utc)
        naive = datetime(2026, 8, 16, 6, 0)
        with self.assertRaises(store.ObservationError):
            asof.batch_known_before([("player:X", aware), ("player:Y", naive)], path=self.ledger)


class TestPositionalOrderAndRepeatedKeys(_LedgerCase):
    def test_results_align_with_request_order_including_repeats(self):
        self._write("player:A", "2026-07-15", 1000.0, observed_at="2026-07-15T12:00:00+00:00")
        self._write("player:A", "2026-08-01", 2000.0, observed_at="2026-08-01T12:00:00+00:00")
        self._write("player:B", "2026-07-18", 500.0, observed_at="2026-07-18T12:00:00+00:00")

        t_before_bump = datetime(2026, 7, 20, 0, 0, tzinfo=timezone.utc)
        t_after_bump = datetime(2026, 8, 5, 0, 0, tzinfo=timezone.utc)

        requests = [
            ("player:A", t_before_bump),  # -> 1000
            ("player:B", t_before_bump),  # -> 500
            ("player:A", t_after_bump),  # -> 2000 (repeat of key A, different instant)
            ("player:A", t_before_bump),  # -> 1000 (exact repeat)
        ]
        out = asof.batch_known_before(requests, path=self.ledger)
        values = [r["value"] for r in out["results"]]
        self.assertEqual(values, [1000.0, 500.0, 2000.0, 1000.0])


class TestOneFetchPerDistinctKey(_LedgerCase):
    """The whole point of batching: a key repeated across N requests must
    cost one SQL round trip, not N."""

    def test_fetch_candidates_called_once_per_distinct_key(self):
        self._write("player:A", "2026-07-15", 1000.0, observed_at="2026-07-15T12:00:00+00:00")
        self._write("player:B", "2026-07-16", 2000.0, observed_at="2026-07-16T12:00:00+00:00")

        t = datetime(2026, 8, 1, 0, 0, tzinfo=timezone.utc)
        requests = [
            ("player:A", t),
            ("player:A", t + timedelta(days=1)),
            ("player:A", t + timedelta(days=2)),
            ("player:B", t),
            ("player:B", t + timedelta(days=1)),
        ]
        with mock.patch.object(asof, "_fetch_candidates", wraps=asof._fetch_candidates) as spy:
            asof.batch_known_before(requests, path=self.ledger)
        self.assertEqual(spy.call_count, 2)
        called_keys = sorted(c.args[1] for c in spy.call_args_list)
        self.assertEqual(called_keys, ["player:A", "player:B"])


class TestSummaryAggregate(_LedgerCase):
    def test_partial_fidelity_summary(self):
        self._write("player:A", "2026-08-16", 1000.0, observed_at="2026-08-16T12:00:00+00:00")
        t = datetime(2026, 8, 20, 0, 0, tzinfo=timezone.utc)
        out = asof.batch_known_before([("player:A", t), ("player:nowhere", t)], path=self.ledger)
        self.assertEqual(out["summary"]["items"], 2)
        self.assertEqual(out["summary"]["exact"], 0)
        self.assertEqual(out["summary"]["nearestPrior"], 1)
        self.assertEqual(out["summary"]["unavailable"], 1)
        self.assertEqual(out["summary"]["fidelity"], asof.FIDELITY_PARTIAL)

    def test_empty_batch(self):
        out = asof.batch_known_before([], path=self.ledger)
        self.assertEqual(out["results"], [])
        self.assertEqual(out["summary"]["fidelity"], asof.FIDELITY_UNAVAILABLE)
        self.assertEqual(out["summary"]["items"], 0)


class TestMaxAgeBudget(_LedgerCase):
    def test_max_age_days_downgrades_a_stale_prior_observation(self):
        self._write("player:X", "2026-07-20", 4000.0, observed_at="2026-07-20T12:00:00+00:00")
        t = datetime(2026, 8, 16, 0, 0, tzinfo=timezone.utc)
        out = asof.batch_known_before([("player:X", t)], path=self.ledger, max_age_days=7)
        r = out["results"][0]
        self.assertEqual(r["fidelity"], asof.FIDELITY_UNAVAILABLE)
        self.assertEqual(r["missingReason"], asof.REASON_OUTSIDE_MAX_AGE)
        self.assertEqual(r["nearestPriorDate"], "2026-07-20")

    def test_default_has_no_freshness_budget(self):
        self._write("player:X", "2026-07-20", 4000.0, observed_at="2026-07-20T12:00:00+00:00")
        t = datetime(2026, 8, 16, 0, 0, tzinfo=timezone.utc)
        out = asof.batch_known_before([("player:X", t)], path=self.ledger)
        self.assertEqual(out["results"][0]["fidelity"], asof.FIDELITY_NEAREST_PRIOR)


if __name__ == "__main__":
    unittest.main()
