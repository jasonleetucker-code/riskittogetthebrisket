"""Team-code table parity: the scraper vs the canonical pool builder.

``src/pool/builder.py::pool_clean_name`` is labelled "(extracted from
Dynasty Scraper.py)" and its regex bodies are character-identical to
``Dynasty Scraper.py::clean_name``.  The DATA had drifted: the pool
carried its own ``_TEAM_CODES`` literal that was 7 entries behind the
scraper's (GBP, JAC, KCC, LVR, NEP, SFO, TBB), so ``"Caleb WilliamsJAC"``
cleaned to ``"Caleb Williams"`` in the scraper and stayed
``"Caleb WilliamsJAC"`` in the pool.

That divergence was latent — the scraper pre-cleans every Sleeper
roster name (``Dynasty Scraper.py`` builds ``SLEEPER_ROSTER_DATA
["positions"]`` from ``clean_name(full)``) and hands the pool KTC /
IDPTradeCalc maps it has already run through the same function, so the
pool never saw a raw glued name in the live path.  It was one new
caller away from mattering.

Fix: ``src/utils/name_clean.py::NFL_TEAM_CODES`` is now the single
definition and ``src/pool/builder.py`` imports it.  The scraper keeps
its own literal (it is the production scraper and is deliberately not
edited here), so this test is the drift guard: it parses that literal
out of the file as text and asserts the two sets are equal.

Measured before the change (2026-07-29): adopting the scraper's full
table changes the cleaned form of ZERO strings across every real
payload in the repo — ``exports/latest/dynasty_data_2026-07-29.json``,
``data/legacy_data_2026-03-22.json``, ``data/sleeper_last_good.json``
and ``exports/latest/site_raw/*.json``, 3,492 distinct strings.
"""

from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

from src.utils.name_clean import NFL_TEAM_CODES

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRAPER_PATH = REPO_ROOT / "Dynasty Scraper.py"

_LITERAL_RE = re.compile(r"^_TEAM_CODES\s*=\s*\{(.*?)\n\}", re.S | re.M)


def _scraper_team_codes() -> set[str]:
    """Extract the scraper's ``_TEAM_CODES`` set literal as text.

    Deliberately narrow: read the file as text, locate the top-level
    assignment, and ``ast.literal_eval`` just that literal.  The scraper
    module is never imported — importing it executes the whole thing.
    """
    if not SCRAPER_PATH.exists():
        raise FileNotFoundError(f"scraper not found: {SCRAPER_PATH}")
    text = SCRAPER_PATH.read_text(encoding="utf-8")
    match = _LITERAL_RE.search(text)
    if not match:
        raise AssertionError(
            "could not locate a top-level `_TEAM_CODES = {...}` literal in "
            "Dynasty Scraper.py — if it moved or changed shape, update this "
            "parser rather than deleting the test"
        )
    return set(ast.literal_eval("{" + match.group(1) + "}"))


class TestTeamCodeParity(unittest.TestCase):
    def test_scraper_and_shared_table_agree(self):
        scraper = _scraper_team_codes()
        shared = set(NFL_TEAM_CODES)
        self.assertEqual(
            scraper,
            shared,
            "Dynasty Scraper.py::_TEAM_CODES and "
            "src/utils/name_clean.py::NFL_TEAM_CODES have drifted.\n"
            f"  only in scraper: {sorted(scraper - shared)}\n"
            f"  only in shared:  {sorted(shared - scraper)}\n"
            "Update NFL_TEAM_CODES to match; src/pool/builder.py reads it "
            "and must clean names exactly as the scraper does.",
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

    def test_glued_team_code_is_stripped_by_the_pool(self):
        from src.pool.builder import pool_clean_name

        # One code from each half of the previously-drifted set.
        self.assertEqual(pool_clean_name("Caleb WilliamsJAC"), "Caleb Williams")
        self.assertEqual(pool_clean_name("Caleb WilliamsJAX"), "Caleb Williams")
        self.assertEqual(pool_clean_name("Jordan LoveGBP"), "Jordan Love")
        self.assertEqual(pool_clean_name("Jordan LoveGB"), "Jordan Love")

    def test_short_stems_are_left_alone(self):
        """The >3-character stem guard is what keeps this from eating
        real names; assert it rather than trusting it."""
        from src.pool.builder import pool_clean_name

        # Stem "Ali" is 3 characters, so the trailing code is NOT stripped.
        self.assertEqual(pool_clean_name("AliNE"), "AliNE")


if __name__ == "__main__":
    unittest.main()
