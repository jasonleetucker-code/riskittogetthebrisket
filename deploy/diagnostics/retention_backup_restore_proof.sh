#!/usr/bin/env bash
#
# retention_backup_restore_proof.sh — run the real production backup,
# then RESTORE the retained artifacts into a throwaway directory and
# verify them.
#
# C1A unit 1 requires backup AND restore proof, and this exists because
# neither could be asserted before: `riskit-state-backup.sh` verifies
# what it writes, but nothing ever read a generation back, and a backup
# nobody has restored is a hypothesis.  Log text saying a backup command
# ran is not evidence the artifact is in it.
#
# WHAT IT PROVES, AND WHAT IT REFUSES TO CLAIM
# ─────────────────────────────────────────────
# For each retained artifact the rule is the same and it is the point of
# the script: **an artifact that exists on the source and is ABSENT from
# the backup is a FAILURE; an artifact that does not exist yet is
# reported and is not.**  A retention stream that has legitimately not
# started cannot make this red, and a stream that HAS started cannot be
# quietly left out of the backup.
#
# Restore goes to a temp directory. It NEVER touches live state — no
# path under $DATA_DIR is written, and the backend is not stopped.
#
# PRIVACY
# ───────
# `league_events.sqlite` holds our own leagues' real trades. It is
# proven by SCHEMA, COUNTS and ID SHAPE only. No payload, no manager
# name, no roster is printed — this output goes to a CI log.
#
# WHERE IT LOOKS
# ──────────────
# It does not decide.  `deploy/backup/backup_root_lib.sh` — sourced from
# the DEPLOYED tree, so it is the same resolver the writer just ran — owns
# the requested primary root, the writability determination, the fallback
# and the pointer format.  With RUN_BACKUP=1 the generation comes from the
# machine-readable result that run wrote; with RUN_BACKUP=0 it is the
# newest generation recorded by any candidate root.  Nothing here parses a
# log line, and nothing here reimplements the fallback.
#
# Inputs (environment):
#   APP_DIR              deployed app tree (also where the resolver lives)
#   DATA_DIR             live data dir (READ ONLY here)
#   BACKUP_ROOT          requested primary root — read via the shared
#                        resolver, and NOT assumed to be where the backup
#                        actually landed
#   BACKUP_FALLBACK_ROOT fallback root, same
#   PYTHON_BIN           venv interpreter (sqlite3 CLI is not on the box)
#   RUN_BACKUP           "1" (default) to run the backup first; "0" to
#                        verify the newest recorded generation only
#   PROOF_SKIP_OPTIONAL  OPTIONAL artifact names the proof's backup run
#                        leaves out (passed to the writer as
#                        BACKUP_SKIP_OPTIONAL).  Default: the two large
#                        stores, "temporal_ledger.sqlite intel_ledger.sqlite3".
#
# THE PROOF RUN IS A CORE RESTORE PROOF, NOT A SECOND NIGHTLY
# ───────────────────────────────────────────────────────────
# It runs after every production deploy inside a 20-minute job budget, as
# the deploy user, on the live box.  The nightly (root, 2h TimeoutStartSec)
# is what carries the 1.5 GB temporal ledger and the 0.7 GB intel-ledger
# online copy; copying, integrity-checking and gzipping both here would spend
# most of the budget and compete with the app for I/O right after a deploy,
# to prove nothing the small stores do not.  So this run skips them by
# default (recorded in the generation as `skipped_requested`, and the intel
# ledger then rides in intel.tar.gz as raw files, the pre-AL-P2 path) and
# runs at low CPU and I/O priority.  It restore-checks every CORE artifact
# and the SMALL OPTIONAL ones; it never restores the large ledgers.
#
# An OPTIONAL store the writer recorded as failed or shed for disk space
# (optional_stores.tsv in the generation, writer exit 3) is a WARNING here,
# emitted as a GitHub ::warning:: annotation — the same posture the writer
# takes — never a silent pass and never a red proof.  The proof's own run
# cannot see a failure in the two stores it skips, so it also reads the
# NIGHTLY unit's last ExecMainStatus (unprivileged `systemctl show`) and
# annotates a 3 or a failure there (section 1b).
#
# Exit codes: 0 proven (possibly with optional-store warnings) · 1 could
# not run · 2 an artifact that exists on the source is missing from the
# backup, or a restored artifact failed verification.

set -Eeuo pipefail

APP_DIR="${APP_DIR:-/home/dynasty/trade-calculator}"
DATA_DIR="${DATA_DIR:-${APP_DIR}/data}"
PYTHON_BIN="${PYTHON_BIN:-/home/dynasty/.venvs/trade-calculator/bin/python}"
RUN_BACKUP="${RUN_BACKUP:-1}"
PROOF_SKIP_OPTIONAL="${PROOF_SKIP_OPTIONAL-temporal_ledger.sqlite intel_ledger.sqlite3}"

