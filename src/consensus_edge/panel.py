"""Reconstruct the board as it stood on any past date, out of git.

A buy/sell model that has never been checked against an outcome is a
guess with a number attached.  Checking requires a panel: for each of
many past dates, what the board said, and what happened next.

The discovery pass concluded no such panel existed — the only visible
history was 21 daily export bundles carrying three source CSVs.  That was
an artifact of a **shallow clone**.  ``scheduled-refresh.yml`` commits
``CSVs/site_raw/`` and ``exports/latest/`` with ``git add -f`` every two
hours, so the inputs are all preserved.  Measured after
``git fetch --unshallow``:

* ``CSVs/site_raw/*.csv`` — 24 sources, 110 distinct change-days,
  2026-04-16 → 2026-08-03
* ``exports/latest/dynasty_data_<date>.json`` — the raw scraper payload,
  1022 commits, back to 2026-03-09

So the panel is a ``git show`` away, and needs no new collection and no
waiting for calendar time.

**What this replays and what it does not.**  It runs TODAY's pipeline
over THAT DATE's inputs.  Data leakage is therefore impossible in the
inputs — every byte came from a commit at or before the as-of date — but
the *model* is current: today's Hill curves, today's registry, today's
constants.  That makes the panel valid for asking "would this signal have
ranked players usefully?" and invalid for asking "what did the site show
that day?".  Any evaluation built on it must state which question it is
answering.  ``PanelDay.model_is_current`` carries the caveat in the data
so it cannot be quietly forgotten.

Reconstruction is per-date and independent, so a caller can sample dates
rather than walk all of them; a full 110-day build is ~110 × (payload
extraction + 3 pipeline passes).
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
SITE_RAW_REL = "CSVs/site_raw"
LATEST_REL = "exports/latest"
# Dated playerctx snapshots, retained so a study can replay the joined
# artifact production served rather than only reconstructing its inputs.
#
# Deliberately NOT part of `available_dates`' intersection. Retention
# started 2026-08-05, so joining it would collapse the panel from 111
# usable dates to zero and grow it back one per week — trading every
# existing measurement for a feature that has no data yet. A day without
# a retained snapshot is a normal day; `PanelDay.playerctx` is None and
# the caller decides.
PLAYERCTX_REL = "data/playerctx/history"


class PanelUnavailable(RuntimeError):
    """Raised when the repository cannot supply an as-of reconstruction."""


@dataclass(frozen=True)
class PanelDay:
    """One as-of reconstruction."""

    as_of: date
    payload: dict[str, Any]
    payload_commit: str
    payload_path: str
    csv_commit: str
    # Repo-shaped root holding this date's CSVs; pass straight to
    # ``build_api_data_contract(csv_root=...)``.  Valid only inside the
    # ``panel_day`` block that produced it — the tree is deleted on exit.
    csv_root: Path | None = None
    csv_sources: tuple[str, ...] = ()
    # The retained playerctx snapshot for this date, or None when the
    # date predates retention. None is the normal case for every date in
    # the current panel and must stay legible as "not retained" rather
    # than being mistaken for "nobody played" — `playerctx_commit` is
    # set iff `playerctx` is.
    playerctx: dict[str, Any] | None = None
    playerctx_commit: str | None = None
    playerctx_path: str | None = None
    # Always True for a git replay.  Stated as data, not prose, because
    # every metric computed from this panel inherits the caveat.
    model_is_current: bool = True
    warnings: tuple[str, ...] = field(default_factory=tuple)


def _git(*args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, check=True)
    return proc.stdout


def _git_bytes(*args: str) -> bytes:
    proc = subprocess.run(["git", *args], cwd=REPO, capture_output=True, check=True)
    return proc.stdout


def is_shallow() -> bool:
    return (REPO / ".git" / "shallow").exists()


def _assert_deep() -> None:
    if is_shallow():
        raise PanelUnavailable(
            "shallow clone: run `git fetch --unshallow` first. A panel built "
            "from a shallow clone silently covers only the days the clone "
            "happens to contain, and the resulting evaluation would look "
            "complete while measuring a few days."
        )


def _commit_before(when: date, pathspec: str) -> str | None:
    out = _git(
        "rev-list",
        "-1",
        f"--before={when.isoformat()} 23:59:59",
        "HEAD",
        "--",
        pathspec,
    ).strip()
    return out or None


def available_dates(start: date | None = None, end: date | None = None) -> list[date]:
    """Dates for which BOTH a payload and source CSVs can be reconstructed.

    The intersection matters: a payload without CSVs reproduces a board
    missing most of its sources, which would look like a real board and
    score like a broken one.
    """
    _assert_deep()

    def _change_days(pathspec: str) -> set[date]:
        out = _git("log", "--format=%ad", "--date=short", "--", pathspec)
        days: set[date] = set()
        for line in out.splitlines():
            line = line.strip()
            if line:
                days.add(datetime.strptime(line, "%Y-%m-%d").date())
        return days

    payload_days = _change_days(LATEST_REL)
    csv_days = _change_days(SITE_RAW_REL)
    if not payload_days or not csv_days:
        raise PanelUnavailable("no committed history for payloads or source CSVs")

    # A date is usable once BOTH streams have started; between change
    # days each stream carries its last-known state forward, exactly as
    # the live pipeline does when a source does not refresh.
    first = max(min(payload_days), min(csv_days))
    last = min(max(payload_days), max(csv_days))
    if start:
        first = max(first, start)
    if end:
        last = min(last, end)
    if first > last:
        return []
    return [first + timedelta(days=i) for i in range((last - first).days + 1)]


def payload_asof(when: date) -> tuple[dict[str, Any], str, str]:
    """The raw scraper payload as committed on or before ``when``."""
    _assert_deep()
    commit = _commit_before(when, LATEST_REL)
    if not commit:
        raise PanelUnavailable(f"no committed payload at or before {when}")
    listing = _git("ls-tree", "-r", "--name-only", commit, "--", LATEST_REL)
    candidates = [
        p for p in listing.splitlines() if p.strip().endswith(".json") and "dynasty_data_" in p
    ]
    if not candidates:
        raise PanelUnavailable(f"commit {commit[:8]} has no dynasty_data_*.json")
    # Newest filename wins — the name carries the scrape date, so a
    # commit holding two is a same-day rebuild and the later is current.
    path = sorted(candidates)[-1]
    blob = _git_bytes("show", f"{commit}:{path}")
    try:
        payload = json.loads(blob.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PanelUnavailable(f"payload at {commit[:8]}:{path} is unreadable: {exc}") from exc
    return payload, commit, path


def playerctx_asof(when: date) -> tuple[dict[str, Any], str, str] | None:
    """The retained playerctx snapshot as of ``when``, or None.

    Mirrors :func:`payload_asof`, with one deliberate difference: absence
    is a **return value, not an exception**. A missing payload means the
    panel cannot reconstruct that date at all; a missing playerctx
    snapshot means only that the date predates retention, which is true
    of every date before 2026-08-05 and must not take a fold down with
    it.

    Newest-filename-wins, same as ``payload_asof`` — which is why
    ``store.history_path`` writes ``snapshot_YYYY-MM-DD.json``: a name
    that does not sort chronologically would silently replay the wrong
    day.
    """
    _assert_deep()
    commit = _commit_before(when, PLAYERCTX_REL)
    if not commit:
        return None
    listing = _git("ls-tree", "-r", "--name-only", commit, "--", PLAYERCTX_REL)
    candidates = [
        p for p in listing.splitlines() if p.strip().endswith(".json") and "snapshot_" in p
    ]
    if not candidates:
        return None
    path = sorted(candidates)[-1]
    try:
        blob = _git_bytes("show", f"{commit}:{path}")
        snapshot = json.loads(blob.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, PanelUnavailable):
        # A corrupt retained file must not take down a replay that has a
        # perfectly good board — the axis it feeds simply goes absent.
        return None
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("players"), dict):
        return None
    return snapshot, commit, path


def materialize_csvs_asof(when: date, dest_root: Path) -> tuple[str, tuple[str, ...]]:
    """Write ``CSVs/site_raw`` as of ``when`` under ``dest_root``.

    Returns ``(commit, source_stems)``.  ``dest_root`` is treated as a
    repo-shaped root, so files land at
    ``dest_root/CSVs/site_raw/<name>.csv`` — the layout
    ``_enrich_from_source_csvs(csv_root=...)`` expects.
    """
    _assert_deep()
    commit = _commit_before(when, SITE_RAW_REL)
    if not commit:
        raise PanelUnavailable(f"no committed source CSVs at or before {when}")
    listing = _git("ls-tree", "-r", "--name-only", commit, "--", SITE_RAW_REL)
    paths = [p for p in listing.splitlines() if p.strip().endswith(".csv")]
    if not paths:
        raise PanelUnavailable(f"commit {commit[:8]} has no source CSVs")

    target_dir = Path(dest_root) / SITE_RAW_REL
    target_dir.mkdir(parents=True, exist_ok=True)
    stems: list[str] = []
    for path in paths:
        blob = _git_bytes("show", f"{commit}:{path}")
        (Path(dest_root) / path).write_bytes(blob)
        stems.append(Path(path).stem)
    return commit, tuple(sorted(stems))


class panel_day:  # noqa: N801 — context manager, reads as a noun at call sites
    """Context manager yielding a :class:`PanelDay` for ``when``.

    ::

        with panel_day(date(2026, 6, 15)) as day:
            contract = build_api_data_contract(day.payload, csv_root=day.csv_root)

    The temporary CSV tree is deleted on exit, so nothing about a replay
    can leak into the working tree — which matters because the working
    tree is where the LIVE board reads its CSVs from.
    """

    def __init__(self, when: date):
        self.when = when
        self._tmp: tempfile.TemporaryDirectory | None = None
        self.csv_root: Path | None = None

    def __enter__(self) -> PanelDay:
        payload, payload_commit, payload_path = payload_asof(self.when)
        self._tmp = tempfile.TemporaryDirectory(prefix=f"ce-panel-{self.when.isoformat()}-")
        self.csv_root = Path(self._tmp.name)
        csv_commit, stems = materialize_csvs_asof(self.when, self.csv_root)

        warnings: list[str] = []
        payload_date = str(payload.get("date") or "")
        if payload_date and payload_date != self.when.isoformat():
            # Expected whenever the scrape did not run that day; the
            # last-known payload is carried forward.  Recorded rather
            # than silently accepted so a study can exclude stale days.
            warnings.append(f"payload carried forward from {payload_date}")

        # Absence is normal and is not a warning: every date before
        # retention started has none, and emitting a warning per fold
        # would drown the ones that mean something.
        retained = playerctx_asof(self.when)
        return PanelDay(
            as_of=self.when,
            payload=payload,
            payload_commit=payload_commit,
            payload_path=payload_path,
            csv_commit=csv_commit,
            csv_root=self.csv_root,
            csv_sources=stems,
            playerctx=retained[0] if retained else None,
            playerctx_commit=retained[1] if retained else None,
            playerctx_path=retained[2] if retained else None,
            warnings=tuple(warnings),
        )

    def __exit__(self, *exc: Any) -> None:
        if self._tmp is not None:
            self._tmp.cleanup()
            self._tmp = None
        self.csv_root = None
