# Public-repository data exposure: decision brief (Task 8)

Date: 2026-11-18. Status: **input for an OWNER policy decision.** Nothing in this PR deletes, untracks, moves or rewrites data, changes visibility, or changes what the refresh/deploy pipelines publish. No legal conclusions. No identifier, token or paid-source value appears here: counts, field names, paths and vendors only.

Related: `SECURITY.md`, MD-23 (IDP Show proprietary-data hygiene), `docs/security/PUBLIC_SURFACE_CENSUS_2026-11-15.md` (public API routes, a different surface), `tests/api/test_tracked_artifacts_privacy.py` (per-manager decision intelligence).

## 1. Facts (measured 2026-11-18 on `main`)

Reproduce: `python scripts/audit_tracked_data_exposure.py` (aggregate output committed as `DATA_EXPOSURE_INVENTORY_2026-11-18.md/.json` beside this file).

- Repository is **public** (`private: false`); GitHub reports ~882 MB.
- 18,872 tracked files; 12,554 in inventory scope (`CSVs/ exports/ data/ config/ reports/ audit/` plus data-like extensions), 2.28 GB uncompressed.
- **Vendor boards committed.** `CSVs/site_raw/` holds 30 current vendor CSVs. `data/raw/<vendor>/` holds ~120 dated snapshots per source. Heuristically-paid vendors by path: Draft Sharks (1,724 files), Dynasty League Football (501), Footballguys (862), Dynasty Nerds (123), PFF-via-IDP tables (120), The IDP Show (9). `exports/archive/` zips (123 of 158 carry `site_raw/` vendor CSV members) re-include them. Free/public sources (KTC, FantasyCalc, FantasyPros, Dynasty Daddy, IDPTC, Yahoo/Boone, OTC, others) account for another ~5,600 files.
- **Sleeper identifiers.** The 158 archive zips, `exports/dynasty_export_latest.zip` and `exports/latest/` carry the full contract's `sleeper` block: 73,448 owner/user-id fields and 34,908 league-id fields in 169 files (category `derived_board_with_league_identifiers`). A further 37 files elsewhere (`audit/baseline`, `data/ros/power_snapshots`, `data/ros/sims`, `config/leagues`, narratives, a few fixtures) carry 3,652 owner/user-id fields. Emails: 0 found (excluding the bot noreply). Person-name fields (`username`, owner/manager names): 90 occurrences, all in `config/`. Display names inside the contract are player names and are not counted.
- **Size/churn.** `data/ros/aggregate` is 1.38 GB (1,397 files); `data/identity` 506 MB; `data/raw_sources` 104 MB. These are not sensitive-looking but dominate clone size.
- **Why it is tracked** (verified by grep, see inventory "Why path groups are tracked"): `scheduled-refresh.yml` runs `git add -f` over `CSVs/ exports/ data/raw/ data/raw_sources/ data/identity/ data/ros/ data/scrape_state/ data/canonical/ data/sleeper_last_good.json` and selected `config/draft_valuation/*` every ~2 h; box timers `deploy/dlf_fetch_and_push.sh` and `deploy/idpshow_fetch_and_push.sh` push DLF / IDP Show CSVs and dataset state to `main` directly; `deploy/deploy.sh` does `git fetch` + `reset --hard` on the box, so **git is the transport that puts `exports/` and `data/` on production**; `deploy.yml` validates the whole target tree; deploy dispatch keys on the refresh commit subjects (CLAUDE.md W31-F001: `git rm --cached` on `data/scrape_state/` freezes production `source_health`). 61 test/script/src files read the export archive (`tests/archive_fixtures.py::newest_complete_raw_payload` and others).
- **Already done, do not duplicate:** per-manager decision-intelligence content is guarded by `tests/api/test_tracked_artifacts_privacy.py` (and `data/ros/team_strength` is unstaged by B8). That guard is about *content* (weakness maps, tendencies); it does not look at paid-vendor boards or at bare owner-id fields in archives. The new guard below is complementary.

## 2. Vendor terms (input only; no conclusions)

