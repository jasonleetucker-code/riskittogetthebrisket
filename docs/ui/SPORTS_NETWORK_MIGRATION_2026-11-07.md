# Sports Network frontend migration — November 7, 2026

**Existing Lane 6 acceptance/evidence record.** Owner continuation: “continue until its fully implemented,” after review of the working Sports Network references. Execution authority remains `docs/EXECUTION_PLAN.md`. No new product backlog or completion denominator.

## Approved outcome and compatibility

Implement the reviewed Sports Network identity across the active frontend: navy broadcast masthead, condensed Barlow headlines, readable Plex interface/data/prose, coral emphasis, selective gold and cream research/editorial surfaces. Distinct task compositions, no card-wall terminal template. Sunday Paper remains subordinate.

Use current React/Next architecture and canonical components. Keep existing route names/menu reachability, auth/capabilities, public/private semantics, commands, team/league context, specialist/hidden/paused workflows, backend values/ranks/history, transforms, sorting/filtering/export, data freshness and attribution. Do not ship prototype fixtures or fictional generated player art. No model, source, backend, package/framework migration or flag activation.

## Units and owners

- **Foundation / coordinator:** canonical tokens, font assets and loader, legacy aliases, shared display/table/chart/control consistency; Rankings composition over its current data path; route inventory and global validation. One writer for shared foundations.
- **Shell worker:** existing navigation/model consumers and mobile chrome presentation only; preserve all access and interaction behavior.
- **News worker:** newsroom presentation over shared `useNews`/news-service and backend digests; retain every existing facet/tab, real source/date/identity semantics and explicit failure states.
- **Player worker:** asymmetric personnel dossier over current row values, shared PlayerPopup research sections and real history/explanation endpoints; preserve lazy sections and missing states.
- **Integration:** dependency-ordered coherent PRs, independent review, exact-tree checks and current release safety gates. Presentation code is not production verification.

## Acceptance and route coverage

Regenerate the current route inventory rather than assuming the November 1 count is still current. Every active route must consume the single canonical brand/type/color foundation; route-specific sections must remain appropriate to its actual task. Flagged-off, self-authenticated, unlisted and public routes retain their access/activation class.

Required evidence: current route/access/feature inventory; source → API → real live component maps for flagship screens; representative populated/loading/empty/missing/stale/unavailable flows; retained feature tests and semantic invariants; desktop 1440, tablet 768 and phone 390 renders; keyboard/focus/contrast/axe and reduced-motion checks; build, bundle/privacy budgets, query/interaction performance and regression checks. Data/model tests remain intact. Public artifacts must use approved synthetic/sanitized test sessions only, never real private production data.

The global token/type migration must reach both current semantic components and legacy aliases. Maintain validated chart semantics/CVD distinctions and text contrast. A cream scope cannot inherit dark-calibrated chart/text colors. Shared dark masthead/hero regions explicitly scope their own readable inverse tokens.

## Engineering applicability

**APPLY_NOW:** stable canonical contracts, deterministic UI fixtures, source/route traceability, regression journeys, font/image provenance, accessibility, build/bundle privacy, resource bounds and local performance. **ALREADY_COVERED:** existing auth, single-flight data/news hooks, exact scoring/value owners, established component/test architecture. **NOT_RELEVANT:** database migrations, source ingestion/parser changes, model experiments or new agent infrastructure. **DEFERRED_BY_AUTHORITY:** consequential model/source/flag promotion and bypassing Integration/release safety.

## Implementation and evidence — November 8

Implementation source: `5cf6b892a` (last change distinguishes unavailable News roster coverage from zero); full-suite source `c40ad6987875b99d53ac91efef6fdbafa17c52aa`. Integration/deployment remain separate, unverified states until their actual receipts exist. The independently reviewed prototype is draft PR #2132; the historical owner charter is [open #2112](https://github.com/jasonleetucker-code/riskittogetthebrisket/pull/2112), file `docs/owner/FRONTEND_EXPERIENCE_REBUILD_RESEARCH_CHARTER_2026-11-07.md` on that proposal. Its original prototype-only boundary is superseded by the explicit continuation captured in the execution plan. This record is linked through the existing UI ledger and owner intake.

