# Owner Feature Addendum — Dynasty Best-Ball Roster Utility

**Owner decision date:** 2026-08-29  
**Tracking issue:** #1173  
**Status:** OWNER-APPROVED SCOPE / PLANNED  
**Primary product owner:** canonical Trade Analyze / Trade Desk decision contract  
**Related foundations:** exact lineup assignment, Team Strength/Weakness, projections, injury/availability modeling, canonical values, KTC Value Adjustment

## 1. Purpose

Add a roster-conditional dynasty best-ball utility layer to trade analysis without changing canonical standalone player values.

Canonical player value continues to answer **what the asset is worth in the dynasty market/model**. This addendum creates a separate roster-context question: **what does this asset do for this exact roster under this league's best-ball lineup rules?**

The primary use is `/trade` Analyze Trade and the future Trade Desk. The same engine may later power a team-page Roster Efficiency / Redundancy Map.

## 2. Mathematical owner contract

For roster `R`, define expected best-ball lineup utility as:

`F(R) = E[optimal legal weekly lineup score | R, exact league rules]`.

For a proposed trade:

`Best-Ball Lineup Impact = F(R_after) - F(R_before)`.

The model must evaluate the entire legal lineup globally, including Superflex, offensive FLEX and IDP-FLEX eligibility. It must reuse canonical exact lineup/assignment machinery rather than independent per-position greedy approximations.

Player roster utility is conditional on the rest of the roster. A player's standalone canonical value must not be overwritten because his expected lineup utilization is low or high on a particular team.

## 3. Required decision outputs

The engine must provide, at minimum:

- **Best-Ball Lineup Impact:** expected optimal-lineup PPG and/or season delta before versus after the trade.
- **Lineup Entry Probability (LEP):** probability a relevant player appears in the optimal legal lineup under simulated/scenario weekly outcomes.
- **Usable Production / Redundancy:** distinguish raw projected scoring from projected scoring that actually survives competition for lineup slots.
- **Depth Insurance Value:** estimate lineup degradation under plausible starter injury/unavailability states before versus after the trade.
- **Roster Spot Shadow Value:** in unequal-player-count trades, value the gained/lost roster spot using the best realistic retained, replacement, stash or waiver asset rather than treating an empty slot as automatically worth zero.
- **Consolidation / Diversification classification:** identify whether the trade concentrates or spreads roster value and calculate roster-specific impact; there is no universal consolidation premium.
- **Position-specific depth effects:** diminishing returns must emerge from exact lineup demand and roster competition rather than arbitrary depth multipliers.
- **Explainable reasons:** output human-readable evidence for Analyze Trade, e.g. incoming player's lineup-entry probability, outgoing players' redundant utilization, healthy-lineup gain, injury-resilience loss, and roster-slot value.

## 4. Inputs and calibration

Use the best available canonical inputs, including:

- exact league scoring;
- exact league lineup requirements and eligibility;
- canonical player and pick identity;
- current / ROS / weekly projections when trustworthy;
- historical weekly scoring distributions;
- position/player availability and injury assumptions;
- bye weeks;
- empirical or bounded weekly variance and ceiling distributions;
- relevant player/team correlation where it adds independent information;
- realistic replacement/stash candidates for roster-slot valuation.

Missing or untrusted evidence remains explicit. Do not silently convert missing projection, injury or correlation information to zero.

Validate the model first on controlled synthetic cases where expected direction is mathematically known, then on historical weekly data with no-lookahead backtesting and calibration.

## 5. Trade-decision integration

This is a genuinely incremental **roster utility** dimension inside the one canonical Analyze Trade decision contract. It does not replace:

- canonical asset/package equity;
- KTC Value Adjustment as a named external-market consolidation lens;
- independent market corroboration;
- age/window/future-asset analysis;
- positional scarcity/need;
- uncertainty/risk analysis.

Respect lineage. Canonical player values, projections derived from common sources, Monte Carlo centered on those same values, and roster analyses that reuse those inputs must not be counted as independent votes merely because they render in different panels.

The decision engine should be able to distinguish a market-even trade that meaningfully improves usable weekly lineup scoring from one that only increases redundant bench value.

## 6. Product surface

Add a compact **Roster Construction Impact** section to Analyze Trade. At minimum it should expose:

- best-ball expected PPG before and after;
- net lineup-impact delta;
- relevant LEP changes;
- consolidation/redundancy effect;
- injury/depth-resilience delta;
- gained/lost roster-slot value;
- plain-English explanation of why the roster benefits or loses.

Example presentation:

> Strong consolidation opportunity. The incoming WR enters the simulated optimal lineup in 91% of eligible weeks; the two outgoing WRs enter in 28% and 7%. Expected optimal-lineup scoring rises 2.6 PPG. Injury resilience falls 0.4 PPG-equivalent, while the freed roster spot adds 0.3 PPG-equivalent. Net roster utility remains strongly positive.

Later, reuse this engine for a team-page **Roster Efficiency / Redundancy Map** identifying high-utilization core players, useful depth, redundant assets and fragile positional depth.

## 7. Guardrails

1. **Do not change canonical player values because of roster fit.**
2. **Do not invent a second proprietary Value Adjustment solely to encode roster utility.**
3. Preserve exact KTC VA as a separate market lens.
4. Best Ball Mania tournament advancement, finals and championship-equity statistics are **not** direct inputs to this dynasty best-ball model. Public best-ball research may inform methodology only where structurally transferable.
5. Tournament payout/upper-tail optimization is out of scope for this league's weekly dynasty-best-ball decision objective.
6. FLEX must be modeled globally; WR/RB/TE depth cannot be valued in isolation when they compete for shared lineup slots.
7. Unequal-package trades must account for the roster spot gained/lost.
8. Injury resilience and healthy-week efficiency must remain separately visible before synthesis.
9. Any roster-context recommendation must preserve market-value truth: a redundant player can still be highly valuable in trade even if his marginal scoring utility to the current roster is low.

## 8. Relationship to existing owner decisions

This addendum deepens the already-approved direction that **roster marginal impact is a major genuinely incremental trade dimension** and that Analyze Trade must synthesize unique-information dimensions without double counting. It specifies the previously missing dynasty-best-ball mechanics required to make that roster-impact dimension decision-grade.

It should be reconciled into `docs/OWNER_REQUESTED_TODO.md`, `docs/OWNER_FEATURE_INVENTORY.md`, the appropriate scope manifest/roadmap, and `docs/EXECUTION_PLAN.md` only when the normal planning/authorization workflow schedules implementation.

---

## 9. Future First six-episode extension — owner intake, 2026-10-30 (FFBB-1–8)

**Input:** owner-pasted transcripts of Future First Dynasty Best Ball episodes 50 (fundamentals), 51 (QB/TE), 52 (RB), 53 (WR/Scott Connor), 54 (contending builds), 55 (rebuilding), plus the owner's original Roster Construction tab proposal and the 44 working discussion concepts. **Scope:** durable product RESEARCH / FUTURE FEATURE DESIGN ONLY. The owner explicitly requested that these ideas be added to planning documents before any implementation. No authorization to build, promote a model, alter production formulas, merge, deploy, send Sleeper writes, pay for data, or generate the eventual Claude master implementation prompt.

This extension **does not replace §§1–8** or create a second best-ball/trade/roster utility engine. The preexisting mathematical owner contract for roster utility (F(R) = expected optimal legal weekly lineup points conditional on roster R) and canonical standalone dynasty valuations remain intact. Existing rollout, UI, C-Series, waiver, source, trade and owner-only release gates win if any historical transcript claim conflicts with them. This is **league-configuration-specific dynasty intelligence**, not a generic Best Ball Mania/tournament suite (previously explicitly out of scope).

### Goals and information architecture

The private, authenticated **Roster Construction** tab is the user's primary new proposed discovery surface. It must show a **selected team**, and optionally compare any two teams, league averages and other teams, with explicit metric identity and evidence dates. It connects four reusable product surfaces: Roster Construction (diagnosis); Trade/Trade Desk (how a move changes a roster); Waiver Advisor (best attainable additions and safe drops); and Team Strategy/Portfolio (championship window, draft capital, rebuilding). A unified recommendation layer tentatively called **The Next Move** can consume these outputs and suggest a bounded feasible action OR **NO ACTION**. Do not build another player value board, trade verdict owner, projection engine, fantasy lineup solver, or waiver transaction writer.

**Owner's central question:** Where do my league-relative starter points come from, where do my league-relative dynasty values sit, how often do rostered or prospective players meaningfully make an optimal lineup, and what *realistic* roster change improves this team given its strategy and available assets?

