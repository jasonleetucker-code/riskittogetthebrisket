"""The fair-value board must not contain the price it is judged against,
and what survives must be denominated in one set of units.

Most tests here pin one of the three ways the market anchor leaked back
into a "leave-one-out" board.  All three were measured on the live
payload on 2026-08-04; the numbers in the docstrings are those
measurements, kept so a future reader can tell a regression from a
market shift.

The rest pin the failure mode that leak-hunting missed entirely: a board
can be perfectly free of the anchor's influence and still be unusable,
because the excluded source was what made the numbers comparable in the
first place.  Two row classes were affected and both were being
published as buys — see ``test_idp_is_refused_out_loud_rather_than_priced_wrong``
and ``test_the_surviving_board_is_on_one_scale``.

A note on how these tests load the pipeline, because getting it wrong
costs hours: import ``src.api.data_contract`` normally.  Loading it a
second time under another name via ``importlib.util.spec_from_file_location``
produces a half-initialised duplicate whose transitive imports still
resolve to the real module, and the resulting board differs from the
real one for reasons that have nothing to do with the code under test.
That false signal is exactly what this comment exists to prevent.
"""

from __future__ import annotations

import json
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from src.api import data_contract as dc
from src.consensus_edge import fair_value as fv

REPO = Path(__file__).resolve().parents[2]
ARCHIVE = REPO / "exports" / "archive"


def _load_latest_raw_payload() -> dict | None:
    """Newest archived raw scraper payload, or None if the archive is empty.

    These are the tracked daily export bundles.  Using a real payload
    rather than a synthetic fixture is deliberate: the leaks under test
    are properties of how 21 real sources interact, and a three-source
    fixture would pass while the live board still leaked.
    """
    if not ARCHIVE.is_dir():
        return None
    zips = sorted(ARCHIVE.glob("dynasty_export_*.zip"))
    if not zips:
        return None
    with zipfile.ZipFile(zips[-1]) as zf:
        names = [n for n in zf.namelist() if n.startswith("dynasty_data_") and n.endswith(".json")]
        if not names:
            return None
        return json.loads(zf.read(names[0]))


_RAW = _load_latest_raw_payload()
_needs_payload = unittest.skipIf(_RAW is None, "no archived export payload available")


class TestCorrelationGroups(unittest.TestCase):
    """Leak 1: a source derived from the anchor is not independent."""

    def test_expanding_the_anchor_pulls_in_its_derived_source(self):
        # fantasyNavigatorSf republishes KTC-derived values; excluding
        # ktcSfTep alone left 440 rows still carrying an FN vote.
        self.assertEqual(
            fv.expand_correlation_groups(["ktcSfTep"]),
            {"ktcSfTep", "fantasyNavigatorSf"},
        )

    def test_an_independent_source_expands_to_only_itself(self):
        # ``fantasyCalc`` is a genuinely single-board provider.
        #
        # This used to name ``dlfSf``, which stopped being true rather
        # than stopped being tested: B10-T2 declared DLF's four boards
        # (SF, rookie SF, IDP, rookie IDP) as one provider family, and
        # measured 52 players that DLF was voting on more than once.
        # The property under test is unchanged — an independent source
        # expands to itself — so it needs a source that is still one.
        self.assertEqual(dc.expand_correlation_groups(["fantasyCalc"]), {"fantasyCalc"})

    def test_a_declared_family_member_expands_to_the_whole_family(self):
        """The companion the suite lacked.

        Without it, declaring a family could quietly stop propagating and
        only the singleton case above would notice — which is the
        direction that does NOT fail closed.
        """
        self.assertEqual(
            dc.expand_correlation_groups(["dlfSf"]),
            {"dlfSf", "dlfRookieSf", "dlfIdp", "dlfRookieIdp"},
        )

    def test_an_unknown_key_passes_through_rather_than_raising(self):
        # A caller naming a retired source should get a board without it,
        # not a stack trace.
        self.assertEqual(dc.expand_correlation_groups(["retiredSource"]), {"retiredSource"})

    def test_undeclared_sources_default_to_a_singleton_group(self):
        for src in dc._RANKING_SOURCES:
            key = str(src["key"])
            if not src.get("correlation_group"):
                self.assertEqual(
                    dc.correlation_group_for(key),
                    key,
                    f"{key} should be its own group when undeclared",
                )

    def test_the_registry_surface_never_emits_a_null_group(self):
        for entry in dc.get_ranking_source_registry():
            self.assertTrue(
                entry.get("correlationGroup"),
                f"{entry.get('key')} exposed an empty correlationGroup",
            )


