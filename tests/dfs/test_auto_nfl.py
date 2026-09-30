"""DFS-AUTO: a real slate reaches /dfs with no uploads — synthetic sources, real code paths.

Every source is a SYNTHETIC fixture in the source's own shape (schedule rows in
nflverse columns, pool rows as ``sources_dff.parse`` returns them, Sleeper
projection rows as the Sleeper endpoint returns them, a Sleeper directory).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.dfs import pit, store
from src.dfs.auto import SYSTEM_OWNER, PlatformIdsUnavailable, nfl, refresh, refuse_synthetic_ids
from src.dfs.export import ExportError, build_upload_csv
from src.dfs.imports import SlateAthlete
from src.dfs.optimizer import optimize, parse_constraints
from src.dfs.rules import get_ruleset

SEASON, WEEK = 2026, 4
# (away, home, gameday, gametime ET) — a real week's SHAPE: TNF, a London
# morning game, four 1:00s, a 4:05, two 4:25s, SNF, MNF.
GAMES = [
    ("PIT", "CLE", "2026-10-01", "20:15"),
    ("IND", "WAS", "2026-10-04", "09:30"),
    ("TEN", "BAL", "2026-10-04", "13:00"),
    ("NE", "BUF", "2026-10-04", "13:00"),
    ("NYJ", "CHI", "2026-10-04", "13:00"),
    ("LA", "PHI", "2026-10-04", "13:00"),
    ("MIA", "MIN", "2026-10-04", "16:05"),
    ("KC", "LV", "2026-10-04", "16:25"),
    ("DEN", "SF", "2026-10-04", "16:25"),
    ("DET", "CAR", "2026-10-04", "20:20"),
    ("ATL", "NO", "2026-10-05", "20:15"),
]
NOW = datetime(2026, 9, 30, 20, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DFS_DATA_DIR", str(tmp_path))


def schedule_rows():
    return [
        {
            "game_id": f"{SEASON}_{WEEK:02d}_{a}_{h}",
            "season": SEASON,
            "week": WEEK,
            "game_type": "REG",
            "gameday": d,
            "gametime": t,
            "away_team": a,
            "home_team": h,
            "spread_line": 3.0,
            "total_line": 45.5,
        }
        for a, h, d, t in GAMES
    ]


def _dfs_team(t):
    return "LAR" if t == "LA" else t


SLOTS = [("QB", 1), ("RB", 2), ("WR", 3), ("TE", 1)]


def pool_rows(platform):
    """One team's worth of players per side of every game (DFF ``parse`` shape)."""
    rows = []
    bump = 0 if platform == "draftkings" else 1000  # FanDuel prices differently
    for away, home, day, _t in GAMES:
        for team, opp in ((_dfs_team(away), _dfs_team(home)), (_dfs_team(home), _dfs_team(away))):
            for pos, n in SLOTS:
                for i in range(n):
                    rows.append(
                        {
                            "name": f"{team} {pos}{i + 1}",
                            "team": team,
                            "opponent": opp,
                            "position": pos,
                            "salary": 3000 + 700 * (len(rows) % 9) + bump,
                            "projection": 6.0 + (len(rows) % 11),
                            "injury": None,
                            "spread": -3.0,
                            "overUnder": 45.5,
                            "impliedTeamTotal": 24.0,
                            "startDate": day,
                            "sourcePlayerId": f"{team}{pos}{i + 1}",
                        }
                    )
            rows.append(
                {
                    "name": f"{team} Defense",
                    "team": team,
                    "opponent": opp,
                    "position": "DST",
                    "salary": 2800 + bump,
                    "projection": 7.0,
                    "injury": None,
                    "startDate": day,
                    "sourcePlayerId": f"{team}DST",
                }
            )
    return rows


def directory():
    d = {}
    for row in pool_rows("draftkings"):
        if row["position"] == "DST":
            continue
        sid = f"s-{row['sourcePlayerId']}"
        first, last = row["name"].split(" ", 1)
        d[sid] = {
            "player_id": sid,
            "full_name": row["name"],
            "first_name": first,
            "last_name": last,
            "position": row["position"],
            "fantasy_positions": [row["position"]],
            "team": row["team"],
            "active": True,
            "injury_status": None,
        }
    return d


