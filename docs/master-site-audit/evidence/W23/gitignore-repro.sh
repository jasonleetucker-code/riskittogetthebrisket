#!/usr/bin/env bash
# W23 evidence: reproduces the exact failure of the "Commit ... result" step in
# the four Sharp diagnostic workflows.  They run `git add data/ops/<file>.json`
# under GitHub Actions' default `bash -e {0}` shell, but `.gitignore:45` excludes
# `data/`.  git refuses an explicitly-named ignored path with exit 1, and `-e`
# kills the step before any later command in it runs.
#
# Usage: bash docs/master-site-audit/evidence/W23/gitignore-repro.sh
set -u
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
REPO_GITIGNORE="$(git rev-parse --show-toplevel)/.gitignore"

cd "$WORK"
git init -q .
cp "$REPO_GITIGNORE" .
mkdir -p data/ops
echo '{"status":"healthy"}' > data/ops/sharp-production-smoke.json
git add .gitignore
git -c user.email=a@b -c user.name=a commit -qm init

echo "--- replicating verify-sharp-production.yml 'Commit production smoke result' ---"
bash -e -c '
  git add data/ops/sharp-production-smoke.json
  echo "REACHED: git commit"      # never printed
  git commit -m "chore(ops): record Sharp production smoke"
'
echo "STEP EXIT=$?   (non-zero => the step fails => 'Enforce healthy population' is skipped)"
