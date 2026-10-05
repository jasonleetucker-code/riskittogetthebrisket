"""Read-only, privacy-safe proof from the existing production scrape event stream.

Input is JSONL over stdin. Raw messages and metadata are never printed.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from typing import Iterable

_SHA = re.compile(r"^[0-9a-f]{40}$")
_WORKER = re.compile(r"^run-[0-9a-f]{12}$")
_SOURCE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,39}$")
_TERMINAL = {"source_complete", "source_partial", "source_failed"}


class ProofError(ValueError):
    """The input does not contain a current, correlated source lifecycle."""


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def prove(lines: Iterable[str], *, now: datetime | None = None, max_age_hours: int = 48) -> dict:
    if not 1 <= max_age_hours <= 168:
        raise ProofError("invalid maximum age")
    clock = now or datetime.now(timezone.utc)
    checkout_sha = None
    starts: dict[tuple[str, str], datetime] = {}
    completed: list[tuple[datetime, datetime, str, str, str]] = []
    for line in lines:
        try:
            row = json.loads(line)
        except (TypeError, ValueError):
            continue
        if not isinstance(row, dict):
            continue
        if row.get("type") == "checkout_identity":
            candidate = row.get("sha")
            if isinstance(candidate, str) and _SHA.fullmatch(candidate):
                checkout_sha = candidate
            continue
        event = row.get("event")
        if event != "source_start" and event not in _TERMINAL:
            continue
        worker = row.get("worker_id")
        source = row.get("source")
        timestamp = _timestamp(row.get("ts"))
        if (
            not isinstance(worker, str)
            or not _WORKER.fullmatch(worker)
            or not isinstance(source, str)
            or not _SOURCE.fullmatch(source)
            or timestamp is None
        ):
            continue
        key = (worker, source)
        if event == "source_start":
            starts[key] = timestamp
        elif key in starts:
            start = starts.pop(key)
            if start <= timestamp <= clock and timestamp - start <= timedelta(hours=2):
                completed.append((timestamp, start, worker, source, event))
    if checkout_sha is None:
        raise ProofError("production checkout identity unavailable")
    if not completed:
        raise ProofError("no correlated source start and terminal event")
    end, start, worker, source, outcome = max(completed)
    if clock - end > timedelta(hours=max_age_hours):
        raise ProofError("latest complete source lifecycle is stale")
    return {
        "schema": "scrape-source-lifecycle-proof/v1",
        "checkout_sha": checkout_sha,
        "worker_id": worker,
        "source": source,
        "outcome": outcome,
        "started_at": start.isoformat(),
        "completed_at": end.isoformat(),
        "duration_seconds": round((end - start).total_seconds(), 3),
        "status": "observed",
    }


def main() -> int:
    try:
        result = prove(sys.stdin)
    except ProofError as exc:
        print(f"::error title=Scrape source lifecycle proof::{exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
