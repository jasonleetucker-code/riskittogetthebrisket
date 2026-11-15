# Owner directive 2026-11-01: production intelligence validation, model accuracy and decision quality

**Owner:** the site owner (Chase Upside / `riskittogetthebrisket`).
**Date:** 2026-11-01.
**Source:** the owner's chat with the coordinator session, 2026-11-01 ("CHASE UPSIDE — MASTER DEVELOPMENT DIRECTIVE"),
copied verbatim below. Intake rows: `docs/OWNER_REQUESTED_TODO.md` "Added 2026-11-01 — Master development directive"
(MD-1 … MD-16). Authorization: `docs/EXECUTION_PLAN.md`, same date. Register rows:
`docs/owner/OWNER_DECISION_REGISTER.md` "Master development directive (2026-11-01)". Recording the directive here
authorizes nothing beyond what the execution plan says.

## Owner decisions (binding; supersede earlier pending labels only for the exact subjects named)

1. **Roster Construction V1 — conditional private activation APPROVED.** `roster_construction` turns on for
   authenticated users once every condition holds:
   - recomputed 2026 finalized-week points match Sleeper within the documented tolerance
     (`config/roster_construction/v1.json` `hostScoreTolerance`, 0.011) on every fully comparable team-week;
   - contradictory or incomplete observations are withheld and labelled;
   - position attribution, ownership history, FLEX, superflex and two-TE rules are correct;
   - production requests pass authorization, privacy, performance and mobile acceptance;
   - exact-head CI and independent review pass;
   - the live authenticated workflow succeeds for a real team.
   No further owner approval is needed once these pass. After production verification, add Roster Construction to
   the authenticated My Team navigation with capability-gated visibility. Never public. If any condition fails, the
   flag stays OFF and the cause is fixed. Supersedes RCV-7 "OWNER-GATED".
2. **Historical (2025) roster configuration — do NOT infer it for production.** Sleeper's 2025 league object (17
   starters) contradicts its own 2025 matchups (22 seated). Show verified 2026 first. For 2025, either establish the
   configuration from authoritative evidence or show a clear unavailable state. A research-only reconstruction may be
   studied; it may not silently become the production rule.
