"""Portfolio optimizer: exact greedy behaviour on known payouts; end-to-end decision is frozen."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from src.dfs import pit, portfolio_opt
from src.dfs.contests import parse_contest
from src.dfs.imports import apply_projection_csv, parse_draftkings_salaries
from src.dfs.optimizer import Constraints, validate_lineup
from src.dfs.rules import get_ruleset

FIX = Path(__file__).parent / "fixtures"
DK = get_ruleset("draftkings.nfl.classic")


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DFS_DATA_DIR", str(tmp_path))


def test_ev_greedy_picks_highest_expected_payouts_and_recommends_only_positive_entries():
    rng = np.random.default_rng(0)
    means = [900.0, 700.0, 450.0, 100.0]  # fee 500: only the first two are clearly profitable
    pay = np.vstack([rng.normal(m, 50.0, 4000) for m in means])
    lus = [("a", "b"), ("c", "d"), ("e", "f"), ("g", "h")]
    out = portfolio_opt.select(
        pay, lus, fee=500, entries=4, objective="ev", bankroll=None, lam=0.0, max_exposure=None
    )
    assert out["chosen"] == [0, 1, 2, 3]
    assert out["recommendedEntries"] == 2
    assert out["trail"][2]["marginalLower90Cents"] < 0


def test_exposure_cap_blocks_overlapping_candidates():
    pay = np.vstack([np.full(100, 1000.0), np.full(100, 900.0), np.full(100, 100.0)])
    lus = [("star", "x"), ("star", "y"), ("z", "w")]
    out = portfolio_opt.select(
        pay, lus, fee=10, entries=2, objective="ev", bankroll=None, lam=0.0, max_exposure=0.5
    )
    assert out["chosen"] == [0, 2]  # the second "star" lineup would exceed 50% exposure


def test_objectives_differ_and_log_growth_requires_a_bankroll():
    # Candidate 0: high mean, all-or-nothing.  Candidate 1: steady, slightly lower mean.
    lottery = np.where(np.arange(1000) < 10, 100_000.0, 0.0)  # mean 1000
    steady = np.full(1000, 900.0)
    pay = np.vstack([lottery, steady])
    lus = [("a",), ("b",)]
    ev = portfolio_opt.select(
        pay, lus, fee=500, entries=1, objective="ev", bankroll=None, lam=0, max_exposure=None
    )
    lg = portfolio_opt.select(
        pay,
        lus,
        fee=500,
        entries=1,
        objective="log_growth",
        bankroll=2_000,
        lam=0,
        max_exposure=None,
    )
    assert ev["chosen"] == [0] and lg["chosen"] == [1]
    with pytest.raises(ValueError):
        portfolio_opt.select(
            pay,
            lus,
            fee=500,
            entries=1,
            objective="log_growth",
            bankroll=None,
            lam=0,
            max_exposure=None,
        )


def test_end_to_end_portfolio_is_legal_compared_and_frozen_as_a_pre_lock_decision():
    athletes, _ = parse_draftkings_salaries(
        (FIX / "synthetic_dk_nfl_classic_salaries.csv").read_text(encoding="utf-8")
    )
    apply_projection_csv(
        athletes, (FIX / "synthetic_dk_nfl_classic_projections.csv").read_text(encoding="utf-8")
    )
    snap = {
        "id": "snap_p",
        "ruleset": DK.key,
        "contentHash": "h" * 64,
        "createdAt": "2026-09-29T00:00:00+00:00",
        "body": {"athletes": [a.to_dict() for a in athletes]},
    }
    contest = parse_contest(
        {
            "name": "Mini",
            "platform": "draftkings",
            "sport": "nfl",
            "format": "classic",
            "entryFee": "5",
            "capacity": 300,
            "tieRule": "split_positions",
            "payoutText": "1 $300\n2 $150\n3-10 $40\n11-60 $10",
        }
    )
    out = portfolio_opt.build_portfolio(
        "o",
        snap,
        DK,
        contest,
        "2026-10-04T16:00:00+00:00",
        base=Constraints(),
        entries=3,
        sims=300,
        field_sample=400,
        seed=2,
        allow_priors=True,
        sample_optimal=8,
        baseline=4,
    )
    by_id = {a.player_id: a for a in athletes}
    slots = [s.name for s in DK.slots]
    chosen = out["result"]["perLineup"]
    assert 1 <= len(chosen) <= 3 and out["candidates"] >= 4
    for row in chosen:
        assert not validate_lineup(list(zip(slots, row["lineup"])), DK, by_id)
    assert out["vsProjectionBaseline"]["profitDifferenceSe"] >= 0
    d = pit.get_decision("o", out["decisionId"])
    assert d["timing"] == "pre_lock" and len(d["selected"]) == len(chosen)
    assert d["rejectedTotal"] == out["candidates"] - len(chosen)
