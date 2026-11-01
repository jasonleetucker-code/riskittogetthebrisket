# UX navigation and information-architecture audit, 2026-11-01

**Contract:** owner directive 2026-11-01, "NEXT MASTER EXECUTION DIRECTIVE", Priority 4 (§4.1–4.12).
**Owner of this workstream:** frontend IA and usability (Lane 6 conventions: PSI / Direction A, no new styling).
**Base:** `origin/main` at `2060fa78a`. Branch `claude/ux-nav-audit`.
**Machine-readable inventory:** [`evidence/route_inventory_2026-11-01.json`](evidence/route_inventory_2026-11-01.json), checked by `frontend/__tests__/route-inventory.test.js`.

This document does not change product scope or planning records. The coordinator maps the defect register (§4) into the roadmap. Every "OWNER" item in §4 and §10 is a proposal, not an implemented change.

Evidence classes used below:

- **CODE**: read from the live source on `main`.
- **LOCAL**: observed on a local production build (`next build` + `next start`) with a test session minted by the repo's E2E harness (`/api/test/create-session`), seeded from `exports/latest/`.
- **PROD-OUT**: observed signed-out on https://chaseupside.com, read-only, 2026-11-01. Signed-in production was not used.

---

## 1. Inventory

61 page routes exist under `frontend/app` (API bridges excluded). The JSON holds every row with name, URL, purpose, audience, access class, user task, status, contextual inbound links and notes. It also holds the derived nav facts: menu group, section, capability, admin-only, palette, mobile tabs, home quick action, signed-out offer and reachability. The test recomputes those facts from `nav-model.js` and `public-routes.js` and fails if the JSON disagrees. The JSON cannot silently go stale.

