#!/usr/bin/env bash
#
# retention_health_probe.sh — run the C1A retention health check on the
# production host and let its exit status stand.
#
# Piped over stdin by .github/workflows/retention-health.yml rather than
# read from the app tree, because the host is checked out at whatever
# revision is DEPLOYED — so the runner's copy is what makes this
# runnable before it ships.  Same reasoning as
# deploy/diagnostics/scoring_snapshot_inventory.sh.
#
# READ-ONLY: it opens files and databases for reading and writes
# nothing.
#
# Inputs (environment):
#   APP_DIR     deployed app tree (default /home/dynasty/trade-calculator)
#   PYTHON_BIN  venv interpreter (falls back to python3 on PATH)
#   REQUIRE     space-separated stream ids that must be ok for this to
#               pass.  EMPTY means report-only: print the table, exit 0.
#               "ALL" requires every stream.
#
# Exit codes: 0 pass (or report-only) · 1 the probe could not run ·
# 2 a required stream is stale, missing or unreadable.

set -Eeuo pipefail

APP_DIR="${APP_DIR:-/home/dynasty/trade-calculator}"
PYTHON_BIN="${PYTHON_BIN:-/home/dynasty/.venvs/trade-calculator/bin/python}"
REQUIRE="${REQUIRE:-}"

log() { printf '[retention-health] %s\n' "$*"; }

cd "${APP_DIR}" || {
    log "ERROR: app dir not found: ${APP_DIR}"
    exit 1
}

[[ -x "${PYTHON_BIN}" ]] || PYTHON_BIN="$(command -v python3 || true)"
if [[ ! -x "${PYTHON_BIN}" ]]; then
    log "ERROR: no usable python interpreter"
    exit 1
fi

if [[ ! -f scripts/retention_health.py ]]; then
    # The deployed revision predates the checker.  Say so plainly rather
    # than exiting 0 — "the check is not there yet" and "the check
    # passed" must never look the same.
    log "ERROR: scripts/retention_health.py absent on the deployed revision"
    exit 1
fi

if [[ "${REQUIRE}" == "ALL" ]]; then
    log "requiring every stream"
    exec "${PYTHON_BIN}" scripts/retention_health.py
fi

# Word-splitting is intended: REQUIRE is a space-separated id list, and
# an empty one must collapse to a bare `--require` (report-only).
# shellcheck disable=SC2086
log "requiring: ${REQUIRE:-<none — report only>}"
exec "${PYTHON_BIN}" scripts/retention_health.py --require ${REQUIRE}
