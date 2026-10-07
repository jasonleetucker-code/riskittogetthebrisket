"""AL-4a — Game Day calibration scorecard (report-only).

Synthetic league-weeks shaped exactly like ``src.ros.game_day_live``'s stored
evidence: ``generations.jsonl`` index rows (``_generation_index_row``) and the
latest ``generation.json`` once final (``resolved`` + ``render.medianRace``).
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

import pytest

from src.model_registry import game_day_calibration as gdc
from src.model_registry import receipt_store as rs
from src.model_registry.evaluation_receipt import VERDICT_INSUFFICIENT
from src.model_registry.learning_receipt import canonical_json

LEAGUE = "lg"
SEASON = 2026
V4 = "game-day-sim-v4"
V5 = "game-day-sim-v5"
ROSTERS = [str(i) for i in range(1, 13)]  # 6 matchups, 12 median events per week


def _t(week: int, hours: float) -> str:
    base = datetime(2026, 9, 6, 17, tzinfo=timezone.utc) + timedelta(days=7 * (week - 1))
    return (base + timedelta(hours=hours)).isoformat()


def _pairs() -> list[tuple[str, str]]:
    return [(ROSTERS[i], ROSTERS[i + 1]) for i in range(0, len(ROSTERS), 2)]


def _scores(week: int) -> dict[str, float]:
    rnd = random.Random(week)
    return {rid: round(80 + rnd.random() * 60, 2) for rid in ROSTERS}


def _row(
    week: int,
    gid: str,
    *,
    hours: float,
    mode: str,
    version: str = V4,
    win: dict[str, float | None] | None = None,
    median: dict[str, float | None] | None = None,
    banked: float = 0.0,
) -> dict:
    outcomes = {}
    for rid in ROSTERS:
        outcomes[rid] = {
            "winMatchupPct": (win or {}).get(rid, 55.0),
            "beatMedianPct": (median or {}).get(rid, 50.0),
            "expectedFinalBestBall": 100.0,
            "actualScore": None,
            "pointsBanked": banked if mode != "pregame" else None,
            "scoreNow": None,
        }
    return {
        "generationId": gid,
        "supersedes": None,
        "producer": "game_day_live_collector",
        "sequence": 0,
        "inputsFetchedAt": _t(week, hours),
        "computedAt": _t(week, hours),
        "inputFingerprint": f"fp-{gid}",
        "leagueObservationSeq": 1,
        "mode": mode,
        "modelVersion": version,
        "medianRace": None,
        "outcomes": outcomes,
    }


def _final_generation(week: int, *, hours: float = 30.0, scores=None, race_state="final") -> dict:
    scores = scores or _scores(week)
    opponents = {}
    for a, b in _pairs():
        opponents[a], opponents[b] = b, a
    ordered = sorted(s for s in scores.values() if s is not None)
    median = (ordered[len(ordered) // 2 - 1] + ordered[len(ordered) // 2]) / 2
    teams = [
        {
            "rosterId": rid,
            "finalResult": (
                None if s is None else "BEAT" if s > median else "TIE" if s == median else "MISS"
            ),
        }
        for rid, s in scores.items()
    ]
    return {
        "schemaVersion": 1,
        "generationId": f"w{week}-final",
        "leagueKey": LEAGUE,
        "season": SEASON,
        "week": week,
        "inputsFetchedAt": _t(week, hours),
        "modelVersion": V4,
        "resolved": {"mode": "final", "opponents": opponents, "hostScores": dict(scores)},
        "render": {"medianRace": {"state": race_state, "teams": teams}},
    }


def _week(
    week: int, *, version: str = V4, extra_rows=(), final=True, win=None
) -> gdc.LeagueWeekEvidence:
    rows = [
        _row(week, f"w{week}-pre", hours=-1, mode="pregame", version=version, win=win),
        _row(week, f"w{week}-live", hours=2, mode="live", version=version, banked=60.0, win=win),
        _row(week, f"w{week}-final", hours=30, mode="final", version=version),
        *extra_rows,
    ]
    return gdc.LeagueWeekEvidence(
        league_key=LEAGUE,
        season=SEASON,
        week=week,
        index_rows=rows,
        latest_generation=_final_generation(week) if final else None,
    )


def _ids(result) -> set[str]:
    return {s.generation_id for s in result.scored}


# ── temporal guard ───────────────────────────────────────────────────────────


def test_a_prediction_fetched_after_the_outcome_is_known_is_excluded():
    leaky = _row(1, "w1-leak", hours=31, mode="live", banked=99.0)  # after the first final
    result = gdc.evaluate([_week(1, extra_rows=[leaky])])
    assert "w1-leak" not in _ids(result)
    assert "w1-final" not in _ids(result)  # a final-mode generation is never a prediction
    week = result.summary["leagues"][LEAGUE]["weeks"][0]
    assert week["predictionExclusions"]["at_or_after_outcome"] == 1
    assert week["predictionExclusions"]["post_outcome_final_mode"] == 1
    assert {"w1-pre", "w1-live"} <= _ids(result)


def test_outcome_known_at_is_the_first_final_generation_not_the_latest():
    # A stat-correction generation later supersedes the final; a live row between the
    # first final and the correction is still AFTER the outcome was known.
    between = _row(1, "w1-between", hours=31, mode="live", banked=99.0)
    ev = _week(1, extra_rows=[between])
    ev = gdc.LeagueWeekEvidence(
        league_key=ev.league_key,
        season=ev.season,
        week=ev.week,
        index_rows=ev.index_rows,
        latest_generation=_final_generation(1, hours=60),
    )
    result = gdc.evaluate([ev])
    assert "w1-between" not in _ids(result)
    outcome = result.summary["leagues"][LEAGUE]["weeks"][0]["outcome"]
    assert outcome["knownAt"] == _t(1, 30)
    assert outcome["revisionAt"] == _t(1, 60)


def test_an_unprovable_instant_is_excluded_not_assumed():
    bad = _row(1, "w1-dateonly", hours=0, mode="pregame")
    bad["inputsFetchedAt"] = "2026-09-06"
    result = gdc.evaluate([_week(1, extra_rows=[bad])])
    assert "w1-dateonly" not in _ids(result)
    assert (
        result.summary["leagues"][LEAGUE]["weeks"][0]["predictionExclusions"]["unproven_instant"]
        == 1
    )


# ── missing is never imputed ─────────────────────────────────────────────────


def test_a_withheld_probability_is_missing_never_scored_as_half_or_zero():
    withheld = {rid: None for rid in ROSTERS}
    result = gdc.evaluate([_week(1, win=withheld)])
    wins = [s for s in result.scored if s.target == gdc.TARGET_WIN]
    assert wins == []
    week = result.summary["leagues"][LEAGUE]["weeks"][0]
    assert week["predictionsMissingPerGenerationEvent"]["winMatchup:withheld_or_absent"] == 12
    cohort = next(
        c
        for c in result.summary["leagues"][LEAGUE]["cohorts"]
        if c["target"] == gdc.TARGET_WIN and c["state"] == "all_states_pooled"
    )
    assert cohort["n"] == 0
    assert cohort["missingCount"] == cohort["outcomeEvents"] == 6
    assert cohort["metrics"] is None


def test_a_week_without_a_final_generation_has_no_outcome_and_scores_nothing():
    result = gdc.evaluate([_week(1, final=False)])
    assert result.scored == []
    week = result.summary["leagues"][LEAGUE]["weeks"][0]
    assert week["outcome"] == {"state": "unavailable", "reason": "no_generation"}


def test_a_live_latest_generation_is_not_an_outcome():
    ev = _week(1)
    live = dict(_final_generation(1))
    live["resolved"] = {**live["resolved"], "mode": "live"}
    ev = gdc.LeagueWeekEvidence(LEAGUE, SEASON, 1, ev.index_rows, live)
    result = gdc.evaluate([ev])
    assert result.scored == []
    assert result.summary["leagues"][LEAGUE]["weeks"][0]["outcome"]["reason"] == (
        "latest_generation_not_final:live"
    )


def test_a_missing_host_score_drops_only_that_matchup():
    scores = _scores(1)
    scores["1"] = None
    ev = _week(1)
    ev = gdc.LeagueWeekEvidence(
        LEAGUE, SEASON, 1, ev.index_rows, _final_generation(1, scores=scores)
    )
    result = gdc.evaluate([ev])
    events = {s.event for s in result.scored if s.target == gdc.TARGET_WIN}
    assert not any(e.endswith("|1v2") for e in events)
    assert len(events) == 5


def test_a_tied_final_is_not_a_binary_event():
    scores = _scores(1)
    scores["2"] = scores["1"]
    ev = _week(1)
    ev = gdc.LeagueWeekEvidence(
        LEAGUE, SEASON, 1, ev.index_rows, _final_generation(1, scores=scores)
    )
    result = gdc.evaluate([ev])
    assert not any(s.event.endswith("|1v2") for s in result.scored)
    outcome = result.summary["leagues"][LEAGUE]["weeks"][0]["outcome"]
    assert outcome["notes"]["matchup_tie"] == 1


def test_median_outcomes_need_a_final_median_race():
    ev = _week(1)
    gen = _final_generation(1, race_state="not_applicable")
    result = gdc.evaluate([gdc.LeagueWeekEvidence(LEAGUE, SEASON, 1, ev.index_rows, gen)])
    assert not [s for s in result.scored if s.target == gdc.TARGET_MEDIAN]
    assert [s for s in result.scored if s.target == gdc.TARGET_WIN]


# ── duplicates and model versions ────────────────────────────────────────────


def test_duplicate_generation_rows_are_deduped_and_conflicts_counted():
    ev = _week(1)
    dup = dict(ev.index_rows[0])
    conflict = dict(ev.index_rows[1])
    conflict["mode"] = "pregame"
    rows = [*ev.index_rows, dup, conflict]
    result = gdc.evaluate([gdc.LeagueWeekEvidence(LEAGUE, SEASON, 1, rows, ev.latest_generation)])
    once = gdc.evaluate([ev])
    assert [(s.event, s.state) for s in result.scored] == [(s.event, s.state) for s in once.scored]
    census = result.summary["leagues"][LEAGUE]["weeks"][0]["indexCensus"]
    assert census == {"conflict": 1, "duplicate": 1}


def test_model_versions_are_separate_cohorts_never_pooled():
    weeks = [_week(1, version=V4), _week(2, version=V5)]
    result = gdc.evaluate(weeks)
    versions = {s.model_version for s in result.scored}
    assert versions == {V4, V5}
    receipts = gdc.receipts(result, code_sha="abc123")
    ids = {r.model_version_id for r in receipts}
    assert ids == {f"mv:game_day_sim:{V4}", f"mv:game_day_sim:{V5}"}
    for r in receipts:
        version = r.model_version_id.split(":")[-1]
        assert version in r.native_id
    # V5 published nothing in week 1, so week 1 is not in its coverage denominator.
    v5 = next(
        c
        for c in result.summary["leagues"][LEAGUE]["cohorts"]
        if c["modelVersion"] == V5 and c["target"] == gdc.TARGET_WIN and c["state"] == "pregame"
    )
    assert v5["outcomeEvents"] == 6


def test_a_row_without_a_model_version_is_excluded():
    row = _row(1, "w1-anon", hours=-2, mode="pregame")
    row["modelVersion"] = None
    result = gdc.evaluate([_week(1, extra_rows=[row])])
    assert "w1-anon" not in _ids(result)


def test_the_last_as_known_generation_in_a_state_is_scored():
    early = _row(1, "w1-pre-early", hours=-20, mode="pregame", win={"1": 10.0})
    result = gdc.evaluate([_week(1, extra_rows=[early])])
    pregame = [s for s in result.scored if s.state == "pregame" and s.target == gdc.TARGET_WIN]
    assert {s.generation_id for s in pregame} == {"w1-pre"}


def test_live_rows_are_bucketed_by_banked_share():
    rows = [
        _row(1, "q1", hours=1, mode="live", banked=10.0),
        _row(1, "q3", hours=3, mode="live", banked=60.0),
        _row(1, "q4", hours=4, mode="live", banked=90.0),
    ]
    assert [gdc.game_state(r) for r in rows] == ["live_q1", "live_q3", "live_q4"]
    unknown = _row(1, "u", hours=1, mode="live", banked=10.0)
    unknown["outcomes"]["1"]["pointsBanked"] = None
    assert gdc.game_state(unknown) == gdc.STATE_LIVE_UNKNOWN


# ── small samples, metrics, receipts ─────────────────────────────────────────


def test_a_small_sample_is_flagged_insufficient_with_no_metric():
    result = gdc.evaluate([_week(1)])
    for cohort in result.summary["leagues"][LEAGUE]["cohorts"]:
        assert cohort["status"] == "insufficient_sample"
        assert cohort["metrics"] is None and cohort["reliability"] is None
    for receipt in gdc.receipts(result, code_sha="abc123"):
        body = receipt.body
        assert body["verdict"] == VERDICT_INSUFFICIENT
        assert body["overallResult"]["metrics"] == {}
        assert body["promotes"] is False


def test_a_sufficient_sample_reports_brier_and_reliability():
    weeks = [_week(w, win={rid: 80.0 for rid in ROSTERS}) for w in range(1, 7)]  # 36 matchups
    result = gdc.evaluate(weeks)
    cohort = next(
        c
        for c in result.summary["leagues"][LEAGUE]["cohorts"]
        if c["target"] == gdc.TARGET_WIN and c["state"] == "pregame"
    )
    assert cohort["status"] == "ok" and cohort["events"] == 36
    wins = [s for s in result.scored if s.target == gdc.TARGET_WIN and s.state == "pregame"]
    expected = sum((0.8 - s.y) ** 2 for s in wins) / len(wins)
    assert cohort["metrics"]["brier"] == pytest.approx(expected, abs=1e-6)
    assert cohort["coverage"] == 1.0
    bins = {b["bin"]: b for b in cohort["reliability"]}
    assert bins["0.8-0.9"]["n"] == 36 and bins["0.8-0.9"]["meanPredicted"] == 0.8
    assert bins["0.1-0.2"]["status"] == "insufficient_sample"


def test_replay_is_byte_identical_and_order_independent():
    weeks = [_week(w) for w in range(1, 7)]
    a = gdc.evaluate(weeks)
    b = gdc.evaluate(list(reversed(weeks)))
    assert canonical_json(a.summary) == canonical_json(b.summary)
    ra = [r.content_hash() for r in gdc.receipts(a, code_sha="abc123")]
    rb = [r.content_hash() for r in gdc.receipts(b, code_sha="abc123")]
    assert ra == rb


def test_receipts_round_trip_through_the_store_idempotently(tmp_path):
    result = gdc.evaluate([_week(w) for w in range(1, 7)])
    receipts = gdc.receipts(result, code_sha="abc123")
    store = tmp_path / "receipts.sqlite"
    first = rs.append_receipts(receipts, path=store)
    again = rs.append_receipts(
        gdc.receipts(gdc.evaluate([_week(w) for w in range(1, 7)]), code_sha="abc123"), path=store
    )
    assert first["written"] == len(receipts) and not first["rejected"]
    assert again["written"] == 0 and again["duplicates"] == len(receipts)
    assert not again["contentConflicts"]
    for r in receipts:
        assert r.kind == "EVALUATION"
        assert r.body["role"] == "champion" and r.body["promotes"] is False


def test_a_code_revision_is_required():
    with pytest.raises(Exception, match="code revision"):
        gdc.receipts(gdc.evaluate([_week(1)]), code_sha="")


# ── the script reads stored evidence through the Game Day owner ─────────────


def test_script_collects_league_weeks_through_the_owner_readers(tmp_path, monkeypatch, capsys):
    import json

    from scripts import game_day_calibration_scorecard as script
    from src.ros import game_day_live as gdl

    monkeypatch.setattr(gdl, "LIVE_ROOT", tmp_path)
    for w in range(1, 3):
        ev = _week(w)
        week_dir = tmp_path / LEAGUE / str(SEASON) / f"week_{w}"
        week_dir.mkdir(parents=True)
        (week_dir / "generations.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in ev.index_rows) + "{torn", encoding="utf-8"
        )
        gen = {**ev.latest_generation, "schemaVersion": gdl.GENERATION_SCHEMA_VERSION}
        (week_dir / "generation.json").write_text(json.dumps(gen), encoding="utf-8")
    (tmp_path / "_nfl" / str(SEASON)).mkdir(parents=True)  # not a league

    evidence = script.collect()
    assert [(e.league_key, e.week) for e in evidence] == [(LEAGUE, 1), (LEAGUE, 2)]
    assert gdc.evaluate(evidence).summary == gdc.evaluate([_week(1), _week(2)]).summary
    assert script.main(["--dry-run"]) == 0
    assert "scored-predictions=" in capsys.readouterr().out
