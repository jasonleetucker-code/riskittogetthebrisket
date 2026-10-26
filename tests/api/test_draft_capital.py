"""Tests for the draft capital pipeline.

The Draft Data workbook is the authoritative source for pick values
(Q45:Q116) and the slot→original-owner standings (O30:R42).  Pick
ownership is overlaid live from Sleeper's ``/traded_picks`` API; the
workbook's R45:R116 column is the fallback when Sleeper is
unreachable.  Tests that need to assert workbook-only behavior pass
``apply_sleeper_trades=False``.

Every test that drives ``_fetch_draft_capital`` runs against a HERMETIC
``dynasty_main`` league (``_dynasty_main_league``): the suite's conftest
configures no league at all, and since the canonical rookie-auction reader
(draft valuation Batches E/F) prices only a configured league's upcoming
class, these tests used to get ``draft_dollars_unavailable`` and SKIP — 15 of
them, silently, on every run.  The harness maps the stubbed Sleeper league to
``dynasty_main`` and models the league as it really is between drafts: this
season's rookie draft complete and its picks rostered, so the workbook class
is NEXT season's (the upcoming class), and the slot map comes from the
completed draft.  An error from the builder is now a FAILURE, not a skip.
"""

from __future__ import annotations

import io
import json
import sys
import unittest
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

TEST_LEAGUE = "TEST_LEAGUE"
ROUNDS = 6


def _load():
    import server

    return server._parse_draft_data()


def _players(rid: int) -> list[str]:
    return [f"p{rid}_{k}" for k in range(ROUNDS)]


def _retire(url_map: dict, season: int, rids) -> None:
    """Make draft ``D1`` (season ``season``) a COMPLETE rookie draft whose picks
    are all on rosters — the canonical "retired class" evidence
    (``pick_lifecycle``: completion AND roster consumption).  The upcoming
    class is then ``season + 1``."""
    for d in url_map["/drafts"]:
        if d["draft_id"] == "D1":
            assert int(d["season"]) == int(season)
            d["status"] = "complete"
            d["settings"] = {"rounds": ROUNDS, "player_type": 1}
    for r in url_map["/rosters"]:
        if int(r["roster_id"]) in set(rids):
            r["players"] = _players(int(r["roster_id"]))
    picks = [
        {"player_id": p, "metadata": {"years_exp": "0"}}
        for rid in sorted(rids)
        for p in _players(rid)
    ]
    # Inserted FIRST: the stub matches by substring in insertion order, and
    # "/draft/D1" would otherwise answer ".../draft/D1/picks".
    rest = dict(url_map)
    url_map.clear()
    url_map["/draft/D1/picks"] = picks
    url_map.update(rest)


def _stub_urlopen(url_to_payload):
    """A urllib.request.urlopen stub.  ``url_to_payload`` maps a URL substring
    to a payload; the special key ``"__LEAGUE_META__"`` answers the bare
    ``/v1/league/{id}`` endpoint (no trailing resource)."""
    meta_payload = url_to_payload.get("__LEAGUE_META__")
    substring_map = {k: v for k, v in url_to_payload.items() if k != "__LEAGUE_META__"}

    def fake_urlopen(url, *args, **kwargs):
        target = url.full_url if hasattr(url, "full_url") else str(url)
        # League meta = "/v1/league/{id}" with no trailing path
        # segment.  A normal "/v1/league/{id}/rosters" URL has at
        # least one trailing segment, which is how we distinguish.
        tail = target.split("/v1/league/", 1)[-1] if "/v1/league/" in target else ""
        if meta_payload is not None and "/v1/league/" in target and "/" not in tail:
            return io.BytesIO(json.dumps(meta_payload).encode())
        for key, payload in substring_map.items():
            if key in target:
                return io.BytesIO(json.dumps(payload).encode())
        raise AssertionError(f"unexpected urlopen({target})")

    return fake_urlopen


