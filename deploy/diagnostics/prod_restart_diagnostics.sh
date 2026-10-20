#!/usr/bin/env bash
# Read-only evidence for "why did the backend restart, and what did the
# liveness watchdog see?"
#
# Written for the 2026-10-19 production stall.  Private endpoints began
# timing out at 45 s around 08:28 UTC, timed out continuously from about
# 08:39:30, and the backend came back at 08:42:49 on the SAME commit
# (public /api/status build.process_started_at).  Nobody had read the box
# journal.  The candidate mechanisms:
#
#   * the liveness watchdog (deploy/systemd/dynasty-healthcheck.sh): three
#     consecutive minutely /api/health probes with no HTTP answer in 25 s,
#     then `systemctl restart`;
#   * MemoryHigh throttling (slows every thread, the event loop included),
#     which ends in that same watchdog restart;
#   * a MemoryMax OOM kill, after which Restart=always starts it in 5 s.
#
# Each leaves a different footprint in the journal, and this script prints
# only those footprints.  It is reusable for any window.
#
# CONTRACT — READ-ONLY and COUNT-ONLY.  It never restarts, reloads,
# deploys, checks out, writes to the app tree or imports the application.
# It prints NO application log line.  Every journal line it prints has
# passed a strict allowlist (systemd unit lifecycle, kernel OOM, the
# watchdog's own verdicts, uvicorn's start/stop banners), and is cut to
# 300 characters.  Everything else the application logged (request
# lines, query strings, cookies, tokens, bodies, tracebacks) is reduced
# to per-minute COUNTS and never echoed.  No environment variable or
# command line is printed: `systemctl show` gets an explicit property
# list without Environment or ExecStart.
#
# Pinned by tests/deploy/test_prod_restart_diagnostics.py, which feeds the
# allowlist synthetic journal text carrying secrets.
#
# Usage:
#   prod_restart_diagnostics.sh [service] [since_utc] [until_utc]
#       since/until: "YYYY-MM-DD HH:MM[:SS]" in UTC (a "T" separator and a
#       trailing "Z" are accepted).  Default window 2026-10-19 08:20-08:50.
#   prod_restart_diagnostics.sh --filter service|healthcheck|kernel|units
#       stdin = journal text (-o short-iso-precise); prints allowlisted lines.
#   prod_restart_diagnostics.sh --counts [HH:MM ...]
#       stdin = journal text; prints the per-minute count table only.
#
# Exit: 0 complete; 2 bad arguments or missing tools; 5 required evidence
# missing (the journal could not be read, or held nothing for the
# service in the window).  There is no unconditional `exit 0`: a
# diagnostic that could not look must not read as one that looked and
# found nothing.

set -uo pipefail

MAX_LINE=300

# Journal line prefix in `-o short-iso(-precise)`: timestamp then hostname.
TS='^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]+)?([+-][0-9]{2}:?[0-9]{2}|Z)? [^ ]+ '

# systemd (PID 1) talking about a unit's lifecycle.  Nothing a request
# carries can appear in these.
RE_SYSTEMD="${TS}systemd\\[1\\]: ([A-Za-z0-9@._-]+\\.(service|timer|scope): )?(Started|Starting|Stopping|Stopped|Finished|Deactivated successfully|Main process exited|Failed with result|Failed to start|Killing process|Sent signal|State '[a-z-]+' timed out|Scheduled restart job|Start request repeated too quickly|A process of this unit has been killed by the OOM killer|Consumed|Control process exited|Processes still around)"
# The healthcheck unit's own systemd lines, minus the routine minutely
# Starting / Finished / Deactivated / Consumed noise.
RE_SYSTEMD_FAILURE="${TS}systemd\\[1\\]: ([A-Za-z0-9@._-]+\\.(service|timer): )?(Main process exited|Failed with result|Failed to start|Killing process|State '[a-z-]+' timed out)"
# The watchdog's verdicts (deploy/systemd/dynasty-healthcheck.sh log()).
RE_HEALTHCHECK="${TS}[^ ]+\\[[0-9]+\\]: \\[healthcheck\\] (LIVENESS FAIL [0-9]+/[0-9]+|threshold reached|restart issued|ERROR: systemctl restart|recovered|DEGRADED \\(log-only\\)|degraded state cleared|fd (WARNING|CRITICAL|EMERGENCY|recovered))"
# uvicorn's start/stop banners, matched as WHOLE messages so an
# application line that merely contains "Shutting down" cannot pass.
RE_UVICORN="${TS}[^ ]+\\[[0-9]+\\]: (INFO|WARNING|ERROR):? +(Started server process \\[[0-9]+\\]|Waiting for application startup\\.|Application startup complete\\.|Shutting down|Waiting for application shutdown\\.|Application shutdown complete\\.|Finished server process \\[[0-9]+\\]|Uvicorn running on https?://[0-9A-Za-z.:]+ \\(Press CTRL\\+C to quit\\))$"
# Kernel OOM verdicts only, never the task table that follows them.
RE_KERNEL="${TS}kernel: (.* invoked oom-killer:|oom-kill:|Out of memory:|Memory cgroup out of memory:|oom_reaper: )"
# systemd-oomd's kill verdicts.
RE_OOMD="${TS}systemd-oomd\\[[0-9]+\\]: (Killed|Considered)"

