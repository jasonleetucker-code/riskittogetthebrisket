from __future__ import annotations

import pytest

from src.bestball.params import load_marginal_params, with_overrides
from src.league_intel.sim_calibration import PointsModel
from src.roster_intel.best_ball_utility import clear_before_side_cache


@pytest.fixture(autouse=True)
def _fresh_before_cache():
    clear_before_side_cache()
    yield
    clear_before_side_cache()


@pytest.fixture
def params():
    return load_marginal_params()


@pytest.fixture
def fast_params(params):
    return with_overrides(params, draws=params["testDraws"])


@pytest.fixture
def points_model():
    # The documented fallback-constants model: identical on every machine,
    # whatever calibration artifact a box may hold.
    return PointsModel()
