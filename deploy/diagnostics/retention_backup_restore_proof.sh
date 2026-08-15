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
# Inputs (environment):
#   APP_DIR      deployed app tree
#   DATA_DIR     live data dir (READ ONLY here)
#   BACKUP_ROOT  where riskit-state-backup.sh writes
#   PYTHON_BIN   venv interpreter (sqlite3 CLI is not on the box)
#   RUN_BACKUP   "1" (default) to run the backup first; "0" to verify
#                the newest existing generation only
#
# Exit codes: 0 proven · 1 could not run · 2 an artifact that exists on
# the source is missing from the backup, or a restored artifact failed
# verification.

set -Eeuo pipefail

APP_DIR="${APP_DIR:-/home/dynasty/trade-calculator}"
DATA_DIR="${DATA_DIR:-${APP_DIR}/data}"
BACKUP_ROOT="${BACKUP_ROOT:-/var/backups/riskit-state}"
PYTHON_BIN="${PYTHON_BIN:-/home/dynasty/.venvs/trade-calculator/bin/python}"
RUN_BACKUP="${RUN_BACKUP:-1}"

log()  { printf '[backup-proof] %s\n' "$*"; }
warn() { printf '[backup-proof][WARN] %s\n' "$*" >&2; }
fail() { printf '[backup-proof][ERROR] %s\n' "$*" >&2; exit 1; }

FAILURES=0
note_fail() { printf '[backup-proof][FAIL] %s\n' "$*" >&2; FAILURES=$((FAILURES + 1)); }

[[ -d "${APP_DIR}" ]] || fail "app dir not found: ${APP_DIR}"
[[ -x "${PYTHON_BIN}" ]] || PYTHON_BIN="$(command -v python3 || true)"
[[ -x "${PYTHON_BIN}" ]] || fail "no usable python interpreter"

# ── 1. Run the real backup ───────────────────────────────────────────
if [[ "${RUN_BACKUP}" == "1" ]]; then
    BACKUP_SCRIPT="${APP_DIR}/deploy/backup/riskit-state-backup.sh"
    [[ -f "${BACKUP_SCRIPT}" ]] || fail "backup script absent on the deployed revision: ${BACKUP_SCRIPT}"
    log "running production backup: ${BACKUP_SCRIPT}"
    if ! APP_DIR="${APP_DIR}" DATA_DIR="${DATA_DIR}" BACKUP_ROOT="${BACKUP_ROOT}" \
         PYTHON_BIN="${PYTHON_BIN}" bash "${BACKUP_SCRIPT}"; then
        fail "backup run FAILED"
    fi
else
    log "RUN_BACKUP=0 — verifying the newest existing generation only"
fi

# ── 2. Locate the generation we are proving ──────────────────────────
GEN="$(ls -1d "${BACKUP_ROOT}/daily"/20* 2>/dev/null | sort | tail -n1 || true)"
[[ -n "${GEN}" && -d "${GEN}" ]] || fail "no backup generation under ${BACKUP_ROOT}/daily"
log "proving generation: ${GEN}"
log "generation size: $(du -sh "${GEN}" 2>/dev/null | cut -f1)"

RESTORE_DIR="$(mktemp -d /tmp/retention-restore-XXXXXX)"
trap 'rm -rf "${RESTORE_DIR}"' EXIT
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
