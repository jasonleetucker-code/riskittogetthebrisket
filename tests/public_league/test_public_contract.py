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
        # Our fixture has two completed trades (2025 wk3, 2024 wk5).
        self.assertEqual(s["totalCount"], 2)

    def test_draft_drafts(self) -> None:
        s = self.contract["sections"]["draft"]
        for block in (
            "drafts",
            "pickOwnership",
            "stockpileLeaderboard",
            "mostPicksOwned",
            "fewestPicksOwned",
            "mostTradedPick",
            "pickMovementTrail",
        ):
            self.assertIn(block, s)

    def test_weekly_weeks(self) -> None:
        s = self.contract["sections"]["weekly"]
        self.assertIn("weeks", s)

    def test_superlatives(self) -> None:
        s = self.contract["sections"]["superlatives"]
        for block in (
            "mostQbHeavy",
            "mostRbHeavy",
            "mostWrHeavy",
            "mostTeHeavy",
            "mostIdpHeavy",
            "mostPickHeavy",
            "mostRookieHeavy",
            "mostBalanced",
            "mostActive",
            "mostFutureFocused",
        ):
            self.assertIn(block, s)

    def test_archives_indices(self) -> None:
        s = self.contract["sections"]["archives"]
        for block in (
            "managers",
            "trades",
            "waivers",
            "weeklyMatchups",
            "rookieDrafts",
            "seasonResults",
        ):
            self.assertIn(block, s)


class ActivityGradingTests(unittest.TestCase):
    """Server-side trade grades on the public activity feed.

    Grades mirror the private ``/trades`` page letter grades but the
    raw values used to compute them never touch the payload — the
    contract safety assert + blocklist still hold.
    """

    @classmethod
    def setUpClass(cls) -> None:
        install_stubs(build_stub_client())
        cls.snapshot = build_public_snapshot("L2025", max_seasons=2)

    def test_activity_feed_has_no_grades_without_valuation(self) -> None:
        # Regression: default callers (no valuation) keep the pre-existing
        # contract shape — grades are strictly opt-in.
        contract = build_public_contract(self.snapshot)
        feed = contract["sections"]["activity"]["feed"]
        self.assertGreater(len(feed), 0)
        for trade in feed:
            for side in trade.get("sides") or []:
                self.assertNotIn("grade", side)

    def test_activity_feed_gains_grades_when_valuation_supplied(self) -> None:
        # Value every "p-rb2" higher than "p-wr2" so the two-player
        # swap in TRADE_2025_WK3 is lopsided enough to exit the
        # Fair-trade bucket (pct >= 3).  Picks are valued low so the
        # pick-swap does not wash out the player edge.
        player_values = {
            "p-rb2": 8000.0,
            "p-wr2": 2000.0,
            "p-wr3": 1500.0,
        }

        def _valuation(asset):
            if not isinstance(asset, dict):
                return 0.0
            if asset.get("kind") == "player":
                return player_values.get(str(asset.get("playerId") or ""), 0.0)
            if asset.get("kind") == "pick":
                return 200.0
            return 0.0

        contract = build_public_contract(
            self.snapshot, activity_valuation=_valuation,
        )
        feed = contract["sections"]["activity"]["feed"]
        graded_sides = [
            side for trade in feed for side in (trade.get("sides") or [])
            if "grade" in side
        ]
        # At least the 2025 two-player swap should be graded.
        self.assertGreater(len(graded_sides), 0)
        for side in graded_sides:
            grade = side["grade"]
            self.assertIn(grade["grade"], {"A", "A-", "A+", "B+", "B", "C", "D", "F"})
            self.assertIn("label", grade)
            self.assertIn("color", grade)
            # Raw values MUST NOT accompany the grade block.
            self.assertNotIn("weighted", side)
            self.assertNotIn("totalValue", side)

        # The full contract must still pass the public safety assert
        # even with grades present — grade/label/color field names are
        # not on the blocklist.
        assert_public_payload_safe(contract)

    def test_activity_grades_all_sides_fair_when_every_value_is_zero(self) -> None:
        # When the private contract has no value for any asset in the
        # trade, grading must still emit a neutral "Fair trade" badge
        # on every side.  Silently dropping grade blocks here would
        # inconsistently hide badges on trades full of unranked
        # assets — the private /trades page treats zero-gap trades
        # as fair, so this path mirrors that behavior.
        def _valuation(_asset):
            return 0.0

        contract = build_public_contract(
            self.snapshot, activity_valuation=_valuation,
        )
        feed = contract["sections"]["activity"]["feed"]
        self.assertGreater(len(feed), 0)
        for trade in feed:
            for side in trade.get("sides") or []:
                self.assertEqual(side["grade"]["grade"], "A")
                self.assertEqual(side["grade"]["label"], "Fair trade")

    def test_activity_grades_mark_only_top_and_bottom_in_multi_team(self) -> None:
        # Simulate a 3-team lopsided trade by valuing the winner's
        # received assets high, the loser's low, and the middle
        # side exactly at the winner's total minus a hair so it is
        # neither max nor min.  The private /trades grading only
        # decorates the extremes — middle sides get "Fair trade".
        #
        # We synthesize this directly against the internal grading
        # helper so the test doesn't depend on the stub trade feed
        # having a 3-side transaction.
        from src.public_league.activity import _apply_trade_grades

        trade = {
            "transactionId": "synthetic-3way",
            "sides": [
                {"receivedAssets": [{"kind": "player", "playerId": "top"}]},
                {"receivedAssets": [{"kind": "player", "playerId": "mid"}]},
                {"receivedAssets": [{"kind": "player", "playerId": "bot"}]},
            ],
        }
        values = {"top": 10000.0, "mid": 5000.0, "bot": 100.0}

        def _valuation(asset):
            return values.get(str(asset.get("playerId") or ""), 0.0)

        _apply_trade_grades([trade], _valuation)
        grades = [s["grade"]["grade"] for s in trade["sides"]]
        labels = [s["grade"]["label"] for s in trade["sides"]]
        # Top-weighted side earns a winner grade (A/A-/A+), bottom
        # earns a loser grade (B/C/D/F), middle is neutral Fair.
        self.assertIn(grades[0], {"A", "A-", "A+", "B+"})
        self.assertEqual(labels[1], "Fair trade")
        self.assertIn(grades[2], {"B+", "B", "C", "D", "F"})

    def test_activity_section_payload_threads_valuation(self) -> None:
        # The per-section endpoint (/api/public/league/activity) also
        # honors the optional valuation kwarg.  Uniform player values
        # + uniform pick values → the 2025 swap is balanced and both
        # sides land in the "Fair trade" bucket.
        def _valuation(asset):
            if isinstance(asset, dict) and asset.get("kind") == "player":
                return 1000.0
            return 100.0

        payload = build_section_payload(
            self.snapshot, "activity", activity_valuation=_valuation,
        )
        feed = payload["data"]["feed"]
        self.assertGreater(len(feed), 0)
        trade_2025 = next(t for t in feed if t["transactionId"] == "tx-2025-a")
        grades = [side["grade"]["grade"] for side in trade_2025["sides"]]
        self.assertEqual(grades, ["A", "A"])
        labels = {side["grade"]["label"] for side in trade_2025["sides"]}
        self.assertEqual(labels, {"Fair trade"})


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
