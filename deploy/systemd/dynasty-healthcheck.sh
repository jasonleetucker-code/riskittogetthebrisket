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
#   HEALTH_CGROUP_ROOT     default /sys/fs/cgroup (cgroup v2 mount)
#   HEALTH_PROC_ROOT       default /proc
#   HEALTH_PYSPY           default 1 (0 disables the optional pre-restart
#                          py-spy dump; it only ever runs if py-spy is
#                          already installed — nothing installs it)
#   HEALTH_PYSPY_TIMEOUT   default 8 (seconds; SIGTERM at this point,
#                          SIGKILL HEALTH_PYSPY_KILL_AFTER seconds later)
#   HEALTH_PYSPY_KILL_AFTER default 2 (seconds)
#   NOTIFY_WEBHOOK_URL     default unset — OPTIONAL owner push (ntfy topic;
#                          treat as a secret, never logged).  When set, each
#                          RESTART sends exactly one POST (same transport as
#                          deploy/monitoring/uptime_check.sh).  Unset = the
#                          restart is log-only, nothing external is contacted.
#   HEALTH_NOTIFY_TIMEOUT  default 10 (seconds)

set -Eeuo pipefail

HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8000/api/health}"
HEALTH_SERVICE="${HEALTH_SERVICE:-dynasty}"
HEALTH_FAIL_THRESHOLD="${HEALTH_FAIL_THRESHOLD:-3}"
HEALTH_CURL_TIMEOUT="${HEALTH_CURL_TIMEOUT:-25}"
HEALTH_STATE_DIR="${HEALTH_STATE_DIR:-${RUNTIME_DIRECTORY:-/run/dynasty-healthcheck}}"

NOTIFY_WEBHOOK_URL="${NOTIFY_WEBHOOK_URL:-}"
HEALTH_NOTIFY_TIMEOUT="${HEALTH_NOTIFY_TIMEOUT:-10}"

FAIL_FILE="${HEALTH_STATE_DIR}/consecutive-failures"
NOTIFIED_FILE="${HEALTH_STATE_DIR}/restart-notified"
DEGRADED_FILE="${HEALTH_STATE_DIR}/degraded"

log() { printf '[healthcheck] %s\n' "$*"; }

mkdir -p "${HEALTH_STATE_DIR}"

read_failures() {
    local n
    n="$(cat "${FAIL_FILE}" 2>/dev/null || echo 0)"
    [[ "${n}" =~ ^[0-9]+$ ]] || n=0
    printf '%s' "${n}"
}

# ── FD utilisation watch (2026-08-12 incident) ───────────────────────
# The backend exhausted its file descriptors and wedged: `socket.accept()`
# raised `OSError: [Errno 24] Too many open files` 1,212 times from PID
# 887292, first at 16:47:46 local.  The kernel kept completing TCP
# handshakes into the listen backlog, so nginx connected in 0.4 ms and
# then waited its full 300 s `proxy_read_timeout` for bytes that never
# came.  Nothing anywhere reported the descriptor count on the way up.
#
# This lives HERE, in the existing minutely root-run healthcheck, rather
# than in a new subsystem or an application endpoint — the whole point is
# that it must work when the process cannot answer HTTP, which is exactly
# when an /api/ metric is unavailable.  It runs BEFORE the liveness
# branch so it reports on every tick, alive or not.
#
# It only ever REPORTS.  No restart on a threshold: the liveness rule
# above is the only thing allowed to restart this service, and adding a
# second independent restart trigger during an incident repair is how you
# get a bounce loop nobody predicted.
#
# Thresholds are absolute, not a percentage of the limit.  A healthy
# process measures ~16 descriptors, so 80% of an 8192 soft limit would
# be a 400x excursion — an alarm that only fires once the situation is
# already unrecoverable.  256 is ~16x normal: far outside anything this
# workload does, far below anything that breaks.
FD_WARN="${FD_WARN:-256}"
FD_CRIT="${FD_CRIT:-512}"
FD_EMERG="${FD_EMERG:-768}"
FD_TIER_FILE="${HEALTH_STATE_DIR}/fd-tier"

