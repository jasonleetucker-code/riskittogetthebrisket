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

escape_sed_replacement() {
  printf '%s' "$1" | sed -e 's/[\\/&]/\\&/g'
}

main() {
  local force_install unit_path tmp_unit

  require_command sudo
  require_command install
  require_command mktemp
  require_command sed
  require_command systemctl

  [[ -n "${SERVICE_NAME}" ]] || { error "SERVICE_NAME cannot be empty."; exit 1; }
  [[ -n "${APP_USER}" ]] || { error "APP_USER cannot be empty."; exit 1; }
  [[ -n "${APP_DIR}" ]] || { error "APP_DIR cannot be empty."; exit 1; }
  [[ -n "${VENV_DIR}" ]] || { error "VENV_DIR cannot be empty."; exit 1; }
  [[ -f "${SERVICE_TEMPLATE_PATH}" ]] || { error "Service template not found: ${SERVICE_TEMPLATE_PATH}"; exit 1; }

  force_install="$(lower "${FORCE_SERVICE_INSTALL}")"
  unit_path="/etc/systemd/system/${SERVICE_NAME}.service"
  if sudo systemctl cat "${SERVICE_NAME}" >/dev/null 2>&1; then
    if [[ "${force_install}" != "true" && "${force_install}" != "1" && "${force_install}" != "yes" ]]; then
      log "Service ${SERVICE_NAME} already exists; skipping bootstrap install."
      exit 0
    fi
    log "FORCE_SERVICE_INSTALL enabled; rewriting ${unit_path}."
  else
    log "Installing missing systemd unit ${unit_path}."
  fi

  tmp_unit="$(mktemp)"
  trap 'rm -f "${tmp_unit}"' EXIT
  sed \
    -e "s/__SERVICE_NAME__/$(escape_sed_replacement "${SERVICE_NAME}")/g" \
    -e "s/__APP_USER__/$(escape_sed_replacement "${APP_USER}")/g" \
    -e "s/__APP_DIR__/$(escape_sed_replacement "${APP_DIR}")/g" \
    -e "s/__VENV_DIR__/$(escape_sed_replacement "${VENV_DIR}")/g" \
    "${SERVICE_TEMPLATE_PATH}" > "${tmp_unit}"

  sudo install -m 0644 "${tmp_unit}" "${unit_path}"
  sudo systemctl daemon-reload
  sudo systemctl enable "${SERVICE_NAME}"
  log "Installed and enabled ${SERVICE_NAME}.service"
}

main "$@"
