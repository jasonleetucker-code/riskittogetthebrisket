"""Regression coverage for the player-identity / source-join refactor.

These tests pin the behaviour added in the
``claude/fix-rankings-player-identity`` branch:

* Canonical alias / normalization handles every realistic spelling
  variant (suffix, apostrophe, hyphen, initials, accents, nickname).
* Position-aware canonical keys keep distinct players from collapsing
  on a shared surname (Walker, Allen, Wilson, Thomas, Murphy, …).
* The ``isSingleSource`` flag is *semantic*: it only fires when the
  structural eligibility set contains more than one source AND only
  one matched, never on rookies that the second source structurally
  excludes.
* Two distinct players sharing a normalized name across position
  groups produce two distinct canonical entities — never one
  silently-merged row.
* High-profile veteran top-board players (Kenneth Walker, Marvin
  Harrison, Brian Thomas, T.J. Watt, etc.) cannot silently regress
  to ``1-src`` unless they are explicitly allow-listed.
* The validation pass surfaces real position-aware identity
  collisions and never resurrects the legacy
  ``near_name_value_mismatch`` noise rule.

The tests are deterministic and run on the current
``exports/latest/dynasty_data_*.json`` snapshot — they do not require
network or a running scraper.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from src.api.data_contract import (
    _RANKING_SOURCES,
    _expected_sources_for_position,
    _validate_and_quarantine_rows,
    build_api_data_contract,
)
from src.utils.name_clean import (
    canonical_player_key,
    canonical_position_group,
    normalize_player_name,
    resolve_canonical_name,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


def _latest_dynasty_payload() -> dict:
    """Load the most recent committed ``dynasty_data_*.json`` snapshot.

    We point at the *latest* export (the file the live server reads)
    so the regression checks reflect what the user actually sees on
    the rendered board.
    """
    latest = REPO_ROOT / "exports" / "latest"
    candidates = sorted(latest.glob("dynasty_data_*.json"))
    if not candidates:
        raise unittest.SkipTest("no dynasty_data export available")
    with candidates[-1].open("r", encoding="utf-8") as f:
        return json.load(f)


# ── Normalization regression ────────────────────────────────────────────


class TestNormalizationRegression(unittest.TestCase):
    """Every known-tricky name must collapse to a stable canonical key."""

    SUFFIX_CASES = [
        ("Kenneth Walker III", "Kenneth Walker"),
        ("Marvin Harrison Jr.", "Marvin Harrison"),
        ("Marvin Harrison Jr", "Marvin Harrison"),
        ("Brian Thomas Jr.", "Brian Thomas"),
        ("Brian Thomas Jr", "Brian Thomas"),
        ("Michael Penix Jr.", "Michael Penix"),
        ("Calvin Ridley III", "Calvin Ridley"),
        ("Cedrick Wilson Jr.", "Cedrick Wilson"),
    ]

    PUNCTUATION_CASES = [
        ("T.J. Watt", "TJ Watt"),
        ("Ja'Marr Chase", "JaMarr Chase"),
        ("Le'Veon Bell", "LeVeon Bell"),
        ("De'Von Achane", "DeVon Achane"),
        ("D'Andre Swift", "DAndre Swift"),
        ("N'Keal Harry", "NKeal Harry"),
        ("Amon-Ra St. Brown", "Amon Ra St Brown"),
        ("Jaxon Smith-Njigba", "Jaxon Smith Njigba"),
        ("CJ Allen", "C.J. Allen"),
        ("CJ Stroud", "C.J. Stroud"),
        ("DJ Moore", "D.J. Moore"),
        ("AJ Brown", "A.J. Brown"),
    ]

    ACCENT_CASES = [
        ("Jérémy Chinn", "Jeremy Chinn"),
        ("J\u00e9hu Chesson", "Jehu Chesson"),
        ("Tre\u2019von Moehrig", "TreVon Moehrig"),
    ]

    def test_suffix_variants_collapse(self):
        for variant, canonical in self.SUFFIX_CASES:
            with self.subTest(variant=variant):
                self.assertEqual(
                    normalize_player_name(variant),
                    normalize_player_name(canonical),
                )

    def test_punctuation_variants_collapse(self):
        for variant, canonical in self.PUNCTUATION_CASES:
            with self.subTest(variant=variant):
                self.assertEqual(
                    normalize_player_name(variant),
                    normalize_player_name(canonical),
                )

    def test_accent_variants_collapse(self):
        for variant, canonical in self.ACCENT_CASES:
            with self.subTest(variant=variant):
                self.assertEqual(
                    normalize_player_name(variant),
                    normalize_player_name(canonical),
                )

    def test_resolve_canonical_name_is_idempotent(self):
        # Running the resolver twice must not move the key.
        for name, _ in self.SUFFIX_CASES + self.PUNCTUATION_CASES:
            once = resolve_canonical_name(name)
            twice = resolve_canonical_name(once)
            self.assertEqual(once, twice, f"resolver drifted on {name!r}")


# ── Position-aware canonical keys ──────────────────────────────────────


class TestPositionAwareCanonicalKeys(unittest.TestCase):
    """Distinct players sharing a surname must get distinct canonical keys."""

    SAME_SURNAME_DIFFERENT_PEOPLE = [
        # (offense_name, offense_pos, idp_name, idp_pos)
        ("Kenneth Walker", "RB", "Quay Walker", "LB"),
        ("Kenneth Walker", "RB", "Jalon Walker", "LB"),
        ("Kenneth Walker", "RB", "Travon Walker", "DL"),
        ("Josh Allen", "QB", "CJ Allen", "LB"),
        ("Josh Allen", "QB", "Jonathan Allen", "DL"),
        ("Josh Allen", "QB", "Zach Allen", "DL"),
        ("Brian Thomas", "WR", "Drake Thomas", "LB"),
        ("Caleb Williams", "QB", "Quincy Williams", "LB"),
        ("Caleb Williams", "QB", "Quinnen Williams", "DL"),
        ("Caleb Williams", "QB", "Mykel Williams", "DL"),
        ("Bijan Robinson", "RB", "Chop Robinson", "DL"),
        ("Daniel Jones", "QB", "Brandon Jones", "DB"),
        ("Daniel Jones", "QB", "Chris Jones", "DL"),
        ("Daniel Jones", "QB", "Marcus Jones", "DB"),
        # Same surname WITHIN a single universe — still distinct people.
        ("Quay Walker", "LB", "Jalon Walker", "DL"),
    ]

    def test_position_groups_keep_distinct_players_apart(self):
        for off_name, off_pos, idp_name, idp_pos in self.SAME_SURNAME_DIFFERENT_PEOPLE:
            with self.subTest(off=off_name, idp=idp_name):
                k_off = canonical_player_key(off_name, off_pos)
                k_idp = canonical_player_key(idp_name, idp_pos)
                self.assertNotEqual(k_off, k_idp)

    def test_offense_and_idp_groups_are_distinct(self):
        groups = {
            canonical_position_group("QB"),
            canonical_position_group("RB"),
            canonical_position_group("WR"),
            canonical_position_group("TE"),
        }
        self.assertEqual(groups, {"OFFENSE"})
        groups = {
            canonical_position_group("DL"),
            canonical_position_group("LB"),
            canonical_position_group("DB"),
            canonical_position_group("S"),
            canonical_position_group("CB"),
            canonical_position_group("DE"),
            canonical_position_group("DT"),
            canonical_position_group("EDGE"),
        }
        self.assertEqual(groups, {"IDP"})

    def test_suffix_strip_does_not_collide_distinct_people(self):
        # Marvin Harrison Jr. (WR) and a hypothetical Marvin Harrison
        # CB/S would still get the same name key, but the position
        # group separates them.  Same for Kenneth Walker III RB vs an
        # unrelated Kenneth Walker LB.
        self.assertNotEqual(
            canonical_player_key("Marvin Harrison Jr.", "WR"),
            canonical_player_key("Marvin Harrison", "CB"),
        )
        self.assertNotEqual(
            canonical_player_key("Kenneth Walker III", "RB"),
            canonical_player_key("Kenneth Walker", "LB"),
        )


# ── Specific-target regression for the named bug players ───────────────


# Players the user explicitly listed as "must verify".  Each entry:
#   name, expected position group, expected_in_top_board (bool)
TARGET_PLAYERS = [
    # The headline 1-src bug players
    ("Kenneth Walker", "OFFENSE", True),
    ("Marvin Harrison", "OFFENSE", True),
    ("Brian Thomas",    "OFFENSE", True),
    # Near-name collision noise targets
    ("Quay Walker",     "IDP", True),
    ("Jalon Walker",    "IDP", True),
    ("CJ Allen",        "IDP", True),
    ("Payton Wilson",   "IDP", True),
    ("Nick Emmanwori",  "IDP", True),
    # Elite IDP cornerstones (should be cleanly multi-src in top board)
    ("Aidan Hutchinson", "IDP", True),
    ("Will Anderson",    "IDP", True),
    ("Micah Parsons",    "IDP", True),
    ("Carson Schwesinger", "IDP", True),
    ("Jack Campbell",    "IDP", True),
    ("Fred Warner",      "IDP", True),
    ("Nick Bosa",        "IDP", True),
    ("Brian Burns",      "IDP", True),
    ("Roquan Smith",     "IDP", True),
    ("T.J. Watt",        "IDP", True),
    ("Danielle Hunter",  "IDP", True),
    ("Brian Branch",     "IDP", True),
    ("Kyle Hamilton",    "IDP", True),
]


class TestTargetPlayerSourceAudit(unittest.TestCase):
    """Verify every target player has a sane sourceAudit block."""

    @classmethod
    def setUpClass(cls):
        cls.payload = _latest_dynasty_payload()
        cls.contract = build_api_data_contract(cls.payload)
        cls.by_name = {
            r["canonicalName"]: r for r in cls.contract["playersArray"]
        }

    def _row(self, name):
        row = self.by_name.get(name)
        self.assertIsNotNone(row, f"target player {name!r} missing from contract")
        return row

    def test_target_players_present(self):
        for name, _, _ in TARGET_PLAYERS:
            with self.subTest(player=name):
                self._row(name)

    def test_target_players_have_position_group(self):
        for name, expected_group, _ in TARGET_PLAYERS:
            with self.subTest(player=name):
                row = self._row(name)
                self.assertEqual(
                    canonical_position_group(row.get("position")),
                    expected_group,
                )

    def test_target_players_carry_source_audit(self):
        for name, _, _ in TARGET_PLAYERS:
            with self.subTest(player=name):
                row = self._row(name)
                audit = row.get("sourceAudit") or {}
                self.assertIn("expectedSources", audit)
                self.assertIn("matchedSources", audit)
                self.assertIn("reason", audit)
                self.assertIn(audit["reason"], {
                    "fully_matched",
                    "partial_coverage",
                    "structurally_single_source",
                    "matching_failure_other_sources_eligible",
                    "no_source_match",
                })

    def test_target_players_in_top_board_have_canonical_rank(self):
        for name, _, expected_top in TARGET_PLAYERS:
            if not expected_top:
                continue
            with self.subTest(player=name):
                row = self._row(name)
                self.assertIsNotNone(
                    row.get("canonicalConsensusRank"),
                    f"{name} is missing canonicalConsensusRank",
                )

    def test_no_target_player_collides_with_a_distinct_namesake(self):
        """No two targets share the same canonical key."""
        seen: dict[str, str] = {}
        for name, _, _ in TARGET_PLAYERS:
            row = self._row(name)
            key = canonical_player_key(name, row.get("position"))
            self.assertNotIn(key, seen, f"{name} collides with {seen.get(key)}")
            seen[key] = name

    def test_quay_walker_has_no_near_name_flag(self):
        """The retired noise rule must not resurrect."""
        row = self._row("Quay Walker")
        flags = row.get("anomalyFlags") or []
        self.assertNotIn("near_name_value_mismatch", flags)

    def test_jalon_walker_has_no_near_name_flag(self):
        row = self._row("Jalon Walker")
        flags = row.get("anomalyFlags") or []
        self.assertNotIn("near_name_value_mismatch", flags)

    def test_cj_allen_has_no_near_name_flag(self):
        row = self._row("CJ Allen")
        flags = row.get("anomalyFlags") or []
        self.assertNotIn("near_name_value_mismatch", flags)

    def test_payton_wilson_has_no_near_name_flag(self):
        row = self._row("Payton Wilson")
        flags = row.get("anomalyFlags") or []
        self.assertNotIn("near_name_value_mismatch", flags)


# ── Build-time allowlist: top board players cannot silently regress ───


# Players we *expect* to be 1-src on the live board because the
# scraper is currently missing them in the second source.  Each entry
# must be accompanied by a one-line rationale so future maintainers
# can see why it was added.
KNOWN_TOP_BOARD_SINGLE_SOURCE_ALLOWLIST: dict[str, str] = {
    "Kenneth Walker":  "IDPTradeCalc upstream feed has no entry under Kenneth Walker / Kenneth Walker III",
    "Marvin Harrison": "IDPTradeCalc upstream feed has no entry under Marvin Harrison / Marvin Harrison Jr.",
    "Brian Thomas":    "IDPTradeCalc upstream feed has no entry under Brian Thomas / Brian Thomas Jr.",
    "Michael Penix":   "IDPTradeCalc upstream feed has no entry under Michael Penix / Michael Penix Jr.",
    "Omar Cooper":     "Indiana WR (current college rookie) — not yet listed in IDPTradeCalc autocomplete",
    "Devin Bush":      "Veteran depth IDP — outside DLF top-185 cut",
    "David Bailey":    "Edge rookie IDP — only FantasyPros IDP covers him; moved into top-200 after 2026 slot picks were un-ranked",
    # ── IDP top-board 1-src that surfaced after the IDP Hill curve
    # was refit to IDPTC (midpoint 69.50 / slope 0.945).  The steeper
    # top-of-curve elevation pulled these into the top 200 where they
    # previously lived outside the allowlist's view.  All are
    # legitimate source gaps — IDPTC and FBG haven't listed them so
    # only one IDP board (FP or DLF Rookie) stamps a rank.
    "Jack Gibbens":    "Veteran LB only ranked by FantasyPros IDP — IDPTC/DLF/FBG haven't picked him up",
    "Malachi Moore":   "Veteran S only ranked by FantasyPros IDP — IDPTC/FBG haven't picked him up",
    # Lavonte David removed 2026-04-25: 36yo FA, FBG dropped him in
    # the latest scrape and he no longer appears on the live board.
    # Allowlist entries must reflect a player who CURRENTLY exists on
    # the live contract, otherwise the post-condition test
    # (test_allowlist_entries_actually_appear_on_board) flags it as
    # stale.  If FBG re-adds him, restore the entry.
    # ── Top-200 1-src surfacings after the 2026-04-20 FBG combined-
    # rank scraper upgrade.  FBG's cross-market ordering pulled these
    # veteran DBs / DL up into the top 200 (they previously lived in
    # the 250-400 tail).  Each is a genuine FBG-only veteran that
    # IDPTC, DLF IDP, and the other IDP boards have either dropped or
    # never carried. ──
    "DaRon Bland":      "Veteran CB only ranked by FootballGuys IDP",
    "Jordan Davis":     "Veteran DL only ranked by FootballGuys IDP",
    "Marlon Humphrey":  "Veteran CB only ranked by FootballGuys IDP",
    "Mike Jackson":     "Veteran CB only ranked by FootballGuys IDP",
    "Nahshon Wright":   "Veteran CB only ranked by FootballGuys IDP",
    "Zyon McCollum":    "Veteran CB only ranked by FootballGuys IDP",
}


class TestTopBoardSingleSourceAllowlist(unittest.TestCase):
    """Build-time assertion: high-profile top-board players cannot
    silently remain 1-src unless explicitly allow-listed.

    The allowlist is intentionally short and each entry carries a
    one-line rationale.  Adding a new entry requires a comment
    explaining *why* the upstream pipeline cannot reach the player.
    """

    TOP_BOARD_LIMIT = 200

    @classmethod
    def setUpClass(cls):
        cls.payload = _latest_dynasty_payload()
        cls.contract = build_api_data_contract(cls.payload)

    def test_no_unannotated_single_source_in_top_board(self):
        offenders: list[str] = []
        for row in self.contract["playersArray"]:
            ccr = row.get("canonicalConsensusRank") or 9999
            if ccr > self.TOP_BOARD_LIMIT:
                continue
            if not row.get("isSingleSource"):
                continue
            # Quarantined rows are already flagged by a stronger
            # identity-integrity gate (test_quarantined_under_threshold
            # in tests/api/test_launch_readiness.py).  Listing them here
            # too just double-counts the same fringe rookie / IDP — the
            # daily refresh routinely shifts a quarantined no-value row
            # in and out of the top board, churning this allowlist with
            # transient entries.  Skip them so the two gates don't
            # double-count the same row.
            if row.get("quarantined"):
                continue
            name = row.get("canonicalName") or ""
            if name in KNOWN_TOP_BOARD_SINGLE_SOURCE_ALLOWLIST:
                continue
            offenders.append(f"#{ccr} {name} ({row.get('position')})")
        self.assertEqual(
            offenders,
            [],
            "Top-board players silently regressed to 1-src.  Either fix "
            "the upstream join or add an explicit entry to "
            "KNOWN_TOP_BOARD_SINGLE_SOURCE_ALLOWLIST with a rationale:\n  "
            + "\n  ".join(offenders),
        )

    def test_allowlist_entries_actually_appear_on_board(self):
        """Catch stale allowlist entries — every entry must still be
        present on the live board, otherwise it's just dead data.
        """
        names = {r.get("canonicalName") for r in self.contract["playersArray"]}
        for name in KNOWN_TOP_BOARD_SINGLE_SOURCE_ALLOWLIST:
            with self.subTest(player=name):
                self.assertIn(name, names)


# ── Duplicate / collision tests ─────────────────────────────────────────


class TestCanonicalIdentityUniqueness(unittest.TestCase):
    """No two distinct rows may resolve to the same position-aware
    canonical key.  The validation pass also flags this case
    explicitly with ``duplicate_canonical_identity``.
    """

    @classmethod
    def setUpClass(cls):
        cls.payload = _latest_dynasty_payload()
        cls.contract = build_api_data_contract(cls.payload)

    def test_position_aware_canonical_keys_are_unique(self):
        seen: dict[str, str] = {}
        duplicates: list[tuple[str, str, str]] = []
        for row in self.contract["playersArray"]:
            name = row.get("canonicalName") or ""
            pos = row.get("position")
            key = canonical_player_key(name, pos)
            if not key:
                continue
            existing = seen.get(key)
            if existing is not None and existing != name:
                duplicates.append((key, existing, name))
            seen[key] = name
        self.assertEqual(
            duplicates,
            [],
            f"Two distinct rows collide on the same canonical key: {duplicates}",
        )

    def test_validate_flag_fires_on_synthetic_duplicate(self):
        rows = [
            {
                "canonicalName": "Patrick Mahomes",
                "displayName": "Patrick Mahomes",
                "position": "QB",
                "assetClass": "offense",
                "playerId": None,
                "canonicalSiteValues": {"ktcSfTep": 9000},
                "anomalyFlags": [],
                "confidenceBucket": "high",
                "confidenceLabel": "",
                "rankDerivedValue": 9000,
            },
            {
                "canonicalName": "Patrick Mahomes",
                "displayName": "Patrick Mahomes",
                "position": "QB",
                "assetClass": "offense",
                "playerId": None,
                "canonicalSiteValues": {"idpTradeCalc": 5500},
                "anomalyFlags": [],
                "confidenceBucket": "high",
                "confidenceLabel": "",
                "rankDerivedValue": 5500,
            },
        ]
        summary = _validate_and_quarantine_rows(rows)
        self.assertGreaterEqual(summary["duplicateCanonicalIdentityCount"], 1)
        for row in rows:
            self.assertIn("duplicate_canonical_identity", row["anomalyFlags"])
            self.assertTrue(row["quarantined"])


# ── Source-eligibility refinement (rookie / depth) ─────────────────────


class TestExpectedSourcesRefinement(unittest.TestCase):
    """Expected source set must respect rookie-only sources and shallow
    depth caps.
    """

    def test_rookie_idp_player_does_not_expect_dlf(self):
        off, idp = _expected_sources_for_position(
            "LB", is_rookie=True, player_effective_rank=120
        )
        self.assertNotIn("dlfIdp", off | idp)
        self.assertIn("idpTradeCalc", off | idp)

    def test_veteran_idp_inside_dlf_depth_expects_dlf(self):
        off, idp = _expected_sources_for_position(
            "LB", is_rookie=False, player_effective_rank=50
        )
        self.assertIn("dlfIdp", off | idp)
        self.assertIn("idpTradeCalc", off | idp)

    def test_veteran_idp_beyond_dlf_depth_does_not_expect_dlf(self):
        # 250 > 185 * 1.25 = ~231 → DLF dropped from expected set.
        off, idp = _expected_sources_for_position(
            "LB", is_rookie=False, player_effective_rank=300
        )
        self.assertNotIn("dlfIdp", off | idp)
        self.assertIn("idpTradeCalc", off | idp)


# ── Rebuild output sanity ───────────────────────────────────────────────


class TestRebuildOutputSanity(unittest.TestCase):
    """End-to-end: the rebuilt contract has a sane shape."""

    @classmethod
    def setUpClass(cls):
        cls.payload = _latest_dynasty_payload()
        cls.contract = build_api_data_contract(cls.payload)

    def test_every_top_board_row_has_source_audit(self):
        missing = []
        for row in self.contract["playersArray"]:
            ccr = row.get("canonicalConsensusRank") or 9999
            if ccr > 200:
                continue
            audit = row.get("sourceAudit")
            if not isinstance(audit, dict) or "matchedSources" not in audit:
                missing.append(row.get("canonicalName"))
        self.assertEqual(missing, [])

    def test_validation_summary_carries_new_collision_keys(self):
        vs = self.contract.get("validationSummary") or {}
        self.assertIn("duplicateCanonicalIdentityCount", vs)
        self.assertIn("duplicateCanonicalIdentityPairs", vs)
        self.assertEqual(vs.get("nearNameMismatchCount"), 0)

    def test_methodology_lists_new_anomaly_flags(self):
        methodology = self.contract.get("methodology") or {}
        flags = methodology.get("anomalyFlags") or []
        self.assertIn("duplicate_canonical_identity", flags)
        self.assertNotIn("near_name_value_mismatch", flags)
