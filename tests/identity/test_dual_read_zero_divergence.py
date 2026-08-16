"""C1-ID-01 CI gate: the contract-join dual-read must show ZERO divergence.

Builds the real contract from the committed live corpus (the same
pattern ``tests/api/test_player_identity_regression.py`` uses) and
asserts the canonical engine's CSV-join transcription agreed with the
inline cascade on every single (row, source) decision.  This is the
zero-diff harness the P2 acceptance profile requires before any cutover,
running on every CI build rather than on request.

If this test EVER reports a divergence, do not relax it: either the
inline cascade changed without its transcription
(``src/identity/resolution.match_row_to_source_entry``) being updated —
which is precisely the second-owner drift C1-ID-01 exists to prevent —
or the transcription was edited unilaterally.  The two must move
together until the cutover retires the inline copy.
"""

from __future__ import annotations

import contextlib
import io
import json
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


class TestContractJoinDualReadZeroDivergence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        boards = sorted((REPO / "exports" / "latest").glob("dynasty_data_*.json"), reverse=True)
        if not boards:
            raise unittest.SkipTest("no committed live board to build from")
        from src.api.data_contract import build_api_data_contract

        raw = json.loads(boards[0].read_bytes())
        with contextlib.redirect_stdout(io.StringIO()):
            cls.contract = build_api_data_contract(raw)

    def test_tally_is_present_and_ran(self):
        tally = self.contract.get("identityDualRead")
        self.assertIsInstance(tally, dict, "contract build must stamp identityDualRead")
        self.assertGreater(
            tally["calls"],
            1000,
            "the dual-read compared suspiciously few join decisions — "
            "did the comparison get short-circuited?",
        )

    def test_zero_divergence(self):
        tally = self.contract["identityDualRead"]
        self.assertEqual(
            tally["v1Diverge"],
            0,
            "legacy CSV-join cascade and the canonical engine disagreed:\n"
            + json.dumps(tally.get("v1Examples", [])[:10], indent=1),
        )


if __name__ == "__main__":
    unittest.main()
