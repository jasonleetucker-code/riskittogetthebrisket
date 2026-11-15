# Owner directive — Phase 2: deep investigation of package Value Adjustment models (2026-10-19)

**Recorded verbatim**, with the directive's bullet lists reflowed into sentences; no requirement was
dropped or reworded. Phase 1 directive: `HYBRID_VALUE_ADJUSTMENT_RESEARCH_2026-10-19.md`. Answering memo:
`docs/valuation/PACKAGE_MODEL_PHASE2_RESEARCH_2026-10-19.md`.

---

Claude — Phase 2: Deep Investigation of Package Value Adjustment Models. Repository
jasonleetucker-code/riskittogetthebrisket.

**Objective.** Continue the research from PR #1833. I am not approving any change to our production Value
Adjustment model at this time. Our current production model is geom_q078_v1, with q = 0.78. The initial
research concluded that blending our geometric model with KTC's package adjustment is inferior, and that
none of the tested alternatives demonstrated enough improvement to justify replacement. I accept that
conclusion provisionally. However, I want the outstanding research completed before considering the
investigation closed. Your job is to determine whether our current model is genuinely the best available
approach, especially for trades involving unusually large packages, without sacrificing the accuracy of
ordinary trades. Do not interpret this assignment as permission to replace our current model.

**1. Review the existing research before proceeding.** Begin by examining PR #1833 and its supporting
documentation (docs/valuation/PACKAGE_MODEL_HYBRID_RESEARCH_2026-10-19.md,
docs/valuation/HYBRID_VALUE_ADJUSTMENT_RESEARCH_2026-10-19.md,
docs/valuation/evidence/package_model_hybrid_2026-10-19/research.json,
docs/valuation/evidence/package_model_hybrid_2026-10-19/matrix_cells.csv). Also inspect the actual
production Value Adjustment implementation, its consumers, the existing research scripts, relevant tests,
and the Trade Finder evaluation logic. Preserve all previous research and findings. Do not restart the
research from scratch or repeat experiments unnecessarily.

**2. Run the research against our full market-trade archive.** The initial research only evaluated 38
trades from our own league. That is insufficient to determine how different models perform across
real-world dynasty trades. We also have a significantly larger database of trades collected from external
leagues and trade sources, including Sharp/KTC-related data. The existing research report states that a
script mode was added specifically to evaluate model candidates against this archive. Find that script and
run it against the complete available archive. If the archive is accessible only on our production server,
determine the appropriate read-only execution method. Do not modify production data, interfere with
ingestion jobs, or expose credentials. Evaluate: our current geom_q078_v1 model; KTC adjustment
independently; the previously tested geometric/KTC blends; the geometric depth-floor candidate; HYBRID_50;
any other previously tested candidates worth retaining as experimental baselines. Data quality
requirements — before interpreting results, audit the dataset for: (1) duplicate trades, including the same
trade collected from multiple sources; (2) multi-team trades being incorrectly represented as two-team
trades; (3) outdated trades evaluated using future player values; (4) trades involving assets missing
historical values; (5) trades with incomplete player or draft-pick information; (6) trades from leagues
with unusual scoring or roster configurations; (7) bias caused by one league, manager, source, or time
period contributing disproportionately many trades. Use the best available point-in-time values. Where
historical values are missing, report exclusions and coverage rather than silently substituting current
values. Separate superflex, 1QB, IDP, TE-premium, and other league formats when reliable format metadata
permits. Very importantly, distinguish observed manager behavior from actual trade fairness. An accepted
trade does not prove a trade was fair. Do not optimize a model merely to make historical trades appear
even. Instead, determine what the archive can and cannot legitimately tell us about package valuation.
Where the archive includes trades that influenced KTC or our underlying source values, investigate
circularity and avoid treating those observations as independent validation. If production access is
unavailable, exhaust reasonable read-only alternatives and document the exact blocker and executable
procedure. Never represent an unexecuted analysis as completed.

