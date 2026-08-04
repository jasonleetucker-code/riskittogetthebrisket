#!/usr/bin/env python3
"""Measure the as-of historical panel available to Consensus Edge.

Consensus Edge cannot honestly fit weights without out-of-sample
history, and the discovery pass concluded there was almost none: the
only visible history was ``exports/archive/*.zip`` — 21 daily bundles
carrying just three source CSVs.  That conclusion was an artifact of a
**shallow clone**.

``.github/workflows/scheduled-refresh.yml`` commits ``CSVs/site_raw/``
with ``git add -f`` every two hours, so every source board this repo
has ever fetched is preserved in git history.  Reconstructing the board
as of any past date is therefore a ``git show <commit>:<path>`` away —
no new collection, no waiting for calendar time.

This script measures what that history actually contains, because the
answer decides how much of the backtest phase is honest:

  * per source: how many distinct dates it changed on, and its span
  * the panel: how many as-of dates can be reconstructed with a given
    minimum number of sources present
  * the forward-outcome horizon: how many non-overlapping folds a given
    holding period admits

A source that updates weekly shows fewer "change days" than one that
updates hourly, and that is not a defect — the as-of reconstruction
carries each source's last-known value forward, exactly as the live
pipeline does.  What matters is the span, not the change count.

Exit codes (repo convention — see scripts/refresh_playerctx.py):
    0  - measurement written
    1  - soft failure (not a git repo, no history, write error)
    2  - schema regression: the clone is shallow, so any measurement
         would understate the panel and must not be recorded
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SITE_RAW = "CSVs/site_raw"
OUT_DIR = REPO / "docs" / "measurements"

# Holding periods we would evaluate a buy/sell call over.  Chosen to
# bracket the horizons the discovery report proposed (30/90/180d) so the
# report can say plainly which are reachable and which are not.
HORIZONS_DAYS = (7, 14, 30, 60, 90, 180)


def log(msg: str) -> None:
    print(f"[panel-measure] {msg}")


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def _is_shallow() -> bool:
    return (REPO / ".git" / "shallow").exists()


def _tracked_site_raw() -> list[str]:
    out = _git("ls-files", SITE_RAW)
    return sorted(p for p in out.splitlines() if p.endswith(".csv"))


def _change_dates(path: str) -> list[str]:
    """UTC dates on which ``path`` changed, oldest first."""
    out = _git("log", "--format=%ad", "--date=short", "--", path)
    return sorted({line.strip() for line in out.splitlines() if line.strip()})


def _daterange(start: date, end: date) -> list[date]:
    span = (end - start).days
    return [start + timedelta(days=i) for i in range(span + 1)]


def measure() -> dict:
    files = _tracked_site_raw()
    if not files:
        raise RuntimeError(f"no tracked CSVs under {SITE_RAW}")

    per_source: dict[str, dict] = {}
    for path in files:
        dates = _change_dates(path)
        key = Path(path).stem
        per_source[key] = {
            "path": path,
            "changeDates": len(dates),
            "first": dates[0] if dates else None,
            "last": dates[-1] if dates else None,
        }

    firsts = [v["first"] for v in per_source.values() if v["first"]]
    lasts = [v["last"] for v in per_source.values() if v["last"]]
    panel_start = min(firsts)
    panel_end = max(lasts)

    start_d = datetime.strptime(panel_start, "%Y-%m-%d").date()
    end_d = datetime.strptime(panel_end, "%Y-%m-%d").date()
    all_days = _daterange(start_d, end_d)

    # For each calendar day, how many sources have at least one commit on
    # or before it?  That is the count reconstructable as-of that day.
    firsts_by_source = {
        k: datetime.strptime(v["first"], "%Y-%m-%d").date()
        for k, v in per_source.items()
        if v["first"]
    }
    coverage_by_day = {
        d.isoformat(): sum(1 for f in firsts_by_source.values() if f <= d) for d in all_days
    }

    # Usable as-of dates at a few source-count floors.
    floors = (3, 5, 10, 15, 20)
    usable = {str(n): sum(1 for c in coverage_by_day.values() if c >= n) for n in floors}

    # Forward-outcome capacity: with a panel of N calendar days, a
    # holding period of H days admits (N - H) origin dates and
    # floor(N / H) NON-OVERLAPPING folds.  Overlapping origins are not
    # independent observations, so the fold count is the honest number.
    n_days = len(all_days)
    horizons = {
        str(h): {
            "originDates": max(0, n_days - h),
            "nonOverlappingFolds": n_days // h,
        }
        for h in HORIZONS_DAYS
    }

    deep = sorted(
        (k for k, v in per_source.items() if v["changeDates"] >= 50),
        key=lambda k: -per_source[k]["changeDates"],
    )
    thin = sorted(
        (k for k, v in per_source.items() if v["changeDates"] < 10),
        key=lambda k: per_source[k]["changeDates"],
    )

    return {
        "measuredAt": datetime.now(timezone.utc).isoformat(),
        "method": (
            "git history of CSVs/site_raw/*.csv, committed every 2h by "
            "scheduled-refresh.yml; as-of state for any date is the last "
            "commit <= that date touching each file"
        ),
        "totalCommits": int(_git("rev-list", "--count", "HEAD").strip()),
        "panel": {
            "start": panel_start,
            "end": panel_end,
            "calendarDays": n_days,
            "sources": len(per_source),
        },
        "usableAsOfDatesByMinSourceCount": usable,
        "forwardOutcomeCapacity": horizons,
        "deepSources": deep,
        "thinSources": thin,
        "perSource": per_source,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=None, help="output JSON path")
    ap.add_argument("--dry-run", action="store_true", help="print, do not write")
    args = ap.parse_args(argv)

    if _is_shallow():
        print(
            "[panel-measure] shallow clone: run `git fetch --unshallow` first. "
            "Measuring now would understate the panel and the number would be "
            "quoted later as if it were real.",
            file=sys.stderr,
        )
        return 2

    try:
        result = measure()
    except subprocess.CalledProcessError as exc:
        print(f"[panel-measure] git failed: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 — CLI boundary
        print(f"[panel-measure] failed: {exc}", file=sys.stderr)
        return 1

    panel = result["panel"]
    log(
        f"panel {panel['start']} -> {panel['end']} "
        f"({panel['calendarDays']} days, {panel['sources']} sources)"
    )
    log(f"deep sources (>=50 change-days): {', '.join(result['deepSources']) or 'none'}")
    log(f"thin sources (<10 change-days): {', '.join(result['thinSources']) or 'none'}")
    for h, cap in result["forwardOutcomeCapacity"].items():
        log(f"  {h}d horizon: {cap['nonOverlappingFolds']} non-overlapping folds")

    if args.dry_run:
        print(json.dumps(result, indent=2))
        return 0

    out = args.out or (OUT_DIR / f"consensus-edge-panel-{date.today().isoformat()}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n")
    log(f"wrote {out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