log()  { printf '[backup-proof] %s\n' "$*"; }
warn() { printf '[backup-proof][WARN] %s\n' "$*" >&2; }
fail() { printf '[backup-proof][ERROR] %s\n' "$*" >&2; exit 1; }

OPTIONAL_WARNINGS=0
# A GitHub Actions workflow command on stdout: rendered as an annotation on
# the run when this script's output reaches a workflow log (it does — the
# workflow relays it over ssh), and a harmless line anywhere else.
note_optional_warning() {
    printf '[backup-proof][WARN] %s\n' "$*" >&2
    printf '::warning title=Backup proof: optional store::%s\n' "$*"
    OPTIONAL_WARNINGS=$((OPTIONAL_WARNINGS + 1))
}

FAILURES=0
note_fail() { printf '[backup-proof][FAIL] %s\n' "$*" >&2; FAILURES=$((FAILURES + 1)); }
# "nothing failed" is TRUE of a run that read nothing. Counting what was
# actually restored and verified is what stops silence reading as proof.
PROVEN=0
note_proven() { PROVEN=$((PROVEN + 1)); }

RESTORE_DIR=""
RESULT_FILE=""
# Each step guarded INDEPENDENTLY. Under `set -Eeuo pipefail` a failing
# `rm -rf` inside an EXIT trap aborts the trap: the pending exit status is
# replaced by 1 and every later step is skipped. That turns a real artifact
# failure (exit 2, "missing from the backup") into what reads as
# infrastructure breakage, and a fully green proof into a red one — while
# also leaking the result file it never got to remove.
cleanup() {
    [[ -z "${RESTORE_DIR}" ]] || rm -rf "${RESTORE_DIR}" || true
    [[ -z "${RESULT_FILE}" ]] || rm -f "${RESULT_FILE}" || true
    return 0
}
trap cleanup EXIT

[[ -d "${APP_DIR}" ]] || fail "app dir not found: ${APP_DIR}"
[[ -x "${PYTHON_BIN}" ]] || PYTHON_BIN="$(command -v python3 || true)"
[[ -x "${PYTHON_BIN}" ]] || fail "no usable python interpreter"

# ── 0. The backup root has ONE owner, and it is not this script ──────
# This script does not know where backups live and must not guess.  It
# asks the same library the writer uses, from the DEPLOYED tree, so the
# resolver answering here is byte-identical to the one that ran there.
# Absent library = cannot run (exit 1); never a silent pass, and never a
# locally reimplemented fallback.
BACKUP_ROOT_LIB="${APP_DIR}/deploy/backup/backup_root_lib.sh"
[[ -f "${BACKUP_ROOT_LIB}" ]] || fail "backup root library missing on the deployed revision: ${BACKUP_ROOT_LIB} — cannot resolve the effective backup root without reimplementing it; deploy the revision that ships it"
# shellcheck source=deploy/backup/backup_root_lib.sh
source "${BACKUP_ROOT_LIB}"

# The getters refuse a non-absolute root; make that refusal fatal HERE rather
# than letting an empty candidate list quietly become "no generation found".
backup_root_primary >/dev/null || fail "BACKUP_ROOT must be an absolute path"
backup_root_fallback >/dev/null || fail "BACKUP_FALLBACK_ROOT must be an absolute path"

# ── 1. Run the real backup ───────────────────────────────────────────
if [[ "${RUN_BACKUP}" == "1" ]]; then
    BACKUP_SCRIPT="${APP_DIR}/deploy/backup/riskit-state-backup.sh"
    [[ -f "${BACKUP_SCRIPT}" ]] || fail "backup script absent on the deployed revision: ${BACKUP_SCRIPT}"
    RESULT_FILE="$(mktemp /tmp/retention-backup-result-XXXXXX)"
    # Low priority: this runs on the live box right after a deploy, as the
    # deploy user, next to the app it just restarted.  Best-effort class at
    # its lowest level rather than `idle`, which can starve indefinitely under
    # load and turn a 20-minute job budget into a timeout.
    PRIO=(nice -n 10)
    if command -v ionice >/dev/null 2>&1; then
        PRIO+=(ionice -c2 -n7)
    fi
    log "running production backup: ${BACKUP_SCRIPT} (skipping optional: ${PROOF_SKIP_OPTIONAL:-none})"
    backup_rc=0
    APP_DIR="${APP_DIR}" DATA_DIR="${DATA_DIR}" \
        BACKUP_ROOT="$(backup_root_primary)" \
        BACKUP_FALLBACK_ROOT="$(backup_root_fallback)" \
        BACKUP_RESULT_FILE="${RESULT_FILE}" \
        BACKUP_SKIP_OPTIONAL="${PROOF_SKIP_OPTIONAL}" \
        OFFBOX_RSYNC_DEST= \
        PYTHON_BIN="${PYTHON_BIN}" "${PRIO[@]}" bash "${BACKUP_SCRIPT}" || backup_rc=$?
    case "${backup_rc}" in
        0) ;;
        3) note_optional_warning "the backup promoted its generation with all CORE state, but an OPTIONAL store failed or was shed for disk space (writer exit 3) — see optional_stores.tsv in the generation" ;;
        *) fail "backup run FAILED (exit ${backup_rc})" ;;
    esac
