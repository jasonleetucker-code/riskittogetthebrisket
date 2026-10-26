"""A mismatched pregame archive is never trusted, so the raw log is never pruned on it.

``ensure_pregame_archive`` used to write the archive at its accepted path and
THEN read it back.  When the read-back disagreed it wrote the failure marker
and returned False -- but left the failed file in place.  The retry an hour
later found an archive that parses, returned True, cleared the marker, and
``prune_retention`` deleted the raw ``observations/`` log: the only good copy
of what Calculator knew before kickoff, replaced by the archive that had
already failed verification (and fed to the AL-3b scorecard).

The accepted path now only ever holds an archive that has been read back and
count-checked: a build is written beside it (``.candidate``), verified, and
moved into place; one that fails is set aside as ``.mismatch``.  These tests
drive the real prune with a controlled clock and a writer that corrupts the
archive but leaves it readable (the failure that reads back as ``parses, but
the counts are wrong``).
"""

from __future__ import annotations

import gzip
import json
import logging
import os
import pathlib
import shutil

import pytest

from src.api import ops_alerts as oa
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
RETRY = live._PREGAME_ARCHIVE_RETRY_SECONDS
PRUNE_WEEK = WEEK + live.RAW_RETENTION_WEEKS + 1
MISMATCH = live.PREGAME_ARCHIVE_NAME + live.PREGAME_ARCHIVE_MISMATCH_SUFFIX
CANDIDATE = live.PREGAME_ARCHIVE_NAME + live.PREGAME_ARCHIVE_CANDIDATE_SUFFIX


@pytest.fixture(autouse=True)
def _fresh_state(monkeypatch):
    live._weekly_history_cache.clear()
    monkeypatch.setattr(live, "_archive_schedule_rows", lambda season: list(SCHEDULE))
    yield
    live._weekly_history_cache.clear()


@pytest.fixture()
def clock(monkeypatch):
    """Drive ``prune_retention``'s own ``ensure_pregame_archive`` call at a chosen time."""
    state = {"now": NOW}
    real = live.ensure_pregame_archive
    monkeypatch.setattr(
        live,
        "ensure_pregame_archive",
        lambda season, week, now=None: real(season, week, now=state["now"]),
    )
    return state


def _record(*fetches) -> None:
    log = live.observation_log(live.NFL_KEY, SEASON, WEEK, live.SOURCE_WEEKLY)
    for fetch in fetches:
        status, meta, content = live.weekly_to_observation(fetch)
        log.append(fetched_at=meta["observedAt"], status=status, meta=meta, content=content)


def _week_dir() -> pathlib.Path:
    return live.league_week_dir(live.NFL_KEY, SEASON, WEEK)


def _obs_dir() -> pathlib.Path:
    return _week_dir() / "observations"


def _accepted() -> pathlib.Path:
    return live.pregame_archive_path(SEASON, WEEK)


def _weekly_log_bytes() -> bytes:
    return live.observation_log(
        live.NFL_KEY, SEASON, WEEK, live.SOURCE_WEEKLY
    ).log_path.read_bytes()


def _good_payload() -> dict:
    payload = live.build_pregame_projection_archive(SEASON, WEEK, schedule_rows=SCHEDULE, now=NOW)
    assert payload is not None and len(payload["players"]) >= 1
    return payload


def _truncated(payload: dict) -> dict:
    """The same archive minus one player: readable, schema-valid, wrong counts."""
    bad = dict(payload)
    bad["players"] = dict(list(payload["players"].items())[:-1])
    return bad


def _corrupt_every_write(monkeypatch):
    """Make the archive writer produce a readable archive with a player missing."""
    real = live._write_pregame_archive

    def write(path, payload):
        real(path, _truncated(payload))

    monkeypatch.setattr(live, "_write_pregame_archive", write)
    return real


def _marker_reason() -> str | None:
    stored = live._read_json(live._pregame_failure_path(SEASON, WEEK))
    return stored.get("reason") if isinstance(stored, dict) else None


# --- the mismatched file never reaches the accepted path ---------------------------------


def test_a_mismatched_build_never_reaches_the_accepted_path(monkeypatch):
    _record(PRE_KICKOFF_FETCH, REAL_FETCH)
    good = _good_payload()
    _corrupt_every_write(monkeypatch)

    assert live.ensure_pregame_archive(SEASON, WEEK, now=NOW) is False

    assert not _accepted().exists()  # nothing a later pass could mistake for a good archive
    assert not (_week_dir() / CANDIDATE).exists()
    aside = live._read_pregame_archive(_week_dir() / MISMATCH)
    assert (
        aside is not None and len(aside["players"]) == len(good["players"]) - 1
    )  # kept to diagnose
    assert _marker_reason() == "archive_readback_mismatch"
    assert _obs_dir().is_dir()


