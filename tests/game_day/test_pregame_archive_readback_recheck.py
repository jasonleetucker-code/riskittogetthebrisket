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

Durability (rounds 2-4): the raw log goes only once the rename that put the
verified archive in place is known to be on disk.  An accepted archive whose
rename is unproven -- after an ``fsync`` error, with no marker, or beside any
marker but a recorded ``open`` failure -- is re-established by a BYTE-IDENTICAL
rewrite (its own bytes, copied, read back and checked by size and sha256,
renamed over it, then flushed), never by a rebuild: a rebuild also reads the
schedule, the stored scoreboard and the clock, and could replace the verified
archive with a different one.
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
    and the next pass is the one whose True lets the raw log go.  (Beside this
    unrelated marker that means the byte-identical rewrite, then its flush.)"""
    _record(PRE_KICKOFF_FETCH, REAL_FETCH)
    live._write_pregame_archive(_accepted(), _good_payload())
    accepted_bytes = _accepted().read_bytes()
    before = _weekly_log_bytes()
    marker = live._pregame_failure_path(SEASON, WEEK)
    live._mark_pregame_failure(marker, NOW, "kickoffs_unknown")  # an unrelated stale marker
    flush = _stub_dir_flush(monkeypatch, live._DIR_OPEN_FAILED)
    builds = _count_builds(monkeypatch)

    # An unrelated marker does not throttle the accept branch's flush.
    assert live.ensure_pregame_archive(SEASON, WEEK, now=NOW + 60) is False

    assert flush["calls"] == 1 and builds == []
    assert _accepted().read_bytes() == accepted_bytes  # kept: not rebuilt, not set aside
    assert not (_week_dir() / MISMATCH).exists()
    # The marker now says why the raw log is kept -- not the stale reason, and
    # not cleared as though the archive were established.  Its start is this
    # attempt: the stale marker was a different failure.
    stored = _marker()
    assert stored["reason"] == "archive_directory_unflushed" and "candidateFlow" not in stored
    assert stored["firstFailedAt"] == live._iso(NOW + 60)
    assert _obs_dir().is_dir() and _weekly_log_bytes() == before

    flush["outcome"] = live._DIR_FLUSHED
    assert live.ensure_pregame_archive(SEASON, WEEK, now=NOW + 60 + RETRY) is True
    assert flush["calls"] == 2 and builds == []
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


def test_after_an_open_failure_only_the_flush_is_retried(monkeypatch, clock):
    """No fsync ran, so no write error was reported and consumed: re-flushing is
    sound, and the archive is neither rebuilt nor rewritten -- the one marker that
    earns a bare re-flush."""
    flush = _fail_the_first_flush(monkeypatch, live._DIR_OPEN_FAILED)
    accepted_bytes = _accepted().read_bytes()
    builds = _count_builds(monkeypatch)
    file_flushes = _count_file_flushes(monkeypatch)
    writes = _record_archive_writes(monkeypatch)

    clock["now"] = NOW + RETRY  # the window has lapsed (its boundary retries)
    assert str(_obs_dir()) not in live.prune_retention(SEASON, PRUNE_WEEK)  # still failing

    assert flush["calls"] == 2 and builds == [] and file_flushes == [] and writes == []
    assert _accepted().read_bytes() == accepted_bytes  # re-flushed, not replaced
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
    assert flush["calls"] == 3 and builds == [] and file_flushes == [] and writes == []
    assert _accepted().read_bytes() == accepted_bytes
    assert not live._pregame_failure_path(SEASON, WEEK).exists()
    assert live.pregame_archive_health() == []


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


def _unflushed_fsync_marker(failed_at: float) -> dict:
    return {
        "failedAt": live._iso(failed_at),
        "firstFailedAt": live._iso(NOW),
        "flushFailure": "fsync",
        "reason": "archive_directory_unflushed",
    }


@pytest.mark.parametrize("damage", ["one_byte_changed", "one_byte_short"])
def test_a_rewrite_that_does_not_read_back_identical_fails_closed(
    monkeypatch, clock, caplog, damage
):
    """The copy must match the accepted archive in size AND sha256 before it may
    replace it -- here one byte differs at the same size, or the copy is short.
    It never does: the accepted archive, the marker's meaning and the raw log are
    all kept, and the next retry overwrites the bad copy."""
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
    assert _marker() == _unflushed_fsync_marker(NOW + RETRY)
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
    assert _marker() == _unflushed_fsync_marker(NOW + RETRY)
    assert _obs_dir().is_dir() and _weekly_log_bytes() == before


def test_a_rewrite_that_fails_with_no_failure_on_record_is_marked_throttled_and_retried(
    monkeypatch, clock
):
    """With no prior failed flush on record there is no step to name, so the
    marker records ``flushFailure: null`` (the alert says the step is not on
    record); it is throttled like every reason, and retried by the rewrite."""
    _record(PRE_KICKOFF_FETCH, REAL_FETCH)
    live._write_pregame_archive(_accepted(), _good_payload())  # accepted, no marker
    accepted_bytes = _accepted().read_bytes()
    flush = _stub_dir_flush(monkeypatch, live._DIR_FLUSHED)
    writes = _record_archive_writes(monkeypatch)
    squatter = _week_dir() / (CANDIDATE + ".tmp")
    squatter.mkdir()  # the copy cannot be written

    assert str(_obs_dir()) not in live.prune_retention(SEASON, PRUNE_WEEK)
    assert _marker() == {
        "failedAt": live._iso(NOW),
        "firstFailedAt": live._iso(NOW),
        "flushFailure": None,
        "reason": "archive_directory_unflushed",
    }
    assert len(writes) == 1 and flush["calls"] == 0
    rows = live.pregame_archive_health()
    assert rows is not None and [(r["reason"], r["flushFailure"]) for r in rows] == [
        ("archive_directory_unflushed", None)
    ]
    (alert,) = oa._check_pregame_archive(rows)
    assert "not on record" in alert.detail and "byte for byte" in alert.detail

    clock["now"] = NOW + 60  # throttled: nothing is rewritten
    assert str(_obs_dir()) not in live.prune_retention(SEASON, PRUNE_WEEK)
    assert len(writes) == 1 and flush["calls"] == 0

    squatter.rmdir()
    clock["now"] = NOW + RETRY
    assert str(_obs_dir()) in live.prune_retention(SEASON, PRUNE_WEEK)
    assert writes == [(CANDIDATE, _sha(accepted_bytes))] * 2 and flush["calls"] == 1
    assert _accepted().read_bytes() == accepted_bytes
    assert not live._pregame_failure_path(SEASON, WEEK).exists()


@pytest.mark.parametrize(
    "beside",
    [
        "no_marker",
        "unrelated_marker",
        "candidate_flow_mismatch",
        "unflushed_unknown_kind",
        "unflushed_null_kind",
        "unflushed_no_kind",
    ],
)
def test_an_accepted_archive_with_a_retained_raw_log_is_rewritten_unless_open_is_recorded(
    monkeypatch, beside
):
    """A bare re-flush is trusted only after a recorded ``open`` failure.  With no
    marker (one whose write failed after an fsync error, say) or any other marker,
    the pass that lets the raw log go first rewrites the archive's own bytes, so
    its flush covers a rename made after any consumed error."""
    _record(PRE_KICKOFF_FETCH, REAL_FETCH)
    live._write_pregame_archive(_accepted(), _good_payload())
    accepted_bytes = _accepted().read_bytes()
    marker = live._pregame_failure_path(SEASON, WEEK)
    if beside == "unrelated_marker":
        live._mark_pregame_failure(marker, NOW, "kickoffs_unknown")
    elif beside == "candidate_flow_mismatch":
        live._mark_pregame_failure(marker, NOW, "archive_readback_mismatch", candidate_flow=True)
    elif beside != "no_marker":
        fields = {
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


def test_an_unflushed_marker_with_no_recorded_step_is_retried_as_an_fsync_failure(
    monkeypatch, clock
):
    """A marker written before ``flushFailure`` existed cannot say a re-flush is
    sound, so it takes the byte-identical rewrite; its ``failedAt`` is the best
    start."""
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


def test_the_next_retry_trusts_the_kind_of_the_latest_flush(monkeypatch, clock):
    """The rewrite's rename is the newest write, so ITS flush outcome decides the
    next retry: an open failure after it is re-flushed only."""
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
    assert builds == [] and len(writes) == 1  # open -> re-flushed only
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

    # FAILED, at the open step: no fsync ran, so a retry may re-flush only.
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
def test_an_unknown_flush_outcome_is_the_least_trusting_kind(outcome):
    """``"open"`` is the one kind whose retry trusts a bare re-flush, so only the
    exact ``open_failed`` outcome may become it.  Anything this code does not
    know -- including ``"failed"``, the outcome before the step was recorded, and
    the KIND ``"open"`` passed as an outcome -- is ``"fsync"``."""
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
    # The stale marker's failedAt is NOW, so NOW + 60 is inside the throttle
    # window (as after a clock stepped back) and the other two are past it.  The
    # accepted-archive branch never consults the throttle: every one keeps it.
    for later in (NOW + 60, NOW + RETRY + 60, NOW + 3 * RETRY):
        assert live.ensure_pregame_archive(SEASON, WEEK, now=later) is True
        assert builds == []  # not rebuilt
        assert _accepted().read_bytes() == accepted_bytes  # not rewritten
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
