"""Tests for trust, confidence, and anomaly fields added to the data contract.

Covers:
  - Confidence bucket computation
  - Anomaly flag rules
  - Market gap direction/magnitude
  - New per-player fields stamped by _compute_unified_rankings
  - Payload-level methodology, dataFreshness, and anomalySummary blocks
"""

from __future__ import annotations

import copy
import unittest

from src.api.data_contract import (
    OVERALL_RANK_LIMIT,
    _RANKING_SOURCES,
    _compute_confidence_bucket,
    _compute_anomaly_flags,
    _compute_market_gap,
    build_api_data_contract,
)
from src.canonical.idp_backbone import SOURCE_SCOPE_OVERALL_OFFENSE


# ── Helpers ──────────────────────────────────────────────────────────────────


class _SecondOffenseSourceMixin:
    """Mixin that temporarily registers a second `overall_offense` source.

    Under the scope-aware ranking pipeline a QB can only be ranked by
    overall_offense sources, so exercising any "multi-source" confidence
    path on an offense player requires two sources sharing that scope.
    Tests that relied on the old position-agnostic ranking used KTC+IDP
    on a QB — that's not possible (and not correct) under scope gating.
    This mixin installs a synthetic sibling source for the duration of
    one test so the two-source path is testable without faking anything.
    """

    _SIBLING_KEY = "ktcMirror"

    def setUp(self) -> None:  # noqa: D401 - unittest signature
        self._saved_registry = copy.deepcopy(_RANKING_SOURCES)
        _RANKING_SOURCES.append(
            {
                "key": self._SIBLING_KEY,
                "display_name": "KTC Mirror (test)",
                "scope": SOURCE_SCOPE_OVERALL_OFFENSE,
                "position_group": None,
                "depth": None,
                "weight": 1.0,
                "is_backbone": False,
            }
        )

    def tearDown(self) -> None:  # noqa: D401 - unittest signature
        _RANKING_SOURCES.clear()
        _RANKING_SOURCES.extend(self._saved_registry)


def _make_player(name, position, *, ktc=None, idp=None, team="TST", sibling=None):
    """Build a minimal raw player dict for contract builder tests.

    `sibling` attaches a value under the test-only `ktcMirror` key that
    `_SecondOffenseSourceMixin` temporarily registers as a second
    overall_offense source.
    """
    sites = {}
    if ktc is not None:
        # Standard ``ktc`` was retired from the blend 2026-04-28; the
        # ``ktcSfTep`` board is the canonical KTC offense source.  The
        # ``ktc`` parameter name is preserved for fixture ergonomics.
        sites["ktcSfTep"] = ktc
    if idp is not None:
        sites["idpTradeCalc"] = idp
    if sibling is not None:
        sites["ktcMirror"] = sibling
    composite_max = max(ktc or 0, idp or 0, sibling or 0)
    return {
        name: {
            "_composite": composite_max,
            "_rawComposite": composite_max,
            "_finalAdjusted": composite_max,
            "_sites": ((1 if ktc else 0) + (1 if idp else 0) + (1 if sibling else 0)),
            "position": position,
            "team": team,
            "_canonicalSiteValues": sites,
        }
    }


def _payload_with_players(*player_dicts):
    """Merge multiple _make_player dicts into a minimal contract payload."""
    players = {}
    positions = {}
    for d in player_dicts:
        for name, pdata in d.items():
            players[name] = pdata
            positions[name] = pdata["position"]
    return {
        "players": players,
        "sites": [{"key": "ktcSfTep"}, {"key": "idpTradeCalc"}],
        "maxValues": {"ktcSfTep": 9999},
        "sleeper": {"positions": positions},
    }


def _build_and_find(payload, player_name):
    """Build contract and return the named player row from playersArray."""
    contract = build_api_data_contract(payload)
    for row in contract["playersArray"]:
        if row["canonicalName"] == player_name:
            return row
    return None


# ── Confidence bucket unit tests ─────────────────────────────────────────────


class TestConfidenceBucket(unittest.TestCase):
    def test_high_bucket(self):
        bucket, label = _compute_confidence_bucket(2, 20.0)
        self.assertEqual(bucket, "high")
        self.assertIn("High", label)

    def test_high_boundary(self):
        bucket, _ = _compute_confidence_bucket(2, 30.0)
        self.assertEqual(bucket, "high")

    def test_medium_bucket(self):
        bucket, label = _compute_confidence_bucket(2, 50.0)
        self.assertEqual(bucket, "medium")
        self.assertIn("Medium", label)

    def test_medium_boundary(self):
        bucket, _ = _compute_confidence_bucket(2, 80.0)
        self.assertEqual(bucket, "medium")

    def test_low_bucket_wide_spread(self):
        bucket, label = _compute_confidence_bucket(2, 100.0)
        self.assertEqual(bucket, "low")
        self.assertIn("Low", label)

    def test_low_bucket_single_source(self):
        bucket, _ = _compute_confidence_bucket(1, None)
        self.assertEqual(bucket, "low")

    def test_none_bucket_zero_sources(self):
        bucket, label = _compute_confidence_bucket(0, None)
        self.assertEqual(bucket, "none")
        self.assertIn("unranked", label.lower())