### Live execution and contract mapping

| Surface | Actual path and canonical owner | Retained behavior |
|---|---|---|
| Rankings | `app/rankings/page.jsx` → `useDynastyData` → `lib/dynasty-data.js::fetchDynastyData` → `/api/dynasty-data`, custom-mix delta endpoints → existing backend `src/api/data_contract.py` | Canonical values/ranks; league-aware server transforms; query, positions/NFL team/confidence/lens/screens; numerical sorting; filtered CSV/copy; column configuration; source audit; player popup/profile convergence. Research is lazy until opened, then retained. |
| Player File | `app/players/[playerId]/page.jsx` → AppShell canonical row; shared `PlayerPopup` research sections; `PlayerRankHistoryChart` → `/api/data/player-source-history`; existing lazy value explanation | All five tabs, watchlist, comparison, trade handoff, actual ownership, realized points, source/rank history and missing states. Related profiles use canonical `playerProfileHref`. No invented fallback history. |
| News Desk | `app/news/page.jsx` → `useNews` → `lib/news-service.js` → `/api/news` and existing digests | By-player/stories views, roster/league/all scope, query/team/position/source facets, source attribution and date, popup identity links, explicit unavailable/retry behavior. Manual stationary wire, no new feed or polling owner. |
| Shell | RootLayout → AppShellWrapper → TopBar / MobileChrome / NavMenu → unchanged `NAV_MODEL`, auth/capability and public-route owners | One navigation model, existing reachability/gates, league/team context, search commands, keyboard/focus, skip link, mobile tab/menu behavior. |
| Public / other tools | HomeClient and LeagueClient retain existing public contract/advisor bootstrap; all routes inherit root tokens, local fonts, DS and legacy aliases | Public/private separation, lazy league sections and section URL, existing specialist workflows, data calculations, paused/hidden flags and server capabilities. No activation. |

The existing inventory contains **61 page routes**, matching **61 `app/**/page.jsx` files**. `route-inventory.test.js` verifies exact coverage/access classifications. No new route, API contract, provider or frontend calculation was introduced. Root/compatibility scopes share one cream foundation; inverse regions are explicitly scoped. Historical >6-category chart hue/order is held, with an inverse navy plotting surface where required; this is not a new categorical palette or fold algorithm.

### Design specification

- Navy `#0b2130`, coral `#fd633f`, cream `#f0eddf`, selective gold `#f7c77f`; use dark coral `#a3341c` for small accent text. Bright coral controls use navy text.
- Local Barlow Condensed bold Latin (27,480 bytes) for broadcast display; IBM Plex Sans variable Latin (84,116 bytes) for UI/prose/data. OFL notices are adjacent in `app/fonts/`; no runtime font service. Existing monospaced fallbacks remain available.
- Table-first Rankings, asymmetrical navy Player identity/value feature and history-first research, coral News priority rail with cream reading space. Rectangular controls, sharp dividers, restrained surfaces; no persistent animation added.
- Header heights follow desktop/tablet/mobile shell geometry. Route focus uses pathname identity and `preventScroll:true`, leaving Next responsible for scrolling/restoration. Full refresh does not spuriously focus/scroll main in Strict Mode.
- Mobile tools use one disclosure and one set of actions. Secondary data remain reachable. Contrast text shades are separate from chart/position mark colors. Recovery, frozen table cells and horizontal comparison regions receive the same accessibility treatment as populated screens.

### Concrete critique and revisions

