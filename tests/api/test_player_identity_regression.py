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
    # Kenneth Walker, Marvin Harrison, Brian Thomas, Michael Penix,
    # and Omar Cooper used to live here.  All five were promoted to
    # multi-source after wiring the DLF SuperFlex
    # (``exports/latest/site_raw/dlfSf.csv``, depth 278, weight 3)
    # and FantasyCalc (``exports/latest/site_raw/fantasyCalc.csv``,
    # depth 456) offense sources into ``_RANKING_SOURCES`` in
    # ``src/api/data_contract.py``.  Both sources include the
    # suffix-bearing names that the IDPTradeCalc autocomplete
    # fallback in ``Dynasty Scraper.py`` was silently dropping.
    "Devin Bush":      "Veteran depth LB — outside DLF top-185 cut and outside KTC's offense pool",
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
                "canonicalSiteValues": {"ktc": 9000},
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


# ── Rank/value monotonicity safety rails ────────────────────────────────


class TestRankValueMonotonicity(unittest.TestCase):
    """Pipeline-wide invariant: the displayed rank must be the
    position of the row in the displayed-value-descending sort.

    These tests pin the bug class that surfaced as:

    * "Amon-Ra St. Brown ranked below Justin Jefferson despite a
      higher displayed value"
    * "Will Anderson and Ladd McConkey both show rank 46 with
      different values"
    * "Tyler Allgeier and Chig Okonkwo both show rank 220 with
      different values"

    The fix is in two places:

    * ``src/api/data_contract.py::resort_unified_board_by_value``
      renumbers ``canonicalConsensusRank`` strictly by displayed value.
    * ``src/api/data_contract.py::assert_rank_value_invariants`` runs
      after every rerank and raises if either invariant is violated.
    * ``server.py::_apply_canonical_primary_overlay`` calls both
      after value overlays so the canonical engine can never
      reintroduce per-universe ranks onto the unified board.
    """

    @classmethod
    def setUpClass(cls):
        cls.payload = _latest_dynasty_payload()
        cls.contract = build_api_data_contract(cls.payload)

    def test_no_duplicate_canonical_consensus_ranks(self):
        seen: dict[int, str] = {}
        dups: list[tuple[int, str, str]] = []
        for row in self.contract["playersArray"]:
            ccr = row.get("canonicalConsensusRank")
            if ccr is None:
                continue
            if ccr in seen:
                dups.append((ccr, seen[ccr], row.get("canonicalName") or ""))
            else:
                seen[ccr] = row.get("canonicalName") or ""
        self.assertEqual(dups, [], f"Duplicate canonicalConsensusRank values: {dups}")

    def test_rank_order_is_monotonic_in_displayed_value(self):
        ranked = sorted(
            (r for r in self.contract["playersArray"] if r.get("canonicalConsensusRank")),
            key=lambda r: r["canonicalConsensusRank"],
        )
        prev_value: float | None = None
        prev_name: str | None = None
        for row in ranked:
            rdv = row.get("rankDerivedValue")
            if rdv is None:
                continue
            value = float(rdv)
            if prev_value is not None and value > prev_value + 1e-9:
                self.fail(
                    f"Rank/value monotonicity broken at "
                    f"#{row['canonicalConsensusRank']}: "
                    f"{row.get('canonicalName')!r}={value} "
                    f"> previous {prev_name!r}={prev_value}"
                )
            prev_value = value
            prev_name = row.get("canonicalName")

    def test_named_pairs_in_correct_relative_order(self):
        """The exact players the user reported as out-of-order."""
        by_name = {
            r["canonicalName"]: r for r in self.contract["playersArray"]
        }
        pairs = [
            ("Amon-Ra St. Brown", "Justin Jefferson"),
            ("Trey McBride",      "Lamar Jackson"),
        ]
        for higher, lower in pairs:
            with self.subTest(higher=higher, lower=lower):
                a = by_name.get(higher)
                b = by_name.get(lower)
                self.assertIsNotNone(a)
                self.assertIsNotNone(b)
                if a.get("rankDerivedValue") is not None and b.get("rankDerivedValue") is not None:
                    if a["rankDerivedValue"] >= b["rankDerivedValue"]:
                        # Higher-value player must have a lower
                        # (better) rank number.
                        self.assertLess(
                            a["canonicalConsensusRank"],
                            b["canonicalConsensusRank"],
                            f"{higher} (value={a['rankDerivedValue']}) must be ranked above "
                            f"{lower} (value={b['rankDerivedValue']}) but "
                            f"got rank {a['canonicalConsensusRank']} vs {b['canonicalConsensusRank']}",
                        )

    def test_invariant_helper_catches_duplicates(self):
        """Direct test of ``assert_rank_value_invariants``."""
        from src.api.data_contract import assert_rank_value_invariants
        bad = {
            "playersArray": [
                {"canonicalName": "A", "canonicalConsensusRank": 1, "rankDerivedValue": 9000},
                {"canonicalName": "B", "canonicalConsensusRank": 1, "rankDerivedValue": 8000},
            ]
        }
        with self.assertRaises(AssertionError):
            assert_rank_value_invariants(bad)

    def test_invariant_helper_catches_monotonicity_break(self):
        from src.api.data_contract import assert_rank_value_invariants
        bad = {
            "playersArray": [
                {"canonicalName": "A", "canonicalConsensusRank": 1, "rankDerivedValue": 7000},
                {"canonicalName": "B", "canonicalConsensusRank": 2, "rankDerivedValue": 9000},
            ]
        }
        with self.assertRaises(AssertionError):
            assert_rank_value_invariants(bad)

    def test_resort_helper_renumbers_in_place(self):
        from src.api.data_contract import resort_unified_board_by_value
        contract = {
            "playersArray": [
                {"canonicalName": "Hi",  "canonicalConsensusRank": 99, "rankDerivedValue": 9000},
                {"canonicalName": "Lo",  "canonicalConsensusRank": 1,  "rankDerivedValue": 1000},
                {"canonicalName": "Mid", "canonicalConsensusRank": 50, "rankDerivedValue": 5000},
            ]
        }
        n = resort_unified_board_by_value(contract)
        self.assertEqual(n, 3)
        ranks = {r["canonicalName"]: r["canonicalConsensusRank"] for r in contract["playersArray"]}
        self.assertEqual(ranks, {"Hi": 1, "Mid": 2, "Lo": 3})


