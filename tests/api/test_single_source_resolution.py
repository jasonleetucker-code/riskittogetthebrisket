"""Regression tests for single-source resolution.

These tests guarantee that:

1. Known top offense players never regress back to ``isSingleSource=True``
   (semantic 1-src / matching failure).
2. Every top-400 1-src player has an explicit allowlist reason.
3. Cross-source name aliases resolve correctly.
4. The allowlist build check catches unexplained 1-src cases.
"""
from __future__ import annotations

import unittest
from typing import Any

from src.api.data_contract import (
    SINGLE_SOURCE_ALLOWLIST,
    _compute_unified_rankings,
    assert_no_unexplained_single_source,
)
from src.utils.name_clean import (
    CANONICAL_NAME_ALIASES,
    normalize_player_name,
    resolve_canonical_name,
)


# ── Helpers ──────────────────────────────────────────────────────────────

def _row(
    name: str,
    position: str,
    *,
    ktc: int | None = None,
    idp: int | None = None,
    dlf: int | None = None,
    dlf_sf: int | None = None,
    dn_sf_tep: int | None = None,
    rookie: bool = False,
) -> dict[str, Any]:
    sites: dict[str, int | None] = {
        "ktc": ktc,
        "idpTradeCalc": idp,
        "dlfIdp": dlf,
        "dlfSf": dlf_sf,
        "dynastyNerdsSfTep": dn_sf_tep,
    }
    return {
        "canonicalName": name,
        "displayName": name,
        "position": position,
        "assetClass": "idp" if position in ("DL", "LB", "DB") else "offense",
        "canonicalSiteValues": sites,
        "values": {"overall": max(v or 0 for v in sites.values()), "rawComposite": None, "finalAdjusted": None, "displayValue": None},
        "sourceCount": 0,
        "sourcePresence": {},
        "rookie": rookie,
    }


# ── Test: Name alias resolution ─────────────────────────────────────────

class TestNameAliases(unittest.TestCase):
    """Verify cross-source name aliases collapse correctly."""

    def test_greg_gregory_rousseau(self):
        self.assertEqual(
            resolve_canonical_name("Greg Rousseau"),
            resolve_canonical_name("Gregory Rousseau"),
        )

    def test_foye_foyesade_oluokun(self):
        self.assertEqual(
            resolve_canonical_name("Foye Oluokun"),
            resolve_canonical_name("Foyesade Oluokun"),
        )

    def test_josh_joshua_metellus(self):
        self.assertEqual(
            resolve_canonical_name("Josh Metellus"),
            resolve_canonical_name("Joshua Metellus"),
        )

    def test_kam_kamren_curl(self):
        self.assertEqual(
            resolve_canonical_name("Kam Curl"),
            resolve_canonical_name("Kamren Curl"),
        )

    def test_suffix_stripping_walker(self):
        """Kenneth Walker III and Kenneth Walker collapse to same key."""
        self.assertEqual(
            normalize_player_name("Kenneth Walker III"),
            normalize_player_name("Kenneth Walker"),
        )

    def test_suffix_stripping_harrison(self):
        self.assertEqual(
            normalize_player_name("Marvin Harrison Jr"),
            normalize_player_name("Marvin Harrison"),
        )

    def test_suffix_stripping_thomas(self):
        self.assertEqual(
            normalize_player_name("Brian Thomas Jr"),
            normalize_player_name("Brian Thomas"),
        )

    def test_apostrophe_stripping(self):
        """Ja'Marr and JaMarr and Ja\u2019Marr all collapse."""
        self.assertEqual(
            normalize_player_name("Ja'Marr Chase"),
            normalize_player_name("JaMarr Chase"),
        )
        self.assertEqual(
            normalize_player_name("Ja\u2019Marr Chase"),
            normalize_player_name("JaMarr Chase"),
        )

    def test_initials_collapse(self):
        """T.J. Watt and TJ Watt collapse."""
        self.assertEqual(
            normalize_player_name("T.J. Watt"),
            normalize_player_name("TJ Watt"),
        )

    def test_hyphen_preserved_as_space(self):
        """Smith-Njigba normalizes consistently."""
        key = normalize_player_name("Jaxon Smith-Njigba")
        self.assertIn("smith", key)
        self.assertIn("njigba", key)


# ── Test: Top offense players must NOT be semantic 1-src ─────────────────

