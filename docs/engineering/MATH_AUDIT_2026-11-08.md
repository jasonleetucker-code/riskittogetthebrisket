# Mathematical correctness audit — 2026-11-08

Owner directive 2026-11-08 ("Finish the mathematical correctness audit"), §3.
This record does not change any methodology. For each quantitative feature it
lists:
- **Method and meaning:** the method, and what the output means to a user.
- **Oracle:** the INDEPENDENT oracle that checks it. An oracle is never the
  function under test called twice.
- **Gap:** what is still unverified.

Test files named here exist on `main` (or on the PR named beside them).

## Findings this pass

| # | Finding | Evidence | Action |
|---|---|---|---|
| F1 | CW-49 refused playoff, title and draft-slot odds for every league with Sleeper divisions ON. That is wrong for `dynasty_main`: per the owner, its divisions give no berth, seeding or bye. | Owner rules table. 2025 host bracket: a four-way 15-11 tie seeded strictly by points for (rosters 8, 2, 5, 3 → seeds 2–5). | Fixed in #2149: per-league `config/leagues/playoff_rules.json`, division-title odds, draft slots survive. |
| F2 | The best-ball points model is uncalibrated at TEAM level. The simulated weekly mean ranges 117–524 against a realized 241–436 (8 weeks, live 2026). The spread between teams is about 2.3× the real one. As a result, every team shows 0% / 100% at Week 8, and projected final points for are inflated (Brent: 6,632 projected vs a 6,105 pace). | Local run of `_build_team_distributions` on the live snapshot (2026-11-08); `pointsModelSource: fallback-constants`. Table below. | Not changed. This is RPA-LGI-008, under a pre-registered calibration study (`docs/league-intelligence/ROS_SCALE_CALIBRATION_*`) with no challenger passing yet. Recommendation: add team-level checks (simulated weekly mean and sd vs realized, per team) to that study's gates. |
| F3 | The playoff chart showed a simulated 0 or 1 as "0%" / "100%" mid-season. | `PlayoffOddsChart.jsx` label code. | Fixed in #2149: reads "<1%" / ">99%" until the season is final. |
| F4 | User-facing copy overstated what was known:<br>• "samples each owner's actual weekly history" (false in best ball)<br>• "market overvalues"<br>• "STRONG BUY"<br>• "61% confidence"<br>• "Hit %"<br>• "clear winner" | Copy vs the code path behind each phrase. | Fixed in #2149 (subtitle) and #2150 (the rest). |

