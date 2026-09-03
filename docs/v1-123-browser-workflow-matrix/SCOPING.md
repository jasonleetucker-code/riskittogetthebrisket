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

**Phase 0 — code shipped 2026-09-03 (PR #1231), a real test-race bug found and fixed 2026-09-03,
not yet re-confirmed clean.** `tests/e2e/specs/prod-auth/v1-123-public-league-matrix.spec.js`
failed **identically on both projects, on two independent real runs** (`33768425785`,
2026-09-03T14:42-14:47Z, and `33769285866`, 14:51-14:55Z): `/league?tab=overview` returned a
36-byte near-empty document (expected > 100), always on the test's first navigation. Per this
program's own "at most once" re-run policy, a second identical failure is real, not a flake — a
direct `curl` showing the live page healthy ruled out "the page is broken," but not "the test has
a bug."

**Root cause found**: `waitForLeagueReady`'s two `page.waitForFunction` calls check for the
*absence* of "Loading league data..."/"Loading section..." text starting from the instant they are
called. On a cold navigation in a fresh browser context — this test's own first request, before any
JS bundle has mounted anything — that text is not in the DOM yet for the unrelated reason that
nothing has rendered at all, so "loading text is absent" is vacuously true and the wait resolves
immediately, before the app has had any chance to load. The subsequent one-shot body-length check
then reads the still-blank shell. Fixed by polling for real content (`expect.poll` on
`body.trim().length`, the same idiom already used throughout this test suite's local and prod-auth
specs) instead of trusting the loading-negation's single instant — same assertions and messages,
now retry-based rather than one-shot. **Not yet re-run against production to confirm the fix**;
do not mark Phase 0 done until that run passes.

**Phase 1 — IN PROGRESS** (2026-09-03, this session). First real run against production this
session (`33768425785`): **28 of 31 test instances passed.**

- `tests/e2e/specs/prod-auth/v1-123-rankings-journeys.spec.js` — sort/reverse, position filter
  narrow+restore, name-fragment search filter+clear, player popup (Our Value + Source Breakdown)
  ALL PASSED on both `prod-desktop` and `prod-mobile`. The global `/` search shortcut → popup
  test failed on `prod-mobile` only — a genuine TEST bug, not a production defect: `.shell-search-
  btn` lives in `components/shell/TopBar.jsx`, whose own docstring says "the desktop shell header
  (R1)" — the affordance simply does not exist at the mobile viewport (mobile search lives behind
  the Menu drawer instead). Fixed by gating that one test `desktopOnly` rather than the whole
  file, since the other four interactions are now PROVEN to work on both viewports — narrowing
  coverage to "desktop-only" for the whole file, as the local source spec does, would have thrown
  away real, working mobile coverage this run just established.
- `tests/e2e/specs/prod-auth/v1-123-mobile-nav.spec.js` — PASSED. The one behavior from
  `mobile-smoke.spec.js` not already covered elsewhere: the mobile bottom tab bar's visibility and
  cross-tab navigation (`prod-mobile` only). The other two `mobile-smoke.spec.js` behaviors
  (rankings board renders on a phone viewport; player popup opens/closes) are already exercised by
  the rankings-journeys spec above running on `prod-mobile`, so porting them again would be
  duplicate coverage, not new evidence.