| Screen | Observed shortcoming | Revision / retained limit |
|---|---|---|
| Rankings | Secondary Edge/mover research displaced the table. | Default-collapsed Market research; children mount on first opening and retain state. |
| Rankings | Mobile export/source/methodology actions competed with the heading. | Board tools disclosure preserves one copy of all controls. |
| Rankings | Six summary metrics consumed too much phone height. | Compact label/value rows retain every count and freshness footnote. |
| Rankings | Raw headings/frozen cells inherited dark literals against dark semantic text. | Semantic opaque cream header/cell surfaces; independently measured 6.21:1 header contrast. |
| Rankings | Focus could scroll the title beneath sticky chrome. | Pathname guard/preventScroll fix; load → profile → Back browser regression. |
| Rankings | Changed clock wording broke truthful scrape-vs-build expectations. | Retained canonical clock prefix and distinct build/scrape labels. |
| Player | Legacy identity/value layout lacked an authored dossier hierarchy. | Asymmetric real identity/portrait/value hero; history-first overview and peer rail. |
| Player | Inverse hero controls inherited a cream-context focus ring. | Explicit gold inverse focus treatment. |
| Player | Mobile decorative position lettering measured 1.62:1. | Readable muted inverse lettering; subsequent phone axe passes. |
| Player | A related-player link bypassed the canonical destination builder. | Canonical `playerProfileHref(peer)`; identity guard passes. |
| Player | Missing ownership coverage could appear equivalent to unrostered. | Coverage unavailable remains explicit, with no invented ownership. |
| Player | Dark-calibrated source marks/axis context did not fit the cream migration. | Contextual SVG text and scoped inverse legacy-series plots; geometry/gaps/math unchanged. Local history can genuinely be unavailable. |
| News | Equal-weight feed boxes lacked lead/priority/reading hierarchy. | Actual lead report, coral priority rail, source/date metadata and quiet reading area. |
| News | Coverage labels risked confusing stories, digest players and sources. | Counts follow their actual service units and represented providers. |
| News | Roster label was an invalid sibling inside a definition-list group. | Label nested inside the corresponding definition; zero axe definition-list violations afterward. |
| News | Shared team label collided with the player identity static guard. | Explicit `rosterLabel` presentation variable; player links retain their shared owner. |
| News | A long priority rail vertically centered the lead below the fold. | Top-align lead content independently of rail height. |
| News | Generic dark control/reading treatments competed with editorial hierarchy. | Shared cream control tokens, divided digest reading area and stationary manually navigated wire. |

Wider review also repaired: pull-to-refresh/error recovery contrast, public Superlatives wash, comparison-stat/search surfaces, semantic public win/loss copy, Team Strength position-label shades (independent minimum **4.54:1**, eight groups; swatches unchanged), Draft action-column name and heading order, unique Trade summary region name, unavailable-state heading order, and keyboard-focusable horizontally scrolling comparison tables.

### Capability classification and limitations

- **Functional real-contract behavior:** production routes, canonical filtering/sorting/export/navigation, original Player research tabs, News facets/digests/source links, shell context and public league sections. These use the checked-out local backend, not prototype fixtures.
- **Functional fixture behavior / simulated research:** only isolated `prototypes/sports-network` in draft #2132. Its synthetic trade scenarios/confirmation classes never enter this production runtime.
- **Unavailable dependency:** missing local player source-history snapshots remain an explicit unavailable chart; partial public section/backend data and stale snapshots remain labeled. Browser scans do not manufacture a populated history, authentication capability or missing result.
- **Proposed production integration:** frontend integration is implemented in this branch but merge/deployment/field verification require actual Integration/release receipts. Confirmation intelligence or a new fairness/forecast engine is not claimed.

### Validation protocol and reproducibility

Node 20.20.2, Next 16.4.3, React 19.3.1; existing Vitest/Testing Library, Playwright and axe. No package manifest, lockfile or backend source changes in this program. Current main correctness updates were reconciled in `1ec46dbb0`; subsequent main movement is an Integration freshness classification, not permission to change data semantics.

