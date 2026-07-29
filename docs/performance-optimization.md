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

Reordered after round 4, because the throttled-CPU numbers say plainly
where the remaining time goes.  On a 6× throttled mobile CPU the budget
is **script 1301–1829ms, layout 310–417ms, style recalc 255–321ms** —
script is 4–6× everything else, so JS is the whole ballgame now that
payloads and layout shift are handled.

1. **Cut first-paint JS on the heaviest routes** (`/league` 169 KB,
   `/draft` 126 KB, `/trade` 78 KB — all within ~2 KB of their budgets).
   This is the single biggest remaining lever on slow devices.
2. **Pin the rankings board's column widths, then window its rows.**
   Prerequisite, not optional: the table is `table-layout: auto` with no
   `colgroup`, so spacer-row windowing makes columns jump.
   `content-visibility` is ruled out (spec excludes table internals) and
   `VirtualList.jsx` is div-only. Payoff: `/rankings` scrolls at 2–3 FPS
   with 1,095 rows on a 4–6× throttled CPU, and 10–14 FPS even at the
   default 200.
3. **Cap filtered results the way unfiltered ones are capped.** An
   active filter bypasses `rowLimit` entirely, so a broad filter renders
   every match with no cap and no transition — the same freeze "Show
   all" had before round 4.
4. **The remaining CSS families** (~32 KB, single-owner, mixed-free):
   scouting / portfolio / pmm / ticker / edge / watchlist / tc. The
   splitter and pixel-diff harness from round 4 make it mechanical.
   Small win — see round 4's scope note on why CSS is not the
   bottleneck.
5. **`app/sitemap.js` still fetches the 2 MB aggregate contract**, so it
   keeps tripping Next's Data Cache size limit. Crawler-only path.
6. **Navigation** — ensure route transitions reuse cached data instead
   of refetching/recomputing.
7. **Client revalidation** — blocked on the auth-scoping work above.

## Validation notes

Backend changes here are covered by pytest (`tests/api`). Frontend proxy
changes are `node --check`-clean and rely on the client's existing
raw/wrapped normalization, but still need a browser/E2E pass
(`npm run regression`) against a running stack before rollout — the
vitest/Playwright toolchain isn't runnable in the current CI sandbox.
