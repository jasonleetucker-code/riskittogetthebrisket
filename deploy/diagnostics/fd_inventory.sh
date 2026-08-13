#!/usr/bin/env bash
# Read-only file-descriptor evidence for the 2026-08-12 incident.
#
# On that date the production FastAPI process stopped answering.  The
# deploy's own journal capture showed why:
#
#     [ERROR] socket.accept() out of system resource
#     File "/usr/lib/python3.12/asyncio/selector_events.py", line 178,
#       in _accept_connection
#     File "/usr/lib/python3.12/socket.py", line 295, in accept
#     OSError: [Errno 24] Too many open files
#
# EMFILE at accept() explains the outside signature exactly: the kernel
# completes the TCP handshake into the listen backlog, so nginx connects
# in 0.4 ms, and the application can never accept the connection, so
# nginx waits its full 300 s proxy_read_timeout for bytes that never
# come.
#
# What is NOT established is WHAT accumulated.  "Descriptor leak" is a
# hypothesis until this script names the type.  That is the whole job
# here: inventory, not theory, and no application fix before the
# inventory says what grows.
#
# CONTRACT — this script is READ-ONLY.  It must never:
#   restart or reload a service, deploy, checkout, or write to the app
#   tree; import the application; run Sharp, scrapers, or any payload
#   build; trigger background work; or print environment variables,
#   command lines, or anything else that can carry a credential.
#
# It reads /proc, asks systemd for properties, lists sockets, and greps
# the journal.  Sampling is passive: it observes whatever the process is
# already doing on its own schedule and never provokes work.
#
# REQUIRED vs OPTIONAL EVIDENCE.  A diagnostic that reports success
# while answering nothing is worse than one that fails: the first
# privilege probe died on `BASH_SOURCE[0]: unbound variable` after its
# earlier sections had printed, and the job went green.  So every
# section is declared as one or the other:
#
#   run_required  — the evidence this script exists to produce.  It must
#                   both RUN and YIELD (a section that succeeds while
#                   printing nothing counts as failed).  Any failure is
#                   accumulated and makes the script exit 5.
#   run_optional  — corroborating detail, or a tool that may not be
#                   installed.  Degrades with an explicit line and does
#                   not affect the exit status.
#
# There is deliberately no unconditional `exit 0` at the end: the last
# statement is the verdict on the accumulator.
#
# Usage:
#   deploy/diagnostics/fd_inventory.sh [service] [samples] [interval_s]
#
# Defaults: dynasty, 10 samples, 30 s apart (a 5-minute window).

set -uo pipefail

SERVICE_NAME="${1:-${SERVICE_NAME:-dynasty}}"
SAMPLES="${2:-10}"
INTERVAL="${3:-30}"

SYSTEMCTL=""
for c in /bin/systemctl /usr/bin/systemctl; do
  [[ -x "$c" ]] && SYSTEMCTL="$c" && break
done
JOURNALCTL=""
for c in /bin/journalctl /usr/bin/journalctl; do
  [[ -x "$c" ]] && JOURNALCTL="$c" && break
done

section() { printf '\n===== %s =====\n' "$*"; }

REQUIRED_FAILED=()

# `rc=$?` must be captured from the CALL, not after an `if` compound:
# once `if … fi` completes without an else branch, `$?` is the compound's
# status, which is 0.  The first version read it there and reported every
# failure as "(exit 0)" — a diagnostic misreporting its own evidence.
run_required() {
  local label="$1"; shift
  section "${label}"
  local rc=0
  "$@" || rc=$?
  if (( rc == 0 )); then
    return 0
  fi
  REQUIRED_FAILED+=("${label} (exit ${rc})")
  printf '[REQUIRED EVIDENCE MISSING] %s failed (exit %s)\n' "${label}" "${rc}" >&2
  # Keep going: one broken probe should not hide the others.  The exit
  # status at the bottom is what makes this fatal.
  return 0
}

run_optional() {
  local label="$1"; shift
  section "${label}"
  local rc=0
  "$@" || rc=$?
  if (( rc != 0 )); then
    printf '[optional] %s unavailable (exit %s) — continuing\n' "${label}" "${rc}" >&2
  fi
  return 0
}

if [[ -z "${SYSTEMCTL}" ]]; then
  echo "systemctl not found; cannot resolve the service." >&2
  exit 2
fi

