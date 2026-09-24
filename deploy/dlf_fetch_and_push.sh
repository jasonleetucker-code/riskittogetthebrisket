#!/usr/bin/env bash
#
# dlf_fetch_and_push.sh - prod-side DLF refresh + commit-back to main.
#
# Why this script lives on prod, not in CI:
#
#   DLF sits behind a Cloudflare ruleset that 403s any GET to
#   wp-login.php from GitHub Actions IP ranges, before our credentials
#   are even sent.  The same ``scripts/fetch_dlf.py`` succeeds from
#   prod's residential-ish VPS IP (curl_cffi chrome131
#   impersonation passes CF, then WP login succeeds).  This is the
#   same pattern ``fetch_idpshow.py`` already uses - the
#   scheduled-refresh CI step explicitly skips it with the comment
#   "scraper runs on the production server where the session file
#   is maintained".  We extend that pattern to DLF.
#
# Operates in a dedicated clone at ``/var/lib/dlf-fetch/repo`` so the
# live deploy directory (``/home/dynasty/trade-calculator``) is never
# touched - eliminates any race with deploy.sh, the FastAPI service,
# or the auto-refresh CSV churn that lives in the live repo.
#
# Sequence:
#   1. Initial run: clone the repo into the dedicated work dir.
#   2. fetch + reset --hard origin/main so we always start from the
#      latest CI-committed state.
#   3. Pull cached cookies from ``$WORK_DIR/dlf_session.json``
#      (persists across runs; auto-refreshed by fetch_dlf.py when WP
#      invalidates the session).
#   4. Run ``scripts/fetch_dlf.py`` with credentials from the systemd
#      EnvironmentFile (DLF_USERNAME + DLF_PASSWORD).
#   5. On success: stamp ``data/scrape_state/dlf_last_success`` with
#      the current epoch, stage the four CSVs + the stamp, commit,
#      push.  Push retries on rebase conflict (CI's data-refresh
#      cron also pushes to main every 2h).
#
# Idempotent: if fetch_dlf.py reports no row changes (or only
# rank-jitter) the staged diff is empty and we exit clean without
# committing.
#
# Logs to stdout/stderr; the systemd unit pipes both into the
# journal (journalctl -u dynasty-dlf-fetch.service).

set -Eeuo pipefail

WORK_DIR="${DLF_FETCH_WORK_DIR:-/var/lib/dlf-fetch}"
REPO_DIR="${WORK_DIR}/repo"
REPO_URL="${DLF_FETCH_REPO_URL:-git@github.com:jasonleetucker-code/riskittogetthebrisket.git}"
SESSION_FILE="${WORK_DIR}/dlf_session.json"
VENV_PYTHON="${DLF_FETCH_PYTHON:-/home/dynasty/.venvs/trade-calculator/bin/python}"
SSH_KEY="${DLF_FETCH_SSH_KEY:-${HOME}/.ssh/github_deploy_key}"

GIT_AUTHOR_NAME="${DLF_FETCH_GIT_NAME:-DLF Fetch (prod)}"
GIT_AUTHOR_EMAIL="${DLF_FETCH_GIT_EMAIL:-dlf-fetch@brisket-prod-1.local}"

PUSH_RETRY_MAX=3

log() { printf '[dlf-fetch] %s\n' "$*"; }
err() { printf '[dlf-fetch][ERR] %s\n' "$*" >&2; }

# Use the deploy key for all git operations in this script.  The live
# repo at /home/dynasty/trade-calculator already has core.sshcommand
# pinned to this key, but the dedicated clone is fresh, so we set it
# via env instead of repo config.
export GIT_SSH_COMMAND="ssh -i ${SSH_KEY} -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"

mkdir -p "${WORK_DIR}"

if [[ ! -d "${REPO_DIR}/.git" ]]; then
  log "first run - cloning ${REPO_URL} into ${REPO_DIR}"
  git clone "${REPO_URL}" "${REPO_DIR}"
fi

cd "${REPO_DIR}"

log "syncing to origin/main"
git fetch --prune origin main
git checkout -B main origin/main
git reset --hard origin/main

