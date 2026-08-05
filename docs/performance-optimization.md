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

## 2026-07-29 round 2 — CLS, /league TTFB, terminal race

Follow-up to the sitewide audit, taking its top three remaining items.

**CLS (measured: `/` 0.72 → 0.088; `/draft` and `/waivers` claimed
0.005 / 0.063 — SEE THE ROUND 3 CORRECTION BELOW, those two numbers
were single-run flukes and the underlying shifts were not fixed):**
- `/`'s dominant shift was the auth swap: `app/page.jsx` first-painted
  the ~200px landing card for EVERY visitor (auth resolves in an
  effect) and then replaced it with the ~4000px terminal.  The `null`
  auth state now renders a terminal-shaped skeleton shell (command
  stats + chart slot + ticker strip + rail + 3-col grid), with a 4s
  cap falling back to the navigable landing if the probe stalls.
- Terminal panels: chart slot always mounted with reserved height
  (`TeamCommandHeader`), sized `SkeletonTable`s replacing one-line
  string loaders (`MoversPanel`, `PortfolioSummary`, `BuySellHold`),
  height-stable rail placeholder while the team resolves
  (`TopSignalsRail`), `min-height` on `.ticker`.
- `/draft` pre-auth skeleton now matches its `loading.jsx` geometry
  (was 3 different heights in sequence); `/waivers` stubs the full
  settled layout, not just the first panel.
- Deliberately NOT reserved: the `StaleDataBanner` slot.  It renders
  only in rare stale/stalled alert states (contributed ~0 to the
  measured CLS on fresh data) and permanently reserving ~40px on every
  healthy page is the wrong trade for an alert that is meant to
  interrupt.

**/league TTFB (measured: 2.5–4s → ~85ms warm):** `GET
/api/public/league` rebuilt all 16 sections + double-safety-walked +
`json.dumps`ed the multi-MB contract per request, while the identical
contract was already built and discarded during every snapshot
rebuild.  Now: `_PUBLIC_CONTRACT_BYTES_CACHE` — key
`(root_league_id, snapshot.generated_at, latest_data_etag)` (private
etag included because activity trade grades derive from the private
board), value = pre-encoded response bytes, no TTL
(generation-keyed), bound 4, seeded by the rebuild's persist step,
`?refresh=1` bypasses the read.  Freshness identical to before — the
300s snapshot SWR window governs, the memo never outlives a
generation.  Also: duplicate `assert_public_payload_safe` walk
dropped (the builder asserts internally), activity-valuation callable
memoized per private generation, and `app/league/page.jsx` wraps its
fetch in React `cache()` so `generateMetadata` + the page body share
one backend call per render.

**Terminal duplicate fetch (measured: 2 calls → 1, team pre-resolved):**
`useTeam().loading` now means "team identity not yet answerable":
`dataLoading || !settingsHydrated || autoAssignPending`, where
`autoAssignPending` clears when the auto-assign effect completes for
BOTH outcomes (match or no-match — a league with no default team must
not hold forever) and `selectionTouched` is the deliberate-clear
escape hatch.  All seven `useTerminal` call sites already gate on it
via `skip`.

## 2026-07-29 round 3 — CLS, honestly this time

### First: a correction to round 2

Round 2 reported `/draft` 0.34 → 0.005 and `/waivers` 0.20 → 0.063.
**Both were wrong.**  They were single-run measurements, and CLS on a
data-driven page is close to a coin flip run-to-run — it depends
entirely on whether async data lands before or after paint.  Re-measured
as a **5-run median**, the true post-round-2 values were `/draft` 0.336
and `/waivers` 0.219: the round-2 skeleton changes on those two pages
had essentially no effect on the real shift sources.

**Rule going forward: CLS is reported as a 5-run median, and a fix is
only "done" when the fixed element disappears from the browser's own
layout-shift SOURCE ATTRIBUTION** — not when an aggregate number looks
better.  Chrome's `LayoutShift.sources` (with `previousRect`/
`currentRect`) is what actually identifies the culprit; every fix below
was found that way, and two plausible-sounding fixes were discarded
because attribution showed they moved nothing.

### Measured (5-run medians, local prod-topology harness)

| Route | After round 2 (real) | After round 3 |
|---|---|---|
| `/trade` | 0.139 | **0.004** |
| `/draft` | 0.336 | **0.013** |
| `/` | 0.093 | **0.069** |
| `/waivers` | 0.219 | **0.208** — NOT fixed, see below |
| `/draft-capital` TTFB | 1445ms | **87ms** |

Every other route re-swept: CLS ≤ 0.076, LCP < 1s, no regressions.

### What actually fixed it

* **`/trade` (0.139 → 0.004).** The proactive-suggestions rail is
  fetched after a 500ms debounce plus a round-trip, so it always
  mounted *after* the page painted, inserting a 213px panel above the
  trade controls and meter.  Two changes: the rail now reserves its
  slot (`SuggestionsRailPlaceholder`, reusing the real `Panel` header so
  only the body is bones) driven by a `suggestionsPending` flag that
  **defaults true** — effects run post-commit, so a `false` default
  still left one un-reserved frame — and the loading skeleton was
  retuned from 6 rows (258px) to 4 (213px) so the loading→content
  transition is height-neutral.  **Matching the heights exactly is what
  mattered**: a reserved-but-wrong-height slot (233px vs 213px) still
  shifted.
* **`/draft` (0.336 → 0.013).** Three compounding inserts above the
  ~440px team list: the button label swapping `"Loading…"` →
  `"↻ Load from Draft Capital"` (wrapped to a 2nd line, and once
  `nowrap`'d still re-wrapped the sibling description by changing
  width — fixed with `nowrap` + a `minWidth` of the measured 223px
  settled width); the Draft-Capital status line appearing (reserved
  26px); and the progress bar + stats strip (26px + 105px) that exist
  only after auth resolves, now reserved in the pre-auth skeleton.
