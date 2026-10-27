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

Durability (rounds 2-5): the raw log goes only once the rename that put the
verified archive in place is known to be on disk.  While the raw weekly log is
retained, an accepted archive is ALWAYS re-established by a BYTE-IDENTICAL
rewrite (its own bytes, copied, read back and checked by sha256, renamed over
it, then flushed) -- whatever marker is beside it, a recorded ``open`` failure
included, and with none -- never by a rebuild (a rebuild also reads the
schedule, the stored scoreboard and the clock, and could replace the verified
archive with a different one) and never by a bare re-flush (a marker is best
effort and can be stale).  Any marker inside the hourly window throttles it,
and a raw log that survives the prune is recorded (``raw_log_prune_failed``),
so no state rewrites the archive on every tick.
"""

from __future__ import annotations

import errno
import gzip
import hashlib
import json
import logging
import os
import pathlib
import shutil
import types

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
    """Drive ``prune_retention`` -- its own markers and its ``ensure_pregame_archive``
    call -- and direct ``ensure_pregame_archive`` calls at a chosen time."""
    state = {"now": NOW}
    real = live.ensure_pregame_archive
    real_prune = live.prune_retention
    monkeypatch.setattr(
        live,
        "ensure_pregame_archive",
        lambda season, week, now=None: real(season, week, now=state["now"]),
    )
    monkeypatch.setattr(
        live,
        "prune_retention",
        lambda season, week, now=None: real_prune(season, week, now=state["now"]),
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


def _marker() -> dict:
    stored = live._read_json(live._pregame_failure_path(SEASON, WEEK))
    assert isinstance(stored, dict), stored
    return stored


def _count_builds(monkeypatch) -> list[int]:
    """Record every archive build from here on."""
    builds: list[int] = []
    real_build = live.build_pregame_projection_archive

    def build(*args, **kwargs):
        builds.append(1)
        return real_build(*args, **kwargs)

    monkeypatch.setattr(live, "build_pregame_projection_archive", build)
    return builds


def _deny_marker_unlink(monkeypatch):
    """Make the failure marker impossible to remove (everything else unlinks)."""
    real_unlink = pathlib.Path.unlink

    def unlink(self, *args, **kwargs):
        if self.name == live.PREGAME_ARCHIVE_FAILURE_NAME:
            raise PermissionError(13, "Permission denied", str(self))
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "unlink", unlink)
    return real_unlink


def _stub_dir_flush(monkeypatch, outcome: str) -> dict:
    """Make every directory flush report ``outcome`` (switchable via the
    returned ``state["outcome"]``); ``state["calls"]`` counts them, and each is
    noted as ``"dir-flush"`` in ``state["events"]`` once a test sets it to a list."""
    state = {"outcome": outcome, "calls": 0, "events": None}

    def fsync_dir(directory):
        state["calls"] += 1
        if state["events"] is not None:
            state["events"].append("dir-flush")
        return state["outcome"]

    monkeypatch.setattr(live, "_fsync_dir", fsync_dir)
    return state


def _count_file_flushes(monkeypatch, events: list[str] | None = None) -> list[str]:
    """Record the name of every file ``_fsync_file`` flushes from here on (it
    still flushes); each is also noted as ``"file-flush:<name>"`` in ``events``."""
    flushed: list[str] = []
    real = live._fsync_file

    def fsync_file(path):
        flushed.append(pathlib.Path(path).name)
        if events is not None:
            events.append(f"file-flush:{pathlib.Path(path).name}")
        return real(path)

    monkeypatch.setattr(live, "_fsync_file", fsync_file)
    return flushed


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _record_archive_writes(monkeypatch, events: list[str] | None = None) -> list[tuple[str, str]]:
    """Note (file name, sha256 of the bytes) for every archive file write
    attempted from here on -- a build's and a byte-identical rewrite's alike (it
    still writes); each is also noted as ``"write:<name>"`` in ``events``."""
    writes: list[tuple[str, str]] = []
    real = live._write_archive_bytes

    def write(path, blob):
        writes.append((pathlib.Path(path).name, _sha(blob)))
        if events is not None:
            events.append(f"write:{pathlib.Path(path).name}")
        return real(path, blob)

    monkeypatch.setattr(live, "_write_archive_bytes", write)
    return writes


def _watch_accepted_path(monkeypatch, events: list[str]) -> None:
    """Note every rename or unlink that touches the accepted archive path."""
    real_replace, real_unlink = pathlib.Path.replace, pathlib.Path.unlink

    def replace(self, target):
        if pathlib.Path(target) == _accepted():
            events.append("replace-over-accepted" if _accepted().exists() else "replace-into-empty")
        elif self == _accepted():
            events.append("moved-accepted-away")
        return real_replace(self, target)

    def unlink(self, *args, **kwargs):
        if self == _accepted():
            events.append("unlinked-accepted")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "replace", replace)
    monkeypatch.setattr(pathlib.Path, "unlink", unlink)


def _fail_the_first_flush(monkeypatch, outcome: str) -> dict:
    """Pass 1 at ``NOW`` through the real prune: built, verified, renamed into
    place -- and the directory flush fails with ``outcome``."""
    _record(PRE_KICKOFF_FETCH, REAL_FETCH)
    flush = _stub_dir_flush(monkeypatch, outcome)
    assert str(_obs_dir()) not in live.prune_retention(SEASON, PRUNE_WEEK)
    assert _marker_reason() == "archive_directory_unflushed" and flush["calls"] == 1
    return flush


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
    assert _accepted().read_bytes() == first  # only ever copied onto itself, byte for byte
    assert live.pregame_archive_health() == []


def test_a_good_archive_beside_an_unrelated_stale_marker_is_still_accepted():
    """Only a read-back-mismatch marker makes an existing archive suspect; the
    other reasons keep the old "marker is stale once the archive reads back".  A
    build failure records nothing pending on an archive that exists, so it is not
    a retry-family marker and throttles nothing: accepted on the very next pass."""
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
    # ... and the marker now has the candidate-flow meaning, its failedAt (so the
    # throttle) untouched.
    assert _marker() == {
        "failedAt": live._iso(NOW),
        "reason": "archive_readback_mismatch",
        "candidateFlow": True,
    }

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
    # Not re-stamped: the leftover is still at the accepted path, so the marker
    # must keep saying it is not to be trusted.
    assert "candidateFlow" not in _marker()
    assert any("could not set aside" in r.getMessage() for r in caplog.records)


def test_a_mismatch_marker_with_no_raw_log_left_to_rebuild_from_is_left_alone():
    """Setting the archive aside with nothing to rebuild it from would turn
    "a copy that failed a check" into "no copy"; the old behaviour stands."""
    _record(PRE_KICKOFF_FETCH, REAL_FETCH)
    _pre_fix_leftover()
    shutil.rmtree(_obs_dir())  # the raw log is gone; only the archive remains

    assert live.ensure_pregame_archive(SEASON, WEEK, now=NOW + RETRY + 1) is True
    assert _accepted().exists() and not (_week_dir() / MISMATCH).exists()


# --- the set-aside reaches disk before the marker says the path is clean ------------------


@pytest.mark.parametrize("outcome", [live._DIR_FLUSHED, live._DIR_FLUSH_UNSUPPORTED])
def test_the_set_aside_is_flushed_before_the_marker_is_re_stamped(monkeypatch, outcome):
    """Re-stamped first, a crash could persist ``candidateFlow`` without the
    rename -- the unverified leftover at the accepted path beside a marker that
    vouches for it, accepted next pass, raw log pruned."""
    _record(PRE_KICKOFF_FETCH, REAL_FETCH)
    bad_bytes = _pre_fix_leftover()
    seen: list[tuple[bool, bool, bool]] = []

    def fsync_dir(directory):
        # (set aside yet?, leftover still at the accepted path?, already re-stamped?)
        seen.append(
            ((_week_dir() / MISMATCH).exists(), _accepted().exists(), "candidateFlow" in _marker())
        )
        return outcome

    monkeypatch.setattr(live, "_fsync_dir", fsync_dir)

    # Inside the throttle, so the pass ends right after the re-stamp: exactly one
    # flush, and it falls between the rename and the re-stamp.
    assert live.ensure_pregame_archive(SEASON, WEEK, now=NOW + 60) is False

    assert seen == [(True, False, False)]
    assert _marker() == {
        "failedAt": live._iso(NOW),
        "reason": "archive_readback_mismatch",
        "candidateFlow": True,
    }
    assert (_week_dir() / MISMATCH).read_bytes() == bad_bytes


@pytest.mark.parametrize("outcome", [live._DIR_OPEN_FAILED, live._DIR_FSYNC_FAILED])
def test_a_set_aside_that_cannot_be_flushed_keeps_the_legacy_marker(monkeypatch, caplog, outcome):
    _record(PRE_KICKOFF_FETCH, REAL_FETCH)
    good = _good_payload()
    bad_bytes = _pre_fix_leftover()
    marker = live._pregame_failure_path(SEASON, WEEK)
    legacy = marker.read_bytes()
    before = _weekly_log_bytes()
    flush = _stub_dir_flush(monkeypatch, outcome)
    builds = _count_builds(monkeypatch)

    with caplog.at_level(logging.WARNING, logger=live.__name__):
        # Past the throttle: only the unflushed set-aside stops this pass.
        assert live.ensure_pregame_archive(SEASON, WEEK, now=NOW + RETRY + 1) is False

    assert marker.read_bytes() == legacy  # not re-stamped, not rewritten at all
    assert flush["calls"] == 1 and builds == []  # nothing else happened this pass
    assert not _accepted().exists()
    assert (_week_dir() / MISMATCH).read_bytes() == bad_bytes
    assert _obs_dir().is_dir() and _weekly_log_bytes() == before
    assert any("could not flush the set-aside" in r.getMessage() for r in caplog.records)

    # A crash that kept the marker but lost the rename puts the leftover back at
    # the accepted path.  The marker still says "untrusted", so it is set aside
    # again -- not accepted -- and rebuilt.
    (_week_dir() / MISMATCH).replace(_accepted())
    flush["outcome"] = live._DIR_FLUSHED
    assert live.ensure_pregame_archive(SEASON, WEEK, now=NOW + RETRY + 2) is True
    archive = live._read_pregame_archive(_accepted())
    assert archive is not None and len(archive["players"]) == len(good["players"])
    assert builds == [1]
    assert (_week_dir() / MISMATCH).read_bytes() == bad_bytes


# --- a marker that cannot be re-stamped never raises --------------------------------------


def _deny_marker_rewrite(monkeypatch, how: str) -> None:
    """Make every rewrite of the failure marker raise ``PermissionError``."""
    if how == "atomic_write":
        real_write = live._atomic_write_json

        def write(path, payload):
            if pathlib.Path(path).name == live.PREGAME_ARCHIVE_FAILURE_NAME:
                raise PermissionError(13, "Permission denied", str(path))
            return real_write(path, payload)

        monkeypatch.setattr(live, "_atomic_write_json", write)
        return
    real_replace = pathlib.Path.replace

    def replace(self, target):  # the rename of the writer's temp file onto the marker
        if pathlib.Path(target).name == live.PREGAME_ARCHIVE_FAILURE_NAME:
            raise PermissionError(13, "Permission denied", str(target))
        return real_replace(self, target)

    monkeypatch.setattr(pathlib.Path, "replace", replace)


@pytest.mark.parametrize("how", ["atomic_write", "replace_onto_marker"])
def test_a_legacy_marker_that_cannot_be_re_stamped_does_not_raise(monkeypatch, caplog, how):
    _record(PRE_KICKOFF_FETCH, REAL_FETCH)
    _pre_fix_leftover()
    marker = live._pregame_failure_path(SEASON, WEEK)
    legacy = marker.read_bytes()
    _deny_marker_rewrite(monkeypatch, how)

    with caplog.at_level(logging.WARNING, logger=live.__name__):
        assert live.ensure_pregame_archive(SEASON, WEEK, now=NOW + 60) is False  # no raise

    assert marker.read_bytes() == legacy  # it keeps its old meaning
    assert not _accepted().exists()  # the leftover was still set aside
    assert any("could not re-stamp" in r.getMessage() for r in caplog.records)
    assert [p.name for p in _week_dir().iterdir() if p.name.endswith(".tmp")] == []


@pytest.mark.parametrize("how", ["atomic_write", "replace_onto_marker"])
def test_a_legacy_marker_that_cannot_be_re_stamped_does_not_abort_the_prune(
    monkeypatch, clock, caplog, how
):
    _record(PRE_KICKOFF_FETCH, REAL_FETCH)
    good = _good_payload()
    _pre_fix_leftover()
    # A second week the same walk must still reach: raw logs with nothing to archive.
    week_b = WEEK + 1
    obs_b = live.league_week_dir(live.NFL_KEY, SEASON, week_b) / "observations"
    obs_b.mkdir(parents=True)
    (obs_b / "placeholder.txt").write_text("x", encoding="utf-8")
    _deny_marker_rewrite(monkeypatch, how)

    clock["now"] = NOW + RETRY + 1
    with caplog.at_level(logging.WARNING, logger=live.__name__):
        removed = live.prune_retention(SEASON, WEEK + live.RAW_RETENTION_WEEKS + 2)

    # Whatever order the weeks were visited in, both were pruned.
    assert sorted(removed) == sorted([str(_obs_dir()), str(obs_b)])
    archive = live._read_pregame_archive(_accepted())
    assert archive is not None and len(archive["players"]) == len(good["players"])
    assert any("could not re-stamp" in r.getMessage() for r in caplog.records)


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
    # Only a read-back mismatch is a candidate-flow marker; this one must not
    # claim that meaning.
    assert "candidateFlow" not in _marker()
    assert _obs_dir().is_dir() and _weekly_log_bytes() == before


def test_the_directory_is_flushed_after_the_rename(monkeypatch):
    _record(PRE_KICKOFF_FETCH, REAL_FETCH)
    seen: list[tuple[pathlib.Path, bool, bool]] = []

    def fsync_dir(directory):
        seen.append(
            (pathlib.Path(directory), _accepted().exists(), (_week_dir() / CANDIDATE).exists())
        )
        return live._DIR_FLUSHED

    monkeypatch.setattr(live, "_fsync_dir", fsync_dir)

    assert live.ensure_pregame_archive(SEASON, WEEK, now=NOW) is True

    # Once, on the week directory, after the candidate had become the accepted file.
    assert seen == [(_week_dir(), True, False)]


# --- a directory flush that FAILED keeps the raw log; one the platform lacks does not ------


@pytest.mark.parametrize(
    ("outcome", "kind"), [(live._DIR_OPEN_FAILED, "open"), (live._DIR_FSYNC_FAILED, "fsync")]
)
def test_a_rename_whose_directory_flush_failed_keeps_the_raw_log(monkeypatch, clock, outcome, kind):
    """The verified archive is in place, but the rename that put it there is not
    known to be durable, so the raw log -- deleted the moment this returns True --
    must stay.  The archive is kept (its bytes are verified and flushed)."""
    _record(PRE_KICKOFF_FETCH, REAL_FETCH)
    good = _good_payload()
    before = _weekly_log_bytes()
    _stub_dir_flush(monkeypatch, outcome)

    removed = live.prune_retention(SEASON, PRUNE_WEEK)

    assert str(_obs_dir()) not in removed
    assert _obs_dir().is_dir() and _weekly_log_bytes() == before
    archive = live._read_pregame_archive(_accepted())
    assert archive is not None and len(archive["players"]) == len(good["players"])
    assert not (_week_dir() / CANDIDATE).exists() and not (_week_dir() / MISMATCH).exists()
    # Not a read-back mismatch, so no candidateFlow; which step failed, and when
    # the failure began (this attempt -- there was none before it).
    assert _marker() == {
        "failedAt": live._iso(NOW),
        "firstFailedAt": live._iso(NOW),
        "flushFailure": kind,
        "reason": "archive_directory_unflushed",
    }
    rows = live.pregame_archive_health()
    assert rows is not None and len(rows) == 1
    assert rows[0]["reason"] == "archive_directory_unflushed" and rows[0]["rawLogRetained"] is True
    assert rows[0]["flushFailure"] == kind and rows[0]["firstFailedAt"] == live._iso(NOW)


def test_an_existing_archive_is_accepted_only_once_its_directory_is_flushed(monkeypatch):
    """The accept branch makes the rename durable too: the pass that wrote this
    archive may have crashed between the rename and the flush (or predates it),
    and the next pass is the one whose True lets the raw log go.  (With the raw
    log retained that means the byte-identical rewrite, then its flush.)"""
    _record(PRE_KICKOFF_FETCH, REAL_FETCH)
    live._write_pregame_archive(_accepted(), _good_payload())
    accepted_bytes = _accepted().read_bytes()
    before = _weekly_log_bytes()
    marker = live._pregame_failure_path(SEASON, WEEK)
    live._mark_pregame_failure(marker, NOW, "kickoffs_unknown")  # an unrelated stale marker
    flush = _stub_dir_flush(monkeypatch, live._DIR_OPEN_FAILED)
    builds = _count_builds(monkeypatch)
    writes = _record_archive_writes(monkeypatch)

    # The stale build failure is not a retry-family marker: it throttles nothing.
    assert live.ensure_pregame_archive(SEASON, WEEK, now=NOW + 60) is False

    assert flush["calls"] == 1 and builds == [] and writes == [(CANDIDATE, _sha(accepted_bytes))]
    assert _accepted().read_bytes() == accepted_bytes  # kept: not rebuilt, not set aside
    assert not (_week_dir() / MISMATCH).exists()
    # The marker now says why the raw log is kept -- not the stale reason, and
    # not cleared as though the archive were established.  Its start is this
    # attempt: the stale marker was a different, non-retry failure.
    stored = _marker()
    assert stored["reason"] == "archive_directory_unflushed" and "candidateFlow" not in stored
    assert stored["firstFailedAt"] == live._iso(NOW + 60)
    assert _obs_dir().is_dir() and _weekly_log_bytes() == before

    # The unflushed marker IS retry work: inside its window the pass touches nothing.
    assert live.ensure_pregame_archive(SEASON, WEEK, now=NOW + 60 + RETRY - 1) is False
    assert flush["calls"] == 1 and len(writes) == 1

    flush["outcome"] = live._DIR_FLUSHED
    assert live.ensure_pregame_archive(SEASON, WEEK, now=NOW + 60 + RETRY) is True
    assert flush["calls"] == 2 and builds == [] and len(writes) == 2
    assert not marker.exists()


def test_a_platform_that_cannot_flush_a_directory_still_archives_and_prunes(monkeypatch, clock):
    """``"unsupported"`` (Windows refuses to open a directory) is not a failure:
    the rename's durability is the filesystem's own, on both branches."""
    _record(PRE_KICKOFF_FETCH, REAL_FETCH)
    flush = _stub_dir_flush(monkeypatch, live._DIR_FLUSH_UNSUPPORTED)

    assert live.ensure_pregame_archive(SEASON, WEEK, now=NOW) is True  # built, renamed
    assert live.ensure_pregame_archive(SEASON, WEEK, now=NOW + 60) is True  # existing archive
    assert flush["calls"] == 2
    assert not live._pregame_failure_path(SEASON, WEEK).exists()

    clock["now"] = NOW + 120
    removed = live.prune_retention(SEASON, PRUNE_WEEK)

    assert str(_obs_dir()) in removed and not _obs_dir().exists()
    assert live._read_pregame_archive(_accepted()) is not None
    assert live.pregame_archive_health() == []


# --- a pending flush is retried at most hourly, and keeps when it began -------------------


@pytest.mark.parametrize("outcome", [live._DIR_OPEN_FAILED, live._DIR_FSYNC_FAILED])
def test_a_pending_flush_is_not_retried_inside_the_throttle(monkeypatch, clock, caplog, outcome):
    """``prune_retention`` runs every tick; inside the hourly window a pass with a
    pending flush flushes nothing, rebuilds nothing, rewrites nothing, warns nothing."""
    flush = _fail_the_first_flush(monkeypatch, outcome)
    marker = live._pregame_failure_path(SEASON, WEEK)
    marker_bytes = marker.read_bytes()
    accepted_bytes = _accepted().read_bytes()
    builds = _count_builds(monkeypatch)
    writes = _record_archive_writes(monkeypatch)

    for later in (NOW + 60, NOW + RETRY - 1):
        clock["now"] = later
        caplog.clear()
        with caplog.at_level(logging.DEBUG, logger=live.__name__):
            assert str(_obs_dir()) not in live.prune_retention(SEASON, PRUNE_WEEK)
        assert flush["calls"] == 1  # no flush attempted
        assert builds == [] and writes == []  # nothing rebuilt, nothing rewritten
        assert marker.read_bytes() == marker_bytes  # failedAt is still the real attempt
        assert _accepted().read_bytes() == accepted_bytes
        assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []
    assert _obs_dir().is_dir()


def test_after_an_open_failure_the_retry_still_rewrites_the_same_bytes(monkeypatch, clock):
    """A recorded ``open`` failure used to earn a bare re-flush (no fsync ran, so
    no write error was consumed).  But that marker can be stale -- a later fsync
    error whose marker write failed leaves it saying ``open`` -- so it earns
    nothing: the retry rewrites the archive's own bytes, then flushes."""
    flush = _fail_the_first_flush(monkeypatch, live._DIR_OPEN_FAILED)
    accepted_bytes = _accepted().read_bytes()
    events: list[str] = []
    builds = _count_builds(monkeypatch)
    file_flushes = _count_file_flushes(monkeypatch)
    writes = _record_archive_writes(monkeypatch, events)
    flush["events"] = events

    clock["now"] = NOW + RETRY  # the window has lapsed (its boundary retries)
    assert str(_obs_dir()) not in live.prune_retention(SEASON, PRUNE_WEEK)  # still failing

    assert builds == [] and file_flushes == []  # never rebuilt
    assert writes == [(CANDIDATE, _sha(accepted_bytes))]  # rewritten, not merely re-flushed
    assert events == [f"write:{CANDIDATE}", "dir-flush"] and flush["calls"] == 2
    assert _accepted().read_bytes() == accepted_bytes
    # failedAt is this attempt (the throttle reads it); firstFailedAt is the start.
    assert _marker() == {
        "failedAt": live._iso(NOW + RETRY),
        "firstFailedAt": live._iso(NOW),
        "flushFailure": "open",
        "reason": "archive_directory_unflushed",
    }

    flush["outcome"] = live._DIR_FLUSHED  # the fault clears
    clock["now"] = NOW + 2 * RETRY
    removed = live.prune_retention(SEASON, PRUNE_WEEK)

    assert str(_obs_dir()) in removed and not _obs_dir().exists()
    assert flush["calls"] == 3 and builds == [] and file_flushes == []
    assert writes == [(CANDIDATE, _sha(accepted_bytes))] * 2
    assert events[-2:] == [f"write:{CANDIDATE}", "dir-flush"]
    assert _accepted().read_bytes() == accepted_bytes
    assert not live._pregame_failure_path(SEASON, WEEK).exists()
    assert live.pregame_archive_health() == []


