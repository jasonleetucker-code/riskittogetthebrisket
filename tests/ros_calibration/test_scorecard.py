"""MD-104 standing scorecard: deterministic synthetic fixtures, hand-computed oracles."""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.model_registry import game_day_calibration as gdc
from src.ros_calibration import scorecard as sc

REPO = Path(__file__).resolve().parents[2]
RULE_PATH = REPO / "config" / "forecast_scorecard" / "degradation_rule_v1.json"
T0 = datetime(2026, 9, 6, 17, tzinfo=timezone.utc)


def _rule_config(**over) -> dict:
    """The committed rule's shape with floors small enough for tiny fixtures."""
    cfg = json.loads(RULE_PATH.read_text(encoding="utf-8"))
    cfg["bootstrap"]["b"] = 50
    cfg["consecutiveEvaluations"] = 2
    for fam in cfg["families"].values():
        fam["minEligible"] = 1
        fam["minClusters"] = 1
        fam["minSeasons"] = 1
    cfg.update(over)
    return cfg


def _rule(**over) -> sc.Rule:
    return sc.parse_rule(_rule_config(**over))


def _at(days: float) -> datetime:
    return T0 + timedelta(days=days)


NOW = _at(400)  # far past every outcome and the 72h wait


# -- metrics: independent hand-computed oracles ------------------------------


def test_brier_and_bias_hand_computed() -> None:
    m = sc.binary_metrics([0.8, 0.3], [1, 0])
    assert m["brier"] == pytest.approx((0.2**2 + 0.3**2) / 2)  # 0.065
    assert m["bias"] == pytest.approx((0.8 + 0.3) / 2 - 0.5)
    assert m["logLoss"] == pytest.approx(-(math.log(0.8) + math.log(0.7)) / 2)
    assert m["calibrationSlope"] == pytest.approx(2.0)  # obs rises 1 over the p's 0.5
    assert m["intervalCoverage"]["state"] == "not_applicable"


def test_crps_hand_computed() -> None:
    # Normal(0, 1) at y = 0: CRPS = 2*phi(0) - 1/sqrt(pi) = 0.7978845608 - 0.5641895835
    m = sc.points_metrics([0.0], [0.0], [1.0])
    assert m["crps"] == pytest.approx(0.2336949773, abs=1e-9)
    assert m["intervalCoverage"]["coverage"] == 1.0
    # |y - mu| = 2 sd lies outside the 80% interval (1.2816 sd)
    out = sc.points_metrics([0.0], [2.0], [1.0])
    assert out["intervalCoverage"]["coverage"] == 0.0


def test_points_metrics_without_sd_say_unavailable_never_zero() -> None:
    m = sc.points_metrics([100.0, 110.0], [90.0, 120.0])
    assert m["mae"] == 10.0 and m["bias"] == 0.0
    assert m["crps"]["state"] == "unavailable"
    assert m["intervalCoverage"]["state"] == "unavailable"


def test_empty_metrics_are_unavailable() -> None:
    assert sc.binary_metrics([], [])["state"] == "unavailable"
    assert sc.points_metrics([], [])["state"] == "unavailable"


def test_committed_rule_declares_every_family_before_data() -> None:
    cfg = json.loads(RULE_PATH.read_text(encoding="utf-8"))
    rule = sc.parse_rule(cfg)
    assert rule.version == "forecast_degradation_v1"
    assert set(rule.families) == set(sc.FAMILIES)
    assert rule.consecutive == 3 and rule.wait == timedelta(hours=72)
    assert "REVIEW REQUEST ONLY" in cfg["effect"]
    assert rule.families["team_weekly_points"].metric == "mae"


def test_malformed_rule_raises_never_defaults() -> None:
    cfg = _rule_config()
    del cfg["families"]["game_day_win"]
    with pytest.raises(ValueError):
        sc.parse_rule(cfg)


# -- season families ----------------------------------------------------------

OWNERS = ["a", "b", "c", "d"]
SHA = "v1" * 8


