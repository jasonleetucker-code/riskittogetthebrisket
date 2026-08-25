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
        # Only eager sections appear in the aggregate walk's
        # ``c["sections"]`` block.  Lazy ones (e.g. playoffOdds, which
        # runs a 10K-sim Monte Carlo) are intentionally excluded so
        # the baseline contract load doesn't pay their cost — they
        # remain callable via ``/api/public/league/<section>``.
        from src.public_league.public_contract import (
            _SECTION_BUILDERS,
            _LAZY_SECTION_BUILDERS,
            OVERVIEW_SECTION,
        )

        eager = (OVERVIEW_SECTION,) + tuple(_SECTION_BUILDERS.keys())
        for key in eager:
            self.assertIn(key, c["sections"])
        for key in _LAZY_SECTION_BUILDERS:
            self.assertNotIn(key, c["sections"])

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

    def test_team_assignment_healthy_snapshot_reports_available(self) -> None:
        """V1-94 / #815, healthy half, through the REAL assembly pipeline
        (not a hand-built ``PublicLeagueSnapshot`` — this one comes from
        ``build_public_snapshot`` over stubbed Sleeper responses, same as
        every other section this class checks)."""
        payload = build_section_payload(self.snapshot, "teamAssignment")
        data = payload["data"]
        self.assertTrue(data["available"])
        self.assertIsNone(data["unavailableReason"])
        self.assertGreater(len(data["assignments"]), 0)

    def test_team_assignment_degraded_snapshot_reports_unavailable_not_empty(
        self,
    ) -> None:
        """V1-94 / #815, degraded half, through the SAME real pipeline.

        An unknown league id makes ``fetch_league`` return ``None``, which
        ``build_public_snapshot`` turns into zero seasons — a real
        degraded-fetch shape, not a hand-constructed one. Before #815 this
        rendered as a bare ``assignments: []`` indistinguishable from a
        healthy empty league; it must now say why, and the safety walk
        must still accept the shape.
        """
        degraded_snapshot = build_public_snapshot("L_UNKNOWN_LEAGUE_ID", max_seasons=2)
        self.assertIsNone(degraded_snapshot.current_season)
        payload = build_section_payload(degraded_snapshot, "teamAssignment")
        assert_public_payload_safe(payload)
        data = payload["data"]
        self.assertFalse(data["available"])
        self.assertEqual(data["unavailableReason"], "no_current_season")
        self.assertEqual(data["assignments"], [])

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

    def test_archives_manager_index_covers_every_season_result_owner(self) -> None:
        """V1-96 residual (C9-HIST-01): the archives manager index must
        cover the rows it indexes.

        ``seasonResults`` emits every historical standings row, including
        retirees' real past seasons.  A manager index built from the
        forward-facing directory (``ordered_managers()`` default,
        retirees excluded) therefore cannot find owners its own archive
        contains.  The invariant — not a count literal: every ownerId
        appearing in seasonResults appears in the manager index.
        """
        from src.public_league import archives

        install_stubs(build_stub_client())
        snapshot = build_public_snapshot("L2025", max_seasons=2)
        # owner-X held roster 4 in 2024 only — exactly the retiree shape.
        # Flag them retired the way build_manager_registry models it
        # (Manager.is_retired), so the fixture contains a retired manager
        # WITH historical season rows.
        snapshot.managers.by_owner_id["owner-X"].is_retired = True

        section = archives.build_section(snapshot)
        season_result_owners = {row["ownerId"] for row in section["seasonResults"]}
        index_owners = {row["ownerId"] for row in section["managers"]}

        # Guard against vacuity: the retiree really is in the archive rows.
        self.assertIn("owner-X", season_result_owners)
        self.assertLessEqual(
            season_result_owners,
            index_owners,
            msg=(
                "archives.seasonResults contains owners the archives manager "
                "index cannot find: "
                f"{sorted(season_result_owners - index_owners)}"
            ),
        )

    def test_luck_section(self) -> None:
        s = self.contract["sections"]["luck"]
        for block in (
            "byOwnerCareer",
            "byOwnerSeason",
            "currentSeasonRanked",
            "weeklyTrail",
            "methodology",
        ):
            self.assertIn(block, s)

    def test_streaks_section(self) -> None:
        s = self.contract["sections"]["streaks"]
        for block in (
            "activeStreaks",
            "activeStreaksByType",
            "recordsInReach",
            "notableThisWeek",
        ):
            self.assertIn(block, s)

    def test_no_legacy_power_section(self) -> None:
        """The v1 power engine (``src/public_league/power.py``) is
        retired.  The aggregate contract no longer builds a ``power``
        section at all -- the canonical engine lives at the lazy
        ``rosPower`` section key instead (see test_server_routes.py for
        HTTP-level coverage of that endpoint)."""
        self.assertNotIn("power", self.contract["sections"])
        self.assertNotIn("power", PUBLIC_SECTION_KEYS)

    def test_matchup_preview_section(self) -> None:
        s = self.contract["sections"]["matchupPreview"]
        for block in ("currentSeason", "currentWeek", "mode", "matchups"):
            self.assertIn(block, s)

    def test_weekly_recap_section(self) -> None:
        s = self.contract["sections"]["weeklyRecap"]
        for block in ("weeks", "byKey", "latest", "seasonsCovered"):
            self.assertIn(block, s)


