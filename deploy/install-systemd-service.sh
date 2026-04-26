#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_APP_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

APP_DIR="${APP_DIR:-${DEFAULT_APP_DIR}}"
APP_USER="${APP_USER:-$(id -un)}"
APP_SLUG="${APP_SLUG:-$(basename "${APP_DIR}")}"
VENV_DIR="${VENV_DIR:-${HOME}/.venvs/${APP_SLUG}}"
SERVICE_NAME="${SERVICE_NAME:-dynasty}"
SERVICE_TEMPLATE_PATH="${SERVICE_TEMPLATE_PATH:-${APP_DIR}/deploy/systemd/dynasty.service.template}"
FORCE_SERVICE_INSTALL="${FORCE_SERVICE_INSTALL:-false}"
SYSTEMCTL_BIN=""
INSTALL_BIN=""

log() {
  printf '[systemd-bootstrap] %s\n' "$*"
}

error() {
  printf '[systemd-bootstrap][ERROR] %s\n' "$*" >&2
}

lower() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]'
}

require_command() {
  local cmd="$1"
  command -v "${cmd}" >/dev/null 2>&1 || {
    error "Required command not found: ${cmd}"
    exit 1
  }
}

resolve_sudo_nopasswd_binary() {
  local label="$1"
  shift
  local candidate
  local checked_candidates=""

  for candidate in "$@"; do
    [[ -x "${candidate}" ]] || continue
    checked_candidates="${checked_candidates}${checked_candidates:+, }${candidate}"
    if sudo -n "${candidate}" --version >/dev/null 2>&1; then
      printf '%s\n' "${candidate}"
      return 0
    fi
  done

  if [[ -n "${checked_candidates}" ]]; then
    error "Missing NOPASSWD sudo permission for ${label}. Checked: ${checked_candidates}"
  else
    error "Could not resolve required binary for ${label}. Checked: $*"
  fi
  exit 1
}

resolve_and_validate_sudo_binaries() {
  SYSTEMCTL_BIN="$(resolve_sudo_nopasswd_binary "systemctl" /bin/systemctl /usr/bin/systemctl)"
  INSTALL_BIN="$(resolve_sudo_nopasswd_binary "install" /usr/bin/install /bin/install)"
}

# Locate an absolute path to the `npm` binary that the dynasty-frontend
# systemd unit can use as ExecStart.  This mirrors deploy.sh's
# resolve_node_toolchain but returns paths instead of relying on PATH
# side-effects, because systemd runs with a minimal environment and
# will not source nvm.sh on its own.
#
# Writes two values to NPM_BIN_PATH and NODE_BIN_DIR on success.
# Returns 1 and logs an error if npm cannot be located.
NPM_BIN_PATH=""
NODE_BIN_DIR=""

resolve_npm_bin_for_systemd() {
  NPM_BIN_PATH=""
  NODE_BIN_DIR=""

  local candidate
  # 1. System-wide install (Debian/Ubuntu package).
  for candidate in /usr/bin/npm /usr/local/bin/npm; do
    if [[ -x "${candidate}" ]]; then
      NPM_BIN_PATH="${candidate}"
      NODE_BIN_DIR="$(dirname "${candidate}")"
      return 0
    fi
  done

  # 2. Anything already on PATH (e.g. from operator shell profile).
  if command -v npm >/dev/null 2>&1; then
    NPM_BIN_PATH="$(command -v npm)"
    NODE_BIN_DIR="$(dirname "${NPM_BIN_PATH}")"
    return 0
  fi

  # 3. nvm-installed node under the service user's home dir.  This is
  # the production case — the Hetzner VPS manages node via nvm and
  # /usr/bin/npm does not exist.
  local home_candidates=(
    "/home/${APP_USER}"
    "${HOME:-}"
  )
  local home_dir=""
  for candidate in "${home_candidates[@]}"; do
    if [[ -n "${candidate}" && -d "${candidate}" ]]; then
      home_dir="${candidate}"
      break
    fi
  done

  local nvm_dir=""
  if [[ -n "${home_dir}" && -d "${home_dir}/.nvm" ]]; then
    nvm_dir="${home_dir}/.nvm"
  fi

  if [[ -n "${nvm_dir}" && -d "${nvm_dir}/versions/node" ]]; then
    local node_bin
    node_bin="$(
      find "${nvm_dir}/versions/node" -mindepth 2 -maxdepth 2 -type d -name bin 2>/dev/null \
      | sort -V \
      | tail -n 1
    )"
    if [[ -n "${node_bin}" && -x "${node_bin}/npm" ]]; then
      NPM_BIN_PATH="${node_bin}/npm"
      NODE_BIN_DIR="${node_bin}"
      return 0
    fi
  fi

  error "Could not locate npm for dynasty-frontend systemd unit."
  error "Checked: /usr/bin/npm, /usr/local/bin/npm, PATH, and ${nvm_dir:-<no nvm dir>}/versions/node/*/bin/npm"
  return 1
}

