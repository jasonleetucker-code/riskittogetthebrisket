#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_APP_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

APP_DIR="${APP_DIR:-${DEFAULT_APP_DIR}}"
APP_USER="${APP_USER:-$(id -un)}"
VENV_DIR="${VENV_DIR:-${APP_DIR}/.venv}"
SERVICE_NAME="${SERVICE_NAME:-dynasty}"
FORCE_SHARP_RECORDS_KICK="${FORCE_SHARP_RECORDS_KICK:-false}"
SHARP_BOOTSTRAP_MAX_PASSES="${SHARP_BOOTSTRAP_MAX_PASSES:-3}"

SYSTEMCTL_BIN=""
INSTALL_BIN=""
JOURNALCTL_BIN=""
TMP_DIR=""

log() {
  printf '[sharp-bootstrap] %s\n' "$*"
}

warn() {
  printf '[sharp-bootstrap][WARN] %s\n' "$*" >&2
}

error() {
  printf '[sharp-bootstrap][ERROR] %s\n' "$*" >&2
}

lower() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]'
}

resolve_binary() {
  local candidate
  for candidate in "$@"; do
    if [[ -x "${candidate}" ]]; then
      printf '%s\n' "${candidate}"
      return 0
    fi
  done
  return 1
}

escape_sed_replacement() {
  printf '%s' "$1" | sed -e 's/[\\/&]/\\&/g'
}

render_unit() {
  local template="$1"
  local target="$2"
  local rendered="${TMP_DIR}/$(basename "${target}")"

  [[ -f "${template}" ]] || {
    error "Missing Sharp Tracker systemd template: ${template}"
    return 1
  }

  sed \
    -e "s/__SERVICE_NAME__/$(escape_sed_replacement "${SERVICE_NAME}")/g" \
    -e "s/__APP_USER__/$(escape_sed_replacement "${APP_USER}")/g" \
    -e "s/__APP_DIR__/$(escape_sed_replacement "${APP_DIR}")/g" \
    -e "s/__VENV_DIR__/$(escape_sed_replacement "${VENV_DIR}")/g" \
    "${template}" > "${rendered}"

  sudo -n "${INSTALL_BIN}" -m 0644 "${rendered}" "${target}"
  log "Installed $(basename "${target}")"
}

queue_field() {
  local field="$1"
  "${VENV_DIR}/bin/python" - "${field}" <<'PY'
import sys

from src.sharp.record_queue import queue_stats

value = queue_stats().get(sys.argv[1])
print(0 if value is None else value)
PY
}

records_field() {
  local field="$1"
  "${VENV_DIR}/bin/python" - "${field}" <<'PY'
import sys

from src.sharp.records import records_coverage

value = records_coverage().get(sys.argv[1])
print(0 if value is None else value)
PY
}

qualified_count() {
  "${VENV_DIR}/bin/python" - <<'PY'
from src.sharp import records
from src.sharp import score as sharp_score

scored = sharp_score.score_managers(records.build_manager_records())
print(sum(1 for manager in scored if manager.qualified))
PY
}

show_diagnostics() {
  log "Current season-record coverage:"
  "${VENV_DIR}/bin/python" "${APP_DIR}/scripts/crawl_sharp_records.py" --stats || true
  log "Current Sharp Score tiers:"
  "${VENV_DIR}/bin/python" "${APP_DIR}/scripts/crawl_sharp_records.py" --score || true
  log "Recent records-crawler journal:"
  sudo -n "${JOURNALCTL_BIN}" -u "${SERVICE_NAME}-sharp-records.service" -n 80 --no-pager || true
}

run_oneshot() {
  local unit="$1"
  log "Starting ${unit}"
  sudo -n "${SYSTEMCTL_BIN}" reset-failed "${unit}" >/dev/null 2>&1 || true
  if ! sudo -n "${SYSTEMCTL_BIN}" start "${unit}"; then
    error "${unit} failed."
    sudo -n "${JOURNALCTL_BIN}" -u "${unit}" -n 120 --no-pager || true
    return 1
  fi
  if sudo -n "${SYSTEMCTL_BIN}" is-failed --quiet "${unit}"; then
    error "${unit} entered a failed state."
    sudo -n "${JOURNALCTL_BIN}" -u "${unit}" -n 120 --no-pager || true
    return 1
  fi
  log "${unit} completed."
}

run_ffpc_now() {
  local installer="${APP_DIR}/deploy/install-ffpc-sharp-service.sh"
  local ffpc_service="${SERVICE_NAME}-ffpc-sharp.service"

  if [[ ! -f "${installer}" ]]; then
    warn "FFPC installer is unavailable: ${installer}"
    return 0
  fi

  log "Installing the daily FFPC collector and forcing an immediate public ingestion pass."
  APP_DIR="${APP_DIR}" \
  APP_USER="${APP_USER}" \
  VENV_DIR="${VENV_DIR}" \
  SERVICE_NAME="${SERVICE_NAME}" \
    bash "${installer}"

  if ! sudo -n "${SYSTEMCTL_BIN}" cat "${ffpc_service}" >/dev/null 2>&1; then
    warn "FFPC service was not installed; the public collector may be disabled by configuration."
    return 0
  fi

  run_oneshot "${ffpc_service}"
  log "Recent FFPC collector journal:"
  sudo -n "${JOURNALCTL_BIN}" -u "${ffpc_service}" -n 120 --no-pager || true
}

