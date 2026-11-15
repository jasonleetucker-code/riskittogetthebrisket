OWNER DIRECTIVE — UNIVERSAL SOURCE VOTING AND FRESHNESS POLICY

Repository: jasonleetucker-code/riskittogetthebrisket
Website: chaseupside.com
Priority: P0 — Valuation Accuracy and Source Voting

I am clarifying and updating my source-voting philosophy for Chase Upside. These decisions supersede any conflicting portions of earlier source-voting directives.

My goal is simple: I want every legitimate dynasty ranking source we collect to contribute to our consensus valuations.

The reason I gathered all these different sources is because I want their opinions represented. I do not want legitimate sources sitting on our website without voting simply because they agree with other websites, disagree with other websites, or have not updated in the last few days.

I want source freshness to determine how much influence a source receives, with a maximum age of 30 days.

Implement the following policy throughout the entire dynasty valuation system.

--------------------------------------------------
1. RESTORE DLF IDP VOTING
--------------------------------------------------

I explicitly approve restoring voting eligibility for:

- dlfIdp
- dlfRookieIdp

The previous owner-policy hold on these sources is rescinded.

DLF should contribute to our defensive consensus whenever its information is valid, compatible with our valuation system, and no more than 30 days old.

DLF's offensive rankings should continue voting as well.

Preserve the existing DLF provider-family safeguards so separate boards from the same provider do not accidentally receive duplicate weight for the same underlying player observation.

Investigate and correct the outlier-filter interaction that previously caused significant IDP value movements when DLF became another voter.

Do not indefinitely exclude DLF simply because another part of our valuation methodology needs improvement.

--------------------------------------------------
2. IMPLEMENT A UNIVERSAL FRESHNESS SCHEDULE
--------------------------------------------------

Replace the current cadence-relative freshness weighting for dynasty ranking sources with the following weekly schedule:

Days since last genuine rankings update:

0–7 days: 100% voting power
8–14 days: 75% voting power
15–21 days: 50% voting power
22–30 days: 25% voting power
More than 30 days: 0% voting power

These percentages multiply each source's existing approved base weight.

For example, a source with a base weight of 1.0 would receive:

Week 1: 1.00
Week 2: 0.75
Week 3: 0.50
Week 4: 0.25
After 30 days: 0.00

A source publishing new, valid rankings immediately returns to 100% of its approved base weight.

The freshness clock must be based on the publisher's actual rankings update, not when our scraper last downloaded the information.

Downloading unchanged rankings does not reset freshness.

A genuine new publication does not require every player's ranking to change. However, we must have credible evidence that the provider actually published or revised the rankings.

If a publisher's update timestamp is unavailable, use a defensible, recorded observation of actual content changes. Do not fabricate update dates or reset the clock just because a request succeeded.

Apply this schedule to offense, IDP, and rookie dynasty ranking sources.

Preserve legitimate seasonal inactivity for rookie boards between draft classes.

No dynasty ranking source should receive voting power when its latest genuine update is more than 30 days old.

--------------------------------------------------
3. EVERY LEGITIMATE SOURCE GETS A VOTE
--------------------------------------------------

A source should be eligible to vote when:

- It publishes genuine dynasty rankings or player valuations.
- Its data is successfully collected and usable.
- Player identities are correctly matched.
- Its scoring format is compatible or can be accurately normalized.
- Its rankings were genuinely updated within the last 30 days.
- It passes reasonable data-quality and integrity safeguards.
- It is not merely an additional feed duplicating the same provider's underlying observation.

Agreement between two different websites is not grounds for removing either vote.

Disagreement between two different websites is not grounds for removing either vote.

Do not assume one website copied another simply because their rankings are similar or identical.

If there is credible evidence of actual shared underlying data, document that evidence and apply the appropriate provider-lineage protections.

Otherwise, allow both legitimate sources to contribute at their approved weights.