# Restore cookie jar from the work-dir-persistent location.  fetch_dlf.py
# will auto-refresh + rewrite this file on success; we copy the result
# back at the end.  Missing on first run is fine - fetch_dlf.py will
# fall through to a full WP login.
if [[ -f "${SESSION_FILE}" ]]; then
  cp -f "${SESSION_FILE}" "${REPO_DIR}/dlf_session.json"
fi

# DLF_USERNAME / DLF_PASSWORD come from the systemd EnvironmentFile
# (the live repo's .env).  Verify they're set so we fail fast with a
# clean message instead of fetch_dlf.py's noisier traceback.
if [[ -z "${DLF_USERNAME:-}" || -z "${DLF_PASSWORD:-}" ]]; then
  err "DLF_USERNAME / DLF_PASSWORD not set in environment - check the systemd unit's EnvironmentFile=."
  exit 1
fi

log "running scripts/fetch_dlf.py"
# PARTIAL SUCCESS IS PUSHED (2026-09-23).  fetch_dlf.py exits non-zero when
# ANY board fails or refuses to overwrite its last-good CSV (e.g. the #1297
# native-Value coverage guard on dlfSf) — but it still writes every board
# that passed.  This script used to discard ALL of them on any non-zero exit,
# so one refusing board froze all four boards and every DLF stamp from
# 2026-09-09 onward.  Now the boards it actually wrote (``--written-manifest``)
# are committed with their per-key stamps and dataset state; the aggregate
# ``dlf_last_success`` stamp still requires a fully clean run, and the unit
# still exits non-zero so the failure stays visible in the journal.
MANIFEST="${WORK_DIR}/dlf_written.json"
FETCH_RC=0
"${VENV_PYTHON}" scripts/fetch_dlf.py --written-manifest "${MANIFEST}" || FETCH_RC=$?
mapfile -t WRITTEN < <("${VENV_PYTHON}" -c 'import json,sys; print("\n".join(json.load(open(sys.argv[1]))))' "${MANIFEST}" 2>/dev/null || true)
if [[ "${FETCH_RC}" -ne 0 && "${#WRITTEN[@]}" -eq 0 ]]; then
  err "fetch_dlf.py exited ${FETCH_RC} and wrote no board - keeping previous CSVs / stamps; will retry on next timer fire."
  exit 1
fi
if [[ "${FETCH_RC}" -ne 0 ]]; then
  err "fetch_dlf.py exited ${FETCH_RC}; committing only the boards it wrote: ${WRITTEN[*]}"
else
  WRITTEN=(dlfSf dlfIdp dlfRookieSf dlfRookieIdp dlfValuesSfTep)
fi

# Persist the (possibly refreshed) session jar back to the work dir so
# the next run can skip the WP login round-trip.
if [[ -f "${REPO_DIR}/dlf_session.json" ]]; then
  cp -f "${REPO_DIR}/dlf_session.json" "${SESSION_FILE}"
  chmod 600 "${SESSION_FILE}"
fi

# Stamp last-successful-fetch epoch.  ``Assert DLF freshness`` in
# scheduled-refresh.yml reads ``dlf_last_success``'s CONTENT (not its
# mtime, which actions/checkout resets) and red-Xes the workflow when
# the epoch is more than 24h behind ``date +%s``.
#
# We also stamp per-registry-key files (dlfSf / dlfIdp / dlfRookieSf
# / dlfRookieIdp) so ``server._per_source_freshness`` — which looks
# up stamps by registry key, not vendor name — finds them.  Without
# the per-key stamps, the freshness reader falls through to CSV
# mtime, which freezes on prod's ``git checkout --force`` whenever
# DLF re-publishes byte-identical content (common for rookie boards
# in the off-season), tripping false-positive 24h stale alerts.
mkdir -p data/scrape_state
NOW_EPOCH="$(date -u +%s)"
for key in "${WRITTEN[@]}"; do
  printf '%s\n' "${NOW_EPOCH}" > "data/scrape_state/${key}_last_success"
