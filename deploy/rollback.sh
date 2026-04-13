#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_APP_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

APP_NAME="${APP_NAME:-riskittogetthebrisket}"
APP_DIR="${APP_DIR:-${DEFAULT_APP_DIR}}"
APP_USER="${APP_USER:-$(id -un)}"
VENV_DIR="${VENV_DIR:-${APP_DIR}/.venv}"
SERVICE_NAME="${SERVICE_NAME:-dynasty}"
DEPLOY_STATE_DIR="${DEPLOY_STATE_DIR:-${APP_DIR}/.deploy}"
LAST_SUCCESSFUL_DEPLOY_COMMIT_FILE="${LAST_SUCCESSFUL_DEPLOY_COMMIT_FILE:-${DEPLOY_STATE_DIR}/${APP_NAME}.last_successful_deploy_commit}"
APP_HOST="${APP_HOST:-127.0.0.1}"
APP_PORT="${APP_PORT:-8000}"
FRONTEND_HOST="${FRONTEND_HOST:-127.0.0.1}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"
FRONTEND_STAGING_DIR_NAME="${FRONTEND_STAGING_DIR_NAME:-.next.new}"
FRONTEND_PROBE_MAX_ATTEMPTS="${FRONTEND_PROBE_MAX_ATTEMPTS:-15}"
FRONTEND_PROBE_SLEEP_SECONDS="${FRONTEND_PROBE_SLEEP_SECONDS:-2}"
RUN_FRONTEND_BUILD="${RUN_FRONTEND_BUILD:-true}"
PUBLIC_URL="${PUBLIC_URL:-}"
STRICT_LOCAL_HEALTH="${STRICT_LOCAL_HEALTH:-true}"
ROLLBACK_REF="${1:-${ROLLBACK_REF:-}}"
SYSTEMCTL_BIN=""
JOURNALCTL_BIN=""
CHOWN_BIN=""

lower() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]'
}

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

resolve_node_toolchain() {
  if command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1; then
    return 0
  fi
  local home_candidates=("/home/${APP_USER}" "${HOME:-}")
  local home_dir="" candidate=""
  for candidate in "${home_candidates[@]}"; do
    if [[ -n "${candidate}" && -d "${candidate}" ]]; then
      home_dir="${candidate}"; break
    fi
  done
  if [[ -z "${NVM_DIR:-}" && -n "${home_dir}" && -d "${home_dir}/.nvm" ]]; then
    export NVM_DIR="${home_dir}/.nvm"
  fi
  if [[ -n "${NVM_DIR:-}" && -s "${NVM_DIR}/nvm.sh" ]]; then
    # shellcheck disable=SC1090
    . "${NVM_DIR}/nvm.sh"
  fi
  if command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1; then
    return 0
  fi
  local node_bin=""
  if [[ -n "${NVM_DIR:-}" && -d "${NVM_DIR}/versions/node" ]]; then
    node_bin="$(find "${NVM_DIR}/versions/node" -mindepth 2 -maxdepth 2 -type d -name bin 2>/dev/null | sort -V | tail -n 1)"
    if [[ -n "${node_bin}" && -d "${node_bin}" ]]; then
      export PATH="${node_bin}:${PATH}"
    fi
  fi
  if command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1; then
    return 0
  fi
  return 1
}

# Verify every .js/.css reference in the Next.js build manifests exists
# on disk.  Mirrors deploy.sh::verify_frontend_build_manifest — any
# drift here reintroduces the chunk-hash mismatch bug, so keep the two
# implementations behaviourally identical.
verify_frontend_build_manifest() {
  local dist_dir="$1"
  if [[ ! -d "${dist_dir}" ]]; then
    error "Frontend build dir does not exist: ${dist_dir}"
    return 1
  fi
  local build_manifest="${dist_dir}/build-manifest.json"
  if [[ ! -f "${build_manifest}" ]]; then
    error "Missing build-manifest.json at ${build_manifest}"
    return 1
  fi
  log "Verifying frontend build manifest references: ${dist_dir}"
  python3 - "${dist_dir}" <<'PY' || return 1
import json
import os
import sys

dist_dir = sys.argv[1]
manifests = [
    "build-manifest.json",
    "app-build-manifest.json",
    "react-loadable-manifest.json",
]

missing = []
seen = 0


def walk(obj):
    global seen
    if isinstance(obj, str):
        if obj.endswith(".js") or obj.endswith(".css"):
            seen += 1
            full = os.path.join(dist_dir, obj)
            if not os.path.exists(full):
                missing.append(obj)
    elif isinstance(obj, list):
        for item in obj:
            walk(item)
    elif isinstance(obj, dict):
        for value in obj.values():
            walk(value)


for name in manifests:
    path = os.path.join(dist_dir, name)
    if not os.path.exists(path):
        continue
    try:
        with open(path) as fh:
            data = json.load(fh)
    except Exception as exc:  # noqa: BLE001
        print(f"[verify-build] Unable to parse {name}: {exc}", file=sys.stderr)
        sys.exit(1)
    walk(data)

if missing:
    print(
        f"[verify-build] {len(missing)} referenced asset(s) missing from {dist_dir}",
        file=sys.stderr,
    )
    for entry in missing[:20]:
        print(f"  - {entry}", file=sys.stderr)
    sys.exit(1)

print(f"[verify-build] OK: {seen} manifest-referenced asset(s) present in {dist_dir}")
PY
}

