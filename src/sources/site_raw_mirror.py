"""Raw vendor CSVs that must reach the export bundle to be observable.

WHY THIS EXISTS (V1-89 / OD-04, measured 2026-08-25).

``scripts/check_source_health.measure_content_staleness`` answers "how
long has this source's raw CSV been byte-identical", and it reads
exactly one evidence lane: the tracked ``exports/archive/*.zip``
bundles.  Those bundles are assembled by ``Dynasty Scraper.py`` from its
own ``FULL_DATA`` maps, so ``exports/latest/site_raw/`` carried the
three sources the legacy scraper produces and nothing else.

Every source acquired by a standalone fetcher writes straight into
``CSVs/site_raw/`` and therefore never entered an archive — so the
detector could not evaluate it, at all, ever.  Measured consequence for
DraftSharks: substituting 8-day-old CSVs while leaving the fetch stamps
current produced a health verdict byte-identical to the healthy run.
The detector was not wrong; it was never given the bytes.

WHAT THIS IS NOT.  Not a second staleness detector, not a new health
vocabulary, not a new writer.  It copies files into the bundle the
existing export path already builds, so the existing detector can see
them and report them with the words it already uses.

WHAT IT PRESERVES.  Files are copied VERBATIM — 13-column vendor rows
for the dynasty boards, 7-column rows for the ROS boards, not the
``name,value`` shape ``FULL_DATA`` emits.  The detector hashes bytes and
asks only whether one acquisition is comparable with itself across
archives, so the vendor's own schema is the right thing to preserve.

ABSENT IS ABSENT.  A missing source file is skipped, never written as an
empty placeholder: a placeholder would make a never-acquired source look
perfectly byte-stable, which is the exact failure this module exists to
remove.

ONE-RUN LAG, stated rather than hidden.  ``scheduled-refresh.yml`` runs
the scraper BEFORE the standalone fetchers, so the bundle written by run
N carries the CSVs acquired by run N-1.  A constant offset does not
distort a "how long has this been byte-identical" measurement — content
changing every run still reads 0 days, content frozen for a month still
reads a month — and closing it would mean a second archive writer.
"""

from __future__ import annotations

import shutil
from pathlib import Path

#: Raw vendor CSVs that vote through ``_RANKING_SOURCES`` in
#: ``src/api/data_contract.py`` but are acquired by a standalone fetcher
#: rather than by ``Dynasty Scraper.py``, so the export bundle never saw
#: them.  Held in step with the registry by
#: ``tests/sources/test_site_raw_mirror.py``, which fails if a name here
#: stops being a registered source path.
MIRRORED_SITE_RAW_CSVS: tuple[str, ...] = (
    "draftSharksSf.csv",
    "draftSharksIdp.csv",
    "draftSharksRosSf.csv",
    "draftSharksRosIdp.csv",
)


def mirror_site_raw_csvs(
    *,
    repo_root: Path,
    site_raw_dir: Path,
    produced_this_run: set[str] | frozenset[str] = frozenset(),
    names: tuple[str, ...] = MIRRORED_SITE_RAW_CSVS,
) -> dict[str, str]:
    """Copy the named ``CSVs/site_raw`` files into the export bundle.

    Returns ``{filename: outcome}`` where outcome is one of
    ``"mirrored"``, ``"missing_source"`` (the fetcher has never produced
    it, or produced nothing this cycle and no last-good exists) or
    ``"skipped_scraper_owns"``.

    ``produced_this_run`` is the set of filenames the scraper itself
    wrote from ``FULL_DATA`` this run.  A name in that set is never
    overwritten: ``FULL_DATA`` stays the owner of everything it emits,
    and a future name collision has to be a visible skip rather than a
    silent replacement.
    """
    source_dir = Path(repo_root) / "CSVs" / "site_raw"
    dest_dir = Path(site_raw_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    outcomes: dict[str, str] = {}
    for name in names:
        if name in produced_this_run:
            outcomes[name] = "skipped_scraper_owns"
            continue
        src = source_dir / name
        if not src.is_file():
            outcomes[name] = "missing_source"
            continue
        try:
            shutil.copy2(src, dest_dir / name)
        except OSError:
            outcomes[name] = "missing_source"
            continue
        outcomes[name] = "mirrored"
    return outcomes
