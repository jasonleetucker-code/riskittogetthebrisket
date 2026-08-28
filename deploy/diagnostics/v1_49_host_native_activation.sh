#!/usr/bin/env bash
#
# v1_49_host_native_activation.sh — controlled production activation and
# rollback for ONE feature flag: RISKIT_FEATURE_HOST_NATIVE_SCORING.
#
# WHAT THIS IS, AND IS NOT
# ─────────────────────────
# This script does exactly three things, selected by $ACTION: (1) a
# read-only preflight that refuses to proceed on any unexpected state,
# (2) a controlled activation — backup, flag flip, restart, PBP rebuild,
# post-activation measurement — that automatically rolls itself back on
# any failure, and (3) an explicit rollback that restores a prior
# activation attempt's captured state. It is deliberately NOT a general
# remote-command runner: the flag key is a hard-coded constant
# ($FLAG_KEY below), never taken from an argument, and there is no path
# by which caller-supplied text becomes a shell command.
#
# THE SINGLE ROLLBACK PATH
# ─────────────────────────
# do_rollback() is the ONLY code that ever touches the flag or the PBP
# artifacts to undo something. It runs from two callers only: the ERR
# trap installed inside do_activate() (automatic rollback on any failure
# during activation), and the $ACTION=rollback branch (an explicit,
# later dispatch — including one run in a fresh SSH session after this
# script's own process died, e.g. an SSH drop or a runner timeout). Both
# callers pass it the SAME on-disk state directory, so there are not two
# rollback implementations to keep in sync — there is one, and it reads
# its inputs from files, never from in-memory state that a dropped
# connection could lose.
#
# do_rollback() is idempotent: every restore it performs
# (scripts/prod_env_flag_ops.py restore, scripts/pbp_artifact_backup.py
# restore) is itself idempotent, so running it twice — e.g. the ERR trap
# fires, and a later explicit $ACTION=rollback dispatch is also run
# against the same activation id — converges to the same state and is
# not an error.
#
# WHAT NEVER TRIGGERS A ROLLBACK
# ────────────────────────────────
# The post-activation "league-comparison rerun" probe
# (GET /api/league-comparison?refresh=1) is an OBSERVATION, not a
# pass/fail gate — a 503 there is a documented, normal condition of that
# endpoint (Sleeper transiently unreachable) and is recorded as such,
# never treated as evidence the activation itself is broken. Every other
# step (flag flip, restart, health check, PBP rebuild, PBP schema
# validation, BDVM pre/post build and diff) is a hard requirement: any
# failure trips automatic rollback.
#
# STATE LAYOUT
# ─────────────
#   $APP_DIR/.deploy/v1-49-host-native-activation/<activation_id>/
#     prior_flag_state.txt          raw .env value captured before the
#                                    flip ("ABSENT" if the key was unset)
#     prior_flag_enabled_bool.txt   is_enabled() result captured before
#                                    the flip, for the post-rollback
#                                    sanity check
#     pbp_backup_manifest_path.txt  path to the pbp_artifact_backup.py
#                                    manifest for this attempt
#     bdvm_pre_snapshot_path.txt / bdvm_post_snapshot_path.txt
#     report.json                   final structured report
#     result.txt                    ACTIVATED | ROLLED_BACK | ROLLBACK_FAILED
#   $APP_DIR/.deploy/v1-49-host-native-activation/LATEST
#     the most recent activation_id — used by $ACTION=rollback when no
#     --activation-id / ACTIVATION_ID is supplied
#
# Inputs (environment):
#   ACTION            preflight | activate | rollback   (required)
#   APP_DIR           deployed app tree
#   SERVICE_NAME      systemd unit to restart (default: dynasty)
#   PYTHON_BIN        venv interpreter (falls back through candidates)
#   APP_HOST/APP_PORT local health-check target (default 127.0.0.1:8000)
#   EXPECTED_SHA      required for preflight/activate — refuses on mismatch
#   ACTIVATION_ID     required for activate; for rollback, empty = LATEST
#   REASON            free-text audit note (never used as a command)
#   BDVM_SEASON       required for activate — the season bdvm_build_baseline.py
#                     targets (this script does not derive it; the
#                     dispatching human states it explicitly)
#
# Exit codes:
#   0  preflight passed / activation succeeded / rollback succeeded
#   1  preflight refused (nothing was written) / rollback found nothing
#      to roll back
#   2  activation failed and automatic rollback SUCCEEDED — this is a
#      FAILED V1-49 verification attempt, not a success
#   3  activation failed and automatic rollback ALSO FAILED, or an
#      explicit rollback dispatch failed — manual intervention required

