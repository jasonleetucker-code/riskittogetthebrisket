"""Team-code table ownership: one definition, every cleaner imports it.

History, in two stages:

* 2026-07-29 — ``src/pool/builder.py`` carried its own ``_TEAM_CODES``
  literal that was 7 entries behind the scraper's (GBP, JAC, KCC, LVR,
  NEP, SFO, TBB), so ``"Caleb WilliamsJAC"`` cleaned differently in the
  two "identical" cleaners.  Fix: ``name_clean.NFL_TEAM_CODES`` became
  the single definition, the pool imported it, and this test regex-
  extracted the scraper's remaining literal as text to pin equality.

* C1-ID-01 — ``Dynasty Scraper.py::clean_name`` itself moved verbatim to
  ``src/identity/name_primitives.py`` (the canonical identity owner) and
  the scraper's literal was DELETED along with it.  The text-extraction
  tripwire in the previous version of this test fired exactly as
  designed — the literal moved, and the mover (this change) updated the
  guard to pin the new structure instead of the old text.

What this test now asserts: there is ONE team-code table,
``src/utils/name_clean.py::NFL_TEAM_CODES``, and every clean-name
implementation — the identity owner's ``clean_name`` and the pool's
``pool_clean_name`` — reads that object, not a copy.  The scraper no
longer defines either the table or the cleaner; it imports both from
``src/identity/name_primitives`` (asserted structurally below without
importing the scraper, which would execute it).
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from src.utils.name_clean import NFL_TEAM_CODES

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRAPER_PATH = REPO_ROOT / "Dynasty Scraper.py"


class TestTeamCodeOwnership(unittest.TestCase):
    def test_identity_owner_uses_the_shared_table(self):
        from src.identity import name_primitives

        self.assertIs(
            name_primitives._TEAM_CODES,
            NFL_TEAM_CODES,
            "src/identity/name_primitives.py no longer shares "
            "name_clean.NFL_TEAM_CODES — a second copy is exactly the drift "
            "this test exists to prevent",
        )

    def test_pool_builder_uses_the_shared_table(self):
        """The pool must not re-introduce a private copy."""
        from src.pool import builder

        self.assertIs(
            builder._TEAM_CODES,
            NFL_TEAM_CODES,
            "src/pool/builder.py no longer shares name_clean.NFL_TEAM_CODES — "
            "a second copy is exactly the drift this test exists to prevent",
        )

    def test_scraper_no_longer_carries_a_private_literal(self):
        """The scraper must stay an adapter: no resurrected ``_TEAM_CODES``
        literal and no local ``def clean_name`` — it imports both from the
        identity owner.  Text assertions on purpose: importing the scraper
        executes it."""
        text = SCRAPER_PATH.read_text(encoding="utf-8")
        self.assertIsNone(
            re.search(r"^_TEAM_CODES\s*=\s*\{", text, re.M),
            "Dynasty Scraper.py has grown a private _TEAM_CODES literal again — "
            "the table's one owner is src/utils/name_clean.py::NFL_TEAM_CODES",
        )
        self.assertIsNone(
            re.search(r"^def clean_name\(", text, re.M),
            "Dynasty Scraper.py has grown a private clean_name again — the "
            "canonical owner is src/identity/name_primitives.py::clean_name",
        )
        self.assertIn(
            "from src.identity.name_primitives import",
            text,
            "the scraper must import its name primitives from the identity owner",
        )

    def test_glued_team_code_is_stripped_by_the_pool(self):
        from src.pool.builder import pool_clean_name

        # One code from each half of the previously-drifted set.
        self.assertEqual(pool_clean_name("Caleb WilliamsJAC"), "Caleb Williams")
        self.assertEqual(pool_clean_name("Caleb WilliamsJAX"), "Caleb Williams")
        self.assertEqual(pool_clean_name("Jordan LoveGBP"), "Jordan Love")
        self.assertEqual(pool_clean_name("Jordan LoveGB"), "Jordan Love")

    def test_glued_team_code_is_stripped_by_the_identity_owner(self):
        from src.identity.name_primitives import clean_name

        self.assertEqual(clean_name("Caleb WilliamsJAC"), "Caleb Williams")
        self.assertEqual(clean_name("Jordan LoveGBP"), "Jordan Love")

    def test_short_stems_are_left_alone(self):
        """The >3-character stem guard is what keeps this from eating
        real names; assert it rather than trusting it."""
        from src.identity.name_primitives import clean_name
        from src.pool.builder import pool_clean_name

        # Stem "Ali" is 3 characters, so the trailing code is NOT stripped.
        self.assertEqual(pool_clean_name("AliNE"), "AliNE")
        self.assertEqual(clean_name("AliNE"), "AliNE")


if __name__ == "__main__":
    unittest.main()
