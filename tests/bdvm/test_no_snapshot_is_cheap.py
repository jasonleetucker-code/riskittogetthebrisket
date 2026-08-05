"""Refusing to answer must not cost more than answering.

With no projection snapshot, `run_valuation` returns
`status="no_projection_snapshot"` before it reads actuals, player context or
the schedule. `get_bdvm_values` fetched all three first anyway.

The nflverse weekly pull behind `_actuals_for` measured **47,994 ms** on
GET /api/bdvm/roster — 48 seconds to produce a 310-byte "I have no data"
response, every one of those bytes already determined before the fetch
started. Audit finding W26-F004. Measured after the fix: 0.57 s cold,
0.02 s warm, byte-identical payload.

These tests assert the *absence of work*, because that is the whole defect —
the output was always correct and always expensive.
"""

from __future__ import annotations

import unittest
from unittest import mock

from src.api import bdvm_api


class TestNoSnapshotSkipsExpensiveInputs(unittest.TestCase):
    """No snapshot -> none of the three costly inputs are gathered."""

    def _run(self, snapshot_path):
        contract = {"generatedAt": "2026-08-05T00:00:00Z", "sleeper": {}}
        with (
            mock.patch.object(bdvm_api, "latest_snapshot_path", return_value=snapshot_path),
            mock.patch.object(bdvm_api, "_actuals_for", return_value=(None, {})) as actuals,
            mock.patch.object(bdvm_api, "_context_for", return_value=None) as context,
            mock.patch.object(bdvm_api, "_schedule_for", return_value=None) as schedule,
            mock.patch.object(
                bdvm_api, "run_valuation", return_value={"status": "no_projection_snapshot"}
            ),
            mock.patch.object(bdvm_api, "_registry_settings_for", return_value=({}, False, "p")),
        ):
            bdvm_api._values_cache.clear()
            out = bdvm_api.get_bdvm_values(contract, "dynasty_main")
        return out, actuals, context, schedule

    def test_actuals_are_not_fetched(self):
        _out, actuals, _c, _s = self._run(None)
        actuals.assert_not_called()

    def test_player_context_is_not_built(self):
        _out, _a, context, _s = self._run(None)
        context.assert_not_called()

    def test_schedule_is_not_loaded(self):
        _out, _a, _c, schedule = self._run(None)
        schedule.assert_not_called()

    def test_the_refusal_still_comes_from_run_valuation(self):
        """One definition of the message, not a second copy in the API layer.

        Short-circuiting with a locally-built payload would have been the
        obvious fix and would have forked the refusal text.
        """
        out, _a, _c, _s = self._run(None)
        self.assertEqual(out["status"], "no_projection_snapshot")

    def test_with_a_snapshot_the_inputs_are_still_gathered(self):
        """The guard must not disable the real path."""
        _out, actuals, context, schedule = self._run("/tmp/some-snapshot.json")
        actuals.assert_called_once()
        context.assert_called_once()
        schedule.assert_called_once()


if __name__ == "__main__":
    unittest.main()
