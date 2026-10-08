"""Derived picks carry ``pickEvidence`` inherited from their parents (#1697 review).

A pick priced by derivation -- ``derived_year_step`` (board basis),
``derived_round_step`` or ``derived_uniform_tier_ev`` -- changes value when a
parent loses a provider (e.g. IDP Trade Calculator withheld by the freshness
quarantine), but carried no ``pickEvidence``, so it said nothing.  It now
inherits the parents' evidence state, never stronger than the weakest parent,
with the parents named.  Reporting only (SRC-STALEPRES-2026-10-01): no value,
rank or confidence bucket moves.
"""

from __future__ import annotations

import pytest

import src.api.data_contract as dc
from src.api.confidence import (
    PICK_EVIDENCE_MULTI_PROVIDER,
    PICK_EVIDENCE_NO_PROVIDER,
    PICK_EVIDENCE_PROVIDER_UNKNOWN,
    PICK_EVIDENCE_SINGLE_PROVIDER,
    PICK_VALUE_BASIS_DERIVED,
    derived_pick_evidence,
    pick_evidence,
)

_KTC = "ktcCrowdSfTep"
_IDPTC = "idpTradeCalc"
_BOTH = {_KTC: 5000, _IDPTC: 5100}


def _ev(withheld=()):
    return pick_evidence(dict(_BOTH), withheld_sources=withheld)


# ── the owner function ───────────────────────────────────────────────────


def test_a_healthy_parent_is_inherited_as_is():
    ev = derived_pick_evidence([_ev()], derived_from=["2027 Early 4th"])
    assert ev["state"] == PICK_EVIDENCE_MULTI_PROVIDER
    assert ev["valueBasis"] == PICK_VALUE_BASIS_DERIVED
    assert ev["derivedFrom"] == ["2027 Early 4th"]
    assert ev["reducedCoverage"] is False
    assert ev["votingSources"] == sorted(_BOTH)


def test_a_parent_that_lost_a_provider_reduces_the_child():
    parent = _ev(withheld=[_IDPTC])
    ev = derived_pick_evidence([parent], derived_from=["2027 Early 4th"])
    assert ev["state"] == PICK_EVIDENCE_SINGLE_PROVIDER
    assert ev["reducedCoverage"] is True
    assert ev["withheldProviders"] == parent["withheldProviders"]
    assert ev["withheldSources"] == [_IDPTC]
    assert ev["votingProviders"] == parent["votingProviders"]


def test_combining_parents_never_upgrades_the_weakest():
    names = ["2027 Early 1st", "2027 Mid 1st", "2027 Late 1st"]
    ev = derived_pick_evidence([_ev(), _ev(), _ev(withheld=[_IDPTC])], derived_from=names)
    assert ev["state"] == PICK_EVIDENCE_SINGLE_PROVIDER
    assert ev["reducedCoverage"] is True
    assert ev["derivedFrom"] == names
    only_ktc = pick_evidence({_KTC: 1})
    only_idptc = pick_evidence({_IDPTC: 1})
    # Two single-provider parents on DIFFERENT providers are not two
    # independent providers behind the derived value.
    ev = derived_pick_evidence([only_ktc, only_idptc], derived_from=["a", "b"])
    assert ev["state"] == PICK_EVIDENCE_NO_PROVIDER


def test_a_parent_without_evidence_fails_closed():
    ev = derived_pick_evidence([_ev(), None], derived_from=["a", "b"])
    assert ev["state"] == PICK_EVIDENCE_PROVIDER_UNKNOWN
    assert ev["parentsWithoutEvidence"] == ["b"]
    assert ev["votingProviders"] == []


def test_the_rows_own_withheld_market_is_reported():
    own = pick_evidence({_IDPTC: 4000}, withheld_sources=[_IDPTC])
    ev = derived_pick_evidence([pick_evidence({_KTC: 1})], derived_from=["a"], own=own)
    assert ev["reducedCoverage"] is True
    assert ev["withheldSources"] == [_IDPTC]
    assert ev["state"] == PICK_EVIDENCE_SINGLE_PROVIDER


# ── the completion pass stamps it (fails on main: no pickEvidence) ────────


def _tier_row(name, value, withheld=()):
    return {
        "canonicalName": name,
        "assetClass": "pick",
        "rankDerivedValue": value,
        "canonicalSiteValues": dict(_BOTH),
        "freshnessExcludedSources": list(withheld),
        "pickEvidence": _ev(withheld),
    }


def _unpriced(name):
    return {"canonicalName": name, "assetClass": "pick", "rankDerivedValue": None}


def _complete(rows):
    dc._complete_future_pick_values(rows, {}, 2026)
    return {r["canonicalName"]: r for r in rows}