fi

# ── 1b. The NIGHTLY's last exit status ───────────────────────────────
# The run above is this proof's own, and it skips the two large stores on
# purpose — so its exit 3 can never report a failure in the temporal ledger or
# the intel ledger's online copy, which only the 02:30 root nightly carries.
# That nightly's generation is root-only (0700), but its unit status is not:
# `systemctl show` needs no privilege.  This is the only place a nightly exit 3
# surfaces, so it surfaces at the next deploy, not when it happens.  It
# annotates; it never changes this proof's exit code, which is about the
# generation proven below.
NIGHTLY_UNIT="${NIGHTLY_UNIT:-riskit-state-backup.service}"
check_nightly_last_status() {
    if ! command -v systemctl >/dev/null 2>&1; then
        log "nightly ${NIGHTLY_UNIT}: systemctl not available here — its last exit status is not checked"
        return 0
    fi
    local load result status at
    load="$(systemctl show "${NIGHTLY_UNIT}" -p LoadState --value 2>/dev/null)" || load=""
    if [[ "${load}" != "loaded" ]]; then
        log "nightly ${NIGHTLY_UNIT}: not installed here (LoadState=${load:-unknown}) — its last exit status is not checked"
        return 0
    fi
    result="$(systemctl show "${NIGHTLY_UNIT}" -p Result --value 2>/dev/null)" || result=""
    status="$(systemctl show "${NIGHTLY_UNIT}" -p ExecMainStatus --value 2>/dev/null)" || status=""
    at="$(systemctl show "${NIGHTLY_UNIT}" -p ExecMainExitTimestamp --value 2>/dev/null)" || at=""
    if [[ -z "${at}" || "${at}" == "n/a" ]]; then
        log "nightly ${NIGHTLY_UNIT}: no completed run since the service manager started — nothing to report"
        return 0
    fi
    if [[ "${result}" == "success" && "${status}" == "0" ]]; then
        log "nightly ${NIGHTLY_UNIT}: last run (${at}) exit 0"
    elif [[ "${result}" == "success" && "${status}" == "3" ]]; then
        note_optional_warning "the nightly ${NIGHTLY_UNIT} last run (${at}) exited 3 — its generation was promoted with all CORE state, but an OPTIONAL store failed or was shed (the temporal ledger and the intel ledger's online copy are only in the nightly); the store is named in that generation's root-only optional_stores.tsv and in: sudo journalctl -u ${NIGHTLY_UNIT}"
    else
        warn "nightly ${NIGHTLY_UNIT}: last run (${at}) Result=${result:-unknown} ExecMainStatus=${status:-unknown} — not a successful backup"
        printf '::warning title=Backup proof: nightly backup::the nightly %s last run (%s) did not succeed (Result=%s ExecMainStatus=%s) — see: sudo journalctl -u %s\n' \
            "${NIGHTLY_UNIT}" "${at}" "${result:-unknown}" "${status:-unknown}" "${NIGHTLY_UNIT}"
    fi
}
check_nightly_last_status

# ── 2. Locate the generation we are proving ──────────────────────────
# With a backup just run, the generation is whatever THAT run reported —
# read from its machine-readable result, not re-derived and not scraped
# out of its log.  This is what makes the location that received the
# promoted backup and the location inspected here the same location by
# construction, and it is why a newer pointer sitting in the other
# candidate root cannot capture this proof.
if [[ "${RUN_BACKUP}" == "1" ]]; then
    GEN="$(backup_root_pointer_field "${RESULT_FILE}" generation || true)"
    EFFECTIVE_ROOT="$(backup_root_pointer_field "${RESULT_FILE}" effective_root || true)"
    [[ -n "${GEN}" ]] || fail "the backup completed but recorded no generation in ${RESULT_FILE}"