* **`/draft-capital` TTFB (1445ms → 87ms).** It was never a slow page —
  it was an 11-line React component calling `redirect()`, so the first
  leg cost a full route invocation and the number being measured was
  really `/league`'s SSR.  Moved to a routing-layer 308 in
  `next.config.mjs` and deleted the page.  `server.py::serve_draft_capital`
  now returns a real `RedirectResponse` instead of proxying — its
  `urllib`-based proxy follows redirects, so it would have served
  `/league`'s HTML under the `/draft-capital` URL and blocked the event
  loop for the whole SSR.
* **`/waivers` `ManualAddDrop`.** Rendering a one-line "select a team"
  message and then expanding to the full calculator grew that panel
  150px → 646px.  It now holds a sized skeleton while
  `useTeam().loading` is true.  This removed that source from the
  attribution — but see below, it was not the page's dominant shift.

### Tried and reverted (negative results, recorded so nobody retries them)

* **`min-width` on the topbar league/team switchers.**  The switchers
  grow when their labels resolve (`.shell-nav-right` 386px → 464px),
  which slides its left-hand siblings — a real horizontal shift that
  counts fully toward CLS.  Reserving their width made things
  **measurably worse** (`/` 0.069 → 0.199) and was reverted.  Horizontal
  reservation in a `margin-left: auto` flex row re-distributes space in
  ways that create new shifts; if this is retried, the fix probably
  belongs in the switcher's own label placeholder, not the toggle width.

### Still open: `/waivers` 0.208 — **CLOSED IN ROUND 4, and this diagnosis was wrong**

> Kept as written because the correction is the lesson.  This section
> read the shift's source-attribution list — two `BUTTON.shell-nav-link`
> elements at ~320ms — as naming the *cause*, and concluded the fix was
> a switcher label placeholder.
>
> Round 4 A/B-tested exactly that: pinning `.shell-nav-right` to its
> settled width moved `/` from 0.0925 to 0.0889.  The rail was a
> co-source, not the cause.  Those two buttons were moving because the
> *nav item set changed* — `TopBar` answered "signed in?" with the
> public nav while the answer was still unknown, then inserted four
> items.  Fixing that, plus a wrapping page description, took
> `/waivers` to 0.014.
>
> **Co-listed is not causal.** Attribution tells you what moved; only
> an intervention tells you why.

## 2026-07-29 round 4 — the last CLS, /league's payload, CSS scope, board growth

Round 3 closed with one route outside Google's "good" CLS band and a
hypothesis about why.  **The hypothesis was wrong**, and finding that
out is most of what this round is.

### Measurement environment: it was broken, and it lied quietly

Every CLS reading at the start of this round was `0`, on every route,
with LCP ~200ms.  Cause: `next start` was serving a `.next` directory
that had been rebuilt underneath it, so the client requested chunk
hashes the running server no longer had.  The pages rendered a shell
and nothing else, which reads as "perfect CLS" rather than as an error.

**Restart `next start` after every `npm run build`.** A stale server
does not fail loudly; it reports excellent numbers for a page that
never rendered.

A second, subtler harness bug: the first A/B harness injected candidate
CSS from an `addInitScript` `<style>` tag, and reported **CLS = 0 for
every variant including the placebo**.  The injection itself perturbed
paint timing.  The working harness routes the *stylesheet response*
(`page.route("**/_next/static/css/*.css")`) and appends to its body —
content changes, timing does not.  With that, placebo reproduced
control to four decimals, and the A/B results below are trustworthy.

Rule, alongside round 3's 5-run-median rule: **an A/B without a placebo
arm is not an A/B.**

### Results (5-run medians, prod topology)

| Route | Round 3 end | Round 4 end |
|---|---|---|
| `/waivers` | 0.180 | **0.014** |
| `/draft` | 0.316 | **0.073** |
| `/trade` | 0.117 | **0.004** |
| `/` | 0.094 | 0.093 |

25-route sweep: every route CLS ≤ 0.091, LCP ≤ 1096ms, TTFB ≤ 92ms.

### What was actually causing it

**1. The shell nav guessed at auth.** `TopBar`'s `authenticated` prop is
tri-state, and `visibleGroups` answered `null` ("not resolved yet") with
the *public* nav.  Signed-in users got a 2-item nav on the first paint
and then had four items inserted, sliding "Trade" 185→335px and
"League" 266→586px — on **every route**, since this is the shell.  Now
renders nothing until the answer arrives, which is free: the nav sits
between a left-aligned brand and a `margin-left: auto` rail, so items
appear without moving either neighbour.

Round 3's guess — that `/waivers` needed a *switcher label placeholder*
— was wrong twice over.  The switcher rail does grow (205→335→464px),
but an A/B pinning `.shell-nav-right` to its settled width moved `/`
only 0.0925→0.0889.  The rail is a co-source in the attribution list,
not the cause.  **Co-listed is not causal**; only the intervention
tells you which.

**2. A 4px header growth was worth 0.24 CLS.** `/draft`'s reserved
status-line slot had `min-height` but no block formatting context, so
the status block's own `margin-top` collapsed *through* the slot and
pushed it down 4px.  Four pixels — but they move the ~490px team list
below, and the A/B measured that at 0.24 of the page's 0.315.
`display: flow-root` keeps the margin inside the reservation.

**Reserving a box is not reserving the space.** A `min-height`
placeholder whose future children carry margins needs `flow-root`.

**3. Two "we don't know yet" windows, collapsed instead of reserved.**
`/trade` cleared `suggestionsPending` while `loading`, poisoning the
first `!loading` paint; and again in the commit between `useTeam`
resolving the team and `selectTeam` populating the page's roster
mirror.  The second is why the page measured *bimodally* — 3 runs at
0.226, 2 at 0.003, depending on whether the roster beat the paint.
Topbar→page team resolution is now one derived value with a real
three-way answer (`null` = not answerable yet).

