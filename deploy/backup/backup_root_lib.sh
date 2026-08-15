# backup_root_lib.sh — THE owner of "where does the state backup live".
#
# Sourced, never executed.  It defines functions only and runs nothing at
# source time, so a caller's `set -Eeuo pipefail` and exit status are
# untouched.
#
# WHY THIS EXISTS
# ───────────────
# `riskit-state-backup.sh` writes a nightly generation, and
# `retention_backup_restore_proof.sh` reads one back.  Each used to
# resolve the destination independently from the same two defaults, which
# is fine right up until they disagree — and they did, on production proof
# run 31872681688: the primary root was not writable, the writer fell back
# to the service user's home and promoted a COMPLETE generation there, and
# the proof reported "no backup generation under /var/backups/riskit-state
# /daily" for a backup that had succeeded.  Two implementations of one
# decision produce exactly one class of bug, and this is it.
#
# So there is one owner of all four questions:
#
#   requested primary root   → backup_root_primary
#   writability determination→ backup_root_writable / backup_root_claim
#   fallback root            → backup_root_fallback
#   effective generation loc → the pointer written by backup_root_write_result
#
# THE INVARIANT
# ─────────────
#   the location that successfully receives the promoted backup
#     ==
#   the location the restore proof subsequently inspects
#
# It is held two ways, deliberately belt-and-braces:
#
#  1. Both scripts resolve candidate roots through the SAME functions
#     here, so neither can invent a path the other does not know about.
#  2. The writer records what it actually did in a MACHINE-READABLE
#     pointer (KEY=VALUE, schema-versioned).  The proof reads that.  It
#     does not re-derive the location and it does not parse log prose —
#     human-readable log lines are for humans and are not an API.
#
# POINTER FORMAT (schema 1)
# ─────────────────────────
#   schema=1
#   effective_root=/home/dynasty/backups/riskit-state
#   generation=/home/dynasty/backups/riskit-state/daily/2026-08-15
#   date_stamp=2026-08-15
#   artifacts=14
#   promoted_at=2026-08-15T09:12:33Z
#
# `promoted_at` is ISO-8601 UTC with a fixed width, so lexicographic
# ordering IS chronological ordering — that is what lets a reader compare
# pointers from two roots without a date parser.
#
# Values are read with a first-`=` split, so a path containing `=`
# round-trips.  Nothing is ever eval'd.

BACKUP_ROOT_LIB_VERSION=1
BACKUP_ROOT_POINTER_SCHEMA=1
BACKUP_ROOT_POINTER_NAME="last_generation"

# The requested primary root.  `BACKUP_ROOT` is the operator/caller
# override; the default is the system location.
backup_root_primary() {
    printf '%s\n' "${BACKUP_ROOT:-/var/backups/riskit-state}"
}

# The fallback, used when the primary cannot be created or written.  It is
# the service user's own home, which is writable without privilege — the
# nightly runs unprivileged on some hosts.
backup_root_fallback() {
    printf '%s\n' "${BACKUP_FALLBACK_ROOT:-/home/dynasty/backups/riskit-state}"
}

# Every location a generation could legitimately be in, in preference
# order.  A reader that scans anything else is looking somewhere the
# writer would never have written.
backup_root_candidates() {
    local primary fallback
    primary="$(backup_root_primary)"
    fallback="$(backup_root_fallback)"
    printf '%s\n' "${primary}"
    [[ "${fallback}" == "${primary}" ]] || printf '%s\n' "${fallback}"
}

# Writability determination — the single definition.  Creating the
# directory is part of the question: a root that cannot be created is not
# writable, and asking `-w` about a path that does not exist answers no
# for the wrong reason.
backup_root_writable() {
    local root="${1:-}"
    [[ -n "${root}" ]] || return 1
    mkdir -p "${root}" 2>/dev/null || return 1
    [[ -w "${root}" ]] || return 1
    return 0
}

# The WRITER's resolution: first candidate that is actually writable.
# Echoes the effective root; returns 1 when none is usable (the caller
# decides whether that is fatal — here it always is).
backup_root_claim() {
    local root
    while IFS= read -r root; do
        [[ -n "${root}" ]] || continue
        if backup_root_writable "${root}"; then
            printf '%s\n' "${root}"
            return 0
        fi
    done < <(backup_root_candidates)
    return 1
}

backup_root_pointer_path() {
    printf '%s\n' "${1%/}/${BACKUP_ROOT_POINTER_NAME}"
}