class TestCorrelationMetadataIsInert(unittest.TestCase):
    """The default board must not move because we added metadata.

    Correlation grouping exists for one caller.  If declaring it changed
    the live board by even one value, that would be a silent repricing of
    every user's rankings — the exact thing the repo's "preserve working
    behavior" rule forbids.
    """

    @_needs_payload
    def test_declaring_a_correlation_group_does_not_change_the_default_board(self):
        def fingerprint(contract):
            return [
                (r.get("displayName"), r.get("rankDerivedValue"), r.get("canonicalConsensusRank"))
                for r in (contract.get("playersArray") or [])
            ]

        with_groups = fingerprint(dc.build_api_data_contract(_RAW))

        stripped = []
        for src in dc._RANKING_SOURCES:
            copy = dict(src)
            copy.pop("correlation_group", None)
            stripped.append(copy)

        with mock.patch.object(dc, "_RANKING_SOURCES", stripped):
            without_groups = fingerprint(dc.build_api_data_contract(_RAW))

        self.assertEqual(
            with_groups,
            without_groups,
            "correlation-group metadata changed the default board; it must be inert there",
        )


class TestRookieLadderLeak(unittest.TestCase):
    """Leak 2: the rookie ladder is built from the anchor's own ranks.

    ``dlfRookieSf`` / ``flockFantasySfRookies`` inherit KTC's SCALE by
    crosswalking through a ladder of KTC's live rookie ranks.  The ladder
    pass already guards on ``ref_key not in active_keys``, so excluding
    KTC skips it — this test exists because that guard is load-bearing
    for a KTC-free board and nothing else pins it.
    """

    @_needs_payload
    def test_no_surviving_ladder_translation_routes_through_the_excluded_anchor(self):
        contract = fv.leave_one_out_board(_RAW, exclude=["ktcSfTep"])
        via_anchor = []
        for row in contract.get("playersArray") or []:
            for src_key, meta in (row.get("sourceRankMeta") or {}).items():
                if not isinstance(meta, dict):
                    continue
                method = str(meta.get("method") or "")
                if "ladder_translation" in method and "ktcSfTep" in method:
                    via_anchor.append((row.get("displayName"), src_key, method))
        self.assertEqual(
            via_anchor,
            [],
            "rookie rows were still scaled through the excluded anchor's ladder",
        )

    @_needs_payload
    def test_the_excluded_anchor_casts_no_vote_anywhere(self):
        contract = fv.leave_one_out_board(_RAW, exclude=["ktcSfTep"])
        for row in contract.get("playersArray") or []:
            ranks = row.get("sourceRanks") or {}
            self.assertNotIn("ktcSfTep", ranks, f"{row.get('displayName')} still has a KTC vote")
            self.assertNotIn(
                "fantasyNavigatorSf",
                ranks,
                f"{row.get('displayName')} still has a KTC-derived FN vote",
            )