def sleeper_rows(directory_):
    """Sleeper weekly projection rows (RotoWire model) with raw stat lines."""
    out = []
    for sid, p in directory_.items():
        if p["position"] == "QB":
            stats = {"pass_yd": 250.0, "pass_td": 1.8, "pass_int": 0.7, "rush_yd": 15.0}
        elif p["position"] == "RB":
            stats = {"rush_yd": 60.0, "rush_td": 0.4, "rec": 3.0, "rec_yd": 20.0}
        else:
            stats = {"rec": 4.0, "rec_yd": 50.0, "rec_td": 0.3}
        out.append(
            {
                "player_id": sid,
                "season": str(SEASON),
                "week": WEEK,
                "season_type": "regular",
                "company": "rotowire",
                "game_id": "g1",
                "team": p["team"],
                "stats": stats,
                "player": {"position": p["position"], "fantasy_positions": [p["position"]]},
            }
        )
    return out


def page(platform):
    return {
        "rows": pool_rows(platform),
        "url": f"https://example.invalid/{platform}",
        "fetchedAt": NOW.isoformat(),
        "updatedAt": (NOW - timedelta(minutes=20)).isoformat(),
        "sha256": "0" * 64,
    }


def run_refresh(now=NOW, **over):
    d = directory()
    kwargs = {
        "get_schedule": lambda season: schedule_rows(),
        "get_dff": page,
        "get_sleeper_rows": lambda s, w: (sleeper_rows(d), now.isoformat()),
        "get_directory": lambda: d,
    }
    kwargs.update(over)
    return refresh.refresh_nfl(now=now, force=True, **kwargs)


# ── schedule → slates ────────────────────────────────────────────────────


def test_slates_are_derived_from_the_schedule_windows():
    games = nfl.games_from_schedule(schedule_rows(), SEASON)
    assert nfl.current_week(games, NOW) == WEEK
    slates = {s.key: s for s in nfl.derive_slates(games)}
    assert set(slates) == {"main", "early", "afternoon", "primetime", "full_week"}
    main = {g.event_id for g in slates["main"].games}
    # Main = Sunday 1:00–4:25 ET: no London morning game, no night games.
    assert main == {"TEN@BAL", "NE@BUF", "NYJ@CHI", "LAR@PHI", "MIA@MIN", "KC@LV", "DEN@SF"}
    assert slates["main"].lock_utc == "2026-10-04T17:00:00+00:00"  # 1:00 PM EDT
    assert {g.event_id for g in slates["primetime"].games} == {"PIT@CLE", "DET@CAR", "ATL@NO"}
    assert len(slates["full_week"].games) == len(GAMES)
    # nflverse's "LA" is the platforms' "LAR".
    assert "LAR@PHI" in main


def test_a_window_identical_to_a_bigger_one_is_not_repeated():
    games = [g for g in nfl.games_from_schedule(schedule_rows(), SEASON) if g.kickoff_et.hour == 13]
    keys = [s.key for s in nfl.derive_slates(games)]
    assert keys == ["main"]  # early == main == full week here: one slate, not three


def test_a_row_without_a_kickoff_time_is_dropped_never_guessed():
    rows = schedule_rows()
    rows[0]["gametime"] = None
    assert "PIT@CLE" not in {g.event_id for g in nfl.games_from_schedule(rows, SEASON)}


# ── the pool ─────────────────────────────────────────────────────────────


def _pool(platform="draftkings", **kw):
    games = nfl.games_from_schedule(schedule_rows(), SEASON)
    return nfl.build_pool(platform, pool_rows(platform), games, **kw)


def test_pool_gets_platform_salary_positions_ids_and_kickoffs():
    dk, rep = _pool("draftkings")
    fd, _ = _pool("fanduel")
    assert rep.used == len(pool_rows("draftkings")) and not rep.rejected
    a = next(x for x in dk if x.name == "LAR QB1")
    assert a.player_id == "auto-LARQB1" and a.game == "LAR@PHI" and a.opponent == "PHI"
    assert a.start_time_utc == "2026-10-04T17:00:00+00:00"
    # DraftKings and FanDuel stay separate: own salaries and own defense label.
    b = next(x for x in fd if x.name == "LAR QB1")
    assert b.salary == a.salary + 1000
    assert {x.positions[0] for x in dk if "Defense" in x.name} == {"DST"}
    assert {x.positions[0] for x in fd if "Defense" in x.name} == {"D"}


def test_missing_salary_and_off_schedule_rows_are_refused_not_zeroed():
    games = nfl.games_from_schedule(schedule_rows(), SEASON)
    rows = pool_rows("draftkings")
    rows[0]["salary"] = None
    rows[1]["team"] = "HOU"  # not playing this week
    rows[2]["opponent"] = "DAL"  # contradicts the schedule
    ath, rep = nfl.build_pool("draftkings", rows, games)
    reasons = {r["reason"] for r in rep.rejected}
    assert reasons == {
        "missing_salary",
        "team_not_on_this_weeks_schedule",
        "opponent_disagrees_with_schedule",
    }
    assert len(ath) == len(rows) - 3


