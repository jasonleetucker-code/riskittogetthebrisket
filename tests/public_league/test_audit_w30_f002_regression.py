"""CW-40 / master-site-audit W30-F002 regression evidence (P1).

Finding: both playoff-odds engines published exactly 1.0 / 0.0 for every owner
with zero games played and 14 weeks remaining, and the convergence gate
certified it (``worstPlayoffOddsSe == 0.0`` because every simulation returned
the identical answer).

Adjudication (docs/audits/remediation_2026-11-06/CW40_P1_OPEN_ADJUDICATION.md):
PARTIAL.

* CLOSED for the audited state.  The public section is an adapter over the one
  canonical engine (``src.ros.playoff_sim``); with no scored week the engine
  refuses (``no_scored_weeks_in_league``) and the section publishes
  ``simulated: False`` with ``playoffProbability: None`` -- whether or not ROS
  strength is available.  The existing tests cover the no-ROS case; this file adds
  the ROS-available case and the posted-14-week shape of the finding.
* A real simulation with zero games played (distributions injected) spreads
  probabilities strictly inside (0, 1).
* RESIDUAL (latent).  ``simulate_playoff_odds`` still stamps ``converged: True``
  on a zero-variance result, because the gate is a binomial SE that is 0 at
  p in {0, 1}.  Production distribution builders floor ``sd`` at 1.0
  (``playoff_sim._compose_team_distribution``) so the state is unreachable
  from them today; the xfail below pins the gate gap itself.

No network, no files: the engine's cache, ROS and best-ball readers are patched.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.public_league import playoff_odds as _po
from src.ros import playoff_sim
from tests.public_league.test_playoff_odds_no_fabricated_certainty import _snapshot_no_games

OWNERS = [f"o{i:02d}" for i in range(12)]


def _round_robin(weeks: int) -> list[tuple[int, str, str]]:
    """Circle-method schedule, 6 games per week for 12 teams."""
    out: list[tuple[int, str, str]] = []
    for wk in range(1, weeks + 1):
        arr = list(range(12))
        for _ in range((wk - 1) % 11):
            arr = [arr[0]] + [arr[-1]] + arr[1:-1]
        out.extend((wk, OWNERS[arr[i]], OWNERS[arr[11 - i]]) for i in range(6))
    return out


def _simulate(*, sd: float, mean_of, n: int = 400) -> dict:
    dists = {
        o: playoff_sim._TeamDist(owner_id=o, mean=mean_of(i), sd=sd, pf_to_date=0.0)
        for i, o in enumerate(OWNERS)
    }
    snap = SimpleNamespace(seasons=[], managers=SimpleNamespace(by_owner_id={}))
    record = {o: {"wins": 0, "losses": 0} for o in OWNERS}
    with (
        patch.object(
            playoff_sim,
            "_build_team_distributions",
            return_value=(dists, {o: 0.0 for o in OWNERS}),
        ),
        patch.object(
            playoff_sim,
            "_current_standings",
            return_value=(record, {"medianGame": False, "state": "not_applicable"}),
        ),
        patch.object(playoff_sim, "_remaining_schedule", return_value=_round_robin(14)),
        patch.object(playoff_sim, "_load_ros_strength_map", return_value={}),
        patch.object(playoff_sim, "_league_best_ball", return_value=False),
    ):
        return playoff_sim.simulate_playoff_odds(
            snap, n_simulations=n, playoff_seeds=6, bye_seeds=2
        )


@pytest.fixture
def offline_engine_with_ros(monkeypatch):
    """The canonical engine on the snapshot alone, but WITH real ROS strength."""
    ids = ["alpha", "bravo", "charlie", "xray", "yankee", "zulu"]
    ros = {o: 40.0 + 10.0 * i for i, o in enumerate(ids)}
    monkeypatch.setattr(playoff_sim, "_load_cached_payload", lambda *a, **k: None)
    monkeypatch.setattr(playoff_sim, "_load_ros_strength_map", lambda *a, **k: dict(ros))
    monkeypatch.setattr(playoff_sim, "_load_team_depth_ratios", lambda *a, **k: {})
    monkeypatch.setattr(playoff_sim, "_league_best_ball", lambda *a, **k: False)
    monkeypatch.setattr(
        "src.public_league.draft_order.league_draft_order_rule", lambda *a, **k: None
    )
    return ids


def test_zero_games_with_ros_strength_publishes_no_certainty(offline_engine_with_ros):
    """Zero finished weeks, a posted 3-week schedule and ROS strength for every owner.

    Preseason ROS evidence cannot stand in for the missing score history: the
    engine refuses by name and the public section carries no probability at all
    (not 1.0, not 0.0, not a coin flip).
    """
    payload = _po.compute_playoff_odds(_snapshot_no_games(offline_engine_with_ros))
    assert payload["weeksPlayed"] == 0
    assert payload["weeksRemaining"] == 3
    assert payload["simulated"] is False
    assert [o["playoffProbability"] for o in payload["owners"]] == [None] * len(
        offline_engine_with_ros
    )
    assert payload["unsimulable"]["reason"] == "no_scored_weeks_in_league"


def test_zero_games_14_posted_weeks_with_variance_spreads_probabilities():
    """Control for the finding's own shape: 12 teams, 14 posted weeks, 0 played.

    With real score variance the engine returns graded, non-degenerate odds.
    """
    out = _simulate(sd=20.0, mean_of=lambda i: 100.0 + 2.0 * i)
    odds = [r["playoffOdds"] for r in out["playoffOdds"]]
    assert len(odds) == 12
    assert all(0.0 < p < 1.0 for p in odds), odds
    assert len(set(odds)) >= 6, odds
    assert min(odds) < 0.3 and max(odds) > 0.7, "means differ, so the odds must too"


# Measured: sd = 0 with distinct means and 14 weeks left -> every owner exactly
# 0.0 or 1.0, ``converged: True``, ``worstPlayoffOddsSe: 0.0``.  The gate is blind
# to a zero-variance result.  Flips (strict) when the gate learns to refuse or
# flag it.  Not reachable from the production builders (sd floored at 1.0).
@pytest.mark.xfail(
    strict=True,
    reason="W30-F002: converged=True is stamped on a degenerate 0/1 result with weeks remaining",
)
def test_degenerate_result_is_not_certified_converged():
    out = _simulate(sd=0.0, mean_of=lambda i: 100.0 + 2.0 * i)
    odds = {r["playoffOdds"] for r in out["playoffOdds"]}
    degenerate = odds <= {0.0, 1.0}
    assert degenerate, "harness drift: expected the zero-variance run to be all 0/1"
    assert out.get("converged") is not True
