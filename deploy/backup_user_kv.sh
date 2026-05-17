#!/usr/bin/env bash
#
# backup_user_kv.sh — nightly backup of user_kv.sqlite + session_store.sqlite + guest_passes.sqlite
#
# Run from cron at 02:00 UTC:
#   0 2 * * * /home/dynasty/trade-calculator/deploy/backup_user_kv.sh
#
# Keeps 30 daily + 12 monthly backups locally in /var/backups/riskit/
# (falls back to /home/dynasty/backups/riskit if that needs root).
# Uses the Python stdlib sqlite3 Connection.backup() primitive (the
# sqlite3 CLI is not installed) so backups are consistent even while
# the app is writing (WAL journaling permits online backup).
#
# Optional: set BACKUP_S3_BUCKET env var to also mirror to S3 / B2
# via rclone.  If rclone is unavailable or the env var is unset,
# local-only backup is still good.
#
# Weekly restore-test flag: run with --restore-test to exercise the
# restore path (decompress latest daily, run PRAGMA integrity_check
# and a row count via the Python sqlite3 module).

set -Eeuo pipefail

DATA_DIR="${DATA_DIR:-/home/dynasty/trade-calculator/data}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/riskit}"
KEEP_DAILY="${KEEP_DAILY:-30}"
KEEP_MONTHLY="${KEEP_MONTHLY:-12}"
DATE_STAMP="$(date -u +%Y-%m-%d)"
DAY_OF_MONTH="$(date -u +%d)"

BACKUP_FALLBACK_DIR="${BACKUP_FALLBACK_DIR:-/home/dynasty/backups/riskit}"

PYTHON_BIN="${PYTHON_BIN:-/home/dynasty/.venvs/trade-calculator/bin/python}"
[[ -x "$PYTHON_BIN" ]] || PYTHON_BIN="$(command -v python3 || true)"
if [[ -z "$PYTHON_BIN" ]]; then
    echo "BACKUP-FAILED: no python interpreter available for sqlite backup" >&2
    exit 1
fi

# Online, WAL-safe SQLite backup via the Python stdlib sqlite3 module.
# Connection.backup() is the same online-backup primitive the sqlite3
# CLI's ``.backup`` exposes; the CLI is not installed on this host.
sqlite_backup() {
    "$PYTHON_BIN" - "$1" "$2" <<'PY'
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

sqlite_query() {
    "$PYTHON_BIN" - "$1" "$2" <<'PY'
import sqlite3, sys
db, sql = sys.argv[1], sys.argv[2]
con = sqlite3.connect(db)
try:
    for row in con.execute(sql):
        print("|".join("" if v is None else str(v) for v in row))
finally:
    con.close()
PY
}

ensure_backup_dir() {
    # Primary location first.  If it cannot be created or is not
    # writable, fall back to a directory the 'dynasty' service user
    # owns.  (/var/backups needs root; that permission failure killed
    # backups silently for weeks — the fallback makes that impossible.)
    if mkdir -p "$BACKUP_DIR/daily" "$BACKUP_DIR/monthly" 2>/dev/null \
        && [[ -w "$BACKUP_DIR/daily" ]]; then
        return 0
    fi
    local reason="primary backup dir '$BACKUP_DIR' not writable"
    BACKUP_DIR="$BACKUP_FALLBACK_DIR"
    if mkdir -p "$BACKUP_DIR/daily" "$BACKUP_DIR/monthly" 2>/dev/null \
        && [[ -w "$BACKUP_DIR/daily" ]]; then
        echo "BACKUP-DEGRADED: $reason, using fallback '$BACKUP_DIR'" >&2
        return 0
    fi
    echo "BACKUP-FAILED: neither primary nor fallback '$BACKUP_DIR' writable" >&2
    exit 1
}

ensure_backup_dir

backup_one() {
    local src="$1"
    local name="$(basename "$src")"
    local dst="$BACKUP_DIR/daily/${name%.sqlite}.${DATE_STAMP}.sqlite.gz"
    if [[ ! -f "$src" ]]; then
        echo "skip: $src does not exist"
        return 0
    fi
    # Online backup via SQLite's own .backup command — safe under
    # concurrent writes (WAL).
    local tmp="${BACKUP_DIR}/daily/${name%.sqlite}.${DATE_STAMP}.sqlite"
    sqlite_backup "$src" "$tmp"
    gzip -f "$tmp"
    echo "backed up: $src → $dst"
    # On the 1st of the month, promote into monthly retention.
    if [[ "$DAY_OF_MONTH" == "01" ]]; then
        cp "$dst" "$BACKUP_DIR/monthly/"
    fi
}

prune() {
    find "$BACKUP_DIR/daily" -name "*.sqlite.gz" -mtime "+${KEEP_DAILY}" -delete
    find "$BACKUP_DIR/monthly" -name "*.sqlite.gz" -mtime "+$((KEEP_MONTHLY * 31))" -delete
}

restore_test() {
    # Pick the most recent daily; decompress into tmp; query one row.
    local latest
    latest="$(ls -1t "$BACKUP_DIR/daily"/user_kv.*.sqlite.gz 2>/dev/null | head -n1 || true)"
    if [[ -z "$latest" ]]; then
        echo "ERROR: no daily backups found"
        exit 1
    fi
    local tmp
    tmp="$(mktemp -d)"
    gunzip -c "$latest" > "$tmp/restore.sqlite"
    # Simple integrity check.
    if ! sqlite_query "$tmp/restore.sqlite" "PRAGMA integrity_check" | grep -q "^ok$"; then
        echo "ERROR: restore integrity_check failed"
        rm -rf "$tmp"
        exit 1
    fi
    local rows
    rows="$(sqlite_query "$tmp/restore.sqlite" "SELECT COUNT(*) FROM user_kv" 2>/dev/null || echo 0)"
    echo "restore-test OK: $latest contains $rows user_kv rows"
    rm -rf "$tmp"
}

if [[ "${1:-}" == "--restore-test" ]]; then
    restore_test
    exit 0
fi

backup_one "$DATA_DIR/user_kv.sqlite"
backup_one "$DATA_DIR/session_store.sqlite"
backup_one "$DATA_DIR/guest_passes.sqlite"
prune
echo "nightly backup complete: $(date -u +%FT%TZ)"