**A bimodal metric is a race, not noise.** Averaging it hides the bug.

**4. `/waivers` completes its own page description.** The subtitle
appends `— <league name>` when the league resolves, crossing the 60ch
measure and wrapping to a second line: every panel on the page drops
19px.  Opt-in `.ds-page-header--reserve-2-line-description`.

### `/league`: 2.38 MB → 91 KB

The route server-fetched the aggregate public contract (2.01 MB, 17
sections) and passed the whole object to a client component, which
serialized it into the RSC flight payload.

| | before | after |
|---|---|---|
| `/league` document | 2,383,091 B | **91,346 B** |
| total transfer time | 377ms | 34ms |
| LCP (browser, warm) | 932ms | **276ms** |

Two things made it worse than merely large:

* **Two shipped sections are never read by this page.** The AI-article
  tabs replaced the structured preview/recap views, so `weeklyRecap`
  (378 KB) and `matchupPreview` (11 KB) were pure transfer.
* **It could not be cached on the way in.** Next's Data Cache refuses
  entries over 2 MB, so `revalidate: 60` on the aggregate was silently
  inert and every render re-fetched and re-parsed 2 MB.  The build log
  said so on every build; nobody had read it as a *correctness* notice
  about the cache directive.

Now: `page.jsx` fetches `overview` (the header's season label needs it
on every tab) plus the landing tab's own section, so a deep link to any
tab is still fully server-rendered and crawlers still see real content.
`LeagueClient` fetches each remaining section when the visitor opens
the tab that renders it.

**Cache, per section entry:** Next Data Cache · key = the section URL ·
revalidate 60s · invalidated by that window elapsing.  Stale reads are
possible and bounded at ~60s of an already eventually-consistent public
page — no private data, no trade math, nothing a user acts on.  A
long-lived tab CAN hold two sections built from snapshots up to a
minute apart; they are independent read-only views (Records vs
Archives), never two halves of one number.

Latent bug found on the way: the frontend's `PUBLIC_SECTION_KEYS` was
missing `teamAssignment`, which the backend serves.  Nothing had ever
requested that section individually, so `fetchPublicSection` would have
thrown the first time anyone did.  A lockstep test now fails if a tab
maps to a section the public API will not serve.

Still open: `app/sitemap.js` fetches the aggregate, so the 2 MB
Data-Cache warning persists for that route.  Crawler-only, not on any
user path.

### CSS: route-scope the draft board

`globals.css` is imported by `app/layout.jsx`, so all ~70 routes
downloaded and parsed 27 KB of `.draft-*` rules that only
`app/draft/page.jsx` renders.

| | before | after |
|---|---|---|
| globals CSS chunk | 112 KB | **92 KB** |
| CSS per route (not `/draft`) | 194 KB | **174 KB** |

Mechanical split: a rule moved only if its **entire** selector list
references a `.draft-` class, with `@media` blocks split so their
draft-only rules travel.  Zero rules mixed draft and non-draft
selectors.

Verified by full-page pixel diff of 15 routes at 1366×900 and 390×844:
`/draft` byte-identical at both, every other route within
text-antialiasing noise (3 mobile shots, 19–56 px, 0.001–0.017%).  That
check is the point — extraction silently changes **cascade order**,
because page CSS now loads *after* layout CSS, so any specificity tie
between a moved `.draft-x` rule and a later global rule would flip.

**Honest scope note.** "191 KB globals.css" overstates the cost.  The
four render-blocking sheets gzip to **32.6 KB** total and nginx already
serves `text/css` gzipped, so this saves ~4 KB on the wire per route.
The real cost is CPU, and CSS is the smallest part of it — measured on
a 6× throttled mobile CPU:

| | script | layout | style recalc |
|---|---|---|---|
| `/` | 1301ms | 310ms | 255ms |
| `/rankings` | 1829ms | 417ms | 321ms |

That is why this stopped at one clean extraction rather than
restructuring 7,200 lines.  Remaining movable families, all
single-owner and mixed-free, ~32 KB combined: scouting / portfolio /
pmm / ticker (terminal components), edge (`/rankings`), watchlist, tc.
The splitter and the pixel-diff harness make it mechanical.

### Rankings: the board freeze, and why it is not virtualized

Measured first, on `/rankings` at 390×844:

| CPU | rows | scroll FPS |
|---|---|---|
| 1× | 229 (default) | 61 |
| 1× | 1,095 ("Show all") | 13 |
| 4× | 229 | 14 |
| 4× | 1,095 | 3 |
| 6× | 229 | 10 |
| 6× | 1,095 | 2 |

"Show all" takes the board from 200 to ~1,095 rows at 36 DOM nodes
each — 7,326 → 33,966 elements.  Committing that synchronously froze
the tab.  `useTransition` fixes the freeze:

| | control | with transition |
|---|---|---|
| 1× time-to-rows | 934ms | **473ms** |
| 1× longest frame gap | 600ms | **54ms** |
| 1× p95 frame gap | 600ms | **49ms** |
| 6× time-to-rows | 7511ms | **5479ms** |
| 6× longest frame gap | 5052ms | 3771ms |
| 6× p95 frame gap | 5052ms | **60ms** |

The p95 frame gap is the number that matters: 5052ms → 60ms at 6×
throttle means the page paints throughout instead of going dead, and
the button now says "Adding rows…" instead of looking broken.

**Scroll FPS is unchanged** — the transition does not reduce DOM size.
That needs real virtualization, and it is blocked on a prerequisite:

* `components/ui/VirtualList.jsx` **cannot be used here.** Its own
  docstring says div rows, not `<tr>`; the board is a real `<table>`.