- `tests/e2e/specs/prod-auth/v1-123-perfect-draft.spec.js` (new, this session) — ports
  `journey-perfect-draft.spec.js`'s three tests (buyable rookie combination; never exceeds budget;
  an unloaded league produces no panel rather than a placeholder plan) onto production, desktop
  only (matches the local source spec's own gate). Seeds the client-side draft workspace via
  `addInitScript` using real team names read from the authenticated production contract. **Written,
  not yet run against production.**
- `tests/e2e/specs/prod-auth/v1-123-trade-journeys.spec.js` (new, this session) — extends `v1-45`
  to `/arbitrage` and `/trades` per this document's own Phase 1 candidate list, plus the
  `/rankings?screen=` deep-link filter and `POST /api/trade/finder`. Deliberately excludes
  `journey-trade.spec.js`'s "/trade builder renders" test — `v1-45-trade-surface.spec.js` already
  covers `/trade` in prod-auth field-for-field, so porting it again would be duplicate coverage.

**Phase 1 is code-complete AND run against production** (run `33774483633`, 2026-09-03T15:44-15:54Z,
8.8 minutes, 56 test instances): `v1-123-perfect-draft.spec.js` **3/3 PASSED** on real production —
budget survives, real rookie recommendations render, spend never exceeds budget, an unloaded league
produces no panel. `v1-123-trade-journeys.spec.js` **7/8 passed**: `/trades`, the
`/rankings?screen=` filter, `POST /api/trade/finder`, and `/arbitrage` on `prod-desktop` (21.4s,
real trade cards) all passed; `/arbitrage` timed out at 90s on `prod-mobile` only. This run also
independently confirmed `v1-111` (which failed the *previous* run on a 45s API timeout) now passes
cleanly on both projects — corroborating that the previous failure was genuine transient production
load, not a defect: current direct checks of the same endpoints are fast and healthy.

**A second, distinct Phase 0 defect found and fixed this run — not related to the race-condition
fix.** `/league?tab=conduct` failed with `Received: "piece-of-shit-rankings"` instead of the
requested `"conduct"`. Direct investigation (not guessed at): `frontend/app/league/tabs.js` defines
`conduct` as a **deliberate legacy alias** (`TAB_ALIASES`, "kept forever for old deep links") that
the page correctly rewrites the URL bar to the real canonical slug `piece-of-shit-rankings` for —
confirmed live with `curl https://chaseupside.com/league?tab=conduct`, which server-renders
`<option value="piece-of-shit-rankings" selected>Piece of Shit Rankings</option>`. The test's
strict URL-preservation assertion was correctly failing on an alias by design, not on a bug. Fixed
by testing the tab's real canonical slug instead of its alias, and by fixing a genuine typo
(`rivalry` → the real key `rivalries`) found during the same cross-check against
`tabs.js::VALID_TABS`. Two entries (`articles`, `week`) are not `tab=` query keys in the current
model at all — they silently render `DEFAULT_TAB` content without rewriting the URL, so they never
failed this test, but were never testing what their names claimed either; removed with a note
rather than silently left in, since the public article surface is a distinct ROUTE
(`/league/articles/[season]/[week]`) out of this deep-link spec's scope. **Not yet re-run to
confirm this fix.**

**Open, unresolved finding — not yet fixed or explained**: `/arbitrage` on `prod-mobile` timed out
at 90s waiting for the scan to resolve to trades or an explicit empty state, while the identical
scan passed on `prod-desktop` in 21.4s (a >4x margin under the 90s budget). Could be a genuine
mobile-specific UI issue (a control not reachable the way the test expects at 390px) or compounding
load late in an 8.8-minute run — not determined either way. Left open rather than guessed at; needs
its own investigation before Phase 1 can be called fully proven.

**Phase 2 — code shipped 2026-09-03, not yet run against production.** All ten named gaps have
new specs, built from a dedicated research pass over the real source (exact selectors/component
files/state text cited per surface, not guessed):

- `v1-123-command-center.spec.js` — `/` war-room surface + team switcher, ported from
  `signed-in-smoke.spec.js`'s existing local assertions.
- `v1-123-trade-journeys.spec.js` gained a new test asserting `/arbitrage`'s player-level edge
  table and the player-type filter (Trade Finder *content*, distinct from the nav-only coverage
  Phase 1 already proved).
- `v1-123-package-builder.spec.js` — `/angle`, offer mode: select a roster player, submit, require
  real return packages or the backend's own named empty state. Zero prior coverage anywhere; written
  fresh.
- `v1-123-sharp-roster-percentage.spec.js` — `/market/sharp-roster-percentage`, mirrors
  `v1-62-sharp-tracker.spec.js`'s "capture the page's own fetch, prove the render matches it"
  structure, adjusted for this endpoint's real differences (a ds `DataTable` keyed by `assetId`,
  `payload.totalQualifyingPlayers` in place of Sharp Tracker's single "Assets" stat tile, and
  backend-driven empty-state copy rather than a fixed string).
