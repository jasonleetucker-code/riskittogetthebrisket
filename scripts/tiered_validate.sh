#!/usr/bin/env bash
# Canonical local entrypoint for the tiered fast-development workflow.
#
# See docs/AGENT_OPERATING_SYSTEM.md §3 "Tiered validation workflow — L0
# through L3" for the full policy this implements. In short:
#
#   L0 — seconds.    Formatting, linting, syntax, changed-file imports.
#   L1 — ~1-3 min.   Subsystem-targeted tests for whatever you touched.
#   L2 — full suite. The same hard gates pr-validation.yml runs, run
#                    locally before you open the one integration PR for
#                    this development phase.
#
# L3 (production-candidate validation) is NOT run from here — it is
# release-candidate.yml + deploy.yml, deliberately unchanged and strict.
#
# Usage:
#   bash scripts/tiered_validate.sh l0
#   bash scripts/tiered_validate.sh l1
#   bash scripts/tiered_validate.sh l2
#   bash scripts/tiered_validate.sh l0 l1        # run both in sequence
#
# Every level is additive to the one below it: running l1 does not skip
# l0's checks; running l2 does not skip l0/l1's. Run l0 continuously while
# editing, l1 after a logical chunk, l2 once before opening the PR for the
# integration checkpoint.
#
# This script never decides less than the truth: like
# scripts/ci_change_scope.py (which it calls to decide L1 scope), any
# detection failure widens what gets run rather than narrowing it.

set -Eeuo pipefail
cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"

BASE_REF="${TIERED_VALIDATE_BASE_REF:-origin/main}"

log() { printf '\n\033[1m== %s ==\033[0m\n' "$1"; }

run_l0() {
  log "L0 — formatting, linting, syntax (seconds)"
  bash scripts/format_python_changes.sh

  # Changed-file Python syntax + import-shape gate. ruff check/format above
  # already covers style; this catches import errors quickly on just the
  # files that changed, without paying for the full backend test suite.
  mapfile -t PY_FILES < <(python scripts/ci_change_scope.py --base "$BASE_REF" --paths-only | grep -E '\.py$' || true)
  if ((${#PY_FILES[@]} > 0)); then
    echo "Syntax-checking ${#PY_FILES[@]} changed Python file(s):"
    printf '  %s\n' "${PY_FILES[@]}"
    python -m py_compile "${PY_FILES[@]}"
  fi

  mapfile -t FRONTEND_FILES < <(python scripts/ci_change_scope.py --base "$BASE_REF" --paths-only | grep -E '^frontend/.*\.(js|jsx|ts|tsx)$' || true)
  if ((${#FRONTEND_FILES[@]} > 0)) && [[ -d frontend/node_modules ]]; then
    echo "Frontend files changed (${#FRONTEND_FILES[@]}) — run 'npm run build:nocheck' in frontend/ for a full L1 check."
  fi

  echo "L0: GREEN"
}

run_l1() {
  log "L1 — subsystem-targeted tests (~1-3 min)"
  local scope_out
  scope_out="$(python scripts/ci_change_scope.py --base "$BASE_REF")"
  echo "$scope_out"

  mapfile -t CHANGED < <(python scripts/ci_change_scope.py --base "$BASE_REF" --paths-only)

  # Map changed paths onto the tests/<subsystem> directory of the same
  # name, plus a small set of named subsystems from CLAUDE.md's L1 table
  # (Game Day, rankings/valuation, trade analyzer, Sleeper ingestion,
  # database/schema) that don't line up 1:1 with a single src/ directory.
  declare -A TEST_DIRS=()
  add_dir() { [[ -d "tests/$1" ]] && TEST_DIRS["$1"]=1; }

  for path in "${CHANGED[@]}"; do
    case "$path" in
      src/*)
        subsystem="${path#src/}"
        subsystem="${subsystem%%/*}"
        add_dir "$subsystem"
        ;;
      tests/*)
        subsystem="${path#tests/}"
        subsystem="${subsystem%%/*}"
        add_dir "$subsystem"
        ;;
    esac
    case "$path" in
      *game_day*|*playoff*|*GAME_DAY_PROBABILITY*) add_dir "game_day" ;;
      src/canonical/*|src/api/data_contract.py) add_dir "canonical"; add_dir "api" ;;
      src/bdvm/*) add_dir "bdvm" ;;
      src/trade/*) add_dir "trade" ;;
      "Dynasty Scraper.py"|src/adapters/*) add_dir "adapters" ;;
      src/identity/*|*migrations*) add_dir "identity" ;;
      src/history/*) add_dir "history" ;;
      src/sharp/*) add_dir "sharp" ;;
      src/league_intel/*) add_dir "league_intel" ;;
      src/ros/*) add_dir "ros" ;;
      src/draft/*) add_dir "draft" ;;
      src/roster_intel/*) add_dir "roster_intel" ;;
      src/picks/*) add_dir "picks" ;;
      src/public_league/*) add_dir "public_league" ;;
      src/steward/*) add_dir "steward" ;;
      src/scoring/*) add_dir "scoring" ;;
      src/model_registry/*) add_dir "model_registry" ;;
    esac
  done

  if ((${#TEST_DIRS[@]} > 0)); then
    local dirs=()
    for d in "${!TEST_DIRS[@]}"; do dirs+=("tests/$d"); done
    echo "Running targeted pytest for: ${dirs[*]}"
    python -m pytest "${dirs[@]}" -q --tb=short -m "not livedata"
  else
    echo "No backend subsystem test directory matched the diff; skipping targeted pytest."
  fi

  if printf '%s\n' "${CHANGED[@]}" | grep -q '^frontend/'; then
    echo "Frontend files changed — running vitest."
    (cd frontend && npm test)
  fi

  echo "L1: GREEN"
}

run_l2() {
  log "L2 — full local dry-run of the integration-PR gates"
  echo "This mirrors .github/workflows/pr-validation.yml. It is the check"
  echo "to run once before opening the single integration PR for this"
  echo "development phase — not after every small edit."

  python -m pip check || true
  python scripts/check_env.py
  python -m py_compile server.py "Dynasty Scraper.py" src/api/data_contract.py
  python -m ruff format --check .
  python -m ruff check .
  python scripts/check_decision_coercions.py
  python scripts/audit_status.py
  python scripts/check_planning_integrity.py
  python scripts/check_product_plan_governance.py

  ALLOW_DEFAULT_LOGIN_DEV=1 python - <<'PY'
import fastapi
import uvicorn
import requests
from playwright.async_api import async_playwright
import server
print("Runtime import gate passed.")
PY

  ALLOW_DEFAULT_LOGIN_DEV=1 UPTIME_CHECK_ENABLED=0 python -m pytest tests/ -x -q --tb=short -m "not livedata"
  python scripts/validate_api_contract.py --repo . --lane structural

  if [[ -d frontend/node_modules ]]; then
    (cd frontend && npm test && npm run build:nocheck && npm run check:bundles)
  else
    echo "frontend/node_modules missing — run 'npm ci' in frontend/ first, then re-run L2."
  fi

  echo "L2: GREEN — safe to open/advance the integration PR."
}

if (($# == 0)); then
  echo "Usage: $0 <l0|l1|l2> [l0|l1|l2 ...]" >&2
  exit 2
fi

for level in "$@"; do
  case "$level" in
    l0) run_l0 ;;
    l1) run_l1 ;;
    l2) run_l2 ;;
    *)
      echo "Unknown level: $level (expected l0, l1, or l2)" >&2
      exit 2
      ;;
  esac
done