| Vendor (heuristic paid/private) | Public terms located? | What is verifiable |
|---|---|---|
| FantasyPros (listed as free here; paid tiers exist) | **Yes**, `fantasypros.com/about/legal/` (fetched 2026-11-18) | Terms bar copying, republishing, uploading, posting or distributing site material without prior written permission except a single personal copy; bar commercial reuse; content owned by the operator. Terms do not mention scraping, bots or rankings data specifically. Whether FantasyPros data in `data/raw/fantasypros*` falls under this is a legal reading: **not assessed**. |
| Dynasty League Football | **Not verified.** Terms URL returned 403 to the fetch tool | Unknown. Premium product by public reputation; not confirmed here. |
| Draft Sharks | **Not verified.** Guessed terms URLs returned 404 | Unknown. |
| The IDP Show | **Not verified.** Search surfaced no terms page | MD-23 (owner intake) already records that automated capture of paid tables needs separately verified permission, and PFF-derived tables need PFF licensing. |
| Dynasty Nerds | **Not verified.** Guessed URL 404; a search result shows a premium-membership page only | Unknown. |
| Footballguys, PFF | **Not attempted** (no terms located; paid by public reputation) | Unknown. |
| KeepTradeCut | **Not verified** (guessed URLs 404) | Unknown. |
| FantasyCalc, Dynasty Daddy, IDPTC, Yahoo/Boone, OTC, Flock, Fantasy Navigator, PFK | **Not attempted** | Unknown. |

Owner action for this section: collect each vendor's terms (or any written permission already held) and decide per vendor. "Not verified" must not be read as "permitted".

## 3. Options

Common caveat for every option: **history stays public** unless git history is rewritten. Anyone who cloned or forked already holds past snapshots; GitHub may retain unreachable objects and cached PR refs. Rewriting history is a separate, destructive decision (force-push of `main`, invalidates every open branch/PR/worktree, breaks `git log`-based tooling such as `--git-history` recovery in `deploy.sh`, and still cannot recall existing clones/forks). Not proposed here.

### Option A, accept and document
- Privacy/licensing: unchanged exposure; growth stopped only by the guard. Paid-vendor values remain redistributable by anyone.
- Cost: ~0 (this PR). Risk: vendor complaint/takedown or account termination; the owner-id fields resolve to Sleeper accounts outside the league (see public-surface census §3). Reversibility: fully reversible to any other option later.

### Option B, make the repository private
- Privacy/licensing: removes public readability going forward (not past clones/forks). Does not change what is stored, so vendor data remains in a repository under the owner's control only.
- **Actions-minutes impact (measured).** Public-repo Actions are free and unbilled (the run `timing` endpoint reports 0 billable ms for every sampled run). A private repo bills minutes. The API's 1,000-run search cap returned only the newest 1,000 runs, covering 2026-11-11 to 2026-11-18 (about 6.7 days; 2,500 runs exist since 2026-10-19). Over that window:
  - wall-clock minutes summed over runs: ~7,100 (~1,060/day, ~32,000 per 30 days);
  - the dominant workflows are PR Validation (123 runs, ~1,780 wall-min), Deploy Production (73, ~1,750), Bootstrap Sharp Records (50, ~1,330), E2E Safety Net (27, ~570), Scheduled Data Refresh (20, ~140);
  - billing is per job-minute, and the sharded jobs run in parallel: sampled runs show job-minutes about 4 to 6 times wall-clock for PR Validation (~65 job-min vs ~14 wall) and Deploy (~130 vs ~24), about 1x for the others;
  - **order-of-magnitude estimate: 60,000 to 90,000 billed minutes per 30 days**, versus a 2,000 (Free) or 3,000 (Pro/Team) monthly allowance. At the published Linux rate (about $0.008/min; verify current pricing) that is very roughly $450 to $700 per month, before per-job round-up. Caveats: the sample week was an unusually busy remediation campaign; only 8 of 69 `runs-on` lines are pinned to `ubuntu-24.04` and the rest `ubuntu-latest` (both Linux, 1x); no Windows/macOS runners found. The plan tier was not readable from the API, so the allowance is unconfirmed.
  - Mitigations if pursued: cut Bootstrap Sharp Records and the 2-hourly refresh cadence, fewer shards, or self-hosted runners (a separate cost and security decision).
