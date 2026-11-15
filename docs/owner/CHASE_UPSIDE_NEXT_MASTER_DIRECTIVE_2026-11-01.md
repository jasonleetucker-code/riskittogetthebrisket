# Owner directive 2026-11-01 (second): production security, Roster Construction, IDP prediction accuracy, frontend UX audit

**Owner:** the site owner (Chase Upside / `riskittogetthebrisket`).
**Date:** 2026-11-01.
**Source:** the owner's chat with the coordinator session, 2026-11-01 ("CHASE UPSIDE — NEXT MASTER EXECUTION DIRECTIVE"),
copied verbatim below. It expands, and does not replace, the first 2026-11-01 directive
(`docs/owner/CHASE_UPSIDE_MASTER_DIRECTIVE_DECISIONS_2026-11-01.md`, decisions 1–10). Intake rows:
`docs/OWNER_REQUESTED_TODO.md` MD-26 … MD-34. Authorization: `docs/EXECUTION_PLAN.md`, same date. Recording the
directive here authorizes nothing beyond what the execution plan says.

## What it authorizes

- **P0 production security.** Restrict unintended direct public access to the application ports while preserving
  availability; apply the repository's established nginx hardening process (`deploy/apply_hardening.sh`); verify the
  headers; retest. No infrastructure address, secret or sensitive configuration in any public artifact. The public
  Trade Advisor stays disabled.