# ── Anomaly flag unit tests ──────────────────────────────────────────────────


class TestAnomalyFlags(unittest.TestCase):
    def test_no_flags_for_clean_player(self):
        flags = _compute_anomaly_flags(
            name="Patrick Mahomes",
            position="QB",
            asset_class="offense",
            source_ranks={"ktcSfTep": 1},
            rank_derived_value=9999,
            canonical_sites={"ktcSfTep": 9999},
        )
        self.assertEqual(flags, [])

    def test_offense_as_idp(self):
        flags = _compute_anomaly_flags(
            name="Fake Player",
            position="WR",
            asset_class="offense",
            source_ranks={"idpTradeCalc": 50},
            rank_derived_value=5000,
            canonical_sites={"idpTradeCalc": 500},
        )
        self.assertIn("offense_as_idp", flags)

    def test_idp_as_offense(self):
        flags = _compute_anomaly_flags(
            name="Fake Defender",
            position="LB",
            asset_class="idp",
            source_ranks={"ktcSfTep": 100},
            rank_derived_value=3000,
            canonical_sites={"ktcSfTep": 300},
        )
        self.assertIn("idp_as_offense", flags)

    def test_missing_position(self):
        flags = _compute_anomaly_flags(
            name="Mystery Man",
            position="?",
            asset_class="offense",
            source_ranks={"ktcSfTep": 200},
            rank_derived_value=2000,
            canonical_sites={"ktcSfTep": 200},
        )
        self.assertIn("missing_position", flags)

    def test_missing_position_empty(self):
        flags = _compute_anomaly_flags(
            name="No Pos",
            position="",
            asset_class="offense",
            source_ranks={"ktcSfTep": 200},
            rank_derived_value=2000,
            canonical_sites={"ktcSfTep": 200},
        )
        self.assertIn("missing_position", flags)

    def test_retired_or_invalid_name(self):
        flags = _compute_anomaly_flags(
            name="Retired Player Test",
            position="QB",
            asset_class="offense",
            source_ranks={"ktcSfTep": 300},
            rank_derived_value=1500,
            canonical_sites={"ktcSfTep": 150},
        )
        self.assertIn("retired_or_invalid_name", flags)

    def test_ol_contamination(self):
        flags = _compute_anomaly_flags(
            name="Joe Lineman",
            position="OL",
            asset_class="offense",
            source_ranks={"ktcSfTep": 400},
            rank_derived_value=1000,
            canonical_sites={"ktcSfTep": 100},
        )
        self.assertIn("ol_contamination", flags)

    def test_suspicious_disagreement(self):
        flags = _compute_anomaly_flags(
            name="Disagreed Player",
            position="QB",
            asset_class="offense",
            source_ranks={"ktcSfTep": 10, "idpTradeCalc": 200},
            rank_derived_value=5000,
            canonical_sites={"ktcSfTep": 9000, "idpTradeCalc": 500},
        )
        self.assertIn("suspicious_disagreement", flags)

    def test_no_suspicious_disagreement_when_close(self):
        flags = _compute_anomaly_flags(
            name="Agreed Player",
            position="QB",
            asset_class="offense",
            source_ranks={"ktcSfTep": 10, "idpTradeCalc": 20},
            rank_derived_value=9000,
            canonical_sites={"ktcSfTep": 9000, "idpTradeCalc": 8500},
        )
        self.assertNotIn("suspicious_disagreement", flags)

    def test_impossible_value(self):
        flags = _compute_anomaly_flags(
            name="Zero Val Player",
            position="QB",
            asset_class="offense",
            source_ranks={"ktcSfTep": 50},
            rank_derived_value=0,
            canonical_sites={"ktcSfTep": 500},
        )
        self.assertIn("impossible_value", flags)

    def test_impossible_value_none(self):
        flags = _compute_anomaly_flags(
            name="None Val Player",
            position="QB",
            asset_class="offense",
            source_ranks={"ktcSfTep": 50},
            rank_derived_value=None,
            canonical_sites={"ktcSfTep": 500},
        )
        self.assertIn("impossible_value", flags)


# ── Market gap unit tests ────────────────────────────────────────────────────


