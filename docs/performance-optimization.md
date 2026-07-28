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
Python backend** (`deploy/nginx/chaseupside.com.conf`), where
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
| Client caching | The client fetches `/api/dynasty-data` with `cache: "no-store"`, so the browser never revalidates with `If-None-Match` — every navigation re-downloads the payload even when unchanged. | **Fixed** (2026-07-28) — `cache: "no-cache"`, see the sitewide-audit section below; the "Rejected" entry below documents why `"default"` was unsafe and why `"no-cache"` is not |
| Frontend bundle | Analyzed 2026-07-28: NOT the bottleneck. 5 runtime deps, hand-rolled SVG charts, per-page chunks all under budget (`scripts/check-bundle-sizes.mjs`), shared chunk 102 KB. | **Closed (no action)** |
| Render cost | Rankings table / trade views: audit for unmemoized recompute on sort/filter/scroll. | **Partially fixed** (2026-07-28: `displayRows` memoized; virtualization deliberately deferred — see audit section) |

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

## 2026-07-28 sitewide performance audit (the "10-second pages" fix)

Full-stack audit + fix pass targeting the ~10s initial loads and
page-to-page navigations. Root causes, in impact order, all verified in
source and by measurement before changing anything:

1. **Every page load ran the full ranking pipeline server-side —
   twice.** The `/settings` default `tepMultiplier: 1.15` makes every
   stock user "customized" (`tepMultiplierIsCustomized` treats any
   finite number as an override), so every `fetchDynastyData` took the
   override path: `GET` base + `POST /api/rankings/overrides?view=delta`,
   and the POST rebuilt the whole pipeline synchronously ON the event
   loop, uncached (~0.75s locally, seconds on prod hardware). The hook
   mounts twice per page (AppShell + page), doubling all of it.
   *The default was deliberately NOT changed* — posting 1.15 flat is a
   different valuation than omitting it (ADR-015 basis curve), so the
   fix is memoization, not semantics.
2. **Cold Sleeper overlay rebuild = ~90 sequential HTTP round-trips
   inline on `/api/data`** whenever the 15-min TTL expired (~7 of 8
   windows, since the warm-behind only runs on the 2h scrape cadence),
   with no single-flight — concurrent expirees each launched their own
   storm.
3. **Desktop production downloaded the full ~11.8 MB contract.**
   `preferredDataView()` returned `"delta"` — not a valid GET view — so
   the param was dropped and the server defaulted to `view=full`.
4. **Event-loop blockers**: `/api/draft-capital` (~4s of openpyxl + six
   blocking Sleeper calls per request, ×3 per /draft load),
   `/api/terminal` + `/api/news` news aggregation evaluated as
   *arguments* to `run_in_threadpool` (i.e. on the loop) with ~6 RSS
   providers fetched sequentially, `/api/trade/suggestions` CPU on the
   loop, `/api/status` disk globs per request, `_prime_latest_payload`
   freezing the loop for seconds after every scrape.
5. **No request dedup client-side** and `cache: "no-store"` defeating
   the backend's working ETag/304 path.

### Caches added (contract per CLAUDE.md's documentation rule)

