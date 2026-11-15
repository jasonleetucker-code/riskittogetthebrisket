# OWNER DIRECTIVE (verbatim) — 2026-10-19 — Get Signals Fantasy IDP Fully Voting

CLAUDE IMPLEMENTATION PROMPT

Get Signals Fantasy IDP Fully Voting in the Risk It to Get the Brisket Calculator

Repository: jasonleetucker-code/riskittogetthebrisket

Priority: HIGH — Active implementation request

Objective: Make Signals Fantasy's IDP dynasty valuations fully functional, trustworthy, and actively voting in our canonical dynasty valuation system.

PRIMARY OWNER DIRECTIVE

I want Signals Fantasy to be a real, contributing valuation source for all three defensive position families:

* Defensive Line (DL): DT and DE
* Linebackers (LB)
* Defensive Backs (DB): CB and S

Signals' offensive valuations are already integrated and configured to vote. Preserve that functionality.

Its IDP boards are already collected, but currently operate in shadow mode because the previous shared-market translation methodology failed production validation.

Your job is to identify and resolve the issues preventing Signals IDP from voting, implement the best validated solution, and activate voting for every defensive family that passes the required acceptance criteria.

Do not stop at a research report.

Do not stop after identifying a better formula.

Do not stop after creating another shadow candidate.

Follow the entire implementation process through testing, review, deployment where authorized, and production verification.

If a family cannot pass the required validation, leave that family in shadow mode, document exactly why, and complete every other portion of the work that can safely proceed.

The goal is active voting for all three families, but never manufacture validation results or weaken safeguards simply to achieve activation.

⸻

PHASE 1 — UNDERSTAND THE CURRENT IMPLEMENTATION

Before modifying anything, audit the existing Signals integration and canonical valuation architecture.

Start with:

* src/sources/signals.py
* src/api/data_contract.py
* src/bridges/ladder.py
* src/bridges/descriptor.py
* src/api/feature_flags.py
* scripts/verify_signals_onbox.py
* scripts/fetch_signals_values.py
* .github/workflows/signals-onbox-verification.yml
* config/sources/source_lineage.json
* config/sources/freshness_v1.json
* docs/sources/SIGNALS_FANTASY_INTEGRATION.md

Also inspect the relevant tests, existing source-quality work, IDP bridge diagnostics, release procedures, and current repository instructions.

Follow the repository's existing engineering and implementation-governance conventions.

Determine the exact current state of:

1. Signals authenticated offense and IDP collection.
2. Player identity matching and position normalization.
3. Native IDP valuation storage.
4. DL/LB/DB positional ranking.
5. Shared-market translation.
6. Canonical source registration.
7. Feature flags and voting holds.
8. Source freshness and effective weights.
9. Outlier rejection.
10. Correlation-family weighting.
11. Source-health monitoring.
12. Production deployment and rollback.

Verify current code and production configuration rather than treating historical documentation as proof of current behavior.

Preserve existing functionality

Do not break Signals offense voting, the canonical valuation engine, existing source integrations, IDP Trade Calculator, Draft Sharks, or existing league scoring.

Do not create a separate Signals-specific valuation engine.

Signals must contribute through the same authoritative aggregation system as other legitimate voting sources.

⸻

PHASE 2 — REPRODUCE AND DIAGNOSE THE FAILED OCTOBER 17 TEST

The repository documents an October 17, 2026 production evaluation of Signals IDP Candidate A.

Its results included:

Measurement	Previous result
IDP players moving	343 of 396
Median value movement	1.37%
90th-percentile movement	30.07%
Signals IDP outlier drops	2.9%
LB signed bias	−6.24%
DB signed bias	−9.95%
Offensive player rows moving	1
Scorable completed IDP trades	0

The previous implementation failed the movement and signed-bias validation criteria.

Do not simply switch signals_idp_shared_market to True.

Reproduce the previous results where possible and investigate the actual reasons for failure.

Specific investigations

A. Defensive Line movement

Determine why DL value movement becomes extreme in the distribution's tail.

Separate:

* Ranked players versus unranked or deep-tail players.
* Absolute value movement versus relative movement.
* Players losing or gaining their first qualifying voting family.
* Sparse-evidence adjustments.
* Outlier-filter changes.
* Changes to source coverage.
* Changes introduced by the positional crosswalk.

Identify the precise mechanism rather than blaming all large percentage moves on low starting values.

B. Linebacker bias

The previous signed-bias result was −6.24%.

Determine whether that represents:

