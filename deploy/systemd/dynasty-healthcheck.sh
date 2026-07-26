#!/usr/bin/env bash
#
# dynasty-healthcheck.sh — local LIVENESS watchdog for the FastAPI
# backend.  Liveness and application health are deliberately separate:
#
#   * LIVENESS  — does the process answer HTTP at all?  ANY HTTP
#     response (200, 401, 404, 503, ...) proves the server process is
#     up and serving; only a connection-level failure (refused, timeout,
#     empty reply — curl exit 7/28/52/56/...) counts as down.  We probe
#     127.0.0.1 directly, so no proxy can answer on a dead backend's
#     behalf.
#   * HEALTH    — /api/health deliberately returns HTTP 503 with
#     status "degraded" for stale data, a failed/stalled scrape, or
#     contract validation failure WHILE the process is up and serving
#     cached data (see server.py::get_health).  Restarting on that
#     would bounce a healthy process — and worse, a restart clears the
#     in-memory scrape error and reloads the disk cache with a fresh
#     loadedAt, flipping health green WITHOUT a successful scrape and
#     concealing the ingestion fault.  Degraded 503s are therefore
#     LOG-ONLY (reported on state transitions): report, never restart.
#
# Fired every minute by dynasty-healthcheck.timer.  After
# HEALTH_FAIL_THRESHOLD CONSECUTIVE liveness failures it runs
# `systemctl reset-failed` + `systemctl restart` on the backend service
# and clears the counter.  A single blip (e.g. the service restarting
# on its own) never triggers a restart — only a sustained outage does.
#
# reset-failed matters: the hardened dynasty.service has a
# StartLimitBurst crash-loop brake, and once that trips systemd
# refuses further starts until the failed state is cleared.
#
# State lives in RuntimeDirectory (/run/dynasty-healthcheck), so the
# counter resets on reboot — correct, since a reboot is a fresh start.
#
# Runs as root (it must be able to systemctl restart).  Logs to the
# journal: `journalctl -u dynasty-healthcheck.service`.
#
# Env overrides (set via drop-in on dynasty-healthcheck.service):
#   HEALTH_URL             default http://127.0.0.1:8000/api/health
#   HEALTH_SERVICE         default dynasty
#   HEALTH_FAIL_THRESHOLD  default 3   (consecutive LIVENESS failures)
#   HEALTH_CURL_TIMEOUT    default 25  (seconds; generous so a busy
#                          event loop during a scrape isn't misread
#                          as down)
#   HEALTH_STATE_DIR       default /run/dynasty-healthcheck

set -Eeuo pipefail

HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8000/api/health}"
HEALTH_SERVICE="${HEALTH_SERVICE:-dynasty}"
HEALTH_FAIL_THRESHOLD="${HEALTH_FAIL_THRESHOLD:-3}"
HEALTH_CURL_TIMEOUT="${HEALTH_CURL_TIMEOUT:-25}"
HEALTH_STATE_DIR="${HEALTH_STATE_DIR:-${RUNTIME_DIRECTORY:-/run/dynasty-healthcheck}}"

FAIL_FILE="${HEALTH_STATE_DIR}/consecutive-failures"
DEGRADED_FILE="${HEALTH_STATE_DIR}/degraded"

log() { printf '[healthcheck] %s\n' "$*"; }

mkdir -p "${HEALTH_STATE_DIR}"

read_failures() {
    local n
    n="$(cat "${FAIL_FILE}" 2>/dev/null || echo 0)"
    [[ "${n}" =~ ^[0-9]+$ ]] || n=0
    printf '%s' "${n}"
}

# LIVENESS probe: no -f — any HTTP status is proof of life.  rc != 0
# means curl got no usable HTTP response (connection refused, timeout,
# empty reply, ...) and only that counts as a liveness failure.
rc=0
http_code="$(curl -sS --max-time "${HEALTH_CURL_TIMEOUT}" -o /dev/null \
                 -w '%{http_code}' "${HEALTH_URL}" 2>/dev/null)" || rc=$?

if (( rc == 0 )); then
    # Process is alive.  Reset the liveness counter; surface app-level
    # degradation as log-only, on transitions.
    prev="$(read_failures)"
    if [[ "${prev}" != "0" ]]; then
        log "recovered: ${HEALTH_URL} responding again after ${prev} liveness failure(s)"
    fi
    printf '0\n' > "${FAIL_FILE}"

    if [[ "${http_code}" == "503" ]]; then
        if [[ ! -f "${DEGRADED_FILE}" ]]; then
            log "DEGRADED (log-only): ${HEALTH_URL} returned 503 — the app reports degraded health (stale data / failed or stalled scrape / contract issue) but the process is alive and serving cached data.  NOT restarting: a restart would clear the in-memory scrape error and reload the cache with a fresh loadedAt, masking the ingestion fault.  Investigate via /api/status and journalctl -u ${HEALTH_SERVICE}."
            : > "${DEGRADED_FILE}"
        fi
    elif [[ -f "${DEGRADED_FILE}" ]]; then
        log "degraded state cleared: ${HEALTH_URL} now returns ${http_code}"
        rm -f "${DEGRADED_FILE}"
    fi
    exit 0
fi

failures="$(( $(read_failures) + 1 ))"
printf '%s\n' "${failures}" > "${FAIL_FILE}"
log "LIVENESS FAIL ${failures}/${HEALTH_FAIL_THRESHOLD}: no HTTP response from ${HEALTH_URL} (curl exit ${rc})"

if (( failures < HEALTH_FAIL_THRESHOLD )); then
    exit 0
fi

log "threshold reached — restarting ${HEALTH_SERVICE}.service"
# Clear any tripped StartLimit state first, otherwise restart is a no-op
# on a unit systemd has given up on.
systemctl reset-failed "${HEALTH_SERVICE}.service" 2>/dev/null || true
if systemctl restart "${HEALTH_SERVICE}.service"; then
    log "restart issued for ${HEALTH_SERVICE}.service"
else
    log "ERROR: systemctl restart ${HEALTH_SERVICE}.service failed"
fi
# Reset the counter either way so the next window measures the NEW
# process (and a restart that doesn't help re-triggers after another
# full threshold, not instantly every minute).
printf '0\n' > "${FAIL_FILE}"