def test_two_families_are_averaged_and_rescored_per_platform():
    d = directory()
    games = nfl.games_from_schedule(schedule_rows(), SEASON)
    pts = {}
    for platform in ("draftkings", "fanduel"):
        p, _ = refresh._sleeper_points(sleeper_rows(d), platform, SEASON, WEEK, NOW.isoformat())
        pts[platform] = p
    from src.identity.resolution import build_sleeper_index

    idx = build_sleeper_index(d)
    dk, rep = nfl.build_pool(
        "draftkings", pool_rows("draftkings"), games,
        sleeper_points=pts["draftkings"], directory=d, directory_index=idx,
    )  # fmt: skip
    wr = next(x for x in dk if x.name == "NE WR1")
    fams = dict(kv.split("=") for kv in wr.extra["projectionFamilies"].split(";"))
    # 4 rec, 50 yd, 0.3 TD: DraftKings full PPR = 4 + 5 + 1.8 = 10.8; FanDuel half PPR = 8.8.
    assert float(fams["sleeper_rotowire"]) == pytest.approx(10.8)
    assert pts["fanduel"][wr.extra["sleeperId"]]["points"] == pytest.approx(8.8)
    assert wr.projection == pytest.approx((float(fams["dailyfantasyfuel"]) + 10.8) / 2, abs=0.01)
    assert wr.projection_source == "auto_ensemble:dailyfantasyfuel+sleeper_rotowire"
    assert rep.identity["resolved"] > 0 and rep.identity["team_defense"] == 2 * len(GAMES)


def test_ambiguous_identity_is_quarantined_not_first_wins():
    d = directory()
    clone = dict(d["s-NEWR1"])
    d["s-NEWR1-dup"] = {
        **clone,
        "player_id": "s-NEWR1-dup",
    }  # two directory players, same name/team/pos
    from src.identity.resolution import build_sleeper_index

    games = nfl.games_from_schedule(schedule_rows(), SEASON)
    ath, rep = nfl.build_pool(
        "draftkings",
        pool_rows("draftkings"),
        games,
        directory=d,
        directory_index=build_sleeper_index(d),
    )
    wr = next(x for x in ath if x.name == "NE WR1")
    assert "sleeperId" not in wr.extra and wr.extra["identity"] in ("ambiguous", "unresolved")
    assert any(q["name"] == "NE WR1" for q in rep.quarantined_identity)
    # The athlete still exists (the salary row is real); only the join is refused.
    assert wr.salary > 0 and wr.projection is not None


def test_ruled_out_players_are_withheld_never_zeroed_and_zero_lines_excluded():
    d = directory()
    d["s-NEWR1"]["injury_status"] = "Out"
    from src.identity.resolution import build_sleeper_index

    games = nfl.games_from_schedule(schedule_rows(), SEASON)
    pts = {"s-NEWR2": {"points": 0.0, "team": "NE", "uncovered": []}}
    ath, rep = nfl.build_pool(
        "draftkings", pool_rows("draftkings"), games,
        sleeper_points=pts, directory=d, directory_index=build_sleeper_index(d),
    )  # fmt: skip
    out = next(x for x in ath if x.name == "NE WR1")
    assert out.projection is None and out.projection_source == "withheld:status_Out"
    assert out.status == "Out"
    zero = next(x for x in ath if x.name == "NE WR2")
    assert zero.projection is not None and zero.projection > 0  # a zero line is not a forecast of 0
    assert zero.extra["excludedFamily"] == "sleeper_rotowire:zero_line"


# ── refresh, storage, freshness ──────────────────────────────────────────


def test_refresh_builds_every_slate_for_both_platforms_with_no_uploads():
    out = run_refresh()
    assert out["outcome"] == "ok" and out["week"] == WEEK
    listing = refresh.list_slates("nfl", now=NOW)
    keys = {(s["platform"], s["slateKey"]) for s in listing["slates"]}
    for platform in ("draftkings", "fanduel"):
        assert {
            (platform, k) for k in ("main", "early", "afternoon", "primetime", "full_week")
        } <= keys
    main = next(
        s for s in listing["slates"] if s["platform"] == "draftkings" and s["slateKey"] == "main"
    )
    assert main["freshness"]["state"] == "CURRENT" and not main["freshness"]["locked"]
    assert main["freshness"]["cadenceMinutes"] == 120  # > 24 h to lock
    assert main["summary"]["projected"] == main["summary"]["players"]
    # Stored as an ordinary snapshot + recorded in the point-in-time ledger.
    snap = store.get_snapshot(SYSTEM_OWNER, refresh.get_row(main["autoSlateId"])["snapshotId"])
    prov = snap["body"]["slate"]["provenance"]
    assert prov["sourceKind"] == "auto_derived" and prov["platformIds"] == "unavailable"
    assert prov["slateDerivation"] == "derived_from_schedule"
    assert pit.get_slate(SYSTEM_OWNER, snap["id"])["lockAt"] == "2026-10-04T17:00:00.000000+00:00"


