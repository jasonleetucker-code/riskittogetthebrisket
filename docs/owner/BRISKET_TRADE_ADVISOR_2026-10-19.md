# OWNER DIRECTIVE (verbatim) — 2026-10-19 — IMPLEMENTATION REQUEST: BRISKET TRADE ADVISOR

> *Not part of the verbatim directive:* the implementation design record is [`BRISKET_TRADE_ADVISOR_DESIGN_2026-10-19.md`](BRISKET_TRADE_ADVISOR_DESIGN_2026-10-19.md).

IMPLEMENTATION REQUEST: BRISKET TRADE ADVISOR

Public League Hub Trade Calculator — Full Implementation

REPOSITORY

"jasonleetucker-code/riskittogetthebrisket"

PRIORITY

High — Production implementation

OBJECTIVE

Build a public-facing trade evaluation tool for our dynasty fantasy football league, Risk It to Get the Brisket.

The tool will be named:

BRISKET TRADE ADVISOR

It must become the default landing page of the existing public League Hub.

This is not a new valuation system.

It is not a simplified mathematical approximation of our existing calculator.

It must be a secure, streamlined, public-facing interface powered by the exact same calculation engine, valuation methods, source weighting, value adjustments, league settings, and trade evaluation logic used by our existing private trade calculator.

The primary difference is what the user is allowed to see.

Our private calculator exposes extensive player values, source data, adjustments, comparisons, and underlying trade intelligence.

The Brisket Trade Advisor must expose none of that proprietary information.

Instead, league members should be able to construct a trade involving two, three, or four teams, submit the trade for analysis, and receive a simple recommendation about whether the trade benefits their selected team.

The intended audience includes relatively inexperienced fantasy football managers.

The interface should be exceptionally intuitive without sacrificing the accuracy or sophistication of the underlying calculations.

Implement this feature completely, including frontend, backend, integration, security, testing, and navigation.

Do not stop after producing a proposal or design document.

---

PHASE 1 — AUDIT THE EXISTING SYSTEM

Before making changes, inspect the repository thoroughly.

Identify and document:

1. The existing private trade calculator.
2. Its frontend components.
3. Its backend valuation and calculation services.
4. Its current trade evaluation algorithms.
5. All applicable value adjustment logic.
6. The current source weighting and aggregation system.
7. Existing package adjustments.
8. Existing player and pick valuation systems.
9. Existing league-specific scoring adjustments.
10. Existing multi-team trade support.
11. The current public League Hub.
12. Existing League Hub navigation and routing.
13. Existing Sleeper league data integrations.
14. Current player ownership and roster data.
15. Existing draft pick ownership and projection logic.
16. Existing API authentication, authorization, caching, and rate limiting.
17. Any other dependencies that could affect trade evaluations.

Determine whether the existing trade calculator is calculated server-side, client-side, or through a combination.

This distinction is extremely important.

Do not assume that an existing frontend calculation can safely be reused in a public application.

If the current calculator calculates values in the user's browser, determine how to securely expose its authoritative evaluation functionality through the backend without sending private valuation data to public clients.

Document the current architecture before changing it.

Critical instruction

Do not create a separate implementation of the valuation formula.

Do not copy the existing formula into another independent calculator.

Do not create a second set of source weights.

Do not establish separate valuation databases for the public and private calculators.

There must be one authoritative valuation and evaluation system.

The public Trade Advisor should call that same system through a secure, tightly controlled interface.

If architectural refactoring is necessary, preserve the existing private calculator's behavior.

---

PHASE 2 — LEAGUE HUB LANDING PAGE

Make the Trade Advisor the default page

Currently, users access the public League Hub through the existing navigation.

Modify the routing so that clicking:

GO TO LEAGUE HUB

opens the new Brisket Trade Advisor immediately.

The other existing League Hub pages and features must remain accessible.

Do not remove or replace existing functionality unnecessarily.

Page heading

BRISKET TRADE ADVISOR

Subtitle:

Evaluate trades using our league's scoring, roster construction, and dynasty market.

The page should visually communicate that this is a sophisticated but simple trade decision tool.

