# Preserved League Tycoon transition ideas — owner decision 2026-10-16

**Status: OWNER-PARKED / IDEAS ONLY; no implementation authorized.**
**Source preservation:** exact owner-research detail recovered from **unmerged GitHub PR #1755**, `docs/BRISKET_IDEAS.md` proposed §15, on 2026-10-30. Its proposed section numbering is retained **as historical section labels**; it is NOT the currently active `docs/BRISKET_IDEAS.md` §15 (which governs agent-ready planning). The research blueprint from merged PR #1764 is a companion; neither authorizes live work.

**Why this exists:** The previously prepared #1755 preservation PR remains open, so its **100-mechanism catalogue and 44 future candidate ideas had not reached `main` through that PR**. This separate source-preserving document prevents detail loss and avoids colliding with newer master-planning sections. Upon integration, reconcile #1755 as superseded/duplicate, never auto-merge both competing edits. Detailed existing `docs/OWNER_REQUESTED_TODO.md` intake points here.

**Hard stop:** Do not move to League Tycoon, build contract-engine code, change valuations/rosters/host, purchase data, alter official rookie auction, or start research/implementation on the owner's behalf unless **later explicitly authorized**. This file captures *historical proposed ideas and research*, not a promise the host can support them.

---

---

## 15. League Tycoon

**Captured:** 2026-10-16 · **Owner decision: PARKED / IDEAS ONLY / LATER / NOT AUTHORIZED.**
**Activation condition: ONLY an explicit future owner instruction that it is time to implement the League Tycoon transition.**
**Current priority:** finish the rest of Calculator first. The League Tycoon migration date is unknown; neither finishing the current app nor this idea record automatically starts League Tycoon development.

**Hard stop:** Do not build, modify app code or schemas, open feature implementation branches, alter valuation/trade/auction behavior, subscribe to paid data, change the real league, migrate to League Tycoon, or launch its production capabilities from this record. Do not add these items to the *current* Calculator-completion denominator, current execution plan or next automatic development batch. A research/idea document is **not implementation authorization**. Future authorization must be a new explicit owner decision and be recorded in `docs/EXECUTION_PLAN.md`.

### 15.1 Mission and bounded scope

Keep League Tycoon as a possible **future league host**, while Risk It to Get the Brisket / Chase Upside becomes its **independent decision-intelligence companion**: salary- and contract-aware values, trade discovery, rookie auctions, extensions/tags/options, cap forecasting, best-ball analysis and commissioner diagnostics. Preserve complete Sleeper support and all existing Calculator work. Avoid duplicating a fantasy hosting platform.

