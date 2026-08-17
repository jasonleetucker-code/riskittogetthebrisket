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

STATUS: PARTIALLY CLOSED — RED-1, RED-2 and RED-5 are repaired and their
assertions below now verify the defect is GONE.  **RED-3 and RED-4 remain
OPEN** and still assert the defect, because the ``identityConfidence`` and
``marketConfidence`` renames are the second half of C1-U5 and have not
landed yet.  Saying otherwise would make this file claim a repair that
does not exist.

Closed here:
  RED-1  the anchor pass stamps its own confidence when it prices a row
         nothing assessed — scoped to exactly those rows, so the 48 picks
         the dispersion rule had already judged keep their verdict.
  RED-2  ``confidenceBasis`` separates the four states ``"none"`` was
         covering, and ``validate_api_data_contract`` now ERRORS on a
         priced row with a missing, unknown or self-contradicting basis —
         so the hole is closed, not just the rows that fell through it.
  RED-5  the pick rule moved to its owner; the circular import is gone.

Measured blast radius of the repair: 0 values moved, 24 buckets
``none`` -> ``low``, all of them 2026 round-5/6 slot picks.

The positive contract lives in ``test_confidence_naming.py``.

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
        assert not unassessed, (
            f"rookie-anchored picks carrying a value but no honest basis: {unassessed[:8]}"
        )


class TestNoneBucketIsAmbiguous:
    """RED-2 — CLOSED. ``none`` no longer covers four states with one word."""

    def test_a_field_now_separates_unpriced_from_never_assessed(self) -> None:
        none_bucket = [r for r in _rows() if r.get("confidenceBucket") == "none"]
        assert none_bucket, "no row buckets 'none' any more — check this is intended"
        without_basis = [
            r.get("canonicalName") for r in none_bucket if not r.get("confidenceBasis")
        ]
        assert not without_basis, (
            f"'none' rows with no basis to disambiguate them: {without_basis[:8]}"
        )

    def test_priced_and_unpriced_none_rows_are_distinguishable(self) -> None:
        none_bucket = [r for r in _rows() if r.get("confidenceBucket") == "none"]
        priced_bases = {r.get("confidenceBasis") for r in none_bucket if _is_priced(r)}
        unpriced_bases = {r.get("confidenceBasis") for r in none_bucket if not _is_priced(r)}
        assert not (priced_bases & unpriced_bases), (
            f"a basis value is shared by priced and unpriced 'none' rows "
            f"({priced_bases & unpriced_bases}) — the states are ambiguous again"
        )


class TestIdentityConfidenceGradesResolutionNotEvidence:
    """RED-3: the value set proves what it measures."""

    RESOLUTION_GRADES = {1.0, 0.95, 0.7}

    def test_it_only_ever_takes_the_join_quality_grades(self) -> None:
        values = {
            r["identityConfidence"] for r in _rows() if r.get("identityConfidence") is not None
        }
        assert values, "identityConfidence is no longer published"
        assert values <= self.RESOLUTION_GRADES, (
            f"identityConfidence took values outside the join-quality grades "
            f"{sorted(self.RESOLUTION_GRADES)}: {sorted(values - self.RESOLUTION_GRADES)}. "
            f"If it has become a continuous score it is measuring something else now."
        )

    def test_it_is_published_beside_evidence_confidence_under_a_confusable_name(self) -> None:
        rows = [r for r in _rows() if r.get("identityConfidence") is not None]
        both = [r for r in rows if r.get("confidenceBucket") is not None]
        assert both, "no row publishes identityConfidence and confidenceBucket together"
        assert not any("identityResolutionConfidence" in r for r in rows), (
            "identityResolutionConfidence exists — C1-U5 has landed and this RED is closed"
        )


class TestMarketConfidenceCannotExpressItsOwnName:
    """RED-4: a bounded breadth/agreement index named as a confidence."""

    #: ``site_score*0.65 + cv_score*0.35``, both clamped to [0.20, 1.00],
    #: published as ``round(x, 4)``. The live board's observed ceiling.
    OBSERVED_CEILING = 0.59375

    def test_it_never_enters_the_top_of_a_zero_to_one_scale(self) -> None:
        values = [r["marketConfidence"] for r in _rows() if r.get("marketConfidence") is not None]
        assert values, "marketConfidence is no longer published"
        # Compare against the rounded ceiling the payload can actually carry.
        ceiling = round(self.OBSERVED_CEILING, 4)
        assert max(values) <= ceiling, (
            f"marketConfidence reached {max(values)}, above the {ceiling} ceiling this "
            f"RED was measured against — the blend's inputs have changed"
        )
        assert max(values) < 0.60, (
            "marketConfidence now reaches into the top 40% of its own 0–1 name, so the "
            "naming defect this RED describes has changed shape"
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
        assert "def _compute_pick_confidence(" not in source, (
            "a pick confidence rule reappeared in data_contract.py — one concept, one owner"
        )

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
