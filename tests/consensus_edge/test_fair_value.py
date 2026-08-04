"""The fair-value board must not contain the price it is judged against.

Every test here pins one of the three ways the market anchor leaked back
into a "leave-one-out" board.  All three were measured on the live
payload on 2026-08-04; the numbers in the docstrings are those
measurements, kept so a future reader can tell a regression from a
market shift.

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
        self.assertEqual(dc.expand_correlation_groups(["dlfSf"]), {"dlfSf"})

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


class TestCorridorClampLeak(unittest.TestCase):
    """Leak 3: the clamp anchors on the source we removed.

    ``_market_anchor_value_for_row`` reads ``canonicalSiteValues``, not
    the blend vote, so dropping a source does not stop the clamp pulling
    values back toward it.  Measured with ``idpTradeCalc`` excluded: 101
    IDP rows still clamped toward idpTradeCalc, mean shift 552 points.
    """

    @_needs_payload
    def test_the_default_board_still_clamps(self):
        contract = dc.build_api_data_contract(_RAW)
        clamped = [
            r
            for r in contract.get("playersArray") or []
            if (r.get("marketCorridorClamp") or {}).get("applied")
        ]
        self.assertGreater(
            len(clamped),
            0,
            "no rows clamped on the default board — the suppression test below proves nothing",
        )

    @_needs_payload
    def test_a_fair_value_board_is_never_clamped_toward_its_own_anchor(self):
        contract = fv.leave_one_out_board(_RAW, exclude=["idpTradeCalc"])
        clamped = [
            r
            for r in contract.get("playersArray") or []
            if (r.get("marketCorridorClamp") or {}).get("applied")
        ]
        self.assertEqual(
            [r.get("displayName") for r in clamped],
            [],
            "fair-value board was pulled back toward the price it will be compared against",
        )

    @_needs_payload
    def test_suppression_is_opt_in(self):
        default = dc.build_api_data_contract(_RAW)
        suppressed = dc.build_api_data_contract(_RAW, suppress_market_corridor_clamp=True)

        def clamped_count(contract):
            return sum(
                1
                for r in contract.get("playersArray") or []
                if (r.get("marketCorridorClamp") or {}).get("applied")
            )

        self.assertGreater(clamped_count(default), 0)
        self.assertEqual(clamped_count(suppressed), 0)


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
        index = fv.fair_value_index(_RAW)
        cov = fv.coverage(index)
        self.assertEqual(cov["totalRows"], len(index))
        self.assertEqual(cov["pricedRows"] + sum(cov["unpricedByReason"].values()), len(index))
        self.assertGreater(cov["pricedRows"], 0)
        # Both markets must be represented — an IDP league whose IDP
        # rows all fell out is the failure mode that made finder.py
        # silently offense-only for months.
        self.assertGreater(cov["pricedByAssetClass"].get("offense", 0), 0)
        self.assertGreater(cov["pricedByAssetClass"].get("idp", 0), 0)

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
    """One definition of "which source is the market" across the repo."""

    def test_anchor_map_matches_the_contract_pipeline(self):
        self.assertEqual(
            fv.MARKET_ANCHOR_BY_ASSET_CLASS,
            dc._MARKET_ANCHOR_BY_ASSET_CLASS,
        )

    def test_anchor_map_matches_league_intel(self):
        from src.league_intel import values as li_values

        self.assertEqual(
            fv.MARKET_ANCHOR_BY_ASSET_CLASS,
            li_values.MARKET_ANCHOR_BY_ASSET_CLASS,
        )


if __name__ == "__main__":
    unittest.main()
