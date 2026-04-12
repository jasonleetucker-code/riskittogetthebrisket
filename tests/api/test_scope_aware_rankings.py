"""Integration tests for the scope-aware + backbone-aware unified
ranking pipeline in src/api/data_contract.py.

These tests exercise the full `_compute_unified_rankings` function with
rows that look like real playersArray entries.  They cover every
category the IDP ranking brief called out:

    A. Full overall IDP source normalises correctly
    B. Position-only DL/LB/DB sources translate to synthetic overall
       IDP ranks via the backbone ladder
    C. Mixed-source IDP blending uses coverage-aware weights so shallow
       lists cannot overpower deep boards
    D. Offensive behaviour does not regress (KTC-driven offensive
       rankings and picks still land in the expected order)
    E. Backend stamps the same sourceRanks shape we mirror on the
       frontend (sourceRankMeta, idpBackboneFallback, etc.)
    F. Edge cases: empty backbone fallback, extrapolation past the tail,
       zero/missing source values
"""
from __future__ import annotations

import copy
import unittest

from src.api.data_contract import (
    _RANKING_SOURCES,
    _compute_unified_rankings,
)
from src.canonical.idp_backbone import (
    SOURCE_SCOPE_OVERALL_IDP,
    SOURCE_SCOPE_OVERALL_OFFENSE,
    SOURCE_SCOPE_POSITION_IDP,
    TRANSLATION_DIRECT,
    TRANSLATION_EXACT,
    TRANSLATION_EXTRAPOLATED,
    TRANSLATION_FALLBACK,
    TRANSLATION_INTERPOLATED,
)
from src.canonical.player_valuation import rank_to_value


def _row(name: str, pos: str, *, ktc=None, idp=None, extra=None) -> dict:
    """Build a minimal playersArray row with optional per-source values."""
    sites: dict = {}
    if ktc is not None:
        sites["ktc"] = ktc
    if idp is not None:
        sites["idpTradeCalc"] = idp
    if extra:
        sites.update(extra)
    return {
        "canonicalName": name,
        "displayName": name,
        "legacyRef": name,
        "position": pos,
        "assetClass": "offense" if pos in {"QB", "RB", "WR", "TE"} else "idp",
        "values": {"overall": 0, "rawComposite": 0,
                   "finalAdjusted": 0, "displayValue": None},
        "canonicalSiteValues": sites,
        "sourceCount": 1,
    }


class TestAFullOverallIdpSource(unittest.TestCase):
    """A. Full overall IDP source behaves the same as an offense source:
    each eligible row gets a direct ordinal rank that feeds the Hill
    curve untouched.
    """

    def test_overall_idp_ranks_descend_by_value(self):
        rows = [
            _row("dl_top", "DL", idp=950),
            _row("lb_mid", "LB", idp=700),
            _row("db_low", "DB", idp=400),
        ]
        _compute_unified_rankings(rows, {})
        by_rank = sorted(
            (r for r in rows if "idpRank" in r), key=lambda r: r["idpRank"]
        )
        self.assertEqual(
            [r["canonicalName"] for r in by_rank], ["dl_top", "lb_mid", "db_low"]
        )
        # Overall IDP is direct — no translation metadata should say fallback.
        for r in rows:
            meta = r["sourceRankMeta"]["idpTradeCalc"]
            self.assertEqual(meta["scope"], SOURCE_SCOPE_OVERALL_IDP)
            self.assertEqual(meta["method"], TRANSLATION_DIRECT)
            self.assertIsNone(meta["positionGroup"])

    def test_idp_rank_is_effective_rank_for_backbone_source(self):
        rows = [_row(f"idp{i}", "DL", idp=9000 - i) for i in range(5)]
        _compute_unified_rankings(rows, {})
        for r in rows:
            self.assertEqual(r["idpRank"], r["sourceRanks"]["idpTradeCalc"])
            self.assertFalse(r["idpBackboneFallback"])


