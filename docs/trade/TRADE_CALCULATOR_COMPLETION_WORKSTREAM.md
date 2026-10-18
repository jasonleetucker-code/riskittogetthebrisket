# Trade Calculator completion: audit, redesign and unified YES/NO decision engine

**Origin.** Owner master directive, 2026-10-17 ("MASTER AUDIT, REDESIGN & COMPLETION DIRECTIVE — Chase Upside — The
Ultimate Dynasty Trade Calculator"). It is added to the **current active implementation queue**; it does not replace
it. The work already in flight keeps its order and its commitments:

- injury/availability-aware simulations (#1772, #1774, #1775);
- IDP source rehabilitation (#1770, #1773, #1776–#1778);
- the geometric Value Adjustment activation (#1771);
- Manager Intelligence B–F (`docs/intel/MANAGER_INTELLIGENCE_WORKSTREAM.md`);
- draft-pick ownership.

Where to find the rest:

- Intake: `docs/OWNER_REQUESTED_TODO.md` → "Added 2026-10-17 — Trade Calculator completion".
- Authorization: `docs/EXECUTION_PLAN.md` → "Trade Calculator completion".
- Native IDs: `C3-CALC-01` (calculator maturity) and `C7-DESK-01` (Analyze Trade / decision contract). It also touches
  `C3-CALC-02` (overrides), `C3-CALC-03` (Second Opinions tally), `C3-PKG-01` (package model), `C2-SIM-01` (simulation),
  `C4-MTL-03` (comparable trades) and `C6-MGR-02` (partner intelligence).

The end state: one finished premium product at `/trade`. A user builds a trade, sees the immediate package comparison,
runs the complete analysis and gets **one** answer: **YES — MAKE THE TRADE** or **NO — DO NOT MAKE THE TRADE**. The
answer comes with confidence, the main reason, supporting factors, the main counterargument and what would change it,
and it is equally capable on desktop and mobile. When essential evidence is missing, the honest answer is
"a reliable recommendation cannot be made yet", never a forced binary.

## Rules that bind every batch

- **Authorities.** `CLAUDE.md` invariants: ONE CONCEPT / ONE CANONICAL OWNER, MISSING IS NEVER ZERO, no
  double counting, and point-in-time integrity.
- **Package model.** Every package-equity number comes from the one active model through
  `src/valuation_math/package_model.py` / `trade-logic.js::packageAdjustPair`.
  - The approved model is `geom_q078_v1`, q = 0.78. Its activation is PR #1771, owner-approved and in CI; until #1771 merges and deploys, `main` and production still run `ktc_2026_04`.
  - KTC (`ktc_2026_04`) stays available only as the named rollback / historical comparison.
  - The model and q are never changed as part of this work.
- **One decision engine.** The decision is extended in place, not rebuilt beside the old one: `src/trade/analyze_trade.py` (`/api/trade/analyze`) plus the War Room UI.
  - No widget computes a competing final verdict.
- **Kinds of evidence.** Each signal is classified as **independent evidence**, **correlated evidence**, a **contextual
  transformation** or an **explanatory output**. Only independent evidence moves the verdict, and it moves it once.
- **Evidence coverage.** Every decision dimension records evaluated or not, evidence, freshness, applicability,
  uncertainty, contribution and the exclusion reason. An absent input is never claimed as evaluated.
- **Confidence.** Confidence is a calibrated label. Numeric probabilities appear only once validated against a defined
  target.
- **Invariants.** The display side never changes objective math. The user's side and goal may change the personalized
  recommendation.
- **Gates.** Merges, deploys, model promotions and source-vote changes keep their gates and owner approvals.
  League Tycoon contract features stay deferred.
- **Design.** PSI Direction A (`docs/ui/CALCULATOR_UI_IMPLEMENTATION_CONTRACT.md`). Mobile is a first-class layout, not a
  compressed desktop.

## Batches (each one a reviewable PR, or a short train of PRs)

### TC-0 — Establish the truth (Deliverables 1, 2 and the current-page UX audit)

- `docs/trade/TRADE_CALCULATOR_FEATURE_MATRIX.md`. Every Trade Calculator requirement ever recorded, with:
  - the original intent, current implementation, production availability and backend/frontend owners;
  - data dependencies, canonical-value use, offense+IDP support, multi-team support and cross-feature consistency;
  - desktop and mobile UX, tests, production evidence, missing work, severity and the files/PRs needed;
  - a class: VERIFIED COMPLETE / IMPLEMENTED BUT UNVERIFIED / PARTIAL / DISCONNECTED / INCORRECT / NOT IMPLEMENTED /
    SUPERSEDED-DEFERRED.
- `docs/trade/TRADE_CALCULATOR_COMPETITIVE_ANALYSIS.md`. KeepTradeCut, DynastyProcess, Dynasty Daddy, FantasyCalc, DLF,
  Dynasty Nerds, FantasyPros, IDP Trade Calculator, DraftSharks, RotoTrade and others found during research.
  - Public, permitted evidence only; no paywall or authentication bypass.
  - What each does well and poorly, where we are stronger or weaker, patterns to adopt and patterns to avoid.
- `docs/trade/TRADE_CALCULATOR_UX_AUDIT.md`. Every section `/trade` renders today, on desktop and mobile, with
  screenshots: duplicates, competing verdicts, discoverability, scrolling and small-screen failures.
- `docs/trade/TRADE_DECISION_ENGINE_AUDIT.md`. The live Analyze Trade graph.
  - Which signals feed the verdict, a dependency/origin map, classification into the four evidence kinds, and
    double-counting risks.
  - The gaps against the ten required decision dimensions.

**Done when:** all four documents are committed, every finding cites a file, PR or production observation, and the gap
list feeds TC-A…TC-F below.

### TC-A — Correctness (critical first)

- **Package-model consistency.** Every surface that reports adjusted package equity must agree for the same inputs,
  model and context: headline, Analyze Trade, Second Opinions, finder, suggestions, balancers, multi-team, Trade History,
  current and at-time grades, public grades, simulations and package generators. Add a cross-surface parity test.
- **Thresholds calibrated under KTC.** Fair bands, balancer tolerances, finder acceptance, aging bands and fairness
  labels are re-evaluated for the geometric model. Any that are not recalibrated are labelled as provisional PRIORs
  with provenance.
- **Simulations consume availability.** Every simulation feeding trade evaluation uses player-week availability
  (follows #1772 and #1774).
- **Other correctness defects** surfaced by TC-0.

**Depends on:** #1771 (merged and deployed), #1772.

**Done when:** the parity test and threshold provenance are in place, and every defect is fixed with a test that failed
before and passes after.

### TC-B — Complete missing functionality

Every authorized requirement the matrix marks partial, disconnected or not implemented.

- **Builder:**
  - offense, IDP and picks through the horizon (generic / tier / exact);
  - multi-team trades, unequal counts, large packages;
  - import (KTC URL, screenshot), share and URL restore, clear and edit;
  - legitimate repeated generic picks;
  - honest unpriced assets.
- **Personalization:**
  - the selected league and team auto-load, using the actual league settings and never the owner's league as a global
    default;
  - roster consequences: lineup change, bench, replacement level, flex/superflex/TEP/IDP scarcity, forced drops, holes,
    depth and bye coverage.
- **Evidence and next actions:**
  - Second Opinions per `docs/trade/SECOND_OPINIONS_TODO.md` and the owner fallback spec: full-source vs hybrid,
    an independent tally and coverage;
  - comparable completed trades labelled by comparability;
  - next-action deep links into the existing trade engines: balancer, finder, package builder, Best Trade, Golden
    Upgrades, Manager Scout and Manager Intelligence.

**Done when:** every matrix row in scope reaches IMPLEMENTED with tests, on desktop and mobile.

### TC-C — Unified decision engine (YES / NO)

- Extend `analyze_trade` to produce the headline: **YES — MAKE THE TRADE / NO — DO NOT MAKE THE TRADE / NOT ENOUGH
  EVIDENCE**, plus confidence, the primary reason, 2–3 supporting factors, the main counterargument and what would
  change the verdict.
- It keeps the existing component separation:
  - objective package value;
  - personal roster benefit;
  - strategic fit (team goal win-now / balanced / rebuild, inferred posture shown and adjustable);
  - feasibility.
  These components are never summed across incompatible units.
- **Ten dimensions:** asset value, immediate improvement, long-term improvement, roster construction, market evidence,
  competitive strategy, risk, feasibility, opportunity cost and league constraints. Each has a coverage record.
- **Validation:**
  - no side bias, no star bias, no depth bias;
  - adding value to the user's incoming side never worsens the verdict without a real new constraint;
  - injury changes rest-of-season consequences but not long-term value;
  - backend, desktop and mobile agree;
  - confidence tracks evidence quality;
  - historical replay and decision receipts.

**Done when:** the engine and its property / holdout / replay tests are green, the evidence coverage is published, and
no other component computes a final verdict.

#### Owner decisions for TC-C — DECIDED (owner, 2026-10-18, binding)

These answer the five questions in `TRADE_DECISION_ENGINE_AUDIT.md` §7.10. They are recorded in
`docs/OWNER_REQUESTED_TODO.md` ("Added 2026-10-17 — Trade Calculator completion") and in the audit §7.10.

1. **Near tie.** A near tie with complete evidence reads **"NO — TOO CLOSE"**. **NOT ENOUGH EVIDENCE** is used only
   when material information is missing or uncertainty prevents a defensible recommendation.
2. **Default strategy.** Inferred from the existing competitive-posture classification plus league evidence:
   contender → **win now**, rebuilder → **long-term value**, uncertain / balanced → **BALANCED**. The strategy in use
   is always displayed and can always be overridden manually. **Refined (owner, 2026-10-18, final): RETOOL →
   BALANCED.** PUSH → win now, RETOOL → balanced, REBUILD → long-term, HOLD → balanced; RETOOL stays its own
   classification and is never called a rebuilder; a balanced decision weighs current competitiveness and long-term
   value and does not automatically prefer future picks over meaningful current production; the inferred
   classification, the strategy and the reasoning appear in the recommendation and the receipt.
3. **Fairness bands.** Re-evaluated for the geometric model as a **relative difference with an absolute minimum**,
   validated on offense, IDP, picks, consolidation and large packages. The numbers stay provisional until tested.
   q = 0.78 is never modified.
4. **Second Opinions "even".** EVEN = within **1% of the larger adjusted side** (initial, subject to validation).
   Independent opinions stay separate from canonical-fallback comparisons; fallbacks and correlated sources never
   count as independent votes. *Implemented in TC-A* (`d3c5fcc947`, `OPINION_EVEN_TOLERANCE_PCT`).
5. **`teamImpact.verdict`.** Retired as a competing YES/NO. The underlying analysis stays (starting-lineup changes,
   strength / weakness changes, bench depth, displacement, forced drops, roster construction, positional needs) and
   feeds independent information to the unified engine without double counting. ONE canonical decision owner.
   *Implemented in TC-A* (`822b9fb2f8`: `verdict`, `compositeScore`, `equityScore` and the 0.55 / 0.45 weighting
   removed from backend, config and UI).

### TC-D — Desktop / mobile redesign

- **Information architecture:** Trade Builder → Immediate Result (raw, VA, adjusted, net, quick verdict) → Final
  Decision → Supporting Intelligence (value, roster, lineup & simulation, second opinions, market, comparables, risk,
  reasoning) → Advanced Tools. Progressive disclosure throughout.
- **Desktop:** a two-column workspace with a sticky result and decision. Validate this against the measured layout.
- **Mobile:** builder sheets, a persistent verdict summary, contextual section navigation, touch targets of at least
  44 px, and no horizontal page scroll.
- **Artifacts:** before/after screenshots and Playwright desktop and mobile journeys.

**Done when:** the redesign ships behind the existing route with journeys green and no lost functionality.

### TC-E — Reliability and polish

- Immediate math stays separate from expensive analysis.
- Stale responses never overwrite newer trade states (request sequencing).
- Bundle and initial-load budgets; search latency; loading, error and partial states.
- Accessibility: keyboard, labels and screen-reader semantics.
- Measured before/after performance.

### TC-F — Final validation and release

- Run the full acceptance matrix from the directive §19, including real-stack and read-only production smoke tests.
- Write the production readiness assessment.
- Release through the normal RC / deploy gates with owner approval.

## TC-A notes (2026-10-18)

### Fixes on `claude/trade-calculator-tc-a`

| # | defect (source) | fix | test | commit |
|---|---|---|---|---|
| P0-1 | Monte Carlo clamped the package adjustment at 9999 per asset (meter VA 5,806 vs MC 1,879); `adjustedDelta` used a spread heuristic (UX audit) | full adjustment lands; `adjustedDelta` = raw + active VA; meter hands MC the override-applied sides | `tests/trade/test_monte_carlo_meter_parity.py`, `trade-mc-meter-parity.test.jsx` | `aca57e8270` |
| P0-2 | Simulate impact / MC results outlived edits and Clear | trade-signature keys + request sequencing | `trade-stale-results.test.jsx` | `9fcc10fb4a` |
| P0-6 | empty trade read FAIR / Gap 0 | `tradeEvaluationState` empty state on meter and tray | `trade-empty-and-unpriced-verdict.test.jsx` | `4f8709618f` |
| P0-4 | value-mode "Raw" rewired trade math onto the legacy composite | mode retired; trade math canonical only | `trade-raw-mode-retired.test.js` | `85603c4a40` |
| A07 | unpriced assets graded as 0 | INCOMPLETE headline; Analyze excludes and names them | `test_analyze_trade_unpriced.py`, `trade-empty-and-unpriced-verdict.test.jsx` | `fb20d50f16` |
| P0-7 | overrides silently ignored by War Room / Simulate impact | basis notice + "Includes N edited values" | `trade-override-basis-notice.test.jsx` | `0ec76de555` |
| P0-5 | War Room assumed Side A on a 0-0 roster tie | `resolveTeamSide`; asks which side | `trade-war-room-side-choice.test.jsx` | `6a2f4b2f90`, `74d66aa35b` |
| P1-6 | "Net KTC equity" / unqualified Equity on Simulate impact | labelled raw, before Value Adjustment | `test_team_impact_equity_label.py`, `trade-simulation-equity-label.test.jsx` | `a555b70573` |
| V11 | history letters non-monotone (A, A, A−, B+, A+) | monotone in both owners; cut points unchanged | `test_trade_grade_monotone.py`, `trade-grade-monotone.test.js` | `b3c2cf021d` |
| P1-8 | "2027 1st" / "2027 Mid" / "2027 Round 1" found nothing | structured pick query matching | `trade-pick-query-search.test.js` | `d3312bed74` |
| B06 | unknown pick ownership read as "no picks" | read through `lib/pick-ownership.js` | `trade-pick-ownership-unknown.test.js` | `ad927d0fee` |
| K13 | ROS Fit panel read the default league | league-scoped fetch + cache | `ros-trade-fit-league.test.jsx` | `6512d0e4ce` |
| C04 | share links dropped 3+-team routing and model | `d` + `pm` fields | `trade-share-routing-model.test.js` | `978efb95e0` |
| #14 | `/api/draft-capital` fetched twice per load | wait for the league to resolve | `trade-draft-capital-dedupe.test.jsx` | `bc7c835bb0` |
| #15 | no cross-surface package-equity parity test | shared fixture, both languages | `test_package_equity_parity.py`, `trade-package-equity-parity.test.js` | `ed9dff3743` |
| decision 5 | `teamImpact.verdict` competing YES/NO | retired from backend, config, UI | `test_trade_simulator.py`, `trade-simulation-equity-label.test.jsx` | `822b9fb2f8` |
| decision 4 | Second Opinions "even" only below 1 point | within 1% of the larger adjusted side | `second-opinions-even-band.test.js` | `d3c5fcc947` |
| review | two missing-to-zero coercions introduced on this branch (`symmetrize` adjustedDelta, override notice) | removed; two retired baseline entries deleted | `tests/trade/test_symmetrize.py`, coercion gate | `8f2e616e54` |
| review | War Room idle copy said "Pick your team" with a team selected (empty / one-sided trades answer no request since `6a2f4b2f90`) | copy keys on the selected team | `trade-war-room-side-choice.test.jsx` | `25a6dfe262` |
| review | four existing vitest cases broke on the trade-keyed Simulate impact gate (`9fcc10fb4a`) | `simulationSignature` helper; mocks and source check updated, gate unchanged | the three on-demand suites | `d6a84298c7` |

The parity test (#15) found no disagreement on the eight fixture pairings: every surface already computes the same
adjusted gap for the same numbers. Its documented intentional differences are the finder's retail-market basis (and
its no-adjustment-without-full-coverage rule), Second Opinions' vendor values, Analyze's exclusion of unpriced and
not-held assets, 3+-team trades (JS only), integer rounding, and external calculators priced on KTC.

### Fairness-threshold inventory

No value below was changed in TC-A. Unless stated otherwise, the provenance of each is **PRIOR — calibrated under KTC,
pending recalibration (owner decision 3, 2026-10-18)**. Decision 3 replaces them, after testing, with a relative
difference plus an absolute minimum, validated on offense, IDP, picks, consolidation and large packages. q = 0.78 is
not a threshold and is never modified. Under `geom_q078_v1` a 1-for-1 is unchanged; only multi-asset gaps change
meaning (engine audit §5). Line numbers are as of `d3c5fcc947`.

| threshold | value | where (file:line) | consumers | provenance |
|---|---|---|---|---|
| meter / tray verdict bands | FAIR < 350 · SLIGHT EDGE < 900 · UNFAIR < 1800 · LOPSIDED ≥ 1800 (absolute adjusted gap) | `frontend/lib/trade-logic.js:46-48` (`VERDICT_NEAR_EVEN` / `VERDICT_LEAN` / `VERDICT_STRONG_LEAN`), `:914` `verdictFromGap`, `:1946-1950` `meterVerdict` (literals) | TradeMeter badge, sticky tray, multi-team meter, `colorFromGap` | PRIOR — calibrated under KTC, pending recalibration (owner decision 3) |
| meter "worth N% more" winner text | ≥ 3% relative | `frontend/components/trade/TradeMeter.jsx:109`; `percentageGap` `trade-logic.js:1960` | TradeMeter | PRIOR — calibrated under KTC, pending recalibration (owner decision 3) |
| fairness explanation | "even" < 3% relative; notable source gap ≥ 200 | `frontend/components/trade/TradeFairnessExplanation.jsx:142`, `:56` (`MIN_NOTABLE_GAP`) | fairness sentence | PRIOR — calibrated under KTC, pending recalibration (owner decision 3) |
| market lens even / lean / stretch | < 256 · < 769 · ≥ 769 | `src/trade/suggestions.py:962-968` (`_fairness_label`), `:144` (`FAIRNESS_TOLERANCE = 769`) | Analyze market lens direction and strength (`analyze_trade.py:159-185`), `equity_verdict.win` → Best Offers / Package Builder, suggestion fairness badge and rank bonus (`:1022`) | PRIOR — calibrated under KTC, pending recalibration (owner decision 3) |
| JS balancer trigger | adjusted imbalance ≥ 350; top 5 | `frontend/lib/trade-logic.js:1608` (`VERDICT_NEAR_EVEN`), `:1601` (`maxResults = 5`); `frontend/app/trade/page.jsx:1064`, `:1103`, `:1989` (literal 350) | `findBalancers`, 2-team and multi-team balancer panels | PRIOR — calibrated under KTC, pending recalibration (owner decision 3) |
| Python balancer trigger | \|gap\| ≥ 256; at most 2 | `src/trade/suggestions.py:1595`, `:1726` (`MAX_BALANCERS = 2`) | suggestions equalizer | PRIOR — calibrated under KTC, pending recalibration (owner decision 3) |
| suggestion overpay / consolidation | 1.5× and 2.0× of 769; consolidation 0.70 / 0.30 | `src/trade/suggestions.py:1524`, `:163` / `:1493`, `:151`, `:158` | suggestion generation | PRIOR — calibrated under KTC, pending recalibration (owner decision 3) |
| angle gains | my gain ≥ 5%, market gain ≤ 5% | `src/trade/angle.py:430-431`, checked at `:548-550` | Angle Finder | PRIOR — calibrated under KTC, pending recalibration (owner decision 3) |
| finder acceptance ratios | junk < 350; 2-for-1 ≥ 0.55; elite ≥ 0.65; anchor ≥ 0.35 | `src/trade/finder.py:53-54`, `:147-148` | finder candidate acceptance | PRIOR — calibrated under KTC, pending recalibration (owner decision 3) |
| Monte Carlo headline | win % 80 / 60 / 40 / 20 | `frontend/components/ui/MonteCarloButton.jsx:108-130` | MC summary sentence | PRIOR — calibrated under KTC, pending recalibration (owner decision 3); relabel as sensitivity in TC-C (audit §7.8) |
| trade-history letter grades | 3 / 8 / 15 / 25 / 40 % of the larger effective side | `frontend/lib/league-analysis.js:94-105`; `src/public_league/trade_grading.py:54-58` | /trades, public /league timeline | PRIOR — calibrated under KTC, pending recalibration (owner decision 3). Letters made monotone in TC-A; cut points unchanged |
| trade aging "stable" band | ± 200 adjusted | `frontend/lib/trade-history-grades.js:34` (`AGING_STABLE_BAND_PRIOR`), applied `:155-157` | How It Aged verdict | PRIOR — calibrated under KTC, pending recalibration (owner decision 3); already a declared PRIOR (TRADE_HISTORY_AGING_SPEC §5) |
| Second Opinions "even" | within 1% of the larger adjusted side (1-point floor) | `frontend/lib/second-opinions.js:295` (`OPINION_EVEN_TOLERANCE_PCT`), `:305` | per-source leader, independent / modeled tallies | owner decision 4 (2026-10-18): initial value, subject to validation. Replaced the historical < 1 point in TC-A |
| external calculator "even" | 0.0% | `src/league_intel/cross_market.py:798` (`EXTERNAL_EVEN_TOLERANCE_PCT`) | Best Offers qualification | owner default; external calculators are priced with KTC by design ("what KTC says"), so not a geom recalibration target |
| `teamImpact` composite verdict | 0.55 / 0.45, ± 8 / ± 20 | — | — | RETIRED in TC-A (owner decision 5, `822b9fb2f8`) |

### Gates run on the TC-A head (2026-10-18)

- `bash scripts/format_python_changes.sh`: GREEN (Ruff 0.6.9). `check_decision_coercions.py`: clean.
  `check_planning_integrity.py`: exit 0. `check_product_plan_governance.py`: clean.
- `pytest tests/trade tests/valuation_math tests/public_league tests/identity -q -p no:randomly`: 3133 passed.
- Full `npx vitest run`: 303 files / 3955 tests passed (jsdom "navigation not implemented" stderr noise only).
- `npm run build:nocheck` + `npm run check:bundles`: every page under budget; `/trade` 85.1 KB of 93 KB.
- Playwright trade specs: NOT run (no Playwright browsers in the environment, no local stack).

### What TC-A does not do

- Simulations consuming player-week availability (#1772 follow-through, TCM-H06) — not in this batch.
- One fairness-band owner served to the client (TCM-E01) and the decision-3 recalibration — TC-C.
- Asset-Only analysis without a selected team (TCM-G10): the backend still requires a team.
- Analyze still returns a recommendation (with capped confidence) when an asset is unpriced, while the meter refuses a
  verdict. Decision 1 (NOT ENOUGH EVIDENCE when material information is missing) closes this in TC-C.

## TC-C notes (2026-10-18)

Implements the five owner decisions above on `claude/trade-calculator-tc-c` (stacked on TC-A). Acceptance is on
`dynasty_main` only (owner scope correction, 2026-10-18).

### One decision owner

- `src/trade/trade_decision.py` is the only producer of the top-line answer: **YES — MAKE THE TRADE**, **NO — DO NOT
  MAKE THE TRADE**, **NO — TOO CLOSE**, **NOT ENOUGH EVIDENCE**. `analyze_trade` builds the evidence (lenses over the
  canonical owners) and calls `decide()` once; packet `analyze_trade_v3` carries `decision`. The v2 `recommendation`
  stays as the graded leaning, and its rule table moved into the decision owner.
- The decision carries: headline + text, `missingEvidence` (each gap named, with its evidence), `reasons` (each with
  the evidence it used), `primaryReason`, `mainCounterargument`, `strategy` (requested / requestedValid / used /
  source, options, the posture map), `posture`, `bands` (the fairness-band receipt), a `confidence` label with the
  bottleneck axes and a statement (`isProbability: false`), `recommendationOnly: true`, `executes: false`.
- The War Room renders it verbatim (`decision.headlineText`) with a strategy control that sends `teamGoal`.
- `tests/trade/test_trade_decision_owner.py` pins: only the owner holds the headline texts in the backend; no
  frontend module builds them; `analyze_trade` calls `decide()` exactly once; `teamImpact.verdict` stays retired; the
  owner imports only stdlib + `src.valuation_math`.

### How it decides (no weights)

1. **Strategy** (decision 2 + the final RETOOL decision): `teamGoal` override, else posture PUSH → WIN_NOW, RETOOL →
   BALANCED, REBUILD → LONG_TERM, HOLD → BALANCED (a no-evidence HOLD is BALANCED and says so); posture unavailable →
   unknown. BALANCED is symmetric: a large gain in one component with a modest loss in the other is a YES either way;
   WIN_NOW takes any large lineup gain; LONG_TERM takes any value gain.
2. **Execution gate:** no legal roster cleanup → NO.
3. **Evidence gates** (decision 1) → NOT ENOUGH EVIDENCE: no priced assets; off-board, unpriced, unheld, quarantined
   or stale traded assets; unknown pick ownership with picks traded; unknown roster, roster limit or posture; an
   unpriced forced cut; a traded player without a projection when the strategy is WIN_NOW / BALANCED in season. An
   offseason roster (`season_unresolved`, `no_remaining_fantasy_weeks`) is *not applicable*, not missing.
4. **Components:** A = the adjusted package gap net of the release cost of cuts the trade adds, classified by the
   fairness-band owner; B = the best-ball roster utility lens. A goal-keyed table decides; the strategy only breaks a
   disagreement between A and B. A near tie with complete evidence → NO — TOO CLOSE.

How often the value gates can fire, measured on the board rebuilt from `exports/latest/dynasty_data_2026-10-17.json`
(1,130 rows, 740 ranked): confidence-owner freshness `low` on 2 rows (0 ranked, 0 in the top 200); `quarantined` on
60 rows. Picks carry no freshness axis, which reads as "not stale", never as fresh-by-default evidence.

Validated by `tests/trade/test_trade_decision.py`: every gate, the near tie, the strategy map and override, the
disagreement table, the forced-cut charge, monotonicity (more incoming value never worsens the answer, for every
goal and roster effect), asset-only side symmetry, and `teamImpact` unable to influence the result.

### One fairness-band owner (decision 3)

`config/trade/fairness_bands.json` (`fairness_bands_v1`, **PROVISIONAL**) + `src/valuation_math/fairness_bands.py` +
the pinned mirror `frontend/lib/fairness-bands.js`. Relative to the larger ADJUSTED side: fair under 3.5% or under 250
points, slight < 9%, unfair < 18%, lopsided beyond. The cut points are the KTC-era 350 / 900 / 1800 expressed relative
to a 10,000-point side, so a one-star trade reads as before and a bench trade is no longer graded on a star's scale;
250 is the tighter existing even band, rounded. q = 0.78 is untouched (asserted).

Validation: `tests/fixtures/fairness_band_cases.json` (offense, IDP, picks, consolidation, large packages,
boundaries; package cases from the parity fixture under `geom_q078_v1`) asserted in Python and JS, plus sign
blindness, monotonicity, scale invariance above the minimum and no asset-class input. Against the retired absolute
meter, 5 of 24 cases change level (bench 300 on 1,500: fair → lopsided; IDP 400 on 3,300: slight → unfair; picks
1,400 on 3,200: unfair → lopsided; 600 on 30,000: slight → fair; 250 on 1,000: fair → lopsided). That is the intended
effect of a relative band; the numbers remain provisional until validated against a defined target.

Consumers now on the owner: the /trade meter badge and winner text, the multi-team meter, the sticky tray, both JS
balancer triggers and `findBalancers`, the fairness explanation, the Analyze market lens / `equity_verdict` (so Best
Offers and the package builder), the decision, the suggestions badge and the suggestions equalizer trigger.

Retired by this: meter 350 / 900 / 1800, the 3% winner-text and explanation band, market lens 256 / 769, JS balancer
350 (four sites), Python balancer 256. Still separate, by design, and still PRIOR (calibrated under KTC, pending
recalibration): the suggestions generator tolerance 769 and overpay multiples (generation, not a verdict), angle ±5%,
finder ratios, the Monte Carlo headline bands, history letter grades (out of `/trade`), aging ±200 and external "even"
(KTC by design).

### Gates run on the TC-C head (2026-10-18)

- `format_python_changes.sh`: GREEN (Ruff 0.6.9). Coercion check: clean. Planning integrity: exit 0. Product-plan
  governance: clean.
- `pytest tests/trade tests/valuation_math tests/public_league` (plus `tests/test_trade_suggestions.py`,
  `tests/api/test_trade_simulator.py`, `tests/api/test_trade_simulate_mc.py`): 3108 passed.
- Full `npx vitest run`: 304 files / 3988 tests passed.
- `build:nocheck` + `check:bundles`: all pages under budget; `/trade` 87.8 KB of 93 KB (TC-A head: 85.1 KB).
- Playwright and a real-stack run on `dynasty_main`: NOT run (no browsers or local stack here).

### Fairness-band impact, measured on real data (decision 3)

`scripts/measure_fairness_band_change.py` (read-only). Raw output: `docs/trade/tc-c-fairness-band-impact/results.json`.

Method:
- **Board:** rebuilt from `exports/latest/dynasty_data_2026-10-17.json` with its own rosters (`dynasty_main`, 12
  teams).
- **Old vs new:** each surface runs under the NEW bands and under the retired absolute rule (even < 256, lean < 769),
  restored by monkeypatching the one `fairness_bands.classify`.
- **Qualified candidates:** captured at the engines' own seam (`best_offers._factors`, called once per candidate
  that passed every hard rule).
- **Mode:** Asset-only for Best Offers and the Package Builder (the band enters only through `equity_verdict`).
- **Coverage:** Best Offers for all 132 opponent cards; the Package Builder for 36 "sell a player" requests;
  suggestions for every team.

**Qualification**, reported separately from ranking. Measured AFTER the owner's Best Offers decision (2026-10-18, Option B,
below); the board is rebuilt from the same export with current code, so the OLD baselines differ slightly from the
pre-decision run:

| surface | qualified OLD → NEW | kept | dropped | added |
|---|---|---|---|---|
| Best Offers | 45,055 → 45,328 | 45,055 | 0 | 273 (9 small, 232 IDP, 0 picks, 240 consolidation; 1.21–12.3% / 250–255 pts) |
| Package Builder | 72,980 → 73,375 | 72,915 | 65 (250–255 pts against, 3.5–6.1%) | 460 (256–379 pts against, ≤ 3.5%) |
| Suggestions | 45 → 45 | 38 | 7 (consolidations re-badged lean → stretch at about 9–10%, replaced) | 7 |

Best Offers candidates judged: 1,368,084; 2,589 qualified ONLY by the meaningful-gain rule (band FAIR, gain ≥ 250).

**Pre-decision figures (superseded, kept for the record — NOT post-decision measurements):** Best Offers 44,376 →
43,413 (43,208 kept; 1,168 dropped: 0 small, 460 IDP, 974 consolidation, 1.25–3.50% / 256–774 pts; 205 added: 3.53–12.3% /
250–255 pts); Package Builder 72,941 → 73,353 (64 dropped / 476 added); suggestions 45 → 44 (8 dropped / 7 added).

**Ranking among trades qualified under both:**
- **Best Offers and Package Builder:** 0 order changes in 140 / 139 groups and 0 top-trade changes. Their ranking
  does not take the band as an input.
- **Suggestions:** 4 of 37 kept trades changed rank, and 5 were relabelled. Their ranking uses the band through the
  rank bonus.

**What a user would see:**
- **Best Offers:** 131 of 132 cards serve the same offer under both bands, and the last one has no offer either way.
- **Package Builder:** for the best package per opponent, 377 kept, 3 added, 1 dropped.

**Exclusions (pre-decision).** Before the owner's decision the only material removal was Best Offers' 1,168 "canonical
wins" on large packages (larger side about 20,000+) ahead by under 3.5% — largest example: Joey gives Gibbs +
Smith-Njigba for Burrow + Mahomes + Olave, +774 on 22,581 (3.43%). None was a served offer.

**Owner decision (2026-10-18, Option B) — APPLIED, Best Offers only.** A positive VA-adjusted canonical gain of at
least the band owner's `absoluteMinimum` (currently 250) qualifies a Best Offers package as a meaningful opportunity
even when the band rates it FAIR. `best_offers.best_offers_qualification` names the basis (`canonical_win` /
`meaningful_gain`) on each offer (`qualification`); the FAIR label, the thresholds, `equity_verdict` and its `win` flag
are unchanged; the card states the actual gain and band ("+774 … a meaningful gain (at least 250 points), though the
fairness band rates the package FAIR, 3.43% …"), never "clear win" for a FAIR package. Every other hard gate is kept
(plausible shape, whole-package native coverage, opponent even or better, constraints, protections). Not applied to
the Trade Calculator YES/NO, the fairness meter or the Package Builder. Post-decision result above: the 1,168 come back,
nothing is dropped. Tests: `tests/trade/test_best_offers_meaningful_gain.py`.

**Validation status: NOT validated, still PROVISIONAL.** Missing:
- a defined target (realized trades valued at the time, or an owner-labelled fair / unfair set);
- a fit of the cut points against that target, with a holdout;
- more than one board date;
- Team Context runs.

**Trade Finder lane.** TC-A and TC-C changed **0 lines** in `best_offers.py`, `golden_upgrades.py`,
`package_builder.py`, `finder.py` and the `/arbitrage` views. Best Offers and the Package Builder reach the band owner
only through `analyze_trade.equity_verdict`. Golden Upgrades uses no band and no package model: its pairs are
1-for-1, and its inversion minimums are a separate PRIOR.

### What TC-C does not do

- Monte Carlo still shows its own "favored" sentence (relabel planned in TC-D, audit §7.8).
- Historical replay is **asset-only** (`src/trade/decision_replay.py`, values from `src/history` as-of reads).
  Team-context replay is DEFERRED: no as-of store exists for rosters, roster rules, projections or posture.

Built since the first TC-C head:
- `whatWouldChange`: the smallest flip found by re-running the decision;
- the ten-dimension `coverage` record;
- the decision `receipt`;
- decision receipts through AL-P5 (`src/trade/trade_decision_log.py` → `producer_receipts` section 6 → the existing
  `scripts/trade_decision_receipts.py`).
- Second Opinions dispersion and comparables do not yet lower the agreement axis.
- The fairness bands are provisional: no validation target exists yet to fit them against.

## TC-B notes (2026-10-18)

Branch `claude/trade-calculator-tc-b`, on `origin/main` `c290dea0a8` (TC-A and TC-C merged). Acceptance is on
`dynasty_main`. Code commits: `2bd2986ddd` (backend: roster-lens holes, partner evidence endpoint) and `8625ab7b77`
(frontend: builder, personalization, next steps). Agent-OS-Receipt: `cdca1dca8385f70c0989302dece8d1bd4ce4843c`.

### Inventory — every matrix row in TC-B scope, re-verified against live code

The scope is every row whose Batch cell names TC-B (30 rows, including the shared `TC-B / TC-C` and `TC-B / TC-D`
rows), plus TCM-N03, whose Batch cell assigns "a banner now in TC-B". Each claim was re-checked on live code; where the
matrix was stale it says so. Line numbers are as of `8625ab7b77`. "Done" means implemented with tests in this batch
(TC-B1); it is IMPLEMENTED BUT UNVERIFIED until observed in production.

| row | state found (TC-0 class → re-verified) | live path (file:line) | what was missing | owner | TC-B1 |
|---|---|---|---|---|---|
| A02 position mix | NOT IMPLEMENTED — confirmed | `frontend/app/trade/trade-sections.jsx:757`; helper `frontend/lib/trade-assets.js:426` | a per-side mix | display (`trade-assets.js`) | **done** |
| A03 row metadata | PARTIAL — confirmed: no age | `trade-sections.jsx:381` (`formatAssetAge`) | age on the row | display; age from the contract row | **done** |
| A05 stable identity | PARTIAL — confirmed: players key on name (`trade-assets.js:71`), share links carry names | `frontend/lib/trade-assets.js:71`, `frontend/lib/trade-share.js:322` | key players by `playerId` across workspace / share / import | `trade-assets.js`, `trade-share.js` | remaining — changes the share format, which Manager Intelligence Batch D seeds `/trade` through right now |
| B04 generic picks | PARTIAL — confirmed: no uncertainty shown | `trade-sections.jsx:439`; wording `frontend/lib/pick-provenance.js` + `pick-provenance-text.js` | the PRIOR on derived rows; C1-U7 distributions | backend `pickValueProvenance` (C1-U6); C1-U7 | **calculator half done** (badge + basis); C1-U7 distributions remain (a separate owner) |
| B06 unknown pick ownership | IMPLEMENTED BUT UNVERIFIED (TC-A) — confirmed | `frontend/app/trade/page.jsx` pick-ownership banner | production observation | `lib/pick-ownership.js` | no change |
| C04 share restore | PARTIAL — confirmed: `parseShareParam` returns `null` on an unknown version (`trade-share.js:334`) | `trade-share.js:334` | per-asset degrade; stable ids (A05) | `trade-share.js` | remaining — share-format freeze (Batch D) |
| D14 override reset | IMPLEMENTED INCORRECTLY — confirmed: per-row "Reset" beside every overridden input | was `trade-sections.jsx` (now `:502`, a comment) | remove the per-row reset; keep the global one | `trade-sections.jsx` | **done** (#781) |
| F03 equalizer combos | PARTIAL — confirmed: singles only | `frontend/lib/trade-logic.js:1623` (`findBalancers`) | pairs when no single closes the gap | `findBalancers` (the JS balancer owner) | **done** (`combos: true`) |
| F05 pick-context link | PARTIAL — confirmed: a pick opens the quick-view popup only | `trade-sections.jsx` `PlayerNameButton` | a pick-context link | — | remaining (P3) |
| G09 3+ team analysis | NOT IMPLEMENTED — confirmed: War Room renders only for 2 sides | `page.jsx:2478` | N-side analysis, or state the limitation | `trade_decision.py` (N-side would be TC-C scope) | **limitation stated** (the matrix's second option); N-side analysis not built |
| G18 Trade Desk ↔ decision | PARTIAL — confirmed | `src/trade/trade_desk.py:361` | attach the Analyze packet to saved ideas | `trade_desk.py` | **Save from /trade done (O13)**; the Analyze packet attachment remains |
| H03 capacity for both teams | PARTIAL — confirmed: `forced_drop_cost` ranks the selected team only (`src/trade/finder.py:1148`); suggestions carry no counterparty block | `finder.py:1148`, `src/trade/suggestions.py` | rank counterparty cost, consolidation credit, suggestions block | `roster_capacity.py` consumers | remaining — Trade Finder lane (generator ranking) |
| H12 roster consequences | PARTIAL — re-verified: availability (#1772) now merged, so byes and injuries are modelled; holes / bye coverage were not reported; no replacement-level report | `src/roster_intel/best_ball_utility.py:242`, `:575`; UI `frontend/components/trade/TradeWarRoom.jsx:349` | holes, bye coverage, replacement level | `best_ball_utility.py` (one exact solver) | **holes + bye coverage done**; replacement level remains (`rosterSpot.shadowValuePpg` is still `None`, `best_ball_utility.py:589`) |
| I04 league + team auto-load | PARTIAL — re-verified: the ROS panel league defect was fixed in TC-A, but `useTeam` still auto-selected a hardcoded owner team ("Rossini Panini") on the default league for any user the server could not place | `frontend/components/useTeam.js:245` | no owner team as a global default | `useTeam` + `/api/leagues` `userDefaultTeam` | **done** |
| K03 immediate tally | PARTIAL — confirmed: the tally rendered only inside the folded panel | `page.jsx:2550`; rows `frontend/lib/second-opinions-rows.js` | surface it outside the fold | `lib/second-opinions.js` (tally), one row assembly | **done** |
| K06 source unavailable | NOT IMPLEMENTED — confirmed: rows carry `freshnessExcludedSources` (`src/api/data_contract.py:4857`) but Second Opinions ignores it | `frontend/lib/second-opinions.js:191` | an "unavailable" state | `second-opinions.js` | remaining — `SECOND_OPINIONS_TODO.md` lists it as an open owner decision (it changes which rows vote) |
| K13 ROS Fit | PARTIAL — confirmed: league-scoped since TC-A, not labelled | `frontend/components/RosTradeFitPanel.jsx:162` | label it as the public deadline view | `RosTradeFitPanel.jsx` | **done** |
| L01 recent real trades | IMPLEMENTED BUT UNVERIFIED — confirmed: no Trade Database link | `frontend/components/trade/RecentRealTrades.jsx:212` | a link into the Trade Database | `RecentRealTrades.jsx` | **done** |
| L05 comparability labels | PARTIAL ("not confirmed" in TC-0) — **stale**: every card already renders the ledger's disposition (`formatMatchText`, `frontend/lib/recent-real-trades.js:122`, shipped with TC-09) | `recent-real-trades.js:122` | nothing; a test per disposition | `market_trade_format.py` (disposition) | **verified in code + test added** |
| M01–M07 charts / facts | NOT IMPLEMENTED — confirmed | — | stacked bars, identity map, trend chart, facts table, dispersion, value span, 30-day movers | presentation; M03/M06 need a `src/history` read endpoint | remaining (P3) |
| N03 historical replay banner | NOT IMPLEMENTED — confirmed: `/trades` opens `/trade?share=` in live mode (`frontend/app/trades/page.jsx:429`) | `trades/page.jsx:429` | an as-of mode or a banner | `trade-share.js` restore | remaining — telling a history link from any other share link needs a URL change, and the share format is frozen while Batch D seeds `/trade` through it |
| O11 next-action links | NOT IMPLEMENTED — confirmed | `page.jsx:2623`; owner `frontend/lib/trade-next-actions.js`; reader `frontend/app/arbitrage/page.jsx:452` | contextual links into the engines | the engines (unchanged) | **done** |
| O12 partner intelligence | NOT IMPLEMENTED — confirmed | `src/intel/manager_scout_api.py:196`; `frontend/components/trade/TradeNextActions.jsx` | a counterparty panel consuming Scout / MI | `manager_scout.offer_evidence` | **done** (Scout evidence for this package; MI by link — `/managers` needs a Sleeper username the contract does not carry) |
| O13 Save to Trade Desk | PARTIAL — confirmed: generated cards only | `TradeNextActions.jsx` → `SaveToDeskButton`; `trade_desk.py:62` (`calculator` source already allowed) | the button on /trade | `trade_desk.py` | **done** |
| R01 announcement banner | NOT IMPLEMENTED — confirmed | — | config-driven announcement with expiry | — | remaining (P3, low) |

Task-list items with no TC-B matrix row, verified: **legitimate repeated generic picks** (TCM-A08, IMPLEMENTED BUT
UNVERIFIED, TC-F) and **honest unpriced assets** (TCM-A07, done in TC-A) are both live on `main`; nothing to build.
**Forced drops** (TCM-H02) are VERIFIED COMPLETE. **Second Opinions full-source vs hybrid tally and coverage** were
already complete after VA PR2 (`TradeSourceBreakdown`, `tallyOpinions`); what was missing was the immediate surface
(K03), now done.

### What TC-B1 does (and how each piece stays inside its owner)

- **No second engine.** The equalizer pairs extend `findBalancers` in place and are simulated whole through
  `tradeImbalance`; partner evidence is `manager_scout.offer_evidence` verbatim; holes are counted inside the one
  best-ball utility run; the tally reads the one row assembly the per-source table now uses.
- **Never a vote.** `lineupHoles` is explanatory: BBLI already scores an empty slot as zero, so it does not enter the
  decision (`trade_decision.py` unchanged). The tally states counts, not a verdict. Next steps change no total.
- **Missing is never zero.** A missing age is absent; a slot only an unprojected player fits is named
  (`onlyUnprojected`), not hidden; a roster with no projected player has unknown holes (`None`); a player with no id
  is counted as "not in the filter", never matched by name; partner history that is not measured says why.
- **Share format untouched** (Batch D seeds `/trade` through it). The new deep links point away from `/trade`.
- **Bundle.** The tally and Next steps are `React.lazy`; the long derived-pick prose lives in its own module so the
  page chunk carries only the label. `/trade` 91.7 KB of 93 KB (main `c290dea0a8`: 88.9 KB; TC-C head: 87.8 KB).
  Headroom is 1.3 KB — TC-D must split before it adds.
- **Declared PRIORs added:** `BALANCER_PAIR_POOL = 8` and `BALANCER_MAX_PAIRS = 2` (`trade-logic.js`), bounds on
  the pair search, not fitted.

### Gates run on the TC-B head (2026-10-18)

- `format_python_changes.sh`: GREEN (Ruff 0.6.9). Coercion check: clean.
- `pytest tests/trade tests/roster_intel tests/intel/test_manager_scout_*` + `tests/api/test_trade_simulator.py` +
  `tests/api/test_trade_simulate_mc.py`: 2825 passed, 22 skipped.
- Full `npx vitest run`: 325 files / 4128 tests passed.
- `build:nocheck` + `check:bundles`: all pages under budget; `/trade` 91.7 KB of 93 KB.
- Playwright `tests/e2e/specs/trade-next-actions.spec.js` written (desktop + phone projects, test ids, partner
  request mocked); NOT run — no Playwright browsers or local stack here.

### Remaining in TC-B (TC-B2 and later)

A05 and C04 (stable player ids and per-asset share degrade) and N03 (history banner) wait for the share-format freeze
to lift; K06 waits for the owner decision; H03 belongs to the Trade Finder lane; G18 needs the Analyze packet stored
on a desk item; H12 replacement level needs the waiver-pool projection join; B04 needs C1-U7; F05, M01–M07 and R01
are P3.

*Superseded by "TC-B2 / TC-D2 notes" below* — K06 is now DECIDED (owner closeout 2026-10-18, decision 9) and
implemented; the share-link format stays frozen (decision 10), so N03 ships as a banner without a URL change, C04 ships
its restore half, and A05 stays open.

## TC-D notes (2026-10-18)

Branch `claude/trade-calculator-tc-d`, **stacked on TC-B1** (`claude/trade-calculator-tc-b`, #1800, head
`9cc840a33f`). Code commit `ecbde07821`. Agent-OS-Receipt: `cdca1dca8385f70c0989302dece8d1bd4ce4843c`. Phase D1: make room,
then the core layout. Not merged, not deployed, not observed in production.

### Bundle headroom first

`/trade` was 91.7 KB of 93 KB. A source-map attribution of the page chunk (temporary `productionBrowserSourceMaps`
build, not committed) put `TradeWarRoom.jsx` + its CSS at about 19.5 KB, the largest module the page still carried;
everything else on the candidate list (Second Opinions, comparables, Trade Desk, next actions, screenshot import) was
already `React.lazy`. The War Room is now one more `dyn(...)` section (`React.lazy` + its own `Suspense` +
`ResilientSection`, never `next/dynamic`), prefetched on mount next to the player-pool fetch. It shows nothing before
its first `POST /api/trade/analyze` answers (a 700 ms debounce after two filled sides), so nothing visible changes.

| build | `/trade` page chunk |
|---|---|
| TC-B head `9cc840a33f` | 91.7 KB / 93 KB (1.3 KB headroom) |
| War Room split only | 72.5 KB (20.5 KB headroom) |
| D1 (split + layout) | **77.9 KB (15.1 KB headroom)** |

### Information architecture (UX audit §7 hypothesis, implemented)

| layer | anchor | contents (owners unchanged) |
|---|---|---|
| 1. Trade builder | `#trade-builder` | quick-add (mobile, now in flow), controls, pick-ownership / share / import banners, KTC panel, screenshot dialog, pick team selectors, side cards |
| 2. Immediate result | `#trade-result` | raw / VA / adjusted per side (`DataTable`, from `sideTotals`: adjusted = raw + VA), "How the verdict works", `TradeMeter` (+ Monte Carlo), the experimental stack note |
| 3. Final decision | `#trade-decision` | the Trade War Room (or the 3+-team limitation); on desktop an echo of its headline, confidence and primary reason sits in the sticky column |
| 4. Supporting intelligence | `#trade-intelligence` | the Simulate impact result (no longer inserted above the builder), Second opinions, Recent real trades |
| 5. Ideas & tools | `#trade-tools` | Next steps, the proactive rail (no longer above the builder), the suggestions desk |

- **One decision.** The echo is the War Room's own answer, reported up through a new `onDecision` prop and rendered
  verbatim (`DecisionSummary`, its own `decision-summary*` test ids, so the War Room keeps the only
  `decision-headline`). The verdict bar shows the same headline word only while the answer is for the trade on screen.
- **Desktop (>= 1024 px).** Two columns (3fr / 2fr). The right column (result, decision echo, then the fairness
  explanation and the independent tally) is sticky with its own scroll. Side cards stack in the left column: two
  370 px cards side by side truncated every row's metadata at 1366. The bottom tray is hidden there.
- **Below 1024 px.** One column in layer order; a sticky section nav (44 px targets); the verdict bar links to the
  decision. The quick-add bar is no longer sticky (it overlapped scrolled content, UX audit P2-4).
- **Every feature stays reachable**, and every test id the e2e specs use is unchanged.

Measured on the local real stack (Playwright, Chromium, the seeded board, analyze mocked from the real fixtures):

| measure | before (TC-B head) | after (D1) |
|---|---|---|
| decision on screen at 1366x900 | War Room headline y=877; meter y=1,917 | decision echo y=639; meter y=375 |
| fixed chrome at 390x844 | 235 px (top bar 46 + quick-add 62 + tray 74 + tab bar 53) | 219 px (top bar 46 + section nav 46 + tray 74 + tab bar 53) |
| horizontal scroll at 390 / 360 / 1024 / 1366 / 1920 | none at 390 / 1366 | none at any of the five |

Before/after screenshots were taken at 1366x900 and 390x844 (after also at 360x780, 1024x768 and 1920x1080). They
are session artifacts, not committed.

### Gates run on the TC-D head (2026-10-18)

- Real-stack Playwright, desktop-1366 + mobile-chromium: `trade-war-room`, `trade-next-actions`, `trade-ktc-import`,
  `trade-screenshot-import`, `mobile-trade-quantity`, `mobile-pinned-overlap` and `journey-trade`. Result: 26 passed,
  7 skipped (gated to the other project by the specs themselves), 1 failed. The failure was
  `journey-trade` "/arbitrage scans" (90 s predicate timeout under the parallel run). `/arbitrage` is not touched
  here, and the same test passed alone in 21 s.
- Full vitest: 4150 / 4151. The one failure was `game-day-panel.test.jsx` (a 5 s test timeout under suite load; not
  touched; 64 / 64 alone). The new `trade-tcd-layout.test.jsx` has 21 tests. The de-flaked
  `trade-on-demand-sections-render` uses a shared prewarm (`__tests__/setup/trade-lazy-sections.js`, the #1792
  pattern); its assertions are unchanged.
- `build:nocheck` + `check:bundles`: every page is under budget, `/trade` 77.9 KB of 93 KB.

### Remaining in TC-D (D2 and later)

- Builder bottom sheets on mobile (one search per side).
- The toolbar overflow menu (CSV / JSON / Copy KTC URL).
- Supporting-intelligence drilldown tabs (Value · Roster · Season · Market · Reasoning).
- One roster-consequence surface (TCM-H13: Simulate impact folded under the decision).
- A persistent summary for 3+-team trades.
- The Monte Carlo "favored" relabel (§7.8).
- The withdrawn "My league" control (TCM-D09).
- A wider cap at 1920 (shell-level).
- The screenshot FAB still sits over the bottom-right of the sticky column on desktop; it is the pre-existing UX audit
  §2.1 row 18, and the FAB is shell-owned.

*Superseded by "TC-B2 / TC-D2 notes" below*: every item above shipped in D2 except the 1920 cap and the FAB.

## TC-B2 / TC-D2 notes (2026-10-18)

Branch `claude/trade-calculator-tc-b2-d2`, **stacked on release train 8** (`integration/train-8-2026-10-18`, #1809,
carrying TC-B1 #1800 and TC-D1 #1805). Agent-OS-Receipt: `cdca1dca8385f70c0989302dece8d1bd4ce4843c`. Not merged, not
deployed, not observed in production.

### Owner decisions folded in — DECIDED (owner closeout 2026-10-18, binding)

- **Decision 9 (TCM-K06), DECIDED.** An external opinion excluded for freshness, access, identity or any other evidence
  reason reads **"Unavailable — <actual reason>"**: never EVEN, never our canonical value as its vote, never a canonical
  fallback counted as a second opinion, never 0, never hidden; the independent tally equals the independent opinions
  shown. Implemented in the Second Opinions owners: `lib/second-opinions.js` (`OPINION_ORIGIN.UNAVAILABLE`,
  `OPINION_STATE.UNAVAILABLE`, the backend's own `excludedReason` / `supersededBy` / row `freshnessExcludedSources`;
  the retired `STALE_OR_HELD` fallback used our value in the source's place), `tallyOpinions` (`counts.unavailable`,
  `unavailableFamilies`), `lib/second-opinions-rows.js` (coverage words), `TradeSourceBreakdown` (the row, "—" totals,
  the unavailable count). Tests: `second-opinions-unavailable.test.jsx`, `second-opinions-hybrid.test.jsx` §9.
  On the seeded contract, preflight already reports withheld votes (`fantasyNavigatorSf` on 448 rows,
  `idpShowCombined` on 656), so this state is live, not hypothetical.
- **Decision 10, DECIDED.** Priority order (evidence states → redesign → reliability → matrix gaps → verification)
  followed here. **The share-link format stays frozen**: no URL change ships (an earlier draft of this batch added a
  player-id field and `from=history` query parameters; both were reverted before commit). **3+-team trades** get a
  YES / NO only when the engine can identify the user's side and account for every side, which today means two-team
  trades; the War Room banner, the decision echo, the Reasoning tab and the persistent summary now say a reliable
  YES / NO is unavailable. One package-value owner and one decision owner, unchanged.
- Unchanged: `geom_q078_v1` (q 0.78), the 250-point Best Offers rule, the fairness bands. DFS untouched.

### TC-D2 — what shipped

| item | how (owners unchanged) |
|---|---|
| Builder bottom sheets on phones | `app/trade/trade-asset-sheet.jsx` (React.lazy, rendered only after a tap): the ds `Drawer` re-anchored to the bottom edge through its documented `className` override; one search per side (the page's `searchAssets`), stays open between adds and names each add, rows pick on a completed tap so a scroll gesture adds nothing. Below 768 px each side card shows a 44 px "Add to Side X" button instead of the inline dropdown; the quick-add bar is removed (the sheet replaces it). Desktop keeps the inline search. |
| Toolbar overflow | CSV / JSON / Copy KTC URL sit in a "More" disclosure (same pattern as Import trade; Escape closes it). Toolbar buttons are 44 px on phones. |
| Supporting-intelligence drilldowns | `TradeIntelTabs` (ds `Tabs`, roving tabindex): **Value** (package breakdown, multi-team flow, Second opinions folded), **Roster** (Simulate impact), **Season** (ROS fit), **Market** (Recent real trades), **Reasoning** (the decision's coverage + what would change it). Only the open tab is rendered, so a closed tab's chunk and request never load (the contract the folded panels had). Tabs are 44 px on phones. |
| One roster-consequence surface (TCM-H13) | Simulate impact left the toolbar for the Roster tab, beside a pointer to the War Room's roster answer (the one that counts toward the decision). |
| Persistent 3+-team summary | `MultiTeamSummaryBar` in the tray slot: each side's net flow and the band of the worst gap, from `multiTeamNetSummary` (new, `lib/trade-logic.js`), which the multi-team meter now also reads — one helper, so the two cannot drift. Links to the result; states that a reliable YES / NO is unavailable. |
| Monte Carlo relabel (§7.8) | On /trade (`sidesSend`) the result is headed "Value-sensitivity check": no winner / favored / clearly / probably, neutral tone, "Side A's package came out bigger in N% of M simulations"; the button reads "Simulate value sensitivity". /waivers keeps its own wording. |
| "My league" control (TCM-D09) | Removed; the contract-gated `ValueBasisNote` replaces the inline banner (renders nothing on the market board). |
| Reasoning | `components/trade/TradeDecisionReasoning.jsx` (React.lazy): `decision.whatWouldChange` and `decision.coverage` (all ten dimensions: coverage state, evidence kind, role, freshness, the exclusion / approximation reason), verbatim from the War Room's own answer (`onDecision`). The War Room rendered neither. |

Not shipped, named: **the 1920 cap** needs a wide-shell value — no token exists and `--shell-max` (1320) is shell-wide,
so it is an **OWNER UI DECISION** (UI contract §2: a genuinely new visual decision); **the desktop FAB overlap** is
shell-owned (UX audit §2.1 row 18) and belongs to the shell lane.

### TC-B2 — rows

| row | done here | left, and the exact reason |
|---|---|---|
| K06 | decision 9, above | — |
| M01 / M02 / M04 / M05 | `TradePackageBreakdown` (Value tab) over `lib/trade-package-facts.js`: stacked raw-value bars per side on one scale with VA as its own hatched segment, every number in the legend; one marker number per line + the fixed chart series (first six; a neutral "other" series after, never colour alone); Quick Trade Facts (raw priced value, pieces, players · picks, average piece value, average player age, average backend-stamped consensus rank, not priced; every average names its coverage, a missing value is never averaged as 0); concentration as the largest piece's share and the inverse Herfindahl "behaves like N equal pieces", with no threshold and no better/worse reading. Supersedes the two-bar value split chart (TCM-K15; component deleted). | M04's Chase Upside-specific facts (confidence, starter impact, scarcity, fit, liquidity) are optional in TC-14 and not added |
| N03 | Banner: "Opened from Trade History — today's view, not a replay", with the trade date. No URL change: `/trades` records a same-tab sessionStorage hand-off keyed to the exact share payload (`lib/trade-history-origin.js`); a link opened any other way shows nothing. | the as-of replay itself (dependency-gated, spec §2–§9) |
| C04 | Restore half: names that no longer resolve are listed in the load notice, never dropped silently. | per-asset degrade on an unknown schema version — waits for the coordinated compatibility migration (decision 10) |
| A05 | — | stable player ids change the share format; frozen by decision 10 until a compatibility migration is tested |
| G18 | A calculator save names the served decision's run id; `trade_desk.new_item` attaches the server's OWN logged record (`trade_decision_log.find_decision_run`, headline words from the decision owner) or states why not; the desk shows "War Room answer when saved …, not refreshed". Never a client-typed verdict, never a status. | — |
| H03 | — | Trade Finder lane (generator ranking), not this calculator lane |
| H12 | — | replacement level needs the waiver-pool projection join in `best_ball_utility` (an engineering dependency, not an owner decision) |
| B04 | — | C1-U7 owned-pick distributions (separate owner) |
| M03 / M06 | — | need a private `src/history` read endpoint for trade assets plus a chart (a backend unit; methodology is in spec TC-13 / TC-16) |
| M07 | — | the existing movers owner (rankings / terminal) has no 30-day horizon; needs a ledger-backed movers read |
| F05 | — | "pick context" has no destination page: **owner decision needed** — which surface a pick links to (Rankings filtered to picks, the draft-capital tab, or a pick profile that does not exist) |
| R01 | — | **owner decision needed** — what to announce and where (site-wide shell vs /trade); a mechanism with no content renders nothing |

### Bundle

`/trade` 77.9 → 82.2 KB of 93 KB (10.8 KB headroom); every new panel is `React.lazy` (`dyn`, never `next/dynamic`).
`/league` 49.8 KB before and after (the train head is already at 49.8; this batch adds nothing to it). `/trades`
23.6 → 25.0 KB of 26; `/arbitrage` 76.0 → 77.3 KB of 82.

### Gates run on the TC-B2/D2 head (2026-10-18)

- `format_python_changes.sh`: GREEN (Ruff 0.6.9). `check_decision_coercions.py`: "clean: no new coercions, no stale
  allowances in the files this change touches." (one new `|| 0` in `multiTeamNetSummary` was caught on the first
  commit and fixed: an unknown net stays unknown). `check_planning_integrity.py` and
  `check_product_plan_governance.py`: clean.
- `pytest tests/trade tests/api/test_trade_desk_endpoint.py`: 2098 passed (48 subtests).
- Full `npx vitest run __tests__`: 4274 / 4275. The one failure was `game-day-panel.test.jsx` (load-sensitive, not
  touched; 64 / 64 alone), the same test D1 recorded.
- `build:nocheck` + `check:bundles`: all 17 budgeted pages under budget — `/trade` 82.2 KB of 93, `/arbitrage` 77.3 of
  82, `/league` 49.8 of 50 (unchanged from the train head), `/trades` 25.0 of 26.
- Real-stack Playwright (seeded snapshot, Chromium, desktop-1366 + mobile-chromium): `trade-tcd2` (new),
  `trade-war-room`, `trade-next-actions`, `mobile-trade-quantity`, `trade-screenshot-import`, `trade-ktc-import`,
  `mobile-pinned-overlap`, `journey-trade` — 29 passed, 7 skipped (gated to the other project by the specs
  themselves), 0 failed. The specs add assets through one helper (`tests/e2e/helpers/trade-builder.js`) that drives
  the inline search on desktop and the bottom sheet on phones; the production-auth specs that add assets or press
  Simulate impact were moved onto it too (not run here: they target production).
- Before/after screenshots at 1440x900 and 375x812, plus measurements, in `docs/trade/tc-d2-2026-10-18/`
  (before = the train head, after = this branch, same trade). Found and fixed while capturing: at 375 px a 3-team
  trade's routed rows clipped the player name to nothing (the destination select took the row; UI contract §6) and a
  balancer line pushed the page 48 px sideways; both now wrap. The Second Opinions shots show two real sources
  (`idpShowCombined`, `fantasyNavigatorSf`) reading "Unavailable — stale or unhealthy source, excluded from our
  blend" on the seeded board, where they used to be scored with our values.

## Coordination with in-flight work

| In-flight | Overlap | Rule |
|---|---|---|
| #1771 GEOM activation | `trade-logic.js`, `analyze_trade.py`, War Room, help copy | TC-A/C/D code starts on top of #1771 after it merges; TC-0 is read-only |
| #1772 availability | `best_ball_utility`, `roster_capacity`, `analyze_trade.py`, War Room | TC-C consumes it after merge; no edits to those files before then |
| #1774 / #1775 | playoff sim, Game Day | consumed, not edited |
| Manager Intelligence B1/B2 | `/managers`, `manager_intel_api` | TC-B partner links consume its endpoint |
| Second Opinions (VA PR2, merged) | `second-opinions.js`, `TradeSourceBreakdown` | TC-B extends it, no second implementation |

## Status

| Batch | State |
|---|---|
| TC-0 audit + research | DONE — feature matrix, competitive analysis, UX audit, decision-engine audit committed (docs PR) |
| TC-A correctness | IMPLEMENTATION HEAD GREEN on local branch `claude/trade-calculator-tc-a` (local commits on `integration/train-5-2026-10-17` @ `ea054f386a`; not pushed, no PR). RELEASE CANDIDATE: NOT YET FROZEN. Not merged, not deployed, not observed in production. Simulations consuming availability (#1772 follow-through) is not part of this batch. See "TC-A notes" |
| TC-C decision engine | IMPLEMENTATION HEAD on local branch `claude/trade-calculator-tc-c`, stacked on TC-A (not pushed, no PR). RELEASE CANDIDATE: NOT YET FROZEN. Not merged, not deployed, not observed in production. See "TC-C notes" |
| TC-B missing functionality | TC-B1 IMPLEMENTATION HEAD on `claude/trade-calculator-tc-b` (`2bd2986ddd`, `8625ab7b77`, PR to main): of the 31 inventoried rows, 12 moved to IMPLEMENTED BUT UNVERIFIED (A02, A03, D14, F03, G09, I04, K03, K13, L05, O11, O12, O13) and 4 advanced but kept their class (B04, G18, H12 partial; L01 gained its database link); the other 15 are listed under "Remaining in TC-B". RELEASE CANDIDATE: NOT YET FROZEN. Not merged, not deployed, not observed in production. See "TC-B notes" |
| TC-B2 / TC-D2 | IMPLEMENTATION HEAD on `claude/trade-calculator-tc-b2-d2`, PR stacked on release train 8 (#1809). Owner decisions 9 (K06) and 10 DECIDED (closeout 2026-10-18) and folded in. To IMPLEMENTED BUT UNVERIFIED: K06, D09, H13, P03, M01, M02, M04, M05, N03 (banner), G18; K15 superseded by M01. RELEASE CANDIDATE: NOT YET FROZEN. Not merged, not deployed, not observed in production. Open: the 1920 cap (owner UI decision), the FAB (shell lane), A05 / C04 unknown-version (share format frozen), F05 / R01 (owner decisions), M03 / M06 / M07, H03, H12, B04. See "TC-B2 / TC-D2 notes" |
| TC-D redesign | D1 IMPLEMENTATION HEAD on `claude/trade-calculator-tc-d` (`ecbde07821`), stacked on TC-B1 (#1800): War Room code split (`/trade` 91.7 → 77.9 KB of 93 KB) and the five-layer layout, with a desktop sticky result + decision echo and a mobile section nav + verdict bar. TCM-P01 / P02 moved to IMPLEMENTED BUT UNVERIFIED; P03, P05, Q03, F06, H13 and K03 advanced. RELEASE CANDIDATE: NOT YET FROZEN. Not merged, not deployed, not observed in production. D2 remains (see "TC-D notes") |
| TC-E … TC-F | QUEUED, in order; each starts as its dependencies land |
