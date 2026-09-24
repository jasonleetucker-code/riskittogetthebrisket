# Calculator — UI Implementation Contract

**Status:** binding implementation contract for existing Lane 6 / Premium UI.
**Owner directive:** 2026-09-24, #1421.
**Design authority:** `docs/PREMIUM_SPORTS_INTELLIGENCE_DESIGN_NORTH_STAR.md`.
**Execution authority:** `docs/EXECUTION_PLAN.md`; this is not a second authorization record.
**Completion front door:** Calculator Ideas, `docs/BRISKET_IDEAS.md`.
**Operational ledger:** `docs/ui/UI_PARALLEL_LEDGER.md`.

UI policy: ALWAYS_PARALLEL_UNTIL_UI_COMPLETE

The North Star defines what the product should look/feel like. This implementation
constitution defines how agents realize that already-approved decision. No design
exploration is authorized. Keep the historical BRISKET_IDEAS.md filename; the project
is Calculator and its owner-facing full completion portfolio is Calculator Ideas.

## 1. Continuous parallel execution

**Lane 6 / Premium UI is an always-active parallel lane through Calculator completion.**
Preserve its UI, frontend, performance and accessibility ownership and existing C8-U1
(performance), C8-U2 (premium design system / migration) and C8-U3 (accessibility).
Do not create a duplicate program or change unrelated scope or completion denominators.

Every substantial implementation batch, next reasonable batch, next ten Calculator
Ideas, parallel-batch recommendation and fresh-session prompt must include useful UI
work or explicitly reference an adequately staffed active UI lane. Backend-heavy new
ideas cannot make UI disappear from the full completion portfolio.

The batch shape is FOUNDATION / BACKEND (canonical data/model/feature owners) + UI
(dependency-safe foundation or frontend consumer) + INTEGRATION (stable contract
connection, E2E and production proof). UI need not touch the same feature when that
would cause rework. Where the frontend contract is stable, advance it with the feature.

When an existing lane covers the batch, say `UI lane already active: <issue/PR/work claim>`
and explain coverage. An old branch, queued handoff or historical dispatcher snapshot
is not evidence of an active worker. Label queued reservations honestly.

A sufficiently stable canonical contract is required for a route's final migration.
An unstable route contract blocks only that route's final wiring, not the UI program.
Move to shared tokens/primitives, shell/navigation, mobile, accessibility, performance,
tables/search/filters/charts/player identity, loading/error/stale/empty/partial states,
visual testing, migration inventory, proven legacy retirement or another stable route.
Do not say all UI is blocked unless every remaining task has an evidenced unresolved
owner/external blocker. Name the individual blocker and select the next safe ledger unit.

## 2. Locked authority / no aesthetic discretion

For UI decisions use, in order: newest explicit owner UI instruction; PSI North Star;
this contract; approved PSI production reference routes; DESIGN-SYSTEM.md and semantic
token contract; current ds primitives; legacy implementation. Current code can disprove
stale implementation-status claims but cannot override a newer owner design decision.
Historical freeze records remain traceable with dated supersession pointers.

Agents must not independently choose palette, fonts/type scale, radii, shadows, spacing,
breakpoints, chart palette, navigation, density, card-versus-table philosophy, movement
colors, buttons, badges, player presentation or mobile information architecture.

Decision tree: implement the explicit owner instruction; otherwise the North Star;
otherwise this contract; otherwise the closest approved PSI reference; otherwise the
applicable shared primitive. If a genuinely new visual decision remains, mark
**OWNER UI DECISION REQUIRED** and stop only that decision, continuing other safe work.
Engineering problem solving is allowed; becoming the art director is not. “I thought
this looked cleaner” does not justify deviation or a new design language.

## 3. Product feel and absolute anti-goals

Every migrated surface must feel like a premium football personnel and market-
intelligence system for serious dynasty managers: professional-sports identity,
editorial authority, front-office credibility, dense but calm information, strong
numerical/type hierarchy, tabular numerals, restrained chrome, thin rules/alignment,
minimal radii, disciplined color, purposeful player imagery, explainability and speed.
It is an application, not a sports-news site, generic SaaS/AI dashboard or KTC clone.
Do not copy KTC's visual design.

