#!/usr/bin/env bash
#
# signals_idp_family_rollback.sh — fast, verified rollback of Signals IDP
# voting, one family at a time (plan PR-RB; owner directive 2026-10-19).
#
# WHAT THIS IS, AND IS NOT
# ─────────────────────────
# V1-49 style (deploy/diagnostics/v1_49_host_native_activation.sh): a fixed,
# checked-in script that edits exactly ONE production .env key, selected by a
# closed FAMILY choice from a HARD-CODED table below — never a key, value or
# command taken from an argument.  Without it the documented rollback for an
# activated Signals IDP family is "revert + deploy" (~90 min).
#
#   FAMILY        .env key                                gate flag                    sources withheld
#   dl            RISKIT_FEATURE_SIGNALS_IDP_DL_VOTE      signals_idp_dl_vote          signalsIdpDl
#   lb            RISKIT_FEATURE_SIGNALS_IDP_LB_VOTE      signals_idp_lb_vote          signalsIdpLb
#   db            RISKIT_FEATURE_SIGNALS_IDP_DB_VOTE      signals_idp_db_vote          signalsIdpDb
#   all-idp       RISKIT_FEATURE_SIGNALS_IDP_SHARED_MARKET signals_idp_shared_market   all three IDP boards
#   all-signals   RISKIT_FEATURE_SIGNALS_ACTIVE_SOURCE    signals_active_source        offense + all IDP
#
# The rollback direction is ALWAYS "off" (value 0).  It never activates
# anything: activation is a reviewed _DEFAULTS flip released through a
# train (plan §6).  ``restore`` puts back exactly the raw .env state captured
# before a given rollback (usually ABSENT, i.e. the registry default).
#
# POST-VERIFICATION (the point of the exercise): after the restart the
# SERVED state is read from local GET /api/status — ``featureFlags[<gate>]``
# must read disabled and every withheld source must appear in
# ``served_private_absent_by_design``.  A flag being off in .env is not proof.
#
# A rollback whose verification fails is NOT undone automatically: off is the
# safe direction.  It exits 2 (ROLLBACK_UNVERIFIED) for a human.
#
# Inputs (environment):
#   ACTION        preflight | rollback | restore     (required)
#   FAMILY        dl | lb | db | all-idp | all-signals (required)
#   APP_DIR       deployed app tree
#   SERVICE_NAME  systemd unit to restart (default: dynasty)
#   PYTHON_BIN    venv interpreter (falls back through candidates)
#   APP_HOST/APP_PORT  local status target (default 127.0.0.1:8000)
#   EXPECTED_SHA  required for preflight / rollback — refuses on mismatch
#   ROLLBACK_ID   rollback: the run id (state dir); restore: id to restore,
#                 empty = LATEST for this family
#   REASON        free-text audit note (never used as a command)
#
# State: $APP_DIR/.deploy/signals-idp-family-rollback/<family>/<id>/
#   prior_flag_state.txt  prior_flag_enabled_bool.txt  reason.txt  result.txt
#
# Exit codes: 0 ok · 1 refused (nothing written) · 2 written but the served
# state did not verify (manual check) · 3 restore failed

set -Eeuo pipefail

APP_DIR="${APP_DIR:-/home/dynasty/trade-calculator}"
SERVICE_NAME="${SERVICE_NAME:-dynasty}"
APP_HOST="${APP_HOST:-127.0.0.1}"
APP_PORT="${APP_PORT:-8000}"
ENV_FILE="${APP_DIR}/.env"
ACTION="${ACTION:-}"
FAMILY="${FAMILY:-}"
EXPECTED_SHA="${EXPECTED_SHA:-}"
ROLLBACK_ID="${ROLLBACK_ID:-}"
REASON="${REASON:-unspecified}"
STATE_BASE="${APP_DIR}/.deploy/signals-idp-family-rollback"

log()  { printf '[signals-idp-rollback] %s\n' "$*"; }
warn() { printf '[signals-idp-rollback][WARN] %s\n' "$*" >&2; }
refuse() { printf '[signals-idp-rollback][REFUSED] %s\n' "$*" >&2; exit 1; }

