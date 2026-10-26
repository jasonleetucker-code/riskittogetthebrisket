"""Owner Decision 11 — playoff / title odds count a team's ROS evidence ONCE.

WHERE THE DOUBLE COUNT WAS (``origin/main`` fd87c9068a, ``src/ros/playoff_sim.py``)
================================================================================
* line 706 — on a best-ball league the team's weekly ``(mean, sd)`` is replaced by
  the pre-sim, which draws every rostered player from ``model.draw(rosValue, …)``
  (line 411) and solves the exact lineup: the pre-sim IS the roster's ROS evidence.
* lines 711-712 — the ROS z-score multiplier ``× (1 + ROS_BLEND × ros_z)`` is then
  applied to that pre-sim mean.  ``ros_z`` is the z-score of ``teamRosStrength``,
  i.e. ``0.72 × startingLineupScore + 0.18 × benchDepthScore + …``
  (``team_strength.py`` lines 40-43, 192), sums of the SAME ``rosValue`` numbers.
* line 715 → line 264 — the spread is lifted by ``0.15 × bench/starter``, a ratio of
  the same ``rosValue`` sums, although the pre-sim spread already comes from
  drawing the whole roster (bench included) through the lineup solve.

So on a pre-sim basis the same rosValues entered the mean twice and the spread
twice.  ``_compose_team_distribution(ros_counted_once=True)`` applies neither on
a pre-sim basis, and applies both exactly as before on an empirical/pool basis
(past scores are not ROS evidence, so the ROS term there is its ONE entry).

This file is gate G1 of docs/research/PLAYOFF_ROS_D11_PREREGISTRATION.md, plus
the guards that the incumbent is still served byte for byte when the flag is off.
"""

from __future__ import annotations

import ast
import itertools
import random
from pathlib import Path

import pytest

from src.api import feature_flags
from src.ros import playoff_sim

REPO = Path(__file__).resolve().parents[2]


def _compose(**overrides):
    base = dict(
        basis="presim",
        basis_mean=150.0,
        basis_sd=20.0,
        pool_sd=25.0,
        ros_z=1.3,
        depth_ratio=0.4,
        best_ball=True,
        ros_counted_once=True,
    )
    base.update(overrides)
    return playoff_sim._compose_team_distribution(**base)


@pytest.fixture
def flag(monkeypatch):
    def _set(value: bool | None) -> None:
        if value is None:
            monkeypatch.delenv("RISKIT_FEATURE_PLAYOFF_ROS_COUNTED_ONCE", raising=False)
        else:
            monkeypatch.setenv("RISKIT_FEATURE_PLAYOFF_ROS_COUNTED_ONCE", "1" if value else "0")
        feature_flags.reload()

    yield _set
    feature_flags.reload()


# ── G1: the corrected equation counts ROS evidence once ─────────────────────


@pytest.mark.parametrize("ros_z", [-2.0, -0.5, 0.0, 0.7, 2.4, None])
@pytest.mark.parametrize("depth_ratio", [0.0, 0.3, 1.0])
def test_corrected_presim_ignores_ros_z_and_depth(ros_z, depth_ratio):
    """On a pre-sim basis no second ROS summary moves the mean or the spread."""
    assert _compose(ros_z=ros_z, depth_ratio=depth_ratio) == (
        150.0,
        20.0 * playoff_sim.BEST_BALL_VARIANCE_BUMP,
    )


@pytest.mark.parametrize("basis", ["empirical", "pool"])
def test_corrected_non_presim_still_takes_ros_once(basis):
    """Past scores are not ROS evidence: there the ROS term is its one entry."""
    lo = _compose(basis=basis, ros_z=-1.0)
    hi = _compose(basis=basis, ros_z=1.0)
    assert lo[0] < hi[0]
    assert hi[0] == pytest.approx(150.0 * (1 + playoff_sim.ROS_BLEND))
    deep = _compose(basis=basis, depth_ratio=1.0)
    thin = _compose(basis=basis, depth_ratio=0.0)
    assert deep[1] > thin[1]


def test_incumbent_presim_counts_ros_twice():
    """Documents the defect the flag removes: the pre-sim mean is re-scaled by ros_z."""
    lo = _compose(ros_counted_once=False, ros_z=-1.0)
    hi = _compose(ros_counted_once=False, ros_z=1.0)
    assert hi[0] / lo[0] == pytest.approx((1 + 0.2) / (1 - 0.2))
    assert (
        _compose(ros_counted_once=False, depth_ratio=1.0)[1]
        > _compose(ros_counted_once=False, depth_ratio=0.0)[1]
    )


def test_corrected_distribution_depends_on_rosvalues_only_through_the_presim():
    """Same rosters (same pre-sim) but different team-strength summaries →
    identical corrected distributions; the incumbent moves."""
    per_owner = {"a": [140.0] * 5, "b": [150.0] * 5, "c": [130.0] * 5}
    pool = [x for xs in per_owner.values() for x in xs]
    presim = {"a": (160.0, 18.0), "b": (155.0, 22.0), "c": (149.0, 15.0)}
    strength_1 = {"a": 80.0, "b": 50.0, "c": 20.0}
    strength_2 = {"a": 20.0, "b": 50.0, "c": 80.0}
    depth_1 = {"a": 0.9, "b": 0.1, "c": 0.5}
    depth_2 = {"a": 0.0, "b": 1.0, "c": 0.2}

    def build(strength, depth, once):
        dists, _ = playoff_sim._team_distributions_from_inputs(
            per_owner,
            pool,
            strength,
            depth_ratios=depth,
            bestball_dists=presim,
            best_ball=True,
            ros_counted_once=once,
        )
        return {o: (d.mean, d.sd, d.basis) for o, d in dists.items()}

    assert build(strength_1, depth_1, True) == build(strength_2, depth_2, True)
    assert build(strength_1, depth_1, False) != build(strength_2, depth_2, False)
    for o, (mean, sd, basis) in build(strength_1, depth_1, True).items():
        assert basis == "presim"
        assert mean == presim[o][0]
        assert sd == pytest.approx(presim[o][1] * playoff_sim.BEST_BALL_VARIANCE_BUMP)


