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

Worth keeping when the rules go: `.panel-body` carried
`content-visibility: auto` + `contain-intrinsic-size: 1px 320px`, and
`.panel` carried `contain: layout paint`. That is a real mobile
performance behaviour, not decoration. Confirm the ds `Panel`'s
equivalent containment is in `ds.css` before deleting, and if it is
absent, port it rather than dropping it — a silent loss here shows up as
jank on the dashboard where 6+ panels stack, which is precisely where it
was introduced.

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

Not required for the purge. If R5 wants the block gone entirely, three
components must be re-tagged **first**, and they are not the same shape:

| Component | Current | Correct target |
|---|---|---|
| `PlayerMarketMovement.jsx:138` | `.panel-tabs` with `role="tablist"`, `aria-label="Window"` | ds `Tabs` or `SegmentedControl` |
| `TeamNewsFeed.jsx:53` | `.panel-tabs` with `role="tablist"`, `aria-label="News scope"` | ds `Tabs` or `SegmentedControl` |
| `BuySellHold.jsx:220` | a lone `.panel-tab` for `showDismissed` — **no tablist, no tabpanel** | ds `Button` (toggle, `aria-pressed`) — **not** Tabs |

That third row is the trap: a blanket "migrate every `.panel-tab` to
Tabs" would wrap a binary show/hide toggle in tab semantics and announce
a one-tab tablist. Check the ds control-choice rule in
`docs/DESIGN-SYSTEM.md` before picking `Tabs` vs `SegmentedControl` for
the first two — both are ≤4 values, which is `SegmentedControl`
territory unless they genuinely own a tabpanel.

Also verify whether the existing `role="tablist"` markup has real
`tabpanel` counterparts. If it does not, today's semantics are already
wrong and the migration is a fix, not a like-for-like port — worth
saying so in the PR rather than letting it read as cosmetic.

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
2. **Single-owner assertion — add this test.** Extend
   `frontend/__tests__/terminal-mobile-order.test.js` with a case
   asserting that `globals.css` contains no `order:` declaration
   targeting a `.panel--*` selector, i.e. the ordering contract lives in
   exactly one file. This is what makes the §3 landmine unrepeatable —
   a future half-deletion fails a test instead of shipping.
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

## 7. Scope note

This plan covers only the `.panel*` / `.terminal-*` block. The wider R5
global-class purge (per-panel content classes, `pos`/`conf` badge
classes, the legacy `.card` system) is separate and larger. Nothing here
should be read as clearing those.