# ── the ONE table: family -> key, gate, withheld sources ───────────────────
resolve_family() {
  case "${FAMILY}" in
    dl)          FLAG_KEY="RISKIT_FEATURE_SIGNALS_IDP_DL_VOTE";       FLAG_GATE_NAME="signals_idp_dl_vote";       SOURCE_KEYS="signalsIdpDl" ;;
    lb)          FLAG_KEY="RISKIT_FEATURE_SIGNALS_IDP_LB_VOTE";       FLAG_GATE_NAME="signals_idp_lb_vote";       SOURCE_KEYS="signalsIdpLb" ;;
    db)          FLAG_KEY="RISKIT_FEATURE_SIGNALS_IDP_DB_VOTE";       FLAG_GATE_NAME="signals_idp_db_vote";       SOURCE_KEYS="signalsIdpDb" ;;
    all-idp)     FLAG_KEY="RISKIT_FEATURE_SIGNALS_IDP_SHARED_MARKET"; FLAG_GATE_NAME="signals_idp_shared_market"; SOURCE_KEYS="signalsIdpDl signalsIdpLb signalsIdpDb" ;;
    all-signals) FLAG_KEY="RISKIT_FEATURE_SIGNALS_ACTIVE_SOURCE";     FLAG_GATE_NAME="signals_active_source";     SOURCE_KEYS="signalsSf signalsIdpDl signalsIdpLb signalsIdpDb" ;;
    *) refuse "FAMILY must be one of dl, lb, db, all-idp, all-signals (got: '${FAMILY}')" ;;
  esac
  STATE_ROOT="${STATE_BASE}/${FAMILY}"
  LATEST_POINTER="${STATE_ROOT}/LATEST"
}

validate_rollback_id() {
  local id="$1"
  if [[ -z "${id}" || ! "${id}" =~ ^[A-Za-z0-9_.-]+$ || "${id}" == "." || "${id}" == ".." ]]; then
    echo "[signals-idp-rollback][ERROR] invalid rollback id: '${id}'" >&2
    exit 1
  fi
}

resolve_python_bin() {
  if [[ -n "${PYTHON_BIN:-}" && -x "${PYTHON_BIN}" ]]; then
    printf '%s\n' "${PYTHON_BIN}"; return 0
  fi
  local candidate
  for candidate in \
    "${APP_DIR}/.venv/bin/python" \
    "${APP_DIR}/venv/bin/python" \
    "/home/dynasty/.venvs/trade-calculator/bin/python"
  do
    [[ -x "${candidate}" ]] && { printf '%s\n' "${candidate}"; return 0; }
  done
  command -v python3
}

resolve_systemctl_bin() {
  local candidate
  for candidate in /bin/systemctl /usr/bin/systemctl; do
    [[ -x "${candidate}" ]] || continue
    if sudo -n "${candidate}" --version >/dev/null 2>&1; then
      printf '%s\n' "${candidate}"; return 0
    fi
  done
  warn "No NOPASSWD sudo permission for systemctl (checked /bin, /usr/bin)."
  return 1
}