def test_start_sit_league_identical_under_both_equations():
    """Format sensitivity: no pre-sim in a start/sit league, so nothing changes."""
    per_owner = {"a": [140.0, 120.0, 150.0, 133.0], "b": [99.0, 101.0, 140.0, 120.0], "c": []}
    pool = [x for xs in per_owner.values() for x in xs]
    strength = {"a": 70.0, "b": 40.0, "c": 55.0}
    out = []
    for once in (False, True):
        dists, _ = playoff_sim._team_distributions_from_inputs(
            per_owner,
            pool,
            strength,
            depth_ratios={"a": 0.5},
            bestball_dists={},
            best_ball=False,
            ros_counted_once=once,
        )
        out.append({o: (d.mean, d.sd, d.basis) for o, d in dists.items()})
    assert out[0] == out[1]


# ── the incumbent is still served byte for byte ─────────────────────────────


def _retired_formula(basis_mean, basis_sd, pool_sd, ros_z, depth_ratio, best_ball):
    """The pre-D11 arithmetic, transcribed from origin/main lines 709-724."""
    blended = basis_mean * (1 + 0.20 * ros_z) if ros_z is not None else basis_mean
    mult = (1.10 + 0.15 * depth_ratio) if best_ball else 1.0
    sd = basis_sd * mult if basis_sd > 0 else pool_sd * mult
    return max(0.0, blended), max(1.0, sd)


def test_incumbent_equation_matches_retired_arithmetic_exactly():
    rng = random.Random(11)
    for basis, best_ball in itertools.product(("presim", "empirical", "pool"), (True, False)):
        for _ in range(200):
            m = rng.uniform(0, 250)
            s = rng.choice([0.0, rng.uniform(0, 40)])
            p = rng.uniform(0, 40)
            z = rng.choice([None, rng.uniform(-3, 3)])
            r = rng.uniform(0, 1)
            got = _compose(
                basis=basis,
                basis_mean=m,
                basis_sd=s,
                pool_sd=p,
                ros_z=z,
                depth_ratio=r,
                best_ball=best_ball,
                ros_counted_once=False,
            )
            assert got == _retired_formula(m, s, p, z, r, best_ball)


def test_flag_selects_the_served_equation(flag):
    flag(False)
    assert playoff_sim.ros_counted_once_enabled() is False
    assert playoff_sim.ros_evidence_method() == playoff_sim.ROS_EVIDENCE_INCUMBENT
    assert playoff_sim.presim_ros_blend() == playoff_sim.ROS_BLEND
    flag(True)
    assert playoff_sim.ros_counted_once_enabled() is True
    assert playoff_sim.ros_evidence_method() == playoff_sim.ROS_EVIDENCE_ONCE
    assert playoff_sim.presim_ros_blend() == 0.0


def test_build_team_distributions_routes_through_the_flag(flag, monkeypatch):
    """``_build_team_distributions`` passes the flag's value to the pure owner."""
    seen = []

    def spy(*args, **kwargs):
        seen.append(kwargs["ros_counted_once"])
        return {}, {}

    monkeypatch.setattr(playoff_sim, "_team_distributions_from_inputs", spy)
    monkeypatch.setattr(playoff_sim, "_load_team_depth_ratios", lambda *a, **k: {})
    monkeypatch.setattr(playoff_sim.playoff_odds, "_season_weekly_scores", lambda *a, **k: ({}, []))

    class _Season:
        season = "2026"
        league: dict = {}

    class _Snap:
        seasons = [_Season()]
        managers = None

    monkeypatch.setattr(playoff_sim.luck, "_season_sort_key", lambda s: 0)
    for value in (False, True):
        flag(value)
        playoff_sim._build_team_distributions(_Snap(), {}, best_ball=False)
    assert seen == [False, True]


def test_twin_reads_the_served_presim_blend():
    src = (REPO / "src" / "league_intel" / "twin.py").read_text(encoding="utf-8")
    assert "presim_ros_blend()" in src
    assert "ros_blend = ROS_BLEND" not in src


def test_forecast_archive_identity_names_the_equation(flag):
    from src.ros import forecast_archive

    flag(True)
    params = forecast_archive._sim_params(True, {})
    assert params["rosEvidenceMethod"] == playoff_sim.ROS_EVIDENCE_ONCE
    flag(False)
    params = forecast_archive._sim_params(True, {})
    assert params["rosEvidenceMethod"] == playoff_sim.ROS_EVIDENCE_INCUMBENT


def test_payload_stamps_ros_evidence_method():
    tree = ast.parse((REPO / "src" / "ros" / "playoff_sim.py").read_text(encoding="utf-8"))
    keys = {
        k.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Dict)
        for k in node.keys
        if isinstance(k, ast.Constant)
    }
    assert "rosEvidenceMethod" in keys
