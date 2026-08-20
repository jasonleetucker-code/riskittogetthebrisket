"""V1-97 / C3-REPLAY-01 — integration coverage for the as-of grading
wiring in ``src/public_league/activity.py``.

``test_public_activity_asof_valuation.py`` pins the resolver
(``build_asof_valuation``) in isolation.  This file pins the layer
above it: ``_apply_trade_grades`` resolving per-side against a real
ledger, and ``build_section`` collecting every ``(asset, instant)``
pair across a WHOLE feed and calling its ``valuation_factory`` exactly
once (the batching the temporal ledger's I/O cost depends on).
"""

from __future__ import annotations

import functools
import tempfile
import unittest
from datetime import timezone
from pathlib import Path
from unittest import mock

from src.api.public_activity_valuation import build_asof_valuation
from src.history import store
from src.public_league import activity
from src.public_league.snapshot import ManagerRegistry, PublicLeagueSnapshot, SeasonSnapshot


def _epoch_ms(date_str: str) -> int:
    from datetime import datetime

    dt = datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _season(league_id: str, week: int, transactions: list[dict]) -> SeasonSnapshot:
    return SeasonSnapshot(
        season="2026",
        league_id=league_id,
        league={"status": "complete"},
        users=[],
        rosters=[],
        matchups_by_week={},
        transactions_by_week={week: transactions},
        drafts=[],
        draft_picks_by_draft={},
        traded_picks=[],
        winners_bracket=[],
        losers_bracket=[],
    )


def _snapshot(*seasons: SeasonSnapshot) -> PublicLeagueSnapshot:
    return PublicLeagueSnapshot(
        root_league_id=seasons[0].league_id if seasons else "L",
        generated_at="2026-08-20T00:00:00Z",
        seasons=list(seasons),
        managers=ManagerRegistry(),
    )


class _LedgerCase(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.ledger = Path(self._td.name) / "ledger.sqlite"
        store._reset_setup_cache_for_tests()
        self.factory = functools.partial(build_asof_valuation, path=self.ledger)

    def _write(self, asset_key, observed_date, value, *, observed_at):
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
                    "origin": "test",
                }
            ],
            path=self.ledger,
        )
        assert result["written"] == 1, result


class TwoTeamTradeGrading(_LedgerCase):
    def test_resolvable_trade_gets_a_real_grade_as_of_its_own_date(self) -> None:
        self._write("player:rb2", "2026-07-16", 8000.0, observed_at="2026-07-16T12:00:00+00:00")
        self._write("player:wr2", "2026-07-16", 2000.0, observed_at="2026-07-16T12:00:00+00:00")
        trade = {
            "transaction_id": "tx-1",
            "type": "trade",
            "status": "complete",
            "created": _epoch_ms("2026-07-20"),
            "roster_ids": [1, 2],
            "adds": {"rb2": 1, "wr2": 2},
            "drops": {"rb2": 2, "wr2": 1},
            "draft_picks": [],
        }
        snapshot = _snapshot(_season("L", 3, [trade]))
        section = activity.build_section(snapshot, valuation_factory=self.factory)
        feed_trade = section["feed"][0]
        for side in feed_trade["sides"]:
            self.assertIn("grade", side)
            self.assertNotEqual(side["grade"].get("available"), False)
            self.assertIsNotNone(side["grade"]["grade"])

    def test_appending_a_post_trade_observation_never_changes_the_grade(self) -> None:
        self._write("player:rb2", "2026-07-16", 8000.0, observed_at="2026-07-16T12:00:00+00:00")
        self._write("player:wr2", "2026-07-16", 2000.0, observed_at="2026-07-16T12:00:00+00:00")
        trade = {
            "transaction_id": "tx-1",
            "type": "trade",
            "status": "complete",
            "created": _epoch_ms("2026-07-20"),
            "roster_ids": [1, 2],
            "adds": {"rb2": 1, "wr2": 2},
            "drops": {"rb2": 2, "wr2": 1},
            "draft_picks": [],
        }
        snapshot = _snapshot(_season("L", 3, [trade]))
        before = activity.build_section(snapshot, valuation_factory=self.factory)
        before_grades = [s["grade"]["grade"] for s in before["feed"][0]["sides"]]

        # The board moves after the trade: a much larger post-trade value.
        self._write("player:rb2", "2026-08-10", 50000.0, observed_at="2026-08-10T12:00:00+00:00")
        after = activity.build_section(
            _snapshot(_season("L", 3, [trade])), valuation_factory=self.factory
        )
        after_grades = [s["grade"]["grade"] for s in after["feed"][0]["sides"]]
        self.assertEqual(before_grades, after_grades)

    def test_missing_evidence_produces_an_honest_unavailable_side(self) -> None:
        # rb2 has ledger coverage; wr2 has none at all -- the whole trade
        # predates any observation for wr2.
        self._write("player:rb2", "2026-07-16", 8000.0, observed_at="2026-07-16T12:00:00+00:00")
        trade = {
            "transaction_id": "tx-1",
            "type": "trade",
            "status": "complete",
            "created": _epoch_ms("2026-07-20"),
            "roster_ids": [1, 2],
            "adds": {"rb2": 1, "wr2": 2},
            "drops": {"rb2": 2, "wr2": 1},
            "draft_picks": [],
        }
        snapshot = _snapshot(_season("L", 3, [trade]))
        section = activity.build_section(snapshot, valuation_factory=self.factory)
        sides = section["feed"][0]["sides"]
        for side in sides:
            self.assertEqual(side["grade"]["available"], False)
            self.assertEqual(side["grade"]["grade"], None)
            self.assertEqual(side["grade"]["label"], "Insufficient historical evidence")

    def test_trade_with_no_parseable_instant_is_unavailable_on_every_side(self) -> None:
        self._write("player:rb2", "2026-07-16", 8000.0, observed_at="2026-07-16T12:00:00+00:00")
        self._write("player:wr2", "2026-07-16", 2000.0, observed_at="2026-07-16T12:00:00+00:00")
        trade = {
            "transaction_id": "tx-1",
            "type": "trade",
            "status": "complete",
            "created": 0,  # unparseable -> None instant
            "roster_ids": [1, 2],
            "adds": {"rb2": 1, "wr2": 2},
            "drops": {"rb2": 2, "wr2": 1},
            "draft_picks": [],
        }
        snapshot = _snapshot(_season("L", 3, [trade]))
        section = activity.build_section(snapshot, valuation_factory=self.factory)
        for side in section["feed"][0]["sides"]:
            self.assertEqual(side["grade"]["available"], False)
            self.assertEqual(side["grade"]["reason"], "invalid_trade_instant")

    def test_no_grades_at_all_when_no_factory_supplied(self) -> None:
        trade = {
            "transaction_id": "tx-1",
            "type": "trade",
            "status": "complete",
            "created": _epoch_ms("2026-07-20"),
            "roster_ids": [1, 2],
            "adds": {"rb2": 1, "wr2": 2},
            "drops": {"rb2": 2, "wr2": 1},
            "draft_picks": [],
        }
        snapshot = _snapshot(_season("L", 3, [trade]))
        section = activity.build_section(snapshot)
        for side in section["feed"][0]["sides"]:
            self.assertNotIn("grade", side)


