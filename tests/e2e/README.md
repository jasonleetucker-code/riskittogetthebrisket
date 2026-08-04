# E2E regression suite

Playwright suite that boots the real stack (FastAPI backend :8000 +
Next.js frontend :3000) and drives a browser through the critical user
journeys.  It is the **functional-parity safety net for the UI
redesign**: every phase of the rewrite must leave this suite green.

No external network and no credentials are required — the backend
serves data seeded from the committed snapshot (`exports/latest/`,
kept fresh by `scheduled-refresh.yml`), and authentication uses the
test-only session endpoint.

## Running it — the one command

From a clean checkout, in any container, with no stack running and no
environment set up:

```bash
npm ci && npm --prefix frontend ci && npm run e2e
```

That is the whole recipe.  It works offline, needs no credentials, and
if anything is missing it tells you exactly what to fix.  `npm run e2e`:

1. **Preflight** — compile checks, contract validation, and it
   **guarantees a usable snapshot** in `data/`, seeding from the
   committed `exports/latest/` when the newest snapshot is missing,
   empty, or truncated (a failed scrape leaves one behind, and
   `load_from_disk` always takes the newest by name).
2. **Boots the stack itself** — backend on :8000 with every var it
   needs, frontend built and served on :3000.  Already-running servers
   on those ports are reused.
3. **Verifies the stack can actually serve the suite** before any spec
   runs — snapshot loaded, test sessions unlocked, an *authenticated*
   `/api/data` populated, frontend responding — and fails with a
   fix-it message rather than a wall of timeouts.
4. Runs `desktop-1366` + `mobile-chromium` with `--ignore-snapshots`
   (no pixel baselines are committed; visual specs still run their
   structural assertions).

```bash
npm run e2e:report                # open the HTML report afterwards
```

### Why `npm ci` and not `npm install`

Both lockfiles are committed.  `npm ci` installs exactly what they
pin and **never rewrites them**, so it is safe under coordination
rules that forbid lockfile edits — no agent needs a lockfile change to
get a runnable suite.  Preflight fails with this exact command when
either `node_modules` is missing.

### Don't trust these signals — they're misleading here

Two agents in a row concluded the stack was broken from symptoms that
are all **expected**:

| Signal | What it actually means |
|---|---|
| `GET /api/health` → **503** | Normal offline.  The startup scrape can't reach ranking sites, so the backend is permanently "degraded".  Not a data problem. |
| `GET /api/data` → **401** | Correct — that endpoint is auth-gated.  Use a session (the suite does). |
| `last_success_at: null` | Expected.  The suite runs on the **committed snapshot**, never a live scrape. |
| backend exits instantly | `server.py` raises at import without `JASON_LOGIN_PASSWORD`.  `npm run e2e` sets `ALLOW_DEFAULT_LOGIN_DEV=1` for you; if you boot the backend by hand, you must too. |
| `FileNotFoundError: No dynasty_data_YYYY-MM-DD.json files found` from `validate_api_contract.py` | **This one is NOT expected — it is a real failure, and it used to be the recipe's own bug.** Preflight validated the contract *before* seeding the snapshot the validation reads; `data/` is gitignored, so on a clean checkout it aborted here and no spec ever ran.  Fixed 2026-07 by seeding first.  If you still see it: you are on a pre-fix checkout, or you ran `scripts/validate_api_contract.py` directly instead of through `npm run e2e`.  Do **not** file it under "no data" — the row below is about a *running* backend, this is preflight refusing to start.  If `exports/latest/` is genuinely missing too, preflight now says so in plain English instead of raising. |

The check that actually matters is `/api/status` → `has_data: true`,
and global setup asserts it (plus an authenticated `/api/data`) before
the first spec.  A green run without those would mean signed-in specs
skipped silently.

### Pre-installed Chromium (sandboxed containers)

