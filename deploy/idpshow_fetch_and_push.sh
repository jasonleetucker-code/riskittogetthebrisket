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
#   4. Run ``scripts/fetch_idpshow.py`` (IDP-only board, unregistered/
#      diagnostic) and ``scripts/fetch_idpshow.py --combined`` (the
#      COMBINED offense+IDP board — the provider family's sole VOTING
#      source as of 2026-08-20).  Both read the same session jar; the
#      fetcher only READS it — no code path rewrites cookies; re-mints
#      are human-made directly into ``$WORK_DIR``, which stays the
#      source of truth.
#   5. Stamp ``data/scrape_state/idpShow_last_success`` and
#      ``data/scrape_state/idpShowCombined_last_success`` with the
#      current epoch, stage both CSVs + stamps, commit, push.  Push
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

# Two boards, one paywalled article family, one session cookie.
# idpShowCombined is the VOTING board (see
# src/api/data_contract.py::_RANKING_SOURCES) as of 2026-08-20 — it
# must stay on the same refresh cadence as the retired idpShow.csv,
# which is now acquisition-only (unregistered, kept for diagnostics).
# Each fetch is independent: one board's fetch failing does not block
# committing the other board's successful refresh, and only a
# same-run failure of BOTH aborts the whole push.
DEFAULT_FETCH_OK=1
COMBINED_FETCH_OK=1

log "running scripts/fetch_idpshow.py (IDP-only board, unregistered/diagnostic)"
if ! "${VENV_PYTHON}" scripts/fetch_idpshow.py; then
  err "fetch_idpshow.py exited non-zero - keeping previous CSV / stamp."
  DEFAULT_FETCH_OK=0
fi

log "running scripts/fetch_idpshow.py --combined (VOTING board)"
if ! "${VENV_PYTHON}" scripts/fetch_idpshow.py --combined; then
  err "fetch_idpshow.py --combined exited non-zero - keeping previous CSV / stamp."
  COMBINED_FETCH_OK=0
fi

if [[ "${DEFAULT_FETCH_OK}" -eq 0 && "${COMBINED_FETCH_OK}" -eq 0 ]]; then
  err "both idpShow fetches failed - nothing to commit; will retry on next timer fire."
  exit 1
fi

# Copy the repo-clone jar back to the work dir.  Today this is a
# byte-identical no-op safeguard (the fetcher never rewrites the jar);
# it only matters if a future fetcher starts refreshing cookies.
if [[ -f "${REPO_DIR}/idpshow_session.json" ]]; then
  cp -f "${REPO_DIR}/idpshow_session.json" "${SESSION_FILE}"
  chmod 600 "${SESSION_FILE}"
fi

mkdir -p data/scrape_state
if [[ "${DEFAULT_FETCH_OK}" -eq 1 ]]; then
  date -u +%s > data/scrape_state/idpShow_last_success
fi
if [[ "${COMBINED_FETCH_OK}" -eq 1 ]]; then
  date -u +%s > data/scrape_state/idpShowCombined_last_success
fi

# Force-add both boards' outputs + stamps because data/ is gitignored
# at the repo level (data/scrape_state/ is the carve-out we want
# tracked) - matches the scheduled-refresh.yml "Commit updated data"
# step.  Adding a path whose fetch failed (and so is unchanged on
# disk) is harmless - it just produces no diff to commit.
git add -f -- \
  CSVs/site_raw/idpShow.csv \
  CSVs/site_raw/idpShowCombined.csv \
  data/scrape_state/idpShow_last_success \
  data/scrape_state/idpShowCombined_last_success

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
