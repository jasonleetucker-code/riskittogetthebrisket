# V1-123 — Browser / workflow matrix — scoping

**Row:** `V1-123 | Browser / workflow matrix | C10-CLOSE-03 | L5 | NOT STARTED | L4 | production verification`
**Spec:** `docs/C_SERIES_REPLAN_AND_COMPLETION_CONTRACT.md` §13.3 — *"Exercise the real authenticated application
on desktop and true mobile widths across the major routes and workflows, including
populated/empty/stale/error states."*

This is a scoping pass, not an implementation. No test code is added here. Goal: turn an
open-ended "test everything" line into a bounded, ordered, checkable list — matching how every
other row in `docs/VERSION_1_COMPLETION_CONTRACT.md` this session was closed (real evidence
against a real deployed session, read and cited, never inferred).

## 1. What already exists, and what it is not

Three coverage classes exist in this repo today, and they answer different questions:

| class | runs against | proves |
|---|---|---|
| `tests/e2e/specs/*.spec.js` (local) | a freshly built local stack (`next build` + `next start`, backend on :8000) | the code is correct, on a build that matches `main` |
| `tests/e2e/specs/prod-auth/*.spec.js` | the real deployed site, a real ephemeral `guest_pass` session | the **deployed** build, **consumed** by a real session — the L4 bar every other row this session closed on |
| direct fetches against `https://chaseupside.com/api/public/*` | production, no session | public data correctness (used ad hoc this session for the Team Assignment check) |

§13.3's own wording ("the real authenticated application", "desktop and true mobile widths")
matches the **prod-auth** class exactly — the same class V1-45/V1-56/V1-62/V1-109/V1-111/V1-131
already used. Local specs are not evidence for this row, but they are the fastest path to
writing a prod-auth spec: the hard design work (what to assert, how to navigate, which selectors
are stable) is already solved in most cases, and every prod-auth spec built this session
(V1-45, V1-62, V1-109) ported an existing local spec's logic rather than designing from
scratch.

**Existing prod-auth coverage** (8 files, all built across V1-27/45/56/62/109/111/131 this
program, not new this pass):

