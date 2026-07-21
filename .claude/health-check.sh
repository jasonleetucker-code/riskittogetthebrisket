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
echo ""
echo "--- Data Freshness ---"
for csv in exports/latest/site_raw/ktc.csv exports/latest/site_raw/idpTradeCalc.csv; do
  if [[ -f "$csv" ]]; then
    AGE_HOURS=$(( ($(date +%s) - $(stat --format=%Y "$csv" 2>/dev/null || stat -f %m "$csv" 2>/dev/null)) / 3600 ))
    LINES=$(wc -l < "$csv")
    echo "  $(basename "$csv"): ${LINES} lines, ${AGE_HOURS}h old"
    if (( AGE_HOURS > 12 )); then
      echo "  WARNING: Stale (>12h). Check scheduled-refresh workflow."
    fi
  else
    echo "  $(basename "$csv"): MISSING"
  fi
done

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