set -Eeuo pipefail

FLAG_KEY="RISKIT_FEATURE_HOST_NATIVE_SCORING"
FLAG_GATE_NAME="host_native_scoring"
PBP_SEASONS=(2021 2022 2023 2024 2025)

APP_DIR="${APP_DIR:-/home/dynasty/trade-calculator}"
SERVICE_NAME="${SERVICE_NAME:-dynasty}"
APP_HOST="${APP_HOST:-127.0.0.1}"
APP_PORT="${APP_PORT:-8000}"
ENV_FILE="${APP_DIR}/.env"
ACTION="${ACTION:-}"
EXPECTED_SHA="${EXPECTED_SHA:-}"
ACTIVATION_ID="${ACTIVATION_ID:-}"
REASON="${REASON:-unspecified}"
BDVM_SEASON="${BDVM_SEASON:-}"

STATE_ROOT="${APP_DIR}/.deploy/v1-49-host-native-activation"
LATEST_POINTER="${STATE_ROOT}/LATEST"

log()  { printf '[v1-49] %s\n' "$*"; }
warn() { printf '[v1-49][WARN] %s\n' "$*" >&2; }

fail_preflight() {
  printf '[v1-49][PREFLIGHT REFUSED] %s\n' "$*" >&2
  exit 1
}

# ACTIVATION_ID becomes a path segment (${STATE_ROOT}/${ACTIVATION_ID}).
# For `activate` it is always github.run_id (numeric, not caller-chosen),
# but for `rollback` it is free-text operator input
# (inputs.activation_id) — unvalidated, "../../etc" would point
# do_rollback at a directory outside $STATE_ROOT entirely. Enforced
# before ANY use, on both paths, so there is one gate rather than one
# per caller.
validate_activation_id() {
  local id="$1"
  if [[ -z "${id}" || ! "${id}" =~ ^[A-Za-z0-9_.-]+$ || "${id}" == "." || "${id}" == ".." ]]; then
    echo "[v1-49][ERROR] invalid activation id (must match ^[A-Za-z0-9_.-]+\$, not '.' or '..'): '${id}'" >&2
    exit 1
  fi
}

