# Data exposure policy: ONE recommendation (STAB-7)

Date: 2026-11-19. Status: **recommendation for an OWNER decision; nothing in this change moves, untracks, deletes or
rewrites data, changes visibility, or alters what the refresh and deploy pipelines publish.** Builds on
`DATA_EXPOSURE_DECISION_BRIEF_2026-11-18.md` (options and facts) and `DATA_EXPOSURE_INVENTORY_2026-11-18.md`; this file
chooses. No legal conclusions. No identifier, credential or paid-source value appears here.

## 1. The recommendation

**Keep the code repository public. Stop publishing vendor data and Sleeper owner ids in it. Move exactly those
classes into a second, PRIVATE data repository that holds data only (no code, GitHub Actions disabled), and keep the
operational state the deploy keys on in the public repository.** Do not rewrite history.

In one table:

| Question | Decision |
|---|---|
| Repository visibility | **Public stays.** Private costs an estimated **$450 to $700 per month** in billed Actions minutes (brief Option B: 60,000 to 90,000 billed min per 30 days against a 2,000 to 3,000 allowance, at about $0.008 per Linux minute; the rate was **not re-verified today**, the plan tier is unreadable, and the sample week was an unusually busy campaign). Going private does not un-publish past clones, forks or history, and also loses free secret scanning. The money buys nothing the data split does not buy for free. |
| Where vendor raw CSVs and full-board exports live | **A private data repository** (suggested name `riskittogetthebrisket-private-data`). A private repository holding only data costs $0, runs no Actions, and keeps git as the transport, which is why delivery does not break. |
| What moves | Four classes, sized by `scripts/report_data_policy_migration.py` (section 3): paid-vendor boards, FantasyPros raw, export archives and snapshots that carry owner ids, and the full-board `exports/latest/`. |
| What stays public and tracked | `data/scrape_state/` and `data/sleeper_last_good.json` (the deploy dispatch and `source_health` key on these commits, CLAUDE.md W31-F001), everything else under `data/` and `exports/` not in the four classes, free/public-source boards whose terms are unverified (explicit, recorded risk acceptance, section 5), `config/`, code, docs, synthetic test fixtures. |
| How build and deploy get the private data | CI clones the private repository with a write-scoped deploy key held as one new Actions secret; the production box pulls it with a read-only deploy key into a path **outside** the public checkout. Tests and the PR gate use only synthetic fixtures (PR #2239) and never need it. |
| Sleeper owner/user ids | Full-fidelity archives go to the private repository. Anything that must stay public carries the existing per-league pseudonym (`publicOwnerKey`, public-surface census D1) instead of the raw id. Past exposure is accepted as low sensitivity (section 6). |
| Vendor licensing | Default **fail closed** for paid vendors until the owner supplies each vendor's terms or written permission. Only FantasyPros terms were located (they bar redistribution without written permission), so FantasyPros raw moves too. |
| Historical exposure | **No history rewrite.** It cannot recall forks or clones, and it is destructive (section 7). |

Why a private data repository and not "box-local only" (brief Option C): CI builds the board and the Hill refit reads
vendor observations, so both need the data off the box; a box-only store breaks them or forces a new artifact service.
A private repository is the smallest change that keeps every existing consumer able to get the bytes.

## 2. Why this and not the other options

| Option | Verdict |
|---|---|
| A, accept and document | Leaves paid-vendor values redistributable by anyone indefinitely and publishes owner ids in new archives every two hours. The guard stops new paths only. Rejected as an end state; it is the interim state until stage 5. |
| B, make the repository private | Costs an estimated $450 to $700 per month, risks CI throttling that blocks merges and refreshes, breaks public links and free secret scanning, and still stores vendor data that vendor terms may not allow in any hosting you do not control. Rejected on cost and on not fixing the cause. |
| C, box-local or artifact storage only | Highest engineering cost, breaks CI board builds and the Hill refit input, and loses the free off-site copy. Rejected. |
| D, hybrid (the brief's recommendation) | Adopted, with its transport made concrete: the private store is a private repository. |

## 3. What would move (measured, dry run)

`python scripts/report_data_policy_migration.py` (added by this change; read-only, deterministic, reuses the CI guard's
detectors) on 18,958 tracked files, 2026-11-19:

| Class | files | MB | where |
|---|---:|---:|---|
| `MOVE_PAID_VENDOR` | 3,317 | 79.5 | `data/raw/{dlf_*, draftsharks*, footballguys_*, dynastynerds, pff_idp}`, **2,152 paid-vendor files under `data/ros/runs/`** (Draft Sharks ROS and similar), paid `CSVs/site_raw/*` |
| `MOVE_TERMS_FORBID` (FantasyPros) | 4,558 | 13.1 | `data/raw/fantasypros*` (120 per feed), **4,192 under `data/ros/runs/`** |
| `MOVE_OWNER_IDS` | 199 | 65.0 | `exports/archive/` (159), `data/ros/power_snapshots/` (21), `exports/narratives/` (8), `data/ros/sims/` (4) |
| **Total move** | **8,074** | **157.6** | about 1% of the 2.28 GB tracked data volume; the bulk (1.4 GB `data/ros/aggregate`) is not touched |
| `FIXTURE_OWNER_IDS` | 7 | 2.4 | `tests/fixtures/` (pseudonymise in place, do not move) |
| `REVIEW_CONFIG` | 3 | 0.0 | `config/leagues/`, `config/sharp/` (reviewed config; league id accepted as public in `SECURITY.md`) |
| `UNVERIFIED_FREE` (stays) | 1,002 | 84.1 | KTC, FantasyCalc, Dynasty Daddy, IDPTC and the other free feeds |
| `PROTECTED_STAY` | 68 | 1.4 | `data/scrape_state/` and `data/sleeper_last_good.json`; the script exits 3 if a move ever overlaps this set |

New finding the brief did not size: the `data/ros/runs/` tree is vendor data too (6,344 of the 7,875 vendor-named
files), and `data/ros/` is covered by a rotating prefix in the guard baseline, so it was invisible to the guard.
Path-only mode (`--scan none`) runs in under a second; the owner-id scan takes about two minutes.

## 4. How delivery keeps working

Delivery today (all verified in the repository): `scheduled-refresh.yml` scrapes, builds, and `git add -f`s
`CSVs/ exports/ data/...`, pushes, then dispatches `deploy.yml`; box timers (`dlf_fetch_and_push.sh`,
`idpshow_fetch_and_push.sh`) push DLF and IDP Show CSVs; `deploy/deploy.sh` runs `git fetch` and `reset --hard` on the
box; `deploy.yml` validates the full target tree. The plan changes only WHERE the four classes are committed:

1. **CI**: `scheduled-refresh.yml` checks out the private repository (deploy key, new secret
   `PRIVATE_DATA_DEPLOY_KEY`, write scope on that one repository) and `git add -f`s the four classes there instead of
   in the public repository. `data/scrape_state/` keeps its public commit, so the dispatch subjects do not change.
2. **Box**: `deploy.sh` also `git pull --ff-only`s the private repository (read-only deploy key) into
   `/home/dynasty/private-data`, and the app reads moved classes through one path resolver
   (`RISKIT_PRIVATE_DATA_DIR`, falling back to the in-tree path while the stages overlap). Box timers push their CSVs to
   the private repository.
3. **Tests and the PR gate**: synthetic fixtures only (the owner of that work is PR #2239). Nothing in a pull request
   needs the private repository, so fork PRs cannot reach it and no secret reaches `pull_request`.
4. **`deploy.yml`** validates the public tree plus a checkout of the private repository at the pinned SHA, so the FULL
   contract lane still sees the shipped board. This is a change to a strict L3 file and needs its own reviewed PR.

**Trap the brief understated (verified in `deploy/deploy.sh` and the refresh workflow):** `git rm --cached` keeps files on
the machine that ran it, but the box updates with `reset --hard`, which **deletes working-tree files that the target
commit no longer tracks**. Untracking the vendor trees in the public repository would delete the box's own copies,
including the dated snapshot history the temporal ledger and Hill refit read, on the next deploy. Stage 6 below is
therefore gated on the box already reading those trees from the private checkout.

**Unverified, to be settled in stage 2 (needs box access, not available to the author):** whether the box's served
board is built from its own scrape loop (`Dynasty Scraper.py`, imported by `server.py`) or from the shipped `exports/`.
The stale comment at the top of `deploy.yml` says the former; the brief and `deploy.sh` suggest git is the transport.
The plan works either way (the private checkout supplies the bytes), but stage 5 needs to know which readers to repoint.

## 5. Vendor licensing: what is and is not known

Only FantasyPros terms were located (`fantasypros.com/about/legal/`, fetched 2026-11-18): they bar copying,
republishing, uploading or distributing site material without prior written permission, and are silent on scraping and
rankings data specifically. Whether the repository's FantasyPros files fall under that is a legal reading, **not
assessed here**. For Dynasty League Football, Draft Sharks, The IDP Show, Dynasty Nerds, Footballguys, PFF, KeepTradeCut and
every free feed, **no terms were verified**, and "not verified" is not "permitted".

Policy: paid vendors and FantasyPros move (the cautious default the brief proposed); the free feeds with unverified
terms stay, as a **recorded risk acceptance the owner signs** (decision 2 below), to be revisited vendor by vendor as
the owner collects terms or permissions. `--include-unverified-free` on the dry run sizes the alternative (adds 1,002
files, 84.1 MB).

## 6. Sleeper identifiers

`SECURITY.md` already records that the Sleeper league id is a public resource identifier (Sleeper's read API needs no
authentication), and Sleeper's league user list is retrievable the same way for anyone holding that id. The owner-id
fields in the archives (73,448 occurrences over 169 files, a few dozen distinct managers) are therefore largely
re-derivable from Sleeper itself by anyone who knows the league id, which is why the recommendation accepts the past
exposure and fixes the future: new full-fidelity archives are private, and anything public carries the per-league
pseudonym. This reading is the author's and rests on `SECURITY.md`; the owner confirms it in decision 3.

## 7. Historical exposure

Removing files does not remove history. The full dated vendor snapshots and every archive remain readable in every past
commit, in every existing clone and fork (`allow_forking` is true), and possibly in GitHub's cached views of unreachable
objects. A history rewrite means a force-push of `main`, invalidates every open branch, PR and worktree, breaks the
history-based recovery in `deploy.sh`, and **cannot recall anything already copied**. The recommendation is **not to
rewrite**. If the owner overrides this, it is a separate destructive decision with a mirror clone taken first and is
not part of any stage below.

## 8. Staged migration

Every stage ends at an owner approval point; none starts without it. Code stages are small PRs that go through the
existing L0 to L3 gates (stages 4 to 6 touch the delivery path and are high-risk under `scripts/ci_change_scope.py`).

| # | Stage | Owner approval point | Rollback |
|---|---|---|---|
| 0 | This PR: the recommendation, the dry-run script, and the guard hardening (below). No data or pipeline change. | none | revert the PR |
| 1 | Owner signs the decision (section 9). Owner collects vendor terms in parallel. | **the signature** | n/a |
| 2 | Owner creates the private repository, a write deploy key (for CI) and a read-only deploy key (for the box), with Actions disabled. Box check (author could not do it): is the served board built locally or from shipped `exports/`. | **owner creates repository and keys** (never an agent, never a PAT with wider scope) | delete the repository and keys |
| 3 | Mirror, do not move: copy the classes into the private repository; verify file counts and SHA-256 against the dry run's list; leave the public repository untouched. | owner confirms the verification report | delete the private repository contents |
| 4 | Dual write: CI and the box timers also commit to the private repository; readers get the path resolver with the in-tree fallback. | owner approves the `scheduled-refresh.yml` and timer-script PR | remove the extra writes; the resolver falls back |
| 5 | Stop the public writes: drop the four classes from the `git add -f` list and the box push scripts, add the owner-id pseudonymising step to archive production, add `.gitignore` entries, shrink the baseline. `deploy.yml` checks out the private repository. | **owner approves the delivery-path PR and the exact-tree release candidate** | restore the `git add -f` entries; data still in both places |
| 6 | Untrack the four classes in the public repository in one reviewed PR, **only after** the box has run stage 5 for a full retention cycle and reads the trees from the private checkout (the `reset --hard` trap, section 4). | **owner approves, after the dry run is re-run and shows the box path is preserved** | `git revert` the PR; the private repository still holds every file |
| 7 | History rewrite. **Recommended: skip.** | separate owner decision | none once force-pushed |
| 8 | Ratchet: shrink `config/security/tracked_data_exposure_baseline.txt` as paths leave; the guard stays. | none | n/a |

## 9. The exact decision the owner signs

> I approve, for the repository `jasonleetucker-code/riskittogetthebrisket`:
> 1. **Visibility:** it stays public. Becoming private is rejected at an estimated $450 to $700 per month.
> 2. **Vendor data:** paid-vendor boards (Dynasty League Football, Draft Sharks, The IDP Show, Dynasty Nerds,
>    Footballguys, PFF-derived, Signals) and FantasyPros raw move to a private data repository. I accept, and record, the
>    risk of leaving the free feeds with unverified terms (KeepTradeCut, FantasyCalc, Dynasty Daddy, IDPTC, Yahoo/Boone,
>    OTC, Flock, Fantasy Navigator, Play for Keeps) tracked until I supply their terms. I will supply each vendor's terms
>    or written permission, and the default for any vendor I do not answer for is "not redistributable".
> 3. **Sleeper owner ids:** new full-fidelity archives go to the private repository; anything public carries the
>    pseudonym. I accept the past exposure as low sensitivity.
> 4. **History:** no rewrite.
> 5. **Setup:** I will create the private repository and the two deploy keys myself (stage 2), and I authorise stages 3
>    to 5 as separate PRs under the normal gates. Stage 6 needs my separate approval.

If any item is declined: 1 declined (go private) needs the cost accepted and Actions cuts planned first; 2 or 3 declined
leaves the stage-0 guard as the only control; 4 can be reversed only before anything is published to the contrary.

## 10. What this change adds (non-destructive)

- `scripts/report_data_policy_migration.py` and `tests/governance/test_report_data_policy_migration.py`: the dry run;
  stdlib, deterministic, no mutation (a test fails if the script gains a delete or write call).
- A real gap in the existing guard closed in `scripts/audit_tracked_data_exposure.py::check_changed_since`, with a test
  in `tests/governance/test_tracked_data_exposure_guard.py`: the brief's known limit was that anything under the
  rotating prefixes (`data/raw/`, `data/ros/`, `exports/archive/`, ...) is acknowledged, so a NEW paid vendor feed
  committed in a new directory there passed. A paid-vendor file under a baselined prefix now fails the PR check when its
  directory does not exist at the merge base. Refresh pushes go straight to `main` and never run this check, and files
  in existing vendor directories are unchanged in behaviour, so no served data and no delivery step is affected.
- Not changed: the data contract, `scheduled-refresh.yml`, `deploy.yml`, the baseline file, repository settings.
