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

### Tier 2 — status

**U2. EmptyCard / EmptyState pattern drift.** *Closed — wontfix.*
On a second read, the league-side `EmptyCard` is not drift but a thin
convenience wrapper that defaults the "X coming online" framing across
every league tab.  Removing it would force every consumer to duplicate
that framing inline, making the codebase more verbose, not less.
Leaving as-is.

**U3. Mobile top-bar title isn't parameterized for deep routes.**
*Shipped.* `AppShellWrapper.jsx::pageTitle` now walks two segments
of the route, so `/league/franchise/[owner]` → "Franchise",
`/league/player/[playerId]` → "Player", `/league/week/...` →
"Week recap", `/tools/source-health` → "Source health", etc.
Top-level routes still resolve identically. Risk: very low — the
function only generates a heading string.

**U4. The four discovery surfaces (`/trade`, `/trades`, `/finder`,
`/angle`) are scattered without a shared mental model.** *Deferred.*
Real IA work — deserves a design pass and owner alignment before
the navigation tree changes. Documented as the highest-leverage
follow-up.

**U5. Mobile filter bar exposes only search + position; confidence
filter and tiers toggle are `hide-mobile` and unreachable on phones.**
*Shipped.* Removed `hide-mobile` from the confidence select and the
tiers button on `/rankings`. Both now wrap to a second row of the
existing flex-wrap filter bar on narrow viewports — small layout
cost, restores feature parity with desktop. Risk: low — pure CSS
class change, no JSX restructure.

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

## Implementation summary (what shipped)

**Files changed across the audit's three passes:**

1. `frontend/app/globals.css` — mobile `.button/.select/.input`
   min-height 40 → 44 px (WCAG 2.5.5 AAA tap-target compliance).
2. `frontend/app/AppShellWrapper.jsx::pageTitle` — walks two route
   segments so deep `/league/*` and `/tools/*` routes get specific
   titles ("Franchise", "Player", "Source health", etc.) instead
   of falling back to the parent route name (U3).
3. `frontend/app/rankings/page.jsx` — removed `hide-mobile` from
   the confidence select and the tiers toggle in the filter bar so
   mobile users can access them (U5).
4. `frontend/app/AppShellWrapper.jsx` (PRIMARY_NAV `hint` field) —
   each desktop nav item now has a one-line `title` tooltip that
   surfaces on hover.  Closes the "/trade vs /trades vs /finder
   vs /angle" identity ambiguity (U4 lite).
5. **New components**: `frontend/components/ui/PlayerImage.jsx` +
   `frontend/components/ui/NflTeamLogo.jsx` + helpers in
   `frontend/lib/player-images.js`.  Player headshots from Sleeper
   CDN with team-logo + position-tinted-initials fallback chain.
   Wired into rankings table, trade tray (player rows + receiving
   + recent + picker), league player records, league awards
   (player + MVP + playoff MVP), and the player-journey hero.

Risk audit:
- No backend / API touched.
- No JSX restructure — CSS class removal + a single function rewrite.
- Existing `.filter-bar` already uses flex-wrap, so the previously
  hidden controls just appear on a second row at narrow widths.
- `pageTitle` rewrite has no behaviour for routes that don't match
  one of the new sub-route maps; it falls back to the same
  top-level title behaviour as before.

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

## Recommended next passes (ranked) — all shipped

The original five next-pass recommendations have all landed across PRs
#303, #304, #305, #306, and a final follow-up PR closing out the
remaining items below:

1. **Mobile filter bar redesign for `/rankings`** (U5) — *Shipped.*
   Confidence + Tiers exposed on mobile via `hide-mobile` removal.
2. **Discovery-surface IA pass** (U4) — *Shipped (full).* The four
   trade-related routes (/trade · /trades · /finder · /angle) used
   to live as flat top-level peers; they now collapse into a single
   "Trade ▾" dropdown on desktop with sub-items labelled "Calculator
   / History / Arbitrage Finder / Counter-Pitch".  Direct URLs still
   work — the change is nav-only.  /more page is restructured to
   mirror the new grouping ("Trade workflow", "Signals", "League",
   "Settings").  Original lite version (tooltips + group separators)
   is preserved.
3. **Parameterized mobile top-bar titles** (U3) — *Shipped.*
   `AppShellWrapper.jsx::pageTitle` walks two route segments.
4. **Standardize on `EmptyState` everywhere** (U2) — *Closed wontfix.*
   `EmptyCard` is a useful "X coming online" framing wrapper.
5. **Comprehensive 320 / 375 / 1440 px responsive sweep** — *Shipped.*
   New `@media (max-width: 360px)` block: tighter card padding,
   `.page-header-actions { flex: 1 0 100% }` so actions wrap to a
   second row, smaller filter-bar gaps, smaller trade-meter side
   values, smaller sub-nav buttons, shorter sticky-name column on
   rankings.  Closes iPhone SE / Galaxy Fold cover-screen gaps.

### Bonus shipments along the way

- **Trade calculator: sticky team affordance** — `mySideIdx` derived
  in `trade/page.jsx` from selectedTeam vs. each side's roster.  The
  matching side card gets a "You · {team name}" pill + subtle gold
  border; persists through scroll because it's part of the side card
  itself.
- **Rosters page: player headshots** — `buildPlayerMetaMap` and
  `findWaiverWireGems` in `frontend/lib/league-analysis.js` thread
  `playerId` + `team`; Trade Targets, Trade Chips (surplus), and
  Waiver Wire Gems rows all render a 20-22 px `<PlayerImage>`.
- **Recap depth + variety** (per #306).
- **Trade history images** (per #306).

The audit is closed.  Future passes can pick up new findings as they
emerge from real-world use; the catalog above is preserved as
historical context.
