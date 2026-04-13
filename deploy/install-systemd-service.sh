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
    tmp_frontend="$(mktemp)"
    sed \
      -e "s/__SERVICE_NAME__/$(escape_sed_replacement "${SERVICE_NAME}")/g" \
      -e "s/__APP_USER__/$(escape_sed_replacement "${APP_USER}")/g" \
      -e "s/__APP_DIR__/$(escape_sed_replacement "${APP_DIR}")/g" \
      -e "s/__VENV_DIR__/$(escape_sed_replacement "${VENV_DIR}")/g" \
      "${frontend_template}" > "${tmp_frontend}"
    sudo -n "${INSTALL_BIN}" -m 0644 "${tmp_frontend}" "${frontend_unit_path}"
    log "Installed ${frontend_name}.service"
  fi

  # ── daemon-reload and enable ────────────────────────────────────────────
  if [[ "${backend_needs_install}" == "true" || "${frontend_needs_install}" == "true" ]]; then
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
}

main "$@"
