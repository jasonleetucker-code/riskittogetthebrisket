#!/usr/bin/env bash
#
# riskit-state-backup.sh — nightly LOCAL backup of all irreplaceable
# production state (everything that cannot be regenerated from the repo
# or re-scraped):
#
#   * data/user_kv.sqlite        — user settings / watchlists / league prefs
#   * data/session_store.sqlite  — login sessions
#   * data/guest_passes.sqlite   — guest pass grants
#   * data/public_league/        — public-league snapshots & identity
#   * data/intel/                — intel artifacts (guarded: may not exist yet)
#
#   C1A irreversible-evidence retention (docs/retention/RETENTION_REGISTER.md).
#   Every one of these records something that CANNOT be re-fetched once
#   it is gone — a rolling source window that has turned over, an
#   overwrite that has already landed, or a board that was computed and
#   discarded.  Losing the box loses the history permanently, which is
#   what makes them state and not cache:
#
#   * data/retention/evidence.sqlite     — per-observation scoring-card
#     history + Sleeper trending series (C1-RET-04, C1-RET-05)
#   * data/retention/league_events.sqlite — our own leagues'
#     transactions (C1-RET-06).  PRIVATE: real managers, real trades.
#     On-box like the session cookies; it may reach the off-box mirror
#     only because that destination is the operator's own.  It must
#     NEVER be committed or force-added to the public repository.
#   * data/board_history.sqlite  — canonical board as-of records
#     (C1-RET-02)
#   * data/rank_history.jsonl    — per-player rank series (C1-RET-03)
#   * data/faab/                 — KTC crowd-FAAB accumulator, whose
#     upstream is a ~5-day rolling window, plus per-league bid history
#     (C1-RET-01).  PRIVATE: contains our leagues' own claim history.
#   * data/identity/             — identity resolution reports
#     (C1-RET-07)
#   * data/playerctx/history/    — dated playerctx snapshots
#     (C1-RET-08).  The directory ONLY: data/playerctx/ next door holds
#     a 38 MB depth-chart CSV and a 14 MB Sleeper dump, both
#     regenerable, and neither belongs in a nightly generation.
#   * scraper session cookies    — dlf/draftsharks/idpshow *_session.json
#     from the repo root and the /var/lib/{dlf,idpshow}-fetch work dirs.
#     These are SECRETS: gitignored, manually provisioned (IDP Show's
#     captcha-gated login can ONLY be restored by hand-pasting browser
#     cookies).  They are backed up ON-BOX ONLY, mode 0600, and must
#     never be committed to the repo or pushed anywhere public.
#
# SQLite files are copied with the online-backup primitive
# (sqlite3.Connection.backup via the venv python — the sqlite3 CLI is
# not installed on the box), so they are consistent even while the app
# is writing (WAL).  Directories are tar.gz'd.  Every artifact gets an
# integrity check (gzip -t / tar -tzf) before the run reports success.
#
# Layout: $BACKUP_ROOT/daily/YYYY-MM-DD/...
# Rotation: keep the newest $KEEP_DAILY dated directories (default 14).
#
# Operation order (destructive steps strictly last):
#   write artifacts into a hidden staging dir → integrity checks →
#   required-artifact manifest check → FAILURE: discard staging,
#   exit 1 (daily/ namespace untouched) | SUCCESS: promote staging →
#   dated dir → off-box mirror (validated snapshots only) → prune
#   oldest generations beyond $KEEP_DAILY.
#
# Required-artifact manifest: a snapshot only counts as a generation
# when it contains the CORE state.  BACKUP_REQUIRED (space-separated
# basenames, default "user_kv.sqlite session_store.sqlite") lists the
# items that must have been successfully written and verified; a
# partial snapshot (e.g. DATA_DIR unmounted/mistyped while a stray
# session JSON still bumps the artifact count) is discarded instead of
# promoted, so it can never displace a COMPLETE older generation or
# reach the off-box mirror.  Dir names (public_league, intel) may be
# listed too, e.g. BACKUP_REQUIRED="user_kv.sqlite session_store.sqlite public_league".
#
# Off-box mirroring (OPTIONAL, operator-configured): set
# OFFBOX_RSYNC_DEST to an rsync destination (e.g.
# "backup@storagebox.example:riskit-state/") in a drop-in on
# riskit-state-backup.service.  When unset (default), the run is
# local-only.  See deploy/backup/README.md.
#
# Relationship to deploy/backup_user_kv.sh (riskit-backup.timer): that
# older job covers ONLY the three sqlite files but keeps 30 daily + 12
# monthly generations.  This job is a superset per-night with 14-day
# retention.  Keeping both enabled is safe (a few MB of duplicate
# sqlite gz per night) and preserves the long/monthly sqlite history.
#
# Exit codes: 0 success, 1 hard failure (no backup written or integrity
# check failed).  Unreadable OPTIONAL inputs (missing dirs, root-owned
# session files when run unprivileged) are logged and skipped.

