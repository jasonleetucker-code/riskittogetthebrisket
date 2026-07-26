# Design System — Redesign R0 Foundation

**Status:** R0 shipped (tokens + component library + `/design` reference).
**Territory:** `frontend/app/tokens.css`, `frontend/app/ds.css`,
`frontend/components/ds/*`, `frontend/app/design/*`, plus two surgical edits
(font loading in `app/layout.jsx`, imports + font-stack wiring in
`app/globals.css`). Nothing else was touched — R1+ migrates pages onto this
foundation.

---

## 1. Visual direction: "War-room terminal"

The brief: *NFL war room × Bloomberg-grade market terminal × Apple-level
restraint. Intelligence, confidence, speed, authority.* The choices below are
decisive, not exploratory — each one answers the brief directly.

| Decision | Rationale against the brief |
|---|---|
| **Near-black neutrals with a violet undertone** (hue ≈ 265, very low chroma: `#0d0b12 → #221d30`) | Terminals are built on near-black, not brand-purple slabs. The legacy saturated-purple cards (`#2a1550`) read as a fan site; the undertone keeps the franchise DNA in the room without shouting it. Elevation = surface lightness, not drop shadows — the Bloomberg move. |
| **ONE accent: the franchise gold** (`#FFC704`) | Gold-on-near-black *is* the terminal aesthetic (amber phosphor heritage), and it happens to be the brand color — the rare case where restraint and identity are the same choice. Gold is reserved for: the primary action, active/selected state, the page eyebrow, active sort. It is never a background wash for content. |
| **Market semantics, not casino colors** | `--positive #4cc38a` / `--negative #e5646e` are desaturated one step from the legacy `#34d399`/`#f87171` (and the four rogue greens die). Direction is additionally always carried by an arrow glyph — color is reinforcement, never the sole channel. Warning is orange (`#e09f3e`), deliberately distinct from accent gold. |
| **Two typefaces, actually loaded** | Inter (UI) + JetBrains Mono (all data). The audit found both *named but never loaded* — the "terminal" rendered in Segoe UI. `next/font` self-hosts both (zero runtime requests, `display: swap`). Every number that can be compared sits in the mono face with `tabular-nums`. That single rule is most of the "Bloomberg feel". |
| **Density with a floor** | 8-step type scale, 11px minimum (legacy shipped ~8.7px). Dense ≠ tiny: density comes from tight line-heights, compact table padding, and uppercase micro-labels — not from shrinking below legibility. |
| **Flat, bordered, luminous** | Panels are 1px-bordered surfaces one step lighter than the page. No gradients, no glassmorphism, no neon glows, no card-grid confetti. Shadows exist only for true overlays (3 levels). |

What this explicitly rejects (per the brief): generic AI-dashboard card
grids, random gradients, glassmorphism, neon, oversized empty space,
cartoonish sports imagery, emoji-as-UI, ASCII-as-iconography.

---

## 2. Token reference

All tokens live in `frontend/app/tokens.css`; the machine-readable contract
is `frontend/components/ds/token-contract.js`, pinned by
`__tests__/components/ds/tokens-contract.test.js` (missing/undocumented/
legacy-colliding tokens fail CI). The layer is **additive**: it defines only
new names and never overrides a legacy `globals.css` token.

**Components consume semantic aliases only.** The neutral ramp and brand
hexes are raw material; if you type `--neutral-850` or a hex literal in a
component, you are doing it wrong.

### Color

| Group | Tokens | Notes |
|---|---|---|
| Surfaces | `--surface-0..3`, `--surface-hover/active/inverse`, `--backdrop` | 0 = page, 1 = panel, 2 = nested/inputs, 3 = overlay. Elevation by lightness. |
| Text | `--text-primary/secondary/tertiary/disabled/inverse` | Primary 16.4:1, secondary 7.6:1, tertiary ≥ 4.5:1 on every surface. `disabled` is decorative-only. |
| Borders | `--border-subtle/default/strong` | subtle = in-panel hairlines, default = panel outline, strong = interactive rests. |
| Accent | `--accent`, `--accent-hover/pressed/muted/border`, `--text-on-accent` | The one gold. `on-accent` is 11.9:1 on gold. |
| Semantic | `--positive/negative/warning/info` + `*-text` + `*-muted`, `--neutral-signal(-muted)` | Base = marks (≥3:1), `*-text` = copy (≥4.5:1), `*-muted` = washes. |
| Charts | `--chart-1..6`, `--chart-grid`, `--chart-axis` | See Color method below. |
| Focus | `--focus-ring`, `--focus-ring-color` | Two-layer ring: surface gap + gold. |

