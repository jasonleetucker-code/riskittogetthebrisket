"""Tests for the draft capital pipeline.

The Draft Data workbook is the authoritative source for pick values
(Q45:Q116) and the slot→original-owner standings (O30:R42).  Pick
ownership is overlaid live from Sleeper's ``/traded_picks`` API; the
workbook's R45:R116 column is the fallback when Sleeper is
unreachable.  Tests that need to assert workbook-only behavior pass
``apply_sleeper_trades=False``.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))


def _load():
    import server
    return server._parse_draft_data()


class TestDraftDataParsing(unittest.TestCase):

    def test_72_picks(self):
        pick_dollars, _, _, _, _ = _load()
        self.assertEqual(len(pick_dollars), 72)

    def test_workbook_picks_parsed(self):
        _, workbook_picks, _, _, _ = _load()
        self.assertEqual(len(workbook_picks), 72)

    def test_pick_values_are_float(self):
        pick_dollars, _, _, _, _ = _load()
        for i, v in enumerate(pick_dollars):
            self.assertIsInstance(v, float, f"pick_dollars[{i}] is {type(v)}")

    def test_workbook_has_decimals(self):
        """Workbook values (97.5, 88.5 etc.) confirm xlsx is being read."""
        _, workbook_picks, _, _, _ = _load()
        has_decimal = any(wp["value"] % 1 != 0 for wp in workbook_picks)
        self.assertTrue(has_decimal, "No decimals — likely reading stale CSV")


class TestIntegerRounding(unittest.TestCase):

    def test_round_to_budget_sums_to_1200(self):
        import server
        _, workbook_picks, _, _, _ = _load()
        values = [wp["value"] for wp in workbook_picks]
        rounded = server._round_to_budget(values, 1200)
        self.assertEqual(sum(rounded), 1200,
                         f"Rounded sum = {sum(rounded)}, expected 1200")

    def test_round_to_budget_all_ints(self):
        import server
        _, workbook_picks, _, _, _ = _load()
        values = [wp["value"] for wp in workbook_picks]
        rounded = server._round_to_budget(values, 1200)
        for i, v in enumerate(rounded):
            self.assertIsInstance(v, int, f"rounded[{i}] is {type(v)}")

    def test_expansion_picks_equal_after_rounding(self):
        """Picks 1 and 2 in each round should be equal (same input value
        produces same rounded output)."""
        import server
        _, workbook_picks, _, _, _ = _load()
        values = [wp["value"] for wp in workbook_picks]
        rounded = server._round_to_budget(values, 1200)
        for rnd in range(6):
            idx = rnd * 12
            self.assertEqual(rounded[idx], rounded[idx + 1],
                             f"R{rnd+1}: pick1={rounded[idx]} != pick2={rounded[idx+1]}")


class TestApiOutput(unittest.TestCase):

    def test_api_values_are_integers(self):
        import server
        result = server._fetch_draft_capital(apply_sleeper_trades=False)
        if "error" in result:
            self.skipTest(f"Unavailable: {result['error']}")
        for p in result["picks"]:
            self.assertIsInstance(p["adjustedDollarValue"], int,
                                 f"{p['pick']}: {p['adjustedDollarValue']} is not int")

    def test_api_total_budget_1200(self):
        import server
        result = server._fetch_draft_capital(apply_sleeper_trades=False)
        if "error" in result:
            self.skipTest(f"Unavailable: {result['error']}")
        self.assertEqual(result["totalBudget"], 1200)

    def test_api_team_totals_sum_to_1200(self):
        import server
        result = server._fetch_draft_capital(apply_sleeper_trades=False)
        if "error" in result:
            self.skipTest(f"Unavailable: {result['error']}")
        total = sum(t["auctionDollars"] for t in result["teamTotals"])
        self.assertEqual(total, 1200, f"Team total sum = {total}")


class TestTeamTotalsMirrorSheet(unittest.TestCase):
    """The pipeline must mirror the sheet: accumulating R45:R116
    ownership against Q45:Q116 values must equal the authoritative
    per-owner decimals in T63:U74, and the API's integer totals must
    sum to exactly 1200 via largest-remainder rounding of those
    decimals."""

    def test_decimal_totals_match_sheet_per_owner(self):
        from collections import defaultdict
        _, workbook_picks, _, wb_team_totals, _ = _load()
        computed = defaultdict(float)
        for wp in workbook_picks:
            computed[wp["owner"]] += wp["value"]
        for owner, total in computed.items():
            self.assertAlmostEqual(
                total, wb_team_totals.get(owner, 0.0), places=2,
                msg=f"{owner}: computed={total}, sheet={wb_team_totals.get(owner)}",
            )

    def test_api_team_totals_match_largest_remainder_of_sheet_decimals(self):
        """Sorted API dollar totals must equal largest-remainder
        rounding of the sheet's per-owner decimals (regardless of the
        Sleeper display-name mapping used to label each row).

        Pinned to ``apply_sleeper_trades=False`` so the workbook's
        R45:R116 ownership column is the sole owner-of-record; with
        the live overlay any Sleeper trade not yet reflected in the
        sheet would shift dollars between teams and break this
        invariant."""
        import server
        from collections import defaultdict
        _, workbook_picks, _, _, _ = _load()
        decimals = defaultdict(float)
        for wp in workbook_picks:
            decimals[wp["owner"]] += wp["value"]

        result = server._fetch_draft_capital(apply_sleeper_trades=False)
        if "error" in result:
            self.skipTest(f"Unavailable: {result['error']}")

        # Pad with zero-total rows for any teams Sleeper reports that
        # don't appear as owners in R45:R116 (e.g. expansion franchises
        # with no picks yet).
        api_totals = sorted(
            [t["auctionDollars"] for t in result["teamTotals"]], reverse=True,
        )
        decimal_vals = sorted(decimals.values(), reverse=True)
        pad = max(0, len(api_totals) - len(decimal_vals))
        decimal_vals += [0.0] * pad
        expected = sorted(
            server._round_to_budget(decimal_vals, 1200), reverse=True,
        )
        self.assertEqual(api_totals, expected,
                         f"api={api_totals} expected={expected}")


class TestSleeperTradeOverlay(unittest.TestCase):
    """Ownership in the workbook (R45:R116) is hand-edited and lags
    real-time trades.  ``_fetch_draft_capital`` overlays Sleeper's
    ``/traded_picks`` so dollars-per-team reflect the current
    Sleeper roster ownership without waiting for a commissioner edit.
    """

    def _stub_urlopen(self, url_to_payload):
        """Build a urllib.request.urlopen stub from a {url-substring: payload}
        map.  Each payload is a dict/list that gets JSON-encoded."""
        import io
        import json as _json

        def fake_urlopen(url, *args, **kwargs):
            target = url.full_url if hasattr(url, "full_url") else str(url)
            for key, payload in url_to_payload.items():
                if key in target:
                    return io.BytesIO(_json.dumps(payload).encode())
            raise AssertionError(f"unexpected urlopen({target})")
        return fake_urlopen

    def _build_overlay_fixture(self, draft_season):
        """Construct mocked Sleeper responses for a single traded pick.

        Returns ``(url_map, wp, orig_first, other_first)`` where ``wp``
        is the workbook pick chosen for the trade and the two first
        names identify the original / receiving team buckets.

        ``draft_season`` is what Sleeper reports as the league/draft
        season — may differ from the server's calendar year (Dec→Jan
        boundary regression)."""
        _, workbook_picks, slot_to_original, _, _ = _load()
        if not workbook_picks or not slot_to_original:
            return None

        target = None
        for wp in workbook_picks:
            if wp["value"] <= 0:
                continue
            orig = slot_to_original.get(wp["pick"])
            other = next(
                (n for s, n in slot_to_original.items()
                 if s != wp["pick"] and n != orig),
                None,
            )
            if orig and other:
                target = (wp, orig, other)
                break
        if target is None:
            return None
        wp, orig_first, other_first = target

        rosters, users = [], []
        slot_to_roster: dict[str, int] = {}
        roster_id_for_first: dict[str, int] = {}
        for slot, first_name in slot_to_original.items():
            rid = int(slot)
            owner_uid = f"u{rid}"
            rosters.append({"roster_id": rid, "owner_id": owner_uid})
            users.append({
                "user_id": owner_uid,
                "display_name": f"Team-{first_name}",
                "metadata": {},
            })
            slot_to_roster[str(slot)] = rid
            roster_id_for_first[first_name] = rid

        drafts = [{"draft_id": "D1", "season": draft_season}]
        draft_detail = {"slot_to_roster_id": slot_to_roster}
        traded_picks = [{
            "season": draft_season,
            "round": wp["round"],
            "roster_id": roster_id_for_first[orig_first],
            "owner_id": roster_id_for_first[other_first],
            "previous_owner_id": roster_id_for_first[orig_first],
        }]
        url_map = {
            "/rosters": rosters,
            "/users": users,
            "/drafts": drafts,
            "/draft/D1": draft_detail,
            "/traded_picks": traded_picks,
        }
        return url_map, wp, orig_first, other_first

    def _run_overlay(self, draft_season):
        """Drive ``_fetch_draft_capital`` with mocked Sleeper responses
        for ``draft_season``.  Returns (with_overlay_result,
        without_overlay_result, wp, orig_first, other_first) or None
        if the workbook is unavailable."""
        import server
        fixture = self._build_overlay_fixture(draft_season)
        if fixture is None:
            return None
        url_map, wp, orig_first, other_first = fixture
        with patch.object(server.urllib.request, "urlopen",
                          self._stub_urlopen(url_map)), \
             patch.object(server, "_sleeper_league_id_for_draft",
                          return_value="TEST_LEAGUE"):
            with_overlay = server._fetch_draft_capital(apply_sleeper_trades=True)
            without_overlay = server._fetch_draft_capital(apply_sleeper_trades=False)
        if "error" in with_overlay or "error" in without_overlay:
            return None
        return with_overlay, without_overlay, wp, orig_first, other_first

    @staticmethod
    def _team_total(result, team_first):
        label = f"Team-{team_first}"
        for row in result["teamTotals"]:
            if row["team"] == label:
                return row["auctionDollars"]
        return 0

    def test_traded_pick_moves_dollars_between_teams(self):
        """When Sleeper reports a pick was traded, the receiving team's
        dollar total must increase and the original owner's must
        decrease — independent of whatever R45:R116 says."""
        from datetime import datetime, timezone
        run = self._run_overlay(datetime.now(timezone.utc).year)
        if run is None:
            self.skipTest("Workbook unavailable")
        with_overlay, without_overlay, wp, orig_first, other_first = run

        delta_recv = (self._team_total(with_overlay, other_first)
                      - self._team_total(without_overlay, other_first))
        delta_orig = (self._team_total(with_overlay, orig_first)
                      - self._team_total(without_overlay, orig_first))
        self.assertGreater(delta_recv, 0,
                           f"Receiving team did not gain dollars: {delta_recv}")
        self.assertLess(delta_orig, 0,
                        f"Original owner did not lose dollars: {delta_orig}")

        traded_pick_label = f"{wp['round']}.{str(wp['pick']).zfill(2)}"
        overlay_pick = next(
            (p for p in with_overlay["picks"] if p["pick"] == traded_pick_label),
            None,
        )
        self.assertIsNotNone(overlay_pick)
        self.assertEqual(overlay_pick["currentOwner"], f"Team-{other_first}")
        self.assertTrue(overlay_pick["isTraded"])

    def test_overlay_uses_sleeper_draft_season_not_calendar_year(self):
        """Regression for the Dec→Jan boundary: when Sleeper reports
        the league/draft season as a year that differs from the
        server's calendar year, the overlay must still apply and the
        response must stamp ``season`` from Sleeper, not ``now().year``.
        Pre-fix, this filter (``season != current_year``) silently
        dropped every traded pick in that window."""
        from datetime import datetime, timezone
        wall_year = datetime.now(timezone.utc).year
        # Simulate the boundary: Sleeper reports next year's draft.
        sleeper_season = wall_year + 1
        run = self._run_overlay(sleeper_season)
        if run is None:
            self.skipTest("Workbook unavailable")
        with_overlay, without_overlay, wp, orig_first, other_first = run

        # The overlay must still flip the dollar totals, even though
        # the draft season differs from datetime.now().year.
        delta_recv = (self._team_total(with_overlay, other_first)
                      - self._team_total(without_overlay, other_first))
        self.assertGreater(delta_recv, 0,
                           "Trade overlay regressed under sleeper_season != calendar_year")
        # And the response must report the actual draft season.
        self.assertEqual(with_overlay["season"], sleeper_season)


if __name__ == "__main__":
    unittest.main()