class TestNoBoardIsPulledTowardAMarketAnchor(unittest.TestCase):
    """Leak 3, and it is now closed by construction rather than by a flag.

    The original requirement: a fair-value board must never be pulled back
    toward the price it is about to be compared against. The old
    market-corridor clamp read its anchor out of ``canonicalSiteValues``
    rather than out of the vote, so *dropping* a source from the blend did
    not stop the clamp pulling values toward it — measured 2026-08-04:
    with ``idpTradeCalc`` excluded, 101 IDP rows were still clamped toward
    idpTradeCalc, mean shift 552 points. Hence the opt-in suppression.

    The clamp is gone (#794/#795/#796). Nothing in the contract pipeline
    reads a market anchor or moves a value toward one, so the requirement
    now holds on EVERY board unconditionally, and these tests assert that
    rather than asserting the flag still works.

    The previous versions of these tests asserted that the default board
    *does* clamp. That was true and is now false — deliberately. They are
    re-decided here from measured evidence, not deleted: the corridor
    fired on 0 of 6 victims across every injected anomaly class once the
    anomalies were injected at the source CSVs instead of into the
    post-blend value, so nothing it was protecting is lost.
    """

    @_needs_payload
    def test_no_row_on_any_board_is_clamped_toward_an_anchor(self):
        for label, contract in (
            ("default", dc.build_api_data_contract(_RAW)),
            ("fair-value", fv.leave_one_out_board(_RAW, exclude=["idpTradeCalc"])),
        ):
            clamped = [
                r
                for r in contract.get("playersArray") or []
                if (r.get("marketCorridorClamp") or {}).get("applied")
            ]
            self.assertEqual(
                [r.get("displayName") for r in clamped],
                [],
                f"{label} board carried a corridor clamp; the mechanism was removed",
            )

    @_needs_payload
    def test_suppression_no_longer_changes_a_single_value(self):
        """The flag survives for its caller, but it cannot move a number.

        It now suppresses only the integrity DIAGNOSTIC. If suppressing it
        ever changes a value again, something value-moving has been
        reattached to that flag.
        """
        default = dc.build_api_data_contract(_RAW)
        suppressed = dc.build_api_data_contract(_RAW, suppress_market_corridor_clamp=True)

        def values(contract):
            return {
                str(r.get("displayName")): r.get("rankDerivedValue")
                for r in contract.get("playersArray") or []
            }

        self.assertEqual(values(default), values(suppressed))