def _deny_marker_writes(monkeypatch) -> dict:
    """Make every write of the failure marker fail with ENOSPC while
    ``state["deny"]`` is true (it is swallowed, as on the box)."""
    state = {"deny": False}
    real = live._atomic_write_json

    def write(path, payload):
        if state["deny"] and pathlib.Path(path).name == live.PREGAME_ARCHIVE_FAILURE_NAME:
            raise OSError(errno.ENOSPC, "No space left on device", str(path))
        return real(path, payload)

    monkeypatch.setattr(live, "_atomic_write_json", write)
    return state


def test_a_stale_open_marker_after_an_unrecorded_fsync_failure_still_rewrites(monkeypatch, clock):
    """The reviewer's round-5 probe.  Pass 1: the rename, then the directory OPEN
    fails -> marker ``open``.  Pass 2: the retry's fsync fails with EIO (reported
    once, so consumed) and the marker write fails with ENOSPC (swallowed) -> the
    marker still says ``open``, with pass 1's ``failedAt``.  Pass 3, a minute
    later, is not throttled.  A bare re-flush on a new handle would succeed and
    prune the raw log behind a rename that may never have reached disk; instead
    it rewrites the bytes, so the flush that lets the log go follows a NEW rename."""
    flush = _fail_the_first_flush(monkeypatch, live._DIR_OPEN_FAILED)
    accepted_bytes = _accepted().read_bytes()
    deny = _deny_marker_writes(monkeypatch)
    events: list[str] = []
    writes = _record_archive_writes(monkeypatch, events)
    flush["events"] = events

    flush["outcome"] = live._DIR_FSYNC_FAILED  # pass 2
    deny["deny"] = True
    clock["now"] = NOW + RETRY
    assert str(_obs_dir()) not in live.prune_retention(SEASON, PRUNE_WEEK)
    assert _marker()["flushFailure"] == "open" and _marker()["failedAt"] == live._iso(NOW)  # stale

    deny["deny"] = False
    flush["outcome"] = live._DIR_FLUSHED  # pass 3: a fresh fsync now "succeeds"
    clock["now"] = NOW + RETRY + 60
    removed = live.prune_retention(SEASON, PRUNE_WEEK)

    assert str(_obs_dir()) in removed
    # Both passes rewrote; the flush that let the raw log go came after pass 3's
    # own rename, not after the consumed error.
    assert writes == [(CANDIDATE, _sha(accepted_bytes))] * 2
    assert events == [f"write:{CANDIDATE}", "dir-flush"] * 2
    assert _accepted().read_bytes() == accepted_bytes


def test_after_an_fsync_failure_the_retry_rewrites_the_same_bytes(monkeypatch, clock):
    """Linux reports a write error to ONE fsync; a later fsync on a new handle can
    return 0 although the rename never reached disk.  So the retry trusts no bare
    re-flush -- and it does not rebuild either.  It writes the accepted archive's
    OWN bytes to a flushed copy, checks the copy, renames it OVER the accepted
    archive (never deleting that first), and only then flushes the directory."""
    flush = _fail_the_first_flush(monkeypatch, live._DIR_FSYNC_FAILED)
    accepted_bytes = _accepted().read_bytes()
    first = live._read_pregame_archive(_accepted())
    events: list[str] = []
    builds = _count_builds(monkeypatch)
    file_flushes = _count_file_flushes(monkeypatch, events)
    writes = _record_archive_writes(monkeypatch, events)
    synced = _record_fsyncs(monkeypatch)
    _watch_accepted_path(monkeypatch, events)
    flushed_at_replace: list[bool] = []
    watched_replace = pathlib.Path.replace

    def replace(self, target):
        if self.name == CANDIDATE and pathlib.Path(target) == _accepted():
            stat = os.stat(self)
            flushed_at_replace.append((stat.st_ino, stat.st_size) in synced)
        return watched_replace(self, target)

    monkeypatch.setattr(pathlib.Path, "replace", replace)
    flush["events"] = events
    flush["outcome"] = live._DIR_FLUSHED  # this time the flush works

    clock["now"] = NOW + RETRY
    removed = live.prune_retention(SEASON, PRUNE_WEEK)

    assert builds == [] and file_flushes == []  # never rebuilt
    assert writes == [(CANDIDATE, _sha(accepted_bytes))]  # the accepted archive's own bytes
    assert events == [f"write:{CANDIDATE}", "replace-over-accepted", "dir-flush"]
    assert flushed_at_replace == [True]  # the copy was on disk before it replaced the original
    assert flush["calls"] == 2
    assert _accepted().read_bytes() == accepted_bytes
    assert live._read_pregame_archive(_accepted())["archivedAt"] == first["archivedAt"]
    assert not (_week_dir() / CANDIDATE).exists()
    assert not (_week_dir() / (CANDIDATE + ".tmp")).exists()
    assert str(_obs_dir()) in removed and not _obs_dir().exists()
    assert live.pregame_archive_health() == []