lifecycle_filter() {
  local kind="$1" re
  case "${kind}" in
    service)     re="(${RE_SYSTEMD})|(${RE_UVICORN})" ;;
    healthcheck) re="(${RE_SYSTEMD_FAILURE})|(${RE_HEALTHCHECK})" ;;
    kernel)      re="(${RE_KERNEL})|(${RE_OOMD})" ;;
    units)       re="${RE_SYSTEMD}" ;;
    *) echo "unknown filter kind: ${kind}" >&2; return 2 ;;
  esac
  # `|| true`: grep exits 1 on "no lines", which is an answer, not a fault.
  { grep -E -- "${re}" || true; } | cut -c1-"${MAX_LINE}"
}

# Per-minute counts of the application log.  Prints the minute and
# integers, never a line.  Optional args: HH:MM keys to zero-fill, so a
# minute in which the process logged NOTHING shows as zeros rather than
# vanishing — that gap is the stall.
minute_counts() {
  awk -v keys="$*" '
    BEGIN {
      nk = split(keys, order, " ")
      fam["http"]        = "\"(GET|POST|HEAD|PUT|PATCH|DELETE|OPTIONS) [^ ]+ HTTP/[0-9.]+\" [0-9][0-9][0-9]"
      fam["health"]      = "\"(GET|HEAD) /api/health[^ ]* HTTP/[0-9.]+\" [0-9][0-9][0-9]"
      fam["http5xx"]     = "HTTP/[0-9.]+\" 5[0-9][0-9]"
      fam["uptime_fail"] = "Uptime check failed \\("
      fam["alert_fail"]  = "Failed to send alert email"
      fam["alert_sent"]  = "Alert sent: "
      fam["traceback"]   = "Traceback \\(most recent call last\\)"
      fam["memerr"]      = "MemoryError"
      fam["emfile"]      = "Errno 24"
      nf = split("http health http5xx uptime_fail alert_fail alert_sent traceback memerr emfile", fo, " ")
    }
    $1 ~ /^[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]/ {
      m = substr($1, 12, 5)
      if (!(m in seen)) { seen[m] = 1; if (nk == 0) order[++extra] = m }
      lines[m]++
      for (i = 1; i <= nf; i++) if ($0 ~ fam[fo[i]]) c[m, fo[i]]++
    }
    END {
      n = (nk > 0) ? nk : extra
      for (j = 1; j <= n; j++) {
        m = order[j]
        out = m " lines=" (lines[m] + 0)
        for (i = 1; i <= nf; i++) out = out " " fo[i] "=" (c[m, fo[i]] + 0)
        print out
      }
    }
  '
}

# ── filter-only entry points (used by the tests; harmless anywhere) ───
case "${1:-}" in
  --filter) lifecycle_filter "${2:-}"; exit $? ;;
  --counts) shift; minute_counts "$@"; exit $? ;;
esac

SERVICE_NAME="${1:-${SERVICE_NAME:-dynasty}}"
SINCE_UTC="${2:-2026-10-19 08:20}"
UNTIL_UTC="${3:-2026-10-19 08:50}"
HEALTH_UNIT="${SERVICE_NAME}-healthcheck"

if [[ ! "${SERVICE_NAME}" =~ ^[A-Za-z0-9@._-]+$ ]]; then
  echo "refusing service name '${SERVICE_NAME}'" >&2
  exit 2
fi

