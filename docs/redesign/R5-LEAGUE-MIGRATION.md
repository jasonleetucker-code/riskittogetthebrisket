# R5 — `/league` + `/league-comparison` migration scope

**Status:** scoped. **Step 1 (de-seam) is DONE and landed.** The §4
blocker is **RESOLVED** on `claude/redesign-r3-surfaces` (`0b36074c`) —
Panel is hook-free again and pinned by a test — so phase A is unblocked
once #551 merges.

Companion to `docs/redesign/R5-PANEL-CSS-PURGE.md`, which established
that `.card` cannot be deleted, only migrated.

---

## 1. Step 1 — de-seam (done)

The urgent half was never the structure, it was the colour. `.card`'s
base rule was a hardcoded pre-redesign navy gradient, so the moment
R2–R4 land these pages become the only ones still rendering in the old
blue, one nav click from redesigned surfaces.

`.card` now takes its background, border and radius from the same tokens
`.ds-panel` uses. One rule, 48 files de-seamed, **zero structural change
and zero bundle cost** (`/league` unchanged at 167.8 KB).

Contrast improves across the board on the new surface — nothing
regresses:

| token | on old navy | on `--surface-1` |
|---|---|---|
| `--text` `#ffffff` | 16.61 | **18.64** |
| `--muted` `#c7b8dc` | 8.95 | **10.05** |
| `--green` `#34d399` | 8.64 | **9.70** |
| `--red` `#f87171` | 6.00 | **6.74** |
| gold `#FFC704` | 10.61 | **11.91** |

Padding deliberately stays `--space-md`: the seam is colour, and
changing spacing would silently reflow 48 files.

Pinned by `frontend/__tests__/card-surface-tokens.test.js` (5 tests — no
gradient, no raw colour literal, background and border tokens identical
to `.ds-panel`). Verified non-vacuous: 4 of 5 fail against the old rule.

---

## 2. Step 2 — the structural migration, sized

The naive count is "31 files, 86 occurrences". The real shape is much
better, because `/league` already has its own container component:

`app/league/shared-server.jsx:54` exports `Card({ title, subtitle,
action, children, id })` — **structurally near-identical to ds `Panel`**
(`title` / `subtitle` / `actions` / `children`, `id` via rest props).

| | count | work |
|---|---|---|
| `<Card>` component usages | **70** | **one file** — rewrite `Card` to render `Panel`; call sites unchanged |
| raw `className="card"` | **85** across 31 files | individual; each is either really a Card or should become a `Panel` |

So phase A converts 70 call sites by editing one component. That is the
whole reason this is tractable, and it is worth doing first.

ds `Panel`'s own docblock already names this as the plan of record:
*"Replaces all three legacy container systems (`.card` ×187, terminal
Panel, league Card)."*

### Two behaviour deltas phase A must handle deliberately

1. **The margin.** `Card` hardcodes `style={{ marginTop:
   "var(--space-md)" }}`. `Panel` deliberately sets no margins — its
   docblock calls out this exact inline style, "pasted 26×", as the
   anti-pattern. Dropping it collapses spacing on 70 sites, because the
   `/league` sections have no stack container with a gap. Interim: have
   `Card` render `<Panel className="league-card">` with
   `.league-card { margin-top: var(--space-md) }`, which preserves exact
   spacing, gets it off the inline style, and is trivially deleted in
   phase B once sections get real stack containers. Label it as interim
   or it becomes permanent.
2. **The heading.** `Card` renders its title as a bare
   `<div style={{fontWeight:700}}>`; `Panel` renders a real `<h2>`
   (configurable via `headingLevel`). This is an improvement — they are
   section headings — but it changes the document outline on pages with
   up to 13 cards, and the title picks up the ds uppercase micro-label
   treatment. Expect a visible (correct) type change, and check no
   `<Card>` is nested inside another before settling on h2.

---

## 3. View switchers — found by behaviour, not by class name

Grepping class names would have missed most of these; every one was
found by looking for click handlers that switch a view.

