#!/usr/bin/env bash
#
# Push the week's dated playerctx snapshot to main.
#
# Structurally different from deploy/dlf_fetch_and_push.sh and
# deploy/idpshow_fetch_and_push.sh, and the difference is forced rather
# than stylistic. Those two do their work INSIDE a dedicated clone,
# because nothing reads their output locally. playerctx cannot: the API
# reads data/playerctx/snapshot.json out of the live deploy directory,
# so the refresh has to run there — and deploy.sh does an unconditional
# `git checkout --force` + `git reset --hard` on that tree, which would
# throw away anything committed in it.
#
# So this splits the two jobs. The refresh writes the live path (its own
# systemd unit, unchanged). This script COPIES the dated file into a
# dedicated clone and pushes from there, touching the live repo not at
# all.
#
# Everything else is lifted from dlf_fetch_and_push.sh deliberately:
# same dedicated-clone layout, same sync-before-work, same no-op guard,
# same three-attempt push retry with a rebase between, same per-command
# identity.
#
# Logs to stdout/stderr; the systemd unit pipes both into the journal
# (journalctl -u dynasty-playerctx-history.service).

set -Eeuo pipefail

WORK_DIR="${PLAYERCTX_HISTORY_WORK_DIR:-/var/lib/playerctx-history}"
REPO_DIR="${WORK_DIR}/repo"
REPO_URL="${PLAYERCTX_HISTORY_REPO_URL:-git@github.com:jasonleetucker-code/riskittogetthebrisket.git}"
SSH_KEY="${PLAYERCTX_HISTORY_SSH_KEY:-${HOME}/.ssh/github_deploy_key}"

# Where the refresh wrote it. The live deploy dir, which this script
# only ever READS.
LIVE_APP_DIR="${PLAYERCTX_HISTORY_APP_DIR:-/home/dynasty/trade-calculator}"
HISTORY_REL="data/playerctx/history"

GIT_AUTHOR_NAME="${PLAYERCTX_HISTORY_GIT_NAME:-playerctx History (prod)}"
GIT_AUTHOR_EMAIL="${PLAYERCTX_HISTORY_GIT_EMAIL:-playerctx-history@brisket-prod-1.local}"

PUSH_RETRY_MAX=3

log() { printf '[playerctx-history] %s\n' "$*"; }
err() { printf '[playerctx-history][ERR] %s\n' "$*" >&2; }

export GIT_SSH_COMMAND="ssh -i ${SSH_KEY} -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"

# The deploy-key check lives HERE, not in install-systemd-service.sh, and
# that placement is the fix for a measured failure rather than a
# preference.  The installer gated the whole unit on this file and
# reported it missing on the 2026-08-05 deploy, installing nothing —
# but the installer runs as the DEPLOY user, whose sudo is scoped to
# specific commands, so it can neither `sudo test -f` nor stat another
# user's ~/.ssh.  This script runs as the app user under
# `User=__APP_USER__`, which is the only context that can answer the
# question it is actually asking: can the thing that pushes read the key?
#
# Exit 0, not 1.  Nothing has been lost or half-done at this point, and a
# unit that goes red every week is a unit nobody reads.  The backlog is
# safe because the glob below takes EVERY dated snapshot rather than the
# newest, so supplying the key later backfills every missed week on the
# next run.  A stalled retention is meant to surface through
# `store.history_coverage()`'s missingDays — the same way rank_history
# reports its own gaps — not through a permanently failing timer.
if [[ ! -r "${SSH_KEY}" ]]; then
  log "no readable deploy key at ${SSH_KEY} - snapshots stay on disk, nothing pushed"
  log "fix: place the key there, or set PLAYERCTX_HISTORY_SSH_KEY in ${LIVE_APP_DIR}/.env"
  exit 0
fi

SRC_DIR="${LIVE_APP_DIR}/${HISTORY_REL}"
if [[ ! -d "${SRC_DIR}" ]]; then
  log "no history directory at ${SRC_DIR} - nothing to push (exiting clean)"
  exit 0
fi

# Only dated snapshots. A glob rather than the whole directory, because
# data/playerctx/ next door holds a 38 MB depth-chart CSV and a 14 MB
# Sleeper dump and no directory-level copy should ever be able to reach
# them.
shopt -s nullglob
SNAPSHOTS=("${SRC_DIR}"/snapshot_[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].json)
shopt -u nullglob
if [[ ${#SNAPSHOTS[@]} -eq 0 ]]; then
  log "no dated snapshots in ${SRC_DIR} - exiting clean"
  exit 0
fi

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

mkdir -p "${REPO_DIR}/${HISTORY_REL}"
STAGED=()
for src in "${SNAPSHOTS[@]}"; do
  name="$(basename "${src}")"
  cp -f "${src}" "${REPO_DIR}/${HISTORY_REL}/${name}"
  STAGED+=("${HISTORY_REL}/${name}")
done

# `git add -f` with an EXPLICIT path list, never a directory and never
# -A. data/ is gitignored repo-wide, so this is the only thing that can
# commit these — and naming each file is what makes it impossible to
# sweep in the raw cache by accident. A `git add -A` is precisely what
# put an earlier PR into merge conflict by committing two scrape-state
# timestamps nobody intended.
log "staging ${#STAGED[@]} snapshot(s)"
git add -f -- "${STAGED[@]}"

if git diff --cached --quiet; then
  log "no changes after copy - exiting clean"
  exit 0
fi

STAMP="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
git -c user.name="${GIT_AUTHOR_NAME}" -c user.email="${GIT_AUTHOR_EMAIL}" \
  commit -m "chore(playerctx): retain snapshot ${STAMP}"

attempt=1
while (( attempt <= PUSH_RETRY_MAX )); do
  if git push origin main; then
    log "pushed on attempt ${attempt}"
    exit 0
  fi
  err "push rejected on attempt ${attempt} - rebasing onto origin/main"
  git fetch origin main
  # --strategy-option=theirs matches the sibling pushers: on the rare
  # collision with a concurrent refresh, the other writer's copy of a
  # generated file wins. These files are dated and disjoint in practice,
  # so this is a formality rather than a real merge policy.
  git pull --rebase --strategy-option=theirs origin main
  attempt=$(( attempt + 1 ))
done

err "push failed after ${PUSH_RETRY_MAX} attempts"
exit 1
