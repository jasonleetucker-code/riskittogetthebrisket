#!/usr/bin/env bash
# C10-CLOSE-07 / V1-126 — the deterministic final V1 regression command.
#
# WHAT THIS IS. A pure COMPOSITION of gates that already exist and already
# run somewhere in this repo's CI — no new test logic, no new gate. It
# exists because no single existing command runs all of them together:
# release-candidate.yml is the closest match but deliberately does NOT
# include Playwright/E2E (that lives in the separately-triggered,
# path-filtered e2e.yml), while C_SERIES_REPLAN_AND_COMPLETION_CONTRACT.md
# section 13.7 explicitly requires it: "Run all blocking backend/frontend
# /contract/lint/audit/E2E gates on the final exact head."
#
# WHAT THIS IS NOT. Running this script is NOT itself V1-126's closure, and
# it carries no numerator claim. Per the owner's own instruction: "Do not
# attempt final V1 regression closure early... define the deterministic
# final command/matrix that will be run when the denominator is otherwise
# complete. No numerator claim yet." This script is that definition. It is
# meant to be run once V1-121 through V1-125 (and the rest of the C10
# closure rows) are otherwise closed, by whoever is driving that closure —
# not executed speculatively by whichever session happens to write it.
#
# EXIT CODE. Non-zero on the first blocking failure (set -e). The advisory
# source-health step is deliberately NOT gating, matching the same
# structural/advisory split release-candidate.yml already uses (see
# CLAUDE.md's "CI has two lanes" section) — its output is recorded, not
# enforced.
#
# THE ONE THING THIS SCRIPT ADDS THAT release-candidate.yml DOES NOT HAVE:
# the full Playwright suite, run UNCONDITIONALLY rather than relying on
# e2e.yml's normal path-filtered trigger. A "final" regression that skips
# E2E because the diff happens not to touch a path-filter pattern is not
# what section 13.7 asks for.
#
# WEBKIT DECISION, made explicit rather than left implicit: this script
# includes the two WebKit-only Playwright projects (mobile-390, mobile-430)
# that CI never runs (see docs/ops/C10_CLOSE_03_BROWSER_WORKFLOW_MATRIX.md's
# viewport table). If WebKit/Safari coverage is out of V1 scope, that is an
# owner decision to make explicitly — comment out the WEBKIT_PROJECTS line
# below and say why, rather than silently dropping the coverage.

set -Eeuo pipefail

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

say() { printf '\n[final-v1-regression] === %s ===\n' "$*"; }

RECORD_DIR="${FINAL_REGRESSION_RECORD_DIR:-/tmp/final-v1-regression}"
mkdir -p "${RECORD_DIR}"

say "1/12 Python format + lint (ruff)"
python -m ruff format --check .
python -m ruff check .

say "2/12 Governance + planning gates"
python scripts/check_planning_integrity.py
python scripts/check_product_plan_governance.py
python scripts/check_decision_coercions.py
python scripts/audit_status.py

say "3/12 Backend unit tests (pytest, hard gate)"
python -m pytest tests/ -x -q --tb=short -m "not livedata"

say "4/12 CI release-gate classification (V1-121)"
python -m pytest tests/deploy/test_release_gate_classification.py -q

say "5/12 API data contract check (FULL lane -- not structural-only, this is the final gate not the PR gate)"
python scripts/validate_api_contract.py --repo . --lane full

say "6/12 Source health (advisory -- recorded, not gating)"
python scripts/check_source_health.py --repo . 2>&1 | tee "${RECORD_DIR}/source-health.log" || true

say "7/12 Dependency graph + environment preflight"
python -m pip check
python scripts/check_env.py

say "8/12 Python syntax + runtime import gates"
python -m py_compile server.py "Dynasty Scraper.py"
python -m py_compile src/api/data_contract.py
python - <<'PY'
import fastapi  # noqa: F401
import uvicorn  # noqa: F401
import requests  # noqa: F401
PY

say "9/12 Deploy script syntax gate"
for f in deploy/*.sh; do
  [ -e "$f" ] || continue
  bash -n "$f"
done

say "10/12 Frontend unit tests (vitest) + build + bundle budget"
(
  cd frontend
  if [[ -f package-lock.json ]]; then
    npm ci --no-audit --no-fund
  else
    npm install --no-audit --no-fund
  fi
  npm test
  npm run build
)

say "11/12 Full Playwright suite -- ALL projects, unconditionally (not the normal path-filtered e2e.yml trigger)"
npm run regression:preflight
WEBKIT_PROJECTS="--project=mobile-390 --project=mobile-430"
npx playwright test -c tests/e2e/playwright.config.js \
  --project=desktop-1366 --project=mobile-chromium ${WEBKIT_PROJECTS}

say "12/12 Duplicate-owner census (V1-125) -- recorded, not gating (open rows are real, out-of-scope work, not a regression)"
python -c "
import sys
sys.path.insert(0, 'scripts')
from check_planning_integrity import check_duplicate_owners, parse_manifest, read, MANIFEST, Failures
f = Failures()
check_duplicate_owners(f, parse_manifest(read(MANIFEST)))
" 2>&1 | tee "${RECORD_DIR}/duplicate-owners.log" || true

say "ALL GATES RAN. This is a command definition, not a numerator claim -- see the module docstring."
