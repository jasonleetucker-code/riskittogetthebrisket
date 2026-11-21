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
#   NOTIFY_BUDGET       default 15 (seconds during which a run may START a
#                        delivery, all channels; each send is capped at
#                        SEND_TIMEOUT 10 s + 2 s to kill).  Keep
#                        3 x CURL_TIMEOUT + NOTIFY_BUDGET + 13 <= the unit's
#                        TimeoutStartSec (120).
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
# The pre-2026-11-21 unit pointed STATE_FILE at this shared path.  It is
# replaced by the private default without a warning, and its status is read
# once (below) so an outage in progress at the upgrade still gets its
# recovery message.  (Overridable for tests only.)
LEGACY_STATE_FILE="${UPTIME_LEGACY_STATE_FILE:-/var/tmp/riskit-uptime.state}"
LEGACY_FILE=""
if [[ "${STATE_FILE}" == "${LEGACY_STATE_FILE}" ]]; then
    LEGACY_FILE="${STATE_FILE}"
    STATE_FILE="${PRIVATE_STATE_FILE}"
fi
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
# case, then delivery: sends may START for NOTIFY_BUDGET (15s) and each is
# capped at 12s, so 60 + 15 + 12 + 1 = 88s, inside riskit-uptime.service's
# TimeoutStartSec=120.  If you raise CURL_TIMEOUT or NOTIFY_BUDGET, keep
# 3 x CURL_TIMEOUT + NOTIFY_BUDGET + 13 <= TimeoutStartSec.
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

if [[ ! "${NOTIFY_BUDGET}" =~ ^[0-9]{1,3}$ ]]; then
    logline "${NOW} WARN NOTIFY_BUDGET is not a whole number of seconds (0-999); using 15"
    NOTIFY_BUDGET=15
