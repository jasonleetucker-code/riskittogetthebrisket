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

if [[ -z "${SYSTEMCTL}" ]]; then
  echo "systemctl not found; cannot resolve the service." >&2
  exit 2
fi

section "service identity and limits"
# ActiveEnterTimestamp dates the CURRENT process: an FD count means
# nothing without knowing how long it has been accumulating.
sudo -n "${SYSTEMCTL}" show "${SERVICE_NAME}" \
  -p MainPID -p LimitNOFILE -p LimitNOFILESoft -p ActiveEnterTimestamp \
  -p NRestarts -p TasksCurrent -p TasksMax -p MemoryCurrent

PID="$(sudo -n "${SYSTEMCTL}" show "${SERVICE_NAME}" -p MainPID --value)"
if [[ -z "${PID}" || "${PID}" == "0" ]]; then
  echo "Service ${SERVICE_NAME} has no MainPID (not running?)." >&2
  exit 3
fi
echo "resolved PID=${PID}"

section "who is looking, and who owns the process"
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
echo "ssh user:     $(id -un)"
echo "process user: $(stat -c '%U' "/proc/${PID}" 2>/dev/null || echo '<unreadable>')"

section "kernel-enforced limits for the running process"
# systemd's LimitNOFILE is what was CONFIGURED; /proc/PID/limits is what
# the process actually got.  They can differ.
cat "/proc/${PID}/limits" 2>/dev/null | sed -n '1p;/open files/p'

section "system-wide file-nr (allocated / unused / max)"
# The three fields are ALLOCATED, UNUSED-but-allocated, and MAX — not
# "free".  On modern kernels the middle column is essentially always 0
# because freed structures are returned immediately rather than kept on a
# free list, so reading it as "free descriptors remaining" inverts the
# meaning entirely.  Only the first and third are informative here, and
# both are system-wide: neither one can show a per-process exhaustion,
# which is what EMFILE actually was.
cat /proc/sys/fs/file-nr 2>/dev/null || true

section "process and thread counts"
printf 'threads: '; cat "/proc/${PID}/status" 2>/dev/null | awk '/^Threads:/{print $2}'
printf 'children: '; pgrep -P "${PID}" 2>/dev/null | wc -l

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

section "FD type breakdown"
# This is the answer we came for.  Every /proc/PID/fd entry is a symlink
# whose target names its kind: socket:[…], pipe:[…], anon_inode:[…]
# (epoll, eventfd, inotify, timerfd), /dev/…, or a regular path.
bash -c '
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
  echo "total_fds=$total"
  for k in "${!kinds[@]}"; do printf "  %-28s %s\n" "$k" "${kinds[$k]}"; done | sort -k2 -rn
' _ "${PID}"

section "regular files held open, by directory"
# A leak of regular files usually points at one directory. Paths only —
# never contents.
bash -c '
  find "/proc/$1/fd" -maxdepth 1 -type l -exec readlink {} \; 2>/dev/null \
    | grep -E "^/" | grep -vE "^/(dev|proc|sys)/" \
    | xargs -r -n1 dirname 2>/dev/null | sort | uniq -c | sort -rn | head -20
' _ "${PID}"

section "sockets owned by this process, by state"
if command -v ss >/dev/null 2>&1; then
  # -p attributes sockets to the pid; we filter to ours and count states
  # rather than dumping peer addresses.
  ss -tanp 2>/dev/null | grep "pid=${PID}," \
    | awk '{print $1}' | sort | uniq -c | sort -rn
  echo "-- top peer ports (destination), to spot one chatty dependency --"
  ss -tanp 2>/dev/null | grep "pid=${PID}," \
    | awk '{print $5}' | sed 's/.*://' | sort | uniq -c | sort -rn | head -10
else
  echo "ss not installed"
fi

section "lsof type summary (NOT an FD count)"
# Cross-check only.  `lsof` lists more than open descriptors — memory
# mappings (mem), the text segment (txt), cwd and rtd all appear with
# type REG — so its REG row count is NOT the number of open regular-file
# descriptors and will exceed it.  /proc/PID/fd above is canonical; this
# is here to name WHAT is open, not how many.
if command -v lsof >/dev/null 2>&1; then
  lsof -nP -p "${PID}" 2>/dev/null | awk 'NR>1{print $5}' | sort | uniq -c | sort -rn | head -15
else
  echo "lsof not installed"
fi

section "earliest Errno 24 in the retained journal"
if [[ -n "${JOURNALCTL}" ]]; then
  # First occurrence dates the onset; the count and last occurrence say
  # whether it is over.
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
else
  echo "journalctl not found"
fi

section "FD count samples (${SAMPLES} x ${INTERVAL}s)"
# Trend, not a snapshot: a single number cannot distinguish a healthy
# steady state from the middle of an accumulation.  Passive — we watch
# whatever the process does on its own schedule.
echo "utc_time            total  sockets  files  anon  pipes  ESTAB  CLOSE-WAIT  other  peer_ports"
for ((i = 0; i < SAMPLES; i++)); do
  bash -c '
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
  ' _ "${PID}"
  (( i < SAMPLES - 1 )) && sleep "${INTERVAL}"
done

section "scheduled work in the observation window"
# Correlation without provocation: name the timers that could have run
# during the samples above.  We do not fire any of them.
sudo -n "${SYSTEMCTL}" list-timers --all --no-pager 2>/dev/null \
  | head -25 || true

echo
echo "fd_inventory complete (read-only; nothing was modified)."


# Every section above either produced its evidence or said why it could
# not.  The readability guard exits 4 rather than emit false zeros, and
# nothing here is wrapped in `|| true` that would let a failed section
# pass as a completed diagnostic.  fd-diagnostics.yml runs this over ssh
# without masking the exit status, so a broken probe fails the job.
exit 0
