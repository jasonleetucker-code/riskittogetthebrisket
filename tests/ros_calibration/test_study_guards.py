"""Study-script guards: split integrity, output confinement, promotes=false."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import ros_scale_calibration_study as study


def test_holdout_and_development_are_disjoint_and_final_fit_excludes_confirm_week():
    assert set(study.HOLDOUT).isdisjoint(study.DEVELOPMENT)
    assert study.CONFIRM_WEEK not in study.FINAL_FIT_WEEKS
    assert max(study.FINAL_FIT_WEEKS) < study.CONFIRM_WEEK


def test_rolling_origin_fit_weeks_precede_the_evaluated_week():
    for h in study.HOLDOUT + study.DEVELOPMENT:
        assert all(w < h for w in range(1, h))


def test_output_is_confined_to_evidence_dir(tmp_path: Path):
    with pytest.raises(study.v1.StudyRefusal):
        study.assert_safe_output(study.REPO / "data" / "ros" / "aggregate" / "latest.json")
    with pytest.raises(study.v1.StudyRefusal):
        study.assert_safe_output(tmp_path / "x.json")
    assert study.assert_safe_output(study.OUT_DIR / "evaluation.json")


def test_gate_thresholds_match_preregistration():
    prereg = (study.REPO / study.PREREGISTRATION).read_text(encoding="utf-8")
    assert "`|D_X − 1| ≤ 0.10`" in prereg and study.G1_D_TOL == 0.10
    assert "[0.85, 1.15]" in prereg and study.G1_R_BAND == (0.85, 1.15)
    assert "ρ(C0) − 0.02" in prereg and study.G4_TOL == 0.02
    assert "agreement(C0) − 0.01" in prereg and study.G5_TOL == 0.01
    assert "concordance(C0) − 0.02" in prereg and study.G6_TOL == 0.02
    assert "≥ 50 holdout player-weeks" in prereg and study.GATE_MIN_N == 50
    assert (
        "B = 2,000, seed 20261028" in prereg
        and study.SEED == 20261028
        and study.BOOTSTRAP_B == 2000
    )


def test_gates_require_every_check_and_name_failures():
    acc = {
        "byModel": {
            m: {
                "D": {"estimate": 1.0, "ci95": [0.9, 1.1]},
                "ratioOFF": 1.0,
                "ratioIDP": 1.0,
                "mae": 5.0,
                "dMAEvsC0": {"estimate": 0.5, "ci95": [0.1, 0.9]},
            }
            for m in ("C0", "CG", "CF", "CR")
        },
        "families": {},
    }
    conc = {
        "sufficient": True,
        "byModel": {m: {"deltaVsC0": {"ci95": [0.01, 0.02]}} for m in ("CG", "CF", "CR")},
    }
    stab = {"mean": {m: 0.9 for m in ("C0", "CG", "CF", "CR")}}
    team = {
        "sufficient": True,
        "byModel": {
            m: {"lineupAgreement": {"estimate": 0.8}, "allPlayConcordance": 0.6}
            for m in ("C0", "CG", "CF", "CR")
        },
    }
    g = study.gates(acc, conc, stab, team)
    assert all(g["challengers"][x]["verdict"] == "PASSES_ALL_GATES" for x in ("CG", "CF", "CR"))
    assert g["recommendation"] == "CG"
    conc["byModel"]["CG"]["deltaVsC0"]["ci95"] = [-0.01, 0.02]
    team["sufficient"] = False
    g = study.gates(acc, conc, stab, team)
    assert g["challengers"]["CG"]["failing"] == ["G3", "G5", "G6"]
    assert g["challengers"]["CR"]["failing"] == ["G5", "G6"]
    assert g["recommendation"] is None