Navigation

Retain existing League Hub navigation conventions.

Add the Trade Advisor as the primary/default destination.

Ensure that:

- Existing League Hub URLs remain functional.
- Existing pages remain accessible.
- Deep links continue working.
- Browser back and forward navigation work.
- Direct loading of the Trade Advisor works.
- Mobile navigation remains intuitive.

If the League Hub already has an established routing hierarchy, integrate with it instead of introducing a competing navigation system.

---

PHASE 3 — SELECT YOUR TEAM

The first interaction should be selecting a team.

Display:

WHICH TEAM ARE YOU EVALUATING FOR?

Provide a searchable dropdown containing the 12 teams in the league.

Use actual current team names, owners, and identifiers from our existing league data.

Do not hardcode names.

When a user selects a team, that team becomes:

YOUR TEAM

throughout the interface.

The user should then select a trading partner.

Display:

SELECT TRADE PARTNER

Populate that dropdown with all other teams in the league.

The same team cannot occupy multiple positions in the same trade.

Important distinction

Selecting "Your Team" establishes the perspective from which the trade is evaluated.

It does not establish authenticated ownership or grant permission to modify a roster.

If the League Hub is publicly accessible, users should be able to evaluate trades from any team's perspective without the application falsely implying that they own that team.

The advisor is strictly an evaluation tool.

It must not execute trades, modify rosters, submit offers, or change league data.

---

PHASE 4 — TWO-, THREE-, AND FOUR-TEAM TRADES

Support trades involving:

- Two teams
- Three teams
- Four teams

At the top of the calculator, include:

TEAMS INVOLVED

"[ 2 ] [ 3 ] [ 4 ]"

Default to two teams.

Changing the number of teams should dynamically update the trade builder.

Two-team layout

On desktop, use two columns.

YOUR TEAM

Select assets being sent.

TRADE PARTNER

Select assets being sent.

For example:

YOUR TEAM SENDS:

- Josh Allen

TRADE PARTNER SENDS:

- Joe Burrow
- Ja'Marr Chase

Underneath, provide a consolidated summary:

YOU SEND
Josh Allen

YOU RECEIVE
Joe Burrow
Ja'Marr Chase

Then:

ANALYZE TRADE

This summary is essential.

The user should never have to guess which players they are sending or receiving.

Three- and four-team layout

Multi-team trades require a more flexible interface.

Each team should have its own panel.

Every selected asset must have a clearly specified destination team.

For example:

TEAM A:

- Josh Allen → Team B

TEAM B:

- Joe Burrow → Team A
- Ja'Marr Chase → Team C

TEAM C:

- Justin Jefferson → Team B

The trade builder must support legitimate multi-team transactions, including nonreciprocal asset routing within an otherwise valid trade.

Do not assume that every team must exchange assets directly with every other team.

For each asset, track:

- Asset identifier
- Asset type
- Originating team
- Destination team
- Trade participation context

Validate the complete transaction before analysis.

Reject duplicate assets, invalid destinations, empty or malformed trades, unauthorized asset assignments, and other invalid configurations.

Use the existing private calculator's trade validity and multi-team requirements wherever they already exist.

Do not silently invent new eligibility requirements that would prohibit otherwise valid trades.

Trade summary

Before analysis, provide a complete summary of what every team sends and receives.

On mobile, use vertically stacked team panels instead of squeezing multiple columns onto the screen.

---

PHASE 5 — ACTUAL LEAGUE ROSTERS

The asset selector must automatically populate from actual league data.

When a team is selected, load that team's current assets.

This must include:

- Quarterbacks
- Running backs
- Wide receivers
- Tight ends
- Defensive tackles
- Defensive ends
- Linebackers
- Cornerbacks
- Safeties
- All other eligible player types supported by the existing calculator
- All eligible owned draft picks

Do not restrict the tool to offensive players.

Our league uses IDP, and our existing valuation system has specialized IDP handling.

The Trade Advisor must preserve that functionality.

Asset selection experience

Provide a searchable asset selector.

Users should be able to:

- Search by player name.
- Filter by offensive position.
- Filter by defensive position.
- Show offense only.
- Show defense only.
- Show draft picks.
- Sort alphabetically.
- Sort from highest internal value to lowest.
- Sort from lowest internal value to highest.

Default sorting should be highest internal value first.

However:

Never display the actual underlying values.

The user may see player names ordered according to our valuation system, but never the numerical scores responsible for that ordering.

Do not include numerical ranks, percentile labels, value differences, or hidden value attributes.

Security requirement for sorting

The backend should return an already ordered list for the requested sort.

Do not transmit the private numerical values to the browser and sort them client-side.

Changing sort order must not expose valuation fields in API responses.

Sorting must use the same active valuation state as the calculator's evaluation engine.

Prevent invalid selections

An asset already assigned to a trade should not be selectable again.

Prevent users from:

- Including the same player twice.
- Including the same pick twice.
- Sending a player from a team that does not own that player.
- Sending a pick from a team that does not own that pick.
- Selecting the same team multiple times.
- Sending an asset to its existing owner as a trade movement.

Backend validation must enforce these rules independently of frontend validation.

---

PHASE 6 — DRAFT PICKS AND PROJECTED PICKS

The Trade Advisor must support the same draft pick assets supported by our private calculator.

This includes applicable future draft years, such as:

- 2027
- 2028
- 2029

Do not hardcode those as the only years.

Use our current draft pick data model and eligible valuation horizon.

Owned picks

Populate the selector with actual picks owned by each team.

Ownership must reflect trades that have already occurred.

A team's original picks may now belong to another team.

Never assume original ownership.

Projected picks

Our private calculator already has logic for projected picks and their relative values.

Reuse that logic exactly.

Where applicable, the interface may display:

- Projected Early
- Projected Mid
- Projected Late

However, projected classifications must be associated with actual eligible draft pick assets.

Do not create fictional tradable picks simply because the valuation engine models projected selections.

Pick identity

Ensure that the system correctly tracks:

- Draft year
- Round
- Original owner
- Current owner
- Underlying asset identifier
- Applicable projected position or classification

Use the repository's existing pick identification logic wherever possible.

Public display

Show useful descriptive labels without exposing the pick's numerical value.

For example:

2027 1st — Originally Team X — Projected Early

Avoid showing:

- Internal pick value
- Historical valuation spine
- Adjusted dollar value
- Source contribution
- Projection formula
- Value Adjustment calculations

If a projected classification changes, the public advisor should reflect the change through its existing data refresh mechanism.

---

PHASE 7 — SHARED VALUATION ENGINE

This is the most important engineering requirement.

The public advisor must calculate trades using the exact same active valuation and trade evaluation logic as our existing private calculator.

Not approximately.

Not a simplified version.

Not a separate formula.

The exact same logic.

Reuse all applicable functionality

This includes, but is not limited to:

1. Current player valuations

Use the same authoritative player values.

2. Current draft pick valuations

Use our existing valuation methodology.

3. Value Adjustment

Our updated Value Adjustment system must be included.

Do not accidentally use outdated or unadjusted values when the private calculator uses the active adjusted model.

4. Source aggregation

Preserve our current aggregation and weighting rules.

5. Offensive valuation sources

Use whatever offensive sources currently contribute to the private calculator.

6. Defensive valuation sources

Include all currently eligible voting IDP sources.

7. Source recency and freshness

Preserve current freshness rules and recency weighting.

8. Package adjustments

Preserve existing rules that account for trading one premium asset for multiple assets.

9. Multi-player trade evaluation

Evaluate the entire package, not each asset in isolation.

10. Multi-team trade evaluation

Preserve the private calculator's existing multi-team handling.

11. League-specific scoring

Use the existing league's scoring settings, including superflex, tight end premium, and IDP configurations.

12. All remaining adjustments

If the private calculator applies an adjustment that is not explicitly listed here, the public calculator must also apply it whenever appropriate.

Do not introduce new logic

Do not independently invent:

- New player values
- New source weights
- New adjustment multipliers
- New package penalties
- New IDP formulas
- New positional scarcity formulas
- New contender/rebuilder bonuses
- New trade fairness thresholds