escape_sed_replacement() {
  printf '%s' "$1" | sed -e 's/[\\/&]/\\&/g'
}

main() {
  local force_install force_install_on unit_path tmp_unit
  local frontend_template frontend_name frontend_unit_path tmp_frontend
  local backend_needs_install=false
  local frontend_needs_install=false

  require_command sudo
  require_command install
  require_command mktemp
  require_command sed
  require_command systemctl
  resolve_and_validate_sudo_binaries

  [[ -n "${SERVICE_NAME}" ]] || { error "SERVICE_NAME cannot be empty."; exit 1; }
  [[ -n "${APP_USER}" ]] || { error "APP_USER cannot be empty."; exit 1; }
  [[ -n "${APP_DIR}" ]] || { error "APP_DIR cannot be empty."; exit 1; }
  [[ -n "${VENV_DIR}" ]] || { error "VENV_DIR cannot be empty."; exit 1; }
  [[ -f "${SERVICE_TEMPLATE_PATH}" ]] || { error "Service template not found: ${SERVICE_TEMPLATE_PATH}"; exit 1; }

  force_install="$(lower "${FORCE_SERVICE_INSTALL}")"
  force_install_on=false
  if [[ "${force_install}" == "true" || "${force_install}" == "1" || "${force_install}" == "yes" ]]; then
    force_install_on=true
  fi

  tmp_unit=""
  tmp_frontend=""
  trap 'rm -f "${tmp_unit:-}" "${tmp_frontend:-}"' EXIT

  # ── Backend service (FastAPI) ───────────────────────────────────────────
  # Deliberately do NOT `exit 0` early when the backend unit already
  # exists: we still need to check whether the frontend unit is
  # installed.  A previous version of this script exited here, which
  # meant production (where the backend was already installed) never
  # got the frontend systemd unit and silently ran Next.js under some
  # unmanaged process manager, so deploy.sh could not restart it.
  unit_path="/etc/systemd/system/${SERVICE_NAME}.service"
  if sudo -n "${SYSTEMCTL_BIN}" cat "${SERVICE_NAME}" >/dev/null 2>&1; then
    if [[ "${force_install_on}" == "true" ]]; then
      log "FORCE_SERVICE_INSTALL enabled; rewriting ${unit_path}."
      backend_needs_install=true
    else
      log "Backend service ${SERVICE_NAME} already installed; skipping."
    fi
  else
    log "Installing missing backend systemd unit ${unit_path}."
    backend_needs_install=true
  fi

  if [[ "${backend_needs_install}" == "true" ]]; then
    tmp_unit="$(mktemp)"
    sed \
      -e "s/__SERVICE_NAME__/$(escape_sed_replacement "${SERVICE_NAME}")/g" \
      -e "s/__APP_USER__/$(escape_sed_replacement "${APP_USER}")/g" \
      -e "s/__APP_DIR__/$(escape_sed_replacement "${APP_DIR}")/g" \
      -e "s/__VENV_DIR__/$(escape_sed_replacement "${VENV_DIR}")/g" \
      "${SERVICE_TEMPLATE_PATH}" > "${tmp_unit}"
    sudo -n "${INSTALL_BIN}" -m 0644 "${tmp_unit}" "${unit_path}"
    log "Installed ${SERVICE_NAME}.service"
  fi

  # ── Frontend service (Next.js) ──────────────────────────────────────────
  frontend_template="${APP_DIR}/deploy/systemd/dynasty-frontend.service.template"
  frontend_name="${SERVICE_NAME}-frontend"
  frontend_unit_path="/etc/systemd/system/${frontend_name}.service"

  if [[ ! -f "${frontend_template}" ]]; then
    error "Frontend service template not found at ${frontend_template}."
    error "The Next.js process must be managed by systemd; aborting bootstrap."
    exit 1
  fi

  if sudo -n "${SYSTEMCTL_BIN}" cat "${frontend_name}" >/dev/null 2>&1; then
    if [[ "${force_install_on}" == "true" ]]; then
      log "FORCE_SERVICE_INSTALL enabled; rewriting ${frontend_unit_path}."
      frontend_needs_install=true
    else
      log "Frontend service ${frontend_name} already installed; skipping."
    fi
  else
    log "Installing missing frontend systemd unit ${frontend_unit_path}."
    frontend_needs_install=true
  fi

  if [[ "${frontend_needs_install}" == "true" ]]; then
    # Resolve npm absolute path now so the rendered unit file uses a
    # path that actually exists under the service user's runtime.
    # Systemd does NOT source ~/.bashrc or nvm.sh, so relying on PATH
    # alone will fail on nvm-based production boxes.
    if ! resolve_npm_bin_for_systemd; then
      error "Cannot render dynasty-frontend unit without an absolute npm path."
      exit 1
    fi
    log "Resolved npm for frontend unit: ${NPM_BIN_PATH} (PATH dir: ${NODE_BIN_DIR})"

    tmp_frontend="$(mktemp)"
    sed \
      -e "s/__SERVICE_NAME__/$(escape_sed_replacement "${SERVICE_NAME}")/g" \
      -e "s/__APP_USER__/$(escape_sed_replacement "${APP_USER}")/g" \
      -e "s/__APP_DIR__/$(escape_sed_replacement "${APP_DIR}")/g" \
      -e "s/__VENV_DIR__/$(escape_sed_replacement "${VENV_DIR}")/g" \
      -e "s/__NPM_BIN__/$(escape_sed_replacement "${NPM_BIN_PATH}")/g" \
      -e "s/__NODE_BIN_DIR__/$(escape_sed_replacement "${NODE_BIN_DIR}")/g" \
      "${frontend_template}" > "${tmp_frontend}"
    sudo -n "${INSTALL_BIN}" -m 0644 "${tmp_frontend}" "${frontend_unit_path}"
    log "Installed ${frontend_name}.service"
  fi

  # ── Signal-alerts sweep (optional systemd timer) ───────────────────────
  # Deploys a one-shot service + daily timer that POSTs the internal
  # /api/signal-alerts/run endpoint.  We only install these units when
  # both templates exist AND SIGNAL_ALERT_CRON_TOKEN is set in the
  # .env file — without the token the endpoint would reject the
  # bearer auth, so there's no point enabling the timer yet.
  local alerts_service_template="${APP_DIR}/deploy/systemd/dynasty-signal-alerts.service.template"
  local alerts_timer_template="${APP_DIR}/deploy/systemd/dynasty-signal-alerts.timer.template"
  local alerts_service_name="${SERVICE_NAME}-signal-alerts"
  local alerts_service_path="/etc/systemd/system/${alerts_service_name}.service"
  local alerts_timer_path="/etc/systemd/system/${alerts_service_name}.timer"
  local alerts_needs_install=false
  local has_cron_token=false

  if [[ -f "${APP_DIR}/.env" ]] && grep -Eq '^[[:space:]]*SIGNAL_ALERT_CRON_TOKEN=.+$' "${APP_DIR}/.env"; then
    has_cron_token=true
  fi

  if [[ -f "${alerts_service_template}" && -f "${alerts_timer_template}" && "${has_cron_token}" == "true" ]]; then
    if sudo -n "${SYSTEMCTL_BIN}" cat "${alerts_service_name}.timer" >/dev/null 2>&1; then
      if [[ "${force_install_on}" == "true" ]]; then
        log "FORCE_SERVICE_INSTALL enabled; rewriting ${alerts_service_path} + timer."
        alerts_needs_install=true
      else
        log "Signal-alerts timer already installed; skipping."
      fi
    else
      log "Installing signal-alerts service + timer."
      alerts_needs_install=true
    fi

    if [[ "${alerts_needs_install}" == "true" ]]; then
      local tmp_alerts_service tmp_alerts_timer
      tmp_alerts_service="$(mktemp)"
      tmp_alerts_timer="$(mktemp)"
      trap 'rm -f "${tmp_unit:-}" "${tmp_frontend:-}" "${tmp_alerts_service:-}" "${tmp_alerts_timer:-}"' EXIT
      sed \
        -e "s/__SERVICE_NAME__/$(escape_sed_replacement "${SERVICE_NAME}")/g" \
        -e "s/__APP_USER__/$(escape_sed_replacement "${APP_USER}")/g" \
        -e "s/__APP_DIR__/$(escape_sed_replacement "${APP_DIR}")/g" \
        "${alerts_service_template}" > "${tmp_alerts_service}"
      sed \
        -e "s/__SERVICE_NAME__/$(escape_sed_replacement "${SERVICE_NAME}")/g" \
        "${alerts_timer_template}" > "${tmp_alerts_timer}"
      sudo -n "${INSTALL_BIN}" -m 0644 "${tmp_alerts_service}" "${alerts_service_path}"
      sudo -n "${INSTALL_BIN}" -m 0644 "${tmp_alerts_timer}" "${alerts_timer_path}"
      log "Installed ${alerts_service_name}.service + .timer"
    fi
  elif [[ -f "${alerts_service_template}" && "${has_cron_token}" != "true" ]]; then
    log "Signal-alerts timer skipped: SIGNAL_ALERT_CRON_TOKEN not set in ${APP_DIR}/.env."
  fi

  # ── Custom-alerts sweep (optional systemd timer) ───────────────────────
  # Same pattern as signal-alerts: install only when the cron token is
  # present.  Fires every 2 hours; the rule-engine cooldown inside
  # ``custom_alerts.py`` keeps a single rule from re-firing within 24h.
  local custom_alerts_service_template="${APP_DIR}/deploy/systemd/dynasty-custom-alerts.service.template"
  local custom_alerts_timer_template="${APP_DIR}/deploy/systemd/dynasty-custom-alerts.timer.template"
  local custom_alerts_service_name="${SERVICE_NAME}-custom-alerts"
  local custom_alerts_service_path="/etc/systemd/system/${custom_alerts_service_name}.service"
  local custom_alerts_timer_path="/etc/systemd/system/${custom_alerts_service_name}.timer"
  local custom_alerts_needs_install=false

  if [[ -f "${custom_alerts_service_template}" && -f "${custom_alerts_timer_template}" && "${has_cron_token}" == "true" ]]; then
    if sudo -n "${SYSTEMCTL_BIN}" cat "${custom_alerts_service_name}.timer" >/dev/null 2>&1; then
      if [[ "${force_install_on}" == "true" ]]; then
        log "FORCE_SERVICE_INSTALL enabled; rewriting ${custom_alerts_service_path} + timer."
        custom_alerts_needs_install=true
      else
        log "Custom-alerts timer already installed; skipping."
      fi
    else
      log "Installing custom-alerts service + timer."
      custom_alerts_needs_install=true
    fi

    if [[ "${custom_alerts_needs_install}" == "true" ]]; then
      local tmp_custom_alerts_service tmp_custom_alerts_timer
      tmp_custom_alerts_service="$(mktemp)"
      tmp_custom_alerts_timer="$(mktemp)"
      sed \
        -e "s/__SERVICE_NAME__/$(escape_sed_replacement "${SERVICE_NAME}")/g" \
        -e "s/__APP_USER__/$(escape_sed_replacement "${APP_USER}")/g" \
        -e "s/__APP_DIR__/$(escape_sed_replacement "${APP_DIR}")/g" \
        "${custom_alerts_service_template}" > "${tmp_custom_alerts_service}"
      sed \
        -e "s/__SERVICE_NAME__/$(escape_sed_replacement "${SERVICE_NAME}")/g" \
        "${custom_alerts_timer_template}" > "${tmp_custom_alerts_timer}"
      sudo -n "${INSTALL_BIN}" -m 0644 "${tmp_custom_alerts_service}" "${custom_alerts_service_path}"
      sudo -n "${INSTALL_BIN}" -m 0644 "${tmp_custom_alerts_timer}" "${custom_alerts_timer_path}"
      rm -f "${tmp_custom_alerts_service}" "${tmp_custom_alerts_timer}"
      log "Installed ${custom_alerts_service_name}.service + .timer"
    fi
  fi

  # ── daemon-reload and enable ────────────────────────────────────────────
  if [[ "${backend_needs_install}" == "true" || "${frontend_needs_install}" == "true" || "${alerts_needs_install}" == "true" || "${custom_alerts_needs_install}" == "true" ]]; then
    sudo -n "${SYSTEMCTL_BIN}" daemon-reload
    log "Reloaded systemd unit files."
  fi

  if [[ "${backend_needs_install}" == "true" ]]; then
    sudo -n "${SYSTEMCTL_BIN}" enable "${SERVICE_NAME}"
    log "Enabled ${SERVICE_NAME}.service"
  fi
  if [[ "${frontend_needs_install}" == "true" ]]; then
    sudo -n "${SYSTEMCTL_BIN}" enable "${frontend_name}"
    log "Enabled ${frontend_name}.service"
  fi
  if [[ "${alerts_needs_install}" == "true" ]]; then
    sudo -n "${SYSTEMCTL_BIN}" enable --now "${alerts_service_name}.timer"
    log "Enabled ${alerts_service_name}.timer"
  fi
  if [[ "${custom_alerts_needs_install}" == "true" ]]; then
    sudo -n "${SYSTEMCTL_BIN}" enable --now "${custom_alerts_service_name}.timer"
    log "Enabled ${custom_alerts_service_name}.timer"
  fi

  # ── Backup timer + restore-test timer + logrotate (2026-04-25) ──
  # Idempotent: copies from deploy/systemd/ if not already installed.
  # Units hardcode paths to /home/dynasty/trade-calculator so they
  # don't need template rendering.  Safe to re-run on every deploy;
  # `cp` + `install` overwrites with an identical file when the
  # source is unchanged.  Enabling is idempotent too.
  local any_backup_installed=false
  for unit in riskit-backup.service riskit-backup.timer \
              riskit-backup-restore-test.service riskit-backup-restore-test.timer; do
    local src="${APP_DIR}/deploy/systemd/${unit}"
    local dst="/etc/systemd/system/${unit}"
    if [[ ! -f "${src}" ]]; then
      continue
    fi
    # Only reinstall when the target is missing OR content differs —
    # keeps daemon-reload churn to a minimum.
    if [[ ! -f "${dst}" ]] || ! sudo -n cmp -s "${src}" "${dst}" 2>/dev/null; then
      sudo -n "${INSTALL_BIN}" -m 0644 "${src}" "${dst}"
      log "Installed ${unit}"
      any_backup_installed=true
    fi
  done

  if [[ "${any_backup_installed}" == "true" ]]; then
    sudo -n "${SYSTEMCTL_BIN}" daemon-reload
    log "Reloaded systemd unit files (backup timers)."
  fi

  # Enable timers — safe to re-run; --now starts them if inactive.
  for timer in riskit-backup.timer riskit-backup-restore-test.timer; do
    local timer_path="/etc/systemd/system/${timer}"
    if [[ -f "${timer_path}" ]]; then
      if ! sudo -n "${SYSTEMCTL_BIN}" is-enabled "${timer}" >/dev/null 2>&1; then
        sudo -n "${SYSTEMCTL_BIN}" enable --now "${timer}" >/dev/null 2>&1 || \
          log "Note: enable ${timer} skipped (likely no systemd user unit perms)."
        log "Enabled ${timer}"
      fi
    fi
  done

  # Logrotate config — copy into /etc/logrotate.d/ if changed.
  local logrotate_src="${APP_DIR}/deploy/logrotate.conf"
  local logrotate_dst="/etc/logrotate.d/riskit"
  if [[ -f "${logrotate_src}" ]]; then
    if [[ ! -f "${logrotate_dst}" ]] || ! sudo -n cmp -s "${logrotate_src}" "${logrotate_dst}" 2>/dev/null; then
      sudo -n "${INSTALL_BIN}" -m 0644 "${logrotate_src}" "${logrotate_dst}"
      log "Installed /etc/logrotate.d/riskit"
    fi
  fi
}

main "$@"
