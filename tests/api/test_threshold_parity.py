"""``config/thresholds.json`` is the source; the JS mirror must match it.

WHY THIS EXISTS
---------------
The thresholds that gate every decision surface lived in two places —
``frontend/lib/thresholds.js`` and, for the confidence cutoffs,
``src/api/data_contract.py`` — kept in step by a **comment** in the JS
header listing the Python constant names and their values by hand.

That is the same failure mode ``test_source_registry_parity.py`` was
written for, and the registry is the one parity mechanism in this repo
that demonstrably works. So this test is deliberately modelled on it,
down to reusing its narrow-parse philosophy: read the JS as text, pull
out the exported constants, fail loudly on anything unusual rather than
quietly skipping it.

Python cannot drift at all — ``src/api/thresholds.py`` *loads* the JSON.
This test covers the remaining half.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from src.api.thresholds import CONFIG_PATH, threshold_entries

REPO_ROOT = Path(__file__).resolve().parents[2]
JS_PATH = REPO_ROOT / "frontend" / "lib" / "thresholds.js"

_EXPORT = re.compile(
    r"^export const ([A-Z][A-Z0-9_]*)\s*=\s*(-?\d+(?:\.\d+)?)\s*;",
    re.MULTILINE,
)


def _parse_js_constants() -> dict[str, float]:
    if not JS_PATH.exists():
        raise FileNotFoundError(f"frontend threshold mirror not found: {JS_PATH}")
    text = JS_PATH.read_text(encoding="utf-8")
    out: dict[str, float] = {}
    for name, raw in _EXPORT.findall(text):
        out[name] = float(raw) if "." in raw else int(raw)
    if not out:
        raise ValueError(f"no `export const NAME = <number>;` declarations found in {JS_PATH}")
    return out


class TestThresholdParity(unittest.TestCase):
    def setUp(self) -> None:
        self.maxDiff = None
        self.json_entries = threshold_entries()
        self.js = _parse_js_constants()

    def test_every_json_threshold_is_mirrored_in_js(self) -> None:
        missing = sorted(set(self.json_entries) - set(self.js))
        self.assertEqual(
            missing,
            [],
            f"declared in {CONFIG_PATH.name} but not exported from thresholds.js: {missing}",
        )

    def test_no_js_constant_is_invented_locally(self) -> None:
        """A number the JSON has never heard of is an unreviewed threshold.

        This is the direction that matters most: adding a constant to
        the JS is easy and invisible, and it is how the four
        market-gap thresholds ended up disagreeing with each other in
        the first place.
        """
        extra = sorted(set(self.js) - set(self.json_entries))
        self.assertEqual(
            extra,
            [],
            f"exported from thresholds.js but absent from {CONFIG_PATH.name}: {extra}. "
            "Add it to the JSON with a derivation, or delete it.",
        )

    def test_values_match(self) -> None:
        for name, entry in sorted(self.json_entries.items()):
            with self.subTest(threshold=name):
                self.assertEqual(
                    self.js.get(name),
                    entry["value"],
                    f"{name}: thresholds.js has {self.js.get(name)}, "
                    f"{CONFIG_PATH.name} has {entry['value']}",
                )

    def test_every_threshold_records_how_it_was_derived(self) -> None:
        """An undocumented threshold is a number somebody invented.

        Four of these were re-derived in batch C4 when the market gap
        changed units; the point of the field is that the next person to
        touch one can see whether it rests on a measurement or on a
        round number that felt right.
        """
        for name, entry in sorted(self.json_entries.items()):
            with self.subTest(threshold=name):
                self.assertTrue(
                    (entry.get("derivedFrom") or "").strip(),
                    f"{name} has no derivedFrom",
                )
                self.assertTrue((entry.get("unit") or "").strip(), f"{name} has no unit")
                self.assertIsInstance(entry.get("value"), (int, float))

    def test_the_hand_written_sync_comment_is_gone(self) -> None:
        """The mechanism this test replaces must not survive alongside it.

        Two sync mechanisms is worse than one: the comment cannot fail a
        build, so whichever one is wrong, the comment is the one people
        will believe.
        """
        text = JS_PATH.read_text(encoding="utf-8")
        self.assertNotIn(
            "_CONFIDENCE_SPREAD_HIGH",
            text,
            "thresholds.js still carries the hand-written 'mirror these Python "
            "constants' comment that config/thresholds.json replaced",
        )

    def test_market_gap_thresholds_are_in_rank_space(self) -> None:
        """Unit guard.

        The gap magnitude changed from ordinal ranks to rank-space
        per-mille in C4. A threshold left in the old unit would still be
        a plausible number and would silently mis-gate, so the unit is
        asserted rather than assumed.
        """
        for name in (
            "MARKET_GAP_MIN_MAGNITUDE",
            "MARKET_PREMIUM_MAGNITUDE",
            "PREMIUM_SUMMARY_MAGNITUDE",
            "MIN_EDGE_MAGNITUDE",
        ):
            with self.subTest(threshold=name):
                self.assertEqual(self.json_entries[name]["unit"], "rankSpacePerMille")


if __name__ == "__main__":
    unittest.main()
