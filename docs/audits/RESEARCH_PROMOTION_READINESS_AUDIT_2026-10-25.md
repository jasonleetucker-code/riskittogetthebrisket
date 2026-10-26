# Research and Promotion-Readiness Audit, 2026-10-25

**Status:** read-only audit report. Nothing in the repository, configuration, feature flags or values was changed.  
**Generated:** 2026-10-26T13:14:41Z on a branch cut from `origin/main` `f0f5eb2ce`; PR and run states were re-checked with `gh` at generation time.  
**Companion inventory:** `docs/audits/RESEARCH_PROMOTION_READINESS_AUDIT_2026-10-25.json` (all 125 assessments unchanged, plus the 39 structured defect rows).  
**Product authority:** none. This report records evidence; it authorizes nothing. `docs/EXECUTION_PLAN.md` remains the only implementation-authorization record, and every activation, promotion or served-value change named below stays owner-reserved.

## 1. Summary

### What was audited

Every research initiative, shadow challenger, promotion candidate and data collector that the planning records and the live system show: **87 initiatives and 38 collectors, 125 items in all**. Each item carries an operational status, an evidence status, the highest stage that is both verified and authorized, whether a decision is possible now, and a group (1 to 5, defined in the method appendix). The count was verified: every id is present once, none is missing, none is duplicated, and **no item is marked NOT_ASSESSED** (collector ids are `COL-nnn` in the catalog and `RPA-COL-nnn` in the assessments, the same 38).

Evidence came from git, `gh`, public requests to chaseupside.com and read-only sessions on the production box, mostly on 2026-10-25 and 2026-10-26. Where an item's text pre-dates a later change (for example a PR that has since merged), sections 9.5, 10 and 11 say so. The excluded Chase Upside MCP integration (PR #1921) was not assessed.

### Counts

**By group**

| Group | Meaning | Items |
|---|---|---|
| 1 | Owner decisions possible now | 21 |
| 2 | Active engineering | 44 |
| 3 | Collecting, waiting on a sample or a date | 31 |
| 4 | Blocked | 22 |
| 5 | Retire or superseded | 7 |

**By category** (initiatives: DRF draft, GOV governance, LGI league intelligence, OPS operations, SRC sources, TRD trade, VAL valuation; COL collectors)

| Category | Items |
|---|---|
| COL | 38 |
| DRF | 6 |
| GOV | 8 |
| LGI | 19 |
| OPS | 12 |
| SRC | 11 |
| TRD | 13 |
| VAL | 18 |

**By operational status**

| Operational status | Items |
|---|---|
| COLLECTING_ACTIVE | 34 |
| COLLECTING_BROKEN | 5 |
| COLLECTING_STALE | 4 |
| DORMANT_IMPLEMENTED | 14 |
| IMPLEMENTATION_ACTIVE | 8 |
| LIVE | 4 |
| NOT_STARTED | 14 |
| RETIRED | 1 |
| SHADOW_NOT_RUNNING | 6 |
| SHADOW_RUNNING | 8 |
| SUPERSEDED | 2 |
| WAITING_ON_DEPENDENCY | 10 |
| WAITING_ON_OWNER | 15 |

**By evidence status**

| Evidence status | Items |
|---|---|
| BLOCKED | 5 |
| ENGINEERING_NOT_READY | 18 |
| EVIDENCE_SUPPORTS_ADVANCEMENT | 2 |
| EVIDENCE_SUPPORTS_REJECTION | 2 |
| INSUFFICIENT_EVIDENCE | 18 |
| NEEDS_METHODOLOGY_REVISION | 4 |
| NEEDS_MORE_DATA | 15 |
| NEEDS_PREREGISTRATION | 17 |
| NOT_A_PROMOTION_CANDIDATE | 25 |
| OWNER_APPROVAL_REQUIRED | 15 |
| READY_FOR_DECISION | 4 |

**By priority**: P0 1, P1 23, P2 66, P3 35.  
**By highest verified and authorized stage (0 to 6)**: stage 0: 9, stage 1: 16, stage 2: 5, stage 3: 13, stage 4: 37, stage 5: 7, stage 6: 38.

### Defects found

39 defect rows (section 2). By severity: critical 0, high 10, medium 20, low 9. By status: CONFIRMED 33, SUSPECTED 4, UNRESOLVED 2. **No finding meets the critical bar** (a confirmed wrong served value or exposure with no compensating control). The closest are the scheduled-refresh false success, the unpatched auction-room security fixes, the critical dependency alerts and the league-config propagation defects; each has a compensating control or is not yet shown to be reachable.

### Top 10 verified defects

Ranked by what they can do to a decision or to served data. All ten are CONFIRMED.

| # | Finding | Severity | Defect | Owner or PR (first sentence) |
|---|---|---|---|---|
| 1 | RPA-F-001 | high | Scheduled data refresh reports success while its browser fetchers produce nothing | #1939 merged (manual post-pin run verified; scheduled run pending); #1953 draft |
| 2 | RPA-F-002 | high | Thirteen league-config propagation defects, including cross-league leakage and a manual multiplier that moves canonical values | #1948 draft (tests); #1951 draft fixes 7 of 13; #1843 open |
| 3 | RPA-F-003 | high | The committed league-rules snapshot is 21 scoring keys behind the live Sleeper card; the dynasty_new roster size also disagrees | #1843 and #1931 open; refresh needs owner approval |
| 4 | RPA-F-004 | high | The ESPN injury feed parses 0 of 800 entries and reports it as 'no active injuries' | #1952 draft |
| 5 | RPA-F-005 | high | The Sharp transaction crawl fetches zero leagues in 13 of 28 runs because 404 leagues trip the shared Sleeper breaker | #1957 draft |
| 6 | RPA-F-006 | high | Independent-audit security and money fixes for the Rookie Auction Room are not on main while the room is live in mock mode | #1950 draft (supersedes #1533) |
| 7 | RPA-F-007 | high | 111 open Dependabot alerts, 12 of them critical, and the three PRs that would clear 100 of them cannot go green | #1955 draft (supersedes #1855, #1895, #1896) |
| 8 | RPA-F-008 | high | Four nflverse scorer defects bias the live BDVM in-season fundamentals, mostly for IDP | #1931 open; #1938 draft (awaits owner) |
| 9 | RPA-F-011 | medium | Public /league has a 44-second cold path and the production smoke monitor fails intermittently on it | None (unclaimed) |
| 10 | RPA-F-023 | medium | Owner-facing decision and status records state facts that production or code contradicts | None (records pass needed) |

Also rated high but **not verified** (status UNRESOLVED): RPA-F-009, backup coverage of the irreplaceable 2.25 GB temporal ledger cannot be confirmed, and the health stamp reads the wrong directory; RPA-F-010, the 2026-10-22/23 production degradation (about 24 hours) has no established root cause and the evidence is gone.

### What the owner should know first

