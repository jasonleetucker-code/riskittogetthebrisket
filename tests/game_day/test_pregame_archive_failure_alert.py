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

import logging
import pathlib
import shutil
import zlib

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
    """An unreadable archive leaves a marker; once an archive that DOES parse is
    in place the next pass returns True (and prunes the raw log), so the marker
    must go.  (A read-back MISMATCH marker is different: the archive beside it
    is not trusted -- see ``test_pregame_archive_readback_recheck.py``.)"""
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
    # ``archive_unreadable`` is not retry work: the file is re-checked on every
    # pass, as the alert says, so the very next pass -- a minute later, well
    # inside that marker's hourly window -- accepts it.
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


# --- orphan markers: a resolved failure the prune can no longer clean up ---------------


def _write_valid_archive() -> None:
    payload = live.build_pregame_projection_archive(SEASON, WEEK, schedule_rows=SCHEDULE, now=NOW)
    live._write_pregame_archive(live.pregame_archive_path(SEASON, WEEK), payload)


def _orphan_marker(reason: str = "archive_readback_mismatch") -> pathlib.Path:
    """A failure marker in a week with no ``observations/`` directory."""
    marker = live._pregame_failure_path(SEASON, WEEK)
    live._mark_pregame_failure(marker, NOW, reason)
    assert not _obs_dir().exists()
    return marker


def test_a_resolved_orphan_marker_is_not_reported(kv):
    """The archive reads back and the raw log is already gone, so nothing is
    retained or retried; ``prune_retention`` only revisits a week that still
    has ``observations/``, so it can never clear this marker itself."""
    _record(PRE_KICKOFF_FETCH, REAL_FETCH)
    _write_valid_archive()
    marker = live._pregame_failure_path(SEASON, WEEK)
    live._mark_pregame_failure(marker, NOW, "archive_readback_mismatch")
    shutil.rmtree(_obs_dir())  # the prune of an earlier build removed the raw log

    assert live.prune_retention(SEASON, PRUNE_WEEK) == []  # nothing for the prune to do
    assert marker.exists()  # ... so it really is never cleaned up there

    rows = live.pregame_archive_health()
    assert rows == []
    sink = Sink()
    summary = _sweep(kv, sink, rows)
    assert summary["active"] == 0 and summary["fired"] == 0 and sink.sent == []
    assert marker.exists()  # the health reader is read-only


def test_the_orphan_skip_resolves_a_firing_alert(kv):
    """An alert raised while the raw log was still retained resolves once the
    log is gone and the archive reads back, even though the marker stays."""
    _record(PRE_KICKOFF_FETCH, REAL_FETCH)
    live._mark_pregame_failure(
        live._pregame_failure_path(SEASON, WEEK), NOW, "archive_readback_mismatch"
    )
    sink = Sink()
    assert _sweep(kv, sink, live.pregame_archive_health())["fired"] == 1

    _write_valid_archive()
    shutil.rmtree(_obs_dir())
    rows = live.pregame_archive_health()
    assert rows == []
    assert _sweep(kv, sink, rows)["recovered"] == 1


def test_an_orphan_marker_with_no_archive_is_still_reported(kv):
    """No raw log and no readable archive: the week's baseline is lost for
    good, which is exactly what an operator needs to hear about."""
    _orphan_marker("archive_unreadable")

    rows = live.pregame_archive_health()
    assert [(r["season"], r["week"], r["rawLogRetained"]) for r in rows] == [(SEASON, WEEK, False)]
    assert _sweep(kv, Sink(), rows)["categories"] == [CATEGORY]


def test_an_orphan_marker_beside_an_unreadable_archive_is_still_reported():
    path = live.pregame_archive_path(SEASON, WEEK)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"not gzip")
    _orphan_marker("archive_unreadable")

    rows = live.pregame_archive_health()
    assert len(rows) == 1 and rows[0]["rawLogRetained"] is False


def test_a_marker_beside_a_retained_raw_log_is_still_reported():
    """The skip is narrow: while ``observations/`` exists the prune will
    revisit the week and clear the marker, so health keeps reporting it."""
    _record(PRE_KICKOFF_FETCH, REAL_FETCH)
    _write_valid_archive()
    live._mark_pregame_failure(live._pregame_failure_path(SEASON, WEEK), NOW, "x")

    rows = live.pregame_archive_health()
    assert [(r["week"], r["rawLogRetained"]) for r in rows] == [(WEEK, True)]


def test_a_corrupt_deflate_stream_reads_back_as_unreadable(monkeypatch):
    """``zlib.error`` is neither an OSError nor a ValueError; it must mean
    "does not read back" (None), not a crash in the prune or the health read."""
    import gzip

    def corrupt(*_args, **_kwargs):
        raise zlib.error("Error -3 while decompressing data: invalid stored block lengths")

    path = live.pregame_archive_path(SEASON, WEEK)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x1f\x8b")
    monkeypatch.setattr(gzip, "open", corrupt)

    assert live._read_pregame_archive(path) is None
    _orphan_marker("archive_unreadable")
    rows = live.pregame_archive_health()  # does not raise, and does not skip the week
    assert rows is not None and len(rows) == 1


# --- the alert text says what is actually true -------------------------------------------


