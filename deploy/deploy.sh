#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_APP_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

APP_NAME="${APP_NAME:-riskittogetthebrisket}"
APP_USER="${APP_USER:-$(id -un)}"
APP_DIR="${APP_DIR:-${DEFAULT_APP_DIR}}"
VENV_DIR="${VENV_DIR:-${APP_DIR}/.venv}"
SERVICE_NAME="${SERVICE_NAME:-dynasty}"
DEPLOY_BRANCH="${DEPLOY_BRANCH:-main}"
DEPLOY_REF="${DEPLOY_REF:-${DEPLOY_BRANCH}}"
AUTO_ROLLBACK="${AUTO_ROLLBACK:-true}"
APP_HOST="${APP_HOST:-127.0.0.1}"
APP_PORT="${APP_PORT:-8000}"
PUBLIC_URL="${PUBLIC_URL:-}"
RUN_FRONTEND_BUILD="${RUN_FRONTEND_BUILD:-false}"
STRICT_LOCAL_HEALTH="${STRICT_LOCAL_HEALTH:-true}"
ALLOW_DIRTY_DEPLOY="${ALLOW_DIRTY_DEPLOY:-false}"

STATE_DIR=""
PRE_DEPLOY_REV=""
TARGET_REV=""
ROLLBACK_ATTEMPTED="false"

log() {
  printf '[deploy] %s\n' "$*"
}

warn() {
  printf '[deploy][WARN] %s\n' "$*" >&2
}