set -Eeuo pipefail

APP_DIR="${APP_DIR:-/home/dynasty/trade-calculator}"
DATA_DIR="${DATA_DIR:-${APP_DIR}/data}"
BACKUP_ROOT="${BACKUP_ROOT:-/var/backups/riskit-state}"
BACKUP_FALLBACK_ROOT="${BACKUP_FALLBACK_ROOT:-/home/dynasty/backups/riskit-state}"
KEEP_DAILY="${KEEP_DAILY:-14}"
DATE_STAMP="$(date -u +%Y-%m-%d)"
OFFBOX_RSYNC_DEST="${OFFBOX_RSYNC_DEST:-}"
BACKUP_REQUIRED="${BACKUP_REQUIRED:-user_kv.sqlite session_store.sqlite}"

PYTHON_BIN="${PYTHON_BIN:-/home/dynasty/.venvs/trade-calculator/bin/python}"
[[ -x "${PYTHON_BIN}" ]] || PYTHON_BIN="$(command -v python3 || true)"

# Backups contain login-session secrets — never world/group readable.
umask 077

log()  { printf '[state-backup] %s\n' "$*"; }
warn() { printf '[state-backup][WARN] %s\n' "$*" >&2; }
fail() { printf '[state-backup][ERROR] %s\n' "$*" >&2; exit 1; }

[[ -n "${PYTHON_BIN}" ]] || fail "no python interpreter available for sqlite online backup"

# ── Destination (primary, then service-user fallback) ────────────────
ensure_root() {
    if mkdir -p "${BACKUP_ROOT}" 2>/dev/null && [[ -w "${BACKUP_ROOT}" ]]; then
        return 0
    fi
    warn "primary backup root '${BACKUP_ROOT}' not writable, using fallback"
    BACKUP_ROOT="${BACKUP_FALLBACK_ROOT}"
    if mkdir -p "${BACKUP_ROOT}" 2>/dev/null && [[ -w "${BACKUP_ROOT}" ]]; then
        return 0
    fi
    fail "neither primary nor fallback backup root writable"
}
ensure_root
chmod 700 "${BACKUP_ROOT}" 2>/dev/null || true

# Stage the snapshot in a hidden dir and promote it to the dated slot
# only after validation.  A failed run therefore never appears in the
# daily/ namespace at all: it cannot displace an old generation from
# the prune keep-window, and a failed same-day RERUN cannot clobber
# that day's earlier good snapshot.  (Dot-prefixed names are invisible
# to prune's `ls -1` and sort out of the retention math entirely.)
FINAL_DEST="${BACKUP_ROOT}/daily/${DATE_STAMP}"
DEST="${BACKUP_ROOT}/daily/.staging-${DATE_STAMP}-$$"
mkdir -p "${DEST}/sqlite" "${DEST}/dirs" "${DEST}/sessions" "${DEST}/files"