def test_the_alert_text_matches_whether_the_raw_log_is_retained():
    retained = {
        "leagueKey": live.NFL_KEY,
        "season": SEASON,
        "week": WEEK,
        "reason": "kickoffs_unknown",
        "failedAt": live._iso(NOW),
        "rawLogRetained": True,
    }
    gone = dict(retained, rawLogRetained=False, reason="archive_unreadable")

    (a_retained,) = oa._check_pregame_archive([retained])
    (a_gone,) = oa._check_pregame_archive([gone])

    assert "retries hourly" in a_retained.detail
    assert "resolves when a build succeeds" in a_retained.detail

    # No raw log and no archive: no retry, no automatic resolution, said plainly.
    assert "retries hourly" not in a_gone.detail
    assert "resolves when a build succeeds" not in a_gone.detail
    assert "does not retry" in a_gone.detail
    assert "raw weekly-projection log is gone" in a_gone.detail
    assert "cannot be rebuilt" in a_gone.detail and "cannot be rebuilt" in a_gone.title
    assert "archive_unreadable" in a_gone.detail
    # Same category either way, so cooldown/recovery bookkeeping is unchanged.
    assert a_gone.category == a_retained.category == CATEGORY


def test_an_unrecoverable_week_reaches_the_operator_with_the_true_text(kv):
    _orphan_marker("archive_unreadable")
    sink = Sink()
    summary = _sweep(kv, sink, live.pregame_archive_health())

    assert summary["fired"] == 1 and len(sink.sent) == 1
    _to, _subject, body = sink.sent[0]
    assert "cannot be rebuilt" in body and "retries hourly" not in body


def _row(reason, *, retained=True, **extra) -> dict:
    """A health row; ``retained`` is both the observations directory and the
    weekly log unless ``weeklyLogRetained`` is passed separately."""
    return {
        "leagueKey": live.NFL_KEY,
        "season": SEASON,
        "week": WEEK,
        "reason": reason,
        "failedAt": live._iso(NOW + 7200),
        "firstFailedAt": None,
        "flushFailure": None,
        "rawLogRetained": retained,
        "weeklyLogRetained": retained,
        **extra,
    }


# A build failure's claims that are FALSE for a pending directory flush: the
# verified archive exists, nothing is rebuilt for it, and the alert resolves
# when the flush -- not a build -- succeeds.
_BUILD_FAILURE_CLAIMS = ("not built", "until the archive exists", "resolves when a build succeeds")
# Every pending-flush kind is retried the same way: the byte-identical rewrite.
_REWRITE_RETRY = (
    "Whatever the failed step, the Game Day collector's retry, at most hourly, rewrites the "
    "accepted archive byte for byte -- its own bytes, read back and checked by sha256, never "
    "rebuilt from the raw log -- renames that copy over it and flushes the directory again: no "
    "bare re-flush is trusted"
)


def _assert_retry_is_the_rewrite(alert) -> None:
    assert _REWRITE_RETRY in alert.detail
    # Round 4's "open" text promised a flush-only retry; nothing does that now.
    assert "retries only the flush" not in alert.detail
    assert "size and sha256" not in alert.detail  # one guard: sha256
    assert "rebuilds the archive" not in alert.detail and "treated as an fsync" not in alert.detail


@pytest.mark.parametrize(
    ("kind", "cause"),
    [
        ("open", "The directory could not be opened, so no fsync ran."),
        ("fsync", "fsync reported an error."),
        (None, "The failed step is not on record."),
        ("dir_sync", "The failed step is not on record."),
    ],
    ids=["open", "fsync", "null", "unknown"],
)
def test_a_pending_directory_flush_alert_says_what_is_true(kind, cause):
    first = live._iso(NOW)
    (alert,) = oa._check_pregame_archive(
        [_row("archive_directory_unflushed", firstFailedAt=first, flushFailure=kind)]
    )
    text = alert.title + "\n" + alert.detail

    for claim in _BUILD_FAILURE_CLAIMS:
        assert claim not in text
    assert "retries hourly" not in text
    assert alert.title == (
        f"Pregame projections archive for {SEASON} week {WEEK} awaiting a durable directory flush"
    )
    # The lead and the closing are round 4's, byte for byte.
    assert alert.detail.startswith(
        f"The verified pregame weekly-projections archive for {live.NFL_KEY} {SEASON} week "
        f"{WEEK} is in place, but the directory holding it could not be flushed to disk "
        f"(archive_directory_unflushed; flush failure: {kind or 'unrecorded'}; "
        f"failing since {first}).  Until a flush succeeds a power loss could undo the rename "
        "that put it there, so the raw weekly-projection log is retained"
    )
    assert alert.detail.endswith("This resolves when the directory flush succeeds.")
    assert f"  {cause}  {_REWRITE_RETRY}" in alert.detail
    assert live._iso(NOW + 7200) not in alert.detail  # the start, not the latest retry
    _assert_retry_is_the_rewrite(alert)
    assert alert.category == CATEGORY and alert.severity == "warning"