If `PLAYWRIGHT_BROWSERS_PATH` holds a Chromium whose revision doesn't
match this `@playwright/test` (common in agent containers, where
`playwright install` isn't possible), the config **auto-detects and
uses it** — no flag needed.  `E2E_CHROMIUM_PATH` still overrides
explicitly.

The Playwright config boots both servers itself (`webServer`) and
re-uses them when they already answer, so you can also keep your own
stack running:

```bash
# terminal 1 — backend (env vars as above)
UPTIME_CHECK_ENABLED=false python server.py
# terminal 2 — frontend (production build; `next dev` first-compiles
# are slower than server.py's 5s page-proxy timeout and will 503)
cd frontend && npm run build:nocheck && npm run start
# terminal 3
E2E_BASE_URL=http://127.0.0.1:8000 npm run e2e
```

`npm run regression` is the older full-matrix entry point (adds the
webkit `mobile-390` / `mobile-430` projects, which need
`npx playwright install webkit`, and enforces pixel snapshots).

### Env vars the suite understands

| Var | Effect |
|---|---|
| `E2E_BASE_URL` | Target an already-running stack; skips the `webServer` boot |
| `E2E_PAGE_ORIGIN` | Origin for **page** navigations (APIs keep `E2E_BASE_URL`).  Defaults to `http://127.0.0.1:3000` in webServer mode, empty when `E2E_BASE_URL` is set.  Production routes pages straight to Next via nginx; this reproduces that topology.  Required for correctness, not just speed: through the backend's page proxy, `/` renders the **anonymous** shell even for a signed-in session (`/api/auth/status` says `authenticated:true` while the proxied page shows "Sign In"), the proxy's 5s timeout is exceeded by slow SSR passes like `/league`, and it doesn't register every Next page (`/waivers`, `/news`) |
| `RATE_LIMIT_BYPASS_IPS=127.0.0.1` | **Server-side, needed for repeated full runs.**  Exempts the runner from the public-API rate limiter (60/min + 1000/hour per IP — `src/api/rate_limit.py`).  A full run fires thousands of public calls (`/api/auth/status` per page load, `/api/public/league/*`); when the hour bucket drains, the 429s surface as bogus auth/render failures (create-session 429 → signed-in specs skip; `/api/auth/status` 429 → pages render the logged-out shell) |
| `E2E_TEST_MODE=1` + `E2E_TEST_SECRET` | Enable the test-session endpoint on the server; the same secret on the runner side unlocks the signed-in specs (they **skip cleanly** when unset).  Set automatically when the config boots the backend — you only need these when driving your own stack |
| `ALLOW_DEFAULT_LOGIN_DEV=1` | **Server-side, mandatory.**  `server.py` raises at import without `JASON_LOGIN_PASSWORD`; the resulting boot failure looks like a data problem downstream.  Set automatically for the backend the config boots |
| `E2E_FRONTEND_CMD` | Override the frontend `webServer` command (default: production build + start) |
| `E2E_CHROMIUM_PATH` | Launch a pre-installed Chromium binary instead of the revision-pinned download (sandboxes / air-gapped runners) |
| `SKIP_VISUAL_REGRESSION=1` | Skip the two visual-regression specs entirely |

## Spec inventory

| Spec | Layer | What it protects |
|---|---|---|
| `journey-rankings.spec.js` | signed-in UI | Board renders real rows; column sort; position filter; board search; player popup with source breakdown; global search (`/`) |
| `journey-trade.spec.js` | signed-in UI + API | `/trade` builder renders + controls; `/trades` history; `/rankings?screen=` deep-link actually narrows the board; `/arbitrage` scans to trades or an explicit empty state; `POST /api/trade/finder` returns trades for a real roster |
| `journey-settings-overrides.spec.js` | signed-in UI | Settings lists every registered source; toggling one fires `POST /api/rankings/overrides` and the board re-renders with the custom-mix badge |
| `journey-news.spec.js` | signed-in UI | `/news` tab — skips with a clear message while the route 404s (pre-PR #533) and self-activates once it ships |
| `mobile-smoke.spec.js` | signed-in UI @390x844 | Board usable, popup opens/closes, bottom nav navigates |
| `critical-smoke.spec.js` | public | Every route renders without JS errors; API auth gates |
| `public-league.spec.js` | public | The whole public `/league` hub: tabs, deep links, franchise/rivalry/player routes, privacy isolation |
| `signed-in-smoke.spec.js` | signed-in | Authed pages + API round-trips |
| `waivers-smoke.spec.js` | signed-in UI | `/waivers` renders + filters operate |
| `multi-league.spec.js` | API | League registry + `?leagueKey=` contract |
| `api-trade-intelligence.spec.js` | signed-in API | `/api/draft-capital` pick-board completeness + round-over-round value monotonicity; `/api/trade/suggestions` top-150 board gate and "you can only trade players you own" |
| `journey-tools-health.spec.js` | signed-in UI | `/tools/source-health` names match `/api/status`'s enabled sources; `/tools/trade-coverage` renders one audited row per Sleeper team |
| `chart-visual-regression.spec.js`, `public-league-visual.spec.js` | visual | Pixel baselines (not committed — run with `--update-snapshots` locally to generate; skipped by `--ignore-snapshots` / `SKIP_VISUAL_REGRESSION=1`) |

Retired (2026-07): `smoke-api.spec.js`, `rankings-more.spec.js`,
`trade-calculator.spec.js` and `utils/app.js` targeted the removed
static frontend (`window.loadedData`, `switchTab`) and could no longer
pass; the journey specs above are their Next.js-era replacements.

## Conventions (keep these through the redesign)

1. **Data-driven waits.**  Wait for actual rows/content
   (`expect(...).toBeVisible()`, `expect.poll(...)`,
   `waitForFunction` on real DOM state) — never bare
   `waitForTimeout` sleeps.
2. **No hardcoded player names.**  Sample names from the live board
   and assert on counts/structure; data changes nightly.
3. **Behavior over markup.**  Assert what the user can do (sorting
   reorders, filtering narrows, popup explains the value), not what
   the DOM looks like.
4. **Selectors are centralized** in `helpers/journey.js` (`SEL`).
   When a redesign phase changes a page's DOM, update the selector
   registry — the journey assertions themselves should not need to
   change.  If an assertion has to change, the redesign changed
   behavior, which is exactly what this suite exists to surface.
5. **Skip cleanly on absent INFRA — never on absent DATA.**  Missing
   `E2E_TEST_SECRET` or a wrong project produce annotated skips with a
   reason: that infrastructure genuinely isn't here.  An empty league
   dataset is the opposite — the committed snapshot always carries
   rosters, rivalries, matchups and players, so "no data" means the
   pipeline broke and must **fail**.  Four such data gates were audited
   in 2026-07 and none of them had ever fired; each is now an assertion
   that the data is present.  Before adding a `test.skip` on a data
   condition, check whether the seeded snapshot can actually produce
   it — if it can't, you are writing a permanently-off guard that will
   one day convert a real regression into a green skip.
   See `docs/e2e-assertion-audit.md`.
6. **Assertions must be able to fail.**  The shell renders a nav
   carrying "Trade", "Rosters", "Settings", "News" on every route, so
   `expect(body).toContainText(/Trade/i)` passes on a page whose body
   never rendered.  Anchor on the page's own `<h1>`
   (`pageHeading()` in `helpers/journey.js` — the shell owns no `<h1>`)
   and on content derived from the live contract
   (`contractFixture()`), never on chrome.  When in doubt, run the
   assertion against a *different* page: if it still passes, it is
   vacuous.
7. **Screenshots/videos/traces on failure** come free from the config
   (`screenshot: only-on-failure`, `video: retain-on-failure`,
   `trace: on-first-retry`) — check `test-results/` or the CI
   artifact.

## CI

`.github/workflows/e2e.yml` runs the suite nightly and on manual
dispatch (deliberately **not** on every PR — it's a minutes-long,
full-stack run; `pr-validation.yml` owns the fast PR loop).  It boots
the stack from the committed snapshot, uploads the Playwright report
as an artifact, and maintains an idempotent tracking issue labelled
`e2e-failures` when a run fails.

The backend's startup scrape is deliberately disabled there (its
browser path points at an empty directory), so CI results are pinned
to the committed data snapshot — a scrape outage can never flake the
safety net, and the safety net never hits ranking sites.

## Redesign playbook

For each redesign phase:

1. Rewrite the page.
2. Run `npm run e2e` locally.
3. Selector broke but behavior intact → update `helpers/journey.js`.
4. Assertion broke → the phase changed behavior; either restore
   parity or (for a deliberate product change) update the journey
   spec **in the same PR** with a comment explaining the new
   contract.
5. New page/journey shipped → add a `journey-*.spec.js` following the
   conventions above, and gate it to the right projects
   (`desktopOnly` / `mobileOnly` helpers).