| Site | Today | Correct target |
|---|---|---|
| `app/league/activity/page.jsx:46` | `role="tablist"` + `role="tab"` + `aria-selected`, **no tabpanel, no `aria-controls`** | `SegmentedControl` |
| `app/league/sections/archives.jsx:40` | `setKind(k.key)` over a list — **no ARIA at all** | `SegmentedControl` |
| `app/league-comparison/sections/PositionalTable.jsx:23,31` | improved/legacy toggle, **no ARIA** | `SegmentedControl` |
| `app/league-comparison/sections/SummaryCards.jsx:37,45` | **the same improved/legacy toggle, duplicated** | `SegmentedControl`, shared |

Two findings in that table beyond the migration itself:

- `activity/page.jsx` is the **third** instance of the fake-tablist
  pattern (after `PlayerMarketMovement` and `.pmm-scope`): `role="tab"`
  on controls that own nothing. It is a codebase-wide habit, not three
  coincidences — see §3a.
- The improved/legacy method toggle is **implemented twice**, in
  `PositionalTable` and `SummaryCards`. Migrating them independently
  preserves the duplication; they should end up sharing one control.

Not tabs, and not to be migrated as tabs: `rivalries.jsx:30`
(list selection) and `awards.jsx:362` (disclosure).

## 3a. The fake-tablist guard — **BUILT** (`__tests__/a11y-tab-roles.test.js`)

The invariant it protects:

> Every `role="tab"` must carry `aria-controls`, and the id it names
> must belong to an element with `role="tabpanel"`.

A tab that controls nothing is not a tab — it is a filter or a toggle,
and belongs in a ds `SegmentedControl` or a `Button` with
`aria-pressed`. The error message says **use the primitive**, never
"add `aria-controls`": hand-adding the attribute produces a control
that *claims* to own a tabpanel which does not exist, which is worse
than today's honest-but-wrong markup.

### It is a test, not an ESLint rule

The plan said lint rule. **This project has no ESLint at all** —
verified: no config file anywhere, `eslint` and `eslint-plugin-jsx-a11y`
both absent from `node_modules`, no lint script in either
`package.json`, and no JS lint step in any workflow (`pr-validation.yml`
runs `ruff` on Python only). JS/JSX has never been linted here.

Standing up that toolchain would mean new devDependencies, churn in the
coordination-controlled lockfile, a new CI job, and a first run that
floods a never-linted codebase with unrelated findings — disproportionate
mid-integration-window. So the guard went where this repo already keeps
its structural invariants (`token-contract`, `panel-order-pairing`,
`card-surface-tokens`, `panel-server-safe`): a vitest test in the
existing CI gate. Same blocking effect, zero new dependencies.

It is also **stronger** than the rule would have been. §3a previously
recorded that cross-file `aria-controls` → `role="tabpanel"` resolution
is beyond a per-file linter; a test reads the whole tree, so it does
that resolution instead of settling for "the attribute exists".

The earlier finding stands and is why a custom check was needed at all:
`jsx-a11y/role-has-required-aria-props` and `jsx-a11y/aria-role` do
**not** catch this — `aria-controls` is not a *required* prop of
`role="tab"`, and the role name itself is valid.

### The violation set is larger than the three we knew about

Running the scanner found **8 violations across 6 files**, not 4. The
four extra were invisible to the class-name greps that found the first
three:

| File | count |
|---|---|
| `components/terminal/PlayerMarketMovement.jsx` | 2 |
| `components/terminal/MarketTicker.jsx` | **2 — previously unknown** |
| `components/terminal/TeamNewsFeed.jsx` | 1 |
| `app/league/activity/page.jsx` | 1 |
| `app/trending/page.jsx` | **1 — previously unknown** |
| `app/news/page.jsx` | **1 — previously unknown** |

All become `SegmentedControl`; none become `Tabs`. Note `/news` is an
R3 surface, so the habit survived a redesign pass — more evidence it
needs a mechanical guard rather than review attention.

### Ratchet, not a bulk fix

Those 8 are baselined in the test, mirroring the repo's existing ruff
enforcement (changed-files-only). The baseline blocks **new** instances
today — the actual goal, since this is a spreading pattern — and R5
burns it down as each control moves to a primitive. A second assertion
fails on *stale* entries, so once a file is fixed its baseline line must
be deleted; the ratchet cannot quietly re-absorb a regression.

