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
#   STATE_FILE          default $STATE_DIRECTORY/state (systemd StateDirectory=),
#                        else $HOME/.local/state/riskit-uptime/state.  Its
#                        directory must be owned by this user and not group-
#                        or world-writable; otherwise the private default is
#                        used instead (the retry queues sit beside it).
#   NOTIFY_BUDGET       default 15 (seconds of delivery per run, all
#                        channels; keeps a run inside TimeoutStartSec=90)
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
# Everything this script creates (status, queues, lock) is private.
umask 077

SITE_URL="${SITE_URL:-https://chaseupside.com}"
CHECK_LOCAL="${CHECK_LOCAL:-true}"
LOG_FILE="${LOG_FILE:-/var/log/riskit-uptime.log}"
if [[ -n "${STATE_DIRECTORY:-}" ]]; then
    PRIVATE_STATE_FILE="${STATE_DIRECTORY%%:*}/state"
else
    PRIVATE_STATE_FILE="${HOME:-/nonexistent}/.local/state/riskit-uptime/state"
fi
STATE_FILE="${STATE_FILE:-${PRIVATE_STATE_FILE}}"
NOTIFY_BUDGET="${NOTIFY_BUDGET:-15}"
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
#
# Storage.  The status and the per-channel retry queues live in ONE private
# directory: owned by this user, not group- or world-writable (systemd's
# StateDirectory=, mode 0700).  A configured STATE_FILE whose directory fails
# that check (e.g. the old /var/tmp default: predictable, shared, sticky) is
# replaced by the private default, so no other local user can pre-create,
# swap or block these files.  Writes go to a temp file in the same directory
# and are renamed into place (atomic; a rename replaces a symlink rather than
# following it), and one run at a time holds the directory's lock.
state_dir_is_private() {
    local d="$1" mode
    [[ -d "${d}" && ! -L "${d}" && -O "${d}" ]] || return 1
    mode="$(stat -c %a -- "${d}" 2>/dev/null)" || return 1
    (( (8#${mode} & 8#022) == 0 ))
}

pick_state_dir() {
    local d
    d="$(dirname -- "${STATE_FILE}")"
    mkdir -p -m 0700 -- "${d}" 2>/dev/null || true
    state_dir_is_private "${d}" && return 0
    logline "${NOW} WARN state directory for STATE_FILE is not private (owner or mode); using the private default"
    STATE_FILE="${PRIVATE_STATE_FILE}"
    d="$(dirname -- "${STATE_FILE}")"
    mkdir -p -m 0700 -- "${d}" 2>/dev/null || true
    state_dir_is_private "${d}"
}

if ! pick_state_dir; then
    logline "${NOW} WARN no private state directory; status not recorded and notifications skipped"
    exit "${FAILED}"
fi
STATE_DIR="$(dirname -- "${STATE_FILE}")"

if command -v flock >/dev/null 2>&1; then
    exec 9>>"${STATE_DIR}/lock"
    if ! flock -n 9; then
        logline "${NOW} INFO another uptime run holds the lock; this run records nothing"
        exit "${FAILED}"
    fi
fi
# Temp files left by a run that was killed between write and rename.
rm -f -- "${STATE_FILE}".tmp.* "${STATE_FILE}".pending-*.tmp.* 2>/dev/null || true

# write_atomic <file> <line>...  -- all lines or nothing.
write_atomic() {
    local file="$1" tmp
    shift
    tmp="$(mktemp -- "${file}.tmp.XXXXXX" 2>/dev/null)" || return 1
    if printf '%s\n' "$@" > "${tmp}" && mv -f -- "${tmp}" "${file}"; then
        return 0
    fi
    rm -f -- "${tmp}" 2>/dev/null || true
    return 1
}

PREV="$(cat -- "${STATE_FILE}" 2>/dev/null || true)"
[[ "${PREV}" == "UP" || "${PREV}" == "DOWN" ]] || PREV="UP"

# Delivery is tracked PER CHANNEL, separately from the observed status.
# The status is recorded every run (so a short outage still yields its
# "DOWN -> UP" message), and each channel keeps its own FIFO queue of
# messages it has not yet delivered (${STATE_FILE}.pending-<channel>, at most
# PENDING_MAX, oldest dropped).  Every run appends the new transition, saves
# the queue, then delivers in order, saving again after each acceptance:
#   * a failed push is retried even if the outage cleared before the next run;
#   * a working channel never repeats a message because another one failed;
#   * a run killed mid-delivery loses nothing and re-sends at most the one
#     message it was sending (at-least-once);
#   * a channel that is no longer configured has its queue discarded.
# "Delivered" means the channel accepted it: an HTTP 2xx from the webhook
# (curl -f), exit 0 from NOTIFY_CMD.  Neither proves the owner read it.
PENDING_MAX=10
MSG_MAX=1000
MSG_PREFIX="[riskit-uptime] "
DELIVERY_START="${SECONDS}"

send_one() {
    local channel="$1" msg="$2"
    case "${channel}" in
        # The body goes on stdin (@-), never as an argument: curl reads a -d
        # value that starts with "@" as a FILE NAME.
        webhook) printf '%s' "${msg}" | curl -fsS --max-time 10 -X POST --data-binary @- \
                     "${NOTIFY_WEBHOOK_URL}" >/dev/null 2>&1 ;;
        cmd)
            if command -v timeout >/dev/null 2>&1; then
                printf '%s\n' "${msg}" | timeout 10 ${NOTIFY_CMD} >/dev/null 2>&1
            else
                printf '%s\n' "${msg}" | ${NOTIFY_CMD} >/dev/null 2>&1
            fi
            ;;
        *) return 1 ;;
    esac
}

