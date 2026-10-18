# Trade Decision Engine Audit (TC-0, Deliverable 4)

**Status:** READ-ONLY AUDIT. It authorizes nothing. The design in §7 is a proposal for TC-C. Any decision
threshold it names is a declared PRIOR that waits for owner approval and calibration.

**Directive:** owner master directive 2026-10-17 →
`docs/trade/TRADE_CALCULATOR_COMPLETION_WORKSTREAM.md` (TC-0 deliverable 4, TC-C).

**Native IDs:** `C7-DESK-01` (Analyze Trade decision contract), `C3-CALC-01`, `C3-CALC-03`, `C3-PKG-01`,
`C2-SIM-01`, `C4-MTL-03`, `C7-POST-01`, `C3-CAP-01`, `C3-EQ-01`.

**Audited tree:**

- Base: `origin/main` @ `0b3194f190`, lane branch `claude/trade-calculator-completion` @ `695fc26c37`
  (docs-only commit on top).
- Pending, read from their worktrees and **not on main**:
  - **#1772** `claude/injury-aware-bestball` @ `e40fd1dac8` (availability-aware best-ball utility);
  - **#1771** geometric package-model activation @ `53cd6e4ac5` (`geom_q078_v1` active, KTC kept as
    rollback).
- Every `file:line` below refers to `origin/main` unless it is marked `[#1772]` or `[#1771]`.

**Agent-OS-Receipt:** UNKNOWN. This session wrote only this file, so no receipt was generated.

---

## 0. Executive summary

1. **There is one backend decision owner, and it is well built.**
   - `src/trade/analyze_trade.py::analyze_trade` (`:865-916`) composes six lenses over one `simulate_trade`
     payload.
   - Exactly three lenses vote: market, roster and feasibility. The rule table in `_recommend` (`:553-601`)
     combines them, and lineage tags (`:72-82`) keep correlated evidence from voting twice.
   - MISSING IS NEVER ZERO is held everywhere I traced it.
2. **The product still shows at least eight other final-sounding verdicts for the same trade.**
   - They use six different threshold vocabularies (§3), and several can contradict the War Room on the
     same screen:
     - the TradeMeter badge;
     - the TradeMeter "% more" text;
     - the Fairness Explanation;
     - the Monte Carlo headline;
     - the Second Opinions tally;
     - the "Simulate impact" `teamImpact.verdict`;
     - the suggestions-desk fairness badge;
     - the tray verdict.
   - The worst of them is `teamImpact.verdict`: a weighted sum of a canonical-value fit score and raw
     (non-VA) equity, shown as "accept / decline" (§3.2).
3. **The engine covers about 3½ of the ten required dimensions.**
   - **Evaluated:** asset value (market lens), immediate improvement (roster lens, in season only),
     roster construction / forced drops (feasibility).
   - **Partly evaluated:** feasibility (pick ownership is reported, acceptance is not).
   - **Shown but non-voting:** competitive strategy (posture) and market evidence (comparables).
   - **Not evaluated:** long-term improvement as a roster-level quantity, risk (MC excluded as unaudited),
     opportunity cost, league constraints beyond the roster limit.
   - **Offseason gap:** from February to August the roster lens is unavailable
     (`season_unresolved`, `src/trade/roster_capacity.py:995`), so the verdict is market-only.
4. **Real invariant defects** (§6):
   - Adding an *unprojected* player to either side makes the roster lens abstain. A dissenting lens goes
     quiet, so adding evidence can *raise* the recommendation (TOO_CLOSE → MAKE), and adding a favorable
     asset can lower it (MAKE → LEAN_MAKE).
   - Feasibility moves the verdict one full step whatever the forced-drop cost: a 50-point cut counts the
     same as a 3,000-point cut.
   - Confidence is not monotone in evidence quality. A single-lens verdict is MEDIUM even when every traded
     asset is low-confidence.
   - There is no property test for side symmetry, monotonicity or star/depth bias.
5. **Thresholds calibrated under KTC that #1771 leaves unchanged** (§5):
   - `_fairness_label` 256 / 769 (`src/trade/suggestions.py:961-967`) drives the market lens, Best Offers
     and Package Builder;
   - the JS meter at 350 / 900 / 1800 (`frontend/lib/trade-logic.js:37-39`);
   - balancers at 256 (Python) and 350 (JS);
   - angle ±5%;
   - history grades 3 / 8 / 15 / 25 / 40%;
   - aging ±200.
   - Under geom every multi-asset trade carries an adjustment, so these bands now mean something different.
     1-for-1 trades are unaffected, because neither model adjusts a 1-for-1.
6. **TC-C proposal** (§7):
   - Keep `analyze_trade` as the only owner.
   - Add a YES / NO / NOT ENOUGH EVIDENCE headline over four separately-united components: objective
     package value, personal roster benefit, strategic fit and feasibility.
   - Combine them through gates and a goal-keyed lexicographic table, never a weighted sum.
   - Publish a per-dimension coverage record and a bottleneck confidence label.
   - Retire or relabel every competing verdict.

---

## 1. The live decision graph

### 1.1 Request path

```
/trade page (frontend/app/trade/page.jsx)
  └─ warRoomRequest = tradeRequestForTeam(sides, teamRosterNames(selectedTeam), selectedTeam.name)   page.jsx:1557-1563
       (which side the team GIVES = side holding more of its rostered names; tie → side 0)            trade-war-room.js:48-85
  └─ <TradeWarRoom request leagueKey useTeamContext>  (2-side trades only)                           page.jsx:2276-2283
       POST /api/trade/analyze  (stale answers refused by analyzeRequestKey / validAnalyzePayload)   trade-war-room.js:88-119
server.py::post_trade_analyze                                                                        server.py:17201-17243
  └─ _build_trade_simulation(for_analysis=True)                                                      server.py:16940-17146
       auth → league resolve → scoring-identity gate / cross-league overlay → _valuation_scoped_contract (lens withdrawn)
       → resolve team → team_context_requested(body) (default ON)                                    src/trade/team_context.py:22-24
       → competitive_posture_for(build_if_missing=for_analysis and team ctx)                         server.py:17111-17118; src/api/trade_simulator.py:397-433
       → trade_simulator.simulate_trade(include_roster_utility = for_analysis and team ctx)          server.py:17096-17119
       → result.teamContext; result.nflExposure (attached AFTER, non-influence C2-EXP-01)            server.py:17120-17134
  └─ comparable_trades.comparable_trades(league, side_a=receiving, side_b=sending)                   server.py:17227-17238
  └─ result["analysis"] = analyze_trade(result, comparables)                                         server.py:17239
```

### 1.2 What `simulate_trade` produces (`src/api/trade_simulator.py:436-867`)

| field | origin | notes |
|---|---|---|
| `receiving` / `sending` | canonical board rows. `_resolve_asset` reads `rankDerivedValue`, plus the stamps `confidenceBucket` and `hasSourceDisagreement` | `:228-350`. One canonical value per asset (W29-F001). Picks resolve through the identity owner; alias-suppressed rows are never priced at 0 (`:308-318`) |
| `equity` | **raw** Σin − Σout | `:675`. Not VA-adjusted. Consumed by `team_impact` |
| `ownedPickChecks` (`notOwnedBySender`, `hypotheticalPicksOut`, …) | `identity.picks.lookup_league_pick_owner` | `:599-611, :687-695`. A not-owned pick is left out of `sending` |
| `pickOwnership` | `team_pick_ownership_unavailable_reason` | `:697-706`. **Not read by `analyze_trade`** (gap, §4) |
| `competitivePosture` | `window.competitive_posture` via `gameplan.league_competitive_postures` | `:708-713`. **Pre-trade roster only** |
| `teamImpact` | `src/trade/team_impact.compute` (fit + equity composite, `verdict`) | `:719-734` |
| `rosterCapacity` | `roster_capacity.assess_roster_capacity` | `:757-776`. Players only; picks occupy no spot |
| `finalRosterSimulation` | `roster_capacity.simulate_final_legal_roster` (Team Strength: Σ canonical) | `:778-826` |
| `rosterUtility` | `roster_capacity.evaluate_final_roster_utility` → `best_ball_utility.evaluate_trade_utility` | `:828-866`. League-scored ROS ensemble per-game means, 400 paired draws, exact lineup solve (`best_ball_utility.py:75-76`, `:441-511`) |

