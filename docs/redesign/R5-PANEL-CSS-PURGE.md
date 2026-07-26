# R5 — legacy `.panel*` / `.terminal-*` CSS purge plan

**Status:** planned, not executed. **Do not run this until #551 (R3) and
#552 (R4) have merged.**

Deferred out of the R3 review batch on purpose: the block is a mix of
genuinely dead rules and live ones, so it has to be removed as a unit
after analysis rather than swept during a review fix. The analysis is
below so R5 executes instead of re-deriving it.

Line numbers are as of `4cccfd84` (`claude/redesign-r3-surfaces`) and
**will shift** once R3/R4 merge. Anchor on the selectors, not the
numbers; re-locate with the inventory command in §5.

---

## 1. Why the post-merge state is knowable now

R4 (`claude/redesign-r4-warroom`) touches **zero** files under
`frontend/components/terminal/`:

```
git diff --name-status 9ccdecea origin/claude/redesign-r4-warroom -- frontend/components/terminal/
  (empty)
```

R3 rewrites fourteen of them and deletes `terminal/Panel.jsx`. So the
merge is clean in that directory and **the post-merge state of every
consumer discussed here is exactly R3's state**. R4's grep hits against
`.panel-head` / `.panel--bare` are its inherited copy of the merge base,
not new usage — its own rewritten pages (`/draft`, `/trade`, `/trades`,
`/angle`, `/waivers`) introduce no legacy `.panel*` classes. The one
lookalike, `.draft-panel-header`, is a different selector and out of
scope.

This is the assumption most likely to age badly. Re-run the two commands
in §5 immediately before executing; if either returns a hit that isn't
listed here, stop and re-derive.

---

## 2. Block A — the legacy Panel primitive

`frontend/app/globals.css`, ~4730–4846, under the comment
`/* ─ Panel primitive ─ */`.

### DELETE — no consumer survives R3

| Selector | Was used by |
|---|---|
| `.panel`, `.panel:hover` | `terminal/Panel.jsx` (deleted by R3) |
| `.panel--bare`, `.panel--bare .panel-head` | `terminal/Panel.jsx`; `TeamCommandHeader` (`"tc-header panel panel--bare"`, rewritten by R3 onto ds `PageHeader`) |
| `.panel--collapsed .panel-body` | `terminal/Panel.jsx` |
| `.panel-head`, `.panel-head-text`, `.panel-head-actions` | `terminal/Panel.jsx` |
| `.panel-title`, `.panel-subtitle` | `terminal/Panel.jsx` |
| `.panel-collapse-btn`, `.panel-collapse-btn:hover` | `terminal/Panel.jsx` |
| `.panel-body`, `.panel-body--flush` | `terminal/Panel.jsx` |

`terminal/Panel.jsx` was the **sole** consumer of all of these. R3
deletes it and moves its eight consumers to the ds `Panel`, which is why
these become dead the moment R3 lands and not before.

#### Containment — checked, and the answer is **do not port it**

The legacy rules carried real performance behaviour: `.panel` had
`contain: layout paint`, `.panel-body` had `content-visibility: auto` +
`contain-intrinsic-size: 1px 320px`. **ds `Panel` has neither** —
verified, `ds.css` contains no `contain` or `content-visibility` on
`.ds-panel`. So R3's migration already dropped it.

The obvious follow-up is to port it onto `.ds-panel`. **Don't.** Both
halves are unsafe as a blanket rule now that `Panel` is the app-wide
container:

- **`contain: paint` would clip ds `Tooltip`.** `.ds-tooltip` is
  `position: absolute; bottom: calc(100% + …); left: 50%;
  transform: translateX(-50%)` — it deliberately escapes its anchor's
  box on all sides. Any tooltip on a panel's top row or near its side
  edges gets cut off. The legacy `.panel` never hit this because
  terminal panels didn't use ds `Tooltip`; every ds Panel can.