def test_a_failed_rewrite_alert_says_the_rewrite_could_not_complete():
    """``flushFailure: "rewrite"`` -- an I/O error or a sha256 mismatch stopped
    the rewrite before any flush ran -- must not say the directory "could not be
    flushed", nor that it resolves when "the directory flush" succeeds."""
    first = live._iso(NOW)
    (alert,) = oa._check_pregame_archive(
        [_row("archive_directory_unflushed", firstFailedAt=first, flushFailure="rewrite")]
    )

    assert alert.title == (
        f"Pregame projections archive for {SEASON} week {WEEK} awaiting a durable directory flush"
    )
    assert alert.detail.startswith(
        f"The verified pregame weekly-projections archive for {live.NFL_KEY} {SEASON} week "
        f"{WEEK} is in place, but the byte-identical rewrite that re-establishes the rename that "
        "put it there could not complete (archive_directory_unflushed; flush failure: rewrite; "
        f"failing since {first}).  Until that rewrite and its directory flush succeed a power "
        "loss could undo the rename, so the raw weekly-projection log is retained"
    )
    assert "before any directory flush ran" in alert.detail
    assert alert.detail.endswith(
        "This resolves when the byte-identical rewrite and its directory flush succeed."
    )
    assert "could not be flushed to disk" not in alert.detail
    assert "This resolves when the directory flush succeeds." not in alert.detail
    _assert_retry_is_the_rewrite(alert)
    for claim in _BUILD_FAILURE_CLAIMS:
        assert claim not in alert.title + alert.detail


def test_a_raw_log_prune_failed_alert_says_what_is_true():
    """The archive is in place and nothing is lost; only the delete failed, and it
    is retried at most hourly.  Not a build failure, not a pending flush."""
    first = live._iso(NOW)
    (alert,) = oa._check_pregame_archive([_row("raw_log_prune_failed", firstFailedAt=first)])

    assert alert.title == (
        f"Pregame projections archive for {SEASON} week {WEEK} in place; raw log not removed"
    )
    assert alert.detail.startswith(
        f"The verified pregame weekly-projections archive for {live.NFL_KEY} {SEASON} week "
        f"{WEEK} is in place, but the week's raw observations could not be removed after it was "
        f"established (raw_log_prune_failed; failing since {first}).  Nothing is lost"
    )
    assert "retries at most hourly" in alert.detail and "byte-identical rewrite" in alert.detail
    assert alert.detail.endswith("This resolves when the raw log is removed.")
    assert live._iso(NOW + 7200) not in alert.detail  # the start, not the latest retry
    for claim in (*_BUILD_FAILURE_CLAIMS, "could not be flushed", "awaiting"):
        assert claim not in alert.title + alert.detail
    assert alert.category == CATEGORY and alert.severity == "warning"


def test_a_real_raw_log_prune_failure_reaches_the_operator(monkeypatch, kv):
    """End to end: the real prune with a delete that fails silently, the health
    reader, the sweep, the sink -- then the alert resolves once the delete works."""
    _record(PRE_KICKOFF_FETCH, REAL_FETCH)
    real_rmtree = shutil.rmtree
    monkeypatch.setattr(shutil, "rmtree", lambda *a, **k: None)

    assert live.prune_retention(SEASON, PRUNE_WEEK, now=NOW) == []
    sink = Sink()
    summary = _sweep(kv, sink, live.pregame_archive_health())

    assert summary["categories"] == [CATEGORY] and len(sink.sent) == 1
    _to, _subject, body = sink.sent[0]
    assert "raw log not removed" in body and "raw_log_prune_failed" in body
    assert f"failing since {live._iso(NOW)}" in body

    monkeypatch.setattr(shutil, "rmtree", real_rmtree)
    assert live.prune_retention(SEASON, PRUNE_WEEK, now=NOW + 3600) == [str(_obs_dir())]
    assert _sweep(kv, sink, live.pregame_archive_health())["recovered"] == 1


def test_a_pending_flush_alert_without_a_start_falls_back_to_the_latest_attempt():
    """A marker written before ``firstFailedAt`` existed still names a time."""
    (alert,) = oa._check_pregame_archive([_row("archive_directory_unflushed")])
    assert f"failing since {live._iso(NOW + 7200)}" in alert.detail


def test_an_unreadable_archive_alert_does_not_promise_a_build_retry():
    """``archive_unreadable`` was rendered as a build failure too, and that was
    false: the unreadable file is never overwritten, so no hourly build runs."""
    (alert,) = oa._check_pregame_archive([_row("archive_unreadable")])

    assert alert.title == f"Pregame projections archive for {SEASON} week {WEEK} unreadable"
    assert "retries hourly" not in alert.detail
    assert "resolves when a build succeeds" not in alert.detail
    # An EXISTING (readable) archive can be replaced by its byte-identical
    # durability rewrite; an UNREADABLE one is never overwritten.
    assert "never overwrites an unreadable archive" in alert.detail
    assert "existing archive" not in alert.detail
    assert "archive_unreadable" in alert.detail and "raw weekly-projection log is retained" in (
        alert.detail
    )
    assert "This resolves when the file at the archive path reads back" in alert.detail


