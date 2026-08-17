"""C1-U5 GREEN: confidence fields mean what they are named.

The reproduction lives in ``test_confidence_naming_red.py``; this file is
the contract that replaces it. Manifest row ``C1-CONF-01``.

Two things are pinned here that are easy to undo by accident:

1. **``CONFIDENCE_LEVELS`` is still exactly four values.** The overall
   level is the WEAKEST axis, so adding a fifth changes what the
   bottleneck ``min()`` means for every axis at once. C1-U5 deliberately
   added an ORTHOGONAL field rather than a level, because what was
   missing was never a degree of confidence — it was *which owner decided
   it, from what class of evidence*. Calibration policy §7 preserves the
   architecture; this test is that preservation made executable.

2. **A priced row always says what decided its confidence.** Not "should"
   — ``validate_api_data_contract`` errors on a priced row with a missing,
   unknown or self-contradicting basis, so the build fails rather than
   the row shipping with a placeholder. That is the difference between
   fixing 24 rows and closing the hole they came through.

NOT ``livedata``-marked: builds from a tracked export, deterministic for a
given tree, and asserts invariants rather than absolute counts per
``docs/ops/STABILIZATION_2026-08-16.md`` §3d.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.api.confidence import (
    CONFIDENCE_BASES,
    CONFIDENCE_LEVELS,
    degrade_for_quarantine,
    unassessed_defaults,
)
from src.api.data_contract import build_api_data_contract, validate_api_data_contract

_REPO = Path(__file__).resolve().parents[2]

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


def _priced(row: dict[str, Any]) -> bool:
    v = row.get("rankDerivedValue")
    return isinstance(v, (int, float)) and not isinstance(v, bool) and float(v) > 0


class TestMethodologyIsUnchanged:
    """C1-U5 is a naming and ownership migration. Nothing about the gate moved."""

    def test_confidence_levels_are_still_exactly_four(self) -> None:
        assert CONFIDENCE_LEVELS == ("none", "low", "medium", "high"), (
            "the published bucket vocabulary changed. The overall level is the "
            "WEAKEST axis, so this is a methodology change, not a rename — it needs "
            "the champion/challenger path, not a C1-U5-shaped commit."
        )

    def test_basis_is_a_closed_set_disjoint_from_levels(self) -> None:
        assert len(set(CONFIDENCE_BASES)) == len(CONFIDENCE_BASES), "duplicate basis value"
        assert not (set(CONFIDENCE_BASES) & set(CONFIDENCE_LEVELS)), (
            "a basis value collides with a bucket value — the two vocabularies must stay "
            "distinguishable, or the confusion this unit removed comes straight back"
        )


class TestEveryPricedRowSaysWhatDecidedIt:
    """The invariant, asserted as all-of-them rather than as a count."""

    def test_no_priced_row_is_missing_a_basis(self) -> None:
        offenders = [
            r.get("canonicalName") or r.get("displayName")
            for r in _rows()
            if _priced(r) and not r.get("confidenceBasis")
        ]
        assert not offenders, f"priced rows with no confidenceBasis: {offenders[:10]}"

    def test_every_basis_is_from_the_closed_set(self) -> None:
        seen = {r.get("confidenceBasis") for r in _rows() if r.get("confidenceBasis")}
        assert seen, "no row publishes a confidenceBasis"
        assert seen <= set(CONFIDENCE_BASES), (
            f"unknown basis values: {seen - set(CONFIDENCE_BASES)}"
        )

    def test_no_priced_row_claims_it_is_unpriced_or_unlooked_at(self) -> None:
        offenders = [
            (r.get("canonicalName") or r.get("displayName"), r.get("confidenceBasis"))
            for r in _rows()
            if _priced(r) and r.get("confidenceBasis") in ("unpriced", "no_evidence")
        ]
        assert not offenders, (
            f"rows carrying a real value while claiming no value / no assessment: {offenders[:10]}"
        )

    def test_no_priced_row_wears_the_row_builder_placeholder(self) -> None:
        offenders = [
            r.get("canonicalName") or r.get("displayName")
            for r in _rows()
            if _priced(r) and r.get("confidenceLabel") == "None — unranked"
        ]
        assert not offenders, (
            f"priced rows still wearing the constructor's placeholder: {offenders[:10]}"
        )

    def test_the_contract_validator_rejects_a_priced_row_without_a_basis(self) -> None:
        """The hole, not just the rows that fell through it."""
        contract = _load_contract()
        if contract is None:
            pytest.skip("no export")
        broken = json.loads(json.dumps(contract))
        for row in broken.get("playersArray") or []:
            if _priced(row):
                row.pop("confidenceBasis", None)
                break
        else:
            pytest.skip("no priced row to break")
        result = validate_api_data_contract(broken)
        assert any("confidence_basis_missing" in str(e) for e in (result.get("errors") or [])), (
            "the validator accepted a priced row with no basis — the guard is not wired, "
            "so the next pass that prices a row without saying why ships silently"
        )


class TestRookieTetheredPicksAreHonest:
    """The 24 measured rows, and the 48 that must NOT have been relabelled."""

    def test_tethered_rows_report_the_tether_as_their_basis(self) -> None:
        tethered = [r for r in _rows() if r.get("confidenceBasis") == "derived_rookie_tether"]
        assert tethered, "no row reports a rookie tether — the anchor pass stopped stamping"
        for row in tethered:
            assert _priced(row), f"{row.get('canonicalName')} claims a tether but carries no value"
            assert row.get("pickRookieAnchor"), (
                f"{row.get('canonicalName')} claims a tether with no anchor recorded"
            )
            assert row.get("confidenceBucket") == "low"

    def test_picks_with_their_own_market_keep_the_dispersion_basis(self) -> None:
        """Scope guard.

        The anchor pass runs over every current-year slot pick, not only the
        ones no market prices. Stamping the tether basis on all of them would
        downgrade real pick-market confidence to a derivation label — a
        methodology change wearing a rename's clothes. The rows the dispersion
        rule already assessed must still say so.
        """
        dispersion = [r for r in _rows() if r.get("confidenceBasis") == "pick_dispersion"]
        assert dispersion, (
            "no row reports pick_dispersion — the anchor pass has overwritten "
            "confidence the dispersion rule had already decided"
        )


class TestOwnerHelpers:
    def test_unassessed_defaults_separate_unpriced_from_unlooked_at(self) -> None:
        _b1, _l1, basis_unpriced = unassessed_defaults(priced=False)
        _b2, _l2, basis_priced = unassessed_defaults(priced=True)
        assert basis_unpriced == "unpriced"
        assert basis_priced == "no_evidence"
        assert basis_unpriced != basis_priced, (
            "'we have no value' and 'we never looked' collapsed back into one state"
        )

    def test_quarantine_never_promotes(self) -> None:
        for level in CONFIDENCE_LEVELS:
            bucket, _label, basis = degrade_for_quarantine(level)
            assert basis == "quarantine_degraded"
            assert CONFIDENCE_LEVELS.index(bucket) <= CONFIDENCE_LEVELS.index(level), (
                f"quarantining a {level!r} row promoted it to {bucket!r}"
            )


class TestThePickRuleLivesAtItsOwner:
    """RED-5 closed: the owner no longer imports its consumer."""

    def test_confidence_does_not_import_the_pick_rule_from_data_contract(self) -> None:
        source = (_REPO / "src" / "api" / "confidence.py").read_text(encoding="utf-8")
        assert "_compute_pick_confidence" not in source, (
            "src/api/confidence.py still references _compute_pick_confidence — the owner "
            "is reaching into its consumer again"
        )

    def test_data_contract_no_longer_defines_a_pick_confidence_rule(self) -> None:
        source = (_REPO / "src" / "api" / "data_contract.py").read_text(encoding="utf-8")
        assert "def _compute_pick_confidence(" not in source, (
            "a pick confidence rule reappeared in data_contract.py — one concept, one owner"
        )

    def test_the_rule_still_produces_the_same_verdicts(self) -> None:
        """Moved verbatim. Two sources agreeing tightly is still high."""
        from src.api.confidence import assess_pick_confidence

        bucket, _label = assess_pick_confidence(
            {"ktcSfTep": 5000.0, "idpTradeCalc": 5100.0}, is_slot_specific=False
        )
        assert bucket == "high"
        bucket, _label = assess_pick_confidence({"idpTradeCalc": 5000.0}, is_slot_specific=False)
        assert bucket == "low"
        bucket, label = assess_pick_confidence({}, is_slot_specific=False)
        assert (bucket, label) == ("none", "None — no pick source values")