| Status | Count | Routes |
|---|---|---|
| working: in a menu | 33 | every ungated or available NAV_MODEL / SYSTEM_MODEL leaf (admin Ops included) |
| working: tab / palette, not a menu | 3 | `/` (Home tab), `/login` (signed-out tab), `/market/sharp-people` (palette + contextual; was orphaned, see NAV-01) |
| working: contextual only | 11 | `/players/[playerId]`, `/managers/compare`, `/managers/leaderboards`, `/managers/league/[leagueId]`, `/market/sharp-people/[personId]`, `/admin/sharp-identities`, `/league/franchise/[owner]`, `/league/player/[playerId]`, `/league/weekly/…`, `/league/articles/…` ×2 |
| share_target | 2 | `/league/week/[season]/[week]`, `/league/rivalry/[pair]` (entered from share links and the sitemap; the same content renders inline in the hub) |
| disabled_by_flag | 2 | `/consensus-edge` (capability-gated menu entry), `/roster-construction` (flag off; menu entry arrives with PR #2044) |
| intentionally_hidden | 6 | `/auction` family ×5 (owner-gated launch, own sign-in), `/waiver-wire/r7k4q9m2` (unlisted by owner request) |
| redirect | 3 | `/finder` → `/rankings`, `/intel` → `/league/insider-trading`, `/rankings/[position]` → `/rankings?pos=…` |
| dev_reference | 1 | `/design` |

Access classes come from `public-routes.js`: 11 public, 40 private, 5 self-authed (`/auction*`), 1 unlisted, plus 3 redirects and 1 dev route.

**Naming accuracy.** The naming canon (`__tests__/helpers/naming-canon.js`) already pins nav label = `pageTitleFor` = `<h1>` for 26 routes. This audit found three gaps outside it:

- UX-D09: `/game-day`'s h1 is "This week's matchup". Its "Game Day" label is only the eyebrow, and the route is not in the canon.
- UX-D11: `/tools/trade-coverage`'s h1 is "Trade Coverage Audit", but its nav label is "Trade Coverage". It is admin-only.
- `/market/sharp-people/[personId]` is titled "Sharp profile" under a "Sharp People" mobile title. This is acceptable for a detail page.

**Overlap.** Three clusters answer one user question from several places:

- waivers: Waivers, Waiver Advisor, Weekly IDP Streaming
- "who is mispriced": Fundamental Values, Source Disagreement, Consensus Edge, Arbitrage, Sharp Tracker
- draft prep: Draft Board under My Team, Rookie Board under Rankings, Draft Capital as a hub tab

See §4, UX-P02, UX-P03 and UX-P06.

## 2. Existing hierarchy (before)

One nav model (`frontend/lib/nav-model.js`) feeds every surface: the desktop top bar (`TopBar` + `NavMenu`), the mobile top bar, the tab bar and drawer (`MobileChrome`), the `/more` site map and the command palette. Capability gating (`itemIsOffered`, from `features` on `/api/auth/status`) and the admin filter (`systemItemsFor`) fail closed everywhere.

```
Rankings ▾  Rankings · Trending · Rookie Board · Compare Players · Fundamental Values
News
Trades ▾    Trade Calculator · Package Builder · Arbitrage · Trade History
My Team ▾   Game Day · Team Strength · Waivers · Waiver Advisor[cap] · Weekly IDP Streaming[cap] · Draft Board · Win-now vs Rebuild
Market ▾    Source Disagreement · Consensus Edge[cap] · Sharp Tracker · Sharp Roster Percentage · Trade Database · Manager Intelligence[cap]
League ▾    Hub · Activity · Insider Trading · Scoring Comparison
DFS ▾       DFS Workspace
System ▾    Settings · All destinations · [Ops, admin only] Source Health · ROS Data Health · Trade Coverage · Admin · Model Lab
Mobile tabs: Home · Ranks · Trade · News · Menu      (signed out: Home · League · Sign in · Menu)
Home quick actions: Rankings · Trade Calculator · Waivers · Team Strength
Palette extras: Home
```

Before this change, section headings existed only in the System menu, and only the desktop dropdown rendered them. The drawer and `/more` flattened them away.

### Per-menu answers (the 10 questions)

The answers are condensed. "OK" means no defect was found.

| Menu | Purpose clear? | Labels = page titles? | Right items? | Missing items? | Gated items fail closed? | Order matches task frequency? | Too long? | Mobile parity? | Keyboard / SR? | Dead ends? |
|---|---|---|---|---|---|---|---|---|---|---|
| Rankings | OK | OK (canon) | Rookie Board is draft prep (UX-P03) | — | n/a | OK | OK (5) | OK | OK | — |
| Trades | OK | OK | Trade Database sits in Market (UX-P04) | — | n/a | OK | OK (4) | OK | OK | — |
| My Team | Label opens a league-wide page (UX-P01) | Game Day eyebrow-only (UX-D09) | Win-now vs Rebuild is league-wide (UX-P05) | Roster Construction (#2044, gated) | yes | weekly items first: OK | 7 flat items, no grouping (**NAV-09**) | headings lost on mobile (**NAV-05**) | headings not grouped (**A11Y-02**) | /waivers did not lead to the advisor (**NAV-03**) |
| Market | "where the market disagrees" is fair | OK | Sharp People missing (**NAV-01**) | Sharp People | yes | OK | 6, ungrouped (UX-P06) | OK | OK | Tracker did not link its siblings (**NAV-04**) |
| League | OK | Hub h1 = league name (data-derived, documented) | Scoring Comparison is settings-like | no playoff-odds signpost (**NAV-07**) | Insider Trading private, filtered signed-out | OK | OK | OK | OK | 22-tab hub (UX-D07) |
| News / DFS | OK | OK | OK | — | — | — | — | OK | OK | — |
| System | OK | Trade Coverage label ≠ h1 (UX-D11) | Sharp Identity Review not in Ops (UX-P07) | — | admin-only filter | OK | OK | OK | menu header not a group (**A11Y-02**) | — |
| Mobile tabs | OK | OK | no in-season Game Day tab (UX-P10) | — | signed-out set has Sign in | OK | 5 slots | n/a | 52 px targets OK | — |
| Palette | OK | OK | Sharp People missing (**NAV-01**) | "playoff" found nothing (**NAV-07**) | yes | n/a | n/a | n/a | combobox + listbox OK | — |
| Home quick actions | OK | OK | Game Day missing (**NAV-06**) | — | n/a | OK | 4 | OK | OK | — |
| Breadcrumbs | not used. Deep public-league pages carry "← League home" back-links; deep private pages (Player File, manager subpages) use page-level back-links | | | | | | | | | |
| Account / settings | Settings has no league or team control. Switching is only in the top-bar switchers (UX-D08) | | | | | | | | | |
| Installed iPhone PWA | `start_url: "/"`, standalone. Signed-out launches go to `/auction` (owner choice in `HomeClient.jsx`). The tab bar respects safe-area insets. No manifest `shortcuts` (UX-P09) | | | | | | | | | |

## 3. Proposed hierarchy (after this PR, plus owner proposals)

Implemented in this PR. No URL changed and no top-level section was renamed or moved.

```
My Team ▾   THIS WEEK: Game Day
            ROSTER: Team Strength · (Roster Construction[cap], from PR #2044, lands here unchanged)
            WAIVERS & FAAB: Waivers · Waiver Advisor[cap] · Weekly IDP Streaming[cap]
            DRAFT & STRATEGY: Draft Board · Win-now vs Rebuild
League ▾    Hub ("Standings, power, playoff odds, records, draft capital, recaps"; palette: playoff odds)
Palette extras: Home · Sharp People
Home quick actions: Game Day · Rankings · Trade Calculator · Waivers · Team Strength
Contextual "Related" rows: Waivers → Waiver Advisor, Weekly IDP Streaming;  Waiver Advisor → Waivers;
                           Sharp Tracker → Sharp Roster Percentage, Sharp People;  Rookie Board → Draft Board
```

The same section groups render in the desktop dropdown, the mobile drawer and `/more`. All three use `nav-model.sectionRuns`.

**Fit with PR #2044.** That PR inserts the Roster Construction item between Team Strength and Waivers. This PR touches no line inside that hunk's context. The new item carries no `section`, so it continues the "Roster" run and sits next to Team Strength, which is where §4.6 asks for it. After both PRs land, the route-inventory test will ask for `UPDATE_ROUTE_INVENTORY=1` once, because `/roster-construction` gains a menu entry. That regenerated diff is the IA change for review.

Proposed for the owner (not implemented): UX-P01 to UX-P10 in §4.

## 4. Defect register

Priority uses the directive's order: 1 = missing nav to an active feature, 2 = broken destination, 3 = misleading label, 4 = illogical placement, 5 = mobile defect, 6 = a11y failure, 7 = title/label consistency, 8 = contextual links, 9 = low-risk visual.

| ID | User problem | Intended improvement | Owner component | Routes / components | Pri | Depends on | Acceptance criteria | Status |
|---|---|---|---|---|---|---|---|---|
| NAV-01 | A signed-in user cannot find Sharp People; its only inbound link was on an admin page | Offer it in the palette and contextually from Sharp Tracker; menu promotion is UX-P07 | nav-model | `/market/sharp-people`; `PALETTE_EXTRA_TARGETS`; Sharp Tracker page | 1 | — | Palette finds "Sharp People"; Sharp Tracker links it; inventory reachable = nav | **IMPLEMENTED** (this PR) |
| NAV-02 | Reachability was pinned against a hand-kept route list, so a new page could ship orphaned | Filesystem-derived inventory test: every `page.jsx` classified; working pages must be reachable; derived facts checked | tests | `__tests__/route-inventory.test.js`, inventory JSON | 1 | — | Adding a `page.jsx` without a row fails; an orphaned working page fails | **IMPLEMENTED** |
| NAV-03 | On `/waivers`, nothing says Waiver Advisor or Weekly IDP Streaming exists (dead end for "stream an LB" and "safe drop") | Capability-gated Related row on `/waivers` ↔ `/waiver-advisor` | RelatedLinks (nav-model-derived) | `/waivers`, `/waiver-advisor` | 8 | — | Links appear only when the capability is `available: true`; labels are canon | **IMPLEMENTED** |
| NAV-04 | Sharp Tracker does not lead to its two sibling cohort views | Related row → Sharp Roster Percentage, Sharp People | RelatedLinks | `/market/sharp-tracker` | 8 | NAV-01 | Both links render | **IMPLEMENTED** |
| NAV-05 | The mobile drawer and `/more` dropped section headings that desktop showed, so the same IA read differently per viewport | One `sectionRuns` helper; NavMenu, drawer and `/more` render identical labelled groups | NavMenu, NavLinkList | shell | 5 | — | Drawer shows the same groups as the desktop menu (unit + E2E) | **IMPLEMENTED** |
| NAV-06 | Game Day, the in-season weekly destination, had no dashboard shortcut | Add it first in Quick actions | QuickActions | `/` | 8 | — | Quick actions list Game Day first | **IMPLEMENTED** |
| NAV-07 | "Playoff chances" has no signpost: the Hub hint never mentioned it and palette "playoff" returned nothing | Hub hint and keywords name playoff odds; a deep-link entry is UX-P08 | nav-model | `/league` | 3 | — | Palette "playoff" → League Hub | **IMPLEMENTED (partial)**: still one tab click inside the hub |
| NAV-08 | Rookie Board (Rankings) and Draft Board (My Team) are split with no cross-link | Rookie Board → Draft Board Related link | RelatedLinks | `/idptc-rookies` | 8 | — | Link renders | **IMPLEMENTED** one way. Reverse link deferred: `/draft`'s header heights are CLS-pinned (see §10) |
| NAV-09 | My Team is seven flat rows; the waiver/FAAB tools read as three unrelated entries and "FAAB" appears nowhere | Section headings: This week / Roster / Waivers & FAAB / Draft & strategy | nav-model | My Team group | 4 | NAV-05 | Headings render on all surfaces; a gated-away first item never strands a heading | **IMPLEMENTED** |
| A11Y-02 | Inside `role="menu"`, section headings were bare divs (unowned, unnamed children) | Each section is a `role="group"` labelled by its heading | NavMenu | shell | 6 | NAV-05 | Every child of the menu is a group or menuitem; axe clean on the open menu | **IMPLEMENTED** |
| A11Y-01 | NavMenu lacks Home/End and type-ahead | Add the keys | NavMenu | shell | 6 | — | APG menu keys | DEFERRED (minor) |
| A11Y-03 | On `/waiver-advisor?mode=streaming`, "Weekly IDP Streaming" never shows as current (active matching is pathname-only) | Pass search params into active matching | shell | TopBar, MobileChrome | 7 | needs `useSearchParams` in the shell, which forces a Suspense boundary at the layout level | `aria-current` on the streaming item in streaming mode | DEFERRED (risk to static rendering; needs Lane 6 decision) |
| UX-D07 | The public hub has 22+ tabs. With the advisor off, Overview is labelled "Home", which collides with the site's own Home | Group or rename tabs | public league | `/league` tabs.js | 3 | owner | — | OWNER |
| UX-D08 | Settings has no league or team control; the switchers live only in the top bar (hidden with one league) | A "League & team" row in Settings that renders the same switchers | Settings | `/settings` | 4 | — | Changing league is reachable from Settings | DEFERRED (Settings is CQ-66's active file) |
| UX-D09 | Game Day's h1 ("This week's matchup") ≠ nav label; route absent from the naming canon | Either retitle or add a documented canon exception | Lane 6 / Game Day | `/game-day`, naming-canon, w1-16 prod-auth spec | 7 | owner / Lane 6 | Canon covers `/game-day` | OWNER (a prod-auth spec pins the h1) |
| UX-D10 | Week Recap and Rivalry standalone pages have no in-app link | Documented as share targets (content is inline in the hub) | — | `/league/week/…`, `/league/rivalry/…` | — | — | — | ACCEPTED as designed |
| UX-D11 | Trade Coverage nav label ≠ h1 "Trade Coverage Audit" | Align one to the other | admin tools | `/tools/trade-coverage` | 7 | — | Same string | DEFERRED (admin-only) |
| UX-P01 | "My Team" opens Team Strength, a league-wide ranking | In season, land on Game Day; or rename the group | nav-model | My Team | 3 | owner | — | OWNER |
| UX-P02 | Waivers and Waiver Advisor overlap (both do add/drop analysis) | Consolidate into one page with modes, or rename to separate the questions | waivers | `/waivers`, `/waiver-advisor` | 3 | owner | — | OWNER |
| UX-P03 | Rookie Board sits under Rankings; draft prep looks under My Team | Move it into "Draft & strategy", or keep and rely on NAV-08 | nav-model | `/idptc-rookies` | 4 | owner | — | OWNER |
| UX-P04 | Trade Database sits under Market; trade evaluators look under Trades | Move it or cross-list it | nav-model | `/market/trade-database` | 4 | owner | — | OWNER |
| UX-P05 | Win-now vs Rebuild is league-wide but lives in My Team | Move it to League | nav-model | `/phases` | 4 | owner | — | OWNER |
| UX-P06 | "Find undervalued players" is spread over five surfaces in three groups | A "Find value" section, or one landing page that explains the lenses | nav-model / product | see §1 overlap | 4 | owner | — | OWNER |
| UX-P07 | Sharp People is not in the Market menu; Sharp Identity Review is not in the admin Ops menu | Promote both | nav-model | `/market/sharp-people`, `/admin/sharp-identities` | 1 | owner (is the curated universe populated in production?) | — | OWNER |
| UX-P08 | Playoff odds still need a tab click inside the hub | A "Playoff Odds" League entry → `/league?tab=rosChampionship` | nav-model | `/league` | 4 | owner; query-string active state (A11Y-03) | — | OWNER |
| UX-P09 | The installed PWA has no shortcuts; signed-out launches skip the public League path | Manifest `shortcuts`; revisit the `/auction` redirect | manifest, HomeClient | `/` | 5 | owner (auction launch) | — | OWNER |
| UX-P10 | In season, the mobile tab bar has no Game Day | Swap News → Game Day in season | nav-model `MOBILE_TABS` | mobile | 5 | owner | — | OWNER |

## 5. Prioritized plan

1. **Done in this PR (routine, reversible, no URL or top-level change):** NAV-01 to NAV-09 and A11Y-02. Tests for each are listed in §7.
2. **Next routine unit (needs a free file claim):** UX-D08 (Settings league/team row) once CQ-66's Settings work merges. UX-D11. A11Y-01. The reverse half of NAV-08, measured against `/draft`'s CLS skeleton.
3. **Needs a Lane 6 decision:** A11Y-03 (shell `useSearchParams`) and UX-D09.
4. **Owner decisions (consequential IA moves):** UX-P01 to UX-P10, UX-D07. None is blocked on engineering. Each is a few lines in `nav-model.js` plus an inventory regeneration.

## 6. Journeys: before and after

Interactions are counted from the signed-in dashboard. D = desktop clicks, M = mobile taps. Ambiguity is rated L/M/H. Rows marked E2E are executed by `tests/e2e/specs/nav-ia-journeys.spec.js` on desktop-1366 and mobile-chromium.

| # | Journey | Before: path (D / M) | Before: ambiguity, dead ends, answer? | After: path (D / M) | After: notes | E2E |
|---|---|---|---|---|---|---|
| 1 | Dynasty roster strength | My Team label → Team Strength (1 / 2); Home quick action (1 / 1) | L. Answers it (position breakdowns) | same | "Roster" heading | yes |
| 2 | Stream an LB this week | My Team ▾ → Weekly IDP Streaming (2 / 2 + scroll). From `/waivers`: dead end | H: three similar waiver rows, no grouping | same, under "Waivers & FAAB"; from `/waivers` 1 click (Related) | dead end removed | yes |
| 3 | Safe drop | Waivers / Waiver Advisor / Streaming (2 / 2); no label says "drop" | H: three candidates; Waivers did not point onward | grouped + cross-linked (2 / 2) | still M until UX-P02 | — |
| 4 | Evaluate a trade | Trades label (1) / Trade tab (1) | L | same | — | yes |
| 5 | Undervalued players | 5 surfaces in 3 groups (2 / 2 each) | H; no single answer | unchanged | UX-P06 | — |
| 6 | Compare rankings / values | Rankings ▾ → Compare Players (2 / 2) | L | same | — | yes |
| 7 | Roster construction weaknesses | Team Strength breakdowns (1 / 2); Roster Construction gated, not in nav | M | same; "Roster" section ready for #2044 | — | — |
| 8 | Playoff chances | League (1) → find "Championship" among 22 tabs (+1); palette "playoff" → nothing. M: Menu → Hub → scroll tabs (3+) | H: nothing says "playoff" | same clicks; hint + palette now say "playoff odds" | M; UX-P08 for 1 click | yes (to Hub) |
| 9 | Rookie draft prep | My Team ▾ → Draft Board (2 / 2); Rookie Board in another menu, not linked | M | same; Rookie Board → Draft Board link | — | yes |
| 10 | Research a defender | Ranks → LB filter → name → Player File (3 / 3); `/` search + name (2); `/rankings/lb` shortcut | L | same | — | yes (`/rankings/lb`) |
| 11 | What changed in my league | League ▾ → Activity (2 / 2); dashboard movers (0); News (1) | L | same | — | yes |
| 12 | Settings / change league | System ▾ → Settings (2 / 2); league change = top-bar switcher (1 + choose) | M: Settings has no league control (dead end if the user looks there) | unchanged | UX-D08 | — |

## 7. Implemented changes (this PR)

| Change | Files | Test |
|---|---|---|
| `sectionRuns`, `relatedNavItems`, My Team sections, Hub hint and keywords, Sharp People palette target | `frontend/lib/nav-model.js` | `nav-sections-parity.test.jsx`, `route-inventory.test.js`, `nav-model.test.js` |
| Menu sections as labelled `role="group"` | `components/shell/NavMenu.jsx`, `app/shell.css` | parity test; E2E axe on the open menu |
| Drawer and `/more` render the same sections | `components/shell/NavLinkList.jsx` (new), `MobileChrome.jsx`, `app/more/page.jsx` | parity test; E2E drawer |
| Contextual Related rows, capability-gated through the nav model, with height held while the probe resolves (no CLS) | `components/shell/RelatedLinks.jsx` (new); `/waivers`, `/waiver-advisor`, `/market/sharp-tracker`, `/idptc-rookies` | parity test; E2E J2 |
| Game Day quick action | `components/terminal/QuickActions.jsx` (now exports `QUICK_ACTIONS`) | route-inventory (no broken links) |
| Route inventory + regression test | `docs/ui/evidence/route_inventory_2026-11-01.json`, `__tests__/route-inventory.test.js` | itself |
| E2E: offered destinations answer, menu/drawer keyboard + Escape + focus return, open-menu axe, skip link, signed-out boundary, journeys | `tests/e2e/specs/nav-ia-journeys.spec.js` | itself |
| Hub-hint pin updated (the guard still forbids advisor wording) | `__tests__/components/advisor-flag-off-surfaces.test.jsx` | itself |

Not touched: URLs, redirects, flags, capability resolvers, `server.py`, `src/`, public/private routing, and any business logic.

## 8. Desktop and mobile evidence

- **LOCAL, Chromium, 2026-11-01:** 37/37 passed with `--retries=0`. The run covered `nav-ia-journeys.spec.js` plus the existing `a11y-axe.spec.js` scans of `/`, `/waivers`, `/waiver-advisor`, `/market/sharp-tracker`, `/idptc-rookies` and `/more`, on desktop-1366 and mobile-chromium, all against one production build of this branch. A probe of the same build measured horizontal overflow = 0 at 1366 and at 390 on all six pages. The Related rows rendered with canon labels on `/waivers`, `/waiver-advisor` and `/market/sharp-tracker` (capabilities `waiverAdvisor` and `idpStreaming` were available locally). The `/idptc-rookies` row was not visually confirmed because the rookie board was still loading when the screenshot was taken. The nav spec covers:
  - every destination `/more` offers returns no 4xx and no login bounce;
  - the desktop My Team menu opens with Enter, moves with ArrowDown, and closes with Escape with focus back on the trigger, showing four labelled groups;
  - the mobile drawer shows the same four groups, has no horizontal overflow at 390 px, closes on Escape with focus back on Menu, and the tab bar has 5 targets ≥ 44 px;
  - signed-out chrome offers no private href;
  - journeys J1, J2, J4, J6, J8, J9, J10 and J11.
- **LOCAL screenshots:** desktop My Team menu, mobile drawer, and the Related rows. They were captured to the session scratchpad and are not committed (contract §16: local screenshots are not production proof).
- **PROD-OUT:** the signed-out landing at 375 px shows tabs Home / League / Sign in / Menu. The drawer offers only League → Hub, Activity. `/league` desktop offers League + Sign in only, with the public 22-tab strip (UX-D07). The ds Drawer close button is named "Close" through its icon label.
- **WebKit (mobile-390):** not run locally. The installed Playwright WebKit build (2248) does not match the pinned runner (needs 2359). Running it needs `npx playwright install webkit` (UNRESOLVED; CI's E2E lane runs desktop-1366 + mobile-chromium).

## 9. Accessibility findings

| Check | Result |
|---|---|
| Landmarks | `<header>` banner, `nav[aria-label=Primary]` (desktop top bar and mobile tab bar; the off-viewport one is `display:none`), `<main id=main>`, skip link first focusable (E2E). Related rows are `nav[aria-label="Related pages"]` |
| Labels | Group trigger = link + "X menu" button with `aria-expanded` / `aria-haspopup=menu`; menu `aria-label` = group; sections labelled groups (A11Y-02 fixed); drawer `role=dialog` labelled "Menu"; close button named "Close" |
| Drawer / dropdown state | `aria-expanded` tracks open state on both (E2E) |
| Escape | Closes the menu and the drawer and returns focus (E2E) |
| Focus | Route change moves focus to `<main>` (RouteFocusManager); `:focus-visible` rings use `--focus-ring` |
| Contrast | Unchanged tokens; Related links use `--accent` + underline (not colour-only) |
| Touch targets | Tab bar ≥ 44 px (E2E); Related links have a 24 px minimum hit height (WCAG 2.5.8) |
| Reduced motion | Shell already covered by `reduced-motion-shell.test.js`; no new motion added |
| axe (WCAG 2.0/2.1 A + AA) | **0 violations, LOCAL.** Checked on the open My Team menu (desktop) and the open drawer (mobile), which no page scan reaches. Page scans of `/`, `/waivers`, `/waiver-advisor`, `/market/sharp-tracker`, `/idptc-rookies` and `/more` stay at an empty baseline on desktop-1366. `/more` was also scanned on mobile-chromium. Production is not verified |
| Open | A11Y-01 (Home/End and type-ahead), A11Y-03 (query-string active state). PROD-OUT also showed a second, hidden `h1` on `/league`; it was not investigated here and is handed to the public-league owner |

## 10. Deferred items

- UX-D08 (Settings league/team row): `/settings` is the active file of CQ-66.
- The reverse NAV-08 link on `/draft`: its loading skeleton mirrors measured header heights to hold CLS at 0.32 → ~0. Adding a row needs a re-measure.
- A11Y-03: requires `useSearchParams` in the layout-level shell.
- WebKit E2E: local browser build mismatch; see §8.
- Every OWNER row in §4.
- PR #2044 (Roster Construction nav): unchanged and not duplicated. After it merges, run `UPDATE_ROUTE_INVENTORY=1 npx vitest run __tests__/route-inventory.test.js` once and set `/roster-construction`'s status when its flag is on.
