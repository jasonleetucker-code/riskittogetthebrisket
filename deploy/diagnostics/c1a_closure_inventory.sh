#!/usr/bin/env bash
#
# C1A unit 1 closure inventory — READ ONLY.
#
# Answers two questions that the backup/restore proof deliberately cannot,
# because they are about state the proof does not touch:
#
#   A. THE NIGHTLY LINEAGE.  `deploy/apply_hardening.sh` installs root-owned
#      copies under /usr/local/lib/riskit/ and ordinary deploys do NOT run it
#      (pinned by tests/deploy/test_hardening_script_stays_operator_run.py).
#      So "the deployed checkout is fixed" and "the nightly writer is fixed"
#      are two different facts, and only the first is evidence a deploy can
#      produce.  This reports the second by hashing what is actually
#      installed against what is actually deployed.
#
#   B. THE PLAYERCTX PUBLICATION PATH (C1-RET-08).  /api/status reports
#      pendingPush=2, i.e. both retained snapshots exist locally and neither
#      has ever been committed.  The producer and the pusher fail
#      independently; this reports the pusher's unit state, working
#      directory, last result and journal so the failure is measured rather
#      than hypothesised.
#
# WHAT THIS SCRIPT WILL NOT DO.  It never writes, installs, enables, starts,
# commits or pushes anything.  Every command is an inspection.  Fixing what
# it finds is a separate, explicitly authorised action — a diagnostic that
# repairs its subject destroys the evidence it was run to collect.
#
# PRIVACY.  Emits unit metadata, file hashes, and DATED FILENAMES only.  It
# never prints a snapshot's contents, a league payload, a roster, a manager
# name, or any key material — `test -r` answers "can the pusher read the
# key" without revealing it.  Journal tails are scoped to a named unit and
# capped.
#
# Usage (matches the sibling diagnostics):
#   APP_DIR=... SERVICE_NAME=... bash -s < deploy/diagnostics/c1a_closure_inventory.sh
#
# Exit codes:
#   0  inventory completed — read the report, it may still describe a defect
#   1  the inventory itself could not run (bad APP_DIR, no bash, etc.)
#
# An absent object is reported ABSENT and an unreadable one UNREADABLE.  They
# are different facts and collapsing them is the exact bug class #852 exists
# to remove, so this script keeps them apart too.

set -Eeuo pipefail

APP_DIR="${APP_DIR:-/home/dynasty/trade-calculator}"
SERVICE_NAME="${SERVICE_NAME:-dynasty}"
LIB_DIR="${RISKIT_PRIV_LIB_DIR:-/usr/local/lib/riskit}"
JOURNAL_LINES="${JOURNAL_LINES:-40}"