The public interface must reflect the actual existing calculator.

If the existing calculator already accounts for team needs or roster composition, preserve that functionality.

If it does not, do not add an independent model that could contradict the private calculator.

Automatic synchronization

When the main calculator changes, the public advisor must automatically use the updated logic.

Changes to the following must propagate without maintaining a separate public model:

- Player values
- Source weights
- Value Adjustment
- Freshness weighting
- Draft pick valuation
- IDP valuation
- Package calculations
- Applicable league settings
- Trade evaluation logic

Use shared services and shared authoritative data.

Do not create synchronization processes that merely copy values between two independently maintained calculators.

---

PHASE 8 — PUBLIC TRADE RECOMMENDATIONS

The public interface must never show raw trade values.

After the user constructs a trade and clicks:

ANALYZE TRADE

the server should evaluate the transaction privately.

The user should receive a recommendation from the perspective of their selected team.

Recommended categories

Use five possible result categories:

1. STRONGLY FAVORABLE

Display:

ACCEPT — STRONG TRADE FOR YOUR TEAM

Supporting message:

Our analysis strongly favors your side of this trade.

2. FAVORABLE

Display:

ACCEPT — GOOD TRADE FOR YOUR TEAM

Supporting message:

Our analysis indicates this trade benefits your team.

3. APPROXIMATELY EVEN

Display:

FAIR TRADE — YOUR DECISION

Supporting message:

Our analysis considers this a relatively balanced exchange.

4. UNFAVORABLE

Display:

DECLINE — NOT RECOMMENDED

Supporting message:

Our analysis indicates this trade does not favor your team.

5. STRONGLY UNFAVORABLE

Display:

DECLINE — STRONGLY NOT RECOMMENDED

Supporting message:

Our analysis strongly favors the assets your team would give up.

Classification rules

These five categories should be mapped from the existing calculator's authoritative evaluation.

Inspect the private calculator's current verdict and fairness methodology.

Where the existing methodology supports these distinctions, derive the public categories from it.

Do not create arbitrary, unsupported numerical thresholds.

If the existing engine cannot reliably distinguish all five categories, document the limitation and implement the smallest defensible category mapping without introducing an independent valuation system.

Do not label a trade strongly favorable unless the authoritative evaluation supports that conclusion.

Directional evaluation

A trade recommendation must always be evaluated from the perspective of the selected team.

For example:

If a manager chooses Team A:

The result describes whether Team A benefits.

If the same trade is evaluated from Team B's perspective:

The result must reflect Team B's position.

Do not simply label one side the winner and assume that resolves every possible recommendation.

For multi-team trades, evaluate the selected team's net position using the existing multi-team engine.

Avoid contradictory outcomes

Ensure that public recommendations remain consistent with private evaluations.

If the private calculator considers a trade unfavorable to Team A, the public advisor must not call it strongly favorable to Team A.

Create automated tests enforcing this consistency.

If the private engine cannot evaluate a proposed trade reliably, return an unavailable or inconclusive result rather than inventing a confident recommendation.

---

PHASE 9 — RESULTS INTERFACE

After clicking Analyze Trade, show a clean results panel.

Example:

---

TRADE ANALYSIS

YOUR TEAM SENDS

Josh Allen

YOUR TEAM RECEIVES

Joe Burrow
Ja'Marr Chase

RECOMMENDATION

ACCEPT — GOOD TRADE FOR YOUR TEAM

Our analysis indicates this trade benefits your team.

[ EDIT TRADE ]

[ NEW TRADE ]

---

Extremely important display restrictions

The public results must NOT display:

- Player valuation numbers
- Pick valuation numbers
- Adjusted values
- Raw values
- Source rankings
- Source-specific player values
- Source weighting
- Adjustment factors
- Package adjustment calculations
- Value differences
- Percentage advantages
- Trade ratios
- Internal fairness scores
- Confidence calculations derived from private valuation data
- Model internals
- Scoring formulas
- Source contribution breakdowns
- Hidden debug information

Do not expose this information in expandable sections, tooltips, HTML attributes, JavaScript state, or API payloads.

