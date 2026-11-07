"""Pre-kickoff point-in-time capture hardening (owner directive 2026-11-07, Part 7).

Three gaps in the Game Day prediction archive, each pinned here:

* **D** — only one snapshot per week, taken before the week's FIRST kickoff
  (~Wednesday evening), so Sunday/Monday games were archived against
  four-day-old inputs.  A second kind, ``pregame_late``, is captured before
  the first SUNDAY kickoff resolved from the same nflverse slate, at its own
  immutable path, with the same refusal and provenance rules.
* **B** — no injury state was archived.  Each capture run now records the
  injury report as known at capture time (the canonical as-known ledger,
  ``src/nfl_data/injury_history.py``), with its content hash and fetch time,
  or ``unavailable`` with a reason — never an empty "no injuries" list.
* **C** — no record of which canonical board was current.  Each run records
  the board's existing identity (payload sha256 + scrapeTimestamp), labelled
  as NOT an input of the estimates, which come from the projection ensemble.

Network-free: every Sleeper / schedule payload is a literal, the clock is
frozen through the modules' own ``datetime`` seam, and every store is a
``tmp_path``.
"""

from __future__ import annotations

import configparser
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.nfl_data import injury_history as ih
from src.ros import game_day_archive as gda
from src.ros import game_day_capture as gdc
from src.ros.game_day_archive import (
    GameDayArchiveError,
    PlayerPointEstimate,
    WeeklyPredictionSnapshot,
    load_capture_contexts,
    load_snapshot,
    load_snapshots_for_week,
    record_capture_context,
    record_snapshot,
)
from src.ros.game_day_capture import (
    LATE_CAPTURE_WINDOW_HOURS,
    PREGAME_LATE_FIRST_WEEK,
    board_context_from_payload,
    build_capture,
    combine_exit_codes,
    first_kickoff_utc,
    first_sunday_kickoff_utc,
    injury_context_from_as_known,
    late_pregame_window_state,
    pregame_capture_gaps,
    snapshot_provenance,
)

_REPO = Path(__file__).resolve().parents[2]
_UTC = timezone.utc

# ── a real-shaped 2026 Week 10 slate (US-Eastern, as nflverse publishes) ──
# Thursday 8:15pm ET opener; DST ended 2026-11-01, so ET = UTC-5.
WEEK10 = [
    {"season": 2026, "week": 10, "gameday": "2026-11-12", "gametime": "20:15"},
    {"season": 2026, "week": 10, "gameday": "2026-11-15", "gametime": "13:00"},
    {"season": 2026, "week": 10, "gameday": "2026-11-15", "gametime": "16:25"},
    {"season": 2026, "week": 10, "gameday": "2026-11-16", "gametime": "20:15"},
    {"season": 2026, "week": 11, "gameday": "2026-11-19", "gametime": "20:15"},
]
THURSDAY_KICKOFF = datetime(2026, 11, 13, 1, 15, tzinfo=_UTC)
SUNDAY_KICKOFF = datetime(2026, 11, 15, 18, 0, tzinfo=_UTC)


def _at(iso: str) -> datetime:
    return datetime.fromisoformat(iso).astimezone(_UTC)


# ── D: the first Sunday kickoff comes from the slate, not a weekday ──


def test_first_sunday_kickoff_skips_the_thursday_opener():
    assert first_kickoff_utc(WEEK10, season=2026, week=10) == THURSDAY_KICKOFF
    assert first_sunday_kickoff_utc(WEEK10, season=2026, week=10) == (SUNDAY_KICKOFF, None)


def test_a_london_morning_game_is_the_sunday_kickoff():
    rows = [*WEEK10, {"season": 2026, "week": 10, "gameday": "2026-11-15", "gametime": "09:30"}]
    kickoff, reason = first_sunday_kickoff_utc(rows, season=2026, week=10)
    assert (kickoff, reason) == (datetime(2026, 11, 15, 14, 30, tzinfo=_UTC), None)


def test_saturday_games_are_not_the_sunday_kickoff():
    rows = [
        {"season": 2026, "week": 16, "gameday": "2026-12-24", "gametime": "20:15"},
        {"season": 2026, "week": 16, "gameday": "2026-12-26", "gametime": "16:30"},  # Sat
        {"season": 2026, "week": 16, "gameday": "2026-12-27", "gametime": "13:00"},  # Sun
    ]
    kickoff, _ = first_sunday_kickoff_utc(rows, season=2026, week=16)
    assert kickoff == datetime(2026, 12, 27, 18, 0, tzinfo=_UTC)


