# MASTER OWNER DECISION CLOSEOUT & EVIDENCE-UNBLOCK DIRECTIVE
## Chase Upside / Risk It to Get the Brisket — October 18, 2026

> Verbatim owner directive, received in the coordination session 2026-10-18 ~19:55 UTC.
> Binding owner decisions D1–D20 below. Capture is not implementation authorization beyond
> what the directive itself authorizes; every named evidence gate still applies.

### YOUR MISSION

You are continuing the existing Chase Upside site-completion campaign in `jasonleetucker-code/riskittogetthebrisket`.

I am delegating the remaining **product, methodology, design, prioritization, and operational-policy decisions explicitly resolved in this prompt**. Treat these as binding owner decisions, subject to the evidence, validation, privacy, and production safeguards below.

**Do not repeatedly return to me with questions that this directive answers.**

The objective is to finish a reliable, accurate, polished, production-ready dynasty football application—not to maximize feature counts, increase data-source votes, or accelerate merges at the expense of correctness.

Use this priority order whenever requirements compete:

1. Correct results and complete, independent evidence.
2. Prevention of misleading recommendations or fabricated certainty.
3. Production reliability, security, privacy, and recoverability.
4. A coherent user experience across desktop and mobile.
5. Completion of already-authorized functionality.
6. Performance and operating cost.
7. Additional experimental capabilities.

Do not reinterpret these priorities as permission to override existing binding owner decisions.

---

# PART 1 — MANDATORY SCOPE

### Continue all non-DFS Calculator development

Continue the already-authorized completion campaign, including:

- Trade Calculator and Trade Finder.
- Manager Intelligence.
- Rankings, player valuation, IDP source rehabilitation.
- Draft Capital and Draft Valuation.
- Game Day and Power Rankings.
- Schedule Intelligence.
- Adaptive Learning and Model Lab.
- Premium UI and accessibility.
- Rookie Auction preparation and mock functionality.
- Security, reliability, production verification, and sitewide completion.

### DFS IS SHELVED — BINDING

All additional DFS implementation is **PAUSED until I explicitly authorize resumption**.

No new DFS models, optimizers, features, feed integrations, data research, slate support, projection work, or DFS-specific releases.

Preserve the existing deployed functionality, documentation, tests, and historical work. Do not remove or disable the DFS product solely because development is paused.

Pause DFS-related pending decisions, credentials, subscriptions, and provider approvals. Mark them `OWNER_PAUSED`, not rejected, forgotten, or completed.

The pause is recorded in PR #1810. Integrate it after appropriate checks and reconcile any outdated completion-plan instructions.

Ordinary sitewide security fixes may continue when necessary; they must not be disguised DFS feature work.

### LEAGUE TYCOON IS ALSO SHELVED

Retain the completed League Tycoon research and Ideas backlog.

Do not implement the League Tycoon integration, contract-dynasty features, or platform migration. Do not request league configuration decisions, signed-in captures, or credentials for it now.

Sleeper remains the current platform. Reopen League Tycoon only after a fresh explicit owner directive.

---

# PART 2 — BINDING VALUATION AND IDP DECISIONS

## Decision 1 — DLF IDP voting: KEEP THE HOLD

Choose **Option B** from the October 18 IDP rehabilitation evaluation.

Do not immediately reverse the DLF offense-only voting policy.

The evidence shows DLF's own IDP contribution is relatively modest, but reversing the hold also reactivates the existing outlier filter on 158 IDP rows, removes 32 other-source votes, and moves 31 player values by as much as 48%.

That downstream effect is too significant to accept without evaluating the preregistered challenger.

Implement and run `idp-hampel-n3-v1` against its 105 frozen complete archives, using the declared holdout, seed, and evaluation metrics. Do not change the preregistration after observing results.

**Binding disposition:**

- If the challenger fails, is inconclusive, or lacks sufficient independent validation, keep the DLF IDP voting hold.
- If it satisfies its preregistered acceptance criteria, independently validate the full board impact, including the filter's effects on other-source votes.
- Only then may the explicitly approved DLF IDP restoration proceed through a reviewed, reversible release with production verification.
- Never reduce outlier standards merely to activate the source.
- Keep DLF's IDP and rookie-IDP boards under one provider-family cap.

No additional owner decision is needed for ordinary challenger execution. A previously unapproved methodology change still requires its own evidence and gate.

## Decision 2 — IDP source independence: PREVENT DOUBLE COUNTING

