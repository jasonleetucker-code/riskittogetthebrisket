# Chase Upside Completion Queue

**As of:** 2026-10-19 07:23Z
**State checked against:** `origin/main` b08f7230d1 (release train 10, #1825). Production `/api/status` reports build.commit **eb10d3e12d** (contains trains 7, 8 and 9, not train 10). Deploy Production run 39211570693 for b08f7230d1 is in progress.
**Authority:** Master Directive "Finish Chase Upside" (2026-10-19) §12. Also binding: the Owner Decision Closeout (2026-10-18), the Trade Calculator clarity/dual VA/speed directive (2026-10-19) the Source Voting Consensus directive (2026-10-19, which supersedes the conflicting parts of D2 and D3), and the Universal Source Voting and Freshness Policy (2026-10-19, which supersedes conflicting D1/D2/D3 decisions and the old cadence-relative freshness method).
**Scope:** the authorized non-DFS scope only. DFS and League Tycoon are SHELVED and not counted.

This is the one authoritative completion queue. It replaces nothing in `docs/EXECUTION_PLAN.md` (implementation authority) or the completion ledger (requirement rows). It groups those rows into a finite list of finishable items, and it must get shorter as work ships.

## How to use

1. **One row per remaining item.** An item leaves the queue only when its production evidence is recorded. Then move it to "Shipped and verified" as a single line with the PR, deploy run and probe.
2. **Do not add rows for technical subtasks.** Put a newly found subtask inside the item that owns it. Add a new row only for a user-visible defect or an owner-authorized requirement that no row covers.
3. **Blocker vocabulary:**
   - `NONE`: engineering can finish it.
   - `OWNER-ONLY:<why>`: it needs an action listed under "Owner-only actions".
   - `EXTERNAL:<why>`: it depends on time or on a provider.

   A row with `NONE` must never wait on the owner.
4. **Batches respect file ownership.** Two concurrent batches never edit the same shared source files. `docs/WORK_CLAIMS.md` is the one shared multi-writer file: claim rows are append-only, and the coordinator resolves conflicts in it.
5. **Status words:**
   - `merged` is not `deployed`.
   - `deployed` is not `verified`.
   - Production evidence means a probe of the served build, with the commit confirmed.
6. **Priorities set the order, not what may be dropped.** Every row stays until it is shipped, explicitly deferred, or genuinely blocked.

## Read first: findings that change the plan

1. **#1817 is being verified against a superseded design.**
   - Its head 8dc29e3ea9 (06:54Z) still turns on `idp_shared_correlation_cap` (D2) and `idptc_offense_vote_excluded` (D3) from b9801b5836. It also preregisters a D2 gate as "approved in principle".
   - The Source Voting Consensus directive (06:55Z) reverses both.
   - The head also conflicts with train 10 in `src/api/feature_flags.py`, `README.md` and `docs/ARCHITECTURE.md`, and has 0 check runs. The last green CI is on eb44b5421f (Validate PR 39204279085).
   - Redirect the verification to the reworked design (CQ-01).
2. **The public playoff and title odds are broken in production (P0).**
   - dynasty_main `playoffOdds` reports numSims 0.
   - `rosPlayoffOdds` and `rosChampionship` report `unsimulable: median_game_week_unsimulable` for weeks 6-14 (forecast 05:27Z).
   - The fix is #1822, carried by train 11 #1829 (CQ-02).
3. **Power Rankings mis-ranks roster 11 after the manager replacement.**
   - John has gamesUsed 0, with null all-play, recent and PPG components, and is ranked 11. With full weights he would be about rank 10.
   - #1822 leaves Power out of scope (CQ-09).
4. **Authenticated production verification is switched off.**
   - Workflows 342419392 (`v1-authenticated-verification.yml`) and 262433998 (`prod-e2e-smoke.yml`) have been `disabled_manually` since 2026-10-08.
   - This one owner action gates production proof for the Trade Calculator, Manager Intelligence, Trade Finder and about 78 deployed ledger rows (OWNER-01).
5. **None of the four 2026-10-19 directives is recorded on `main` yet** (CQ-17). The Universal Source Voting and Freshness Policy (latest) adds CQ-64, CQ-65 and CQ-66 and expands CQ-01.

## In-flight release pipeline (coordinator-managed; reported, not duplicated)

| PR | Head | CI on head | State | Next |
|---|---|---|---|---|
| #1825 train 10 (TC-E #1824, playoff D11/D12 #1821) | b08f7230d1 (merged 06:43Z) | RC 39204421033 green | Deploy 39211570693 in progress | Confirm served commit (CQ-04) |
| #1829 train 11 (#1822 + #1823) | 23fed8b8cc | Validate PR in progress | unstable (checks pending) | RC, E2E, merge, deploy (CQ-02, CQ-08) |
| #1826 dual VA comparison | c3eaa29a02 | Validate 39198638208 and E2E 39198638132 green | clean; verified ready | Train with #1827 (CQ-06) |
| #1827 War Room plain English | 11906c7dc4 (round 6) | L0 and E2E journeys green; Validate PR in progress | unstable | Finish fix round, then train with #1826 (CQ-05) |
| #1828 analyze speed | c712781629 | L0 and Validate PR green | clean | Independent re-verification, then train (CQ-03) |
| #1817 source independence | 8dc29e3ea9 | 0 check runs | dirty (conflicts with train 10) | Rework per directive (CQ-01) |

## Counts

**66 remaining items:**

| Priority | Items |
|---|---|
| P0 | 6 |
| P1 | 14 |
| P2 | 16 |
| P3 | 25 |
| P4 | 5 |

Gated by the owner:
- **Fully owner-gated: 3 items** (CQ-12, CQ-13, CQ-16).
- **Owner-gated for production evidence only: 8 items** (CQ-03, CQ-04, CQ-05, CQ-07, CQ-08, CQ-19, CQ-42, CQ-63). All of them need OWNER-01.
- Every other item can be finished by engineering.

## Queue

### P0: production correctness

| ID | Feature / defect | Canonical owner | Current code / PR status | Remaining implementation | Required tests + production evidence | Depends on | Blocker |
|---|---|---|---|---|---|---|---|
| CQ-01 | Source voting correction (#1817 rework) per the 2026-10-19 Source Voting Consensus + Universal Source Voting directives | `src/api/data_contract.py` (voting, family caps, holds, two-way boost), `src/api/feature_flags.py`, `config/sources/source_lineage.json` | **#1817** (claude/idp-source-independence) being reworked by its lane. Head 8dc29e3ea9 still ships the old D2/D3 and conflicts with train 10. | (1) Merge main. (2) D2 cross-provider IDPTC/IDP Show cap NOT enabled (similarity is not lineage); similarity kept as diagnostics only. (3) D3 reverted: IDPTC offense vote restored. (4) DLF IDP + DLF Rookie IDP hold RESCINDED (flag), under the DLF provider-family cap; final default decided with CQ-65. (5) Cross-provider families resting on similarity only get separate families (flag); documented lineage and same-provider boards (DLF, IDP Show, KTC Crowd/Trades) stay grouped. (6) Two-way eligibility fix as its own flag (one vote-gate owner, no double haircut). (7) D4 gated on the closeout conditions; D5 as its own flag. (8) Single-source haircut: existing rule kept; any change runs as a challenger only. | Reproducible scenario comparison on the real board (directive §9 metrics), all-flags-off parity (`board_diff --expect-no-value-change`), exact-head CI, independent verification, RC. Production: served source votes and effective weights per source. | Train 10 deploy (new base) | NONE |
| CQ-02 | Playoff and title odds refused after the roster-11 manager hand-off | `src/public_league/luck.py` + `playoff_odds.py` (consumer of `src/ros/playoff_sim.py`) | **#1822** at 4217b55d1e (Validate 39172504425 green), carried by **train 11 #1829** at 23fed8b8cc (Validate PR in progress). Production `playoffOdds` numSims 0; ROS odds unsimulable for weeks 6-14. | RC + E2E on #1829, merge, deploy. Then wait one ROS refresh, because `latest_playoff.json` is cached. | Public probes of `/api/public/league/playoffOdds`, `rosPlayoffOdds` and `rosChampionship` (dynasty_main): all 12 teams have probabilities and n_simulations > 0. | Train 10 deploy finishing (shared deploy concurrency group) | NONE |
| CQ-03 | Trade War Room analysis takes about 1 minute (`/api/trade/analyze`) | `src/trade/analyze_trade.py` + `server.py` analyze route | **#1828** at c712781629: L0 + Validate PR green, mergeable clean. Local warm p50 went from 2.2s to 0.46-0.61s; cold from 10s to 5-6s. | Independent re-verification of the current head, then train, RC, merge, deploy. Keep the named not-fixed items visible and fix any that are measured as material: `load_league_inputs` runs twice; aborted requests keep running; shared GIL; slow first analyze after a restart. | CI + local benchmark. Production: warm/cold p50/p95 on a real trade via Server-Timing / `analysisTiming`. | none | NONE (production latency check needs OWNER-01) |
| CQ-64 | Universal freshness schedule: 0–7 days 100%, 8–14 75%, 15–21 50%, 22–30 25%, more than 30 days 0%, measured from the publisher's genuine update (not the download); applies to offense, IDP and rookie sources; rookie seasonal inactivity kept | `src/sources/freshness.py`, `config/sources/freshness*.json`, `src/sources/dataset_state.py` | New lane (freshness), own branch/PR. Replaces the cadence-relative curve. | Step-schedule freshness factor; genuine-update clock (publisher timestamp, else recorded content-change observation; an unchanged re-download never resets it); per-source voting-status summary (status codes active_100/75/50/25, stale, data_issue, seasonal, testing) and the 26-source audit generator. | Unit and property tests on the schedule boundaries and the clock; whole-board comparison (directive §9); verify no source older than 30 days contributes; RC; production per-source status probe. | Coordinates with CQ-01 (D5 clock) | NONE |
| CQ-65 | IDP outlier filter discards valid disagreement when a 4th IDP voter appears (blocks a clean DLF IDP return) | Hampel step in `src/api/data_contract.py` (new policy module + minimal hook) | New lane (outlier), own branch/PR. Preregistered `idp-hampel-n3-v1` exists (docs/valuation/evidence/idp-outlier-n3-2026-10-18/); not yet run. | Diagnose which removals are data errors (identity, normalization, corruption) versus legitimate disagreement; evaluate the preregistered challenger and a disagreement-preserving alternative; implement the winner behind a flag. | Reproducible comparison on frozen archives, adversarial tests (corrupted, misidentified and mis-normalized observations must still be caught), independent validation before activation; explain every 40–50% move in the DLF-restored scenario. | CQ-01 (DLF restore) | NONE |
| CQ-66 | Source voting transparency: Settings and Source Health pages show Source / Last Updated / Freshness / Voting Weight / Status with the owner's plain status labels, reasons and expandable detail | `frontend/app/settings`, source-health page, over the CQ-64 per-source status payload | Not started; starts once CQ-64 defines the payload and the War Room lane frees frontend capacity | Render the per-source table and plain reasons; stale shown as stale even when collection succeeds | Component tests, Playwright desktop + mobile, axe; production probe | CQ-64 | NONE |

### P1: finish core functionality

| ID | Feature / defect | Canonical owner | Current code / PR status | Remaining implementation | Required tests + production evidence | Depends on | Blocker |
|---|---|---|---|---|---|---|---|
| CQ-04 | Train 10 deploy confirmation (TC-E #1824, playoff D11/D12 #1821) | `deploy.yml` / coordinator | Merged b08f7230d1 at 06:43Z; Deploy 39211570693 in progress; production still on eb10d3e12d | Finish the deploy; confirm the served commit | `/api/status` build.commit is b08f7230d1 or a descendant. Signed-in smoke of TC-E keyboard, balancer and retry states. `playoff_ros_counted_once` observed OFF. | none | NONE (signed-in smoke needs OWNER-01) |
| CQ-05 | War Room plain English: one recommendation first, honest loading/retry/failure, details expandable | `/trade` War Room components over `src/trade/trade_decision.py` | **#1827** at 11906c7dc4 (round 6): L0 + E2E journeys green, Validate PR in progress | Finish the fix round and get CI green. At train time, apply the vaSlot integration so #1826's comparison sits in the at-a-glance slot. Merge, deploy. | Vitest, Playwright desktop/phone and axe in CI. Production: screenshots at 1366/390/375 and live axe (signed in). | CQ-06 (same train) | NONE (production check needs OWNER-01) |
| CQ-06 | Value Adjustment comparison (geom q=0.78 vs the KTC method), including Second Opinions | `frontend/lib/va-comparison.js` over the `trade-logic.js` dispatch; Second Opinions owners | **#1826** at c3eaa29a02: clean; Validate + E2E green; verified ready | Train with #1827, RC, merge, deploy. The 3+-team comparison is deliberately not computed (documented). | Tally-invariance tests (present). Production: toggling the comparison never changes the verdict or the tally. | CQ-05 | NONE |
| CQ-07 | Trade directive 2026-10-19 §5 release acceptance | Trade verification (TC workstream) | Not started. All three PRs list production verification as UNRESOLVED. The A.J. Brown / Herbert case exists only as a route-mock fixture. | After CQ-03/05/06 deploy: reproduce A.J. Brown / Herbert on the live board; desktop/phone visual + axe; latency numbers; toggle invariance. Record everything in the TC workstream. | Production run ids and screenshots | CQ-03, CQ-05, CQ-06 | NONE (production run needs OWNER-01) |
| CQ-08 | Trade Tendencies: top trading partner missing on mobile | `frontend/app/trades/page.jsx` (consumer of the Manager Scout materializer) | **#1823** at 6e18b833e2 (Validate 39174119082 green; docs-only conflicts), carried by train 11 #1829 | RC, merge, deploy. Close #1823 as delivered via the train. | Vitest manager-scout (in #1829). Production: 390px `/trades` check (signed in). | CQ-02 train | NONE (production check needs OWNER-01) |
| CQ-09 | Power Rankings: roster 11 (John) has gamesUsed 0 and ranks 11 instead of about 10 after the manager replacement | `src/ros/power_v2.py` | No PR. Production `rosPower`: John powerScore 11.67, all-play/recent/PPG null. Luck credits the same roster with 5 games. A full-weight recompute gives about 19.5 (rank 10, above Blaine at 14.34). Cause: `power_v2.py:1077` calls `luck._season_weekly_scores` with a per-week `resolve_owner`. | Key current-season Power weekly scores to the roster's current franchise (`by_franchise=True` from #1822), keeping the manager-history split. Fix the previousOfficialRank / movement baseline: the week-5 snapshot is keyed to Joel. | Regression test on the hand-off fixture. Public `/api/public/league/rosPower`: John has gamesUsed 5 and is about rank 10. | CQ-02 (#1822 luck.py API) | NONE (an attribution fix, not a formula change; master §7/§10) |
| CQ-10 | Single-source haircut collapses and two-way boost gap (Sneed 1,133 to 339; Travis Hunter 4,692 to 2,224) | `data_contract` single-source haircut + `_apply_two_way_player_boost` | Partial analysis in #1817: e7f8286e10 (54 defensive rows haircut); eb44b5421f (Hunter; flag-off gap 3,738 to 3,599) | Attribute each collapse to source grouping (fixed by CQ-01) or to a genuine haircut flaw. Keep the current rule. Any revised haircut runs only as a preregistered challenger. Close the two-way evidence gaps. | Scenario table from the CQ-01 evidence; challenger preregistration and results | CQ-01 | NONE (rule changes only through challenger gates) |
| CQ-11 | Screenshot import: multi-screenshot side alignment, real mobile/dark fixtures, production status spec | `src/trade/screenshot_import/` + `frontend/lib/screenshot-import.js` | Full-page fix #1816 is deployed. Fixture `ktc_fullpage_browser`: Dart to Team 1, Achane to Team 2, Young and Hampton ignored. Real-tesseract tests 14/14; screenshot tests 220/220. Gaps: (1) both mobile fixtures are synthetic; (2) `mergeImages` aligns sides by position, so a follow-up shot showing only "Team 2 gets" lands on Side A (plausible, not reproduced); (3) no prod-auth screenshot spec. | (1) Label-aware per-image side alignment, with positional fallback and a conflict flag. (2) Capture real public KTC renderings at 390px, light and dark, with picks and IDP, as fixtures. (3) Add a prod-auth spec for `GET /api/trade/import-screenshot/status`. Never auto-import a guessed identity. | Vitest single-side follow-up cases; eval on the new fixtures; spec runs once OWNER-01 is done | none | NONE |
| CQ-12 | Screenshot import production proof with real screenshots | `src/trade/screenshot_import` | Upload returns 403 `guest_read_only` to guest passes (`server.py:10600`), so no production workflow can exercise it. Public metrics show 0 imports since the 06:46Z restart. | A member session uploads the Dart/Achane KTC page, a phone screenshot, a multi-shot pair and a dark-mode shot. Engineering records the results and fixes any failures. Screenshot privacy is preserved. | Recorded production results per case | CQ-11 | OWNER-ONLY: needs a signed-in member session (OWNER-02) |
| CQ-13 | TC-F: Trade Calculator final acceptance and release | `docs/trade` workstream + `/trade` | TC-F is QUEUED. Feature matrix (178 rows): 9 VERIFIED, 110 implemented but unverified, 33 partial, 17 not implemented, 3 disconnected, 6 superseded or deferred. | Run the directive §19 matrix (real stack + read-only production), the TC-29/R05 KTC parity audit and the R06 end-state gate. Write the readiness memo. Promote each IBU row to VERIFIED with run ids. | Authenticated desktop + mobile production runs per matrix section A-R | CQ-03, CQ-05, CQ-06, CQ-07, CQ-14, CQ-15, CQ-21 | OWNER-ONLY: authenticated production runs need OWNER-01 |
| CQ-14 | One verdict: decision-engine evidence and competing verdicts | `src/trade/trade_decision.py` + Second Opinions + TradeFairnessExplanation | Open matrix rows: G14/K14 partial (the BDVM per-currency check still names its own leader; the fairness explanation is not rebased). G06: signal classification unpublished. K09: no market-corroboration dimension. Agreement axis ignores Second Opinions dispersion. G12: no holdout/replay/parity journey. G03: no calibration target. The orphan branch `claude/analyze-trade-v3` (12340208f6, no PR) holds `_market_corroboration`, `_value_uncertainty`, `_strategic_fit` and `_age_window`. | (1) Demote the BDVM leader wording to explanation. (2) Rebase or demote the fairness explanation onto the decision packet. (3) Publish the signal classification. (4) Add non-double-counting market corroboration: harvest it from analyze-trade-v3, or close that branch with a disposition. (5) Wire the agreement axis. (6) Label G03 confidence as uncalibrated. | Unit and cross-surface tests (one verdict on every surface); holdout/replay harness; desktop/mobile parity journey | CQ-03, CQ-05 merged (same files) | NONE |
| CQ-15 | Team-context dimensions and roster consequences | `src/trade/analyze_trade.py` + `best_ball_utility.py` (consumer of `src/ros/lineup.py`) | Open rows: H07 currentSeasonEquity named UNAVAILABLE (`analyze_trade.py:36,102`). H09 and H10 not implemented. I02/I05 partial. H12 `shadowValuePpg` is None (`best_ball_utility.py:589`). G10: the backend still requires a team. P07 partial. Custom-flex slot mislabel in `best_ball_utility._run` (named in #1828). | (1) Roster-level playoff counterfactual (Team Context ON). (2) Weakness / young-core / meaningful-core deltas. (3) Pick-capital delta with a guarded own-pick counterfactual. (4) Waiver-pool replacement join. (5) Asset-Only analysis with no team. (6) Merge the "Your team" control into the side selector. (7) Pass the flex rule into the solve. | Unit tests per dimension; lineup tests on the exact solver; production journey | CQ-03 merged; CQ-02 (playoff sim) | NONE |
| CQ-16 | Authenticated production verification backlog | `tests/e2e/specs/prod-auth` + completion families | Last authenticated run: 37732356062 (2026-10-08). Waiting on it: about 78 dashboard rows marked DEPLOYED_NOT_PRODUCTION_VERIFIED; Manager Intelligence A-F (#1762 #1779 #1781 #1783 #1797 #1796 #1801) including saved-manager alerts; Trade Finder discovery (#1788 #1789); Perfect Waivers (#1717); Model Lab (#1723); TC-A to TC-E. | Run the prod-auth suites per family on desktop and mobile. File each defect into its owning item. Reclassify the rows. | Run ids per family | OWNER-01 | OWNER-ONLY: both workflows are `disabled_manually` |
| CQ-17 | Record the 2026-10-19 owner directives and this queue on `main` | `docs/OWNER_REQUESTED_TODO.md`, `docs/EXECUTION_PLAN.md` §0, `docs/owner/OWNER_DECISION_REGISTER.md` | `git grep 2026-10-19 docs` on main finds only ADMIN_ONLY_ACTIONS_RUNBOOK.md | (1) Capture the master directive, the TC clarity/dual VA/speed directive and the source-voting directive (verbatim or by pointer). (2) Add the EXECUTION_PLAN §0 authorization. (3) Mark the D2/D3 register rows superseded. (4) Commit this file as `docs/COMPLETION_QUEUE.md`. | Governance/docs gates in PR Validation | none | NONE |

### P2: performance, reliability and required evidence

| ID | Feature / defect | Canonical owner | Current code / PR status | Remaining implementation | Required tests + production evidence | Depends on | Blocker |
|---|---|---|---|---|---|---|---|
| CQ-18 | D4 (DLF Values rank-to-Hill, offense-only, under the DLF family cap) and D5 (FantasyPros upstream clock), controlled independently of D2/D3 | `_RANKING_SOURCES` / DLF family cap; `config/sources/freshness_v1.json` + `src/sources/dataset_state.py` | Implemented inside #1817: flag `dlf_values_rank_hill_vote` ON; FantasyPros style switch in b9801b5836. Register: ODR-DLF-VALUES-VOTE is EVIDENCE_PENDING, ODR-FP-UPSTREAM-CLOCK is DECIDED. | Decouple from the D2/D3 flags, splitting the PR if CQ-01 holds. Pass the D4 gates: timestamps, completeness, stability, top movers, offense/picks/IDP non-interference, geom regression. D5 must report stale honestly, never 0. | Board diff per flag; flag-off parity. Production: `dlfValuesSfTep` votes and the FantasyPros freshness state. | CQ-01 conflict resolution | NONE (FantasyPros vendor data stale since 2026-09-04 is external and reported, not blocking) |
| CQ-19 | Verify served-board source contributions and withheld votes | `/api/data` + value-explain; `config/sources/rehabilitation.json` | The production contract is degraded by warnings `source_votes_withheld:fantasyNavigatorSf:448` and `idpShowCombined:656`. IDP Show republished 2026-10-18 22:32 but is still withheld in production. Open rows: SRC-STALEPRES, SIG-ACTIVE-OFF, the secondOpinion slot. | Confirm each withholding is the intended upstream-timestamp gate, and repair it if it is a defect. Verify the served votes after CQ-01/CQ-18. Wire or retire the secondOpinion slot. Update RESIDUAL_BLOCKERS §2. | Contract warnings on public `/api/status`; signed-in `/api/data` source votes | CQ-01, CQ-18 | NONE (signed-in board check needs OWNER-01) |
| CQ-20 | War Room loading shows the server's real analysis phases | `/trade` War Room + analyze status endpoint | #1828 adds `X-Analysis-Request-Id` and `GET /api/trade/analyze/status`; #1827 shows elapsed time only | Render the truthful server phases, with no time-remaining estimate | Vitest + E2E; production observation | CQ-03, CQ-05 | NONE |
| CQ-21 | Calculator correctness parity | `trade-logic.js::findBalancers` + `suggestions._find_balancers`; `/trade`; analyze route | B08: no test checks that one pick key prices the same across contract, simulate, finder, analyze and calculator. F02: two balancers with no shared fixture. D10: which surfaces consume overrides is undecided. D11: the user source-weight board is unlabelled and not forwarded. D02: the active package model is not named in the UI. J03: no 3+-team Monte Carlo refusal. | Add the B08 parity test. Add a shared JS/Python balancer fixture. Decide and document the override consumers (one owner), and label or forward the weights. Render the packageModel id. Write the J03 refusal copy. | Parity tests in both runtimes; vitest | CQ-06 merged (trade-logic.js) | NONE |
| CQ-22 | Trade engine and Trade Finder residuals | `src/trade` (finder, suggestions, angle, roster_capacity, team_context, pick_market); `src/roster_intel/packages.py` | H03: forced-drop cost ranks only the selected team (`finder.py:1148`), with no consolidation credit and no counterparty capacity in suggestions. O09: posture-aware picks need two-team mutual utility. Also open: C3-CAP-01, C3-CTX-01, C3-EQ-01, C7-PICKGEN-01, inventory 2.3/2.4 `verify_closure`, C3-MC-01 shadow band. O15: duplicate generator (C3-PKG-01). O16: the `/api/gameplan` roster_intel path is disconnected (`server.py:8785`). | Implement each row through the existing owners, with no new value math. Retire the duplicate generator. Give `/api/gameplan` a consumer or retire it (C2-GP-01). | Unit tests and closure reproductions; structure guards | CQ-15 (H07 for O09); CQ-03 merged | NONE |
| CQ-23 | Provisional trade thresholds labelled honestly; recalibrate only with evidence | `src/valuation_math` fairness_bands; finder / angle / suggestions / monte_carlo; `src/api/trade_history_asof.py` | `fairness_bands_v1` is PROVISIONAL. KTC-era PRIORs still in use: 3.3% display gate (E02), finder ratios (E04), angle ±5%, suggestions 769/overpay, Monte Carlo 80/60/40/20, history grades, aging ±200 (E05/N05; C3-AGE-01 partial). | Label E02 KTC-only or retire it. Keep explicit PRIOR labels wherever these numbers are shown. Before any change, preregister a validation target and fit with a holdout across board dates. Derive the aging band from measured volatility over `src/history`. q stays 0.78. | Label tests; preregistration; holdout results | none | NONE |
| CQ-24 | On-box valuation evidence: D8 package-model archive evaluation and D7 Signals IDP dependence | `src/valuation_math/package_model.py` residual report; `scripts/idp_rehab_eval.py --signals-dependence-only` | Not run because the data is box-local. The command is in `docs/sources/evidence/IDP_CLOSEOUT_2026-10-18/OPERATOR_COMMANDS.md`. Signals round 1 failed criteria 6/6b (#1773); the hold stays. | Add a read-only `workflow_dispatch` (pattern: `signals-onbox-verification.yml`) and run it. Record the residuals and `meta.packageModel.id`. Assess D7 under the new directive: similarity alone is not duplication. | Workflow run ids + recorded results | none | NONE |
| CQ-25 | Draft Valuation Batch G row 6: deployed smoke + rollback drill | `src/draft/rookie_auction` + `scripts/draft_valuation.py` | A-G code is deployed. Public `/api/draft-capital`: 216 unique pick ids, $3,600, all priced, frozen_fallback provisional. Row 6 is NOT_TESTED. | Desktop 1440 / mobile 375 smoke of `/league?tab=draft-capital` (2027, 2028, 2029, All Years). Run a one-command rollback/resume drill in a sandbox. Record PASS/FAIL. | Screenshots + drill log in the Batch G evidence doc | none | NONE |
| CQ-26 | Pick forecast correctness | `src/public_league/draft_order.py` + `src/ros/playoff_sim.py` + pick projection | Open ledger rows: draft-order rollover gap; points model on fallback constants (OWNER-TODO 2026-10-04); projector #1652 unverified; C1-PICK-03. B04/C1-U7 owned-pick distributions open. Calibration of c needs 2027 slots. | Use prior-season final standings across the rollover. Repair the points model. Replace the uniform tier EV with C1-U7 distributions. Check production after CQ-02. | Unit tests; public pick-forecast probe | CQ-02 | NONE (calibration EXTERNAL: needs 2027 slots) |
| CQ-27 | D11 playoff ROS counted once: calibrate before activation | `src/ros/playoff_sim.py` (C5-PLAY-01) | #1821 (train 10): `playoff_ros_counted_once` is OFF, G4 FAIL, incumbent kept | Repair the pre-sim calibration (AL-5c), or re-run on the box with the calibrated points model. Promote only if the gates pass. AL-5b after the 2026 title. | Recorded challenger results | CQ-02, CQ-26 (same files) | NONE (AL-5b EXTERNAL: season end) |
| CQ-28 | Rank-form drift audit failing every week | rank-form constants in `src/canonical/player_valuation.py`; `frontend/lib/value-history.js` RANK_FORM_CURVE | `audit-rank-form-drift.yml` has failed 6 weeks running (latest 38420587619). RMSE vs refit: offense 171.0 vs 89.9, IDP 175.9 vs 37.7 (threshold 25). Issue #898. | Inventory the consumers. If the constants feed served values, refit through the model-registry challenger path (Hill Autopilot rule: never hand-edit live constants). If they are display-only, refit every named location together. | Next scheduled run green; board_diff if any value moves | none | NONE |
| CQ-29 | Scheduled workflow and CI health | `.github/workflows` + `dynasty-*` units | intel-refresh 39130612952 failed (retry fix 6c2faef891 is deployed; #1795 open). Nightly E2E 39122837068 failed the a11y route-family test (spec updated since; #1793 open). Data Refresh has 9/26 failures, the last on 10-16. Some `dynasty-*` units are failing. The deploy unit hard gate takes 27-69 min. | Confirm the 09:10Z intel run and the next nightly are green, then close #1795 and #1793. Check the failing units on the box. Add a test-isolation guard (R-TEST-ISOLATION). Investigate the hard-gate runtime variance. | Green scheduled run ids; issues closed | none | NONE |
| CQ-30 | Open accessibility defects | Lane 6 / DataTable | Baselined axe findings: `/draft` pill, `/league-comparison` filter, `/auction/notifications` headers, franchise links. TC-E hover tint is below 4.5:1. DataTable aria-expanded. #730. | Token and underline fixes, removing each from the baseline. DataTable fix. Reproduce or close #730. | Axe in E2E with the baseline reduced | none (leave `/trade` until CQ-05 lands) | NONE |
| CQ-31 | Performance gates on every route | `docs/performance/CURRENT_ARCHITECTURE.md` owners | #1338 closed with no successor. Open: C10-CLOSE-05, C8-PSI-02 (desktop Rankings first render), C8-PERF-04 (Sharp pages), #1622 harvest. | Open a successor issue. Run a desktop + mobile route census with one comparable harness. Fix Rankings first render and the Sharp pages. | Before/after measurements on the same harness | none | NONE |
| CQ-32 | Game Day Command Center completion | `src/ros/game_day_sim` + `/game-day` | C5-GD-01 acceptance is the AL-4a on-box scorecard. Also open: #789 extras (TV mode, news, rooting), G1, GD-GATE-D/G, GD-UNCOVERED-SCORING, median race. | Run the on-box scorecard; build the extras; capture live slates in production | Scorecard + slate captures | CQ-44 workflow | NONE (live slates EXTERNAL: game timing; the BALLDONTLIE key is optional) |
| CQ-33 | Regenerate the completion dashboard and reconcile stale records | `scripts/completion_ledger.py` + `docs/completion/families` | Families were audited 2026-10-07 at 911411cb42, before trains 3-10. Stale records: (1) WORK_CLAIMS rows 54, 56-58, 63-68, 79-81 and 379. (2) Register rows D1 and D6 (both run in #1815), D11, D14 (#1818), K06 (#1814), OD-01 attestation (`OWNER_REQUESTED_TODO.md:728`), Tesseract install, IDP Show quarantine. (3) TC matrix lag on D04/H06/G04/G05/G13/C03. (4) DV, MI (C6-MGR-02 missing) and C3-IMPORT-IMAGE records. (5) Perfect Waivers, Model Lab, C6-SIG-02, median games D3, TC-01/11/12/14/15. (6) The CLAUDE.md #1618 section: the default-league `traded_picks` path now fails closed, and `/trade` imports `lib/pick-ownership`. | Re-audit the families from live evidence. Regenerate the dashboard with the canonical script. Close the claims. Refresh the register basis and RESIDUAL_BLOCKERS. Correct the CLAUDE.md section. | Ledger/doc parity tests | B1/B2 trains landed (WORK_CLAIMS conflicts) | NONE |

### P3: premium UI, remaining authorized features, learning

| ID | Feature / defect | Canonical owner | Current code / PR status | Remaining implementation | Required tests + production evidence | Depends on | Blocker |
|---|---|---|---|---|---|---|---|
| CQ-34 | Calculator UI residuals | `/trade` + shell (Lane 6) | F05 pick-context link and R01 announcement banner are marked "owner decision" in the TC-B2 notes. Also: 1920 wide-shell cap; screenshot FAB over the sticky column; hover-tint contrast. | Engineering decides these reversible UI choices (master §7): pick destination, banner content, wide-shell token, FAB placement. Then implement. | Desktop/mobile screenshots + axe | CQ-05, CQ-06 merged | NONE |
| CQ-35 | Calculator analytics: value trend, value span, 30-day movers, explainers | `/trade` + a private `src/history` read endpoint | M03, M06 and M07 not implemented; M08 and P04 partial | Build a private as-of read endpoint (fidelity labels, 2026-07-14 floor, never interpolated). Add the charts, ledger-backed movers, explainers and phone rendering. | Endpoint tests (no future observation selectable); vitest; mobile screenshot | CQ-05 merged | NONE |
| CQ-36 | Share-link compatibility migration and historical replay | `trade-share.js` / `trade-assets.js`; `decision_replay.py`; `src/history` | A05/C04 partial (D10 freezes the format until a tested migration). N03 is a banner only. N04 not implemented. G13 replay is asset-only: there is no as-of roster/projection/posture store. | Versioned payload with stable ids: old links keep resolving, and an unknown version degrades per asset. As-of replay per the HISTORICAL_TRADE_REPLAY spec. Build the as-of roster store, then team-context replay. | Round-trip tests over old link fixtures; replay tests | CQ-05 merged | NONE |
| CQ-37 | Trade Finder "Most Impactful" prior validation | `src/trade/discovery.py` + `config/trade/discovery_impact_prior.json` | PRIOR_UNVALIDATED. DISCOVERY_IMPACT_EVALUATION_2026-10-18 §8 says "evaluated, not validated". | Define an outcome target (AL-P5 receipts accepted vs offered, or realized value). Run a held-out comparison against the legacy orders. Keep the PRIOR label until then. | Held-out evaluation | CQ-45 receipts | EXTERNAL: needs accrued outcome receipts |
| CQ-38 | Draft capital residuals and promoted-generation replay | `src/draft` + `src/draft/rookie_auction/promotion.py` + `/league` draft-capital | promotionMode is `dry_run`, and replay refuses promoted pointers. C7-DRAFT-01 partial (Perfect Draft canonical pick identity). C7-DRAFT-02/G5 auto pre-auction snapshot open. PSI draft-capital not migrated. The `/draft` estimate's whole vs half dollars is undecided. | Implement promoted replay before the first live switch. Route Perfect Draft through `src/identity/picks`. Add the timer snapshot and the PSI table. Engineering decides the ladder precision (master §7). | Replay tests; rollback; smoke | CQ-25 | NONE (live flip EXTERNAL: class window opens 2027-05-01) |
| CQ-39 | Schedule Intelligence: B remainder, C, D, E | `src/public_league/schedule_impact.py` | EXECUTION_PLAN says "Next: C". No Hard Luck on main, and weekly_recap has no schedule statements. SI-D and SI-E are dependency-blocked. | C: Hard Luck, history view, recap statements, share card. B: league-valid calendar plus finish/qualification distributions. Then D (slot swaps), then E behind C5-WAR-01. | Unit tests; public screenshot of the Power schedule column | B/D after CQ-02; E after CQ-55 | NONE |
| CQ-40 | Power Rankings residuals | `/league` power + playoff archive | No week-in-progress note on main. Open: §12 rolling-origin backtest, AL-7, AL-P6 archive. | Render the note; run the report-only backtest; backfill the archive | Unit tests + public page probe | CQ-09 (same files) | NONE |
| CQ-41 | PSI Direction A migration of the remaining route families + mobile parity | Lane 6 / `components/ds` | UI_PARALLEL_LEDGER marks these audited but not certified: `/waivers /rosters /draft /phases`, `/angle /arbitrage /trades`, `/league` hubs, `/market` Sharp, `/bdvm /news /trending /idptc-rookies /players/compare`, `/settings /more`, `/admin /tools`, `/league-comparison`, `/auction`, `/managers`. Also C8-U2 mobile parity (#1153). | Migrate each family with desktop/mobile + axe evidence and retire the legacy CSS. Skip routes owned by an active batch. | Screenshots + axe per family | Per route: after the batch that owns it lands | NONE |
| CQ-42 | PSI production visual/axe certification | Lane 6 | Deployed but not verified in production: rankings / player file (#1520), `/trade`, `/game-day`, home/login, `/design`, D14 chart palette (#1818). | Anonymous routes now (`/login`, `/league`, `/auction`); private routes after OWNER-01. Close #1422/#1428. | Production screenshots + axe, light and dark | Private routes: OWNER-01 | NONE (private routes need OWNER-01) |
| CQ-43 | Rookie auction mock Phase 2 + rehearsal tooling | `src/auction` | **#1533** at bd39536fec is 1,890 commits behind. Validate 36652223664 FAILED (its own cookie-domain test). Docs conflicts in WORK_CLAIMS and LAUNCH_CHECKLIST. Unique work: `src/auction/feedback.py`, `ReportProblem.jsx`, `auction_load_rehearsal.py`. | Rebase, fix the test, re-review, merge (the official room stays gated). Run the §13 rehearsal scenarios. Check the backup timer. Fix axe on `/auction/notifications`. | Exact-head CI; rehearsal report | none | NONE |
| CQ-44 | Background jobs and timers proven on the production box | systemd timers / retention / deploy | Open: C10-CLOSE-04, AL-P2, G4/R-G4, R-G6, C1-RET-07, AL-P4, C4-MTL-02, AUC-BACKUP-TIMER, #1667 rollback drill. R-DEPLOY-SHA-PIN can be closed with deploy 39204644265. | Run read-only on-box checks via `workflow_dispatch` (same mechanism as CQ-24) and record the results. Harvest the 9-line Game Day diagnostic from `claude/gd-diag-evidence` if useful. | Workflow run ids | CQ-24 workflow | NONE |
| CQ-45 | Learning-loop evidence capture | Adaptive Learning (IC-1) | AL-P5 receipts exist for Best Offers only (#1747); finder, suggestions, angle, FAAB and Perfect Draft have none. AL-P7's 400-day prune will drop any Sharp trades not archived first. AL-2a census not run. | Add receipts through the existing owners. Archive trades before the prune. Run the on-box census. | Receipt tests; census run | CQ-22 (same engine files) | NONE |
| CQ-46 | Evaluators, scorecards and preregistered challengers | `src/model_registry` + Model Lab | Open: IC-2, IC-8, IC-9, C10-ML-01, AL-3b, AL-4a, AL-3d, AL-1b, AL-2b0/2b/2c, B3-BC, B3-E, B3-KL, VAM-V2-2, HILL-INDEP-TARGET (Hill gate 7 has no independent validation target), B2-B-REC, B3-D2 | Run the on-box scorecards, build the evaluators and preregister the challengers. No promotion without gates. | Recorded evaluator outputs | CQ-24/CQ-44 workflow; CQ-45 | NONE |
| CQ-47 | Source lineage and ingestion integrity | `scripts/source_inventory.py` + `Dynasty Scraper.py` + `src/identity` | Open: B3-G, B3-G-INSTR/MD-3b, SRC-DLFROOKIE, SRC-DLFVAL display, SIG-H-BATCH3, C4-KTC-01, CANONICAL_V2 (first-name-variant rung and no-position tiebreak), TE-PREM (#785), C4-SRC-02 (#1065), SRC-1425/R-1423, R-ER-P1 replay fixtures | Implement per row. Distinguish actual shared data lineage from numerical similarity, per the 2026-10-19 directive. No value change without gates. | Replay fixtures; dual-read `v2WouldChange`; board diff | CQ-01 merged (shared files) | NONE |
| CQ-48 | Analyst / podcast / YouTube intelligence (free sources only) | `src/intel` analyst ledger | C6-ANA-01 has no producer. Also open: C6-FRESH-01, C6-UPP-01, C6-POD-01, C6-YT-01, C6-EDGE-01. | Build the first scheduled producer, the freshness policy and the Player File feed | Producer tests; production feed observation | none | NONE (no paid spend) |
| CQ-49 | Player File completion + universal player link | `/players/[playerId]` + player link primitive | Open: inv-6.6 (BDVM, Sharp roster %, acquisition history), UI contract §10 value movement, #1337 | Add the sections; take per-generation evidence via `src/history`; convert id-less producers | Vitest; mobile screenshot | CQ-35 history endpoint | NONE |
| CQ-50 | Command Center action queue, portfolio/exposure, Edge Alerts | terminal (C7-CMD-01) | Open: C7-CMD-01/CE-04, CE-06, CE-26, C7-ALERT-01. CE-06 and CE-26 likely overlap the Manager Intelligence portfolio (#1762). | Reconcile the overlap with MI first, then build on the existing owners | Unit + E2E | none | NONE |
| CQ-51 | Decision-product catalog | C7 decision products | The dashboard shows decision products at 0% (20 active rows: C7-AI-02..05, CE-07/08/12/13/14/14A/17/22/24/25/27). No Market ADP, Lineup IQ or personal-overlay code exists. | Confirm each row's manifest authorization, then build in dependency order over the canonical owners | Per-row acceptance | CQ-22, CQ-50 | NONE |
| CQ-52 | Public league, awards and reports residuals | `src/public_league` | Open: HONORS §7 traded split (absent from awards.py); T-NEW-03 Sync Sleeper (`server.py:14760` says "future"); awards mobile check; C9-SHARE-01, C9-WRS-01, C9-UR-01/02, C9-RECAP-01, C9-TRUTH-01, C9-V3-01 | Build per row. Sleeper sync is read-only (no write actions). | Unit tests + public probes | Some rows dependency-blocked; `server.py` only after B2 lands | NONE |
| CQ-53 | Roster intelligence residuals | `src/roster_intel` | Open: C2-WEAK-01, C2-AGE-03, C7-AGE-01, LANE-A-CLASSIFY-NEED. Production checks pending: C2-STR/CORE/DROP. | Implement; run the production checks | Unit tests; signed-in checks | CQ-22 (gameplan) | NONE |
| CQ-54 | FAAB and waivers residuals | `src/trade/faab_engine` + `/waivers` | Open: C4-FAAB-01 (4th population), V1-56 no-team tiles, #738, Live Waiver Opportunity, C4-WAIV-01 production check | Implement per row | Unit tests + signed-in check | none | NONE |
| CQ-55 | Projection ensemble + Player Impact (xWAR) | `src/ros` projections / `src/bdvm` | Open: C5-PROJ-C/E/F, C5-ROS-01, C5-WAR-01 (xWAR), C5-FIT-01/nfl, B3-J2, C5-ST-01 (#802) | Register the adapters, migrate the consumers, build xWAR with leakage tests | Leakage tests; backtest | none | NONE (college fit needs the optional CFBD key, OWNER-06) |
| CQ-56 | Sharp Insider format filter + decision workflow | `src/sharp` + `/market` | Open: SHARP_INSIDER §7.2, §8 steps B/G, C4-MTL-02 first-capture record | Implement over the captured format dimensions | Unit tests; signed-in check | none | NONE |
| CQ-57 | League Comparison with live 2026 scoring | league comparison | Donor branch `codex/league-comparison-2026-live` (a79f7e435d; PR #1399 closed). The requirement is in OWNER_REQUESTED_TODO (#1469 / train #1472). | Add the EXECUTION_PLAN §0 pointer (CQ-17). Then a corrected port: finished-weeks gate, no caching at the horizon. | Unit tests; production check | CQ-17 | NONE |
| CQ-58 | Engineering reliability priorities | CI / requirements / typed contracts | Open: R-ER-P2/P3/P6/P8/P10/P11; Node 22 migration (F-PRIV-01) | Extend the typed contracts, define the SLO set, migrate to Node 22 | CI green | CQ-59 | NONE |

### P4: final integration and hygiene

| ID | Feature / defect | Canonical owner | Current code / PR status | Remaining implementation | Required tests + production evidence | Depends on | Blocker |
|---|---|---|---|---|---|---|---|
| CQ-59 | Dependency update trains | `requirements.txt` / frontend package files / workflows | 12 Dependabot PRs. Backend: #1661 numpy (needs board_diff), #1662, #1663 (Validate FAILED), #1506, #1508. Frontend: #1738 (supersedes #1660), #1687, #1688, #1728 (FAILED), #1729 jsdom 30 (FAILED). CI: #1575 (class B, goes through RC). | Close #1660. Rebase or recreate the rest on main. Diagnose each failure or close the PR. Land one backend train and one frontend train. | Full CI; board_diff for numpy | Frontend train after CQ-05/CQ-06 land | NONE |
| CQ-60 | Unified Manager of the Year stays validation-only (D12) | `src/public_league/moty_candidate_policy.py` | **#1513** at 221df2e711 is 1,994 commits behind with 7 doc conflicts. Its /0.90 rescale is a redistribution that D12 forbids. | Rebase onto the policy module as a labelled candidate, or keep it unmerged. No promotion before 2027. | Full CI | none | NONE (promotion EXTERNAL: 2027 season) |
| CQ-61 | PR and branch hygiene | repo | #1660 is superseded. #1755 is a League Tycoon parking record. 46 orphan branches are ahead of main, all superseded or absorbed. `claude/analyze-trade-v3` is handled in CQ-14. | Close #1660. Merge #1755 as a record or close it with a disposition. Delete the absorbed and superseded branches after confirming archive tags. | n/a | none | NONE |
| CQ-62 | Owner-intent recovery #1336 + the #1628 intake pointer | `docs/OWNER_REQUESTED_TODO.md` | #1336 is PARTIAL; R-1628-INTAKE open | Add the pointer row. Present the ambiguous list once (OWNER-09) without promoting it to scope. | Docs gates | CQ-17 | NONE |
| CQ-63 | Site-wide closure pass | C10-CLOSE | Open: C10-CLOSE-01/02/03/07, C0-GOV-01/08 | W30 duplicate-owner census and retirement; browser matrix; final regression; dashboard checked against the master directive §14 Definition of DONE | Final regression + production matrix | All P0-P2 items | NONE (C10-CLOSE-03 needs OWNER-01) |

## Batches

A batch is a set of items that can be finished and released together. It owns the listed files exclusively while it is active.

| Batch | Items | Start now? | Owns (exclusive while active) | Notes |
|---|---|---|---|---|
| B1 Release: train 10 deploy + train 11 | CQ-04, CQ-02, CQ-08 | Yes (in flight) | `luck.py`, `playoff_odds.py`, `frontend/app/trades/page.jsx` | Coordinator-managed. Deploy 39211570693 is running; #1829 Validate PR is running. Train 11 deploys after train 10. |
| B2 Trade directive train | CQ-06, CQ-05, CQ-03, CQ-07, CQ-20 | Yes (in flight) | `frontend/app/trade/*`, `frontend/lib/trade-*.js`, `va-comparison.js`, `src/trade/analyze_trade.py`, `server.py` analyze route | Coordinator-managed. #1826 is ready; #1827 is in its fix round; #1828 is CI green and awaiting re-verification. #1826 + #1827 go together (vaSlot); #1828 overlaps only in WORK_CLAIMS. CQ-07 and CQ-20 follow the merge. |
| B3 Source-voting correction | CQ-01, CQ-18, CQ-10, CQ-19 | Yes (rework of #1817) | `src/api/data_contract.py`, `src/api/feature_flags.py`, `config/sources/*`, `README.md`, `docs/ARCHITECTURE.md` | The existing #1817 owner does this; no parallel branch. Redirect the running verification to the revised design. Keep D4/D5 flags independent. CQ-19 comes after deploy. |
| B4 Power Rankings attribution | CQ-09, CQ-40 | Yes (stacked on #1822 head 4217b55d1e) | `src/ros/power_v2.py` + tests, `/league` power frontend | Must not edit `luck.py` or `playoff_odds.py`; it only consumes #1822's `by_franchise` API. Release in or after train 11. |
| B5 Screenshot import completion | CQ-11, CQ-12 | Yes | `src/trade/screenshot_import/`, `frontend/lib/screenshot-import.js`, screenshot fixtures, a new prod-auth spec | Do not touch `frontend/app/trade/page.jsx` (B2). CQ-12's production upload needs OWNER-02. |
| B6 Draft Valuation finish | CQ-25, CQ-38 | Yes | `scripts/draft_valuation.py`, `src/draft/*`, `docs/draft/*` | CQ-25 is a public smoke test plus a drill. CQ-38's live flip waits for 2027-05-01. |
| B7 Playoff and pick forecast | CQ-26, CQ-27 | No: after train 11 merges | `src/ros/playoff_sim.py`, `src/public_league/draft_order.py`, pick projection | Shares the playoff files with #1822. |
| B8 Trade wave 2: decision engine + team context | CQ-14, CQ-15 | No: after B2 merges | `trade_decision.py`, `analyze_trade.py`, `best_ball_utility.py`, War Room components | Its frontend work is limited to the War Room components; B10 owns `page.jsx`. |
| B9 Trade wave 2: generators + parity | CQ-21, CQ-22, CQ-23 | No: after B2 merges | `finder.py`, `suggestions.py`, `angle.py`, `roster_capacity.py`, `pick_market.py`, `roster_intel/packages.py`, `findBalancers` in `trade-logic.js`, fairness bands | Never touches `analyze_trade.py` or `trade_decision.py` (B8). CQ-22 O09 comes after CQ-15 H07. |
| B10 Trade wave 2: calculator UI, analytics, share/replay | CQ-34, CQ-35, CQ-36 | No: after B2 merges | `frontend/app/trade/page.jsx`, share/assets libs, private history endpoint | Coordinate War Room boundaries with B8. |
| B11 TC-F release | CQ-13 | No | none (acceptance only) | Needs B2, B8 and CQ-21 merged, plus OWNER-01. |
| B12 Authenticated production verification sweep | CQ-16 | No: gated on OWNER-01 | `tests/e2e/specs/prod-auth/*` | Runs as soon as OWNER-01 is done. Each defect goes to its owning item. |
| B13 Records and governance | CQ-17, CQ-33, CQ-62 | Yes (CQ-17 now) | `docs/EXECUTION_PLAN.md`, `docs/owner/*`, `docs/completion/*`, `docs/COMPLETION_QUEUE.md`, CLAUDE.md pick-ownership section | Coordinator docs PR. OWNER_REQUESTED_TODO edits are append-only. WORK_CLAIMS closures and the dashboard regeneration come after B1/B2 land. |
| B14 CI, scheduled workflows, on-box evidence | CQ-29, CQ-28, CQ-24, CQ-44 | Yes | New `workflow_dispatch` files, rank-form constants, scheduled workflow fixes | Workflow files are class B, so they go through RC. CQ-28 never hand-edits the live Hill constants. |
| B15 Accessibility, performance, PSI (Lane 6) | CQ-30, CQ-31, CQ-41, CQ-42 | Yes | `components/ds`, non-owned route pages, legacy CSS | Lane 6 stays active. Skip `/trade` (B2/B10), `/trades` (B1), `/league` power (B4), draft-capital (B6) and `/auction` (B18) until those land. Coordinate shared ds primitives with B2. |
| B16 Game Day | CQ-32 | Yes | `src/ros/game_day_sim*`, `/game-day` | The on-box scorecard uses the B14 workflow. |
| B17 League intelligence | CQ-39, CQ-52, CQ-57, CQ-60 | Yes (SI-C, awards, recap) | `schedule_impact.py`, `awards.py`, `weekly_recap`, league comparison, `moty_candidate_policy.py` | SI-B/D wait for train 11; CQ-57 waits for the CQ-17 pointer. Do not touch `server.py` until B2 lands. |
| B18 Rookie auction mock | CQ-43 | Yes | `src/auction/*`, `/auction` | #1533 rebase; the official room stays gated. |
| B19 Player and market intelligence | CQ-48, CQ-49, CQ-55, CQ-56 | Yes | `src/intel` analyst ledger, `/players/[playerId]`, `src/ros` projections, `src/bdvm`, `src/sharp` | The CQ-49 history section waits for the CQ-35 endpoint. |
| B20 Decision products, roster, FAAB | CQ-50, CQ-51, CQ-53, CQ-54 | No: after B9 | terminal, C7 products, `src/roster_intel`, `faab_engine`, `/waivers` | Shares generator and roster_intel owners with B9. |
| B21 Valuation follow-through + learning | CQ-47, CQ-45, CQ-46, CQ-37 | No: after B3 and B9 | source inventory, scraper, identity, receipts, model_registry | Receipts touch the engine files owned by B9. |
| B22 Dependencies and hygiene | CQ-61, CQ-59, CQ-58 | Yes (hygiene + backend deps) | `requirements.txt`, branch deletion | The frontend deps train, Node 22 and CI actions wait until B2/B10 land, to avoid lockfile churn under active frontend PRs. |
| B23 Final closure | CQ-63 | No | none | Last. |

**Start now (14 batches):**
- In flight: B1, B2.
- Redirect: B3.
- Ready to start: B4, B5, B6, B13, B14, B15, B16, B17, B18, B19, B22.

## Owner-only actions

Only these items need the owner. Every other blocker belongs to engineering.

1. **OWNER-01: Re-enable authenticated production verification.**
   - Workflows: `prod-e2e-smoke.yml` (262433998) and `v1-authenticated-verification.yml` (342419392), `disabled_manually` since 2026-10-08 07:51Z after the security incident.
   - Steps: run `gh workflow enable prod-e2e-smoke.yml`, then `gh workflow enable v1-authenticated-verification.yml`, then `gh workflow run v1-authenticated-verification.yml -f suite=all -f league=dynasty_main -f pass_hours=2`. Full instructions are in `docs/ops/AUTH_VERIFICATION_REENABLE.md`.
   - Unblocks: CQ-13 and CQ-16, the production evidence for CQ-03, 04, 05, 07, 08, 19, 42 and 63, and production latency measurement.
2. **OWNER-02: Member-session screenshot proof.**
   - Guest passes are refused at upload (403 `guest_read_only`).
   - Either upload the real screenshots yourself (the Dart/Achane KTC page, a phone shot, a multi-shot pair, dark mode), or approve a non-guest verification credential.
   - Unblocks CQ-12.
3. **OWNER-03: Rotate the exposed `JASON_LOGIN_PASSWORD`** (D18, ODR-PASSWORD-ROTATION). Record only the date.
4. **OWNER-04: Apply the main protection ruleset and retire unused deploy keys.**
   - Ruleset: `deploy/github/main-protection-ruleset.json`, admin runbook §1.
   - Deploy keys: write keys 145025388 and 148579683, after a fingerprint check (runbook §2).
5. **OWNER-05: League rule.** Does the dynasty_main rookie-draft order count league-median results (ODR-DRAFT-ORDER-MEDIAN)?
   - Needed before the 2026 regular season ends.
   - Until you answer, the head-to-head record is used.
6. **OWNER-06: Optional free credentials.**
   - BALLDONTLIE key: Game Day live state (D17).
   - CFBD key: college fit (CQ-55).
   - Neither blocks anything else.
7. **OWNER-07: Official 2027 rookie auction gates (D20).** VAPID keys (which also gate push), human rehearsals, official rules, off-host DR, pool and launch authority. These come after the late-April 2027 NFL draft; VAPID can be done any time.
8. **OWNER-08: Unauthorized scope candidates** OD-06, OD-07 and the R44 sixth slot. These happen only if you want them. They are not requested and not counted.
9. **OWNER-09: #1336 ambiguous owner-intent candidates.** A one-time review, non-blocking. The optional Game Day visual sign-off (#1335) is also non-blocking.

**Not owner-only.** The master directive §7 delegates these reversible choices to engineering, so they will not be asked:
- the F05 pick-context link and R01 banner;
- the 1920 wide-shell cap;
- the `/draft` estimate's whole vs half dollars;
- the Power Rankings roster-11 attribution;
- the 90s analyze timeout bound.

## Shipped and verified

- Trains 7, 8 and 9 are live. Production build eb10d3e12d contains 24e218205e, fd87c9068a (#1809) and a079ae938c (#1820). Deploy 39204644265 succeeded at 06:49:50Z.
- Production runtime is healthy (2026-10-19 06:51Z):
  - `/api/health`: ok, data age 0.0h, contract_ok.
  - Board: 1,131 players, 20/26 sources.
  - Structural and source-health errors: empty. Circuit breakers: closed.
- Anonymous auth gates hold:
  - `/trade` returns 307 to `/login`.
  - `/api/trade/analyze`, `/api/trade/import-screenshot` and `/status` return 401.
- Draft Valuation A-G pre-deploy scope (#1812 via train 9): 216 unique pick ids, $3,600 priced, 0 unpriced, 321/321 tests.
- Deploy pipeline: both failures in the last 15 runs (39156965228 hard gate, 39124863471 SSH timeout) were followed by green deploys.

## Shipped, production proof pending (tracked by the items named)

| Work | PRs | Tracked in |
|---|---|---|
| Trade Calculator TC-A to TC-D2, K06 Second Opinions unavailable state | #1790 #1791 #1800 #1805 #1814 | CQ-13, CQ-16 |
| TC-E keyboard and balancer clarity | #1824 (train 10, deploying) | CQ-04 |
| Geometric package model q=0.78 | #1771 | CQ-24 |
| Manager Intelligence A-F, saved managers and alerts | #1762 #1779 #1781 #1783 #1797 #1796 #1801 | CQ-16 |
| Trade Finder meaningful discovery + Package Builder sides | #1788 #1789 | CQ-16 |
| Screenshot import full-page KTC fix | #1816 | CQ-12 |
| Draft Valuation E/F/G | #1802 #1806 #1812 | CQ-25 |
| D14 chart palette | #1818 | CQ-42 |
| Perfect Waivers, Model Lab UI, MarketTicker | #1717 #1723 #1720 | CQ-16, CQ-33 |
| Median games in record and seeding (D3) | #1719 | CQ-33 |
| D1 and D6 challengers run (holds retained) | #1815 | CQ-33 |

## Documented exceptions (healthy by justification, not by fix)

- `public-league-warmup` runs every 2-3 hours instead of every 20 minutes because GitHub throttles scheduled runs. Every run succeeds. Move it to an on-box timer only if cold public snapshots become a user problem.
- FantasyPros expert data has been stale upstream since 2026-09-04. This is external and is reported honestly, never shown as 0.
- The 3+-team Value Adjustment comparison is deliberately not computed (#1826). Extending it would be a methodology decision.

## Deferred / out of scope (not counted)

- DFS and League Tycoon: shelved by the master directive §7. #1755 only records the parking.
- Certified prepared serving (`codex/performance-serving`, PR #1346 closed, tag `archive/pr-1346`): future scope under #1338. It needs EXECUTION_PLAN authorization.
- Trade Calculator ancillary rows:
  - R02, R03 (/about) and L06: not authorized.
  - B09: waits on #1529.
  - O14: waits on OD-02.
  - R04, K07 and J05: superseded.
- The draft-capital stack effect stays informational until the #1529 prerequisites are met.
- The official 2027 rookie auction launch: OWNER-07, after the 2027 NFL draft.
