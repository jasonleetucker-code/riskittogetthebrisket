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
#   * data/retention/acquisition.sqlite  — acquisition history, cost
#     basis and pick lineage (C1-ACQ-01..03).  Same PRIVATE class and
#     same rules as league_events.sqlite.  Its events are a normalised
#     projection and could in principle be rebuilt, but only from
#     evidence that is itself irreplaceable — realized auction prices
#     and out-of-window waiver claims that Sleeper no longer serves —
#     so losing it is losing history, not losing a cache.
#   * data/board_history.sqlite  — canonical board as-of records
#     (C1-RET-02)
#   * data/rank_history.jsonl    — per-player rank series (C1-RET-03)
#   * data/faab/                 — KTC crowd-FAAB accumulator, whose
#     upstream is a ~5-day rolling window, plus per-league bid history
#     (C1-RET-01).  PRIVATE: contains our leagues' own claim history.
#   * data/identity/             — identity resolution reports
#     (C1-RET-07)
#   * data/game_day/             — Game Day pre-game prediction snapshots + the pregame weekly-projection archive (live/_nfl/*/week_*/pregame_projections.json.gz)
#     (C5-GD-02).  THE most irreplaceable artifact in this list, and the
#     only one whose loss window is measured in hours: a pregame capture
#     records the state that produced a prediction BEFORE the outcome was
#     known, and once the week scores that state is gone.  Every other
#     entry here could at worst be re-derived from something; this one
#     could not be re-created even with unlimited access to Sleeper,
#     because the thing it records no longer exists.  Its own writer
#     refuses to reconstruct one after kickoff for exactly that reason.
#     PRIVATE: real rosters and per-player point estimates for our own
#     leagues; same rules as league_events.sqlite — never committed,
#     never force-added to the public repository.
#   * data/learning/receipts.sqlite — Adaptive Learning AL-0 receipts
#     (src/model_registry/receipt_store.py): the append-only record of what
#     each model was evaluated on and how it did.  PRIVATE decision
#     intelligence; same rules as league_events.sqlite.  Not a RET row —
#     see the 2026-10-01 addendum in docs/retention/RETENTION_REGISTER.md.
#   * AL-P2 perishable-evidence stores (2026-10-01; full list and the
#     include-vs-rebuildable reasoning beside the backup calls below and in
#     the register's AL-P2 addendum): the KTC trade archive, Consensus Edge
#     labels, KTC format-variant boards, own-league format captures, the
#     temporal ledger, the DFS workspace, an ONLINE copy of the intel ledger,
#     and the bdvm / forecast_archive / pick_forecast_snapshots / shadow
#     ledger directories.
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
# CORE vs OPTIONAL stores (AL-P2 review, 2026-10-01).  Every store that
# predates AL-P2 is CORE: a failed online copy, integrity check, gzip or tar
# on it fails the run and discards the whole generation, exactly as before.
# The AL-P2 additions are OPTIONAL (wrapped in `optional` below): a failure
# on one of them is a WARNING — the store is listed in the generation's
# `optional_stores.tsv` (name, status, detail) and the generation is KEPT.
# The reason is the intel ledger's corruption history on the box
# (ledger.sqlite3.corrupt, a 2026-08-01 recovery directory): latent
# corruption in one optional store must not stop user_kv / session_store
# being backed up every night.  OPTIONAL stores are also what a low-disk
# run sheds (see the free-space guard) and what BACKUP_SKIP_OPTIONAL may
# deliberately leave out (the post-deploy proof uses it for the two large
# stores).
#
# Exit codes:
#   0  success — every store that exists was backed up
#   1  hard failure (no backup written, a CORE store failed its integrity
#      check, required state missing, or the off-box mirror failed)
#   3  generation PROMOTED and every CORE store in it, but at least one
#      OPTIONAL store failed or was shed for disk space.  The unit maps it
#      to success (SuccessExitStatus=3) so a known-degraded optional store
#      does not mark the box failed every night; it stays visible as
#      ExecMainStatus=3, the WARN lines, and optional_stores.tsv.  Where it
#      surfaces: the post-deploy proof's OWN backup run annotates its own
#      exit 3 (that run skips the two large stores on purpose, so it can
#      only see a failure in the small ones), and the same proof reads the
#      nightly unit's last ExecMainStatus via `systemctl show` and annotates
#      a 3 there too — so a nightly exit 3 is surfaced at the next deploy,
#      not at 02:30.  Nothing pages on it in between; the root-only
#      optional_stores.tsv and `journalctl -u riskit-state-backup` name the
#      store.
# Unreadable OPTIONAL inputs (missing dirs, root-owned session files when
# run unprivileged) are logged and skipped.

set -Eeuo pipefail

APP_DIR="${APP_DIR:-/home/dynasty/trade-calculator}"
DATA_DIR="${DATA_DIR:-${APP_DIR}/data}"
# BACKUP_ROOT / BACKUP_FALLBACK_ROOT are read here as overrides only.
# Their DEFAULTS live in backup_root_lib.sh, sourced below, which is the
# single owner of where a backup goes — see the destination block.
KEEP_DAILY="${KEEP_DAILY:-14}"
# The generation date. Overridable like KEEP_DAILY / OFFBOX_RSYNC_DEST
# below it, and for the same reason: a caller that needs a deterministic
# generation name must be able to say so.
#
# Added 2026-08-17. ``tests/deploy/test_backup_root_resolution.py`` reads
# the UTC date once at module import and asserts on ``daily/${DATE_STAMP}``
# at thirty-odd sites, while this script read the clock when it ran — so a
# suite that straddled UTC midnight compared a generation the script had
# just created as ``2026-08-17`` against an expectation of ``2026-08-16``
# and failed a docs-only pull request at 00:03:49Z. Pinning the two
# together by construction is the fix; the default is unchanged, so
# production behaviour is identical unless someone exports it deliberately.
DATE_STAMP="${DATE_STAMP:-$(date -u +%Y-%m-%d)}"
OFFBOX_RSYNC_DEST="${OFFBOX_RSYNC_DEST:-}"
BACKUP_REQUIRED="${BACKUP_REQUIRED:-user_kv.sqlite session_store.sqlite}"
# OPTIONAL artifact names (the output name: label or basename) to leave out
# of this run on purpose.  Recorded as `skipped_requested`, not a warning.
BACKUP_SKIP_OPTIONAL="${BACKUP_SKIP_OPTIONAL:-}"
# Free-space floor for running the OPTIONAL stores at all: the run needs
# max(2 x the newest generation's size, this) free on the backup filesystem
# before it writes any of them.  5 GiB default.  Per optional store it also
# needs 2 x the source (raw copy + its gzip, the peak) + this margin.
BACKUP_MIN_FREE_KB="${BACKUP_MIN_FREE_KB:-5242880}"
BACKUP_STORE_MARGIN_KB="${BACKUP_STORE_MARGIN_KB:-1048576}"

