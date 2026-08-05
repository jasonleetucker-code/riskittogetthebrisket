# W01 — NAV vs REALITY, and Unlisted Features Discovered

`frontend/lib/nav-model.js` is the single IA source: `NAV_MODEL` (6 groups,
23 leaves) + `SYSTEM_MODEL` (6 items, 4 admin-only) + `MOBILE_TABS` +
`MOBILE_TABS_PUBLIC` + `PALETTE_EXTRA_TARGETS`. The desktop bar, mobile tab
bar, drawer, command palette and the `/more` site map all derive from it —
`/more` maps `[...NAV_MODEL, SYSTEM_MODEL]` directly, so it cannot list
anything the model omits.

## Nav entries pointing at nothing: **none**

All 31 distinct `href` values resolve to a real page that returns HTTP 200
with a session (`page-auth-probe-3000.txt`). The naming invariant the file
declares also holds: every static page's `PageHeader title=` string is
byte-identical to its nav label (20/20 checked).

## Pages reachable from NO navigation: **three**, plus two deep-link shims

| page | in nav? | in `/more`? | any in-app `<Link>`? | what it is |
|---|---|---|---|---|
| `/finder` | no | no | **no** | Legacy screener, now a client-side redirect into `/rankings?screen=…`. Self-documented as a bookmark shim. |
| `/intel` | no | no | **no** | Retired route, server `redirect()` → `/league/insider-trading`. Self-documented. |
| `/design` | no | no | **no** | **Dev-only design-system gallery**, `robots: {index:false}`. Ships in the production Next build and sits behind the ordinary session gate — any signed-in user who guesses the URL gets it. |
| `/rankings/[position]` | no | no | no | Deep-link shim → `/rankings?pos=X`. Documented; `/rankings` does not link back into it. |
| `/draft-capital` | no | no | no | `next.config.mjs` 308 → `/league?tab=draft-capital`. Named in `pageTitleFor` but in no menu. |

Verified by grepping every `frontend/app/**` and `frontend/components/**`
`.js`/`.jsx` for `/finder`, `/design`, `/intel` outside those pages' own
directories: **zero hits**.

## Unlisted Features Discovered

Everything below is functionality the audit brief did not name. Status
labels are from `AUDIT_PROTOCOL.md`.

### Pages

| surface | status | note |
|---|---|---|
| `/finder` | **Deprecated but still active** | Redirect shim only; no content of its own. Anonymous → 307 `/login`. |
| `/design` | **Scaffolded only** | Design-system gallery. In the prod build, no nav, noindexed, session-gated. Nothing imports `DesignGallery` except this page. |
| `/intel` | **Deprecated but still active** | Redirect shim → `/league/insider-trading`. |
| `/trending` | **Implemented and verified** | *Is* in nav ("Trending", Rankings group). Listed here because the brief did not name it. |
| `/players/compare` | **Implemented and verified** | In nav ("Compare Players"). Its own comment records it was palette-only before #626. |
| `/idptc-rookies` | **Implemented and verified** | In nav ("Rookie Board"). |
| `/league-comparison` | **Implemented and verified** | In nav ("Scoring Comparison"). |
| `/phases` | **Implemented and verified** | In nav ("Win-now vs Rebuild"). `/league/phases` 308s here via `MOVED_ROUTES`. |
| `/trades` | **Implemented and verified** | In nav ("Trade History"). Deliberately **private** — `public-routes.js` documents that it was wrongly declared public while rendering proprietary trade grades. |
| `/more` | **Implemented and verified** | Site map derived from `nav-model.js`. |
| `/admin` | **Implemented and verified** | Nav-visible **admin-only**; `/api/admin/*` returns 403 for `e2e-test-user` (expected). |
| `/tools/source-health` | **Implemented and verified** | Admin-only nav item. |
| `/tools/ros-data-health` | **Implemented and verified** | Admin-only nav item; the only real surface for the 7 `/api/ros/*` routes. |
| `/tools/trade-coverage` | **Implemented and verified** | Admin-only nav item. |