Do not introduce excessive/nested rounded cards, large radii, ubiquitous pills, default
shadcn/Tailwind dashboard styling, glassmorphism, purple/blue AI gradients, glow, blobs,
decorative shadows, icon saturation, one tile per number, manufactured whitespace,
marketing heroes inside tools, card grids replacing desktop tables for convenience,
generic startup visuals or superficial recoloring of unchanged legacy composition.
Organize with typography, rules, alignment, grouping, spacing rhythm and restrained
surface differences. Use desktop space efficiently without hiding useful information.

## 4. Exact semantic styling owner

Use the existing `.psi-editorial` scope in `frontend/app/tokens.css`, not a second DS or
an indiscriminate whole-app theme flip. Approved values belong only in that token owner:

| Role | Token | Approved value |
|---|---|---|
| Page canvas | --surface-0 | #f2ebdd |
| Panel | --surface-1 | #faf6ec |
| Nested / input / raised | --surface-2 | #e9dfca |
| Overlay | --surface-3 | #ffffff |
| Primary ink | --text-primary | #1c1712 |
| Secondary ink | --text-secondary | #4a4136 |
| Tertiary ink | --text-tertiary | #6b6151 |
| Strong structural rule | --border-strong | #1c1712 |
| Identity / interactive accent | --accent | #a3341c |
| Hover | --accent-hover | #8c2c17 |
| Pressed | --accent-pressed | #752312 |

Components consume semantic --surface-*, --text-*, --border-*, --accent* and state tokens.
Never copy raw colors into component/page CSS. No arbitrary spacing/radii/shadows,
new breakpoints, z-index values, type sizes or page-local semantic colors.

Burnt red is the single identity/interactive accent: primary action, selected state,
eyebrow, active sort and intentional emphasis. Not decorative washes or every border,
icon and number. Movement is not success/failure: preserve --data-up* blue + up arrow
and --data-down* orange + down arrow, never color alone. Genuine positive/negative
system states retain their state semantics; falling dynasty value is not an error.

Use --radius-1/2/3 for approximately 2px controls/tiles and 3px panels/modals. Full circle
is for real dots/round indicators. No new 8/12/16px card variants. Shadows belong to
actual overlays (popover, modal, drawer, elevated menu); normal sections/tables/panels/
stat regions rely on surfaces, borders, spacing and typography.

Canonical breakpoints are 480, 768, 1024 and 1320. These documented media-condition
literals are allowed; do not invent 640/900/1180 or copy legacy exceptions merely to
avoid responsive composition. Fixed plot/image geometry is not a breakpoint.

## 5. Typography, density, hierarchy and desktop tables

Use existing editorial/display authority, legible UI typography and tabular numerical
roles. --font-display already exists: no new/downloaded font without a newer owner
instruction. Reuse the approved token scale/reference routes, not stale values in old
docs. Comparable numbers use tabular numerals and consistent alignment, normally
right-aligned in numerical table columns rather than centered for symmetry.

Dense but calm is the requirement. Hierarchy comes from typography, grouping, rules,
alignment and restrained surfaces, not giant gaps. A data-heavy private page generally
orders page identity/context -> primary decision/key state -> primary workflow -> why/
explainability -> supporting market/roster/source evidence -> secondary detail. Do not
bury the action under analytics or a marketing introduction.

Rankings, source comparisons, player lists, transaction ledgers and trade assets belong
in dense tables/aligned rows, compact identity and expandable detail, not huge card grids.

## 6. Mobile parity and unambiguous identity

Mobile is the same product, not a summary-only version. Preserve canonical calculations
and core workflows: asset search, trade construction, player/pick selection, totals,
Value Adjustment, balance suggestions, real-trade comparisons, charts/analytics,
before/after roster impact, filters/sorting, explainability, source states and actions.
Presentation may change; capabilities may not silently disappear.