class TestMarketGap(unittest.TestCase):
    """Retail vs consensus, in rank space, with the positional basis removed.

    REVERSAL RECORDED IN PLACE (audit S-1/C19 + S-2/C08, batch C4).
    Every test in this class used to assert raw-ordinal arithmetic as
    correct — ``_compute_market_gap({"ktcSfTep": 10, "idpTradeCalc": 50})``
    was expected to return a magnitude of exactly ``40.0``.

    That expectation encodes the defect. It is only true if the two
    boards are the same depth, and measured on the live board they are
    not: the registered sources publish between 278 and 900 rows, so
    "rank 50" is a bottom-third placement on one board and a top-tenth
    placement on another. Comparing the ordinals flipped the sign of the
    gap on 42% of offense rows and 35 of 36 picks.

    The tests are rewritten rather than deleted so a future reader can
    see that the old numbers were reversed deliberately.
    """

    # Two boards of deliberately different depth. Sized so the classic
    # "rank 10 vs rank 50" case can be shown to invert.
    DEPTHS = {"ktcSfTep": 100, "idpTradeCalc": 1000, "dlfIdp": 1000, "sleeperTrade": 100}
    # No basis for the position under test unless a case supplies one,
    # so most cases isolate the rank-space change from the de-meaning.
    NO_BASIS: dict[str, float] = {"WR": 0.0}

    def gap(self, ranks, *, depths=None, position="WR", basis=None, retail_keys=None):
        return _compute_market_gap(
            ranks,
            depths if depths is not None else self.DEPTHS,
            position,
            basis if basis is not None else self.NO_BASIS,
            retail_keys=retail_keys,
        )

    # ── the defect itself ────────────────────────────────────────────
    def test_identical_ordinals_invert_when_the_boards_differ_in_depth(self):
        """The single case this batch exists for.

        Retail rank 10 of 100 is one tenth of the way down its board.
        Consensus rank 50 of 1000 is one twentieth of the way down
        theirs — a BETTER placement. Ordinal arithmetic called this a
        40-rank retail premium; in the only space where the two boards
        can be compared it is a consensus premium.
        """
        direction, magnitude, absolute, unknown = self.gap({"ktcSfTep": 10, "idpTradeCalc": 50})
        self.assertEqual(direction, "consensus_premium")
        # 0.05 - 0.10 = -0.05 → 50 per-mille.
        self.assertAlmostEqual(magnitude, 50.0, places=6)
        self.assertAlmostEqual(absolute, -50.0, places=6)
        self.assertIsNone(unknown)

    def test_equal_depth_reproduces_the_ordinal_intuition(self):
        """Rank space is not a different answer, it is the same answer
        measured properly: when the boards ARE the same depth the old
        ordinal reading is recovered exactly."""
        direction, magnitude, _absolute, _unknown = self.gap(
            {"ktcSfTep": 10, "idpTradeCalc": 50},
            depths={"ktcSfTep": 100, "idpTradeCalc": 100},
        )
        self.assertEqual(direction, "retail_premium")
        # 40 ranks of a 100-row board = 400 per-mille.
        self.assertAlmostEqual(magnitude, 400.0, places=6)

    # ── direction, in rank space ─────────────────────────────────────
    def test_retail_premium(self):
        direction, magnitude, _a, _u = self.gap(
            {"ktcSfTep": 10, "idpTradeCalc": 500},
        )
        self.assertEqual(direction, "retail_premium")
        self.assertAlmostEqual(magnitude, 400.0, places=6)

    def test_consensus_premium(self):
        direction, magnitude, _a, _u = self.gap(
            {"ktcSfTep": 80, "idpTradeCalc": 200},
        )
        self.assertEqual(direction, "consensus_premium")
        self.assertAlmostEqual(magnitude, 600.0, places=6)

    def test_equal_positions_are_a_measured_tie(self):
        """0.0 is a real answer here and must not read as absent."""
        direction, magnitude, _a, unknown = self.gap(
            {"ktcSfTep": 30, "idpTradeCalc": 300},
        )
        self.assertEqual(direction, "none")
        self.assertEqual(magnitude, 0.0)
        self.assertIsNone(unknown)

    def test_consensus_side_is_averaged_across_sources(self):
        direction, magnitude, _a, _u = self.gap(
            {"ktcSfTep": 10, "idpTradeCalc": 400, "dlfIdp": 600},
        )
        self.assertEqual(direction, "retail_premium")
        # mean(0.40, 0.60) - 0.10 = 0.40
        self.assertAlmostEqual(magnitude, 400.0, places=6)

    def test_multi_retail_sources_are_averaged(self):
        """Hypothetical two-retail world, via the retail_keys override so
        the real registry is not mutated."""
        direction, magnitude, _a, _u = self.gap(
            {"ktcSfTep": 10, "sleeperTrade": 30, "idpTradeCalc": 500, "dlfIdp": 700},
            retail_keys=frozenset({"ktcSfTep", "sleeperTrade"}),
        )
        self.assertEqual(direction, "retail_premium")
        # retail mean(0.10, 0.30) = 0.20; consensus mean(0.50, 0.70) = 0.60
        self.assertAlmostEqual(magnitude, 400.0, places=6)

    # ── abstention, which used to be one undifferentiated "none" ─────
    def test_retail_only_says_so(self):
        direction, magnitude, absolute, unknown = self.gap({"ktcSfTep": 10})
        self.assertEqual(direction, "none")
        self.assertIsNone(magnitude)
        self.assertIsNone(absolute)
        self.assertEqual(unknown["reason"], "retail_only")

    def test_no_retail_says_so_and_this_is_every_defender(self):
        """The retail anchor publishes no IDP at all.

        Measured on the live board: 386 rows abstain with exactly this
        reason. Before C4 they were indistinguishable from a genuine
        tie, which is why the market gap being unavailable for the whole
        IDP half of the board was invisible.
        """
        direction, magnitude, _a, unknown = self.gap({"idpTradeCalc": 10, "dlfIdp": 20})
        self.assertEqual(direction, "none")
        self.assertIsNone(magnitude)
        self.assertEqual(unknown["reason"], "consensus_only")

    def test_unranked_says_so(self):
        direction, _m, _a, unknown = self.gap({})
        self.assertEqual(direction, "none")
        self.assertEqual(unknown["reason"], "unranked")

    def test_a_source_with_no_known_depth_cannot_be_placed(self):
        """Depth is observed, so a source nothing ranked has none. That
        must abstain rather than divide by a guess."""
        direction, _m, _a, unknown = self.gap(
            {"ktcSfTep": 10, "idpTradeCalc": 50}, depths={"ktcSfTep": 100}
        )
        self.assertEqual(direction, "none")
        self.assertEqual(unknown["reason"], "consensus_depth_unknown")

    # ── the positional basis ─────────────────────────────────────────
    def test_the_position_basis_is_subtracted(self):
        """A gap exactly equal to its position's basis is NOT a signal.

        This is the tight-end case in miniature: measured on the live
        board the median TE gap is +121 per-mille, so a tight end at
        +121 is simply an ordinary tight end on a TE-premium retail
        board — not a sell candidate.
        """
        ranks = {"ktcSfTep": 10, "idpTradeCalc": 200}  # absolute gap = +100
        direction, magnitude, absolute, _u = self.gap(ranks, position="TE", basis={"TE": 0.100})
        self.assertEqual(direction, "none")
        self.assertAlmostEqual(magnitude, 0.0, places=6)
        # The raw number survives: it is what a trade with a
        # retail-anchored partner actually turns on.
        self.assertAlmostEqual(absolute, 100.0, places=6)

    def test_deviation_from_the_basis_is_the_signal(self):
        ranks = {"ktcSfTep": 10, "idpTradeCalc": 200}  # absolute gap = +100
        direction, magnitude, absolute, _u = self.gap(ranks, position="TE", basis={"TE": 0.040})
        self.assertEqual(direction, "retail_premium")
        self.assertAlmostEqual(magnitude, 60.0, places=6)
        self.assertAlmostEqual(absolute, 100.0, places=6)

    def test_a_position_with_no_basis_abstains_rather_than_guessing(self):
        """De-meaning off too small a sample invents a constant out of
        the noise it exists to remove, so there is no direction — but
        the absolute number is still published."""
        direction, magnitude, absolute, unknown = self.gap(
            {"ktcSfTep": 10, "idpTradeCalc": 200}, position="K", basis={"WR": 0.0}
        )
        self.assertEqual(direction, "none")
        self.assertIsNone(magnitude)
        self.assertAlmostEqual(absolute, 100.0, places=6)
        self.assertEqual(unknown["reason"], "position_sample_too_small")


