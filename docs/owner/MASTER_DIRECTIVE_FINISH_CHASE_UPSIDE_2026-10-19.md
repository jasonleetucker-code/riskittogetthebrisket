MASTER DIRECTIVE — FINISH CHASE UPSIDE ASAP
Risk It to Get the Brisket / Chase Upside
Full-Site Completion, Integration, Deployment & Production Verification
THIS IS A BINDING OWNER DIRECTIVE. HIGHEST EXECUTION PRIORITY.
I want Chase Upside finished as quickly as reasonably possible.
We have spent considerable time building, auditing, researching, planning, redesigning, and creating implementation workstreams. The site has made enormous progress, but I want to transition from an ongoing development project into a polished, reliable, feature-complete production application.
Your mission is to FINISH THE SITE, not continue expanding the development process.
Take ownership of the remaining authorized work and carry it through implementation, integration, testing, merging, deployment, and production verification.
Do not stop after producing a plan.
Do not stop after opening PRs.
Do not stop after tests pass.
Do not declare completion until the actual production website has been verified.
1. Immediately Establish the Real State
Before starting new work, reconcile the current GitHub repository, open PRs, active worktrees, running agents, workflow runs, production build, and completion records.
Specifically investigate the current state of:

* Release trains 8 and 9.
* Source independence PR #1817.
* Trade Calculator TC-E PR #1824.
* Playoff/MOTY PR #1821.
* Playoff franchise-attribution fix #1822.
* Mobile trade-tendencies fix #1823.
* Draft Valuation Batch G.
* Screenshot-import full-page recognition fix.
* Any additional PRs or active implementation branches created since these were recorded.

Treat these as discovery pointers, not assumptions about their current status.
Resolve merge conflicts, reconcile overlapping changes, eliminate duplicate branches, and recover completed work.
Do not rewrite working functionality or create another implementation of something that already exists.
Identify one canonical owner for every shared subsystem.
2. Prioritize Actual Completion Over Planning
Use this order:
P0 — Production correctness and broken functionality
Fix features that crash, fail, hang, miscalculate, display misleading information, fail to load, or behave differently from their approved specification.
P1 — Finish core functionality
Complete the remaining authorized features, particularly Trade Calculator, Trade Finder, Manager Intelligence, valuations, IDP, Draft Capital, Power Rankings, and the league intelligence systems.
P2 — Performance and reliability
Eliminate significant page-load delays, unnecessary calculations, slow API requests, stale results, unstable background jobs, and unreliable production verification.
P3 — Premium UI and usability
Complete our approved Premium Sports Intelligence Direction A redesign everywhere it is still required. Achieve full desktop/mobile parity.
P4 — Final integration and production acceptance
Ensure every subsystem works with every relevant other subsystem, with the expected league and scoring settings, and survives real user interactions.
These priorities determine execution order, not permission to abandon lower-priority authorized requirements.
3. Finish the Trade Calculator Completely
This is one of the site's most important features and should receive immediate attention.
Complete all remaining Trade Calculator workstreams and feature-matrix requirements.
Specifically:

* Fix the approximately one-minute Trade War Room analysis waits. Instrument the actual backend request and eliminate measured bottlenecks.
* Provide meaningful loading, retry, and failure states without losing an assembled trade.
* Make the entire Trade War Room easier to understand for ordinary fantasy football managers.
* Put the actionable recommendation and the few most important reasons first.
* Move technical details, lengthy tables, and detailed methodology into expandable sections.
* Preserve one canonical decision engine and one official verdict.
* Keep our geometric Value Adjustment, `q = 0.78`, as the active model.
* Add a compact comparison of our Value Adjustment and the existing KeepTradeCut adjustment method.
* Extend that optional comparison throughout Second Opinions using each source's proper input values.
* Preserve source independence, fallback provenance, and honest unavailable states.
* Never double-apply or average the two Value Adjustments.
* Complete personalization, trade recommendations, multi-team behavior, package suggestions, simulations, share/import/export, and the remaining approved calculator features.
* Preserve accurate IDP, TEP, Superflex, picks, repeated assets, and manual override handling.

