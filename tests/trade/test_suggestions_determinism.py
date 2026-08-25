"""The suggestions API is deterministic across interpreter hash seeds.

``_opponent_fit_label`` built its "needs POS, POS, POS" clause by joining a
SET, so one suggestion produced different `/api/trade/suggestions` bytes in
different processes — measured before the repair: four distinct labels for
the same input across ``PYTHONHASHSEED`` 0/1/7/42.  Sets are the right
container for the membership checks above the join; the JOIN is where an
order must be chosen, and it must be chosen by the data, not the seed.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from src.trade.suggestions import PlayerAsset, TradeSuggestion, _opponent_fit_label

REPO = Path(__file__).resolve().parents[2]

_PROBE = """
from types import SimpleNamespace
from src.trade.suggestions import _opponent_fit_label, TradeSuggestion, PlayerAsset
mk = lambda n, p, v: PlayerAsset(name=n, position=p, display_value=v, calibrated_value=v)
s = TradeSuggestion(
    type="sell_high",
    give=[mk("A", "WR", 100), mk("B", "RB", 100), mk("C", "TE", 100)],
    receive=[mk("D", "QB", 300)],
    give_total=300, receive_total=300, gap=0, fairness="even",
    rationale="", why_this_helps="", confidence=0.5, strategy="balanced",
)
opp = SimpleNamespace(need_positions={"WR", "RB", "TE"}, surplus_positions=set())
print(_opponent_fit_label(s, {"Team Z": opp}))
"""


def _mk(name: str, pos: str, val: int) -> PlayerAsset:
    return PlayerAsset(name=name, position=pos, display_value=val, calibrated_value=val)


def _suggestion() -> TradeSuggestion:
    return TradeSuggestion(
        type="sell_high",
        give=[_mk("A", "WR", 100), _mk("B", "RB", 100), _mk("C", "TE", 100)],
        receive=[_mk("D", "QB", 300)],
        give_total=300,
        receive_total=300,
        gap=0,
        fairness="even",
        rationale="",
        why_this_helps="",
        confidence=0.5,
        strategy="balanced",
    )


def test_the_needs_clause_is_sorted_not_seed_ordered():
    opp = SimpleNamespace(need_positions={"WR", "RB", "TE"}, surplus_positions=set())
    label = _opponent_fit_label(_suggestion(), {"Team Z": opp})
    assert label == "Strong bilateral fit: Team Z needs RB, TE, WR and could deal."


def test_the_label_is_identical_across_hash_seeds():
    """The property, proven the only way it can be: separate interpreters.

    In-process assertions cannot exercise hash randomisation — every call in
    one process shares one seed.  Before the repair this test fails with
    multiple distinct labels; after it, one.
    """
    outputs = set()
    for seed in ("0", "1", "7", "42"):
        env = dict(os.environ)
        env["PYTHONHASHSEED"] = seed
        result = subprocess.run(
            [sys.executable, "-c", _PROBE],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(REPO),
            timeout=120,
        )
        assert result.returncode == 0, result.stderr[-2000:]
        outputs.add(result.stdout.strip())
    assert len(outputs) == 1, (
        f"one suggestion produced {len(outputs)} distinct labels across hash "
        f"seeds: {sorted(outputs)}"
    )
