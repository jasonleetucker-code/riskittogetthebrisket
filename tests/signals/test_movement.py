"""Movement-window tests for src.signals.movement (C6-SIG-02).

Mirrors the style of ``tests/history/test_temporal_ledger.py`` — a real
temp SQLite ledger, written through the canonical recorder
(``src.history.record.record_contract``), never a hand-built fixture
that bypasses the store's own invariants.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.history import record
from src.signals.movement import stamp_movement_windows

_PLAYER_ID = "9001"


def _row(*, value: int, rank: int, name: str = "Test Player") -> dict:
    return {
        "playerId": _PLAYER_ID,
        "canonicalName": name,
        "displayName": name,
        "position": "WR",
        "assetClass": "offense",
        "rankDerivedValue": value,
        "canonicalConsensusRank": rank,
    }


def _contract(rows: list[dict], date: str) -> dict:
    return {"playersArray": rows, "date": date, "scrapeTimestamp": f"{date}T11:00:00.000000"}


class TestMovementWindows(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.ledger = Path(self._td.name) / "ledger.sqlite"

    # ── 7. A ledger gap inside the window never fabricates a value ──────

    def test_gap_inside_window_is_unavailable_not_zero(self):
        # Only today's board is recorded — no observation exists 7 or 30
        # days back, so both windows must report unavailable/None, never
        # a delta computed against something that was never observed.
        record.record_contract(_contract([_row(value=5000, rank=50)], "2026-08-20"), path=self.ledger)

        rows = [_row(value=5000, rank=50)]
        stamp_movement_windows(rows, board_date="2026-08-20", ledger_path=self.ledger)

        windows = rows[0]["movementWindows"]
        for label in ("7d", "30d"):
            assert windows[label]["fidelity"] == "unavailable"
            assert windows[label]["deltaRank"] is None
            assert windows[label]["deltaValue"] is None
        # asOfDate echoes what was REQUESTED (informative: which date was
        # checked) even though nothing was found there — distinct from a
        # bare None, which would say nothing was even asked.
        assert windows["7d"]["asOfDate"] == "2026-08-13"
        assert windows["30d"]["asOfDate"] == "2026-07-21"

    def test_prior_observation_produces_a_real_delta(self):
        record.record_contract(
            _contract([_row(value=4000, rank=80)], "2026-08-13"), path=self.ledger
        )
        record.record_contract(
            _contract([_row(value=5000, rank=50)], "2026-08-20"), path=self.ledger
        )

        rows = [_row(value=5000, rank=50)]
        stamp_movement_windows(rows, board_date="2026-08-20", ledger_path=self.ledger)

        seven_day = rows[0]["movementWindows"]["7d"]
        assert seven_day["fidelity"] in ("exact", "nearest-prior")
        # Positive = moved UP (lower rank number now), matching
        # _stamp_rank_changes's own sign convention: prior rank 80,
        # current rank 50 -> +30.
        assert seven_day["deltaRank"] == 30
        assert seven_day["deltaValue"] == 1000

    def test_windows_are_independent_7d_can_resolve_while_30d_cannot(self):
        record.record_contract(
            _contract([_row(value=4000, rank=80)], "2026-08-13"), path=self.ledger
        )
        record.record_contract(
            _contract([_row(value=5000, rank=50)], "2026-08-20"), path=self.ledger
        )

        rows = [_row(value=5000, rank=50)]
        stamp_movement_windows(rows, board_date="2026-08-20", ledger_path=self.ledger)

        assert rows[0]["movementWindows"]["7d"]["fidelity"] != "unavailable"
        assert rows[0]["movementWindows"]["30d"]["fidelity"] == "unavailable"

    def test_unkeyable_row_is_unavailable(self):
        # No playerId, no canonicalName/displayName, no position -> the
        # keys owner cannot classify it at all.
        rows = [{"rankDerivedValue": 100, "canonicalConsensusRank": 900}]
        stamp_movement_windows(rows, board_date="2026-08-20", ledger_path=self.ledger)
        assert rows[0]["movementWindows"]["7d"]["fidelity"] == "unavailable"

    def test_missing_ledger_file_degrades_to_unavailable_not_a_crash(self):
        nonexistent = Path(self._td.name) / "does_not_exist.sqlite"
        rows = [_row(value=5000, rank=50)]
        stamp_movement_windows(rows, board_date="2026-08-20", ledger_path=nonexistent)
        assert rows[0]["movementWindows"]["7d"]["fidelity"] == "unavailable"

    # ── 8. Structurally wired to the ledger, never rank_history.jsonl ───

    def test_does_not_read_rank_history_jsonl(self):
        """Patching the JSONL loader to raise must not affect this
        module at all -- it is wired to src.history.asof exclusively."""
        import src.api.rank_history as rank_history_module

        original = rank_history_module.load_history

        def _boom(*args, **kwargs):
            raise AssertionError("stamp_movement_windows must not read rank_history.jsonl")

        rank_history_module.load_history = _boom
        try:
            record.record_contract(
                _contract([_row(value=4000, rank=80)], "2026-08-13"), path=self.ledger
            )
            record.record_contract(
                _contract([_row(value=5000, rank=50)], "2026-08-20"), path=self.ledger
            )
            rows = [_row(value=5000, rank=50)]
            stamp_movement_windows(rows, board_date="2026-08-20", ledger_path=self.ledger)
            assert rows[0]["movementWindows"]["7d"]["deltaRank"] == 30
        finally:
            rank_history_module.load_history = original


if __name__ == "__main__":
    unittest.main()
