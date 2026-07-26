# WS-J — Roster Intelligence dashboard: design spec

**Status: specification only. No implementation, and none should start
from this document alone.** Every number it arranges is unbuilt, several
may turn out to be undefendable (see AUDIT.md F-1 and the three open
questions), and anything built now would be rebuilt. What follows is the
information architecture and the three encoding decisions that are
expensive to change later — chosen now so the engine work can proceed
against a known surface.

Context: `docs/roster-trade-intelligence/AUDIT.md`. Valuation policy:
`docs/league-intelligence/DECISIONS.md` ADR-001/ADR-003. Component rules:
`docs/DESIGN-SYSTEM.md`.

---

## 1. Where it lives — and an IA collision to settle first

`/intel` is **taken** (Sharp Tracker, in the Intel group) and the "Intel"
group means *market* signals. This surface is roster-facing, so it
belongs in the **Roster** group.

Proposed route: **`/gameplan`**, label "Game Plan", in the Roster group
beside Draft Board / Waivers / Team Strength. The content is a plan
(window, targets, partners, recommended trades, pick strategy), not a
report, and the name sits in the war-room register the design direction
already uses.

### The `/rosters` boundary — **decided: split by scope, not by page**

- **`/gameplan`** owns **one roster in depth** — snapshot, window,
  positional marginal strength, surplus/needs, targets, trades, picks.
- **`/rosters`** keeps **the league in comparison** — edge map, tiers,
  age curves, waiver wire.

Verified against the code, because the obvious framing (absorb it) is
wrong: `/rosters` is built on `buildAllTeamSummaries(sleeperTeams, …)`
over **all** teams, sorted and ranked against each other. It is a
league-comparison surface. Absorbing it into a roster-depth page would
drag league-scoped features into a roster-scoped one.

**Refinement worth carrying into the build — "per-position strength" is
not one duplicated thing, it is two different questions wearing one
name:**

| | `/rosters` | `/gameplan` |
|---|---|---|
| computes | `byGroup[pos] / groupAvg[pos]` | marginal value over replacement |
| denominator | **league average** (needs all 12 teams) | **your own roster's alternatives** |
| answers | "am I above or below the league at RB?" | "does my RB3 actually earn a start?" |

So the position bars **cannot simply move** — `/rosters` sorts and
compares on that ratio and would lose the input it is built from. The
duplication is nominal, not computational. Give them distinct names in
the UI and let neither recompute the other.

**The genuine overlap is `TradeTargetsCard`** (`app/rosters/page.jsx`
299–433), not the position bars. It computes weakest/strongest
positions, a surplus list, trade targets, and infers each opponent's
need — all roster-scoped, all squarely WS-J Zone 2 + Zone 3, and all on
crude proxies (ratio-to-league-average, hardcoded value cutoffs of
1200/8000/1500). That card is what should retire into `/gameplan`.

**Unrelated finding, flagged for the toggle rollout:**
`app/rosters/page.jsx:31` holds `const [valueMode, setValueMode] =
useState("full")` — local valuation state, feeding
`buildAllTeamSummaries`. It predates ADR-003 and will conflict with the
global valuation toggle. It needs folding into the global selector when
that lands, not preserving.

---

## 2. The page's argument

Thirteen content blocks is too many for thirteen panels — that is the
auto-fit card wall the design direction explicitly rejects. The page
makes one argument in reading order, and the blocks are subordinate to
it:

> **Where you stand → what you're made of → what to do → how much of
> this to believe.**

### Zone 1 — Standing (above the fold, no scrolling)

- **Competitive window** — the five probabilities (§4). This is the
  page's lead, not a badge in the header.
- **Roster snapshot** — a `StatTile` row: roster value, league rank,
  starter strength, age/window posture. Four tiles, not eight.

Zone 1 must survive being the only thing a user reads.

### Zone 2 — Composition

One panel, tabbed or segmented, **not four panels**:

- **Strengths / weaknesses** — by position, as a single ranked list with
  polarity, not two lists. One ordering, signed values; splitting them
  into "strengths" and "weaknesses" panels hides the middle, which is
  where most rosters actually live.
