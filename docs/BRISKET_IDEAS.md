# Calculator Ideas — Owner Intake & Parallel Work Front Door

## Full completion portfolio / permanent UI batching — 2026-09-24 (#1421)

UI policy: ALWAYS_PARALLEL_UNTIL_UI_COMPLETE
UI batching: INCLUDE_OR_REFERENCE_ACTIVE_LANE

Calculator Ideas represents the entire remaining master site completion plan. Keep this
legacy filename; it is a front door, not a competing backlog. Before next reasonable
batch / next ten / parallel batches / fresh-session dispatch, reconcile current main,
open PRs/branches/claims, Master Plan, Feature Inventory, Product Backlog/specs, C-Series
manifest/map, completion contracts, owner intake, issues, code/production evidence and
the combined-phase replan. Remove completed/superseded/rejected work, group shared
foundations, respect dependencies and avoid active-file conflicts. #1419's full-portfolio
reconciliation is folded into §8 (batch ranking); issue #1418 is its durable record.

Every substantial batch explicitly evaluates backend completion, UI completion, actual
UI staffing, stable routes, file/branch conflicts and integration order. Consult
`docs/ui/CALCULATOR_UI_IMPLEMENTATION_CONTRACT.md` and `docs/ui/UI_PARALLEL_LEDGER.md`. Required response shape:

- FOUNDATION / BACKEND: bounded authorized unit, canonical owner, dependencies.
- UI: safe unit/claim/branch, or `UI lane already active: <issue/PR/work claim>` with
  adequate coverage. Queued handoffs/old branches are not running workers. An unstable
  route contract blocks only its final wiring; select other useful UI work.
- INTEGRATION: contract connection, ordering, E2E and production proof. Backend complete
  / UI incomplete = product incomplete, without double-counting scope.

Use `docs/ui/UI_IMPACT_TEMPLATE.md` for material feature plans. Tiny maintenance need
not manufacture UI edits; substantial planning still names Lane 6 coverage.

**Status:** OWNER-FACING NAVIGATION / PROCESS LAYER  
**Owner directive:** 2026-09-24 · issue #1412  
**Product authority:** none by itself. `docs/EXECUTION_PLAN.md` remains the only implementation-authorization record.

This is the simple front door for ideas, defects, UX requests, methodology changes, future products, and “do this later” instructions for **Calculator**.

The owner should not need to remember the repository's planning-document hierarchy.

## 1. Conversational shorthand

When the owner says any of the following, treat them as equivalent:

- “add this to Calculator Ideas”
- “put this on the Calculator list”
- “save this idea”
- “remember this for the site”
- “we should build/fix/revisit this later”

The durable destination is still the existing canonical intake system:

```
owner statement
  -> docs/OWNER_REQUESTED_TODO.md        # live intake ledger
  -> existing/new GitHub issue or spec   # detail when needed
  -> canonical feature/spec/manifest mapping
  -> docs/EXECUTION_PLAN.md              # only place that authorizes implementation
```

**This file is not a second backlog.** It explains how to use the one we already have.

## 2. One idea, one durable record

Before creating anything new:

1. search `docs/OWNER_REQUESTED_TODO.md`;
2. search open/closed GitHub issues;
3. search the Feature Inventory / Product Backlog Spec / feature-specific specs;
4. search recent PRs and current code when the request may already be implemented;
5. update/supersede the existing record when one exists instead of creating a duplicate.

If a later owner instruction changes an earlier one, preserve the old record for history and mark the newer instruction as the active supersession.

Do not delete history merely to make the list look cleaner.

## 3. Lightweight same-session portfolio check

Every **material** new owner idea triggers a small planning pass in the same session. This is intake/reconciliation, not implementation authorization.

Record or determine:

- **Priority:** P0 / P1 / P2 or the product-family equivalent already in use.
- **Canonical owner:** the module/system that should own the concept.
- **Dependencies:** what must exist or be proven first.
- **Overlap / supersession:** which existing idea, issue, feature or defect it touches.
- **Shared foundation:** whether an already-needed primitive can satisfy several ideas at once.
- **Planning position:** NOW / NEXT / LATER / BLOCKED.
- **Parallel class:** SAFE_PARALLEL / SERIAL_CANONICAL_OWNER / INTEGRATION_ONLY / DEPENDENCY_BLOCKED.
- **Roadmap effect:** whether it changes the current combined phase or should wait.
- **Acceptance evidence:** what would prove the work is actually complete.

Always ask:

> Can this be implemented through an already-needed canonical owner or shared foundation so several requirements are unlocked once, without creating a second implementation?

The answer should prefer reuse/consolidation over feature-local copies.

## 4. Planning position vocabulary

These labels organize the portfolio. They **do not grant authority**.

| State | Meaning |
|---|---|
| **NOW** | On the current critical path or already-authorized campaign. Must still be supported by `EXECUTION_PLAN.md`. |
| **NEXT** | Dependency-ready or nearly ready; the next sensible work once current prerequisites/claims clear. |
| **LATER** | Wanted and preserved, but not on the current path. |
| **BLOCKED** | Waiting on a named dependency, owner decision, credential, evidence, or canonical-owner work. |
| **PAUSED** | Explicitly paused by the owner; do not resume without a later owner instruction. |
| **DONE** | Implemented and verified to the evidence standard named by the canonical record. |
| **REJECTED / NOT PLANNED** | Deliberately not doing it; keep the reason so it is not re-litigated from scratch. |

Legacy status words in older planning records remain historical evidence. Do not mass-rewrite old rows just for vocabulary consistency. Normalize an item when it is next touched/reconciled.

## 5. Authorization is a separate axis

A planning state is not permission to build.

Use `docs/EXECUTION_PLAN.md` for the authority question:

- **AUTHORIZED NOW**
- **NOT AUTHORIZED**
- **COMPLETE / VERIFIED**
- **OWNER ACTION REQUIRED**

