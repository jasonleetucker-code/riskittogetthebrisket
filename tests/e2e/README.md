# E2E regression suite

Playwright suite that boots the real stack (FastAPI backend :8000 +
Next.js frontend :3000) and drives a browser through the critical user
journeys.  It is the **functional-parity safety net for the UI
redesign**: every phase of the rewrite must leave this suite green.

No external network and no credentials are required — the backend
serves data seeded from the committed snapshot (`exports/latest/`,
kept fresh by `scheduled-refresh.yml`), and authentication uses the
test-only session endpoint.

## Running locally

```bash
npm install                       # root deps (@playwright/test)
npm --prefix frontend install     # frontend deps (Next.js build)
npm run regression:install        # one-time: download chromium

# Chromium-only safety net (desktop + mobile viewport):
export E2E_TEST_MODE=1            # enables /api/test/create-session
export E2E_TEST_SECRET=localdev   # shared by server + test runner
export ALLOW_DEFAULT_LOGIN_DEV=1  # placeholder login password for dev
npm run e2e

npm run e2e:report                # open the HTML report
```

`npm run e2e` runs preflight (compile checks, contract validation,
**data seeding** — it copies `exports/latest/dynasty_data_*.json` into
`data/` when `data/` has no snapshot), then the suite on the
`desktop-1366` + `mobile-chromium` projects with `--ignore-snapshots`
(pixel baselines are not committed; the visual specs still run their
structural assertions).

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
| `E2E_PAGE_ORIGIN` | Origin for **page** navigations (APIs keep `E2E_BASE_URL`).  Defaults to `http://127.0.0.1:3000` in webServer mode, empty when `E2E_BASE_URL` is set.  Needed because server.py's page proxy has a 5s timeout (slow SSR passes like `/league` exceed it) and doesn't register every Next page (e.g. `/waivers`) — production routes pages straight to Next via nginx, and this reproduces that topology |
| `E2E_TEST_MODE=1` + `E2E_TEST_SECRET` | Enable the test-session endpoint on the server; the same secret on the runner side unlocks the signed-in specs (they **skip cleanly** when unset) |
| `E2E_FRONTEND_CMD` | Override the frontend `webServer` command (default: production build + start) |
| `E2E_CHROMIUM_PATH` | Launch a pre-installed Chromium binary instead of the revision-pinned download (sandboxes / air-gapped runners) |
| `SKIP_VISUAL_REGRESSION=1` | Skip the two visual-regression specs entirely |

## Spec inventory

| Spec | Layer | What it protects |
|---|---|---|
| `journey-rankings.spec.js` | signed-in UI | Board renders real rows; column sort; position filter; board search; player popup with source breakdown; global search (`/`) |
| `journey-trade.spec.js` | signed-in UI + API | `/trade` builder renders + controls; `/trades` history; `/finder` arbitrage board rows; `POST /api/trade/finder` returns trades for a real roster |
| `journey-settings-overrides.spec.js` | signed-in UI | Settings lists every registered source; toggling one fires `POST /api/rankings/overrides` and the board re-renders with the custom-mix badge |
| `journey-news.spec.js` | signed-in UI | `/news` tab — skips with a clear message while the route 404s (pre-PR #533) and self-activates once it ships |
| `mobile-smoke.spec.js` | signed-in UI @390x844 | Board usable, popup opens/closes, bottom nav navigates |
| `critical-smoke.spec.js` | public | Every route renders without JS errors; API auth gates |
| `public-league.spec.js` | public | The whole public `/league` hub: tabs, deep links, franchise/rivalry/player routes, privacy isolation |
| `signed-in-smoke.spec.js` | signed-in | Authed pages + API round-trips |
| `waivers-smoke.spec.js` | signed-in UI | `/waivers` renders + filters operate |
| `multi-league.spec.js` | API | League registry + `?leagueKey=` contract |
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
5. **Skip cleanly, never fail on absent infra.**  Missing
   `E2E_TEST_SECRET`, a not-yet-shipped route (`/news`), or an empty
   league dataset produce annotated skips with a reason.
6. **Screenshots/videos/traces on failure** come free from the config
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
