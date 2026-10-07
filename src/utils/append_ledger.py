"""Append-only, monthly-rotated JSONL ledger with a sidecar key index.

One neutral owner for the mechanics the capture stores share (the
sparse-evidence shadow, ``src/api/sparse_evidence_shadow.py``, the AL-P4
pick-forecast snapshot, ``src/ros/pick_forecast_snapshot.py``, and the G4
as-known stores ``src/nfl_data/injury_history.py`` / ``src/news/archive.py``). It knows
nothing about what a record MEANS -- only that every record carries a ``key``
and a ``recordedAt``:

* one JSON line per record, appended to ``ledger-YYYY-MM.jsonl`` chosen by the
  record's own ``recordedAt`` month;
* existing lines are never rewritten; a torn final line (a crash mid-append)
  is left in place and the next record starts on a fresh line;
* idempotency is decided from ``ledger.keys`` (one key per line) instead of
  re-parsing every record. A missing index is rebuilt from the files once, and
  the newest file's final record is always merged in, so a crash between the
  ledger append and the index append cannot become a duplicate line.

A store may also carry ONE pre-rotation single file (``legacy_name``): it is
read first and its keys count, but it is never written again.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Iterator, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

INDEX_NAME = "ledger.keys"


def month_of(stamp: str | None) -> str:
    """``YYYY-MM`` of an ISO timestamp; the current UTC month when absent."""
    text = str(stamp or "")
    if len(text) >= 7 and text[4] == "-" and text[:4].isdigit() and text[5:7].isdigit():
        return text[:7]
    return datetime.now(timezone.utc).strftime("%Y-%m")


def ledger_path(base: Path, month: str | None = None) -> Path:
    """The monthly ledger file for ``month`` (``YYYY-MM...``; default: this month)."""
    return Path(base) / f"ledger-{month_of(month)}.jsonl"


def index_path(base: Path) -> Path:
    return Path(base) / INDEX_NAME


def ledger_files(base: Path, legacy_name: str | None = None) -> list[Path]:
    """Every ledger file, oldest first: the legacy file (if any), then each month."""
    base = Path(base)
    legacy = [base / legacy_name] if legacy_name and (base / legacy_name).exists() else []
    monthly = sorted(base.glob("ledger-[0-9][0-9][0-9][0-9]-[0-9][0-9].jsonl"))
    return legacy + monthly


def iter_records(path: Path) -> Iterator[dict[str, Any]]:
    """Every parseable record, in file order. A torn final line is skipped."""
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if isinstance(record, dict):
                yield record


def iter_all_records(base: Path, legacy_name: str | None = None) -> Iterator[dict[str, Any]]:
    """Every parseable record across every ledger file, oldest file first."""
    for path in ledger_files(base, legacy_name):
        yield from iter_records(path)


def last_record(path: Path) -> dict[str, Any] | None:
    """The final complete record of one file, read from its tail only."""
    if not path.exists() or path.stat().st_size == 0:
        return None
    data = b""
    with path.open("rb") as fh:
        pos = fh.seek(0, os.SEEK_END)
        while pos > 0:
            step = min(65536, pos)
            pos -= step
            fh.seek(pos)
            data = fh.read(step) + data
            if data.rstrip(b"\n").count(b"\n") >= 1:
                break
    for raw in reversed(data.rstrip(b"\n").split(b"\n")):
        try:
            record = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            continue
        return record if isinstance(record, dict) else None
    return None


def recorded_keys(base: Path, legacy_name: str | None = None) -> set[str]:
    """Every recorded key, from the sidecar index (rebuilt from the files if absent)."""
    index = index_path(base)
    if index.exists():
        with index.open("r", encoding="utf-8") as fh:
            keys = {line.strip() for line in fh if line.strip()}
    else:
        keys = {str(r["key"]) for r in iter_all_records(base, legacy_name) if r.get("key")}
    files = ledger_files(base, legacy_name)
    if files:
        tail = last_record(files[-1])
        if tail and tail.get("key"):
            keys.add(str(tail["key"]))
    return keys


def ends_with_newline(path: Path) -> bool:
    with path.open("rb") as fh:
        fh.seek(-1, os.SEEK_END)
        return fh.read(1) == b"\n"


def append_record(base: Path, record: Mapping[str, Any], legacy_name: str | None = None) -> bool:
    """Append ``record`` to its month's file unless its key is already recorded.

    True when written. The sidecar index gains the key AFTER the line is durable;
    a missing index is first seeded with every key already in the files, so it
    never forgets a record.
    """
    return append_records(base, [record], legacy_name) == 1


def append_records(
    base: Path, records: Iterable[Mapping[str, Any]], legacy_name: str | None = None
) -> int:
    """Append every record whose key is not yet recorded; return how many were written.

    The batch form of :func:`append_record`, with identical semantics: the index
    is read ONCE, a key repeated inside the batch is written once, every line is
    durable (fsync) before its key enters the index, and nothing already in a
    file is ever rewritten. Records are grouped by their ``recordedAt`` month and
    keep their input order inside a month.
    """
    batch = list(records)
    for record in batch:
        if not record.get("key"):
            raise ValueError("record has no key")
    base = Path(base)
    index = index_path(base)
    seed = not index.exists()
    known = recorded_keys(base, legacy_name)
    fresh: list[Mapping[str, Any]] = []
    taken: set[str] = set()
    for record in batch:
        key = str(record["key"])
        if key in known or key in taken:
            continue
        taken.add(key)
        fresh.append(record)
    if not fresh:
        return 0
    base.mkdir(parents=True, exist_ok=True)
    by_path: dict[Path, list[str]] = {}
    for record in fresh:
        path = ledger_path(base, record.get("recordedAt"))
        line = json.dumps(record, sort_keys=True, separators=(",", ":"), default=str)
        by_path.setdefault(path, []).append(line)
    for path, lines in by_path.items():
        torn = path.exists() and path.stat().st_size > 0 and not ends_with_newline(path)
        with path.open("a", encoding="utf-8") as fh:
            if torn:  # a crash mid-append: start fresh, never rewrite what is there
                fh.write("\n")
            for line in lines:
                fh.write(line + "\n")
            fh.flush()
            os.fsync(fh.fileno())
    index_torn = index.exists() and index.stat().st_size > 0 and not ends_with_newline(index)
    with index.open("a", encoding="utf-8") as fh:
        if index_torn:  # a crash mid-append: never glue the next key onto a partial one
            fh.write("\n")
        for k in sorted(known) if seed else ():
            fh.write(k + "\n")
        for record in fresh:
            fh.write(str(record["key"]) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    return len(fresh)
