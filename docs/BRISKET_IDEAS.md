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
| Playoff / title odds | `data/ros/sims/*.json`, rewritten every 2 h by the refresh runner; each commit in git history (155 commits to `latest_playoff.json` in 30 days). Runner-computed; equality with the box-served payload UNVERIFIED. |
| ROS / redraft source boards | `data/ros/sources/` + `data/ros/aggregate/history/`, git-tracked every 2 h. |
| Trending adds; sharp cohort market | C1-RET-05 + hourly `dynasty-trending-history-refresh`; `data/intel/` ledger (daily crawls, sharp transactions 4×/day), backed up as a directory. |
| playerctx; nflverse stats, PBP, depth charts | C1-RET-08 weekly; nflverse is an external historical archive (re-fetchable, not perishable; stat corrections go through Game Day's corrections path). |

### 13.2 Gaps — minimum capture path

| # | Stream | Status | Owner / evidence | What is lost | Minimum capture path (existing owner) | Storage | Unblocks |
|---|---|---|---|---|---|---|---|
| **G1** | Pregame weekly projections (Sleeper, the only live weekly family) | **IMPLEMENTED — merged 2026-09-29, PR #1525** (`e1f4dce4c`, `882c4558a`: the last pre-kickoff row per player is archived to `pregame_projections.json.gz` before the prune, fail-closed, backed up under `data/game_day/`); production observation UNVERIFIED. Original finding: PARTIAL — active loss clock | `game_day_live.py` logs every `sleeper_weekly_projections` fetch append-only, then `prune_retention` deletes each league-week's `observations/` after `RAW_RETENTION_WEEKS = 4`, on every collector tick. The 14-day backup rotation does not extend it | Full-NFL raw stat lines, unrostered players and intra-week movement up to kickoff. Week 1 logs are deleted at the first tick of Week 6 (≈2026-10-13, depends on Sleeper's week flip), then one week per week. Generations keep only league-scored baselines for rostered players | Exempt `_nfl/<season>/week_N/observations/sleeper_weekly_projections.*` from `prune_retention`, or first write the kickoff-locked subset (`matchup_intel._prune_weekly_history`, already the "last pre-kickoff read" rule) beside `generations.jsonl`. One owner, one path; no new store | UNVERIFIED — measure `du` on the box before choosing between full log and locked subset | #854 / C5-ROS-01 projection-family scorecards (Adaptive Learning candidate 2); C5-GD calibration baseline provenance; MVP xWAR no-lookahead for waiver/unrostered players |
| **G2** | KTC Trade Database (real market trades) | **IN FLIGHT — PR #1586** (Batch 3 I: append-only raw archive + 30-min timer; Adaptive Learning AL-2). Original finding: NOT PRESERVED | C4-MTL-02 ABSENT; producer retired 2026-08-18; ~200-entry rolling window (measured that day) | Every trade that scrolls out of the window, permanently | Accumulator on the C1-RET-01 pattern (`fetch_crowd_faab.py`: dedupe by KTC row `id`, merge, never truncate) under `data/`, added to the backup set and the retention register. Capture only, no consumer, never a vote | Small (≈200 rows per window); turnover rate UNVERIFIED, so it sets the cadence | C4-MTL-01/03 comparable trades, C7-DESK-01 real-trade evidence, C7-AI-03 liquidity, market calibration. Needs endpoint-level intake confirmation; whether the 2026-09-25 source attestation covers this endpoint is UNVERIFIED |
| **G3** | KTC non-selected format variants (SF base / TE+ / TE+++; 1QB UNVERIFIED) | **NOT PRESERVED** | The scraper already receives `superflexValues.{base,tep,tepp,teppp}` in the payload it parses (`Dynasty Scraper.py` ~L1835–1941) and keeps the selected mode. C1-SRC-01's `src/source_archive/` has one caller, `scripts/fetch_dynasty_nerds_idp.py`, which is not scheduled | Same-day paired format evidence. KTC publishes current values only | Call `source_archive.archive_board` from the KTC parse for the unselected variants: zero extra requests, one provider family (the C1-SRC-01 rule). Add `data/source_archive/boards.sqlite` to the backup | ≈4 × one board per scrape; UNVERIFIED | #809 multi-format archive, TE-basis / format-curve calibration. Archive is never production eligibility |
| **G4** | As-known injury / news state | **PARTIAL** | `refresh_injury_feed.py` (4-hourly, ESPN) overwrites `injuries_prior.json` and keeps only transition events in `data/bdvm/events/<season>.json` (not backed up). Sleeper players DB (`injury_status`, practice participation) is overwritten daily. `/api/news` items are in-memory, 7-day window, never persisted; BDVM news events prune at 90 d | Status as known at kickoff and at decision time; which headlines existed when. Official weekly designations stay recoverable from nflverse (2026 in-season availability UNVERIFIED) | (a) have the injury refresh append each fetched snapshot to a dated append-only log instead of only overwriting the prior; (b) persist `/api/news` item metadata (id, provider, published/fetched time, headline, URL, matched player ids; no article bodies) at the aggregator's refresh | Small: status deltas plus headline metadata | Injury-aware Game Day / MVP retrospectives, C7-ALERT-01 / C6-ANA-01 signal evaluation, FAAB opportunity backtests |
| **G5** | Draft-time state (board + roster context at draft start) | **PARTIAL** | C7-DRAFT-02 (`RET`): `backtest_perfect_draft.py --record-snapshot` exists and is manual only. Board values are recoverable as `nearest-prior` (≤ one scrape) from the temporal ledger; roster context, cut ladder, waiver levels and the plan are not | The Perfect Draft backtest inputs. Next exposure is the 2027 rookie auction, so not urgent now | Timer-driven `record_snapshot` when the league's Sleeper draft reports `pre_draft` with a near start time, first capture stands (the `game_day_capture` pattern). Must be live before the 2027 draft | Small | Perfect Draft backtest (currently `BLOCKED`, exit 2), live-auction calibration |
| **G6** | League settings beyond the scoring card | **PARTIAL** | C1-RET-04 records `scoring_settings` only. `roster_positions` and `settings` (playoff teams, median game, waiver budget, taxi/IR slots) live in the overwritten `public_league/snapshot.json`. Completed seasons are re-fetchable via the league chain | Mid-season commissioner changes | Observe a content-addressed settings payload in `evidence.sqlite` at the same `write_scoring_snapshot` site (the C1-RET-04 observation model, unobserved stays unobserved) | Negligible | Median-game / playoff methodology per week, roster-capacity history, trade replay legality at the time |
| **G7** | Backup coverage of existing append-only stores | **PARTIAL** | Not in `riskit-state-backup.sh`: `data/temporal_ledger.sqlite`, `data/consensus_edge.sqlite`, `data/source_archive/boards.sqlite`, `data/bdvm/` (dated projection snapshots incl. Mike Clay, plus events) | Box loss erases them. The ledger rebuilds at daily fidelity from git-tracked `exports/archive/` (idempotent backfill); Clay snapshots and Consensus Edge label history do not | Add `backup_sqlite` / `backup_dir` lines in the one backup owner, plus a retention-register addendum (the 2026-09-04 `data/game_day/` precedent) | Size UNVERIFIED | Durability for C1-HIST-01, C6-FRESH, BDVM and Consensus Edge evaluation |
| G8 | Recommendations and decisions as served (finder, suggestions, FAAB, Perfect Draft plan) | NOT PRESERVED | Already recorded as `ADAPTIVE_LEARNING_2026-09-26.md` §6 item 8 and R14 CANDIDATE; since 2026-10-01 the DECISION / NON-ACTION receipt kinds are defined there (§19.1) and capture stays a separately sequenced unit | — | No new record; pointer only | — | C7-DESK-01, C10-ML-01 |

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


## 14. Adaptive Learning / Continuous Improvement — roadmap pointers (2026-10-01)

Owner directive 2026-10-01 (intake: `docs/OWNER_REQUESTED_TODO.md`; sections 9+ truncated in delivery,
pending owner re-send). One plan, extended in place: `docs/research/ADAPTIVE_LEARNING_2026-09-26.md` Part II.
Governance owner `C10-ML-01` + P6. This table is a pointer, not a second backlog.

| Unit | Area | Canonical owner | Position | Authorization (`EXECUTION_PLAN.md` §0) |
|---|---|---|---|---|
| AL-0 | shared learning receipt + evaluation receipt + versioned feature dictionary | `src/history/` + `src/model_registry/` | NOW (after #1588) | AUTHORIZED — first foundation unit |
| AL-1 | Valuation Trust / source learning | Batch 3 (`F-SRC-01`, `C6-FRESH-01`) | NOW (highest) | AUTHORIZED |
| AL-2 | completed-trade / IDP market, format-aware latent price (shadow) | `C4-MTL-01/02/03`, `C1-ACQ-01` | NOW (after #1586) | AUTHORIZED |
| AL-3 | BDVM + projection learning | `C5-BDVM-01`, `C5-ROS-01`, `C5-GD-02` | NOW (archive/eval) / NEXT | AUTHORIZED |
| AL-4 | Game Day calibration | `C5-GD-01/02` | NEXT | AUTHORIZED when dependency-ready |
| AL-5 | playoff / title calibration | `C5-PLAY-01` | NEXT | AUTHORIZED when dependency-ready; D2/D3 owner decisions open |

Authorization covers implementation, never promotion of an unvalidated model. Parallel class: AL-0 is
`SERIAL_CANONICAL_OWNER` on `src/model_registry/` (behind #1588); AL-2a waits on #1586; AL-3a is the serial owner of
`deploy/backup/` (AL-0's A9 backup line lands through or after AL-3a's claim). UI: none until measured evidence exists; a later Lane 6 "Model Evidence" surface may report
sample size, last evaluation cutoff and calibration only.

---

**Related:** issue #1412 · `docs/OWNER_REQUESTED_TODO.md` · `docs/PLANNING_DOCUMENT_STATUS.md` · `docs/MASTER_PRODUCT_PLAN.md` · `docs/EXECUTION_PLAN.md` · `docs/WORK_CLAIMS.md`.
