"""Config provenance, published shapes, and the committed parity fixture."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from src.league_valuation.contracts import (
    ContractError,
    LeagueFairValue,
    load_params,
    param_set_id_for,
)
from src.league_valuation.evidence import utility_evidence_from_bdvm
from src.league_valuation.challenger import compute_fair_values
from tests.league_valuation._builders import NOW, PARAMS, pins

REPO = Path(__file__).resolve().parents[2]
FIX = REPO / "tests/fixtures/league_valuation"
CONFIG = REPO / "config/league_valuation/fair_value_v1.json"


def test_param_set_id_is_the_content_hash():
    payload = json.loads(CONFIG.read_text())
    assert payload["paramSetId"] == param_set_id_for(payload)
    tampered = dict(payload, kMax={**payload["kMax"], "value": 0.3})
    assert param_set_id_for(tampered) != payload["paramSetId"]


def test_load_params_refuses_a_stale_id(tmp_path):
    payload = json.loads(CONFIG.read_text())
    payload["kMax"]["value"] = 0.5
    bad = tmp_path / "p.json"
    bad.write_text(json.dumps(payload))
    with pytest.raises(ContractError):
        load_params(str(bad))


def test_every_tunable_is_labelled_prior_and_no_centring_constant_exists():
    payload = load_params()
    for block in ("kMax", "quality", "freshness"):
        assert payload[block]["classification"] == "PRIOR", block
    assert payload["idpFanOut"]["classification"] == "REUSED"
    text = json.dumps({k: v for k, v in payload.items() if k != "_comment"}).lower()
    for forbidden in ("reference", "centre", "center", "multiplier", "factor"):
        assert forbidden not in text, forbidden


def test_excluded_fair_value_must_equal_market():
    with pytest.raises(ContractError):
        LeagueFairValue(
            asset_key="player:1",
            player_id="1",
            scope="OFFENSE",
            market_value=100,
            fair_value=101,
            matched_value=None,
            k=0.0,
            utility_rank=None,
            market_rank=1,
            excluded_reason="quarantined",
            model_version="x",
            param_set_id="y",
            pins={},
            state="excluded",
            reason="quarantined",
        )


def _close(a, b, path=""):
    if isinstance(a, dict):
        assert set(a) == set(b), path
        for k in a:
            _close(a[k], b[k], f"{path}.{k}")
    elif isinstance(a, list):
        assert len(a) == len(b), path
        for i, (x, y) in enumerate(zip(a, b)):
            _close(x, y, f"{path}[{i}]")
    elif isinstance(a, float) and isinstance(b, (int, float)) and not isinstance(b, bool):
        assert math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-9), path
    else:
        assert a == b, path


def test_committed_fixture_reproduces_exactly():
    board = json.loads((FIX / "synthetic_board.json").read_text())
    payload = json.loads((FIX / "bdvm_payload.json").read_text())
    expected = json.loads((FIX / "expected_fair_value_board.json").read_text())
    ev = utility_evidence_from_bdvm(payload, now=NOW, params=PARAMS)
    fb = compute_fair_values(
        board["playersArray"], ev, params=PARAMS, pins=pins(), anchor_year=board["currentDraftYear"]
    )
    _close(json.loads(json.dumps(fb.to_dict())), expected["board"])
    _close({k: e.to_dict() for k, e in ev.items()}, expected["utilityEvidence"])


def test_published_shapes_are_camel_case():
    expected = json.loads((FIX / "expected_fair_value_board.json").read_text())
    some_value = next(iter(expected["board"]["values"].values()))
    some_ev = next(iter(expected["utilityEvidence"].values()))
    for key in list(some_value) + list(some_ev) + list(expected["board"]):
        assert "_" not in key, key