def _counted_counts(archive: dict) -> list[int]:
    return [len(archive[key]) for key in ("players", "timingUnverified")]


@pytest.mark.parametrize("change", ["schedule_changed", "schedule_empty", "builder_differs"])
def test_the_fsync_retry_never_replaces_the_archive_from_changed_inputs(monkeypatch, clock, change):
    """The review's probe.  A rebuild reads more than the retained raw log -- the
    cached schedule, the stored scoreboard, the clock -- so a durability retry
    that rebuilt could swap the verified archive for a different, less complete
    one (a reviewer saw 599 players become 564 plus 35 ``timingUnverified``) and
    then prune the raw log.  The retry copies bytes instead: whatever those inputs
    say now, the accepted archive stays byte-identical, and the raw log goes only
    once a flush after the rewrite succeeds."""
    flush = _fail_the_first_flush(monkeypatch, live._DIR_FSYNC_FAILED)
    accepted_bytes = _accepted().read_bytes()
    first = live._read_pregame_archive(_accepted())
    if change == "builder_differs":
        real_build = live.build_pregame_projection_archive
        monkeypatch.setattr(
            live,
            "build_pregame_projection_archive",
            lambda *args, **kwargs: _truncated(real_build(*args, **kwargs)),
        )
    else:
        changed = [] if change == "schedule_empty" else list(SCHEDULE[: len(SCHEDULE) // 2])
        monkeypatch.setattr(live, "_archive_schedule_rows", lambda season: list(changed))

    # The probe has teeth: a rebuild now would NOT reproduce the accepted archive.
    def rebuild():
        return live.build_pregame_projection_archive(
            SEASON, WEEK, schedule_rows=live._archive_schedule_rows(SEASON), now=NOW + RETRY
        )

    if change == "schedule_empty":
        with pytest.raises(live.PregameArchiveUnavailable):
            rebuild()
    else:
        assert _counted_counts(rebuild()) != _counted_counts(first)

    reads: list[str] = []
    for name in ("_archive_schedule_rows", "_last_scoreboard"):
        real = getattr(live, name)
        monkeypatch.setattr(
            live,
            name,
            lambda *a, _real=real, _name=name, **k: reads.append(_name) or _real(*a, **k),
        )
    builds = _count_builds(monkeypatch)
    writes = _record_archive_writes(monkeypatch)

    # The retry's own flush fails again: nothing is pruned, nothing changes.
    clock["now"] = NOW + RETRY
    assert str(_obs_dir()) not in live.prune_retention(SEASON, PRUNE_WEEK)
    assert _accepted().read_bytes() == accepted_bytes and _obs_dir().is_dir()
    assert _marker()["flushFailure"] == "fsync"

    # Once a flush succeeds the raw log goes -- and the archive is still the original.
    flush["outcome"] = live._DIR_FLUSHED
    clock["now"] = NOW + 2 * RETRY
    removed = live.prune_retention(SEASON, PRUNE_WEEK)

    assert str(_obs_dir()) in removed and not _obs_dir().exists()
    assert _accepted().read_bytes() == accepted_bytes
    archive = live._read_pregame_archive(_accepted())
    assert archive["archivedAt"] == first["archivedAt"]
    assert _counted_counts(archive) == _counted_counts(first)
    assert builds == [] and reads == []  # the builder, schedule and scoreboard: never consulted
    assert writes == [(CANDIDATE, _sha(accepted_bytes))] * 2
    assert flush["calls"] == 3


def _unflushed_rewrite_marker(failed_at: float) -> dict:
    """The marker after a rewrite that could not complete: the step is the
    rewrite itself (no flush ran), and the failure's start is kept."""
    return {
        "failedAt": live._iso(failed_at),
        "firstFailedAt": live._iso(NOW),
        "flushFailure": "rewrite",
        "reason": "archive_directory_unflushed",
    }


@pytest.mark.parametrize("damage", ["one_byte_changed", "one_byte_short"])
def test_a_rewrite_that_does_not_read_back_identical_fails_closed(
    monkeypatch, clock, caplog, damage
):
    """The copy's sha256 must equal the accepted archive's before it may replace
    it -- here one byte differs at the same size, or the copy is short.  It never
    does: the accepted archive and the raw log are kept, the marker records the
    rewrite as the failed step (its start kept), and the next retry overwrites
    the bad copy."""
    flush = _fail_the_first_flush(monkeypatch, live._DIR_FSYNC_FAILED)
    accepted_bytes = _accepted().read_bytes()
    before = _weekly_log_bytes()
    real_write = live._write_archive_bytes

    def damaged_write(path, blob):
        bad = blob[:-1] if damage == "one_byte_short" else blob[:-1] + bytes([blob[-1] ^ 0xFF])
        assert len(bad) == len(blob) - (damage == "one_byte_short")
        return real_write(path, bad)

    monkeypatch.setattr(live, "_write_archive_bytes", damaged_write)
    flush["outcome"] = live._DIR_FLUSHED  # a flush would succeed; the copy is what is wrong

    clock["now"] = NOW + RETRY
    with caplog.at_level(logging.WARNING, logger=live.__name__):
        assert str(_obs_dir()) not in live.prune_retention(SEASON, PRUNE_WEEK)

    assert _accepted().read_bytes() == accepted_bytes  # never replaced by the bad copy
    assert flush["calls"] == 1  # no rename, so no flush
    assert _marker() == _unflushed_rewrite_marker(NOW + RETRY)
    assert _obs_dir().is_dir() and _weekly_log_bytes() == before
    assert any(
        "byte-identical rewrite" in r.getMessage() and "readback_mismatch" in r.getMessage()
        for r in caplog.records
    )
    assert (_week_dir() / CANDIDATE).read_bytes() != accepted_bytes  # left for the next attempt

    monkeypatch.setattr(live, "_write_archive_bytes", real_write)  # the fault clears
    clock["now"] = NOW + 2 * RETRY
    assert str(_obs_dir()) in live.prune_retention(SEASON, PRUNE_WEEK)
    assert _accepted().read_bytes() == accepted_bytes
    assert not (_week_dir() / CANDIDATE).exists()  # overwritten, then moved into place


@pytest.mark.parametrize(
    "fault", ["temp_file_write", "temp_file_fsync", "rename_to_candidate", "rename_over_accepted"]
)
def test_a_rewrite_that_cannot_be_written_fails_closed(monkeypatch, clock, fault):
    flush = _fail_the_first_flush(monkeypatch, live._DIR_FSYNC_FAILED)
    accepted_bytes = _accepted().read_bytes()
    before = _weekly_log_bytes()
    if fault == "temp_file_write":
        (_week_dir() / (CANDIDATE + ".tmp")).mkdir()  # the copy's temp file cannot be opened
    elif fault == "temp_file_fsync":

        def fsync(fd):
            raise OSError(errno.EIO, "Input/output error")

        monkeypatch.setattr(os, "fsync", fsync)
    else:
        real_replace = pathlib.Path.replace

        def replace(self, target):
            if fault == "rename_to_candidate":
                hit = pathlib.Path(target).name == CANDIDATE
            else:
                hit = pathlib.Path(target) == _accepted()
            if hit:
                raise OSError(errno.EIO, "Input/output error", str(target))
            return real_replace(self, target)

        monkeypatch.setattr(pathlib.Path, "replace", replace)
    flush["outcome"] = live._DIR_FLUSHED

    clock["now"] = NOW + RETRY
    assert str(_obs_dir()) not in live.prune_retention(SEASON, PRUNE_WEEK)

    assert _accepted().read_bytes() == accepted_bytes
    assert live._read_pregame_archive(_accepted()) is not None
    assert flush["calls"] == 1
    assert _marker() == _unflushed_rewrite_marker(NOW + RETRY)
    assert _obs_dir().is_dir() and _weekly_log_bytes() == before


@pytest.mark.parametrize("fault", ["candidate_write_enospc", "archive_read_eio", "temp_squatter"])
def test_a_rewrite_that_fails_with_no_failure_on_record_is_marked_throttled_and_retried(
    monkeypatch, clock, fault
):
    """No flush was attempted, so the marker names the step that did fail:
    ``flushFailure: "rewrite"`` -- not ``null``, whose alert said the directory
    "could not be flushed".  It is throttled like every reason, and retried by
    the rewrite.  (The reviewer's round-5 probe: ENOSPC on the candidate write.)"""
    _record(PRE_KICKOFF_FETCH, REAL_FETCH)
    live._write_pregame_archive(_accepted(), _good_payload())  # accepted, no marker
    accepted_bytes = _accepted().read_bytes()
    flush = _stub_dir_flush(monkeypatch, live._DIR_FLUSHED)
    writes = _record_archive_writes(monkeypatch)
    squatter = _week_dir() / (CANDIDATE + ".tmp")
    undo = []
    if fault == "temp_squatter":
        squatter.mkdir()  # the copy's temp file cannot be opened
        undo.append(squatter.rmdir)
    elif fault == "candidate_write_enospc":
        recording = live._write_archive_bytes

        def full(path, blob):
            raise OSError(errno.ENOSPC, "No space left on device", str(path))

        monkeypatch.setattr(live, "_write_archive_bytes", full)
        undo.append(lambda: monkeypatch.setattr(live, "_write_archive_bytes", recording))
    else:
        real_read = pathlib.Path.read_bytes

        def read_bytes(self):
            if self == _accepted():
                raise OSError(errno.EIO, "Input/output error", str(self))
            return real_read(self)

        monkeypatch.setattr(pathlib.Path, "read_bytes", read_bytes)
        undo.append(lambda: monkeypatch.setattr(pathlib.Path, "read_bytes", real_read))

    assert str(_obs_dir()) not in live.prune_retention(SEASON, PRUNE_WEEK)
    assert _marker() == {
        "failedAt": live._iso(NOW),
        "firstFailedAt": live._iso(NOW),
        "flushFailure": "rewrite",
        "reason": "archive_directory_unflushed",
    }
    assert flush["calls"] == 0  # the rewrite never reached its flush
    assert not (_week_dir() / CANDIDATE).exists()  # nothing reached the candidate either
    rows = live.pregame_archive_health()
    assert rows is not None and [(r["reason"], r["flushFailure"]) for r in rows] == [
        ("archive_directory_unflushed", "rewrite")
    ]
    (alert,) = oa._check_pregame_archive(rows)
    assert "the byte-identical rewrite that re-establishes the rename" in alert.detail
    assert "could not be flushed to disk" not in alert.detail
    assert alert.detail.endswith(
        "This resolves when the byte-identical rewrite and its directory flush succeed."
    )
    first_writes = len(writes)

    clock["now"] = NOW + 60  # throttled: nothing is rewritten
    assert str(_obs_dir()) not in live.prune_retention(SEASON, PRUNE_WEEK)
    assert len(writes) == first_writes and flush["calls"] == 0

    for fix in undo:
        fix()
    clock["now"] = NOW + RETRY
    assert str(_obs_dir()) in live.prune_retention(SEASON, PRUNE_WEEK)
    assert writes[first_writes:] == [(CANDIDATE, _sha(accepted_bytes))] and flush["calls"] == 1
    assert _accepted().read_bytes() == accepted_bytes  # untouched by the failed attempt too
    assert not live._pregame_failure_path(SEASON, WEEK).exists()


@pytest.mark.parametrize(
    "beside",
    [
        "no_marker",
        "unrelated_marker",
        "candidate_flow_mismatch",
        "raw_log_prune_failed",
        "unflushed_open",
        "unflushed_fsync",
        "unflushed_rewrite",
        "unflushed_unknown_kind",
        "unflushed_null_kind",
        "unflushed_no_kind",
    ],
)
def test_an_accepted_archive_with_a_retained_raw_log_is_always_rewritten(monkeypatch, beside):
    """No marker earns a bare re-flush -- a recorded ``open`` failure included,
    since a marker is best effort and can be stale.  With no marker (one whose
    write failed after an fsync error, say) or any marker, the pass that lets the
    raw log go first rewrites the archive's own bytes, so its flush covers a
    rename made after any consumed error."""
    _record(PRE_KICKOFF_FETCH, REAL_FETCH)
    live._write_pregame_archive(_accepted(), _good_payload())
    accepted_bytes = _accepted().read_bytes()
    marker = live._pregame_failure_path(SEASON, WEEK)
    if beside == "unrelated_marker":
        live._mark_pregame_failure(marker, NOW, "kickoffs_unknown")
    elif beside == "candidate_flow_mismatch":
        live._mark_pregame_failure(marker, NOW, "archive_readback_mismatch", candidate_flow=True)
    elif beside == "raw_log_prune_failed":
        live._mark_raw_log_prune_failed(marker, NOW, None)
    elif beside != "no_marker":
        fields = {
            "unflushed_open": {"flushFailure": "open"},
            "unflushed_fsync": {"flushFailure": "fsync"},
            "unflushed_rewrite": {"flushFailure": "rewrite"},
            "unflushed_unknown_kind": {"flushFailure": "dir_sync"},
            "unflushed_null_kind": {"flushFailure": None},
            "unflushed_no_kind": {},
        }[beside]
        live._mark_pregame_failure(marker, NOW, "archive_directory_unflushed", fields=fields)
    events: list[str] = []
    flush = _stub_dir_flush(monkeypatch, live._DIR_FLUSHED)
    flush["events"] = events
    builds = _count_builds(monkeypatch)
    writes = _record_archive_writes(monkeypatch, events)

    assert live.ensure_pregame_archive(SEASON, WEEK, now=NOW + RETRY) is True

    assert builds == []
    assert writes == [(CANDIDATE, _sha(accepted_bytes))]  # rewritten, not merely re-flushed
    assert events == [f"write:{CANDIDATE}", "dir-flush"]
    assert _accepted().read_bytes() == accepted_bytes
    assert not marker.exists()


@pytest.mark.parametrize("second_flush", [live._DIR_FLUSHED, live._DIR_FSYNC_FAILED])
def test_an_fsync_error_whose_marker_was_lost_is_never_re_flushed_and_pruned(
    monkeypatch, clock, second_flush
):
    """The correlated failure: the build's rename, the directory fsync fails with
    EIO (reported once, so consumed), and the marker write then fails with ENOSPC
    and is swallowed.  The next pass finds NO marker, and a fresh fsync would
    return 0 for a rename that may never have reached disk.  It rewrites the
    archive's bytes first, so the raw log is pruned only behind a flush of a
    rename made after the error."""
    _record(PRE_KICKOFF_FETCH, REAL_FETCH)
    flush = _stub_dir_flush(monkeypatch, live._DIR_FSYNC_FAILED)
    deny = {"marker": True}
    real_write = live._atomic_write_json

    def write(path, payload):
        if deny["marker"] and pathlib.Path(path).name == live.PREGAME_ARCHIVE_FAILURE_NAME:
            raise OSError(errno.ENOSPC, "No space left on device", str(path))
        return real_write(path, payload)

    monkeypatch.setattr(live, "_atomic_write_json", write)

    assert str(_obs_dir()) not in live.prune_retention(SEASON, PRUNE_WEEK)  # pass 1
    assert flush["calls"] == 1
    assert not live._pregame_failure_path(SEASON, WEEK).exists()  # the marker was lost
    accepted_bytes = _accepted().read_bytes()
    before = _weekly_log_bytes()

    deny["marker"] = False
    events: list[str] = []
    flush["events"] = events
    flush["outcome"] = second_flush
    builds = _count_builds(monkeypatch)
    writes = _record_archive_writes(monkeypatch, events)

    clock["now"] = NOW + 60  # no marker, so no throttle either
    removed = live.prune_retention(SEASON, PRUNE_WEEK)

    assert builds == [] and writes == [(CANDIDATE, _sha(accepted_bytes))]
    assert events == [f"write:{CANDIDATE}", "dir-flush"]  # the flush follows a NEW rename
    assert _accepted().read_bytes() == accepted_bytes
    if second_flush == live._DIR_FLUSHED:
        assert str(_obs_dir()) in removed and not _obs_dir().exists()
    else:
        assert str(_obs_dir()) not in removed and _weekly_log_bytes() == before
        assert _marker()["flushFailure"] == "fsync"


@pytest.mark.parametrize("prior", ["fsync_failure", "no_marker"])
def test_a_rewrite_on_a_platform_with_no_directory_flush_is_trusted(monkeypatch, clock, prior):
    """``"unsupported"`` after the rewrite is the platform's own durability, as on
    every other path: the raw log goes."""
    if prior == "fsync_failure":
        flush = _fail_the_first_flush(monkeypatch, live._DIR_FSYNC_FAILED)
    else:
        _record(PRE_KICKOFF_FETCH, REAL_FETCH)
        live._write_pregame_archive(_accepted(), _good_payload())
        flush = _stub_dir_flush(monkeypatch, live._DIR_FLUSH_UNSUPPORTED)
    accepted_bytes = _accepted().read_bytes()
    writes = _record_archive_writes(monkeypatch)
    flush["outcome"] = live._DIR_FLUSH_UNSUPPORTED

    clock["now"] = NOW + RETRY
    removed = live.prune_retention(SEASON, PRUNE_WEEK)

    assert writes == [(CANDIDATE, _sha(accepted_bytes))]
    assert str(_obs_dir()) in removed and not _obs_dir().exists()
    assert _accepted().read_bytes() == accepted_bytes
    assert not live._pregame_failure_path(SEASON, WEEK).exists()


def test_an_unflushed_marker_with_no_recorded_step_is_rewritten(monkeypatch, clock):
    """A marker written before ``flushFailure`` existed takes the byte-identical
    rewrite like every other; its ``failedAt`` is the best start."""
    _record(PRE_KICKOFF_FETCH, REAL_FETCH)
    assert live.ensure_pregame_archive(SEASON, WEEK) is True  # built + flushed (clock: NOW)
    accepted_bytes = _accepted().read_bytes()
    marker = live._pregame_failure_path(SEASON, WEEK)
    live._mark_pregame_failure(marker, NOW, "archive_directory_unflushed")  # the old shape
    flush = _stub_dir_flush(monkeypatch, live._DIR_FSYNC_FAILED)
    builds = _count_builds(monkeypatch)
    writes = _record_archive_writes(monkeypatch)

    clock["now"] = NOW + 60  # throttled by the old marker's failedAt too
    live.prune_retention(SEASON, PRUNE_WEEK)
    assert flush["calls"] == 0 and builds == [] and writes == []

    clock["now"] = NOW + RETRY
    live.prune_retention(SEASON, PRUNE_WEEK)
    assert builds == [] and writes == [(CANDIDATE, _sha(accepted_bytes))]
    assert flush["calls"] == 1
    assert _marker()["firstFailedAt"] == live._iso(NOW) and _marker()["flushFailure"] == "fsync"
    assert _accepted().read_bytes() == accepted_bytes


def test_the_latest_kind_is_recorded_but_decides_nothing(monkeypatch, clock):
    """The marker records the step of the LATEST attempt (an open failure after
    an fsync one, the start kept) -- and the next retry rewrites anyway."""
    flush = _fail_the_first_flush(monkeypatch, live._DIR_FSYNC_FAILED)
    accepted_bytes = _accepted().read_bytes()
    builds = _count_builds(monkeypatch)
    writes = _record_archive_writes(monkeypatch)

    flush["outcome"] = live._DIR_OPEN_FAILED
    clock["now"] = NOW + RETRY
    live.prune_retention(SEASON, PRUNE_WEEK)
    assert builds == [] and len(writes) == 1  # fsync -> rewritten
    assert _marker()["flushFailure"] == "open" and _marker()["firstFailedAt"] == live._iso(NOW)

    flush["outcome"] = live._DIR_FLUSHED
    clock["now"] = NOW + 2 * RETRY
    removed = live.prune_retention(SEASON, PRUNE_WEEK)
    assert builds == [] and writes == [(CANDIDATE, _sha(accepted_bytes))] * 2  # open -> rewritten
    assert _accepted().read_bytes() == accepted_bytes
    assert str(_obs_dir()) in removed and not _obs_dir().exists()


def test_the_alert_shows_when_the_flush_failure_began(monkeypatch, clock):
    flush = _fail_the_first_flush(monkeypatch, live._DIR_OPEN_FAILED)
    for later in (NOW + RETRY, NOW + 2 * RETRY):
        clock["now"] = later
        live.prune_retention(SEASON, PRUNE_WEEK)
    assert flush["calls"] == 3

    rows = live.pregame_archive_health()
    assert rows is not None and len(rows) == 1
    assert rows[0]["failedAt"] == live._iso(NOW + 2 * RETRY)  # the latest attempt ...
    assert rows[0]["firstFailedAt"] == live._iso(NOW)  # ... and the start
    (alert,) = oa._check_pregame_archive(rows)
    assert f"failing since {live._iso(NOW)}" in alert.detail
    assert live._iso(NOW + 2 * RETRY) not in alert.detail


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
        outcome = live._fsync_dir(tmp_path)

    assert outcome == "flushed"
    assert calls == [("open", tmp_path, os.O_RDONLY), ("fsync", 77), ("close", 77)]


# These patch ``os.name`` as well as the calls, so BOTH platforms' rules run on
# every host (no platform skips).  Nothing may build a ``Path`` while ``os.name``
# is patched -- ``Path()`` reads it -- so every check happens after the context.


def test_fsync_dir_reports_the_windows_directory_refusal_as_unsupported(
    monkeypatch, tmp_path, caplog
):
    """Windows: ``os.open`` on a directory raises ``PermissionError``.  Expected,
    so DEBUG and ``"unsupported"`` -- never a warning, never ``"failed"``."""
    fsynced: list[int] = []
    refusal = PermissionError(13, "Permission denied", str(tmp_path))

    def refuse(path, flags, *a, **k):
        raise refusal

    with caplog.at_level(logging.DEBUG, logger=live.__name__):
        with monkeypatch.context() as patch:
            patch.setattr(os, "name", "nt")
            patch.setattr(os, "open", refuse)
            patch.setattr(os, "fsync", lambda fd: fsynced.append(fd))
            outcome = live._fsync_dir(tmp_path)

    assert outcome == "unsupported"
    assert fsynced == []
    levels = [r.levelno for r in caplog.records if r.name == live.__name__]
    assert levels == [logging.DEBUG]


@pytest.mark.parametrize(
    ("platform", "error"),
    [
        # A permission refusal is only "the platform cannot" on Windows.
        ("posix", PermissionError(13, "Permission denied")),
        ("posix", OSError(24, "Too many open files")),
        ("posix", FileNotFoundError(2, "No such file or directory")),
        # ... and on Windows anything else is still a failure.
        ("nt", OSError(24, "Too many open files")),
        ("nt", FileNotFoundError(2, "No such file or directory")),
    ],
    ids=["posix-EACCES", "posix-EMFILE", "posix-ENOENT", "nt-EMFILE", "nt-ENOENT"],
)
def test_fsync_dir_reports_any_other_open_failure_as_failed(
    monkeypatch, tmp_path, caplog, platform, error
):
    fsynced: list[int] = []

    def refuse(path, flags, *a, **k):
        raise error

    with caplog.at_level(logging.DEBUG, logger=live.__name__):
        with monkeypatch.context() as patch:
            patch.setattr(os, "name", platform)
            patch.setattr(os, "open", refuse)
            patch.setattr(os, "fsync", lambda fd: fsynced.append(fd))
            outcome = live._fsync_dir(tmp_path)

    # FAILED, at the open step (no fsync ran), which the marker records.
    assert outcome == "open_failed"
    assert live._dir_flush_failure(outcome) == "open"
    assert fsynced == []
    warnings = [
        r.getMessage()
        for r in caplog.records
        if r.name == live.__name__ and r.levelno == logging.WARNING
    ]
    assert len(warnings) == 1 and "could not open directory" in warnings[0]


def test_dir_flush_failure_maps_each_known_outcome():
    assert live._dir_flush_failure(live._DIR_FLUSHED) is None
    assert live._dir_flush_failure(live._DIR_FLUSH_UNSUPPORTED) is None
    assert live._dir_flush_failure(live._DIR_OPEN_FAILED) == "open"
    assert live._dir_flush_failure(live._DIR_FSYNC_FAILED) == "fsync"


@pytest.mark.parametrize(
    "outcome", ["", "failed", "open", "Open_failed", "open_failed ", "partial"]
)
def test_an_unknown_flush_outcome_is_reported_as_an_fsync_failure(outcome):
    """Only the exact ``open_failed`` outcome is reported as the open step.
    Anything else this code does not know -- including ``"failed"``, the outcome
    before the step was recorded, and the KIND ``"open"`` passed as an outcome --
    is a flush that did not succeed: ``"fsync"``.  (Diagnostic only: no kind
    lets a retry skip the rewrite.)"""
    assert live._dir_flush_failure(outcome) == "fsync"


def test_fsync_dir_closes_the_handle_and_warns_when_the_flush_fails(monkeypatch, tmp_path, caplog):
    closed: list[int] = []

    def fsync(fd):
        raise OSError(5, "Input/output error")

    with monkeypatch.context() as patch:
        patch.setattr(os, "open", lambda path, flags, *a, **k: 78)
        patch.setattr(os, "fsync", fsync)
        patch.setattr(os, "close", lambda fd: closed.append(fd))
        with caplog.at_level(logging.WARNING, logger=live.__name__):
            outcome = live._fsync_dir(tmp_path)

    assert outcome == "fsync_failed"
    assert live._dir_flush_failure(outcome) == "fsync"
    assert closed == [78]
    assert any("could not flush directory" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize(("fsync_fails", "expected"), [(False, "flushed"), (True, "fsync_failed")])
def test_fsync_dir_never_raises_when_the_close_fails(
    monkeypatch, tmp_path, caplog, fsync_fails, expected
):
    """A close error is logged; the outcome is the ``fsync``'s, which ran first."""

    def fsync(fd):
        if fsync_fails:
            raise OSError(5, "Input/output error")

    def close(fd):
        raise OSError(5, "Input/output error")

    with monkeypatch.context() as patch:
        patch.setattr(os, "open", lambda path, flags, *a, **k: 79)
        patch.setattr(os, "fsync", fsync)
        patch.setattr(os, "close", close)
        with caplog.at_level(logging.WARNING, logger=live.__name__):
            outcome = live._fsync_dir(tmp_path)

    assert outcome == expected
    assert any("could not close directory" in r.getMessage() for r in caplog.records)


# --- a filesystem that refuses a directory fsync is "unsupported", not a failure ----------

#: Present on this host; a platform lacking one is simply not tested for it.
_UNSUPPORTED_FSYNC_ERRNOS = [n for n in ("EINVAL", "ENOTSUP", "EOPNOTSUPP") if hasattr(errno, n)]
_FAILED_FSYNC_ERRNOS = [
    n for n in ("EIO", "ENOSPC", "EROFS", "EBADF", "EACCES", "EDQUOT") if hasattr(errno, n)
]


def test_the_unsupported_fsync_errnos_skip_constants_a_platform_lacks():
    assert live._DIR_FSYNC_UNSUPPORTED_ERRNOS == {
        getattr(errno, n) for n in _UNSUPPORTED_FSYNC_ERRNOS
    }
    lacking = types.SimpleNamespace(EINVAL=22)  # e.g. no ENOTSUP / EOPNOTSUPP
    assert live._errno_codes(lacking, ("EINVAL", "ENOTSUP", "EOPNOTSUPP")) == {22}


@pytest.mark.parametrize("name", _UNSUPPORTED_FSYNC_ERRNOS)
def test_fsync_dir_reports_a_filesystem_that_refuses_directory_fsync_as_unsupported(
    monkeypatch, tmp_path, caplog, name
):
    """Some FUSE, CIFS, 9p and drvfs mounts refuse ``fsync`` on a directory on
    EVERY call: the platform offers no flush, so ``"unsupported"`` -- else every
    week is held forever.  INFO once per process, then DEBUG; never a WARNING."""
    code = getattr(errno, name)
    closed: list[int] = []
    monkeypatch.setattr(live, "_dir_fsync_unsupported_reported", False)

    def fsync(fd):
        raise OSError(code, os.strerror(code))

    with monkeypatch.context() as patch:
        patch.setattr(os, "open", lambda path, flags, *a, **k: 80)
        patch.setattr(os, "fsync", fsync)
        patch.setattr(os, "close", lambda fd: closed.append(fd))
        with caplog.at_level(logging.DEBUG, logger=live.__name__):
            outcomes = [live._fsync_dir(tmp_path) for _ in range(3)]

    assert outcomes == ["unsupported"] * 3
    assert live._dir_flush_failure(outcomes[0]) is None  # the rename is trusted
    assert closed == [80, 80, 80]
    levels = [r.levelno for r in caplog.records if r.name == live.__name__]
    assert levels == [logging.INFO, logging.DEBUG, logging.DEBUG]


@pytest.mark.parametrize("name", _FAILED_FSYNC_ERRNOS)
def test_fsync_dir_reports_every_other_fsync_errno_as_failed(monkeypatch, tmp_path, caplog, name):
    code = getattr(errno, name)
    monkeypatch.setattr(live, "_dir_fsync_unsupported_reported", False)

    def fsync(fd):
        raise OSError(code, os.strerror(code))

    with monkeypatch.context() as patch:
        patch.setattr(os, "open", lambda path, flags, *a, **k: 81)
        patch.setattr(os, "fsync", fsync)
        patch.setattr(os, "close", lambda fd: None)
        with caplog.at_level(logging.DEBUG, logger=live.__name__):
            outcome = live._fsync_dir(tmp_path)

    assert outcome == "fsync_failed" and live._dir_flush_failure(outcome) == "fsync"
    records = [r for r in caplog.records if r.name == live.__name__]
    assert [r.levelno for r in records] == [logging.WARNING]
    assert "could not flush directory" in records[0].getMessage()


def test_a_filesystem_that_refuses_directory_fsync_still_archives_and_prunes(
    monkeypatch, clock, caplog
):
    """End to end: ``EINVAL`` from every directory fsync -- the week is archived
    and its raw log pruned, not held and retried forever."""
    _record(PRE_KICKOFF_FETCH, REAL_FETCH)
    monkeypatch.setattr(live, "_dir_fsync_unsupported_reported", False)
    real_open, real_fsync, real_close = os.open, os.fsync, os.close
    dir_fd = 9001  # a stand-in handle for the week directory (Windows cannot open one)
    flushed: list[int] = []

    def fake_open(path, flags, *args, **kwargs):
        if not kwargs and pathlib.Path(path) == _week_dir():
            return dir_fd
        return real_open(path, flags, *args, **kwargs)

    def fake_fsync(fd):
        if fd == dir_fd:
            flushed.append(fd)
            raise OSError(errno.EINVAL, "Invalid argument")
        return real_fsync(fd)

    def fake_close(fd):
        return None if fd == dir_fd else real_close(fd)

    monkeypatch.setattr(os, "open", fake_open)
    monkeypatch.setattr(os, "fsync", fake_fsync)
    monkeypatch.setattr(os, "close", fake_close)
    with caplog.at_level(logging.DEBUG, logger=live.__name__):
        removed = live.prune_retention(SEASON, PRUNE_WEEK)

    assert flushed == [dir_fd]  # the directory flush was attempted, and refused
    assert str(_obs_dir()) in removed and not _obs_dir().exists()
    assert live._read_pregame_archive(_accepted()) is not None
    assert not live._pregame_failure_path(SEASON, WEEK).exists()
    assert live.pregame_archive_health() == []
    assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []
    assert [r.levelno for r in caplog.records if "cannot flush directory" in r.getMessage()] == [
        logging.INFO
    ]


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
    real_unlink = _deny_marker_unlink(monkeypatch)
    assert live.ensure_pregame_archive(SEASON, WEEK, now=NOW + RETRY + 1) is True  # verified
    assert marker.exists()  # ... and the stale marker could not be removed
    accepted_bytes = _accepted().read_bytes()
    archive = live._read_pregame_archive(_accepted())
    assert archive is not None and len(archive["players"]) == len(good["players"])
    assert _obs_dir().is_dir()  # the raw log is still there to tempt a rebuild

    builds = _count_builds(monkeypatch)
    writes = _record_archive_writes(monkeypatch)
    # The stale candidate-flow marker records nothing pending on this archive,
    # so it throttles nothing -- not even at NOW + 60, inside its window (as
    # after a clock stepped back).  Every pass keeps the archive by the
    # byte-identical rewrite, since the raw log is still here.
    passes = [(NOW + 60, True, 1), (NOW + RETRY + 60, True, 2), (NOW + 3 * RETRY, True, 3)]
    for later, accepted, rewrites in passes:
        assert live.ensure_pregame_archive(SEASON, WEEK, now=later) is accepted
        assert builds == []  # not rebuilt
        assert writes == [(CANDIDATE, _sha(accepted_bytes))] * rewrites
        assert _accepted().read_bytes() == accepted_bytes  # only ever its own bytes
        assert aside.read_bytes() == aside_bytes  # and not set aside over the diagnosis copy

    # Once the marker can be removed, it is.
    monkeypatch.setattr(pathlib.Path, "unlink", real_unlink)
    assert live.ensure_pregame_archive(SEASON, WEEK, now=NOW + 4 * RETRY) is True
    assert not marker.exists()
    assert live.pregame_archive_health() == []


def test_a_pre_fix_leftover_rebuilt_beside_an_unclearable_marker_is_not_rebuilt_again(monkeypatch):
    """legacy leftover -> set aside -> verified rebuild -> the marker unlink fails -> later passes.

    The pre-fix marker carries no ``candidateFlow``.  Were it left that way, every
    later pass that still found the raw log would take the GOOD rebuild for the
    pre-fix leftover: set it aside -- over the ``.mismatch`` copy of the original
    bad file -- and rebuild it, every tick.  Setting the leftover aside re-stamps
    the marker as candidate-flow (keeping its failedAt), so they do not."""
    _record(PRE_KICKOFF_FETCH, REAL_FETCH)
    good = _good_payload()
    bad_bytes = _pre_fix_leftover()
    marker = live._pregame_failure_path(SEASON, WEEK)
    aside = _week_dir() / MISMATCH
    _deny_marker_unlink(monkeypatch)

    # Past the throttle: the leftover is set aside, rebuilt, verified, accepted.
    assert live.ensure_pregame_archive(SEASON, WEEK, now=NOW + RETRY + 1) is True
    assert marker.exists()  # the stale marker could not be removed ...
    assert _marker() == {  # ... but it now has the candidate-flow meaning
        "failedAt": live._iso(NOW),
        "reason": "archive_readback_mismatch",
        "candidateFlow": True,
    }
    assert aside.read_bytes() == bad_bytes
    accepted_bytes = _accepted().read_bytes()
    archive = live._read_pregame_archive(_accepted())
    assert archive is not None and len(archive["players"]) == len(good["players"])
    assert _obs_dir().is_dir()  # e.g. the prune's rmtree could not remove it

    builds = _count_builds(monkeypatch)
    for later in (NOW + RETRY + 60, NOW + 2 * RETRY, NOW + 3 * RETRY):
        assert live.ensure_pregame_archive(SEASON, WEEK, now=later) is True
        assert builds == []  # not rebuilt
        assert _accepted().read_bytes() == accepted_bytes  # the good archive is kept
        assert aside.read_bytes() == bad_bytes  # the diagnosis copy is still the ORIGINAL


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


# --- with no raw weekly log left, an accepted archive is re-flushed only ------------------


def _drop_the_weekly_log() -> None:
    """Remove the raw weekly log (and its head cache) but keep ``observations/``
    with another file in it, so the prune still visits the week."""
    log = live.observation_log(live.NFL_KEY, SEASON, WEEK, live.SOURCE_WEEKLY)
    log.log_path.unlink()
    log.head_path.unlink(missing_ok=True)
    (_obs_dir() / "other_source.jsonl").write_text("{}\n", encoding="utf-8")


@pytest.mark.parametrize("beside", ["no_marker", "open", "fsync", "rewrite"])
def test_an_accepted_archive_with_no_raw_weekly_log_is_re_flushed_only(monkeypatch, clock, beside):
    """The documented branch: nothing is left to rebuild from, so nothing is
    protected by a rewrite -- the archive is re-flushed only, NEVER rewritten
    (and never rebuilt), whatever marker is beside it."""
    _record(PRE_KICKOFF_FETCH, REAL_FETCH)
    live._write_pregame_archive(_accepted(), _good_payload())
    accepted_bytes = _accepted().read_bytes()
    _drop_the_weekly_log()
    marker = live._pregame_failure_path(SEASON, WEEK)
    if beside != "no_marker":
        live._mark_directory_unflushed(marker, NOW - 2 * RETRY, beside, None)
    flush = _stub_dir_flush(monkeypatch, live._DIR_FSYNC_FAILED)
    builds = _count_builds(monkeypatch)
    writes = _record_archive_writes(monkeypatch)

    # A failed flush keeps observations/ and records the step; nothing is written.
    assert str(_obs_dir()) not in live.prune_retention(SEASON, PRUNE_WEEK)
    assert flush["calls"] == 1 and writes == [] and builds == []
    assert _marker()["flushFailure"] == "fsync"

    flush["outcome"] = live._DIR_FLUSHED
    clock["now"] = NOW + RETRY
    removed = live.prune_retention(SEASON, PRUNE_WEEK)

    assert str(_obs_dir()) in removed and not _obs_dir().exists()
    assert flush["calls"] == 2 and writes == [] and builds == []  # re-flushed only
    assert _accepted().read_bytes() == accepted_bytes
    assert not marker.exists()


# --- only a RETRY-family marker inside the window throttles the accepted archive ---------


_RETRY_FAMILY_MARKERS = [
    ("archive_directory_unflushed", {"flushFailure": "open"}),
    ("archive_directory_unflushed", {"flushFailure": "fsync"}),
    ("archive_directory_unflushed", {"flushFailure": "rewrite"}),
    ("archive_directory_unflushed", {"flushFailure": None}),
    ("archive_directory_unflushed", {"flushFailure": "dir_sync"}),
    ("archive_directory_unflushed", {}),
    ("raw_log_prune_failed", {}),
]
_RETRY_FAMILY_IDS = [
    "unflushed-open",
    "unflushed-fsync",
    "unflushed-rewrite",
    "unflushed-null",
    "unflushed-unknown-kind",
    "unflushed-no-kind",
    "raw_log_prune_failed",
]
# Markers that record nothing pending on a readable accepted archive.
_NOT_RETRY_MARKERS = [
    ("archive_unreadable", {}),
    ("archive_readback_mismatch", {"candidateFlow": True}),
    ("kickoffs_unknown", {}),
    ("weekly_log_unreadable", {}),
    ("OSError: [Errno 28] No space left on device", {}),
]
_NOT_RETRY_IDS = [
    "archive_unreadable",
    "candidate_flow_mismatch",
    "kickoffs_unknown",
    "weekly_log_unreadable",
    "exception",
]


def _accepted_archive_beside(reason: str, fields: dict, weekly_log: str) -> pathlib.Path:
    """A readable accepted archive with a ``reason`` marker written at ``NOW``."""
    _record(PRE_KICKOFF_FETCH, REAL_FETCH)
    live._write_pregame_archive(_accepted(), _good_payload())
    if weekly_log == "gone":
        _drop_the_weekly_log()
    marker = live._pregame_failure_path(SEASON, WEEK)
    fields = dict(fields)
    candidate_flow = bool(fields.pop("candidateFlow", False))
    live._write_pregame_marker(marker, NOW, reason, candidate_flow=candidate_flow, fields=fields)
    return marker


def test_the_retry_family_is_exactly_the_pending_work_on_an_accepted_archive():
    assert live._PREGAME_RETRY_REASONS == {"archive_directory_unflushed", "raw_log_prune_failed"}


@pytest.mark.parametrize(("reason", "fields"), _RETRY_FAMILY_MARKERS, ids=_RETRY_FAMILY_IDS)
@pytest.mark.parametrize("weekly_log", ["retained", "gone"])
def test_a_retry_family_marker_inside_the_window_throttles_the_accepted_archive(
    monkeypatch, caplog, reason, fields, weekly_log
):
    """Every rewrite path -- and the re-flush-only path beside it -- respects the
    hourly throttle while a RETRY-family marker (pending work on this archive)
    is inside its window: a pass flushes nothing, rewrites nothing, rebuilds
    nothing, logs nothing and leaves the marker as it was."""
    marker = _accepted_archive_beside(reason, fields, weekly_log)
    marker_bytes = marker.read_bytes()
    flush = _stub_dir_flush(monkeypatch, live._DIR_FLUSHED)
    builds = _count_builds(monkeypatch)
    writes = _record_archive_writes(monkeypatch)

    with caplog.at_level(logging.DEBUG, logger=live.__name__):
        for later in (NOW + 1, NOW + 60, NOW + RETRY - 1):
            assert live.ensure_pregame_archive(SEASON, WEEK, now=later) is False
    assert flush["calls"] == 0 and writes == [] and builds == []
    assert marker.read_bytes() == marker_bytes
    assert [r for r in caplog.records if r.name == live.__name__] == []

    assert live.ensure_pregame_archive(SEASON, WEEK, now=NOW + RETRY) is True  # the boundary
    assert len(writes) == (1 if weekly_log == "retained" else 0) and flush["calls"] == 1


@pytest.mark.parametrize(("reason", "fields"), _NOT_RETRY_MARKERS, ids=_NOT_RETRY_IDS)
@pytest.mark.parametrize("weekly_log", ["retained", "gone"])
def test_a_marker_with_no_pending_retry_does_not_throttle_the_accepted_archive(
    monkeypatch, reason, fields, weekly_log
):
    """A marker that records no pending work on the readable archive beside it --
    a repaired ``archive_unreadable`` file, a stale build failure, a candidate-flow
    mismatch marker that could not be cleared -- throttles nothing: the very next
    pass (here one second later) re-establishes the archive and accepts it, by
    the byte-identical rewrite while the weekly log remains, by a re-flush once
    it is gone."""
    marker = _accepted_archive_beside(reason, fields, weekly_log)
    accepted_bytes = _accepted().read_bytes()
    flush = _stub_dir_flush(monkeypatch, live._DIR_FLUSHED)
    builds = _count_builds(monkeypatch)
    writes = _record_archive_writes(monkeypatch)

    assert live.ensure_pregame_archive(SEASON, WEEK, now=NOW + 1) is True

    expected = [(CANDIDATE, _sha(accepted_bytes))] if weekly_log == "retained" else []
    assert writes == expected and flush["calls"] == 1 and builds == []
    assert _accepted().read_bytes() == accepted_bytes
    assert not marker.exists()


# --- a raw log that survives the prune is recorded, throttled and alerted ----------------


def _stub_rmtree(monkeypatch) -> dict:
    """Make ``shutil.rmtree`` (as the prune calls it, ``ignore_errors=True``) fail
    silently while ``state["fail"]`` is true -- a permission error or a Windows
    lock; ``state["calls"]`` counts the attempts."""
    state = {"fail": True, "calls": 0}
    real = shutil.rmtree

    def rmtree(path, *args, **kwargs):
        state["calls"] += 1
        if not state["fail"]:
            return real(path, *args, **kwargs)
        return None

    monkeypatch.setattr(shutil, "rmtree", rmtree)
    return state


def _prune_marker(failed_at: float, first: float) -> dict:
    return {
        "failedAt": live._iso(failed_at),
        "firstFailedAt": live._iso(first),
        "reason": "raw_log_prune_failed",
    }


def test_a_raw_log_that_survives_the_prune_is_recorded_throttled_and_never_churns(
    monkeypatch, clock, caplog
):
    """The reviewers' round-5 churn probe.  ``rmtree(observations, ignore_errors=True)``
    can fail silently.  It used to leave no marker, so every one-minute tick
    rewrote the archive and deleted again, without limit and unseen.  Now the
    survival is detected, warned, recorded as ``raw_log_prune_failed`` and
    reported -- and that marker throttles every later pass to hourly."""
    _record(PRE_KICKOFF_FETCH, REAL_FETCH)
    flush = _stub_dir_flush(monkeypatch, live._DIR_FLUSHED)
    rm = _stub_rmtree(monkeypatch)
    builds = _count_builds(monkeypatch)
    writes = _record_archive_writes(monkeypatch)

    with caplog.at_level(logging.WARNING, logger=live.__name__):
        removed = live.prune_retention(SEASON, PRUNE_WEEK)  # pass 1: built, verified, flushed

    assert removed == [] and _obs_dir().is_dir()  # never reported as removed
    assert rm["calls"] == 1 and builds == [1] and flush["calls"] == 1
    accepted_bytes = _accepted().read_bytes()
    assert _marker() == _prune_marker(NOW, NOW)
    assert any(
        "could not remove raw observations" in r.getMessage()
        and "raw_log_prune_failed" in r.getMessage()
        for r in caplog.records
    )
    rows = live.pregame_archive_health()
    assert rows is not None and len(rows) == 1
    assert (rows[0]["reason"], rows[0]["rawLogRetained"], rows[0]["firstFailedAt"]) == (
        "raw_log_prune_failed",
        True,
        live._iso(NOW),
    )
    (alert,) = oa._check_pregame_archive(rows)
    assert "raw log not removed" in alert.title

    first_writes = len(writes)
    for tick in range(1, 7):  # six one-minute ticks: all inside the window
        clock["now"] = NOW + 60 * tick
        assert live.prune_retention(SEASON, PRUNE_WEEK) == []
    assert len(writes) == first_writes and builds == [1]  # nothing rewritten, nothing rebuilt
    assert rm["calls"] == 1 and flush["calls"] == 1  # nothing deleted, nothing flushed
    assert _marker() == _prune_marker(NOW, NOW)

    # The hourly retry: one byte-identical rewrite, one delete -- which fails again.
    clock["now"] = NOW + RETRY
    assert live.prune_retention(SEASON, PRUNE_WEEK) == []
    assert writes[first_writes:] == [(CANDIDATE, _sha(accepted_bytes))] and rm["calls"] == 2
    assert _marker() == _prune_marker(NOW + RETRY, NOW)  # the start is kept
    for tick in range(1, 7):
        clock["now"] = NOW + RETRY + 60 * tick
        live.prune_retention(SEASON, PRUNE_WEEK)
    assert len(writes) == first_writes + 1 and rm["calls"] == 2

    # The delete works again: the raw log goes, the marker goes, the alert resolves.
    rm["fail"] = False
    clock["now"] = NOW + 2 * RETRY
    assert live.prune_retention(SEASON, PRUNE_WEEK) == [str(_obs_dir())]
    assert not _obs_dir().exists() and not live._pregame_failure_path(SEASON, WEEK).exists()
    assert _accepted().read_bytes() == accepted_bytes
    assert live.pregame_archive_health() == []


def test_an_unmarked_archive_whose_prune_fails_is_rewritten_once_then_throttled(monkeypatch, clock):
    """With no marker at all the first rewrite runs at once; when the prune then
    fails, the marker it records throttles every later pass."""
    _record(PRE_KICKOFF_FETCH, REAL_FETCH)
    live._write_pregame_archive(_accepted(), _good_payload())  # accepted, no marker
    accepted_bytes = _accepted().read_bytes()
    _stub_dir_flush(monkeypatch, live._DIR_FLUSHED)
    rm = _stub_rmtree(monkeypatch)
    writes = _record_archive_writes(monkeypatch)

    for tick in range(0, 8):  # eight one-minute ticks
        clock["now"] = NOW + 60 * tick
        assert live.prune_retention(SEASON, PRUNE_WEEK) == []

    assert writes == [(CANDIDATE, _sha(accepted_bytes))]  # the first tick only
    assert rm["calls"] == 1
    assert _marker() == _prune_marker(NOW, NOW)
    assert _obs_dir().is_dir() and _accepted().read_bytes() == accepted_bytes


def test_a_raw_log_prune_failure_with_no_archive_is_warned_but_not_marked(monkeypatch, caplog):
    """Nothing to archive (no weekly log) and the delete fails: warned and not
    reported as removed -- but there is no archive to rewrite or to describe,
    so no pregame marker.  The same goes for every other league's raw logs."""
    other = live.league_week_dir("lk", SEASON, WEEK) / "observations"
    other.mkdir(parents=True)
    (other / "x.jsonl").write_text("{}\n", encoding="utf-8")
    _obs_dir().mkdir(parents=True)
    (_obs_dir() / "other_source.jsonl").write_text("{}\n", encoding="utf-8")
    _stub_rmtree(monkeypatch)

    with caplog.at_level(logging.WARNING, logger=live.__name__):
        removed = live.prune_retention(SEASON, PRUNE_WEEK, now=NOW)

    assert removed == [] and other.is_dir() and _obs_dir().is_dir()
    assert not live._pregame_failure_path(SEASON, WEEK).exists()
    warned = [r.getMessage() for r in caplog.records if "could not remove raw" in r.getMessage()]
    assert len(warned) == 2
    for message in warned:
        assert "the removal is retried every pass" in message
        assert f"recorded in {live.RAW_PRUNE_FAILURE_NAME}" in message
    # Round 7: the WARNING is limited by a stamp beside each week -- not a
    # pregame marker, and never read as one.
    for week_dir in (other.parent, _week_dir()):
        assert (week_dir / live.RAW_PRUNE_FAILURE_NAME).is_file()
    assert live.pregame_archive_health() == []


# --- round 6: an unreadable archive is re-checked every pass and recorded hourly ---------


def _unreadable_archive_through_the_prune(clock, ticks: int) -> pathlib.Path:
    """Garbage at the archive path, then ``ticks`` one-minute prune passes from ``NOW``."""
    _record(PRE_KICKOFF_FETCH, REAL_FETCH)
    _accepted().parent.mkdir(parents=True, exist_ok=True)
    _accepted().write_bytes(b"garbage")
    for tick in range(ticks):
        clock["now"] = NOW + 60 * tick
        assert live.prune_retention(SEASON, PRUNE_WEEK) == []
    return live._pregame_failure_path(SEASON, WEEK)


def test_a_repaired_unreadable_archive_is_accepted_on_the_next_pass(monkeypatch, clock):
    """The reviewers' round-6 probe T4.  Round 5 throttled the accepted archive on
    ANY marker, and ``archive_unreadable`` was re-recorded every tick -- so a file
    an operator repaired was accepted only at t+3840, while the alert said the
    collector "re-checks the file on every pass".  ``archive_unreadable`` is not
    retry work: the pass right after the repair accepts the archive, and the
    alert resolves."""
    flush = _stub_dir_flush(monkeypatch, live._DIR_FLUSHED)
    marker = _unreadable_archive_through_the_prune(clock, ticks=5)
    assert _marker()["reason"] == "archive_unreadable" and _obs_dir().is_dir()
    assert flush["calls"] == 0
    (alert,) = oa._check_pregame_archive(live.pregame_archive_health())
    assert "The collector re-checks the file on every pass" in alert.detail

    live._write_pregame_archive(_accepted(), _good_payload())  # the operator repairs the file
    repaired = _accepted().read_bytes()
    writes = _record_archive_writes(monkeypatch)
    clock["now"] = NOW + 300  # the next one-minute pass, deep inside the marker's window
    removed = live.prune_retention(SEASON, PRUNE_WEEK)

    assert removed == [str(_obs_dir())] and not _obs_dir().exists()
    assert writes == [(CANDIDATE, _sha(repaired))] and flush["calls"] == 1  # rewritten, flushed
    assert _accepted().read_bytes() == repaired
    assert not marker.exists()
    assert live.pregame_archive_health() == []
    assert oa._check_pregame_archive(live.pregame_archive_health()) == []


def test_an_unreadable_archive_marker_is_not_rewritten_every_tick(monkeypatch, clock, caplog):
    """While the file stays unreadable, the marker is written -- and the WARNING
    logged -- once when the state is entered, then at most hourly; it keeps
    ``firstFailedAt``.  Every pass still re-reads the file (it is never
    overwritten)."""
    reads: list[str] = []
    real_read = live._read_pregame_archive

    def read(path):
        if pathlib.Path(path) == _accepted():
            reads.append("read")
        return real_read(path)

    monkeypatch.setattr(live, "_read_pregame_archive", read)
    with caplog.at_level(logging.WARNING, logger=live.__name__):
        marker = _unreadable_archive_through_the_prune(clock, ticks=1)
        first_bytes = marker.read_bytes()
        assert _marker() == {
            "failedAt": live._iso(NOW),
            "firstFailedAt": live._iso(NOW),
            "reason": "archive_unreadable",
        }
        for tick in range(1, 60):  # 59 more one-minute ticks, all inside the hour
            clock["now"] = NOW + 60 * tick
            assert live.prune_retention(SEASON, PRUNE_WEEK) == []
            assert marker.read_bytes() == first_bytes  # not rewritten
    warned = [r for r in caplog.records if "archive_unreadable" in r.getMessage()]
    assert len(warned) == 1  # the state was entered once
    assert len(reads) == 60  # ... but the file was re-checked on every pass

    caplog.clear()
    with caplog.at_level(logging.WARNING, logger=live.__name__):
        clock["now"] = NOW + RETRY  # an hour on: recorded again, the start kept
        live.prune_retention(SEASON, PRUNE_WEEK)
        assert _marker() == {
            "failedAt": live._iso(NOW + RETRY),
            "firstFailedAt": live._iso(NOW),
            "reason": "archive_unreadable",
        }
        hourly_bytes = marker.read_bytes()
        for tick in range(1, 6):
            clock["now"] = NOW + RETRY + 60 * tick
            live.prune_retention(SEASON, PRUNE_WEEK)
            assert marker.read_bytes() == hourly_bytes
    assert len([r for r in caplog.records if "archive_unreadable" in r.getMessage()]) == 1
    assert _accepted().read_bytes() == b"garbage" and _obs_dir().is_dir()  # never overwritten


@pytest.mark.parametrize(
    "prior",
    ["archive_directory_unflushed", "raw_log_prune_failed", "kickoffs_unknown", "old_unreadable"],
)
def test_entering_the_unreadable_state_is_recorded_at_once(prior):
    """The no-churn rule only spares a REPEAT inside the hour: a file that stops
    reading back beside any other marker, or beside an unreadable marker older
    than the hour, is recorded on that pass.  Its start is this pass, unless the
    prior marker recorded the same unreadable incident."""
    _record(PRE_KICKOFF_FETCH, REAL_FETCH)
    marker = live._pregame_failure_path(SEASON, WEEK)
    if prior == "old_unreadable":
        live._write_pregame_marker(
            marker,
            NOW - 2 * RETRY,
            "archive_unreadable",
            fields={"firstFailedAt": live._iso(NOW - 5 * RETRY)},
        )
    else:
        live._write_pregame_marker(
            marker, NOW - 60, prior, fields={"firstFailedAt": live._iso(NOW - 3 * RETRY)}
        )
    _accepted().write_bytes(b"garbage")

    assert live.ensure_pregame_archive(SEASON, WEEK, now=NOW) is False

    start = NOW - 5 * RETRY if prior == "old_unreadable" else NOW
    assert _marker() == {
        "failedAt": live._iso(NOW),
        "firstFailedAt": live._iso(start),
        "reason": "archive_unreadable",
    }


# --- round 6: one incident keeps one start across the retry family ------------------------


def test_one_incident_keeps_its_start_across_retry_family_reasons(monkeypatch, clock):
    """The reviewers' round-6 probe T1.  The raw log never goes (rmtree fails
    silently) while the directory flush fails and recovers in turn, so the
    marker moves prune-failed -> unflushed (fsync) -> prune-failed -> unflushed
    (open) -> prune-failed.  That is ONE incident: ``firstFailedAt`` stays the
    first failure throughout, ``failedAt`` is always the latest attempt, and the
    alert keeps saying "failing since" the start."""
    _record(PRE_KICKOFF_FETCH, REAL_FETCH)
    flush = _stub_dir_flush(monkeypatch, live._DIR_FLUSHED)
    _stub_rmtree(monkeypatch)
    outcomes = {
        "flushed": live._DIR_FLUSHED,
        "fsync": live._DIR_FSYNC_FAILED,
        "open": live._DIR_OPEN_FAILED,
    }
    plan = [
        (0, "flushed", "raw_log_prune_failed", None, 0),
        (60, "flushed", "raw_log_prune_failed", None, 0),  # throttled
        (RETRY, "fsync", "archive_directory_unflushed", "fsync", RETRY),
        (RETRY + 60, "fsync", "archive_directory_unflushed", "fsync", RETRY),  # throttled
        (2 * RETRY, "flushed", "raw_log_prune_failed", None, 2 * RETRY),
        (3 * RETRY, "open", "archive_directory_unflushed", "open", 3 * RETRY),
        (4 * RETRY, "flushed", "raw_log_prune_failed", None, 4 * RETRY),
        (4 * RETRY + 300, "flushed", "raw_log_prune_failed", None, 4 * RETRY),  # throttled
    ]
    for offset, outcome, reason, kind, latest in plan:
        clock["now"] = NOW + offset
        flush["outcome"] = outcomes[outcome]
        assert live.prune_retention(SEASON, PRUNE_WEEK) == []
        stored = _marker()
        assert (stored["reason"], stored.get("flushFailure")) == (reason, kind), offset
        assert stored["firstFailedAt"] == live._iso(NOW), offset  # the incident's start
        assert stored["failedAt"] == live._iso(NOW + latest), offset  # the latest attempt
        (alert,) = oa._check_pregame_archive(live.pregame_archive_health())
        assert f"failing since {live._iso(NOW)}" in alert.detail, offset


def test_a_cleared_marker_ends_the_incident(monkeypatch, clock):
    """Once a pass establishes the archive and clears the marker, the next
    failure is a new incident with its own start."""
    flush = _fail_the_first_flush(monkeypatch, live._DIR_FSYNC_FAILED)  # incident 1 at NOW
    flush["outcome"] = live._DIR_FLUSHED
    clock["now"] = NOW + RETRY
    assert live.ensure_pregame_archive(SEASON, WEEK) is True
    assert not live._pregame_failure_path(SEASON, WEEK).exists()

    flush["outcome"] = live._DIR_OPEN_FAILED  # no marker: the next pass rewrites at once
    clock["now"] = NOW + RETRY + 60
    assert live.ensure_pregame_archive(SEASON, WEEK) is False
    assert _marker()["firstFailedAt"] == live._iso(NOW + RETRY + 60)


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        ({"failedAt": 3 * RETRY, "firstFailedAt": RETRY}, RETRY),
        ({"failedAt": 3 * RETRY}, 3 * RETRY),  # written before firstFailedAt existed
        ({"failedAt": RETRY, "firstFailedAt": 3 * RETRY}, RETRY),  # earliest, whichever key
        ({"failedAt": 3 * RETRY, "firstFailedAt": "not a time"}, 3 * RETRY),
        ({"failedAt": None}, None),
    ],
    ids=["both", "failedAt-only", "earliest-wins", "unparseable-start", "no-time"],
)
def test_failure_start_is_the_earliest_stamp_of_a_retry_family_marker(fields, expected):
    stamps = {k: (live._iso(NOW + v) if isinstance(v, float) else v) for k, v in fields.items()}
    for reason in sorted(live._PREGAME_RETRY_REASONS):
        got = live._failure_start({"reason": reason, **stamps}, live._PREGAME_RETRY_REASONS)
        assert got == (None if expected is None else live._iso(NOW + expected))
    # Any other reason starts a new incident.
    for reason in ("archive_unreadable", "kickoffs_unknown", None):
        prior = {"reason": reason, **stamps}
        assert live._failure_start(prior, live._PREGAME_RETRY_REASONS) is None
    assert live._failure_start(None, live._PREGAME_RETRY_REASONS) is None


# --- round 6: the prune warning says whether the failure was recorded ---------------------


def test_a_recorded_prune_failure_warns_that_it_is_recorded(monkeypatch, clock, caplog):
    _record(PRE_KICKOFF_FETCH, REAL_FETCH)
    _stub_dir_flush(monkeypatch, live._DIR_FLUSHED)
    _stub_rmtree(monkeypatch)

    with caplog.at_level(logging.WARNING, logger=live.__name__):
        assert live.prune_retention(SEASON, PRUNE_WEEK) == []

    (message,) = [
        r.getMessage() for r in caplog.records if "could not remove raw" in r.getMessage()
    ]
    assert message.endswith(
        "beside the accepted pregame archive -- recorded as raw_log_prune_failed, retried at "
        "most hourly"
    )
    assert "NOT recorded" not in message
    assert _marker()["reason"] == "raw_log_prune_failed"


def test_an_unrecorded_prune_failure_warns_that_it_is_not_recorded(monkeypatch, clock, caplog):
    """The reviewers' round-6 probe T3.  The prune warning used to say "recorded as
    raw_log_prune_failed, retried at most hourly" BEFORE the marker write -- which
    is swallowed -- so with an unwritable marker it claimed a throttle that did
    not exist while every pass rewrote and deleted again.  It now says the failure
    is NOT recorded and every pass retries, which is what happens."""
    _record(PRE_KICKOFF_FETCH, REAL_FETCH)
    flush = _stub_dir_flush(monkeypatch, live._DIR_FLUSHED)
    rm = _stub_rmtree(monkeypatch)
    live.prune_retention(SEASON, PRUNE_WEEK)  # built, verified; the prune failure is recorded
    assert _marker()["reason"] == "raw_log_prune_failed"
    writes = _record_archive_writes(monkeypatch)
    _deny_marker_writes(monkeypatch)["deny"] = True

    caplog.clear()
    with caplog.at_level(logging.WARNING, logger=live.__name__):
        for tick in range(61, 67):  # past the recorded marker's window, then every minute
            clock["now"] = NOW + 60 * tick
            assert live.prune_retention(SEASON, PRUNE_WEEK) == []

    assert not live._pregame_failure_path(SEASON, WEEK).exists()  # cleared, never re-recorded
    assert len(writes) == 6 and rm["calls"] == 7 and flush["calls"] == 7  # every pass retried
    warned = [r.getMessage() for r in caplog.records if "could not remove raw" in r.getMessage()]
    assert len(warned) == 6
    for message in warned:
        assert "the failure is NOT recorded" in message
        assert "every pass retries the removal" in message
        assert live.PREGAME_ARCHIVE_FAILURE_NAME in message
        assert "retried at most hourly" not in message


def test_the_marker_writer_reports_whether_it_wrote(monkeypatch):
    marker = live._pregame_failure_path(SEASON, WEEK)
    assert live._write_pregame_marker(marker, NOW, "kickoffs_unknown") is True
    assert _marker() == {"failedAt": live._iso(NOW), "reason": "kickoffs_unknown"}

    _deny_marker_writes(monkeypatch)["deny"] = True
    assert live._write_pregame_marker(marker, NOW + 60, "weekly_log_unreadable") is False
    assert live._mark_raw_log_prune_failed(marker, NOW + 60, None) is False
    assert _marker() == {"failedAt": live._iso(NOW), "reason": "kickoffs_unknown"}  # unchanged


def test_a_failure_whose_marker_cannot_be_written_warns_that_it_is_not_recorded(
    monkeypatch, caplog
):
    marker = live._pregame_failure_path(SEASON, WEEK)
    with caplog.at_level(logging.WARNING, logger=live.__name__):
        assert live._mark_pregame_failure(marker, NOW, "kickoffs_unknown") is True
    (recorded,) = [r.getMessage() for r in caplog.records]
    assert recorded.endswith("pregame projection archive not established (kickoffs_unknown)")

    _deny_marker_writes(monkeypatch)["deny"] = True
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger=live.__name__):
        assert live._mark_pregame_failure(marker, NOW + 60, "archive_unreadable") is False
    (unrecorded,) = [r.getMessage() for r in caplog.records]
    assert "(archive_unreadable); the failure is NOT recorded" in unrecorded
    assert "not throttled and the next pass retries" in unrecorded