## 10. User-facing Roster Construction tab — explicit owner requests

1. **Exact sortable position groups:** QB / RB / WR / TE / DL (including EDGE where host classifies so) / LB / DB. Display (a) **realized optimal-starter fantasy points from the selected position** and its league rank, (b) standalone canonical **dynasty market/model value by position** and its separately ranked league standing, (c) projected current and target-year positional scoring readiness, (d) realized/projected optimal lineup appearances and marginal contribution, (e) coverage/injury resilience/false depth. Show rank numerator and denominator, total where useful, known ties and incomplete data. Keep scoring, market valuation, and positional need separate: Team Strength is NOT ROS production or playoff odds. **FLEX is not a separate sortable position**; allocate each accepted FLEX starter's realized points to their actual QB/RB/WR/TE/IDP group, while giving a separate FLEX *allocation/explanation* drill-down. Preserve the owner-approved #899 order: assign real FLEX starters BEFORE reserve depth.
2. **Player table with two different historical questions:** (i) how many weeks a player actually entered **this selected roster's legally optimized lineup while owned**; (ii) how many weeks they **would have** entered that roster if hypothetically rostered on eligible weeks, given *as-of-week* ownership and roster eligibility. For trade-history comparisons, freeze the roster at each week's appropriate transaction cutoff and mark impossible/unobservable hypothetical histories. Historical realized impact must not leak future weeks into past decisions.
3. **Independent average-starter comparator:** report weeks in which a player clears the empirical league/position-specific replacement or average-starter threshold, e.g., QB2 replacement in 12-team SF often approximates the QB24 tier, but never assume one hard QB24, RB24+flex or TE24+flex cutoff for all league cards. Calculate thresholds from actual required dedicated starters, flex competition, number of teams, availability and scoring. For TE, use actual **two mandatory TE spots** where configured, with no extra premium unless the selected league actually has one. This metric is deliberately **not** the same as entry to the owner's lineup.
4. **Player/spot historical audit:** starts, points that actually survived optimal-lineup assignment, incremental points beyond next-best legal alternative, weeks owned, productive-week rate, zero-production stretches, changes in dynasty value, hypothetical available replacements, and trade/insurance utility. Avoid claiming every unused or injured developmental player is waste; establish meaningful age/upside/contingency and user locks. Explain the different opportunity costs of holding a 23-year-old prospect versus an aging one-week streamer.
5. **Gap diagnosis:** e.g., TE scoring rank 12/12 but value rank 2/12 can represent future prospect upside rather than a current winning position; recommend short-term production only when it materially improves the chosen competitive window and does not sacrifice disproportionate long-term value. Show *why the two ranks disagree* and which available actions are plausible.
6. **Presentation:** main overview score/rank comparisons; position detail (starter allocations, projected start histogram, spike weeks, depth); roster asset/contribution table; compare with other 11 teams; transaction what-if and The Next Move with assumptions, confidence and dates. Progressive disclosure on mobile. This is private Front Office intelligence, not the public league museum. UI must consume server-stamped canonical results; existing Premium Sports Intelligence direction and Lane 6 rules govern design.

## 11. Shared exact-lineup methodology — refine, don't fork #1173