def _record(
    computed_days: float,
    probs: list[float],
    *,
    kind: str = "playoff",
    version: str = SHA,
    cutoff: int = 5,
    season: str = "2026",
    inputs_sha: str | None = "in1",
    complete: bool = False,
    code: str = "code1",
) -> dict:
    field = "playoffOdds" if kind == "playoff" else "championshipOdds"
    forecast = {
        "computedAt": _at(computed_days).isoformat(),
        field: [{"ownerId": o, field: p} for o, p in zip(OWNERS, probs)],
        "playoffStructure": {"playoffTeams": 2},
        "regularSeasonProgress": {"weeksTotal": 14, "weeksFinal": cutoff, "complete": complete},
    }
    return {
        "kind": kind,
        "leagueKey": "lg",
        "computedAt": forecast["computedAt"],
        "season": season,
        "lastScoredWeek": cutoff,
        "model": {"simParamsSha256": version, "codeSha": code},
        "inputs": {"inputsSha256": inputs_sha, "leagueSnapshotSha256": "card1"},
        "forecast": forecast,
    }


def _outcome(**kw) -> sc.SeasonOutcome:
    base = dict(
        league_key="lg",
        season="2026",
        playoffs_decided_at=_at(50),
        playoff_owner_ids=frozenset({"a", "b"}),
        title_decided_at=_at(60),
        champion_owner_id="a",
    )
    base.update(kw)
    return sc.SeasonOutcome(**base)


def _season(records, outcomes, family=sc.FAMILY_PLAYOFF, now=NOW):
    return sc.season_family(family, records, outcomes, _rule(), now)


def test_season_playoff_hand_computed_with_identical_baseline_samples() -> None:
    res = _season([_record(10, [0.9, 0.6, 0.4, 0.1])], [_outcome()])
    (row,) = res["rows"]
    # y = a:1 b:1 c:0 d:0; Brier = (0.01 + 0.16 + 0.16 + 0.01) / 4
    assert row["served"]["brier"] == pytest.approx(0.085)
    # baseline: playoffTeams/teams = 2/4 = 0.5 on the same four samples
    assert row["baseline"]["name"] == "uniform_base_rate"
    assert row["baseline"]["brier"] == pytest.approx(0.25)
    assert row["baseline"]["n"] == row["served"]["n"] == row["eligibleSamples"] == 4
    assert row["delta"] == pytest.approx(0.085 - 0.25)
    assert row["verdict"] == sc.VERDICT_NOT_WORSE
    assert row["modelVersion"] == "sim:" + "v1" * 6
    assert row["codeShas"] == ["code1"] and row["cutoffs"] == [5]
    assert row["scoringCard"]["ids"] == ["card1"]
    assert row["exclusions"].get("model_version_mixed", 0) == 0


def test_season_title_uses_one_over_n_baseline() -> None:
    res = _season(
        [_record(10, [0.7, 0.2, 0.1, 0.0], kind="championship")],
        [_outcome()],
        family=sc.FAMILY_TITLE,
    )
    (row,) = res["rows"]
    assert row["baseline"]["meanPredicted"] == pytest.approx(0.25)
    assert row["served"]["brier"] == pytest.approx((0.09 + 0.04 + 0.01 + 0.0) / 4)


def test_no_outcome_yet_is_unavailable_with_reason_never_zero() -> None:
    res = _season([_record(10, [0.9, 0.6, 0.4, 0.1])], [])
    assert res["state"] == "unavailable" and res["reason"] == "no_outcome_yet"
    (row,) = res["rows"]
    assert row["state"] == "unavailable"
    assert row["eligibleSamples"] == 0 and row["forecastCount"] == 1
    assert row["served"]["state"] == "unavailable"
    assert "brier" not in row["served"]
    assert row["verdict"] == sc.VERDICT_INSUFFICIENT


def test_no_archived_forecasts_is_unavailable() -> None:
    res = _season([], [_outcome()])
    assert res["state"] == "unavailable" and res["reason"] == "no_archived_forecasts"


def test_undecided_outcome_fields_are_no_outcome() -> None:
    res = _season([_record(10, [0.9, 0.6, 0.4, 0.1])], [_outcome(playoffs_decided_at=None)])
    assert res["rows"][0]["exclusions"]["no_outcome_yet"] == 1