Multi-team results

For three- and four-team trades, show a complete asset exchange summary.

However, the recommendation must focus on the user's selected team.

For example:

YOUR TEAM'S RECOMMENDATION

ACCEPT — GOOD TRADE FOR YOUR TEAM

Do not expose individual valuation scores for the other participating teams.

Do not add a detailed numerical winner/loser leaderboard.

Editing

After receiving a result, the user must be able to:

- Return to the trade builder.
- Add or remove assets.
- Change asset destinations.
- Reanalyze the revised trade.
- Reset the transaction.

Reanalysis should reflect current authoritative valuation data, subject to the application's established caching and freshness policy.

---

PHASE 10 — SECURITY AND PROPRIETARY DATA PROTECTION

This feature is intended to give league members access to our evaluation intelligence without giving them direct access to the underlying valuation data.

Therefore, security is a core architectural requirement.

It is not sufficient to hide values with CSS.

It is not sufficient to remove values from visible table columns.

It is not sufficient to calculate everything in the browser and simply display a verdict.

Required architecture

Implement a secure server-side evaluation boundary.

The public frontend submits:

- League identifier
- Selected team identifier
- Participating team identifiers
- Asset identifiers
- Asset origin and destination information

The server then:

1. Validates the request.
2. Verifies current asset ownership.
3. Validates the trade structure.
4. Obtains the authoritative valuation context.
5. Runs the existing trade evaluation engine.
6. Determines the appropriate public recommendation.
7. Constructs a tightly restricted response.
8. Returns only permitted public information.

Example response

{
  "status": "success",
  "recommendation": "ACCEPT",
  "category": "FAVORABLE",
  "message": "Good trade for your team."
}

The implementation may require additional non-sensitive fields for valid UI operation.

However, public response objects must be explicitly allowlisted.

Do not serialize an entire internal trade evaluation object and rely on the frontend to ignore fields.

Protect internal APIs

Inspect existing routes that expose valuation data.

Ensure that implementing the public advisor does not unintentionally make previously private services publicly accessible.

Do not expose private environment variables, source credentials, valuation snapshots, raw model outputs, or internal caches.

Public endpoints should provide only the minimum information needed to build and evaluate trades.

Asset sorting

Sorting by internal value must occur on the server.

Only the ordered asset identities and permitted display metadata should be returned.

Never provide numerical sorting keys to the frontend.

Authentication and access

Inspect the current League Hub access model.

Preserve its intended public accessibility.

If authentication already exists, integrate with it appropriately.

Do not introduce a new login requirement without an architectural reason.

Public trade evaluation must never grant access to private administrative functionality.

Reverse-engineering protection

Recognize that repeated queries could allow someone to infer approximate private valuations.

Add reasonable protections, including:

- Rate limiting.
- Request validation.
- Response size limits.
- Maximum supported teams.
- Maximum legitimate trade assets, based on existing rules.
- Protection against automated high-volume submissions.
- Appropriate public API caching behavior.
- No numerical precision in responses.
- No debug metadata.
- No verbose errors containing internal data.

Use an appropriate server-side or shared rate limiter for the existing deployment architecture.

Do not rely exclusively on client-side restrictions.

Do not assume these protections make the underlying valuations mathematically impossible to infer.

The objective is to substantially reduce information leakage without making the tool frustrating for legitimate league members.

Security audit

Before completion, verify that none of the new public endpoints expose proprietary values through:

- Response bodies
- Response headers
- Error responses
- Serialized application state
- Hydration payloads
- HTML attributes
- Public JavaScript bundles
- Source maps
- Browser storage
- Public cache endpoints
- Debug routes

Also inspect whether the public advisor accidentally exposes existing private calculator services.

---

PHASE 11 — MOBILE-FIRST USER EXPERIENCE

Most league members may use this tool on their phones.

Build mobile-first, then enhance the desktop layout.

Mobile workflow

STEP 1 — SELECT YOUR TEAM

Dropdown.

STEP 2 — SELECT TRADE PARTNER

Dropdown.

STEP 3 — BUILD YOUR TRADE

YOU SEND