_RETAINED_TEXT = (
    "The pregame weekly-projections archive for {league} {season} week {week} could not be "
    "established ({reason}; failed {failed}).  The raw weekly-projection log is retained -- the "
    "prune keeps it rather than delete evidence it has not archived -- but until the archive "
    "exists that week's pregame baseline is not preserved for the projection scorecard, and its "
    "raw observations stay on disk.  The Game Day collector retries hourly; see "
    "pregame_projections.retained.json beside the week.  This resolves when a build succeeds."
)
_GONE_TEXT = (
    "The pregame weekly-projections archive for {league} {season} week {week} could not be "
    "established ({reason}; failed {failed}).  The raw weekly-projection log is gone and no "
    "readable archive exists, so the week cannot be rebuilt: its pregame baseline is permanently "
    "missing from the projection scorecard.  The Game Day collector does not retry a week that "
    "has no raw log.  This alert keeps firing until the failure marker "
    "(pregame_projections.retained.json beside the week) is removed."
)


@pytest.mark.parametrize(
    ("reason", "retained"),
    [
        ("kickoffs_unknown", True),
        ("weekly_log_unreadable", True),
        ("archive_readback_mismatch", True),
        ("PregameArchiveUnavailable: kickoffs_unknown", True),
        ("failure_marker_unreadable", True),
        (None, True),
        ("archive_unreadable", False),
        ("archive_directory_unflushed", False),
        ("raw_log_prune_failed", False),
        ("kickoffs_unknown", False),
    ],
)
def test_every_other_reasons_alert_text_is_unchanged(reason, retained):
    """Byte for byte what the alert said before the two corrected reasons got
    their own text (the literals are the previous strings)."""
    row = _row(reason, retained=retained)
    (alert,) = oa._check_pregame_archive([row])
    fmt = {
        "league": live.NFL_KEY,
        "season": SEASON,
        "week": WEEK,
        "reason": reason or "unknown",
        "failed": row["failedAt"],
    }

    if retained:
        assert alert.title == f"Pregame projections archive for {SEASON} week {WEEK} not built"
        assert alert.detail == _RETAINED_TEXT.format(**fmt)
    else:
        assert alert.title == (
            f"Pregame projections archive for {SEASON} week {WEEK} cannot be rebuilt"
        )
        assert alert.detail == _GONE_TEXT.format(**fmt)


def test_a_real_pending_flush_reaches_the_operator_with_the_true_text(monkeypatch, kv):
    """End to end: the real archive pass, the health reader, the sweep, the sink."""
    _record(PRE_KICKOFF_FETCH, REAL_FETCH)
    monkeypatch.setattr(live, "_fsync_dir", lambda directory: live._DIR_OPEN_FAILED)
    assert live.ensure_pregame_archive(SEASON, WEEK, now=NOW) is False
    assert live._read_pregame_archive(live.pregame_archive_path(SEASON, WEEK)) is not None

    sink = Sink()
    summary = _sweep(kv, sink, live.pregame_archive_health())

    assert summary["categories"] == [CATEGORY] and len(sink.sent) == 1
    _to, _subject, body = sink.sent[0]
    assert "awaiting a durable directory flush" in body and "archive_directory_unflushed" in body
    assert f"failing since {live._iso(NOW)}" in body
    for claim in _BUILD_FAILURE_CLAIMS:
        assert claim not in body


# --- a marker that cannot be removed must not abort the prune ---------------------------


def _deny_marker_unlink(monkeypatch) -> None:
    real_unlink = pathlib.Path.unlink

    def unlink(self, *args, **kwargs):
        if self.name == live.PREGAME_ARCHIVE_FAILURE_NAME:
            raise PermissionError(13, "Permission denied", str(self))
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "unlink", unlink)


def test_an_unremovable_marker_does_not_abort_the_prune(monkeypatch, caplog):
    # Week A: a readable archive plus a stale marker (the "archive reads back" clear).
    # The marker is an earlier "unreadable" failure; a read-back-mismatch marker
    # would make the archive beside it untrusted rather than clearing.
    _record(PRE_KICKOFF_FETCH, REAL_FETCH)
    _write_valid_archive()
    marker_a = live._pregame_failure_path(SEASON, WEEK)
    live._mark_pregame_failure(marker_a, NOW, "archive_unreadable")
    # Week B: a raw-log directory with no weekly log (the "nothing to preserve" clear).
    week_b = WEEK + 1
    obs_b = live.league_week_dir(live.NFL_KEY, SEASON, week_b) / "observations"
    obs_b.mkdir(parents=True)
    (obs_b / "placeholder.txt").write_text("x", encoding="utf-8")
    marker_b = live._pregame_failure_path(SEASON, week_b)
    live._mark_pregame_failure(marker_b, NOW, "weekly_log_unreadable")

    _deny_marker_unlink(monkeypatch)
    with caplog.at_level(logging.WARNING, logger=live.__name__):
        # A minute later: neither marker is retry work, so neither throttles.
        removed = live.prune_retention(SEASON, WEEK + live.RAW_RETENTION_WEEKS + 2, now=NOW + 60)

    # Both weeks were pruned whatever order they were visited in: the first
    # marker's permission error did not abort the walk.
    assert sorted(removed) == sorted([str(_obs_dir()), str(obs_b)])
    assert not _obs_dir().exists() and not obs_b.exists()
    # The markers survive (and so keep alerting, which is the honest outcome) ...
    assert marker_a.exists() and marker_b.exists()
    # ... and the failure to clear them is on the record.
    cleared = [r for r in caplog.records if "could not clear pregame archive" in r.getMessage()]
    assert len(cleared) == 2


