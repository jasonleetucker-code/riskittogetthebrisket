#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_APP_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

APP_HOST="${APP_HOST:-127.0.0.1}"
APP_PORT="${APP_PORT:-8000}"
APP_DIR="${APP_DIR:-${DEFAULT_APP_DIR}}"
FRONTEND_HOST="${FRONTEND_HOST:-127.0.0.1}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"
FRONTEND_BUILD_DIR="${FRONTEND_BUILD_DIR:-${APP_DIR}/frontend/.next}"
SERVICE_NAME="${SERVICE_NAME:-dynasty}"
PUBLIC_URL="${PUBLIC_URL:-}"
VERIFY_MAX_ATTEMPTS="${VERIFY_MAX_ATTEMPTS:-20}"
VERIFY_SLEEP_SECONDS="${VERIFY_SLEEP_SECONDS:-2}"
VERIFY_CURL_TIMEOUT="${VERIFY_CURL_TIMEOUT:-8}"
STRICT_LOCAL_HEALTH="${STRICT_LOCAL_HEALTH:-true}"
STRICT_PUBLIC_HEALTH="${STRICT_PUBLIC_HEALTH:-false}"
STRICT_FRONTEND_ASSETS="${STRICT_FRONTEND_ASSETS:-true}"

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

dump_service_diagnostics() {
  local systemctl_bin="${1:-}"
  local journalctl_bin="${2:-}"
  if [[ -z "${SERVICE_NAME}" || -z "${systemctl_bin}" || -z "${journalctl_bin}" ]]; then
    return 0
  fi
  warn "Collecting service diagnostics for ${SERVICE_NAME}"
  sudo -n "${systemctl_bin}" status "${SERVICE_NAME}" --no-pager || true
  sudo -n "${journalctl_bin}" -u "${SERVICE_NAME}" -n 160 --no-pager || true
}