# Clear stale staging dirs from previous crashed runs (>1 day old).
find "${BACKUP_ROOT}/daily" -maxdepth 1 -name '.staging-*' -mtime +1 \
    -exec rm -rf {} + 2>/dev/null || true

ARTIFACTS=0
ERRORS=0
# Space-padded list of item names (sqlite basenames / dir names) that
# were successfully written AND integrity-checked — the required-
# artifact manifest is validated against this before promotion.
OK_LIST=" "

# ── SQLite (online, WAL-safe) ────────────────────────────────────────
sqlite_backup() {
    "${PYTHON_BIN}" - "$1" "$2" <<'PY'
import sqlite3, sys
src, dst = sys.argv[1], sys.argv[2]
con = sqlite3.connect(src)
try:
    bck = sqlite3.connect(dst)
    try:
        with bck:
            con.backup(bck)
    finally:
        bck.close()
finally:
    con.close()
PY
}

# PRAGMA integrity_check on the COPIED database.  gzip -t only proves
# the compressed stream is intact — structural corruption that
# Connection.backup() copies page-for-page passes it cleanly.  Exits
# nonzero unless the check returns exactly "ok" (an unreadable /
# not-a-database file raises and exits nonzero too).
sqlite_integrity_ok() {
    "${PYTHON_BIN}" - "$1" <<'PY'
import sqlite3, sys
con = sqlite3.connect(sys.argv[1])
try:
    rows = [str(r[0]) for r in con.execute("PRAGMA integrity_check")]
finally:
    con.close()
sys.exit(0 if rows == ["ok"] else 1)
PY
}

backup_sqlite() {
    local src="$1"
    local name
    name="$(basename "${src}")"
    if [[ ! -f "${src}" ]]; then
        log "skip sqlite (absent): ${src}"
        return 0
    fi
    local tmp="${DEST}/sqlite/${name}"
    local out="${tmp}.gz"
    if ! sqlite_backup "${src}" "${tmp}"; then
        warn "sqlite online backup FAILED: ${src}"
        ERRORS=$((ERRORS + 1))
        rm -f "${tmp}"
        return 0
    fi
    if ! sqlite_integrity_ok "${tmp}" 2>/dev/null; then
        warn "sqlite PRAGMA integrity_check FAILED on copied db: ${src} — source database is likely corrupt; artifact rejected"
        ERRORS=$((ERRORS + 1))
        rm -f "${tmp}"
        return 0
    fi
    gzip -f "${tmp}"
    if ! gzip -t "${out}"; then
        warn "integrity check FAILED: ${out}"
        ERRORS=$((ERRORS + 1))
        return 0
    fi
    ARTIFACTS=$((ARTIFACTS + 1))
    OK_LIST+="${name} "
    log "sqlite ok: ${src} -> ${out}"
}

# ── Single files (gzip, guarded) ─────────────────────────────────────
#
# For append-only logs that are neither a SQLite database nor a
# directory — today just data/rank_history.jsonl (C1-RET-03).  A plain
# copy is safe for it because the writer appends whole lines and the
# reader tolerates a truncated final line, so a copy taken mid-append
# loses at most the record being written and never corrupts the ones
# before it.
backup_file() {
    local src="$1"
    local name
    name="$(basename "${src}")"
    if [[ ! -f "${src}" ]]; then
        log "skip file (absent): ${src}"
        return 0
    fi
    local out="${DEST}/files/${name}.gz"
    if ! gzip -c "${src}" > "${out}"; then
        warn "gzip FAILED: ${src}"
        ERRORS=$((ERRORS + 1))
        rm -f "${out}"
        return 0
    fi
    if ! gzip -t "${out}"; then
        warn "integrity check FAILED: ${out}"
        ERRORS=$((ERRORS + 1))
        return 0
    fi
    ARTIFACTS=$((ARTIFACTS + 1))
    OK_LIST+="${name} "
    log "file ok: ${src} -> ${out}"
}

