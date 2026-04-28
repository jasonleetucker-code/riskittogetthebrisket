"""Player-name → canonical-name resolver for ROS sources.

Reuses the dynasty identity layer (``src.utils.name_clean``) so a
"M. Harrison Jr." in an ROS source lands on the same canonical row a
KTC scrape would.  Confidence-tagged so the aggregator can quarantine
low-confidence matches rather than silently corrupt the blend.

Confidence buckets (per spec):

    1.0  — exact normalize_player_name match
    0.9  — alias hit via CANONICAL_NAME_ALIASES
    0.7  — fuzzy match (single typo / suffix variant)
    <0.6 — quarantine; player excluded from aggregate, reported in run JSON

Manual overrides live at ``data/ros/mapping_overrides.json`` — entries
there bypass the resolver entirely with confidence 1.0.
"""
from __future__ import annotations

import difflib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from src.ros import ROS_DATA_DIR
from src.utils.name_clean import (
    CANONICAL_NAME_ALIASES,
    normalize_player_name,
    resolve_canonical_name,
)

# Reuse dynasty identity layer for all canonical normalization.
_normalize = normalize_player_name
_ALIASES = CANONICAL_NAME_ALIASES


@dataclass(frozen=True)
class MappedPlayer:
    """Result of resolving a source row to a canonical player.

    ``canonical_name`` is the normalized identity.  ``confidence`` is in
    [0, 1].  ``method`` is a debug breadcrumb ("override", "exact",
    "alias", "fuzzy", "quarantine") that surfaces in run metadata.
    """

    source_name: str
    canonical_name: str | None
    confidence: float
    method: str
    position: str | None = None
    team: str | None = None


def _load_overrides() -> dict[str, str]:
    """Read manual mapping overrides, returning {source_name: canonical_name}.

    Tolerates a missing file (returns empty dict) so a fresh checkout
    doesn't crash the resolver.  The override file's top-level
    ``overrides`` key is the actual mapping; ``_comment`` and
    ``_examples`` are documentation-only.
    """
    path = ROS_DATA_DIR / "mapping_overrides.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    raw = data.get("overrides")
    if not isinstance(raw, dict):
        return {}
    return {str(k): str(v) for k, v in raw.items() if v}


def _candidate_pool(canonical_universe: Iterable[str]) -> set[str]:
    """Index the canonical universe for fuzzy matching."""
    return {_normalize(name) for name in canonical_universe if name}


def resolve_player(
    source_name: str,
    *,
    canonical_universe: set[str] | None = None,
    overrides: dict[str, str] | None = None,
    position: str | None = None,
    team: str | None = None,
) -> MappedPlayer:
    """Resolve a source-side player name to the canonical identity.

    ``canonical_universe`` is the set of normalized canonical names the
    dynasty player pool exposes.  When None, only exact-normalize +
    alias paths run (useful for unit tests with no live pool).
    """
    raw = (source_name or "").strip()
    if not raw:
        return MappedPlayer(source_name, None, 0.0, "empty", position, team)

    overrides = overrides if overrides is not None else _load_overrides()

    # 1. Manual override — highest confidence, bypasses everything.
    if raw in overrides:
        return MappedPlayer(raw, overrides[raw], 1.0, "override", position, team)

    normalized = _normalize(raw)

    # 2. Alias table — handles "JJ Smith-Schuster" → "Juju Smith-Schuster" type collapses.
    aliased = _ALIASES.get(normalized)
    if aliased and aliased != normalized:
        # Confidence 0.9 because the alias step transformed the input.
        return MappedPlayer(raw, aliased, 0.9, "alias", position, team)

    # 3. Exact match against the live canonical universe.
    if canonical_universe is not None:
        if normalized in canonical_universe:
            return MappedPlayer(raw, normalized, 1.0, "exact", position, team)

        # 4. Fuzzy match — single-typo / suffix variant.  Restricted to
        # ratio >= 0.92 so we don't silently fold distinct players.
        candidates = difflib.get_close_matches(
            normalized, canonical_universe, n=1, cutoff=0.92
        )
        if candidates:
            return MappedPlayer(raw, candidates[0], 0.7, "fuzzy", position, team)

    # 5. No canonical universe provided — accept the normalize step at
    # confidence 1.0.  Tests that don't pass a universe rely on this
    # path; live aggregation always passes one.
    if canonical_universe is None:
        return MappedPlayer(raw, normalized, 1.0, "exact-no-universe", position, team)

    # 6. Quarantine — no acceptable match.  Aggregator drops these.
    return MappedPlayer(raw, None, 0.0, "quarantine", position, team)
