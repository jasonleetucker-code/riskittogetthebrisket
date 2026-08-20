"""RED-first invariant tests for the Central Buy/Sell Reconciler (C6-SIG-01).

Each test pins one invariant named in
``docs/lane4/C6_SIG_01_RECONCILER.md``. Every test in this file was
authored to fail against a naive first implementation and was manually
mutation-verified (branch reordered / precedence check removed / etc.)
before being left in this passing state — see that doc for the mutation
log.
"""

from __future__ import annotations

import pytest

from src.analyst.stance import Direction, Stance
from src.signals.reconciler import (
    KNOWN_FAMILIES,
    ReconciledVerdict,
    SignalFamilyEvidence,
    gate_parameter,
    reconcile_row,
)


def _evidence(
    family: str,
    direction: Direction = Direction.BUY_SIDE,
    magnitude: float = 0.5,
    confidence: str = "high",
    fresh: bool | None = True,
    provenance: dict | None = None,
) -> SignalFamilyEvidence:
    return SignalFamilyEvidence(
        family=family,
        direction=direction,
        magnitude=magnitude,
        family_confidence=confidence,
        fresh=fresh,
        provenance=provenance or {},
    )


# ── 1. Zero eligible families never reports a fake neutral ─────────────


def test_no_eligible_families_never_reports_neutral():
    result = reconcile_row(families=[])
    assert result.verdict == "INSUFFICIENT_EVIDENCE"
    assert result.verdict != Stance.HOLD
    assert result.confidenceBucket == "none"


def test_no_eligible_families_is_not_stance_no_signal():
    """INSUFFICIENT_EVIDENCE is deliberately NOT Stance.NO_SIGNAL — see the
    module docstring in src/signals/reconciler.py. NO_SIGNAL means "we
    looked and there is no call here"; zero firing families means nobody
    looked at all."""
    result = reconcile_row(families=[])
    assert result.verdict != Stance.NO_SIGNAL


# ── 2. A quarantined row is always WITHHELD, whatever the evidence says ─


def test_quarantined_row_never_downgrades_to_plain_verdict():
    strong_buy_evidence = [
        _evidence("board_consensus_gap", Direction.BUY_SIDE, 0.9),
        _evidence("bdvm_fundamental", Direction.BUY_SIDE, 0.9),
        _evidence("sharp_transaction", Direction.BUY_SIDE, 0.9),
    ]
    result = reconcile_row(quarantined=True, families=strong_buy_evidence)
    assert result.verdict == "WITHHELD"
    assert result.families == []  # withheld carries no evidence detail


def test_quarantine_read_from_contract_row_confidence_basis():
    row = {"confidenceBasis": "quarantine_degraded"}
    result = reconcile_row(
        contract_row=row,
        families=[_evidence("board_consensus_gap", Direction.BUY_SIDE, 0.9)],
    )
    assert result.verdict == "WITHHELD"


def test_a_normal_confidence_basis_is_not_withheld():
    row = {"confidenceBasis": "evidence_gate"}
    result = reconcile_row(
        contract_row=row,
        families=[_evidence("board_consensus_gap", Direction.BUY_SIDE, 0.9)],
    )
    assert result.verdict != "WITHHELD"


# ── 3. No two board-descended families can both vote (structural) ──────


def test_family_registry_has_exactly_one_board_descended_family():
    """The registry this reconciler wires from must never grow a second
    family sourced from rankDerivedValue/the board's own inputs — that
    would double-count a correlated descendant as independent evidence
    (CLAUDE.md §3.3). Structural guard on KNOWN_FAMILIES rather than a
    behavioural test, since the defect this pins is "someone adds a
    second board-derived family name", not a runtime branch."""
    board_descended = {"board_consensus_gap"}
    assert set(KNOWN_FAMILIES) & board_descended == board_descended
    # bdvm_fundamental and sharp_transaction are declared independent in
    # docs/lane4/C6_SIG_01_RECONCILER.md; this count pins that today's
    # registry has exactly one board-descended member, not two.
    assert len([f for f in KNOWN_FAMILIES if "board" in f]) == 1


# ── 4. A shared anchor is declared, never silently collapsed ───────────


def test_shared_anchor_declared_not_silently_corrected():
    board = _evidence(
        "board_consensus_gap", Direction.BUY_SIDE, 0.3,
        provenance={},
    )
    bdvm = _evidence(
        "bdvm_fundamental", Direction.BUY_SIDE, 0.3,
        provenance={"sharedAnchors": ["ktcSfTep"]},
    )
    result = reconcile_row(families=[board, bdvm])
    assert result.sharedAnchors == ["ktcSfTep"]
    # Both families still count toward independence — declaring the
    # overlap is not the same as discarding one of the two observations.
    assert result.confidenceAxes["independence"] in ("medium", "high")
    assert len(result.families) == 2


def test_no_shared_anchor_is_an_empty_list_not_none():
    board = _evidence("board_consensus_gap", Direction.BUY_SIDE, 0.3)
    result = reconcile_row(families=[board])
    assert result.sharedAnchors == []