def test_a_failure_between_the_write_and_the_check_leaves_no_accepted_archive(monkeypatch):
    """The window the old order had: written, not yet verified.  A raise (or a
    killed process) there used to leave an unverified file at the accepted path."""
    _record(PRE_KICKOFF_FETCH, REAL_FETCH)

    def explode(path):
        raise RuntimeError("read-back blew up")

    monkeypatch.setattr(live, "_read_pregame_archive", explode)

    assert live.ensure_pregame_archive(SEASON, WEEK, now=NOW) is False

    assert not _accepted().exists()
    assert "RuntimeError" in (_marker_reason() or "")
    assert _obs_dir().is_dir()


# --- the review's scenario: mismatch on pass 1, retry on pass 2 --------------------------


def test_the_retry_after_a_mismatch_does_not_prune_the_raw_log(monkeypatch, clock):
    _record(PRE_KICKOFF_FETCH, REAL_FETCH)
    before = _weekly_log_bytes()
    _corrupt_every_write(monkeypatch)

    live.prune_retention(SEASON, PRUNE_WEEK)  # pass 1
    assert _obs_dir().is_dir() and not _accepted().exists()

    clock["now"] = NOW + RETRY + 1  # an hour later: the throttle has lapsed
    removed = live.prune_retention(SEASON, PRUNE_WEEK)  # pass 2, same fault

    assert str(_obs_dir()) not in removed
    assert _obs_dir().is_dir()
    assert _weekly_log_bytes() == before  # the evidence is byte-identical
    assert not _accepted().exists()
    # ... and the week is still REPORTED, not quietly considered done.
    rows = live.pregame_archive_health()
    assert rows is not None and len(rows) == 1
    assert rows[0]["reason"] == "archive_readback_mismatch" and rows[0]["rawLogRetained"] is True


def test_the_retry_within_the_throttle_window_also_keeps_the_raw_log(monkeypatch, clock):
    _record(PRE_KICKOFF_FETCH, REAL_FETCH)
    _corrupt_every_write(monkeypatch)
    live.prune_retention(SEASON, PRUNE_WEEK)

    clock["now"] = NOW + 60
    live.prune_retention(SEASON, PRUNE_WEEK)

    assert _obs_dir().is_dir() and not _accepted().exists()


def test_a_mismatch_that_clears_is_rebuilt_verified_and_only_then_pruned(monkeypatch, clock):
    _record(PRE_KICKOFF_FETCH, REAL_FETCH)
    good = _good_payload()
    real_write = _corrupt_every_write(monkeypatch)
    live.prune_retention(SEASON, PRUNE_WEEK)
    assert _obs_dir().is_dir() and not _accepted().exists()

    monkeypatch.setattr(live, "_write_pregame_archive", real_write)  # the fault is gone
    clock["now"] = NOW + RETRY + 1
    removed = live.prune_retention(SEASON, PRUNE_WEEK)

    assert str(_obs_dir()) in removed and not _obs_dir().exists()
    archive = live._read_pregame_archive(_accepted())
    assert archive is not None
    assert len(archive["players"]) == len(good["players"])  # the VERIFIED copy, not the failed one
    assert not live._pregame_failure_path(SEASON, WEEK).exists()
    assert live.pregame_archive_health() == []


# --- a genuinely good archive is still accepted ------------------------------------------


def test_a_good_existing_archive_is_still_accepted_and_the_raw_log_pruned(clock):
    _record(PRE_KICKOFF_FETCH, REAL_FETCH)
    assert live.ensure_pregame_archive(SEASON, WEEK, now=NOW) is True  # built + verified
    first = _accepted().read_bytes()
    assert not (_week_dir() / CANDIDATE).exists()  # moved into place, not copied
    assert _obs_dir().is_dir()  # e.g. the process stopped before the prune

    clock["now"] = NOW + 60
    removed = live.prune_retention(SEASON, PRUNE_WEEK)

    assert str(_obs_dir()) in removed and not _obs_dir().exists()
    assert _accepted().read_bytes() == first  # never rewritten
    assert live.pregame_archive_health() == []


