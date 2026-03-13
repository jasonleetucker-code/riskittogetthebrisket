#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_APP_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

APP_DIR="${APP_DIR:-${DEFAULT_APP_DIR}}"
APP_USER="${APP_USER:-$(id -un)}"
VENV_DIR="${VENV_DIR:-${APP_DIR}/.venv}"
SERVICE_NAME="${SERVICE_NAME:-dynasty}"
APP_HOST="${APP_HOST:-127.0.0.1}"
APP_PORT="${APP_PORT:-8000}"
PUBLIC_URL="${PUBLIC_URL:-}"
STRICT_LOCAL_HEALTH="${STRICT_LOCAL_HEALTH:-true}"
ROLLBACK_REF="${1:-${ROLLBACK_REF:-}}"

log() {
  printf '[rollback] %s\n' "$*"
}

warn() {
  printf '[rollback][WARN] %s\n' "$*" >&2
}

error() {
  printf '[rollback][ERROR] %s\n' "$*" >&2
}

require_command() {
  local cmd="$1"
  command -v "${cmd}" >/dev/null 2>&1 || {
    error "Required command not found: ${cmd}"
    exit 1
  }
}

require_noninteractive_sudo() {
  if ! sudo -n true >/dev/null 2>&1; then
    error "Passwordless sudo is required for rollback automation."
    exit 1
  fi
}

resolve_git_ref() {
  local ref="$1"
  if git rev-parse --verify --quiet "${ref}^{commit}" >/dev/null; then
    git rev-parse "${ref}^{commit}"
    return 0
  fi
  if git rev-parse --verify --quiet "origin/${ref}^{commit}" >/dev/null; then
    git rev-parse "origin/${ref}^{commit}"
    return 0
  fi
  return 1
}

canonical_requirements_file() {
  printf '%s\n' "requirements.txt"
}

ensure_venv_site_packages_writable() {
  local venv_python="$1"
  local site_packages=""

  site_packages="$("${venv_python}" - <<'PY'
import sysconfig
print(sysconfig.get_paths().get("purelib", ""))
PY
)"

  if [[ -z "${site_packages}" ]]; then
    warn "Could not resolve site-packages path from venv; skipping ownership check."
    return 0
  fi

  if [[ -w "${site_packages}" ]]; then
    return 0
  fi

  warn "site-packages is not writable (${site_packages}); repairing ownership on ${VENV_DIR}."
  sudo -n chown -R "${APP_USER}:${APP_USER}" "${VENV_DIR}"

  if [[ ! -w "${site_packages}" ]]; then
    error "site-packages remains non-writable after ownership repair: ${site_packages}"
    exit 1
  fi
}

prepare_python_runtime() {
  local req_file
  req_file="$(canonical_requirements_file)"
  if [[ ! -f "${req_file}" ]]; then
    warn "Canonical Python dependency manifest is missing in rollback target (${APP_DIR}/${req_file}); skipping dependency install."
    return 0
  fi
  log "Python dependency manifest detected: ${req_file}"
  require_command python3
  if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
    log "Creating virtualenv at ${VENV_DIR}"
    python3 -m venv "${VENV_DIR}"
  fi
  ensure_venv_site_packages_writable "${VENV_DIR}/bin/python"
  "${VENV_DIR}/bin/python" -m pip install --upgrade pip
  "${VENV_DIR}/bin/pip" install -r "${req_file}"
}

main() {
  require_command git
  require_command bash
  require_command systemctl
  require_command sudo
  require_noninteractive_sudo

  [[ -d "${APP_DIR}" ]] || { error "APP_DIR does not exist: ${APP_DIR}"; exit 1; }
  cd "${APP_DIR}"
  [[ -d ".git" ]] || { error "APP_DIR is not a git repository: ${APP_DIR}"; exit 1; }

  local state_dir rollback_target current_rev target_rev
  state_dir="${APP_DIR}/.deploy"
  mkdir -p "${state_dir}"

  if [[ -z "${ROLLBACK_REF}" && -f "${state_dir}/pre_deploy_rev" ]]; then
    ROLLBACK_REF="$(head -n 1 "${state_dir}/pre_deploy_rev" | tr -d '\r\n')"
  fi
  if [[ -z "${ROLLBACK_REF}" && -f "${state_dir}/last_successful_rev" ]]; then
    ROLLBACK_REF="$(head -n 1 "${state_dir}/last_successful_rev" | tr -d '\r\n')"
  fi
  if [[ -z "${ROLLBACK_REF}" ]]; then
    error "No rollback target specified and no saved revision found."
    exit 1
  fi

  git fetch --prune --tags origin
  if ! rollback_target="$(resolve_git_ref "${ROLLBACK_REF}")"; then
    error "Could not resolve rollback ref '${ROLLBACK_REF}'."
    exit 1
  fi

  current_rev="$(git rev-parse HEAD)"
  target_rev="$(git rev-parse --short "${rollback_target}")"
  log "Rolling back from ${current_rev} to ${rollback_target} (${target_rev})."

  git checkout --force "${rollback_target}"
  git reset --hard "${rollback_target}"

  prepare_python_runtime

  log "Restarting service ${SERVICE_NAME} after rollback."
  sudo -n systemctl restart "${SERVICE_NAME}"
  if ! sudo -n systemctl is-active --quiet "${SERVICE_NAME}"; then
    error "Service ${SERVICE_NAME} is not active after rollback restart."
    sudo -n journalctl -u "${SERVICE_NAME}" -n 120 --no-pager || true
    exit 1
  fi

  if [[ -f "${APP_DIR}/deploy/verify-deploy.sh" ]]; then
    APP_HOST="${APP_HOST}" \
    APP_PORT="${APP_PORT}" \
    SERVICE_NAME="${SERVICE_NAME}" \
    PUBLIC_URL="${PUBLIC_URL}" \
    STRICT_LOCAL_HEALTH="${STRICT_LOCAL_HEALTH}" \
    bash "${APP_DIR}/deploy/verify-deploy.sh"
  fi

  printf '%s\n' "${rollback_target}" > "${state_dir}/last_successful_rev"
  printf '%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "${state_dir}/last_successful_at_utc"
  log "Rollback complete. Active revision: ${rollback_target}"
}

main "$@"