# Write the machine-readable result.
#   $1 destination file · $2 effective root · $3 generation dir
#   $4 date stamp · $5 artifact count
# Written to a temp file and renamed, so a reader never sees half a
# pointer.
backup_root_write_result() {
    local out="$1" root="$2" gen="$3" stamp="$4" artifacts="$5"
    local tmp="${out}.tmp.$$"
    {
        printf 'schema=%s\n' "${BACKUP_ROOT_POINTER_SCHEMA}"
        printf 'effective_root=%s\n' "${root}"
        printf 'generation=%s\n' "${gen}"
        printf 'date_stamp=%s\n' "${stamp}"
        printf 'artifacts=%s\n' "${artifacts}"
        printf 'promoted_at=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    } > "${tmp}" 2>/dev/null || { rm -f "${tmp}"; return 1; }
    mv -f "${tmp}" "${out}" 2>/dev/null || { rm -f "${tmp}"; return 1; }
    return 0
}

# The in-root pointer: same content, at the well-known name, so a later
# reader can find the generation without having run the backup itself.
backup_root_write_pointer() {
    local root="$1" gen="$2" stamp="$3" artifacts="$4"
    backup_root_write_result "$(backup_root_pointer_path "${root}")" \
        "${root}" "${gen}" "${stamp}" "${artifacts}"
}

# Can a READER see into this root at all?  Distinct from
# `backup_root_writable`, which is the writer's question and CREATES the
# directory — a reader must never do that, because a root it just made is
# indistinguishable from one that legitimately holds nothing.
#
# The distinction is load-bearing: the nightly runs as root and chmods its
# root 0700, so an unprivileged reader gets "not readable" for a root that
# is FULL of generations.  Treating that as "empty" and quietly certifying
# an older generation from the other root is a fail-open, and it is the
# exact defect this library exists to prevent, merely inverted.
backup_root_readable() {
    local root="${1:-}"
    [[ -n "${root}" && -d "${root}" && -r "${root}" && -x "${root}" ]]
}

# The newest dated generation actually ON DISK under a root, with no
# pointer involved.
#
# Needed because the pointer is younger than the backups: the production
# nightly executes a root-owned copy of the writer that only
# apply_hardening.sh refreshes, so real generations keep landing with no
# pointer beside them until an operator re-runs that installer.  A reader
# that could only follow pointers would be blind to every one of them.
backup_root_scan_generation() {
    local root="${1:-}" gen
    [[ -n "${root}" ]] || return 1
    gen="$(ls -1d "${root%/}/daily"/[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] 2>/dev/null | sort | tail -n1 || true)"
    [[ -n "${gen}" && -d "${gen}" ]] || return 1
    printf '%s\n' "${gen}"
}

# When was this generation promoted?  The pointer's `promoted_at` when the
# pointer describes THIS generation, else midnight of the dated directory
# name.  Never empty for a well-formed generation, which matters because a
# comparison against an empty incumbent silently accepts anything.
backup_root_generation_stamp() {
    local root="$1" gen="$2" ptr at="" ptr_gen base
    ptr="$(backup_root_pointer_path "${root}")"
    ptr_gen="$(backup_root_pointer_field "${ptr}" generation || true)"
    if [[ -n "${ptr_gen}" && "${ptr_gen}" == "${gen}" ]]; then
        at="$(backup_root_pointer_field "${ptr}" promoted_at || true)"
    fi
    if [[ -z "${at}" ]]; then
        base="$(basename "${gen}")"
        [[ "${base}" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] && at="${base}T00:00:00Z"
    fi
    printf '%s\n' "${at}"
}

# Read one field.  First-`=` split; no eval, no sourcing of the pointer.
backup_root_pointer_field() {
    local file="$1" key="$2" line
    [[ -f "${file}" ]] || return 1
    while IFS= read -r line; do
        [[ "${line}" == "${key}="* ]] || continue
        printf '%s\n' "${line#*=}"
        return 0
    done < "${file}"
    return 1
}

# The generation recorded under a root, or 1 when there is no USABLE
# pointer.  "Usable" means the schema is one we understand and the
# generation it names still exists — a pointer to a pruned generation is
# not a generation, and must not be presented as one.
backup_root_read_generation() {
    local root="$1" ptr schema gen
    ptr="$(backup_root_pointer_path "${root}")"
    [[ -f "${ptr}" ]] || return 1
    schema="$(backup_root_pointer_field "${ptr}" schema || true)"
    [[ "${schema}" == "${BACKUP_ROOT_POINTER_SCHEMA}" ]] || return 1
    gen="$(backup_root_pointer_field "${ptr}" generation || true)"
    [[ -n "${gen}" && -d "${gen}" ]] || return 1
    printf '%s\n' "${gen}"
    return 0
}