Approve the proposed **IDP-scoped shared correlation cap** for IDP Trade Calculator and `idpShowCombined`.

The observed near-identical IDP ordering makes treating them as two independent opinions indefensible when both are eligible.

Requirements:

- Apply this cap only to defensive players.
- Do not combine their offensive or pick evidence under the IDP-specific rule.
- Do not make the IDP-only Show board an additional voter.
- Implement the correlation rule through the canonical source-lineage and family-cap owners, not a second weighting system.
- Run a baseline-versus-challenger replay, with independent confidence-count checks.
- Preserve current values where the IDP Show remains quarantined.
- Require a normal validated release before activating a change that moves served values.

The policy choice is made: correlated copies must never gain artificial voting power.

## Decision 3 — IDP Trade Calculator offense vote: DO NOT ADD AN INDEPENDENT DUPLICATE

Do not treat an IDP Trade Calculator offensive opinion as a new independent KTC-family vote without lineage evidence.

Choose **exclusion of an unproven extra offense vote**, rather than an artificial addition to the consensus.

Keep any existing legitimate, independently evidenced source behavior unchanged until its actual contribution has been measured.

If a future offensive vote is proven to derive from KTC Crowd, it may enter only under the existing KTC Crowd shared cap, never as an additional independent family.

This settles the policy question; the engineering task is verifying the exact existing voting behavior.

## Decision 4 — DLF Values: APPROVE RANK-TO-HILL, CONDITIONALLY RELEASE

Approve the **rank-to-Hill** representation of DLF Values as an offense-only member of the existing DLF provider family.

Reject the raw/max representation: its observed outlier rejection is approximately 89.7%.

The rank-to-Hill representation shows reasonable stability and a relatively limited measured board impact.

Conditions for production activation:

- Preserve the existing DLF family weight; never create a new independent provider family.
- Split the existing DLF cap appropriately when both DLF Rank and DLF Values are eligible.
- Verify source timestamps, completeness, longitudinal stability, top-player movement, and the full regression suite.
- Test changes against offense, picks, IDP noninterference, and the current geometric package model.
- Preserve the current source policy if independent gates fail.
- Use a reversible, explicitly observable release.

This is approval of the named candidate under its evidence gates, not permission to manufacture a passing result.

## Decision 5 — FantasyPros: USE ACTUAL UPSTREAM FRESHNESS

Approve the stricter `EXPLICIT_UPSTREAM_TIMESTAMP` interpretation.

The timestamp that controls voting freshness must reflect the provider's actual publication or expert-update evidence, not the time our collector downloaded an old ranking.

Do not refresh the age of stale rankings simply by scraping them again.

Complete the outstanding dual-family duplicate-identity analysis and eliminate any artificial vote amplification without suppressing legitimately independent material.

If stricter freshness removes a source's voting eligibility, report the source honestly as stale or unavailable. Do not fill missing votes with zero.

## Decision 6 — IDP deep-tail normalization: RUN A CHALLENGER

Approve developing the proposed preregistered challenger comparing:

- Current rank-to-Hill extrapolation on deep IDP ranks.
- Translation to the IDP Trade Calculator's own native values at equivalent effective ranks.

Measure calibration, bias, rank preservation, source independence, position-level effects, and historical stability.

**Do not immediately replace the approved Hill method.**

Use independent holdout evidence and existing model-governance thresholds. If the challenger does not convincingly improve the current method, retain the incumbent.

Do not alter the approved tail saturation rank or global valuation coordinate as an unreviewed side effect.

## Decision 7 — Signals IDP: MAINTAIN THE CURRENT HOLD

The Signals IDP candidate did not pass the required promotion gates.

Do not activate it, lower thresholds, or manipulate timestamps or denominators to make it pass.

Obtain the box-local evidence and diagnose failures. A genuinely different challenger must be preregistered before testing.

No production source-promotion action until the existing governance is satisfied.

## Decision 8 — Active Value Adjustment: NO CHANGE

Keep `geom_q078_v1` with **q = 0.78** as the active package model.

Keep the previous KTC model available for the existing rollback/historical-comparison purposes.

Do not recalibrate q from a small collection of accepted real trades. Accepted trades are useful market observations, not automatically ground-truth fair values.

Continue the independent package-model evaluation using the server-local production trade archive.

Do not reopen the already-approved 250-point Best Offers rule, fairness classifications, or the separate canonical YES/NO decision engine.

---

# PART 3 — TRADE CALCULATOR AND SIMULATION DECISIONS

## Decision 9 — Missing external-source evidence