* Genuine independent Signals disagreement.
* Incorrect rank translation.
* Different player populations.
* Incorrect normalization.
* A problem with the reference market.
* An aggregation or weighting defect.

Do not automatically normalize away genuine disagreement.

C. Defensive Back bias

The previous signed-bias result was −9.95%.

The documentation identifies a coverage mismatch: Signals included defensive backs absent from the bridge reference.

Investigate whether that mismatch is causing rank displacement.

Test coverage-aligned translation without guessing missing player values.

D. Offensive player changes

The previous experiment unexpectedly moved one offensive player.

Investigate two-way-player handling, including Travis Hunter, and determine whether the movement is a defect or a legitimate, explicitly modeled dependency.

Prevent unintended cross-position contamination without breaking correct two-way-player calculations.

E. Outlier and family-count interactions

Measure whether the inclusion of Signals changes:

* Hampel eligibility and rejection outcomes.
* Trimmed versus untrimmed aggregation.
* Independent evidence-family counts.
* Confidence calculations.
* Single-source adjustments.
* Other sources' effective contributions.

Do not assume a small Signals weight guarantees a small board impact.

Produce a reproducible root-cause report.

⸻

PHASE 3 — INVESTIGATE SIGNALS' NATIVE LEAGUE-SPECIFIC VALUES

This investigation takes priority over inventing another positional translation formula.

Signals Fantasy offers league-specific fantasy valuation capabilities.

Determine whether its authenticated application produces a usable, same-scale valuation for offensive and defensive players under a common league configuration.

This is a hypothesis to investigate, not an established fact.

Research requirements

Inspect the authenticated data flow available to our existing, authorized integration.

Determine:

1. Whether league-specific player valuations exist as retrievable observations.
2. Whether IDP and offense genuinely share one valuation scale.
3. Whether the output supports DT, DE, LB, CB, and S.
4. Whether it accepts or derives exact Sleeper league scoring.
5. Whether roster requirements, positional scarcity, or replacement levels are applied.
6. Whether the values are returned by a service or independently calculated in the browser.
7. Whether the values are derived from FantasyCalc, KTC, or another source already in our system.
8. Whether Signals provides an independent IDP opinion or largely republishes another market.
9. Whether the output is reproducible across collection runs.
10. Whether its data lineage, format, publication timestamps, and licensing constraints permit canonical use.

Use existing authorized access. Do not bypass access controls, payment requirements, or authentication restrictions.

Do not collect or publish credentials, session cookies, or protected raw values in public GitHub output.

Important valuation distinction

An identical numerical scale does not establish that values are comparable.

If offense and IDP both use a scale from 0–10,000, that is not proof that 5,000 represents the same dynasty trade value across the two universes.

Verify the economic meaning of the scale.

Similarly, do not treat league-specific fantasy point projections as dynasty trade values.

Projection, lineup utility, and dynasty market value are different quantities.

Decision

If a valid, accessible, genuinely comparable native valuation exists, develop and evaluate that candidate.

If it is not accessible, reproducible, or trustworthy, explicitly reject that approach and continue with a repaired positional translation.

Do not let an unavailable native-value route block improvements to the existing integration.

⸻

PHASE 4 — DEVELOP BETTER TRANSLATION CANDIDATES

The current implementation uses Signals' within-family rankings and translates them through a shared-market family ladder.

Preserve the principle that Signals provides an ordering within each defensive family unless stronger cross-family evidence is established.

Do not falsely infer that Signals' LB1 must be worth more or less than Signals' DE1 simply because their vendor-native values are numerically similar.

Candidate 1 — Coverage-Aligned Crosswalk

Develop a translation based on reliably matched players shared by Signals and the eligible reference market.

Requirements:

* Use canonical Sleeper player identities.
* Separate DL, LB, and DB.
* Align the reference population appropriately.
* Prevent missing players from shifting every subsequent rank incorrectly.
* Preserve valid within-family order.
* Withhold unsupported extrapolations.
* Avoid changing a player's source value simply to force agreement with consensus.

Investigate whether this resolves the defensive back coverage-bias problem.

Candidate 2 — Independent Shared-Market Reference

Investigate using qualified cross-position valuation evidence from multiple sources.

Potential references include:

* IDP Trade Calculator.
* Draft Sharks.
* Other existing sources that have demonstrably comparable offense/IDP market relationships.

Do not automatically assume a source is independent.

Inspect lineage, shared inputs, scoring models, and underlying valuation ancestry.

