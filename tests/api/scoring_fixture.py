"""Shared factual-scoring fixtures (W18-F001).

Cross-league ranking reuse is decided by a league's ACTUAL scoring card,
not by the ``scoringProfile`` label in the registry, and an unverifiable
identity fails closed.  So any test whose registry has two leagues and
whose request crosses between them has to say what those leagues
actually score — otherwise it is asserting against the fail-closed path
by accident.

Lives in its own module rather than in one test file because three
suites need it and importing a fixture module is clearer than importing
from a sibling test.
"""

from __future__ import annotations

from typing import Any

from src.api import league_registry

#: Two genuinely different cards.  The differences are the real ones
#: between the repo's two live leagues (full PPR vs 0.08, 4-point vs
#: 6-point passing TDs), so a test that mixes them is modelling a real
#: incompatibility rather than an invented one.
SCORING_CARD: dict[str, float] = {
    "rec": 1.0,
    "pass_td": 4.0,
    "pass_yd": 0.04,
    "pass_int": -1.0,
}
OTHER_SCORING_CARD: dict[str, float] = {
    "rec": 0.08,
    "pass_td": 6.0,
    "pass_yd": 1 / 30,
    "pass_int": -4.0,
}


def install_scoring_snapshots(tmp_path, monkeypatch, cards: dict[str, Any]) -> None:
    """Point the snapshot store at ``tmp_path`` and seed it.

    ``cards`` maps Sleeper league id → scoring settings.  A league with
    no entry is UNVERIFIABLE and every cross-league path involving it
    must fail closed.
    """
    from src.bdvm.actuals import nfl_projection_season

    directory = tmp_path / "league-scoring"
    if directory.exists():
        # Called twice in one test (fixture, then a narrower override)
        # the leftovers would silently keep a league "verified".
        for stale in directory.glob("scoring_*.json"):
            stale.unlink()
    monkeypatch.setenv("LEAGUE_SCORING_SNAPSHOT_DIR", str(directory))
    league_registry._scoring_fp_cache.clear()
    # Record the current season, exactly as ``refresh_scoring_snapshot``
    # does (``season=info.season``).  A card whose season cannot be
    # verified is STALE and proves nothing, which is its own test case in
    # test_scoring_compatibility.py — not the state these routing
    # fixtures are trying to set up.
    season = str(nfl_projection_season())
    for league_id, card in cards.items():
        league_registry.write_scoring_snapshot(league_id, card, season=season)