# --- round 6: health and the alert tell the weekly log from observations/ -----------------


def _partial_rmtree(monkeypatch) -> dict:
    """``shutil.rmtree`` that removes everything in ``observations/`` except a
    ``keep.lock`` (a held lock), and so leaves the directory; ``state["mode"]``
    ``"ok"`` makes it real again."""
    state = {"mode": "partial", "calls": 0}
    real = shutil.rmtree

    def rmtree(path, *args, **kwargs):
        state["calls"] += 1
        if state["mode"] == "ok":
            return real(path, *args, **kwargs)
        for item in pathlib.Path(path).iterdir():
            if item.name != "keep.lock":
                item.unlink()
        return None

    monkeypatch.setattr(shutil, "rmtree", rmtree)
    return state


def test_a_partial_prune_that_removed_the_weekly_log_alerts_the_true_state(monkeypatch, clock):
    """The reviewers' round-6 probe T2.  A prune whose rmtree removed the weekly
    log but left another file keeps ``observations/``.  The next retry correctly
    re-flushes only (nothing left to protect); when that flush fails, the alert
    used to say "the raw weekly-projection log is retained" and that the retry
    "rewrites the accepted archive byte for byte ... no bare re-flush is trusted"
    -- both false.  Health now reports the weekly log separately, and the alert
    says the weekly log is gone and the retry only re-flushes."""
    _record(PRE_KICKOFF_FETCH, REAL_FETCH)
    (_obs_dir() / "keep.lock").write_text("x", encoding="utf-8")
    flush = _stub_dir_flush(monkeypatch, live._DIR_FLUSHED)
    rm = _partial_rmtree(monkeypatch)
    weekly = live.observation_log(live.NFL_KEY, SEASON, WEEK, live.SOURCE_WEEKLY).log_path

    assert live.prune_retention(SEASON, PRUNE_WEEK) == []  # built, flushed; rmtree partial
    assert not weekly.exists() and _obs_dir().is_dir()
    (row,) = live.pregame_archive_health()
    assert (row["reason"], row["rawLogRetained"], row["weeklyLogRetained"]) == (
        "raw_log_prune_failed",
        True,
        False,
    )
    (alert,) = oa._check_pregame_archive([row])
    assert "raw observations not fully removed" in alert.title
    assert "weekly-projection log itself is already gone" in alert.detail
    assert "only re-flushes the directory" in alert.detail
    assert "the raw log simply stays on disk" not in alert.detail
    assert "byte-identical rewrite of its own bytes" not in alert.detail
    accepted_bytes = _accepted().read_bytes()
    writes = _record_archive_writes(monkeypatch)

    flush["outcome"] = live._DIR_FSYNC_FAILED  # the hourly retry's re-flush fails
    clock["now"] = NOW + RETRY
    assert live.prune_retention(SEASON, PRUNE_WEEK) == []
    assert writes == [] and flush["calls"] == 2  # re-flushed only: nothing left to protect
    (row,) = live.pregame_archive_health()
    assert (row["reason"], row["flushFailure"]) == ("archive_directory_unflushed", "fsync")
    assert (row["rawLogRetained"], row["weeklyLogRetained"]) == (True, False)
    assert row["firstFailedAt"] == live._iso(NOW)  # one incident since the prune failed
    (alert,) = oa._check_pregame_archive([row])
    assert "awaiting a durable directory flush" in alert.title
    assert "The raw weekly-projection log is no longer on disk" in alert.detail
    assert "nothing left to protect" in alert.detail
    assert "only re-flushes the directory -- it never rewrites or rebuilds" in alert.detail
    for false_claim in (
        "the raw weekly-projection log is retained",
        "rewrites the accepted archive byte for byte",
        "no bare re-flush is trusted",
    ):
        assert false_claim not in alert.detail
    assert f"failing since {live._iso(NOW)}" in alert.detail

    flush["outcome"] = live._DIR_FLUSHED
    rm["mode"] = "ok"
    clock["now"] = NOW + 2 * RETRY
    assert live.prune_retention(SEASON, PRUNE_WEEK) == [str(_obs_dir())]
    assert writes == [] and _accepted().read_bytes() == accepted_bytes
    assert live.pregame_archive_health() == []


