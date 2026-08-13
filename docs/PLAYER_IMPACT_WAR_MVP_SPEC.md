# Chase Upside — Player Impact, Fantasy WAR & MVP

**Status:** BINDING OWNER-INTENT / FUTURE IMPLEMENTATION SPEC  
**Date:** 2026-08-13  
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

## 7. MVP methodology — eligibility change

The previous planned rule that League MVP must be on a playoff team and above .500 is **superseded**.

**League MVP has no hard playoff-field or >.500 team-record eligibility requirement.**

A player who created the most defensible individual fantasy value must not be automatically disqualified because the rest of his manager's roster missed the playoffs.

Team success may be context or a validated tie-breaker, but not a hard player-MVP gate.

This change applies to **player MVP only**. Manager of the Year may continue to require actual team success because it measures managerial accomplishment. GM of the Year remains distinct, and OPOY/DPOY/ROY/positional awards do not inherit the player-MVP team gate.

## 8. MVP evidence hierarchy

Do **not** make MVP equal whichever player leads one metric.

Preferred evidence hierarchy:

1. **xWAR** — central continuous standings-value measure;
2. **Realized VORP** — central player-dominance measure;
3. **Actual WAR** — high-leverage reality check showing literal standings results changed;
4. **WAB / Game Changer** — context for actual roster indispensability;
5. team/postseason success — context or validated tie-break only.

Do not invent arbitrary fixed weights just to manufacture an index. During the C-series Awards methodology pass, compare transparent deterministic aggregation methods, test positional bias and sensitivity, and obtain owner approval before promoting the final MVP formula. AI may explain the winner but may not choose the winner.

MVP, OPOY/DPOY and positional awards should remain distinct:

- MVP = overall fantasy-team/standings value;
- OPOY/DPOY = strongest realized offensive/defensive player performance, where VORP/dominance may matter more;
- positional awards = dominance/value within role.

## 9. Player Impact UI

When foundations are ready, appropriate player-season / UPP surfaces should expose a compact Player Impact block:

- Realized VORP
- xWAR
- Actual WAR
- Wins Above Bench

Progressive disclosure should show weekly contributions and literal result flips, e.g. `+4 WAR — 2 H2H results + 2 median results changed`.

Missing historical xWAR must display unavailable/insufficient-history, not 0.00.

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
- negative VORP/WAR/xWAR/WAB is valid;
- ties use actual league rules;
- historical xWAR without defensible archived probability evidence is unavailable by default.

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
- MVP candidate methods are tested for stability and for meaningful distinction from OPOY/DPOY.

## 13. Done criteria / sequencing

Done requires one canonical replacement-baseline owner, trusted B7 realized scoring, one canonical best-ball solver, league standings rules from canonical config, one weekly player-impact contract shared by Awards/UPP/Upside Report, immutable provenance/history, the old MVP playoff/>.500 gate removed, final deterministic MVP aggregation validated + owner-approved, and representative production weeks independently reproduced.

Do **not** interrupt the active B fast lane to implement this full feature family. B7 exact scoring is a prerequisite foundation; the complete Player Impact / WAR / Awards integration belongs in the mandatory post-B C-series replan, where this file is binding owner intent.
