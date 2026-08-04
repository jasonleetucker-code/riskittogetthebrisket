#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_APP_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

APP_DIR="${APP_DIR:-${DEFAULT_APP_DIR}}"
APP_USER="${APP_USER:-$(id -un)}"
APP_SLUG="${APP_SLUG:-$(basename "${APP_DIR}")}"
VENV_DIR="${VENV_DIR:-${HOME}/.venvs/${APP_SLUG}}"
SERVICE_NAME="${SERVICE_NAME:-dynasty}"
SERVICE_TEMPLATE_PATH="${SERVICE_TEMPLATE_PATH:-${APP_DIR}/deploy/systemd/dynasty.service.template}"
FORCE_SERVICE_INSTALL="${FORCE_SERVICE_INSTALL:-false}"
SYSTEMCTL_BIN=""
INSTALL_BIN=""

log() {
  printf '[systemd-bootstrap] %s\n' "$*"
}

error() {
  printf '[systemd-bootstrap][ERROR] %s\n' "$*" >&2
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

resolve_and_validate_sudo_binaries() {
  SYSTEMCTL_BIN="$(resolve_sudo_nopasswd_binary "systemctl" /bin/systemctl /usr/bin/systemctl)"
  INSTALL_BIN="$(resolve_sudo_nopasswd_binary "install" /usr/bin/install /bin/install)"
}

# Locate an absolute path to the `npm` binary that the dynasty-frontend
# systemd unit can use as ExecStart.  This mirrors deploy.sh's
# resolve_node_toolchain but returns paths instead of relying on PATH
# side-effects, because systemd runs with a minimal environment and
# will not source nvm.sh on its own.
#
# Writes two values to NPM_BIN_PATH and NODE_BIN_DIR on success.
# Returns 1 and logs an error if npm cannot be located.
NPM_BIN_PATH=""
NODE_BIN_DIR=""

resolve_npm_bin_for_systemd() {
  NPM_BIN_PATH=""
  NODE_BIN_DIR=""

  local candidate
  # 1. System-wide install (Debian/Ubuntu package).
  for candidate in /usr/bin/npm /usr/local/bin/npm; do
    if [[ -x "${candidate}" ]]; then
      NPM_BIN_PATH="${candidate}"
      NODE_BIN_DIR="$(dirname "${candidate}")"
      return 0
    fi
  done

  # 2. Anything already on PATH (e.g. from operator shell profile).
  if command -v npm >/dev/null 2>&1; then
    NPM_BIN_PATH="$(command -v npm)"
    NODE_BIN_DIR="$(dirname "${NPM_BIN_PATH}")"
    return 0
  fi

  # 3. nvm-installed node under the service user's home dir.  This is
  # the production case — the production VPS manages node via nvm and
  # /usr/bin/npm does not exist.
  local home_candidates=(
    "/home/${APP_USER}"
    "${HOME:-}"
  )
  local home_dir=""
  for candidate in "${home_candidates[@]}"; do
    if [[ -n "${candidate}" && -d "${candidate}" ]]; then
      home_dir="${candidate}"
      break
    fi
  done

  local nvm_dir=""
  if [[ -n "${home_dir}" && -d "${home_dir}/.nvm" ]]; then
    nvm_dir="${home_dir}/.nvm"
  fi

  if [[ -n "${nvm_dir}" && -d "${nvm_dir}/versions/node" ]]; then
    local node_bin
    node_bin="$(
      find "${nvm_dir}/versions/node" -mindepth 2 -maxdepth 2 -type d -name bin 2>/dev/null \
      | sort -V \
      | tail -n 1
    )"
    if [[ -n "${node_bin}" && -x "${node_bin}/npm" ]]; then
      NPM_BIN_PATH="${node_bin}/npm"
      NODE_BIN_DIR="${node_bin}"
      return 0
    fi
  fi

  error "Could not locate npm for dynasty-frontend systemd unit."
  error "Checked: /usr/bin/npm, /usr/local/bin/npm, PATH, and ${nvm_dir:-<no nvm dir>}/versions/node/*/bin/npm"
  return 1
}

escape_sed_replacement() {
  printf '%s' "$1" | sed -e 's/[\\/&]/\\&/g'
}