For Trade Calculator matrix item `TCM-K06`, use the following behavior:

If an external opinion is excluded for freshness, access, identity, or other evidence reasons, display it as **Unavailable — [actual reason]**.

Do not:

- Show an unavailable opinion as EVEN.
- Replace its independent vote with our own canonical value.
- Count a canonical fallback as a second opinion.
- Turn the missing value into zero.
- Hide the fact that a source could not be evaluated.

The independent-vote tally must be numerically consistent with the displayed independent opinions.

Implement this through the existing Second Opinions owners and add regression tests.

## Decision 10 — Remaining Trade Calculator work

Continue TC-B through TC-F under the approved completion workstream.

Prioritize, in order:

1. Missing correctness and evidence states.
2. Complete desktop/mobile redesign.
3. Reliability, stale-response prevention, performance, and accessibility.
4. The remaining feature-matrix gaps.
5. Independent end-to-end and authenticated production verification.

Keep the existing share-link format frozen until a coordinated compatibility migration is tested; no silent URL breaks.

For three-or-more-team trades, provide supported analysis only when the decision engine can accurately identify the user's side and account for every trade side. Otherwise state that a reliable YES/NO recommendation is unavailable.

Never fabricate a binary recommendation for unsupported trade shapes.

Reuse one package-value owner and one final decision owner. No competing recommendations.

## Decision 11 — Playoff odds: ELIMINATE DOUBLE COUNTING

Approve removing a proven duplicate rest-of-season influence from the championship/playoff model.

Before replacing the published engine:

- Use the AL-5c shadow evaluation or an equivalent preregistered independent comparison.
- Show the incumbent and corrected equations explicitly.
- Prove that rest-of-season evidence is not counted twice.
- Validate historical calibration, predicted distribution behavior, uncertainty, and league-format sensitivity.
- Keep the incumbent if the proposed replacement fails the established acceptance standard.

Do not change the official Power Rankings formula as a side effect.

The product decision is that **double-counted evidence is not acceptable**; the evidence gate determines whether the proposed implementation has actually corrected it.

---

# PART 4 — AWARDS AND LEAGUE-STRATEGY DECISIONS

## Decision 12 — Unified Manager of the Year: REMAIN EXPERIMENTAL

Do not promote the unified Manager of the Year candidate as the official award for 2024, 2025, or 2026.

The historical record is incomplete, especially the decision-time future-value half of the trade component. Missing history must never be replaced by hindsight values.

Adopt these interim rules:

- Preserve the current official Manager of the Year method and official display.
- Keep the unified method as a clearly labelled **validation-only candidate**.
- Keep its already-approved weights unchanged.
- An unavailable trade component is `UNAVAILABLE`; do not redistribute its weight.
- Do not publish an incomplete candidate as a definitive 100-point score.
- Prefer component-level evidence and an explicit range of possible outcomes over an apparent winner that incomplete evidence could overturn.
- A component with materially incomplete required evidence, including waiver/draft evidence, must be marked partial or unavailable rather than being treated as complete.
- Never penalize rebuilding, players sold for future picks, or legitimate no-trade seasons because evidence is missing.
- Use historical values only when they were actually knowable at the decision time.
- Use prior-period or out-of-sample draft expectations; don't claim an in-sample model independently predicted its training data.
- Keep FAAB transfers unpriced when no defensible point-in-time conversion exists.
- Unknown dropped-player production remains unknown.

**Earliest potentially eligible official season: 2027**, subject to complete evidence and normal promotion gates.

Continue improving the candidate's evaluation and reporting, but do not change today's official award.

## Decision 13 — `dynasty_new` draft order: OUT OF CURRENT SCOPE

Do not invent a lottery or presume a playoff-finish rule for `dynasty_new`.

The current draft-valuation automation scope is `dynasty_main`.

Preserve `dynasty_new` and its existing behavior; defer all league-specific draft-order methodology until the owner actually requests it.

Similarly, the `dynasty_main` 2027–2029 inventory and $1,200-per-class policy have already been approved. Remove obsolete requests for those decisions.

---

# PART 5 — PREMIUM UI DECISION

## Decision 14 — Resolve categorical chart contrast

Choose a **high-contrast categorical palette on the existing cream editorial surfaces**, implemented centrally through the semantic chart-token owner.

Approve these candidate colors in categorical order:

| Semantic token | Color |
|---|---|
| `--chart-1` | `#986400` |
| `--chart-2` | `#2264af` |
| `--chart-3` | `#ac386a` |
| `--chart-4` | `#6752b6` |
| `--chart-5` | `#087650` |
| `--chart-6` | `#aa3c17` |

