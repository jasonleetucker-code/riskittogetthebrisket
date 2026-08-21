# C10-CLOSE-03 — Browser / workflow matrix (V1-123)

**Status: CHECKLIST/INSTRUMENT ONLY.** No row in this document has been executed against
production. This session had no deployed-production access. Building the instrument is this
document's whole job; filling in `Result` / `Evidence` / `Date` on each row is Claude 5's (or
whoever has deployed production access).

**Target level: L4** — "L3 plus proof the intended user-facing surface consumes the canonical
implementation with truthful semantics," per `docs/VERSION_1_COMPLETION_CONTRACT.md` §2. A row is
NOT verified until it is run against the deployed SHA, by a real authenticated session, with the
result recorded here.

## Canonical definition (§13.3, `docs/C_SERIES_REPLAN_AND_COMPLETION_CONTRACT.md`)

> Exercise the real authenticated application on desktop and true mobile widths across the major
> routes and workflows, including populated/empty/stale/error states.

## How to execute a row

1. Deployed-SHA preamble: record the exact production commit SHA and the wall-clock time of the
   check (same convention as `docs/lane4/L2_L3_VERIFICATION_PROCEDURES.md:82-117`).
2. Sign in as a real authenticated session (not a synthetic test session).
3. Navigate to the route at the stated viewport. For a dynamic `[param]` route, use the recipe
   in the table below — do not guess an id.
4. Record: does the page render populated data, or an EXPLICIT named empty/error state (never a
   blank region, never a permanent spinner)? This repo's own E2E suite already states the bar —
   `tests/e2e/specs/journey-trade.spec.js:60,146,204`, `public-league.spec.js:98,608` — and
   `docs/route-usability-audit.md` already distinguishes **"PASS (honest empty)"** from **"DEFECT
   — empty-state lie"** (a state that looks empty but real data exists that should be showing).
   Reuse that vocabulary verbatim; do not invent a third category.
5. A state that cannot naturally occur on production today (e.g. a specific error condition) is
   recorded `NOT-EXERCISABLE`, not skipped silently and not marked passed. No state-injection/
   route-stubbing harness exists in this repo's E2E suite (verified: zero `page.route()` calls) —
   every empty/error-state assertion that exists today is opportunistic, not forced.

## Viewports

| Project | Engine | Size | In CI today? |
|---|---|---|---|
| `desktop-1366` | Chromium | 1366×768 | Yes (`.github/workflows/e2e.yml:372-376`) |
| `mobile-chromium` | Chromium, touch | 390×844 | Yes |
| `mobile-390` | WebKit (iPhone 13) | 390×844 | **No — local-only, never CI** |
| `mobile-430` | WebKit (iPhone 14 Pro Max) | 430×932 | **No — local-only, never CI** |

**Decision needed from whoever executes this matrix**: run the two WebKit projects manually as
part of this closure pass, or explicitly declare WebKit/Safari and tablet-width (768/1024)
coverage out of V1 scope. Do not leave it implicit — the current state is that CI has zero WebKit
coverage and that fact does not appear anywhere else in the V1 completion record.

## Dynamic-route parameter recipes

Ported from `docs/route-usability-audit.md:68-77` (2026-07-27; re-verify these ids are still live
before use) plus the routes that shipped since that audit was written.