def test_look_ahead_forecast_at_or_after_the_outcome_is_excluded_and_counted() -> None:
    recs = [
        _record(10, [0.9, 0.6, 0.4, 0.1], cutoff=5),
        _record(50, [1.0, 1.0, 0.0, 0.0], cutoff=6),  # exactly at decided_at: excluded
        _record(51, [1.0, 1.0, 0.0, 0.0], cutoff=7),  # after: excluded
    ]
    (row,) = _season(recs, [_outcome()])["rows"]
    assert row["exclusions"]["forecast_after_outcome"] == 2
    assert row["eligibleForecasts"] == 1 and row["cutoffs"] == [5]
    assert row["served"]["brier"] == pytest.approx(
        0.085
    )  # the leaked perfect forecasts did not score


def test_stat_correction_window_holds_an_outcome_back() -> None:
    rec = [_record(10, [0.9, 0.6, 0.4, 0.1])]
    inside = _season(rec, [_outcome()], now=_at(50) + timedelta(hours=71.9))
    assert inside["rows"][0]["exclusions"]["stat_correction_window_open"] == 1
    assert inside["rows"][0]["eligibleSamples"] == 0
    exactly = _season(rec, [_outcome()], now=_at(50) + timedelta(hours=72))
    assert exactly["rows"][0]["eligibleSamples"] == 4


def test_mixed_model_versions_are_kept_apart_and_served_is_the_latest() -> None:
    old = _record(10, [0.9, 0.6, 0.4, 0.1], version="aa" * 8, cutoff=3)
    new = _record(20, [0.5, 0.5, 0.5, 0.5], version="bb" * 8, cutoff=4)
    rows = {r["modelVersion"]: r for r in _season([old, new], [_outcome()])["rows"]}
    a, b = "sim:" + "aa" * 6, "sim:" + "bb" * 6
    assert set(rows) == {a, b}
    assert rows[a]["served"]["brier"] == pytest.approx(0.085)
    assert rows[b]["served"]["brier"] == pytest.approx(0.25)
    assert rows[a]["isServedModel"] is False
    assert rows[b]["isServedModel"] is True
    assert rows[b]["exclusions"]["model_version_mixed"] == 1
    assert rows[a]["eligibleSamples"] == 4  # never pooled


def test_missing_identity_and_input_hash_are_excluded_by_name() -> None:
    no_hash = _record(10, [0.9, 0.6, 0.4, 0.1], inputs_sha=None)
    no_ident = _record(11, [0.9, 0.6, 0.4, 0.1])
    no_ident["model"]["simParamsSha256"] = None
    res = _season([no_hash, no_ident], [_outcome()])
    reasons: dict[str, int] = {}
    for r in res["rows"]:
        for k, v in r["exclusions"].items():
            reasons[k] = reasons.get(k, 0) + v
    assert reasons["missing_input_hash"] == 1 and reasons["model_identity_missing"] == 1
    assert res["state"] == "unavailable"


def test_later_forecast_supersedes_within_a_cutoff_and_complete_season_is_excluded() -> None:
    recs = [
        _record(10, [0.9, 0.6, 0.4, 0.1], cutoff=5),
        _record(12, [0.8, 0.7, 0.3, 0.2], cutoff=5),
        _record(14, [1.0, 1.0, 0.0, 0.0], cutoff=14, complete=True),
    ]
    (row,) = _season(recs, [_outcome()])["rows"]
    assert row["exclusions"]["superseded_same_cutoff"] == 1
    assert row["exclusions"]["outcome_already_determined"] == 1
    assert row["served"]["brier"] == pytest.approx((0.04 + 0.09 + 0.09 + 0.04) / 4)


# -- Game Day families --------------------------------------------------------

R = ["1", "2", "3", "4"]  # pairs (1,2) and (3,4)
V = "game-day-sim-v4"
WIN = {"1": 80.0, "2": 20.0, "3": 30.0, "4": 70.0}


def _gd_t(week: int, hours: float) -> datetime:
    return T0 + timedelta(days=7 * (week - 1), hours=hours)


def _gd_row(week, gid, hours, mode, mus, win=None, version=V):
    return {
        "generationId": gid,
        "inputsFetchedAt": _gd_t(week, hours).isoformat(),
        "mode": mode,
        "modelVersion": version,
        "medianRace": None,
        "outcomes": {
            rid: {
                "winMatchupPct": (win or {}).get(rid, 50.0),
                "beatMedianPct": 50.0,
                "expectedFinalBestBall": mus[rid],
                "actualScore": None,
                "pointsBanked": 0.0 if mode != "pregame" else None,
                "scoreNow": None,
            }
            for rid in R
        },
    }