probe_frontend_next_assets() {
  local live_dir="$1"
  local manifest="${live_dir}/build-manifest.json"
  if [[ ! -f "${manifest}" ]]; then
    error "Missing build-manifest.json at ${manifest}; cannot probe frontend."
    return 1
  fi
  local probe_list
  probe_list="$(python3 - "${manifest}" <<'PY'
import json
import sys

with open(sys.argv[1]) as fh:
    manifest = json.load(fh)

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


walk(manifest)
chunks = sorted(a for a in assets if a.startswith("static/chunks/"))
picked = []
for asset in chunks[:2]:
    picked.append(asset)
if chunks:
    picked.append(chunks[-1])
for asset in picked:
    print(asset)
PY
  )"
  if [[ -z "${probe_list}" ]]; then
    warn "Build manifest lists no static chunks; skipping _next probe."
    return 0
  fi
  local asset url code attempts
  while IFS= read -r asset; do
    [[ -z "${asset}" ]] && continue
    url="http://${FRONTEND_HOST}:${FRONTEND_PORT}/_next/${asset}"
    attempts=0
    code=""
    while (( attempts < FRONTEND_PROBE_MAX_ATTEMPTS )); do
      code="$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' --max-time 10 "${url}" || echo 000)"
      if [[ "${code}" == "200" ]]; then
        log "Frontend _next probe OK: ${asset}"
        break
      fi
      attempts=$((attempts + 1))
      log "Frontend _next probe ${asset} returned HTTP ${code} (attempt ${attempts}/${FRONTEND_PROBE_MAX_ATTEMPTS}); retrying in ${FRONTEND_PROBE_SLEEP_SECONDS}s."
      sleep "${FRONTEND_PROBE_SLEEP_SECONDS}"
    done
    if [[ "${code}" != "200" ]]; then
      error "Frontend _next probe failed after ${attempts} attempts: ${url} -> HTTP ${code}"
      return 1
    fi
  done <<< "${probe_list}"
  return 0
}

