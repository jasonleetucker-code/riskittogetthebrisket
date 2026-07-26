"""Variation guards against the REAL 12 rosters, at full roster depth.

Two lessons are encoded here.

1. ``_positional_coverage`` once returned exactly 100.00 for all 12
   teams — a constant masquerading as a score.  Synthetic fixtures would
   not have caught that, because it only collapsed on live data.  Every
   headline metric is therefore asserted to VARY across the real league.

2. The first WS-J measurement ran on ``startingLineup + benchDepth``
   from the team-strength snapshot — 26 players against real 53-58 man
   rosters.  A truncated pool understates depth and overstates
   fragility, so those figures were directionally wrong in a known
   direction.  These tests join the FULL Sleeper rosters
   (``data/sleeper_last_good.json``) to ROS values and pin the roster
   sizes so a future truncation regresses loudly.

Marked ``livedata``: they read the live snapshots and are excluded from
the blocking suite (``-m "not livedata"``), matching the repo's existing
convention for data-dependent assertions.
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path

import pytest

from src.roster_intel.marginal import absence_impacts, position_marginals, to_roster_players

pytestmark = pytest.mark.livedata

REPO = Path(__file__).resolve().parents[2]
SLEEPER = REPO / "data" / "sleeper_last_good.json"
AGGREGATE = REPO / "data" / "ros" / "aggregate" / "latest.json"


def _norm(s: str) -> str:
    return "".join(c for c in str(s or "").lower() if c.isalnum())


@pytest.fixture(scope="module")
def league():
    if not SLEEPER.exists() or not AGGREGATE.exists():
        pytest.skip("live snapshots not present in this checkout")

    agg = json.loads(AGGREGATE.read_text())
    rows = agg if isinstance(agg, list) else (agg.get("players") or list(agg.values())[0])
    by_name: dict[str, dict] = {}
    for r in rows:
        k = _norm(r.get("canonicalName"))
        if not k:
            continue
        # The WS-E audit recorded duplicate rows with split values; keep
        # the higher one rather than whichever happens to be last.
        if k in by_name and float(r.get("rosValue") or 0) <= float(by_name[k].get("rosValue") or 0):
            continue
        by_name[k] = r

    teams = json.loads(SLEEPER.read_text())["rosterData"]["teams"]

    # Read the registry FILE rather than src.api.league_registry: the
    # module caches a resolved registry and other suites reset it, so
    # get_default_league() returns None depending on test ordering.
    # The file is the same source of truth without the shared state.
    registry_path = REPO / "config" / "leagues" / "registry.json"
    if not registry_path.exists():
        pytest.skip("league registry not present")
    registry = json.loads(registry_path.read_text())
    default_key = registry.get("defaultLeagueKey")
    entry = next(
        (lg for lg in registry.get("leagues") or [] if lg.get("key") == default_key),
        None,
    )
    if entry is None:
        pytest.skip("default league not found in registry")
    starters = ((entry.get("rosterSettings") or {}).get("starters")) or {}
    alias = {"SFLEX": "SUPER_FLEX"}
    slots: list[str] = []
    for slot, count in starters.items():
        try:
            n = int(count)
        except (TypeError, ValueError):
            continue
        if n > 0:
            slots.extend([alias.get(str(slot).upper(), str(slot).upper())] * n)

    built = []
    for t in teams:
        names = t.get("players") or []
        pool_rows = []
        for nm in names:
            hit = by_name.get(_norm(nm))
            if hit is None:
                continue
            pool_rows.append(
                {
                    "playerId": nm,
                    "canonicalName": nm,
                    "position": hit.get("position") or "",
                    "rosValue": float(hit.get("rosValue") or 0.0),
                    "confidence": float(hit.get("confidence") or 0.0),
                    "fantasyPositions": (),
                }
            )
        pool = to_roster_players(pool_rows)
        built.append(
            {
                "name": t.get("name"),
                "rostered": len(names),
                "matched": len(pool_rows),
                "marginals": position_marginals(pool, slots),
                "absence": absence_impacts(pool, slots),
            }
        )
    return built


# ── The truncation guard ───────────────────────────────────────────


def test_rosters_are_full_depth_not_the_26_player_snapshot(league):
    """MECHANISM TEST. Fails if the pool is ever fed from
    ``startingLineup + benchDepth`` (26) instead of the real roster.

    Real rosters run 44-58 players; the team-strength snapshot exposes
    26.  A mean below 40 means someone reconnected the truncated source
    and every depth/fragility number silently became wrong again.
    """
    sizes = [t["rostered"] for t in league]
    assert min(sizes) > 26, f"a roster came in at snapshot depth: {sizes}"
    assert statistics.fmean(sizes) > 40


def test_join_loss_stays_small_and_is_visible(league):
    """The ROS aggregate has known name-casing and duplicate defects
    (WS-E audit).  Some loss is expected; a silent jump is not."""
    rostered = sum(t["rostered"] for t in league)
    matched = sum(t["matched"] for t in league)
    loss = (rostered - matched) / rostered
    assert loss < 0.10, f"join loss {loss:.1%} — identity layer regressed"
    assert matched > 600


# ── Variation guards ───────────────────────────────────────────────


@pytest.mark.parametrize(
    "metric",
    ["lineup_score", "QB_marginal", "RB_marginal", "WR_marginal", "TE_marginal"],
)
def test_headline_metrics_vary_across_the_real_league(league, metric):
    if metric == "lineup_score":
        vals = [t["marginals"].lineup_score for t in league]
    else:
        pos = metric.split("_")[0]
        vals = [
            t["marginals"].by_position[pos].marginal_points
            for t in league
            if pos in t["marginals"].by_position
        ]
    assert len(vals) >= 10
    assert len(set(round(v, 4) for v in vals)) > 1, f"{metric} is constant across 12 real rosters"
    assert (
        statistics.pstdev(vals) > 1.0
    ), f"{metric} barely moves (sd={statistics.pstdev(vals):.3f})"


def test_fragility_varies_and_is_not_the_old_constant(league):
    """The first fragility definition returned ~1/n for everyone.  On
    the real league that would show as a near-zero spread."""
    vals = [t["absence"]["RB"].fragility for t in league if "RB" in t["absence"]]
    assert len(set(round(v, 4) for v in vals)) > 1
    assert statistics.pstdev(vals) > 0.05, "fragility has collapsed toward a constant"
    assert all(0.0 <= v <= 1.0 for v in vals)


def test_clogger_value_discriminates_hoarders(league):
    """Clog is the signal a summed-value metric cannot express.  Some
    roster must be carrying real un-startable value, and some must not."""
    vals = [
        t["marginals"].by_position["QB"].clogger_value
        for t in league
        if "QB" in t["marginals"].by_position
    ]
    assert max(vals) > 20.0, "no roster shows QB clog — suspicious in superflex"
    assert min(vals) < max(vals)


def test_entry_rate_is_below_one_somewhere(league):
    """If every position on every roster had entry rate 1.0, the
    optimizer would not be constraining anything and the metric would be
    decorative."""
    rates = [
        t["marginals"].by_position["QB"].entry_rate
        for t in league
        if "QB" in t["marginals"].by_position
    ]
    assert min(rates) < 1.0
    assert len(set(round(r, 4) for r in rates)) > 1