main() {
  [[ -d "${APP_DIR}" ]] || { error "APP_DIR does not exist: ${APP_DIR}"; exit 1; }
  [[ -x "${VENV_DIR}/bin/python" ]] || {
    error "Python virtualenv is unavailable: ${VENV_DIR}/bin/python"
    exit 1
  }
  [[ "${SHARP_BOOTSTRAP_MAX_PASSES}" =~ ^[1-9][0-9]*$ ]] || {
    error "SHARP_BOOTSTRAP_MAX_PASSES must be a positive integer."
    exit 1
  }

  SYSTEMCTL_BIN="$(resolve_binary /bin/systemctl /usr/bin/systemctl)" || {
    error "systemctl was not found."
    exit 1
  }
  INSTALL_BIN="$(resolve_binary /usr/bin/install /bin/install)" || {
    error "install was not found."
    exit 1
  }
  JOURNALCTL_BIN="$(resolve_binary /bin/journalctl /usr/bin/journalctl)" || {
    error "journalctl was not found."
    exit 1
  }

  cd "${APP_DIR}"
  TMP_DIR="$(mktemp -d)"
  trap 'rm -rf "${TMP_DIR:-}"' EXIT

  local discovery_service="${SERVICE_NAME}-sharp-discovery.service"
  local discovery_timer="${SERVICE_NAME}-sharp-discovery.timer"
  local records_service="${SERVICE_NAME}-sharp-records.service"
  local records_timer="${SERVICE_NAME}-sharp-records.timer"

  # Re-render all four units on every run. This intentionally bypasses the
  # generic installer's historical presence-check blind spot and guarantees
  # that a changed timer template reaches production, even when the unit
  # already exists.
  render_unit \
    "${APP_DIR}/deploy/systemd/dynasty-sharp-discovery.service.template" \
    "/etc/systemd/system/${discovery_service}"
  render_unit \
    "${APP_DIR}/deploy/systemd/dynasty-sharp-discovery.timer.template" \
    "/etc/systemd/system/${discovery_timer}"
  render_unit \
    "${APP_DIR}/deploy/systemd/dynasty-sharp-records.service.template" \
    "/etc/systemd/system/${records_service}"
  render_unit \
    "${APP_DIR}/deploy/systemd/dynasty-sharp-records.timer.template" \
    "/etc/systemd/system/${records_timer}"

  sudo -n "${SYSTEMCTL_BIN}" daemon-reload
  log "Reloaded systemd after installing Sharp Tracker units."
  sudo -n "${SYSTEMCTL_BIN}" enable --now "${discovery_timer}"
  sudo -n "${SYSTEMCTL_BIN}" enable --now "${records_timer}"
  log "Enabled both Sharp Tracker timers."

  local eligible
  eligible="$(queue_field eligibleLeagues)"
  if (( eligible == 0 )); then
    warn "No sharp-eligible leagues are stored yet; running discovery first."
    run_oneshot "${discovery_service}"
    eligible="$(queue_field eligibleLeagues)"
  fi

  if (( eligible == 0 )); then
    error "Discovery completed but produced no sharp-eligible leagues."
    show_diagnostics
    exit 1
  fi
  log "Sharp-eligible leagues available: ${eligible}"

  local force passes qualified uncrawled complete_rows
  force="$(lower "${FORCE_SHARP_RECORDS_KICK}")"
  passes=0
  qualified="$(qualified_count)"
  uncrawled="$(queue_field uncrawledLeagues)"
  complete_rows="$(records_field completedSeasonRows)"

  log "Before bootstrap: completed_rows=${complete_rows}, uncrawled_leagues=${uncrawled}, qualified_managers=${qualified}"

  # Every successful production deploy receives at least one immediate
  # records pass. An empty or still-unqualified cohort may receive further
  # bounded passes. Every pass recomputes the persistent fair queue, so it
  # advances instead of rereading a fixed league prefix.
  while (( passes < SHARP_BOOTSTRAP_MAX_PASSES )); do
    if (( passes > 0 && qualified > 0 )) && [[ "${force}" != "true" && "${force}" != "1" && "${force}" != "yes" ]]; then
      break
    fi
    if (( passes > 0 && uncrawled == 0 )); then
      break
    fi

    passes=$((passes + 1))
    log "Running immediate Sharp records pass ${passes}/${SHARP_BOOTSTRAP_MAX_PASSES}."
    run_oneshot "${records_service}"

    qualified="$(qualified_count)"
    uncrawled="$(queue_field uncrawledLeagues)"
    complete_rows="$(records_field completedSeasonRows)"
    log "After pass ${passes}: completed_rows=${complete_rows}, uncrawled_leagues=${uncrawled}, qualified_managers=${qualified}"

    # FORCE means at least one pass, not an unbounded refresh loop.
    force="false"
  done

  show_diagnostics

  if (( complete_rows == 0 )); then
    error "The records service ran but stored no completed-season rows."
    exit 1
  fi

  if (( qualified == 0 )); then
    warn "Historical records now exist, but no manager has cleared every Sharp Score gate yet."
    warn "The enabled daily timer will continue through the fair queue until coverage expands."
  else
    log "Sharp Tracker is populated with ${qualified} qualified manager(s)."
  fi

  run_ffpc_now
}

main "$@"