# Rebuild the rolled-back frontend into a staging dir and atomically
# swap it into place.  Without this, a rollback would keep whatever
# .next/ the failed forward deploy left on disk, so HTML from the old
# (rolled-back) commit would reference chunk hashes from the new build
# — the exact failure mode we are trying to eliminate.
maybe_rebuild_frontend_after_rollback() {
  local run_build
  run_build="$(lower "${RUN_FRONTEND_BUILD}")"
  if [[ "${run_build}" != "true" && "${run_build}" != "1" && "${run_build}" != "yes" ]]; then
    log "Frontend build disabled (RUN_FRONTEND_BUILD=${RUN_FRONTEND_BUILD}); skipping rollback frontend rebuild."
    return 0
  fi

  local frontend_dir="${APP_DIR}/frontend"
  if [[ ! -f "${frontend_dir}/package.json" ]]; then
    warn "No frontend/package.json after rollback; skipping frontend rebuild."
    return 0
  fi

  if ! resolve_node_toolchain; then
    error "Required command not found for rollback frontend rebuild: npm"
    return 1
  fi

  local staging_dir="${frontend_dir}/${FRONTEND_STAGING_DIR_NAME}"
  local live_dir="${frontend_dir}/.next"
  local old_dir="${frontend_dir}/.next.old"

  if [[ -d "${staging_dir}" ]]; then
    log "Removing stale frontend staging dir: ${staging_dir}"
    rm -rf "${staging_dir}"
  fi

  log "Installing frontend dependencies in ${frontend_dir} (rollback)"
  if [[ -f "${frontend_dir}/package-lock.json" ]]; then
    npm ci --prefix "${frontend_dir}"
  else
    npm install --prefix "${frontend_dir}"
  fi

  log "Rebuilding rolled-back frontend bundle into staging dir: ${staging_dir}"
  (
    cd "${frontend_dir}"
    NEXT_DIST_DIR="${FRONTEND_STAGING_DIR_NAME}" npm run build
  )

  verify_frontend_build_manifest "${staging_dir}" || return 1

  local frontend_name="${SERVICE_NAME}-frontend"
  if sudo -n "${SYSTEMCTL_BIN}" cat "${frontend_name}" >/dev/null 2>&1; then
    log "Stopping frontend service for rollback swap: ${frontend_name}"
    sudo -n "${SYSTEMCTL_BIN}" stop "${frontend_name}" || true
  fi

  if [[ -d "${old_dir}" ]]; then
    rm -rf "${old_dir}"
  fi
  if [[ -d "${live_dir}" ]]; then
    mv "${live_dir}" "${old_dir}"
  fi
  mv "${staging_dir}" "${live_dir}"
  log "Rolled-back frontend build swapped into place: ${live_dir}"

  if sudo -n "${SYSTEMCTL_BIN}" cat "${frontend_name}" >/dev/null 2>&1; then
    log "Starting frontend service after rollback swap: ${frontend_name}"
    sudo -n "${SYSTEMCTL_BIN}" start "${frontend_name}"
    sleep 2
    if ! sudo -n "${SYSTEMCTL_BIN}" is-active --quiet "${frontend_name}"; then
      error "Frontend service ${frontend_name} failed to start after rollback swap."
      sudo -n "${JOURNALCTL_BIN}" -u "${frontend_name}" -n 80 --no-pager || true
      return 1
    fi
    log "Frontend service ${frontend_name} is active after rollback swap."
    if ! probe_frontend_next_assets "${live_dir}"; then
      error "Post-rollback /_next/static/* asset probe failed."
      return 1
    fi
  fi

  if [[ -d "${old_dir}" ]]; then
    ( rm -rf "${old_dir}" ) >/dev/null 2>&1 &
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
  resolve_and_validate_sudo_binaries

  [[ -d "${APP_DIR}" ]] || { error "APP_DIR does not exist: ${APP_DIR}"; exit 1; }
  cd "${APP_DIR}"
  [[ -d ".git" ]] || { error "APP_DIR is not a git repository: ${APP_DIR}"; exit 1; }

  local state_dir rollback_target current_rev target_rev
  state_dir="${DEPLOY_STATE_DIR}"
  mkdir -p "${state_dir}"

  if [[ -z "${ROLLBACK_REF}" && -f "${state_dir}/pre_deploy_rev" ]]; then
    ROLLBACK_REF="$(head -n 1 "${state_dir}/pre_deploy_rev" | tr -d '\r\n')"
  fi
  if [[ -z "${ROLLBACK_REF}" && -f "${state_dir}/last_successful_rev" ]]; then
    ROLLBACK_REF="$(head -n 1 "${state_dir}/last_successful_rev" | tr -d '\r\n')"
  fi
  if [[ -z "${ROLLBACK_REF}" && -n "${LAST_SUCCESSFUL_DEPLOY_COMMIT_FILE}" && -f "${LAST_SUCCESSFUL_DEPLOY_COMMIT_FILE}" ]]; then
    ROLLBACK_REF="$(head -n 1 "${LAST_SUCCESSFUL_DEPLOY_COMMIT_FILE}" | tr -d '\r\n')"
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

  # Rebuild the frontend from the rolled-back source tree before
  # restarting the backend.  A failure here should still fall through
  # to the backend restart, but we log the failure loudly so operators
  # know the frontend is potentially inconsistent.
  if ! maybe_rebuild_frontend_after_rollback; then
    error "Rollback frontend rebuild failed; backend will still be restarted but frontend state is suspect."
  fi

  log "Restarting service ${SERVICE_NAME} after rollback."
  sudo -n "${SYSTEMCTL_BIN}" restart "${SERVICE_NAME}"
  if ! sudo -n "${SYSTEMCTL_BIN}" is-active --quiet "${SERVICE_NAME}"; then
    error "Service ${SERVICE_NAME} is not active after rollback restart."
    sudo -n "${JOURNALCTL_BIN}" -u "${SERVICE_NAME}" -n 120 --no-pager || true
    exit 1
  fi

  if [[ -f "${APP_DIR}/deploy/verify-deploy.sh" ]]; then
    APP_HOST="${APP_HOST}" \
    APP_PORT="${APP_PORT}" \
    APP_DIR="${APP_DIR}" \
    FRONTEND_HOST="${FRONTEND_HOST}" \
    FRONTEND_PORT="${FRONTEND_PORT}" \
    FRONTEND_BUILD_DIR="${APP_DIR}/frontend/.next" \
    SERVICE_NAME="${SERVICE_NAME}" \
    PUBLIC_URL="${PUBLIC_URL}" \
    STRICT_LOCAL_HEALTH="${STRICT_LOCAL_HEALTH}" \
    bash "${APP_DIR}/deploy/verify-deploy.sh"
  fi

  printf '%s\n' "${rollback_target}" > "${state_dir}/last_successful_rev"
  printf '%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "${state_dir}/last_successful_at_utc"
  if [[ -n "${LAST_SUCCESSFUL_DEPLOY_COMMIT_FILE}" ]]; then
    mkdir -p "$(dirname "${LAST_SUCCESSFUL_DEPLOY_COMMIT_FILE}")"
    printf '%s\n' "${rollback_target}" > "${LAST_SUCCESSFUL_DEPLOY_COMMIT_FILE}"
  fi
  log "Rollback complete. Active revision: ${rollback_target}"
}

main "$@"