PYTHON_BIN="${PYTHON_BIN:-/home/dynasty/.venvs/trade-calculator/bin/python}"
[[ -x "${PYTHON_BIN}" ]] || PYTHON_BIN="$(command -v python3 || true)"

# Backups contain login-session secrets — never world/group readable.
umask 077

log()  { printf '[state-backup] %s\n' "$*"; }
warn() { printf '[state-backup][WARN] %s\n' "$*" >&2; }
fail() { printf '[state-backup][ERROR] %s\n' "$*" >&2; exit 1; }

[[ -n "${PYTHON_BIN}" ]] || fail "no python interpreter available for sqlite online backup"
for _knob in BACKUP_MIN_FREE_KB BACKUP_STORE_MARGIN_KB; do
    [[ "${!_knob}" =~ ^[0-9]+$ ]] || fail "${_knob} must be a non-negative integer (KiB), got '${!_knob}'"
done
unset _knob

# ── Destination (primary, then service-user fallback) ────────────────
#
# Resolved by the SHARED owner, not here.  The requested primary root, the
# writability determination and the fallback are one decision made in one
# place, because the backup/restore proof has to inspect the location this
# run actually wrote to.  While each script resolved it independently, a
# fallback here left the proof reading an empty primary and reporting "no
# backup generation" for a backup that had succeeded (production proof run
# 31872681688).
BACKUP_ROOT_LIB="$(dirname "${BASH_SOURCE[0]}")/backup_root_lib.sh"
[[ -f "${BACKUP_ROOT_LIB}" ]] || fail "backup root library missing: ${BACKUP_ROOT_LIB}"
# shellcheck source=deploy/backup/backup_root_lib.sh
source "${BACKUP_ROOT_LIB}"

REQUESTED_ROOT="$(backup_root_primary)"
BACKUP_ROOT="$(backup_root_claim)" || fail "neither primary ('${REQUESTED_ROOT}') nor fallback ('$(backup_root_fallback)') backup root writable"
if [[ "${BACKUP_ROOT}" != "${REQUESTED_ROOT}" ]]; then
    warn "primary backup root '${REQUESTED_ROOT}' not writable, using fallback '${BACKUP_ROOT}'"
fi
log "effective backup root: ${BACKUP_ROOT}"
chmod 700 "${BACKUP_ROOT}" 2>/dev/null || true

# Stage the snapshot in a hidden dir and promote it to the dated slot
# only after validation.  A failed run therefore never appears in the
# daily/ namespace at all: it cannot displace an old generation from
# the prune keep-window, and a failed same-day RERUN cannot clobber
# that day's earlier good snapshot.  (Dot-prefixed names are invisible
# to prune's `ls -1` and sort out of the retention math entirely.)
FINAL_DEST="${BACKUP_ROOT}/daily/${DATE_STAMP}"
STAGING_DIR="${BACKUP_ROOT}/daily/.staging-${DATE_STAMP}-$$"
# Held (fd 9) for the whole run.  The kernel drops it when this process
# dies however it dies, which is what lets the sweep below tell a live
# run's staging from a dead one's without guessing from an mtime.
STAGING_LOCK="${STAGING_DIR}.lock"
DEST="${STAGING_DIR}"

# This run's staging is its own garbage the moment the run ends without
# promoting it — a failure, a SIGTERM from systemd's TimeoutStartSec, a
# Ctrl-C.  Before this trap only the explicit failure branch removed it,
# so a timed-out run (the AL-P2 stores made the run much longer) leaked a
# partial generation-sized directory that the old mtime +1 day sweep kept
# for another day.  STAGING_DIR is cleared on promotion.  Every step is
# guarded on its own: a failing rm inside an EXIT trap under errexit would
# replace the run's real exit status.
cleanup_staging() {
    [[ -z "${STAGING_DIR}" ]] || rm -rf "${STAGING_DIR}" 2>/dev/null || true
    [[ -z "${STAGING_LOCK}" ]] || rm -f "${STAGING_LOCK}" 2>/dev/null || true
    return 0
}
trap cleanup_staging EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

mkdir -p "${BACKUP_ROOT}/daily"
if command -v flock >/dev/null 2>&1; then
    exec 9>"${STAGING_LOCK}"
    flock -n 9 || fail "could not lock this run's staging (${STAGING_LOCK})"
else
    STAGING_LOCK=""
    warn "flock not installed — stale staging is recognised by PID only"
fi
# A same-named staging dir can only be a DEAD run's: the name carries this
# PID, so no other live process on the host can own it, and (with flock) this
# run now holds its lock.  It is left behind when a run dies in a way the trap
# cannot catch (SIGKILL, OOM, power loss) and its PID is reused later the same
# UTC day.  The sweep below skips this run's own name, so without this a reused
# staging would carry the dead run's partial artifacts — and a stale
# optional_stores.tsv — into this run's generation.
rm -rf "${STAGING_DIR}"
mkdir -p "${DEST}/sqlite" "${DEST}/dirs" "${DEST}/sessions" "${DEST}/files"

