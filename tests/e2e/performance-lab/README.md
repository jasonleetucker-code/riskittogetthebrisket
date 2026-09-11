# Prepared read-model browser lab

This opt-in local lab uses 120 synthetic players. It exercises the production
Next build and its actual read-model, detail, and override proxy routes against
a fixture backend. It does not validate production latency or real valuation
data. Keep the rollout flag off until the separate production gates pass.

From `frontend`, build with `NEXT_PUBLIC_PREPARED_READ_MODELS=1` and
`NEXT_DIST_DIR=.next.prepared-lab`:

```sh
npm run build
```

Start that build with `BACKEND_API_URL=http://127.0.0.1:3083` and the same
`NEXT_DIST_DIR` (the public flag was compiled at build time):

```sh
node node_modules/next/dist/bin/next start -p 3081 -H 127.0.0.1
```

From the repository root, in another terminal:

```sh
node tests/e2e/performance-lab/fixture-server.mjs
```

The fixture listens only on loopback: backend `3083`, browser origin `3082`.
The front proxy supplies `/api/test/create-session`, `/api/user/state`, and
`/api/health`, which the development Next router does not provide, plus the
lab-only control endpoint. All other browser requests go through Next `3081`.
The fixture cookie and every identity/value are synthetic. Do not point this
lab at a production server or real account.

With Playwright installed, run from the repository root:

```sh
node tests/e2e/performance-lab/browser-lab.mjs
node tests/e2e/performance-lab/diagnose.mjs
node tests/e2e/performance-lab/geometry.mjs
```

Set `PW_CHROMIUM_PATH` to an installed Chromium executable if Playwright's
downloaded browser is unavailable. `PERF_LAB_OUTPUT` optionally changes the
artifact directory; the default is `output/playwright`.

The browser driver also requires successful privacy-safe document Web Vitals POSTs on each route, rejects extra fields and Referer headers, and records the Node runtime. It does not require unobserved INP/CLS values.

The browser driver checks rankings/trade in desktop/mobile viewports, exact
CSV equality between full-shaped and prepared fixtures, filtering, source
display controls, expanded source audit, actual full popup content, trade
selection, and first-intent catalog search. It rejects global `/api/data` or
`/api/dynasty-data` requests on the migrated routes and uncaught page errors.
Both fixture variants use the flag-on API path: this proves projection
consumer parity, not a separate flag-off build comparison. Backend producer,
custom override arithmetic, and authorization tests remain separate.

The diagnostic script runs one cold and warm mobile navigation per route with
4x CPU throttling, 150ms latency, 1.6Mbps download and 750Kbps upload. It keeps
the ten-second useful-state cutoff and records resource groups, API waterfall,
CDP script/layout task durations, long tasks, and marker geometry. Run after
other tests/builds stop. It does not change the readiness predicate or app.

The geometry script checks mounted versus total row counts, reachability of
the last row, stable column widths while scrolling, horizontal scrolling,
and width restoration across desktop/mobile resizing. Compare its output
before and after a rendering change using separate `PERF_LAB_OUTPUT` folders.

The general baseline harness is `frontend/scripts/measure-route-baselines.mjs`.
Use `E2E_BASE_URL=http://127.0.0.1:3082`,
`E2E_PAGE_ORIGIN=http://127.0.0.1:3082`, `E2E_TEST_SECRET=lab-only`, and the
same browser executable setting. For example, from `frontend`:

```sh
node scripts/measure-route-baselines.mjs --runs 3 --viewport both --routes /rankings,/trade,/league-comparison --json ../output/playwright/prepared-baseline.json
```

`GET /__lab/control?variant=full` switches to the full-shaped fixture;
`variant=prepared` restores the projected fixture. `detailDelay=350` makes
the loading-state assertion observable. This control exists only in the lab.

Next fetch decodes the fixture's gzip stream and the route removes stale
encoding/length headers. Local browser API entries consequently have equal
encoded and decoded sizes. The separately recorded fixture gzip sizes are
upstream bytes; production nginx serves the backend directly and was not
measured here. CWV are observations within the declared lab window; unreported
values remain null, and these are not finalized document metrics or field p75.

The checked-in `evidence.json` records the bounded validation and its failures.
Detailed generated reports and screenshots remain in the output directory.
The median-update guard removes redundant row-window state updates and passes
the geometry and interaction checks. Its measured speed benefit remains
unproven, and the throttled useful-state gate remains failed.
