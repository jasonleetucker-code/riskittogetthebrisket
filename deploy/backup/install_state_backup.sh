#!/usr/bin/env bash
#
# THE canonical installer for the C1A state-backup line.
#
# Installs exactly four things and nothing else:
#
#   /usr/local/lib/riskit/backup_root_lib.sh        root:root 0644  (sourced)
#   /usr/local/lib/riskit/riskit-state-backup.sh    root:root 0755  (executed)
#   /etc/systemd/system/riskit-state-backup.service
#   /etc/systemd/system/riskit-state-backup.timer
#
# WHY THIS FILE EXISTS.  The same four steps used to live inside
# `apply_hardening.sh`, which also rewrites the nginx site config, re-renders
# the backend and frontend units, and reloads nginx — and which requires a full
# root shell to run.  Measured on production 2026-08-15, the deploy account's
# NOPASSWD sudo covers `systemctl`, `journalctl`, `install` and `chown` and NOT
# `bash`, so that installer cannot run at all from the deployment privilege
# model.  Installing a backup timer therefore demanded a human root session and
# an nginx rewrite it had no business performing — and nginx is exactly the step
# that can silently revert certbot's TLS edits.
#
# So the four steps moved HERE, and `apply_hardening.sh` now calls this file
# rather than carrying its own copy.  ONE implementation, two entry points:
#
#   * full hardening      — apply_hardening.sh sources this and calls the same
#                           functions, in the same order, at the same point;
#   * bounded install     — `bash install_state_backup.sh`, runnable by the
#                           deploy account using only install/chown/systemctl.
#
# The point is not that duplication is untidy.  It is that two copies of
# "which files, in which order, with which modes" WILL drift, and the failure
# mode of drift here is a nightly that runs the wrong writer, or a writer
# installed without its library — a silently lost generation.
#
# PRIVILEGE.  Every privileged operation goes through `priv`, which runs the
# command directly when already root and via `sudo -n` otherwise.  That is what
# lets one implementation serve both entry points: as root inside
# apply_hardening.sh, and as the deploy user through the existing allowlist.
#
# WHAT IT DELIBERATELY DOES NOT DO: nginx, backend/frontend units, healthcheck,
# uptime, certificates, or anything else in the hardening script.  Those remain
# apply_hardening.sh's business.

set -Eeuo pipefail

STATE_BACKUP_SERVICE="riskit-state-backup.service"
STATE_BACKUP_TIMER="riskit-state-backup.timer"
STATE_BACKUP_UNIT_DIR="${STATE_BACKUP_UNIT_DIR:-/etc/systemd/system}"

# Set to 1 by any step that actually (re)wrote a file.  A caller that runs
# this on EVERY deploy (deploy/install-systemd-service.sh) reads it to decide
# whether daemon-reload + enable is needed, so an up-to-date box stays a true
# no-op instead of reloading systemd on every deploy.
STATE_BACKUP_CHANGED="${STATE_BACKUP_CHANGED:-0}"

_sb_log() { printf '[state-backup-install] %s\n' "$*"; }
_sb_err() { printf '[state-backup-install][ERR] %s\n' "$*" >&2; }

# Run a command as root. Direct when already root, `sudo -n` otherwise.
# Never `sudo bash` — the whole point is to stay inside an allowlist that
# grants specific binaries rather than a shell.
priv() {
    if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
        "$@"
    else
        sudo -n "$@"
    fi
}

# Install one root-owned file. Idempotent: an identical destination is left
# alone so a re-run is not a rewrite.
_sb_install_file() {
    local src="$1" dest="$2" mode="$3"
    if [[ ! -r "${src}" ]]; then
        _sb_err "source missing or unreadable: ${src}"
        return 1
    fi
    if [[ -f "${dest}" ]] && cmp -s "${src}" "${dest}"; then
        _sb_log "up-to-date: ${dest}"
        return 0
    fi
    _sb_log "installing ${dest} (root:root ${mode})"
    priv install -o root -g root -m "${mode}" -D "${src}" "${dest}" || return 1
    STATE_BACKUP_CHANGED=1
}

# ── the four steps ────────────────────────────────────────────────────────

# LIBRARY FIRST, and the order is load-bearing rather than stylistic.
# riskit-state-backup.sh SOURCES backup_root_lib.sh from its own directory and
# treats it as fatal when absent, so the root-owned copy needs the library
# beside it or the nightly cannot resolve a backup root at all. Installing the
# writer first leaves a window — the timer fires at 02:30 UTC — in which the
# new writer exists without its library and that night's backup is simply not
# taken. A library without the new writer is harmless; the reverse loses a
# generation.
#
# Sourced, never executed: 0644, not 0755.
state_backup_install_scripts() {
    local app_dir="$1" lib_dir="$2"
    # `|| return 1`: a failed library install must stop the writer install
    # even when the caller has errexit suspended (it is, inside an `if`).
    _sb_install_file "${app_dir}/deploy/backup/backup_root_lib.sh" \
                     "${lib_dir}/backup_root_lib.sh" 0644 || return 1
    _sb_install_file "${app_dir}/deploy/backup/riskit-state-backup.sh" \
                     "${lib_dir}/riskit-state-backup.sh" 0755
}