**3. Deep investigation: Why do large packages favor the superstar?** This is my biggest remaining concern.
The initial results showed that for 1-for-6 and 1-for-10 packages, our model favored the single superstar
approximately 91% of the time. That might be entirely reasonable for the underlying combinations being
tested. But I want to establish whether the model adequately differentiates between useful depth and
disposable roster filler. Scenario A — Genuine roster depth: one elite player is exchanged for six players
who are all meaningful contributors, have legitimate starting potential, or carry substantial individual
dynasty value. Scenario B — Roster filler: one elite player is exchanged for six players with minimal
dynasty value, little realistic starting potential, or negligible usefulness to an actual fantasy roster.
Both trades contain six incoming assets, but they should not necessarily receive similar package
treatment. Investigate: (1) does our current geometric model already distinguish these situations
appropriately? (2) how much does the result depend on relative asset values versus the number of assets?
(3) are useful secondary players being discounted too aggressively? (4) are very low-value players
retaining too much influence? (5) does adding the sixth, seventh, or tenth player meaningfully affect
fairness when that player is nearly worthless? (6) do packages behave differently when their value is
distributed relatively evenly versus concentrated in one or two headliners? (7) what happens when several
genuine starters are exchanged for one elite player? (8) how do rookie picks, IDP players, and mixed
offense/defense packages behave? Use a controlled test matrix that holds total raw package value constant
while changing value concentration and asset count. Test 1-for-2 through at least 1-for-10, plus
asymmetric multi-player trades such as 2-for-3, 2-for-5, 3-for-6, and 4-for-8. Use real player examples in
addition to synthetic numerical scenarios. Do not assume that adding more assets should eventually overcome
a superstar. Determine whether each outcome makes sense given the distribution of value. Also distinguish
mathematical value adjustment from actual lineup utility. Do not quietly introduce starting-lineup,
roster-space, or positional-need adjustments into the shared model merely to fix package-count behavior.

**4. Investigate whether a more sophisticated model would help.** Do not restrict this phase to averaging
existing models. If the evidence suggests that the geometric model has an identifiable weakness,
investigate whether a targeted alternative could address that weakness. Potential ideas to explore
include: adjustments based on how value is distributed within each side; concentration-sensitive geometric
weighting; effective package depth rather than raw player count; different diminishing-return behavior for
genuinely useful assets versus negligible assets; smooth mathematical functions that adjust depth
sensitivity without abrupt thresholds. These are research directions, not instructions to implement them.
I specifically do not want a model that makes six worthless players equal one superstar. I also do not want
an arbitrary hard cutoff that declares players below a certain dynasty value worthless. Any candidate must
preserve the mathematical properties established in the original research. Especially important: adding a
player worth 1 to a package must not produce a larger valuation improvement than the player actually
contributes. Preserve all prior mandatory tests involving symmetry, monotonicity, negligible assets, and
other established invariants. Do not weaken the tests to get a challenger to pass. Check for
discontinuities, arbitrage-like behavior, unreasonable sensitivity to value distribution, and unnatural
results around thresholds. Any proposed challenger must have an explainable mathematical rationale, not
simply fit a collection of handpicked trades. Keep all experimental implementations separate from
production.

**5. Actually rerun Trade Finder under each viable model.** The previous report estimated Trade Finder
impact based on how often fairness grades would change. That is useful as an initial approximation, but I
want a proper replay. Find the actual Trade Finder logic and determine how to evaluate its outputs under
alternative package models. Run the same eligible teams, roster snapshots, filters, player values, and
search settings against each viable candidate wherever possible. Evaluate actual changes to: Golden Trades;
Package Scanner; trade recommendation rankings; trade fairness assessments; recommended send/receive
combinations; offensive and defensive asset packages; recommendations involving elite players;
recommendations involving lower-ranked roster filler; three-or-more-player packages. I particularly want to
know whether a different model starts recommending trades that superficially look fair but realistically
require one manager to give up a superstar for a collection of mediocre assets. Also examine whether our
current model incorrectly rejects sensible trades where multiple legitimate contributors are exchanged for
an elite player. Report how many trade recommendations change, how many disappear or appear, and whether
the recommendations become more or less defensible. Keep model effects separate from search-algorithm and
candidate-generation effects. If replaying the complete search is computationally expensive, create a
representative reproducible benchmark, explain its coverage, and identify what remains untested. Do not
confuse a changed trade recommendation with an improved trade recommendation. Establish an evaluation
method before comparing results.

**6. Respect the current Value Adjustment architecture.** Our current Value Adjustment logic has been
extended across the site. It influences more than the main calculator, including Trade Finder, Trade
History, and Second Opinions wherever applicable. I do not want an experimental model to introduce
inconsistent values or alternative valuation behavior across pages. Investigate how candidate models would
affect these consumers, but keep experiments isolated. In particular: preserve the established treatment
of source-native values; preserve the agreed Second Opinions fallback behavior for sources missing
particular assets; preserve our existing approach to IDP and offense valuation; preserve historical
point-in-time evaluation behavior; do not modify the base valuation consensus or voting-source weights. A
package adjustment is not permission to change the value of the underlying assets.