### 1.3 Lenses in `analyze_trade.py`

| lens (packet key) | consumes | votes? | lineage tag | direction rule | file:line |
|---|---|---|---|---|---|
| **market** (`equity`) | `receiving` / `sending` values → `package_model.adjusted_pair_totals` (active model) | **YES** | `canonical_value` | magnitude = `_fairness_label(VA gap)`: `even` <256, `lean` <769, else `stretch`. `even` → neutral | `:157-184`, `:187-242`; `suggestions.py:961-967` |
| **roster** (`rosterUtility`) | `rosterUtility.impact.ppg`, `standardError`, `coverage` | **YES** | `league_scored_projection` | band = max(`materialityPpg` 1.0, 2·SE); `large` ≥ 3× band; `coverage.partial` → **abstain** (reported unavailable) | `:266-345`; config `config/trade/analyze_trade.json` |
| Team Strength (inside roster detail) | `finalRosterSimulation` strength before / after | no (context) | `canonical_value` | — | `:248-263` |
| **feasibility** | `rosterCapacity` | **YES** (step modifier) | `league_roster_rules` | resolves / reduces overage → favors. cut_required / worsens → opposes if `forcedDropReleaseCost` > 0 or worsening. unknown_limit / uncertain → unavailable | `:351-446` |
| **evidence** | asset `confidenceBucket`, `hasSourceDisagreement`, projection coverage, SE | no | — | sets confidence / uncertainty | `:452-477` |
| **comparables** (`marketCorroboration`) | `comparable_trades` payload | no | `real_trade_ledger` | `context`. Never moves confidence | `:483-542` |
| **posture** (`strategicPosture`) | `competitivePosture`, `teamImpact.windowFit` | no | `team_strategy_context` | `context` | `:808-852` |
| `valueUncertainty`, `currentSeasonEquity` | — | named UNAVAILABLE | — | `unaudited_model`, `counterfactual_not_wired` | `:88-102` |

### 1.4 How the verdict and confidence form (`_recommend`, `:553-601`; `analyze_trade`, `:895-901`)

1. **No primary lens available** → `TOO_CLOSE`, `LOW`.
2. **One primary lens** (Asset-Only, offseason, or roster abstained):
   - favors → `MAKE` if strong, else `LEAN_MAKE`;
   - opposes → `PASS` if strong, else `LEAN_PASS`;
   - neutral → `TOO_CLOSE`.
   - "Strong" means `stretch` for the market lens and `large` for the roster lens.
   - Confidence is `MEDIUM` when there is a direction, `LOW` when neutral.
3. **Two primary lenses**, by the pair of directions:

   | market and roster | verdict | confidence |
   |---|---|---|
   | favors + favors | MAKE | HIGH |
   | opposes + opposes | PASS | HIGH |
   | favors + neutral | LEAN_MAKE | MEDIUM |
   | opposes + neutral | LEAN_PASS | MEDIUM |
   | favors + opposes | TOO_CLOSE | MEDIUM |
   | neutral + neutral | TOO_CLOSE | LOW |

   Magnitudes are **ignored** in the two-lens table.
4. **Feasibility** favors / opposes shifts the verdict **one step**, whatever the magnitude (`:592-594`).
   `ladderExhausted` caps the verdict at `TOO_CLOSE` (`:595-600`).
5. **Any** uncertainty line downgrades `HIGH` → `MEDIUM` (`:898-901`). Nothing ever downgrades `MEDIUM` → `LOW`
   for evidence quality.

The War Room renders the packet as display only:

- headline badge and confidence: `frontend/components/trade/TradeWarRoom.jsx:550-557`;
- labels: `frontend/lib/trade-war-room.js:20-34`.

### 1.5 Pending changes that alter this graph

- **#1772 (availability)** — roster lens:
  - `best_ball_utility._run` maps each draw to a real remaining week and **removes** `unavailable`
    player-weeks before the solve. It does not zero them. `[#1772] best_ball_utility.py`: `_plays`,
    `_eligible_share`, `_run`.
  - `evaluate_final_roster_utility` builds availability from `src/ros/availability.py` (a new owner).
    `[#1772] roster_capacity.py` evaluate_final_roster_utility hunk.
  - `analyze_trade._reasons` gains availability-qualified lineup reasons. `[#1772] analyze_trade.py`
    `_availability_note`.
  - **No change to `_recommend`.**
  - Effect: the roster lens becomes a **remaining-weeks** quantity. An injured incoming star can now flip
    the roster lens to *opposes* while the long-horizon market lens still *favors*. The two-lens table
    resolves that to TOO_CLOSE (MEDIUM).
- **#1771 (geom activation)**:
  - `config/trade/package_model.json` → `active: geom_q078_v1`;
  - JS `ACTIVE_PACKAGE_MODEL_ID` → geom;
  - analyze reason copy drops "KTC" (`[#1771] analyze_trade.py:624-631`).
  - **No threshold changes:** the 256 / 769, 350 / 900 / 1800, 3%, ±200 and 5% constants are untouched in
    its diff.
  - The market lens will compute `gap = U_recv − U_send` (geometric utility difference, `package_model.py:123-130`).

---

## 2. Dependency / origin map and evidence classification

### 2.1 Origin map

```
 SOURCES (≈20 dynasty boards: KTC Crowd, KTC Trades, IDPTC, DLF, FantasyCalc, Signals, …)
   │   per-source normalized `valueContribution` (also read raw by Second Opinions)
   ▼
 CANONICAL BOARD  rankDerivedValue  (data_contract._compute_unified_rankings; family-capped, freshness-weighted)
   ├─► market lens (VOTES) ──► package model (geom/KTC)  [transformation of the same values]
   ├─► Team Strength (finalRosterSimulation)            [Σ canonical → correlated, non-voting ✔]
   ├─► forced-drop releaseCost = value × scarcity       [canonical lineage, different asset]
   ├─► cut ladder choice (WHICH player is cut)          [canonical lineage chooses the roster the roster lens evaluates]
   ├─► team_impact fit/equity/verdict                    [canonical + raw equity → correlated, competing verdict ✘]
   ├─► Monte Carlo centre (effectiveValue) ± synthetic 15%  [correlated, excluded from verdict ✔, own headline ✘]
   ├─► Second Opinions rows = the board's own inputs re-viewed [correlated, own tally ✘ (frontend only)]
   ├─► confidenceBucket (B11: family count/coverage/freshness/applicability/agreement) [contextual ✔]
   └─► KTC Market benchmark (ktcMarket / marketGap*)     [not read by analyze]

 ROS PROJECTION ENSEMBLE (league-scored, equal-family mean; projection_ensemble)  + PointsModel CV + lineup solver
   ├─► roster lens BBLI (VOTES)                          [independent lineage from the dynasty board ✔]
   ├─► playoff_sim odds ─► competitive posture ─► posture lens (context) & team_impact.windowFit
   └─► [#1772] availability (src/ros/availability.py: Sleeper status, ESPN returns, byes, overrides)

 LEAGUE RULES (registry + Sleeper league settings)
   ├─► roster limit / taxi / slots ─► feasibility (VOTES), lineup solver, cut ladder
   └─► trade_deadline ─► posture timing only (NOT a feasibility gate)

 OWNERSHIP RECORDS (sleeper.teams[].pickDetails assetId; /traded_picks)
   └─► ownedPickChecks / pickOwnership ─► market-lens exclusion + uncertainty lines

 REAL-TRADE LEDGER (own league + Sharp + KTC-published trades)
   └─► comparable_trades ─► comparables lens (context only)

 BDVM fundamentals (projection snapshots + CES; zero market inputs) ─► BdvmTradePanel (second opinion, not in packet)
```