The result should be a trade calculator that is powerful enough for experienced dynasty players but straightforward enough for somebody new to fantasy football.
4. Finish Screenshot Importing
Tesseract 5.3.4 has already been installed on the production VPS.
Do not spend time reinstalling it or investigating a missing binary.
Finish the code-level recognition problem.
Ordinary uncropped screenshots from KeepTradeCut and other supported trade calculators must work.
The existing real-world regression case is:

* Team 1 gets Jaxson Dart.
* Team 2 gets De'Von Achane.
* Bryce Young, Omarion Hampton, advertisements, sidebar content, and unrelated website text must be ignored.

Finish player/pick recognition, trade-region detection, side assignment, ambiguity handling, mobile screenshots, and multi-screenshot behavior.
Verify the feature in production with real screenshots. Preserve screenshot privacy.
5. Finish the Valuation and IDP Work
Implement the decisions already authorized in the October 18 Owner Decision Closeout.
Do not ask me to repeat them.
Maintain:

* Geometric Value Adjustment `q = 0.78`.
* Source-lineage and correlation protections.
* DLF IDP hold unless its approved evidence gate passes.
* Evidence-gated DLF Values rank-to-Hill activation.
* Strict FantasyPros upstream timestamps.
* Honest source availability and confidence.
* Approved rookie/draft valuation rules.
* Complete cross-surface valuation consistency.

Do not promote questionable sources simply to increase the number of votes.
Do not modify mathematical models without satisfying the existing validation rules.
Finish required source evidence, independent challenges, board-impact testing, and production verification.
6. Finish Every Remaining Authorized Non-DFS Feature
Work through the canonical execution plan, requirement manifest, completion dashboard, Calculator Ideas, and active product workstreams.
This includes, but is not limited to:

* Rankings and player profiles.
* Trade Calculator and Trade Finder.
* Manager Intelligence.
* Trade History and Trade Tendencies.
* Draft Capital and Draft Valuation.
* Power Rankings and playoff projections.
* Game Day Command Center.
* Schedule and opponent intelligence.
* Market and player intelligence.
* Adaptive Learning and relevant prediction systems.
* Rookie Auction mock and preparation features.
* System reliability, accessibility, security, and account flows.
* Remaining sitewide Premium UI.

Do not interpret this list as approval to build unrelated new ideas. Finish the explicitly authorized scope first.
For each requirement, determine whether it is implemented, genuinely blocked, or unfinished. Then act accordingly.
Do not let stale planning documents generate duplicate work.
7. Do Not Reopen Settled Decisions
I am delegating routine technical implementation decisions to you.
When the evidence supports a safe, reversible, well-established solution, choose the solution that is best for the site and proceed.
Prioritize:

1. Accuracy.
2. Reliability.
3. User experience.
4. Performance.
5. Maintainability.
6. Reasonable operating cost.

Only return to me when a decision genuinely requires owner-only authority, new spending, credentials, official league policy, or an intentional change to a locked methodology.
Existing decisions remain binding.
DFS IMPLEMENTATION IS SHELVED.
LEAGUE TYCOON IMPLEMENTATION IS SHELVED.
Do not implement either until explicitly resumed.
Preserve existing features and research.
Do not initiate paid data subscriptions, paid inference, or write actions against Sleeper without explicit authorization.
Do not launch the official 2027 rookie auction prematurely.
8. Parallelize Aggressively but Intelligently
Use multiple specialized agents and worktrees when they actually accelerate completion.
Divide work along independent canonical ownership boundaries.
Do not assign two agents to edit the same shared files simultaneously.
Run independent backend, frontend, UI, evidence, and testing work in parallel where safe.
Respect machine resources: avoid running so many agents or tests simultaneously that the server becomes slower or tests fail from resource contention.
The goal is the shortest safe path to a finished product, not the highest number of active agents.
Finish and integrate work in continuous, dependency-safe batches.
Do not build unnecessary infrastructure for managing the development process itself.
9. Accelerate the Release Process Without Lowering Standards
Use release trains when several related PRs should be tested together.
Resolve conflicts promptly.
Run targeted tests early, broader tests on integration candidates, and mandatory release checks on the exact candidate head.
Preserve required review, CI, E2E, security, and release gates.
Do not bypass a failing gate to merge sooner.
Do not repeatedly rerun an unchanged test suite unless needed for credible evidence.
Once an authorized release candidate is green:

