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
# `systemctl` reloads/enables/starts.
#
# What that does and does not buy, stated precisely: keeping the
# root-EXECUTED watchdog as a root:root 0755 copy under RISKIT_LIB_DIR,
# outside the deploy-user-writable checkout, means an ordinary edit to
# the checkout does not become the script root runs, and it preserves
# the intended ownership/execution layout. It is NOT an OS security
# boundary around the deploy identity: that identity holds NOPASSWD root
# `install` and `systemctl` on this host, so code already running as it
# is not contained by this arrangement. `_rc_sudo` constrains what THIS
# reconciler will do, not what that identity can do. Tightening the
# production deploy sudo scope is separate, backlogged work.
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

# TEST SEAMS, AND WHY PRODUCTION IGNORES THEM.
#
# The suite needs to drive the real functions against a temporary root
# rather than reimplement them, which means the unit directory, /proc
# and the required watchdog owner have to be redirectable.  Reading them
# straight from the environment (`${VAR:-default}`) made the production
# contract configurable by anything that happened to be exported into a
# deploy — and for the owner that is worse than cosmetic, because
# install and verification both read the same variable and would agree
# with each other while requiring something other than root:root.
#
# So production is NOT parameterised: the values below are constants
# unless the harness explicitly opts in with RC_ALLOW_TEST_OVERRIDES=1.
# A stray RC_WATCHDOG_OWNER on its own therefore does nothing at all.
#
# BOTH production entry points — deploy.sh and rollback.sh — go further
# and scrub the flag and every override before sourcing this file, so no
# combination of exported variables can reach the override branch during
# a real deploy or rollback.  The gate exists for direct/unit testing of
# these functions; the end-to-end suites double the privileged commands
# instead and let production constants stand.
_RC_PROD_SYSTEMD_UNIT_DIR="/etc/systemd/system"
_RC_PROD_PROC_DIR="/proc"
# The watchdog is EXECUTED by root, so its file is owned by root and
# kept outside the deploy-user-writable checkout.  That keeps ordinary
# edits to the checkout from becoming the root-executed script and
# preserves the intended ownership/execution layout.  It is not, by
# itself, containment of a compromised deploy identity — that identity
# already holds NOPASSWD root `install` and `systemctl` on this host.
_RC_PROD_WATCHDOG_OWNER="root:root"

if [[ "${RC_ALLOW_TEST_OVERRIDES:-0}" == "1" ]]; then
  # Loud on purpose.  deploy.sh scrubs this flag outright, so it can only
  # be reached from a harness — but "only a harness sets it" is a claim,
  # and a claim belongs in the log where an operator can falsify it.
  printf '[reconcile][WARN] TEST OVERRIDES ACTIVE — runtime paths and the required\n' >&2
  printf '[reconcile][WARN] watchdog owner are NOT the production constants.\n' >&2
  SYSTEMD_UNIT_DIR="${SYSTEMD_UNIT_DIR:-${_RC_PROD_SYSTEMD_UNIT_DIR}}"
  RC_PROC_DIR="${RC_PROC_DIR:-${_RC_PROD_PROC_DIR}}"
  RC_WATCHDOG_OWNER="${RC_WATCHDOG_OWNER:-${_RC_PROD_WATCHDOG_OWNER}}"
else
  SYSTEMD_UNIT_DIR="${_RC_PROD_SYSTEMD_UNIT_DIR}"
  RC_PROC_DIR="${_RC_PROD_PROC_DIR}"
  RC_WATCHDOG_OWNER="${_RC_PROD_WATCHDOG_OWNER}"
fi

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


# Is there a FUTURE monotonic activation?
#
# systemd pretty-prints timespan properties, so a scheduled value looks
# like "2w 3d 2h 8min 32.168902s" rather than a raw integer.  Every
# rendering that means "nothing scheduled" is rejected; anything else is
# a real next-elapse.
#
# `infinity` is rejected HERE and handled one level up, in
# _verify_runtime_controls, because it is the only one of these
# renderings with a legitimate explanation.
_rc_monotonic_elapse_is_scheduled() {
  local value="$1"
  [[ -n "${value}" ]] || return 1
  case "${value}" in
    0|0s|0us|n/a|infinity) return 1 ;;
  esac
  return 0
}

# Does the timer carry a RECURRING monotonic schedule, right now, per
# systemd — not per the unit file in this checkout?
#
# `TimersMonotonic` lists the monotonic timer definitions systemd
# actually loaded — one entry per directive, each on its own line.
# Measured on production 2026-08-13:
#
#   timer.TimersMonotonic  { OnUnitActiveUSec=1min ; next_elapse=2w 3d 7h 19min 55.xxxs }
#                          { OnBootUSec=3min ; next_elapse=3min }
#
# The recurring bases are the two that re-arm from the triggered unit's
# own activity; `OnBootUSec` alone fires once per boot and would leave a
# timer that looks enabled and never runs again.  Requiring one of them
# is what makes "no next activation because it is running right now"
# separable from "no next activation because there is no schedule".
#
# Substring match rather than a parse: the surrounding rendering of this
# property is a systemd version detail, the base NAME is the contract.
_rc_timer_has_recurring_monotonic_schedule() {
  local value="$1"
  [[ "${value}" == *OnUnitActiveUSec=* || "${value}" == *OnUnitInactiveUSec=* ]]
}