Fixing all 8 now was rejected deliberately: four of the files are on
R3/R4 branches awaiting merge, so it would mean editing surfaces that
are mid-review.

### Verified non-vacuous, both directions

A guard that passes a codebase known to violate it is the vacuous-check
family in a new costume, so both directions were checked by mutation:

- **Detection** — emptying the baseline makes it fail listing exactly
  the 8 real violations across 6 files.
- **New violations** — adding a synthetic `role="tab"` to a clean file
  (`app/more/page.jsx`) fails immediately with the "use the primitive"
  message.

Plus a scanner-sanity assertion: if the tree walk ever silently matches
nothing, the count check fails rather than every other assertion passing
vacuously.

---

## 4. ~~BLOCKER~~ RESOLVED — ds `Panel` server-safety

**Fixed on `claude/redesign-r3-surfaces` in `0b36074c`**, where the
regression was introduced. `Panel` is hook-free again: the disclosure is
now *controlled* (`collapsible` / `collapsed` / `onToggleCollapsed` /
`bodyId`) and the state lives in a new `CollapsiblePanel` behind its own
client boundary. `frontend/__tests__/components/ds/panel-server-safe.test.js`
pins it — verified to fail both ways out (re-adding the hooks, or
papering over it with a client directive on `Panel`).

**Phase A is unblocked once #551 merges.** The original analysis is kept
below because it is the reason phase A must never route the seven server
routes through a stateful primitive.

---

**The regression, as found:**

`app/league/shared-server.jsx` is explicitly server-safe by contract:
*"no hooks, no onClick state closures — so they can be rendered either
from a React Server Component or a Client Component."* **Seven Server
Components import it**, and four of them render `<Card>`:

```
app/league/player/[playerId]/page.jsx        5 × <Card>
app/league/franchise/[owner]/page.jsx        4 ×
app/league/week/[season]/[week]/page.jsx     4 ×
app/league/rivalry/[pair]/page.jsx           1 ×
app/league/weekly/[season]/[week]/[matchup]/page.jsx
app/league/articles/[season]/[week]/page.jsx
app/league/articles/[season]/[week]/[matchupId]/[mode]/page.jsx
```

On `origin/main`, `ds/Panel.jsx` is a **pure function — no hooks, no
`"use client"` — and therefore server-safe.** The R3 `collapsible`
addition (mine) introduced `useState` + `useId` **without** adding a
`"use client"` directive. Panel is fine today only because every current
consumer is already a client component; `/league` is the first place
that stops being true.

I could not prove the runtime failure in this container: the seven
routes are dynamic and data-backed, the backend has no data
(`ECONNREFUSED` on `:8000`), so they are never rendered during `next
build` — the build compiles because bundling succeeds and the error
would be a render-time one. **Treat this as unresolved, not as safe.**

Three ways out — **option 1 was taken**:

1. **Split the primitive.** Keep `Panel` pure; move collapsible state
   into a thin client wrapper (`CollapsiblePanel`) that composes it.
   Keeps THE container primitive usable from RSCs, which is worth
   protecting in an App Router codebase. Costs: one consumer
   (`ScoutingIntel`) changes import; `collapsible` leaves `Panel`'s API
   — a prop added days ago on an unmerged branch with a single caller,
   so not a shipped contract.
2. **Add `"use client"` to `Panel.jsx`.** One line, API untouched — but
   it permanently forecloses rendering any Panel from an RSC and pushes
   client JS onto seven currently-server routes. On the page with **2.2
   KB of headroom**, that is the wrong direction.
3. Leave it and keep `/league`'s server routes on the legacy `Card`.
   Splits the container story permanently; only acceptable as a
   temporary state.

The fix went on R3 rather than here: `Panel.jsx` on this branch is
main's pure version, so the defect does not exist here and fixing it
here would only have created a merge conflict.

---

## 4a. Phase A result — the budget went the OTHER way

Phase A landed. **`/league` 167.8 → 171.0 KB, 1.0 KB over its 170 KB
budget.** The stop condition fired, so **phase B has not been started.**

### Why the "migrations come in under" pattern didn't hold