* `content-visibility: auto` **does not work on table internals** —
  the containment spec excludes `table-row` / `table-row-group` from
  size containment.  Measured on both `tr` and `tbody`: scroll stayed
  at 2 FPS, settle unchanged.  Not a browser bug, a spec constraint.
* Row windowing with spacer `<tr>`s needs stable column widths, and the
  table is `table-layout: auto` with no `<colgroup>`.  Windowing it
  as-is makes columns jump while scrolling.

So the honest prerequisite is: **pin the board's column widths**
(measure once, emit a `colgroup`, switch to `table-layout: fixed`,
handle the responsive `ds-col-hide-*` columns), *then* window the rows.
That is architectural work on the app's most complex surface, not a
drive-by.

Also worth knowing: an **active filter bypasses `rowLimit` entirely**
(`hasActiveFilter ? ranked : ranked.slice(0, rowLimit)`), so a broad
filter renders every match with no cap and no transition.

*(Both open items here are closed: round 5 fixed the filter freeze with
`useDeferredValue` and landed `freezeColumnWidths`; round 6 capped the
filtered board.  Windowing is still not done — round 6's constraint
audit is the reason, and the checklist.)*

## 2026-07-30 round 5 — the board's two freeze paths, and stable columns

Two things round 4 left open, both on `/rankings`.

### The filter freeze

Round 4 fixed "Show all" with `useTransition` but left the other path
open: an active filter bypassed `rowLimit`, so choosing a broad
position rendered every match synchronously.  Same freeze, different
button.

The fix is `useDeferredValue` on the rendered rows, not on the filter
state — defer the *rows*, keep the input urgent, so typing and the
`<select>` stay responsive while the board catches up:

```js
const renderedRows = useDeferredValue(displayRows);
const rowsPending = renderedRows !== displayRows;
```

Measured at 6× throttle, 390×844, applying the broadest position
filter:

| | before | after |
|---|---|---|
| p95 frame gap | 5052ms | **23ms** |
| frames painted during the commit | 10 | **146** |

The tab paints throughout instead of going dead.  This handles the
*transition*; it does nothing about the steady state, which is what
round 6's cap addresses.

### `freezeColumnWidths`: the windowing prerequisite

Round 4 named pinned column widths as the prerequisite for row
windowing.  `components/ds/DataTable.jsx` grew a `freezeColumnWidths`
prop: measure the header cells once, emit a `<colgroup>`, switch to
`table-layout: fixed`.  Column drift while the board grows went from
116px / 47px to **0px / 0px** on the two widest columns.

Two bugs found on the way, both worth knowing because both looked
correct:

* **The obvious dependency array silently disables it.**  A layout
  effect with deps on `[freezeColumnWidths, frozen, columns]` never
  fires usefully when the first render has no rows: a passive effect
  keyed on `columnKeys` cleared `frozen` *after* the layout effect set
  it (layout effects run before passive ones in the same commit), and
  the deps never changed again.  The measuring effect deliberately has
  **no dependency array** and self-guards instead.
* **`<col>` maps to columns by POSITION, and `display:none` removes a
  column from the fixed-layout algorithm.**  Emitting a placeholder
  `<col>` for a responsively hidden column shifted every width after it
  onto the wrong column — at 390px the player-name column collapsed to
  0 and the position column inherited its 296px.  Only *visible*
  columns get a `<col>`.

Verified by full-page pixel diff of `/rankings` and `/finder` (same
board) at 1366×900 and 390×844, reviewed by the user, plus the vitest
suite.

## 2026-08-04 round 6 — cut the JS every route executes

### The finding that reordered the round

Round 4's throttled-CPU profile said script cost dominates (1301–1829ms
vs layout 310–417ms vs style recalc 255–321ms at 6×).  So the question
was how much JS each route executes — and the answer was hidden from
CI.  `frontend/scripts/check-bundle-sizes.mjs` filtered to
`static/chunks/app/`, which is the *page-specific slice only*:

| Route | real first-load JS | what the gate measured | coverage |
|---|---|---|---|
| `/league` | 718.4 KB | 174.0 KB | 24% |
| `/draft` | 682.7 KB | 130.2 KB | 19% |
| `/trade` | 638.2 KB | 82.6 KB | 13% |
| `/rankings` | 629.2 KB | 62.8 KB | 10% |
| `/settings` | 592.2 KB | 47.8 KB | 8% |

The root layout alone was **548.8 KB on every route, of which the gate
counted 4.3 KB**.  "Three routes within 2 KB of ceiling" — round 4's
stated priority — was a fact about the smaller 8–24% slice.  Caching
does not help: nginx already serves `_next/static` content-hashed and
`immutable`, so the cost is parse-and-execute, not download.  Only
shipping less JS moves it.

### INP — measured for the first time