# Plain KEY=VALUE reader, the same rule EnvironmentFile= applies (never
# `source`): see the V1-49 script for the incident that made this the rule.
env_sourced_python() {
  local -a env_args=()
  local line
  if [[ -f "${ENV_FILE}" ]]; then
    while IFS= read -r line || [[ -n "${line}" ]]; do
      [[ "${line}" =~ ^[[:space:]]*(#.*)?$ ]] && continue
      [[ "${line}" =~ ^([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]] && env_args+=("${BASH_REMATCH[1]}=${BASH_REMATCH[2]}")
    done < "${ENV_FILE}"
  fi
  ( cd "${APP_DIR}" && env ${env_args[@]+"${env_args[@]}"} "${PYTHON_BIN}" "$@" )
}

flag_registered() {
  FLAG_GATE_NAME="${FLAG_GATE_NAME}" env_sourced_python -c "
import os, sys
sys.path.insert(0, '.')
from src.api.feature_flags import registered_flags
print(os.environ['FLAG_GATE_NAME'] in registered_flags())
"
}

read_flag_enabled() {
  FLAG_GATE_NAME="${FLAG_GATE_NAME}" env_sourced_python -c "
import os, sys
sys.path.insert(0, '.')
from src.api.feature_flags import is_enabled
print(is_enabled(os.environ['FLAG_GATE_NAME']))
"
}

wait_for_service_health() {
  local attempts="${HEALTH_CHECK_MAX_ATTEMPTS:-45}" n=1
  while (( n <= attempts )); do
    curl -fsS --max-time 8 "http://${APP_HOST}:${APP_PORT}/api/status" >/dev/null 2>&1 && return 0
    (( n < attempts )) && sleep "${HEALTH_CHECK_SLEEP_SECONDS:-2}"
    n=$((n + 1))
  done
  return 1
}

# SERVED-state verification: the gate reads ${1} (True/False) in /api/status
# featureFlags and, when ${1} is False, every withheld source is absent by
# design on the served board.  Polls: a restarted server serves the board
# only after it has loaded one.
verify_served_state() {
  local want_enabled="$1"
  local attempts="${VERIFY_MAX_ATTEMPTS:-60}" n=1 body verdict
  while (( n <= attempts )); do
    body="$(curl -fsS --max-time 15 "http://${APP_HOST}:${APP_PORT}/api/status" 2>/dev/null || true)"
    if [[ -n "${body}" ]]; then
      verdict="$(STATUS_BODY="${body}" WANT="${want_enabled}" GATE="${FLAG_GATE_NAME}" \
        SOURCES="${SOURCE_KEYS}" "${PYTHON_BIN}" -c "
import json, os
try:
    s = json.loads(os.environ['STATUS_BODY'])
except ValueError:
    print('unparseable'); raise SystemExit
flag = (s.get('featureFlags') or {}).get(os.environ['GATE'])
enabled = flag.get('enabled') if isinstance(flag, dict) else flag
want = os.environ['WANT'] == 'True'
if not s.get('has_data'):
    print('no_board_yet')
elif enabled is None:
    print('gate_not_reported')
elif bool(enabled) != want:
    print('gate_mismatch')
elif not want:
    absent = set(s.get('served_private_absent_by_design') or [])
    missing = [k for k in os.environ['SOURCES'].split() if k not in absent]
    print('ok' if not missing else 'sources_still_served:' + ','.join(missing))
else:
    print('ok')
")"
      log "served-state check ${n}/${attempts}: ${verdict}"
      [[ "${verdict}" == "ok" ]] && return 0
    fi
    (( n < attempts )) && sleep "${VERIFY_SLEEP_SECONDS:-5}"
    n=$((n + 1))
  done
  return 1
}

restart_service() {
  local systemctl_bin
  systemctl_bin="$(resolve_systemctl_bin)" || return 1
  log "Restarting ${SERVICE_NAME}."
  sudo -n "${systemctl_bin}" restart "${SERVICE_NAME}" || return 1
  sleep 3
  sudo -n "${systemctl_bin}" is-active --quiet "${SERVICE_NAME}" || return 1
  wait_for_service_health
}

run_preflight_checks() {
  log "Preflight: family=${FAMILY} key=${FLAG_KEY} gate=${FLAG_GATE_NAME}"
  [[ -n "${EXPECTED_SHA}" ]] || refuse "EXPECTED_SHA was not supplied."
  [[ -d "${APP_DIR}/.git" ]] || refuse "APP_DIR is not a git checkout: ${APP_DIR}"
  local actual_sha
  actual_sha="$(git -C "${APP_DIR}" rev-parse HEAD)" || refuse "could not read HEAD"
  [[ "${actual_sha}" == "${EXPECTED_SHA}" ]] \
    || refuse "deployed SHA (${actual_sha}) does not match expected (${EXPECTED_SHA})."
  local registered
  registered="$(flag_registered)" || refuse "could not read the flag registry."
  # The per-family flags arrive with the per-family activation build (PR-I);
  # until it is deployed there is nothing to roll back for a single family.
  [[ "${registered}" == "True" ]] \
    || refuse "${FLAG_GATE_NAME} is not registered on the deployed build."
  local systemctl_bin
  systemctl_bin="$(resolve_systemctl_bin)" || refuse "cannot resolve a usable systemctl."
  sudo -n "${systemctl_bin}" cat "${SERVICE_NAME}" >/dev/null 2>&1 \
    || refuse "systemd unit not found: ${SERVICE_NAME}"
  log "Current ${FLAG_GATE_NAME} enabled=$(read_flag_enabled)"
  log "Preflight OK."
}

do_rollback() {
  [[ -n "${ROLLBACK_ID}" ]] || refuse "ROLLBACK_ID was not supplied."
  validate_rollback_id "${ROLLBACK_ID}"
  run_preflight_checks
  local state_dir="${STATE_ROOT}/${ROLLBACK_ID}"
  mkdir -p "${state_dir}"
  printf '%s\n' "${ROLLBACK_ID}" > "${LATEST_POINTER}"
  printf '%s\n' "${REASON}" > "${state_dir}/reason.txt"
  printf '%s\n' "${EXPECTED_SHA}" > "${state_dir}/expected_sha.txt"

  local prior_bool set_json prior_state
  prior_bool="$(read_flag_enabled)"
  printf '%s\n' "${prior_bool}" > "${state_dir}/prior_flag_enabled_bool.txt"
  set_json="$("${PYTHON_BIN}" "${APP_DIR}/scripts/prod_env_flag_ops.py" set \
    --env-file "${ENV_FILE}" --key "${FLAG_KEY}" --value "0")"
  prior_state="$(SET_JSON="${set_json}" "${PYTHON_BIN}" -c "import json,os; print(json.loads(os.environ['SET_JSON'])['prior_state'])")"
  printf '%s\n' "${prior_state}" > "${state_dir}/prior_flag_state.txt"
  log "${FLAG_KEY}=0 written. Prior raw state: ${prior_state} (enabled=${prior_bool})"

  if ! restart_service; then
    echo "ROLLBACK_UNVERIFIED" > "${state_dir}/result.txt"
    warn "service restart / health failed after the rollback write — MANUAL CHECK REQUIRED."
    exit 2
  fi
  if ! verify_served_state "False"; then
    echo "ROLLBACK_UNVERIFIED" > "${state_dir}/result.txt"
    warn "served state did not verify (flag still on, or sources still served) — MANUAL CHECK REQUIRED."
    exit 2
  fi
  echo "ROLLED_BACK" > "${state_dir}/result.txt"
  log "ROLLED_BACK and verified on the served board: ${SOURCE_KEYS}"
}

do_restore() {
  local rollback_id="${ROLLBACK_ID}"
  if [[ -z "${rollback_id}" ]]; then
    [[ -f "${LATEST_POINTER}" ]] || { echo "[signals-idp-rollback][ERROR] no ROLLBACK_ID and no LATEST for ${FAMILY}." >&2; exit 1; }
    rollback_id="$(cat "${LATEST_POINTER}")"
  fi
  validate_rollback_id "${rollback_id}"
  local state_dir="${STATE_ROOT}/${rollback_id}"
  [[ -f "${state_dir}/prior_flag_state.txt" ]] \
    || { echo "[signals-idp-rollback][ERROR] nothing captured for ${FAMILY}/${rollback_id}." >&2; exit 1; }
  local prior_state expected_bool actual_bool
  prior_state="$(cat "${state_dir}/prior_flag_state.txt")"
  expected_bool="$(cat "${state_dir}/prior_flag_enabled_bool.txt")"
  log "RESTORE: ${FLAG_KEY} -> captured prior state ${prior_state} (expect enabled=${expected_bool})"
  "${PYTHON_BIN}" "${APP_DIR}/scripts/prod_env_flag_ops.py" restore \
    --env-file "${ENV_FILE}" --key "${FLAG_KEY}" --prior-state "${prior_state}" \
    || { echo "RESTORE_FAILED" > "${state_dir}/result.txt"; exit 3; }
  restart_service || { echo "RESTORE_FAILED" > "${state_dir}/result.txt"; exit 3; }
  actual_bool="$(read_flag_enabled || echo '<error>')"
  if [[ "${actual_bool}" != "${expected_bool}" ]]; then
    echo "RESTORE_FAILED" > "${state_dir}/result.txt"
    warn "post-restore flag state (${actual_bool}) != pre-rollback state (${expected_bool})."
    exit 3
  fi
  verify_served_state "${expected_bool}" || { echo "RESTORE_FAILED" > "${state_dir}/result.txt"; exit 3; }
  echo "RESTORED" > "${state_dir}/result.txt"
  log "RESTORED and verified (enabled=${actual_bool})."
}

main() {
  resolve_family
  PYTHON_BIN="$(resolve_python_bin)"
  case "${ACTION}" in
    preflight) run_preflight_checks ;;
    rollback)  do_rollback ;;
    restore)   do_restore ;;
    *) refuse "ACTION must be one of: preflight, rollback, restore (got: '${ACTION}')" ;;
  esac
}

# Run main only when EXECUTED (also when piped over `ssh ... bash -s`), not
# when sourced by a test — see the V1-49 script for why the default expansion.
if [[ "${BASH_SOURCE[0]:-${0}}" == "${0}" ]]; then
  main "$@"
fi
