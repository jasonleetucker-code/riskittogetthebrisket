# Runbook — Shrinking Git History (349 MiB pack)

> **Status: PLAN ONLY. Do not execute casually.** This runbook rewrites
> `main`'s history and requires a coordinated force-push. It is a
> destructive, one-time operation that invalidates every existing clone
> and open PR. Read the whole document before running anything.

## Why

The packed repository is ~349 MiB. The bulk is generated scrape output
that was force-committed (`git add -f`) into history over months without
ever being pruned:

| Path | Nature |
|---|---|
| `data/raw_sources/raw_source_snapshot_*.json` | ~5.4 MB each, ~177 committed, near-identical |
| `data/raw/<source>/<year>/*` | thousands of per-run archives |
| `data/canonical/*` | orphaned — the offline canonical pipeline was retired |
| `CSVs/*.har`, large one-off CSV/HAR captures | debugging artifacts |
| `audit/baseline/api_data.json` | 10 MB fixture |

**The forward-growth leak is already fixed** by wiring
`src/maintenance/retention.py` into `.github/workflows/scheduled-refresh.yml`
(the pruner now runs before each automated commit, keeping only the
newest N snapshots). That stops the bleeding. This runbook is the
*separate* step of reclaiming the history that already accumulated —
`git` history is immutable, so shrinking the pack requires a rewrite.

Because retention now bounds forward growth, this rewrite is **optional
housekeeping**, not urgent. Only do it if clone/CI times or storage
actually hurt.

## Blast radius — read first

- Every commit SHA on `main` changes. **All existing clones must be
  re-cloned** (or hard-reset to the rewritten remote); a normal `git
  pull` will conflict catastrophically.
- **All open PRs break** and must be recreated against the rewritten
  base. Merge or close outstanding PRs first.
- The production deploy scripts (`deploy/dlf_fetch_and_push.sh`,
  `deploy/idpshow_fetch_and_push.sh`) hold a **long-lived clone on the
  prod box** and run `git pull --rebase --strategy-option=theirs origin
  main`. After a history rewrite that pull will fail — the prod clone
  must be re-cloned or hard-reset to the new `main` **before** the next
  scheduled scrape, or the pipeline will wedge.
- Any external mirror, fork, or backup that fetches `main` is affected.

## Preconditions

1. Announce a maintenance window; freeze merges to `main`.
2. **Pause the scheduled workflows** that push to `main`
   (`scheduled-refresh.yml`, and any freshness-stamp / warmup jobs)
   so nothing pushes mid-rewrite. Disable them in the Actions UI.
3. Merge or close every open PR.
4. Take a full backup: `git clone --mirror` the repo to a safe location
   (this is your rollback).
5. Install [`git-filter-repo`](https://github.com/newren/git-filter-repo)
   (`pip install git-filter-repo`). Do **not** use the deprecated
   `git filter-branch`.

## Procedure

Work in a fresh mirror clone, never your working checkout.

```bash
# 1. Fresh mirror (this is what you will rewrite + push).
git clone --mirror git@github.com:jasonleetucker-code/riskittogetthebrisket.git rewrite.git
cd rewrite.git

# 2. Inspect the biggest blobs to confirm the target set before deleting.
git rev-list --objects --all \
  | git cat-file --batch-check='%(objecttype) %(objectsize) %(rest)' \
  | awk '$1=="blob"{print $2, $3}' | sort -rn | head -40

# 3. Strip the generated/archive paths from ALL history.
#    --invert-paths deletes matches; everything else is preserved.
git filter-repo --force \
  --path data/raw_sources/ \
  --path data/raw/ \
  --path data/canonical/ \
  --path-glob 'CSVs/*.har' \
  --path audit/baseline/api_data.json \
  --invert-paths

# 4. Verify: repo should be dramatically smaller.
git count-objects -vH | grep size-pack

# 4b. Re-add origin. git-filter-repo REMOVES the origin remote after a
#     full-history rewrite (a deliberate safety measure so you can't
#     fat-finger a push before verifying). Without this, step 5 fails
#     with "'origin' does not appear to be a git repository". Use the
#     same URL the mirror was cloned from in step 1.
git remote add origin git@github.com:jasonleetucker-code/riskittogetthebrisket.git

# 4c. Drop any GitHub-owned refs the mirror may carry. `push --mirror`
#     force-updates EVERY ref under refs/, including read-only
#     refs/pull/* (PR refs). GitHub rejects those as hidden refs and the
#     whole push fails. Delete them from the local mirror first so the
#     push only carries branches and tags.
git for-each-ref --format='delete %(refname)' refs/pull refs/pull-requests \
  | git update-ref --stdin || true

# 5. Push the rewritten history. This is the irreversible step.
#    --mirror so deleted branches are pruned on the remote too. If a
#    hidden-ref rejection still slips through, push heads + tags only:
#      git push --force origin 'refs/heads/*:refs/heads/*' 'refs/tags/*:refs/tags/*'
git push --force --mirror origin
```

> **Keep-recent nuance:** step 3 removes these paths from *all* history,
> including the newest snapshots on the current tip. If you want the tip
> to retain the newest N (so a fresh clone still has working data), first
> run the retention pruner on a normal checkout, commit the pruned tip,
> then rewrite only the *historical* blobs — or simply let the next
> scheduled scrape repopulate the newest snapshots after the rewrite
> (the pruner keeps them bounded thereafter). The simpler path is: rewrite
> everything out, then let the pipeline regenerate the current snapshots.

## After the rewrite

1. **Re-clone the prod box** before re-enabling scrapes:
   ```bash
   # on the prod box, replace the stale clone used by deploy/*_fetch_and_push.sh
   mv riskittogetthebrisket riskittogetthebrisket.old
   git clone git@github.com:jasonleetucker-code/riskittogetthebrisket.git
   # re-apply any untracked local config/secrets the scripts expect
   ```
2. Re-enable the paused workflows.
3. Have every collaborator re-clone (or `git fetch && git reset --hard
   origin/main` on a clean tree).
4. Recreate any PRs that were open.
5. Trigger `scheduled-refresh.yml` once manually and confirm it commits +
   pushes cleanly (validates the prod clone and retention prune end to
   end).
6. Keep `rewrite.git` and the pre-rewrite mirror backup for at least a
   few weeks before deleting.

## Rollback

If anything goes wrong before you are confident, restore from the mirror
backup taken in preconditions step 4:

```bash
cd backup.git   # the --mirror clone taken before the rewrite
# Same hidden-ref guard as step 4c: the untouched backup can still carry
# refs/pull/*, which GitHub rejects on a --mirror push — do NOT let that
# block an emergency restore.
git for-each-ref --format='delete %(refname)' refs/pull refs/pull-requests \
  | git update-ref --stdin || true
git push --force --mirror origin
# Fallback if a hidden-ref rejection still occurs:
#   git push --force origin 'refs/heads/*:refs/heads/*' 'refs/tags/*:refs/tags/*'
```

Then re-sync the prod box and collaborators to the restored history.
