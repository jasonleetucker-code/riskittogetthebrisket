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
| Waivers / FAAB / Perfect Waivers | `/waivers` | populated, but with the named team-selection gap | **`/waivers`: partial** — needs the `V1-56` follow-up. **Perfect Waivers itself: N/A — POST-V1**, per §4.2/§4.3 (`C7-WAIV-01`, "inv 3.3 Perfect Waivers" — a real but unbuilt future optimizer, no route exists to test). |
| Draft / Perfect Draft / pick tools | `/draft`, `/draft-capital` (folds into `/league?tab=draft-capital`) | `/draft` type-floor only (mobile) | **gap** — Perfect Draft itself (the auction optimizer) has zero prod-auth coverage despite a rich local spec (`journey-perfect-draft.spec.js`) to port from |
| Team/Roster intelligence | `/rosters`, `/league?tab=ros-team-strength` | `/rosters` lineup + capacity-identity only | **partial** — Team Strength/Weakness tab uncovered |
| Market / Sharp / Insider / Analyst Intelligence | `/edge`, `/consensus-edge`, `/market/sharp-tracker`, `/market/sharp-roster-percentage`, `/league/insider-trading`, `/league-comparison` | Sharp Tracker only; `/consensus-edge` reachability only (no content assertion) | **gap** — Sharp Roster Percentage, Source Disagreement, Insider Trading, League Comparison all uncovered |
| Playoff / Power / Game Day | `/league?tab=ros-championship` (playoff), `/league?tab=ros-power` (power) | none | **playoff/power: gap.** Game Day: **N/A — POST-V1**, per `docs/VERSION_1_COMPLETION_CONTRACT.md` §4.1 (`C5-GD-01`/`CE-20`/`C5-GD-02`, owner-named-out 2026-08-18). Confirmed independently: no shipped route or section file exists (`frontend/app/league/sections/` has no `game-day.jsx`). Not a coverage gap to close — out of this row's denominator by scope, not by omission. |
| Command Center / Portfolio | `/` (home dashboard / "war-room surface") | none in prod-auth (touched only by local `signed-in-smoke.spec.js`) | **gap** |
| authenticated League navigation | `/league` + its `?tab=` fan-out, signed in | `v1-131` covers the shell's nav *offer* (menus, capability gating), not `/league` tab *content* | **partial** |
| public League surfaces | `/league`, `/league/activity`, `/league/articles`, `/league/franchise`, `/league/rivalry`, `/league/week`, `/league/weekly` (public — no session needed) | none against real production (strong LOCAL coverage: `public-league.spec.js`, `public-league-visual.spec.js`) | **gap for production**, but cheapest to close — no `guest_pass` required, a plain fetch/navigate suffices, same posture as this session's direct `/api/public/league/*` checks |
| Upside Report / Awards / history / sharing | `/league?tab=awards`, `?tab=history`, `?tab=archives`; "sharing" = the `.screenshot-fab` save-as-image control seen on `/trade` and `/more` this session | none against production | **Awards/history/archives/sharing: gap.** "Upside Report" itself: **N/A — POST-V1**, per §4.1's "Wrapped / reporting" group (`C9-UR-01/02`, owner-named-out 2026-08-18). No section file names it because it hasn't shipped, not because it's unidentified. |

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

**Not in scope for this row — confirmed against `docs/VERSION_1_COMPLETION_CONTRACT.md` §4
"POST-V1 DEFERRED", not merely absent from the shipped route table:**

| item | canonical id | §4 citation |
|---|---|---|
| Trade Desk | `C7-BEST-TRADE` / `#841` / `CE-05` | §4.2, L2 lane-continuation (also `V1-45`'s own boundary ruling) |
| Game Day | `C5-GD-01` / `CE-20` / `C5-GD-02` | §4.1, named-out 2026-08-18 |
| Perfect Waivers | `C7-WAIV-01` | §4.2 (L2) and §4.3 ("inv 3.3 Perfect Waivers") |
| Upside Report | `C9-UR-01/02` | §4.1, "Wrapped / reporting" group |

All four are real, owner-approved future scope — "deferral is a scheduling statement, never a
withdrawal" (§4's own framing) — but none of them exist as a testable production surface today,
and none of them are required for V1-123's L4 bar. Building prod-auth coverage for a surface
that doesn't exist would be inventing evidence for nothing, the same reasoning `V1-45` already
established for Trade Desk. This resolves what an earlier draft of this document raised as three
open questions (§5, now removed) — the answer was already in the canonical scope record and
did not need a human decision.

## 5. Status

**Phase 0 — DONE** (2026-09-03, `chatgpt/v1-123-phase0-public-league-20260903`, PR #1231):
`tests/e2e/specs/prod-auth/v1-123-public-league-matrix.spec.js` — all 15 public `/league?tab=`
routes render on the deployed site without touching private endpoints.

**Phase 1 — IN PROGRESS** (2026-09-03, this session). Two of four candidates ported so far:

- `tests/e2e/specs/prod-auth/v1-123-rankings-journeys.spec.js` — sort/reverse, position filter
  narrow+restore, name-fragment search filter+clear, player popup (Our Value + Source Breakdown),
  global `/` search shortcut → popup. Runs on both `prod-desktop` and `prod-mobile` projects
  (ported from `journey-rankings.spec.js`, which is desktop-only locally — this is broader
  coverage than the source it ports, not narrower).
- `tests/e2e/specs/prod-auth/v1-123-mobile-nav.spec.js` — the one behavior from
  `mobile-smoke.spec.js` not already covered elsewhere: the mobile bottom tab bar's visibility and
  cross-tab navigation (`prod-mobile` only). The other two `mobile-smoke.spec.js` behaviors
  (rankings board renders on a phone viewport; player popup opens/closes) are already exercised by
  the rankings-journeys spec above running on `prod-mobile`, so porting them again would be
  duplicate coverage, not new evidence.

Still open from Phase 1: **Perfect Draft** (`journey-perfect-draft.spec.js` → prod-auth) and
**Trade journeys** (`journey-trade.spec.js` → prod-auth, extending `v1-45` to `/arbitrage` and
`/trades`).

**Phase 2 — NOT STARTED.** All ten named gaps remain: Command Center/home dashboard, Universal
Player Profile overlay, Trade Finder content, Package Builder (`/angle`), Sharp Roster Percentage,
Source Disagreement (`/edge` content), Insider Trading, League Comparison, Team Strength/Weakness
tab, `/draft-capital`.

**V1-123 as a whole stays below its L4 bar** ("the real authenticated application... across the
major routes and workflows, including populated/empty/stale/error states") until Phase 2 closes —
this document's own §4 framing is explicit that the row needs the COMPLETE matrix, not a phase.
Each new spec also needs an actual run against production (not merely committed) before it counts
as L4 evidence at all; that run is tracked separately in
`docs/VERSION_1_COMPLETION_CONTRACT.md`'s `V1-123` row, not here.
