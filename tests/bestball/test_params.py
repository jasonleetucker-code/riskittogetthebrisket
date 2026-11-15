from __future__ import annotations

import json

import pytest

from src.bestball.params import (
    MARGINAL_PARAMS_PATH,
    ParamsUnavailable,
    load_marginal_params,
    param_set_id,
    with_overrides,
)
from src.roster_intel.best_ball_utility import DEFAULT_DRAWS, DEFAULT_SEED


def test_inherited_priors_match_the_owner_defaults(params):
    assert params["draws"] == DEFAULT_DRAWS == 400
    assert params["seed"] == DEFAULT_SEED == 1173
    assert params["candidatesPerSlotFamily"] == 1
    assert params["materialityPpg"] == 1.0
    assert params["testDraws"] == 30
    assert params["classification"] == "PRIOR"


def test_param_set_id_is_a_content_hash(params):
    raw = json.loads(MARGINAL_PARAMS_PATH.read_text(encoding="utf-8"))
    assert params["paramSetId"] == param_set_id(raw)
    # Annotations do not move the id; values do.
    assert param_set_id({**raw, "_note": "x"}) == params["paramSetId"]
    assert param_set_id({**raw, "draws": 401}) != params["paramSetId"]


def test_override_re_mints_the_id(params):
    fast = with_overrides(params, draws=30)
    assert fast["draws"] == 30
    assert fast["paramSetId"] != params["paramSetId"]
    assert load_marginal_params()["draws"] == 400  # cached copy untouched


def test_missing_file_raises_rather_than_defaulting(tmp_path):
    with pytest.raises(ParamsUnavailable):
        load_marginal_params(tmp_path / "absent.json")
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"draws": 1}), encoding="utf-8")
    with pytest.raises(ParamsUnavailable):
        load_marginal_params(bad)
