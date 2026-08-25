"""One rule for "give me a real board to test against".

WHY THIS EXISTS
───────────────
Several deterministic tests build a real contract from the tracked
export archive rather than a synthetic fixture, and that is the right
call — the properties they check (source correlation leaks, the
consensus-edge input seam, snapshot round-trips) are properties of how
~21 real sources interact, and a three-source fixture would pass while
the live board was broken.

Each of them reached for ``sorted(archive.glob(...))[-1]`` — *the newest*
bundle.  That silently made them a function of the most recent scrape's
HEALTH.  On 2026-08-16 one KTC fetch timed out (300 s against a 39-run
baseline of ~18.8 s) and the resulting bundle carried an empty KTC board;
twelve consensus-edge tests in the blocking gate then failed with
``'offense' not found in set()`` — no code defect, no board defect, just
a provider that did not answer that once.

A seam test needs *a real complete board*, not *the latest board*.  This
module supplies exactly that: the newest archived scrape that the
contract's OWN source-health definition calls complete.  Deterministic
(the archive is tracked), immune to a single bad scrape, and it degrades
by SKIPPING rather than by passing vacuously.

It does not soften any assertion, and it is not a livedata exemption:
these tests stay in the blocking gate.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ARCHIVE = REPO / "exports" / "archive"


def _degraded_critical_sources(payload: dict) -> list[str]:
    """Critical sources this scrape failed to complete.

    Classification comes from the contract validator's own constants, so
    "critical" means here exactly what it means in ``contractHealth``.
    """
    from src.api.data_contract import (
        TOLERABLE_PARTIAL_SOURCES,
        critical_primary_for_run_source,
    )

    settings = payload.get("settings") if isinstance(payload.get("settings"), dict) else {}
    summary = settings.get("sourceRunSummary") if isinstance(settings, dict) else None
    if not isinstance(summary, dict):
        return []
    degraded: list[str] = []
    for key in ("partialSources", "failedSources", "timedOutSources"):
        for src in summary.get(key) or []:
            name = str(src)
            if name in TOLERABLE_PARTIAL_SOURCES:
                continue
            if critical_primary_for_run_source(name) is not None:
                degraded.append(name)
    return degraded


def newest_complete_raw_payload() -> tuple[dict | None, str | None]:
    """``(payload, archive_name)`` for the newest COMPLETE archived scrape.

    ``(None, None)`` when the archive is absent or every bundle in it is
    source-degraded — in which case callers skip, because a degraded
    board cannot answer the question they are asking.
    """
    if not ARCHIVE.is_dir():
        return None, None
    for archive in sorted(ARCHIVE.glob("dynasty_export_*.zip"), reverse=True):
        try:
            with zipfile.ZipFile(archive) as zf:
                names = [
                    n
                    for n in zf.namelist()
                    if n.startswith("dynasty_data_") and n.endswith(".json")
                ]
                if not names:
                    continue
                payload = json.loads(zf.read(names[0]))
        except (OSError, ValueError, zipfile.BadZipFile):
            continue
        if not isinstance(payload, dict):
            continue
        if _degraded_critical_sources(payload):
            continue
        return payload, archive.name
    return None, None