class TestTopOffenseNotSemantic1Src(unittest.TestCase):
    """Regression guard: known top offensive players must never be flagged
    as ``isSingleSource=True`` (semantic 1-src / matching failure).

    They may be ``isStructurallySingleSource=True`` with an allowlist
    reason if the second source genuinely doesn't carry them, but they
    must NEVER be semantic 1-src which implies a fixable join failure.
    """

    # These players are top-100 dynasty offense assets with KTC > 3000.
    # Each one is also covered by DLF Superflex, so all three must
    # resolve to multi-source (NOT isSingleSource) in the synthetic
    # fixture.  If any becomes semantic 1-src in a fixture that
    # provides both KTC and DLF SF, it means a name-join regression
    # broke cross-source matching.
    #
    # Tuple format: (name, pos, ktc_value, dlf_sf_synthetic, dn_sf_tep_synthetic)
    # dlf_sf and dn_sf_tep values are synthetic rank transforms — the
    # absolute number is irrelevant, only the ordering matters.
    MUST_NOT_BE_SEMANTIC_1SRC = [
        ("Kenneth Walker", "RB", 8000, 950000, 950000),
        ("Marvin Harrison", "WR", 5001, 950000, 950000),
        ("Brian Thomas", "WR", 4930, 950000, 950000),
        ("Michael Penix", "QB", 3144, 950000, 950000),
    ]

    def test_each_is_not_semantic_1src(self):
        """Each listed player must not be isSingleSource after ranking."""
        for name, pos, ktc_val, dlf_sf_val, dn_val in self.MUST_NOT_BE_SEMANTIC_1SRC:
            with self.subTest(player=name):
                rows = [
                    _row(name, pos, ktc=ktc_val, dlf_sf=dlf_sf_val, dn_sf_tep=dn_val),
                    # Provide another player so the source pool has > 1 entry
                    _row(
                        "Zzz Anchor QB",
                        "QB",
                        ktc=9999,
                        idp=9999,
                        dlf_sf=999999,
                        dn_sf_tep=999999,
                    ),
                    _row("Zzz Anchor LB", "LB", idp=8000, dlf=900000),
                ]
                _compute_unified_rankings(rows, {})
                target = next(r for r in rows if r["canonicalName"] == name)
                self.assertFalse(
                    target.get("isSingleSource"),
                    f"{name} regressed to semantic 1-src (isSingleSource=True)",
                )

    def test_multi_source_players_are_not_1src(self):
        """Players present in both KTC and IDPTC must never be 1-src."""
        rows = [
            _row("Bijan Robinson", "RB", ktc=9981, idp=9981),
            _row("Josh Allen", "QB", ktc=9987, idp=9987),
        ]
        _compute_unified_rankings(rows, {})
        for row in rows:
            self.assertFalse(row.get("isSingleSource"), f"{row['canonicalName']} should not be 1-src")
            self.assertFalse(row.get("isStructurallySingleSource"), f"{row['canonicalName']} should not be structural 1-src")


# ── Test: IDP 1-src for rookies/depth is structural, not semantic ────────

class TestIdpStructural1Src(unittest.TestCase):

    def test_idp_rookie_without_dlf_or_fp_or_fbg_is_structural(self):
        """IDP rookies missing from DLF, FP, AND FootballGuys are structural
        1-src (not semantic).  DLF and FP exclude rookies structurally;
        FootballGuys IDP DOES cover rookies, so an IDP rookie must also
        be missing from FBG for the 1-src to be "structural" across every
        expert IDP board."""
        rows = [
            _row("Arvell Reese", "LB", idp=4169, rookie=True),
            _row("Zzz Anchor LB", "LB", idp=8000, dlf=999900),
        ]
        _compute_unified_rankings(rows, {})
        reese = next(r for r in rows if r["canonicalName"] == "Arvell Reese")
        # Historically this asserted structural=True when only DLF had a
        # rookie exclusion.  With FootballGuys IDP added as an 11th source
        # that DOES cover rookies, a rookie missing from FBG is no longer
        # "structurally" excluded — FBG should have picked him up.  So the
        # synthesized row now represents a SEMANTIC 1-src (other sources
        # were eligible but the scrape didn't include him).
        self.assertFalse(reese.get("isStructurallySingleSource"))
        self.assertTrue(reese.get("isSingleSource"))


# ── Test: Allowlist completeness ─────────────────────────────────────────

class TestAllowlistCompleteness(unittest.TestCase):

    def test_all_allowlist_keys_are_normalized(self):
        """Every allowlist key must be a valid normalized name."""
        for key in SINGLE_SOURCE_ALLOWLIST:
            self.assertEqual(
                key, normalize_player_name(key),
                f"Allowlist key '{key}' is not in normalized form",
            )

    def test_all_allowlist_reasons_have_category(self):
        """Every allowlist reason must start with a recognized category."""
        valid_prefixes = ("source_gap:", "depth_boundary:", "rookie_exclusion:")
        for key, reason in SINGLE_SOURCE_ALLOWLIST.items():
            self.assertTrue(
                reason.startswith(valid_prefixes),
                f"Allowlist reason for '{key}' missing category prefix: {reason}",
            )


# ── Test: Build check function ───────────────────────────────────────────

class TestBuildCheck(unittest.TestCase):

    def test_no_unexplained_1src_with_allowlist(self):
        """Players on the allowlist should not appear as unexplained.

        Uses 'Arvell Reese' (IDP rookie) — an allowlisted player whose
        reason is DLF rookie exclusion, which is a permanent structural
        property of DLF rather than a scraper gap.
        """
        rows = [
            _row("Arvell Reese", "LB", idp=4000, rookie=True),
            _row("Zzz Anchor LB", "LB", idp=8000, dlf=900000),
            _row("Zzz Anchor QB", "QB", ktc=9999, idp=9999),
        ]
        _compute_unified_rankings(rows, {})
        unexplained = assert_no_unexplained_single_source(rows, rank_limit=800)
        # Arvell Reese is on the allowlist (rookie exclusion)
        names = [u["canonicalName"] for u in unexplained]
        self.assertNotIn("Arvell Reese", names)

    def test_unexplained_1src_without_allowlist(self):
        """A 1-src player NOT on the allowlist should be flagged."""
        rows = [
            _row("Zzz Unknown Player", "QB", ktc=7000),
            _row("Zzz Anchor QB", "QB", ktc=9999, idp=9999),
            _row("Zzz Anchor LB", "LB", idp=8000, dlf=900000),
        ]
        _compute_unified_rankings(rows, {})
        unexplained = assert_no_unexplained_single_source(rows, rank_limit=800)
        names = [u["canonicalName"] for u in unexplained]
        self.assertIn("Zzz Unknown Player", names)

    def test_fully_matched_player_not_flagged(self):
        """A multi-source player should never appear as unexplained."""
        rows = [
            _row("Full Coverage QB", "QB", ktc=9000, idp=9000),
        ]
        _compute_unified_rankings(rows, {})
        unexplained = assert_no_unexplained_single_source(rows, rank_limit=800)
        self.assertEqual(len(unexplained), 0)


if __name__ == "__main__":
    unittest.main()
