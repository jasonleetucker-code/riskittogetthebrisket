# UX / UI Audit

**Generated:** 2026-04-25  
**Scope:** Risk It To Get The Brisket — desktop + mobile interface,
navigation, layout, components, responsiveness.

This doc documents the full audit *and* the small set of safe,
high-confidence improvements that ship in the same pass. The owner's
master rule is "preserve existing functionality; do not destabilize
what already works." Findings are reported even when they're left for
a follow-up pass.

---

## Audit results — what's actually shipping today

The product is more polished than the UX-explorer pass suggested. Of
the 15 findings I generated, **5 turned out to be false positives**
when verified directly against the source. Specifically:

- `/rankings` and `/trade` *do* render loading and error states
  (`rankings/page.jsx:1047-1063`, `trade/page.jsx:1594-1617`). These
  are not gaps.
- The filter bar *does* have mobile rules (`globals.css:1431-1438` and
  `:1553`).
- Mobile buttons *do* already have an enlarged touch target
  (`globals.css:1562` — `min-height: 40px`).
- The mobile top bar title *does* page-title-map for primary routes
  (`AppShellWrapper.jsx:148-167`); it just isn't dynamically
  parameterized for `[owner]` / `[playerId]` deep links.

Always verify before changing.

---

## Route inventory (verified)

| Route | Purpose | Tier |
|---|---|---|
| `/` | Landing / auth gate | Primary |
| `/rankings` | Player value rankings | Primary |
| `/trade` | Trade calculator | Primary |
| `/draft` | Draft prep + ADP | Primary |
| `/edge` | Source-signal disagreement | Secondary |
| `/finder` | Discovery presets (consensus gaps, sell-high, buy-low) | Secondary |
| `/angle` | Trade-pitch generator | Secondary |
| `/trades` | League trade history | Secondary |
| `/rosters` | Team strength + age curves | Secondary |
| `/league` | Public league hub (records / streaks / awards / recaps / etc.) | Public |
| `/league/franchise/[owner]` | Per-franchise detail | Tertiary |
| `/league/player/[playerId]` | Player ownership journey | Tertiary |
| `/league/rivalry/[pair]` | Head-to-head | Tertiary |
| `/league/week/[season]/[week]` | Weekly recap | Tertiary |
| `/league/weekly/[season]/[week]/[matchup]` | Matchup detail | Tertiary |
| `/draft-capital` | Legacy redirect → `/league` | Deprecated |
| `/settings` | Source weights, TEP, notifications | Secondary |
| `/login` | Auth | Public |
| `/more` | Mobile catch-all hub | Mobile primary |
| `/admin` | Operator panel | Admin |
| `/tools/source-health` | Source uptime + freshness | Tertiary |
| `/tools/trade-coverage` | Trade-coverage diagnostic | Tertiary |

22 routes + 1 deprecated redirect. No orphaned routes detected.

---

## Navigation map (verified)

**Desktop top bar** (`AppShellWrapper.jsx:14-25`):
Rankings · Trade · Draft · Edge · Finder · Angle · League · Settings · More

**Mobile bottom bar** (`AppShellWrapper.jsx:31-35`):
Rankings (R) · Trade (T) · More (M)

**League context** (LeagueSwitcher + TeamSwitcher) is persistent in
both top bars. This is good and matches the codebase's
"scoringProfile controls rankings, leagueKey controls context"
contract. No friction here.

---

## Design tokens & shared components (verified)

**Tokens** (`globals.css:42-85`): Vikings palette, 5-step spacing
scale, 3-step radii, 1320px max width, 54px desktop topbar / 46px
mobile / 56px mobile bottom nav.

**League primitives** (`app/league/shared.jsx`,
`shared-server.jsx`, `shared-helpers.js`): Card, Avatar, Stat,
EmptyCard, MiniLeaderboard, HighlightCard, SingleHighlight,
ManagerInline, LinkButton, plus 6 pure helpers.

**Global UI primitives** (`components/ui/`): EmptyState, ErrorState,
LoadingState, PageHeader, FilterBar, SubNav, TierDivider,
ValueBandBadge, MobileSheet, VirtualList, Skeleton, Toast.

**Inconsistency:** `EmptyCard` (league-side) wraps `EmptyState`
(global) in a `Card`; `/rosters` and `/trades` use `EmptyState`
directly. This is cosmetic drift, not user-facing breakage. Worth
cleaning up but not a P0.

---

## Mobile breakpoints in use (verified)

| Width | Count | Use |
|---|---|---|
| 768px | 20+ | Primary mobile breakpoint — column drops, tighter padding, touch-target sizing |
| 720px | 2 | min-width tablet+ rules |
| 1024px | 1 | min-width large desktop |
| 1200px | 1 | XL desktop |
| 880px | 1 | Edge table wrap point |
| 980px | 1 | Trade controls stack point |
| 600px / 640px / 520px / 420px | 1 each | Targeted overrides for very narrow screens / specific pages |

The 768px breakpoint dominates and matches industry convention.

---

## Verified findings, ranked by ROI