- **Surplus / needs** — the actionable projection of the same data.
  Deliberately adjacent, because surplus is what pays for needs.
- **Best-ball contributors** and **roster-clogger candidates** — two
  faces of the same question ("who is actually earning a spot"). Same
  table, one column that distinguishes them; not two tables.

### Zone 3 — Action

Ordered by how directly the user can act:

1. **Recommended trades** — concrete packages. Leads because it is the
   most specific.
2. **Trade partners** — who, and why (need alignment + acceptance).
3. **Target positions and players** — the shopping list, when no
   package is ready.
4. **IDP opportunities** — a filtered view of the same machinery, not a
   parallel system. Gated on `idpEnabled` per league.
5. **Pick strategy** — slowest-moving, so last.

**Blocking constraint from AUDIT.md F-1:** mixed offense↔IDP packages
have no validated normalization. The UI needs a defined state for
"cannot be compared" — visibly suppressed or labelled un-normalized, per
the audit. It must never be a blank cell, a zero, or a package silently
ranked among comparable ones. This is the single most likely place for
the F-1 defect to reappear as a UI bug.

### Zone 4 — Provenance

**Model status** is not a footer. It is a persistent, quiet strip — and
it becomes a `Banner` **only when something is degraded** (stale inputs,
a suppressed model, a missing projection source). On a healthy day it is
one line of small text with a timestamp.

---

## 3. Design problem 1 — confidence visible without dominating

Every value carries `dataConfidence`, `projectionConfidence`,
`roleConfidence`, `marketConfidence`, `acceptanceConfidence` and more.
The failure mode is a page of asterisks.

**The governing invariant, and the thing to test:**

> On a fully-confident page, **zero confidence chrome renders.**
> Deviation from the plain rendering *is* the signal.

Caveats become the exception rather than the wallpaper, and the cost of
the system is paid only where it buys something.

### Four tiers, in order of how little space they take

**Tier 0 — precision is the encoding.** The most important idea here,
and it costs nothing: *the number's own resolution carries its
confidence.* You cannot mislead with a digit you did not print.

| Bucket | Renders as |
|---|---|
| high (≥ 0.67) | `+3.4 pts` · `#4` — point estimate, full precision |
| medium (0.34–0.66) | `+3 pts` · `#4–6` — coarsened, or a narrow band |
| low (> 0) | `+2 to +5` · `top 10` — a range or a class, **never** a point estimate |
| none (0) | no number; "insufficient evidence" |

**Tier 1 — the tick marker.** Reuse the confidence language **already
shipped**: `confidenceBucket()` and the `ds-movement__ticks` motif in
`components/ds/Badge.jsx`. Three ticks, filled to the bucket. Rendered
only for medium and low. No new visual vocabulary; a user who has read a
`Movement` already knows it.

**Tier 2 — the binding constraint, one phrase.** Show *which* dimension
limits the number, not all five: "limited by role confidence". One
clause. Which dimension binds is a model output, not a UI computation.

**Tier 3 — the full breakdown, on demand.** All dimensions in a
`Tooltip` (values that are already focusable) or an expanded table row.
Never inline.

### Hard rules

- **Never color alone**, and **never the status palette.**
  `--positive` / `--negative` / `--warning` mean good/bad. Low
  confidence is not a bad outcome, it is a thin one; painting it amber
  tells the user something false and burns a reserved token.
- **Low confidence suppresses ranking, it does not demote.** An item
  below the confidence floor goes in a separate "insufficient evidence"
  group, **not** at the bottom of the sorted list — bottom-of-list reads
  as *worst*, not as *unknown*. This is a real misreading, not a
  hypothetical one.
- **One confidence per displayed value.** Five bars beside one number is
  the wall this section exists to prevent.
- Confidence never changes a number's **position** in a layout, only its
  rendering. Otherwise the page reflows as data refreshes.

---

## 4. Design problem 2 — the competitive window

Five probabilities, not a label. Collapsing them to "Contender" throws
away the only interesting part.

### Form