fd_watch() {
    local pid soft total tier prev sockets files anon uptime
    pid="$(systemctl show "${HEALTH_SERVICE}.service" -p MainPID --value 2>/dev/null)"
    [[ -n "${pid}" && "${pid}" != "0" ]] || return 0

    # /proc/PID/fd is the canonical count of OPEN DESCRIPTORS.  Deliberately
    # not lsof: its output also carries memory mappings, cwd and the text
    # segment, so counting its REG rows answers a different question.
    total="$(find "/proc/${pid}/fd" -maxdepth 1 -type l 2>/dev/null | wc -l)"
    # A denied or vanished /proc yields 0 from `find`, and "0 descriptors"
    # is not a state a running server can be in — report nothing rather
    # than a false all-clear.
    (( total > 0 )) || return 0

    # The kernel's soft limit for THIS process, not the unit's declared
    # value: a drop-in or a manual ulimit can make them differ, and EMFILE
    # is raised against the kernel's.
    soft="$(awk '/^Max open files/{print $4}' "/proc/${pid}/limits" 2>/dev/null)"
    [[ "${soft}" =~ ^[0-9]+$ ]] || soft=0

    if   (( total >= FD_EMERG )); then tier=EMERGENCY
    elif (( total >= FD_CRIT ));  then tier=CRITICAL
    elif (( total >= FD_WARN ));  then tier=WARNING
    else tier=OK
    fi

    prev="$(cat "${FD_TIER_FILE}" 2>/dev/null || echo OK)"
    printf '%s\n' "${tier}" > "${FD_TIER_FILE}"
    [[ "${tier}" == "${prev}" ]] && return 0   # transitions only, not every minute

    if [[ "${tier}" == "OK" ]]; then
        log "fd: recovered — ${total} descriptors (was ${prev})"
        return 0
    fi

    # Only pay for the breakdown when something is actually wrong.  Which
    # KIND is growing is the question a responder needs answered first,
    # and it is unrecoverable once the process is gone.
    sockets=0; files=0; anon=0
    while IFS= read -r l; do
        case "$(readlink "$l" 2>/dev/null)" in
            socket:*)     sockets=$((sockets+1)) ;;
            anon_inode:*) anon=$((anon+1)) ;;
            /*)           files=$((files+1)) ;;
        esac
    done < <(find "/proc/${pid}/fd" -maxdepth 1 -type l 2>/dev/null)
    uptime="$(systemctl show "${HEALTH_SERVICE}.service" -p ActiveEnterTimestamp --value 2>/dev/null)"

    log "fd ${tier}: pid=${pid} fds=${total} soft_limit=${soft} used=$(( soft > 0 ? total * 100 / soft : 0 ))% sockets=${sockets} files=${files} anon=${anon} up_since='${uptime}' (report only — not restarting)"
}

fd_watch || true

# ── cgroup pressure snapshot (2026-10-19 incident) ────────────────────
# The 2026-10-19 08:42 UTC restart was this watchdog (PROVEN: three
# no-response probes, SIGTERM ignored for TimeoutStopSec, SIGKILL).  WHY
# the process stopped answering was left at LIKELY memory throttling, not
# proven, for one reason: the dead process's own cgroup counters
# (memory.events high, memory.pressure) are destroyed when the restart
# recreates the cgroup, and host-wide PSI cannot be attributed to one
# cgroup.  So, on every LIVENESS FAIL and immediately before a restart,
# record the backend cgroup's memory and pressure counters into the
# journal while they still exist.
#
# REPORT ONLY.  These are plain file reads (cheap, never blocking on the
# backend), every read tolerates a missing file, and nothing here feeds
# the restart decision.  Every logged value is numeric (or "na" / "max"),
# so the public restart-diagnostics workflow can allowlist the lines
# strictly (deploy/diagnostics/prod_restart_diagnostics.sh); each line is
# kept under that workflow's 300-character cut.
HEALTH_CGROUP_ROOT="${HEALTH_CGROUP_ROOT:-/sys/fs/cgroup}"
HEALTH_PROC_ROOT="${HEALTH_PROC_ROOT:-/proc}"
HEALTH_PYSPY="${HEALTH_PYSPY:-1}"
HEALTH_PYSPY_TIMEOUT="${HEALTH_PYSPY_TIMEOUT:-8}"
HEALTH_PYSPY_KILL_AFTER="${HEALTH_PYSPY_KILL_AFTER:-2}"

# A value as it may be logged: a number, "max" (an unlimited cgroup knob)
# or "na" for anything missing or unexpected.
_snap_val() {
    if [[ "${1:-}" =~ ^[0-9]+(\.[0-9]+)?$ || "${1:-}" == "max" ]]; then
        printf '%s' "$1"
    else
        printf 'na'
    fi
}

# First line of a single-value file, or "na".
_snap_file() {
    local v=""
    if [[ -r "$1" ]]; then read -r v < "$1" 2>/dev/null || true; fi
    _snap_val "${v}"
}

# "key value" files (memory.events, memory.stat, /proc/meminfo): the value
# of each requested key, as " out=value" pairs.
_snap_keyed() {
    local file="$1"; shift
    local -A seen=()
    local k v _rest pair out=""
    if [[ -r "${file}" ]]; then
        while read -r k v _rest; do
            seen["${k%:}"]="${v}"
        done < "${file}" 2>/dev/null
    fi
    for pair in "$@"; do
        out+=" ${pair%%=*}=$(_snap_val "${seen[${pair#*=}]:-}")"
    done
    printf '%s' "${out}"
}

# A PSI file ("some avg10=.. avg60=.. avg300=.. total=..", "full ...") as
# " <prefix>some_avg10=.. <prefix>some_avg60=.. <prefix>some_total=.. ...".
_snap_psi() {
    local file="$1" prefix="${2:-}" kind rest kv k
    local -A seen=()
    if [[ -r "${file}" ]]; then
        while read -r kind rest; do
            for kv in ${rest}; do seen["${kind}_${kv%%=*}"]="${kv#*=}"; done
        done < "${file}" 2>/dev/null
    fi
    local out=""
    for k in some_avg10 some_avg60 some_total full_avg10 full_avg60 full_total; do
        out+=" ${prefix}${k}=$(_snap_val "${seen[${k}]:-}")"
    done
    printf '%s' "${out}"
}

backend_cgroup_dir() {
    local cg
    cg="$(systemctl show "${HEALTH_SERVICE}.service" -p ControlGroup --value 2>/dev/null || true)"
    [[ "${cg}" =~ ^/[A-Za-z0-9@._/-]+$ ]] || cg="/system.slice/${HEALTH_SERVICE}.service"
    printf '%s%s' "${HEALTH_CGROUP_ROOT}" "${cg}"
}

cgroup_snapshot() {
    local reason="$1" cg
    cg="$(backend_cgroup_dir)"
    log "snapshot mem reason=${reason} cur=$(_snap_file "${cg}/memory.current") peak=$(_snap_file "${cg}/memory.peak") high=$(_snap_file "${cg}/memory.high") max=$(_snap_file "${cg}/memory.max")$(_snap_keyed "${cg}/memory.events" ev_high=high ev_max=max ev_oom=oom ev_oom_kill=oom_kill)"
    log "snapshot stat reason=${reason}$(_snap_keyed "${cg}/memory.stat" anon=anon file=file shmem=shmem kernel=kernel sock=sock)"
    log "snapshot psi_memory reason=${reason}$(_snap_psi "${cg}/memory.pressure")"
    log "snapshot psi_cpu reason=${reason}$(_snap_psi "${cg}/cpu.pressure")"
    log "snapshot psi_io reason=${reason}$(_snap_psi "${cg}/io.pressure")"
    # Host-wide context (h_* = host PSI), so the next incident can tell a cgroup-local
    # stall (high cgroup PSI, plenty of host MemAvailable) from global
    # reclaim.
    log "snapshot host reason=${reason}$(_snap_keyed "${HEALTH_PROC_ROOT}/meminfo" mem_available_kb=MemAvailable)$(_snap_psi "${HEALTH_PROC_ROOT}/pressure/memory" h_)"
}

# Optional, restart path only: a Python stack dump of the wedged process,
# ONLY if py-spy is already installed on the host (this script installs
# nothing).  Written to the state dir rather than the journal — stack
# frames name files and functions, which the public diagnostics workflow
# must not echo — and only a numeric receipt is logged.  Hard-bounded:
# SIGTERM at HEALTH_PYSPY_TIMEOUT, then SIGKILL HEALTH_PYSPY_KILL_AFTER
# seconds later (`timeout -k`).  Without `-k` the timeout only SENDS
# SIGTERM, and a py-spy that ignores it would hold the restart open past
# the unit's TimeoutStartSec — the restart would then never run.
pyspy_dump() {
    [[ "${HEALTH_PYSPY}" == "1" ]] || return 0
    command -v py-spy >/dev/null 2>&1 || return 0
    command -v timeout >/dev/null 2>&1 || return 0
    local pid out rc=0 bytes
    pid="$(systemctl show "${HEALTH_SERVICE}.service" -p MainPID --value 2>/dev/null || true)"
    [[ "${pid}" =~ ^[0-9]+$ && "${pid}" != "0" ]] || return 0
    out="${HEALTH_STATE_DIR}/pyspy-$(date -u +%Y%m%dT%H%M%SZ).txt"
    timeout -k "${HEALTH_PYSPY_KILL_AFTER}" "${HEALTH_PYSPY_TIMEOUT}" py-spy dump --pid "${pid}" > "${out}" 2>&1 || rc=$?
    bytes="$(wc -c < "${out}" 2>/dev/null || echo 0)"
    log "snapshot pyspy reason=pre-restart rc=$(_snap_val "${rc}") bytes=$(_snap_val "${bytes// /}")"
    # Keep the newest three dumps.
    ls -1t "${HEALTH_STATE_DIR}"/pyspy-*.txt 2>/dev/null | tail -n +4 | xargs -r rm -f -- 2>/dev/null
    return 0
}

# One owner push per restart episode, never one per probe.  The marker is
# written only after a push was DELIVERED (a failed push is retried on the
# next threshold crossing) and is cleared as soon as the backend answers
# again, so the next outage notifies afresh.  The URL is never printed:
# failures log a reason class only.  Never fails the watchdog.
# The shell form of src/utils/owner_notify.validate (this root-owned copy has
# no repo Python), checked in validate()'s own order: inner whitespace; any
# byte outside printable ASCII or an unparsable port/[ipv6] (malformed); the
# raw scheme must be lower-case https, or http to EXACTLY localhost /
# 127.0.0.1 / [::1] (host compared lower-cased, as urlsplit does); no
# user:pass@; a host.  Prints a reason CODE on refusal, never any part of the
# value.  tests/deploy/test_alert_shell_pushes.py diffs it against validate()
# over a generated corpus: identical answers, except a bracketed host other
# than [::1], which this refuses.
# owner_notify.validate() drops surrounding whitespace with Python's
# str.strip(), i.e. every character str.isspace() accepts -- more than bash's
# [[:space:]] (it also strips \x1c-\x1f, NBSP and the Unicode spaces).  The
# same set, as UTF-8 byte sequences, so a value pasted with a trailing NBSP is
# judged and sent exactly as the reporter judged it.
PY_STRIP_CHARS=(
    $'\t' $'\n' $'\v' $'\f' $'\r' $'\x1c' $'\x1d' $'\x1e' $'\x1f' ' '
    $'\xc2\x85' $'\xc2\xa0' $'\xe1\x9a\x80'
    $'\xe2\x80\x80' $'\xe2\x80\x81' $'\xe2\x80\x82' $'\xe2\x80\x83'
    $'\xe2\x80\x84' $'\xe2\x80\x85' $'\xe2\x80\x86' $'\xe2\x80\x87'
    $'\xe2\x80\x88' $'\xe2\x80\x89' $'\xe2\x80\x8a'
    $'\xe2\x80\xa8' $'\xe2\x80\xa9' $'\xe2\x80\xaf' $'\xe2\x81\x9f' $'\xe3\x80\x80'
)

# py_strip <value>: sets PY_STRIPPED to the value without surrounding
# str.isspace() characters.
py_strip() {
    local LC_ALL=C
    local s="$1" w changed=1
    while (( changed )); do
        changed=0
        for w in "${PY_STRIP_CHARS[@]}"; do
            if [[ -n "${s}" && "${s}" == "${w}"* ]]; then s="${s#"${w}"}"; changed=1; fi
            if [[ -n "${s}" && "${s}" == *"${w}" ]]; then s="${s%"${w}"}"; changed=1; fi
        done
    done
    PY_STRIPPED="${s}"
}

webhook_reject_reason() {
    local LC_ALL=C
    local u="$1" scheme rest authority hostport host port
    if [[ "${u}" =~ [[:space:]] ]]; then echo whitespace; return; fi
    if [[ "${u}" =~ [^[:graph:]] ]]; then echo malformed; return; fi
    scheme="${u%%:*}"
    authority=""
    # As urlsplit: an authority exists only after a valid scheme and "//".
    if [[ "${scheme}" =~ ^[A-Za-z][A-Za-z0-9+.-]*$ && "${u}" == "${scheme}://"* ]]; then
        rest="${u#"${scheme}://"}"
        authority="${rest%%[/?#]*}"
    fi
    hostport="${authority##*@}"
    port=""
    # urlsplit refuses an authority with "[" but no "]", or the reverse.
    if [[ "${authority}" == *\[* && "${authority}" != *\]* ]] \
        || [[ "${authority}" == *\]* && "${authority}" != *\[* ]]; then
        echo malformed; return
    fi
    if [[ "${hostport}" == \[* ]]; then
        if [[ "${hostport}" != *\]* ]]; then echo malformed; return; fi
        host="${hostport#\[}"
        host="${host%%\]*}"
        # Stricter than validate() on purpose: the only bracketed host allowed
        # is the loopback [::1] (validate() also accepts any valid IPv6
        # literal; no ntfy webhook is a bare IPv6 address, and refusing one
        # fails safe -- nothing is sent).
        if [[ "${host}" != "::1" ]]; then echo malformed; return; fi
        rest="${hostport#*\]}"
        if [[ -n "${rest}" ]]; then
            if [[ "${rest}" != :* ]]; then echo malformed; return; fi
            port="${rest#:}"
        fi
    elif [[ "${hostport}" == *[\[\]]* ]]; then
        # A bracket anywhere but around the whole host: refused (urlsplit
        # refuses most such values; refusing the rest fails safe).
        echo malformed; return
    elif [[ "${hostport}" == *:* ]]; then
        host="${hostport%%:*}"
        port="${hostport#*:}"
    else
        host="${hostport}"
    fi
    if [[ -n "${port}" ]]; then
        # As urlsplit: ASCII digits, leading zeros allowed, 0..65535.
        if [[ ! "${port}" =~ ^[0-9]+$ ]]; then echo malformed; return; fi
        port="${port#"${port%%[!0]*}"}"
        if (( ${#port} > 5 )) || (( 10#${port:-0} > 65535 )); then
            echo malformed; return
        fi
    fi
    host="${host,,}"
    if [[ "${scheme}" == "https" ]]; then
        :
    elif [[ "${scheme}" == "http" ]] && [[ "${host}" == "localhost" || "${host}" == "127.0.0.1" || "${host}" == "::1" ]]; then
        :
    else
        echo scheme; return
    fi
    if [[ "${authority}" == *@* ]]; then echo userinfo; return; fi
    if [[ -z "${host}" ]]; then echo no_host; return; fi
}

notify_restart() {
    local url reason
    py_strip "${NOTIFY_WEBHOOK_URL}"
    url="${PY_STRIPPED}"
    [[ -n "${url}" ]] || return 0
    [[ ! -f "${NOTIFIED_FILE}" ]] || return 0
    reason="$(webhook_reject_reason "${url}")"
    if [[ -n "${reason}" ]]; then
        log "WARN: restart push not sent (reason=webhook_rejected:${reason})"
        return 0
    fi
    local rc=0
    curl -fsS --max-time "${HEALTH_NOTIFY_TIMEOUT}" -X POST \
        -d "[dynasty-healthcheck] restarting ${HEALTH_SERVICE}.service after ${failures} consecutive liveness failures at $(date -u +%FT%TZ)" \
        "${url}" >/dev/null 2>&1 || rc=$?
    if (( rc == 0 )); then
        : > "${NOTIFIED_FILE}" 2>/dev/null || true
        log "restart push delivered"
    else
        log "WARN: restart push failed (reason=curl_exit_${rc})"
    fi
    return 0
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
    rm -f "${NOTIFIED_FILE}"

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
cgroup_snapshot "liveness-fail-${failures}" || true

if (( failures < HEALTH_FAIL_THRESHOLD )); then
    exit 0
fi

log "threshold reached — restarting ${HEALTH_SERVICE}.service"
# Last chance to read the dying cgroup's counters: the restart below
# destroys them.
cgroup_snapshot "pre-restart" || true
pyspy_dump || true
notify_restart
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