- `cd frontend; npx --yes --package=node@20 node node_modules/vitest/vitest.mjs run --maxWorkers=2`: **430 files, 5,536 passing tests, 3 expected failures; 396.46 s**, full-suite source `c40ad6987`. Final CSS-only refinement is separately rendered/scanned; exact PR CI must cover the final head.
- `cd frontend; npx --yes --package=node@20 node node_modules/next/dist/bin/next build --webpack`; then `node scripts/check-bundle-sizes.mjs` and `node scripts/check-public-bundle-privacy.mjs`: final source results in the machine receipt below. Budgets were not raised; Source Disagreement SVG code was split, and duplicated League metadata/navigation copy removed.
- Existing `tests/e2e/specs/psi-rankings-player-a11y.spec.js`: **8/8** on the built app, covering semantic populated board, sorting/focus, popup focus return, all Player tabs/axe, roving keyboard tabs, deep link and reduced motion; includes new sticky-header focus regression. Environment: `E2E_BASE_URL=http://127.0.0.1:8200`, `E2E_PAGE_ORIGIN=http://127.0.0.1:3200`, local test secret read from ignored runtime file. A local transparent `/api/**` proxy reproduces production nginx routing to FastAPI; it returns actual responses, never fixture substitutions.
- 1440/768/390: Rankings, Player File and News (nine screenshots), plus Scoring Comparison. Wider family scan: 1440/390 × Home, League, Trade, Team Strength, Draft, Compare Players, Waivers, Settings, Source Disagreement, Package Builder, Trade History and the existing Roster Construction gated/unavailable response. Full results and source receipt: `evidence/SPORTS_NETWORK_MIGRATION_2026-11-08.json`.
- Independent read-only source reviews: worker cross-reviews plus independent integration review at `c40ad6987`; 58 focused tests, 67 foundation/shell tests, 55 contrast/team-strength/trade-layout tests. No source blocker identified within the stated scope; full production release remains unverified.
- `python scripts/check_planning_integrity.py`: passed. `git diff --check`: passed. Route/access inventory test is in the full frontend portfolio. Runtime diff contains no backend/models/auth/source/config/activation changes, and preserved Claude checkout is untouched.

The loopback **built app** is `http://127.0.0.1:3200`; isolated demonstration remains `http://127.0.0.1:3100`. Private real-snapshot screenshots stay under ignored `.agent-runtime/built-browser/` (nine flagship images named `{rankings,player,news}-{1440,768,390}.png`), wider scans under `.agent-runtime/family-browser/`. Do not publish those images or session credentials. The checked-in JSON contains only route/access metadata, measurements and count-based scan findings. Prototype synthetic imagery remains separately reviewable in #2132.

Local performance numbers are measured separately from the intentional 1.6-second settling wait in screenshot probes; screenshot `usableMs` values are **not** load benchmarks. See machine receipt for navigation/search timings, environment and gaps. No production improvement, INP score or field Web Vitals is inferred from these local measurements.

Agent-OS-Receipt: 741230def70b1c94b9924192ee784bb7241b91a6


Final local measurement: three navigations per flagship route on the loopback production build,
without network/CPU throttling. Median time to the probe’s usable-content/font-ready condition:
Rankings **657 ms**, Player File **664 ms**, News **323 ms**. Search action to settled-board signal:
**172 ms**. These include Playwright dispatch overhead and are not INP or field Web Vitals.
Final implementation `26c5d4092`: build passed115routeentries,19/19 budgets and public-bundle privacy;
39 targeted tests passed after CSS refinement. Final12flagship/comparison scans and24representative
family scans have zero axe violations, page errors and document overflow. Nine flagship screenshots
were inspected visually; phone table density and News lead alignment were revised and rendered again.


Final News review follow-up `631d86e4a` / `5cf6b892a`: label the displayed units as **Player digests**
and **Roster stories**; absent selected-team coverage is unavailable rather than a measured zero.
Regression + News service/player-identity guards: **107/107 pass**, three files. Rebuilt final source:
115routeentries,19/19unchanged bundle budgets and public-bundle privacy pass; refreshed12viewport
scans have zero axe/page errors/document overflow. Screenshot hashes in the machine receipt are
from this final build. Draft review PR: [#2171](https://github.com/jasonleetucker-code/riskittogetthebrisket/pull/2171).

Integration freshness reconciliation `2d88d7fba` merges current-main `5642d192e`: additive roster
metadata (existing totalValue semantics retained), inspected DLF/IDP refreshes and session records.
This is classified as a relevant API dependency move, not assumed benign from automation authorship.
The merge changed no frontend file; frontend tree exactly matches tested/built `5cf6b892a`.
Exact PR CI and deployment remain separate states; do not infer production approval from this draft.
