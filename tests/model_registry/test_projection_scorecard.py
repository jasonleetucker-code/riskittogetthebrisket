"""AL-3b — projection scorecard (report-only).

WEEKLY fixtures are shaped exactly like ``pregame_projections.json.gz``
(``src.ros.game_day_live.build_pregame_projection_archive``) and Sleeper's weekly
stat dump; SEASON fixtures are BDVM ``ProjectionRecord`` snapshots plus the
``bdvm.actuals.weekly_points_from_rows`` output shape.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.bdvm.projections import ProjectionRecord
from src.model_registry import projection_scorecard as ps
from src.model_registry import receipt_store as rs
from src.model_registry.evaluation_receipt import VERDICT_INSUFFICIENT
from src.model_registry.learning_receipt import canonical_json

CARD = {"rec": 1.0, "rec_yd": 0.1, "rec_td": 6.0, "rush_yd": 0.1, "rush_td": 6.0}
KICK = datetime(2026, 10, 4, 17, tzinfo=timezone.utc)
SEASON = 2026
WEEK = 5


def _proj_row(pid: str, *, rec: float, rec_yd: float, week: int = WEEK) -> dict:
    return {
        "player_id": pid,
        "season": str(SEASON),
        "week": week,
        "season_type": "regular",
        "game_id": f"g{int(pid) % 4}",
        "company": "rotowire",
        "team": "KC",
        "opponent": "BUF",
        "player": {"fantasy_positions": ["WR"], "position": "WR"},
        "stats": {"rec": rec, "rec_yd": rec_yd},
    }


def _archive(players: dict[str, dict], *, week: int = WEEK, source="archive") -> ps.WeeklyArchive:
    return ps.WeeklyArchive(
        season=SEASON,
        week=week,
        payload={
            "kind": "pregame_weekly_projections",
            "players": players,
            "timingUnverified": {},
            "noPreKickoffObservation": [],
        },
        source_key=f"{source}-w{week}",
    )


def _entry(pid: str, *, observed: datetime, rec=5.0, rec_yd=60.0, week=WEEK) -> dict:
    return {
        "observedAt": observed.isoformat(),
        "kickoffAt": KICK.isoformat(),
        "fetchUrl": "u",
        "row": _proj_row(pid, rec=rec, rec_yd=rec_yd, week=week),
    }


def _players(n: int, *, observed: datetime | None = None) -> dict[str, dict]:
    observed = observed or KICK - timedelta(hours=2)
    return {
        str(100 + i): _entry(str(100 + i), observed=observed, rec=5.0 + i % 3) for i in range(n)
    }


#: Sleeper /state/nfl after week 5 finished (the host moved on to week 6).
HOST_AFTER = {"season": "2026", "week": WEEK + 1, "season_type": "regular"}
#: ... and DURING week 5 (Sunday afternoon, MNF still to play).
HOST_DURING = {"season": "2026", "week": WEEK, "season_type": "regular"}


def _realized(
    pids,
    *,
    fetched: datetime | None = None,
    week=WEEK,
    host=HOST_AFTER,
    source="sleeper",
    **override,
) -> ps.RealizedWeek:
    stats = {pid: {"rec": 4.0, "rec_yd": 55.0, "gp": 1.0} for pid in pids}
    stats.update(override)
    fetched = fetched or KICK + timedelta(days=4)
    return ps.RealizedWeek(
        season=SEASON,
        week=week,
        fetched_at=fetched,
        stats=stats,
        source_key=f"{source}-w{week}-{fetched.isoformat()}",
        host_state=host,
        host_state_observed_at=fetched - timedelta(minutes=1),
    )


def _weekly(archives, realized, **kw):
    return ps.evaluate(
        league_key="lg",
        scoring=CARD,
        scoring_fingerprint="sf-test",
        weekly_archives=archives,
        realized_weeks=realized,
        **kw,
    )


def _points(result, provider=None):
    return [
        p
        for p in result.pairs
        if p.stat == ps.STAT_POINTS and (provider is None or p.provider == provider)
    ]


# ── temporal guard ───────────────────────────────────────────────────────────


def test_a_projection_observed_after_kickoff_is_excluded():
    players = _players(3)
    players["999"] = _entry("999", observed=KICK + timedelta(minutes=5))
    result = _weekly([_archive(players)], [_realized(players)])
    scored = {p.player.split(":")[1] for p in _points(result)}
    assert "999" not in scored and scored == {"100", "101", "102"}
    week = result.summary["weekly"]["weeks"][0]
    assert week["census"]["post_kickoff_excluded"] == 1


def test_a_realized_dump_fetched_before_the_last_kickoff_scores_nothing():
    players = _players(3)
    result = _weekly([_archive(players)], [_realized(players, fetched=KICK - timedelta(hours=1))])
    assert result.pairs == []
    assert result.summary["weekly"]["weeks"][0]["state"] == "realized_fetched_before_last_kickoff"


def test_a_mid_game_dump_after_the_last_kickoff_is_not_scored_as_final():
    """B3: a dump read after the last kickoff while the week is still being played
    (gp=1 partial lines) is NOT an outcome: the host state must show the week done."""
    players = _players(3)
    mid_game = _realized(players, fetched=KICK + timedelta(hours=1), host=HOST_DURING)
    result = _weekly([_archive(players)], [mid_game])
    assert result.pairs == []
    assert result.summary["weekly"]["weeks"][0]["state"] == "realized_not_proven_final"


def test_a_dump_with_no_host_evidence_is_not_scored():
    players = _players(3)
    unproven = _realized(players, host=None)
    result = _weekly([_archive(players)], [unproven])
    assert result.pairs == []
    assert result.summary["weekly"]["weeks"][0]["state"] == "realized_not_proven_final"


def test_a_final_dump_inside_the_correction_window_is_not_scored():
    players = _players(3)
    early = _realized(players, fetched=KICK + timedelta(days=1))
    result = _weekly([_archive(players)], [early])
    assert result.pairs == []
    assert result.summary["weekly"]["weeks"][0]["state"] == "realized_within_correction_window"


def test_the_newest_proven_final_dump_wins_over_a_later_unproven_one():
    players = _players(3)
    final = _realized(players)
    later_bad = _realized(
        players, fetched=KICK + timedelta(days=5), host=None, **{"100": {"rec": 99.0, "gp": 1.0}}
    )
    result = _weekly([_archive(players)], [final, later_bad])
    assert {p.actual for p in _points(result)} == {4.0 + 5.5}
    assert result.summary["weekly"]["weeks"][0]["realizedSource"] == final.source_key


def test_host_week_final_reads_the_host_state():
    assert ps.host_week_final(HOST_AFTER, SEASON, WEEK)
    assert not ps.host_week_final(HOST_DURING, SEASON, WEEK)
    assert ps.host_week_final({"season": "2026", "week": 1, "season_type": "post"}, SEASON, 17)
    assert ps.host_week_final({"season": "2027", "week": 1, "season_type": "pre"}, SEASON, 18)
    assert not ps.host_week_final({"season": "2026", "week": 9, "season_type": "pre"}, SEASON, 1)
    assert not ps.host_week_final({"week": 9}, SEASON, 1)
    assert not ps.host_week_final(None, SEASON, 1)


def test_a_season_snapshot_is_scored_only_on_weeks_after_its_as_of():
    # Week 2's first kickoff is 2026-09-17T00:15Z: a snapshot dated that same day is
    # bounded at the END of the day, so week 2 is NOT after it (conservative).
    snap = _snapshot("2026-09-17", players=["a"])
    realized = _realized_season({"a": [(1, 99.0), (2, 99.0), (3, 10.0), (4, 12.0)]})
    result = ps.evaluate(
        league_key="lg",
        scoring=CARD,
        scoring_fingerprint="sf",
        season_snapshots=[snap],
        realized_season=realized,
    )
    snapshot_row = result.summary["season"]["snapshots"][0]
    # weeks 1-2 kicked off before the snapshot's day ended: never scored against it.
    assert snapshot_row["eligibleWeeks"] == [3, 4]
    champion = [p for p in result.pairs if p.provider == ps.CHAMPION]
    assert champion and champion[0].actual == pytest.approx(11.0)


# ── missing is never zero ────────────────────────────────────────────────────


def test_an_absent_realized_row_is_missing_not_zero():
    players = _players(3)
    realized = _realized(["100", "101"])  # 102 has no row at all
    result = _weekly([_archive(players)], [realized])
    scored = {p.player.split(":")[1] for p in _points(result)}
    assert scored == {"100", "101"}
    assert result.summary["weekly"]["weeks"][0]["census"]["outcome_missing"] == 1
    assert all(p.actual != 0.0 for p in _points(result))


def test_a_player_who_did_not_play_is_counted_not_scored():
    players = _players(2)
    realized = _realized(["100"], **{"101": {"gp": 0.0}})
    result = _weekly([_archive(players)], [realized])
    assert {p.player.split(":")[1] for p in _points(result)} == {"100"}
    assert result.summary["weekly"]["weeks"][0]["census"]["did_not_play"] == 1


def test_a_week_with_no_realized_dump_scores_nothing():
    result = _weekly([_archive(_players(3))], [])
    assert result.pairs == []
    assert result.summary["weekly"]["weeks"][0]["state"] == "realized_unavailable"


def test_a_stat_the_realized_line_does_not_publish_is_unpublished_never_zero():
    """B1: no default-to-zero. A stat absent from the host line is unavailable."""
    players = {"100": _entry("100", observed=KICK - timedelta(hours=1))}
    realized = _realized([], **{"100": {"rec": 3.0, "gp": 1.0}})  # rec_yd not published
    result = _weekly([_archive(players)], [realized])
    assert not [p for p in result.pairs if p.stat == "rec_yd"]
    assert [p.actual for p in result.pairs if p.stat == "rec"] == [3.0]
    assert result.summary["weekly"]["weeks"][0]["census"]["stat_actual_unpublished"] == 1


def test_alias_spellings_are_one_rule_on_both_sides():
    """B1: the host line may spell a rule ``idp_pass_def`` while the card or the
    projection spells it ``idp_pd``. Both sides are compared on ONE spelling, so a
    league-paid stat can never read actual 0 because of a spelling."""
    card = {**CARD, "idp_pass_def": 2.0, "idp_tkl_solo": 1.0}
    row = _proj_row("200", rec=0.0, rec_yd=0.0)
    row["player"] = {"fantasy_positions": ["DB"], "position": "DB"}
    row["stats"] = {"idp_pd": 0.7, "idp_tkl_solo": 4.1}
    players = {
        "200": {
            "observedAt": (KICK - timedelta(hours=1)).isoformat(),
            "kickoffAt": KICK.isoformat(),
            "row": row,
        }
    }
    realized = _realized([], **{"200": {"idp_pass_def": 2.0, "idp_tkl_solo": 5.0, "gp": 1.0}})
    result = ps.evaluate(
        league_key="lg",
        scoring=card,
        scoring_fingerprint="sf",
        weekly_archives=[_archive(players)],
        realized_weeks=[realized],
    )
    by_stat = {p.stat: p for p in result.pairs}
    assert by_stat["idp_pd"].projected == 0.7 and by_stat["idp_pd"].actual == 2.0
    assert by_stat["idp_tkl_solo"].actual == 5.0


# ── duplicates, versions ─────────────────────────────────────────────────────


def test_a_duplicate_week_archive_is_scored_once():
    players = _players(3)
    a = _archive(players, source="archive")
    b = _archive(players, source="rawlog")
    result = _weekly([a, b], [_realized(players)])
    assert len(_points(result)) == 3
    states = [w["state"] for w in result.summary["weekly"]["weeks"]]
    assert states.count("duplicate_skipped") == 1


def test_a_duplicate_snapshot_record_is_scored_once():
    snap = _snapshot("2026-08-01", players=["a"], duplicate=True)
    result = ps.evaluate(
        league_key="lg",
        scoring=CARD,
        scoring_fingerprint="sf",
        season_snapshots=[snap],
        realized_season=_realized_season({"a": [(3, 10.0)]}),
    )
    assert result.summary["season"]["snapshots"][0]["census"]["duplicate_record"] == 1
    assert len([p for p in result.pairs if p.provider == "clayProjections"]) == 1


def test_a_same_day_refresh_chain_is_scored_once_from_its_final_member():
    """B2: the weekly BDVM refresh writes baseline, then _clay, then _idpshow on ONE
    date, each carrying the earlier records forward. Only the final member counts."""
    day = "2026-08-01"
    baseline = _snapshot(day, players=["a", "b"], name=f"projections_{day}.json")
    clay = _snapshot(day, players=["a", "b"], name=f"projections_{day}_clay.json")
    idpshow = _snapshot(
        day, players=["a", "b"], idp_show=True, name=f"projections_{day}_idpshow.json"
    )
    result = ps.evaluate(
        league_key="lg",
        scoring=CARD,
        scoring_fingerprint="sf",
        season_snapshots=[idpshow, baseline, clay],
        realized_season=_realized_season({"a": [(3, 10.0)], "b": [(3, 8.0)]}),
    )
    states = sorted(r["state"] for r in result.summary["season"]["snapshots"])
    assert states == ["scored", "superseded_in_day_chain", "superseded_in_day_chain"]
    for provider in ("clayProjections", "idpShowProjections", ps.CHAMPION):
        assert sorted(p.player for p in result.pairs if p.provider == provider) == ["a", "b"]
    assert [c["n"] for c in result.summary["season"]["pairedComparison"]] == [2, 2]


def test_snapshot_vintages_are_separate_cohorts():
    older = _snapshot("2026-08-01", players=["a"])
    newer = _snapshot("2026-08-20", players=["a"])
    result = ps.evaluate(
        league_key="lg",
        scoring=CARD,
        scoring_fingerprint="sf",
        season_snapshots=[older, newer],
        realized_season=_realized_season({"a": [(3, 10.0)]}),
    )
    models = {p.model for p in result.pairs if p.provider == "clayProjections"}
    assert models == {"asOf=2026-08-01", "asOf=2026-08-20"}
    ids = {r.model_version_id for r in ps.receipts(result, code_sha="c", scoring_fingerprint="sf")}
    assert len([i for i in ids if "clayProjections" in i]) == 2


def test_another_provider_model_is_refused_not_relabelled():
    players = _players(2)
    players["100"]["row"]["company"] = "someoneelse"
    result = _weekly([_archive(players)], [_realized(players)])
    assert {p.model for p in _points(result)} == {"rotowire"}
    assert result.summary["weekly"]["weeks"][0]["census"]["refused:model_company_mismatch"] == 1


# ── champion vs constituents ─────────────────────────────────────────────────


def test_weekly_reports_one_family_honestly():
    result = _weekly([_archive(_players(3))], [_realized(_players(3))])
    weekly = result.summary["weekly"]
    assert weekly["providerFamiliesObserved"] == 1
    assert weekly["championEqualsSoleConstituent"] is True


def test_season_champion_is_the_equal_family_mean_of_its_constituents():
    snap = _snapshot("2026-08-01", players=["a"], idp_show=True)
    result = ps.evaluate(
        league_key="lg",
        scoring=CARD,
        scoring_fingerprint="sf",
        season_snapshots=[snap],
        realized_season=_realized_season({"a": [(3, 10.0)]}),
    )
    by_provider = {p.provider: p for p in result.pairs}
    assert by_provider[ps.CHAMPION].families == 2
    # Not vacuous: the BDVM-vocabulary line really scores (85 rec + 1020 yd / 17 g).
    assert by_provider["clayProjections"].projected == pytest.approx((85 + 102) / 17)
    assert by_provider[ps.CHAMPION].projected == pytest.approx(
        (by_provider["clayProjections"].projected + by_provider["idpShowProjections"].projected) / 2
    )


# ── sample size, metrics, replay, receipts ───────────────────────────────────


def test_a_small_sample_is_insufficient_with_no_metric():
    result = _weekly([_archive(_players(5))], [_realized(_players(5))])
    for cohort in result.summary["cohorts"]:
        assert cohort["status"] == "insufficient_sample" and cohort["metrics"] is None
    for receipt in ps.receipts(result, code_sha="c", scoring_fingerprint="sf"):
        assert receipt.body["verdict"] == VERDICT_INSUFFICIENT
        assert receipt.body["promotes"] is False


def test_a_sufficient_sample_reports_mae_rmse_bias():
    players = _players(40)
    result = _weekly([_archive(players)], [_realized(players)])
    cohort = next(
        c
        for c in result.summary["cohorts"]
        if c["stat"] == ps.STAT_POINTS and c["position"] == ps.ALL_POSITIONS
    )
    assert cohort["status"] == "ok" and cohort["n"] == 40
    pts = _points(result)
    bias = sum(p.projected - p.actual for p in pts) / len(pts)
    assert cohort["metrics"]["bias"] == pytest.approx(bias, abs=1e-4)


def test_replay_is_byte_identical():
    players = _players(40)
    a = _weekly([_archive(players)], [_realized(players)])
    b = _weekly([_archive(players)], [_realized(players)])
    assert canonical_json(a.summary) == canonical_json(b.summary)
    ra = [r.content_hash() for r in ps.receipts(a, code_sha="c", scoring_fingerprint="sf")]
    rb = [r.content_hash() for r in ps.receipts(b, code_sha="c", scoring_fingerprint="sf")]
    assert ra == rb


def test_receipts_round_trip_through_the_store(tmp_path):
    players = _players(40)
    result = _weekly([_archive(players)], [_realized(players)])
    receipts = ps.receipts(result, code_sha="c", scoring_fingerprint="sf")
    out = rs.append_receipts(receipts, path=tmp_path / "receipts.sqlite")
    assert out["written"] == len(receipts) and not out["rejected"]
    again = rs.append_receipts(receipts, path=tmp_path / "receipts.sqlite")
    assert again["duplicates"] == len(receipts) and not again["contentConflicts"]


# ── helpers ──────────────────────────────────────────────────────────────────


def _snapshot(
    as_of: str, *, players, duplicate=False, idp_show=False, name=None
) -> ps.SeasonSnapshot:
    records = []
    for key in players:
        records.append(
            ProjectionRecord(
                source="clayProjections",
                player_key=key,
                position="WR",
                season=SEASON,
                as_of=as_of,
                games=17.0,
                # BDVM stat-line vocabulary (nflverse columns), not Sleeper keys.
                stat_line={"receptions": 85.0, "receiving_yards": 1020.0},
            )
        )
        if duplicate:
            records.append(records[-1])
        if idp_show:
            records.append(
                ProjectionRecord(
                    source="idpShowProjections",
                    player_key=key,
                    position="WR",
                    season=SEASON,
                    as_of=as_of,
                    games=17.0,
                    fpg=12.0,
                    scoring_native=True,
                )
            )
    return ps.SeasonSnapshot(
        as_of=as_of, records=records, source_key=f"data/bdvm/{name or f'projections_{as_of}.json'}"
    )


def _realized_season(points, final_weeks=(1, 2, 3, 4)) -> ps.RealizedSeason:
    first = datetime(2026, 9, 10, 0, 15, tzinfo=timezone.utc)
    return ps.RealizedSeason(
        season=SEASON,
        known_at=datetime(2026, 10, 7, tzinfo=timezone.utc),
        points=points,
        week_first_kickoff={w: first + timedelta(days=7 * (w - 1)) for w in range(1, 5)},
        source_key="nflverse-2026",
        final_weeks=frozenset(final_weeks),
    )


def test_script_keeps_one_copy_per_realized_content_so_replays_are_stable(tmp_path):
    from scripts import projection_scorecard as script

    first = script._keep_if_changed(tmp_path, {"100": {"rec": 3.0}}, dry_run=False)
    again = script._keep_if_changed(tmp_path, {"100": {"rec": 3.0}}, dry_run=False)
    assert again["readAt"] == first["readAt"]  # unchanged content keeps its original read instant
    changed = script._keep_if_changed(tmp_path, {"100": {"rec": 4.0}}, dry_run=False)
    assert changed["sha256"] != first["sha256"]
    assert len(list(tmp_path.glob("*.json"))) == 2


def test_real_capture_scores_identically_on_both_sides_when_the_line_is_realized():
    """A real RotoWire week-3 capture under dynasty_main's committed card: when the
    realized host line equals the projected line, the projection owner and the
    realized owner must agree to the cent -- the scorecard adds no scoring of its own."""
    import json
    from pathlib import Path

    repo = Path(__file__).resolve().parents[2]
    rows = json.loads(
        (
            repo / "tests/fixtures/game_day/sleeper_projections/2026_w3_rotowire_sample.json"
        ).read_text(encoding="utf-8")
    )
    card = json.loads(
        (repo / "config/league_intel/sleeper_league_snapshot_2026-07-26.json").read_text(
            encoding="utf-8"
        )
    )["scoring_settings"]
    kick = datetime(2026, 9, 28, 17, tzinfo=timezone.utc)
    observed = (kick - timedelta(hours=3)).isoformat()
    players = {
        str(r["player_id"]): {"observedAt": observed, "kickoffAt": kick.isoformat(), "row": r}
        for r in rows
    }
    realized = ps.RealizedWeek(
        season=2026,
        week=3,
        fetched_at=kick + timedelta(days=4),
        stats={pid: dict(e["row"]["stats"]) for pid, e in players.items()},
        source_key="replay",
        host_state={"season": "2026", "week": 4, "season_type": "regular"},
        host_state_observed_at=kick + timedelta(days=4) - timedelta(minutes=1),
    )
    archive = ps.WeeklyArchive(2026, 3, {"players": players}, "replay")
    result = ps.evaluate(
        league_key="dynasty_main",
        scoring=card,
        scoring_fingerprint="sf",
        weekly_archives=[archive],
        realized_weeks=[realized],
    )
    points = _points(result)
    assert len(points) >= 10
    for p in points:
        assert p.projected == pytest.approx(p.actual, abs=1e-9), p.player
    # Per stat too (B1): every league-paid stat both lines publish must agree --
    # a spelling mismatch or a defaulted 0 would break it.
    per_stat = [p for p in result.pairs if p.stat != ps.STAT_POINTS]
    assert len(per_stat) >= 20
    assert {p.position for p in per_stat} >= {"QB", "DL", "LB", "DB"}
    for p in per_stat:
        assert p.projected == pytest.approx(p.actual, abs=1e-9), (p.player, p.stat)


def test_a_season_week_the_host_has_not_finished_is_not_scored():
    snap = _snapshot("2026-08-01", players=["a"])
    realized = _realized_season({"a": [(3, 10.0), (4, 30.0)]}, final_weeks=(1, 2, 3))
    result = ps.evaluate(
        league_key="lg",
        scoring=CARD,
        scoring_fingerprint="sf",
        season_snapshots=[snap],
        realized_season=realized,
    )
    assert result.summary["season"]["snapshots"][0]["eligibleWeeks"] == [1, 2, 3]
    assert [p.actual for p in result.pairs if p.provider == ps.CHAMPION] == [10.0]


def test_season_uncovered_league_paid_keys_are_reported():
    card = {**CARD, "fum_lost": -2.0}
    snap = _snapshot("2026-08-01", players=["a"])
    result = ps.evaluate(
        league_key="lg",
        scoring=card,
        scoring_fingerprint="sf",
        season_snapshots=[snap],
        realized_season=_realized_season({"a": [(3, 10.0)]}),
    )
    row = result.summary["season"]["snapshots"][0]
    assert row["uncoveredLeaguePaidKeys"].get("fum_lost") == 1
    assert row["census"]["projection_uncovered_keys"] == 1