- For each past/future week, globally optimize all *legal* dedicated slots, FLEX, Superflex, both mandatory TEs where configured, and DL/LB/DB/IDP-FLEX under exact scoring, one player per lineup at most once, bye/injury/eligibility/status constraints, with canonical src/ros/lineup.py. Seasonal simple sums of players' hit weeks DO NOT guarantee coverage because hit weeks overlap; no greedy or independent per-position summing.
- Realized lineup entry: 1 if player appears in that week's legal optimal lineup for the actual historical roster. Marginal points: F_week(R) minus F_week(R without player, with best legal alternative subject to availability/roster legality). Prospective lineup entry probability (LEP): P(player in optimized lineup) under simulations; distinguish historical realized, forward projected, team-specific, market-comparator, and counterfactual.
- Estimate required weekly positional appearances via dedicated starter demand plus **empirically optimized** eligible FLEX assignments, not invented fixed shares. The podcast's 12-point WR and 76.5 WR-appearance example applies only to its example settings and is not a universal recommendation; avoid equating a positional *appearance* with a 12+-point performance.
- Model weekly scores as distributions (floor, typical, spike, tail) with realistic availability, team-level pace, bye weeks, scoring correlation, injury dependence and lineup substitution. Preserve week alignment rather than adding expected starts independently. Bound uncertainty and mark missing inputs instead of assuming 0.
- Marginal roster spot / transaction utility: Delta U = E[optimal points with candidate (and any legally required drop)] - E[optimal points without], plus separately presented dynasty-market-equity change, future value, downside/injury resilience, acquired pick value, FAAB and possible replacement. Explicitly include empty-slot replacement/stash cost (#1173), package size and user-protected roster assets.
- Provide **false depth** warning: nominal player count differs from productive, reliable and contingent coverage. Allow depth-complementarity and lineup overlap simulations rather than naive 'two players = one stud' arithmetic. Team-quality forecasts and title chances must come from existing calibrated simulation consumers, not new automatic formulas.

## 12. Position and weekly-opportunity modeling hypotheses

Treat episode opinions as **research hypotheses**, not fixed production values or current roster facts:

- **RB opportunity intelligence (RC-17 to RC-23):** carries, targets, routes, goal-line/red-zone touches, first downs, rush share, high-value touches, game script, committee share, team rushing environment, receiving participation, explosive plays. In this league, points per carry and first downs matter; snaps alone are not scoring. Role tags: elite anchor, established starter, 1B/sidekick, receiving specialist, contingent backup, speculative zero, veteran producer; tags can overlap/change. Expected weekly scoring is evaluated on the *exact card*. Test hero/robust/zero RB portfolios on equal asset budget; see opportunity cost, role/job-security and rookie/adaptation uncertainty. Succession risk tests by draft capital, experience, injury/workload and survival, without declaring a universal 'fifth-year cliff'. Weekly roster-spot efficiency, coverage and free-agent comparisons reuse the same lineup owner.
- **QB scarcity and security (episodes 50/51):** positional 32-team NFL supply constraints, 2QB/SF demand, expected starts, season-to-season job survival and veteran/backup/rookie contingent paths. Test elite-anchor-plus-cheap-depth, several stable starters, and active replacement strategies. Carrying starting QB plus primary backup can be an owner preference; never silently force sale of that pairing.
- **TE usage (episodes 50/51):** distinction between premium and **no-premium** scoring, two dedicated starter spots, elite-TE versus cheaper TE committee/Frankenstein builds, secondary TEs in 12/13 personnel as optional flex alternatives, injury/no-route risk, depth economy. Don't assume a change to NFL personnel trends persists; validate against target/route/opportunity data. Never restore withdrawn TE++.
- **WR elasticity (episode 53):** dedicated demand, flex share, individual useful-week threshold curves (1 / 3–5 / 6–9 / 12+ weeks), costly 'safe' WR2/WR3 archetypes versus cheap volatile contributors, route/target participation changes, WR3 injury-fill opportunities, and shallow/deep roster differences. Reproduce podcast 2025 population statistics before using them; forecast only with sourced observations and pinned priors.
- **All IDP roles:** extend the exact same framework to DL, LB and DB under actual IDP starter/roster needs, high-value opportunity statistics (rush/pass coverage, defensive snaps, tackles/TFLs/pass defenses/sacks as scored), contingent role changes, injury rotation, safe drops and league-relative starter thresholds. No second offense-to-IDP price scale or unauthorized source-weight changes.
- **Variance vs floor:** score the reliability of weekly coverage and boom/bust diversification, not merely season PPG. An injury-holding rebuilder and a production-seeking contender can rationally value the same player differently even while sharing one canonical standalone market value.

## 13. League meta and counter-meta (RC-24 to RC-29)

Measure league-wide roster counts and relevant available supply by position, total active NFL starters and backups, team-by-team demand, positional crowding, waiver replacement quality, trade frequency and market execution. Propose adaptive counter-meta options when many teams chase the same archetype, but never reward contrarian behavior by itself. Evaluate under equivalent roster capacity, trade/pick/FAAB cost, and plausible player availability.

Compare: robust vs hero vs low-capital RB; anchor-WR versus many cheap spike WRs; elite TE vs mid-tier committee; stable QB scarcity vs backup carousel; role/age/value concentration; thin versus deep best-ball portfolios; roster size 22/27/32/58+ etc. **No static roster-allocation prescriptions** ('double every position', '5 TE', or '6 RB') without a selected league calculation. Roster economy depends on roster limit, eligible positions and full-league player distribution.

Identify *market-versus-lineup* arbitrage: a player may have strong standalone value but modest weekly incremental impact on one roster. Tier down only if new pieces plus realistic roster spots improve outcomes or transferable asset value. Explicitly retain independent market liquidity even if a player would rarely start on the owner's team. Market prices must distinguish sources, overlapping samples and observed transactions. Do not present hypothetical trade acceptance as a fact.

## 14. Transaction, waiver and 'The Next Move' research (RC-18/19, RC-27/28, RC-32/35)

Reuse the existing single Analyze Trade owner, roster simulation, Team Weakness, C7 Best Trade / Manager Scout, waivers/FAAB and active IST waiver optimizer:
- Identify positional surplus that can **actually** be exchanged without harming mandatory lineup coverage; partner with teams possessing complementary shortages. Generate legally executable before/after portfolios with forced drops, protection locks (Minnesota Vikings outgoing preference where applicable), actual offered pick ownership, market equity, dynasty horizon and remaining roster spot value.
- Project weekly gains and losses, available waiver replacement vs trading cost; show confidence and decomposed effects rather than an unexplained composite.
- Route candidates through safe-to-drop / dynasty protection classes; never recommend an unpriced/missing asset as an automatic drop. Respect current zero dynasty-loss budget and 'no transaction' options where already binding.
- Model flexible in-season reserves for FAAB, veteran buys, QB emergencies, TE production, playoffs, roster churn and league-specific waiver frequency; don't assume the current site can submit claims or execute trades.
- The Next Move shows the most justified achievable *action* (or HOLD / NO ACTION), estimated point/championship impact, long-term market value implications, alternate options, dependencies and source freshness. It is a new presentation layer, NOT a second recommendation owner.

## 15. Contender integrity, strategy and season transitions (RC-30 to RC-36)

- Compare **official record**, optional median-game/all-play context, actual points, opponent/luck variance, expected wins, residual optimized projected weekly output, injury availability, position coverage, dynasty liquidity, age/succession risk and *calibrated* playoff/title distributions. A winning record can mask roster fragility; avoid claiming confidence in title probabilities when simulation calibration is unavailable.
- Choose conditional paths PUSH / HOLD / RETOOL / REBUILD from the existing competitive posture owner; compare long-run outcome distributions and opportunity costs, not blanket sell-all rules. A favorable record alone doesn't imply pushing; aging veterans alone don't imply tearing down. Dynasty value and point production remain different lenses.
- Value acquisition rights and strategic flexibility: future picks, liquid young stars, veteran producers, replacement and roster capacity. Flag synchronized expiring veteran windows; avoid harsh deterministic aging cutoffs.
- **Startup decision audit:** hypothetical draft and trade alternatives using the information available **at the decision time**, not hindsight outcome labels. Evaluate roster-fit of each pick and opportunity-cost of a luxury WR/RB selection over a then-available TE/QB. Historical outcomes are separate ex post evaluation; tests must prevent future-data leakage.
- Respect preexisting league-specific owner overlays and lineup/scoring semantics, and compare alternatives at equal asset budget before calling one build stronger.

## 16. Rebuild flywheel, contingent value and pick portfolio (RC-37 to RC-44)

- **Rebuild Exit Roadmap:** estimate probability of assembling enough productive players plus legal position/flex coverage in target years. Include draft classes, pick-owner distributions, uncertainty, rookie misses, veteran acquisitions, available managers and retained trade ammunition. Do not turn a dynasty value rank into a certainty of next-year contention.
- **Value Flywheel:** acquire cheap speculative assets, observe verified role changes or temporary starts, evaluate sell versus hold, consolidate into a genuinely more valuable future asset when executable, and reinvest freed roster spots. Measure the value created through actual transactions and value appreciation **separately** from optimized starter points. 'Zero snaps = zero immediate fantasy points' does NOT imply zero dynasty or option value.
- **Contingent QB/RB/WR/TE/IDP assets:** model probabilities of becoming active contributors, estimated fantasy production conditional on playing, expected resale values, holding time, downside and opportunity cost. Vet actual primary-backup roles vs 3rd-string or committee situations. Avoid treating speculative opportunities as certain jobs or encouraging a roster of only zeros that cannot eventually recover.
- **Liquidity / sell windows:** in quiet leagues with no genuine buyers, downgrade hypothetical 'sell for a second' recommendations to an *unexecutable/low-confidence proposal*. Distinguish a firm offer, trade comp, and theoretical value. Compare sell now, keep, package, later draft-market sale; account for draft position incentives as actually configured.
- **Picks / portfolio:** age and risk of production window, future 2027/2028/etc picks, origination, ownership, pick-horizon probabilities, rookie class concentration, draft capital held to repair a contender, cost of transacting in shallow vs deep leagues. Never assume popular future classes are guaranteed excellent.
- **Draft position** is governed by the selected league's **recorded rules**, not generic Max PF. For dynasty_main, docs/picks/DRAFT_ORDER_RULE.md expressly mandates worst final regular-season record and lower regular-season Points For tie-break, with the median-record question separately unresolved. Max PF may be explored only when another league explicitly establishes it as its rule; a low Max PF must never silently be presented as a draft advantage in dynasty_main.
- **Waiver economics:** understand continuous/weekly/quarterly runs, deadlines, $1 minimum where configured, legal transaction windows and pickup competition. FAAB is an asset with scarcity and trade value only if supported by that league; unobserved losing bids remain unknown.

## 17. Startup draft, auction and other workflow extensions

Use existing Perfect Draft/Draft Room, auction owners, pick identity, roster simulations and constrained trade package tooling. Compare startup *pick-package* swaps including small late-round improvements bundled with marquee early picks; value at the expected draft board and current roster need, not absolute round number alone. Contrast flexible proxy slow-auction budget allocation against snake draft opportunities, while preserving existing draft/auction definitions, bidding legality, user constraints and provenance. Read-only research and what-if suggestions only unless separately authorized.

## 18. Research identity, trust and validation

**Acceptance questions for eventual separately authorized design/implementation:**
1. For each selected real league and week, the historical optimized lineup agrees with official host-reported scoring when official best-ball scoring is available; all positions/2TE/IDP/FLEX/bye constraints respected; no player counted twice.
2. Selected team positional starter-point rankings and dynasty-value ranks reflect **different** clearly labeled denominators; duplicate starts through flex are impossible. Demonstrate position-rank comparisons across all teams. Support 'would this player have started' using weeks owned and an independently flagged hypothetical simulation.
3. With identical source/roster snapshots, trade, waiver, team view and Next Move display identical shared lineup utility, projections and value semantics; never duplicate canonical owners.
4. Replacing/adding a cheap player cannot improve a team's scoring forecast when the player is mathematically dominated and has no legal lineup path, though dynasty/insurance value may remain. Free replacement value must account for availability, team-specific replacement, FAAB and league deadlines.
5. Synthetic known-answer baselines cover flex intersections, 2TE, SF, 3 DL/LB/DB, missing/unpriced and protected players, spike overlap, negative-trade/forced drop, opposing injuries, and 'no action'. Explicitly preserve existing IST protection/streaming contract.
6. Blind, no-lookahead backtest against at least multiple completed league-years where available: LEP calibration, positional threshold calibration, market trade timing, performance by archetype, overfitting/selection bias, opponent meta and rookie transition uncertainty. Dataset limitations are labeled.
7. Championship probabilities, replacement distributions, speculative job promotions, acceptance likelihood and aging hazards are **challengers** until independent calibration and owner-approved promotion; no arbitrary numerical assurance, static hard-coded 12-point benchmark, automatic age cliff, or adoption from podcast anecdotes.
8. Every user-visible result includes method version, available coverage, data-as-of time, source lineage and missing/insufficient/stale statuses; no paid unapproved sources and no cross-user/private league leaks. No Sleeper writes or automated trade spam.

**Existing canonical owners/dependency routing:** exact assignment src/ros/lineup.py; Team Strength src/roster_intel/strength.py; before/after src/roster_intel/simulation.py; replacement/PAR C2-REPL-01; projections src/ros/ weekly owners; canonical values and pick owners; Team Weakness; historical src/history and acquisition; waivers/drop assessment and IDP IST work; market trade ledger, Manager Scout; draft/auction stores; competitive posture; playoff simulation. Inspect current production paths/claims before any implementation. One service per concept and one decision/verdict owner.

## 19. Relationship to old discussion identifiers and duplication control

The **44 RC-01…RC-44 numbers are brainstorming labels only**, not implementation tickets, not additional C-Series units, and not claims of 44 independent code features. Episode 50/51 initial ideas include the selected-team roster-construction UI, player start/history and league-average starter counters, positional scoring vs dynasty value, start coverage, floor/spike blending, QB/TE scarcity, contingency and zero roster spots; §§10–12 preserve these baseline concepts. The later labels are grouped as follows:

| Discussion range | Captured implementation family / coverage |
|---|---|
| RC-17…RC-23 (RB episode) | Opportunity, roles, roster spot efficiency, portfolio construction simulation, depth complementarity, succession, timing; §§11–12, 14–15 |
| RC-24…RC-29 (WR/meta episode) | League-meta intelligence, start/flex demand, spike supply, replacement shadow value, market/utility arbitrage, counter-meta; §§11, 13–14 |
| RC-30…RC-36 (contending episode) | Contender monitor, whole-roster builds, surplus conversions, startup pick-package swaps, posture change, resource allocation, decision replay; §§14–15, 17 |
| RC-37…RC-44 (rebuilding episode) | Exit roadmap, value flywheel, contingencies, trade liquidity, sell window, pick portfolio, rule-specific draft incentives, waiver calendar; §16 |

Do not use these ranges as delivery-denominator increments. Reconcile against prior #1173, existing C2/C3/C4/C5/C7 rows, IST-1…12, NC directives, and canonical model owners before creating any feature ticket. **No changes to existing production behavior or methodology are authorized by these planning notes.**

## 20. Priority, dependencies, acceptance and implementation authority

| Work family | Planning priority / position | Canonical dependency / concurrency | Minimum acceptance evidence when later authorized |
|---|---|---|---|
| Selected-team Roster Construction ranks and transparent historical starts | P1 / NEXT after data/existing-UI audit | C2 exact lineup, roster/actuals history, position scoring and canonical market value; backend serial, UI safely parallel | All 12 league teams, 7 position groups, week-by-week parity, no duplicate FLEX, missingness |
| Shared weekly counterfactual LEP / marginal roster utility and roster-spot opportunity cost | P1 research / NEXT; no automatic model promotion | Existing #1173 utility, C2 solver, C5 projection and roster snapshot history; serial shared owner | Synthetic exact baselines, prior-year no-lookahead backtest, model calibration |
| Positional role/variance/false-depth, meta and counter-meta portfolios | P2 research / LATER or dependency blocked | C5 data/source licensing, C2 replacement, C4 market behavior | No hindsight, comparable asset budgets, benchmark deltas and uncertainty |
| Trade/waiver integration and 'The Next Move' | P1 product outcome / DEPENDENCY BLOCKED until common utility and existing IST work settled | Single Analyze Trade, roster capacity, C7, IST safe-drop; integration-only after owner review | One consistent recommendation across pages, no-action and user locks |
| Contender integrity, windows, rebuild flywheel, draft/auction and FAAB economics | P2 / LATER; shadow-calibration first | Posture, playoff odds, pick rule, trade and waiver history, market liquidity | Calibrated decision uplift vs baselines, owner-selected league rule proof, original no-hindsight audit |
| PSI UI treatment | Existing always-parallel UI lane where scope ready | UI implementation contract and active claims | Accessible/mobile usable, backend/UI parity, UI acceptance |

**Implementation authority:** none from this research intake. Remains solely in docs/EXECUTION_PLAN.md; do not amend current execution authorization or intersect open IST/NC file claims. Preserve existing work and owner-reserved gates. The user also explicitly withheld authorization to create the **single final Claude master implementation prompt** until a later instruction.

**Superseded for V1 scope (2026-10-30):** `docs/EXECUTION_PLAN.md` RCV-4 now AUTHORIZES building the private Roster Construction V1 (FFBB-1, plus the minimal FFBB-2 layer it needs) behind default-OFF flag `roster_construction`; production activation stays owner-gated (RCV-7); FFBB-3…8 research items remain unauthorized. Owner record: `docs/owner/RELEASE_COMPLETION_ROSTER_CONSTRUCTION_DIRECTIVE_2026-10-30.md`.
