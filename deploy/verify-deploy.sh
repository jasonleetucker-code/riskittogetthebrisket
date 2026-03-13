#!/usr/bin/env bash
set -Eeuo pipefail

APP_HOST="${APP_HOST:-127.0.0.1}"
APP_PORT="${APP_PORT:-8000}"
SERVICE_NAME="${SERVICE_NAME:-dynasty}"
PUBLIC_URL="${PUBLIC_URL:-}"
VERIFY_MAX_ATTEMPTS="${VERIFY_MAX_ATTEMPTS:-20}"
VERIFY_SLEEP_SECONDS="${VERIFY_SLEEP_SECONDS:-2}"
VERIFY_CURL_TIMEOUT="${VERIFY_CURL_TIMEOUT:-8}"
STRICT_LOCAL_HEALTH="${STRICT_LOCAL_HEALTH:-true}"
STRICT_PUBLIC_HEALTH="${STRICT_PUBLIC_HEALTH:-false}"

log() {
  printf '[verify] %s\n' "$*"
}

warn() {
  printf '[verify][WARN] %s\n' "$*" >&2
}

error() {
  printf '[verify][ERROR] %s\n' "$*" >&2
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

probe_with_retries() {
  local url="$1"
  local attempts="$2"
  local sleep_seconds="$3"
  local timeout_seconds="$4"
  local body_file="$5"
  local code=""
  local n=1

  while (( n <= attempts )); do
    code="$(curl --silent --show-error --output "${body_file}" --write-out '%{http_code}' --max-time "${timeout_seconds}" "${url}" || true)"
    if [[ "${code}" == "200" ]]; then
      return 0
    fi
    log "Attempt ${n}/${attempts} for ${url} returned HTTP ${code:-curl_error}; retrying in ${sleep_seconds}s."
    sleep "${sleep_seconds}"
    n=$((n + 1))
  done

  error "Endpoint did not return HTTP 200 after ${attempts} attempts: ${url}"
  if [[ -s "${body_file}" ]]; then
    warn "Last response body from ${url}:"
    sed -n '1,120p' "${body_file}" >&2 || true
  fi
  return 1
}

main() {
  STRICT_LOCAL_HEALTH="$(lower "${STRICT_LOCAL_HEALTH}")"
  STRICT_PUBLIC_HEALTH="$(lower "${STRICT_PUBLIC_HEALTH}")"

  require_command curl

  if ! [[ "${APP_PORT}" =~ ^[0-9]+$ ]]; then
    error "APP_PORT must be numeric; got '${APP_PORT}'."
    exit 1
  fi

  local status_url health_url status_body health_body public_body systemctl_bin journalctl_bin
  status_url="http://${APP_HOST}:${APP_PORT}/api/status"
  health_url="http://${APP_HOST}:${APP_PORT}/api/health"
  status_body="$(mktemp)"
  health_body="$(mktemp)"
  public_body="$(mktemp)"
  trap 'rm -f "${status_body:-}" "${health_body:-}" "${public_body:-}"' EXIT

  if [[ -n "${SERVICE_NAME}" ]] && command -v systemctl >/dev/null 2>&1; then
    require_command sudo
    systemctl_bin="$(resolve_sudo_nopasswd_binary "systemctl" /bin/systemctl /usr/bin/systemctl)"
    journalctl_bin="$(resolve_sudo_nopasswd_binary "journalctl" /bin/journalctl /usr/bin/journalctl)"
    if ! sudo -n "${systemctl_bin}" is-active --quiet "${SERVICE_NAME}"; then
      error "Systemd service is not active: ${SERVICE_NAME}"
      sudo -n "${journalctl_bin}" -u "${SERVICE_NAME}" -n 120 --no-pager || true
      exit 1
    fi
    log "Service is active: ${SERVICE_NAME}"
  fi

  probe_with_retries "${status_url}" "${VERIFY_MAX_ATTEMPTS}" "${VERIFY_SLEEP_SECONDS}" "${VERIFY_CURL_TIMEOUT}" "${status_body}"
  log "Status endpoint healthy: ${status_url}"

  local health_code
  health_code="$(curl --silent --show-error --output "${health_body}" --write-out '%{http_code}' --max-time "${VERIFY_CURL_TIMEOUT}" "${health_url}" || true)"
  if [[ "${health_code}" == "200" ]]; then
    log "Health endpoint healthy: ${health_url}"
  elif [[ "${STRICT_LOCAL_HEALTH}" == "true" || "${STRICT_LOCAL_HEALTH}" == "1" || "${STRICT_LOCAL_HEALTH}" == "yes" ]]; then
    error "Health endpoint check failed with HTTP ${health_code:-curl_error}: ${health_url}"
    if [[ -s "${health_body}" ]]; then
      sed -n '1,120p' "${health_body}" >&2 || true
    fi
    exit 1
  else
    warn "Health endpoint returned HTTP ${health_code:-curl_error} (STRICT_LOCAL_HEALTH=${STRICT_LOCAL_HEALTH})."
  fi

  if [[ -n "${PUBLIC_URL}" ]]; then
    local public_code
    public_code="$(curl --silent --show-error --output "${public_body}" --write-out '%{http_code}' --max-time "${VERIFY_CURL_TIMEOUT}" "${PUBLIC_URL}" || true)"
    if [[ "${public_code}" == "200" ]]; then
      log "Public URL reachable: ${PUBLIC_URL}"
    elif [[ "${STRICT_PUBLIC_HEALTH}" == "true" || "${STRICT_PUBLIC_HEALTH}" == "1" || "${STRICT_PUBLIC_HEALTH}" == "yes" ]]; then
      error "Public URL check failed with HTTP ${public_code:-curl_error}: ${PUBLIC_URL}"
      if [[ -s "${public_body}" ]]; then
        sed -n '1,120p' "${public_body}" >&2 || true
      fi
      exit 1
    else
      warn "Public URL check returned HTTP ${public_code:-curl_error} (STRICT_PUBLIC_HEALTH=${STRICT_PUBLIC_HEALTH})."
    fi
  fi

  log "Deploy verification checks passed."
}

main "$@"