- **`contain-intrinsic-size: 1px 320px` was tuned for terminal panels.**
  Applied to every ds Panel across rankings, edge, finder, trade and
  draft — whose real heights vary enormously — it makes scrollbar length
  and scroll position jumpy as panels enter the viewport.

So this is **not** a silent regression to fix by restoring the rules; it
is a behaviour that has to be re-earned narrowly. If dashboard scroll
performance is measurably worse after R3, add an **opt-in** modifier
(a `Panel` prop or a dashboard-scoped class) applying containment only
to the stacked terminal panels, and measure first. Do not add either
property to the base `.ds-panel` rule.

Either way it does not block the purge — deleting the dead rules removes
nothing that is currently in effect.

### RETAIN — live

| Selector | Live consumers |
|---|---|
| `.panel-tabs` | `PlayerMarketMovement.jsx:138`, `TeamNewsFeed.jsx:53` |
| `.panel-tab`, `.panel-tab.is-active`, `.panel-tab:disabled` | the two above, plus `BuySellHold.jsx:220` |
| `.panel-tab` inside the touch-target media query (~6545) | same; grouped with `.signal-filter`, `.pmm-scope-tab`, `.pmm-sort-chip`, `.ticker-scope-tab` |

These are the rules buried inside the dead block — the reason a
find-and-delete on `.panel` is unsafe.

---

## 3. Block B — the legacy terminal grid (and the landmine)

`frontend/app/globals.css` 5225–5268, under
`/* ─ Responsive grid (mobile-first) ─ */`.

### DELETE — dead

`.terminal-grid` (3 occurrences: base, ≥720px, ≥1200px), `.terminal-col`
(base + ≥720px), `.terminal-col--left|center|right`. No JSX references
`terminal-grid` or `terminal-col` anywhere; R3's `TerminalLayout` uses
the CSS-module `.grid` / `.col` / `.colRight`.

### DELETE — but **only as a pair**

```css
/* 5234–5239 — base orders, apply at every width */
.panel--portfolio { order: 40; }  .panel--scouting { order: 50; }
.panel--movement  { order: 20; }  .panel--signals  { order: 10; }
.panel--news      { order: 30; }  .panel--actions  { order: 60; }

/* 5259–5260 — inside @media (min-width: 720px) */
.panel--portfolio, .panel--scouting, .panel--movement,
.panel--signals, .panel--news, .panel--actions { order: 0; }
```

> ### ⚠ The landmine
>
> **Deleting the `order: 0` reset while keeping the base orders silently
> reorders the desktop dashboard.**
>
> `order` is inert on a static block but live inside a flex or grid
> container. Post-R3, `.col` is `display: flex; flex-direction: column`
> at ≥768px — so if the base orders survive without the reset, every
> tagged panel sorts by that scale *within its column* at desktop, and
> the three columns quietly rearrange. Nothing throws; the page just
> renders in the wrong order.
>
> The inverse is harmless: deleting the base orders and keeping the
> reset leaves a no-op rule setting `order: 0` on already-0 elements.
>
> **So: delete both, or neither. Never the reset alone.**

Deleting both is safe because `terminal.module.css` now owns the entire
ordering contract inside its own `@media (width < 768px)` block, and
that block is self-contained — it sets `display: contents` on
`.col`/`.colRight` and the full 10→60 scale, with values identical to
the globals it replaces. Above 768px nothing sets `order` at all once
these go, which is correct: layout there is grid-area driven.

The `.panel--*` **hook classes on the components stay.** They are what
the module's `:global(...)` selectors target. Only the globals.css
`order` declarations go.

---

## 4. Optional — retiring `.panel-tabs` / `.panel-tab`

Not required for the purge, and **blocked on R3 merging** — all three
components are modified by R3, so re-tagging them from a `main`-based
branch would collide with a PR in the integration window. The analysis
is done so the work is mechanical once R3 lands.

**Answered: none of these are tabs, and none should become `Tabs`.**

