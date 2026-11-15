# Owner directive 2026-10-30: release completion, integration recovery, Roster Construction Intelligence V1

**Owner:** the site owner (Chase Upside / `riskittogetthebrisket`).
**Date:** 2026-10-30.
**Source:** the owner's chat with the coordinator session, 2026-10-30 ("MASTER EXECUTION DIRECTIVE"). Copied verbatim
below. Intake rows: `docs/OWNER_REQUESTED_TODO.md` "Added 2026-10-30 — Release completion, integration recovery, Roster
Construction Intelligence V1" (RCV-1 … RCV-8). Authorization: `docs/EXECUTION_PLAN.md`, same date. Recording the
directive here authorizes nothing beyond what the execution plan says.

## What it authorizes

- Scoped implementation of a **private** Roster Construction Intelligence V1 behind a new **default-OFF** feature flag,
  subject to the existing canonical methodology, permissions, independent review and release gates (directive Phase 3).
- Completing #2024 (IDP streaming composer) and then #2025 (streaming API + UI) under owner decision 1 of 2026-10-29
  (`docs/owner/IDP_STREAMING_DIRECTIVE_2026-10-29.md`): signed-in activation of `waiver_advisor` + the streaming flag
  after the acceptance scenarios, exact-head green CI and independent review.
- Reconciling and integrating PR #2026 (three-month owner-idea audit, Future First roster specs) into the planning
  hierarchy under the standing routine-merge authorization, only when every applicable gate passes.

## What it does NOT authorize