# Dated generations this writer could plausibly have produced, oldest first.
# ONE definition, shared by the keep-window, the mirror's continuity count and
# the free-space estimate — two answers to "what is a generation" is the class
# of bug this whole change exists to remove.
plausible_generations() {
    local dir
    while IFS= read -r -d '' dir; do
        dir="$(basename "${dir}")"
        [[ -n "${dir}" ]] || continue

        # POSITIVE recognition, not "did not look wrong". prune deletes with
        # `rm -rf`, so an entry it cannot account for as one of this writer's
        # own generations must never reach it — and, just as important, must
        # never consume a slot in the keep window. Measured before this guard:
        # a plain README.txt dropped into daily/ took a retention slot and a
        # REAL generation (2026-08-10) was deleted early to make room for it.
        #
        # Four independent things must hold. Shape alone is not enough: a
        # regular file, a symlink, or an impossible calendar date can all wear
        # a date-shaped name.
        [[ -d "${BACKUP_ROOT}/daily/${dir}" ]] || continue                 # a directory
        [[ ! -L "${BACKUP_ROOT}/daily/${dir}" ]] || continue               # not a symlink
        [[ "${dir}" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] || continue         # the writer's shape
        # A real calendar date: `date -d` rejects 2026-13-45, 2026-00-00 and
        # 2026-02-31, and the round-trip rejects 2026-8-1 and other loose forms.
        [[ "$(date -u -d "${dir}" +%Y-%m-%d 2>/dev/null)" == "${dir}" ]] || continue

        if backup_root_name_is_future "${dir}"; then
            warn "generation ${BACKUP_ROOT}/daily/${dir} is dated beyond the clock-skew bound (newest plausible $(backup_root_max_plausible_date)) — excluded from the keep window and NOT deleted; remove or re-date it"
            continue
        fi
        printf '%s\n' "${dir}"
    done < <(find "${BACKUP_ROOT}/daily" -mindepth 1 -maxdepth 1 -print0 2>/dev/null | sort -z)
}

# Is a staging dir still owned by a running writer?  0 = live (or not
# provably dead — leave it), 1 = dead (safe to remove).
staging_is_live() {
    local dir="$1" lock="$1.lock" pid
    if [[ -e "${lock}" ]] && command -v flock >/dev/null 2>&1; then
        # Acquiring it means nobody holds it.  Failing to — held, or a lock
        # this user cannot even open — is not proof of death.
        if flock -n "${lock}" true 2>/dev/null; then
            return 1
        fi
        return 0
    fi
    # No lock: a writer predating it (or a host without flock).  The PID is
    # the name's last field.  /proc, not `kill -0`: kill cannot tell "no such
    # process" from "someone else's process" by exit status, and the nightly
    # (root) and the proof (deploy user) are different users.
    pid="${dir##*-}"
    if [[ "${pid}" =~ ^[0-9]+$ ]]; then
        [[ -d "/proc/${pid}" ]] && return 0
        return 1
    fi
    # Not this writer's shape at all: only an old one counts as dead.
    [[ -n "$(find "${dir}" -maxdepth 0 -mtime +1 2>/dev/null)" ]] && return 1
    return 0
}

# Clear staging left by crashed or killed runs — any staging dir no live
# process holds, whatever its age.  The previous rule (mtime +1 day) kept a
# killed run's partial generation for a day, and with the temporal ledger in
# the run that is gigabytes on the same filesystem the next run needs.
sweep_stale_staging() {
    local entry
    for entry in "${BACKUP_ROOT}/daily"/.staging-*; do
        [[ -e "${entry}" || -L "${entry}" ]] || continue
        [[ "${entry}" == "${STAGING_DIR}" || "${entry}" == "${STAGING_DIR}.lock" ]] && continue
        if [[ "${entry}" == *.lock ]]; then
            # A lock whose staging dir is gone: drop it once nobody holds it.
            [[ -e "${entry%.lock}" ]] && continue
            if command -v flock >/dev/null 2>&1 && flock -n "${entry}" true 2>/dev/null; then
                rm -f "${entry}" 2>/dev/null || true
            fi
            continue
        fi
        if staging_is_live "${entry}"; then
            log "staging ${entry} belongs to a live run — left alone"
            continue
        fi
        log "removing stale staging from a dead run: ${entry}"
        rm -rf "${entry}" 2>/dev/null || warn "could not remove stale staging ${entry}"
        rm -f "${entry}.lock" 2>/dev/null || true
    done
}
sweep_stale_staging
# And stale pointer temp files.  These live one level ABOVE daily/, so
# neither the sweep above nor prune can reach them: a run killed between
# writing the temp and renaming it leaves one behind forever.
find "${BACKUP_ROOT}/" -maxdepth 1 -name 'last_generation.tmp.*' -mtime +1 \
    -delete 2>/dev/null || true

ARTIFACTS=0
ERRORS=0
# Space-padded list of item names (sqlite basenames / dir names) that
# were successfully written AND integrity-checked — the required-
# artifact manifest is validated against this before promotion.
OK_LIST=" "

# ── CORE / OPTIONAL classification ───────────────────────────────────
# STORE_CLASS is "core" except inside `optional <backup_fn> ...`.  The
# backup functions report a failed store through store_failed, which is the
# ONE place the two classes diverge: CORE counts an ERROR (the generation is
# discarded), OPTIONAL records a warning in the generation's manifest and
# keeps it.
STORE_CLASS="core"
OPTIONAL_ISSUES=0          # optional stores failed or shed for disk space
OPTIONAL_NOT_BACKED_UP=""  # their names, for the summary line
OPTIONAL_MANIFEST_NAME="optional_stores.tsv"
OPTIONAL_LOW_SPACE=""      # non-empty => every optional store is shed (reason)
OPTIONAL_LOW_SPACE_STATUS="skipped_low_space"  # its manifest status

optional() {
    STORE_CLASS="optional"
    "$@"
    STORE_CLASS="core"
}

# name<TAB>status<TAB>detail, one row per optional store NOT in this
# generation.  Written inside the generation so it travels with it (mirror,
# restore) and a restorer can see what is missing and why.
#
# The append is failure-TOLERANT on purpose.  It runs under errexit, and the
# likeliest moment for it to fail is the moment an optional store has just
# failed for lack of space (ENOSPC): an unguarded `>>` then exits 1 and the
# EXIT trap deletes the staging directory holding the CORE stores — failing to
# RECORD an optional failure would discard the very generation the optional
# class exists to protect.  The store is still counted in OPTIONAL_ISSUES and
# named on the WARN lines, so exit 3 and the journal carry it either way.
record_optional() {
    printf '%s\t%s\t%s\n' "$1" "$2" "$3" 2>/dev/null >> "${DEST}/${OPTIONAL_MANIFEST_NAME}" \
        || warn "could not record OPTIONAL store $1 ($2) in ${OPTIONAL_MANIFEST_NAME} — the generation is kept; this WARN line is the record"
}

store_failed() {
    local name="$1" reason="$2"
    if [[ "${STORE_CLASS:-core}" == "optional" ]]; then
        warn "OPTIONAL store ${name} is NOT in this generation (${reason}) — generation kept; CORE state unaffected"
        record_optional "${name}" "failed" "${reason}"
        OPTIONAL_ISSUES=$((OPTIONAL_ISSUES + 1))
        OPTIONAL_NOT_BACKED_UP+="${name} "
    else
        ERRORS=$((ERRORS + 1))
    fi
}

free_kb() {
    df -Pk "$1" 2>/dev/null | awk 'NR==2 {print $4}'
}

# Called by every backup function once it knows the store exists.
# Returns 1 to skip it.  CORE stores are never skipped.
optional_gate() {
    local name="$1" src="$2"
    [[ "${STORE_CLASS:-core}" == "optional" ]] || return 0
    if [[ " ${BACKUP_SKIP_OPTIONAL} " == *" ${name} "* ]]; then
        log "skip optional (BACKUP_SKIP_OPTIONAL): ${name}"
        record_optional "${name}" "skipped_requested" "BACKUP_SKIP_OPTIONAL"
        return 1
    fi
    local why="${OPTIONAL_LOW_SPACE:-}" status="${OPTIONAL_LOW_SPACE_STATUS:-skipped_low_space}"
    if [[ -z "${why}" ]]; then
        # Unknown is SHORT, not roomy: a source or a free-space figure that
        # cannot be measured skips the store, exactly as the run-level guard
        # treats an unmeasurable filesystem.  A live SQLite store's online
        # copy carries what is still in its -wal, so the WAL counts too.
        local src_kb wal_kb=0 avail
        src_kb="$(du -sk "${src}" 2>/dev/null | cut -f1)" || src_kb=""
        if [[ -f "${src}" && -e "${src}-wal" ]]; then
            wal_kb="$(du -sk "${src}-wal" 2>/dev/null | cut -f1)" || wal_kb=""
        fi
        avail="$(free_kb "${BACKUP_ROOT}")" || avail=""
        if [[ ! "${src_kb}" =~ ^[0-9]+$ || ! "${wal_kb}" =~ ^[0-9]+$ || ! "${avail}" =~ ^[0-9]+$ ]]; then
            why="space could not be measured (source ${src_kb:-?} KiB, wal ${wal_kb:-?} KiB, free ${avail:-?} KiB)"
            status="skipped_space_unmeasurable"
        else
            src_kb=$((src_kb + wal_kb))
            if (( avail < 2 * src_kb + BACKUP_STORE_MARGIN_KB )); then
                why="${avail} KiB free, store needs $((2 * src_kb + BACKUP_STORE_MARGIN_KB)) KiB (2 x ${src_kb} KiB source incl. WAL + margin)"
            fi
        fi
    fi
    if [[ -n "${why}" ]]; then
        warn "OPTIONAL store ${name} SKIPPED for disk space (${why}) — CORE state is still backed up"
        record_optional "${name}" "${status}" "${why}"
        OPTIONAL_ISSUES=$((OPTIONAL_ISSUES + 1))
        OPTIONAL_NOT_BACKED_UP+="${name} "
        return 1
    fi
    return 0
}

# ── Free-space guard (before anything is written) ────────────────────
# The OPTIONAL stores multiplied the generation (the temporal ledger alone
# is 1.5 GB raw), and a backup that fills the disk takes the app's own
# SQLite writes down with it.  So: measure first, and if the filesystem
# cannot hold max(2 x the newest generation, BACKUP_MIN_FREE_KB), shed every
# OPTIONAL store (warn, exit 3) and still back up CORE.  An unmeasurable
# filesystem is treated as short, not as roomy — unknown is not "enough".
#
# Every measurement below is `|| x=""`-guarded: under errexit + pipefail a
# failing `df` / `du` inside "$(...)" would otherwise exit the run (status 1,
# no generation) right here — the opposite of the promise above.
check_free_space() {
    local avail last_gen last_kb=0 need
    avail="$(free_kb "${BACKUP_ROOT}")" || avail=""
    last_gen="$(plausible_generations | tail -n 1)" || last_gen=""
    if [[ -n "${last_gen}" ]]; then
        last_kb="$(du -sk "${BACKUP_ROOT}/daily/${last_gen}" 2>/dev/null | cut -f1)" || last_kb=""
    fi
    [[ "${last_kb}" =~ ^[0-9]+$ ]] || last_kb=0
    need=$((2 * last_kb))
    (( need >= BACKUP_MIN_FREE_KB )) || need="${BACKUP_MIN_FREE_KB}"
    if [[ ! "${avail}" =~ ^[0-9]+$ ]]; then
        OPTIONAL_LOW_SPACE="free space on ${BACKUP_ROOT} could not be measured"
        OPTIONAL_LOW_SPACE_STATUS="skipped_space_unmeasurable"
    elif (( avail < need )); then
        OPTIONAL_LOW_SPACE="${avail} KiB free on ${BACKUP_ROOT}, need ${need} KiB (2 x newest generation ${last_kb} KiB, floor ${BACKUP_MIN_FREE_KB} KiB)"
    fi
    if [[ -n "${OPTIONAL_LOW_SPACE}" ]]; then
        warn "LOW DISK: every OPTIONAL store is skipped this run; CORE state is still backed up — ${OPTIONAL_LOW_SPACE}"
    else
        log "free space ok: ${avail} KiB free, need ${need} KiB"
    fi
}
check_free_space

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
    # Optional second argument renames the OUTPUT artifact (and the name the
    # required-artifact manifest sees), exactly as backup_dir's label does.
    # Needed because basenames are not unique across stores: two writers that
    # both call their file "archive.sqlite" would land on one
    # sqlite/archive.sqlite.gz and the second would silently replace the
    # first inside the same generation.  The SOURCE is always "$1".
    local name
    name="${2:-$(basename "${src}")}"
    if [[ ! -f "${src}" ]]; then
        # "(absent)" must mean PROVEN absent. `-f`/`-d` are false for
        # ENOENT *and* EACCES/ENOTDIR anywhere on the path, so a store
        # behind a 0700 ancestor or on a volume that failed to mount was
        # silently omitted from every generation under a reassuring line.
        # WARN rather than ERROR: the header's posture is that unreadable
        # OPTIONAL inputs are skipped, and failing here would discard
        # user_kv and session_store too. The prover is the fail-closed
        # authority; this is the visibility half.
        if backup_source_absent "${src}"; then
            log "skip sqlite (absent): ${src}"
        else
            warn "sqlite source NOT backed up and NOT provably absent: ${src} — it may exist and be unreadable by $(id -un); this generation omits it"
        fi
        return 0
    fi
    optional_gate "${name}" "${src}" || return 0
    local tmp="${DEST}/sqlite/${name}"
    local out="${tmp}.gz"
    if ! sqlite_backup "${src}" "${tmp}"; then
        warn "sqlite online backup FAILED: ${src}"
        rm -f "${tmp}"
        store_failed "${name}" "sqlite online backup failed"
        return 0
    fi
    if ! sqlite_integrity_ok "${tmp}" 2>/dev/null; then
        warn "sqlite PRAGMA integrity_check FAILED on copied db: ${src} — source database is likely corrupt; artifact rejected"
        rm -f "${tmp}"
        store_failed "${name}" "PRAGMA integrity_check failed on the copy"
        return 0
    fi
    if ! gzip -f "${tmp}"; then
        warn "gzip FAILED: ${tmp}"
        rm -f "${tmp}" "${out}"
        store_failed "${name}" "gzip failed"
        return 0
    fi
    if ! gzip -t "${out}"; then
        warn "integrity check FAILED: ${out}"
        rm -f "${out}"
        store_failed "${name}" "gzip -t failed"
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
        # "(absent)" must mean PROVEN absent. `-f`/`-d` are false for
        # ENOENT *and* EACCES/ENOTDIR anywhere on the path, so a store
        # behind a 0700 ancestor or on a volume that failed to mount was
        # silently omitted from every generation under a reassuring line.
        # WARN rather than ERROR: the header's posture is that unreadable
        # OPTIONAL inputs are skipped, and failing here would discard
        # user_kv and session_store too. The prover is the fail-closed
        # authority; this is the visibility half.
        if backup_source_absent "${src}"; then
            log "skip file (absent): ${src}"
        else
            warn "file source NOT backed up and NOT provably absent: ${src} — it may exist and be unreadable by $(id -un); this generation omits it"
        fi
        return 0
    fi
    optional_gate "${name}" "${src}" || return 0
    local out="${DEST}/files/${name}.gz"
    if ! gzip -c "${src}" > "${out}"; then
        warn "gzip FAILED: ${src}"
        rm -f "${out}"
        store_failed "${name}" "gzip failed"
        return 0
    fi
    if ! gzip -t "${out}"; then
        warn "integrity check FAILED: ${out}"
        rm -f "${out}"
        store_failed "${name}" "gzip -t failed"
        return 0
    fi
    ARTIFACTS=$((ARTIFACTS + 1))
    OK_LIST+="${name} "
    log "file ok: ${src} -> ${out}"
}