# --- round 7: a surviving observations/ with no archive is warned once, then hourly -------


_STAMP_REASON = "observations_prune_failed"


def _unarchived_week(where: str) -> tuple[pathlib.Path, pathlib.Path]:
    """An old week whose ``observations/`` has no weekly-projection log, so no
    accepted pregame archive is ever written beside it: an NFL week with only
    another source's log, or any other league's week.  Returns (week dir, obs)."""
    if where == "nfl_no_weekly_log":
        week_dir = _week_dir()
    else:
        week_dir = live.league_week_dir("lk", SEASON, WEEK)
    obs = week_dir / "observations"
    obs.mkdir(parents=True)
    (obs / "espn_scoreboard.jsonl").write_text("{}\n", encoding="utf-8")
    return week_dir, obs


def _prune_warnings(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if "could not remove raw" in r.getMessage()]


@pytest.mark.parametrize("where", ["nfl_no_weekly_log", "other_league"])
def test_an_unarchived_prune_failure_warns_once_then_hourly(monkeypatch, clock, caplog, where):
    """Round 7 blocking item.  ``rmtree`` keeps failing on a week with no accepted
    pregame archive (every non-NFL league week, and an NFL week with no weekly
    log).  Round 6 warned on EVERY one-minute tick and wrote nothing; ``main``
    was silent.  Each tick is a fresh process, so the limit is a stamp on disk:
    one WARNING when the state is entered, then at most one an hour -- while the
    removal itself is retried on every pass."""
    week_dir, obs = _unarchived_week(where)
    stamp = week_dir / live.RAW_PRUNE_FAILURE_NAME
    rm = _stub_rmtree(monkeypatch)

    ticks = 0
    with caplog.at_level(logging.WARNING, logger=live.__name__):
        for tick in range(0, 8):  # eight one-minute ticks: one WARNING
            clock["now"] = NOW + 60 * tick
            assert live.prune_retention(SEASON, PRUNE_WEEK) == []
            ticks += 1
        assert len(_prune_warnings(caplog)) == 1
        assert rm["calls"] == ticks  # the removal is retried on every pass
        assert live._read_json(stamp) == {
            "failedAt": live._iso(NOW),
            "firstFailedAt": live._iso(NOW),
            "reason": _STAMP_REASON,
        }
        for tick in range(0, 8):  # the hour lapses: one more, then quiet again
            clock["now"] = NOW + RETRY + 60 * tick
            assert live.prune_retention(SEASON, PRUNE_WEEK) == []
            ticks += 1
        warned = _prune_warnings(caplog)

    assert len(warned) == 2 and rm["calls"] == ticks == 16
    assert live._read_json(stamp) == {
        "failedAt": live._iso(NOW + RETRY),
        "firstFailedAt": live._iso(NOW),  # the start is kept
        "reason": _STAMP_REASON,
    }
    for message in warned:
        assert str(obs) in message and "the removal is retried every pass" in message
        assert f"recorded in {live.RAW_PRUNE_FAILURE_NAME}" in message
        assert f"failing since {live._iso(NOW)}" in message
        assert "repeats at most hourly" in message and "NOT recorded" not in message
    # Not a pregame-archive failure: no marker, no health row, no alert.
    assert not live._pregame_failure_path(SEASON, WEEK).exists()
    assert not (week_dir / live.PREGAME_ARCHIVE_FAILURE_NAME).exists()
    rows = live.pregame_archive_health()
    assert rows in ([], None)
    assert oa._check_pregame_archive(rows or []) == []

    # The removal works again: the directory goes, and so does the stamp.
    rm["fail"] = False
    clock["now"] = NOW + RETRY + 600
    assert live.prune_retention(SEASON, PRUNE_WEEK) == [str(obs)]
    assert not obs.exists() and not stamp.exists()