Keep identity, the key decision number, verdict/state and primary action immediately
visible. Secondary fields remain accessible through expansion, secondary rows,
controlled horizontal table regions or drilldown drawers. Do not hide important columns
without a path to them. Do not clip player names into ambiguity. Owned picks preserve
owner/year/round identity where needed; generic quantities remain understandable.

## 7. One navigation model / correct app shell

`frontend/lib/nav-model.js` remains the single IA. Desktop top nav and mobile top bar,
tab bar and menu/drawer render the same product with shared route/capability gating,
not two products. Preserve skip-to-content, main landmark, route focus management,
auth-aware navigation, public/private boundaries, command/search, mobile chrome and
stale-data communication. Visual simplification cannot weaken auth or accessibility.

## 8. Shared primitives, charts, imagery and gallery

Reuse existing shared buttons/inputs/selects/segmented controls/tabs/panels/tables,
player rows, badges, movement/confidence/freshness, loading/empty/error states,
modals/drawers, charts/tooltips/filters/pagination. Extend an approved shared primitive
under a claim rather than fork a page-local version. Portals must retain the approved
scope; do not assume a page-root scope reaches body-level overlays.

Charts preserve existing semantic palette, fixed CVD-safe series order, labels/tooltips,
accessible descriptions and responsive rendering. No rainbow charts or color-only
critical meaning. Preserve the supported categorical limit/Other grouping; do not
repaint surviving series after filters. Verify contrast on actual plot surfaces rather
than repurpose a dark-theme validation claim for every light plot.

Player imagery is selective, purposeful and subordinate to data/identity/hierarchy,
not decorative wallpaper or giant cutouts everywhere. Follow approved reference use.

`/design` is a living implementation/test reference, not a product page. Keep it current
for every introduced primitive, variant/state, type role, table/movement/confidence,
loading/empty/error and responsive pattern. Isolated deterministic gallery/test fixtures
are allowed and labelled; they must not become fake production decision data.

## 9. Visible speed and truthful data states

Keep useful current content while refreshing, use local pending states, skeletons only
without useful prior content, progressive sections and stable dimensions. Avoid global
spinners for local changes, flash-to-empty, jumping layouts or blocking an entire route
on a secondary request. Do not make a fast application feel slow.

MISSING IS NEVER ZERO. Distinguish loading, unavailable, missing, stale, degraded,
partial coverage and actual zero. A clean component is not a reason to hide source
limitations or present a stale source as current. Fetch freshness is not content freshness.
No production route may use hardcoded fake data to look finished: use an honest
unavailable/degraded state or an appropriate feature gate when a live contract is absent.

## 10. Explainability and canonical ownership

Calculator must be fast, clear, actionable, explainable, consistent and mobile-friendly.
Values, ranks, edge, confidence, verdicts, adjustments and recommendations need a path
to meaning, movement reasons, contributing evidence and missing/degraded inputs. Use
progressive disclosure, not permanent diagnostic clutter.

The UI consumes/displays/interacts/explains and filters/sorts only where semantically
safe. It must not create parallel owners for player/pick valuation, trade math, Value
Adjustment, Team Strength/Weakness, lineup/replacement/scoring, FAAB, projections,
freshness, confidence or market verdicts. Connect canonical owners rather than recompute.

## 11. Trade Calculator — locked workflow

Trade is a primary private workflow. Its mature experience supports clear Side A/B,
optional supported 3+ participant/destination identity, players, owned picks, repeatable
generic assets, duplicate-looking uniquely owned picks, raw/adjusted totals, amount-to-
even, fairness/verdict, balance suggestions, real-trade comps, before/after roster and
position impact, uncertainty/risk, market/source context and shareable state. Do not
scatter the evidence for one proposed trade across unrelated pages.