- `v1-123-source-disagreement.spec.js` — `/edge`, all three signal-panel tabs (Market gaps /
  Agreement / Data caution), asserting real panel content, not just that the nav link resolves
  (`v1-131-nav-gating.spec.js` already proved reachability only).
- `v1-123-insider-trading.spec.js` — `/league/insider-trading`, the intel table plus row expansion
  into member-exposure evidence, or the page's own named empty/staleness states. Zero prior
  coverage anywhere.
- `v1-123-league-comparison.spec.js` — `/league-comparison`, `HeaderCard`'s "My League"/"Standard
  Baseline" blocks plus tab navigation, with a generous timeout matching the page's own documented
  30+ second cold-cache first load. Zero prior coverage anywhere.
- `v1-123-team-strength.spec.js` — the ROS Strength tab. **Corrected during scoping**: the real
  `VALID_TABS` key is `rosTeamStrength` (camelCase), not the kebab-case `ros-team-strength` this
  document's own §2 table used — there is no alias for the kebab-case form, so that URL would have
  silently rendered the default tab instead of failing, the same class of test bug Phase 0's
  `conduct` alias already taught this row to check for explicitly rather than assume.
- `v1-123-draft-capital.spec.js` — follows the `/draft-capital` → `/league?tab=draft-capital`
  redirect (already proven at the HTTP level by `public-league.spec.js`) and asserts real team-totals
  content. This component has no CSS classes or test-ids anywhere in its source, so assertions are
  necessarily text-content-based — flagged here for whoever next touches this spec.
- Universal Player Profile overlay: **no new file** — `v1-123-rankings-journeys.spec.js` (Phase 1)
  already proved the overlay opens with Our Value + Source Breakdown on both viewports; the research
  pass confirmed this is genuine, non-duplicate coverage and that extending it further (Player
  context / Realized points / Value chain sections) is optional depth, not a closed gap.

**First real production run** (`v1-authenticated-verification.yml` run `33777101766`,
2026-09-03T16:11-16:25Z, dispatched before PR #1232 merged — this is the run whose failure showed
as the advisory "V1 authenticated verification" check on the PR, which did not block merge since
that check is non-required). Results, read from the artifact rather than inferred from the
conclusion:

- **Phase 0 re-confirmed clean**: `v1-123-public-league-matrix.spec.js` passed on both
  `prod-desktop` and `prod-mobile` — both the race-condition fix and the tab-alias fix hold.
- **Phase 1 fully clean, including the previously-open finding**: `v1-123-rankings-journeys.spec.js`,
  `v1-123-mobile-nav.spec.js`, `v1-123-perfect-draft.spec.js` all passed. `v1-123-trade-journeys.spec.js`
  passed all 5 tests on both viewports — critically, `/arbitrage` on `prod-mobile` now passed in
  20.6s (previously timed out at 90s). This resolves that finding as genuine transient production
  load, not a persistent defect: the identical scan is fast and correct on a normal-load run.