If Draft Sharks qualifies as a second useful reference, determine whether it can help validate the translation independently.

Do not change global multi_bridge_ladder behavior simply to get Signals voting. That is a separate methodology decision affecting other sources.

Candidate 3 — Validated Monotonic Mapping

Investigate a constrained monotonic mapping from Signals' within-family ranks into the shared-market value coordinate.

Possible methods include:

* Isotonic regression.
* Coverage-adjusted percentile mapping.
* Shrinkage-based monotonic calibration.
* Other mathematically justified methods.

Avoid unnecessary complexity.

Do not introduce flexible fitted models without sufficient independent evidence.

Any fitted relationship must be evaluated using different observations, reference sources, or time periods from those used to fit it.

Candidate 4 — Completed-Trade-Informed Calibration

Use the existing completed-trade ledger where sufficient comparable evidence exists.

Do not use raw trade counts without verifying trade quality.

Require:

* Dynasty league format comparability.
* IDP scoring compatibility or validated transformation.
* Deduplication by underlying trade identity.
* Protection against one league or manager dominating the sample.
* Separate DL/LB/DB population evidence.
* Chronological separation of training and validation.
* Appropriate treatment of multi-asset transactions.
* The canonical Value Adjustment-inclusive trade comparison where relevant.

Retain existing sample eligibility safeguards.

If trade evidence is insufficient, mark the candidate unsupported rather than inventing a valuation.

Candidate management

The repository already documented Candidates A through E.

Do not retroactively redefine a failed candidate as successful.

Register new candidates with distinct identities and preregistered methodology before testing them against new evaluation data.

No tuning acceptance thresholds after seeing results.

⸻

PHASE 5 — EVALUATE WHAT SIGNALS ACTUALLY CONTRIBUTES

I do not want Signals to be forced to agree with the other sources.

I want its independent information to be represented accurately.

Distinguish three possible outcomes:

1. Bad translation

Signals' ranking opinion is valid, but our translation assigns an unjustified numerical value.

Repair the translation.

2. Genuine disagreement

Signals differs from our other valuation sources, and the disagreement is supported by legitimate independent evidence.

Preserve the disagreement and let the existing aggregation, weighting, and outlier systems handle it.

3. Untrustworthy observation

Signals' data is stale, incorrectly mapped, unsupported, or internally inconsistent.

Withhold that specific observation.

Do not assume consensus agreement is proof of correctness.

Do not use disagreement alone to justify excluding Signals.

Likewise, do not call a mathematically consistent translation trustworthy without validation of its market-scale interpretation.

Measure whether adding Signals improves independent evidence quality or merely creates another correlated vote.

⸻

PHASE 6 — INDEPENDENT VALIDATION AND ACCEPTANCE CRITERIA

Run each promising candidate in shadow mode against the canonical production-shaped dataset.

Use the October 17 failed implementation as an explicit comparison baseline.

Retain the established acceptance requirements unless a separately preregistered methodological change provides a defensible reason for different criteria.

Existing numerical safeguards

* IDP median relative movement: no greater than 2%.
* IDP p90 relative movement: no greater than 8%.
* Per-family median signed contribution bias: within ±5%.
* Signals outlier rejection: no greater than 5%.
* Overall top-200 family-share movement: no greater than 3 percentage points per family.
* No unsupported changes to offensive player values.
* No invented shared-market ordering.
* No unsupported ladder extrapolation.

Additional requirements:

* No duplicate source observations.
* No wrongly matched players.
* No positional-family mismatches voting.
* No stale or invalid observations voting.
* No unjustified inflation of confidence.
* No prohibited source lineage duplication.
* No material deterioration in independently evaluated trade outcomes.

Investigate the practical effect on:

* Elite IDP players.
* Mid-tier starters.
* Bench players.
* Deep-tail players.
* IDP rookies.
* Rookie-tethered picks.
* Two-way players.

Independent validation

Where possible, use eligible held-out completed trades and other independent market evidence.

Track whether enough evidence exists to draw meaningful conclusions.

Do not present absence of contradictory evidence as affirmative validation.

If the October 17 acceptance limits are unsuitable for a newly developed method, document a prospective revised gate with a specific justification and evaluate it on data not used to choose the revision.

Do not silently waive failed tests.

Required result

Produce a per-family validation report containing:

* Candidate methodology.
* Dataset and version.
* Source coverage.
* Identity match rate.
* Effective voting coverage.
* Outlier drop rate.
* Signed contribution bias.
* Value movement distribution.
* Rank movement distribution.
* Confidence changes.
* Family composition changes.
* Trade evidence.
* Known limitations.
* PASS / FAIL / INSUFFICIENT verdict.

