"""Regression tests for ``sourceNativeValues`` — the parallel per-player
map preserving rank-signal sources' vendor-native value column.

Roadmap item 7 ("keep ranking and value as separate data points"): the
rank branch of ``_parse_source_csv_cached`` historically DROPPED the
vendor value column entirely, while registry comments claimed it was
"still loaded into canonicalSiteValues".  These tests pin the corrected
behaviour:

* the rank branch reads the value column into the parsed tuple's
  ``nativeValue`` slot (``canonicalSiteValues`` keeps the synthetic
  rank encoding — the ordering machinery is untouched),
* the value branch stamps ``None`` (its canonicalSiteValues slot IS
  the native number),
* the trust mirror copies ``sourceNativeValues`` onto the legacy dict
  so the default ``view=app`` payload carries it.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from src.api.data_contract import (
    _RANK_TO_SYNTHETIC_VALUE_OFFSET,
    _TRUST_MIRROR_FIELDS,
    _parse_source_csv_cached,
)


class TestRankBranchPreservesNativeValue(unittest.TestCase):
    def _parse(self, csv_text: str, signal: str):
        with TemporaryDirectory() as td:
            p = Path(td) / "src.csv"
            p.write_text(csv_text, encoding="utf-8")
            lookup, err = _parse_source_csv_cached(p, "testSource", signal, Path("src.csv"))
        self.assertIsNone(err)
        return lookup

    def test_rank_signal_keeps_vendor_value_as_native(self) -> None:
        lookup = self._parse("name,value,rank\nJosh Allen,9891.5,1\n", "rank")
        entries = next(iter(lookup.values()))
        (name, synthetic, rank_val, native, sid) = entries[0]
        self.assertEqual(name, "Josh Allen")
        self.assertEqual(rank_val, 1.0)
        self.assertEqual(synthetic, _RANK_TO_SYNTHETIC_VALUE_OFFSET * 100 - 100)
        self.assertEqual(native, 9891.5)
        self.assertIsNone(sid)

    def test_rank_signal_without_value_column_is_none(self) -> None:
        lookup = self._parse("name,rank\nJosh Allen,1\n", "rank")
        (_, _, _, native, _) = next(iter(lookup.values()))[0]
        self.assertIsNone(native)

    def test_rank_signal_nonpositive_value_is_none(self) -> None:
        lookup = self._parse("name,value,rank\nJosh Allen,0,1\n", "rank")
        (_, _, _, native, _) = next(iter(lookup.values()))[0]
        self.assertIsNone(native)

    def test_rank_signal_reads_sleeper_id_column(self) -> None:
        """PFK-style CSVs carry a sleeper_id column for ID-grade
        identity (survives vendor/Sleeper name-spelling drift like
        Kenneth vs Kenny Gainwell)."""
        lookup = self._parse("name,value,rank,sleeper_id\nKenneth Gainwell,2778,110,7567\n", "rank")
        (name, _, _, native, sid) = next(iter(lookup.values()))[0]
        self.assertEqual(name, "Kenneth Gainwell")
        self.assertEqual(native, 2778.0)
        self.assertEqual(sid, "7567")

    def test_value_signal_native_slot_is_none(self) -> None:
        """Value-signal sources' canonicalSiteValues IS the native
        number — no duplicate stamp."""
        lookup = self._parse("name,value,rank\nJosh Allen,9000,1\n", "value")
        (name, value, orig_rank, native, sid) = next(iter(lookup.values()))[0]
        self.assertEqual(value, 9000)
        self.assertEqual(orig_rank, 1.0)
        self.assertIsNone(native)
        self.assertIsNone(sid)


class TestNativeValuesSurviveViewApp(unittest.TestCase):
    def test_trust_mirror_includes_source_native_values(self) -> None:
        """view=app strips playersArray; without the legacy mirror the
        map would silently vanish from the main runtime payload (the
        effectiveSourceRanks lesson from PR #530)."""
        self.assertIn("sourceNativeValues", _TRUST_MIRROR_FIELDS)


if __name__ == "__main__":
    unittest.main()
