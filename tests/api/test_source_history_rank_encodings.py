"""Rank encodings must never be charted as values.

WHY THIS EXISTS
===============
``source_history.py``'s own docstring promises the series it writes:

    Every source value is on the normalized 1-9999 scale

Its ``canonicalSiteValues`` fallback broke that promise.  On a modern
contract, a rank-signal source's slot holds a SYNTHETIC RANK ENCODING
(``999900 - rank*100``) — ``rank_signal_source_keys()`` says so in as
many words, and ``src/trade/suggestions.py`` already skips those keys
for exactly this reason after the same confusion produced two real
bugs (PR #530). This module never got the same treatment.

Measured on the pinned 2026-07-30 contract, through the live
``_extract_player_entry`` path:

    encodings in canonicalSiteValues  5,119
    ...of those, reaching this series  452   on 169 of 1,093 rows
    total values written             7,187 -> 6,735 after the skip

Worst case charted **995,420 beside a blended 1,799** on a SHARED Y
axis — a 553x spike that flattens every other series on that player's
chart to a line along the bottom. And the read path derives a blended
value from the MEDIAN of per-source values when no blend was
persisted, so a single encoding drags the blended line too.

WHAT COULD DISAGREE WITH IT, BEFORE
===================================
Nothing. No test asserted a scale bound on anything this module writes,
and the frontend charts whatever arrives.

WHY NOTHING IS LOST
===================
The rank is already carried in the separate ``sourceRanks`` channel for
**424 of the 452**. The remaining 28 are picks whose encoding decodes to
a FRACTIONAL rank (995420 -> 44.8) — an interpolated bookkeeping number
that was never a rank either, so recovering it would invent precision
rather than restore information.

WHY THE FILTER IS BOTH KEY-BASED AND SCALE-BASED, ON BOTH PATHS
===============================================================
Neither half is sound alone:

* **Key alone deletes real data.** A LEGACY export predates the
  encoding and carries genuine 0-9999 numbers under these same keys,
  which ``backfill_from_exports`` ranks to build per-source rank
  history; and on the read path, 15 of the 17 rank-signal sources have
  legitimate ``valueContribution`` history written by the normal path.
  This is not hypothetical — the first version of this fix was
  key-only and broke
  ``test_backfill_derives_ranks_for_legacy_dict_export``. That
  regression is pinned here too, so the same mistake fails inside this
  module rather than somewhere across the suite.
* **Scale alone** is a magnitude heuristic that keeps passing while
  remaining wrong in principle, and would fire on a value-signal
  source that legitimately published above the scale.

Together they are exact on real data: rank-signal keys carrying an
in-scale value number **0**, value-signal keys carrying an off-scale
one number **0**, and an encoding can only fall under 9,999 at rank
>= 9,899 when the deepest rank any source publishes is **903**.

NOT ``livedata``-marked: pure logic over synthetic rows, must block.
"""

from __future__ import annotations

import unittest

from src.api import source_history as sh
from src.api.data_contract import rank_signal_source_keys


def _encode(rank: int) -> int:
    """The synthetic encoding, written the way the pipeline writes it."""
    return 999900 - rank * 100


class TestThePremiseHolds(unittest.TestCase):
    """Non-vacuity: without these, every assertion below could pass
    against an empty key set or a renamed registry field."""

    def test_the_registry_still_reports_rank_signal_sources(self) -> None:
        keys = rank_signal_source_keys()
        self.assertGreater(len(keys), 5)
        self.assertIn("dlfSf", keys)

    def test_the_module_resolves_the_same_set(self) -> None:
        sh._rank_signal_keys.__dict__.pop("_cached", None)
        self.assertEqual(sh._rank_signal_keys(), frozenset(rank_signal_source_keys()))

    def test_a_value_signal_source_is_not_in_that_set(self) -> None:
        """The filter must be surgical. ``ktcSfTep`` publishes a real
        0-9999 board and must keep flowing."""
        self.assertNotIn("ktcSfTep", rank_signal_source_keys())


