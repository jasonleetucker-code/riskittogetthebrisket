#!/usr/bin/env bash
#
# dynasty-healthcheck.sh — local watchdog for the FastAPI backend.
#
# Fired every minute by dynasty-healthcheck.timer.  Curls
# http://127.0.0.1:8000/api/health; after HEALTH_FAIL_THRESHOLD
# CONSECUTIVE failures it runs `systemctl reset-failed` + `systemctl
# restart` on the backend service and clears the counter.  A single
# blip (e.g. the service restarting on its own) never triggers a
# restart — only a sustained outage does.
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
#   HEALTH_FAIL_THRESHOLD  default 3   (consecutive failures)
#   HEALTH_CURL_TIMEOUT    default 25  (seconds; /api/health is cheap,
#                          but stays generous so a busy event loop
#                          during a scrape isn't misread as down)
#   HEALTH_STATE_DIR       default /run/dynasty-healthcheck

set -Eeuo pipefail

HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8000/api/health}"
HEALTH_SERVICE="${HEALTH_SERVICE:-dynasty}"
HEALTH_FAIL_THRESHOLD="${HEALTH_FAIL_THRESHOLD:-3}"
HEALTH_CURL_TIMEOUT="${HEALTH_CURL_TIMEOUT:-25}"
HEALTH_STATE_DIR="${HEALTH_STATE_DIR:-${RUNTIME_DIRECTORY:-/run/dynasty-healthcheck}}"

FAIL_FILE="${HEALTH_STATE_DIR}/consecutive-failures"

log() { printf '[healthcheck] %s\n' "$*"; }

mkdir -p "${HEALTH_STATE_DIR}"

read_failures() {
    local n
    n="$(cat "${FAIL_FILE}" 2>/dev/null || echo 0)"
    [[ "${n}" =~ ^[0-9]+$ ]] || n=0
    printf '%s' "${n}"
}

if curl -fsS --max-time "${HEALTH_CURL_TIMEOUT}" -o /dev/null "${HEALTH_URL}"; then
    prev="$(read_failures)"
    if [[ "${prev}" != "0" ]]; then
        log "recovered: ${HEALTH_URL} healthy again after ${prev} failure(s)"
    fi
    printf '0\n' > "${FAIL_FILE}"
    exit 0
fi

failures="$(( $(read_failures) + 1 ))"
printf '%s\n' "${failures}" > "${FAIL_FILE}"
log "FAIL ${failures}/${HEALTH_FAIL_THRESHOLD}: ${HEALTH_URL} not responding"

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
