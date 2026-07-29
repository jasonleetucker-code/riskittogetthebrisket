# Manual-Action Audit

**Repository:** `jasonleetucker-code/riskittogetthebrisket`
**Audited:** 2026-07-29, against `main` @ `bbd7091` and live production `https://chaseupside.com`
**Method:** repository inspection, GitHub API (branches, PRs, issues, workflow runs, job logs), live unauthenticated HTTP probes against production.

Every finding below is labelled **CONFIRMED** (I observed it directly and the evidence is cited) or **UNVERIFIED** (I could not see inside a dashboard, a `.env` on the VPS, or a GitHub settings page).

---

## 1. Executive Summary

| Metric | Count |
|---|---|
| Confirmed manual tasks (only you can do them) | **11** |
| Possible manual tasks requiring your verification first | **7** |
| Autonomous tasks I can complete without you | **14** |
| Decisions I need from you | **6** |

**Main categories of manual work:** repository visibility and data exposure · GitHub security settings (branch protection, Dependabot, code scanning, secret scanning) · three unmerged pull requests, one of which contains a live production security fix · one credential you must retrieve from a third-party login · one modelling decision that only a human is allowed to promote · verification of items previous sessions could not confirm.

### Can the application build, test, deploy, and run in production?

| Question | Answer | Evidence |
|---|---|---|
| Build? | **Yes** — CONFIRMED | `Deploy Production` run `30439500565` (2026-07-29 09:24) completed with zero failed jobs. Validate job runs `pip check`, `ruff format --check`, `py_compile`, the pytest suite, and `npm run build`. |
| Test? | **Yes in CI, no in this container** — CONFIRMED | CI green. The session-start hook here reports `No module named pytest` — that is this ephemeral container lacking a venv, not a repository defect. `make setup` fixes it. |
| Deploy? | **Yes** — CONFIRMED | 6 successful `Deploy Production` runs in the last 12 hours, `push` and `workflow_dispatch`. |
| Run in production? | **Yes, healthy** — CONFIRMED | `GET https://chaseupside.com/api/health` → `status: ok`, `contract_ok: true`, `data_age_hours: 0.8`, 1,094 players, all 21 ranking sources fetched within 3 hours, `scrape_success_rate_24h: 1.0`, TLS valid (`ssl_verify=0`). |

**So: nothing is broken in the build-and-ship sense. The blockers are exposure and governance, not function.**

### The most important blocker

**The repository is public.** `GET /repos/jasonleetucker-code/riskittogetthebrisket` returns `"private": false`, `"visibility": "public"`, `"allow_forking": true`, `"stargazers_count": 2`. `README.md:3` describes it as a "Private repo". Everything in the tree is world-readable today: the full valuation engine (`src/api/data_contract.py`), the BDVM fundamentals model, your Sleeper league IDs and owner IDs (`config/leagues/registry.json:8,42`), manager display names (`config/leagues/owner_names.json`), and **8,015 tracked files under `data/` and `exports/`** containing your ranking snapshots and export archives.

### Critical security issues requiring immediate owner action

Two, both CONFIRMED by live probe against production, both anonymous, both right now:

1. **`GET https://chaseupside.com/api/draft-capital` returns the proprietary rookie board with no authentication.** Response includes `rookieName`, `rookieKtcValue`, `rookieKtcDollar`, `rookieIdpDollar` per pick, plus real manager usernames (`jstuedle`, `ughb`, `Russini Panini`). This is `rankDerivedValue`-derived data — the exact field the public-league payload guard is written to blocklist.
2. **Private pages serve full HTML to anonymous visitors.** `GET https://chaseupside.com/rankings` → HTTP 200, 54,551 bytes. nginx routes `location /` straight to Next.js, so `server.py`'s page gates never execute. The `/api/` gate does hold — `GET /api/data` correctly returns 401 — so this is a shell/SEO/scraping exposure rather than a full data breach, but the draft-capital leak above is a real data leak.

**Both are already fixed in open PR #625, which is not merged and currently has merge conflicts.** Merging it is Task **OA-03** below and is the single highest-value action on this list.

### Confirmed vs assumed — what I could not see

I have no visibility into: GitHub Settings pages (secrets list, Dependabot toggles, branch protection UI, environment reviewers, webhooks, deploy keys, OAuth apps), your VPS filesystem or its `.env`, your domain registrar, or any third-party dashboard. Where the repository or a live endpoint gave me indirect evidence about one of those, I say so and label it inferred.

---

## 2. Critical Owner Actions

Do these three first, in this order. Everything else can wait.

| # | Task | Why now | Risk if skipped |
|---|---|---|---|
| **OA-01** | Decide and set repository visibility | Your entire valuation IP, league IDs and 8,015 data files are public today | Critical |
| **OA-03** | Merge PR #625 (after I resolve its conflicts) | Closes the live anonymous rookie-board leak on production | Critical |
| **OA-02** | Enable branch protection on `main` | `main` is unprotected; anything can be force-pushed over it, and a repo-history rewrite has already happened once here | High |

---

## 3. Master Owner Action Checklist

Phases are dependency-ordered. Each task states its blocking dependency explicitly.

---

### Phase 0 — Safety and preparation

---

#### OA-00 · Take a local backup of the repository before anything else

**Why this is necessary.** Two later tasks change repository-level state that is awkward to reverse (visibility flip, branch deletions). A local mirror costs two minutes and makes every later step reversible.

**Evidence.** `main` currently has 205 commits (`git rev-list --count origin/main`). Five branches — `claude/e2e-r1-reconcile`, `claude/league-intel-projections`, `claude/league-intel-sim`, `claude/session-audit-handoff-tvxfc1`, `scratch/e2e-yml-probe` — carry 3,761 commits each and share **zero** commits with `main`. That is the fingerprint of a history rewrite that already happened in this repository. Treat local backups as mandatory here.

**Where I must do it.** Local terminal (Windows PowerShell).

**Commands.** Run from anywhere; creates a sibling folder.

```powershell
cd C:\Users\jason\code
git clone --mirror https://github.com/jasonleetucker-code/riskittogetthebrisket.git riskittogetthebrisket-backup-2026-07-29.git
Get-ChildItem riskittogetthebrisket-backup-2026-07-29.git | Measure-Object -Property Length -Sum
```

**Expected result.** A `riskittogetthebrisket-backup-2026-07-29.git` folder containing a bare mirror of every branch and tag.

**Verification.**
```powershell
git --git-dir=C:\Users\jason\code\riskittogetthebrisket-backup-2026-07-29.git branch -a | Measure-Object -Line
```
Should report **30** branches.

**Failure recovery.** If the clone fails on authentication, run `gh auth login` (or use your existing credential manager) and retry. If it fails on disk space, the repo is ~480 MB — free space and retry.

**Risk:** Low · **Reversible:** Yes (delete the folder) · **Depends on:** nothing · **Stop point:** No.

---

### Phase 1 — Accounts and access

*(No new accounts are required. Every external service this project uses is already provisioned and working — see §7. The one credential-retrieval task is OA-08.)*

---

### Phase 2 — GitHub settings

---

#### OA-01 · Decide and set repository visibility — **CRITICAL**

**Why this is necessary.** The repository is public. Your dynasty valuation methodology is the product. `README.md:3` says "Private repo for the dynasty trade calculator stack powering chaseupside.com", and `CLAUDE.md`'s entire security posture ("Do not exfiltrate private data", the public/private API split) is written on the assumption of a private repository. One of those two facts is wrong, and only you can decide which.

**Evidence — CONFIRMED.**
- GitHub API `GET /repos/jasonleetucker-code/riskittogetthebrisket` → `"private": false`, `"visibility": "public"`, `"allow_forking": true`, `"forks_count": 0`, `"stargazers_count": 2`.
- `README.md:3` — `Private repo for the dynasty trade calculator stack`.
- `config/leagues/registry.json:8` — `"sleeperLeagueId": "1312006700437352448"`; `:42` — `"sleeperLeagueId": "1320092771247222784"`; `:31-33` — a real `ownerId` and team name.
- `git ls-files data exports | wc -l` → **8,015** tracked files, including `exports/archive/dynasty_export_*.zip` and the whole of `data/ros/`.
- Workflow logs are public consequence of this: run `30438842408` printed `E2E_TEST_SECRET: 969a7e3b...` in cleartext. (That specific value is harmless — `.github/workflows/e2e.yml:112` regenerates it per run with `openssl rand -hex 24` and it never leaves the runner — but it demonstrates that anything a workflow echoes is world-readable.)

**Where I must do it.** GitHub website.

**Exact navigation.**
> GitHub → `jasonleetucker-code/riskittogetthebrisket` → **Settings** (top tab) → scroll to the bottom → **Danger Zone** → **Change repository visibility** → **Change to private** → type `jasonleetucker-code/riskittogetthebrisket` to confirm → **I understand, change repository visibility**

**Exact values.** No values to enter beyond the confirmation string above.

**Expected result.** A **Private** badge appears beside the repository name. The two stargazers lose access. Forking is disabled implicitly.

**Verification.** Open `https://github.com/jasonleetucker-code/riskittogetthebrisket` in a private/incognito browser window while signed out. You should get GitHub's 404 page.

**What this does NOT fix.** Making the repo private from here forward does not un-publish what was already public. Anyone could have cloned it. If you consider the exposure material, the follow-up is credential rotation — see OA-09 — and accepting that the model constants and league IDs are burned. It also does **not** fix the production leak in OA-03; that is a separate, independent exposure on `chaseupside.com` itself.

**Failure recovery.** If GitHub refuses the change, it is normally because a GitHub Pages site is published from the repo. `has_pages: false` here, so that should not apply. If Actions minutes billing is a concern: private repos on the Free plan get 2,000 Actions minutes/month, and this repo's scheduled workloads (a data refresh every ~4h, health checks, warmups) will likely exceed that. **That is the real trade-off** — see Decision D-1 in §9.

**Risk:** Medium (Actions billing implications) · **Reversible:** Yes, same screen, "Change to public" · **Depends on:** OA-00 · **Stop point:** **Yes — tell me which way you went and whether Actions minutes became a problem, before I touch workflow schedules.**

---

#### OA-02 · Enable branch protection on `main`

**Why this is necessary.** `main` is completely unprotected. There is nothing preventing a force-push over it, a direct push that bypasses `pr-validation.yml`, or an accidental deletion. This repository has *already* had its history rewritten once (see OA-00 evidence). Additionally, `.github/workflows/deploy.yml:4-6` deploys **every push to `main`** straight to production — so an unprotected `main` is a direct, unreviewed path to your live site.

**Evidence — CONFIRMED.** GitHub API `GET /repos/.../branches` returns `{"name": "main", "sha": "bbd7091...", "protected": false}`.

**Where I must do it.** GitHub website.

**Exact navigation.**
> GitHub → repository → **Settings** → **Rules** → **Rulesets** → **New ruleset** → **New branch ruleset**

**Exact values to enter.**

| Field | Value |
|---|---|
| Ruleset Name | `main-protection` |
| Enforcement status | **Active** |
| Bypass list | Add **Repository admin** (so you can still hotfix) |
| Target branches | **Add target** → **Include default branch** |

Then tick these rules and leave the rest unticked:

| Rule | Setting |
|---|---|
| Restrict deletions | ✅ on |
| Block force pushes | ✅ on |
| Require a pull request before merging | ✅ on · **Required approvals: 0** |
| Require status checks to pass | ✅ on · **Do not require branches to be up to date** |
| → status check to add | `Validate PR` |

**Why 0 required approvals:** you are the only human contributor (`list_repository_collaborators` shows a single account). Requiring 1 approval on a solo repo means you can never merge your own PR without a second account. Zero approvals still forces the PR path and still runs the status check.

**Why `Validate PR` and nothing else:** that is the exact check-run name I observed on PR #626 (`{"name": "Validate PR", "conclusion": "success"}`, from `.github/workflows/pr-validation.yml`). Adding `E2E Safety Net` or `Deploy Production` as required checks would deadlock every PR — E2E is currently **failing** (OA-04) and Deploy only runs post-merge.

**Expected result.** The ruleset appears as Active. Pushing directly to `main` is rejected with `GH006: Protected branch update failed`.

**Verification.** From your local checkout, on a clean tree:
```powershell
cd C:\Users\jason\code\riskittogetthebrisket
git checkout main
git commit --allow-empty -m "protection probe"
git push origin main
```
This **should fail**. Then undo the local commit:
```powershell
git reset --hard HEAD~1
```

**Failure recovery.** If the empty push *succeeds*, the ruleset targeting is wrong — reopen it and confirm **Target branches** shows "Default branch" and Enforcement is **Active**, not "Evaluate".

**Risk:** Low · **Reversible:** Yes — Settings → Rules → Rulesets → `main-protection` → Delete · **Depends on:** OA-00 · **Stop point:** No.

---

#### OA-05 · Turn on Dependabot alerts, Dependabot security updates, and secret scanning

**Why this is necessary.** None of these are enabled or configured. `requirements.txt` contains **76 dependency lines and zero `==` pins** — so every deploy resolves whatever version is current, and you have no alerting when one of them ships a CVE. Secret scanning would have caught anything credential-shaped before it reached a public repo, which matters given OA-01.

**Evidence — CONFIRMED.**
- `ls .github/dependabot.yml` → **No such file or directory**.
- `grep -rl "codeql" .github/` → no matches. No code-scanning workflow exists.
- `ls SECURITY.md .github/SECURITY.md` → neither exists, so private vulnerability reporting has no intake document.
- `grep -c "==" requirements.txt` → **0**, against 76 total lines.

**Where I must do it.** GitHub website. *(The toggles are owner-only; I can write the `dependabot.yml` config file — that half is on my list as AC-04.)*

