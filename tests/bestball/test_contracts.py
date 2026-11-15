"""Published shapes: camelCase fixtures, no probability from MC error, states.

The JSON fixtures under ``tests/fixtures/bestball/`` are the contract downstream
consumers (the decision engine's local Protocols) read in their batch-2 parity
tests.  Regenerate deliberately with ``BESTBALL_UPDATE_FIXTURES=1`` and say so
in the PR — a fixture change is a contract change.
"""

from __future__ import annotations

import dataclasses
import json
import os
from pathlib import Path

import pytest

from src.bestball.contracts import (
    EVIDENCE_STATES,
    FREE_WAIVER_COST_ASSUMPTION,
    CompetitiveOutcome,
    DynastyHorizonForecast,
    MarginalBestBallUtility,
    ReplacementChoice,
    RosterMarginals,
    SeasonForecast,
    TeamHorizonExpectation,
    TeamLineupDelta,
    WaiverPool,
)
from src.roster_intel.best_ball_utility import UtilityPlayer

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "bestball"


def _replacement() -> ReplacementChoice:
    return ReplacementChoice(
        kind="waiver_free_agent",
        player_id="te074",
        ppg=4.2,
        contested=False,
        cost_assumption=FREE_WAIVER_COST_ASSUMPTION,
        assumption="the vacated roster spot is filled by a free waiver claim",
    )


def _examples() -> dict[str, object]:
    repl = _replacement()
    return {
        "replacement_choice": repl,
        "waiver_pool": WaiverPool(
            candidates=(UtilityPlayer("te074", "Synthetic TE 74", "TE", 4.2),),
            unpriced_ids=("noproj02",),
            excluded_auction_lot_ids=("rookie03",),
            basis={"universe": "contract.playersArray", "priced": 1, "unpriced": 1},
            state="available",
            reason=None,
        ),
        "marginal_bestball_utility": MarginalBestBallUtility(
            player_id="te001",
            owner_id="owner01",
            with_ppg=180.12,
            without_ppg=173.18,
            delta_ppg=6.94,
            mc_standard_error=0.374,
            precision_ok=True,
            predictive_sd=None,
            predictive_basis="unavailable",
            replacement=repl,
            draws=400,
            seed=1173,
            weeks=(),
            param_set_id="48a3a5cdd4fa884b",
            basis={"materialityBandPpg": 1.0, "openedSlotFamilies": ["TE", "FLEX", "SUPER_FLEX"]},
            state="available",
            reason=None,
        ),
        "competitive_outcome": CompetitiveOutcome(
            owner_id="owner01",
            title_prob_before=None,
            title_prob_after=None,
            delta=None,
            ci_low=None,
            ci_high=None,
            horizon="current_season",
            basis="src.ros.playoff_sim (rosValue presim) — not consumed",
            state="unavailable",
            reason="basis_mismatch: playoff presim on rosValue index; owner decision 11 pending",
        ),
        "team_lineup_delta": TeamLineupDelta(
            owner_id="owner01",
            before_ppg=180.12,
            after_ppg=182.4,
            delta_ppg=2.28,
            mc_standard_error=0.31,
            predictive_sd=None,
            predictive_basis="unavailable",
            downside_q10=None,
            depth_before=6.1,
            depth_after=6.5,
            coverage="full",
            vacated_spot_backfill=(repl,),
            state="available",
            reason=None,
        ),
        "dynasty_horizon_forecast": DynastyHorizonForecast(
            player_id="wr001",
            seasons=(SeasonForecast(2027, None, None, None, "unavailable"),),
            aging_curve_version="unfitted",
            state="unavailable",
            reason="horizon_not_built",
        ),
        "team_horizon_expectation": TeamHorizonExpectation(
            owner_id="owner01",
            by_season=((2027, None, None),),
            method="deterministic_lineup_on_expected_ppg",
            state="unavailable",
            reason="horizon_not_built",
        ),
    }


@pytest.mark.parametrize("name", sorted(_examples()))
def test_committed_fixture_matches_to_dict(name):
    payload = _examples()[name].to_dict()
    path = FIXTURES / f"{name}.json"
    if os.environ.get("BESTBALL_UPDATE_FIXTURES") == "1":
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    assert json.loads(path.read_text(encoding="utf-8")) == json.loads(json.dumps(payload))


@pytest.mark.parametrize("name", sorted(_examples()))
def test_to_dict_keys_are_camel_case(name):
    def _walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                assert "_" not in k, f"{name}: snake_case key {k!r}"
                _walk(v)
        elif isinstance(node, list):
            for v in node:
                _walk(v)

    _walk(_examples()[name].to_dict())


def test_marginal_has_no_probability_or_distinguishable_field():
    for cls in (MarginalBestBallUtility, RosterMarginals, WaiverPool, ReplacementChoice):
        names = [f.name.lower() for f in dataclasses.fields(cls)]
        for banned in ("prob", "distinguish", "significan", "p_value", "pvalue", "confidence"):
            assert not any(banned in n for n in names), (cls.__name__, banned)
    keys = " ".join(_examples()["marginal_bestball_utility"].to_dict()).lower()
    for banned in ("prob", "distinguish", "significan", "pvalue"):
        assert banned not in keys


def test_states_are_the_shared_vocabulary():
    assert EVIDENCE_STATES == ("available", "partial", "stale", "unavailable")
    with pytest.raises(ValueError):
        WaiverPool((), (), (), {}, "ok", None)


def test_unprojected_player_cannot_be_a_waiver_candidate():
    with pytest.raises(ValueError):
        WaiverPool((UtilityPlayer("x", "x", "WR", None),), (), (), {}, "available", None)


def test_replacement_must_state_its_assumption_and_name_a_claim():
    with pytest.raises(ValueError):
        ReplacementChoice("none_available", None, None, False, FREE_WAIVER_COST_ASSUMPTION, "")
    with pytest.raises(ValueError):
        ReplacementChoice("waiver_free_agent", None, 3.0, False, FREE_WAIVER_COST_ASSUMPTION, "a")
    with pytest.raises(ValueError):
        ReplacementChoice("empty_slot", None, None, False, FREE_WAIVER_COST_ASSUMPTION, "a")


def test_unavailable_marginal_carries_no_number_and_predictive_sd_needs_a_basis():
    base = dataclasses.asdict(_examples()["marginal_bestball_utility"])
    base["replacement"] = _replacement()
    with pytest.raises(ValueError):
        MarginalBestBallUtility(**{**base, "state": "unavailable"})
    with pytest.raises(ValueError):
        MarginalBestBallUtility(**{**base, "predictive_sd": 2.0})
