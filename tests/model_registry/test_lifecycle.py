"""End-to-end: refit -> challenger -> validation -> promotion -> rollback.

The unit tests cover each piece.  This covers the property that matters
operationally: a challenger cannot reach production without clearing
the gate, and a human can undo it in one step.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from src.model_registry.holdout import evaluate_offense_master, hill
from src.model_registry.promotion import decide_promotion
from src.model_registry.versioning import ModelRegistry, ModelVersion

CHAMPION = {"HILL_PERCENTILE_C": 0.118, "HILL_PERCENTILE_S": 1.17}


def _board(path: Path, c: float, s: float, n: int = 400) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["name", "value"])
        w.writeheader()
        for i in range(n):
            w.writerow({"name": f"p{i}", "value": hill(i / (n - 1), c, s)})


@pytest.fixture
def world(tmp_path):
    """Three held-out boards whose true shape is (0.100, 1.25).

    The incumbent (0.118, 1.17) is therefore genuinely wrong, and a
    challenger closer to the truth genuinely deserves promotion — the
    fixture is not rigged toward either outcome.
    """
    for i in range(3):
        _board(tmp_path / f"h{i}.csv", 0.100 + i * 0.002, 1.25)
    sources = {f"H{i}": (f"h{i}.csv", "value") for i in range(3)}

    def score(params):
        return evaluate_offense_master(
            params["HILL_PERCENTILE_C"],
            params["HILL_PERCENTILE_S"],
            repo_root=tmp_path,
            holdout_sources=sources,
            training_sources={},
        )

    return score


def _registry(champ_holdout=None) -> ModelRegistry:
    reg = ModelRegistry("hill")
    reg.seed_champion(
        ModelVersion(
            model_id="hill",
            version=1,
            params=dict(CHAMPION),
            fitted_at="2026-07-01T00:00:00+00:00",
            producer="seed",
            holdout=champ_holdout,
        )
    )
    return reg


def test_a_better_challenger_is_promoted_and_can_be_rolled_back(world, tmp_path):
    champ_score = world(CHAMPION)
    reg = _registry(champ_score.to_dict())

    better = {"HILL_PERCENTILE_C": 0.101, "HILL_PERCENTILE_S": 1.24}
    chal_score = world(better)
    reg.add(
        ModelVersion(
            model_id="hill",
            version=2,
            params=better,
            fitted_at="2026-07-08T00:00:00+00:00",
            producer="refit",
            holdout=chal_score.to_dict(),
        )
    )

    decision = decide_promotion(champ_score.criterion, chal_score.criterion)
    assert decision.promote, decision.reason

    reg.promote(2, reason=decision.reason)
    assert reg.champion.params == better
    assert reg.champion.confidence == "measured"

    reg.rollback(reason="prod regression")
    assert reg.champion.params == CHAMPION

    reg.save(tmp_path)
    assert ModelRegistry.load("hill", tmp_path).champion.params == CHAMPION


def test_a_worse_challenger_never_reaches_production(world):
    """MECHANISM TEST. The gate's reason for existing."""
    champ_score = world(CHAMPION)
    reg = _registry(champ_score.to_dict())

    worse = {"HILL_PERCENTILE_C": 0.180, "HILL_PERCENTILE_S": 1.60}
    chal_score = world(worse)
    reg.add(
        ModelVersion(
            model_id="hill",
            version=2,
            params=worse,
            fitted_at="",
            producer="refit",
            holdout=chal_score.to_dict(),
        )
    )

    decision = decide_promotion(champ_score.criterion, chal_score.criterion)
    assert not decision.promote
    reg.reject(2, reason=decision.reason)

    assert reg.champion.version == 1
    assert reg.champion.params == CHAMPION
    assert reg.get(2).status == "rejected"


def test_a_noise_level_challenger_does_not_churn_production(world):
    champ_score = world(CHAMPION)
    nudged = world({"HILL_PERCENTILE_C": 0.1181, "HILL_PERCENTILE_S": 1.17})
    decision = decide_promotion(champ_score.criterion, nudged.criterion)
    assert not decision.promote


def test_an_unevaluated_champion_blocks_the_whole_pipeline(world):
    """MECHANISM TEST. Without this, the FIRST refit after the registry
    is seeded would promote unopposed — exactly the autonomous rewrite
    the directive prohibits."""
    reg = _registry(champ_holdout=None)
    assert not reg.champion.qualified

    chal_score = world({"HILL_PERCENTILE_C": 0.100, "HILL_PERCENTILE_S": 1.25})
    decision = decide_promotion((reg.champion.holdout or {}).get("criterion"), chal_score.criterion)
    assert not decision.promote
    assert "unmeasured incumbent" in decision.reason


@pytest.mark.livedata
def test_the_shipped_registry_is_coherent():
    """The committed registry must load, have exactly one champion, and
    state its own confidence."""
    reg = ModelRegistry.load("hill_scope_masters")
    assert reg.champion
    assert reg.champion.confidence in {"unvalidated", "provisional", "measured"}
    if reg.champion.qualified:
        assert reg.champion.holdout["criterion"] > 0
        assert "doesNotMeasure" in reg.champion.holdout["_semantics"]