The open question was whether the existing `role="tablist"` markup has
real tabpanel counterparts. It does not. Neither `TeamNewsFeed` nor
`PlayerMarketMovement` contains a single `role="tabpanel"` or
`aria-controls` — they are `role="tablist"` + `role="tab"` +
`aria-selected` on controls that own nothing. **Today's ARIA is already
wrong**, so the migration is a fix, not a like-for-like port; say so in
the PR rather than letting it read as cosmetic.

Once that is established, each control turns out to be a **filter over
one view**, not a switch between views — so the naive "tablist →
`Tabs`" mapping is wrong in all three cases:

| Component | Current | Correct target | Why |
|---|---|---|---|
| `TeamNewsFeed.jsx:53` | `.panel-tabs`, 3 values, "News scope" | ds `SegmentedControl` | filters one feed; ≤4 values |
| `PlayerMarketMovement.jsx:138` | `.panel-tabs`, "Window" | ds `SegmentedControl` | time-window filter over one table |
| `PlayerMarketMovement.jsx:155` | `.pmm-scope`, "Movement scope" | ds `SegmentedControl` | **second** fake tablist, different class — same defect, so the fix is wider than `.panel-tab` |
| `BuySellHold.jsx:220` | lone `.panel-tab`, `showDismissed` | ds `Button` + `aria-pressed` | binary toggle; **no tablist at all** |

Two traps in that table. The last row is the one a blanket migration
destroys — wrapping a binary show/hide in tab semantics and announcing a
one-tab tablist, which is worse than what ships today. The
`PlayerMarketMovement.jsx:155` row is the one a `.panel-tab`-scoped
grep misses entirely.

If all four move, additionally delete `.panel-tabs`, `.panel-tab`,
`.panel-tab.is-active`, `.panel-tab:disabled`, and remove `.panel-tab`
from the ~6545 touch-target selector list (leave the other four
selectors in that rule intact).

If all three move, additionally delete `.panel-tabs`, `.panel-tab`,
`.panel-tab.is-active`, `.panel-tab:disabled`, and remove `.panel-tab`
from the ~6545 touch-target selector list (leave the other four
selectors in that rule intact).

---

## 5. Execution order

1. **Re-verify** (do not skip — the whole plan rests on this):
   ```
   git diff --name-status <merge-base> origin/main -- frontend/components/terminal/
   git grep -nE "panel-head|panel-body|panel-title|panel-subtitle|panel-collapse-btn|panel--bare|panel--collapsed|panel-tabs|panel-tab" -- frontend/app frontend/components frontend/lib
   ```
   Expect: only the `.panel-tab(s)` hits in the three components of §4,
   plus `.draft-panel-header`. Anything else → stop.
2. Port `.panel` / `.panel-body` containment into `ds.css` **if** it is
   not already there (§2).
3. Delete Block A's dead selectors.
4. Delete Block B as a unit — dead grid rules **and** both `order`
   blocks together.
5. Optionally do §4, in the order re-tag → verify → delete CSS.

---

## 6. Verification — specifically, that desktop ordering survives

The claim to prove is narrow: **after the purge, nothing sets `order` on
a dashboard panel at ≥768px.** That is greppable, so make it a test
rather than a screenshot.

1. **Zero-reference check.** For every deleted selector, grep
   `frontend/app`, `frontend/components`, `frontend/lib` (exclude
   `.next/` — build artifacts contain the old classes and will produce
   false hits; this bit me while deriving this plan). Expect zero.
