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
        pick_dollars, _, _, _, _, _ = _load()
        self.assertEqual(len(pick_dollars), 72)

    def test_workbook_picks_parsed(self):
        _, workbook_picks, _, _, _, _ = _load()
        self.assertEqual(len(workbook_picks), 72)

    def test_pick_values_are_float(self):
        pick_dollars, _, _, _, _, _ = _load()
        for i, v in enumerate(pick_dollars):
            self.assertIsInstance(v, float, f"pick_dollars[{i}] is {type(v)}")

    def test_workbook_has_decimals(self):
        """Workbook values (97.5, 88.5 etc.) confirm xlsx is being read."""
        _, workbook_picks, _, _, _, _ = _load()
        has_decimal = any(wp["value"] % 1 != 0 for wp in workbook_picks)
        self.assertTrue(has_decimal, "No decimals — likely reading stale CSV")


class TestIntegerRounding(unittest.TestCase):

    def test_round_to_budget_sums_to_1200(self):
        import server
        _, workbook_picks, _, _, _, _ = _load()
        values = [wp["value"] for wp in workbook_picks]
        rounded = server._round_to_budget(values, 1200)
        self.assertEqual(sum(rounded), 1200,
                         f"Rounded sum = {sum(rounded)}, expected 1200")

    def test_round_to_budget_all_ints(self):
        import server
        _, workbook_picks, _, _, _, _ = _load()
        values = [wp["value"] for wp in workbook_picks]
        rounded = server._round_to_budget(values, 1200)
        for i, v in enumerate(rounded):
            self.assertIsInstance(v, int, f"rounded[{i}] is {type(v)}")

    def test_equal_inputs_round_to_equal_outputs(self):
        """``_round_to_budget`` must give equal-value inputs the same
        rounded output, both inside and outside the deficit-incremented
        block.

        The workbook's expansion-pair averaging (R1 picks 1+2 sharing a
        value, etc.) is operator-chosen and varies year-to-year — the
        prior test pinned this property indirectly via the live sheet
        and false-failed once the operator hand-edited the workbook to
        use asymmetric pick values. This synthetic version pins the
        rounding function's own invariant so it stays meaningful
        regardless of workbook content.

        Two scenarios are exercised:
          1. A high-remainder pair that sits INSIDE the +1 allocation
             block (both indices receive the deficit increment).
          2. A low-remainder pair that sits OUTSIDE the +1 allocation
             block (neither index receives it). The prior version only
             covered case 1, which let a position-dependent regression
             for later indices slip through.
        """
        import server

        # Scenario 1 — pair inside the +1 block, pair outside.
        # 72 picks: 36 with remainder 0.9 (idx 0..35, top of sort),
        # 36 with remainder 0.1 (idx 36..71, bottom of sort).
        # floors sum = 36*10 + 36*10 = 720. Pad with a flat pick value
        # so the deficit allocation lands exactly at the boundary
        # between the two remainder tiers: top 36 indices get +1.
        values = [10.9] * 36 + [10.1] * 36
        # Normalise to exactly 1200.
        deficit = 1200 - sum(values)
        values[-1] += deficit
        rounded = server._round_to_budget(values, 1200)

        # Pair at the head — both indices fall inside the +1 block.
        self.assertEqual(rounded[0], rounded[1],
                         f"head-pair: {rounded[0]} != {rounded[1]}")
        # Pair near the middle of the +1 block.
        self.assertEqual(rounded[20], rounded[21],
                         f"mid-block: {rounded[20]} != {rounded[21]}")
        # Pair outside the +1 block — equal inputs at low remainders.
        self.assertEqual(rounded[50], rounded[51],
                         f"outside-block: {rounded[50]} != {rounded[51]}")


