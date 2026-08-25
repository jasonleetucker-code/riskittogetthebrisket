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

import statistics
import unittest
from pathlib import Path
from unittest import mock

from src.api import data_contract as dc
from src.consensus_edge import fair_value as fv
from tests.archive_fixtures import newest_complete_raw_payload

REPO = Path(__file__).resolve().parents[2]
ARCHIVE = REPO / "exports" / "archive"


def _load_latest_raw_payload() -> dict | None:
    """Newest archived raw scraper payload, or None if the archive is empty.

    These are the tracked daily export bundles.  Using a real payload
    rather than a synthetic fixture is deliberate: the leaks under test
    are properties of how 21 real sources interact, and a three-source
    fixture would pass while the live board still leaked.
    """
    # The newest COMPLETE scrape, not simply the newest: a single
    # timed-out source produces a bundle whose thin board fails these
    # assertions for a data reason (2026-08-16).  See
    # ``tests/archive_fixtures``.
    raw, _archive = newest_complete_raw_payload()
    return raw


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


class TestCorrelationMetadataDrivesTheBlendExactly(unittest.TestCase):
    """Was ``TestCorrelationMetadataIsInert``.

    That class asserted the default board must NOT move because we added
    correlation metadata — true while grouping existed only for
    leave-one-out and Consensus Edge, and it is what made B10-T2's
    declaration safely reviewable.

    B10-T3b deliberately ends that. The declaration now drives the blend:
    each family casts one vote, published by its highest-precedence
    member. "The board does not move" is no longer the property to
    protect.

    What replaces it is stricter — the board must move by EXACTLY the
    family collapse and nothing else. Two propagation routes are
    legitimate and are stated rather than excluded silently:

    * **Picks inherit.** Current-year slot picks are tethered to the
      merged rookie pool (Phase 5.2b), so a pick moves when the rookies
      move even though its own source list has no duplicated family.
      Measured: 66 of the 71 non-local changes are picks, every one of
      them single-source on ``idpTradeCalc``.
    * **The rank-800 boundary.** ``OVERALL_RANK_LIMIT`` truncates value
      as well as rank, so a row can cross into or out of pricing. Those
      rows have no *before* source list to classify. Measured: the other
      5, and each one's post-change source list does carry a duplicated
      family (Jam Miller holds ``ktcSfTep`` + ``fantasyNavigatorSf`` and
      both Flock boards).

    Anything outside those two is a side effect riding along with the
    intended change, which is what the inertness test was really for.
    """

    @staticmethod
    def _stripped_registry():
        out = []
        for src in dc._RANKING_SOURCES:
            copy = dict(src)
            copy.pop("correlation_group", None)
            out.append(copy)
        return out

    @_needs_payload
    def test_declaring_families_moves_the_board(self):
        """If this passes trivially, T3b is not wired in at all."""

        def values(contract):
            return {
                r.get("displayName"): r.get("rankDerivedValue")
                for r in (contract.get("playersArray") or [])
            }

        with_groups = values(dc.build_api_data_contract(_RAW))
        with mock.patch.object(dc, "_RANKING_SOURCES", self._stripped_registry()):
            without_groups = values(dc.build_api_data_contract(_RAW))

        changed = [
            n for n, v in with_groups.items() if n in without_groups and without_groups[n] != v
        ]
        self.assertTrue(changed, "declaring families changed nothing")

    @_needs_payload
    def test_every_changed_player_had_a_family_voting_twice(self):
        """Players only — picks inherit, see the class docstring."""

        def rows(contract):
            return {r.get("displayName"): r for r in (contract.get("playersArray") or [])}

        after = rows(dc.build_api_data_contract(_RAW))
        with mock.patch.object(dc, "_RANKING_SOURCES", self._stripped_registry()):
            before = rows(dc.build_api_data_contract(_RAW))

        offenders = []
        for name, arow in after.items():
            brow = before.get(name)
            if brow is None:
                continue
            bv, av = brow.get("rankDerivedValue"), arow.get("rankDerivedValue")
            if bv == av:
                continue
            if not isinstance(bv, int) or not isinstance(av, int):
                # A PRICING-STATE change, not a value move: OVERALL_RANK_LIMIT
                # truncates value as well as rank, so a row crosses in or out
                # of pricing when the rows ABOVE it reorder. Its own sources
                # need not have changed at all. Counted separately below.
                continue
            if (arow.get("assetClass") or "") == "pick":
                continue  # tethered to the rookie pool
            keys = set(brow.get("sourceRanks") or {}) | set(arow.get("sourceRanks") or {})
            groups = [dc.correlation_group_for(k) for k in keys]
            if len(set(groups)) == len(groups):
                offenders.append((name, sorted(keys)))

        self.assertEqual(
            offenders,
            [],
            "player rows moved with no duplicated provider family — the collapse "
            "is doing something beyond removing duplicate family votes",
        )

    @_needs_payload
    def test_the_rank_limit_boundary_swaps_rather_than_loses_rows(self):
        """Rows crossing OVERALL_RANK_LIMIT must balance.

        A net loss would mean the collapse is dropping coverage rather
        than reordering it — the reduced evidence base pushing rows off
        the board instead of merely re-ranking them.
        """

        def priced(contract):
            return {
                r.get("displayName")
                for r in (contract.get("playersArray") or [])
                if isinstance(r.get("rankDerivedValue"), int)
            }

        after = priced(dc.build_api_data_contract(_RAW))
        with mock.patch.object(dc, "_RANKING_SOURCES", self._stripped_registry()):
            before = priced(dc.build_api_data_contract(_RAW))

        self.assertEqual(
            len(after),
            len(before),
            f"priced count changed: {len(before)} -> {len(after)} "
            f"(entered {sorted(after - before)}, left {sorted(before - after)})",
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
    def test_multi_reason_rows_are_counted_under_every_reason(self):
        """RE-DECIDED for C7 — the arithmetic is pinned, the fixture is not.

        The defect this guards is real and unchanged: ``coverage`` counted the
        singular headline reason, so a row that lost the rookie ladder AND the
        IDP backbone was invisible under the rookie one.

        What changed is that the anchor-free board no longer PRODUCES such a
        row. Losing ``idpTradeCalc`` used to cost the shared-market scale as
        well as the rookie ladder; Draft Sharks now carries the scale, so only
        the rookie dependency is lost and the overlap is empty. Requiring the
        overlap to be non-empty would now be asserting that the repair did not
        happen, so the count identity is asserted unconditionally instead —
        it holds whether or not any row currently carries two reasons, and it
        still fails the moment ``coverage`` goes back to counting one.
        """
        index = fv.fair_value_index(_RAW)
        both = [e for e in index.values() if len(e.get("unpricedReasons") or []) > 1]
        cov = fv.coverage(index)
        for entry in both:
            for reason in entry["unpricedReasons"]:
                self.assertGreaterEqual(
                    cov["unpricedByReason"].get(reason, 0),
                    1,
                    f"{entry['playerKey']}: reason {reason} is missing from the census",
                )
        self.assertEqual(
            sum(cov["unpricedByReason"].values()) - cov["unpricedRows"],
            sum(len(e["unpricedReasons"]) - 1 for e in both),
            "the census over-count must be exactly the multi-reason rows",
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

    def test_idp_is_priced_because_a_second_bridge_survives(self):
        """RE-DECIDED for C7. The assertion inverts; the invariant does not.

        History, because it is the whole argument. This test first asserted
        ``pricedByAssetClass["idp"] > 0`` on the reasoning that an IDP league
        whose defenders all fall out is the failure mode that made
        ``finder.py`` silently offense-only for months. That reasoning was
        right and the assertion was wrong: IDP rows WERE priced, on a scale
        that did not exist. It was then inverted to require refusal, because
        refusing was the only honest option available — ``idpTradeCalc`` was
        the sole source able to seed the shared-market ladder, and the
        leave-one-out board excludes the anchor by construction.

        That is no longer true. Draft Sharks is a qualified bridge, so an
        anchor-free board still has a working cross-position scale, and
        refusing would now discard evidence rather than protect anyone.

        The invariant that survived every version is the one asserted here:
        **IDP is never SILENTLY absent.** A row is priced on a scale that
        exists, or it names the dependency that failed.
        """
        index = fv.fair_value_index(_RAW)
        idp = [e for e in index.values() if e.get("assetClass") == "idp"]
        self.assertGreater(len(idp), 50, "IDP rows vanished from the index entirely")

        priced = [e for e in idp if e.get("fairValue")]
        self.assertGreater(
            len(priced),
            0,
            "no IDP row was priced — the surviving bridge is not carrying the scale",
        )
        for entry in idp:
            if entry.get("fairValue"):
                self.assertFalse(
                    (entry.get("scaleIntegrity") or {}).get("lost"),
                    f"{entry['playerKey']}: priced on a scale reported lost",
                )
            else:
                self.assertTrue(
                    entry.get("unpricedReason"),
                    f"{entry['playerKey']}: unpriced without naming a reason",
                )

    def test_the_surviving_board_is_on_one_scale(self):
        """Units, not opinions — and C7 forces the two to be separated.

        The guard's purpose is that whatever survives is denominated in the
        same units as the board it is compared against. That used to be
        expressible as a single worst-case bound of 1.35x, because IDP was
        refused outright and every priced row was offense.

        Now IDP is priced, and IDP is where the bridges genuinely disagree —
        Draft Sharks and IDP Trade Calculator differ by roughly 3x on elite
        DL and reverse on LB. An anchor-free board that drops one of them
        therefore moves individual defenders a long way on the STRENGTH OF AN
        OPINION, which is not a broken denominator. Measured here: median
        ratio 0.995 across 585 priced rows, with the extreme a linebacker
        Draft Sharks ranks near the top of its board and IDP Trade Calculator
        does not.

        So the bound is asserted where it means units — the central tendency,
        and the offense rows whose anchors did not change — and the tail is
        allowed to reflect disagreement.
        """
        default = dc.build_api_data_contract(_RAW)
        base = {fv._row_key(r): r for r in default["playersArray"] if fv._row_key(r)}
        ratios: list[tuple[float, str]] = []
        offense_ratios: list[tuple[float, str]] = []
        for key, entry in fv.fair_value_index(_RAW).items():
            fair = entry.get("fairValue")
            row = base.get(key) or {}
            baseline = row.get("rankDerivedValue")
            if not fair or not isinstance(baseline, (int, float)) or baseline <= 0:
                continue
            ratio = fair / float(baseline)
            ratios.append((ratio, key))
            if str(row.get("position") or "").upper() in {"QB", "RB", "WR", "TE"}:
                offense_ratios.append((ratio, key))

        self.assertGreater(len(ratios), 200, "too few priced rows to judge scale")

        median = statistics.median([r for r, _ in ratios])
        self.assertLess(
            abs(median - 1.0),
            0.05,
            f"median leave-one-out ratio is {median:.3f} — the anchor-free board is "
            f"not denominated in the same units as the board it is compared against",
        )

        worst_offense, worst_key = max(offense_ratios)
        self.assertLess(
            worst_offense,
            1.35,
            f"{worst_key} is {worst_offense:.2f}x the default board on the offense "
            f"side, where no bridge changed — that is a denominator fault, not a "
            f"difference of opinion",
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
    """A registry label may not confer cross-position capability.

    REWRITTEN for C7. The property is unchanged and the mechanism that
    guarantees it is stronger, so the tests move rather than relax.

    The original class pinned a hazard: ``scale_integrity_lost`` gated the IDP
    refusal on "does any surviving overall_idp source carry ``is_backbone``",
    and that gate could be satisfied by a one-line edit — promoting
    ``draftSharksIdp``, which carries ZERO positive offense values under its
    own key — while the board stayed bit-for-bit broken. Four shipped
    documents recommended exactly that edit as the forward path.

    Two things have changed.

    * ``is_backbone`` is **no longer read** when the ladder is built or when
      the declared gate is evaluated. The pipeline asks the bridge owner,
      which measures capability from the board.
    * A bridge is a **family**, so Draft Sharks — whose offense half lives
      under the separate ``draftSharks`` key — is a real second bridge rather
      than an identity ladder. Excluding ``idpTradeCalc`` therefore no longer
      breaks the IDP scale, which is the repair this lane exists for.

    So the tests below pin: the label buys nothing at all now; the declared
    gate follows the bridge registry; losing the incumbent bridge is survived;
    and losing EVERY bridge still refuses.
    """

    def _patched_registry(self):
        patched = []
        for src in dc._RANKING_SOURCES:
            copy = dict(src)
            if copy["key"] == "draftSharksIdp":
                copy["is_backbone"] = True
            patched.append(copy)
        return patched

    @_needs_payload
    def test_the_label_no_longer_moves_the_declared_gate(self):
        """The edit those documents recommended now buys nothing at all.

        It used to lift the refusal without repairing anything. The gate reads
        the bridge registry, so the flag is inert in both directions.
        """
        with mock.patch.object(dc, "_RANKING_SOURCES", self._patched_registry()):
            patched = dc.scale_integrity_lost(["idpTradeCalc"])
        unpatched = dc.scale_integrity_lost(["idpTradeCalc"])
        self.assertEqual(
            patched,
            unpatched,
            "is_backbone still changes the declared gate — the label is load-bearing again",
        )

    @_needs_payload
    def test_the_declared_gate_follows_the_bridge_registry(self):
        """Losing one QUALIFIED bridge is survivable; losing all is not."""
        self.assertEqual(dc.scale_integrity_lost([])["assetClasses"], {})
        self.assertEqual(
            dc.scale_integrity_lost(["idpTradeCalc"])["assetClasses"],
            {},
            "a second qualified bridge should carry the scale when the incumbent goes",
        )
        self.assertEqual(
            dc.scale_integrity_lost(["idpTradeCalc", "draftSharks", "draftSharksIdp"])[
                "assetClasses"
            ],
            {"idp": dc.SCALE_LOST_IDP_BACKBONE},
            "with every bridge gone the scale must be declared lost",
        )

    @_needs_payload
    def test_a_bridge_needs_both_halves(self):
        """Half a two-key vendor is not a bridge."""
        self.assertEqual(
            dc.scale_integrity_lost(["idpTradeCalc", "draftSharksIdp"])["assetClasses"],
            {"idp": dc.SCALE_LOST_IDP_BACKBONE},
        )

    @_needs_payload
    def test_losing_the_incumbent_bridge_is_survived(self):
        """The repair, measured on a real board: no untranslated votes."""
        board = fv.leave_one_out_board(_RAW, exclude=["idpTradeCalc"])
        failed = dc.shared_market_crosswalk_failed(board.get("playersArray") or [])
        self.assertEqual(
            failed,
            {},
            "excluding the incumbent bridge still produced untranslated votes",
        )

    @_needs_payload
    def test_the_default_board_translates_cleanly(self):
        # The probe must not cry wolf: with idpTradeCalc present, every
        # crosswalk-dependent source is translated.
        contract = dc.build_api_data_contract(_RAW)
        self.assertEqual(dc.shared_market_crosswalk_failed(contract.get("playersArray") or []), {})

    @_needs_payload
    def test_with_no_bridge_at_all_nothing_is_untranslated_either(self):
        """Not because it was translated — because the vote was withheld.

        This is the property that actually protects a user. Before the repair
        an anchor-free board reported ``["dlfIdp", "fantasyProsIdp",
        "idpShow"]`` as having fallen back, and those fallbacks put IDP #1 on
        the board as asset #1. Now no untranslated rank is recorded at all.
        """
        board = fv.leave_one_out_board(
            _RAW, exclude=["idpTradeCalc", "draftSharks", "draftSharksIdp"]
        )
        rows = board.get("playersArray") or []
        self.assertEqual(dc.shared_market_crosswalk_failed(rows), {})
        idp_at_ceiling = [
            r
            for r in rows
            if str(r.get("position") or "").upper() in {"DL", "LB", "DB"}
            and isinstance(r.get("rankDerivedValue"), (int, float))
            and float(r["rankDerivedValue"]) >= 9000
        ]
        self.assertEqual(
            idp_at_ceiling,
            [],
            "an IDP reached the top of the scale with no cross-position bridge",
        )


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
    def test_the_double_loss_is_still_declarable(self):
        """RE-DECIDED for C7. The machinery is pinned at its source.

        A rookie IDP row used to lose BOTH dependencies on the anchor-free
        board, because ``idpTradeCalc`` was the shared-market bridge AND the
        rookie ladder's reference. Draft Sharks now carries the bridge, so
        excluding the anchor costs only the rookie ladder and the overlap on
        that board is empty.

        The overlap is therefore asserted where it can still be produced —
        the declaration itself, with every bridge and the rookie reference
        gone — rather than by requiring a board to keep exhibiting a defect
        the repair removed.
        """
        declared = dc.scale_integrity_lost(["idpTradeCalc", "draftSharks", "draftSharksIdp"])
        self.assertEqual(declared["assetClasses"], {"idp": dc.SCALE_LOST_IDP_BACKBONE})
        self.assertEqual(
            declared["sources"].get("dlfRookieIdp"),
            dc.SCALE_LOST_ROOKIE_LADDER,
            "a rookie IDP source must still lose its ladder when its reference goes",
        )

    @_needs_payload
    def test_any_row_reporting_two_causes_names_both(self):
        index = fv.fair_value_index(_RAW)
        for entry in index.values():
            reasons = (entry.get("scaleIntegrity") or {}).get("reasons") or []
            if len(reasons) > 1:
                self.assertEqual(
                    sorted(reasons),
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
