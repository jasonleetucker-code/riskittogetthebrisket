"""Rookie-pick valuation as outcome distributions (BDVM §5.12 / prompt §9).

A pick is a probability distribution over the player it becomes, never a
guaranteed player-equivalent.  Outcome tables are config
(``config/bdvm/pick_outcomes_v1.json``) — explicitly the most
placeholder-ish priors in the model, to be replaced with distributions
fit from the platform's own historical rookie ADP + later values.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from src.bdvm.params import ParamSet

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTCOMES_PATH = REPO_ROOT / "config" / "bdvm" / "pick_outcomes_v1.json"


class PickConfigError(ValueError):
    pass


@lru_cache(maxsize=4)
def _load_outcomes(path_str: str) -> dict[str, Any]:
    path = Path(path_str)
    if not path.exists():
        raise PickConfigError(f"pick outcomes config missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def pick_value(
    overall_slot: int,
    params: ParamSet,
    *,
    fmt: str = "default",
    class_strength: float = 1.0,
    years_out: int = 0,
    strategy: str = "balanced",
    outcomes_path: Path | None = None,
) -> dict[str, float]:
    """Expected value + distribution stats for one rookie pick.

    ``class_strength`` is clamped to the configured bounds.  Future-year
    picks are discounted with the strategy's discount factor; the
    strategy's ``pick_premium`` captures contender/rebuilder asymmetry
    (picks are cheaper, roster-flexible, and liquid for a rebuilder).
    """
    if overall_slot < 1:
        raise PickConfigError(f"overall_slot must be >= 1, got {overall_slot}")
    cfg = _load_outcomes(str(outcomes_path or DEFAULT_OUTCOMES_PATH))
    fmt_cfg = cfg["formats"].get(fmt) or cfg["formats"]["default"]
    slots = {int(k): v for k, v in fmt_cfg["slots"].items()}
    lo, hi = cfg.get("class_strength_bounds", [0.85, 1.15])
    cs = min(float(hi), max(float(lo), float(class_strength)))

    nearest = min(slots, key=lambda k: abs(k - overall_slot))
    row = slots[nearest]
    p_hit, v_hit = float(row["p_hit"]), float(row["v_hit"])
    p_mid, v_mid = float(row["p_mid"]), float(row["v_mid"])

    st = params.strategy(strategy)
    discount = float(st["discount"]) ** max(0, years_out)
    premium = float(st.get("pick_premium", 1.0))

    ev = (p_hit * v_hit + p_mid * v_mid) * cs * discount * premium
    return {
        "ev": ev,
        "p_hit": p_hit,
        "p_mid": p_mid,
        "p_miss": max(0.0, 1.0 - p_hit - p_mid),
        "ceiling": v_hit * cs,
        "median": v_mid * cs,
        "class_strength": cs,
        "years_out": float(years_out),
    }


def pick_values_all_strategies(
    overall_slot: int,
    params: ParamSet,
    **kwargs: Any,
) -> dict[str, dict[str, float]]:
    return {
        name: pick_value(overall_slot, params, strategy=name, **kwargs)
        for name in params.strategy_names()
    }
