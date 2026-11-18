#!/usr/bin/env python3
"""Is a production deploy in flight?  One answer for every on-box workflow.

On-box diagnostics (``signals-health-probe.yml``, ``signals-onbox-verification.yml``)
refuse to run while a Deploy Production run could move the checkout under them.
They used to count EVERY ``deploy.yml`` run in an active status, so a run GitHub
created but never started blocked them forever.  Measured 2026-11-18: two such
runs sat in ``queued`` — one since 2026-08-19 (a ``workflow_dispatch`` of
``1d9a001c``), one since 2026-11-11 (a push of ``44a0d573``) — and both refuse
GitHub's ordinary cancel ("not in progress" / "not been queued yet").  Every
on-box Signals run failed "Production deploy in flight" with no deploy running,
which is why the 16-day ``signalsSf`` stall could not even be diagnosed.

The rule now:

* ``in_progress`` — always in flight, whatever its age;
* ``queued`` / ``waiting`` / ``pending`` / ``requested`` — in flight only while
  younger than ``ORPHAN_AFTER_HOURS``.  A deploy starts within seconds and runs
  for well under an hour, so a run that has not STARTED after six hours is an
  orphan, not a deploy.  Orphans are named in a warning so they stay visible
  (they still need cancelling in the Actions UI) instead of silently blocking;
* a run whose age cannot be read counts as in flight (fail closed);
* the run list itself unreadable → exit 2, never "clear".

Exit codes: 0 clear, 1 a deploy is in flight, 2 the deploy state is unreadable.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone

ACTIVE_STATUSES = ("in_progress", "queued", "waiting", "pending", "requested")
ORPHAN_AFTER_HOURS = 6.0


def _parse_ts(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def classify(
    runs: Iterable[dict],
    now: datetime,
    orphan_after_hours: float = ORPHAN_AFTER_HOURS,
) -> tuple[list[dict], list[dict]]:
    """Split active deploy runs into (in flight, orphaned)."""
    busy: list[dict] = []
    orphaned: list[dict] = []
    seen: set[object] = set()
    for run in runs:
        key = run.get("id")
        if key in seen:
            continue
        seen.add(key)
        status = run.get("status")
        if status not in ACTIVE_STATUSES:
            continue
        if status == "in_progress":
            busy.append(run)
            continue
        created = _parse_ts(run.get("created_at"))
        if created is None:
            busy.append(run)
            continue
        if now - created >= timedelta(hours=orphan_after_hours):
            orphaned.append(run)
        else:
            busy.append(run)
    return busy, orphaned


def _describe(run: dict) -> str:
    return (
        f"run {run.get('id')} ({run.get('event')}, {run.get('status')}, "
        f"created {run.get('created_at')}, sha {str(run.get('head_sha') or '')[:8]})"
    )


def _fetch_active_runs(repo: str) -> list[dict]:
    runs: list[dict] = []
    for status in ACTIVE_STATUSES:
        out = subprocess.run(
            [
                "gh",
                "api",
                f"repos/{repo}/actions/workflows/deploy.yml/runs?status={status}&per_page=100",
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        payload = json.loads(out)
        page = payload.get("workflow_runs")
        if not isinstance(page, list):
            raise ValueError(f"no workflow_runs list for status={status}")
        runs.extend(page)
    return runs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", required=True, help="owner/name")
    ap.add_argument("--orphan-after-hours", type=float, default=ORPHAN_AFTER_HOURS)
    args = ap.parse_args(argv)
    try:
        runs = _fetch_active_runs(args.repo)
    except (subprocess.CalledProcessError, ValueError, json.JSONDecodeError) as exc:
        print(f"::error title=Deploy state unreadable::{type(exc).__name__}")
        return 2
    busy, orphaned = classify(runs, datetime.now(timezone.utc), args.orphan_after_hours)
    for run in orphaned:
        print(
            "::warning title=Orphaned deploy run::"
            f"{_describe(run)} never started; ignored as not in flight. Cancel it in the Actions UI."
        )
    if busy:
        print("::error title=Production deploy in flight::" + "; ".join(_describe(r) for r in busy))
        return 1
    print(f"no deploy in flight ({len(orphaned)} orphaned run(s) ignored)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