# ── required: service identity ──────────────────────────────────────
# ActiveEnterTimestamp dates the CURRENT process: an FD count means
# nothing without knowing how long it has been accumulating.
svc_identity() {
  local out
  out="$(sudo -n "${SYSTEMCTL}" show "${SERVICE_NAME}" \
    -p MainPID -p LimitNOFILE -p LimitNOFILESoft -p ActiveEnterTimestamp \
    -p NRestarts -p TasksCurrent -p TasksMax -p MemoryCurrent 2>&1)" || return 1
  printf '%s\n' "${out}"
  # Ran but yielded nothing usable — still a missing answer.
  [[ "${out}" == *MainPID=* ]] || return 1
}
run_required "service identity and limits" svc_identity

PID="$(sudo -n "${SYSTEMCTL}" show "${SERVICE_NAME}" -p MainPID --value)"
if [[ -z "${PID}" || "${PID}" == "0" ]]; then
  echo "Service ${SERVICE_NAME} has no MainPID (not running?)." >&2
  exit 3
fi
echo "resolved PID=${PID}"

# ── optional: identity cross-check ──────────────────────────────────
# The first run of this script failed here, usefully.  It used `sudo -n`
# for the /proc reads, and the host grants NOPASSWD sudo for exactly four
# binaries — systemctl, journalctl, install, chown — so `sudo -n cat`
# and `sudo -n bash` were refused ("sudo: a password is required") and
# the readability guard stopped the run.
#
# sudo was never needed: the service runs as `User=__APP_USER__` and the
# deploy connects as that same user, so it OWNS the process and can read
# /proc/PID/* directly.  sudo is now used only for the two allowlisted
# binaries.  Printing both identities makes that assumption checkable
# instead of load-bearing-and-invisible.
who_is_looking() {
  echo "ssh user:     $(id -un)"
  echo "process user: $(stat -c '%U' "/proc/${PID}" 2>/dev/null || echo '<unreadable>')"
}
run_optional "who is looking, and who owns the process" who_is_looking

# ── required: kernel-enforced limits ────────────────────────────────
# systemd's LimitNOFILE is what was CONFIGURED; /proc/PID/limits is what
# the process actually got.  They can differ, and EMFILE follows the
# process — so the kernel's answer is required evidence, not a nicety.
kernel_limits() {
  local out
  out="$(sed -n '1p;/open files/p' "/proc/${PID}/limits" 2>/dev/null)" || return 1
  printf '%s\n' "${out}"
  [[ "${out}" == *"Max open files"* ]] || return 1
}
run_required "kernel-enforced limits for the running process" kernel_limits

# ── optional: system-wide context ───────────────────────────────────
# The three fields are ALLOCATED, UNUSED-but-allocated, and MAX — not
# "free".  On modern kernels the middle column is essentially always 0
# because freed structures are returned immediately rather than kept on a
# free list, so reading it as "free descriptors remaining" inverts the
# meaning entirely.  Only the first and third are informative here, and
# both are system-wide: neither one can show a per-process exhaustion,
# which is what EMFILE actually was.  Hence optional.
run_optional "system-wide file-nr (allocated / unused / max)" \
  cat /proc/sys/fs/file-nr

proc_counts() {
  printf 'threads: '; awk '/^Threads:/{print $2}' "/proc/${PID}/status" 2>/dev/null
  # `pgrep` exits 1 when there are no children, which is a real answer
  # (0), not a failure — same distinction as the socket section.
  printf 'children: '; { pgrep -P "${PID}" 2>/dev/null || true; } | wc -l
}
run_optional "process and thread counts" proc_counts

# ── hard guard: readability ─────────────────────────────────────────
section "readability guard"
# A denied read of /proc/PID/fd makes `find -type l` yield NOTHING, and
# every count below would then report 0 — "the process holds no
# descriptors", which is not a possible state for a running server.  A
# zero that means "could not look" must never be presented as a
# measurement, so establish readability first and stop if it fails.
_probe="$(bash -c 'find "/proc/$1/fd" -maxdepth 1 -type l 2>/dev/null | wc -l' _ "${PID}")"
if [[ "${_probe}" -eq 0 ]]; then
  echo "Cannot read /proc/${PID}/fd (permission, or the process exited)." >&2
  echo "Every count below would be a false zero. Stopping." >&2
  exit 4
fi
echo "ok: /proc/${PID}/fd is readable (${_probe} entries on first look)"

