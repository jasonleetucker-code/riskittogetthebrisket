# Repository stabilization campaign — reconciliation record (2026-10-07)

**Authority:** owner directive 2026-10-07, recorded in `docs/EXECUTION_PLAN.md` §0
("Repository stabilization / truth-reconciliation campaign"). This file is a
point-in-time **evidence record**, not an authorization record and not a roadmap.
GitHub and live code remain the truth for implementation status; when this file
and GitHub disagree, GitHub wins.

Machine-readable PR / issue dispositions: [`stabilization_2026-10-07.json`](stabilization_2026-10-07.json).

## 1. Before state (captured at session start)

| Fact | Value | Evidence |
|---|---|---|
| `main` | `96da962fa` | `git rev-parse origin/main` |
| Production served commit | `1eec690fa` (3 automation-only commits behind main) | `GET /api/status` → `build.commit`; Deploy Production run 37621154868 green |
| Production health | `/api/health` `status: ok`, `contract_ok`, `served_generation_ok`, `source_health_ok` | read-only probe 2026-10-07T14:48Z |
| Open PRs | 37 | `gh pr list` |
| Open issues | 89 (26 machine-created) | `gh issue list` |
| Work-claim rows claiming in-flight work that had merged/closed | 69 | CLEANUP-1 audit |
| Open PRs with no claim row | 10 | CLEANUP-1 audit |
| `main` protection | ruleset `19976839`: deletion + non-fast-forward only; **no PR, no status check required** | `gh api …/rulesets/19976839` |

## 2. What was stale or wrong — and what was done

| Area | Finding | Action |
|---|---|---|
| Claims | 69 rows reported live editors for merged/closed work; `check_work_claims.py` only treated `open…` statuses as open, so `active`/`in progress` rows were invisible to the overlap check and backticked paths never matched | Reconciled + checker hardened — PR #1674 |
| Status docs | DFS handoff described merged PRs as open/stacked; UI ledger rows cited closed PRs and branch-only proof; `PRODUCT_PLAN.md` current position predated `EXECUTION_PLAN` §0 by ~7 weeks; `REPO_INVENTORY.md` described the retired Static/`FRONTEND_RUNTIME` architecture | Reconciled with CURRENT STATUS + HISTORICAL POINTER — PR #1674 |
| Authority | The 2026-10-03 directive, the AI-architecture campaign and both 2026-10-07 directives were missing from `EXECUTION_PLAN` §0 | Recorded — PR #1674 |
| PR #1656 | Byte-identical (same patch-id) to `d3335e2f4`, already on main via hotfix #1657 | Closed as SUPERSEDED_BY_MAIN |
| Machine issues | 18 open "Production health check failing" trackers for a check green since 2026-10-05; stale/duplicate Hill, rank-form, intel trackers | 22 closed with evidence; dedupe/close defects fixed in the CI-reliability PR; #1676 opened for the one untracked live failure |
| Source-state reporting | Declared seasonal/private absences reported as "Missing"/red; recorder could manufacture private provisioning; unknown age read as fresh | PR #1675 (D2, D3, D4, D5, D7, D11) |
| Ruleset payload in repo | `deploy/github/main-protection-ruleset.json` (never applied) would have blocked every automated pusher | Corrected + test-pinned (this PR) |

## 3. Branch protection — owner-ready decision

