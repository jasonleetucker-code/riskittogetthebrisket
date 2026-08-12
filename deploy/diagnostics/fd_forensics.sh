#!/usr/bin/env bash
# Bounded historical forensics for the 2026-08-12 EMFILE incident.
#
# The exhausted process (default PID 887292) is gone, so this reads the
# journal it left behind.  One pass, one question: what was the
# application DOING in the ~20 minutes before its first
# `OSError: [Errno 24] Too many open files`.
#
# Established already, and not re-litigated here:
#   - EMFILE at socket.accept() wedged the process (proven)
#   - soft LimitNOFILE was 1024, hard 524288
#   - the replacement process sits at ~16 FDs, flat
#   - 1,212 Errno 24 events from PID 887292; first at 16:47:46 CEST
#
# NOT established: what accumulated.  If this pass names no defensible
# suspect, the search stops — the process is gone and no amount of
# staring reconstructs a descriptor table nobody captured.
#
# READ-ONLY.  Same contract as fd_inventory.sh: journal reads and
# nothing else.  No restart, no deploy, no application import, no
# background work triggered, no environment printed.
#
# Usage:
#   fd_forensics.sh [service] [old_pid] [first_emfile_local] [lead_minutes]
# e.g.
#   fd_forensics.sh dynasty 887292 "2026-08-12 16:47:46" 20

set -uo pipefail

SERVICE_NAME="${1:-dynasty}"
OLD_PID="${2:-887292}"
FIRST_EMFILE="${3:-2026-08-12 16:47:46}"
LEAD_MIN="${4:-20}"

JOURNALCTL=""
for c in /bin/journalctl /usr/bin/journalctl; do
  [[ -x "$c" ]] && JOURNALCTL="$c" && break
done
[[ -n "${JOURNALCTL}" ]] || { echo "journalctl not found" >&2; exit 2; }

J() { sudo -n "${JOURNALCTL}" "$@" 2>/dev/null; }
section() { printf '\n===== %s =====\n' "$*"; }

# Journal timestamps are host-local; keep every window in the same
# vocabulary rather than converting and risking an off-by-two-hours.
SINCE="$(date -d "${FIRST_EMFILE} -${LEAD_MIN} min" '+%Y-%m-%d %H:%M:%S' 2>/dev/null)"
UNTIL="$(date -d "${FIRST_EMFILE} +2 min" '+%Y-%m-%d %H:%M:%S' 2>/dev/null)"
if [[ -z "${SINCE}" ]]; then
  echo "Could not parse FIRST_EMFILE='${FIRST_EMFILE}'" >&2
  exit 3
fi
echo "service=${SERVICE_NAME} old_pid=${OLD_PID}"
echo "window: ${SINCE}  ->  ${UNTIL}  (local time, ${LEAD_MIN}m lead)"

section "lifetime of the exhausted process"
# _PID= is an indexed journal field, so this is exact rather than a grep.
echo "-- first retained line for PID ${OLD_PID} --"
J _PID="${OLD_PID}" -o short-iso --no-pager | head -3
echo "-- last line for PID ${OLD_PID} --"
J _PID="${OLD_PID}" -o short-iso --no-pager | tail -3
echo "-- total retained lines for that PID --"
J _PID="${OLD_PID}" --no-pager | wc -l

section "EMFILE onset"
echo "-- first 5 Errno 24 lines, with timestamps --"
J _PID="${OLD_PID}" -o short-iso --no-pager | grep -n 'Errno 24' | head -5
echo "-- what the 20 lines BEFORE the first Errno 24 say --"
# The lines immediately preceding exhaustion are the highest-value
# evidence in the whole pass: whatever was running when the last
# descriptor went.
J _PID="${OLD_PID}" -o short-iso --no-pager \
  | awk '/Errno 24/{exit} {buf[NR]=$0} END{for(i=(NR>20?NR-19:1);i<=NR;i++) print buf[i]}'

section "application activity in the lead window"
echo "-- line volume per minute (a burst is a lead) --"
J -u "${SERVICE_NAME}" --since "${SINCE}" --until "${UNTIL}" -o short-iso --no-pager \
  | awk '{split($1,a,"T"); split(a[2],b,":"); print a[1]"T"b[1]":"b[2]}' \
  | uniq -c | tail -30

section "resource families named in the lead window"
# Counts only — one line per family, so a runaway is obvious without
# dumping the log.  These are the families worth suspecting for a
# descriptor accumulation in this codebase.
declare -A PATTERNS=(
  [scrape/pool-build]='scrape|pool|contract build|build_api_data|rebuild'
  [sleeper-api]='sleeper|api\.sleeper'
  [external-sources]='ktc|dynastydaddy|fantasycalc|dlf|idptradecalc|idpshow|fantasypros|yahoo|otcffb|flock'
  [public-league-snapshot]='public_league|public-league|snapshot'
  [sharp]='sharp|ffpc|cohort|roster_collect'
  [playwright/browser]='playwright|chromium|browser|headless'
  [subprocess]='subprocess|Popen|spawn'
  [http-retry]='retry|retrying|backoff|timeout|timed out'
  [connection-errors]='ConnectionError|ConnectionReset|RemoteDisconnected|SSLError|Max retries'
  [session-construction]='new session|Session\(|client created|connector'
  [bdvm]='bdvm|projection'
  [warnings]='WARNING|ERROR|Traceback'
)
for k in "${!PATTERNS[@]}"; do
  n="$(J -u "${SERVICE_NAME}" --since "${SINCE}" --until "${UNTIL}" --no-pager \
        | grep -icE "${PATTERNS[$k]}" || true)"
  printf '  %-24s %s\n' "$k" "${n:-0}"
done

section "most repeated message shapes in the lead window"
# Strip timestamps/pids/numbers so identical messages collapse; a leak
# usually shows up as one line repeated thousands of times.
J -u "${SERVICE_NAME}" --since "${SINCE}" --until "${UNTIL}" --no-pager \
  | sed -E 's/^[A-Za-z]{3} [0-9 ]{2} [0-9:]{8} [^ ]+ [^:]+: //' \
  | sed -E 's/[0-9]+/N/g' \
  | sort | uniq -c | sort -rn | head -15

section "scheduled units that ran near the onset"
# Correlation, not provocation — nothing is started here.
J --since "${SINCE}" --until "${UNTIL}" -o short-iso --no-pager \
  | grep -iE 'systemd\[1\].*(Starting|Started|Finished)' \
  | grep -viE "${SERVICE_NAME}\.service" \
  | head -30

section "the service's own restarts around the incident"
J -u "${SERVICE_NAME}" -o short-iso --no-pager \
  | grep -iE 'Started|Stopped|Main process exited|Failed with result|Consumed' \
  | tail -20

echo
echo "fd_forensics complete (read-only; nothing was modified)."