# ── required: the answer we came for ────────────────────────────────
# Every /proc/PID/fd entry is a symlink whose target names its kind:
# socket:[…], pipe:[…], anon_inode:[…] (epoll, eventfd, inotify,
# timerfd), /dev/…, or a regular path.
fd_breakdown() {
  local out
  out="$(bash -c '
    pid="$1"
    total=0
    declare -A kinds
    while IFS= read -r link; do
      tgt="$(readlink "$link" 2>/dev/null)" || continue
      total=$((total+1))
      case "$tgt" in
        socket:*)      k="socket" ;;
        pipe:*)        k="pipe" ;;
        anon_inode:*)  k="anon_inode:${tgt#anon_inode:}" ;;
        /dev/*)        k="dev" ;;
        /proc/*)       k="proc" ;;
        /memfd:*)      k="memfd" ;;
        *)             k="file" ;;
      esac
      kinds["$k"]=$(( ${kinds["$k"]:-0} + 1 ))
    done < <(find "/proc/$pid/fd" -maxdepth 1 -type l 2>/dev/null)
    [[ "$total" -gt 0 ]] || exit 1
    echo "total_fds=$total"
    for k in "${!kinds[@]}"; do printf "  %-28s %s\n" "$k" "${kinds[$k]}"; done | sort -k2 -rn
  ' _ "${PID}")" || return 1
  printf '%s\n' "${out}"
}
run_required "FD type breakdown" fd_breakdown

# ── optional: where regular files live ──────────────────────────────
# A leak of regular files usually points at one directory.  Paths only —
# never contents.  Empty is a legitimate answer (this process holds ~1
# regular file), so this cannot be required evidence.
run_optional "regular files held open, by directory" bash -c '
  # `|| true` on the greps: holding no regular files is a real answer.
  find "/proc/$1/fd" -maxdepth 1 -type l -exec readlink {} \; 2>/dev/null \
    | { grep -E "^/" || true; } | { grep -vE "^/(dev|proc|sys)/" || true; } \
    | xargs -r -n1 dirname 2>/dev/null | sort | uniq -c | sort -rn | head -20
' _ "${PID}"

# ── required: socket states ─────────────────────────────────────────
# Required because sockets are what this process actually holds; the
# TOOL, though, may be absent, and an absent tool degrades explicitly
# rather than counting as a broken probe.
socket_states() {
  if ! command -v ss >/dev/null 2>&1; then
    echo "ss not installed — socket state unavailable on this host"
    return 0
  fi
  # COULD NOT LOOK vs LOOKED AND FOUND NONE.  Only the first is a broken
  # probe.  `grep` exits 1 on no matches, and under `pipefail` that makes
  # the whole pipeline non-zero, so the naive one-liner reported a
  # process with no TCP sockets as a failed required section.  The live
  # backend always has sockets so it never fired there — which is exactly
  # why it has to be handled rather than left to chance.
  local rows mine
  rows="$(ss -tanp 2>/dev/null)" || return 1   # the tool itself failed
  mine="$(printf '%s\n' "${rows}" | grep "pid=${PID}," || true)"
  if [[ -z "${mine}" ]]; then
    echo "no TCP sockets attributed to pid ${PID}"
    return 0
  fi
  # -p attributes sockets to the pid; we count states rather than dumping
  # peer addresses.
  printf '%s\n' "${mine}" | awk '{print $1}' | sort | uniq -c | sort -rn
  echo "-- top peer ports (destination), to spot one chatty dependency --"
  printf '%s\n' "${mine}" \
    | awk '{print $5}' | sed 's/.*://' | sort | uniq -c | sort -rn | head -10
  # DESTINATION ADDRESSES, for CLOSE-WAIT only.
  #
  # This script previously counted states "rather than dumping peer
  # addresses", which was the right default while the question was "how
  # many".  The question is now "which dependency", and a port number of
  # 443 cannot answer it: every outbound HTTPS call in the process looks
  # identical.  Scope is narrowed rather than widened — CLOSE-WAIT rows
  # only, deduplicated, capped — and these are the public API endpoints
  # this service calls by design, not user or credential data.
  echo "-- distinct CLOSE-WAIT peers (destination address) --"
  printf '%s\n' "${mine}" | awk '$1=="CLOSE-WAIT"{print $5}' \
    | sort | uniq -c | sort -rn | head -8
}
run_required "sockets owned by this process, by state" socket_states

# ── optional: lsof cross-check ──────────────────────────────────────
# `lsof` lists more than open descriptors — memory mappings (mem), the
# text segment (txt), cwd and rtd all appear with type REG — so its REG
# row count is NOT the number of open regular-file descriptors and will
# exceed it.  /proc/PID/fd above is canonical; this is here to name WHAT
# is open, not how many.
lsof_summary() {
  if ! command -v lsof >/dev/null 2>&1; then
    echo "lsof not installed"
    return 0
  fi
  lsof -nP -p "${PID}" 2>/dev/null | awk 'NR>1{print $5}' | sort | uniq -c | sort -rn | head -15
}
run_optional "lsof type summary (NOT an FD count)" lsof_summary

# ── optional: journal history ───────────────────────────────────────
# Optional because journal retention is a host policy: "no Errno 24 in
# the retained journal" is a real answer, not a broken probe.
journal_errno24() {
  if [[ -z "${JOURNALCTL}" ]]; then
    echo "journalctl not found"
    return 0
  fi
  # First occurrence dates the onset; the count and last occurrence say
  # whether it is over.
  local first last cnt
  first="$(sudo -n "${JOURNALCTL}" -u "${SERVICE_NAME}" --no-pager -o short-iso 2>/dev/null \
    | grep -m1 'Errno 24' || true)"
  echo "first: ${first:-<none in retained journal>}"
  last="$(sudo -n "${JOURNALCTL}" -u "${SERVICE_NAME}" --no-pager -o short-iso 2>/dev/null \
    | grep 'Errno 24' | tail -1 || true)"
  echo "last:  ${last:-<none>}"
  cnt="$(sudo -n "${JOURNALCTL}" -u "${SERVICE_NAME}" --no-pager 2>/dev/null \
    | grep -c 'Errno 24' || true)"
  echo "count: ${cnt:-0}"
  echo "-- journal retention window --"
  sudo -n "${JOURNALCTL}" -u "${SERVICE_NAME}" --no-pager -o short-iso -n 1 2>/dev/null | tail -1
  # `head -1` closes the pipe on a journal that is still streaming, so
  # journalctl dies of SIGPIPE and `pipefail` reports 141 — a spurious
  # non-zero on a section that printed its evidence correctly.  Read the
  # whole stream and take the first line in the shell instead, so the
  # status reflects the journal, not the reader.
  local oldest rc=0
  oldest="$(sudo -n "${JOURNALCTL}" -u "${SERVICE_NAME}" --no-pager -o short-iso 2>/dev/null)" || rc=$?
  printf '%s\n' "${oldest}" | sed -n '1p'
  # A journalctl that genuinely failed still degrades this optional
  # section; only the reader's SIGPIPE is gone.
  return "${rc}"
}
run_optional "earliest Errno 24 in the retained journal" journal_errno24

# ── optional: the watchdog, read directly ───────────────────────────
# The DEPLOY gate verifies these; this reads them independently so the
# two are not the same statement twice.
#
# Both NextElapse properties are printed, deliberately.  The unit ships
# `OnBootSec` + `OnUnitActiveSec`, which are MONOTONIC bases, so
# systemd computes `NextElapseUSecMonotonic`; `NextElapseUSecRealtime`
# is the CALENDAR next-elapse and is zero for a timer with no calendar
# event.  Reading only the realtime field is how a correctly scheduled
# timer reads as "no next activation".
watchdog_state() {
  local timer="dynasty-healthcheck.timer" svc="dynasty-healthcheck.service"
  local prop
  for prop in LoadState ActiveState UnitFileState \
              NextElapseUSecRealtime NextElapseUSecMonotonic LastTriggerUSec; do
    printf '%-26s %s\n' "timer.${prop}" \
      "$(sudo -n "${SYSTEMCTL}" show "${timer}" -p "${prop}" --value 2>/dev/null)"
  done
  printf '%-26s %s\n' "service.LoadState" \
    "$(sudo -n "${SYSTEMCTL}" show "${svc}" -p LoadState --value 2>/dev/null)"

  local installed="${RISKIT_LIB_DIR:-/usr/local/lib/riskit}/dynasty-healthcheck.sh"
  if [[ -r "${installed}" ]]; then
    printf '%-26s %s\n' "watchdog.path" "${installed}"
    printf '%-26s %s\n' "watchdog.owner" "$(stat -c '%U:%G' "${installed}")"
    printf '%-26s %s\n' "watchdog.mode" "$(stat -c '%a' "${installed}")"
    local th
    for th in 'FD_WARN:-256' 'FD_CRIT:-512' 'FD_EMERG:-768'; do
      if grep -q "${th}" "${installed}"; then
        printf '%-26s %s\n' "watchdog.${th%%:*}" "present (${th#*:-})"
      else
        printf '%-26s %s\n' "watchdog.${th%%:*}" "MISSING"
      fi
    done
  else
    printf '%-26s %s\n' "watchdog.path" "${installed} (unreadable)"
  fi
}
run_optional "watchdog units and installed executable" watchdog_state

# ── optional: the timer contract ACROSS a firing boundary ───────────
# `watchdog_state` above reads the timer once.  One read cannot see the
# state that matters here: while the triggered oneshot is executing,
# systemd has no next activation to report and answers
# `NextElapseUSecMonotonic=infinity`.  A verifier that samples once
# therefore passes or fails on where its read landed relative to a
# 60-second cadence.
#
# So this samples the whole tuple every second for longer than one
# period, which guarantees crossing at least one boundary, and prints
# every sample rather than a summary — the transition IS the evidence.
#
# `TimersMonotonic` is the property that distinguishes "no next
# activation because the unit is running right now" from "no next
# activation because this timer has no recurring schedule": it lists the
# monotonic timer definitions systemd actually loaded, so it is present
# for a healthy timer whatever its momentary next-elapse says.  It is
# read live rather than inferred from the unit file in the repository,
# because what shipped and what is loaded are different claims.
#
# Still read-only: `systemctl show` computes nothing and starts nothing.
WATCHDOG_CONTRACT_SAMPLES="${WATCHDOG_CONTRACT_SAMPLES:-75}"

watchdog_timer_contract() {
  local timer="dynasty-healthcheck.timer" svc="dynasty-healthcheck.service"
  local prop
  for prop in Unit TimersMonotonic TimersCalendar AccuracyUSec RandomizedDelayUSec; do
    printf '%-30s %s\n' "timer.${prop}" \
      "$(sudo -n "${SYSTEMCTL}" show "${timer}" -p "${prop}" --value 2>/dev/null)"
  done
  for prop in Type TimeoutStartUSec ActiveState SubState Result; do
    printf '%-30s %s\n' "service.${prop}" \
      "$(sudo -n "${SYSTEMCTL}" show "${svc}" -p "${prop}" --value 2>/dev/null)"
  done

  printf '\nsampling %s x 1s (cadence is 60s, so this crosses a boundary)\n\n' \
    "${WATCHDOG_CONTRACT_SAMPLES}"
  printf '%-21s %-8s %-10s %-30s %s\n' \
    utc_time timer.Act svc.Act/Sub next_monotonic last_trigger
  local i timer_out svc_out t_active next_mono last_trig s_active s_sub
  for ((i = 0; i < WATCHDOG_CONTRACT_SAMPLES; i++)); do
    timer_out="$(sudo -n "${SYSTEMCTL}" show "${timer}" \
      -p ActiveState -p NextElapseUSecMonotonic -p LastTriggerUSec 2>/dev/null)"
    svc_out="$(sudo -n "${SYSTEMCTL}" show "${svc}" \
      -p ActiveState -p SubState 2>/dev/null)"
    t_active="$(printf '%s\n' "${timer_out}" | sed -n 's/^ActiveState=//p')"
    next_mono="$(printf '%s\n' "${timer_out}" | sed -n 's/^NextElapseUSecMonotonic=//p')"
    last_trig="$(printf '%s\n' "${timer_out}" | sed -n 's/^LastTriggerUSec=//p')"
    s_active="$(printf '%s\n' "${svc_out}" | sed -n 's/^ActiveState=//p')"
    s_sub="$(printf '%s\n' "${svc_out}" | sed -n 's/^SubState=//p')"
    printf '%-21s %-8s %-10s %-30s %s\n' \
      "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${t_active:-<empty>}" \
      "${s_active:-?}/${s_sub:-?}" "${next_mono:-<empty>}" "${last_trig:-<empty>}"
    sleep 1
  done
}
run_optional "watchdog timer contract across a firing boundary" watchdog_timer_contract

# ── required: the trend ─────────────────────────────────────────────
# A single number cannot distinguish a healthy steady state from the
# middle of an accumulation.  Passive — we watch whatever the process
# does on its own schedule.  Every sample must produce a row: a run that
# silently emits fewer than it promised is a shorter window than the
# reader thinks it is reading.
fd_samples() {
  local emitted=0 i row
  echo "utc_time            total  sockets  files  anon  pipes  ESTAB  CLOSE-WAIT  other  peer_ports"
  for ((i = 0; i < SAMPLES; i++)); do
    if row="$(bash -c '
      pid="$1"
      t=0; s=0; f=0; a=0; p=0
      while IFS= read -r link; do
        tgt="$(readlink "$link" 2>/dev/null)" || continue
        t=$((t+1))
        case "$tgt" in
          socket:*) s=$((s+1)) ;;
          pipe:*) p=$((p+1)) ;;
          anon_inode:*) a=$((a+1)) ;;
          /*) f=$((f+1)) ;;
        esac
      done < <(find "/proc/$pid/fd" -maxdepth 1 -type l 2>/dev/null)
      # A zero total here means the read failed or the process exited —
      # never a real measurement.  Same false-zero rule as the guard.
      [[ "$t" -gt 0 ]] || exit 1
      # TCP state per sample.  A run on 2026-08-12 22:00 showed 9 sockets
      # that had been ESTAB an hour earlier sitting in CLOSE-WAIT, all to
      # :443.  CLOSE-WAIT means the PEER closed and this process has not
      # closed its end — i.e. a descriptor held open by the application.
      # Whether that count is bounded or accumulates is the difference
      # between "normal churn" and a named accumulation source, so every
      # sample records it rather than the total alone.
      est=0; cw=0; oth=0; ports="-"
      if command -v ss >/dev/null 2>&1; then
        states="$(ss -tanp 2>/dev/null | grep "pid=$pid," | awk "{print \$1}")"
        est=$(printf "%s\n" "$states" | grep -c "^ESTAB$" || true)
        cw=$(printf "%s\n" "$states" | grep -c "^CLOSE-WAIT$" || true)
        oth=$(printf "%s\n" "$states" | grep -vcE "^(ESTAB|CLOSE-WAIT)$" || true)
        ports="$(ss -tanp 2>/dev/null | grep "pid=$pid," | awk "{print \$5}" \
                 | sed "s/.*://" | sort | uniq -c | sort -rn \
                 | head -3 | awk "{printf \"%sx%s \", \$1, \$2}")"
      fi
      printf "%s  %5d  %7d  %5d  %5d  %5d  %5s  %10s  %5s  %s\n" \
        "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$t" "$s" "$f" "$a" "$p" \
        "$est" "$cw" "$oth" "${ports:--}"
    ' _ "${PID}")"; then
      printf '%s\n' "${row}"
      emitted=$((emitted + 1))
    else
      printf '[sample %d] could not read /proc/%s/fd\n' "$((i + 1))" "${PID}" >&2
    fi
    if (( i < SAMPLES - 1 )); then sleep "${INTERVAL}"; fi
  done
  if (( emitted < SAMPLES )); then
    printf 'only %d of %d samples produced a row\n' "${emitted}" "${SAMPLES}" >&2
    return 1
  fi
  return 0
}
run_required "FD count samples (${SAMPLES} x ${INTERVAL}s)" fd_samples

# ── optional: correlation without provocation ───────────────────────
# Name the timers that could have run during the samples above.  We do
# not fire any of them.
run_optional "scheduled work in the observation window" bash -c \
  'sudo -n "$1" list-timers --all --no-pager 2>/dev/null | head -25' _ "${SYSTEMCTL}"

# Same reading, after the window: which peers still hold descriptors at
# the end tells you whether the CLOSE-WAIT set turned over or is the
# same sockets throughout.
run_optional "socket states and peers AFTER the sample window" socket_states

# ── verdict ─────────────────────────────────────────────────────────
# The LAST statement, and it is conditional.  An unconditional `exit 0`
# here would override every failure above — which is precisely the
# false-green this model exists to prevent.
echo
if (( ${#REQUIRED_FAILED[@]} > 0 )); then
  printf 'fd_inventory INCOMPLETE — %d required section(s) produced no evidence:\n' \
    "${#REQUIRED_FAILED[@]}" >&2
  printf '  - %s\n' "${REQUIRED_FAILED[@]}" >&2
  echo "A diagnostic that could not gather its required evidence has not" >&2
  echo "answered the question it was dispatched for. Failing the run." >&2
  exit 5
fi
echo "fd_inventory complete (read-only; nothing was modified)."
exit 0