def _gd_week(week, scores, mus, *, win=None, extra=(), final_hours=30):
    opp = {"1": "2", "2": "1", "3": "4", "4": "3"}
    ordered = sorted(scores.values())
    med = (ordered[1] + ordered[2]) / 2
    teams = [
        {"rosterId": r, "finalResult": "BEAT" if s > med else "TIE" if s == med else "MISS"}
        for r, s in scores.items()
    ]
    gen = {
        "generationId": f"w{week}-final",
        "leagueKey": "lg",
        "season": 2026,
        "week": week,
        "inputsFetchedAt": _gd_t(week, final_hours).isoformat(),
        "modelVersion": V,
        "resolved": {"mode": "final", "opponents": opp, "hostScores": dict(scores)},
        "render": {"medianRace": {"state": "final", "teams": teams}},
    }
    rows = [
        _gd_row(week, f"w{week}-pre", -1, "pregame", mus, win=win),
        _gd_row(week, f"w{week}-final", final_hours, "final", mus),
        *extra,
    ]
    return gdc.LeagueWeekEvidence("lg", 2026, week, rows, gen)


def _scores(w):
    return {"1": 100.0 + w, "2": 90.0, "3": 80.0, "4": 95.0}


def _gd(result, now=NOW):
    return sc._gd_rows(result, gdc.TARGET_WIN, sc.FAMILY_GD_WIN, _rule(), now)


def test_game_day_win_brier_hand_computed_and_coin_flip_baseline() -> None:
    # w1: 1 beats 2 (101 > 90), 4 beats 3 (95 > 80). Pregame p(win): roster 1 .8, roster 3 .3.
    ev = _gd_week(1, _scores(1), dict.fromkeys(R, 100.0), win=WIN)
    (row,) = [r for r in _gd(gdc.evaluate([ev]))["rows"] if r["ruleBasis"]]
    # events (1v2: p=.8, y=1) and (3v4: p=.3, y=0): Brier = (0.04 + 0.09) / 2
    assert row["served"]["brier"] == pytest.approx(0.065)
    assert row["baseline"]["name"] == "coin_flip_0.5"
    assert row["baseline"]["brier"] == pytest.approx(0.25)
    assert row["eligibleSamples"] == 2 and row["cutoff"] == "pregame"


def test_game_day_look_ahead_rows_are_excluded_and_counted() -> None:
    mus = dict.fromkeys(R, 100.0)
    sure = {"1": 100.0, "2": 0.0, "3": 0.0, "4": 100.0}
    leak_final = _gd_row(1, "leak-final", 31, "final", mus, win=sure)
    leak_live = _gd_row(1, "leak-live", 31, "live", mus, win=sure)
    ev = _gd_week(1, _scores(1), mus, win=WIN, extra=[leak_final, leak_live])
    (row,) = [r for r in _gd(gdc.evaluate([ev]))["rows"] if r["ruleBasis"]]
    assert row["exclusions"]["post_outcome_final_mode"] >= 1
    assert row["exclusions"]["at_or_after_outcome"] >= 1
    assert row["served"]["brier"] == pytest.approx(0.065)  # the leaked certainty did not score


def test_game_day_stat_correction_wait_applies() -> None:
    ev = _gd_week(1, _scores(1), dict.fromkeys(R, 100.0), win=WIN)
    soon = _gd_t(1, 30) + timedelta(hours=10)
    (row,) = [r for r in _gd(gdc.evaluate([ev]), soon)["rows"] if r["ruleBasis"]]
    assert row["eligibleSamples"] == 0 and row["state"] == "unavailable"
    assert row["exclusions"]["stat_correction_window_open"] == 2


def test_game_day_without_final_outcome_is_unavailable() -> None:
    mus = dict.fromkeys(R, 100.0)
    ev = gdc.LeagueWeekEvidence("lg", 2026, 1, [_gd_row(1, "w1-pre", -1, "pregame", mus)], None)
    res = _gd(gdc.evaluate([ev]))
    assert res["state"] == "unavailable" and res["reason"] == "no_outcome_yet"
    assert _gd(gdc.evaluate([]))["reason"] == "no_game_day_evidence"