def test_an_unremovable_marker_after_a_successful_build_still_returns_true(monkeypatch):
    """The archive was written and verified, so the raw log may go; a marker
    that will not delete must not turn that into a failure or an exception."""
    _record(PRE_KICKOFF_FETCH, REAL_FETCH)
    marker = live._pregame_failure_path(SEASON, WEEK)
    live._mark_pregame_failure(marker, NOW, "weekly_log_unreadable")
    _deny_marker_unlink(monkeypatch)

    assert live.ensure_pregame_archive(SEASON, WEEK, now=NOW + 3601) is True
    assert live.pregame_archive_path(SEASON, WEEK).exists()
    assert marker.exists()


# --- the sweep is wired to the reader ---------------------------------------------------


def _run_sweep(monkeypatch) -> dict:
    """Drive the REAL ``POST /api/signal-alerts/run`` handler with
    ``ops_alerts.check_and_alert`` replaced by a recorder; return its kwargs."""
    from fastapi.testclient import TestClient

    import server  # noqa: PLC0415

    seen: dict = {}

    def check_and_alert(**kwargs):
        seen.update(kwargs)
        return {"fired": 0}

    monkeypatch.setattr(oa, "check_and_alert", check_and_alert)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        # Patch AFTER lifespan startup so it cannot clobber the stubs
        # (see tests/api/test_signal_alerts.py).
        monkeypatch.setattr(server, "latest_contract_data", {"players": {}})
        monkeypatch.setattr(server, "SIGNAL_ALERT_CRON_TOKEN", "test-token-pregame")
        monkeypatch.setattr(server._user_kv, "all_user_states", lambda: {})
        res = c.post(
            "/api/signal-alerts/run", headers={"Authorization": "Bearer test-token-pregame"}
        )
    assert res.status_code == 200, res.text
    assert res.json()["opsAlerts"] == {"fired": 0}
    return seen


def test_the_signal_alert_sweep_passes_the_archive_health_to_the_alerter(monkeypatch):
    _record(PRE_KICKOFF_FETCH, REAL_FETCH)
    _no_kickoffs(monkeypatch)
    live.ensure_pregame_archive(SEASON, WEEK, now=NOW)
    expected = live.pregame_archive_health()
    assert expected is not None and len(expected) == 1

    seen = _run_sweep(monkeypatch)

    # The producer is useless unless the cron that calls the alerter hands it over.
    assert "pregame_archive" in seen
    assert seen["pregame_archive"] == expected


def test_the_signal_alert_sweep_passes_not_checked_through_as_none(monkeypatch):
    """An unreadable/absent store is "not checked" (None), never an empty list."""
    assert not (live.LIVE_ROOT / live.NFL_KEY).exists()

    seen = _run_sweep(monkeypatch)

    assert "pregame_archive" in seen and seen["pregame_archive"] is None


# --- round 6: the weekly log and observations/ are two facts, and the text uses both -----


_UNREADABLE_TEXT = (
    "The pregame weekly-projections archive for {league} {season} week {week} could not be "
    "established (archive_unreadable; failing since {since}).  A file is at the archive path but "
    "does "
    "not read back, and the Game Day collector never overwrites an unreadable archive, so it is "
    "not rebuilt.  The raw weekly-projection log is retained -- the prune keeps it rather than "
    "delete evidence it has not archived -- and that week's pregame baseline is not preserved for "
    "the projection scorecard until the archive reads back.  The collector re-checks the file on "
    "every pass; see pregame_projections.retained.json beside the week.  This resolves when the "
    "file at the archive path reads back, or once it is removed and the next hourly build "
    "succeeds."
)


@pytest.mark.parametrize("first", [None, "2033-05-18T03:33:20+00:00"])
def test_the_unreadable_alert_text_while_the_weekly_log_is_retained(first):
    """Round 6 changed what makes this text TRUE (the file is now re-checked, and
    accepted, on every pass).  Round 7 changed one thing in it, deliberately: it
    shows when the incident BEGAN ("failing since" ``firstFailedAt``, else
    ``failedAt`` on a marker written before the start was recorded), not
    ``failedAt``, which moves with every hourly re-record.  Every other byte is
    round 6's."""
    row = _row("archive_unreadable", firstFailedAt=first)
    (alert,) = oa._check_pregame_archive([row])
    assert alert.title == f"Pregame projections archive for {SEASON} week {WEEK} unreadable"
    assert alert.detail == _UNREADABLE_TEXT.format(
        league=live.NFL_KEY, season=SEASON, week=WEEK, since=first or row["failedAt"]
    )


@pytest.mark.parametrize("retained", ["weekly", "observations-only"])
def test_the_unreadable_alert_shows_the_start_not_the_latest_re_record(retained):
    """``failedAt`` is the latest hourly re-record; the alert must not move with it."""
    first, latest = live._iso(NOW), live._iso(NOW + 5 * 3600)
    row = _row(
        "archive_unreadable",
        firstFailedAt=first,
        failedAt=latest,
        weeklyLogRetained=retained == "weekly",
    )
    (alert,) = oa._check_pregame_archive([row])
    assert alert.title.endswith("unreadable")
    assert f"(archive_unreadable; failing since {first})" in alert.detail
    assert latest not in alert.detail