### Tier 1 — fix in this pass (low risk, real value)

**U1. Mobile tap targets at 40px are below WCAG 2.5.5 (44px).**
- File: `frontend/app/globals.css:1562`
- Current: `.button, .select, .input { min-height: 40px; }` inside the `@media (max-width: 768px)` block.
- WCAG AAA recommends 44px for touch targets. Some `.button` selectors elsewhere already set 44px (`globals.css:805, 847, 853, 890`), so this 40px is the outlier.
- **Fix this pass:** bump mobile `.button, .select, .input` rule to 44px.
- **Risk:** very low. 4px taller buttons/selects on mobile only.

### Tier 2 — leave for a focused follow-up (medium risk, real value)

**U2. EmptyCard / EmptyState pattern drift.**
- League-side custom `EmptyCard` wraps the global `EmptyState`
  inside an extra `Card`. Other pages render `EmptyState` directly.
- Cosmetic; not user-facing breakage. Worth consolidating in a
  separate cleanup PR but not while we're touching layout.

**U3. Mobile top-bar title isn't parameterized for deep routes.**
- `AppShellWrapper.jsx:148-167` maps the route prefix to a fixed
  string. On `/league/player/[playerId]` the title stays "League"
  — a player name would be nicer.
- Requires threading title through context or layout prop. Real
  wiring change; deserves a focused PR.

**U4. The four discovery surfaces (`/trade`, `/trades`, `/finder`,
`/angle`) are scattered without a shared mental model.**
- New users can't tell from the labels alone which tool solves
  which problem. Desktop nav shows them flat; only `/more`
  surfaces descriptions, and only mobile users see `/more`.
- Real IA work. Deserves a design pass before code change. Options:
  group under a "Tools" submenu, add desktop hover descriptions, or
  add a shared discovery hub.

**U5. Mobile filter bar still wraps to multiple rows on 390px.**
- Layout works (no overflow), but the search input + position
  select + tiers button + (hidden) confidence select compete for
  space.
- Could collapse secondary filters behind an "Advanced filters"
  drawer. MEDIUM-risk change because it touches a hot path
  (rankings page is the most-trafficked surface).

### Tier 3 — already handled or out of scope

**U6.** Loading / error states on `/rankings` and `/trade`. Already
handled (verified in code). Not a finding.

**U7.** Filter bar mobile layout. Already has rules
(`globals.css:1431-1438, :1553`). Not a finding.

**U8.** Confidence filter on mobile. Hidden via `.hide-mobile`. There
*is* a finding here in principle, but the filter is one of three on
that page and the column layout would be cluttered; this is a
deliberate trade-off. Not changing.

**U9.** Desktop button sizes (~32-36px). Desktop pointers don't
require 44px targets; only touch surfaces do. WCAG carve-out applies.

**U10.** Settings email status persists 2.5s. Deliberate; the success
toast is meant to disappear. Not breaking.

---

## Implementation summary (what shipped this pass)

**One file changed:** `frontend/app/globals.css`

**Diff**: in the existing `@media (max-width: 768px)` block, the
`.button, .select, .input { min-height: 40px; }` rule moves to 44px.
This brings all primary-action mobile controls into WCAG 2.5.5 (Level
AAA) Target Size compliance — every primary tap target is at least
44×44 px on mobile.

Adjacent `min-height: 44px` rules elsewhere in the file
(`globals.css:805, 847, 853, 890`) already set 44 — this just brings
the general rule into line with them.

Risk audit:
- No JSX touched, no API touched, no test touched.
- No layout reflow on desktop (rule is mobile-only).
- Buttons, selects, and text inputs gain 4 px of height on mobile;
  internal padding unchanged. Visual impact: marginally taller
  controls. Functional impact: easier to tap accurately.

---

## What was deliberately *not* done

- **Did not refactor navigation.** U3 + U4 are real but require IA
  decisions — not safe to ship without owner alignment.
- **Did not redesign the mobile filter bar.** Works today; redesign
  needs design + visual review.
- **Did not collapse `EmptyCard` into `EmptyState`.** Cosmetic; no
  user-facing benefit; defer.
- **Did not change the league public sections** I shipped earlier
  today. They use the standard `Card` + `.row` flex-wrap pattern;
  spot-checked that they collapse cleanly on mobile.

---

## Validation

- `npm run build` — clean (verified before push).
- Unit tests untouched.
- No backend / API change.

---

## Recommended next passes (ranked)

1. **Mobile filter bar redesign for `/rankings`** (U5). Highest user
   impact; touch-heavy surface.
2. **Discovery-surface IA pass** (U4). Group `/trade`, `/trades`,
   `/finder`, `/angle` more clearly. Owner design decision first.
3. **Parameterized mobile top-bar titles** (U3). Real wiring change;
   small but worthwhile for the deep-link views.
4. **Standardize on `EmptyState` everywhere** (U2). Pure cleanup PR.
5. **Comprehensive 320 px / 375 px / 1440 px responsive sweep** —
   catalog any layout that breaks at edges, fix systematically.
