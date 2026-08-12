# Canonical Playoff Predictor — League-Aware Seasonal Probability Engine

**Status:** CANONICAL DETAILED PRODUCT/METHODOLOGY SPEC SUPPLEMENT  
**Owner direction captured:** 2026-08-12  
**Canonical family:** ROS / Seasonal Intelligence / Public League / Pick Forecast  
**Execution posture:** APPROVED PRODUCT REQUIREMENT; DO NOT INTERRUPT CURRENT B6/B7 FOUNDATION SEQUENCE UNLESS SEPARATELY AUTHORIZED  
**Public/private posture:** PUBLIC-SAFE probabilities may be shown on league/broadcast surfaces; private decision-intelligence consumers may reuse the same canonical probabilities without creating another simulation engine.

> This is an upgrade/consolidation of existing playoff-odds and championship simulation capabilities. It does **not** authorize a third independent playoff predictor. One canonical engine must own the probabilities.

---

## 1. Owner intent

For every connected/configured dynasty league, the site should automatically understand that league's actual playoff structure and produce, for every team:

1. **MAKE PLAYOFFS %** — probability the team qualifies for the championship playoff field.
2. **EARN BYE %** — probability the team finishes in a seed that receives a first-round playoff bye.
3. **WIN CHAMPIONSHIP %** — probability the team wins the league championship.

Recommended secondary outputs, where useful:

- top-seed probability;
- miss-playoffs probability;
- expected final regular-season wins;
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

The finished architecture must determine which implementation becomes the canonical owner, migrate any useful behavior into it, and retire/delegate duplicate probability calculations rather than allowing divergent playoff numbers on different pages.

**One concept, one canonical owner applies here.**

No page, Pick Forecast model, Game Day module, contender classifier, public league section, or trade intelligence feature should independently recalculate playoff/championship odds once the canonical predictor is established.

---

## 3. League settings are authoritative — no universal 6-team / 2-bye assumption

The predictor must derive the postseason structure from the **requested league's authoritative league settings/configuration**, not from universal defaults or the owner's current home league.

At minimum establish, where the host/settings make them knowable:

- number of teams in the league;
- number of championship-playoff berths;
- number of bye seeds;
- regular-season end / playoff start;
- playoff bracket length/round count;
- seeding behavior;
- division/wild-card qualification rules if applicable;
- regular-season tiebreak rules used to establish seeds;
- playoff reseeding behavior if applicable;
- any host-specific configuration that changes who qualifies or who receives a bye.

Exact Sleeper field mapping must be verified against real league payloads rather than guessed from field names.

If the postseason configuration cannot be demonstrated from authoritative data, the predictor must fail closed as **PLAYOFF FORMAT UNVERIFIED / ODDS UNAVAILABLE** rather than silently assume six playoff teams and two byes.

A structurally known zero is allowed: for a league with **no byes**, `byeOdds = 0` is correct. That is different from missing/unverified bye configuration.

---

## 4. Canonical probability model

The predictor should simulate the actual remainder of the season and postseason rather than converting a power ranking directly into a probability.

Conceptual simulation flow:

**current league state**  
+ **remaining regular-season schedule**  
+ **team future scoring distributions**  
+ **league scoring/lineup format**  
→ simulate remaining regular season  
→ apply actual qualification + tiebreak rules  
→ assign seeds/byes  
→ simulate the actual playoff bracket  
→ aggregate Make Playoffs / Bye / Championship probabilities.

Every simulation run should produce one internally coherent season outcome. A team cannot win a simulated championship without first qualifying for that simulated playoff field.

---

## 5. Inputs

The canonical predictor may consume defensible inputs including:

- current wins/losses/ties;
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

Exact API names may preserve/backward-compat existing fields such as `playoffOdds`, `byeOdds`, and `championshipOdds`; do not fork the contract just for naming preference.

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
- a completed season may show factual 0/100 outcomes, but a preseason/no-data state must never manufacture certainty.

---

## 7. Tiebreakers and seeding

Do not permanently hard-code `wins then points-for` unless that is verified to reproduce the requested league's actual seeding rules.

The implementation must trace the host's available standings/settings and establish the real qualification/seeding rules.

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

---

## 10. Missing-data behavior

**Missing is never zero.**

Examples:

- unknown postseason structure ≠ six playoff teams / two byes;
- no ROS projection ≠ zero expected points;
- missing future schedule ≠ zero remaining games;
- unverified tiebreak ≠ known tiebreak;
- stale team-strength data ≠ fresh current-season outlook;
- no simulations run ≠ 0% chance.

Surface explicit states such as:

- `UNAVAILABLE`;
- `UNSIMULABLE`;
- `PLAYOFF_FORMAT_UNVERIFIED`;
- `SCHEDULE_INCOMPLETE`;
- `PARTIAL_ROS_COVERAGE`;
- `STALE_INPUTS`.

---

## 11. Simulation convergence / uncertainty

Do not treat a fixed arbitrary simulation count as proof of precision.

Prefer adaptive/convergence-aware simulation or another method that reports the remaining Monte Carlo uncertainty.

Display percentages at a precision justified by the simulation and model quality. The API should preserve enough metadata to audit:

- simulations completed;
- convergence state;
- probability confidence/error intervals where supported;
- random seed policy for reproducible test/evaluation runs;
- model version;
- source/input snapshot timestamps.

Simulation error is only one uncertainty component. A narrow Monte Carlo interval does not mean the underlying player/team forecast model is perfectly calibrated.

---

## 12. Historical prediction archive and calibration

Archive predictor snapshots through the season so the model can be evaluated honestly later.

At minimum preserve by league/team/as-of date:

- Make Playoffs %;
- Bye %;
- Championship %;
- current record/seed;
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
- whether ROS/redraft evidence improves over empirical scoring history alone.

Do not promote a more complex predictor merely because it sounds more sophisticated. It must beat defensible baselines out of sample.

---

## 13. Relationship to Pick Forecast

Pick Forecast may consume the canonical Playoff Predictor because final team outcome often affects future-pick slot distributions.

However:

- playoff/championship probabilities and ROS team strength are correlated descendants, not independent votes;
- Pick Forecast must model that lineage rather than counting both as separate evidence;
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

This allows a team to be an aging 2026 title favorite or a non-contending 2026 team with an elite dynasty future without misclassification.

---

## 15. UI requirement

The predictor should be easy to understand at a glance.

For each team, the primary presentation should prominently show:

**Make Playoffs** — `XX%`  
**Earn Bye** — `XX%`  
**Win Championship** — `XX%`

Optional drill-down may show expected wins, likely seed, complete seed distribution, top-seed %, uncertainty, remaining schedule strength, and major drivers.

Do not bury the three owner-requested probabilities behind an opaque power score.

Public-safe league/broadcast surfaces may show these probabilities as sports-broadcast information. Private surfaces may additionally explain roster/ROS drivers when that explanation would expose decision intelligence.

---

## 16. Validation / acceptance criteria

Before calling the Playoff Predictor complete:

1. identify the canonical current implementation and eliminate/delegate duplicate probability engines;
2. prove every active configured league reads its own postseason settings;
3. RED test a league whose playoff field/bye count differs from 6/2 and prove the old default path is wrong;
4. prove zero-bye leagues emit genuine 0% bye probability rather than unavailable or a default;
5. test at least two materially different league structures;
6. verify exact requested-league roster/scoring/schedule/settings ownership — no cross-league chimera;
7. test probability invariants and aggregate berth/bye/championship totals;
8. verify completed-season and preseason/unsimulable behavior separately;
9. verify bracket simulation honors configured playoff size and bye count end to end;
10. compare the canonical model against simple historical baselines;
11. archive predictions for future calibration;
12. measure runtime/cache cost and avoid duplicating expensive simulations for separate surfaces;
13. run full backend/frontend/livedata/E2E gates and exact-head CI;
14. document residual unsupported host rules explicitly.

---

## 17. Current known implementation gap to preserve for future repair

At the time this owner requirement was recorded, `src/ros/playoff_sim.py` already exposed playoff, bye, top-seed, seed-distribution, and championship probabilities, but its callable defaults remained `playoff_seeds=6` and `bye_seeds=2`.

The scheduled per-league cache refresh called the simulator with the league's best-ball flag but did not thread league-specific playoff-seed/bye configuration into that call.

A second `src/ros/championship.py` simulator also duplicated regular-season/bracket simulation and contained six-team assumptions inside its bracket logic.

Therefore the target is **not feature creation from zero**. The target is:

> **canonicalize the existing simulation family, derive postseason rules from the requested league, expose the owner-required three probabilities consistently, archive them, and validate their calibration.**

Reproduce these facts on the implementation baseline before repairing them; current code may evolve before this backlog item is activated.

---

## 18. Method status

**Product requirement:** OWNER-APPROVED / FINAL DIRECTION.  
**Exact simulation implementation:** EXISTING BUT REQUIRES CANONICALIZATION, LEAGUE-SETTINGS FIDELITY, AND VALIDATION.  
**ROS/redraft model improvements:** EVIDENCE-GATED.  
**Use in dynasty asset valuation:** PROHIBITED as a direct dynasty-value input.  
**Use in seasonal intelligence, Pick Forecast, Game Day, public-safe league broadcast, and contender classification:** APPROVED through the canonical predictor with lineage preserved.