Note on the four Ops entries: `SYSTEM_MODEL` marks them `adminOnly` and
`systemItemsFor({isAdmin})` filters them out of the menu, but the **page**
is only session-gated (`middleware.js` checks cookie *presence* only). A
non-admin who types `/admin` gets a 200 shell whose data calls 403 and
which then renders an explicit "This page requires an admin session"
card — honest degradation, not a leak.

`/admin`'s feature-flag panel is **read-only and honest**: it renders
`gateStatus` beside `enabled` with the tooltip "This flag's gate is not
reachable from the server, so its value cannot change a response", and
tells the operator flags are env-driven. The page docstring's phrase
"for flipping feature flags" overstates it — no `/api/admin/*` route
writes a flag, and `feature_flags.py` caches reads per process — but the
UI itself does not make that claim.

### Backend surfaces with no UI at all

| surface | status | note |
|---|---|---|
| `GET /api/gameplan` | **Implemented but disconnected** | Whole roster-intelligence engine (`src/roster_intel/`), no caller. See W01-F002. |
| `GET /api/public/league/{section}.csv` | **Implemented but disconnected** | Public-league CSV export; no link anywhere in the UI. The four in-app CSV exports (`/rankings`, `/trade`, `/idptc-rookies`, `/draft`) are all client-side blob downloads that never touch it. |
| `GET /api/scaffold/{status,raw,league,identity,validation,report}` | **Scaffolded only** | Six pipeline-introspection routes, no UI, no ops caller. `/api/scaffold/status` is additionally in `_PUBLIC_API_EXACT` — unauthenticated, and its payload contains absolute server filesystem paths. |
| `GET /api/metrics` | **Implemented but disconnected** | Public, unauthenticated ops metrics. No in-repo consumer (no dashboard, no workflow, no timer). |
| `POST /api/test-alert` | **Scaffolded only** | Zero references anywhere in the repo, including tests. |
| `GET /api/sharp/market/audit`, `GET /api/sharp/roster-percentage/audit` | **Implemented but disconnected** | CLAUDE.md describes the roster one as "for manual verification"; neither has a UI entry point. |
| `GET /api/consensus-edge/player/{player_key}`, `/health` | **Implemented but disconnected** | Only `players` + `methodology` are consumed by `/consensus-edge`. |
| `GET /api/intel/member/{owner_id}`, `/api/intel/waiver-interest` | **Implemented but disconnected** | `/league/insider-trading` uses `summary`, `player` and `leads` only. |
| `POST /api/angle/find` | **Implemented but disconnected** | Has a Next bridge; `/angle` calls `packages` only. |
| `POST /api/waiver/suggestions` | **Implemented but disconnected** | CLAUDE.md concedes "no UI caller". |
| `GET /api/rankings/sources` | **Implemented but disconnected** | CLAUDE.md calls it the "Runtime check" for registry lockstep; nothing calls it at runtime. The parity test parses the frontend JS statically. |
| `POST /api/league/articles/generate` | **Implemented but disconnected** | AI article generation, no UI trigger, no workflow, no timer. |

### Flag-gated surfaces

| flag | default | reachable surface | proven |
|---|---|---|---|
| `consensus_edge` | **OFF** | `/consensus-edge` + 5 routes | Yes — `=1` yields a real 325-player board |
| `bdvm_engine` | ON | `/bdvm` + 4 routes + `/rankings` "Fund gap" column + `/draft` panel | Yes — `=0` yields 503 `feature_disabled` |
| `monte_carlo_trade` | ON | Simulate button on `/trade` | Yes |
| `realized_points_api` | ON | `PlayerPopup` | Yes |
| `te_basis_conversion` | ON | every TE and pick value on every board | Yes — 135 rows move |
| `idp_scoring_fit`, `reception_scoring_fit` | ON | league-adjusted lens only | Yes — 293/709 factors move |
| 7 others | OFF | **nothing** | Verified inert — see `flag-differential.md` |
