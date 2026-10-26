#!/usr/bin/env python3
"""Report which BROWSER-driven source CSVs were kept, not rewritten, this refresh.

WHY THIS EXISTS (2026-10-25).  The Scheduled Data Refresh lost its Chromium
(the floating ``ubuntu-latest`` label became ubuntu-26.04, where the locked
Playwright cannot install it).  Every browser-driven fetcher then produced
nothing, the orchestrator restored the last-good CSVs and correctly declined to
stamp them, and five consecutive runs still concluded ``success``.  The
evidence was in the raw log and nowhere a person looks.

This is SIGNAL, not a gate.  It reads files the refresh already produced,
appends a short block to the job summary and raises one ``::warning`` when a
browser-dependent CSV was kept from the previous run.  It never writes a CSV,
never writes a freshness stamp, never reads a threshold, and ALWAYS exits 0, so
it cannot turn a green refresh red.  Whether a source preserved for N
consecutive runs should eventually fail the run is an owner decision, not made
here.

The list of browser-dependent sources lives in :data:`BROWSER_SOURCES` and
nowhere else; ``tests/deploy/test_scheduled_refresh_playwright_runner.py`` fails
if the workflow starts invoking a Playwright fetcher this list does not name.

HOW "KEPT" IS DECIDED (two evidence lanes, because the files differ):

* **Scraper-owned** (``Dynasty Scraper.py``: KTC x5, IDP Trade Calculator).
  A file mtime cannot answer the question: the scraper's restore pass writes the
  last-good copy back with ``open(dest, "wb")``, which gives it a CURRENT mtime
  (audit Z-2, the reason ``stamp_if_present`` consults the manifest).  So the
  authority is ``exports/latest/manifest.json::siteRawPreserved`` - but only a
  manifest written THIS run.  ``exports/latest/`` is tracked, so a scraper that
  dies before writing leaves last run's manifest on disk; a manifest not newer
  than the pre-scrape marker is ignored and the mtime test below decides.
* **Standalone fetchers** (``fetch_draftsharks.py``, ``fetch_draftsharks_ros.py``).
  The manifest is NOT evidence here: the scraper runs BEFORE these fetchers, so
  ``siteRawPreserved`` lists the DraftSharks CSVs on every healthy run too (they
  are never in the scraper's own output).  Their writers open the destination
  for writing only on success and every guard returns before writing, so "the
  CSV is newer than the pre-scrape marker" is exactly "the fetcher wrote it".
  The export-bundle mirror uses ``copy2`` and the workflow's mirror-back uses
  ``cp -p``, both mtime-preserving, so neither can fake a rewrite.

Missing is never zero and unknown is never fine: a CSV that is absent is
reported as missing, and a marker that cannot be found yields a notice that
says the question could not be answered, not a clean bill of health.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BrowserSource:
    """One CSV whose producer drives a real browser."""

    name: str  # CSV stem; what the freshness machinery calls the board
    csv: str  # basename under CSVs/site_raw
    fetcher: str  # repo-relative entry point that drives the browser
    scraper_owned: bool  # True: manifest.siteRawPreserved is evidence for it


_SCRAPER = "Dynasty Scraper.py"
_DS = "scripts/fetch_draftsharks.py"
_DS_ROS = "scripts/fetch_draftsharks_ros.py"

#: THE list of browser-dependent source CSVs.  Add a browser-driven fetcher to
#: ``scheduled-refresh.yml`` and its CSVs here in the same change.
BROWSER_SOURCES: tuple[BrowserSource, ...] = (
    BrowserSource("ktc", "ktc.csv", _SCRAPER, True),
    BrowserSource("ktcSfTep", "ktcSfTep.csv", _SCRAPER, True),
    BrowserSource("ktcCrowdSfTep", "ktcCrowdSfTep.csv", _SCRAPER, True),
    BrowserSource("ktcTradesSfTep", "ktcTradesSfTep.csv", _SCRAPER, True),
    BrowserSource("ktcCrowdTradesSfTep", "ktcCrowdTradesSfTep.csv", _SCRAPER, True),
    BrowserSource("idpTradeCalc", "idpTradeCalc.csv", _SCRAPER, True),
    BrowserSource("draftSharksSf", "draftSharksSf.csv", _DS, False),
    BrowserSource("draftSharksIdp", "draftSharksIdp.csv", _DS, False),
    BrowserSource("draftSharksRosSf", "draftSharksRosSf.csv", _DS_ROS, False),
    BrowserSource("draftSharksRosIdp", "draftSharksRosIdp.csv", _DS_ROS, False),
)

REASON_MISSING = "CSV missing"
REASON_RESTORED = "scraper restored the last-good copy (manifest siteRawPreserved)"
REASON_NOT_REWRITTEN = "CSV not rewritten this run (kept previous file)"


@dataclass(frozen=True)
class ManifestEvidence:
    """What ``manifest.json`` can and cannot say about THIS run."""

    state: str  # "current" | "stale" | "absent" | "unreadable"
    preserved: frozenset[str] = frozenset()


def read_manifest(path: Path, marker_ns: int) -> ManifestEvidence:
    """``siteRawPreserved`` of a manifest written after the pre-scrape marker."""
    try:
        stat = path.stat()
    except OSError:
        return ManifestEvidence("absent")
    if stat.st_mtime_ns <= marker_ns:
        # Tracked file left over from checkout: it describes the PREVIOUS run.
        return ManifestEvidence("stale")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        preserved = data.get("siteRawPreserved") or []
        return ManifestEvidence("current", frozenset(str(item) for item in preserved))
    except (OSError, ValueError, AttributeError, TypeError):
        return ManifestEvidence("unreadable")


def kept_reason(
    source: BrowserSource,
    *,
    csv_dir: Path,
    marker_ns: int,
    manifest: ManifestEvidence,
) -> str | None:
    """Why ``source`` was kept from the previous run, or None if rewritten."""
    csv = csv_dir / source.csv
    try:
        mtime_ns = csv.stat().st_mtime_ns
    except OSError:
        return REASON_MISSING
    if source.scraper_owned and source.csv in manifest.preserved:
        return REASON_RESTORED
    # Strictly newer, the same comparison as bash ``-nt`` in stamp_if_present.
    if mtime_ns <= marker_ns:
        return REASON_NOT_REWRITTEN
    return None


def find_kept(
    *,
    csv_dir: Path,
    marker_ns: int,
    manifest: ManifestEvidence,
    sources: Sequence[BrowserSource] = BROWSER_SOURCES,
) -> list[tuple[BrowserSource, str]]:
    kept: list[tuple[BrowserSource, str]] = []
    for source in sources:
        reason = kept_reason(source, csv_dir=csv_dir, marker_ns=marker_ns, manifest=manifest)
        if reason is not None:
            kept.append((source, reason))
    return kept


def render_summary(
    kept: Sequence[tuple[BrowserSource, str]],
    *,
    total: int,
    manifest: ManifestEvidence,
) -> str:
    lines = ["### Browser-driven sources", ""]
    if not kept:
        lines.append(f"All {total} browser-dependent source CSVs were rewritten this run.")
    else:
        lines += [
            f"**{len(kept)} of {total}** browser-dependent source CSVs were kept from the "
            "previous run instead of being rewritten. A kept CSV is last-good data, not a "
            "fresh fetch, and its `_last_success` stamp is not advanced.",
            "",
            "| Source | CSV | Driven by | What happened |",
            "|---|---|---|---|",
        ]
        for source, reason in kept:
            lines.append(f"| {source.name} | {source.csv} | {source.fetcher} | {reason} |")
        lines += [
            "",
            "Look for a `Playwright chromium install failed` annotation and the fetcher "
            "output in the `Run scraper` step.",
        ]
    if manifest.state != "current":
        lines += [
            "",
            f"Manifest evidence: `{manifest.state}` (`exports/latest/manifest.json` was not "
            "written by this run); scraper-owned sources were judged by file mtime only.",
        ]
    return "\n".join(lines) + "\n"


def render_annotation(kept: Sequence[tuple[BrowserSource, str]], *, total: int) -> str:
    names = ", ".join(source.name for source, _ in kept)
    return (
        f"::warning title=Browser sources preserved::{len(kept)} of {total} browser-driven "
        f"source CSVs were kept from the previous run, not rewritten: {names}. "
        "Their freshness stamps are not advanced. Check the Playwright install step and "
        "the fetcher output in the Run scraper step."
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument(
        "--marker",
        type=Path,
        required=True,
        help="pre-scrape marker file (its mtime is 'run start')",
    )
    parser.add_argument("--csv-dir", type=Path, default=Path("CSVs/site_raw"))
    parser.add_argument("--manifest", type=Path, default=Path("exports/latest/manifest.json"))
    parser.add_argument(
        "--summary",
        type=Path,
        default=None,
        help="markdown file to append to (default: $GITHUB_STEP_SUMMARY; none if unset)",
    )
    return parser


def run(args: argparse.Namespace) -> None:
    try:
        marker_ns = args.marker.stat().st_mtime_ns
    except OSError:
        print(
            "::notice title=Browser sources not assessed::the pre-scrape marker "
            f"({args.marker}) does not exist, so the scraper step never started; "
            "no claim is made about which browser sources were rewritten."
        )
        return
    manifest = read_manifest(args.manifest, marker_ns)
    total = len(BROWSER_SOURCES)
    kept = find_kept(csv_dir=args.csv_dir, marker_ns=marker_ns, manifest=manifest)

    summary_path = args.summary
    if summary_path is None and os.environ.get("GITHUB_STEP_SUMMARY"):
        summary_path = Path(os.environ["GITHUB_STEP_SUMMARY"])
    if summary_path is not None:
        with summary_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(render_summary(kept, total=total, manifest=manifest))

    if kept:
        print(render_annotation(kept, total=total))
    else:
        print(f"browser sources: all {total} CSVs rewritten this run")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        run(args)
    except Exception as exc:  # report-only: never a new way for the refresh to fail
        print(
            f"::warning title=Browser source report failed::{type(exc).__name__}: {exc}. "
            "Reporting only; the refresh itself is unaffected."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
