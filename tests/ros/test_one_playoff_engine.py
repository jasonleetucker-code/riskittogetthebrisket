"""C5-PLAY-01 / V1-51 — ONE playoff / title probability engine.

THE DEFECT, measured on the committed 2026-10-07 week-5 state (four finished
weeks, every remaining regular-season week posted).  Two simulators were both
served in production, on two tabs of the same /league page, and disagreed:

=============  =====================================  =====================
team           ``playoffOdds`` (public_league engine)  ``rosPlayoffOdds``
=============  =====================================  =====================
Kich           99.0%                                  77.2%
Collin         85.1%                                  99.4%
=============  =====================================  =====================

The bracket had already been unified (``playoff_structure``, #919/#930) and
both engines read finished weeks through the same gate (#1435, #1465).  What
differed was the MODEL: the public engine resampled each team's own past
weekly scores; ``src/ros/playoff_sim.py`` draws from ROS-informed, best-ball
pre-simulated distributions.  ``rosChampionship`` was a THIRD loop
(``championship.py``) over playoff_sim's distributions with its own bracket.

WHY ``playoff_sim`` IS THE CANONICAL ENGINE (the evidence, all in code):

* model identity + point-in-time capture: ``src/ros/forecast_archive.py``
  (AL-P6) archives every forecast ``ros/scrape.py`` writes, with
  ``simParams`` read off ``playoff_sim``'s module constants, and an identity
  sidecar (``data/ros/sims/*.identity.json``) — the public engine computed
  per request and was never captured, so it could never be calibrated;
* ``draftSlotDistribution`` / ``finalWins`` under the league's recorded
  draft-order rule — consumed by the pick projector
  (``src/ros/pick_projection.py``, ``src/trade/pick_market.py``,
  ``src/ros/pick_forecast_snapshot.py``, #1642/#1652);
* championship odds from the SAME seeding draw (the public engine had none);
* adaptive convergence with Wilson intervals (``playoffOddsCi``) consumed by
  ``src/roster_intel`` / ``src/api/gameplan.py``;
* the league's exact lineup solve for best-ball weeks.

Exact league rules: both read the bracket from ``playoff_structure`` and the
record from ``playoff_odds._regular_season_record_to_date``; NEITHER counted
median games (owner decision D3) — so consolidating moves no league rule.
D2 (the ``ROS_BLEND`` multiplier on top of a ROS-drawn pre-sim) and D3 stay
exactly as the canonical engine has them, and every surface now inherits
them (``docs/OWNER_REQUESTED_TODO.md``).

WHAT THIS FILE PINS: the three surfaces publish IDENTICAL numbers for one
league and week (the parity test fails the moment any of them simulates on
its own again); each surface keeps the response shape its consumers read;
the canonical engine's own numbers did not move; and missing stays missing.
"""

from __future__ import annotations

import ast
import json
import random
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.public_league import playoff_odds as public_odds
from src.ros import championship, playoff_sim

REPO = Path(__file__).resolve().parents[2]

# ── a realistic league ────────────────────────────────────────────────


