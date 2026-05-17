#!/usr/bin/env python3
"""Pre-commit scrape sanity gate (roadmap 1.4).

Runs in scheduled-refresh.yml AFTER the scraper writes
``CSVs/site_raw/*.csv`` and BEFORE "Commit updated data" (which is
``success()``-gated, so a non-zero exit here blocks the bad data from
being committed or deployed).

Per source CSV, compared against the previously-committed version
(``git show HEAD:<path>``):

  * ERROR  — current row count < the source's registered minimum, OR
             every value cell is empty/0/NaN, OR row count collapsed
             > 50% vs the prior commit.
  * WARN   — row count dropped 30-50% (non-fatal; surfaces but ships).

Errors exit 1 (fails the step → commit/deploy skipped → the existing
"Alert on workflow failure" opens a tracking issue).  Warnings exit 0.

Conservative by design: the 50% / all-zero error bar plus the
``COLLAPSE_EXEMPT`` allowlist keep legitimate refreshes (rank jitter,
seasonal ROS emptiness) from blocking the pipeline.
"""

from __future__ import annotations

import glob
import subprocess
import sys
from pathlib import Path

# Mirror scheduled-refresh.yml::stamp_if_present minimum line counts
# (header + data rows == wc -l).  Sources not listed use DEFAULT_MIN.
MIN_LINES: dict[str, int] = {
    "ktc": 100,
    "ktcSfTep": 100,
    "idpTradeCalc": 50,
    "dynastyNerdsSfTep": 50,
    "fantasyProsSf": 50,
    "fantasyProsIdp": 50,
}
DEFAULT_MIN = 10

# Sources exempt from the row-collapse / all-zero / min-line checks.
# ROS (rest-of-season) boards are legitimately empty in the offseason
# and intentionally keep yesterday's CSV per source, so a "collapse"
# there is expected, not a scraper failure.
COLLAPSE_EXEMPT = {
    "draftSharksRosSf",
    "draftSharksRosIdp",
}

COLLAPSE_ERROR_RATIO = 0.50  # > 50% fewer rows than prior == error
COLLAPSE_WARN_RATIO = 0.70  # 30-50% fewer rows == warning


def _source_key(path: str) -> str:
    return Path(path).stem


def _data_rows(text: str) -> list[list[str]]:
    """Return non-empty data rows (header dropped) as split columns."""
    lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    if not lines:
        return []
    return [ln.split(",") for ln in lines[1:]]


def _has_any_numeric_signal(text: str) -> bool:
    """True if any data row has a nonzero number in any non-name column.

    site_raw CSVs have heterogeneous schemas (``name,value``;
    ``name,Rank,position,team``; multi-column rank exports), so we don't
    guess THE value column — a healthy scraped row always carries at
    least one numeric signal (a rank or a value).  Only a genuinely
    broken scrape (rows present but every numeric field empty/0/NaN)
    has none, which is exactly the corruption this guards against.
    """
    for row in _data_rows(text):
        for cell in row[1:]:  # skip col 0 (name)
            raw = cell.strip().replace("$", "").replace(",", "")
            if not raw or raw.lower() in {"nan", "none", "null"}:
                continue
            try:
                if float(raw) != 0.0:
                    return True
            except ValueError:
                continue
    return False


def evaluate(name: str, cur_text: str | None, prev_text: str | None) -> tuple[str, str]:
    """Pure decision function. Returns (level, message); level in
    {"ok","warn","error"}.  ``cur_text`` None == file unreadable."""
    if cur_text is None:
        return "error", f"{name}: current CSV unreadable/missing — cannot validate"

    cur_rows = len(_data_rows(cur_text))
    min_lines = MIN_LINES.get(name, DEFAULT_MIN)
    exempt = name in COLLAPSE_EXEMPT

    if not exempt and (cur_rows + 1) < min_lines:
        return (
            "error",
            f"{name}: {cur_rows} data rows (+header) < required {min_lines} lines",
        )

    if not exempt and cur_rows > 0 and not _has_any_numeric_signal(cur_text):
        return "error", f"{name}: no numeric signal in any column ({cur_rows} rows)"

    if not exempt and prev_text:
        prev_rows = len(_data_rows(prev_text))
        if prev_rows >= 10 and cur_rows < prev_rows:
            ratio = cur_rows / prev_rows
            if ratio < COLLAPSE_ERROR_RATIO:
                return (
                    "error",
                    f"{name}: row count collapsed {prev_rows} -> {cur_rows} "
                    f"({ratio:.0%} of prior, < {COLLAPSE_ERROR_RATIO:.0%})",
                )
            if ratio < COLLAPSE_WARN_RATIO:
                return (
                    "warn",
                    f"{name}: row count dropped {prev_rows} -> {cur_rows} "
                    f"({ratio:.0%} of prior)",
                )
    return "ok", f"{name}: {cur_rows} rows OK"


def _git_show(path: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", "show", f"HEAD:{path}"],
            capture_output=True,
            text=True,
            check=True,
        )
        return out.stdout
    except subprocess.CalledProcessError:
        return None  # new file / not in HEAD — collapse check skipped


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    csvs = sorted(glob.glob(str(repo / "CSVs" / "site_raw" / "*.csv")))
    if not csvs:
        print("::error title=Scrape sanity::No CSVs/site_raw/*.csv found")
        return 1

    errors = 0
    warnings = 0
    for path in csvs:
        name = _source_key(path)
        rel = str(Path(path).relative_to(repo))
        try:
            cur = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            cur = None
        prev = _git_show(rel)
        level, msg = evaluate(name, cur, prev)
        if level == "error":
            errors += 1
            print(f"::error title=Scrape sanity::{msg}")
        elif level == "warn":
            warnings += 1
            print(f"::warning title=Scrape sanity::{msg}")
        else:
            print(msg)

    print(f"\nScrape sanity: {len(csvs)} sources, {errors} error(s), " f"{warnings} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