- Other changes: GitHub Pages is not enabled (`has_pages: false`); Dependabot works on private repos; secret scanning for private repos needs GitHub Advanced Security (paid) while it is free on public repos; public links to the repo in docs, forks and external references break; code scanning/other Advanced Security features may need a licence; any Claude/Codex or third-party integration relying on public clone access needs re-authorisation. `deploy.sh` on the box needs a deploy key or token (check its current remote auth). Wide effects on the site's `chaseupside.com` public traffic: none (the site is served from the box, not from GitHub).
- Cost: low engineering, high running cost (above). Risk: CI throttling or spend cap blocks merges and refreshes. Reversibility: private to public is one click but re-exposes everything; forks made while public persist.

### Option C, stop committing vendor CSVs and board exports (box-local / private artifact storage)
- Privacy/licensing: the most direct fix of licensing exposure going forward; also removes the owner-id-bearing archives from new commits. Past history unaffected.
- What breaks today and must be re-plumbed first:
  1. **refresh -> deploy dispatch.** Deploy keys on refresh commit subjects (`freshness stamps ...`, `automated data refresh ...`); `data/scrape_state/` must stay tracked or be replaced by another trigger and a non-git source-health channel.
  2. **deploy ships `exports/` and `data/` via git on the box** (`git fetch` + `reset --hard`); stopping commits means the box must get these another way (it already scrapes some sources itself via timers; CI-scraped sources would need an upload path) and `deploy.yml`'s "full lane" contract validation (`scripts/validate_api_contract.py --lane full`) reads the shipped board, so it needs a private artifact.
  3. **tests that read archives**: 61 files use `exports/archive` / `newest_complete_raw_payload`; PR #2239 (pinning test inputs into minimal fixtures) is the prerequisite so CI no longer needs the real archive. Fixtures must themselves be synthetic or stripped of vendor values and owner ids.
  4. **Hill autopilot** (`refit-hill-curves.yml`, ~2 h) trains on vendor observations in `data/raw` / archive boards; needs a private artifact input and the same provenance pinning.
  5. **Temporal ledger / history**: `scripts/build_temporal_ledger.py` backfills from `exports/archive/`; the as-of history floor (2026-07-14) exists only in these files, so a private archive must be created BEFORE untracking (copy, verify, then stop committing).
  6. **Public `/league` features**: served from the box's own snapshots; tracked CSVs are not on its request path, so low risk, but verify against `data/public_league/` and `exports/latest/`.
  7. Retention workflows and `src/maintenance/retention` prune tracked trees; they would need to prune the private store instead.
- Cost: high (multi-PR, touches the deploy contract; high-risk escalation under `scripts/ci_change_scope.py`). Risk: stale production data if the new transport fails (fail-safe: box keeps serving what it has). Reversibility: good if the pipeline keeps a flag to also commit; data already left out of commits cannot be re-created for the gap.

### Option D, hybrid (recommended)
Keep `data/scrape_state/` and the free/public-source material tracked (they are what the deploy contract and tests key on), and move the **paid vendors and owner-id-bearing board archives** out of git first:
- paid-vendor raw trees (`data/raw/{dlf_*,draftsharks*,footballguys_*,dynastynerds,pff_idp}`, paid `CSVs/site_raw/*` and their copies inside archive zips) to box-local/private storage;
- archive zips/`exports/latest` produced with the `sleeper` block's owner/user ids pseudonymised or stripped (the public-surface census already adopts a per-league pseudonym decision D1, so one owner-id strategy covers both);
- keep the repository public; keep the new guard permanently as the ratchet.
Privacy/licensing: removes the highest-risk class going forward, no Actions cost. Engineering: medium, staged. Risk: moderate, stage-gated. Reversible per step. History remains public as above.

### Comparison

