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

# A root is a LOCATION, and only an absolute path is one.  A relative root
# — or a systemd `~/...` that was never expanded — resolves against each
# PROCESS's own cwd, so the writer promotes under its cwd while the prover
# reports "does not exist" and certifies the other root's older generation.
# That is two answers to one location question, which is the entire class
# this library exists to eliminate.
#
# Refused, never normalised against $PWD: normalising would silently pick
# one process's cwd as the truth and reintroduce the disagreement one layer
# down.
backup_root_require_absolute() {
    local path="${1:-}" name="${2:-root}"
    if [[ "${path}" != /* ]]; then
        printf 'backup root %s must be an absolute path, got: %s\n' "${name}" "${path}" >&2
        return 1
    fi
    printf '%s\n' "${path}"
}

# The requested primary root.  `BACKUP_ROOT` is the operator/caller
# override; the default is the system location.
backup_root_primary() {
    backup_root_require_absolute "${BACKUP_ROOT:-/var/backups/riskit-state}" BACKUP_ROOT
}

# The fallback, used when the primary cannot be created or written.  It is
# the service user's own home, which is writable without privilege — the
# nightly runs unprivileged on some hosts.
backup_root_fallback() {
    backup_root_require_absolute "${BACKUP_FALLBACK_ROOT:-/home/dynasty/backups/riskit-state}" BACKUP_FALLBACK_ROOT
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
    # `mktemp`, not "${out}.tmp.$$": the old name was derivable from the
    # world-readable result path, and `>` follows a symlink planted there.
    local tmp
    tmp="$(mktemp "${out}.tmp.XXXXXX" 2>/dev/null)" || return 1
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
# It covers `daily/` as well as the root, because that is what both finders
# actually open — and the two levels are permissioned independently: the
# writer chmods only the root, while daily/ takes whatever `umask 077` gave
# it at mkdir.  A root readable with an unreadable daily/ would otherwise
# report "holds no generation", which is the same fail-open one level down,
# and it is exactly what an operator produces by chmod'ing the root alone
# after reading the refusal message.
#
# The `! -e` arm is load-bearing: a root that has never been written has no
# daily/ at all, and that must stay an ordinary empty root rather than
# becoming a refusal.  It is paired with `! -L` because `-e` DEREFERENCES:
# a symlinked daily/ pointing somewhere unreachable is `! -e` too, and
# without the pairing it short-circuits the whole check and reports "holds
# no generation" — the same errno confusion this arm was added to close,
# one directory level down.
backup_root_readable() {
    local root="${1:-}"
    [[ -n "${root}" && -d "${root}" && -r "${root}" && -x "${root}" ]] || return 1
    local daily="${root%/}/daily"
    [[ ! -e "${daily}" && ! -L "${daily}" ]] || [[ -d "${daily}" && -r "${daily}" && -x "${daily}" ]]
}

# The newest dated generation actually ON DISK under a root, with no
# pointer involved.
#
# Needed because the pointer is younger than the backups: the production
# nightly executes a root-owned copy of the writer that only
# apply_hardening.sh refreshes, so real generations keep landing with no
# pointer beside them until an operator re-runs that installer.  A reader
# that could only follow pointers would be blind to every one of them.
# Nothing can have been promoted after now, so a dated name AHEAD of today
# is not a newer generation — it is a MISDATED one, and it is the only kind
# of entry that can be positively ruled out rather than merely resolved.
#
# The name is the ONLY evidence of recency this scan has, and it had no
# upper bound.  `riskit-state-backup.timer` is `Persistent=true`, so a
# missed nightly replays at boot — before NTP has stepped the clock — and
# that run promotes a COMPLETE generation under e.g. `daily/2099-03-04`.
# It then outranks every real generation forever (`sort -r` takes it, and
# prune's `sort | head -n -14` can never reach it, so retention silently
# drops 14 -> 13), and every later proof certifies it and exits 0 without
# ever opening the current generation.
#
# SKIPPED, not refused: this library refuses on anything it cannot resolve
# because an unresolvable entry may BE the newer generation, but a
# future-dated one provably is not — refusing would trade a fail-open for
# an outage.  The skip is announced, because an unannounced substitution is
# the bug this whole file is about.
# The accepted clock-skew bound. A writer whose clock runs slightly ahead, or a
# proof crossing midnight UTC, legitimately produces a generation dated
# tomorrow; that is skew and it is normal. A generation dated beyond this bound
# is not skew — it is a WRONG CLOCK, and because this system decides recency by
# directory name, a wrong clock means recency cannot be trusted in that root at
# all.
BACKUP_ROOT_FUTURE_TOLERANCE_DAYS="${BACKUP_ROOT_FUTURE_TOLERANCE_DAYS:-1}"

backup_root_max_plausible_date() {
    date -u -d "+${BACKUP_ROOT_FUTURE_TOLERANCE_DAYS} days" +%Y-%m-%d
}

# Dated within the bound (today, or tomorrow by default)?
backup_root_name_is_plausible() {
    [[ ! "${1:-}" > "$(backup_root_max_plausible_date)" ]]
}

# Retained under its old name for callers; TRUE only beyond the bound.
backup_root_name_is_future() {
    ! backup_root_name_is_plausible "${1:-}"
}

# Is a SOURCE path provably absent, or merely invisible from here?
#
# The same ENOENT/EACCES conflation this library closed for the backup root,
# closed for the artifacts.  `-e`/`-f`/`-d` are false for ENOENT *and* for
# EACCES/ENOTDIR anywhere on the path, and only the first means "this stream
# has not started".  A retention store behind a mode-0700 ancestor, or on a
# volume that failed to mount, is otherwise excused as never-started and
# omitted from every generation — silently, because the retention artifacts
# are deliberately not in BACKUP_REQUIRED.
#
#   0  proven absent      2  indeterminate (may exist and be unreachable)
backup_source_absent() {
    local path="${1:-}" probe
    [[ -n "${path}" ]] || return 2
    [[ ! -e "${path}" && ! -L "${path}" ]] || return 2
    probe="${path}"
    while [[ ! -e "${probe}" && ! -L "${probe}" && "${probe}" != "/" && "${probe}" != "." ]]; do
        probe="$(dirname "${probe}")"
    done
    [[ -r "${probe}" && -x "${probe}" ]] || return 2
    return 0
}

# THREE outcomes, and the third is the point:
#   0 + path  the newest dated entry that really resolves to a directory
#   2         a dated entry is LISTED but cannot be resolved as a directory,
#             so a newer generation cannot be ruled out here — indeterminate
#   1         the root holds no dated entries at all — genuinely empty
#
# A glob match is an lstat-level fact; `-d` is a stat-level fact. Taking only
# `tail -n1` and failing the whole root when that one entry is not a directory
# discarded every older real generation under it and reported the root as
# EMPTY — so the prover certified a stale generation from the other root and
# exited 0. One dangling symlink, one stray file, or one generation on an
# unmounted volume was enough. That is the ENOENT/EACCES corollary re-opened
# one directory below where backup_root_readable closes it.
#
# Newest-first, and an unresolvable NEWEST entry stops the walk rather than
# being skipped: it may itself BE the newer generation, and silently falling
# back to an older sibling is exactly the substitution this library forbids.
backup_root_scan_generation() {
    local root="${1:-}" entry
    [[ -n "${root}" ]] || return 1
    local daily="${root%/}/daily"
    [[ -d "${daily}" ]] || return 1

    local -a entries=()
    while IFS= read -r entry; do
        [[ -n "${entry}" ]] || continue
        entries+=("${entry}")
    done < <(ls -1d "${daily}"/[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] 2>/dev/null | sort -r)
    (( ${#entries[@]} )) || return 1

    for entry in "${entries[@]}"; do
        if [[ -d "${entry}" ]]; then
            # Checked AFTER resolution, never before: an unresolvable entry
            # may still BE a newer generation whatever it is named, so it
            # keeps stopping the walk.  Only an entry that resolves — whose
            # name is therefore the writer's own date stamp — is ruled out.
            if backup_root_name_is_future "$(basename "${entry}")"; then
                # rc 3, not `continue`. A name beyond the skew bound means the
                # clock that wrote it was wrong, and this scan decides recency
                # BY NAME — so no ordering in this root can be trusted. It also
                # sits inside prune's keep window forever, silently costing a
                # retention slot per skewed run. Refusing is what puts it in
                # front of an operator, who is the only one who can clear it.
                printf 'generation dated beyond the clock-skew bound: %s (newest plausible is %s) — the clock that wrote it was wrong, so name-ordered recency cannot be trusted in this root; remove or re-date it\n' \
                    "${entry}" "$(backup_root_max_plausible_date)" >&2
                return 3
            fi
            printf '%s\n' "${entry}"
            return 0
        fi
        return 2
    done
    return 1
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
    local root="$1" ptr schema gen base
    ptr="$(backup_root_pointer_path "${root}")"
    [[ -f "${ptr}" ]] || return 1
    schema="$(backup_root_pointer_field "${ptr}" schema || true)"
    [[ "${schema}" == "${BACKUP_ROOT_POINTER_SCHEMA}" ]] || return 1
    gen="$(backup_root_pointer_field "${ptr}" generation || true)"
    [[ -n "${gen}" ]] || return 1

    # A pointer is a hint about THIS root, never a redirect out of it, and
    # the name it gives must be the dated shape the whole selection
    # algorithm compares on.  Both are load-bearing, and the second is not
    # cosmetic: the reader ranks a pointer against the root's own newest
    # with `basename >`, and EVERY non-dated name sorts ABOVE every date, so
    # an out-of-root pointer named anything else wins unconditionally and
    # silently disarms the on-disk scan that exists to stop a stale pointer
    # masking a newer generation.  Measured: a pointer naming
    # `<root>/../elsewhere/restore-scratch` was certified — and its contents
    # gunzipped — while the real `daily/<today>` in the named root was never
    # opened, under a log line reading "effective backup root: <root>".
    #
    # Exact-path match, not a prefix test, so `daily/../..` cannot satisfy it.
    #
    # REJECTED, not refused: the caller falls through to the on-disk scan of
    # the root it actually asked about, so that root's own newest real
    # generation is certified and the log says `via on-disk scan`. A
    # well-formed pointer is unaffected — the writer only ever emits
    # ${BACKUP_ROOT}/daily/${DATE_STAMP}.
    base="$(basename "${gen}")"
    [[ "${gen}" == "${root%/}/daily/${base}" ]] || return 1
    [[ "${base}" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] || return 1
    [[ -d "${gen}" ]] || return 1
    # The skewed run writes its pointer with the same wrong clock, so the
    # other finder must rule it out too.
    ! backup_root_name_is_future "${base}" || return 1

    printf '%s\n' "${gen}"
    return 0
}