# The service is RENDERED (checkout path and lib dir rewritten for non-default
# installs); the timer is copied verbatim because it names neither. Rendering
# happens unprivileged into a temp file, so only the final copy needs root.
#
# Every step checks its own status explicitly.  The per-deploy caller runs
# this inside `if !`, which SUSPENDS errexit for the whole function body, so a
# missing template or a failed sed would otherwise flow straight on and
# install an EMPTY or truncated service file — a nightly with no ExecStart.
state_backup_install_units() {
    local app_dir="$1" lib_dir="$2"
    local template="${app_dir}/deploy/backup/${STATE_BACKUP_SERVICE}"
    local timer_src="${app_dir}/deploy/backup/${STATE_BACKUP_TIMER}"
    local staged
    if [[ ! -r "${template}" ]]; then
        _sb_err "service template missing or unreadable: ${template}"
        return 1
    fi
    if [[ ! -r "${timer_src}" ]]; then
        _sb_err "timer unit missing or unreadable: ${timer_src}"
        return 1
    fi
    staged="$(mktemp)" || { _sb_err "mktemp failed"; return 1; }
    if ! sed -e "s|/home/dynasty/trade-calculator|${app_dir}|g" \
        -e "s|/usr/local/lib/riskit|${lib_dir}|g" \
        "${template}" > "${staged}"; then
        _sb_err "rendering ${template} failed"
        rm -f "${staged}"
        return 1
    fi
    # A render that produced no ExecStart is not a unit worth installing.
    if ! grep -q '^ExecStart=' "${staged}"; then
        _sb_err "rendered ${STATE_BACKUP_SERVICE} has no ExecStart= line; refusing to install it"
        rm -f "${staged}"
        return 1
    fi
    if [[ -f "${STATE_BACKUP_UNIT_DIR}/${STATE_BACKUP_SERVICE}" ]] \
        && cmp -s "${staged}" "${STATE_BACKUP_UNIT_DIR}/${STATE_BACKUP_SERVICE}"; then
        _sb_log "up-to-date: ${STATE_BACKUP_UNIT_DIR}/${STATE_BACKUP_SERVICE}"
    else
        _sb_log "installing ${STATE_BACKUP_UNIT_DIR}/${STATE_BACKUP_SERVICE}"
        if ! priv install -m 0644 -D "${staged}" "${STATE_BACKUP_UNIT_DIR}/${STATE_BACKUP_SERVICE}"; then
            rm -f "${staged}"
            return 1
        fi
        STATE_BACKUP_CHANGED=1
    fi
    rm -f "${staged}"

    _sb_install_file "${timer_src}" \
                     "${STATE_BACKUP_UNIT_DIR}/${STATE_BACKUP_TIMER}" 0644
}

# Re-read the unit files, then arm the timer. `daemon-reload` before `enable`
# is not optional: systemd serves a cached copy otherwise, so a freshly written
# unit can be enabled while the running manager still holds the old one.
#
# `enable` + `start` of the TIMER only — never a start of the SERVICE.  The
# timer used to declare `Requires=riskit-state-backup.service`, and starting a
# unit starts what it requires, so the old `enable --now` ran a full root
# backup on the spot every time a deploy refreshed a backup file (the
# 2026-08-15 install shows the off-schedule run).  The Requires= is gone from
# the timer and enable/start are split, so this only arms the 02:30 schedule;
# `start` on an already-active timer is a no-op.
state_backup_enable() {
    _sb_log "systemctl daemon-reload"
    priv systemctl daemon-reload || return 1
    _sb_log "systemctl enable ${STATE_BACKUP_TIMER}"
    priv systemctl enable "${STATE_BACKUP_TIMER}" || return 1
    _sb_log "systemctl start ${STATE_BACKUP_TIMER} (arms the schedule; runs no backup)"
    priv systemctl start "${STATE_BACKUP_TIMER}" || return 1
}

# ── standalone entry point ────────────────────────────────────────────────
# Sourced by apply_hardening.sh (which calls the functions itself, in its own
# sequence); executed directly for the bounded install.
#
# `${BASH_SOURCE[0]:-$0}`, not `${BASH_SOURCE[0]}`. When bash reads a script
# from STDIN — `ssh host bash -s < script`, which is how every workflow in this
# repo delivers one to production — BASH_SOURCE is EMPTY, and `set -u` makes
# referencing element 0 fatal. The first production run died here, before any
# privileged call, having installed nothing.
#
# Defaulting to $0 gives the right answer in all three modes: piped (unset ->
# $0 -> equal -> run), executed by path (equal -> run), sourced (the file path
# vs the parent's name -> not equal -> define only).
if [[ "${BASH_SOURCE[0]:-$0}" == "${0}" ]]; then
    APP_DIR="${APP_DIR:-/home/dynasty/trade-calculator}"
    RISKIT_LIB_DIR="${RISKIT_LIB_DIR:-/usr/local/lib/riskit}"

    [[ -d "${APP_DIR}" ]] || { _sb_err "APP_DIR missing: ${APP_DIR}"; exit 1; }

    _sb_log "host=$(hostname) user=$(id -un) date=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    _sb_log "APP_DIR=${APP_DIR} RISKIT_LIB_DIR=${RISKIT_LIB_DIR}"
    _sb_log "state-backup line ONLY — no nginx, no app units, no certificates"

    state_backup_install_scripts "${APP_DIR}" "${RISKIT_LIB_DIR}"
    state_backup_install_units "${APP_DIR}" "${RISKIT_LIB_DIR}"
    state_backup_enable

    _sb_log "done"
fi