# This branch deliberately precedes every legacy output/helper invocation.
# It is a single metadata snapshot, not resource/credential acceptance.
case "${INVENTORY_SCOPE:-closure}" in
performance-safe)
    [[ "${SERVICE_NAME}" =~ ^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$ ]] || { echo 'inventory_error=invalid_service'; exit 1; }
    [[ "${APP_DIR}" =~ ^/[a-zA-Z0-9_./-]+$ && "/${APP_DIR}/" != *'/../'* && -d "${APP_DIR}" ]] || { echo 'inventory_error=invalid_app'; exit 1; }
    safe_number() {
        local label="$1" value="$2"
        if [[ "${value}" =~ ^[0-9]{1,24}$ || "${value}" == infinity ]]; then
            printf '%s=%s\n' "${label}" "${value}"
        else
            printf '%s=unavailable\n' "${label}"
        fi
    }
    printf 'scope=performance-safe\n'
    printf 'timestamp=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    revision="$(git -C "${APP_DIR}" rev-parse --verify HEAD 2>/dev/null || true)"
    if [[ "${revision}" =~ ^[a-fA-F0-9]{40}$ ]]; then printf 'revision=%s\n' "${revision}"; else echo 'revision=unavailable'; fi
    for metric in MemTotal MemAvailable; do
        safe_number "host.${metric}KiB" "$(awk -v key="${metric}:" '$1==key {print $2}' /proc/meminfo 2>/dev/null || true)"
    done
    safe_number host.logicalCPUs "$(getconf _NPROCESSORS_ONLN 2>/dev/null || true)"
    safe_number host.fileMax "$(cat /proc/sys/fs/file-max 2>/dev/null || true)"
    # Fixed role paths only. stat reports numbers, never target paths/content.
    for role in app store; do
        target="${APP_DIR}"
        [[ "${role}" != store ]] || target="${APP_DIR}/data/private_serving"
        if [[ -e "${target}" ]]; then
            for spec in 'owner:%u' 'group:%g' 'mode:%a'; do
                safe_number "${role}.${spec%%:*}" "$(stat -c "${spec#*:}" -- "${target}" 2>/dev/null || true)"
            done
            for spec in 'blockSize:%S' 'blocks:%b' 'availableBlocks:%a'; do
                safe_number "${role}.${spec%%:*}" "$(stat -f -c "${spec#*:}" -- "${target}" 2>/dev/null || true)"
            done
        else
            printf '%s.state=absent_or_inaccessible\n' "${role}"
        fi
    done
    for suffix in '.service' '-frontend.service' '-source-producer.service' '-source-producer.timer' '-source-producer.path' '-league-serving.service' '-league-serving.timer' '-league-serving.path' '-prepared-news.service' '-dlf-fetch.service' '-dlf-fetch.timer' '-idpshow-fetch.service' '-idpshow-fetch.timer' 'nginx.service'; do
        unit="${SERVICE_NAME}${suffix}"
        [[ "${suffix}" != nginx.service ]] || unit=nginx.service
        properties='LoadState ActiveState SubState UnitFileState MainPID User Group MemoryCurrent MemoryPeak MemoryHigh MemoryMax TasksCurrent TasksMax LimitNOFILE CPUUsageNSec ExecMainStatus NRestarts'
        if [[ "${suffix}" == '-dlf-fetch.service' ]]; then
            properties+=' Result ExecMainCode ExecMainStartTimestamp ExecMainExitTimestamp ExecMainStartTimestampMonotonic ExecMainExitTimestampMonotonic'
        fi
        for property in ${properties}; do
            if value="$(LC_ALL=C TZ=UTC systemctl show "${unit}" --property="${property}" --value 2>/dev/null)"; then
                case "${property}" in
                    LoadState) pattern='^(loaded|not-found|masked|error|bad-setting|merged|stub)$' ;;
                    ActiveState) pattern='^(active|inactive|failed|activating|deactivating|reloading|maintenance|refreshing)$' ;;
                    SubState) pattern='^(running|dead|exited|waiting|listening|failed|auto-restart|start|stop|start-pre|start-post|stop-sigterm|stop-post)$' ;;
                    UnitFileState) pattern='^(enabled|disabled|static|masked|indirect|generated|transient|alias|enabled-runtime|masked-runtime|linked|linked-runtime)$' ;;
                    User|Group) pattern='^[a-zA-Z0-9_][a-zA-Z0-9_-]{0,63}$' ;;
                    Result) pattern='^(success|resources|timeout|exit-code|signal|core-dump|watchdog|start-limit-hit|protocol|exec-condition|oom-kill)$' ;;
                    ExecMainStartTimestamp|ExecMainExitTimestamp) pattern='^(Mon|Tue|Wed|Thu|Fri|Sat|Sun) [0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2} UTC$' ;;
                    *) pattern='^([0-9]{1,24}|infinity)$' ;;
                esac
                if [[ "${value}" =~ ${pattern} ]]; then
                    printf 'unit.%s.%s=%s\n' "${unit}" "${property}" "${value}"
                else
                    printf 'unit.%s.%s=unavailable\n' "${unit}" "${property}"
                fi
            else
                printf 'unit.%s.%s=probe_failed\n' "${unit}" "${property}"
            fi
        done
    done
    # Fixed public source outputs only, never environment/session/key material.
    # Monotonic unit timestamps above are boot-relative, not UTC epochs.
    if command -v python3 >/dev/null 2>&1 && command -v timeout >/dev/null 2>&1; then
        if dlf_output=$( { timeout -k 1s 15s python3 - "${APP_DIR}" <<'DLF_METADATA_PY'
import csv
import hashlib
import io
import os
from pathlib import Path
import re
import stat
import sys

BOARDS = ("dlfSf", "dlfIdp", "dlfRookieSf", "dlfRookieIdp")

def read_bounded(root, relative, maximum):
    path = root
    try:
        if root.resolve() != root.absolute():
            return "unsafe_path", None, None
        for part in relative.parts:
            path = path / part
            if path.is_symlink():
                return "unsafe_path", None, None
        mode = path.lstat().st_mode
        if not stat.S_ISREG(mode):
            return "not_regular", None, None
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        with os.fdopen(os.open(path, flags), "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode):
                return "not_regular", None, None
            if before.st_size > maximum:
                return "oversize", None, None
            data = stream.read(maximum + 1)
            after = os.fstat(stream.fileno())
        if len(data) > maximum:
            return "oversize", None, None
        if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
            return "changed_during_read", None, None
        return "read", data, after
    except FileNotFoundError:
        return "missing", None, None
    except PermissionError:
        return "inaccessible", None, None
    except OSError:
        return "probe_failed", None, None

print("dlf.dedicated_path=assumed_default")
for role, root in (("live", Path(sys.argv[1])), ("dedicated", Path("/var/lib/dlf-fetch/repo"))):
    for board in BOARDS:
        label = "dlf." + role + "." + board
        state, data, info = read_bounded(root, Path("CSVs/site_raw") / (board + ".csv"), 2097152)
        print(label + ".state=" + state)
        if data is None:
            continue
        print(label + ".bytes=" + str(len(data)))
        print(label + ".sha256=" + hashlib.sha256(data).hexdigest())
        print(label + ".mtimeNs=" + str(max(0, info.st_mtime_ns)))
        try:
            reader = csv.reader(io.StringIO(data.decode("utf-8-sig")), strict=True)
            header = next(reader, [])
            rows = 0
            for row in reader:
                if row:
                    rows += 1
                if rows > 10000:
                    raise ValueError()
            print(label + ".matchesCurrentWriterSchema=" + str(int(header == ["name", "rank", "value"])))
            print(label + ".rows=" + str(rows))
        except (UnicodeError, csv.Error, ValueError):
            print(label + ".csvState=invalid_or_over_limit")
    for key in ("dlf",) + BOARDS:
        label = "dlf." + role + "." + key
        state, data, _ = read_bounded(root, Path("data/scrape_state") / (key + "_last_success"), 64)
        if data is not None:
            value = data.strip()
            if re.fullmatch(rb"[0-9]{10,12}", value):
                print(label + ".lastSuccessEpoch=" + value.decode("ascii"))
                continue
            state = "invalid_epoch"
        print(label + ".stampState=" + state)
DLF_METADATA_PY
        } 2>/dev/null | head -c 8193); then
            dlf_valid=1
            [[ ${#dlf_output} -le 8192 && -n "$dlf_output" ]] || dlf_valid=0
            while IFS= read -r line; do
                if [[ "$line" == 'dlf.dedicated_path=assumed_default' ]]; then
                    continue
                fi
                if [[ ! "$line" =~ ^dlf\.(live|dedicated)\.(dlf|dlfSf|dlfIdp|dlfRookieSf|dlfRookieIdp)\.(state|stampState)=(read|unsafe_path|not_regular|oversize|changed_during_read|missing|inaccessible|probe_failed|invalid_epoch)$ &&
                      ! "$line" =~ ^dlf\.(live|dedicated)\.(dlfSf|dlfIdp|dlfRookieSf|dlfRookieIdp)\.(bytes|mtimeNs|rows)=[0-9]{1,20}$ &&
                      ! "$line" =~ ^dlf\.(live|dedicated)\.(dlfSf|dlfIdp|dlfRookieSf|dlfRookieIdp)\.matchesCurrentWriterSchema=[01]$ &&
                      ! "$line" =~ ^dlf\.(live|dedicated)\.(dlfSf|dlfIdp|dlfRookieSf|dlfRookieIdp)\.sha256=[0-9a-f]{64}$ &&
                      ! "$line" =~ ^dlf\.(live|dedicated)\.(dlf|dlfSf|dlfIdp|dlfRookieSf|dlfRookieIdp)\.lastSuccessEpoch=[0-9]{10,12}$ &&
                      ! "$line" =~ ^dlf\.(live|dedicated)\.(dlfSf|dlfIdp|dlfRookieSf|dlfRookieIdp)\.csvState=invalid_or_over_limit$ ]]; then
                    dlf_valid=0
                fi
            done <<< "$dlf_output"
            if [[ "$dlf_valid" == 1 ]]; then
                printf '%s\n' "$dlf_output"
            else
                echo 'dlf.metadata=probe_failed'
            fi
        else
            echo 'dlf.metadata=probe_failed'
        fi
    else
        echo 'dlf.metadata=python_or_timeout_unavailable'
    fi
    # Invocation-scoped journal classification. Raw messages never leave Python.
    if command -v python3 >/dev/null 2>&1 && command -v timeout >/dev/null 2>&1; then
        if journal_output=$( { timeout -k 1s 25s python3 - "${APP_DIR}" "${SERVICE_NAME}-dlf-fetch.service" <<'DLF_JOURNAL_PY'
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import threading

def bounded(args, limit=65536):
    child = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    chunks = []
    reader = threading.Thread(target=lambda: chunks.append(child.stdout.read(limit + 1)), daemon=True)
    reader.start()
    try:
        reader.join(4)
        if reader.is_alive():
            raise ValueError("timeout")
        if not chunks or len(chunks[0]) > limit:
            raise ValueError("overflow")
        if child.wait(timeout=1) != 0:
            raise ValueError("command")
        return chunks[0].decode("utf-8", errors="strict")
    finally:
        if child.poll() is None:
            child.kill()
        child.wait(timeout=1)
        reader.join(1)
        if not reader.is_alive():
            child.stdout.close()

def classify(raw, invocation):
    lines = raw.splitlines()
    if len(lines) >= 200:
        raise ValueError("possibly_truncated")
    result = []
    unknown = 0
    for line in lines:
        if len(line.encode("utf-8")) > 8192:
            raise ValueError("record_limit")
        row = json.loads(line)
        if not isinstance(row, dict) or row.get("_SYSTEMD_INVOCATION_ID") != invocation:
            raise ValueError("invocation")
        message = row.get("MESSAGE")
        timestamp = row.get("__REALTIME_TIMESTAMP")
        if not isinstance(message, str) or not isinstance(timestamp, str) or not re.fullmatch(r"[0-9]{1,20}", timestamp):
            raise ValueError("shape")
        stage = None
        board = "all"
        match = re.match(r"^\[DLF\] (dlfSf|dlfIdp|dlfRookieSf|dlfRookieIdp)(?::| )", message)
        if match:
            board = match[1]
            tail = message[match.end():]
            for pattern, label in (
                (r"^fetch failed: ", "fetch_failed"),
                (r"^ re-auth failed: ", "reauth_failed"),
                (r"^ still preview after re-auth", "persistent_preview"),
                (r"^ parsed only [0-9]+ rows", "row_floor"),
                (r"^ native Value coverage [0-9]+/[0-9]+", "native_value_floor"),
                (r"^ got non-member preview", "preview_reauth"),
            ):
                if re.match(pattern, tail):
                    stage = label
                    break
        if message.startswith("[DLF] login failed: "):
            stage = "login_failed"
        empty = re.fullmatch(r"\[DLF\] WARN: no rows extracted for (dlfSf|dlfIdp|dlfRookieSf|dlfRookieIdp)", message)
        wrote = re.fullmatch(r"\[DLF\] wrote [0-9]+ rows → CSVs/site_raw/(dlfSf|dlfIdp|dlfRookieSf|dlfRookieIdp)\.csv", message)
        if empty or wrote:
            board = (empty or wrote)[1]
            stage = "empty_rows" if empty else "wrote"
        if message == "[dlf-fetch][ERR] fetch_dlf.py exited non-zero - keeping previous CSVs / stamp; will retry on next timer fire.":
            stage = "wrapper_fetch_nonzero"
        if stage is None:
            unknown += 1
        else:
            result.append((timestamp, board, stage))
    return result, unknown

def main():
    app, unit = sys.argv[1:]
    expected = str(Path(app) / "deploy/dlf_fetch_and_push.sh")
    try:
        execution = bounded(["systemctl", "show", unit, "--property=ExecStart", "--value"], 8192).strip()
    except Exception:
        execution = ""
    # Recognize only systemd's single-command representation with no arguments.
    # Any other representation is unknown, never permission to inspect its path.
    match = re.fullmatch(r"\{ path=" + re.escape(expected) + r" ; argv\[\]=" + re.escape(expected) + r" ; ignore_errors=(?:yes|no) ; start_time=\[[^\]\r\n]*\] ; stop_time=\[[^\]\r\n]*\] ; pid=[0-9]+ ; code=[A-Za-z_]+ ; status=[0-9]+ \}", execution)
    print("dlf.identity.wrapperCommand=" + ("expected_single_command" if match else "unverified"))
    for role, path in (("wrapper", Path(expected)), ("defaultFetcher", Path("/var/lib/dlf-fetch/repo/scripts/fetch_dlf.py"))):
        try:
            if path.resolve() != path.absolute() or any(parent.is_symlink() for parent in path.parents):
                raise ValueError("path")
            with os.fdopen(os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)), "rb") as stream:
                before = os.fstat(stream.fileno())
                if not stat.S_ISREG(before.st_mode) or before.st_size > 262144:
                    raise ValueError("file")
                content = stream.read(262145)
                after = os.fstat(stream.fileno())
            if len(content) > 262144 or (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise ValueError("changed")
            print("dlf.identity." + role + "Sha256=" + hashlib.sha256(content).hexdigest())
        except Exception:
            print("dlf.identity." + role + "State=unavailable")
    try:
        revision = bounded(["git", "-C", "/var/lib/dlf-fetch/repo", "rev-parse", "--verify", "HEAD"], 128).strip()
    except Exception:
        revision = ""
    print("dlf.identity.defaultRevision=" + (revision if re.fullmatch(r"[0-9a-f]{40}", revision) else "unavailable"))
    invocation = bounded(["systemctl", "show", unit, "--property=InvocationID", "--value"], 128).strip()
    if not re.fullmatch(r"[0-9a-f]{32}", invocation) or invocation == "0" * 32:
        raise ValueError("no_invocation")
    raw = bounded(["journalctl", "--no-pager", "--output=json", "--output-fields=MESSAGE,__REALTIME_TIMESTAMP,_SYSTEMD_INVOCATION_ID", "-n", "200", "_SYSTEMD_INVOCATION_ID=" + invocation])
    events, unknown = classify(raw, invocation)
    # Query again: do not associate an old invocation with a newly running unit.
    if bounded(["systemctl", "show", unit, "--property=InvocationID", "--value"], 128).strip() != invocation:
        raise ValueError("changed_invocation")
    print("dlf.journal.state=" + ("classified" if raw else "empty"))
    print("dlf.journal.unclassified=" + str(unknown))
    for index, (timestamp, board, stage) in enumerate(events):
        print(f"dlf.journal.event{index}.timestampUs={timestamp}")
        print(f"dlf.journal.event{index}.board={board}")
        print(f"dlf.journal.event{index}.stage={stage}")

if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("dlf.journal.state=unavailable_or_incomplete")
DLF_JOURNAL_PY
        } 2>/dev/null | head -c 32769); then
            journal_valid=1
            [[ ${#journal_output} -le 32768 && -n "$journal_output" ]] || journal_valid=0
            while IFS= read -r line; do
                if [[ ! "$line" =~ ^dlf\.journal\.state=(classified|empty|unavailable_or_incomplete)$ &&
                      ! "$line" =~ ^dlf\.journal\.unclassified=[0-9]{1,3}$ &&
                      ! "$line" =~ ^dlf\.journal\.event[0-9]{1,3}\.timestampUs=[0-9]{1,20}$ &&
                      ! "$line" =~ ^dlf\.journal\.event[0-9]{1,3}\.board=(all|dlfSf|dlfIdp|dlfRookieSf|dlfRookieIdp)$ &&
                      ! "$line" =~ ^dlf\.journal\.event[0-9]{1,3}\.stage=(fetch_failed|reauth_failed|persistent_preview|row_floor|native_value_floor|preview_reauth|login_failed|empty_rows|wrote|wrapper_fetch_nonzero)$ &&
                      ! "$line" =~ ^dlf\.identity\.wrapperCommand=(expected_single_command|unverified)$ &&
                      ! "$line" =~ ^dlf\.identity\.(wrapper|defaultFetcher)Sha256=[0-9a-f]{64}$ &&
                      ! "$line" =~ ^dlf\.identity\.(wrapper|defaultFetcher)State=unavailable$ &&
                      ! "$line" =~ ^dlf\.identity\.defaultRevision=([0-9a-f]{40}|unavailable)$ ]]; then
                    journal_valid=0
                fi
            done <<< "$journal_output"
            if [[ "$journal_valid" == 1 ]]; then printf '%s\n' "$journal_output"; else echo 'dlf.journal.state=probe_failed'; fi
        else
            echo 'dlf.journal.state=probe_failed'
        fi
    else
        echo 'dlf.journal.state=unavailable'
    fi
    echo 'limits=snapshot_only;assumed_default_store_path;actual_store_configuration_unverified;no_process_fd_recovery;no_credential_separation_proof'
    exit 0
    ;;
closure) ;;
*) echo 'inventory_error=invalid_scope'; exit 1 ;;
esac

say() { printf '[c1a-inventory] %s\n' "$*"; }
hdr() { printf '\n[c1a-inventory] ══ %s ══\n' "$*"; }
kv() { printf '[c1a-inventory]   %-34s %s\n' "$1" "$2"; }

[[ -d "${APP_DIR}" ]] || { printf '[c1a-inventory][ERR] APP_DIR missing: %s\n' "${APP_DIR}" >&2; exit 1; }

say "host=$(hostname) user=$(id -un) date=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
say "APP_DIR=${APP_DIR} SERVICE_NAME=${SERVICE_NAME} LIB_DIR=${LIB_DIR}"

# ── helpers ───────────────────────────────────────────────────────────────
# Absent, unreadable and present-with-a-hash are three answers, not two.
file_state() {
    local path="$1"
    if [[ -e "${path}" || -L "${path}" ]]; then
        if [[ -r "${path}" ]]; then
            printf 'PRESENT sha256=%s bytes=%s mtime=%s' \
                "$(sha256sum "${path}" 2>/dev/null | awk '{print $1}')" \
                "$(stat -c %s "${path}" 2>/dev/null || echo '?')" \
                "$(stat -c %y "${path}" 2>/dev/null | cut -d. -f1 || echo '?')"
        else
            printf 'UNREADABLE by %s' "$(id -un)"
        fi
    else
        printf 'ABSENT'
    fi
}

unit_state() {
    local unit="$1"
    if ! systemctl cat "${unit}" >/dev/null 2>&1; then
        kv "${unit}" "NOT INSTALLED"
        return 0
    fi
    kv "${unit}" "installed"
    kv "  is-enabled" "$(systemctl is-enabled "${unit}" 2>&1 || true)"
    kv "  is-active" "$(systemctl is-active "${unit}" 2>&1 || true)"
    local prop val
    for prop in Result ExecMainStatus ExecMainExitTimestamp NRestarts \
                WorkingDirectory User ActiveEnterTimestamp \
                LastTriggerUSec NextElapseUSecRealtime Persistent; do
        val="$(systemctl show "${unit}" -p "${prop}" --value 2>/dev/null || true)"
        if [[ -n "${val}" ]]; then
            kv "  ${prop}" "${val}"
        fi
    done
    # ExecStart is a struct; the path is what matters here.
    #
    # `if`, not `[[ … ]] && kv …`.  A TIMER has no ExecStart, so the && chain
    # returns 1, that becomes this function's exit status, and `set -e` kills
    # the whole inventory mid-report — which is what happened on the first
    # production run: section A completed, the first installed TIMER aborted it.
    # The units in section A had escaped it only by returning early.
    local execstart
    execstart="$(systemctl show "${unit}" -p ExecStart --value 2>/dev/null | head -c 300 || true)"
    if [[ -n "${execstart}" ]]; then
        kv "  ExecStart" "${execstart}"
    fi
    return 0
}

journal_tail() {
    local unit="$1"
    if journalctl -u "${unit}" -n "${JOURNAL_LINES}" --no-pager >/dev/null 2>&1; then
        say "journal (last ${JOURNAL_LINES}) for ${unit}:"
        journalctl -u "${unit}" -n "${JOURNAL_LINES}" --no-pager 2>&1 | sed 's/^/[journal] /' || true
    elif sudo -n journalctl -u "${unit}" -n "${JOURNAL_LINES}" --no-pager >/dev/null 2>&1; then
        say "journal (last ${JOURNAL_LINES}, via sudo) for ${unit}:"
        sudo -n journalctl -u "${unit}" -n "${JOURNAL_LINES}" --no-pager 2>&1 | sed 's/^/[journal] /' || true
    else
        say "journal for ${unit}: UNAVAILABLE to $(id -un) (not an assertion that it is empty)"
    fi
}

# ══ A. NIGHTLY BACKUP LINEAGE ═════════════════════════════════════════════
hdr "A. nightly backup lineage (root-owned, refreshed only by apply_hardening.sh)"

INSTALLED_WRITER="${LIB_DIR}/riskit-state-backup.sh"
INSTALLED_LIB="${LIB_DIR}/backup_root_lib.sh"
DEPLOYED_WRITER="${APP_DIR}/deploy/backup/riskit-state-backup.sh"
DEPLOYED_LIB="${APP_DIR}/deploy/backup/backup_root_lib.sh"

kv "installed writer" "$(file_state "${INSTALLED_WRITER}")"
kv "installed lib" "$(file_state "${INSTALLED_LIB}")"
kv "deployed writer" "$(file_state "${DEPLOYED_WRITER}")"
kv "deployed lib" "$(file_state "${DEPLOYED_LIB}")"

# The question that actually decides whether the nightly carries #852.
for pair in "writer:${INSTALLED_WRITER}:${DEPLOYED_WRITER}" "lib:${INSTALLED_LIB}:${DEPLOYED_LIB}"; do
    name="${pair%%:*}"; rest="${pair#*:}"
    inst="${rest%%:*}"; depl="${rest#*:}"
    if [[ -r "${inst}" && -r "${depl}" ]]; then
        a="$(sha256sum "${inst}" | awk '{print $1}')"
        b="$(sha256sum "${depl}" | awk '{print $1}')"
        if [[ "${a}" == "${b}" ]]; then
            kv "${name}: installed vs deployed" "IDENTICAL — nightly carries the deployed code"
        else
            kv "${name}: installed vs deployed" "DIFFERENT — nightly is running OTHER code than the checkout"
        fi
    elif [[ ! -e "${inst}" && ! -L "${inst}" ]]; then
        kv "${name}: installed vs deployed" "INSTALLED COPY ABSENT — apply_hardening.sh has not installed it"
    else
        kv "${name}: installed vs deployed" "INDETERMINATE — one side unreadable by $(id -un)"
    fi
done

hdr "A2. backup units"
# Corroborate a NOT-INSTALLED verdict against the unit REGISTRY before
# believing it. Probing one hard-coded name and reporting absence would turn a
# rename into "there is no nightly backup", which is a far more alarming claim
# than the evidence would support.
say "unit files whose name mentions riskit/backup:"
if systemctl list-unit-files --no-pager --no-legend 2>/dev/null \
    | grep -Ei 'riskit|backup' | sed 's/^/[c1a-inventory]     /'; then
    :
else
    kv "  registry match" "NONE — no installed unit file mentions riskit or backup"
fi
unit_state "riskit-state-backup.timer"
unit_state "riskit-state-backup.service"
journal_tail "riskit-state-backup.service"

hdr "A3. backup roots as seen by $(id -un)"
# Names only. A generation directory name is a date, not a payload.
for root in "${BACKUP_ROOT_PRIMARY:-/var/backups/riskit-state}" \
            "${BACKUP_ROOT_FALLBACK:-${HOME}/backups/riskit-state}"; do
    say "root ${root}"
    if [[ ! -e "${root}" && ! -L "${root}" ]]; then
        kv "  state" "ABSENT"
        continue
    fi
    if [[ ! -r "${root}" || ! -x "${root}" ]]; then
        kv "  state" "UNREADABLE by $(id -un) — cannot rule out generations here"
        continue
    fi
    kv "  state" "readable"
    kv "  last_generation pointer" "$(file_state "${root}/last_generation")"
    if [[ -r "${root}/last_generation" ]]; then
        sed 's/^/[c1a-inventory]     pointer: /' "${root}/last_generation" 2>/dev/null || true
    fi
    if [[ -d "${root}/daily" && -r "${root}/daily" && -x "${root}/daily" ]]; then
        kv "  daily/ entries" "$(ls -1 "${root}/daily" 2>/dev/null | wc -l | tr -d ' ')"
        ls -1 "${root}/daily" 2>/dev/null | sed 's/^/[c1a-inventory]     /' || true
    elif [[ -e "${root}/daily" || -L "${root}/daily" ]]; then
        kv "  daily/" "PRESENT but not a readable directory"
    else
        kv "  daily/" "ABSENT"
    fi
done

# ══ B. PLAYERCTX PUBLICATION PATH (C1-RET-08) ═════════════════════════════
hdr "B. playerctx retention — producer and pusher are separate failures"

unit_state "${SERVICE_NAME}-playerctx-refresh.timer"
unit_state "${SERVICE_NAME}-playerctx-refresh.service"
unit_state "${SERVICE_NAME}-playerctx-history.timer"
unit_state "${SERVICE_NAME}-playerctx-history.service"
journal_tail "${SERVICE_NAME}-playerctx-history.service"

hdr "B2. the pusher's preconditions"
WORK_DIR="${PLAYERCTX_HISTORY_WORK_DIR:-/var/lib/playerctx-history}"
SSH_KEY="${PLAYERCTX_HISTORY_SSH_KEY:-${HOME}/.ssh/github_deploy_key}"

# WorkingDirectory= has no `-` prefix in the unit template, so systemd fails
# the unit BEFORE ExecStart if this is missing — the script's own `mkdir -p`
# can never help, because the script never starts. That produces zero
# [playerctx-history] log lines, which is indistinguishable from "never ran"
# unless you look here.
if [[ -d "${WORK_DIR}" ]]; then
    kv "WorkingDirectory ${WORK_DIR}" "PRESENT owner=$(stat -c '%U:%G' "${WORK_DIR}" 2>/dev/null || echo '?') mode=$(stat -c %a "${WORK_DIR}" 2>/dev/null || echo '?')"
    kv "  dedicated clone .git" "$([[ -d "${WORK_DIR}/riskittogetthebrisket/.git" ]] && echo PRESENT || echo ABSENT)"
elif [[ -e "${WORK_DIR}" || -L "${WORK_DIR}" ]]; then
    kv "WorkingDirectory ${WORK_DIR}" "PRESENT but NOT A DIRECTORY — systemd will fail the unit before ExecStart"
else
    kv "WorkingDirectory ${WORK_DIR}" "ABSENT — systemd fails the unit before ExecStart (no '-' prefix in the template)"
fi

# Readability, never content.
if [[ -r "${SSH_KEY}" ]]; then
    kv "deploy key ${SSH_KEY}" "READABLE by $(id -un)"
elif [[ -e "${SSH_KEY}" || -L "${SSH_KEY}" ]]; then
    kv "deploy key ${SSH_KEY}" "PRESENT but UNREADABLE by $(id -un)"
else
    kv "deploy key ${SSH_KEY}" "ABSENT"
fi

hdr "B3. what is on disk vs what is committed"
HIST_DIR="${APP_DIR}/data/playerctx/history"
if [[ -d "${HIST_DIR}" ]]; then
    kv "history dir" "${HIST_DIR}"
    kv "  dated snapshots on disk" "$(ls -1 "${HIST_DIR}"/snapshot_*.json 2>/dev/null | wc -l | tr -d ' ')"
    ls -1 "${HIST_DIR}" 2>/dev/null | sed 's/^/[c1a-inventory]     /' || true
    # `data/` is gitignored repo-wide and these reach the tree only via an
    # explicit `git add -f`, so tracked-vs-untracked IS pushed-vs-unpushed.
    say "git ls-files for that path (tracked == previously pushed):"
    git -C "${APP_DIR}" ls-files -- data/playerctx/history 2>&1 | sed 's/^/[c1a-inventory]     /' || true
    kv "  tracked count" "$(git -C "${APP_DIR}" ls-files -- data/playerctx/history 2>/dev/null | wc -l | tr -d ' ')"
else
    kv "history dir" "ABSENT at ${HIST_DIR}"
fi

hdr "B4. the checkout's git identity (read-only)"
kv "branch" "$(git -C "${APP_DIR}" rev-parse --abbrev-ref HEAD 2>&1 || true)"
kv "HEAD" "$(git -C "${APP_DIR}" rev-parse HEAD 2>&1 || true)"
kv "remote origin" "$(git -C "${APP_DIR}" remote get-url origin 2>&1 || true)"

hdr "DONE — nothing above was modified"
exit 0