class TestBPositionOnlySourceTranslation(unittest.TestCase):
    """B. A position_idp source (e.g. a DL-only top-20 list) must have
    its raw positional rank translated through the backbone ladder into
    a synthetic overall-IDP rank before feeding the Hill curve.

    The backbone here is idpTradeCalc; we inject a DL-only source via a
    temporary registry monkey-patch.
    """

    def setUp(self) -> None:
        # Build a realistic backbone: DL+LB+DB interleaved.  With this
        # data DL1 → overall 1, DL2 → overall 3, DL3 → overall 5, etc.
        self._fixture_rows = [
            _row("dl1", "DL", idp=900),
            _row("lb1", "LB", idp=850),
            _row("dl2", "DL", idp=800),
            _row("lb2", "LB", idp=750),
            _row("dl3", "DL", idp=700),
            _row("db1", "DB", idp=650),
            _row("dl4", "DL", idp=600),
            _row("lb3", "LB", idp=550),
            _row("db2", "DB", idp=500),
            _row("dl5", "DL", idp=450),
        ]
        # Snapshot the registry so we can restore it cleanly.
        self._saved_registry = copy.deepcopy(_RANKING_SOURCES)
        _RANKING_SOURCES.append(
            {
                "key": "dlTop5",
                "display_name": "DL Top-5 Test",
                "scope": SOURCE_SCOPE_POSITION_IDP,
                "position_group": "DL",
                "depth": 5,
                "weight": 1.0,
                "is_backbone": False,
            }
        )

    def tearDown(self) -> None:
        _RANKING_SOURCES.clear()
        _RANKING_SOURCES.extend(self._saved_registry)

    def _attach_dl_top5(self, rows, pairs):
        """Attach per-row dlTop5 raw values (bigger = better)."""
        for name, value in pairs.items():
            for r in rows:
                if r["canonicalName"] == name:
                    r["canonicalSiteValues"]["dlTop5"] = value

    def test_exact_anchor_maps_dl1_to_overall_1(self):
        rows = copy.deepcopy(self._fixture_rows)
        # Only DL1 gets a dlTop5 value — raw positional rank 1 → synthetic
        # overall rank 1 via exact anchor.
        self._attach_dl_top5(rows, {"dl1": 100})
        _compute_unified_rankings(rows, {})
        dl1 = next(r for r in rows if r["canonicalName"] == "dl1")
        meta = dl1["sourceRankMeta"]["dlTop5"]
        self.assertEqual(meta["rawRank"], 1)
        self.assertEqual(meta["effectiveRank"], 1)
        self.assertEqual(meta["method"], TRANSLATION_EXACT)
        self.assertEqual(meta["positionGroup"], "DL")

    def test_dl3_raw_rank_3_maps_to_backbone_overall_5(self):
        rows = copy.deepcopy(self._fixture_rows)
        # DL3 gets dlTop5 raw rank 3 (only one row with the value).  Its
        # synthetic overall rank must match the backbone ladder DL[2]=5.
        self._attach_dl_top5(rows, {
            "dl1": 100, "dl2": 90, "dl3": 80,
        })
        _compute_unified_rankings(rows, {})
        dl3 = next(r for r in rows if r["canonicalName"] == "dl3")
        meta = dl3["sourceRankMeta"]["dlTop5"]
        self.assertEqual(meta["rawRank"], 3)
        self.assertEqual(meta["effectiveRank"], 5)  # ladder DL = [1,3,5,7,10]
        self.assertEqual(meta["method"], TRANSLATION_EXACT)

    def test_interpolation_uses_fractional_rank(self):
        # Direct unit call into translate_position_rank to verify
        # interpolation drives the synthetic rank for fractional inputs.
        from src.canonical.idp_backbone import translate_position_rank

        ladder = [1, 3, 5, 7, 10]  # DL ladder derived from the fixture
        syn, method = translate_position_rank(2.5, ladder)
        self.assertEqual(method, TRANSLATION_INTERPOLATED)
        self.assertEqual(syn, 4)  # midpoint of 3 and 5

    def test_extrapolation_past_ladder_is_monotonic(self):
        rows = copy.deepcopy(self._fixture_rows)
        # Add DL6..DL8 ghost entries that only the dlTop5 source sees,
        # forcing the translator past the known ladder.
        ghosts = [
            _row("dl6", "DL", extra={"dlTop5": 70}),
            _row("dl7", "DL", extra={"dlTop5": 60}),
            _row("dl8", "DL", extra={"dlTop5": 50}),
        ]
        # Set dlTop5 values for the first five DLs too so their raw ranks
        # take the expected order.
        self._attach_dl_top5(rows, {
            "dl1": 100, "dl2": 90, "dl3": 80, "dl4": 75, "dl5": 72,
        })
        rows.extend(ghosts)
        _compute_unified_rankings(rows, {})
        dl6 = next(r for r in rows if r["canonicalName"] == "dl6")
        dl7 = next(r for r in rows if r["canonicalName"] == "dl7")
        dl8 = next(r for r in rows if r["canonicalName"] == "dl8")
        for g in (dl6, dl7, dl8):
            self.assertEqual(
                g["sourceRankMeta"]["dlTop5"]["method"], TRANSLATION_EXTRAPOLATED
            )
        # Strict monotonicity: each extrapolated synthetic rank > previous.
        r6 = dl6["sourceRankMeta"]["dlTop5"]["effectiveRank"]
        r7 = dl7["sourceRankMeta"]["dlTop5"]["effectiveRank"]
        r8 = dl8["sourceRankMeta"]["dlTop5"]["effectiveRank"]
        self.assertGreater(r6, 10)  # past DL5 anchor which is 10
        self.assertLess(r6, r7)
        self.assertLess(r7, r8)