def test_a_good_archive_beside_an_unrelated_stale_marker_is_still_accepted(clock):
    """Only a read-back-mismatch marker makes an existing archive suspect; the
    other reasons keep the old "marker is stale once the archive reads back"."""
    _record(PRE_KICKOFF_FETCH, REAL_FETCH)
    live._write_pregame_archive(_accepted(), _good_payload())
    marker = live._pregame_failure_path(SEASON, WEEK)
    live._mark_pregame_failure(marker, NOW, "kickoffs_unknown")

    assert live.ensure_pregame_archive(SEASON, WEEK, now=NOW + 60) is True

    assert not marker.exists()
    assert not (_week_dir() / MISMATCH).exists()


# --- an archive already left behind by the pre-fix order is not trusted ------------------


def _pre_fix_leftover() -> bytes:
    """What the old order left: a readable, truncated archive and its marker."""
    live._write_pregame_archive(_accepted(), _truncated(_good_payload()))
    live._mark_pregame_failure(
        live._pregame_failure_path(SEASON, WEEK), NOW, "archive_readback_mismatch"
    )
    return _accepted().read_bytes()


def test_a_pre_fix_mismatched_archive_is_not_trusted_on_retry():
    _record(PRE_KICKOFF_FETCH, REAL_FETCH)
    good = _good_payload()
    bad_bytes = _pre_fix_leftover()
    before = _weekly_log_bytes()

    # Inside the throttle window: set aside, nothing trusted, nothing pruned.
    assert live.ensure_pregame_archive(SEASON, WEEK, now=NOW + 60) is False
    assert not _accepted().exists()
    assert (_week_dir() / MISMATCH).read_bytes() == bad_bytes
    assert _obs_dir().is_dir() and _weekly_log_bytes() == before

    # Once the throttle lapses it is rebuilt from the raw log and verified.
    assert live.ensure_pregame_archive(SEASON, WEEK, now=NOW + RETRY + 1) is True
    archive = live._read_pregame_archive(_accepted())
    assert archive is not None and len(archive["players"]) == len(good["players"])
    assert not live._pregame_failure_path(SEASON, WEEK).exists()


def test_the_leftover_fails_closed_when_it_cannot_be_set_aside(monkeypatch, caplog):
    _record(PRE_KICKOFF_FETCH, REAL_FETCH)
    bad_bytes = _pre_fix_leftover()
    real_replace = pathlib.Path.replace

    def replace(self, target):
        if self.name == live.PREGAME_ARCHIVE_NAME:
            raise PermissionError(13, "Permission denied", str(self))
        return real_replace(self, target)

    monkeypatch.setattr(pathlib.Path, "replace", replace)
    with caplog.at_level(logging.WARNING, logger=live.__name__):
        assert live.ensure_pregame_archive(SEASON, WEEK, now=NOW + RETRY + 1) is False

    assert _accepted().read_bytes() == bad_bytes  # untouched, and not blessed
    assert _obs_dir().is_dir()
    assert _marker_reason() == "archive_readback_mismatch"  # still alerting
    assert any("could not set aside" in r.getMessage() for r in caplog.records)


def test_a_mismatch_marker_with_no_raw_log_left_to_rebuild_from_is_left_alone():
    """Setting the archive aside with nothing to rebuild it from would turn
    "a copy that failed a check" into "no copy"; the old behaviour stands."""
    _record(PRE_KICKOFF_FETCH, REAL_FETCH)
    _pre_fix_leftover()
    shutil.rmtree(_obs_dir())  # the raw log is gone; only the archive remains

    assert live.ensure_pregame_archive(SEASON, WEEK, now=NOW + RETRY + 1) is True
    assert _accepted().exists() and not (_week_dir() / MISMATCH).exists()


# --- expiry: one unremovable archive does not abort the walk -----------------------------


def test_an_unremovable_expired_archive_does_not_abort_the_prune(monkeypatch, caplog):
    weeks = [WEEK, WEEK + 1, WEEK + 2]
    for w in weeks:
        path = live.pregame_archive_path(SEASON, w)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"expired")
    aside = live.pregame_archive_path(SEASON, weeks[0]).with_name(MISMATCH)
    aside.write_bytes(b"expired mismatch")
    denied = live.pregame_archive_path(SEASON, weeks[1])
    real_unlink = pathlib.Path.unlink

    def unlink(self, *args, **kwargs):
        if self == denied:
            raise PermissionError(13, "Permission denied", str(self))
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "unlink", unlink)
    with caplog.at_level(logging.WARNING, logger=live.__name__):
        removed = live.prune_retention(SEASON + live.PREGAME_ARCHIVE_SEASONS + 1, 1)

    # Whatever order the weeks were visited in, the others were still removed.
    assert sorted(removed) == sorted(
        [
            str(live.pregame_archive_path(SEASON, weeks[0])),
            str(aside),
            str(live.pregame_archive_path(SEASON, weeks[2])),
        ]
    )
    assert denied.exists()  # stays, and is retried on the next tick
    assert str(denied) not in removed  # never reported as removed
    assert any("could not remove expired pregame archive" in r.getMessage() for r in caplog.records)


