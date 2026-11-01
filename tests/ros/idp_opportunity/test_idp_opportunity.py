"""IDP opportunity shadow challengers: no leakage, scoring parity, missing != 0,
determinism, isolation.  Synthetic data only; no network."""

from __future__ import annotations

import ast
import copy
import json
from pathlib import Path

import pytest

from src.league_intel.scorer import score_stat_line
from src.ros.idp_opportunity import EVIDENCE_TYPE
from src.ros.idp_opportunity import sources as S
from src.ros.idp_opportunity.evaluate import bootstrap_delta_mae, metrics, population, run_season
from src.ros.idp_opportunity.leakage import LeakageError, SeasonData
from src.ros.idp_opportunity.model import (
    MODELS,
    PRIORS,
    Params,
    build_context,
    build_rows,
    effective_model,
    fast_points,
    project_points,
    project_stat_line,
)
from src.ros.idp_opportunity.positions import family_of, subgroup_of
from tests.ros.idp_opportunity._fixtures import CARD_SETTINGS, card, season

ROOT = Path(__file__).resolve().parents[3]
PKG = ROOT / "src" / "ros" / "idp_opportunity"


# ── no-leakage guard ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("week", [4, 5])
def test_view_refuses_target_week_and_later(week):
    view = season().view(4)
    for accessor in (view.stats_week, view.team_week, view.offense_week):
        with pytest.raises(LeakageError):
            accessor(week)
    assert view.weeks_before() == [1, 2, 3]


def test_view_cannot_be_widened():
    view = season().view(3)
    assert view.narrow(2).cutoff == 2
    with pytest.raises(LeakageError):
        view.narrow(4)


def test_features_are_invariant_to_target_and_future_weeks():
    data = season()
    c = card()
    base_view = data.view(4)
    base = build_rows(base_view, build_context(base_view, c), c, ["1", "2", "3", "5", "7"])
    poisoned_stats = copy.deepcopy(dict(data.stats))
    for w in (4, 5):
        for line in poisoned_stats[w].values():
            line.update({"def_snp": 1.0, "tm_def_snp": 99.0, "idp_tkl_solo": 50.0, "idp_sack": 9.0})
    poisoned = SeasonData(
        season=data.season,
        stats=poisoned_stats,
        team_of={w: v for w, v in data.team_of.items() if w < 4},
        offense={w: v for w, v in data.offense.items() if w < 4},
        schedule=data.schedule,
        injury_report=data.injury_report,
        positions=data.positions,
    )
    pv = poisoned.view(4)
    again = build_rows(pv, build_context(pv, c), c, ["1", "2", "3", "5", "7"])
    for m in MODELS:
        assert [project_points(r, m, PRIORS, c) for r in base] == [
            project_points(r, m, PRIORS, c) for r in again
        ]


def test_run_season_projection_does_not_see_its_outcome():
    data = season()
    c = card()
    preds, _ = run_season(data, c, [4])
    changed = copy.deepcopy(dict(data.stats))
    for line in changed[4].values():
        line["idp_tkl_solo"] = 40.0
    data2 = SeasonData(
        season=data.season,
        stats=changed,
        team_of=data.team_of,
        offense=data.offense,
        schedule=data.schedule,
        injury_report=data.injury_report,
        positions=data.positions,
    )
    preds2, _ = run_season(data2, c, [4])
    assert [p.projected for p in preds] == [p.projected for p in preds2]
    assert [p.actual for p in preds] != [p.actual for p in preds2]


# ── scoring parity with the canonical scorer ─────────────────────────────────


@pytest.mark.parametrize("model", MODELS)
def test_projection_is_scored_by_the_canonical_scorer(model):
    data = season()
    c = card()
    view = data.view(4)
    rows = build_rows(view, build_context(view, c), c, population(data, 4))
    assert rows
    params = Params(
        kappa_vol=50.0, kappa_splash=800.0, kappa_opp=200.0, alpha=0.75, beta={"S": 0.4, "CB": 0.3}
    )
    for r in rows:
        line = project_stat_line(r, model, params, c)
        canonical = score_stat_line(line, CARD_SETTINGS).total_points
        assert project_points(r, model, params, c) == canonical
        assert fast_points(r, model, params) == pytest.approx(canonical, abs=1e-9)