2. **Pairing assertion — ALREADY LANDED**,
   `frontend/__tests__/panel-order-pairing.test.js` (3 tests).
   I specified this originally as "assert `globals.css` contains no
   `order:` targeting `.panel--*`", which was wrong: that assertion is
   red today, when the rules are present and correct, so it could not
   be landed before the purge and would have to be written blind.
   It asserts the **pairing** instead, which holds across the purge:

   | state | result |
   |---|---|
   | today — both halves present | PASS |
   | **half deleted — the landmine** | **FAIL** |
   | after the purge — both gone | PASS |

   All three verified by mutating `globals.css` and re-running, so the
   guard is known to be non-vacuous rather than assumed to be. It also
   pins that the reset is declared *after* the base orders (equal
   specificity, so source order decides) and *inside* a `min-width`
   query rather than unconditionally.

   Because it is green before and after, it can land — and has landed —
   ahead of the purge, so the landmine is guarded during the window
   rather than after it.
3. **Existing suite.** `terminal-mobile-order.test.js` must stay green
   unchanged; it already pins `display: contents`, all six panel rules,
   their relative priority, and that the base `.col` box precedes the
   mobile block. Its two cascade assertions were verified non-vacuous
   against a pre-fix stylesheet, so a green there is meaningful.
4. **Manual, four widths** on `/` signed in: 390 / 767 / 768 / 1440.
   - 390 and 767: Movers/Watchlist lead; then signals → movement → news
     → portfolio → scouting → actions.
   - 768 and 1440: visual order matches **DOM order within each column**,
     and the three columns are in their grid-area positions. This is the
     assertion the landmine breaks; 768 is the boundary case and the one
     worth actually looking at.
5. **Build + budgets.** `npm run build`; all budgets pass. CSS should
   shrink — record the delta, it is the only quantitative evidence the
   purge did anything.
6. **E2E.** `.panel*` is not in the SEL registry (checked), so no
   selector should break. `tests/e2e/` belongs to the E2E workstream —
   if a spec does break, hand it over rather than editing the registry.

---

## 7. Scope note — and a measurement that should change R5's plan

This plan covers only the `.panel*` / `.terminal-*` block. Nothing here
clears the per-panel content classes, the `pos`/`conf` badge classes, or
the legacy `.card` system.

**The `.card` half is not a CSS purge at all, and it is much bigger than
the `.panel` one.** Measured against the branches rather than estimated:

| | files using `.card` |
|---|---|
| `origin/main` | 58 |
| cleared by R3 | 3 |
| cleared by R4 | 7 |
| **still using it after both merge** | **48** |

192 occurrences today, of which **86 sit in `/league` + `/league-comparison`
alone** — 31 of the 48 remaining files. Those two surfaces were never in
the R1-R4 scope (R2 rankings, R3 dashboard/news/edge/finder, R4
draft/trade/trades/angle/waivers), so nothing so far has touched them.

Two consequences worth deciding before R5 is planned as "polish":

1. **`.card` cannot be deleted; it has to be migrated.** Unlike `.panel`
   — whose sole consumer R3 removes, leaving genuinely dead rules — every
   one of these 48 files renders through `.card` today. Deleting the rule
   unstyles a third of the app. R5's `.card` work is a page migration
   (`/league` and `/league-comparison` onto ds `Panel`), with the CSS
   deletion as its last step, not its first.

2. **These surfaces are visibly off-palette right now.** The base rule is

   ```css
   .card { background: linear-gradient(180deg,
             rgba(20, 39, 79, 0.9) 0%, rgba(13, 29, 63, 0.92) 100%); … }
   ```

   A hardcoded pre-redesign **navy gradient** — not a token, and a
   gradient at all, which the design direction rules out. So once R2-R4
   land, `/league` and `/league-comparison` won't merely be
   "unmigrated": they will be the only surfaces still rendering in the
   old blue, sitting one nav click from redesigned pages. That is a
   visible product seam, not deferred cleanup.

Budget note for whoever scopes it: `/league` is the largest page in the
app (167.8 KB against a 170 KB budget — 2.2 KB headroom). R2, R3 and R4
each came in *under* their pre-migration size as legacy CSS and
components dropped out, so a migration is more likely to free headroom
than consume it — but it is the one page where that assumption should be
checked early rather than at the end.