### Color method (charts)

The categorical order `gold #c98500 → blue #3987e5 → magenta #d55181 →
violet #9085e9 → aqua #199e70 → orange #d95926` was **validated with the
dataviz palette validator** on `--surface-1` (dark): lightness band PASS,
chroma PASS, worst adjacent CVD ΔE 9.4 (≥8 target), normal-vision ΔE 19.7
(≥15), contrast ≥3:1 for all six. First three slots also validate all-pairs
(scatter-safe). Rules: assign slots in fixed order, never cycle, never
repaint survivors when a filter changes series count; >6 series folds to
"Other". Status colors are never series colors. `lib/chart-primitives.js`'s
`CHART_COLORS` re-derives from these slots in R1.

### Typography

| Token | Value | Use |
|---|---|---|
| `--font-ui` | Inter (next/font var) | Everything textual |
| `--font-data` | JetBrains Mono (next/font var) | ALL data values, always with `tabular-nums` (`.ds-mono`) |
| `--font-size-2xs..3xl` | 11 / 12 / 13 / 14 / 16 / 20 / 24 / 32 px | **Eight sizes. There is no ninth.** 2xs is the floor. |
| `--font-weight-regular/medium/semibold/bold` | 400/500/600/700 | |
| `--line-height-tight/snug/normal` | 1.2 / 1.35 / 1.5 | headings / dense rows / body |
| `--tracking-wide` | 0.06em | uppercase micro-labels only |

Size mapping: 2xs = micro labels + column headers · xs = captions, badges ·
sm = dense table body · md = body · lg = emphasized/tile values · xl = panel
headline · 2xl = page title · 3xl = hero stat.

### Layout, depth, motion

| Group | Tokens |
|---|---|
| Space (4px grid) | `--space-0..10` → 0, 4, 8, 12, 16, 20, 24, 32, 40, 48, 64px |
| Radii (four) | `--radius-1` 4px (inputs, badges) · `--radius-2` 8px (buttons, tiles) · `--radius-3` 12px (panels, modals) · `--radius-full` |
| Shadows (three) | `--shadow-1/2/3` — only overlays get 2-3 |
| Z-index | `--z-raised/sticky/header/dropdown/overlay/modal/toast/tooltip` (1 → 2500; overlay tiers sit above every legacy value, incl. the inline 1100/1200/2000s) |
| Motion | `--motion-fast/base/slow` (120/180/280ms) + `--ease-out/in-out`; all durations zero under `prefers-reduced-motion` |
| Breakpoints (four) | 480 / 768 / 1024 / 1320. Media queries may use these literal values and **no others**. |

### Theming

Dark is default. `:root[data-theme="light"]` re-maps semantic aliases only
(scaffolded now, validated for contrast, not user-exposed yet). Because
components are semantic-only, light mode costs zero component changes at
enablement; remaining work then is light steps for `--chart-*` and a toggle.

---

## 3. Component inventory (`frontend/components/ds/`)

Import via the barrel: `import { Panel, DataTable } from "@/components/ds"`.
Every component: token-styled via `ds.css` (zero runtime CSS-in-JS, zero raw
hex — CI-enforced), keyboard/a11y correct, doc comment with usage rules.

