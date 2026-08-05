"""Decision-surface thresholds, loaded from ``config/thresholds.json``.

WHY A LOADER AND NOT CONSTANTS
------------------------------
The values used to live in two places — ``frontend/lib/thresholds.js``
and, for the confidence cutoffs, ``src/api/data_contract.py`` — kept in
step by a hand-written comment in the JS header listing the Python names
and their values.  That comment was the sync mechanism.  It is exactly
what ``tests/api/test_source_registry_parity.py`` was written to replace
for the ranking-source registry, and the registry is the one parity
mechanism in this repo that demonstrably works.

So: the JSON is the source.  Python LOADS it, which means the Python
side cannot drift at all.  The JS mirrors it statically (there is no
codegen step in this repo and adding one for fourteen numbers would be
worse than the problem) and ``tests/api/test_threshold_parity.py``
fails the build when the mirror stops matching.

Every entry in the JSON records how its value was derived.  Four of them
were re-derived in batch C4 because the market gap changed units — from
ordinal ranks, which are incomparable across boards of different depth,
to rank-space per-mille.  A threshold whose ``derivedFrom`` says nothing
is a number somebody invented, and the test below refuses one.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "thresholds.json"

__all__ = [
    "load_thresholds",
    "threshold",
    "threshold_entries",
    "CONFIG_PATH",
]

CONFIG_PATH = _CONFIG_PATH


@lru_cache(maxsize=1)
def _document() -> dict[str, Any]:
    return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))


def threshold_entries() -> dict[str, dict[str, Any]]:
    """The full entries, including unit and derivation, by name."""
    raw = _document().get("thresholds")
    if not isinstance(raw, dict):
        raise ValueError(f"{_CONFIG_PATH} has no 'thresholds' object")
    return {str(k): dict(v) for k, v in raw.items() if isinstance(v, dict)}


def load_thresholds() -> dict[str, float]:
    """Just the numbers, by name — what callers gating on a value want."""
    return {name: entry["value"] for name, entry in threshold_entries().items()}


def threshold(name: str) -> float:
    """One threshold by name.

    Raises on an unknown name rather than returning a default.  A
    missing threshold means a caller and this file disagree about what
    exists, and silently substituting a number would gate a decision
    surface on a value nobody chose — the failure mode this whole batch
    is about.
    """
    entries = threshold_entries()
    if name not in entries:
        raise KeyError(f"no threshold named {name!r} in {_CONFIG_PATH}")
    return entries[name]["value"]