def test_the_unreadable_alert_of_a_real_marker_keeps_its_start_across_re_records():
    """End to end: the real marker writer re-records hourly; the alert's time stays put."""
    marker = live._pregame_failure_path(SEASON, WEEK)
    _record(PRE_KICKOFF_FETCH, REAL_FETCH)
    live._mark_archive_unreadable(marker, NOW, None)
    for hour in (1, 2, 3):
        live._mark_archive_unreadable(marker, NOW + hour * 3600, live._read_json(marker))
    stored = live._read_json(marker)
    assert stored["failedAt"] == live._iso(NOW + 3 * 3600)
    row = {
        "leagueKey": live.NFL_KEY,
        "season": SEASON,
        "week": WEEK,
        "reason": stored["reason"],
        "failedAt": stored["failedAt"],
        "firstFailedAt": stored["firstFailedAt"],
        "flushFailure": None,
        "rawLogRetained": True,
        "weeklyLogRetained": True,
    }
    (alert,) = oa._check_pregame_archive([row])
    assert f"failing since {live._iso(NOW)})" in alert.detail
    assert live._iso(NOW + 3 * 3600) not in alert.detail


def test_health_reports_the_weekly_log_separately_from_observations():
    """``observations/`` holds every source's log; the weekly-projection log is one
    of them.  Health reports both, and they can disagree."""
    _record(PRE_KICKOFF_FETCH, REAL_FETCH)
    marker = live._pregame_failure_path(SEASON, WEEK)
    live._mark_pregame_failure(marker, NOW, "kickoffs_unknown")
    (_obs_dir() / "espn_scoreboard.jsonl").write_text("{}\n", encoding="utf-8")
    weekly = live.observation_log(live.NFL_KEY, SEASON, WEEK, live.SOURCE_WEEKLY).log_path

    def facts():
        (row,) = live.pregame_archive_health()
        return row["rawLogRetained"], row["weeklyLogRetained"]

    assert facts() == (True, True)
    weekly.unlink()  # e.g. a partial rmtree: the weekly log went, another source's stayed
    assert facts() == (True, False)
    shutil.rmtree(_obs_dir())  # and no readable archive, so the row is still reported
    assert facts() == (False, False)


_REASONS = [
    ("archive_directory_unflushed", "open"),
    ("archive_directory_unflushed", "fsync"),
    ("archive_directory_unflushed", "rewrite"),
    ("archive_directory_unflushed", None),
    ("archive_directory_unflushed", "dir_sync"),
    ("raw_log_prune_failed", None),
    ("archive_unreadable", None),
    ("kickoffs_unknown", None),
    ("weekly_log_unreadable", None),
    ("archive_readback_mismatch", None),
    ("PregameArchiveUnavailable: kickoffs_unknown", None),
    ("failure_marker_unreadable", None),
    (None, None),
]
# Claims that are only true while the raw weekly-projection log is on disk.
_WEEKLY_LOG_CLAIMS = (
    "The raw weekly-projection log is retained",
    "the raw weekly-projection log is retained",
    "rewrites the accepted archive byte for byte",
    "no bare re-flush is trusted",
    "the raw log simply stays on disk",
    "byte-identical rewrite of its own bytes",
    "retries hourly",
    "resolves when a build succeeds",
    "the next hourly build succeeds",
)
# Claims that are only true when NO raw observations remain.
_NOTHING_LEFT_CLAIMS = (
    "so the week cannot be rebuilt",
    "permanently missing",
    "does not retry a week that has no raw log",
)


