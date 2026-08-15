# Canonical Playoff Predictor — League-Aware Seasonal Probability Engine

> **RECONCILIATION AMENDMENT — 2026-08-14.** Promoted to `main` verbatim from its planning branch by the
> post-B master reconciliation (`docs/POST_B_RECONCILIATION_2026-08-14.md`). No content was changed.
> Its C-Series phase placement and completion evidence live in
> `docs/C_SERIES_SCOPE_MANIFEST.md`.


**Status:** CANONICAL DETAILED PRODUCT/METHODOLOGY SPEC SUPPLEMENT  
**Owner direction captured:** 2026-08-12  
**Canonical family:** ROS / Seasonal Intelligence / Public League / Pick Forecast  
**Execution posture:** APPROVED PRODUCT REQUIREMENT; DO NOT INTERRUPT CURRENT B6/B7 FOUNDATION SEQUENCE UNLESS SEPARATELY AUTHORIZED  
**Public/private posture:** PUBLIC-SAFE probabilities may be shown on league/broadcast surfaces; private decision-intelligence consumers may reuse the same canonical probabilities without creating another simulation engine.

> This is an upgrade/consolidation of existing playoff-odds and championship simulation capabilities. It does **not** authorize a third independent playoff predictor. One canonical engine must own the probabilities.

---

## 1. Owner intent

For every connected/configured dynasty league, the site should automatically understand that league's actual regular-season standings rules and playoff structure and produce, for every team:

1. **MAKE PLAYOFFS %** — probability the team qualifies for the championship playoff field.
2. **EARN BYE %** — probability the team finishes in a seed that receives a first-round playoff bye.
3. **WIN CHAMPIONSHIP %** — probability the team wins the league championship.

Recommended secondary outputs, where useful:

- top-seed probability;
- miss-playoffs probability;
- expected final regular-season wins / standings points under the league's actual rules;
- most-likely seed;
- median final seed;
- complete seed probability distribution;
- finals / semifinal probability where the actual bracket structure supports those concepts;
- confidence / simulation error interval;
- as-of timestamp and model/data freshness.

These are related probabilities from **one season simulation**, not unrelated scores.

---

## 2. Existing implementation is the starting point, not a second system

Current repository code already contains multiple playoff-related implementations, including:

- `src/ros/playoff_sim.py` — ROS-driven regular-season + bracket Monte Carlo;
- `src/public_league/playoff_odds.py` — older/public playoff-odds implementation;
- `src/ros/championship.py` — separate championship Monte Carlo.

The finished architecture must determine which implementation becomes the canonical owner, migrate useful behavior into it, and retire/delegate duplicate probability calculations rather than allowing divergent playoff numbers on different pages.

**One concept, one canonical owner applies here.**

No page, Pick Forecast model, Game Day module, contender classifier, public league section, or trade intelligence feature should independently recalculate playoff/championship odds once the canonical predictor is established.

---

## 3. League settings are authoritative — no universal assumptions

The predictor must derive regular-season standings rules and postseason structure from the **requested league's authoritative league settings/configuration**, not from universal defaults or the owner's current home league.

At minimum establish, where the host/settings make them knowable:

- number of teams in the league;
- whether each scoring period includes an extra game/result against the league median or equivalent all-play threshold;
- how that extra result is recorded in standings;
- number of championship-playoff berths;
- number of bye seeds;
- regular-season end / playoff start;
- playoff bracket length/round count;
- seeding behavior;
- division/wild-card qualification rules if applicable;
- regular-season tiebreak rules used to establish seeds;
- playoff reseeding behavior if applicable;
- any host-specific configuration that changes standings, qualification, seeding, or byes.

Exact Sleeper field mapping must be verified against real league payloads rather than guessed from field names.

If material standings/postseason configuration cannot be demonstrated from authoritative data, the predictor must fail closed as **LEAGUE FORMAT UNVERIFIED / ODDS UNAVAILABLE** rather than silently assume conventional rules.

A structurally known zero is allowed: for a league with **no byes**, `byeOdds = 0` is correct. That is different from missing/unverified bye configuration.

### 3.1 League-median / extra weekly result is first-class standings logic

Many Sleeper leagues, including the owner's primary league, enable an additional weekly result against the league median (`league_average_match` in the observed Sleeper payload). This changes the standings and therefore changes playoff, bye, championship, contender/rebuilder, and Pick Forecast probabilities.

For every simulated regular-season week in a league where the feature is enabled:

1. simulate **all teams' scores for that week as one joint league week**;
2. determine the league-median threshold using the host-faithful rule for that scoring period;
3. award each team its normal head-to-head result;
4. independently award the additional median result according to the host rule;
5. update the same standings state used for playoff qualification, seeding, byes, and tiebreakers.

Do **not** approximate the median game as an independent fixed-probability coin flip. A team's median result is correlated with its simulated weekly score and with the scores of every other team in that same simulation week. The median threshold must therefore be derived from the simulated league-wide score set for that week.

The implementation must also verify how the host treats:

- ties exactly at the median/threshold;
- odd vs even league sizes;
- any setting changes during a season;
- completed historical weeks and how the extra result appears in the host standings/record fields.

Current standings ingestion must reproduce the host's **actual record to date**, including already-earned median wins/losses. Future simulation must then add only the remaining median results. Do not double-count historical median results if the host's current win/loss fields already include them.

When league median is disabled, the simulator must not award a second weekly result.

A regression suite must include otherwise-identical leagues with median ON vs OFF and prove the resulting expected records, seed distributions, and playoff probabilities can differ.

---

## 4. Canonical probability model

The predictor should simulate the actual remainder of the season and postseason rather than converting a power ranking directly into a probability.

Conceptual simulation flow:

**current league state**  
+ **remaining regular-season schedule**  
+ **team future scoring distributions**  
+ **league scoring/lineup format**  
+ **standings rules, including league-median games when enabled**  
→ simulate each remaining league week jointly  
→ award head-to-head + any configured extra standings results  
→ apply actual qualification + tiebreak rules  
→ assign seeds/byes  
→ simulate the actual playoff bracket  
→ aggregate Make Playoffs / Bye / Championship probabilities.

Every simulation run should produce one internally coherent season outcome. A team cannot win a simulated championship without first qualifying for that simulated playoff field.

---

## 5. Inputs

The canonical predictor may consume defensible inputs including:

- current wins/losses/ties or equivalent standings state;
- current league-median/all-play record component when applicable;
- points-for and the actual league tiebreak information;
- remaining schedule;
- current roster construction;
- canonical ROS player rankings/projections;
- verified redraft/ROS source evidence from the seasonal-intelligence domain;
- team ROS strength;
- injury/availability distributions where supported;
- custom league scoring;
- starter/flex/Superflex/IDP requirements;
- best-ball vs managed-lineup setting;
- lineup/replacement model where appropriate;
- team depth and volatility where empirically justified.

Do not use long-horizon dynasty market value as a direct substitute for expected current-season scoring. Dynasty value and seasonal competitive strength are separate concepts.

When the ROS/redraft archive is expanded, improved seasonal evidence may challenge the current future-scoring model, but production changes remain evidence-gated.

---

## 6. Probability outputs and invariants

For every team, expose the three owner-required headline metrics:

- `makePlayoffsProbability`
- `byeProbability`
- `championshipProbability`

Exact API names may preserve/backward-compatible existing fields such as `playoffOdds`, `byeOdds`, and `championshipOdds`; do not fork the contract just for naming preference.

Required logical invariants:

- `0 <= championshipProbability <= makePlayoffsProbability <= 1`;
- `0 <= byeProbability <= makePlayoffsProbability <= 1`;
- if the verified league has zero bye slots, every team's bye probability is exactly 0;
- across a fully simulated league, expected playoff qualifiers aggregate approximately to the configured number of playoff berths (within Monte Carlo error);
- expected bye recipients aggregate approximately to the configured number of bye slots;
- championship probabilities aggregate approximately to 1.0 when a single champion is always produced;
- eliminated teams have 0 playoff/bye/championship probability once elimination is mathematically certain;
- clinched playoff teams have 100% playoff probability once qualification is mathematically certain;
- a clinched bye may become 100% only when actual remaining scenarios prove it;
- a completed season may show factual 0/100 outcomes, but a preseason/no-data state must never manufacture certainty;
- in a median-game league, each completed simulated week must contribute exactly the host-defined number of standings decisions per team (normally one H2H result plus one median result) unless a verified host exception applies.

---

## 7. Tiebreakers and seeding

Do not permanently hard-code `wins then points-for` unless that is verified to reproduce the requested league's actual seeding rules.

The implementation must trace the host's available standings/settings and establish the real qualification/seeding rules, including how median-game results are incorporated into the official record.

Where a host rule cannot be reproduced exactly:

- declare the unsupported tiebreak component;
- quantify or describe the uncertainty where possible;
- avoid presenting exact-looking probabilities as fully host-faithful.

Do not use a coin flip merely because the implementation lacks the host's real tiebreak rule unless the host itself specifies a random tiebreak.

