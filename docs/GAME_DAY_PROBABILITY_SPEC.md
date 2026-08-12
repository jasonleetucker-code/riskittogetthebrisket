# Game Day Probability Intelligence — Matchup + League Median

**Status:** CANONICAL DETAILED PRODUCT/METHODOLOGY SPEC SUPPLEMENT  
**Owner direction captured:** 2026-08-12  
**Canonical family:** CE-20 Game Day Command Center / ROS Seasonal Intelligence  
**Execution posture:** APPROVED PRODUCT REQUIREMENT; IMPLEMENT WITH GAME DAY / CANONICAL WEEKLY-SIM WORK, NOT AS AN INTERRUPTION TO CURRENT B6/B7 FOUNDATION WORK  
**Public/private posture:** PUBLIC-SAFE probability outputs may be shown where approved; private Game Day may expose richer drivers and decision context.

> This specification extends the already-approved Game Day Command Center. It does **not** authorize a second matchup model or a separate median model. Weekly probabilities should come from one canonical league-aware scoring simulation whenever possible.

---

## 1. Owner-required Game Day probabilities

For the selected fantasy team in the current scoring period, Game Day should prominently show:

1. **WIN MATCHUP %** — probability the team wins its scheduled head-to-head matchup.
2. **BEAT LEAGUE MEDIAN %** — when the requested league has the extra weekly league-median result enabled, probability the team finishes above the host-defined weekly league median / average-match threshold and earns that additional standings result.

These should update through the scoring period as live information changes.

For leagues without a median game, do not show a fake 0% chance. The feature is **NOT APPLICABLE** and should be hidden or labeled accordingly.

---

## 2. One weekly score model, two related outcomes

Do not calculate matchup win probability and median probability from unrelated formulas.

Preferred architecture:

**league-specific current-week player/team score distributions**  
+ **current live/finalized scoring state**  
+ **remaining players / game states**  
+ **injury/availability information**  
+ **league scoring + lineup rules**  
+ **best-ball behavior where applicable**  
→ jointly simulate the rest of the scoring period for the whole league  
→ derive the selected team's final weekly score  
→ compare against its opponent for `Win Matchup %`  
→ derive the same simulation's league-wide median threshold  
→ compare the selected team's score against that threshold for `Beat League Median %`.

The two outputs are correlated descendants of the same simulated week. Do not count them later as independent evidence without preserving that lineage.

---

## 3. League-median probability must be joint, not independent

In a league-median format, `Beat League Median %` cannot be estimated correctly by comparing the selected team's projection against a fixed historical average or by assigning an independent probability.

For each simulation draw:

1. simulate the final score for **every fantasy team** in the requested league for that same scoring period;
2. calculate the host-faithful league median/threshold from that simulated league-wide score set;
3. determine whether the selected team's final score earns the median result;
4. aggregate the result over all simulation draws.

This preserves the fact that the threshold itself moves with the other teams' simulated scores.

Verify Sleeper/host behavior for ties at the median and odd/even league sizes rather than guessing.

---

## 4. League settings are authoritative

The Game Day probability system must consume the same canonical league-settings/standings interpretation as the Playoff Predictor.

At minimum respect the requested league's:

- custom scoring;
- roster/starter slots;
- Superflex/flex/TE/IDP eligibility;
- best-ball vs managed lineup behavior;
- league-median setting (`league_average_match` or equivalent when verified);
- team count;
- scoring-period/week state;
- any host rule that changes the score used for the median result.

Do not use another league's configuration and do not fall back silently to the owner's home-league format.

The owner's primary league is a regression fixture with league-median standings enabled; that is not a universal default for uploaded/connected leagues.

---

## 5. Accuracy / calibration requirement

The owner wants the matchup prediction to be as accurate as reasonably possible. Treat both weekly probabilities as probabilistic models that must earn trust through historical evaluation rather than presentation polish.

Archive pregame and useful in-game snapshots so future evaluation can measure:

- matchup-win probability calibration;
- median-win probability calibration;
- Brier score / log loss or another proper probabilistic scoring rule;
- calibration curves by probability bucket;
- discrimination against simple baselines;
- error/calibration by league format, week, best-ball state, and scoring configuration where sample permits;
- whether added ROS/redraft/projection sources improve out-of-sample prediction.

A model that says `70%` should eventually win roughly 70% of comparable observations over an adequate sample.

Do not automatically promote a more complex challenger because it looks sophisticated. Compare it out of sample against the current champion and simple baselines.

---

## 6. Live updating

Game Day should become more informed as the week progresses.

The model may consume, when available and validated:

