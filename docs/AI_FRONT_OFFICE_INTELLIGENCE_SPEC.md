# AI Front Office Intelligence — Approved High-Value Feature Family

**Status:** CANONICAL DETAILED PRODUCT SPEC SUPPLEMENT  
**Owner direction captured:** 2026-08-12  
**Execution posture:** APPROVED FUTURE PRODUCT WORK; DOES NOT INTERRUPT CURRENT FOUNDATION SEQUENCE  
**Public/private posture:** PRIVATE DECISION INTELLIGENCE unless a separately approved public-safe derivative is defined.

## 1. Approved feature set

The owner explicitly approved these six features from the August 12, 2026 ideation pass:

1. **Ask Brisket**
2. **Roster Path Optimizer**
3. **Edge Alerts**
4. **Trade Liquidity & Market Depth**
5. **Negotiation Coach**
6. **League Truth**

These are not six independent data/model stacks. They are product surfaces that consume canonical systems.

## 2. Ask Brisket

Natural-language front-office interface over the site's real canonical data and models. It should answer league-specific questions such as what moves matter, why a recommendation exists, what a trade changes, who may be a realistic buyer, and what risks or alternatives exist.

The LLM should not recalculate canonical values, playoff odds, trade comps, Team Strength, Pick Forecast, Manager Scout, or other established quantities from raw data. A structured retrieval/orchestration layer should assemble the relevant canonical evidence, then the language model reasons over and explains that evidence.

Required properties:

- grounded in the selected league/team;
- explicit provenance and freshness for material evidence;
- explainable answers;
- missing data remains missing;
- no silent league mutation;
- cost-aware model routing/caching so expensive inference is optional and controllable;
- recommendation and execution stay separate;
- private intelligence never leaks into public league surfaces.

## 3. Roster Path Optimizer

Optimize sequences of actions rather than isolated one-trade decisions. A path may contain trades, waivers, lineup/roster moves, pick conversions, or other approved actions and should optimize toward an explicit objective such as championship probability, rebuild asset value, balanced future/current strength, or a user-selected constraint set.

It must consume the same canonical package generator, Trade Analyzer, Team Strength/Weakness, Pick Forecast, Playoff Predictor, market comps, waiver model and Manager Scout rather than building replacements.

Outputs should show the proposed sequence, before/after roster state, expected objective improvement, constraints consumed, uncertainty and why the path beats simpler alternatives. Do not present combinatorial-search output as certainty.

## 4. Edge Alerts

A high-signal event-to-opportunity layer. It should detect meaningful changes that create a possible user action, e.g. a league-mate injury creating demand, a projected pick moving materially, a market price diverging from fundamentals, a Sharp accumulation event, a liquidity spike, or a championship-odds shift changing contender strategy.

Alerts must have:

- a materiality threshold;
- a defined trigger and canonical source;
- deduplication/cooldown;
- freshness;
- explanation of why the change may matter;
- actionability, not generic news spam;
- user-configurable watchlists/thresholds later where useful.

A signal descendant cannot be counted twice simply because it appears as both an alert and its underlying source.

## 5. Trade Liquidity & Market Depth

Model how easy an asset is to transact at a defensible price, separate from its canonical dynasty value.

Potential components include:

- recent real-trade volume in comparable formats;
- number and quality of comparable transactions;
- bid/ask-equivalent dispersion inferred from trade comps where defensible;
- number of plausible buyers in the selected league based on roster need and Manager Scout;
- package compatibility / common transaction shapes;
- time since last comparable trade;
- market concentration and uncertainty.

Liquidity is informational/advisory. A 6,000-value liquid asset and a 6,000-value illiquid asset remain 6,000 canonical value unless a separately validated market-value model says otherwise.

The broad-market transaction input for this feature is the canonical CE-01 Market Trade Ledger described in `docs/MARKET_TRADE_LEDGER_ACTIONABILITY_SPEC.md`; do not create another recent-trades store inside Liquidity.

## 6. Negotiation Coach

Help turn a desirable trade into a realistic offer/counter strategy. It may use canonical value, package economics, Market Trade Ledger comps, Trade Liquidity, selected counterparty roster needs, Manager Scout and historical Insider Trading behavior.

Potential output:

- opening offer;
- target/fair package;
- maximum defensible concession;
- walk-away point;
- likely counter structures;
- which asset types the counterparty historically prefers;
- explanation of which evidence is factual market behavior versus inferred negotiation strategy.

Do not perform real-world personal profiling. This is fantasy-manager behavior within the connected fantasy-league context. Do not automatically send offers.

## 7. League Truth

A public-safe/privately richer standings-quality layer that distinguishes record from underlying performance.

Potential metrics:

- official record;
- head-to-head record;
- league-median record where enabled;
- all-play record;
- expected wins;
- schedule strength/luck;
- record under every other team's schedule where reconstructable;
- points distribution and consistency;
- close-game outcomes;
- current-season underlying team quality;
- playoff probability context.

The feature should answer questions like "How good is this team really?" without collapsing Team Strength, Power Rankings, Playoff Odds and dynasty asset strength into one number.

Public `/league` may show sports-broadcast-style factual and retrospective League Truth metrics. Private surfaces may add actionable interpretations.

## 8. Shared architecture

These features should reuse, not duplicate:

- canonical player/pick values;
- league settings/scoring;
- Team Strength and Team Weakness;
- replacement/PAR;
- Playoff Predictor / Game Day probability primitives;
- Pick Forecast;
- Market Trade Ledger and comps;
- Manager Scout / Insider Trading;
- Sharp / analyst / news intelligence;
- package generation and trade simulation;
- acquisition history;
- source provenance/confidence.

## 9. AI cost posture

Ask Brisket may require paid model inference when activated. Architecture should make LLM usage optional and efficient: retrieve only the needed structured evidence, cache deterministic/context packages where appropriate, route simple tasks to cheaper models and reserve stronger reasoning for complex synthesis. Building the canonical retrieval/orchestration layer does not itself require activating a paid LLM API.

## 10. Method status

**Ask Brisket:** OWNER-APPROVED FUTURE FEATURE; API/model activation is cost-gated and security/privacy-gated.  
**Roster Path Optimizer:** OWNER-APPROVED FUTURE FEATURE; exact objective/search methodology requires validation.  
**Edge Alerts:** OWNER-APPROVED FUTURE FEATURE; thresholds require evidence and anti-spam design.  
**Trade Liquidity & Market Depth:** OWNER-APPROVED FUTURE FEATURE; exact metric/model evidence-gated.  
**Negotiation Coach:** OWNER-APPROVED FUTURE FEATURE; no automatic execution.  
**League Truth:** OWNER-APPROVED FUTURE FEATURE; underlying metrics must remain distinct and reproducible.