else
    # Verifying an existing generation: ask each candidate root what it
    # recorded and take the newest.  `promoted_at` is fixed-width ISO-8601
    # UTC, so a string comparison is a chronological one.  Every candidate
    # examined is logged, so the selection is visible rather than implied.
    # Verifying an existing generation.  Three rules, and every one of them
    # exists because breaking it turns this proof into a false pass:
    #
    #  1. A root we cannot READ is not an empty root.  The nightly runs as
    #     root and chmods its root 0700, so an unprivileged prover sees
    #     exactly that — and if we skipped it we would go on to certify an
    #     OLDER generation out of the readable root and exit 0, which is
    #     worse than the bug this file was rewritten to fix.  Unreadable ⇒
    #     refuse (below), never substitute.
    #  2. A generation with no pointer still counts.  The pointer is younger
    #     than the backups: production's nightly runs a root-owned copy of
    #     the writer that only apply_hardening.sh refreshes, so real
    #     generations land with no pointer beside them.  Pointer first,
    #     on-disk scan second, and the log says which answered.
    #  3. A pointer is a HINT, not an upper bound.  Within one root, take
    #     whichever of the pointer and the disk names the newer generation —
    #     the pointer write is warn-only and happens AFTER promotion, so a
    #     run killed in that window leaves a stale pointer sitting in front
    #     of a newer generation.
    #  4. Compare on the DATE first and the instant only as a tiebreak, and
    #     hold the incumbent on "do we have one" rather than "does it have a
    #     stamp".  A derived midnight and a real promoted_at are not the same
    #     currency: straddling 00:00 UTC, yesterday's dated directory can
    #     carry a promoted_at of today and outrank a genuinely newer one.
    log "RUN_BACKUP=0 — locating the newest recorded generation"
    GEN=""; EFFECTIVE_ROOT=""; BEST_KEY=""; UNREADABLE=""
    while IFS= read -r cand; do
        [[ -n "${cand}" ]] || continue
        if [[ ! -e "${cand}" ]]; then
            # `-e` is false for ENOENT *and* for EACCES anywhere on the path,
            # and only the first is an empty root.  Absence has to be PROVEN:
            # walk up to the deepest ancestor that can actually be stat'd, and
            # if that one is not searchable then a generation may be sitting
            # behind the permission — which is an unreadable root, not a
            # missing one.  Keeping the branch matters: a genuinely absent
            # fallback must stay ordinary, not turn every run red.
            # `! -L` is not decoration.  `-e` DEREFERENCES a symlink while
            # `dirname` is purely textual, so without it the walk steps OFF a
            # symlinked root onto its readable lexical parent and calls a root
            # whose target is merely unreachable "absent" — the pre-fix
            # fail-open, restored by the ordinary sysadmin move of relocating
            # backups to another volume via a symlink.  lstat-visible means
            # unresolvable, not missing.
            probe="${cand}"
            while [[ ! -e "${probe}" && ! -L "${probe}" && "${probe}" != "/" && "${probe}" != "." ]]; do
                probe="$(dirname "${probe}")"
            done
            if [[ ! -x "${probe}" ]]; then
                log "candidate root ${cand}: NOT READABLE by $(id -un) (cannot stat through ${probe}) — cannot rule out a newer generation here"
                UNREADABLE+="${cand} "
                continue
            fi
            log "candidate root ${cand}: does not exist"
            continue
        fi
        if ! backup_root_readable "${cand}"; then
            log "candidate root ${cand}: NOT READABLE by $(id -un) — cannot rule out a newer generation here"
            UNREADABLE+="${cand} "
            continue
        fi
        # Ask BOTH finders, always.  Consulting the disk only when the
        # pointer says nothing lets a stale pointer mask a newer generation
        # in its own root.
        #
        # rc 2 from the scan means a dated entry is listed but unresolvable —
        # an unmounted volume, a dangling symlink, a path this user cannot
        # traverse. That entry may BE a newer generation, so the root is
        # INDETERMINATE, not empty, and takes the same refusal an unreadable
        # root takes. Checked before the pointer is consulted: a pointer
        # cannot vouch for a sibling entry nobody can read.
        cand_src="pointer"
        cand_disk=""; cand_rc=0
        cand_disk="$(backup_root_scan_generation "${cand}")" || cand_rc=$?
        if (( cand_rc == 3 )); then
            log "candidate root ${cand}: holds a generation dated beyond the clock-skew bound — name-ordered recency is untrustworthy here"
            UNREADABLE+="${cand} "
            continue
        fi
        if (( cand_rc == 2 )); then
            log "candidate root ${cand}: a dated entry under daily/ cannot be resolved by $(id -un) — cannot rule out a newer generation here"
            UNREADABLE+="${cand} "
            continue
        fi
        cand_gen="$(backup_root_read_generation "${cand}" || true)"
        if [[ -z "${cand_gen}" ]]; then
            cand_src="on-disk scan"
            cand_gen="${cand_disk}"
        elif [[ -n "${cand_disk}" && "${cand_disk}" != "${cand_gen}" ]]; then
            # Same generation ⇒ keep the pointer, which carries the real
            # instant.  Different ⇒ newer wins, whichever named it.
            if [[ "$(basename "${cand_disk}")" > "$(basename "${cand_gen}")" ]]; then
                log "candidate root ${cand}: pointer names ${cand_gen} but a NEWER generation is on disk"
                cand_src="on-disk scan (newer than the pointer)"
                cand_gen="${cand_disk}"
            fi
        fi
        if [[ -z "${cand_gen}" ]]; then
            log "candidate root ${cand}: readable, holds no generation"
            continue
        fi
        cand_at="$(backup_root_generation_stamp "${cand}" "${cand_gen}")"
        # Date dominates; the space sorts below every digit, so an unknown
        # instant loses a tie rather than winning one.
        cand_key="$(basename "${cand_gen}") ${cand_at}"
        log "candidate root ${cand}: generation ${cand_gen} (via ${cand_src}) promoted_at ${cand_at:-unknown}"
        if [[ -z "${GEN}" || "${cand_key}" > "${BEST_KEY}" ]]; then
            GEN="${cand_gen}"; EFFECTIVE_ROOT="${cand}"; BEST_KEY="${cand_key}"
        fi
    done < <(backup_root_candidates)

    # Refuse BEFORE accepting a winner.  Proving the older readable
    # generation while a root we cannot see may hold a newer one is
    # precisely the false pass this ordering prevents.
    if [[ -n "${UNREADABLE}" ]]; then
        fail "cannot certify a generation: candidate root(s) ${UNREADABLE}are not readable by $(id -un) (the root itself, its daily/, or a parent directory), so a newer generation may exist there and be invisible here — refusing to certify an older one instead. The nightly runs as root and chmods its root 0700; run with RUN_BACKUP=1 to prove a generation this user can actually write and read."
    fi
    [[ -n "${GEN}" ]] || fail "no backup generation in any readable candidate root ($(backup_root_candidates | tr '\n' ' ')) — run with RUN_BACKUP=1"
