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

## Phase 2 attribution and private replay

The lab can export the existing offline canonical builder's accepted bytes:

```sh
python tests/e2e/performance-lab/export-replay.py --input <private_serving/recorded-input.json> --output-dir <private_serving/replay>
```

The output must remain under an ignored `private_serving` directory. It contains
private payloads, the canonical player index, and raw input. Never commit or
publish it. The script wraps the existing payload measurement's producer and
validation; it does not introduce another projection implementation.
Set `PERF_LAB_REPLAY` to this directory when starting `fixture-server.mjs`.
The default fixture remains the synthetic 120-row board. Replay responses use
exact exported raw/gzip bytes and verify the raw SHA-256 before serving.

For diagnostic attribution only, build with
`NEXT_PUBLIC_PERFORMANCE_LAB=1 NEXT_PUBLIC_PREPARED_READ_MODELS=1`
and `next build --webpack --profile`. Run `diagnose.mjs` with
`PERF_LAB_INSTRUMENTED=1`. This enables the opt-in collector before hydration.
It records fixed phase/scope enums and finite timings/counts, with no URLs,
settings, auth state, player/league IDs or payload data. Marks distinguish
module evaluation, initial hydration commit, local settings read, auth probe,
fetch/cache joins, response headers/body, JSON parse, shared materialization,
publication/commit, React Profiler duration and existing table width reads.
The diagnostic JSON path explicitly reads text then parses it, so these
instrumented timings are attribution only, never acceptance numbers.

Build acceptance candidates without the lab flag and without `--profile`.
Do not set `PERF_LAB_INSTRUMENTED`. Run baseline Next on port 3084 and candidate
Next on port 3081, both pointing to fixture backend 3083. The existing diagnostic
harness accepts `PERF_LAB_SEQUENCE=3084,3081,3081,3084` for controlled A/B/B/A
navigation order. `PERF_LAB_ROUTE=/rankings` limits the candidate comparison to
the affected route. Every cold sample uses a fresh browser context; its warm
sample reloads in that same context. There are no other builds/tests/soaks in
these measured windows. Keep failed ten-second predicates null; no slower
result becomes a passing sample through the extra diagnostic observation.

`PERF_LAB_TRANSPORT=next-proxy` exercises the actual Next bridge and its decoded
local response. `direct-gzip` routes local API calls straight to the fixture,
simulating nginx's direct API routing and preserving the exported gzip bytes.
It is a transport lab, not a production deployment measurement. This distinction
matters for a 3.1MB decoded replay at 1.6Mbps. The original profile experiment
used Node's default gzip recompression; final replay comparisons use the
producer's exact level 5 gzip bytes. Both are labeled in Phase 2 evidence.

The rejected hidden-cell candidate kept all rows, headers, td and col geometry,
and the same sort/filter/export inputs. Only rankings opted in. Below the existing
CSS breakpoint, body-cell child renderers for already-hidden columns were skipped;
the matchMedia subscription restores them when the viewport widens. The shared
CSS/token breakpoints are pinned by a test. Server and initial hydration render
the same tree; a hydration test includes preloaded rows. No initial width or
row-window algorithm changes are part of this candidate.

The hidden-cell candidate was fully reverted after all 16 uninstrumented
rankings samples missed the unchanged useful-state cutoff on both builds.
Its geometry and consumer checks passed, but speed benefit was not established.
`rejected-hidden-cell.patch` preserves the exact experiment for reproduction;
it is not active product code. Reapply only for a deliberate lab experiment
with `git apply --unidiff-zero tests/e2e/performance-lab/rejected-hidden-cell.patch`. `phase2-evidence.json` records the failed gate,
stage attribution and final kept-code validation. `replay-smoke.mjs` compares
private replay CSV hashes after the existing Show all action, filtering, source
controls, geometry and full popup content without writing private screenshots
or assertion text. The synthetic driver rejects private replay explicitly.
