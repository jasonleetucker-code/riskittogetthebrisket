"""V1-97 / C3-REPLAY-01 — the as-of half of the public activity valuation
bridge: ``asset_history_key``, ``trade_instant_from_created_at`` and
``build_asof_valuation``.

The defect these functions close: the public /league Activity tab's
trade-grade badge was computed from TODAY's canonical board
(``build_valuation_from_contract(latest_contract_data)``) with no date
parameter anywhere, so a trade from a month ago and a trade from this
morning were graded against the identical, current values — a
hindsight leak.  ``build_asof_valuation`` instead resolves every asset
strictly against the canonical temporal ledger (``src.history.asof``)
AS OF the trade's own instant, and returns ``None`` — never a
substituted current value — when the ledger has no admissible
observation.
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from src.api.public_activity_valuation import (
    asset_history_key,
    build_asof_valuation,
    trade_instant_from_created_at,
)
from src.history import store


class AssetHistoryKeyTests(unittest.TestCase):
    def test_player_with_platform_id(self) -> None:
        asset = {"kind": "player", "playerId": "5859", "playerName": "Some Guy", "position": "WR"}
        self.assertEqual(asset_history_key(asset), "player:5859")

    def test_player_without_platform_id_falls_back_to_name_key(self) -> None:
        asset = {"kind": "player", "playerId": "", "playerName": "Ja'Marr Chase", "position": "WR"}
        key = asset_history_key(asset)
        self.assertIsNotNone(key)
        self.assertTrue(key.startswith("name:"))

    def test_pick_generic_grade(self) -> None:
        asset = {"kind": "pick", "season": "2027", "round": 1}
        self.assertEqual(asset_history_key(asset), "mpick:2027:r1")

    def test_pick_with_non_numeric_season_is_unresolved(self) -> None:
        self.assertIsNone(asset_history_key({"kind": "pick", "season": "", "round": 1}))
        self.assertIsNone(asset_history_key({"kind": "pick", "season": "2027", "round": None}))

    def test_pick_with_out_of_range_round_is_unresolved_not_raised(self) -> None:
        # MarketPickRef.__post_init__ raises ValueError for round 0 / 99;
        # this must degrade to None, never propagate the exception.
        self.assertIsNone(asset_history_key({"kind": "pick", "season": "2027", "round": 0}))
        self.assertIsNone(asset_history_key({"kind": "pick", "season": "2027", "round": 99}))

    def test_unknown_kind_and_non_dict_are_unresolved(self) -> None:
        self.assertIsNone(asset_history_key({"kind": "other"}))
        self.assertIsNone(asset_history_key(None))
        self.assertIsNone(asset_history_key("not-a-dict"))


class TradeInstantFromCreatedAtTests(unittest.TestCase):
    def test_valid_epoch_ms(self) -> None:
        instant = trade_instant_from_created_at(1752580800000)
        self.assertIsNotNone(instant)
        self.assertEqual(instant.tzinfo, timezone.utc)
        self.assertEqual(instant.year, 2025)

    def test_missing_zero_negative_and_non_numeric_are_none(self) -> None:
        for bad in (None, 0, -1, "not-a-number", "", [], {}):
            with self.subTest(value=bad):
                self.assertIsNone(trade_instant_from_created_at(bad))

    def test_numeric_string_is_accepted(self) -> None:
        # Sleeper's own JSON sometimes carries this as a string.
        instant = trade_instant_from_created_at("1752580800000")
        self.assertIsNotNone(instant)


class _LedgerCase(unittest.TestCase):
    def setUp(self) -> None:
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


class BuildAsofValuationTests(_LedgerCase):
    """T0/T1/T2 at the public-activity resolver layer."""

    def test_t0_t1_t2_resolves_the_prior_value_not_the_latest(self) -> None:
        self._write("player:5859", "2026-07-15", 4000.0, observed_at="2026-07-15T12:00:00+00:00")
        self._write("player:5859", "2026-08-10", 9999.0, observed_at="2026-08-10T12:00:00+00:00")

        asset = {"kind": "player", "playerId": "5859", "playerName": "X", "position": "WR"}
        t1 = datetime(2026, 7, 20, tzinfo=timezone.utc)
        resolve = build_asof_valuation([(asset, t1)], path=self.ledger)
        self.assertEqual(resolve(asset, t1), 4000.0)

    def test_board_moving_after_the_trade_never_changes_the_answer(self) -> None:
        self._write("player:5859", "2026-07-15", 4000.0, observed_at="2026-07-15T12:00:00+00:00")
        asset = {"kind": "player", "playerId": "5859", "playerName": "X", "position": "WR"}
        t1 = datetime(2026, 7, 20, tzinfo=timezone.utc)

        resolve = build_asof_valuation([(asset, t1)], path=self.ledger)
        before = resolve(asset, t1)

        # "The board moved": append a much larger post-trade observation
        # and rebuild the resolver, exactly as a later /league request
        # would with a fresh factory call.
        self._write("player:5859", "2026-08-10", 9999.0, observed_at="2026-08-10T12:00:00+00:00")
        resolve2 = build_asof_valuation([(asset, t1)], path=self.ledger)
        after = resolve2(asset, t1)
        self.assertEqual(before, after)
        self.assertEqual(before, 4000.0)

    def test_only_future_observation_exists_resolves_to_none(self) -> None:
        self._write("player:5859", "2026-08-10", 9999.0, observed_at="2026-08-10T12:00:00+00:00")
        asset = {"kind": "player", "playerId": "5859", "playerName": "X", "position": "WR"}
        t0 = datetime(2026, 7, 20, tzinfo=timezone.utc)
        resolve = build_asof_valuation([(asset, t0)], path=self.ledger)
        self.assertIsNone(resolve(asset, t0))

    def test_no_observation_at_all_resolves_to_none(self) -> None:
        asset = {"kind": "player", "playerId": "nowhere", "playerName": "Ghost", "position": "WR"}
        t0 = datetime(2026, 7, 20, tzinfo=timezone.utc)
        resolve = build_asof_valuation([(asset, t0)], path=self.ledger)
        self.assertIsNone(resolve(asset, t0))

    def test_never_substitutes_a_current_value_for_a_missing_historical_one(self) -> None:
        # A player who is heavily priced TODAY but has zero ledger
        # coverage before the trade instant must resolve to None, never
        # to a plausible-looking current-ish number.  There is nothing
        # here for the resolver to fall back to -- proving the absence
        # of a fallback path, not just its behavior on one input.
        self._write("player:5859", "2026-08-18", 9500.0, observed_at="2026-08-18T12:00:00+00:00")
        asset = {"kind": "player", "playerId": "5859", "playerName": "X", "position": "WR"}
        t0 = datetime(2026, 7, 20, tzinfo=timezone.utc)  # before the only observation
        resolve = build_asof_valuation([(asset, t0)], path=self.ledger)
        self.assertIsNone(resolve(asset, t0))

    def test_missing_instant_resolves_to_none(self) -> None:
        asset = {"kind": "player", "playerId": "5859", "playerName": "X", "position": "WR"}
        resolve = build_asof_valuation([(asset, None)], path=self.ledger)
        self.assertIsNone(resolve(asset, None))

    def test_naive_instant_resolves_to_none_rather_than_raising(self) -> None:
        # A caller that skipped tz-awareness gets a clean miss, not an
        # ObservationError leaking out of a valuation call.
        asset = {"kind": "player", "playerId": "5859", "playerName": "X", "position": "WR"}
        naive = datetime(2026, 7, 20)
        resolve = build_asof_valuation([(asset, naive)], path=self.ledger)
        self.assertIsNone(resolve(asset, naive))

    def test_pick_resolves_via_the_generic_market_ref(self) -> None:
        self._write("mpick:2027:r1", "2026-07-20", 3000.0, observed_at="2026-07-20T12:00:00+00:00")
        asset = {"kind": "pick", "season": "2027", "round": 1}
        t1 = datetime(2026, 7, 25, tzinfo=timezone.utc)
        resolve = build_asof_valuation([(asset, t1)], path=self.ledger)
        self.assertEqual(resolve(asset, t1), 3000.0)

    def test_out_of_range_pick_round_resolves_to_none_not_a_crash(self) -> None:
        asset = {"kind": "pick", "season": "2027", "round": 0}
        t1 = datetime(2026, 7, 25, tzinfo=timezone.utc)
        resolve = build_asof_valuation([(asset, t1)], path=self.ledger)
        self.assertIsNone(resolve(asset, t1))

    def test_multiple_observations_same_day_deterministic_tie(self) -> None:
        self._write("player:5859", "2026-08-16", 100.0, observed_at="2026-08-16T09:00:00+00:00")
        self._write("player:5859", "2026-08-16", 200.0, observed_at="2026-08-16T18:00:00+00:00")
        asset = {"kind": "player", "playerId": "5859", "playerName": "X", "position": "WR"}
        q = datetime(2026, 8, 16, 23, 0, tzinfo=timezone.utc)
        resolve = build_asof_valuation([(asset, q)], path=self.ledger)
        self.assertEqual(resolve(asset, q), 200.0)

    def test_timezone_boundary_negative_offset(self) -> None:
        self._write(
            "player:5859",
            "2026-08-16",
            4947.0,
            # 18:00-07:00 == 2026-08-17T01:00Z
            observed_at="2026-08-16T18:00:00-07:00",
        )
        asset = {"kind": "player", "playerId": "5859", "playerName": "X", "position": "WR"}
        q_before = datetime(2026, 8, 16, 23, 0, tzinfo=timezone.utc)
        resolve_before = build_asof_valuation([(asset, q_before)], path=self.ledger)
        self.assertIsNone(resolve_before(asset, q_before))

        q_after = datetime(2026, 8, 17, 2, 0, tzinfo=timezone.utc)
        resolve_after = build_asof_valuation([(asset, q_after)], path=self.ledger)
        self.assertEqual(resolve_after(asset, q_after), 4947.0)

    def test_decoupled_from_any_current_or_live_board(self) -> None:
        # The resolver never reads latest_contract_data or any "current"
        # source at all -- a player who is priced ONLY in the ledger,
        # with nothing resembling a live board anywhere in this test,
        # still resolves correctly.  This is the single strongest proof
        # the fix is not merely usually-agreeing with today's board.
        self._write("player:gone", "2026-07-16", 2500.0, observed_at="2026-07-16T12:00:00+00:00")
        asset = {
            "kind": "player",
            "playerId": "gone",
            "playerName": "Long Retired",
            "position": "RB",
        }
        t1 = datetime(2026, 7, 20, tzinfo=timezone.utc)
        resolve = build_asof_valuation([(asset, t1)], path=self.ledger)
        self.assertEqual(resolve(asset, t1), 2500.0)

    def test_batches_distinct_requests_through_one_ledger_call(self) -> None:
        from unittest import mock

        from src.history import asof as asof_module

        self._write("player:A", "2026-07-15", 1.0, observed_at="2026-07-15T12:00:00+00:00")
        self._write("player:B", "2026-07-16", 2.0, observed_at="2026-07-16T12:00:00+00:00")
        t = datetime(2026, 7, 20, tzinfo=timezone.utc)
        requests = [
            ({"kind": "player", "playerId": "A", "playerName": "A", "position": "WR"}, t),
            ({"kind": "player", "playerId": "A", "playerName": "A", "position": "WR"}, t),
            ({"kind": "player", "playerId": "B", "playerName": "B", "position": "WR"}, t),
        ]
        with mock.patch.object(
            asof_module, "batch_known_before", wraps=asof_module.batch_known_before
        ) as spy:
            build_asof_valuation(requests, path=self.ledger)
        self.assertEqual(spy.call_count, 1)
        # Deduplicated: only 2 distinct (key, instant) pairs, not 3.
        self.assertEqual(len(spy.call_args[0][0]), 2)

    def test_empty_requests_returns_a_working_resolver(self) -> None:
        resolve = build_asof_valuation([], path=self.ledger)
        asset = {"kind": "player", "playerId": "5859", "playerName": "X", "position": "WR"}
        self.assertIsNone(resolve(asset, datetime(2026, 7, 20, tzinfo=timezone.utc)))


if __name__ == "__main__":
    unittest.main()