fi

[[ -d "${GEN}" ]] || fail "recorded generation does not exist on disk: ${GEN}"
# "effective backup root: X" must never be printed for a generation that is
# not under X. Belt-and-braces behind the library's pointer containment check.
if [[ -n "${EFFECTIVE_ROOT}" && "${GEN}" != "${EFFECTIVE_ROOT%/}/daily/"* ]]; then
    fail "selected generation ${GEN} is not under the root that supplied it (${EFFECTIVE_ROOT}) — refusing to certify a generation from outside a candidate backup location"
fi
log "effective backup root: ${EFFECTIVE_ROOT:-unknown}"

# Say what this run does NOT cover.  The nightly is a different process
# (root, from /usr/local/lib/riskit) writing a different root, and a green
# tick here must not be read as "the nightly's generations restore" when
# this user cannot even open them.
if [[ -n "${EFFECTIVE_ROOT}" && "${EFFECTIVE_ROOT}" != "$(backup_root_primary)" ]]; then
    warn "this proves the backup lineage written by $(id -un) into the FALLBACK root. The nightly systemd job runs as root and writes $(backup_root_primary); those generations are not readable here and are NOT covered by this run."
fi
log "proving generation: ${GEN}"
log "generation size: $(du -sh "${GEN}" 2>/dev/null | cut -f1)"

RESTORE_DIR="$(mktemp -d /tmp/retention-restore-XXXXXX)"
log "restore target (throwaway): ${RESTORE_DIR}"

# ── OPTIONAL stores the writer recorded as NOT in this generation ─────
# riskit-state-backup.sh lists every OPTIONAL store it left out, with why,
# in <generation>/optional_stores.tsv (name<TAB>status<TAB>detail).  A CORE
# store is never listed there, so a missing core artifact can never be
# explained away by this file.
optional_status() {
    local manifest="${GEN}/optional_stores.tsv"
    [[ -f "${manifest}" ]] || return 0
    awk -F '\t' -v n="$1" '$1 == n { s = $2 } END { if (s != "") print s }' "${manifest}"
}

# 0 = the absence is the writer's own recorded decision (handled here),
# 1 = unexplained (the caller records a FAIL).
#
# Only a name the writer itself wraps in `optional` can be explained this way.
# The manifest is a file in the generation, and "a CORE store is never listed
# there" was a property of the writer, not of this reader: a stray or forged
# row naming user_kv.sqlite must still fail, not pass as a recorded skip.
# Lockstep with the `optional backup_*` calls in riskit-state-backup.sh is
# pinned by tests/deploy/test_state_backup_optional_stores.py.
KNOWN_OPTIONAL_STORES=" intel_ledger.sqlite3 market_trades_archive.sqlite market_trades_reports own_league_format_captures.sqlite source_archive_boards.sqlite bdvm forecast_archive pick_forecast_snapshots sparse_evidence_shadow robust_filter_shadow signals_sources consensus_edge.sqlite dfs_workspace.sqlite temporal_ledger.sqlite "
optional_absence_explained() {
    local name="$1" label="$2" status
    if [[ "${KNOWN_OPTIONAL_STORES}" != *" ${name} "* ]]; then
        return 1
    fi
    status="$(optional_status "${name}")"
    case "${status}" in
        skipped_requested)
            log "${label}: not in this generation by request (BACKUP_SKIP_OPTIONAL) — not proven here; the nightly carries it"
            return 0 ;;
        failed|skipped_low_space|skipped_space_unmeasurable)
            note_optional_warning "${label}: OPTIONAL store NOT in this generation (writer recorded: ${status})"
            return 0 ;;
    esac
    return 1
}