The five outcomes lie on an **ordered axis** (rebuild → … → win-now).
Per the dataviz form heuristic, ordered-scale share is a **diverging
stacked bar centred on the neutral middle outcome** — not a categorical
stacked bar, not five tiles, not a gauge.

Why this form specifically:

- **One bar reads as one distribution.** Five tiles read as five
  independent facts and invite the reader to take the largest as *the*
  answer.
- **Centring on neutral makes the shape legible at a glance**, which is
  the actual information: 41/39 split across two adjacent outcomes is a
  completely different decision from 41/12/12/12/23, even though both
  have the same modal outcome.

### Copy rules

- The headline names the modal outcome **with its probability
  attached** — "Contend 41%", never "Contender".
- **When the top two are within ~10 points, the headline names both** —
  "between retool and contend". The ambiguity is the finding; asserting
  one of them is a fabrication.
- A one-word decisiveness read ("concentrated" / "genuinely uncertain")
  earns its place. A single-word *label* does not.

### Color — computed, not eyeballed

The project has **no diverging pair.** `--chart-1…6` is categorical;
`--positive`/`--negative` are reserved status (and green↔red is the
worst possible CVD choice, besides moralising "rebuild = bad").

Proposed poles from the existing chart family, blue ↔ orange (a
warm/cool pair, which the anti-pattern catalog names as a succeeding
one), with a neutral gray midpoint:

| Slot | Value |
|---|---|
| rebuild pole | `--chart-2` `#3987e5` |
| midpoint | neutral gray (`--neutral-400` `#8b82a3` family) |
| contend pole | `--chart-6` `#d95926` |

**Validated with `scripts/validate_palette.js`, both modes:**

```
poles, dark  (surface #14111c): ALL CHECKS PASS  — CVD ΔE 26.8 protan / 32.4 tritan
poles, light (surface #fdfcfe): ALL CHECKS PASS  — same separation
```

Recorded so it is not re-litigated: running the **three**-colour set
through the validator FAILs the chroma floor on the midpoint. That is
**correct and expected** — a diverging midpoint is supposed to read as
nothing. Do not "fix" it by saturating the middle; that is itself an
anti-pattern (a hue at the diverging midpoint). Validate the poles;
check the intermediate steps for lightness monotonicity toward the
midpoint.

The two intermediate steps do not exist yet — see §6.

### Mark rules (from the dataviz spec, non-negotiable)

- 2px **surface gap** between segments — not borders.
- Labels inside a segment only when they fit with padding; otherwise
  outside the bar or in the tooltip. Small probabilities will not fit —
  plan for it rather than clipping.
- Legend present (5 series); direct-label selectively, not every
  segment.
- Per-segment hover tooltip.
- A table view of the same five numbers must exist — this is a value
  users will want to read exactly.
- Size the container to include the label band; no nested scrollbar.

### The one assumption to confirm

This form is correct **iff** the five outcomes are (a) mutually
exclusive, (b) sum to 1, and (c) genuinely ordered.

**Intended as all three** per the coordinator — to be confirmed against
the engine when the window actually lands, since intent and output can
diverge. If it comes back as unordered scenarios, the diverging form is
wrong and this becomes a plain categorical stacked bar; §4's palette
work still holds, but the centring and the two intermediate ramp steps
do not.

---

## 5. Design problem 3 — seven value types must stay distinct

Market, consensus, league-adjusted, ROS, contender, rebuilder, and
roster-specific marginal. The UI is where these get accidentally merged
— and AUDIT.md F-1 is proof the same class of error already shipped in
the backend (KTC points added to IDPTC points).

### Mechanisms

1. **No bare numbers.** Every value renders with a **type chip** — a
   short, fixed, always-present label. A number without a chip is a bug.
2. **A column never mixes types.** The column header names the type. If
   two types must appear together, they are two columns.
3. **The UI performs no arithmetic across types.** No delta cell between
   market and league-adjusted unless the *engine* emits that delta as a
   defined output. If the engine doesn't emit it, the UI doesn't compute
   it. This is F-1's exact failure mode, one layer up.