error() {
  printf '[deploy][ERROR] %s\n' "$*" >&2
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

require_non_empty() {
  local name="$1"
  local value="${!name:-}"
  if [[ -z "${value}" ]]; then
    error "Required variable ${name} is empty."
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
  if req_file="$(detect_requirements_file)"; then
    log "Python dependency manifest detected: ${req_file}"
  else
    log "No Python dependency manifest found (requirements*.txt); skipping pip install."
    return 0
  fi

  require_command python3
  if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
    log "Creating virtualenv at ${VENV_DIR}"
    python3 -m venv "${VENV_DIR}"
  fi

  "${VENV_DIR}/bin/python" -m pip install --upgrade pip
  "${VENV_DIR}/bin/pip" install -r "${req_file}"
}

maybe_build_frontend() {
  local run_build
  run_build="$(lower "${RUN_FRONTEND_BUILD}")"
  if [[ "${run_build}" != "true" && "${run_build}" != "1" && "${run_build}" != "yes" ]]; then
    log "Frontend build disabled (RUN_FRONTEND_BUILD=${RUN_FRONTEND_BUILD})."
    return 0
  fi

  if [[ ! -f "${APP_DIR}/frontend/package.json" ]]; then
    warn "RUN_FRONTEND_BUILD enabled but frontend/package.json not found; skipping frontend build."
    return 0
  fi

  require_command npm
  log "Running frontend production build in ${APP_DIR}/frontend"
  if [[ -f "${APP_DIR}/frontend/package-lock.json" ]]; then
    npm ci --prefix "${APP_DIR}/frontend"
  else
    npm install --prefix "${APP_DIR}/frontend"
  fi
  npm run --prefix "${APP_DIR}/frontend" build
}

restart_service() {
  require_command systemctl
  log "Restarting systemd service: ${SERVICE_NAME}"
  systemctl restart "${SERVICE_NAME}"
  if ! systemctl is-active --quiet "${SERVICE_NAME}"; then
    error "Service ${SERVICE_NAME} failed to become active after restart."
    journalctl -u "${SERVICE_NAME}" -n 120 --no-pager || true
    exit 1
  fi
  log "Service ${SERVICE_NAME} is active."
}

verify_deploy() {
  if [[ -f "${APP_DIR}/deploy/verify-deploy.sh" ]]; then
    log "Running deploy verification script."
    APP_HOST="${APP_HOST}" \
    APP_PORT="${APP_PORT}" \
    SERVICE_NAME="${SERVICE_NAME}" \
    PUBLIC_URL="${PUBLIC_URL}" \
    STRICT_LOCAL_HEALTH="${STRICT_LOCAL_HEALTH}" \
    bash "${APP_DIR}/deploy/verify-deploy.sh"
    return 0
  fi

  warn "verify-deploy.sh not found; running basic local status probe."
  require_command curl
  curl --fail --silent --show-error --max-time 10 "http://${APP_HOST}:${APP_PORT}/api/status" >/dev/null
}

record_success_state() {
  mkdir -p "${STATE_DIR}"
  printf '%s\n' "${TARGET_REV}" > "${STATE_DIR}/last_successful_rev"
  printf '%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "${STATE_DIR}/last_successful_at_utc"
}

attempt_auto_rollback() {
  local rollback_flag
  rollback_flag="$(lower "${AUTO_ROLLBACK}")"
  if [[ "${rollback_flag}" != "true" && "${rollback_flag}" != "1" && "${rollback_flag}" != "yes" ]]; then
    warn "AUTO_ROLLBACK disabled; leaving failed deployment state in place."
    return 0
  fi

  if [[ -z "${PRE_DEPLOY_REV}" ]]; then
    warn "No PRE_DEPLOY_REV recorded; skipping auto-rollback."
    return 0
  fi

  if [[ "${ROLLBACK_ATTEMPTED}" == "true" ]]; then
    warn "Rollback already attempted for this run; skipping."
    return 0
  fi

  if [[ ! -f "${APP_DIR}/deploy/rollback.sh" ]]; then
    warn "rollback.sh not found; cannot auto-rollback."
    return 0
  fi

  ROLLBACK_ATTEMPTED="true"
  warn "AUTO_ROLLBACK enabled. Attempting rollback to ${PRE_DEPLOY_REV}."
  if APP_DIR="${APP_DIR}" \
     VENV_DIR="${VENV_DIR}" \
     SERVICE_NAME="${SERVICE_NAME}" \
     APP_HOST="${APP_HOST}" \
     APP_PORT="${APP_PORT}" \
     PUBLIC_URL="${PUBLIC_URL}" \
     STRICT_LOCAL_HEALTH="${STRICT_LOCAL_HEALTH}" \
     bash "${APP_DIR}/deploy/rollback.sh" "${PRE_DEPLOY_REV}"; then
    warn "Auto-rollback completed to ${PRE_DEPLOY_REV}."
  else
    error "Auto-rollback failed. Manual intervention required."
  fi
}

on_error() {
  local exit_code="$?"
  local line_no="${1:-unknown}"
  error "Deployment failed at line ${line_no} (exit code ${exit_code})."
  attempt_auto_rollback || true
  exit "${exit_code}"
}

trap 'on_error $LINENO' ERR

main() {
  AUTO_ROLLBACK="$(lower "${AUTO_ROLLBACK}")"
  RUN_FRONTEND_BUILD="$(lower "${RUN_FRONTEND_BUILD}")"
  STRICT_LOCAL_HEALTH="$(lower "${STRICT_LOCAL_HEALTH}")"
  ALLOW_DIRTY_DEPLOY="$(lower "${ALLOW_DIRTY_DEPLOY}")"

  require_non_empty APP_DIR
  require_non_empty SERVICE_NAME
  require_non_empty DEPLOY_BRANCH
  require_non_empty DEPLOY_REF
  require_non_empty APP_HOST
  require_non_empty APP_PORT
  if ! [[ "${APP_PORT}" =~ ^[0-9]+$ ]]; then
    error "APP_PORT must be numeric; got '${APP_PORT}'."
    exit 1
  fi

  [[ -d "${APP_DIR}" ]] || { error "APP_DIR does not exist: ${APP_DIR}"; exit 1; }
  cd "${APP_DIR}"
  [[ -d ".git" ]] || { error "APP_DIR is not a git repository: ${APP_DIR}"; exit 1; }

  require_command git
  require_command bash
  require_command curl

  STATE_DIR="${APP_DIR}/.deploy"
  mkdir -p "${STATE_DIR}"

  git config --global --add safe.directory "${APP_DIR}" >/dev/null 2>&1 || true

  if [[ "${ALLOW_DIRTY_DEPLOY}" != "true" && -n "$(git status --porcelain)" ]]; then
    error "Git working tree is not clean in ${APP_DIR}. Commit/stash changes or set ALLOW_DIRTY_DEPLOY=true."
    git status --short || true
    exit 1
  fi

  local current_rev target_short
  current_rev="$(git rev-parse HEAD)"
  PRE_DEPLOY_REV="${current_rev}"
  printf '%s\n' "${PRE_DEPLOY_REV}" > "${STATE_DIR}/pre_deploy_rev"

  log "Deploy context: app=${APP_NAME} user=${APP_USER} service=${SERVICE_NAME} app_dir=${APP_DIR}"
  log "Deploy target requested: DEPLOY_REF=${DEPLOY_REF} (fallback branch=${DEPLOY_BRANCH})"
  log "Current revision: ${current_rev}"

  git fetch --prune --tags origin

  if ! TARGET_REV="$(resolve_git_ref "${DEPLOY_REF}")"; then
    if ! TARGET_REV="$(resolve_git_ref "${DEPLOY_BRANCH}")"; then
      error "Could not resolve DEPLOY_REF='${DEPLOY_REF}' or DEPLOY_BRANCH='${DEPLOY_BRANCH}' to a commit."
      exit 1
    fi
    warn "Falling back to DEPLOY_BRANCH '${DEPLOY_BRANCH}' because DEPLOY_REF '${DEPLOY_REF}' was not resolvable."
  fi
  target_short="$(git rev-parse --short "${TARGET_REV}")"
  log "Resolved target revision: ${TARGET_REV} (${target_short})"

  if [[ "${current_rev}" != "${TARGET_REV}" ]]; then
    log "Checking out target revision."
    git checkout --force "${TARGET_REV}"
    git reset --hard "${TARGET_REV}"
  else
    log "Repository already at target revision."
  fi

  prepare_python_runtime
  maybe_build_frontend
  restart_service
  verify_deploy
  record_success_state

  log "Deployment succeeded at revision ${TARGET_REV}."
}

main "$@"