**Exact navigation.**
> GitHub → repository → **Settings** → **Advanced Security** (left sidebar; on some plans it reads **Code security and analysis**)

Then, in order:

| Control | Action | Note |
|---|---|---|
| **Dependabot alerts** | Click **Enable** | Free on public and private repos |
| **Dependabot security updates** | Click **Enable** | Opens PRs that fix vulnerable pins automatically |
| **Secret scanning** | Click **Enable** | On private repos this needs GitHub Advanced Security — if the button is greyed out, skip it and note that for me |
| **Push protection** | Click **Enable** (appears once secret scanning is on) | Blocks a commit containing a detectable credential |
| **Private vulnerability reporting** | Click **Enable** | Only meaningful while the repo is public |
| **Code scanning** | **Set up** → **Default** | CodeQL default setup; Python + JavaScript are both auto-detected here |

**Expected result.** Each row shows **Enabled**. Within roughly 10 minutes a **Security** tab appears with a Dependabot alert count.

**Verification.** GitHub → repository → **Security** → **Dependabot** — you should see either a list of alerts or "No open alerts", not "Dependabot alerts are not enabled".

**Failure recovery.** If Code scanning default setup fails, it is almost always because a workflow file it generates collides with an existing one. There is no CodeQL workflow here, so a failure means the language auto-detect picked something odd — switch to **Advanced** and it will commit a `.github/workflows/codeql.yml` you can inspect first.