@pytest.mark.parametrize("where", ["nfl_no_weekly_log", "other_league"])
def test_an_unarchived_prune_failure_whose_stamp_cannot_be_written_says_so(
    monkeypatch, clock, caplog, where
):
    """Nowhere to persist the limit: every pass warns, and says why."""
    week_dir, _obs = _unarchived_week(where)
    _stub_rmtree(monkeypatch)
    real = live._atomic_write_json

    def write(path, payload):
        if pathlib.Path(path).name == live.RAW_PRUNE_FAILURE_NAME:
            raise OSError(errno.ENOSPC, "No space left on device", str(path))
        return real(path, payload)

    monkeypatch.setattr(live, "_atomic_write_json", write)
    with caplog.at_level(logging.WARNING, logger=live.__name__):
        for tick in range(0, 5):
            clock["now"] = NOW + 60 * tick
            live.prune_retention(SEASON, PRUNE_WEEK)
    warned = _prune_warnings(caplog)

    assert len(warned) == 5
    for message in warned:
        assert (
            f"the failure is NOT recorded ({live.RAW_PRUNE_FAILURE_NAME} could not be written)"
        ) in message
        assert "this warning repeats on every pass" in message
    assert not (week_dir / live.RAW_PRUNE_FAILURE_NAME).exists()