The October 2026 research surveyed the real repository and official [League Tycoon Contract League Rules](https://leaguetycoon.com/rules/contract-league-rules/). Treat that research and the owner's 100-item mechanism reference as **candidate product inputs**, not confirmed final league rules or proof of implementation. Platform rules and export layouts must be reverified on activation.

**Reuse rather than rebuild:** `src/league_intel/values.py` (market/consensus/league value axes), `src/league_intel/replacement.py` (scarcity/replacement), `src/ros/lineup.py` (exact Best Ball lineup assignments), `src/api/trade_simulator.py` / `frontend/lib/trade-logic.js` / existing Best Offers and Package Builder, `frontend/lib/perfect-draft.js`, `src/auction/engine.py` / `src/auction/store.py` (existing mock-ready shared rookie auction room), `src/api/auction_power.py`, `src/api/faab_analytics.py`, `src/api/league_registry.py`, identity/provenance, Model Lab and Manager Scout. Existing code/merged PR does **not** establish full deployed or production-verified readiness.

### 15.2 The complete 100-mechanism feature-reference index

The following indexed inventory preserves every item from the original League Tycoon feature discussion. Individual items may be optional settings, not unique platform features. Their **capability and export details require fresh verification** before implementation.

| Source items | Covered mechanics |
|---|---|
| 1–11 | 1 team salary cap; 2 individual player salaries; 3 available cap room; 4 future salary commitments; 5 future cap enforcement; 6 cap rollover; 7 cap holdback; 8 tradable cap space; 9 commissioner cap adjustments; 10 cap compliance; 11 minimum salaries. |
| 12–24 | 12 one-year; 13 two-year; 14 three-year; 15 four-year; 16 commissioner-enabled five-year contracts; 17 contract allotments by length; 18 annual allotment resets; 19 expiration; 20 remaining contract term as trade asset; 21 contracts transfer in trades; 22 salary escalators; 23 flat annual salaries; 24 Owners Choose initial contract allocation. |
| 25–32 | 25 extensions; 26 annual extension limits; 27 maximum extension length; 28 stable-price extension; 29 performance-based extension; 30 extension multiplier; 31 minimum extension salary; 32 extension eligibility. |
| 33–37 | 33 franchise tags; 34 tag limits; 35 position-based tag prices; 36 top-N salary averaging; 37 tag eligibility/history. |
| 38–42 | 38 RFA tenders; 39 right of first refusal; 40 compensatory picks; 41 configurable tenders/prices; 42 RFA eligibility. |
| 43–52 | 43 Rookie contract designation; 44 rookie salary scale; 45 rookie term; 46 rookie option years; 47 annual option limits; 48 stable-price option; 49 market/PPG-based option; 50 tag-percentage option; 51 configurable percentages; 52 option eligibility. |
| 53–62 | 53 multiple drafts; 54 rookies-only auctions; 55 recurring additional auction configuration; 56 slow auctions; 57 winning bids become host salaries; 58 standard auction Regular contracts; 59 salary-plus-years bidding; 60 player-pool restrictions; 61 automatic ownership/contract recording; 62 post-auction rookie practice-squad eligibility. |
| 63–69 | 63 cap-backed FAAB; 64 waiver winning bid as salary; 65 one-year in-season waiver deal; 66 minimum-salary open pickups; 67 blind bidding; 68 configurable waiver/open pickup rules; 69 expired contracts repriced in open market. |
| 70–75 | 70 current-season release dead money; 71 future-season dead money; 72 configurable percentages; 73 penalty based on remaining years; 74 practice-squad dead money; 75 trade-versus-release decisions. |
| 76–82 | 76 practice-squad contracts; 77 reduced practice-squad cap charge; 78 practice-squad salary increases; 79 developmental eligibility; 80 commissioner eligibility modifications; 81 IR cap percentage; 82 practice-squad release penalties. |
| 83–96 | 83 Sleeper league import; 84 autogenerated conversion salaries; 85 cap preview; 86 conversion holdback effects; 87 holdback post-conversion immutability; 88 Owners Choose conversion; 89 manual contract editing; 90 bulk contract CSV upload; 91 rights eligibility editing; 92 leaguewide Front Office views; 93 detailed contract exports; 94 roster exports; 95 player/stat/projection exports; 96 undo-signing rules. |
| 97–100 | 97 distinct DT/DE/LB/CB/S eligibility; 98 differentiated IDP scoring; 99 format-dependent salary generation; 100 custom offense/IDP/kicking scoring. |

**Coverage evaluation required on activation for every item #1–100:** verified host behavior and limitations; actual current Calculator implementation; missing decision-support opportunity; supporting league data and permitted acquisition method; shared canonical owner/code reuse; validation; value outside this one league; and classification (existing / partial / absent / conditional / impossible / unknown).

### 15.3 Candidate user-facing intelligence tools — original 20

1. **Dynasty GM Dashboard:** Leaguewide and team-specific payroll, value, depth, strategy, annual risk and future flexibility.
2. **Multi-Year Cap Simulator:** Interactive 1–5 year payroll, expirations, planned acquisitions, extensions, tag, IR/PS, rollover and dead-cap scenarios.
3. **Contract Recommendation Engine:** Optimal legal term/length and limited contract-allotment use, accounting for uncertainty.
4. **Extension Decision Engine:** Extend versus tag, trade, release, option, or allow expiration with actual calendar/legal windows.
5. **Franchise Tag Optimizer:** Optimize tag assignments given the positional formula and limited annual tags.
6. **Rookie Option Optimizer:** Compare eligible option decisions and scarce option allotments under each pricing method.
7. **Free Agency Auction Assistant:** Bid discipline, position opportunity costs and roster-safe maximum bids.
8. **Rookie Auction War Room:** Pick-derived dollars, nomination, bidding, roster utility, and host-contract reconciliation.
9. **Dead Money Calculator:** Exact current/next-year costs for a cut vs trade/retention, including practice squad.
10. **Contract Bargain Finder:** Find high expected contract-surplus players without confusing salary with market dynasty value.
11. **Contract Burden Detector:** Find expensive commitments at risk of becoming strategically restrictive.
12. **Cap Relief Trade Finder:** Find both legally feasible partners and economically reasonable salary dumps.
13. **Dynasty Window Analyzer:** Project roster contention and replacement exposure over several seasons.
14. **Leaguewide Financial Power Rankings:** Compare talent, payroll, value surplus, future commitments and flexibility without opaque single-number claims.
15. **Contract Expiration Forecast:** Calendar of free-agent supply and expected roster holes.
16. **Roster Construction Optimizer:** Cap-constrained and roster-legal spending allocations across offense and granular IDP positions.
17. **Rookie-versus-Veteran Value Engine:** Compare development upside versus immediate performance and associated contract economics.
18. **Contract Negotiation Simulator:** Compare only legally available salary/year bid structures and contract possibilities.
19. **What-If Franchise Sandbox:** Non-mutating multi-move scenarios: trades, releases, tags, options, signings and draft awards.
20. **AI General Manager Assistant:** Grounded explanations over canonical evidence, never model-invented values or autonomous transactions.

### 15.4 Additional 24 researched concepts — preserve even if later rejected

21. **Contract Slot Shadow Price:** Value the scarce right to issue a multi-year deal, tag, extension or option instead of assigning it to the next eligible player.
22. **Rollover Timing Arbitrage:** Compare legal before/after-rollover actions and deadlines, salary carryover and lump-sum penalties.
23. **Franchise Fiscal Cliff:** Detect seasons where several core players expire together or cap availability collapses.
24. **Cap-Room Term Structure:** Show year-by-year opportunity cost of cap space without assuming every future-year dollar is tradeable.
25. **Salary Release Break-Even:** Find the relative trade return/expected points that make trade, cut and retain preferable.
26. **Contract Risk Budget:** Expose salary concentrated in aging, injury-sensitive, volatile or correlated players.
27. **Option Exercise Frontier:** Compare whole sets of rookie-option exercises under a limited allotment.
28. **Practice Squad Activation Cost:** Price permanent eligibility consequences and changing cap charge when promoting a prospect.
29. **Contract Data Diff Ledger:** Explain every change between trusted CSV snapshots, including unresolved identity/contract differences.
30. **Salary Scoring Sensitivity Map:** Test how scoring or lineup rules change conversion fairness and positional pay.
31. **Commissioner Conversion Equity Monitor:** Flag large differences in inherited contracts and salary scale after adjusting for league settings.
32. **Contract Expiry Replacement Funnel:** Forecast positions needing replacement as contracts run out.
33. **FA Auction Bid Discipline:** Preserve minimum-roster cap room and holdbacks when recommending a series of bids.
34. **RFA Eligibility Gatekeeper:** Validate required tender rights, compensation picks and ability to match; defer while RFA is off.
35. **Auction Salary Bridge Reconciliation:** Match our rookie-room awards against host player ownership, salary and contract type.
36. **Contract Replacement Salary Curve:** Experimentally estimate market price of positional replacement using actual historical contracts.
37. **Offer Eligibility Feasibility Score:** Tell whether a seemingly fair multi-asset trade would actually be cap/roster compliant.
38. **Counterparty Cap Urgency Index:** Find franchises needing cap relief or facing immediate contract decisions.
39. **Dynasty Plan Robustness Test:** Stress-test plans against injuries, salary increases, changed market prices and missed rookie targets.
40. **Salary-to-Performance Realization Ledger:** Track ex-ante cost and forecast versus realized value without look-ahead bias.
41. **Financial Move Replay:** Reconstruct what was known when an earlier cut, extension or trade was decided.
42. **Cap Utilization Efficient Frontier:** Compare quality of roster plans across cap usage and title probability, not one brittle scalar.
43. **Rookie Pick Economic Attribution:** Break picks into pick rights, independent rookie-auction currency, salary and eligibility implications.
44. **Contract Identity Confidence Meter:** Block unsupported financial advice when player, salary, team or Rookie/Regular contract type is uncertain.

The 44 product concepts above are **ideas to evaluate**, not 44 independent engineering systems. Several deliberately share a common contract ledger, salary engine, market model, trade/roster model or auction engine. Explicitly reject duplicates, unsupported automation, uncalibrated AI predictions and fragile cross-provider assumptions when implementation is finally considered.

### 15.5 Contract economics and valuation specifications to revisit

Keep **eight distinct outputs** where reliable: (1) pure dynasty market value; (2) contract-adjusted dynasty value; (3) multi-year contract surplus versus realistically obtainable alternatives; (4) marginal production/expected wins per cap dollar; (5) discounted future contract/roster value; (6) cap flexibility/liquidity; (7) calibrated injury/age/volatility risk; and (8) contract-aware trade-market value. Existing `marketValue`, `consensusValue`, and `leagueAdjusted` remain separate.

Research appropriate alternatives: points/wins over replacement, endogenous lineup slot demand, positional scarcity (especially SFLEX/TE/DT/DE/LB/CB/S), expected future salary opportunity cost, salary-price comparables, optional discounted scenario surplus, Monte Carlo, contract allotment shadow prices, and cap-constrained roster optimization. Never derive host extension/option salary merely from our proprietary dynasty value. Prefer interpretable, point-in-time validated methods; unknown player/host data stays unknown, never zero.

Enhance **existing trade calculators and generators**, not a duplicate calculator: show year 1–5 salary and cap deltas, legal offer feasibility for both parties, transfer of contract obligations, positional and starting-lineup effects, contract expiration/option/tag eligibility, roster slot capacity, tradeable cap assets where legal, salary relief, bad-contract dumps, rebuilding/contending horizons, projected title equity (if calibrated), actual comparable trades and counterparty fit. Distinguish a trade's canonical asset equity from its financial/roster utility.

**Contract rules requiring exact host validation:** after-Week-17/pre-rollover tag and RFA windows; post-rollover/pre-kickoff contract assignment/extension/rookie option windows; position-based tag pricing and stable floors; adjusted recent-PPG and positional-salary-snapshot rules for performance pricing; annual and future salary increases; cap holdback/rollover; trades transferring contracts without seller release penalties; default future release dead money charged as a next-season lump sum; relevant practice-squad promotion eligibility. Confirm the current rules each season.

### 15.6 Rookie-auction/cap economics — three different ledgers

The existing league's rookie draft uses an **independent $1,200 total, pick-derived buying-power pool**, allocated by actual owned picks, not each manager's annual salary cap. Track separately:

1. **Rookie-auction purchasing power** (original pick-derived dollars, transfers, reservations, bids, expenditures).
2. **Actual League Tycoon salary/cap commitments** for players acquired, imported/reconciled from the host.
3. **Estimated football/market value** of rookies, picks and their long-run roster utility.

Do not interpret winning $135 of *our* rookie auction currency as necessarily signing a $135 host salary. Investigate a legal reconciliation workflow between our existing mock-first auction and subsequent League Tycoon commissioner entry, including award matching, salary designation, eligibility disputes, contract exports, purchase caps and budget audits. Reuse `src/auction/*` and Perfect Draft; do not reopen its owner-only **official launch** gate merely because this future plan is captured.

**Rookie options blocker:** a rookie obtained through a supplemental/rookies-only auction may receive a Regular rather than Rookie contract. Whether League Tycoon can manually convert this classification, including all option rights, requires **written support confirmation** before a transition; do not model the conversion as supported by default. Keep RFA off unless explicitly enabled later.

### 15.7 Multi-provider data model, imports and confidence

League Tycoon has **no verified public integration API** for our needs. Plan for authorized official CSV exports, roster and contract uploads, explicit verified manual inputs and optional verified screenshot/identity extraction. Never assume private APIs, unauthorized scraping, remote host writes, unattended transfers or invisible auto-synchronization.

Provider-neutral records should preserve: internal league and season IDs; provider association; normalized owner/team/player identities; per-year salary versus cap hit; contract type, length, start/end and status; extension/tag/RFA/rookie-option rights; future dead money; rollover/holdback/cap adjustments; draft picks; **separate rookie-currency budget**; practice squad/IR and eligibility; auctions; transaction dates; detailed scoring/lineup rules; source/version/timestamp/quality; and immutable import history.

Detect missing/duplicate/mismatched player IDs, wrong teams, incomplete CSVs, conflicting contracts, missing picks, stale data, invalid eligibility, cap mismatches and undetermined provider rules. Show preview → review → resolve → commit a versioned read-only snapshot and give explicit confidence flags; never silently overwrite current Sleeper context.

### 15.8 Best Ball, scoring parity and migration blockers

**Best Ball is essential to the owner's preferred league.** League Tycoon Contract Dynasty did not provide the desired native Best Ball weekly lineup scoring in the October 2026 review. The existing exact optimizer can support independent theoretical/commissioner-reviewed optimal lineups, scoring comparisons, exports and roster-building intelligence; it **cannot make the host award official Best Ball results** without an actual supported league process. Do not misrepresent external scoring as native hosting support; treat this as an explicit go/no-go decision before moving the league.

Do not trust a scoring-profile name: at research time the current registry had 12 teams, 58 roster spots, Best Ball, two TE starters, 2 FLEX, SFLEX and aggregate DL/LB/DB IDP slots, whereas proposed League Tycoon rules add distinct DT/DE/LB/CB/S and possibly a further FLEX. Historical 2026 league intelligence also reported removal of the TE reception premium despite a legacy profile label. Compare **actual scoring snapshots, precise positional eligibility, raw stats and lineup rules** before any player salaries, scarcity or conversion fairness models are trusted.

### 15.9 Proposed configuration — NOT a binding rule change

| Possible setting | Preliminary figure |
|---|---|
| Base team cap / minimum salary / annual raise | $2,000 / $1 / 0% |
| Standard Rookie contract | 3 years |
| Performance-based extension | 85% of host-calculated market salary, subject to exact host floors |
| Rookie option | 70% host market salary **or** 50% franchise-tag salary; alternative scenarios, not simultaneous rules |
| Franchise tag | Positional top-8 average, subject to host minimum/stable floor |
| Ordinary release dead money | 100% current-season; 25% per remaining contract year applied as one following-season sum if confirmed |
| RFA | Initially OFF |
| Rookie draft | Separate rookies-only auction, subject to contract classification confirmation |
| Independent rookie auction budget | $1,200 aggregate pick-derived currency, **not host salary cap** |

All values are configurable hypotheses; owner must confirm final league rules in the future. Host exact deadlines/formulas take precedence over approximate descriptions.

### 15.10 Commissioner toolkit, UI and evidence

Consider a dedicated **Front Office** area, not dozens of disconnected navigation entries: GM overview, Contract Lab (player rights and value), year-by-year Cap Simulator, Leaguewide Market, existing Trade and Rookie Auction screens with financial lenses, and Commissioner Lab. Preserve Premium Sports Intelligence Direction A, cream/dark/rust palette, thin rules, tabular numerals, minimal radii, dense legible tables and mobile parity.

Commissioner-specific analyses: Sleeper → League Tycoon conversion readiness; scoring/salary parity; inherited-contract fairness; payroll/roster compliance; rule-change impacts (cap, holdback, dead money, salary escalators, positions); accurate contract export/reconciliation; draft-currency transfers; expiry deadline calendars; and audit trail. Analyses never mutate actual league rules or transactions.

Use the existing Model Lab/evidence framework, with **shadow-only** market-salary models, historical auction-price learning, offer acceptance tendencies and contract-return calibration until samples, permissions and out-of-sample tests support promotion. No fictional bid history, unsupported confidence or unapproved automation.

### 15.11 Research-based priority backlog (all deferred)

These are *provisional research ranks* from October 16, 2026, not measured ROI or immediate batch priority; revisit on activation and re-rank with current code, data and host behavior.

1. Contract identity confidence meter
2. League Tycoon contract importer & reconciler
3. League scoring and positional parity audit
4. Rookie currency / host salary two-ledger bridge
5. Financial trade feasibility engine
6. Auction host-contract reconciliation
7. Trade offer eligibility score
8. Contract-aware trade calculator lens
9. Commissioner salary conversion equity
10. Pick economic attribution
11. Exact cap/dead-money rules kernel
12. Five-year cap planning sandbox
13. Read-only Front Office salary table
14. Commissioner conversion fairness monitor
15. Contract windows/calendar planner
16. Practice squad activation cost
17. Contract import diff ledger
18. Rookie auction live cap-constrained frontier
19. Salary distressed-trade finder
20. Rollover timing arbitrage
21. Franchise fiscal cliff predictor
22. Dynasty Front Office overview
23. Extension/tag/rookie-option adviser
24. Contract value / surplus engine
25. Salary-performance realization receipts
26. Salary-scoring sensitivity map
27. Contract expiry replacement funnel
28. Salary release break-even
29. Contract allotment shadow price
30. Contract expiration market forecast
31. FA auction bid discipline
32. Option exercise frontier
33. Cap room term structure
34. Cap utility efficient frontier
35. Counterparty cap urgency index
36. Historic contract-decision replay
37. Dynasty plan stress test
38. Contract replacement salary curve
39. Contract risk budget
40. RFA offer gatekeeper
41. External Best Ball weekly award sync — **DEFER / external dependency**
42. Manager bidding prediction — **DEFER / external dependency**
43. Automatic supplemental Rookie-type conversion — **DEFER / external dependency**
44. Host automated transaction execution — **DEFER / external dependency**

**Prioritization criteria:** usefulness; incremental value over League Tycoon and Calculator; usage frequency; competitive differentiation; technical feasibility; data availability; reuse; implementation and maintenance burden; expected reliability; this league's custom scoring; support for other leagues; and independence from unavailable integrations. Use weighted scores **only as planning judgments** and let prerequisites override ranks. Do not revive RFA, host transaction execution, automatic Rookie conversion, manager-bid prediction or host-side Best Ball synchronization until supporting evidence and explicit approval exist.

### 15.12 Future-only staged roadmap — does not enter current queue

0. **On explicit owner transition authorization only:** re-audit main/production, code, existing claims, permissions, official host docs, export examples, actual scoring and formal migration readiness. Ask only unresolved questions.
1. **Data foundation:** provider-neutral, immutable League Tycoon contract/roster CSV snapshots; identity and contract-type confidence; salary/ownership reconciliation; no effect on Sleeper.
2. **Exact financial rules:** unit-tested season-specific cap, holdbacks, rollover, deadlines, dead money, PS/IR, and transfers; read-only what-if model.
3. **Valuation and trading:** separate contract value from market, calibrated surplus and financial trade feasibility; extend existing trade engines.
4. **Front Office:** multi-year cap views, extension/tag/options, contract allocation, legal release choices, commissioner conversion fairness, responsive UI.
5. **Auction and free agency:** existing rookie-room award reconciliation, separate currency and host salary, cap-aware Perfect Draft, FAAB-to-salary pricing and waivers.
6. **Learning:** historical receipts, market-salary forecasting, calibrated Manager Scout, scenario robustness and grounded AI explanation (no autonomous actions).
7. **Host-migration gate:** native Best Ball availability or explicitly acceptable manual arrangement; confirmed rookie option classification, scoring parity, roster limits, owners' decision and rehearsal.

**Candidate first future implementation batch, not permission to execute:** LT-01, read-only Contract Snapshot Import + Identity Reconciliation + salary/cap provenance. Inspect `src/api/league_registry.py`, `src/identity/`, `src/api/data_contract.py`, `src/auction/sources.py`, feature-flag conventions, private persistence and canonical tests. Require real CSV samples, a reviewed schema, parse/identity/duplicate/conflict/cap tests, private preview/review UX and absolute regression protection for Sleeper/trade/auction. No host mutations, real money, official auction launch or production activation.

### 15.13 Explicit owner reactivation phrase and preservation rules

**Owner instruction, 2026-10-16 (controlling):** “I don't know when we're moving to League Tycoon, and I would like to finish out the rest of the app. But just have it in the ideas. That way whenever I tell you it's time to implement the League Tycoon transition, we can start implementing these ideas.”

Treat `League Tycoon` as a **deferred idea family** only, outside today's implementation scope. It may be researched or re-ranked on explicit request, but never autonomously promoted because another milestone, app-completion percentage, date or dependency changes. When the owner later expressly authorizes transition, use this record to start a fresh technical audit and confirm contract rules, not to execute an old prompt unexamined.

**Evidence for future re-audit:** `docs/auction/ROOKIE_AUCTION_ROOM.md`, `docs/OWNER_FEATURE_ADDENDUM_2026-09-13_LIVE_ROOKIE_AUCTION_PERFECT_DRAFT.md`, `docs/league-intelligence/STATUS.md`, `src/league_intel/values.py`, `src/ros/lineup.py`, `src/auction/*`, `src/api/trade_simulator.py`, `docs/AI_FRONT_OFFICE_INTELLIGENCE_SPEC.md`, recent merged trade-discovery PRs, League Tycoon's published rules and direct provider written replies. The 2026-10-16 report is a dated research baseline, **not** current host/production truth.

---

## Repository preservation receipt (2026-10-30)

- **Original unmerged source:** https://github.com/jasonleetucker-code/riskittogetthebrisket/pull/1755
- **Other merged research baseline:** https://github.com/jasonleetucker-code/riskittogetthebrisket/pull/1764
- **Existing architectural consumers:** source/league identity, Trade Calculator, `src/ros/lineup.py`, `src/auction/`, Perfect Draft, dynasty values. Any future build consumes them without a new parallel authority.
- **Source accuracy:** copied PR's proposed §15 without converting candidates into confirmed owner rules. Inspect later provider rules and actual league policy at future approval.

## Original #1755 owner-intake entry and Activation rule (verbatim)

PR #1755 also added the entry below to `docs/OWNER_REQUESTED_TODO.md`. It is copied here word for word (commit
`f844c71baf`) so its Activation rule survives without a second ledger row. Its link to `BRISKET_IDEAS.md` §15
resolves only on #1755's own branch; that section's content is preserved verbatim above (§15). Kept in a code block
so the text is exact and its relative link is not rendered from this directory.

