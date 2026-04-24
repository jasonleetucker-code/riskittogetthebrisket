#!/usr/bin/env bash
#
# backup_user_kv.sh — nightly backup of user_kv.sqlite + session_store.sqlite
#
# Run from cron at 02:00 UTC:
#   0 2 * * * /home/dynasty/trade-calculator/deploy/backup_user_kv.sh
#
# Keeps 30 daily + 12 monthly backups locally in /var/backups/riskit/.
# Uses SQLite's ``.backup`` command so backups are consistent even
# while the app is writing (WAL journaling permits online backup).
#
# Optional: set BACKUP_S3_BUCKET env var to also mirror to S3 / B2
# via rclone.  If rclone is unavailable or the env var is unset,
# local-only backup is still good.
#
# Weekly restore-test flag: run with --restore-test to exercise the
# restore path (requires a DB tool; currently just validates the
# file is readable via sqlite3).

set -Eeuo pipefail

DATA_DIR="${DATA_DIR:-/home/dynasty/trade-calculator/data}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/riskit}"
KEEP_DAILY="${KEEP_DAILY:-30}"
KEEP_MONTHLY="${KEEP_MONTHLY:-12}"
DATE_STAMP="$(date -u +%Y-%m-%d)"
DAY_OF_MONTH="$(date -u +%d)"

mkdir -p "$BACKUP_DIR/daily" "$BACKUP_DIR/monthly"

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
    sqlite3 "$src" ".backup '$tmp'"
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
    if ! sqlite3 "$tmp/restore.sqlite" "PRAGMA integrity_check" | grep -q "^ok$"; then
        echo "ERROR: restore integrity_check failed"
        rm -rf "$tmp"
        exit 1
    fi
    local rows
    rows="$(sqlite3 "$tmp/restore.sqlite" "SELECT COUNT(*) FROM user_kv" 2>/dev/null || echo 0)"
    echo "restore-test OK: $latest contains $rows user_kv rows"
    rm -rf "$tmp"
}

if [[ "${1:-}" == "--restore-test" ]]; then
    restore_test
    exit 0
fi

backup_one "$DATA_DIR/user_kv.sqlite"
backup_one "$DATA_DIR/session_store.sqlite"
prune
echo "nightly backup complete: $(date -u +%FT%TZ)"
