"""Explicit uncertainty-unavailable contract (owner directive 2026-11-08, Priority 12).

The Monte Carlo response states that no empirically calibrated band
exists and never calls its simulation share an acceptance probability.
Additive: every pre-existing field is byte-identical to the frozen
pre-change response in ``tests/fixtures/mc_response_pre_uncertainty_contract.json``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from src.trade import analyze_trade as _analyze
from src.trade import monte_carlo as mc
from src.trade import symmetrize as sym

_FIX = json.loads(
    (
        Path(__file__).resolve().parents[1]
        / "fixtures"
        / "mc_response_pre_uncertainty_contract.json"
    ).read_text(encoding="utf-8")
)
_STUDY = "docs/valuation/TRADE_UNCERTAINTY_STUDY_2026-11-08.md"


def _players():
    inp = _FIX["inputs"]
    return (
        [mc.build_trade_player(r) for r in inp["A"]],
        [mc.build_trade_player(r) for r in inp["B"]],
        inp,
    )


def _symmetric():
    a, b, inp = _players()
    return sym.enrich_with_decision_shape(
        sym.simulate_symmetric(a, b, n_sims=inp["nSims"], seed=inp["seed"]), a, b
    )


def _strip(d):
    return {k: v for k, v in d.items() if k != "valueUncertainty"}


def test_symmetric_response_carries_exact_unavailable_state():
    vu = _symmetric()["valueUncertainty"]
    assert vu["state"] == "unavailable"
    assert vu["reason"] == "no_empirically_calibrated_band"
    assert vu["evidence"] == _STUDY
    assert vu["calibratedIntervals"] is None and vu["horizonDays"] is None
    assert vu["bandBasis"] == "assumed_flat_15pct"
    replay = vu["replayCheckOfAssumedBand"]
    assert replay["coverageIsUpperBound"] is True
    assert replay["nominalCoverage"] == 0.8


def test_raw_sim_result_carries_the_field():
    a, b, inp = _players()
    out = mc.simulate_trade(a, b, n_sims=inp["nSims"], seed=inp["seed"]).to_dict()
    assert out["valueUncertainty"]["state"] == "unavailable"


def test_every_preexisting_field_is_byte_identical():
    assert json.dumps(_strip(_symmetric()), sort_keys=True) == json.dumps(
        _FIX["symmetric"], sort_keys=True
    )
    a, b, inp = _players()
    raw = mc.simulate_trade(a, b, n_sims=inp["nSims"], seed=inp["seed"]).to_dict()
    assert json.dumps(_strip(raw), sort_keys=True) == json.dumps(_FIX["raw"], sort_keys=True)


def test_disclaimer_never_claims_an_acceptance_probability():
    text = _symmetric()["disclaimer"].lower()
    assert not re.search(r"acceptance\s+prob", text)
    assert "not a real-world win probability" in text


def test_band_basis_follows_band_sources():
    f = mc.value_uncertainty_unavailable
    assert f({mc.BAND_SOURCE_STAMPED: 2})["bandBasis"] == "stamped_value_band_uncalibrated"
    assert f({mc.BAND_SOURCE_STAMPED: 1, mc.BAND_SOURCE_SYNTHETIC: 1})["bandBasis"] == (
        "assumed_flat_15pct"
    )
    assert f(None)["bandBasis"] == "unknown"
    assert f(None)["state"] == "unavailable"


def test_analyze_and_monte_carlo_agree_on_reason_and_study():
    dims = {d["dimension"]: d for d in _analyze._UNAVAILABLE_DIMENSIONS}
    vu = dims["valueUncertainty"]
    mc_vu = _symmetric()["valueUncertainty"]
    assert vu["reason"] == mc_vu["reason"] == mc.UNCERTAINTY_UNAVAILABLE_REASON
    assert vu["evidence"] == mc_vu["evidence"] == _STUDY
    assert "not an acceptance probability" in vu["notes"]
