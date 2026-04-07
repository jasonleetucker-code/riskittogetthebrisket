#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_APP_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

APP_NAME="${APP_NAME:-riskittogetthebrisket}"
APP_DIR="${APP_DIR:-${DEFAULT_APP_DIR}}"
APP_USER="${APP_USER:-$(id -un)}"
APP_SLUG="${APP_SLUG:-$(basename "${APP_DIR}")}"
VENV_DIR="${VENV_DIR:-/home/${APP_USER}/.venvs/${APP_SLUG}}"
SERVICE_NAME="${SERVICE_NAME:-dynasty}"
APP_HOST="${APP_HOST:-127.0.0.1}"
APP_PORT="${APP_PORT:-8000}"
DEPLOY_STATE_DIR="${DEPLOY_STATE_DIR:-/home/${APP_USER}/.deploy-state}"
LAST_SUCCESSFUL_DEPLOY_COMMIT_FILE="${LAST_SUCCESSFUL_DEPLOY_COMMIT_FILE:-${DEPLOY_STATE_DIR}/${APP_SLUG}.last_successful_deploy_commit}"
PLAYWRIGHT_BROWSER="${PLAYWRIGHT_BROWSER:-chromium}"
INSTALL_PLAYWRIGHT_BROWSER="${INSTALL_PLAYWRIGHT_BROWSER:-true}"
INSTALL_PLAYWRIGHT_DEPS="${INSTALL_PLAYWRIGHT_DEPS:-false}"
FORCE_SERVICE_INSTALL="${FORCE_SERVICE_INSTALL:-false}"
STRICT_LOCAL_HEALTH="${STRICT_LOCAL_HEALTH:-false}"
RUN_VERIFY="${RUN_VERIFY:-true}"

SYSTEMCTL_BIN=""
JOURNALCTL_BIN=""
INSTALL_BIN=""

log() {
  printf '[bootstrap] %s\n' "$*"
}

warn() {
  printf '[bootstrap][WARN] %s\n' "$*" >&2
}

