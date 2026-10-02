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
CHOWN_BIN=""

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

# Does the INSTALLED file already carry exactly the rendered content?
#
# UNPRIVILEGED on purpose.  The box user's NOPASSWD surface is exactly
# systemctl, journalctl, install and chown — `cmp` is NOT in it, so
# `sudo -n cmp` is refused with "a password is required"
# (deploy/reconcile-runtime-controls.sh documents the same allowlist and
# compares without sudo for the same reason).  The refusal used to be
# read as drift, so EVERY deploy rewrote and daemon-reloaded every unit
# compared this way and re-fired each one's initial kick — measured on
# deploy run 36881631608 as `sudo: a password is required` followed by
# "<unit> differs from its template; updating." for ~16 units.
#
# Nothing needs privilege here: units are installed 0644 and logrotate
# configs are world-readable, so an ordinary read is sufficient and is the
# truer check (it sees what systemd sees).  A missing or unreadable target
# makes `cmp` exit 2, which still counts as drift — reinstalling a correct
# file is harmless, skipping a changed one is the silent failure.
installed_matches() {
  local rendered="$1" installed="$2"
  cmp -s "${rendered}" "${installed}" 2>/dev/null && return 0
  if [[ -e "${installed}" && ! -r "${installed}" ]]; then
    log "Note: ${installed} is not readable as $(id -un); treating it as drifted."
  fi
  return 1
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

# ── Timer unit reconciliation (the ONE renderer for dynasty-* timers) ────
# `reconcile_timer_units` renders one timer's service + timer templates,
# compares them with what is installed, and rewrites both only on a real
# difference.  It is the single place this installer turns a timer
# template into a unit file.  Two callers:
#
#   * `install_simple_timer` (below) — render, reconcile, enable.  For any
#     timer whose install is nothing more than that.
#   * the dedicated per-timer blocks in main() — timers with real special
#     cases (credential gating, an initial kick, a /var/lib seed, an
#     ownership migration).  They keep their gate and their post-install
#     steps, and delegate ONLY the render/compare/write here.
#
# Why the dedicated blocks delegate (2026-10-01).  Each used to ask "does
# the timer exist?" and, when it did, log "already installed; skipping"
# unless FORCE_SERVICE_INSTALL was set — so EDITING THE TEMPLATE HAD NO
# EFFECT ON THE BOX, the same hole this helper was written to close for
# the simple timers.  Measured on production 2026-10-01, rendering every
# template and comparing it with /etc/systemd/system found two units
# frozen at their first-install content:
#
#   * dynasty-bdvm-refresh.service lacked the stage-0
#     `refresh_bdvm_inputs.py` ExecStart added on 2026-08-20, so the BDVM
#     player context had never been materialised and /api/bdvm/* ran on
#     neutral priors;
#   * dynasty-consensus-edge-snapshot.service lacked User=/Group=,
#     EnvironmentFile and journal output — it ran as root and left a
#     root-owned data/consensus_edge.sqlite the API cannot open read-write.
#
# Both deploys had reported success.
#
# Result: sets TIMER_UNITS_WRITTEN=true when it wrote the unit files (new
# install, FORCE_SERVICE_INSTALL, or content drift), false otherwise.  A
# global rather than an exit status, because every caller runs under
# `set -e` and a non-zero "nothing to do" would abort the install.
TIMER_UNITS_WRITTEN=false

reconcile_timer_units() {
  local stem="$1" label="$2"
  local service_template="${APP_DIR}/deploy/systemd/dynasty-${stem}.service.template"
  local timer_template="${APP_DIR}/deploy/systemd/dynasty-${stem}.timer.template"
  local unit_name="${SERVICE_NAME}-${stem}"
  local service_path="/etc/systemd/system/${unit_name}.service"
  local timer_path="/etc/systemd/system/${unit_name}.timer"

  TIMER_UNITS_WRITTEN=false
  [[ -f "${service_template}" && -f "${timer_template}" ]] || return 0

  # RENDER FIRST, THEN DECIDE. The old order asked "does a unit exist?"
  # and, if it did, changed nothing without FORCE_SERVICE_INSTALL — so
  # EDITING A TEMPLATE HAD NO EFFECT ON THE BOX. The unit stayed at
  # whatever content it was first installed with, the deploy reported
  # success, and nothing said otherwise.
  #
  # That is not hypothetical. #1263 moved this feature's timer off a
  # Thursday-only schedule because Week 1 of 2026 opens on a Wednesday
  # and the old schedule fired ~13 hours after kickoff. Merging and
  # deploying it would have left the WRONG schedule running and lost the
  # observation anyway — a fix that ships and does not take effect is
  # indistinguishable from no fix.
  local tmp_service tmp_timer
  tmp_service="$(mktemp)"
  tmp_timer="$(mktemp)"
  sed \
    -e "s/__SERVICE_NAME__/$(escape_sed_replacement "${SERVICE_NAME}")/g" \
    -e "s/__APP_USER__/$(escape_sed_replacement "${APP_USER}")/g" \
    -e "s/__APP_DIR__/$(escape_sed_replacement "${APP_DIR}")/g" \
    -e "s/__VENV_DIR__/$(escape_sed_replacement "${VENV_DIR}")/g" \
    "${service_template}" > "${tmp_service}"
  sed \
    -e "s/__SERVICE_NAME__/$(escape_sed_replacement "${SERVICE_NAME}")/g" \
    "${timer_template}" > "${tmp_timer}"

  local needs_install=false
  if sudo -n "${SYSTEMCTL_BIN}" cat "${unit_name}.timer" >/dev/null 2>&1; then
    if [[ "${force_install_on}" == "true" ]]; then
      log "FORCE_SERVICE_INSTALL enabled; rewriting ${service_path} + timer."
      needs_install=true
    # Content drift, compared WITHOUT sudo — see installed_matches for
    # why `sudo -n cmp` is refused on the box and what that used to cost.
    # A missing or unreadable target still counts as drift.
    elif ! installed_matches "${tmp_timer}" "${timer_path}" \
      || ! installed_matches "${tmp_service}" "${service_path}"; then
      log "${unit_name} differs from its template; updating."
      needs_install=true
    else
      log "${unit_name} already installed and current."
    fi
  else
    log "Installing ${label} service + timer."
    needs_install=true
  fi

  if [[ "${needs_install}" == "true" ]]; then
    sudo -n "${INSTALL_BIN}" -m 0644 "${tmp_service}" "${service_path}"
    sudo -n "${INSTALL_BIN}" -m 0644 "${tmp_timer}" "${timer_path}"
    # Reload here rather than relying only on the shared reload in main():
    # enabling a unit systemd has not re-read is the ce_needs_install
    # failure — the fix deployed, reported as deployed, and not running.
    sudo -n "${SYSTEMCTL_BIN}" daemon-reload
    log "Installed ${unit_name}.service + .timer"
    TIMER_UNITS_WRITTEN=true
  fi
  rm -f "${tmp_service}" "${tmp_timer}"
}

# ── Generic timer installer ─────────────────────────────────────────────
# Every timer below main()'s backend/frontend sections used to be a
# hand-written block, and each new one is another chance to forget a block
# entirely.  Three had been forgotten by 2026-08-05: crowd-faab,
# sharp-activity and board-snapshot all shipped BOTH templates while
# nothing installed them, so their producers never ran on prod and every
# deploy still reported success.  Same shape as the 2026-07-30 finding one
# screen down, where nine timer pairs shipped and two were installed.
#
# Worse than "does not run": deploy.sh's missing-timer detector globs the
# SAME directory to decide whether to invoke this script, so an unwired
# template is reported missing on EVERY deploy, which runs this installer
# to fix it, which does not install it.  A permanent loop, silent because
# it only warns.
#
# This helper covers any timer whose install is just "render the two
# templates, enable it".  Timers with real special cases — credential
# gating, an initial kick, a /var/lib seed — keep their dedicated blocks,
# which share `reconcile_timer_units` above for the unit files themselves.
# `tests/deploy/test_all_timers_are_wired.py` asserts every shipped
# template is reached by one route or the other, so the next timer added
# cannot go missing quietly.
install_simple_timer() {
  local stem="$1" label="$2"
  local service_template="${APP_DIR}/deploy/systemd/dynasty-${stem}.service.template"
  local timer_template="${APP_DIR}/deploy/systemd/dynasty-${stem}.timer.template"
  local unit_name="${SERVICE_NAME}-${stem}"

  [[ -f "${service_template}" && -f "${timer_template}" ]] || return 0

  reconcile_timer_units "${stem}" "${label}"

  # Enablement is checked SEPARATELY, and not only when we just wrote the
  # files.  deploy.sh's detector treats installed-but-disabled as missing,
  # so a unit that reached disk without being enabled produces the same
  # permanent loop as one that never reached disk at all.
  if ! sudo -n "${SYSTEMCTL_BIN}" is-enabled "${unit_name}.timer" >/dev/null 2>&1; then
    if sudo -n "${SYSTEMCTL_BIN}" enable --now "${unit_name}.timer" >/dev/null 2>&1; then
      log "Enabled ${unit_name}.timer"
    else
      log "Note: could not enable ${unit_name}.timer."
    fi
  fi
}

# ── Consensus Edge store ownership migration ────────────────────────────
# The consensus-edge snapshot unit ran as root until its installed unit
# was brought current (see reconcile_timer_units), so on a box that ran it
# the store and its SQLite sidecars are root:root.  Once the unit runs as
# APP_USER it cannot write them — and snapshot.connect() opens read-write,
# so neither can the API.  Hand exactly these three files to APP_USER.
#
# Idempotent: a file already owned by APP_USER:APP_USER is left alone, so
# an up-to-date box makes no sudo call at all.  Never deletes, never
# creates, never follows a symlink, never touches any other path.  A
# failed chown is LOUD but not fatal: consensus_edge is flag-OFF, and
# failing a production deploy over a dormant feature's store would trade a
# contained defect for an outage.  The unit's own failure in the journal
# then names the same problem.
migrate_consensus_edge_store_ownership() {
  local store="${APP_DIR}/data/consensus_edge.sqlite"
  local path owner
  for path in "${store}" "${store}-wal" "${store}-shm"; do
    [[ -e "${path}" || -L "${path}" ]] || continue
    if [[ -L "${path}" || ! -f "${path}" ]]; then
      error "Consensus Edge store: ${path} is not a regular file; ownership left unchanged."
      continue
    fi
    owner="$(stat -c '%U:%G' "${path}" 2>/dev/null || true)"
    if [[ "${owner}" == "${APP_USER}:${APP_USER}" ]]; then
      continue
    fi
    # By ABSOLUTE path, resolved the way deploy.sh / rollback.sh do it:
    # the NOPASSWD rule names a binary, not a PATH lookup.  Resolved
    # lazily (an up-to-date box never reaches here) and non-fatally —
    # the same "loud, not an outage" posture as a failed chown below.
    if [[ -z "${CHOWN_BIN}" ]]; then
      CHOWN_BIN="$(resolve_sudo_nopasswd_binary "chown" /bin/chown /usr/bin/chown)" || CHOWN_BIN=""
    fi
    if [[ -n "${CHOWN_BIN}" ]] && sudo -n "${CHOWN_BIN}" "${APP_USER}:${APP_USER}" "${path}"; then
      log "Consensus Edge store: ${path} ${owner:-<unreadable owner>} -> ${APP_USER}:${APP_USER}."
    else
      error "Consensus Edge store: could not chown ${path} to ${APP_USER}:${APP_USER}; the snapshot unit (running as ${APP_USER}) will fail to write it."
    fi
  done
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
  local alerts_needs_install=false
  local has_cron_token=false

  if [[ -f "${APP_DIR}/.env" ]] && grep -Eq '^[[:space:]]*SIGNAL_ALERT_CRON_TOKEN=.+$' "${APP_DIR}/.env"; then
    has_cron_token=true
  fi

  # Gate unchanged; the unit files go through the shared drift-aware
  # renderer so a template edit reaches the box (reconcile_timer_units).
  if [[ -f "${alerts_service_template}" && -f "${alerts_timer_template}" && "${has_cron_token}" == "true" ]]; then
    reconcile_timer_units "signal-alerts" "signal-alerts"
    alerts_needs_install="${TIMER_UNITS_WRITTEN}"
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
  local custom_alerts_needs_install=false

  if [[ -f "${custom_alerts_service_template}" && -f "${custom_alerts_timer_template}" && "${has_cron_token}" == "true" ]]; then
    reconcile_timer_units "custom-alerts" "custom-alerts"
    custom_alerts_needs_install="${TIMER_UNITS_WRITTEN}"
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
    # Render FIRST, then decide.  Every sibling block here gates on
    # "does the timer exist" alone, which means a template edit is
    # silently ignored on an already-provisioned box until someone
    # remembers FORCE_SERVICE_INSTALL — the same class of failure the
    # reload-and-enable block below documents, one step earlier: the
    # change is deployed, reported as deployed, and not running.  That
    # bit for real when --retain-history was added to the ExecStart, so
    # this block compares CONTENT the way the backup-unit loop at the
    # bottom of this function already does.
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

    if sudo -n "${SYSTEMCTL_BIN}" cat "${playerctx_service_name}.timer" >/dev/null 2>&1; then
      if [[ "${force_install_on}" == "true" ]]; then
        log "FORCE_SERVICE_INSTALL enabled; rewriting ${playerctx_service_path} + timer."
        playerctx_needs_install=true
      elif ! installed_matches "${tmp_playerctx_service}" "${playerctx_service_path}" \
        || ! installed_matches "${tmp_playerctx_timer}" "${playerctx_timer_path}"; then
        log "Player-context unit files changed; rewriting ${playerctx_service_path} + timer."
        playerctx_needs_install=true
      else
        log "Player-context timer already installed and current; skipping."
      fi
    else
      log "Installing player-context refresh service + timer."
      playerctx_needs_install=true
    fi

    if [[ "${playerctx_needs_install}" == "true" ]]; then
      sudo -n "${INSTALL_BIN}" -m 0644 "${tmp_playerctx_service}" "${playerctx_service_path}"
      sudo -n "${INSTALL_BIN}" -m 0644 "${tmp_playerctx_timer}" "${playerctx_timer_path}"
      log "Installed ${playerctx_service_name}.service + .timer"
    fi
    rm -f "${tmp_playerctx_service}" "${tmp_playerctx_timer}"
  fi

  # ── Player-context retention push timer (dated snapshots -> main) ──────
  # The refresh above writes data/playerctx/history/snapshot_<date>.json
  # into the LIVE deploy dir; this pushes those dated files to main from
  # a dedicated clone.  Split into two units on purpose: deploy.sh does
  # `git checkout --force` + `git reset --hard` on the live tree, so
  # anything committed there is destroyed on the next deploy.  See the
  # header of deploy/playerctx_history_push.sh.
  #
  # INSTALLED UNCONDITIONALLY, and the deploy-key check lives in the
  # script rather than here.  It was gated on the key at first, by
  # analogy with the DLF / IDP Show pushers, and that was wrong twice
  # over — measured on the 2026-08-05 deploy, which logged
  # "retention timer skipped: /home/…/.ssh/github_deploy_key missing"
  # and installed nothing:
  #
  #   1. THE TEST RAN AS THE WRONG USER.  The unit runs as __APP_USER__
  #      and reads that user's key; this installer runs as the deploy
  #      user, whose sudo is scoped to specific commands, so
  #      `sudo -n test -f` is not reliably permitted and a plain `[[ -f ]]`
  #      cannot stat another user's ~/.ssh.  The check could report
  #      "missing" for a key that is present and working — and the DLF
  #      pusher committing to main every two hours is evidence one IS
  #      present.  Only the service user can answer this, so the service
  #      user asks it.
  #   2. A CONDITIONALLY-INSTALLED TIMER BREAKS deploy.sh.  Its presence
  #      check globs *.timer.template and warns for anything not
  #      installed AND enabled, then runs this installer to fill the gap
  #      — so a permanently-skipped timer means a warning plus a pointless
  #      installer run on EVERY deploy, forever.  That is the exact loop
  #      #729 closed for three other timers.  deploy.sh carries a `case`
  #      exempting the alert timers; adding a fourth exemption would have
  #      spread the problem rather than fixed it.
  #
  # The unit is cheap and safe when unusable: the script names the
  # missing key and exits 0 without touching anything, and because it
  # copies EVERY dated snapshot rather than the newest, fixing the key
  # later backfills the whole backlog on the next run.
  local pchist_service_template="${APP_DIR}/deploy/systemd/dynasty-playerctx-history.service.template"
  local pchist_timer_template="${APP_DIR}/deploy/systemd/dynasty-playerctx-history.timer.template"
  local pchist_service_name="${SERVICE_NAME}-playerctx-history"
  local pchist_service_path="/etc/systemd/system/${pchist_service_name}.service"
  local pchist_timer_path="/etc/systemd/system/${pchist_service_name}.timer"
  local pchist_needs_install=false

  if [[ -f "${pchist_service_template}" && -f "${pchist_timer_template}" ]]; then
    local tmp_pchist_service tmp_pchist_timer
    tmp_pchist_service="$(mktemp)"
    tmp_pchist_timer="$(mktemp)"
    sed \
      -e "s/__SERVICE_NAME__/$(escape_sed_replacement "${SERVICE_NAME}")/g" \
      -e "s/__APP_USER__/$(escape_sed_replacement "${APP_USER}")/g" \
      -e "s/__APP_DIR__/$(escape_sed_replacement "${APP_DIR}")/g" \
      "${pchist_service_template}" > "${tmp_pchist_service}"
    sed \
      -e "s/__SERVICE_NAME__/$(escape_sed_replacement "${SERVICE_NAME}")/g" \
      "${pchist_timer_template}" > "${tmp_pchist_timer}"

    if sudo -n "${SYSTEMCTL_BIN}" cat "${pchist_service_name}.timer" >/dev/null 2>&1; then
      if [[ "${force_install_on}" == "true" ]]; then
        log "FORCE_SERVICE_INSTALL enabled; rewriting ${pchist_service_path} + timer."
        pchist_needs_install=true
      elif ! installed_matches "${tmp_pchist_service}" "${pchist_service_path}" \
        || ! installed_matches "${tmp_pchist_timer}" "${pchist_timer_path}"; then
        log "Player-context retention unit files changed; rewriting."
        pchist_needs_install=true
      else
        log "Player-context retention timer already installed and current; skipping."
      fi
    else
      log "Installing player-context retention push service + timer."
      pchist_needs_install=true
    fi

    if [[ "${pchist_needs_install}" == "true" ]]; then
      sudo -n "${INSTALL_BIN}" -m 0644 "${tmp_pchist_service}" "${pchist_service_path}"
      sudo -n "${INSTALL_BIN}" -m 0644 "${tmp_pchist_timer}" "${pchist_timer_path}"
      log "Installed ${pchist_service_name}.service + .timer"
      sudo -n "${INSTALL_BIN}" -d -m 0755 -o "${APP_USER}" -g "${APP_USER}" /var/lib/playerctx-history
    fi
    rm -f "${tmp_pchist_service}" "${tmp_pchist_timer}"
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
  local bdvm_needs_install=false

  # Drift-aware since 2026-10-01: production's installed unit had stayed
  # at its first-install content and never received the stage-0
  # refresh_bdvm_inputs.py ExecStart (see reconcile_timer_units).
  if [[ -f "${bdvm_service_template}" && -f "${bdvm_timer_template}" ]]; then
    reconcile_timer_units "bdvm-refresh" "BDVM projection refresh"
    bdvm_needs_install="${TIMER_UNITS_WRITTEN}"
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
  local ce_needs_install=false

  # Drift-aware since 2026-10-01: production's installed unit predated
  # the template's User=/Group= and ran as root (see
  # reconcile_timer_units).  The ownership migration runs AFTER the unit
  # is current and BEFORE the initial kick at the bottom of main(), so
  # the first run as APP_USER finds a store it can write.  It runs on
  # every install (not only when the unit was rewritten) because it is
  # idempotent and a chown that failed once must be retried next deploy.
  if [[ -f "${ce_service_template}" && -f "${ce_timer_template}" ]]; then
    reconcile_timer_units "consensus-edge-snapshot" "Consensus Edge snapshot"
    ce_needs_install="${TIMER_UNITS_WRITTEN}"
    migrate_consensus_edge_store_ownership
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
  local sharp_needs_install=false

  if [[ -f "${sharp_service_template}" && -f "${sharp_timer_template}" ]]; then
    reconcile_timer_units "sharp-discovery" "Sharp Tracker manager-discovery"
    sharp_needs_install="${TIMER_UNITS_WRITTEN}"
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
  local sharprec_needs_install=false

  if [[ -f "${sharprec_service_template}" && -f "${sharprec_timer_template}" ]]; then
    reconcile_timer_units "sharp-records" "Sharp Tracker season-records"
    sharprec_needs_install="${TIMER_UNITS_WRITTEN}"
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
  local sharpros_needs_install=false

  if [[ -f "${sharpros_service_template}" && -f "${sharpros_timer_template}" ]]; then
    reconcile_timer_units "sharp-rosters" "Sharp roster collection"
    sharpros_needs_install="${TIMER_UNITS_WRITTEN}"
  fi


  # ── FFPC public Sharp ingestion timer ───────────────────────────────
  local ffpc_service_template="${APP_DIR}/deploy/systemd/dynasty-ffpc-sharp.service.template"
  local ffpc_timer_template="${APP_DIR}/deploy/systemd/dynasty-ffpc-sharp.timer.template"
  local ffpc_service_name="${SERVICE_NAME}-ffpc-sharp"
  local ffpc_needs_install=false
  local ffpc_enabled=false
  if [[ -f "${APP_DIR}/config/sharp/ffpc_sources.json" ]] && \
     grep -m1 -Eq '"enabled"[[:space:]]*:[[:space:]]*true' \
       "${APP_DIR}/config/sharp/ffpc_sources.json"; then
    ffpc_enabled=true
  fi
  # Same presence-only hole as the twelve logged blocks, minus the log
  # line; gate (ffpc_sources.json "enabled": true) unchanged.
  if [[ "${ffpc_enabled}" == "true" && -f "${ffpc_service_template}" && -f "${ffpc_timer_template}" ]]; then
    reconcile_timer_units "ffpc-sharp" "FFPC public Sharp ingestion"
    ffpc_needs_install="${TIMER_UNITS_WRITTEN}"
  fi

  # ── Sharp Tracker transaction crawl timer ─────────────────────────────
  # The THIRD sharp pass, and the one that actually produces the board:
  # discovery finds managers, records finds their results, this finds
  # their TRADES.  Writes the same gitignored SQLite ledger, so it runs
  # prod-side for the same reason as the other two.
  #
  # Runs every 6h rather than daily because it tracks a MOVING signal —
  # a 48h window is one of the board's headline lenses, and a
  # once-daily crawl would make "last 48 hours" mean "as of this
  # morning".  Exit 2 (budget exhausted, leagues remaining) is the
  # normal steady state on a large graph, not a failure.
  local sharptx_service_template="${APP_DIR}/deploy/systemd/dynasty-sharp-transactions.service.template"
  local sharptx_timer_template="${APP_DIR}/deploy/systemd/dynasty-sharp-transactions.timer.template"
  local sharptx_service_name="${SERVICE_NAME}-sharp-transactions"
  local sharptx_needs_install=false

  if [[ -f "${sharptx_service_template}" && -f "${sharptx_timer_template}" ]]; then
    reconcile_timer_units "sharp-transactions" "Sharp Tracker transaction crawl"
    sharptx_needs_install="${TIMER_UNITS_WRITTEN}"
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
  local rd_needs_install=false

  if [[ -f "${rd_service_template}" && -f "${rd_timer_template}" ]]; then
    reconcile_timer_units "reception-depth" "reception-depth refresh"
    rd_needs_install="${TIMER_UNITS_WRITTEN}"
  fi

  # ── Play-by-play weekly stat timer ────────────────────────────────────
  # Streams nflverse play-by-play into per-player-WEEK stats for the ten
  # rules this league pays that the nflverse WEEKLY feed does not publish
  # (the six reception bands, st_tkl_solo, st_ff, st_fum_rec,
  # pass_int_td).  Same prod-side reasoning as reception-depth: the
  # readers load a LOCAL file and data/ is gitignored, so a CI-built
  # artifact never reaches the VPS.  Public nflverse, no credentials.
  #
  # Builds COMPLETED seasons only, so it can never record a not-yet-played
  # game as a real zero.  Exit 2 ("everything already on disk") is its
  # normal weekly state and is treated as success.
  local pbw_service_template="${APP_DIR}/deploy/systemd/dynasty-pbp-weekly.service.template"
  local pbw_timer_template="${APP_DIR}/deploy/systemd/dynasty-pbp-weekly.timer.template"
  local pbw_service_name="${SERVICE_NAME}-pbp-weekly"
  local pbw_needs_install=false

  if [[ -f "${pbw_service_template}" && -f "${pbw_timer_template}" ]]; then
    reconcile_timer_units "pbp-weekly" "play-by-play weekly stat"
    pbw_needs_install="${TIMER_UNITS_WRITTEN}"
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
  local dlf_fetch_needs_install=false
  local has_dlf_creds=false

  if [[ -f "${APP_DIR}/.env" ]] \
     && grep -Eq '^[[:space:]]*DLF_USERNAME=.+$' "${APP_DIR}/.env" \
     && grep -Eq '^[[:space:]]*DLF_PASSWORD=.+$' "${APP_DIR}/.env"; then
    has_dlf_creds=true
  fi

  if [[ -f "${dlf_fetch_service_template}" && -f "${dlf_fetch_timer_template}" && "${has_dlf_creds}" == "true" ]]; then
    reconcile_timer_units "dlf-fetch" "DLF-fetch"
    dlf_fetch_needs_install="${TIMER_UNITS_WRITTEN}"

    if [[ "${dlf_fetch_needs_install}" == "true" ]]; then
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
  local idpshow_fetch_needs_install=false
  local has_idpshow_session=false

  if [[ -f "${APP_DIR}/idpshow_session.json" ]]; then
    has_idpshow_session=true
  fi

  if [[ -f "${idpshow_fetch_service_template}" && -f "${idpshow_fetch_timer_template}" && "${has_idpshow_session}" == "true" ]]; then
    reconcile_timer_units "idpshow-fetch" "IDP Show fetch"
    idpshow_fetch_needs_install="${TIMER_UNITS_WRITTEN}"

    if [[ "${idpshow_fetch_needs_install}" == "true" ]]; then
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

  # ── Timers with no special install requirements ─────────────────────────
  # These need nothing but "render both templates and enable", so they go
  # through the shared helper instead of another 40-line copy.  All three
  # shipped templates that NOTHING installed until 2026-08-05; see the
  # helper's comment for why that was worse than simply not running.
  install_simple_timer "crowd-faab" "cross-league FAAB crowd accumulation"
  # Sibling of crowd-faab, and deliberately a SEPARATE unit: crowd-faab
  # collects what OTHER leagues pay, this collects what THIS league pays.
  # The engine fits its market priors from the second and has been falling
  # back to configured priors — and saying so — for want of a cadence.
  install_simple_timer "faab-history" "own-league FAAB bid-history collection"
  install_simple_timer "sharp-activity" "qualified-manager Sleeper activity crawl"
  install_simple_timer "board-snapshot" "canonical board as-of snapshot"
  install_simple_timer "sharp-cohort-snapshot" "daily sharp-cohort baseline"
  # Signals account session renewal (docs/sources/SIGNALS_ACCOUNT_CONNECTION.md).
  # A no-op exit 0 until the owner provisions a session to /var/lib/signals-auth.
  install_simple_timer "signals-auth-renew" "Signals owner-session renewal"
  # Live Waiver Opportunity layer (docs/faab-live-opportunity-model.md):
  # all three feed BDVM structured events / trending history that
  # src/trade/faab_opportunity.py reads.  Public endpoints, no creds.
  install_simple_timer "depth-charts-refresh" "ESPN depth-chart diff -> BDVM promotion/demotion events"
  install_simple_timer "injury-feed-refresh" "ESPN injury-status diff -> BDVM injury/return events"
  install_simple_timer "trending-history-refresh" "Sleeper trending adds+drops history snapshot"
  install_simple_timer "game-day-capture" "pre-kickoff Game Day prediction archive capture"
  # Game Day U5 shared live collector: fires every minute, the tick decides
  # whether it is due (src/ros/game_day_live.py).  Public endpoints, no creds.
  install_simple_timer "game-day-live" "Game Day live collector (observations + generations)"
  install_simple_timer "auction-backup" "rookie auction store hourly verified backup (backup + restore + replay check)"
  # DFS-AUTO: automatic DraftKings/FanDuel slates, no uploads (src/dfs/auto/refresh.py).
  # Fires every 10 minutes; the tick decides whether anything is due.  No creds.
  install_simple_timer "dfs-auto-refresh" "DFS automatic slate refresh (schedule + salaries + projections)"
  # Signals Fantasy public dynasty boards -> box-local private store read by
  # the authenticated /api/second-opinion/signals (src/sources/signals.py).
  # Public pages, no creds; a 401/403 persists a stop the script obeys.
  install_simple_timer "signals-fetch" "Signals Fantasy public-board collection (non-voting second opinion)"
  # KTC Trade Database -> append-only raw trade archive (Market Trade Ledger,
  # Batch 3 Unit I; src/sources/ktc_trades.py).  Public page, no creds; a
  # 401/403/challenge persists a stop the script obeys.  Never moves a value.
  install_simple_timer "ktc-trades" "KTC Trade Database accumulation (Market Trade Ledger raw archive)"
  # Daily rebuild of the DERIVED underlying-trade ledger + coverage report
  # from that archive (src/trade/market_trade_report.py).  Its own unit so a
  # rebuild can never eat the fetch's timeout/memory; box-local files only.
  install_simple_timer "market-trade-ledger" "Market Trade Ledger daily rebuild (derived underlying-trade ledger)"
  # Batch 3 Unit F: the #1571 joint robust filter in SHADOW beside the incumbent
  # Hampel filter -> append-only data/robust_filter_shadow/ledger.jsonl + the
  # preregistered evaluation. Writes no served value; never promotes.
  install_simple_timer "joint-filter-shadow" "joint robust-filter shadow ledger (no served-value change)"
  # Sparse-evidence estimator SHADOW ledger (Batch 3 Unit E): builds the served
  # board and candidate C in memory, appends both answers to gitignored
  # data/sparse_evidence_shadow/. Never serves or promotes. No creds.
  install_simple_timer "sparse-evidence-shadow" "sparse-evidence estimator shadow ledger (incumbent vs candidate C)"
  # AL-P4: weekly point-in-time pick-forecast / team-strength snapshot ->
  # gitignored data/pick_forecast_snapshots/ (NOT data/ros/, which the refresh
  # force-adds). Capture only; reads canonical owners, serves nothing. No creds.
  install_simple_timer "pick-forecast-snapshot" "weekly pick-forecast / team-strength snapshot (capture only)"

  # ── daemon-reload and enable ────────────────────────────────────────────
  # ce_needs_install was missing from this list. Every other timer's
  # flag is here, so a FORCE_SERVICE_INSTALL rewrite of the Consensus
  # Edge unit wrote a new file to disk and then started the STALE cached
  # one, because nothing had told systemd to re-read it — the failure
  # mode where the fix is deployed, reported as deployed, and not
  # running.
  #
  # Fixing it for `ce` alone left the same hole open twice more:
  # `sharpros_needs_install` and `sharptx_needs_install` both gate an
  # `enable --now` below while being absent from this chain, so a run
  # that installed ONLY the sharp-rosters or sharp-transactions unit
  # enabled it against a systemd that had never read it.  Both added,
  # and `tests/deploy/test_all_timers_are_wired.py` now derives the
  # expected set from the declarations rather than trusting this line to
  # be maintained by hand.
  if [[ "${backend_needs_install}" == "true" || "${frontend_needs_install}" == "true" || "${alerts_needs_install}" == "true" || "${custom_alerts_needs_install}" == "true" || "${playerctx_needs_install}" == "true" || "${pchist_needs_install}" == "true" || "${bdvm_needs_install}" == "true" || "${ce_needs_install}" == "true" || "${sharp_needs_install}" == "true" || "${sharprec_needs_install}" == "true" || "${sharpros_needs_install}" == "true" || "${sharptx_needs_install}" == "true" || "${ffpc_needs_install}" == "true" || "${rd_needs_install}" == "true" || "${pbw_needs_install}" == "true" || "${dlf_fetch_needs_install}" == "true" || "${idpshow_fetch_needs_install}" == "true" ]]; then
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
  if [[ "${pchist_needs_install}" == "true" ]]; then
    # --now arms the weekly timer.  NO initial kick: the first run would
    # clone the repo during a deploy for a file the refresh has not
    # written yet (retention only starts producing on the next Tuesday),
    # and the script would correctly exit clean having done nothing.
    sudo -n "${SYSTEMCTL_BIN}" enable --now "${pchist_service_name}.timer"
    log "Enabled ${pchist_service_name}.timer"
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
  if [[ "${pbw_needs_install}" == "true" ]]; then
    # Same reasoning as reception-depth: --now arms the timer, no initial
    # kick.  Unlike that one this artifact GATES scoring rather than
    # enriching it — without it ten configured rules score nothing — so
    # the first Wednesday run matters, and until it lands the engine
    # reports them in ``unscored`` rather than pretending they are zero.
    sudo -n "${SYSTEMCTL_BIN}" enable --now "${pbw_service_name}.timer"
    log "Enabled ${pbw_service_name}.timer"
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
  # These three were gated on TEMPLATE PRESENCE, not on a write, so
  # sharp-records and ffpc-sharp re-kicked a budgeted crawl on EVERY
  # deploy, and sharp-rosters re-armed its timer.  The kick now follows a
  # (re)write, like every other block.  A unit that is on disk but not
  # enabled is still enabled — deploy.sh's detector treats that as
  # missing — but without a kick (same rule as install_simple_timer).
  if [[ "${sharprec_needs_install}" == "true" ]]; then
    sudo -n "${SYSTEMCTL_BIN}" enable --now "${sharprec_service_name}.timer"
    log "Enabled ${sharprec_service_name}.timer"
    sudo -n "${SYSTEMCTL_BIN}" start --no-block "${sharprec_service_name}.service" || \
      log "Note: initial sharp-records crawl could not be started; the timer will cover it."
  elif [[ -f "${sharprec_service_template}" && -f "${sharprec_timer_template}" ]] \
    && ! sudo -n "${SYSTEMCTL_BIN}" is-enabled "${sharprec_service_name}.timer" >/dev/null 2>&1; then
    sudo -n "${SYSTEMCTL_BIN}" enable --now "${sharprec_service_name}.timer" && \
      log "Enabled ${sharprec_service_name}.timer" || \
      log "Note: could not enable ${sharprec_service_name}.timer."
  fi
  if [[ "${sharpros_needs_install}" == "true" ]] \
    || { [[ -f "${sharpros_service_template}" && -f "${sharpros_timer_template}" ]] \
      && ! sudo -n "${SYSTEMCTL_BIN}" is-enabled "${sharpros_service_name}.timer" >/dev/null 2>&1; }; then
    # --now arms the daily timer. No initial kick: this pass collects
    # for the cohort that discovery and records produce, and on a fresh
    # deploy those two have not finished yet — an immediate run would
    # collect for an empty cohort and log a misleading zero. The 30-min
    # OnActiveSec in the timer covers deploy day.
    # Guarded like install_simple_timer: under set -e an unguarded enable
    # failure would abort the whole installer (and the deploy) over one timer.
    sudo -n "${SYSTEMCTL_BIN}" enable --now "${sharpros_service_name}.timer" && \
      log "Enabled ${sharpros_service_name}.timer" || \
      log "Note: could not enable ${sharpros_service_name}.timer."
  fi
  if [[ "${ffpc_needs_install}" == "true" ]]; then
    sudo -n "${SYSTEMCTL_BIN}" enable --now "${ffpc_service_name}.timer"
    log "Enabled ${ffpc_service_name}.timer"
    sudo -n "${SYSTEMCTL_BIN}" start --no-block "${ffpc_service_name}.service" || \
      log "Note: initial FFPC public crawl could not be started; the timer will cover it."
  elif [[ "${ffpc_enabled}" == "true" && -f "${ffpc_service_template}" && -f "${ffpc_timer_template}" ]] \
    && ! sudo -n "${SYSTEMCTL_BIN}" is-enabled "${ffpc_service_name}.timer" >/dev/null 2>&1; then
    sudo -n "${SYSTEMCTL_BIN}" enable --now "${ffpc_service_name}.timer" && \
      log "Enabled ${ffpc_service_name}.timer" || \
      log "Note: could not enable ${ffpc_service_name}.timer."
  fi
  if [[ "${sharptx_needs_install}" == "true" ]]; then
    # --now arms the 6-hourly timer.  No initial kick, same reason as
    # records: the discovery crawl started above has to publish the
    # sharp-eligible league list before there is anything to crawl, and
    # the next slot picks it up within hours.
    sudo -n "${SYSTEMCTL_BIN}" enable --now "${sharptx_service_name}.timer"
    log "Enabled ${sharptx_service_name}.timer"
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
    # keeps daemon-reload churn to a minimum.  installed_matches covers
    # both (a missing target is drift) and reads without sudo.
    if ! installed_matches "${src}" "${dst}"; then
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
    if ! installed_matches "${logrotate_src}" "${logrotate_dst}"; then
      sudo -n "${INSTALL_BIN}" -m 0644 "${logrotate_src}" "${logrotate_dst}"
      log "Installed /etc/logrotate.d/riskit"
    fi
  fi

  refresh_state_backup_line
}

# ── C1A state-backup line: refresh the ROOT-OWNED copy on drift (AL-P2) ──
#
# riskit-state-backup.service runs /usr/local/lib/riskit/riskit-state-backup.sh
# as root — a copy OUTSIDE the deploy-user-writable checkout.  Until
# 2026-10-01 only deploy/apply_hardening.sh and the c1a-install-state-backup
# workflow refreshed it, never a deploy, so a merged change to the writer did
# not reach the nightly.  Measured read-only on production 2026-10-02: the
# root copy was the 600-line 2026-08-16 script while the checkout carried
# 647 lines — the nightly was skipping acquisition, auction and game_day,
# which only the deploy user's post-deploy proof run was still covering.
#
# NOT a second installer.  This sources deploy/backup/install_state_backup.sh
# — the one owner of "which files, in which order, with which modes", and of
# the service render — and calls its functions.  Its _sb_install_file compares
# unprivileged (`cmp`, which the NOPASSWD allowlist refuses under sudo; same
# reason as installed_matches above) and writes only on real drift, through
# `sudo -n install`.  daemon-reload + enable run only when something changed,
# so an up-to-date box is a no-op on every deploy.
#
# Privilege model unchanged.  The deploy account already holds NOPASSWD
# `install` (and runs this exact installer from the c1a workflow); refreshing
# on deploy grants nothing it could not already do.  The root copy still
# exists so that the nightly never EXECUTES a deploy-user-writable file.
#
# Non-fatal by design: a failed refresh is logged as an ERROR and the deploy
# continues, because the previous root copy keeps producing generations and a
# backup-installer hiccup must not block shipping the app.  The failure is not
# silent — the ERROR names what is still stale.
refresh_state_backup_line() {
  local owner="${APP_DIR}/deploy/backup/install_state_backup.sh"
  local lib_dir="${RISKIT_LIB_DIR:-/usr/local/lib/riskit}"
  if [[ ! -f "${owner}" ]]; then
    log "State-backup installer not shipped in this checkout; skipping root-copy refresh."
    return 0
  fi
  # shellcheck source=deploy/backup/install_state_backup.sh
  source "${owner}"
  STATE_BACKUP_CHANGED=0
  if ! state_backup_install_scripts "${APP_DIR}" "${lib_dir}" \
    || ! state_backup_install_units "${APP_DIR}" "${lib_dir}"; then
    error "State-backup root copy refresh FAILED; the nightly may still run a stale ${lib_dir}/riskit-state-backup.sh."
    return 0
  fi
  local name
  for name in backup_root_lib.sh riskit-state-backup.sh; do
    if ! cmp -s "${APP_DIR}/deploy/backup/${name}" "${lib_dir}/${name}" 2>/dev/null; then
      error "State-backup root copy ${lib_dir}/${name} still differs from the checkout after refresh."
      return 0
    fi
  done
  if [[ "${STATE_BACKUP_CHANGED}" == "1" ]]; then
    if ! state_backup_enable; then
      error "State-backup units refreshed but daemon-reload/enable failed."
      return 0
    fi
    log "State-backup root copy refreshed from the checkout (drift)."
  else
    log "State-backup root copy current."
  fi
}

main "$@"