The original brief asked for INP.  Rounds 1–5 never measured it; TBT
was covered (the sweep's `longTaskMs`) and INP was silently skipped.
Measured via `PerformanceObserver({type: "event"})` + `interactionId`,
with `long-animation-frame` for cause attribution.  Mobile 390×844,
medians of 3, Google's bands: good ≤200ms, poor >500ms.

| interaction | 1× | 4× before | 4× after | 6× before |
|---|---|---|---|---|
| `/rankings` sort a column | 88 | 384 | **328** | 504 |
| `/rankings` expand a row | 128 | 480 | 496 | 664 |
| `/rankings` open player popup | 144 | 488 | **304** | 800 |
| `/rankings` "Show all" | 64 | 264 | **232** | 472 |
| `/league` switch tab (1366px) | 24 | 48 | 48 | 72 |
| `/` open nav menu (1366px) | 32 | 56 | 56 | 80 |

On a **filtered** board — the case the row cap targets — the change is
larger, because the interaction no longer runs against 632 rows:

| interaction (4×, filtered) | before | after |
|---|---|---|
| sort a column | 840 | **384** |
| expand a row | 992 | **480** |
| open player popup | 584 | **280** |

All three were "poor" (>500ms); none is now.  LoAF attributed the
blocking time to the framework chunk — React reconciliation over the
board's DOM, not app logic — which is why DOM size, not app code, was
the lever.

### What changed

Seven commits, each independently measurable:

1. **`"sideEffects": ["*.css"]` in `frontend/package.json`.**  There was
   no `sideEffects` field, so every barrel (`components/ds/index.js`,
   47 importers; `components/ui/index.js`, 29) was only weakly
   tree-shakeable.  **Not a bare `false`** — CSS imports are side
   effects by definition (`app/layout.jsx` imports `./globals.css`
   purely for the import), and `false` invites the bundler to drop them
   and ship an unstyled app.  The `//sideEffects` key in
   `package.json` records that.
2. **`PlayerPopup` + `CommandPalette` out of the root layout** via
   `dynamic(..., {ssr: false})`.  Both were statically imported by
   `AppShell.jsx` and gated by booleans at their render sites;
   `PlayerPopup` is the largest component in the repo (48.3 KB) and
   statically pulls `PlayerRankHistoryChart`.  **The render gates had to
   move too** — `dynamic()` fetches its chunk when the component
   *renders*, so `privateDataEnabled && popupRow && …` is what actually
   defers it.  On `/league`, `privateDataEnabled` is false, so all
   69.2 KB was provably unreachable there already.
3. **The 21 `/league` sections behind `dynamic()`.**  `LeagueClient.jsx`
   imported all of them statically and rendered exactly one.  The
   default tab stays statically imported so the landing view has no
   loading flash.  Composes with round 4's per-section SSR: the code for
   a tab and the data for a tab now both arrive on open.
4. **The bundle gate reports first-load JS.**  Added a
   `[first-load N KB]` column and a root-layout header line.  Reported,
   not budgeted — the per-page budgets remain the right gate for "did
   this feature bloat its own route", but they cannot see the shared
   graph, which is how it reached 548 KB unnoticed.
5. **Filtered board results are capped**, the way unfiltered ones
   already were — see below.
6. **Dead code deleted**: five `components/ui/` modules with zero
   consumers (`MobileSheet`, `FilterBar`, `VirtualList`,
   `ValueBandBadge`, `TierDivider`), two orphaned `/league` sections,
   and `react-markdown`, an entirely unused dependency whose
   unified/remark/rehype tree was one careless import from a bundle.
7. **`/trade`'s collapsed "Second opinions" panel and `/rankings`'
   methodology charts** behind `dynamic()`.  This needed a change to
   `CollapsiblePanel`: the `hidden` attribute still **mounts** children,
   so a `dynamic()` import inside a collapsed panel fetches its chunk
   immediately and the split buys nothing.  Hence
   `mountCollapsedChildren={false}` — opt-in, because skipping the mount
   is a real behaviour change (children never run effects or fetch until
   first open), right for inert charts and wrong for anything that must
   be warm.

### Result: real first-load JS

```
ROOT LAYOUT (every route): 548.8 -> 463.9 KB   (-84.9 on every one of 90 routes)

route                before    after     delta     pct
/league               718.4    503.1    -215.3  -30.0%
/draft                682.7    615.5     -67.2   -9.8%
/trade                638.2    558.8     -79.4  -12.4%
/rankings             629.2    580.8     -48.4   -7.7%
/                     622.3    564.6     -57.7   -9.3%
/settings             592.2    515.1     -77.1  -13.0%
/waivers              590.8    535.1     -55.7   -9.4%
```

Average −85.8 KB across the seven measured routes.

**Three page-specific budgets were bumped, and that is the interesting
part.**  `/rankings` 65→75, `/trade` 82→92, `/draft` 128→150 — they
went *over* their budgets **because of the improvement**: code that used
to sit in everyone's shared graph is now attributed to the routes that
actually use it.  Judged on the old number alone, an unambiguous win
looked like a regression.  That is the blind spot change 4 closes.
`/league` moved the other way and was **tightened 170→50**, since its
page slice fell 174→39 KB and a future
`import XSection from "./sections/…"` — the easy mistake, since it looks
like every other import — should trip CI rather than quietly put all 21
sections back.

### The row cap, and why windowing was not done

Round 4 named windowing as the fix and round 5 removed its stated
blocker (`freezeColumnWidths`).  A full constraint audit of
`DataTable.jsx` then found windowing is a much larger change than the
ledger implied.  Recorded as the checklist if it is ever revisited:

1. **There is no vertical scroll container.**  `maxHeight` has zero
   consumers and `.ds-table-wrap` sets `overflow-x: auto` with no
   height, so the board scrolls with the *document* and the sticky
   header is inert today.  Container-scroll windowing would make it live
   for the first time and nest a scroll region — a visible UX change.
2. **`nth-child(even)` zebra striping is positional CSS** (and its own
   comment says it is "doing tracking work, not decoration").  Windowing
   changes row parity every scroll frame, so stripes visibly invert
   while scrolling.  Fixing that means a data-driven class, which
   collides with `rowClassName` being caller-owned.
3. **Every interactive row is a tab stop**, as is every in-cell button.
   Windowing breaks tab continuity and destroys focus when the focused
   row unmounts; no roving-tabindex infrastructure exists.
4. **`renderBeforeRow` receives the slice index.**  Rankings' tier
   divider reads `renderedRows[i - 1]` and short-circuits on `i === 0`,
   so a window-local index emits dividers in the wrong places.
5. **jsdom has no layout** — `getBoundingClientRect()` is all zeros, so
   a height-driven window renders 0 rows and breaks ~25 unit tests.  It
   must degrade to full rendering when unmeasurable.
6. **E2E tripwire**: `tests/e2e/helpers/journey.js` polls until
   `rows.count() >= 50` (gating 7 tests) and `mobile-smoke.spec.js`
   asserts ≥50 rows at 390×844.  A viewport-sized window renders ~30–45
   — both fail.
7. `freezeColumnWidths` measures whatever window is mounted, so a long
   name at row 800 would clip; measurement must see worst-case content.
8. `aria-rowcount` / `aria-rowindex` do not exist and windowing requires
   them, including on caller-authored `<tr>`s the caller cannot index.
9. The variable-height expansion pattern is not rankings-only — bdvm
   roster capitals pairs `onRowClick` with `renderAfterRow` too.

The cap reaches the same target in ~10 lines.  `displayRows` is now
`ranked.slice(0, rowLimit)` unconditionally.  Three things moved with
it, without which this would be the dishonest version of the fix:

* **`hasMore` no longer excludes the filtered case**, so a filtered
  board never caps silently.
* **The count line stays truthful** — it reads "200 of 516 shown", the
  total is still stated, and the rest is one click away.
* **`rowLimit` resets when the filter changes**, or a user who clicked
  "Show all" once would keep an uncapped board forever and the fix would
  do nothing.

Round 5's `useDeferredValue` is untouched: it handles the transition,
this handles the steady state.

### Scroll FPS: measured, including where it still misses

390×844, mouse-wheel driven, rAF-sampled.  The `showall` row **is** the
pre-cap filtered behaviour exactly (a filter used to render every
match), so it doubles as the before column:

| CPU | default (200) | filtered (200) | filtered + one "Show more" (510) | "Show all" (632) |
|---|---|---|---|---|
| 1× | 58.9 | **60.1** | 48.0 | 39.5 |
| 4× | 36.0 | **29.2** | 14.5 | 8.8 |
| 6× | 22.9 | **19.9** | 9.1 | 5.6 |

Filtered scroll at 4× went **8.8 → 29.2 FPS** (p95 frame gap 182ms →
51ms) and at 1× **39.5 → 60.1**.

**Stated plainly: the Phase-4 target was ≥30 FPS at 4× and ≥50 at 1× on
the worst reachable board, and only part of that is met.**  Default and
filtered hit it at 1×; default hits it at 4× (36.0) and filtered lands
just under (29.2).  Once the user explicitly asks for more rows —
"Show more" or "Show all" — it is not met, and cannot be by a cap,
because those states exist precisely to defeat the cap.  Getting 500+
rows to 30 FPS is the windowing work above.

### Correction: the numbers above were measured on Next 15.5.22

Round 6 was measured, written up, and PR'd against Next **15.5.22**.  While
it was open, `main` gained #712 (Next **16.2.12**, built with `--webpack`)
and #703 (a bundle gate rewritten to resolve chunks from disk, because
Next 16 emits no manifest mapping an app-router page key to its chunks).
Merging `main` in changed the ground under every figure in this section.