class TestFairValueIndex(unittest.TestCase):
    """Routing, provenance, and honest absence."""

    @_needs_payload
    def test_each_row_is_priced_by_the_board_that_excluded_its_own_anchor(self):
        index = fv.fair_value_index(_RAW)
        for entry in index.values():
            anchor = entry.get("anchorKey")
            if not anchor:
                continue
            self.assertIn(
                anchor,
                entry["excludedSources"],
                f"{entry['displayName']} was priced by a board that still contained {anchor}",
            )

    @_needs_payload
    def test_picks_get_no_market_value_and_say_why(self):
        index = fv.fair_value_index(_RAW)
        picks = [e for e in index.values() if e.get("assetClass") == "pick"]
        self.assertGreater(len(picks), 0, "expected pick rows in the payload")
        for entry in picks:
            self.assertIsNone(entry["marketValue"])
            self.assertEqual(entry["unpricedReason"], fv.UNPRICED_NO_ANCHOR)

    @_needs_payload
    def test_an_unpriced_row_always_carries_a_reason(self):
        index = fv.fair_value_index(_RAW)
        for entry in index.values():
            if entry["fairValue"] is None or entry["marketValue"] is None:
                self.assertTrue(
                    entry["unpricedReason"],
                    f"{entry['displayName']} is unpriced with no reason given",
                )

    @_needs_payload
    def test_a_priced_row_never_carries_a_reason(self):
        index = fv.fair_value_index(_RAW)
        for entry in index.values():
            if entry["fairValue"] is not None and entry["marketValue"] is not None:
                self.assertIsNone(entry["unpricedReason"])

    @_needs_payload
    def test_coverage_accounts_for_every_row(self):
        """Rows reconcile exactly; reason counts may exceed them.

        This asserted `pricedRows + sum(unpricedByReason) == totalRows`,
        which silently required every unpriced row to carry exactly ONE
        reason — and that requirement is what hid rows losing two
        dependencies at once. The row identity is `pricedRows +
        unpricedRows`; the reason counts are a separate tally that
        over-counts by design.
        """
        index = fv.fair_value_index(_RAW)
        cov = fv.coverage(index)
        self.assertEqual(cov["totalRows"], len(index))
        self.assertEqual(cov["pricedRows"] + cov["unpricedRows"], len(index))
        self.assertGreaterEqual(sum(cov["unpricedByReason"].values()), cov["unpricedRows"])
        self.assertGreater(cov["pricedRows"], 0)
        self.assertGreater(cov["pricedByAssetClass"].get("offense", 0), 0)

    @_needs_payload
    def test_rows_that_lost_two_dependencies_are_counted_under_both(self):
        # The defect: `coverage` counted the singular headline reason, so
        # every row that lost the rookie ladder AND the IDP backbone was
        # invisible under the rookie one.
        index = fv.fair_value_index(_RAW)
        both = [e for e in index.values() if len(e.get("unpricedReasons") or []) > 1]
        self.assertTrue(both, "expected rookie-IDP rows carrying two causes")
        cov = fv.coverage(index)
        self.assertGreaterEqual(
            cov["unpricedByReason"].get(fv.UNPRICED_SCALE_ROOKIE_LADDER, 0),
            len(both),
            "rows losing both dependencies are missing from the rookie-ladder count",
        )
        # And the over-count is exactly the double-counted rows.
        self.assertEqual(
            sum(cov["unpricedByReason"].values()) - cov["unpricedRows"],
            sum(len(e["unpricedReasons"]) - 1 for e in both),
        )

    @_needs_payload
    def test_the_plural_always_contains_the_singular(self):
        index = fv.fair_value_index(_RAW)
        for entry in index.values():
            single = entry.get("unpricedReason")
            plural = entry.get("unpricedReasons") or []
            if single:
                self.assertIn(single, plural, entry["playerKey"])
            else:
                self.assertEqual(plural, [], entry["playerKey"])

    def test_idp_is_refused_out_loud_rather_than_priced_wrong(self):
        # This assertion used to read ``pricedByAssetClass["idp"] > 0``,
        # on the reasoning that an IDP league whose defenders all fell
        # out is the failure mode that made finder.py silently
        # offense-only for months. That reasoning is right and the
        # assertion was wrong: IDP rows WERE being priced, on a scale
        # that does not exist.
        #
        # ``idpTradeCalc`` builds the shared-market ladder that lifts the
        # three IDP-only boards' within-class ordinal (``dlfIdp``,
        # ``idpShow``, ``fantasyProsIdp``, all flagged
        # ``needs_shared_market_translation``) into the combined
        # offense+IDP rank space. The leave-one-out board excludes it by
        # construction, so those votes fall back to the untranslated rank
        # and IDP #1 scores as asset #1. Measured on the 2026-08-03
        # payload: 220 IDP rows, median LOO/base ratio 1.224, range 0.45x
        # to 3.48x.
        #
        # This comment used to say ``position_idp`` sources lost a
        # within-DL/LB/DB crosswalk. No registered source has that scope
        # and no row on the live board carries that stamp; the branch is
        # dead. The assertions below were right throughout — only the
        # stated reason was wrong.
        #
        # So the invariant that matters is not "IDP is priced" — it is
        # "IDP is never SILENTLY absent". Every IDP row must still be in
        # the index, and each must name the dependency that failed.
        index = fv.fair_value_index(_RAW)
        idp = [e for e in index.values() if e.get("assetClass") == "idp"]
        self.assertGreater(len(idp), 50, "IDP rows vanished from the index entirely")
        for entry in idp:
            self.assertIsNone(entry["fairValue"], entry["playerKey"])
            self.assertEqual(entry["unpricedReason"], fv.UNPRICED_SCALE_IDP_BACKBONE)
            self.assertTrue((entry.get("scaleIntegrity") or {}).get("lost"))

    def test_the_surviving_board_is_on_one_scale(self):
        # The guard's whole purpose, stated as a measurement rather than
        # as a list of excluded keys: whatever survives must be a board
        # whose values mean the same thing. A leave-one-out value differs
        # from the default board's by the weight of one vote — a few
        # percent — and anything near 2x is a broken denominator, not a
        # strong opinion.
        default = dc.build_api_data_contract(_RAW)
        base = {fv._row_key(r): r for r in default["playersArray"] if fv._row_key(r)}
        ratios = []
        for key, entry in fv.fair_value_index(_RAW).items():
            fair = entry.get("fairValue")
            row = base.get(key) or {}
            baseline = row.get("rankDerivedValue")
            if not fair or not isinstance(baseline, (int, float)) or baseline <= 0:
                continue
            ratios.append((fair / float(baseline), key))
        self.assertGreater(len(ratios), 200, "too few priced rows to judge scale")
        worst_ratio, worst_key = max(ratios)
        self.assertLess(
            worst_ratio,
            1.35,
            f"{worst_key} is {worst_ratio:.2f}x the default board — the anchor-free "
            f"board is not denominated in the same units as the board it is "
            f"compared against",
        )

    @_needs_payload
    def test_the_fair_value_actually_differs_from_the_market(self):
        # If these were near-identical the whole exercise would be
        # measuring noise.  Measured 2026-08-04: excluding ktcSfTep moved
        # 541 of 808 rows, mean absolute delta 27, max 1692.
        index = fv.fair_value_index(_RAW)
        moved = [
            e
            for e in index.values()
            if e["fairValue"] and e["marketValue"] and abs(e["fairValue"] - e["marketValue"]) > 1
        ]
        self.assertGreater(len(moved), 50, "fair value tracks the market too closely to be useful")