# ── Directories (tar.gz, guarded) ────────────────────────────────────
backup_dir() {
    local src="$1"
    # The MEMBER tar archives is always the real directory name; the
    # optional second argument only renames the OUTPUT file, for cases
    # where basename alone is ambiguous on restore (data/playerctx/history
    # would otherwise land as "history.tar.gz").
    #
    # These were conflated when the label was added, and the first real
    # backup-proof run caught it: tar was asked for a member called
    # "playerctx_history" inside data/playerctx/, which does not exist, so
    # the archive failed and — because the run counts that as an error —
    # the WHOLE nightly generation was discarded.
    local member
    member="$(basename "${src}")"
    local name="${2:-${member}}"
    # Arguments 3.. are tar --exclude patterns, matched against archive
    # member names (which start with "${member}/").  Used to keep a LIVE
    # SQLite database out of a directory tarball when backup_sqlite already
    # takes a consistent online copy of it — a tar of a WAL database is a
    # torn copy (see the "file changed as we read it" note below), and
    # archiving it twice doubles the generation for nothing.
    local excludes=()
    local pattern
    for pattern in "${@:3}"; do
        excludes+=("--exclude=${pattern}")
    done
    if [[ ! -d "${src}" ]]; then
        # "(absent)" must mean PROVEN absent. `-f`/`-d` are false for
        # ENOENT *and* EACCES/ENOTDIR anywhere on the path, so a store
        # behind a 0700 ancestor or on a volume that failed to mount was
        # silently omitted from every generation under a reassuring line.
        # WARN rather than ERROR: the header's posture is that unreadable
        # OPTIONAL inputs are skipped, and failing here would discard
        # user_kv and session_store too. The prover is the fail-closed
        # authority; this is the visibility half.
        if backup_source_absent "${src}"; then
            log "skip dir (absent): ${src}"
        else
            warn "dir source NOT backed up and NOT provably absent: ${src} — it may exist and be unreadable by $(id -un); this generation omits it"
        fi
        return 0
    fi
    optional_gate "${name}" "${src}" || return 0
    local out="${DEST}/dirs/${name}.tar.gz"

    # GNU tar exits 1 for "file changed as we read it" and 2 for a fatal
    # error.  They are not the same event and must not be treated alike:
    # exit 1 means the archive was WRITTEN and one member may be torn,
    # which for a live directory (data/intel holds a SQLite WAL that the
    # app writes continuously) is expected and routine.  Failing the run
    # on it discards every OTHER artifact in the generation — including
    # the retention stores this backup exists to protect — because one
    # unrelated directory was busy.  That is a durability defect wearing
    # the costume of strictness.
    #
    # Live SQLite still belongs in backup_sqlite(), which uses the online
    # backup API and is consistent under WAL; that is exactly why the
    # retention stores go through it and not through here.
    local rc=0
    tar -czf "${out}" ${excludes[@]+"${excludes[@]}"} -C "$(dirname "${src}")" "${member}" || rc=$?
    if (( rc >= 2 )); then
        warn "tar FAILED (rc=${rc}): ${src}"
        rm -f "${out}"
        store_failed "${name}" "tar failed (rc=${rc})"
        return 0
    fi
    if ! tar -tzf "${out}" >/dev/null; then
        warn "integrity check FAILED: ${out}"
        rm -f "${out}"
        store_failed "${name}" "tar -tzf failed"
        return 0
    fi
    if (( rc == 1 )); then
        warn "tar reported changed file(s) while reading ${src} — archive is intact but a member may be torn"
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
        rm -f "${out}" 2>/dev/null || true
        store_failed "${label}" "session copy failed"
    fi
}

