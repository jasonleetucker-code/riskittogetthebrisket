"""C1-ID-02: the frontend's pick-label lookup grammar cannot drift
silently from the canonical owner.

``frontend/lib/trade-logic.js`` still parses pick display labels
client-side (``parsePickToken`` / ``buildPickLookupCandidates``) — a
deliberately DEFERRED migration (design record §4: moving it onto
stamped ``assetId`` fields needs C1-U6's generic-grade board rows to
avoid re-inventing tier-centre conventions client-side).  Until then,
this test holds the two languages in lockstep the same way
``test_source_registry_parity.py`` does for the source registry: by
parsing the JS source and diffing the load-bearing constants against
the Python side.

If this test fails you changed one side of a cross-language grammar —
change both, or finish the migration.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TRADE_LOGIC = REPO / "frontend" / "lib" / "trade-logic.js"


class TestTierCentreSlotsLockstep(unittest.TestCase):
    """The tier→centre-slot convention exists in exactly two places:
    the backend's alias builder (``data_contract.
    _suppress_generic_pick_tiers_when_slots_exist``) and the frontend's
    ``TIER_CENTRE_SLOT``.  They must agree or the same tier label
    resolves to different slot rows on the two surfaces."""

    def test_frontend_and_backend_centres_agree(self):
        js = TRADE_LOGIC.read_text(encoding="utf-8")
        m = re.search(
            r"TIER_CENTRE_SLOT\s*=\s*\{\s*early:\s*(\d+),\s*mid:\s*(\d+),\s*late:\s*(\d+)\s*\}",
            js,
        )
        self.assertIsNotNone(m, "TIER_CENTRE_SLOT literal not found in trade-logic.js")
        js_centres = {
            "Early": int(m.group(1)),
            "Mid": int(m.group(2)),
            "Late": int(m.group(3)),
        }

        py = (REPO / "src" / "api" / "data_contract.py").read_text(encoding="utf-8")
        pm = re.search(
            r"tier_centre_slot\s*=\s*\{\"Early\":\s*(\d+),\s*\"Mid\":\s*(\d+),\s*\"Late\":\s*(\d+)\}",
            py,
        )
        self.assertIsNotNone(pm, "tier_centre_slot literal not found in data_contract.py")
        py_centres = {
            "Early": int(pm.group(1)),
            "Mid": int(pm.group(2)),
            "Late": int(pm.group(3)),
        }
        self.assertEqual(js_centres, py_centres)


class TestFrontendLabelRegexesStillMatchOwnerGrammar(unittest.TestCase):
    """``parsePickToken``'s two regex literals are pinned verbatim.

    They are known-compatible with every label the owner's formatters
    emit (slot form ``YYYY R.SS`` and the tier/round-suffix families).
    A change to either literal must be made consciously against
    ``src/identity/picks.py``'s grammar — this pin forces that look.
    """

    def test_slot_and_label_regex_literals_are_the_measured_ones(self):
        js = TRADE_LOGIC.read_text(encoding="utf-8")
        self.assertIn(r"/^(\d{4})\s+(\d)\.(\d{2})/", js)
        self.assertIn(
            r"/^(\d{4})\s+(early|mid|late)?\s*(1st|2nd|3rd|4th|5th|6th)/i", js
        )

    def test_every_owner_emitted_label_family_is_parseable_by_the_js_grammar(self):
        """Python-side simulation of the two JS regexes over the owner's
        actual formatter outputs — the lookup path must at least parse
        every label the backend can now emit."""
        from src.identity import picks as P

        js_slot = re.compile(r"^(\d{4})\s+(\d)\.(\d{2})")
        js_label = re.compile(
            r"^(\d{4})\s+(early|mid|late)?\s*(1st|2nd|3rd|4th|5th|6th)", re.I
        )
        emitted = []
        for season in (2026, 2027, 2028, 2029):
            for rnd in range(1, 7):
                for slot in (None, 1, 6, 12):
                    emitted.append(
                        P.format_pick_label_baked(
                            season=season,
                            round_num=rnd,
                            slot=slot,
                            current_year=2026,
                            league_size=12,
                        )
                    )
                    emitted.append(P.format_pick_label_overlay(str(season), rnd, slot))
        for label in emitted:
            self.assertTrue(
                js_slot.match(label) or js_label.match(label),
                f"owner-emitted label not parseable by frontend grammar: {label!r}",
            )


class TestKnownDivergenceIsStillPresentUntilTheMigration(unittest.TestCase):
    """Census §2.4: the frontend hardcodes 12-team tier boundaries
    (``slot <= 4`` early / ``<= 8`` mid) while the backend rule is
    league-size-aware.  The divergence is DEFERRED, not endorsed — this
    pin exists so removing it is a conscious act that also updates the
    design record's disposition table (and ideally replaces the
    client-side derivation with the stamped ``assetId`` path)."""

    def test_the_12_team_hardcode_is_still_there(self):
        js = TRADE_LOGIC.read_text(encoding="utf-8")
        self.assertIn('slot <= 4 ? "early" : slot <= 8 ? "mid" : "late"', js)


if __name__ == "__main__":
    unittest.main()
