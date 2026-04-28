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
FRONTEND_HOST="${FRONTEND_HOST:-127.0.0.1}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"
PUBLIC_URL="${PUBLIC_URL:-}"
RUN_FRONTEND_BUILD="${RUN_FRONTEND_BUILD:-true}"
STRICT_LOCAL_HEALTH="${STRICT_LOCAL_HEALTH:-true}"
ALLOW_DIRTY_DEPLOY="${ALLOW_DIRTY_DEPLOY:-false}"
# Where next build stages its output before the atomic swap.  Relative
# to frontend/ so it lives on the same filesystem as the live .next (a
# requirement for an atomic rename).  See deploy_frontend_atomic().
FRONTEND_STAGING_DIR_NAME="${FRONTEND_STAGING_DIR_NAME:-.next.new}"
FRONTEND_PROBE_MAX_ATTEMPTS="${FRONTEND_PROBE_MAX_ATTEMPTS:-15}"
FRONTEND_PROBE_SLEEP_SECONDS="${FRONTEND_PROBE_SLEEP_SECONDS:-2}"

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

resolve_node_toolchain() {
  if command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1; then
    return 0
  fi

  local home_candidates=(
    "/home/${APP_USER}"
    "${HOME:-}"
  )

  local home_dir=""
  local candidate=""
  for candidate in "${home_candidates[@]}"; do
    if [[ -n "${candidate}" && -d "${candidate}" ]]; then
      home_dir="${candidate}"
      break
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
    node_bin="$(
      find "${NVM_DIR}/versions/node" -mindepth 2 -maxdepth 2 -type d -name bin 2>/dev/null \
      | sort -V \
      | tail -n 1
    )"
    if [[ -n "${node_bin}" && -d "${node_bin}" ]]; then
      export PATH="${node_bin}:${PATH}"
    fi
  fi

  if command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1; then
    return 0
  fi

  return 1
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

# A full 40-char hex SHA is the only form of DEPLOY_REF we can trust
# to point at a specific revision without a fresh fetch — branches,
# tags, and abbreviated SHAs are all mutable or ambiguous.  Accept
# both lowercase and uppercase: GITHUB_SHA is always lowercase, but
# git resolves either, and workflow_dispatch's deploy_ref input
# forwards user-pasted SHAs verbatim with no normalization.
is_full_commit_sha() {
  [[ "$1" =~ ^[0-9a-fA-F]{40}$ ]]
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
  # RUN_FRONTEND_BUILD used to be an opt-out via env var, but the
  # production server had it set to a non-true value in its login
  # environment, which silently short-circuited every frontend rebuild
  # and shipped stale /_next/ chunks.  We now IGNORE the variable
  # entirely and always run the frontend build.  If the frontend
  # directory is missing, that's a deploy-fatal error.
  log "Frontend build requested (RUN_FRONTEND_BUILD=${RUN_FRONTEND_BUILD:-unset}, build is always forced)."

  if [[ ! -f "${APP_DIR}/frontend/package.json" ]]; then
    error "frontend/package.json missing at ${APP_DIR}/frontend/package.json; cannot build frontend."
    exit 1
  fi

  if ! resolve_node_toolchain; then
    error "Required command not found: npm"
    error "Checked PATH plus NVM locations under /home/${APP_USER}/.nvm and \$HOME/.nvm"
    exit 1
  fi

  log "Using node=$(command -v node)"
  log "Using npm=$(command -v npm)"

  local frontend_dir="${APP_DIR}/frontend"
  local staging_dir="${frontend_dir}/${FRONTEND_STAGING_DIR_NAME}"

  # Remove any leftover staging dir from a prior failed deploy so we
  # start from a known-empty state.
  if [[ -d "${staging_dir}" ]]; then
    log "Removing stale frontend staging dir: ${staging_dir}"
    rm -rf "${staging_dir}"
  fi

  log "Installing frontend dependencies in ${frontend_dir}"
  if [[ -f "${frontend_dir}/package-lock.json" ]]; then
    npm ci --prefix "${frontend_dir}"
  else
    npm install --prefix "${frontend_dir}"
  fi

  # Build into the staging directory.  The next.config.mjs honors
  # NEXT_DIST_DIR so this does not touch the live .next/ directory at
  # all — the running dynasty-frontend process keeps serving chunks
  # from the current build until we do the atomic swap below.
  log "Building frontend production bundle into staging dir: ${staging_dir}"
  (
    cd "${frontend_dir}"
    NEXT_DIST_DIR="${FRONTEND_STAGING_DIR_NAME}" npm run build
  )

  verify_frontend_build_manifest "${staging_dir}"
}