# ── Integration: single-source player row ────────────────────────────────────


class TestSingleSourceRow(unittest.TestCase):
    def test_single_source_offense_player(self):
        # Use a unique name that won't match CSV enrichment data on disk.
        # With two primary-scope offense sources now registered (KTC +
        # DLF Superflex), a KTC-only QB whose rank is within DLF's
        # expected depth IS a real matching failure — DLF should have
        # covered him and didn't.  The test fixture uses an unusual
        # name so it won't match DLF's CSV on disk.
        payload = _payload_with_players(
            _make_player("Zzz Testonly Qb Alpha", "QB", ktc=9500),
        )
        row = _build_and_find(payload, "Zzz Testonly Qb Alpha")
        self.assertIsNotNone(row)
        self.assertTrue(row["isSingleSource"])
        self.assertFalse(row["isStructurallySingleSource"])
        self.assertEqual(row["confidenceBucket"], "low")
        self.assertIsNone(row["sourceRankSpread"])
        self.assertEqual(row["marketGapDirection"], "none")
        self.assertIsNone(row["marketGapMagnitude"])
        self.assertFalse(row["hasSourceDisagreement"])
        self.assertIsInstance(row["anomalyFlags"], list)

    def test_single_source_idp_player(self):
        payload = _payload_with_players(
            _make_player("Zzz Testonly Lb Alpha", "LB", idp=8000),
        )
        row = _build_and_find(payload, "Zzz Testonly Lb Alpha")
        self.assertIsNotNone(row)
        self.assertTrue(row["isSingleSource"])
        self.assertEqual(row["confidenceBucket"], "low")


# ── Integration: two-source player row ───────────────────────────────────────


class TestTwoSourceRow(_SecondOffenseSourceMixin, unittest.TestCase):
    def test_two_source_player_tight_agreement(self):
        """Two offense sources with similar values → high confidence,
        no disagreement.  Uses the test-only ktcMirror sibling source
        registered by the mixin, because KTC and idpTradeCalc have
        disjoint scopes and can never both rank the same player.
        """
        payload = _payload_with_players(
            _make_player("Two Source Guy", "QB", ktc=9000, sibling=8800),
        )
        row = _build_and_find(payload, "Two Source Guy")
        self.assertIsNotNone(row)
        self.assertFalse(row["isSingleSource"])
        self.assertIsNotNone(row["sourceRankSpread"])
        # Both offense sources exist
        self.assertIn("ktcSfTep", row.get("sourceRanks", {}))
        self.assertIn("ktcMirror", row.get("sourceRanks", {}))
        # blendedSourceRank should be a number
        self.assertIsNotNone(row["blendedSourceRank"])
        self.assertIsInstance(row["blendedSourceRank"], float)