def test_game_day_model_versions_stay_apart() -> None:
    mus = dict.fromkeys(R, 100.0)
    ev1 = _gd_week(1, _scores(1), mus, win=WIN)
    flat = dict.fromkeys(R, 50.0)
    other = _gd_row(2, "w2-pre2", -0.5, "pregame", mus, win=flat, version="game-day-sim-v5")
    ev2 = _gd_week(2, _scores(2), mus, win=flat, extra=[other])
    res = _gd(gdc.evaluate([ev1, ev2]))
    assert {r["modelVersion"] for r in res["rows"]} == {V, "game-day-sim-v5"}
    served = [r for r in res["rows"] if r["isServedModel"] and r["ruleBasis"]]
    assert len(served) == 1 and served[0]["modelVersion"] == "game-day-sim-v5"


# -- team weekly points -------------------------------------------------------


def test_points_family_trailing_mean_baseline_on_identical_samples() -> None:
    mus = {"1": 105.0, "2": 90.0, "3": 85.0, "4": 95.0}
    weeks = [_gd_week(w, _scores(w), mus) for w in (1, 2, 3)]
    (row,) = sc.points_family(weeks, _rule(), NOW)["rows"]
    # Week 1 has no earlier week: dropped from BOTH arms.
    assert row["exclusions"]["baseline_unavailable"] == 4
    assert row["eligibleSamples"] == 8 and row["clusters"] == 2
    # week 2 served |mu - y|: 3, 0, 5, 0 -> 2.0; week 3 (y1 = 103): 2, 0, 5, 0 -> 1.75
    assert row["served"]["mae"] == pytest.approx((2.0 + 1.75) / 2)
    # baseline = trailing mean of earlier actuals: week 2 -> (101, 90, 80, 95) gives 0.25;
    # week 3 -> roster 1 mean(101, 102) = 101.5, so |101.5 - 103| = 1.5 -> 0.375
    assert row["baseline"]["mae"] == pytest.approx((0.25 + 0.375) / 2)
    assert row["baseline"]["name"] == "trailing_team_mean"
    assert row["delta"] == pytest.approx(1.875 - 0.3125)
    assert row["verdict"] == sc.VERDICT_WORSE  # delta >= 0.25 and both clusters worse
    assert row["served"]["crps"]["state"] == "unavailable"


def test_points_baseline_uses_only_outcomes_known_before_the_forecast() -> None:
    mus = dict.fromkeys(R, 100.0)
    ev1 = _gd_week(
        1, _scores(1), mus, final_hours=400
    )  # week 1 final lands AFTER week 2's forecast
    ev2 = _gd_week(2, _scores(2), mus)
    (row,) = sc.points_family([ev1, ev2], _rule(), _at(900))["rows"]
    assert row["exclusions"]["baseline_unavailable"] == 8  # nothing was known for week 2
    assert row["eligibleSamples"] == 0


def test_points_forecast_after_kickoff_is_excluded_and_counted() -> None:
    mus = {"1": 105.0, "2": 90.0, "3": 85.0, "4": 95.0}
    kickoff = {("lg", 2026, 2): _gd_t(2, -2)}  # week 2's pregame row (hours=-1) is after kickoff
    res = sc.points_family(
        [_gd_week(1, _scores(1), mus), _gd_week(2, _scores(2), mus)], _rule(), NOW, kickoff
    )
    (row,) = res["rows"]
    assert row["exclusions"]["forecast_after_kickoff"] == 1
    assert row["eligibleSamples"] == 0


def test_points_stat_correction_wait_and_no_evidence() -> None:
    mus = dict.fromkeys(R, 100.0)
    now = _gd_t(2, 30) + timedelta(hours=1)
    res = sc.points_family(
        [_gd_week(1, _scores(1), mus), _gd_week(2, _scores(2), mus)], _rule(), now
    )
    assert res["rows"][0]["exclusions"]["stat_correction_window_open"] == 4
    assert sc.points_family([], _rule(), NOW)["reason"] == "no_game_day_evidence"


# -- trigger: exactly at the declared threshold, never below ------------------


def _samples_with_delta():
    # served Brier values 0.01 and 0.64 -> mean 0.325; baseline 0.25; delta 0.075.
    # Ten identical clusters: the bootstrap interval collapses onto 0.075 (above zero).
    out = []
    for i in range(10):
        out.append(sc.Sample(f"c{i}", "2026", 0.9, 0.5, 1.0))
        out.append(sc.Sample(f"c{i}", "2026", 0.8, 0.5, 0.0))
    return out