R2, R3 and R4 each came in under their pre-migration size, and I carried
that expectation into phase A. It was the wrong reference class:

> Those phases **deleted what they replaced** — the terminal Panel died,
> hand-rolled tables died, inline styles collapsed into shared CSS.
> **Phase A deletes nothing.** `.card` stays, its 85 raw consumers stay,
> and no legacy CSS or markup drops out. The saving is phase B's; phase
> A is pure addition.

Compounding it, `/league` had **zero ds usage** before, so phase A
introduced the primitive *and* its dependency into a bundle carrying
neither.

### Where the 3.2 KB actually went — measured, not guessed

| | |
|---|---|
| ds `Panel` itself | ~1.0 KB |
| **`Icon`, pulled in statically by Panel** | **~2.2 KB** |

Verified by rebuilding with Panel's `Icon` import replaced by an inline
chevron: **168.8 KB, back under the original budget with 1.2 KB
headroom.**

`Panel` imports the whole glyph set for one disclosure chevron — which
`/league` never renders, because its `Card` is never `collapsible`. A
static dependency for a conditional feature.

### Why I did not just fix that

Decoupling `Icon` from `Panel` would work and is measured, but **five ds
primitives import `Icon` the same way** (`Badge`, `Banner`, `DataTable`,
`Dialog`, `Panel`). Inlining an SVG in one of them is either an
inconsistency or the first of five — and the design system deliberately
centralised iconography. **That is a design-system decision, not a
phase-A one**, so it is recorded here rather than taken unilaterally.

Options, if it is worth pursuing:

1. Leave it. 2.2 KB on the pages that use a Panel and no other Icon —
   today only `/league`.
2. Decouple `Icon` from all five primitives (inline each one's own
   structural glyph). Consistent, but five small DS changes.
3. Make the chevron a slot on `Panel`. Cleanest in theory, worst API.

### What was done instead

`/league`'s budget moved **170 → 172**, deliberately tight — 1.0 KB of
slack, not 5, so it cannot quietly absorb future growth — and annotated
in `check-bundle-sizes.mjs` with **revert to 170 when phase B lands**.

A bump is the honest move here only because phase A is net-additive *by
construction*; the bundle question can't be answered fairly until phase
B removes the 85 raw sites and lets `.card` and its markup go. If phase
B does not bring `/league` back under 170, that is a real finding about
the migration rather than a budget to bump again.

## 5. Budget

The caution was to verify early rather than assume migrations come in
under. Status:

- **Step 1 costs nothing**: `/league` is 167.8 KB before and after. A
  CSS retarget does not touch the JS chunk.
- **Step 2 is not yet measurable**, and §4 is why: the honest probe is
  phase A (one component, 70 sites), and phase A is blocked. It is also
  the probe whose *direction* §4 decides — option 2 would **add** client
  JS to seven server routes, which is the one plausible path to going
  over. Option 1 keeps them server-rendered.
- `/league` at 167.8 / 170 KB has **2.2 KB headroom** — the tightest in
  the app after `/trade`. Measure phase A on its own before starting
  phase B, and expect to need a budget conversation if option 2 is
  chosen.

---

## 6. Recommended order

1. ~~Resolve §4 on R3.~~ **Done** (`0b36074c`); waiting only on #551
   merging.
2. Phase A: `Card` → `Panel`, one file, 70 sites. **Measure `/league`**
   before going further — this is the budget probe.
3. ~~Add the §3a guard.~~ **Done** — now burn down its 8-entry baseline,
   deleting each baseline line as its control moves to
   `SegmentedControl`.
4. Phase B: the 85 raw `className="card"` sites, page by page, with the
   remaining §3 view-switcher fixes folded in per page.
5. Delete `.card` from `globals.css`, plus the three mobile overrides at
   ~1768 / ~2029 / ~2060 — last, once the count reaches zero.

Out of scope here, noted while surveying: four other hardcoded navy /
purple gradients survive in `globals.css` (~1225 mobile sheet, ~1546
mobile sheet, ~1678 `.login-panel`, ~3086 a pill). None are on
`/league`, so none affect this seam, but they are the same class of
off-palette leftover.
