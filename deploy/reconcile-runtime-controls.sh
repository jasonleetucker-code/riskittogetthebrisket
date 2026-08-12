#!/usr/bin/env bash
# Converge the RUNTIME controls this revision requires. Deploy + rollback
# both source this; there is deliberately one implementation.
#
# THE DEFECT THIS EXISTS FOR (2026-08-12).  A fully green deploy of #812
# left the live backend on soft LimitNOFILE 1024 — the exact limit EMFILE
# was raised against — and left dynasty-healthcheck.timer with
# LoadState=not-found. The unit template and the watchdog were shipped in
# Git and never installed, because deploy.sh only ever checked that the
# unit EXISTED. So the deploy reported success while the controls the
# revision required lived only in the repository.
#
# Invariant: a deploy must never report success when a runtime artifact
# required by that revision is missing, stale, disabled or inactive on
# the host.
#
# PRIVILEGE.  Nothing here needs new sudo. The deploy user already holds
# NOPASSWD for exactly systemctl, journalctl, install and chown, which is
# precisely the set this needs: `install` writes the root-owned files and
# `systemctl` reloads/enables/starts. The security property that matters
# is preserved — the root-EXECUTED watchdog keeps running from a
# root:root 0755 copy under RISKIT_LIB_DIR, outside the deploy-user-
# writable checkout, so a compromised checkout still cannot rewrite what
# root executes.
#
# SCOPE.  Only the controls this incident requires: the backend unit, the
# watchdog executable, and the watchdog service+timer. It does NOT run
# apply_hardening.sh, and does not touch nginx, backups or uptime
# monitoring — those are operator-owned and unrelated to this failure.

# SOURCING MUST NOT CHANGE THE CALLER'S SHELL OPTIONS.
#
# deploy.sh and rollback.sh both run under `set -Eeuo pipefail`.  A
# top-level `set -uo pipefail` here would silently turn errexit OFF for
# the remainder of whichever script sourced us — every unchecked command
# in the rest of a production deploy would stop aborting on failure.
# That is a far worse version of the defect this file exists to fix, and
# it would be invisible.
#
# So there is no global `set` at all.  The two entry points install
# their own options for the duration of their own call and restore the
# caller's exactly (see `_rc_with_local_opts`), and everything in
# between propagates failure explicitly rather than relying on errexit —
# which is disabled inside any function invoked as a condition anyway,
# and both entry points are invoked that way.

RECONCILE_CHANGED_UNITS=false
RECONCILE_ACTIONS=()

# Locations, overridable so the suite can exercise the REAL functions
# against a temporary root instead of reimplementing their logic.
# Production defaults are the production paths; nothing sets these on the
# host.  ``SYSTEMCTL_BIN`` / ``INSTALL_BIN`` below are the same seam.
SYSTEMD_UNIT_DIR="${SYSTEMD_UNIT_DIR:-/etc/systemd/system}"
RC_PROC_DIR="${RC_PROC_DIR:-/proc}"

_rc_log()  { printf '[reconcile] %s\n' "$*"; }
_rc_warn() { printf '[reconcile][WARN] %s\n' "$*" >&2; }
_rc_err()  { printf '[reconcile][ERROR] %s\n' "$*" >&2; }


# EVERY privileged call goes through here.  Two reasons, and the second
# is the one that matters: the allowlist is enforced at RUNTIME (an
# unauthorized binary is refused by this function before sudo is even
# reached, with a clear message instead of a bare "a password is
# required"), and it makes the static audit exact — a reviewer or test
# reads one list rather than resolving shell indirection at every call
# site.  The first version scattered `sudo -n` across the file, one of
# them via a variable, and the audit could not see through it.
#
# The set is the verified NOPASSWD surface on the deploy host.
_RC_SUDO_ALLOWED=(systemctl journalctl install chown)
_rc_sudo() {
  local bin="$1"; shift
  local base; base="$(basename "${bin}")"
  local ok=false a
  for a in "${_RC_SUDO_ALLOWED[@]}"; do [[ "${base}" == "${a}" ]] && ok=true && break; done
  if [[ "${ok}" != "true" ]]; then
    _rc_err "refusing to sudo '${base}' — not in the authorized set (${_RC_SUDO_ALLOWED[*]})"
    return 126
  fi
  sudo -n "${bin}" "$@"
}

