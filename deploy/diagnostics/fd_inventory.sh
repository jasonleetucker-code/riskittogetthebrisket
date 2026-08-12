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

run_required() {
  local label="$1"; shift
  section "${label}"
  if "$@"; then
    return 0
  fi
  local rc=$?
  REQUIRED_FAILED+=("${label} (exit ${rc})")
  printf '[REQUIRED EVIDENCE MISSING] %s failed (exit %s)\n' "${label}" "${rc}" >&2
  # Keep going: one broken probe should not hide the others.  The exit
  # status at the bottom is what makes this fatal.
  return 0
}

run_optional() {
  local label="$1"; shift
  section "${label}"
  if "$@"; then
    return 0
  fi
  printf '[optional] %s unavailable (exit %s) — continuing\n' "${label}" "$?" >&2
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
  printf 'children: '; pgrep -P "${PID}" 2>/dev/null | wc -l
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
  find "/proc/$1/fd" -maxdepth 1 -type l -exec readlink {} \; 2>/dev/null \
    | grep -E "^/" | grep -vE "^/(dev|proc|sys)/" \
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
  # -p attributes sockets to the pid; we filter to ours and count states
  # rather than dumping peer addresses.
  ss -tanp 2>/dev/null | grep "pid=${PID}," | awk '{print $1}' | sort | uniq -c | sort -rn
  echo "-- top peer ports (destination), to spot one chatty dependency --"
  ss -tanp 2>/dev/null | grep "pid=${PID}," \
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
  ss -tanp 2>/dev/null | grep "pid=${PID}," | awk '$1=="CLOSE-WAIT"{print $5}' \
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
  sudo -n "${JOURNALCTL}" -u "${SERVICE_NAME}" --no-pager -o short-iso 2>/dev/null | head -1
}
run_optional "earliest Errno 24 in the retained journal" journal_errno24

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