find_bin() {
  local override="$1" name="$2" c
  if [[ -n "${override}" ]]; then printf '%s' "${override}"; return 0; fi
  for c in "/bin/${name}" "/usr/bin/${name}"; do
    [[ -x "${c}" ]] && { printf '%s' "${c}"; return 0; }
  done
  command -v "${name}" 2>/dev/null
}
JOURNALCTL="$(find_bin "${DIAG_JOURNALCTL:-}" journalctl)"
SYSTEMCTL="$(find_bin "${DIAG_SYSTEMCTL:-}" systemctl)"
[[ -n "${JOURNALCTL}" ]] || { echo "journalctl not found" >&2; exit 2; }
[[ -n "${SYSTEMCTL}" ]] || { echo "systemctl not found" >&2; exit 2; }

to_epoch() {
  local v="$1"
  [[ "${v}" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}[\ T][0-9]{2}:[0-9]{2}(:[0-9]{2})?Z?$ ]] || return 1
  v="${v/T/ }"; v="${v%Z}"
  date -u -d "${v}" +%s 2>/dev/null
}
SINCE_EPOCH="$(to_epoch "${SINCE_UTC}")" || { echo "bad since_utc '${SINCE_UTC}'" >&2; exit 2; }
UNTIL_EPOCH="$(to_epoch "${UNTIL_UTC}")" || { echo "bad until_utc '${UNTIL_UTC}'" >&2; exit 2; }
if (( UNTIL_EPOCH <= SINCE_EPOCH || UNTIL_EPOCH - SINCE_EPOCH > 86400 )); then
  echo "window must be positive and at most 24h (got ${SINCE_UTC} -> ${UNTIL_UTC})" >&2
  exit 2
fi
MINUTES=()
for (( t = SINCE_EPOCH - SINCE_EPOCH % 60; t < UNTIL_EPOCH; t += 60 )); do
  MINUTES+=("$(date -u -d "@${t}" +%H:%M)")
done

section() { printf '\n===== %s =====\n' "$*"; }
REQUIRED_FAILED=()
required_failed() {
  REQUIRED_FAILED+=("$1")
  printf '[REQUIRED EVIDENCE MISSING] %s\n' "$1" >&2
}

# ── journal access ────────────────────────────────────────────────────
# The deploy user's NOPASSWD sudo covers journalctl.  Without it only the
# user's own journal is visible, which would read as "nothing happened".
J_MODE=none
if sudo -n "${JOURNALCTL}" -q -n 0 --no-pager >/dev/null 2>&1; then
  J_MODE=sudo
elif "${JOURNALCTL}" -q -n 0 --no-pager >/dev/null 2>&1; then
  J_MODE=plain
fi
J() {
  case "${J_MODE}" in
    sudo)  sudo -n "${JOURNALCTL}" "$@" 2>/dev/null ;;
    plain) "${JOURNALCTL}" "$@" 2>/dev/null ;;
    *)     return 1 ;;
  esac
}
OUTFMT=short-iso-precise
J -q -n 0 --no-pager -o "${OUTFMT}" >/dev/null || OUTFMT=short-iso
JW=(--since "@${SINCE_EPOCH}" --until "@${UNTIL_EPOCH}" --no-pager -q --utc -o "${OUTFMT}")

S() {
  "${SYSTEMCTL}" show "$@" 2>/dev/null || sudo -n "${SYSTEMCTL}" show "$@" 2>/dev/null
}

section "context"
echo "window_utc: ${SINCE_UTC} -> ${UNTIL_UTC} (epoch ${SINCE_EPOCH} -> ${UNTIL_EPOCH})"
echo "now_utc: $(date -u '+%Y-%m-%dT%H:%M:%SZ')  host_tz: $(date +%Z)  booted: $(uptime -s 2>/dev/null || echo unknown)"
echo "systemd: $("${SYSTEMCTL}" --version 2>/dev/null | head -1)"
echo "journal_access: ${J_MODE}  output: ${OUTFMT}"
if [[ "${J_MODE}" == "plain" ]]; then
  echo "WARNING: journal read WITHOUT sudo; system units may be invisible, so an empty answer below proves nothing."
fi

# ── required: unit lifecycle properties ──────────────────────────────
section "unit properties (${SERVICE_NAME}.service)"
# NRestarts counts systemd's own Restart= restarts.  A restart JOB (the
# watchdog's `systemctl restart`, or an operator's) flushes it to 0, so
# NRestarts>=1 with a recent ActiveEnterTimestamp points at a crash or OOM
# path, and 0 points at a requested restart.
svc_props="$(S "${SERVICE_NAME}.service" \
  -p Id -p LoadState -p ActiveState -p SubState -p Result -p NRestarts -p MainPID \
  -p ExecMainPID -p ExecMainCode -p ExecMainStatus \
  -p ExecMainStartTimestamp -p ExecMainExitTimestamp \
  -p ActiveEnterTimestamp -p ActiveExitTimestamp \
  -p InactiveEnterTimestamp -p InactiveExitTimestamp -p StateChangeTimestamp \
  -p MemoryCurrent -p MemoryPeak -p MemorySwapCurrent -p MemorySwapPeak \
  -p MemoryHigh -p MemoryMax -p MemorySwapMax -p OOMPolicy \
  -p ManagedOOMMemoryPressure -p ManagedOOMSwap \
  -p TasksCurrent -p CPUUsageNSec -p Restart -p RestartUSec \
  -p TimeoutStopUSec -p StartLimitBurst -p StartLimitIntervalUSec \
  -p LimitNOFILESoft)"