def test_target_is_the_canonical_score_of_the_full_line():
    c = card()
    line = {
        "idp_tkl_solo": 3,
        "idp_tkl_ast": 2,
        "idp_tkl_loss": 1,
        "idp_pass_def": 1,
        "rec": 1,
        "def_snp": 50,
    }
    assert c.points(line) == score_stat_line(line, CARD_SETTINGS).total_points
    # TFL and passes defended are scored at the card's own rates
    assert c.points(line) == pytest.approx(3 * 1.33 + 2 * 0.8 + 4.24 + 5.3 + 1.0)


# ── missing is never zero ────────────────────────────────────────────────────


def test_player_without_history_is_not_projected_as_zero():
    data = season()
    assert "9" not in population(data, 4)  # first played week 4: no champion, excluded
    assert "9" in population(data, 5)


def test_missing_team_snaps_falls_back_named_not_zero():
    data = season()
    stats = copy.deepcopy(dict(data.stats))
    for w in (1, 2, 3):
        stats[w]["1"]["tm_def_snp"] = None
    d2 = SeasonData(
        data.season,
        stats,
        data.team_of,
        data.offense,
        data.schedule,
        data.injury_report,
        data.positions,
    )
    c = card()
    v = d2.view(4)
    row = next(r for r in build_rows(v, build_context(v, c), c, ["1"]))
    assert row.exp_snaps is None
    assert "team_snaps_missing" in row.reasons
    assert effective_model(row, "M5") == "C0"
    assert project_points(row, "M5", PRIORS, c) == project_points(row, "C0", PRIORS, c) > 0


def test_unknown_subgroup_and_opponent_are_named():
    data = season()
    c = card()
    v = data.view(4)
    rows = {r.pid: r for r in build_rows(v, build_context(v, c), c, ["8"])}
    assert "subgroup_unknown" in rows["8"].reasons
    no_sched = SeasonData(
        data.season, data.stats, data.team_of, data.offense, {}, {}, data.positions
    )
    v2 = no_sched.view(4)
    r2 = build_rows(v2, build_context(v2, c), c, ["1"])[0]
    assert r2.opponent is None and "opponent_unknown" in r2.reasons and r2.factors == {}


def test_unfetchable_week_is_absent_not_zeros(tmp_path, monkeypatch):
    from src.league_comparison import sleeper_stats

    class _Resp:
        payload = None
        error = "http_error:500"
        http_status = 500

    monkeypatch.setattr(sleeper_stats, "fetch_week_stats_response", lambda s, w: _Resp())
    weeks, report = S.load_sleeper_weeks(2026, [1, 2], tmp_path)
    assert weeks == {}
    assert report["missing"] == {"1": "http_error:500", "2": "http_error:500"}


def test_prekickoff_census_counts_nothing_without_an_archive(tmp_path):
    out = S.count_prekickoff_snapshots(2026, [1, 2], {}, [tmp_path / "absent"])
    assert out["genuinePreKickoff"] == 0 and out["captures"] == 0


# ── determinism ──────────────────────────────────────────────────────────────


def test_run_is_deterministic():
    c = card()
    a = run_season(season(), c, [3, 4, 5])
    b = run_season(season(), c, [3, 4, 5])
    assert [(p.pid, p.week, p.model, p.projected, p.lo, p.hi) for p in a[0]] == [
        (p.pid, p.week, p.model, p.projected, p.lo, p.hi) for p in b[0]
    ]
    assert json.dumps(a[1], sort_keys=True) == json.dumps(b[1], sort_keys=True)
    rows = a[0]
    m5 = [p for p in rows if p.model == "M5"]
    c0 = [p for p in rows if p.model == "C0"]
    assert bootstrap_delta_mae(m5, c0, resamples=200) == bootstrap_delta_mae(m5, c0, resamples=200)
    assert metrics(m5, 3)["n"] == len(m5)


# ── positions ────────────────────────────────────────────────────────────────