def test_a_mismatch_alert_still_reaches_the_operator_after_the_retry(monkeypatch, clock, tmp_path):
    """End to end with the alerter: the retry that used to resolve the alert
    (by trusting the failed file) now leaves it firing."""
    from src.api import user_kv

    kv = tmp_path / "kv.sqlite"
    user_kv._SETUP_DONE.clear()
    sent: list[tuple[str, str, str]] = []

    def sink(to: str, subject: str, body: str) -> bool:
        sent.append((to, subject, body))
        return True

    _record(PRE_KICKOFF_FETCH, REAL_FETCH)
    _corrupt_every_write(monkeypatch)
    live.prune_retention(SEASON, PRUNE_WEEK)
    clock["now"] = NOW + RETRY + 1
    live.prune_retention(SEASON, PRUNE_WEEK)

    summary = oa.check_and_alert(
        pregame_archive=live.pregame_archive_health(),
        delivery=sink,
        to_email="ops@example.test",
        kv_path=kv,
    )
    user_kv._SETUP_DONE.clear()

    assert summary["fired"] == 1
    assert summary["categories"] == [f"pregame_archive:{live.NFL_KEY}:{SEASON}:{WEEK}"]
    assert "archive_readback_mismatch" in sent[0][2]


# --- durability: the verified bytes are on disk before the raw log can be pruned ----------


def _write_without_fsync(path, payload) -> None:
    """A writer that flushes nothing, so only the caller's own fsync can satisfy a test."""
    path.parent.mkdir(parents=True, exist_ok=True)
    blob = gzip.compress(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    )
    path.write_bytes(blob)


def _record_fsyncs(monkeypatch) -> list[tuple[int, int]]:
    """Patch ``os.fsync`` to note the (inode, size) of every file it flushes."""
    synced: list[tuple[int, int]] = []
    real_fsync = os.fsync

    def fsync(fd):
        stat = os.fstat(fd)
        synced.append((stat.st_ino, stat.st_size))
        return real_fsync(fd)

    monkeypatch.setattr(os, "fsync", fsync)
    return synced


def test_the_candidate_is_flushed_to_disk_before_it_replaces_the_accepted_archive(monkeypatch):
    """``prune_retention`` deletes the raw log the moment this returns True, so the
    verified bytes must already be durable when they become the accepted archive."""
    _record(PRE_KICKOFF_FETCH, REAL_FETCH)
    monkeypatch.setattr(live, "_write_pregame_archive", _write_without_fsync)
    synced = _record_fsyncs(monkeypatch)
    flushed_at_replace: list[bool] = []
    real_replace = pathlib.Path.replace

    def replace(self, target):
        if self.name == CANDIDATE and pathlib.Path(target).name == live.PREGAME_ARCHIVE_NAME:
            stat = os.stat(self)
            flushed_at_replace.append((stat.st_ino, stat.st_size) in synced)
        return real_replace(self, target)

    monkeypatch.setattr(pathlib.Path, "replace", replace)

    assert live.ensure_pregame_archive(SEASON, WEEK, now=NOW) is True

    assert flushed_at_replace == [True]  # fsync'd (full size), then replaced -- in that order
    assert live._read_pregame_archive(_accepted()) is not None


def test_a_candidate_that_cannot_be_flushed_is_never_accepted(monkeypatch):
    _record(PRE_KICKOFF_FETCH, REAL_FETCH)
    before = _weekly_log_bytes()
    monkeypatch.setattr(live, "_write_pregame_archive", _write_without_fsync)

    def fsync(fd):
        raise OSError(5, "Input/output error")

    monkeypatch.setattr(os, "fsync", fsync)

    assert live.ensure_pregame_archive(SEASON, WEEK, now=NOW) is False

    assert not _accepted().exists()  # never blessed
    assert "OSError" in (_marker_reason() or "")
    assert _obs_dir().is_dir() and _weekly_log_bytes() == before


