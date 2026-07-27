#!/usr/bin/env bash
# Session-start health check for Risk It To Get The Brisket
# Runs automatically when a Claude Code session starts in this repo.
# Reports issues so Claude can fix them immediately.

set -euo pipefail
cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"

echo "=== SITE HEALTH CHECK ==="

# 1. Test collection (fast: ~1s)
# A session-start hook must be quick, so we run collection-only rather than the
# full suite. Collection catches the failure class worth catching at startup:
# missing dependencies and import errors (e.g. a missing httpx breaking
# TestClient). The full suite runs in CI/Linux, where it belongs — running it
# here would take ~10min and, on Windows, throw environment-only false
# positives (symlink privilege, /dev/null, cp1252 encoding).
# The exit code is isolated so `set -e`/`pipefail` can't abort the health check.
echo ""
echo "--- Test Collection ---"
COLLECT_OUT=$(python -m pytest tests/ -q --co 2>&1) && COLLECT_RC=0 || COLLECT_RC=$?
echo "$COLLECT_OUT" | tail -1
if (( COLLECT_RC != 0 )); then
  echo "ACTION NEEDED: pytest collection failed (rc $COLLECT_RC) — likely a missing dependency or import error:"
  echo "$COLLECT_OUT" | grep -iE "error|no module named|cannot import" | head -5
fi

# 2. Scrape data freshness
#
# This check used to read filesystem mtime, which is wrong here and was wrong
# in BOTH directions. Remote sessions clone the repo fresh, so mtime is
# *checkout* time and carries no information about when data was fetched:
#
#   - A fresh clone stamps every file with "now", so every source reads 0h and
#     the warning CANNOT FIRE — even if the pipeline had been dead for months.
#   - A branch switch rewrites only the files that differ, so untouched files
#     keep an older mtime and read as stale when they are not. Measured
#     2026-07-27: idpTradeCalc.csv reported 49h against a real content age of
#     131h (82h under-reported) while ktc.csv reported 0h against 3h.
#
# So it simultaneously missed real outages and invented fake ones — see
# docs/ORCHESTRATION.md §6.15.
#
# What survives cloning is the commit history. The question the operator
# actually wants answered is "is the scrape pipeline alive?", and
# config/source_staleness.json is explicit that the alerting criterion is
# FETCH SUCCESS, not vendor publication. The 2h cron commits whenever a fetch
# changes anything, so the age of the last site_raw commit measures exactly
# that. Per-source content age is reported separately and deliberately does
# NOT warn: idpTradeCalc legitimately goes 5-20 days between updates in the
# offseason (measured over four months of history), so warning on it would
# fire permanently and train the reader to ignore this whole section.
#
# Known limitation, stated rather than hidden: a refresh that fetches
# successfully but yields byte-identical output for every source produces no
# commit and would read as an outage. In practice ktc.csv (500 rows of a live
# market) changes on essentially every run, so a gap here is a real signal.
echo ""
echo "--- Data Freshness ---"
STALE_HOURS=$(python -c "import json;print(json.load(open('config/source_staleness.json'))['thresholds'].get('ktc',24))" 2>/dev/null || echo 24)
NOW=$(date +%s)

# Guard the guard: without commit history every age below reads as 0, which is
# the exact false-clean the mtime version produced. Say so instead.
if [[ "$(git rev-parse --is-shallow-repository 2>/dev/null)" == "true" ]]; then
  echo "  UNKNOWN: shallow clone — no commit history, cannot measure data freshness."
  echo "  (Deepen with 'git fetch --unshallow' if this check matters here.)"
else
  LAST_REFRESH=$(git log -1 --format=%ct -- exports/latest/site_raw/ 2>/dev/null || echo "")
  if [[ -z "$LAST_REFRESH" ]]; then
    echo "  UNKNOWN: no commits touch exports/latest/site_raw/ — cannot measure."
  else
    PIPELINE_AGE=$(( (NOW - LAST_REFRESH) / 3600 ))
    echo "  Pipeline: last refresh commit ${PIPELINE_AGE}h ago (threshold ${STALE_HOURS}h)"
    if (( PIPELINE_AGE > STALE_HOURS )); then
      echo "  WARNING: no data refresh in ${PIPELINE_AGE}h. Check scheduled-refresh workflow."
    fi
  fi

  for csv in exports/latest/site_raw/ktc.csv exports/latest/site_raw/idpTradeCalc.csv; do
    if [[ -f "$csv" ]]; then
      LINES=$(wc -l < "$csv")
      CHANGED=$(git log -1 --format=%ct -- "$csv" 2>/dev/null || echo "")
      if [[ -n "$CHANGED" ]]; then
        echo "  $(basename "$csv"): ${LINES} lines, content last changed $(( (NOW - CHANGED) / 86400 ))d ago"
      else
        echo "  $(basename "$csv"): ${LINES} lines, no commit history"
      fi
    else
      echo "  $(basename "$csv"): MISSING"
    fi
  done
fi

# 3. Git status
echo ""
echo "--- Git Status ---"
BRANCH=$(git branch --show-current 2>/dev/null || echo "unknown")
echo "  Branch: $BRANCH"
DIRTY=$(git status --porcelain --untracked-files=no 2>/dev/null | wc -l)
if (( DIRTY > 0 )); then
  echo "  WARNING: $DIRTY uncommitted tracked changes"
fi

# 4. Scraper syntax
echo ""
echo "--- Scraper Syntax ---"
if python -m py_compile "Dynasty Scraper.py" 2>/dev/null; then
  echo "  Dynasty Scraper.py: OK"
else
  echo "  Dynasty Scraper.py: SYNTAX ERROR - fix immediately"
fi
if python -m py_compile server.py 2>/dev/null; then
  echo "  server.py: OK"
else
  echo "  server.py: SYNTAX ERROR - fix immediately"
fi

echo ""
echo "=== HEALTH CHECK COMPLETE ==="