@contextmanager
def _dynasty_main_league(url_map, parsed=None):
    """Drive ``_fetch_draft_capital`` hermetically for a stubbed Sleeper league
    registered as ``dynasty_main`` (no live Sleeper, no live KTC, no stored
    draft-class evidence)."""
    import server
    import src.api.draft_class_evidence as dce

    with ExitStack() as stack:
        stack.enter_context(patch.object(server.urllib.request, "urlopen", _stub_urlopen(url_map)))
        stack.enter_context(
            patch.object(server, "_sleeper_league_id_for_draft", return_value=TEST_LEAGUE)
        )
        stack.enter_context(
            patch.object(
                server._league_registry,
                "league_key_for_sleeper_id",
                side_effect=lambda lid: "dynasty_main" if lid == TEST_LEAGUE else None,
            )
        )
        stack.enter_context(patch.object(dce, "read_snapshot", return_value=None))
        stack.enter_context(patch.object(server, "_our_rookie_pool", return_value=[]))
        stack.enter_context(patch.object(server, "_get_ktc_rookies", return_value=[]))
        if parsed is not None:
            stack.enter_context(patch.object(server, "_parse_draft_data", return_value=parsed))
        yield server


def _plain_league(season: int) -> dict:
    """The workbook's 12 teams as a Sleeper league whose ``season`` rookie draft
    is complete and rostered (the upcoming class is ``season + 1``), no trades."""
    _, _, slot_to_original, _, _, _ = _load()
    rids = [int(s) for s in slot_to_original]
    url_map = {
        "/rosters": [{"roster_id": rid, "owner_id": f"u{rid}"} for rid in rids],
        "/users": [
            {"user_id": f"u{int(s)}", "display_name": f"Team-{fn}", "metadata": {}}
            for s, fn in slot_to_original.items()
        ],
        "/drafts": [{"draft_id": "D1", "season": season}],
        "/traded_picks": [],
        "/draft/D1": {"slot_to_roster_id": {str(rid): rid for rid in rids}},
        "__LEAGUE_META__": {"season": str(season)},
    }
    _retire(url_map, season, rids)
    return url_map


def _hermetic_fetch(*, apply_sleeper_trades: bool):
    season = datetime.now(timezone.utc).year
    with _dynasty_main_league(_plain_league(season)) as server:
        result = server._fetch_draft_capital(apply_sleeper_trades=apply_sleeper_trades)
    assert "error" not in result, result
    assert result["season"] == season + 1, result.get("season")
    return result


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


class TestApiOutput(unittest.TestCase):
    def test_api_values_are_whole_dollars_with_half_dollar_reference(self):
        """Owner decision 2026-10-18 — whole dollars only.  Every published
        pick dollar is an integer from the canonical whole-dollar step; the
        workbook's half-dollar L2:L73 figure travels beside it as reference
        data (an integer multiple of 0.5), and the published value is never
        more than a dollar from it."""
        result = _hermetic_fetch(apply_sleeper_trades=False)
        self.assertEqual(sum(p["dollarValue"] for p in result["picks"]), 1200)
        for p in result["picks"]:
            v = p["dollarValue"]
            self.assertIsInstance(v, int, f"{p['pick']}: {v!r} is not a whole dollar")
            self.assertEqual(p["adjustedDollarValue"], v)
            ref = p["workbookReferenceDollarValue"]
            self.assertAlmostEqual(ref * 2, round(ref * 2), places=6)
            self.assertLess(abs(v - ref), 1, f"{p['pick']}: {v} vs reference {ref}")
        # The 72-pick class's receipt is the SERVED record's (Batch F): the
        # whole-dollar step lives in ``validation.apportionment``.  The flat
        # ``total`` / ``floored`` / ``residual`` shape this test used to read
        # belongs to ``workbook_class_whole_dollars``, which now serves only a
        # workbook of another size (census row 10, still pinned by
        # ``test_draft_capital_all_years.py``).
        validation = result["wholeDollarAllocation"]["validation"]
        receipt = validation["apportionment"]
        self.assertEqual(receipt["total"], 1200)
        self.assertEqual(receipt["flooredSum"] + receipt["residual"], 1200)
        self.assertEqual(receipt["finalWholeDollars"], [p["dollarValue"] for p in result["picks"]])
        self.assertEqual(validation["verifier"]["result"], "pass")

    def test_api_total_budget_1200(self):
        result = _hermetic_fetch(apply_sleeper_trades=False)
        self.assertEqual(result["totalBudget"], 1200)

    def test_api_team_totals_sum_to_1200(self):
        result = _hermetic_fetch(apply_sleeper_trades=False)
        total = sum(t["auctionDollars"] for t in result["teamTotals"])
        self.assertEqual(total, 1200, f"Team total sum = {total}")