# ════════════════════════════════════════════════════════════════════
# CORE stores — everything that predates AL-P2.  A failure on any of these
# fails the run and discards the generation (store_failed counts an ERROR).
# They run FIRST so that a large OPTIONAL store can never consume the disk
# they need.
# ════════════════════════════════════════════════════════════════════
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
backup_sqlite "${DATA_DIR}/retention/acquisition.sqlite"
backup_sqlite "${DATA_DIR}/board_history.sqlite"
# Rookie auction room (src/auction/store.py): rooms, accepted-command log,
# awards, private proxy state, accounts. Online backup — never a raw file
# copy, which would ignore the WAL.
backup_sqlite "${DATA_DIR}/auction/auction.sqlite"
# Adaptive Learning AL-0 receipts (src/model_registry/receipt_store.py):
# append-only MODEL / FEATURES / CHALLENGER / EVALUATION / DRIFT receipts that
# point into native stores. PRIVATE decision intelligence (never under data/ros/,
# never committed). Online backup — the store runs in WAL mode.
backup_sqlite "${DATA_DIR}/learning/receipts.sqlite"
backup_file   "${DATA_DIR}/rank_history.jsonl"

backup_dir "${DATA_DIR}/public_league"
backup_dir "${DATA_DIR}/faab"
backup_dir "${DATA_DIR}/identity"
backup_dir "${DATA_DIR}/game_day"
backup_dir "${DATA_DIR}/playerctx/history" "playerctx_history"

