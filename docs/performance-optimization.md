# Performance Optimization Program

Tracking doc for the site-wide performance push toward a consumer-ready
rollout. Each item is a discrete, independently reviewable change. This
doc is the running ledger: **Done**, **In progress**, **Planned**, with
the evidence behind each.

## Method

1. Trace the *live* execution path before changing anything (CLAUDE.md
   rule #1) — no speculative optimization.
2. Prefer the smallest change that removes real work: eliminate
   duplicated serialization, oversized payloads, per-request recompute,
   and event-loop blocking.
3. Every change ships with a regression test where the path is testable,
   and a note on what still needs browser/load validation.

## Audit summary

The backend `/api/data` contract is already well-optimized *in the
degraded path*: it precomputes `bytes + gzip + ETag` for the full /
runtime / startup views and supports `304` revalidation. The real costs
are elsewhere:

| Area | Finding | Status |
|---|---|---|
| Mobile payload | Frontend proxy silently dropped the client's `view=compact` request → mobile always got the full `view=app` payload. | **Fixed** |
| Proxy CPU | `/api/dynasty-data` parsed + re-serialized the whole multi-MB contract per request, discarding the backend's gzip/ETag/cache headers. | **Fixed** |
| Compact view | `?view=compact` re-ran `compact_contract` + `json.dumps` + gzip **on the event loop** for every request (no precompute). | **Fixed** |
| **Live-overlay serialization** | In normal operation (Sleeper overlay active for the loaded league), every `/api/data` request calls `JSONResponse(content=scrubbed)` → re-serializes the **entire multi-MB payload on the event loop**. The precomputed bytes fast path is only used when the overlay is *unavailable*. This is the single biggest backend cost and blocks the loop under concurrency. | **Planned (next, high priority)** |
| Client caching | The client fetches `/api/dynasty-data` with `cache: "no-store"`, so the browser never revalidates with `If-None-Match` — every navigation re-downloads the payload even when unchanged. | **Planned** |
| Frontend bundle | No bundle-size analysis yet; large client bundles delay first paint. | **Planned** |
| Render cost | Rankings table / trade views: audit for unmemoized recompute on sort/filter/scroll. | **Planned** |

## Done

### 1. Forward `view`/`leagueKey` + stream-through in the data proxy
`frontend/app/api/dynasty-data/route.js` now forwards the caller's
`view` and `leagueKey` to the backend and streams the backend response
body through unchanged (preserving `Cache-Control` + `ETag`, forwarding
`If-None-Match`) instead of parsing and re-serializing the multi-MB
contract on Node per request. The disk fallback returns the raw contract;
the client already normalizes both raw and legacy `{ok,source,data}`
shapes. **Impact:** mobile now actually receives the compact view; the
per-request Node parse+stringify of the whole contract is gone.

### 2. Precompute the compact view (bytes + gzip + ETag)
`server.py::_prime_latest_payload` now precomputes the compact payload
alongside runtime/startup, and `/api/data?view=compact` serves those
cached bytes (with an ETag) instead of re-compacting + dumping + gzipping
on the event loop for every mobile request. Falls back to on-demand
compaction if the precompute ever fails. Regression test:
`tests/api/test_league_routing.py::test_api_data_compact_view_serves_precomputed_bytes`.

## Planned (prioritized)

1. **Offload + cache the live-overlay serialization.** Move the
   `JSONResponse(content=scrubbed)` serialization off the event loop
   (`run_in_threadpool`, mirroring the public-league fix) and cache the
   overlaid, serialized bytes keyed by `(leagueKey, view,
   overlayFetchedAt)`. The overlay is already cached ~15 min per league,
   so the serialized result is stable within that window — repeat
   requests can reuse it instead of re-dumping multi-MB per request.
2. **Let the client revalidate.** Drop `cache: "no-store"` on the base
   contract fetch (or switch to a conditional fetch) so the browser can
   send `If-None-Match` and get `304`s within the backend's
   `max-age`/`stale-while-revalidate` window.
3. **Frontend bundle analysis + code-splitting** for the heaviest routes
   (rankings, trade, league) to cut first-paint JS.
4. **Render-path audit** of the rankings table and trade views:
   memoization, virtualization for long lists, and avoiding recompute on
   sort/filter/scroll.
5. **Navigation** — ensure route transitions reuse cached data instead of
   refetching/recomputing.

## Validation notes

Backend changes here are covered by pytest (`tests/api`). Frontend proxy
changes are `node --check`-clean and rely on the client's existing
raw/wrapped normalization, but still need a browser/E2E pass
(`npm run regression`) against a running stack before rollout — the
vitest/Playwright toolchain isn't runnable in the current CI sandbox.
