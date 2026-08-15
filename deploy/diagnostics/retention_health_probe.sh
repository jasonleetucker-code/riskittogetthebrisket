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
# ── THE SCHEDULED WATCHDOG MUST ACTUALLY WATCH ──────────────────────
#
# The rule that a SCHEDULED run requires the whole tranche lives HERE,
# in a script, and not in a GitHub Actions expression.  That placement
# is deliberate and it is the fix for a real defect: the first version
# resolved REQUIRE from ``inputs.require``, which is empty on a
# ``schedule`` event, so the nightly watchdog ran in report-only mode
# and stayed green while every retention stream was dead.  A watchdog
# that cannot fail is not a watchdog — it is the same ships-then-stops-
# then-stays-quiet silence the C1-RET tranche exists to repair, wearing
# a green tick.
#
# In a shell script the rule is executable and therefore testable
# end-to-end (tests/retention/test_watchdog_semantics.py runs this file
# against a temp data dir and asserts the exit codes).  A YAML
# expression could only ever be checked by a regex.
#
# Inputs (environment):
#   APP_DIR     deployed app tree (default /home/dynasty/trade-calculator)
#   PYTHON_BIN  venv interpreter (falls back to python3 on PATH)
#   DATA_DIR    optional override for the probed data directory
#   EVENT_NAME  the GitHub event that triggered this run.  "schedule"
#               FORCES REQUIRE=ALL and cannot be talked out of it.
#   REQUIRE     manual-dispatch only.  Space-separated stream ids that
#               must be ok; "ALL" requires every stream; EMPTY means
#               report-only (print the table, exit 0).
#
# Exit codes: 0 pass (or manual report-only) · 1 the probe could not run
# · 2 a required stream is stale, missing or unreadable.

set -Eeuo pipefail

APP_DIR="${APP_DIR:-/home/dynasty/trade-calculator}"
PYTHON_BIN="${PYTHON_BIN:-/home/dynasty/.venvs/trade-calculator/bin/python}"
DATA_DIR="${DATA_DIR:-}"
EVENT_NAME="${EVENT_NAME:-}"
REQUIRE="${REQUIRE:-}"

log() { printf '[retention-health] %s\n' "$*"; }

# A scheduled run requires the COMPLETE authorized tranche, always.
# Not "whatever the caller passed", not "whatever is provisioned so far"
# — a scheduled failure while production has not yet produced an
# artifact is truthful and useful, and the job turns green when the
# retention system actually becomes healthy.
if [[ "${EVENT_NAME}" == "schedule" ]]; then
    if [[ -n "${REQUIRE}" && "${REQUIRE}" != "ALL" ]]; then
        log "scheduled run: ignoring REQUIRE='${REQUIRE}' — the watchdog always requires every stream"
    fi
    REQUIRE="ALL"
fi

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

ARGS=()
[[ -n "${DATA_DIR}" ]] && ARGS+=(--data-dir "${DATA_DIR}")

if [[ "${REQUIRE}" == "ALL" ]]; then
    log "requiring every retention stream (event=${EVENT_NAME:-<none>})"
    exec "${PYTHON_BIN}" scripts/retention_health.py "${ARGS[@]}"
fi

# Word-splitting is intended: REQUIRE is a space-separated id list, and
# an empty one must collapse to a bare `--require` (report-only).
# shellcheck disable=SC2086
log "requiring: ${REQUIRE:-<none — report only>} (event=${EVENT_NAME:-<none>})"
exec "${PYTHON_BIN}" scripts/retention_health.py "${ARGS[@]}" --require ${REQUIRE}