def _const_valuation_factory(value_fn):
    """Wrap an old-style ``(asset) -> float`` valuation function as the
    resolver-factory shape ``activity_valuation`` now expects
    (V1-97 / C3-REPLAY-01: grading resolves AS OF each trade's own
    instant, via a factory that batches every ``(asset, instant)`` pair
    up front).  These tests exercise grading MATH — band table, VA
    engine, sanitization — not temporal correctness, so the factory
    here ignores the trade instant entirely and just re-runs the
    supplied per-asset function.
    """

    def _factory(_requests):
        return lambda asset, _instant: value_fn(asset)

    return _factory


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
            self.snapshot,
            activity_valuation=_const_valuation_factory(_valuation),
        )
        feed = contract["sections"]["activity"]["feed"]
        graded_sides = [
            side for trade in feed for side in (trade.get("sides") or []) if "grade" in side
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
        # trade, grading must still emit badges on every side.  With
        # the floor-1 contribution that mirrors private grading, a
        # symmetric trade (both sides got the same asset count) ends
        # up with identical floor totals → "Fair trade" on every
        # side.  We pin against the 2025 fixture trade which is
        # symmetric (1 player + 1 pick per side); the 2024 fixture
        # is asymmetric and legitimately grades lopsided when the
        # loser side received nothing.
        def _valuation(_asset):
            return 0.0

        contract = build_public_contract(
            self.snapshot,
            activity_valuation=_const_valuation_factory(_valuation),
        )
        feed = contract["sections"]["activity"]["feed"]
        trade_2025 = next(t for t in feed if t["transactionId"] == "tx-2025-a")
        for side in trade_2025["sides"]:
            self.assertEqual(side["grade"]["grade"], "A")
            self.assertEqual(side["grade"]["label"], "Fair trade")

    def test_activity_grades_sanitize_non_finite_valuation(self) -> None:
        # A valuation that returns NaN for some assets must not poison
        # the per-side total.  Without sanitization the NaN propagates
        # into the net, every band comparison against it is False, and
        # the side falls through to the "F Fleeced" tail — on a trade
        # that is a dead-even 1000-for-1000 swap.
        from src.public_league.activity import _apply_trade_grades

        got_a = [
            {"kind": "player", "playerId": "a"},
            {"kind": "player", "playerId": "nan-1"},
        ]
        got_b = [
            {"kind": "player", "playerId": "b"},
            {"kind": "player", "playerId": "nan-2"},
        ]
        trade = {
            "transactionId": "synthetic-nan",
            "createdAt": 1752580800000,
            "sides": [
                {"receivedAssets": got_a, "sentAssets": got_b},
                {"receivedAssets": got_b, "sentAssets": got_a},
            ],
        }

        def _valuation(asset, _instant):
            pid = str(asset.get("playerId") or "")
            if pid in {"a", "b"}:
                return 1000.0
            return float("nan")

        _apply_trade_grades([trade], _valuation)
        grades = [s["grade"]["grade"] for s in trade["sides"]]
        labels = [s["grade"]["label"] for s in trade["sides"]]
        self.assertEqual(grades, ["A", "A"])
        self.assertEqual(labels, ["Fair trade", "Fair trade"])

    def test_activity_grades_each_multi_team_side_on_its_own_net(self) -> None:
        # 3-team trade, graded the way the private /trades page grades
        # it: every side on its OWN got-minus-gave net, not ranked
        # against the other sides' received totals.  The two differ
        # exactly where it matters — team C receives the SECOND-smallest
        # pile (3000) but sent only 1000, so it is a clear winner, while
        # ranking received totals would call it the unremarkable middle
        # side and stamp it "Fair trade".
        #
        #   A: got 1000, gave 8000  → −7000 / 8000 = −87.5%  → F
        #   B: got 8000, gave 3000  → +5000 / 8000 = +62.5%  → A+
        #   C: got 3000, gave 1000  → +2000 / 3000 = +66.67% → A+
        #
        # Every side is 1-for-1, and KTC suppresses the value adjustment
        # on 1v1 packages, so all three pcts are plain ratios.
        #
        # Synthesized directly against the internal grading helper so
        # the test doesn't depend on the stub feed having a 3-side
        # transaction.
        from src.public_league.activity import _apply_trade_grades

        def _asset(pid):
            return {"kind": "player", "playerId": pid}

        trade = {
            "transactionId": "synthetic-3way",
            "createdAt": 1752580800000,
            "sides": [
                {"receivedAssets": [_asset("small")], "sentAssets": [_asset("big")]},
                {"receivedAssets": [_asset("big")], "sentAssets": [_asset("mid")]},
                {"receivedAssets": [_asset("mid")], "sentAssets": [_asset("small")]},
            ],
        }
        values = {"big": 8000.0, "mid": 3000.0, "small": 1000.0}

        def _valuation(asset, _instant):
            return values.get(str(asset.get("playerId") or ""), 0.0)

        _apply_trade_grades([trade], _valuation)
        grades = [s["grade"]["grade"] for s in trade["sides"]]
        labels = [s["grade"]["label"] for s in trade["sides"]]
        self.assertEqual(grades, ["F", "A+", "A+"])
        self.assertEqual(labels, ["Fleeced", "Big win", "Big win"])

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
            self.snapshot,
            "activity",
            activity_valuation=_const_valuation_factory(_valuation),
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
            msg="Public league package must not import private internals:\n" + "\n".join(offenders),
        )


if __name__ == "__main__":
    unittest.main()
