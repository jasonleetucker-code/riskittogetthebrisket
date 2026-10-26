"""A failed pregame-archive build raises an ops alert instead of staying silent.

Audit RPA-COL-020.  ``ensure_pregame_archive`` fails closed: when the archive
for an old NFL week cannot be built, written or read back, the raw weekly
projection log is kept and a ``pregame_projections.retained.json`` marker is
written -- but nothing told an operator, so the first real build (the first
prune after Sleeper flips to week 8) could fail unseen.

The marker is the failure state.  ``game_day_live.pregame_archive_health``
reads it, the operator-alert sweep (``ops_alerts.check_and_alert``) raises one
``pregame_archive:<league>:<season>:<week>`` alert per failing week, and the
marker's removal on a successful build is what resolves it.  These tests drive
the real prune against the isolated Game Day store with a fake alert sink and a
temporary alert-state store.
"""

from __future__ import annotations

import inspect

import pytest

from src.api import ops_alerts as oa
from src.api import user_kv
from src.ros import game_day_live as live
from tests.game_day.test_game_day_replay import (
    PRE_KICKOFF_FETCH,
    REAL_FETCH,
    SEASON,
    WEEK,
    _scenario,
    _schedule_rows,
)

SCHEDULE = _schedule_rows(_scenario("real_halftime")["espn"])
NOW = 2_000_000_000.0
CATEGORY = f"pregame_archive:{live.NFL_KEY}:{SEASON}:{WEEK}"
PRUNE_WEEK = WEEK + live.RAW_RETENTION_WEEKS + 1


@pytest.fixture(autouse=True)
def _fresh_state(monkeypatch):
    live._weekly_history_cache.clear()
    monkeypatch.setattr(live, "_archive_schedule_rows", lambda season: list(SCHEDULE))
    yield
    live._weekly_history_cache.clear()


@pytest.fixture()
def kv(tmp_path):
    path = tmp_path / "kv.sqlite"
    user_kv._SETUP_DONE.clear()
    yield path
    user_kv._SETUP_DONE.clear()


