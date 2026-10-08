"""DFS-AUTO-19: NBA + NHL slates reach /dfs with no uploads — recorded schedule, real code paths.

Fixtures:

* ESPN scoreboard payloads RECORDED 2026-10-07 and trimmed to the fields
  ``league_schedule.parse`` reads (``fixtures/espn_scoreboard_*.json`` — factual
  schedule data only);
* Daily Fantasy Fuel pages SYNTHESISED in the exact row shape observed on the live
  NHL pages on 2026-10-07 (attribute order, the ``data-ou= "…"`` spacing, the
  ``reg_line`` / ``pp_line`` / ``starter_flag`` attributes) with invented "Syn"
  names, salaries and projections — DFF content is not committed (redistribution
  rights are not established) — and run through the REAL ``sources_dff.parse``.
"""

from __future__ import annotations

import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.dfs import pit, sources_dff, store
from src.dfs.auto import SYSTEM_OWNER, daily, league_schedule, refresh
from src.dfs.export import ExportError, build_upload_csv
from src.dfs.imports import SlateAthlete
from src.dfs.optimizer import optimize, parse_constraints
from src.dfs.rules import get_ruleset

FIX = Path(__file__).parent / "fixtures"
NHL_DAY, NBA_DAY = "2026-10-07", "2026-10-21"
NHL_NOW = datetime(2026, 10, 7, 16, 0, tzinfo=timezone.utc)  # noon ET, 7.5 h to lock
NBA_NOW = datetime(2026, 10, 21, 15, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DFS_DATA_DIR", str(tmp_path))


def scoreboard(sport):
    day = NHL_DAY if sport == "nhl" else NBA_DAY
    return json.loads((FIX / f"espn_scoreboard_{sport}_{day}.json").read_text(encoding="utf-8"))


def _row(**a):
    """One ``<tr>`` in the live page's attribute layout (observed 2026-10-07)."""
    return (
        f'<tr class=" projections-listing " data-start_date="{a["day"]}"  data-name="{a["name"]}" '
        f'data-fn="Syn" data-ln="{a["name"][4:]}" data-pos="{a["pos"]}" data-pos_alt="{a.get("alt", "")}" '
        f'data-spread="-1.5" data-ou= "6.5" data-rest="2" data-inj="{a.get("inj", "")}" '
        f'data-team="{a["team"]}" data-opp="{a["opp"]}" data-loc="{a["loc"]}" data-proj_score="3.1" '
        f'data-salary="{a["salary"]}" data-opp_rank="0"  data-reg_line="{a.get("rl", "")}" '
        f'data-pp_line="{a.get("pp", "")}" data-l5_avg="10.0" data-l10_avg="9.0" data-szn_avg="9.5" '
        f'data-ppg_proj="{a["proj"]}" data-value_proj="2.0" data-player_id="{a["pid"]}" '
        f'data-starter_flag="{a.get("sf", "0")}" data-depth_rank="1" >'
    )


# NHL opening night as DFF listed it (codes as DFF writes them).
NHL_GAMES = [("PIT", "WSH"), ("COL", "WPG"), ("EDM", "ANA")]
NHL_SHAPE = [("C", 2), ("W", 4), ("D", 3), ("G", 2)]
# Three late NBA games, DFF-style codes that differ from ESPN's (GS/GSW, PHX/PHO).
NBA_GAMES = [("GSW", "LAL"), ("PHO", "POR"), ("SAC", "LAC")]
NBA_SHAPE = [("PG", "SG"), ("SG", ""), ("SF", ""), ("PF", "C"), ("C", ""), ("PG", ""), ("SF", "PF")]


def pool_html(sport, platform, extra_rows=()):
    games, shape, day = (
        (NHL_GAMES, NHL_SHAPE, NHL_DAY) if sport == "nhl" else (NBA_GAMES, NBA_SHAPE, NBA_DAY)
    )
    bump = 0 if platform == "draftkings" else 700
    rows, n = [], 0
    for away, home in games:
        for team, opp, loc in ((away, home, "@"), (home, away, "vs")):
            if sport == "nhl":
                specs = [(p, "", i) for p, k in shape for i in range(k)]
            else:
                specs = [(p, alt, i) for i, (p, alt) in enumerate(shape)]
            for pos, alt, i in specs:
                n += 1
                rows.append(
                    _row(
                        day=day,
                        name=f"Syn {team}{pos}{i}",
                        pos=pos,
                        alt=alt,
                        team=team,
                        opp=opp,
                        loc=loc,
                        salary=3000 + 400 * (n % 13) + bump,
                        proj=f"{5 + n % 9}.5",
                        pid=f"{team}{pos}{i}",
                        rl=(i % 4) + 1 if pos != "G" else "",
                        pp=1 if i == 0 and pos != "G" else "",
                        sf="1" if (pos == "G" and i == 0 and team != "ANA") else "0",
                    )  # fmt: skip
                )
    return "<html><table>" + "".join(rows) + "".join(extra_rows) + "</table></html>"


def dff_page(sport, platform, html=None):
    text = html if html is not None else pool_html(sport, platform)
    return {
        "rows": sources_dff.parse(text),
        "url": f"https://example.invalid/{sport}/{platform}",
        "fetchedAt": "2026-10-07T15:55:00+00:00",
        "updatedAt": sources_dff.page_updated_at(text),
        "sha256": "0" * 64,
    }


def schedule(sport, day):
    games, dropped = league_schedule.parse(sport, scoreboard(sport))
    return {"games": [g for g in games if g.date_et == day], "dropped": dropped, "url": "x"}


def run(sport, now=None, **over):
    kw = {"get_dff": dff_page, "get_schedule": schedule}
    kw.update(over)
    return refresh.refresh_daily(
        sport, now=now or (NHL_NOW if sport == "nhl" else NBA_NOW), force=True, **kw
    )


# ── schedule ─────────────────────────────────────────────────────────────


def test_recorded_nhl_scoreboard_parses_to_utc_starts_and_eastern_dates():
    games, dropped = league_schedule.parse("nhl", scoreboard("nhl"))
    assert not dropped
    by_id = {g.event_id: g for g in games}
    assert set(by_id) == {"PIT@WSH", "COL@WPG", "EDM@ANA"}
    assert by_id["PIT@WSH"].start_utc == "2026-10-07T23:30:00+00:00"
    # 02:00Z on the 8th is 10 PM ET on the 7th — the platforms' slate day.
    assert by_id["EDM@ANA"].start_utc.startswith("2026-10-08T02:00")
    assert by_id["EDM@ANA"].date_et == NHL_DAY


def test_recorded_nba_scoreboard_maps_espn_codes_to_canonical_codes():
    games, _ = league_schedule.parse("nba", scoreboard("nba"))
    ids = {g.event_id for g in games}
    assert len(games) == 11
    # ESPN writes GS / UTAH / WSH / NO; the identity owner's NBA table answers.
    assert {"GSW@LAL", "UTA@MEM", "MIL@WAS", "IND@NOP"} <= ids


def test_unusable_schedule_events_are_dropped_with_a_reason_never_timed_by_a_guess():
    payload = scoreboard("nhl")
    ev = payload["events"]
    ev[0]["season"]["type"] = 1  # preseason
    ev[1]["competitions"][0]["timeValid"] = False
    ev[2]["status"]["type"]["name"] = "STATUS_POSTPONED"
    games, dropped = league_schedule.parse("nhl", payload)
    assert games == []
    assert {d["reason"] for d in dropped} == {
        "season_type_1",
        "start_time_not_valid",
        "status_postponed",
    }
    payload = scoreboard("nhl")
    payload["events"][0]["competitions"][0]["competitors"][0]["team"]["abbreviation"] = "XYZ"
    games, dropped = league_schedule.parse("nhl", payload)
    assert len(games) == 2 and dropped[0]["reason"] == "team_unknown_for_sport"


class _Resp(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_schedule_fetch_is_cached_and_failures_are_named(monkeypatch):
    from src.utils import circuit_breaker

    circuit_breaker.reset_all_for_tests()
    calls = []

    def opener(req, timeout):
        calls.append(req.full_url)
        return _Resp(json.dumps(scoreboard("nhl")).encode())

    got = league_schedule.fetch("nhl", NHL_DAY, now=1000.0, opener=opener)
    assert calls == [
        "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard?dates=20261007"
    ]
    assert not got["fromCache"] and len(got["sha256"]) == 64
    again = league_schedule.fetch("nhl", NHL_DAY, now=1000.0 + 60, opener=opener)
    assert again["fromCache"] and len(calls) == 1

    def down(req, timeout):
        raise OSError("unreachable")

    with pytest.raises(league_schedule.ScheduleError) as e:
        league_schedule.fetch("nba", NBA_DAY, now=5000.0, opener=down)
    assert e.value.code == "PROVIDER_UNAVAILABLE"
    with pytest.raises(league_schedule.ScheduleError) as e:
        league_schedule.scoreboard_url("mma", NBA_DAY)
    assert e.value.code == "UNSUPPORTED_SPORT"
    circuit_breaker.reset_all_for_tests()


# ── the pool ─────────────────────────────────────────────────────────────


def _pool(sport, platform="draftkings", html=None):
    games = schedule(sport, NHL_DAY if sport == "nhl" else NBA_DAY)["games"]
    return daily.build_pool(sport, platform, dff_page(sport, platform, html)["rows"], games)


def test_dff_nhl_rows_carry_lines_and_starter_flag_as_parsed_evidence():
    rows = sources_dff.parse(pool_html("nhl", "draftkings"))
    c0 = next(r for r in rows if r["sourcePlayerId"] == "PITC0")
    assert c0["homeAway"] == "away" and c0["regLine"] == 1 and c0["ppLine"] == 1
    g1 = next(r for r in rows if r["sourcePlayerId"] == "PITG1")
    assert g1["regLine"] is None and g1["ppLine"] is None  # absent, never 0
    assert g1["starterFlag"] == "0"


def test_nhl_pool_is_timed_by_the_schedule_with_sport_scoped_identity():
    ath, rep = _pool("nhl")
    assert rep.used == len(NHL_GAMES) * 2 * 11 and not rep.rejected
    a = next(x for x in ath if x.extra["sourcePlayerId"] == "EDMC0")
    assert a.player_id == "auto-nhl-EDMC0"
    assert a.extra["athleteKey"] == "athlete:nhl:dailyfantasyfuel:EDMC0"
    assert a.extra["identity"] == "provider_scoped" and "NHL" in a.extra["identityReason"]
    assert a.game == "EDM@ANA" and a.opponent == "ANA"
    assert a.start_time_utc.startswith("2026-10-08T02:00")
    assert a.extra["dffRegLine"] == "1" and a.extra["dffPpLine"] == "1"
    assert "sleeperId" not in a.extra  # never joined to the NFL directory
    # Both goalies of a team are listed; unconfirmed starts are disclosed, not hidden.
    assert any("goalie" in n for n in rep.notes)


def test_nba_pool_maps_provider_codes_and_keeps_multi_position_eligibility():
    ath, rep = _pool("nba")
    assert not rep.rejected
    gsw = next(x for x in ath if x.extra["sourcePlayerId"] == "GSWPG0")
    assert gsw.team == "GSW" and gsw.game == "GSW@LAL" and gsw.positions == ["PG", "SG"]
    pho = next(x for x in ath if x.extra["sourcePlayerId"] == "PHOC4")
    assert pho.team == "PHX" and pho.game == "PHX@POR"  # DFF "PHO" == ESPN "PHX"
    assert pho.player_id == "auto-nba-PHOC4"


def test_rows_the_schedule_cannot_time_are_refused_never_guessed():
    bad = [
        _row(day=NBA_DAY, name="Syn Off", pos="PG", team="BOS", opp="NYK", loc="vs",
             salary=5000, proj="20", pid="BOS1"),  # BOS is not on this listed day
        _row(day=NBA_DAY, name="Syn Code", pos="PG", team="XYZ", opp="LAL", loc="@",
             salary=5000, proj="20", pid="XYZ1"),
        _row(day=NBA_DAY, name="Syn Opp", pos="PG", team="LAL", opp="SAC", loc="vs",
             salary=5000, proj="20", pid="LAL9"),
        _row(day=NBA_DAY, name="Syn Loc", pos="PG", team="LAL", opp="GSW", loc="@",
             salary=5000, proj="20", pid="LAL8"),
        _row(day=NBA_DAY, name="Syn Free", pos="PG", team="LAL", opp="GSW", loc="vs",
             salary=0, proj="20", pid="LAL7"),
    ]  # fmt: skip
    ath, rep = _pool("nba", html=pool_html("nba", "draftkings", bad))
    assert {r["name"]: r["reason"] for r in rep.rejected} == {
        "Syn Off": "game_not_on_schedule",
        "Syn Code": "team_unknown_for_sport",
        "Syn Opp": "opponent_disagrees_with_schedule",
        "Syn Loc": "home_away_disagrees_with_schedule",
        "Syn Free": "missing_salary",
    }


def test_ruled_out_players_are_withheld_and_zero_lines_excluded_never_zeroed():
    extra = [
        _row(day=NHL_DAY, name="Syn Hurt", pos="C", team="PIT", opp="WSH", loc="@",
             salary=4000, proj="9.0", pid="PITX1", inj="IR"),
        _row(day=NHL_DAY, name="Syn Iffy", pos="C", team="PIT", opp="WSH", loc="@",
             salary=4000, proj="9.0", pid="PITX2", inj="Q"),
        _row(day=NHL_DAY, name="Syn Scratch", pos="W", team="PIT", opp="WSH", loc="@",
             salary=3000, proj="0", pid="PITX3"),
    ]  # fmt: skip
    ath, rep = _pool("nhl", html=pool_html("nhl", "draftkings", extra))
    by = {a.extra["sourcePlayerId"]: a for a in ath}
    assert by["PITX1"].projection is None and by["PITX1"].projection_source == "withheld:status_IR"
    assert by["PITX2"].projection == 9.0 and by["PITX2"].status == "Q"
    assert by["PITX3"].projection is None and by["PITX3"].projection_source is None
    assert by["PITX3"].extra["excludedFamily"] == "dailyfantasyfuel:zero_line"


# ── refresh, storage, freshness ──────────────────────────────────────────


@pytest.mark.parametrize("sport", ["nba", "nhl"])
def test_refresh_builds_one_listed_slate_per_platform_with_no_uploads(sport):
    out = run(sport)
    assert out["outcome"] == "ok"
    listing = refresh.list_slates(sport, now=NHL_NOW if sport == "nhl" else NBA_NOW)
    assert listing["state"] == "AVAILABLE" and "Daily Fantasy Fuel" in listing["derivationNote"]
    assert {s["platform"] for s in listing["slates"]} == {"draftkings", "fanduel"}
    s = next(x for x in listing["slates"] if x["platform"] == "draftkings")
    day = NHL_DAY if sport == "nhl" else NBA_DAY
    assert s["slateDate"] == day and s["week"] is None and s["sport"] == sport
    assert s["summary"]["games"] == 3 and s["freshness"]["state"] == "CURRENT"
    snap = store.get_snapshot(SYSTEM_OWNER, refresh.get_row(s["autoSlateId"])["snapshotId"])
    body = snap["body"]
    prov = body["slate"]["provenance"]
    assert prov["slateDerivation"] == "dff_listed_slate" and prov["platformIds"] == "unavailable"
    assert prov["identityScope"] == "provider_scoped"
    assert body["positionsNotInRuleset"] == []
    assert body["auto"]["scheduleGamesThatDay"] == (3 if sport == "nhl" else 11)
    # The lock is the FIRST listed game's start, from the schedule.
    expected = "2026-10-07T23:30:00+00:00" if sport == "nhl" else "2026-10-22T02:00:00+00:00"
    assert body["auto"]["lockAt"] == expected
    assert pit.get_slate(SYSTEM_OWNER, snap["id"]) is not None


def test_an_unchanged_refresh_creates_no_new_snapshot():
    run("nhl")
    out = run("nhl", now=NHL_NOW + timedelta(minutes=5))
    assert set(out["platforms"]["draftkings"]["slates"].values()) == {"unchanged"}


def test_failed_sources_are_named_and_keep_the_last_good_slate():
    run("nhl")

    def boom(sport, platform):
        raise RuntimeError("down")

    later = NHL_NOW + timedelta(minutes=40)
    out = run("nhl", now=later, get_dff=boom)
    assert out["outcome"] == "source_error"
    states = {s["freshness"]["state"] for s in refresh.list_slates("nhl", now=later)["slates"]}
    assert states == {"SOURCE_ERROR"}

    def sched_down(sport, day):
        raise league_schedule.ScheduleError("PROVIDER_UNAVAILABLE", "x")

    out = run("nba", get_schedule=sched_down)
    assert out["outcome"] == "source_error"
    assert out["platforms"]["draftkings"] == {
        "outcome": "source_error",
        "stage": "schedule",
        "error": "PROVIDER_UNAVAILABLE",
    }


def test_an_empty_or_preseason_page_is_unavailable_and_backs_off():
    out = run("nba", get_dff=lambda s, p: dff_page(s, p, "<html></html>"))
    assert out["outcome"] == "unavailable"
    assert out["platforms"]["fanduel"]["reason"] == "no_slate_listed"
    listing = refresh.list_slates("nba", now=NBA_NOW)
    assert listing["state"] == "UNAVAILABLE" and "No NBA slate is listed" in listing["reason"]
    assert not refresh.is_due("nba", NBA_NOW + timedelta(minutes=30))
    assert refresh.is_due("nba", NBA_NOW + timedelta(minutes=61))

    # A page listing games the regular-season schedule does not show (preseason).
    def preseason(sport, day):
        return {"games": [], "dropped": [{"reason": "season_type_1"}]}

    out = run("nhl", get_schedule=preseason)
    assert out["outcome"] == "unavailable"
    assert out["platforms"]["draftkings"]["reason"] == "listed_day_not_regular_season"
    listing = refresh.list_slates("nhl", now=NHL_NOW)
    assert listing["state"] == "UNAVAILABLE" and "preseason / all-star" in listing["reason"]


def _pgh(html):
    """DFF team-code drift: Pittsburgh written "PGH", which the NHL table does not know."""
    return html.replace('data-team="PIT"', 'data-team="PGH"').replace(
        'data-opp="PIT"', 'data-opp="PGH"'
    )


def test_listed_rows_matching_no_scheduled_game_are_a_source_error_not_an_off_day():
    """Review blocker on #1695 (PGH repro): the schedule HAS games that day, every
    listed row is refused, and that must read as a data error — never 'off day'."""
    rows = ["<tr" + r for r in pool_html("nhl", "draftkings").split("<tr")[1:]]
    pit_wsh = "".join(r for r in rows if 'data-team="PIT"' in r or 'data-team="WSH"' in r)
    out = run("nhl", get_dff=lambda s, p: dff_page(s, p, _pgh(pit_wsh)))
    assert out["outcome"] == "source_error"
    dk = out["platforms"]["draftkings"]
    assert dk["outcome"] == "source_error" and dk["error"] == "listed_rows_unmatched"
    assert dk["scheduledGames"] == 3 and dk["rowsListed"] == 22
    # PGH rows: unknown code; WSH rows: their opponent "PGH" contradicts the schedule.
    assert dk["rejectedByReason"] == {
        "opponent_disagrees_with_schedule": 11,
        "team_unknown_for_sport": 11,
    }
    listing = refresh.list_slates("nhl", now=NHL_NOW)
    assert listing["state"] == "SOURCE_ERROR"
    assert (
        "not an off day" in listing["reason"] and "off day, the offseason" not in listing["reason"]
    )
    # A failure retries on the short cadence, not the one-hour off-day backoff.
    assert refresh.is_due("nhl", NHL_NOW + timedelta(minutes=11))


def test_partial_team_code_drift_builds_but_marks_the_slate_degraded():
    out = run("nhl", get_dff=lambda s, p: dff_page(s, p, _pgh(pool_html(s, p))))
    assert out["outcome"] == "ok"
    s = next(
        x for x in refresh.list_slates("nhl", now=NHL_NOW)["slates"]
        if x["platform"] == "draftkings"
    )  # fmt: skip
    assert s["freshness"]["state"] == "DEGRADED"
    assert "listed_rows_unmatched:team_unknown_for_sport=11" in s["freshness"]["degraded"]
    assert "lock_may_be_early:untimed_listed_rows" in s["freshness"]["degraded"]


def test_a_single_listed_game_is_not_a_classic_slate():
    rows = ["<tr" + r for r in pool_html("nhl", "draftkings").split("<tr")[1:]]
    one = "".join(r for r in rows if 'data-team="PIT"' in r or 'data-team="WSH"' in r)
    out = run("nhl", get_dff=lambda s, p: dff_page(s, p, one))
    assert out["outcome"] == "unavailable"
    assert out["platforms"]["draftkings"]["reason"] == "single_game_listing"
    listing = refresh.list_slates("nhl", now=NHL_NOW)
    assert "single-game slate is not a classic slate" in listing["reason"]


def test_sports_do_not_see_each_others_slates_or_runs():
    run("nhl")
    assert refresh.list_slates("nba", now=NHL_NOW)["slates"] == []
    assert refresh.list_slates("nfl", now=NHL_NOW)["slates"] == []
    assert refresh.is_due("nba", NHL_NOW)  # nothing stored for the NBA yet


# ── the optimizer consumes it unchanged; upload exports refuse it ────────


@pytest.mark.parametrize("sport", ["nba", "nhl"])
@pytest.mark.parametrize("platform", ["draftkings", "fanduel"])
def test_the_optimizer_builds_legal_lineups_on_the_automatic_slate(sport, platform):
    run(sport)
    s = next(
        x for x in refresh.list_slates(sport, now=NHL_NOW if sport == "nhl" else NBA_NOW)["slates"]
        if x["platform"] == platform
    )  # fmt: skip
    snap = store.get_snapshot(SYSTEM_OWNER, refresh.get_row(s["autoSlateId"])["snapshotId"])
    rs = get_ruleset(snap["ruleset"].split("@")[0])
    assert rs.key.startswith(f"{platform}.{sport}.classic") and not rs.verified
    athletes = [SlateAthlete(**a) for a in snap["body"]["athletes"]]
    res = optimize(rs, athletes, parse_constraints({"lineups": 2}, rs, athletes))
    assert res["status"] == "optimal" and len(res["lineups"]) == 2
    for lineup in res["lineups"]:
        ids = [p["playerId"] for p in lineup["players"]]
        assert all(i.startswith(f"auto-{sport}-") for i in ids)
    with pytest.raises(ExportError) as e:
        build_upload_csv(rs, res["lineups"], athletes)
    assert e.value.code == "PLATFORM_IDS_UNAVAILABLE"


def test_the_timer_script_exit_codes():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "refresh_script", Path(__file__).parents[2] / "scripts" / "refresh_dfs_auto_slates.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.exit_code({"nfl": {"outcome": "not_due"}, "nba": {"outcome": "unavailable"}}) == 2
    assert mod.exit_code({"nfl": {"outcome": "ok"}, "nhl": {"outcome": "not_due"}}) == 0
    assert mod.exit_code({"nfl": {"outcome": "ok"}, "nhl": {"outcome": "partial"}}) == 1
    assert (
        mod.exit_code({"nfl": {"outcome": "not_due"}, "nba": {"outcome": "awaiting_approval"}}) == 2
    )


# ── owner approval of the NBA / NHL schedule source (ADR-DFS-025) ────────


def _approval_file(tmp_path, **entry):
    p = tmp_path / "auto_sources.json"
    p.write_text(json.dumps({"sports": {"nba": entry, "nhl": entry}}), encoding="utf-8")
    return p


def test_nba_nhl_are_pending_owner_approval_today_and_fail_closed(tmp_path):
    from src.dfs.auto import approval

    for sport in ("nba", "nhl"):
        st = approval.sport_status(sport)
        assert st["approved"] is False and st["approval"] == "pending_owner_decision"
        assert st["decisionRecord"] == "docs/game-day/SOURCE_ACCESS_EVIDENCE_2026-09-25.md"
    # "approved" without a date and evidence is NOT approved.
    bare = _approval_file(tmp_path, approval="approved")
    assert approval.sport_status("nba", bare)["approved"] is False
    assert approval.sport_status("nba", bare)["approval"] == "approved_without_evidence"
    ok = _approval_file(
        tmp_path, approval="approved", approvedOn="2026-10-08", evidence="owner chat 2026-10-08"
    )
    assert approval.sport_status("nhl", ok)["approved"] is True
    assert approval.sport_status("nhl", tmp_path / "missing.json")["approved"] is False
    assert approval.sport_status("mma", ok)["approved"] is False


def test_pending_approval_fetches_and_builds_nothing(monkeypatch):
    from src.dfs.auto import live

    def never(*a, **k):
        raise AssertionError("no source may be fetched while approval is pending")

    monkeypatch.setattr(live, "get_daily_dff", never)
    monkeypatch.setattr(live, "get_daily_schedule", never)
    for sport in ("nba", "nhl"):
        out = live.refresh_live(sport, force=True)
        assert out == {
            "outcome": "awaiting_approval",
            "sport": sport,
            "reason": "schedule_source_pending",
        }
    assert live.sport_approved("nfl") is True  # NFL never reads the approval record


# ── review of #1695 @3f5f879b1: run-detail storage, off-day vs error, approval ──


def _preseason(sport, day):
    return {"games": [], "dropped": [{"sourceGameId": "1", "reason": "season_type_1"}]}


def test_a_large_run_detail_is_stored_as_valid_bounded_json_and_reads_back():
    """B1: the stored detail used to be ``json.dumps(...)[:4000]`` — sliced mid-JSON
    for any real page — after which list_slates / is_due raised JSONDecodeError
    (/api/dfs/auto/slates 500, timer wedged).  Repro: a full page, preseason day."""
    run("nhl", get_schedule=_preseason)
    # Every read path that parses the stored detail must work.
    listing = refresh.list_slates("nhl", now=NHL_NOW)
    assert listing["state"] == "UNAVAILABLE"
    assert refresh.is_due("nhl", NHL_NOW + timedelta(hours=2))
    # And a refused-everything page stores counts + a capped sample, still valid.
    big = refresh._bounded_detail(
        {"stage": "pool", "report": {"rowsRead": 999, "rejected": [{"name": "x" * 60}] * 300}}
    )
    parsed = json.loads(big)
    assert len(big) <= refresh.DETAIL_MAX_CHARS and len(parsed["report"]["rejectedSample"]) == 5
    huge = refresh._bounded_detail({"error": "e" * 10_000, "sample": ["s" * 5000] * 3})
    assert len(huge) <= refresh.DETAIL_MAX_CHARS and json.loads(huge)["detailTruncated"] is True


def test_a_corrupt_legacy_run_row_is_unknown_and_due_never_a_crash():
    with refresh._connect() as conn:
        conn.execute(
            "INSERT INTO dfs_auto_runs VALUES (?,?,?,?,?)",
            ("draftkings", "nhl", NHL_NOW.isoformat(), "unavailable", '{"report": {"rej'),
        )
    assert refresh.is_due("nhl", NHL_NOW + timedelta(minutes=1))  # unknown → refresh now
    listing = refresh.list_slates("nhl", now=NHL_NOW)
    assert listing["lastRuns"]["draftkings"]["outcome"] == "unknown"


@pytest.mark.parametrize("stored", ["[1, 2]", '"str"', "123", "null", "true"])
@pytest.mark.parametrize("outcome", ["unavailable", "source_error"])
def test_a_run_detail_that_is_valid_json_but_not_an_object_is_unknown(stored, outcome):
    """Valid JSON that is not an object (a list, a string, a number) used to
    reach ``list_slates`` as the run detail and raise AttributeError on
    ``.get`` — a 500, not a listing.  Any non-object detail is outcome unknown
    (due now), never a raise."""
    with refresh._connect() as conn:
        conn.execute(
            "INSERT INTO dfs_auto_runs VALUES (?,?,?,?,?)",
            ("draftkings", "nhl", NHL_NOW.isoformat(), outcome, stored),
        )
    listing = refresh.list_slates("nhl", now=NHL_NOW)
    assert listing["lastRuns"]["draftkings"]["outcome"] == "unknown"
    assert listing["lastRuns"]["draftkings"]["detail"] == {"corruptDetail": True}
    assert refresh.is_due("nhl", NHL_NOW + timedelta(minutes=1))  # unknown → refresh now


def test_schedule_side_drift_or_an_empty_payload_is_a_source_error_not_an_off_day():
    def drifted(sport, day):
        return {"games": [], "dropped": [{"reason": "team_unknown_for_sport"}] * 3}

    out = run("nhl", get_schedule=drifted)
    dk = out["platforms"]["draftkings"]
    assert dk["outcome"] == "source_error" and dk["error"] == "schedule_has_no_listed_games"
    assert dk["droppedByReason"] == {"team_unknown_for_sport": 3}
    listing = refresh.list_slates("nhl", now=NHL_NOW)
    assert listing["state"] == "SOURCE_ERROR" and "not an off day" in listing["reason"]
    # An ESPN payload with NO events for a day DFF lists a slate on: also an error.
    out = run("nba", get_schedule=lambda sport, day: {"games": [], "dropped": []})
    assert out["platforms"]["fanduel"]["error"] == "schedule_has_no_listed_games"


def test_listing_drift_collapsing_to_one_game_is_a_source_error():
    html = pool_html("nhl", "draftkings")
    for code in ("COL", "WPG", "EDM", "ANA"):
        html = html.replace(f'data-team="{code}"', f'data-team="X{code}"').replace(
            f'data-opp="{code}"', f'data-opp="X{code}"'
        )
    out = run("nhl", get_dff=lambda s, p: dff_page(s, p, html))
    dk = out["platforms"]["draftkings"]
    assert dk["outcome"] == "source_error" and dk["error"] == "listed_games_unmatched"
    assert dk["listedGames"] == 3 and dk["matchedGames"] == 1
    assert "not an off day" in refresh.list_slates("nhl", now=NHL_NOW)["reason"]


def test_partial_schedule_drift_marks_degraded_and_warns_the_lock_may_be_early():
    def missing_first(sport, day):
        got = schedule(sport, day)
        return {**got, "games": [g for g in got["games"] if g.event_id != "PIT@WSH"]}

    out = run("nhl", get_schedule=missing_first)
    assert out["outcome"] == "ok"
    s = next(
        x for x in refresh.list_slates("nhl", now=NHL_NOW)["slates"]
        if x["platform"] == "draftkings"
    )  # fmt: skip
    assert s["summary"]["games"] == 2 and s["freshness"]["state"] == "DEGRADED"
    assert "listed_rows_unmatched:game_not_on_schedule=22" in s["freshness"]["degraded"]
    assert "lock_may_be_early:untimed_listed_rows" in s["freshness"]["degraded"]


def test_a_same_time_failure_is_not_hidden_behind_another_platforms_off_day_backoff():
    def mixed(sport, platform):
        if platform == "fanduel":
            raise RuntimeError("down")
        return dff_page(sport, platform, "<html></html>")

    out = run("nba", get_dff=mixed)
    assert {p: d["outcome"] for p, d in out["platforms"].items()} == {
        "draftkings": "unavailable",
        "fanduel": "source_error",
    }
    # Same timestamp: the failure's 10-minute retry wins, not the 1-hour wait.
    assert refresh.is_due("nba", NBA_NOW + timedelta(minutes=11))
    # Each platform's view names its own state and platform.
    dk = refresh.list_slates("nba", platform="draftkings", now=NBA_NOW)
    fd = refresh.list_slates("nba", platform="fanduel", now=NBA_NOW)
    assert dk["state"] == "UNAVAILABLE" and dk["reason"].startswith("DraftKings: No NBA slate")
    assert fd["state"] == "SOURCE_ERROR" and fd["reason"].startswith("FanDuel: The last NBA")


@pytest.mark.parametrize(
    "doc",
    [
        {"sports": ["nba"]},
        {"sports": "approved"},
        {"sports": {"nba": {"approval": "approved", "approvedOn": "2026-99-99", "evidence": "x"}}},
        {
            "sports": {
                "nba": {"approval": "approved", "approvedOn": "2026-10-08\n", "evidence": "x"}
            }
        },
        {"sports": {"nba": {"approval": "approved", "approvedOn": "2026-10-08", "evidence": 123}}},
        {"sports": {"nba": {"approval": "approved", "approvedOn": "2026-10-08", "evidence": "  "}}},
        {"sports": {"nba": {"approval": "approved", "approvedOn": 20261008, "evidence": "x"}}},
    ],
)
def test_malformed_approval_records_fail_closed_never_raise(tmp_path, doc):
    from src.dfs.auto import approval

    p = tmp_path / "auto_sources.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    assert approval.sport_status("nba", p)["approved"] is False
