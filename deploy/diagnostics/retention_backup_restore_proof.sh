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
#
# Exit codes: 0 proven · 1 could not run · 2 an artifact that exists on
# the source is missing from the backup, or a restored artifact failed
# verification.

set -Eeuo pipefail

APP_DIR="${APP_DIR:-/home/dynasty/trade-calculator}"
DATA_DIR="${DATA_DIR:-${APP_DIR}/data}"
PYTHON_BIN="${PYTHON_BIN:-/home/dynasty/.venvs/trade-calculator/bin/python}"
RUN_BACKUP="${RUN_BACKUP:-1}"

log()  { printf '[backup-proof] %s\n' "$*"; }
warn() { printf '[backup-proof][WARN] %s\n' "$*" >&2; }
fail() { printf '[backup-proof][ERROR] %s\n' "$*" >&2; exit 1; }

FAILURES=0
note_fail() { printf '[backup-proof][FAIL] %s\n' "$*" >&2; FAILURES=$((FAILURES + 1)); }

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

# ── 1. Run the real backup ───────────────────────────────────────────
if [[ "${RUN_BACKUP}" == "1" ]]; then
    BACKUP_SCRIPT="${APP_DIR}/deploy/backup/riskit-state-backup.sh"
    [[ -f "${BACKUP_SCRIPT}" ]] || fail "backup script absent on the deployed revision: ${BACKUP_SCRIPT}"
    RESULT_FILE="$(mktemp /tmp/retention-backup-result-XXXXXX)"
    log "running production backup: ${BACKUP_SCRIPT}"
    if ! APP_DIR="${APP_DIR}" DATA_DIR="${DATA_DIR}" \
         BACKUP_ROOT="$(backup_root_primary)" \
         BACKUP_FALLBACK_ROOT="$(backup_root_fallback)" \
         BACKUP_RESULT_FILE="${RESULT_FILE}" \
         PYTHON_BIN="${PYTHON_BIN}" bash "${BACKUP_SCRIPT}"; then
        fail "backup run FAILED"
    fi
fi

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

# ── SQLite: restore, integrity-check, read schema + counts ───────────
# $1 source path under DATA_DIR · $2 basename in the backup · $3 label
# $4.. tables whose row counts to report
prove_sqlite() {
    local src="$1" name="$2" label="$3"; shift 3
    local gz="${GEN}/sqlite/${name}.gz"

    if [[ ! -f "${src}" ]]; then
        if [[ -f "${gz}" ]]; then
            log "${label}: source absent, backup present (older generation) — ok"
        else
            log "${label}: SOURCE ABSENT, not backed up — stream has not started (not a failure)"
        fi
        return 0
    fi
    if [[ ! -f "${gz}" ]]; then
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
    fi
}

# ── Plain file (gzipped) ─────────────────────────────────────────────
prove_file() {
    local src="$1" name="$2" label="$3"
    local gz="${GEN}/files/${name}.gz"

    if [[ ! -f "${src}" ]]; then
        log "${label}: SOURCE ABSENT, not backed up — stream has not started (not a failure)"
        return 0
    fi
    if [[ ! -f "${gz}" ]]; then
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

    if [[ ! -d "${src}" ]]; then
        log "${label}: SOURCE ABSENT, not backed up — stream has not started (not a failure)"
        return 0
    fi
    if [[ ! -f "${tgz}" ]]; then
        note_fail "${label}: EXISTS at ${src} but is MISSING from the backup (${tgz})"
        return 0
    fi
    if ! tar -tzf "${tgz}" >/dev/null; then
        note_fail "${label}: tar integrity check failed"
        return 0
    fi
    local entries src_entries
    entries="$(tar -tzf "${tgz}" | grep -cv '/$' || true)"
    src_entries="$(find "${src}" -type f | wc -l | tr -d ' ')"
    mkdir -p "${RESTORE_DIR}/${name}"
    tar -xzf "${tgz}" -C "${RESTORE_DIR}/${name}"
    local restored
    restored="$(find "${RESTORE_DIR}/${name}" -type f | wc -l | tr -d ' ')"
    log "${label}: restored ${restored} file(s) (archive listed ${entries}, source holds ${src_entries})"
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

log "─────────────────────────────────────────────────────────────────"
if (( FAILURES > 0 )); then
    warn "${FAILURES} artifact(s) failed backup/restore proof"
    exit 2
fi
log "backup + restore proven for every artifact that exists"
exit 0