def _noisy_samples():
    # Same pooled delta (0.075) but two clusters of opposite sign: the interval spans zero.
    return [sc.Sample("c1", "2026", 0.9, 0.5, 1.0), sc.Sample("c2", "2026", 0.8, 0.5, 0.0)]


def _fam(margin: float, floors=(1, 1, 1)) -> sc.FamilyRule:
    return sc.FamilyRule("season_playoff_odds", "brier", "uniform_base_rate", margin, *floors, None)


def test_verdict_fires_exactly_at_the_margin_and_not_below() -> None:
    rule = _rule()
    at = sc.evaluate_samples(_samples_with_delta(), _fam(0.075), rule)
    assert at["delta"] == pytest.approx(0.075)
    assert at["verdict"] == sc.VERDICT_WORSE
    assert (
        sc.evaluate_samples(_samples_with_delta(), _fam(0.0751), rule)["verdict"]
        == sc.VERDICT_NOT_WORSE
    )
    assert (
        sc.evaluate_samples(_samples_with_delta(), _fam(0.2), rule)["verdict"]
        == sc.VERDICT_NOT_WORSE
    )


def test_point_delta_clearing_the_margin_with_an_interval_spanning_zero_does_not_fire() -> None:
    res = sc.evaluate_samples(_noisy_samples(), _fam(0.05), _rule())
    assert res["delta"] == pytest.approx(0.075) and res["delta"] >= 0.05
    lo, hi = res["deltaCi95"]
    assert lo < 0 < hi
    assert res["verdict"] == sc.VERDICT_NOT_WORSE
    assert res["verdictGate"] == "point_delta_reaches_margin_but_interval_spans_zero"
    # the interval is what blocks it: with the requirement off the same data fires
    off = sc.evaluate_samples(_noisy_samples(), _fam(0.05), _rule(requireCiExcludesZero=False))
    assert off["verdict"] == sc.VERDICT_WORSE


def test_single_cluster_cannot_compute_an_interval_and_is_insufficient() -> None:
    one = [sc.Sample("c1", "2026", 0.9, 0.5, 1.0)]
    assert sc.evaluate_samples(one, _fam(0.0), _rule())["verdict"] == sc.VERDICT_INSUFFICIENT


def test_below_the_sample_floors_the_verdict_is_insufficient_evidence() -> None:
    res = sc.evaluate_samples(_samples_with_delta(), _fam(0.0, floors=(30, 20, 2)), _rule())
    assert res["verdict"] == sc.VERDICT_INSUFFICIENT
    assert len(res["shortfalls"]) == 3  # eligible, clusters and seasons


def _row(verdict, digest, *, served=True, basis=True, clusters=None):
    return {
        "clusterIds": clusters if clusters is not None else [digest],
        "leagueKey": "lg",
        "family": sc.FAMILY_GD_WIN,
        "target": "winMatchup",
        "modelVersion": "m1",
        "ruleBasis": basis,
        "isServedModel": served,
        "verdict": verdict,
        "sampleDigest": digest,
        "delta": 0.01,
        "eligibleSamples": 200,
        "served": {"brier": 0.26},
        "baseline": {"brier": 0.25},
    }


def test_streak_needs_consecutive_distinct_evaluations_and_resets() -> None:
    rule = _rule()  # consecutive = 2
    r1 = _row(sc.VERDICT_WORSE, "d1")
    reviews, streaks = sc.apply_trigger([r1], rule, None)
    assert reviews == [] and r1["streak"] == 1
    # identical data re-run: the streak does NOT advance
    r1b = _row(sc.VERDICT_WORSE, "d1")
    reviews, streaks_b = sc.apply_trigger([r1b], rule, streaks)
    assert reviews == [] and r1b["streak"] == 1
    # new samples, still worse: the second consecutive evaluation fires
    r2 = _row(sc.VERDICT_WORSE, "d2")
    reviews, streaks2 = sc.apply_trigger([r2], rule, streaks_b)
    assert len(reviews) == 1 and reviews[0]["ruleVersion"] == "forecast_degradation_v1"
    assert reviews[0]["category"].startswith("forecast_degradation:lg:game_day_win:")
    assert reviews[0]["category"].endswith(":forecast_degradation_v1")
    # a healthy evaluation resets
    r3 = _row(sc.VERDICT_NOT_WORSE, "d3")
    reviews, _ = sc.apply_trigger([r3], rule, streaks2)
    assert reviews == [] and r3["streak"] == 0