# Parse the Next.js build manifests in the given dist directory and
# verify every chunk/asset they reference actually exists on disk.
# This catches partial builds, disk-full truncation, and any case where
# the manifest references a hash webpack has already deleted.
verify_frontend_build_manifest() {
  local dist_dir="$1"
  if [[ ! -d "${dist_dir}" ]]; then
    error "Frontend build dir does not exist: ${dist_dir}"
    exit 1
  fi

  local build_manifest="${dist_dir}/build-manifest.json"
  if [[ ! -f "${build_manifest}" ]]; then
    error "Missing build-manifest.json at ${build_manifest}"
    exit 1
  fi

  log "Verifying frontend build manifest references: ${dist_dir}"
  python3 - "${dist_dir}" <<'PY' || {
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
    if len(missing) > 20:
        print(f"  ... and {len(missing) - 20} more", file=sys.stderr)
    sys.exit(1)

print(f"[verify-build] OK: {seen} manifest-referenced asset(s) present in {dist_dir}")
PY
    error "Frontend build verification failed for ${dist_dir}."
    exit 1
  }
}

# Atomic frontend swap:
#   1. Stop the dynasty-frontend service so no process is holding file
#      descriptors into the old .next/.
#   2. Move the old .next to .next.old (for emergency rollback) and
#      rename the staging .next.new into place.
#   3. Start the frontend service, which will read the fresh .next/.
#   4. Probe a few /_next/static/* assets over localhost to confirm
#      the running process actually serves the chunks referenced by
#      the new build-manifest.json.
#   5. Remove the .next.old archive in the background.
deploy_frontend_atomic() {
  local frontend_dir="${APP_DIR}/frontend"
  local staging_dir="${frontend_dir}/${FRONTEND_STAGING_DIR_NAME}"
  local live_dir="${frontend_dir}/.next"
  local old_dir="${frontend_dir}/.next.old"

  # Atomic swap always runs.  maybe_build_frontend is guaranteed to
  # have produced a staging dir (or exited fatally).  If the staging
  # dir is still missing here, something is seriously wrong and we
  # refuse to continue, because the previous skip-and-return behavior
  # is exactly what silently shipped broken /_next/ chunks.
  if [[ ! -d "${staging_dir}" ]]; then
    error "Expected frontend staging dir missing at ${staging_dir}."
    error "maybe_build_frontend did not produce a build output — aborting deploy."
    exit 1
  fi

  local frontend_name="${SERVICE_NAME}-frontend"
  # HARD FAIL: the frontend MUST be managed by systemd.  The previous
  # WARN-and-continue branch is exactly the silent-failure path that
  # shipped the ChunkLoadError outage — we swapped .next/ on disk but
  # the unmanaged Next.js process (pm2/nohup/tmux) kept serving stale
  # chunks because nothing restarted it.  ensure_systemd_service must
  # install the unit before we reach this point.
  if ! sudo -n "${SYSTEMCTL_BIN}" cat "${frontend_name}" >/dev/null 2>&1; then
    error "Frontend systemd unit ${frontend_name} is not installed."
    error "ensure_systemd_service should have installed it before this point."
    exit 1
  fi

  log "Stopping frontend service for atomic swap: ${frontend_name}"
  sudo -n "${SYSTEMCTL_BIN}" stop "${frontend_name}" || true

  # Best-effort cleanup of any legacy process still holding the port.
  # One-shot migration step: on a box that was previously running
  # Next.js via pm2 / nohup / tmux (outside systemd), `systemctl stop`
  # is a no-op.  We need to kill the unmanaged process or the next
  # `systemctl start` below will fail with EADDRINUSE on port 3000.
  if ! ensure_port_free "${FRONTEND_PORT}"; then
    error "Could not free port ${FRONTEND_PORT} before frontend swap."
    exit 1
  fi

  # Clear any leftover .next.old from a previous interrupted deploy.
  if [[ -d "${old_dir}" ]]; then
    rm -rf "${old_dir}"
  fi

  if [[ -d "${live_dir}" ]]; then
    mv "${live_dir}" "${old_dir}"
  fi
  mv "${staging_dir}" "${live_dir}"
  log "Frontend build swapped into place: ${live_dir}"

  log "Starting frontend service after swap: ${frontend_name}"
  sudo -n "${SYSTEMCTL_BIN}" start "${frontend_name}"
  sleep 2
  if ! sudo -n "${SYSTEMCTL_BIN}" is-active --quiet "${frontend_name}"; then
    error "Frontend service ${frontend_name} failed to start after swap."
    sudo -n "${JOURNALCTL_BIN}" -u "${frontend_name}" -n 80 --no-pager || true
    exit 1
  fi
  log "Frontend service ${frontend_name} is active."

  if ! probe_frontend_next_assets "${live_dir}"; then
    error "Post-swap /_next/static/* asset probe failed; aborting deploy."
    exit 1
  fi

  # Background-delete the old build so the critical path stays short.
  if [[ -d "${old_dir}" ]]; then
    ( rm -rf "${old_dir}" ) >/dev/null 2>&1 &
  fi
}