def test_the_sunday_kickoff_is_localised_through_dst():
    # 2026-10-25 is EDT (UTC-4); 2026-11-01 is the first EST Sunday (UTC-5).
    edt = [{"season": 2026, "week": 7, "gameday": "2026-10-25", "gametime": "13:00"}]
    est = [{"season": 2026, "week": 8, "gameday": "2026-11-01", "gametime": "13:00"}]
    assert first_sunday_kickoff_utc(edt, season=2026, week=7)[0].hour == 17
    assert first_sunday_kickoff_utc(est, season=2026, week=8)[0].hour == 18


def test_no_rows_is_unknown_and_no_sunday_is_not_applicable():
    # The two reasons mean opposite things and must not collapse.
    assert first_sunday_kickoff_utc([], season=2026, week=10) == (
        None,
        "no_schedule_rows_for_week",
    )
    thursday_only = [WEEK10[0]]
    assert first_sunday_kickoff_utc(thursday_only, season=2026, week=10) == (
        None,
        "no_sunday_game",
    )


@pytest.mark.parametrize(
    "now, state",
    [
        ("2026-11-11T20:00:00+00:00", "early"),  # Wednesday
        ("2026-11-15T05:59:00+00:00", "early"),  # 12h01m before Sunday
        ("2026-11-15T06:00:00+00:00", "open"),
        ("2026-11-15T17:59:00+00:00", "open"),
        ("2026-11-15T18:00:00+00:00", "closed"),  # at kickoff is not pregame
    ],
)
def test_late_window_states(now, state):
    got, _why = late_pregame_window_state(
        season=2026, week=10, sunday_kickoff=SUNDAY_KICKOFF, kickoff_reason=None, now=_at(now)
    )
    assert got == state


def test_late_window_unknown_and_not_applicable():
    unknown, _ = late_pregame_window_state(
        season=2026, week=10, sunday_kickoff=None, kickoff_reason="no_schedule_rows_for_week"
    )
    assert unknown == "unknown"
    no_sunday, _ = late_pregame_window_state(
        season=2026, week=10, sunday_kickoff=None, kickoff_reason="no_sunday_game"
    )
    assert no_sunday == "not_applicable"
    before_floor, why = late_pregame_window_state(
        season=2026,
        week=PREGAME_LATE_FIRST_WEEK[1] - 1,
        sunday_kickoff=SUNDAY_KICKOFF,
        kickoff_reason=None,
        now=SUNDAY_KICKOFF + timedelta(hours=1),
    )
    assert before_floor == "not_applicable" and "never collected" in why


def _timer_fire_hours() -> tuple[list[int], int]:
    parser = configparser.ConfigParser(interpolation=None)
    parser.read_string(
        (_REPO / "deploy/systemd/dynasty-game-day-capture.timer.template").read_text(
            encoding="utf-8"
        )
    )
    on_calendar = parser["Timer"]["OnCalendar"]  # e.g. "*-*-* 00,04,...:00:00 UTC"
    clock = on_calendar.split()[1]
    hours, minute, _second = clock.split(":")
    return [int(h) for h in hours.split(",")], int(minute)