| file | surface | viewport | state |
|---|---|---|---|
| `v1-111-premium-rankings.spec.js` | `/rankings` | desktop + mobile | populated |
| `v1-131-nav-gating.spec.js` | shell nav (Market menu, palette, `/more`, drawer, hard-reload network invariant, `/consensus-edge` reachability) | desktop + mobile | populated + the `available`/`unavailable` capability branch |
| `v1-27-lineup-render.spec.js` | `/rosters`, terminal portfolio | desktop | populated + an honest-unavailable state |
| `v1-45-roster-source.spec.js` | roster-capacity identity evidence | desktop | populated |
| `v1-45-trade-surface.spec.js` | `/trade` (2-team) | desktop | populated (2 of 3 states are code-proven not production-inducible, per that row's `EVIDENCE_METHODOLOGY`) |
| `v1-56-waivers-faab-strip.spec.js` | `/waivers` FAAB strip | desktop | populated (has a known, named gap — no team-selection step, so the FAAB stat tiles never render; see `V1-56`'s row) |
| `v1-62-sharp-tracker.spec.js` | `/market/sharp-tracker` | mobile-gated but desktop-run | populated + `cohort_building`/`no_activity` branches |
| `v1-109-mobile-usability.spec.js` | `/trade` tray, `/rankings` watchlist, `/rankings`+`/rosters`+`/draft` type floor | mobile only | populated |

## 2. Canonical surface inventory

Every route the shell nav actually offers (`frontend/lib/nav-model.js`, 33 top-level paths;
`/league` alone fans out to ~19 more via `?tab=`, validated against `VALID_TABS`). Mapped onto
§13.3's own category list:

| §13.3 category | routes | prod-auth today | verdict |
|---|---|---|---|
| Rankings | `/rankings`, `/trending`, `/idptc-rookies`, `/players/compare`, `/bdvm` | `/rankings` only (populated) | **partial** — 4 of 5 routes uncovered |
| Universal Player Profile | player detail overlay (opened from a rankings row, no dedicated URL) | none | **gap** |
| Trade Calculator / Trade Desk / 3+ team | `/trade` | 2-team, desktop, populated | **partial** — 3+ team and mobile untested; Trade Desk is POST-V1 (no surface exists — see `V1-45`'s boundary ruling) |
| Trade Finder / Suggestions / Package Builder | `/arbitrage` (Finder), `/angle` (Package Builder); Suggestions is embedded in `/trade` | none | **gap** |
| Waivers / FAAB / Perfect Waivers | `/waivers` | populated, but with the named team-selection gap | **partial** — needs the `V1-56` follow-up + a "Perfect Waivers" definition check (no distinct route found; likely a `/waivers` section — confirm before scoping it separately) |
| Draft / Perfect Draft / pick tools | `/draft`, `/draft-capital` (folds into `/league?tab=draft-capital`) | `/draft` type-floor only (mobile) | **gap** — Perfect Draft itself (the auction optimizer) has zero prod-auth coverage despite a rich local spec (`journey-perfect-draft.spec.js`) to port from |
| Team/Roster intelligence | `/rosters`, `/league?tab=ros-team-strength` | `/rosters` lineup + capacity-identity only | **partial** — Team Strength/Weakness tab uncovered |
| Market / Sharp / Insider / Analyst Intelligence | `/edge`, `/consensus-edge`, `/market/sharp-tracker`, `/market/sharp-roster-percentage`, `/league/insider-trading`, `/league-comparison` | Sharp Tracker only; `/consensus-edge` reachability only (no content assertion) | **gap** — Sharp Roster Percentage, Source Disagreement, Insider Trading, League Comparison all uncovered |
| Playoff / Power / Game Day | `/league?tab=ros-championship` (playoff), `/league?tab=ros-power` (power) | none | **gap** — and "Game Day" has **no shipped route or section file** (`frontend/app/league/sections/` has no `game-day.jsx`; matches `docs/WORK_CLAIMS.md`'s `C5-GD-02`, which is mid-construction, no live consumer). Recommend recording Game Day as **N/A — not yet a real surface** rather than a coverage gap, and re-scoping it once it ships. |
| Command Center / Portfolio | `/` (home dashboard / "war-room surface") | none in prod-auth (touched only by local `signed-in-smoke.spec.js`) | **gap** |
| authenticated League navigation | `/league` + its `?tab=` fan-out, signed in | `v1-131` covers the shell's nav *offer* (menus, capability gating), not `/league` tab *content* | **partial** |
| public League surfaces | `/league`, `/league/activity`, `/league/articles`, `/league/franchise`, `/league/rivalry`, `/league/week`, `/league/weekly` (public — no session needed) | none against real production (strong LOCAL coverage: `public-league.spec.js`, `public-league-visual.spec.js`) | **gap for production**, but cheapest to close — no `guest_pass` required, a plain fetch/navigate suffices, same posture as this session's direct `/api/public/league/*` checks |
| Upside Report / Awards / history / sharing | `/league?tab=awards`, `?tab=history`, `?tab=archives`; "sharing" = the `.screenshot-fab` save-as-image control seen on `/trade` and `/more` this session | none against production | **gap** — "Upside Report" has no obvious 1:1 section-file match; confirm what it names before scoping (candidate: `overview.jsx`, or it may be marketing copy for the terminal itself) |

## 3. What "populated/empty/stale/error" means here, honestly

Every closed row this session that hit this question (`V1-45`, `V1-62`) established the same
answer: **production evidence for whatever state production naturally produces; mutation-proof
against the real component for states production cannot legitimately be made to produce.**
Manufacturing a production failure to "cover the error state" is exactly the fabrication this
program forbids. So each surface in the phased plan below gets:

- the state(s) actually reachable on the real board today (named explicitly, not assumed);
- for any state that is not reachable, a citation to an existing (or newly written) mutation
  test against the real production component — the same pattern `V1-45`'s `EVIDENCE_METHODOLOGY`
  note used for its two unreachable branches.

No item in this matrix is done until both halves are accounted for, not just the populated one.

## 4. Proposed phased order

Ordered by (a) how much of the hard part is already solved elsewhere, (b) blast radius if
wrong, (c) whether the surface is confirmed to exist yet.

**Phase 0 — public League surfaces (no auth, cheapest, highest route count per unit effort).**
`/league` + its public `?tab=` fan-out (activity, articles, franchise, rivalry, week, weekly,
awards, history, archives, records, streaks, superlatives, conduct, luck, overview) plus the
already-`VALID_TABS`-validated deep-link behavior. No `guest_pass` needed — a plain navigate is
sufficient, same posture as this session's direct public-API checks. Strong local prior art in
`public-league.spec.js` / `public-league-visual.spec.js` to port from.

**Phase 1 — port existing, well-designed local specs onto prod-auth.** Highest signal-per-line,
because the assertions are already right; only the fixture (real session vs. test-only) changes.
Candidates, in order: Perfect Draft (`journey-perfect-draft.spec.js`), Rankings journeys
(`journey-rankings.spec.js` — search, sort, filters, player popup — extends `v1-111`'s
populated-only coverage), Trade journeys (`journey-trade.spec.js` — extends `v1-45` to
`/arbitrage` and `/trades`), mobile smoke invariants (`mobile-smoke.spec.js` — extends `v1-109`).

**Phase 2 — close the named gaps with no local prior art.** Command Center/home dashboard,
Universal Player Profile (the overlay, not a route), Trade Finder (`/arbitrage` content, not
just navigation), Package Builder (`/angle`), Sharp Roster Percentage
(`/market/sharp-roster-percentage` — mirror `v1-62`'s structure exactly, same cohort/qualification
machinery), Source Disagreement (`/edge` — the `V1-131` spec already proves the link exists and
is reachable; this phase asserts real board content), Insider Trading, League Comparison,
Team Strength/Weakness tab, `/draft-capital`.

**Phase 3 — confirm-before-scoping.** Game Day (record as N/A pending a real route), "Perfect
Waivers" and "Upside Report" (confirm what these terms name in the current product before
writing anything against them — do not guess a route).

**Not in scope for this row:** Trade Desk (explicitly POST-V1 per `V1-45`'s boundary ruling —
building prod-auth coverage for a surface that doesn't exist would be inventing evidence for
nothing).

## 5. Open questions for a human decision before Phase 2/3 work starts

1. Does "Perfect Waivers" name a real, distinct feature, or is it prose describing `/waivers`'
   existing manual add/drop calculator? If the latter, it's already inside Phase 0/1's
   `/waivers` scope and needs no separate line.
2. Same question for "Upside Report" — no section file matches it 1:1.
3. Is Game Day expected to ship before V1-123 needs to close, or should this row's L4 bar be
   read as "cover what exists today" with Game Day tracked as a known, dated gap? (`C5-GD-02`'s
   own claim says its capture store has zero callers yet — this is a real product-readiness
   question, not a testing one.)

## 6. Status

Scoping only. Nothing implemented. Next step, pending direction: start Phase 0 (public League
surfaces) — no credentials needed, fastest path to real production evidence, and it establishes
the pattern (deep-link `?tab=` coverage, populated/empty states already distinguished by the
public contract) that Phases 1-2 will reuse.
