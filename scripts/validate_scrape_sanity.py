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
    "ktcCrowdSfTep": 400,
    "ktcTradesSfTep": 100,
    "ktcCrowdTradesSfTep": 400,
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

# Audit-only SIDECARS: files that live in ``CSVs/site_raw/`` beside a source
# board but are NOT a source — no adapter reads them and they are never a model
# input.  The row floor and the collapse ratio exist to stop a degraded SOURCE
# board voting; neither question applies to a sidecar, so they do not block on
# one.  The numeric-signal check still applies (rows present but every value
# empty/0 is a broken write whatever the file is for), and an empty sidecar or
# a drop is still REPORTED as a non-blocking warning so it stays visible.
#
# ``dlfValuesSfTepPicks`` — the pick rows of DLF's Trade Analyzer Values page,
# written by ``scripts/fetch_dlf.py`` (``picks_out``) "for the pick audit —
# never a model input" (``scripts/source_inventory.py::
# KNOWN_NON_VOTING_REASONS``).  Two measured facts make the floor wrong here:
#
#   * header-only is the HONEST state when DLF publishes no pick rows.  On
#     2026-09-30 18:27Z the page went from 413 assets (323 valued players + 60
#     ``2026 R.SS`` slot picks) to 353 assets (the same 323 players, 0 picks) —
#     the vendor dropped its completed 2026 class; the player tables parsed
#     identically, so this is not parser drift.  Missing is the absence of
#     rows, never zero values.
#   * it is produced by the prod DLF timer (``deploy/dlf_fetch_and_push.sh``),
#     which pushes it straight to ``main``.  This pre-commit gate therefore
#     cannot keep it out of ``main`` — failing on it only blocked the 29 OTHER
#     sources' commit and the Hill dispatch, every run, from 2026-09-30.
#
# The parent board ``dlfValuesSfTep`` keeps every check.
AUDIT_SIDECARS = {
    "dlfValuesSfTepPicks",
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

    if name in AUDIT_SIDECARS:
        if cur_rows > 0 and not _has_any_numeric_signal(cur_text):
            return "error", f"{name}: no numeric signal in any column ({cur_rows} rows)"
        # Empty warns on EVERY run, not only on the run that emptied it: the
        # box pushes this file straight to main, so in scheduled-refresh the
        # working tree equals HEAD and a cur-vs-prev drop is never observable
        # here.  Empty must never print as "OK".
        prev_rows = len(_data_rows(prev_text)) if prev_text else 0
        if cur_rows == 0:
            dropped = f" (dropped {prev_rows} -> 0)" if prev_rows else ""
            return (
                "warn",
                f"{name}: audit-only sidecar has 0 data rows{dropped} — the vendor "
                "published none (not a source; non-blocking)",
            )
        if cur_rows < prev_rows:
            return (
                "warn",
                f"{name}: audit-only sidecar dropped {prev_rows} -> {cur_rows} rows "
                "(not a source; not gated — the vendor published fewer rows)",
            )
        return "ok", f"{name}: {cur_rows} rows OK (audit-only sidecar, not a source)"

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
