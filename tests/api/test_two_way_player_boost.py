"""The two-way player boost must not invent a value the board disagrees with.

WHY THIS EXISTS
===============
``_apply_two_way_player_boost`` is a post-blend OVERRIDE: it writes
``rankDerivedValue`` outright.  Until 2026-08-04 it had exactly one
audit field stamped on one row and **no test of any kind** — no
assertion on the value it produced, on the sources it used, or on the
arithmetic that got there.  A number went to users that nothing in the
repository could disagree with.

What it did was feed a RAW WITHIN-SOURCE ordinal into the COMBINED-pool
percentile curve::

    p = (rank - 1) / (_PERCENTILE_REFERENCE_N - 1)   # denominator = 500
    alt = percentile_to_value(p, IDP master curve)

``idpShow`` rank 5 means "5th best IDP".  Read through a combined-pool
denominator it means "5th most valuable asset on the entire board", and
the curve duly returned **9304** on a scale whose maximum is 9999.

The board refutes that number directly, which is what makes this
testable rather than a matter of opinion: on the 2026-07-30 payload the
*actual* ``idpShow`` #1 (Aidan Hutchinson) is worth 6362, and #2-#4 are
5876 / 5875 / 4803.  A top-5 IDP is worth ~4.8k-6.4k.  No defender is
worth 9304, so no defensive valuation of a two-way player can be
either.

THE INVARIANT
=============
An alt-family contribution is a claim about where a player sits *among
that family*.  It therefore cannot exceed what the board pays the best
real member of that family.  That is the assertion below, and it is the
one the old code violated by 46%.

WHY NOT PIN THE NUMBER ITSELF
=============================
A pinned 4506 would go stale on every market move and teach the next
reader to re-baseline it, which is the green-by-construction failure
ADR-008 (``docs/roster-trade-intelligence/DECISIONS.md``) documents.
The ceiling invariant holds across any payload, so it stays honest
without maintenance.  ``test_ladder_translation_is_bounded_by_the_ladder``
pins the mechanism separately.

NOT ``livedata``-MARKED — this is pure logic on synthetic rows and must
block the CI hard gate.  The defect it guards shipped for months behind
a suite that ran green the whole time.
"""

from __future__ import annotations

import unittest
from typing import Any

from src.api import data_contract as dc
from src.api.data_contract import _apply_two_way_player_boost, _compute_unified_rankings
from src.sources import freshness as dc_freshness


def _row(name: str, position: str, **sites: Any) -> dict[str, Any]:
    """A contract row shaped the way ``_compute_unified_rankings`` expects.

    Rank-signal sources also get ``sourceOriginalRanks``, as the CSV loader
    stamps it on every row a rank board matches: the boost's alt LADDER is
    built from it.  Without it the ladder had no rows, every rank source
    silently dropped out of the alt value, and the ladder this module claims
    to pin never ran.
    """
    site_values: dict[str, Any] = dict(sites)
    original_ranks = {
        key: float((dc._RANK_TO_SYNTHETIC_VALUE_OFFSET * 100 - v) / 100)
        for key, v in site_values.items()
        if v and v >= dc._RANK_TO_SYNTHETIC_VALUE_OFFSET * 50
    }
    return {
        "canonicalName": name,
        "displayName": name,
        "position": position,
        "assetClass": "idp" if position in ("DL", "LB", "DB") else "offense",
        "canonicalSiteValues": site_values,
        "sourceOriginalRanks": original_ranks,
        "values": {
            "overall": max((v or 0) for v in site_values.values()) if site_values else 0,
            "rawComposite": None,
            "finalAdjusted": None,
            "displayValue": None,
        },
    }


def _synthetic_rank(rank: int) -> int:
    """Encode a within-source rank the way the CSV loader does."""
    return dc._RANK_TO_SYNTHETIC_VALUE_OFFSET * 100 - rank * 100