class TestTeamTotalsMirrorSheet(unittest.TestCase):
    """The pipeline must mirror the sheet: accumulating R45:R116
    ownership against Q45:Q116 values must equal the authoritative
    per-owner decimals in T63:U74 (reference data), and the API's integer
    totals must be the exact sums of each team's whole-dollar picks."""

    def test_decimal_totals_match_sheet_per_owner(self):
        from collections import defaultdict

        _, workbook_picks, _, wb_team_totals, _, _ = _load()
        computed = defaultdict(float)
        for wp in workbook_picks:
            computed[wp["owner"]] += wp["value"]
        for owner, total in computed.items():
            self.assertAlmostEqual(
                total,
                wb_team_totals.get(owner, 0.0),
                places=2,
                msg=f"{owner}: computed={total}, sheet={wb_team_totals.get(owner)}",
            )

    def test_api_team_totals_are_exact_sums_of_owned_whole_dollar_picks(self):
        """Owner decision 2026-10-18: each team's budget is an integer equal to
        the EXACT sum of the whole-dollar picks it owns — never rounded on its
        own — and the budgets total $1,200.

        Pinned to ``apply_sleeper_trades=False`` so the workbook's R45:R116
        ownership column is the sole owner-of-record."""
        from collections import defaultdict

        result = _hermetic_fetch(apply_sleeper_trades=False)
        owned = defaultdict(int)
        for p in result["picks"]:
            owned[p["currentOwner"]] += p["dollarValue"]
        for t in result["teamTotals"]:
            self.assertIsInstance(t["auctionDollars"], int)
            self.assertEqual(t["auctionDollars"], owned.get(t["team"], 0), t["team"])
        self.assertEqual(sum(t["auctionDollars"] for t in result["teamTotals"]), 1200)