def test_a_stale_stamp_whose_directory_is_gone_is_removed(clock):
    """A stamp left by a pass that removed the directory but could not clear it
    (or a directory removed by hand) goes on the next pass."""
    week_dir = live.league_week_dir("lk", SEASON, WEEK)
    week_dir.mkdir(parents=True)
    stamp = week_dir / live.RAW_PRUNE_FAILURE_NAME
    live._atomic_write_json(stamp, {"failedAt": live._iso(NOW), "reason": _STAMP_REASON})

    assert live.prune_retention(SEASON, PRUNE_WEEK) == []
    assert not stamp.exists()


def test_a_prune_stamp_is_never_read_as_a_pregame_failure(clock):
    """``pregame_archive_health`` reads only the pregame marker: a prune stamp
    beside a week adds no row, and changes none."""
    _record(PRE_KICKOFF_FETCH, REAL_FETCH)
    stamp = _week_dir() / live.RAW_PRUNE_FAILURE_NAME
    live._atomic_write_json(stamp, {"failedAt": live._iso(NOW), "reason": _STAMP_REASON})
    assert live.pregame_archive_health() == []

    marker = live._pregame_failure_path(SEASON, WEEK)
    live._write_pregame_marker(marker, NOW, "kickoffs_unknown")
    (with_stamp,) = live.pregame_archive_health()
    stamp.unlink()
    assert live.pregame_archive_health() == [with_stamp]


