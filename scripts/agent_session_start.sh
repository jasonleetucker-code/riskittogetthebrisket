#!/usr/bin/env bash
# Model-neutral session-start health/router for any coding agent.
# Claude's .claude/health-check.sh is only an adapter to this file.

set -euo pipefail
cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"

echo "=== AGENT SESSION START ==="
echo "  Universal entrypoint: AI_INSTRUCTIONS.md"
echo "  Agent OS: docs/AGENT_OPERATING_SYSTEM.md"
python scripts/agent_os_receipt.py || true
echo "  Product authority: docs/EXECUTION_PLAN.md + active owner-authorized contract"
echo "  Coordination: ASSISTANT_COORDINATION.md + docs/WORK_CLAIMS.md"
echo "  Technical runbook: CLAUDE.md (legacy filename; universal to all models)"

LAUNCH_CONTRACT="docs/season-launch/WEEK_1_LAUNCH_CONTRACT.md"
if [[ -f "$LAUNCH_CONTRACT" ]]; then
  LAUNCH_TOTAL=$(grep -cE '^\| W1-[0-9][0-9] .*\| (VERIFIED|IMPLEMENTED_UNVERIFIED|IN PROGRESS|NOT STARTED|BLOCKED) \|$' "$LAUNCH_CONTRACT" || true)
  LAUNCH_VERIFIED=$(grep -cE '^\| W1-[0-9][0-9] .*\| VERIFIED \|$' "$LAUNCH_CONTRACT" || true)
  if [[ "$LAUNCH_TOTAL" =~ ^[0-9]+$ ]] && [[ "$LAUNCH_VERIFIED" =~ ^[0-9]+$ ]] && (( LAUNCH_TOTAL > 0 )); then
    echo "  Week 1 contract: $LAUNCH_VERIFIED/$LAUNCH_TOTAL literal VERIFIED"
  else
    echo "  Week 1 contract: UNKNOWN tally"
  fi
fi

echo ""
echo "--- Test Collection ---"
COLLECT_OUT=$(python -m pytest tests/ -q --co 2>&1) && COLLECT_RC=0 || COLLECT_RC=$?
echo "$COLLECT_OUT" | tail -1
if (( COLLECT_RC != 0 )); then
  echo "ACTION NEEDED: pytest collection failed (rc $COLLECT_RC)"
  echo "$COLLECT_OUT" | grep -iE "error|no module named|cannot import" | head -5 || true
fi

echo ""
echo "--- Git Status ---"
BRANCH=$(git branch --show-current 2>/dev/null || echo "unknown")
echo "  Branch: $BRANCH"
DIRTY=$(git status --porcelain --untracked-files=no 2>/dev/null | wc -l)
if (( DIRTY > 0 )); then
  echo "  WARNING: $DIRTY uncommitted tracked changes"
fi

echo ""
echo "--- Syntax Smoke ---"
python -m py_compile "Dynasty Scraper.py" server.py
echo "  Python entrypoints: OK"
echo "=== AGENT SESSION START COMPLETE ==="