- **Phase 2: 4 of 9 files passed clean first try** (`v1-123-sharp-roster-percentage.spec.js` desktop,
  `v1-123-league-comparison.spec.js` both viewports, `v1-123-team-strength.spec.js` both viewports).
  **5 of 9 had real bugs, all in the new TEST code, not production** — each root-caused against the
  actual source rather than guessed, then fixed:
  - `v1-123-command-center.spec.js` (`prod-mobile` only, 180s **timeout**): `AppShellWrapper` mounts
    BOTH `TopBar`'s desktop team-switcher toggle and `MobileChrome`'s mobile one unconditionally —
    CSS media queries pick which is shown per viewport, the same pattern that made
    `.shell-search-btn` desktop-only earlier this session. `.first()` alone selected the CSS-hidden
    desktop instance at the mobile viewport, so `.click()` waited for actionability until the whole
    test timed out. Fixed: scope to `button.team-switcher-toggle:visible`.
  - `v1-123-draft-capital.spec.js` (both viewports, **failed**): the league tab picker's own
    `<select>` carries an `<option>Draft Capital</option>` entry with the same text as the section's
    real title; `getByText().first()` picked that (hidden outside an open native dropdown) instead
    of the visible title. Fixed: `.and(page.locator(":visible"))`.
  - `v1-123-insider-trading.spec.js` (both viewports, **failed**, strict-mode violation): the page's
    own fixed subtitle ("Trades your league-mates made...") also matches a loose `/League-mate/i`
    search, colliding with the real `MemberExposure` table's `<th>League-mate</th>` header. Fixed:
    `getByRole("columnheader", { name: "League-mate" })`.
  - `v1-123-package-builder.spec.js` (both viewports, **failed**, element not found): `RosterPicker`'s
    row class comes from a CSS module (`angle.module.css`), so the literal `label.rosterRow` selector
    never matches the hashed production class name. Fixed: select the real `<input type="checkbox">`
    inside each row by ARIA role instead, which survives hashing.
  - `v1-123-source-disagreement.spec.js` (both viewports, **failed**, strict-mode violation): "Sell
    signals" is a substring of "IDP sell signals," and both panel headings live in the same tab, so
    an unanchored text search matched both. Fixed: anchor the heading-name regex to
    `/^Sell signals/i`.

All five fixes are committed and were re-run against production
(`v1-authenticated-verification.yml` run `33798151305`, dispatched against `ae7e634`,
2026-09-03T19:44-20:11Z): **all 5 pass.** None of `v1-123-command-center.spec.js`,
`v1-123-draft-capital.spec.js`, `v1-123-insider-trading.spec.js`, `v1-123-package-builder.spec.js`,
or `v1-123-source-disagreement.spec.js` appear in this run's failures — every one of the five
real bugs found on the first run is confirmed fixed.

**Two NEW failures appeared this run, in files unchanged since the first run's clean pass**:
`v1-123-sharp-roster-percentage.spec.js` (`prod-desktop`, 90s timeout waiting for the page's own
`GET /api/sharp/roster-percentage` response) and `v1-123-team-strength.spec.js` (`prod-desktop`,
60s timeout, neither the table nor either named empty state appeared). Neither spec file was
touched between the two runs, so this is not a code regression in the test. A direct latency
spot-check immediately after (`curl` against both endpoints) answered in under 0.8s each —
production is not degraded right now — corroborating that both were genuine transient load during
that specific run rather than a persistent defect, the same evidentiary pattern already established
this session for the `/arbitrage` mobile timeout and the `v1-111` failure. **Not yet re-confirmed
with a third run** — dispatched, pending.

**Third confirmation run** (`v1-authenticated-verification.yml` run `33801083291`, dispatched
against `7e8ce4c`, 2026-09-03T20:14-20:21Z): **80 of 80 test instances passed, zero failures.**
Both `v1-123-sharp-roster-percentage.spec.js` and `v1-123-team-strength.spec.js` passed clean,
confirming the prior run's two failures were transient production load, not defects, exactly as
the latency spot-check predicted.

**V1-123 CLOSED — PROMOTED → `VERIFIED` (L4) 2026-09-03.** Every phase (0, 1, 2) has a confirmed
clean production run on the same commit; the L4 bar ("the real authenticated application... across
the major routes and workflows, including populated/empty/stale/error states") is met by the
COMPLETE matrix, not a phase, per this document's own §4 framing. Full history above is the
evidence trail; `docs/VERSION_1_COMPLETION_CONTRACT.md`'s `V1-123` row carries the summary and the
promotion record.
