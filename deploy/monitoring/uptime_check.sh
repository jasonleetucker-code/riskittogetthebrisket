#!/usr/bin/env bash
#
# uptime_check.sh — lightweight external-path uptime probe.
#
# Checks the PUBLIC endpoints (through nginx + TLS, i.e. the same path
# a user takes) plus the local backend port, logs one line per run, and
# optionally notifies on STATE CHANGES (up→down, down→up) so a sustained
# outage produces one alert, not one per probe.
#
# Fired every 5 minutes by riskit-uptime.timer (or from cron:
#   */5 * * * * /home/dynasty/trade-calculator/deploy/monitoring/uptime_check.sh
# ).
#
# NOTE: running on the VPS itself, this catches nginx/TLS/backend/
# frontend failures but NOT a network partition or a dead box — true
# external monitoring needs a second vantage point (documented in
# deploy/monitoring/README.md; no third-party service is wired in).
#
# Env overrides (drop-in on riskit-uptime.service, or cron env):
#   SITE_URL            default https://chaseupside.com
#   CHECK_LOCAL         default true   (also probe 127.0.0.1:8000 directly)
#   LOG_FILE            default /var/log/riskit-uptime.log
#                        (falls back to stdout if unwritable)
#   STATE_FILE          default /var/tmp/riskit-uptime.state
#   CURL_TIMEOUT        default 20 (seconds per probe)
#   NOTIFY_WEBHOOK_URL  default unset — OPTIONAL operator-provided URL
#                        that accepts a POST with a text body (ntfy topic,
#                        Slack/Discord webhook wrapper, etc.).  Unset =
#                        log-only, nothing external is contacted.
#   NOTIFY_CMD          default unset — alternative to the webhook: a
#                        command that receives the message on stdin
#                        (e.g. "mail -s riskit-alert ops@example.com").
#
# Exit code: 0 all checks passed, 1 otherwise.

set -Eeuo pipefail

SITE_URL="${SITE_URL:-https://chaseupside.com}"
CHECK_LOCAL="${CHECK_LOCAL:-true}"
LOG_FILE="${LOG_FILE:-/var/log/riskit-uptime.log}"
STATE_FILE="${STATE_FILE:-/var/tmp/riskit-uptime.state}"
CURL_TIMEOUT="${CURL_TIMEOUT:-20}"
NOTIFY_WEBHOOK_URL="${NOTIFY_WEBHOOK_URL:-}"
NOTIFY_CMD="${NOTIFY_CMD:-}"

NOW="$(date -u +%FT%TZ)"
RESULTS=()
FAILED=0

logline() {
    local line="$1"
    if [[ -w "${LOG_FILE}" ]] || { [[ ! -e "${LOG_FILE}" ]] && touch "${LOG_FILE}" 2>/dev/null; }; then
        printf '%s\n' "${line}" >> "${LOG_FILE}"
    else
        printf '%s\n' "${line}"
    fi
}

# probe <label> <url>  — records "label=CODE/SECONDS" and tracks failure.
# Exactly ONE curl per endpoint: -w output is emitted even when curl
# exits non-zero (000/0.000 on connection failure, the real HTTP code
# on -f HTTP errors), and the `out=$(...)` assignment keeps that stdout
# regardless of exit status.  A second "get the code" probe would
# double the worst-case runtime — with three hung endpoints that blew
# past the unit's TimeoutStartSec and systemd killed the run before it
# could record DOWN.  Budget: 3 probes x CURL_TIMEOUT(20s) = 60s worst
# case, inside riskit-uptime.service's TimeoutStartSec=90 with margin.
# If you raise CURL_TIMEOUT, keep 3 x CURL_TIMEOUT + 10s <= TimeoutStartSec.
probe() {
    local label="$1" url="$2"
    local out code secs rc=0
    out="$(curl -fsS -o /dev/null --max-time "${CURL_TIMEOUT}" \
               -w '%{http_code}/%{time_total}' "${url}" 2>/dev/null)" || rc=$?
    code="${out%%/*}"
    secs="${out##*/}"
    if (( rc == 0 )); then
        RESULTS+=("${label}=ok(${code},${secs}s)")
    else
        RESULTS+=("${label}=FAIL(${code:-000})")
        FAILED=1
    fi
}

probe "public-health"   "${SITE_URL}/api/health"
probe "public-frontend" "${SITE_URL}/"
if [[ "${CHECK_LOCAL}" == "true" ]]; then
    probe "local-backend" "http://127.0.0.1:8000/api/health"
fi

STATUS="UP"
(( FAILED == 0 )) || STATUS="DOWN"
LINE="${NOW} ${STATUS} ${RESULTS[*]}"
logline "${LINE}"

# ── State-change notification (optional, operator-configured) ────────
PREV="$(cat "${STATE_FILE}" 2>/dev/null || echo UP)"
printf '%s\n' "${STATUS}" > "${STATE_FILE}" 2>/dev/null || true

notify() {
    local msg="$1"
    if [[ -n "${NOTIFY_WEBHOOK_URL}" ]]; then
        curl -fsS --max-time 10 -X POST -d "${msg}" "${NOTIFY_WEBHOOK_URL}" >/dev/null 2>&1 \
            || logline "${NOW} WARN notify-webhook failed"
    fi
    if [[ -n "${NOTIFY_CMD}" ]]; then
        printf '%s\n' "${msg}" | ${NOTIFY_CMD} >/dev/null 2>&1 \
            || logline "${NOW} WARN notify-cmd failed"
    fi
}

if [[ "${STATUS}" != "${PREV}" ]]; then
    notify "[riskit-uptime] ${PREV} -> ${STATUS} at ${NOW}: ${RESULTS[*]}"
fi

exit "${FAILED}"