# ── SQLite: restore, integrity-check, read schema + counts ───────────
# $1 source path under DATA_DIR · $2 basename in the backup · $3 label
# $4.. tables whose row counts to report
prove_sqlite() {
    local src="$1" name="$2" label="$3"; shift 3
    local gz="${GEN}/sqlite/${name}.gz"

    if [[ ! -f "${src}" && ! -f "${gz}" ]]; then
        if ! backup_source_absent "${src}"; then
            note_fail "${label}: source ${src} cannot be resolved by $(id -un) — it may EXIST and be unreadable (permission on it or on a parent, or an unresolved path), so it may be silently outside this generation; refusing to record it as a stream that has not started"
            return 0
        fi
        log "${label}: SOURCE ABSENT, not backed up — stream has not started (not a failure)"
        return 0
    fi
    if [[ ! -f "${src}" ]]; then
        if ! backup_source_absent "${src}"; then
            note_fail "${label}: source ${src} cannot be resolved by $(id -un) — it may EXIST and be unreadable (permission on it or on a parent, or an unresolved path), so it may be silently outside this generation; refusing to record it as a stream that has not started"
            return 0
        fi
        # Present in the backup: PROVE it rather than waving it through.
        log "${label}: source absent, backup present (older generation) — proving it from the backup"
    fi
    if [[ ! -f "${gz}" ]]; then
        optional_absence_explained "${name}" "${label}" && return 0
        note_fail "${label}: EXISTS at ${src} but is MISSING from the backup (${gz})"
        return 0
    fi

    local out="${RESTORE_DIR}/${name}"
    if ! gunzip -c "${gz}" > "${out}"; then
        note_fail "${label}: gunzip failed"
        return 0
    fi
    log "${label}: restored $(stat -c%s "${out}" 2>/dev/null || echo '?') bytes from $(stat -c%s "${gz}" 2>/dev/null || echo '?') compressed"

    if ! "${PYTHON_BIN}" - "${out}" "${label}" "$@" <<'PY'
import sqlite3, sys
path, label = sys.argv[1], sys.argv[2]
tables = sys.argv[3:]
con = sqlite3.connect(path)
try:
    rows = [str(r[0]) for r in con.execute("PRAGMA integrity_check")]
    if rows != ["ok"]:
        print(f"[backup-proof][FAIL] {label}: integrity_check -> {rows}", file=sys.stderr)
        sys.exit(1)
    print(f"[backup-proof] {label}: PRAGMA integrity_check = ok")
    present = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    print(f"[backup-proof] {label}: schema tables = {sorted(present)}")
    try:
        ver = con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        print(f"[backup-proof] {label}: schema_version = {ver[0] if ver else 'absent'}")
    except sqlite3.Error:
        pass
    missing = [t for t in tables if t not in present]
    if missing:
        print(f"[backup-proof][FAIL] {label}: expected table(s) missing: {missing}", file=sys.stderr)
        sys.exit(1)
    for t in tables:
        n = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"[backup-proof] {label}: {t} rows = {n}")
finally:
    con.close()
PY
    then
        note_fail "${label}: restored database failed verification"
    else
        note_proven
    fi
}

# ── Plain file (gzipped) ─────────────────────────────────────────────
prove_file() {
    local src="$1" name="$2" label="$3"
    local gz="${GEN}/files/${name}.gz"

    if [[ ! -f "${src}" && ! -f "${gz}" ]]; then
        if ! backup_source_absent "${src}"; then
            note_fail "${label}: source ${src} cannot be resolved by $(id -un) — it may EXIST and be unreadable (permission on it or on a parent, or an unresolved path), so it may be silently outside this generation; refusing to record it as a stream that has not started"
            return 0
        fi
        log "${label}: SOURCE ABSENT, not backed up — stream has not started (not a failure)"
        return 0
    fi
    if [[ ! -f "${src}" ]]; then
        if ! backup_source_absent "${src}"; then
            note_fail "${label}: source ${src} cannot be resolved by $(id -un) — it may EXIST and be unreadable (permission on it or on a parent, or an unresolved path), so it may be silently outside this generation; refusing to record it as a stream that has not started"
            return 0
        fi
        log "${label}: source absent, backup present (older generation) — proving it from the backup"
    fi
    if [[ ! -f "${gz}" ]]; then
        optional_absence_explained "${name}" "${label}" && return 0
        note_fail "${label}: EXISTS at ${src} but is MISSING from the backup (${gz})"
        return 0
    fi
    if ! gzip -t "${gz}"; then
        note_fail "${label}: gzip integrity check failed"
        return 0
    fi
    local out="${RESTORE_DIR}/${name}"
    gunzip -c "${gz}" > "${out}"
    local lines
    lines="$(wc -l < "${out}" | tr -d ' ')"
    log "${label}: restored, gzip -t ok, ${lines} line(s)"
    note_proven
    # JSONL: prove it parses rather than merely existing.
    if [[ "${name}" == *.jsonl ]]; then
        if ! "${PYTHON_BIN}" - "${out}" "${label}" <<'PY'
import json, sys
path, label = sys.argv[1], sys.argv[2]
good = bad = 0
with open(path, encoding="utf-8") as fh:
    for line in fh:
        line = line.strip()
        if not line:
            continue
        try:
            json.loads(line); good += 1
        except ValueError:
            bad += 1
print(f"[backup-proof] {label}: {good} parseable record(s), {bad} unparseable")
# A trailing torn line is tolerable (append-only log); wholesale
# corruption is not.
sys.exit(1 if bad > 1 else 0)
PY
        then
            note_fail "${label}: restored JSONL did not parse"
        fi
    fi
}