class TestApiOutput(unittest.TestCase):

    def test_api_values_are_half_dollar_aligned(self):
        # Pick values now come from the workbook's L2:L73 column, which
        # carries half-dollar precision (R2 picks at $28.50, R5 picks
        # at $1.50, etc.).  Each value must be a number that's an
        # integer multiple of 0.5.
        import server
        result = server._fetch_draft_capital(apply_sleeper_trades=False)
        if "error" in result:
            self.skipTest(f"Unavailable: {result['error']}")
        for p in result["picks"]:
            v = p["adjustedDollarValue"]
            self.assertIsInstance(v, (int, float),
                                  f"{p['pick']}: {v} is not numeric")
            doubled = float(v) * 2
            self.assertAlmostEqual(doubled, round(doubled), places=6,
                                   msg=f"{p['pick']}: {v} not half-dollar aligned")

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
        _, workbook_picks, _, wb_team_totals, _, _ = _load()
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
        _, workbook_picks, _, _, _, _ = _load()
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
        """Build a urllib.request.urlopen stub.  ``url_to_payload`` is
        a {key: payload} dict where ``key`` is either a URL substring
        match or the special sentinel ``"__LEAGUE_META__"`` for the
        bare ``/v1/league/{id}`` endpoint (matched by checking the
        path ends in the league id with no trailing resource).
        """
        import io
        import json as _json

        meta_payload = url_to_payload.get("__LEAGUE_META__")
        substring_map = {k: v for k, v in url_to_payload.items()
                         if k != "__LEAGUE_META__"}

        def fake_urlopen(url, *args, **kwargs):
            target = url.full_url if hasattr(url, "full_url") else str(url)
            # League meta = "/v1/league/{id}" with no trailing path
            # segment.  A normal "/v1/league/{id}/rosters" URL has at
            # least one trailing segment, which is how we distinguish.
            tail = target.split("/v1/league/", 1)[-1] if "/v1/league/" in target else ""
            if meta_payload is not None and "/v1/league/" in target and "/" not in tail:
                return io.BytesIO(_json.dumps(meta_payload).encode())
            for key, payload in substring_map.items():
                if key in target:
                    return io.BytesIO(_json.dumps(payload).encode())
            raise AssertionError(f"unexpected urlopen({target})")
        return fake_urlopen

    def _build_overlay_fixture(self, draft_season, *,
                               league_meta_season=None,
                               drafts_seasons=None,
                               traded_pick_season=None):
        """Construct mocked Sleeper responses for a single traded pick.

        Returns ``(url_map, wp, orig_first, other_first)`` where ``wp``
        is the workbook pick chosen for the trade and the two first
        names identify the original / receiving team buckets.

        ``draft_season`` — convenience default used for league meta,
            drafts, and traded_picks when the more specific kwargs
            are not provided.
        ``league_meta_season`` — what ``/v1/league/{id}.season``
            reports.  Defaults to ``draft_season``.  Pass an
            explicit value (or ``False`` to drop the field) to
            simulate the league meta endpoint returning a different
            season than ``/drafts``.
        ``drafts_seasons`` — list of seasons returned by
            ``/v1/league/{id}/drafts``.  Defaults to
            ``[draft_season]``.  Use ``[older_season]`` to simulate
            the pre-rollover offseason window.
        ``traded_pick_season`` — season stamped on the traded-pick
            entry.  Defaults to ``draft_season``.
        """
        _, workbook_picks, slot_to_original, _, _, _ = _load()
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

        if drafts_seasons is None:
            drafts_seasons = [draft_season]
        if traded_pick_season is None:
            traded_pick_season = draft_season
        if league_meta_season is None:
            league_meta_season = draft_season

        drafts = [
            {"draft_id": f"D{i}", "season": s}
            for i, s in enumerate(drafts_seasons, start=1)
        ]
        draft_detail = {"slot_to_roster_id": slot_to_roster}
        traded_picks = [{
            "season": traded_pick_season,
            "round": wp["round"],
            "roster_id": roster_id_for_first[orig_first],
            "owner_id": roster_id_for_first[other_first],
            "previous_owner_id": roster_id_for_first[orig_first],
        }]
        url_map: dict[str, object] = {
            "/rosters": rosters,
            "/users": users,
            "/drafts": drafts,
            "/traded_picks": traded_picks,
        }
        # League-meta endpoint (``/v1/league/{id}`` with no trailing
        # path).  ``league_meta_season=False`` simulates the field
        # being missing so the drafts-based fallback gets exercised.
        league_meta_payload: dict[str, object] = {}
        if league_meta_season is not False and league_meta_season is not None:
            league_meta_payload["season"] = str(league_meta_season)
        # Match the bare /league/{id} URL via a longer substring than
        # the per-resource endpoints to avoid false positives.  Stub
        # comparison happens left-to-right in dict-insertion order,
        # so put the more-specific paths first.
        for did in [d["draft_id"] for d in drafts]:
            url_map[f"/draft/{did}"] = draft_detail
        url_map["__LEAGUE_META__"] = league_meta_payload
        return url_map, wp, orig_first, other_first

    def _run_overlay(self, draft_season, **fixture_kwargs):
        """Drive ``_fetch_draft_capital`` with mocked Sleeper responses
        for ``draft_season``.  Extra kwargs are forwarded to
        ``_build_overlay_fixture`` (e.g. ``league_meta_season``,
        ``drafts_seasons``, ``traded_pick_season``).  Returns
        (with_overlay_result, without_overlay_result, wp,
        orig_first, other_first) or None if the workbook is
        unavailable."""
        import server
        fixture = self._build_overlay_fixture(draft_season, **fixture_kwargs)
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

    def test_overlay_degrades_safely_when_active_season_draft_missing(self):
        """Pre-rollover offseason regression (Codex P1): a dynasty
        league has rolled to season N+1 (so ``/league/{id}.season``
        reports N+1) but the N+1 draft hasn't been created yet, so
        ``/drafts`` only has season N.  The overlay must NOT fall
        back to N's slot mapping — rookie slot order is reverse-
        standings of the PRIOR season, so it shifts year to year and
        a cross-year mapping would mis-route trades and shift dollars
        to the wrong teams.

        Required behavior in this gap:
          1. Response ``season`` is anchored on ``/league/{id}.season``
             (proves league-meta — not max(drafts) — drives it).
          2. Per-team dollar totals are identical with and without the
             overlay (proves no unsafe cross-year mapping is applied;
             we degrade to workbook ownership, which is freshly
             hand-maintained for N+1 in this window).
        """
        from datetime import datetime, timezone
        active = datetime.now(timezone.utc).year + 1   # active pick season
        prior = active - 1                              # last completed draft
        run = self._run_overlay(
            active,
            league_meta_season=active,
            drafts_seasons=[prior],
            traded_pick_season=active,
        )
        if run is None:
            self.skipTest("Workbook unavailable")
        with_overlay, without_overlay, _wp, _orig_first, _other_first = run
        # League meta drives the response season, not max(drafts).
        self.assertEqual(with_overlay["season"], active,
                         "Response season must follow league meta, not drafts max")
        # Overlay must not apply incorrectly: per-team totals must be
        # bit-identical between with/without when the active-season
        # slot map is unavailable.
        with_totals = sorted(
            (t["team"], t["auctionDollars"]) for t in with_overlay["teamTotals"]
        )
        without_totals = sorted(
            (t["team"], t["auctionDollars"]) for t in without_overlay["teamTotals"]
        )
        self.assertEqual(with_totals, without_totals,
                         "Overlay shifted dollars using a cross-year slot map")
        # And teamTotals must not contain duplicate logical teams
        # (e.g. a Sleeper "Russini Panini" row at $0 plus a workbook
        # "Jason" row at $XX).  Codex P1 round 4: when the first-name
        # → team-name bridge is empty (no active-season draft),
        # pre-seeding Sleeper team names while the picks loop emits
        # raw first names produced doubled rows.  The teamTotals
        # length must equal the unique team count from the workbook.
        team_names = {row["team"] for row in with_overlay["teamTotals"]}
        self.assertEqual(
            len(with_overlay["teamTotals"]), len(team_names),
            f"Duplicate rows in teamTotals: {with_overlay['teamTotals']}",
        )
        self.assertLessEqual(
            len(with_overlay["teamTotals"]),
            with_overlay.get("numTeams", 12),
            f"teamTotals exploded past numTeams: {with_overlay['teamTotals']}",
        )

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