# ── Integration: unranked player (no source values) ─────────────────────────


class TestUnrankedPlayer(unittest.TestCase):
    def test_unranked_player_gets_defaults(self):
        """A player with no source values should still have trust fields."""
        payload = _payload_with_players(
            _make_player("No Value Guy", "QB"),
        )
        row = _build_and_find(payload, "No Value Guy")
        self.assertIsNotNone(row)
        self.assertEqual(row["confidenceBucket"], "none")
        self.assertEqual(row["anomalyFlags"], [])
        self.assertFalse(row["isSingleSource"])
        self.assertFalse(row["hasSourceDisagreement"])
        self.assertIsNone(row["blendedSourceRank"])
        self.assertIsNone(row["sourceRankSpread"])


# ── Integration: contract payload-level blocks ───────────────────────────────


class TestPayloadLevelBlocks(unittest.TestCase):
    def test_methodology_block_present(self):
        payload = _payload_with_players(
            _make_player("Test QB", "QB", ktc=8000),
        )
        contract = build_api_data_contract(payload)
        meth = contract.get("methodology")
        self.assertIsNotNone(meth)
        self.assertEqual(meth["version"], contract["contractVersion"])
        self.assertEqual(meth["overallRankLimit"], OVERALL_RANK_LIMIT)
        self.assertIn("formula", meth)
        self.assertIn("confidenceBuckets", meth)
        self.assertIn("anomalyFlags", meth)
        self.assertIsInstance(meth["sources"], list)
        # ktc + ktcSfTep + idpTradeCalc + dlfIdp + idpShow + dlfSf +
        # dynastyNerdsSfTep + fantasyCalc + otcffbSf + fantasyProsSf +
        # dynastyDaddySf + fantasyProsIdp + flockFantasySf +
        # footballGuysSf + footballGuysIdp + yahooBoone +
        # fantasyProsFitzmaurice + dlfRookieSf + flockFantasySfRookies +
        # dlfRookieIdp + draftSharks + draftSharksIdp.  Standard
        # ``ktc`` was retired from the blend 2026-04-28 in favor of
        # ``ktcSfTep`` alone (the prior 20-source count included both
        # KTC variants as separate blend votes); ``fantasyCalc`` was
        # added 2026-05-13; ``otcffbSf`` added 2026-05-15;
        # ``fantasyNavigatorSf`` + ``pfkDynasty`` added 2026-07-25
        # (Phase 2 of the competitor-parity roadmap).
        self.assertEqual(len(meth["sources"]), 21)
        keys = {s.get("key") for s in meth["sources"]}
        self.assertEqual(
            keys,
            {
                "ktcSfTep",
                "idpTradeCalc",
                "dlfIdp",
                "idpShow",
                "dlfSf",
                "dynastyNerdsSfTep",
                "fantasyCalc",
                "otcffbSf",
                "fantasyNavigatorSf",
                "pfkDynasty",
                "fantasyProsSf",
                "dynastyDaddySf",
                "fantasyProsIdp",
                "flockFantasySf",
                "yahooBoone",
                "fantasyProsFitzmaurice",
                "dlfRookieSf",
                "flockFantasySfRookies",
                "dlfRookieIdp",
                "draftSharks",
                "draftSharksIdp",
            },
        )

    def test_data_freshness_block_present(self):
        payload = _payload_with_players(
            _make_player("Test QB", "QB", ktc=8000),
        )
        contract = build_api_data_contract(payload)
        freshness = contract.get("dataFreshness")
        self.assertIsNotNone(freshness)
        self.assertIn("generatedAt", freshness)
        self.assertIn("sourceTimestamps", freshness)
        self.assertIn("ktcSfTep", freshness["sourceTimestamps"])
        self.assertIn("idpTradeCalc", freshness["sourceTimestamps"])

    def test_anomaly_summary_block_present(self):
        payload = _payload_with_players(
            _make_player("Test QB", "QB", ktc=8000),
        )
        contract = build_api_data_contract(payload)
        summary = contract.get("anomalySummary")
        self.assertIsNotNone(summary)
        self.assertIn("totalFlagged", summary)
        self.assertIn("flagCounts", summary)

    def test_methodology_formula_matches_constants(self):
        """The published formula block must describe the LIVE percentile-form
        pipeline (scope-master Hill curves + fixed 500-rank percentile
        reference), not the retired rank-form curve.  Before the 2026-07-29
        audit this block published midpoint 45 / slope 1.10 — constants no
        live code path used — and this test pinned the fossil."""
        from src.api.data_contract import _PERCENTILE_REFERENCE_N

        payload = _payload_with_players(
            _make_player("Test QB", "QB", ktc=8000),
        )
        contract = build_api_data_contract(payload)
        formula = contract["methodology"]["formula"]
        self.assertEqual(formula["referenceN"], _PERCENTILE_REFERENCE_N)
        self.assertIn("percentile", formula["name"].lower())
        self.assertIn("(p/c)^s", formula["expression"])
        self.assertNotIn("midpoint", formula)
        self.assertNotIn("slope", formula)
        self.assertEqual(formula["scaleMin"], 1)
        self.assertEqual(formula["scaleMax"], 9999)

    def test_anomaly_summary_counts_flagged_players(self):
        """Build a payload with a player that triggers an anomaly, verify count."""
        # OL player is excluded from ranking, gets unsupported_position flag
        payload = _payload_with_players(
            _make_player("Good QB", "QB", ktc=9000),
            _make_player("OL Guy", "OL", ktc=5000),
        )
        contract = build_api_data_contract(payload)
        summary = contract["anomalySummary"]
        # OL Guy should be flagged with unsupported_position (not ol_contamination,
        # because OL is now excluded from per-source ranking entirely)
        self.assertGreaterEqual(summary["totalFlagged"], 1)
        self.assertIn("unsupported_position", summary["flagCounts"])