# ── Directory (tar.gz) ───────────────────────────────────────────────
prove_dir() {
    local src="$1" name="$2" label="$3"
    local tgz="${GEN}/dirs/${name}.tar.gz"

    if [[ ! -d "${src}" && ! -f "${tgz}" ]]; then
        if ! backup_source_absent "${src}"; then
            note_fail "${label}: source ${src} cannot be resolved by $(id -un) — it may EXIST and be unreadable (permission on it or on a parent, or an unresolved path), so it may be silently outside this generation; refusing to record it as a stream that has not started"
            return 0
        fi
        log "${label}: SOURCE ABSENT, not backed up — stream has not started (not a failure)"
        return 0
    fi
    if [[ ! -d "${src}" ]]; then
        if ! backup_source_absent "${src}"; then
            note_fail "${label}: source ${src} cannot be resolved by $(id -un) — it may EXIST and be unreadable (permission on it or on a parent, or an unresolved path), so it may be silently outside this generation; refusing to record it as a stream that has not started"
            return 0
        fi
        log "${label}: source absent, backup present (older generation) — proving it from the backup"
    fi
    if [[ ! -f "${tgz}" ]]; then
        optional_absence_explained "${name}" "${label}" && return 0
        note_fail "${label}: EXISTS at ${src} but is MISSING from the backup (${tgz})"
        return 0
    fi
    if ! tar -tzf "${tgz}" >/dev/null; then
        note_fail "${label}: tar integrity check failed"
        return 0
    fi
    local entries src_entries
    entries="$(tar -tzf "${tgz}" | grep -cv '/$' || true)"
    if [[ -d "${src}" ]]; then
        # An UNGUARDED find dies under `set -e` on a partially unreadable
        # source, killing the sweep with no diagnostic; a `|| true` would
        # undercount instead, and an undercount lets an empty restore pass
        # the zero-check below. So a walk that cannot complete is a FAIL.
        if ! src_entries="$(find "${src}" -type f 2>/dev/null | wc -l | tr -d ' ')"; then
            note_fail "${label}: source ${src} could not be enumerated — coverage cannot be established"
            return 0
        fi
    else
        src_entries=0
    fi
    mkdir -p "${RESTORE_DIR}/${name}"
    tar -xzf "${tgz}" -C "${RESTORE_DIR}/${name}"
    local restored
    restored="$(find "${RESTORE_DIR}/${name}" -type f | wc -l | tr -d ' ')"
    log "${label}: restored ${restored} file(s) (archive listed ${entries}, source holds ${src_entries})"
    note_proven
    if [[ "${restored}" -eq 0 && "${src_entries}" -gt 0 ]]; then
        note_fail "${label}: source has ${src_entries} file(s) but the restore produced none"
    fi
}

log "── retention artifacts ──────────────────────────────────────────"

prove_sqlite "${DATA_DIR}/retention/evidence.sqlite" "evidence.sqlite" \
    "C1-RET-04/05 evidence.sqlite" scoring_card_observations scoring_card_payloads trending_observations

# PRIVATE. Schema + counts only; the loop above prints no payload column.
prove_sqlite "${DATA_DIR}/retention/league_events.sqlite" "league_events.sqlite" \
    "C1-RET-06 league_events.sqlite (PRIVATE)" league_transactions

prove_sqlite "${DATA_DIR}/board_history.sqlite" "board_history.sqlite" \
    "C1-RET-02 board_history.sqlite" board_history

prove_file "${DATA_DIR}/rank_history.jsonl" "rank_history.jsonl" "C1-RET-03 rank_history.jsonl"

prove_dir "${DATA_DIR}/faab"              "faab"              "C1-RET-01 faab/"
prove_dir "${DATA_DIR}/identity"          "identity"          "C1-RET-07 identity/"
prove_dir "${DATA_DIR}/playerctx/history" "playerctx_history" "C1-RET-08 playerctx history/"