# TWO renderers, because there are two placeholder contracts and they
# are not interchangeable.  The first version of this file used the
# hardening substitutions for the backend template, which would have
# installed a unit still containing literal __SERVICE_NAME__ /
# __APP_USER__ / __APP_DIR__ / __VENV_DIR__ — a broken unit, shipped by
# the very mechanism meant to stop broken runtime state.
#
# Backend unit: placeholder tokens, exactly as install-systemd-service.sh
# does it, escaping included (APP_DIR contains slashes).
_rc_escape_sed() { printf '%s' "$1" | sed -e 's/[\\/&]/\\&/g'; }

# A FAILED RENDER MUST NOT BE INSTALLABLE.
#
# This file runs under `set -uo pipefail`, without errexit, and that is
# deliberate: errexit is disabled for the entire body of a function
# invoked as a condition, and every caller here invokes these as
# `if ! _rc_render_… ` or `… || rc=1`.  Turning `set -e` on globally
# would therefore be inert in exactly the frames that need it — the same
# Bash trap that produced the rollback defect this program already
# fixed — while arming it everywhere else in whatever script sources us.
# So each fallible step is checked where it can fail.
#
# The original shape was `sed … > "${out}"` followed by an unresolved-
# placeholder `if`.  A failing `sed` left a truncated or empty file, the
# `if` found no placeholders in it, and the function returned the status
# of a false `if` — which is 0.  A broken render reported success.
_rc_check_render() {
  local src="$1" out="$2" sed_rc="$3"
  if (( sed_rc != 0 )); then
    _rc_err "render of ${src} failed (sed exit ${sed_rc}) — refusing to install a partial unit"
    return 1
  fi
  if [[ ! -s "${out}" ]]; then
    _rc_err "render of ${src} produced an empty unit — refusing to install it"
    return 1
  fi
  # A placeholder that survives rendering is a unit that cannot work.
  if grep -q '__[A-Z_]\+__' "${out}"; then
    _rc_err "unresolved placeholder(s) in rendered ${src}:"
    grep -o '__[A-Z_]\+__' "${out}" | sort -u | sed 's/^/  /' >&2
    return 1
  fi
  return 0
}

_rc_render_backend_unit() {
  local src="$1" out="$2" sed_rc=0
  sed -e "s/__SERVICE_NAME__/$(_rc_escape_sed "${SERVICE_NAME}")/g" \
      -e "s/__APP_USER__/$(_rc_escape_sed "${APP_USER}")/g" \
      -e "s/__APP_DIR__/$(_rc_escape_sed "${APP_DIR}")/g" \
      -e "s/__VENV_DIR__/$(_rc_escape_sed "${VENV_DIR}")/g" \
      "${src}" > "${out}" || sed_rc=$?
  _rc_check_render "${src}" "${out}" "${sed_rc}"
}

# Hardening units (healthcheck service/timer): literal substitutions,
# matching apply_hardening.sh::install_unit.  Each pattern is a no-op in
# units that do not contain it.
_rc_render_hardening_unit() {
  local src="$1" out="$2" sed_rc=0
  sed -e "s|/home/dynasty/trade-calculator|${APP_DIR}|g" \
      -e "s|/usr/local/lib/riskit|${RISKIT_LIB_DIR}|g" \
      -e "s|HEALTH_SERVICE=dynasty|HEALTH_SERVICE=${SERVICE_NAME}|g" \
      -e "s|^User=dynasty$|User=${APP_USER}|" \
      -e "s|^Group=dynasty$|Group=${APP_USER}|" \
      "${src}" > "${out}" || sed_rc=$?
  _rc_check_render "${src}" "${out}" "${sed_rc}"
}

# Install only when the desired content differs from what is installed.
# `cmp` against the RENDERED desired file is the whole point: existence
# is not convergence, and that conflation is what shipped 1024 to
# production under a green deploy.
_rc_install_if_different() {
  local staged="$1" dest="$2" mode="${3:-0644}" owner="${4:-}"
  # Structural backstop to the render checks above: whatever produced
  # this file, an empty or missing source is never installed over a
  # working artifact.  Belt and braces on purpose — the renderer is not
  # the only thing that could ever stage a file here.
  if [[ ! -s "${staged}" ]]; then
    _rc_err "refusing to install ${dest} from empty/missing source ${staged}"
    return 1
  fi
  # UNPRIVILEGED comparison only.  The NOPASSWD surface is exactly
  # systemctl, journalctl, install and chown — `cmp`/`stat`/`grep` are
  # NOT in it, and an earlier version called them under sudo, which
  # would simply have been refused.  Nothing needs privilege here: units
  # are 0644 and the watchdog is root:root 0755, both world-readable by
  # design, so an ordinary read is sufficient AND is a truer check (it
  # verifies what any reader, including systemd, would see).
  if [[ -f "${dest}" ]]; then
    if [[ ! -r "${dest}" ]]; then
      _rc_err "${dest} exists but is not readable as $(id -un) — cannot prove convergence"
      return 1
    fi
    if cmp -s "${staged}" "${dest}"; then
      _rc_log "up-to-date: ${dest}"
      return 0
    fi
  fi
  _rc_log "installing: ${dest} (mode ${mode}${owner:+, ${owner}})"
  local args=(-m "${mode}" -D)
  [[ -n "${owner}" ]] && args=(-o "${owner%%:*}" -g "${owner##*:}" "${args[@]}")
  if ! _rc_sudo "${INSTALL_BIN:-/usr/bin/install}" "${args[@]}" "${staged}" "${dest}"; then
    _rc_err "failed to install ${dest}"
    return 1
  fi
  RECONCILE_CHANGED_UNITS=true
  RECONCILE_ACTIONS+=("installed ${dest}")
  return 0
}