3. **Deep-tail rookie voting (PR #2006) — RESTORE the original rule.** Keep the factual correction that FantasyPros
   IDP and DLF IDP include rookies (`excludes_rookies=False`); separate it from the policy that skips a rookie ranked
   beyond 80% of a source's pool. Before merging: rebase on current main, measure the latest player and pick value
   changes, confirm the scope matches the original rule, check dynasty valuations and source registry invariants,
   independent review and required green CI. Covers this restoration only. Supersedes NC-E "held".
4. **Offense/IDP ROS calibration — diagnosis ACCEPTED; NO promotion.** The 0–100 offense and IDP ROS indexes do not
   represent comparable expected fantasy points. CR (per-position-family rank→points curve) is the preferred
   challenger for further research. Authorized: the frozen Week 8 confirmation; prospective confirmation on further
   eligible weeks; a preregistered evaluation of ROS-horizon cross-position ordering; a separate `rosPointsPerWeek`
   shadow field behind a default-OFF flag if the research justifies it. Not authorized: replacing `rosValue`,
   changing canonical dynasty prices or live team-strength formulas, promoting CR. **The original G3 gate stays
   recorded as FAILED**; a revised future gate cannot retroactively change it.
5. **IDP source authority — NO voting promotion.** DLF IDP voting stays held until outlier integrity is independently
   validated; `source_freshness_schedule_v2` stays OFF; the voting IDP Show combined board is not replaced by its
   IDP-only board yet. Authorized: read-only comparative evaluation of those options on identical inputs
   (retained/rejected votes, indirect pick changes, provenance, board impact). Freshness is never extended to
   produce a preferred result.
6. **Trade Advisor — public launch stays OFF.** Provisional single response floor **300 ms**, subject to security
   verification and implementation tests. Keep admission (public 2, private 2), the 5 s public / 30 s private
   deadlines, every rate-limit bucket and request-size limit; no automatic increases. Launch stays blocked until
   source permissions, security headers, direct-port exposure, privacy verification and production testing are
   satisfactory. No manufactured permission attestations; authenticated-display permission does not extend to public
   use.
7. **Waiver Advisor and Weekly IDP Streaming — keep the approved authenticated deployment.** Default dynasty-loss
   budget **0**; users may explicitly choose more within the interface, with disclosure of what is sacrificed. Use
   the canonical marginal release-cost method; missing dynasty value is never zero. No transaction is a valid optimal
   result. Kickers are evaluated for projected lineup contribution without an invented market value. Defensive
   touchdowns and every other defensive category come from the selected league's exact scoring card. Edge-rusher and
   developmental protection must be evidence-based, not a position-wide exemption. The FAAB list-bid season-phase
   fix through the canonical FAAB owner is authorized. (Coordinator note: that fix already shipped as IST-7, PR
   #2018 `29216a529`; this directive's work is to verify it.)
8. **User-facing fixes — finish PR #2031** (clearer site-owner sign-in on iPhone Home Screen) **and PR #2032**
   (authenticated Weekly IDP Streaming discoverability), each through its ordinary testing, security and
   independent-review gates.
9. **Probability disclosure wording — APPROVED** for unvalidated playoff or championship estimates, applied only
   where accurate, with no change to the probability mathematics:
   **"Experimental projection — not yet calibrated against this league's historical outcomes."**
10. **Protected programs — unchanged.** No League Tycoon implementation or migration; no unapproved Simulation V3
    promotion; no unapproved canonical dynasty value change; no automatic Sleeper transactions; no paid API
    purchase or subscription; no arbitrary TE++ change; no change to the `dynasty_new` taxi cap; no merge of held
    research PRs merely because they are open. Routine engineering decisions are autonomous; evidence-gated
    methodology promotions still need their documented conditions.

## What it authorizes

- Workstreams A–F of the directive (Parts 4–5), routed in `docs/EXECUTION_PLAN.md` 2026-11-01.
- Activating `roster_construction` (private) and its capability-gated nav once decision 1's conditions are proven.
- Merging the #2006 restoration under decision 3's conditions; merging #2031, #2032 and the #2035 research runner
  under standing merge authorization.
- Setting the advisor `responseFloorMs` to 300 (launch flag stays OFF).
- Research and shadow work for ROS calibration (decision 4), source-integrity comparisons (decision 5) and streaming
  accuracy (decision 7, directive Workstream C).

## What it does NOT authorize

- Promoting CR or any ROS calibration; changing `rosValue`, canonical dynasty values, team strength, TE++, source
  weights, voting membership or freshness rules; releasing the DLF IDP hold.
- Turning on `source_freshness_schedule_v2`, `brisket_trade_advisor`, or any held flag.
- Public exposure of Roster Construction, the Waiver Advisor or streaming.
- Inferring the 2025 lineup configuration for production.
- Writing any source-permission attestation; any Sleeper write; paid data.
- Merging #1884, #1938, #1873, #1852 or any other held research PR.
- League Tycoon, Simulation V3 promotion, the `dynasty_new` taxi cap.

## Owner-gated (remain)

- Public Trade Advisor launch and per-source public-use permission (OD-3).
- Production box operator actions outside the deploy pipeline (nginx security headers via
  `deploy/apply_hardening.sh`; binding the app away from `0.0.0.0`) — escalated with a recommendation, not done
  unilaterally.
- Any future CR / `rosPointsPerWeek` promotion, DLF IDP release, IDP Show board swap or freshness-rule change.

## The directive (verbatim)

# CHASE UPSIDE — MASTER DEVELOPMENT DIRECTIVE
## Production Intelligence Validation, Model Accuracy, and Decision-Quality Improvement

**Repository:** `jasonleetucker-code/riskittogetthebrisket`

**Date:** November 1, 2026

**Execution mode:** Maximum Safe Parallel Build Mode

**Primary mission:** Transform the recently implemented Chase Upside functionality into a fully integrated, production-verified, mathematically reliable dynasty football decision platform.

This is an **execution directive**, not a request to produce another proposal or list of recommendations.

Audit the current repository, preserve existing work, complete authorized improvements, independently validate the results, integrate qualified PRs, deploy eligible functionality, and report what is actually functioning.

Do not stop after research if implementation is already authorized.

---

# PART 1 — BINDING OWNER DECISIONS

The owner has delegated the outstanding decisions listed below. Record them in the repository's existing owner-decision and execution-planning system before changing behavior.

These decisions supersede earlier pending-decision labels only for the precise subjects addressed here. All other protections remain in effect.

### Decision 1 — Roster Construction V1

**APPROVED FOR CONDITIONAL PRIVATE ACTIVATION.**

Activate `roster_construction` for authenticated users once:

- Recomputed 2026 finalized-week fantasy points match Sleeper within the existing documented scoring tolerance for every fully comparable team-week.
- All contradictory or incomplete observations are withheld and correctly labeled.
- Position attribution, ownership history, FLEX rules, superflex rules, and two-TE roster requirements are correct.
- Production requests pass authorization, privacy, performance, and mobile acceptance checks.
- Exact-head CI and independent review pass.
- The live authenticated workflow succeeds for a real team.

If these requirements fail, retain the OFF flag and fix the underlying problems.

Once requirements pass, no additional owner approval is necessary for private activation.

After successful production verification, add Roster Construction to the authenticated My Team navigation using capability-gated visibility.

Do not expose it publicly.

### Decision 2 — Historical roster configuration

**DO NOT INFER THE 2025 STARTING-LINEUP RULES FOR PRODUCTION.**

The existing research indicates a discrepancy between the historical host lineup and the current Sleeper settings.

Display verified 2026 results first.

For 2025, either establish the historical configuration through authoritative evidence or show a clear unavailable state.

A research-only reconstruction may be studied, but it cannot silently become the production rule.

### Decision 3 — Rookie deep-tail filtering, PR #2006

**APPROVED: RESTORE THE ORIGINAL DEEP-TAIL ROOKIE VOTING RULE.**

Preserve the factual correction that FantasyPros IDP and DLF IDP include rookies.

Separate that factual property from the policy determining whether deep-tail rookie rankings count as meaningful votes.

The original 80% deep-tail threshold is approved for restoration.

Before merging:

1. Rebase against current main.
2. Measure the latest player and pick value changes.
3. Confirm the scope matches the original rule.
4. Check dynasty valuations and source registry invariants.
5. Obtain independent review and required green CI.

This approval covers the specified restoration, not unrelated valuation changes.

### Decision 4 — Offense/IDP ROS calibration

**ACCEPT THE DIAGNOSIS. DO NOT PROMOTE A NEW MODEL YET.**

The current 0–100 offensive and defensive rest-of-season indexes do not reliably represent comparable expected fantasy points.

The per-position family rank-curve model, CR, is the preferred challenger for further research.

Authorize:

- Frozen Week 8 confirmation.
- Prospective confirmation on additional eligible weeks.
- A preregistered evaluation of ROS-horizon cross-position ordering.
- Development of a separate `rosPointsPerWeek` shadow field behind a default-OFF flag, if justified by the research.

Do not replace `rosValue`, change canonical dynasty prices, alter live team-strength formulas, or promote CR until the new evidence supports it.

The original failed G3 gate must remain recorded as failed. A revised future research gate cannot retroactively change the result.

### Decision 5 — IDP source authority

**NO CURRENT SOURCE-VOTING PROMOTION.**

Keep DLF IDP voting held until outlier integrity is independently validated.

Keep `source_freshness_schedule_v2` OFF.

Do not replace the voting IDP Show combined board with its IDP-only board yet.

Authorize read-only comparative evaluation of these source options on identical inputs, including retained/rejected votes, indirect pick changes, provenance, and board impacts.

Do not extend freshness merely to produce preferred results.

### Decision 6 — Trade Advisor

**PUBLIC LAUNCH REMAINS OFF.**

Approve a provisional single response floor of **300 milliseconds**, subject to normal security verification and implementation tests.

Retain existing admission and rate-limit settings:

- Public concurrency: 2.
- Private concurrency: 2.
- Existing five-second public and 30-second private deadlines.
- Existing rate-limit buckets and request-size limits.

No automatic increases or reduced protections.

The public launch remains blocked until source permissions, security headers, direct-port exposure, privacy verification, and production testing are satisfactory.

Do not manufacture permission attestations or assume existing authenticated-display permission extends to public use.

### Decision 7 — Waiver Advisor and Weekly IDP Streaming

Preserve the previously approved authenticated deployment.

The default permitted dynasty-loss budget is **zero**. Users may explicitly choose a higher budget within the existing interface, with clear disclosure of what is being sacrificed.

Use the existing canonical marginal release-cost methodology; do not introduce a competing value calculation or treat missing dynasty values as zero.

No transaction is a valid optimal recommendation.

Kickers must be evaluated for projected lineup contributions without inventing a market value when no supported dynasty valuation exists.

Defensive touchdowns and all other defensive scoring categories must derive from the exact selected league scoring card.

Edge-rusher and developmental-player protection must be evidence-based, not an arbitrary position-wide exemption.

Authorize correction of the known FAAB list-bid season-phase defect through the canonical FAAB owner.

### Decision 8 — User-facing improvements

Approve finishing:

- PR #2031 — clearer site-owner sign-in on iPhone Home Screen.
- PR #2032 — authenticated Weekly IDP Streaming discoverability.

Both require their ordinary testing, security and independent-review gates.

### Decision 9 — Probability disclosures

Approve the following public wording when displaying unvalidated playoff or championship estimates:

**"Experimental projection — not yet calibrated against this league's historical outcomes."**

Apply only where accurate. Do not change the underlying probability mathematics.

### Decision 10 — Protected programs

Keep these decisions unchanged:

- No League Tycoon implementation or migration.
- No unapproved Simulation V3 promotion.
- No unapproved canonical dynasty value changes.
- No automatic Sleeper transactions.
- No paid API purchases or subscriptions.
- No arbitrary TE++ methodology change.
- No change to the `dynasty_new` taxi cap.
- No merging of otherwise held research PRs merely because they are open.

Routine engineering decisions may be made autonomously. Evidence-gated methodology promotions must still satisfy their documented conditions.

---

# PART 2 — RECONSTRUCT THE ACTUAL STATE

Before starting implementation, inspect:

- Current `main` HEAD and production served SHA.
- Active feature flags and deployment environment.
- Open PRs and recent merges.
- Required GitHub Actions checks.
- Existing work claims and branch ownership.
- Canonical model owners and shared calculations.
- Production health, data freshness, and source status.

At minimum inspect:

| PR | Purpose |
|---|---|
| #2031 | iPhone site-owner sign-in |
| #2032 | Weekly IDP Streaming navigation |
| #2035 | Frozen Week 8 ROS confirmation |
| #2006 | Deep-tail rookie voting |
| #2010 | ROS calibration evidence |
| #2014 | IDP source authority |
| #2024–#2025 | Streaming composer and interface |
| #2028 | Roster Construction V1 |
| #2029–#2030 | Waiver activation and presentation |
| #1884 | Held outlier-integrity research |
| #1938 | Held IDP scoring correction |
| #1873 / #1852 | Held trade-market research |

Do not assume any status based on this prompt. Query GitHub and production.

Build a verified status register identifying:

1. Already merged and deployed.
2. Merged but not production-verified.
3. Open and ready for validation.
4. Draft or blocked.
5. Research-only.
6. Superseded.
7. Explicitly owner-held.

Do not reopen correctly completed releases without evidence of a regression.

---

# PART 3 — RECORD ALL DECISIONS IN THE MASTER ROADMAP

**THIS STEP IS MANDATORY.**

Discover and read the existing canonical planning hierarchy, including:

- `docs/OWNER_REQUESTED_TODO.md`
- `docs/EXECUTION_PLAN.md`
- `docs/MASTER_PRODUCT_PLAN.md`
- `docs/BRISKET_IDEAS.md`
- `docs/PLANNING_DOCUMENT_STATUS.md`
- Relevant existing specifications, research reports, ownership manifests, work claims, and completion records.

Create a dated, authoritative owner-decision record for this November 1 directive, using the repository's established conventions.

Reconcile its decisions into the correct existing master documents.

Every new feature idea, statistical-model proposal, bug, research outcome, recommendation, deferred improvement and implementation requirement must remain discoverable in the master roadmap.

Each entry should state:

- Its purpose and expected decision-quality benefit.
- Existing canonical owner.
- Exact requirements.
- Dependencies.
- Authorization status.
- Implementation PR or issue.
- Validation and release requirements.
- Current completion state.

Preserve existing detailed requirements from the three-month conversation audit.

Do not summarize a multi-page specification into a vague single-line TODO.

Avoid duplicating requirements already represented in the roadmap.

Passing planning integrity tests is mandatory.

---

# PART 4 — PARALLEL DEVELOPMENT WORKSTREAMS

Use independent agents, branches and worktrees where appropriate. Assign one owner per shared calculation or configuration file.

## Workstream A — Release and usability integration

Highest immediate integration priority.

### A1. PR #2031

Review and validate the site-owner sign-in fix.

Confirm that the normal site login, site-owner bridge and invitation-only league-member authentication remain separate.

Test authenticated and unauthenticated behavior on desktop and mobile, including installed-PWA behavior where access is available.

Preserve auction launch flags.

Merge and deploy only after the required checks pass.

### A2. PR #2032

Complete the Weekly IDP Streaming navigation fix.

The authenticated My Team menu must provide a clearly named route to the Waiver Advisor's streaming mode.

The link must fail closed when the capability is unavailable.

Verify desktop, mobile drawer, command palette and authenticated route behavior.

Do not expose protected league data to signed-out users.

### A3. Release verification

Verify both features on the actual deployed SHA.

A successful local build or merged PR is not sufficient.

If an authenticated production check requires credentials unavailable to the agent, report that specific verification gap without claiming success.

## Workstream B — Roster Construction V1 production readiness

This is the main product priority.

Use the real `dynasty_main` 2026 league snapshot and its scoring configuration.

### B1. League score parity

Reproduce every eligible finalized team-week through the canonical scoring and optimal-lineup owners.

For each team-week report:

- Sleeper awarded points.
- Recomputed legal-lineup points.
- Absolute discrepancy.
- Lineup configuration.
- Source coverage.
- Contradictions or exclusions.

Do not convert unknown players, missing statistics, or incomplete weeks into zero.

Investigate every meaningful discrepancy.

### B2. Position contribution integrity

Verify:

- One attribution per real starting player.
- FLEX and superflex players credited to their actual position.
- No double counting.
- The league's two TE slots.
- All nine IDP starting slots.
- Kicker eligibility.
- Ownership changes and transaction-effective dates.
- Optimal appearances versus hypothetical appearances.
- League-relative startability.
- Current dynasty values kept separate from historical production.

### B3. Private activation

Measure realistic full-league calculation and interactive response times against the existing performance standard.

Validate on desktop and WebKit mobile.

If all previously specified conditions pass, activate the private Roster Construction flag using the established safe release process.

Add authenticated, capability-gated navigation after the live behavior is verified.

If any required gate fails, keep the feature OFF and document the exact reason.

### B4. Product usefulness

Ensure the interface plainly answers:

- Which positions actually produced the most fantasy points?
- Which positions have the most dynasty market value?
- Where does the roster lack usable depth?
- Which players seldom contribute to an optimal lineup?
- Which positions are deceptively deep or weak?
- Which assets offer conditional injury insurance?
- What roster-construction problems merit REVIEW?
- When is NO ACTION preferable?

Do not introduce automatic trades or waiver moves into this module.

---

## Workstream C — Weekly IDP Streaming accuracy

The current historical findings show that the strict dynasty-safe optimizer gained approximately 0.4 points per decision week for the studied manager during the small 2026 sample, compared with approximately 19.9 points from that manager's actual streaming behavior.

This is an important gap, not proof that unlimited streaming is better.

### C1. Investigate why the optimizer trails

Decompose the differences into:

- Player pool eligibility.
- Predicted production.
- Injuries.
- Snap and role changes.
- Waiver availability.
- Dynasty value protection.
- Roster capacity.
- FAAB.
- Single-week versus multiweek optimization.
- Whether bench and replacement-level assumptions suppress worthwhile moves.
- Unpriced players.
- Projection data recorded after kickoff.
- Search limits and solver approximation.

Do not use hindsight to create unrealistic historical recommendations.

### C2. Source accuracy

Evaluate available authorized weekly IDP projection sources.

Use proper point-in-time timestamps and lineage.

Measure source performance separately for DL, LB and DB, including coverage, MAE, calibration, freshness and meaningful incremental accuracy.

Do not confuse IDP dynasty ranking sources with weekly scoring projections.

Build champion/challenger evidence before changing ensemble weights.

### C3. Better recommendations

Improve the existing optimizer and explanation system where evidence supports changes.

Continue respecting the default zero dynasty-loss budget and protected-player rules.

Expose alternatives showing how the recommendation changes when a user explicitly accepts additional dynasty loss.

Recommend zero, one, or multiple moves as appropriate.

Preserve legal roster limits, exact lineup assignment, FAAB constraints and transaction timing.

Search-budget exhaustion must never be reported as proven optimality.

### C4. Actual scenarios

Verify real-team examples of:

1. A beneficial one-for-one IDP streamer.
2. An available defender who is attractive but not worth the required drop.
3. A protected developmental defender.
4. Multiple legal simultaneous additions.
5. A rebuilding team where holding is preferable.
6. A contender weighing playoff benefit against dynasty loss.
7. Missing source projections.
8. An explicit NO TRANSACTION result.

Show the actual expected scoring benefit, uncertainty, dynasty release cost and relevant alternatives.

Do not submit transactions.

---

## Workstream D — ROS calibration and cross-position expected points

### D1. Finish PR #2035

Inspect the new frozen Week 8 confirmation runner and its tests.

Do not assume it is correct because the files exist.

Verify:

- Git blob identity and frozen parameter serialization.
- No retraining on Week 8.
- Correct eligibility and finalized-week checks.
- Host-scored point reconciliation.
- Relevant position-family handling.
- Accurate sample sizes.
- Research-only output isolation.
- No accidental promotion or live consumption.

Run targeted tests and independent review.

Repair defects and merge if qualified.

Then execute the confirmation with real eligible data.

### D2. Prospective validation

Compare the current champion with CR and the other preregistered challengers.

Report forecast accuracy, position bias, cross-position ordering, lineup behavior and team-ordering consequences.

If Week 9 or later is used, clearly establish whether the model was frozen before the evaluated games.

Do not call a retrospective refit a prospective test.

### D3. Next methodology

Design a separate expected-points-per-week quantity rather than forcing all positions into the same 0–100 index.

Maintain explicit distinction among:

- Dynasty market value.
- Rest-of-season normalized rank/value.
- Expected weekly fantasy points.
- Points above replacement.
- Roster-conditional marginal value.
- Playoff impact.

Do not apply arbitrary offensive or IDP multipliers.

Use the canonical replacement owner and avoid scarcity double counting.

Research can proceed behind a default-OFF flag, but any new production mathematical behavior requires its established acceptance and promotion gates.

---

## Workstream E — IDP source integrity and rookie voting

### E1. PR #2006

Implement the newly approved owner decision precisely.

Revalidate the changed voting logic and current-board impact.

Ensure no unrelated weight, voting-family, source freshness, source normalization or TE++ change.

Complete independent review and required CI.

Then integrate under the standing authorized release process.

### E2. Outlier integrity V2

Resume the evidence-based investigation from #1884 without blindly merging the existing experimental implementation.

Evaluate identical frozen input populations with:

- Incumbent source composition and filter.
- Proposed sources with incumbent filter.
- Proposed sources with the challenger filter.
- Challenger filter with held sources still excluded.

Account for rejected legitimate opinions, genuinely invalid observations, direct player valuation changes, indirect rookie-pick effects and source coverage.

The objective is not to make every source agree. It is to reject bad information without suppressing legitimate disagreement.

### E3. Freshness and IDP Show

Keep current source holds.

Investigate the newer IDP-only board, vendor clocks, stale combined-board behavior and legitimate publication freshness.

Produce a quantified owner-ready recommendation only after the necessary testing.

No automatic DLF, IDP Show or freshness-rule activation.

---

## Workstream F — Trade Advisor and production security

Continue preparation without launching the public Trade Advisor.

### F1. Response floor and limits

Use the approved provisional 300 ms policy.

Test the effect on timing disclosure, legitimate latency, cold requests, errors, concurrency and load.

Retain admission and limiter defaults unless a separately documented security requirement demands otherwise.

### F2. Production security

Resolve or explicitly escalate:

- Missing expected nginx security headers.
- Direct application-port exposure.
- Private-route authentication.
- Rate-limit behavior.
- Error response leakage.
- CORS behavior.
- Sensitive source information.
- Public versus private data boundaries.

Do not claim a secure launch from unit tests alone.

### F3. Source permissions

Inspect the existing source permission checklist and evidence.

Do not invent an owner attestation, license, or legal permission.

If public-use permission cannot be established, the public launch stays blocked.

Keep the canonical private and public methodology consistent; do not silently remove voting sources to make launch easier.

### F4. Probability transparency

Apply the approved experimental-projection wording wherever required.

Keep uncalibrated Simulation V3 estimates identified as experimental.

No numerical probability methodology changes.

---

# PART 5 — ENGINEERING REQUIREMENTS

These requirements apply to every workstream.

**Canonical ownership:** Reuse the existing lineup, scoring, replacement, valuation, trade, source, history and waiver owners. Never create a competing calculation engine.

**Historical integrity:** All historical decisions must use information available at their historical decision time. Missing data is not zero. Preserve as-of provenance.

**Mathematical validation:** Every consequential new numerical method needs a baseline, preregistered tests where appropriate, representative worked examples and regression evidence.

**Privacy:** Protect league rosters, user identities, private board data, sessions, tokens and paid information.

**Performance:** Prefer targeted tests while building. Run the required broader tests at promotion boundaries. Measure representative full-roster workloads.

**Agent coordination:** Use nonoverlapping file ownership. Reconcile shared changes through an integration owner. Do not let agents overwrite each other's planning records.

**GitHub workflow:** Preserve independent reviews, exact-head required CI, branch protection and established squash-merge rules. No force pushes, bypassed protections or fabricated passing results.

**Release discipline:** Distinguish code written, tests passed, merged, deployed, activated and production-verified. None of those statuses is interchangeable.

**Financial and external actions:** No purchases, unauthorized paid access, automatic Sleeper writes or new public source permission attestations.

---

# PART 6 — REQUIRED FINAL HANDOFF

Deliver a consolidated, evidence-backed report with:

### A. Release inventory
Every relevant PR, current SHA, review status, tests, merge status and deployment status.

### B. Production functionality
Which pages and APIs actually work, their authentication and feature-flag status, and which real-user flows were verified.

### C. Roster Construction
Actual 2026 score-parity measurements, excluded weeks, position-rank examples, performance and activation decision.

### D. Weekly IDP Streaming
Representative add/drop examples, predicted advantages, dynasty protections, historical benchmark comparisons and improvement opportunities.

### E. Mathematical evidence
ROS calibration results, source-integrity findings, uncertainty, sample sizes and all failed acceptance gates.

### F. Valuation preservation
Evidence that unauthorized dynasty values, TE++ behavior, package methodology, source weights and held calculations did not change. Explicitly isolate the authorized #2006 effects.

### G. Security and reliability
Authentication checks, privacy tests, production network findings, mobile E2E, CI and deployment results.

### H. Master roadmap traceability
Which exact planning documents were updated, what items changed, and where new ideas or unresolved tasks were recorded.

### I. Remaining owner decisions
Only genuinely unresolved decisions that cannot be made under the current directive. Include a concrete recommendation and supporting evidence for each.

### J. Next highest-value development cycle
Rank the next opportunities by expected improvement in fantasy decision quality, not by the number of new features or visual polish.

---

# FINAL EXECUTION INSTRUCTION

Begin coordinated execution now.

First reconstruct actual repository and production status, then record these decisions in the canonical roadmap, assign independent workstreams and implement the highest-priority authorized work.

**Prioritize finishing and verifying existing functionality over creating new features.**

Do not ask the owner for another routine engineering decision or separate prompt after each phase.

Proceed autonomously within the approvals above. Where evidence is insufficient, retain the existing safe methodology, report the blocker, and keep independent authorized work moving.

Do not merge unvalidated code or activate a model merely to make the release appear complete.

The ultimate objective is a Chase Upside platform that can accurately and explainably answer:

**"Given my league scoring, roster, dynasty assets, available players, expected weekly production, replacement options and championship outlook, what should I actually do to improve my team — and when is doing nothing the better decision?"**

Build toward that answer, validate it against real evidence, and deliver working, production-verified improvements.
