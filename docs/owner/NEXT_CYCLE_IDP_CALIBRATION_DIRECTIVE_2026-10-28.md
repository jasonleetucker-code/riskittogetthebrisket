# Owner directive 2026-10-28 — next development cycle: IDP calibration, source authority, Trade Advisor readiness

**Source:** the owner's chat, 2026-10-28, to the coordinator session. Recorded verbatim below. Intake:
`docs/OWNER_REQUESTED_TODO.md` "Added 2026-10-28 — Next development cycle" (NC-A … NC-E). Authorization:
`docs/EXECUTION_PLAN.md` (same date). Recording it here authorizes nothing beyond what the execution plan says.

**Factual note (2026-10-28, not part of the verbatim text):** the verified `dynasty_main` lineup is QB, SUPER_FLEX,
RB×2, WR×3, TE×2, FLEX×2 (RB/WR/TE), K, DL×3, LB×3, DB×3, best ball, 12 teams; the scoring card grants TEs no
premium (`bonus_rec_te 0`). The directive's "2 QB / 2 WR flex" describes QB + SUPER_FLEX and two RB/WR/TE FLEX slots.
Source: PR #2010, `docs/league-intelligence/ROS_SCALE_CALIBRATION_RESULTS_2026-10-28.md`.

---

NEXT DEVELOPMENT CYCLE — IDP Calibration, Source Authority, and Trade Advisor Readiness

Continue development of "jasonleetucker-code/riskittogetthebrisket" from the post-release state described in the latest handoff.

Operating mode: Parallel Build Mode.

The previous release is closed. Do not reopen completed work without evidence of a regression.

PRIMARY OBJECTIVE

Improve the mathematical reliability of Chase Upside's dynasty league analysis, especially the relationship between offensive and IDP player contributions.

Our ultimate objective remains an accurate, explainable Trade Calculator that recommends whether to accept or reject a trade using all relevant factors, including league scoring, roster construction, positional scarcity, player valuations, rest-of-season expectations, replacement value, championship equity, and uncertainty.

Preserve the distinction between dynasty market value and rest-of-season competitive value.

WORKSTREAM A — IDP/OFFENSE SCALE CALIBRATION

Highest priority.

Investigate the incompatible 100-point offense and IDP rest-of-season scales.

Build a proposed calibration system that translates positional projections into comparable contributions to team performance.

Requirements:

- Use our league's actual scoring and starting lineup.
- Account for 2 QB, 2 RB, 3 WR, 2 WR flex, 2 TE, 3 DL, 3 LB, and 3 DB starters.
- Respect superflex, two-TE scarcity, and position-specific replacement values.
- Evaluate projected fantasy points, weekly variance, matchup uncertainty, and points above replacement.
- Determine whether each position requires a separate conversion.
- Avoid arbitrary equalization of offensive and defensive scoring.
- Prevent double counting of replacement value or scarcity.
- Preserve existing dynasty valuation methodology.
- Evaluate downstream effects on team strength, optimal lineups, playoff simulations, and trade recommendations.

Create a champion/challenger evaluation using historical results and out-of-sample testing wherever sufficient data exists.

Define measurable acceptance criteria, including prediction error, calibration, ranking stability, and relevant downstream decision quality. Report insufficient sample sizes explicitly.

Do not promote a new valuation methodology automatically. Produce a recommendation with supporting evidence for owner approval.

WORKSTREAM B — IDP SOURCE AUTHORITY

Run concurrently with Workstream A.

Investigate why elite IDP rows currently retain approximately 37% of normal source weight.

Examine:

- IDP Show freshness and ingestion.
- FantasyPros timestamp interpretation.
- DLF source hold.
- Source availability and actual data age.
- Provenance, licensing, and reliability.
- Freshness weighting and confidence calculations.

Restore legitimately available source information where possible.

Do not manufacture freshness or increase weights merely to achieve a preferred valuation.

Test changes against actual IDP players, including elite defenders, rookies, and deep-roster players.

Expose source-specific reasons for reduced weight.

WORKSTREAM C — RELEASE COMPLETION AND TEST RELIABILITY

In parallel:

- Confirm #2008's deployment and served SHA.
- Promote deterministic tests from non-blocking live-data tiers into the required CI gate.
- Add the explicit-file-encoding regression test.
- Monitor the next scheduled E2E run for recurrence of #2000.
- Complete remaining WebKit mobile tests.
- Complete Trade Advisor production network checks.

Preserve independent review, necessary security checks, and green required CI before merging.

Do not introduce unnecessary full-suite testing into every small development iteration.

WORKSTREAM D — TRADE ADVISOR READINESS

Continue technical work, but preserve the owner's launch controls.

Prepare evidence-backed recommendations for the proposed 250 ms response floor, source permissions, admission limits, and rate limits.

Explain what the response floor protects against and whether a different latency policy would be preferable.

Do not enable the launch flag or assume owner approval for held decisions.

Ensure the advisor can explain the difference between market value, roster utility, expected points, and playoff impact.

Keep Simulation V3 experimental. Clearly mark championship and trade playoff-impact estimates as uncalibrated wherever appropriate.

WORKSTREAM E — EXISTING DECISIONS AND BACKLOG

Keep #2006 held pending explicit owner approval. The recommended outcome is to restore the original deep-tail rookie voting rule, with separate future evaluation of that rule's merits.

Do not alter the "dynasty_new" taxi cap without separate authorization.

Continue authorized work on Waiver Advisor readiness, IDP source freshness, GitHub Support #1985, and closing superseded #1921 where safe.

PARALLEL EXECUTION

Use independent agents, branches, or worktrees where appropriate.

Implement independent improvements concurrently. Avoid multiple agents modifying shared calculation logic without coordination.

Keep approved implementation work moving while calibration research is underway.

Require tests for numerical changes, source-weight changes, scoring changes, and critical privacy boundaries.

Use targeted tests during development, with full integration validation at promotion boundaries.

REQUIRED OUTPUT

At completion, provide:

1. Workstream status and associated PRs.
2. What was actually implemented and merged.
3. What is deployed versus merely proposed.
4. Before/after comparisons for representative players and teams.
5. Evidence that dynasty valuations and TE++ methodology were not unintentionally changed.
6. Champion/challenger results and acceptance-gate findings.
7. Remaining blockers requiring owner authorization.
8. Recommended next development priorities.

Do not confuse a completed implementation with a validated methodology or production deployment.

Prioritize substantive improvements to the accuracy of Chase Upside's decisions over cosmetic changes or administrative housekeeping.