| Cache | Key | TTL / bound | Invalidation | Stale window | Why appropriate |
|---|---|---|---|---|---|
| `server._OVERRIDES_RESPONSE_CACHE` (bytes) | sha1(canonical POST body) + view + league + sleeper_matches | version-keyed (no TTL), 16 slots | `latest_data_etag` mismatch → rebuild in place; cleared by `_prime_latest_payload`; leagueAdjusted bypasses | none — versioned on contract generation | ~every client posts the identical stock body; output is a pure function of (body, contract generation) |
| client `_cachedBaseContract` + inflight map | (leagueKey, view) | 30s | `_resetBaseContractCache()` on league switch + `auth:changed`; errors never cached | ≤30s — same as the server's `max-age=30` | collapses the double-mounted hook onto one fetch |
| client merged-override memo + inflight | (POST body, league) pinned to base object identity | 30s | base identity change, key change, reset | ≤30s | same delta for same body+generation |
| browser HTTP cache (`no-cache`) | URL | revalidate-always | 304 requires passing `_private_api_gate`; 401 after logout | none served without revalidation | unlocks zero-body 304s; see “Rejected” note below for why `"default"` was unsafe and `"no-cache"` is not |
| `sleeper_overlay._CACHE` (upgraded) | sleeper_league_id | 15 min fresh (unchanged) | `force_refresh`, refresh completion | **15–30 min stale-serve with exactly one background refresher** (operator-approved); >30 min blocks on a single-flighted rebuild | roster/trade context, not valuations; was already 15 min stale by design |
| `sleeper_overlay._BuildFetcher` | URL, scoped to ONE build | build lifetime | n/a | none — dedupes URLs previously fetched ms apart | trades+waivers read the same 19 weekly feeds; chain/roster lookups ran 2-3× per build |
| `server._DRAFT_CAPITAL_CACHE` | league key | 300s | `?refresh=1`, scrape promotion, TTL | ≤5 min of pick-ownership data — same freshness class as the overlay | endpoint was ~4s of blocking work per request, ×3 per /draft load |
| `server._DRAFT_WB_CACHE` (openpyxl workbook) | (path, mtime_ns, size) | none | file replacement | none — keyed on file identity | workbook changes only by deploy/edit |
| `server._LIVE_CONTRACT_SCAN_MEMO` (names/meta) | `latest_data_etag` | single entry per kind | new contract generation | none | pure projections of the contract |
| `NewsService._cache` (upgraded) | sha1 of known-names universe (was a ~2,000-string tuple) | **600s (was 180s, operator-approved)**; failure TTL unchanged | TTL | ≤10 min headlines | aggregated RSS rarely updates faster; providers now fetch concurrently so even cold refreshes are ~5s worst-case, not ~30s |
| `server._DISK_PROBE_MEMO` (status/health probes) | helper name | 30s | TTL only | ≤30s on ages measured in hours | pure observability; polled every 60s from every page |

### Other changes in this pass

* `?view=array` (alias `desktop`): fifth precomputed `/api/data`
  variant — the full contract minus the LEGACY `players` dict (a
  parallel encoding of `playersArray`). 11.83 MB → 6.45 MB raw,
  1.18 MB → 674 KB gzip, and `buildRows(full)` vs `buildRows(array)`
  is row-for-row IDENTICAL (pinned by `tests/api/test_array_view.py` +
  a 1,073-row live parity run). Desktop now requests it. `view=app`
  and `view=compact` were both rejected for desktop: they drop
  tier/confidence/audit fields that 20+ desktop surfaces render.
* `_prime_latest_payload` restructured to compute-into-locals +
  tight-swap publish, and the scrape-completion call site offloads it
  to the threadpool. Failure now atomically publishes the empty
  generation.
* Weekly Sleeper transaction feeds + per-league lookups prefetched in
  one bounded parallel wave; cold overlay build measured at 51 unique
  calls (was ~90 with duplicates, fully sequential).
* Route-level `loading.jsx` for the 12 main routes; preconnect to
  sleepercdn.com; SW `NEVER_CACHE` now includes `/api/data` +
  `/api/dynasty-data` (v7 bump); `/rankings` `displayRows` memoized;
  `useTerminal` gained `skip` and all 8 call sites gate on team
  resolution (kills the discarded `ownerId:""` duplicate);
  `/tools/trade-coverage` uses a 4-wide worker pool instead of 12
  sequential awaits.

### Measured (local prod-topology harness: next build + next start + nginx-standin proxy)

| Metric | Before | After |
|---|---|---|
| `POST /api/rankings/overrides` (stock body, warm) | 0.75–0.93s every call | **4ms** (memo hit; 0.73s once per scrape generation) |
| `/api/data` desktop wire | 11.83 MB raw / 1.18 MB gzip (view=full) | 6.45 MB / 674 KB (view=array), then 304s |
| `/api/terminal` | 7.8s cold / 20ms warm | 1.4s cold / 20ms warm |
| `/api/draft-capital` | 3.9–4.1s EVERY request, on the loop | 2.6–3.2s cold (threadpooled) / **5ms** warm |
| `/trade` page settle | 13.5s (LCP 12.4s) | **1.7s** (LCP 0.7s) |
| `/draft` page settle | 11.4s | **1.6s** |
| `/rankings` usable | 6.9s | **1.1s** |
| `/` LCP | 2.7s | 0.8s |
| per-page transfer | 2.5–4.9 MB | 2.1–3.4 MB (and ~0 on repeat within 30s) |

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
