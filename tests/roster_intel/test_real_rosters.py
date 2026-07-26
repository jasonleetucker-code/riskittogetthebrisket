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

from src.league_intel.replacement import compute_replacement_levels
from src.roster_intel.engine import analyze_roster
from src.roster_intel.marginal import (
    absence_impacts,
    optimal_score,
    position_marginals,
    to_roster_players,
)
from src.roster_intel.window import COMPETITIVE_STATES

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
                "owner": str(t.get("ownerId") or t.get("name")),
                "slots": slots,
                "rows": pool_rows,
                "pool": pool,
                "rostered": len(names),
                "matched": len(pool_rows),
                "marginals": position_marginals(pool, slots),
                "absence": absence_impacts(pool, slots),
            }
        )
    return built


@pytest.fixture(scope="module")
def intel(league):
    """Full :func:`analyze_roster` output for all 12 real rosters.

    Replacement levels are computed from the same 12 rosters (the
    league IS the replacement market), and lineup scores are passed so
    the window's competitiveness axis has a real source rather than the
    "unavailable" default — the default would hand every team the same
    median and manufacture the constant this file exists to catch.
    """
    slots = league[0]["slots"]
    replacement = compute_replacement_levels([{"players": t["rows"]} for t in league], slots)
    lineup_scores = {t["owner"]: optimal_score(t["pool"], slots) for t in league}
    return [
        analyze_roster(
            t["owner"],
            t["pool"],
            slots,
            replacement=replacement,
            lineup_scores=lineup_scores,
        )
        for t in league
    ]


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


# ── Engine rollups: variation on the real league ────────────────────


@pytest.mark.parametrize(
    "attr",
    ["ros", "starters_ros", "bench_ros"],
)
def test_value_rollups_vary_across_the_real_league(intel, attr):
    vals = [getattr(t.values, attr) for t in intel]
    assert len(set(round(v, 3) for v in vals)) == len(vals), f"values.{attr} has ties across 12"
    assert statistics.pstdev(vals) > 10.0


def test_starters_and_bench_split_the_roster(intel):
    """MECHANISM TEST. Fails if the starters/bench split stops reading
    the optimizer's assignment and degenerates (all-starters or
    all-bench), which would make ``benchRos`` a copy of ``ros``."""
    for t in intel:
        assert t.values.starters_ros > 0
        assert t.values.bench_ros > 0
        assert abs((t.values.starters_ros + t.values.bench_ros) - t.values.ros) < 0.01
        # The optimal lineup is 21 slots against 44-58 rostered
        # players; if starters were the whole roster the split is off.
        assert t.values.starters_ros < t.values.ros


def test_lineup_score_equals_the_starters_rollup(intel):
    """The two are computed by different code paths (marginal solve vs
    value rollup over assigned ids). They must agree, or one of them is
    reading a stale assignment."""
    for t in intel:
        assert abs(t.lineup_score - t.values.starters_ros) < 0.01


def test_needs_vary_and_are_not_all_zero(intel):
    """Contribution must vary everywhere; deficit must be positive
    SOMEWHERE. A board where nobody is ever below replacement means the
    baseline is not being applied."""
    positions = sorted({p for t in intel for p in t.needs})
    assert len(positions) >= 6

    for pos in positions:
        contribs = [t.needs[pos].actual_contribution for t in intel if pos in t.needs]
        risks = [t.needs[pos].concentration_risk for t in intel if pos in t.needs]
        if len(contribs) < 10:
            continue
        assert (
            len(set(round(v, 3) for v in contribs)) > 1
        ), f"needs[{pos}].actualContribution is constant across 12 real rosters"
        assert (
            len(set(round(v, 4) for v in risks)) > 1
        ), f"needs[{pos}].concentrationRisk is constant across 12 real rosters"

    positive = [(t.owner_id, p) for t in intel for p, n in t.needs.items() if n.deficit > 0]
    assert positive, "no roster is below replacement anywhere — baseline not applied"
    # ...and not EVERY roster/position, which would mean the baseline is
    # scaled wrong rather than applied.
    total = sum(len(t.needs) for t in intel)
    assert len(positive) < total * 0.5, f"{len(positive)}/{total} positions in deficit"