1. The data refresh fix (#1939) is merged and **partly verified**. No scheduled run had fired since the merge (re-checked 13:13Z on 2026-10-26), but a manually dispatched run on ubuntu-24.04 at 12:46Z installed Chromium and advanced the KTC, IDPTC and DraftSharks stamps to 12:50-12:53Z. Until a scheduled run does the same, treat GitHub-side evidence from 2026-10-25 12:03Z to 2026-10-26 12:50Z as built on stale browser sources.
2. 21 items are waiting on you now (section 3), several time-sensitive: the rookie-draft median-game rule (before the regular season ends, about mid-December), the roster-12 cutover for week-7 scoring, and the data-capture cadence.
3. More than twenty planning and ledger records say things production or code contradicts (D4 shown ON, a challenger "not yet", code that "does not exist"). They can mislead a decision; section 10 lists the corrections.
4. Several collectors and gates report green while measuring nothing (scheduled refresh, Sharp production smoke, the BDVM projection unit, injury feed). Fixes are in draft PRs #1952, #1953, #1957, #1958 and #1959.

## 2. Verified defects that can mislead decisions or data quality

Each row is one finding. The table gives the headline fields; the detail below it carries the rest of the twelve required fields, and `findings[]` in the JSON carries every field as one record. Status is taken from the evidence prefixes in the source items: **CONFIRMED** (a VERIFIED line reproduces the defect), **SUSPECTED** (rests on INFERRED lines), **UNRESOLVED** (UNVERIFIED with the allowed access). Severity uses the rubric in the method appendix. "Fix authorized?" is read from each item's `qC_authorized`; "Activation requires owner approval?" says whether the fix, or a change it enables, moves a served value or touches an owner-reserved surface.

| Finding | Severity | Status | Affected subsystem | Defect | Items | Owner approval? |
|---|---|---|---|---|---|---|
| RPA-F-001 | high | CONFIRMED | CI / source ingestion (scheduled-refresh.yml) | Scheduled data refresh reports success while its browser fetchers produce nothing | RPA-COL-001, RPA-SRC-006 | no |
| RPA-F-002 | high | CONFIRMED | League intelligence / API scoping | Thirteen league-config propagation defects, including cross-league leakage and a manual multiplier that moves canonical values | RPA-LGI-001 | yes |
| RPA-F-003 | high | CONFIRMED | League intelligence / scoring configuration | The committed league-rules snapshot is 21 scoring keys behind the live Sleeper card; the dynasty_new roster size also disagrees | RPA-LGI-001, RPA-LGI-008 | yes |
| RPA-F-004 | high | CONFIRMED | Injury / availability collector | The ESPN injury feed parses 0 of 800 entries and reports it as 'no active injuries' | RPA-LGI-016, RPA-COL-019 | yes |
| RPA-F-005 | high | CONFIRMED | Sharp cohort / completed-trade ledger input | The Sharp transaction crawl fetches zero leagues in 13 of 28 runs because 404 leagues trip the shared Sleeper breaker | RPA-COL-017, RPA-COL-016 | no |
| RPA-F-006 | high | CONFIRMED | Rookie Auction Room | Independent-audit security and money fixes for the Rookie Auction Room are not on main while the room is live in mock mode | RPA-DRF-003 | no |
| RPA-F-007 | high | CONFIRMED | Dependencies / supply chain | 111 open Dependabot alerts, 12 of them critical, and the three PRs that would clear 100 of them cannot go green | RPA-OPS-010 | no |
| RPA-F-008 | high | CONFIRMED | Scoring / BDVM in-season path | Four nflverse scorer defects bias the live BDVM in-season fundamentals, mostly for IDP | RPA-VAL-013, RPA-LGI-005 | yes |
| RPA-F-009 | high | UNRESOLVED | Backups / retention | Backup coverage of the irreplaceable 2.25 GB temporal ledger cannot be confirmed, and the health stamp reads the wrong directory | RPA-COL-032, RPA-COL-026, RPA-COL-024, RPA-COL-025 | yes |
| RPA-F-010 | high | UNRESOLVED | Production operations | The 2026-10-22/23 production degradation (about 24 hours) has no established root cause and the evidence is gone | RPA-OPS-006, RPA-COL-034, RPA-COL-026 | yes |
| RPA-F-011 | medium | CONFIRMED | Public site performance / monitors | Public /league has a 44-second cold path and the production smoke monitor fails intermittently on it | RPA-OPS-002, RPA-COL-034 | no |
| RPA-F-012 | medium | CONFIRMED | CI / E2E | The nightly E2E Safety Net was red four nights running on deterministic specs | RPA-OPS-003, RPA-COL-034 | no |
| RPA-F-013 | medium | CONFIRMED | Source freshness / IDP valuation | IDP vote evidence is thinning: four of five IDP vendor feeds have static content, and IDPTC is the only anchor with no rehabilitation entry | RPA-SRC-004, RPA-SRC-002, RPA-SRC-003, RPA-SRC-005 | no |
| RPA-F-014 | medium | SUSPECTED | Source freshness / confidence | Fetch-success stamps for KTC, IDPTC and DraftSharks have a single writer (the GitHub runner) and feed the confidence freshness axis | RPA-SRC-006 | yes |
| RPA-F-015 | medium | CONFIRMED | Valuation display / Terminal | Rank-form reconstruction constants have drifted 3x to 8x past budget, and the Terminal team-value chart always uses them | RPA-VAL-011, RPA-COL-007 | no |
| RPA-F-016 | medium | CONFIRMED | BDVM projections | BDVM's IDP Show projection feed has never produced a record, and the weekly unit still reports success | RPA-COL-027 | yes |
| RPA-F-017 | medium | CONFIRMED | Monitoring (/api/health) | /api/health reports the DLF session as 96.6 days old with 0.0 days remaining; it reads a dead July copy | RPA-COL-012 | no |
| RPA-F-018 | medium | CONFIRMED | DLF collector | The DLF fetcher exited clean after a fetch timeout, and DLF's Value column is unavailable, so DLF votes as rank only | RPA-COL-012 | no |
| RPA-F-019 | medium | CONFIRMED | Sharp production verification | The Sharp production gate has never measured anything, and its green runs read as verification | RPA-OPS-009, RPA-COL-036 | yes |
| RPA-F-020 | medium | CONFIRMED | Frontend settings | Settings still offers 'Value basis: My league' and says it is the only setting that changes the numbers; the lens was withdrawn | RPA-VAL-018 | no |
| RPA-F-021 | medium | CONFIRMED | Simulations (playoff odds, Game Day, forecast archive) | Every production best-ball simulation runs on fallback points-model constants because the calibrated artifact was never built | RPA-LGI-008, RPA-LGI-006, RPA-LGI-007 | yes |
| RPA-F-022 | medium | CONFIRMED | Roster capacity / forced drops | The incumbent cut ladder breaks ties alphabetically by asset name, which changes forced-drop charges and Perfect Draft cut order | RPA-TRD-004, RPA-TRD-007 | yes |
| RPA-F-023 | medium | CONFIRMED | Planning and ledger records | Owner-facing decision and status records state facts that production or code contradicts | RPA-VAL-003, RPA-VAL-004, RPA-LGI-006, RPA-GOV-003, RPA-LGI-009, RPA-TRD-006 | no |
| RPA-F-024 | medium | CONFIRMED | Feature flags / deploy gate | Nine owner-reserved flags (and three closed-challenger flags) are default OFF but not protected by the deploy-time hold | RPA-OPS-007, RPA-VAL-005, RPA-TRD-007, RPA-TRD-008 | no |
| RPA-F-025 | medium | CONFIRMED | Repository governance | The main branch ruleset has no required status checks or reviews | RPA-GOV-001 | yes |
| RPA-F-026 | medium | CONFIRMED | Repository hygiene | Work that exists only in local worktrees or unpushed branches could be lost | RPA-GOV-008, RPA-SRC-010, RPA-OPS-011, RPA-LGI-011, RPA-DRF-003 | no |
| RPA-F-027 | medium | CONFIRMED | ROS rankings aggregate | The ROS aggregate counts a 12-day-old unchanged body as 'ok', and an orphan source file sits beside it | RPA-COL-031 | no |
| RPA-F-028 | medium | CONFIRMED | Retention monitoring | retention-health has been red on 26 of its last 40 daily runs, including a 22-day streak nobody examined | RPA-COL-032 | no |
| RPA-F-029 | medium | CONFIRMED | Shadow evidence / Model Lab | Several shadow recorders and scorecards run (or are merged) with no evaluator, so their status panels read as monitoring | RPA-VAL-006, RPA-VAL-007, RPA-VAL-016, RPA-COL-003, RPA-COL-004, RPA-COL-005, RPA-LGI-004, RPA-LGI-013 | no |
| RPA-F-030 | medium | SUSPECTED | Completed-trade market ledger | The market-trade ledger grows about 27 MiB a day toward a 2 GiB memory ceiling, and no alert fires on a missed report day | RPA-COL-015, RPA-OPS-001, RPA-TRD-011 | no |
| RPA-F-031 | low | CONFIRMED | Planning records (rank-digest capture, #804) | docs/lane4/LANE4_804_CAPTURE_CADENCE_DECISION.md says the capture unit shipped in #921; #921 was closed unmerged | RPA-SRC-009 | no |
| RPA-F-032 | low | CONFIRMED | Forecast and news archives | The forecast archive never established two identity fields, and 10.9% of news mentions have no Sleeper id | RPA-COL-022 | no |
| RPA-F-033 | low | CONFIRMED | Weekly narratives | The Week 6 narrative recaps were never exported and nothing retries a failed Tuesday run | RPA-COL-037 | no |
| RPA-F-034 | low | CONFIRMED | Agent infrastructure | A Codex 'Brisket Orchestrator' automation is ACTIVE daily and points at the archived OneDrive copy | RPA-GOV-007, RPA-COL-038 | yes |
| RPA-F-035 | low | CONFIRMED | Public waiver-compare page | Waiver-compare settings labels show mojibake ('Dynasty Â· Crowd+Trades') | RPA-LGI-018 | no |
| RPA-F-036 | low | SUSPECTED | Player identity | Justin Madubuike is unresolved by the served identity policy while CANONICAL_V2 resolves him to 6818 | RPA-SRC-007, RPA-COL-009 | yes |
| RPA-F-037 | low | SUSPECTED | FAAB market evidence | The KTC crowd-FAAB freshness gate keys on fetch time, so a frozen feed would stay 'fresh' for seven days | RPA-COL-029 | no |
| RPA-F-038 | low | CONFIRMED | Hill autopilot / repository churn | Four of 32 Hill refit runs lost their evidence to a push race, and bot commits add churn to main | RPA-COL-002, RPA-VAL-008, RPA-COL-016 | no |
| RPA-F-039 | low | CONFIRMED | Feature flags (documentation in code) | Two feature-flag comments describe the opposite of the live state | RPA-LGI-005, RPA-LGI-013, RPA-OPS-007 | no |

### RPA-F-001 (high, CONFIRMED) Scheduled data refresh reports success while its browser fetchers produce nothing

- **Affected subsystem:** CI / source ingestion (scheduled-refresh.yml)
- **Reproduction evidence:** gh run view 40290067631 (2026-10-26T08:07Z): 'Playwright does not support chromium on ubuntu26.04-x64' (hidden by `2>/dev/null || true`), then 'BrowserType.launch: Executable doesn't exist'; the run still concluded success. 32 of 32 scheduled runs in 7 days concluded success; four runs fall after the runner label moved to ubuntu-26.04 (10-25 16:49Z and 21:14Z, 10-26 00:43Z and 08:07Z; only the 08:07Z log was read directly).
- **Data source and observed timestamps:** gh run list; production /api/status source_health at ~2026-10-26T12:05Z (ktc and idpTradeCalc 24.02 h old, draftSharks 23.98 h); stamps ktc/ktcSfTep/idpTradeCalc 2026-10-25T12:03:37Z and draftSharks 12:06:15Z; /api/health at the same moment said data_stale false, data_age_hours 0.4. Box scrape last_scrape 2026-10-26T11:40:28Z. Cadence: 32 runs in 7 days (4.6/day) against 12/day declared.
- **Status:** CONFIRMED
- **Existing owner or PR:** #1939 MERGED 2026-10-26T11:32:46Z (pin to ubuntu-24.04, loud non-fatal install warning, IDP staleness report). Post-merge verification is PARTIAL: no scheduled run has fired since the merge (latest scheduled run 2026-10-26T08:07:07Z, re-checked at 13:13Z), but a manually dispatched run (40325142841, workflow_dispatch, created 12:46:40Z, Image ubuntu-24.04) installed Chromium, concluded success and advanced the stamps on origin/main: ktc, ktcSfTep and idpTradeCalc to 2026-10-26T12:50:16Z and draftSharks and draftSharksIdp to 12:52:55Z (commit e8b8788f3). The first scheduled post-pin run is still pending. #1953 draft (signals for unstamped and preserved browser sources, plus the draftsharks-diagnostic pin). Items RPA-COL-001, RPA-SRC-006.
- **Fix authorized?** Yes. Standing production infrastructure; #1939 merged under the routine-merge policy. A hard freshness guard is a workflow change that needs a work claim; no owner decision found.
- **Recommended repair:** Confirm the next scheduled run (not only the manual one) keeps advancing the stamps. Add a content-level guard (fail or open an issue when a browser source is not rewritten for N consecutive runs). Pin the other ubuntu-latest Playwright workflows (e2e, prod-e2e-smoke, v1-authenticated-verification).
- **Potential impact:** Served KTC and IDPTC values stay live because the box runs its own scrape, but the fetch stamps feed /api/status and the confidence freshness axis, and the GitHub-side evidence (identity-capture uploads, the committed dual-read copy, Hill refit inputs, shadow ledgers) was built on restored last-good rows. DraftSharks has no verified box path, and its content clock moved at 16:50Z (11 rows) while its stamp did not, which is unexplained.
- **Dependencies:** First scheduled post-pin run; feeds RPA-COL-002, RPA-COL-009, RPA-COL-010 and RPA-SRC-006.
- **Activation requires owner approval?** No

### RPA-F-002 (high, CONFIRMED) Thirteen league-config propagation defects, including cross-league leakage and a manual multiplier that moves canonical values

- **Affected subsystem:** League intelligence / API scoping
- **Reproduction evidence:** Draft PR #1948 ships a 73-row propagation matrix and tests/league_intel/test_league_config_metamorphic.py (38 passing relations, 13 strict xfails, one per defect). Reported examples: /api/intel/leads crosses leagues; /api/movers has no scoring gate; a manual tep_multiplier still moves rankDerivedValue on 110 of 1,107 rows; the gameplan scoring-fit result is memoised by leagueKey forever. The audit read these numbers from the PR bodies and the committed reconciliation JSON; it did not re-run the tests.
- **Data source and observed timestamps:** PR #1948 and #1843 bodies and evidence files, read 2026-10-26; live dynasty_main rules read at 2026-10-26T08:25:58Z.
- **Status:** CONFIRMED
- **Existing owner or PR:** #1948 draft (matrix and tests). #1951 draft repairs defects 01/03/04/06/09/10/11 (7 of 13). #1843 open (audit, CI running). Item RPA-LGI-001.
- **Fix authorized?** Partly. The read-only audit and test work is authorized (EXECUTION_PLAN section 0, 2026-10-19 later; 2026-10-25 read-only audit). Any served-config or served-value change is owner-reserved.
- **Recommended repair:** Land #1843 and #1948, then #1951 after review; file the six remaining defects; give the manual tep_multiplier path an explicit owner decision.
- **Potential impact:** Wrong-league data on two routes and a manual input that changes the canonical board value of 110 rows. Two leagues share a scoring-profile label but differ in scoring, so this is the failure mode the scoring-fingerprint rule exists to prevent.
- **Dependencies:** #1843 L2 green; #1948 then #1951 stack; owner decision on tep_multiplier.
- **Activation requires owner approval?** Yes

### RPA-F-003 (high, CONFIRMED) The committed league-rules snapshot is 21 scoring keys behind the live Sleeper card; the dynasty_new roster size also disagrees

- **Affected subsystem:** League intelligence / scoring configuration
- **Reproduction evidence:** Live dynasty_main fingerprint sf1:9e51824690d091f9 (148 keys) against a config/league_intel snapshot dated 2026-07-26: 21 rate keys differ plus 7 zero keys. The export archive brackets the live edit to 2026-08-18T23:02Z..2026-08-19T23:03Z, before any scored 2026 week. refresh_snapshot is unscheduled. dynasty_new registry rosterSize is 27 against live roster_positions 24.
- **Data source and observed timestamps:** Live Sleeper league GET 2026-10-26T08:25:58Z (PR #1843 evidence files); export archive; config/league_intel.
- **Status:** CONFIRMED
- **Existing owner or PR:** #1843 open (documents it); #1931 open (awarded-week reconciliation). Item RPA-LGI-001; also RPA-LGI-008.
- **Fix authorized?** No. Refreshing config/league_intel is a served-config change (owner-reserved list, EXECUTION_PLAN 2026-10-25), so the audit deliberately left it alone.
- **Recommended repair:** Owner-approved PR that refreshes the snapshot from the live card, a scheduled refresh_snapshot with a status stamp, and a registry fix for dynasty_new rosterSize (dynasty_new is out of scope per the owner's 2026-10-18 correction, so a tracked divergence note may be enough).
- **Potential impact:** The exact scorer loads this card by default, so any consumer that reads it without being handed the live card scores 2026 under July rules. A calibration refit must be handed the live card explicitly.
- **Dependencies:** Owner approval; #1843 merge.
- **Activation requires owner approval?** Yes

### RPA-F-004 (high, CONFIRMED) The ESPN injury feed parses 0 of 800 entries and reports it as 'no active injuries'

- **Affected subsystem:** Injury / availability collector
- **Reproduction evidence:** Public ESPN injuries endpoint fetched 2026-10-26T09:09Z returns 800 entries across 32 teams (Out 178, Injured Reserve 50, Questionable 44, Doubtful 2, Suspension 1, Active 525). 800 of 800 lack athlete.id, so _parse_espn_payload (injury_feed.py:251) skips them; the origin/main parser returns 0 parsed while payload_shape_error is None. Box journal: 42 of 42 runs in 7 days (180 lines over 40 days) logged 'no active injuries returned (fetch proven)'; injuries_prior.json is 2 bytes. The separate injury-return-evidence path reads the same ESPN data and finds 513 OUT athletes (510 players).
- **Data source and observed timestamps:** Parser run against the live payload 2026-10-26T09:09Z; box journal and file reads 2026-10-26; first 'fetch proven' line 2026-10-08; earlier empty runs came from ModuleNotFoundError (Sep 5-6) and ESPN HTTP 403 (Sep 20 - Oct 2).
- **Status:** CONFIRMED
- **Existing owner or PR:** #1952 draft (parses 274 of 800, was 0; derived events go to a shadow file; prior seeded silently). Items RPA-LGI-016, RPA-COL-019.
- **Fix authorized?** Yes for the parser and shadow diversion (routine engineering, injury/availability lane). Writing derived events into the BDVM events file is owner-gated, as it was for depth charts in #1926.
- **Recommended repair:** Land #1952 with a guard that treats zero parsed entries from a payload that has rows as a failure (non-zero exit), then verify the first post-merge run reports hundreds of entries. Keep events in shadow until a volume and false-positive measurement exists.
- **Potential impact:** A naive fix would, with the empty prior snapshot, treat about 274 injured players as new transitions and merge them as confidence-0.85 INJURY events into the file BDVM reads for every valuation. Until fixed, waiver-opportunity and availability evidence believe nobody is hurt.
- **Dependencies:** #1952; owner decision before events leave shadow.
- **Activation requires owner approval?** Yes

### RPA-F-005 (high, CONFIRMED) The Sharp transaction crawl fetches zero leagues in 13 of 28 runs because 404 leagues trip the shared Sleeper breaker

- **Affected subsystem:** Sharp cohort / completed-trade ledger input
- **Reproduction evidence:** 28 runs in 7 days: leaguesFetched = 0 in 13 runs and at most 5 in three more; 50-60 per run from 2026-10-23 16:26 to 10-26 03:23; 0 again at 2026-10-26 09:25 CET. leaguesFailed is a constant 598 and leaguesPending about 5,494. The journal shows the first five queued leagues return HTTP 404 on /rosters, which opens the shared sleeper_api breaker (5 in 60 s), then every other league is fast-failed. The unit exits 2 and systemd records success, so nothing alerts.
- **Data source and observed timestamps:** Box journals for dynasty-sharp-transactions, parsed 2026-10-26 (28 runs).
- **Status:** CONFIRMED
- **Existing owner or PR:** #1957 draft (404 leagues no longer trip the sleeper_api breaker; gone leagues skipped for 168 h; explicit stoppedReason). Items RPA-COL-017, RPA-COL-016.
- **Fix authorized?** Yes. Standing box timer, evidence only; an ordinary bounded defect repair.
- **Recommended repair:** Land #1957; report leaguesFetched against leaguesConsidered and exit non-zero under a floor; re-measure coverage; confirm the 598 are really deleted leagues (only five were sampled).
- **Potential impact:** The Sleeper lane of the completed-trade ledger rests on about 10,309 trades from 50-60 leagues per good run and from none on a bad one, and it is biased toward leagues that happen to answer. Package-model and market-trade evaluations inherit that bias.
- **Dependencies:** #1957 CI (UNSTABLE at last read); ledger rebuild RPA-COL-015.
- **Activation requires owner approval?** No

### RPA-F-006 (high, CONFIRMED) Independent-audit security and money fixes for the Rookie Auction Room are not on main while the room is live in mock mode

- **Affected subsystem:** Rookie Auction Room
- **Reproduction evidence:** Three independent audits on PR #1533 found money (2 defects), security (6, including a site-owner account password without proof and CSV formula injection) and recovery (10, including a non-atomic backup and a false outage pause) defects. feedback.py, open_trade_offers and a CSV formula guard are absent from main. #1533 is OPEN, DIRTY, 1,890 commits behind, and its Validate PR run 36652223664 failed on an httpx cookie-jar incompatibility in test_concurrent_duplicate_admin_request_acts_once. Each specific defect being unfixed on main was spot-checked for only a few.
- **Data source and observed timestamps:** gh pr view 1533; failed run log; flag rookie_auction ON in /api/status and /api/auction/meta 200, 2026-10-26.
- **Status:** CONFIRMED
- **Existing owner or PR:** #1950 draft (Phase 2 security and money fixes plus review follow-ups; supersedes #1533). Four audit branches exist only as unpushed local worktrees. Items RPA-DRF-003, RPA-GOV-001.
- **Fix authorized?** Yes. CQ-43 (blocker NONE) authorizes rebase, test fix, re-review and merge. The official room stays gated (D20) and is not authorized.
- **Recommended repair:** Finish and review #1950 (security fixes first, consider a small split PR), run exact-head CI, merge, then push or confirm the four local audit branches' content is in it. Leave the official gate OFF.
- **Potential impact:** Seat and account security and bid-money correctness for a room that is reachable in production, even if only in mock mode.
- **Dependencies:** #1950 review and CI.
- **Activation requires owner approval?** No

### RPA-F-007 (high, CONFIRMED) 111 open Dependabot alerts, 12 of them critical, and the three PRs that would clear 100 of them cannot go green

- **Affected subsystem:** Dependencies / supply chain
- **Reproduction evidence:** gh api dependabot/alerts: 111 open = 12 critical, 54 high, 39 medium, 6 low; pillow 82 (10 critical), aiohttp 16, certifi 2 (critical), vite 6, vitest/mocker 3, source-map-js 1, setuptools 1. PRs #1896 (pillow 13), #1895 (certifi) and #1855 (aiohttp 3.14.4) fail prove-linux-wheels, prove-runtime-wheels and Validate PR with 'dependency input changed without lock refresh: requirements.txt' (log text read for #1896 only). Whether the vulnerable packages sit on the box's execution path was not checked.
- **Data source and observed timestamps:** gh api and gh pr checks, 2026-10-26.
- **Status:** CONFIRMED
- **Existing owner or PR:** #1955 draft (aiohttp, certifi, pillow with lock refresh; supersedes #1855, #1895, #1896; covers 100 of 111 alerts). Item RPA-OPS-010.
- **Fix authorized?** Yes. CQ-59 (blocker NONE); framework and dependency upgrades are high-risk and need the full L2 backend and frontend suites plus box verification (#1485).
- **Recommended repair:** Land #1955 after box verification, then the frontend train; close #1660 as a duplicate of #1885; update CQ-59, which lists two PRs that no longer exist.
- **Potential impact:** Critical image-parsing and certificate-store exposure in the scraper runtime if those packages are executed there.
- **Dependencies:** #1955 CI and box verification; Node 22 migration for the frontend train.
- **Activation requires owner approval?** No

### RPA-F-008 (high, CONFIRMED) Four nflverse scorer defects bias the live BDVM in-season fundamentals, mostly for IDP

- **Affected subsystem:** Scoring / BDVM in-season path
- **Reproduction evidence:** Lane A reconciliation: host-native scorer equals Sleeper players_points on 3,710 of 3,710 rostered player-weeks (dynasty_main weeks 1-6, max error 0.0044); the nflverse path matches 2,832 of 3,095 (91.5%), with IDPA-DEFECT-01..04 affecting 92 player-weeks. IDP exactness: LB 84.5%, DB 87.6%, DL 93.8%. The assessor inspected the artifacts but they had no independent review, and reproduction outside the lane worktree is unverified.
- **Data source and observed timestamps:** PR #1931 evidence (2026-10-26) and the Lane A artifacts; BDVM actuals blend is active for the 2026 season (weeks 1-6).
- **Status:** CONFIRMED
- **Existing owner or PR:** #1931 open (evidence). #1938 draft fixes defects 01/02/03 on the nflverse path and CHANGES BDVM in-season values; it awaits owner approval. Items RPA-VAL-013, RPA-LGI-005.
- **Fix authorized?** No. The IDP accuracy directive forbids live scoring or value changes; the fix needs its own authorization and an owner decision on #1938.
- **Recommended repair:** Owner decides #1938; route the defects to the BDVM/scoring owner as a separate unit; meanwhile state the nflverse path's exactness next to any in-season BDVM figure.
- **Potential impact:** In-season BDVM values (the /rankings Fund-gap column, the /bdvm trade scan, signal alerts) are computed from partly wrong weekly points, concentrated in LB and DB.
- **Dependencies:** #1931 merge; owner decision on #1938.
- **Activation requires owner approval?** Yes

### RPA-F-009 (high, UNRESOLVED) Backup coverage of the irreplaceable 2.25 GB temporal ledger cannot be confirmed, and the health stamp reads the wrong directory

- **Affected subsystem:** Backups / retention
- **Reproduction evidence:** Verified: /api/health backup_health reports newestBackupAgeHours 10.24 from the legacy dynasty-owned directory ('fallback'), not from /var/backups/riskit-state (root-only); the restore proof skips temporal_ledger.sqlite and intel_ledger.sqlite3 by default; the weekly restore test covers user_kv only; the state-backup unit has no OFFBOX_RSYNC_DEST (inferred: no off-box mirror). Unverified: whether the newest state-backup generation actually contains the ledger (it is an OPTIONAL store shed first when disk is low).
- **Data source and observed timestamps:** Box reads and public /api/health, 2026-10-26; temporal_ledger.sqlite 2,249,994,240 bytes, 5,022,969 observations, growing about 20 MB/day; / has 44 GB free.
- **Status:** UNRESOLVED
- **Existing owner or PR:** No PR. Items RPA-COL-032, RPA-COL-026, RPA-COL-024, RPA-COL-025.
- **Fix authorized?** Yes for the listing, restore proof and health-stamp repair (C1A retention machinery). Provisioning an off-box destination is owner-only.
- **Recommended repair:** Have root list the newest riskit-state generation and report which optional stores are present and how large; run one restore proof with PROOF_SKIP_OPTIONAL unset; point backup_health at the state-backup root; decide the off-box mirror.
- **Potential impact:** The pre-2026-07-14 history gap is permanent and any lost later day is too; a disk shortage could silently drop the ledger from the nightly backup.
- **Dependencies:** Root access on the box; owner decision on an off-box destination.
- **Activation requires owner approval?** Yes

### RPA-F-010 (high, UNRESOLVED) The 2026-10-22/23 production degradation (about 24 hours) has no established root cause and the evidence is gone

- **Affected subsystem:** Production operations
- **Reproduction evidence:** Backend process pid 408097: first KTC API-intercept timeout 2026-10-23 01:12, then every KTC and IDPTC scrape ended 'PARTIAL SCRAPE NOT PROMOTED' (fail-closed worked) with durations growing from 577 s to 2,767 s until the 10-24 02:05 CEST restart. Health check failed 4 of 4 with HTTP 503 on 10-23; public-league warmup failed 6 of 6 on 10-23; the temporal ledger holds 9,212 rows for 10-23 against 62k-87k on neighbouring days. Three explanations fit (process aging or memory throttling, host slowness, vendor-side blocking); none is tested, and the process's cgroup events were lost with it.
- **Data source and observed timestamps:** dynasty.service journal 10-22 06:20 to 10-24 01:58 CEST; gh run histories; temporal ledger daily volumes.
- **Status:** UNRESOLVED
- **Existing owner or PR:** No PR. #1880 (self-diagnosing liveness snapshot) merged but no snapshot of the degraded process exists; #1917 merged 10-23; issue #1919 closed 10-24. Items RPA-OPS-006, RPA-COL-034, RPA-COL-026.
- **Fix authorized?** Partly. Diagnostics are covered by the 2026-10-07 stabilization campaign; any production setting change (including the memory canary) is owner-reserved.
- **Recommended repair:** Add a cheap cgroup memory.events and pressure capture to the scrape-stall path so the next stall explains itself; treat the reported ~979-row IDPTC partial as unverifiable (the journal shows 898/900) and close it.
- **Potential impact:** It can recur without a diagnosis, and the 10-23 gap in the temporal ledger (about 85% of that day) is permanent.
- **Dependencies:** RPA-OPS-005 memory-canary decision.
- **Activation requires owner approval?** Yes

### RPA-F-011 (medium, CONFIRMED) Public /league has a 44-second cold path and the production smoke monitor fails intermittently on it

- **Affected subsystem:** Public site performance / monitors
- **Reproduction evidence:** Probes 2026-10-26 ~11:40Z: /api/public/league (no leagueKey) 44.1 s for 2.65 MB, then ?leagueKey=dynasty_main 1.15 s cached; a second clean-client probe saw 7.5 s cold. Prod E2E Smoke: 19 failures / 23 successes over the last 42 runs (2026-10-04..10-26) and 13 of 28 since 10-19, every failure 'curl: (28) timed out after 60002 ms ... HTTP 000'. Warmup cron declared every 20 min actually fires with a median gap of 251 min against a 300 s cache TTL. Root cause (cold cache at probe time) is inferred, not traced.
- **Data source and observed timestamps:** gh run list; run logs 40224120704 and 40162685579; live curl timing 2026-10-26.
- **Status:** CONFIRMED
- **Existing owner or PR:** No PR or claim (unclaimed). Items RPA-OPS-002, RPA-COL-034.
- **Fix authorized?** Yes. 2026-10-07 stabilization campaign and the performance directive (#1338).
- **Recommended repair:** Open a claim; measure the cold path server-side; make warmup independent of GitHub cron (box timer) or serve stale-while-revalidate so users never see the cold build; make the smoke monitor report timeout vs connect vs TLS. Do not raise the curl timeout.
- **Potential impact:** A real visitor hitting a cold cache would see the same wait; red smoke runs teach people to ignore the monitor.
- **Dependencies:** None.
- **Activation requires owner approval?** No

### RPA-F-012 (medium, CONFIRMED) The nightly E2E Safety Net was red four nights running on deterministic specs

- **Affected subsystem:** CI / E2E
- **Reproduction evidence:** Scheduled runs 39775326284 (10-22), 39948716424 (10-23), 40089106765 (10-24), 40190095632 (10-25 11:44Z) failed on trade-multi-team.spec.js:138 and :318 and trade-tcd2.spec.js:61 (live-board pick names such as '2027 Mid 1st (from Kich)').
- **Data source and observed timestamps:** gh run list for e2e.yml. No scheduled run has completed since the fix merged (latest listed 2026-10-25T11:44Z, failure).
- **Status:** CONFIRMED
- **Existing owner or PR:** #1923 MERGED 2026-10-25T20:26:33Z (bb28be9f5; PR-branch run green at 17:02Z). Issue #1918 open. Verification of the fix on a scheduled main run is PENDING. Items RPA-OPS-003, RPA-COL-034.
- **Fix authorized?** Yes. Lane B of the 2026-10-16 repository-audit directive and the stabilization campaign.
- **Recommended repair:** Check the next scheduled main run; close #1918 only on green; do not re-dispatch manually before then.
- **Potential impact:** A known-red gate hides real regressions in the multi-team trade work.
- **Dependencies:** Next scheduled E2E run.
- **Activation requires owner approval?** No

### RPA-F-013 (medium, CONFIRMED) IDP vote evidence is thinning: four of five IDP vendor feeds have static content, and IDPTC is the only anchor with no rehabilitation entry

- **Affected subsystem:** Source freshness / IDP valuation
- **Reproduction evidence:** IDP Show: fetch HEALTHY (665 rows, 2026-10-26T10:32Z) but vendor chart lastModifiedAt 2026-08-19T17:50Z, so source_votes_withheld:idpShowCombined:655. FantasyPros IDP: vendor clock 2026-09-04, freshness about 0.11 and self-quarantine near 2026-11-22 (both computed by the auditor, inferred). IDPTC: players last changed 2026-10-16T07:38Z, picks 2026-10-10T20:25Z; config/sources/rehabilitation.json has no idpTradeCalc entry and issue #1065's body predates the 10/10 update. Signals IDP: collector healthy, vendor board static since 2026-10-21T15:05Z. DLF IDP is held by policy. Whether IDPTC currently votes at full weight is unverified (the weighting endpoint needs a login).
- **Data source and observed timestamps:** data/scrape_state files and box dataset_state, production /api/status warnings, 2026-10-25/26.
- **Status:** CONFIRMED
- **Existing owner or PR:** No PR. #1884 (DLF IDP gate) open. Items RPA-SRC-004, RPA-SRC-002, RPA-SRC-003, RPA-SRC-005, RPA-VAL-010.
- **Fix authorized?** Yes for the idpTradeCalc rehabilitation entry and #1065 refresh. Activating or re-weighting any IDP source is owner-reserved.
- **Recommended repair:** Add (or consciously decline) an idpTradeCalc rehabilitation entry and refresh #1065; run the registry's overdue report when the 10-31 and 11-01 reviewBy dates arrive; do no activation work.
- **Potential impact:** IDP values lean on fewer and older independent voters, and the ranking's confidence labels for IDP rows depend on which of them still count.
- **Dependencies:** Vendor publication; RPA-VAL-001 for DLF IDP.
- **Activation requires owner approval?** No

### RPA-F-014 (medium, SUSPECTED) Fetch-success stamps for KTC, IDPTC and DraftSharks have a single writer (the GitHub runner) and feed the confidence freshness axis

- **Affected subsystem:** Source freshness / confidence
- **Reproduction evidence:** By grep of origin/main, only scheduled-refresh.yml run_fetcher writes data/scrape_state/<key>_last_success for ktc*, idpTradeCalc and draftSharks*; the box scrape rewrote CSVs/site_raw/ktcSfTep.csv at 09:40Z and the box dataset clock for ktcCrowdSfTep reads 2026-10-26T11:40:01Z, while the committed copy says 2026-10-25T12:07:00Z. _SOURCE_MAX_AGE_HOURS gives these sources 6 h, but the real cadence has 4 of 11 inter-run gaps over 6 h (max 7.4 h). That stale stamps lower served confidence labels is inferred from code, not measured on a served contract.
- **Data source and observed timestamps:** git grep on origin/main 6eddc569f; read-only ssh md5 and JSON clock reads; gh run list, 2026-10-26.
- **Status:** SUSPECTED
- **Existing owner or PR:** No PR or branch for stamp ownership. Related #1939, #1953, issue #1423. Item RPA-SRC-006.
- **Fix authorized?** No. No EXECUTION_PLAN row authorizes changing stamp ownership or the 6 h budgets; changing which stamp feeds the confidence gate changes served labels.
- **Recommended repair:** After the post-pin run, scope one unit: have the box scrape stamp what it fetches (or let the freshness axis read the dataset_state fetch clock), resolve the two-writer problem for ktc*_dataset.json, re-derive the budgets, and include a replay showing how many labels move.
- **Potential impact:** Healthy sources can be flagged stale intermittently and vice versa; confidence labels for rows supported by these sources move with it.
- **Dependencies:** RPA-COL-001 repair; owner review of any confidence-label change.
- **Activation requires owner approval?** Yes

### RPA-F-015 (medium, CONFIRMED) Rank-form reconstruction constants have drifted 3x to 8x past budget, and the Terminal team-value chart always uses them

- **Affected subsystem:** Valuation display / Terminal
- **Reproduction evidence:** Constants 65.4/0.910 (offense) and 64.6/0.900 (IDP) unchanged since 2026-07-30. Weekly audit red on 10 consecutive scheduled runs (2026-08-18..10-20): offense RMSE 175.4 against a refit 100.8 (excess +74.6) and IDP 174.8 against 34.0 (excess +140.8), budget 25. frontend computeTeamValueSeries/normalizePoints drop persisted rank_history values and always rebuild from rank with the stale curve (TeamValueChart, TeamCommandHeader 7/30-day deltas), contrary to the file's own comment.
- **Data source and observed timestamps:** gh run list for audit-rank-form-drift.yml; run 39426512824 log; code on origin/main a20de7020; issue #898.
- **Status:** CONFIRMED
- **Existing owner or PR:** No PR or claim for CQ-28; #898 open with bot-only comments; #1672 closed NOT_PLANNED. Items RPA-VAL-011, RPA-COL-007.
- **Fix authorized?** Yes. CQ-28 (blocker NONE) under EXECUTION_PLAN line 145; the constants are reconstruction-only. An owner decision is needed only if a consumer is shown to feed served canonical values.
- **Recommended repair:** Claim CQ-28; make computeTeamValueSeries prefer the stored value; refit and update the three constant locations and two guard files in one reviewed PR; keep the threshold at 25.
- **Potential impact:** Terminal team-value levels and deltas are off by roughly the audit's RMSE; a permanently red audit also cannot warn about a real regression after a Hill-master promotion.
- **Dependencies:** None.
- **Activation requires owner approval?** No

### RPA-F-016 (medium, CONFIRMED) BDVM's IDP Show projection feed has never produced a record, and the weekly unit still reports success

- **Affected subsystem:** BDVM projections
- **Reproduction evidence:** 2026-10-20 journal: baseline exit 0, Clay exit 0, idpshow exit 1, then 'idpshow returned no usable data'; the report shows reason 'not_a_projection_table' with unmapped columns 'Position Rank' and 'Projected Total Snaps'. None of the 29 snapshot files since 2026-07-30 contains an IDP Show record; 2026-10-20 held 3,067 records (62% proxy). Cookies are fresh (6.2 of 90 days), so the leading explanation is a layout or parse change (inferred). This is a different feed from the IDP Show rankings board.
- **Data source and observed timestamps:** Box journal 2026-10-20 06:14Z; 29 snapshot files; events/2026.json (244 events, all news:cbs).
- **Status:** CONFIRMED
- **Existing owner or PR:** #1959 draft (the refresh reports failed sources honestly and writes refresh_status.json; the IDP Show parser had rejected the sheet because the position now arrives only as a 'Position Rank' code, an inference, and the PR mirrors the rename the rankings fetcher already handles; parsed records go to a shadow file only). Merging them into BDVM snapshots is an owner decision behind a default-off switch. Item RPA-COL-027.
- **Fix authorized?** Yes for honest reporting and the shadow parser (BDVM is a live flagged engine and the IDP Show projection fetcher is merged). Merging parsed records into the BDVM snapshots is an owner decision.
- **Recommended repair:** Land #1959; verify the Tue 2026-10-27 run writes refresh_status.json and shows the IDP Show stage's real outcome; the owner decides whether shadow records may later be merged into the snapshots.
- **Potential impact:** IDP fundamentals rest on Clay (no TFL or pass-defended) plus proxies, while the unit looks healthy.
- **Dependencies:** #1959; next run 2026-10-27; owner decision before any merge into snapshots.
- **Activation requires owner approval?** Yes

### RPA-F-017 (medium, CONFIRMED) /api/health reports the DLF session as 96.6 days old with 0.0 days remaining; it reads a dead July copy

- **Affected subsystem:** Monitoring (/api/health)
- **Reproduction evidence:** session_cookies shows dlf_session.json ageDays 96.6, lifetime 14, daysRemaining 0.0, expired false. It reads /home/dynasty/trade-calculator/dlf_session.json (mtime 2026-07-21), while the timer uses /var/lib/dlf-fetch/dlf_session.json (mtime 2026-10-26 11:27). The same applies to idpshow_session.json (app-dir copy 2026-10-20, timer copy 2026-10-26).
- **Data source and observed timestamps:** ssh find -printf and public /api/health, 2026-10-26.
- **Status:** CONFIRMED
- **Existing owner or PR:** #1956 draft (read the DLF session the timer actually uses). Item RPA-COL-012.
- **Fix authorized?** Yes. Standing box timers and health endpoint; routine engineering.
- **Recommended repair:** Land #1956 and check idpshow_session.json the same way.
- **Potential impact:** The health page contradicts reality in both directions: a healthy session looks expired, and a genuinely expired timer session would not show.
- **Dependencies:** #1956.
- **Activation requires owner approval?** No

### RPA-F-018 (medium, CONFIRMED) The DLF fetcher exited clean after a fetch timeout, and DLF's Value column is unavailable, so DLF votes as rank only

- **Affected subsystem:** DLF collector
- **Reproduction evidence:** 2026-10-22 06:27 CEST: a curl_cffi 30 s timeout on the DLF home page raised a Traceback, then the script logged 'no changes after fetch - exiting clean' (exit 0); one such run in 7 days plus 3 'cached session rejected - re-authenticating' events. 'dlfSf native Value coverage 0/287 - DLF Value column unavailable; writing rank with an empty value column' appeared 83 times in 7 days.
- **Data source and observed timestamps:** Box journals for dynasty-dlf-fetch, 7 days to 2026-10-26.
- **Status:** CONFIRMED
- **Existing owner or PR:** No PR. Item RPA-COL-012.
- **Fix authorized?** Yes (standing box timer).
- **Recommended repair:** Turn a fetch Traceback into a non-zero exit; surface the 'Value column unavailable' warning in source health; do not reset the IDP Show clock.
- **Potential impact:** A failed DLF fetch can look like an unchanged board; DLF's contribution to the blend is rank-derived rather than value-based.
- **Dependencies:** None.
- **Activation requires owner approval?** No

### RPA-F-019 (medium, CONFIRMED) The Sharp production gate has never measured anything, and its green runs read as verification

- **Affected subsystem:** Sharp production verification
- **Reproduction evidence:** data/ops/sharp-production-smoke.json: status 'unverifiable_unauthenticated', measured false, lastMeasuredOn null, lastError '401 from https://chaseupside.com/api/sharp/cohort'. Issue #1727 puts the state at since 2026-10-12T12:28Z with 'last time it could measure: never'. No SHARP_SMOKE_TOKEN repository secret exists. Over 7 days the workflow had 52 success / 18 failure / 30 cancelled; the latest three runs were green while measuring nothing. Issue #951 has 852 comments, one per run. The box-side cohort snapshot (2,547 members, 2026-10-26 06:10 CET) shows collection works.
- **Data source and observed timestamps:** Committed smoke file, gh secret list (names only), gh issue view, box reads, 2026-10-26. The two items disagree on the start date of the unmeasured state (file stateSince 2026-10-26T02:08Z vs issue 2026-10-12); the issue date is the earlier and the file resets on each record commit.
- **Status:** CONFIRMED
- **Existing owner or PR:** #1727 and #951 open; #1837 merged. Items RPA-OPS-009, RPA-COL-036.
- **Fix authorized?** No for the credential: minting and storing SHARP_SMOKE_TOKEN is owner-held. Yes for relabelling the gate and suppressing per-run record commits while unmeasured.
- **Recommended repair:** Owner provisions a least-privilege SHARP_SMOKE_TOKEN (repository secret plus production .env, then a restart) or accepts an unmeasured gate; stop citing green runs as proof; stop appending a comment per run to #951.
- **Potential impact:** Sharp surfaces' production health is unverified while the dashboard looks green.
- **Dependencies:** Owner credential action.
- **Activation requires owner approval?** Yes

### RPA-F-020 (medium, CONFIRMED) Settings still offers 'Value basis: My league' and says it is the only setting that changes the numbers; the lens was withdrawn

- **Affected subsystem:** Frontend settings
- **Reproduction evidence:** frontend/app/settings/page.jsx ~619-690 renders the select and the copy 'This is the only setting that changes the numbers themselves ... scale every player at that position by up to +/-10%'. Since #822/B9a (2026-08-14) the server ignores the request and stamps valuationMode market; dynasty-data.js hard-codes leagueAdjusted = false. Whether the control renders in production is unverified (login-only).
- **Data source and observed timestamps:** Code on origin/main 6eddc569f; /api/valuation/league-adjusted returns 401 anonymously, 2026-10-26.
- **Status:** CONFIRMED
- **Existing owner or PR:** #1954 draft (truthful value-basis setting, plus the waiver-compare charset repair). Item RPA-VAL-018.
- **Fix authorized?** Yes. A frontend copy and control change with no served-value effect; the flags' fate is an Integration decision.
- **Recommended repair:** Land #1954; decide whether idp_scoring_fit and reception_scoring_fit stay ON (they only feed an unused opt-in endpoint and the offline backtest).
- **Potential impact:** Users are told a control changes their numbers when it does nothing.
- **Dependencies:** #1954.
- **Activation requires owner approval?** No

### RPA-F-021 (medium, CONFIRMED) Every production best-ball simulation runs on fallback points-model constants because the calibrated artifact was never built

- **Affected subsystem:** Simulations (playoff odds, Game Day, forecast archive)
- **Reproduction evidence:** data/league_intel/ does not exist on the box and no script, timer or workflow calls build_calibration, so load_points_model() stamps 'fallback-constants' (rosValuePerPoint 2.7; CV QB .32 ... DL .55, DB .50). The D11 playoff comparison also ran on fallback constants (sampleSize 0) and failed gate G4. In-sample six-week measurements on draft PR #1941 give CV DL 0.73, DB 0.65, QB 0.57, which is not validated out of sample.
- **Data source and observed timestamps:** ssh ls and git grep, 2026-10-26; evaluation_historical_replay and D11 results (2026-10-18).
- **Status:** CONFIRMED
- **Existing owner or PR:** Drafts #1941, #1945; no builder PR. Items RPA-LGI-008, RPA-LGI-006, RPA-LGI-007.
- **Fix authorized?** Partly. Building an offline or shadow artifact is within EXECUTION_PLAN section 0 (2026-10-19 later); changing served simulation inputs is owner-reserved.
- **Recommended repair:** Run build_calibration offline (output not under box data/league_intel), compare against the fallback on held-out weeks under a preregistered gate, add a scheduled builder with a status stamp, and only then request promotion.
- **Potential impact:** Published playoff and title odds and Game Day probabilities use uncalibrated dispersion that looks too low for IDP and QB.
- **Dependencies:** Preregistration; live card hand-off (see the stale-snapshot finding).
- **Activation requires owner approval?** Yes

### RPA-F-022 (medium, CONFIRMED) The incumbent cut ladder breaks ties alphabetically by asset name, which changes forced-drop charges and Perfect Draft cut order

- **Affected subsystem:** Roster capacity / forced drops
- **Reproduction evidence:** Draft PR #1937 cites build_cut_ladder breaking ties by asset.name.lower(); two independent lanes (Lane E I9-TIEBREAK and IDP Lane H X2) report a tied first cut on all 12 rosters that costs replayed best-ball points on 9 of 12. The mechanism is verified from the PR body; the impact figures are from draft PRs and were not re-run; the '12.19 points/week' maximum quoted in the brief was not found in committed text.
- **Data source and observed timestamps:** PR #1937 and #1945 bodies read 2026-10-26.
- **Status:** CONFIRMED
- **Existing owner or PR:** #1937 draft (pins I9-TIEBREAK as an owner decision) and #1945 draft (X2). Item RPA-TRD-004, RPA-TRD-007.
- **Fix authorized?** Partly. A stand-alone tie-break repair can be decided now by the owner; it is not authorized as part of any forced-drop activation.
- **Recommended repair:** Owner decides the tie-break rule; land it separately from V5-R; keep forced_drop_cheapest_legal OFF.
- **Potential impact:** Forced-drop cost shown in trade analysis and the cut ladder in Perfect Draft depend on alphabetical order when assets tie.
- **Dependencies:** Owner decision; #1935 then #1937 stack.
- **Activation requires owner approval?** Yes

### RPA-F-023 (medium, CONFIRMED) Owner-facing decision and status records state facts that production or code contradicts

- **Affected subsystem:** Planning and ledger records
- **Reproduction evidence:** D4 is OFF in production (dlf_values_rank_hill_vote enabled false), but OWNER_REQUESTED_TODO line 2269 says the flag is ON in PR #1817 and DEVELOPMENT_TRACKER line 40 says 'D4 and D5 ON'; ODR-DLF-VALUES-VOTE still reads EVIDENCE_PENDING; ODR-IDP-DEEP-TAIL and intake D6 read EVIDENCE_PENDING although the verdict was committed 2026-10-18; ODR-PLAYOFF-ROS-DOUBLE says 'no challenger yet' although the challenger exists and failed gate G4; family_C.json and the completion dashboard say AL-4a and AL-3b code does not exist; Schedule Intelligence still says part E is blocked on C5-WAR-01 (merged #1692). The full list is in 'Stale records corrected'.
- **Data source and observed timestamps:** git show origin/main for each record, plus production /api/status, 2026-10-26.
- **Status:** CONFIRMED
- **Existing owner or PR:** No open PR refreshes them. Items RPA-VAL-003, RPA-VAL-004, RPA-LGI-006, RPA-GOV-003, RPA-LGI-009, RPA-TRD-006.
- **Fix authorized?** Yes. Records pass under the 2026-10-07 stabilization campaign; one coordinator choice is needed on which denominator is live (ledger dashboard or COMPLETION_QUEUE).
- **Recommended repair:** One records PR: correct each row to the cited evidence, regenerate the dashboard, refresh COMPLETION_QUEUE 'as of', point HANDOFF.md at the current owner-action record.
- **Potential impact:** An owner or agent reading the register would believe D4 is live, a challenger is undecided, or code is missing, and could decide on that basis.
- **Dependencies:** None.
- **Activation requires owner approval?** No

### RPA-F-024 (medium, CONFIRMED) Nine owner-reserved flags (and three closed-challenger flags) are default OFF but not protected by the deploy-time hold

- **Affected subsystem:** Feature flags / deploy gate
- **Reproduction evidence:** scripts/verify_owner_held_flags.py holds six flags (dlf_offense_only_vote must be ON; dlf_values_rank_hill_vote, source_freshness_schedule_v2, low_value_depth_disclosure_shadow, replacement_level_li5_consolidation, forced_drop_cheapest_legal must be OFF). Still unlocked and OFF in production: brisket_trade_advisor, trade_multi_team_analysis, signals_idp_shared_market, signals_idp_dl_vote, signals_idp_lb_vote, signals_idp_db_vote, signals_idp_xwalk_v2, outlier_disagreement_policy, playoff_ros_counted_once. The three further closed challengers (rank_space_hampel_challenger, rank_space_hampel_per_vote_challenger, idp_hampel_n3_challenger; outlier_disagreement_policy is already in the list above) are still env-activatable inside the canonical valuation path. The registry (61 flags) and production (61 flags) agree except host_native_scoring.
- **Data source and observed timestamps:** Registry on origin/main and production /api/status (build f1dc2b0c7), 2026-10-26.
- **Status:** CONFIRMED
- **Existing owner or PR:** #1927 merged (added two locks). #1929 would add a 62nd flag (conditional_startup_scrape) without one. Items RPA-OPS-007, RPA-VAL-005, RPA-TRD-007, RPA-TRD-008.
- **Fix authorized?** Yes. Widening the lock is covered by the stabilization campaign; each addition should cite its owner decision.
- **Recommended repair:** Add the nine flags to OWNER_HELD_FLAGS (and conditional_startup_scrape when #1929 lands); retire the rank-space and n=3 challenger code in a separate behaviour-preserving PR with a byte-identical board proof.
- **Potential impact:** A stray environment variable could open a public-launch or voting path without the deploy gate failing.
- **Dependencies:** Coordination on data_contract.py.
- **Activation requires owner approval?** No

### RPA-F-025 (medium, CONFIRMED) The main branch ruleset has no required status checks or reviews

- **Affected subsystem:** Repository governance
- **Reproduction evidence:** gh api: ruleset 19976839 enforces only deletion and non_fast_forward; bypass actors are DeployKey and repository roles 4 and 5; the branch-protection API returns 404. 'Required checks' exist only through process and Integration discipline.
- **Data source and observed timestamps:** gh api, 2026-10-26.
- **Status:** CONFIRMED
- **Existing owner or PR:** No PR. Item RPA-GOV-001.
- **Fix authorized?** No. Changing required checks or branch protection is outside this audit and the Agent OS forbids weakening them; adding them is an owner decision.
- **Recommended repair:** Raise the gap with the owner as a decision; do not change settings from an audit.
- **Potential impact:** A merge can occur without the checks the written process relies on.
- **Dependencies:** Owner decision.
- **Activation requires owner approval?** Yes

### RPA-F-026 (medium, CONFIRMED) Work that exists only in local worktrees or unpushed branches could be lost

- **Affected subsystem:** Repository hygiene
- **Reproduction evidence:** Examples: DLF structural diagnostic (+273/-2, three modified files and two untracked tests) only in C:/Users/jason/code/calculator-performance-ops-1338; code/rib-security-report-sanitization has 10 modified files (+226/-79) whose hardening may be unlanded; Codex performance worktrees carry uncommitted edits and untracked output/ directories (33 GB); the OD-MOTY intake text exists only on PR #1513's branch (CONFLICTING, 2,697 commits behind); four Auction audit branches are unpushed. Since the batches ran, Lane A (#1931), Lane C (#1936) and the Lane E measurement script (#1949) have been pushed as PRs.
- **Data source and observed timestamps:** git worktree list, git status and gh pr view, 2026-10-26 (88 worktrees; 40 on merged branches, 29 with no PR).
- **Status:** CONFIRMED
- **Existing owner or PR:** Items RPA-GOV-008, RPA-SRC-010, RPA-OPS-011, RPA-LGI-011, RPA-DRF-003, RPA-VAL-013, RPA-TRD-007.
- **Fix authorized?** Yes for preserving to pushed draft branches; deletion needs a diff review first (never git stash, never git commit -a).
- **Recommended repair:** Push or tag each unique tree, port the OD-MOTY text to main, then remove merged-branch worktrees after review.
- **Potential impact:** Evidence and security hardening could be deleted with a worktree.
- **Dependencies:** Owner choice on RPA-SRC-010 and RPA-LGI-011.
- **Activation requires owner approval?** No

### RPA-F-027 (medium, CONFIRMED) The ROS aggregate counts a 12-day-old unchanged body as 'ok', and an orphan source file sits beside it

- **Affected subsystem:** ROS rankings aggregate
- **Reproduction evidence:** ffc2qbAdp.csv was byte-unchanged for 12 days at assessment (14 days per #1958) while its run status reads 'ok' (a fetch result) and it contributes to the aggregate; src/ros keeps the existing CSV when an adapter returns zero rows and still reports ok. footballGuysRosIdp.csv (19 KB, 2026-07-20) has no adapter, registry entry or run record (#1958 confirms the orphan). The freshness multiplier reads scraped_at, a fetch time.
- **Data source and observed timestamps:** Box run index, CSV mtimes and aggregate/latest.json (written 2026-10-26 09:34Z); PR #1958 body.
- **Status:** CONFIRMED
- **Existing owner or PR:** #1958 draft (explicit kept_previous status and a content clock for ROS sources; reporting only, changes no value). Item RPA-COL-031.
- **Fix authorized?** Yes. The seasonal-intelligence lane is allowed; the aggregate is existing production.
- **Recommended repair:** Land #1958 (content-change time per ROS source, keep-last-good surfaced as kept_previous instead of 'ok'); delete or register the orphan CSV.
- **Potential impact:** Rest-of-season strength, playoff odds and Game Day lineup intelligence can lean on stale data labelled fresh.
- **Dependencies:** #1958.
- **Activation requires owner approval?** No

### RPA-F-028 (medium, CONFIRMED) retention-health has been red on 26 of its last 40 daily runs, including a 22-day streak nobody examined

- **Affected subsystem:** Retention monitoring
- **Reproduction evidence:** Failures on every run 2026-09-16..10-07 (22 days), plus 10-12, 10-13, 10-14 and 10-23; green 10-08..10-11, 10-15..10-22, 10-24, 10-25. The 10-23 failure listed three stale streams (crowd-FAAB 11.64 h, scoring card 14.89 h, trending 14.89 h against 6.0 h budgets). The cause of the 22-day streak was not examined.
- **Data source and observed timestamps:** gh run list for retention-health.yml, 2026-10-26.
- **Status:** CONFIRMED
- **Existing owner or PR:** No PR. Item RPA-COL-032.
- **Fix authorized?** Yes (existing retention machinery).
- **Recommended repair:** Establish why the streak was red and why it cleared; keep the budgets honest; do not change a budget to turn it green.
- **Potential impact:** A monitor that is red for weeks teaches everyone to ignore it.
- **Dependencies:** None.
- **Activation requires owner approval?** No

### RPA-F-029 (medium, CONFIRMED) Several shadow recorders and scorecards run (or are merged) with no evaluator, so their status panels read as monitoring

- **Affected subsystem:** Shadow evidence / Model Lab
- **Reproduction evidence:** Sparse-evidence recorder: 47 records, 'record' subcommand only, no outcome horizon preregistered, all records workingTreeDirty. Joint robust-filter shadow: 47 records, every h=7 pair skipped on fingerprint mismatch (data_contract.py changed 54 times since 10-01; longest unchanged gap 5.53 days), so only h=3 is evaluable. Consensus Edge: the committed measurement is frozen at 2026-08-04, the 54,170 labelled forward outcomes are read by nothing, and Model Lab reports the stale numbers. AL-4a and AL-3b scorecards are merged but no timer or workflow runs them. waiver_live_opportunity: 0 of 200 shadow comparisons recorded.
- **Data source and observed timestamps:** Box timers, ledgers and journals, 2026-10-26; PR #1691.
- **Status:** CONFIRMED
- **Existing owner or PR:** No PR. Items RPA-VAL-006, RPA-VAL-007, RPA-VAL-016, RPA-COL-003, RPA-COL-004, RPA-COL-005, RPA-LGI-004, RPA-LGI-013.
- **Fix authorized?** Yes for scheduling report-only runs and writing evaluators; none of this authorizes promotion.
- **Recommended repair:** Give each recorder an evaluator and a preregistered rule or retire it; schedule AL-4a weekly and build the pregame archive before week 8; add board source-content age to ledger rows.
- **Potential impact:** The owner may believe evidence is accumulating toward a decision when it cannot reach one.
- **Dependencies:** Owner decisions on RPA-VAL-006 and RPA-VAL-007.
- **Activation requires owner approval?** No

### RPA-F-030 (medium, SUSPECTED) The market-trade ledger grows about 27 MiB a day toward a 2 GiB memory ceiling, and no alert fires on a missed report day

- **Affected subsystem:** Completed-trade market ledger
- **Reproduction evidence:** Reports for 2026-10-24 and 10-25 were never written (the old MemoryHigh=768M throttled the job until its timeout); the 10-26 run succeeded in 73 s at peakRssMiB 870.3 after #1926. The unit author estimates the 2 GiB ceiling holds roughly six weeks (about early December 2026); that projection is inferred. The raw archive is append-only so no observation was lost. The 10-26 report shows 37,089 observations and 1 NATIVE_COMPARABLE trade (0 on 10-23).
- **Data source and observed timestamps:** Box journal, report listing and latest.json, 2026-10-26.
- **Status:** SUSPECTED
- **Existing owner or PR:** #1926 merged 2026-10-26T01:31:25Z. No PR for the streamed persist or the alert. Items RPA-COL-015, RPA-OPS-001, RPA-TRD-011.
- **Fix authorized?** Yes. Standing evidence job; never moves a canonical value.
- **Recommended repair:** Add an alert when latest.json is older than 36 h; stream the persist before the ceiling is reached; confirm two consecutive clean runs.
- **Potential impact:** Package-model confirmation and the translator-readiness table depend on this ledger.
- **Dependencies:** Market-trades owner's lane.
- **Activation requires owner approval?** No

### RPA-F-031 (low, CONFIRMED) docs/lane4/LANE4_804_CAPTURE_CADENCE_DECISION.md says the capture unit shipped in #921; #921 was closed unmerged

- **Affected subsystem:** Planning records (rank-digest capture, #804)
- **Reproduction evidence:** gh pr view 921: CLOSED, mergedAt null, closed 2026-09-09 'DEFER / PRESERVE REFERENCE'; src/history/store.py VALID_LANES is still {canonical_board, source_value, scraper_blend}. The head branch is gone from the remote; refs/pull/921/head still resolves to 03ee6212.
- **Data source and observed timestamps:** gh and git on origin/main 6eddc569f, 2026-10-26.
- **Status:** CONFIRMED
- **Existing owner or PR:** No replacement PR. Item RPA-SRC-009.
- **Fix authorized?** Yes for the one-sentence correction; the capture itself is authorized by EXECUTION_PLAN 0.4b but its cadence is an owner decision.
- **Recommended repair:** Correct the sentence; then get the cadence decision and dispatch a fresh implementation.
- **Potential impact:** A reader could believe the capture is already running and skip the decision.
- **Dependencies:** Cadence decision.
- **Activation requires owner approval?** No

### RPA-F-032 (low, CONFIRMED) The forecast archive never established two identity fields, and 10.9% of news mentions have no Sleeper id

- **Affected subsystem:** Forecast and news archives
- **Reproduction evidence:** forecasts-2026-10.jsonl: 416 records, inputs.contractGeneration and inputs.pointsModelFileSha256 are null on 416 of 416. News ledger: 3,293 records, 343 of 3,144 mentions (10.9%) have sleeperId null by design. Neither archive has a staleness alert.
- **Data source and observed timestamps:** Box file reads, 2026-10-26.
- **Status:** CONFIRMED
- **Existing owner or PR:** No PR. Item RPA-COL-022.
- **Fix authorized?** Yes (capture-only, no served value).
- **Recommended repair:** Fill or drop the two identity fields; add last-written staleness checks.
- **Potential impact:** Season-end calibration will not be able to attach a forecast to the exact contract and points model that produced it.
- **Dependencies:** None.
- **Activation requires owner approval?** No

### RPA-F-033 (low, CONFIRMED) The Week 6 narrative recaps were never exported and nothing retries a failed Tuesday run

- **Affected subsystem:** Weekly narratives
- **Reproduction evidence:** Tuesday 2026-10-20 18:24Z failed with 'could not build brief for 2026 W6 matchup 1'. The Wednesday 10-21 success produced the W7 previews, not the W6 recaps, so the earlier 'transient' reading is wrong.
- **Data source and observed timestamps:** gh run list and log for weekly-narratives.yml.
- **Status:** CONFIRMED
- **Existing owner or PR:** No PR. Item RPA-COL-037.
- **Fix authorized?** Yes (standing workflow, export mode).
- **Recommended repair:** Reproduce the W6 brief failure; add a Wednesday retry of a failed Tuesday recap; watch Tue 10-27 14:00Z.
- **Potential impact:** One week of recap packages is missing.
- **Dependencies:** None.
- **Activation requires owner approval?** No

### RPA-F-034 (low, CONFIRMED) A Codex 'Brisket Orchestrator' automation is ACTIVE daily and points at the archived OneDrive copy

- **Affected subsystem:** Agent infrastructure
- **Reproduction evidence:** automation.toml: status ACTIVE, daily 04:00, model gpt-5.4, cwd C:/Users/jason/OneDrive/Desktop/Trade Calculator (archive-only per the owner's 2026-10-21 directive). memory.md has four dated entries, the last on 2026-09-10, and describes a scaffold repo that no longer exists. Whether it still fires is unverified.
- **Data source and observed timestamps:** Local Codex automation files, 2026-10-26.
- **Status:** CONFIRMED
- **Existing owner or PR:** No PR. Items RPA-GOV-007, RPA-COL-038.
- **Fix authorized?** No. Disabling it is a local-machine action only the owner can take.
- **Recommended repair:** Owner pauses or deletes the automation, or repoints it at the active working copy in report-only mode.
- **Potential impact:** If it fires it reads stale code and writes a wrong memory file.
- **Dependencies:** Owner action.
- **Activation requires owner approval?** Yes

### RPA-F-035 (low, CONFIRMED) Waiver-compare settings labels show mojibake ('Dynasty Â· Crowd+Trades')

- **Affected subsystem:** Public waiver-compare page
- **Reproduction evidence:** Live public payload 2026-10-26T09:18Z carries the garbled separator in the sources' settings labels; whether the corruption is in the stored labels or the encoder is unverified.
- **Data source and observed timestamps:** Public curl of /api/public/waiver-compare.
- **Status:** CONFIRMED
- **Existing owner or PR:** #1954 draft (waiver-compare charset). Item RPA-LGI-018.
- **Fix authorized?** Yes.
- **Recommended repair:** Land #1954.
- **Potential impact:** Cosmetic; also the page's values are stale (21+ h) until the refresh repair is verified.
- **Dependencies:** #1954.
- **Activation requires owner approval?** No

### RPA-F-036 (low, SUSPECTED) Justin Madubuike is unresolved by the served identity policy while CANONICAL_V2 resolves him to 6818

- **Affected subsystem:** Player identity
- **Reproduction evidence:** The dual-read file (generatedAt 2026-10-25T12:03:37Z, 2,017 calls, v2WouldChange 27) shows V1 serving nothing and V2 resolving 6818. Whether V1 is wrong or V2 is right was not checked against ground truth; the other 26 divergences are mostly V2 refusing a plausible V1 match (for example Matt Judon, Michael Hall).
- **Data source and observed timestamps:** data/scrape_state/identity_dual_read.json on origin/main; the committed copy has been frozen since 10-25 12:03Z.
- **Status:** SUSPECTED
- **Existing owner or PR:** No PR. Items RPA-SRC-007, RPA-COL-009.
- **Fix authorized?** No. CANONICAL_V2 activation and its repair unit are not authorized (EXECUTION_PLAN:1444).
- **Recommended repair:** Classify the 27 examples against ground truth read-only; check Madubuike on the live board.
- **Potential impact:** One player may be missing from the board's identity join.
- **Dependencies:** Owner authorization of a V2 repair unit.
- **Activation requires owner approval?** Yes

### RPA-F-037 (low, SUSPECTED) The KTC crowd-FAAB freshness gate keys on fetch time, so a frozen feed would stay 'fresh' for seven days

- **Affected subsystem:** FAAB market evidence
- **Reproduction evidence:** updatedAt is the fetch time and drives the 7-day maxFileAgeDays gate; the newest claim date (2026-10-25, day granularity) is not used. New-row yield has decayed to 0-6 per three-hour run. Inferred from code and file fields.
- **Data source and observed timestamps:** Box file reads, 2026-10-26.
- **Status:** SUSPECTED
- **Existing owner or PR:** No PR. Item RPA-COL-029.
- **Fix authorized?** Yes (evidence collector).
- **Recommended repair:** Gate on newest row date as well, or alert on N consecutive '+0 new' runs.
- **Potential impact:** The crowd market could be quoted from a stalled feed.
- **Dependencies:** None.
- **Activation requires owner approval?** No

### RPA-F-038 (low, CONFIRMED) Four of 32 Hill refit runs lost their evidence to a push race, and bot commits add churn to main

- **Affected subsystem:** Hill autopilot / repository churn
- **Reproduction evidence:** Runs on 10-20 00:02Z, 10-21 01:05Z, 10-21 14:14Z and 10-24 16:22Z failed with 'main advanced during evaluation; refusing stale write'. About 4 refit evidence commits a day (28 since 2026-10-18) and about 8 Sharp smoke record commits a day land on main.
- **Data source and observed timestamps:** gh run list and git log, 2026-10-26.
- **Status:** CONFIRMED
- **Existing owner or PR:** No PR. Items RPA-COL-002, RPA-VAL-008, RPA-COL-016.
- **Fix authorized?** Yes (retry-on-race); Hill constants are never hand-edited.
- **Recommended repair:** Retry the refit commit on race; suppress the Sharp smoke record commits while the gate is unmeasured.
- **Potential impact:** Gaps in the forward-persistence series; extra deploys.
- **Dependencies:** None.
- **Activation requires owner approval?** No

### RPA-F-039 (low, CONFIRMED) Two feature-flag comments describe the opposite of the live state

- **Affected subsystem:** Feature flags (documentation in code)
- **Reproduction evidence:** The host_native_scoring comment still says OFF by default and 'a temporary champion/challenger gate' while production runs it ON (registry default False at feature_flags.py:734). The _GATE_STATUS comment for waiver_live_opportunity (lines 1144-1151) says it 'defaults False rather than True' while _DEFAULTS is True (line 752). The _DEFAULTS comment for that flag is internally consistent, which is why one assessor could not reproduce the stale comment.
- **Data source and observed timestamps:** git show origin/main f0f5eb2ce:src/api/feature_flags.py.
- **Status:** CONFIRMED
- **Existing owner or PR:** No PR. Items RPA-LGI-005, RPA-LGI-013, RPA-OPS-007.
- **Fix authorized?** Partly. A comment-only fix is routine; changing the host_native_scoring registry default is owner-reserved.
- **Recommended repair:** Correct both comments; record the host_native_scoring divergence deliberately (owner-approved default change or a tracked-divergence assertion).
- **Potential impact:** A reader trusts a comment over the running state.
- **Dependencies:** Owner decision on the standing state of host_native_scoring.
- **Activation requires owner approval?** No

## 3. Owner decisions possible now (group 1)

21 items. For each: the exact decision, and the evidence that makes it decidable today. Nothing here has been decided or implied by this report.

### D1. RPA-DRF-001 (P1) Rookie-draft order: median-game question (time-sensitive)

- **Decision needed:** Does dynasty_main's rookie-draft order rank teams on the official Sleeper record including league-median results, or on head-to-head results only? One yes/no answer.
- **Evidence:** config/leagues/draft_order_rules.json is silent on median games. Since #1712 standings and seeding count the median game, but the draft-order simulation ranks on head-to-head plus half-win ties and labels its forecasts with that interim basis. Two earlier drafts cannot settle it (the 2026 draft was an auction; the 2025 linear order matches neither reading). On 2026-10-26: 6 weeks played, 8 remaining, playoffs start week 15. Needed before the regular season ends (about mid-December 2026, inferred).
- **Status:** WAITING_ON_OWNER / OWNER_APPROVAL_REQUIRED

### D2. RPA-TRD-004 (P1) Forced-drop cheapest-legal fix V5-R: activation decision (dormant, flag OFF)

- **Decision needed:** Not an activation decision. Decide four things about the forced-drop cheapest-legal fix (flag forced_drop_cheapest_legal, OFF): (1) accept and state that its displayed net is not monotone, or change the accounting currency; (2) accept or reject the cheap-single-source-tail values; (3) authorize or decline a box re-run that breaks down favourable verdicts lost to Component B; (4) approve corrected copy C1-C3. Separately, decide the stand-alone cut-ladder tie-break repair.
- **Evidence:** Pinned production-box replay f10fc997 (generated 2026-10-22T03:05Z, merged via #1922): the incumbent names an irrational cut in 85 of 135 acquired-piece releases; the fix charges more on 49 of 180 and 36 of 278 trades; in 3,000 random upgrades 122 lowered the displayed net (worst -1,233) while the real roster improved; under a cheap-tail stress favourable verdicts fall from 103 to 9; 54 of 696 rostered players are unpriced. Two independent lanes found the incumbent's alphabetical tie-break is itself a defect. Analysis recommends not activating yet.
- **Status:** DORMANT_IMPLEMENTED / NEEDS_METHODOLOGY_REVISION

### D3. RPA-COL-007 (P2) Rank-form curve drift weekly audit

- **Decision needed:** As listed this is an ownership question for issue #898 (refit the rank-form reconstruction constants or retire the check). See the reconciliation: RPA-VAL-011 shows CQ-28 already authorizes the refit as engineering, so no owner approval is needed unless a consumer is shown to feed served values.
- **Evidence:** Weekly audit red on 10-06, 10-13 and 10-20 (and every run since 08-18 per the item): offense excess +74.6 and IDP +140.8 against a budget of 25; next run Tue 2026-10-27, the first on ubuntu-26.04.
- **Status:** COLLECTING_ACTIVE / OWNER_APPROVAL_REQUIRED

### D4. RPA-GOV-007 (P2) Agent infrastructure: Steward runtime, agent-eval harness, and the Codex 'Brisket Orchestrator' cron pointed at OneDrive

- **Decision needed:** Disable, delete or repoint the Codex 'brisket-orchestrator' automation (a local-machine action only you can take).
- **Evidence:** ACTIVE, daily 04:00, cwd the archived OneDrive copy that the 2026-10-21 directive says is archive-only. memory.md has four entries in seven months, the last on 2026-09-10, describing a scaffold repo that no longer exists. No evidence it has fired since about 09-10 (inferred; Codex logs were not inspected). Steward and agent-evals stay dormant. Same automation as RPA-COL-038.
- **Status:** DORMANT_IMPLEMENTED / OWNER_APPROVAL_REQUIRED

### D5. RPA-LGI-005 (P2) Host-native scoring (V1-49): live through an env override that diverges from the registry default

- **Decision needed:** Keep host-native scoring ON in production as the standing state, and either make the registry default match through an owner-approved PR or add an explicit tracked-divergence assertion? Also decide #1938 (nflverse scorer fixes that change BDVM in-season values).
- **Evidence:** Authorization for the controlled activation is on record (docs/VERSION_1_COMPLETION_CONTRACT.md line 1017, Packet C, 2026-08-25). Evidence (#1931, open): host-native points equal Sleeper's players_points on 3,710 of 3,710 player-weeks (dynasty_main weeks 1-6, max error 0.0044); the nflverse path matches 91.5%. Single league, six weeks, unmerged PR. Promotion to sole canonical scoring owner is not authorized and is not decidable yet.
- **Status:** WAITING_ON_OWNER / READY_FOR_DECISION

### D6. RPA-LGI-011 (P2) Unified Manager of the Year validation track (#1513)

- **Decision needed:** Rebase #1513 as a labelled validation candidate, or close it after porting the OD-MOTY intake text to main.
- **Evidence:** Owner Decision 12 (2026-10-18): remain experimental, official award unchanged. #1513 is CONFLICTING, 2,697 commits behind main, last commit 2026-09-29. The trade future-value half is not measurable (2024 0 of 29, 2025 0 of 124, 2026 25 of 69). The OD-MOTY text is absent from main. It cannot become official before 2027 either way.
- **Status:** WAITING_ON_OWNER / OWNER_APPROVAL_REQUIRED

### D7. RPA-LGI-012 (P2) Roster 12 manager hand-off: open owner items

- **Decision needed:** Roster 12 hand-off: confirm the cutover week, the new manager's real name, and Waiver King eligibility.
- **Evidence:** config/leagues/roster_ownership_changes.json records effectiveWeek 7 and still says 'PENDING OWNER CONFIRMATION'. The roster became ownerless 2026-10-20T05:20Z and has a new owner from 10-20T21:53Z. Week 7 is being scored now, so week-7 attribution depends on the answer. Waiver King ineligibility is keyed to the previous manager's user id; the new manager is eligible by default.
- **Status:** WAITING_ON_OWNER / OWNER_APPROVAL_REQUIRED

### D8. RPA-OPS-005 (P2) Backend memory policy canary (MemoryMax=3584M, no MemoryHigh) and memory-pressure diagnostics

- **Decision needed:** Approve, decline or defer the Stage 1 backend-memory canary (MemoryMax 3584M, no MemoryHigh) after re-reading the updated arithmetic.
- **Evidence:** The package (#1905) predates #1926. Declared ceilings now sum to 9,216 MiB against 7,941 MiB of host RAM (the recommended option sums to 8,704 MiB, 763 MiB over); margin -466 MiB. Live unit: MemoryHigh 2,560M, MemoryMax 3G, current 859 MB, peak 1.47 GB since the 09:35Z restart, zero cgroup throttle events. The throttle hypothesis is unconfirmed because no degraded-process snapshot was captured.
- **Status:** WAITING_ON_OWNER / OWNER_APPROVAL_REQUIRED

### D9. RPA-SRC-008 (P2) Chase Upside Trade Market shadow source (chaseTradeMarket P1-P6a) and reserve decision Q2

- **Decision needed:** Q2: the holdout reserve policy for the chaseTradeMarket shadow source, chosen from the #1907 lineage census alternatives.
- **Evidence:** The census (merged) gives component sizes and allocation alternatives. A 20% permanent reserve and the five-way split are explicitly not approved. The preregistration is a DRAFT, not frozen; no chase data directory exists on the box; the Sharp lane feeding it has 1 native-comparable trade; #1852 (the reserve mechanism) is open and DIRTY.
- **Status:** WAITING_ON_OWNER / NEEDS_PREREGISTRATION

### D10. RPA-SRC-009 (P2) Per-source rank digest retention: #804 capture lane, authorized but not implemented (perishable)

- **Decision needed:** Cadence for the per-source rank-digest capture (#804 evidence prerequisite): daily (recommended) or every build, and re-authorize a fresh implementation on current main.
- **Evidence:** Measured growth: every build 38.8 MB/day (about 14.2 GB/year), daily 3.2 MB/day (about 1.2 GB/year). The capture is authorized (EXECUTION_PLAN 0.4b) but #921 was closed unmerged and nothing has been captured. The loss is smaller than stated: raw per-source CSVs are recoverable from git history (45-1,327 committed versions per source); only per-build derived metadata is not.
- **Status:** WAITING_ON_OWNER / OWNER_APPROVAL_REQUIRED

### D11. RPA-SRC-011 (P2) Credentialed-source authorization posture (OD-01): IDPTC, DLF, Draft Sharks, IDP Show and Flock permissions

- **Decision needed:** For each of IDPTC, DLF, Draft Sharks, IDP Show and Flock: is the collection permitted under the provider's terms (record it as owner-reported, as was done for KTC and Signals), or should it be re-scoped?
- **Evidence:** Register row ODR-SRC-AUTH-POSTURE is HUMAN_ACTION_REQUIRED; the scope manifest shows IDPTC ABSENT and seven credentialed source keys with zero recorded authorization. The same statement feeds the OD-3 source-permission record that the public Trade Advisor launch gate requires (approvedSourcePermissionRecord is null; the advisor is OFF). No agent may write the record.
- **Status:** WAITING_ON_OWNER / OWNER_APPROVAL_REQUIRED

### D12. RPA-TRD-005 (P2) Low-value depth disclosure V4 shadow counters (LVA-P4): owner G3 shadow-window decision

- **Decision needed:** Start the low-value depth disclosure shadow window now, and for how long? Name the fire-rate review rule so the window is not open-ended.
- **Evidence:** Counters are merged dormant (#1908), aggregate-only, no display, held OFF at deploy. Design study: false-alarm rates 9.8% on non-flipping filler, 21.1% on base trades, 4.5% on own-league; 39% of own-league sides were not evaluable. It is unverified that the owner was ever asked. Starting needs one reviewed PR that flips the required flag state in the deploy verifier, updates the lock test and sets the box variable.
- **Status:** SHADOW_NOT_RUNNING / OWNER_APPROVAL_REQUIRED

### D13. RPA-VAL-004 (P2) IDP deep-tail native-value challenger (PROMOTION-ELIGIBLE but blocked)

- **Decision needed:** Close idp-deep-tail-native-v1 and retain the incumbent Hill/B4 tail, or commission a new preregistered continuous variant under the IDP accuracy program?
- **Evidence:** Preregistered replay (committed 2026-10-18) returned PROMOTION-ELIGIBLE on all seven checks, but the governance overlay is AUTO_PROMOTION_BLOCKED (no independent validation target exists, and DLF IDP and IDP Show are measured-dependent on IDPTC). The one clear gain is graded against its own provider; the independent target is flat and slips on safeties and linebackers; v1 adds a ~5% step at rank 500 with ~200 boundary inversions. The register and intake rows still read EVIDENCE_PENDING. No independent review or owner decision is recorded.
- **Status:** DORMANT_IMPLEMENTED / READY_FOR_DECISION

### D14. RPA-VAL-006 (P2) Joint robust-filter (outlier+sparse) shadow challenger, Batch 3 Unit F

- **Decision needed:** Authorize one final decisive backfill re-run of the joint robust filter and then close the experiment (or relabel the live timer census-only)?
- **Evidence:** Historical replay met its minimum sample and returned INCONCLUSIVE (projected additional weeks 0). The live pairing can never produce an h=7 observation: every pair is skipped on fingerprint mismatch (data_contract.py changed 54 times since 10-01). Post-hoc split: offense +0.030, IDP -0.033 (offense up, IDP down). The re-run is already authorized under the preregistration but has not been done since 2026-10-01 (about 7 minutes with full history).
- **Status:** SHADOW_RUNNING / READY_FOR_DECISION

### D15. RPA-VAL-007 (P2) Sparse-evidence estimator challenger (Batch 3 Unit E) and the single-source haircut collapse

- **Decision needed:** Should a single-family row that no healthy absent family contradicts keep its observation as the central value, with uncertainty carried separately? (README decision 1; decision 2 follows.)
- **Evidence:** Candidate C failed gate G2c (median ratio 3.335 against a ceiling of 2.0) while passing 7 of 8 gates, so the incumbent 0.30 haircut stays champion. The recorder has run twice daily since 2026-10-01 (47 records) with no evaluator and no preregistered horizon. If yes: preregister an outcome-based successor before anyone scores the ledger. If no: retire the recorder. CQ-10's named cases (Sneed, Travis Hunter) never appear in the shadow population.
- **Status:** SHADOW_RUNNING / NEEDS_PREREGISTRATION

### D16. RPA-VAL-008 (P2) Hill Autopilot OFFENSE challenger: gate 7 independent-validation target is empty, so promotion is structurally impossible

- **Decision needed:** Choose: (1) authorize a preregistration unit for an independent validation target (the owner-named candidate is the completed-trade ledger with KTC-derived parts excluded); (2) commission a one-off manual governance review of challenger v246; or (3) record that OFFENSE stays on the incumbent until a target exists. Also say whether the refit loop should keep committing about 4 evidence commits a day.
- **Evidence:** 187 run rows; all 91 new-schema runs report no_independent_validation_target (registry size 0). Latest run 2026-10-25T16:55Z: v246 (c 0.065, s 1.10) improvement 620.9 against 56.5 required, but only on lineage-dependent boards. Live constants are c 0.110, S 1.110 (champion v2). Nothing the loop does can add an independent observation. v246 would reach AUTO_PROMOTION_BLOCKED within 1-2 days (inferred) unless a code change resets its windows.
- **Status:** COLLECTING_ACTIVE / NEEDS_PREREGISTRATION

### D17. RPA-VAL-017 (P2) TE premium target basis is a constant, not league TE demand (2-TE calibration audit #785)

- **Decision needed:** Retire the 'make the TE basis league-demand-driven through an overlay' framing, and authorize the #785 TE-premium audit as a Stage-1 research unit with preregistered criteria?
- **Evidence:** The TE target basis is a constant (tepp). For dynasty_main the measured demand (two mandatory TE starters, no TE scoring premium) equals that constant, so the overlay framing has no in-scope consumer (fingerprint gating, dynasty_new out of scope, overlay withdrawn). The KTC-to-TE++ curve was fitted once on 2026-07-27 (n=73) and never re-fit. #785 has no comments since 2026-08-11 and is not in EXECUTION_PLAN.
- **Status:** NOT_STARTED / NEEDS_PREREGISTRATION

### D18. RPA-GOV-002 (P3) Live development tracker PR #1838 (undisposed) and owner-intent recovery #1336

- **Decision needed:** Close PR #1838 (the live development tracker) and mark docs/DEVELOPMENT_TRACKER.md historical, or keep a live tracker.
- **Evidence:** #1838 is a +5/-3 refresh of a file already on main; the tracker content has been frozen since 2026-10-19 22:55 and duplicates WORK_CLAIMS, EXECUTION_PLAN, COMPLETION_QUEUE and the RIT reconciliation. It still says 'D4 and D5 ON' (D4 is OFF).
- **Status:** WAITING_ON_OWNER / READY_FOR_DECISION

### D19. RPA-GOV-004 (P3) Scope candidates without disposition: sixth slot (R40/R44), OD-06, OD-07, RIT-088 realignment

- **Decision needed:** Four yes/no scope items: the sixth slot (register recommends option 1), OD-06 (user feedback and polling), OD-07 ('link any Sleeper account' onboarding), and RIT-088 (two divisions with strength-balanced schedules).
- **Evidence:** Register rows ODR-SIXTH-SLOT, ODR-OD-06 and ODR-OD-07 are HUMAN_ACTION_REQUIRED ('not covered by the directive'); RIT-088 is NOT_STARTED with no EXECUTION_PLAN or intake record. Nothing has moved since 2026-10-19. These are scope choices, not evidence questions.
- **Status:** WAITING_ON_OWNER / OWNER_APPROVAL_REQUIRED

### D20. RPA-LGI-015 (P3) Game Day live-state provider trial (BALLDONTLIE shadow, SportsDataIO fallback) and CFBD key

- **Decision needed:** Continue the BALLDONTLIE live-state trial (install a free key and run one live Sunday in shadow) or park it.
- **Evidence:** The trial's premise was an ESPN block; box journals show live_game_state 403s only from 2026-09-26 to 10-01 and none since, and espn_scoreboard.jsonl grows every tick. BALLDONTLIE has no period or clock and its free tier (5 requests/min) cannot cover 13+ concurrent games. No credential exists; no provider response has been captured.
- **Status:** WAITING_ON_OWNER / INSUFFICIENT_EVIDENCE

### D21. RPA-SRC-010 (P3) Unpreserved DLF structural diagnostic work (uncommitted worktree touching the production fetcher)

- **Decision needed:** Preserve the uncommitted DLF structural-diagnostic work to a pushed draft branch, or discard it.
- **Evidence:** Exists only as uncommitted edits (+273/-2 over three files plus two untracked tests) in C:/Users/jason/code/calculator-performance-ops-1338; tip afb4182fd is an ancestor of main, no remote branch or PR, and scripts/fetch_dlf.py has since changed. Its trigger (the September DLF outage) was repaired by #1411, #1424 and #1430. It reads DLF credentials from the app .env on the production box, so keeping it also needs the credentialed-source posture (RPA-SRC-011). Do not delete the worktree.
- **Status:** WAITING_ON_OWNER / ENGINEERING_NOT_READY

## 4. Active engineering (group 2)

44 items: authorized work that needs engineers or coordinators, not an owner decision. Sorted by priority.

| Item | Pri | What it is | Status | Stage | Where it stands, and the next step |
|---|---|---|---|---|---|
| RPA-COL-010 | P1 | IDP identity capture U2/U2b/U3/VID (collect-only provenance) | COLLECTING_ACTIVE / INSUFFICIENT_EVIDENCE | s3 | IDP identity capture (collect-only) stopped uploading at 2026-10-25 12:06Z when the browser fetch broke, and covers 3 boards of about 27; box copies sit under a doubled data/data path the 30-day pruner may not reach. Next: confirm uploads resume before the 2026-11-04 G1 checkpoint. |
| RPA-COL-015 | P1 | Completed-trade market ledger rebuild | COLLECTING_ACTIVE / ENGINEERING_NOT_READY | s6 | The completed-trade ledger rebuilt on 2026-10-26 after #1926 (reports for 10-24 and 10-25 are missing); it holds 37,089 observations and 1 native-comparable trade. Next: missed-report alert and a streamed persist before the 2 GiB memory ceiling (about six weeks). |
| RPA-COL-016 | P1 | Sharp cohort crawl chain (discovery, records, rosters, activity, cohort snapshot, FFPC) and production population verification | COLLECTING_ACTIVE / INSUFFICIENT_EVIDENCE | s6 | The Sharp discovery, records, roster and activity passes hit their budgets and exit 2, which systemd records as success; the oldest records crawl is 82 days old, the intel ledger is 800 MB, and four temporary Sharp workflows remain active. Next: report the fraction of the queue covered per run; set a ledger retention plan. |
| RPA-COL-027 | P1 | BDVM weekly projection refresh and news-to-events ingestion | COLLECTING_ACTIVE / ENGINEERING_NOT_READY | s6 | BDVM's weekly refresh builds a baseline and merges Mike Clay's guide, but the IDP Show projection feed has never produced a record and the unit still reports success. Next: land #1959 (honest failure reporting, IDP Show parser to shadow); verify the Tue 2026-10-27 run; merging parsed records into snapshots is an owner decision. |
| RPA-COL-032 | P1 | Retention backups, restore proofs and auction backup | COLLECTING_ACTIVE / INSUFFICIENT_EVIDENCE | s6 | All backup units are green, but coverage of the temporal ledger, DFS workspace, intel ledger and receipts cannot be confirmed without root, the health stamp reads the wrong directory, and no off-box mirror exists. retention-health was red on 26 of 40 runs. Next: root listing, restore proof without the optional-skip, health-stamp fix; owner decides the off-box mirror. |
| RPA-DRF-003 | P1 | Rookie Auction Room official launch and Phase 2 (#1533) | IMPLEMENTATION_ACTIVE / ENGINEERING_NOT_READY | s2 | The Auction Room base is live in mock mode; the independent-audit fixes are not on main. #1533 is conflicting with a failing test; #1950 (draft) carries the merge with main and supersedes it. Next: review security fixes first, exact-head CI, merge; official launch stays gated. |
| RPA-LGI-001 | P1 | Live Sleeper scoring/rules parity audit (#1842/#1843, Stage A) | IMPLEMENTATION_ACTIVE / NOT_A_PROMOTION_CANDIDATE | s1 | The live scoring and rules parity audit has 4 of 9 boxes evidenced, all on unmerged PRs (#1843, #1931, #1948). Next: land #1843, #1931, #1948, then #1951; tick #1842 boxes 1-4; file follow-ups for the six remaining defects and the stale snapshot. |
| RPA-LGI-004 | P1 | Game Day calibration scorecard (AL-4a) and projection scorecard (AL-3b), plus AL-3c/3d challengers | SHADOW_NOT_RUNNING / ENGINEERING_NOT_READY | s4 | The Game Day and projection scorecards are merged but nothing schedules them, and no pregame_projections archive exists, so the projection scorecard has no scorable week. Next: run AL-4a once and schedule it weekly; build the archive before the week-8 kickoff (about 2026-10-29). |
| RPA-LGI-008 | P1 | Best-ball sim points-model calibration (LI-8) and League Twin: validation not inspected | SHADOW_NOT_RUNNING / NEEDS_PREREGISTRATION | s1 | The calibrated sim points model was never built on the box, so every production best-ball simulation uses fallback constants. Next: offline calibration on 2025 plus 2026 weeks 1-7 under a preregistered gate, with a scheduled builder. |
| RPA-OPS-010 | P1 | Dependency and vulnerability backlog (16 open dependabot PRs, 111 alerts) | NOT_STARTED / ENGINEERING_NOT_READY | s0 | 111 dependency alerts (12 critical) are open; the three PRs that would clear 100 are red on a lock check. #1955 (draft) supersedes them. Next: land it after box verification, then the frontend train. |
| RPA-TRD-007 | P1 | Multi-team private analysis enablement: Lane E QA and D-net loopback bind (claimed, never started) | IMPLEMENTATION_ACTIVE / ENGINEERING_NOT_READY | s4 | The N-team engine is merged dormant behind trade_multi_team_analysis (OFF). Lane E QA is a draft stack (#1935 to #1937/#1946, with #1949); #1930 was closed unmerged on 2026-10-26. Next: independent review, the two spec decisions, a green scheduled E2E, then a normal-release flag flip. |
| RPA-VAL-013 | P1 | IDP valuation accuracy program (2026-10-25 directive, shadow only), including Investigation B IDP replacement/scoring research | IMPLEMENTATION_ACTIVE / NEEDS_PREREGISTRATION | s1 | The IDP valuation accuracy program (shadow only) is active. Lanes A and C are now PRs #1931 and #1936, with further lane drafts #1940-#1943 and #1945; the backtest preregistration (IDPV-8) does not exist. Next: commit the evidence, write the preregistration before any held-out measurement, route the four nflverse defects. |
| RPA-COL-002 | P2 | Hill refit challenger loop and autopilot run ledger | COLLECTING_ACTIVE / NEEDS_PREREGISTRATION | s4 | The Hill refit loop runs after each data refresh and its challenger passes every gate except gate 7 (no independent validation target), so promotion is structurally blocked. 4 of 32 runs lost their evidence to a push race. Next: retry the commit on a race; the target question is the owner decision under RPA-VAL-008. |
| RPA-COL-004 | P2 | Sparse-evidence estimator shadow ledger | SHADOW_RUNNING / ENGINEERING_NOT_READY | s3 | The sparse-evidence shadow recorder writes twice daily but nothing evaluates it, and its input directory is not fixed. Next: add an evaluate step and preregistration; record source-content age beside board age. |
| RPA-COL-012 | P2 | DLF and IDP Show box fetch with commit-back | COLLECTING_ACTIVE / NOT_A_PROMOTION_CANDIDATE | s6 | DLF and IDP Show are fetched on the box every 2 hours and pushed to main. DLF votes rank-only (Value column unavailable), a timeout once exited clean, and /api/health reads dead session copies. Next: land #1956; make a fetch Traceback non-zero. |
| RPA-DRF-004 | P2 | Perfect Draft backtest: blocked, needs a pre-draft snapshot captured before the 2027 auction (perishable) | NOT_STARTED / ENGINEERING_NOT_READY | s1 | The Perfect Draft backtest is blocked: no pre-draft board-plus-roster snapshot was ever captured and the capture is manual. Next: automate the pre-auction capture; the next real auction is after the 2027 class window opens on 2027-05-01. |
| RPA-GOV-003 | P2 | Status-record freshness: completion ledger/dashboard, family files, COMPLETION_QUEUE, HANDOFF.md, and stale owner-register rows | COLLECTING_STALE / NOT_A_PROMOTION_CANDIDATE | s6 | The completion dashboard, family evidence files, COMPLETION_QUEUE, HANDOFF.md and several register rows date from 2026-10-07 to 10-19 and contain claims the code now contradicts. Next: a coordinator records pass; choose which denominator is live. |
| RPA-LGI-003 | P2 | Multi-source projection ensemble (#854, C5-PROJ-A..F) | WAITING_ON_DEPENDENCY / INSUFFICIENT_EVIDENCE | s4 | The weekly projection ensemble is a single-family passthrough (Sleeper/RotoWire); no pregame projection archive exists for weeks 3-7 and no leakage-safe backtest has run. Next: build the pregame archive (shared with RPA-LGI-004). |
| RPA-LGI-006 | P2 | Playoff/title odds: ROS double count (D11) and season-end calibration (AL-5a/5b/5c) | WAITING_ON_DEPENDENCY / NEEDS_METHODOLOGY_REVISION | s4 | The preregistered playoff-odds comparison passed 5 of 6 gates and failed calibration (G4), so the incumbent stays; the points model it ran on is uncalibrated. Next: calibrated points model in shadow, a dual-arm recorder and a new preregistration; season-level calibration waits for January 2027. |
| RPA-LGI-010 | P2 | Team Strength / Power Rankings v2: team VORP missing, WAR/WAB (C5-WAR-01) absent | NOT_STARTED / NEEDS_PREREGISTRATION | s0 | Power Rankings v2 runs without its team VORP component (its 0.15 weight is redistributed); live results share is 68.9% against the owner's 0.70 target. Next: re-verify #1340 on production; build team_vorp as a shadow candidate. |
| RPA-LGI-017 | P2 | Waiver lineup-legality and Perfect Waivers validation (C2-DROP-01, C7-WAIV-01, #899) | IMPLEMENTATION_ACTIVE / INSUFFICIENT_EVIDENCE | s5 | Perfect Waivers is live (23 requests 2026-10-20 to 10-26) with unit tests only and no outcome backtest. Next: backtest weeks 1-7 against realized best-ball lineups; verify and close #899. |
| RPA-OPS-002 | P2 | Public /league latency and Production E2E Smoke failures (unclaimed) | NOT_STARTED / INSUFFICIENT_EVIDENCE | s0 | Public /league has a 44-second cold path and the 4-hourly smoke monitor fails on it; nobody owns it. Next: open a claim, measure the cold build on the box, and warm or serve stale-while-revalidate. |
| RPA-OPS-004 | P2 | Deploy restart decoupling: D-1 data-only release (declined), D-2 conditional startup scrape (#1929), D-3 paths-ignore (#1925) | IMPLEMENTATION_ACTIVE / OWNER_APPROVAL_REQUIRED | s6 | #1925 (skip deploys for prose and test-only changes) is merged; #1929 (conditional startup scrape, default OFF) is open; restarts fell from 12-13 to 8 a day. Next: merge #1929 dormant and measure three full days; activation is an owner call. |
| RPA-OPS-006 | P2 | KTC/IDPTC scrape outage 2026-10-22/23: root cause (aged-process/throttle hypothesis), including the unverified IDPTC ~979-row partial incident | NOT_STARTED / INSUFFICIENT_EVIDENCE | s1 | Root cause of the 2026-10-22/23 KTC/IDPTC scrape outage is unknown and its evidence is gone. Next: add a cgroup and pressure capture to the stall path; close the unverifiable 979-row claim. |
| RPA-OPS-007 | P2 | Feature-flag registry vs production state, and held-flag lock coverage gaps | LIVE / NOT_A_PROMOTION_CANDIDATE | s6 | The 61-flag registry matches production except host_native_scoring; nine owner-reserved OFF flags are not in the deploy-time hold. Next: extend OWNER_HELD_FLAGS and record the host-native authorization. |
| RPA-OPS-012 | P2 | Learning receipts coverage (AL-P5 beyond Best Offers), Sharp trade retention before the 400-day prune (AL-P7), and the Adaptive Learning / Model Lab umbrella | COLLECTING_ACTIVE / ENGINEERING_NOT_READY | s3 | Learning receipts exist for Hill, the shadow recorders and Best Offers decisions only; nothing for finder, suggestions, angle, FAAB or Perfect Draft, and Sharp trade movements reach the 400-day prune on 2027-06-08. Next: CQ-45 after CQ-22 frees the shared files. |
| RPA-SRC-003 | P2 | Signals Fantasy IDP voting: per-family DL/LB/DB and the Candidate F crosswalk (held) | DORMANT_IMPLEMENTED / NEEDS_MORE_DATA | s4 | Signals IDP voting is held: six flags OFF, collector healthy, but the vendor IDP board has been static since 2026-10-21. Next: run the on-box diagnose and gate dispatches and a health probe; put proposed decisions 1-4, 6 and 8 to the owner; R1 deadline 2026-11-16. |
| RPA-SRC-006 | P2 | KTC/IDPTC last_success freshness stamps come from the GH-runner scrape, not the box scrape that serves data | COLLECTING_STALE / ENGINEERING_NOT_READY | s6 | The fetch-success stamps for KTC, IDPTC and DraftSharks are written only by the GitHub runner and were 24 hours old while the box scrape was live. Next: the manual post-pin run advanced them (2026-10-26T12:50-12:53Z); confirm a scheduled run does too, then scope one unit to settle stamp ownership and re-derive the 6-hour budgets. |
| RPA-TRD-002 | P2 | fairness_bands_v2 post-launch validation (OD-F4), history-vs-public alignment (OD-F6), and the +/-200 How-It-Aged prior | NOT_STARTED / NEEDS_PREREGISTRATION | s5 | fairness_bands_v2 is live as an owner-approved prior; the validation study (OD-F4) has no preregistration or harness. Next: draft the OD-F4 preregistration and get the pass rule signed; fix CQ-23's v1 wording. |
| RPA-VAL-010 | P2 | Source-quality evaluator and weight challengers (B3-B/C, AL-1b..d) plus dynamic_source_weights | SHADOW_NOT_RUNNING / NEEDS_PREREGISTRATION | s2 | All three learned source-weight challengers failed gate G1; the equal-family champion is retained. AL-1b..d have no claim or branch. Next: an Integration decision to claim AL-1b and write the second preregistration (panel history is only now long enough). |
| RPA-VAL-011 | P2 | Rank-form curve drift: stale reconstruction Hill constants (#898) | NOT_STARTED / EVIDENCE_SUPPORTS_ADVANCEMENT | s2 | The rank-form reconstruction constants are 3x to 8x over budget, the weekly audit has been red for ten weeks, and the Terminal team-value chart uses them. CQ-28 authorizes the refit (blocker NONE) but nobody has claimed it. Next: claim CQ-28. |
| RPA-VAL-014 | P2 | LI-5 replacement-level consolidation (C2-REPL-01, LVA-P3) | IMPLEMENTATION_ACTIVE / EVIDENCE_SUPPORTS_ADVANCEMENT | s2 | LI-5 replacement-level consolidation: P1-P2 merged unwired and P3 (#1927) is now MERGED dormant (flag OFF, deploy-locked); follow-ups are in draft #1944. Next: review #1944, scope the box replay and the stability collector; activation criteria are not defined. |
| RPA-GOV-001 | P3 | Coordination records: stale WORK_CLAIMS rows and the 14-day RIT reconciliation (#1924) | LIVE / NOT_A_PROMOTION_CANDIDATE | s6 | WORK_CLAIMS was cleaned to 5 open or claimed rows after #1924, but about 25 in-flight PRs have no claim row, the #1533 row is stale, and the main ruleset has no required checks. Next: one records PR; raise the protection gap with the owner. |
| RPA-GOV-008 | P3 | Workspace hygiene: stranded branches, stale worktrees, and uncommitted leftovers | NOT_STARTED / NOT_A_PROMOTION_CANDIDATE | s0 | 88 local worktrees (40 on merged branches, 29 with no PR); one holds 10 uncommitted files of possibly unlanded hardening. Nothing was removed. Next: diff-review before any deletion; never stash or commit -a. |
| RPA-LGI-007 | P3 | Best-ball true marginal utility library (Stage C, offline, no consumer) | DORMANT_IMPLEMENTED / NEEDS_PREREGISTRATION | s4 | The best-ball marginal-utility library is merged with no consumer, no numeric gate and no holdout. Next: preregister numeric gates before touching the holdout; keep it unwired. |
| RPA-LGI-009 | P3 | Schedule Intelligence remainders: the B league-valid calendar, C, D, and E MVP win-impact (#1530) | NOT_STARTED / NOT_A_PROMOTION_CANDIDATE | s4 | Schedule Intelligence parts B-remainder, C, D and E are not started; the docs wrongly say E is blocked on C5-WAR-01, which merged as #1692. Next: correct the docs, then take the next item in dependency order. |
| RPA-LGI-014 | P3 | FAAB engine re-evaluation (AL-8 loop) and market extension with Sleeper heat and Sharp bids (#830) | COLLECTING_ACTIVE / NEEDS_PREREGISTRATION | s1 | FAAB collectors are healthy; the engine has one backtest and no owner for the re-evaluation loop (AL-8). Next: assign an owner and preregister acceptance before building Sharp bid ingestion. |
| RPA-LGI-018 | P3 | Public waiver-compare page: public/private boundary review | COLLECTING_STALE / NOT_A_PROMOTION_CANDIDATE | s6 | The unlisted public waiver-compare page exposes only vendor values and Sleeper-public rosters; its values were 21+ hours stale because of the refresh failure, and its labels show mojibake (#1954). Next: record the boundary conclusion. |
| RPA-LGI-019 | P3 | Knowledge-cutoff replay and the missing as-of roster store (team-context replay deferred) | NOT_STARTED / ENGINEERING_NOT_READY | s4 | Leakage guards for as-of reads are merged (#1864), but there is no as-of roster, projection or posture store and nothing calls the replay. Next: design a roster-reconstruction owner from Sleeper transactions. |
| RPA-OPS-011 | P3 | Performance follow-ups (#1622) and abandoned Codex performance worktrees | NOT_STARTED / INSUFFICIENT_EVIDENCE | s1 | Codex-era performance branches (62, 45, 37, 34, 24, 6, 1 commits ahead) and a 33 GB local folder are unlanded; #1622 is unclaimed. Next: tree-diff each against main, archive anything unique, then remove the worktrees. |
| RPA-TRD-006 | P3 | Low-value asset program umbrella (recommendation R-C: informational disclosure only) | DORMANT_IMPLEMENTED / NOT_A_PROMOTION_CANDIDATE | s4 | The low-value-asset program is research-complete with dormant children (forced-drop, depth shadow, LI-5); its integration report still says every decision is PENDING. Next: annotate it as superseded; land #1944 after review. |
| RPA-TRD-009 | P3 | Trade decision engine v3 shadow challenger (League Intelligence Stage E) and evidence-lineage registry | SHADOW_NOT_RUNNING / NEEDS_PREREGISTRATION | s4 | The decision-engine v3 library is merged with no importer, no seam flag and no runner. Next: freeze promotion gates, register the default-OFF seam flag, build a receipts-only runner. |
| RPA-TRD-010 | P3 | Analyze Trade v3 branch: stranded, no PR (#792 Batch 4) | SUPERSEDED / NOT_A_PROMOTION_CANDIDATE | s1 | claude/analyze-trade-v3 (12340208f, one commit, +4,191/-96) is stranded with no PR and is partly superseded by main. Next: tag it, extract the methodology doc, record the disposition in CQ-14, delete the branch. |
| RPA-TRD-012 | P3 | Monte Carlo trade simulator audit TODOs and band-width re-audit (#790) | IMPLEMENTATION_ACTIVE / INSUFFICIENT_EVIDENCE | s5 | The Monte Carlo simulator is live with a synthetic flat +/-15% band against a measured 3.57% weekly half-width; there is no current-head audit. Next: run the #790 checklist read-only and re-measure with in-season data. |

## 5. Collecting, waiting on a sample or a date (group 3)

31 items, mostly collectors. Dates are the ones the evidence names; "inferred" means the auditor computed it.

| Item | Pri | What it is | Status | Stage | Where it stands, and the date or trigger |
|---|---|---|---|---|---|
| RPA-COL-020 | P1 | Game Day live collector and Sleeper weekly projection archive (AL-P8 / G1) | COLLECTING_ACTIVE / NOT_A_PROMOTION_CANDIDATE | s6 | The Game Day live collector is healthy; the pregame projection archive has never run. First build expected when Sleeper flips to week 8 (about 2026-10-27 to 10-29); weeks 1-2 projections are permanently lost. |
| RPA-COL-021 | P1 | Game Day pregame prediction capture | COLLECTING_ACTIVE / NOT_A_PROMOTION_CANDIDATE | s6 | Pregame prediction capture works again after #1926 (about 17 unseen failed runs 10-23 to 10-26, no snapshot lost). Week-8 capture must land before the first kickoff at 2026-10-30T00:15Z. |
| RPA-COL-026 | P1 | Temporal ledger, board history and daily board snapshot (C1-U4) | COLLECTING_ACTIVE / NOT_A_PROMOTION_CANDIDATE | s6 | The temporal ledger records daily (5.0M observations, 2.25 GB) except the 2026-10-23 hole; backup coverage unverified (see the backup finding). No sample gate; durability work only. |
| RPA-OPS-003 | P1 | E2E Safety Net repair (#1918 / #1923) | WAITING_ON_DEPENDENCY / NEEDS_MORE_DATA | s6 | The E2E fix (#1923) is merged and green on its branch; no scheduled main run has completed since. Close #1918 only on a green scheduled run (due about 12:00Z on 2026-10-26; none had appeared at 13:13Z). |
| RPA-COL-003 | P2 | Joint robust-filter shadow ledger | SHADOW_RUNNING / INSUFFICIENT_EVIDENCE | s3 | The joint-filter shadow ledger (5.5 MB, twice daily) returns INSUFFICIENT on every run. Wait on the owner decision in RPA-VAL-006; no date. |
| RPA-COL-005 | P2 | Consensus Edge daily snapshot and outcome labelling | SHADOW_RUNNING / INSUFFICIENT_EVIDENCE | s3 | The Consensus Edge store holds 91,180 rows over 83 dates (one day, 2026-10-05, missing) with 54,993 labelled outcomes. Wait on in-season folds; add a skipped-day alert. |
| RPA-COL-006 | P2 | Consensus Edge weekly revalidation | COLLECTING_ACTIVE / INSUFFICIENT_EVIDENCE | s3 | The weekly Consensus Edge revalidation was red ten weeks, green on 10-14 and 10-21, verdict 'do not ship yet'. Next run Wednesday 2026-10-28. |
| RPA-COL-008 | P2 | Hampel dropped-source weekly audit | COLLECTING_ACTIVE / INSUFFICIENT_EVIDENCE | s6 | The Hampel dropped-source audit failed once (DraftSharks 15.2% against 15%) while that source's fetch was compromised. The 10-26 run had not appeared at 12:10Z; re-read it after the refresh repair. |
| RPA-COL-009 | P2 | Identity dual-read measurement and identity match audit | COLLECTING_ACTIVE / NEEDS_MORE_DATA | s6 | Identity dual-read: served policy diverges from the legacy ladder 0 times; CANONICAL_V2 would change 27 of 2,017 calls (1.3%, up 3 in nine days). The committed copy is frozen at 2026-10-25T12:03Z until the refresh repair is verified. |
| RPA-COL-011 | P2 | Signals Fantasy collectors (auth-renew, public fetch, authenticated values) | COLLECTING_ACTIVE / INSUFFICIENT_EVIDENCE | s6 | Signals collectors are healthy; offense publishes daily, the authenticated IDP board is frozen at 2026-10-21T15:05Z (public boards still advance). Dates: R1 deadline 2026-11-16; token expiry about early November (the doc's own unverified inference). |
| RPA-COL-013 | P2 | Multi-format KTC source archive (TE+/TE++ variants, C1-U9) | COLLECTING_ACTIVE / INSUFFICIENT_EVIDENCE | s3 | The KTC multi-format archive holds 192 boards (8 variants x 24 dates, 2026-10-02 to 10-26; 10-23 missing), box-local only. Wait on more samples; confirm backup inclusion. |
| RPA-COL-014 | P2 | KTC Trade Database accumulation | COLLECTING_ACTIVE / NOT_A_PROMOTION_CANDIDATE | s6 | KTC trade-database accumulation is healthy: 1,184 fetches since 2026-10-01, largest gap 0.77 h. Keep the 30-minute cadence; add a 2-hour gap alert. |
| RPA-COL-018 | P2 | ESPN depth-chart refresh | COLLECTING_ACTIVE / INSUFFICIENT_EVIDENCE | s4 | ESPN depth charts were 0/32 for 31 runs since 2026-09-06 and 32/32 on 2026-10-26 after #1926. First event-deriving run Tuesday 2026-10-27 05:20 CET. |
| RPA-COL-022 | P2 | Playoff/title forecast archive (AL-P6) and as-known news metadata archive (G4) | COLLECTING_ACTIVE / NEEDS_MORE_DATA | s6 | Forecast archive (416 records) and news archive (3,293 records) accumulate. Season-level calibration waits for January 2027; no backfill before 2026-10-02 / 10-08. |
| RPA-COL-023 | P2 | Pick forecast / team strength weekly snapshot (AL-P4) | COLLECTING_ACTIVE / NEEDS_MORE_DATA | s6 | Pick-forecast snapshots: 7 keys since 2026-10-06. Next firing Tuesday 2026-10-27 12:21Z; calibration needs final 2026 standings (about mid-December 2026) and a second class. |
| RPA-COL-024 | P2 | Learning receipts store | COLLECTING_ACTIVE / NOT_A_PROMOTION_CANDIDATE | s6 | The learning receipts store holds 2,076 receipts and 0 corrections; no rows yet from three registered producers; backup membership unverified. |
| RPA-COL-029 | P2 | KTC crowd FAAB market accumulation | COLLECTING_ACTIVE / NEEDS_MORE_DATA | s6 | KTC crowd-FAAB ledgers hold about 3,400 rows each; 50 of 200 and 27 of 200 comparable. No IDP league exists in the feed, so DL/LB/DB cannot be priced. Add a content-freshness gate. |
| RPA-COL-031 | P2 | ROS rankings aggregate and ROS source collectors | COLLECTING_ACTIVE / NOT_A_PROMOTION_CANDIDATE | s6 | The ROS aggregate is current (five sources, written 2026-10-26 09:34Z) but one source body is 12 days old under status ok and one orphan file exists. Fix: draft #1958 (kept_previous status and content clock; reporting only). |
| RPA-COL-037 | P2 | Weekly narratives generation (export mode) | COLLECTING_ACTIVE / NOT_A_PROMOTION_CANDIDATE | s6 | Weekly narratives export on schedule except the Week 6 recaps (failed 2026-10-20, never re-exported). Next fires Tuesday 2026-10-27 14:00Z (W7 recaps) and Wednesday 10-28 13:00Z. |
| RPA-DRF-002 | P2 | Draft valuation Batch D guarded promotion (dry_run) and the class state machine (#1807) | SHADOW_RUNNING / NEEDS_MORE_DATA | s4 | Rookie-class promotion is in dry-run: state FALLBACK_VERIFIED, 2027/2028/2029 classes served from the frozen fallback at $1,200 each. The class window opens 2027-05-01; no evaluation is possible before then. |
| RPA-OPS-001 | P2 | Box unit repairs (#1926): depth charts, market-trade ledger timeout, game-day capture false refusal | LIVE / NEEDS_MORE_DATA | s6 | #1926 repaired three box units; each has exactly one clean post-deploy run. Re-check after the 2026-10-27 05:20 and 09:56 runs and the week-8 capture (kickoff 10-29/30), then close #1409. |
| RPA-TRD-001 | P2 | Package model geom_q078_v1: market-ledger prospective evaluation (#1873), with Phase 1-3 research and the fairness_v2 re-measure | WAITING_ON_DEPENDENCY / NEEDS_MORE_DATA | s5 | geom_q078_v1 is active (Phases 1-3 said KEEP; owner approved 2026-10-20). The fully independent prospective confirmation needs at least 2,000 post-2026-10-20 unequal trades (early to mid November, inferred) and separate owner authorization to run on the box. Do not merge #1873. |
| RPA-VAL-003 | P2 | D4 DLF Values rank->Hill offense vote (owner-held, flag OFF) | DORMANT_IMPLEMENTED / NEEDS_MORE_DATA | s4 | D4 (DLF Values offense vote) is merged dormant and OFF in production. It waits on outlier-integrity V2.1: identity prerequisites by 2026-11-04 and held-out data no earlier than 2026-11-25 (extension to 2026-12-02). |
| RPA-VAL-016 | P2 | Consensus Edge buy/sell board (flag OFF; ship gate 'do not ship'; outcomes accumulating) | COLLECTING_ACTIVE / EVIDENCE_SUPPORTS_REJECTION | s4 | Consensus Edge is OFF and its ship gate says 'do not ship yet' at both horizons on every run. Collection continues; take a retire-or-redesign decision if in-season folds keep failing. The 2026-10-14 CI artifact expires about mid-November. |
| RPA-COL-025 | P3 | AL-P5 served trade decision receipts log | COLLECTING_ACTIVE / NEEDS_MORE_DATA | s6 | 267 served trade decisions logged and converted in about eight days; retention and backup coverage undocumented. |
| RPA-COL-028 | P3 | Own-league FAAB bid history | COLLECTING_ACTIVE / NOT_A_PROMOTION_CANDIDATE | s6 | Own-league FAAB bid history refreshes daily and feeds the engine's market priors. Monitoring only. |
| RPA-COL-030 | P3 | Player-context collectors: trending history, playerctx, reception depth, PBP weekly | COLLECTING_ACTIVE / NOT_A_PROMOTION_CANDIDATE | s6 | Player-context collectors (trending, playerctx, reception depth, play-by-play) all succeeded; 2026 play-by-play is intentionally not built mid-season. Add weekly-feed freshness checks. |
| RPA-COL-033 | P3 | DFS auto-refresh tick (owner-paused area) | COLLECTING_ACTIVE / OWNER_APPROVAL_REQUIRED | s6 | The DFS auto-refresh tick runs every 10 minutes in an owner-paused area (947 MB workspace). Wait on the owner's keep-or-pause answer; NBA/NHL stay gated. |
| RPA-COL-035 | P3 | V1 failure classifier (report-only) | SHADOW_RUNNING / NEEDS_MORE_DATA | s3 | The report-only V1 failure classifier has classified one failure. Needs several more before its accuracy can be judged. |
| RPA-DRF-005 | P3 | Pick forecast market confidence 'c' calibration (provisional) and AL-P4 snapshot acceptance | COLLECTING_ACTIVE / NEEDS_MORE_DATA | s4 | The pick-market confidence c is provisional (0.5 x final-weeks share); calibration needs 24 pairs per bucket and two draft classes (about December 2027). Reconcile the acceptance wording now. |
| RPA-TRD-003 | P3 | Unvalidated trade-decision priors: discovery 'Most Impactful', Second Opinions 'even within 1%', KTC-era finder/angle priors, competitive posture_v1_prior | WAITING_ON_DEPENDENCY / NEEDS_PREREGISTRATION | s5 | Discovery weights, the Second Opinions 1% rule, KTC-era finder and angle thresholds and the posture map are live declared priors with no outcome target. No date; pick one outcome target per family. |

Dates to watch, in order:

| Date | What happens |
|---|---|
| 2026-10-26 (pending) | First scheduled refresh run after the #1939 pin (a manual run at 12:46Z already advanced the stamps); first scheduled E2E run after #1923. |
| 2026-10-27 05:20 CET / 09:56 CET | Second depth-chart run (first event-deriving run) and second market-trade ledger run. |
| 2026-10-27 | BDVM weekly refresh; pick-forecast snapshot (12:21Z); rank-form drift audit (first on ubuntu-26.04); weekly narratives W7 recaps (14:00Z). |
| 2026-10-28 | Consensus Edge weekly revalidation; weekly narratives W8 previews (13:00Z). |
| 2026-10-29 / 10-30T00:15Z | NFL week-8 Thursday kickoff: pregame prediction capture and the first pregame projection archive build must land before it. |
| 2026-10-31 / 11-01 / 11-07 / 11-15 | IDP source rehabilitation reviewBy dates. |
| 2026-11-04 | Identity-capture prerequisites must be live for the V2.1 G1 checkpoint (no extension). |
| early to mid November | About 2,000 post-2026-10-20 unequal trades expected for the package-model prospective confirmation (inferred); Signals refresh-token expiry about early November (unverified inference). |
| 2026-11-16 | Deadline for a qualifying Signals IDP release R1. |
| 2026-11-22 | FantasyPros IDP would self-quarantine if the vendor stays silent (inferred). |
| 2026-11-25 (extension 12-02) | Earliest ready date for V2.1 held-out boards. |
| about mid-December 2026 | Regular season ends; final 2026 standings fix the rookie-draft order (so DRF-001 needs its answer first). |
| about early December 2026 | Market-trade ledger reaches its 2 GiB memory ceiling at the current growth (the unit author's six-week estimate). |
| January 2027 | Season-level playoff and title calibration (AL-5b). |
| 2027-05-01 | Rookie-class window opens; promotion dry-run can first evaluate. |
| 2027-06-08 | First Sharp movement rows reach the 400-day prune. |

## 6. Blocked (group 4)

22 items. Group 4 also holds broken collectors whose fix is in an unmerged PR, because the assessors counted a defect with no landed repair as blocked.

| Item | Pri | What it is | Status | Stage | Blocked on, and the way out |
|---|---|---|---|---|---|
| RPA-COL-001 | P0 | Scheduled data refresh workflow and in-process box scrape loop | COLLECTING_STALE / ENGINEERING_NOT_READY | s6 | P0. The scheduled refresh fix (#1939) is merged. A manually dispatched run on ubuntu-24.04 (2026-10-26T12:46Z) installed Chromium and advanced the KTC, IDPTC and DraftSharks stamps to 12:50-12:53Z, so the repair works; the first scheduled run after the pin is still pending. Next: confirm that run, then add a content guard. Move to group 3 once a scheduled run advances the stamps. |
| RPA-COL-017 | P1 | Sharp transaction crawl, and Sharp/own-league format-at-trade-time capture | COLLECTING_BROKEN / ENGINEERING_NOT_READY | s6 | The Sharp transaction crawl is broken by 404 leagues tripping the breaker. Fix in draft #1957. |
| RPA-COL-019 | P1 | ESPN injury feed refresh | COLLECTING_BROKEN / ENGINEERING_NOT_READY | s4 | The injury feed parses nothing. Fix in draft #1952; activation of derived events is owner-gated. |
| RPA-COL-034 | P1 | Production smoke and E2E monitors | COLLECTING_BROKEN / ENGINEERING_NOT_READY | s6 | Production monitors are unreliable: smoke times out, the nightly E2E was red four nights (fix #1923 merged), the 10-23 outage is unexplained. Next: report the curl failure mode, add one retry, fix the cold path (RPA-OPS-002). |
| RPA-LGI-016 | P1 | Injury/availability: injury feed reports zero active injuries (suspected silent-empty) and the availability backtest | COLLECTING_BROKEN / ENGINEERING_NOT_READY | s4 | Same defect as RPA-COL-019 (injury parser). Fix in draft #1952; then run the availability backtest. |
| RPA-VAL-001 | P1 | Outlier integrity V2 / V2.1: layered source validation (gates the DLF IDP, D4 and freshness-v2 restorations) | WAITING_ON_DEPENDENCY / NEEDS_METHODOLOGY_REVISION | s1 | Outlier integrity V2 ended 'more research required'; V2.1 fails five criteria on development data and has had no commit since 2026-10-21. #1884 is conflicting and 346 commits behind. Dates: identity stamps live by 2026-11-04; held-out data no earlier than 2026-11-25. Owner decisions IV21-O2 and the AD3 registration defect are open. |
| RPA-COL-036 | P2 | Sharp production smoke | COLLECTING_BROKEN / BLOCKED | s4 | The Sharp production smoke has never measured anything. Blocked on an owner-held SHARP_SMOKE_TOKEN (or an owner choice to retire the check). |
| RPA-LGI-013 | P2 | Live Waiver Opportunity FAAB shadow: flag ON but zero shadow comparisons recorded | SHADOW_NOT_RUNNING / INSUFFICIENT_EVIDENCE | s3 | The live waiver-opportunity shadow flag is ON but 0 of 200 comparisons exist because the shadow only records inside a route nobody calls. Blocked on a server-side collector and repaired injury inputs. |
| RPA-OPS-009 | P2 | Sharp production gate cannot measure: no credential (#1727/#951) | WAITING_ON_OWNER / BLOCKED | s4 | Same gate as RPA-COL-036. Blocked on the owner provisioning SHARP_SMOKE_TOKEN; stop issue #951 collecting a comment per run. |
| RPA-SRC-001 | P2 | Universal freshness step schedule v2 (merged dormant, owner-held activation) | DORMANT_IMPLEMENTED / OWNER_APPROVAL_REQUIRED | s4 | Freshness schedule v2 is merged dormant and held OFF by the owner. Activation waits on outlier-integrity V2 validation (#1884, held-out data no earlier than 2026-11-25), a combined shadow run (FS-B6, no named owner) and owner approval (FS-B7). |
| RPA-SRC-004 | P2 | IDP source rehabilitation (IDP Show, IDPTC, FantasyPros IDP; D2 gate superseded) | WAITING_ON_DEPENDENCY / NEEDS_MORE_DATA | s1 | No IDP source can be rehabilitated now: IDP Show and FantasyPros wait on vendor publication, Signals on a vendor release plus owner decisions, DLF IDP on #1884. reviewBy dates: 2026-10-31 (signals, dlfIdp, dlfRookieIdp, fantasyProsIdp), 2026-11-01 (idpShowCombined), 2026-11-07 (fantasyNavigatorSf), 2026-11-15 (idpShow, dlfValuesSfTep). |
| RPA-SRC-005 | P2 | Source content staleness vs fetch freshness: withheld IDP Show/FantasyNavigator votes and stale vendor content | COLLECTING_ACTIVE / NEEDS_MORE_DATA | s6 | Content staleness is detected and stale votes are withheld as designed. Its older next action (renew the #1726 acknowledgment or re-mint the IDP Show cookie) is superseded: the IDP Show fetch is healthy. See the IDP Show reconciliation. |
| RPA-TRD-008 | P2 | Public Brisket Trade Advisor launch gate (owner-reserved) | DORMANT_IMPLEMENTED / BLOCKED | s4 | The public Brisket Trade Advisor is dormant and OFF. Launch is owner-reserved: five owner decisions are open and unasked (OD-3, AD-1, F-1, RF-1, LA-1) plus OD-4; the source-permission record depends on RPA-SRC-011. |
| RPA-TRD-011 | P2 | Adaptive Learning trade loop: translator readiness (AL-2b0), preregistered translator (AL-2b), latent price (AL-2c) | WAITING_ON_DEPENDENCY / ENGINEERING_NOT_READY | s1 | Translator readiness (AL-2b0) is not built; blocked on the ledger rebuild being healthy for two cycles and on undefined readiness thresholds. |
| RPA-VAL-002 | P2 | DLF IDP / DLF Rookie IDP vote restoration (owner-held, dlf_offense_only_vote ON) | WAITING_ON_DEPENDENCY / BLOCKED | s4 | DLF IDP voting stays held (flag dlf_offense_only_vote ON). Blocked on RPA-VAL-001 and an explicit owner activation; the incumbent filter would drop 31 valid votes and move 30 rows 34-54%. |
| RPA-VAL-012 | P2 | Multi-bridge IDP ladder (Lane 8 PR-B, Draft Sharks beside IDPTC) | DORMANT_IMPLEMENTED / NEEDS_PREREGISTRATION | s4 | The multi-bridge IDP ladder is merged dormant and OFF with one two-month-old prose-only measurement and no criteria. Blocked on a preregistered evaluation inside the IDP accuracy program and an owner decision. |
| RPA-VAL-015 | P2 | League-aware fair value v1 shadow challenger (successor to the withdrawn league-adjusted lens) | DORMANT_IMPLEMENTED / NEEDS_PREREGISTRATION | s4 | The league-aware fair-value shadow is merged but imported by nothing; its preregistration is a draft with every threshold unfrozen and two owner preconditions unrecorded. Blocked on both; the IDP directive may supersede it for IDP. |
| RPA-DRF-006 | P3 | Rookie/college prospect projections (C5-FIT-01 college translation, #803) | NOT_STARTED / BLOCKED | s0 | College-prospect translation (#803) is not started: no CFBD code, no design, BDVM returns no_projection for the 2026 rookie class. Blocked on the owner's free CollegeFootballData key decision. |
| RPA-GOV-006 | P3 | OWNER_PAUSED: DFS and League Tycoon (deployed DFS preserved) | WAITING_ON_OWNER / OWNER_APPROVAL_REQUIRED | s6 | DFS and League Tycoon are owner-paused; the deployed DFS keeps running. Blocked until the owner resumes; records-only housekeeping (#1755). |
| RPA-LGI-002 | P3 | Keyed weekly projection providers (Fantasy Nerds / SportsDataIO): blocked on license/spend | WAITING_ON_OWNER / OWNER_APPROVAL_REQUIRED | s4 | Fantasy Nerds and SportsDataIO adapters are merged but unregistered and uncredentialed. Blocked on the owner's key and spend decision (no automatic paid subscriptions). |
| RPA-SRC-007 | P3 | CANONICAL_V2 identity policy activation (unauthorized; v2WouldChange growing) | SHADOW_RUNNING / NEEDS_METHODOLOGY_REVISION | s3 | CANONICAL_V2 identity runs only as a dual-read watch; it is not authorized to serve and has no promotion criteria. Blocked on an owner-authorized repair unit and ground-truth classification of the 27 examples. |
| RPA-VAL-009 | P3 | Hill D2 rerun, source alignment, and lineage-dependence policy v1 instrument extensions (MD-3b), including correlated-source anomaly protection | WAITING_ON_DEPENDENCY / NEEDS_PREREGISTRATION | s2 | Hill D2 evidence is closed (no ancestry-safe holdout); lineage-policy instrument extensions (MD-3b) are not started; #804 has no owner. Blocked on a reviewed instrument unit and the capture decision (RPA-SRC-009). |

## 7. Retire or superseded (group 5)

7 items. Their remaining work is cleanup or records only. RPA-TRD-010 also carries the status SUPERSEDED but sits in group 2, because its remaining action is a branch disposition.

| Item | Pri | What it is | Status | Stage | Action |
|---|---|---|---|---|---|
| RPA-COL-038 | P3 | Codex 'Brisket Orchestrator' cron automation | DORMANT_IMPLEMENTED / NOT_A_PROMOTION_CANDIDATE | s4 | The Codex Brisket Orchestrator cron points at the archived OneDrive copy. Retire; same owner action as RPA-GOV-007. |
| RPA-GOV-005 | P3 | Deferred/not-authorized successors: Market Edge Lab, dynamic_source_weights, R14 private-offer capture, draft-capital stack rebuild (#1529), C1-U5 confidence naming, C1A unit 6 | NOT_STARTED / NOT_A_PROMOTION_CANDIDATE | s0 | Market Edge Lab, dynamic_source_weights, R14 private-offer capture, the draft-capital stack rebuild (#1529) and C1A unit 6 are parked, not authorized. Records fix only: the C1A header still calls C1-U5 deferred though #876 shipped. |
| RPA-OPS-008 | P3 | Dead/decorative flags cleanup: value_confidence_intervals, positional_tiers, unified_id_mapper, usage_signals (and dynamic_source_weights) | DORMANT_IMPLEMENTED / NOT_A_PROMOTION_CANDIDATE | s4 | Seven decorative or unreachable flags (all OFF) gate nothing. Retire in a behaviour-preserving cleanup PR; leave dynamic_source_weights documented as not authorized. |
| RPA-SRC-002 | P3 | FantasyPros IDP upstream clock (D5) remainder: dual-family duplicate-identity analysis | LIVE / NOT_A_PROMOTION_CANDIDATE | s6 | FantasyPros IDP's upstream clock is live and the duplicate-identity analysis is complete ('no amplification'). Records housekeeping only: the lineage defect still says open. Watch its freshness (self-quarantine near 2026-11-22, inferred). |
| RPA-TRD-013 | P3 | /trade pick-ownership unknown-state reader (named non-parity follow-up) | SUPERSEDED / NOT_A_PROMOTION_CANDIDATE | s5 | The /trade unknown-pick-ownership reader shipped on 2026-10-17. Close; correct the stale CLAUDE.md sentence. |
| RPA-VAL-005 | P3 | Closed/rejected outlier challengers: rank-space Hampel (whole and per-vote), IDP n=3 Hampel, outlier_disagreement_policy V1 (dormant code paths) | RETIRED / EVIDENCE_SUPPORTS_REJECTION | s4 | Four closed outlier challengers (rank-space, per-vote, IDP n=3, the corroborated V1 policy) are rejected or closed. Retire the three that V2 does not need; keep V1 as a comparator until V2 concludes. |
| RPA-VAL-018 | P3 | Scoring-fit flags ON for a withdrawn lens (idp_scoring_fit, reception_scoring_fit) and player-specific scoring fit (#803) | DORMANT_IMPLEMENTED / NOT_A_PROMOTION_CANDIDATE | s4 | idp_scoring_fit and reception_scoring_fit are ON for a lens that was withdrawn; their only consumer is an opt-in endpoint the client never calls. Retire or document as offline-only; fix the false Settings copy (#1954). |

## 8. Collector health

All 38 collectors. "Runs" is whether it executes on a schedule today. "Clock" is what the item's freshness measures: `fetch` (when we last asked), `content` (when the vendor data last changed) or `both`. "Silent-failure risk" is the assessor's rating of how long a failure could go unseen.

| Collector | Name | Runs | Last success | Clock | Silent-failure risk | Consumers | Group and status |
|---|---|---|---|---|---|---|---|
| RPA-COL-001 | Scheduled data refresh workflow and in-process box scrape loop | yes | 2026-10-26T08:07:07Z | both | high | data_contract._compute_unified_rankings (live board); dataset_state / freshness weighting; /api/status source_health; deploy.yml; refit-hill-curves.yml (dispatched after each refresh); shadow ledgers COL-003/004/005 | g4 COLLECTING_STALE |
| RPA-COL-002 | Hill refit challenger loop and autopilot run ledger | yes | 2026-10-26T08:08:40Z | fetch | medium | config/model_registry/ (champion/challenger records); scripts/model_registry.py promote/apply (human); docs/valuation Hill autopilot evidence | g2 COLLECTING_ACTIVE |
| RPA-COL-003 | Joint robust-filter shadow ledger | yes | 2026-10-26T07:58:08Z | fetch | low | src/model_registry/model_lab.py; src/model_registry/learning_receipt.py; scripts/outlier_policy_replay.py; scripts/idp_evidence_challengers.py | g3 SHADOW_RUNNING |
| RPA-COL-004 | Sparse-evidence estimator shadow ledger | yes | 2026-10-26T08:07:39Z | fetch | low | src/model_registry/model_lab.py; src/model_registry/learning_receipt.py; src/ros/forecast_archive.py (reference); none for valuation | g2 SHADOW_RUNNING |
| RPA-COL-005 | Consensus Edge daily snapshot and outcome labelling | yes | 2026-10-26T07:31:59Z | both | medium | src/consensus_edge/snapshot.py (labelling); validation and /edge surfaces via src/consensus_edge/service.py | g3 SHADOW_RUNNING |
| RPA-COL-006 | Consensus Edge weekly revalidation | yes | 2026-10-21T10:34:55Z | fetch | low | docs/measurements/ committed verdicts; Consensus Edge ship decision | g3 COLLECTING_ACTIVE |
| RPA-COL-007 | Rank-form curve drift weekly audit | yes | none recorded | fetch | low | issue #898 comments; reconstruction paths (terminal value fallback, rank_history backfill, frontend charts) | g1 COLLECTING_ACTIVE |
| RPA-COL-008 | Hampel dropped-source weekly audit | yes | 2026-10-12T16:46:08Z | fetch | low | workflow summary / red status only; RPA-SRC-005, RPA-VAL-001 evidence | g3 COLLECTING_ACTIVE |
| RPA-COL-009 | Identity dual-read measurement and identity match audit | yes | 2026-10-26T00:27:49Z | fetch | medium | src/api/data_contract.py (identityJoin stamp); src/retention/health.py; scripts/identity_parity.py | g3 COLLECTING_ACTIVE |
| RPA-COL-010 | IDP identity capture U2/U2b/U3/VID (collect-only provenance) | yes | 2026-10-25T12:06:57Z | fetch | medium | none for valuation (collect-only); scripts/verify_identity_capture_evidence.py; future V2.1 identity decisions | g2 COLLECTING_ACTIVE |
| RPA-COL-011 | Signals Fantasy collectors (auth-renew, public fetch, authenticated values) | yes | 2026-10-26T07:23:23Z | both | medium | data_contract (signalsSf voter in the fantasyCalc B10 family); private_source_availability; scripts/check_source_health.py; scripts/watchdog_freshness.py; IDP shadow translation (held) | g3 COLLECTING_ACTIVE |
| RPA-COL-012 | DLF and IDP Show box fetch with commit-back | yes | 2026-10-26T10:32:13Z | both | medium | data_contract (dlfSf, dlfRookieSf voting; idpShowCombined withheld); scheduled-refresh.yml DLF freshness guard; /api/health session_cookies; deploy.yml (CSV pushes) | g2 COLLECTING_ACTIVE |
| RPA-COL-013 | Multi-format KTC source archive (TE+/TE++ variants, C1-U9) | yes | 2026-10-26T01:03:01Z | fetch | medium | none in production valuation (collect-only); scripts/fetch_dynasty_nerds_idp.py (references the store) | g3 COLLECTING_ACTIVE |
| RPA-COL-014 | KTC Trade Database accumulation | yes | 2026-10-26T12:07:59Z | both | low | COL-015 ledger build; src/trade/market_trade_archive.py; src/trade/comparable_trades.py (via the ledger) | g3 COLLECTING_ACTIVE |
| RPA-COL-015 | Completed-trade market ledger rebuild | yes | 2026-10-26T08:57:22Z | fetch | medium | src/trade/market_trade_report.py; src/trade/comparable_trades.py; scripts/lineage_component_census.py; scripts/verify_signals_onbox.py | g2 COLLECTING_ACTIVE |
| RPA-COL-016 | Sharp cohort crawl chain (discovery, records, rosters, activity, cohort snapshot, FFPC) and production population verification | yes | 2026-10-26T05:10:28Z | fetch | high | frontend /market/sharp-tracker and /market/sharp-roster-percentage; /api/sharp/*; src/sharp/market.py; COL-015 ledger build (Sleeper lane); data/sharp/cohort snapshots | g2 COLLECTING_ACTIVE |
| RPA-COL-017 | Sharp transaction crawl, and Sharp/own-league format-at-trade-time capture | yes | 2026-10-26T08:29:14Z | fetch | high | COL-015 ledger (sleeper_sharp_discovery lane, 8,841 trades via this crawl); market_trade_normalize format selection; own-league trade grading | g4 COLLECTING_BROKEN |
| RPA-COL-018 | ESPN depth-chart refresh | yes | 2026-10-26T04:20:43Z | fetch | medium | src/bdvm/events.py; src/trade/faab_opportunity.py; BDVM projections | g3 COLLECTING_ACTIVE |
| RPA-COL-019 | ESPN injury feed refresh | yes | 2026-10-26T08:10:55Z | fetch | high | src/ros/availability.py; src/nfl_data/injury_return_evidence.py; data/bdvm/events (BDVM / FAAB speculation lane) | g4 COLLECTING_BROKEN |
| RPA-COL-020 | Game Day live collector and Sleeper weekly projection archive (AL-P8 / G1) | yes | 2026-10-26T11:18:15Z | both | medium | src/api/matchup_intel.py (Game Day payloads); scripts/projection_scorecard.py and src/model_registry/projection_scorecard.py (weekly pregame store); src/model_registry/game_day_calibration.py; playoff/title simulations that read generations | g3 COLLECTING_ACTIVE |
| RPA-COL-021 | Game Day pregame prediction capture | yes | 2026-10-26T12:00:03Z | both | medium | src/model_registry/game_day_calibration.py; season-end Game Day calibration; docs/game-day prediction scorecards (RPA-LGI-004) | g3 COLLECTING_ACTIVE |
| RPA-COL-022 | Playoff/title forecast archive (AL-P6) and as-known news metadata archive (G4) | yes | 2026-10-26T09:38:00Z | both | high | season-end playoff/title calibration (not yet built); model_lab capture inventory; BDVM news-to-events (separate ingestion), as-known news lookups (G4) | g3 COLLECTING_ACTIVE |
| RPA-COL-023 | Pick forecast / team strength weekly snapshot (AL-P4) | yes | 2026-10-22T12:24:11Z | content | low | Pick Forecast scoring (future); src/ros/pick_forecast_snapshot readers; ledger.keys idempotency index | g3 COLLECTING_ACTIVE |
| RPA-COL-024 | Learning receipts store | yes | 2026-10-26T09:39:07Z | both | medium | src/model_registry/model_lab.py; promotion_gates.py; reproducible_evaluation.py; Hill Autopilot evidence | g3 COLLECTING_ACTIVE |
| RPA-COL-025 | AL-P5 served trade decision receipts log | yes | 2026-10-26T04:09:00Z | fetch | medium | scripts/trade_decision_receipts.py -> learning receipts (DECISION); model_lab / decision scoring (future) | g3 COLLECTING_ACTIVE |
| RPA-COL-026 | Temporal ledger, board history and daily board snapshot (C1-U4) | yes | 2026-10-26T11:40:00Z | fetch | medium | src/history/asof.py; rankChange stamps; trade at-the-time grades and How It Aged; Consensus Edge labelling (consensus_edge.sqlite); board_history readers | g3 COLLECTING_ACTIVE |
| RPA-COL-027 | BDVM weekly projection refresh and news-to-events ingestion | yes | 2026-10-20T06:14:57Z | fetch | high | /api/bdvm/values, /roster, /trades, /trade-eval; /rankings Fund-gap column; /draft BDVM panel; dynasty-signal-alerts BDVM alert leg | g2 COLLECTING_ACTIVE |
| RPA-COL-028 | Own-league FAAB bid history | yes | 2026-10-26T07:47:00Z | content | low | src/trade/faab_engine.py market priors; /api/waiver/faab-recommend; src/api/faab_analytics.py; scripts/faab_backtest.py | g3 COLLECTING_ACTIVE |
| RPA-COL-029 | KTC crowd FAAB market accumulation | yes | 2026-10-26T09:26:20Z | both | medium | src/trade/faab_engine.py (rival engagement and clearing price only); faab_history.crowd_bid_index; /api/waiver/faab-recommend crowdMarket block; retention-health C1-RET-01 | g3 COLLECTING_ACTIVE |
| RPA-COL-030 | Player-context collectors: trending history, playerctx, reception depth, PBP weekly | yes | 2026-10-26T11:35:16Z | fetch | medium | waiver trending/adds signals and retention C1-RET-05; src/nfl_data/reception_shape_projection.py; BDVM baseline and projection inputs; player-context panels (depth/snaps/contracts) | g3 COLLECTING_ACTIVE |
| RPA-COL-031 | ROS rankings aggregate and ROS source collectors | yes | 2026-10-26T08:08:16Z | fetch | high | data/ros/aggregate/latest.json -> rosValue; playoff/title simulations and team strength (src/ros/playoff_sim, team_strength); Game Day lineup intelligence; forecast archive inputs (ROS aggregate hash) | g3 COLLECTING_ACTIVE |
| RPA-COL-032 | Retention backups, restore proofs and auction backup | yes | 2026-10-26T02:38:10Z | fetch | high | disaster recovery of all box-local evidence; retention-health / retention-backup-proof workflows; /api/health backup_health | g2 COLLECTING_ACTIVE |
| RPA-COL-033 | DFS auto-refresh tick (owner-paused area) | yes | 2026-10-26T12:00:49Z | fetch | low | DFS section of the site (paused, deployed); nightly state backup (optional dfs_workspace.sqlite) | g3 COLLECTING_ACTIVE |
| RPA-COL-034 | Production smoke and E2E monitors | yes | 2026-10-26T04:45:18Z | fetch | medium | owner and Integration merge/deploy decisions (green or red status); issue #1918; retention-health correlation | g4 COLLECTING_BROKEN |
| RPA-COL-035 | V1 failure classifier (report-only) | yes | 2026-10-24T01:31:15Z | fetch | low | operators reading V1 run summaries; future retry/alert policy (not authorized) | g3 SHADOW_RUNNING |
| RPA-COL-036 | Sharp production smoke | yes | none recorded | fetch | high | owner/ops reading data/ops/sharp-production-smoke.json; Sharp production-gate evidence for RPA-OPS-009; main history (record commits) | g4 COLLECTING_BROKEN |
| RPA-COL-037 | Weekly narratives generation (export mode) | yes | 2026-10-21T17:56:21Z | content | medium | owner weekly narrative workflow (external LLM paste/import); exports/narratives/ on main; workflow artifact data/narrative_packages | g3 COLLECTING_ACTIVE |
| RPA-COL-038 | Codex 'Brisket Orchestrator' cron automation | unknown | 2026-09-10T05:08:00Z | unknown | low | none in the repo (local memory.md only) | g5 DORMANT_IMPLEMENTED |

Reading the "Last success" column: it is the assessor's recorded timestamp of the last run that finished successfully. For RPA-COL-001 a successful run is not proof that the browser sources refreshed (finding RPA-F-001), and the green runs of RPA-COL-036 measure nothing (RPA-F-019). RPA-COL-007 shows none because every retained run was red. RPA-COL-038 has no run log.

Silent-failure risk across the 38: high 9, medium 18, low 11. The high-risk collectors are RPA-COL-001, RPA-COL-016, RPA-COL-017, RPA-COL-019, RPA-COL-022, RPA-COL-027, RPA-COL-031, RPA-COL-032, RPA-COL-036.

## 9. Cross-batch conflicts, reconciled

### 9.1 `host_native_scoring` authorization (RPA-LGI-005 against RPA-OPS-007)

- **RPA-LGI-005** found the owner authorization at "PACKET C ANSWERED by owner, 2026-08-25" in `docs/VERSION_1_COMPLETION_CONTRACT.md`.
- **RPA-OPS-007** reported that no record authorizing the live activation was found in `docs/EXECUTION_PLAN.md` or `docs/OWNER_REQUESTED_TODO.md`.
- **Check** (`git show origin/main:docs/VERSION_1_COMPLETION_CONTRACT.md | grep -n -i "packet c"`): line 1017 reads "PACKET C ANSWERED by owner, 2026-08-25 — controlled production activation AUTHORIZED", with the conditions verbatim: exact-head CI green, blast radius measured first, rollback ready, any unexpected scoring behavior triggers rollback, no scoring-methodology change. The V1-49 row (about line 715) records the controlled activation (written as 2026-08-29; workflow run 33207091827 was created 2026-08-28T20:10Z, so the dates differ by a UTC day) with no rollback trigger fired.
- **Resolution:** the authorization exists. RPA-OPS-007's "not found" came from searching only EXECUTION_PLAN and OWNER_REQUESTED_TODO, so it is a search-scope miss, not an absence. What is genuinely open is narrower and is what RPA-LGI-005 asks the owner to settle: (1) the authorization covers a controlled activation, not a standing state, and promotion to sole canonical scoring owner is **not** authorized; (2) the registry default (`feature_flags.py:734`) is still False and its comment still calls the flag a temporary OFF challenger; (3) the flag is not in `OWNER_HELD_FLAGS`; (4) neither EXECUTION_PLAN nor OWNER_REQUESTED_TODO records it, which is why the second assessor missed it.

### 9.2 IDP Show: two different feeds (RPA-SRC-005, RPA-SRC-004, RPA-COL-027, RPA-COL-012)

- **Rankings board (`idpShowCombined`).** The fetch is **healthy**: `idpShowCombined_last_status.json` is HEALTHY with 665 rows at 2026-10-26T10:32Z, and the box timer commits every 2 hours. The vote is withheld (`source_votes_withheld:idpShowCombined:655`) only because the vendor chart has not changed since 2026-08-19T17:50Z. The earlier RPA-SRC-005 next action (renew the expired #1726 fetch-outage acknowledgment, or re-mint cookies) is therefore **moot and should be retired**; RPA-SRC-004 supersedes it.
- **BDVM projection feed (`scripts/fetch_idpshow_projections.py`, weekly `dynasty-bdvm-refresh`).** RPA-COL-027 found it has **never produced a record** in any of 29 snapshots since 2026-07-30; on 2026-10-20 the report said `not_a_projection_table` with unmapped columns "Position Rank" and "Projected Total Snaps". The cookie is fresh, so this is a layout or parse change (inferred), not an outage. Draft #1959 reports failed sources honestly and parses the sheet to a shadow file; merging parsed records into BDVM snapshots is an owner decision.
- **Why they are easy to confuse:** both use the same login session file, and the unit that runs the projection stage reports success whatever that stage returns. A healthy rankings fetch says nothing about the projection parser, and a stale vendor chart says nothing about the cookie.

### 9.3 Consensus Edge (RPA-LGI-001 against RPA-VAL-018 and RPA-VAL-016)

- RPA-LGI-001 listed, as a blocker, that refreshing `config/league_intel` "changes served consensus_edge/scoring_fit behaviour". RPA-VAL-018 noted that `consensus_edge` is OFF in production.
- **Evidence:** production `/api/status` (2026-10-25 and 10-26) shows `consensus_edge` enabled false; `/api/consensus-edge/*` answers 503 feature_disabled when off (401 to anonymous callers); the only readers of `idp_scoring_fit` and `reception_scoring_fit` are the two resolvers in `src/api/gameplan.py`, which feed the login-only `/api/valuation/league-adjusted` endpoint that the shipped client never calls; `src/consensus_edge/scoring_fit.py` reads neither flag.
- **Resolution:** refreshing `config/league_intel` changes **no default-served consensus_edge behaviour**, because that feature is off. It would still change the opt-in overlay endpoint, the offline adjusted-board backtest and the shadow fair-value challenger (inferred). The audit was right not to touch the config, but for a different reason: any served-config change is owner-reserved and the same card is the exact scorer's default (finding on the stale snapshot). RPA-LGI-001's blocker sentence should read "owner-reserved", not "changes consensus_edge behaviour".

### 9.4 #804 against the capture sub-task, and the false "#921 shipped" claim (RPA-SRC-009, RPA-VAL-009)

- **#804** is the issue "Correlated-source / shared-lineage anomaly protection" (open since 2026-08-11, labels lane-4-market and post-v1, zero comments). `docs/EXECUTION_PLAN.md` section 0.4b and `docs/lane4/LANE4_804_CORRELATED_SOURCE_STATUS.md` also call the per-source **rank-digest capture** "#804", because that capture is the evidence prerequisite. The two assessors were describing one program (protection, the parent) and its capture sub-task.
- **The capture was never built on main.** PR #921 (a `source_rank` lane proven non-influencing against the golden board) was **closed unmerged** on 2026-09-09 as "DEFER / PRESERVE REFERENCE"; `VALID_LANES` in `src/history/store.py` still has three lanes; nothing has been captured. `docs/lane4/LANE4_804_CAPTURE_CADENCE_DECISION.md` therefore wrongly says "the capture unit shipped in #921 and its feature flag is OFF" (finding RPA-F-031). `refs/pull/921/head` (03ee6212) still preserves the diff.
- **State:** the capture is **authorized** (EXECUTION_PLAN 0.4b, capture only) but **not implemented**, and its cadence is an owner decision (daily recommended, about 1.2 GB a year). The protection itself has no owner, design or series, and the owner's 2026-10-19 consensus directive forbids acting on rank or value similarity alone, so any protection must be report-only or rest on data-lineage evidence. The claim that "every day without capture is lost" is overstated: raw per-source CSVs are recoverable from the git history of `CSVs/site_raw` (45 to 1,327 committed versions per source); only per-build derived metadata is not.

### 9.5 Other conflicts found while merging

| Conflict | Resolution |
|---|---|
| RPA-COL-007 (group 1, owner decision) against RPA-VAL-011 (group 2, engineering) | Same rank-form drift audit. RPA-VAL-011 verified that CQ-28 has blocker NONE and EXECUTION_PLAN line 145 authorizes it, and that nobody has claimed it. **Engineering, no owner approval**, unless a consumer is shown to feed served canonical values. RPA-COL-007's "UNVERIFIED whether it falls under the same gate" is answered. |
| RPA-VAL-014 (#1927 OPEN) against RPA-TRD-004, RPA-TRD-006 and RPA-OPS-007 (#1927 merged) | `gh` shows #1927 MERGED 2026-10-25T20:51:11Z. RPA-VAL-014 was read before the merge. The flag `replacement_level_li5_consolidation` is OFF and deploy-locked. |
| RPA-TRD-007 (#1930 open; Lane E script unpushed) | `gh` shows #1930 CLOSED unmerged at 2026-10-26T09:05:39Z; the measurement script is draft #1949. The add/add conflict with #1946 is moot. |
| RPA-VAL-013 (lanes only in local worktrees; no open PR) | Lane A is #1931 and Lane C #1936 (both open); lane drafts #1940 to #1943 and #1945 also exist. |
| RPA-TRD-001, RPA-TRD-002 and RPA-TRD-011 (ledger stalled at the 10-23 report; native-comparable 0) against RPA-COL-015 and RPA-OPS-001 | A 2026-10-26 report exists (NATIVE_COMPARABLE 1, scoring evidence fresh). The 10-24 and 10-25 reports are permanently missing. Two clean cycles are still needed. |
| RPA-OPS-007 against RPA-LGI-013 on a stale `waiver_live_opportunity` comment | Both are right about different comments. The `_DEFAULTS` comment is consistent (default ON); the `_GATE_STATUS` comment at `feature_flags.py:1144-1151` still says "defaults False rather than True". Verified on origin/main. |
| RPA-VAL-005 ("OWNER_HELD_FLAGS holds four") against RPA-OPS-007, RPA-SRC-003 and RPA-TRD-004 (six) | Six since #1927. RPA-VAL-005 was read before it merged. |
| RPA-COL-034 ("no PR repairs the failing specs") against RPA-OPS-003 | #1923 merged 2026-10-25T20:26:33Z; the scheduled-run confirmation is still pending. |
| RPA-OPS-009 against RPA-COL-036 on when the Sharp gate became unmeasured | Issue #1727 says since 2026-10-12 and "never measured"; the file's `stateSince` 2026-10-26T02:08Z resets on each record commit. They are one fact: it has never measured. Same check, two items. |
| RPA-GOV-007 (group 1) and RPA-COL-038 (group 5) | One Codex automation, one owner action (disable or repoint). Counted once as a decision, once as a retirement. |
| RPA-OPS-002 against RPA-COL-034 on smoke failure counts and cold-path time | Different windows: 19 of 42 runs (2026-10-04 to 10-26) against 13 of 28 (since 10-19); cold path 44.1 s in one probe and 7.5 s in another. Both agree the failure is intermittent and the cold path is slow. |
| RPA-SRC-006 against RPA-COL-001 on refresh cadence | 5.1 runs a day over 2.36 days against 4.6 a day over 7 days; both far below the declared 12. |

## 10. Stale records corrected by this audit

Planning, ledger or code-comment claims that the evidence contradicted. The records themselves are **not** edited here (this audit is read-only); each row names the correction a records pass should make.

| # | Record | What it claimed | What the evidence shows | Items |
|---|---|---|---|---|
| 1 | CLAUDE.md 'Pick identity' section | '/trade does not yet' read the unknown pick-ownership state. | Shipped by TC-A commit ad927d0fe on 2026-10-17 with tests; only frontend/lib/pick-stack.js:233 (display-only) still maps team.picks\|\|[]. | RPA-TRD-013 |
| 2 | OWNER_REQUESTED_TODO line 2269 and docs/DEVELOPMENT_TRACKER.md line 40 | D4 (DLF Values vote) is ON ('flag ON in PR #1817', 'D4 and D5 ON'). | dlf_values_rank_hill_vote is OFF in production (/api/status 2026-10-25); #1817 merged it dormant. | RPA-VAL-003 |
| 3 | OWNER_DECISION_REGISTER ODR-DLF-VALUES-VOTE | EVIDENCE_PENDING, 'nothing registered' (last edit 2026-10-19). | D4 is merged dormant and held for outlier-integrity V2.1 since 2026-10-20. | RPA-VAL-003 |
| 4 | OWNER_DECISION_REGISTER ODR-IDP-DEEP-TAIL; intake D6 | EVIDENCE_PENDING, ship column blank. | The preregistered replay verdict was committed 2026-10-18 (PROMOTION-ELIGIBLE, governance overlay AUTO_PROMOTION_BLOCKED). | RPA-VAL-004 |
| 5 | OWNER_DECISION_REGISTER ODR-PLAYOFF-ROS-DOUBLE | 'No challenger yet'. | The challenger exists as flag playoff_ros_counted_once (OFF) and its preregistered comparison failed gate G4 on 2026-10-18. | RPA-LGI-006, RPA-GOV-003 |
| 6 | docs/completion/families/family_C.json and the completion dashboard | AL-4a and AL-3b code does not exist; Perfect Waivers absent. | src/model_registry/game_day_calibration.py, projection_scorecard.py and their scripts are on main (#1691); Perfect Waivers is live. The family files date from 2026-10-07. | RPA-GOV-003, RPA-LGI-004, RPA-LGI-017, RPA-OPS-012 |
| 7 | docs/EXECUTION_PLAN.md, family_C.json and SCHEDULE_INTELLIGENCE_SPEC | Schedule Intelligence part E is blocked on C5-WAR-01 (absent). | C5-WAR-01 merged as #1692 on 2026-10-08 (src/public_league/player_impact.py). | RPA-LGI-009 |
| 8 | docs/EXECUTION_PLAN.md '## C1A' header | C1-U5 is DEFERRED. | PR #876 merged 2026-08-17 and line 1506 of the same file records it in production with the checklist unexecuted. | RPA-GOV-005 |
| 9 | docs/lane4/LANE4_804_CAPTURE_CADENCE_DECISION.md | The capture unit shipped in #921 and its flag is OFF. | #921 was closed unmerged on 2026-09-09; VALID_LANES has only three lanes; nothing has been captured. | RPA-SRC-009 |
| 10 | config/sources/source_lineage.json defect 'fantasypros-idp-dual-family-duplicates'; OWNER_REQUESTED_TODO lines 2250 and 2288 | Status 'open' / PARTIAL / OWNER DECISION NEEDED. | The analysis was completed 2026-10-18 (owner closeout Decision 5): no vote amplification. Only status text is stale. | RPA-SRC-002 |
| 11 | Multi-bridge PR-B doc (Lane 8) | 'FEATURE_GREEN / READY_FOR_INTEGRATION'. | Merged 2026-08-20 as #993, flag OFF, dormant for two months. | RPA-VAL-012 |
| 12 | docs/valuation/HILL_SOURCE_ALIGNMENT_AUDIT_2026-09-24.md and the D2 README | Production columns will be re-derived once #1427 lands; 'production still treats OTC as independent'. | #1601 removed the private dependence copy on 2026-10-01 (independentCriterion now null / no_independent_holdout). The promised re-derivation has no artifact. | RPA-VAL-009 |
| 13 | LI-5 design doc section 11; family_A.json; manifest; RIT-037 | Every decision PENDING; C2-REPL-01 COMPLETE_AND_PROVEN vs DUPLICATED vs PARTIAL. | The owner answered D1-D8 on 2026-10-21; family_A's 'complete' refers to the V1-29 census scope; LI-5 reuses the id for a different scope. | RPA-VAL-014 |
| 14 | docs/owner/LVA_INTEGRATION_REPORT_AND_DECISIONS_2026-10-21.md | Every decision below is PENDING. | LVA_OWNER_DECISIONS_2026-10-21.md answers all five packages. | RPA-TRD-006 |
| 15 | docs/COMPLETION_QUEUE.md CQ-23, CQ-45, CQ-59 | fairness_bands_v1 PROVISIONAL; AL-P7 perishable now; #1738 and #1728 open. | v2 is live (#1894); the first Sharp movement rows reach the 400-day prune on 2027-06-08; those two PRs no longer exist. | RPA-TRD-002, RPA-OPS-012, RPA-OPS-010 |
| 16 | docs/WORK_CLAIMS.md | #1533 BLOCKED; completion-campaign row open; Lane E 'starts once A1 lands'; D-net claimed. | #1950 supersedes #1533; the completion campaign's PR #1689 merged 2026-10-07; Lane E is in flight under different branch names; claude/advisor-loopback-bind is not on the remote. | RPA-GOV-001, RPA-TRD-007, RPA-DRF-003 |
| 17 | RIT reconciliation rows RIT-072/073/074; issue #1409 | Depth charts, ledger and game-day capture PARTIAL / BROKEN_REGRESSED / UNVERIFIABLE. | They pre-date #1926 (merged 2026-10-26T01:31Z); each unit now has one clean post-deploy run. | RPA-OPS-001 |
| 18 | Docs and hints saying the market-trade ledger is stuck at the 2026-10-23 report with 0 native-comparable trades | Ledger stalled; last report 10-23; NATIVE_COMPARABLE 0. | A 2026-10-26 report exists (09:56 CET): NATIVE_COMPARABLE 1, scoring evidence fresh. Reports for 10-24 and 10-25 are permanently missing. | RPA-TRD-001, RPA-TRD-002, RPA-TRD-011, RPA-COL-015 |
| 19 | Docs calling the live meta.packageModel.id observation 'pending' since 2026-10-18 | Not yet observed. | The 2026-10-22 box-replay provenance records geom_q078_v1 ACTIVE on code 4d5b7ed21; the served /api/data meta itself is still unobserved. | RPA-TRD-001 |
| 20 | RPA-SRC-005 next action (renew the #1726 acknowledgment or re-mint the IDP Show cookie) | The IDP Show fetch is in outage. | idpShowCombined_last_status.json is HEALTHY (665 rows, 2026-10-26T10:32Z); the vote is withheld only because the vendor chart has been unchanged since 2026-08-19. | RPA-SRC-005, RPA-SRC-004 |
| 21 | RPA-LGI-001 blocker text | Refreshing config/league_intel changes served consensus_edge / scoring_fit behaviour. | consensus_edge is OFF in production and the only scoring_fit consumer is an unused opt-in endpoint; see the Consensus Edge reconciliation. | RPA-LGI-001, RPA-VAL-018 |
| 22 | RPA-VAL-014 state | #1927 OPEN, unreviewed. | gh: #1927 MERGED 2026-10-25T20:51:11Z (flag OFF, deploy-locked). | RPA-VAL-014 |
| 23 | RPA-VAL-013 state | Lanes A and C exist only as uncommitted files; Lanes B and D not started; no open PR for any lane. | gh: Lane A #1931 and Lane C #1936 are open PRs; Lane B #1940, Lane D #1941, Lane E #1943, Lane G/F #1942 and Lane H #1945 exist as PRs. | RPA-VAL-013 |
| 24 | RPA-TRD-007 state | #1930 open and ready; the Lane E measurement script exists only as an unpushed local commit. | gh: #1930 CLOSED (unmerged) 2026-10-26T09:05:39Z; the measurement script is draft PR #1949. | RPA-TRD-007 |
| 25 | RPA-COL-034 'no PR repairs the failing specs' | No fix exists. | #1923 merged 2026-10-25T20:26:33Z (scheduled-run verification pending). | RPA-COL-034, RPA-OPS-003 |
| 26 | RPA-VAL-005 'OWNER_HELD_FLAGS holds four flags' | Four flags. | Six since #1927 (merged 2026-10-25T20:51Z). | RPA-VAL-005, RPA-OPS-007 |
| 27 | Input hint: 'promotion criteria NONE_DEFINED' for the live waiver opportunity layer | No criteria. | docs/faab-live-opportunity-model.md section 5a carries Stage 2 numbers. | RPA-LGI-013 |
| 28 | Input hint: Power Rankings '60-65% results share demonstrated' | A recorded figure. | Appears nowhere in the repo; the recorded owner target is forward/results 0.30/0.70 and the live results share is 68.9%. | RPA-LGI-010 |
| 29 | Input hint: the DEVELOPMENT_TRACKER 'Rule E' conflicts with the Agent OS | Nothing merges without owner approval. | The tracker (main and branch) already says the 2026-10-19 standing merge authorization supersedes Rule E. | RPA-GOV-002 |
| 30 | Reported ~979-row IDPTC partial scrape of 2026-10-23/24 | A partial scrape of about 979 rows. | The journal shows IDPTC identity counts of 898 then 900; the figure is unverifiable. | RPA-OPS-006, RPA-SRC-004 |
| 31 | Side finding 'nflverse schedules sched_2026.csv url_stale' | A failed schedule URL. | Documented, handled log noise: the fallback to games.csv works and the schedule source is healthy. | RPA-LGI-015, RPA-COL-020 |

## 11. Status updates since the batches ran (2026-10-26)

| PR | State at 2026-10-26 (gh) | What it does |
|---|---|---|
| #1939 | MERGED 2026-10-26T11:32:46Z | Pins `scheduled-refresh.yml` to ubuntu-24.04. **Post-merge verification partial**: no scheduled post-pin run had happened at 13:13Z (latest scheduled run 2026-10-26T08:07:07Z), but manual run 40325142841 (12:46:40Z, ubuntu-24.04) succeeded and advanced the ktc, ktcSfTep, idpTradeCalc, draftSharks and draftSharksIdp stamps to 12:50-12:53Z (origin/main e8b8788f3). |
| #1950 | draft | Auction Phase 2 security and money fixes plus review follow-ups; supersedes #1533. |
| #1951 | draft | LI1842 config-propagation defects 01/03/04/06/09/10/11 (stacked on #1948). |
| #1952 | draft | Injury feed parses 274 of 800 ESPN rows (was 0); derived events are shadow-only. |
| #1953 | draft | Refresh silent-failure signals plus the `draftsharks-diagnostic` pin. |
| #1954 | draft | Settings value-basis copy, and the waiver-compare charset. |
| #1955 | draft | Python security bumps (aiohttp, certifi, pillow) with lock refresh; supersedes #1855, #1895, #1896; covers 100 of 111 alerts. |
| #1956 | draft | `/api/health` reads the DLF session the timer actually uses. |
| #1957 | draft | Sharp transaction crawl: 404 leagues no longer trip the `sleeper_api` breaker; gone leagues skipped for 168 h; explicit `stoppedReason`. |
| #1958 | draft | ROS collector: explicit `kept_previous` status and a content clock (reporting only); confirms the orphan `footballGuysRosIdp.csv` and that `ffc2qbAdp` has been unchanged for 14 days while status reads "ok". |
| #1959 | draft | BDVM projection refresh reports failed sources honestly and writes `refresh_status.json`; the IDP Show parser (position now arrives only as a `Position Rank` code, inferred) writes to a shadow file only; merging into BDVM snapshots is an owner decision behind a default-off switch. |
| #1927 | MERGED 2026-10-25T20:51:11Z | LI-5 P3 wiring, flag OFF and deploy-locked (RPA-VAL-014 predates it). |
| #1930 | CLOSED unmerged 2026-10-26T09:05:39Z | Lane E surface-parity tests; #1946 and #1949 remain as drafts. |
| #1923 | MERGED 2026-10-25T20:26:33Z | E2E journeys independent of live-board drift; scheduled-run confirmation pending (no scheduled run since 2026-10-25 11:44Z failure). |
| #1926 / #1925 | MERGED 2026-10-26T01:31Z / 01:32Z | Box unit repairs; deploy paths-ignore. |

## Appendix A. Dropped and merged items

Eleven candidates were merged away or excluded during de-duplication. None was assessed as its own item; where the open residue lives in an assessed item, it is named.

| # | Dropped or merged candidate | Reason recorded | Merged into |
|---|---|---|---|
| 1 | EXCLUDED: Chase Upside private ChatGPT/plugin MCP integration (PR #1921, branch codex/chase-upside-private-mcp) | Excluded from this audit by instruction. It appeared in four sweeps and was not assessed. The main checkout is on this branch, with an untracked .codex/ folder. | Excluded by instruction; not merged into any item and not assessed. Appeared in four sweeps. |
| 2 | Value replay (board vs KTC Market gap) | A completed read-only diagnostic (docs/valuation/evidence/value-replay-2026-09-30/, scripts/value_replay.py, src/api/value_replay.py, research_pinned_board.py, research_readonly_guard.py). It is now a shared research harness with no pending decision. | No item: a completed read-only diagnostic, now a shared research harness with no pending decision. |
| 3 | Early backtest/measurement corpus (Jul-Aug 2026) | Historical and closed (docs/measurements/, scripts/backtest_*.py, adjusted-board-backtest, LEAGUE_AWARE_METHODOLOGY_REJECTION). The adjusted board was withdrawn, and the scripts are unscheduled. | No item: historical and closed; the scripts are unscheduled. |
| 4 | Value-moving production flags already ON (board methodology in force) | This is the incumbent champion, not a candidate. The one open residual, idp/reception scoring fit feeding the withdrawn lens, is carried as RPA-VAL-018. | RPA-VAL-018 (the one open residual: idp/reception scoring-fit flags feeding the withdrawn lens). |
| 5 | Other ON product-surface flags (bdvm_engine, perfect_draft, rookie_auction, monte_carlo_trade, trade_screenshot_import, manager_intelligence, nfl_data_ingest, realized_points_api) | Shipped features with no pending research. Their collectors are listed separately, and the open items are carried in RPA-TRD-012 and RPA-DRF-004. | RPA-TRD-012 and RPA-DRF-004 (the open items); their collectors are listed in section 8. |
| 6 | Manager Intelligence batches A-F | Shipped and ON in production; RIT marks it VERIFIED_IN_CODE_AND_TESTS. Only an authenticated production proof is outstanding, which is an evidence item rather than research. The data/intel ledger is noted on COL-016. | No item (shipped and ON). The data/intel ledger is noted on RPA-COL-016. Only an authenticated production proof is outstanding. |
| 7 | Player archetype model | A shipped threshold labelling model (last changed 08-04) with no pending experiment or decision. UNVERIFIED whether it changes any value, and the threshold basis is NONE_DEFINED. | No item: shipped threshold labelling model, no pending experiment. |
| 8 | Lineup optimizer (canonical) | Shipped single owner, 10/10 against Sleeper. The residuals C2-DROP-01 and #899 are carried in RPA-LGI-017. | RPA-LGI-017 (residuals C2-DROP-01 and #899). |
| 9 | Trade screenshot import / KTC URL import | A shipped feature (RIT-028 MERGED_PROD_UNVERIFIED, RIT-029 verified). Only the production tesseract availability check is outstanding. | No item: shipped; only the production tesseract availability check is outstanding. |
| 10 | Frontend/backend parity tests | INFERRED healthy and running in L2. The one known non-parity gap is carried as RPA-TRD-013. | RPA-TRD-013 (the one known non-parity gap). |
| 11 | In-flight PRs touching collectors/initiatives; Session in-flight PRs #1923-#1927 | Meta lists. Each PR (#1922-#1929) is folded into its owning initiative: RPA-TRD-004, RPA-OPS-003, RPA-GOV-001, RPA-OPS-004, RPA-OPS-001, RPA-VAL-014, RPA-VAL-013. | RPA-TRD-004, RPA-OPS-003, RPA-GOV-001, RPA-OPS-004, RPA-OPS-001, RPA-VAL-014, RPA-VAL-013 (PRs #1922 to #1929, each folded into its owning initiative). |

## Appendix B. Method

**Read-only.** No code, configuration, feature flag, value or setting was changed, and no credential or .env file was read. Production and the box were touched only by read-only means. The only new files are this report and its JSON inventory.

**Evidence channels.** `git` (origin/main and branches), `gh` (pull requests, issues, workflow runs, Dependabot alerts, rulesets, secret names only), public `curl` of chaseupside.com, and read-only `ssh` to the production box (service state, journals, files, SQLite in read-only mode). Authenticated endpoints were not read, so per-source weights and served confidence labels are unmeasured. Each assessor marked every claim in its `verification` list with a prefix: VERIFIED, INFERRED, UNVERIFIED, CORRECTED or CONTRADICTED. In writing this report the author re-checked the conflicts in section 9 and the PR states in section 11 with `git` and `gh` only.

**Assembly and count check.** Seven category catalogs, four category assessment files (68 items), two collector files (38 items) and the 19 earlier assessments held in the catalogs were merged. 87 initiatives plus 38 collectors is 125 distinct ids: none missing, none duplicated. `items[]` in the JSON is the assessments exactly as written, sorted by id; `findings[]` is sorted by id.

**Enums.**

| operationalStatus | Meaning |
|---|---|
| LIVE | Running in production; nothing pending beyond observation. |
| COLLECTING_ACTIVE | A collector or monitor is running and producing output. |
| COLLECTING_STALE | Running, but its inputs or output are older than their budget. |
| COLLECTING_BROKEN | Running or scheduled, but not producing usable output. |
| SHADOW_RUNNING | A shadow challenger is running and recording. |
| SHADOW_NOT_RUNNING | Shadow code is merged or authorized but nothing is producing shadow evidence. |
| DORMANT_IMPLEMENTED | Merged and tested but switched off, unwired or held. |
| IMPLEMENTATION_ACTIVE | Engineering is in progress now. |
| NOT_STARTED | Authorized or wanted, but nobody has started. |
| WAITING_ON_OWNER | Needs an owner decision or owner-only action. |
| WAITING_ON_DEPENDENCY | Needs another item, vendor or date first. |
| SUPERSEDED | Replaced by other work. |
| RETIRED | Closed; remaining work is cleanup. |

| evidenceStatus | Meaning |
|---|---|
| NEEDS_MORE_DATA | A sample size or date must pass before a decision. |
| NEEDS_PREREGISTRATION | No frozen evaluation criteria exist yet. |
| NEEDS_METHODOLOGY_REVISION | The current design cannot yield a valid answer. |
| OWNER_APPROVAL_REQUIRED | Evidence is not the blocker; an owner decision is. |
| NOT_A_PROMOTION_CANDIDATE | Infrastructure, collector or record with nothing to promote. |
| ENGINEERING_NOT_READY | A defect or missing build blocks any evaluation. |
| BLOCKED | Cannot proceed on a named external or governance block. |
| INSUFFICIENT_EVIDENCE | Too little evidence either way. |
| READY_FOR_DECISION | Enough evidence exists for the decision that is on the table. |
| EVIDENCE_SUPPORTS_REJECTION | The evidence favours rejecting or retiring. |
| EVIDENCE_SUPPORTS_ADVANCEMENT | The evidence favours advancing the work. |

| Verification prefix | Meaning |
|---|---|
| VERIFIED | Read or measured directly in git, gh, a public endpoint, or a read-only box session. |
| INFERRED | Concluded from verified facts but not observed directly. |
| UNVERIFIED | Could not be checked with the allowed access. |
| CORRECTED | An input claim was wrong and the item states the corrected fact. |
| CONTRADICTED | The evidence contradicts an input claim or a record. |

Priority labels (P0 to P3) are the assessors' own; P0 is a single item.

**Stage scale, 0 to 6** (`highestVerifiedAuthorizedStage` is the highest stage that is both verified and authorized; the scale is reconstructed from the assessors' stage notes):

| Stage | Meaning |
|---|---|
| 0 | Idea or request only; no evidence work. |
| 1 | Research or evidence gathered (verified and authorized). |
| 2 | A candidate implementation is justified and authorized. |
| 3 | Shadow evaluation is ready or running. |
| 4 | Merged dormant: tested, disabled or held, with locks. |
| 5 | Activated (live) under authorization, with validation as far as it exists. |
| 6 | Verified in production: observed on the deployed surface. |

**Group meanings.**

| Group | Meaning |
|---|---|
| 1 | Owner decisions possible now: the evidence is enough for a specific decision the owner can make today. |
| 2 | Active engineering: authorized, dependency-ready work that needs engineers, not an owner decision. |
| 3 | Collecting: running and waiting on a sample size or a date. |
| 4 | Blocked: waiting on a dependency, a vendor, an owner-held credential or a defect fix; includes broken collectors whose fix is in an unmerged PR. |
| 5 | Retire or superseded: the remaining work is closing, deleting or correcting records. |

**Finding status.** CONFIRMED: a VERIFIED line reproduces the defect. SUSPECTED: it rests on INFERRED lines. UNRESOLVED: the headline claim is UNVERIFIED. **Severity:** critical (a confirmed wrong served value or exposure with no compensating control; none), high (silently corrupts, hides or loses evidence, exposes a security or money path, or leaves a monitor green over a failure, with a compensating control limiting the blast radius), medium (degraded evidence, misleading status, or a gate or monitor gap without a current wrong served value), low (record, copy or housekeeping drift).

**Limits.** The assessors' box and production reads date from 2026-10-25 and 2026-10-26 and were not repeated. Test suites, replays and draft-PR evidence were not re-run; where a figure comes from a draft PR the finding says so. Groups, priorities and stages are the assessors' judgments and are not re-graded. Some item text pre-dates the changes in section 11 and section 9.5; the items are left as assessed and the corrections are listed rather than applied.

