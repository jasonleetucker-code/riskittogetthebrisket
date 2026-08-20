# Claude 13 — C8/C9/C10 Delivery Log

**This branch (`claude/psi-reference-routes`) carries PR A/PR B (the PSI reference-route
migration) only.** Batches 1–3 of the earlier campaign (Chase Upside Market Ticker, franchise
continuity repair, dead-code census) are recorded in this same file's copy on
`claude/cseries-premium-public-closure` (PR #965), which this branch was deliberately **not**
based on (see below). **When both PRs merge, Claude 5 should reconcile these into one file** —
noted here rather than silently produced as a merge surprise.

## PR A / PR B authorization (governance record)

The owner explicitly authorized a real, production-capable migration of two reference routes —
Dynasty Rankings and a new Universal Player Profile — onto the "Premium Sports Intelligence"
editorial visual direction (`docs/PREMIUM_SPORTS_INTELLIGENCE_DESIGN_NORTH_STAR.md`), using two
attached reference screenshots as the visual source of truth. This supersedes the direction's
previous "preparation only" posture and is an explicit continuation of the owner override already
recorded for the broader C8/C9/C10 campaign earlier this session.

**Governance gap, recorded honestly.** As of this session's most recent check of the canonical
docs: `docs/VERSION_1_COMPLETION_CONTRACT.md` still lists `C8-PSI-02` / `R-PREMIUM` ("Premium
migration of the high-use routes") as `NOT STARTED`, and `docs/EXECUTION_PLAN.md` §6 still names
"Premium route migration" under "do not opportunistically begin." Unlike the earlier C8/C9/C10
authorization (found already reconciled into `EXECUTION_PLAN.md` §0 before that work began), **this
specific authorization has not yet been written into the canonical record.** The owner's
instruction directly anticipates this ("Claude 5 will reconcile the canonical execution/governance
record. Do not independently rewrite the V1 completion contract") — I am proceeding on that basis
per explicit instruction, not editing either canonical doc myself, and recording the exact delta
here for Claude 5.

**PR #965 stays frozen.** This work started on a fresh branch, `claude/psi-reference-routes`, off
`origin/main` — not off `claude/cseries-premium-public-closure` — per explicit instruction not to
keep piling unrelated work onto #965.

## Design decisions made during implementation (not verbatim from the brief)

- **Font**: the brief asked for "major serif editorial display typography" but also "do not add an
  external font dependency merely to imitate a screenshot unless the repository already has a
  supported/legal mechanism for it." The app's only font mechanism is `next/font/local` with
  checked-in `woff2` assets, specifically because the build environment can't reach
  `fonts.googleapis.com`. **Decision: the new `--font-display` token is a system serif stack**
  (`Georgia, Cambria, "Times New Roman", Times, serif`) — no new asset, no license risk. This is a
  real, visible gap versus the screenshot's distinctive display serif, and is called out here
  rather than silently accepted — swappable later via the same mechanism if the owner
  supplies/approves a licensed font file.
- **Token scoping mechanism**: rather than a whole-app theme flip or an all-new token namespace,
  the editorial palette is a new `.psi-editorial` CSS class that re-maps the SAME semantic alias
  names (`--surface-0`, `--text-primary`, `--accent`, etc.) every `ds/` component already consumes
  exclusively — the same mechanism `[data-theme="light"]` already uses, just scoped to a class
  instead of the whole document. Every existing `ds/` primitive (Panel, DataTable, Button, Badge…)
  therefore renders correctly in the new palette with zero component changes, and a migrated route
  reverts to the terminal palette instantly by removing one class — matching the north star's own
  "route-by-route, reversible" migration method (§8) exactly.
- **Every color WCAG-computed, not eyeballed** (matching this file's own existing discipline):
  text ≥4.5:1 on every surface (worst case, the nested `surface-2`), accent/market-direction marks
  ≥3:1, the screenshot's visible "thin black rule" separators get a genuinely near-ink
  `--border-strong` rather than a token reused from elsewhere at the wrong weight. The existing
  `--data-up`/`--data-down` terminal values were validated only against dark surfaces and measured
  below the 3:1 mark floor on this scope's nested surface (2.75/2.94:1) — re-derived rather than
  inherited, darker blue/orange in the same CVD-safe hue family, verified ≥4.5:1+ everywhere.
  22 tests in `tokens-contract.test.js` (8 new) pin these ratios so a future edit can't silently
  regress them.

## Batch log

### Setup — done

- Branch `claude/psi-reference-routes` created from `origin/main`.
- This delivery doc created (fresh copy — see the note at the top about reconciling with #965's
  copy at merge time).
- `docs/WORK_CLAIMS.md` row added for PR A.

### Batch A1 (C8-PSI-02) — Editorial token layer — done

**What shipped:**
- `frontend/app/tokens.css`: new additive `.psi-editorial` scope (see "Design decisions" above for
  the mechanism and the exact palette). Does not touch any existing dark/light token or
  `globals.css` — purely additive, verified by the existing "stays additive" contract test plus a
  new one scoped to this block.
- `frontend/components/ds/token-contract.js`: new `PSI_EDITORIAL_REQUIRED` export listing the
  tokens this scope must define, mirroring `LIGHT_THEME_REQUIRED`'s existing pattern.
- `frontend/__tests__/components/ds/tokens-contract.test.js`: 8 new tests — required-token
  presence, no-primitives-redefined, additive-only, and 5 WCAG contrast assertions (accent on
  worst surface, text-on-accent, text-primary on all 4 surfaces, data-up/data-down mark floor on
  all 4 surfaces, border-strong reads as a real rule).

**Verified:**
- `tokens-contract.test.js`: 22/22 passing (14 pre-existing + 8 new).
- Full frontend suite: 142 test files / 2,243 tests passing, zero regressions.

**Deliberately NOT claiming:**
- A licensed display serif font (system stack used instead — see "Design decisions").
- Any component/page actually USING the new scope yet — that's Batch A2 (shell) and A3
  (Rankings). This batch is tokens only, so it's inert until a page opts in via the class.

### Batch A2 (C8-PSI-01) — Shell restyle — done

**Finding that reshaped this batch:** `frontend/app/shell.css` (the app chrome stylesheet —
`TopBar`, `MobileChrome`, nav dropdowns, the mobile drawer, the command palette) turned out to
already consume ONLY semantic token aliases, zero raw hex, matching the same discipline as
`ds.css`. It is also **not** on the Lane 6 claim's path list (only `globals.css` is). That means
applying the new `.psi-editorial` class to the shell's root elements re-skins the ENTIRE header —
brand, nav, search, account menu, mobile tab bar, drawer, dropdowns — automatically, with **zero
CSS rewrite needed**. This is exactly the payoff the token architecture was built for, so the
batch became much smaller than planned: no new CSS modules, no shell.css rewrite, just scoping +
one small monogram tweak.

**What shipped:**
- `frontend/components/shell/TopBar.jsx`: `.psi-editorial` added to the `<header>` root (covers
  the nav dropdowns and the System menu too, since they render inline, not via a portal —
  verified, no `createPortal` anywhere in this tree). Brand mark glyph changed from a bare "▪" to
  "CU" text (still `aria-hidden`, the accessible name is still "Chase Upside" from the link's own
  text), to match the screenshot's compact monogram-block treatment.
- `frontend/components/shell/MobileChrome.jsx`: `.psi-editorial` added to `MobileTopBar`'s
  `<header>` and `MobileTabBar`'s `<nav>`. The menu `Drawer` is a JSX **sibling** of the tab bar
  (not a descendant), so it needed the class passed explicitly via its own `className` prop
  (`Drawer` already supports one) rather than inheriting it.
- `frontend/app/shell.css`: one small additive rule,
  `.psi-editorial .shell-brand-mark` — a bordered 22px square rendering "CU" in the new serif
  display face, scoped so it doesn't touch the terminal shell's existing plain-glyph treatment if
  the class were ever removed from a route.
- **This is a global, immediate change**: `TopBar`/`MobileChrome` are the one persistent shell
  rendered on every route, so every page's header/nav now shows the editorial palette right away,
  while unmigrated page BODIES stay on the terminal palette until their own route migrates. This
  is a deliberate, temporary seam — the north star's own "route-by-route, reversible" method says
  a split state during migration is expected, only says not to leave it split *indefinitely* — and
  matches the brief's own success condition ("open the app and immediately see the migration has
  begun").

**Verified:**
- `TopBar.test.jsx`: 20/20 passing, unchanged (no test asserted the literal "▪" glyph).
- Full frontend suite: 142 test files / 2,243 tests, zero regressions.

**Deliberately NOT claiming:**
- Any change to `AppShell.jsx` (claimed by Lane 6, and confirmed not to need touching — it's
  behavior/context only, no styling lives there).
- Any change to `globals.css` (claimed).
- A rewrite of the nav's information architecture — every existing nav item, group, gating rule
  and keyboard/focus behavior is untouched; only the palette changed.

### Batch A3 (C8-PSI-02) — Rankings visual migration — done

**Finding that reshaped this batch, same as A2:** `frontend/app/rankings/board.module.css` is
already 100% token-driven — zero raw hex, zero `rgba()` (verified by grep before writing a line).
Applying `.psi-editorial` to the page root re-skins the entire table (rank/player/value/source
cells, filters, rails, trust strip) automatically. The real work was finding and closing the small
number of places the page reached OUTSIDE the token system, into legacy `globals.css` classes this
Lane-6 claim forbids editing.

**What shipped:**
- `frontend/app/rankings/page.jsx`: `.psi-editorial` added to the page root `<section>`. Three
  legacy-class leaks closed by adding local replacements to `board.module.css` and swapping the
  className references (never editing `globals.css`):
  - `button-reset` (hardcoded `--border`/`--cyan`, both pre-R0 legacy names invisible to the new
    scope) → new `.resetButton`, a genuine reset (no background/border) rather than the legacy
    rule's incidental box — matches the screenshot's plain inline typography for player names,
    watch stars and values.
  - `rankings-player-name` (legacy `--cyan` hover) → new `.playerName`, same behavior, hover color
    now `--accent`.
  - `muted` (legacy `--muted` token) → new `.muted`, now `--text-tertiary`.
  - `custom-mix-badge` audited and left AS-IS: verified its own declared properties (font-family,
    size, spacing, a brightness-filter hover) are all color-neutral: it layers onto `ds-badge
    ds-badge--warning`, which is already fully token-driven.
- **Hero treatment**: eyebrow now reads "Chase Upside Consensus / Updated {relative time}" —
  reusing the page's own existing `relativeUpdated` freshness derivation (`rawData?.dataFreshness`
  → `generatedAt`), not a new computation. `<h1>` stays the literal string `"Rankings"` — see the
  naming-canon note below for why "The Dynasty Board" is NOT the `<h1>`. Description became "The
  Dynasty Board — unified dynasty rankings, offense + IDP blended by consensus rank." (existing
  product language, "The Dynasty Board" folded in as editorial branding rather than a new claim).
  New `.hero` class + a scoped `:global(.ds-page-header__title)` compound selector in
  `board.module.css` gives just this page's title a serif `--font-display` face at
  `--font-size-3xl` (the existing scale's largest step — no ninth size invented) — `ds.css`'s
  shared `PageHeader` styling is untouched for every other page.
- **"Format summary" (real league Superflex/TEP/IDP label) deliberately omitted**: no canonical
  field for this was found readily available on this page (checked `useLeague()`,
  `useTeam()`) in the time budget for this batch. Rather than guess or fabricate a label,
  omitted — a real gap, named per the owner's own instruction rather than silently skipped.

**Naming-canon course-correction, caught by the test suite (not by inspection):** the first attempt
set the literal `<h1>` to "The Dynasty Board", which broke `page-title-canon.test.jsx` — this repo
pins nav label ≡ page `<h1>` deliberately (its docstring cites a real 2026-07-29 regression this
guard now catches). Changing the canon would mean changing `nav-model.js`'s desktop nav link label
too — an app-wide copy change well beyond "Rankings page visual migration," and out of scope for
this batch. Reverted to keep `<h1>` as the canon "Rankings" and moved the editorial name into the
description instead. Recorded here because a plan-vs-actual note belongs beside the code, not
silently corrected away.

**Legacy badge system, NOT touched, documented rather than silently left:** `lib/display-helpers.js`
(`posBadgeClass`, `confBadgeClass`, `marketEdge`/`marketAction`) all return legacy `globals.css`
class names (`badge-cyan`, `badge-amber`, `badge-green`, `badge-red`, `edge-buy`, `edge-sell`) for
position/confidence/edge badges throughout the table, audit panel and edge rail. `board.module.css`'s
OWN header comment already names this as an acknowledged, deferred concern ("Badge/tier/audit-grid
colors stay on their legacy global classes until the R5 CSS purge") — not something this batch
introduced. These badges are self-contained colored chips (not transparent), so they remain fully
legible, just visually inconsistent with the new palette rather than broken. Migrating this whole
shared badge system onto `ds/Badge` is real work spanning multiple pages beyond Rankings and is
correctly a separate, dedicated unit (the repo's own planned "R5 CSS purge"), not silent scope creep
here. Same disposition for the mobile-source-strip/audit-row expanded-drawer background wash
(`rankings-mobile-source-row`/`rankings-audit-row`) — near-transparent legacy tints, low visual
impact, same acknowledged-deferred class.

**Verified:**
- Full frontend suite: 142 test files / 2,243 tests, zero regressions (including
  `page-title-canon.test.jsx` after the h1 correction above).
- `next build` (both the default Turbopack builder and `--webpack`, since the bundle-budget script
  needs the latter): clean, zero new errors (same three pre-existing `/api/public/league*`
  `TypeError`s from no backend running in this sandbox, unrelated to this diff).
- Bundle budget: `/rankings/page` 66.6 KB / 75 KB (8.4 KB headroom) — all 14/14 budgeted pages
  pass.

**Deliberately NOT claiming:**
- The legacy badge system migration and the mobile-source-row/audit-row background tint (see
  above) — named, deferred, not silently dropped.
- The "format summary" league line (see above).
- Real browser/visual verification and the axe a11y suite — that's Batch A4.