Do not give sources extra voting power simply because they agree.

Do not remove voting power simply because they disagree.

Preserve safeguards against incorrect identities, mismatched scoring formats, genuinely duplicated feeds, corrupted data, and invalid observations.

--------------------------------------------------
4. IDP TRADE CALCULATOR AND IDP SHOW
--------------------------------------------------

Both IDP Trade Calculator and The IDP Show should be eligible to vote.

Do not combine their voting power merely because their rankings are similar.

Do not exclude IDP Trade Calculator's offensive values solely because we cannot prove how independently those values were created.

If IDP Trade Calculator publishes valid offensive values, those values should participate under the same rules as other eligible offensive sources.

If The IDP Show publishes fresh, valid combined offense and IDP rankings, those rankings should participate.

Continue using source-lineage diagnostics, but do not allow numerical similarity alone to suppress votes.

Avoid counting multiple boards from The IDP Show as separate votes when they represent the same provider's underlying rankings.

--------------------------------------------------
5. REVIEW ALL 26 REGISTERED RANKING SOURCES
--------------------------------------------------

Audit every registered dynasty ranking source.

For each source, identify:

- Source name
- Source key
- Provider
- Offense, IDP, rookie, or combined coverage
- Last genuine publisher update
- Days since that update
- Freshness voting percentage
- Approved base weight
- Actual effective voting weight
- Number of players receiving a contribution
- Whether the source is currently voting
- Exact reason if it is not voting
- What is required to restore voting eligibility

Identify every source currently excluded by an older policy.

Reevaluate those exclusions under this new owner directive.

My default preference is to restore legitimate sources to voting, not keep them permanently sidelined.

However, do not fabricate voting contributions from sources whose information cannot be accurately normalized or whose data is missing or invalid.

For Signals Fantasy IDP, finish the necessary shared-market normalization and independent validation so those sources can eventually participate correctly.

Do not silently activate mathematically incompatible data.

--------------------------------------------------
6. FIX THE IDP OUTLIER-FILTER PROBLEM
--------------------------------------------------

The current valuation system has a problem where adding a fourth defensive source can activate the outlier filter and suddenly remove another source's opinion.

I do not want valid disagreements automatically treated as bad information.

Investigate this behavior throughout the valuation pipeline.

Distinguish genuine data errors from legitimate differences of opinion.

Evaluate a method that retains valid source opinions while protecting the consensus from corrupted, misidentified, or improperly normalized information.

A source should not be removed simply because its ranking is significantly higher or lower than the others.

For example, if three sites value a player around 5,000 and Draft Sharks values him at 3,000, that does not automatically mean Draft Sharks is wrong.

Its opinion may contain useful information.

We should preserve valid disagreement rather than automatically discard it.

Any material changes to the outlier-filter mathematics must undergo reproducible comparisons, adversarial testing, and independent validation before production activation.

Do not allow restoring DLF to create unexplained 40–50% player-value changes.

Do not hide legitimate player-value changes either. Explain what caused them.

--------------------------------------------------
7. KEEP SOURCE WEIGHTS CONSISTENT
--------------------------------------------------

Preserve the approved base weights unless an existing owner-approved methodology explicitly requires otherwise.

Freshness should multiply those weights.

Do not secretly boost or penalize particular websites because they agree or disagree with the consensus.

Do not create duplicate voting authority from multiple representations of the same provider's underlying data.

Preserve approved provider-family protections.

A source's actual contribution should be explainable from:

- Its approved base weight
- Its freshness percentage
- Its data eligibility and quality
- Its applicable provider-family treatment

If another weighting factor remains necessary, document exactly what it does and why.

No hidden weighting rules.

--------------------------------------------------
8. UPDATE SOURCE HEALTH AND SETTINGS
--------------------------------------------------

Make source voting easy to understand throughout Chase Upside.

The Settings and Source Health pages should clearly show:

Source
Last Updated
Freshness
Voting Weight
Status

Use straightforward status labels:

Active — 100%
Active — 75%
Active — 50%
Active — 25%
Stale — Not Voting
Data Issue — Not Voting
Seasonal — Not Voting
Testing — Not Voting

Users should be able to see why a source is voting or not voting.

Avoid unnecessarily technical explanations.

More detailed information can remain accessible through expandable sections.

If a source is being collected successfully but its actual rankings have not changed in more than 30 days, it should clearly show as stale rather than fresh.

--------------------------------------------------
9. VALIDATE THE ENTIRE VALUATION SYSTEM
--------------------------------------------------

Before deployment, compare the current production valuation board against the proposed methodology.

Measure:

- Total offensive players affected
- Total IDP players affected
- Rookie values affected
- Draft pick values affected
- Median value changes
- 90th percentile changes
- 99th percentile changes
- Maximum value changes
- Largest individual movers
- Position-specific changes
- Top-50 and top-200 ranking changes
- Number of voting sources per player
- Actual effective source weights
- Outlier-filter behavior
- Single-source penalty behavior
- Source-family contribution totals
- Confidence changes
- Effects on two-way players such as Travis Hunter

Investigate unexpected or extreme changes.

Verify that no source older than 30 days contributes to the consensus.

Verify that a legitimate fresh source gets its full approved base weight, subject only to documented quality and provider-family limitations.

Verify that adding a valid new source does not unexpectedly remove other legitimate opinions.

Verify that every eligible source is actually capable of influencing the canonical consensus.

Verify that rankings, player profiles, the Trade Calculator, Trade Finder, Trade History, Second Opinions, and other valuation-dependent surfaces use the correct canonical values.

Preserve the approved geometric Value Adjustment model, q = 0.78.

Do not modify the Trade Calculator's Value Adjustment methodology as part of this source-voting change.

--------------------------------------------------
10. IMPLEMENT WITHOUT DELAYING THE REST OF THE SITE
--------------------------------------------------

Apply this directive to PR #1817 and all relevant source-voting implementation work.

This directive supersedes conflicting D1, D2, and D3 decisions and any older freshness methodology that conflicts with the new schedule.

Preserve unrelated owner decisions.

Coordinate with existing PRs and release trains.

Do not create duplicate implementations or competing valuation engines.

Use the canonical source registry, freshness owner, weighting pipeline, and valuation pipeline.

Complete targeted testing, independent review, full integration validation, deployment, and production verification.

If a specific mathematical change fails validation, isolate that change rather than holding up unrelated completed features.

Continue the existing Chase Upside site-completion campaign.

Do not stop Trade Calculator improvements, Manager Intelligence, Draft Capital, Trade Finder, or other authorized work because source-voting changes require additional testing.

DFS implementation remains shelved.

League Tycoon implementation remains shelved.

--------------------------------------------------
FINAL OWNER DIRECTIVE
--------------------------------------------------

I want Chase Upside to represent a genuine consensus of the legitimate dynasty football sources we collect.

The whole purpose of collecting these sources is to use their information.

Every eligible source should contribute.

Agreement is not a reason to exclude a source.

Disagreement is not a reason to exclude a source.

Freshness determines how much voting power an otherwise eligible source retains.

The freshness schedule is:

Days 0–7: 100%
Days 8–14: 75%
Days 15–21: 50%
Days 22–30: 25%
Older than 30 days: 0%

DLF IDP and DLF Rookie IDP are approved to return to voting.

Preserve genuine data-quality and duplicate-provider safeguards, but do not use them to unnecessarily exclude legitimate opinions.

Correct the IDP outlier-filter interaction.

Make every source's actual voting status and effective weight transparent.

Implement this consistently across Chase Upside, validate the resulting valuations, deploy safely, and verify production.

Continue finishing the rest of the site as quickly as safely possible.

Do not ask me to repeat these decisions.