class TestAnchorParity(unittest.TestCase):
    """One definition of "which source is the market" across the repo.

    Was a THREE-way parity check. ``data_contract`` no longer defines an
    anchor map at all: it existed only for the market-corridor clamp,
    which was removed (#794/#795/#796) because the anchor was itself a
    voter in the blend it corrected. The two remaining definitions are
    genuine consumers — mispricing signal and league-adjusted values —
    and they still have to agree with each other.
    """

    def test_the_contract_no_longer_defines_a_market_anchor(self):
        """The removal is asserted, not merely no longer checked.

        A deleted parity leg is indistinguishable from a forgotten one
        unless something pins the deletion.
        """
        self.assertFalse(
            hasattr(dc, "_MARKET_ANCHOR_BY_ASSET_CLASS"),
            "the contract pipeline re-grew a market anchor; if that is "
            "deliberate, this parity check needs its third leg back",
        )
        self.assertFalse(hasattr(dc, "_apply_market_corridor_clamp"))

    def test_anchor_map_matches_league_intel(self):
        from src.league_intel import values as li_values

        self.assertEqual(
            fv.MARKET_ANCHOR_BY_ASSET_CLASS,
            li_values.MARKET_ANCHOR_BY_ASSET_CLASS,
        )


if __name__ == "__main__":
    unittest.main()