def test_round_step_and_generic_rows_inherit_parent_evidence():
    rows = [
        _tier_row("2027 Early 4th", 1200, withheld=[_IDPTC]),
        _tier_row("2027 Mid 4th", 1100),
        _tier_row("2027 Late 4th", 1000),
        _unpriced("2027 Early 5th"),
        _unpriced("2027 Mid 5th"),
        _unpriced("2027 Late 5th"),
    ]
    by = _complete(rows)
    early5 = by["2027 Early 5th"]
    assert early5["pickValueProvenance"]["class"] == "derived_round_step"
    ev = early5["pickEvidence"]
    assert ev["valueBasis"] == PICK_VALUE_BASIS_DERIVED
    assert ev["derivedFrom"] == ["2027 Early 4th"]
    assert ev["reducedCoverage"] is True and ev["state"] == PICK_EVIDENCE_SINGLE_PROVIDER
    assert by["2027 Mid 5th"]["pickEvidence"]["reducedCoverage"] is False
    generic = by["2027 Round 5"]
    assert generic["pickValueProvenance"]["class"] == "derived_uniform_tier_ev"
    gev = generic["pickEvidence"]
    assert gev["derivedFrom"] == ["2027 Early 5th", "2027 Mid 5th", "2027 Late 5th"]
    # Chained: the Early-5th parent's reduction reaches the generic row.
    assert gev["reducedCoverage"] is True and gev["state"] == PICK_EVIDENCE_SINGLE_PROVIDER


def test_board_basis_year_step_inherits_parent_evidence():
    rows = [_tier_row("2027 Early 1st", 6000, withheld=[_IDPTC]), _unpriced("2028 Early 1st")]
    by = _complete(rows)
    row = by["2028 Early 1st"]
    assert row["pickValueProvenance"]["class"] == "derived_year_step"
    assert row["pickEvidence"]["derivedFrom"] == ["2027 Early 1st"]
    assert row["pickEvidence"]["reducedCoverage"] is True


def test_values_are_unchanged_by_the_stamp():
    """The stamp is diagnostic: the same derivation with and without parent
    evidence produces the same numbers."""
    with_ev = _complete([_tier_row("2027 Early 4th", 1200), _unpriced("2027 Early 5th")])
    bare = [_tier_row("2027 Early 4th", 1200), _unpriced("2027 Early 5th")]
    bare[0].pop("pickEvidence")
    without_ev = _complete(bare)
    assert (
        with_ev["2027 Early 5th"]["rankDerivedValue"]
        == without_ev["2027 Early 5th"]["rankDerivedValue"]
    )
    assert without_ev["2027 Early 5th"]["pickEvidence"]["state"] == PICK_EVIDENCE_PROVIDER_UNKNOWN


def test_contract_health_reports_reduced_derived_picks_on_their_own_line():
    rows = [
        _tier_row("2027 Early 4th", 1200, withheld=[_IDPTC]),
        _unpriced("2027 Early 5th"),
    ]
    _complete(rows)
    report = dc.validate_api_data_contract({"playersArray": rows})
    warnings = report["warnings"]
    assert "pick_evidence_reduced_derived:1" in warnings
    # The parent is counted once as a single-provider pick; the derived child
    # is not counted again under that line.
    assert "pick_evidence_reduced_to_single_provider:1" in warnings


# ── on a real board with IDP Trade Calculator aged past its cutoff ────────


_DERIVED = {"derived_round_step", "derived_uniform_tier_ev"}


def _parents(row):
    prov = row.get("pickValueProvenance") or {}
    basis = prov.get("basis")
    return basis if isinstance(basis, list) else [basis]


def test_every_derived_pick_on_the_cut_board_carries_inherited_evidence(tmp_path_factory):
    from tests.api.test_idptc_cutoff_readiness import _simulation

    sim = _simulation(tmp_path_factory.mktemp("derived_pick_evidence"))
    after = sim["after"]["playersArray"]
    by = {r.get("canonicalName"): r for r in after}
    derived = [
        r
        for r in after
        if r.get("assetClass") == "pick"
        and (
            (r.get("pickValueProvenance") or {}).get("class") in _DERIVED
            or (r.get("pickValueProvenance") or {}).get("appliedTo") == "canonical_board_value"
        )
    ]
    if not derived:
        pytest.skip("no derived pick rows on this archived board")
    for row in derived:
        ev = row.get("pickEvidence")
        assert isinstance(ev, dict), row.get("canonicalName")
        assert ev["valueBasis"] == PICK_VALUE_BASIS_DERIVED
        parents = _parents(row)
        assert ev["derivedFrom"] == parents
        parent_evs = [(by.get(p) or {}).get("pickEvidence") or {} for p in parents]
        if any(pe.get("reducedCoverage") for pe in parent_evs):
            assert ev["reducedCoverage"] is True, row.get("canonicalName")
        order = {
            PICK_EVIDENCE_PROVIDER_UNKNOWN: 0,
            PICK_EVIDENCE_NO_PROVIDER: 1,
            PICK_EVIDENCE_SINGLE_PROVIDER: 2,
            PICK_EVIDENCE_MULTI_PROVIDER: 3,
        }
        weakest = min(order.get(pe.get("state"), 0) for pe in parent_evs)
        assert order[ev["state"]] <= weakest, row.get("canonicalName")