class ThreeTeamTradeIndependence(_LedgerCase):
    def test_one_sides_missing_evidence_does_not_poison_another_side(self) -> None:
        # "small" and "big" have coverage; "mid" has none.
        self._write("player:small", "2026-07-16", 1000.0, observed_at="2026-07-16T12:00:00+00:00")
        self._write("player:big", "2026-07-16", 8000.0, observed_at="2026-07-16T12:00:00+00:00")
        trade = {
            "transaction_id": "tx-3way",
            "type": "trade",
            "status": "complete",
            "created": _epoch_ms("2026-07-20"),
            "roster_ids": [1, 2, 3],
            "adds": {"small": 3, "big": 2, "mid": 1},
            "drops": {"small": 2, "big": 1, "mid": 3},
            "draft_picks": [],
        }
        snapshot = _snapshot(_season("L", 3, [trade]))
        section = activity.build_section(snapshot, valuation_factory=self.factory)
        sides = section["feed"][0]["sides"]
        by_roster = {s["rosterId"]: s for s in sides}
        # adds: roster 3 <- small, roster 2 <- big, roster 1 <- mid (uncovered)
        # drops: roster 2 -> small, roster 1 -> big, roster 3 -> mid (uncovered)
        # Roster 1 RECEIVED the uncovered "mid" -> unresolved.
        self.assertEqual(by_roster[1]["grade"]["available"], False)
        # Roster 3 SENT the uncovered "mid" -> also unresolved.
        self.assertEqual(by_roster[3]["grade"]["available"], False)
        # Roster 2 never touches "mid" at all (received "big", sent
        # "small", both covered) -- grades cleanly, unaffected by the
        # other two sides' missing evidence in the SAME trade.
        self.assertNotIn("available", by_roster[2]["grade"])
        self.assertIsNotNone(by_roster[2]["grade"]["grade"])


class BatchingWiring(_LedgerCase):
    def test_valuation_factory_called_exactly_once_per_feed_build(self) -> None:
        self._write("player:rb2", "2026-07-16", 8000.0, observed_at="2026-07-16T12:00:00+00:00")
        self._write("player:wr2", "2026-07-16", 2000.0, observed_at="2026-07-16T12:00:00+00:00")
        self._write("player:wr3", "2026-07-15", 500.0, observed_at="2026-07-15T12:00:00+00:00")
        trade_a = {
            "transaction_id": "tx-a",
            "type": "trade",
            "status": "complete",
            "created": _epoch_ms("2026-07-20"),
            "roster_ids": [1, 2],
            "adds": {"rb2": 1, "wr2": 2},
            "drops": {"rb2": 2, "wr2": 1},
            "draft_picks": [],
        }
        trade_b = {
            "transaction_id": "tx-b",
            "type": "trade",
            "status": "complete",
            "created": _epoch_ms("2026-07-19"),
            "roster_ids": [1, 3],
            "adds": {"wr3": 1},
            "drops": {"wr3": 3},
            "draft_picks": [],
        }
        snapshot = _snapshot(_season("L", 3, [trade_a, trade_b]))
        spy_factory = mock.Mock(side_effect=self.factory)
        activity.build_section(snapshot, valuation_factory=spy_factory)
        self.assertEqual(spy_factory.call_count, 1)
        # The one call carries every asset from BOTH trades.
        requests = spy_factory.call_args[0][0]
        # trade_a: 2 sides x (1 received + 1 sent) = 4; trade_b: 2 sides
        # x 1 asset each (a one-directional 1-for-nothing swap) = 2.
        self.assertEqual(len(requests), 6)


if __name__ == "__main__":
    unittest.main()