printf '%s\n' "${svc_props}"
# `systemctl show` answers for a unit that does not exist (LoadState=not-found).
[[ "${svc_props}" == *"Id=${SERVICE_NAME}.service"* && "${svc_props}" == *"LoadState=loaded"* ]] \
  || required_failed "systemctl show ${SERVICE_NAME}.service: unit not loaded or no answer"

section "unit properties (${HEALTH_UNIT}.service / .timer)"
S "${HEALTH_UNIT}.service" -p Id -p ActiveState -p SubState -p Result \
  -p ExecMainCode -p ExecMainStatus -p ExecMainStartTimestamp \
  -p ExecMainExitTimestamp -p NRestarts || echo "(unavailable)"
S "${HEALTH_UNIT}.timer" -p Id -p ActiveState -p Result -p LastTriggerUSec \
  -p NextElapseUSecRealtime || echo "(unavailable)"

# ── optional: memory accounting of the CURRENT cgroup ────────────────
# A service restart recreates its cgroup, so these counters describe the
# process started after the restart, not the one that died.  They say
# whether the replacement is already back near MemoryHigh.
section "cgroup memory (current process only)"
cg="/sys/fs/cgroup/system.slice/${SERVICE_NAME}.service"
if [[ -d "${cg}" ]]; then
  for f in memory.current memory.peak memory.high memory.max memory.swap.current; do
    [[ -r "${cg}/${f}" ]] && printf '%s=%s\n' "${f}" "$(head -c 64 "${cg}/${f}")"
  done
  for f in memory.events memory.pressure cpu.pressure io.pressure; do
    [[ -r "${cg}/${f}" ]] && sed "s/^/${f}: /" "${cg}/${f}" | head -8
  done
else
  echo "(no cgroup v2 directory at ${cg})"
fi

section "host memory and pressure (since boot)"
free -m 2>/dev/null | head -3
for f in memory cpu io; do
  [[ -r "/proc/pressure/${f}" ]] && sed "s/^/psi_${f}: /" "/proc/pressure/${f}"
done

section "watchdog state files"
for f in consecutive-failures fd-tier; do
  p="/run/${HEALTH_UNIT}/${f}"
  if [[ -r "${p}" ]]; then printf '%s=%s\n' "${f}" "$(head -c 32 "${p}" | tr -dc '0-9A-Z')"; fi
done
[[ -e "/run/${HEALTH_UNIT}/degraded" ]] && echo "degraded=present" || echo "degraded=absent"

# ── required: the journal window ─────────────────────────────────────
section "boots (a reboot in the window would explain a restart)"
J --list-boots --no-pager 2>/dev/null | tail -3 | cut -c1-"${MAX_LINE}" || echo "(unavailable)"

svc_journal=""
if [[ "${J_MODE}" == "none" ]]; then
  required_failed "journal unreadable (no sudo journalctl, no plain access)"
else
  svc_journal="$(J -u "${SERVICE_NAME}.service" "${JW[@]}")"
  n_svc="$(printf '%s' "${svc_journal}" | grep -c . || true)"
  echo
  echo "service journal lines in window: ${n_svc} (0 means wrong window or rotated journal, NOT an idle service)"
  (( n_svc > 0 )) || required_failed "no ${SERVICE_NAME}.service journal lines in the window"
fi

section "${SERVICE_NAME}.service lifecycle (systemd + uvicorn banners only)"
printf '%s\n' "${svc_journal}" | lifecycle_filter service

section "${HEALTH_UNIT} verdicts"
hc_lines="$(J -u "${HEALTH_UNIT}.service" "${JW[@]}" | lifecycle_filter healthcheck)"
printf '%s\n' "${hc_lines}"

section "kernel OOM / systemd-oomd"
kern_lines="$( { J -k "${JW[@]}"; J -u systemd-oomd.service "${JW[@]}"; } | lifecycle_filter kernel)"
if [[ -n "${kern_lines}" ]]; then printf '%s\n' "${kern_lines}"; else echo "(none in window)"; fi