# ── Source coverage promotion (named players must reach multi-src) ─────


class TestNamedPlayersAreMultiSource(unittest.TestCase):
    """The original 1-src bug class: Kenneth Walker, Marvin Harrison,
    Brian Thomas, Michael Penix, Omar Cooper, Travis Hunter must all
    reach multi-source coverage via DLF SuperFlex + FantasyCalc + KTC.

    Devin Bush is the one allowed exception (deep depth veteran LB
    outside both DLF cuts) and stays in
    ``KNOWN_TOP_BOARD_SINGLE_SOURCE_ALLOWLIST``.
    """

    EXPECTED_MULTI_SOURCE = {
        "Kenneth Walker",
        "Marvin Harrison",
        "Brian Thomas",
        "Michael Penix",
        "Omar Cooper",
        "Travis Hunter",
    }

    @classmethod
    def setUpClass(cls):
        cls.payload = _latest_dynasty_payload()
        cls.contract = build_api_data_contract(cls.payload)
        cls.by_name = {
            r["canonicalName"]: r for r in cls.contract["playersArray"]
        }

    def test_named_players_have_2_or_more_sources(self):
        for name in self.EXPECTED_MULTI_SOURCE:
            with self.subTest(player=name):
                row = self.by_name.get(name)
                self.assertIsNotNone(row, f"{name} missing from contract")
                self.assertGreaterEqual(
                    row.get("sourceCount") or 0, 2,
                    f"{name} must be multi-source after the DLF SF + "
                    f"FantasyCalc wiring; got sourceCount="
                    f"{row.get('sourceCount')}, sourceRanks="
                    f"{row.get('sourceRanks')}",
                )
                self.assertFalse(
                    row.get("isSingleSource"),
                    f"{name} must not be flagged isSingleSource",
                )

    def test_named_players_are_not_in_allowlist(self):
        for name in self.EXPECTED_MULTI_SOURCE:
            with self.subTest(player=name):
                self.assertNotIn(
                    name, KNOWN_TOP_BOARD_SINGLE_SOURCE_ALLOWLIST,
                    f"{name} is multi-source now and must NOT be allow-listed",
                )

    def test_travis_hunter_no_suspicious_disagreement(self):
        """Travis Hunter is the dual-role CB/WR.  The robust
        drop-one outlier in :func:`_percentile_rank_spread` removes
        the IDP-side IDPTradeCalc rank that disagrees with the
        offense-side trio (KTC, DLF SF, FantasyCalc), so the
        ``suspicious_disagreement`` flag should not fire.
        """
        row = self.by_name.get("Travis Hunter")
        self.assertIsNotNone(row)
        flags = row.get("anomalyFlags") or []
        self.assertNotIn(
            "suspicious_disagreement", flags,
            f"Travis Hunter should not be flagged suspicious_disagreement "
            f"with 3+ offense sources; flags={flags}, sourceRanks={row.get('sourceRanks')}",
        )