# ── the two entry points ─────────────────────────────────────────────
# Both are thin wrappers that scope this file's shell options to their
# own call and hand the caller back exactly what it had.
#
# The obvious implementation — `saved="$(set +o)"` … `eval "${saved}"` —
# is WRONG here, and wrong in the one direction that matters.  Bash runs
# command substitutions without errexit unless `inherit_errexit` is set,
# so `set +o` inside `$( )` always reports `set +o errexit`, and
# restoring that script turns errexit OFF in a caller that had it on.
# The restore would silently disarm the rest of a production deploy —
# precisely the hazard this wrapper exists to prevent.  `$-` is expanded
# in THIS shell and is authoritative; pipefail has no `$-` letter, so it
# is read with `[[ -o … ]]`, which is also not a subshell.
_rc_with_local_opts() {
  local fn="$1"; shift
  local saved_flags="$-"
  local saved_pipefail=off
  if [[ -o pipefail ]]; then saved_pipefail=on; fi

  set +e            # explicit propagation below; see the header
  set -u
  set -o pipefail

  local rc=0
  "${fn}" "$@" || rc=$?

  case "${saved_flags}" in *e*) set -e ;; *) set +e ;; esac
  case "${saved_flags}" in *u*) set -u ;; *) set +u ;; esac
  if [[ "${saved_pipefail}" == "on" ]]; then set -o pipefail; else set +o pipefail; fi
  return "${rc}"
}

reconcile_runtime_controls() { _rc_with_local_opts _reconcile_runtime_controls "$@"; }
verify_runtime_controls()   { _rc_with_local_opts _verify_runtime_controls "$@"; }