class TestTheGuardIsACapabilityNotAFlag(unittest.TestCase):
    """`is_backbone` is a label, and a label can be granted by an edit.

    `scale_integrity_lost` gates the IDP refusal on "does any surviving
    overall_idp source carry is_backbone". Four shipped documents used to
    describe that as a feature — "registering a second cross-market IDP
    source lifts the refusal automatically" — and recommend it as the
    forward path. It is the opposite of a feature:

    * A second cross-market IDP source is ALREADY registered
      (`draftSharksIdp`, is_cross_market=True) and the refusal correctly
      does not lift, because the gate is `is_backbone`.
    * `build_backbone_from_rows` seeds its ladder from ONE registry key,
      so a backbone needs a source whose own value column spans offense
      AND IDP. `idpTradeCalc` is the only one (529 positive offense +
      258 positive IDP). `draftSharksIdp` has ZERO positive offense
      values under its key — its offense half is the separate
      `draftSharks` key — so promoting it produces the identity ladder,
      which is exactly the fallback.
    * So the one-line edit those docs recommend lifts the guard and
      leaves the board bit-for-bit broken: median 1.224, max 3.478,
      Caleb Banks still 3.48x.

    These tests pin that the MEASURED gate holds where the declared one
    folds. They are the reason `shared_market_crosswalk_failed` exists.
    """

    @_needs_payload
    def test_the_declared_gate_can_be_satisfied_by_an_edit(self):
        # Not a bug being asserted as correct — this is the hazard, pinned
        # so that anyone who changes the declaration sees what it does not
        # buy them.
        patched = []
        for src in dc._RANKING_SOURCES:
            copy = dict(src)
            if copy["key"] == "draftSharksIdp":
                copy["is_backbone"] = True
            patched.append(copy)
        with mock.patch.object(dc, "_RANKING_SOURCES", patched):
            declared = dc.scale_integrity_lost(["idpTradeCalc"])
        self.assertEqual(
            declared["assetClasses"],
            {},
            "the registry gate no longer lifts on this edit — if that is deliberate, "
            "this test should be rewritten rather than deleted",
        )

    @_needs_payload
    def test_but_the_board_still_reports_the_crosswalk_as_failed(self):
        patched = []
        for src in dc._RANKING_SOURCES:
            copy = dict(src)
            if copy["key"] == "draftSharksIdp":
                copy["is_backbone"] = True
            patched.append(copy)
        with mock.patch.object(dc, "_RANKING_SOURCES", patched):
            board = fv.leave_one_out_board(_RAW, exclude=["idpTradeCalc"])
            failed = dc.shared_market_crosswalk_failed(board.get("playersArray") or [])
        self.assertTrue(
            failed,
            "promoting a source with no offense values produced a working ladder — "
            "if a real second backbone was registered, re-measure before trusting this",
        )
        self.assertIn("idpShow", failed)

    @_needs_payload
    def test_and_the_refusal_therefore_holds(self):
        # The property that actually protects a user: the flag edit must
        # not put IDP rows back on the board.
        patched = []
        for src in dc._RANKING_SOURCES:
            copy = dict(src)
            if copy["key"] == "draftSharksIdp":
                copy["is_backbone"] = True
            patched.append(copy)
        with mock.patch.object(dc, "_RANKING_SOURCES", patched):
            index = fv.fair_value_index(_RAW)
        idp_priced = [
            e for e in index.values() if e.get("assetClass") == "idp" and e.get("fairValue")
        ]
        self.assertEqual(
            idp_priced,
            [],
            "a registry flag edit put IDP rows back on the board without repairing the scale",
        )

    @_needs_payload
    def test_the_default_board_translates_cleanly(self):
        # The probe must not cry wolf: with idpTradeCalc present, every
        # crosswalk-dependent source is translated.
        contract = dc.build_api_data_contract(_RAW)
        self.assertEqual(dc.shared_market_crosswalk_failed(contract.get("playersArray") or []), {})

    @_needs_payload
    def test_the_anchor_free_board_reports_which_sources_fell_back(self):
        board = fv.leave_one_out_board(_RAW, exclude=["idpTradeCalc"])
        failed = dc.shared_market_crosswalk_failed(board.get("playersArray") or [])
        self.assertEqual(sorted(failed), ["dlfIdp", "fantasyProsIdp", "idpShow"])


class TestBothScaleFailuresAreNamed(unittest.TestCase):
    """A row can lose two dependencies; the payload must say so.

    A rookie IDP row loses the shared-market crosswalk AND its rookie
    ladder — `dlfRookieIdp` is paired with `idpTradeCalc` in
    `ROOKIE_LADDER_PAIRS`. The reason field tested the asset class first
    and stopped, so Caleb Banks, the worst row on the board at 3.48x,
    was stamped with the smaller of his two causes. Scoring was never
    affected (both paths refuse); the label was, and the label is what a
    person debugging this reads.
    """

    @_needs_payload
    def test_a_row_with_two_broken_dependencies_lists_both(self):
        index = fv.fair_value_index(_RAW)
        both = [
            e
            for e in index.values()
            if len((e.get("scaleIntegrity") or {}).get("reasons") or []) > 1
        ]
        self.assertTrue(both, "no row reported two causes — expected the rookie IDP overlap")
        for entry in both:
            self.assertEqual(
                sorted(entry["scaleIntegrity"]["reasons"]),
                sorted({fv.UNPRICED_SCALE_IDP_BACKBONE, fv.UNPRICED_SCALE_ROOKIE_LADDER}),
                entry["playerKey"],
            )

    @_needs_payload
    def test_the_headline_reason_is_still_one_of_the_reasons(self):
        # `unpricedReason` stays a scalar for every existing consumer.
        index = fv.fair_value_index(_RAW)
        for entry in index.values():
            integrity = entry.get("scaleIntegrity") or {}
            if not integrity.get("lost"):
                continue
            self.assertIn(integrity["reason"], integrity["reasons"])
            self.assertEqual(entry["unpricedReason"], integrity["reason"])
