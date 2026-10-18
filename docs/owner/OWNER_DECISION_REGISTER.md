# Owner decision register

**Status:** canonical consolidated register (Deliverable A of the owner decision closeout directive,
2026-10-18, `docs/owner/OWNER_DECISION_CLOSEOUT_2026-10-18.md`). It lists every owner decision that was open, or
recorded as open after it had been decided, across the repository's owner-action and decision records. It gives
each one its decision, its provenance and its **live** status.

**What this register is not:**

- It is not authorization. `docs/EXECUTION_PLAN.md` §0 authorizes.
- It is not the intake ledger. That is `docs/OWNER_REQUESTED_TODO.md`.
- It is not the completion denominator. That is `docs/completion/CALCULATOR_COMPLETION_DASHBOARD.md`, generated
  by `scripts/completion_ledger.py`.

Where records conflicted, the latest specifically scoped owner decision wins, and the row cites it.

**Reconciled:** 2026-10-18, against base `3bc9cbfcec` (release train 8 head, #1809).

**Records searched:**

- `OWNER_DECISION_REQUIRED`, "owner decision", "needs owner", `HUMAN_ACTION`, "owner approval required",
  "pending owner" and "OWNER ACTION" across `docs/` and `config/`;
- the completion ledger's owner asks and `OWNER_ACTION_REQUIRED` rows;
- the Trade Calculator workstream, decision-engine audit and feature matrix;
- the IDP rehabilitation evaluation;
- UMOTY #1513, issue #1428, the Scope Manifest §6 `OD-*` table;
- the DFS records, the League Tycoon records, the draft-capital / draft-order / `dynasty_new` records, and the
  Signals and FantasyPros records.

## Status vocabulary

Status is true to live evidence and nothing stronger. Merged ≠ deployed ≠ production-verified. An approved
methodology is not a validated implementation.

| status | meaning |
|---|---|
| `DECIDED` | the owner's answer is recorded; any implementation is not built yet, or none is needed |
| `IMPLEMENTED` | built on a branch or PR; not merged |
| `MERGED` | on `main` (or in an approved release train that has merged); not yet in a deployed build |
| `DEPLOYED` | in a production build (`build.commit` contains the merge); the specific behaviour has not been observed in production |
| `PRODUCTION_VERIFIED` | the behaviour was observed on production |
| `EVIDENCE_PENDING` | a conditional activation or challenger whose evidence gate has not passed; nothing activates until it does |
| `HUMAN_ACTION_REQUIRED` | needs an owner or administrator: credentials, permissions, a league-rule fact, an official launch |
| `OWNER_PAUSED` | deferred by the owner (DFS, League Tycoon); not rejected, not complete, not to be requested |

## Production facts used

- Release train 7 (#1803) merged 2026-10-18 18:16Z and is deployed and production-verified at build
  `24e218205e`.
- That build contains release trains 5 (#1782), 6 (#1794) and 7, plus #1771 and #1786 (verified by git
  ancestry). "Production-verified" there is build-level. A feature-level claim needs its own observation, so rows
  below say `DEPLOYED` unless the behaviour was observed.
- Release train 8 (#1809: #1800 #1801 #1802 #1804 #1805 #1806 #1808 #1811) is approved and validating. It is
  **not merged**.
- #1812 (draft valuation Batch G pre-deploy) is open.
- #1810 (DFS pause, docs only) is open, and the coordinator merges it separately.

**Operator check used by several rows.** Run it on the box after any deploy to confirm the active package model
without exposing data:

```bash
cd /home/dynasty/trade-calculator && /home/dynasty/.venvs/trade-calculator/bin/python -c \
  "from src.valuation_math import package_model as m; print(m.receipt())"
```

The served stamp is `meta.packageModel` on the authenticated `/api/data?view=app`, observable once the
authenticated verification workflow is re-enabled (runbook §6).

## Register

### Valuation and sources

| ID | family | question | decision | evidence | risk / impact | status | PR / tests | remaining action |
|---|---|---|---|---|---|---|---|---|
| `ODR-DLF-IDP-VOTE` | Rankings & sources | Reverse the DLF offense-only vote hold for `dlfIdp` / `dlfRookieIdp` now (a), or keep it until the preregistered IDP outlier challenger reports (b)? | **(b) keep the hold** — D1 (2026-10-18). Restore only after `idp-hampel-n3-v1` meets its preregistered criteria AND an independent full-board validation passes. Outlier standards are never lowered to activate the source. DLF IDP and rookie IDP stay under one family cap | `docs/sources/IDP_REHABILITATION_EVALUATION_2026-10-18.md` §2, §4: reversal re-activates the filter on 158 rows, drops 32 other-source votes, moves 31 rows ≤ 48% | a premature reversal moves IDP values materially; keeping the hold costs one fresh family on 151 rows | EVIDENCE_PENDING | hold: #1758 merged 2026-10-17, deployed (`voteHold` verified then). Challenger: preregistered (`docs/valuation/evidence/idp-outlier-n3-2026-10-18/`), not implemented | implement and run `idp-hampel-n3-v1` on the 105 frozen archives (seed 2029, h = 7 primary) without changing the preregistration; if it passes, run independent board validation, then a reviewed, reversible release |
| `ODR-IDP-SHARED-CAP` | Rankings & sources | Should IDP Trade Calculator and `idpShowCombined` share one IDP-scoped correlation cap? (ledger `OD-IDPTC-CAP`, IDP half) | **Approved** — D2. Defensive rows only. Offense and pick evidence is not combined. The IDP-only Show board never becomes an extra voter. Implemented through the source-lineage and family-cap owners | IDP Trade Calculator IDP order is ORDER-IDENTICAL to the IDP Show IDP-only board since 2026-10-10 (evaluation §3, residual 0.992) | latent double count once the vendor republishes. Zero board change today (`idpShowCombined` quarantined) | EVIDENCE_PENDING | not implemented; registry text updated (`config/sources/rehabilitation.json`) | default-off row-scoped rule in `correlation_group_for`; baseline-vs-challenger replay with independent confidence-count checks; validated release before served values move |
| `ODR-IDPTC-OFFENSE-VOTE` | Rankings & sources | Does an IDP Trade Calculator offense opinion join the `ktcCrowd` cap or get excluded? (ledger `OD-IDPTC-CAP`, offense half) | **Exclude an unproven extra offense vote** — D3. A proven KTC Crowd derivative enters only under the KTC Crowd cap | 2026-10-01 sweep measured IDPTC offense as a lagged KTC Crowd copy outside the cap | an independent duplicate would manufacture agreement | DECIDED | — | measure the existing IDPTC offense voting behaviour and contribution; change nothing that is independently evidenced until measured |
| `ODR-DLF-VALUES-VOTE` | Rankings & sources | Do DLF Values vote, and in which representation? (ledger `SRC-DLFVAL-2026-09-24/vote`; EXECUTION_PLAN "DLF Values vote" gate) | **Rank-to-Hill approved, conditionally**, as an offense-only member of the existing DLF family. Raw/max rejected (≈ 89.7% outlier rejection) — D4 | gate re-run 2026-10-18 (evaluation §5): rank → Hill drop 0.009, board p90 1.33%, 24 stable daily releases | low measured board impact; a second DLF family would double-count | EVIDENCE_PENDING | gate script `scripts/dlf_values_gate.py`; nothing registered | split DLF's one cap with DLF Rank; verify timestamps, completeness, longitudinal stability and top-player movement; run offense / picks / IDP-noninterference / geometric-package regression; reversible observable release; keep the current policy if any gate fails |
| `ODR-FP-UPSTREAM-CLOCK` | Rankings & sources | Should FantasyPros freshness use the stricter `EXPLICIT_UPSTREAM_TIMESTAMP`? | **Yes** — D5. The voting clock is the provider's own publication / expert-update evidence, never our fetch time. Stale is reported stale / unavailable, never zero | #1777 persists `publishedAt` 2026-09-04 (2 of 6 experts); 16 dual-family duplicate identities | stricter freshness may remove FantasyPros IDP eligibility, which is the correct outcome | DECIDED | #1777 merged (train 5), deployed (evidence only; style not switched) | switch the freshness style in `config/sources/freshness_v1.json`; finish the dual-family duplicate-identity analysis without suppressing independent material |
| `ODR-IDP-DEEP-TAIL` | Rankings & sources | Price deep IDP rank votes by Hill extrapolation, or translate them to IDP Trade Calculator native values at equivalent effective rank (N-1)? | **Run a preregistered challenger**; the incumbent Hill method stays unless it convincingly improves — D6. Tail saturation rank and global coordinate are not altered as a side effect | evaluation §3: value-direct vs rank→Hill differ ×0.71 past rank 500 | DB/LB deep rows skewed; replacing without evidence risks calibration | EVIDENCE_PENDING | — | preregister, then run against the independent holdout under model-governance thresholds |
| `ODR-SIGNALS-IDP` | Rankings & sources | Activate Signals IDP, or preregister a new candidate (and who decides it)? | **Hold maintained** — D7. Box-local evidence and diagnosis come first. Engineering preregisters any genuinely different challenger before testing; no threshold, timestamp or denominator changes | Candidate A failed round 1, criteria 6 and 6b (#1773) | activating a failed candidate would publish biased IDP values | DEPLOYED | hold in `PRIVATE_SOURCE_VOTE_HOLDS`; #1773 merged (train 5) | on-box dependence analysis (`signals-onbox-verification`); preregister any new candidate |
| `ODR-SRC-AUTH-POSTURE` | Rankings & sources | `OD-01`: record (or forgo) an IDP Trade Calculator authorization, and set one posture for credentialed sources (DLF, Draft Sharks, IDP Show, Flock) | **Not covered by the directive.** D17 only says "legitimate, existing free data when it meets provider-use requirements". KTC half resolved 2026-09-30 (#1555) | Scope Manifest `F-EXT-02` / `F-EXT-03` | provider-terms exposure; none of today's builds is blocked | HUMAN_ACTION_REQUIRED | — | one owner record: is each credentialed / IDPTC collection permitted for this non-commercial site under its terms (record the artifact), or re-scope it. Recommended: record the existing permissions you hold; nothing changes in code |

### Trade

| ID | family | question | decision | evidence | risk / impact | status | PR / tests | remaining action |
|---|---|---|---|---|---|---|---|---|
| `ODR-PACKAGE-MODEL` | Trade | Which package Value Adjustment is active, and may q be recalibrated from accepted trades? | **`geom_q078_v1`, q = 0.78, stays active**; KTC `ktc_2026_04` kept for rollback / historical comparison; no recalibration from a small set of accepted trades — D8 (activation approved 2026-10-17) | `config/trade/package_model.json` `active: geom_q078_v1`; residuals on 39 own-league trades (evaluation §6) | recalibrating on accepted trades would treat market clearing as fair value | DEPLOYED | #1771 merged 2026-10-17 (`f57775c65c`), in production build `24e218205e`; `tests/valuation_math/test_package_model.py` | observe live `meta.packageModel.id == geom_q078_v1` (operator check above); independent evaluation on the server-local production trade archive (`data/intel`) |
| `ODR-BEST-OFFERS-250` | Trade | In Best Offers, does a positive adjusted gain ≥ the band's `absoluteMinimum` (250) qualify a FAIR package as meaningful (Option B)? | **Yes, Best Offers only** — owner 2026-10-18 (#1791 comment); D8 says not to reopen it | `docs/trade/tc-c-fairness-band-impact/results.json` | FAIR classification, `equity_verdict` and YES/NO unchanged | DEPLOYED | #1791 via release train 6 #1794 (deploy succeeded) | production observation on authenticated `/arbitrage` Best Offers |
| `ODR-TC-NEAR-TIE` | Trade | Should a near tie with complete evidence read NO or NOT ENOUGH EVIDENCE? | **"NO — TOO CLOSE"**; NOT ENOUGH EVIDENCE only when material information is missing — owner 2026-10-18 (TC-C decision 1) | `docs/trade/TRADE_DECISION_ENGINE_AUDIT.md` §7.10 | — | DEPLOYED | #1791 via #1794 | authenticated production check of the War Room headline |
| `ODR-TC-DEFAULT-STRATEGY` | Trade | Default strategy when the user picks none? | **Inferred from competitive posture + league evidence**, always shown, always overridable — owner 2026-10-18 (TC-C decision 2) | workstream TC-C | — | DEPLOYED | #1791 via #1794 | as above |
| `ODR-TC-FAIRNESS-BANDS` | Trade | Re-evaluate the fairness bands for the geometric model? | **Relative difference with an absolute minimum, provisional until validated**; q never modified — owner 2026-10-18 (TC-C decision 3) | workstream TC-A threshold inventory (PRIOR labels) | KTC-calibrated thresholds mislabel geom results until validated | DEPLOYED | band owner in #1791 via #1794; numbers labelled provisional | validate on offense, IDP, picks, consolidation and large packages |
| `ODR-TC-SO-EVEN` | Trade | Second Opinions "even" band? (feature matrix `TCM-E06`) | **Within 1% of the larger adjusted side** (initial) — owner 2026-10-18 (TC-C decision 4) | `docs/trade/SECOND_OPINIONS_TODO.md` | — | DEPLOYED | TC-A #1790 via #1794; `frontend/__tests__/second-opinions-even-band.test.js` | validate the 1% on real trades |
| `ODR-TC-TEAMIMPACT` | Trade | Retire `teamImpact.verdict` as a competing YES/NO? | **Retired**; the roster analysis stays as input, no double counting — owner 2026-10-18 (TC-C decision 5) | workstream TC-A | — | DEPLOYED | #1790 via #1794 (`822b9fb2f8`) | — |
| `ODR-TC-RETOOL` | Trade | How does RETOOL map to a strategy? | **RETOOL → BALANCED** (PUSH → win now, REBUILD → long-term, HOLD → balanced); supersedes the audit's RETOOL → long-term proposal — owner 2026-10-18 (final) | audit §7.10, workstream TC-C | — | DEPLOYED | #1791 via #1794 | — |
| `ODR-TCM-K06` | Trade | How does Second Opinions show a source excluded for freshness, access, identity or other evidence reasons? | **"Unavailable — [actual reason]"**: never EVEN, never our canonical value as its vote, never a counted second opinion, never zero, never hidden; the tally matches the displayed independent opinions — D9 | `freshnessExcludedSources` stamped on rows but ignored by `second-opinions.js` | an excluded source reading EVEN fabricates agreement | DECIDED | not built | implement in the Second Opinions owners (TC-B2) with regression tests |
| `ODR-SO-PARTIAL-VOTE` | Trade | May a partially covered Second Opinions row ever vote? (`SECOND_OPINIONS_TODO.md` "Open") | **Never**: any canonical fallback makes the row HYBRID_ESTIMATE, and the tally counts full-source rows only — owner package 2026-10-17; reaffirmed by D9 | owner package 2026-10-17 | — | DEPLOYED | release train #1768 (merged 2026-10-17), in production build | — |
| `ODR-TC-MULTITEAM` | Trade | What does the decision engine say for 3+-team trades? | **Supported analysis only when it identifies the user's side and every side; otherwise "a reliable YES/NO recommendation is unavailable"** — never a fabricated binary — D10 | directive D10 | a forced binary on unsupported shapes misleads | DECIDED | — | verify the engine's refusal path in TC-E/TC-F tests |
| `ODR-TC-SHARELINK` | Trade | May the share-link format change during the redesign? | **Frozen until a coordinated, tested compatibility migration**; no silent URL breaks — D10 | workstream (A05/C04/N03 wait on the freeze) | — | DECIDED | freeze in force | migration is its own tested unit |
| `ODR-POSTURE-840` | Trade | #840: reconcile the owner's posture concept with the continuous design | **Decided 2026-10-03**: owner-chosen map (declared map + season timing, PRIOR). The intake row still said "OWNER DECISION REQUIRED" — closed in place | CLAUDE.md "Competitive Posture"; `src/roster_intel/window.py::competitive_posture` | — | DEPLOYED | Wave B #1642 merged 2026-10-04 | — |

### Power, playoff odds and awards

| ID | family | question | decision | evidence | risk / impact | status | PR / tests | remaining action |
|---|---|---|---|---|---|---|---|---|
| `ODR-PLAYOFF-ROS-DOUBLE` | Power & playoff odds | Remove the double-counted ROS multiplier from the playoff / title simulator (ledger `TODO-2026-09-26-D2`)? | **Double-counted evidence is not acceptable; removal approved as policy** — D11. Replacement only through the AL-5c shadow (or equivalent preregistered) comparison; incumbent kept otherwise; official Power Rankings formula untouched | `playoff_sim.py` `emp_mean*(1+0.2·ros_z)`; Brent 99.45% vs 84.6% (2026-09-26) | overconfident championship odds today | EVIDENCE_PENDING | no challenger yet | build AL-5c with both equations stated, proof ROS counts once, historical calibration / distribution / uncertainty / format sensitivity |
| `ODR-DRAFT-ORDER-MEDIAN` | Power & playoff odds / draft | Does the `dynasty_main` rookie-draft order rank on the official Sleeper record including league-median results, or on head-to-head only? | **Not covered by the directive.** The 2026-10-04 rule says "final regular-season record" without saying, and the league's history does not settle it | `docs/picks/DRAFT_ORDER_RULE.md` "Median games"; #1712 | the final 2026 standings fix the 2027 draft order; forecasts are labelled `head_to_head_with_half_win_ties` meanwhile | HUMAN_ACTION_REQUIRED | #1712 (standings / seeding count median) | owner answers one yes/no before the 2026 regular season ends. No recommendation is offered: it is a league-rule fact, and the evidence matches neither reading |
| `ODR-UMOTY` | Awards | Promote unified Manager of the Year to official, and from which season? (#1513) | **Remain experimental**: validation-only candidate; official method and display unchanged; weights unchanged; UNAVAILABLE components never redistributed; no definitive score from incomplete evidence; **earliest eligible official season 2027** — D12 | PR #1513 (open, PARTIAL / NOT PROMOTED); trade component's decision-time half incomplete | publishing an incomplete winner could be overturned | DECIDED | PR #1513 open, not merged | apply the D12 interim rules on the candidate; promotion no earlier than 2027 through normal gates |

### Draft capital and picks

| ID | family | question | decision | evidence | risk / impact | status | PR / tests | remaining action |
|---|---|---|---|---|---|---|---|---|
| `ODR-DRAFTCAP-INVENTORY` | Draft capital | Extend `dynasty_main` draft-capital inventory to 2028/2029? (ledger `DRAFTCAP-2029-INVENTORY`, `R-DRAFTCAP-INVENTORY`, `Draft Capital 2028/2029 inventory`) | **Already approved** (owner 2026-10-17: extend; 2026-10-18 scope: `dynasty_main` only); obsolete request removed — D13 | `docs/OWNER_REQUESTED_TODO.md` "P1: all Sleeper draft years" | — | DEPLOYED | #1785 via release train 6 #1794 (deploy succeeded); Batch E #1802 in train 8 (not merged) | observe `/league?tab=draft-capital` for `dynasty_main` (All Years / 2027 / 2028 / 2029) after train 8 deploys |
| `ODR-DRAFTCAP-1200` | Draft capital | One $1,200 pool per class, or one shared across classes? | **$1,200 per class, every year, `dynasty_main` only**, whole dollars, last-known-good — owner 2026-10-18; D13 says not to re-ask | draft-valuation workstream; `budgetPolicy` `per_class_pool` | — | DEPLOYED | #1786 (merged 2026-10-18) and #1785 (train 6), both in production build | Batch E/F (train 8) and Batch G (#1812) verification |
| `ODR-DYNASTY-NEW-ORDER` | Draft capital | What is `dynasty_new`'s rookie-draft order (lottery? playoff finish?) (ledger `DRAFT-ORDER-DYNASTY-NEW`, `dynasty_new draft-order rule`) | **Out of current scope** — D13. No lottery or playoff rule is presumed; fail-closed behaviour preserved; deferred until the owner requests it | `config/leagues/draft_order_rules.json` (`dynasty_main` only) | — | DECIDED | — | none until the owner raises it |

### Premium UI

| ID | family | question | decision | evidence | risk / impact | status | PR / tests | remaining action |
|---|---|---|---|---|---|---|---|---|
| `ODR-CHART-PALETTE` | Premium UI | #1428: which categorical chart treatment on cream PSI surfaces? (ledger `#1428`, `R-1428`) | **High-contrast palette** `--chart-1`…`--chart-6` = `#986400` `#2264af` `#ac386a` `#6752b6` `#087650` `#aa3c17` (≈ 3.82–4.71:1 on `#e9dfca`) through the semantic chart-token owner — D14 | issue #1428; directive contrast figures | colour-only series fail CVD users unless differentiated | DECIDED | not built; `/design` chart previews still gated | Lane 6 unit: every chart background and mark, light and dark, CVD (labels / patterns / markers), order kept, movement colours untouched, desktop + mobile evidence, axe; then ungate previews |
| `ODR-TOKEN-DIRECTION` | Premium UI | `OD-05`: live terminal token drift vs the north star | **Resolved 2026-08-18** (PSI Direction A); the Scope Manifest §6 still listed it — closed in place | `docs/DESIGN-SYSTEM.md` | — | DEPLOYED | historical | — |

### Platform, spending and data policies

| ID | family | question | decision | evidence | risk / impact | status | PR / tests | remaining action |
|---|---|---|---|---|---|---|---|---|
| `ODR-SLEEPER-WRITE` | Decision products | `OD-02` / `C7-GATE-01`: build an authenticated Sleeper write gateway now? | **Not now** — D15. Read-only toward real roster and league transactions; read-only recommendations continue | — | — | DECIDED | — | a separate future owner directive is required |
| `ODR-PAID-INFERENCE` | Decision products | `C7-AI-01`: Ask Brisket paid inference posture | **Off** until a documented cost, privacy and value case exists — D16 | — | — | DECIDED | — | deterministic features may continue |
| `ODR-PAID-DATA` | Data | Subscribe to SportsDataIO / Fantasy Nerds / licensed odds? (ledger `PROJ-KEYED-ADAPTERS`) | **No automatic subscriptions**; honest unavailable states — D17 | — | — | DECIDED | adapters stay credential-gated, default off | — |
| `ODR-ANALYST-COST` | Data | `OD-03`: Analyst Intelligence cost posture (paid transcription / API spend) | **No paid inference, transcription or data spend** — D16 / D17 | — | — | DECIDED | — | free, legitimate sources only |
| `ODR-BALLDONTLIE-KEY` | Game Day | BALLDONTLIE free key for the live-state shadow (ledger `BALLDONTLIE-TRIAL`) | **Free path only if terms and reliability support it and an authorized key exists**; otherwise honest unavailable — D17 | ESPN 403 on live state | Game Day live evidence missing on each live Sunday | HUMAN_ACTION_REQUIRED | adapter merged, shadow flag off | optional: owner creates the free account and installs `BALLDONTLIE_API_KEY` on the box |
| `ODR-CFBD-KEY` | Projections | CollegeFootballData free key (ledger `C5-FIT-01/college`) | **Same free-path rule** — D17 | — | — | HUMAN_ACTION_REQUIRED | — | optional: owner installs a free key if the terms allow |
| `ODR-DRAFTSHARKS` | Rankings & sources | `OD-04`: Draft Sharks — re-mint, accept degradation, or retire? | **Resolved 2026-08-25: ACCEPT**; Scope Manifest §6 still listed it — closed in place | `docs/VERSION_1_COMPLETION_CONTRACT.md` V1-89 | — | DEPLOYED | historical | — |

### Security and operations

| ID | family | question | decision | evidence | risk / impact | status | PR / tests | remaining action |
|---|---|---|---|---|---|---|---|---|
| `ODR-MAIN-RULESET` | Security | Apply the `main` ruleset; admin bypass `pull_request` or `always`? (ledger `C10-CLOSE-06/branch-protection`, `R-STAB-RULESET`) | **Protected PR merging without routine admin bypass** (admin `pull_request`) — D18 | `docs/audit/STABILIZATION_2026-10-07.md` §3; payload #1677 | unprotected `main` ships straight to production | HUMAN_ACTION_REQUIRED | payload `deploy/github/main-protection-ruleset.json`; `tests/deploy/test_main_protection_ruleset.py` | admin applies per `docs/ops/ADMIN_ONLY_ACTIONS_RUNBOOK.md` §1 |
| `ODR-DEPLOY-KEYS` | Security | Retire unused write deploy keys 145025388 / 148579683? | **Inventory first; retire only after confirming the deploy path** — D18 | box pushers authenticate via `~/.ssh/github_push` (measured 2026-08-15) | removing the box's key freezes data pushes and deploy dispatch | HUMAN_ACTION_REQUIRED | — | runbook §2 fingerprint comparison, then retire |
| `ODR-PASSWORD-ROTATION` | Security | Rotate `JASON_LOGIN_PASSWORD`? (ledger `C10-CLOSE-06/credential-rotation`) | **Operator rotates it**; the value is never shown, logged or committed — D18 | a literal once sat in public history | credential exposure | HUMAN_ACTION_REQUIRED | `server.py` requires the env value | runbook §3; record only the date |
| `ODR-OCR` | Trade | OCR engine and production install (ledger `C3-IMPORT-IMAGE`) | **Free local Tesseract**; no paid vision or new credential; install is an admin task; never auto-import a guessed identity — D19 | deployed; status endpoint `tesseract_not_installed` | screenshot import unavailable until installed | HUMAN_ACTION_REQUIRED | #1751 via #1753 (`47a9f561b`), deployed | runbook §4 install + recognition checks |
| `ODR-AUTH-VERIFY` | Security / delivery | Re-enable the paused authenticated production verification workflows? | **Restore legitimate authenticated verification** (Part 9 item 9); preconditions met (train 4 #1759 merged and deployed 2026-10-16) | `docs/ops/AUTH_VERIFICATION_REENABLE.md` | 35 completion-ledger rows name an authenticated production check as their next action | HUMAN_ACTION_REQUIRED | #1724 / #1725 merged | owner enables per runbook §6 |

### Rookie auction

| ID | family | question | decision | evidence | risk / impact | status | PR / tests | remaining action |
|---|---|---|---|---|---|---|---|---|
| `ODR-AUC-OPEN-OFFERS` | Rookie auction | Do open trade offers reserve auction money? (ledger `AUC-OPEN-OFFERS`) | **No**: an unaccepted offer reserves nothing; money moves only after a verified accepted transaction; leading bids keep reserving — D20 | `src/auction/engine.py` rule | — | DEPLOYED | engine rule; `tests/auction/test_trades.py` | observe in a mock room |
| `ODR-AUC-RULES` | Rookie auction | Confirm the `PROPOSED_RULE_KEYS` rules (ledger `AUC-RULES-CONFIRM`) | **Proposed timing / nomination rules for mocks only**; official confirmation at official launch; not demanded now — D20 | `docs/auction/LAUNCH_CHECKLIST.md` B | — | HUMAN_ACTION_REQUIRED | — | at official launch only |
| `ODR-AUC-DR` | Rookie auction | Accept the on-host DR window, or provide an off-host copy? (ledger `AUC-DR-WINDOW`) | **Mocks: hourly on-host backup + restore verification. Official: recommend a validated encrypted off-host copy, or a documented risk acceptance, before launch** — D20 | auction backup timer is on-host | disk loss loses an official draft | HUMAN_ACTION_REQUIRED | `scripts/auction_backup_verify.py` | runbook §5, before official launch |
| `ODR-AUC-OFFICIAL` | Rookie auction | Approve the official 2027 pool and launch (ledger `AUC-OFFICIAL-LAUNCH`, `AUC-2027-POOL`) | **Gated on readiness and explicit owner launch**; no official room, invites, budgets or roster writes before; provisional PF standings are never the final order; no synthetic rookies — D20 | — | — | HUMAN_ACTION_REQUIRED | — | after the 2027 NFL draft, checklist A–C complete |
| `ODR-AUC-REHEARSAL` | Rookie auction | Human device rehearsals (ledger `AUC-REHEARSAL-HUMAN`) | not covered by the directive; existing owner gate (real devices and league-mates) | `docs/auction/REHEARSAL_GUIDE.md` | — | HUMAN_ACTION_REQUIRED | — | before the official auction, after VAPID keys |
| `ODR-VAPID` | Notifications | Production VAPID keys (ledger `C7-CE-01/CE-29`, `AUC-002`) | not covered by the directive; a credential only the owner installs | `.env.example` one-liner | push notifications off; inbox works | HUMAN_ACTION_REQUIRED | — | owner generates the key pair into the box `.env`, then restarts |

### Scope candidates (not authorized, not blocking)

| ID | family | question | decision | evidence | risk / impact | status | PR / tests | remaining action |
|---|---|---|---|---|---|---|---|---|
| `ODR-SIXTH-SLOT` | Decision products | Sixth NEW CANDIDATE: R40 stays EXTEND under `C7-ALERT-01`, or admit R44 (which also decides `OD-06`)? | not covered by the directive | `docs/OWNER_REQUESTED_TODO.md` "Sixth-slot discrepancy" | none; candidates only | HUMAN_ACTION_REQUIRED | — | recommended: option 1 (R40 stays EXTEND; R44 not admitted), which prejudges nothing. Owner yes/no whenever convenient |
| `ODR-OD-06` | Decision products | `OD-06`: CE-28 user feedback / polling — approve as scope, or drop? | not covered by the directive | `docs/CE_REGISTRY.md` | none | HUMAN_ACTION_REQUIRED | — | owner approve / drop whenever convenient |
| `ODR-OD-07` | Decision products | `OD-07`: "link any Sleeper account" onboarding — approve as scope, or drop? | not covered by the directive (Manager Intelligence username search is a different, authorized feature) | Scope Manifest §6 | none | HUMAN_ACTION_REQUIRED | — | owner approve / drop whenever convenient |

### DFS — OWNER_PAUSED (owner directive 2026-10-18; PR #1810)

| ID | family | question | decision | evidence | risk / impact | status | PR / tests | remaining action |
|---|---|---|---|---|---|---|---|---|
| `ODR-DFS-PAUSE` | DFS | Continue DFS implementation? | **Shelved** until the owner explicitly resumes it; deployed DFS, docs and tests preserved; no new models, optimizers, feeds, research, slate support or releases | directive Part 1; PR #1810 | — | OWNER_PAUSED | #1810 (docs only, open); ledger: 117 DFS rows `OWNER_PAUSED` (prior disposition kept) | resume only on an explicit owner directive |
| `ODR-DFS-ESPN-NBA-NHL` | DFS | May ESPN's public NBA/NHL scoreboards supply DFS slate start times? | paused, not decided | `config/dfs/auto_sources.json` (`pending_owner_decision`, fails closed) | — | OWNER_PAUSED | ADR-DFS-025 | — |
| `ODR-DFS-RULESETS` | DFS | Confirm DK/FD rule sets or supply official templates (`DFS-§5-02`, `DFS-ADD-29`, `DFS-§19-02`, `DFS-MOD-14`) | paused | — | — | OWNER_PAUSED | — | — |
| `ODR-DFS-SLATE-FEED` | DFS | SportsDataIO DFS slate plan (`DFS-ADD-02`, `DFS-AUTO-18`) | paused; paid services are not subscribed in any case (D17) | — | — | OWNER_PAUSED | — | — |
| `ODR-DFS-RESULTS` | DFS | Import contest-standings exports or license a results source (`DFS-MOD-09`) | paused | — | — | OWNER_PAUSED | — | — |
| `ODR-DFS-ODDS` | DFS | Licensed odds / props aggregator (`DFS-§14-01`) | paused; no paid service (D17) | — | — | OWNER_PAUSED | — | — |

### League Tycoon — OWNER_PAUSED (owner directive 2026-10-18)

| ID | family | question | decision | evidence | risk / impact | status | PR / tests | remaining action |
|---|---|---|---|---|---|---|---|---|
| `ODR-LT-PAUSE` | League Tycoon | Implement the League Tycoon integration, contract-dynasty features or migration? | **Shelved**; research and Ideas backlog retained; Sleeper stays the platform | directive Part 1; ideas PR #1755 (open) | — | OWNER_PAUSED | — | reopen only on a fresh explicit owner directive |
| `ODR-LT-OD1` | League Tycoon | OD-1: which league moves, from which season? | paused | `docs/research/league-tycoon-migration-2026-10-17/README.md` §11 | — | OWNER_PAUSED | — | — |
| `ODR-LT-OD2` | League Tycoon | OD-2: standard or contract dynasty? | paused | same | — | OWNER_PAUSED | — | — |
| `ODR-LT-OD3` | League Tycoon | OD-3: does League Tycoon support IDP / best ball / 58-man rosters / TE premium? | paused | same | — | OWNER_PAUSED | — | — |
| `ODR-LT-OD4` | League Tycoon | OD-4: access posture | **Decided 2026-10-17**: League Tycoon's written permission received (kept by the owner) | README §1.5 | — | DECIDED | — | retained for any future reopening |
| `ODR-LT-OD5` | League Tycoon | OD-5: lift R60 contract-league modelling from DEFER? | paused | same | — | OWNER_PAUSED | — | — |
| `ODR-LT-OD6` | League Tycoon | OD-6: keep Sleeper as the record for seasons up to a cutover? | paused (was RECOMMENDED) | same | — | OWNER_PAUSED | — | — |
| `ODR-LT-OD7` | League Tycoon | OD-7: rookie-draft format and draft-order rule on League Tycoon | paused | same | — | OWNER_PAUSED | — | — |
| `ODR-LT-CAPTURE` | League Tycoon | One signed-in evidence capture by the owner | paused; not to be requested | `OWNER_EVIDENCE_CAPTURE.md` | — | OWNER_PAUSED | — | — |

## Counts

<!-- counts: generated from the tables above when this file was written; recount if rows change -->
| status | rows |
|---|---:|
| `DECIDED` | 13 |
| `IMPLEMENTED` | 0 |
| `MERGED` | 0 |
| `DEPLOYED` | 16 |
| `PRODUCTION_VERIFIED` | 0 |
| `EVIDENCE_PENDING` | 5 |
| `HUMAN_ACTION_REQUIRED` | 17 |
| `OWNER_PAUSED` | 14 |
| **total** | **65** |

## Where each stale record was closed (in place)

| decision | home record(s) edited 2026-10-18 |
|---|---|
| Geometric VA active (D8) | `docs/EXECUTION_PLAN.md` (sitewide VA entry); `docs/OWNER_REQUESTED_TODO.md` (sitewide VA rows); `docs/trade/TRADE_CALCULATOR_COMPLETION_WORKSTREAM.md` (package-model rule); `docs/trade/TRADE_CALCULATOR_FEATURE_MATRIX.md` §1.3 |
| 250-point Best Offers rule; five TC-C decisions; RETOOL → BALANCED | already recorded DECIDED in their home records (workstream TC-C, audit §7.10, intake 2026-10-17). Stale "open" leftovers closed in `docs/trade/TRADE_CALCULATOR_FEATURE_MATRIX.md` (`TCM-E06`), `docs/trade/TRADE_DECISION_ENGINE_AUDIT.md` (§2 table, §7 table) and `docs/trade/SECOND_OPINIONS_TODO.md` |
| TCM-K06 (D9) | `docs/trade/SECOND_OPINIONS_TODO.md`; workstream TC-B K06 row + remaining list; feature matrix `TCM-K06` |
| `dynasty_main` 2027–2029 inventory, $1,200 per class (D13) | already superseded in `docs/OWNER_REQUESTED_TODO.md`; completion ledger rows re-dispositioned (`family_Z_coordinator.json` overrides) |
| `dynasty_new` draft order out of scope (D13) | `docs/picks/DRAFT_ORDER_RULE.md`; ledger rows → `INTENTIONALLY_FUTURE` |
| DFS → OWNER_PAUSED | `docs/dfs/DECISIONS.md` (banner); `docs/game-day/SOURCE_ACCESS_EVIDENCE_2026-09-25.md`; ledger (117 rows); `docs/EXECUTION_PLAN.md` §0 |
| League Tycoon → OWNER_PAUSED | `docs/OWNER_REQUESTED_TODO.md` (League Tycoon rows); research `README.md` §11 and `OWNER_EVIDENCE_CAPTURE.md` |
| #1428 palette DECIDED (D14) | `docs/OWNER_REQUESTED_TODO.md` (#1428 row); `docs/EXECUTION_PLAN.md` ("Owner gates still open"); `docs/ui/UI_PARALLEL_LEDGER.md`; `docs/ui/PSI_DESIGN_REFERENCE_HANDOFF.md`; ledger rows → `AUTHORIZED_AND_READY` |
| IDP / source decisions (D1–D7) | `docs/sources/IDP_REHABILITATION_EVALUATION_2026-10-18.md` (banner, status table, blockers); `config/sources/rehabilitation.json` (recovery actions / triggers); `docs/OWNER_REQUESTED_TODO.md` (2026-10-17 package rows) |
| Playoff D2 (D11) | `docs/OWNER_REQUESTED_TODO.md` (2026-09-26 entry); `docs/EXECUTION_PLAN.md` (AL-5c row) |
| UMOTY (D12) | `docs/BRISKET_HONORS_ELIGIBILITY_SPEC.md` |
| Auction open offers / DR (D20) | `docs/auction/LAUNCH_CHECKLIST.md`; `docs/auction/ROOKIE_AUCTION_ROOM.md` §8 |
| `OD-02`…`OD-05` | `docs/C_SERIES_SCOPE_MANIFEST.md` §6 |
| #840 posture | `docs/OWNER_REQUESTED_TODO.md` (#840 row) |