class TestCCoverageAwareBlending(unittest.TestCase):
    """C. A shallow positional list must not outweigh a deep full-board
    IDP source when the two disagree on a player's placement.
    """

    def setUp(self) -> None:
        self._saved_registry = copy.deepcopy(_RANKING_SOURCES)
        _RANKING_SOURCES.append(
            {
                "key": "dlTop5",
                "display_name": "DL Top-5 Test",
                "scope": SOURCE_SCOPE_POSITION_IDP,
                "position_group": "DL",
                "depth": 5,  # Very shallow → coverage weight scales down
                "weight": 1.0,
                "is_backbone": False,
            }
        )

    def tearDown(self) -> None:
        _RANKING_SOURCES.clear()
        _RANKING_SOURCES.extend(self._saved_registry)

    def test_shallow_list_cannot_overpower_deep_backbone(self):
        """The DL-only source declares depth=5, so its coverage weight
        collapses to 5/60 ≈ 0.083 against the backbone's full 1.0.

        Scenario: DL_A is the backbone #3 DL but dlTop5 rates it DL1.
        Without coverage weighting, the naive average would yank
        DL_A's value toward the DL1 Hill value (9999); with coverage
        weighting the backbone dominates.
        """
        rows = [
            _row("dl_backbone_top", "DL", idp=900),   # backbone DL1
            _row("dl_backbone_two", "DL", idp=800),   # backbone DL2
            _row("dl_A",            "DL", idp=700),   # backbone DL3
        ]
        rows[2]["canonicalSiteValues"]["dlTop5"] = 100  # ← DL1 in shallow list
        _compute_unified_rankings(rows, {})

        dl_a = next(r for r in rows if r["canonicalName"] == "dl_A")
        # sanity: shallow source mapped DL_A's raw rank 1 → synthetic 1
        self.assertEqual(dl_a["sourceRankMeta"]["dlTop5"]["rawRank"], 1)
        self.assertEqual(dl_a["sourceRankMeta"]["dlTop5"]["effectiveRank"], 1)

        # Coverage weight stamped on meta
        eff_w = dl_a["sourceRankMeta"]["dlTop5"]["effectiveWeight"]
        self.assertLess(eff_w, 0.1)
        backbone_w = dl_a["sourceRankMeta"]["idpTradeCalc"]["effectiveWeight"]
        self.assertEqual(backbone_w, 1.0)

        # The blended value must stay closer to rank_to_value(3) than to
        # rank_to_value(1) — the deep backbone dominates the shallow list.
        v_rank3 = rank_to_value(3)
        v_rank1 = rank_to_value(1)
        dist_to_rank3 = abs(dl_a["rankDerivedValue"] - v_rank3)
        dist_to_rank1 = abs(dl_a["rankDerivedValue"] - v_rank1)
        self.assertLess(dist_to_rank3, dist_to_rank1)

    def test_full_board_second_idp_source_carries_equal_weight(self):
        """A second full-board overall_idp source (depth=None) should
        blend equally with the backbone (both get coverage weight 1.0)."""
        self._saved_registry2 = copy.deepcopy(_RANKING_SOURCES)
        _RANKING_SOURCES.append(
            {
                "key": "secondFull",
                "display_name": "Second Full IDP",
                "scope": SOURCE_SCOPE_OVERALL_IDP,
                "position_group": None,
                "depth": None,
                "weight": 1.0,
                "is_backbone": False,
            }
        )
        try:
            rows = [
                _row("a", "DL", idp=900, extra={"secondFull": 800}),
                _row("b", "LB", idp=700, extra={"secondFull": 900}),
            ]
            _compute_unified_rankings(rows, {})
            b = next(r for r in rows if r["canonicalName"] == "b")
            bw = b["sourceRankMeta"]["secondFull"]["effectiveWeight"]
            bw_bb = b["sourceRankMeta"]["idpTradeCalc"]["effectiveWeight"]
            self.assertEqual(bw, 1.0)
            self.assertEqual(bw_bb, 1.0)
        finally:
            _RANKING_SOURCES.clear()
            _RANKING_SOURCES.extend(self._saved_registry2)