# Repo-root session files (gitignored via "*_session.json").
backup_session_file "${APP_DIR}/dlf_session.json"         "repo.dlf_session.json"
backup_session_file "${APP_DIR}/draftsharks_session.json" "repo.draftsharks_session.json"
backup_session_file "${APP_DIR}/idpshow_session.json"     "repo.idpshow_session.json"
# Fetcher work-dir copies (see deploy/dlf_fetch_and_push.sh /
# deploy/idpshow_fetch_and_push.sh).
backup_session_file "/var/lib/dlf-fetch/dlf_session.json"         "workdir.dlf_session.json"
backup_session_file "/var/lib/idpshow-fetch/idpshow_session.json" "workdir.idpshow_session.json"

# ════════════════════════════════════════════════════════════════════
# The intel ledger: an OPTIONAL online copy, with the CORE intel tar as its
# fallback.
#
# Sharp transactions, rosters, records AND the Sharp league-format captures.
# AL-P2 made the ledger an ONLINE copy; before that it rode only inside
# intel.tar.gz as a tar of a live WAL database, which is a torn copy whenever
# the crawler writes mid-read.  The online copy is OPTIONAL because this
# ledger has a corruption history on the box (ledger.sqlite3.corrupt, a
# 2026-08-01 recovery directory): latent corruption fails PRAGMA
# integrity_check, and that must not stop the core backup.
#
# When the online copy is NOT in this generation — it failed, was shed for
# disk space, was skipped on request (the post-deploy proof), or the source
# is absent — the raw ledger files go back into intel.tar.gz exactly as
# before AL-P2.  That tar is the corruption-tolerant path: tar copies bytes
# and never runs integrity_check, so the generation still holds something a
# recovery can work from.  Only when the online copy succeeded does the tar
# exclude the live database files.
# ════════════════════════════════════════════════════════════════════
optional backup_sqlite "${DATA_DIR}/intel/ledger.sqlite3" "intel_ledger.sqlite3"
if [[ "${OK_LIST}" == *" intel_ledger.sqlite3 "* ]]; then
    backup_dir "${DATA_DIR}/intel" "intel" \
        "intel/ledger.sqlite3" "intel/ledger.sqlite3-wal" "intel/ledger.sqlite3-shm"
else
    if [[ -f "${DATA_DIR}/intel/ledger.sqlite3" ]]; then
        log "intel ledger online copy not in this generation — its raw files ride in intel.tar.gz (pre-AL-P2 behaviour)"
    fi
    backup_dir "${DATA_DIR}/intel" "intel"
fi