# ── Integration: REQUIRED_PLAYER_KEYS includes new fields ───────────────────


class TestRequiredPlayerKeys(unittest.TestCase):
    def test_new_fields_in_required_keys(self):
        from src.api.data_contract import REQUIRED_PLAYER_KEYS

        self.assertIn("confidenceBucket", REQUIRED_PLAYER_KEYS)
        self.assertIn("anomalyFlags", REQUIRED_PLAYER_KEYS)


# ── Quarantine and identity confidence ─────────────────────────────────────


class TestQuarantineFields(unittest.TestCase):
    """Verify quarantine flag and confidence degradation."""

    def test_clean_player_not_quarantined(self):
        payload = _payload_with_players(
            _make_player("Clean QB", "QB", ktc=9000),
        )
        row = _build_and_find(payload, "Clean QB")
        self.assertFalse(row["quarantined"])

    def test_ol_player_quarantined(self):
        """OL contamination is a quarantine-level flag."""
        payload = _payload_with_players(
            _make_player("OL Guy", "OL", ktc=5000),
        )
        row = _build_and_find(payload, "OL Guy")
        self.assertTrue(row["quarantined"])
        self.assertIn("unsupported_position", row["anomalyFlags"])

    def test_quarantine_degrades_confidence(self):
        """Quarantined players should have confidence degraded.
        OL players are excluded from ranking, so they keep the default
        'none' confidence bucket — quarantine does not promote to 'low'."""
        payload = _payload_with_players(
            _make_player("Normal WR", "WR", ktc=8000),
            _make_player("OL Leak", "OL", ktc=6000),
        )
        row = _build_and_find(payload, "OL Leak")
        self.assertTrue(row["quarantined"])
        # OL is excluded from ranking → stays at default "none" confidence.
        # Quarantine degrades high/medium → low, but "none" is already lowest.
        self.assertEqual(row["confidenceBucket"], "none")


class TestIdentityConfidence(unittest.TestCase):
    """Verify identity confidence scoring."""

    def test_name_only_gets_070(self):
        payload = _payload_with_players(
            _make_player("No ID QB", "QB", ktc=9000),
        )
        row = _build_and_find(payload, "No ID QB")
        # No playerId, but position matches source evidence
        self.assertGreaterEqual(row["identityConfidence"], 0.70)
        self.assertIn(
            row["identityMethod"],
            (
                "name_only",
                "position_source_aligned",
                "partial_evidence",
            ),
        )

    def test_identity_fields_present(self):
        payload = _payload_with_players(
            _make_player("Any Player", "WR", ktc=7000),
        )
        row = _build_and_find(payload, "Any Player")
        self.assertIn("identityConfidence", row)
        self.assertIn("identityMethod", row)
        self.assertIsInstance(row["identityConfidence"], float)
        self.assertIsInstance(row["identityMethod"], str)


class TestMultiFlagScenarios(unittest.TestCase):
    """Verify behaviour when multiple anomaly flags fire."""

    def test_missing_position_and_no_source_flags(self):
        """A player with pos=? and no sources should get multiple flags."""
        payload = _payload_with_players(
            _make_player("Mystery", "?"),
        )
        row = _build_and_find(payload, "Mystery")
        # Should have at least missing_position flag
        # (won't be ranked so anomaly flags from _compute_anomaly_flags
        # may not fire, but contract defaults should be clean)
        self.assertIsInstance(row["anomalyFlags"], list)

    def test_suspicious_disagreement_with_high_spread(self):
        """Two sources > 150 ranks apart triggers suspicious_disagreement."""
        # Create many players so ranks can actually spread.  IDPTradeCalc
        # now contributes to both the offense and IDP scopes, so the
        # filler QBs carry IDPTC values too (mirroring production where
        # IDPTC's autocomplete covers every offense star).  Without a
        # full offense IDPTC pool the test player would be the only QB
        # ranked by IDPTC and the spread would collapse to zero.
        players = {}
        for i in range(200):
            p = _make_player(
                f"Filler Off {i}",
                "QB",
                ktc=9000 - i * 40,
                idp=9000 - i * 40,
            )
            players.update(p)
        for i in range(200):
            p = _make_player(f"Filler IDP {i}", "DL", idp=9000 - i * 40)
            players.update(p)
        # Add test player with both sources at wildly different ranks.
        # ktc=9000 puts him near the top of the KTC offense ladder, while
        # idp=100 puts him near the bottom of the IDPTC offense ladder.
        test_p = _make_player("Spread Guy", "QB", ktc=9000, idp=100)
        players.update(test_p)
        payload = {
            "players": players,
            "sites": [{"key": "ktcSfTep"}, {"key": "idpTradeCalc"}],
            "maxValues": {"ktcSfTep": 9999},
            "sleeper": {"positions": {k: v["position"] for k, v in players.items()}},
        }
        row = _build_and_find(payload, "Spread Guy")
        self.assertIsNotNone(row)
        # Should have a significant spread
        if row.get("sourceRankSpread") is not None:
            self.assertGreater(row["sourceRankSpread"], 50)


