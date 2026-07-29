# Branch disposition — verified 2026-07-29

Evidence for the branch-cleanup decision (D-5 in `docs/OWNER_ACTION_AUDIT_2026-07-29.md`).
Generated mechanically from ancestry, not judged by name.

## How to read this

`main` has 223 commits. A branch showing 223 'commits in main not in it' shares **zero** history with `main`.

| Branch | Ahead of `main` | Last commit | Verdict |
|---|---|---|---|
| `archive/claude/complete-frontend-migration-Vkjeg` | 364 | 4 months ago | **ORPHAN** — shares no history with `main`; pre-rewrite |
| `archive/claude/fix-nextjs-production-load-q643J` | 305 | 4 months ago | **ORPHAN** — shares no history with `main`; pre-rewrite |
| `archive/claude/fix-settings-crash-and-tep-visibility` | 494 | 4 months ago | **ORPHAN** — shares no history with `main`; pre-rewrite |
| `archive/claude/new-session-DBIhp` | 386 | 4 months ago | **ORPHAN** — shares no history with `main`; pre-rewrite |
| `archive/claude/override-unification-finalize` | 495 | 3 months ago | **ORPHAN** — shares no history with `main`; pre-rewrite |
| `archive/claude/remove-lam-scarcity-3hxzs` | 368 | 4 months ago | **ORPHAN** — shares no history with `main`; pre-rewrite |
| `archive/codex/deploy-incident-fix` | 36 | 5 months ago | **ORPHAN** — shares no history with `main`; pre-rewrite |
| `archive/codex/deploy-sudo-fix` | 32 | 5 months ago | **ORPHAN** — shares no history with `main`; pre-rewrite |
| `archive/codex/release-gate-hardening` | 33 | 4 months ago | **ORPHAN** — shares no history with `main`; pre-rewrite |
| `archive/codex/stale-ip-cleanup` | 36 | 5 months ago | **ORPHAN** — shares no history with `main`; pre-rewrite |
| `archive/codex/workspace-coordination` | 3676 | 4 days ago | **ORPHAN** — shares no history with `main`; pre-rewrite |
| `archive/debug/ktc-dom-snapshot` | 890 | 3 months ago | **ORPHAN** — shares no history with `main`; pre-rewrite |
| `archive/feat/terminal-activation` | 831 | 3 months ago | **ORPHAN** — shares no history with `main`; pre-rewrite |
| `archive/fg-prepass-and-count-aware-anchor` | 740 | 3 months ago | **ORPHAN** — shares no history with `main`; pre-rewrite |
| `archive/rankings-cleanup-deploy` | 461 | 4 months ago | **ORPHAN** — shares no history with `main`; pre-rewrite |
| `archive/refit/ktc-va-observations-2026-04-25` | 893 | 3 months ago | **ORPHAN** — shares no history with `main`; pre-rewrite |
| `archive/refit/v13-borderline-observations` | 901 | 3 months ago | **ORPHAN** — shares no history with `main`; pre-rewrite |
| `archive/value-automation-sweep` | 766 | 3 months ago | **ORPHAN** — shares no history with `main`; pre-rewrite |
| `claude/complete-codebase-audit-fzp0ye` | 2 | 31 minutes ago | **UNMERGED** — 2 commit(s) not on `main` |
| `claude/e2e-r1-reconcile` | 3761 | 3 days ago | **ORPHAN** — shares no history with `main`; pre-rewrite |
| `claude/fully-implemented-riu0zp` | 0 | 19 hours ago | **MERGED** — safe to delete |
| `claude/league-intel-projections` | 3762 | 3 days ago | **ORPHAN** — shares no history with `main`; pre-rewrite |
| `claude/league-intel-sim` | 3754 | 3 days ago | **ORPHAN** — shares no history with `main`; pre-rewrite |
| `claude/repository-manual-action-audit-44b8i5` | 1 | 47 minutes ago | **UNMERGED** — 1 commit(s) not on `main` |
| `claude/session-audit-handoff-tvxfc1` | 3762 | 3 days ago | **ORPHAN** — shares no history with `main`; pre-rewrite |
| `claude/sharp-insider-audit-separation-fibqu6` | 4 | 35 minutes ago | **UNMERGED** — 4 commit(s) not on `main` |
| `claude/sitewide-performance-audit-nubuz8` | 4 | 10 minutes ago | **UNMERGED** — 4 commit(s) not on `main` |
| `claude/tier3-snap-share` | 1 | 2 days ago | **UNMERGED** — 1 commit(s) not on `main` |
| `claude/ui-ia-audit-1o1yku` | 0 | 14 minutes ago | **MERGED** — safe to delete |
| `scratch/e2e-yml-probe` | 3770 | 3 days ago | **ORPHAN** — shares no history with `main`; pre-rewrite |


## What the ORPHAN verdict means, and why it is not a licence to delete

`main` was rewritten at some point in this repository's history. Twenty-two
branches predate that rewrite and share **zero commits** with `main`. Git
cannot tell you whether their work was merged, because there is no common
ancestor to compare against — a squash, a rebase, or a manual re-application
all look identical from here.

So "ORPHAN" means *"ancestry cannot answer this"*, **not** *"unmerged"* and
**not** *"safe to delete"*. Deleting them destroys the only surviving copy of
the pre-rewrite history. Two of them are recent enough to be genuinely
in-flight rather than historical:

- `archive/codex/workspace-coordination` — 4 days old
- `claude/e2e-r1-reconcile`, `claude/league-intel-projections`,
  `claude/league-intel-sim`, `claude/session-audit-handoff-tvxfc1`,
  `scratch/e2e-yml-probe` — 3 days old

The five 3-day-old ones carrying ~3,760 commits are almost certainly working
branches cut from the pre-rewrite `main` and never rebased. Their *content*
may well be superseded; their *history* is not recoverable from anywhere else.

## Recommendation

**Safe now, no judgement required:**

- `claude/fully-implemented-riu0zp` — 0 commits ahead, fully contained in `main`
- `claude/ui-ia-audit-1o1yku` — merged as #625

**Leave alone for now:** everything marked ORPHAN. The `archive/` prefix is
already an archival convention and the branches cost nothing but a line in the
branch list. If you want them gone, tag them first so the history survives:

```bash
# From a full clone. Creates a tag per orphan branch, then you can delete
# the branches without losing the commits.
for b in $(git branch -r --format='%(refname:short)' | grep '^origin/archive/'); do
  git tag "archived/${b#origin/archive/}" "$b"
done
git push origin --tags
```

**Active, do not touch:** `claude/complete-codebase-audit-fzp0ye`,
`claude/sharp-insider-audit-separation-fibqu6`,
`claude/sitewide-performance-audit-nubuz8`,
`claude/repository-manual-action-audit-44b8i5` — all have open or in-flight
work.

`claude/tier3-snap-share` is the one genuinely orphaned *modern* branch: 1
commit, on the current history line, 2 days old, no open PR. Worth a look
before deleting — it is real unmerged work, not an artifact.
