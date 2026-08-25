# V1-109 — mobile usability re-measured at 390×844

**Head:** `131abf9f9` (the dispatch SHA; `origin/main` at the time of measurement)
**Instrument:** `frontend/scripts/measure-mobile-usability.mjs` (new, this pass)
**Viewport:** 390×844, `isMobile`, `hasTouch`, DPR 3, production build, real backend,
real board (1,109 players served), authenticated session
**Raw output:** `mobile-390-current.json`, `mobile-390-after-fab-fix.json`

## Why re-measure at all

The row inherits four claims from the 2026-07 audit (`W26-F015`, `W26-F017`). Both
predate **#984** (PSI shell restyle across every route) and **#1003** (rankings
windowing). Under this repo's own rule — *no reproduction, no repair* — they were
claims, not findings, until re-measured. Two of the four turned out to have changed
materially, and one is fixed here.

## The instrument, and its control

The repo has been burned once by an instrument measuring itself (#760's
`setTimeout`-paced FPS harness), so this one refuses to run without passing a
control first: a synthetic page with targets of known size (30/44/48 px) and a 9 px
span. It must report exactly 3 targets, 1 undersized, smallest font 9 px, or it
exits 2 and voids the run. It passed on every run below.

It also **refuses to report zero for a page that did not render**. A route with no
`<main>` or no interactive targets is recorded `unavailable` with a reason rather
than as clean — on an accessibility sweep, "0 violations" and "the page never
loaded" look identical and mean opposite things.

## Measured — current head, before any repair

| route | targets < 44 px | smallest type | h-overflow | pinned overlaps | over-wide elements |
|---|---|---|---|---|---|
| `/rankings` | **163 / 170** (95.9%) | **9.0 px** (×36) | 0 px | 0 | 6 (all inside scrollers) |
| `/trade` | 20 / 30 (66.7%) | 10.2 px | 0 px | **1 — 44×44 px** | 0 |
| `/draft` | 397 / 555 (71.5%) | **9.3 px** (×72) | 0 px | 2 (1 px, `th`/`th`) | 10 (all inside scrollers) |
| `/rosters` | 31 / 48 (64.6%) | **9.0 px** (×54) | 0 px | 0 | 2 (inside scrollers) |

## Claim-by-claim verdict

### `W26-F015` — "/trade's sticky verdict bar is clipped by a floating action button"
**STILL REPRODUCED, and FIXED in this pass.**

Exact geometry before:

```
.trade-sticky-tray   y 714  h 74   full width (0–390)   z-index 35
.screenshot-fab      y 734  44×44  x 334–378            z-index 900
```

The FAB sat **entirely inside** the tray, occluding its right-hand 44×44 corner.
Root cause: both are anchored to the same bottom baseline, and the FAB's base rule
lifts it only `+16px` — which never clears a 74 px tray.

Fixed by giving the FAB a declared clearance above a pinned tray
(`frontend/app/globals.css`). **Measured after: 0 overlaps.**

One detail worth keeping, because it is the difference between "moved" and "fixed":
the first attempt put the mobile override inside the `@media (max-width: 768px)`
block at ~line 1880, which **loses on source order** to the identically-specific
base rule at ~3150. Overlap fell only 44×44 → 44×30 — mobile had silently taken the
desktop offset and dropped the 56 px nav term. The two rules are now adjacent, with
a comment saying why.

Pinned by `tests/e2e/specs/mobile-pinned-overlap.spec.js`, which asserts the
**invariant** (no two pinned boxes overlap) rather than the offset, so a future
redesign may move either element anywhere — it just may not stack one on the other.
Mutation: removing the clearance rules and rebuilding reproduces
`div.trade-sticky-tray x button.screenshot-fab — 44x44px` → RED; restoring → GREEN.

### `W26-F015` — "/draft's teams panel refuses to stack"
**NO LONGER REPRODUCES as a page-breaking defect.** `/draft` shows **0 px** of
horizontal document overflow. The over-wide elements that remain (`draft-table` at
1061 px, `draft-team-row-head` at 599 px) sit inside their own `overflow-x` scroll
containers — which is the pattern this codebase requires for wide tables, not a
defect. The two remaining "pinned overlaps" are adjacent sticky `th` cells sharing a
1 px border edge; the spec's threshold ignores ≤1 px for exactly this reason.

Reported as closed-by-later-work rather than repaired again.

### `W26-F017` — "873 of 900 interactive targets on /rankings are under 44 px"
**STILL REPRODUCES. Measured, NOT repaired in this pass** — see below.

The absolute count fell to **163 of 170**, but that is windowing (#1003) mounting
fewer rows, not a usability improvement: the **rate is essentially unchanged, 97% →
95.9%**. Reporting the count alone would have read as a 5× improvement that did not
happen. Worst offenders are the watchlist star buttons at **17×13 px**, repeated per
row.

### `W26-F017` — "type as small as 9.0px ships on three pages"
**STILL REPRODUCES, on exactly three pages:** `/rankings` 9.0 px (×36), `/rosters`
9.0 px (×54), `/draft` 9.3 px (×72). **Measured, NOT repaired in this pass.**

## Why the last two are reported rather than fixed

Not for lack of a fix — for lack of the authority to choose one.

- **Touch targets.** The correct repair for a 17×13 control in a dense data table is
  hit-area expansion (a pseudo-element), *not* growing the box — growing it changes
  row height, and row height is load-bearing for the windowing in `V1-106`, which is
  `VERIFIED` and frozen. But hit-area expansion is invisible to a
  `getBoundingClientRect()` measurement, so shipping it here would mean claiming a
  repair this instrument cannot verify. That is the synthetic "feels better" claim
  the dispatch forbids. It needs hit-area instrumentation first.
- **Type scale.** Raising the floor from 9 px is a change to the type ramp across
  three high-use routes — a design-token decision, which is `C8-PSI-01` / **V1-110**,
  and V1-110 is gated on undecided owner decision **`OD-05`** (premium token
  direction). Picking a type scale here would pre-empt that decision in the one lane
  told not to.

Both are recorded with exact numbers so whoever holds `OD-05` can act on evidence
rather than re-measure.

## Status

`V1-109` remains **`IN PROGRESS`**, and its level is **L4** — a production consumer —
which no local measurement can satisfy regardless. This pass closes one of its four
named defects with a mutation-proved fix and converts the other three from claims
into current measurements. Status column untouched; promotion is Integration's call.