def test_a_prune_stamp_with_other_content_does_not_suppress_the_warning(monkeypatch, clock, caplog):
    """A stamp that does not record this state (unreadable here) neither limits
    the WARNING nor lends a start."""
    week_dir, _obs = _unarchived_week("other_league")
    stamp = week_dir / live.RAW_PRUNE_FAILURE_NAME
    stamp.write_text("not json", encoding="utf-8")
    _stub_rmtree(monkeypatch)
    with caplog.at_level(logging.WARNING, logger=live.__name__):
        live.prune_retention(SEASON, PRUNE_WEEK)
    assert len(_prune_warnings(caplog)) == 1
    assert live._read_json(stamp)["firstFailedAt"] == live._iso(NOW)


# --- round 7: a leftover that cannot be set aside is recorded, retried hourly -------------


def _deny_leftover_set_aside(monkeypatch) -> dict:
    """Refuse every rename of the accepted archive while ``state["deny"]``;
    ``state["calls"]`` counts the attempts."""
    state = {"deny": True, "calls": 0}
    real_replace = pathlib.Path.replace

    def replace(self, target):
        if self.name == live.PREGAME_ARCHIVE_NAME:
            state["calls"] += 1
            if state["deny"]:
                raise PermissionError(13, "Permission denied", str(self))
        return real_replace(self, target)

    monkeypatch.setattr(pathlib.Path, "replace", replace)
    return state


def _set_aside_warnings(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if "could not set aside" in r.getMessage()]


def _untrusted_warnings(caplog) -> list[str]:
    return [
        r.getMessage() for r in caplog.records if "stays at the accepted path" in r.getMessage()
    ]


def test_a_leftover_that_cannot_be_set_aside_is_recorded_and_retried_hourly(
    monkeypatch, clock, caplog
):
    """Round 7 nit 2.  A persistently refused set-aside returned without writing
    anything, so the legacy marker's old ``failedAt`` never throttled it: the
    rename was re-attempted, and warned, on every tick while the alert said the
    collector retries hourly.  It is now recorded on the marker -- which stays
    legacy, so the leftover stays untrusted."""
    _record(PRE_KICKOFF_FETCH, REAL_FETCH)
    players = len(_good_payload()["players"])
    bad_bytes = _pre_fix_leftover()  # legacy marker, failedAt NOW
    deny = _deny_leftover_set_aside(monkeypatch)
    start = NOW + RETRY + 1

    with caplog.at_level(logging.WARNING, logger=live.__name__):
        for tick in range(0, 6):  # six one-minute ticks: one attempt, one WARNING
            clock["now"] = start + 60 * tick
            assert live.prune_retention(SEASON, PRUNE_WEEK) == []
        assert deny["calls"] == 1 and len(_set_aside_warnings(caplog)) == 1
        assert _marker() == {
            "failedAt": live._iso(start),
            "firstFailedAt": live._iso(NOW),  # the incident began with the legacy marker
            "reason": "archive_readback_mismatch",
            "setAsideFailed": True,
        }
        (recorded,) = _untrusted_warnings(caplog)
        assert "untrusted (archive_readback_mismatch)" in recorded
        assert "recorded in pregame_projections.retained.json and retried at most hourly" in (
            recorded
        )

        (row,) = live.pregame_archive_health()
        (alert,) = oa._check_pregame_archive([row])
        assert "The Game Day collector retries hourly" in alert.detail  # now true
        assert f"failed {live._iso(start)})" in alert.detail  # the latest attempt

        for tick in range(0, 6):  # the hour lapses: one more attempt, then quiet
            clock["now"] = start + RETRY + 60 * tick
            assert live.prune_retention(SEASON, PRUNE_WEEK) == []
        assert deny["calls"] == 2 and len(_set_aside_warnings(caplog)) == 2

    assert _marker()["failedAt"] == live._iso(start + RETRY)
    assert _marker()["firstFailedAt"] == live._iso(NOW)  # the start is kept
    assert "candidateFlow" not in _marker()  # still legacy: the leftover is not trusted
    assert _accepted().read_bytes() == bad_bytes and _obs_dir().is_dir()

    # The rename works again: set aside, rebuilt from the raw log, verified, pruned.
    deny["deny"] = False
    _stub_dir_flush(monkeypatch, live._DIR_FLUSHED)
    clock["now"] = start + 2 * RETRY
    assert live.prune_retention(SEASON, PRUNE_WEEK) == [str(_obs_dir())]
    assert (_week_dir() / MISMATCH).read_bytes() == bad_bytes
    archive = live._read_pregame_archive(_accepted())
    assert archive is not None and len(archive["players"]) == players
    assert not live._pregame_failure_path(SEASON, WEEK).exists()


def test_the_adopted_marker_drops_the_set_aside_failure():
    """Once the set-aside succeeds, the re-stamped marker must not keep saying it
    failed (every other field kept)."""
    marker = live._pregame_failure_path(SEASON, WEEK)
    prior = {
        "failedAt": live._iso(NOW + 60),
        "firstFailedAt": live._iso(NOW),
        "reason": "archive_readback_mismatch",
        "setAsideFailed": True,
    }
    live._adopt_legacy_mismatch_marker(marker, prior)
    assert _marker() == {
        "failedAt": live._iso(NOW + 60),
        "firstFailedAt": live._iso(NOW),
        "reason": "archive_readback_mismatch",
        "candidateFlow": True,
    }


def test_a_leftover_set_aside_failure_whose_marker_cannot_be_written_says_so(
    monkeypatch, clock, caplog
):
    """Nowhere to persist the throttle: every pass retries the set-aside, and says so."""
    _record(PRE_KICKOFF_FETCH, REAL_FETCH)
    _pre_fix_leftover()
    before = _marker()
    deny = _deny_leftover_set_aside(monkeypatch)
    _deny_marker_writes(monkeypatch)["deny"] = True
    with caplog.at_level(logging.WARNING, logger=live.__name__):
        for tick in range(0, 5):
            clock["now"] = NOW + RETRY + 1 + 60 * tick
            assert live.prune_retention(SEASON, PRUNE_WEEK) == []
    assert deny["calls"] == 5 and len(_set_aside_warnings(caplog)) == 5
    unrecorded = _untrusted_warnings(caplog)
    assert len(unrecorded) == 5
    for message in unrecorded:
        assert "the failure is NOT recorded (pregame_projections.retained.json" in message
        assert "not throttled and the next pass retries" in message
    assert _marker() == before  # the legacy marker as it was


# --- round 7: the weekly-gone build-failure text names what the next pass does -------------


@pytest.mark.parametrize("state", ["no_file", "readable_flushed", "readable_unflushed", "garbage"])
def test_the_weekly_gone_build_failure_text_matches_the_next_pass(monkeypatch, clock, state):
    """Round 7 nit 4.  The text said the next pass "replaces" the marker if a file
    is at the archive path; beside a readable archive it CLEARS it (after a
    re-flush).  Each sub-state is driven through the real prune and checked
    against the text."""
    _record(PRE_KICKOFF_FETCH, REAL_FETCH)
    payload = _good_payload()
    _drop_the_weekly_log()
    marker = live._pregame_failure_path(SEASON, WEEK)
    live._write_pregame_marker(marker, NOW, "kickoffs_unknown")
    if state.startswith("readable"):
        live._write_pregame_archive(_accepted(), payload)
    elif state == "garbage":
        _accepted().write_bytes(b"garbage")
    (row,) = live.pregame_archive_health()
    (alert,) = oa._check_pregame_archive([row])
    assert alert.title.endswith("not built; raw weekly log gone")
    assert "or replaces it, if a file is at the archive path" not in alert.detail
    assert "pass clears this marker: at once if no file is at the archive path" in alert.detail
    assert "after re-flushing the directory holding a readable archive there" in alert.detail
    assert "replaces it with archive_directory_unflushed instead" in alert.detail
    assert "a file there that does not read back replaces it with archive_unreadable" in (
        alert.detail
    )

    unflushed = state == "readable_unflushed"
    _stub_dir_flush(monkeypatch, live._DIR_FSYNC_FAILED if unflushed else live._DIR_FLUSHED)
    clock["now"] = NOW + 60  # the very next pass
    live.prune_retention(SEASON, PRUNE_WEEK)
    expected = {
        "no_file": None,
        "readable_flushed": None,
        "readable_unflushed": "archive_directory_unflushed",
        "garbage": "archive_unreadable",
    }[state]
    if expected is None:
        assert not marker.exists() and not _obs_dir().exists()  # cleared, pruned
    else:
        assert _marker_reason() == expected and _obs_dir().is_dir()