```markdown
## Added 2026-10-16 — League Tycoon ideas PARKED (owner instruction, NOT authorized)

**Status: IDEAS ONLY / LATER / explicit OWNER TRIGGER required.** The owner does not know when (or whether) the league will move to League Tycoon and wants to **finish the rest of Calculator first**. Do not schedule, build, automatically dispatch, or include League Tycoon transition work in the current completion denominator or any authorized execution batch. Current Sleeper functionality and product priorities remain unchanged.

**One durable detailed owner-facing record:** [`docs/BRISKET_IDEAS.md` §15 — League Tycoon](BRISKET_IDEAS.md#15-league-tycoon). This section retains the full 100-mechanism source index, twenty baseline and twenty-four additional candidate features, the 44-item research-ranked future backlog, preliminary league rules, provider/contract data architecture, Best Ball and rookie eligibility blockers, reusable code owners, migration gates, and the seven-stage future-only roadmap.

**Activation rule:** Only when the owner **explicitly instructs us to begin implementing the League Tycoon transition** may an agent re-audit current code/provider rules, propose the first batch, and obtain the requisite implementation authorization through `docs/EXECUTION_PLAN.md`. Completing the rest of Calculator, a passing dependency or a calendar date never implicitly activates this deferred family. No repository application-code changes, host migration, new provider integration, official auction launch, league transactions or production deployment authorized by this intake.

**Position:** LATER (owner-gated); **parallel class:** DEPENDENCY_BLOCKED / no execution claim; **existing canonical systems to reuse if later approved:** league registry + identity, valuation/lineup/replacement, trade engines, rookie auction/Perfect Draft, source provenance and Model Lab. This is a planning reference, **not** a change to existing C-Series scope or execution priorities.
```
