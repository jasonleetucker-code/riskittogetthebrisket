URGENT OWNER DIRECTIVE — CORRECT SOURCE VOTING AND CONSENSUS METHODOLOGY
Repository: `jasonleetucker-code/riskittogetthebrisket`
Priority: P0 — Valuation correctness
Affected work: PR #1817, IDP source independence, correlation caps, source voting, single-source haircuts, D2/D3 decisions, and the broader consensus methodology.
1. My Actual Philosophy on Source Voting
I want Chase Upside to be a consensus-driven dynasty valuation platform.
If two different fantasy football websites independently arrive at the same or similar player values, that is agreement, and I want that agreement represented in our consensus.
Do not punish sources simply because their rankings or values are similar.
I do not want our system automatically treating similar rankings as evidence that one source copied another.
Two websites agreeing is not inherently a problem. It's often exactly what we're trying to measure.
This directive supersedes the conflicting portions of my October 18 D2 and D3 decisions. All unrelated owner decisions remain in effect.
2. All Legitimate Sources Should Be Allowed to Vote
My preferred policy is:

1. Every approved, eligible source should contribute its opinion.
2. Similar values do not automatically mean the sources are duplicates.
3. Two sources independently agreeing should remain two legitimate observations.
4. Keep each source's existing approved weighting unless a separately authorized methodology change is justified.
5. Do not create an extra multiplier or bonus just because two sources agree.
6. Do not exclude a source solely because its independence has not been proven.
7. Continue enforcing freshness, data quality, identity, eligibility, and the existing approved provider-family rules.

There is an important exception:
If credible evidence establishes that one feed simply republishes another feed, don't pretend they're two independent observations.
But distinguish actual shared data lineage from numerical similarity.
A near-identical ranking is a reason to investigate, not sufficient proof to remove voting rights.
3. Specific Decision: IDP Trade Calculator and IDP Show
Both sources should remain eligible to vote on IDP player valuations.
Do not combine them into one voting family solely because their rankings are identical or highly correlated.
Do not automatically introduce a shared cap between these two different websites based only on rank similarity.
They may each receive their approved voting weight when:

* Their observations are current and valid.
* Their data is eligible under existing source rules.
* They meet the existing source-quality gates.
* There is no credible evidence that one is merely republishing the other's underlying feed.

If an actual shared-data dependency is established, document it and apply the existing provider-lineage safeguards appropriately.
Keep source-correlation information available for diagnostics, confidence analysis, and research, without allowing similarity by itself to suppress voting.
4. Specific Decision: IDP Trade Calculator Offense Values
Revisit the D3 decision to exclude IDP Trade Calculator from offensive voting.
I do not want its offensive values excluded simply because we cannot prove how independently they were produced.
If IDP Trade Calculator publishes legitimate, eligible offensive player values, it should be allowed to contribute under the same established quality, freshness, normalization, and weighting rules as other approved sources.
Do not classify its offensive values as duplicates of KTC merely because they resemble KTC.
If there is actual evidence of copied or derived underlying KTC data, evaluate the appropriate existing family treatment.
Otherwise, do not automatically remove the vote.
Preserve IDP and rookie/pick voting behavior except where an independently justified correction is required.
5. Fix the Single-Source Haircut Problem
The current PR #1817 evaluation found that some defensive player values drop approximately 70% under the proposed source-correlation change.
Example:

* L'Jarius Sneed: 1,133 → 339.

I do not want this behavior accepted without rigorous justification.
Investigate the single-source reliability haircut, especially how it interacts with:

* Source families.
* Multiple eligible providers.
* Correlation group assignments.
* Source freshness.
* IDP Show's republished board.
* The 30% single-source haircut.
* Two-way players such as Travis Hunter.
* Actual voting eligibility versus values merely present in source data.

My decision: Do not activate the proposed D2 shared-family cap or its resulting extreme value changes as currently designed.
First determine which parts of the problem are caused by inappropriate source grouping versus an actual flaw in the haircut.
Do not remove legitimate votes to make the evidence look cleaner.
Do not simply disable every reliability safeguard either.
Any revised single-source haircut must have an explainable purpose, independent validation, and protection against unjustified discontinuities.
If changing the haircut requires an additional mathematical methodology decision not resolved by this directive, keep the existing approved rule and run the proposed alternative as a challenger until it passes its evidence gates.
6. Preserve Legitimate Family Protections
This directive is not permission to count every URL, board, or dataset as a completely independent opinion.
Preserve approved protections against:

* The same provider publishing several versions of the same underlying rankings.
* Multiple source boards representing the same provider family.
* Duplicate player observations inside one source.
* Stale or invalid observations.
* Identity mismatches.
* Unapproved experimental sources.

For example, DLF Rank and DLF Values should still respect the approved DLF provider-family cap.
But do not conflate two providers reaching similar conclusions with two listings of the same underlying source.
Those are different situations and must be treated differently.
7. Rework PR #1817 Before Merging
Audit the current implementation and correct it to reflect these decisions.
Specifically:
D2 — IDP correlation cap

* Do not enable the proposed cross-provider shared cap based solely on identical ranks.
* Preserve the approved votes for IDP Trade Calculator and IDP Show when both are eligible.
* Keep their similarity measurements available for diagnostics.
* Remove or disable any new haircut interaction that incorrectly treats their agreement as a loss of source coverage.

D3 — IDP Trade Calculator offense

* Do not exclude its offensive vote solely for unproven independence.
* Evaluate it using the normal approved eligibility and quality rules.
* Preserve the original voting contribution unless a different, evidence-supported disqualification exists.

D4 — DLF Values

* Continue the approved offense-only rank-to-Hill implementation.
* Preserve the existing DLF family cap.
* Keep all release and evidence requirements.

D5 — FantasyPros freshness

* Preserve the strict actual-upstream-timestamp policy.
* A newly downloaded old ranking must not become a fresh vote.

Keep these decisions independently controlled so correcting D2/D3 does not unnecessarily block D4/D5.
8. Required Independent Evidence
Before releasing the changes, compare at least these scenarios against the existing production board:

1. Current approved source-voting behavior.
2. Proposed D2/D3 changes from the existing PR.
3. Revised policy allowing both eligible IDP providers to contribute.
4. Revised policy including IDP Trade Calculator's eligible offensive votes.
5. The combined revised policy with D4/D5.

Report:

* How many offensive and defensive players change.
* Median, p90, p99, and maximum value changes.
* Largest individual movers.
* Position-level effects.
* Top-50 and top-200 movement.
* Source vote counts and effective weights.
* Confidence changes.
* Single-source haircut changes.
* Effects on two-way players.
* Impact on picks where relevant.
* Any source receiving more influence than its approved weight.
* All-flags-off compatibility with the existing production model.

Make these evaluations reproducible.
No artificial test fixtures should be used to conceal unexpected effects on real players.
If a change fails its evidence requirements, hold that specific change without blocking unrelated validated improvements.
9. Preserve Our Other Valuation Decisions
The following remain binding:

* Active geometric Value Adjustment `geom_q078_v1`, `q = 0.78`.
* KTC Value Adjustment remains a comparison/rollback model.
* DLF IDP remains held pending its separate evidence gate.
* DLF Values follows the approved DLF-family policy.
* Source freshness and identity protections remain.
* No silent source-weight changes.
* No missing value is treated as zero.
* No source receives additional voting weight merely for agreeing.
* No independent vote is fabricated by using our canonical values as a fallback.

Do not alter the Trade Calculator's approved Value Adjustment methodology to solve a source-voting problem.
10. Finish the Work Without Delaying the Site
Continue the Chase Upside completion campaign.
Do not stop the Trade Calculator speed work, simplified War Room, dual Value Adjustment comparison, screenshot imports, Manager Intelligence, or other non-DFS completion work because this source-policy change needs additional testing.
Coordinate with the current release trains.
Implement the source-policy correction through the canonical owners, update PR #1817 or supersede it cleanly if necessary, run independent testing, and merge only after the required release gates pass.
After deployment, verify the actual served board and source contributions in production.
Keep DFS implementation and League Tycoon implementation shelved.
FINAL OWNER DECISION
My objective is consensus from legitimate sources.
I want agreement to be visible in the consensus, not treated automatically as a defect.
I want the system to detect actual duplication, not assume duplication whenever two rankings match.
I want the reliability safeguards to protect the board without causing unjustified collapses in player value.
I want every eligible source to contribute according to its approved weight.
Use this interpretation across the Chase Upside source-voting system, not just IDP Trade Calculator and IDP Show.
Correct PR #1817 accordingly, validate the results, and continue finishing the site ASAP. Do not request another owner decision on D2 or D3 unless genuinely new evidence presents a different, material policy question not answered here.