- Changing live dynasty values, valuation curves, source voting or weights.
- Turning on any held model promotion or held flag (#2006, #1938, #1884, #1873, #1852, freshness v2, DLF holds, Sim V3).
- Public exposure of the Waiver Advisor, the streaming advisor or Roster Construction.
- Any Sleeper write or claim submission.
- League Tycoon migration or implementation (stays OWNER-PARKED; #1755 stays a coordinator disposition).
- Weakening any test, gate, or legal league configuration.

## Owner-gated

- **Production activation of Roster Construction V1 is not explicitly authorized.** The flag stays OFF in production
  until the owner says otherwise. Building, testing, reviewing and merging it default-OFF is authorized.

## The directive (verbatim)

MASTER EXECUTION DIRECTIVE

CHASE UPSIDE — RELEASE COMPLETION, INTEGRATION RECOVERY & ROSTER CONSTRUCTION INTELLIGENCE

Date: October 30, 2026
Repository: "jasonleetucker-code/riskittogetthebrisket"
Production: "https://chaseupside.com"

YOUR ROLE

Act as the principal engineering coordinator, quantitative fantasy football architect, software integration lead, and independent quality-control director for Chase Upside.

You are responsible for coordinating multiple specialized development agents to complete existing work, remove integration blockers, and begin the next major product capability without creating duplicate engines, contradictory models, or disconnected features.

This is an execution assignment, not simply a research or documentation exercise.

The objective is to deliver the maximum amount of correct, integrated, verified product functionality permitted under the current owner directives.

Do not confuse writing documentation, passing unit tests, merging a PR, deploying code, and verifying the actual user experience. These are separate milestones.

---

PHASE 0 — ESTABLISH THE CURRENT TRUTH

Before modifying code:

1. Fetch current "origin/main".
2. Read "CLAUDE.md", "AI_INSTRUCTIONS.md", "docs/AGENT_OPERATING_SYSTEM.md", "docs/EXECUTION_PLAN.md", and "docs/WORK_CLAIMS.md".
3. Inspect all open PRs, recently merged PRs, CI results, review comments, branch relationships, feature flags, and recent deployment evidence.
4. Read the October 2026 planning audits, including the new PR #2026.
5. Confirm the actual production state rather than trusting old handoff notes or historical audit statuses.

The current audit identifies 21 open PRs, but you must independently refresh that number.

Particular priorities:

- #2024 — IDP streaming composer.
- #2025 — IDP streaming API and UI, stacked on #2024.
- #2026 — three-month owner-idea audit and master-planning improvements.
- #2006 — owner-held rookie voting rule.
- #1938 — held IDP scoring changes affecting BDVM.
- #1884 — held outlier integrity V2.
- #1873 — held market-ledger evaluation.
- #1852 — held market maturity/reserve work.
- #1755 — deferred League Tycoon ideas, preserved separately.

For every significant open PR, identify:

- Actual purpose.
- Whether it remains necessary.
- Whether its work is already merged elsewhere.
- Whether it is behind main or conflicts with another branch.
- Whether its tests pass on the exact integration head.
- Whether independent review is complete.
- Whether the owner authorized merging and activation.
- The next concrete action.

Do not blindly close or merge PRs to clean up the queue.

Deliverable: a concise, accurate integration priority register that serves as the execution checklist.

---

PHASE 1 — MAKE THE MASTER PLAN AUTHORITATIVE

PR #2026 contains the three-month retrospective Chase Upside audit and the six-episode Future First Roster Construction specifications.

Its contents must be reconciled and integrated into the existing planning hierarchy.

Important sources include:

- "docs/MASTER_PRODUCT_PLAN.md"
- "docs/OWNER_PRODUCT_BACKLOG_SPEC.md"
- "docs/OWNER_REQUESTED_TODO.md"
- "docs/BRISKET_IDEAS.md"
- "docs/OWNER_FEATURE_ADDENDUM_2026-08-29_BEST_BALL_ROSTER_UTILITY.md"
- "docs/owner/CHASE_UPSIDE_90_DAY_CONVERSATION_AUDIT_2026-10-30.md"
- "docs/owner/LEAGUE_TYCOON_DEFERRED_IDEAS_PRESERVED_2026-10-16.md"

The October 30 audit incorporates 72 previously recovered requirement clusters and the separate 88-item October audit. Preserve the detailed original specification references; do not reduce them to generic feature titles.

Resolve overlapping changes to "docs/OWNER_REQUESTED_TODO.md", which has been claimed by the IDP streaming coordinator.

Rebase or reconcile PR #2026 against current main, validate all cross-references, obtain the required independent review, and merge under the existing standing authorization only when all applicable conditions are met.

The League Tycoon research remains expressly parked. Do not use this work to authorize migration or implementation.

Acceptance: a fresh engineering agent reading main can identify the exact requested behavior, canonical implementation owner, dependencies, authorization, and remaining tests for every incorporated major feature.

---

PHASE 2 — COMPLETE THE IDP WAIVER ADVISOR

This is the immediate product-release priority.

The following foundations are already merged and must not be rebuilt:

- #2018 — IDP streaming intake and FAAB current-week correction.
- #2019/#2023 — backtest framework and results.
- #2020 — dynasty-safe drop assessment.
- #2021 — weekly league-scored projection source and archive.
- #2022 — exact streaming solver.

Finish #2024 and then #2025 in the correct dependency order.

2A. Repair #2024

The previous CI failed on:

"tests/draft/test_waiver_population.py::test_only_the_p3_consumers_import_the_population_builder"

It reported "src/waivers/streaming.py" as an unexpected import consumer.

Investigate the architectural contract. If the module is legitimately consuming a shared population builder, update the test's documented ownership boundary with evidence. If the import improperly bypasses the canonical free-agent interface, fix the implementation instead.

Do not simply weaken an architectural test to obtain green CI.

The same previous run showed Micah Parsons ranked #219 while an IDP launch-readiness test required #210 or better.

Investigate:

- Actual underlying scored inputs.
- Source freshness and vote availability.
- Correct defensive stat weighting.
- Player identity and position classification.
- Whether the test is meant to enforce a valid owner-approved requirement.
- Whether current main independently reproduces the issue.

Do not manipulate a player value, change a valuation curve, change the test threshold, or override source weights merely to pass this check. Preserve owner approval gates for consequential numerical changes.

Rebase #2024, run full required checks, seek independent review, and integrate when authorized.

2B. Integrate #2025

After #2024 is integrated, retarget/rebase #2025 to main and verify the complete backend/frontend flow.

The user must be able to:

1. Select their Sleeper league and roster.
2. Select the upcoming week and relevant IDP position.
3. View available players and projected fantasy output under their actual league settings.
4. See which players on their own roster are protected, conditional, or safe to consider dropping.
5. Configure an appropriate dynasty-value-loss budget.
6. Evaluate up to seven possible streaming positions, while allowing zero.
7. Compare best legal add/drop packages across multiple weeks and playoff-relevant horizons.
8. See projected optimized-lineup point improvement, dynasty asset cost, and FAAB implications.
9. Understand why a recommendation was made.
10. Receive an explicit NO TRANSACTION result when no worthwhile legal move exists.

Preserve the exact historical and projection distinction.

Missing inputs must not become zero.

Searches that exhaust their work budget must not claim mathematical optimality.

The interface must match Premium Sports Intelligence Direction A and pass authenticated desktop and mobile tests, including WebKit, accessibility, and performance checks.

The October 29 owner directive already conditionally authorizes signed-in production activation after the specified acceptance, independent review, green CI, and safety gates. Reverify that authorization and its scope before activation. Do not extrapolate it to public exposure, Sleeper transactions, or unrelated features.

Completion requires: deployed, appropriately gated, authenticated production functionality with a verified real selected-league user path, not simply merged code.

---

PHASE 3 — BUILD THE NEXT FLAGSHIP FEATURE: ROSTER CONSTRUCTION INTELLIGENCE V1

This prompt authorizes scoped implementation of a new private Roster Construction V1, subject to the existing canonical methodology, permissions, independent review, and release gates. It does not authorize changes to live dynasty valuations, source voting or other held model promotions.

The detailed feature contract is in:

"docs/OWNER_FEATURE_ADDENDUM_2026-08-29_BEST_BALL_ROSTER_UTILITY.md", especially §§9–20.

Also read "docs/OWNER_PRODUCT_BACKLOG_SPEC.md" FC-01, FC-02, FC-06 and the six Future First podcast research records.

3A. The exact user-facing goal

Create a new Roster Construction experience that lets me choose any dynasty team and understand the actual effectiveness of its roster.

It must answer:

How well does this team produce fantasy points at each position, how does that compare to the other teams in its league, how much dynasty value does it hold at each position, and what does that mismatch tell us about how the roster should be built?

Do not create another generic Team Strength dashboard or rename existing functionality.

Reuse what already works.

3B. Actual positional production rankings

Show league-wide rankings for:

- QB
- RB
- WR
- TE
- DL
- LB
- DB

Also account for K and any other configured eligible positions or slots where appropriate.

For each team's position group, compute the total fantasy points contributed by players who entered its actual legal optimized weekly best-ball lineup, attributed to their real player position.

A WR assigned to a FLEX slot counts as WR production exactly once.

A TE assigned to an eligible FLEX counts as TE production exactly once.

Superflex, dedicated QB slots, two-TE requirements, and DL/LB/DB slots must follow the selected league's real rules.

Do not hardcode the podcast's 12-team, start-11, 27-player example as the site's universal format.

Display:

- Total optimal starter points.
- Rank among league teams.
- Rank percentile or appropriate comparison.
- League average and median.
- Weekly progression.
- Number of distinct players contributing.
- Top contributors.

Historical scoring must respect when a player was actually owned and eligible on that team.

If a league uses manually submitted lineups rather than best ball, label and separate observed submitted scoring from hypothetical optimal scoring.

3C. Dynasty value rankings beside production

Show a separate ranking of the dynasty market/model value held at each position.

A hypothetical TE group might be:

- 12th in actual tight end starter points.
- 2nd in dynasty tight end asset value.

That is potentially meaningful roster information, but it does not automatically mean that tight ends are overpriced or that a trade should occur.

The two metrics must remain independently calculated and clearly labeled.

Position-normalize comparisons where appropriate and distinguish productive veterans, developmental players, injured assets, and concentrated value.

Never feed team-dependent lineup utility back into a player's standalone canonical dynasty price.

3D. Actual starts versus counterfactual starts

For each player, calculate and label three distinct concepts:

Actual optimized starts while owned: weeks the player entered this team's optimal legal lineup during their real ownership tenure.

Hypothetical optimal starts: weeks the player would have entered that lineup under a clearly defined counterfactual roster scenario, with its assumptions visible.

League-relative startability: weeks the player exceeded an appropriate empirical scoring or replacement standard for that league, with FLEX competition and scoring rules accounted for.

A player traded away in Week 6 should not automatically be compared to a player owned for 17 weeks as though they had the same opportunity to start.

Show denominators, bye weeks, injuries, sample size, and ownership-effective dates.

Do not claim that a simple weekly top-24 positional finish is always equivalent to an optimal lineup start in a league with multiple FLEX positions.

3E. Roster utility and depth quality

Build or reuse shared analytics for:

- Conditional marginal optimized-lineup points.
- Lineup Entry Probability where supported.
- Redundant production.
- Depth insurance.
- Position-week coverage.
- Spike-week overlap.
- Replacement-player opportunity cost.
- Roster-slot shadow value.
- Availability and aging risk.

The canonical definition of a player's conditional contribution is the difference in optimal legal lineup utility between the roster with and without that player, holding scenario assumptions consistent.

Use the existing legal lineup solver, not a second competing optimization engine.

For historical calculations, use actual realized outcomes. For future projections, use explicitly labeled predictive inputs and calibrated uncertainty.

3F. Actionable construction diagnosis

The dashboard should identify specific roster construction problems such as:

- Too much dynasty value concentrated in players who rarely contribute to the lineup.
- Strong starting talent but inadequate injury or bye-week coverage.
- Too many low-opportunity bench players on a contender.
- Excessive reliance on aging players.
- A developmental roster with valuable assets but insufficient future starting coverage.
- A position that would benefit from cheaper depth rather than another expensive star.
- An opportunity to gain value through a sensible tier-up or tier-down.

Every diagnosis must be supported by actual calculated evidence.

Do not hardcode "twice the number of starters" as a mathematical law. Treat it as a research heuristic and test it against the true requirements of each league.

An apparent weak position must not automatically generate a transaction recommendation.

NO ACTION is a valid result.

3G. Shared-system architecture

Roster Construction must ultimately inform:

- Trade Analyzer and Trade Desk.
- The existing Waiver Advisor.
- Dynasty Team Strength.
- Competitive Posture.
- Draft and rookie auction planning.
- Contender versus rebuilder strategy.
- Future Next Move recommendations.

But these products must consume the same canonical calculations.

They must not each independently decide replacement level, legal lineup allocation, or the meaning of roster value.

For V1, prioritize historical correctness, selected-team comparison, understandable explanations and a stable private interface before adding every advanced future scenario.

---

PHASE 4 — PARALLEL ENGINEERING STRATEGY

Use specialized agents where the work is independent.

Do not have five agents editing the same service or creating five interpretations of the same model.

Recommended lanes:

Lane A — Integration and release. Own #2024/#2025 dependency repair, CI, independent review, release gates and production verification. Respect existing active work claims.

Lane B — Planning and documentation reconciliation. Own PR #2026, historical source preservation, accurate current-state statuses and specification completeness. Coordinate any overlap with Lane A.

Lane C — Roster intelligence mathematics. Inspect and reuse "src/ros/lineup.py", established roster utility/replacement owners, scoring and historical player eligibility. Implement only the minimal missing calculation layer.

Lane D — Roster Construction frontend. Build the private mobile-first dashboard against a versioned backend contract. Use realistic fixtures while the API integration is pending.

Lane E — Independent validation. Verify numerical fixtures, cross-position scoring, ownership history, FLEX attribution, chronological correctness, mobile UX, and integration/release readiness. Do not self-certify code written by the same worker.

If a worker's files are already claimed, coordinate with that owner or defer the overlapping portion. Do not overwrite existing agents' work.

Serial integration of shared contracts is preferable to unsafe concurrent edits.

---

PHASE 5 — ACCEPTANCE AND RELEASE

At minimum, validate:

1. A selected league with the real configured starting positions and defensive scoring.
2. A player acquired or traded halfway through the season.
3. A FLEX contributor who must be counted at his actual position exactly once.
4. A valuable injured player with no current points.
5. Multiple players with simultaneous spike weeks where only some enter the lineup.
6. A team with great starters but inadequate backup coverage.
7. A team whose roster is overfilled and must make a legal drop.
8. Missing historical ownership or weekly actuals.
9. A player who is valuable in the dynasty market but redundant on a particular roster.
10. A team for which a waiver acquisition improves expected points but the dynasty loss makes the move unacceptable.

Use synthetic deterministic fixtures first, then actual historical league snapshots.

Confirm backend/front-end parity and prevent future information from leaking into historical decisions.

Maintain the existing mandatory CI, independent review, accessibility, mobile and deployment requirements.

Do not weaken tests to declare completion.

Do not turn held valuation, source-voting, public-advisor, market-trading or League Tycoon flags on.

Do not change established legal league configuration or the owner's unapproved methodology.

---

PHASE 6 — FINAL INTEGRATED DELIVERABLE

I do not want the assignment to end with five unrelated reports or several unmerged PRs that require me to reconstruct what everyone did.

Provide one coordinated delivery summary containing:

A. Current production truth: what is demonstrably live and functioning.

B. PR disposition: what merged, what remains open, what was superseded and why.

C. IDP Waiver Advisor: exact functionality delivered, required gates, live validation and any blockers.

D. Roster Construction V1: precise completed capabilities, routes/screens, inputs, calculations, comparison outputs and test evidence.

E. Architecture: how the new work reuses established scoring, values, lineups, projections and historical data.

F. Outstanding owner decisions: only genuinely consequential questions that cannot be resolved under existing authority.

G. Next recommended development wave: rank the remaining opportunities by user impact, technical dependency, implementation effort and readiness.

For every reported item, distinguish:

"SPECIFIED → IMPLEMENTED → TESTED → REVIEWED → MERGED → DEPLOYED → PRODUCTION VERIFIED"

Do not report a feature as complete because its PR exists.

MY PRIMARY OBJECTIVE

I want Chase Upside to become an increasingly intelligent, unified dynasty football decision platform.

Each feature should make the other features better because they share the same truthful data and mathematical foundations.

I want maximum useful progress, not maximum code volume, maximum PR count or maximum documentation.

Finish what's already underway. Integrate what belongs together. Build the next genuinely useful system. Preserve everything we have already decided.