def test_the_directory_is_flushed_after_the_rename(monkeypatch):
    _record(PRE_KICKOFF_FETCH, REAL_FETCH)
    seen: list[tuple[pathlib.Path, bool, bool]] = []

    def fsync_dir(directory):
        seen.append(
            (pathlib.Path(directory), _accepted().exists(), (_week_dir() / CANDIDATE).exists())
        )
        return True

    monkeypatch.setattr(live, "_fsync_dir", fsync_dir)

    assert live.ensure_pregame_archive(SEASON, WEEK, now=NOW) is True

    # Once, on the week directory, after the candidate had become the accepted file.
    assert seen == [(_week_dir(), True, False)]


def test_the_archive_writer_flushes_its_temp_file_before_the_rename(monkeypatch):
    synced = _record_fsyncs(monkeypatch)
    flushed_at_replace: list[bool] = []
    real_replace = pathlib.Path.replace
    target = _week_dir() / "flush-probe.json.gz"

    def replace(self, destination):
        if pathlib.Path(destination) == target:
            stat = os.stat(self)
            flushed_at_replace.append((stat.st_ino, stat.st_size) in synced)
        return real_replace(self, destination)

    monkeypatch.setattr(pathlib.Path, "replace", replace)

    live._write_pregame_archive(target, {"schemaVersion": live.PREGAME_ARCHIVE_SCHEMA})

    assert flushed_at_replace == [True]
    assert live._read_pregame_archive(target) is not None


def test_fsync_dir_flushes_and_closes_the_directory(monkeypatch, tmp_path):
    calls: list[tuple] = []
    with monkeypatch.context() as patch:
        patch.setattr(
            os,
            "open",
            lambda path, flags, *a, **k: calls.append(("open", pathlib.Path(path), flags)) or 77,
        )
        patch.setattr(os, "fsync", lambda fd: calls.append(("fsync", fd)))
        patch.setattr(os, "close", lambda fd: calls.append(("close", fd)))
        assert live._fsync_dir(tmp_path) is True

    assert calls == [("open", tmp_path, os.O_RDONLY), ("fsync", 77), ("close", 77)]


def test_fsync_dir_tolerates_a_platform_that_cannot_open_a_directory(monkeypatch, tmp_path):
    """Windows: ``os.open`` on a directory raises ``PermissionError``."""
    fsynced: list[int] = []

    def refuse(path, flags, *a, **k):
        raise PermissionError(13, "Permission denied", str(path))

    with monkeypatch.context() as patch:
        patch.setattr(os, "open", refuse)
        patch.setattr(os, "fsync", lambda fd: fsynced.append(fd))
        assert live._fsync_dir(tmp_path) is False

    assert fsynced == []


def test_fsync_dir_closes_the_handle_and_warns_when_the_flush_fails(monkeypatch, tmp_path, caplog):
    closed: list[int] = []

    def fsync(fd):
        raise OSError(5, "Input/output error")

    with monkeypatch.context() as patch:
        patch.setattr(os, "open", lambda path, flags, *a, **k: 78)
        patch.setattr(os, "fsync", fsync)
        patch.setattr(os, "close", lambda fd: closed.append(fd))
        with caplog.at_level(logging.WARNING, logger=live.__name__):
            assert live._fsync_dir(tmp_path) is False

    assert closed == [78]
    assert any("could not flush directory" in r.getMessage() for r in caplog.records)


# --- a failed set-aside of the candidate is reported -------------------------------------


def test_a_candidate_that_cannot_be_set_aside_is_logged_and_never_accepted(monkeypatch, caplog):
    _record(PRE_KICKOFF_FETCH, REAL_FETCH)
    _corrupt_every_write(monkeypatch)
    real_replace = pathlib.Path.replace

    def replace(self, target):
        if pathlib.Path(target).name == MISMATCH:
            raise PermissionError(13, "Permission denied", str(self))
        return real_replace(self, target)

    monkeypatch.setattr(pathlib.Path, "replace", replace)
    with caplog.at_level(logging.WARNING, logger=live.__name__):
        assert live.ensure_pregame_archive(SEASON, WEEK, now=NOW) is False

    messages = [r.getMessage() for r in caplog.records]
    assert any("could not set aside" in m for m in messages)  # the rename's own reason
    assert any("stays in place" in m and CANDIDATE in m for m in messages)  # and its consequence
    assert not _accepted().exists()
    assert _marker_reason() == "archive_readback_mismatch"
    assert _obs_dir().is_dir()