def _league(
    *,
    n_teams: int = 12,
    finished_weeks: int = 4,
    weeks: int = 14,
    playoff_teams: int = 7,
    root: str = "LPARITY",
    generated_at: str = "2026-10-07T17:39:18+00:00",
    seed: int = 11,
):
    """``finished_weeks`` scored weeks (host clock agrees), the rest of the
    regular season POSTED with ``0.0`` stubs, exactly as Sleeper serves it."""
    rng = random.Random(seed)
    owners = [f"owner{i:02d}" for i in range(1, n_teams + 1)]
    matchups: dict[int, list[dict]] = {}
    for wk in range(1, weeks + 1):
        rot = owners[:1] + owners[1:][wk % (n_teams - 1) :] + owners[1:][: wk % (n_teams - 1)]
        rows = []
        for m in range(n_teams // 2):
            for oid in (rot[m], rot[-(m + 1)]):
                pts = round(rng.uniform(80, 160), 2) if wk <= finished_weeks else 0.0
                rows.append(
                    {"roster_id": owners.index(oid) + 1, "matchup_id": m + 1, "points": pts}
                )
        matchups[wk] = rows
    season = SimpleNamespace(
        season="2026",
        league_id=root,
        league={
            "settings": {
                "last_scored_leg": finished_weeks,
                "playoff_teams": playoff_teams,
                "playoff_week_start": weeks + 1,
            }
        },
        num_teams=n_teams,
        rosters=[{"roster_id": i, "owner_id": owners[i - 1]} for i in range(1, n_teams + 1)],
        matchups_by_week=matchups,
        regular_season_weeks=list(range(1, weeks + 1)),
        winners_bracket=[],
        losers_bracket=[],
    )
    managers = SimpleNamespace(
        roster_to_owner={(root, i): owners[i - 1] for i in range(1, n_teams + 1)},
        by_owner_id={o: SimpleNamespace(display_name=o.upper()) for o in owners},
    )
    snap = SimpleNamespace(
        seasons=[season],
        current_season=season,
        managers=managers,
        root_league_id=root,
        generated_at=generated_at,
    )
    return snap, owners


#: ROS team strength for the twelve owners — deliberately NOT monotone in the
#: owner index, so the record and the roster disagree for some teams (the
#: exact situation in which the retired empirical engine and this one split).
_STRENGTH = [41.0, 77.0, 58.0, 90.0, 33.0, 66.0, 52.0, 70.0, 45.0, 61.0, 38.0, 84.0]


@pytest.fixture
def engine(monkeypatch, tmp_path):
    """The canonical engine on the snapshot + a fixed ROS strength map: no
    real cache file, no best-ball roster reads, no draft-order registry."""
    monkeypatch.setattr(playoff_sim, "ROS_DATA_DIR", tmp_path)
    monkeypatch.setattr(playoff_sim, "_league_best_ball", lambda *a, **k: False)
    monkeypatch.setattr(playoff_sim, "_load_team_depth_ratios", lambda *a, **k: {})
    monkeypatch.setattr(
        "src.ros.team_strength.resolve_snapshot_league_key", lambda snap: "dynasty_parity"
    )
    monkeypatch.setattr(
        "src.api.league_registry.default_league_key", lambda *a, **k: "dynasty_main"
    )
    monkeypatch.setattr(
        "src.public_league.draft_order.league_draft_order_rule", lambda *a, **k: None
    )
    strengths: dict[str, float] = {}
    monkeypatch.setattr(playoff_sim, "_load_ros_strength_map", lambda *a, **k: dict(strengths))
    # ``getattr``: lets this file run against the pre-consolidation tree too,
    # which is how its parity tests were shown to FAIL there.
    memo = getattr(playoff_sim, "_LIVE_MEMO", {})
    memo.clear()
    yield SimpleNamespace(tmp=tmp_path, strengths=strengths)
    memo.clear()


def _with_strength(engine, owners):
    engine.strengths.clear()
    engine.strengths.update(dict(zip(owners, _STRENGTH)))


def _served(snap):
    """The three published surfaces, through their real section builders."""
    return (
        public_odds.build_section(snap),
        playoff_sim.build_section(snap),
        championship.build_section(snap),
    )


# ── the parity contract ───────────────────────────────────────────────


def _assert_one_answer(public, ros, champ):
    """The invariant, stated once: every probability a surface publishes for
    an owner is the canonical forecast's number for that owner."""
    canonical = {r["ownerId"]: r for r in ros["playoffOdds"]}
    assert canonical, "the canonical forecast published nothing to compare"

    pub = {o["ownerId"]: o["playoffProbability"] for o in public["owners"]}
    assert pub == {o: r["playoffOdds"] for o, r in canonical.items()}, (
        "playoffOdds and rosPlayoffOdds publish different playoff odds for "
        "one league and week — two engines are answering"
    )
    assert public["numSims"] == ros["n_simulations"] == champ["n_simulations"]

    champ_rows = {r["ownerId"]: r for r in champ["championshipOdds"]}
    assert set(champ_rows) == set(canonical)
    for owner, row in champ_rows.items():
        for field in (
            "playoffOdds",
            "championshipOdds",
            "finalsOdds",
            "semifinalOdds",
            "expectedFinish",
        ):
            assert row[field] == canonical[owner][field], (
                f"rosChampionship.{field} for {owner} is {row[field]}, the canonical "
                f"forecast says {canonical[owner][field]}"
            )


def test_three_surfaces_publish_one_answer_on_a_live_run(engine):
    """No cache file: the live fallback runs ONCE and every surface reads it."""
    snap, owners = _league()
    _with_strength(engine, owners)
    calls = {"n": 0}
    real = playoff_sim.simulate_playoff_odds

    def _counting(*a, **k):
        calls["n"] += 1
        return real(*a, **k)

    with patch.object(playoff_sim, "simulate_playoff_odds", _counting):
        public, ros, champ = _served(snap)
    assert calls["n"] == 1, f"{calls['n']} simulations ran for one snapshot"
    _assert_one_answer(public, ros, champ)
    assert public["simulated"] is True
    assert public["scheduleCertainty"] == "posted"


def test_three_surfaces_publish_one_answer_from_the_scheduled_file(engine):
    """The production path: the scrape's file, read by all three."""
    snap, owners = _league()
    _with_strength(engine, owners)
    forecast = playoff_sim.simulate_playoff_odds(snap, rng=random.Random(5))
    sims = engine.tmp / "sims"
    sims.mkdir()
    (sims / "dynasty_parity_playoff.json").write_text(
        json.dumps({"computedAt": "2026-10-07T17:39:24+00:00", **forecast})
    )
    with patch.object(playoff_sim, "simulate_playoff_odds", side_effect=AssertionError):
        public, ros, champ = _served(snap)
    assert ros["cached"] is True and public["forecastCached"] is True
    assert champ["computedAt"] == public["forecastComputedAt"] == ros["computedAt"]
    _assert_one_answer(public, ros, champ)


def test_the_scrape_writes_both_files_from_one_simulation(engine, monkeypatch):
    """``*_championship.json`` (read by the trade-deadline rollup and the
    AL-P6 archive) is the playoff forecast reshaped, not a second run."""
    from src.ros import scrape

    snap, owners = _league()
    _with_strength(engine, owners)
    monkeypatch.setattr(scrape, "ROS_DATA_DIR", engine.tmp)
    monkeypatch.setattr("src.public_league.snapshot.build_public_snapshot", lambda *a, **k: snap)
    monkeypatch.setattr(scrape, "_archive_forecast", lambda *a, **k: None)
    calls = {"n": 0}
    real = playoff_sim.simulate_playoff_odds

    def _counting(*a, **k):
        calls["n"] += 1
        return real(*a, **k)

    monkeypatch.setattr(playoff_sim, "simulate_playoff_odds", _counting)
    cfg = SimpleNamespace(key="dynasty_parity", sleeper_league_id="LPARITY", best_ball=False)
    out = scrape._refresh_sim_caches_for_league(cfg, "dynasty_main")
    assert calls["n"] == 1
    playoff = json.loads(out["playoff"].read_text())
    champ = json.loads(out["championship"].read_text())
    assert champ["computedAt"] == playoff["computedAt"]
    by_owner = {r["ownerId"]: r for r in playoff["playoffOdds"]}
    for row in champ["championshipOdds"]:
        assert row["championshipOdds"] == by_owner[row["ownerId"]]["championshipOdds"]
        assert row["playoffOdds"] == by_owner[row["ownerId"]]["playoffOdds"]


def test_a_stale_week_file_is_not_laid_beside_a_newer_record(engine):
    """Fetched recently is not content fresh.  A file simulated before the
    latest week finalised would sit next to a record that already counts
    it; the shared accessor re-simulates instead, for every surface."""
    snap, owners = _league(finished_weeks=4)
    _with_strength(engine, owners)
    old_snap, _ = _league(finished_weeks=3)
    stale = playoff_sim.simulate_playoff_odds(old_snap, rng=random.Random(5))
    assert stale["regularSeasonProgress"]["weeksFinal"] == 3
    sims = engine.tmp / "sims"
    sims.mkdir()
    (sims / "dynasty_parity_playoff.json").write_text(json.dumps(stale))
    public, ros, champ = _served(snap)
    assert ros["cached"] is False
    assert ros["regularSeasonProgress"]["weeksFinal"] == 4 == public["weeksPlayed"]
    _assert_one_answer(public, ros, champ)


def test_a_file_without_bracket_depth_is_not_served_as_current(engine):
    """A forecast written before this engine recorded finals / semifinal /
    expected finish would force the Championship tab to publish those
    columns as missing, so it is re-simulated rather than served."""
    snap, owners = _league()
    _with_strength(engine, owners)
    forecast = playoff_sim.simulate_playoff_odds(snap, rng=random.Random(5))
    for row in forecast["playoffOdds"]:
        del row["finalsOdds"]
    assert not playoff_sim.cached_forecast_matches_snapshot(forecast, snap)


def test_the_divergence_this_removes_is_real(engine):
    """Non-vacuity.  The retired public engine (git ``origin/main`` before
    C5-PLAY-01) resampled each team's own scores; on this league it and the
    canonical engine disagree by far more than Monte Carlo error, which is
    what the parity test above would catch if a second engine came back."""
    snap, owners = _league()
    _with_strength(engine, owners)
    ros = playoff_sim.simulate_playoff_odds(snap, rng=random.Random(5))
    canonical = {r["ownerId"]: r["playoffOdds"] for r in ros["playoffOdds"]}
    # Empirical resampling, the retired model, re-stated minimally here ONLY
    # as a witness (it is not reachable from src/): sample each owner's own
    # finished-week scores for every posted remaining matchup.
    season = snap.current_season
    per_owner, _ = public_odds._season_weekly_scores(season, snap.managers)
    record = public_odds._regular_season_record_to_date(season, snap.managers)
    posted = public_odds._posted_future_matchups(season, snap.managers)
    rng = random.Random(9)
    made = dict.fromkeys(owners, 0)
    n = 4000
    for _ in range(n):
        wins = {o: record[o]["wins"] for o in owners}
        pf = {o: record[o]["pointsFor"] for o in owners}
        for pairs in posted.values():
            for a, b in pairs:
                sa, sb = rng.choice(per_owner[a]), rng.choice(per_owner[b])
                pf[a] += sa
                pf[b] += sb
                wins[a if sa > sb else b] += 1
        for o in public_odds.standings_from_sim(wins, pf, owners, rng=rng)[:7]:
            made[o] += 1
    gap = max(abs(made[o] / n - canonical[o]) for o in owners)
    assert gap > 0.10, f"the two models agree to {gap:.3f}; the witness proves nothing"


# ── the shapes consumers read ─────────────────────────────────────────

_PUBLIC_KEYS = {
    "season",
    "numSims",
    "playoffSpots",
    "weeksPlayed",
    "weeksRemaining",
    "scheduleCertainty",
    "simulated",
    "owners",
}
_PUBLIC_OWNER_KEYS = {
    "ownerId",
    "displayName",
    "currentWins",
    "currentPointsFor",
    "playoffProbability",
}
_CHAMP_KEYS = {
    "championshipOdds",
    "n_simulations",
    "playoffSeeds",
    "byeSeeds",
    "playoffStructure",
    "rosStrengthAvailable",
}
_CHAMP_ROW_KEYS = {
    "ownerId",
    "displayName",
    "championshipOdds",
    "finalsOdds",
    "semifinalOdds",
    "playoffOdds",
    "expectedFinish",
    "contenderTier",
}
_ROS_ROW_KEYS = {
    "ownerId",
    "displayName",
    "playoffOdds",
    "playoffOddsCi",
    "championshipOdds",
    "championshipOddsCi",
    "byeOdds",
    "topSeedOdds",
    "missPlayoffsOdds",
    "expectedWins",
    "medianFinalSeed",
    "mostLikelySeed",
    "seedDistribution",
}


def test_every_surface_keeps_the_shape_its_consumers_read(engine):
    """``PlayoffOddsChart`` reads the public keys; ``ros-championship.jsx``
    and ``trade_deadline`` read the championship row keys; ``gameplan`` /
    ``roster_intel`` / the pick projector read the canonical row keys."""
    snap, owners = _league()
    _with_strength(engine, owners)
    public, ros, champ = _served(snap)
    assert _PUBLIC_KEYS <= set(public)
    for row in public["owners"]:
        assert _PUBLIC_OWNER_KEYS <= set(row)
        assert isinstance(row["playoffProbability"], float)
    assert _CHAMP_KEYS <= set(champ)
    for row in champ["championshipOdds"]:
        assert _CHAMP_ROW_KEYS <= set(row)
        assert "unavailableFields" not in row
    for row in ros["playoffOdds"]:
        assert _ROS_ROW_KEYS <= set(row)
    assert champ["championshipOdds"] == sorted(
        champ["championshipOdds"], key=lambda r: -r["championshipOdds"]
    )


def test_a_canonical_refusal_reaches_every_surface_as_a_refusal(engine):
    """No ROS evidence and too few finished weeks: the engine refuses
    (``team_strength_unavailable``), and no surface turns that into 0%."""
    snap, _ = _league(finished_weeks=2)
    public, ros, champ = _served(snap)
    reason = playoff_sim.TEAM_STRENGTH_UNAVAILABLE
    assert ros["unsimulable"]["reason"] == reason
    assert champ["unsimulable"]["reason"] == reason and champ["championshipOdds"] == []
    assert champ["n_simulations"] == 0
    assert public["unsimulable"]["reason"] == reason and public["simulated"] is False
    assert public["numSims"] == 0
    assert all(o["playoffProbability"] is None for o in public["owners"])
    assert all(isinstance(o["currentWins"], int) for o in public["owners"])


def test_an_owner_the_forecast_does_not_cover_is_missing_not_zero(engine):
    snap, owners = _league()
    forecast = {
        "n_simulations": 5000,
        "playoffOdds": [{"ownerId": o, "playoffOdds": 0.5} for o in owners[1:]],
    }
    out = public_odds.compute_playoff_odds(snap, forecast=forecast)
    missing = next(o for o in out["owners"] if o["ownerId"] == owners[0])
    assert missing["playoffProbability"] is None
    assert missing["unavailableReason"] == "owner_absent_from_canonical_forecast"


def test_a_championship_field_the_forecast_lacks_is_missing_not_zero():
    out = championship.championship_from_forecast(
        {
            "n_simulations": 100,
            "playoffOdds": [{"ownerId": "a", "playoffOdds": 0.4, "championshipOdds": 0.1}],
        }
    )
    row = out["championshipOdds"][0]
    assert row["finalsOdds"] is None and row["expectedFinish"] is None
    assert set(row["unavailableFields"]) == {"finalsOdds", "semifinalOdds", "expectedFinish"}
    assert row["contenderTier"] == "Serious Contender"


# ── the canonical engine did not move ─────────────────────────────────

#: ``simulate_playoff_odds`` on ``_league()`` with ``_STRENGTH``, seed 20261007,
#: 3,000 simulations — computed by the engine as it stood on ``origin/main``
#: BEFORE C5-PLAY-01 (``37ccfbb68``).  Recording bracket depth draws nothing
#: from the RNG, so every published number must be byte-identical.
_PRE_CONSOLIDATION_PATH = REPO / "tests" / "fixtures" / "one_playoff_engine_pre_consolidation.json"


def test_the_canonical_engines_numbers_are_unchanged(engine):
    pinned = json.loads(_PRE_CONSOLIDATION_PATH.read_text(encoding="utf-8"))
    snap, owners = _league()
    _with_strength(engine, owners)
    out = playoff_sim.simulate_playoff_odds(snap, n_simulations=3000, rng=random.Random(20261007))
    got = {r["ownerId"]: {k: r[k] for k in pinned["fields"]} for r in out["playoffOdds"]}
    assert got == pinned["rows"]


def test_recording_the_bracket_draws_nothing_from_the_rng():
    dists = {
        f"t{i}": playoff_sim._TeamDist(owner_id=f"t{i}", mean=100 + 3 * i, sd=18.0, pf_to_date=0)
        for i in range(7)
    }
    seeded = list(dists)
    for seed in range(30):
        a, b = random.Random(seed), random.Random(seed)
        placements: dict = {}
        champ_a = playoff_sim._simulate_bracket(seeded, dists, 1, a)
        champ_b = playoff_sim._simulate_bracket(seeded, dists, 1, b, placements)
        assert champ_a == champ_b and a.getstate() == b.getstate()
        assert placements[champ_b] == {"field": 1, "place": 1}


@pytest.mark.parametrize(
    "teams,byes,places",
    [
        # The retired championship loop's placement convention, kept: the
        # final's loser is 2nd, BOTH semifinal losers 3rd, round-one losers
        # 5th.. in game order.
        (7, 1, [1, 2, 3, 3, 5, 6, 7]),
        (6, 2, [1, 2, 3, 3, 5, 6]),
        (4, 0, [1, 2, 3, 3]),
    ],
)
def test_bracket_placements_keep_the_published_convention(teams, byes, places):
    dists = {
        f"t{i}": playoff_sim._TeamDist(owner_id=f"t{i}", mean=100.0, sd=15.0, pf_to_date=0)
        for i in range(teams)
    }
    placements: dict = {}
    playoff_sim._simulate_bracket(list(dists), dists, byes, random.Random(3), placements)
    assert sorted(p["place"] for p in placements.values()) == places
    assert sum(1 for p in placements.values() if p["field"] <= 2) == 2
    assert sum(1 for p in placements.values() if p["field"] <= 4) == min(4, teams)


# ── structural: no surface may simulate on its own again ──────────────


@pytest.mark.parametrize("rel", ["src/public_league/playoff_odds.py", "src/ros/championship.py"])
def test_adapter_surfaces_draw_no_randomness_and_seed_no_standings(rel):
    """A second engine needs random draws or a standings order.  The two
    adapter surfaces may have neither — ``standings_from_sim`` is DEFINED in
    the public module (the engine imports it) but never called there."""
    tree = ast.parse((REPO / rel).read_text(encoding="utf-8"))
    offenders = []
    for fn in (n for n in tree.body if isinstance(n, ast.FunctionDef)):
        if fn.name == "standings_from_sim":
            continue
        for node in ast.walk(fn):
            if isinstance(node, ast.Call):
                name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
                if name in {
                    "standings_from_sim",
                    "gauss",
                    "choice",
                    "random",
                    "_simulate_bracket",
                    "_build_team_distributions",
                }:
                    offenders.append(f"{rel}:{node.lineno} {fn.name} calls {name}")
    assert not offenders, "a second playoff simulator is back:\n" + "\n".join(offenders)