# Return 0 if the TCP port is currently accepting connections (in use),
# 1 if it is free.  Uses bash's built-in /dev/tcp virtual filesystem so
# no extra tools are required.
port_in_use() {
  local port="$1"
  if (: < "/dev/tcp/127.0.0.1/${port}") >/dev/null 2>&1; then
    return 0
  fi
  return 1
}

# Best-effort: kill any process holding the given TCP port and wait for
# the port to become free.  Returns 0 if the port is free within the
# timeout, 1 otherwise.  Used to migrate off an unmanaged Next.js
# process before handing control to the dynasty-frontend systemd unit.
ensure_port_free() {
  local port="$1"
  local max_wait_seconds="${ENSURE_PORT_FREE_TIMEOUT:-15}"
  local waited=0

  if ! port_in_use "${port}"; then
    return 0
  fi

  log "Port ${port} is still in use after systemctl stop; killing legacy listener(s)."

  # Prefer fuser (kills by TCP port, respects ownership).
  if command -v fuser >/dev/null 2>&1; then
    fuser -k -n tcp "${port}" 2>/dev/null || true
  fi

  # Fall back to lsof + kill for anything fuser didn't catch.
  if command -v lsof >/dev/null 2>&1; then
    local pids
    pids="$(lsof -ti:"${port}" 2>/dev/null || true)"
    if [[ -n "${pids}" ]]; then
      log "Killing pids holding port ${port}: ${pids}"
      # shellcheck disable=SC2086
      kill -9 ${pids} 2>/dev/null || true
    fi
  fi

  # Final fallback: pkill any next start / next-server for current user.
  pkill -9 -u "$(id -u)" -f 'next start' 2>/dev/null || true
  pkill -9 -u "$(id -u)" -f 'next-server' 2>/dev/null || true

  while (( waited < max_wait_seconds )); do
    if ! port_in_use "${port}"; then
      log "Port ${port} is free after ${waited}s."
      return 0
    fi
    sleep 1
    waited=$((waited + 1))
  done

  error "Port ${port} is still in use after ${max_wait_seconds}s cleanup."
  return 1
}