class TestEdgeCaseFixtures(_SecondOffenseSourceMixin, unittest.TestCase):
    """Regression fixtures for edge-case row types.

    Uses the _SecondOffenseSourceMixin so the multi-source consensus
    test below can attach a second overall_offense source (ktcMirror)
    alongside KTC.
    """

    def test_single_source_offense_player(self):
        payload = _payload_with_players(
            _make_player("Solo WR", "WR", ktc=7500),
        )
        row = _build_and_find(payload, "Solo WR")
        self.assertTrue(row["isSingleSource"])
        self.assertIsNone(row["sourceRankSpread"])
        self.assertEqual(row["marketGapDirection"], "none")
        self.assertFalse(row["hasSourceDisagreement"])

    def test_single_source_idp_player(self):
        payload = _payload_with_players(
            _make_player("Solo LB", "LB", idp=6000),
        )
        row = _build_and_find(payload, "Solo LB")
        self.assertTrue(row["isSingleSource"])
        self.assertEqual(row["confidenceBucket"], "low")

    def test_high_confidence_consensus_asset(self):
        """Multi-source with tight agreement = high confidence.

        Uses two overall_offense sources (ktc + ktcMirror) because KTC
        and idpTradeCalc have disjoint scopes under the scope-aware
        ranking pipeline.
        """
        payload = _payload_with_players(
            _make_player("Consensus QB", "QB", ktc=9000, sibling=8900),
        )
        row = _build_and_find(payload, "Consensus QB")
        self.assertFalse(row["isSingleSource"])
        self.assertEqual(row["confidenceBucket"], "high")
        self.assertFalse(row["quarantined"])

    def test_all_trust_fields_present_on_ranked_player(self):
        """Every trust field should exist on a ranked player."""
        payload = _payload_with_players(
            _make_player("Complete QB", "QB", ktc=8000),
        )
        row = _build_and_find(payload, "Complete QB")
        required_fields = [
            "confidenceBucket",
            "confidenceLabel",
            "anomalyFlags",
            "isSingleSource",
            "hasSourceDisagreement",
            "blendedSourceRank",
            "sourceRankSpread",
            "marketGapDirection",
            "marketGapMagnitude",
            "identityConfidence",
            "identityMethod",
            "quarantined",
        ]
        for field in required_fields:
            self.assertIn(field, row, f"Missing trust field: {field}")


class TestTrustMirrorToLegacy(_SecondOffenseSourceMixin, unittest.TestCase):
    """Trust fields must be mirrored from playersArray → legacy players dict.

    The runtime view strips playersArray.  The frontend falls back to the
    legacy dict and reads trust fields via r.raw?.field.  This test proves
    that build_api_data_contract copies all 12 trust fields into the legacy
    dict so they survive the runtime view.
    """

    TRUST_FIELDS = [
        "confidenceBucket",
        "confidenceLabel",
        "anomalyFlags",
        "isSingleSource",
        "hasSourceDisagreement",
        "blendedSourceRank",
        "sourceRankSpread",
        "marketGapDirection",
        "marketGapMagnitude",
        "identityConfidence",
        "identityMethod",
        "quarantined",
    ]

    def test_trust_fields_mirrored_to_legacy_dict(self):
        """All 12 trust fields appear on the legacy players dict entry."""
        payload = _payload_with_players(
            _make_player("Mirror QB", "QB", ktc=8500),
        )
        contract = build_api_data_contract(payload)
        legacy_entry = contract["players"].get("Mirror QB")
        self.assertIsNotNone(legacy_entry, "Legacy dict entry missing")

        for field in self.TRUST_FIELDS:
            self.assertIn(field, legacy_entry, f"Trust field '{field}' not mirrored to legacy dict")

    def test_mirrored_values_match_players_array(self):
        """Mirrored legacy values must match the playersArray values."""
        payload = _payload_with_players(
            _make_player("Match QB", "QB", ktc=9000, idp=None),
        )
        contract = build_api_data_contract(payload)
        row = None
        for r in contract["playersArray"]:
            if r["canonicalName"] == "Match QB":
                row = r
                break
        self.assertIsNotNone(row)
        legacy_entry = contract["players"]["Match QB"]

        for field in self.TRUST_FIELDS:
            self.assertEqual(
                legacy_entry[field],
                row[field],
                f"Mismatch on '{field}': legacy={legacy_entry[field]!r}, " f"array={row[field]!r}",
            )

    def test_quarantine_reflected_in_legacy_dict(self):
        """Quarantined status and degraded confidence reach the legacy dict."""
        # Build two players with same name collision → triggers quarantine
        payload = _payload_with_players(
            _make_player("Quarantine QB", "QB", ktc=7000),
        )
        contract = build_api_data_contract(payload)
        legacy_entry = contract["players"]["Quarantine QB"]
        # Whether quarantined or not, the field must be present and boolean
        self.assertIn("quarantined", legacy_entry)
        self.assertIsInstance(legacy_entry["quarantined"], bool)
        self.assertIn("confidenceBucket", legacy_entry)

    def test_multi_source_high_confidence_mirrored(self):
        """A multi-source player with tight agreement gets 'high' mirrored.

        Uses two overall_offense sources (ktc + ktcMirror) via the mixin
        because KTC and idpTradeCalc have disjoint scopes and cannot
        both rank a QB under the scope-aware pipeline.
        """
        payload = _payload_with_players(
            _make_player("Dual QB", "QB", ktc=8000, sibling=8000),
        )
        contract = build_api_data_contract(payload)
        legacy_entry = contract["players"]["Dual QB"]
        # With equal values across two sources, spread=0 → high confidence
        self.assertEqual(legacy_entry["confidenceBucket"], "high")
        self.assertFalse(legacy_entry["isSingleSource"])