# C5-GD-02: the Game Day pregame archive. riskit-state-backup.sh's own
# header calls this "THE most irreplaceable artifact in this list" and
# writes it (backup_dir "${DATA_DIR}/game_day", :427) — but until now
# nothing here restored or verified it, so a backup that WROTE
# game_day.tar.gz and a proof run that never opened it could both go
# green while W1-03's literal bar ("restored and verified", not merely
# written) stayed unmet. Same function, same privacy posture (counts
# and tar integrity only, no payload) as every artifact above it.
prove_dir "${DATA_DIR}/game_day"          "game_day"          "C5-GD-02 game_day/"

# ── AL-P2 OPTIONAL stores: the SMALL ones only ───────────────────────
# Integrity check + schema listing (no row counts: the proof does not
# hard-code these stores' table names).  Measured on the box 2026-10-02:
# KTC trade archive 0.8 MB, own-league captures 0.08 MB, format boards
# 1.5 MB, Consensus Edge 42 MB, DFS workspace 100 MB, the directories under
# 30 MB.  DELIBERATELY NOT HERE: the temporal ledger (1.5 GB) and the intel
# ledger online copy (0.7 GB).  Restoring and integrity-checking those on
# every deploy would spend most of the 20-minute job budget on two stores;
# the proof run does not even write them (PROOF_SKIP_OPTIONAL above).  Their
# restore path is documented in deploy/backup/README.md and exercised by
# hand against a nightly generation.
log "── AL-P2 optional artifacts (small) ─────────────────────────────"
prove_sqlite "${DATA_DIR}/market_trades/archive.sqlite" "market_trades_archive.sqlite" \
    "AL-P2 market_trades archive (PRIVATE)"
prove_sqlite "${DATA_DIR}/leagues/own_league_format_captures.sqlite" "own_league_format_captures.sqlite" \
    "AL-P2 own-league format captures"
prove_sqlite "${DATA_DIR}/source_archive/boards.sqlite" "source_archive_boards.sqlite" \
    "AL-P2 KTC format-variant boards"
prove_sqlite "${DATA_DIR}/consensus_edge.sqlite" "consensus_edge.sqlite" \
    "AL-P2 Consensus Edge labels"
prove_sqlite "${DATA_DIR}/dfs/workspace.sqlite" "dfs_workspace.sqlite" \
    "AL-P2 DFS workspace"
prove_dir "${DATA_DIR}/market_trades/reports" "market_trades_reports" "AL-P2 market_trades reports/"
prove_dir "${DATA_DIR}/bdvm"                    "bdvm"                    "AL-P2 bdvm/"
prove_dir "${DATA_DIR}/forecast_archive"        "forecast_archive"        "AL-P2 forecast_archive/"
prove_dir "${DATA_DIR}/pick_forecast_snapshots" "pick_forecast_snapshots" "AL-P2 pick_forecast_snapshots/"
prove_dir "${DATA_DIR}/sparse_evidence_shadow"  "sparse_evidence_shadow"  "AL-P2 sparse_evidence_shadow/"
prove_dir "${DATA_DIR}/robust_filter_shadow"    "robust_filter_shadow"    "AL-P2 robust_filter_shadow/"
prove_dir "${DATA_DIR}/sources/signals"         "signals_sources"         "Signals private store sources/signals/"

log "─────────────────────────────────────────────────────────────────"
if (( FAILURES > 0 )); then
    warn "${FAILURES} artifact(s) failed backup/restore proof"
    exit 2
fi

# "No artifact failed" is TRUE of a run that read nothing at all. The writer
# discards any snapshot with ARTIFACTS == 0 and never promotes it, so a
# certified directory holding no artifact is not a generation — announcing a
# proof over one is the vacuous-success shape this whole script exists to
# remove. Measured against a corrupt current generation that was never opened.
#
# The floor counts the WHOLE generation, not the seven retention artifacts:
# a host whose retention streams have legitimately not started still carries
# its core state (user_kv + session_store), so it stays green — and the
# printed counts make a zero visible instead of implied.
GEN_HELD="$(find "${GEN}" -type f 2>/dev/null | wc -l | tr -d ' ')"
if (( GEN_HELD == 0 )); then
    warn "certified generation ${GEN} holds NO artifact at all — the writer discards any snapshot with zero artifacts, so this directory is not a generation; refusing to announce a proof over an empty one"
    exit 2
fi
if (( OPTIONAL_WARNINGS > 0 )); then
    log "backup + restore proven: ${PROVEN} retention artifact(s) restored and verified, ${GEN_HELD} artifact(s) in the generation — WITH ${OPTIONAL_WARNINGS} optional-store warning(s)"
    exit 0
fi
log "backup + restore proven: ${PROVEN} retention artifact(s) restored and verified, ${GEN_HELD} artifact(s) in the generation"
exit 0