An item may be `NEXT` while still `NOT AUTHORIZED`.

An issue, this document, the intake ledger, a branch, or a model's confidence can never silently promote work into authorized implementation.

## 6. Parallel-work classification

Parallel work is encouraged when it is genuinely independent and discouraged when it creates competing canonical owners.

### SAFE_PARALLEL

Use when all are true:

- independent canonical owners or clearly disjoint files;
- no unresolved dependency between the units;
- one writer per path/canonical concept;
- acceptance can be tested independently;
- integration order is known.

Examples: a frontend-only presentation unit and a source-research unit that consume a stable contract.

### SERIAL_CANONICAL_OWNER

Use when multiple ideas touch the same canonical owner, especially high-conflict owners such as:

- `src/api/data_contract.py`;
- `server.py`;
- canonical player/pick value;
- identity;
- trade simulation;
- scoring;
- shared persistence/schema.

Combine/resequence the requirements, then use one writer for that owner. Do not let several sessions create alternate implementations.

### INTEGRATION_ONLY

The implementation is complete or independent, but the next step requires the integration/traffic-control role to:

- reconcile current `main`;
- sequence dependent PRs;
- run final integration/release gates;
- merge/deploy.

Implementation agents freeze rather than chase every movement of `main`.

### DEPENDENCY_BLOCKED

A required upstream owner, permission, data source, owner decision, or evidence gate is missing. Name the blocker precisely and move to another dependency-ready unit instead of idling.

## 7. How multiple sessions should work

For meaningful parallel work, prefer:

```
coordinator / traffic control
    |
    +-- bounded lane A (one owner / one path set)
    +-- bounded lane B (different owner / path set)
    +-- bounded lane C (different owner / path set)
    |
    +-- read-only reviewer when warranted
    |
integration queue -> current-main reconciliation -> merge/deploy
```

There is no magic number of lanes. Use the smallest number that gains real calendar time. Two to four active implementation lanes is usually enough; more lanes are justified only when the ownership graph is genuinely independent.

Every lane gets:

- mission;
- canonical owner;
- exact paths;
- dependencies;
- writer/read-only role;
- acceptance tests;
- stop condition;
- work claim.

Before writing, check:

- `docs/WORK_CLAIMS.md`;
- open PR changed-file lists;
- remote branches;
- current execution authorization.

If a unit collides with a live claim, do not build around the owner. Mark only that unit blocked and continue with another dependency-ready unit.

## 8. Shared-foundation / combined-phase rule

Calculator has many historical issue numbers and owner decisions. Issue order is not automatically implementation order.

When several requests share:

- the same canonical owner;
- the same data model;
- the same API contract;
- the same UI primitive;
- the same source/provenance layer;
- the same test/deploy prerequisite;

plan the shared foundation once, then split implementation into small coherent PRs.

The canonical combined-phase sequencing overlay is:

`docs/BACKLOG_REPLAN_2026-09-10.md`

It is subordinate to the Master Product Plan and Execution Plan and does not authorize work.

### "Next reasonable batch": rank by practical importance, never by issue number

When the owner asks for the next reasonable batch (or equivalent), recompute a bounded batch from
current truth; do not take the next issue numbers or the next rows in one document. Prefer, in
order, unless evidence justifies a different sequence:

1. P0/P1 correctness, production health, data loss, security or user-blocking defects;
2. completion-critical requirements that block the declared completion contract;
3. high-unlock shared foundations that satisfy or unblock several downstream requirements;
4. time-sensitive / irrecoverable evidence work that cannot be reconstructed later;
5. dependency-ready product work with high user value;
6. adjacent cleanup that is cheap because the same owner/files are already open.