# Probe EVERY static chunk referenced by both the live build
# manifests AND the prerendered SSG HTML output in .next/server/app/
# and .next/server/pages/.  Each URL must return HTTP 200 from the
# running Next.js process on the loopback interface.
#
# The prerendered HTML walk is what catches the ChunkLoadError failure
# mode: Next.js bakes <script src> tags for async chunks (like the
# 448-*.js outage chunk) that do NOT appear in build-manifest.json.
# A manifest-only probe silently missed the exact failure mode that
# shipped the production outage.
probe_frontend_next_assets() {
  local build_dir="$1"
  if [[ ! -d "${build_dir}" ]]; then
    error "Frontend build dir missing: ${build_dir}"
    return 1
  fi

  local probe_list
  probe_list="$(python3 - "${build_dir}" <<'PY'
import json
import os
import re
import sys

live_dir = sys.argv[1]
manifests = [
    "build-manifest.json",
    "app-build-manifest.json",
    "react-loadable-manifest.json",
]

assets = set()


def walk(obj):
    if isinstance(obj, str):
        if obj.startswith("static/") and (obj.endswith(".js") or obj.endswith(".css")):
            assets.add(obj)
    elif isinstance(obj, list):
        for item in obj:
            walk(item)
    elif isinstance(obj, dict):
        for value in obj.values():
            walk(value)


for name in manifests:
    path = os.path.join(live_dir, name)
    if not os.path.exists(path):
        continue
    try:
        with open(path) as fh:
            walk(json.load(fh))
    except Exception:
        pass

html_asset_re = re.compile(r"/_next/(static/[^\"\s<>?]+\.(?:js|css))")
for root in ("server/app", "server/pages"):
    root_path = os.path.join(live_dir, root)
    if not os.path.isdir(root_path):
        continue
    for dirpath, _dirnames, filenames in os.walk(root_path):
        for fname in filenames:
            if not fname.endswith(".html"):
                continue
            try:
                with open(os.path.join(dirpath, fname), encoding="utf-8") as fh:
                    for match in html_asset_re.finditer(fh.read()):
                        assets.add(match.group(1))
            except Exception:
                pass

for asset in sorted(assets):
    print(asset)
PY
  )"

  if [[ -z "${probe_list}" ]]; then
    warn "Manifests and prerendered HTML list no static chunks; skipping _next probe."
    return 0
  fi

  local asset url code
  local total=0
  local ok=0
  while IFS= read -r asset; do
    [[ -z "${asset}" ]] && continue
    total=$((total + 1))
    url="http://${FRONTEND_HOST}:${FRONTEND_PORT}/_next/${asset}"
    # --globoff: literal [ and ] in Next.js dynamic-route chunk names
    # must not be interpreted as curl glob/range syntax.
    code="$(curl --silent --show-error --globoff --output /dev/null --write-out '%{http_code}' --max-time "${VERIFY_CURL_TIMEOUT}" "${url}" || echo 000)"
    if [[ "${code}" != "200" ]]; then
      error "Frontend _next asset probe failed: ${url} -> HTTP ${code}"
      return 1
    fi
    ok=$((ok + 1))
  done <<< "${probe_list}"
  log "Frontend _next asset probe OK: ${ok}/${total} chunks served by live Next.js process."
  return 0
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
    code="$(curl --silent --show-error --globoff --output "${body_file}" --write-out '%{http_code}' --max-time "${timeout_seconds}" "${url}" || true)"
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
    # Check frontend service (Next.js)
    local frontend_name="${SERVICE_NAME}-frontend"
    if sudo -n "${systemctl_bin}" cat "${frontend_name}" >/dev/null 2>&1; then
      if ! sudo -n "${systemctl_bin}" is-active --quiet "${frontend_name}"; then
        if [[ "${STRICT_FRONTEND_ASSETS}" == "true" || "${STRICT_FRONTEND_ASSETS}" == "1" || "${STRICT_FRONTEND_ASSETS}" == "yes" ]]; then
          error "Frontend service is not active: ${frontend_name}"
          sudo -n "${journalctl_bin}" -u "${frontend_name}" -n 120 --no-pager || true
          exit 1
        fi
        warn "Frontend service is not active: ${frontend_name}"
        sudo -n "${journalctl_bin}" -u "${frontend_name}" -n 60 --no-pager || true
      else
        log "Frontend service is active: ${frontend_name}"
      fi
    fi
  fi

  # Verify the running Next.js server actually serves the /_next/static
  # chunk hashes referenced by the live build-manifest.json on disk.
  # This is the guardrail for the ChunkLoadError failure mode: if HTML
  # and assets diverge, the deploy fails here instead of silently
  # succeeding with a broken UI.
  if [[ -d "${FRONTEND_BUILD_DIR}" ]]; then
    if ! probe_frontend_next_assets "${FRONTEND_BUILD_DIR}"; then
      if [[ "${STRICT_FRONTEND_ASSETS}" == "true" || "${STRICT_FRONTEND_ASSETS}" == "1" || "${STRICT_FRONTEND_ASSETS}" == "yes" ]]; then
        dump_service_diagnostics "${systemctl_bin:-}" "${journalctl_bin:-}"
        exit 1
      else
        warn "Frontend _next asset probe failed (STRICT_FRONTEND_ASSETS=${STRICT_FRONTEND_ASSETS}); continuing."
      fi
    fi
  else
    warn "Frontend build dir not found at ${FRONTEND_BUILD_DIR}; skipping _next asset probe."
  fi

  if ! probe_with_retries "${status_url}" "${VERIFY_MAX_ATTEMPTS}" "${VERIFY_SLEEP_SECONDS}" "${VERIFY_CURL_TIMEOUT}" "${status_body}"; then
    dump_service_diagnostics "${systemctl_bin:-}" "${journalctl_bin:-}"
    exit 1
  fi
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
    dump_service_diagnostics "${systemctl_bin:-}" "${journalctl_bin:-}"
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