@pytest.mark.parametrize(("reason", "kind"), _REASONS, ids=lambda v: str(v))
@pytest.mark.parametrize(
    ("weekly", "observations"),
    [(True, True), (False, True), (False, False), (True, False)],
    ids=["weekly+obs", "obs-only", "nothing", "weekly-without-obs"],
)
def test_every_alert_text_is_accurate_to_both_fields(reason, kind, weekly, observations):
    """Every reason and kind, in every combination of the two facts.  The weekly
    log lives inside ``observations/``, so a row claiming it is retained is read
    as that (the contradictory row renders exactly like the consistent one)."""
    first = live._iso(NOW)
    row = _row(
        reason,
        retained=observations,
        weeklyLogRetained=weekly,
        flushFailure=kind,
        firstFailedAt=first,
    )
    (alert,) = oa._check_pregame_archive([row])
    text = alert.title + "\n" + alert.detail
    assert alert.category == CATEGORY and alert.severity == "warning"
    assert (reason or "unknown") in alert.detail

    if weekly:
        consistent = _row(
            reason, retained=True, weeklyLogRetained=True, flushFailure=kind, firstFailedAt=first
        )
        (expected,) = oa._check_pregame_archive([consistent])
        assert (alert.title, alert.detail) == (expected.title, expected.detail)
        if reason == "raw_log_prune_failed":
            assert "the raw log simply stays on disk" in alert.detail
        else:
            assert "raw weekly-projection log is retained" in alert.detail
        for claim in ("no longer on disk", "already gone", *_NOTHING_LEFT_CLAIMS):
            assert claim not in text
    elif observations:
        for claim in (*_WEEKLY_LOG_CLAIMS, *_NOTHING_LEFT_CLAIMS):
            assert claim not in text, claim
        assert "other raw observations" in alert.detail
        if reason == "archive_directory_unflushed":
            assert (
                "The raw weekly-projection log is no longer on disk, so there is nothing left to "
                "protect"
            ) in alert.detail
            assert "only re-flushes the directory -- it never rewrites or rebuilds" in alert.detail
            assert alert.detail.endswith("This resolves when the directory flush succeeds.")
            assert f"failing since {first}" in alert.detail
            lead = "byte-identical rewrite" if kind == "rewrite" else "could not be flushed to disk"
            assert lead in alert.detail
            assert f"flush failure: {kind or 'unrecorded'}" in alert.detail
        elif reason == "raw_log_prune_failed":
            assert "raw observations not fully removed" in alert.title
            assert "weekly-projection log itself is already gone" in alert.detail
            assert "each retry only re-flushes the directory" in alert.detail
            assert f"failing since {first}" in alert.detail
        elif reason == "archive_unreadable":
            assert alert.title.endswith("unreadable")
            assert "The raw weekly-projection log is no longer on disk either" in alert.detail
            assert "The collector re-checks the file on every pass" in alert.detail
            assert "never overwrites an unreadable archive" in alert.detail
        else:
            assert alert.title.endswith("not built; raw weekly log gone")
            assert "no build can run and none is retried" in alert.detail
    else:
        assert alert.title.endswith("cannot be rebuilt")
        assert alert.detail == _GONE_TEXT.format(
            league=live.NFL_KEY,
            season=SEASON,
            week=WEEK,
            reason=reason or "unknown",
            failed=row["failedAt"],
        )


@pytest.mark.parametrize("retained", [True, False])
@pytest.mark.parametrize(("reason", "kind"), _REASONS, ids=lambda v: str(v))
def test_a_row_without_the_weekly_field_reads_as_its_reader_meant_it(reason, kind, retained):
    """A row built before ``weeklyLogRetained`` existed equated the two facts."""
    legacy = _row(reason, retained=retained, flushFailure=kind)
    del legacy["weeklyLogRetained"]
    (got,) = oa._check_pregame_archive([legacy])
    (expected,) = oa._check_pregame_archive([dict(legacy, weeklyLogRetained=retained)])
    assert (got.title, got.detail) == (expected.title, expected.detail)


def test_a_real_partial_prune_reaches_the_operator_with_the_true_text(monkeypatch, kv):
    """End to end: the real prune with an rmtree that removes the weekly log but
    leaves another file, the health reader, the sweep, the sink."""
    _record(PRE_KICKOFF_FETCH, REAL_FETCH)
    (_obs_dir() / "keep.lock").write_text("x", encoding="utf-8")

    def partial(path, *args, **kwargs):
        for item in pathlib.Path(path).iterdir():
            if item.name != "keep.lock":
                item.unlink()

    monkeypatch.setattr(shutil, "rmtree", partial)
    assert live.prune_retention(SEASON, PRUNE_WEEK, now=NOW) == []
    sink = Sink()
    summary = _sweep(kv, sink, live.pregame_archive_health())

    assert summary["categories"] == [CATEGORY] and len(sink.sent) == 1
    _to, _subject, body = sink.sent[0]
    assert "raw observations not fully removed" in body
    assert "weekly-projection log itself is already gone" in body
    assert "the raw log simply stays on disk" not in body


# --- round 8: a stale throttle and a refused legacy set-aside say what is true -------------

# Every state whose text promises an hourly retry, and so can go stale.
_THROTTLED_STATES = [
    ("archive_directory_unflushed", {"flushFailure": kind}, weekly)
    for kind in ("open", "fsync", "rewrite", None, "dir_sync")
    for weekly in (True, False)
] + [
    ("raw_log_prune_failed", {}, True),
    ("raw_log_prune_failed", {}, False),
    ("archive_readback_mismatch", {"setAsideFailed": True}, True),
]
_THROTTLED_IDS = [
    f"{reason}-{fields.get('flushFailure', fields and 'set_aside')}-{'weekly' if w else 'obs'}"
    for reason, fields, w in _THROTTLED_STATES
]


def _throttled_row(reason, fields, weekly, **extra) -> dict:
    return _row(
        reason,
        retained=True,
        weeklyLogRetained=weekly,
        firstFailedAt=live._iso(NOW),
        **fields,
        **extra,
    )