def test_a_streak_look_must_add_a_new_cluster() -> None:
    rule = _rule()
    first = _row(sc.VERDICT_WORSE, "d1", clusters=["w1", "w2"])
    _, st = sc.apply_trigger([first], rule, None)
    same = _row(sc.VERDICT_WORSE, "d2", clusters=["w1", "w2"])  # new digest, no new cluster
    reviews, st2 = sc.apply_trigger([same], rule, st)
    assert reviews == [] and same["streak"] == 1
    grown = _row(sc.VERDICT_WORSE, "d3", clusters=["w1", "w2", "w3"])
    reviews, _ = sc.apply_trigger([grown], rule, st2)
    assert grown["streak"] == 2 and len(reviews) == 1


def test_committed_rule_states_the_honesty_notes() -> None:
    cfg = json.loads(RULE_PATH.read_text(encoding="utf-8"))
    assert cfg["requireCiExcludesZero"] is True and cfg["streakRequiresNewCluster"] is True
    assert "NOT independent" in cfg["independenceNote"]
    assert (
        "FLOORS" in cfg["baselinesAreFloorsNote"]
        and "will NOT fire" in cfg["baselinesAreFloorsNote"]
    )


def test_only_the_served_model_on_the_rule_basis_can_trigger() -> None:
    rows = [_row(sc.VERDICT_WORSE, "d1", served=False), _row(sc.VERDICT_WORSE, "d1", basis=False)]
    prior = {"lg|game_day_win|winMatchup|m1|forecast_degradation_v1": {"streak": 5, "digest": "x"}}
    reviews, streaks = sc.apply_trigger(rows, _rule(), prior)
    assert reviews == [] and streaks == {}


def test_insufficient_evidence_never_advances_a_streak() -> None:
    prior = {"lg|game_day_win|winMatchup|m1|forecast_degradation_v1": {"streak": 1, "digest": "d0"}}
    r = _row(sc.VERDICT_INSUFFICIENT, "d1")
    reviews, _ = sc.apply_trigger([r], _rule(), prior)
    assert reviews == [] and r["streak"] == 0


# -- whole scorecard ----------------------------------------------------------


def test_build_scorecard_is_deterministic_and_all_unavailable_without_outcomes() -> None:
    kw = dict(
        rule=_rule(),
        now=NOW,
        forecast_records=[_record(10, [0.9, 0.6, 0.4, 0.1])],
        season_outcomes=[],
        game_day_evidence=[],
    )
    a = sc.build_scorecard(**kw)
    b = sc.build_scorecard(**kw)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    assert all(f["state"] == "unavailable" for f in a["families"].values())
    assert a["degradationReviews"] == []
    assert a["families"][sc.FAMILY_PLAYOFF]["reason"] == "no_outcome_yet"
    assert a["ruleVersion"] == "forecast_degradation_v1"


def test_end_to_end_game_day_rows_reach_the_scorecard() -> None:
    mus = {"1": 105.0, "2": 90.0, "3": 85.0, "4": 95.0}
    evidence = [_gd_week(1, _scores(1), mus, win=WIN), _gd_week(2, _scores(2), mus, win=WIN)]
    card = sc.build_scorecard(
        rule=_rule(), now=NOW, forecast_records=[], season_outcomes=[], game_day_evidence=evidence
    )
    win = card["families"][sc.FAMILY_GD_WIN]
    assert win["state"] == "scored"
    assert card["families"][sc.FAMILY_POINTS]["state"] == "scored"
    assert card["families"][sc.FAMILY_PLAYOFF]["reason"] == "no_archived_forecasts"


def test_season_outcome_from_json_round_trip() -> None:
    o = sc.season_outcome_from_json(
        {
            "leagueKey": "lg",
            "season": 2026,
            "playoffsDecidedAt": "2026-12-01T00:00:00Z",
            "playoffOwnerIds": ["a", "b"],
            "titleDecidedAt": None,
            "championOwnerId": None,
        }
    )
    assert o.season == "2026" and o.playoff_owner_ids == frozenset({"a", "b"})
    assert o.title_decided_at is None and o.champion_owner_id is None