class Sink:
    """A fake alert delivery: records (to, subject, body) and always succeeds."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    def __call__(self, to: str, subject: str, body: str) -> bool:
        self.sent.append((to, subject, body))
        return True


def _sweep(kv, sink, rows):
    return oa.check_and_alert(
        pregame_archive=rows, delivery=sink, to_email="ops@example.test", kv_path=kv
    )


def _record(*fetches) -> None:
    log = live.observation_log(live.NFL_KEY, SEASON, WEEK, live.SOURCE_WEEKLY)
    for fetch in fetches:
        status, meta, content = live.weekly_to_observation(fetch)
        log.append(fetched_at=meta["observedAt"], status=status, meta=meta, content=content)


def _obs_dir():
    return live.league_week_dir(live.NFL_KEY, SEASON, WEEK) / "observations"


def _weekly_log_bytes() -> bytes:
    return live.observation_log(
        live.NFL_KEY, SEASON, WEEK, live.SOURCE_WEEKLY
    ).log_path.read_bytes()


def _no_kickoffs(monkeypatch) -> None:
    monkeypatch.setattr(live, "_archive_schedule_rows", lambda season: [])


# --- a build failure raises the alert ---------------------------------------------------


def test_a_build_failure_raises_an_ops_alert(monkeypatch, kv):
    _record(PRE_KICKOFF_FETCH, REAL_FETCH)
    _no_kickoffs(monkeypatch)
    assert live.ensure_pregame_archive(SEASON, WEEK, now=NOW) is False

    rows = live.pregame_archive_health()
    assert rows is not None and len(rows) == 1
    row = rows[0]
    assert (row["leagueKey"], row["season"], row["week"]) == (live.NFL_KEY, SEASON, WEEK)
    assert "kickoffs_unknown" in row["reason"]
    assert row["failedAt"] == live._iso(NOW)
    assert row["rawLogRetained"] is True

    sink = Sink()
    summary = _sweep(kv, sink, rows)

    assert summary["fired"] == 1 and summary["categories"] == [CATEGORY]
    assert summary["delivered"] is True
    assert len(sink.sent) == 1
    _to, subject, body = sink.sent[0]
    assert "1 warning" in subject
    assert f"{SEASON} week {WEEK}" in body and "kickoffs_unknown" in body

    # The same failure on the next sweep stays inside the cooldown.
    again = _sweep(kv, sink, live.pregame_archive_health())
    assert again["fired"] == 0 and len(sink.sent) == 1


def test_the_prune_itself_surfaces_the_failure_as_an_alert(monkeypatch, kv):
    """The real entry point (the collector's prune), not a direct call."""
    _record(PRE_KICKOFF_FETCH, REAL_FETCH)
    _no_kickoffs(monkeypatch)

    live.prune_retention(SEASON, PRUNE_WEEK)

    sink = Sink()
    summary = _sweep(kv, sink, live.pregame_archive_health())
    assert summary["categories"] == [CATEGORY]


def test_an_unreadable_archive_raises_the_alert_too(kv):
    _record(PRE_KICKOFF_FETCH, REAL_FETCH)
    path = live.pregame_archive_path(SEASON, WEEK)
    path.write_bytes(b"not gzip")

    live.prune_retention(SEASON, PRUNE_WEEK)

    rows = live.pregame_archive_health()
    assert [r["reason"] for r in rows] == ["archive_unreadable"]
    assert _sweep(kv, Sink(), rows)["categories"] == [CATEGORY]


# --- a successful build raises none and resolves a prior alert --------------------------


def test_a_successful_build_raises_no_alert(kv):
    _record(PRE_KICKOFF_FETCH, REAL_FETCH)

    live.prune_retention(SEASON, PRUNE_WEEK)

    assert live.pregame_archive_path(SEASON, WEEK).exists()
    assert not _obs_dir().exists()  # pruned only because the archive exists
    rows = live.pregame_archive_health()
    assert rows == []
    sink = Sink()
    summary = _sweep(kv, sink, rows)
    assert summary["active"] == 0 and summary["fired"] == 0 and summary["recovered"] == 0
    assert sink.sent == []


def test_a_successful_build_resolves_the_prior_alert(monkeypatch, kv):
    _record(PRE_KICKOFF_FETCH, REAL_FETCH)
    _no_kickoffs(monkeypatch)
    assert live.ensure_pregame_archive(SEASON, WEEK, now=NOW) is False
    sink = Sink()
    assert _sweep(kv, sink, live.pregame_archive_health())["fired"] == 1

    # Kickoffs become known; the hourly retry builds, writes and verifies.
    monkeypatch.setattr(live, "_archive_schedule_rows", lambda season: list(SCHEDULE))
    assert live.ensure_pregame_archive(SEASON, WEEK, now=NOW + 3601) is True

    rows = live.pregame_archive_health()
    assert rows == []
    summary = _sweep(kv, sink, rows)
    assert summary["fired"] == 0 and summary["recovered"] == 1
    assert len(sink.sent) == 2
    assert "recovered" in sink.sent[1][1].lower() and CATEGORY in sink.sent[1][2]

    # Resolved once: a further healthy sweep says nothing.
    assert _sweep(kv, sink, live.pregame_archive_health())["recovered"] == 0
    assert len(sink.sent) == 2


def test_a_stale_marker_is_cleared_once_the_archive_reads_back(kv):
    """A read-back mismatch leaves a marker beside an archive that DOES parse;
    the next pass returns True (and prunes the raw log), so the marker must go."""
    _record(PRE_KICKOFF_FETCH, REAL_FETCH)
    path = live.pregame_archive_path(SEASON, WEEK)
    path.write_bytes(b"not gzip")
    assert live.ensure_pregame_archive(SEASON, WEEK, now=NOW) is False
    marker = live._pregame_failure_path(SEASON, WEEK)
    assert marker.exists()
    sink = Sink()
    assert _sweep(kv, sink, live.pregame_archive_health())["fired"] == 1

    payload = live.build_pregame_projection_archive(SEASON, WEEK, schedule_rows=SCHEDULE, now=NOW)
    live._write_pregame_archive(path, payload)
    assert live.ensure_pregame_archive(SEASON, WEEK, now=NOW + 60) is True

    assert not marker.exists()
    assert live.pregame_archive_health() == []
    assert _sweep(kv, sink, live.pregame_archive_health())["recovered"] == 1


# --- the raw log is still retained on failure -------------------------------------------


def test_the_raw_log_is_still_retained_on_failure(monkeypatch, kv):
    _record(PRE_KICKOFF_FETCH, REAL_FETCH)
    before = _weekly_log_bytes()
    _no_kickoffs(monkeypatch)

    removed = live.prune_retention(SEASON, PRUNE_WEEK)

    assert str(_obs_dir()) not in removed
    assert _obs_dir().is_dir()
    assert _weekly_log_bytes() == before  # the evidence is byte-identical
    assert not live.pregame_archive_path(SEASON, WEEK).exists()
    marker = live._pregame_failure_path(SEASON, WEEK)
    assert marker.exists() and "kickoffs_unknown" in marker.read_text()
    # Raising the alert does not change any of that.
    _sweep(kv, Sink(), live.pregame_archive_health())
    assert _obs_dir().is_dir() and _weekly_log_bytes() == before


# --- "not checked" is never "healthy" ---------------------------------------------------


def test_an_unreadable_store_is_unknown_not_recovered(monkeypatch, kv):
    _record(PRE_KICKOFF_FETCH, REAL_FETCH)
    _no_kickoffs(monkeypatch)
    live.ensure_pregame_archive(SEASON, WEEK, now=NOW)
    sink = Sink()
    assert _sweep(kv, sink, live.pregame_archive_health())["fired"] == 1

    unchecked = _sweep(kv, sink, None)
    assert unchecked["recovered"] == 0 and len(sink.sent) == 1


def test_no_game_day_store_is_reported_as_not_checked():
    assert not (live.LIVE_ROOT / live.NFL_KEY).exists()
    assert live.pregame_archive_health() is None


# --- the sweep is wired to the reader ---------------------------------------------------


def test_the_signal_alert_sweep_passes_the_archive_health_to_the_alerter(monkeypatch):
    import server  # noqa: PLC0415

    assert server._pregame_archive_health() is None  # nothing on disk: not checked

    _record(PRE_KICKOFF_FETCH, REAL_FETCH)
    _no_kickoffs(monkeypatch)
    live.ensure_pregame_archive(SEASON, WEEK, now=NOW)
    rows = server._pregame_archive_health()
    assert rows == live.pregame_archive_health() and len(rows) == 1

    # The producer is useless unless the cron that calls the alerter hands it over.
    source = inspect.getsource(server.run_signal_alerts)
    assert "pregame_archive=await run_in_threadpool(_pregame_archive_health)" in source