@pytest.mark.parametrize(("reason", "fields", "weekly"), _THROTTLED_STATES, ids=_THROTTLED_IDS)
def test_a_stale_throttle_never_promises_an_hourly_retry(reason, fields, weekly):
    """Round 8 blocking item.  A throttled row whose marker is no longer being
    refreshed (``throttleStale``) must not say "at most hourly": it says the
    marker could not be updated, so every pass retries, and that the time shown
    is when it was last recorded.  A fresh row renders byte for byte as before."""
    (before,) = oa._check_pregame_archive([_throttled_row(reason, fields, weekly)])
    (fresh,) = oa._check_pregame_archive(
        [_throttled_row(reason, fields, weekly, throttleStale=False)]
    )
    assert (fresh.title, fresh.detail) == (before.title, before.detail)
    assert "at most hourly" in fresh.detail and "not updating" not in fresh.title

    (stale,) = oa._check_pregame_archive(
        [_throttled_row(reason, fields, weekly, throttleStale=True)]
    )
    last = live._iso(NOW + 7200)
    assert stale.category == CATEGORY
    assert stale.title == before.title + " (failure marker not updating)"
    assert "at most hourly" not in stale.detail
    assert "on every pass while its failure marker cannot be updated (see below)" in stale.detail
    assert stale.detail == before.detail.replace(
        "at most hourly", "on every pass while its failure marker cannot be updated (see below)"
    ) + (
        f"  The failure marker has not been updated since {last}, although every retry updates "
        "it, so the hourly throttle is not holding: the marker most likely could not be updated "
        "(it reads back but cannot be written or replaced -- a read-only file, say), so the "
        "collector retries on every pass and warns each time that the failure is NOT recorded.  "
        "If instead the collector has not run the retry at all (out of season, or stopped), "
        f"nothing is retried.  {last} is when the marker was last recorded, not the latest "
        "attempt."
    )


# The reasons with no hourly throttle: health never marks them stale.
_UNTHROTTLED_REASONS = [
    (reason, kind)
    for reason, kind in _REASONS
    if reason not in ("archive_directory_unflushed", "raw_log_prune_failed")
]


@pytest.mark.parametrize(("reason", "kind"), _UNTHROTTLED_REASONS, ids=lambda v: str(v))
@pytest.mark.parametrize("weekly", [True, False])
def test_staleness_changes_no_text_without_an_hourly_promise(reason, kind, weekly):
    """``throttleStale`` reaches only the texts that promise a throttled retry.  On
    any other row (health never marks one stale, but an alerter must not invent
    a claim) the text is unchanged."""
    row = _row(reason, weeklyLogRetained=weekly, flushFailure=kind)
    (plain,) = oa._check_pregame_archive([row])
    (marked,) = oa._check_pregame_archive([dict(row, throttleStale=True)])
    assert (marked.title, marked.detail) == (plain.title, plain.detail)


@pytest.mark.parametrize("first", [None, live._iso(NOW)])
def test_the_legacy_set_aside_alert_names_the_refused_rename(first):
    """Round 8 nit 2.  A legacy marker whose leftover could not be set aside got
    the generic build-failure text with the latest hourly attempt's time.  It now
    says the refused rename is the blocker and an untrusted file sits at the
    archive path, shows when the incident began ("failing since", falling back
    to ``failedAt``), and says how it resolves."""
    row = _row("archive_readback_mismatch", firstFailedAt=first, setAsideFailed=True)
    (alert,) = oa._check_pregame_archive([row])
    since = first or row["failedAt"]
    assert alert.title == (
        f"Pregame projections archive for {SEASON} week {WEEK} not built; untrusted archive "
        "could not be set aside"
    )
    assert alert.detail == (
        f"The pregame weekly-projections archive for {live.NFL_KEY} {SEASON} week {WEEK} could "
        f"not be established (archive_readback_mismatch; failing since {since}).  A file an "
        "earlier version of the collector left at the archive path never passed verification, "
        "so it is not trusted, and the rename that sets it aside (to "
        "pregame_projections.json.gz.mismatch) was refused: that refused rename is what blocks "
        "the rebuild.  The untrusted file stays at the archive path and is never accepted.  The "
        "raw weekly-projection log is retained -- the prune keeps it rather than delete evidence "
        "it has not archived -- but until a verified archive exists that week's pregame baseline "
        "is not preserved for the projection scorecard.  The Game Day collector retries the "
        "set-aside at most hourly; see pregame_projections.retained.json beside the week.  This "
        "resolves when the set-aside rename succeeds and the rebuilt archive verifies."
    )


@pytest.mark.parametrize("weekly", [True, False])
def test_a_mismatch_without_a_failed_set_aside_keeps_its_text(weekly):
    """Only ``setAsideFailed`` selects the new text: a mismatch marker without it
    (and every observations-only row, where no set-aside runs) is unchanged."""
    row = _row("archive_readback_mismatch", weeklyLogRetained=weekly, firstFailedAt=live._iso(NOW))
    (plain,) = oa._check_pregame_archive([row])
    (flagged,) = oa._check_pregame_archive([dict(row, setAsideFailed=False)])
    assert (flagged.title, flagged.detail) == (plain.title, plain.detail)
    if not weekly:
        (gone,) = oa._check_pregame_archive([dict(row, setAsideFailed=True)])
        assert (gone.title, gone.detail) == (plain.title, plain.detail)


def test_health_reports_a_failed_set_aside_only_on_a_legacy_marker():
    _record(PRE_KICKOFF_FETCH, REAL_FETCH)
    marker = live._pregame_failure_path(SEASON, WEEK)
    stored = {"failedAt": live._iso(NOW), "reason": "archive_readback_mismatch"}
    for extra, expected in (
        ({"setAsideFailed": True}, True),
        ({}, False),
        ({"setAsideFailed": True, "candidateFlow": True}, False),
    ):
        live._atomic_write_json(marker, {**stored, **extra})
        (row,) = live.pregame_archive_health(now=NOW)
        assert row["setAsideFailed"] is expected
