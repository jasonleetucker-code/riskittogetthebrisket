#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_APP_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

APP_DIR="${APP_DIR:-${DEFAULT_APP_DIR}}"
APP_SLUG="${APP_SLUG:-$(basename "${APP_DIR}")}"
VENV_DIR="${VENV_DIR:-${HOME}/.venvs/${APP_SLUG}}"
SERVICE_NAME="${SERVICE_NAME:-dynasty}"
APP_HOST="${APP_HOST:-127.0.0.1}"
APP_PORT="${APP_PORT:-8000}"
PUBLIC_URL="${PUBLIC_URL:-}"
STRICT_LOCAL_HEALTH="${STRICT_LOCAL_HEALTH:-true}"
ROLLBACK_REF="${1:-${ROLLBACK_REF:-}}"
DEPLOY_STATE_DIR="${DEPLOY_STATE_DIR:-${HOME}/.deploy-state}"
LAST_SUCCESSFUL_DEPLOY_COMMIT_FILE="${LAST_SUCCESSFUL_DEPLOY_COMMIT_FILE:-${DEPLOY_STATE_DIR}/${APP_SLUG}.last_successful_deploy_commit}"
PRE_DEPLOY_COMMIT_FILE="${PRE_DEPLOY_COMMIT_FILE:-${DEPLOY_STATE_DIR}/${APP_SLUG}.pre_deploy_commit}"
LAST_SUCCESSFUL_DEPLOY_AT_FILE="${LAST_SUCCESSFUL_DEPLOY_AT_FILE:-${DEPLOY_STATE_DIR}/${APP_SLUG}.last_successful_at_utc}"

log() {
  printf '[rollback] %s\n' "$*"
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

ensure_parent_dir() {
  local target="$1"
  mkdir -p "$(dirname "${target}")"
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

detect_requirements_file() {
  local candidate
  for candidate in requirements-prod.txt requirements.txt requirements-dev.txt; do
    if [[ -f "${candidate}" ]]; then
      printf '%s\n' "${candidate}"
      return 0
    fi
  done
  return 1
}

prepare_python_runtime() {
  local req_file=""
  if ! req_file="$(detect_requirements_file)"; then
    log "No Python dependency manifest found; skipping pip install."
    return 0
  fi
  require_command python3
  mkdir -p "$(dirname "${VENV_DIR}")"
  if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
    log "Creating virtualenv at ${VENV_DIR}"
    python3 -m venv "${VENV_DIR}"
  fi
  "${VENV_DIR}/bin/python" -m pip install --upgrade pip
  "${VENV_DIR}/bin/pip" install -r "${req_file}"
}

main() {
  require_command git
  require_command bash
  require_command systemctl

  [[ -d "${APP_DIR}" ]] || { error "APP_DIR does not exist: ${APP_DIR}"; exit 1; }
  cd "${APP_DIR}"
  [[ -d ".git" ]] || { error "APP_DIR is not a git repository: ${APP_DIR}"; exit 1; }

  local rollback_target current_rev target_rev legacy_state_dir

  if [[ -z "${ROLLBACK_REF}" && -f "${PRE_DEPLOY_COMMIT_FILE}" ]]; then
    ROLLBACK_REF="$(head -n 1 "${PRE_DEPLOY_COMMIT_FILE}" | tr -d '\r\n')"
  fi
  if [[ -z "${ROLLBACK_REF}" && -f "${LAST_SUCCESSFUL_DEPLOY_COMMIT_FILE}" ]]; then
    ROLLBACK_REF="$(head -n 1 "${LAST_SUCCESSFUL_DEPLOY_COMMIT_FILE}" | tr -d '\r\n')"
  fi

  # Legacy fallback for hosts that still have in-repo deploy state from older scripts.
  legacy_state_dir="${APP_DIR}/.deploy"
  if [[ -z "${ROLLBACK_REF}" && -f "${legacy_state_dir}/pre_deploy_rev" ]]; then
    ROLLBACK_REF="$(head -n 1 "${legacy_state_dir}/pre_deploy_rev" | tr -d '\r\n')"
  fi
  if [[ -z "${ROLLBACK_REF}" && -f "${legacy_state_dir}/last_successful_rev" ]]; then
    ROLLBACK_REF="$(head -n 1 "${legacy_state_dir}/last_successful_rev" | tr -d '\r\n')"
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
  sudo systemctl restart "${SERVICE_NAME}"
  if ! sudo systemctl is-active --quiet "${SERVICE_NAME}"; then
    error "Service ${SERVICE_NAME} is not active after rollback restart."
    sudo journalctl -u "${SERVICE_NAME}" -n 120 --no-pager || true
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

  ensure_parent_dir "${LAST_SUCCESSFUL_DEPLOY_COMMIT_FILE}"
  ensure_parent_dir "${LAST_SUCCESSFUL_DEPLOY_AT_FILE}"
  printf '%s\n' "${rollback_target}" > "${LAST_SUCCESSFUL_DEPLOY_COMMIT_FILE}"
  printf '%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "${LAST_SUCCESSFUL_DEPLOY_AT_FILE}"
  log "Rollback complete. Active revision: ${rollback_target}"
}

main "$@"