Within a tier favor more downstream unlocks, fewer canonical-owner conflicts and smaller coherent
PR boundaries. Never rank by novelty, issue age or issue number. A batch normally has one primary
critical-path lane plus zero to a few genuinely independent lanes (two to four is a default, not a
quota); serial/integration-only work kept separate; acceptance criteria and stop conditions per
lane; merge order; and named owner-only decisions or external blockers. (Harvested from #1419;
issue #1418 remains the durable record.)

## 9. Intake record shape for new material ideas

The compact owner ledger may stay compact, but the issue/spec should make these fields recoverable:

```
Owner request
Area / product family
Required outcome
Canonical owner
Priority
Planning position: NOW | NEXT | LATER | BLOCKED
Authorization: from EXECUTION_PLAN
Dependencies
Overlap / supersession
Shared foundation
Parallel class
Acceptance evidence
Status
Related issue/spec/PR
```

Do not force trivial one-line fixes to create a giant spec. Use proportional detail.

## 10. Cleanup rules

Orderliness means fewer conflicting truths, not fewer historical records.

- Do not create a second idea ledger.
- Do not duplicate an existing issue because its title differs.
- Do not copy an entire feature spec into the intake table.
- Use compact pointers from intake -> detailed record.
- Close/mark superseded records only when the successor is explicit.
- Preserve rejected ideas and their reasons.
- When a status is stale relative to merged code, fix the status rather than creating a new feature row.
- Prefer one canonical owner and many consumers.
- Keep implementation readiness separate from product desirability.

## 11. Where to look

| Question | Record |
|---|---|
| “Where do I put this idea?” | `docs/OWNER_REQUESTED_TODO.md` (use the shorthand **Calculator Ideas**) |
| “What exactly did the owner mean?” | GitHub issue + `docs/OWNER_PRODUCT_BACKLOG_SPEC.md` / feature-specific spec |
| “Does it already exist / what is its status?” | `docs/OWNER_FEATURE_INVENTORY.md` + current code/PR evidence |
| “Which canonical owner/foundation should handle it?” | `docs/MASTER_PRODUCT_PLAN.md`, architecture records, combined-phase replan |
| “Can several items be built together?” | this file + `docs/BACKLOG_REPLAN_2026-09-10.md` |
| “Where is the DFS plan?” | `docs/dfs/README.md` → `ROADMAP.md` / `TRACEABILITY.md` (supporting detail for the one intake entry, not a second backlog) |
| “Does DFS need CSV uploads?” | **No — permanent owner requirement (2026-09-30):** automated data first, manual files second. `/dfs` opens on automatically populated slates; manual import is fallback / override under *Advanced* (`docs/dfs/DECISIONS.md` ADR-DFS-024, `TRACEABILITY.md` DFS-AUTO-01..24) |
| “Is it authorized now?” | **`docs/EXECUTION_PLAN.md` only** |
| “Who is editing it?” | `docs/WORK_CLAIMS.md`, open PRs and branches |
| “How do branches/merges work?” | `ASSISTANT_COORDINATION.md` |
| “How does an agent operate?” | `AI_INSTRUCTIONS.md` + `docs/AGENT_OPERATING_SYSTEM.md` |

## 12. Owner experience

The owner may simply say:

> Add this to Calculator Ideas.

The agent is responsible for the repository bookkeeping. The owner should not have to choose between the intake ledger, issue tracker, feature inventory, manifest, backlog spec, or execution plan.

The agent should report what durable record was updated and whether the idea is NOW, NEXT, LATER, BLOCKED, PAUSED, or already covered — without turning capture into unauthorized implementation.

## 13. Perishable-evidence capture audit — 2026-09-29

**Owner directive (2026-09-29):** identify data that will be "impossible to recreate later"; where a needed
stream is not preserved, record it here with the minimum capture path; prefer capturing now over
reconstructing with hindsight. Intake pointer: `docs/OWNER_REQUESTED_TODO.md` (2026-09-29 entry).

**Authority:** planning record only. Capture is not implementation authorization; every gap below is
`NOT AUTHORIZED` until `docs/EXECUTION_PLAN.md` says otherwise. It creates no second history system: each
capture path extends an existing owner (`src/history/`, `docs/retention/RETENTION_REGISTER.md` /
`deploy/backup/riskit-state-backup.sh`, `src/ros/game_day_live.py`, `src/source_archive/`,
`src/retention/evidence_store.py`). Planning tier: §8 tier 4 (time-sensitive / irrecoverable evidence).

**Method.** Each stream was checked against its writer, schedule (`deploy/systemd/*.timer.template`, all
reconciled by `deploy/deploy.sh` on every deploy; `.github/workflows/`; the `server.py` 2 h scrape loop),
retention/prune code and the nightly backup set (`riskit-state-backup.sh`, 14 daily generations). Repo facts
only: on-box file sizes, row counts and timer run state were **not** observed in this unit (UNVERIFIED).

### 13.1 Already preserved — no action

| Stream | Owner · cadence · retention |
|---|---|
| Trade-time player + pick values; served board per generation | `src/history/` temporal ledger (`record_contract` at every fresh box scrape, 2 h; append-only, indefinite; floor 2026-07-14; picks first-class, C1-HIST-02). Raw evidence feeds besides: `board_history.sqlite` daily (C1-RET-02), `rank_history.jsonl` (C1-RET-03), git-tracked `exports/archive/` (every zip 14 d, one per day 365 d on disk, all commits in git history) and `CSVs/site_raw/*.csv` (every committed source-board change in git history). Backup gap: G7. |
| Own-league trades / waiver moves | `league_events.sqlite` (C1-RET-06) + `acquisition.sqlite` (C1-ACQ-01), captured before our window cutoff; backed up. |
| FAAB bids incl. failed claims | `dynasty-faab-history` daily 07:40 UTC → `data/faab/bid_history_<leagueKey>.json` with failed bids; Sleeper is host of record over the league chain. Crowd FAAB rolling window: C1-RET-01, 3-hourly accumulator, backed up. |
| Scoring card history | C1-RET-04 `evidence.sqlite`, per observation, before overwrite; backed up. |
| Weekly rosters / lineups as scored | Sleeper matchups (`players`/`starters`/`players_points` per week) are host of record and re-fetchable over the league chain; Game Day pregame capture (`dynasty-game-day-capture`, 4-hourly, first capture stands, IR/taxi buckets read from the payload) and generations add the pregame roster state. |
| Game Day predictions | `data/game_day/predictions/` (C5-GD-02, append-only) and `data/game_day/live/**/generations.jsonl` + `state.json` (never pruned; league-scored per-player pregame baselines for rostered players); `data/game_day/` backed up. Raw feed logs: G1. |
| Power Rankings publications | `data/ros/power_snapshots/<league>/<season>/week_NN.json`, immutable, git-tracked. |
| Playoff / title odds | `data/ros/sims/*.json`, rewritten every 2 h by the refresh runner; each commit in git history (155 commits to `latest_playoff.json` in 30 days). Runner-computed; equality with the box-served payload UNVERIFIED. *Reclassified 2026-10-01 as PARTIAL (no model identity or inputs on the payload): §13.4 AL-P6.* |
| ROS / redraft source boards | `data/ros/sources/` + `data/ros/aggregate/history/`, git-tracked every 2 h. |
| Trending adds; sharp cohort market | C1-RET-05 + hourly `dynasty-trending-history-refresh`; `data/intel/` ledger (daily crawls, sharp transactions 4×/day), backed up as a directory. |
| playerctx; nflverse stats, PBP, depth charts | C1-RET-08 weekly; nflverse is an external historical archive (re-fetchable, not perishable; stat corrections go through Game Day's corrections path). |

### 13.2 Gaps — minimum capture path

| # | Stream | Status | Owner / evidence | What is lost | Minimum capture path (existing owner) | Storage | Unblocks |
|---|---|---|---|---|---|---|---|
| **G1** | Pregame weekly projections (Sleeper, the only live weekly family) | **IMPLEMENTED — merged 2026-09-29, PR #1525** (`e1f4dce4c`, `882c4558a`: the last pre-kickoff row per player is archived to `pregame_projections.json.gz` before the prune, fail-closed, backed up under `data/game_day/`); production observation UNVERIFIED. Original finding: PARTIAL — active loss clock | `game_day_live.py` logs every `sleeper_weekly_projections` fetch append-only, then `prune_retention` deletes each league-week's `observations/` after `RAW_RETENTION_WEEKS = 4`, on every collector tick. The 14-day backup rotation does not extend it | Full-NFL raw stat lines, unrostered players and intra-week movement up to kickoff. Week 1 logs are deleted at the first tick of Week 6 (≈2026-10-13, depends on Sleeper's week flip), then one week per week. Generations keep only league-scored baselines for rostered players | Exempt `_nfl/<season>/week_N/observations/sleeper_weekly_projections.*` from `prune_retention`, or first write the kickoff-locked subset (`matchup_intel._prune_weekly_history`, already the "last pre-kickoff read" rule) beside `generations.jsonl`. One owner, one path; no new store | UNVERIFIED — measure `du` on the box before choosing between full log and locked subset | #854 / C5-ROS-01 projection-family scorecards (Adaptive Learning candidate 2); C5-GD calibration baseline provenance; MVP xWAR no-lookahead for waiver/unrostered players |
| **G2** | KTC Trade Database (real market trades) | **IN FLIGHT — PR #1586** (Batch 3 I: append-only raw archive + 30-min timer; Adaptive Learning AL-2). *2026-10-01: #1586 merged, but the box (at `ed48d54ab`) does not run it and the archive is not in the backup set — §13.4 AL-P1 / AL-P2.* Original finding: NOT PRESERVED | C4-MTL-02 ABSENT; producer retired 2026-08-18; ~200-entry rolling window (measured that day) | Every trade that scrolls out of the window, permanently | Accumulator on the C1-RET-01 pattern (`fetch_crowd_faab.py`: dedupe by KTC row `id`, merge, never truncate) under `data/`, added to the backup set and the retention register. Capture only, no consumer, never a vote | Small (≈200 rows per window); turnover rate UNVERIFIED, so it sets the cadence | C4-MTL-01/03 comparable trades, C7-DESK-01 real-trade evidence, C7-AI-03 liquidity, market calibration. Needs endpoint-level intake confirmation; whether the 2026-09-25 source attestation covers this endpoint is UNVERIFIED |
| **G3** | KTC non-selected format variants (SF base / TE+ / TE+++; 1QB UNVERIFIED) | **NOT PRESERVED** (re-verified 2026-10-01: §13.4 AL-P3) | The scraper already receives `superflexValues.{base,tep,tepp,teppp}` in the payload it parses (`Dynasty Scraper.py` ~L1835–1941) and keeps the selected mode. C1-SRC-01's `src/source_archive/` has one caller, `scripts/fetch_dynasty_nerds_idp.py`, which is not scheduled | Same-day paired format evidence. KTC publishes current values only | Call `source_archive.archive_board` from the KTC parse for the unselected variants: zero extra requests, one provider family (the C1-SRC-01 rule). Add `data/source_archive/boards.sqlite` to the backup | ≈4 × one board per scrape; UNVERIFIED | #809 multi-format archive, TE-basis / format-curve calibration. Archive is never production eligibility |
| **G4** | As-known injury / news state | **PARTIAL** | `refresh_injury_feed.py` (4-hourly, ESPN) overwrites `injuries_prior.json` and keeps only transition events in `data/bdvm/events/<season>.json` (not backed up). Sleeper players DB (`injury_status`, practice participation) is overwritten daily. `/api/news` items are in-memory, 7-day window, never persisted; BDVM news events prune at 90 d | Status as known at kickoff and at decision time; which headlines existed when. Official weekly designations stay recoverable from nflverse (2026 in-season availability UNVERIFIED) | (a) have the injury refresh append each fetched snapshot to a dated append-only log instead of only overwriting the prior; (b) persist `/api/news` item metadata (id, provider, published/fetched time, headline, URL, matched player ids; no article bodies) at the aggregator's refresh | Small: status deltas plus headline metadata | Injury-aware Game Day / MVP retrospectives, C7-ALERT-01 / C6-ANA-01 signal evaluation, FAAB opportunity backtests |
| **G5** | Draft-time state (board + roster context at draft start) | **PARTIAL** | C7-DRAFT-02 (`RET`): `backtest_perfect_draft.py --record-snapshot` exists and is manual only. Board values are recoverable as `nearest-prior` (≤ one scrape) from the temporal ledger; roster context, cut ladder, waiver levels and the plan are not | The Perfect Draft backtest inputs. Next exposure is the 2027 rookie auction, so not urgent now | Timer-driven `record_snapshot` when the league's Sleeper draft reports `pre_draft` with a near start time, first capture stands (the `game_day_capture` pattern). Must be live before the 2027 draft | Small | Perfect Draft backtest (currently `BLOCKED`, exit 2), live-auction calibration |
| **G6** | League settings beyond the scoring card | **PARTIAL** | C1-RET-04 records `scoring_settings` only. `roster_positions` and `settings` (playoff teams, median game, waiver budget, taxi/IR slots) live in the overwritten `public_league/snapshot.json`. Completed seasons are re-fetchable via the league chain | Mid-season commissioner changes | Observe a content-addressed settings payload in `evidence.sqlite` at the same `write_scoring_snapshot` site (the C1-RET-04 observation model, unobserved stays unobserved) | Negligible | Median-game / playoff methodology per week, roster-capacity history, trade replay legality at the time |
| **G7** | Backup coverage of existing append-only stores | **PARTIAL** (re-verified 2026-10-01 and widened — the nightly root job also runs a stale script: §13.4 AL-P2) | Not in `riskit-state-backup.sh`: `data/temporal_ledger.sqlite`, `data/consensus_edge.sqlite`, `data/source_archive/boards.sqlite`, `data/bdvm/` (dated projection snapshots incl. Mike Clay, plus events) | Box loss erases them. The ledger rebuilds at daily fidelity from git-tracked `exports/archive/` (idempotent backfill); Clay snapshots and Consensus Edge label history do not | Add `backup_sqlite` / `backup_dir` lines in the one backup owner, plus a retention-register addendum (the 2026-09-04 `data/game_day/` precedent) | Size UNVERIFIED | Durability for C1-HIST-01, C6-FRESH, BDVM and Consensus Edge evaluation |
| G8 | Recommendations and decisions as served (finder, suggestions, FAAB, Perfect Draft plan) | NOT PRESERVED (2026-10-01: §13.4 AL-P5, after AL-0) | Already recorded as `ADAPTIVE_LEARNING_2026-09-26.md` §6 item 8 and R14 CANDIDATE; since 2026-10-01 the DECISION / NON-ACTION receipt kinds are defined there (§19.1) and capture stays a separately sequenced unit | — | No new record; pointer only | — | C7-DESK-01, C10-ML-01 |

### 13.3 Already lost — recorded, never backfilled as exact

- Board and value history before 2026-07-14 (`HISTORY_FLOOR`); queries answer `before_history_boundary`.
- `dynasty_new` has no Week-0 preseason Power snapshot (`dynasty_main` has `week_00.json`), so its Week-1
  movement baseline was never captured.
- The C9-UR-02 preseason baseline window (Tuesday before Week 1) has passed and the manifest records the row
  ABSENT. Its inputs survive (ledger, `dynasty_main` Power Week 0), so any baseline built now is
  `nearest-prior`, not an exact contemporaneous edition.
- Analyst ledger (`src/analyst/`, C6-ANA-01): the store exists, but no scheduled producer was found, so
  nothing is accumulating.

**Suggested order (planning only).** G1 (dated deadline) → G7 (config-only) → G3 (zero extra network) →
G4 → G2 (endpoint intake) → G6 → G5 (before the 2027 draft). Parallel class: G1 is `SERIAL_CANONICAL_OWNER` on
`src/ros/game_day_live.py` (active Game Day claims); G7 owns `deploy/backup/`; G3 owns the KTC parse in
`Dynasty Scraper.py`. These are otherwise `SAFE_PARALLEL`. UI: none; these are evidence-only units.

### 13.4 Extension — 2026-10-01, Adaptive Learning directive §21 stream audit

**Owner directive (2026-10-01, Adaptive Learning master roadmap §21):** "Before building sophisticated models,
audit whether their required historical evidence is being preserved. Extend the existing perishable-evidence
audit. If something will disappear, CAPTURE FIRST. Modeling can wait. Irrecoverable evidence cannot." Plan:
`docs/research/ADAPTIVE_LEARNING_2026-09-26.md` §36. Authorization for the capture units: `docs/EXECUTION_PLAN.md`
§0 (Adaptive Learning, Wave 1 item 4). This subsection extends §13.1–§13.3; it does not replace them.

**Method.** Code and deploy config at `origin/main` `cd48748af` (writers, `deploy/systemd/*.timer.template`,
`.github/workflows/scheduled-refresh.yml`, prune code, `deploy/backup/riskit-state-backup.sh`), then a
**read-only** production check (`ssh chaseupside`, app at `/home/dynasty/trade-calculator`; no writes, no
`systemctl` changes, no sudo) on 2026-10-01 ≈19:00 UTC. **BOX** = verified on the box; **CODE** = code / config
only.

**Production facts this audit rests on (BOX):**

- The box serves **`ed48d54ab`** (#1589; `/api/status` `build.commit`, process started 18:23 UTC). It does
  **not** contain #1586, #1588, #1591, #1594, #1595, #1596 or #1598.
- Installed `dynasty-*` timers do **not** include `dynasty-ktc-trades`, `dynasty-market-trade-ledger` or
  `dynasty-sparse-evidence-shadow`. `dynasty-joint-filter-shadow` is installed and has never fired
  (`LastTriggerUSec` empty). `data/market_trades/`, `data/learning/`, `data/source_archive/`,
  `data/analyst_ledger.sqlite`, `data/robust_filter_shadow/` and `data/sparse_evidence_shadow/` do not exist.
- **The nightly root backup runs a stale script.** `riskit-state-backup.service` executes the root-owned copy
  `/usr/local/lib/riskit/riskit-state-backup.sh` (600 lines). That copy has **no** `retention/acquisition.sqlite`,
  `auction/auction.sqlite` or `game_day` lines, all of which the repo script carries. The copy reaches the box
  only through `deploy/apply_hardening.sh` → `deploy/backup/install_state_backup.sh` (or the
  `c1a-install-state-backup.yml` workflow), never through `deploy.sh`. The nightly generation under
  `/var/backups/riskit-state` is not readable without root (contents UNVERIFIED). The post-deploy generation
  under `/home/dynasty/backups/riskit-state/daily/2026-10-01` (19 artifacts) **does** include acquisition, auction
  and `game_day.tar.gz` (12.9 MB), so those streams are currently protected only by post-deploy runs.
- Not in any backup generation (BOX): `temporal_ledger.sqlite` (1.49 GB), `consensus_edge.sqlite` (42 MB, still
  root-owned), `data/bdvm/` (26 MB), `data/dfs/` (`workspace.sqlite`, 70 MB).

**Stream table.**

| Stream | Captured today? | Owner · timer / service | Storage | Retention / rotation | Backed up? | Point-in-time? | Reconstructible if missed? | Verdict |
|---|---|---|---|---|---|---|---|---|
| Pregame projection snapshots — Sleeper weekly | yes, **from Week 3, possibly partial** (BOX: `_nfl/2026/week_3` created 2026-09-25 23:20 UTC — after the Week 3 Thursday game; no Week 1–2 raw logs; our ensemble's rostered-player pregame estimates exist separately from Week 1 under `data/game_day/predictions/`) | `src/ros/game_day_live.py` `ensure_pregame_archive` (called from `prune_retention`); `dynasty-game-day-live` every minute | `data/game_day/live/_nfl/<season>/week_N/pregame_projections.json.gz` (written at prune time, Week N+5; none yet — BOX) | raw logs pruned after 4 weeks only once the archive is built and read back; archive kept 10 seasons | post-deploy generation yes; nightly root copy **no** (stale script) | write-once | no — pregame state; whether Sleeper re-serves historical pre-kickoff values is UNVERIFIED | **PARTIAL** — Weeks 1–2 lost as exact pregame; first archive build not yet observed |
| Pregame projection snapshots — BDVM season (Clay, IDP Show, proxy) | yes | `scripts/refresh_bdvm_projections.py`; `dynasty-bdvm-refresh` Tue 06:10 UTC (BOX: last ran 2026-09-29) | `data/bdvm/projections/<season>/` (immutable, `write_snapshot` refuses overwrite) | none | **no** (BOX) | immutable, dated | no — vendors publish current editions only | **AT_RISK** (box loss) |
| ROS / redraft source boards | yes | `scheduled-refresh.yml` every 2 h | `data/ros/sources/`, `aggregate/history/` | none | git history | dated + git | no | PRESERVED |
| KTC Trade Database | **no in production** (BOX: timer not installed, archive absent) | `scripts/fetch_ktc_trades.py` → `src/sources/ktc_trades.py` + `src/trade/market_trade_archive.py`; `dynasty-ktc-trades` `*:07,37` UTC (CODE, #1586) | `data/market_trades/archive.sqlite` (append-only; UPDATE/DELETE abort triggers) | none | **no** (not in the repo script either) | append-only, revisions kept | **no** — ~200-row rolling window | **AT_RISK** — every window that rolls out before the first production capture is lost |
| Sharp / Sleeper trades | yes | `scripts/crawl_sharp_transactions.py`; `dynasty-sharp-transactions` 4×/day (BOX: ran today); read read-only by the market-trade ledger as lane `sleeper_sharp_discovery` | `data/intel/ledger.sqlite3` (704 MB, BOX) | **deleted after 400 days** (`src/intel/ledger.py` `MOVEMENT_RETENTION_DAYS`, `prune()` on every intel refresh) | yes (`backup_dir intel`, a tar of a live WAL database) | append until prune | partly — per-league Sleeper transactions while the league stays reachable | **PARTIAL** (slow clock: the prune deletes by TRANSACTION timestamp and the crawler backfills to week 0 of the season, so first deletions start ≈400 days after the earliest crawled transaction, which can predate the first crawl) |
| Source boards (raw CSVs) | yes | scheduled refresh + box DLF / IDP Show timers | `CSVs/site_raw/*.csv` | none | git history | git history | no | PRESERVED |
| Change clocks (`dataset_state`) | yes | `src/sources/dataset_state.py` | `data/scrape_state/<key>_dataset.json` (overwritten; `changeHistory` capped at 240) | cap + overwrite | git history (`git add -f data/scrape_state/` every 2 h) | only through git | no | PRESERVED (through git only) |
| Source boards — KTC unselected format variants (G3) | **no** | `src/source_archive/store.py`; no scheduled caller (BOX: `data/source_archive/` absent) | — | — | no | — | no — KTC publishes current values only | **NOT_CAPTURED** |
| Game Day predictions | yes | `src/ros/game_day_archive.py` (create-once) + live `generations.jsonl`; `dynasty-game-day-capture` 4-hourly, `dynasty-game-day-live` every minute (BOX: 88 prediction files) | `data/game_day/predictions/`, `data/game_day/live/**` | none | post-deploy generation yes; nightly root copy **no** | append-only | no | PRESERVED (backup depends on post-deploy runs until the root copy is reinstalled) |
| Playoff / title probabilities | yes, overwritten | `src/ros/scrape.py` writes `latest_*` / `<key>_*`; `scheduled-refresh.yml` 2 h | `data/ros/sims/*.json` (BOX copy dated 2026-09-30 16:02 — refreshed by deploy, not by the runner) | overwritten each run; the dated `playoff_<iso_ts>.json` in `src/ros/__init__.py` was never built | git history only | only through git commits | no | **PARTIAL** — no model identity / inputs on the payload; box-served equality UNVERIFIED |
| Power snapshots | yes | `src/ros/power_snapshots.py` `record_snapshot` (create-once) from `src/ros/scrape.py` | `data/ros/power_snapshots/<league>/<season>/week_NN.json` (BOX: `dynasty_main` weeks 00–03) | none | git history | immutable | no | PRESERVED (`dynasty_new` Week 0 already lost, §13.3) |
| FAAB losing bids | failed claims yes | `scripts/fetch_faab_history.py` → `src/trade/faab_history.py` (`status == "failed"` with the bid); `dynasty-faab-history` daily 07:40 UTC (BOX: ran today) | `data/faab/bid_history_<leagueKey>.json` | rebuilt from the Sleeper league chain | yes | rebuildable | yes — Sleeper is host of record | PRESERVED for failed claims; **NOT_OBSERVABLE** for rival bids that were outbid or never submitted (never imputed) |
| Rookie auction sales | yes | room engine `src/auction/store.py` (command log, awards); `dynasty-auction-backup` hourly (BOX: hourly copies present); Sleeper `metadata.amount` (`src/public_league/draft.py`) | `data/auction/auction.sqlite` + `data/auction/backups/` | hourly copies | post-deploy generation yes; nightly root copy **no** | command log | Sleeper picks re-fetchable | **PARTIAL** — sales preserved; pre-sale state (board, roster context, plan) still manual (G5) |
| Pick forecasts | **no** | `src/ros/pick_projection.py`, computed per request (`src/ros/api.py`); input `data/ros/team_strength/latest.json` is un-staged from git (`scheduled-refresh.yml`) and overwritten | — | — | no | — | **no** — team strength as of the week is gone | **NOT_CAPTURED** |
| Recommendations | **no** | finder / suggestions / angle / FAAB recommend / BDVM trades computed per request; Perfect Draft plan lives in browser `localStorage`; `src/trade/faab_shadow.py` logs canonical-vs-opportunity value (not the recommended bid; ring capped at 5,000); alert state in `user_kv` keeps only the latest signal; `consensus_edge.sqlite` daily labels (BOX, not backed up) | — | — | consensus_edge **no** | — | no | **NOT_CAPTURED** (G8) |
| Analyst claims | **no** | `src/analyst/store.py` (`data/analyst_ledger.sqlite`); no producer anywhere in `scripts/`, `deploy/`, `.github/`, `server.py` (BOX: file absent) | — | — | no | — | no | **NOT_CAPTURED** |
| DFS projections / salaries | yes | `scripts/refresh_dfs_auto_slates.py` → `src/dfs/auto/refresh.py` (immutable snapshot + `pit.capture_snapshot`); `dynasty-dfs-auto-refresh` every 10 min, cadence-gated (BOX: ran today) | `data/dfs/workspace.sqlite`; raw provider pulls `data/dfs/raw/dailyfantasyfuel/*.json` overwritten | no DELETE in `src/dfs` | **no** (BOX) | immutable snapshots | no | **AT_RISK** (box loss) |
| DFS ownership / contest settlements | **no** (owner standings upload only, `src/dfs/results.py`; auto slates carry `ownershipReport: None`) | — | `data/dfs/` | — | no | — | only for contests the owner entered; window UNVERIFIED | **NOT_CAPTURED / NOT_OBSERVABLE** (Phase H "HARNESS BUILT, NO DATA") |

**Ranked Wave 1 capture units (planning; authorized as Wave 1 item 4, not implemented here).** Order is by
irrecoverability × Wave 1 dependency. Each extends an existing owner; none creates a second history system.

| Rank | Unit | Gap | Exact scope | Why this rank |
|---|---|---|---|---|
| 1 | **AL-P1** KTC Trade DB — production capture (G2) | AT_RISK | Complete the deploy chain so the box runs `main` ≥ #1586; verify `dynasty-ktc-trades` + `dynasty-market-trade-ledger` installed and firing from `systemctl`; first capture recorded (raw / new / known / resolution / unresolved / format coverage); add `backup_sqlite data/market_trades/archive.sqlite` + a retention-register addendum (`underlying_trades.sqlite` is rebuilt wholesale and stays out). No canonical value change | active loss every window turnover; Wave 1 item 2 and the TRADE loop start here |
| 2 | **AL-P2** Backup coverage (G7, extended) | AT_RISK | One change in the backup owner: `backup_sqlite` for `market_trades/archive.sqlite`, `consensus_edge.sqlite`, `source_archive/boards.sqlite` (once AL-P3 writes it) and `temporal_ledger.sqlite` **or** a written rebuildable rationale (1.49 GB; rebuilds at daily fidelity from `exports/archive/`, but its 2-hourly rows do not); `backup_dir` for `data/bdvm`, `data/dfs`, `data/robust_filter_shadow`, `data/sparse_evidence_shadow`, and AL-0's `data/learning` (A9); switch `intel` to an online `backup_sqlite`; **reinstall the root-owned copy** via `c1a-install-state-backup.yml` / `apply_hardening.sh` (operator step) and prove the nightly generation contains acquisition, auction and `game_day`; retention-register addendum. Serial owner of `deploy/backup/` (= AL-3a's backup half) | config-only; one box loss today erases BDVM editions, DFS snapshots, Consensus Edge labels and (once running) the KTC archive; the nightly job is provably stale |
| 3 | **AL-P3** KTC unselected format variants (G3) | NOT_CAPTURED | Call `source_archive.archive_board` from the KTC parse in `Dynasty Scraper.py` for the unselected `superflexValues.{base,tep,teppp}` variants (zero extra requests, one provider family per C1-SRC-01); 1QB only if the payload proves it; backup via AL-P2. Archive is never production eligibility | the paired same-provider format evidence AL-2b translators rank first in the evidence hierarchy; every day not captured is gone |
| 4 | **AL-P4** Pick forecast + team-strength snapshot | NOT_CAPTURED | Write a dated, private (outside git) per-league snapshot of the `pick_projection` output and its `team_strength` input at each scheduled refresh, first-write-wins per (league, season, week), with model identity; backed up via AL-P2 | future-pick values sit inside trade values; the team-strength state of a week cannot be rebuilt later; AL-6 needs it |
| 5 | **AL-P5** Recommendation / decision receipts (G8) | NOT_CAPTURED | After AL-0: DECISION receipts at serve time for finder, suggestions, angle, FAAB recommend and the server-side half of Perfect Draft, referencing the contract generation and inputs; private store under `data/learning`; NON-ACTION only where legitimately observable | the decision-time state is the whole of AL-13 and most of AL-8/AL-9; blocked on AL-0 |
| 6 | **AL-P6** Playoff / title forecast archive (= AL-5a capture) | PARTIAL | Dated, write-once private forecast files (league, season, week, computedAt) carrying `n_simulations`, points-model fields, code SHA and an input fingerprint; git-commit history backfilled as `nearest-prior` with unknown model version, never `exact` | git commits mitigate; model identity and inputs are what is missing |
| 7 | **AL-P7** Sharp trade retention | PARTIAL | Exempt trade movements from the 400-day `ledger.prune()`, or copy Sharp-lane trades into the append-only market archive at ledger build; intel backup made online (in AL-P2) | slow clock (≈400 days), but the TRADE loop's second lane |
| 8 | **AL-P8** Projection archive completeness (= AL-3a archive half) | PARTIAL | Observe the first `pregame_projections.json.gz` build on the box (Week 3 → at the first Week-8 prune, ≈2026-10-29) and alert if a prune runs without it; record Weeks 1–2 as already lost (never backfilled as pregame); per-source in-season ROS re-snapshot cadence | the archive is merged and fail-closed; this verifies it rather than builds it |

**Not Wave 1 (recorded, ranked later):** analyst claims (no producer — AL-15 / `C6-ANA-01`), DFS ownership and
settlements (Phase H), G4 as-known injury / news, G5 draft-time state (before the 2027 auction), G6 league
settings beyond scoring.

**Already lost, added by this pass:** Sleeper pregame weekly projections for 2026 Weeks 1–2 (the live
collector's first NFL week directory is Week 3, created 2026-09-26). Any later fetch of those weeks is a
post-hoc value, never a pregame observation.

## 14. Adaptive Learning / Continuous Improvement — roadmap pointers (2026-10-01)

Owner directive 2026-10-01 (intake: `docs/OWNER_REQUESTED_TODO.md`). Sections 1–8 arrived first; sections 9+
were *truncated in delivery, pending owner re-send* — **RESOLVED the same day:** the owner re-sent sections 9–31
plus binding continuation instructions (reconciled in plan Part III). One plan, extended in place:
`docs/research/ADAPTIVE_LEARNING_2026-09-26.md` Parts II and III. Governance owner `C10-ML-01` + P6. This table
is a pointer, not a second backlog. Roadmap order is the owner's Wave 1–4 list (plan §28); the goal it serves
first is **trade values the owner can trust**.

| Unit | Area | Canonical owner | Wave · position | Status / authorization (`EXECUTION_PLAN.md` §0) |
|---|---|---|---|---|
| AL-0 | shared learning receipt + evaluation receipt + versioned feature dictionary | `src/history/` + `src/model_registry/` | Wave 1 (item 5) | AUTHORIZED — #1597 open, round-two review gates its merge |
| AL-0b | Model Lab backend contract (internal, read-only; no UI) | `src/model_registry/` over AL-0 receipts | Wave 1 (item 5) | AUTHORIZED after AL-0 |
| AL-1a–d | Valuation Trust / source learning | Batch 3 (`F-SRC-01`, `C6-FRESH-01`) | Wave 1 (item 1, highest) | AUTHORIZED — Batch 3 B/C/E/F/G merged; AL-1a after AL-0 |
| AL-2 ops · AL-2a · AL-2a′ · AL-2a″ | completed-trade ledger in production; censuses; BROAD_CONTEXT disposition; IDP inventory | `C4-MTL-01/02`, `C1-ACQ-01`, `src/sharp/` | Wave 1 (item 2) | AL-2a DONE (#1595); production capture NOT RUNNING (box at `ed48d54ab`); rest AUTHORIZED in campaign order |
| AL-2b0 · AL-2b · AL-2c | translator readiness table; ≤ 1 preregistered shadow translator; latent price (shadow) | `C4-MTL-03` | Wave 1 (item 3) | AUTHORIZED after the accumulated census |
| AL-P1…AL-P8 | perishable capture gaps (§13.4) | each stream's owner | Wave 1 (item 4) | AUTHORIZED — ranked; none implemented yet |
| AL-3a · AL-3b | projection archive completeness + `data/bdvm/` backup; scorecard vs equal-family champion | `C5-BDVM-01`, `C5-ROS-01`, `C5-GD-02` | Wave 1 (item 6) | AUTHORIZED |
| AL-3c · AL-3d | learned ensemble challengers; BDVM calibration (= Batch 3 J2) | `C5-ROS-01`, `C5-BDVM-01` | Wave 2 (7, 8) | AUTHORIZED when dependency-ready |
| AL-4 | Game Day calibration | `C5-GD-01/02` | Wave 2 (9) | AUTHORIZED when dependency-ready |
| AL-5 | playoff / title calibration (capture half = AL-P6) | `C5-PLAY-01` | Wave 2 (10) | AUTHORIZED when dependency-ready; D2/D3 owner decisions open |
| AL-6 · AL-7 | future-pick distribution + empirical discount; Power predictive components (descriptive contract untouched) | `C1-PICK-03`; `C5-POW-01` | Wave 2 (11, 12) | AUTHORIZED when dependency-ready |
| AL-8 … AL-13 | FAAB clearing price; rookie auction; Sharp Score validation; Manager Scout; roster utility distributions; trade recommendation evaluation | `C4-FAAB-01/02`; `C7-DRAFT-02/03`; `C4-SHARP-01`; `C6-MGR-01`; `C2-STR-01`/`C2-REPL-01`; `C7-DESK-01` | Wave 3 | AUTHORIZED when dependency-ready |
| AL-14 … AL-19 | player development; analyst reliability; DFS → `docs/dfs/ROADMAP.md` Phase H (no new system); alerts (actionability, never clicks); adaptive acquisition; personalized models | `C6-UPP-01`; `C6-ANA-01`; `src/dfs/`; `C7-ALERT-01`; freshness owners; — | Wave 4 | AUTHORIZED when dependency-ready |

Authorization covers implementation, shadow challengers and capture — never promotion of an unvalidated model,
autonomous trades / waivers / DFS entries, hidden recommendation changes, or new paid data. Completion standard:
four closed loops (SOURCE, TRADE, PROJECTION, MODEL GOVERNANCE) on real data (plan §34). Parallel class: AL-0 is
`SERIAL_CANONICAL_OWNER` on `src/model_registry/`; AL-P2 / AL-3a are the serial owner of `deploy/backup/`; AL-P3
owns the KTC parse in `Dynasty Scraper.py`; `data_contract.py` keeps one writer. UI: none until measured
evidence exists; a later Lane 6 surface carries user-facing explanation (plan §31) and the Model Lab stays
internal (plan §33).

---

**Related:** issue #1412 · `docs/OWNER_REQUESTED_TODO.md` · `docs/PLANNING_DOCUMENT_STATUS.md` · `docs/MASTER_PRODUCT_PLAN.md` · `docs/EXECUTION_PLAN.md` · `docs/WORK_CLAIMS.md`.
