# Chase Upside — Player Impact, Fantasy WAR & MVP

> **RECONCILIATION AMENDMENT — 2026-08-14.** Promoted to `main` verbatim from PR #816 by the post-B master
> reconciliation (`docs/POST_B_RECONCILIATION_2026-08-14.md`). Body unchanged. One correction of fact:
>
> **There is no active B fast lane to avoid interrupting.** B4–B11 are merged and the B-Series Completion Audit
> passed (#837, `79f47ff`). This spec's closing sequencing caution is satisfied, not pending.
>
> **OWNER DECISION — 2026-09-26:** §7 below is **superseded**. League MVP **does** require team success (the
> playoff-field + >.500 gate in `docs/BRISKET_HONORS_ELIGIBILITY_SPEC.md` §3–§4 is canonical again); OPOY, DPOY,
> ROY and positional awards do not inherit it.
>
> **OWNER CLARIFICATION — 2026-09-27:** Player win-impact must be a meaningful **component of the overall
> League MVP formula**, not only a separate statistic, panel, leaderboard, or tie-break, and not the entire
> formula by itself. Individual performance remains a meaningful component too. See §8 and §14. Inclusion is
> owner-approved; exact normalization, weights and production promotion still require methodology validation.
> The team-success gate above is unchanged. This is durable Calculator Ideas scope, not a runtime change.


**Status:** BINDING OWNER-INTENT / FUTURE IMPLEMENTATION SPEC  
**Date:** 2026-08-13; MVP integration clarified 2026-09-27  
**Implementation effect:** docs only; implement only when sequencing authorizes it.

## Purpose

Chase Upside must distinguish three different questions instead of forcing them into one metric:

1. **Realized Lineup VORP:** how good was the player versus a normal league-level positional replacement?
2. **Fantasy WAR / xWAR:** how many actual / expected standings wins did that performance create versus league replacement?
3. **Wins Above Bench (WAB):** how indispensable was the player to this manager's actual roster?

These become first-class player-season statistics and canonical inputs to Awards, UPP, The Upside Report, and historical season stories.

## 1. Replacement baselines

### League replacement — VORP, WAR, xWAR

Use a **league-level positional replacement expectation**, derived from actual league scoring, lineup requirements, league size, positional demand, flex/superflex/IDP rules, and the relevant week/season context.

Do **not** use the next-best player on that owner's bench for VORP/WAR/xWAR. One manager's unusual depth must not redefine how good the player was relative to the league.

The final replacement estimator should be robust (for example a marginal replacement band around the league-demand cutoff) rather than one brittle arbitrary player. Missing replacement evidence remains unavailable, never zero.

### Team replacement — WAB / Game Changer

For roster-specific indispensability, remove the player from that team's roster for the week and **re-solve the complete legal best-ball lineup using the actual scores of the remaining rostered players**.

This answers: **"If this fantasy team did not have this player, what would actually have happened?"**

## 2. Realized Lineup VORP

For each player-week whose score is counted in the final legal best-ball lineup:

`weeklyVORP = actualCountedPoints - leagueReplacementExpectation(position, league, week)`

`seasonVORP = Σ weeklyVORP`

Non-counted best-ball weeks contribute 0 realized lineup VORP. Negative VORP is valid.

VORP is the primary dominance primitive for OPOY/DPOY, positional awards, MVP supporting evidence, and player-season impact profiles.

## 3. Fantasy WAR — Actual Wins Above Replacement

For every counted player-week:

`counterfactualTeamScore = actualTeamScore - playerActualPoints + leagueReplacementExpectation`

Use the league's real standings rules to compare actual and counterfactual standings-win credits.

For the current H2H + league-median format, evaluate both:

- head-to-head result;
- league-median result.

`weeklyWAR = actualStandingsWinCredits - replacementStandingsWinCredits`

`seasonWAR = Σ weeklyWAR`

Typical no-tie weekly values are +2, +1, 0, -1, -2. Ties use the league's actual fractional standings credit.

**Mandatory:** recalculate the league median after replacing the player's score. Do not hold the actual median fixed if the counterfactual score can change it.

WAR is intentionally leverage-sensitive. A huge blowout performance can create 0 WAR if replacement production still wins; a smaller performance can create +2 if it flips both results. Therefore WAR must not be the sole MVP metric.

## 4. xWAR — Expected Wins Above Replacement

Actual WAR is discrete and margin/schedule sensitive. xWAR is the continuous companion.

For the same actual and replacement team scores, use the **same archived no-lookahead league-week scoring distribution / simulation** to estimate expected standings-win credits:

`weekly_xWAR = E[wins | actual score] - E[wins | replacement score]`

In an H2H + median league:

`E[wins] = P(win H2H) + P(beat league median)`

Use the same joint league-week simulation as canonical Game Day / Playoff systems rather than pretending the two outcomes are independent when better modeling exists.

`season_xWAR = Σ weekly_xWAR`

This naturally produces decimals. Archive the model/version and probability inputs used. If historical probability evidence does not exist, xWAR is unavailable unless a separately approved reconstructed method is explicitly labeled; never use today's model and pretend it was contemporaneous.

## 5. Wins Above Bench (WAB)

For each counted player-week:

1. remove the player;
2. retain every other actual rostered player's real weekly score;
3. re-solve the exact best-ball lineup;
4. obtain `bestBallScoreWithoutPlayer`;
5. recompute H2H/median results, including a newly calculated league median where necessary.

`weeklyWAB = actualStandingsWinCredits - benchCounterfactualStandingsWinCredits`

`seasonWAB = Σ weeklyWAB`

WAB is deliberately roster-specific. It must re-solve the whole lineup, not merely plug in "the next RB" or "the next WR," because flex/superflex/IDP assignments can change.

## 6. Game Changer Points

The Upside Report's Game Changer must reuse the exact same remove-and-re-solve primitive:

`GameChangerPoints = actualTeamScore - bestBallScoreWithoutPlayer`

The report may show both the point delta and whether those points flipped H2H and/or median results. Do not implement separate Game Changer math in the report renderer.

## 7. MVP methodology — eligibility

**Owner decision 2026-09-26 (binding; supersedes the 2026-08-13 text of this section):** League MVP
**requires meaningful team success.** A player is in the League MVP race only when the credited fantasy
franchise is in the championship playoff field **and** above .500 — live: current standings position under the
league's real qualification rules; finalized: actual playoff qualification plus a winning final record. The full
rule is `docs/BRISKET_HONORS_ELIGIBILITY_SPEC.md` §3–§6.

League MVP = elite player performance on a successful fantasy team. **Offensive / Defensive Player of the Year**
are the best offensive / defensive individual performances regardless of the fantasy team's record; they, the
Rookie of the Year awards and the positional awards do **not** inherit the gate. Manager of the Year keeps its
own separately validated team-success logic. The gate is an eligibility rule over the canonical player-impact
metric; it never changes the metric. The 2026-09-27 composition requirement in §8 and §14 governs how eligible
players will be ranked once the new methodology is validated; it does not modify this gate.

*Superseded (2026-08-13):* "League MVP has no hard playoff-field or >.500 team-record eligibility requirement;
team success may be context or a validated tie-breaker." Kept for provenance only.

## 8. MVP components — binding owner clarification, 2026-09-27

Do **not** make MVP equal whichever player leads one metric. The owner explicitly requires player win-impact
to be **part of the overall MVP formula**, alongside meaningful individual performance. A separate WAB/WAR
leaderboard, an explanatory panel or an impact-only award does not satisfy MVP integration. A cosmetic
non-influential coefficient or a tie-break-only use does not satisfy it either.

The intended two-stage structure is:

1. Apply the already-approved team-success eligibility gate in §7.
2. Rank eligible candidates with a transparent composite in which **performance above league replacement** and
   **standings-win impact** both materially contribute.

The evidence keeps its distinct meanings:

- **Realized VORP:** the individual-performance/dominance component.
- **WAR/xWAR:** actual/expected standings impact against league-level replacement. Evaluate a validated xWAR
  measure as the preferred continuous input; do not call it validated merely because it produces decimals.
- **WAB/Game Changer:** the original owner question about the team's actual bench replacement and changed
  results. Compute and expose these; evaluate whether a bounded WAB contribution adds useful information to
  the win-impact component without turning the award into a measure of the manager's weak bench.

**Recommended candidate structure, not a promoted numerical formula:**

`MVPScore = (1 - alpha) * normalizedPerformance + alpha * normalizedWinImpact`, for eligible candidates.

`0 < alpha < 1` expresses that neither dimension can be absent or constitute the entire score. It does not
select a coefficient. The component definitions, normalization, meaningful influence range, ties, coverage
policy and final weights remain to be compared and validated. An equivalent transparent composite is allowed
if it preserves both substantive dimensions and is explicitly documented. The owner has approved inclusion,
not a particular 60/40 or other invented split.

Do not add VORP, WAR, xWAR and WAB as though they were four independent votes. Do not combine raw points and
wins without a defined scale. Do not multiply by team record again simply to reward the same team-success
context twice. Test actual-opponent and league-standardized probability environments explicitly; probabilistic
xWAR is not automatically schedule-neutral.

During the C-series Awards methodology pass, compare candidates against the current MVP method, test
positional bias, roster-depth/schedule sensitivity and stability, publish the proposed aggregation and obtain
methodology approval before production promotion. Do not tune weights toward a preferred named winner.
AI may explain the winner but may not choose the winner.

MVP, OPOY/DPOY and positional awards remain distinct:

- MVP = individual performance plus standings-win impact among eligible successful-team contributions;
- OPOY/DPOY = strongest realized offensive/defensive player performance, without inheriting the MVP composite
  or team-success eligibility requirement;
- positional awards = dominance/value within role under their existing own methodology.

The old evidence hierarchy remains the design history, not permission to ship an xWAR-only MVP rank with
VORP merely a tie-break. This clarification requires both performance and win-impact to contribute materially.

## 9. Player Impact UI

When foundations are ready, appropriate player-season / UPP surfaces should expose a compact Player Impact block:

- Realized VORP
- xWAR
- Actual WAR
- Wins Above Bench

Progressive disclosure should show weekly contributions and literal result flips, e.g. `+4 WAR — 2 H2H results + 2 median results changed`.

Missing historical xWAR must display unavailable/insufficient-history, not 0.00.

**Owner-approved integration direction, 2026-09-27:**

- The **Player File / player-season view** is the primary detailed home: expand a week to see actual versus
  replacement lineup and scores, the replacement player/slot chain, and H2H/median results that changed.
- The **League Hub** consumes the same backend contract for a top-12 Player Impact leaderboard, with the
  metric definitions and coverage visible. This is not a new independent calculation or filler award.
- The **MVP race and expanded standings** show the overall score and its performance/win-impact contributions,
  eligibility and coverage. A standalone impact surface is an intermediate delivery, not MVP completion.
- The **Upside Report / weekly recaps** reuse the same Game Changer evidence; no second report-local formula
  or paid narrative generation is required by this feature.
- Lane 6 / Premium UI remains active alongside the backend under locked PSI / Direction A. Reuse canonical
  player/franchise links; provide desktop and 390px mobile expansion, keyboard/screen-reader access, explicit
  missing states and existing latency/payload budgets. Do not run all historical lineup solves per viewer.
- Any later live Game Day impact is **provisional**, not a replacement for finalized weekly season totals.

## 10. Historical / canonical data contract

Preserve enough immutable/versioned weekly evidence to reproduce the metrics:

- league, season, week;
- league scoring/config version;
- canonical player/team/roster identity;
- final counted best-ball lineup;
- actual player/team scores;
- league-wide scores needed to reconstruct the median;
- opponent/result;
- replacement expectation + method/version;
- best-ball score without player;
- actual/counterfactual H2H and median results;
- xWAR model/version and archived probability inputs;
- calculation version/timestamp.

Historical awards/reports must not be silently recomputed under today's model and overwrite what was published at the time.

## 11. Missing / edge semantics

- missing score/player/replacement evidence = unavailable, not zero;
- B7 scoring incompleteness must remain explicit rather than pretending exact impact;
- non-counted best-ball player-week = 0 realized lineup impact;
- negative VORP/WAR/xWAR can be valid; for exact remove-and-reoptimize WAB, apply the conditional invariant below;
- ties use actual league rules;
- historical xWAR without defensible archived probability evidence is unavailable by default.

**Remove-and-reoptimize clarification (2026-09-27):** with unchanged scoring/constraints and a feasible
remaining lineup, removing an available player cannot increase the maximum achievable best-ball score. A
negative Game Changer/WAB result under those conditions requires investigation, not a blanket clamp. An
infeasible or insufficiently observed replacement lineup is an explicit coverage/legality state, not an
invented zero-score replacement. This refines the old blanket statement that negative WAB is valid without
changing the separate signed league-replacement metrics.

**Attribution limits:** individual leave-one-out win impacts are not additive shares of team wins. Two players
can each be necessary to the same close victory. Label the result as standings outcomes changed under this
counterfactual, not an exclusive causal allocation. Hold the actual historical roster fixed; do not invent
alternate acquisitions or trades. Attribute each player-week to the franchise that actually received it;
a late trade must not transfer earlier impact or launder eligibility through the newest owner.

## 12. Validation

Before production promotion, pin at minimum:

- no result flip → WAR 0;
- H2H-only flip → +1;
- median-only flip → +1;
- both flips → +2;
- below-replacement performance can produce negative WAR;
- counterfactual median is recalculated correctly;
- ties use canonical standings credit;
- non-counted best-ball player produces zero realized impact;
- WAB re-solves the full legal lineup including flex/superflex/IDP changes;
- Game Changer Points exactly equals actual score minus re-solved score;
- missing evidence never becomes zero;
- xWAR uses identical archived distribution/version for actual and replacement states;
- no temporal leakage;
- positional/QB/IDP bias and replacement-baseline sensitivity are measured;
- MVP candidate methods are tested for stability and for meaningful distinction from OPOY/DPOY;
- controlled eligible-player cases prove win-impact can change the composite MVP order while performance
  remains independently meaningful, rather than merely adding a displayed field or tie-break;
- report before/after component contributions and rank changes against the current MVP baseline;
- test elite players on deep versus thin benches, blowouts versus close wins, star QBs/TEs/IDPs, shared pivotal
  wins, tied scores, insufficient replacement evidence and midseason traded players;
- counterfactual league-score replacement identifies the correct roster by canonical ID, not matching a
  possibly duplicated score value;
- comparable coverage is enforced across award candidates; missing xWAR is not silently zero-filled or
  compensated by per-player weight renormalization that changes the contest;
- no unrelated award formula, source role, league rule or player value changes;
- final aggregate score and displayed component breakdown agree across API, Awards, Player File and League Hub;
- current Awards season-level/clamped VORP versus this spec's signed weekly VORP is explicitly reconciled with
  an impact report and methodology decision, not silently changed as a wiring detail.

## 13. Done criteria / sequencing

Done requires one canonical replacement-baseline owner, trusted B7 realized scoring, one canonical best-ball solver, league standings rules from canonical config, one weekly player-impact contract shared by Awards/UPP/Upside Report, immutable provenance/history, the League MVP playoff-field + >.500 gate applied to League MVP only (owner decision 2026-09-26), final deterministic MVP aggregation validated + owner-approved, and representative production weeks independently reproduced.

The 2026-09-27 requirement additionally needs meaningful win-impact participation in the **overall MVP
formula**, inspectable component contributions, comparable evidence coverage and desktop/mobile production
acceptance. Shipping only the independent WAB/WAR statistic does not close the MVP integration outcome.

Do **not** interrupt the active B fast lane to implement this full feature family. B7 exact scoring is a prerequisite foundation; the complete Player Impact / WAR / Awards integration belongs in the mandatory post-B C-series replan, where this file is binding owner intent.

## 14. Calculator Ideas intake clarification — 2026-09-27

**Owner instruction:** "make it where it will be part of the overall MVP formula. Not just its own thing ...
make it just be a piece of it." This confirms the shared Player Impact product and requires a substantive
win-impact component in the overall award calculation, not an impact-only award.

**Canonical mapping:** `C5-WAR-01` owns player-impact calculation and evidence; `C9-AWARD-02` consumes it for
MVP; `C6-UPP-01`, the League Hub/PSI owners and `C9-UR-01` / `C9-WRS-01` consume the same contract for explanation
and reporting. The owner-intake ledger already points to this specification under the League MVP decision;
this section is its additive scoring-composition clarification, not a separate backlog. PR #969 remains a
closed donor/reference, not merged implementation and not authority to restore its old branch wholesale.

**Planning position:** retain as a high-value, dependency-gated Player Impact/MVP extension. Evidence/schema and
stable Lane 6 design can be planned in parallel; official formula promotion is blocked on comparable evidence,
validated normalization/weights and the applicable P6/owner-methodology decision. Do not interrupt the current
Game Day live-collector repair or measured performance work simply because the idea was recorded.

**Bounded delivery sequence:**

1. Refresh current owners and the #969 donor; build the deterministic weekly WAB/Game Changer evidence over
   real historical rosters, scores and exact lineup rules, plus Actual WAR where replacement evidence permits.
   Deliver Player File weekly inspection and the shared League Hub/MVP explanatory views with Lane 6 active.
2. Evaluate xWAR and overall MVP-composite candidates in shadow against the current method. Preserve the
   two substantive dimensions in §8. Test whether a bounded WAB contribution helps; document when roster-depth
   dependence or close-game noise makes it inappropriate as a directly weighted term.
3. Publish the selected component definitions, scales, weights, coverage rules, sensitivity and positional
   checks, tie handling and rollout/version decision. After methodology approval and normal execution/release
   gates, integrate it into the actual MVP ranking and verify the deployed breakdowns.

A useful deterministic first release need not wait for every historic xWAR input, but missing historic
probabilities cannot be invented to declare the official composite ready. Retain the current official MVP
method until the replacement has passed its gates; leave the integration outcome open rather than rebranding
that delay as completion. No silent midseason rule switch or overwrite of prior published award history.

**Authority boundary:** this change captures approved future product intent and formula participation only.
It does not select numerical weights, promote a model, change current winners, run training, activate data
providers or authorize an immediate production build. `docs/EXECUTION_PLAN.md` remains unchanged. Inclusion of
win-impact is settled; do not ask the owner to reapprove that basic requirement. Any remaining question must
identify the actual normalization, policy, evidence or rollout choice that remains unresolved.