def _build_board() -> list[dict[str, Any]]:
    """A board with real IDP players plus one dual-eligible offense row.

    Shaped to mirror the live board in the one respect this test depends
    on: **the top of the combined board is offense, so the best IDP sits
    well below the display maximum.**

    That is not cosmetic. A first draft of this fixture gave defenders
    the highest ``idpTradeCalc`` values on the board, which made the best
    IDP 9999 — and a ceiling of 9999 is a ceiling nothing can breach, so
    the headline assertion passed even under the mutation it exists to
    catch. Mutation testing caught the vacuous guard; keep the shape.

    Real-board justification: ``idpTradeCalc`` is a FULL-ROSTER
    calculator that prices offense too, so its site maximum belongs to
    an offense player and defenders normalise below it. On the
    2026-07-30 payload the best IDP is 6362 against a 9999 scale.
    Hence offense rows carry the top ``idpTradeCalc`` values here.

    Defenders also carry an INDEPENDENT IDP lineage (``fantasyProsIdp``),
    and so does the two-way player.  Owner closeout 2026-10-18 Decision 2
    makes ``idpTradeCalc`` and its correlated ``idpShowCombined`` copy ONE
    lineage on a defensive row where both vote, so a board priced by those
    two alone rests every defender on one lineage: all of them take the
    single-source haircut (best IDP ~2.5k), and so does the two-way alt
    value, and the ceiling below compared two haircut numbers that hid the
    untranslated-Hill mutation.  The live board's top defenders carry
    independent IDP evidence; this keeps that shape.  The one-lineage case
    is pinned on its own in ``TestAltEvidenceFollowsRowLevelRules``.
    """
    rows: list[dict[str, Any]] = []
    for i in range(1, 21):
        rows.append(
            _row(
                f"Defender {i:02d}",
                "LB",
                idpTradeCalc=6400 - i * 150,
                idpShowCombined=_synthetic_rank(i),
                fantasyProsIdp=_synthetic_rank(i),
            )
        )
    # Offense carries the top of the board — including the top
    # idpTradeCalc values, as the real full-roster calculator does.
    for i in range(1, 21):
        rows.append(
            _row(
                f"Receiver {i:02d}",
                "WR",
                ktcCrowdSfTep=9900 - i * 200,
                idpTradeCalc=9900 - i * 120,
            )
        )
    # The two-way player: offense-classed, but ranked 5th by an IDP source.
    rows.append(
        _row(
            "Two Way Player",
            "WR",
            ktcCrowdSfTep=3000,
            idpShowCombined=_synthetic_rank(5),
            idpTradeCalc=5200,
            fantasyProsIdp=_synthetic_rank(5),
        )
    )
    return rows