section "${SERVICE_NAME}.service application log, per minute (COUNTS ONLY)"
echo "http = access-log lines (0 while the process is alive = it was not serving)"
printf '%s\n' "${svc_journal}" | minute_counts "${MINUTES[@]}"

section "other units systemd started or stopped in the window"
# Correlation, not provocation: concurrent timers compete for the same
# memory.  systemd's own lines only.
J _PID=1 "${JW[@]}" | lifecycle_filter units \
  | grep -E 'Started|Finished|Deactivated|Consumed|Failed|Killing|OOM' \
  | grep -vE "systemd\\[1\\]: (${HEALTH_UNIT}\\.service: |Starting |Finished ${HEALTH_UNIT})" \
  | grep -vE '\.scope|user@|user-runtime-dir@' \
  | grep -vE "systemd\\[1\\]: [A-Za-z]* ?${SERVICE_NAME}\\.service( -|: )" \
  | head -60

section "nginx upstream timeouts, per minute (counts only)"
# nginx writes local time; map each UTC minute to the host's local minute.
ngx=/var/log/nginx/error.log
if [[ -r "${ngx}" ]]; then
  map=""
  for (( t = SINCE_EPOCH - SINCE_EPOCH % 60; t < UNTIL_EPOCH; t += 60 )); do
    map+="$(date -d "@${t}" '+%Y/%m/%d %H:%M') $(date -u -d "@${t}" +%H:%M)"$'\n'
  done
  awk -v map="${map}" '
    BEGIN { n = split(map, rows, "\n"); for (i = 1; i <= n; i++) if (rows[i] != "") {
      loc = substr(rows[i], 1, 16); utc = substr(rows[i], 18, 5); u[loc] = utc; ord[++k] = loc } }
    /upstream timed out/ { key = substr($0, 1, 16); if (key in u) c[key]++ }
    END { for (i = 1; i <= k; i++) print u[ord[i]] " upstream_timed_out=" (c[ord[i]] + 0) }
  ' "${ngx}"
else
  echo "(${ngx} not readable by this user; skipped)"
fi

# ── evidence summary ─────────────────────────────────────────────────
section "evidence summary (hints, not a verdict)"
svc_life="$(printf '%s\n' "${svc_journal}" | lifecycle_filter service)"
count() { printf '%s\n' "$1" | grep -cE -- "$2" || true; }
n_fail="$(count "${hc_lines}" 'LIVENESS FAIL')"
n_thresh="$(count "${hc_lines}" 'threshold reached')"
n_oom="$(count "${svc_life}${kern_lines:+$'\n'}${kern_lines}" 'OOM killer|oom-kill|Out of memory|Killed process|oom_reaper|systemd-oomd')"
n_stop_to="$(count "${svc_life}" "State 'stop-sigterm' timed out")"
n_exit="$(count "${svc_life}" 'Main process exited')"
n_start="$(count "${svc_life}" 'Started server process|systemd\[1\]: (Started|.*: Scheduled restart job)')"
echo "liveness_failures=${n_fail} watchdog_restarts=${n_thresh} oom_lines=${n_oom} stop_sigterm_timeouts=${n_stop_to} main_process_exits=${n_exit} start_lines=${n_start}"
if (( n_oom > 0 )); then
  echo "HINT: oom_kill — the kernel or systemd-oomd killed the process (see the lines above)."
elif (( n_thresh > 0 )); then
  echo "HINT: liveness_watchdog_restart — ${HEALTH_UNIT} saw ${n_fail} consecutive no-response probe(s) and restarted ${SERVICE_NAME}."
  (( n_stop_to > 0 )) && echo "HINT: the process did not exit within TimeoutStopSec after SIGTERM and was SIGKILLed (a wedged event loop does this)."
elif (( n_exit > 0 )); then
  echo "HINT: process_exit — read code=/status= on the 'Main process exited' line."
else
  echo "HINT: undetermined_in_window — widen the window or check journal retention."
fi

echo
if (( ${#REQUIRED_FAILED[@]} > 0 )); then
  printf 'prod_restart_diagnostics INCOMPLETE — %d required item(s) missing:\n' "${#REQUIRED_FAILED[@]}" >&2
  printf '  - %s\n' "${REQUIRED_FAILED[@]}" >&2
  exit 5
fi
echo "prod_restart_diagnostics complete (read-only; nothing was modified)."
exit 0
