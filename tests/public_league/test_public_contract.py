"""Tests for the PUBLIC /league contract.

These tests are the load-bearing guardrails that stop the public
pipeline from ever leaking private signals:

    1. The rendered contract contains NO field names that match the
       private-field blocklist (edge, trade-finder, site values, etc.).
    2. Manager identity is keyed by ``owner_id`` — renames do not
       split a manager across seasons, and orphan-roster handoffs do
       not merge two owner_ids.
    3. History / records / awards attribute to the owner who actually
       held the roster at the time of each season.
    4. The public snapshot pipeline does NOT read from private
       modules (``src.canonical``, ``src.api.data_contract``,
       ``src.trade``) — enforced by an import-surface scan.
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

from src.public_league import (
    PUBLIC_SECTION_KEYS,
    build_public_contract,
    build_public_snapshot,
    build_section_payload,
)
from src.public_league.public_contract import (
    _PRIVATE_FIELD_BLOCKLIST,
    assert_public_payload_safe,
)

from tests.public_league.fixtures import build_stub_client, install_stubs


class PublicContractSafetyTests(unittest.TestCase):
    """Assert the contract never emits any field on the blocklist."""

    @classmethod
    def setUpClass(cls) -> None:
        install_stubs(build_stub_client())
        cls.snapshot = build_public_snapshot("L2025", max_seasons=2)
        cls.contract = build_public_contract(cls.snapshot)

    def test_contract_has_expected_top_level_shape(self) -> None:
        c = self.contract
        self.assertIn("contractVersion", c)
        self.assertIn("league", c)
        self.assertIn("sections", c)
        self.assertIn("sectionKeys", c)
        self.assertEqual(list(c["sectionKeys"]), list(PUBLIC_SECTION_KEYS))
        for key in PUBLIC_SECTION_KEYS:
            self.assertIn(key, c["sections"])

    def test_contract_does_not_leak_any_private_fields(self) -> None:
        # The explicit assert_public_payload_safe runs during the
        # contract build above.  Here we double-check with a textual
        # scan so a future edit that bypasses the assert (e.g. by
        # injecting raw scraper JSON) is caught by a different
        # mechanism.
        import json as _json

        blob = _json.dumps(self.contract).lower()
        for name in _PRIVATE_FIELD_BLOCKLIST:
            # Words in the blocklist are field names — use a
            # word-boundary-ish check against quoted dict keys so we
            # don't false-positive on substrings embedded in user
            # strings (e.g. "bea's beast mode" is fine even though
            # "edge" is in the blocklist).
            pattern = f'"{name}"' + ":"
            self.assertNotIn(
                pattern,
                blob,
                msg=f"Blocked field {name!r} leaked into public contract",
            )

    def test_every_section_is_safe_on_its_own(self) -> None:
        for key in PUBLIC_SECTION_KEYS:
            payload = build_section_payload(self.snapshot, key)
            assert_public_payload_safe(payload)

    def test_private_field_guard_rejects_leaks(self) -> None:
        # Direct invariant test — if someone adds a private field to
        # the header, the guard MUST trip.
        for name in ("ourValue", "edgeSignals", "tradeFinder", "siteWeights", "rankDerivedValue"):
            with self.assertRaises(AssertionError):
                assert_public_payload_safe({"foo": [{"bar": {name: 1}}]})


class ManagerIdentityTests(unittest.TestCase):
    """owner_id — not team name, not roster_id — is the key."""

    @classmethod
    def setUpClass(cls) -> None:
        install_stubs(build_stub_client())
        cls.snapshot = build_public_snapshot("L2025", max_seasons=2)

    def test_renamed_team_stays_one_manager(self) -> None:
        aaron = self.snapshot.managers.by_owner_id["owner-A"]
        alias_names = sorted(a.team_name for a in aaron.aliases)
        self.assertIn("AAron Classic", alias_names)
        self.assertIn("Brisket Bandits", alias_names)
        # Two seasons, one manager, two aliases — not two managers.
        self.assertEqual(len(self.snapshot.managers.by_owner_id.get("owner-A").aliases), 2)

    def test_orphan_handoff_does_not_merge_owners(self) -> None:
        # owner-X held roster 4 in 2024; owner-D holds it in 2025.
        # The registry MUST contain both managers separately.
        self.assertIn("owner-X", self.snapshot.managers.by_owner_id)
        self.assertIn("owner-D", self.snapshot.managers.by_owner_id)
        self.assertNotEqual("owner-X", "owner-D")

    def test_roster_to_owner_is_season_scoped(self) -> None:
        # Roster 4 in 2025 is owner-D, in 2024 it's owner-X.
        self.assertEqual(self.snapshot.managers.owner_for_roster("L2025", 4), "owner-D")
        self.assertEqual(self.snapshot.managers.owner_for_roster("L2024", 4), "owner-X")
        # Roster 1 is owner-A in both seasons.
        self.assertEqual(self.snapshot.managers.owner_for_roster("L2025", 1), "owner-A")
        self.assertEqual(self.snapshot.managers.owner_for_roster("L2024", 1), "owner-A")

    def test_history_attributes_by_owner_id_not_roster(self) -> None:
        contract = build_public_contract(self.snapshot)
        history = contract["sections"]["history"]
        seasons = {s["season"]: s for s in history["seasons"]}
        # 2024: roster 4 owner was owner-X.
        row_2024 = next(r for r in seasons["2024"]["standings"] if r["rosterId"] == 4)
        self.assertEqual(row_2024["ownerId"], "owner-X")
        # 2025: roster 4 owner is owner-D.
        row_2025 = next(r for r in seasons["2025"]["standings"] if r["rosterId"] == 4)
        self.assertEqual(row_2025["ownerId"], "owner-D")


class SectionCoverageTests(unittest.TestCase):
    """Every section at least returns the expected top-level shape."""

    @classmethod
    def setUpClass(cls) -> None:
        install_stubs(build_stub_client())
        cls.snapshot = build_public_snapshot("L2025", max_seasons=2)
        cls.contract = build_public_contract(cls.snapshot)

    def test_history_sections(self) -> None:
        s = self.contract["sections"]["history"]
        self.assertIn("seasons", s)
        self.assertIn("hallOfFame", s)
        self.assertIn("championsBySeason", s)

    def test_rivalries(self) -> None:
        s = self.contract["sections"]["rivalries"]
        self.assertIn("rivalries", s)

    def test_awards_has_season_rows(self) -> None:
        s = self.contract["sections"]["awards"]
        self.assertIn("bySeason", s)
        self.assertGreaterEqual(len(s["bySeason"]), 1)

    def test_records_has_highs_and_lows(self) -> None:
        s = self.contract["sections"]["records"]
        self.assertIn("singleWeekHighest", s)
        self.assertIn("singleWeekLowest", s)

    def test_franchise_index_and_detail(self) -> None:
        s = self.contract["sections"]["franchise"]
        self.assertIn("index", s)
        self.assertIn("detail", s)
        self.assertIn("owner-A", s["detail"])

    def test_activity_feed(self) -> None:
        s = self.contract["sections"]["activity"]
        self.assertIn("feed", s)
        self.assertIn("totalCount", s)
        # Our fixture has one trade — it should survive.
        self.assertEqual(s["totalCount"], 1)

    def test_draft_drafts(self) -> None:
        s = self.contract["sections"]["draft"]
        self.assertIn("drafts", s)
        self.assertIn("remainingCapital", s)

    def test_weekly_weeks(self) -> None:
        s = self.contract["sections"]["weekly"]
        self.assertIn("weeks", s)

    def test_superlatives(self) -> None:
        s = self.contract["sections"]["superlatives"]
        for block in ("hardLuck", "luckyDuck", "tradeMachine", "mostImproved", "couchCoach"):
            self.assertIn(block, s)

    def test_archives_indices(self) -> None:
        s = self.contract["sections"]["archives"]
        for block in ("managers", "trades", "draftPicks", "weekScores"):
            self.assertIn(block, s)


class ImportSurfaceTests(unittest.TestCase):
    """Enforce the public pipeline never imports private internals."""

    FORBIDDEN_IMPORT_PREFIXES = (
        "src.api.data_contract",
        "src.canonical",
        "src.trade",
        "src.pool",
    )

    def test_public_league_package_has_no_private_imports(self) -> None:
        package_dir = Path(__file__).resolve().parents[2] / "src" / "public_league"
        offenders: list[str] = []
        import_re = re.compile(r"^\s*(from|import)\s+([a-zA-Z0-9_\.]+)")
        for path in package_dir.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for line in text.splitlines():
                m = import_re.match(line)
                if not m:
                    continue
                mod = m.group(2)
                for bad in self.FORBIDDEN_IMPORT_PREFIXES:
                    if mod == bad or mod.startswith(bad + "."):
                        offenders.append(f"{path.name}: {line.strip()}")
        self.assertFalse(
            offenders,
            msg="Public league package must not import private internals:\n"
            + "\n".join(offenders),
        )


if __name__ == "__main__":
    unittest.main()
