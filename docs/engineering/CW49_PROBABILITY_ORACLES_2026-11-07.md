# CW-49 independent oracles: playoff, title, draft-slot and Game Day probabilities

Owner directive 2026-11-07 (sitewide feature verification), Parts 2–4. Follows `docs/engineering/CW49_ORACLES.md`
(FAAB, BDVM ROS blend). Result: both engines match their independent oracles. Two defects were repaired in the
canonical playoff owner. Neither changes a number any live league gets today.

## What the engines must do (controlling requirements)
| Engine | Requirement | Live path |
|---|---|---|
| Playoff / bye / seed / title / finals / semis, `src/ros/playoff_sim.py` | `docs/PLAYOFF_PREDICTOR_SPEC.md` §§1–4: one season simulation. It must apply the league's own qualification, seeding, tiebreak and bracket rules, including the median game (§3.1) and "division/wild-card qualification rules if applicable" (§3). If a rule cannot be verified it must fail closed, never assume. | `/api/public/league/rosPlayoffOdds`, `playoffOdds` and `rosChampionship` all read `canonical_forecast`. That is the scheduled `src/ros/scrape.py` file, or a live `simulate_playoff_odds` run. No flag; `playoff_ros_counted_once` only picks the D11 equation and defaults off. |
| Draft-slot distribution (same run) | Owner decision 2026-10-04 (`docs/picks/DRAFT_ORDER_RULE.md`, `config/leagues/draft_order_rules.json`): worst record picks first; teams tied on record go by lower Points For, recursively; the record is head-to-head with ties as half a win (`DRAFT_ORDER_RECORD_BASIS`). A league with no recorded rule gets no forecast. | Same payload, read by the pick projector and `src/trade/pick_market.py` |
| Game Day Win Matchup % / Beat League Median %, `src/ros/game_day_sim.py` | `docs/GAME_DAY_PROBABILITY_SPEC.md` §§2–3, 6, 8–9: one joint draw per iteration and a per-draw middle-two median, where landing exactly on it is a tie. Banked points are certain; only the remainder is drawn. Must never publish fabricated 0% or 50% (`NOT_APPLICABLE`, `STANDINGS_RULE_UNVERIFIED`, `UNSIMULABLE`). | `GET /api/matchup/intel` calls `matchup_intel.run_league_simulation`, then `get_cached_league_week_simulation`. `game_day_live_game_state` and `sleeper_weekly_projections` are LIVE. |

## Relationship to #2135 / #2143 (merged)
Written in parallel with PRs #2135 and #2143, which merged `tests/ros/test_probability_oracles.py` (test-only
oracles for `playoff_sim`, draft slots and Game Day). That file is NOT the sole coverage and neither is this one.
The two sets use different, independently written oracles and fixtures over the same engines (this PR adds 8-team
and fixed-bracket enumeration, metamorphic checks, the closed-form PF tiebreak and exchangeable-league Game Day
cases), so they cross-check each other; no test here repeats a merged case verbatim. What only this PR adds is the
two production repairs below and their regression tests.

## Files
- `tests/ros/test_playoff_probability_oracles.py`: 29 tests, independent.
- `tests/game_day/test_game_day_probability_oracles.py`: 9 tests, independent.
- `tests/ros/test_playoff_divisions_fail_closed.py`: 15 regression tests for the two repairs. 12 of them fail on the pre-repair code.
- Repairs: `src/public_league/playoff_structure.py` and `src/ros/playoff_sim.py`.

