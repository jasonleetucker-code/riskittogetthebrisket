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

**Deployment note (important):** in production, nginx routes every
`/api/*` request — including `/api/dynasty-data` — **straight to the
Python backend** (`deploy/nginx/riskittogetthebrisket.org.conf`), where
`server.py::get_dynasty_data_alias` → `get_data` already honors the
caller's `view`/`leagueKey`. The Next.js route at
`frontend/app/api/dynasty-data/route.js` is therefore **only on the dev
path** (no nginx in front) and any Next-fronted deployment. So the proxy
fixes below are **dev-path correctness/parity**, not production data-path
wins. The production win in this batch is the backend compact precompute.

| Area | Scope | Finding | Status |
|---|---|---|---|
| Compact view precompute | **Production + dev** | `?view=compact` re-ran `compact_contract` + `json.dumps` + gzip **on the event loop** for every request (no precompute). Now precomputed. | **Fixed** |
| Proxy view forwarding | Dev / Next-only | The Next proxy hardcoded `view=app`, so in the dev flow mobile's `view=compact` request was dropped (production was unaffected — it hits Python directly). | **Fixed** |
| Proxy stream-through | Dev / Next-only | The Next proxy parsed + re-serialized the whole multi-MB contract per request, discarding the backend's gzip/ETag. Now streams the body through with an idle-abort timeout. | **Fixed** |
| **Live-overlay serialization** | In normal operation (Sleeper overlay active for the loaded league), every `/api/data` request called `JSONResponse(content=scrubbed)` → re-serialized the **entire multi-MB payload on the event loop**. Now offloaded to a worker and cached per overlay window; adds ETag/304 + Vary. | **Fixed** |
| Client caching | The client fetches `/api/dynasty-data` with `cache: "no-store"`, so the browser never revalidates with `If-None-Match` — every navigation re-downloads the payload even when unchanged. | **Blocked** — see below |
| Frontend bundle | No bundle-size analysis yet; large client bundles delay first paint. | **Planned** |
| Render cost | Rankings table / trade views: audit for unmemoized recompute on sort/filter/scroll. | **Planned** |

## Done

### 1. Forward `view`/`leagueKey` + stream-through in the data proxy (dev path)
`frontend/app/api/dynasty-data/route.js` now forwards the caller's
`view` and `leagueKey` to the backend and streams the backend response
body through unchanged (preserving `Cache-Control` + `ETag`, forwarding
`If-None-Match`, with an idle-abort timeout that stays armed across the
body) instead of parsing and re-serializing the multi-MB contract on Node
per request. The disk fallback returns the raw contract; the client
already normalizes both raw and legacy `{ok,source,data}` shapes.
**Scope:** this is the **dev / Next-fronted** path only — production nginx
sends `/api/dynasty-data` directly to Python, which already honored
`view`. Impact is bringing dev in line with production (mobile gets the
compact view in dev; no Node parse+stringify of the whole contract).

### 2. Precompute the compact view (bytes + gzip + ETag)
`server.py::_prime_latest_payload` now precomputes the compact payload
alongside runtime/startup, and `/api/data?view=compact` serves those
cached bytes (with an ETag) instead of re-compacting + dumping + gzipping
on the event loop for every mobile request. Falls back to on-demand
compaction if the precompute ever fails. Regression test:
`tests/api/test_league_routing.py::test_api_data_compact_view_serves_precomputed_bytes`.

### 3. Offload + cache the live-overlay serialization (production hot path)
In normal operation the live Sleeper overlay is spliced onto every
`/api/data` response, which previously meant `JSONResponse(content=scrubbed)`
re-serialized the **entire multi-MB payload on the event loop for every
request** — the precomputed fast path was only used when the overlay was
unavailable. `server.py::_serialize_overlaid_response` now offloads the
JSON encode (+ gzip) to a worker thread (`run_in_threadpool`) and memoizes
the encoded bytes. Since the overlay is cached ~15 min per league, repeat
requests in that window reuse the dump instead of re-encoding. Also adds an
`ETag` (with `If-None-Match` → `304`) and `Vary: Accept-Encoding` to this
path.

**Stable-slot caching.** The cache key is the *context only* — `(kind,
leagueKey, loadedLeague, view, sleeper_matches)` — and the freshness stamp
(`overlayFetchedAt` + base `ETag`) is stored **inside** the entry as its
version. On a hit the version is compared; a mismatch re-encodes and
**replaces the slot**. Keying on the freshness stamp instead would mint a
fresh multi-MB entry (raw *and* gzip) on every 15-min overlay refresh and
every scrape, leaving prior generations resident — a memory sawtooth ending
in a wholesale clear that cold-misses every hot key. The same scheme covers
the cross-league (overlay-unavailable) fallback, whose version is the base
`ETag`. Slot count is bounded by the registry (leagues × views), so
`_evict_overlay_cache_if_oversized` is a safety net rather than the primary
bound; it preserves in-flight locks so an eviction can't orphan a running
single-flight encode.

Concurrent misses for one slot are single-flighted on a per-key
`asyncio.Lock`, so a burst after startup or a refresh can't fan out into N
duplicate serializations.

Regression tests (`tests/api/test_league_routing.py`):
`test_api_data_overlay_response_is_offloaded_and_cached`,
`test_overlay_serialize_single_flights_concurrent_misses`,
`test_overlay_serialize_cache_invalidates_on_version_change`,
`test_cross_league_cache_slot_is_reused_across_refreshes`.

## Rejected (attempted, reverted)

### Browser revalidation via `If-None-Match`/`304` — **not safe as-is**
Switching `frontend/lib/dynasty-data.js::_fetchBaseContract` from
`cache: "no-store"` to `cache: "default"` was tried and **reverted**. It is
not a staleness problem — it is an **auth** problem:

* `/api/dynasty-data` → `get_data` is a **private** endpoint; it is not in
  `_PUBLIC_API_EXACT`, so `_private_api_gate` 401s unauthenticated callers.
* But its success response carries
  `Cache-Control: public, max-age=30, stale-while-revalidate=300`.

With `cache: "default"` the browser's HTTP cache is allowed to store that
authenticated payload and satisfy a later request for the same URL **without
contacting the server** — so the private rankings contract can be replayed
after logout, or served to the next account to use that browser, never
reaching the gate for a fresh `401`.

Prerequisites before retrying:
1. Make the response auth-scoped (`Cache-Control: private`, plus a `Vary`
   on the session, or a per-session URL/key) — `private` alone still
   permits same-browser reuse after logout, so it is necessary but not
   sufficient.
2. Purge the cached entry on logout.
3. Only then relax the client's `cache` mode.

That is a correctness/security change to a production auth path, not a perf
tweak, so it is tracked separately rather than bundled here.

## Planned (prioritized)

1. **Frontend bundle analysis + code-splitting** for the heaviest routes
   (rankings, trade, league) to cut first-paint JS.
2. **Render-path audit** of the rankings table and trade views:
   memoization, virtualization for long lists, and avoiding recompute on
   sort/filter/scroll.
3. **Navigation** — ensure route transitions reuse cached data instead of
   refetching/recomputing.
4. **Client revalidation** — blocked on the auth-scoping work above.

## Validation notes

Backend changes here are covered by pytest (`tests/api`). Frontend proxy
changes are `node --check`-clean and rely on the client's existing
raw/wrapped normalization, but still need a browser/E2E pass
(`npm run regression`) against a running stack before rollout — the
vitest/Playwright toolchain isn't runnable in the current CI sandbox.