# Returns non-zero on any failure. Callers must treat that as fatal:
# failing closed is the entire contract. Never leaves a partially
# converged host silently.
_reconcile_runtime_controls() {
  local repo_dir="${1:-${APP_DIR}}"
  local sysd="${repo_dir}/deploy/systemd"
  local rc=0 staged
  RECONCILE_CHANGED_UNITS=false
  RECONCILE_ACTIONS=()

  : "${SERVICE_NAME:?SERVICE_NAME required}"
  : "${APP_DIR:?APP_DIR required}"
  : "${APP_USER:=$(id -un)}"
  : "${RISKIT_LIB_DIR:=/usr/local/lib/riskit}"
  : "${VENV_DIR:=${APP_DIR}/.venv}"

  _rc_log "reconciling runtime controls from ${repo_dir}"

  # 1. backend unit — the LimitNOFILE carrier.
  if [[ -f "${sysd}/dynasty.service.template" ]]; then
    staged="$(mktemp)"
    # Render is checked BEFORE install, always. A failed render skips the
    # install entirely rather than handing it a truncated file.
    if _rc_render_backend_unit "${sysd}/dynasty.service.template" "${staged}"; then
      _rc_install_if_different "${staged}" "${SYSTEMD_UNIT_DIR}/${SERVICE_NAME}.service" 0644 || rc=1
    else
      rc=1
    fi
    rm -f "${staged}"
  else
    _rc_err "missing ${sysd}/dynasty.service.template"; rc=1
  fi

  # 2. watchdog executable — root-owned, outside the checkout.
  if [[ -f "${sysd}/dynasty-healthcheck.sh" ]]; then
    # Basename preserved, matching apply_hardening.sh::install_priv_script
    # (`basename "$1"`) and therefore matching the healthcheck unit's
    # ExecStart, which the hardening renderer rewrites only in its
    # DIRECTORY component.  An earlier version installed
    # ${SERVICE_NAME}-healthcheck.sh, which agrees with ExecStart only
    # because production happens to run SERVICE_NAME=dynasty — an
    # accidental coupling that breaks on any other service name.
    _rc_install_if_different "${sysd}/dynasty-healthcheck.sh" \
      "${RISKIT_LIB_DIR}/dynasty-healthcheck.sh" 0755 "root:root" || rc=1
  else
    _rc_err "missing ${sysd}/dynasty-healthcheck.sh"; rc=1
  fi

  # 3. watchdog service + timer.
  local u
  for u in "dynasty-healthcheck.service" "dynasty-healthcheck.timer"; do
    if [[ -f "${sysd}/${u}" ]]; then
      staged="$(mktemp)"
      # Same rule as the backend unit: render, check, only then install.
      if _rc_render_hardening_unit "${sysd}/${u}" "${staged}"; then
        # Unit FILE names are canonical too — apply_hardening.sh installs
        # them under their own basenames and renders only their contents.
        _rc_install_if_different "${staged}" "${SYSTEMD_UNIT_DIR}/${u}" 0644 || rc=1
      else
        rc=1
      fi
      rm -f "${staged}"
    else
      _rc_err "missing ${sysd}/${u}"; rc=1
    fi
  done

  # 4. daemon-reload ONLY when a unit changed, and before anything is
  # started — systemd otherwise starts the old unit and the new limits
  # never reach the process.
  if [[ "${RECONCILE_CHANGED_UNITS}" == "true" ]]; then
    _rc_log "unit files changed — daemon-reload"
    _rc_sudo "${SYSTEMCTL_BIN:-/bin/systemctl}" daemon-reload || { _rc_err "daemon-reload failed"; rc=1; }
  else
    _rc_log "no unit changed — skipping daemon-reload"
  fi

  # 5. the timer must be enabled AND active. Enabled-but-inactive is the
  # state that reads as configured and watches nothing.
  local timer="dynasty-healthcheck.timer"
  if ! _rc_sudo "${SYSTEMCTL_BIN:-/bin/systemctl}" enable --now "${timer}"; then
    _rc_err "could not enable/start ${timer}"; rc=1
  else
    RECONCILE_ACTIONS+=("enabled+started ${timer}")
  fi

  if (( rc != 0 )); then
    _rc_err "runtime reconciliation FAILED — refusing to proceed"
    return 1
  fi
  _rc_log "runtime controls reconciled (${#RECONCILE_ACTIONS[@]} action(s))"
  printf '[reconcile]   %s\n' "${RECONCILE_ACTIONS[@]:-none}"
  return 0
}