Two consequences, both load-bearing:

* **The first-load table is a Next 15 measurement.**  The *direction* of
  every change holds — the same code is split the same way — but the
  absolute KB figures are not reproducible on the merged branch.  Re-measure
  before citing them.
* **`firstLoadChunks()` is gone**, and deliberately.  It read
  `manifest.pages["/layout"]`, which no longer exists.  The disk-derived
  substitute ("every `.js` sitting directly in `static/chunks/`") was
  implemented and measured, and it is *wrong*: a dynamic import emits its
  chunk there too, so the metric counts on-demand code as always-loaded.
  It scored round 6's own refactor as +213 KB shared while `/league`'s page
  slice fell 163.4 → 37.8 KB — an improvement reported as a regression,
  which is precisely the failure this section describes.  A number nothing
  can contradict is worse than no number, so the shared graph is left
  unmeasured until it can be measured truthfully.

So the blind spot round 6 identified is **real and still open**.  What
changed is that the first attempt at an instrument was retracted rather
than shipped wrong.

### The SSR duplication `dynamic()` caused, and what actually caught it

Phase 2 shipped a defect that no measurement in this document would have
found, and it is the most useful thing in this section.

`dynamic()` is `React.lazy`, which needs a Suspense boundary.  `AppShell`
had no local one, so the nearest ancestor was the App Router's — and
`{children}`, the entire page, renders inside it.  Every route's content
became deferred streaming content: emitted into React's `<div id="S:1">`
staging container, moved into place, and the staged copy left behind.
`/waivers` served **three `<main>` elements**: the shell's, the page's, and
a hidden second full copy of the page.

The duplicate had no client rects and never reached the accessibility tree.
It is invisible in a screenshot, in an a11y snapshot, and to a human
clicking around.  It is still duplicate DOM, duplicate element ids, and
every page's markup rendered twice — a regression in the exact dimension
the split existed to improve.

Measured on Next 16.2.12, `/waivers`:

| | checkboxes | `<main>` | `#S:1` |
|---|---|---|---|
| static imports | 1 | 2 | absent |
| `dynamic()` bare | 2 | 3 | **present** |
| `dynamic()` + local `<Suspense>` | 1 | 2 | absent |
| imperative `await import()` | 1 | 2 | absent |

`ssr: false` was a red herring — it reproduces with and without.  The fix
is the imperative-import idiom the repo already used
(`components/ScreenshotFab.jsx`): no lazy component, so no boundary exists
to enclose the page, and webpack still emits the separate chunk.  The
69 KB split is intact.

**What caught it was the E2E safety net, which does not run on PRs** — a
Playwright strict-mode violation ("resolved to 2 elements") in
`tests/e2e/specs/waivers-smoke.spec.js`.  `pr-validation.yml` runs pytest,
vitest and lint; it never opens a browser.  Every metric in this document
— CLS, LCP, INP, FPS, bundle size — was *unchanged* by a bug that rendered
every page twice.  Dispatch `e2e.yml` manually on any branch that touches
the shell.