class TestLiveStandingsOverride(unittest.TestCase):
    """Mid-season live-standings reshuffle: fewest fpts → slot 1,
    second-fewest → slot 2, etc.  Validates that every slot-derived
    field stays consistent under the override:

      • originalOwner follows the new mapping (the feature itself);
      • for untraded picks, currentOwner follows the same mapping
        (regression test for Codex P1 #2 — otherwise untraded picks
        get mis-flagged isTraded because only originalOwner shifted);
      • Sleeper traded_picks key to the slot the ORIGINAL roster now
        occupies post-reshuffle, not its historical workbook slot
        (regression test for Codex P1 #3 — otherwise trades land on
        the wrong slot once standings diverge from draft order).
    """

    def _stub_urlopen(self, url_to_payload):
        return TestSleeperTradeOverlay._stub_urlopen(self, url_to_payload)

    def _build_fixture(self, draft_season, *, fpts_by_rid, trades=None,
                       empty_draft_detail=False,
                       drop_slots_from_draft_detail=None,
                       remap_slot_keys=None,
                       extra_unbridged_rosters=None):
        """Mocked Sleeper fixture with explicit per-roster fpts so the
        live-standings override fires.

        ``fpts_by_rid`` maps roster_id (1..N) → integer fpts.  At
        least one entry must be > 0 to trigger the override.
        ``trades`` is an optional list of
        ``{"round": int, "original_rid": int, "new_rid": int}``
        entries that get rendered into /traded_picks.
        ``empty_draft_detail`` returns a draft payload with no
        ``slot_to_roster_id`` / ``draft_order`` keys so server-side
        ``slot_to_roster`` stays empty — simulates Sleeper's draft
        endpoint returning an unusable payload.
        ``drop_slots_from_draft_detail`` is an iterable of slot
        numbers to OMIT from the ``slot_to_roster_id`` mapping —
        simulates a partial draft payload (some slots present, some
        missing) that the Codex P1 follow-up flagged.
        ``extra_unbridged_rosters`` is an iterable of
        ``(rid, fpts)`` tuples to append to ``/rosters`` WITHOUT
        adding them to the draft slot_to_roster_id map — simulates
        the Codex regression where Sleeper exposes more rosters
        than the workbook bridges (expansion / inactive), and a
        low-scoring extra would otherwise hijack slot 1 in the
        reshuffle.

        Returns ``(url_map, workbook_picks, slot_to_original,
        first_name_by_rid)`` or None when the workbook is
        unavailable.
        """
        _, workbook_picks, slot_to_original, _, _, _ = _load()
        if not workbook_picks or not slot_to_original:
            return None

        rosters, users = [], []
        slot_to_roster: dict[str, int] = {}
        first_name_by_rid: dict[int, str] = {}
        for slot, first_name in slot_to_original.items():
            rid = int(slot)
            owner_uid = f"u{rid}"
            settings = {
                "fpts": int(fpts_by_rid.get(rid, 0)),
                "fpts_decimal": 0,
            }
            rosters.append({
                "roster_id": rid,
                "owner_id": owner_uid,
                "settings": settings,
            })
            users.append({
                "user_id": owner_uid,
                "display_name": f"Team-{first_name}",
                "metadata": {},
            })
            slot_to_roster[str(slot)] = rid
            first_name_by_rid[rid] = first_name

        # Append any "extra" Sleeper rosters that the workbook
        # doesn't bridge.  These get a real /rosters entry (so they
        # show up in roster_fppts) but are intentionally absent
        # from the slot_to_roster_id draft map.
        for rid, fpts in (extra_unbridged_rosters or ()):
            owner_uid = f"u{rid}"
            rosters.append({
                "roster_id": int(rid),
                "owner_id": owner_uid,
                "settings": {"fpts": int(fpts), "fpts_decimal": 0},
            })
            users.append({
                "user_id": owner_uid,
                "display_name": f"Extra-{rid}",
                "metadata": {},
            })

        drafts = [{"draft_id": "D1", "season": draft_season}]
        if empty_draft_detail:
            draft_detail: dict[str, object] = {}
        else:
            partial_map = dict(slot_to_roster)
            for s in (drop_slots_from_draft_detail or ()):
                partial_map.pop(str(s), None)
            # ``remap_slot_keys`` rewrites slot KEYS to out-of-range
            # values WITHOUT changing the entry count — simulates
            # Sleeper returning a full-size slot_to_roster_id map that
            # nonetheless doesn't cover the workbook's slot set (Codex
            # P1: a count-only gate would still activate here).
            for old_s, new_s in (remap_slot_keys or {}).items():
                if str(old_s) in partial_map:
                    partial_map[str(new_s)] = partial_map.pop(str(old_s))
            draft_detail = {"slot_to_roster_id": partial_map}
        traded_picks_payload = []
        for t in (trades or []):
            traded_picks_payload.append({
                "season": draft_season,
                "round": t["round"],
                "roster_id": t["original_rid"],
                "owner_id": t["new_rid"],
                "previous_owner_id": t["original_rid"],
            })

        url_map: dict[str, object] = {
            "/rosters": rosters,
            "/users": users,
            "/drafts": drafts,
            "/traded_picks": traded_picks_payload,
            "/draft/D1": draft_detail,
            "__LEAGUE_META__": {"season": str(draft_season)},
        }
        return url_map, workbook_picks, slot_to_original, first_name_by_rid

    def _run(self, draft_season, **fixture_kwargs):
        import server
        fixture = self._build_fixture(draft_season, **fixture_kwargs)
        if fixture is None:
            return None
        url_map, workbook_picks, slot_to_original, first_name_by_rid = fixture
        with patch.object(server.urllib.request, "urlopen",
                          self._stub_urlopen(url_map)), \
             patch.object(server, "_sleeper_league_id_for_draft",
                          return_value="TEST_LEAGUE"):
            result = server._fetch_draft_capital(apply_sleeper_trades=True)
        if "error" in result:
            return None
        return result, workbook_picks, slot_to_original, first_name_by_rid

    def test_untraded_pick_does_not_get_misflagged_isTraded(self):
        """Codex P1: when standings reshuffle the slot order, an
        untraded pick must keep originalOwner == currentOwner.  Pre-
        fix, currentOwner stayed bound to the workbook's
        pre-reshuffle slot owner while originalOwner shifted, so
        every untraded pick read ``isTraded: true`` mid-season.
        """
        from datetime import datetime, timezone
        season = datetime.now(timezone.utc).year
        # Reverse the standings: roster 12 fewest points → slot 1,
        # roster 11 next → slot 2, ..., roster 1 most → slot 12.
        fpts = {rid: (13 - rid) * 100 for rid in range(1, 13)}
        run = self._run(season, fpts_by_rid=fpts, trades=[])
        if run is None:
            self.skipTest("Workbook unavailable")
        result, workbook_picks, slot_to_original, first_name_by_rid = run

        # With no trades at all, every pick must report
        # originalOwner == currentOwner (regardless of which slot
        # the live reshuffle moved each team to).
        misflagged = [
            p for p in result["picks"]
            if p["originalOwner"] != p["currentOwner"] or p["isTraded"]
        ]
        self.assertEqual(
            misflagged, [],
            "Untraded picks were flagged as traded after live-standings reshuffle"
        )

    def test_traded_pick_follows_original_roster_to_its_new_slot(self):
        """Codex P1: Sleeper traded_picks must key to the slot the
        original roster occupies AFTER the live-standings reshuffle.
        Pre-fix, the override map used the historical draft slot, so
        a trade by roster X (workbook slot 5) landed on whatever
        roster the reshuffle now placed in slot 5 — corrupting an
        unrelated pick's currentOwner and leaving X's actual pick
        untouched.
        """
        from datetime import datetime, timezone
        season = datetime.now(timezone.utc).year
        # Same reversed standings: rid r → slot (13 - r).
        fpts = {rid: (13 - rid) * 100 for rid in range(1, 13)}
        # Trade: roster 1's round-1 pick goes to roster 5.  After
        # the reshuffle, roster 1 has the MOST points so it occupies
        # workbook slot 12; roster 12 has the FEWEST and occupies
        # slot 1; roster 5 sits in slot 8.  Recipient is roster 5
        # (not roster 12) so the assertions discriminate pre-fix
        # behavior — pre-fix keyed the override at the historical
        # slot 1, which post-reshuffle is roster 12's pick, leaving
        # both slot 1 and slot 12 with wrong currentOwners.
        trades = [{"round": 1, "original_rid": 1, "new_rid": 5}]
        run = self._run(season, fpts_by_rid=fpts, trades=trades)
        if run is None:
            self.skipTest("Workbook unavailable")
        result, workbook_picks, slot_to_original, first_name_by_rid = run

        rid_1_team = f"Team-{first_name_by_rid[1]}"
        rid_5_team = f"Team-{first_name_by_rid[5]}"
        rid_12_team = f"Team-{first_name_by_rid[12]}"

        # Roster 1's pick lands at slot 12 after the reshuffle:
        # originalOwner = Team-1, currentOwner = Team-5, isTraded.
        # Pre-fix this row would have shown currentOwner = Team-12
        # (workbook static for slot 12, no override applied) because
        # the override mis-keyed to slot 1.
        traded_pick = next(
            (p for p in result["picks"] if p["pick"] == "1.12"),
            None,
        )
        self.assertIsNotNone(traded_pick, "Expected pick 1.12 in result")
        self.assertEqual(traded_pick["originalOwner"], rid_1_team)
        self.assertEqual(traded_pick["currentOwner"], rid_5_team)
        self.assertTrue(traded_pick["isTraded"])

        # Slot 1 (now occupied by roster 12) had NO trade, so it
        # must read as untraded with currentOwner = Team-12.  Pre-
        # fix the misapplied override would have set currentOwner =
        # Team-5 (the new owner from roster 1's trade), corrupting
        # this unrelated pick.
        slot1_pick = next(
            (p for p in result["picks"] if p["pick"] == "1.01"),
            None,
        )
        self.assertIsNotNone(slot1_pick, "Expected pick 1.01 in result")
        self.assertEqual(slot1_pick["originalOwner"], rid_12_team)
        self.assertEqual(slot1_pick["currentOwner"], rid_12_team)
        self.assertFalse(slot1_pick["isTraded"])


    def test_traded_pick_detected_when_two_rosters_share_display_name(self):
        """Codex P2: ``isTraded`` must use stable roster_ids, not the
        rendered display names.  Sleeper doesn't enforce unique
        ``team_name`` / ``display_name``, and a display-only compare
        would silently mark a real trade as untraded when both rosters
        render to the same string.
        """
        from datetime import datetime, timezone
        season = datetime.now(timezone.utc).year
        # No fpts → live override doesn't fire; this exercises the
        # workbook + Sleeper trade overlay path where the display-only
        # comparison was the pre-fix isTraded source.
        fpts = {rid: 0 for rid in range(1, 13)}
        # Trade roster 1's R1 pick to roster 12; we'll force their
        # display_names to match below by monkeypatching the fixture.
        trades = [{"round": 1, "original_rid": 1, "new_rid": 12}]

        # Build the fixture, then collapse both rosters' display_name
        # onto a single shared string to simulate the duplicate-name
        # regression.
        fixture = self._build_fixture(season, fpts_by_rid=fpts, trades=trades)
        if fixture is None:
            self.skipTest("Workbook unavailable")
        url_map, workbook_picks, slot_to_original, first_name_by_rid = fixture
        shared_label = "Duplicate Team Name"
        for user in url_map["/users"]:
            if user["user_id"] in ("u1", "u12"):
                user["display_name"] = shared_label

        import server
        with patch.object(server.urllib.request, "urlopen",
                          self._stub_urlopen(url_map)), \
             patch.object(server, "_sleeper_league_id_for_draft",
                          return_value="TEST_LEAGUE"):
            result = server._fetch_draft_capital(apply_sleeper_trades=True)
        if "error" in result:
            self.skipTest(f"Unavailable: {result['error']}")

        # The pick at roster 1's slot (workbook slot 1, since live
        # override is off) should report the trade.  Both sides now
        # render to ``shared_label``, but the roster_ids differ —
        # post-fix isTraded must still be True.
        traded_pick = next(
            (p for p in result["picks"] if p["pick"] == "1.01"),
            None,
        )
        self.assertIsNotNone(traded_pick, "Expected pick 1.01 in result")
        self.assertEqual(traded_pick["originalOwner"], shared_label)
        self.assertEqual(traded_pick["currentOwner"], shared_label)
        self.assertTrue(
            traded_pick["isTraded"],
            "Trade between two rosters with the same display name must "
            "still be reported isTraded=True (compare roster_ids, not strings)",
        )

    def test_live_override_excludes_unbridged_extra_rosters(self):
        """Codex P1 follow-up: when Sleeper exposes more rosters
        than the workbook bridges (expansion / inactive rosters
        with their own fpts), the live-fpts sort must NOT pull
        those unbridged rosters into ``effective_slot_to_rid``.
        Pre-fix, the reshuffle source set was all of
        ``roster_fppts`` and a low-scoring extra would land in
        slot 1 with no ``roster_id_to_first_name`` entry,
        triggering the same isTraded false-positive as the
        partial-bridge case.  The reshuffle must be restricted to
        roster IDs in ``slot_to_roster``.
        """
        from datetime import datetime, timezone
        season = datetime.now(timezone.utc).year
        # All 12 workbook rosters have meaningful fpts.
        fpts = {rid: (13 - rid) * 100 for rid in range(1, 13)}
        # Inject one "extra" Sleeper roster (rid 99) with the
        # absolute fewest points so it would otherwise be sorted
        # into live-slot 1 and break the bridge.
        run = self._run(
            season,
            fpts_by_rid=fpts,
            trades=[],
            extra_unbridged_rosters=[(99, 1)],
        )
        if run is None:
            self.skipTest("Workbook unavailable")
        result, workbook_picks, slot_to_original, first_name_by_rid = run

        misflagged = [
            p for p in result["picks"]
            if p["originalOwner"] != p["currentOwner"] or p["isTraded"]
        ]
        self.assertEqual(
            misflagged, [],
            "Untraded picks were flagged traded when Sleeper exposed extra "
            "unbridged rosters (live reshuffle must restrict to bridged rids)",
        )
        # And the extra roster's display name must never appear as an
        # originalOwner — confirms rid 99 didn't sneak into the
        # slot assignment.
        owners = {p["originalOwner"] for p in result["picks"]}
        self.assertNotIn("Extra-99", owners)

    def test_live_override_skipped_on_partial_slot_to_roster(self):
        """Codex P1 follow-up: a partial draft payload (some slots
        missing from ``slot_to_roster_id``) leaves
        ``roster_id_to_first_name`` incomplete, so any slot whose
        roster isn't in the join stays unmapped at owner-remap time.
        Pre-fix that produced ``isTraded: true`` for every untraded
        pick at the missing slots — the override must be gated on a
        COMPLETE bridge, not just a non-empty one.
        """
        from datetime import datetime, timezone
        season = datetime.now(timezone.utc).year
        fpts = {rid: (13 - rid) * 100 for rid in range(1, 13)}
        # Drop two slots from the draft detail to simulate a partial
        # bridge (10 of 12 workbook slots covered).
        run = self._run(season, fpts_by_rid=fpts, trades=[],
                        drop_slots_from_draft_detail=[7, 8])
        if run is None:
            self.skipTest("Workbook unavailable")
        result, workbook_picks, slot_to_original, first_name_by_rid = run

        misflagged = [
            p for p in result["picks"]
            if p["originalOwner"] != p["currentOwner"] or p["isTraded"]
        ]
        self.assertEqual(
            misflagged, [],
            "Untraded picks were flagged traded under partial slot_to_roster "
            "coverage (live-standings override should require complete bridge)",
        )

    def test_live_override_skipped_when_slot_to_roster_empty(self):
        """Codex P1: when live fpts data is present but Sleeper's
        ``/draft/{id}`` endpoint returns an empty payload (no
        ``slot_to_roster_id`` / ``draft_order``), the
        live-standings override must NOT fire.  Without the slot↔
        roster bridge, ``roster_id_to_first_name`` stays empty and
        the picks loop can't remap ``owner_first`` to match the
        reshuffled origin — every untraded pick would otherwise
        read ``isTraded: true``.  Falling back to the workbook
        ordering in that case preserves correctness.
        """
        from datetime import datetime, timezone
        season = datetime.now(timezone.utc).year
        fpts = {rid: (13 - rid) * 100 for rid in range(1, 13)}
        run = self._run(season, fpts_by_rid=fpts, trades=[],
                        empty_draft_detail=True)
        if run is None:
            self.skipTest("Workbook unavailable")
        result, workbook_picks, slot_to_original, first_name_by_rid = run

        # With slot_to_roster empty, the override must be skipped and
        # the workbook's slot ordering preserved.  Untraded picks
        # must keep originalOwner == currentOwner.
        misflagged = [
            p for p in result["picks"]
            if p["originalOwner"] != p["currentOwner"] or p["isTraded"]
        ]
        self.assertEqual(
            misflagged, [],
            "Untraded picks were flagged traded when slot_to_roster was empty "
            "(live-standings override should have been gated off)",
        )

    def test_live_override_skipped_when_slot_keys_dont_cover_workbook(self):
        """Codex P1 follow-up: a full-size ``slot_to_roster_id`` whose
        KEYS don't cover the workbook slot set must not enable the
        override.  Pre-fix the gate only compared counts
        (``len(slot_to_roster) >= len(slot_to_original)``), so a
        12-entry map keyed e.g. 1..10,101,102 against a 1..12 workbook
        passed the gate while workbook slots 11/12 had no roster
        bridge — leaving roster_id_to_first_name incomplete and
        producing rows where originalOwner (live) != currentOwner
        (stale workbook) on untraded picks.  The gate now requires
        the workbook slot set to be a subset of the bridged slot
        keys; partial coverage falls back to the workbook ordering.
        """
        from datetime import datetime, timezone
        season = datetime.now(timezone.utc).year
        fpts = {rid: (13 - rid) * 100 for rid in range(1, 13)}
        # Same entry count (12) but slots 11 & 12 re-keyed to
        # out-of-range 101/102 so they no longer cover the workbook.
        run = self._run(season, fpts_by_rid=fpts, trades=[],
                        remap_slot_keys={11: 101, 12: 102})
        if run is None:
            self.skipTest("Workbook unavailable")
        result, workbook_picks, slot_to_original, first_name_by_rid = run

        misflagged = [
            p for p in result["picks"]
            if p["originalOwner"] != p["currentOwner"] or p["isTraded"]
        ]
        self.assertEqual(
            misflagged, [],
            "Untraded picks mis-flagged when slot_to_roster keys did not "
            "cover the workbook slot set (count-only gate regression)",
        )

    def test_isTraded_correct_when_two_rosters_share_workbook_first_name(self):
        """Codex P1 (#8): two rosters carrying the same workbook first
        name must not collapse through ``first_name_to_rid``.

        Synthesises a 2-slot workbook where BOTH slots' owner first
        name is ``"Mike"`` so the prior ``first_name_to_rid.setdefault``
        kept only roster 1.  A Sleeper trade moves roster 1's R1 pick
        to roster 2 (the other "Mike").

        Pre-fix failure modes this locks out:
          • the traded 1.01 pick resolved owner_rid via the collapsed
            name map → roster 1 → ``isTraded`` False (real trade
            silently hidden);
          • the untraded 1.02 pick (roster 2) resolved owner_rid to
            roster 1 → ``isTraded`` True (untraded pick mis-flagged).

        Post-fix: the Sleeper override carries the new owner's
        roster_id directly and the untraded baseline owner_rid is the
        slot's own roster, so neither path touches the ambiguous name
        map.
        """
        from datetime import datetime, timezone
        import copy
        import server

        season = datetime.now(timezone.utc).year
        base = server._parse_draft_data()
        if not base or not base[1] or not base[2]:
            self.skipTest("Workbook unavailable")
        pick_dollars, wb_picks, slot_to_original, wb_totals, rookies, pv_l = base

        # Pick two real slots and force slot ``dup_slot``'s owner first
        # name to equal slot ``keep_slot``'s, so the workbook now has a
        # genuine duplicate first name across two distinct rosters.
        slots_sorted = sorted(slot_to_original)
        keep_slot, dup_slot = slots_sorted[0], slots_sorted[1]
        shared_first = slot_to_original[keep_slot]

        slot_to_original = dict(slot_to_original)
        slot_to_original[dup_slot] = shared_first
        wb_picks = copy.deepcopy(wb_picks)
        for p in wb_picks:
            if p["pick"] == dup_slot:
                p["owner"] = shared_first
        mutated = (pick_dollars, wb_picks, slot_to_original,
                   wb_totals, rookies, pv_l)

        # Full 12-roster Sleeper fixture aligned to the (mutated)
        # slot_to_original — rid == slot, distinct display names so the
        # discriminating signal is the roster_id path, not the
        # display-string fallback.  No fpts → live override off; this
        # exercises the workbook + Sleeper-trade path where
        # first_name_to_rid was the pre-fix owner_rid source.
        rosters, users, slot_to_roster = [], [], {}
        for slot in slot_to_original:
            rid = int(slot)
            rosters.append({"roster_id": rid, "owner_id": f"u{rid}",
                             "settings": {"fpts": 0, "fpts_decimal": 0}})
            users.append({"user_id": f"u{rid}",
                          "display_name": f"Team-{rid}", "metadata": {}})
            slot_to_roster[str(slot)] = rid
        keep_rid, dup_rid = int(keep_slot), int(dup_slot)
        url_map = {
            "/rosters": rosters,
            "/users": users,
            "/drafts": [{"draft_id": "D1", "season": season}],
            "/draft/D1": {"slot_to_roster_id": slot_to_roster},
            # Trade keep_slot roster's round-1 pick to dup_slot roster
            # (the other roster carrying ``shared_first``).
            "/traded_picks": [
                {
                    "season": season,
                    "round": 1,
                    "roster_id": keep_rid,
                    "owner_id": dup_rid,
                    "previous_owner_id": keep_rid,
                }
            ],
            "__LEAGUE_META__": {"season": str(season)},
        }
        with patch.object(server, "_parse_draft_data", return_value=mutated), \
             patch.object(server.urllib.request, "urlopen",
                          self._stub_urlopen(url_map)), \
             patch.object(server, "_sleeper_league_id_for_draft",
                          return_value="TEST_LEAGUE"):
            result = server._fetch_draft_capital(apply_sleeper_trades=True)
        if "error" in result:
            self.skipTest(f"Unavailable: {result['error']}")

        by_pick = {p["pick"]: p for p in result["picks"]}
        keep_pick = f"1.{str(keep_slot).zfill(2)}"
        dup_pick = f"1.{str(dup_slot).zfill(2)}"
        self.assertIn(keep_pick, by_pick)
        self.assertIn(dup_pick, by_pick)
        # keep_slot's R1 pick was traded to dup_slot's roster — must be
        # flagged even though both rosters' workbook first name matches.
        self.assertTrue(
            by_pick[keep_pick]["isTraded"],
            "Sleeper-traded pick hidden because both rosters share the "
            "workbook first name (first_name_to_rid collapse)",
        )
        # dup_slot's own R1 pick was NOT traded — must stay unflagged.
        self.assertFalse(
            by_pick[dup_pick]["isTraded"],
            "Untraded pick mis-flagged traded due to duplicate-first-name "
            "roster_id collapse",
        )


if __name__ == "__main__":
    unittest.main()