# Verify LIVE state, not repository intent. Desired values are read back
# from the rendered unit rather than hard-coded, so this cannot pass by
# agreeing with a constant nobody applied.
_verify_runtime_controls() {
  local repo_dir="${1:-${APP_DIR}}"
  local sysd="${repo_dir}/deploy/systemd" rc=0 staged want_soft want_hard
  local SC="${SYSTEMCTL_BIN:-/bin/systemctl}"

  staged="$(mktemp)"
  _rc_render_backend_unit "${sysd}/dynasty.service.template" "${staged}" || { rm -f "${staged}"; _rc_err "cannot render desired unit"; return 1; }
  local line
  line="$(grep -E '^LimitNOFILE=' "${staged}" | tail -1 | cut -d= -f2)"
  rm -f "${staged}"
  # NOT a warning.  This reconciler exists because a green deploy left
  # production on soft 1024; a run that cannot even derive the expected
  # limit has proved nothing about the control it was written to
  # guarantee, and "nothing to verify" is indistinguishable from
  # "verified" in a log.  Fail closed instead.
  #
  # No version-aware exception: main has carried the #812 declaration
  # since the incident, so every revision this reconciler runs against —
  # forward deploy and rollback target alike — is required to declare it.
  # A rollback to a revision that predates it must be a loud refusal, not
  # a silent downgrade back to the limit that failed.
  if [[ -z "${line}" ]]; then
    _rc_err "desired unit declares no LimitNOFILE — cannot prove the FD limit this revision requires"
    return 1
  fi
  if [[ ! "${line}" =~ ^[0-9]+(:[0-9]+)?$ ]]; then
    _rc_err "desired LimitNOFILE='${line}' is not a systemd soft[:hard] value — cannot derive the expected limit"
    return 1
  fi
  want_soft="${line%%:*}"
  if [[ "${line}" == *:* ]]; then want_hard="${line##*:}"; else want_hard="${want_soft}"; fi

  local got_soft got_hard pid
  got_soft="$(_rc_sudo "$SC" show "${SERVICE_NAME}" -p LimitNOFILESoft --value)"
  got_hard="$(_rc_sudo "$SC" show "${SERVICE_NAME}" -p LimitNOFILE --value)"
  if [[ "${got_soft}" != "${want_soft}" || "${got_hard}" != "${want_hard}" ]]; then
    _rc_err "systemd limits ${got_soft}:${got_hard}, expected ${want_soft}:${want_hard}"
    rc=1
  else
    _rc_log "systemd limits OK: ${got_soft}:${got_hard}"
  fi

  # /proc is the kernel's answer and must agree — a drop-in or a manual
  # ulimit can make systemd's declared value and the process's real one
  # differ, and EMFILE follows the process's.
  pid="$(_rc_sudo "$SC" show "${SERVICE_NAME}" -p MainPID --value)"
  if [[ -n "${pid}" && "${pid}" != "0" && -r "${RC_PROC_DIR}/${pid}/limits" ]]; then
    local psoft phard
    read -r psoft phard < <(awk '/^Max open files/{print $4, $5}' "${RC_PROC_DIR}/${pid}/limits")
    if [[ "${psoft}" != "${want_soft}" || "${phard}" != "${want_hard}" ]]; then
      _rc_err "${RC_PROC_DIR}/${pid}/limits ${psoft}:${phard}, expected ${want_soft}:${want_hard}"
      rc=1
    else
      _rc_log "${RC_PROC_DIR}/${pid}/limits OK: ${psoft}:${phard}"
    fi
  else
    _rc_err "cannot read ${RC_PROC_DIR}/<MainPID>/limits — cannot prove the running process got the limit"
    rc=1
  fi

  # watchdog units must be loaded, enabled and ACTIVE.
  local timer="dynasty-healthcheck.timer" svc="dynasty-healthcheck.service"
  local ls_t as_t ufs_t next ls_s
  ls_t="$(_rc_sudo "$SC" show "${timer}" -p LoadState --value)"
  as_t="$(_rc_sudo "$SC" show "${timer}" -p ActiveState --value)"
  ufs_t="$(_rc_sudo "$SC" show "${timer}" -p UnitFileState --value)"
  next="$(_rc_sudo "$SC" show "${timer}" -p NextElapseUSecRealtime --value)"
  ls_s="$(_rc_sudo "$SC" show "${svc}" -p LoadState --value)"
  _rc_log "watchdog: timer load=${ls_t} active=${as_t} file=${ufs_t} next=${next:-none}; service load=${ls_s}"
  [[ "${ls_t}"  == "loaded"  ]] || { _rc_err "${timer} LoadState=${ls_t}";      rc=1; }
  [[ "${ls_s}"  == "loaded"  ]] || { _rc_err "${svc} LoadState=${ls_s}";        rc=1; }
  [[ "${ufs_t}" == "enabled" ]] || { _rc_err "${timer} UnitFileState=${ufs_t}"; rc=1; }
  [[ "${as_t}"  == "active"  ]] || { _rc_err "${timer} ActiveState=${as_t}";    rc=1; }
  [[ -n "${next}" && "${next}" != "0" ]] || { _rc_err "${timer} has no next activation"; rc=1; }

  # the INSTALLED executable, not the checkout copy.
  local installed="${RISKIT_LIB_DIR:-/usr/local/lib/riskit}/dynasty-healthcheck.sh"
  local owner mode
  if [[ ! -r "${installed}" ]]; then
    _rc_err "${installed} is missing or unreadable — cannot verify the watchdog that actually runs"
    return 1
  fi
  owner="$(stat -c '%U:%G' "${installed}")"
  mode="$(stat -c '%a' "${installed}")"
  if [[ "${owner}" != "root:root" ]]; then
    _rc_err "${installed} owner=${owner}, expected root:root"; rc=1
  fi
  if [[ "${mode}" != "755" ]]; then
    _rc_err "${installed} mode=${mode}, expected 755"; rc=1
  fi
  # The FD thresholds must be in the thing that RUNS, not the template.
  local t
  for t in 'FD_WARN:-256' 'FD_CRIT:-512' 'FD_EMERG:-768'; do
    if ! grep -q "${t}" "${installed}"; then
      _rc_err "installed watchdog missing threshold ${t}"; rc=1
    fi
  done

  if (( rc != 0 )); then
    _rc_err "LIVE runtime verification FAILED — repository intent is not deployment success"
    return 1
  fi
  _rc_log "live runtime controls verified"
  return 0
}