---

## 8. Playoff bracket fidelity

Championship probability must simulate the **actual configured bracket**, not a generic six-team bracket.

The model must support the structures actually encountered in connected leagues, including varying:

- playoff field size;
- number of byes;
- number of rounds;
- reseeding vs fixed bracket where known;
- championship week structure where known.

Do not infer a six-team field internally after correctly reading another `playoffSeeds` value at the API boundary.

If the host exposes multi-week playoff matchups, two-week championship rounds, consolation effects, or other meaningful bracket rules, investigate them explicitly before claiming exact championship odds.

---

## 9. Best-ball and lineup-format behavior

For best-ball leagues, the predictor should use the canonical optimal-lineup machinery rather than a start/sit approximation. Depth may legitimately affect both expected scoring and variance because the optimal lineup can capture bench spike weeks.

For managed-lineup leagues, do not credit the bench as though best-ball automatically selects it.

The playoff predictor must consume the same canonical lineup eligibility rules used elsewhere, including Superflex, flex, TE, and hybrid IDP eligibility.

League-median comparison must use the same simulated final weekly team score that the league would use for standings, including best-ball optimization when the league is best ball.

---

## 10. Missing-data behavior

**Missing is never zero.**

Examples:

- unknown postseason structure ≠ six playoff teams / two byes;
- unknown median-game setting ≠ disabled;
- no ROS projection ≠ zero expected points;
- missing future schedule ≠ zero remaining games;
- unverified tiebreak ≠ known tiebreak;
- stale team-strength data ≠ fresh current-season outlook;
- no simulations run ≠ 0% chance.

Surface explicit states such as:

- `UNAVAILABLE`;
- `UNSIMULABLE`;
- `LEAGUE_FORMAT_UNVERIFIED`;
- `PLAYOFF_FORMAT_UNVERIFIED`;
- `STANDINGS_RULE_UNVERIFIED`;
- `SCHEDULE_INCOMPLETE`;
- `PARTIAL_ROS_COVERAGE`;
- `STALE_INPUTS`.

---

## 11. Simulation convergence / uncertainty

Do not treat a fixed arbitrary simulation count as proof of precision.

Prefer adaptive/convergence-aware simulation or another method that reports remaining Monte Carlo uncertainty.

Display percentages at a precision justified by the simulation and model quality. The API should preserve enough metadata to audit:

- simulations completed;
- convergence state;
- probability confidence/error intervals where supported;
- random seed policy for reproducible test/evaluation runs;
- model version;
- source/input snapshot timestamps;
- league-format/standings-rule fingerprint, including median-game state.

Simulation error is only one uncertainty component. A narrow Monte Carlo interval does not mean the underlying player/team forecast model is perfectly calibrated.

---

## 12. Historical prediction archive and calibration

Archive predictor snapshots through the season so the model can be evaluated honestly later.

At minimum preserve by league/team/as-of date:

- Make Playoffs %;
- Bye %;
- Championship %;
- current record/seed;
- median-game/all-play setting and relevant standings-rule fingerprint;
- relevant model version;
- playoff-format fingerprint/settings;
- ROS/team-strength snapshot version;
- schedule state;
- simulation count/convergence;
- realized final outcome.

Use leakage-safe historical evaluation to measure:

- playoff probability calibration;
- bye probability calibration;
- championship probability calibration;
- Brier score / log loss or suitable probabilistic scoring rules;
- calibration curves/reliability diagrams;
- discrimination versus simple baselines such as current standings or points-for;
- whether ROS/redraft evidence improves over empirical scoring history alone;
- whether league-median ON/OFF leagues are reproduced without format-specific bias.

Do not promote a more complex predictor merely because it sounds more sophisticated. It must beat defensible baselines out of sample.

---

## 13. Relationship to Pick Forecast

Pick Forecast may consume the canonical Playoff Predictor because final team outcome often affects future-pick slot distributions.

However:

- playoff/championship probabilities and ROS team strength are correlated descendants, not independent votes;
- Pick Forecast must model that lineage rather than counting both as separate evidence;
- league-median results must already be incorporated into the canonical final-standings distribution before Pick Forecast consumes it;
- playoff outcome should affect **specific expected pick slot/distribution**;
- dynasty value of that resulting pick/slot remains owned by the canonical dynasty valuation system.

Archive the playoff prediction used by each historical Pick Forecast so future backtests know exactly what information was available at the time.

---

## 14. Relationship to contender/rebuilder classification

Current-season contender status should use canonical playoff/championship probabilities as an important seasonal outcome signal.