[ + ADD PLAYER OR PICK ]

YOU RECEIVE

[ + ADD PLAYER OR PICK ]

STEP 4 — REVIEW TRADE

Show a clear transaction summary.

STEP 5 — ANALYZE

[ ANALYZE TRADE ]

STEP 6 — RECOMMENDATION

Show a prominent, easy-to-understand result.

Mobile asset selection

The asset picker should be fast and easy to use.

Requirements:

- Searchable.
- Large enough touch targets.
- Clear asset labels.
- Position filters.
- Offensive/defensive filters.
- Draft pick filtering.
- Internally value-sorted assets.
- No unnecessary navigation.
- No horizontal overflow.
- No unusably narrow panels.

For multi-team trades, use stacked team sections or another responsive approach that preserves clarity.

Desktop layout

Use a denser interface.

For two-team trades, display team panels side by side.

For larger trades, adapt intelligently based on available width.

Do not sacrifice usability simply to fit four panels into one row.

---

PHASE 12 — VISUAL DESIGN

Follow the established design system used throughout the Calculator project.

We have already established a specific visual direction.

Premium Sports Intelligence — Direction A

Preserve the existing palette:

- Cream background
- Dark brown/black text: "#1c1712"
- Burnt-red accent: "#a3341c"

Styling requirements:

- Minimal border radii.
- Thin dividing lines.
- Dense but readable asset lists.
- Clear typography hierarchy.
- Tabular numerals wherever applicable.
- Restrained use of color.
- No gradients.
- No oversized rounded cards.
- No generic SaaS dashboard styling.

The page should feel like a natural extension of the existing site.

Not a separate application.

Not a third-party calculator embedded inside our website.

Result colors

Use restrained success, neutral, and warning treatments.

Favor clarity over decoration.

Recommendation categories must remain understandable without relying on color alone.

---

PHASE 13 — STATE MANAGEMENT AND DATA FRESHNESS

The advisor should reflect current league data and current valuation logic.

Inspect how the existing calculator refreshes its values.

Use the same authoritative data state.

Roster updates

When Sleeper roster ownership changes, the public advisor must reflect those changes through the existing synchronization process.

Draft pick changes

When picks are traded, the selector must reflect their current owner.

Valuation updates

When valuation sources refresh or Value Adjustment changes, new trade evaluations must use the active model.

Data consistency

Avoid mixing:

- An old roster snapshot
- A newer pick ownership snapshot
- A different valuation version

Prefer a consistent evaluation context where supported by the existing architecture.

If valuation updates occur during an evaluation, the calculation should use a coherent version of the data.

Cache behavior

Reuse existing cache infrastructure where appropriate.

Cache public roster metadata if useful.

Do not make private valuation objects publicly retrievable through cache keys or endpoints.

Ensure that private evaluation outputs are never unintentionally shared across users or exposed through public caching layers.

---

PHASE 14 — EDGE CASES

Handle the following conditions explicitly.

Player recently traded

An asset may appear in a stale client-side list after ownership changes.

Backend validation must detect incorrect ownership.

Refresh the user interface and display an understandable message.

Player missing from valuation sources

Preserve the existing private calculator's missing-data handling.

Do not invent a new valuation.

Use the active canonical or fallback behavior only where it is already applicable in the private calculator.

If an asset cannot be evaluated under current rules, report that the trade cannot be evaluated reliably.

IDP players

Confirm that all supported defensive positions work correctly.

Use current voting source eligibility and active IDP adjustments.

Draft picks

Handle:

- Missing picks.
- Traded picks.
- Future years.
- Projected classifications.
- Unavailable projections.
- Duplicate selections.

Multi-team trades

Handle:

- Three-team cycles.
- Four-team cycles.
- Teams sending multiple assets.
- Teams receiving multiple assets.
- Unequal numbers of assets.
- Players and picks mixed together.
- Assets routed to different destinations.

Invalid trades

Provide understandable errors without exposing calculation details.

Empty states

Handle a team with no eligible assets in a particular filter.

Loading states

Provide clear feedback while fetching rosters or evaluating a trade.

Analysis failures