### Current state (verified 2026-10-07)
Ruleset `19976839 main-protection`, enforcement `active`, target `~DEFAULT_BRANCH`,
rules `deletion` + `non_fast_forward`, bypass actors `DeployKey` (always), repository
role 4 *write* (always), role 5 *admin* (always). No classic branch protection.
**Any account with write access can push straight to `main`, and `deploy.yml`
ships pushes to `main` to production.** The last 100 rule-suite evaluations all
`pass`: box deploy-key pushes (recorded under the owner's name) and
`github-actions[bot]` pushes.

### Who legitimately pushes to `main`
| Pusher | Credential | What |
|---|---|---|
| `scheduled-refresh.yml` (×2), `refit-hill-curves.yml`, `verify-sharp-production.yml`, `weekly-narratives.yml` | `GITHUB_TOKEN` (GitHub Actions app 15368) | data refresh + freshness stamps, Hill evidence, Sharp smoke receipt, narratives |
| `deploy/dlf_fetch_and_push.sh`, `idpshow_fetch_and_push.sh`, `playerctx_history_push.sh` (box timers) | write deploy key 157964404 "dynasty-box-push" | `data/scrape_state/*`, `CSVs/site_raw/*`, playerctx history |
| Owner and every AI agent session | the same admin account | PR merges (and occasional direct pushes) |

Deploy dispatch and production `source_health` depend on the automated commits
(CLAUDE.md W31-F001), so **any protection that blocks them freezes production.**

### Desired state
`deploy/github/main-protection-ruleset.json` (corrected in this PR, pinned by
`tests/deploy/test_main_protection_ruleset.py`):

- rules: `deletion`, `non_fast_forward`, `pull_request` (0 approvals — solo repo),
  `required_status_checks` = `Validate PR` (the only check that runs on every PR),
  `strict: false` (requiring up-to-date branches would chase the 2-hourly refresh —
  CLAUDE.md HEAD FREEZE);
- bypass: `DeployKey` **always** (box timers), `Integration 15368` **always**
  (Actions pushers), admin role **`pull_request`**;
- removed: the *write* role bypass.

**Why admin = `pull_request`:** the owner and AI agents push as the same account,
so GitHub cannot tell them apart. `always` = direct-main authority for every agent
session. `pull_request` blocks direct pushes while keeping an emergency path: the
admin can still merge a PR whose checks are red (`gh pr merge --admin`).

### Owner decisions required (smallest set)
1. **Apply the ruleset?** Recommended: yes, as written.
2. **Admin bypass `pull_request` (recommended) vs `always`.** `always` keeps the
   "do it → push to main" habit but gives the same power to every agent session.
3. **Retire unused write deploy keys** 145025388 "hetzner-riskit" (last used
   2026-03-09) and 148579683 "dynasty-prod-deploy" (last used 2026-06-24): the
   `DeployKey` bypass covers *all* write deploy keys. Recommended: delete or make
   read-only.
4. *(Hardening, later)* move the four `GITHUB_TOKEN` pushers onto a dedicated
   deploy-key secret and drop the `Integration` bypass — the Actions bypass
   currently covers any workflow with `contents: write`. If GitHub rejects an
   `Integration` bypass on this user-owned repo, this becomes required.

### Commands (admin token; run right after a box push at :27/:32 past even hours)
```bash
# 0. rollback copy
gh api repos/jasonleetucker-code/riskittogetthebrisket/rulesets/19976839 > ruleset-19976839-backup.json
# 1. dry run: validates the payload locally, sends nothing
bash deploy/github/apply-branch-protection.sh --dry-run
# 1b. acceptance probe (evaluate mode is Enterprise-only): create a DISABLED copy;
#     a 201 echoing all three bypass actors proves GitHub accepts them, then delete it
# 2. apply (updates ruleset 19976839 in place)
GH_TOKEN=<admin token> bash deploy/github/apply-branch-protection.sh
# 3. verify the next DLF/IDP Show push and the next github-actions[bot] push show `bypass`
gh api repos/jasonleetucker-code/riskittogetthebrisket/rulesets/rule-suites
# rollback
gh api --method PUT repos/jasonleetucker-code/riskittogetthebrisket/rulesets/19976839 --input ruleset-19976839-backup.json
```

## 4. Is `main` green?

Hard gates on main are green: the latest Deploy Production run (`1eec690fa`, which
runs the blocking unit suite and the full-lane contract check) passed, as did Scheduled
Data Refresh, Health Check, Prod E2E Smoke, Intel and the Sharp workflows. Scheduled
workflows red on `main` at audit time:

| Workflow | Cause | Owner / disposition |
|---|---|---|
| V1 authenticated verification | `prod-auth/trade-stack-withdrawn.spec.js:176` — stack note not shown for a first-round pick, red since 2026-10-03 | Diagnosis/fix lane (CLEANUP-3) |
| consensus-edge-revalidate | `validate_consensus_edge_board.py:746` `relative_to` crash for out-of-repo `--out` | CI-reliability PR |
| smoke-test "Validate Code Quality" | unit suite (~60 min) under a 10-minute timeout → cancelled daily | CI-reliability PR |
| E2E safety net | `/waivers` mobile a11y `scrollable-region-focusable` | #1673 (open, real) |
| audit-rank-form-drift | real constant drift | #898 (open, human-updated per ADR-008) |
| retention-health | C1-RET-07 stream has no producer since 2026-04-20 | #1676 (owner/methodology) |

## 5. Source-state semantics

Core owners hold the invariants (dataset clocks, freshness curve, seasonal policy,
private availability, coverage gates; ~1,100 existing tests pin them). Reporting
layers did not; fixed in PR #1675. Remaining, each a named follow-up rather than a
silent gap:

- **D1** first observation of a board stamps fetch time as content time
  (`firstObservationIsBaseline` written, never read) — changes stamped freshness state;
  needs board-diff verification.
- **D6** Rankings "Updated X ago" = contract build time; Waivers says IDPTC "updated"
  from fetch time.
- **D8** validator `source_missing` has no seasonal exemption (latent).
- **D9** B11 confidence freshness uses wall clock, not the board's as-of — touches
  published `confidenceAxes`; needs board-diff evidence.
- **D10 / D12** new alert / census categories need an owner decision.
- **D13** display-only explain-table defaults.

## 6. Repository footprint and retention

Tracked tree 2.24 GB / 15,280 files; packed history ~774 MiB, growing ~132 MB per 30
days. **91 % of the checkout is three subtrees.** No artifact met all four pruning bars
(not irreplaceable · no consumer of path *or history* · retention allows · tested
rebuild), so **nothing was deleted.**

| Subtree | Size | Class | Note |
|---|---|---|---|
| `data/ros/aggregate/history` | 1.25 GB tree, still growing | G/F (redundant) | write-only; each file equals the `players` array of `data/ros/aggregate/latest.json` committed in the same commit (1,233 ↔ 1,233; 12/12 sampled identical). Docstring promises a "rolling 30-day archive" that was never implemented |
| `data/identity` | 506 MB, frozen 2026-04-20 | B/H | C1-RET-07 indefinite; primary store; see #1676 |
| `data/raw`, `data/raw_sources` | 276 MB, frozen | H | retired adapter pipeline; keep-30 already reached |
| `exports/archive/*.zip` | 39 MB tree, **55 % of pack** | G in git | zips byte-match `exports/latest/*` of the same commit; zips neither compress nor delta |

**Recommendation (each step needs its own authorized unit):**
1. **Stop `data/ros/aggregate/history` growing** — after a tested rebuild script
   (`git log` + `git show` of `latest.json`) exists, stop force-adding it in
   `scheduled-refresh.yml` (or stop `src/ros/scrape.py` writing it) and correct the
   docstring + `docs/BRISKET_IDEAS.md` §13 row. Removing the existing files from the
   tree saves 1.25 GB per checkout but **also deletes them on the box** (`deploy.sh`
   runs `git reset --hard`) → owner approval.
2. **Stop committing export zips** once their consumers (`src/history/backfill.py`,
   `tests/archive_fixtures.py`, `check_source_health` content staleness, backfill
   scripts) read `exports/latest` history or the box copy; needs a retention-register
   amendment. ~0.55 GB/year of pack growth avoided.
3. **Cheaper CI checkouts:** 12 checkout steps use `fetch-depth: 0`; add
   `filter: blob:none` (partial clone) and sparse checkout for jobs that do not read
   the large data subtrees.
4. **No Git LFS, no history rewrite:** migrating history is a rewrite (SECURITY.md
   rules it out); LFS for new files breaks every `git show <commit>:<path>` reader
   (`CSVs/site_raw`, `exports/latest`, `data/ros/sims`, `scrape_state`) and the
   2-hourly CI/deploy fetches would exhaust free LFS bandwidth. Projected pack size a
   year out (~1.6 GB) is within GitHub guidance. The on-box nightly backup already
   satisfies "durable does not mean committed".

## 7. Legacy and transitional surfaces

- `Jenkinsfile` — unused (GitHub Actions owns CI/deploy); its unique stages run over
  raw snapshots frozen since 2026-04-20. Legacy; documented, not deleted here.
- `start_dynasty.bat` — referenced by `CLAUDE.md` and `README.md`, **does not exist**.
- `sync.bat` — `git add -A` + push of the current branch (possibly `main`); conflicts
  with the explicit-path / PR-only practice. Recommend retiring.
- `/static` mount (`server.py`) — empty directory created at import, never routed by
  nginx; dead in production.
- `src/api/chat.py` — unwired (recorded by an existing test).
- `IDP_POSITIONS` defined ~13 times with different members — no single owner (seam
  for a later unit).
- All 52 frontend bridge routes have a matching backend endpoint (no orphans).
- Monolith extraction: the two high-confidence seams were the league narrative-articles
  routes (`server.py`) and the rankings delta builder (`data_contract.py`); see the
  CLEANUP-4 PR for what was actually extracted. Everything else is documented as a
  seam, not extracted.

## 8. Not changed by this campaign (by design)

No canonical player value, source weight, Hill constant/methodology, challenger
promotion, Signals IDP activation, league rule, DFS action, purchase, or
official-auction action. No test was weakened.