### The same duplication is a pre-existing, app-wide race — measured

The table above says "clean" for the shipped fix, and that is true of the
**deterministic** failure `dynamic()` caused.  It is not true that the
duplicate never happens: the app has an ambient SSR-streaming race in
which React's `#S:1` staging copy is left behind, and it predates round 6.

Measured by loading a route repeatedly and counting how many loads show
two copies, against builds of `main` and of this branch on the same box,
same backend, same browser:

| route | needle | `main` | round-6 branch |
|---|---|---|---|
| `/arbitrage` | "Pick a team and scan" | 1/15 | 1/15 |
| `/waivers` | "Include rookies" | **1/45** | **1/45** |

Identical on both routes.  So:

* **What round 6 did wrong** was make an ambient ~2–7%-per-load race fire
  on *every* load of *every* route, by putting a lazy boundary around
  `{children}` in the root layout.  That is fixed.
* **What round 6 did not cause, and has not fixed**, is the underlying
  race.  `main` has it at the same rate.

Consequence for CI: `e2e.yml` is intermittently red on `main`'s own
defect.  `main`'s runs mostly pass because each spec navigates once;
`waivers-smoke.spec.js` and `journey-trade.spec.js` are simply the two
specs whose assertions are strict enough to notice.  Do not "fix" this by
loosening those locators — they are the only detector the repo has for a
class of bug that no performance metric in this document can see.

### Resolved 2026-08-05 — it was never "main's own defect"

The paragraph above is right that round 6 did not cause the ambient race
and wrong about whose defect it is.  It is **React 19.2's deferred
Suspense reveal**, read from the pinned `react-dom@19.2.8` source rather
than inferred:

```js
$RC = function (a, b) { ... a.previousSibling.data = "$~"; $RB.push(a, b);
  2 === $RB.length && ("number" !== typeof $RT
    ? requestAnimationFrame($RV.bind(null, $RB))
    : setTimeout($RV.bind(null, $RB), ...)) ... }
```

`$RC` no longer reveals; it marks the boundary `"$~"`, queues the pair,
and schedules `$RV` — rAF for the first reveal, thereafter a `setTimeout`
throttled to `$RT + 300 - now` (up to 2300ms in one window).  `$RV` is
the only thing that removes `<div hidden id="S:n">`.  A full copy of the
boundary is therefore **supposed** to be in the DOM for that window.  No
app-side change removes it, and no user can see it.

Measured locally against the E2E stack, chromium under
`Emulation.setCPUThrottlingRate` (a loaded CI runner by other means):

| | |
|---|---|
| boundary marker `"$~"` seen | 30/30 loads (unthrottled) |
| staging container present | 20/25 loads (8× throttle) |
| `<main>` == 3 **and** toggle resolving to 2 | **2/25** — the CI symptom |
| same loop after `awaitStreamSettled()` | **0/25** |

So the suite waits it out (`tests/e2e/helpers/journey.js`) rather than
treating it as a bug to fix in the app.  The locators stay strict, and
that still matters: a **permanent** duplicate — what round 6's
`dynamic()` produced, and what a service worker replaying a frozen
mid-stream document would produce — is a real defect, and those two
specs remain its only detector.  Verified by injecting one: the wait
returns immediately and the strict locator still fails.

### Regression check

25-route sweep plus 5-run medians on the volatile routes.  No CLS
regression: `/` 0.0910 → 0.0936, `/draft` 0.0682 → 0.0682, `/settings`
0.0710 → 0.0723 — all inside Google's "good" band, all within run
noise.  A single-run sweep showed `/draft` at 0.167 and
`/league/activity` LCP at 1460ms; both were outliers that vanished on
medians (0.0682 and 268ms), which is why single runs are not trusted
here.  1,647 frontend tests pass; the bundle gate exits 0.

One known tail: `/draft` hits ~0.18 in roughly 1 run in 5, attributed
to a `DIV.muted` block collapsing 361×166 → 0 at ~900ms.  Pre-existing,
not round 6's doing, and not yet fixed.

## 2026-08-05 — row windowing: BUILT, MEASURED, REVERTED

Planned item #2 ("the rankings board past the row cap") was implemented
in full and then backed out, because the measurement says its premise is
wrong. **Row count is not what makes the board scroll slowly.**

This section exists so nobody builds it a second time. The instrument
that produced the numbers is committed —
`frontend/scripts/measure-board-fps.mjs` — so every line below is
re-runnable rather than remembered.

### The premise, and the measurement that refutes it

This doc said: "Getting 500+ rows to 30 FPS is the windowing work",
i.e. only rendering fewer rows reaches the target. Measured on one
machine, one session, same harness, 3 runs each (median):

| board | rows | DOM nodes | FPS @1× |
|---|---|---|---|
| capped | 65 | 2,305 | **32.1** |
| "Show all", no window | 964 | 30,553 | **28.6** |
| "Show all", windowed | 964 | **3,763** | **30.9** |
| *control: trivial page* | — | 204 | **59.5** |

Read the first two rows together: a **15× increase in rows and a 13×
increase in DOM nodes costs about 11% of the frame rate.** Then read the
control: this machine renders a bare scrolling page at 59.5 FPS, so the
~30 the board sits at is not a hardware ceiling.

The board is ~30 FPS at *any* size. Whatever costs the other half of the
frame budget is **page-level, not row-level** — so windowing, which is
purely a row-count intervention, cannot fix it. It did exactly what it
promised (30,553 → 3,763 nodes, an 8× cut) and bought ~2 FPS.

### What was ruled out