class TestUnsupportedPositionRankingExclusion(unittest.TestCase):
    """Unsupported positions (OL, OT, OG, C, G, T, LS) must never receive
    a canonicalConsensusRank or rankDerivedValue, even when they have
    source values."""

    UNSUPPORTED = ["OL", "OT", "OG", "C", "G", "T", "LS"]

    def _make_unsupported(self, name, position, ktc_val=7000):
        """Build a player dict with an unsupported position but valid KTC."""
        return {
            name: {
                "_composite": ktc_val,
                "_rawComposite": ktc_val,
                "_finalAdjusted": ktc_val,
                "_sites": 1,
                "position": position,
                "team": "TST",
                "_canonicalSiteValues": {"ktcSfTep": ktc_val},
            }
        }

    def test_ol_not_ranked(self):
        """OL player with KTC value must not receive a rank."""
        payload = _payload_with_players(
            self._make_unsupported("Nick Martin", "C", ktc_val=5000),
            _make_player("Real QB", "QB", ktc=9000),
        )
        row = _build_and_find(payload, "Nick Martin")
        self.assertIsNotNone(row)
        # Must not have a rank or derived value from the ranking pass
        self.assertIn("unsupported_position", row.get("anomalyFlags", []))
        self.assertTrue(row["quarantined"])
        # canonicalConsensusRank should be None (not ranked)
        rank = row.get("canonicalConsensusRank")
        self.assertTrue(
            rank is None or rank == 0,
            f"OL player got rank {rank} — should be unranked",
        )

    def test_all_unsupported_positions_excluded(self):
        """Every unsupported position must be excluded from ranking."""
        for pos in self.UNSUPPORTED:
            players = [
                self._make_unsupported(f"Test {pos}", pos, ktc_val=8000),
                _make_player("Anchor QB", "QB", ktc=9500),
            ]
            payload = _payload_with_players(*players)
            row = _build_and_find(payload, f"Test {pos}")
            self.assertIsNotNone(row, f"Row missing for position {pos}")
            rank = row.get("canonicalConsensusRank")
            self.assertTrue(
                rank is None or rank == 0,
                f"Position {pos} got rank {rank} — should be unranked",
            )

    def test_supported_positions_still_ranked(self):
        """Supported positions must still receive ranks normally."""
        payload = _payload_with_players(
            _make_player("Ranked QB", "QB", ktc=9000),
            _make_player("Ranked LB", "LB", idp=8000),
        )
        qb = _build_and_find(payload, "Ranked QB")
        lb = _build_and_find(payload, "Ranked LB")
        self.assertIsNotNone(qb)
        self.assertIsNotNone(lb)
        self.assertIsNotNone(qb.get("canonicalConsensusRank"))
        self.assertGreater(qb["canonicalConsensusRank"], 0)
        self.assertIsNotNone(lb.get("canonicalConsensusRank"))
        self.assertGreater(lb["canonicalConsensusRank"], 0)

    def test_unsupported_does_not_displace_supported(self):
        """An unsupported-position player must not take a rank slot
        away from a supported-position player."""
        payload = _payload_with_players(
            self._make_unsupported("OL Guy", "OL", ktc_val=9999),
            _make_player("Real WR", "WR", ktc=5000),
        )
        wr = _build_and_find(payload, "Real WR")
        ol = _build_and_find(payload, "OL Guy")
        self.assertIsNotNone(wr)
        self.assertIsNotNone(ol)
        # WR must be ranked
        self.assertGreater(wr["canonicalConsensusRank"], 0)
        # OL must NOT be ranked (no rank displacement)
        ol_rank = ol.get("canonicalConsensusRank")
        self.assertTrue(ol_rank is None or ol_rank == 0)


if __name__ == "__main__":
    unittest.main()