- points already scored;
- players whose games are complete;
- players currently in progress;
- remaining eligible players;
- current NFL game state and opportunity where available;
- injury/inactive status;
- weekly/ROS projections whose horizon matches the task;
- best-ball optimal-lineup possibilities and remaining bench upside;
- actual custom league scoring.

Do not treat already-scored points as uncertain or completed players as still having a full projection remaining.

For best-ball leagues, current and projected lineup outcomes must use the canonical optimal-lineup machinery rather than a static start/sit approximation.

---

## 7. Recommended Game Day presentation

At the top of the selected matchup, prominently show something like:

**Win Matchup — 64%**  
**Beat Median — 71%**

when the median game is enabled.

Useful secondary context may include:

- current score;
- projected/final-score distribution;
- opponent projected/final-score distribution;
- projected league median;
- probability of finishing above/below the median;
- major remaining swing players;
- probability both results are won;
- probability exactly one result is won;
- probability both results are lost;
- playoff implication delta where the canonical Playoff Predictor can compute it without circularity or excessive runtime.

Do not overload the primary presentation. The two headline weekly probabilities should remain easy to scan.

---

## 8. Optional joint weekly-outcome view

For median-game leagues, a useful drill-down may present the four mutually exclusive weekly outcomes:

- **2-0 week:** win H2H + beat median;
- **1-1 via H2H:** win H2H + lose median;
- **1-1 via median:** lose H2H + beat median;
- **0-2 week:** lose H2H + lose median.

These probabilities should be generated from the same simulation draws and therefore sum to approximately 100% within rounding.

This is optional presentation, not another prediction engine.

---

## 9. Missing / unavailable behavior

**Missing is never zero.**

Examples:

- league median disabled = `NOT_APPLICABLE`, not 0%;
- median setting unknown = `STANDINGS_RULE_UNVERIFIED`, not disabled;
- missing opponent/schedule = `UNSIMULABLE`, not 50%;
- missing player projection = unavailable/partial coverage, not zero expected points;
- stale projections = stale evidence, not fresh certainty;
- no simulations completed = unavailable, not 0%.

Preserve coverage/freshness/model-version metadata so the UI can distinguish a high-quality current estimate from a degraded one.

---

## 10. Relationship to Playoff Predictor

Game Day weekly probabilities and the canonical Playoff Predictor should share league rules, score-distribution primitives, and standings semantics where appropriate, but they answer different time horizons:

- **Game Day:** probability of this scoring period's H2H and median outcomes;
- **Playoff Predictor:** probability distribution over the remainder of the regular season and postseason.

A future efficient architecture may reuse the current-week simulation draws as inputs to conditional playoff-odds updates, but do not build a second playoff simulation inside Game Day.

League-median handling must be identical between the two systems.

---

## 11. Relationship to ROS/redraft intelligence

Verified weekly/redraft/ROS projections may improve the weekly scoring distributions when their horizon and format fit the task.

They remain in the seasonal competitive domain and must never leak into canonical dynasty asset value merely because Game Day uses them.

Source lineage and correlation must remain explicit: a projection source used to create the weekly score distribution is not another independent vote after its output has already been consumed by the simulation.

---

## 12. Validation / acceptance criteria

Before the Game Day probability feature is considered complete:

1. identify the one canonical weekly matchup/scoring simulation owner;
2. prove `Win Matchup %` and `Beat Median %` derive from the same league-aware simulation family rather than divergent formulas;
3. test median ON and OFF leagues;
4. for median ON, prove every draw computes the threshold from the same draw's league-wide scores;
5. verify tie-at-median semantics against the host;
6. verify the requested league's custom scoring and lineup configuration are used;
7. verify best-ball leagues use canonical optimal-lineup behavior;
8. verify completed/in-progress/not-started NFL player states are not double projected;
9. test probability bounds and the optional 2-0/1-1/0-2 joint probabilities;
10. archive predictions/results for calibration;
11. compare matchup and median models against simple baselines and prior champion behavior;
12. measure runtime/cache behavior so league-wide joint simulation remains responsive on Game Day;
13. verify public/private output classification;
14. run backend/frontend/livedata/E2E and exact-head CI gates before activation.

---

## 13. Method status

**Win Matchup %:** OWNER-APPROVED GAME DAY REQUIREMENT; existing prediction capability must be audited/calibrated rather than assumed optimal.  
**Beat League Median %:** OWNER-APPROVED / FINAL PRODUCT REQUIREMENT FOR MEDIAN-GAME LEAGUES.  
**One joint weekly simulation:** APPROVED CANONICAL DIRECTION.  
**Exact projection blend / future ML challenger:** EVIDENCE-GATED.  
**Use in dynasty canonical value:** PROHIBITED as a direct input.
