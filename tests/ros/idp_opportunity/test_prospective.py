"""Prospective frozen-parameter models: no refit, no leakage, canonical scoring,
missing never zero, determinism.  Synthetic data only; no network."""

from __future__ import annotations

import copy
import json

import pytest

from src.league_intel.scorer import score_stat_line
from src.ros.idp_opportunity.leakage import SeasonData
from src.ros.idp_opportunity.prospective import (
    PROSPECTIVE_MODELS,
    FrozenParams,
    build_prospective_rows,
    effective,
    fit_frozen,
    predict_week,
    project_line,
)
from tests.ros.idp_opportunity._fixtures import CARD_SETTINGS, card, season


def _frozen():
    return fit_frozen(season(6), card(), [2, 3, 4])


def test_fit_uses_only_declared_weeks_and_is_deterministic():
    fp1, d1 = _frozen()
    fp2, d2 = _frozen()
    assert fp1 == fp2
    assert json.dumps(d1, sort_keys=True) == json.dumps(d2, sort_keys=True)
    assert d1["fitWeeks"] == [2, 3, 4]
    # the fit cannot see week 5+: poisoning them changes nothing
    data = season(6)
    stats = copy.deepcopy(dict(data.stats))
    for w in (5, 6):
        for line in stats[w].values():
            line.update({"idp_tkl_solo": 60.0, "def_snp": 2.0})
    d2data = SeasonData(
        data.season,
        stats,
        data.team_of,
        data.offense,
        data.schedule,
        data.injury_report,
        data.positions,
    )
    assert fit_frozen(d2data, card(), [2, 3, 4])[0] == fp1


def test_frozen_params_round_trip():
    fp, _ = _frozen()
    assert FrozenParams.from_dict(json.loads(json.dumps(fp.to_dict()))) == fp


def test_predict_never_reads_the_target_week():
    fp, _ = _frozen()
    data = season(6)
    base = predict_week(data, card(), fp, 5)
    stats = copy.deepcopy(dict(data.stats))
    for line in stats[5].values():
        line.update({"idp_tkl_solo": 60.0, "def_snp": 2.0})
    poisoned = SeasonData(
        data.season,
        stats,
        data.team_of,
        data.offense,
        data.schedule,
        data.injury_report,
        data.positions,
    )
    assert predict_week(poisoned, card(), fp, 5) == base
    assert {r["pid"] for r in base} == {"1", "2", "3", "4", "5", "6", "7", "8", "9"}


@pytest.mark.parametrize("model", PROSPECTIVE_MODELS)
def test_points_are_the_canonical_score_of_the_projected_line(model):
    fp, _ = _frozen()
    data = season(6)
    c = card()
    for pr in build_prospective_rows(data.view(5), c, ["1", "2", "3", "7"]):
        line = project_line(pr, model, fp, c)
        assert c.points(line) == score_stat_line(line, CARD_SETTINGS).total_points


def test_missing_snaps_fall_back_to_s0_named():
    fp, _ = _frozen()
    data = season(6)
    stats = copy.deepcopy(dict(data.stats))
    for w in (1, 2, 3, 4):
        stats[w]["1"]["tm_def_snp"] = None
    d2 = SeasonData(
        data.season,
        stats,
        data.team_of,
        data.offense,
        data.schedule,
        {},
        data.positions,
    )
    pr = build_prospective_rows(d2.view(5), card(), ["1"])[0]
    for m in ("SNAP", "OPP", "ROLE", "HYB"):
        assert effective(pr, m) == "S0"
    assert card().points(project_line(pr, "HYB", fp, card())) > 0


def test_role_gamma_moves_expected_snaps_toward_last_week():
    from dataclasses import replace

    fp, _ = _frozen()
    data = season(6)
    c = card()
    pr = build_prospective_rows(data.view(5), c, ["1"])[0]
    assert pr.role.state == "ok"
    lo = c.points(project_line(pr, "ROLE", replace(fp, gamma=0.0), c))
    hi = c.points(project_line(pr, "ROLE", replace(fp, gamma=1.0), c))
    snap = c.points(project_line(pr, "SNAP", fp, c))
    assert lo == pytest.approx(snap)
    assert (hi - lo) * (pr.role.last_share - pr.share3) >= 0