Do not equate `low championship probability` with `bad dynasty roster`.

Keep separate:

- current-season contention probability;
- long-term dynasty asset strength;
- age/window/future-pick position;
- confidence.

Because median-game standings affect qualification probability, contender/rebuilder logic must consume the canonical predictor output rather than independently approximating record odds without the median rule.

---

## 15. UI requirement

The predictor should be easy to understand at a glance.

For each team, the primary presentation should prominently show:

**Make Playoffs** — `XX%`  
**Earn Bye** — `XX%`  
**Win Championship** — `XX%`

Optional drill-down may show expected wins/standings record, likely seed, complete seed distribution, top-seed %, uncertainty, remaining schedule strength, and major drivers.

For leagues with an extra median game, the drill-down may also show useful derived context such as projected H2H record, projected median-game record, or the probability of finishing above the median in a given remaining week, but these are explanatory outputs rather than separate prediction engines.

Do not bury the three owner-requested probabilities behind an opaque power score.

Public-safe league/broadcast surfaces may show these probabilities as sports-broadcast information. Private surfaces may additionally explain roster/ROS drivers when that explanation would expose decision intelligence.

---

## 16. Validation / acceptance criteria

Before calling the Playoff Predictor complete:

1. identify the canonical current implementation and eliminate/delegate duplicate probability engines;
2. prove every active configured league reads its own postseason **and standings** settings;
3. RED test a league whose playoff field/bye count differs from 6/2 and prove the old default path is wrong;
4. RED test two otherwise-identical leagues with `league_average_match` ON vs OFF and prove the simulator produces different legal standings distributions when scores warrant it;
5. for median ON, prove each simulated week derives the threshold from that same week's simulated league-wide score set and awards the extra result correctly;
6. prove historical record-to-date matches the host including already-earned median results, with no double counting when future sims begin;
7. prove zero-bye leagues emit genuine 0% bye probability rather than unavailable or a default;
8. test at least two materially different league structures;
9. verify exact requested-league roster/scoring/schedule/settings ownership — no cross-league chimera;
10. test probability invariants and aggregate berth/bye/championship totals;
11. verify completed-season and preseason/unsimulable behavior separately;
12. verify bracket simulation honors configured playoff size and bye count end to end;
13. compare the canonical model against simple historical baselines;
14. archive predictions for future calibration;
15. measure runtime/cache cost and avoid duplicating expensive simulations for separate surfaces;
16. run full backend/frontend/livedata/E2E gates and exact-head CI;
17. document residual unsupported host rules explicitly.

---

## 17. Current known implementation gaps to preserve for future repair

At the time this owner requirement was recorded:

- `src/ros/playoff_sim.py` already exposed playoff, bye, top-seed, seed-distribution, and championship probabilities, but its callable defaults remained `playoff_seeds=6` and `bye_seeds=2`;
- the scheduled per-league cache refresh called the simulator with the league's best-ball flag but did not thread league-specific playoff-seed/bye configuration into that call;
- `src/ros/championship.py` duplicated regular-season/bracket simulation and contained six-team assumptions inside its bracket logic;
- the future regular-season loop in `src/ros/playoff_sim.py` updated standings from simulated head-to-head results but did not award an additional weekly league-median result;
- the owner's observed 2026 Sleeper league payload has `league_average_match: 1` and `playoff_teams: 7`, so both the median-game omission and generic playoff defaults are directly relevant to the primary league rather than theoretical edge cases.

Therefore the target is **not feature creation from zero**. The target is:

> **canonicalize the existing simulation family, derive all material standings and postseason rules from the requested league, simulate league-median games when enabled, expose the owner-required three probabilities consistently, archive them, and validate their calibration.**

Reproduce these facts on the implementation baseline before repairing them; current code may evolve before this backlog item is activated.

---

## 18. Method status

**Product requirement:** OWNER-APPROVED / FINAL DIRECTION.  
**League-median handling:** REQUIRED FIRST-CLASS STANDINGS BEHAVIOR WHEN ENABLED BY THE REQUESTED LEAGUE.  
**Exact simulation implementation:** EXISTING BUT REQUIRES CANONICALIZATION, LEAGUE-SETTINGS FIDELITY, MEDIAN-GAME SUPPORT, AND VALIDATION.  
**ROS/redraft model improvements:** EVIDENCE-GATED.  
**Use in dynasty asset valuation:** PROHIBITED as a direct dynasty-value input.  
**Use in seasonal intelligence, Pick Forecast, Game Day, public-safe league broadcast, and contender classification:** APPROVED through the canonical predictor with lineage preserved.
