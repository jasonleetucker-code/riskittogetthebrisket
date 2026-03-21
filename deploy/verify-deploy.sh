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
STRICT_LEAGUE_SHELL_READINESS="${STRICT_LEAGUE_SHELL_READINESS:-true}"

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

is_truthy() {
  local value
  value="$(lower "${1:-}")"
  [[ "${value}" == "true" || "${value}" == "1" || "${value}" == "yes" || "${value}" == "on" ]]
}

require_command() {
  local cmd="$1"
  command -v "${cmd}" >/dev/null 2>&1 || {
    error "Required command not found: ${cmd}"
    exit 1
  }
}

check_league_shell_source_control() {
  local strict_flag="$1"
  local script_dir repo_root
  local required_assets=(
    "Static/league/index.html"
    "Static/league/league.css"
    "Static/league/league.js"
  )

  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  repo_root="$(cd "${script_dir}/.." && pwd)"

  if ! command -v git >/dev/null 2>&1; then
    if is_truthy "${strict_flag}"; then
      error "git is required to verify League shell source-control readiness."
      return 1
    fi
    warn "git unavailable; skipping League shell source-control readiness check."
    return 0
  fi

  if ! git -C "${repo_root}" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    if is_truthy "${strict_flag}"; then
      error "Cannot verify League shell source-control readiness outside a git worktree (${repo_root})."
      return 1
    fi
    warn "Skipping League shell source-control readiness check outside a git worktree (${repo_root})."
    return 0
  fi

  local failures=0
  local rel
  for rel in "${required_assets[@]}"; do
    if [[ ! -f "${repo_root}/${rel}" ]]; then
      error "League shell artifact missing from repo tree: ${rel}"
      failures=1
      continue
    fi
    if ! git -C "${repo_root}" ls-files --error-unmatch "${rel}" >/dev/null 2>&1; then
      error "League shell artifact is not source-controlled: ${rel}"
      failures=1
    fi
  done

  if (( failures > 0 )); then
    if is_truthy "${strict_flag}"; then
      return 1
    fi
    warn "League shell source-control readiness check failed, continuing because strict mode is disabled."
    return 0
  fi

  log "League shell source-control readiness OK (tracked: Static/league/index.html, league.css, league.js)."
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
  STRICT_LEAGUE_SHELL_READINESS="$(lower "${STRICT_LEAGUE_SHELL_READINESS}")"

  require_command curl

  if ! [[ "${APP_PORT}" =~ ^[0-9]+$ ]]; then
    error "APP_PORT must be numeric; got '${APP_PORT}'."
    exit 1
  fi

  check_league_shell_source_control "${STRICT_LEAGUE_SHELL_READINESS}"

  local status_url health_url route_authority_url status_body health_body route_body public_body
  status_url="http://${APP_HOST}:${APP_PORT}/api/status"
  health_url="http://${APP_HOST}:${APP_PORT}/api/health"
  route_authority_url="http://${APP_HOST}:${APP_PORT}/api/runtime/route-authority"
  status_body="$(mktemp)"
  health_body="$(mktemp)"
  route_body="$(mktemp)"
  public_body="$(mktemp)"
  trap 'rm -f "${status_body}" "${health_body}" "${route_body}" "${public_body}"' EXIT

  if [[ -n "${SERVICE_NAME}" ]] && command -v systemctl >/dev/null 2>&1; then
    if ! sudo systemctl is-active --quiet "${SERVICE_NAME}"; then
      error "Systemd service is not active: ${SERVICE_NAME}"
      sudo journalctl -u "${SERVICE_NAME}" -n 120 --no-pager || true
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

  local route_code
  route_code="$(curl --silent --show-error --output "${route_body}" --write-out '%{http_code}' --max-time "${VERIFY_CURL_TIMEOUT}" "${route_authority_url}" || true)"
  if [[ "${route_code}" != "200" ]]; then
    if [[ "${STRICT_LEAGUE_SHELL_READINESS}" == "true" || "${STRICT_LEAGUE_SHELL_READINESS}" == "1" || "${STRICT_LEAGUE_SHELL_READINESS}" == "yes" ]]; then
      error "Route authority endpoint check failed with HTTP ${route_code:-curl_error}: ${route_authority_url}"
      if [[ -s "${route_body}" ]]; then
        sed -n '1,120p' "${route_body}" >&2 || true
      fi
      exit 1
    fi
    warn "Route authority endpoint returned HTTP ${route_code:-curl_error} (STRICT_LEAGUE_SHELL_READINESS=${STRICT_LEAGUE_SHELL_READINESS})."
  elif command -v python3 >/dev/null 2>&1; then
    local readiness_result readiness_ok readiness_authority readiness_entry readiness_css readiness_js
    readiness_result="$(
      python3 - "${route_body}" <<'PY'
import json
import sys

payload = {}
try:
    with open(sys.argv[1], "r", encoding="utf-8") as handle:
        payload = json.load(handle)
except Exception:
    print("0|unknown|0|0|0")
    raise SystemExit(0)

shell = payload.get("deployReadiness", {}).get("leagueShell", {})
ok = 1 if bool(shell.get("ok")) else 0
authority = str(shell.get("currentRuntimeAuthority") or "unknown")
entry = 1 if bool(shell.get("entryExists")) else 0
css = 1 if bool(shell.get("cssExists")) else 0
js = 1 if bool(shell.get("jsExists")) else 0
print(f"{ok}|{authority}|{entry}|{css}|{js}")
PY
    )"
    IFS='|' read -r readiness_ok readiness_authority readiness_entry readiness_css readiness_js <<< "${readiness_result}"
    if [[ "${readiness_ok}" == "1" ]]; then
      log "League shell readiness OK (authority=${readiness_authority}, entry=${readiness_entry}, css=${readiness_css}, js=${readiness_js})."
    elif [[ "${STRICT_LEAGUE_SHELL_READINESS}" == "true" || "${STRICT_LEAGUE_SHELL_READINESS}" == "1" || "${STRICT_LEAGUE_SHELL_READINESS}" == "yes" ]]; then
      error "League shell readiness failed (authority=${readiness_authority}, entry=${readiness_entry}, css=${readiness_css}, js=${readiness_js})."
      sed -n '1,160p' "${route_body}" >&2 || true
      exit 1
    else
      warn "League shell readiness not fully ready (authority=${readiness_authority}, entry=${readiness_entry}, css=${readiness_css}, js=${readiness_js})."
    fi
  else
    warn "python3 not available; skipping strict /api/runtime/route-authority league readiness parse."
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
