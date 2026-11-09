"""Study two, script half: the freeze, settlement, leakage and no-network guards.

No network, no live data.  Preregistration:
``docs/league-intelligence/TEAM_POINTS_STUDY2_PREREGISTRATION_2026-11-09.md``.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import team_points_calibration_eval as study
from src.ros_calibration import team_points as tp

_KICK = datetime(2026, 11, 13, 1, 15, tzinfo=timezone.utc)
_PATH = study.PREREGISTRATION_2
_TEXT = "before\n*Freeze line. x\nafter\n"


def _git(**over):
    answers = {
        "added": study.FREEZE_COMMIT_2,
        "touched": _PATH,
        "ancestor": "",
        "committed": "2026-11-09T16:59:33-05:00",
        "frozen": _TEXT,
    }
    answers.update(over)

    def run(*args):
        if args[0] == "log":
            return answers["added"]
        if args[0] == "show" and args[1] == "--name-only":
            return answers["touched"]
        if args[0] == "show" and args[1] == "-s":
            return answers["committed"]
        if args[0] == "show":
            return answers["frozen"]
        if args[0] == "merge-base":
            return answers["ancestor"]
        raise AssertionError(args)

    return run


def test_splits_are_frozen_and_never_reuse_study_one_weeks():
    assert study.HOLDOUT_2 == (10, 11, 12, 13, 14)
    assert study.FIT_ONLY_2 == tuple(range(1, 10))
    assert set(study.HOLDOUT_2).isdisjoint(study.HOLDOUT)
    assert set(study.HOLDOUT_2).isdisjoint(study.DEVELOPMENT)
    assert set(study.HOLDOUT_2).isdisjoint(study.FINAL_WEEKS)
    assert study.DRY_RUN_MAX_WEEK < min(study.HOLDOUT_2)
    assert len(study.HOLDOUT_2) == tp.STUDY2_REQUIRED_WEEKS


def test_freeze_ok_and_text_below_the_line_may_grow():
    receipt = study.verify_freeze_2(_KICK, git=_git(), current_text="before\n*Freeze line. x\nmore")
    assert receipt["freezeCommit"] == study.FREEZE_COMMIT_2
    # CRLF checkouts compare equal to the LF blob.
    study.verify_freeze_2(_KICK, git=_git(), current_text=_TEXT.replace("\n", "\r\n"))


@pytest.mark.parametrize(
    "over, text, match",
    [
        ({"added": "0" * 40}, _TEXT, "added by"),
        ({"touched": _PATH + "\nsrc/x.py"}, _TEXT, "touched more"),
        ({"ancestor": None}, _TEXT, "not an ancestor"),
        ({"committed": "2026-11-13T01:15:00+00:00"}, _TEXT, "not before"),
        ({"frozen": None}, _TEXT, "cannot be read"),
        ({}, "changed\n*Freeze line. x\n", "differs"),
    ],
)
def test_freeze_refuses(over, text, match):
    with pytest.raises(study.Refusal, match=match):
        study.verify_freeze_2(_KICK, git=_git(**over), current_text=text)


def test_settlement_is_seven_full_days_after_the_last_kickoff():
    last = datetime(2026, 12, 15, 1, 15, tzinfo=timezone.utc)
    kicks = {14: (last - timedelta(days=4), last)}
    at = last + timedelta(days=7)
    with pytest.raises(study.Refusal, match="not settled"):
        study.assert_holdout_settled(kicks, [14], at - timedelta(seconds=1))
    study.assert_holdout_settled(kicks, [14], at)


def test_a_body_cached_before_settlement_is_refused():
    last = datetime(2026, 12, 15, 1, 15, tzinfo=timezone.utc)
    kicks = {14: (last, last)}
    at = last + timedelta(days=7)
    matchups = f"{study.SLEEPER}/league/{study.LEAGUE_ID}/matchups/14"
    stats_url = f"{study.SLEEPER}/stats/nfl/regular/2026/14"
    late = {"cachedAtUtc": at.strftime("%Y-%m-%dT%H:%M:%SZ")}
    early = {"cachedAtUtc": (at - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")}
    study.assert_bodies_after_settlement({matchups: late, stats_url: late}, [14], kicks)
    with pytest.raises(study.Refusal, match="before it settled"):
        study.assert_bodies_after_settlement({matchups: early, stats_url: late}, [14], kicks)
    with pytest.raises(study.Refusal, match="no cache receipt"):
        study.assert_bodies_after_settlement({matchups: late}, [14], kicks)


def test_schedule_kickoffs_hand_values():
    games = [
        {
            "season": "2026",
            "game_type": "REG",
            "week": "10",
            "gameday": "2026-11-12",
            "gametime": "20:15",
        },
        {
            "season": "2026",
            "game_type": "REG",
            "week": "10",
            "gameday": "2026-11-16",
            "gametime": "20:15",
        },
        {
            "season": "2025",
            "game_type": "REG",
            "week": "10",
            "gameday": "2025-11-12",
            "gametime": "20:15",
        },
        {
            "season": "2026",
            "game_type": "POST",
            "week": "19",
            "gameday": "2027-01-09",
            "gametime": "16:30",
        },
    ]
    assert study.schedule_kickoffs(games) == {
        10: (
            # 20:15 ET in November is 01:15 UTC the next day.
            datetime(2026, 11, 13, 1, 15, tzinfo=timezone.utc),
            datetime(2026, 11, 17, 1, 15, tzinfo=timezone.utc),
        )
    }


def test_the_bye_calendar_reads_byes_and_never_injury_flags():
    games = []
    for week in range(10, 18):
        if week == 11:  # AAA is on bye; BBB has a game with a third team
            games.append(_game(week, "BBB", "CCC"))
        else:
            games.append(_game(week, "AAA", "BBB"))
    inputs = SimpleNamespace(
        settings={"playoff_week_start": 15, "playoff_teams": 7},
        games=games,
        directory={
            # Out with a stated injury: the flag must not make him unavailable.
            "p1": {"team": "AAA", "injury_status": "Out", "position": "WR"},
            "p2": {"team": "BBB", "injury_status": "IR", "position": "RB"},
        },
    )
    rosters = {"T01": {"starters": [{"playerId": "p1"}], "bench": [{"playerId": "p2"}]}}
    weeks, unavailable = study.bye_calendar(inputs, 10, rosters)
    assert weeks == list(range(10, 18))  # served form: origin through the championship week
    assert unavailable == {("p1", 11)}

    # The nflverse file spans every season.  A past season's game in the same week must not
    # erase this season's bye (found by the study-one dry run: every bye vanished).
    inputs.games = games + [{**_game(11, "AAA", "CCC"), "season": "2025"}]
    assert study.bye_calendar(inputs, 10, rosters)[1] == {("p1", 11)}


def _game(week, home, away):
    return {
        "season": "2026",
        "game_type": "REG",
        "week": str(week),
        "gameday": f"2026-11-{min(week, 28):02d}",
        "home_team": home,
        "away_team": away,
    }


def test_served_fingerprint_is_deterministic_and_sealed():
    assert study.served_equation_fingerprint() == study.served_equation_fingerprint()
    assert len(study.SERVED_EQUATION_FINGERPRINT) == 64
    int(study.SERVED_EQUATION_FINGERPRINT, 16)


def test_counted_once_and_affine_compositions_by_hand():
    # The arms use production's own composition; check the two equations by hand.
    rows = [
        {
            "ownerId": "T01",
            "teamRosStrength": 80.0,
            "startingLineupScore": 100.0,
            "benchDepthScore": 40.0,
        },
        {
            "ownerId": "T02",
            "teamRosStrength": 40.0,
            "startingLineupScore": 100.0,
            "benchDepthScore": 10.0,
        },
    ]
    asof = study.AsOf(10, Path("x"), "", [], rows, "test")
    presim = {"T01": (300.0, 30.0), "T02": (200.0, 20.0)}
    view = tp.RealizedView({}, 10)
    once = study.production_distributions(asof, presim, view, ros_counted_once=True)
    assert once["T01"] == pytest.approx((300.0, 33.0))  # mean untouched, sd x 1.10
    assert once["T02"] == pytest.approx((200.0, 22.0))
    with_multiplier = study.production_distributions(asof, presim, view, ros_counted_once=False)
    assert with_multiplier["T01"] == pytest.approx((300.0 * 1.20, 30.0 * (1.10 + 0.15 * 0.40)))


# ── forecasts assembled point-in-time ────────────────────────────────────────────────


def _panel(teams, weeks, seed=11):
    rng = random.Random(seed)
    realized = {
        w: {t: 300.0 + 10.0 * i + rng.gauss(0, 40) for i, t in enumerate(teams)} for w in weeks
    }
    raw = {
        arm: {w: {t: (310.0 + i, 30.0 + i) for i, t in enumerate(teams)} for w in weeks}
        for arm in ("I", "CO", "AF", "AFCO", "I_noCal")
    }
    presim_means = {
        w: {t: 300.0 + 8.0 * i + rng.gauss(0, 5) for i, t in enumerate(teams)} for w in weeks
    }
    return realized, raw, presim_means


def test_week_k_forecast_never_depends_on_week_k_or_later():
    teams = [f"T{i:02d}" for i in range(1, 13)]
    weeks = list(range(1, 15))
    realized, raw, presim_means = _panel(teams, weeks)
    k = 10
    first, _ = study.assemble_forecasts_2(k, realized, teams, raw, presim_means)
    changed = {w: dict(v) for w, v in realized.items()}
    for w in range(k, 15):
        changed[w] = {t: 1.0 for t in teams}
    later_raw = {
        arm: {w: dict(v) if w <= k else {t: (1.0, 1.0) for t in teams} for w, v in by_week.items()}
        for arm, by_week in raw.items()
    }
    later_presim = {w: (v if w <= k else {t: 1.0 for t in teams}) for w, v in presim_means.items()}
    second, _ = study.assemble_forecasts_2(k, changed, teams, later_raw, later_presim)
    for arm in first:
        for team in teams:
            if first[arm][team] is None:
                assert second[arm][team] is None
            else:
                assert second[arm][team] == pytest.approx(first[arm][team]), (arm, team)


def test_only_the_fitted_arms_take_the_dispersion_repair():
    teams = [f"T{i:02d}" for i in range(1, 13)]
    weeks = list(range(1, 15))
    realized, raw, presim_means = _panel(teams, weeks)
    k = 10
    forecasts, meta = study.assemble_forecasts_2(k, realized, teams, raw, presim_means)
    # Hand: mean z² over weeks 3..9, per arm (raw is the same for every arm here).
    total, n = 0.0, 0
    for j in range(3, k):
        for t in teams:
            mu, sd = raw["AFCO"][j][t]
            total += ((realized[j][t] - mu) / sd) ** 2
            n += 1
    scale = (total / n) ** 0.5
    assert n == 84
    assert meta["dispersionScale"]["AFCO"] == pytest.approx(scale, abs=1e-5)
    for team in teams:
        mu, sd = raw["AFCO"][k][team]
        assert forecasts["AFCO"][team] == pytest.approx((mu, sd * scale))
        assert forecasts["AF"][team] == pytest.approx((mu, sd * scale))
        assert forecasts["CO"][team] == raw["CO"][k][team]
        assert forecasts["I"][team] == raw["I"][k][team]


def test_too_few_dispersion_rows_is_no_forecast_not_a_default():
    teams = ["T01", "T02"]
    realized = {w: {"T01": 300.0, "T02": 280.0} for w in range(1, 5)}
    raw = {
        arm: {w: {"T01": (290.0, 30.0), "T02": (285.0, 25.0)} for w in range(1, 5)}
        for arm in ("I", "CO", "AF", "AFCO", "I_noCal")
    }
    presim_means = {w: {"T01": 300.0, "T02": 280.0} for w in range(1, 5)}
    forecasts, meta = study.assemble_forecasts_2(4, realized, teams, raw, presim_means)
    assert meta["dispersionScale"]["AFCO"] is None
    assert forecasts["AFCO"] == {"T01": None, "T02": None}


# ── scoring and the decision, end to end on synthetic weeks ─────────────────────────


def _synthetic_weeks(afco_is_incumbent=False):
    teams = [f"T{i:02d}" for i in range(1, 13)]
    pairs = [
        ("T01", "T02"),
        ("T03", "T04"),
        ("T05", "T06"),
        ("T07", "T08"),
        ("T09", "T10"),
        ("T11", "T12"),
    ]
    rng = random.Random(20261109)
    weeks = {}
    for week in study.HOLDOUT_2:
        centre = {t: 320.0 + 9.0 * (i - 5.5) for i, t in enumerate(teams)}
        realized = {t: centre[t] + rng.gauss(0, 30) for t in teams}
        good = {t: (centre[t], 30.0) for t in teams}
        forecasts = {arm: dict(good) for arm in study.ARMS_2}
        forecasts["I"] = {t: (centre[t] + 1.8 * (centre[t] - 320.0) + 56.0, 26.0) for t in teams}
        forecasts["CO"] = {t: (centre[t] + 45.0, 30.0) for t in teams}
        if afco_is_incumbent:
            forecasts["AFCO"] = dict(forecasts["I"])
        weeks[week] = tp.WeekInputs(week=week, realized=realized, pairs=pairs, forecasts=forecasts)
    return weeks


@pytest.fixture
def fast(monkeypatch):
    monkeypatch.setattr(study, "MEDIAN_DRAWS", 400)
    monkeypatch.setattr(study, "BOOTSTRAP_B", 400)
    monkeypatch.setattr(study, "PLAYOFF_DRAWS_2", 400)


def test_a_clear_winner_is_recommended_end_to_end(fast):
    out = study.score_and_decide_2(_synthetic_weeks())
    assert out["sequence"]["AFCO"] == tp.REJECTED
    assert out["gates"]["AFCO"]["verdict"] == "PASSES_ALL_GATES", out["gates"]["AFCO"]
    assert out["decision"] == {"outcome": tp.OUTCOME_PROMOTE, "arm": "AFCO"}
    # CO is tested after AFCO and fails on level and spread, as it should.
    assert out["sequence"]["CO"] == tp.REJECTED
    assert "SG3" in out["gates"]["CO"]["failed"]
    assert out["inference"]["AFCO"]["signFlipP"] == pytest.approx(1 / 32)


def test_a_challenger_equal_to_the_incumbent_retains_and_stops_the_sequence(fast):
    out = study.score_and_decide_2(_synthetic_weeks(afco_is_incumbent=True))
    assert out["inference"]["AFCO"]["signFlipP"] == pytest.approx(1.0)
    assert out["sequence"] == {"AFCO": tp.NOT_REJECTED, "CO": tp.NOT_TESTED}
    assert out["decision"]["outcome"] == tp.OUTCOME_RETAIN


def test_a_void_reason_overrides_a_winner(fast):
    out = study.score_and_decide_2(_synthetic_weeks(), void_reasons=["served_equation_changed"])
    assert out["decision"]["outcome"] == tp.OUTCOME_VOID


def test_playoff_level_runs_on_the_recorded_rule(fast):
    weeks = _synthetic_weeks()
    realized = {w.week: w.realized for w in weeks.values()}
    pairs = {w.week: w.pairs for w in weeks.values()}
    out = study.playoff_level_2(weeks, realized, pairs, last_week=14)
    assert out["state"] == "scored"
    assert set(out["byOrigin"]) == {"10", "11", "12", "13", "14"}
    assert out["titleOdds"] == "INSUFFICIENT_BY_CONSTRUCTION"
    assert all(score["teams"] == 12 for arm in out["byOrigin"]["10"].values() for score in [arm])


# ── no network, no early look ────────────────────────────────────────────────────────


def test_default_is_no_network_and_refuses_without_a_cached_schedule(tmp_path, capsys):
    assert study.main(["study2", "--cache-dir", str(tmp_path)]) == 2
    assert "--network" in capsys.readouterr().err


def test_a_dry_run_cannot_read_a_holdout_week(tmp_path, capsys):
    assert study.main(["study2", "--cache-dir", str(tmp_path), "--dry-run-holdout", "8,9"]) == 2
    assert "dry run" in capsys.readouterr().err


def test_unsettled_holdout_refuses_before_any_sleeper_fetch(tmp_path, monkeypatch, capsys):
    rows = ["season,game_type,week,gameday,gametime"]
    rows += [f"2026,REG,{w},2099-12-14,20:15" for w in study.HOLDOUT_2]
    (tmp_path / "nflverse_games_20991214.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")

    def _forbidden(*_a, **_k):
        raise AssertionError("no Sleeper body may be read before the holdout settles")

    monkeypatch.setattr(study.v1.CachedFetcher, "get_json", _forbidden)
    assert study.main(["study2", "--cache-dir", str(tmp_path)]) == 2
    assert "not settled" in capsys.readouterr().err


def test_git_output_is_decoded_as_utf8(monkeypatch):
    # The preregistration is not ASCII, and the Windows default codec crashed on it.
    seen = {}

    def fake_run(cmd, **kwargs):
        seen.update(kwargs)
        return SimpleNamespace(stdout="abc
")

    monkeypatch.setattr(study.subprocess, "run", fake_run)
    assert study._git("rev-parse", "HEAD") == "abc"
    assert seen["encoding"] == "utf-8"


def test_capture_needs_explicit_network(capsys):
    assert study.main(["study2-capture"]) == 2
    assert "--network" in capsys.readouterr().err


def test_output_is_confined_to_the_study_two_evidence_dir(tmp_path):
    with pytest.raises(study.Refusal):
        study.assert_safe_output(tmp_path / "evaluation.json", study.OUT_DIR_2)
    with pytest.raises(study.Refusal):
        study.assert_safe_output(study.REPO / "data" / "ros" / "x.json", study.OUT_DIR_2)
    assert study.assert_safe_output(study.OUT_DIR_2 / "evaluation.json", study.OUT_DIR_2)


def test_appeared_fit_rows_keep_only_appeared_priced_players(monkeypatch):
    captured = {}

    def fake_classify(pid, row, meta, card, season, week):
        captured[pid] = meta
        status = study.v1.APPEARED if pid in ("p1", "p2") else "no_appearance"
        return SimpleNamespace(status=status, family="WR", points=12.5)

    monkeypatch.setattr(study.v1, "classify_player_week", fake_classify)
    inputs = SimpleNamespace(
        matchups={10: [{"players": ["p1", "p2", "p3"]}]},
        stats={10: {"p1": {}, "p2": {}, "p3": {}}},
        directory={
            "p1": {"position": "WR", "injury_status": "Out"},
            "p2": {"position": "WR"},
            "p3": {"position": "WR"},
        },
        card={},
    )
    asof = SimpleNamespace(
        rows=[
            {
                "fullRoster": [
                    {"playerId": "p1", "rosValue": 80.0},
                    {"playerId": "p2", "rosValue": 0.0},
                    {"playerId": "p3", "rosValue": 50.0},
                ]
            }
        ],
        snapshot_players=[
            {"position": "WR", "rosValue": 80.0},
            {"position": "WR", "rosValue": 50.0},
        ],
    )
    rows = study.appeared_fit_rows(inputs, 10, asof)
    assert [(r.ros_value, r.points) for r in rows] == [(80.0, 12.5)]  # p2 unpriced, p3 did not play
    assert "injury_status" not in captured["p1"]