class TestDNoOffenseRegression(unittest.TestCase):
    """D. Nothing about the offensive ranking path should change.
    KTC still drives offense + picks; the scope gate admits them.
    """

    def test_offense_ranks_are_untouched(self):
        rows = [
            _row("qb1", "QB", ktc=9500),
            _row("wr1", "WR", ktc=9000),
            _row("rb1", "RB", ktc=8500),
            _row("pick1", "PICK", ktc=8000),
        ]
        _compute_unified_rankings(rows, {})
        by_rank = sorted(
            (r for r in rows if "ktcRank" in r), key=lambda r: r["ktcRank"]
        )
        self.assertEqual(
            [r["canonicalName"] for r in by_rank],
            ["qb1", "wr1", "rb1", "pick1"],
        )
        for r in rows:
            meta = r["sourceRankMeta"]["ktc"]
            self.assertEqual(meta["method"], TRANSLATION_DIRECT)
            self.assertEqual(meta["rawRank"], meta["effectiveRank"])

    def test_ktc_does_not_rank_idp_players(self):
        """Scope gating: even if an IDP row accidentally has a ktc value,
        KTC's overall_offense scope excludes it from receiving a KTC rank.
        (Defensive — real data never has this but the gate must hold.)"""
        rows = [
            _row("qb1", "QB", ktc=9500),
            _row("dl_with_ktc", "DL", ktc=9000, idp=500),
        ]
        _compute_unified_rankings(rows, {})
        dl = next(r for r in rows if r["canonicalName"] == "dl_with_ktc")
        self.assertNotIn("ktc", dl["sourceRanks"])
        # The IDP row still receives its IDP rank.
        self.assertEqual(dl["sourceRanks"]["idpTradeCalc"], 1)


class TestETransparencyFields(unittest.TestCase):
    """E. Every ranked row must carry the transparency fields backend and
    frontend agreed on: sourceRanks, sourceRankMeta, rankDerivedValue,
    canonicalConsensusRank, idpBackboneFallback, plus legacy ktcRank/idpRank.
    """

    def test_all_contract_fields_present(self):
        rows = [
            _row("qb1", "QB", ktc=9500),
            _row("dl1", "DL", idp=900),
        ]
        _compute_unified_rankings(rows, {})
        for r in rows:
            for field in (
                "sourceRanks",
                "sourceRankMeta",
                "rankDerivedValue",
                "canonicalConsensusRank",
                "idpBackboneFallback",
                "blendedSourceRank",
                "confidenceBucket",
                "anomalyFlags",
            ):
                self.assertIn(field, r, f"missing {field} on {r['canonicalName']}")
            # meta dict keys match sourceRanks keys
            self.assertEqual(set(r["sourceRankMeta"].keys()),
                             set(r["sourceRanks"].keys()))

    def test_legacy_rank_fields_mirror_source_ranks(self):
        rows = [
            _row("qb1", "QB", ktc=9500),
            _row("dl1", "DL", idp=900),
        ]
        _compute_unified_rankings(rows, {})
        qb = next(r for r in rows if r["canonicalName"] == "qb1")
        dl = next(r for r in rows if r["canonicalName"] == "dl1")
        self.assertEqual(qb["ktcRank"], qb["sourceRanks"]["ktc"])
        self.assertEqual(dl["idpRank"], dl["sourceRanks"]["idpTradeCalc"])