def test_subgroup_rules():
    assert family_of("DE", ["DL"]) == "DL"
    assert family_of("WR", ["WR"]) is None
    assert subgroup_of("DL", "ED", "LB") == "EDGE"
    assert subgroup_of("LB", "", "OLB") == "LB"
    assert subgroup_of("DL", "", "OLB") == "EDGE"
    assert subgroup_of("DB", "", "", "FS") == "S"
    assert subgroup_of("DB", "", "", "", "DB") == "UNKNOWN"


# ── isolation: shadow only ───────────────────────────────────────────────────

_FORBIDDEN_PREFIXES = ("src.waivers.streaming", "server", "src.api.data_contract", "frontend")


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_package_imports_no_consumer_or_dynasty_owner():
    for path in sorted(PKG.glob("*.py")):
        for name in _imports(path):
            assert not name.startswith(_FORBIDDEN_PREFIXES), f"{path.name} imports {name}"


#: Research harnesses that may read the shadow FEATURE module (never the models).
_RESEARCH_IMPORTERS = {"src/waivers/streaming_backtest.py": {"src.ros.idp_opportunity.features"}}


def test_nothing_live_imports_the_package():
    offenders = []
    candidates = [ROOT / "server.py", *sorted((ROOT / "src").rglob("*.py"))]
    for path in candidates:
        if PKG in path.parents:
            continue
        rel = path.relative_to(ROOT).as_posix()
        allowed = _RESEARCH_IMPORTERS.get(rel, set())
        names = {n for n in _imports(path) if n.startswith("src.ros.idp_opportunity")}
        if names - allowed:
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


def test_evidence_type_is_weekly_only():
    assert EVIDENCE_TYPE == "weekly_opportunity"


# ── role-change feature (offered to the streaming research harness) ─────────


def test_role_change_reads_only_prior_weeks_and_names_missing():
    from src.ros.idp_opportunity.features import role_change

    data = season()
    rc = role_change(data.view(4), "1")
    assert rc.state == "ok" and rc.last_week == 3 and rc.baseline_weeks == 2
    assert rc.delta == pytest.approx(rc.last_share - rc.baseline_share)
    assert role_change(data.view(2), "1").state == "single_week"
    assert role_change(data.view(4), "9").state == "no_history"  # first plays week 4
    poisoned = copy.deepcopy(dict(data.stats))
    for line in poisoned[4].values():
        line["def_snp"] = 1.0
    d2 = SeasonData(
        data.season, poisoned, data.team_of, data.offense, data.schedule, {}, data.positions
    )
    assert role_change(d2.view(4), "1") == rc


# ── missing snaps / volumes stay missing (decision-path coercion gate) ───────


def test_played_requires_an_observed_positive_snap_count():
    from src.ros.idp_opportunity.model import opt_float, played

    assert played({"def_snp": 12}) is True
    assert played({"def_snp": 0}) is False
    assert played({"def_snp": None}) is False
    assert played({}) is False
    assert opt_float({"x": None}, "x") is None and opt_float({"x": "0"}, "x") == 0.0


def test_missing_offense_volume_is_excluded_not_zero():
    data = season()
    offense = copy.deepcopy(dict(data.offense))
    for w in offense:
        offense[w]["AAA"] = {"wr_targets": 20.0}  # dropbacks missing for AAA
    d2 = SeasonData(
        data.season, data.stats, data.team_of, offense, data.schedule, {}, data.positions
    )
    ctx = build_context(d2.view(4), card())
    assert ctx.off_games.get("AAA", 0) == 0 and ctx.off_games_wr["AAA"] == 3
    assert ctx.league["dropbacksPerGame"] == pytest.approx(sum(40.0 - w for w in (1, 2, 3)) / 3)


def test_league_rates_are_unavailable_without_observations():
    data = season()
    d2 = SeasonData(data.season, data.stats, {}, {}, data.schedule, {}, data.positions)
    c = card()
    v = d2.view(4)
    ctx = build_context(v, c)
    assert ctx.league["snapsPerGame"] is None and ctx.league["dropbacksPerGame"] is None
    assert build_rows(v, ctx, c, ["1"])[0].factors == {}