done
# The aggregate ``dlf_last_success`` (read by scheduled-refresh.yml's "Assert
# DLF freshness") means "every DLF RANK board refreshed".  It deliberately
# ignores dlfValuesSfTep: a Trade Analyzer Values failure must never raise the
# rank boards' freshness alarm, and vice versa — each board has its own stamp,
# dataset state and health (owner directive 2026-09-24).
RANK_BOARDS_WRITTEN=0
for key in dlfSf dlfIdp dlfRookieSf dlfRookieIdp; do
  if [[ " ${WRITTEN[*]} " == *" ${key} "* ]]; then
    RANK_BOARDS_WRITTEN=$((RANK_BOARDS_WRITTEN + 1))
  fi
done
if [[ "${RANK_BOARDS_WRITTEN}" -eq 4 ]]; then
  printf '%s\n' "${NOW_EPOCH}" > "data/scrape_state/dlf_last_success"
fi

# Source dataset state (freshness-aware weighting): when did each DLF board's
# DATA last change.  This timer is the ONE writer of the DLF boards' state
# (the GitHub refresh skips them).  Only boards written this run are
# recorded; a refused board keeps its last observation, so its data age keeps
# growing honestly.  Non-fatal.
"${VENV_PYTHON}" scripts/record_source_datasets.py --only "${WRITTEN[@]}" \
  || err "record_source_datasets.py failed - dataset state left at its last observation"
DATASET_PATHS=()
for key in "${WRITTEN[@]}"; do
  if [[ -f "data/scrape_state/${key}_dataset.json" ]]; then
    DATASET_PATHS+=("data/scrape_state/${key}_dataset.json")
  fi
done

# Stage only the paths we own.  No -A/-u, no broad globs - if
# anything else in the dedicated clone got modified, ignore it.  Use
# -f because data/ is gitignored at the repo level - matches the
# "Commit updated data" step in scheduled-refresh.yml which also
# force-adds data/scrape_state/ for the same reason.
# Existing paths only: a board that has never been written (dlfValuesSfTep
# before its first successful capture) has no CSV yet, and one missing
# pathspec would abort the whole add — and with it every healthy board.
OWNED_PATHS=(data/scrape_state/dlf_last_success CSVs/site_raw/dlfValuesSfTepPicks.csv)
for key in dlfSf dlfIdp dlfRookieSf dlfRookieIdp dlfValuesSfTep; do
  OWNED_PATHS+=("CSVs/site_raw/${key}.csv" "data/scrape_state/${key}_last_success")
done
STAGE=()
for path in "${OWNED_PATHS[@]}"; do
  if [[ -e "${path}" ]]; then
    STAGE+=("${path}")
  fi
done
git add -f -- "${STAGE[@]}" "${DATASET_PATHS[@]}"

if git diff --cached --quiet; then
  log "no changes after fetch - exiting clean"
  exit 0
fi

COMMIT_MSG="chore(dlf): automated refresh $(date -u +%Y-%m-%dT%H:%M:%SZ)"
log "committing: ${COMMIT_MSG}"
git -c user.name="${GIT_AUTHOR_NAME}" -c user.email="${GIT_AUTHOR_EMAIL}" \
    commit -m "${COMMIT_MSG}"

# Retry push on rebase conflict.  scheduled-refresh.yml pushes to main
# every 2h on its own cron; the windows can overlap.  ``pull --rebase``
# replays our single DLF commit on top of any newer CI commit; conflicts
# on the four CSVs are impossible (CI's data-refresh step doesn't
# touch dlf*.csv anymore - the workflow change in this same PR removes
# its DLF fetch step).  Conflicts on the freshness stamp would mean two
# successful fetches landed in the same window - take ours, it's newer.
attempt=1
while (( attempt <= PUSH_RETRY_MAX )); do
  if git push origin main; then
    log "push succeeded on attempt ${attempt}/${PUSH_RETRY_MAX}"
    # A partial run pushed what it could but is still a failure to see.
    if [[ "${FETCH_RC}" -ne 0 ]]; then
      exit 1
    fi
    exit 0
  fi
  log "push rejected on attempt ${attempt}/${PUSH_RETRY_MAX} - rebasing and retrying"
  git fetch origin main
  if ! git pull --rebase --strategy-option=theirs origin main; then
    err "rebase failed - manual intervention required."
    exit 1
  fi
  attempt=$((attempt + 1))
done

err "push still rejected after ${PUSH_RETRY_MAX} attempts - giving up; will retry on next timer fire."
exit 1