error() {
  printf '[bootstrap][ERROR] %s\n' "$*" >&2
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

resolve_required_sudo_binaries() {
  SYSTEMCTL_BIN="$(resolve_sudo_nopasswd_binary "systemctl" /bin/systemctl /usr/bin/systemctl)"
  JOURNALCTL_BIN="$(resolve_sudo_nopasswd_binary "journalctl" /bin/journalctl /usr/bin/journalctl)"
  INSTALL_BIN="$(resolve_sudo_nopasswd_binary "install" /usr/bin/install /bin/install)"
}

canonical_requirements_file() {
  printf '%s\n' "requirements.txt"
}

record_state() {
  local revision="$1"
  mkdir -p "${DEPLOY_STATE_DIR}"
  printf '%s\n' "${revision}" > "${DEPLOY_STATE_DIR}/last_successful_rev"
  printf '%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "${DEPLOY_STATE_DIR}/last_successful_at_utc"
  if [[ -n "${LAST_SUCCESSFUL_DEPLOY_COMMIT_FILE}" ]]; then
    mkdir -p "$(dirname "${LAST_SUCCESSFUL_DEPLOY_COMMIT_FILE}")"
    printf '%s\n' "${revision}" > "${LAST_SUCCESSFUL_DEPLOY_COMMIT_FILE}"
  fi
}

main() {
  INSTALL_PLAYWRIGHT_BROWSER="$(lower "${INSTALL_PLAYWRIGHT_BROWSER}")"
  INSTALL_PLAYWRIGHT_DEPS="$(lower "${INSTALL_PLAYWRIGHT_DEPS}")"
  FORCE_SERVICE_INSTALL="$(lower "${FORCE_SERVICE_INSTALL}")"
  STRICT_LOCAL_HEALTH="$(lower "${STRICT_LOCAL_HEALTH}")"
  RUN_VERIFY="$(lower "${RUN_VERIFY}")"

  require_non_empty APP_DIR
  require_non_empty APP_USER
  require_non_empty VENV_DIR
  require_non_empty SERVICE_NAME
  require_non_empty DEPLOY_STATE_DIR
  require_non_empty APP_HOST
  require_non_empty APP_PORT
  if ! [[ "${APP_PORT}" =~ ^[0-9]+$ ]]; then
    error "APP_PORT must be numeric; got '${APP_PORT}'."
    exit 1
  fi

  [[ -d "${APP_DIR}" ]] || { error "APP_DIR does not exist: ${APP_DIR}"; exit 1; }
  [[ -d "${APP_DIR}/.git" ]] || { error "APP_DIR is not a git repo: ${APP_DIR}"; exit 1; }
  cd "${APP_DIR}"

  require_command bash
  require_command git
  require_command python3
  require_command curl
  require_command sudo

  resolve_required_sudo_binaries
  log "Validated command-scoped NOPASSWD sudo for systemctl/journalctl/install."

  local req_file
  req_file="$(canonical_requirements_file)"
  [[ -f "${req_file}" ]] || { error "Missing canonical Python manifest: ${APP_DIR}/${req_file}"; exit 1; }

  if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
    log "Creating virtualenv at ${VENV_DIR}"
    python3 -m venv "${VENV_DIR}"
  fi

  log "Installing Python dependencies from ${req_file}"
  "${VENV_DIR}/bin/python" -m pip install --upgrade pip
  "${VENV_DIR}/bin/pip" install -r "${req_file}"

  if [[ "${INSTALL_PLAYWRIGHT_BROWSER}" == "true" || "${INSTALL_PLAYWRIGHT_BROWSER}" == "1" || "${INSTALL_PLAYWRIGHT_BROWSER}" == "yes" ]]; then
    log "Installing Playwright browser runtime (${PLAYWRIGHT_BROWSER})"
    "${VENV_DIR}/bin/python" -m playwright install "${PLAYWRIGHT_BROWSER}"
  else
    warn "Skipping Playwright browser install (INSTALL_PLAYWRIGHT_BROWSER=${INSTALL_PLAYWRIGHT_BROWSER})."
  fi

  if [[ "${INSTALL_PLAYWRIGHT_DEPS}" == "true" || "${INSTALL_PLAYWRIGHT_DEPS}" == "1" || "${INSTALL_PLAYWRIGHT_DEPS}" == "yes" ]]; then
    warn "Installing Playwright OS dependencies with interactive sudo."
    sudo "${VENV_DIR}/bin/python" -m playwright install-deps "${PLAYWRIGHT_BROWSER}"
  fi

  # Build frontend (Next.js) so dynasty-frontend service can start
  if [[ -f "${APP_DIR}/frontend/package.json" ]]; then
    require_command npm
    log "Building frontend in ${APP_DIR}/frontend"
    if [[ -f "${APP_DIR}/frontend/package-lock.json" ]]; then
      npm ci --prefix "${APP_DIR}/frontend"
    else
      npm install --prefix "${APP_DIR}/frontend"
    fi
    npm run --prefix "${APP_DIR}/frontend" build
  else
    warn "frontend/package.json not found; skipping frontend build."
  fi

  local installer_script
  installer_script="${APP_DIR}/deploy/install-systemd-service.sh"
  [[ -f "${installer_script}" ]] || { error "Missing systemd installer script: ${installer_script}"; exit 1; }
  APP_DIR="${APP_DIR}" \
  APP_USER="${APP_USER}" \
  VENV_DIR="${VENV_DIR}" \
  SERVICE_NAME="${SERVICE_NAME}" \
  FORCE_SERVICE_INSTALL="${FORCE_SERVICE_INSTALL}" \
  bash "${installer_script}"

  log "Restarting service ${SERVICE_NAME}"
  sudo -n "${SYSTEMCTL_BIN}" restart "${SERVICE_NAME}"
  if ! sudo -n "${SYSTEMCTL_BIN}" is-active --quiet "${SERVICE_NAME}"; then
    error "Service ${SERVICE_NAME} did not become active after restart."
    sudo -n "${JOURNALCTL_BIN}" -u "${SERVICE_NAME}" -n 160 --no-pager || true
    exit 1
  fi

  if [[ "${RUN_VERIFY}" == "true" || "${RUN_VERIFY}" == "1" || "${RUN_VERIFY}" == "yes" ]]; then
    if [[ -f "${APP_DIR}/deploy/verify-deploy.sh" ]]; then
      APP_HOST="${APP_HOST}" \
      APP_PORT="${APP_PORT}" \
      SERVICE_NAME="${SERVICE_NAME}" \
      STRICT_LOCAL_HEALTH="${STRICT_LOCAL_HEALTH}" \
      bash "${APP_DIR}/deploy/verify-deploy.sh"
    else
      warn "verify-deploy.sh missing; skipping verification."
    fi
  fi

  local current_rev
  current_rev="$(git rev-parse HEAD)"
  record_state "${current_rev}"

  log "Bootstrap complete at revision ${current_rev}."
  log "State directory: ${DEPLOY_STATE_DIR}"
  log "Last successful file: ${LAST_SUCCESSFUL_DEPLOY_COMMIT_FILE}"
}

main "$@"