If the backend cannot produce a trustworthy result, do not substitute a simplistic sum of values.

Display a clean unavailable result and allow the user to retry.

---

PHASE 15 — AUTOMATED TESTING

Implement comprehensive tests.

Do not consider this project complete merely because the interface renders.

Test group A — Calculator parity

Construct representative transactions and compare the private calculator evaluation with the underlying evaluation used by the public advisor.

Include:

1. One player for one player.
2. One premium player for multiple players.
3. Multiple players for multiple players.
4. Offensive players only.
5. IDP players only.
6. Mixed offense and defense.
7. Players for draft picks.
8. Draft picks for players.
9. Mixed player-and-pick packages.
10. Three-team trades.
11. Four-team trades.
12. Trades affected by package adjustments.
13. Trades affected by Value Adjustment.
14. Trades involving missing or fallback valuations.
15. Trades involving projected picks.

The shared underlying evaluation must be equivalent for identical inputs and evaluation context.

The public response should simply omit private details.

Test group B — Recommendation consistency

Verify that:

- Favorable private evaluations produce consistent public recommendations.
- Unfavorable private evaluations produce consistent public recommendations.
- Approximately fair trades are not arbitrarily classified as strongly favorable.
- Reversing team perspective produces the appropriate perspective-dependent recommendation.
- Multi-team evaluations remain consistent with the authoritative engine.

Do not assume that every trade must have exactly one winner.

Test group C — Asset ownership

Verify:

- Players belong to the selected originating team.
- Picks belong to the correct current owner.
- Duplicate assets are rejected.
- Invalid destinations are rejected.
- Recently moved assets are handled safely.
- Stale client submissions are rejected appropriately.

Test group D — Privacy and security

Test public endpoints to ensure they never return:

- Raw values.
- Adjusted values.
- Source valuations.
- Weighting coefficients.
- Package adjustment values.
- Internal fairness scores.
- Private model output objects.
- Source snapshots.
- Private credentials.

Use exact response schema assertions wherever practical.

Also test error responses.

Verify that unexpected exceptions cannot serialize private information.

Test group E — Frontend

Test:

- Team selection.
- Partner selection.
- Team count changes.
- Asset searching.
- Position filters.
- Sorting.
- Adding assets.
- Removing assets.
- Routing assets in multi-team trades.
- Reviewing a trade.
- Submitting analysis.
- Displaying recommendations.
- Editing transactions.
- Resetting transactions.
- Responsive behavior.
- Accessible labels and controls.

Test group F — Regression

Run the existing project test suites.

Confirm that introducing the public advisor does not break:

- The private calculator.
- Existing valuation calculations.
- Existing League Hub pages.
- Draft pick functionality.
- IDP functionality.
- Current source integration.
- Existing navigation.

If refactoring shared evaluation services, prioritize regression coverage for the old behavior.

---

PHASE 16 — PERFORMANCE

The public advisor should feel responsive.

Avoid recomputing the entire global valuation model unnecessarily for every public request.

Reuse existing authoritative snapshots and calculation infrastructure where possible.

However:

Never substitute stale or simplified values solely to improve speed.

Measure the relevant performance costs.

Optimize:

- Roster fetching.
- Asset filtering.
- Asset sorting.
- Trade submission.
- Server-side evaluation.
- Response rendering.

Keep public API responses small.

Avoid sending large internal data structures when the frontend only needs asset names and identifiers.

---

PHASE 17 — IMPLEMENTATION SAFETY

Preserve all existing project functionality.

Before major changes:

1. Identify the relevant files.
2. Review existing architectural conventions.
3. Determine the smallest maintainable implementation.
4. Establish or extend tests.
5. Implement shared evaluation access.
6. Implement secure public endpoints.
7. Implement the frontend.
8. Integrate routing.
9. Run regression tests.
10. Review the final diff.

Do not perform a sweeping rewrite of unrelated calculator components.

Do not replace established valuation infrastructure simply because a new structure seems easier to implement.

If shared engine extraction is necessary, refactor carefully and preserve existing behavior.

Follow current repository conventions for:

- TypeScript and type safety.
- API architecture.
- Component organization.
- Error handling.
- Testing.
- Environment variables.
- Data fetching.
- Deployment.

Do not introduce unnecessary dependencies.

Do not modify unrelated pages.

---

PHASE 18 — REQUIRED DELIVERABLES

I want this feature implemented, not merely described.

Complete the following:

Deliverable 1 — Architecture audit

Summarize:

- Where the private trade calculator runs.
- Which services provide valuations.
- Which methods evaluate trades.
- Which components and endpoints can be reused.
- How the public interface will securely access the same engine.

Deliverable 2 — Working Trade Advisor

Implement the complete public interface.

Deliverable 3 — League Hub integration

Make the Trade Advisor the default League Hub landing page.

Deliverable 4 — Live roster integration

Populate all eligible assets from actual league ownership.

Deliverable 5 — Multi-team support

Implement two-, three-, and four-team trades.

Deliverable 6 — Secure backend

Ensure all private calculation data stays behind the appropriate server-side boundary.

Deliverable 7 — Recommendation system

Provide clear, directional recommendations derived from the authoritative private calculator.

Deliverable 8 — Automated tests

Add and run all applicable tests.

Deliverable 9 — Security verification

Confirm that no proprietary valuation data is exposed through public client responses or bundles.

Deliverable 10 — Final implementation report

Provide:

- Summary of work completed.
- Files created.
- Files modified.
- Shared calculation services used.
- Public endpoints introduced.
- Tests added.
- Tests executed and results.
- Security protections implemented.
- Any remaining limitations.
- Deployment considerations.
- Commit identifiers and pull request links, if applicable.

---

PHASE 19 — ACCEPTANCE CRITERIA

Consider the feature complete only when all of the following are true.

A. Landing page

Clicking Go to League Hub opens the Brisket Trade Advisor.

B. Team selection

The user can select any eligible league team as the evaluation perspective.

C. Real rosters

The correct players and draft picks appear for each selected team.

D. Sorting

Players can be sorted by internal value without revealing the underlying numbers.

E. Multi-team support

Two-, three-, and four-team trades work correctly.

F. Accurate evaluation

The advisor uses the exact same applicable evaluation logic as the private calculator.

G. Value Adjustment

Our current active Value Adjustment is included wherever applicable.

H. IDP

Offensive and defensive players are supported correctly.

I. Recommendations

The user receives a simple and consistent recommendation from the selected team's perspective.

J. Privacy

No proprietary valuation numbers, formulas, or source information are transmitted to the public frontend.

K. Automatic updates

Changes to the authoritative calculator logic affect subsequent public evaluations without independent public calculator maintenance.

L. Mobile

The complete workflow is usable on a phone.

M. Existing features

The private calculator and other League Hub functionality continue working.

N. Testing

Relevant automated tests pass.

O. Security

Public endpoints are validated, rate-limited appropriately, and constrained to explicitly permitted response fields.

---

FINAL INSTRUCTIONS

The central philosophy is simple:

GIVE LEAGUE MEMBERS THE INTELLIGENCE, NOT THE DATA.

The private trade calculator is the authoritative system.

The public Trade Advisor is a restricted interface to that system.

The private calculator can continue displaying all its detailed values, calculations, sources, and other advanced analytics to authorized users.

The public advisor should not.

A new manager should be able to:

1. Open the League Hub.
2. Select their team.
3. Select a trade partner.
4. Choose the players and picks involved.
5. Click Analyze Trade.
6. Receive a clear recommendation.

They should never need to understand player value scales, source weighting, aggregation, package adjustments, or any of the mathematical machinery powering the recommendation.

At the same time, the resulting recommendation must be as reliable as an evaluation performed by our existing private calculator.

Do not compromise mathematical parity to simplify the interface.

Do not compromise proprietary data protection to reuse frontend code.

Do not create a second valuation engine.

Do not expose private values through public API responses.

Do not break the existing calculator.

Do not stop at a plan or mockup.

Audit the existing repository, implement the feature using its actual architecture, test it thoroughly, and deliver a production-ready Brisket Trade Advisor.

Proceed with implementation.