class TestWriteTimeSkip(unittest.TestCase):
    def _row(self, canonical: dict) -> dict:
        # No ``sourceRankMeta`` -> the canonicalSiteValues fallback fires,
        # which is the branch that leaked.
        return {
            "displayName": "Test Player",
            "position": "WR",
            "rankDerivedValue": 5000,
            "canonicalConsensusRank": 40,
            "canonicalSiteValues": canonical,
        }

    def test_a_rank_encoding_is_not_written_as_a_value(self) -> None:
        entry = sh._extract_player_entry(self._row({"dlfSf": _encode(12)}))
        self.assertNotIn(
            "dlfSf",
            (entry or {}).get("sources") or {},
            msg=(
                "a synthetic rank encoding (999900 - rank*100) was written into a "
                "series documented as 'the normalized 1-9999 scale'. On the live "
                "contract this charted 995,420 next to a blended 1,799 on a shared "
                "Y axis."
            ),
        )

    def test_a_value_signal_source_still_flows_through_the_same_branch(self) -> None:
        """The asymmetry is the point — this is not a blanket mute of
        the fallback."""
        entry = sh._extract_player_entry(self._row({"idpTradeCalc": 6200}))
        self.assertEqual((entry or {}).get("sources", {}).get("idpTradeCalc"), 6200)

    def test_a_legacy_export_keeps_its_genuine_rank_signal_values(self) -> None:
        """The half a key-ONLY skip destroys, and it is not hypothetical
        — the first version of this fix was key-only and broke
        ``test_backfill_derives_ranks_for_legacy_dict_export``.

        Legacy exports predate the synthetic encoding and carry real
        0-9999 numbers under these same keys.
        ``backfill_from_exports`` derives per-source RANK history by
        ranking players on those values, so dropping them silently stops
        the chart from ever gaining rank lines for historical dates.
        """
        entry = sh._extract_player_entry(self._row({"dlfSf": 9000}))
        self.assertEqual(
            (entry or {}).get("sources", {}).get("dlfSf"),
            9000,
            msg=(
                "an in-scale legacy value was dropped because its source is "
                "rank-signal. The skip must require BOTH the key and an off-scale "
                "magnitude — a rank encoding cannot fall below 9,999 unless the "
                "rank exceeds 9,899, and the deepest rank any source publishes "
                "is 903."
            ),
        )

    def test_an_encoding_cannot_masquerade_as_an_in_scale_value(self) -> None:
        """Why the scale half of the test is safe: the encoding's own
        arithmetic puts it out of reach of the legitimate range for any
        rank a source could plausibly publish.

        Asserted rather than assumed, because the whole filter rests on
        it.
        """
        deepest_plausible_rank = 2000  # ~2x the deepest observed (903)
        self.assertGreater(_encode(deepest_plausible_rank), sh._MAX_NORMALIZED_VALUE)
        self.assertGreater((999900 - sh._MAX_NORMALIZED_VALUE) / 100, deepest_plausible_rank)

    def test_nothing_written_by_the_fallback_exceeds_the_scale(self) -> None:
        canonical = {k: _encode(i + 1) for i, k in enumerate(sorted(rank_signal_source_keys()))}
        canonical["idpTradeCalc"] = 6200
        entry = sh._extract_player_entry(self._row(canonical))
        offenders = {
            k: v
            for k, v in ((entry or {}).get("sources") or {}).items()
            if isinstance(v, (int, float)) and v > sh._MAX_NORMALIZED_VALUE
        }
        self.assertEqual(offenders, {})

    def test_the_normal_meta_path_is_untouched(self) -> None:
        """``valueContribution`` for a rank-signal source IS a real
        1-9999 value and must keep being recorded — the skip applies to
        the canonicalSiteValues fallback only."""
        entry = sh._extract_player_entry(
            {
                "displayName": "Test Player",
                "position": "WR",
                "rankDerivedValue": 5000,
                "canonicalConsensusRank": 40,
                "sourceRankMeta": {"dlfSf": {"valueContribution": 5100}},
                "canonicalSiteValues": {"dlfSf": _encode(12)},
            }
        )
        self.assertEqual((entry or {}).get("sources", {}).get("dlfSf"), 5100)


class TestReadTimeMask(unittest.TestCase):
    """Historical snapshots on disk already contain the encodings; the
    JSONL is not rewritten, so the chart has to mask them."""

    def _history(self, tmpdir, sources: dict, blended=None) -> dict:
        import json
        from pathlib import Path

        path = Path(tmpdir) / "hist.jsonl"
        line = {
            "date": "2026-07-30",
            "players": {
                "test player::offense": {
                    "blended": blended,
                    "blendedRank": 40,
                    "sources": sources,
                    "sourceRanks": {},
                }
            },
        }
        path.write_text(json.dumps(line) + "\n")
        return sh.load_player_history("Test Player", path=path, days=400)

    def test_a_stored_encoding_is_masked(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            out = self._history(td, {"dlfSf": _encode(12), "idpTradeCalc": 6200}, blended=5000)
            keys = set(out.get("sources") or {})
            self.assertNotIn("dlfSf", keys)
            self.assertIn("idpTradeCalc", keys)

    def test_an_in_scale_value_from_a_rank_signal_source_survives(self) -> None:
        """The half a purely key-based mask would have destroyed: 15 of
        the 17 rank-signal sources write legitimate ``valueContribution``
        history through the normal path."""
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            out = self._history(td, {"dlfSf": 5100}, blended=5000)
            keys = set(out.get("sources") or {})
            self.assertIn(
                "dlfSf",
                keys,
                msg=(
                    "a legitimate 1-9999 valueContribution was masked because its "
                    "source is rank-signal. The mask must require BOTH the key and "
                    "the off-scale magnitude — key alone deletes most of the chart."
                ),
            )

    def test_the_derived_blend_is_not_dragged_by_an_encoding(self) -> None:
        """The second, quieter consequence: with no persisted blend the
        read path takes the MEDIAN of per-source values.

        Deliberately TWO sources, not three. With three, the median is a
        middle element and shrugs off a single outlier — this assertion
        passed with the mask removed entirely, i.e. it was vacuous.
        Caught by running that mutation. With an even count the median
        averages the two, so the encoding actually moves the line:
        without the mask the derived blend is 502,450 rather than 6,100.
        """
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            out = self._history(
                td,
                {"dlfSf": _encode(12), "idpTradeCalc": 6200},
                blended=None,
            )
            points = [p for p in (out.get("blended") or []) if p.get("value") is not None]
            self.assertTrue(points, "no blended point produced")
            for p in points:
                self.assertLessEqual(
                    p["value"],
                    sh._MAX_NORMALIZED_VALUE,
                    msg=(
                        f"derived blend {p['value']} is off the 1-9999 scale — a "
                        "six-digit rank encoding entered the median."
                    ),
                )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