# ── Directories (tar.gz, guarded) ────────────────────────────────────
backup_dir() {
    local src="$1"
    # Optional archive label.  Needed where basename alone is ambiguous
    # on restore: data/playerctx/history would land as "history.tar.gz".
    local name="${2:-}"
    [[ -n "${name}" ]] || name="$(basename "${src}")"
    if [[ ! -d "${src}" ]]; then
        log "skip dir (absent): ${src}"
        return 0
    fi
    local out="${DEST}/dirs/${name}.tar.gz"
    if ! tar -czf "${out}" -C "$(dirname "${src}")" "${name}"; then
        warn "tar FAILED: ${src}"
        ERRORS=$((ERRORS + 1))
        rm -f "${out}"
        return 0
    fi
    if ! tar -tzf "${out}" >/dev/null; then
        warn "integrity check FAILED: ${out}"
        ERRORS=$((ERRORS + 1))
        return 0
    fi
    ARTIFACTS=$((ARTIFACTS + 1))
    OK_LIST+="${name} "
    log "dir ok: ${src} -> ${out}"
}

# ── Scraper session cookie files (secrets — on-box only) ─────────────
backup_session_file() {
    local src="$1"
    local label="$2"   # disambiguates repo copy vs /var/lib work-dir copy
    if [[ ! -f "${src}" ]]; then
        return 0
    fi
    if [[ ! -r "${src}" ]]; then
        warn "session file present but unreadable (run as root to include): ${src}"
        return 0
    fi
    local out="${DEST}/sessions/${label}"
    if cp -f "${src}" "${out}"; then
        chmod 600 "${out}"
        ARTIFACTS=$((ARTIFACTS + 1))
        log "session ok: ${src} -> ${out}"
    else
        warn "session copy FAILED: ${src}"
        ERRORS=$((ERRORS + 1))
    fi
}

backup_sqlite "${DATA_DIR}/user_kv.sqlite"
backup_sqlite "${DATA_DIR}/session_store.sqlite"
backup_sqlite "${DATA_DIR}/guest_passes.sqlite"

# C1A irreversible-evidence retention.  All guarded: a host that has not
# yet produced one of these logs "skip (absent)" and the run still
# succeeds, so adding them cannot turn a working nightly red.  They are
# deliberately NOT added to BACKUP_REQUIRED for the same reason — the
# required manifest exists to reject a snapshot that lost CORE state,
# and a stream that has legitimately not started yet is not that.
backup_sqlite "${DATA_DIR}/retention/evidence.sqlite"
backup_sqlite "${DATA_DIR}/retention/league_events.sqlite"
backup_sqlite "${DATA_DIR}/board_history.sqlite"
backup_file   "${DATA_DIR}/rank_history.jsonl"

backup_dir "${DATA_DIR}/public_league"
backup_dir "${DATA_DIR}/intel"
backup_dir "${DATA_DIR}/faab"
backup_dir "${DATA_DIR}/identity"
backup_dir "${DATA_DIR}/playerctx/history" "playerctx_history"

# Repo-root session files (gitignored via "*_session.json").
backup_session_file "${APP_DIR}/dlf_session.json"         "repo.dlf_session.json"
backup_session_file "${APP_DIR}/draftsharks_session.json" "repo.draftsharks_session.json"
backup_session_file "${APP_DIR}/idpshow_session.json"     "repo.idpshow_session.json"
# Fetcher work-dir copies (see deploy/dlf_fetch_and_push.sh /
# deploy/idpshow_fetch_and_push.sh).
backup_session_file "/var/lib/dlf-fetch/dlf_session.json"         "workdir.dlf_session.json"
backup_session_file "/var/lib/idpshow-fetch/idpshow_session.json" "workdir.idpshow_session.json"