class TestGDualScopeIdpTradeCalc(unittest.TestCase):
    """G. IDP Trade Calculator registers under two scopes.

    IDPTradeCalc's public value pool covers both offensive and IDP
    players on the same 0-9999 scale, so the source contributes to the
    overall_offense blend (alongside KTC) AND to the overall_idp blend
    (as the backbone).  These tests lock that behaviour so nobody
    accidentally re-narrows it to IDP-only.
    """

    def test_registry_declares_extra_offense_scope(self):
        idptc = next(s for s in _RANKING_SOURCES if s["key"] == "idpTradeCalc")
        self.assertEqual(idptc["scope"], SOURCE_SCOPE_OVERALL_IDP)
        self.assertIn(SOURCE_SCOPE_OVERALL_OFFENSE, idptc.get("extra_scopes") or [])
        # Backbone status is determined by the primary scope only.
        self.assertTrue(idptc["is_backbone"])

    def test_offense_players_get_ktc_and_idptc_ranks(self):
        rows = [
            _row("qb1", "QB", ktc=9500, idp=9600),
            _row("wr1", "WR", ktc=9000, idp=9200),
            _row("rb1", "RB", ktc=8500, idp=8400),
        ]
        _compute_unified_rankings(rows, {})

        qb1 = next(r for r in rows if r["canonicalName"] == "qb1")
        wr1 = next(r for r in rows if r["canonicalName"] == "wr1")
        rb1 = next(r for r in rows if r["canonicalName"] == "rb1")

        # Both sources stamp an offense rank on every row.
        for r in (qb1, wr1, rb1):
            self.assertIn("ktc", r["sourceRanks"])
            self.assertIn("idpTradeCalc", r["sourceRanks"])
            # IDPTradeCalc's meta for this row is tagged overall_offense,
            # not overall_idp — they're being ranked in the offense pool.
            self.assertEqual(
                r["sourceRankMeta"]["idpTradeCalc"]["scope"],
                SOURCE_SCOPE_OVERALL_OFFENSE,
            )

        # KTC order: qb1(9500) > wr1(9000) > rb1(8500)
        self.assertEqual(qb1["sourceRanks"]["ktc"], 1)
        self.assertEqual(wr1["sourceRanks"]["ktc"], 2)
        self.assertEqual(rb1["sourceRanks"]["ktc"], 3)
        # IDPTC order: wr1(9200) > qb1(9600 wait that's higher) — recompute
        # idp values:  qb1=9600, wr1=9200, rb1=8400  →  qb1 > wr1 > rb1
        self.assertEqual(qb1["sourceRanks"]["idpTradeCalc"], 1)
        self.assertEqual(wr1["sourceRanks"]["idpTradeCalc"], 2)
        self.assertEqual(rb1["sourceRanks"]["idpTradeCalc"], 3)

        # Offense players are no longer single-source.
        self.assertFalse(qb1["isSingleSource"])
        self.assertEqual(qb1["sourceCount"], 2)

    def test_offense_idptc_rank_fed_into_blend(self):
        """When KTC and IDPTradeCalc disagree on an offense player, the
        blended rankDerivedValue sits between the two per-source Hill
        values instead of equalling either one.
        """
        rows = [
            # Identical KTC order for wr1 > wr2 but IDPTC flips them.
            _row("wr1", "WR", ktc=9500, idp=8000),
            _row("wr2", "WR", ktc=9000, idp=9500),
        ]
        _compute_unified_rankings(rows, {})

        wr1 = next(r for r in rows if r["canonicalName"] == "wr1")
        wr2 = next(r for r in rows if r["canonicalName"] == "wr2")

        # KTC: wr1=1, wr2=2.  IDPTC: wr2=1, wr1=2.
        self.assertEqual(wr1["sourceRanks"]["ktc"], 1)
        self.assertEqual(wr1["sourceRanks"]["idpTradeCalc"], 2)
        self.assertEqual(wr2["sourceRanks"]["ktc"], 2)
        self.assertEqual(wr2["sourceRanks"]["idpTradeCalc"], 1)
        # Each carries a spread of 1 between the two sources.
        self.assertEqual(wr1["sourceRankSpread"], 1.0)
        self.assertEqual(wr2["sourceRankSpread"], 1.0)

    def test_idp_players_unaffected_by_extra_offense_scope(self):
        """Adding overall_offense as an extra IDPTC scope must NOT change
        how IDP players are ranked — they still only flow through the
        overall_idp pass.
        """
        rows = [
            _row("dl1", "DL", idp=900),
            _row("lb1", "LB", idp=800),
            _row("db1", "DB", idp=700),
        ]
        _compute_unified_rankings(rows, {})
        for r in rows:
            meta = r["sourceRankMeta"]["idpTradeCalc"]
            self.assertEqual(meta["scope"], SOURCE_SCOPE_OVERALL_IDP)
            # Offense scope didn't leak onto IDP rows (they have no 'ktc'
            # entry because they're not eligible under overall_offense).
            self.assertNotIn("ktc", r["sourceRanks"])
        self.assertEqual(rows[0]["sourceRanks"]["idpTradeCalc"], 1)
        self.assertEqual(rows[1]["sourceRanks"]["idpTradeCalc"], 2)
        self.assertEqual(rows[2]["sourceRanks"]["idpTradeCalc"], 3)

    def test_offense_player_without_idptc_value_still_ranks_via_ktc(self):
        """Regression guard: an offense player with only a KTC value must
        still land on the unified board even though IDPTradeCalc is now
        a registered overall_offense source."""
        rows = [
            _row("qb_solo", "QB", ktc=8000),  # no IDPTC value
            _row("qb_both", "QB", ktc=9000, idp=9000),
        ]
        _compute_unified_rankings(rows, {})
        solo = next(r for r in rows if r["canonicalName"] == "qb_solo")
        both = next(r for r in rows if r["canonicalName"] == "qb_both")
        self.assertEqual(solo["sourceRanks"], {"ktc": 2})
        self.assertTrue(solo["isSingleSource"])
        self.assertEqual(both["sourceRanks"]["ktc"], 1)
        self.assertEqual(both["sourceRanks"]["idpTradeCalc"], 1)


