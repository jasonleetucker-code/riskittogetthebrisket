"""C1-U5 RED: confidence fields that do not mean what they are named.

Manifest row ``C1-CONF-01``.  Reproduced through the ACTUAL production
consumer path — ``build_api_data_contract`` on the newest scraper export,
the same call ``server.py`` makes — so every count below is a real
published payload, not a fixture.

The unit is explicitly **not** a methodology change: the five-axis
bottleneck in ``src/api/confidence.py`` is preserved verbatim per
``MATH_MODEL_CALIBRATION_POLICY_2026-08-15.md`` §7.  What is wrong is the
*vocabulary*, and vocabulary is what every later consumer reads.

RED-1  (priced rows wearing the row-builder placeholder) — 24 rows carry a
       finite positive ``rankDerivedValue`` AND ``confidenceBucket:
       "none"`` with the constructor's default label ``"None — unranked"``.
       Measured on the 2026-08-17 board: all 24 are current-year round-5/6
       slot picks, every one carrying ``pickRookieAnchor``.

       The mechanism, traced: a pick with no voting source never enters
       ``row_normalized``, so neither the Phase 4 loop (capped at
       ``OVERALL_RANK_LIMIT``) nor the off-cap Phase 4b′ pass (which skips
       ``derived <= 0``) ever assesses it — and then
       ``_anchor_current_year_picks_to_rookies`` prices it anyway, by
       design and with a comment saying so, while writing no confidence
       field.  The value is right.  The label is the constructor's
       placeholder, and it says the row is *unranked* when what is true is
       that the row was *never assessed*.

       The two sibling passes already do this correctly:
       ``_complete_future_pick_values`` stamps ``low`` with a derivation
       reason, and ``_suppress_generic_pick_tiers_when_slots_exist``
       stamps ``none`` while also nulling the value.  So this is a
       consistency repair, not a new rule.

RED-2  (``"none"`` is four states wearing one label) — the same bucket is
       published for 24 priced-but-unassessed rows AND 261 genuinely
       unpriced rows.  285 rows, one word, and no field distinguishes
       *insufficient evidence* from *unpriced* from *never assessed*.
       A consumer cannot tell "we looked and found nothing" from "we
       never looked", which is MISSING-IS-NEVER-ZERO applied to the
       evidence label rather than the value.

RED-3  (``identityConfidence`` grades resolution, not evidence) — it is
       ``_compute_identity_confidence``, returning 1.0 for
       ``canonical_id``, 0.95 for ``position_source_aligned`` and 0.7 for
       ``name_only``.  Measured: exactly those three values across 1,110
       rows (937 / 162 / 11).  That is join quality.  It sits beside
       ``confidenceBucket`` — evidence quality — under a name a reader
       cannot distinguish from it.

RED-4  (``marketConfidence`` cannot express what its name claims) —
       measured span on the live board is [0.3252, 0.59375]: it never
       enters the top 40% of its own 0–1 name, because it is a bounded
       ``site_score*0.65 + cv_score*0.35`` blend of source COUNT and
       DISPERSION.  It is a breadth/agreement index published under a
       word the canonical five-axis gate owns.

RED-5  (the owner imports its consumer) — ``_compute_pick_confidence``
       lives in ``src/api/data_contract.py``, and ``src/api/confidence.py``
       — the declared canonical owner — imports it back lazily to do its
       own job.  "One concept, one canonical owner" is violated *inside*
       the owner module.

STATUS: CLOSED.  All five classes were reproduced on the live payload
BEFORE the repair — the counts in this docstring are those measurements,
kept as the record of what was actually wrong.  The assertions below now
verify each defect is GONE, so this file is a permanent regression guard
rather than a reproduction that rots the moment it succeeds.  The positive
contract lives in ``test_confidence_naming.py`` and
``test_confidence_rename_aliases.py``.

The repair, one line each:
  RED-1  the anchor pass stamps its own confidence when it prices a row
         nothing assessed — scoped to those rows, so the 48 picks the
         dispersion rule had already judged keep their verdict.
  RED-2  ``confidenceBasis`` separates the four states ``"none"`` covered,
         and the contract validator ERRORS on a priced row without one.
  RED-3  ``identityResolutionConfidence`` / ``...Method`` say they grade
         the join, not the evidence.
  RED-4  ``marketBreadthAgreementIndex`` says what it measures, and the
         two halves the scraper used to discard are published beside it.
  RED-5  the pick rule moved to its owner; the circular import is gone.

Measured blast radius: 0 values moved, 24 buckets ``none`` -> ``low``,
all of them 2026 round-5/6 slot picks.  Every legacy key is still emitted
with its replacement's exact value for the declared deprecation window.

NOT ``livedata``-marked: builds the contract from a tracked export under
``exports/latest``, so it is deterministic for a given tree.  The counts
are asserted as invariants ("some rows", "more than one meaning"), never
as absolute totals, per ``docs/ops/STABILIZATION_2026-08-16.md`` §3d.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.api.data_contract import build_api_data_contract

_REPO = Path(__file__).resolve().parents[2]

#: The row-builder default in ``_derive_player_row``. A priced row wearing
#: this label was never assessed by anything.
PLACEHOLDER_LABEL = "None — unranked"

_contract_cache: dict[str, Any] | None = None


def _load_contract() -> dict[str, Any] | None:
    global _contract_cache
    if _contract_cache is not None:
        return _contract_cache
    json_files = sorted((_REPO / "exports" / "latest").glob("dynasty_data_*.json"), reverse=True)
    if not json_files:
        return None
    with json_files[0].open() as f:
        raw = json.load(f)
    _contract_cache = build_api_data_contract(raw)
    return _contract_cache


def _rows() -> list[dict[str, Any]]:
    contract = _load_contract()
    if contract is None:
        pytest.skip("no export under exports/latest to build a contract from")
    return contract.get("playersArray") or []


def _is_priced(row: dict[str, Any]) -> bool:
    value = row.get("rankDerivedValue")
    return isinstance(value, (int, float)) and value > 0


class TestPricedRowsWearThePlaceholderLabel:
    """RED-1 — CLOSED. A priced asset no longer reads as having no confidence."""

    def test_no_priced_row_carries_the_row_builder_placeholder(self) -> None:
        offenders = [
            (r.get("canonicalName"), r.get("rankDerivedValue"))
            for r in _rows()
            if _is_priced(r) and r.get("confidenceLabel") == PLACEHOLDER_LABEL
        ]
        assert not offenders, (
            f"RED-1 has REGRESSED — {len(offenders)} priced rows wear the constructor's "
            f"placeholder again: {offenders[:8]}. A pass is pricing rows without saying "
            f"what decided their confidence."
        )

    def test_the_measured_population_now_reports_its_tether(self) -> None:
        """The 24 rows this RED was written for, by the property that identified them."""
        anchored = [r for r in _rows() if r.get("pickRookieAnchor") and _is_priced(r)]
        assert anchored, "no rookie-anchored priced picks — the anchor pass stopped running"
        unassessed = [
            r.get("canonicalName")
            for r in anchored
            if r.get("confidenceBasis") in (None, "", "unpriced", "no_evidence")
        ]
        assert (
            not unassessed
        ), f"rookie-anchored picks carrying a value but no honest basis: {unassessed[:8]}"


class TestNoneBucketIsAmbiguous:
    """RED-2 — CLOSED. ``none`` no longer covers four states with one word."""

    def test_a_field_now_separates_unpriced_from_never_assessed(self) -> None:
        none_bucket = [r for r in _rows() if r.get("confidenceBucket") == "none"]
        assert none_bucket, "no row buckets 'none' any more — check this is intended"
        without_basis = [
            r.get("canonicalName") for r in none_bucket if not r.get("confidenceBasis")
        ]
        assert (
            not without_basis
        ), f"'none' rows with no basis to disambiguate them: {without_basis[:8]}"

    def test_priced_and_unpriced_none_rows_are_distinguishable(self) -> None:
        none_bucket = [r for r in _rows() if r.get("confidenceBucket") == "none"]
        priced_bases = {r.get("confidenceBasis") for r in none_bucket if _is_priced(r)}
        unpriced_bases = {r.get("confidenceBasis") for r in none_bucket if not _is_priced(r)}
        assert not (priced_bases & unpriced_bases), (
            f"a basis value is shared by priced and unpriced 'none' rows "
            f"({priced_bases & unpriced_bases}) — the states are ambiguous again"
        )


class TestIdentityConfidenceGradesResolutionNotEvidence:
    """RED-3 — CLOSED. The field now says it grades RESOLUTION."""

    RESOLUTION_GRADES = {1.0, 0.95, 0.7}

    def test_the_honest_name_is_published(self) -> None:
        rows = _rows()
        assert any(
            "identityResolutionConfidence" in r for r in rows
        ), "identityResolutionConfidence is gone — the rename has been reverted"
        assert any("identityResolutionMethod" in r for r in rows), (
            "identityResolutionMethod is gone; renaming the score and not the method "
            "splits a pair that must travel together"
        )

    def test_it_still_only_takes_the_join_quality_grades(self) -> None:
        """The rename must not have changed what the number measures."""
        values = {
            r["identityResolutionConfidence"]
            for r in _rows()
            if r.get("identityResolutionConfidence") is not None
        }
        assert values, "identityResolutionConfidence is published nowhere"
        assert values <= self.RESOLUTION_GRADES, (
            f"values outside the join-quality grades {sorted(self.RESOLUTION_GRADES)}: "
            f"{sorted(values - self.RESOLUTION_GRADES)} — this was a rename, not a "
            f"methodology change"
        )


class TestMarketConfidenceCannotExpressItsOwnName:
    """RED-4 — CLOSED. The index says it measures breadth and agreement."""

    #: ``site_score*0.65 + cv_score*0.35``, both clamped to [0.20, 1.00],
    #: published as ``round(x, 4)``. The live board's observed ceiling.
    OBSERVED_CEILING = 0.59375

    def test_the_honest_name_is_published(self) -> None:
        assert any(
            "marketBreadthAgreementIndex" in r for r in _rows()
        ), "marketBreadthAgreementIndex is gone — the rename has been reverted"

    def test_the_two_halves_are_published_not_discarded(self) -> None:
        """The decomposition is what stops the rename being cosmetic.

        Both may legitimately be ``None`` on an export produced before the
        scraper change — MISSING, not zero. What must not happen is the keys
        vanishing, which would take the explanation away again.
        """
        rows = _rows()
        assert any("marketBreadthScore" in r for r in rows), "marketBreadthScore is not emitted"
        assert any("marketAgreementScore" in r for r in rows), "marketAgreementScore is not emitted"

    def test_the_index_still_cannot_reach_the_top_of_a_zero_to_one_scale(self) -> None:
        values = [
            r["marketBreadthAgreementIndex"]
            for r in _rows()
            if r.get("marketBreadthAgreementIndex") is not None
        ]
        if not values:
            pytest.skip("no market index on this export")
        assert max(values) <= round(self.OBSERVED_CEILING, 4), (
            f"the index reached {max(values)}, above the {self.OBSERVED_CEILING} ceiling "
            f"this was measured against — the blend's inputs have changed, and the name "
            f"should be re-checked against what it can now express"
        )


class TestPickConfidenceHasTwoOwners:
    """RED-5 — CLOSED. The owner no longer reaches into its consumer."""

    def test_the_owner_no_longer_imports_the_pick_rule(self) -> None:
        source = (_REPO / "src" / "api" / "confidence.py").read_text(encoding="utf-8")
        assert "_compute_pick_confidence" not in source, (
            "src/api/confidence.py references _compute_pick_confidence again — the "
            "canonical owner is borrowing its rule back from data_contract"
        )

    def test_the_consumer_no_longer_defines_a_pick_confidence_rule(self) -> None:
        source = (_REPO / "src" / "api" / "data_contract.py").read_text(encoding="utf-8")
        assert (
            "def _compute_pick_confidence(" not in source
        ), "a pick confidence rule reappeared in data_contract.py — one concept, one owner"

    def test_the_moved_rule_still_returns_the_same_verdicts(self) -> None:
        """Moved verbatim: the migration must not have changed a single bucket."""
        from src.api.confidence import assess_pick_confidence

        assert (
            assess_pick_confidence(
                {"ktcSfTep": 5000.0, "idpTradeCalc": 5100.0}, is_slot_specific=False
            )[0]
            == "high"
        )
        assert assess_pick_confidence({"idpTradeCalc": 5000.0}, is_slot_specific=False)[0] == "low"
        assert assess_pick_confidence({}, is_slot_specific=False) == (
            "none",
            "None — no pick source values",
        )
