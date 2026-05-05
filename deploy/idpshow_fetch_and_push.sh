#!/usr/bin/env bash
#
# idpshow_fetch_and_push.sh - prod-side IDP Show refresh + commit-back
#                             to main.
#
# Why this script lives on prod, not in CI:
#
#   The IDP Show is a Substack paywalled rankings page with a
#   CAPTCHA-protected login flow.  We can't solve the CAPTCHA
#   headlessly, so the fetcher (``scripts/fetch_idpshow.py``) reads
#   cached cookies from ``idpshow_session.json`` instead of logging in
#   each cycle.  That session file is gitignored (cookies are session
#   credentials), and re-authenticating requires a human to solve the
#   CAPTCHA in a browser.  So the file lives only on prod, where the
#   operator originally minted it.
#
#   This is the same constraint that put DLF on a prod timer (Cloudflare
#   IP-blocks GitHub Actions).  The mechanics here are identical;
#   only the script + paths differ.
#
# Operates in a dedicated clone at ``/var/lib/idpshow-fetch/repo`` so
# the live deploy directory is never touched (no race with deploy.sh,
# the FastAPI service, or the auto-refresh CSV churn that lives in the
# live repo).
#
# Sequence:
#   1. Initial run: clone the repo into the dedicated work dir.
#   2. fetch + reset --hard origin/main so we always start from the
#      latest CI-committed state.
#   3. Pull cached cookies from ``$WORK_DIR/idpshow_session.json``.
#   4. Run ``scripts/fetch_idpshow.py``.  The fetcher refreshes its
#      own cookie expiry on success; we copy the result back.
#   5. Stamp ``data/scrape_state/idpShow_last_success`` with the
#      current epoch, stage the CSV + stamp, commit, push.  Push
#      retries on rebase conflict (CI's data-refresh cron also
#      pushes to main every 2h).

set -Eeuo pipefail

WORK_DIR="${IDPSHOW_FETCH_WORK_DIR:-/var/lib/idpshow-fetch}"
REPO_DIR="${WORK_DIR}/repo"
REPO_URL="${IDPSHOW_FETCH_REPO_URL:-git@github.com:jasonleetucker-code/riskittogetthebrisket.git}"
SESSION_FILE="${WORK_DIR}/idpshow_session.json"
VENV_PYTHON="${IDPSHOW_FETCH_PYTHON:-/home/dynasty/.venvs/trade-calculator/bin/python}"
SSH_KEY="${IDPSHOW_FETCH_SSH_KEY:-${HOME}/.ssh/github_deploy_key}"

GIT_AUTHOR_NAME="${IDPSHOW_FETCH_GIT_NAME:-IDP Show Fetch (prod)}"
GIT_AUTHOR_EMAIL="${IDPSHOW_FETCH_GIT_EMAIL:-idpshow-fetch@brisket-prod-1.local}"

PUSH_RETRY_MAX=3

log() { printf '[idpshow-fetch] %s\n' "$*"; }
err() { printf '[idpshow-fetch][ERR] %s\n' "$*" >&2; }

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

if [[ -f "${SESSION_FILE}" ]]; then
  cp -f "${SESSION_FILE}" "${REPO_DIR}/idpshow_session.json"
fi

# fetch_idpshow.py expects to find idpshow_session.json in the repo
# root.  Bail out if it's missing - re-authentication needs a human.
if [[ ! -f "${REPO_DIR}/idpshow_session.json" ]]; then
  err "idpshow_session.json missing - cookie-based auth cannot proceed."
  err "Re-mint the session via the operator's browser and copy to ${SESSION_FILE}."
  exit 1
fi

log "running scripts/fetch_idpshow.py"
if ! "${VENV_PYTHON}" scripts/fetch_idpshow.py; then
  err "fetch_idpshow.py exited non-zero - keeping previous CSV / stamp; will retry on next timer fire."
  exit 1
fi

# Persist the (possibly refreshed) session jar back to the work dir
# so the next run can skip re-checking the cookie.
if [[ -f "${REPO_DIR}/idpshow_session.json" ]]; then
  cp -f "${REPO_DIR}/idpshow_session.json" "${SESSION_FILE}"
  chmod 600 "${SESSION_FILE}"
fi

mkdir -p data/scrape_state
date -u +%s > data/scrape_state/idpShow_last_success

# Force-add the stamp because data/ is gitignored at the repo level
# (data/scrape_state/ is the carve-out we want tracked) - matches the
# scheduled-refresh.yml "Commit updated data" step.
git add -f -- \
  CSVs/site_raw/idpShow.csv \
  data/scrape_state/idpShow_last_success

if git diff --cached --quiet; then
  log "no changes after fetch - exiting clean"
  exit 0
fi

COMMIT_MSG="chore(idpshow): automated refresh $(date -u +%Y-%m-%dT%H:%M:%SZ)"
log "committing: ${COMMIT_MSG}"
git -c user.name="${GIT_AUTHOR_NAME}" -c user.email="${GIT_AUTHOR_EMAIL}" \
    commit -m "${COMMIT_MSG}"

attempt=1
while (( attempt <= PUSH_RETRY_MAX )); do
  if git push origin main; then
    log "push succeeded on attempt ${attempt}/${PUSH_RETRY_MAX}"
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
