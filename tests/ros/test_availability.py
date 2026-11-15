"""Player-week availability rules (src/ros/availability.py)."""

from __future__ import annotations

from datetime import date, timedelta

from src.ros import availability as av

SEASON = 2026
LEAGUE = {"leg": 6, "playoff_week_start": 15, "playoff_teams": 7}
WEEK1 = date(2026, 9, 10)


def _rows(byes: dict[str, int] | None = None):
    """Two teams playing each other every regular-season week, minus byes."""
    byes = byes or {}
    rows = []
    for wk in range(1, 19):
        home, away = "NYG", "DAL"
        if byes.get(home) == wk or byes.get(away) == wk:
            continue
        rows.append(
            {
                "game_type": "REG",
                "week": wk,
                "gameday": (WEEK1 + timedelta(days=7 * (wk - 1) + 3)).isoformat(),
                "home_team": home,
                "away_team": away,
            }
        )
    return rows


def _ctx(byes=None, evidence=None, overrides=None, rows=True):
    return av.build_context(
        season=SEASON,
        league_settings=LEAGUE,
        schedule_rows=_rows(byes) if rows else [],
        evidence_payload={"asOf": "2026-10-17T20:00:00Z", "players": evidence or {}},
        overrides=overrides or [],
    )


def _ev(code, ret, reported="2026-09-30T20:35Z"):
    return {"current": {"statusCode": code, "returnDate": ret, "reportedAt": reported}}


def states(pid, meta, ctx):
    return {w: s.state for w, s in av.player_week_states(pid, meta, ctx).items()}


def test_horizon_is_current_week_through_championship():
    weeks, basis = av.fantasy_week_horizon(LEAGUE)
    assert weeks == tuple(range(6, 18))  # 7 teams -> 3 rounds: 15, 16, 17
    assert basis["lastWeekSource"] == "championship_week"


def test_horizon_without_league_settings_is_labelled():
    weeks, basis = av.fantasy_week_horizon({}, fallback_current_week=6)
    assert weeks[0] == 6 and basis["currentWeekSource"] == "calendar_fallback"
    assert basis["lastWeekSource"] == "nfl_regular_season_league_unknown"


def test_season_ending_return_date_is_out_every_remaining_week():
    """Dart, 2026-10-17: Sleeper IR, ESPN IR with returnDate 2027-01-17."""
    meta = {"team": "NYG", "injury_status": "IR", "news_updated": 1_759_000_000_000}
    s = states("12508", meta, _ctx(evidence={"12508": _ev("IR", "2027-01-17")}))
    assert set(s.values()) == {av.UNAVAILABLE}
    assert (
        av.summarize(
            av.player_week_states("12508", meta, _ctx(evidence={"12508": _ev("IR", "2027-01-17")}))
        )["eligibleWeeks"]
        == 0
    )


def test_mid_season_return_is_out_until_then_then_uncertain_then_available():
    meta = {"team": "NYG", "injury_status": "IR"}
    # Week 9's game is 2026-11-08; return on 2026-11-05 means week 9 is back.
    s = states("p", meta, _ctx(evidence={"p": _ev("IR", "2026-11-05")}))
    assert [s[w] for w in (6, 7, 8)] == [av.UNAVAILABLE] * 3
    assert s[9] == av.UNCERTAIN
    assert s[10] == av.AVAILABLE


def test_ir_alone_is_not_season_ending():
    meta = {"team": "NYG", "injury_status": "IR"}
    s = states("p", meta, _ctx())
    assert s[6] == av.UNAVAILABLE  # current week: host-declared
    assert set(s[w] for w in range(7, 18)) == {av.UNCERTAIN}  # no stated return


def test_weekly_out_designation_is_current_week_only():
    s = states("p", {"team": "NYG", "injury_status": "Out"}, _ctx())
    assert s[6] == av.UNAVAILABLE and s[7] == av.AVAILABLE


def test_questionable_is_uncertain_not_out():
    s = states("p", {"team": "NYG", "injury_status": "Questionable"}, _ctx())
    assert s[6] == av.UNCERTAIN and s[7] == av.AVAILABLE


def test_bye_week_is_unavailable_for_a_healthy_player():
    s = states("p", {"team": "NYG", "injury_status": None}, _ctx(byes={"NYG": 11}))
    assert s[11] == av.UNAVAILABLE
    assert av.player_week_states("p", {"team": "NYG"}, _ctx(byes={"NYG": 11}))[11].reason == "bye"
    assert s[10] == av.AVAILABLE


def test_host_active_beats_an_older_return_report():
    meta = {"team": "NYG", "injury_status": None, "news_updated": 1_792_000_000_000}  # Oct 2026
    s = states("p", meta, _ctx(evidence={"p": _ev("IR", "2027-01-17", "2026-09-30T20:35Z")}))
    assert set(s.values()) == {av.AVAILABLE}


def test_newer_return_report_beats_a_lagging_host_record():
    meta = {"team": "NYG", "injury_status": None, "news_updated": 1_759_000_000_000}  # Sep 2025
    s = states("p", meta, _ctx(evidence={"p": _ev("IR", "2027-01-17", "2026-10-16T12:00Z")}))
    assert set(s.values()) == {av.UNAVAILABLE}


def test_no_host_metadata_is_unknown_never_available():
    s = states("p", None, _ctx())
    assert set(s.values()) == {av.UNKNOWN}


def test_owner_override_wins():
    ov = [{"sleeperId": "p", "season": SEASON, "fromWeek": 8, "throughWeek": None}]
    s = states("p", {"team": "NYG"}, _ctx(overrides=ov))
    assert s[7] == av.AVAILABLE and s[8] == av.UNAVAILABLE and s[17] == av.UNAVAILABLE


def test_without_a_schedule_only_a_post_season_return_is_decisive():
    meta = {"team": "NYG", "injury_status": "IR"}
    no_sched = _ctx(evidence={"p": _ev("IR", "2027-02-15")}, rows=False)
    assert set(states("p", meta, no_sched).values()) == {av.UNAVAILABLE}
    mid = _ctx(evidence={"p": _ev("IR", "2026-11-05")}, rows=False)
    assert set(states("p", meta, mid).values()) == {av.UNCERTAIN}
    assert no_sched.basis["schedule"] == "unavailable"


def test_a_questionable_return_date_is_not_binding():
    """Only out-type ESPN statuses make a return date decide a week."""
    meta = {"team": "NYG", "injury_status": "Questionable"}
    s = states("p", meta, _ctx(evidence={"p": _ev("Q", "2026-12-01")}))
    assert s[7] == av.AVAILABLE


def test_summary_counts_and_reasons():
    meta = {"team": "NYG", "injury_status": "IR"}
    summ = av.summarize(
        av.player_week_states("p", meta, _ctx(evidence={"p": _ev("IR", "2026-11-05")}))
    )
    assert summ["weeks"] == 12 and summ["unavailableWeeks"] == 3 and summ["uncertainWeeks"] == 1
    assert summ["reasons"]["expected_return_after_game"] == 3