| Component | Role / rules |
|---|---|
| `Panel` | **THE container.** Title/subtitle/actions/footer/body; `flush` for edge-to-edge tables; `dense` for rails. Replaces `.card` (×187), terminal `Panel`, league `Card`. Spacing between panels belongs to the page grid, never the panel. |
| `PageHeader` | The one page-title pattern; owns the page's single `<h1>`; eyebrow/description/actions. |
| `DataTable` | The product. Column-spec driven; sortable headers are real `<button>`s with `aria-sort` + polite live-region announce; numeric first-click sorts DESC; sticky header; `regular/compact` density; numeric cells auto right-align in the data face; built-in scroll wrapper (unwrapped tables can no longer happen); `onRowClick` rows are keyboard-operable; `caption` required. |
| `StatTile` | The one KPI tile (replaces 3 implementations). Label + tabular value + `Movement`/meta; `bare` for in-panel rows. |
| `Badge` / `StatusIndicator` / `Movement` | The signal language. Badge tones carry meaning, not decoration. StatusIndicator = dot + required label. **Movement = direction (SVG arrow) + magnitude (tabular) + confidence (0-3 ticks)** — replaces every raw red/green delta; announces e.g. "up 340, high confidence". |
| `Button` | primary (one per view region) / secondary / ghost / danger; sm; loading with `aria-busy`. |
| `Field` + `Input`, `Select`, `SegmentedControl` | Field wires label/hint/error ids + `aria-invalid`. Select stays native. SegmentedControl = radiogroup with arrow keys, for 2-5 value choices (panels → Tabs, >5 → Select). |
| `Tabs` | Real tablist, roving tabindex, Arrow/Home/End, `aria-controls`; horizontal overflow scrolls. Replaces `SubNav` + hand-rolled chip rows. |
| `Modal` / `Drawer` | `role="dialog"` + `aria-modal`, focus trap, Escape, focus restore, scroll lock, labelled close. Drawer is the PlayerPopup successor. |
| `Tooltip` | Hover **and focus**, `role="tooltip"` + `aria-describedby`, text-only. |
| `Skeleton` family | Extends the audit's well-built-but-unused skeleton: + `SkeletonText/Table/Stat`. Px-sized (no CLS), `aria-hidden`, reduced-motion aware. Retires the 152 `"Loading..."` strings. |
| `EmptyState` | One quiet voice for "nothing here"; one action max. |
| `Banner` | Tone-ruled inline alert; warning/negative = `role="alert"`, info/positive = `role="status"` (the live-region wiring the audit found missing). |
| `Sparkline` / `Meter` | Small-chart primitives per the dataviz method: 2px line, endpoint dot, no axes at this size, `--chart-*` slots, required accessible label. Bigger charts keep composing `lib/chart-primitives.js`. |
| `Icon` | Internal stroke-glyph set (arrows, chevrons, close, check, search, info, warning). Retires ASCII/emoji iconography. |

Living reference: **`/design`** (unlinked, noindexed) renders every ramp and
component state.

---

## 4. Migration playbook (R1-R5)

Ordering follows the audit's leverage ranking: tokens → the three
workhorse primitives → the mega-pages → IA. Each phase ends with the full
vitest suite + `next build` + budgets green.

> **Status:** the shell/nav/search portion of the IA work originally
> slotted for R5 shipped early as **R1** (app shell on ds primitives,
> grouped nav model in `lib/nav-model.js`, command palette, skip link +
> landmarks + route-change focus). Desktop keeps a **top bar** (not a
> left rail): tables are the product and keep the horizontal space; the
> palette is the power-user accelerator. The page-family migrations
> below are unchanged.