# ── interpreter / systemctl resolution (mirrors the fallback chain
#    already established in lane4-onbox-verification.yml + deploy.sh,
#    kept local here rather than sourced — this script's rollback path
#    must not depend on another script's tree state) ─────────────────
resolve_python_bin() {
  if [[ -n "${PYTHON_BIN:-}" && -x "${PYTHON_BIN}" ]]; then
    printf '%s\n' "${PYTHON_BIN}"
    return 0
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
PYTHON_BIN="$(resolve_python_bin)"

resolve_systemctl_bin() {
  local candidate
  for candidate in /bin/systemctl /usr/bin/systemctl; do
    [[ -x "${candidate}" ]] || continue
    if sudo -n "${candidate}" --version >/dev/null 2>&1; then
      printf '%s\n' "${candidate}"
      return 0
    fi
  done
  warn "No NOPASSWD sudo permission for systemctl (checked /bin, /usr/bin)."
  return 1
}

# ── small python helpers, run against the SAME .env every production
#    process would source (EnvironmentFile=-__APP_DIR__/.env) ─────────
env_sourced_python() {
  # Usage: env_sourced_python <python -c code...>
  ( set -a; [[ -f "${ENV_FILE}" ]] && source "${ENV_FILE}"; set +a
    cd "${APP_DIR}" && "${PYTHON_BIN}" "$@" )
}

read_flag_enabled() {
  env_sourced_python -c "
import sys
sys.path.insert(0, '.')
from src.api.feature_flags import is_enabled
print(is_enabled('${FLAG_GATE_NAME}'))
"
}

# ── preflight: read-only, refuses on any surprise ─────────────────────
run_preflight_checks() {
  log "Preflight: expected SHA, flag state, service, PBP script, artifact state."

  [[ -n "${EXPECTED_SHA}" ]] || fail_preflight "EXPECTED_SHA was not supplied."
  [[ -d "${APP_DIR}/.git" ]] || fail_preflight "APP_DIR is not a git checkout: ${APP_DIR}"

  local actual_sha
  actual_sha="$(git -C "${APP_DIR}" rev-parse HEAD)" || fail_preflight "could not read HEAD in ${APP_DIR}"
  if [[ "${actual_sha}" != "${EXPECTED_SHA}" ]]; then
    fail_preflight "deployed SHA (${actual_sha}) does not match expected (${EXPECTED_SHA})."
  fi
  log "SHA confirmed: ${actual_sha}"

  local current_enabled
  current_enabled="$(read_flag_enabled)" || fail_preflight "could not read current ${FLAG_GATE_NAME} state."
  log "Current ${FLAG_KEY} state: enabled=${current_enabled}"

  local systemctl_bin
  systemctl_bin="$(resolve_systemctl_bin)" || fail_preflight "cannot resolve a usable systemctl."
  sudo -n "${systemctl_bin}" cat "${SERVICE_NAME}" >/dev/null 2>&1 \
    || fail_preflight "systemd unit not found: ${SERVICE_NAME}"
  log "Service unit confirmed: ${SERVICE_NAME}"

  [[ -f "${APP_DIR}/scripts/build_pbp_weekly.py" ]] \
    || fail_preflight "missing scripts/build_pbp_weekly.py"
  # ast.parse rather than py_compile: preflight is read-only, and
  # py_compile would write a __pycache__/*.pyc as a side effect.
  "${PYTHON_BIN}" -c "
import ast
import sys
with open(sys.argv[1]) as fh:
    ast.parse(fh.read())
" "${APP_DIR}/scripts/build_pbp_weekly.py" \
    || fail_preflight "scripts/build_pbp_weekly.py fails to parse"
  [[ -f "${APP_DIR}/scripts/bdvm_build_baseline.py" ]] \
    || fail_preflight "missing scripts/bdvm_build_baseline.py"

  log "Current PBP artifact state (data/nfl_data/actuals/):"
  local season
  for season in "${PBP_SEASONS[@]}"; do
    local artifact="${APP_DIR}/data/nfl_data/actuals/pbp_weekly_${season}.jsonl"
    if [[ -f "${artifact}" ]]; then
      local schema
      schema="$(env_sourced_python -c "
import json
import sys
with open(sys.argv[1]) as fh:
    first = fh.readline()
try:
    print(json.loads(first).get('schemaVersion', '<none>'))
except Exception:
    print('<unparseable>')
" "${artifact}" 2>/dev/null || echo '<error>')"
      log "  ${season}: exists, schemaVersion=${schema}, mtime=$(date -u -r "${artifact}" +%Y-%m-%dT%H:%M:%SZ)"
    else
      log "  ${season}: does not exist yet"
    fi
  done

  log "Preflight OK."
}

# ── the single rollback path ───────────────────────────────────────────
do_rollback() {
  local state_dir="$1"
  local trigger_reason="$2"
  local failures=()

  log "ROLLBACK: starting (state dir: ${state_dir}; trigger: ${trigger_reason})"

  if [[ ! -d "${state_dir}" ]]; then
    warn "ROLLBACK: no state directory at ${state_dir} — nothing captured to roll back."
    return 1
  fi

  local prior_flag_file="${state_dir}/prior_flag_state.txt"
  local prior_bool_file="${state_dir}/prior_flag_enabled_bool.txt"
  local pbp_manifest_pointer="${state_dir}/pbp_backup_manifest_path.txt"

  if [[ -f "${prior_flag_file}" ]]; then
    local prior_state
    if prior_state="$(cat "${prior_flag_file}")"; then
      log "ROLLBACK: restoring ${FLAG_KEY} to captured prior state: ${prior_state}"
      "${PYTHON_BIN}" "${APP_DIR}/scripts/prod_env_flag_ops.py" restore \
        --env-file "${ENV_FILE}" --key "${FLAG_KEY}" --prior-state "${prior_state}" \
        || failures+=("env flag restore failed")
    else
      failures+=("could not read captured prior flag state from ${prior_flag_file}")
    fi
  else
    log "ROLLBACK: no captured prior flag state — flag was never changed this attempt."
  fi

  if [[ -f "${pbp_manifest_pointer}" ]]; then
    local manifest_path
    if manifest_path="$(cat "${pbp_manifest_pointer}")"; then
      log "ROLLBACK: restoring PBP artifacts from manifest: ${manifest_path}"
      "${PYTHON_BIN}" "${APP_DIR}/scripts/pbp_artifact_backup.py" restore \
        --manifest "${manifest_path}" \
        || failures+=("pbp artifact restore failed")
    else
      failures+=("could not read captured pbp backup manifest path from ${pbp_manifest_pointer}")
    fi
  else
    log "ROLLBACK: no PBP backup manifest captured — nothing to restore there."
  fi

  local systemctl_bin
  if systemctl_bin="$(resolve_systemctl_bin)"; then
    log "ROLLBACK: restarting ${SERVICE_NAME} to pick up restored .env"
    sudo -n "${systemctl_bin}" restart "${SERVICE_NAME}" || failures+=("service restart failed")
    sleep 3
    sudo -n "${systemctl_bin}" is-active --quiet "${SERVICE_NAME}" \
      || failures+=("service not active after rollback restart")
  else
    failures+=("could not resolve systemctl to restart the service")
  fi

  if ! curl -fsS --max-time 10 "http://${APP_HOST}:${APP_PORT}/api/status" >/dev/null; then
    failures+=("health check (/api/status) failed after rollback")
  fi

  if [[ -f "${prior_bool_file}" ]]; then
    local expected_bool actual_bool
    if expected_bool="$(cat "${prior_bool_file}")"; then
      actual_bool="$(read_flag_enabled || echo '<error>')"
      if [[ "${actual_bool}" != "${expected_bool}" ]]; then
        failures+=("post-rollback flag state (${actual_bool}) does not match pre-activation state (${expected_bool})")
      else
        log "ROLLBACK: verified flag state matches pre-activation (${actual_bool})."
      fi
    else
      failures+=("could not read captured prior flag boolean from ${prior_bool_file}")
    fi
  fi

  if (( ${#failures[@]} > 0 )); then
    printf '[v1-49][ROLLBACK FAILED] MANUAL INTERVENTION REQUIRED:\n' >&2
    local f
    for f in "${failures[@]}"; do
      printf '  - %s\n' "${f}" >&2
    done
    echo "ROLLBACK_FAILED" > "${state_dir}/result.txt"
    return 1
  fi

  log "ROLLBACK: complete and verified."
  echo "ROLLED_BACK" > "${state_dir}/result.txt"
  return 0
}

# ── controlled activation ──────────────────────────────────────────────
do_activate() {
  [[ -n "${ACTIVATION_ID}" ]] || fail_preflight "ACTIVATION_ID was not supplied."
  validate_activation_id "${ACTIVATION_ID}"
  [[ -n "${BDVM_SEASON}" ]] || fail_preflight "BDVM_SEASON was not supplied."

  run_preflight_checks

  local state_dir="${STATE_ROOT}/${ACTIVATION_ID}"
  mkdir -p "${state_dir}"
  mkdir -p "${STATE_ROOT}"
  printf '%s\n' "${ACTIVATION_ID}" > "${LATEST_POINTER}"
  printf '%s\n' "${REASON}" > "${state_dir}/reason.txt"
  printf '%s\n' "${EXPECTED_SHA}" > "${state_dir}/expected_sha.txt"
  date -u +%Y-%m-%dT%H:%M:%SZ > "${state_dir}/started_at_utc.txt"

  local activation_failed=0
  on_activation_error() {
    local exit_code=$?
    trap - ERR
    printf '[v1-49][ERROR] activation step failed (exit %s); invoking automatic rollback.\n' "${exit_code}" >&2
    if do_rollback "${state_dir}" "automatic (activation step failed, exit ${exit_code})"; then
      log "Automatic rollback succeeded. This remains a FAILED V1-49 verification attempt."
      exit 2
    else
      exit 3
    fi
  }
  trap on_activation_error ERR

  # 1. Backup current PBP artifacts BEFORE anything else changes.
  log "Backing up current PBP artifacts."
  local backup_json manifest_path
  backup_json="$("${PYTHON_BIN}" "${APP_DIR}/scripts/pbp_artifact_backup.py" backup \
    --actuals-dir "${APP_DIR}/data/nfl_data/actuals" \
    --seasons "${PBP_SEASONS[@]}")"
  manifest_path="$(env_sourced_python -c "import json,sys; print(json.loads(sys.argv[1])['manifestPath'])" "${backup_json}")"
  printf '%s\n' "${manifest_path}" > "${state_dir}/pbp_backup_manifest_path.txt"
  log "PBP backup manifest: ${manifest_path}"

  # 2. BDVM baseline BEFORE the flip — captures champion-scoring output.
  local bdvm_pre_label="v149_pre_${ACTIVATION_ID}"
  log "Building BDVM pre-activation snapshot (label=${bdvm_pre_label})."
  env_sourced_python "${APP_DIR}/scripts/bdvm_build_baseline.py" \
    --season "${BDVM_SEASON}" --label "${bdvm_pre_label}"
  local bdvm_pre_path
  bdvm_pre_path="$(find "${APP_DIR}/data/bdvm/projections/${BDVM_SEASON}" -name "projections_*_${bdvm_pre_label}.json" -newer "${state_dir}/started_at_utc.txt" -print -quit)"
  [[ -n "${bdvm_pre_path}" ]] || bdvm_pre_path="$(find "${APP_DIR}/data/bdvm/projections/${BDVM_SEASON}" -name "projections_*_${bdvm_pre_label}.json" -print -quit)"
  [[ -n "${bdvm_pre_path}" ]] || { warn "could not locate the BDVM pre-activation snapshot on disk"; false; }
  printf '%s\n' "${bdvm_pre_path}" > "${state_dir}/bdvm_pre_snapshot_path.txt"
  log "BDVM pre-activation snapshot: ${bdvm_pre_path}"

  # 3. Capture prior flag state and flip.
  local prior_bool
  prior_bool="$(read_flag_enabled)"
  printf '%s\n' "${prior_bool}" > "${state_dir}/prior_flag_enabled_bool.txt"

  local set_json prior_state
  set_json="$("${PYTHON_BIN}" "${APP_DIR}/scripts/prod_env_flag_ops.py" set \
    --env-file "${ENV_FILE}" --key "${FLAG_KEY}" --value "1")"
  prior_state="$(env_sourced_python -c "import json,sys; print(json.loads(sys.argv[1])['prior_state'])" "${set_json}")"
  printf '%s\n' "${prior_state}" > "${state_dir}/prior_flag_state.txt"
  log "Flag flipped. Prior raw state: ${prior_state} (enabled=${prior_bool})"

  # 4. Restart the ONLY service that needs it, then health-check.
  local systemctl_bin
  systemctl_bin="$(resolve_systemctl_bin)"
  log "Restarting ${SERVICE_NAME}."
  sudo -n "${systemctl_bin}" restart "${SERVICE_NAME}"
  sleep 3
  sudo -n "${systemctl_bin}" is-active --quiet "${SERVICE_NAME}"
  curl -fsS --max-time 10 "http://${APP_HOST}:${APP_PORT}/api/status" >/dev/null
  log "Service restarted and healthy."

  # 5. Paranoia check: the flag now reads enabled.
  local now_bool
  now_bool="$(read_flag_enabled)"
  if [[ "${now_bool}" != "True" ]]; then
    warn "Flag does not read enabled after restart (got: ${now_bool})."
    false
  fi
  log "Confirmed ${FLAG_KEY} is now enabled."

  # 6. Rebuild the PBP artifact for the full named season set.
  log "Rebuilding PBP weekly artifacts for seasons: ${PBP_SEASONS[*]}"
  local pbp_rc=0
  env_sourced_python "${APP_DIR}/scripts/build_pbp_weekly.py" \
    --seasons "${PBP_SEASONS[@]}" || pbp_rc=$?
  # Exit 2 ("nothing to do / already current") is a healthy outcome per
  # the script's own systemd unit (SuccessExitStatus=0 2); exit 1 (a
  # season that should exist produced no plays) is a real failure.
  if [[ "${pbp_rc}" != "0" && "${pbp_rc}" != "2" ]]; then
    warn "build_pbp_weekly.py exited ${pbp_rc}"
    false
  fi
  log "PBP rebuild finished (exit ${pbp_rc})."

  # 7. Validate every rebuilt artifact against the CURRENT schema via the
  #    canonical loader — never a re-implementation of its refusal rule.
  log "Validating rebuilt PBP artifacts against the current schema."
  env_sourced_python -c "
import sys
sys.path.insert(0, '.')
from src.nfl_data.pbp_weekly import load_pbp_weekly
seasons = [${PBP_SEASONS[*]/%/,}]
refused = [s for s in seasons if load_pbp_weekly(s) is None]
if refused:
    print('REFUSED or missing after rebuild:', refused, file=sys.stderr)
    sys.exit(1)
print('All seasons loaded and validated against the current schema:', seasons)
"

  # 8. BDVM baseline AFTER the flip — captures challenger-scoring output.
  local bdvm_post_label="v149_post_${ACTIVATION_ID}"
  log "Building BDVM post-activation snapshot (label=${bdvm_post_label})."
  env_sourced_python "${APP_DIR}/scripts/bdvm_build_baseline.py" \
    --season "${BDVM_SEASON}" --label "${bdvm_post_label}"
  local bdvm_post_path
  bdvm_post_path="$(find "${APP_DIR}/data/bdvm/projections/${BDVM_SEASON}" -name "projections_*_${bdvm_post_label}.json" -print -quit)"
  [[ -n "${bdvm_post_path}" ]] || { warn "could not locate the BDVM post-activation snapshot on disk"; false; }
  printf '%s\n' "${bdvm_post_path}" > "${state_dir}/bdvm_post_snapshot_path.txt"
  log "BDVM post-activation snapshot: ${bdvm_post_path}"

  # 9. Diff the two BDVM snapshots — item 1 of the promotion gate.
  log "Diffing BDVM pre/post snapshots."
  local bdvm_diff_json="${state_dir}/bdvm_diff.json"
  "${PYTHON_BIN}" "${APP_DIR}/scripts/diff_bdvm_snapshots.py" \
    --before "${bdvm_pre_path}" --after "${bdvm_post_path}" > "${bdvm_diff_json}"
  log "BDVM diff written: ${bdvm_diff_json}"
  cat "${bdvm_diff_json}"

  # 10. League-comparison OBSERVATION — item 2 of the promotion gate.
  #     Deliberately does NOT trigger rollback on a non-200: this
  #     endpoint's own contract treats upstream unavailability (503) as
  #     normal, and conflating that with an activation failure would be
  #     exactly the "reinterpret failure as success" mistake in reverse
  #     — turning an unrelated upstream hiccup into a false activation
  #     failure. Recorded honestly either way.
  log "Probing GET /api/league-comparison?refresh=1 (uncontrolled in-season observation — see header notes)."
  local lc_http_code lc_body_file="${state_dir}/league_comparison_response.json"
  lc_http_code="$(curl -sS --max-time 30 -o "${lc_body_file}" -w '%{http_code}' \
    "http://${APP_HOST}:${APP_PORT}/api/league-comparison?refresh=1" || echo "curl_error")"
  log "league-comparison probe HTTP status: ${lc_http_code}"

  # 11. Write the final structured report and mark success.
  #
  # Every dynamic value here — REASON above all, which is free-text
  # operator input from the workflow_dispatch form — is passed through
  # the environment and read via os.environ, never interpolated into
  # the Python source text. String-interpolating REASON into a
  # triple-quoted literal would let its content break out of the string
  # and execute as Python; os.environ has no such boundary to escape.
  trap - ERR
  REPORT_ACTIVATION_ID="${ACTIVATION_ID}" \
  REPORT_EXPECTED_SHA="${EXPECTED_SHA}" \
  REPORT_REASON="${REASON}" \
  REPORT_PRIOR_FLAG_RAW="${prior_state}" \
  REPORT_PRIOR_FLAG_BOOL="${prior_bool}" \
  REPORT_PBP_MANIFEST="${manifest_path}" \
  REPORT_PBP_RC="${pbp_rc}" \
  REPORT_BDVM_PRE="${bdvm_pre_path}" \
  REPORT_BDVM_POST="${bdvm_post_path}" \
  REPORT_LC_HTTP="${lc_http_code}" \
  REPORT_STATE_DIR="${state_dir}" \
  env_sourced_python -c "
import json
import os

report = {
    'activationId': os.environ['REPORT_ACTIVATION_ID'],
    'expectedSha': os.environ['REPORT_EXPECTED_SHA'],
    'reason': os.environ['REPORT_REASON'],
    'priorFlagRawState': os.environ['REPORT_PRIOR_FLAG_RAW'],
    'priorFlagEnabled': os.environ['REPORT_PRIOR_FLAG_BOOL'],
    'pbpBackupManifest': os.environ['REPORT_PBP_MANIFEST'],
    'pbpRebuildExitCode': int(os.environ['REPORT_PBP_RC']),
    'bdvmPreSnapshot': os.environ['REPORT_BDVM_PRE'],
    'bdvmPostSnapshot': os.environ['REPORT_BDVM_POST'],
    'item2LeagueComparisonHttpStatus': os.environ['REPORT_LC_HTTP'],
    'item2Label': 'uncontrolled in-season observation, not a controlled diff -- see script header',
    'item3Label': (
        'no dedicated historical-backtest script exists in this repo; '
        'treated as satisfied by the item 1 (BDVM) and item 4 (PBP) '
        'measured deltas above, per HOST_NATIVE_SCORING_VALIDATION.md '
        'own framing of item 3 as downstream of items 1+4'
    ),
}
state_dir = os.environ['REPORT_STATE_DIR']
with open(os.path.join(state_dir, 'report.json'), 'w') as fh:
    json.dump(report, fh, indent=2)
print(json.dumps(report, indent=2))
"
  echo "ACTIVATED" > "${state_dir}/result.txt"
  log "Activation complete."
}

do_rollback_action() {
  local activation_id="${ACTIVATION_ID}"
  if [[ -z "${activation_id}" ]]; then
    [[ -f "${LATEST_POINTER}" ]] || { echo "[v1-49][ERROR] no ACTIVATION_ID given and no LATEST pointer exists." >&2; exit 1; }
    activation_id="$(cat "${LATEST_POINTER}")" \
      || { echo "[v1-49][ERROR] could not read LATEST pointer: ${LATEST_POINTER}" >&2; exit 1; }
    log "No ACTIVATION_ID supplied; using LATEST: ${activation_id}"
  fi
  validate_activation_id "${activation_id}"
  local state_dir="${STATE_ROOT}/${activation_id}"
  [[ -d "${state_dir}" ]] || { echo "[v1-49][ERROR] no state directory for activation id: ${activation_id}" >&2; exit 1; }
  if do_rollback "${state_dir}" "explicit rollback dispatch (${REASON})"; then
    exit 0
  else
    exit 3
  fi
}

main() {
  case "${ACTION}" in
    preflight)
      run_preflight_checks
      ;;
    activate)
      do_activate
      ;;
    rollback)
      do_rollback_action
      ;;
    *)
      echo "[v1-49][ERROR] ACTION must be one of: preflight, activate, rollback (got: '${ACTION}')" >&2
      exit 1
      ;;
  esac
}

# Run main only when EXECUTED, not when sourced — mirrors
# deploy/rollback.sh's own guard. Sourcing is how a test can call
# individual functions (e.g. validate_activation_id) in isolation
# without dispatching a real preflight/activate/rollback.
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