# deliver_queue <channel> <queue file> <new message, or empty>
deliver_queue() {
    local channel="$1" file="$2" new="$3"
    local -a raw=() queue=()
    local line start
    if [[ -f "${file}" && ! -L "${file}" ]]; then
        mapfile -t raw < "${file}" 2>/dev/null || raw=()
    fi
    # Replay only well-formed lines this script queued; anything else is
    # dropped, never sent.
    for line in "${raw[@]}"; do
        if [[ "${line}" == "${MSG_PREFIX}"* ]] && (( ${#line} <= MSG_MAX )); then
            queue+=("${line}")
        fi
    done
    if [[ -n "${new}" ]]; then
        queue+=("${new}")
    fi
    start=$(( ${#queue[@]} > PENDING_MAX ? ${#queue[@]} - PENDING_MAX : 0 ))
    queue=("${queue[@]:start}")
    if (( ${#queue[@]} == 0 )); then
        rm -f -- "${file}" 2>/dev/null || true
        return 0
    fi
    write_atomic "${file}" "${queue[@]}" \
        || logline "${NOW} WARN notify-${channel}: queue could not be saved"
    while (( ${#queue[@]} > 0 )); do
        if (( SECONDS - DELIVERY_START >= NOTIFY_BUDGET )); then
            logline "${NOW} WARN notify-${channel}: delivery budget spent; ${#queue[@]} message(s) kept for the next run"
            return 0
        fi
        if ! send_one "${channel}" "${queue[0]}"; then
            logline "${NOW} WARN notify-${channel} failed; ${#queue[@]} message(s) kept for the next run"
            return 0
        fi
        queue=("${queue[@]:1}")
        if (( ${#queue[@]} > 0 )); then
            write_atomic "${file}" "${queue[@]}" || true
        else
            rm -f -- "${file}" 2>/dev/null || true
        fi
    done
}

NEW_MSG=""
if [[ "${STATUS}" != "${PREV}" ]]; then
    NEW_MSG="${MSG_PREFIX}${PREV} -> ${STATUS} at ${NOW}: ${RESULTS[*]}"
fi
write_atomic "${STATE_FILE}" "${STATUS}" || logline "${NOW} WARN status could not be recorded"

if [[ -n "${NOTIFY_WEBHOOK_URL}" ]]; then
    deliver_queue webhook "${STATE_FILE}.pending-webhook" "${NEW_MSG}"
else
    rm -f -- "${STATE_FILE}.pending-webhook" 2>/dev/null || true
fi
if [[ -n "${NOTIFY_CMD}" ]]; then
    deliver_queue cmd "${STATE_FILE}.pending-cmd" "${NEW_MSG}"
else
    rm -f -- "${STATE_FILE}.pending-cmd" 2>/dev/null || true
fi

exit "${FAILED}"