| | A | B private | C full stop | D hybrid |
|---|---|---|---|---|
| Stops new vendor redistribution | No (guard only blocks new paths) | Not public, still stored | Yes | Yes for paid vendors |
| Stops new owner-id publication | No | Not public | Yes | Yes |
| Running cost | none | est. $450 to $700/mo (see above) | none | none |
| Engineering | trivial | low | high | medium |
| Pipeline risk | none | CI throttling | high | moderate, staged |
| Reversibility | full | full (but forks persist) | partial (gap data lost) | per step |
| Past history | public | public to anyone who copied it | public | public |

## 4. Recommendation and owner decisions

**Recommend D, preceded by this PR's guard (an interim A).** Owner decisions needed, in order:

1. **Vendor policy**: for each paid/private vendor, is redistribution in a public repository acceptable (needs the vendor's terms or permission, section 2)? Default if unanswered: treat paid vendors as not redistributable.
2. **Owner-id policy**: are Sleeper owner/user ids in archive zips acceptable publicly, or stripped/pseudonymised (align with D1 of the public-surface census)?
3. **History rewrite**: yes/no, with the destructive consequences above. Default: no.
4. **Private repository**: only if the owner accepts the cost estimate in Option B.

## 5. Migration plan (ordered, each step reversible, nothing executed here)

| # | Step | Owner decision | Rollback |
|---|---|---|---|
| 0 | Merge this PR: inventory script, baseline, guard test (no publishing change) | none | revert the PR |
| 1 | Pin test inputs to minimal synthetic fixtures (PR #2239) so CI stops needing real archives; verify with the 61 reading files | none (authorised intake) | revert fixtures PR |
| 2 | Build a **private** mirror of what will leave git (box-local directory plus backup via the existing state-backup script); verify copy counts and hashes; no deletion yet | confirms storage location | delete the mirror |
| 3 | Stop the box timers pushing paid CSVs (`dlf_fetch_and_push.sh`, `idpshow_fetch_and_push.sh`): write to the private store, keep their dataset-state stamps tracked | decision 1 | restore the push block in the scripts |
| 4 | In `scheduled-refresh.yml` stop `git add -f` of paid-vendor paths in `CSVs/` and `data/raw/` (guarded by the baseline: new paid paths already blocked); the box reads from the private store | decision 1 | re-add the paths |
| 5 | Strip or pseudonymise owner/user ids in newly produced `exports/` archives (single owner of the transform shared with the public-surface D1) | decision 2 | disable the transform flag |
| 6 | Untrack (`git rm --cached`, files kept on disk) the already-tracked paid vendor trees, in one reviewed PR after steps 2 to 5 have run clean for a full retention cycle; never `data/scrape_state/` | decisions 1 and 2 | `git revert` of that PR; files still on the box |
| 7 | Optional: history rewrite | decision 3 | none once force-pushed; take a mirror clone first |
| 8 | Ratchet: shrink `config/security/tracked_data_exposure_baseline.txt` as paths leave git; the guard keeps new exposure out | none | n/a |

## 6. What this PR adds

- `scripts/audit_tracked_data_exposure.py` (stdlib; deterministic; counts only), plus the committed aggregate report.
- `config/security/tracked_data_exposure_baseline.txt`: paths only. 43 exact paths of existing offenders plus 8 rotating directory prefixes that the refresh republishes (`data/raw/`, `data/raw_sources/`, `data/canonical/`, `data/ros/`, `data/playerctx/history/`, `exports/archive/`, `exports/latest/`, `exports/narratives/`). **Known limit:** inside those prefixes new files are acknowledged, so growth there (for example a new vendor directory under `data/raw/`) is not blocked. Closing it needs the owner decision above; the guard still blocks any new location.
- `tests/governance/test_tracked_data_exposure_guard.py`: fails when a tracked in-scope file not covered by the baseline has owner/user-id-like fields with 17 to 19 digit values (including inside zip members), is a paid-vendor board by path, or is a zip carrying paid-vendor members. Synthetic-file unit tests cover each rule and the baseline matching.