fi
NOTIFY_BUDGET=$(( 10#${NOTIFY_BUDGET} ))

# ── State-change notification (optional, operator-configured) ────────
#
# Storage.  The status and the per-channel retry queues live in ONE private
# directory: owned by this user, not group- or world-writable (systemd's
# StateDirectory=, mode 0700).  A configured STATE_FILE whose directory fails
# that check (a shared directory such as /var/tmp: predictable, shared, sticky)
# is replaced by the private default, so no other local user can pre-create,
# swap or block these files.  The run then works INSIDE the checked directory
# (cd, relative names), so a parent directory renamed after the check cannot
# redirect it.  Writes go to a temp file in that directory and are renamed
# into place (atomic; mv -T replaces a symlink rather than following it), and
# one run at a time holds the directory's lock.
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
# From here on every file is named relative to the directory just checked.
if ! cd -- "$(dirname -- "${STATE_FILE}")" 2>/dev/null || ! state_dir_is_private .; then
    logline "${NOW} WARN state directory changed during the check; status not recorded"
    exit "${FAILED}"
fi
STATE_NAME="$(basename -- "${STATE_FILE}")"

if command -v flock >/dev/null 2>&1; then
    exec 9>>lock
    if ! flock -n 9; then
        logline "${NOW} INFO another uptime run holds the lock; this run records nothing"
        exit "${FAILED}"
    fi
fi
# Temp files left by a run that was killed between write and rename.
rm -f -- "${STATE_NAME}".tmp.* "${STATE_NAME}".pending-*.tmp.* 2>/dev/null || true

# write_atomic <file> <line>...  -- all lines or nothing.
write_atomic() {
    local file="$1" tmp
    shift
    tmp="$(mktemp -- "${file}.tmp.XXXXXX" 2>/dev/null)" || return 1
    if printf '%s\n' "$@" > "${tmp}" && mv -f -T -- "${tmp}" "${file}"; then
        return 0
    fi
    rm -f -- "${tmp}" 2>/dev/null || true
    return 1
}

PREV=""
if [[ -f "${STATE_NAME}" && ! -L "${STATE_NAME}" ]]; then
    PREV="$(head -c 16 -- "${STATE_NAME}" 2>/dev/null || true)"
elif [[ -n "${LEGACY_FILE}" && -f "${LEGACY_FILE}" && ! -L "${LEGACY_FILE}" && -O "${LEGACY_FILE}" ]]; then
    # First run after the upgrade: the old status, if this user wrote it.
    PREV="$(head -c 16 -- "${LEGACY_FILE}" 2>/dev/null || true)"
fi
PREV="${PREV%%[[:space:]]*}"
[[ "${PREV}" == "UP" || "${PREV}" == "DOWN" ]] || PREV="UP"

# Delivery is tracked PER CHANNEL, separately from the observed status.  Each
# configured channel keeps its own FIFO queue of messages it has not yet
# delivered (${STATE_FILE}.pending-<channel>, at most PENDING_MAX, oldest
# dropped).  Every run, in this order:
#   1. appends the new transition to EVERY configured channel's queue and
#      saves each queue;
#   2. records the observed status (every run, so a short outage still yields
#      its "DOWN -> UP" message);
#   3. delivers each queue in order, saving it again after each acceptance.
# So a failed push is retried even if the outage cleared before the next run;
# a working channel never repeats a message because another one failed; a run
# killed at ANY point loses nothing (killed before step 2, the next run queues
# the transition again: at-least-once), and re-sends at most the one message
# it was sending; a channel that is no longer configured has its queue
# discarded.  "Delivered" means the channel accepted it: an HTTP 2xx from the
# webhook (curl -f), exit 0 from NOTIFY_CMD.  Neither proves the owner read it.
PENDING_MAX=10
MSG_MAX=1000
MSG_PREFIX="[riskit-uptime] "
SEND_TIMEOUT=10
declare -a Q_webhook=() Q_cmd=()

send_one() {
    local channel="$1" msg="$2"
    # Children never inherit the lock (fd 9): a NOTIFY_CMD that leaves a
    # process behind cannot hold every later run off.
    case "${channel}" in
        # The body goes on stdin (@-), never as an argument: curl reads a -d
        # value that starts with "@" as a FILE NAME.
        webhook) printf '%s' "${msg}" | curl -fsS --max-time "${SEND_TIMEOUT}" -X POST \
                     --data-binary @- "${NOTIFY_WEBHOOK_URL}" >/dev/null 2>&1 9>&- ;;
        cmd)
            if command -v timeout >/dev/null 2>&1; then
                # -k: a command that ignores SIGTERM is killed 2 s later.
                printf '%s\n' "${msg}" \
                    | timeout -k 2 "${SEND_TIMEOUT}" ${NOTIFY_CMD} >/dev/null 2>&1 9>&-
            else
                printf '%s\n' "${msg}" | ${NOTIFY_CMD} >/dev/null 2>&1 9>&-
            fi
            ;;
        *) return 1 ;;
    esac
}

# enqueue <channel> <queue file> <new message, or empty>
enqueue() {
    local channel="$1" file="$2" new="$3"
    local -n queue="Q_${channel}"
    local -a raw=()
    local line start
    if [[ -f "${file}" && ! -L "${file}" ]]; then
        mapfile -t raw < "${file}" 2>/dev/null || raw=()
    fi
    # Replay only well-formed lines this script queued; anything else is
    # dropped, never sent.
    queue=()
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
    else
        write_atomic "${file}" "${queue[@]}" \
            || logline "${NOW} WARN notify-${channel}: queue could not be saved"
    fi
}

DELIVERY_START=""
# deliver <channel> <queue file>
deliver() {
    local channel="$1" file="$2"
    local -n queue="Q_${channel}"
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
CHANNELS=()
if [[ -n "${NOTIFY_WEBHOOK_URL}" ]]; then
    CHANNELS+=(webhook)
else
    rm -f -- "${STATE_NAME}.pending-webhook" 2>/dev/null || true
fi
if [[ -n "${NOTIFY_CMD}" ]]; then
    CHANNELS+=(cmd)
else
    rm -f -- "${STATE_NAME}.pending-cmd" 2>/dev/null || true
fi

for channel in "${CHANNELS[@]}"; do
    enqueue "${channel}" "${STATE_NAME}.pending-${channel}" "${NEW_MSG}"
done
write_atomic "${STATE_NAME}" "${STATUS}" || logline "${NOW} WARN status could not be recorded"
DELIVERY_START="${SECONDS}"
for channel in "${CHANNELS[@]}"; do
    deliver "${channel}" "${STATE_NAME}.pending-${channel}"
done

exit "${FAILED}"