# ── Frontend tier label cannot use canonicalTierId on unified board ───


class TestUnifiedTierDerivation(unittest.TestCase):
    """Pipeline invariant: the tier label / tier id on a unified
    offense + IDP row MUST be derived from the displayed rank, not
    from the per-universe ``canonicalTierId`` field.

    The off-by-one tier headers ("STARTER" inserted after a player
    instead of before the full tier) were caused by the frontend
    preferring a per-universe ``canonicalTierId`` over the rank-based
    fallback.  These tests pin the source files so the regression
    cannot return.
    """

    HELPER_FILE = REPO_ROOT / "frontend" / "lib" / "rankings-helpers.js"

    def test_tier_label_does_not_consult_canonical_tier_id(self):
        text = self.HELPER_FILE.read_text(encoding="utf-8")
        # ``tierLabel`` body must not branch on canonicalTierId.
        # Find the function body and inspect it.
        import re
        m = re.search(
            r"export function tierLabel\(row\) \{(.*?)\n\}",
            text, re.DOTALL,
        )
        self.assertIsNotNone(m, "tierLabel function not found")
        body = m.group(1)
        self.assertNotIn("canonicalTierId", body)

    def test_effective_tier_id_does_not_consult_canonical_tier_id(self):
        text = self.HELPER_FILE.read_text(encoding="utf-8")
        import re
        m = re.search(
            r"export function effectiveTierId\(row\) \{(.*?)\n\}",
            text, re.DOTALL,
        )
        self.assertIsNotNone(m, "effectiveTierId function not found")
        body = m.group(1)
        self.assertNotIn("canonicalTierId", body)


# ── Frontend dynasty-data.js sorts by displayed value ──────────────────


class TestFrontendSortsByDisplayedValue(unittest.TestCase):
    """Pin the frontend ``buildRows`` sort so it cannot regress to
    sorting by a stale backend ``canonicalConsensusRank``.
    """

    DYNASTY_DATA_FILE = REPO_ROOT / "frontend" / "lib" / "dynasty-data.js"

    def test_buildrows_sets_rank_from_sorted_index(self):
        text = self.DYNASTY_DATA_FILE.read_text(encoding="utf-8")
        # The displayed rank must come from the sorted index, not
        # from a possibly-stale backend ``canonicalConsensusRank``.
        self.assertIn("r.rank = i + 1", text)
        # The legacy "r.rank = r.canonicalConsensusRank ?? r.computedConsensusRank"
        # path is the bug the user reported.
        self.assertNotIn(
            "r.rank = r.canonicalConsensusRank",
            text,
            "buildRows must derive r.rank from the sorted index, not from canonicalConsensusRank",
        )