Clearly separate engineering correctness from empirical valuation quality.

⸻

PHASE 7 — INDEPENDENT DL, LB, AND DB PROMOTION

The current signals_idp_shared_market feature flag governs all three defensive families together.

I want independent family-level activation, while retaining compatibility with existing behavior and rollback controls.

Implement independently controllable activation for:

* Signals DL
* Signals LB
* Signals DB

Use the repository's established feature-flag and source-vote-state architecture.

Do not create a parallel configuration system.

Why this matters

If DL passes all applicable requirements but LB fails, DL should not be held back solely because LB remains unvalidated.

Likewise, a validated DB model should be able to vote independently.

Each family must have:

* Its own activation state.
* Its own qualification evidence.
* Its own current source-health status.
* Its own shadow-vs-voting comparison.
* Its own rollback path.

Preserve the existing global Signals rollback capability.

Activate qualified families

When a defensive family passes all required tests and independent review, complete the approved rollout process and enable voting for that family.

Verify that it is not merely marked enabled, but actually contributes to canonical player values.

A feature flag being True is not sufficient proof.

Verify:

* Source is present.
* Source is fresh enough to contribute.
* Source has qualifying matched rows.
* Source is not held.
* Source has nonzero effective voting contribution where appropriate.
* Canonical values change as expected.
* Rankings source metadata correctly reports voting status.

For families that fail, keep collecting and evaluating their observations in shadow mode.

Do not enable an unqualified family simply because another family passed.

⸻

PHASE 8 — SOURCE WEIGHTING AND INDEPENDENCE

Signals IDP should participate through our existing source aggregation architecture.

Its effective voting authority must respect:

* Current source base weights.
* Freshness weighting.
* Health weighting.
* Coverage weighting.
* Correlation-family caps.
* Outlier filtering.
* Existing confidence rules.

Do not add an artificial Signals-specific bonus.

Do not increase its weight merely because we invested time implementing it.

Source independence

Inspect the existing relationship between Signals Fantasy and FantasyCalc.

Signals offense is currently grouped with FantasyCalc for correlation control.

The IDP boards currently share that declared group even though FantasyCalc has no IDP observations.

Determine whether the existing family classification remains valid based on observed ancestry.

Avoid double-counting correlated information.

Do not assign multiple independent family votes to DL/LB/DB merely because they are represented by three source keys.

On a given player row, only the applicable Signals defensive family should contribute.

⸻

PHASE 9 — PRODUCTION COLLECTION AND AUTHENTICATION

Inspect the actual production collection infrastructure.

The repository uses the dynasty-signals-values service and timer.

The previous October 17 verification recorded the authentication state as renewal_due.

Determine whether authentication and scheduled collection are currently healthy.

Verify:

1. Service and timer are installed and active.
2. Authenticated collection succeeds.
3. Session renewal behaves correctly.
4. All three IDP family boards are produced.
5. Publication timestamps are recorded correctly.
6. Source freshness is based on genuine upstream publication evidence.
7. Last-good snapshots are preserved during collection failures.
8. Incomplete releases are quarantined.
9. No failed scrape refreshes a success clock incorrectly.
10. Warnings and health monitoring detect source degradation.

Signals IDP is believed to follow a roughly weekly publication cadence. Verify actual observed behavior rather than assuming every six-hour collection represents updated values.

Do not loosen freshness safeguards solely to prevent stale-data warnings.

Do not expose paid Signals observations, player-specific values, or credentials through public GitHub logs and artifacts.

⸻

PHASE 10 — TESTING AND REGRESSION

Add or update automated tests for:

Data correctness

* Correct Sleeper ID matching.
* Correct DT/DE → DL mapping.
* Correct CB/S → DB mapping.
* Correct LB mapping.
* Duplicate-player rejection.
* Vendor-family mismatch rejection.
* Invalid and missing valuation handling.
* Stale-data handling.

Mathematical correctness

* Monotonic within-family ranking.
* Shared-market coordinate integrity.
* Correct coverage alignment.
* No fabricated cross-family ordering.
* No unsupported extrapolation.
* Stable and reproducible mappings.
* Deep-tail behavior.
* Outlier handling.
* Source-family weighting.

Voting correctness

* DL independently enabled.
* LB independently enabled.
* DB independently enabled.
* One family disabled while others vote.
* Global Signals rollback.
* Missing Signals data.
* Expired Signals data.
* Failed collection.
* Correct source voting metadata.
* Actual nonzero contribution on eligible rows.