Asset selection distinguishes player, unique owned pick, generic pick and repeated
asset. Two distinct owned picks may both say Mid 2027 1st; both remain selectable.
Generic assets may repeat, but the same unique owned pick cannot accidentally count
twice. Do not use display label or asset type as unique identity. Removing one generic
copy leaves the other; share/persistence/equalizer integration preserves every valid
quantity/identity. Quantity UX cannot hide ownership. Canonical math counts copies;
the UI must not introduce a replacement valuation or serialization owner.

Prioritize who gains/whether balanced, totals, delta/amount-to-even, applicable Value
Adjustment, roster impact and confidence. Sources/comps/charts/secondary analytics go
below or behind disclosure. Preserve latest owner override/reset privacy requirements
where applicable, without corrupting canonical value or pretending edited values are
canonical source observations.

Backend trade engine and Trade UI are distinct parallel lanes. Asset picker/quantity
UX/owned-pick identity/mobile/hierarchy can advance on stable contract portions and
shared primitives before every trade feature is complete. Final connection belongs to
Integration with canonical contract and E2E proof.

## 12. Rankings, universal player, Waivers and league state

Rankings and Universal Player Profile are early canonical PSI reference experiences.
Reuse their typography, spacing, surface/rules, headers, identity, controls and responsive
philosophy. If they disagree, audit against owner/North Star/this contract; personal
preference does not resolve authority.

Rankings retains a real dense sortable table: player identity, rank, canonical value,
position/tier/movement, meaningful confidence/coverage, search/filters and explanation.
Mobile retains identity/rank/primary value/essential movement and access to other detail.

Every player click converges on one canonical experience, not ten competing popups.
Its hierarchy ultimately includes identity, value/rank/tier/confidence, market/history,
BDVM/fundamentals, projections/stats/PAR, roster context, acquisition/holding history,
Sharp, manager/Insider, Analyst Intelligence and factual news through disclosure.

Waivers must relate to Trade: team selection, value-sorted roster, waiver pool,
filters/search/position controls, add/drop selection, clear result/value impact, sources
and FAAB where available. Coordinated desktop panes are allowed; mobile uses intentional
tabs/stacking rather than crammed panes. Preserve workflows and canonical calculations.

League switching/toggles must unmistakably show ON/OFF and stay consistent across
Rankings, Trade, Waivers, profiles, rosters, Finder and future tools. Consume the shared
canonical state/value owner; never secretly fall back to another mode or recalculate
league adjustments in a page.

## 13. Accessibility and performance are shipping gates

Preserve keyboard navigation, visible focus, semantic controls/labels, table/dialog
semantics, aria-current, route focus, reduced motion, non-color cues, accessible charts
and sufficient contrast. C8-U3 requires axe-based CI coverage for migrated references.
A screenshot alone cannot establish accessibility or PSI completion. Test meaningful
populated/interactive states, not only loading skeletons.

Premium UI must not make the app slower. Retain owner targets: useful warm/cached data
<=1s target; normal production p95 <=2s where architectural; supported cold useful path
<=3s preferred; <=5s absolute useful-interactive failure ceiling. Loaded interactions
should feel immediate/local where safe. Inspect JS bundle impact, extra requests, image
size, chart/table rendering, layout shift, hydration and mobile polling. Use code
splitting, pagination/virtualization, prepared imagery, stable skeletons and local
sorting/filtering only when canonical-safe. Measure rather than infer performance.

## 14. Claims, parallel dispatch and required preimplementation audit

Before edits inspect current main, open PR changed files, issues/active branches,
WORK_CLAIMS and canonical planning/contracts, current design implementation/reference
routes and legacy. Claim exact frontend/docs/ui/tests/evidence paths. Do not have two
writers on globals.css, package.json, data_contract.py or server.py; shared edits need
custodian/Integration coordination. Backend agents coordinate UI coverage, not invade
another lane's files. Prefer separate UI branches and disjoint paths.

Before substantive code, report current PSI foundation, active work/PRs/claims,
migrated/partial/legacy routes, DS/mobile/a11y/performance gaps, Trade state, governance
files and the next safe unit. Evidence reconciles decisions versus implementation;
it is not a request to reopen the art direction.