class TestTwoWayBoostCeiling(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = dict(dc._TWO_WAY_PLAYERS)
        dc._TWO_WAY_PLAYERS.clear()
        dc._TWO_WAY_PLAYERS["Two Way Player"] = "DB"

    def tearDown(self) -> None:
        dc._TWO_WAY_PLAYERS.clear()
        dc._TWO_WAY_PLAYERS.update(self._saved)

    def _priced_board(self) -> list[dict[str, Any]]:
        rows = _build_board()
        _compute_unified_rankings(rows, {})
        _apply_two_way_player_boost(rows, {})
        return rows

    def test_alt_family_value_cannot_exceed_the_best_real_player_of_that_family(
        self,
    ) -> None:
        """The invariant the untranslated Hill violated by 46%."""
        rows = self._priced_board()
        best_idp = max(
            (r.get("rankDerivedValue") or 0) for r in rows if r.get("assetClass") == "idp"
        )

        # NON-VACUITY GUARD. If the best IDP is at the top of the display
        # scale then "cannot exceed the best IDP" forbids nothing, and the
        # assertion below would pass for any value whatsoever. That is
        # exactly what the first draft of this fixture did. Fail loudly
        # rather than silently guarding nothing.
        self.assertLess(
            best_idp,
            0.9 * dc._DISPLAY_SCALE_MAX,
            msg=(
                f"FIXTURE IS VACUOUS: best IDP is {best_idp} of a "
                f"{dc._DISPLAY_SCALE_MAX} scale, so the ceiling assertion below "
                f"cannot fail. The fixture must keep offense at the top of the "
                f"board (see _build_board's docstring) — on the real board the "
                f"best IDP is 6362."
            ),
        )

        two_way = next(r for r in rows if r["canonicalName"] == "Two Way Player")
        audit = two_way.get("twoWayPlayerBoost")
        self.assertIsNotNone(audit, "the boost must always stamp its audit block")
        alt_value = audit["altFamilyValue"]

        self.assertLessEqual(
            alt_value,
            best_idp,
            msg=(
                f"two-way alt-family value {alt_value} exceeds the best real IDP on the "
                f"board ({best_idp}). An alt-family value is a claim about standing "
                f"WITHIN that family, so it cannot outrank every real member of it. "
                f"This is what a raw within-source ordinal fed through the "
                f"combined-pool percentile denominator produces — see "
                f"_apply_two_way_player_boost's docstring and use the ladder."
            ),
        )

    def test_alt_value_never_reaches_the_top_of_the_display_scale(self) -> None:
        """Second, cruder net: the old path returned 9304 of a 9999 max."""
        rows = self._priced_board()
        two_way = next(r for r in rows if r["canonicalName"] == "Two Way Player")
        alt_value = two_way["twoWayPlayerBoost"]["altFamilyValue"]
        self.assertLess(
            alt_value,
            0.85 * dc._DISPLAY_SCALE_MAX,
            msg=(
                f"alt-family value {alt_value} is in the top 15% of the display scale "
                f"for a player no source ranks near the top of the whole board."
            ),
        )

    def test_boost_is_max_of_primary_and_alt_not_a_sum(self) -> None:
        """Pins the documented policy: max(), never additive.

        The additive-production argument for a dual-eligible player is a
        FUNDAMENTAL one and lives in BDVM, which folds both stat lines
        into one projection record. Encoding it on the market board
        would mean inventing a premium with no market evidence.
        """
        rows = self._priced_board()
        two_way = next(r for r in rows if r["canonicalName"] == "Two Way Player")
        audit = two_way["twoWayPlayerBoost"]
        final = two_way["rankDerivedValue"]
        self.assertEqual(
            final,
            max(audit["altFamilyValue"], audit["primaryFamilyValue"]),
            msg="rankDerivedValue must be max(primary, alt) — not a sum, not the alt alone",
        )


class TestAltLadderTranslation(unittest.TestCase):
    """Unit-level pins on the mechanism itself."""

    def test_ladder_translation_is_bounded_by_the_ladder(self) -> None:
        """Interpolation clamps; it never extrapolates past the evidence.

        Extrapolating is exactly how the stage manufactured a value
        above the whole family's ceiling.
        """
        rows = _build_board()
        _compute_unified_rankings(rows, {})
        dc._TWO_WAY_PLAYERS.clear()
        dc._TWO_WAY_PLAYERS["Two Way Player"] = "DB"
        try:
            _apply_two_way_player_boost(rows, {})
        finally:
            dc._TWO_WAY_PLAYERS.clear()
            dc._TWO_WAY_PLAYERS["Travis Hunter"] = "DB"

        idp_values = [r.get("rankDerivedValue") or 0 for r in rows if r.get("assetClass") == "idp"]
        two_way = next(r for r in rows if r["canonicalName"] == "Two Way Player")
        alt_value = two_way["twoWayPlayerBoost"]["altFamilyValue"]
        self.assertGreaterEqual(alt_value, min(idp_values))
        self.assertLessEqual(alt_value, max(idp_values))

    def test_the_only_two_way_player_is_the_one_sleeper_says_is_dual_eligible(
        self,
    ) -> None:
        """``_TWO_WAY_PLAYERS`` is an enumeration, and it should stay tiny.

        Verified against Sleeper's full player list on 2026-08-04:
        Travis Hunter (``fantasy_positions: ['DB','WR']``) is the ONLY
        active NFL player with both offense and IDP eligibility. So the
        hardcoded dict is an accurate census of a population of one, not
        a shortcut — worth pinning so a future edit that grows it is a
        deliberate act with a Sleeper check behind it.
        """
        self.assertEqual(dict(dc._TWO_WAY_PLAYERS), {"Travis Hunter": "DB"})


_D2_RULES = frozenset(r["id"] for r in dc.ROW_SCOPED_CORRELATION_GROUPS)


def _one_lineage_board() -> list[dict[str, Any]]:
    """``_build_board`` with the two-way player's independent lineage removed.

    His alt evidence is then the IDP Trade Calculator and its correlated IDP
    Show copy only: Travis Hunter's shape on the live board (DLF IDP is
    policy-held; FantasyPros IDP and Draft Sharks IDP do not list him).
    """
    rows = _build_board()
    two_way = next(r for r in rows if r["canonicalName"] == "Two Way Player")
    del two_way["canonicalSiteValues"]["fantasyProsIdp"]
    del two_way["sourceOriginalRanks"]["fantasyProsIdp"]
    return rows


class _Quarantined:
    """Minimal ``SourceWeighting`` stand-in whose every row weighs 0."""

    measured = True
    health_state = "HEALTHY"
    health_factor = 1.0
    coverage = 1.0
    coverage_factor = 1.0

    def __init__(self, key: str) -> None:
        self.source_key = key
        self._sub = type("Sub", (), {"freshness": 0.0, "state": "QUARANTINED"})()
        self._sub.style = dc_freshness.STYLE_SNAPSHOT

    def subset_for(self, is_pick: bool) -> Any:
        return self._sub

    def factor_for_row(self, **_kw: Any) -> tuple[float, float]:
        return 0.0, 0.0

    def to_dict(self) -> dict[str, Any]:
        return {"sourceKey": self.source_key, "measured": True}


class TestAltEvidenceFollowsRowLevelRules(unittest.TestCase):
    """Owner closeout 2026-10-18 Decision 2 reaches the alt-family side door.

    Independent review: once D2 merged ``idpTradeCalc`` and its correlated
    ``idpShowCombined`` copy into one lineage, every real defender priced
    only by them kept 30% (the single-source haircut), while the boost --
    reading raw ``canonicalSiteValues`` -- still priced the two-way player's
    alt value off the same two copies at full value, and off a copy that did
    not even vote.  The alt value is now held to the rules a real member of
    the alt family is held to: only VOTING sources, lineages on the D2 map,
    and the retention when one lineage remains.
    """

    def setUp(self) -> None:
        self._saved = dict(dc._TWO_WAY_PLAYERS)
        dc._TWO_WAY_PLAYERS.clear()
        dc._TWO_WAY_PLAYERS["Two Way Player"] = "DB"

    def tearDown(self) -> None:
        dc._TWO_WAY_PLAYERS.clear()
        dc._TWO_WAY_PLAYERS.update(self._saved)

    @staticmethod
    def _two_way(rows: list[dict[str, Any]]) -> dict[str, Any]:
        return next(r for r in rows if r["canonicalName"] == "Two Way Player")

    def _boosted(self, **kwargs: Any) -> dict[str, Any]:
        rows = _one_lineage_board()
        _compute_unified_rankings(rows, {})
        _apply_two_way_player_boost(rows, {}, **kwargs)
        return self._two_way(rows)["twoWayPlayerBoost"]

    def test_one_merged_lineage_keeps_the_single_source_retention(self) -> None:
        audit = self._boosted(lineage_rules=_D2_RULES)
        self.assertEqual(audit["sourcesConsidered"], ["idpShowCombined", "idpTradeCalc"])
        self.assertEqual(audit["sharedLineageCaps"], sorted(_D2_RULES))
        self.assertEqual(audit["lineages"], ["idpShow"])
        self.assertTrue(audit["singleSourceValuePenaltyApplied"])
        self.assertAlmostEqual(
            audit["altFamilyValue"],
            audit["altFamilyValueBeforePenalty"] * dc._SINGLE_SOURCE_VALUE_RETENTION,
            delta=1,
        )
        # Parity: a REAL defender with exactly this evidence takes the same
        # haircut in the blend (the e7f8286e10 review fix).
        rows = _one_lineage_board() + [
            _row("Twin Defender", "DB", idpTradeCalc=5200, idpShowCombined=_synthetic_rank(5))
        ]
        _compute_unified_rankings(rows, {})
        twin = next(r for r in rows if r["canonicalName"] == "Twin Defender")
        self.assertEqual(twin.get("sharedLineageCaps"), sorted(_D2_RULES))
        self.assertTrue(twin.get("singleSourceValuePenaltyApplied"))

    def test_the_sparse_challenger_that_disables_the_retention_disables_it_here(self) -> None:
        audit = self._boosted(lineage_rules=_D2_RULES, single_lineage_retention=False)
        self.assertEqual(audit["lineages"], ["idpShow"])
        self.assertFalse(audit["singleSourceValuePenaltyApplied"])
        self.assertNotIn("altFamilyValueBeforePenalty", audit)

    def test_rollback_restores_the_pre_closeout_boost(self) -> None:
        """No lineage rule in force: the boost is main's, byte for byte."""
        off = self._boosted(lineage_rules=())
        on = self._boosted(lineage_rules=_D2_RULES)
        self.assertEqual(
            set(off),
            {"applied", "altFamily", "altFamilyValue", "primaryFamilyValue", "sourcesConsidered"},
        )
        self.assertEqual(off["sourcesConsidered"], on["sourcesConsidered"])
        self.assertEqual(off["altFamilyValue"], on["altFamilyValueBeforePenalty"])

    def test_a_withheld_copy_does_not_vote_and_does_not_merge(self) -> None:
        """Freshness / health weight 0: dropped from the value, never a zero,
        and still PRESENT evidence -- the haircut's no-cliff rule -- so the row
        is neither merged (the copy does not vote) nor haircut."""

        def weight(_row: Any, key: str, _alt: str) -> float:
            return 0.0 if key == "idpShowCombined" else 1.0

        audit = self._boosted(lineage_rules=_D2_RULES, alt_vote_weight=weight)
        self.assertEqual(audit["sourcesConsidered"], ["idpTradeCalc"])
        self.assertEqual(audit["freshnessExcludedSources"], ["idpShowCombined"])
        self.assertEqual(audit["sharedLineageCaps"], [])
        self.assertEqual(audit["lineages"], ["idpShow", "idpTradeCalc"])
        self.assertFalse(audit["singleSourceValuePenaltyApplied"])
        # The value is the voting source's alone (value-direct: raw / board max).
        self.assertEqual(audit["altFamilyValue"], round(5200 / 9780 * 9999))

    def test_a_source_that_may_not_vote_is_not_present_evidence(self) -> None:
        """``None`` (inactive / held): not expected, so not present either --
        the alt value rests on one lineage, as a real row would."""

        def weight(_row: Any, key: str, _alt: str) -> float | None:
            return None if key == "idpShowCombined" else 1.0

        audit = self._boosted(lineage_rules=_D2_RULES, alt_vote_weight=weight)
        self.assertEqual(audit["sourcesConsidered"], ["idpTradeCalc"])
        self.assertEqual(audit["freshnessExcludedSources"], [])
        self.assertEqual(audit["lineages"], ["idpTradeCalc"])
        self.assertTrue(audit["singleSourceValuePenaltyApplied"])

    def test_the_build_asks_the_blends_own_vote_owner(self) -> None:
        """Through ``_compute_unified_rankings``: the active-source gate and the
        freshness owner decide, exactly as for a real row."""
        if not dc._enabled_row_scoped_correlation_rules():
            self.skipTest("idp_shared_correlation_cap is rolled back in this environment")
        # A seasonally inactive source casts no vote and is not expected: the
        # pre-closeout boost still read it from ``canonicalSiteValues``.
        rows = _build_board()
        _compute_unified_rankings(rows, {}, seasonally_inactive_sources={"fantasyProsIdp"})
        audit = self._two_way(rows)["twoWayPlayerBoost"]
        self.assertNotIn("fantasyProsIdp", audit["sourcesConsidered"])
        self.assertNotIn("fantasyProsIdp", audit["freshnessExcludedSources"])
        self.assertEqual(audit["lineages"], ["idpShow"])
        self.assertTrue(audit["singleSourceValuePenaltyApplied"])
        # A quarantined copy is withheld (weight 0), so it neither merges nor
        # leaves the row one-lineage.
        rows = _build_board()
        _compute_unified_rankings(
            rows, {}, source_weighting={"idpShowCombined": _Quarantined("idpShowCombined")}
        )
        audit = self._two_way(rows)["twoWayPlayerBoost"]
        self.assertNotIn("idpShowCombined", audit["sourcesConsidered"])
        self.assertEqual(audit["freshnessExcludedSources"], ["idpShowCombined"])
        self.assertEqual(audit["sharedLineageCaps"], [])
        self.assertEqual(audit["lineages"], ["fantasyPros", "idpShow", "idpTradeCalc"])
        self.assertFalse(audit["singleSourceValuePenaltyApplied"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