Their calculated contrast ratios on the documented nested cream surface `#e9dfca` are approximately 3.82, 4.52, 4.50, 4.59, 4.27 and 4.71 to 1, respectively, exceeding the chart-mark 3:1 target.

Before shipping:

- Validate against every supported chart background and chart-mark treatment.
- Verify light/dark contexts separately.
- Preserve existing categorical order.
- Test color-vision deficiencies and differentiate series through labels, line patterns or marker shapes where necessary.
- Do not repurpose movement-up blue or movement-down orange semantics.
- Use shared design-system tokens; no component-local patches.
- Preserve Premium Sports Intelligence Direction A.
- Capture real desktop/mobile evidence and run accessibility checks.

If a particular surface still fails, repair that surface through its canonical theme owner, not by weakening the contrast target.

This closes the outstanding palette-selection question in issue #1428.

---

# PART 6 — SECURITY, ACCOUNTS, AND OPERATIONAL POLICIES

## Decision 15 — Sleeper write gateway: NOT NOW

Keep Chase Upside **read-only with respect to real Sleeper roster and league transactions**.

Do not implement authenticated trading, waiver claims, drops, commissioner changes, or other real account mutations.

Research and read-only recommendations remain authorized. Actual automated league writes require a separate future owner directive.

## Decision 16 — Ask Brisket inference spending: OFF

Keep paid AI inference disabled until there is a documented cost, privacy, and value case.

Do not buy credits or enable paid inference just to call the site complete.

Existing permitted deterministic features may continue.

## Decision 17 — Optional data services

Use legitimate, existing free data when it meets evidence and provider-use requirements.

Do not subscribe to SportsDataIO, Fantasy Nerds, licensed odds providers, or other paid services automatically.

For BALLDONTLIE or CollegeFootballData, use the free path only if source terms and reliability support it and an appropriately authorized account/key becomes available.

Otherwise show honest incomplete/unavailable states. Missing optional provider keys must not block unrelated features.

Do not let shelving DFS interfere with non-DFS Game Day data needs.

## Decision 18 — Repository security

Choose **protected PR-based merging without routine administrator bypass**.

Preserve required independent checks, exact-head release validation, review requirements, and production-deployment verification.

Inventory write-capable deploy keys. Retire unused write access only after independently confirming that removal will not break the legitimate deployment path.

The operator must rotate the previously exposed `JASON_LOGIN_PASSWORD`. Never display, request in chat, log, or commit the new secret.

Create a clear runbook for remaining administrator-only actions.

## Decision 19 — Screenshot OCR

Keep free, local Tesseract OCR as the approved engine.

Do not add a paid vision service or a new credential requirement.

The documented production binary installation is an administrator task. After installation, verify recognition against real permitted screenshots, especially dark mode, offense, IDP, picks and ambiguous names.

Never automatically import a guessed player identity.

---

# PART 7 — ROOKIE AUCTION POLICY

## Decision 20 — Mock-first continues

Keep the existing rookie auction mock system and its approved rules.

Do not open an official room, invite members to an official auction, change real budgets, or write real roster transactions.

The official 2027 rookie auction remains gated on readiness and explicit owner launch authorization.

For development and mocks:

- Leading accepted bids continue to reserve funds.
- An **unaccepted trade offer does not reserve auction money**.
- Money movement occurs only after a verified accepted transaction.
- Use the existing proposed timing and nomination rules for mock testing only.
- Never treat provisional points-for standings as the final draft order.
- Do not create synthetic rookie identities or official rookie values.

Use the existing hourly on-host backup and restore verification for mock readiness. For official operation, recommend a validated encrypted off-host recovery copy or separately documented risk acceptance before launch.

Do not interrupt current development to demand next year's official auction decisions.

---

# PART 8 — AUTOMATICALLY RESOLVE STALE DECISION RECORDS

Audit every owner-action and unresolved-decision register against the current code, merged PRs, production records, and owner directives.

In particular:

- Close decisions already answered by the active geometric Value Adjustment.
- Close the approved 250-point Best Offers qualification decision.
- Close the five Trade Calculator decisions and RETOOL → BALANCED rule.
- Close `dynasty_main` 2027–2029 draft-capital inventory decisions.
- Mark DFS decisions owner-paused.
- Mark League Tycoon decisions owner-paused.
- Keep `dynasty_new` changes out of scope.
- Do not mislabel merged code as production-verified.
- Do not mislabel an approved methodology as validated implementation.
- Do not treat missing evidence as a new owner decision when engineering can collect it.