def test_deficit_does_not_follow_concentration_on_the_real_league(intel):
    """MECHANISM TEST — the inversion a consumer actually hit.

    Deriving need as ``fragility x marginal`` crowns the position a
    roster is STRONGEST at, because a great room is concentrated by
    definition. Measured here: the naive formula names QB the top need
    for the team with the highest QB contribution in the league.

    This fails if ``position_needs`` is ever reimplemented in terms of
    fragility.
    """
    qb = [(t.owner_id, t.needs["QB"]) for t in intel if "QB" in t.needs]
    assert len(qb) == 12

    naive_top = max(qb, key=lambda kv: kv[1].concentration_risk * kv[1].actual_contribution)
    strongest = max(qb, key=lambda kv: kv[1].actual_contribution)
    assert naive_top[0] == strongest[0], (
        "the naive derivation no longer inverts on this data; this test's "
        "premise needs re-measuring, not deleting"
    )
    # The engine must NOT agree with it.
    assert naive_top[1].deficit == 0.0, (
        "engine reports a deficit at the league's strongest QB room — "
        "position_needs has been rewired to fragility"
    )

    # And the engine's own top need must differ from the naive pick on
    # most rosters, or it is tracking concentration by accident.
    disagreements = 0
    for t in intel:
        if not t.needs:
            continue
        engine_top = max(t.needs.values(), key=lambda n: n.deficit)
        naive = max(t.needs.values(), key=lambda n: n.concentration_risk * n.actual_contribution)
        if engine_top.position != naive.position:
            disagreements += 1
    assert disagreements >= 9, f"engine agreed with the naive ranking on {12 - disagreements}/12"


# ── Competitive window on the real league ──────────────────────────


def test_window_probabilities_vary_and_stay_normalized(intel):
    for state in COMPETITIVE_STATES:
        vals = [t.window.probabilities[state] for t in intel]
        assert (
            len(set(round(v, 4) for v in vals)) > 1
        ), f"window p[{state}] is constant across 12 real rosters"
    for t in intel:
        assert abs(sum(t.window.probabilities.values()) - 1.0) < 1e-9
        serialized = t.window.to_dict()["probabilities"]
        assert abs(sum(serialized.values()) - 1.0) < 1e-9


def test_window_assigns_more_than_one_state_across_the_league(intel):
    """A 12-team league that reads as one state is a broken classifier,
    not a uniform league."""
    labels = [t.window.most_likely for t in intel]
    assert len(set(labels)) >= 3, f"only {set(labels)} across 12 rosters"
    assert max(labels.count(x) for x in set(labels)) <= 6


def test_missing_ages_are_disclosed_rather_than_absorbed(intel):
    """MECHANISM TEST for the live wiring gap.

    No committed artifact carries player ages — they arrive only on the
    live Sleeper overlay — so on this data the trajectory axis is
    pinned neutral and the window is a competitiveness-only read. That
    is survivable ONLY because it is stated. This fails if the note is
    dropped, or if a future age source lands and the note is left
    stale.
    """
    for t in intel:
        has_ages = t.window.inputs.trajectory_sample > 0
        disclosed = any("ages" in n for n in t.notes)
        assert has_ages != disclosed, (
            f"{t.owner_id}: trajectory_sample={t.window.inputs.trajectory_sample} "
            f"but age disclosure={disclosed}"
        )
        if not has_ages:
            assert t.window.inputs.trajectory == pytest.approx(0.5)


def test_odds_absence_is_disclosed(intel):
    """No simulator output is supplied here, so every roster must say
    so rather than present a structural proxy as simulated odds."""
    for t in intel:
        assert t.playoff_odds is None
        assert t.championship_odds is None
        assert t.odds_source == "unavailable"
        assert any("playoff_sim" in n for n in t.notes)
        assert t.window.inputs.competitiveness_source == "lineupScoreRank"
