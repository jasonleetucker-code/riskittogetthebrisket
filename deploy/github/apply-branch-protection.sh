#!/usr/bin/env bash
# Apply the `main` branch ruleset from main-protection-ruleset.json.
#
# Usage (from the repo root, with an ADMIN-scoped token):
#   GH_TOKEN=<admin token> bash deploy/github/apply-branch-protection.sh
#   GH_TOKEN=<admin token> bash deploy/github/apply-branch-protection.sh --dry-run
#
# Env overrides:
#   GH_TOKEN   required. Needs `administration: write` on the repo.
#              A default GITHUB_TOKEN in Actions does NOT have it, and
#              neither does an agent session's credential — which is why
#              this is a script you run rather than something automated.
#   REPO       owner/name.  Default: jasonleetucker-code/riskittogetthebrisket
#   RULESET    payload path. Default: alongside this script.
#
# Why a script and not the settings UI: OA-02 in
# docs/OWNER_ACTION_AUDIT_2026-07-29.md is a 12-field click-through, and
# the field that matters most (the required status check) has to be typed
# exactly. That doc named `E2E Safety Net` — a WORKFLOW name, which GitHub's
# picker never matches, because it matches JOB names. A payload in the repo
# is reviewable, diffable, and cannot be mistyped.
#
# Idempotent: updates the existing `main-protection` ruleset if one exists,
# creates it otherwise.
#
# Exit code: 0 applied (or dry run OK), 1 otherwise.

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

REPO="${REPO:-jasonleetucker-code/riskittogetthebrisket}"
RULESET="${RULESET:-${SCRIPT_DIR}/main-protection-ruleset.json}"
DRY_RUN="false"

log() { printf '[ruleset] %s\n' "$*"; }
warn() { printf '[ruleset][WARN] %s\n' "$*" >&2; }
error() { printf '[ruleset][ERROR] %s\n' "$*" >&2; }

require_command() {
  command -v "$1" >/dev/null 2>&1 || {
    error "missing required command: $1"
    exit 1
  }
}

main() {
  for arg in "$@"; do
    case "${arg}" in
      --dry-run) DRY_RUN="true" ;;
      *)
        error "unknown argument: ${arg}"
        exit 1
        ;;
    esac
  done

  require_command curl
  require_command python3

  [[ -f "${RULESET}" ]] || {
    error "payload not found: ${RULESET}"
    exit 1
  }

  # Strip the _comment key — GitHub rejects unknown top-level fields.
  local payload
  payload="$(python3 -c '
import json, sys
d = json.load(open(sys.argv[1]))
d.pop("_comment", None)
json.dump(d, sys.stdout)
' "${RULESET}")" || {
    error "payload is not valid JSON: ${RULESET}"
    exit 1
  }

  log "repo    ${REPO}"
  log "payload ${RULESET}"
  log "checks  $(python3 -c '
import json,sys
d=json.load(open(sys.argv[1]))
for r in d["rules"]:
    if r["type"]=="required_status_checks":
        print(", ".join(c["context"] for c in r["parameters"]["required_status_checks"]))
' "${RULESET}")"

  if [[ "${DRY_RUN}" == "true" ]]; then
    log "--dry-run: payload validated, nothing sent."
    log "Re-run without --dry-run and with an admin GH_TOKEN to apply."
    return 0
  fi

  [[ -n "${GH_TOKEN:-}" ]] || {
    error "GH_TOKEN is not set. It needs 'administration: write' on ${REPO}."
    error "Without it GitHub answers 403 and the ruleset is NOT applied."
    exit 1
  }

  local api="https://api.github.com/repos/${REPO}/rulesets"
  local existing
  existing="$(curl -sS -H "Authorization: Bearer ${GH_TOKEN}" \
    -H "Accept: application/vnd.github+json" "${api}" |
    python3 -c '
import json, sys
try:
    rs = json.load(sys.stdin)
except Exception:
    sys.exit(0)
if isinstance(rs, list):
    for r in rs:
        if r.get("name") == "main-protection":
            print(r.get("id", ""))
            break
')" || true

  local method url
  if [[ -n "${existing}" ]]; then
    log "updating existing ruleset id=${existing}"
    method="PUT"
    url="${api}/${existing}"
  else
    log "creating a new ruleset"
    method="POST"
    url="${api}"
  fi

  local code
  code="$(curl -sS -o /tmp/ruleset-response.json -w '%{http_code}' \
    -X "${method}" "${url}" \
    -H "Authorization: Bearer ${GH_TOKEN}" \
    -H "Accept: application/vnd.github+json" \
    -H "Content-Type: application/json" \
    -d "${payload}")"

  if [[ "${code}" == "200" || "${code}" == "201" ]]; then
    log "applied (HTTP ${code})."
    log "Verify: an empty commit pushed straight to main must be REJECTED."
    log "  git commit --allow-empty -m 'protection check' && git push origin main"
    log "  # expect: GH006 Protected branch update failed"
    log "  git reset --hard HEAD~1"
    return 0
  fi

  error "GitHub returned HTTP ${code}"
  sed -n '1,20p' /tmp/ruleset-response.json >&2 || true
  if [[ "${code}" == "403" || "${code}" == "404" ]]; then
    error "That is the signature of a token without 'administration: write'."
  fi
  exit 1
}

main "$@"