def _fires_in(start: datetime, end: datetime) -> int:
    hours, minute = _timer_fire_hours()
    count = 0
    day = (start - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    while day <= end:
        for h in hours:
            fire = day.replace(hour=h, minute=minute)
            if start <= fire < end:
                count += 1
        day += timedelta(days=1)
    return count


def test_every_late_window_contains_three_timer_firings_whatever_the_kickoff_minute():
    """The existing 4-hourly timer lands in the new window: no schedule change.

    Every kickoff minute of a day is tried; the half-open window
    [kickoff - 12h, kickoff) holds exactly three firings, so the late capture
    survives two consecutive failed runs.
    """
    base = datetime(2026, 11, 15, 0, 0, tzinfo=_UTC)
    for minute in range(24 * 60):
        kickoff = base + timedelta(minutes=minute)
        window = timedelta(hours=LATE_CAPTURE_WINDOW_HOURS)
        assert _fires_in(kickoff - window, kickoff) == 3, kickoff


def test_week10_late_window_has_firings_before_sunday():
    window = timedelta(hours=LATE_CAPTURE_WINDOW_HOURS)
    assert _fires_in(SUNDAY_KICKOFF - window, SUNDAY_KICKOFF) == 3
    early = timedelta(hours=gdc.CAPTURE_WINDOW_HOURS)
    assert _fires_in(THURSDAY_KICKOFF - early, THURSDAY_KICKOFF) >= 7


def test_the_service_runs_both_pregame_kinds_in_one_process():
    text = (_REPO / "deploy/systemd/dynasty-game-day-capture.service.template").read_text(
        encoding="utf-8"
    )
    exec_lines = [ln for ln in text.splitlines() if ln.startswith("ExecStart=")]
    assert len(exec_lines) == 1, "two ExecStart lines would stop the second on exit 3"
    assert "--capture-kind pregame --capture-kind pregame_late" in exec_lines[0]


@pytest.mark.parametrize(
    "codes, combined",
    [
        ([2, 2], 2),
        ([0, 2], 0),
        ([2, 0], 0),
        ([0, 1], 1),
        ([1, 3], 3),
        ([3, 0], 3),
        ([2, 3], 3),
    ],
)
def test_one_kind_never_masks_the_other(codes, combined):
    assert combine_exit_codes(codes) == combined


class _Snap:
    def __init__(self, team_id, captured_at, capture_kind):
        self.team_id = team_id
        self.captured_at = captured_at
        self.capture_kind = capture_kind


def test_late_gaps_ignore_the_early_snapshot_and_post_sunday_captures():
    snaps = [
        _Snap("1", "2026-11-11T20:00:05+00:00", "pregame"),
        _Snap("2", "2026-11-15T18:00:00+00:00", "pregame_late"),  # at kickoff
        _Snap("3", "2026-11-15T08:00:05+00:00", "pregame_late"),
    ]
    assert pregame_capture_gaps(
        expected_team_ids=[1, 2, 3],
        snapshots=snaps,
        first_kickoff=SUNDAY_KICKOFF,
        capture_kind="pregame_late",
    ) == ["1", "2"]
    # The default kind is unchanged: only the early snapshot counts for it.
    assert (
        pregame_capture_gaps(expected_team_ids=[1], snapshots=snaps, first_kickoff=THURSDAY_KICKOFF)
        == []
    )


def test_build_does_not_refuse_a_late_capture_after_thursday_scored():
    # By Sunday Thursday's game has scored; only the `pregame` kind is
    # score-gated (the schedule gate in the script protects the late kind).
    from tests.ros.test_game_day_capture import _LEAGUE, _PLAYERS_META, _ROSTER

    scored = [{"roster_id": 7, "points": 14.2, "players_points": {"qb1": 14.2}}]
    with pytest.raises(gdc.GameDayCaptureRefusal):
        build_capture(
            league_key="dynasty_main",
            season=2026,
            week=10,
            capture_kind="pregame",
            league_payload=_LEAGUE,
            rosters=[_ROSTER],
            matchups=scored,
            players_meta=_PLAYERS_META,
        )
    build = build_capture(
        league_key="dynasty_main",
        season=2026,
        week=10,
        capture_kind="pregame_late",
        league_payload=_LEAGUE,
        rosters=[_ROSTER],
        matchups=scored,
        players_meta=_PLAYERS_META,
    )
    assert build.capture_kind == "pregame_late" and len(build.teams) == 1


# ── D: the archive keeps the two kinds apart, immutably ──────────────

_ROSTER_ROWS = (
    PlayerPointEstimate(player_id="p1", position="QB", is_lineup_eligible=True),
    PlayerPointEstimate(
        player_id="p2",
        position="WR",
        is_lineup_eligible=True,
        point_estimate=11.5,
        estimate_source="ros_ensemble:PRESEASON_FULL_SEASON:equal_family_mean",
    ),
)


def _record(tmp_path, kind, **extra):
    return record_snapshot(
        league_key="dynasty_main",
        season=2026,
        week=10,
        team_id="1",
        capture_kind=kind,
        scoring_config_id="sf1:abc",
        starter_slots=("QB", "WR"),
        roster=_ROSTER_ROWS,
        base_dir=tmp_path,
        **extra,
    )


def test_late_snapshot_has_its_own_file_and_never_touches_the_early_one(tmp_path):
    _record(tmp_path, "pregame")
    week_dir = tmp_path / "2026" / "dynasty_main" / "week_10"
    early_bytes = (week_dir / "1_pregame.json").read_bytes()

    _record(tmp_path, "pregame_late")
    assert sorted(p.name for p in week_dir.iterdir()) == ["1_pregame.json", "1_pregame_late.json"]
    assert (week_dir / "1_pregame.json").read_bytes() == early_bytes
    with pytest.raises(GameDayArchiveError):
        _record(tmp_path, "pregame_late")
    assert load_snapshot("dynasty_main", 2026, 10, "1", "pregame", base_dir=tmp_path) is not None
    kinds = [
        s.capture_kind for s in load_snapshots_for_week("dynasty_main", 2026, 10, base_dir=tmp_path)
    ]
    assert kinds == ["pregame", "pregame_late"]


def test_an_existing_file_is_refused_not_replaced(tmp_path):
    # Exclusive create: a file that appeared after any exists() check (an
    # overlapping manual run) is never overwritten.
    week_dir = tmp_path / "2026" / "dynasty_main" / "week_10"
    week_dir.mkdir(parents=True)
    (week_dir / "1_pregame_late.json").write_text("EARLIER", encoding="utf-8")
    with pytest.raises(GameDayArchiveError):
        gda._write_once(week_dir / "1_pregame_late.json", "LATER")
    assert (week_dir / "1_pregame_late.json").read_text(encoding="utf-8") == "EARLIER"


def test_provenance_round_trips_and_is_absent_when_not_recorded(tmp_path):
    prov = {"schema": "game-day-snapshot-provenance/v1", "precedesKickoffUtc": "x"}
    stored = _record(tmp_path, "pregame_late", provenance=prov)
    loaded = load_snapshot("dynasty_main", 2026, 10, "1", "pregame_late", base_dir=tmp_path)
    assert loaded == stored and loaded.provenance == prov

    plain = WeeklyPredictionSnapshot(
        league_key="dynasty_main",
        season=2026,
        week=10,
        team_id="1",
        capture_kind="pregame",
        captured_at="2026-11-11T20:00:05+00:00",
        scoring_config_id="sf1:abc",
        starter_slots=("QB",),
        roster=_ROSTER_ROWS,
    )
    # A snapshot without provenance keeps the pre-2026-11-07 shape exactly.
    assert "provenance" not in plain.to_dict()
    assert WeeklyPredictionSnapshot.from_dict(plain.to_dict()).provenance is None


# ── B / C: the per-run capture context ───────────────────────────────


def _ok_blocks():
    return (
        {"state": "unavailable", "reason": "injury_history_store_missing"},
        {"state": "known", "payloadSha256": "f" * 64},
    )


def test_context_files_are_per_run_immutable_and_outside_league_week_dirs(tmp_path):
    injuries, board = _ok_blocks()
    p1, sha1, rec1 = record_capture_context(
        season=2026,
        week=10,
        capture_kind="pregame_late",
        injuries=injuries,
        canonical_board=board,
        run_id="r1",
        base_dir=tmp_path,
    )
    p2, _sha2, _ = record_capture_context(
        season=2026,
        week=10,
        capture_kind="pregame",
        injuries=injuries,
        canonical_board=board,
        base_dir=tmp_path,
    )
    assert p1 != p2 and p1.parent == tmp_path / "2026" / "week_10"
    assert hashlib.sha256(p1.read_bytes()).hexdigest() == sha1
    assert rec1["capturedAt"] and rec1["schema"] == gda.CONTEXT_SCHEMA
    assert [
        c["runId"]
        for c in load_capture_contexts(2026, 10, capture_kind="pregame_late", base_dir=tmp_path)
    ] == ["r1"]
    assert len(load_capture_contexts(2026, 10, base_dir=tmp_path)) == 2
    assert gda.CONTEXT_ROOT.parent == gda.ARCHIVE_ROOT.parent
    assert gda.CONTEXT_ROOT != gda.ARCHIVE_ROOT


@pytest.mark.parametrize("bad", [None, {}, {"state": "empty"}, {"entries": []}])
def test_a_context_block_must_say_known_or_unavailable(tmp_path, bad):
    _, board = _ok_blocks()
    with pytest.raises(GameDayArchiveError):
        record_capture_context(
            season=2026,
            week=10,
            capture_kind="pregame",
            injuries=bad,
            canonical_board=board,
            base_dir=tmp_path,
        )


def _injury_entry(eid, name, status):
    return {
        "espnAthleteId": eid,
        "fullName": name,
        "position": "WR",
        "teamAbbrev": "BUF",
        "status": status,
    }


def _ledger(tmp_path, fetches):
    """Write real injury-history records through the canonical owner."""
    base = tmp_path / "injury_history"
    for when, entries in fetches:
        ih.capture(
            entries,
            fetched_at=_at(when).timestamp(),
            base=base,
            directory={},
            directory_provenance={"path": "fixture"},
            recorded_at=when,
        )
    return base


def test_injury_context_is_the_as_known_report_with_its_hash(tmp_path):
    base = _ledger(
        tmp_path,
        [
            ("2026-11-15T04:10:00+00:00", [_injury_entry("9001", "Alpha", "Questionable")]),
            ("2026-11-15T12:10:00+00:00", [_injury_entry("9001", "Alpha", "Out")]),
        ],
    )
    block = injury_context_from_as_known(ih.as_known_at(_at("2026-11-15T08:00:00+00:00"), base))
    assert block["state"] == "known"
    # No lookahead: the 12:10 fetch is after the 08:00 capture.
    assert block["snapshotFetchedAt"] == "2026-11-15T04:10:00+00:00"
    assert [e["status"] for e in block["entries"]] == ["Questionable"]
    assert block["contentVerified"] is True
    assert block["contentSha256"] == ih.content_sha256(ih.provider_entries(block["entries"]))
    assert block["provider"] == "espn" and block["entryCount"] == 1
    assert block["observedAgeSeconds"] == pytest.approx(3 * 3600 + 50 * 60)


def test_a_proven_empty_report_is_known_empty_not_unavailable(tmp_path):
    base = _ledger(tmp_path, [("2026-11-15T04:10:00+00:00", [])])
    block = injury_context_from_as_known(ih.as_known_at(_at("2026-11-15T08:00:00+00:00"), base))
    assert block["state"] == "known" and block["entryCount"] == 0 and block["entries"] == []


@pytest.mark.parametrize(
    "as_known, error, reason",
    [
        (None, "injury_history_store_missing", "injury_history_store_missing"),
        (
            {"state": "unavailable", "reason": "no_capture_at_or_before"},
            None,
            "no_capture_at_or_before",
        ),
        (None, None, "as_known_result_missing"),
        ({"state": "known", "snapshot": {"key": "k"}}, None, "injury_snapshot_without_entries"),
    ],
)
def test_missing_injury_evidence_is_unavailable_never_an_empty_list(as_known, error, reason):
    block = injury_context_from_as_known(as_known, error=error)
    assert block == {"state": "unavailable", "reason": reason, "owner": gdc.INJURY_CONTEXT_OWNER}
    assert "entries" not in block


def test_a_tampered_injury_copy_is_recorded_unverified_not_repaired(tmp_path):
    base = _ledger(tmp_path, [("2026-11-15T04:10:00+00:00", [_injury_entry("9001", "A", "Out")])])
    known = ih.as_known_at(_at("2026-11-15T08:00:00+00:00"), base)
    known["snapshot"]["entries"][0]["status"] = "Active"
    block = injury_context_from_as_known(known)
    assert block["state"] == "known" and block["contentVerified"] is False


def test_board_context_is_the_existing_payload_identity_and_not_an_input():
    data = b'{"scrapeTimestamp": "2026-11-15T06:05:00+00:00"}'
    found = (_REPO / "exports/latest/dynasty_data_2026-11-15.json", json.loads(data), 1.9, data)
    block = board_context_from_payload(found, stale_budget_hours=6, repo_root=_REPO)
    assert block["state"] == "known"
    assert block["payloadSha256"] == hashlib.sha256(data).hexdigest()
    assert block["source"] == "exports/latest/dynasty_data_2026-11-15.json"
    assert block["scrapeTimestamp"] == "2026-11-15T06:05:00+00:00"
    assert block["stale"] is False and block["usedByEstimates"] is False
    stale = board_context_from_payload((*found[:2], 9.0, data), stale_budget_hours=6)
    assert stale["stale"] is True
    unknown_age = board_context_from_payload((*found[:2], None, data), stale_budget_hours=6)
    assert unknown_age["stale"] is None and unknown_age["payloadAgeHours"] is None


def test_board_context_unavailable_states():
    assert board_context_from_payload(None, stale_budget_hours=6)["reason"] == (
        "no_served_board_payload_on_this_host"
    )
    errored = board_context_from_payload(None, stale_budget_hours=None, error="OSError: x")
    assert errored["state"] == "unavailable" and errored["reason"] == "OSError: x"


def test_snapshot_provenance_names_the_kickoff_and_the_real_inputs():
    from tests.ros.test_game_day_capture import _LEAGUE, _PLAYERS_META, _ROSTER

    build = build_capture(
        league_key="dynasty_main",
        season=2026,
        week=10,
        capture_kind="pregame_late",
        league_payload=_LEAGUE,
        rosters=[_ROSTER],
        matchups=[],
        players_meta=_PLAYERS_META,
        sources_loaded=("clayProjections",),
        sources_unavailable=("idpShowProjections",),
    )
    prov = snapshot_provenance(
        build,
        precedes_kickoff=SUNDAY_KICKOFF,
        precedes_basis="first_sunday_kickoff_of_week",
        injuries={"state": "unavailable", "reason": "no_capture_at_or_before"},
        canonical_board={"state": "known", "payloadSha256": "a" * 64, "usedByEstimates": False},
        capture_context={"state": "known", "path": "x.json", "sha256": "b" * 64},
        code_revision={"sha": "deadbeef", "reason": None},
    )
    assert prov["precedesKickoffUtc"] == "2026-11-15T18:00:00+00:00"
    assert prov["projectionInputs"]["sourcesLoaded"] == ["clayProjections"]
    assert prov["projectionInputs"]["sourcesUnavailable"] == ["idpShowProjections"]
    assert prov["injuries"] == {"state": "unavailable", "reason": "no_capture_at_or_before"}
    assert prov["canonicalBoardAtCapture"]["usedByEstimates"] is False
    assert prov["codeRevision"]["sha"] == "deadbeef"


# ── end to end through the CLI ───────────────────────────────────────

_ROSTER_8 = {"roster_id": 8, "players": ["wr1", "te1"]}


def _freeze(monkeypatch, cap, iso):
    fixed = _at(iso)

    class _Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed if tz is None else fixed.astimezone(tz)

    for module in (gdc, gda, cap):
        monkeypatch.setattr(module, "datetime", _Frozen)


def _cli(monkeypatch, tmp_path, *, schedule=WEEK10, matchups=(), injury_dir=None):
    from scripts import capture_game_day_predictions as cap
    from tests.ros.test_game_day_capture import _LEAGUE, _PLAYERS_META, _ROSTER

    monkeypatch.setattr(gda, "ARCHIVE_ROOT", tmp_path / "predictions")
    monkeypatch.setattr(gda, "CONTEXT_ROOT", tmp_path / "capture_context")
    cfg = SimpleNamespace(key="dynasty_main", roster_settings=None)
    monkeypatch.setattr(
        cap.league_registry, "get_league_by_key", lambda k: cfg if k == "dynasty_main" else None
    )
    monkeypatch.setattr(cap.league_registry, "get_sleeper_league_id", lambda k: "L1")
    monkeypatch.setattr(cap.sleeper_client, "fetch_league", lambda lid: _LEAGUE)
    monkeypatch.setattr(cap.sleeper_client, "fetch_rosters", lambda lid: [_ROSTER, _ROSTER_8])
    monkeypatch.setattr(cap.sleeper_client, "fetch_matchups", lambda lid, wk: list(matchups))
    monkeypatch.setattr(cap.sleeper_client, "fetch_nfl_players", lambda: _PLAYERS_META)
    monkeypatch.setattr(
        cap,
        "_load_schedule",
        lambda season: (schedule, None)
        if schedule is not None
        else (None, "schedule_unavailable: ConnectionError"),
    )
    monkeypatch.setattr(
        cap,
        "_resolve_estimates",
        lambda season, scoring: ({}, None, ("clayProjections",), ("idpShowProjections",)),
    )
    data = b'{"scrapeTimestamp": "2026-11-15T06:05:00+00:00"}'
    monkeypatch.setattr(
        cap,
        "_board_block",
        lambda: board_context_from_payload(
            (Path("dynasty_data_test.json"), json.loads(data), 1.9, data), stale_budget_hours=6
        ),
    )
    monkeypatch.setattr(cap, "_code_revision", lambda: {"sha": "abc123", "reason": None})
    monkeypatch.setenv("RISKIT_INJURY_HISTORY_DIR", str(injury_dir or tmp_path / "no_store"))
    return cap


def _main(monkeypatch, cap, *argv, week=10):
    monkeypatch.setattr(
        sys,
        "argv",
        ["capture", "--league", "dynasty_main", "--season", "2026", "--week", str(week), *argv],
    )
    return cap.main()


_BOTH = ("--capture-kind", "pregame", "--capture-kind", "pregame_late")


def _files(tmp_path, pattern):
    return sorted(
        p.name for p in (tmp_path / "predictions/2026/dynasty_main/week_10").glob(pattern)
    )


def test_week10_end_to_end_early_then_late(monkeypatch, tmp_path):
    injury_dir = _ledger(
        tmp_path,
        [
            ("2026-11-11T16:10:00+00:00", [_injury_entry("9001", "Alpha", "Questionable")]),
            ("2026-11-15T04:10:00+00:00", [_injury_entry("9001", "Alpha", "Out")]),
        ],
    )
    cap = _cli(monkeypatch, tmp_path, injury_dir=injury_dir)

    # Wednesday 20:00 UTC: early window open, late window not yet.
    _freeze(monkeypatch, cap, "2026-11-11T20:00:00+00:00")
    assert _main(monkeypatch, cap, *_BOTH) == 0
    assert _files(tmp_path, "*_pregame.json") == ["7_pregame.json", "8_pregame.json"]
    assert _files(tmp_path, "*_pregame_late.json") == []
    early = {
        n: (tmp_path / "predictions/2026/dynasty_main/week_10" / n).read_bytes()
        for n in _files(tmp_path, "*_pregame.json")
    }

    # Sunday 08:00 UTC, Thursday already scored: early closed (and captured),
    # late window open.
    monkeypatch.setattr(
        cap.sleeper_client,
        "fetch_matchups",
        lambda lid, wk: [{"roster_id": 7, "points": 21.0, "players_points": {"qb1": 21.0}}],
    )
    _freeze(monkeypatch, cap, "2026-11-15T08:00:00+00:00")
    assert _main(monkeypatch, cap, *_BOTH) == 0
    assert _files(tmp_path, "*_pregame_late.json") == ["7_pregame_late.json", "8_pregame_late.json"]
    for name, raw in early.items():  # the early evidence is untouched
        assert (tmp_path / "predictions/2026/dynasty_main/week_10" / name).read_bytes() == raw

    late = load_snapshot("dynasty_main", 2026, 10, "7", "pregame_late")
    assert late.captured_at == "2026-11-15T08:00:00+00:00"
    prov = late.provenance
    assert prov["precedesKickoffUtc"] == SUNDAY_KICKOFF.isoformat()
    assert prov["precedesKickoffBasis"] == "first_sunday_kickoff_of_week"
    assert prov["injuries"]["state"] == "known"
    assert prov["injuries"]["snapshotFetchedAt"] == "2026-11-15T04:10:00+00:00"
    assert prov["canonicalBoardAtCapture"]["usedByEstimates"] is False
    assert prov["codeRevision"] == {"sha": "abc123", "reason": None}

    # The referenced context file exists, matches its hash, and carries the
    # full injury report as known at 08:00 (not the Wednesday one).
    ref = prov["captureContext"]
    ctx_path = Path(ref["path"])
    if not ctx_path.is_absolute():
        ctx_path = _REPO / ctx_path
    assert hashlib.sha256(ctx_path.read_bytes()).hexdigest() == ref["sha256"]
    ctx = json.loads(ctx_path.read_text(encoding="utf-8"))
    assert ctx["captureKind"] == "pregame_late"
    assert [e["status"] for e in ctx["injuries"]["entries"]] == ["Out"]
    early_snap = load_snapshot("dynasty_main", 2026, 10, "7", "pregame")
    assert early_snap.provenance["precedesKickoffUtc"] == THURSDAY_KICKOFF.isoformat()
    assert early_snap.provenance["injuries"]["snapshotFetchedAt"] == "2026-11-11T16:10:00+00:00"

    # A re-run in the same window adds no snapshot and no context file.
    contexts_before = load_capture_contexts(2026, 10)
    _freeze(monkeypatch, cap, "2026-11-15T12:00:00+00:00")
    assert _main(monkeypatch, cap, *_BOTH) == 0
    assert load_capture_contexts(2026, 10) == contexts_before

    # After Sunday kickoff: both kinds closed and captured -> success, not a page.
    _freeze(monkeypatch, cap, "2026-11-15T19:00:00+00:00")
    assert _main(monkeypatch, cap, *_BOTH) == 0


def test_a_missed_late_window_pages_and_the_early_one_does_not_mask_it(monkeypatch, tmp_path):
    cap = _cli(monkeypatch, tmp_path)
    _freeze(monkeypatch, cap, "2026-11-11T20:00:00+00:00")
    assert _main(monkeypatch, cap, "--capture-kind", "pregame") == 0
    _freeze(monkeypatch, cap, "2026-11-15T19:00:00+00:00")
    assert _main(monkeypatch, cap, *_BOTH) == 3
    assert _files(tmp_path, "*_pregame_late.json") == []  # never reconstructed


def test_late_capture_with_an_unknown_sunday_kickoff_is_refused(monkeypatch, tmp_path):
    cap = _cli(monkeypatch, tmp_path, schedule=None)
    _freeze(monkeypatch, cap, "2026-11-15T08:00:00+00:00")
    assert _main(monkeypatch, cap, "--capture-kind", "pregame_late") == 1
    assert _files(tmp_path, "*") == []


def test_late_capture_before_its_first_week_is_not_applicable(monkeypatch, tmp_path):
    rows = [{**r, "week": 9} for r in WEEK10 if r["week"] == 10]
    cap = _cli(monkeypatch, tmp_path, schedule=rows)
    _freeze(monkeypatch, cap, "2026-11-15T19:00:00+00:00")
    assert _main(monkeypatch, cap, "--capture-kind", "pregame_late", week=9) == 2


def test_a_missing_injury_store_is_recorded_and_the_roster_still_captured(monkeypatch, tmp_path):
    cap = _cli(monkeypatch, tmp_path)  # RISKIT_INJURY_HISTORY_DIR -> nonexistent
    _freeze(monkeypatch, cap, "2026-11-15T08:00:00+00:00")
    assert _main(monkeypatch, cap, "--capture-kind", "pregame_late") == 0
    late = load_snapshot("dynasty_main", 2026, 10, "8", "pregame_late")
    assert late.provenance["injuries"] == {
        "state": "unavailable",
        "reason": "injury_history_store_missing",
    }
    (ctx,) = load_capture_contexts(2026, 10, capture_kind="pregame_late")
    assert ctx["injuries"]["state"] == "unavailable"
    assert "entries" not in ctx["injuries"]


def test_default_invocation_is_still_the_single_pregame_kind(monkeypatch, tmp_path):
    cap = _cli(monkeypatch, tmp_path)
    _freeze(monkeypatch, cap, "2026-11-11T20:00:00+00:00")
    assert _main(monkeypatch, cap) == 0
    assert _files(tmp_path, "*_pregame.json") == ["7_pregame.json", "8_pregame.json"]
    assert _files(tmp_path, "*_pregame_late.json") == []


def test_verify_reports_each_kind(monkeypatch, tmp_path, capsys):
    cap = _cli(monkeypatch, tmp_path)
    _freeze(monkeypatch, cap, "2026-11-11T20:00:00+00:00")
    assert _main(monkeypatch, cap) == 0
    _freeze(monkeypatch, cap, "2026-11-15T19:00:00+00:00")
    assert _main(monkeypatch, cap, "--verify") == 3  # late window passed, nothing captured
    out = capsys.readouterr().out
    assert "pregame_late" in out and "GAP dynasty_main" in out
    assert _files(tmp_path, "*_pregame_late.json") == []  # --verify writes nothing


def test_journal_stage_parser_still_recognises_the_pregame_lines_and_the_late_ones(
    monkeypatch, tmp_path, capsys
):
    """deploy/diagnostics/performance_inventory.py fullmatches the capture
    script's journal lines; the `pregame` wording must stay byte-identical and
    the late kind's lines must be recognised rather than counted unknown."""
    import importlib.util
    import re

    spec = importlib.util.spec_from_file_location(
        "perf_inventory_probe", _REPO / "deploy/diagnostics/performance_inventory.py"
    )
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)
    patterns = probe.STAGE_PATTERNS["game_day_capture"]

    def stage(line):
        return next((k for k, p in patterns.items() if re.fullmatch(p, line)), None)

    cap = _cli(monkeypatch, tmp_path)
    _freeze(monkeypatch, cap, "2026-11-15T19:00:00+00:00")
    assert _main(monkeypatch, cap, *_BOTH) == 3
    err = capsys.readouterr().err.splitlines()
    assert stage("REFUSED: first kickoff has passed.") == "kickoff_passed"
    assert "REFUSED: first Sunday kickoff has passed." in err
    assert stage("REFUSED: first Sunday kickoff has passed.") == "late_kickoff_passed"

    _freeze(monkeypatch, cap, "2026-11-15T08:00:00+00:00")
    assert _main(monkeypatch, cap, "--capture-kind", "pregame_late") == 0
    out = capsys.readouterr().out.splitlines()
    started = [ln for ln in out if ln.startswith("Capturing ")]
    assert started and all(stage(ln) == "capture_started" for ln in started)
    assert stage("Done.") == "completed" and "Done." in out