- **P1** completion of Roster Construction (#2040 → #2041 → #2044) under decision 1's gates, with authenticated
  navigation only after production verification.
- **P2/P3** reconciliation of the IDP Show research (#2042, #2039) and the prospective, timestamp-verified comparison
  of the production champion against the shadow challengers (#2043, #2045). Shadow only.
- **P4** a complete frontend information-architecture, navigation, usability, accessibility and visual-consistency
  audit (§4.1–§4.12), and implementation of justified improvements within existing permissions, flags and the PSI /
  Direction A design system.
- **P5** continued mathematical research under existing evidence gates.
- **P6** roadmap reconciliation with full specificity.

## What it does NOT authorize

- Promoting any shadow model, changing production values, source voting or held flags.
- Exposing private intelligence in public navigation, or gated / disabled routes to complete a menu.
- Automated ingestion of proprietary subscriber data without usage rights.
- Bypassing the box's scoped sudo; root-only box changes remain the operator's.
- A second design system or navigation system; renaming or moving features for aesthetics alone.

## The directive (verbatim)

CHASE UPSIDE — NEXT MASTER EXECUTION DIRECTIVE
Production Security, Roster Construction, IDP Prediction Accuracy, and Comprehensive Frontend UX Audit
Repository: `jasonleetucker-code/riskittogetthebrisket`
Date: November 1, 2026
Execution Mode: Maximum Safe Parallel Build Mode
Primary Objective: Continue transforming Chase Upside into a mathematically reliable, intuitive, polished, and fully integrated fantasy football decision-intelligence platform.
This directive expands the existing November 1 development campaign. It does not replace earlier binding owner decisions.
Do not restart completed research, duplicate active workstreams, overwrite claimed files, or repeatedly request authorization for ordinary approved implementation.
The frontend usability workstream must run in parallel with existing backend, mathematical, security, and production work wherever file ownership and dependencies permit.
PRIORITY 0 — PRODUCTION SECURITY
Review PR #2038 and its production security findings.
Verify whether the backend and frontend application ports remain directly accessible from the public internet.
Coordinate with the production operator to restrict unintended direct access while preserving application availability.
Apply the repository's established nginx hardening process, verify the security headers, and retest the affected routes.
Never disclose infrastructure addresses, secrets, credentials, or sensitive configuration in public artifacts.
Keep the public Trade Advisor disabled until its separate security, licensing, and production gates pass.
PRIORITY 1 — ROSTER CONSTRUCTION PRODUCTION COMPLETION
Finish PRs #2040, #2041, and #2044 in the appropriate dependency order.
Preserve the verified 84/84 comparable 2026 team-week scoring parity and independently validate the latest code.
Complete remaining:

* Exact-head CI and independent reviews.
* Desktop and mobile testing, including WebKit.
* Authentication and privacy checks.
* Realistic production performance testing.
* Historical-season unavailable states.
* Position attribution, lineup eligibility, and dynasty-value separation.

Activate private Roster Construction only when every established requirement passes.
After production verification, ensure Roster Construction is discoverable through the correct authenticated navigation category.
Do not expose it publicly.
PRIORITY 2 — COMPLETE IDP SHOW RESEARCH INTEGRATION
Read the merged IDP Show library audit, PR #2042, and GitHub issue #2039.
Preserve the existing authenticated research findings, including the inventory of 24 IDP Show products.
Do not repeat completed investigations or access material outside the owner's subscription permissions.
Reconcile the findings into the weekly IDP, rest-of-season, dynasty, and source-integrity workstreams.
Prioritize independently reproducible signals such as:

* Tackles allowed by true position.
* Sustainable snap and role changes.
* Linebacker injury replacement opportunities.
* Cornerback alignment and opponent offensive personnel.
* EDGE/DT pressure and sack regression.
* Position-specific matchup opportunities.
* Sustainable roles versus temporary streaming situations.

Keep dynasty market values, weekly projected points, and rest-of-season production separate.
Preserve source lineage and prevent duplicate influence from The IDP Show and IDP Trade Calculator.
Do not integrate proprietary subscriber datasets into automated production ingestion without the necessary usage rights.
PRIORITY 3 — WEEKLY IDP PREDICTION ACCURACY
Reconcile PRs #2043 and #2045.
The evidence indicates that forecasting quality and projection coverage are more important than broadly relaxing dynasty-protection constraints.
Evaluate the current shadow challengers against actual timestamp-verified pre-kickoff forecasts from the production projection archive.
If adequate archived forecasts are unavailable, begin proper prospective collection.
Compare:

1. Current Sleeper/RotoWire production champion.
2. A properly shrunk statistical baseline.
3. Snap-weighted opportunity challengers.
4. Opponent-specific matchup challengers.
5. Role-change and injury-based challengers.
6. The complete hybrid model.

Measure MAE, RMSE, bias, calibration, positional ranking, top-starter identification, roster-dependent lineup improvement, and realized streaming decisions.
Distinguish lower point-prediction error from better fantasy decisions.
Do not promote shadow models until their incremental benefit is independently demonstrated.
Preserve the default zero dynasty-loss budget, exact league scoring, FAAB constraints, and explicit NO TRANSACTION recommendations.
PRIORITY 4 — COMPREHENSIVE FRONTEND USER EXPERIENCE AND NAVIGATION AUDIT
NEW OWNER DIRECTIVE — MAJOR PARALLEL WORKSTREAM
Conduct a complete frontend information architecture, navigation, usability, accessibility, and visual consistency audit of Chase Upside.
The goal is not simply to make the interface attractive.
The goal is to ensure that every feature is easy to discover, logically organized, intuitively named, easy to understand, and located where users naturally expect to find it.
I want the site to feel like one thoughtfully designed professional application, not a collection of independently developed features.
4.1 — Audit Every Existing Page and Route
Begin by discovering every actual frontend route in the repository.
Build a comprehensive page and feature inventory.
For each route, identify:

* Page name and URL.
* Primary purpose.
* Intended audience.
* Public or authenticated access.
* Relevant feature flags.
* Current navigation location.
* Every menu or link that exposes the page.
* Whether the page is reachable through normal navigation.
* Whether its name accurately describes its purpose.
* Whether it overlaps another feature.
* Whether its placement makes sense.
* Whether it is usable on desktop and mobile.
* Whether it is working, incomplete, disabled, or intentionally hidden.

Pay particular attention to functionality that has already been implemented but is missing from navigation.
The recent Weekly IDP Streaming discoverability problem is an example of exactly what this audit must prevent.
Do not assume a feature is properly integrated simply because its route works.
Likewise, do not expose intentionally disabled or protected routes merely to make the menu appear complete.
4.2 — Redesign the Information Architecture Where Necessary
Evaluate the entire navigation hierarchy.
Determine whether each feature belongs in its current section or whether another placement would make more sense.
Organize the application around what the user wants to accomplish, rather than internal development architecture, code module names, or the order features were created.
Evaluate whether the major navigation areas clearly distinguish tasks such as:

* Understanding my team.
* Improving my roster.
* Managing waivers and free agents.
* Evaluating trades.
* Researching players.
* Comparing dynasty values.
* Preparing for drafts and auctions.
* Viewing league intelligence.
* Monitoring matchups and game-day performance.
* Accessing historical analysis, reports, and settings.

These are conceptual user tasks, not mandatory final menu names.
Claude must independently determine the clearest grouping and naming based on the actual application.
Do not automatically create a new top-level section for every feature.
Avoid unnecessary menu fragmentation, overly deep nesting, giant undifferentiated dropdowns, and categories containing unrelated tools.
High-frequency and high-value features should generally require fewer navigation actions than rarely used administrative features.
Preserve the established product distinction:

* Public League experience: league history, entertainment, records, rankings, and community.
* Private authenticated experience: front-office intelligence, roster decisions, trading, drafting, and advanced analytics.

Do not expose private intelligence in public navigation.
4.3 — Evaluate Every Menu
Inspect all navigation surfaces, including:

* Desktop primary navigation.
* Desktop dropdown menus.
* Mobile menus and drawers.
* Subnavigation.
* Feature-specific tabs.
* Command palette or site search.
* Homepage feature links.
* Contextual links between related tools.
* Breadcrumbs or back-navigation patterns where applicable.
* Account and settings menus.
* Installed iPhone Home Screen/PWA navigation.

For each menu, answer:

1. Does the category name accurately describe its contents?
2. Are related features grouped together?
3. Are unrelated features mixed together?
4. Are any features duplicated unnecessarily?
5. Are important tools hidden too deeply?
6. Are any links missing?
7. Are any links broken or pointing to obsolete routes?
8. Are menu labels consistent with the actual page titles?
9. Does the mobile menu expose the same appropriate capabilities as desktop?
10. Can the user easily understand where they are and how to get somewhere else?

Identify unnecessary jargon and replace it with clear, recognizable terminology where appropriate.
Use established fantasy football terminology, but do not make users understand internal modeling names just to navigate the product.
4.4 — Evaluate Feature Placement and Discoverability
Specifically audit whether related features appear together.
Examples that require examination include:
Waivers and Weekly IDP Streaming
Determine whether the Waiver Advisor, standard Waiver Wire, weekly IDP streaming, roster-cut analysis, and FAAB tools are placed and named in a way that makes their differences obvious.
Users should not have to guess which of several similarly named pages performs a particular task.
Roster Construction
Determine whether it is naturally discoverable alongside Team Strength, roster analysis, team weaknesses, and other My Team intelligence.
Trade Tools
Determine whether Trade Calculator, Trade Finder, Trade Advisor, trade market intelligence, and related tools form a coherent workflow rather than disconnected destinations.
Player Research
Determine whether player profiles, rankings, projections, source consensus, development analysis, and other research tools can be discovered intuitively.
Draft and Auction Tools
Group related preparation, player evaluation, pick values, and live draft/auction workflows appropriately.
Game Day and League Intelligence
Ensure live matchup tools, playoff projections, league rankings, historical league information, and competitive intelligence are organized by purpose and access boundaries.
Do not assume any of these proposed groupings are correct until the actual user workflows have been audited.
4.5 — Perform User-Journey Testing
Test realistic tasks from the perspective of someone using the application rather than someone who built it.
At minimum, test these questions:

1. I want to see how strong my dynasty roster is. Where do I go?
2. I want to find a free-agent linebacker to stream this week. Where do I go?
3. I want to know which player I can safely drop. Where do I go?
4. I want to evaluate a dynasty trade. Where do I go?
5. I want to find players who are undervalued. Where do I go?
6. I want to compare player rankings and dynasty values. Where do I go?
7. I want to see my team's roster construction weaknesses. Where do I go?
8. I want to understand my playoff chances. Where do I go?
9. I want to prepare for a rookie draft. Where do I go?
10. I want to research a specific defensive player. Where do I go?
11. I want to see what has changed in my league. Where do I go?
12. I want to access settings or change leagues. Where do I go?

For each journey, measure:

* Whether the destination is discoverable.
* Number of navigation interactions required.
* Ambiguous choices.
* Dead ends.
* Incorrect or unnecessary detours.
* Inconsistent page naming.
* Desktop versus mobile differences.
* Whether the destination actually answers the question.

Aim for direct access to the most important workflows, without imposing an arbitrary universal click limit.
Record the before-and-after navigation experience for material changes.
4.6 — Audit Frontend Design Consistency
Use the repository's existing Premium Sports Intelligence / Direction A design north star.
Read the canonical design system, frontend standards, and UI implementation contracts before making visual changes.
Evaluate:

* Typography hierarchy.
* Spacing and alignment.
* Navigation styling.
* Color usage and contrast.
* Buttons and interactive controls.
* Cards, tables, and analytical panels.
* Page headings and descriptions.
* Loading, error, empty, and unavailable states.
* Mobile responsiveness.
* Density of information.
* Consistency across related features.
* Tooltips and contextual help.
* Visual distinction between projections, facts, estimates, and recommendations.

The application should feel professional, modern, polished, and restrained.
Do not respond to every usability problem by adding another dashboard card, tooltip, menu, or decorative component.
Prefer clarity, useful information, and consistent design over visual complexity.
Avoid unnecessary redesign of components that already work well.
4.7 — Audit Mobile and Installed-App Usability
Mobile is a first-class product experience.
Pay special attention to iPhone Safari and the installed Home Screen app.
Test:

* Navigation drawer behavior.
* Touch targets.
* Menu opening and closing.
* Accidental taps.
* Horizontal overflow.
* Long tables and rankings.
* Filter and dropdown accessibility.
* Modal behavior.
* Sticky navigation and headers.
* Back-navigation consistency.
* Authentication transitions.
* Keyboard interaction.
* Safe-area spacing.
* Text readability.
* Loading and error states.
* Route transitions inside the installed app.

Ensure users can perform the same authorized core tasks on mobile as on desktop.
Do not introduce separate, inconsistent navigation systems without a compelling reason.
4.8 — Audit Navigation Accessibility
Validate navigation with appropriate automated and manual accessibility checks.
Include:

* Keyboard navigation.
* Visible focus indicators.
* Logical focus order.
* Correct semantic labels and landmarks.
* Screen reader labels.
* Dropdown and drawer state announcements.
* Escape and outside-dismiss behavior.
* Color contrast.
* Touch target sizing.
* Reduced-motion behavior where relevant.

Accessibility failures should be treated as actual product defects, not optional polish.
4.9 — Create a Proposed Navigation Architecture
After completing the inventory and user-journey audit, develop a coherent proposed information architecture.
Show:

* Existing navigation.
* Proposed navigation.
* Pages moved between categories.
* Pages renamed.
* Missing links to restore.
* Redundant navigation to consolidate.
* Related tools that need contextual links.
* Features that must remain hidden due to access or release gates.
* Changes that require backend or authentication coordination.

Explain each material change based on user tasks and discoverability.
Do not rename or relocate features solely for aesthetic preference.
Keep route URLs stable where practical. If a route must change, preserve safe backwards compatibility or redirects, bookmarks, and relevant internal links.
4.10 — Implement the Improvements
Do not stop after writing an audit report.
Within the established authorization and governance rules, implement justified improvements.
Prioritize:

1. Missing navigation to already-active features.
2. Broken or incorrect destinations.
3. Confusing or misleading labels.
4. Illogical feature placement.
5. Mobile navigation defects.
6. Accessibility failures.
7. Inconsistent page titles and hierarchy.
8. Useful contextual navigation between related tools.
9. Low-risk visual and interaction consistency fixes.

Separate routine safe navigation changes from consequential product redesigns.
Preserve existing permissions, feature flags, private routes, and all business logic.
Coordinate with active frontend claims and the permanent UI development lane.
Do not create a second design system or duplicate feature-navigation components.
4.11 — Regression Testing and Release Verification
Build or extend appropriate automated tests.
At minimum, validate:

* Navigation route inventory and coverage.
* Feature-to-menu mapping.
* Desktop/mobile navigation parity.
* Page-title and menu-label consistency.
* No broken internal destinations.
* Capability and authentication gating.
* Signed-in versus signed-out views.
* Keyboard accessibility.
* Mobile drawer interactions.
* Direct navigation and back-navigation.
* Existing high-priority user journeys.
* Relevant Chrome/Chromium and WebKit behavior.

Test against the actual deployed application once qualified changes are released.
A passing component test does not prove a user can easily find the feature.
Completion requires user-facing verification, not merely a merged navigation PR.
4.12 — Frontend Audit Deliverables
Produce:

1. Complete route and feature inventory.
2. Existing navigation hierarchy.
3. Proposed navigation hierarchy.
4. Discoverability and usability defect register.
5. Prioritized improvement plan.
6. User-journey before/after measurements.
7. Implemented changes with exact PR references.
8. Desktop and mobile acceptance evidence.
9. Accessibility findings and resolutions.
10. Remaining blocked or deferred UI improvements.

Record every identified improvement in the canonical master roadmap, with implementation details and traceability.
PRIORITY 5 — PRESERVE AND ADVANCE VALIDATED MATHEMATICAL IMPROVEMENTS
Continue the existing mathematical research workstreams.
Investigate meaningful improvements to:

* Weekly and ROS projections.
* Dynasty valuation accuracy.
* Replacement-level modeling.
* Lineup optimization.
* Trade recommendations.
* Waiver optimization.
* Source independence and reliability.
* Decision uncertainty and confidence.

Favor incremental accuracy gains over complicated new formulas.
Do not alter production values or promote new models without satisfying the existing evidence requirements.
The frontend workstream must not interfere with the mathematical integrity of these systems.
PRIORITY 6 — MASTER ROADMAP RECONCILIATION
This directive adds a comprehensive frontend information architecture and usability workstream to the existing development campaign.
Discover and follow the canonical planning hierarchy, including:

* `docs/MASTER_PRODUCT_PLAN.md`
* `docs/OWNER_PRODUCT_BACKLOG_SPEC.md`
* `docs/OWNER_FEATURE_INVENTORY.md`
* `docs/OWNER_REQUESTED_TODO.md`
* `docs/EXECUTION_PLAN.md`
* `docs/BRISKET_IDEAS.md`
* `docs/WORK_CLAIMS.md`
* Existing UI design and implementation records.

Reconcile this new request against existing UI commitments, active claims, defects, and already-implemented navigation.
Preserve the full specificity of this directive rather than reducing the frontend audit to a generic TODO such as "improve navigation."
Every proposed or implemented change must have:

* A defined user problem.
* Its intended improvement.
* The canonical frontend owner.
* The affected routes and components.
* Priority and dependencies.
* Implementation authorization.
* Related PRs.
* Measurable acceptance criteria.
* Completion and production verification status.

Do not create a competing master roadmap.
PARALLEL EXECUTION REQUIREMENTS
Coordinate the existing development lanes and add frontend audit work without disrupting active tasks.
Use safe parallel execution where the ownership boundaries permit.
Prioritize:
Immediate operational work: Production security and release blockers.
Immediate product completion: Roster Construction integration and verification.
Parallel frontend work: Full site navigation and usability audit, followed by justified improvements.
Parallel quantitative work: IDP forecasting research and point-in-time validation.
Integration work: Testing, roadmap traceability, independent reviews, release verification and production checks.
Do not merge unreviewed code, bypass CI, overwrite agent work or silently promote held models.
FINAL REQUIRED HANDOFF
Deliver a consolidated evidence-backed report covering:
A. Production Security
Which vulnerabilities or configuration risks were resolved and which remain blocked.
B. Roster Construction
Actual deployment, activation, accuracy, usability and mobile verification.
C. Weekly IDP and Dynasty Intelligence
Measured forecasting improvements, unresolved gaps and downstream recommendation quality.
D. Complete Frontend UX Audit
Every feature and route, navigation placement, missing links, confusing categories, mobile issues, accessibility issues and recommended corrections.
E. Implemented Frontend Improvements
Exact changes, before-and-after navigation hierarchy, PRs, tests and production-verified behavior.
F. Mathematical Integrity
Confirmed preservation of league scoring, dynasty values, source voting, and all held model boundaries.
G. GitHub Integration
Exact open/merged PR states, reviews, required checks, merge order and deployed SHAs.
H. Master Roadmap
Which canonical documents were updated, specific new work items, completion status and traceability.
I. Remaining Blockers
Only genuine unresolved problems, with the evidence and next action required.
J. Next Development Priorities
Rank remaining work by its contribution to predictive accuracy, actionable fantasy decisions, usability, and product reliability.
FINAL OWNER INSTRUCTION
Chase Upside should become a unified fantasy football front-office application.
I do not want to have to remember which agent developed a feature, what technical system powers it, or which obscure menu contains it.
Every feature should be exactly where a reasonable user would expect to find it.
Related tools should feel connected.
The most useful features should be obvious and accessible.
The application should be easy to navigate on both desktop and iPhone.
The interface should be clear enough for a newcomer while still offering the analytical depth an advanced dynasty manager wants.
Do not sacrifice functionality, security, or mathematical accuracy for cosmetic changes.
Audit it, identify what needs improvement, implement justified changes, validate the actual experience, and update our master roadmap.
Continue the established development campaign autonomously within existing authorizations. Finish and verify existing work while advancing the new frontend improvements in parallel.