**Risk:** Low · **Reversible:** Yes, every toggle flips back · **Depends on:** OA-01 (do it after, so you enable the correct plan's feature set) · **Stop point:** **Yes — tell me whether secret scanning was available, and how many Dependabot alerts appeared. Both change what I do next.**

---

#### OA-06 · Set GitHub Actions workflow permissions correctly

**Why this is necessary.** Six workflows write to the repository or open issues using `GITHUB_TOKEN`. If the repo-level default is "Read repository contents permission", the per-workflow `permissions:` blocks cannot grant more than the default allows, and those workflows fail silently at the write step. They are currently succeeding, which *implies* the setting is already permissive — but I cannot see the settings page, so this is a verification task, not a change task.

**Evidence — CONFIRMED (the requirement) / UNVERIFIED (the current setting).**
- `.github/workflows/scheduled-refresh.yml:36-39` — `permissions: contents: write, actions: write, issues: write`.
- `.github/workflows/refit-hill-curves.yml:55-57` — `contents: write, issues: write`.
- `.github/workflows/claude.yml:21-26` — `contents: write, pull-requests: write, issues: write, id-token: write`.
- `.github/workflows/e2e.yml:37-39`, `intel-refresh.yml:29-31`, `audit-identity-matches.yml:51-53` — `issues: write`.
- Inferred-working: run `30438842408` successfully posted to issue #588 (`gh issue comment` at 09:24:18), and `Scheduled Data Refresh` commits data to `main`. So writes work today.

**Where I must do it.** GitHub website.

**Exact navigation.**
> GitHub → repository → **Settings** → **Actions** → **General** → scroll to **Workflow permissions**

**Exact values.**

| Setting | Required value | Why |
|---|---|---|
| Workflow permissions | **Read and write permissions** | `scheduled-refresh.yml` commits data; `refit-hill-curves.yml` opens issues |
| Allow GitHub Actions to create and approve pull requests | **✅ ticked** | `claude.yml` requests `pull-requests: write` |

Also on the same page, under **Actions permissions**, confirm it is **Allow all actions and reusable workflows** — the workflows use `actions/checkout@v6`, `actions/setup-python@v6`, `actions/setup-node@v6`, `actions/upload-artifact@v4` and the third-party `anthropics/claude-code-action@v1`. A "Allow actions created by GitHub" restriction would break `claude.yml`.

**Expected result.** Both radio/checkbox states as above; **Save**.

**Verification.** Re-run a writing workflow and confirm it commits:
> GitHub → **Actions** → **Scheduled Data Refresh** → **Run workflow** → branch `main` → **Run workflow**

Green run with a `chore(...)` commit landing on `main`.

**Failure recovery.** If the run fails at the commit step with `403 Resource not accessible by integration`, the write permission did not save — reload the page and re-set it.

**Risk:** Low · **Reversible:** Yes · **Depends on:** OA-02 (set protection first, then confirm the bots can still work through it) · **Stop point:** No.

---

#### OA-07 · Confirm the `production` deployment environment and consider a protection rule

**Why this is necessary.** `.github/workflows/deploy.yml:206` declares `environment: production`. That environment must exist for the job to run, and it is where your SSH deploy credentials most plausibly live. Because deploy fires on **every** push to `main` (`deploy.yml:4-6`, minus `data/**` and `exports/**`), there is currently no human gate between a merged PR and your live site.

**Evidence — CONFIRMED (the wiring) / UNVERIFIED (the environment's contents and rules).**
- `.github/workflows/deploy.yml:206` — `environment: production`.
- `deploy.yml:217-221` reads `secrets.DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_PORT`, `DEPLOY_SSH_PRIVATE_KEY`, `DEPLOY_KNOWN_HOSTS`.
- `deploy.yml:240-243` hard-fails the run if `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_PRIVATE_KEY` or `DEPLOY_KNOWN_HOSTS` is empty. Six deploys succeeded in the last 12h, so **all four are configured** (inferred, but the guard makes it conclusive).

**Where I must do it.** GitHub website.

**Exact navigation.**
> GitHub → repository → **Settings** → **Environments** → **production**

**What to check and record for me.**
1. Under **Environment secrets** — list the *names* only (never the values). I expect `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_PRIVATE_KEY`, `DEPLOY_KNOWN_HOSTS`, and optionally `DEPLOY_PORT`.
2. Under **Deployment protection rules** — note whether **Required reviewers** is set.

**Optional change (recommended).** Tick **Required reviewers** and add yourself. Cost: one click per deploy. Benefit: no merge reaches production without you seeing it. Given that `deploy.yml` already has `allow_non_fast_forward` guards and an auto-rollback path, this is a preference, not a necessity — see Decision D-4.

**Expected result.** The environment page lists the four-or-five secret names with "Updated N days ago" beside each.

**Verification.** Already proven by the six green deploys. Nothing more to run.

**Failure recovery.** If the `production` environment does not exist at all, the deploys would be failing — they are not, so it exists.

**Risk:** Low · **Reversible:** Yes · **Depends on:** none · **Stop point:** **Yes — send me the secret *names* you see (not values). If `DEPLOY_PORT` is absent that is fine; `deploy.yml:246` defaults it to 22.**

---

#### OA-10 · Review the three open pull requests and dispose of the stale branches

**Why this is necessary.** Three PRs are open, all opened today against the same base. One contains the production security fix (OA-03). Thirty branches exist, most of them dead.

**Evidence — CONFIRMED.**

| PR | Branch | Merges cleanly? | CI | Notes |
|---|---|---|---|---|
| **#625** UI/IA audit | `claude/ui-ia-audit-1o1yku` | **NO** — `mergeable_state: "dirty"`, 4 conflicts | **no check runs at all** (`get_check_runs` → `total_count: 0`) | +3162/−929 across 62 files. **Contains the OA-03 security fix.** |
| **#626** Sharp/Insider separation | `claude/sharp-insider-audit-separation-fibqu6` | Yes | `Validate PR` → **success** | +15 commits |
| **#627** Debt round 2 | `claude/complete-codebase-audit-fzp0ye` | Yes | **pending** (run `30443003846` in progress at audit time) | +2 commits |

#625's four conflicts, from `git merge-tree --write-tree origin/main origin/claude/ui-ia-audit-1o1yku`:
- `data/scrape_state/sleeper_last_success` — generated refresh state, trivial
- `data/sleeper_last_good.json` — generated refresh state, trivial
- `frontend/app/draft/page.jsx` — **real code conflict**
- `frontend/app/page.jsx` — **real code conflict**

Branch inventory (30 total): 18 under `archive/*` (an existing deliberate convention — these predate the history rewrite and share no commits with `main`); 5 pre-rewrite branches carrying 3,761 commits with zero overlap with `main`'s 205 (`claude/e2e-r1-reconcile`, `claude/league-intel-projections`, `claude/league-intel-sim`, `claude/session-audit-handoff-tvxfc1`, `scratch/e2e-yml-probe`); `claude/tier3-snap-share` which is genuinely 1 unmerged commit on the current line; `claude/fully-implemented-riu0zp` which is **fully merged** (0 commits ahead of `main`).

**Where I must do it.** GitHub website, for the merges. The conflict resolution is mine (AC-01).

**Exact navigation and order.**

1. **Merge #627 first** (smallest, no conflicts, and it is the base the others were cut from):
   > GitHub → **Pull requests** → **#627** → wait for `Validate PR` to go green → **Merge pull request** → **Confirm merge**
2. **Merge #626 second:**
   > **Pull requests** → **#626** → **Merge pull request** → **Confirm merge**
3. **STOP.** Do not touch #625 yet. Tell me both are merged. I will rebase #625 onto the new `main`, resolve the two real conflicts, and push. Then you merge it (that is OA-03).
4. **Delete the one confirmed-merged branch:**
   > **Branches** (from the repo home, click the branch-count link) → find `claude/fully-implemented-riu0zp` → 🗑 icon
5. **Do not bulk-delete anything else yet.** The `archive/*` prefix is your own archival convention and the 3,761-commit branches are the only surviving copy of the pre-rewrite history. Deleting them is Decision **D-5**.

**Expected result.** #626 and #627 show **Merged**. `main` advances. `claude/fully-implemented-riu0zp` disappears from the branch list.

**Verification.**
```powershell
cd C:\Users\jason\code\riskittogetthebrisket
git fetch origin main
git log --oneline -5 origin/main
```
The top two entries should be the #627 and #626 merge commits.

**Failure recovery.** If a merge button is greyed out after OA-02, it is the new ruleset requiring `Validate PR` — wait for the check, or re-run it from the Actions tab.

**Risk:** Medium (two substantial PRs land at once) · **Reversible:** Yes — **Revert** button on each merged PR · **Depends on:** OA-02 · **Stop point:** **Yes — after step 3.**

---

#### OA-03 · Merge PR #625 to close the live production data leak — **CRITICAL**

**Why this is necessary.** Right now, anonymously, from anywhere on the internet, your production site hands out your proprietary rookie valuations.

**Evidence — CONFIRMED by live probe, 2026-07-29 10:24 UTC.**

```
$ curl -sS https://chaseupside.com/api/draft-capital
{"picks":[{"pick":"1.01",...,"originalOwner":"jstuedle","currentOwner":"jstuedle",
 "rookieName":"Jeremiyah Love","rookiePos":"RB","rookieKtcValue":137.0,
 "rookieKtcDollar":140.5,"rookieIdpDollar":131.5}, ...
```

```
$ curl -o /dev/null -w "%{http_code} %{size_download}" https://chaseupside.com/rankings
200 54551
```

```
$ curl -o /dev/null -w "%{http_code}" https://chaseupside.com/api/data
401                      # ← this one is correct; the /api/ gate holds
```

PR #625's own description names both defects and the mechanism: `/api/draft-capital` is on the public API allowlist so the public league tab can read pick ownership, but every pick also carries `rookie*` fields filled from `_our_rookie_pool()` reading `latest_contract_data["playersArray"]` ordered by `rankDerivedValue`. And: "nginx routes `location /` straight to Next, so `server.py`'s page gates never run." The fix adds `frontend/middleware.js` and strips `rookie*` for unauthenticated callers, returning a **copy** so the shared cache is not poisoned for authenticated `/draft` users.

**Where I must do it.** GitHub website.

**Exact navigation.**
> GitHub → **Pull requests** → **#625** → confirm the conflict banner is gone and `Validate PR` is green → **Merge pull request** → **Confirm merge**

**Expected result.** #625 shows **Merged**. `Deploy Production` fires automatically on the resulting `main` push (`deploy.yml:4-6`) and takes ~10 minutes.

**Verification — run this after the deploy goes green.**
```powershell
curl.exe -s https://chaseupside.com/api/draft-capital | Select-String -Pattern "rookieKtcValue"
curl.exe -s -o NUL -w "%{http_code}`n" https://chaseupside.com/rankings
```
Expected: the first command prints **nothing** (no matches). The second prints **307** or **302** (a redirect to `/login`), not 200.

**Failure recovery.** If `rookieKtcValue` still appears after deploy, the response is cached — `/api/draft-capital` has a shared TTL cache. Wait 5 minutes and retry. If it persists, tell me and I will trace `_public_api_allowlist` in `server.py` directly.

**Risk:** High (62 changed files, nav restructure, new middleware) · **Reversible:** Yes — **Revert** on the PR, then `Deploy Production` → **Run workflow** · **Depends on:** OA-10 step 3, and my conflict resolution (AC-01) · **Stop point:** **Yes — confirm the two verification commands' output to me before you consider this closed.**

---

### Phase 3 — Secrets and environment variables

---

#### OA-08 · Add the `IDPSHOW_SESSION_JSON` repository secret (optional, resilience only)

**Why this is necessary.** The IDP Show rankings source is currently produced by exactly one machine — a systemd timer on your VPS. The CI path is fully built but inert because the secret is unset. If the VPS timer breaks, that source silently stops with no CI fallback. `idpShow` supplies 278 of the 1,094 players on your live board.

**Evidence — CONFIRMED (the wiring) / UNVERIFIED (whether the secret is set).**
- `.github/workflows/scheduled-refresh.yml:136` — `IDPSHOW_SESSION_JSON: ${{ secrets.IDPSHOW_SESSION_JSON }}`.
- `scheduled-refresh.yml:393` — `echo "IDPSHOW_SESSION_JSON not configured; skipping idpShow (prod timer remains its producer)"`.
- `UNIMPLEMENTED_BACKLOG.md` §10 lists this as operator-only: *"Add as a repo secret to let CI fetch IDP Show. Workflow is pre-wired and inert."*
- Live confirmation the prod timer *is* working: `/api/status` → `"idpShow": {"lastFetched": "2026-07-29T08:32:25+00:00", "ageHours": 1.87}`, and commit `123f4cb chore(idpshow): automated refresh 2026-07-29T08:32:25Z`.

**Where I must do it.** Two places: **The IDP Show website** (to get the value), then **GitHub website** (to store it).

**Exact navigation — retrieving the value.**
1. In a browser, sign in to The IDP Show's subscriber site as you normally do.
2. Open DevTools (**F12**) → **Application** tab → **Storage** → **Cookies** → the IDP Show origin.
3. You need three cookies: `connect.sid`, `AWSALBTG`, `AWSALBTGCORS`.
4. Assemble them into a single JSON object.

**Format.** A JSON object, one key per cookie:
```json
{"connect.sid":"<value>","AWSALBTG":"<value>","AWSALBTGCORS":"<value>"}
```
If your VPS already has the file, it is easier to copy it wholesale — it is at `/var/lib/idpshow-fetch/idpshow_session.json` (`deploy/systemd/README.md:69`). Retrieve it without printing it to your screen:
```powershell
scp dynasty@<your-deploy-host>:/var/lib/idpshow-fetch/idpshow_session.json $env:TEMP\idpshow_session.json
```
Then open that file in Notepad, select all, copy — and **delete the file afterwards**:
```powershell
Remove-Item $env:TEMP\idpshow_session.json
```

**Exact navigation — storing it.**
> GitHub → repository → **Settings** → **Secrets and variables** → **Actions** → **Secrets** tab → **New repository secret**

| Field | Value |
|---|---|
| Name | `IDPSHOW_SESSION_JSON` |
| Secret | paste the JSON object |

**Where it belongs:** GitHub Actions **only**. Not local dev, not preview, not production — production already has the file on disk.

**Expected result.** `IDPSHOW_SESSION_JSON` appears in the Actions secrets list with "Updated now".

**Verification.**
> GitHub → **Actions** → **Scheduled Data Refresh** → **Run workflow** → `main` → **Run workflow**

Open the run, expand **Run scraper**, and search the log. The line `IDPSHOW_SESSION_JSON not configured; skipping idpShow` should be **gone**.

**Failure recovery.** If the log shows an idpShow authentication failure instead of a skip, the cookies have expired — repeat the retrieval. These sessions are short-lived, which is exactly why the VPS timer (which refreshes its own jar) remains the primary producer. **This secret is a backup, not a replacement.**

**Risk:** Low · **Reversible:** Yes — delete the secret · **Depends on:** OA-01 (do not add secrets to a public repo's Actions until you have settled visibility) · **Stop point:** No.

---

#### OA-09 · Verify or rotate `INTEL_REFRESH_TOKEN`

**Why this is necessary.** `UNIMPLEMENTED_BACKLOG.md` §10 records this as *"Unverified whether completed"* — a previous session flagged a rotation and nobody confirmed it. The token is a bearer credential that grants `/api/intel/refresh` on production. If the repository has been public since March (`created_at: 2026-03-09`), and this token was ever echoed by a workflow, it is compromised.

**Evidence — CONFIRMED (the mechanism) / UNVERIFIED (the token's state).**
- `.env.example:105-118` — documents `INTEL_REFRESH_TOKEN`, generation via `openssl rand -hex 32`, and that the same value must exist as the repo secret and in the VPS `.env`.
- `.github/workflows/intel-refresh.yml:65,143` — `TOKEN: ${{ secrets.INTEL_REFRESH_TOKEN }}`; `:69` fails the run when unset.
- `intel-refresh.yml:50-56` — refuses to send the bearer to a guessed host if `vars.PROD_PUBLIC_URL` is unset. Good hygiene, and it means the variable is set (runs succeed).
- Working: intel-refresh runs `30354762721` (2026-07-28) and `30266531871` (2026-07-27) both **success**.

**Where I must do it.** Local terminal (to generate), then GitHub website and your VPS (to store). Rotation touches **two** places and they must match.

**Decision first.** If you are confident the token has never been printed in a public log, skip this and just record it as verified. If unsure — and given OA-01, "unsure" is the honest default — rotate. See Decision D-2.

**Commands — generate the new value without putting it in your shell history.**
```powershell
# Generates a token and copies it straight to the clipboard. Nothing is printed.
$tok = -join ((1..32) | ForEach-Object { '{0:x2}' -f (Get-Random -Max 256) })
Set-Clipboard -Value $tok
Remove-Variable tok
Write-Host "New token is on your clipboard. Paste it into GitHub, then into the VPS .env. Then clear the clipboard."
```

**Exact navigation — GitHub side.**
> GitHub → repository → **Settings** → **Secrets and variables** → **Actions** → find `INTEL_REFRESH_TOKEN` → **Update** (pencil icon) → paste → **Save**

**Exact commands — VPS side.** Both halves must carry the same value or the daily intel refresh 401s.
```bash
ssh dynasty@<your-deploy-host>
sudo cp /home/dynasty/trade-calculator/.env /home/dynasty/trade-calculator/.env.bak-2026-07-29   # backup first
sudo nano /home/dynasty/trade-calculator/.env
# Edit the INTEL_REFRESH_TOKEN= line. Plain KEY=value, no `export`, per .env.example:113-115.
sudo systemctl restart dynasty
sudo systemctl is-active dynasty
```
The restart is mandatory — `.env.example:113-115` states the token is read at process start.

**Then clear your clipboard:**
```powershell
Set-Clipboard -Value " "
```

**Expected result.** `dynasty` reports `active`.

**Verification.**
> GitHub → **Actions** → **Sharp Tracker intel refresh** → **Run workflow** → **Run workflow**

A green run. A red run with a 401 means the two halves disagree.

**Failure recovery.** Restore the backup and restart:
```bash
sudo cp /home/dynasty/trade-calculator/.env.bak-2026-07-29 /home/dynasty/trade-calculator/.env
sudo systemctl restart dynasty
```
Then put the old value back in the GitHub secret.

**Risk:** Medium (a mismatch breaks the daily intel refresh until fixed) · **Reversible:** Yes, via the `.env` backup · **Depends on:** OA-01 · **Stop point:** No.

---

#### OA-11 · Decide on `ANTHROPIC_API_KEY` (weekly narratives are currently skipped)

**Why this is necessary.** The weekly league-narrative generator is fully built and has never run successfully. Its own workflow file records the history.

**Evidence — CONFIRMED.**
- `.github/workflows/weekly-narratives.yml:78` — `ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}`.
- `weekly-narratives.yml:80-82` — *"The generator hard-requires ANTHROPIC_API_KEY (repo secret) ... 'ERROR: ANTHROPIC_API_KEY not set' (8 straight failures as of ...)"*.
- `weekly-narratives.yml:87-92` — now a graceful skip: `::warning title=ANTHROPIC_API_KEY not configured::Weekly narrative generation skipped`.
- `scripts/generate_weekly_narratives.py:30` — `ANTHROPIC_API_KEY env var must be set`.
- **Not needed elsewhere.** `src/api/chat.py:222` also reads it, but that module is dead — `grep "from src.api.chat" server.py` returns nothing, matching `UNIMPLEMENTED_BACKLOG.md` §9 item 5 ("dead proxy removed"). `src/news/digest.py:61` degrades gracefully without it.

**So the only thing this key buys you is the weekly narrative feature.** It is a paid API and therefore a spending decision — Decision **D-3**.

**Where I must do it.** Anthropic Console, then GitHub website.

**Exact navigation — if you want the feature.**
1. → `https://console.anthropic.com/` → sign in → **Settings** → **API keys** → **Create Key**
2. Name it `riskit-weekly-narratives`. Copy the value (shown once).
3. → GitHub → repository → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

| Field | Value |
|---|---|
| Name | `ANTHROPIC_API_KEY` |
| Secret | the `sk-ant-...` value |

**Format.** Starts `sk-ant-api03-`. **Where it belongs:** GitHub Actions only.

**If you do not want the feature:** do nothing. The workflow already skips cleanly and I will note it as a deliberate no-op in the docs (AC-06).

**Expected result.** The secret appears in the list.

**Verification.**
> GitHub → **Actions** → **Weekly narratives** → **Run workflow**

Green, with narrative files committed under `data/league_narratives/`.

**Failure recovery.** A 401 from the API means the key was truncated on paste; recreate it. A 429 means no billing credit on the Anthropic account.

**Risk:** Low · **Reversible:** Yes — delete the secret; the workflow returns to skipping · **Depends on:** OA-01 · **Stop point:** No.

---

### Phase 4 — External service dashboards

---

#### OA-12 · Run the certbot renewal dry-run on the VPS

**Why this is necessary.** `UNIMPLEMENTED_BACKLOG.md` §10 lists this as unverified operator work. TLS on `chaseupside.com` is currently valid (I confirmed `ssl_verify=0` on a live request), but a valid cert today says nothing about whether *renewal* will succeed in 60 days. A silent renewal failure takes the whole site down.

**Evidence — CONFIRMED.**
- `UNIMPLEMENTED_BACKLOG.md` §10 — *"certbot renewal dry-run | `ssh root@chaseupside.com "certbot renew --dry-run"`"*.
- `deploy/PRODUCTION_BOOTSTRAP.md:73-84` — nginx terminates TLS; `deploy/nginx/chaseupside.com.conf` is the live config.
- Live: `curl -o /dev/null -w "%{http_code} %{ssl_verify_result}" https://chaseupside.com/` → `200 0`. Cert valid **now**.
- Related risk, CONFIRMED from the repo: `deploy/nginx/riskittogetthebrisket.org.conf:1-25` is marked ⚠ SUPERSEDED — DO NOT APPLY, because `riskittogetthebrisket.org` **lapsed and now resolves to a third party**. Its `:443` block points at `/etc/letsencrypt/live/riskittogetthebrisket.org/` paths that no longer exist, so applying it fails `nginx -t` and aborts the reload. Do not let any tooling install that file.

**Where I must do it.** Local terminal, over SSH to your VPS.

**Commands.** `--dry-run` contacts Let's Encrypt's staging endpoint and writes nothing.

```bash
ssh root@<your-deploy-host>
certbot certificates
certbot renew --dry-run
```

**Expected result.** `certbot certificates` lists `chaseupside.com` with a future expiry. `certbot renew --dry-run` ends with:
```
Congratulations, all simulated renewals succeeded:
  /etc/letsencrypt/live/chaseupside.com/fullchain.pem (success)
```

**Verification.** Also confirm the renewal timer is armed:
```bash
systemctl list-timers certbot.timer snap.certbot.renew.timer 2>/dev/null
```
One of them should show a NEXT time.

**Failure recovery.** If the dry-run fails with an HTTP-01 challenge error, nginx is not serving `/.well-known/acme-challenge/` — check `deploy/nginx/chaseupside.com.conf` for that location block. If it fails because a *second* site file is enabled, run `ls /etc/nginx/sites-enabled/` and confirm `riskittogetthebrisket.org` is **not** symlinked there (per the ⚠ note above, both files declare the same upstreams and cache zone, so both being enabled fails `nginx -t` outright).

**Risk:** Low (dry-run is non-destructive) · **Reversible:** N/A, read-only · **Depends on:** none · **Stop point:** **Yes — paste the `certbot certificates` expiry date to me.**

---

#### OA-13 · Verify the DLF session before it expires (6.5 days left)

**Why this is necessary.** Your live board reads four DLF boards (`dlfSf` 279 players, `dlfIdp` 165, `dlfRookieSf` 53, `dlfRookieIdp` 27). The session cookie backing them expires in under a week. When it lapses, those four sources stop and the board silently narrows.

**Evidence — CONFIRMED by live probe.** `GET https://chaseupside.com/api/health` →
```json
"session_cookies": {
  "dlf_session.json": {"present": true, "autoRefresh": true, "ageDays": 7.5,
                       "lifetimeDays": 14, "daysRemaining": 6.5,
                       "warnSoon": false, "expired": false},
  "draftsharks_session.json": {"present": false, "autoRefresh": true},
  "idpshow_session.json": {"present": false, "autoRefresh": false}
}
```
`autoRefresh: true` means `scripts/fetch_dlf.py` re-logs-in using `DLF_USERNAME`/`DLF_PASSWORD` when the cookie lapses — so this should self-heal. **The action is to confirm those credentials are still valid**, not to hand-refresh the cookie.

Note the two `present: false` entries are expected, not defects: `deploy/idpshow_fetch_and_push.sh:73,93-94` copies the IDP Show jar into the repo directory only for the duration of a fetch and copies it back to `/var/lib/idpshow-fetch/`, and `git checkout --force` during deploy removes it. Both sources are demonstrably producing (`idpShow` fetched 1.87h ago, `draftSharks` 2.85h ago).

**Where I must do it.** The DLF (DynastyLeagueFootball) website, then optionally GitHub.

**Exact navigation.**
1. → `https://dynastyleaguefootball.com/` → **Log in** with the account whose credentials are in `DLF_USERNAME`/`DLF_PASSWORD`.
2. Confirm the subscription is active and not expiring, and that the password has not been changed since the secret was stored.
3. If the password changed:
   > GitHub → **Settings** → **Secrets and variables** → **Actions** → `DLF_PASSWORD` → **Update**

   And on the VPS, update the same value in `/home/dynasty/trade-calculator/.env`, then `sudo systemctl restart dynasty`.

**Expected result.** A working DLF login, subscription active.

**Verification.** Wait for the next auto-refresh, then:
```powershell
curl.exe -s https://chaseupside.com/api/health | ConvertFrom-Json | Select-Object -ExpandProperty session_cookies
```
`daysRemaining` should reset toward 14.

**Failure recovery.** If DLF sources go stale, `.github/workflows/scheduled-refresh.yml:601,612` raises an explicit error naming `DLF_USERNAME`/`DLF_PASSWORD`, so you will not miss it.

**Risk:** Low · **Reversible:** Yes · **Depends on:** none · **Stop point:** No.

---

### Phase 5 — Local terminal commands

---

#### OA-14 · Bring your local checkout up to date and prove the test suite runs

**Why this is necessary.** Every later local task assumes a working environment. Also worth knowing: `ASSISTANT_COORDINATION.md` requires `git pull --ff-only origin main` at session start, and this session's merges will have moved `main` under you.

**Evidence — CONFIRMED.**
- `ASSISTANT_COORDINATION.md` — *"Use this folder for all Claude, ChatGPT/Codex, and local development: `C:\Users\jason\code\riskittogetthebrisket`"* and the start-of-session pull.
- `README.md:38-46` — `make setup` / `make test` is the sanctioned bootstrap.
- **Important OS note:** `Makefile:34` calls `bash scripts/setup.sh`. Your primary dev machine is Windows (`CLAUDE.md` — *"Platform: Windows (primary dev via `.bat` files)"*; `start_dynasty.bat`, `sync.bat`). **`make` and `bash` are not available in plain PowerShell.** The PowerShell-native equivalent is in the runbook at §4, block 3.
- CI pins **Python 3.12** (`grep 'python-version' .github/workflows/` → `"3.12"` only) and **Node 20** (`node-version: "20"`). There is no `.nvmrc` and no `engines` field, so nothing enforces this locally.

**Where I must do it.** Local terminal (Windows PowerShell).

**Commands.** See §4 blocks 1–4 for the copy-paste version.

**Expected result.** `pytest` collects and runs the suite. Recent PR descriptions cite ~5,046–5,382 Python tests and ~1,390–1,457 frontend tests passing, so a green run in that range is normal.

**Verification.** The final line of pytest reads `N passed` with `0 failed`.

**Failure recovery.** `UNIMPLEMENTED_BACKLOG.md` §9 item 2 records one known-flaky test: `test_anchor_curve_extrapolation_monotone` fails on `main` because `Chase Young` ties at rank 107 against a strictly-increasing assertion. It is `livedata`-marked and **CI deselects it**, so if that is your only failure, it is a known-open defect, not something you broke.

**Risk:** Low · **Reversible:** N/A · **Depends on:** OA-10, OA-03 (pull *after* the merges) · **Stop point:** **Yes — paste the pytest summary line to me.**

---

### Phase 6 — Database and migrations

**There is no migration to run, and no migration tool in this project.** This is a genuine finding, not an omission.

**Evidence — CONFIRMED.** Persistence is SQLite files created on demand by `src/api/session_store.py` and the `user_kv` store, following a stdlib-only pattern. No Alembic, no Django migrations, no Prisma — `requirements.txt` contains no migration library. Backups are already automated: `deploy/systemd/README.md` documents `riskit-backup.timer` (nightly 02:00 UTC online SQLite backup of `user_kv` + `session_store`) and `riskit-backup-restore-test.timer` (weekly Monday 03:30 UTC integrity check), and live `/api/health` returns a `backup_health` block.

One item exists, but it belongs to an unmerged PR:

---

#### OA-15 · (Only after PR #626 merges) Run the intel-ledger migration on production

**Why this is necessary.** PR #626 introduces a new normalized SQLite store (`src/intel/ledger.py`) and a one-time snapshot→ledger import. It does not run itself. Until it runs, the new ledger is empty and the old `aggregate.py` read path continues to serve — which is by design for this stage, but the migration is the point of the PR.

**Evidence — CONFIRMED** from PR #626's own "Manual validation" section: `python scripts/migrate_intel_ledger.py --dry-run`, then `python scripts/migrate_intel_ledger.py`. The PR states the import is idempotent by construction (it reuses the crawler's deterministic `eventId` as `movement_id`) and that re-ingest was tested for byte-identical aggregates across 10 runs.

**Where I must do it.** Local terminal, over SSH to your VPS. It must run on production because `data/` is gitignored and the endpoints read local files.

**Commands. Dry-run first — it writes nothing.**
```bash
ssh dynasty@<your-deploy-host>
cd /home/dynasty/trade-calculator
sudo systemctl start riskit-backup.service          # fresh backup before any write
/home/dynasty/.venvs/trade-calculator/bin/python scripts/migrate_intel_ledger.py --dry-run
```

**Read the dry-run output before continuing.** It reports event counts by `txType`. Then:
```bash
/home/dynasty/.venvs/trade-calculator/bin/python scripts/migrate_intel_ledger.py
```

**Expected result.** The dry-run prints a per-`txType` breakdown. The real run imports and exits 0.

**Verification.**
```bash
curl -s http://127.0.0.1:8000/api/intel/coverage | head -c 400
```
Look for a non-empty `coverage.movementsByTxType`.

**Failure recovery.** The import is idempotent — re-running is safe. If it errors, the ledger is additive and nothing existing is modified; restore from the backup you just took only if `/api/intel/*` starts failing.

**Risk:** Medium · **Reversible:** Yes (backup taken; ledger runs alongside the existing path, does not replace it this stage) · **Depends on:** OA-10 (#626 merged) **and** the subsequent `Deploy Production` run completing · **Stop point:** **Yes — paste the dry-run output to me before running the real import.**

---

### Phase 7 — Deployment

*No manual deployment steps remain.* `deploy.yml` deploys automatically on push to `main`, and the production host is already bootstrapped: `deploy/PRODUCTION_BOOTSTRAP.md`'s sudoers policy, base packages, Playwright OS deps, nginx and TLS are all evidenced as complete by six green deploys and a healthy live site. `README.md` and `PRODUCTION_BOOTSTRAP.md` describe first-time setup — **treat those as history, not as a to-do list.** See §11.

---

### Phase 8 — Verification and cleanup

---

#### OA-04 · Decide what to do about the two failing E2E suites

**Why this is necessary.** Two scheduled suites are red, and one of them tests **live production**. This is not test flakiness — the same three specs fail in both, which is the signature of a real regression.

**Evidence — CONFIRMED.**

`Production E2E Smoke (public /league)` run `30429179456` → **failure**. 6 failed, 26 passed. This runs against `https://chaseupside.com`:
```
[desktop-1366] public-league.spec.js:159 › deep links via ?tab= query param land on the right tab
[desktop-1366] public-league.spec.js:163 › franchise deep link via ?owner= opens the selected franchise
[desktop-1366] public-league.spec.js:218 › archives filter narrows the result set
[mobile-chromium] — the same three
```

`E2E Safety Net` run `30438842408` → **failure**. 13 failed, 123 passed, 49 skipped. Superset of the same three, plus CI-only data-shape failures:
```
Error: public league contract must expose rivalry pairs — zero means the rivalry aggregation broke
Error: public league contract must expose matchups — zero means the matchup feed broke
Error: public league player index must not be empty
expect(assignments.length).toBeGreaterThanOrEqual(8)
Error: league sub-nav is missing tabs: Draft Capital, Home, History, Rivalries, Awards, ...
```

Issue **#588** ("E2E safety net failing") is the auto-opened tracker, last commented 2026-07-29 09:24.

**Reading of the evidence.** The three specs failing in *both* are a genuine production regression in the public `/league` page's deep-linking (`?tab=`, `?owner=`) and archives filter. The additional CI-only failures are data-shape assertions that the runner cannot satisfy — the sub-nav failure lists *every* tab as missing, which is what an empty contract looks like, not a broken nav.

**Where I must do it.** Nowhere — this is **my** work, not yours. It is on this list only because it is a stop point.

**What I need from you:** a decision on sequencing. Note that PR #625 restructures `/league` navigation and moves `/league/phases` → `/phases`, so it will change these specs' behaviour either way. My recommendation is to **merge #625 first (OA-03), let it deploy, then re-run both suites** — fixing the specs before that lands would be fixing the wrong tree. See Decision **D-6**.

**Verification after #625 deploys.**
> GitHub → **Actions** → **Production E2E Smoke (public /league)** → **Run workflow**

**Risk:** N/A (decision only) · **Depends on:** OA-03 · **Stop point:** **Yes.**

---

#### OA-16 · Decide whether to promote the Hill-curve challenger (Issue #613)

**Why this is necessary.** A model challenger cleared its held-out gate and is waiting. **By design, no automation may promote it** — `CLAUDE.md` states production constants move only via a human running `scripts/model_registry.py promote` + `apply`, per ADR-008 in `docs/roster-trade-intelligence/DECISIONS.md`. This is the single item in the project that is architecturally reserved for a human.

**Evidence — CONFIRMED.** Issue **#613**, opened 2026-07-28 by `github-actions`:
```
champion v1: criterion 826.7  (mean per-source RMSE, lower is better)
challenger:  criterion 787.8
verdict: PROMOTABLE
reason:  challenger improves the held-out criterion by 38.8 points
         (826.7 -> 787.8), clearing the 25-point margin
```
`config/model_registry/hill_scope_masters.json` confirms `"championVersion": 1` — the challenger is recorded but not live.

The issue also carries a caveat you should weigh: *"only HILL_PERCENTILE_C / HILL_PERCENTILE_S (the OFFENSE master) are validated out of sample. The other six constants are versioned but not gated."* The largest drift is **IDP at RMSE 366.81** — and that is one of the ungated six.

**Where I must do it.** Local terminal.

**Commands.** Windows PowerShell, from the working copy, on a task branch.
```powershell
cd C:\Users\jason\code\riskittogetthebrisket
git checkout main
git pull --ff-only origin main
git checkout -b claude/promote-hill-v2

.\.venv\Scripts\python.exe scripts\model_registry.py validate 2
```

**Read the validate output. Only if it passes:**
```powershell
.\.venv\Scripts\python.exe scripts\model_registry.py promote 2 --reason "held-out win: 826.7 -> 787.8"
.\.venv\Scripts\python.exe scripts\model_registry.py apply
.\.venv\Scripts\python.exe -m pytest tests\ -q
```

**Expected result.** `validate 2` reports the challenger is valid. `apply` rewrites the Hill constants in `src/canonical/player_valuation.py`. The test suite stays green.

**Verification.** Inspect exactly what moved before you push:
```powershell
git diff --stat
git diff src\canonical\player_valuation.py
```

**Then stop and send me that diff.** This changes every player value on your board. I want to measure the blast radius (how many rows move, and by how much) before it reaches production — `CLAUDE.md` rule 4 requires verifying downstream effects for any value change.

**Failure recovery.** Nothing has been pushed, so:
```powershell
git checkout main
git branch -D claude/promote-hill-v2
```

**Risk:** High — this moves every value on the live board · **Reversible:** Yes, until pushed; afterwards via `promote 1` + `apply` · **Depends on:** OA-14 (working venv) · **Stop point:** **Yes — send me `git diff --stat` and do not push.**

---

#### OA-17 · Confirm production is not running in E2E test mode

**Why this is necessary.** `server.py` exposes `/api/test/create-session`, which mints a session for an arbitrary username. It is gated on two env vars. If both were ever set on production, it is an authentication bypass.

**Evidence — CONFIRMED (the gate) / UNVERIFIED (production's env).**
- `server.py:10570-10571` — the endpoint requires `E2E_TEST_MODE=1` **and** a matching `E2E_TEST_SECRET` bearer.
- `server.py:2757` — *"Returns 404 unless E2E_TEST_MODE + matching bearer secret are"* set.
- `server.py:10597` — fails closed: *"/api/test/create-session refused: E2E_TEST_MODE is on but..."*.
- Only ever set in CI: `.github/workflows/e2e.yml:141-142` sets `E2E_TEST_MODE=1` and a per-run random secret on the runner.
- Not in `.env.example` — so there is no template nudging it onto production.

**Strong indirect evidence it is off:** the design is fail-closed and the variable is absent from every production artifact. But "absent from the repo" is not "absent from the VPS `.env`", which I cannot read.

**Where I must do it.** Local terminal, over SSH.

**Commands.**
```bash
ssh dynasty@<your-deploy-host>
grep -E "E2E_TEST_MODE|E2E_TEST_SECRET|E2E_TEST_USERNAME" /home/dynasty/trade-calculator/.env || echo "CLEAN: no E2E vars in .env"
```

**Expected result.** `CLEAN: no E2E vars in .env`.

**Verification (independent, from your own machine — no SSH needed):**
```powershell
curl.exe -s -o NUL -w "%{http_code}`n" -X POST https://chaseupside.com/api/test/create-session
```
Expected: **404**. Anything else — especially 200 or 401 — means the gate is live and you should tell me immediately.

**Failure recovery.** If the vars are present, remove those lines from `.env` and `sudo systemctl restart dynasty`, then re-run the curl and confirm 404.

**Risk:** Low to check, Critical if it fails · **Reversible:** N/A · **Depends on:** none · **Stop point:** **Yes — send me the HTTP code.**

---

## 4. Copy-and-Paste Terminal Runbook

**Shell:** Windows PowerShell. **Working directory:** `C:\Users\jason\code\riskittogetthebrisket` unless stated.

> **Why PowerShell and not `make`:** `CLAUDE.md` records Windows as the primary dev platform and the repo ships `.bat` launchers. `Makefile:34` shells out to `bash scripts/setup.sh`, which plain PowerShell cannot run. Blocks 2–4 below are the PowerShell-native equivalent of `make setup` + `make test`, calling the same `requirements-dev.txt` and the same `scripts/check_env.py` preflight that CI uses (`.github/workflows/deploy.yml:52,60`). If you prefer WSL, `make setup && make test` works there unchanged.

---

### Block 1 — Orient (read-only)

**Purpose:** confirm where you are, what branch, which remote, and which runtimes.
**Directory:** the working copy · **Changes files:** No · **Changes infrastructure:** No · **Safe to rerun:** Yes

```powershell
cd C:\Users\jason\code\riskittogetthebrisket
Get-Location
git remote -v
git status --short --branch
git branch --show-current
python --version
node --version
npm --version
Test-Path .env
Test-Path .venv\Scripts\python.exe
```

**Expected:** remote is `https://github.com/jasonleetucker-code/riskittogetthebrisket.git`; Python reports **3.12.x** (CI pins 3.12 — a different minor is the single most likely source of a local-only test failure); Node reports **20.x**; `.env` exists (`True`).

---

### Block 2 — Sync to the new `main` (changes files, no infrastructure)

**Purpose:** pull the merges from OA-10 and OA-03.
**Directory:** the working copy · **Changes files:** Yes (fast-forward only) · **Changes infrastructure:** No · **Safe to rerun:** Yes
**Run this only after OA-10 and OA-03 are merged.**

```powershell
cd C:\Users\jason\code\riskittogetthebrisket
git stash list
git status --short
git checkout main
git pull --ff-only origin main
git log --oneline -6
```

`--ff-only` is deliberate: it refuses rather than creating a merge commit if your local `main` has diverged. If it refuses, stop and tell me — do not force anything.

---

### Block 3 — Create the virtualenv and install dependencies

**Purpose:** the PowerShell equivalent of `make setup`.
**Directory:** the working copy · **Changes files:** Yes (creates `.venv\`) · **Changes infrastructure:** No · **Safe to rerun:** Yes (idempotent)

```powershell
cd C:\Users\jason\code\riskittogetthebrisket
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe scripts\check_env.py
```

**Expected:** `pip check` prints `No broken requirements found.` and `check_env.py` exits 0. These are the exact two gates CI runs (`deploy.yml:52-62`), so passing here means CI will not fail on dependencies.

---

### Block 4 — Run the test suites

**Purpose:** prove the checkout is sound.
**Directory:** the working copy · **Changes files:** No · **Changes infrastructure:** No · **Safe to rerun:** Yes

```powershell
cd C:\Users\jason\code\riskittogetthebrisket
.\.venv\Scripts\python.exe -m pytest tests\ -q
```

Then the frontend suite:

```powershell
cd C:\Users\jason\code\riskittogetthebrisket\frontend
npm ci
npm run test
cd ..
```

**Expected:** pytest in the ~5,000–5,400 passed range, 0 failed (one known-open exception — see OA-14 failure recovery). Vitest ~1,390–1,460 passed.

`npm ci` rather than `npm install`: it installs exactly `frontend/package-lock.json` and is what CI uses (`deploy.yml:192`).

---

### Block 5 — Formatting and lint gates (what CI blocks on)

**Purpose:** reproduce the two gates that can fail a PR.
**Directory:** the working copy · **Changes files:** No (`--check` only) · **Changes infrastructure:** No · **Safe to rerun:** Yes

```powershell
cd C:\Users\jason\code\riskittogetthebrisket
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m ruff check . --output-format concise
```

**Expected:** `ruff format --check` reports nothing to reformat — **this one hard-blocks** (`deploy.yml:74-79`). `ruff check` will print a backlog of pre-existing findings; that is **expected and report-only** on `main` (`deploy.yml:81-88`), enforced only on changed files in PRs.

---

### Block 6 — Build the frontend the way production does

**Purpose:** catch a build break before it reaches deploy.
**Directory:** `frontend\` · **Changes files:** Yes (`.next\`) · **Changes infrastructure:** No · **Safe to rerun:** Yes

```powershell
cd C:\Users\jason\code\riskittogetthebrisket\frontend
npm run build
cd ..
```

`npm run build` runs `next build` **and** `scripts/check-bundle-sizes.mjs` — the same pair CI runs.

---

### Block 7 — Run the stack locally

**Purpose:** manual smoke.
**Directory:** the working copy · **Changes files:** Yes (writes into `data\`) · **Changes infrastructure:** No · **Safe to rerun:** Yes

```powershell
cd C:\Users\jason\code\riskittogetthebrisket
.\start_stack.bat
```

Opens two windows: backend on `:8000`, Next on `:3000`. Then in a third terminal:

```powershell
curl.exe -s http://127.0.0.1:8000/api/health
curl.exe -s -o NUL -w "%{http_code}`n" http://127.0.0.1:3000/
```

---

### Block 8 — Production verification from your machine (read-only)

**Purpose:** confirm the OA-03 fix landed and the site is healthy.
**Directory:** any · **Changes files:** No · **Changes infrastructure:** No · **Safe to rerun:** Yes

```powershell
curl.exe -s https://chaseupside.com/api/health
Write-Host "--- draft-capital leak check (expect NO output) ---"
curl.exe -s https://chaseupside.com/api/draft-capital | Select-String -Pattern "rookieKtcValue"
Write-Host "--- private page (expect 307 or 302, NOT 200) ---"
curl.exe -s -o NUL -w "%{http_code}`n" https://chaseupside.com/rankings
Write-Host "--- private API (expect 401) ---"
curl.exe -s -o NUL -w "%{http_code}`n" https://chaseupside.com/api/data
Write-Host "--- test-session endpoint (expect 404) ---"
curl.exe -s -o NUL -w "%{http_code}`n" -X POST https://chaseupside.com/api/test/create-session
```

---

### Destructive commands — isolated, and not required by this audit

Nothing on this checklist needs `git reset --hard`, `git clean -fd`, a force push, a database drop, or a branch deletion beyond the single confirmed-merged branch in OA-10. **If you find yourself typing one of those, stop and ask me first.**

The one guarded exception, only if OA-16 goes wrong before you push:
```powershell
# Discards the Hill-curve promotion branch. Verify the branch name first.
cd C:\Users\jason\code\riskittogetthebrisket
git branch --show-current            # ← must print claude/promote-hill-v2
git checkout main
git branch -D claude/promote-hill-v2
```

---

## 5. GitHub Website Checklist

Cross-references to the master task numbers in §3.

| Setting | Current status | Recommended | Change required? | Click path | Why it matters |
|---|---|---|---|---|---|
| **Repository visibility** | **Public** — CONFIRMED (`"visibility": "public"`) | **Private** | **YES — critical** (OA-01) | Settings → Danger Zone → Change repository visibility | Valuation IP, league IDs, 8,015 data files world-readable |
| **Default branch** | `main` — CONFIRMED | `main` | No | Settings → General → Default branch | Correct already |
| **Branch protection** | **None** — CONFIRMED (`"protected": false`) | Ruleset with force-push block + delete block + `Validate PR` | **YES** (OA-02) | Settings → Rules → Rulesets → New branch ruleset | `main` push auto-deploys to production |
| **Required reviews** | None | **0 approvals**, PR required | Yes (part of OA-02) | same | Solo repo; >0 approvals would deadlock you |
| **Required status checks** | None | `Validate PR` only | Yes (part of OA-02) | same | E2E is currently red; requiring it would block all merges |
| **Merge methods** | UNVERIFIED | Allow **merge commits**; disable rebase | Optional | Settings → General → Pull Requests | The repo's history uses merge commits (`bbd7091 Merge pull request #624`) |
| **Auto-delete head branches** | UNVERIFIED — likely off, given 30 branches | **Enable** | Recommended | Settings → General → Pull Requests → ✅ Automatically delete head branches | Prevents the branch sprawl documented in OA-10 |
| **Actions permissions** | UNVERIFIED — inferred permissive (writes succeed) | Allow all actions | Verify (OA-06) | Settings → Actions → General → Actions permissions | `claude.yml` uses third-party `anthropics/claude-code-action@v1` |
| **Workflow permissions** | UNVERIFIED — inferred read/write | **Read and write** | Verify (OA-06) | Settings → Actions → General → Workflow permissions | 6 workflows need `contents: write` / `issues: write` |
| **Actions → create/approve PRs** | UNVERIFIED | **Enabled** | Verify (OA-06) | same page | `claude.yml` requests `pull-requests: write` |
| **Fork PR permissions** | UNVERIFIED | Leave default | No | Settings → Actions → General → Fork pull request workflows | `forks_count: 0`; moot once private |
| **Repository secrets** | Inferred present: `DLF_USERNAME`, `DLF_PASSWORD`, `DRAFTSHARKS_*`, `FOOTBALLGUYS_*`, `INTEL_REFRESH_TOKEN`, `CLAUDE_CODE_OAUTH_TOKEN`. Inferred absent: `ANTHROPIC_API_KEY`, `IDPSHOW_SESSION_JSON` | Add the two absent ones if you want those features | Optional (OA-08, OA-11) | Settings → Secrets and variables → Actions | See §6 for the full matrix |
| **Repository variables** | Inferred present: `PROD_PUBLIC_URL` (intel-refresh refuses to run without it and it succeeds) | Confirm the 13 `PROD_*` vars | Verify | Settings → Secrets and variables → Actions → **Variables** tab | `deploy.yml` defaults them all, so absence is non-fatal |
| **Environment secrets** | `production` environment exists — CONFIRMED (deploys run). Contents UNVERIFIED | Confirm 4–5 `DEPLOY_*` names | Verify (OA-07) | Settings → Environments → production | The deploy preflight hard-fails on any empty one |
| **Deployment environments** | `production` — CONFIRMED | Keep | No | same | — |
| **Required reviewers on `production`** | UNVERIFIED | Your call | Optional (D-4) | Settings → Environments → production → Deployment protection rules | Adds a human gate before every production deploy |
| **GitHub Apps** | UNVERIFIED | Audit installed apps | Verify | Settings → Integrations → GitHub Apps | Especially relevant while public |
| **Webhooks** | UNVERIFIED | Confirm none unexpected | Verify | Settings → Webhooks | `LOCKSTEP_SETUP.md` describes a Jenkins integration — see §11 |
| **Deploy keys** | UNVERIFIED | Confirm none unexpected | Verify | Settings → Deploy keys | `LOCKSTEP_SETUP.md:19` recommends one; deploy uses `DEPLOY_SSH_PRIVATE_KEY` instead |
| **Pages** | **Disabled** — CONFIRMED (`"has_pages": false`) | Keep disabled | No | Settings → Pages | — |
| **Dependabot alerts** | **Not enabled** — CONFIRMED (no `dependabot.yml`) | **Enable** | **YES** (OA-05) | Settings → Advanced Security → Dependabot alerts | 76 unpinned dependencies, zero CVE alerting |
| **Dependabot security updates** | Not enabled | **Enable** | **YES** (OA-05) | same | Auto-PRs the fix |
| **Code scanning** | **Not configured** — CONFIRMED (no CodeQL workflow) | **Enable default setup** | **YES** (OA-05) | Settings → Advanced Security → Code scanning → Set up → Default | Python + JS both detected |
| **Secret scanning** | UNVERIFIED (public repos get it free) | **Enable + push protection** | **YES** (OA-05) | Settings → Advanced Security → Secret scanning | May require GHAS once private |
| **Private vulnerability reporting** | Not enabled | Enable while public | Recommended (OA-05) | Settings → Advanced Security | No `SECURITY.md` exists |
| **Open pull requests** | 3 open — CONFIRMED | Merge #627, #626, then #625 | **YES** (OA-10, OA-03) | Pull requests | #625 carries the production security fix |
| **Stale branches** | 30 total; 1 confirmed merged; 18 `archive/*`; 5 pre-rewrite orphans — CONFIRMED | Delete 1 now; decide on the rest | Partial (OA-10, D-5) | Branches | Do **not** bulk-delete — the orphans hold the only pre-rewrite history |
| **Releases** | None found | Not needed | No | Releases | Deploy is commit-based, not tag-based |
| **Tags** | None found | Not needed | No | Tags | `deploy.yml` accepts a `deploy_ref` for rollback instead |
| **Wiki** | Enabled — CONFIRMED (`"has_wiki": true`) | Disable (unused) | Optional | Settings → General → Features → Wikis | Reduces public surface |
| **Projects** | Enabled — CONFIRMED (`"has_projects": true`) | Leave | No | Settings → General → Features | — |
| **Issues** | Enabled, 3 open — CONFIRMED | Leave | No | Issues | #613, #588, #555 |

---

## 6. Environment Variables and Secrets Matrix

**No live secret value is reproduced anywhere in this document.** I found **no credential committed to the repository** — `git grep` for assignment-shaped high-entropy strings across tracked non-lockfile, non-data paths returned zero hits, and `.gitignore:33-38` correctly excludes `*_session.json`, `*.env`, `.env*` (with `!.env.example`) and `.secrets/`.

Legend for **Current status**: **Confirmed configured** · **Confirmed missing** · **Possibly missing** · **Obsolete** · **Unknown**

### Backend / server

| Variable | Purpose | Referenced in | Local | Preview | Prod | Actions | Secret? | Source of value | Current status | Owner action |
|---|---|---|---|---|---|---|---|---|---|---|
| `JASON_LOGIN_PASSWORD` | Login gate; **server refuses to start without it** | `server.py` (import-time guard); `.env.example:52-53` | ✅ | n/a | ✅ | via `ALLOW_DEFAULT_LOGIN_DEV=1` | **Secret** | You choose | **Confirmed configured** (site serves) | None |
| `JASON_LOGIN_USERNAME` | Login gate username | `server.py`; `.env.example:50` | ✅ | n/a | ✅ | ❌ | Non-secret | You choose | **Confirmed configured** | None |
| `PRIVATE_APP_ALLOWED_USERNAMES` | Gates `/api/admin/*`; **separate default** from the above | `server.py`; `.env.example:51` | ○ | n/a | ✅ | ❌ | Non-secret | Must match your username | **Unknown** | Verify — a mismatch silently locks you out of `/admin` |
| `JASON_AUTH_COOKIE_SECURE` | `Secure` flag on the session cookie | `server.py:182,9496,9544` | ○ `false` for HTTP dev | n/a | ✅ `true` | ❌ | Non-secret | `true` | **Confirmed configured** (HTTPS works) | None |
| `SLEEPER_LEAGUE_ID` | Back-compat single-league fallback | `Dynasty Scraper.py`, `server.py`; `.env.example:23` | ○ | n/a | ○ | ❌ | Non-secret | Sleeper URL | **Obsolete-ish** — `config/leagues/registry.json` is authoritative when present, and it **is** present | None |
| `BASELINE_LEAGUE_ID` | Documented as "baseline comparison league" | `.env.example:24`, `README.md:125`, `CLAUDE.md:830`, `HANDOFF.md:104` | — | — | — | — | Non-secret | — | **Obsolete** — CONFIRMED: **zero** code references; every hit is documentation | None — I remove the doc references (AC-05) |
| `FRONTEND_URL` | Backend→Next proxy target | `server.py`; `.env.example:4` | ○ | n/a | ○ | ❌ | Non-secret | `http://127.0.0.1:3000` | **Confirmed configured** (default works) | None |
| `LOG_FORMAT` | `text` or `json` | `server.py`; `.env.example:66` | ○ | n/a | ○ | ❌ | Non-secret | `text` | Default fine | None |
| `DISK_SPACE_MIN_MB` | Skip data writes below this | `server.py`; `.env.example:63` | ○ | n/a | ○ | ❌ | Non-secret | `500` | Default fine | None |
| `SESSION_TTL_DAYS` | Session lifetime | `server.py` | ○ | n/a | ○ | ❌ | Non-secret | code default | Default fine | None |
| `RATE_LIMIT_PER_MINUTE` / `_PER_HOUR` / `_BYPASS_IPS` | Public API rate limiting (60/min, 1000/h) | `src/api/rate_limit.py`; `e2e.yml:143` | ○ | n/a | ○ | ✅ `127.0.0.1` on the runner | Non-secret | code defaults | Default fine | None |
| `MAX_REQUEST_BYTES` | Request body cap | `server.py` | ○ | n/a | ○ | ❌ | Non-secret | code default | Default fine | None |
| `SLEEPER_TRADE_HISTORY_DAYS` | Rolling trade window | `Dynasty Scraper.py:1294`; `.env.example:44` | ○ | n/a | ○ | ❌ | Non-secret | `365` | Default fine | None |
| `LEAGUE_REGISTRY_PATH` | Point at a non-default registry | `src/api/league_registry.py`; `.env.example:18` | ○ | n/a | ○ | ❌ | Non-secret | — | Not needed | None |
| `SCRAPE_RUN_TIMEOUT_SECONDS` / `SCRAPE_STALL_SECONDS` / `SCRAPE_REAP_ORPHAN_BROWSERS` | Scrape watchdogs | `server.py` | ○ | n/a | ○ | ❌ | Non-secret | code defaults | Default fine | None |
| `SIMULATE_MC_MAX_SIMS` / `_TIMEOUT_SECONDS` | Monte-Carlo caps | `server.py` | ○ | n/a | ○ | ❌ | Non-secret | code defaults | Default fine | None |
| `PUBLIC_LEAGUE_CACHE_TTL` and 4 siblings | Public-league cache tuning | `src/public_league/*` | ○ | n/a | ○ | ❌ | Non-secret | code defaults | Default fine (live metrics show `cache_hit: 9`, `rebuild_failures: 0`) | None |
| `PUBLIC_MAX_SEASONS` | Public history depth | `src/public_league/*` | ○ | n/a | ○ | ❌ | Non-secret | code default | Default fine | None |
| `SERVICE_NAME` / `SLEEPER_LEAGUE_NAME` | Display/labelling | `server.py` | ○ | n/a | ○ | ❌ | Non-secret | — | Default fine | None |
| `IDP_CALIBRATION_ALLOW_NETWORK` | Documented network toggle for the stats adapter | `.env.example:126` **only** | — | — | — | — | Non-secret | — | **Obsolete** — CONFIRMED: zero code references; `src/idp_calibration/stats_adapter.py` is not referenced by this name | None — I remove it (AC-05) |
| `ENABLE_NEXT_FRONTEND_PROXY` | "legacy/deprecated" per README | `README.md:122` **only** | — | — | — | — | Non-secret | — | **Obsolete** — CONFIRMED: zero code references | None — I remove it (AC-05) |
| `CANONICAL_DATA_MODE` | Retired offline pipeline | nothing | — | — | — | — | — | — | **Obsolete** — CONFIRMED: zero references anywhere; `README.md:194-201` already documents the retirement | Already handled |
| `FRONTEND_RUNTIME` | — | hardcoded `"next"` in `server.py`; pinned by `tests/api/test_frontend_migration.py:19` | — | — | — | — | — | — | **Obsolete as a variable** | None |

### Scraper credentials

| Variable | Purpose | Referenced in | Local | Prod | Actions | Secret? | Source | Status | Owner action |
|---|---|---|---|---|---|---|---|---|---|
| `DLF_USERNAME` / `DLF_PASSWORD` | 4 DLF boards (524 player-rows) | `scripts/fetch_dlf.py`; `scheduled-refresh.yml:130-131`; `.env.example:36-38` | ○ | ✅ | ✅ | **Secret** | dynastyleaguefootball.com | **Confirmed configured** — the `dlf_last_success` freshness guard (`scheduled-refresh.yml:601-612`) passes and all 4 boards fetched 1.95h ago | **OA-13** — confirm subscription/password before the 6.5-day cookie window closes |
| `DRAFTSHARKS_EMAIL` / `_PASSWORD` | `draftSharks` 388 + `draftSharksIdp` 259 | `scripts/fetch_draftsharks.py`; `scheduled-refresh.yml:128-129` | ○ | ✅ | ✅ | **Secret** | draftsharks.com | **Confirmed configured** — both sources fetched 2.85h ago | None |
| `FOOTBALLGUYS_EMAIL` / `_PASSWORD` | FootballGuys refresh | `scripts/fetch_footballguys.py`; `scheduled-refresh.yml:126-127` | ○ | ○ | ✅ | **Secret** | footballguys.com | **Unknown** — no `footballguys*` key appears in live `served_source_coverage`. Either the source was retired or it is failing silently | Verify — I will trace whether the fetcher is still wired (AC-09) |
| `IDPSHOW_SESSION_JSON` | CI fallback for IDP Show (278 players) | `scheduled-refresh.yml:136,393` | ❌ | n/a (uses a file) | ○ | **Secret** | Browser cookies, or the VPS jar | **Confirmed missing** per `UNIMPLEMENTED_BACKLOG.md` §10 | **OA-08** |
| `BDVM_IDPSHOW_SESSION` | IDP Show *projections* jar path | `src/bdvm/idpshow_projections.py` | ○ | ○ | ❌ | Non-secret (a path) | `/var/lib/idpshow-fetch/idpshow_session.json` | **Unknown** | Verify via OA-08's SSH step |

### CI / deploy

| Variable | Purpose | Referenced in | Actions | Secret? | Source | Status | Owner action |
|---|---|---|---|---|---|---|---|
| `DEPLOY_HOST` | Production hostname | `deploy.yml:217,240` | ✅ | **Secret** | Your VPS | **Confirmed configured** — `deploy.yml:240-243` hard-fails on empty, and 6 deploys succeeded | None |
| `DEPLOY_USER` | SSH user (`dynasty`) | `deploy.yml:218,241` | ✅ | **Secret** | VPS | **Confirmed configured** (same guard) | None |
| `DEPLOY_SSH_PRIVATE_KEY` | Deploy key | `deploy.yml:220,242` | ✅ | **Secret** | Generated keypair | **Confirmed configured** — `deploy.yml:256-258` validates the PEM header | None |
| `DEPLOY_KNOWN_HOSTS` | Host-key pinning | `deploy.yml:221,243` | ✅ | **Secret** | `ssh-keyscan -H -p <port> <host>` | **Confirmed configured** — `deploy.yml:260-262` validates the entry, `:302-311` re-checks the host | None |
| `DEPLOY_PORT` | SSH port | `deploy.yml:219,246` | ○ | **Secret** | VPS | **Possibly missing** — defaults to 22, and `deploy.yml:264` logs a notice when unset | None (harmless) |
| `INTEL_REFRESH_TOKEN` | Bearer for `/api/intel/refresh` | `intel-refresh.yml:65,143`; `.env.example:105-118` | ✅ | **Secret** | `openssl rand -hex 32`; **must match the VPS `.env`** | **Confirmed configured** — the workflow fails at `:69` when unset, and runs on 2026-07-27/28 succeeded. **Rotation state unverified** | **OA-09** |
| `SIGNAL_ALERT_CRON_TOKEN` | Server-side fallback for the above; gates 2 systemd timers | `server.py`; `deploy/systemd/README.md` | ❌ | **Secret** | Generated | **Unknown** — the timers install only when it is present in `.env` | Verify via OA-09's SSH step |
| `CLAUDE_CODE_OAUTH_TOKEN` | `@claude` PR/issue automation | `claude.yml:36` | ✅ | **Secret** | Claude Code | **Unknown** — no `claude.yml` run in the sampled window (nobody has typed `@claude`) | Verify by commenting `@claude hello` on any issue |
| `ANTHROPIC_API_KEY` | Weekly narratives | `weekly-narratives.yml:78`; `scripts/generate_weekly_narratives.py:30`; `src/api/chat.py:222` (**dead module**) | ○ | **Secret** | console.anthropic.com | **Confirmed missing** — `weekly-narratives.yml:80-82` records "8 straight failures" | **OA-11** (optional) |
| `GITHUB_TOKEN` | Auto-provided | 6 workflows | ✅ | auto | GitHub | **Confirmed configured** | None — but see **OA-06** for the permission level |
| `PROD_PUBLIC_URL` | Production origin for cron callers | 16 references across workflows; `intel-refresh.yml:50-56` **refuses to run without it** | ✅ (Variable) | Non-secret | `https://chaseupside.com` | **Confirmed configured** — intel-refresh succeeded, and it cannot when this is empty | None |
| `PROD_APP_DIR`, `PROD_VENV_DIR`, `PROD_SERVICE_NAME`, `PROD_APP_PORT`, `PROD_APP_HOST`, `PROD_APP_USER`, `PROD_APP_NAME`, `PROD_DEPLOY_STATE_DIR`, `PROD_LAST_SUCCESSFUL_DEPLOY_COMMIT_FILE`, `PROD_DEPLOY_BRANCH`, `PROD_AUTO_ROLLBACK`, `PROD_STRICT_LOCAL_HEALTH` | Deploy tuning | `deploy.yml` (each with a `||` default) | ○ | Non-secret | — | **Possibly missing, harmless** — every one has an inline default | None |

### Frontend

| Variable | Purpose | Referenced in | Local | Prod | Secret? | Status | Owner action |
|---|---|---|---|---|---|---|---|
| `BACKEND_API_URL` | Next→FastAPI bridge (37 call sites) | `frontend/app/api/**/route.js` | ○ | ○ | Non-secret | Defaults to `http://127.0.0.1:8000` everywhere | None |
| `NEXT_PUBLIC_SITE_URL` / `PUBLIC_SITE_URL` | Canonical origin for `sitemap.js` + `robots.js` | `frontend/app/sitemap.js:21-22`, `robots.js:7-8` | ○ | **should be set** | Non-secret | **Possibly missing** — both files fall back, and a wrong canonical origin publishes bad sitemap/robots URLs | Verify on the VPS; set to `https://chaseupside.com` |
| `NEXT_DIST_DIR` | Build output dir | `frontend/next.config` | ○ | ○ | Non-secret | Default fine | None |

### Optional features (all currently inert)

| Variable | Purpose | Referenced in | Status | Owner action |
|---|---|---|---|---|
| `VAPID_PUBLIC_KEY` / `VAPID_PRIVATE_KEY` / `VAPID_CONTACT` | Web Push / PWA notifications — **all three required** | `src/api/push_delivery.py:34-35,53-54`; `.env.example:86-99` | **Unknown** — likely unset; push is silently inert without them | Optional. Generation command is in `.env.example:88-96`. `VAPID_CONTACT` must be a real `mailto:` — providers send delivery failures there |
| `ALERT_ENABLED` / `ALERT_TO` / `ALERT_FROM` / `ALERT_PASSWORD` | Email alerting via Gmail app password | `Dynasty Scraper.py:297,7452`; `server.py:126`; `.env.example:79-83` | **Unknown** — `server.py:126` defaults `ALERT_ENABLED` to **False** while `Dynasty Scraper.py:297` defaults it to **"true"**. That inconsistency is a real bug | Optional. **I will fix the default mismatch** (AC-08) |
| `GMAIL_APP_PASSWORD` | Alternative name for the above | `Dynasty Scraper.py` | **Inconsistently named** — two names for one credential | I will consolidate (AC-08) |
| `UPTIME_CHECK_ENABLED` / `_URL` / `_INTERVAL_SEC` / `_TIMEOUT_SEC` / `UPTIME_ALERT_FAIL_THRESHOLD` | In-process uptime watchdog | `server.py:142-144,673,2455`; `.env.example:71-76` | **Confirmed configured** — live `/api/health` returns `"uptime_watchdog": {"enabled": true, "target_url": "http://127.0.0.1:8000/api/health"}` | None. **But note:** `.env.example:72` suggests `https://chaseupside.com/api/health` while production is actually probing **itself on localhost** — that cannot detect an nginx or TLS outage. Worth changing; I flag it as Decision **D-7** |
| `RISKIT_FEATURE_BDVM_ENGINE` and every `RISKIT_FEATURE_*` | Feature flag overrides | `src/api/feature_flags.py`; `.env.example:143-166` | **Confirmed configured** via in-code defaults — live `/api/status` shows 14 flags, 6 enabled (`nfl_data_ingest`, `realized_points_api`, `monte_carlo_trade`, `te_basis_conversion`, `idp_scoring_fit`, `reception_scoring_fit`, `bdvm_engine` — all `gateStatus: LIVE`) | None |
| `JENKINS_TRIGGER_URL` / `JENKINS_USER` / `JENKINS_API_TOKEN` | Post-push Jenkins trigger | `scripts/trigger_jenkins.py`; `README.md:216-222`; `LOCKSTEP_SETUP.md` | **Obsolete** — see §11 | See Decision **D-8** |
| `E2E_TEST_MODE` / `E2E_TEST_SECRET` / `E2E_TEST_USERNAME` / `E2E_TEST_SLEEPER_USER_ID` | CI-only session minting | `server.py:10583-10597`; `e2e.yml:112,141-142` | **Correct** — CI-only, per-run random, fail-closed | **OA-17** — confirm they are absent from production |

**Naming inconsistencies found:** `ALERT_PASSWORD` vs `GMAIL_APP_PASSWORD` (same credential, two names) · `NEXT_PUBLIC_SITE_URL` vs `PUBLIC_SITE_URL` (both read, in that precedence order — intentional, but undocumented) · `INTEL_REFRESH_TOKEN` vs `SIGNAL_ALERT_CRON_TOKEN` (documented fallback chain, correct).

---

## 7. External Services Checklist

| Service | Used for | Evidence | Account? | Billing? | Env vars | Callback/webhook | Domain | Scopes | Verifiable? | You must | I can then |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **GitHub** | Source, CI/CD, issue tracking, deploy trigger | 14 workflows; `deploy.yml` | Yes — have it | **Yes if private** — 2,000 free Actions min/mo, and this repo's schedules will exceed that | `GITHUB_TOKEN` (auto) | — | — | repo admin | Yes | OA-01, OA-02, OA-05, OA-06, OA-07 | Author `dependabot.yml`, `SECURITY.md`; tune schedules if minutes bite |
| **Contabo (or current VPS)** | Production host | `deploy/PRODUCTION_BOOTSTRAP.md`; `CLAUDE.md` ("currently Contabo; the deploy target is the `DEPLOY_HOST` secret") | Yes — have it | Yes — ongoing | `DEPLOY_*` | — | resolves `chaseupside.com` | SSH + command-scoped sudo | Partially (health endpoint) | OA-12, OA-15, OA-17 | Nothing directly — no SSH access |
| **Let's Encrypt** | TLS for `chaseupside.com` | `PRODUCTION_BOOTSTRAP.md:73-84`; live `ssl_verify=0` | Automated | Free | — | HTTP-01 at `/.well-known/acme-challenge/` | `chaseupside.com` | — | Yes | **OA-12** | Nothing |
| **Domain registrar (chaseupside.com)** | DNS | `README.md:3`; live site | Yes — have it | Yes — annual | — | — | — | — | Indirectly | Confirm auto-renew is on and the card is valid | Nothing |
| **~~riskittogetthebrisket.org~~** | Former domain | `deploy/nginx/riskittogetthebrisket.org.conf:1-25` | **LAPSED — now resolves to a third party** | — | — | — | — | — | Yes (the file says so) | **Nothing — do not re-register or re-apply that config**; applying it fails `nginx -t` and aborts the reload | Nothing |
| **Sleeper API** | League, rosters, trades, transactions | `Dynasty Scraper.py`; `src/public_league/*`; `src/intel/*` | **No auth needed** — public, unauthenticated | Free | `SLEEPER_LEAGUE_ID` (fallback only) | — | — | none | Yes — live breaker `sleeper_api: closed` | Nothing | Nothing |
| **KeepTradeCut (KTC)** | Anchor market board | `Dynasty Scraper.py`; `_VALUE_BASED_SOURCES` | No account | Free | — | — | — | — | Yes | Nothing | **Note a degradation:** live `source_health` shows `KTC_TradeDB` and `KTC_WaiverDB` both **partial** — *"skipped — no playerID→name mapping available"*, `valueCount: 0`. Affects the crowd-FAAB path. I will investigate (AC-10) |
| **IDPTradeCalc** | IDP + picks market board (769 players) | `_VALUE_BASED_SOURCES`; live coverage | No account | Free | — | — | — | — | Yes | Nothing | Nothing |
| **DynastyLeagueFootball (DLF)** | 4 boards, 524 rows | `scripts/fetch_dlf.py` | **Yes — paid subscription** | **Yes** | `DLF_USERNAME`, `DLF_PASSWORD` | — | — | subscriber | Yes | **OA-13** | Nothing |
| **DraftSharks** | 647 rows across 2 boards | `scripts/fetch_draftsharks.py` | **Yes — paid** | **Yes** | `DRAFTSHARKS_EMAIL`, `DRAFTSHARKS_PASSWORD` | — | — | subscriber | Yes | Nothing | Nothing |
| **FootballGuys** | Fetcher exists | `scripts/fetch_footballguys.py`; `scheduled-refresh.yml:126-127` | Probably paid | Probably | `FOOTBALLGUYS_EMAIL`, `FOOTBALLGUYS_PASSWORD` | — | — | subscriber | **No — absent from live coverage** | Tell me if you still pay for this | Trace whether it is wired or dead (AC-09), and remove the secret refs if dead |
| **The IDP Show** | 278 IDP rows + BDVM projections | `scripts/fetch_idpshow.py`, `fetch_idpshow_projections.py` | **Yes — paid (Substack)** | **Yes** | `IDPSHOW_SESSION_JSON` (CI), session jar (prod) | — | — | subscriber cookies | Yes — fetched 1.87h ago | **OA-08** | Nothing |
| **DynastyNerds** | 293 rows | live coverage; `scripts/fetch_dynasty_nerds.py` | **Yes — paid** | **Yes** | session-file based | — | — | subscriber | Yes | Nothing | Nothing |
| **FantasyPros / FantasyCalc / DynastyDaddy / OTCFFB / PFK / Flock / Yahoo(Boone) / FantasyNavigator / Fitzmaurice** | 9 more sources, ~3,400 rows | `scripts/fetch_*.py`; live coverage | Mostly free/public | No | — | — | — | — | Yes — all fetched <3h ago | Nothing | Nothing |
| **nflverse** | Historical stats, realized points, BDVM baseline | `src/bdvm/actuals.py`; flag `nfl_data_ingest: LIVE` | No account | Free | — | — | — | — | Yes | Nothing | **Note:** live breaker `nflverse_direct` is `closed` (healthy) but `lastError: HTTP Error 404: Not Found` — a fallback is absorbing it. I will check (AC-11) |
| **Mike Clay / ESPN guide** | BDVM offense projections | `scripts/fetch_clay_projections.py` | No account (public CDN PDF) | Free | — | — | — | — | Partially | Nothing | Nothing |
| **Anthropic API** | Weekly league narratives only | `weekly-narratives.yml:78`; `scripts/generate_weekly_narratives.py:30` | **Yes, if you want the feature** | **Yes — usage-based** | `ANTHROPIC_API_KEY` | — | — | API key | Yes | **OA-11** (optional) | Nothing |
| **Claude Code (GitHub Action)** | `@claude` on issues/PRs | `claude.yml:36` | Yes | Subscription | `CLAUDE_CODE_OAUTH_TOKEN` | GitHub events | — | — | Untested | Comment `@claude hello` on an issue to test | Nothing |
| **Grafana** | Optional public-league dashboard | `deploy/grafana/README.md`; `public-league-dashboard.json` | Only if you want it | Free tier available | — | polls `https://chaseupside.com/api/public/league/metrics` | — | Infinity datasource plugin | No | **Optional** — Grafana → Dashboards → Import → upload the JSON → pick an Infinity-plugin datasource | Nothing |
| **Gmail SMTP** | Email alerts | `.env.example:79-83`; `Dynasty Scraper.py:7452` | Yes, if you want alerts | Free | `ALERT_*` / `GMAIL_APP_PASSWORD` | — | — | Gmail **app password** (not your account password) | No | **Optional** | Fix the `ALERT_ENABLED` default mismatch (AC-08) |
| **Web Push (FCM/APNs via VAPID)** | PWA notifications | `src/api/push_delivery.py` | No account — VAPID is self-signed | Free | `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_CONTACT` | — | — | — | No | **Optional** — generate with `.env.example:88-96` | Nothing |
| **Jenkins** | Legacy build lockstep | `Jenkinsfile`, `LOCKSTEP_SETUP.md`, `scripts/trigger_jenkins.py`, `sync.bat` | Unknown — likely dead | — | `JENKINS_*` | possibly a webhook | — | — | No | **Tell me if any Jenkins instance still exists** | Remove the whole path if dead (AC-07) |
| **PlayForKeeps** | Prospective Sharp Tracker source | PR #626 | **Not integrated** | — | — | — | — | — | — | **Nothing — and do not enable it.** PR #626 states their `/terms` is a client-rendered JS shell whose clauses could not be read, so permission is *not* established. No scraper ships | Nothing |

---

## 8. Tasks Claude Can Complete Autonomously

Each of these is mine because it is a repository change requiring no login, no payment, no dashboard, and no irreversible decision. **None of them should be on your list**, and I have not put a single "run this command for me" item there where fixing the repository properly was the right answer instead.

| # | Task | Why it is not yours |
|---|---|---|
| **AC-01** | Rebase PR #625 onto the post-#626/#627 `main` and resolve its 4 conflicts (2 are generated `data/` state, 2 are real: `frontend/app/draft/page.jsx`, `frontend/app/page.jsx`) | Conflict resolution is code work. Asking you to hand-merge two JSX files would be handing you my job |
| **AC-02** | Investigate why PR #625 has **zero** check runs and get `Validate PR` to run on it | CI plumbing |
| **AC-03** | Fix the 3 genuinely-failing production E2E specs (`?tab=` deep link, `?owner=` franchise deep link, archives filter), then the CI-only data-shape failures separately | Application bugs. **After** #625 deploys — see D-6 |
| **AC-04** | Author `.github/dependabot.yml` (pip + npm ×2 + github-actions ecosystems) and `SECURITY.md` | Config files. You only flip the toggles (OA-05) |
| **AC-05** | Remove the 3 confirmed-obsolete env vars from docs: `BASELINE_LEAGUE_ID` (`README.md:125`, `CLAUDE.md:830`, `HANDOFF.md:104`, `.env.example:24`), `IDP_CALIBRATION_ALLOW_NETWORK` (`.env.example:126`), `ENABLE_NEXT_FRONTEND_PROXY` (`README.md:122`) | Documentation correctness. Each verified as zero-reference by grep |
| **AC-06** | Rewrite `HANDOFF.md`, which is materially false. `HANDOFF.md:352` claims *"No CI/CD configured — tests run manually. Deployment is manual SSH + restart."* against 14 workflows and a fully automated deploy. `:360` says the process is "assumed". `:324` describes adapters that `CLAUDE.md` already documents as absent from the tree | A stale doc that says "no CI" will send the next person down a wrong path |
| **AC-07** | Retire the Jenkins path — `Jenkinsfile`, `LOCKSTEP_SETUP.md`, `scripts/trigger_jenkins.py`, the `README.md:206-231` section, and the trigger call in `sync.bat` | Dead-code removal, pending your D-8 answer |
| **AC-08** | Fix the `ALERT_ENABLED` default mismatch (`Dynasty Scraper.py:297` defaults `"true"`, `server.py:126` defaults `False`) and consolidate `ALERT_PASSWORD` / `GMAIL_APP_PASSWORD` onto one name | A real inconsistency bug |
| **AC-09** | Determine whether FootballGuys is still wired — it has two repo secrets but produces no key in live `served_source_coverage` | Code tracing |
| **AC-10** | Investigate `KTC_TradeDB` / `KTC_WaiverDB` returning `partial` with *"no playerID→name mapping available"*, `valueCount: 0` | Live degradation in the crowd-FAAB path |
| **AC-11** | Investigate the `nflverse_direct` circuit breaker's `HTTP Error 404: Not Found` — the breaker is `closed` so a fallback is absorbing it silently | Silent degradation |
| **AC-12** | Add `.nvmrc` (`20`) and `.python-version` (`3.12`), and an `engines` field in `frontend/package.json` | Nothing pins runtime versions locally today; CI pins both. This closes a real works-on-my-machine gap |
| **AC-13** | Address the `actions/upload-artifact@v4` Node 20 deprecation warning appearing in every run | Workflow maintenance |
| **AC-14** | Produce a verified per-branch disposition list for all 30 branches, with evidence for each | So your D-5 decision is informed rather than a guess. Deleting branches on a hunch is exactly what I should not ask you to do |

---

## 9. Decisions Required From Me

| # | Decision | Why it matters | Options | My recommendation | Default if you do not care |
|---|---|---|---|---|---|
| **D-1** | Repository public or private? | Your valuation methodology, league IDs, owner IDs and 8,015 data files are world-readable. Counterweight: private repos get 2,000 free Actions minutes/month, and your schedules (data refresh ~every 4h, warmups, health checks, nightly E2E) will very likely exceed that and start billing | (a) Private, accept possible Actions cost · (b) Private + I cut the schedule frequency to fit the free tier · (c) Stay public | **(b)** — the IP exposure is the larger risk, and I can reduce schedule frequency without losing the pipeline. Data refresh every 4h instead of every 2h is invisible to a dynasty board | (b) |
| **D-2** | Rotate `INTEL_REFRESH_TOKEN`? | A previous session flagged rotation and nobody confirmed it. The repo has been public since 2026-03-09 | (a) Rotate now · (b) Verify only · (c) Skip | **(a)** — it is a 5-minute job and the token grants a production endpoint | (a) |
| **D-3** | Pay for `ANTHROPIC_API_KEY`? | Weekly league narratives is the only live consumer (`src/api/chat.py` is dead code). Usage-based cost, small at this volume | (a) Add the key · (b) Leave it skipping | **(a)** if you actually want weekly narratives; **(b)** otherwise. The workflow already skips cleanly, so (b) costs nothing | (b) |
| **D-4** | Require a human reviewer on the `production` environment? | Today, merging any PR deploys to your live site with no gate | (a) Add required reviewer · (b) Leave automatic | **(a)** — one click per deploy. You just watched an unreviewed path put an anonymous data leak in front of the internet | (b) — `deploy.yml` already has fast-forward guards and auto-rollback |
| **D-5** | What happens to the 29 non-`main` branches? | 18 `archive/*` + 5 pre-rewrite orphans (3,761 commits each, zero overlap with `main`'s 205) + 3 active PR branches + `claude/tier3-snap-share` (1 genuine unmerged commit) | (a) Delete `archive/*` and the orphans · (b) Keep everything · (c) Let me produce the evidence list first (AC-14), then you decide | **(c)** — the orphans hold the only surviving copy of the pre-rewrite history. Deleting them is irreversible once GitHub GCs them | (c) |
| **D-6** | Fix the E2E specs before or after merging #625? | #625 restructures `/league` navigation and moves `/league/phases` → `/phases`, so it changes those specs' expected behaviour either way | (a) Merge #625 first, then fix specs against the new tree · (b) Fix specs first | **(a)** — fixing them first means fixing the wrong tree twice | (a) |
| **D-7** | Point the uptime watchdog at the public URL instead of localhost? | Live `/api/health` shows `target_url: http://127.0.0.1:8000/api/health` — the server probing itself. That cannot detect an nginx failure, a TLS expiry, or a DNS outage. `.env.example:72` suggests `https://chaseupside.com/api/health` | (a) Repoint to the public URL · (b) Leave as-is · (c) Both, via the separate `riskit-uptime.timer` in `deploy/monitoring/` | **(c)** — keep the in-process one for liveness, and confirm the external `riskit-uptime` timer is installed and pointed at the public URL. That is the layer that catches nginx/TLS | (c) |
| **D-8** | Is any Jenkins instance still running? | `Jenkinsfile`, `LOCKSTEP_SETUP.md`, `scripts/trigger_jenkins.py`, a `README.md` section and a `sync.bat` hook all exist for it. GitHub Actions clearly does the real work | (a) Dead — I remove it all · (b) Still used — I leave it | **(a)** unless you say otherwise. `docs/ops/current-automation-state.md` should confirm; I will read it before touching anything | (a) |

---

## 10. End-to-End Verification Checklist

Run in this order after completing the checklist.

| # | Action | Expected outcome | Where to inspect failures |
|---|---|---|---|
| 1 | **Local install** — §4 Block 3 | `pip check` → `No broken requirements found.`; `check_env.py` exits 0 | Console. Almost always a Python minor-version gap — CI pins **3.12** |
| 2 | **Local tests** — §4 Block 4 | pytest ~5,000–5,400 passed, 0 failed; vitest ~1,390–1,460 passed | pytest `--tb=short` output. One known-open exception: `test_anchor_curve_extrapolation_monotone` |
| 3 | **Format/lint gates** — §4 Block 5 | `ruff format --check` clean (hard gate); `ruff check` shows a known backlog (report-only) | Console |
| 4 | **Frontend build** — §4 Block 6 | `next build` succeeds, `check-bundle-sizes.mjs` passes | `frontend/.next/` build output |
| 5 | **Local startup** — §4 Block 7 | Backend `:8000` → `{"status":"ok"}`; frontend `:3000` → 200 | The two `start_stack.bat` windows |
| 6 | **Authentication** | Visit `http://localhost:3000` → redirected to `/login`; sign in with `JASON_LOGIN_USERNAME`/`PASSWORD` → dashboard | Backend console. `JASON_LOGIN_PASSWORD` unset = server will not start at all |
| 7 | **Database connectivity** | `/api/health` returns a `backup_health` block | SQLite files under `data/` are created on demand — there is no external DB |
| 8 | **Data ingestion** | Local `/api/status` → `served_source_coverage` lists ~21 sources; `source_health.sources` all `ageHours < 24` | `/api/status` → `source_failures` names the failing source and reason |
| 9 | **Major pages** | `/rankings`, `/trade`, `/draft`, `/bdvm`, `/waivers`, `/news`, `/settings`, `/league` all render without a client error | Browser DevTools console |
| 10 | **API routes** | `/api/data` (authed) 200 · `/api/leagues` 200 · `/api/bdvm/values` 200 with `status: "ok"` · `/api/trade/suggestions` POST 200 | Backend console |
| 11 | **Scheduled jobs — GitHub** | Actions → last 24h shows `Scheduled Data Refresh`, `Scheduled Health Check`, `Public League Warmup`, `Production E2E Smoke` all green | Per-run logs |
| 12 | **Scheduled jobs — VPS** | `systemctl list-timers 'dynasty-*' 'riskit-*'` shows a NEXT time for each | `journalctl -u <unit>` |
| 13 | **Preview deployment** | **N/A — this project has no preview environment.** `main` deploys straight to production | — |
| 14 | **Production deployment** | Actions → `Deploy Production` green; `deploy/verify-deploy.sh` runs as part of it | The run's SSH steps |
| 15 | **Domain + HTTPS** | `curl -o /dev/null -w "%{http_code} %{ssl_verify_result}" https://chaseupside.com/` → `200 0`; `http://chaseupside.com` → 301 to https | `sudo nginx -t`; `sudo journalctl -u nginx` |
| 16 | **Security boundary (the OA-03 proof)** | §4 Block 8: draft-capital leak check prints **nothing**; `/rankings` → **307/302**; `/api/data` → **401**; `/api/test/create-session` → **404** | If any differs, send me the exact output |
| 17 | **Monitoring** | `/api/health` → `uptime_watchdog.enabled: true`, `anyBreakerOpen: false`, `backup_health` present | See D-7 about what the watchdog can actually detect |
| 18 | **Error logs** | `sudo journalctl -u dynasty -n 200 --no-pager` — no repeating tracebacks | Also `/var/log/dynasty.log`, `/var/log/dynasty-frontend.log` (logrotate keeps 14 days) |
| 19 | **Mobile behaviour** | DevTools device toolbar at 390×844 and 430×932 (the viewports `README.md` names): nav renders, bottom tabs correct signed in **and** signed out | The E2E `mobile-chromium` project covers these |
| 20 | **Sleeper integration** | `/api/leagues` returns both leagues with stable keys and **no raw Sleeper IDs**; `/api/terminal` returns team aggregates; league switching re-fetches | `/api/status` → `leagues[]` shows `tradeCount` per league |
| 21 | **BDVM** | `/api/bdvm/values` → `status: "ok"`, ~726 priced / ~222 unpriced; `/bdvm` page renders; `/rankings` shows the "Fund gap" column | A 503 means the flag is off or no projection snapshot exists |
| 22 | **Backups** | `sudo systemctl start riskit-backup.service`, then `sudo tail /var/log/riskit-backup.log` | Should end `nightly backup complete: <ISO timestamp>` |
| 23 | **Restore test** | `sudo -u dynasty /home/dynasty/trade-calculator/deploy/backup_user_kv.sh --restore-test` | Non-zero exit + `ERROR` in the log on failure |

---

## 11. Obsolete or Unnecessary Instructions

Do **not** follow these. Each is superseded, and each is verified below.

| Instruction | Where it appears | Why it is obsolete |
|---|---|---|
| *"No CI/CD configured — tests run manually. Deployment is manual SSH + restart."* | `HANDOFF.md:352` | **Flatly false.** 14 workflows exist; `Deploy Production` has run 6 times in the last 12 hours. `HANDOFF.md:360` even says the process is "assumed". Rewrite pending (AC-06) |
| *"Process: uvicorn via systemd (assumed)"* | `HANDOFF.md:360` | Not assumed — `deploy/systemd/dynasty.service.template` is real and `deploy/systemd/README.md` documents the whole unit set |
| The whole first-time production bootstrap | `deploy/PRODUCTION_BOOTSTRAP.md`; `README.md` "Production Bootstrap" | **Already complete.** Sudoers policy, base packages, Playwright deps, nginx, TLS — all evidenced done by 6 green deploys and a healthy live site. This is a **disaster-recovery** runbook, not a to-do list |
| `python scripts/canonical_build.py` and the `CANONICAL_DATA_MODE` env var | Older docs | Retired. `README.md:194-201` already carries the correction; grep confirms zero references to `CANONICAL_DATA_MODE` anywhere in the tree |
| Applying `deploy/nginx/riskittogetthebrisket.org.conf` | The file itself | **Actively dangerous.** `:1-25` — the domain lapsed and now resolves to a third party; the `:443` block references certificate paths that no longer exist, so `nginx -t` fails and the reload aborts. It is also mutually exclusive with `chaseupside.com.conf` (duplicate `map`, cache zone and upstream declarations) |
| Setting `BASELINE_LEAGUE_ID` | `.env.example:24`, `README.md:125`, `CLAUDE.md:830`, `HANDOFF.md:104` | **Zero code references.** Documentation-only ghost. Removal is AC-05 |
| Setting `ENABLE_NEXT_FRONTEND_PROXY` | `README.md:122` (already marked "legacy/deprecated") | Zero code references |
| Setting `IDP_CALIBRATION_ALLOW_NETWORK` | `.env.example:126` | Zero code references |
| Setting `SLEEPER_LEAGUE_ID` as the primary league config | `README.md:124`, `.env.example:23` | Superseded by `config/leagues/registry.json`, which exists and is authoritative. `CLAUDE.md` is explicit: *"never read `os.getenv("SLEEPER_LEAGUE_ID")` in new code."* Kept only as a fresh-checkout fallback |
| Jenkins setup, `verify_lockstep.ps1`, the `JENKINS_*` env vars | `LOCKSTEP_SETUP.md`, `README.md:206-231`, `sync.bat` | Almost certainly dead — GitHub Actions does all the real work. Pending D-8 |
| `grant-ssh-access.yml` | `UNIMPLEMENTED_BACKLOG.md` §10 (*"Did it execute in its 33-minute window?"*) | **The workflow does not exist.** `ls .github/workflows/` shows 14 files and that is not among them. This item is closed |
| `npm run regression` as the primary local gate | `README.md:150-166` | Still works, but CI's real gates are `pr-validation.yml` (`Validate PR`) and `e2e.yml`. `README.md:141` also still references `Static/index.html`, which no longer exists — `FRONTEND_RUNTIME` is hardcoded to `next` with no Static fallback |
| *"Private repo"* | `README.md:3` | Wrong today — the repo is public. Either OA-01 makes the sentence true, or I correct the sentence |

---

## 12. Recommended Next Handoff to Claude

Paste this back to me once you have worked through the checklist:

> I've completed the Owner Action Checklist from `docs/OWNER_ACTION_AUDIT_2026-07-29.md`. Here are my results.
>
> **Decisions:** D-1 [public/private + Actions-minutes outcome] · D-2 [rotated / verified / skipped] · D-3 [ANTHROPIC_API_KEY yes/no] · D-4 [required reviewer yes/no] · D-5 [branch disposition] · D-6 [E2E sequencing] · D-7 [uptime watchdog] · D-8 [Jenkins dead/alive]
>
> **Stop-point outputs, pasted below:** OA-01 visibility result · OA-05 (was secret scanning available? how many Dependabot alerts?) · OA-07 (the `production` environment secret **names**) · OA-10 (confirmation #626 and #627 are merged) · OA-12 (`certbot certificates` expiry) · OA-14 (the pytest summary line) · OA-16 (`git diff --stat` from the Hill promotion — **not pushed**) · OA-17 (the `/api/test/create-session` HTTP code) · §4 Block 8 (all five production verification outputs)
>
> Now please:
> 1. **Review every command output above** and tell me plainly whether each task actually succeeded — do not treat a warning as a pass.
> 2. **Verify the manual actions independently** where you can: re-probe production for the OA-03 leak, re-check branch protection and repository visibility via the API, and confirm the secrets I added are visible to the workflows that need them.
> 3. **Finish all autonomous work AC-01 through AC-14**, in dependency order. Start with AC-01 (rebase and de-conflict PR #625) so I can merge it, then AC-03 (the E2E specs) once it has deployed.
> 4. **Retest the application end-to-end** — the full §10 checklist, backend and frontend suites, a production build, and a live production probe.
> 5. **Resolve every remaining failure**, or tell me precisely why one cannot be resolved and what it would take.
> 6. **Update the documentation** so it is true: `HANDOFF.md` (AC-06), the obsolete env vars (AC-05), `README.md`'s "Private repo" line, and anything in §11 my decisions have now settled.
> 7. **Produce a final production-readiness report** covering: what is confirmed working with evidence, what remains open with severity, what I still owe you, and an honest statement of anything you could not verify.
>
> If any step is blocked on something only I can do, stop there and tell me exactly what you need rather than working around it.

---

*Generated 2026-07-29. Live production probes taken at 10:24 UTC. Every "CONFIRMED" claim above is reproducible from the cited file path, GitHub API object, or curl command.*