**7. Establish evidence standards before selecting a winner.** Do not recommend a different model simply
because it performs better on one metric or a handful of examples. Compare candidates on: (1) mathematical
correctness; (2) ordinary 1-for-2 through 2-for-3 trades; (3) larger multi-player packages; (4) genuine
depth versus roster-filler sensitivity; (5) available historical market-trade evidence; (6) actual Trade
Finder outputs; (7) stability across different asset-value distributions; (8) complexity and
explainability; (9) operational and production risk. Where possible, use held-out datasets and evaluate
sensitivity to time periods, leagues, scoring formats, and data sources. Predefine the evaluation criteria
and what would constitute a meaningful improvement before interpreting the results. Avoid tuning model
parameters against the same trades ultimately used to claim superiority. The default remains q = 0.78. Do
not recalibrate q based solely on accepted league trades. A challenger should only be recommended if it
clearly solves a demonstrated weakness while maintaining or improving performance elsewhere. If the results
remain inconclusive, recommend retaining the current model.

**8. CI and PR #1833.** Check the status of PR #1833. Run the appropriate local tests and CI checks, if
accessible. Investigate and resolve any failures directly related to this research. Maintain the
distinction between: local tests passing; CI passing; research results being reproducible; a model being
approved for production. Do not merge the PR merely because local tests pass. Do not implement or activate
a replacement package model without my explicit approval. Create a clearly identified Phase 2 research
update or follow-up PR as appropriate, preserving the original evidence and making additional experimental
work easy to review.

**9. Deliverables.** I want a complete written report, supported by reproducible data and tests. Include:
A. Production archive results (the number of usable trades, dataset quality, exclusions, format coverage,
candidate results, and limitations); B. Large-package investigation (detailed findings explaining the
approximately 91% superstar preference and whether it reflects appropriate valuation or a problem in the
geometric model); C. Roster-filler sensitivity (controlled comparisons of packages with equivalent raw
totals but different distributions of useful and negligible assets); D. Alternative-model evaluation
(formulas, mathematical tests, strengths, weaknesses, and concrete trade examples for viable challengers);
E. Actual Trade Finder impact (how the different models change recommendation generation, ordering,
quality, and fairness classifications); F. Comparative scorecard (a side-by-side assessment of the current
model and every serious challenger); G. Production impact (a precise account of which functions, pages,
shared libraries, historical views, and tests would change if a different model were eventually approved);
H. Recommendation — choose one: 1. KEEP: retain geom_q078_v1 unchanged because no alternative demonstrates
sufficient improvement; 2. CHALLENGE: a specific alternative demonstrates meaningful, reproducible
improvement and deserves my consideration; 3. INSUFFICIENT EVIDENCE: more evidence is necessary, with a
clear explanation of what is missing. Don't force a challenger if the evidence doesn't support one. I.
Verification and outstanding work (the commands executed, test outcomes, CI status, data-access
limitations, and any incomplete evaluations; clearly differentiate completed experiments from estimates and
proposed follow-up work).

**10. Final instructions.** This is a research-and-validation assignment, not a production implementation
assignment. You may write experimental scripts, tests, benchmark harnesses, analysis tools, documentation,
and research evidence. You may fix issues that prevent the research from being executed, provided those
changes do not alter the production model's behavior. Do not change: production geom_q078_v1; the active
q = 0.78 parameter; source voting or weighting; base player values; live Trade Finder evaluation behavior;
existing Value Adjustment integration points. Do not merge or deploy a different model. Complete as much of
the research as the environment permits. Do not stop at proposing research that can actually be executed
with available tools and data. When finished, give me an executive summary in plain English addressing
these four questions: (1) Is our current Value Adjustment model actually undervaluing legitimate depth in
large trades? (2) Is it properly protecting against managers trying to combine a pile of mediocre players
for a superstar? (3) Does any alternative demonstrably improve the quality of our Trade Finder
recommendations? (4) Should we keep q = 0.78 unchanged, or is there sufficient evidence to consider
something better? I care more about a defensible, mathematically sound, realistic trade evaluation than
about making every trade look close to even. Our objective is the most accurate dynasty trade calculator
possible — not a calculator that makes every package look acceptable.
