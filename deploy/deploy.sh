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
DEPLOY_STATE_DIR="${DEPLOY_STATE_DIR:-${APP_DIR}/.deploy}"
LAST_SUCCESSFUL_DEPLOY_COMMIT_FILE="${LAST_SUCCESSFUL_DEPLOY_COMMIT_FILE:-${DEPLOY_STATE_DIR}/${APP_NAME}.last_successful_deploy_commit}"
AUTO_ROLLBACK="${AUTO_ROLLBACK:-true}"
APP_HOST="${APP_HOST:-127.0.0.1}"
APP_PORT="${APP_PORT:-8000}"
PUBLIC_URL="${PUBLIC_URL:-}"
RUN_FRONTEND_BUILD="${RUN_FRONTEND_BUILD:-true}"
STRICT_LOCAL_HEALTH="${STRICT_LOCAL_HEALTH:-true}"
ALLOW_DIRTY_DEPLOY="${ALLOW_DIRTY_DEPLOY:-false}"

STATE_DIR=""
PRE_DEPLOY_REV=""
TARGET_REV=""
ROLLBACK_ATTEMPTED="false"
SYSTEMCTL_BIN=""
JOURNALCTL_BIN=""
INSTALL_BIN=""
CHOWN_BIN=""

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
  JOURNALCTL_BIN="$(resolve_sudo_nopasswd_binary "journalctl" /bin/journalctl /usr/bin/journalctl)"
  INSTALL_BIN="$(resolve_sudo_nopasswd_binary "install" /usr/bin/install /bin/install)"
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
  if [[ -z "${CHOWN_BIN}" ]]; then
    CHOWN_BIN="$(resolve_sudo_nopasswd_binary "chown" /bin/chown /usr/bin/chown)"
  fi
  sudo -n "${CHOWN_BIN}" -R "${APP_USER}:${APP_USER}" "${VENV_DIR}"

  if [[ ! -w "${site_packages}" ]]; then
    error "site-packages remains non-writable after ownership repair: ${site_packages}"
    exit 1
  fi
}

prepare_python_runtime() {
  local req_file
  req_file="$(canonical_requirements_file)"
  if [[ ! -f "${req_file}" ]]; then
    error "Missing canonical Python dependency manifest: ${APP_DIR}/${req_file}"
    exit 1
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

  if ! command -v npm >/dev/null 2>&1; then
    warn "npm not found; skipping frontend build. Install Node.js/npm to enable frontend builds."
    return 0
  fi
  log "Running frontend production build in ${APP_DIR}/frontend"
  if [[ -f "${APP_DIR}/frontend/package-lock.json" ]]; then
    npm ci --prefix "${APP_DIR}/frontend"
  else
    npm install --prefix "${APP_DIR}/frontend"
  fi
  npm run --prefix "${APP_DIR}/frontend" build
}

ensure_systemd_service() {
  require_command systemctl
  if sudo -n "${SYSTEMCTL_BIN}" cat "${SERVICE_NAME}" >/dev/null 2>&1; then
    return 0
  fi

  local installer_script
  installer_script="${APP_DIR}/deploy/install-systemd-service.sh"
  warn "Systemd service ${SERVICE_NAME} not found. Attempting bootstrap install."
  if [[ ! -f "${installer_script}" ]]; then
    error "Missing bootstrap installer script: ${installer_script}"
    exit 1
  fi

  APP_DIR="${APP_DIR}" \
  APP_USER="${APP_USER}" \
  VENV_DIR="${VENV_DIR}" \
  SERVICE_NAME="${SERVICE_NAME}" \
  bash "${installer_script}"

  if ! sudo -n "${SYSTEMCTL_BIN}" cat "${SERVICE_NAME}" >/dev/null 2>&1; then
    error "Systemd service ${SERVICE_NAME} is still unavailable after bootstrap install."
    exit 1
  fi
}

restart_service() {
  require_command systemctl
  # Restart frontend service first (Next.js) since backend depends on it
  local frontend_name="${SERVICE_NAME}-frontend"
  if sudo -n "${SYSTEMCTL_BIN}" cat "${frontend_name}" >/dev/null 2>&1; then
    log "Restarting frontend service: ${frontend_name}"
    sudo -n "${SYSTEMCTL_BIN}" restart "${frontend_name}"
    if ! sudo -n "${SYSTEMCTL_BIN}" is-active --quiet "${frontend_name}"; then
      warn "Frontend service ${frontend_name} failed to become active after restart."
      sudo -n "${JOURNALCTL_BIN}" -u "${frontend_name}" -n 60 --no-pager || true
    else
      log "Frontend service ${frontend_name} is active."
    fi
  fi
  log "Restarting systemd service: ${SERVICE_NAME}"
  sudo -n "${SYSTEMCTL_BIN}" restart "${SERVICE_NAME}"
  if ! sudo -n "${SYSTEMCTL_BIN}" is-active --quiet "${SERVICE_NAME}"; then
    error "Service ${SERVICE_NAME} failed to become active after restart."
    sudo -n "${JOURNALCTL_BIN}" -u "${SERVICE_NAME}" -n 120 --no-pager || true
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
  if [[ -n "${LAST_SUCCESSFUL_DEPLOY_COMMIT_FILE}" ]]; then
    mkdir -p "$(dirname "${LAST_SUCCESSFUL_DEPLOY_COMMIT_FILE}")"
    printf '%s\n' "${TARGET_REV}" > "${LAST_SUCCESSFUL_DEPLOY_COMMIT_FILE}"
  fi
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
     APP_NAME="${APP_NAME}" \
     VENV_DIR="${VENV_DIR}" \
     DEPLOY_STATE_DIR="${DEPLOY_STATE_DIR}" \
     LAST_SUCCESSFUL_DEPLOY_COMMIT_FILE="${LAST_SUCCESSFUL_DEPLOY_COMMIT_FILE}" \
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
  require_non_empty DEPLOY_STATE_DIR
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
  require_command sudo
  resolve_and_validate_sudo_binaries

  STATE_DIR="${DEPLOY_STATE_DIR}"
  mkdir -p "${STATE_DIR}"

  git config --global --add safe.directory "${APP_DIR}" >/dev/null 2>&1 || true

  # ── Handle tracked file drift ──────────────────────────────────────────
  # Production servers should never have tracked file modifications.  When
  # they do (operator edits, Claude Code sessions, script side-effects) we
  # auto-stash instead of hard-failing, so deploys stay unblocked while the
  # diff is preserved for post-mortem.
  local tracked_changes
  tracked_changes="$(git status --porcelain --untracked-files=no)"
  if [[ -n "${tracked_changes}" ]]; then
    if [[ "${ALLOW_DIRTY_DEPLOY}" == "true" ]]; then
      warn "Tracked changes detected but ALLOW_DIRTY_DEPLOY=true — proceeding without stash."
    else
      warn "Tracked git changes detected in ${APP_DIR}:"
      git diff --stat || true
      local stash_name="deploy-auto-stash-$(date -u +%Y%m%dT%H%M%SZ)"
      log "Auto-stashing tracked changes as '${stash_name}' (inspect later with: git stash show -p 'stash@{0}')."
      git stash push -m "${stash_name}" --include-untracked=false
    fi
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
  ensure_systemd_service
  restart_service
  verify_deploy
  record_success_state

  log "Deployment succeeded at revision ${TARGET_REV}."
}

main "$@"
