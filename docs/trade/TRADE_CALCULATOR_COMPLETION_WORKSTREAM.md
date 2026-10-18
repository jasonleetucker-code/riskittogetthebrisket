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
   is always displayed and can always be overridden manually.
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

1. **Strategy** (decision 2): `teamGoal` override, else posture PUSH → WIN_NOW, RETOOL / REBUILD → LONG_TERM, HOLD →
   BALANCED (a no-evidence HOLD is BALANCED and says so); posture unavailable → unknown.
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

### What TC-C does not do

- "What would change it" (perturbation search) is not implemented; `mainCounterargument` is.
- Monte Carlo still shows its own "favored" sentence (relabel planned in TC-D, audit §7.8).
- Historical replay and decision receipts (audit §7.7 / §7.9 items 3–4) are not built.
- Second Opinions dispersion and comparables do not yet lower the agreement axis.
- The fairness bands are provisional: no validation target exists yet to fit them against.

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
| TC-B, TC-D … TC-F | QUEUED, in order; each starts as its dependencies land |