| Phase | Scope | How it maps onto the primitives |
|---|---|---|
| **R1 — workhorses + data spine** | `/rankings`, `/trending`, `/edge`, `/finder`, `/trades`, `/rosters`, `/waivers` | Every hand-rolled `<table>` → `DataTable` (the rankings `SortHeader` dies; `aria-sort` arrives everywhere). Page shells → `PageHeader` + `Panel`. Deltas → `Movement`. Spinners → `Skeleton*`. Also in R1: re-derive `CHART_COLORS` from `--chart-*`, re-point `display-helpers` class names at tokens, rewrite off-brand `app/error.jsx` on tokens, and fix the duplicate-contract fetch (in-flight promise dedupe in `lib/dynasty-data.js`) so the new skeletons aren't papering over a double download. |
| **R2 — terminal + overlays** | `/` terminal, `PlayerPopup`, `GlobalSearch` | Terminal panels → `Panel dense` + `StatTile` + `Sparkline`; `PlayerPopup` → `Drawer`; `GlobalSearch` → `Modal` + proper listbox semantics. Skip link + focus-ring pass across the shell. |
| **R3 — mega-pages** | `/trade` (3,044 L), `/draft` (4,999 L), `/settings` | Decompose against `Panel`/`Tabs`/`DataTable`/`Field`; kill the 178+158 inline styles; sticky tray & slider-in-scroll conflicts resolved with tokens' z-scale and dedicated controls. |
| **R4 — public league hub** | `/league` + 24 sections, league-comparison | 21-tab `SubNav` → grouped `Tabs`; the four copy-pasted ROS sections → ONE parameterized `DataTable` section; `shared-server.jsx` Card/Stat → `Panel`/`StatTile`; `next/dynamic` per tab (the 168 KB chunk dies). |
| **R5 — IA + nav + polish** | `AppShellWrapper` nav, mobile IA, light mode | One nav model derived from one data structure (desktop + mobile), `Icon` set replaces letter-icons, route-title map dies with `PageHeader` adoption; light-mode enablement (chart light steps + toggle); final a11y audit. |

**Rules during migration:** a page migrates wholesale (no half-token
pages); legacy `.card`/`Panel`/`Card` usage is deleted, not wrapped;
`frontend/lib/**` business logic, the 12 hooks, localStorage contracts, and
the 17 API routes are not touched except the named R1 perf fix.

---

## 5. Anti-patterns — never reintroduce

Seeded from audit §5; PR review checks against this list.

1. **No `repeat(auto-fit, minmax(...))` card walls.** Grids are explicit
   per breakpoint. If a layout "just wraps whatever fits", it isn't designed.
2. **No inline `style={{}}` for anything ds.css/tokens cover** (layout
   math like a computed width is fine; colors/spacing/fonts/radii never).
3. **No raw hex / rgba literals in components.** CI enforces zero hex in
   `ds.css`; treat JSX the same.
4. **No new font sizes, radii, shadows, breakpoints, or z-indices.** The
   scales are closed sets. A "13.5px looks better here" is a design bug.
5. **No second container.** If `Panel` can't express it, extend `Panel`.
   Same for tables: extending `DataTable` beats hand-rolling one.
6. **No margin-on-component rhythm** (`className="card" style={{marginTop}}`
   ×26 in the audit). Parents own spacing via gap.
7. **No ASCII/emoji iconography** — letters-as-icons, `▲▼`, `+/−`, `▾`,
   pictographs. Use `Icon`.
8. **No color-only meaning.** Direction gets an arrow, status gets a label,
   charts get labels/legend per the dataviz method.
9. **No spinner-and-"Loading..." pairs.** Async surfaces render skeletons
   sized to their content.
10. **No `outline: none`** without a `:focus-visible` replacement; no
    overlay without dialog semantics + focus trap + restore.
11. **No micro-type below `--font-size-2xs`** (11px), and no `--muted`-style
    sub-AA text for content that matters.
12. **No hover-only disclosure** — everything opens by click/Enter too.
13. **Gold is not a paint bucket.** One primary action per region; accent
    never used as large background fill or body-text color.
14. **No cycled chart palettes** — slots in fixed order; >6 series folds.

---

## 6. R0 file map

| File | What |
|---|---|
| `frontend/app/tokens.css` | Token layer (dark default + light scaffold + reduced-motion) |
| `frontend/app/ds.css` | Component styles (`.ds-*`, zero hex, zero CSS-in-JS) |
| `frontend/app/layout.jsx` | + next/font Inter & JetBrains Mono (surgical) |
| `frontend/app/globals.css` | + two `@import`s; legacy `--font/--mono` now resolve the loaded fonts (surgical) |
| `frontend/components/ds/*` | The library + `token-contract.js` |
| `frontend/app/design/*` | Living style reference (`/design`, unlinked, noindex) |
| `frontend/__tests__/components/ds/*` | DataTable behavior, Badge/Movement semantics, token contract |