### 2.2 Classification of every signal

| # | signal | consumer | kind | votes today | double-counting risk (concrete) |
|---|---|---|---|---|---|
| S1 | canonical `rankDerivedValue` of traded assets | market lens | **INDEPENDENT** (the one value lineage) | yes | KTC Crowd and KTC Trades are already two voters inside it (CLAUDE.md step 4). A KTC-native verdict or a KTC-anchored MC added on top would be a third and fourth KTC vote |
| S2 | package VA (geom / KTC) | market lens | **CONTEXTUAL transformation** of S1 | inside S1's vote | none while it stays inside the market lens. It would double count if a "concentration" factor were also voted separately |
| S3 | raw gap, adjusted totals | market lens detail | EXPLANATORY | no | — |
| S4 | `rosterUtility` BBLI (ppg, SE, lineup entry) | roster lens | **INDEPENDENT** (projection lineage) | yes | (a) The cut ladder that picks the post-trade roster runs on canonical value (`roster_capacity.py:1220`), so S1 lineage chooses which roster S4 scores. (b) Projection providers overlap ranking providers (e.g. FantasyPros publishes both), so they are correlated at provider level on news shocks. (c) [#1772] injury evidence lowers S4 directly, and the market sources already price injuries into S1. One news event therefore moves both voting lenses in the same direction. This is a different quantity (ROS points vs dynasty value), but it is the **same shock**, so TC-C must not count "injury" as a third reason |
| S5 | Team Strength delta | roster detail | CORRELATED (Σ S1) | no ✔ | it would double count S1 if it voted. It is correctly blocked (`analyze_trade.py:248-263`) |
| S6 | capacity state (fits / cut / overage) | feasibility | **INDEPENDENT** (league rules) | yes (step) | — |
| S7 | `forcedDropReleaseCost` | feasibility (sign only) | CORRELATED magnitude (S1 × scarcity) on a *different* asset | yes, by sign | (a) When the forced drop is `acquiredInTrade`, the market lens credits that incoming asset's full value **and** feasibility opposes. The value is overstated in one lens and penalized in the other, without a net-of-release figure. (b) Analyze reads the **total** release cost (`roster_capacity.py:381-385`). The finder reads the **marginal** `forced_drop_cost` (`:629-702`). Two definitions of "cost of the cut" |
| S8 | per-asset `confidenceBucket`, `hasSourceDisagreement` | evidence lens | CONTEXTUAL (confidence modifier) | no ✔ | it must never become a vote. Source disagreement is S1's own dispersion |
| S9 | projection coverage, SE | evidence lens / roster band | CONTEXTUAL | no ✔ | — |
| S10 | competitive posture (PUSH / HOLD / RETOOL / REBUILD) | posture lens | CORRELATED. It is derived from playoff odds (S4's projection lineage) and lineup-entrant ages (`window.py:3-31, :215-260`) | no ✔ | it would double count S4 if it voted. The owner rule says posture is context, never a veto |
| S11 | `teamImpact.windowFit` (ages vs posture probabilities) | posture lens detail | CORRELATED (posture × ages) | no | it would double count S10 and S4 if promoted |
| S12 | comparable real trades | comparables lens | **INDEPENDENT body of evidence**, used as EXPLANATORY | no ✔ | the ledger includes KTC-published trades (`sourceFamilies`). KTC Trades (`ktcTradesSfTep`) is itself built from KTC's trade database and votes in S1. If comparables ever priced a verdict, KTC trade evidence would count twice |
| S13 | Second Opinions per-source verdicts and tally | `TradeSourceBreakdown` (frontend) | CORRELATED. They are S1's own inputs (`valueContribution`), re-adjusted with the active model (`second-opinions.js:1-35`) | not in packet ✔, but renders its own tally | "5 of 7 families favor A" is the canonical blend's internal agreement, not independent corroboration. Valid only as dispersion / confidence. The family tally already mirrors the B10 cap |
| S14 | Monte Carlo win rate | `MonteCarloButton` (frontend) / `/api/trade/simulate-mc` | CORRELATED. It is centered on S1 (or a user override) with a synthetic ±15% band (`monte_carlo.py:1-30`, `MonteCarloButton.jsx:60-68`) and the same VA | excluded ✔ (`valueUncertainty` unavailable) | its win rate is essentially a monotone function of the S1 gap. As a vote it would count S1 twice |
| S15 | `teamImpact` fit / equity / composite / verdict | Simulate-impact panel | CORRELATED (S1 starter values + raw equity) | no, but shown as a verdict | it sums incompatible units (§3.2) and re-counts S1 |
| S16 | BDVM trade-eval (CES per strategy currency) | `BdvmTradePanel` | partially INDEPENDENT (projection fundamentals, zero market inputs) | no | it shares the projection lineage with S4. It is a candidate long-term fundamental signal, but its parameters are priors |
| S17 | ROS Fit tags | `RosTradeFitPanel` | EXPLANATORY (ROS lineage) | no | — |
| S18 | NFL exposure | `nflExposure` | EXPLANATORY (non-influence by rule) | no ✔ | — |
| S19 | draft-capital stack effect | page note | withdrawn / informational | no ✔ (pinned by `frontend/__tests__/trade-stack-withdrawn.test.js`) | — |
| S20 | owned-pick checks / pick ownership | market exclusion + uncertainty | INDEPENDENT (ownership facts) | via S1 exclusion | `pickOwnership: unavailable` is not surfaced by analyze |
| S21 | user value overrides / Raw value mode | headline meter, MC | user-supplied alternate value | no (analyze ignores them by design) | not double counting, but a **competing basis** (§3) |
| S22 | [#1772] player-week availability | roster lens inputs | CONTEXTUAL transformation of S4 | via S4 | see S4(c) |

---

## 3. Competing verdicts

### 3.1 Inventory of every final-sounding verdict / grade / meter

| # | surface | computed where | basis | thresholds | file:line |
|---|---|---|---|---|---|
| V1 | **War Room recommendation** (MAKE…PASS + confidence) | backend `analyze_trade` | canonical + active VA; ROS BBLI; capacity | 256 / 769 VA gap; ppg band; one-step feasibility | `analyze_trade.py:553-601`; `TradeWarRoom.jsx:550-557` |
| V2 | **TradeMeter badge** FAIR / SLIGHT EDGE / UNFAIR / LOPSIDED | frontend `meterVerdict` | `sidesWithOverrides`, current **valueMode**, active VA | 350 / 900 / 1800 absolute | `trade-logic.js:1783-1788`; `TradeMeter.jsx:48`; `page.jsx:856-877, 2294-2301` |
| V3 | **TradeMeter winner text** "Side A's package is worth N% more" | frontend | same totals | 3% relative | `TradeMeter.jsx:64-70` |
| V4 | **Fairness Explanation** sentence | frontend | adjusted totals + per-source raw gaps | 3% relative; 200 "notable" source gap | `TradeFairnessExplanation.jsx:56, 142-183` |
| V5 | **Monte Carlo headline** "Side A is the clear winner / favored / Coin flip" | frontend over `/api/trade/simulate-mc` | `effectiveValue` on **`sides` without overrides**, valueMode default `full` (not the page's mode) | win% 80 / 60 / 40 / 20 | `MonteCarloButton.jsx:103-135, 167`; rendered inside `TradeMeter.jsx:116` |
| V6 | **Second Opinions tally** + per-source leader | frontend | per-source normalized values + active VA | "even" only if gap < 1 point | `second-opinions.js:288-302, 368-410` |
| V7 | **Simulate impact `teamImpact.verdict`** accept / lean accept / neutral / lean decline / decline | backend `team_impact.compute` | 0.55·fitScore + 0.45·equityScore, with **raw** equity / 2500 | ±8 / ±20 composite | `team_impact.py:500-510, 636-662, 716-722`; `config/trade/team_impact.json`; `trade-simulation-panel.jsx:152-153` |
| V8 | **Suggestions-desk fairness badge** Even value / Lean / Stretch | backend `suggestions._fairness_label` | VA gap | 256 / 769 | `trade-suggestions-desk.jsx:18-30`; `suggestions.py:961-967` |
| V9 | **Tray verdict** (sticky summary) | frontend `meterVerdict` + `colorFromGap` | `pwGap` | 350 / 900 / 1800 + % | `page.jsx:2440-2468` |
| V10 | BDVM "Edge (A−B)" per strategy | backend `bdvm_api` | fundamentals | sign only (colored buy / sell) | `BdvmTradePanel.jsx:115-137` |
| V11 | Trade history / public league letter grades | `league-analysis.js` / `trade_grading.py` | got / gave + VA net, % of package | 3 / 8 / 15 / 25 / 40% | `league-analysis.js:87-100`; `trade_grading.py:54-84` |
| V12 | Trade aging verdict (aged well / stable / poorly) | `trade-history-grades.js` | at-time vs current adjusted | ±200 PRIOR | `trade-history-grades.js:31-34, 155-159` |

V11 and V12 sit on `/trades` and `/league`, not `/trade`. They grade the same quantity, though, and a completed trade
re-built in the calculator will show both.

### 3.2 Can they disagree for the same trade? Yes, structurally

- **V1 vs V2 / V3 / V9 at small gaps.**
  - Take a VA gap of +300 to the user, 1-for-1, roster lens neutral.
  - V1: market `lean` → favors → LEAN_MAKE, MEDIUM.
  - V2: |300| < 350 → **FAIR**.
  - V3: totals 4,000 vs 3,700 → 7.5% → "Side A's package is worth 7% more". It renders beside "FAIR"
    in the same widget, because V2 is absolute and V3 relative (the help copy admits this,
    `TradeVerdictHelpBody.jsx:61-64`).
- **V1 vs V2 under overrides / Raw mode.**
  - V2 uses `sidesWithOverrides` and `valueMode` (`page.jsx:722-735, 856-877`).
  - V1 always uses canonical values (`TradeVerdictHelpBody.jsx:78-82` says so).
  - So one override can turn V2 to LOPSIDED while V1 still says MAKE.
- **V2 vs V5 inside the same component.**
  - TradeMeter receives the overridden totals but passes raw `sides` and no `valueMode` to
    `MonteCarloButton` (`TradeMeter.jsx:116`, `MonteCarloButton.jsx:167`).
  - The MC center therefore ignores overrides and Raw mode while the meter beside it applies them.
- **V1 vs V7.**
  - V7's composite is 0.55·fit + 0.45·equity. Fit is a canonical starter-value delta normalized by 4,000;
    equity is **raw** Σin−Σout normalized by 2,500, with no package VA.
  - So a 2-for-1 consolidation that is even after VA can be "lean accept" or "lean decline" on raw
    equity alone, while V1 says TOO_CLOSE.
  - V7 also sums two incompatible normalized quantities, which TC-C forbids.
  - Its rationale still says "Net KTC equity" (`team_impact.py:546`) for a raw canonical sum.
  - It is the only remaining **weighted-sum verdict** in the trade surface.
- **V1 vs V6.**
  - V6 calls any non-zero gap a winner (`< 1` point is the only "even", `second-opinions.js:296`).
  - The independent tally therefore reports "Side A 6 · Side B 0" on a trade every lens calls even.
- **V1 vs V8 / Best Offers.**
  - These share `_fairness_label`, so they agree on the market half.
  - Best Offers' "canonical WIN" (`best_offers.py:537-541`, via `equity_verdict.win`) is the market lens
    alone. It is not the War Room verdict: a Best Offer can be one the War Room calls LEAN_PASS after
    roster and feasibility.
- **Not-owned picks.**
  - V1 leaves a pick the sender does not hold out of `sending` (`trade_simulator.py:599-611`).
  - V2 counts it, because the calculator is hypothetical by owner decision 2026-10-03.
  - Same trade, different totals. V1 names the exclusion in its uncertainty list (`analyze_trade.py:757-767`).
- **Multi-team trades.** The War Room renders only for 2 sides (`page.jsx:2276`). A 3- to 5-team trade has
  V2 (worst-offender net, `TradeMeter.jsx:135-139`) and no decision at all.

**Verdict:** the directive's TC-C done-criterion ("no other component computes a final verdict") is **not met**.
V2/V3/V9 can stay as the *Immediate Result* if they share the market lens's band owner and are worded as
package-only. V5, V6 and V7 need relabelling or retirement (§7.8).

---

## 4. Gap analysis against the ten required dimensions

Legend: ✅ evaluated and votes · ◐ partial · ○ shown, non-voting · ✘ not evaluated.

| # | dimension | evaluated today? | evidence | freshness / applicability / uncertainty recorded? | contribution | what is missing |
|---|---|---|---|---|---|---|
| 1 | **Asset value** (incl. package-adjusted, concentration) | ✅ market lens | canonical values + active package model; `packageModel` receipt (`analyze_trade.py:216-217`) | per-asset `confidenceBucket` (which carries B11 freshness) only as uncertainty lines. **No board as-of / generation id in the packet.** VA uncertainty not recorded | primary vote | relative-gap reading (bands are absolute only → scale bias); concentration shown only implicitly through VA; geom depth saturation on deep packages (PACKAGE_MODEL_EVALUATION §1: 99.77% stud-side on 1-for-6+) not disclosed; unpriced share of each package not quantified |
| 2 | **Immediate improvement** (incl. availability) | ✅ in season; ✘ Feb–Aug | BBLI on final legal roster, 400 paired draws (`best_ball_utility.py:75`), SE published | projection basis (`basis.horizon`, families, `sourcesUnavailable`) ✔; coverage ✔; **availability not modelled on main** (`best_ball_utility.py:425-426`); [#1772] adds it | primary vote | offseason: `season_unresolved` (`roster_capacity.py:991-997`, `bdvm/actuals.py:40-55`) → no roster vote for 7 months; `uncertain`-week probability (#1772 keeps them in the pool); playoff/championship deltas (`currentSeasonEquity` unavailable, `analyze_trade.py:96-101`) |
| 3 | **Long-term improvement** | ◐ only via asset value | canonical dynasty value is long-horizon; posture `windowFit` / ages shown | no | via #1 only | no roster-level long-term quantity (Young Core / #838 age-value, #839 Meaningful Core, owned pick capital delta are not wired); BDVM fundamentals exist but sit outside the packet |
| 4 | **Roster construction** (incl. forced drops, scarcity) | ✅ feasibility + roster lens | capacity state, forced drops, cleanup re-solve, depth (single-starter absence) | `certainty`, `candidatesTied`, `ladderExhausted` ✔; taxi bracket ✔ | step vote + inside BBLI | magnitude-blind step; total vs marginal release cost (S7b); open-spot shadow value unmeasured (`best_ball_utility.py:405-409`); positional holes / Team Weakness delta not a field; scarcity only through release-cost multiplier |
| 5 | **Market evidence** (incl. freshness) | ○ comparables only | comparable trades, relevance-ordered (`comparable_trades.py`, `PRIOR_UNVALIDATED`) | `since`, recency score, format disposition ✔ | none (by design) | Second Opinions dispersion not in packet; KTC Market benchmark / external calculator verdicts (`cross_market.external_package_verdicts`) not in packet; no "market disagreement" confidence input; comparables never priced at-the-time |
| 6 | **Competitive strategy** (win-now / rebuild) | ○ posture context | canonical posture, probabilities, timing, own-first held | `paramsVersion`, `parameterStatus`, `bundleFreshness` ✔ | none | **no user goal input** (win-now / balanced / rebuild); posture is pre-trade only (no post-trade posture or title-odds delta); posture cannot change which lens dominates |
| 7 | **Risk** | ◐ evidence lens | low-confidence assets, source disagreement, projection SE | partial | confidence cap only | value uncertainty (MC) excluded as unaudited (`analyze_trade.py:89-95`); age / injury / role risk not represented; dispersion of S13 unused; downside asymmetry absent |
| 8 | **Feasibility** (incl. pick ownership, acceptance) | ◐ | roster limit, cut, overage; not-owned and hypothetical picks named in uncertainty | ✔ for capacity | step vote | `pickOwnership: unavailable` not surfaced (`trade_simulator.py:697-706` is not read by `analyze_trade.py`); **counterparty acceptance** absent (finder / best offers have `counterpartyRosterCapacity` and external-calculator qualification; analyze has neither); counterparty roster capacity absent |
| 9 | **Opportunity cost** | ✘ | — | — | none | no comparison to the best available alternative (Best Offers / finder / package builder already compute candidates for this team); marginal forced-drop cost (`forced_drop_cost`) not used; open-spot value unmeasured |
| 10 | **League constraints** | ◐ roster limit only | roster limit, taxi, starter slots (lineup), IDP slots | ✔ | via feasibility | trade deadline not a gate (posture timing knows it, `trade-war-room.js:214-220`); recommendation constraints (`C3-CON-01` LOCK / EXCLUDE / untouchables) not applied to the analysis; pick-trading rules; multi-team trades unsupported by the War Room |

---

## 5. Thresholds calibrated under KTC that need re-evaluation for `geom_q078_v1`

General effect of the switch:

- Under KTC the adjustment is suppressed on 1-for-1, under 3.3% of combined value, and on "fair" trades
  (`ktc_va.py:157-159`).
- Under geom, every pair where the two sides discard different depth carries an adjustment, and the
  adjusted gap equals `U_A − U_B` (`package_model.py:123-130`).
- So the same absolute band reads more multi-asset trades as non-even.
- 1-for-1 trades are identical under both models. Every gap-based threshold below changes meaning only
  for multi-asset trades.
- #1771 changes **none** of these constants.

| threshold | value | where | consumers | provenance today | action proposed |
|---|---|---|---|---|---|
| fairness label even / lean / stretch | <256 / <769 / ≥769 | `src/trade/suggestions.py:961-967` (`FAIRNESS_TOLERANCE = 769` at `:144`, "undocumented legacy tuning", `:136-143`) | **market lens direction & strength** (`analyze_trade.py:168-171`); `equity_verdict.win` → Best Offers (`best_offers.py:537-541`), Package Builder (`package_builder.py:519`); suggestion generation / ranking (`:1227, :1300, :1381, :1487, :1523`, `_FAIRNESS_RANK_BONUS :1021`) | legacy, no record | move to one config owner with `class: PRIOR`; measure verdict flip rate KTC→geom on the real-trade corpus (`market_trade_eval`) and the synthetic benchmark; add a relative component |
| single-lens "strong" | `stretch` (≥769) → MAKE / PASS | `analyze_trade.py:563-571` | V1 | inherits above | same |
| JS verdict bands | 350 / 900 / 1800 | `frontend/lib/trade-logic.js:37-39`, `verdictFromGap :852-858`, `meterVerdict :1783-1788` | V2, V9, multi-team meter | none recorded (`suggestions.py:136-143` calls them independent of 256 / 769) | unify with the market-lens band owner (parity test Python↔JS) |
| JS balancer trigger | imbalance ≥ 350, top 5 | `trade-logic.js:1445` | `findBalancers` | as above | `C3-EQ-01` open: one owner |
| Python balancer trigger | \|gap\| ≥ 256, `MAX_BALANCERS = 2` | `suggestions.py:1594, :1725` | suggestions equalizer | as above | same |
| suggestion overpay multiples | 1.5× and 2.0× of 769; consolidation 0.70 / 0.30 | `suggestions.py:146-162, :1492, :1523` | suggestion generation | legacy | re-measure suggestion volume before/after geom |
| angle gains | `min_my_gain_pct = 5`, `max_market_gain_pct = 5` on VA-adjusted totals | `src/trade/angle.py:424-425, :697-698` | Angle Finder | KTC-era | re-evaluate; note it mixes active-model "my" side vs market side |
| external "even" | `EXTERNAL_EVEN_TOLERANCE_PCT = 0.0`, external calculators priced with **KTC** VA by design | `src/league_intel/cross_market.py:798-806, :958-990` | Best Offers qualification | owner default | keep KTC for "what KTC says" (correct). Record that canonical-win (geom) and opponent-even (KTC) are now **different package models** in one rule |
| finder ratios | `MULTI_FOR_ONE_MIN_RATIO 0.55`, `ELITE_MULTI_MIN_RATIO 0.65`, `PACKAGE_ANCHOR_MIN_PCT 0.35`, `JUNK_THRESHOLD 350` | `src/trade/finder.py:53-54, :146-148, :692-700` | finder acceptance (pre-VA model values) | hardening-pass priors | re-validate with geom-scored results |
| TradeMeter / explanation | 3% relative; `MIN_NOTABLE_GAP 200` | `TradeMeter.jsx:65`; `TradeFairnessExplanation.jsx:56, :142` | V3, V4 | none | fold into the one band owner |
| MC headline bands | 80 / 60 / 40 / 20 % | `MonteCarloButton.jsx:103-135` | V5 | none | relabel as sensitivity, or remove the "winner" headline |
| Second Opinions even | gap < 1 point | `second-opinions.js:296` | V6 | historical (SECOND_OPINIONS_TODO "Open") | owner decision already listed as open |
| team_impact composite | weights 0.55 / 0.45, norms 4000 / 2500, verdict ±8 / ±20 | `config/trade/team_impact.json`; `team_impact.py:86-118, :500-510` | V7 | unrecorded | retire the verdict (§7.8) |
| history letter grades | 3 / 8 / 15 / 25 / 40 % | `league-analysis.js:87-100`; `trade_grading.py:54-84` | V11 | unrecorded. **Also non-monotone in letters:** winner A → A → A− → **B+** (15-25%) → A+ (≥25%), and B+ also means "slight overpay" | fix letter order; re-evaluate under geom |
| aging stable band | ±200 adjusted | `trade-history-grades.js:31-34, :155-159` | V12 | declared PRIOR (TRADE_HISTORY_AGING_SPEC §5) | re-evaluate; cross-model aging comparisons are already prevented by `packageModel` receipts (#1771 config comment) |
| help copy "not applied under 3.3%" | KTC-only behavior | `TradeVerdictHelpBody.jsx:41-44` | user copy | — | #1771 edits help; verify the sentence |

---

## 6. Invariant risks and proposed property tests

### 6.1 Findings

1. **Monotonicity broken by abstention.**
   - The roster lens abstains when any traded player is unprojected (`analyze_trade.py:300-306`). The
     verdict then falls back to the single-lens rule (`:561-573`).
   - **Down:** market favors (lean) + roster favors (any) = MAKE HIGH. Add an unprojected rookie to *your
     incoming* side → roster abstains → market-only lean → LEAN_MAKE MEDIUM. Value was added and the
     verdict got worse, with no new constraint.
   - **Up:** market favors (stretch) + roster opposes = TOO_CLOSE. Add an unprojected player to either
     side → MAKE MEDIUM. Silencing a dissenter *raised* the recommendation. This is the trade-level analog
     of the B11 rule "losing evidence never raises confidence".
2. **Magnitude-blind feasibility.**
   - Any priced forced drop moves the verdict one step (`:428-437, :592-594`), whether its release cost is
     50 or 3,000.
   - There is also no net-of-release objective figure, even though both quantities are on the canonical
     scale.
3. **Two-lens table ignores magnitude.**
   - Market `stretch` + roster neutral = LEAN_MAKE.
   - Market `lean` + roster `modest` = MAKE HIGH.
   - So a weaker joint case can outrank a stronger one.
4. **Confidence vs evidence quality.**
   - Single-lens confidence is MEDIUM whatever the evidence (`:572`).
   - Uncertainty only caps HIGH (`:898-901`).
   - So a market-only verdict where every asset is `confidenceBucket: low` and sources disagree is MEDIUM,
     the same as a clean one.
5. **Side / display symmetry.**
   - The backend computes from the selected team. The frontend chooses "my side" by counting owned names,
     tie → side 0 (`trade-war-room.js:51-55`).
   - When the team owns none of the assets, or equal counts on both sides, the display order decides
     which way the trade points. "Swap Sides flips it" (`:40-41`).
   - Objective math (`equity_verdict`) is antisymmetric under `geom`. Under KTC the side-swap property was
     measured clean (PACKAGE_MODEL_EVALUATION §1).
6. **Star / depth bias.**
   - Absolute bands treat a 700 gap on a 2,000-point trade and on a 20,000-point trade alike.
   - geom saturates depth: weights sum to ≤ 1/(1−q) ≈ 4.5 top-assets, so it sides with the stud on 1-for-6+
     trades 99.77% of the time (memo §1).
   - Feasibility structurally penalizes the depth-receiving side through cuts. That is a legitimate
     constraint, but it should be disclosed as such.
7. **ROS vs long-term separation.**
   - [#1772] makes injuries change the roster lens. That is the correct place.
   - Nothing pins that an availability change leaves the market lens unchanged. The market lens reads
     canonical values only, so it holds by construction today; there is no test.

### 6.2 Proposed property tests (Python, over `analyze_trade` with synthetic simulation payloads, plus `package_model`)

| id | property | form |
|---|---|---|
| P-SYM-1 | `equity_verdict(a, b).vaAdjustedGap == −equity_verdict(b, a).vaAdjustedGap` and direction mirrors, for both models | hypothesis over value arrays |
| P-SYM-2 | swapping display order of the two sides yields the same `/api/trade/analyze` request when ownership resolves (JS `tradeRequestForTeam`), and a declared ambiguity state when it does not | vitest |
| P-MONO-1 | adding a positive, **projected, priced** asset to the user's incoming side never lowers the headline rank, unless `feasibility.state` changes to a worse state or `ladderExhausted` flips | hypothesis; generator holds capacity fixed |
| P-MONO-2 | adding an asset that makes a lens abstain never **raises** the headline and never raises confidence (fixes finding 1) | targeted |
| P-MONO-3 | raising one incoming asset's value never lowers the headline (geom only; KTC pinned as KNOWN_DEFECT) | hypothesis |
| P-PERM | permuting assets within a side changes nothing | hypothesis |
| P-HOMO | scaling all values by k > 0 does not change the relative-band classification (once relative bands exist) | hypothesis |
| P-STAR / P-DEPTH | on a balanced synthetic corpus (equal adjusted value), headline YES-rate for the fewer-piece side lies within a declared band of 50%, reported per shape (1v2…1v6+) | corpus test with tolerance as PRIOR |
| P-CONF | confidence is monotone non-increasing in: number of low-confidence assets, unpriced share, lens abstentions, uncertainty lines | enumerated |
| P-ROS | an availability change (all remaining weeks unavailable) for a traded player changes only the roster component and never the market component | fixture pair [after #1772] |
| P-MISS | removing an input yields `NOT_ENOUGH_EVIDENCE` or a lower confidence, never a stronger headline | enumerated |
| P-ONE-VERDICT | AST / grep guard: no frontend module outside the War Room renders a YES / NO headline; `teamImpact.verdict` absent from UI | structural |
| P-PARITY | backend packet → War Room desktop and mobile render the same headline string (extends `tests/trade/test_war_room_ui_fixtures.py`, `war_room_ui_payloads.py`) | fixture |

Existing tests cover lineage and no-vote rules well, but **no** side-symmetry, monotonicity or bias property tests
exist (`tests/trade/test_analyze_trade.py:106-532`).

---

## 7. Proposed TC-C design (extends `analyze_trade`, no second engine)

### 7.1 Contract shape (`PACKET_VERSION = "analyze_trade_v3"`)

Additive. Every v2 field stays, so the Trade Desk and Best Offers consumers of `equity_verdict` are unaffected.

```jsonc
"decision": {
  "headline": "YES" | "NO" | "NOT_ENOUGH_EVIDENCE",
  "headlineText": "YES — MAKE THE TRADE" | "NO — DO NOT MAKE THE TRADE" | "A reliable recommendation cannot be made yet",
  "leaning": "MAKE|LEAN_MAKE|TOO_CLOSE|LEAN_PASS|PASS",      // v2 recommendation, kept as the graded detail
  "confidence": "HIGH" | "MEDIUM" | "LOW",                    // label only; no probability until validated
  "confidenceBottleneck": "<axis>",
  "goal": { "selected": "WIN_NOW|BALANCED|REBUILD|null", "inferredPosture": "PUSH|HOLD|RETOOL|REBUILD|null",
            "used": "WIN_NOW|BALANCED|REBUILD", "source": "user|inferred|default" },
  "components": { "objectiveValue": {...}, "rosterBenefit": {...}, "strategicFit": {...}, "feasibility": {...} },
  "primaryReason": {...}, "supportingFactors": [...], "mainCounterargument": {...} | null,
  "whatWouldChange": [...],
  "coverage": [ /* one record per dimension, §7.5 */ ],
  "receipt": {...}                                            // §7.7
}
```

### 7.2 The four components (each in its own unit, never summed across)

| component | question | unit | built from (existing owners) | direction bands (declared PRIORs) |
|---|---|---|---|---|
| **A. Objective package value** | do I receive more dynasty value than I give, after package adjustment and after the releases this trade forces? | canonical value points and % of the larger adjusted package | market lens (`equity_verdict`); **marginal** `roster_capacity.forced_drop_cost` (`:629-702`) for `A_net = gap − addedReleaseCost` (same canonical scale, the finder's existing rule); package-model receipt; unpriced share per side | relative gap with an absolute floor, replacing pure 256 / 769 after §5 re-evaluation; `stretch` reused only as "large" |
| **B. Personal roster benefit** | does my best legal lineup score more in the remaining weeks? | expected best-ball PPG (ROS, availability-aware after #1772) | roster lens unchanged (band = max(1.0, 2·SE), `large` = 3×); [later] `currentSeasonEquity` once `playoff_sim.simulate_trade_impact` is wired with availability (#1774/#1775) | as today (`config/trade/analyze_trade.json`) |
| **C. Strategic fit** | which of A and B should decide when they disagree, given my goal? | categorical (goal) + posture probabilities | user goal input (new request field `teamGoal`, default = inferred from posture: PUSH→WIN_NOW, REBUILD/RETOOL→REBUILD, HOLD→BALANCED, no evidence→BALANCED); canonical posture shown and overridable | none. C **never votes a direction** (posture is correlated with B, S10). It selects the precedence rule |
| **D. Feasibility** | can this trade be executed as built, and what must go? | gates + categorical | capacity state (existing); pick ownership (`ownedPickChecks`, `pickOwnership`); trade deadline (league settings); constraints owner `C3-CON-01`; [later] counterparty acceptance via `cross_market.external_package_verdicts` + `counterparty_capacity_block` | gate states, not points |

Release cost is charged **once**: its dynasty value is in A_net and its lineup effect is in B. Feasibility therefore
stops being a direction-stepping vote and becomes gates plus the A_net input. This fixes finding 2.

### 7.3 Combination: gates, then a goal-keyed lexicographic table

1. **Execution gates (D).** Any of the following makes the headline **NO** with the gate as the primary reason.
   These are facts, not evidence gaps.
   - the user's side sends a pick it is proven not to hold;
   - the trade deadline has passed (league setting proven);
   - an `EXCLUDE` / LOCK constraint is violated;
   - no legal cleanup exists (`ladderExhausted`).
2. **Evidence-sufficiency gates.** Any of the following makes the headline **NOT_ENOUGH_EVIDENCE**, naming the
   missing input.
   - A unavailable;
   - priced share of either side's value below a declared PRIOR floor;
   - goal ∈ {WIN_NOW, BALANCED} **in season** and B unavailable or abstaining. B is *not* essential in
     the offseason (`season_unresolved`); it is recorded as `not_applicable`;
   - capacity `unknown_limit` / `uncertain` when the trade grows the roster.
3. **Component directions.** A and B each yield favors / neutral / opposes plus `modest` | `large`, in their
   own units.
4. **Lexicographic resolution by goal.** No weights; the table is a declared PRIOR.

   | A \ B | B favors | B neutral / NA | B opposes |
   |---|---|---|---|
   | **A favors** | YES | YES | WIN_NOW: NO unless A large & B modest · BALANCED: YES only if A large & B modest, else NO · REBUILD: YES |
   | **A neutral** | WIN_NOW / BALANCED: YES · REBUILD: YES only if B large | **NO** (status-quo default) | NO |
   | **A opposes** | WIN_NOW: YES only if B large & A modest · BALANCED / REBUILD: NO | NO | NO |

   - "A neutral, B neutral → NO" encodes a status-quo default: a trade must clear a positive margin to
     earn a YES. This is the **smallest owner decision TC-C needs**: should a true near-tie read NO, or
     NOT ENOUGH EVIDENCE?
   - `leaning` keeps the five-level detail, so "NO (too close)" is distinguishable from "NO (pass)".
5. **No abstention flips.**
   - When a component abstains because of partial coverage, the headline is computed for **both** the
     favorable and unfavorable fill of that component.
   - If the two headlines differ, the answer is NOT_ENOUGH_EVIDENCE, naming the unprojected player.
   - If they agree, that headline stands with confidence capped at MEDIUM.
   - This makes P-MONO-2 hold by construction.

### 7.4 Confidence label (bottleneck, B11-style)

`confidence = min(axis levels)`. Thresholds are declared PRIORs until a calibration target exists.

| axis | HIGH needs | LOW when |
|---|---|---|
| coverage | every essential dimension evaluated | any essential dimension partial |
| margin | deciding component ≥ `large` | deciding component within 1.5× its neutral band |
| agreement | A and B agree, or the goal rule made one irrelevant | the goal rule overrode an opposing `large` component |
| asset evidence | no traded asset `confidenceBucket: low`, no unstamped asset | > declared share of package value on low / unstamped assets |
| precision | roster SE < band / 3 | SE ≥ band / 2 |

Second Opinions dispersion (S13) and comparables (S12) may only **lower** the agreement axis, through a declared
dispersion rule. They never raise it, because they are correlated with A.

Numeric probabilities stay off until a validation target exists.

### 7.5 Per-dimension coverage record

One per required dimension (10), always present:

```jsonc
{
  "dimension": "asset_value|immediate_improvement|long_term|roster_construction|market_evidence|competitive_strategy|risk|feasibility|opportunity_cost|league_constraints",
  "state": "evaluated|partial|unavailable|not_applicable|excluded_by_mode",
  "evidenceKind": "independent|correlated|contextual|explanatory",
  "lineage": "canonical_value|league_scored_projection|league_roster_rules|team_strategy_context|real_trade_ledger|ownership_records|…",
  "component": "objectiveValue|rosterBenefit|strategicFit|feasibility|null",
  "role": "gate|decides|tiebreak|confidence_only|explain_only",
  "evidence": { /* the numbers used, verbatim from the owner */ },
  "asOf": "<ISO-8601 or null>", "freshness": "fresh|stale|unknown",
  "applicability": { "state": "exact|approximate|not_applicable", "reason": "<string|null>" },
  "uncertainty": { "kind": "monte_carlo_se|confidence_bucket|range|none|unknown", "value": "<number|string|null>" },
  "contribution": { "direction": "favors|neutral|opposes|context|null", "magnitude": "modest|large|null", "unit": "<string|null>" },
  "exclusionReason": "<code|null>",
  "owner": "<module path>"
}
```

Rules:

- `state: evaluated` requires a non-null `evidence`.
- Only `evidenceKind: independent` with `role: decides` or `gate` may move the headline. This is enforced by
  test, which extends `test_at_most_one_vote_per_lineage`.

Today's mapping:

- asset_value → market lens;
- immediate_improvement → roster lens;
- long_term → `partial` (asset value only);
- roster_construction → feasibility;
- market_evidence → comparables, `explain_only`;
- competitive_strategy → posture, `tiebreak` via goal;
- risk → evidence lens, `confidence_only`;
- feasibility → capacity + pick ownership;
- opportunity_cost → `unavailable` (`not_wired`);
- league_constraints → `partial`.

### 7.6 Explanation fields

- **`primaryReason`**: the gate, or the component that decided under §7.3, with its number and unit. For example:
  `{component:"objectiveValue", text:"+1,240 package value after Value Adjustment (12% of the package)", unit:"canonical"}`.
- **`supportingFactors`**: 2–3 items. Take them from the remaining `reasonsFor` / `reasonsAgainst` aligned with the
  headline, ordered independent before correlated before contextual, at most one per lineage.
- **`mainCounterargument`**: the strongest opposing item, preferring an independent component and otherwise the
  largest correlated / context item, labelled with its kind. It is `null` only when nothing opposes.
- **`whatWouldChange`**: computed by **re-running the rule table on perturbed inputs**, never by subtracting a raw
  value from an adjusted gap (CLAUDE.md "simulate, never subtract"). Entries:
  - the smallest value added to or removed from the user's side that flips the headline, found by search
    over the active package model, the same way `findBalancers` simulates;
  - "if your goal were REBUILD";
  - "if <player> had a projection";
  - "if the cut were avoided".
  Each entry states the flipped headline.

### 7.7 Decision receipt

The receipt is stamped on every packet so that replay is exact:

- board generation id / `meta.generatedAt` and `scoringFingerprint`;
- `packageModel` receipt;
- projection basis (`horizon`, `scoringFingerprint`, families, season);
- availability basis [#1772];
- posture `paramsVersion` and `bundleFreshness`;
- `config/trade/analyze_trade.json` version and hash;
- comparables `methodology.status`;
- request hash (teams, assets, pick asset ids, goal, team-context flag).

Optional persistence uses the Trade Desk "Evaluated" status (user-entered, `trade_desk.py:37-47`). It never sends a
trade.

### 7.8 Competing verdicts: disposition

| surface | disposition |
|---|---|
| V2 / V3 / V9 TradeMeter + tray | keep as **Immediate Result, package only**; read bands from the same owner as component A (Python + JS parity test); one vocabulary; relative and absolute shown together and never contradicting (badge derived from the relative band with absolute floor) |
| V4 Fairness Explanation | keep; it explains V2; same band owner |
| V5 Monte Carlo | drop the "winner / favored" headline; label as "value-sensitivity check"; feed the meter's own totals (overrides / valueMode) or say it uses board values; not an input to the decision until `valueUncertainty` is audited (synthesis plan §A) |
| V6 Second Opinions tally | keep as dispersion, under the decision; adopt a declared "even" band (open owner decision); may only lower agreement confidence (§7.4) |
| V7 `teamImpact.verdict` | **retire from UI and packet** (or rename to `legacyShapeScore`, hidden); keep `starterDelta` / `depthDelta` / `lineupDisplacement` as roster information; fix "Net KTC equity" copy |
| V8 suggestions fairness | keep (generator label); same band owner |
| V10 BDVM | keep as second opinion; candidate long-term input only after methodology approval |
| V11 / V12 history | out of `/trade` scope; fix the non-monotone letter order; re-evaluate bands under geom |

### 7.9 Validation plan

1. **Property tests** P-SYM … P-PARITY (§6.2) are a TC-C merge gate.
2. **Scenario fixtures** from the posture addendum's list (`ANALYZE_TRADE_COMPETITIVE_POSTURE_ADDENDUM_2026-08-14.md`
   "Validation"). Examples:
   - contender paying a first for a large vs a tiny title jump;
   - rebuilder with and without its own first;
   - raw-value win that creates a positional hole;
   - small value loss that materially improves title odds.

   These are added as synthetic simulation payloads alongside `war_room_ui_payloads.py`.
3. **Historical replay** (no lookahead):
   - Completed own-league and Sharp trades from the canonical ledger, valued **at or before** the trade
     timestamp through `src/history/asof.py`.
   - Fidelity `exact` / `nearest-prior` only. Trades before `HISTORY_FLOOR` (2026-07-14) are excluded and
     never interpolated.
   - Report the headline distribution, the YES-rate by shape (star / depth), agreement with managers'
     acceptance (both teams accepted, so this tests *plausibility*, not correctness), and the headline-flip
     rate KTC→geom.
   - No outcome label is claimed. Per the synthesis plan §"Backtesting / governance", a "good trade" target
     must be defined before any calibration.
4. **Decision receipts** (§7.7) make every published answer reproducible. A replay harness re-runs a receipt
   and asserts an identical packet.
5. **Cross-surface parity:** backend packet → War Room desktop and mobile render the same headline, confidence and
   primary reason (Playwright journeys in TC-D).

### 7.10 Owner decisions this design needs (smallest set) — RESOLVED (owner, 2026-10-18)

All five were decided by the owner on 2026-10-18 and are binding. Each question is kept, followed by its decision.

1. Should a near-tie with full evidence read **NO** (status quo, proposed) or NOT ENOUGH EVIDENCE?
   **Decided:** a near tie with complete evidence reads **"NO — TOO CLOSE"**. NOT ENOUGH EVIDENCE is used only when
   material information is missing or uncertainty prevents a defensible recommendation.
2. The default goal when the user picks none: inferred posture mapping (proposed) or BALANCED.
   **Decided:** inferred from the existing competitive-posture classification plus league evidence: contender → win
   now, rebuilder → long-term value, uncertain / balanced → BALANCED. Always displayed; manual override always
   allowed.
3. Re-evaluated A bands under geom: absolute → relative-with-floor (proposed), values as PRIORs.
   **Decided:** re-evaluate for the geometric model as a relative difference with an absolute minimum; validate on
   offense, IDP, picks, consolidation and large packages; numbers provisional until tested; never modify q = 0.78.
   TC-A inventoried every current threshold as a PRIOR with provenance (workstream "TC-A notes").
4. The Second Opinions "even" band (already open in `SECOND_OPINIONS_TODO.md`).
   **Decided:** EVEN = within 1% of the larger adjusted side (initial, subject to validation). Independent opinions
   stay separate from canonical-fallback comparisons; fallbacks and correlated sources never count as independent
   votes. Implemented in TC-A (`OPINION_EVEN_TOLERANCE_PCT`, `frontend/lib/second-opinions.js`).
5. Retiring `teamImpact.verdict` from the UI.
   **Decided:** retire `teamImpact.verdict` as a competing YES/NO; keep the underlying analysis (starting-lineup
   changes, strength / weakness changes, bench depth, displacement, forced drops, roster construction, positional
   needs); feed independent information to the unified engine without double counting; ONE canonical decision
   owner. Implemented in TC-A: `verdict`, `compositeScore`, `equityScore` and the 0.55 / 0.45 weighting are removed
   from `src/trade/team_impact.py`, `config/trade/team_impact.json` and the Simulate impact panel (V7 above is
   retired).

Consequence for §7.3: the "A neutral, B neutral → NO" status-quo default stands, rendered as "NO — TOO CLOSE"
(decision 1). For §7.2 C, the default goal follows decision 2.

**Implemented (TC-C, 2026-10-18, branch `claude/trade-calculator-tc-c`, not merged):** the decision owner is
`src/trade/trade_decision.py` (packet `analyze_trade_v3`, field `decision`), following §7.2–§7.4 with these
deliberate simplifications: the confidence axes are coverage, margin, agreement, asset evidence and precision (§7.4);
the per-dimension coverage record (§7.5), "what would change it" (§7.6), decision receipts and replay (§7.7, §7.9)
are not built yet. Component A's bands come from the one fairness-band owner (`src/valuation_math/fairness_bands.py`,
decision 3). See the workstream "TC-C notes".

---

## 8. Completion result

- **STATUS:** DONE, for the audit deliverable only.
- **ACCEPTANCE:**
  - the live decision graph with `file:line`;
  - the origin map and four-kind classification with concrete double-counting risks;
  - the competing-verdict inventory;
  - the ten-dimension gap analysis;
  - the KTC-calibrated threshold list;
  - invariant risks with property tests;
  - the TC-C design.
- **EVIDENCE:** a read of `origin/main` `0b3194f190` code and docs, plus the diffs of #1772 (`e40fd1dac8`) and
  #1771 (`53cd6e4ac5`). No tests were run and no production observation was made.
- **UNRESOLVED:**
  - The numeric example disagreements in §3.2 and the monotonicity cases in §6.1 are derived from reading the
    code. They have not yet been reproduced by an executed test. TC-A/TC-C should land them as failing tests
    first.
  - #1774 / #1775 diffs were not read.
  - Production behavior is not observed.
- **BLOCKERS:** TC-C code waits on #1771 and #1772 merging (workstream coordination table).
- **NEXT_ACTION:**
  - Feed §3 (competing verdicts), §4 (gaps) and §5 (thresholds) into the TC-A threshold-provenance and
    parity work.
  - Land P-MONO-2 and P-SYM-1 as the first failing / guard tests.