main() {
  local force_install force_install_on unit_path tmp_unit
  local frontend_template frontend_name frontend_unit_path tmp_frontend
  local backend_needs_install=false
  local frontend_needs_install=false

  require_command sudo
  require_command install
  require_command mktemp
  require_command sed
  require_command systemctl
  resolve_and_validate_sudo_binaries

  [[ -n "${SERVICE_NAME}" ]] || { error "SERVICE_NAME cannot be empty."; exit 1; }
  [[ -n "${APP_USER}" ]] || { error "APP_USER cannot be empty."; exit 1; }
  [[ -n "${APP_DIR}" ]] || { error "APP_DIR cannot be empty."; exit 1; }
  [[ -n "${VENV_DIR}" ]] || { error "VENV_DIR cannot be empty."; exit 1; }
  [[ -f "${SERVICE_TEMPLATE_PATH}" ]] || { error "Service template not found: ${SERVICE_TEMPLATE_PATH}"; exit 1; }

  force_install="$(lower "${FORCE_SERVICE_INSTALL}")"
  force_install_on=false
  if [[ "${force_install}" == "true" || "${force_install}" == "1" || "${force_install}" == "yes" ]]; then
    force_install_on=true
  fi

  tmp_unit=""
  tmp_frontend=""
  trap 'rm -f "${tmp_unit:-}" "${tmp_frontend:-}"' EXIT

  # ── Backend service (FastAPI) ───────────────────────────────────────────
  # Deliberately do NOT `exit 0` early when the backend unit already
  # exists: we still need to check whether the frontend unit is
  # installed.  A previous version of this script exited here, which
  # meant production (where the backend was already installed) never
  # got the frontend systemd unit and silently ran Next.js under some
  # unmanaged process manager, so deploy.sh could not restart it.
  unit_path="/etc/systemd/system/${SERVICE_NAME}.service"
  if sudo -n "${SYSTEMCTL_BIN}" cat "${SERVICE_NAME}" >/dev/null 2>&1; then
    if [[ "${force_install_on}" == "true" ]]; then
      log "FORCE_SERVICE_INSTALL enabled; rewriting ${unit_path}."
      backend_needs_install=true
    else
      log "Backend service ${SERVICE_NAME} already installed; skipping."
    fi
  else
    log "Installing missing backend systemd unit ${unit_path}."
    backend_needs_install=true
  fi

  if [[ "${backend_needs_install}" == "true" ]]; then
    tmp_unit="$(mktemp)"
    sed \
      -e "s/__SERVICE_NAME__/$(escape_sed_replacement "${SERVICE_NAME}")/g" \
      -e "s/__APP_USER__/$(escape_sed_replacement "${APP_USER}")/g" \
      -e "s/__APP_DIR__/$(escape_sed_replacement "${APP_DIR}")/g" \
      -e "s/__VENV_DIR__/$(escape_sed_replacement "${VENV_DIR}")/g" \
      "${SERVICE_TEMPLATE_PATH}" > "${tmp_unit}"
    sudo -n "${INSTALL_BIN}" -m 0644 "${tmp_unit}" "${unit_path}"
    log "Installed ${SERVICE_NAME}.service"
  fi

  # ── Frontend service (Next.js) ──────────────────────────────────────────
  frontend_template="${APP_DIR}/deploy/systemd/dynasty-frontend.service.template"
  frontend_name="${SERVICE_NAME}-frontend"
  frontend_unit_path="/etc/systemd/system/${frontend_name}.service"

  if [[ ! -f "${frontend_template}" ]]; then
    error "Frontend service template not found at ${frontend_template}."
    error "The Next.js process must be managed by systemd; aborting bootstrap."
    exit 1
  fi

  if sudo -n "${SYSTEMCTL_BIN}" cat "${frontend_name}" >/dev/null 2>&1; then
    if [[ "${force_install_on}" == "true" ]]; then
      log "FORCE_SERVICE_INSTALL enabled; rewriting ${frontend_unit_path}."
      frontend_needs_install=true
    else
      log "Frontend service ${frontend_name} already installed; skipping."
    fi
  else
    log "Installing missing frontend systemd unit ${frontend_unit_path}."
    frontend_needs_install=true
  fi

  if [[ "${frontend_needs_install}" == "true" ]]; then
    # Resolve npm absolute path now so the rendered unit file uses a
    # path that actually exists under the service user's runtime.
    # Systemd does NOT source ~/.bashrc or nvm.sh, so relying on PATH
    # alone will fail on nvm-based production boxes.
    if ! resolve_npm_bin_for_systemd; then
      error "Cannot render dynasty-frontend unit without an absolute npm path."
      exit 1
    fi
    log "Resolved npm for frontend unit: ${NPM_BIN_PATH} (PATH dir: ${NODE_BIN_DIR})"

    tmp_frontend="$(mktemp)"
    sed \
      -e "s/__SERVICE_NAME__/$(escape_sed_replacement "${SERVICE_NAME}")/g" \
      -e "s/__APP_USER__/$(escape_sed_replacement "${APP_USER}")/g" \
      -e "s/__APP_DIR__/$(escape_sed_replacement "${APP_DIR}")/g" \
      -e "s/__VENV_DIR__/$(escape_sed_replacement "${VENV_DIR}")/g" \
      -e "s/__NPM_BIN__/$(escape_sed_replacement "${NPM_BIN_PATH}")/g" \
      -e "s/__NODE_BIN_DIR__/$(escape_sed_replacement "${NODE_BIN_DIR}")/g" \
      "${frontend_template}" > "${tmp_frontend}"
    sudo -n "${INSTALL_BIN}" -m 0644 "${tmp_frontend}" "${frontend_unit_path}"
    log "Installed ${frontend_name}.service"
  fi

  # ── Signal-alerts sweep (optional systemd timer) ───────────────────────
  # Deploys a one-shot service + daily timer that POSTs the internal
  # /api/signal-alerts/run endpoint.  We only install these units when
  # both templates exist AND SIGNAL_ALERT_CRON_TOKEN is set in the
  # .env file — without the token the endpoint would reject the
  # bearer auth, so there's no point enabling the timer yet.
  local alerts_service_template="${APP_DIR}/deploy/systemd/dynasty-signal-alerts.service.template"
  local alerts_timer_template="${APP_DIR}/deploy/systemd/dynasty-signal-alerts.timer.template"
  local alerts_service_name="${SERVICE_NAME}-signal-alerts"
  local alerts_service_path="/etc/systemd/system/${alerts_service_name}.service"
  local alerts_timer_path="/etc/systemd/system/${alerts_service_name}.timer"
  local alerts_needs_install=false
  local has_cron_token=false

  if [[ -f "${APP_DIR}/.env" ]] && grep -Eq '^[[:space:]]*SIGNAL_ALERT_CRON_TOKEN=.+$' "${APP_DIR}/.env"; then
    has_cron_token=true
  fi

  if [[ -f "${alerts_service_template}" && -f "${alerts_timer_template}" && "${has_cron_token}" == "true" ]]; then
    if sudo -n "${SYSTEMCTL_BIN}" cat "${alerts_service_name}.timer" >/dev/null 2>&1; then
      if [[ "${force_install_on}" == "true" ]]; then
        log "FORCE_SERVICE_INSTALL enabled; rewriting ${alerts_service_path} + timer."
        alerts_needs_install=true
      else
        log "Signal-alerts timer already installed; skipping."
      fi
    else
      log "Installing signal-alerts service + timer."
      alerts_needs_install=true
    fi

    if [[ "${alerts_needs_install}" == "true" ]]; then
      local tmp_alerts_service tmp_alerts_timer
      tmp_alerts_service="$(mktemp)"
      tmp_alerts_timer="$(mktemp)"
      trap 'rm -f "${tmp_unit:-}" "${tmp_frontend:-}" "${tmp_alerts_service:-}" "${tmp_alerts_timer:-}"' EXIT
      sed \
        -e "s/__SERVICE_NAME__/$(escape_sed_replacement "${SERVICE_NAME}")/g" \
        -e "s/__APP_USER__/$(escape_sed_replacement "${APP_USER}")/g" \
        -e "s/__APP_DIR__/$(escape_sed_replacement "${APP_DIR}")/g" \
        "${alerts_service_template}" > "${tmp_alerts_service}"
      sed \
        -e "s/__SERVICE_NAME__/$(escape_sed_replacement "${SERVICE_NAME}")/g" \
        "${alerts_timer_template}" > "${tmp_alerts_timer}"
      sudo -n "${INSTALL_BIN}" -m 0644 "${tmp_alerts_service}" "${alerts_service_path}"
      sudo -n "${INSTALL_BIN}" -m 0644 "${tmp_alerts_timer}" "${alerts_timer_path}"
      log "Installed ${alerts_service_name}.service + .timer"
    fi
  elif [[ -f "${alerts_service_template}" && "${has_cron_token}" != "true" ]]; then
    log "Signal-alerts timer skipped: SIGNAL_ALERT_CRON_TOKEN not set in ${APP_DIR}/.env."
  fi

  # ── Custom-alerts sweep (optional systemd timer) ───────────────────────
  # Same pattern as signal-alerts: install only when the cron token is
  # present.  Fires every 2 hours; the rule-engine cooldown inside
  # ``custom_alerts.py`` keeps a single rule from re-firing within 24h.
  local custom_alerts_service_template="${APP_DIR}/deploy/systemd/dynasty-custom-alerts.service.template"
  local custom_alerts_timer_template="${APP_DIR}/deploy/systemd/dynasty-custom-alerts.timer.template"
  local custom_alerts_service_name="${SERVICE_NAME}-custom-alerts"
  local custom_alerts_service_path="/etc/systemd/system/${custom_alerts_service_name}.service"
  local custom_alerts_timer_path="/etc/systemd/system/${custom_alerts_service_name}.timer"
  local custom_alerts_needs_install=false

  if [[ -f "${custom_alerts_service_template}" && -f "${custom_alerts_timer_template}" && "${has_cron_token}" == "true" ]]; then
    if sudo -n "${SYSTEMCTL_BIN}" cat "${custom_alerts_service_name}.timer" >/dev/null 2>&1; then
      if [[ "${force_install_on}" == "true" ]]; then
        log "FORCE_SERVICE_INSTALL enabled; rewriting ${custom_alerts_service_path} + timer."
        custom_alerts_needs_install=true
      else
        log "Custom-alerts timer already installed; skipping."
      fi
    else
      log "Installing custom-alerts service + timer."
      custom_alerts_needs_install=true
    fi

    if [[ "${custom_alerts_needs_install}" == "true" ]]; then
      local tmp_custom_alerts_service tmp_custom_alerts_timer
      tmp_custom_alerts_service="$(mktemp)"
      tmp_custom_alerts_timer="$(mktemp)"
      sed \
        -e "s/__SERVICE_NAME__/$(escape_sed_replacement "${SERVICE_NAME}")/g" \
        -e "s/__APP_USER__/$(escape_sed_replacement "${APP_USER}")/g" \
        -e "s/__APP_DIR__/$(escape_sed_replacement "${APP_DIR}")/g" \
        "${custom_alerts_service_template}" > "${tmp_custom_alerts_service}"
      sed \
        -e "s/__SERVICE_NAME__/$(escape_sed_replacement "${SERVICE_NAME}")/g" \
        "${custom_alerts_timer_template}" > "${tmp_custom_alerts_timer}"
      sudo -n "${INSTALL_BIN}" -m 0644 "${tmp_custom_alerts_service}" "${custom_alerts_service_path}"
      sudo -n "${INSTALL_BIN}" -m 0644 "${tmp_custom_alerts_timer}" "${custom_alerts_timer_path}"
      rm -f "${tmp_custom_alerts_service}" "${tmp_custom_alerts_timer}"
      log "Installed ${custom_alerts_service_name}.service + .timer"
    fi
  fi

  # ── Player-context refresh timer (prod-side producer) ──────────────────
  # Builds data/playerctx/snapshot.json, which GET /api/playerctx/player
  # serves to the player profile card.  MUST run on prod: the endpoint
  # reads a local file and data/ is gitignored, so a CI-built snapshot
  # would never reach the VPS.  Unlike the alert/DLF timers this needs
  # NO credentials (public nflverse assets), so it installs
  # unconditionally whenever both templates are present.
  local playerctx_service_template="${APP_DIR}/deploy/systemd/dynasty-playerctx-refresh.service.template"
  local playerctx_timer_template="${APP_DIR}/deploy/systemd/dynasty-playerctx-refresh.timer.template"
  local playerctx_service_name="${SERVICE_NAME}-playerctx-refresh"
  local playerctx_service_path="/etc/systemd/system/${playerctx_service_name}.service"
  local playerctx_timer_path="/etc/systemd/system/${playerctx_service_name}.timer"
  local playerctx_needs_install=false

  if [[ -f "${playerctx_service_template}" && -f "${playerctx_timer_template}" ]]; then
    if sudo -n "${SYSTEMCTL_BIN}" cat "${playerctx_service_name}.timer" >/dev/null 2>&1; then
      if [[ "${force_install_on}" == "true" ]]; then
        log "FORCE_SERVICE_INSTALL enabled; rewriting ${playerctx_service_path} + timer."
        playerctx_needs_install=true
      else
        log "Player-context timer already installed; skipping."
      fi
    else
      log "Installing player-context refresh service + timer."
      playerctx_needs_install=true
    fi

    if [[ "${playerctx_needs_install}" == "true" ]]; then
      local tmp_playerctx_service tmp_playerctx_timer
      tmp_playerctx_service="$(mktemp)"
      tmp_playerctx_timer="$(mktemp)"
      sed \
        -e "s/__SERVICE_NAME__/$(escape_sed_replacement "${SERVICE_NAME}")/g" \
        -e "s/__APP_USER__/$(escape_sed_replacement "${APP_USER}")/g" \
        -e "s/__APP_DIR__/$(escape_sed_replacement "${APP_DIR}")/g" \
        -e "s/__VENV_DIR__/$(escape_sed_replacement "${VENV_DIR}")/g" \
        "${playerctx_service_template}" > "${tmp_playerctx_service}"
      sed \
        -e "s/__SERVICE_NAME__/$(escape_sed_replacement "${SERVICE_NAME}")/g" \
        "${playerctx_timer_template}" > "${tmp_playerctx_timer}"
      sudo -n "${INSTALL_BIN}" -m 0644 "${tmp_playerctx_service}" "${playerctx_service_path}"
      sudo -n "${INSTALL_BIN}" -m 0644 "${tmp_playerctx_timer}" "${playerctx_timer_path}"
      rm -f "${tmp_playerctx_service}" "${tmp_playerctx_timer}"
      log "Installed ${playerctx_service_name}.service + .timer"
    fi
  fi

  # ── BDVM projection refresh timer (weekly snapshots for /api/bdvm/*) ──
  # Builds data/bdvm/projections/<season>/ snapshots — a LOCAL file the
  # bdvm_engine-flagged endpoints read, so like playerctx the producer
  # must run where the reader lives.  The baseline stage needs NO
  # credentials (public nflverse); the IDP Show stage self-skips when
  # the session jar is absent, so this installs unconditionally
  # whenever both templates are present.  Safe while the flag is OFF:
  # snapshots are the prerequisite for flipping it.
  local bdvm_service_template="${APP_DIR}/deploy/systemd/dynasty-bdvm-refresh.service.template"
  local bdvm_timer_template="${APP_DIR}/deploy/systemd/dynasty-bdvm-refresh.timer.template"
  local bdvm_service_name="${SERVICE_NAME}-bdvm-refresh"
  local bdvm_service_path="/etc/systemd/system/${bdvm_service_name}.service"
  local bdvm_timer_path="/etc/systemd/system/${bdvm_service_name}.timer"
  local bdvm_needs_install=false

  if [[ -f "${bdvm_service_template}" && -f "${bdvm_timer_template}" ]]; then
    if sudo -n "${SYSTEMCTL_BIN}" cat "${bdvm_service_name}.timer" >/dev/null 2>&1; then
      if [[ "${force_install_on}" == "true" ]]; then
        log "FORCE_SERVICE_INSTALL enabled; rewriting ${bdvm_service_path} + timer."
        bdvm_needs_install=true
      else
        log "BDVM-refresh timer already installed; skipping."
      fi
    else
      log "Installing BDVM projection refresh service + timer."
      bdvm_needs_install=true
    fi

  if [[ "${bdvm_needs_install}" == "true" ]]; then
      local tmp_bdvm_service tmp_bdvm_timer
      tmp_bdvm_service="$(mktemp)"
      tmp_bdvm_timer="$(mktemp)"
      sed \
        -e "s/__SERVICE_NAME__/$(escape_sed_replacement "${SERVICE_NAME}")/g" \
        -e "s/__APP_USER__/$(escape_sed_replacement "${APP_USER}")/g" \
        -e "s/__APP_DIR__/$(escape_sed_replacement "${APP_DIR}")/g" \
        -e "s/__VENV_DIR__/$(escape_sed_replacement "${VENV_DIR}")/g" \
        "${bdvm_service_template}" > "${tmp_bdvm_service}"
      sed \
        -e "s/__SERVICE_NAME__/$(escape_sed_replacement "${SERVICE_NAME}")/g" \
        "${bdvm_timer_template}" > "${tmp_bdvm_timer}"
      sudo -n "${INSTALL_BIN}" -m 0644 "${tmp_bdvm_service}" "${bdvm_service_path}"
      sudo -n "${INSTALL_BIN}" -m 0644 "${tmp_bdvm_timer}" "${bdvm_timer_path}"
      rm -f "${tmp_bdvm_service}" "${tmp_bdvm_timer}"
      log "Installed ${bdvm_service_name}.service + .timer"
    fi
  fi

  # ── Consensus Edge daily board snapshot ───────────────────────────────
  # Records what the board said each day, with the model and parameter
  # versions that produced it.  Without it the feature can never answer
  # "what did we say about X on D" and no call can be scored after the
  # fact — the previous implementation had no persistence at all.
  #
  # Installs unconditionally: it needs no credentials, reads the live
  # contract this box already serves, and writes only into gitignored
  # data/.  Safe while the consensus_edge flag is OFF — accumulating
  # history is exactly the prerequisite for turning it on.
  local ce_service_template="${APP_DIR}/deploy/systemd/dynasty-consensus-edge-snapshot.service.template"
  local ce_timer_template="${APP_DIR}/deploy/systemd/dynasty-consensus-edge-snapshot.timer.template"
  local ce_service_name="${SERVICE_NAME}-consensus-edge-snapshot"
  local ce_service_path="/etc/systemd/system/${ce_service_name}.service"
  local ce_timer_path="/etc/systemd/system/${ce_service_name}.timer"
  local ce_needs_install=false

  if [[ -f "${ce_service_template}" && -f "${ce_timer_template}" ]]; then
    if sudo -n "${SYSTEMCTL_BIN}" cat "${ce_service_name}.timer" >/dev/null 2>&1; then
      if [[ "${force_install_on}" == "true" ]]; then
        log "FORCE_SERVICE_INSTALL enabled; rewriting ${ce_service_path} + timer."
        ce_needs_install=true
      else
        log "Consensus Edge snapshot timer already installed; skipping."
      fi
    else
      log "Installing Consensus Edge snapshot service + timer."
      ce_needs_install=true
    fi

    if [[ "${ce_needs_install}" == "true" ]]; then
      local tmp_ce_service tmp_ce_timer
      tmp_ce_service="$(mktemp)"
      tmp_ce_timer="$(mktemp)"
      sed \
        -e "s/__SERVICE_NAME__/$(escape_sed_replacement "${SERVICE_NAME}")/g" \
        -e "s/__APP_USER__/$(escape_sed_replacement "${APP_USER}")/g" \
        -e "s/__APP_DIR__/$(escape_sed_replacement "${APP_DIR}")/g" \
        -e "s/__VENV_DIR__/$(escape_sed_replacement "${VENV_DIR}")/g" \
        "${ce_service_template}" > "${tmp_ce_service}"
      sed \
        -e "s/__SERVICE_NAME__/$(escape_sed_replacement "${SERVICE_NAME}")/g" \
        "${ce_timer_template}" > "${tmp_ce_timer}"
      sudo -n "${INSTALL_BIN}" -m 0644 "${tmp_ce_service}" "${ce_service_path}"
      sudo -n "${INSTALL_BIN}" -m 0644 "${tmp_ce_timer}" "${ce_timer_path}"
      rm -f "${tmp_ce_service}" "${tmp_ce_timer}"
      log "Installed ${ce_service_name}.service + .timer"
    fi
  fi

  # ── Sharp Tracker manager-discovery timer ─────────────────────────────
  # Grows the Sharp Tracker cohort by walking Sleeper outward from the
  # seeds in config/sharp/discovery_seeds.json.  Writes the SQLite
  # ledger under data/intel/ — gitignored, so like playerctx and BDVM
  # the producer must run where the reader lives.  Needs NO credentials
  # (Sleeper's read API is public and unauthenticated), so this installs
  # unconditionally whenever both templates are present.
  #
  # The unit treats exit 2 as success: "budget exhausted with frontier
  # remaining" is the NORMAL steady state on a compounding graph, not a
  # failure — the next run resumes where this one stopped.
  local sharp_service_template="${APP_DIR}/deploy/systemd/dynasty-sharp-discovery.service.template"
  local sharp_timer_template="${APP_DIR}/deploy/systemd/dynasty-sharp-discovery.timer.template"
  local sharp_service_name="${SERVICE_NAME}-sharp-discovery"
  local sharp_service_path="/etc/systemd/system/${sharp_service_name}.service"
  local sharp_timer_path="/etc/systemd/system/${sharp_service_name}.timer"
  local sharp_needs_install=false

  if [[ -f "${sharp_service_template}" && -f "${sharp_timer_template}" ]]; then
    if sudo -n "${SYSTEMCTL_BIN}" cat "${sharp_service_name}.timer" >/dev/null 2>&1; then
      if [[ "${force_install_on}" == "true" ]]; then
        log "FORCE_SERVICE_INSTALL enabled; rewriting ${sharp_service_path} + timer."
        sharp_needs_install=true
      else
        log "Sharp-discovery timer already installed; skipping."
      fi
    else
      log "Installing Sharp Tracker manager-discovery service + timer."
      sharp_needs_install=true
    fi

    if [[ "${sharp_needs_install}" == "true" ]]; then
      local tmp_sharp_service tmp_sharp_timer
      tmp_sharp_service="$(mktemp)"
      tmp_sharp_timer="$(mktemp)"
      sed \
        -e "s/__SERVICE_NAME__/$(escape_sed_replacement "${SERVICE_NAME}")/g" \
        -e "s/__APP_USER__/$(escape_sed_replacement "${APP_USER}")/g" \
        -e "s/__APP_DIR__/$(escape_sed_replacement "${APP_DIR}")/g" \
        -e "s/__VENV_DIR__/$(escape_sed_replacement "${VENV_DIR}")/g" \
        "${sharp_service_template}" > "${tmp_sharp_service}"
      sed \
        -e "s/__SERVICE_NAME__/$(escape_sed_replacement "${SERVICE_NAME}")/g" \
        "${sharp_timer_template}" > "${tmp_sharp_timer}"
      sudo -n "${INSTALL_BIN}" -m 0644 "${tmp_sharp_service}" "${sharp_service_path}"
      sudo -n "${INSTALL_BIN}" -m 0644 "${tmp_sharp_timer}" "${sharp_timer_path}"
      rm -f "${tmp_sharp_service}" "${tmp_sharp_timer}"
      log "Installed ${sharp_service_name}.service + .timer"
    fi
  fi

  # ── Sharp Tracker season-records timer ─────────────────────────────
  # Grows the Sharp Tracker cohort by walking Sleeper outward from the
  # seeds in config/sharp/discovery_seeds.json.  Writes the SQLite
  # ledger under data/intel/ — gitignored, so like playerctx and BDVM
  # the producer must run where the reader lives.  Needs NO credentials
  # (Sleeper's read API is public and unauthenticated), so this installs
  # unconditionally whenever both templates are present.
  #
  # The unit treats exit 2 as success: "budget exhausted with frontier
  # remaining" is the NORMAL steady state on a compounding graph, not a
  # failure — the next run resumes where this one stopped.
  local sharprec_service_template="${APP_DIR}/deploy/systemd/dynasty-sharp-records.service.template"
  local sharprec_timer_template="${APP_DIR}/deploy/systemd/dynasty-sharp-records.timer.template"
  local sharprec_service_name="${SERVICE_NAME}-sharp-records"
  local sharprec_service_path="/etc/systemd/system/${sharprec_service_name}.service"
  local sharprec_timer_path="/etc/systemd/system/${sharprec_service_name}.timer"
  local sharprec_needs_install=false

  if [[ -f "${sharprec_service_template}" && -f "${sharprec_timer_template}" ]]; then
    if sudo -n "${SYSTEMCTL_BIN}" cat "${sharprec_service_name}.timer" >/dev/null 2>&1; then
      if [[ "${force_install_on}" == "true" ]]; then
        log "FORCE_SERVICE_INSTALL enabled; rewriting ${sharprec_service_path} + timer."
        sharprec_needs_install=true
      else
        log "Sharp-records timer already installed; skipping."
      fi
    else
      log "Installing Sharp Tracker season-records service + timer."
      sharprec_needs_install=true
    fi

    if [[ "${sharprec_needs_install}" == "true" ]]; then
      local tmp_sharprec_service tmp_sharprec_timer
      tmp_sharprec_service="$(mktemp)"
      tmp_sharprec_timer="$(mktemp)"
      sed \
        -e "s/__SERVICE_NAME__/$(escape_sed_replacement "${SERVICE_NAME}")/g" \
        -e "s/__APP_USER__/$(escape_sed_replacement "${APP_USER}")/g" \
        -e "s/__APP_DIR__/$(escape_sed_replacement "${APP_DIR}")/g" \
        -e "s/__VENV_DIR__/$(escape_sed_replacement "${VENV_DIR}")/g" \
        "${sharprec_service_template}" > "${tmp_sharprec_service}"
      sed \
        -e "s/__SERVICE_NAME__/$(escape_sed_replacement "${SERVICE_NAME}")/g" \
        "${sharprec_timer_template}" > "${tmp_sharprec_timer}"
      sudo -n "${INSTALL_BIN}" -m 0644 "${tmp_sharprec_service}" "${sharprec_service_path}"
      sudo -n "${INSTALL_BIN}" -m 0644 "${tmp_sharprec_timer}" "${sharprec_timer_path}"
      rm -f "${tmp_sharprec_service}" "${tmp_sharprec_timer}"
      log "Installed ${sharprec_service_name}.service + .timer"
    fi
  fi


  # ── Sharp roster collection timer ───────────────────────────────────
  #
  # The THIRD pass: what the cohort currently OWNS, which is what
  # /market/sharp-roster-percentage is made of. Installed alongside
  # discovery and records because without it that page stays honestly
  # empty forever — there is no other producer of the roster store.
  #
  # Like the records unit, exit 2 ("budget exhausted, leagues
  # remaining") is the normal steady state and is treated as success.
  local sharpros_service_template="${APP_DIR}/deploy/systemd/dynasty-sharp-rosters.service.template"
  local sharpros_timer_template="${APP_DIR}/deploy/systemd/dynasty-sharp-rosters.timer.template"
  local sharpros_service_name="${SERVICE_NAME}-sharp-rosters"
  local sharpros_service_path="/etc/systemd/system/${sharpros_service_name}.service"
  local sharpros_timer_path="/etc/systemd/system/${sharpros_service_name}.timer"
  local sharpros_needs_install=false

  if [[ -f "${sharpros_service_template}" && -f "${sharpros_timer_template}" ]]; then
    if sudo -n "${SYSTEMCTL_BIN}" cat "${sharpros_service_name}.timer" >/dev/null 2>&1; then
      if [[ "${force_install_on}" == "true" ]]; then
        log "FORCE_SERVICE_INSTALL enabled; rewriting ${sharpros_service_path} + timer."
        sharpros_needs_install=true
      else
        log "Sharp-rosters timer already installed; skipping."
      fi
    else
      log "Installing Sharp roster collection service + timer."
      sharpros_needs_install=true
    fi

    if [[ "${sharpros_needs_install}" == "true" ]]; then
      local tmp_sharpros_service tmp_sharpros_timer
      tmp_sharpros_service="$(mktemp)"
      tmp_sharpros_timer="$(mktemp)"
      sed \
        -e "s/__SERVICE_NAME__/$(escape_sed_replacement "${SERVICE_NAME}")/g" \
        -e "s/__APP_USER__/$(escape_sed_replacement "${APP_USER}")/g" \
        -e "s/__APP_DIR__/$(escape_sed_replacement "${APP_DIR}")/g" \
        -e "s/__VENV_DIR__/$(escape_sed_replacement "${VENV_DIR}")/g" \
        "${sharpros_service_template}" > "${tmp_sharpros_service}"
      sed \
        -e "s/__SERVICE_NAME__/$(escape_sed_replacement "${SERVICE_NAME}")/g" \
        "${sharpros_timer_template}" > "${tmp_sharpros_timer}"
      sudo -n "${INSTALL_BIN}" -m 0644 "${tmp_sharpros_service}" "${sharpros_service_path}"
      sudo -n "${INSTALL_BIN}" -m 0644 "${tmp_sharpros_timer}" "${sharpros_timer_path}"
      rm -f "${tmp_sharpros_service}" "${tmp_sharpros_timer}"
      log "Installed ${sharpros_service_name}.service + .timer"
    fi
  fi


  # ── FFPC public Sharp ingestion timer ───────────────────────────────
  local ffpc_service_template="${APP_DIR}/deploy/systemd/dynasty-ffpc-sharp.service.template"
  local ffpc_timer_template="${APP_DIR}/deploy/systemd/dynasty-ffpc-sharp.timer.template"
  local ffpc_service_name="${SERVICE_NAME}-ffpc-sharp"
  local ffpc_service_path="/etc/systemd/system/${ffpc_service_name}.service"
  local ffpc_timer_path="/etc/systemd/system/${ffpc_service_name}.timer"
  local ffpc_needs_install=false
  local ffpc_enabled=false
  if [[ -f "${APP_DIR}/config/sharp/ffpc_sources.json" ]] && \
     grep -m1 -Eq '"enabled"[[:space:]]*:[[:space:]]*true' \
       "${APP_DIR}/config/sharp/ffpc_sources.json"; then
    ffpc_enabled=true
  fi
  if [[ "${ffpc_enabled}" == "true" && -f "${ffpc_service_template}" && -f "${ffpc_timer_template}" ]]; then
    if sudo -n "${SYSTEMCTL_BIN}" cat "${ffpc_service_name}.timer" >/dev/null 2>&1; then
      if [[ "${force_install_on}" == "true" ]]; then
        ffpc_needs_install=true
      fi
    else
      log "Installing FFPC public Sharp ingestion service + timer."
      ffpc_needs_install=true
    fi
    if [[ "${ffpc_needs_install}" == "true" ]]; then
      local tmp_ffpc_service tmp_ffpc_timer
      tmp_ffpc_service="$(mktemp)"
      tmp_ffpc_timer="$(mktemp)"
      sed \
        -e "s/__SERVICE_NAME__/$(escape_sed_replacement "${SERVICE_NAME}")/g" \
        -e "s/__APP_USER__/$(escape_sed_replacement "${APP_USER}")/g" \
        -e "s/__APP_DIR__/$(escape_sed_replacement "${APP_DIR}")/g" \
        -e "s/__VENV_DIR__/$(escape_sed_replacement "${VENV_DIR}")/g" \
        "${ffpc_service_template}" > "${tmp_ffpc_service}"
      sed \
        -e "s/__SERVICE_NAME__/$(escape_sed_replacement "${SERVICE_NAME}")/g" \
        "${ffpc_timer_template}" > "${tmp_ffpc_timer}"
      sudo -n "${INSTALL_BIN}" -m 0644 "${tmp_ffpc_service}" "${ffpc_service_path}"
      sudo -n "${INSTALL_BIN}" -m 0644 "${tmp_ffpc_timer}" "${ffpc_timer_path}"
      rm -f "${tmp_ffpc_service}" "${tmp_ffpc_timer}"
      log "Installed ${ffpc_service_name}.service + .timer"
    fi
  fi

  # ── Reception-depth histogram timer ───────────────────────────────────
  # Streams nflverse play-by-play into per-player reception-band
  # histograms.  Like playerctx and BDVM the readers load a LOCAL file
  # and data/ is gitignored, so the producer must run where the reader
  # lives.  Needs no credentials (public nflverse), so this installs
  # unconditionally whenever both templates are present.
  #
  # The unit treats exit 2 as success: "the current season has not
  # kicked off" is the normal state from March to August, and a unit
  # sitting red for half the year is a unit nobody reads.
  local rd_service_template="${APP_DIR}/deploy/systemd/dynasty-reception-depth.service.template"
  local rd_timer_template="${APP_DIR}/deploy/systemd/dynasty-reception-depth.timer.template"
  local rd_service_name="${SERVICE_NAME}-reception-depth"
  local rd_service_path="/etc/systemd/system/${rd_service_name}.service"
  local rd_timer_path="/etc/systemd/system/${rd_service_name}.timer"
  local rd_needs_install=false

  if [[ -f "${rd_service_template}" && -f "${rd_timer_template}" ]]; then
    if sudo -n "${SYSTEMCTL_BIN}" cat "${rd_service_name}.timer" >/dev/null 2>&1; then
      if [[ "${force_install_on}" == "true" ]]; then
        log "FORCE_SERVICE_INSTALL enabled; rewriting ${rd_service_path} + timer."
        rd_needs_install=true
      else
        log "Reception-depth timer already installed; skipping."
      fi
    else
      log "Installing reception-depth refresh service + timer."
      rd_needs_install=true
    fi

    if [[ "${rd_needs_install}" == "true" ]]; then
      local tmp_rd_service tmp_rd_timer
      tmp_rd_service="$(mktemp)"
      tmp_rd_timer="$(mktemp)"
      sed \
        -e "s/__SERVICE_NAME__/$(escape_sed_replacement "${SERVICE_NAME}")/g" \
        -e "s/__APP_USER__/$(escape_sed_replacement "${APP_USER}")/g" \
        -e "s/__APP_DIR__/$(escape_sed_replacement "${APP_DIR}")/g" \
        -e "s/__VENV_DIR__/$(escape_sed_replacement "${VENV_DIR}")/g" \
        "${rd_service_template}" > "${tmp_rd_service}"
      sed \
        -e "s/__SERVICE_NAME__/$(escape_sed_replacement "${SERVICE_NAME}")/g" \
        "${rd_timer_template}" > "${tmp_rd_timer}"
      sudo -n "${INSTALL_BIN}" -m 0644 "${tmp_rd_service}" "${rd_service_path}"
      sudo -n "${INSTALL_BIN}" -m 0644 "${tmp_rd_timer}" "${rd_timer_path}"
      rm -f "${tmp_rd_service}" "${tmp_rd_timer}"
      log "Installed ${rd_service_name}.service + .timer"
    fi
  fi

  # ── DLF fetch timer (prod-side replacement for CI fetch_dlf.py) ────────
  # CI cannot run scripts/fetch_dlf.py — Cloudflare 403s the GitHub
  # Actions runner IPs.  The same script succeeds from prod, so this
  # timer fires every 2h on prod, runs the fetch in a dedicated
  # /var/lib/dlf-fetch/repo clone, and pushes the four DLF CSVs +
  # data/scrape_state/dlf_last_success back to main.  Install only
  # when the credentials are present in .env.
  local dlf_fetch_service_template="${APP_DIR}/deploy/systemd/dynasty-dlf-fetch.service.template"
  local dlf_fetch_timer_template="${APP_DIR}/deploy/systemd/dynasty-dlf-fetch.timer.template"
  local dlf_fetch_service_name="${SERVICE_NAME}-dlf-fetch"
  local dlf_fetch_service_path="/etc/systemd/system/${dlf_fetch_service_name}.service"
  local dlf_fetch_timer_path="/etc/systemd/system/${dlf_fetch_service_name}.timer"
  local dlf_fetch_needs_install=false
  local has_dlf_creds=false

  if [[ -f "${APP_DIR}/.env" ]] \
     && grep -Eq '^[[:space:]]*DLF_USERNAME=.+$' "${APP_DIR}/.env" \
     && grep -Eq '^[[:space:]]*DLF_PASSWORD=.+$' "${APP_DIR}/.env"; then
    has_dlf_creds=true
  fi

  if [[ -f "${dlf_fetch_service_template}" && -f "${dlf_fetch_timer_template}" && "${has_dlf_creds}" == "true" ]]; then
    if sudo -n "${SYSTEMCTL_BIN}" cat "${dlf_fetch_service_name}.timer" >/dev/null 2>&1; then
      if [[ "${force_install_on}" == "true" ]]; then
        log "FORCE_SERVICE_INSTALL enabled; rewriting ${dlf_fetch_service_path} + timer."
        dlf_fetch_needs_install=true
      else
        log "DLF-fetch timer already installed; skipping."
      fi
    else
      log "Installing DLF-fetch service + timer."
      dlf_fetch_needs_install=true
    fi

    if [[ "${dlf_fetch_needs_install}" == "true" ]]; then
      local tmp_dlf_service tmp_dlf_timer
      tmp_dlf_service="$(mktemp)"
      tmp_dlf_timer="$(mktemp)"
      sed \
        -e "s/__SERVICE_NAME__/$(escape_sed_replacement "${SERVICE_NAME}")/g" \
        -e "s/__APP_USER__/$(escape_sed_replacement "${APP_USER}")/g" \
        -e "s/__APP_DIR__/$(escape_sed_replacement "${APP_DIR}")/g" \
        "${dlf_fetch_service_template}" > "${tmp_dlf_service}"
      sed \
        -e "s/__SERVICE_NAME__/$(escape_sed_replacement "${SERVICE_NAME}")/g" \
        "${dlf_fetch_timer_template}" > "${tmp_dlf_timer}"
      sudo -n "${INSTALL_BIN}" -m 0644 "${tmp_dlf_service}" "${dlf_fetch_service_path}"
      sudo -n "${INSTALL_BIN}" -m 0644 "${tmp_dlf_timer}" "${dlf_fetch_timer_path}"
      rm -f "${tmp_dlf_service}" "${tmp_dlf_timer}"
      log "Installed ${dlf_fetch_service_name}.service + .timer"

      # Provision the work-dir and seed the cookie cache from the live
      # repo's session file (gitignored, so this is the only place the
      # cached cookies live on prod).  Idempotent: the script also
      # creates the dir if missing, but doing it here means the first
      # timer fire doesn't have to do an unnecessary full WP login.
      sudo -n "${INSTALL_BIN}" -d -m 0755 -o "${APP_USER}" -g "${APP_USER}" /var/lib/dlf-fetch
      if [[ -f "${APP_DIR}/dlf_session.json" && ! -f /var/lib/dlf-fetch/dlf_session.json ]]; then
        sudo -n "${INSTALL_BIN}" -m 0600 -o "${APP_USER}" -g "${APP_USER}" \
          "${APP_DIR}/dlf_session.json" /var/lib/dlf-fetch/dlf_session.json
        log "Seeded /var/lib/dlf-fetch/dlf_session.json from live repo."
      fi
    fi
  elif [[ -f "${dlf_fetch_service_template}" && "${has_dlf_creds}" != "true" ]]; then
    log "DLF-fetch timer skipped: DLF_USERNAME / DLF_PASSWORD not set in ${APP_DIR}/.env."
  fi

  # ── IDP Show fetch timer (prod-side replacement for CI fetch_idpshow.py) ──
  # Substack paywall + CAPTCHA-protected login means CI cannot
  # re-authenticate.  Same prod-timer pattern as DLF; gate on the
  # presence of idpshow_session.json (the operator-minted cookie jar)
  # in the live repo - without it, the fetcher has no auth.
  local idpshow_fetch_service_template="${APP_DIR}/deploy/systemd/dynasty-idpshow-fetch.service.template"
  local idpshow_fetch_timer_template="${APP_DIR}/deploy/systemd/dynasty-idpshow-fetch.timer.template"
  local idpshow_fetch_service_name="${SERVICE_NAME}-idpshow-fetch"
  local idpshow_fetch_service_path="/etc/systemd/system/${idpshow_fetch_service_name}.service"
  local idpshow_fetch_timer_path="/etc/systemd/system/${idpshow_fetch_service_name}.timer"
  local idpshow_fetch_needs_install=false
  local has_idpshow_session=false

  if [[ -f "${APP_DIR}/idpshow_session.json" ]]; then
    has_idpshow_session=true
  fi

  if [[ -f "${idpshow_fetch_service_template}" && -f "${idpshow_fetch_timer_template}" && "${has_idpshow_session}" == "true" ]]; then
    if sudo -n "${SYSTEMCTL_BIN}" cat "${idpshow_fetch_service_name}.timer" >/dev/null 2>&1; then
      if [[ "${force_install_on}" == "true" ]]; then
        log "FORCE_SERVICE_INSTALL enabled; rewriting ${idpshow_fetch_service_path} + timer."
        idpshow_fetch_needs_install=true
      else
        log "IDP Show fetch timer already installed; skipping."
      fi
    else
      log "Installing IDP Show fetch service + timer."
      idpshow_fetch_needs_install=true
    fi

    if [[ "${idpshow_fetch_needs_install}" == "true" ]]; then
      local tmp_idpshow_service tmp_idpshow_timer
      tmp_idpshow_service="$(mktemp)"
      tmp_idpshow_timer="$(mktemp)"
      sed \
        -e "s/__SERVICE_NAME__/$(escape_sed_replacement "${SERVICE_NAME}")/g" \
        -e "s/__APP_USER__/$(escape_sed_replacement "${APP_USER}")/g" \
        -e "s/__APP_DIR__/$(escape_sed_replacement "${APP_DIR}")/g" \
        "${idpshow_fetch_service_template}" > "${tmp_idpshow_service}"
      sed \
        -e "s/__SERVICE_NAME__/$(escape_sed_replacement "${SERVICE_NAME}")/g" \
        "${idpshow_fetch_timer_template}" > "${tmp_idpshow_timer}"
      sudo -n "${INSTALL_BIN}" -m 0644 "${tmp_idpshow_service}" "${idpshow_fetch_service_path}"
      sudo -n "${INSTALL_BIN}" -m 0644 "${tmp_idpshow_timer}" "${idpshow_fetch_timer_path}"
      rm -f "${tmp_idpshow_service}" "${tmp_idpshow_timer}"
      log "Installed ${idpshow_fetch_service_name}.service + .timer"

      sudo -n "${INSTALL_BIN}" -d -m 0755 -o "${APP_USER}" -g "${APP_USER}" /var/lib/idpshow-fetch
      if [[ ! -f /var/lib/idpshow-fetch/idpshow_session.json ]]; then
        sudo -n "${INSTALL_BIN}" -m 0600 -o "${APP_USER}" -g "${APP_USER}" \
          "${APP_DIR}/idpshow_session.json" /var/lib/idpshow-fetch/idpshow_session.json
        log "Seeded /var/lib/idpshow-fetch/idpshow_session.json from live repo."
      fi
    fi
  elif [[ -f "${idpshow_fetch_service_template}" && "${has_idpshow_session}" != "true" ]]; then
    log "IDP Show fetch timer skipped: ${APP_DIR}/idpshow_session.json missing - operator must mint it via browser first."
  fi

  # ── daemon-reload and enable ────────────────────────────────────────────
  if [[ "${backend_needs_install}" == "true" || "${frontend_needs_install}" == "true" || "${alerts_needs_install}" == "true" || "${custom_alerts_needs_install}" == "true" || "${playerctx_needs_install}" == "true" || "${bdvm_needs_install}" == "true" || "${sharp_needs_install}" == "true" || "${sharprec_needs_install}" == "true" || "${ffpc_needs_install}" == "true" || "${rd_needs_install}" == "true" || "${dlf_fetch_needs_install}" == "true" || "${idpshow_fetch_needs_install}" == "true" ]]; then
    sudo -n "${SYSTEMCTL_BIN}" daemon-reload
    log "Reloaded systemd unit files."
  fi

  if [[ "${backend_needs_install}" == "true" ]]; then
    sudo -n "${SYSTEMCTL_BIN}" enable "${SERVICE_NAME}"
    log "Enabled ${SERVICE_NAME}.service"
  fi
  if [[ "${frontend_needs_install}" == "true" ]]; then
    sudo -n "${SYSTEMCTL_BIN}" enable "${frontend_name}"
    log "Enabled ${frontend_name}.service"
  fi
  if [[ "${alerts_needs_install}" == "true" ]]; then
    sudo -n "${SYSTEMCTL_BIN}" enable --now "${alerts_service_name}.timer"
    log "Enabled ${alerts_service_name}.timer"
  fi
  if [[ "${custom_alerts_needs_install}" == "true" ]]; then
    sudo -n "${SYSTEMCTL_BIN}" enable --now "${custom_alerts_service_name}.timer"
    log "Enabled ${custom_alerts_service_name}.timer"
  fi
  if [[ "${playerctx_needs_install}" == "true" ]]; then
    # --now arms the timer immediately; the FIRST snapshot is built by
    # the explicit kick below rather than waiting for Tuesday, so the
    # profile card's context section isn't dark until then.
    sudo -n "${SYSTEMCTL_BIN}" enable --now "${playerctx_service_name}.timer"
    log "Enabled ${playerctx_service_name}.timer"
    if [[ ! -s "${APP_DIR}/data/playerctx/snapshot.json" ]]; then
      log "No player-context snapshot yet — kicking an initial build in the background."
      # --no-block: a ~3 min download must never stall the deploy.
      sudo -n "${SYSTEMCTL_BIN}" start --no-block "${playerctx_service_name}.service" || \
        log "Note: initial player-context build could not be started; the timer will cover it."
    fi
  fi
  if [[ "${ce_needs_install}" == "true" ]]; then
    # --now arms the daily timer, plus one immediate kick so the history
    # starts accumulating on deploy day rather than on the first 07:30.
    # Every day missed is a day that can never be backfilled — the board
    # is only reproducible from a contract that still exists.
    sudo -n "${SYSTEMCTL_BIN}" enable --now "${ce_service_name}.timer"
    log "Enabled ${ce_service_name}.timer"
    sudo -n "${SYSTEMCTL_BIN}" start --no-block "${ce_service_name}.service" || \
      log "Note: initial Consensus Edge snapshot could not be started; the timer will cover it."
  fi
  if [[ "${rd_needs_install}" == "true" ]]; then
    # --now arms the timer.  No initial kick here: the histograms for
    # completed seasons are either already on disk or will be built by
    # the first Wednesday run, and streaming three ~98 MB CSVs during a
    # deploy would stall it for no gain.  The script skips seasons it
    # already has, so that first run is cheap.
    sudo -n "${SYSTEMCTL_BIN}" enable --now "${rd_service_name}.timer"
    log "Enabled ${rd_service_name}.timer"
  fi
  if [[ "${sharp_needs_install}" == "true" ]]; then
    # --now arms the daily timer, plus one immediate --no-block kick so
    # the graph starts compounding on deploy day rather than sitting
    # empty until 04:20.  The crawl is budgeted and resumable, so this
    # first run cannot stall the deploy: it stops at its call cap and
    # leaves a frontier for tomorrow.
    sudo -n "${SYSTEMCTL_BIN}" enable --now "${sharp_service_name}.timer"
    log "Enabled ${sharp_service_name}.timer"
    sudo -n "${SYSTEMCTL_BIN}" start --no-block "${sharp_service_name}.service" || \
      log "Note: initial sharp-discovery crawl could not be started; the timer will cover it."
  fi
  if [[ -f "${sharprec_service_template}" && -f "${sharprec_timer_template}" ]]; then
    sudo -n "${SYSTEMCTL_BIN}" enable --now "${sharprec_service_name}.timer"
    log "Enabled ${sharprec_service_name}.timer"
    sudo -n "${SYSTEMCTL_BIN}" start --no-block "${sharprec_service_name}.service" || \
      log "Note: initial sharp-records crawl could not be started; the timer will cover it."
  fi
  if [[ -f "${sharpros_service_template}" && -f "${sharpros_timer_template}" ]]; then
    # --now arms the daily timer. No initial kick: this pass collects
    # for the cohort that discovery and records produce, and on a fresh
    # deploy those two have not finished yet — an immediate run would
    # collect for an empty cohort and log a misleading zero. The 30-min
    # OnActiveSec in the timer covers deploy day.
    sudo -n "${SYSTEMCTL_BIN}" enable --now "${sharpros_service_name}.timer"
    log "Enabled ${sharpros_service_name}.timer"
  fi
  if [[ "${ffpc_enabled}" == "true" && -f "${ffpc_service_template}" && -f "${ffpc_timer_template}" ]]; then
    sudo -n "${SYSTEMCTL_BIN}" enable --now "${ffpc_service_name}.timer"
    log "Enabled ${ffpc_service_name}.timer"
    sudo -n "${SYSTEMCTL_BIN}" start --no-block "${ffpc_service_name}.service" || \
      log "Note: initial FFPC public crawl could not be started; the timer will cover it."
  fi
  if [[ "${bdvm_needs_install}" == "true" ]]; then
    # --now arms the timer immediately; the FIRST snapshots are built
    # by the explicit kick below rather than waiting for Tuesday, so
    # /api/bdvm/values has data the moment the flag is flipped.
    sudo -n "${SYSTEMCTL_BIN}" enable --now "${bdvm_service_name}.timer"
    log "Enabled ${bdvm_service_name}.timer"
    if ! ls "${APP_DIR}"/data/bdvm/projections/*/projections_*.json >/dev/null 2>&1; then
      log "No BDVM projection snapshot yet — kicking an initial build in the background."
      # --no-block: multi-minute nflverse downloads must never stall the deploy.
      sudo -n "${SYSTEMCTL_BIN}" start --no-block "${bdvm_service_name}.service" || \
        log "Note: initial BDVM snapshot build could not be started; the timer will cover it."
    fi
  fi
  if [[ "${dlf_fetch_needs_install}" == "true" ]]; then
    sudo -n "${SYSTEMCTL_BIN}" enable --now "${dlf_fetch_service_name}.timer"
    log "Enabled ${dlf_fetch_service_name}.timer"
  fi
  if [[ "${idpshow_fetch_needs_install}" == "true" ]]; then
    sudo -n "${SYSTEMCTL_BIN}" enable --now "${idpshow_fetch_service_name}.timer"
    log "Enabled ${idpshow_fetch_service_name}.timer"
  fi

  # ── Backup timer + restore-test timer + logrotate (2026-04-25) ──
  # Idempotent: copies from deploy/systemd/ if not already installed.
  # Units hardcode paths to /home/dynasty/trade-calculator so they
  # don't need template rendering.  Safe to re-run on every deploy;
  # `cp` + `install` overwrites with an identical file when the
  # source is unchanged.  Enabling is idempotent too.
  local any_backup_installed=false
  for unit in riskit-backup.service riskit-backup.timer \
              riskit-backup-restore-test.service riskit-backup-restore-test.timer; do
    local src="${APP_DIR}/deploy/systemd/${unit}"
    local dst="/etc/systemd/system/${unit}"
    if [[ ! -f "${src}" ]]; then
      continue
    fi
    # Only reinstall when the target is missing OR content differs —
    # keeps daemon-reload churn to a minimum.
    if [[ ! -f "${dst}" ]] || ! sudo -n cmp -s "${src}" "${dst}" 2>/dev/null; then
      sudo -n "${INSTALL_BIN}" -m 0644 "${src}" "${dst}"
      log "Installed ${unit}"
      any_backup_installed=true
    fi
  done

  if [[ "${any_backup_installed}" == "true" ]]; then
    sudo -n "${SYSTEMCTL_BIN}" daemon-reload
    log "Reloaded systemd unit files (backup timers)."
  fi

  # Enable timers — safe to re-run; --now starts them if inactive.
  for timer in riskit-backup.timer riskit-backup-restore-test.timer; do
    local timer_path="/etc/systemd/system/${timer}"
    if [[ -f "${timer_path}" ]]; then
      if ! sudo -n "${SYSTEMCTL_BIN}" is-enabled "${timer}" >/dev/null 2>&1; then
        sudo -n "${SYSTEMCTL_BIN}" enable --now "${timer}" >/dev/null 2>&1 || \
          log "Note: enable ${timer} skipped (likely no systemd user unit perms)."
        log "Enabled ${timer}"
      fi
    fi
  done

  # Logrotate config — copy into /etc/logrotate.d/ if changed.
  local logrotate_src="${APP_DIR}/deploy/logrotate.conf"
  local logrotate_dst="/etc/logrotate.d/riskit"
  if [[ -f "${logrotate_src}" ]]; then
    if [[ ! -f "${logrotate_dst}" ]] || ! sudo -n cmp -s "${logrotate_src}" "${logrotate_dst}" 2>/dev/null; then
      sudo -n "${INSTALL_BIN}" -m 0644 "${logrotate_src}" "${logrotate_dst}"
      log "Installed /etc/logrotate.d/riskit"
    fi
  fi
}

main "$@"