def test_an_unchanged_refresh_creates_no_new_snapshot():
    run_refresh()
    first = {
        s["autoSlateId"]: refresh.get_row(s["autoSlateId"])["snapshotId"]
        for s in refresh.list_slates("nfl", now=NOW)["slates"]
    }
    later = NOW + timedelta(minutes=5)
    out = run_refresh(now=later)
    assert set(out["platforms"]["draftkings"]["slates"].values()) == {"unchanged"}
    again = {k: refresh.get_row(k)["snapshotId"] for k in first}
    assert again == first


def test_a_failed_source_keeps_the_last_slate_and_says_source_error():
    run_refresh()

    def boom(platform):
        raise RuntimeError("down")

    later = NOW + timedelta(minutes=30)
    out = run_refresh(now=later, get_dff=boom)
    assert out["outcome"] == "partial"
    listing = refresh.list_slates("nfl", now=later)
    states = {s["freshness"]["state"] for s in listing["slates"]}
    assert states == {"SOURCE_ERROR"} and len(listing["slates"]) == 10


def test_missing_projection_family_is_degraded_not_silent():
    run_refresh(get_sleeper_rows=lambda s, w: None)
    listing = refresh.list_slates("nfl", now=NOW)
    s = listing["slates"][0]
    assert s["freshness"]["state"] == "DEGRADED"
    assert "projection_family_unavailable:sleeper_rotowire" in s["freshness"]["degraded"]


def test_freshness_ages_with_the_cadence_and_locks():
    run_refresh()
    main = lambda now: next(  # noqa: E731
        s for s in refresh.list_slates("nfl", now=now)["slates"]
        if s["platform"] == "draftkings" and s["slateKey"] == "main"
    )  # fmt: skip
    assert main(NOW + timedelta(hours=3))["freshness"]["state"] == "AGING"
    assert main(NOW + timedelta(hours=5))["freshness"]["state"] == "STALE"
    locked = main(datetime(2026, 10, 4, 17, 30, tzinfo=timezone.utc))["freshness"]
    assert locked["locked"] and locked["cadenceMinutes"] is None


def test_cadence_tightens_toward_lock():
    lock = datetime(2026, 10, 4, 17, 0, tzinfo=timezone.utc)
    assert refresh.cadence(lock, lock - timedelta(hours=30)) == timedelta(hours=2)
    assert refresh.cadence(lock, lock - timedelta(hours=10)) == timedelta(minutes=30)
    assert refresh.cadence(lock, lock - timedelta(hours=1)) == timedelta(minutes=10)
    assert refresh.cadence(lock, lock + timedelta(minutes=1)) is None
    assert refresh.is_due("nfl", NOW)  # nothing stored yet
    run_refresh()
    assert not refresh.is_due("nfl", NOW + timedelta(minutes=5))
    assert refresh.is_due("nfl", NOW + timedelta(hours=2, minutes=1))


# ── the optimizer consumes it; upload exports refuse it ─────────────────


def test_the_optimizer_builds_a_legal_lineup_on_the_automatic_main_slate():
    run_refresh()
    for platform in ("draftkings", "fanduel"):
        row = refresh.get_row(f"{platform}:nfl:{SEASON}:w{WEEK}:main")
        snap = store.get_snapshot(SYSTEM_OWNER, row["snapshotId"])
        rs = get_ruleset(snap["ruleset"].split("@")[0])
        athletes = [SlateAthlete(**a) for a in snap["body"]["athletes"]]
        res = optimize(rs, athletes, parse_constraints({"lineups": 2}, rs, athletes))
        assert res["status"] == "optimal" and len(res["lineups"]) == 2
        with pytest.raises(ExportError) as e:
            build_upload_csv(rs, res["lineups"], athletes)
        assert e.value.code == "PLATFORM_IDS_UNAVAILABLE"


def test_synthetic_ids_are_refused_by_every_upload_writer():
    with pytest.raises(PlatformIdsUnavailable):
        refuse_synthetic_ids(["123", "auto-ABC"])
    refuse_synthetic_ids(["12345", "67890"])  # real platform ids pass
