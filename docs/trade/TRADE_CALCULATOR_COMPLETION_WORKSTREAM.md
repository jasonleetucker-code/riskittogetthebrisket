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
| TC-A … TC-F | QUEUED, in order; each starts as its dependencies land |