4. **Distinguish by typography and placement, not hue.** Primary value:
   larger, tabular figures. Secondary: smaller, chipped. Seven hues
   would exceed the categorical ceiling, collide with the series
   palette, and fail CVD.
5. **One comparison surface, opt-in.** A single "value lens" (drawer or
   table) is the *only* place the seven appear together — as named
   columns, which is the one context where seeing them side by side is
   safe. Everywhere else shows the primary plus at most one labelled
   secondary.

### Global valuation toggle — what "no local valuation state" forbids

Per ADR-003 the toggle is global, lives in the R1 shell, and is my
workstream. Concretely, this page must not have:

- a per-panel or per-table valuation dropdown;
- a "compare mode" that changes which value is **primary** locally;
- a URL/query param that overrides valuation for this page only;
- component state deriving a value type from anything but the global
  selector.

The value lens (mechanism 5) is compatible: it *displays* all seven
side by side without changing which one is primary anywhere.

Until LI Phase 3 promotes, `leagueAdjustedDynastyValue == consensusValue`
(ADR-003's no-op default). **The UI must still label them distinctly**
even while they are numerically equal — otherwise the day they diverge,
every screenshot, habit and support answer built on the current page
becomes wrong.

---

## 6. ds primitives — used, and the genuine gaps

**Covers the spec as-is:** `Panel` (incl. `collapsible`), `PageHeader`,
`StatTile`, `DataTable` (grouping via `renderBeforeRow` should cover the
"insufficient evidence" group — verify at build time), `Tabs`,
`SegmentedControl`, `Badge` / `StatusIndicator` / `Movement`, `Tooltip`,
`Modal` / `Drawer`, `Banner`, `EmptyState`, `Skeleton`, `Sparkline`.

**Genuine gaps — flagged, not built** (per the frozen-contract rule, and
because a primitive with one speculative consumer is a liability):

1. ~~**A standalone confidence affordance.**~~ **CLOSED** — `Confidence`
   shipped in `components/ds/Badge.jsx`, exported from the barrel,
   demoed on `/design`, 20 tests. Pure addition; `Movement` untouched.
   §3's tiers 1 and 2 are now buildable as written: `showWhen`
   ("degraded" by default) enforces the quiet-by-default invariant in
   the primitive rather than in each caller, and `limitedBy` carries the
   single binding dimension. Tier 0 (precision as the encoding) is a
   formatting decision for the page, not a component.
2. **A diverging distribution bar.** `Meter` is single-value,
   single-series; `Sparkline` is a series over time. A 100%-stacked
   diverging bar exists nowhere. Build it **page-local first** and
   promote to `ds/` only when a second consumer appears.
3. **Diverging ramp tokens.** `--chart-*` is categorical;
   `--positive`/`--negative` are reserved status. §4 needs 5 ordered
   steps (two poles — validated above — plus two intermediates and a
   neutral midpoint) as real tokens, added to `tokens.css` and the
   `token-contract.js` contract, validated in both themes.

Nothing else in this spec requires a new primitive. If a build turns up
a fourth gap, that is a signal to re-read the spec before adding one.

---

## 7. Deliberately not specified

- **Exact copy, thresholds, and bucket boundaries** — these follow the
  engine's actual output distributions. The 0.34/0.67 buckets in §3 are
  the existing `confidenceBucket()` boundaries, reused for consistency,
  not independently justified.
- **The five outcome names** — engine's to define (§4).
- **Responsive breakpoints and column assignment** — follow the R3
  dashboard pattern (explicit columns by information role, 3 → 2 → 1,
  never auto-fit). Note the R3 lesson recorded in
  `docs/redesign/R5-PANEL-CSS-PURGE.md` §3: if panels reorder across
  columns on mobile, the wrappers need `display: contents` **and** the
  base rule must precede the mobile media block, or the reorder is
  silently inert.
- **Anything downstream of AUDIT.md's three open questions** —
  normalization evidence, the acceptance model, and the projection
  source. If normalization has no defensible answer, §2's mixed-package
  state is not a nicety, it is the whole feature for that block.