Where records conflict, use the latest valid, specifically scoped owner decision and cite the provenance.

Do not manually edit the generated completion dashboard. Correct the underlying requirement evidence and regenerate it using the canonical script.

---

# PART 9 — EVIDENCE WORK TO COMPLETE WITHOUT INTERRUPTING ME

Proceed independently on evidence collection and implementation that does not require privileged owner action.

Prioritize:

1. Run the preregistered IDP outlier challenger.
2. Run Signals IDP dependence analysis on the actual available box-local data.
3. Run the geometric package-model evaluation against the production trade archive.
4. Finish independent draft-valuation verification, 216-pick reconciliation, and rollback testing.
5. Finish the Trade Calculator feature matrix and authenticated desktop/mobile production verification.
6. Prove the Manager Intelligence pages and saved-manager activity functionality under proper authentication.
7. Validate the source freshness and family-cap changes without artificial independence.
8. Investigate and repair broken scheduled workflows and unreliable CI tests.
9. Restore or replace legitimate authenticated production verification where it is disabled.
10. Regenerate the completion dashboard from genuinely refreshed evidence.
11. Continue TC-D2, TC-E and TC-F after their dependency gates.
12. Preserve the approved sitewide package model across Trade History, Second Opinions, discovery, valuation and simulations.

Do not wait for me to approve ordinary tests, read-only queries, reproducible local evaluations, documentation fixes, or already-authorized implementation.

Do not fabricate production evidence when the server, authenticated session, or source archive is unavailable.

If data is unavailable, write the precise executable command and evidence request for an authorized operator rather than claiming success.

---

# PART 10 — IMPLEMENTATION AND MERGE RULES

Review the current GitHub state, especially release trains #1809 and #1810 and any subsequently opened PRs.

Follow current `main` and the canonical Agent OS. Do not trust older PR descriptions over live code.

For each decision:

1. Identify the canonical owner, source of truth, and affected requirements.
2. Record the decision and why it is best for accuracy, fairness, stability and cost.
3. Identify implementation dependencies and owner boundaries.
4. Make the smallest correct code or documentation change.
5. Run relevant unit, integration, cross-surface, adverse-case and independent validation tests.
6. Confirm existing product behavior is preserved except for explicitly approved changes.
7. Open a bounded PR with a clear regression and rollback plan.
8. Merge only after the current exact head satisfies required CI, E2E, release, and review gates.
9. Verify the actual deployed build and observe the relevant functionality before calling it production-complete.

No blind bulk merges. No workaround that makes tests pass by weakening assertions. No changes to source weights, q, or model gates outside the specific decisions here.

**Do not mark a conditional source or model activation complete simply because the owner approved its intended direction.** All named evidence gates must still pass.

---

# PART 11 — REQUIRED FINAL DELIVERABLES

Produce two durable records.

### A. Consolidated owner decision register

One row for every unresolved or previously stale decision, containing:

- Stable decision ID.
- Product family.
- The exact question.
- The decision made under this directive.
- Evidence supporting it.
- Risk and expected impact.
- Current status: DECIDED, IMPLEMENTED, MERGED, DEPLOYED, PRODUCTION_VERIFIED, EVIDENCE_PENDING, HUMAN_ACTION_REQUIRED, OWNER_PAUSED.
- Implementation PR and test evidence.
- Remaining action, if any.

No duplicate owner questions and no invented approvals.

### B. Residual blocker report

After implementing everything currently actionable, report **only what remains genuinely blocked** under these headings:

1. **Human-only action:** credentials, administrator permissions, official launch, unavoidable real-world confirmation.
2. **External/time-dependent evidence:** provider updates, future rookie observations, missing historical records.
3. **Engineering evidence pending:** tests, benchmarks, independent evaluation, replay, deployment, production verification.
4. **Intentionally deferred:** DFS, League Tycoon, official auction activation, expensive/unauthorized services.

For every item identify who can resolve it, exactly what unblocks it, and whether it prevents any currently authorized production feature.

Do not come back with a broad questionnaire.

If a genuinely new decision arises that the present directive does not cover, gather the relevant evidence, prepare one recommended answer, and explain the smallest remaining owner-only choice.

**The finish line is a fully completed, trustworthy Chase Upside site, not a collection of merged PRs. Preserve accuracy and release discipline while removing every unnecessary owner-decision bottleneck.**