Downstream regression

Verify that approved Signals votes flow through canonical values into existing consumers, including:

* Rankings.
* Trade Calculator.
* Trade Finder.
* Second Opinions.
* Trade history and historical analysis, using their correct point-in-time methodology.
* Source-quality reporting.
* Other applicable valuation-dependent features.

Do not separately implement Signals calculations in each feature.

All downstream features should consume the authoritative canonical system.

Preserve current Value Adjustment and league-specific adjustments.

⸻

PHASE 11 — SAFE ROLLOUT

Use the existing deployment and verification infrastructure.

Sequence:

1. Audit the current implementation.
2. Reproduce the failed baseline.
3. Investigate the native same-scale valuation hypothesis.
4. Diagnose the existing failures.
5. Preregister improved candidates.
6. Implement candidate calculations.
7. Run production-shaped shadow comparisons.
8. Obtain independent review.
9. Complete required validation.
10. Add independent family promotion controls.
11. Merge and deploy qualifying implementations through the established process.
12. Enable voting for qualified families.
13. Verify actual contributions on the live canonical board.
14. Confirm public/private data protections.
15. Verify rollback.
16. Produce a final source-status report.

Do not publish experimental candidate values as canonical until they qualify.

Do not leave old feature-flag behavior ambiguous.

Do not create a permanent shadow-only project with no explicit remaining path to voting.

If an external dependency prevents full completion, finish all independent engineering work, retain safe defaults, and identify the exact blocked step.

⸻

PHASE 12 — FINAL DELIVERABLES

When finished, report the actual status of every defensive family.

Use this format:

Family	Collection	Validation	Voting	Remaining blocker
DL	Actual status	PASS/FAIL	ON/OFF	Exact blocker
LB	Actual status	PASS/FAIL	ON/OFF	Exact blocker
DB	Actual status	PASS/FAIL	ON/OFF	Exact blocker

Also provide:

1. Root-cause findings

Explain exactly why the October 17 implementation failed.

2. Native-value investigation

State whether Signals supplies an accessible, trustworthy league-specific valuation suitable for our canonical system.

3. Selected methodology

Explain which translation or native-value approach was implemented and why it was chosen over alternatives.

4. Independent validation

Show the actual acceptance results, including failures and insufficient evidence.

5. Implementation changes

Identify files modified, shared services reused, and feature flags introduced or changed.

6. Production status

Confirm which Signals IDP families are actually voting in production.

Distinguish configured voting from verified nonzero contribution.

7. Testing

List relevant test suites, results, and any failures.

8. Security and privacy

Confirm that Signals' private values and authenticated session data have not been exposed.

9. Pull requests and commits

Provide exact references for the implementation.

10. Remaining work

For any family still held from voting, specify exactly what evidence, engineering correction, or external dependency is needed to activate it.

Do not describe work as deployed or complete without verification.

⸻

NONNEGOTIABLE REQUIREMENTS

1. The goal is active Signals IDP voting, not indefinite research.
2. All three defensive families must be pursued.
3. Promote each family independently when fully validated.
4. Do not blindly enable the existing failed translation.
5. Investigate native league-specific values before committing to another crosswalk.
6. Preserve Signals' actual independent opinion.
7. Do not artificially force Signals to agree with other sources.
8. Do not manufacture cross-family rankings.
9. Do not weaken validation criteria to force a passing result.
10. Use independent evidence and avoid circular validation.
11. Preserve the existing canonical valuation engine.
12. Preserve offense voting and unrelated source behavior.
13. Keep private Signals data out of the public repository.
14. Use existing deployment, testing, and monitoring infrastructure.
15. Complete the implementation and activate voting wherever qualification is demonstrated.

FINAL OWNER INSTRUCTION

I want Signals Fantasy to become a fully trusted and actively participating source in our dynasty valuation system, including defensive linemen, linebackers, and defensive backs.

We already invested in building its authenticated collection, source integration, and valuation infrastructure.

Now finish the work necessary to make the defensive half useful.

Do the investigation, fix the methodology, validate it rigorously, implement the changes, and get every defensibly qualified Signals IDP family voting.

If the existing methodology cannot be made trustworthy, replace that methodology with a validated alternative rather than simply leaving the integration unfinished.

Do not sacrifice valuation accuracy to force activation.

Do not settle for another research document.

Proceed with the full engineering implementation using the actual repository and production verification procedures.
