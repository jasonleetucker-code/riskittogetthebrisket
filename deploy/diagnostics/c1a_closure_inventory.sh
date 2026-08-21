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


# ══ C. EVERY OTHER SYSTEMD UNIT (V1-124 / C10-CLOSE-04) ═══════════════════
#
# Sections A and B answer two specific, previously-measured failures. This
# section exists because V1-124's own census found 14 of the 20 template-
# rendered timers (plus 3 more installed by apply_hardening.sh, plus 2 in
# directories with their own dedicated installer) have NO health signal
# anywhere else — no `_last_success` stamp, no retention stream, no
# /api/status field, no CI assertion. journalctl on the box was the only
# evidence any of them ran. This closes that gap with the same read-only
# unit_state()/journal_tail() probes sections A and B already use, extended
# to cover every unit rather than the 3 this script started with.
#
# TRAP, already documented at docs/master-site-audit/B_SERIES_EXECUTION_
# LEDGER.md:176-178 and worth repeating here: a timer-activated Type=oneshot
# service's correct STEADY STATE between runs is inactive/disabled. Do not
# read `is-active` as a liveness check the way you would for dynasty.service
# below — read LastTriggerUSec + Result + ExecMainStatus instead, which
# unit_state() already reports for every unit.

hdr "C1. the two always-on application services"
unit_state "${SERVICE_NAME}.service"
unit_state "${SERVICE_NAME}-frontend.service"

hdr "C2. sharp-intel lane (8 recurring crawls, zero health signal today — the entire lane)"
for stem in sharp-discovery sharp-records sharp-cohort-snapshot sharp-rosters sharp-activity sharp-transactions; do
    unit_state "${SERVICE_NAME}-${stem}.timer"
    unit_state "${SERVICE_NAME}-${stem}.service"
done
unit_state "chase-upside-ffpc-sharp.timer"
unit_state "chase-upside-ffpc-sharp.service"
unit_state "chase-upside-curated-sharps.timer"
unit_state "chase-upside-curated-sharps.service"

hdr "C3. other dynasty-* template units (no dedicated section elsewhere in this script)"
for stem in bdvm-refresh crowd-faab board-snapshot reception-depth consensus-edge-snapshot faab-history pbp-weekly custom-alerts signal-alerts dlf-fetch idpshow-fetch; do
    unit_state "${SERVICE_NAME}-${stem}.timer"
    unit_state "${SERVICE_NAME}-${stem}.service"
done

hdr "C4. apply_hardening.sh-installed units (V1-124 found this installer has ZERO automated callers — verify these exist on the box at all before trusting anything else in this section)"
unit_state "dynasty-healthcheck.timer"
unit_state "dynasty-healthcheck.service"
unit_state "riskit-uptime.timer"
unit_state "riskit-uptime.service"
unit_state "riskit-backup.timer"
unit_state "riskit-backup.service"
unit_state "riskit-backup-restore-test.timer"
unit_state "riskit-backup-restore-test.service"
kv "riskit-uptime SuccessExitStatus" "known to be '0 1' in the shipped template -- systemd will NOT report this unit failed while the uptime probe is reporting the site DOWN. Read /var/log/riskit-uptime.log directly; is-failed cannot see an outage here"

hdr "DONE — nothing above was modified"
exit 0