# ════════════════════════════════════════════════════════════════════
# OPTIONAL stores — the AL-P2 additions (2026-10-01; docs/BRISKET_IDEAS.md
# §13.4, docs/retention/RETENTION_REGISTER.md "AL-P2" addendum).  Every one
# records something nothing else can re-create, but a failure on one is a
# WARNING (exit 3, optional_stores.tsv), never a discarded generation.
# Guarded (absent => "skip (absent)"), never in BACKUP_REQUIRED, and every
# live SQLite file through backup_sqlite — never a raw copy that ignores the
# WAL.  Labels keep basenames unique inside one generation.  Smallest first,
# the 1.5 GB temporal ledger last, so a disk that runs short sheds the
# biggest store rather than the small ones.
# ════════════════════════════════════════════════════════════════════
#   * KTC Trade Database raw archive (#1586).  KTC serves a ~200-row
#     rolling window, so a row that scrolls out before it is archived is
#     gone.  PRIVATE (vendor feed + league ids).  The DERIVED
#     data/market_trades/underlying_trades.sqlite is deliberately NOT here:
#     market_trade_report.build_ledger (scripts/market_trade_ledger.py, the
#     dynasty-market-trade-ledger timer) rebuilds it wholesale from this
#     archive + the intel ledger + the own-league stores on every run.
optional backup_sqlite "${DATA_DIR}/market_trades/archive.sqlite" "market_trades_archive.sqlite"
optional backup_dir    "${DATA_DIR}/market_trades/reports" "market_trades_reports"
#   * Own-league season format captures (#1607) — dated captures plus the
#     re-observations that prove "unchanged since"; a later fetch cannot
#     say what a season's settings were on an earlier date.
optional backup_sqlite "${DATA_DIR}/leagues/own_league_format_captures.sqlite"
#   * KTC same-day format-variant boards (#1603) — KTC publishes current
#     values only.
optional backup_sqlite "${DATA_DIR}/source_archive/boards.sqlite" "source_archive_boards.sqlite"
#   * AL-P2 directories: dated, write-once or append-only files.
#     BDVM projection editions (Mike Clay, IDP Show, proxy) + events —
#     vendors publish the current edition only.
optional backup_dir "${DATA_DIR}/bdvm"
#     Point-in-time playoff/title forecast archive (#1602, AL-P6).
optional backup_dir "${DATA_DIR}/forecast_archive"
#     Pick-forecast + team-strength snapshots (#1604, AL-P4).
optional backup_dir "${DATA_DIR}/pick_forecast_snapshots"
#     Shadow-evaluation ledgers (monthly JSONL) — what each shadow run saw.
optional backup_dir "${DATA_DIR}/sparse_evidence_shadow"
optional backup_dir "${DATA_DIR}/robust_filter_shadow"
#   * Signals Fantasy private store (docs/sources/SIGNALS_FANTASY_INTEGRATION.md):
#     validated value releases, board CSVs, fetch/collector state and raw
#     gzip payloads.  Box-local by design (never committed, never in CI) and
#     the vendor serves CURRENT values only, so a lost release is lost.  The
#     owner session (/var/lib/signals-auth) is NOT here and never will be —
#     credentials stay with their dedicated owner.  The data/scrape_state
#     Signals stamps are not copied: the next healthy collection re-stamps
#     them from the vendor's own as-of clock.
optional backup_dir "${DATA_DIR}/sources/signals" "signals_sources"
#   * Consensus Edge daily label history — a label is what the model said
#     on that day; it cannot be recomputed later from later boards.
optional backup_sqlite "${DATA_DIR}/consensus_edge.sqlite"
#   * DFS workspace — immutable slate snapshots + point-in-time captures.
#     data/dfs/raw/ is the overwritten latest provider pull, re-fetchable,
#     and its content is already snapshotted inside the workspace.
optional backup_sqlite "${DATA_DIR}/dfs/workspace.sqlite" "dfs_workspace.sqlite"
#   * Temporal ledger (C1-U4).  NOT rebuildable in full: the rebuild path
#     (scripts/build_temporal_ledger.py) restores the daily exports/archive
#     backfill and the two migrated recorders, but every 2-hourly
#     live:server row (canonical board incl. slot picks + the value-direct
#     source anchors) exists only here.  Measured 2026-10-02: ~2.0 M of
#     ~3.3 M rows.  Large (1.5 GB raw); see the register for the disk math.
optional backup_sqlite "${DATA_DIR}/temporal_ledger.sqlite"

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
# Promoted: the EXIT trap must no longer treat it as this run's garbage.
STAGING_DIR=""
log "snapshot promoted: ${FINAL_DEST}"

# Record what this run actually did, machine-readably.  A reader that
# re-derives the location can be wrong about it (that is the defect this
# replaces); a reader that parses the log line above would be depending on
# human prose, which is not an API.  Written only now, after promotion, so
# the pointer never names a generation that does not exist.
if ! backup_root_write_pointer "${BACKUP_ROOT}" "${FINAL_DEST}" "${DATE_STAMP}" "${ARTIFACTS}"; then
    warn "could not record the generation pointer under ${BACKUP_ROOT} (the snapshot itself is intact)"
fi
# A caller that asked for the result by path gets it or gets a failed run.
# Silently not writing it would send the caller looking somewhere else,
# which is precisely the failure mode being closed.
if [[ -n "${BACKUP_RESULT_FILE:-}" ]]; then
    backup_root_write_result "${BACKUP_RESULT_FILE}" "${BACKUP_ROOT}" \
        "${FINAL_DEST}" "${DATE_STAMP}" "${ARTIFACTS}" \
        || fail "could not write the requested BACKUP_RESULT_FILE=${BACKUP_RESULT_FILE}"
    log "result recorded: ${BACKUP_RESULT_FILE}"
fi