After governance is committed, identify actual UI staffing/claims and start the highest-
priority dependency-safe unit if none is active. Prefer broadly unlocking foundations,
legacy-debt retirement, Trade UX, stable major routes or broad mobile/a11y/performance,
not issue-number order. If separate workers are supported, dispatch a separate branch.
Otherwise supply an exact issue, queued work claim, branch and fresh-session prompt;
never say a queued handoff is running. Documentation alone does not complete delivery.

## 15. Migration order, ledger and legacy retirement

Preserve the approved order unless dependencies justify a bounded reorder: shared PSI
foundation; shell/navigation; Rankings; Universal Player Profile; universal search/
command; Market + Sharp/Insider; Trade Analyzer/Finder/Package Builder/Trade Desk;
Team Strength/Weakness/roster/league intelligence; Draft/Waivers/Game Day/probability/
remaining tools; final legacy retirement. Independent stable routes may run concurrently.

No big-bang 150-file redesign or blind globals.css rewrite. Migrate route by route,
reviewable and reversible during development, responsive from day one, with data/
behavior parity, measured performance/a11y, visual evidence and explicit retirement.
Move consumers to tokens/DS, prove parity, then remove unreachable legacy selectors.
Do not delete styles before consumer retirement or add fresh legacy selectors to PSI.

The UI Parallel Ledger tracks route/surface, family, canonical backend owner, contract
stability, PSI migration state, desktop, mobile, accessibility, performance, legacy CSS,
visual proof, active claim/PR, dependency and next action. Map to existing planning/
integration taxonomy; never create a competing completion scoreboard. Source code is
not production/visual proof, and absence of fresh evidence is recorded as unverified.

## 16. Verification and completion

Governance: run current planning integrity, docs tests, WORK_CLAIMS checks and L0.
Frontend: current Vitest, build/bundle gates, lint only if actually enforced, route E2E,
axe/keyboard, visual review, responsive viewports and appropriate performance checks.
Read current repository commands rather than inventing outdated ones.

Every migrated production route needs desktop and phone screenshots. Add tablet,
interaction/loading/error/stale states where useful. Use existing Playwright/evidence
conventions and record exact SHA, URL, viewport, state, timestamp and result. DOM tests
are not visual verification; local/CI screenshots are not production verification.

After deployment inspect the actual production route: desktop/mobile, navigation,
primary workflow, canonical data, loading/refresh, stale/error, keyboard/focus, console,
layout shift and public/private gates. Respect credentials and protected deployment;
unavailable access is an explicit unverified gate, not inferred success.

PSI-complete requires correct canonical data and behavior, faithful visuals/shared
primitives, desktop/mobile parity, keyboard/a11y, loading/empty/error/stale/degraded
states, measured performance, no duplicate business math or needless requests, actual
deployment, screenshots/owner-review evidence and legacy-path retirement. Right colors
alone are not completion. Backend complete / UI incomplete = product incomplete.
Calculator Ideas tracks capability and UI as two dimensions of one product, without
double-counting scope; major legacy routes prevent declaring the full site complete.

## 17. Durable enforcement and handoff

Extend scripts/check_planning_integrity.py with small structural checks for this
contract/ledger, active planning pointers and the UI-batching rule; deletion/mutation
tests must prove these guards fail. Do not build a fragile prose-regex system. Such
checks cannot prove actual worker activity, aesthetics or deployed acceptance.

Use docs/ui/UI_IMPACT_TEMPLATE.md and the PR template for material product changes:
UI impact, existing lane or new parallel unit, route blocker/other active task, PSI
reference, mobile, accessibility, performance and visual evidence. Tiny maintenance
may explain no UI impact without paperwork; substantial planning still covers Lane 6.

Final report: governance files; permanent rule; contract; ledger; enforcement; current
migration status; active lane issue/branch/claim/dependency; next unit; exact tests;
PR/deployment status. Distinguish selected, implemented, tested, merged, deployed and
verified. Keep the UI program active until genuine completion is evidenced.
