#!/usr/bin/env python3
"""Backfill ``data/rank_history.jsonl`` from ``exports/archive/`` zips.

The rank-history log lands empty from deploy day (PR #217).  Until
two scrapes have cycled the live box the ``RankChangeGlyph``
sparklines have nothing to render — every glyph falls through to the
delta-arrow fallback even though the scraper has months of prior
snapshots sitting unused in ``exports/archive/``.

This script replays those archive bundles through the canonical
``build_api_data_contract`` pipeline and feeds each resulting
contract into :func:`src.api.rank_history.append_snapshot` with the
archived date — producing backdated entries so glyphs light up the
moment the backfill finishes, without having to wait on the next
production scrape.

Archive shape
─────────────

Each archive is a zip named ``dynasty_export_YYYYMMDD_HHMMSS.zip``
containing:

* ``manifest.json`` with a top-level ``"date": "YYYY-MM-DD"`` field
* ``dynasty_data_<DATE>.json`` — the raw scraper payload (same shape
  ``build_api_data_contract`` consumes for the live endpoint)

When multiple archives share a day (common — the scraper runs 4-6x
per day) we keep the latest ``HHMMSS`` timestamp per date.  A same-
day re-run would hit ``append_snapshot``'s per-date dedup and
overwrite the earlier entry anyway; selecting up-front just avoids
paying the contract-rebuild cost for snapshots that would be thrown
away.

Idempotency
───────────

``append_snapshot`` already deduplicates by date.  Re-running this
script against the same archive directory converges on the same
JSONL — every date is a fixed point.

Retention
─────────

The retention cap (``MAX_SNAPSHOTS``, currently 180) is honoured.
If the archive directory holds more than 180 days the oldest ones
are trimmed away — same behaviour as the production append path.

Usage
─────

    # See what would be written without touching the file.
    python scripts/backfill_rank_history.py --dry-run

    # Actually write.
    python scripts/backfill_rank_history.py

    # Only process snapshots on/after a cutoff (useful for
    # incremental catch-up after partial backfills).
    python scripts/backfill_rank_history.py --since 2026-03-25

    # Point at a non-default archive directory / history file
    # (used by the unit tests).
    python scripts/backfill_rank_history.py \\
        --archive-dir /tmp/fake_archive \\
        --history-path /tmp/fake_history.jsonl
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path
from typing import Any, Callable, Iterator

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.api import rank_history  # noqa: E402
from src.api.data_contract import build_api_data_contract  # noqa: E402

DEFAULT_ARCHIVE_DIR: Path = REPO / "exports" / "archive"

_FILENAME_RE = re.compile(r"^dynasty_export_(\d{8})_(\d{6})\.zip$")


def _date_from_ymd(ymd: str) -> str:
    """``20260422`` -> ``2026-04-22``."""
    return f"{ymd[0:4]}-{ymd[4:6]}-{ymd[6:8]}"


def _iter_candidate_zips(archive_dir: Path) -> Iterator[tuple[str, str, Path]]:
    """Yield ``(date_str, hhmmss, zip_path)`` for every recognised archive.

    Unrecognised filenames are silently skipped — the archive
    directory has historically carried a few orphan files that don't
    match the scraper's naming convention, and surfacing them as
    errors would make every run noisy.
    """
    if not archive_dir.exists() or not archive_dir.is_dir():
        return
    for p in sorted(archive_dir.iterdir()):
        if not p.is_file() or p.suffix != ".zip":
            continue
        m = _FILENAME_RE.match(p.name)
        if not m:
            continue
        yield _date_from_ymd(m.group(1)), m.group(2), p


def _select_archives_by_date(
    archive_dir: Path,
) -> list[tuple[str, list[Path]]]:
    """Return ``[(date_str, [zip_path, ...]), ...]`` in ascending date order.

    Each inner list is ordered newest-HHMMSS first.  The caller walks
    the list and picks the first candidate that loads + builds
    cleanly — so a corrupt latest archive falls back to an earlier
    same-day archive instead of dropping the whole day.  That matters
    because scrape days almost always have 4-6 bundles and a single
    truncated final upload shouldn't defeat the backfill for that
    day.  When every bundle loads (the common case) this behaves
    identically to a latest-wins pre-selection: the first candidate
    succeeds and the rest are never touched.
    """
    by_date: dict[str, list[tuple[str, Path]]] = {}
    for date_str, hms, path in _iter_candidate_zips(archive_dir):
        by_date.setdefault(date_str, []).append((hms, path))
    out: list[tuple[str, list[Path]]] = []
    for date_str in sorted(by_date.keys()):
        candidates = sorted(by_date[date_str], key=lambda t: t[0], reverse=True)
        out.append((date_str, [p for _, p in candidates]))
    return out


def _load_raw_from_zip(zip_path: Path) -> tuple[str | None, dict[str, Any] | None]:
    """Return ``(manifest_date, raw_payload)`` from a single archive.

    ``manifest_date`` is the value stamped by the scraper inside
    ``manifest.json`` (the authoritative date for the bundle, used in
    preference to the filename when they disagree).  Returns
    ``(None, None)`` if the zip is corrupt or missing the expected
    members — the caller logs & skips.
    """
    try:
        with zipfile.ZipFile(zip_path) as z:
            manifest_date: str | None = None
            try:
                with z.open("manifest.json") as mf:
                    manifest = json.load(mf)
                if isinstance(manifest, dict):
                    maybe = manifest.get("date")
                    if isinstance(maybe, str):
                        manifest_date = maybe
            except KeyError:
                pass
            except json.JSONDecodeError:
                pass

            data_name: str | None = None
            for n in z.namelist():
                if n.startswith("dynasty_data_") and n.endswith(".json"):
                    data_name = n
                    break
            if data_name is None and "dynasty_data.json" in z.namelist():
                data_name = "dynasty_data.json"
            if data_name is None:
                return manifest_date, None

            with z.open(data_name) as df:
                raw = json.load(df)
            if not isinstance(raw, dict):
                return manifest_date, None
            if manifest_date is None:
                maybe = raw.get("date")
                if isinstance(maybe, str):
                    manifest_date = maybe
            return manifest_date, raw
    except (zipfile.BadZipFile, OSError, json.JSONDecodeError):
        return None, None


def _count_ranked_rows(contract: dict[str, Any]) -> int:
    """How many rows would ``append_snapshot`` record for this contract.

    Mirrors the filter in ``rank_history._extract_ranks``: a row
    counts only if it has a name AND a positive integer
    ``canonicalConsensusRank``.  Used for the dry-run preview where
    we want the same number that would actually land in the JSONL
    without invoking the extraction helper's dict build.
    """
    arr = contract.get("playersArray")
    if not isinstance(arr, list):
        data = contract.get("data") or {}
        arr = data.get("playersArray") if isinstance(data, dict) else None
    if not isinstance(arr, list):
        return 0
    n = 0
    for row in arr:
        if not isinstance(row, dict):
            continue
        name = row.get("canonicalName") or row.get("displayName")
        rank = row.get("canonicalConsensusRank")
        if name and isinstance(rank, int) and rank > 0:
            n += 1
    return n


def backfill(
    archive_dir: Path,
    *,
    history_path: Path | None = None,
    dry_run: bool = False,
    max_snapshots: int = rank_history.MAX_SNAPSHOTS,
    since: str | None = None,
    build_contract: Callable[[dict[str, Any]], dict[str, Any]] = build_api_data_contract,
    out=None,
) -> list[dict[str, Any]]:
    """Replay archived snapshots into the rank-history log.

    Parameters
    ──────────
    archive_dir
        Directory of ``dynasty_export_*.zip`` bundles.
    history_path
        Target JSONL path.  Defaults to ``rank_history.HISTORY_PATH``.
    dry_run
        When ``True`` we print what would be written but never touch
        the file — size-growth reporting shows a flat 0.
    max_snapshots
        Retention cap forwarded to ``append_snapshot``.  Defaults to
        the module-level constant (180).
    since
        Optional ``YYYY-MM-DD`` floor; snapshots with ``date < since``
        are skipped.
    build_contract
        Injection seam so tests can bypass the real contract builder.
        Default is ``build_api_data_contract``.
    out
        Output stream for the progress report (defaults to stdout).

    Returns
    ───────
    A list of per-snapshot result dicts suitable for programmatic
    inspection (the unit tests use this; the CLI ignores it and
    relies on the printed report).
    """
    history_path = history_path or rank_history.HISTORY_PATH
    stream = out if out is not None else sys.stdout

    def _print(msg: str = "") -> None:
        print(msg, file=stream)

    start_size = history_path.stat().st_size if history_path.exists() else 0

    _print(f"Archive dir:   {archive_dir}")
    _print(f"History path:  {history_path}")
    _print(f"Max snapshots: {max_snapshots}")
    if since:
        _print(f"Since:         {since}")
    if dry_run:
        _print("DRY RUN — no writes will occur")
    _print("")
    _print(f"  {'date':<12} {'rows':>5}  {'status':<9}  archive")
    _print("  " + "-" * 68)

    results: list[dict[str, Any]] = []
    selections = _select_archives_by_date(archive_dir)

    for filename_date, candidates in selections:
        # Walk newest -> oldest HHMMSS for this day.  The first
        # candidate that loads + builds wins; older ones only come
        # into play if the newer ones are corrupt or trip build_
        # contract.  Without this fallback a single bad latest-of-
        # the-day upload drops the whole date even when yesterday's
        # scrape had 5 other valid bundles.
        chosen: tuple[str | None, dict[str, Any], Path, dict[str, Any]] | None = None
        attempt_failures: list[tuple[Path, str]] = []

        for candidate in candidates:
            manifest_date, raw = _load_raw_from_zip(candidate)
            if raw is None:
                attempt_failures.append((candidate, "unreadable"))
                continue

            effective_date = manifest_date or filename_date
            if since and effective_date < since:
                # ``--since`` is evaluated against the manifest-
                # authoritative date, matching what ``append_snapshot``
                # will actually write; filename/manifest mismatches
                # would otherwise produce off-by-one skips at the
                # cutoff boundary.  Skipping here still allows older
                # same-day candidates to be tried for days whose
                # manifest floats them over the cutoff.
                attempt_failures.append((candidate, "before-since"))
                continue

            try:
                contract = build_contract(raw)
            except Exception as exc:  # noqa: BLE001
                attempt_failures.append((candidate, f"build-err: {exc}"))
                continue

            chosen = (manifest_date, contract, candidate, {})
            break

        if chosen is None:
            # Nothing salvageable for this day.  Only log when the
            # reason wasn't a pure --since skip — an entirely-
            # before-cutoff day is expected and shouldn't pollute
            # the report.
            non_since_failures = [
                (p, reason) for p, reason in attempt_failures
                if reason != "before-since"
            ]
            if not non_since_failures:
                continue
            for path, reason in non_since_failures:
                label = "unreadable" if reason == "unreadable" else "build-err"
                _print(
                    f"  {filename_date:<12} {'?':>5}  {label:<9}  {path.name}"
                    + (f": {reason[len('build-err: '):]}" if reason.startswith("build-err: ") else "")
                )
                results.append(
                    {
                        "date": filename_date,
                        "zip": str(path),
                        "rows": 0,
                        "appended": False,
                        "dry_run": dry_run,
                        "skipped": reason,
                    }
                )
            continue

        manifest_date, contract, zip_path, _ = chosen
        effective_date = manifest_date or filename_date

        row_count = _count_ranked_rows(contract)
        appended = False
        if row_count == 0:
            status = "empty"
        elif dry_run:
            status = "WOULD"
        else:
            appended = rank_history.append_snapshot(
                contract,
                date=effective_date,
                path=history_path,
                max_snapshots=max_snapshots,
            )
            status = "appended" if appended else "skipped"

        _print(
            f"  {effective_date:<12} {row_count:>5d}  {status:<9}  {zip_path.name}"
        )
        results.append(
            {
                "date": effective_date,
                "zip": str(zip_path),
                "rows": row_count,
                "appended": appended and not dry_run,
                "dry_run": dry_run,
            }
        )

    end_size = history_path.stat().st_size if history_path.exists() else 0
    delta = end_size - start_size

    _print("")
    _print(
        f"Processed {len(results)} snapshot(s).  "
        f"History file: {start_size} -> {end_size} bytes "
        f"({'+' if delta >= 0 else ''}{delta})"
    )
    if dry_run and delta != 0:
        # Defensive: a dry run should never move the file pointer.
        # If we ever land here it's a regression in the injected
        # build/append path, not a normal outcome.
        _print("WARN: dry-run recorded non-zero size delta; check the injected build_contract.")

    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Backfill data/rank_history.jsonl from exports/archive snapshots.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--archive-dir",
        type=Path,
        default=DEFAULT_ARCHIVE_DIR,
        help="Directory of dynasty_export_*.zip bundles (default: exports/archive).",
    )
    parser.add_argument(
        "--history-path",
        type=Path,
        default=None,
        help="Target JSONL path (default: data/rank_history.jsonl).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be appended without writing the history file.",
    )
    parser.add_argument(
        "--max-snapshots",
        type=int,
        default=rank_history.MAX_SNAPSHOTS,
        help=f"Retention cap (default: {rank_history.MAX_SNAPSHOTS}).",
    )
    parser.add_argument(
        "--since",
        default=None,
        help="Only process snapshots with date >= YYYY-MM-DD.",
    )
    args = parser.parse_args(argv)

    backfill(
        archive_dir=args.archive_dir,
        history_path=args.history_path,
        dry_run=args.dry_run,
        max_snapshots=args.max_snapshots,
        since=args.since,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