# ── Optional off-box mirror (operator opt-in) ────────────────────────
# Reached only with every artifact written and integrity-checked, so a
# partial/corrupt snapshot can never replace the off-box copy (rsync
# --delete makes a bad publish doubly destructive remotely).
MIRROR_FAILED=0
if [[ -n "${OFFBOX_RSYNC_DEST}" ]]; then
    if command -v rsync >/dev/null 2>&1; then
        # `--delete` makes the remote an exact replica of this root's daily/
        # namespace, so it may run ONLY with positive proof that this root
        # still holds the history the mirror was built from.
        #
        # "Same root as requested" is NOT that proof — it answers which root we
        # wrote to, not whether its history is continuous. Measured: a writable
        # primary whose local generations had vanished (disk replaced, /var
        # wiped, restored image) took `--delete` and cut a remote of 5
        # generations to 1, destroying four that were the only surviving
        # copies. That is precisely the state in which the off-box copy is the
        # last one standing.
        #
        # Four conditions, all required. Any unproven ⇒ publish additively.
        MIRROR_MARKER="${BACKUP_ROOT%/}/last_mirror"
        MIRROR_COUNT="$(plausible_generations | wc -l | tr -d ' ')"
        MIRROR_PRIOR_DEST="$(backup_root_pointer_field "${MIRROR_MARKER}" dest || true)"
        MIRROR_PRIOR_COUNT="$(backup_root_pointer_field "${MIRROR_MARKER}" generations || true)"

        RSYNC_ARGS=(-a)
        MIRROR_DELETE_REFUSED=""
        if [[ "${BACKUP_ROOT}" != "${REQUESTED_ROOT}" ]]; then
            MIRROR_DELETE_REFUSED="this run wrote to the fallback root '${BACKUP_ROOT}', so the generations mirrored from '${REQUESTED_ROOT}' are not represented here"
        elif [[ ! -f "${MIRROR_MARKER}" ]]; then
            MIRROR_DELETE_REFUSED="no record of a previous mirror from this root, so local-history continuity cannot be established"
        elif [[ "${MIRROR_PRIOR_DEST}" != "${OFFBOX_RSYNC_DEST}" ]]; then
            MIRROR_DELETE_REFUSED="the destination changed (previously '${MIRROR_PRIOR_DEST}'), so this remote's history was not built from this root"
        elif [[ ! "${MIRROR_PRIOR_COUNT}" =~ ^[0-9]+$ ]]; then
            MIRROR_DELETE_REFUSED="the previous mirror record carries no usable generation count"
        elif (( MIRROR_COUNT < MIRROR_PRIOR_COUNT )); then
            MIRROR_DELETE_REFUSED="local history SHRANK since the last mirror (${MIRROR_PRIOR_COUNT} -> ${MIRROR_COUNT} generations), so the remote may hold the only surviving copies"
        else
            RSYNC_ARGS+=(--delete)
        fi
        if [[ -n "${MIRROR_DELETE_REFUSED}" ]]; then
            warn "off-box mirror publishing WITHOUT --delete: ${MIRROR_DELETE_REFUSED}"
        fi
        if rsync "${RSYNC_ARGS[@]}" "${BACKUP_ROOT}/daily/" "${OFFBOX_RSYNC_DEST}"; then
            log "off-box mirror ok: ${OFFBOX_RSYNC_DEST}"
            # Re-baseline. A deliberate KEEP_DAILY reduction therefore
            # publishes additively once and reconciles normally afterwards —
            # fail-closed must not become fail-never, or remote retention grows
            # without bound.
            {
                printf 'schema=%s\n' "${BACKUP_ROOT_POINTER_SCHEMA}"
                printf 'dest=%s\n' "${OFFBOX_RSYNC_DEST}"
                printf 'generations=%s\n' "${MIRROR_COUNT}"
                printf 'mirrored_at=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
            } > "${MIRROR_MARKER}" 2>/dev/null \
                || warn "could not record the mirror continuity marker at ${MIRROR_MARKER}; the next run will publish additively"
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
# Generations dated beyond the clock-skew bound are EXCLUDED from the keep
# window rather than counted in it. `sort` puts a 2099 directory at the end of
# an ascending list, so `head -n -N` keeps it forever AND spends one of the N
# slots on it — real retention silently drops to N-1, and to N-2 after the next
# skewed run. It is deliberately not deleted here: an implausible generation is
# an anomaly for an operator to look at, and this script's destructive steps
# only ever remove things it can account for.
prune_candidates() {
    local plausible=()
    while IFS= read -r dir; do
        [[ -n "${dir}" ]] || continue
        plausible+=("${dir}")
    done < <(plausible_generations)
    (( ${#plausible[@]} > KEEP_DAILY )) || return 0
    printf '%s\n' "${plausible[@]}" | head -n -"${KEEP_DAILY}"
}

prune() {
    local dir
    # Dated names sort lexicographically == chronologically.
    while IFS= read -r dir; do
        [[ -n "${dir}" ]] || continue
        log "prune: ${BACKUP_ROOT}/daily/${dir}"
        rm -rf "${BACKUP_ROOT:?}/daily/${dir}"
    done < <(prune_candidates)
}
prune

if (( MIRROR_FAILED )); then
    warn "completed locally (${ARTIFACTS} artifact(s) in ${DEST}) but off-box mirror failed"
    exit 1
fi
if (( OPTIONAL_ISSUES > 0 )); then
    # Exit 3, not 0 and not 1: the generation and all of its CORE state are
    # promoted, but it is missing optional evidence it should have held.  See
    # the exit-code table in the header and SuccessExitStatus=3 on the unit.
    warn "state backup complete WITH WARNINGS: ${ARTIFACTS} artifact(s) in ${DEST}; ${OPTIONAL_ISSUES} OPTIONAL store(s) NOT backed up: ${OPTIONAL_NOT_BACKED_UP}(see ${DEST}/${OPTIONAL_MANIFEST_NAME}) ($(date -u +%FT%TZ))"
    exit 3
fi
log "state backup complete: ${ARTIFACTS} artifact(s) in ${DEST} ($(date -u +%FT%TZ))"