# Is the triggered unit genuinely EXECUTING at this instant?
#
# The healthcheck is `Type=oneshot`, so while its ExecStart runs systemd
# reports ActiveState=activating / SubState=start, and once it exits,
# inactive/dead.  `active`+`exited` is a FINISHED oneshot that declared
# RemainAfterExit — not execution — so it is excluded by name rather
# than by falling through a wildcard.
#
# This is the ONLY thing that can excuse a missing next activation, so
# it is decided on the service's own live state and never inferred from
# the timer's.
_rc_service_is_executing() {
  local active="$1" sub="$2"
  case "${active}" in
    activating|deactivating) return 0 ;;
  esac
  case "${sub}" in
    start|start-pre|start-post|running|reload) return 0 ;;
  esac
  return 1
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
      "${RISKIT_LIB_DIR}/dynasty-healthcheck.sh" 0755 "${RC_WATCHDOG_OWNER}" || rc=1
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
  local ls_t as_t ufs_t next_rt next_mono ls_s
  ls_t="$(_rc_sudo "$SC" show "${timer}" -p LoadState --value)"
  as_t="$(_rc_sudo "$SC" show "${timer}" -p ActiveState --value)"
  ufs_t="$(_rc_sudo "$SC" show "${timer}" -p UnitFileState --value)"
  next_rt="$(_rc_sudo "$SC" show "${timer}" -p NextElapseUSecRealtime --value)"
  ls_s="$(_rc_sudo "$SC" show "${svc}" -p LoadState --value)"

  # THE SCHEDULED-NEXT PROPERTY IS THE MONOTONIC ONE.
  #
  # systemd's Timer interface exposes two next-elapse properties, and
  # which one it populates follows the timer's BASE:
  #
  #   NextElapseUSecRealtime   — next CLOCK_REALTIME/calendar event.
  #                              Empty when the unit has no OnCalendar.
  #   NextElapseUSecMonotonic  — next CLOCK_MONOTONIC event, i.e. what
  #                              OnBootSec / OnUnitActiveSec produce.
  #
  # dynasty-healthcheck.timer ships OnBootSec=3min + OnUnitActiveSec=1min,
  # both monotonic, so the realtime field is empty by construction.
  # Measured on production 2026-08-13, an hour into the timer firing
  # every 60 s without interruption:
  #
  #   timer.NextElapseUSecRealtime    (empty)
  #   timer.NextElapseUSecMonotonic   2w 3d 2h 8min 32.168902s
  #   timer.LastTriggerUSec           Thu 2026-08-13 04:16:02 CEST
  #
  # So gating on the realtime field was not a first-activation race — it
  # is simply the wrong property, and it never becomes non-empty for this
  # timer.  It failed the #813 deploy against a perfectly scheduled
  # watchdog.
  #
  # LastTriggerUSec is deliberately NOT accepted as a substitute: a past
  # trigger says the timer HAS run, not that another run is scheduled.
  # It is logged as context and never gates.
  #
  # AND THE NEXT-ELAPSE IS NOT ALWAYS READABLE, EVEN WHEN HEALTHY.
  #
  # While the triggered oneshot is executing there is no next activation
  # to compute, and systemd answers `NextElapseUSecMonotonic=infinity`.
  # Observed on production 2026-08-13T06:29:24Z, six seconds after a
  # LastTriggerUSec of 08:29:18 CEST, on a timer that had been firing
  # every 60 s for hours.  The #814 gate rejected `infinity` outright, so
  # it passed only because its read happened to land between firings: a
  # healthy deploy could be failed by nothing worse than its own timing.
  # `TimeoutStartSec=90` on the service bounds how long that window can
  # last, which is far longer than any re-read worth spending on it.
  #
  # Sleeping past the execution is therefore the wrong fix.  The state is
  # DECIDABLE from live systemd properties, so it is decided:
  #
  #   finite next-elapse                     → scheduled.  Pass.
  #   infinity + service executing + the
  #     timer's recurring monotonic schedule
  #     still loaded                         → a transition, not a fault.
  #                                            Pass.
  #   infinity + service inactive/failed     → nothing is running and
  #                                            nothing is scheduled. Fail.
  #   empty / 0 / n-a                        → fail, whatever is running:
  #                                            those are not transitions.
  #   recurring monotonic schedule absent    → fail, whatever the
  #                                            next-elapse says.
  #
  # All four facts are re-read TOGETHER each attempt.  Reading them apart
  # invents its own race: a service that finishes between two reads
  # yields "infinity" beside "not executing" and fails a timer that just
  # re-armed correctly.
  #
  # The loop RE-READS through a transition rather than accepting it on
  # sight, and the ordering is deliberate.  A measured healthcheck
  # execution is ~0.2 s wide, so one re-read almost always lands after
  # the timer has re-armed and the run passes on a real next-elapse —
  # the ordinary path never needs the excuse at all.  Only an execution
  # outlasting the whole bounded window falls through to the transition
  # branch below, which is the case that branch exists for.
  #
  # Re-reading is also why the excuse can stay strict.  Sampling the
  # host at 5 Hz showed `TimersMonotonic` still carrying
  # `OnUnitActiveUSec` on every `activating/start` sample, so requiring
  # it mid-execution is a check the healthy state passes rather than a
  # second false-negative.  The same capture showed execution does NOT
  # always report `infinity`: at 07:50:45 the service was executing while
  # the timer still advertised the PREVIOUS finite next-elapse, systemd
  # not having recomputed it yet.  That row passes on the finite value,
  # which is the correct answer for it and another reason the finite
  # branch is tried first.
  local last_trigger attempt timers_mono svc_active svc_sub
  last_trigger="$(_rc_sudo "$SC" show "${timer}" -p LastTriggerUSec --value)"
  for attempt in 1 2 3 4 5; do
    next_mono="$(_rc_sudo "$SC" show "${timer}" -p NextElapseUSecMonotonic --value)"
    timers_mono="$(_rc_sudo "$SC" show "${timer}" -p TimersMonotonic --value)"
    svc_active="$(_rc_sudo "$SC" show "${svc}" -p ActiveState --value)"
    svc_sub="$(_rc_sudo "$SC" show "${svc}" -p SubState --value)"
    if _rc_monotonic_elapse_is_scheduled "${next_mono}"; then break; fi
    (( attempt < 5 )) && sleep 1
  done

  _rc_log "watchdog: timer load=${ls_t} active=${as_t} file=${ufs_t}"
  _rc_log "watchdog: next(monotonic)=${next_mono:-<empty>} next(realtime)=${next_rt:-<empty>} last=${last_trigger:-<never>}; service load=${ls_s} state=${svc_active:-<empty>}/${svc_sub:-<empty>}"
  _rc_log "watchdog: timers(monotonic)=${timers_mono:-<empty>}"
  [[ "${ls_t}"  == "loaded"  ]] || { _rc_err "${timer} LoadState=${ls_t}";      rc=1; }
  [[ "${ls_s}"  == "loaded"  ]] || { _rc_err "${svc} LoadState=${ls_s}";        rc=1; }
  [[ "${ufs_t}" == "enabled" ]] || { _rc_err "${timer} UnitFileState=${ufs_t}"; rc=1; }
  [[ "${as_t}"  == "active"  ]] || { _rc_err "${timer} ActiveState=${as_t}";    rc=1; }

  # Checked unconditionally, not only on the `infinity` branch: a timer
  # whose recurring schedule is gone runs at most once more and then
  # never again, and it reports a perfectly finite next-elapse until it
  # does.  A next-elapse is a symptom; this is the schedule itself.
  if ! _rc_timer_has_recurring_monotonic_schedule "${timers_mono}"; then
    _rc_err "${timer} declares no recurring monotonic schedule (TimersMonotonic='${timers_mono:-<empty>}') — it cannot keep firing"
    rc=1
  elif ! _rc_monotonic_elapse_is_scheduled "${next_mono}"; then
    if [[ "${next_mono}" == "infinity" ]] \
       && _rc_service_is_executing "${svc_active}" "${svc_sub}"; then
      _rc_log "watchdog: no next activation while ${svc} is executing (${svc_active}/${svc_sub}) — recurring schedule intact, accepting"
    else
      _rc_err "${timer} has no future monotonic activation (NextElapseUSecMonotonic='${next_mono:-<empty>}', ${svc} ${svc_active:-<empty>}/${svc_sub:-<empty>})"
      rc=1
    fi
  fi

  # the INSTALLED executable, not the checkout copy.
  local installed="${RISKIT_LIB_DIR:-/usr/local/lib/riskit}/dynasty-healthcheck.sh"
  local owner mode
  if [[ ! -r "${installed}" ]]; then
    _rc_err "${installed} is missing or unreadable — cannot verify the watchdog that actually runs"
    return 1
  fi
  owner="$(stat -c '%U:%G' "${installed}")"
  mode="$(stat -c '%a' "${installed}")"
  if [[ "${owner}" != "${RC_WATCHDOG_OWNER}" ]]; then
    _rc_err "${installed} owner=${owner}, expected ${RC_WATCHDOG_OWNER}"; rc=1
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