## Independent oracles (the expected value is computed by test code, never by a production helper)
| Group | Oracle | Production outputs checked |
|---|---|---|
| Season + bracket, 6 and 8 teams; brackets: re-seeded 3/1 bye, fixed 6/2 byes, re-seeded 7/1 bye (`dynasty_main`'s shape), fixed 5/3 byes | Every win/loss vector of the remaining games is enumerated. Each game is `P(N(Δμ, √(σa²+σb²)) > 0)`, computed with `statistics.NormalDist`; with μ/σ ≥ 6 the zero floor cannot bite (asserted). Points-For-to-date gaps exceed any possible remaining scoring, so the PF tiebreak is deterministic (asserted). An independent bracket enumerator covers re-seed, and fixed brackets as "slot s meets slot m+1−s". | playoff, miss, bye and top-seed odds; the full seed distribution; expectedWins; title, finals and semis odds; expectedFinish; the full draft-slot distribution; finalWins mean |
| Bracket only (season over), fields 2–8 × fixed/re-seed | Path-by-path bracket enumeration plus the documented placement convention | title, finals, semis, expectedFinish. A decided seeding must be published exactly 1/0. |
| Median game counted (D3) | Four i.i.d. teams, so all 24 score orderings per week are equally likely (576 combinations over 2 weeks). The top two of four beat the middle-two average. | Seeding counts the median result. The draft order must not; it uses the head-to-head basis, and a median tie already on the books leaves it exactly once. |
| PF tiebreak decided by the simulated week | Closed form: `P(A seeded over B) = P(S_A > S_B) = Φ(10/√325)`; the draft order is the complement (lower PF picks first); `P(C picks 1st) = Φ(5/√18)`; final PF mean is 1620 | top seed, title, draft slots 1 and 3, finalPointsFor |
| Draft rule | A literal recursive reading of the owner's text (group by record, then by PF, leftovers are unresolved ties), compared with `draft_order` over 400 random leagues. `draft_order_from_standings` gives the same order with ties as half a win; a missing input raises. | order, `unresolved_ties`, refusal |
| Game Day win %, projected mean / p10 / p50 / p90 | Managed league: a team score is a sum of independent normals (banked + remaining, sd = max(0.5, r·cv)), so win % is Φ. Quantile tolerance uses `√(q(1−q))/(f(x_q)√n)`. Bench players are excluded from score and banked points. | win %, ties, range, points_banked |
| Beat median % and the 2-0 / 1-1 / 0-2 buckets | Simpson quadrature over each team's score, with a Poisson-binomial count of teams above it | median % and all four joint buckets |
| Exchangeable best-ball league, 6 teams, real fallback CVs, zero floor active | Exact permutation enumeration: win 1/2, median 1/2, 2-0 = 12/30, 1-1 via H2H = 3/30. Holds whatever the score shape. | all six outcomes |
| Best ball, one QB slot, two QBs | `1 − ∫F₁F₂f_B`; Clark's exact mean of a max of two normals; `P(QB1 in lineup) = Φ(Δ/θ)` | win %, projected mean, player_lineup_pct |
| Two-team median league; finished week; finished week landing on the median | Algebra: the median leg equals the matchup draw for draw. A finished week is certain (100/0, range collapsed). Exactly on the median is a certain tie, never a win and in no joint bucket. | both legs |

Tolerance is `4.5·√(p(1−p)/n)` plus rounding at a fixed seed. Exact 0 and 1 must match exactly.

Mutation check (production temporarily edited, then reverted). Every mutation was killed:
- seeding PF ascending: 8 tests
- draft PF descending: 9
- fixed bracket played as re-seed: 4
- re-seed played as fixed: 4
- semifinal losers placed 3 and 4: 13
- recorded ties not credited: 4
- draft counting median wins: 1
- median taken as mean (playoff): 1
- in-progress draw ignoring banked points: 4
- completed player redrawn: 4
- median as mean (Game Day): 1
- tie at median counted as a win: 1
- managed league summing the bench: 4

## Metamorphic and invariant checks
- Renaming owners so the ids sort in reverse permutes the odds within two-sample noise (playoff). Renaming Game Day teams leaves every number byte-identical, and reordering them still matches Φ.
- An extra win never lowers that team's playoff, bye or top-seed odds, and never raises its opponent's. Verified in the exact oracle; the engine is checked against the oracle in both states.
- Extra banked points never lower Game Day win % or median %. Completed players draw nothing, so this is checked draw for draw.
- Clinched teams are exactly 1.0 and eliminated teams exactly 0.0, while an undecided top seed stays strictly between. The Wilson upper bound is 1.
- Sums hold: playoff = seeds, bye = byes, title = 1, finals = 2, semis = 4; every seed column and every draft-slot column sums to 1; title ≤ finals ≤ semis ≤ playoff.

## Defects found and repaired (canonical owner, tests added first)
1. **Divisions were ignored.** Sleeper qualifies every division winner for the playoffs ([Sleeper blog](https://sleeper.com/blog/how-do-fantasy-playoffs-work): "each division winner will qualify for the playoffs"). The engine never read `settings.divisions` and seeded on overall record only. The live `dynasty_main` stated `divisions: 3` on 2026-10-26 (`docs/audits/evidence/league_rules_dynasty_main_2026-10-26.json`) and `divisions: 0` on 2026-11-07 (read-only GET today), so its published odds ignored the division-winner rule while divisions were on.
   - **Superseded by the owner on 2026-11-08:** `dynasty_main`'s divisions carry no playoff advantage, so the blanket refusal was wrong for it. The rule is now recorded per league (`config/leagues/playoff_rules.json`); only a league with divisions ON and NO record is refused, and only for qualifying (draft-slot and division-title odds survive). See `tests/ros/test_league_division_rules.py`.
   - **Repair (2026-11-07):** `PlayoffStructure` now carries `divisions` / `divisionsReason`. `simulate_playoff_odds` refuses with `league_divisions_unmodeled` (or `divisions_setting_not_recognised`), and "not a 0% chance" detail text, as PLAYOFF_PREDICTOR_SPEC §3 requires. Because `playoffStructure` includes the setting, a cached forecast from before a switch is never served beside it.
   - **Today:** both live leagues are unaffected (`dynasty_main` is `0`; `dynasty_new` omits the key).
   - **One-time side effect:** cached `data/ros/sims` files written before this change lack the new key. They are recomputed live until the next 2-hourly refresh rewrites them.
2. **A refused trade arm read as a zero-impact trade.** `simulate_trade_impact` fell through a refused simulation with empty deltas, `meaningfulDeltas: 0` and `nSimulations = 0 or n_simulations`, i.e. the requested count. It now returns the refusal (`unsimulable`, `nSimulations: 0`). The function has no live route today; the League Twin documents it.

## Owner questions (methodology, deliberately not changed)
1. **Divisions — ANSWERED by the owner 2026-11-08** for `dynasty_main` (no division advantage; ties to points scored; the draft-slot forecast survives). Still open only for a future league that plays Sleeper's default. Original question: How does Sleeper seed division winners against wild cards, and what breaks a tie inside a division? Simulating division leagues instead of refusing them needs both answers. Separately: should the draft-slot forecast survive this refusal, given the draft order ignores divisions? It is withheld now, following the median-unknown refusal precedent.
2. **Absent `divisions` key.** It is read as "no divisions" because the host states a count only after divisions are configured. Confirm, or make absent fail closed. That would withhold `dynasty_new`'s odds.
3. **In-game variance.** The remaining-production sd is `cv × remaining` (constant CV), so with 25% of a game left the sd is 25% of the pregame sd, not roughly 50% under a √time model. Is linear the intended model? The AL-4a scorecard can decide.
4. **Zero floor.** `max(0, N(r, cv·r))` lifts a player's simulated mean above the stated projection, which `PlayerWeek` documents as the mean: +0.75% at CV 0.55, +1.7% at 0.65, +13.6% at the 1.20 clamp. The playoff pre-sim shares this. Keep it, or mean-correct it?
5. **Seeding tiebreak.** PF descending comes from the docstring's "every Sleeper league we've observed". The host page says points "typically" break ties and head-to-head "could also be used". Not verified per league.

## Predictive accuracy (question 3), reported only
- **Playoff and title odds:** `src/ros/forecast_archive` captures forecasts but has no evaluator, so they are uncalibrated and disclosed as "not yet calibrated" (`docs/research/amath/S01_FORECAST_CALIBRATION_LEDGER_STATUS_2026-11-06.md`).
- **Game Day:** the AL-4a `game_day_calibration` scorecard runs weekly from a pregame archive that began in week 8, so early runs report `insufficient_sample`. It still runs on fallback CVs (RPA-F-021).
- No new backtest was run.

## Gaps (not covered by an independent oracle)
- Construction of team distributions: empirical, pool or pre-sim basis, ROS z blend, depth lift.
- The adaptive pre-sim and the convergence stopping rule.
- Median-game seeding with distinct team strengths (only the exchangeable case is exact).
- Fixed-bracket placements when 8 or more teams remain after round one (brackets of 9–16).
- The live Game Day input assembly (`game_day_week` / `game_day_live` / `matchup_intel`). Existing regression tests only, plus the hand-computed `regulation_fraction_remaining` cases.