# --- the marker says which flow wrote it --------------------------------------------------


def test_only_a_candidate_flow_mismatch_is_stamped_candidate_flow(monkeypatch):
    _record(PRE_KICKOFF_FETCH, REAL_FETCH)
    marker = live._pregame_failure_path(SEASON, WEEK)
    _corrupt_every_write(monkeypatch)

    assert live.ensure_pregame_archive(SEASON, WEEK, now=NOW) is False
    stored = live._read_json(marker)
    assert stored["reason"] == "archive_readback_mismatch" and stored["candidateFlow"] is True

    # Any other failure, and the bare writer (the pre-fix shape), carry no stamp.
    _accepted().write_bytes(b"not gzip")
    assert live.ensure_pregame_archive(SEASON, WEEK, now=NOW + 1) is False
    assert "candidateFlow" not in live._read_json(marker)
    live._mark_pregame_failure(marker, NOW, "archive_readback_mismatch")
    assert "candidateFlow" not in live._read_json(marker)


def test_a_good_rebuild_whose_stale_mismatch_marker_cannot_be_cleared_is_kept(monkeypatch):
    """mismatch -> verified rebuild -> the marker unlink fails -> the next pass.

    The archive at the accepted path is a GOOD, verified one (the candidate flow
    puts nothing else there), so the leftover-rule must not set it aside and
    rebuild it on every pass just because a stale mismatch marker is still
    beside it and the raw log still exists."""
    _record(PRE_KICKOFF_FETCH, REAL_FETCH)
    good = _good_payload()
    real_write = _corrupt_every_write(monkeypatch)
    assert live.ensure_pregame_archive(SEASON, WEEK, now=NOW) is False  # the mismatch
    marker = live._pregame_failure_path(SEASON, WEEK)
    aside = _week_dir() / MISMATCH
    aside_bytes = aside.read_bytes()

    monkeypatch.setattr(live, "_write_pregame_archive", real_write)  # the fault is gone
    real_unlink = pathlib.Path.unlink

    def unlink(self, *args, **kwargs):
        if self.name == live.PREGAME_ARCHIVE_FAILURE_NAME:
            raise PermissionError(13, "Permission denied", str(self))
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "unlink", unlink)
    assert live.ensure_pregame_archive(SEASON, WEEK, now=NOW + RETRY + 1) is True  # verified
    assert marker.exists()  # ... and the stale marker could not be removed
    accepted_bytes = _accepted().read_bytes()
    archive = live._read_pregame_archive(_accepted())
    assert archive is not None and len(archive["players"]) == len(good["players"])
    assert _obs_dir().is_dir()  # the raw log is still there to tempt a rebuild

    builds: list[int] = []
    real_build = live.build_pregame_projection_archive

    def build(*args, **kwargs):
        builds.append(1)
        return real_build(*args, **kwargs)

    monkeypatch.setattr(live, "build_pregame_projection_archive", build)
    for later in (NOW + RETRY + 60, NOW + 3 * RETRY):  # inside and beyond the throttle
        assert live.ensure_pregame_archive(SEASON, WEEK, now=later) is True
        assert builds == []  # not rebuilt
        assert _accepted().read_bytes() == accepted_bytes  # not rewritten
        assert aside.read_bytes() == aside_bytes  # and not set aside over the diagnosis copy

    # Once the marker can be removed, it is.
    monkeypatch.setattr(pathlib.Path, "unlink", real_unlink)
    assert live.ensure_pregame_archive(SEASON, WEEK, now=NOW + 4 * RETRY) is True
    assert not marker.exists()
    assert live.pregame_archive_health() == []


# --- expiry: an abandoned candidate ages out with its week -------------------------------


def test_a_leftover_candidate_and_its_temp_file_age_out_with_the_week():
    week_dir = live.pregame_archive_path(SEASON, WEEK).parent
    week_dir.mkdir(parents=True, exist_ok=True)
    candidate = week_dir / CANDIDATE
    temp = week_dir / (CANDIDATE + ".tmp")
    candidate.write_bytes(b"abandoned candidate")
    temp.write_bytes(b"abandoned temp")

    # Not yet expired: a retry may still be using them.
    assert live.prune_retention(SEASON, WEEK) == []
    assert candidate.exists() and temp.exists()

    removed = live.prune_retention(SEASON + live.PREGAME_ARCHIVE_SEASONS + 1, 1)

    assert sorted(removed) == sorted([str(candidate), str(temp)])
    assert not candidate.exists() and not temp.exists()