| Route | Parameter | Source |
|---|---|---|
| `/league/player/[playerId]` | `10229` (Rashee Rice) | `/api/public/league/players` |
| `/league/franchise/[owner]` | `1012114412049731584` (Joey) | `sections.franchise.index[0].ownerId` |
| `/league/rivalry/[pair]` | `1012114412049731584-vs-711452264774041600` | `sections.rivalries.pairs[0].ownerIds` |
| `/league/week/[season]/[week]` | `2025/17` | `weeklyRecap.byKey` |
| `/league/weekly/[season]/[week]/[matchup]` | `2025/17/1` | `sections.weekly.weeks[0].matchups[].matchupId` |
| `/league/articles/[season]/[week]` | `2025/17` | `/api/league/articles?season=2025&week=17` |
| `/league/articles/[…]/[matchupId]/[mode]` | `2025/17/1/preview` | same, `mode: "preview"` |
| `/rankings/[position]` | `qb`, `idp`, `picks` | `POSITION_ALIASES` in the route file |
| `/players/[playerId]` | (any current top-ranked player's Sleeper id from `/api/data`) | live board |
| `/market/sharp-people/[personId]` | (any id from `/api/sharp/people`) | live sharp cohort |

## §13.3 category → real route mapping

Every category §13.3 names, matched against what actually exists in this tree today. A category
with no real route is recorded as such **in this matrix**, not silently omitted — a matrix that
only lists what exists would read as "everything named is covered."

### Categories with a real, shippable route today

| §13.3 category | Route(s) | Result | Evidence | Date |
|---|---|---|---|---|
| Rankings | `/rankings`, `/rankings/[position]`, `/trending`, `/idptc-rookies`, `/players/compare`, `/bdvm` | | | |
| Universal Player Profile | `/players/[playerId]` — **zero E2E coverage today, verify carefully** | | | |
| Trade Calculator (incl. 3+ team) | `/trade` | | | |
| Trade Finder / Suggestions | `/arbitrage` | | | |
| Waivers / FAAB | `/waivers` | | | |
| Draft (incl. Perfect Draft panel) | `/draft` | | | |
| Team / Roster intelligence | `/rosters`, `/phases` | | | |
| Market / Sharp | `/edge`, `/consensus-edge`, `/market/sharp-tracker`, `/market/sharp-roster-percentage`, `/market/sharp-people`, `/market/sharp-people/[personId]` | | | |
| Insider | `/league/insider-trading` (private, despite the `/league` prefix) | | | |
| Authenticated League navigation | `/league`, `/league/activity`, `/league-comparison`, plus shell nav (`NavMenu`, `TopBar`, `MobileChrome`, `CommandPalette`, `/more`) | | | |
| Public League surfaces | `/`, `/login`, `/league`, `/league/activity`, `/league/franchise/[owner]`, `/league/player/[playerId]`, `/league/rivalry/[pair]`, `/league/week/[season]/[week]`, `/league/weekly/[…]/[matchup]`, `/league/articles/[…]` (both forms) | | | |
| History | `/trades`, `/league?tab=history`, `/league/week/*` | | | |
| Sharing | Share-URL round-trip (`frontend/lib/trade-share.js`), 4 `opengraph-image` routes under `/league/**` | | | |
| Awards (v1 only) | `/league?tab=awards` | | | |
| Playoff / Power (as League tabs, not standalone routes) | `/league?tab=power`, `?tab=rosPower`, `?tab=rosChampionship`, `?tab=luck` | | | |
| Package Builder (route exists; feature itself is do-not-opportunistically-begin — verify the shipped page only, not an expanded scope) | `/angle` | | | |

### Categories that are NOT-YET-BUILT — must never be marked passed

Confirmed against `docs/EXECUTION_PLAN.md` §6 (lines 1163-1166, "do not opportunistically begin")
and `docs/VERSION_1_COMPLETION_CONTRACT.md:512,528`. A future session finding one of these has
since shipped should update the row and cite the shipping PR — but absent that, these are NOT
part of the matrix's covered surface and a verifier must not report them as passed by omission.

| §13.3 category | Status | Evidence |
|---|---|---|
| Trade Desk | Does not exist — zero hits anywhere in `frontend/` | `docs/VERSION_1_COMPLETION_CONTRACT.md:512` (L2-excluded, `C7-BEST-TRADE`/`#841`/`CE-05`) |
| Perfect Waivers | Does not exist as a shipped surface — zero hits in `frontend/` | Backend forward-reference only: `src/roster_intel/droppability.py:8`; scheduled `C7-WAIV-01` |
| Analyst Intelligence | Does not exist as a product surface | Only incidental "analyst" strings in `frontend/` |
| Game Day | Does not exist — zero hits in `frontend/` | |
| Command Center | Does not exist under that name — zero hits | Closest real surface: the authed `/` terminal (`TerminalLayout.jsx`) |
| Upside Report | Does not exist — zero hits. Do not confuse with the "Chase Upside" brand name used throughout the product | |
| Awards v2 | Only the v1 League tab exists | |
| Universal Player Profile **expansion** | The shipped route (`/players/[playerId]`) is in scope; an EXPANDED one is not | `docs/EXECUTION_PLAN.md` §6 names "Universal Player Profile expansion" specifically |
| Portfolio (a panel, not a route) | Partial — `PortfolioSummary.jsx` renders inside the authed `/` terminal, `/rosters`, `/draft` | Not independently verifiable as a "route" |

## Known live findings to carry into this matrix as verification rows

| Row | Status as of this document | Action for the executor |
|---|---|---|
| `/draft-capital` | **CORRECTED during this session's research — NOT a 404.** An earlier draft of this document (based on a research pass that checked only for an `app/draft-capital/` page directory) flagged this as "almost certainly 404s in production." That was wrong: `frontend/next.config.mjs:33-34` declares a real 308 redirect, `/draft-capital` → `/league?tab=draft-capital`, and `frontend/__tests__/nav-model.test.js` + `public-routes.test.js` pin it as deliberately public. Same "no page directory ≠ dead" trap this session's V1-125 pass independently caught twice in `dead-code-map.csv` (D-112, D-120) | Verify the redirect actually fires on production (a GET to `/draft-capital` should 308 to `/league?tab=draft-capital`, not 404) — low risk, but confirm rather than assume |
| `/league/activity` Trades filter | `docs/route-usability-audit.md:358` (finding F-2, 2026-07-27) recorded an empty-state LIE: the Trades filter can never populate because `useApp()`'s `rawData` is `null` under `/league/*`, while 109 real trades existed in the contract. Status on the CURRENT tree is unknown — not re-verified this session | Re-check this specific row: does `/league/activity?filter=trades` (or the UI equivalent) show real trades, or the same lie? If still broken, this is a genuine DEFECT-class finding, not a checklist gap |

## Result summary (fill in after execution)

| Metric | Count |
|---|---|
| Rows executed | 0 of ~30 |
| PASS (populated or honest empty) | — |
| DEFECT (empty-state lie, error, crash) | — |
| NOT-EXERCISABLE | — |
| Not yet run | all |