class TestSleeperTradeOverlay(unittest.TestCase):
    """Ownership in the workbook (R45:R116) is hand-edited and lags
    real-time trades.  ``_fetch_draft_capital`` overlays Sleeper's
    ``/traded_picks`` so dollars-per-team reflect the current
    Sleeper roster ownership without waiting for a commissioner edit.
    """

    def _stub_urlopen(self, url_to_payload):
        """See the module-level ``_stub_urlopen``."""
        return _stub_urlopen(url_to_payload)

    def _build_overlay_fixture(
        self,
        draft_season,
        *,
        league_meta_season=None,
        drafts_seasons=None,
        traded_pick_season=None,
        retired=False,
    ):
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
            entry.  Defaults to ``draft_season`` (``draft_season + 1``
            when ``retired``: the upcoming class is the one traded).
        ``retired`` — ``draft_season``'s rookie draft is complete and its
            picks rostered, so the workbook class is ``draft_season + 1``
            (the league as it really is between drafts).
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
                (n for s, n in slot_to_original.items() if s != wp["pick"] and n != orig),
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
            users.append(
                {
                    "user_id": owner_uid,
                    "display_name": f"Team-{first_name}",
                    "metadata": {},
                }
            )
            slot_to_roster[str(slot)] = rid
            roster_id_for_first[first_name] = rid

        if drafts_seasons is None:
            drafts_seasons = [draft_season]
        if traded_pick_season is None:
            traded_pick_season = draft_season + 1 if retired else draft_season
        if league_meta_season is None:
            league_meta_season = draft_season

        drafts = [{"draft_id": f"D{i}", "season": s} for i, s in enumerate(drafts_seasons, start=1)]
        draft_detail = {"slot_to_roster_id": slot_to_roster}
        traded_picks = [
            {
                "season": traded_pick_season,
                "round": wp["round"],
                "roster_id": roster_id_for_first[orig_first],
                "owner_id": roster_id_for_first[other_first],
                "previous_owner_id": roster_id_for_first[orig_first],
            }
        ]
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
        if retired:
            _retire(url_map, draft_season, [int(r["roster_id"]) for r in rosters])
        return url_map, wp, orig_first, other_first

    def _run_overlay(self, draft_season, **fixture_kwargs):
        """Drive ``_fetch_draft_capital`` with mocked Sleeper responses
        for ``draft_season``.  Extra kwargs are forwarded to
        ``_build_overlay_fixture`` (e.g. ``league_meta_season``,
        ``drafts_seasons``, ``traded_pick_season``).  Returns
        (with_overlay_result, without_overlay_result, wp,
        orig_first, other_first) or None if the workbook is
        unavailable.  A builder error FAILS the test (hermetic
        ``dynasty_main`` league — nothing environmental is left to skip on)."""
        fixture = self._build_overlay_fixture(draft_season, **fixture_kwargs)
        if fixture is None:
            return None
        url_map, wp, orig_first, other_first = fixture
        with _dynasty_main_league(url_map) as server:
            with_overlay = server._fetch_draft_capital(apply_sleeper_trades=True)
            without_overlay = server._fetch_draft_capital(apply_sleeper_trades=False)
        self.assertNotIn("error", with_overlay, with_overlay)
        self.assertNotIn("error", without_overlay, without_overlay)
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
        decrease — independent of whatever R45:R116 says.

        The league as it is between drafts: this season's rookie draft is
        complete and rostered, the workbook prices NEXT season's class, and
        the traded pick is in that class."""
        season = datetime.now(timezone.utc).year
        run = self._run_overlay(season, retired=True)
        if run is None:
            self.skipTest("Workbook unavailable")
        with_overlay, without_overlay, wp, orig_first, other_first = run

        delta_recv = self._team_total(with_overlay, other_first) - self._team_total(
            without_overlay, other_first
        )
        delta_orig = self._team_total(with_overlay, orig_first) - self._team_total(
            without_overlay, orig_first
        )
        self.assertGreater(delta_recv, 0, f"Receiving team did not gain dollars: {delta_recv}")
        self.assertLess(delta_orig, 0, f"Original owner did not lose dollars: {delta_orig}")

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

        active = datetime.now(timezone.utc).year + 1  # active pick season
        prior = active - 1  # last completed draft
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
        self.assertEqual(
            with_overlay["season"],
            active,
            "Response season must follow league meta, not drafts max",
        )
        # Overlay must not apply incorrectly: per-team totals must be
        # bit-identical between with/without when the active-season
        # slot map is unavailable.
        with_totals = sorted((t["team"], t["auctionDollars"]) for t in with_overlay["teamTotals"])
        without_totals = sorted(
            (t["team"], t["auctionDollars"]) for t in without_overlay["teamTotals"]
        )
        self.assertEqual(
            with_totals, without_totals, "Overlay shifted dollars using a cross-year slot map"
        )
        # And teamTotals must not contain duplicate logical teams
        # (e.g. a Sleeper "Russini Panini" row at $0 plus a workbook
        # "Jason" row at $XX).  Codex P1 round 4: when the first-name
        # → team-name bridge is empty (no active-season draft),
        # pre-seeding Sleeper team names while the picks loop emits
        # raw first names produced doubled rows.  The teamTotals
        # length must equal the unique team count from the workbook.
        team_names = {row["team"] for row in with_overlay["teamTotals"]}
        self.assertEqual(
            len(with_overlay["teamTotals"]),
            len(team_names),
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
        delta_recv = self._team_total(with_overlay, other_first) - self._team_total(
            without_overlay, other_first
        )
        self.assertGreater(
            delta_recv, 0, "Trade overlay regressed under sleeper_season != calendar_year"
        )
        # And the response must report the actual draft season.
        self.assertEqual(with_overlay["season"], sleeper_season)


def _reverse_standings():
    """Standings where roster 12 is worst and roster 1 best — by RECORD first
    (the league's rule, ``reverse_record_lower_pf``) with Points For agreeing,
    so the rule puts roster r in slot 13 - r."""
    fpts = {rid: (13 - rid) * 100 for rid in range(1, 13)}
    records = {rid: (12 - rid, rid - 1, 0) for rid in range(1, 13)}
    return fpts, records


class TestLiveStandingsOverride(unittest.TestCase):
    """Mid-season standings reshuffle of the upcoming class's slots.

    The reshuffle follows THE league draft-order rule
    (``src/public_league/draft_order.py``, ``reverse_record_lower_pf``: worst
    record first, ties on record by LOWER Points For) via
    ``draft_capital_order.class_slot_order`` since draft valuation Batch E.
    The PF-only ordering this class was written against ("fewest fpts → slot
    1") is RETIRED; the rule itself is pinned by
    ``tests/api/test_draft_capital_multi_year.py``
    (``test_standings_to_date_are_a_labelled_forecast_by_the_owner_rule``,
    ``test_verified_final_standings_are_the_rules_order``).  What this class
    still owns is the slot-BRIDGE consistency every reshuffle must keep, so its
    fixture now supplies records (``_reverse_standings``) and a completed,
    rostered draft for the current season (the workbook class is the next).
    Validates that every slot-derived field stays consistent under the
    override:

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

    def _build_fixture(
        self,
        draft_season,
        *,
        fpts_by_rid,
        trades=None,
        empty_draft_detail=False,
        drop_slots_from_draft_detail=None,
        remap_slot_keys=None,
        extra_unbridged_rosters=None,
        records_by_rid=None,
    ):
        """Mocked Sleeper fixture with explicit per-roster standings so the
        live-standings override fires.

        ``fpts_by_rid`` maps roster_id (1..N) → integer fpts and
        ``records_by_rid`` → ``(wins, losses, ties)`` (default 0-0-0).
        The league rule needs a record for every bridged roster; no game
        played (all zero) keeps the existing order.  ``draft_season``'s
        rookie draft is complete and rostered, so the workbook class —
        and every ``trades`` entry — is ``draft_season + 1``.
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
        ``(rid, fpts)`` or ``(rid, fpts, (wins, losses, ties))`` tuples to append to ``/rosters`` WITHOUT
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
            wins, losses, ties = (records_by_rid or {}).get(rid, (0, 0, 0))
            settings = {
                "fpts": int(fpts_by_rid.get(rid, 0)),
                "fpts_decimal": 0,
                "wins": wins,
                "losses": losses,
                "ties": ties,
            }
            rosters.append(
                {
                    "roster_id": rid,
                    "owner_id": owner_uid,
                    "settings": settings,
                }
            )
            users.append(
                {
                    "user_id": owner_uid,
                    "display_name": f"Team-{first_name}",
                    "metadata": {},
                }
            )
            slot_to_roster[str(slot)] = rid
            first_name_by_rid[rid] = first_name

        # Append any "extra" Sleeper rosters that the workbook
        # doesn't bridge.  These get a real /rosters entry (so they
        # show up in roster_fppts) but are intentionally absent
        # from the slot_to_roster_id draft map.
        for extra in extra_unbridged_rosters or ():
            rid, fpts = extra[0], extra[1]
            wins, losses, ties = extra[2] if len(extra) > 2 else (0, 0, 0)
            owner_uid = f"u{rid}"
            rosters.append(
                {
                    "roster_id": int(rid),
                    "owner_id": owner_uid,
                    "settings": {
                        "fpts": int(fpts),
                        "fpts_decimal": 0,
                        "wins": wins,
                        "losses": losses,
                        "ties": ties,
                    },
                }
            )
            users.append(
                {
                    "user_id": owner_uid,
                    "display_name": f"Extra-{rid}",
                    "metadata": {},
                }
            )

        drafts = [{"draft_id": "D1", "season": draft_season}]
        if empty_draft_detail:
            draft_detail: dict[str, object] = {}
        else:
            partial_map = dict(slot_to_roster)
            for s in drop_slots_from_draft_detail or ():
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
        for t in trades or []:
            traded_picks_payload.append(
                {
                    "season": draft_season + 1,
                    "round": t["round"],
                    "roster_id": t["original_rid"],
                    "owner_id": t["new_rid"],
                    "previous_owner_id": t["original_rid"],
                }
            )

        url_map: dict[str, object] = {
            "/rosters": rosters,
            "/users": users,
            "/drafts": drafts,
            "/traded_picks": traded_picks_payload,
            "/draft/D1": draft_detail,
            "__LEAGUE_META__": {"season": str(draft_season)},
        }
        _retire(url_map, draft_season, [int(s) for s in slot_to_original])
        return url_map, workbook_picks, slot_to_original, first_name_by_rid

    def _run(self, draft_season, **fixture_kwargs):
        fixture = self._build_fixture(draft_season, **fixture_kwargs)
        if fixture is None:
            return None
        url_map, workbook_picks, slot_to_original, first_name_by_rid = fixture
        with _dynasty_main_league(url_map) as server:
            result = server._fetch_draft_capital(apply_sleeper_trades=True)
        self.assertNotIn("error", result, result)
        self.assertEqual(result["season"], draft_season + 1)
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
        fpts, records = _reverse_standings()
        run = self._run(season, fpts_by_rid=fpts, records_by_rid=records, trades=[])
        if run is None:
            self.skipTest("Workbook unavailable")
        result, workbook_picks, slot_to_original, first_name_by_rid = run

        # With no trades at all, every pick must report
        # originalOwner == currentOwner (regardless of which slot
        # the live reshuffle moved each team to).
        misflagged = [
            p for p in result["picks"] if p["originalOwner"] != p["currentOwner"] or p["isTraded"]
        ]
        self.assertEqual(
            misflagged, [], "Untraded picks were flagged as traded after live-standings reshuffle"
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
        fpts, records = _reverse_standings()
        # Trade: roster 1's round-1 pick goes to roster 5.  After
        # the reshuffle, roster 1 has the MOST points so it occupies
        # workbook slot 12; roster 12 has the FEWEST and occupies
        # slot 1; roster 5 sits in slot 8.  Recipient is roster 5
        # (not roster 12) so the assertions discriminate pre-fix
        # behavior — pre-fix keyed the override at the historical
        # slot 1, which post-reshuffle is roster 12's pick, leaving
        # both slot 1 and slot 12 with wrong currentOwners.
        trades = [{"round": 1, "original_rid": 1, "new_rid": 5}]
        run = self._run(season, fpts_by_rid=fpts, records_by_rid=records, trades=trades)
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

        with _dynasty_main_league(url_map) as server:
            result = server._fetch_draft_capital(apply_sleeper_trades=True)
        self.assertNotIn("error", result, result)

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
        fpts, records = _reverse_standings()
        # Inject one "extra" Sleeper roster (rid 99) with the
        # absolute fewest points so it would otherwise be sorted
        # into live-slot 1 and break the bridge.
        run = self._run(
            season,
            fpts_by_rid=fpts,
            records_by_rid=records,
            trades=[],
            extra_unbridged_rosters=[(99, 1, (0, 11, 0))],
        )
        if run is None:
            self.skipTest("Workbook unavailable")
        result, workbook_picks, slot_to_original, first_name_by_rid = run

        misflagged = [
            p for p in result["picks"] if p["originalOwner"] != p["currentOwner"] or p["isTraded"]
        ]
        self.assertEqual(
            misflagged,
            [],
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
        fpts, records = _reverse_standings()
        # Drop two slots from the draft detail to simulate a partial
        # bridge (10 of 12 workbook slots covered).
        run = self._run(
            season,
            fpts_by_rid=fpts,
            records_by_rid=records,
            trades=[],
            drop_slots_from_draft_detail=[7, 8],
        )
        if run is None:
            self.skipTest("Workbook unavailable")
        result, workbook_picks, slot_to_original, first_name_by_rid = run

        misflagged = [
            p for p in result["picks"] if p["originalOwner"] != p["currentOwner"] or p["isTraded"]
        ]
        self.assertEqual(
            misflagged,
            [],
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
        fpts, records = _reverse_standings()
        run = self._run(
            season, fpts_by_rid=fpts, records_by_rid=records, trades=[], empty_draft_detail=True
        )
        if run is None:
            self.skipTest("Workbook unavailable")
        result, workbook_picks, slot_to_original, first_name_by_rid = run

        # With slot_to_roster empty, the override must be skipped and
        # the workbook's slot ordering preserved.  Untraded picks
        # must keep originalOwner == currentOwner.
        misflagged = [
            p for p in result["picks"] if p["originalOwner"] != p["currentOwner"] or p["isTraded"]
        ]
        self.assertEqual(
            misflagged,
            [],
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
        fpts, records = _reverse_standings()
        # Same entry count (12) but slots 11 & 12 re-keyed to
        # out-of-range 101/102 so they no longer cover the workbook.
        run = self._run(
            season,
            fpts_by_rid=fpts,
            records_by_rid=records,
            trades=[],
            remap_slot_keys={11: 101, 12: 102},
        )
        if run is None:
            self.skipTest("Workbook unavailable")
        result, workbook_picks, slot_to_original, first_name_by_rid = run

        misflagged = [
            p for p in result["picks"] if p["originalOwner"] != p["currentOwner"] or p["isTraded"]
        ]
        self.assertEqual(
            misflagged,
            [],
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
        mutated = (pick_dollars, wb_picks, slot_to_original, wb_totals, rookies, pv_l)

        # Full 12-roster Sleeper fixture aligned to the (mutated)
        # slot_to_original — rid == slot, distinct display names so the
        # discriminating signal is the roster_id path, not the
        # display-string fallback.  No fpts → live override off; this
        # exercises the workbook + Sleeper-trade path where
        # first_name_to_rid was the pre-fix owner_rid source.
        rosters, users, slot_to_roster = [], [], {}
        for slot in slot_to_original:
            rid = int(slot)
            rosters.append(
                {
                    "roster_id": rid,
                    "owner_id": f"u{rid}",
                    "settings": {"fpts": 0, "fpts_decimal": 0},
                }
            )
            users.append({"user_id": f"u{rid}", "display_name": f"Team-{rid}", "metadata": {}})
            slot_to_roster[str(slot)] = rid
        keep_rid, dup_rid = int(keep_slot), int(dup_slot)
        url_map = {
            "/rosters": rosters,
            "/users": users,
            "/drafts": [{"draft_id": "D1", "season": season}],
            "/draft/D1": {"slot_to_roster_id": slot_to_roster},
            # Trade keep_slot roster's round-1 pick (upcoming class) to
            # dup_slot roster (the other roster carrying ``shared_first``).
            "/traded_picks": [
                {
                    "season": season + 1,
                    "round": 1,
                    "roster_id": keep_rid,
                    "owner_id": dup_rid,
                    "previous_owner_id": keep_rid,
                }
            ],
            "__LEAGUE_META__": {"season": str(season)},
        }
        # This season's draft is complete and rostered: the workbook class is next season's.
        _retire(url_map, season, [int(s) for s in slot_to_original])
        with _dynasty_main_league(url_map, parsed=mutated) as server:
            result = server._fetch_draft_capital(apply_sleeper_trades=True)
        self.assertNotIn("error", result, result)

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
            "Untraded pick mis-flagged traded due to duplicate-first-name " "roster_id collapse",
        )


if __name__ == "__main__":
    unittest.main()
