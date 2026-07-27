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
# This read filesystem mtime and called it data freshness. It was wrong in
# BOTH directions, which is how it got caught — see ORCHESTRATION.md §6.15.
# Remote sessions clone the repo fresh, so mtime is *checkout* time:
#
#   - A fresh clone stamps every file "now", so every source reads 0h and the
#     warning CANNOT FIRE even if the pipeline died months ago.
#   - A branch switch rewrites only differing files, so unchanged ones keep an
#     older mtime and read as stale. Measured 2026-07-27: idpTradeCalc.csv
#     reported 49h against a real content age of 131h, ktc.csv 0h against 3h.
#
# It also watched the wrong artifact. `exports/latest/site_raw/` is a raw
# mirror — `preflight.py::_seed_data_cache` copies `dynasty_data_*.json` and
# does NOT copy `site_raw/`, so the pipeline, the E2E suite and production all
# read the JSON. The mirror is written only by full scraper runs (the 2h cron
# handles ktc/ktcSfTep/idpTradeCalc with `stamp_if_present`, not
# `run_fetcher`), so it freezes for days with nothing wrong. §6.12 chased that
# exact false alarm at 03:05 and reached the same place.
#
# So the check reads `scrapeTimestamp` from the contract instead. It is an
# internal content stamp, so unlike mtime or commit dates it survives cloning
# and means the same thing everywhere. Per-source health is reported as
# coverage — how many players actually carry a value — which is what a dead
# source would change, and a line count would not.
echo ""
echo "--- Data Freshness ---"
python .claude/freshness.py 2>/dev/null || echo "  UNKNOWN: freshness probe failed to run."

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
