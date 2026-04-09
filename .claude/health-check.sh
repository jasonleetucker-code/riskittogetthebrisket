#!/usr/bin/env bash
# Session-start health check for Risk It To Get The Brisket
# Runs automatically when a Claude Code session starts in this repo.
# Reports issues so Claude can fix them immediately.

set -euo pipefail
cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"

echo "=== SITE HEALTH CHECK ==="

# 1. Test suite
echo ""
echo "--- Tests ---"
TEST_OUT=$(python -m pytest tests/ -q --tb=no 2>&1 | tail -1)
echo "$TEST_OUT"
if echo "$TEST_OUT" | grep -q "failed"; then
  echo "ACTION NEEDED: Fix failing tests"
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