# ── Validate this run BEFORE any destructive step ────────────────────
# Ordering is deliberate: write artifacts into staging → integrity
# checks (above) → on failure discard the staging dir and stop → only
# a fully validated snapshot is promoted, mirrored, or allowed to
# trigger pruning.  The original ordering pruned first, so a failing
# nightly (missing data dir, broken tool) still created its dated dir,
# displaced the oldest GOOD generation from the keep-window, and
# eroded one good backup per day of consecutive failures.
# Required-artifact manifest: the artifact COUNT alone is not enough —
# a misconfigured/unmounted DATA_DIR with a stray session JSON present
# still yields ARTIFACTS>0, and promoting that partial snapshot would
# let prune drop an older COMPLETE generation.  Every item named in
# BACKUP_REQUIRED must have been written and verified.
MISSING_REQUIRED=""
for req in ${BACKUP_REQUIRED}; do
    if [[ "${OK_LIST}" != *" ${req} "* ]]; then
        MISSING_REQUIRED+="${req} "
    fi
done

if (( ARTIFACTS == 0 )) || (( ERRORS > 0 )) || [[ -n "${MISSING_REQUIRED}" ]]; then
    if [[ -n "${MISSING_REQUIRED}" ]]; then
        warn "required artifact(s) missing from snapshot: ${MISSING_REQUIRED}(check DATA_DIR=${DATA_DIR})"
    fi
    warn "run FAILED (${ERRORS} error(s), ${ARTIFACTS} artifact(s), required-missing: ${MISSING_REQUIRED:-none}) — discarding staging snapshot; prior generations left untouched"
    rm -rf "${DEST}"
    exit 1
fi

# Promote: replace any earlier same-day snapshot only now that this
# one is fully validated.
rm -rf "${FINAL_DEST}"
mv "${DEST}" "${FINAL_DEST}"
DEST="${FINAL_DEST}"
log "snapshot promoted: ${FINAL_DEST}"

# ── Optional off-box mirror (operator opt-in) ────────────────────────
# Reached only with every artifact written and integrity-checked, so a
# partial/corrupt snapshot can never replace the off-box copy (rsync
# --delete makes a bad publish doubly destructive remotely).
MIRROR_FAILED=0
if [[ -n "${OFFBOX_RSYNC_DEST}" ]]; then
    if command -v rsync >/dev/null 2>&1; then
        if rsync -a --delete "${BACKUP_ROOT}/daily/" "${OFFBOX_RSYNC_DEST}"; then
            log "off-box mirror ok: ${OFFBOX_RSYNC_DEST}"
        else
            warn "off-box mirror FAILED (local backup unaffected)"
            MIRROR_FAILED=1
        fi
    else
        # The operator explicitly requested an off-box copy; a missing
        # rsync must surface as a failed run, not a silent skip.
        warn "OFFBOX_RSYNC_DEST set but rsync not installed — off-box mirror NOT performed"
        MIRROR_FAILED=1
    fi
fi

# ── Rotation: keep newest $KEEP_DAILY dated dirs ─────────────────────
# Runs last, and only after this run added a verified generation, so
# the keep-window always counts today's GOOD snapshot — never a failed
# stub.  (Safe even when the mirror failed above: the local snapshot
# is validated either way.)
prune() {
    local dir
    # Dated names sort lexicographically == chronologically.
    while IFS= read -r dir; do
        [[ -n "${dir}" ]] || continue
        log "prune: ${BACKUP_ROOT}/daily/${dir}"
        rm -rf "${BACKUP_ROOT:?}/daily/${dir}"
    done < <(ls -1 "${BACKUP_ROOT}/daily" 2>/dev/null | sort | head -n -"${KEEP_DAILY}")
}
prune

if (( MIRROR_FAILED )); then
    warn "completed locally (${ARTIFACTS} artifact(s) in ${DEST}) but off-box mirror failed"
    exit 1
fi
log "state backup complete: ${ARTIFACTS} artifact(s) in ${DEST} ($(date -u +%FT%TZ))"