1. Merge it through the approved GitHub workflow.
2. Verify its component PRs are accounted for.
3. Deploy through the existing production workflow.
4. Confirm the actual served commit.
5. Test the relevant features on the live site.
6. Record results and move to the next batch.

Do not confuse a successful unit test, merged PR, or successful deployment with completed production acceptance.
10. Address Existing Production Problems, Not Just Unfinished Features
Actively resolve defects surfaced by actual site usage.
Prioritize observed failures over speculative enhancements.
Examples already reported:

* Screenshot imports identifying unrelated page content as assets.
* Trade War Room analysis taking far too long or failing to load.
* Overly technical and cluttered trade analysis.
* Missing Trade Tendencies information on mobile.
* Playoff/forecast identity issues after manager replacement.
* Slow page interactions or redundant calculations.
* Source voting and confidence inconsistencies.

Fix the underlying causes rather than applying cosmetic workarounds.
11. Finish the UI Across the Entire Site
The approved direction remains Premium Sports Intelligence Direction A.
Preserve:

* Cream, dark ink, and restrained rust-red palette.
* Dense, readable, high-information layouts.
* Minimal corner radii and thin dividers.
* Professional tables and typography.
* Strong accessibility and contrast.
* Consistent desktop and mobile functionality.

Eliminate unfinished design inconsistencies, excessive jargon, redundant explanations, broken mobile layouts, clipped tables, confusing controls, and unnecessary page clutter.
Use plain-English explanations by default with technical details available on demand.
A completed backend with a confusing or broken user interface is not a completed feature.
12. Create a Finite Completion Queue
Create one authoritative completion queue, not another sprawling collection of plans.
Each remaining item should contain:

* Feature or defect.
* Priority.
* Canonical owner.
* Current code/PR status.
* Exact remaining implementation.
* Required tests and production evidence.
* Dependencies.
* Whether an external or owner-only blocker genuinely exists.

Remove duplicates and close stale decisions.
Group related work into practical finishable batches.
Don't create new workstreams for items that can be completed inside existing ones.
The queue must shrink as work ships.
Do not inflate the requirement count with every newly discovered technical subtask.
However, do not hide genuine unfinished work or mark something completed merely to improve the dashboard.
13. Give Me Useful Progress Updates
I don't need a running transcript of every command or internal agent action.
Instead, report:

* What actually shipped.
* What is currently being completed.
* What failed and is being repaired.
* What is next.
* What genuinely requires my involvement.

Whenever possible, include actual PR numbers, deployment commits, test outcomes, and production verification.
Don't repeatedly ask me whether you should continue.
Continue automatically through the remaining authorized queue.
If execution must stop because of a session or tool limitation, leave a durable, exact resumption record with branch names, unmerged commits, gate results, and the next executable action. Never claim work will continue after the session ends unless an actual scheduled or persistent process is running.
14. Definition of DONE
Chase Upside is not finished simply because the major features exist.
For the currently authorized non-DFS scope, completion means:

* Every in-scope feature has reached its defined acceptance criteria.
* No known critical or high-priority production correctness defect remains unresolved.
* Trade and player valuations agree across their relevant surfaces.
* Important user journeys work on desktop and mobile.
* Required performance and reliability gates pass.
* CI and scheduled workflows are healthy or have clearly documented, justified exceptions.
* Authentication and privacy boundaries are verified.
* Production displays the intended final build.
* Outstanding owner decisions are either already resolved or truly require owner-only action.
* Deferred features remain explicitly deferred rather than falsely completed.
* The completion dashboard is reconciled with actual implementation and live evidence.

If an external dependency is genuinely unavailable, isolate it and clearly distinguish that blocked feature from the rest of the site. Do not hold the entire completion campaign hostage to something nobody can presently resolve.
FINAL INSTRUCTION
START EXECUTING IMMEDIATELY.
Do not respond with only an audit, roadmap, or implementation proposal.
Do not restart previous work.
Do not endlessly research alternatives when a sound technical decision can be made.
Reconcile what already exists, fix what is broken, finish what remains, integrate it, test it, merge it, deploy it, and verify it.
Work in the fastest safe sequence until the authorized site-completion criteria are satisfied or genuinely external blockers prevent further progress.
I want Chase Upside to become a finished, dependable, premium dynasty football application—not a permanent development project.
Make completion the overriding operational priority.