F2 measurement (live `dynasty_main`, weeks 1–8 final; simulated = the served model's per-team weekly distribution):

| Team | Simulated mean / sd | Realized mean / sd |
|---|---|---|
| Brent | 524.5 / 42.9 | 436.2 / 25.6 |
| Jason | 493.1 / 37.8 | 391.4 / 45.3 |
| Joey | 353.9 / 39.3 | 388.1 / 50.4 |
| Kich | 243.2 / 28.6 | 381.5 / 39.0 |
| Ty | 163.7 / 24.6 | 315.1 / 53.5 |
| Roy | 117.3 / 18.7 | 241.2 / 45.2 |

**Check on F2.** An independent simulation built from each team's REALIZED weekly mean and sd, with the real remaining schedule and the median game, also puts the 7th / 8th playoff line at >99.9% / <0.1%. The weekly median game doubles the record gap, so the Week-8 qualification answer is robust to F2. Finer outputs carry the bias:
- seed odds;
- title odds;
- projected points for;
- expected wins (Roy: 0.0 of 12 remaining games).

## Feature ledger

| Feature | Owner | Method and meaning | Independent oracle | Gap |
|---|---|---|---|---|
| Playoff qualification / seeding | `src/ros/playoff_sim.py` | Monte Carlo of the remaining regular season. Qualifying and seeding use the host's standings record (median game included when counted), ties broken by points for, per the league's record. | `tests/ros/test_playoff_probability_oracles.py` (exact enumeration); `tests/ros/test_league_division_rules.py` (#2149: hand-computed finished seasons, 3-way tie, one-week enumeration); host brackets 2024 / 2025. | F2 (team score model). Season-level calibration waits for January 2027 (RPA-LGI-006). |
| Division titles | same | Best record in the division, then points for, counted per simulated season; separate from playoff odds. | `test_league_division_rules.py`: 1/4 vs 3/4 enumeration; champion misses / non-champion qualifies. | The division tiebreaker applies the league's standings rule; the owner has not stated it separately. |
| Draft-slot odds | `src/public_league/draft_order.py` + playoff_sim | Reverse final record, lower points for first, applied per simulation. | `test_playoff_probability_oracles.py` (draft slot); `tests/ros/test_draft_slot_forecast_e2e.py`. | Record basis is head-to-head only (#1712 owner question: does the median game count?). |
| Bracket / title / finals | playoff_sim `_simulate_bracket` | The league's re-seed or fixed bracket, played on the simulated distributions. | `test_playoff_probability_oracles.py`. | F2. |
| Game Day win / median race | `src/ros/game_day_sim.py` | Per-matchup simulation; median threshold. | `tests/game_day/test_game_day_probability_oracles.py`, `test_median_race_math.py`. | Calibration scorecard needs completed weeks (`scripts/game_day_calibration_scorecard.py`). |
| League scoring (offense, IDP, TE) | `src/league_intel/scorer.py` | The league's exact scoring card applied to stat lines. | Host truth: equals Sleeper `players_points` within 0.02 on 4,275 / 4,275 player-weeks (`ROS_SCALE_CALIBRATION_RESULTS_2026-10-28.md`); `tests/league_intel/test_golden_scoring.py`. | None found. |
| Lineup / slot assignment | `src/ros/lineup.py` | Exact assignment solver. | Sleeper's awarded best-ball lineups: 10 / 10 (C2-U1, `tests/lineup/test_c2u1_red.py`). | — |
| Trade package value | `src/valuation_math/package_model.py` (`geom_q078_v1`) | U = Σ 0.78^(i-1)·v_i, shown as a positive-only adjustment. | `tests/valuation_math/test_package_model_oracle.py`: exact-rational reference plus hand table, mirrored in JS. | The model's predictive skill (does it match real trades?) is a separate evaluation. |
| KTC VA rollback model | `src/trade/ktc_va.py` | Port of KTC's `adjustPackage`. | `tests/trade/test_ktc_va_python_port.py` (0 / 40,000 differences vs the JS reference, per CLAUDE.md). | — |
| FAAB bid | `src/trade/faab_engine.py` | Objective ceiling (format) plus market-aware recommended bid. | `tests/trade/test_faab_calibration.py` (human anchors); `scripts/faab_backtest.py` (states its own five caveats); `tests/integration/test_format_pair_isolation.py` (#2154). | The backtest is in-sample, with look-ahead artifacts above the all-in line (CLAUDE.md "FAAB"). Latent default: `team_ceiling` reads an unknown own balance as the full budget. Every live caller guards it (the faab-recommend route withholds; `waiver.py` passes a known cap), so no user sees it. |
| Player value (canonical board) | `src/api/data_contract.py` | Hill percentile curves, count-aware blend, family cap. | Hill holdout on boards the fit never reads (`src/model_registry/holdout.py`); blend-hull integrity check on every build. | No outcome-based validation for IDP; correlated multi-source anomalies are invisible (CLAUDE.md, step 10). |
| Confidence bucket | `src/api/confidence.py` | Evidence-quality grade: the weakest of five axes. | Axis tests (B11 ledger). | Not a probability, and it is not labelled as one. |
| Superflex / TE basis | `src/league_intel/te_premium.py` | KTC's measured TE uplift; target basis constant. | Measured curve (ADR-015). | League-specific TE demand is overlay work, not served. |
| Trade Monte Carlo button | `frontend/components/ui/MonteCarloButton.jsx` | Share of simulations where one side's total is larger. | Display tests (#2150). | It is a frequency, and now reads as one (#2150). |
| Waiver posture share | `frontend/lib/waiver-advisor.js` | Posture class share under a declared-prior model. | — | Uncalibrated; now labelled so (#2150). |
| BDVM pick hit rate | `src/bdvm/` | Placeholder prior table by slot. | Parity with the frozen reference (`tests/bdvm/test_engine_parity.py`). | Not fitted to drafts; now labelled a prior (#2150). |

## Not verifiable yet (named, not assumed)

- **Calibration of any forecast probability against outcomes:**
  - season-level playoff odds after this season ends (January 2027);
  - Game Day after enough completed weeks;
  - draft slots after the 2027 rookie draft.
- **The best-ball points scale (F2):** blocked on the pre-registered study.
- **Real-trade skill of the package model:** an evaluation, not a correctness test.

## League-format coverage (directive §5)

This maps each format axis the owner named to the existing tests that pin it. Every file named here exists on `main` after #2149.

| Axis | What must not leak across formats | Representative tests |
|---|---|---|
| Superflex vs standard slots | lineup fill and slot eligibility | `tests/lineup/test_canonical_lineup.py`, `tests/lineup/test_c2u1_red.py` (SUPER_FLEX vs Sleeper's awarded lineups) |
| TE premium vs none | TE basis conversion; target TEP read from the scoring card, never the profile label | `tests/league_intel/test_te_premium_invariants.py`, `test_te_premium_measurement.py` |
| IDP vs offense-only | waiver and position offers only in started positions | `tests/trade/test_cw50_waiver_workflow.py`, `tests/waivers/test_waiver_workflow_properties.py` (`position_not_started`) |
| Divisions vs none / per-league playoff rules | one league's rules are never applied to another; an unrecorded rule fails closed | `tests/ros/test_league_division_rules.py`, `tests/ros/test_playoff_divisions_fail_closed.py` |
| Playoff field size, byes, re-seed vs fixed | bracket read from the league's own settings | `tests/public_league/test_playoff_structure.py`, `tests/ros/test_playoff_probability_oracles.py` |
| Scoring identity across leagues | rankings shared only when scoring is PROVEN identical | `tests/api/test_scoring_compatibility.py`, `tests/api/test_league_routing.py` |
| Missing FAAB information | unknown balance is withheld, never $100 or $0 | `tests/api/test_faab_recommend_endpoint.py` (#2147), `tests/api/test_cw50_waiver_desk.py` |
| Roster size, full or incomplete rosters, taxi | forced drops reported, never filtered; unknown cap is unknown | `tests/trade/test_roster_capacity.py`, `tests/trade/test_capacity_wiring.py`, `tests/trade/test_forced_drop_selection.py` |
| Missing / stale / contradictory data | structural vs source-health lanes; stale evidence loses authority | `tests/api/test_contract_health_lanes.py`, scoring-evidence freshness tests |

**Gaps, each with an acceptance test:**
- **Format-pair contamination test (one fixture, two leagues): DONE in #2154** for the six pure league-scoped owners. Surfaces that need the live contract or network are not covered: the `/api/data` scoring-fingerprint gate, the sleeper overlay merge, draft capital and public snapshot builders. Build `dynasty_main` and a second league with different scoring, slots, IDP and playoff rules from one snapshot. Every league-scoped surface (playoff odds, waiver offers, lineup, FAAB) must return each league's own answer. Acceptance: swapping the league key changes exactly the league-scoped outputs, and nothing else.
- **Forced-drop property coverage.** The taxi sweep exercises only 76 of 240 seeded cases (#2151). Acceptance: every forced-drop property runs at least N applicable draws per scenario, generated deterministically.