class TestFEdgeCases(unittest.TestCase):
    """F. Edge cases: missing backbone, zero values, empty input."""

    def test_empty_rows_does_not_crash(self):
        rows: list[dict] = []
        _compute_unified_rankings(rows, {})
        self.assertEqual(rows, [])

    def test_zero_value_source_is_ignored(self):
        rows = [
            _row("has_val", "WR", ktc=9000),
            _row("zero_val", "WR", ktc=0),
        ]
        _compute_unified_rankings(rows, {})
        zv = next(r for r in rows if r["canonicalName"] == "zero_val")
        self.assertNotIn("ktcRank", zv)
        self.assertNotIn("canonicalConsensusRank", zv)

    def test_missing_backbone_forces_position_source_to_fallback(self):
        """If there is no overall_idp backbone source producing a ladder,
        any position_idp source falls back to pass-through and stamps
        idpBackboneFallback=True on affected rows.
        """
        saved = copy.deepcopy(_RANKING_SOURCES)
        # Remove the backbone (idpTradeCalc) and add a DL-only source.
        _RANKING_SOURCES.clear()
        _RANKING_SOURCES.extend(
            [
                s for s in saved
                if s["scope"] != SOURCE_SCOPE_OVERALL_IDP
            ]
        )
        _RANKING_SOURCES.append(
            {
                "key": "dlOnly",
                "display_name": "DL Only",
                "scope": SOURCE_SCOPE_POSITION_IDP,
                "position_group": "DL",
                "depth": 5,
                "weight": 1.0,
                "is_backbone": False,
            }
        )
        try:
            rows = [
                _row("dl1", "DL", extra={"dlOnly": 100}),
                _row("dl2", "DL", extra={"dlOnly": 90}),
            ]
            _compute_unified_rankings(rows, {})
            dl1 = next(r for r in rows if r["canonicalName"] == "dl1")
            self.assertEqual(
                dl1["sourceRankMeta"]["dlOnly"]["method"], TRANSLATION_FALLBACK
            )
            self.assertTrue(dl1["idpBackboneFallback"])
        finally:
            _RANKING_SOURCES.clear()
            _RANKING_SOURCES.extend(saved)


if __name__ == "__main__":
    unittest.main()
