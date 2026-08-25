"""Fetch-fresh is not content-fresh — the one detector that knows the difference.

``scripts/check_source_health.py::measure_content_staleness`` is the ONLY
place in this repository that can tell "the vendor published something new"
from "the fetch succeeded".  Every other freshness surface —
``data_contract._build_source_timestamps``, ``server._per_source_freshness``,
``watchdog_freshness.classify_freshness``,
``source_health_alerts.detect_stale_sources`` — reads the
``data/scrape_state/{key}_last_success`` stamp, which is written on every
successful fetch *regardless of whether the content changed*.  That
preference is deliberate (see ``_build_source_timestamps``'s docstring) and
is not what these tests question.

What they pin is the consequence: because the stamp cannot observe vendor
publishing, this detector is the whole of the repo's ability to say
"unchanged beyond budget".  It had **no test coverage at all** until this
file, so nothing stopped it being deleted, or quietly losing the property
that actually matters here — that pick rows are hashed SEPARATELY from the
board.

Motivating live measurement (Lane 8, 2026-08-25): ``idpTradeCalc`` fetches
green every 2h and its whole board changed 1 day ago, while its PICK rows
have been byte-identical since 2026-07-14 — 38 days against a 14-day
budget — and it is one of only two families that price picks at all.  A
whole-file hash cannot see that, because the file *does* change; only the
half that prices picks is frozen.

These fixtures are synthetic zips built in ``tmp_path``.  No credential, no
session material and no vendor payload is committed here.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from scripts.check_source_health import measure_content_staleness

#: Archive names must carry the ``YYYYMMDD_HHMMSS`` stamp the detector's
#: ``_ARCHIVE_STAMP_RE`` parses; age is measured against the NEWEST archive
#: rather than wall-clock, so these tests are time-independent.
_STAMPS = [
    "20260701_120000",
    "20260708_120000",
    "20260715_120000",
    "20260722_120000",
    "20260729_120000",
    "20260805_120000",
]

_PICKS_FROZEN = "\n".join(
    [
        "2026 Early 1st,5554.0",
        "2026 Early 2nd,3318.0",
        "2026 Pick 1.01,8013.0",
    ]
)


def _write_archive(root: Path, stamp: str, members: dict[str, str]) -> None:
    """One synthetic export archive carrying ``site_raw/<key>.csv`` members."""
    archive_dir = root / "exports" / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_dir / f"dynasty_export_{stamp}.zip", "w") as zf:
        for name, body in members.items():
            zf.writestr(f"site_raw/{name}.csv", body)


def _board(players: str, picks: str = _PICKS_FROZEN) -> str:
    return f"name,value\n{players}\n{picks}\n"


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    return tmp_path


class TestContentStalenessSeesWhatTheStampCannot:
    def test_a_source_changing_every_archive_is_not_content_stale(self, repo: Path) -> None:
        """Positive control.

        Without this, a detector that reported EVERYTHING as frozen would
        still satisfy the fail-closed test below, and prove nothing.
        """
        for i, stamp in enumerate(_STAMPS):
            _write_archive(repo, stamp, {"ktcSfTep": _board(f"Josh Allen,{9000 + i}")})
        out = measure_content_staleness(repo)["ktcSfTep"]
        # Newest archive changed too, so zero days since the last change.
        assert out["daysSinceChange"] == 0
        assert out["archivesObserved"] == len(_STAMPS)

    def test_fetch_fresh_but_content_frozen_is_reported_stale(self, repo: Path) -> None:
        """THE fail-closed property.

        Every archive here represents a SUCCESSFUL fetch — in production
        each one would have stamped ``_last_success`` and every stamp-based
        surface would read "fresh".  The content never moved, and this
        detector must say so in days, not agree that it is fresh.
        """
        for stamp in _STAMPS:
            _write_archive(repo, stamp, {"idpTradeCalc": _board("Myles Garrett,5414")})
        out = measure_content_staleness(repo)["idpTradeCalc"]
        # 2026-07-01 → 2026-08-05 measured against the newest archive.
        assert out["daysSinceChange"] == 35
        assert out["daysSinceChange"] > 14.0, "must exceed the configured budget"
        assert out["lastChangedAt"].startswith("2026-07-01")

    def test_pick_rows_are_measured_separately_from_the_board(self, repo: Path) -> None:
        """The exact live idpTradeCalc shape, and the reason a whole-file
        hash is not sufficient: the board moves every run while the pick
        half sits frozen.  Collapsing the two would read "the file changed"
        as "the pick market moved"."""
        for i, stamp in enumerate(_STAMPS):
            _write_archive(repo, stamp, {"idpTradeCalc": _board(f"Myles Garrett,{5400 + i}")})
        out = measure_content_staleness(repo)["idpTradeCalc"]
        # Board is fresh — it changed in the newest archive.
        assert out["daysSinceChange"] == 0
        # Picks are NOT, and that is invisible to a whole-file hash.
        assert out["daysSincePickChange"] == 35
        assert out["pickRowsLastChangedAt"].startswith("2026-07-01")

    def test_a_single_observation_is_unknown_not_fresh(self, repo: Path) -> None:
        """MISSING IS NEVER ZERO, applied to a change interval.

        One archive cannot establish that content is either moving or
        frozen.  Reporting 0 days would let a brand-new source read as
        maximally fresh on no evidence.
        """
        _write_archive(repo, _STAMPS[0], {"dynastyNerdsSfTep": _board("Some Player,100")})
        out = measure_content_staleness(repo)["dynastyNerdsSfTep"]
        assert out["daysSinceChange"] is None
        assert out["lastChangedAt"] is None
        assert out["archivesObserved"] == 1


class TestTheseTestsCanActuallyFail:
    """Self-check: a detector that lost the separate pick hash would still
    pass a whole-file assertion, so prove the pick assertion is load-bearing
    rather than incidentally true."""

    def test_board_and_pick_ages_are_genuinely_different_quantities(self, repo: Path) -> None:
        for i, stamp in enumerate(_STAMPS):
            _write_archive(repo, stamp, {"idpTradeCalc": _board(f"Myles Garrett,{5400 + i}")})
        out = measure_content_staleness(repo)["idpTradeCalc"]
        assert out["daysSinceChange"] != out["daysSincePickChange"], (
            "board age and pick age collapsed to one number — the separate "
            "pick hash is what makes a frozen pick market observable"
        )