# ── 5. Conflicting families force CONFLICTED, never averaged to HOLD ───


def test_conflicting_families_force_conflicted_not_averaged():
    buy = _evidence("board_consensus_gap", Direction.BUY_SIDE, 0.5)
    sell = _evidence("bdvm_fundamental", Direction.SELL_SIDE, 0.5)
    result = reconcile_row(families=[buy, sell])
    assert result.verdict == "CONFLICTED"
    assert result.verdict != Stance.HOLD


def test_conflict_requires_both_sides_above_material_floor():
    """A sub-material dissenter must not manufacture a false conflict —
    only families that clear MATERIAL_MAGNITUDE_FLOOR count toward
    either side of the conflict check."""
    floor = gate_parameter("MATERIAL_MAGNITUDE_FLOOR")
    buy = _evidence("board_consensus_gap", Direction.BUY_SIDE, 0.5)
    trivial_sell = _evidence("bdvm_fundamental", Direction.SELL_SIDE, floor / 2)
    result = reconcile_row(families=[buy, trivial_sell])
    assert result.verdict != "CONFLICTED"


# ── 6. STASH demotes low-confidence BUY, never a confident one ─────────


def test_stash_demotes_low_confidence_buy():
    # A single family clears the magnitude floor but independence can
    # never rise above LOW with only one family — pinning the STASH
    # boundary at exactly the confidence ceiling declared in
    # config/signals/reconciler_v1.json.
    lone_buy = _evidence("board_consensus_gap", Direction.BUY_SIDE, 0.15, fresh=True)
    result = reconcile_row(families=[lone_buy])
    assert result.confidenceBucket == "low"
    assert result.verdict == Stance.STASH


def test_medium_confidence_buy_is_not_stash():
    all_three_agree = [
        _evidence("board_consensus_gap", Direction.BUY_SIDE, 0.15, fresh=True),
        _evidence("bdvm_fundamental", Direction.BUY_SIDE, 0.15, fresh=True),
    ]
    result = reconcile_row(families=all_three_agree)
    assert result.confidenceBucket != "low"
    assert result.verdict != Stance.STASH
    assert result.verdict == Stance.BUY


def test_stash_is_never_reachable_on_the_sell_side():
    """The owner rule (docs/OWNER_FEATURE_SPEC_RECONCILIATION_2026-08-13.md)
    is specifically about false consensus with conviction BUY calls —
    STASH is a buy-side-only concept, per src.analyst.stance's own
    direction mapping (Stance.STASH -> Direction.BUY_SIDE)."""
    lone_sell = _evidence("board_consensus_gap", Direction.SELL_SIDE, 0.15, fresh=True)
    result = reconcile_row(families=[lone_sell])
    assert result.verdict != Stance.STASH
    assert result.verdict == Stance.SELL


# ── Magnitude ladder sanity ─────────────────────────────────────────────


def test_strong_verdict_requires_strong_magnitude_and_confidence():
    strong = [
        _evidence("board_consensus_gap", Direction.BUY_SIDE, 0.9, fresh=True),
        _evidence("bdvm_fundamental", Direction.BUY_SIDE, 0.9, fresh=True),
        _evidence("sharp_transaction", Direction.BUY_SIDE, 0.9, fresh=True),
    ]
    result = reconcile_row(families=strong)
    assert result.verdict == Stance.STRONG_BUY


def test_sub_material_evidence_is_hold_not_insufficient():
    below_floor = gate_parameter("MATERIAL_MAGNITUDE_FLOOR") / 2
    result = reconcile_row(
        families=[_evidence("board_consensus_gap", Direction.BUY_SIDE, below_floor)]
    )
    assert result.verdict == Stance.HOLD
    assert result.verdict != "INSUFFICIENT_EVIDENCE"


# ── Duplicate-family discipline (mirrors src.api.confidence) ───────────


def test_duplicate_family_raises():
    dup = [
        _evidence("board_consensus_gap", Direction.BUY_SIDE, 0.5),
        _evidence("board_consensus_gap", Direction.SELL_SIDE, 0.5),
    ]
    with pytest.raises(ValueError, match="duplicate evidence family"):
        reconcile_row(families=dup)


# ── Purity — never mutates its inputs ───────────────────────────────────


def test_reconcile_row_does_not_mutate_contract_row():
    row = {"confidenceBasis": "evidence_gate", "canonicalConsensusRank": 12}
    snapshot = dict(row)
    reconcile_row(
        contract_row=row,
        families=[_evidence("board_consensus_gap", Direction.BUY_SIDE, 0.5)],
    )
    assert row == snapshot


def test_result_is_a_reconciled_verdict_with_to_dict():
    result = reconcile_row(families=[_evidence("board_consensus_gap")])
    assert isinstance(result, ReconciledVerdict)
    as_dict = result.to_dict()
    assert as_dict["verdict"] == result.verdict
    assert "confidenceAxes" in as_dict