Injected `!important` overrides on the live board, same scroll loop:

| suspect disabled | FPS |
|---|---|
| nothing (baseline) | 38.1 |
| `backdrop-filter` | 39.5 |
| `position: sticky` | 40.0 |
| `box-shadow` | 38.7 |

None of them. Note also the spread — this baseline read 38.1 where the
same board read 32.1 minutes earlier. **These FPS numbers carry roughly
20% run-to-run variance**, which is wide enough that the 28.6 / 30.9 /
32.1 trio should be treated as one number, not three. The 59.5 control
sits well outside that band, which is why the page-level conclusion
holds while finer distinctions do not.

### The second, independent reason it was reverted

Windowing makes the mounted row count stop tracking the board size, and
a journey spec legitimately depends on that. `journey-rankings.spec.js:81`
("position filter narrows the board to one position") counts rows before
and after filtering and asserts the count drops. Under windowing both
counts pin to the window size and the assertion fails — not because
filtering broke, but because a real user-visible behaviour stopped being
observable through the DOM.

That test could have been rewritten against `aria-rowcount`. It was not,
because doing so trades away a working detector to accommodate a change
that does not deliver its goal — and this doc has a standing rule against
loosening board assertions to make a change fit.

### If someone picks this up again

* **Do not start from row count.** Start by profiling what the page does
  per frame during a scroll — the answer is not in this table's size.
* The windowing implementation worked and is recoverable from this
  branch's history if the profile ever justifies it: opt-in `windowRows`
  prop, document-scroll, spacer rows, data-driven zebra parity,
  absolute-index callbacks, full-render fallback when geometry is
  unmeasurable (jsdom reports 0 and all 28 DataTable tests depend on it).
* One trap it hit, worth keeping: measure row height from a row the table
  itself renders (`data-ds-row`), never `tbody tr`. The first `tr` can be
  a caller-authored tier separator, and measuring one collapses the window
  to its floor.

### Also corrected here

The row counts in this doc are stale: "Show all" is **964 rows** today,
not the ~632 or ~1,095 quoted elsewhere, at ~32 DOM nodes per row.

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

Reordered after round 6.  Script cost still dominates on a throttled
mobile CPU (round 4's profile: **script 1301–1829ms, layout 310–417ms,
style recalc 255–321ms** at 6×), and round 6 took 85 KB off every route
without touching the largest single item on the list.

1. **The 337 KB React/Next framework baseline every route pays.**  Now
   the largest remaining item by a wide margin — 463.9 KB of the
   post-round-6 shared graph is framework, and it is a floor only
   because the client boundary sits at the root layout.  Moving it means
   server components, which is an architectural change and **out of
   scope by the user's decision**.  Round 6's first-load reporting makes
   it visible rather than invisible; listed here so the number is not
   mistaken for irreducible.
2. **Window the rankings board's rows** — the only way past 30 FPS with
   500+ rows on a 4× CPU.  Round 5 removed the stated blocker
   (`freezeColumnWidths`), but round 6's audit found nine further
   constraints; the checklist is in the round-6 section above and should
   be worked through before any attempt.  Round 6's cap makes the
   *default* and *filtered* boards fast, so this now only affects users
   who explicitly click "Show more" / "Show all".
3. **Stop non-data routes hydrating the player pipeline.**
   `AppShell.jsx` gates `useDynastyData()` behind
   `PUBLIC_ONLY_ROUTE_PREFIXES`, currently `["/league"]` only.  `/login`
   and `/more` still fetch the contract and materialize ~1,100 rows.
   Audit `/settings`, `/admin`, `/design` individually — a wrong entry
   breaks a page rather than slowing it.
4. **`/draft`'s CLS tail.**  ~1 run in 5 hits 0.18 (median 0.068), from
   a `DIV.muted` block collapsing 361×166 → 0 at ~900ms.  Same
   height-reservation shape as the round-4 fixes.
5. **Extract and split `/draft`'s modals.**  `DraftModal`,
   `DraftReviewPanel` and `DraftGlossary` (~930 lines) live *inside* the
   5,185-line page module, so webpack cannot split them; they need
   extraction to `_`-prefixed siblings first.  Deferred from round 6 as
   the most invasive edit available.  Same for `/settings`'
   `PushNotificationToggle` / `CustomAlertsConfigurator` (~15 KB), which
   render unconditionally and need viewport-triggered mounting rather
   than a boolean gate.
6. **The remaining CSS families** (~32 KB, single-owner, mixed-free):
   scouting / portfolio / pmm / ticker / edge / watchlist / tc.  The
   splitter and pixel-diff harness from round 4 make it mechanical, but
   they gzip to ~32 KB total and nginx already gzips `text/css` — small
   win.
7. **`app/sitemap.js` still fetches the 2 MB aggregate contract**, so it
   keeps tripping Next's Data Cache size limit. Crawler-only path.
8. **Navigation** — ensure route transitions reuse cached data instead
   of refetching/recomputing.
9. **Client revalidation** — blocked on the auth-scoping work above.

Not on this list, and deliberately: **`Icon` tree-shaking**
(`components/ds/Icon.jsx` holds every glyph in one object literal looked
up at runtime by `name`, with `ICON_NAMES = Object.keys(PATHS)` hard-
referencing the map — structurally un-shakeable, as
`glyph-chevron-down.jsx` documents) and **consolidating `components/ui/`
onto `components/ds/`** (a migration, not a perf fix, though finishing
it would drop the whole `ui` barrel off `/league`).

## Validation notes

Backend changes here are covered by pytest (`tests/api`). Frontend proxy
changes are `node --check`-clean and rely on the client's existing
raw/wrapped normalization, but still need a browser/E2E pass
(`npm run regression`) against a running stack before rollout — the
vitest/Playwright toolchain isn't runnable in the current CI sandbox.
