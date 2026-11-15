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
from src.sources import freshness as _freshness


def _row(name: str, position: str, **sites: Any) -> dict[str, Any]:
    """A contract row shaped the way ``_compute_unified_rankings`` expects.

    Rank-signal sources also get ``sourceOriginalRanks``, as the CSV loader
    stamps it on every row a rank board matches (the prior boost's ladder is
    built from it, so without it the rollback path's ladder never ran).
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


def _receivers() -> list[dict[str, Any]]:
    # Offense carries the top of the board — including the top
    # idpTradeCalc values, as the real full-roster calculator does.
    return [
        _row(
            f"Receiver {i:02d}",
            "WR",
            ktcCrowdSfTep=9900 - i * 200,
            idpTradeCalc=9900 - i * 120,
        )
        for i in range(1, 21)
    ]


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

    Defenders and the two-way player carry three B10 families
    (``idpTradeCalc``, ``idpShowCombined``, ``fantasyProsIdp``), as the live
    board's top defenders carry several, so the ladder and the vote paths both
    run and nothing here is haircut.  The ONE-family shape — every defender
    resting on one family and haircut, the live shape that once broke the
    ceiling — is :func:`_one_family_board`.
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
    rows.extend(_receivers())
    # The two-way player: offense-classed, but ranked 5th by IDP sources.
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


def _one_family_board() -> list[dict[str, Any]]:
    """Every defender rests on ONE family (``idpTradeCalc``), so every one of
    them keeps the single-source retention — the board shape on which a
    two-way alt value once outranked every real member of its family.  The
    two-way player also carries an IDP Show rank that no real member's vote
    brackets (the source voted on no defender), so it is untranslated: his
    alt evidence is one family too."""
    rows = [_row(f"Defender {i:02d}", "LB", idpTradeCalc=6400 - i * 150) for i in range(1, 21)]
    rows.extend(_receivers())
    rows.append(
        _row(
            "Two Way Player",
            "WR",
            ktcCrowdSfTep=3000,
            idpShowCombined=_synthetic_rank(5),
            idpTradeCalc=5200,
        )
    )
    return rows


_BOARDS = {"three-family": _build_board, "one-family": _one_family_board}
#: (board, evidence_rules).  The prior boost (rules OFF, the rollback path)
#: is checked on the three-family board only: on the one-family board it
#: keeps its known defect, pinned in
#: ``test_the_rollback_path_keeps_its_known_one_family_defect``.
_CEILING_CASES = (("three-family", True), ("three-family", False), ("one-family", True))


class _TwoWayCase(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = dict(dc._TWO_WAY_PLAYERS)
        dc._TWO_WAY_PLAYERS.clear()
        dc._TWO_WAY_PLAYERS["Two Way Player"] = "DB"

    def tearDown(self) -> None:
        dc._TWO_WAY_PLAYERS.clear()
        dc._TWO_WAY_PLAYERS.update(self._saved)

    @staticmethod
    def _named(rows: list[dict[str, Any]], name: str) -> dict[str, Any]:
        return next(r for r in rows if r["canonicalName"] == name)

    def _priced_board(self, shape: str, **kwargs: Any) -> list[dict[str, Any]]:
        rows = _BOARDS[shape]()
        _compute_unified_rankings(rows, {})
        _apply_two_way_player_boost(rows, {}, **kwargs)
        return rows


class TestTwoWayBoostCeiling(_TwoWayCase):
    def test_alt_family_value_cannot_exceed_the_best_real_player_of_that_family(
        self,
    ) -> None:
        """The invariant the untranslated Hill violated by 46%, on both board
        shapes and on both the evidence-rule and the rollback path."""
        for shape, rules in _CEILING_CASES:
            with self.subTest(board=shape, evidence_rules=rules):
                rows = self._priced_board(shape, evidence_rules=rules)
                best_idp = max(
                    (r.get("rankDerivedValue") or 0) for r in rows if r.get("assetClass") == "idp"
                )
                # NON-VACUITY GUARD. If the best IDP is at the top of the
                # display scale then "cannot exceed the best IDP" forbids
                # nothing. Fail loudly rather than silently guarding nothing.
                self.assertLess(
                    best_idp,
                    0.9 * dc._DISPLAY_SCALE_MAX,
                    msg=(
                        f"FIXTURE IS VACUOUS: best IDP is {best_idp} of a "
                        f"{dc._DISPLAY_SCALE_MAX} scale (see _build_board's docstring)."
                    ),
                )
                audit = self._named(rows, "Two Way Player").get("twoWayPlayerBoost")
                self.assertIsNotNone(audit, "the boost must always stamp its audit block")
                self.assertLessEqual(
                    audit["altFamilyValue"],
                    best_idp,
                    msg=(
                        f"two-way alt-family value {audit['altFamilyValue']} exceeds the "
                        f"best real IDP on the board ({best_idp}). An alt-family value is "
                        f"a claim about standing WITHIN that family, so it cannot outrank "
                        f"every real member of it."
                    ),
                )

    def test_alt_value_never_reaches_the_top_of_the_display_scale(self) -> None:
        """Second, cruder net: the old path returned 9304 of a 9999 max."""
        for shape in _BOARDS:
            with self.subTest(board=shape):
                rows = self._priced_board(shape)
                alt_value = self._named(rows, "Two Way Player")["twoWayPlayerBoost"][
                    "altFamilyValue"
                ]
                self.assertLess(alt_value, 0.85 * dc._DISPLAY_SCALE_MAX)

    def test_boost_is_max_of_primary_and_alt_not_a_sum(self) -> None:
        """Pins the documented policy: max(), never additive.

        The additive-production argument for a dual-eligible player is a
        FUNDAMENTAL one and lives in BDVM, which folds both stat lines
        into one projection record. Encoding it on the market board
        would mean inventing a premium with no market evidence.
        """
        for shape in _BOARDS:
            with self.subTest(board=shape):
                rows = self._priced_board(shape)
                two_way = self._named(rows, "Two Way Player")
                audit = two_way["twoWayPlayerBoost"]
                self.assertEqual(
                    two_way["rankDerivedValue"],
                    max(audit["altFamilyValue"], audit["primaryFamilyValue"]),
                    msg="rankDerivedValue must be max(primary, alt) — not a sum, not the alt alone",
                )


class TestAltLadderTranslation(_TwoWayCase):
    """Unit-level pins on the mechanism itself."""

    def test_ladder_translation_is_bounded_by_the_ladder(self) -> None:
        """Interpolation clamps; it never extrapolates past the evidence.

        Extrapolating is exactly how the stage manufactured a value
        above the whole family's ceiling.  Both paths, both board shapes:
        the prior (rollback) path's board-value ladder, and the evidence
        rules' interpolation of real members' votes.
        """
        for shape, rules in _CEILING_CASES:
            with self.subTest(board=shape, evidence_rules=rules):
                rows = _BOARDS[shape]()
                dc._TWO_WAY_PLAYERS.clear()
                dc._TWO_WAY_PLAYERS["Travis Hunter"] = "DB"
                _compute_unified_rankings(rows, {})
                dc._TWO_WAY_PLAYERS.clear()
                dc._TWO_WAY_PLAYERS["Two Way Player"] = "DB"
                _apply_two_way_player_boost(rows, {}, evidence_rules=rules)
                idp_values = [
                    r.get("rankDerivedValue") or 0 for r in rows if r.get("assetClass") == "idp"
                ]
                alt_value = self._named(rows, "Two Way Player")["twoWayPlayerBoost"][
                    "altFamilyValue"
                ]
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
        dc._TWO_WAY_PLAYERS.clear()
        dc._TWO_WAY_PLAYERS.update(self._saved)
        self.assertEqual(dict(dc._TWO_WAY_PLAYERS), {"Travis Hunter": "DB"})


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
        self._sub.style = _freshness.STYLE_SNAPSHOT

    def subset_for(self, is_pick: bool) -> Any:
        return self._sub

    def factor_for_row(self, **_kw: Any) -> tuple[float, float]:
        return 0.0, 0.0

    def to_dict(self) -> dict[str, Any]:
        return {"sourceKey": self.source_key, "measured": True}


_TWIN_SITES = {
    "three-family": {
        "idpTradeCalc": 5200,
        "idpShowCombined": _synthetic_rank(5),
        "fantasyProsIdp": _synthetic_rank(5),
    },
    # IDP Show voted on no real member of this board, so the alt cannot
    # translate it; the twin carries the evidence the alt could translate.
    "one-family": {"idpTradeCalc": 5200},
}


class TestAltEvidenceIsARealMembersEvidence(_TwoWayCase):
    """Flag ``two_way_alt_evidence_rules`` (PR #1817 review; owner
    source-voting directive 2026-10-19).  The prior boost read raw
    ``canonicalSiteValues``: a quarantined, held or disabled source still
    priced the player, and its board-value ladder carried the members' own
    haircuts into the alt value, which the haircut then hit again.  The alt
    value must be what a REAL member of the family with the same votes gets."""

    def _twin_value(self, shape: str, **compute_kwargs: Any) -> int:
        rows = _BOARDS[shape]() + [_row("Twin Defender", "DB", **_TWIN_SITES[shape])]
        _compute_unified_rankings(rows, {}, **compute_kwargs)
        return int(self._named(rows, "Twin Defender")["rankDerivedValue"])

    def test_the_alt_value_equals_a_real_twins_value(self) -> None:
        """Same votes, same blend, the haircut applied ONCE: the alt value is
        the real twin's within rounding, on the haircut board shape too (where
        the prior ladder double-haircut it)."""
        for shape in _BOARDS:
            with self.subTest(board=shape):
                rows = self._priced_board(shape)
                audit = self._named(rows, "Two Way Player")["twoWayPlayerBoost"]
                self.assertEqual(audit["evidenceRule"], "alt_family_vote_state")
                self.assertAlmostEqual(audit["altFamilyValue"], self._twin_value(shape), delta=2)

    def test_one_family_alt_evidence_is_haircut_exactly_once(self) -> None:
        rows = self._priced_board("one-family")
        audit = self._named(rows, "Two Way Player")["twoWayPlayerBoost"]
        self.assertEqual(audit["sourcesConsidered"], ["idpTradeCalc"])
        self.assertEqual(audit["untranslatedSources"], ["idpShowCombined"])
        self.assertEqual(audit["families"], ["idpTradeCalc"])
        self.assertTrue(audit["singleSourceValuePenaltyApplied"])
        # The vote itself is value-direct (raw / board max), never a board
        # value that already carries a member's haircut.
        self.assertEqual(audit["altFamilyValueBeforePenalty"], round(5200 / 9780 * 9999))
        self.assertAlmostEqual(
            audit["altFamilyValue"],
            audit["altFamilyValueBeforePenalty"] * dc._SINGLE_SOURCE_VALUE_RETENTION,
            delta=1,
        )

    def test_separate_providers_are_separate_families(self) -> None:
        """Owner directive 2026-10-19: agreement between different providers is
        consensus, not duplication.  IDP Trade Calculator and IDP Show both
        voting is two families and no haircut."""
        rows = self._priced_board("three-family")
        audit = self._named(rows, "Two Way Player")["twoWayPlayerBoost"]
        self.assertEqual(audit["families"], ["fantasyPros", "idpShow", "idpTradeCalc"])
        self.assertFalse(audit["singleSourceValuePenaltyApplied"])

    def test_a_quarantined_copy_is_withheld_and_still_present_as_for_a_real_row(self) -> None:
        """The quarantine line behaves identically for the alt and a real row:
        the withheld source leaves the value and stays present evidence (the
        haircut's no-cliff rule)."""
        weighting = {"idpShowCombined": _Quarantined("idpShowCombined")}
        rows = _build_board()
        _compute_unified_rankings(rows, {}, source_weighting=weighting)
        audit = self._named(rows, "Two Way Player")["twoWayPlayerBoost"]
        self.assertEqual(audit["freshnessExcludedSources"], ["idpShowCombined"])
        self.assertNotIn("idpShowCombined", audit["sourcesConsidered"])
        self.assertIn("idpShow", audit["families"])
        self.assertFalse(audit["singleSourceValuePenaltyApplied"])
        self.assertAlmostEqual(
            audit["altFamilyValue"],
            self._twin_value("three-family", source_weighting=weighting),
            delta=2,
        )

    def test_a_source_that_may_not_vote_is_not_evidence(self) -> None:
        """Seasonally inactive (the same gate as disabled / held): no vote and
        not present — the prior boost still read it."""
        rows = _build_board()
        _compute_unified_rankings(rows, {}, seasonally_inactive_sources={"fantasyProsIdp"})
        audit = self._named(rows, "Two Way Player")["twoWayPlayerBoost"]
        self.assertNotIn("fantasyProsIdp", audit["sourcesConsidered"])
        self.assertNotIn("fantasyProsIdp", audit["freshnessExcludedSources"])
        self.assertEqual(audit["families"], ["idpShow", "idpTradeCalc"])

    def test_no_voting_alt_source_withdraws_the_boost_and_says_why(self) -> None:
        weighting = {
            k: _Quarantined(k) for k in ("idpTradeCalc", "idpShowCombined", "fantasyProsIdp")
        }
        rows = _build_board()
        _compute_unified_rankings(rows, {}, source_weighting=weighting)
        two_way = self._named(rows, "Two Way Player")
        audit = two_way["twoWayPlayerBoost"]
        self.assertTrue(audit["withdrawn"])
        self.assertEqual(audit["withdrawnReason"], "no_alt_family_source_votes")
        self.assertIsNone(audit["altFamilyValue"])
        self.assertEqual(
            audit["freshnessExcludedSources"], ["fantasyProsIdp", "idpShowCombined", "idpTradeCalc"]
        )
        self.assertEqual(two_way["rankDerivedValue"], audit["primaryFamilyValue"])

    def test_the_sparse_challenger_that_disables_the_retention_disables_it_here(self) -> None:
        rows = self._priced_board("one-family", single_lineage_retention=False)
        audit = self._named(rows, "Two Way Player")["twoWayPlayerBoost"]
        self.assertFalse(audit["singleSourceValuePenaltyApplied"])
        self.assertNotIn("altFamilyValueBeforePenalty", audit)

    def test_rollback_restores_the_prior_boost(self) -> None:
        """Flag off: the prior boost, key for key."""
        for shape in _BOARDS:
            with self.subTest(board=shape):
                rows = self._priced_board(shape, evidence_rules=False)
                audit = self._named(rows, "Two Way Player")["twoWayPlayerBoost"]
                self.assertEqual(
                    set(audit),
                    {
                        "applied",
                        "altFamily",
                        "altFamilyValue",
                        "primaryFamilyValue",
                        "sourcesConsidered",
                    },
                )

    def test_the_rollback_path_keeps_its_known_one_family_defect(self) -> None:
        """Rules OFF is the prior boost byte for byte, defect included: on the
        one-family board its alt value (5316, a raw value-direct vote) outranks
        every real member of the family, each kept at 30%.  Pinned so a change
        to the rollback path is a deliberate flag-off output change, not an
        accident; the rules ON path is held to the ceiling above."""
        rows = self._priced_board("one-family", evidence_rules=False)
        best_idp = max(
            (r.get("rankDerivedValue") or 0) for r in rows if r.get("assetClass") == "idp"
        )
        audit = self._named(rows, "Two Way Player")["twoWayPlayerBoost"]
        self.assertGreater(audit["altFamilyValue"], best_idp)

    def test_the_primary_value_is_never_touched(self) -> None:
        """The rules decide the ALT value only; the offense (primary) blend is
        the same with them on or off."""
        for shape in _BOARDS:
            with self.subTest(board=shape):
                on = self._priced_board(shape, evidence_rules=True)
                off = self._priced_board(shape, evidence_rules=False)
                self.assertEqual(
                    self._named(on, "Two Way Player")["twoWayPlayerBoost"]["primaryFamilyValue"],
                    self._named(off, "Two Way Player")["twoWayPlayerBoost"]["primaryFamilyValue"],
                )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