# Probe every /_next/static/* asset referenced by both the build
# manifests AND the prerendered SSG HTML output in .next/server/app/
# against the running Next.js process on loopback.  The prerendered
# HTML scan is the critical piece: Next.js bakes <script src> tags for
# async chunks (like the 448-*.js error chunk) that do not appear in
# build-manifest.json, so a manifest-only walk silently missed the
# exact failure mode that shipped the production ChunkLoadError.
probe_frontend_next_assets() {
  local live_dir="$1"
  local manifest="${live_dir}/build-manifest.json"
  if [[ ! -f "${manifest}" ]]; then
    error "Missing build-manifest.json at ${manifest}; cannot probe frontend."
    return 1
  fi

  local probe_list
  probe_list="$(python3 - "${live_dir}" <<'PY'
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
    p = os.path.join(live_dir, name)
    if not os.path.exists(p):
        continue
    try:
        with open(p) as fh:
            walk(json.load(fh))
    except Exception:
        pass

# Also walk every prerendered HTML file under .next/server/app and
# .next/server/pages and collect every /_next/static/* reference.  This
# is what catches the async-chunk failure mode.
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

  local asset url code attempts
  while IFS= read -r asset; do
    [[ -z "${asset}" ]] && continue
    url="http://${FRONTEND_HOST}:${FRONTEND_PORT}/_next/${asset}"
    attempts=0
    code=""
    # --globoff prevents curl from interpreting literal [ and ] in
    # the URL as glob/range syntax.  Next.js dynamic routes produce
    # chunk filenames like "app/api/public/league/[section]/route-*.js"
    # with the square brackets preserved on disk — without --globoff,
    # curl errors out with "bad range in URL" for every such asset.
    while (( attempts < FRONTEND_PROBE_MAX_ATTEMPTS )); do
      code="$(curl --silent --show-error --globoff --output /dev/null --write-out '%{http_code}' --max-time 10 "${url}" || echo 000)"
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

ensure_systemd_service() {
  require_command systemctl
  local frontend_name="${SERVICE_NAME}-frontend"
  local backend_present=false
  local frontend_present=false
  local frontend_execstart=""
  local frontend_exec_bin=""
  local force_reinstall=false

  if sudo -n "${SYSTEMCTL_BIN}" cat "${SERVICE_NAME}" >/dev/null 2>&1; then
    backend_present=true
  fi
  if sudo -n "${SYSTEMCTL_BIN}" cat "${frontend_name}" >/dev/null 2>&1; then
    frontend_present=true
    # Validate the existing frontend unit's ExecStart actually points
    # at an executable file.  An earlier version of the template
    # hardcoded /usr/bin/npm, which does not exist on nvm-based boxes,
    # so the unit got installed but systemctl start would never
    # succeed.  Detect that case and force a reinstall.
    frontend_execstart="$(sudo -n "${SYSTEMCTL_BIN}" cat "${frontend_name}" 2>/dev/null \
      | awk -F= '/^ExecStart=/ {sub(/^ExecStart=/, ""); print; exit}')"
    if [[ -n "${frontend_execstart}" ]]; then
      frontend_exec_bin="${frontend_execstart%% *}"
      if [[ -n "${frontend_exec_bin}" && ! -x "${frontend_exec_bin}" ]]; then
        warn "Frontend unit ExecStart binary is not executable: ${frontend_exec_bin}. Forcing reinstall."
        force_reinstall=true
      fi
    fi
  fi

  if [[ "${backend_present}" == "true" && "${frontend_present}" == "true" && "${force_reinstall}" != "true" ]]; then
    return 0
  fi

  local installer_script
  installer_script="${APP_DIR}/deploy/install-systemd-service.sh"
  if [[ "${force_reinstall}" == "true" ]]; then
    warn "Reinstalling frontend systemd unit because its ExecStart binary (${frontend_exec_bin}) is not runnable."
  else
    warn "Systemd units missing (backend=${backend_present}, frontend=${frontend_present}). Running bootstrap installer."
  fi
  if [[ ! -f "${installer_script}" ]]; then
    error "Missing bootstrap installer script: ${installer_script}"
    exit 1
  fi

  local force_install_value="${FORCE_SERVICE_INSTALL:-false}"
  if [[ "${force_reinstall}" == "true" ]]; then
    force_install_value=true
  fi

  APP_DIR="${APP_DIR}" \
  APP_USER="${APP_USER}" \
  VENV_DIR="${VENV_DIR}" \
  SERVICE_NAME="${SERVICE_NAME}" \
  FORCE_SERVICE_INSTALL="${force_install_value}" \
  bash "${installer_script}"

  if ! sudo -n "${SYSTEMCTL_BIN}" cat "${SERVICE_NAME}" >/dev/null 2>&1; then
    error "Backend systemd unit ${SERVICE_NAME} is still unavailable after bootstrap install."
    exit 1
  fi
  if ! sudo -n "${SYSTEMCTL_BIN}" cat "${frontend_name}" >/dev/null 2>&1; then
    error "Frontend systemd unit ${frontend_name} is still unavailable after bootstrap install."
    error "deploy_frontend_atomic requires the frontend unit to be installed before the swap."
    exit 1
  fi

  # Re-verify the reinstalled frontend unit's ExecStart is now runnable.
  frontend_execstart="$(sudo -n "${SYSTEMCTL_BIN}" cat "${frontend_name}" 2>/dev/null \
    | awk -F= '/^ExecStart=/ {sub(/^ExecStart=/, ""); print; exit}')"
  frontend_exec_bin="${frontend_execstart%% *}"
  if [[ -z "${frontend_exec_bin}" || ! -x "${frontend_exec_bin}" ]]; then
    error "Frontend unit ExecStart binary is still not executable after reinstall: '${frontend_exec_bin}'"
    exit 1
  fi
  log "Frontend systemd unit ExecStart binary resolved to: ${frontend_exec_bin}"
}

restart_service() {
  require_command systemctl
  # NOTE: the frontend (dynasty-frontend) is restarted by
  # deploy_frontend_atomic() as part of the build-swap sequence, not
  # here.  This function only touches the backend so that a frontend
  # chunk-manifest failure short-circuits the deploy BEFORE we cycle
  # the backend.
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
    APP_DIR="${APP_DIR}" \
    FRONTEND_HOST="${FRONTEND_HOST}" \
    FRONTEND_PORT="${FRONTEND_PORT}" \
    FRONTEND_BUILD_DIR="${APP_DIR}/frontend/.next" \
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

  local tracked_changes
  tracked_changes="$(git status --porcelain --untracked-files=no)"
  local needs_force_clean="false"
  if [[ -n "${tracked_changes}" ]]; then
    if [[ "${ALLOW_DIRTY_DEPLOY}" == "true" ]]; then
      warn "Tracked changes detected but ALLOW_DIRTY_DEPLOY=true, proceeding without stash."
    else
      warn "Tracked git changes detected in ${APP_DIR}:"
      git diff --stat || true
      local stash_name="deploy-auto-stash-$(date -u +%Y%m%dT%H%M%SZ)"
      log "Auto-stashing tracked changes as '${stash_name}' (inspect later with: git stash list)."
      if ! git stash push -m "${stash_name}"; then
        warn "git stash failed — likely a .git/objects permission issue (e.g. scraper-owned"
        warn "objects under ${APP_DIR}/.git/objects/ that the deploy user cannot write next to)."
        warn "Tracked changes will be DISCARDED by an unconditional 'git reset --hard' against the target ref"
        warn "(reset only updates refs + working tree, so it survives the same .git/objects permissions"
        warn "that broke stash)."
        warn "If you need the dirty files preserved, set ALLOW_DIRTY_DEPLOY=true and stash manually before re-running."
        warn "To fix the underlying permissions, ensure the scraper and the deploy user share group ownership of"
        warn "${APP_DIR}/.git (e.g. 'chgrp -R <shared-group> .git && chmod -R g+ws .git')."
        needs_force_clean="true"
      fi
    fi
  fi

  local current_rev target_short
  current_rev="$(git rev-parse HEAD)"
  PRE_DEPLOY_REV="${current_rev}"
  printf '%s\n' "${PRE_DEPLOY_REV}" > "${STATE_DIR}/pre_deploy_rev"

  log "Deploy context: app=${APP_NAME} user=${APP_USER} service=${SERVICE_NAME} app_dir=${APP_DIR}"
  log "Deploy target requested: DEPLOY_REF=${DEPLOY_REF} (fallback branch=${DEPLOY_BRANCH})"
  log "Current revision: ${current_rev}"

  local fetch_ok="true"
  if ! git fetch --prune --tags origin; then
    fetch_ok="false"
    warn "git fetch failed — almost certainly the same .git/objects permission issue as the stash error."
    warn "On the production box, run 'ls -la ${APP_DIR}/.git/objects' and look for subdirectories owned"
    warn "by a user other than '${APP_USER:-the deploy user}' (commonly the scraper). Fix with"
    warn "'chgrp -R <shared-group> ${APP_DIR}/.git && chmod -R g+ws ${APP_DIR}/.git', or run scrapes"
    warn "as the deploy user. Continuing with whatever refs are already present locally."
  fi

  # If fetch failed, only proceed when DEPLOY_REF is a full 40-char
  # commit SHA — anything else (branch, tag, short SHA) could resolve
  # to a stale local revision and ship the wrong code. GITHUB_SHA is
  # always a full SHA, so the workflow's auto path stays unaffected.
  if [[ "${fetch_ok}" != "true" ]] && ! is_full_commit_sha "${DEPLOY_REF}"; then
    error "git fetch failed and DEPLOY_REF='${DEPLOY_REF}' is not a full 40-char commit SHA."
    error "Refusing to deploy from a potentially-stale local copy of a mutable ref."
    error "Fix the .git/objects permissions noted above and re-run, or pass an explicit full SHA"
    error "(resolve the branch tip yourself with 'git rev-parse' and pass that as deploy_ref)."
    exit 1
  fi

  if ! TARGET_REV="$(resolve_git_ref "${DEPLOY_REF}")"; then
    # Don't fall back to DEPLOY_BRANCH when fetch failed: the local
    # branch ref is potentially stale (the requested SHA may simply be
    # missing from the local repo), and a silent fallback would deploy
    # the wrong revision and report success.
    if [[ "${fetch_ok}" != "true" ]]; then
      error "Could not resolve DEPLOY_REF='${DEPLOY_REF}' locally and 'git fetch' had failed."
      error "Refusing to fall back to DEPLOY_BRANCH='${DEPLOY_BRANCH}' (potentially stale)."
      error "The requested ref may simply be missing from the local repo because fetch could not"
      error "write new objects. Fix the .git/objects permissions noted above and re-run the deploy."
      exit 1
    fi
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
  elif [[ "${needs_force_clean}" == "true" ]]; then
    log "Repository already at target revision but auto-stash failed; running 'git reset --hard ${TARGET_REV}' to discard the dirty working tree."
    git reset --hard "${TARGET_REV}"
  else
    log "Repository already at target revision."
  fi

  prepare_python_runtime
  maybe_build_frontend
  ensure_systemd_service
  deploy_frontend_atomic
  restart_service
  verify_deploy
  record_success_state

  log "Deployment succeeded at revision ${TARGET_REV}."
}

main "$@"
